"""The Pons decision loop: one brain, one position, many tokens.

docs/SPEC.md D10 addendum 11. This is a **new driver**, not a reuse of
``experiments/historical/run.py``: that loop is welded to minute bars,
sessions and ``horizon.locate``, and a token ninety seconds old has none of
those. What *is* reused, unchanged, is everything that matters — the brain and
its runner, the k = 8 readout, ``comparison_v1``, the decoder, the credit
assigner and its normalised update, the journal, the checkpoint, the recovery
rule and the account's three-way reconciliation.

Per tick (30 s of chain time):

1. the driver advances the event stream to the cutoff and the tapes with it;
2. every launch seen gets a ``DISCOVERY`` record, admitted or not;
3. admission (``admission_v1``) and round-robin rotation give ≤ 6 candidates;
4. they go through :class:`flytrade.readout.ComparisonReadoutPolicy` at k = 8
   and the existing decoder;
5. one ``ROUND`` record carries every candidate, the tallies, the open
   position's **mark** and the chosen token's context;
6. the execution policy acts: BUY opens, a decoded SELL while holding is
   ``RejectReason.FIXED_HOLD`` and closes nothing, and the horizon closes with
   ``CloseReason.POLICY_CLOSE_FIXED_HOLD``;
7. settlement happens only when the **entry and exit blocks are both
   confirmed**; until then the episode is ``PENDING_CONFIRMATION`` and no
   reward exists. A curve that completed onto the unsupported route, or a
   horizon past the data, is ``UNRESOLVED`` — the exposure is retained and
   nothing is taught.

The mark is a mark. It is written into every tick while a position is open and
it never reaches reinforcement; the learning rule takes the settled net
outcome and nothing else.

**Modes.** ``REPLAY_PAPER`` and ``LIVE_PAPER`` share every line of this class —
the collector, the confirmation rule, the settlement, the records — and differ
only in their *driver*: where the events come from and how the clock advances.
:class:`ReplayDriver` reads a recorded window on a virtual clock;
:class:`LiveDriver` polls the endpoint on the wall clock and stops at the first
of four declared limits. Nothing below this line knows which one it has.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .. import decoder as D
from .. import execution as X
from .. import readout as RO
from .. import records as REC
from .. import runner as R
from ..market import Universe
from . import paper as PAPER
from .admission import AdmissionPolicy, Candidate
from .budget import BudgetStop
from .collector import BlockClock, Finality, _int, is_confirmed
from .context import MIN_AGE_S, PONS_FEATURES, TokenTape
from .curve import CurveState
from .encoder import SensoryEncoder
from .manifest import NATIVE_QUOTE
from .reinforcement import (ABSOLUTE_PROFIT_V1, RELATIVE_COHORT_V1,
                            reinforcement_for)
from .rpc import RpcError
from .seed import (LAUNCH_SEED, creator_tax_from_trade, matches_pinned_config,
                   seed_state)

VERSION = "pons_loop_v1"

MODE_REPLAY = "REPLAY_PAPER"
MODE_LIVE = "LIVE_PAPER"
MODES = (MODE_REPLAY, MODE_LIVE)

LEARN = "LEARN"
FROZEN = "FROZEN"
LEARNING_MODES = (LEARN, FROZEN)

VENUE = "PONS"
CHAIN_ID = 4663

#: Addendum 9 / amendment §9: one decision every thirty seconds of chain time.
CADENCE_S = 30

#: Addendum 6: a curve is a candidate while it is this young, or while held.
TRACK_SECONDS = 3_600

TRADE_KINDS = ("CurveBuy", "CurveSell")

#: Addendum 15: a connection is not fresh data. The health block reports
#: ``fresh: false`` whenever the last confirmed block is older than this.
FRESH_SECONDS = 120

#: D11-001 addendum 6: the rejection reason of a decoded BUY refused because
#: its settlement window would cross the partition boundary. It is a policy
#: reject like ``FIXED_HOLD`` — the decision is recorded, the order is not
#: placed — and it is its own name so it never pools with a market refusal.
PARTITION_BOUNDARY = "PARTITION_BOUNDARY"


# --------------------------------------------------------------------------
# Drivers: where the events and the clock come from
# --------------------------------------------------------------------------
class ReplayDriver:
    """Chronological recorded Pons events on a virtual clock. ``REPLAY_PAPER``.

    The dataset is the output of :meth:`flytrade.pons.collector.Collector
    .backfill_window` — the same normalisation path the live collector uses —
    so replay and live differ in their transport and in nothing else.

    Confirmation in replay is the *same rule* evaluated against the head the
    collection recorded: the window ends at the ``safe`` block, so every block
    in it satisfies both the depth rule and the ``safe`` rule, and the check is
    exercised rather than skipped.
    """

    mode = MODE_REPLAY

    def __init__(self, directory, *, finality: Finality):
        self.directory = Path(directory)
        self.manifest = json.loads((self.directory / "MANIFEST.json").read_text())
        self.initial_states = json.loads(
            (self.directory / "initial_states.json").read_text())
        self.discovery = json.loads((self.directory / "discovery.json").read_text())
        self.finality = finality
        headers = [json.loads(line) for line in
                   (self.directory / "headers.jsonl").read_text().splitlines()
                   if line.strip()]
        self.clock = BlockClock(
            headers,
            interval_s=float(self.manifest["window"]["median_block_interval_s"]),
            grid_blocks=int(self.manifest["header_grid_blocks"]))
        self.events = self._load_events()
        self.cursor = 0
        window = self.manifest["window"]
        self.first_block = int(window["first_block"])
        self.last_block = int(window["last_block"])
        self.admission_last_block = int(window["admission_last_block"])
        self.safe_block = int(window["safe_block"])
        self.head_block = self.safe_block
        times = [e["block_timestamp"] for e in self.events]
        self.first_ts = min(times) if times else 0
        self.last_ts = max(times) if times else 0
        #: the last chain second the dataset covers, for every token alike. A
        #: curve that stopped trading is still covered until here.
        self.coverage_end_ts = min(self.last_ts, self.clock.last_ts)
        self.label = self.manifest["dataset"]

    def _load_events(self) -> list[dict]:
        out = []
        with open(self.directory / "events.jsonl", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                event = json.loads(line)
                if event.get("kind") == "ORPHANED":
                    continue
                out.append(event)
        out.sort(key=lambda e: (e["block_number"], e["tx_index"], e["log_index"]))
        return out

    def advance(self, cutoff: int):
        """Every event at or before ``cutoff`` that has not been handed over yet."""
        out = []
        while (self.cursor < len(self.events)
               and self.events[self.cursor]["block_timestamp"] <= int(cutoff)):
            out.append(self.events[self.cursor])
            self.cursor += 1
        return out

    def ticks(self, cadence: int = CADENCE_S):
        """The virtual clock: 30 s of chain time per step, over the window."""
        cutoff = self.first_ts
        while cutoff <= self.last_ts:
            yield int(cutoff)
            cutoff += int(cadence)

    @property
    def block_clock(self):
        return self.clock

    def confirm(self, block_number: int) -> dict:
        confirmed = is_confirmed(int(block_number), head=self.head_block,
                                 finality=self.finality,
                                 safe_block=self.safe_block)
        return {"block_number": int(block_number), "confirmed": bool(confirmed),
                "head": self.head_block, "safe_block": self.safe_block,
                "confirm_depth": self.finality.confirm_depth,
                "source": "recorded dataset head (no request)"}

    def as_dict(self) -> dict:
        return {"mode": self.mode, "dataset": self.label,
                "directory": str(self.directory),
                "events": len(self.events),
                "first_block": self.first_block, "last_block": self.last_block,
                "first_ts": self.first_ts, "last_ts": self.last_ts,
                "admission_last_block": self.admission_last_block,
                "coverage_end_ts": self.coverage_end_ts,
                "safe_block": self.safe_block}


#: Addendum 15: the live exercise stops at the first of these, and at nothing
#: else. There is no retry, no fallback and no second provider anywhere below.
LIVE_MAX_SECONDS = 3_600
LIVE_MAX_REQUESTS = 3_000
LIVE_STOP_FILE = "stop"

#: Live admission never closes on a block number the way the replay window's
#: does: there is no end of data to keep a horizon inside. A position still
#: open when the run stops is retained and reported open, never closed at the
#: last mark.
ADMISSION_ALWAYS_OPEN = 1 << 62

#: An `eth_call` for ``creatorTaxBps()`` is the declared fallback when the
#: arithmetic does not pin the tax (``flytrade.pons.seed``). It is bounded, so
#: a window full of unpinnable launches cannot spend the run's budget on them.
MAX_TAX_READS = 50


@dataclass
class LiveLimits:
    """The finite stop limits of addendum 15, declared before the run."""

    max_seconds: int = LIVE_MAX_SECONDS
    max_requests: int = LIVE_MAX_REQUESTS
    #: attempts kept back from ``max_requests`` so the stop is ours and clean
    #: rather than a :class:`BudgetStop` raised in the middle of a tick.
    reserve_requests: int = 30
    #: addendum 6: at most the last hour of blocks, so tracked curves have
    #: history at the first tick. Bounded again by its own request and wall
    #: clock sub-caps, both inside the run's.
    backfill_seconds: int = 3_600
    backfill_requests: int = 1_200
    backfill_wall_seconds: int = 900
    stop_file: str | None = None

    def as_dict(self) -> dict:
        return {"max_seconds": self.max_seconds,
                "max_requests": self.max_requests,
                "reserve_requests": self.reserve_requests,
                "backfill_seconds": self.backfill_seconds,
                "backfill_requests": self.backfill_requests,
                "backfill_wall_seconds": self.backfill_wall_seconds,
                "stop_file": None if self.stop_file is None else str(self.stop_file),
                "rule": ("60 minutes wall clock, 3,000 requests, the stop file "
                         "flag or SIGTERM — whichever comes first — then a "
                         "clean stop with the cursor, the ledger, the journal "
                         "and the checkpoint persisted")}


class LiveDriver:
    """``LIVE_PAPER``: the wall clock, the collector, and four ways to stop.

    The loop above never asks where an event came from, so this class is the
    whole of the difference between a replay and a live run:

    * :meth:`ticks` is a **wall-clock** generator. It sleeps to the next
      cadence boundary, polls :meth:`flytrade.pons.collector.Collector.tick`
      (head, factory logs, tracked-curve logs, normalise, persist), and yields
      the cutoff — **the timestamp of the latest block seen**. It returns, and
      with it the run ends cleanly, at the first of: the wall-clock limit, the
      request cap, the ``stop`` file flag, ``SIGTERM``, a budget stop or an
      endpoint error. There is no retry and no fallback.
    * :meth:`advance` hands over the normalised events at or before that
      cutoff, from the same :class:`~flytrade.pons.collector.Normaliser` the
      replay dataset was written with.
    * :meth:`confirm` is the collector's own confirmation rule: the depth rule,
      the ``safe`` rule when the endpoint answers the tag, and the grid-anchor
      hash re-read a live chain needs and a recorded one does not.

    **Two live-only mechanics, declared.**

    *The fill anchor.* The replay dataset ends at a known block, so a fill at
    ``cutoff + latency`` is always inside it. Live, that instant is two seconds
    in the future of the head we just read, and a clock that does not reach it
    would refuse every entry as ``COVERAGE``. So after each poll the driver
    waits until the wall clock passes ``cutoff + latency`` and reads **one**
    header — the fill anchor — which becomes the block clock's last point and
    the tapes' coverage end. No event between the cutoff and the anchor is
    fetched or applied, so the state a fill is priced at is exactly the state
    the decision could reach: the same rule the replay run used, where the
    driver also hands over nothing past the cutoff.

    *Holding a launch until its state is known.* A tape needs the curve's
    launch state, and the creator tax is recoverable from the launch's first
    trade with no request at all (:mod:`flytrade.pons.seed`, measured on 546 of
    546 donor calibrations). A launch on the pinned config is therefore held
    back until a trade pins its tax — usually the same tick — and released with
    its own curve events, in chain order, behind it. A launch that is still
    unpinned 60 s later falls back to one ``eth_call``, bounded by
    :data:`MAX_TAX_READS`, and a launch with no trade at all is released with
    no state: it is recorded as a discovery that was never followed, which is
    what it is, and it could never have been admitted (admission needs three
    trades). Nothing is invented and no launch is dropped from the census.
    """

    mode = MODE_LIVE

    def __init__(self, collector, *, finality: Finality,
                 limits: LiveLimits | None = None, label: str = "pons-live",
                 latency_s: int = 2, quote_asset: str = NATIVE_QUOTE,
                 now=None, sleep=None, log=None, on_tick=None):
        self.collector = collector
        self.finality = finality
        self.limits = limits or LiveLimits()
        self.label = str(label)
        self.latency_s = int(latency_s)
        self.quote_asset = str(quote_asset).lower()
        self._now = now or time.time
        self._sleep = sleep or time.sleep
        self.log = log or (lambda *a, **kw: None)
        self.on_tick = on_tick
        #: what :meth:`PonsLoop._open_tape` reads; filled as launches resolve
        self.initial_states: dict[str, dict] = {}
        self.admission_last_block = ADMISSION_ALWAYS_OPEN
        self.coverage_end_ts: int | None = None
        self.first_ts = 0
        self.last_ts = 0
        self.pending: list[dict] = []
        self.started_at: float | None = None
        self.deadline: float | None = None
        self.stopped: str | None = None
        self.stop_detail: str = ""
        self.signalled: str | None = None
        self.ticks_done = 0
        self.launches_seen = 0
        self.tax_reads = 0
        self.reorgs = 0
        self.errors: list[dict] = []
        self.lag_blocks: list[int] = []
        self.lag_seconds: list[int] = []
        self.cutoff_ages: list[int] = []
        self.head_track: list[dict] = []
        self.backfill: dict = {}
        self.anchor: dict | None = None
        self._held: dict[str, list[dict]] = {}
        self._index = 0
        self._clock = None
        self._clock_n = -1
        self._safe: tuple[int, int | None] = (-1, None)

    # ------------------------------------------------------------ stopping
    def install_signal_handlers(self):
        """SIGTERM and SIGINT set the flag; the tick loop stops at the next check.

        The handler does nothing but record the name: a signal that killed the
        process where it stood could leave a half-written tick, and the point
        of a clean stop is that it cannot.
        """
        import signal

        def handle(signum, frame):                    # pragma: no cover - trivial
            self.signalled = signal.Signals(signum).name

        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, handle)
        return self

    @property
    def stop_path(self):
        return None if self.limits.stop_file is None else Path(self.limits.stop_file)

    def stop_reason(self) -> tuple[str, str] | None:
        """The first stop condition that holds, or ``None``. No side effects."""
        if self.signalled:
            return ("SIGNAL", self.signalled)
        path = self.stop_path
        if path is not None and path.exists():
            return ("STOP_FILE", str(path))
        if self.deadline is not None and self._now() >= self.deadline:
            return ("TIME_LIMIT", f"{self.limits.max_seconds}s wall clock")
        ledger = self.collector.rpc.ledger
        left = self.limits.max_requests - self.limits.reserve_requests
        if ledger.run_attempts >= left:
            return ("REQUEST_CAP",
                    f"{ledger.run_attempts} attempts of {self.limits.max_requests}")
        if ledger.halted():
            return ("RPC_QUOTA_STOP", str(ledger.halted().get("reason")))
        return None

    def _stop(self, reason: str, detail: str = "") -> None:
        if self.stopped is None:
            self.stopped = str(reason)
            self.stop_detail = str(detail)
            self.log(f"[live] stopping: {reason} {detail}")

    def _note_error(self, code: str, detail: str = "") -> None:
        self.errors.append({"code": str(code), "detail": str(detail)[:300],
                            "tick": self.ticks_done,
                            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                time.gmtime())})

    # --------------------------------------------------------------- clock
    @property
    def block_clock(self):
        """The live grid inverted, the same class the replay driver uses."""
        headers = self.collector.store.headers
        if self._clock is None or self._clock_n != len(headers):
            self._clock = BlockClock(
                list(headers.values()),
                interval_s=self.finality.median_interval_s,
                grid_blocks=self.collector.grid.grid_blocks)
            self._clock_n = len(headers)
        return self._clock

    def _head(self) -> tuple[int, int]:
        head = self.collector.head
        if not head:
            return (0, 0)
        return (_int(head["number"]), _int(head["timestamp"]))

    # -------------------------------------------------------------- ticks
    def ticks(self, cadence: int = CADENCE_S):
        """The wall clock: one decision every ``cadence`` seconds, until a stop."""
        cadence = max(1, int(cadence))
        self.started_at = self._now()
        self.deadline = self.started_at + self.limits.max_seconds
        self._backfill()
        while True:
            stop = self.stop_reason()
            if stop:
                self._stop(*stop)
                return
            self._sleep_to_boundary(cadence)
            stop = self.stop_reason()
            if stop:
                self._stop(*stop)
                return
            try:
                result = self.collector.tick()
            except BudgetStop as exc:
                self._note_error(exc.code, exc.detail)
                self._stop(exc.code, exc.detail)
                return
            except RpcError as exc:
                # Addendum 15: the run stops on the first error. No retry, no
                # fallback, no provider switch.
                self._note_error(exc.code, exc.detail)
                self._stop(exc.code, exc.detail)
                return
            self.ticks_done += 1
            if result.get("reorg"):
                self.reorgs += 1
            head_number, cutoff = self._head()
            try:
                self._fill_anchor(cutoff)
            except (BudgetStop, RpcError) as exc:
                self._note_error(exc.code, exc.detail)
                self._stop(exc.code, exc.detail)
                return
            self._drain(cutoff)
            self.last_ts = int(cutoff)
            if not self.first_ts:
                self.first_ts = int(cutoff)
            lag = self.collector.block_lag()
            if lag["blocks"] is not None:
                self.lag_blocks.append(int(lag["blocks"]))
            if lag["seconds"] is not None:
                self.lag_seconds.append(int(lag["seconds"]))
            # Two different lags, both reported. ``lag_blocks`` is head minus
            # cursor *after* the scan — how much of the chain the collector has
            # not read — and is normally zero because a tick scans to the head
            # it just read. ``cutoff_age`` is how old the decision's own data
            # is when the tick finishes, which is what a reader means by "how
            # far behind is it".
            age = int(self._now() - int(cutoff))
            self.cutoff_ages.append(age)
            self.head_track.append({
                "tick": self.ticks_done, "cutoff_ts": int(cutoff),
                "head": head_number, "cursor": self.collector.cursor_block,
                "lag_blocks": lag["blocks"], "lag_seconds": lag["seconds"],
                "cutoff_age_s": age,
                "events": result.get("events", 0),
                "attempts": self.collector.rpc.ledger.run_attempts})
            if self.on_tick is not None:
                self.on_tick(self)
            yield int(cutoff)
            if self.stopped:            # set from inside confirm()
                return

    def _sleep_to_boundary(self, cadence: int) -> None:
        """Sleep to the next cadence boundary, in slices, so a stop is prompt."""
        now = self._now()
        target = (int(now) // cadence + 1) * cadence
        while True:
            left = target - self._now()
            if left <= 0:
                return
            if self.stop_reason():
                return
            self._sleep(min(left, 0.5))

    def _fill_anchor(self, cutoff: int) -> dict:
        """One header at or after ``cutoff + latency``: the fill rule's own block.

        Costs one request per tick and is what lets a decision at ``cutoff``
        be priced at the block the latency rule names. Nothing between the
        cutoff and this block is fetched, so no event after the cutoff can
        reach the fill.
        """
        need = int(cutoff) + self.latency_s
        header = None
        for _ in range(3):
            delay = (need + 1) - self._now()
            self._sleep(min(delay, 5.0) if delay > 0 else 1.0)
            header = self.collector.rpc.block("latest")
            self.collector.store.record_headers([header])
            if _int(header["timestamp"]) >= need:
                break
        if header is not None:
            self.anchor = {"block_number": _int(header["number"]),
                           "block_timestamp": _int(header["timestamp"])}
            self.coverage_end_ts = _int(header["timestamp"])
        return self.anchor or {}

    # ------------------------------------------------------------ backfill
    def _backfill(self) -> None:
        """At most the last hour of blocks, so a tracked curve has its history."""
        started = self._now()
        try:
            head = self.collector.rpc.block("latest")
        except (BudgetStop, RpcError) as exc:
            self._note_error(exc.code, exc.detail)
            self._stop(exc.code, exc.detail)
            return
        self.collector.head = head
        self.collector.store.record_headers([head])
        head_number, head_ts = _int(head["number"]), _int(head["timestamp"])
        blocks = max(1, int(round(self.limits.backfill_seconds
                                  / self.finality.median_interval_s)))
        resume = (self.collector.store.cursor or {}).get("block_number")
        first = (max(0, head_number - blocks) if resume is None
                 else min(int(resume) + 1, head_number))
        ledger = self.collector.rpc.ledger
        spent_at_start = ledger.run_attempts

        def guard(top, summary, collector):
            if ledger.run_attempts - spent_at_start >= self.limits.backfill_requests:
                raise BudgetStop("BACKFILL_REQUEST_CAP",
                                 f"{self.limits.backfill_requests} attempts")
            if self._now() - started >= self.limits.backfill_wall_seconds:
                raise BudgetStop("BACKFILL_TIME_CAP",
                                 f"{self.limits.backfill_wall_seconds}s")

        summary = self.collector.backfill_window(
            first, head_number, quote_asset=self.quote_asset, on_segment=guard)
        self.backfill = {
            **summary, "requests": ledger.run_attempts - spent_at_start,
            "wall_s": round(self._now() - started, 1),
            "seconds_of_blocks": self.limits.backfill_seconds,
            "resumed_from_cursor": resume is not None,
        }
        self._drain(head_ts)
        self.log(f"[live] backfill {first}..{head_number} "
                 f"({summary['events']} events, {self.backfill['requests']} "
                 f"requests, {self.backfill['wall_s']}s)")

    # ------------------------------------------------------------- events
    def advance(self, cutoff: int):
        """The normalised events at or before ``cutoff``, handed over once."""
        cutoff = int(cutoff)
        out, keep = [], []
        for event in self.pending:
            (out if int(event["block_timestamp"]) <= cutoff else keep).append(event)
        self.pending = keep
        out.sort(key=lambda e: (e["block_number"], e["tx_index"], e["log_index"]))
        return out

    def _drain(self, cutoff: int) -> None:
        """Everything the collector has written since the last drain, routed."""
        events = self.collector.store.events
        fresh = events[self._index:]
        self._index = len(events)
        orphaned = self.collector.store.orphaned
        fresh = [e for e in fresh if e["log_id"] not in orphaned]
        fresh.sort(key=lambda e: (e["block_number"], e["tx_index"], e["log_index"]))
        for event in fresh:
            self._route(event)
        self._release_stale(cutoff)

    def _route(self, event: dict) -> None:
        if (event.get("event") == "TokenLaunched"
                and event.get("source") == "factory"):
            self.launches_seen += 1
            curve = str(event.get("curve") or "").lower()
            args = event.get("args") or {}
            quote = str(event.get("quote_asset") or "").lower()
            pinned = matches_pinned_config(args.get("launchConfigId"),
                                           args.get("graduationThreshold"))
            if not curve or quote != self.quote_asset or not pinned:
                self.pending.append(event)     # recorded, never followed
                return
            self._held[curve] = [event]
            return
        curve = str(event.get("address") or "").lower()
        held = self._held.get(curve)
        if held is None:
            self.pending.append(event)
            return
        held.append(event)
        if event.get("event") in TRADE_KINDS:
            tax = creator_tax_from_trade(event)
            if tax is not None:
                self._resolve(curve, tax, source="derived")

    def _resolve(self, curve: str, creator_tax_bps: int, *, source: str) -> None:
        held = self._held.pop(curve, None)
        if not held:
            return
        launch = held[0]
        token = launch.get("token")
        args = launch.get("args") or {}
        self.initial_states[token] = {
            "token": token, "curve": curve,
            "launch_block": int(launch["block_number"]),
            "launched_at": int(launch["block_timestamp"]),
            "quote_asset": str(launch.get("quote_asset") or "").lower(),
            "snipe_start_bps": int(LAUNCH_SEED["snipe_start_bps"]),
            "snipe_window_seconds": int(LAUNCH_SEED["snipe_window_seconds"]),
            "launch_config_id": args.get("launchConfigId"),
            "graduation_threshold": args.get("graduationThreshold"),
            "state": seed_state(int(creator_tax_bps)).as_dict(),
            "source": source,
        }
        self.pending.extend(held)

    def _release_stale(self, cutoff: int) -> None:
        """A launch whose tax no trade pinned: one bounded read, or no state."""
        for curve in sorted(self._held):
            held = self._held.get(curve)
            if not held:
                continue
            launch = held[0]
            if int(cutoff) - int(launch["block_timestamp"]) < MIN_AGE_S:
                continue
            trades = [e for e in held if e.get("event") in TRADE_KINDS]
            tax = None
            if trades and self.tax_reads < MAX_TAX_READS:
                tax = self._read_creator_tax(curve, int(launch["block_number"]))
            if tax is not None:
                self._resolve(curve, tax, source="eth_call")
                continue
            # No state: the launch is released so its discovery is recorded
            # with its reason, and it is never followed.
            self.pending.extend(self._held.pop(curve))

    def _read_creator_tax(self, curve: str, block: int) -> int | None:
        from .collector import selector
        self.tax_reads += 1
        try:
            payload = self.collector.rpc.call(
                "eth_call", [{"to": str(curve).lower(),
                              "data": selector("creatorTaxBps()")}, hex(int(block))])
        except (RpcError, BudgetStop) as exc:
            self._note_error(getattr(exc, "code", "RPC_ERROR"),
                             getattr(exc, "detail", ""))
            return None
        try:
            return int.from_bytes(bytes.fromhex(str(payload)[2:])[:32], "big")
        except ValueError:
            return None

    # ------------------------------------------------------- confirmation
    def confirm(self, block_number: int) -> dict:
        """The collector's confirmation rule, with the ``safe`` tag when answered.

        An endpoint failure here is an endpoint failure like any other: it is
        recorded, the run is asked to stop at the next tick, and the block is
        reported **unconfirmed**, so the episode stays
        ``PENDING_CONFIRMATION``. Nothing settles on a failed read.
        """
        head_number, _ = self._head()
        try:
            safe = self._safe_block()
            return self.collector.confirmation(int(block_number), head=head_number,
                                               safe_block=safe)
        except (BudgetStop, RpcError) as exc:
            self._note_error(exc.code, exc.detail)
            self._stop(exc.code, exc.detail)
            return {"block_number": int(block_number), "confirmed": False,
                    "head": head_number, "error": exc.code,
                    "confirm_depth": self.finality.confirm_depth}

    def _safe_block(self) -> int | None:
        """The ``safe`` tag, read at most once per tick and cached with it."""
        if not self.finality.safe_tag_supported:
            return None
        tick, cached = self._safe
        if tick == self.ticks_done:
            return cached
        header = self.collector.rpc.block("safe")
        self.collector.store.record_headers([header])
        number = _int(header["number"])
        self._safe = (self.ticks_done, number)
        return number

    # ------------------------------------------------------------- health
    def health(self, **extra) -> dict:
        """What ``status`` prints and what the observer serves. No request."""
        ledger = self.collector.rpc.ledger
        head_number, head_ts = self._head()
        cursor = self.collector.store.cursor or {}
        confirmed = cursor.get("confirmed_block")
        header = (None if confirmed is None
                  else self.collector.store.header_at_or_below(int(confirmed)))
        confirmed_ts = None if header is None else int(header["timestamp"])
        now = int(self._now())
        age = None if confirmed_ts is None else now - confirmed_ts
        lag = self.collector.block_lag()
        return {
            "venue": VENUE, "chain_id": CHAIN_ID, "mode": self.mode,
            "data": "LIVE", "execution": "PAPER",
            "updated_epoch": now,
            "updated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            "started_epoch": None if self.started_at is None else int(self.started_at),
            "ticks": self.ticks_done,
            "cutoff_ts": self.last_ts,
            "cursor_block": self.collector.cursor_block,
            "head_block": head_number, "head_ts": head_ts,
            "lag_blocks": lag["blocks"], "lag_seconds": lag["seconds"],
            "cutoff_age_s": (None if not self.last_ts
                             else int(self._now() - self.last_ts)),
            "confirmed_block": None if confirmed is None else int(confirmed),
            "confirmed_ts": confirmed_ts,
            "confirmed_age_s": age,
            "fresh": bool(age is not None and age <= FRESH_SECONDS),
            "fresh_rule": (f"false whenever the last confirmed block is older "
                           f"than {FRESH_SECONDS} s: a connection is not fresh "
                           f"data"),
            "safe_block": self._safe[1],
            "confirm_depth": self.finality.confirm_depth,
            "tracked_curves": len(self.collector.tracked(head_ts)) if head_ts else 0,
            "launches_seen": self.launches_seen,
            "held_launches": len(self._held),
            "reorgs": self.reorgs,
            "requests": {
                "run_attempts": ledger.run_attempts,
                "run_cap": self.limits.max_requests,
                "run_remaining": max(0, self.limits.max_requests
                                     - ledger.run_attempts),
                "wave_attempts": ledger.attempts,
                "wave_cap": ledger.wave_cap,
                "wave_remaining": max(0, ledger.wave_cap - ledger.attempts),
                "units": ledger.units,
                "by_method": {k: dict(v) for k, v in
                              ledger.state.get("by_method", {}).items()},
            },
            "last_error": (self.errors[-1]["code"] if self.errors else None),
            "errors": len(self.errors),
            "stop": {"reason": self.stopped, "detail": self.stop_detail,
                     "deadline_epoch": (None if self.deadline is None
                                        else int(self.deadline)),
                     "seconds_left": (None if self.deadline is None
                                      else max(0, int(self.deadline - self._now())))},
            "limits": self.limits.as_dict(),
            **extra,
        }

    def as_dict(self) -> dict:
        return {"mode": self.mode, "dataset": self.label,
                "chain_id": CHAIN_ID,
                "ticks": self.ticks_done,
                "first_ts": self.first_ts, "last_ts": self.last_ts,
                "coverage_end_ts": self.coverage_end_ts,
                "admission_last_block": self.admission_last_block,
                "admission_rule": ("live admission never closes on a block "
                                   "number: a position still open at the stop "
                                   "is retained and reported open"),
                "stopped": self.stopped, "stop_detail": self.stop_detail,
                "limits": self.limits.as_dict(),
                "backfill": self.backfill,
                "launches_seen": self.launches_seen,
                "held_at_stop": len(self._held),
                "tax_reads": self.tax_reads,
                "reorgs": self.reorgs,
                "errors": self.errors,
                "lag_blocks": self.lag_blocks,
                "lag_seconds": self.lag_seconds,
                "cutoff_ages": self.cutoff_ages,
                "head_track": self.head_track,
                "fill_anchor": self.anchor}


# --------------------------------------------------------------------------
# Tallies
# --------------------------------------------------------------------------
@dataclass
class Tally:
    """Denominators that are never pooled, as PROTOCOL §7 has required since D6."""

    per_candidate: Counter = field(default_factory=Counter)
    per_candidate_action: Counter = field(default_factory=Counter)
    per_round: Counter = field(default_factory=Counter)
    per_round_action: Counter = field(default_factory=Counter)
    after_execution: Counter = field(default_factory=Counter)
    admission: Counter = field(default_factory=Counter)
    observation: Counter = field(default_factory=Counter)
    presentations: int = 0
    batches: int = 0
    silent_replicates: int = 0
    invalid_replicates: int = 0

    def as_dict(self) -> dict:
        return {
            "per_candidate_evaluation": {
                "status": dict(self.per_candidate),
                "action": dict(self.per_candidate_action),
                "n": sum(self.per_candidate.values())},
            "per_decision_round": {
                "status": dict(self.per_round),
                "action": dict(self.per_round_action),
                "n": sum(self.per_round.values())},
            "after_execution_constraints": dict(self.after_execution),
            "admission": dict(self.admission),
            "observation_status": dict(self.observation),
            "candidate_evaluations": self.batches,
            "presentations": self.presentations,
            "silent_replicates": self.silent_replicates,
            "silent_replicate_denominator": self.presentations,
            "invalid_replicates": self.invalid_replicates,
        }


# --------------------------------------------------------------------------
# The loop
# --------------------------------------------------------------------------
def _context_v1(tape, cutoff, **kw):
    """``pons_context_v1``, the default. Named so a log can say which ran."""
    return tape.context(cutoff, **kw)


class PonsLoop:
    """One branch: one brain, one account, one position, many tokens."""

    version = VERSION

    def __init__(self, *, driver, run, mb, credit, journal, encoder: SensoryEncoder,
                 admission: AdmissionPolicy, execution: PAPER.PonsPaperExecution,
                 policy, universe: Universe, mode: str, learning: str,
                 branch: str, run_id: str, cadence: int = CADENCE_S,
                 track_seconds: int = TRACK_SECONDS, restart_after: int | None = None,
                 context_fn=None, entry_deadline_ts: int | None = None,
                 reinforcement_rule: str = ABSOLUTE_PROFIT_V1,
                 log=print):
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        if learning not in LEARNING_MODES:
            raise ValueError(f"learning must be one of {LEARNING_MODES}")
        #: D12 addendum 1: which teacher settles an outcome. This loop holds
        #: one position at a time, so it can only ever see one outcome of one
        #: tick; a cohort does not exist here and cannot be invented. A
        #: configuration that selects ``relative_cohort_v1`` is therefore
        #: **refused** rather than silently taught the absolute way — school
        #: mode is ``experiments/d12/school.py``. The default is the rule every
        #: D5-D10 configuration has always taken, so their path is unchanged.
        if reinforcement_rule == RELATIVE_COHORT_V1:
            raise ValueError(
                f"{RELATIVE_COHORT_V1} needs a cohort of candidates evaluated "
                f"at one tick; PonsLoop holds one position and settles one "
                f"outcome, so it cannot form one. School mode drives the same "
                f"brain, readout and trace formation from "
                f"experiments/d12/school.py.")
        if reinforcement_rule != ABSOLUTE_PROFIT_V1:
            raise ValueError(f"unknown reinforcement rule {reinforcement_rule!r}")
        self.reinforcement_rule = str(reinforcement_rule)
        self.driver = driver
        self.run = run
        self.mb = mb
        self.credit = credit
        self.journal = journal
        self.encoder = encoder
        self.admission = admission
        self.x = execution
        self.policy = policy
        self.decoder = policy.decoder
        self.universe = universe
        self.mode = mode
        self.learning = learning
        self.branch = branch
        self.run_id = run_id
        self.cadence = int(cadence)
        self.track_seconds = int(track_seconds)
        self.restart_after = restart_after
        #: How a tape is turned into one observation. D11 selects
        #: ``pons_context_v2`` here by configuration; ``None`` is
        #: ``pons_context_v1``, which is what every D5-D10 configuration gets
        #: and what keeps the D10 replay log byte-identical.
        self.context_fn = context_fn or _context_v1
        #: D11-001 addendum 6: the last chain second an entry's whole
        #: settlement window must fit inside. A decoded BUY at a cutoff where
        #: ``cutoff + latency + horizon`` would cross it is **recorded and not
        #: executed**, so the partition's episodes all settle inside the
        #: partition and no position is open at the boundary. ``None`` — every
        #: D5-D10 configuration — is no deadline at all and the D10 path is
        #: byte-identical.
        self.entry_deadline_ts = (None if entry_deadline_ts is None
                                  else int(entry_deadline_ts))
        self.log = log
        self.tapes: dict[str, TokenTape] = {}
        self.by_curve: dict[str, TokenTape] = {}
        self.discovered: set[str] = set()
        self.tally = Tally()
        self.episodes: list[dict] = []
        self.pending: dict | None = None
        self.unresolved: list[dict] = []
        self._unresolved_seen: set = set()
        self.restarts: list[dict] = []
        self.trace: list[dict] = []
        self.marks = 0
        self.journal.stamp = {"venue": VENUE, "chain_id": CHAIN_ID,
                              "mode": self.mode, "learning": self.learning,
                              "run_id": self.run_id, "branch": self.branch}

    # -------------------------------------------------- partition boundary
    def beyond_entry_deadline(self, cutoff: int) -> bool:
        """Would an entry at ``cutoff`` settle past this partition's end?

        ``cutoff + latency + horizon <= entry_deadline_ts`` is the whole rule,
        and with no deadline it is never true.
        """
        if self.entry_deadline_ts is None:
            return False
        need = int(cutoff) + int(self.x.latency_s) + int(self.x.horizon_s)
        return need > int(self.entry_deadline_ts)

    # ------------------------------------------------------------- tapes
    def _open_tape(self, event: dict) -> None:
        token = event.get("token")
        curve = event.get("curve")
        if not token or token in self.tapes:
            return
        args = event.get("args") or {}
        quote = str(event.get("quote_asset") or "").lower()
        reasons = []
        if quote != NATIVE_QUOTE:
            reasons.append("QUOTE_UNSUPPORTED")
        record = self.driver.initial_states.get(token)
        if record is None:
            reasons.append("NO_INITIAL_STATE")
        if reasons:
            self.discovered.add(token)
            self.tally.admission["|".join(reasons)] += 1
            self.journal.record_discovery(
                token=token, curve=curve, admitted=False, reasons=reasons,
                launch_block=event["block_number"], quote_asset=quote,
                launched_at=event["block_timestamp"],
                launch_config_id=args.get("launchConfigId"),
                graduation_threshold=args.get("graduationThreshold"))
            return
        state = record["state"]
        tape = TokenTape(
            token=token, curve=curve,
            launch_block=int(record["launch_block"]),
            launched_at=int(record["launched_at"]),
            initial=CurveState(
                quote_reserve=int(state["quote_reserve"]),
                token_reserve=int(state["token_reserve"]),
                real_quote_reserve=int(state["real_quote_reserve"]),
                sellable_tokens=int(state["sellable_tokens"]),
                fee_bps=int(state["fee_bps"]),
                creator_tax_bps=int(state["creator_tax_bps"]),
                snipe_tax_bps=0, graduated=bool(state["graduated"])),
            snipe_start_bps=int(record["snipe_start_bps"]),
            snipe_window_seconds=int(record["snipe_window_seconds"]),
            quote_asset=quote, deployment=str(event.get("deployment") or ""),
            coverage_end_ts=getattr(self.driver, "coverage_end_ts", None))
        self.tapes[token] = tape
        self.by_curve[curve] = tape
        self.universe.register(token)
        self.discovered.add(token)
        self.tally.admission["TAPE_OPENED"] += 1
        self.journal.record_discovery(
            token=token, curve=curve, admitted=True, reasons=[],
            launch_block=event["block_number"], quote_asset=quote,
            launched_at=event["block_timestamp"],
            launch_config_id=args.get("launchConfigId"),
            graduation_threshold=args.get("graduationThreshold"),
            initial_state_source=record.get("source"))

    def _refresh_coverage(self) -> None:
        """The driver's coverage end, onto every tape, every tick.

        Replay hands over a constant — the dataset's last covered second — so
        this assigns each tape the value it was already created with and
        changes nothing. Live, the covered end *moves*: it is the fill anchor
        the driver read after the poll, and a tape that did not refresh it
        would refuse every quote past its own last trade as missing coverage.
        """
        end = getattr(self.driver, "coverage_end_ts", None)
        if end is None:
            return
        for tape in self.tapes.values():
            tape.coverage_end_ts = int(end)

    def _ingest(self, events) -> None:
        for event in events:
            if event.get("status") != "OK":
                continue
            if event.get("event") == "TokenLaunched" and event.get("source") == "factory":
                self._open_tape(event)
            elif event.get("source") == "curve":
                tape = self.by_curve.get(event["address"])
                if tape is not None:
                    tape.apply(event)

    # ---------------------------------------------------------- the round
    def _candidates(self, cutoff: int, tick: int) -> tuple[list, list, list]:
        """Every tracked token considered, then rotated. Blind to every price."""
        considered = []
        for token, tape in sorted(self.tapes.items()):
            if tape.launch_block > self.driver.admission_last_block:
                continue
            age = cutoff - tape.launched_at
            if age < MIN_AGE_S or age > self.track_seconds:
                continue
            stable_id = self.universe.stable_id(token)
            context = self.context_fn(tape, cutoff, tick=tick,
                                      stable_id=stable_id)
            self.tally.observation[context.status.value] += 1
            considered.append(self.admission.consider(
                tape, context, stable_id=stable_id, cutoff=cutoff))
        for candidate in considered:
            for reason in (candidate.reasons or ("ADMITTED",)):
                self.tally.admission[reason] += 1
        presented, omitted = self.admission.rotate(considered, tick)
        return considered, presented, omitted

    def run_branch(self) -> dict:
        started = time.time()
        start_digest = self.journal.checkpoint_digest()
        self.journal.record_partition(
            name="REPLAY" if self.mode == MODE_REPLAY else "LIVE",
            boundary="start", branch=self.branch, run_id=self.run_id,
            learning=self.learning == LEARN, neural=True,
            venue=VENUE, chain_id=CHAIN_ID, mode=self.mode,
            dataset=self.driver.as_dict())
        tick = 0
        for cutoff in self.driver.ticks(self.cadence):
            tick += 1
            self._ingest(self.driver.advance(cutoff))
            self._refresh_coverage()
            self._settle_pending(cutoff)
            held = self.x.account.position
            if held is not None:
                self._tick_holding(cutoff, tick, held)
                continue
            self._tick_flat(cutoff, tick)
        self._finish_open(self.driver.last_ts)
        end_digest = self.journal.checkpoint_digest()
        self.journal.record_partition(
            name="REPLAY" if self.mode == MODE_REPLAY else "LIVE",
            boundary="end", branch=self.branch, run_id=self.run_id,
            venue=VENUE, chain_id=CHAIN_ID, mode=self.mode)
        return {
            "branch": self.branch, "run_id": self.run_id, "mode": self.mode,
            "learning": self.learning, "ticks": tick,
            "start_digest": start_digest, "end_digest": end_digest,
            "digest_unchanged": start_digest == end_digest,
            "tokens_discovered": len(self.discovered),
            "tapes": len(self.tapes),
            "tally": self.tally.as_dict(),
            "episodes": self.episodes,
            "unresolved": self.unresolved,
            "marks": self.marks,
            "restarts": self.restarts,
            "execution": self.x.stats(),
            "account": self.x.account.as_dict(),
            "credit": self.credit.stats(),
            "journal": {**self.journal.stats(),
                        "settled_frozen": self.journal.frozen_settled},
            "final_digest": self.journal.checkpoint_digest(),
            "log_path": str(self.journal.log.path),
            "trace": self.trace,
            "wall_s": round(time.time() - started, 2),
        }

    # ----------------------------------------------------------- the ticks
    def _evaluate(self, presented, cutoff: int, tick: int, extra: dict):
        observations = [
            c.context.observation(self.encoder.scales,
                                  symbol=c.token, features=self.encoder.features)
            for c in presented]
        try:
            rnd = self.run.evaluate_round(observations, round_index=tick,
                                          readout=self.policy,
                                          score=self.policy.score)
        except RO.TechnicalFailure as exc:
            self.journal.record_round_aborted(round_index=tick, cutoff_ts=cutoff,
                                              reason=str(exc))
            return None
        self.admission.mark_presented(presented, tick)
        self.journal.record_round(rnd, extra=extra)
        for c in rnd.candidates:
            if c.presentation is None:
                continue
            self.tally.batches += 1
            self.tally.presentations += c.k
            if c.batch is not None:
                self.tally.silent_replicates += c.batch.silent_replicates
                self.tally.invalid_replicates += c.batch.invalid_replicates
            decision = self.decoder.decode(c.presentation)
            self.tally.per_candidate[decision.status.value] += 1
            self.tally.per_candidate_action[decision.action.value] += 1
        return rnd

    def _round_extra(self, cutoff, tick, considered, presented, omitted,
                     contexts, mark=None) -> dict:
        return {
            "cutoff_ts": int(cutoff), "tick": int(tick),
            "tracked": len(self.tapes),
            "considered": len(considered),
            "admitted": sum(1 for c in considered if c.admitted),
            "rotated": len(omitted),
            "presented": [c.token for c in presented],
            "omitted": [{"token": c.token, "reasons": list(c.reasons)}
                        for c in omitted],
            "not_admitted": [{"token": c.token, "reasons": list(c.reasons)}
                             for c in considered if not c.admitted][:20],
            "context": contexts,
            "mark": mark,
        }

    def _empty_round(self, cutoff: int, tick: int, considered) -> None:
        """A round that presents nothing, named by whichever policy is in force.

        ``admission_v1`` has no opinion and keeps the counter it always kept.
        ``admission_v2`` names the round ``NO_ELIGIBLE_CANDIDATES`` — or
        ``DATA_LAG`` when every considered token was excluded by
        ``COLLECTOR_LAG``, because a collector outage is not every token
        becoming inactive — and records the per-token reason histogram, so the
        round leaves a record instead of a silence. Nothing is relaxed and no
        presentation happens either way.
        """
        namer = getattr(self.admission, "empty_round_status", None)
        if namer is None:
            self.tally.per_round["NO_USABLE_CANDIDATE"] += 1
            return
        status = namer(considered)
        self.tally.per_round[status] += 1
        reasons = self.admission.reason_histogram(considered)
        self.journal.record_round_aborted(
            round_index=tick, cutoff_ts=cutoff,
            reason=f"{status}: {len(considered)} considered, "
                   + ", ".join(f"{k}={v}" for k, v in sorted(reasons.items())))

    def _tick_flat(self, cutoff: int, tick: int) -> None:
        considered, presented, omitted = self._candidates(cutoff, tick)
        if not presented:
            self._empty_round(cutoff, tick, considered)
            return
        contexts = [c.context.as_dict(self.encoder.features) for c in presented]
        rnd = self._evaluate(presented, cutoff, tick,
                             self._round_extra(cutoff, tick, considered,
                                               presented, omitted, contexts))
        if rnd is None:
            return
        chosen = rnd.selected
        if chosen is None or chosen.presentation is None:
            self.tally.per_round["NO_USABLE_CANDIDATE"] += 1
            return
        candidate = next(c for c in presented if c.stable_id == chosen.stable_id)
        decision = self.decoder.decode(chosen.presentation)
        self.tally.per_round[decision.status.value] += 1
        self.tally.per_round_action[decision.action.value] += 1
        rec = self._decision_record(chosen, decision, tick, len(rnd.candidates))
        if decision.action is not D.Action.BUY:
            self.tally.after_execution[f"NO_ORDER:{decision.action.value}"] += 1
            self.journal.record_decision(rec, extra=self._chain_extra(candidate))
            return
        if self.beyond_entry_deadline(cutoff):
            # D11-001 addendum 6. The brain did decide BUY and that stays in
            # the log; the partition boundary refuses the entry, because an
            # episode whose settlement window crosses it would teach from
            # market the partition does not own. Nothing is sold, nothing is
            # settled and no reward exists.
            rec.readout_status = D.ReadoutStatus.POLICY_REJECT.value
            rec.rejection = {"side": "BUY", "symbol": candidate.token,
                             "reason": PARTITION_BOUNDARY,
                             "cutoff_ts": int(cutoff),
                             "entry_deadline_ts": int(self.entry_deadline_ts),
                             "needed_through": int(cutoff) + self.x.latency_s
                             + self.x.horizon_s}
            self.tally.after_execution[f"POLICY_REJECT:{PARTITION_BOUNDARY}"] += 1
            self.journal.record_decision(rec, extra=self._chain_extra(candidate))
            return
        tape = self.tapes[candidate.token]
        opened = self.x.open_long(episode_id=chosen.episode_id, tape=tape,
                                  stable_id=chosen.stable_id, cutoff=cutoff,
                                  clock=self.driver.block_clock)
        if isinstance(opened, X.Rejection):
            rec.readout_status = D.ReadoutStatus.POLICY_REJECT.value
            rec.rejection = opened.as_dict()
            self.tally.after_execution[f"POLICY_REJECT:{opened.reason.value}"] += 1
            self.journal.record_decision(rec, extra=self._chain_extra(candidate))
            return
        self.journal.record_decision(rec, extra=self._chain_extra(candidate))
        self.journal.open_episode(rec, chosen.traces, {
            **opened.entry.as_dict(), "market_ts": opened.entry.ts,
            "token": candidate.token, "curve": candidate.curve,
            "block_number": opened.entry.bar_index,
            "cutoff_ts": int(cutoff), "horizon_ts": self.x.horizon_ts,
            "tokens_out_wei": str(self.x.entry_tokens_wei),
            "branch": self.branch})
        self.tally.after_execution["BUY"] += 1
        self.trace.append({"event": "BUY", "tick": tick, "cutoff_ts": cutoff,
                           "token": candidate.token,
                           "episode_id": chosen.episode_id,
                           "v": round(decision.valence_hz, 3),
                           "block": opened.entry.bar_index,
                           "fill": opened.entry.fill_price})

    def _tick_holding(self, cutoff: int, tick: int, held) -> None:
        token = held.symbol
        tape = self.tapes[token]
        stable_id = held.stable_id
        context = self.context_fn(tape, cutoff, tick=tick, stable_id=stable_id)
        self.tally.observation[context.status.value] += 1
        mark = self.x.mark(tape, cutoff, self.driver.block_clock)
        if mark:
            self.marks += 1
        candidate = self.admission.consider(tape, context, stable_id=stable_id,
                                            cutoff=cutoff)
        candidate.admitted = context.usable          # inventory, not admission
        extra = self._round_extra(cutoff, tick, [candidate],
                                  [candidate] if context.usable else [],
                                  [], [context.as_dict(self.encoder.features)],
                                  mark=mark)
        rnd = None
        if context.usable:
            rnd = self._evaluate([candidate], cutoff, tick, extra)
        else:
            self.journal.record_round_aborted(
                round_index=tick, cutoff_ts=cutoff,
                reason=f"held token unusable: {context.status.value}")
        if self.x.due_for_horizon(cutoff):
            self._close_at_horizon(cutoff, tick, tape, held, rnd)
            return
        if rnd is None or rnd.selected is None or rnd.selected.presentation is None:
            self.tally.per_round["NO_USABLE_CANDIDATE"] += 1
            return
        chosen = rnd.selected
        decision = self.decoder.decode(chosen.presentation)
        self.tally.per_round[decision.status.value] += 1
        self.tally.per_round_action[decision.action.value] += 1
        rec = self._decision_record(chosen, decision, tick, len(rnd.candidates))
        if decision.action is D.Action.SELL:
            # Addendum 11 / D9(b) §2. The decoder did decide SELL and that
            # stays in the log. Under the fixed-hold policy the execution
            # policy refuses to act on it: nothing is sold, no outcome is
            # settled, no reward is delivered and no stored trace is touched.
            blocked = self.x.reject("SELL", token, int(cutoff),
                                    X.RejectReason.FIXED_HOLD)
            rec.readout_status = D.ReadoutStatus.POLICY_REJECT.value
            rec.rejection = blocked.as_dict()
            self.tally.after_execution["blocked_by_fixed_hold"] += 1
        else:
            self.tally.after_execution[f"HOLD:{decision.action.value}"] += 1
        self.journal.record_decision(rec, extra=self._chain_extra(candidate,
                                                                  mark=mark))

    # ------------------------------------------------------------ closing
    def _close_at_horizon(self, cutoff: int, tick: int, tape: TokenTape, held,
                          rnd) -> None:
        episode_id = held.episode_id
        try:
            plan = self.x.plan_sell(tape, self.x.horizon_ts, held.quantity,
                                    self.driver.block_clock,
                                    tokens_wei=self.x.entry_tokens_wei)
        except PAPER.Unresolved as exc:
            self._unresolve(episode_id, held.symbol, exc.reason, exc.detail, cutoff)
            return
        entry_ok = self.driver.confirm(held.entry.bar_index)
        exit_ok = self.driver.confirm(plan.block_number)
        if not (entry_ok["confirmed"] and exit_ok["confirmed"]):
            self.pending = {"episode_id": episode_id, "token": held.symbol,
                            "entry": entry_ok, "exit": exit_ok,
                            "since_tick": tick}
            self._unresolve(episode_id, held.symbol, PAPER.PENDING_CONFIRMATION,
                            f"entry {entry_ok['confirmed']} exit "
                            f"{exit_ok['confirmed']}", cutoff, retryable=True)
            return
        self.pending = None
        outcome = self.x.close(tape=tape,
                               reason=X.CloseReason.POLICY_CLOSE_FIXED_HOLD,
                               cutoff=cutoff, clock=self.driver.block_clock)
        if isinstance(outcome, X.Rejection):
            self.tally.after_execution[f"CLOSE_REJECT:{outcome.reason.value}"] += 1
            return
        self.tally.after_execution[X.CloseReason.POLICY_CLOSE_FIXED_HOLD.value] += 1
        event = self._reinforce(outcome, tape, entry_ok, exit_ok, cutoff)
        self.episodes.append({
            "episode_id": episode_id, "token": outcome.symbol,
            "stable_id": outcome.stable_id,
            "entry_block": outcome.entry.bar_index, "entry_ts": outcome.entry.ts,
            "entry_fill": outcome.entry.fill_price,
            "entry_reference": outcome.entry.reference_price,
            "exit_block": outcome.exit.bar_index, "exit_ts": outcome.exit.ts,
            "exit_fill": outcome.exit.fill_price,
            "exit_reference": outcome.exit.reference_price,
            "quantity": outcome.quantity if hasattr(outcome, "quantity")
            else outcome.entry.quantity,
            "fees_eth": outcome.fees, "slippage_eth": outcome.slippage,
            "gas_eth": (self.x.gas_buy_wei + self.x.gas_sell_wei
                        + self.x.gas_approval_wei) / PAPER.WEI,
            "gross_pnl": outcome.gross_pnl,
            "gross_reference_pnl": outcome.gross_reference_pnl,
            "net_pnl": outcome.net_pnl,
            "return_on_notional": outcome.return_on_notional,
            "seconds_held": outcome.market_seconds_held,
            "close_reason": outcome.close_reason.value,
            "confirmation": {"entry": entry_ok, "exit": exit_ok,
                             "status": "CONFIRMED"},
            "learning_event": None if event is None else event.as_dict(),
            "settlement": "SETTLED_FROZEN" if self.learning == FROZEN else "SETTLED",
        })
        self.trace.append({"event": outcome.close_reason.value, "tick": tick,
                           "cutoff_ts": cutoff, "token": outcome.symbol,
                           "episode_id": episode_id,
                           "net_pnl": outcome.net_pnl})
        self._maybe_restart(tick)

    def _settle_pending(self, cutoff: int) -> None:
        """Retry a settlement whose blocks were not confirmed at the horizon."""
        if self.pending is None or self.x.account.position is None:
            return
        held = self.x.account.position
        tape = self.tapes[held.symbol]
        self._close_at_horizon(cutoff, -1, tape, held, None)

    def _finish_open(self, cutoff: int) -> None:
        held = self.x.account.position
        if held is None:
            return
        self._unresolve(held.episode_id, held.symbol, "END_OF_DATA",
                        "the window ended with the position still open", cutoff)

    def _unresolve(self, episode_id, token, reason, detail, cutoff,
                   retryable: bool = False) -> None:
        """Record it once per (episode, reason). The exposure stays open.

        Once per pair, not once per tick: a route transition does not become
        more true by being written thirty times, and a log that repeated it
        would make the count of unresolved episodes unreadable.
        """
        key = (int(episode_id), str(reason))
        if key in self._unresolved_seen:
            return
        self._unresolved_seen.add(key)
        entry = self.x.record_unresolved(episode_id=episode_id, token=token,
                                         reason=reason, detail=detail,
                                         cutoff=cutoff)
        entry["retryable"] = bool(retryable)
        self.unresolved.append(entry)
        self.tally.after_execution[f"UNRESOLVED:{reason}"] += 1
        self.journal.record_unresolved(
            episode_id=int(episode_id), token=token, reason=reason,
            detail=detail, cutoff_ts=int(cutoff), settled=False,
            is_a_loss=False, retryable=bool(retryable))

    # ------------------------------------------------------- reinforcement
    def _reinforce(self, outcome, tape, entry_ok, exit_ok, cutoff):
        """One settled outcome, one normalised update — or none if frozen.

        ``valence`` is the sign of the **net** outcome and ``amount`` is what
        :meth:`flytrade.execution.ExecutionPolicy.reinforcement` derives from
        it, unchanged and with no new constant. The update is credited to the
        entry decision's stored eligibility trace set by episode id, through
        the existing :class:`flytrade.runner.CreditAssigner`.
        """
        payload = {**outcome.as_dict(),
                   "account": self.x.account.as_dict(),
                   "cumulative_realized_pnl": round(self.x.account.realized_pnl, 12),
                   "market_ts": outcome.exit.ts,
                   "token": outcome.symbol, "curve": tape.curve,
                   "entry_block": outcome.entry.bar_index,
                   "exit_block": outcome.exit.bar_index,
                   "confirmation": {"entry": entry_ok, "exit": exit_ok},
                   "branch": self.branch}
        if self.learning != LEARN:
            self.journal.settle_frozen(outcome.episode_id, payload)
            self.tally.after_execution["SETTLED_FROZEN"] += 1
            return None
        valence, amount = reinforcement_for(self.reinforcement_rule,
                                            outcome=outcome, execution=self.x)
        # D11-001 addendum 10: the raw net beside the normalised amount, the
        # scale it was divided by, and whether it clipped — additive fields on
        # the LEARNING record, so the reinforcement table is read from the log
        # rather than reassembled by joining two record kinds.
        learning_extra = {
            "raw_net_pnl_eth": float(outcome.net_pnl),
            "raw_return_on_notional": float(outcome.return_on_notional),
            "reinforce_full_scale": float(self.x.reinforce_full_scale),
            "reinforce_cap": float(self.x.reinforce_cap),
            "normalised_amount": float(amount),
            "clipped": bool(amount >= float(self.x.reinforce_cap)),
        }
        if valence == 0:
            event = R.LearningEvent(episode_id=outcome.episode_id, valence=0,
                                    amount=0.0, accepted=False,
                                    reason="net outcome exactly flat", k=RO.K)
            self.journal._append(REC.EventType.OUTCOME,
                                 {"episode_id": outcome.episode_id, **payload})
            self.journal._append(REC.EventType.LEARNING,
                                 {"episode_id": outcome.episode_id,
                                  **event.as_dict()})
            REC.clear_pending(self.journal.pending_path)
            self.credit.open.pop(outcome.episode_id, None)
            self.credit.settled.add(outcome.episode_id)
            return event
        return self.journal.settle(outcome.episode_id, payload, valence, amount,
                                   extra=learning_extra)

    # ------------------------------------------------------------ restart
    def _maybe_restart(self, tick: int) -> None:
        if (self.restart_after is None or self.learning != LEARN
                or self.restarts or len(self.x.outcomes) < self.restart_after):
            return
        saved = self.mb.gain.copy()
        self.mb.gain[:] = 0.0                 # destroy the in-memory state
        self.mb.apply()
        self.credit = R.CreditAssigner(self.mb)
        self.journal = REC.Journal(self.journal.dir, mb=self.mb,
                                   credit=self.credit,
                                   versions=self.journal.versions)
        self.journal.stamp = {"venue": VENUE, "chain_id": CHAIN_ID,
                              "mode": self.mode, "learning": self.learning,
                              "run_id": self.run_id, "branch": self.branch}
        report = self.journal.recover()
        restored = bool(np.array_equal(self.mb.gain, saved))
        self.restarts.append({"tick": tick,
                              "after_settled_episodes": len(self.x.outcomes),
                              "report": report,
                              "gains_restored_exactly": restored})
        self.log(f"[{self.run_id}/{self.branch}] restart at tick {tick}: "
                 f"{report['action']}; gains restored exactly: {restored}")
        if not restored:
            raise SystemExit("restart did not restore the learned gains")

    # ------------------------------------------------------------ records
    def _decision_record(self, chosen, decision, tick, n_candidates):
        return REC.decision_record(
            chosen, decision, round_index=tick, bar_index=tick,
            versions=self.journal.versions,
            checkpoint_digest=self.journal.checkpoint_digest(),
            n_candidates=int(n_candidates),
            readout_policy=self.policy.as_dict(),
            partition="REPLAY" if self.mode == MODE_REPLAY else "LIVE",
            branch=self.branch, run_id=self.run_id,
            dataset_label=self.driver.label)

    def _chain_extra(self, candidate: Candidate, mark=None) -> dict:
        context = candidate.context
        return {
            # the declared feature order, so the presentation publishes the
            # order the config registered rather than the alphabetical order
            # JSON serialisation leaves in the observation dict
            "feature_order": list(self.encoder.features),
            "token": candidate.token, "curve": candidate.curve,
            "block_number": context.launch_block,
            "age_s": context.age_s,
            "marginal_price": context.marginal_price,
            "last_trade_price": context.last_trade_price,
            "executable_tokens_out": (None if context.executable_tokens_out is None
                                      else str(context.executable_tokens_out)),
            "admission_reasons": list(candidate.reasons),
            "mark": mark,
        }


__all__ = ["VERSION", "MODE_REPLAY", "MODE_LIVE", "MODES", "LEARN", "FROZEN",
           "LEARNING_MODES", "CADENCE_S", "TRACK_SECONDS", "VENUE", "CHAIN_ID",
           "FRESH_SECONDS", "LIVE_MAX_SECONDS", "LIVE_MAX_REQUESTS",
           "LIVE_STOP_FILE", "MAX_TAX_READS", "ADMISSION_ALWAYS_OPEN",
           "PARTITION_BOUNDARY",
           "LiveLimits", "ReplayDriver", "LiveDriver", "PonsLoop", "Tally"]
