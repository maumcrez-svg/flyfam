"""The request ledger and its caps, persisted before any socket is opened.

docs/SPEC.md D10 addendum 5. Three caps apply at once: a wave cap, a per
process-run cap and a per calendar-day cap. The day and wave totals live in
``experiments/d10/rpc_ledger.json`` so a restart does not reset them; the run
cap is per :class:`RequestLedger` instance.

**Attempts, not successes.** Chainstack bills the call, not the answer, so an
error counts. **Archive weighting**: Chainstack charges reads 127 or more
blocks behind the tip at two request units instead of one
(docs.chainstack.com/docs/request-units, verified 2026-09-12), so the ledger
records *units* beside *attempts* and the caps apply to attempts, with the
unit total reported next to them.

Reaching any cap raises :class:`BudgetStop` after the ledger is flushed. There
is no second provider to fall back to and nothing here may add one.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

#: A read this many blocks or more behind the head known at call time is
#: billed as an archive request (two units).
ARCHIVE_DEPTH = 127

LEDGER_VERSION = "d10-rpc-ledger-1"

#: addendum 5, verbatim. These are the **Chainstack** caps and they do not
#: move: the D11-001 loopback caps are a separate registered number carried by
#: ``experiments/d11/d11_001.json`` and passed in explicitly.
WAVE_CAP = 10_000
RUN_CAP = 5_000
DAY_CAP = 10_000

#: D11-001 addendum 4. Hosts that are this machine and nothing else. A request
#: to any of them never leaves the loopback interface, costs no provider unit
#: and is billed by nobody, so it is counted in its own ledger under its own
#: caps rather than against the remote wave.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})

LOOPBACK = "loopback"
REMOTE = "remote"
#: the default scope: classify and record, refuse nothing. Every D5-D10 ledger
#: is opened this way and behaves exactly as it always did.
ANY = "any"
SCOPES = (ANY, LOOPBACK, REMOTE)

#: Raised as a :class:`BudgetStop` code when a ledger opened in ``loopback``
#: scope is handed a remote endpoint without ``--allow-remote``.
REMOTE_REFUSED = "RPC_REMOTE_REFUSED"


def endpoint_class(url: str) -> str:
    """``"loopback"`` or ``"remote"`` for one endpoint URL, by host alone.

    D11-001 addendum 4. The classification is made from the URL's host and
    from nothing else — not from a flag, not from a label an artifact carries,
    not from the port. ``127.0.0.1``, ``localhost`` and ``::1`` are this
    machine; everything else, including a LAN address and including a host
    that happens to resolve to a loopback address, is remote. Resolving names
    to decide would make the answer depend on a DNS reply, and a wave that
    must never open a socket to anything but ``127.0.0.1`` cannot have its
    safety rule decided by a network lookup.
    """
    host = (urlsplit(str(url)).hostname or "").strip().lower()
    return LOOPBACK if host in LOOPBACK_HOSTS else REMOTE


class BudgetStop(RuntimeError):
    """A cap was reached, or the provider halted us. The ledger is persisted."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(code if not detail else f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _utc_day(now=None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")


def _atomic_write_json(path: Path, payload: dict) -> None:
    """Write-temp-rename with an fsync of both the file and its directory.

    The same discipline as :func:`flytrade.records.write_pending`, so a kill
    mid-write leaves either the old ledger or the new one, never a half file.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    os.close(fd)
    tmp = Path(tmp)
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        dfd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


class RequestLedger:
    """Counts every attempt, by method, by day and by run, and persists it.

    ``run_id`` names the process run. ``path`` is the JSON ledger; it is read
    at construction if it exists, so the wave and day totals survive restarts.
    """

    def __init__(self, path, *, run_id: str, wave_cap: int = WAVE_CAP,
                 run_cap: int = RUN_CAP, day_cap: int = DAY_CAP, now=None,
                 scope: str = ANY, allow_remote: bool = True):
        self.path = Path(path)
        self.run_id = str(run_id)
        self.wave_cap = int(wave_cap)
        self.run_cap = int(run_cap)
        self.day_cap = int(day_cap)
        if str(scope) not in SCOPES:
            raise ValueError(f"scope must be one of {SCOPES}, got {scope!r}")
        #: D11-001 addendum 4. ``"loopback"`` is the D11-001 wave's scope: this
        #: ledger's file, counters and caps are its own, and it refuses a
        #: remote endpoint unless ``allow_remote`` was passed. ``"any"`` — the
        #: default — is every D5-D10 ledger, unchanged.
        self.scope = str(scope)
        self.allow_remote = bool(allow_remote)
        self.endpoint_class: str | None = None
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.state = self._load()
        self.run_attempts = 0

    # ---------------------------------------------------------------- state
    def _load(self) -> dict:
        if self.path.exists():
            state = json.loads(self.path.read_text(encoding="utf-8"))
            if state.get("version") != LEDGER_VERSION:
                raise BudgetStop("RPC_LEDGER_VERSION",
                                 f"{state.get('version')!r} != {LEDGER_VERSION!r}")
            return state
        return {
            "version": LEDGER_VERSION,
            "caps": {"wave": self.wave_cap, "run": self.run_cap, "day": self.day_cap},
            "attempts": 0,
            "units": 0,
            "errors": 0,
            "by_method": {},
            "by_day": {},
            "by_run": {},
            "halted": None,
        }

    def flush(self) -> None:
        self.state["caps"] = {"wave": self.wave_cap, "run": self.run_cap,
                              "day": self.day_cap}
        self.state["scope"] = self.scope
        if self.endpoint_class is not None:
            self.state["endpoint_class"] = self.endpoint_class
        _atomic_write_json(self.path, self.state)

    # ------------------------------------------------------------ endpoint
    def admit(self, url: str) -> str:
        """Classify the endpoint this ledger is about to pay for, or refuse it.

        D11-001 addendum 4, and it bites **before a socket is opened**: the
        client calls this when it is constructed, so a remote URL handed to a
        loopback-scoped ledger fails at construction rather than on the first
        request. ``--allow-remote`` is the only way past it, the D11-001 wave
        never passes it, and the wave's report states the remote count, which
        must be zero.

        Returns the class, so a caller can record what it got rather than
        infer it.
        """
        kind = endpoint_class(url)
        if self.scope == LOOPBACK and kind != LOOPBACK and not self.allow_remote:
            raise BudgetStop(
                REMOTE_REFUSED,
                f"a {kind} endpoint was handed to a loopback-scoped ledger "
                f"({self.path.name}) and --allow-remote was not passed")
        if self.scope == REMOTE and kind != REMOTE and not self.allow_remote:
            raise BudgetStop(
                REMOTE_REFUSED,
                f"a {kind} endpoint was handed to a remote-scoped ledger "
                f"({self.path.name})")
        self.endpoint_class = kind
        return kind

    # ----------------------------------------------------------- accounting
    @property
    def attempts(self) -> int:
        return int(self.state["attempts"])

    @property
    def units(self) -> int:
        return int(self.state["units"])

    def day_attempts(self, day: str | None = None) -> int:
        day = day or _utc_day(self._now())
        return int(self.state["by_day"].get(day, {}).get("attempts", 0))

    def remaining(self) -> dict:
        return {
            "wave": self.wave_cap - self.attempts,
            "run": self.run_cap - self.run_attempts,
            "day": self.day_cap - self.day_attempts(),
        }

    def as_dict(self) -> dict:
        """What this ledger is, for a report. Never the endpoint itself."""
        return {"path": str(self.path), "run_id": self.run_id,
                "scope": self.scope, "allow_remote": self.allow_remote,
                "endpoint_class": self.endpoint_class,
                "caps": {"wave": self.wave_cap, "run": self.run_cap,
                         "day": self.day_cap},
                "attempts": self.attempts, "units": self.units,
                "errors": int(self.state.get("errors", 0)),
                "run_attempts": self.run_attempts,
                "by_method": dict(self.state.get("by_method", {})),
                "halted": self.halted()}

    def halted(self) -> dict | None:
        return self.state.get("halted")

    def reserve(self, method: str) -> None:
        """Refuse the call *before* the socket is opened if any cap is spent."""
        if self.state.get("halted"):
            raise BudgetStop("RPC_QUOTA_STOP", str(self.state["halted"].get("reason")))
        if self.run_attempts >= self.run_cap:
            self.flush()
            raise BudgetStop("RPC_BUDGET_STOP", f"run cap {self.run_cap}")
        if self.attempts >= self.wave_cap:
            self.flush()
            raise BudgetStop("RPC_BUDGET_STOP", f"wave cap {self.wave_cap}")
        if self.day_attempts() >= self.day_cap:
            self.flush()
            raise BudgetStop("RPC_BUDGET_STOP", f"day cap {self.day_cap}")

    def record(self, method: str, *, units: int, error: str | None = None) -> None:
        """One attempt happened. ``units`` is 1, or 2 for an archive read."""
        day = _utc_day(self._now())
        self.state["attempts"] += 1
        self.state["units"] += int(units)
        self.run_attempts += 1
        if error:
            self.state["errors"] += 1
        for bucket, key in (("by_method", method), ("by_day", day),
                            ("by_run", self.run_id)):
            entry = self.state[bucket].setdefault(
                key, {"attempts": 0, "units": 0, "errors": 0})
            entry["attempts"] += 1
            entry["units"] += int(units)
            if error:
                entry["errors"] += 1
                entry.setdefault("last_error", None)
                entry["last_error"] = error
        self.flush()

    def halt(self, reason: str) -> None:
        """The provider refused us. Persist it; a later run will not retry."""
        self.state["halted"] = {
            "reason": reason,
            "at": self._now().isoformat().replace("+00:00", "Z"),
            "run_id": self.run_id,
        }
        self.flush()

    def clear_halt(self, why: str) -> dict:
        """Lift a halt, leaving an audit entry. Operator action, never automatic.

        Nothing in the collector or the loop calls this: a halt exists so a
        refusing provider is not hammered, and a program that could lift its
        own halt would not be a cap. It is here for the one case a human can
        judge and a regex cannot — a halt recorded without the evidence needed
        to tell a spent quota from a per-request result limit. The cleared
        halt stays in the ledger under ``cleared_halts`` forever.
        """
        halted = self.state.get("halted")
        if halted is None:
            return {}
        entry = {**halted, "cleared_at": self._now().isoformat().replace("+00:00", "Z"),
                 "cleared_by": self.run_id, "why": str(why)}
        self.state.setdefault("cleared_halts", []).append(entry)
        self.state["halted"] = None
        self.flush()
        return entry


__all__ = ["ARCHIVE_DEPTH", "LEDGER_VERSION", "WAVE_CAP", "RUN_CAP", "DAY_CAP",
           "LOOPBACK_HOSTS", "LOOPBACK", "REMOTE", "ANY", "SCOPES",
           "REMOTE_REFUSED", "endpoint_class", "BudgetStop", "RequestLedger",
           "archive_units", "_atomic_write_json"]


def archive_units(queried_block: int | None, known_head: int | None) -> int:
    """Two units when the read is :data:`ARCHIVE_DEPTH` blocks or more behind.

    ``None`` on either side means we cannot tell, and an unknown depth is
    counted at one unit rather than guessed at two — the cap is on attempts,
    and the unit total is reported as what it is.
    """
    if queried_block is None or known_head is None:
        return 1
    return 2 if known_head - queried_block >= ARCHIVE_DEPTH else 1
