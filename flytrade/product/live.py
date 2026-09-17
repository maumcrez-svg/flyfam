"""The continuous product loop: the same object as `d10-live-001`, that stays up.

docs/SPEC.md P1 addendum 3. Everything that decides anything is unchanged and
is imported, not restated: :class:`flytrade.pons.loop.PonsLoop`, the
``admission_v2`` policy, ``pons_context_v2``, ``pons_encoder_v2``, the k = 8
readout, the decoder, the paper execution and its settlement, the journal, the
checkpoint and the recovery rule. What this module adds is the four things a
product needs and an experiment does not:

* **it does not stop on the clock.** :class:`ProductLiveDriver` removes the
  wall-clock and per-run request stops of addendum 15 and keeps the stop file,
  ``SIGTERM``/``SIGINT`` and the invariant violations. Nothing transient stops
  it.
* **it throttles instead of exiting.** :class:`RollingRequestWindow` is a
  rolling hour of request attempts; at the cap the driver emits ``THROTTLED``
  and waits for the window to free, and the window survives a restart because
  it is written into ``state.json``.
* **it retries instead of failing.** :class:`RetryingRpc` wraps the client with
  exponential backoff and writes an ``RPC_ERROR`` event per failure. The five
  codes that a retry cannot cure — an unallowed method, a range refusal the
  collector itself halves, a missing endpoint — are re-raised untouched.
* **it feeds.** :class:`FeedJournal` and :class:`ProductLoop` translate the
  loop's own records into the nine spectacle kinds and keep ``state.json``
  current, and :class:`ProductLoop` computes the reinforcement of every settled
  episode, writes it as ``CREDIT`` and **never applies it**: learning is
  ``FROZEN`` and the checkpoint digest is asserted unchanged across every
  settlement.

**One brain, one position, one process.** The loop refuses to start under
``LEARN``, refuses a brain whose digest is not the registered one, and refuses
a chain that is not 4663.
"""

from __future__ import annotations

import time
from collections import deque
from pathlib import Path

from .. import records as REC
from ..pons import loop as LOOP
from ..pons import paper as PAPER
from ..pons.budget import BudgetStop
from ..pons.reinforcement import ABSOLUTE_PROFIT_V1, reinforcement_for
from ..pons.rpc import RANGE_TOO_LARGE, RpcError
from . import feed as FEED

VERSION = "pons_product_loop_v1"

#: P1 addendum 3(b): the request budget is a rolling hour. D10's per-run cap is
#: the registered value; ``d10-live-001`` spent 1,493 attempts in its hour, so
#: this is roughly twice the observed steady state and it has never bound.
HOURLY_REQUEST_CAP = 3_000
WINDOW_S = 3_600

#: attempts held back from the cap so a tick that has begun can finish rather
#: than meeting a :class:`BudgetStop` in the middle of its own settlement.
HOURLY_RESERVE = 60

#: the backoff ladder: 1, 2, 4 … seconds, capped. A transient failure costs a
#: tick or two; a persistent one costs one attempt a minute, which the rolling
#: window counts like any other.
BACKOFF_BASE_S = 1.0
BACKOFF_MAX_S = 60.0

#: codes a retry cannot cure. A range refusal is the collector's own to halve
#: (``fetch_logs``), an unallowed method is a bug, and a missing endpoint is an
#: operator's problem: all four are re-raised on the first failure.
NON_RETRYABLE = frozenset({
    "RPC_METHOD_NOT_ALLOWED", RANGE_TOO_LARGE, "RPC_NOT_CONFIGURED",
    "RPC_ENV_UNREADABLE",
})

#: how much per-tick diagnostic history the driver keeps in memory. A loop that
#: runs for days may not grow a list per tick for ever.
KEEP_TICKS = 240

#: how many candidate rows one ``SNIFF`` event lists. The tracked set is in the
#: hundreds and almost all of it is ``INACTIVE``, so the rows are ordered
#: presented, then admitted, then rejected and cut here, with the count that
#: was cut on the event. The **aggregate** — considered, admitted, rejected and
#: the per-reason histogram — is never truncated.
SNIFF_CANDIDATE_CAP = 250


# --------------------------------------------------------------------------
# the rolling hour
# --------------------------------------------------------------------------
class RollingRequestWindow:
    """Attempts made in the last ``window_s`` seconds, from ledger samples.

    The ledger counts attempts cumulatively and never forgets, so "how many in
    the last hour" is the difference between the count now and the count as of
    an hour ago. This keeps those samples — one every ``min_gap_s`` at most, so
    a long wait cannot grow them without bound — and answers two questions: how
    much has been spent inside the window, and when the oldest spending leaves
    it.
    """

    def __init__(self, *, cap: int = HOURLY_REQUEST_CAP,
                 window_s: int = WINDOW_S, reserve: int = HOURLY_RESERVE,
                 min_gap_s: float = 15.0):
        self.cap = int(cap)
        self.window_s = int(window_s)
        self.reserve = int(reserve)
        self.min_gap_s = float(min_gap_s)
        self.samples: deque = deque()

    @property
    def usable(self) -> int:
        return max(1, self.cap - self.reserve)

    def restore(self, rows) -> "RollingRequestWindow":
        for row in rows or ():
            try:
                self.samples.append((float(row[0]), int(row[1])))
            except (TypeError, ValueError, IndexError):    # pragma: no cover
                continue
        return self

    def sample(self, now: float, attempts: int, *, force: bool = False) -> None:
        now, attempts = float(now), int(attempts)
        if self.samples and not force:
            last_t, last_a = self.samples[-1]
            if now - last_t < self.min_gap_s and attempts == last_a:
                return
            if now - last_t < self.min_gap_s:
                self.samples[-1] = (last_t, attempts)
                return
        self.samples.append((now, attempts))
        self._prune(now)

    def _prune(self, now: float) -> None:
        edge = float(now) - self.window_s
        # keep one sample at or before the edge: it is the baseline the
        # in-window difference is measured from
        while len(self.samples) > 2 and self.samples[1][0] <= edge:
            self.samples.popleft()

    def baseline(self, now: float) -> tuple[float, int]:
        edge = float(now) - self.window_s
        base = self.samples[0] if self.samples else (float(now), 0)
        for row in self.samples:
            if row[0] <= edge:
                base = row
            else:
                break
        return base

    def spent(self, now: float, attempts: int) -> int:
        if not self.samples:
            return 0
        return max(0, int(attempts) - int(self.baseline(now)[1]))

    def full(self, now: float, attempts: int) -> bool:
        return self.spent(now, attempts) >= self.usable

    def resume_at(self, now: float, attempts: int) -> float:
        """When enough of the window's spending will have aged out."""
        if not self.samples:
            return float(now)
        for t, a in self.samples:
            if int(attempts) - int(a) < self.usable:
                return t + self.window_s
        return self.samples[-1][0] + self.window_s

    def as_dict(self, now: float, attempts: int) -> dict:
        return {"cap": self.cap, "reserve": self.reserve,
                "window_s": self.window_s,
                "spent_in_window": self.spent(now, attempts),
                "remaining_in_window": max(
                    0, self.usable - self.spent(now, attempts)),
                "samples": [[round(t, 3), int(a)] for t, a in self.samples]}


# --------------------------------------------------------------------------
# the client wrapper
# --------------------------------------------------------------------------
class RetryingRpc:
    """:class:`flytrade.pons.rpc.RpcClient` with backoff. Nothing else moves.

    The allowlist, the masking, the ledger and the archive weighting are the
    client's and are untouched — this object only decides whether to call it
    again. ``d10-live-001`` stopped on the first endpoint error by its own
    registration (addendum 15); a product loop that did that would be down
    every time a provider hiccups, and P1 addendum 3(d) replaces that rule with
    this one, **for the product loop only**.
    """

    def __init__(self, client, *, on_error=None, should_stop=None, sleep=None,
                 now=None, base_delay: float = BACKOFF_BASE_S,
                 max_delay: float = BACKOFF_MAX_S):
        self._client = client
        self._on_error = on_error or (lambda **kw: None)
        self._should_stop = should_stop or (lambda: False)
        self._sleep = sleep or time.sleep
        self._now = now or time.time
        self.base_delay = float(base_delay)
        self.max_delay = float(max_delay)
        self.errors = 0
        self.retries = 0
        self.by_code: dict[str, int] = {}
        self.last_error: dict | None = None

    def __getattr__(self, name):                 # ledger, masked_url, mask, …
        return getattr(self._client, name)

    # ------------------------------------------------------------- retrying
    def _attempt(self, method_name: str, *args, **kw):
        delay = self.base_delay
        attempt = 0
        while True:
            attempt += 1
            try:
                return getattr(self._client, method_name)(*args, **kw)
            except RpcError as exc:
                self.errors += 1
                self.by_code[exc.code] = self.by_code.get(exc.code, 0) + 1
                fatal = exc.code in NON_RETRYABLE
                self.last_error = {"code": exc.code, "detail": exc.detail,
                                   "at": int(self._now()), "attempt": attempt,
                                   "retried": not fatal}
                self._on_error(code=exc.code, detail=exc.detail,
                               method=method_name, attempt=attempt,
                               backoff_s=(None if fatal else delay),
                               retried=not fatal, errors=self.errors)
                if fatal or self._should_stop():
                    raise
                self.retries += 1
                self._wait(delay)
                delay = min(delay * 2.0, self.max_delay)

    def _wait(self, delay: float) -> None:
        left = float(delay)
        while left > 0:
            if self._should_stop():
                return
            step = min(left, 1.0)
            self._sleep(step)
            left -= step

    # ------------------------------------------------- the six read methods
    def call(self, method: str, params=None):
        return self._attempt("call", method, params)

    def chain_id(self) -> int:
        return self._attempt("chain_id")

    def block_number(self) -> int:
        return self._attempt("block_number")

    def block(self, tag) -> dict:
        return self._attempt("block", tag)

    def code(self, address: str, block="latest") -> str:
        return self._attempt("code", address, block)

    def logs(self, addresses, from_block: int, to_block: int, topics=None):
        return self._attempt("logs", addresses, from_block, to_block, topics)

    def stats(self) -> dict:
        return {"errors": self.errors, "retries": self.retries,
                "by_code": dict(self.by_code), "last_error": self.last_error}


# --------------------------------------------------------------------------
# the driver
# --------------------------------------------------------------------------
class ProductLiveDriver(LOOP.LiveDriver):
    """``LIVE_PAPER`` without an end: the stop file, a signal, or an invariant.

    Three overrides and nothing else. :meth:`stop_reason` drops the wall clock
    and the per-run request cap; :meth:`_sleep_to_boundary` waits out the
    rolling hour before every tick; :meth:`health` says so.
    """

    def __init__(self, collector, *, finality, feed, window, **kw):
        super().__init__(collector, finality=finality, **kw)
        self.feed = feed
        self.window = window
        self.throttled = False
        self.throttle_events = 0
        self.throttle_seconds = 0.0

    # ---------------------------------------------------------------- stops
    def stop_reason(self):
        """The product's stop conditions. No clock and no request cap here."""
        if self.signalled:
            return ("SIGNAL", self.signalled)
        path = self.stop_path
        if path is not None and Path(path).exists():
            return ("STOP_FILE", str(path))
        halted = self.collector.rpc.ledger.halted()
        if halted:
            return ("RPC_QUOTA_STOP", str(halted.get("reason")))
        return None

    # ------------------------------------------------------------- throttle
    def _backfill(self) -> None:
        """Seed the window before the backfill, so the backfill is counted.

        The rolling hour is the difference between the ledger's count now and
        its count an hour ago; without a sample taken *before* the start
        backfill, that backfill's several hundred attempts would sit outside
        every window and the first hour would be undercounted by exactly the
        largest single spend the loop ever makes.
        """
        self.window.sample(self._now(), self.collector.rpc.ledger.attempts,
                           force=True)
        super()._backfill()
        self.window.sample(self._now(), self.collector.rpc.ledger.attempts,
                           force=True)

    def _sleep_to_boundary(self, cadence: int) -> None:
        super()._sleep_to_boundary(cadence)
        self.wait_for_the_window()

    def wait_for_the_window(self) -> float:
        """At the hourly cap: emit ``THROTTLED`` and wait. Never exit."""
        ledger = self.collector.rpc.ledger
        started = self._now()
        announced = False
        while True:
            now = self._now()
            self.window.sample(now, ledger.attempts)
            if not self.window.full(now, ledger.attempts):
                if announced:
                    self.throttled = False
                    self.throttle_seconds += now - started
                return now - started if announced else 0.0
            if self.stop_reason():
                return now - started
            if not announced:
                announced = True
                self.throttled = True
                self.throttle_events += 1
                resume = self.window.resume_at(now, ledger.attempts)
                self.feed.emit(
                    FEED.THROTTLED, tick=self.ticks_done,
                    reason="HOURLY_REQUEST_CAP",
                    spent_in_window=self.window.spent(now, ledger.attempts),
                    cap=self.window.cap, reserve=self.window.reserve,
                    window_s=self.window.window_s,
                    resume_at=int(resume), resume_utc=FEED.utc(resume),
                    waits="the loop waits for the window and does not exit")
                self.log(f"[live] throttled: "
                         f"{self.window.spent(now, ledger.attempts)} attempts "
                         f"in the last {self.window.window_s}s")
            self._sleep(min(5.0, max(1.0, self.window.window_s / 720.0)))

    # ---------------------------------------------------------------- house
    def trim(self, keep: int = KEEP_TICKS) -> None:
        """Bound the per-tick diagnostics. A day is 2,880 ticks."""
        for name in ("head_track", "lag_blocks", "lag_seconds", "cutoff_ages"):
            rows = getattr(self, name)
            if len(rows) > keep:
                del rows[:-keep]
        if len(self.errors) > keep:
            del self.errors[:-keep]

    def health(self, **extra) -> dict:
        h = super().health(**extra)
        ledger = self.collector.rpc.ledger
        now = self._now()
        h["stop"]["deadline_epoch"] = None
        h["stop"]["seconds_left"] = None
        h["stop"]["rule"] = ("the stop file, SIGTERM/SIGINT, or an invariant "
                             "violation. There is no wall-clock stop and the "
                             "request cap throttles rather than stops")
        h["throttle"] = {**self.window.as_dict(now, ledger.attempts),
                         "throttled_now": self.throttled,
                         "throttle_events": self.throttle_events,
                         "throttled_seconds": round(self.throttle_seconds, 1)}
        return h


# --------------------------------------------------------------------------
# the journal that also feeds
# --------------------------------------------------------------------------
class FeedJournal(REC.Journal):
    """The journal, unchanged, plus the spectacle events its records imply.

    Every method calls its base first: the durable audit stream is written
    exactly as :class:`flytrade.records.Journal` writes it, and the feed is
    derived from what was written rather than from a second computation.
    """

    def __init__(self, directory, *, mb, credit, versions, feed,
                 loop_ref=None):
        super().__init__(directory, mb=mb, credit=credit, versions=versions)
        self.feed = feed
        self.loop = loop_ref
        self.frozen_settlement_completes_the_log = True

    # ------------------------------------------------------------ the feed
    def _tick(self) -> int:
        return 0 if self.loop is None else int(self.loop.global_tick)

    def record_round(self, rnd, extra=None):
        out = super().record_round(rnd, extra)
        mark = (extra or {}).get("mark")
        if mark:
            self.feed.emit(FEED.MARK, tick=self._tick(),
                           cutoff_ts=(extra or {}).get("cutoff_ts"),
                           token=(self.loop.x.account.position.symbol
                                  if self.loop is not None
                                  and self.loop.x.account.position else None),
                           episode_id=(self.loop.x.account.position.episode_id
                                       if self.loop is not None
                                       and self.loop.x.account.position
                                       else None),
                           **{k: mark.get(k) for k in
                              ("available", "reason", "detail", "block_number",
                               "mark_value_eth", "cost_eth", "unrealised_eth",
                               "marginal_price")})
        return out

    def record_decision(self, rec, extra=None):
        out = super().record_decision(rec, extra)
        extra = extra or {}
        readout = rec.readout or {}
        decoder = rec.decoder or {}
        holding = bool(getattr(self.loop, "holding_tick", False))
        self.feed.emit(
            FEED.PICK, tick=self._tick(), cutoff_ts=rec.cutoff_ts,
            context="HELD" if holding else "FLAT",
            token=extra.get("token") or rec.symbol, curve=extra.get("curve"),
            stable_id=rec.stable_id, episode_id=rec.episode_id,
            action=rec.decoded_action, readout_status=rec.readout_status,
            rejection=rec.rejection,
            valence_hz=decoder.get("valence_hz"),
            approach_hz=decoder.get("approach_hz"),
            avoid_hz=decoder.get("avoid_hz"),
            theta_hz=decoder.get("theta_hz"),
            mbon_rates_hz=readout.get("rates_hz"),
            population_sizes=readout.get("population_sizes"),
            kc_active=readout.get("kc_active"),
            kc_fraction=readout.get("kc_fraction"),
            k=readout.get("k"),
            replicate_scores=([r.get("score_hz") for r in rec.replicates]
                              if rec.replicates else None),
            silent_replicates=readout.get("silent_replicates"),
            n_candidates=rec.n_candidates,
            age_s=extra.get("age_s"),
            marginal_price=extra.get("marginal_price"),
            last_trade_price=extra.get("last_trade_price"),
            admission_reasons=extra.get("admission_reasons"),
            brain_digest=rec.checkpoint_digest)
        self.feed.update(last_pick=self.feed.state["events"][-1])
        if self.loop is not None:
            self.loop.sniffed["picked"] += 1
        return out

    def open_episode(self, rec, trace, execution: dict) -> None:
        super().open_episode(rec, trace, execution)
        # the journal's ``execution`` dict rounds every price to eight decimals
        # — a token at 2.5e-9 ETH rounds to zero there — so the feed takes the
        # entry off the position itself, unrounded.
        position = (None if self.loop is None else self.loop.x.account.position)
        entry = None if position is None else position.entry
        self.feed.emit(
            FEED.OPEN, tick=self._tick(),
            cutoff_ts=execution.get("cutoff_ts"), token=execution.get("token"),
            curve=execution.get("curve"), episode_id=rec.episode_id,
            entry_block=execution.get("block_number"),
            entry_ts=execution.get("market_ts"),
            entry_fill_price=(execution.get("fill_price") if entry is None
                              else float(entry.fill_price)),
            entry_reference_price=(execution.get("reference_price")
                                   if entry is None
                                   else float(entry.reference_price)),
            quantity=(execution.get("quantity") if entry is None
                      else float(entry.quantity)),
            tokens_out_wei=execution.get("tokens_out_wei"),
            fee_eth=execution.get("fee"),
            horizon_ts=execution.get("horizon_ts"),
            size_eth=(None if self.loop is None else self.loop.x.notional))

    def settle_frozen(self, episode_id: int, outcome: dict) -> dict:
        out = super().settle_frozen(episode_id, outcome)
        entry = (outcome.get("entry") or {})
        exit_ = (outcome.get("exit") or {})
        # every price and every PnL in ``outcome`` is rounded to eight decimals
        # by ``OutcomeRecord.as_dict`` — a token at 2.5e-9 ETH rounds to zero —
        # so the feed takes them off the record the loop stashed, unrounded.
        raw = None if self.loop is None else getattr(self.loop, "last_outcome",
                                                     None)
        if raw is not None and int(raw.episode_id) != int(episode_id):
            raw = None

        self.feed.emit(
            FEED.CLOSE, tick=self._tick(), episode_id=int(episode_id),
            token=outcome.get("token"), curve=outcome.get("curve"),
            cutoff_ts=outcome.get("market_ts"),
            entry_block=outcome.get("entry_block"), entry_ts=entry.get("ts"),
            entry_fill_price=(entry.get("fill_price") if raw is None
                              else float(raw.entry.fill_price)),
            entry_reference_price=(entry.get("reference_price") if raw is None
                                   else float(raw.entry.reference_price)),
            exit_block=outcome.get("exit_block"), exit_ts=exit_.get("ts"),
            exit_fill_price=(exit_.get("fill_price") if raw is None
                             else float(raw.exit.fill_price)),
            exit_reference_price=(exit_.get("reference_price") if raw is None
                                  else float(raw.exit.reference_price)),
            quantity=(entry.get("quantity") if raw is None
                      else float(raw.entry.quantity)),
            gross_pnl_eth=(outcome.get("gross_pnl") if raw is None
                           else float(raw.gross_pnl)),
            gross_reference_pnl_eth=(outcome.get("gross_reference_pnl")
                                     if raw is None
                                     else float(raw.gross_reference_pnl)),
            slippage_eth=(outcome.get("slippage") if raw is None
                          else float(raw.slippage)),
            fees_eth=(outcome.get("fees") if raw is None else float(raw.fees)),
            net_pnl_eth=(outcome.get("net_pnl") if raw is None
                         else float(raw.net_pnl)),
            return_on_notional=(outcome.get("return_on_notional") if raw is None
                                else float(raw.return_on_notional)),
            seconds_held=outcome.get("market_seconds_held"),
            close_reason=outcome.get("close_reason"),
            confirmation=outcome.get("confirmation"),
            settlement="SETTLED_FROZEN",
            account=outcome.get("account"))
        return out


# --------------------------------------------------------------------------
# the execution, which remembers its last mark
# --------------------------------------------------------------------------
class ProductPaperExecution(PAPER.PonsPaperExecution):
    """The paper execution of `d10-live-001`, which keeps its last mark.

    One override, and it computes nothing: the mark is the base's own answer,
    stored so the tick that produced it can put it in the feed without asking
    the curve a second question.
    """

    def __init__(self, **kw):
        super().__init__(**kw)
        self.last_mark: dict = {}

    def mark(self, tape, cutoff: int, clock) -> dict:
        out = super().mark(tape, cutoff, clock)
        self.last_mark = dict(out or {})
        return out


# --------------------------------------------------------------------------
# the loop
# --------------------------------------------------------------------------
class ProductLoop(LOOP.PonsLoop):
    """:class:`~flytrade.pons.loop.PonsLoop`, frozen, resumable and fed.

    Four overrides:

    * :meth:`_tick_flat` / :meth:`_tick_holding` add the tick offset that makes
      episode ids monotone across a restart, emit the tick's ``SNIFF`` and
      ``HEARTBEAT``, and keep ``state.json`` current;
    * :meth:`_candidates` captures what the tick sniffed;
    * :meth:`_reinforce` computes the credit of a settled episode, writes it as
      ``CREDIT``, applies **nothing**, and asserts the digest did not move;
    * :meth:`_settle_pending` and :meth:`_tick_holding` refuse to crash when a
      restart has not yet rebuilt the held token's tape.
    """

    version = VERSION

    def __init__(self, *, feed, tick_offset: int = 0, state_hook=None, **kw):
        if kw.get("learning") != LOOP.FROZEN:
            raise ValueError("the product loop runs FROZEN and only FROZEN: "
                             "no plasticity is applied in the product")
        super().__init__(**kw)
        self.feed = feed
        self.tick_offset = int(tick_offset)
        self.global_tick = int(tick_offset)
        self.state_hook = state_hook
        self.last_sniff: dict = {}
        self._sniffed = False
        self.holding_tick = False
        self.sniffed = {"ticks": 0, "candidates": 0, "admitted": 0,
                        "rejected": 0, "picked": 0, "last_tick": 0}
        self.rejected_session: dict = {}
        self.rejected_recent: deque = deque()
        self.credits: dict = {"REWARD": 0, "PUNISHMENT": 0, "NEUTRAL": 0}
        self.last_credit: dict | None = None
        self.last_outcome = None
        self.tape_missing = 0

    # ------------------------------------------------------------- sniffing
    def _candidates(self, cutoff: int, tick: int):
        considered, presented, omitted = super()._candidates(cutoff, tick)
        shown = {c.token for c in presented}
        rows, reasons = [], {}
        for c in considered:
            names = list(c.reasons) or ["ADMITTED"]
            rows.append((0 if c.token in shown else 1 if c.admitted else 2,
                         {"token": c.token, "admitted": bool(c.admitted),
                          "reasons": names}))
            if not c.admitted:
                for name in names:
                    reasons[name] = reasons.get(name, 0) + 1
        rows.sort(key=lambda row: row[0])
        listed = [row[1] for row in rows[:SNIFF_CANDIDATE_CAP]]
        self.last_sniff = {
            "tracked": len(self.tapes), "considered": len(considered),
            "admitted": sum(1 for c in considered if c.admitted),
            "presented": [c.token for c in presented],
            "rotated": len(omitted),
            "rejected": sum(1 for c in considered if not c.admitted),
            "reasons": reasons, "candidates": listed,
            "candidates_listed": len(listed),
            "candidates_truncated": max(0, len(rows) - len(listed)),
            "candidates_order": ("presented, then admitted, then rejected; the "
                                 "counts and the reason histogram above are "
                                 "the whole tick and are never truncated"),
            "holding": False}
        # the tick's SNIFF is written here, before the round it feeds, so the
        # day file reads in the order the tick happened: what was smelled,
        # what was picked, what was done
        self._emit_sniff(cutoff, dict(self.last_sniff))
        self._sniffed = True
        return considered, presented, omitted

    def _emit_sniff(self, cutoff: int, payload: dict) -> None:
        now = time.time()
        for name, n in (payload.get("reasons") or {}).items():
            self.rejected_session[name] = self.rejected_session.get(name, 0) + n
            self.rejected_recent.append((now, name, n))
        while self.rejected_recent and now - self.rejected_recent[0][0] > 3600:
            self.rejected_recent.popleft()
        self.sniffed["ticks"] += 1
        self.sniffed["candidates"] += int(payload.get("considered", 0))
        self.sniffed["admitted"] += int(payload.get("admitted", 0))
        self.sniffed["rejected"] += int(payload.get("rejected", 0))
        self.sniffed["last_tick"] = int(payload.get("considered", 0))
        self.feed.emit(FEED.SNIFF, tick=self.global_tick, cutoff_ts=int(cutoff),
                       **payload)

    def rejected_last_hour(self) -> dict:
        now = time.time()
        out: dict = {}
        for t, name, n in self.rejected_recent:
            if now - t <= 3600:
                out[name] = out.get(name, 0) + n
        return out

    # ----------------------------------------------------------- the ticks
    def _tick_flat(self, cutoff: int, tick: int) -> None:
        self.global_tick = self.tick_offset + int(tick)
        self.holding_tick = False
        self.last_sniff = {}
        self._sniffed = False
        try:
            super()._tick_flat(cutoff, self.global_tick)
        finally:
            if not self._sniffed:                  # a tick that never asked
                self._emit_sniff(cutoff, {
                    "tracked": len(self.tapes), "considered": 0, "admitted": 0,
                    "presented": [], "rotated": 0, "rejected": 0,
                    "reasons": {}, "candidates": [], "holding": False})
            self._end_of_tick(cutoff)

    def _tick_holding(self, cutoff: int, tick: int, held) -> None:
        self.global_tick = self.tick_offset + int(tick)
        self.holding_tick = True
        missing = held.symbol not in self.tapes
        self._emit_sniff(cutoff, {
            "tracked": len(self.tapes), "considered": 0, "admitted": 0,
            "presented": [], "rotated": 0, "rejected": 0, "reasons": {},
            "candidates": [], "holding": True, "held_token": held.symbol,
            "tape_missing": missing,
            "note": ("a position is open: the loop observes the token it holds "
                     "and sniffs no new candidate")})
        try:
            if missing:
                # A restart has not replayed this token's launch back into a
                # tape yet. The exposure is retained and nothing is marked,
                # decided or settled on a tape that does not exist.
                self.tape_missing += 1
                return
            super()._tick_holding(cutoff, self.global_tick, held)
        finally:
            self._end_of_tick(cutoff)

    def _settle_pending(self, cutoff: int) -> None:
        held = self.x.account.position
        if (self.pending is not None and held is not None
                and held.symbol not in self.tapes):
            return
        super()._settle_pending(cutoff)

    # ------------------------------------------------------------ the credit
    def _reinforce(self, outcome, tape, entry_ok, exit_ok, cutoff):
        """The absolute rule computes it; nothing applies it. Addendum 3(f)."""
        before = self.journal.checkpoint_digest()
        #: the unrounded record, for the feed's CLOSE (``as_dict`` rounds)
        self.last_outcome = outcome
        valence, amount = reinforcement_for(ABSOLUTE_PROFIT_V1,
                                            outcome=outcome, execution=self.x)
        label = ("REWARD" if valence > 0 else
                 "PUNISHMENT" if valence < 0 else "NEUTRAL")
        event = super()._reinforce(outcome, tape, entry_ok, exit_ok, cutoff)
        after = self.journal.checkpoint_digest()
        if after != before:
            raise SystemExit(
                f"the frozen product loop moved the learned state on episode "
                f"{outcome.episode_id}: {before[:12]} -> {after[:12]}")
        self.credits[label] += 1
        self.last_credit = self.feed.emit(
            FEED.CREDIT, tick=self.global_tick, cutoff_ts=int(cutoff),
            episode_id=outcome.episode_id, token=outcome.symbol,
            label=label, valence=int(valence), amount=float(amount),
            rule=ABSOLUTE_PROFIT_V1,
            reinforce_full_scale=float(self.x.reinforce_full_scale),
            reinforce_cap=float(self.x.reinforce_cap),
            clipped=bool(amount >= float(self.x.reinforce_cap)),
            net_pnl_eth=float(outcome.net_pnl),
            return_on_notional=float(outcome.return_on_notional),
            applied=False, learning=self.learning,
            brain_digest_before=before, brain_digest_after=after,
            note=("recorded, never applied: the product brain is frozen and "
                  "its digest is asserted unchanged across this settlement"))
        return event

    # ----------------------------------------------------------- the state
    def _end_of_tick(self, cutoff: int) -> None:
        self.prune(cutoff)
        if self.state_hook is not None:
            self.state_hook(self, int(cutoff))

    def prune(self, cutoff: int) -> None:
        """Forget what can no longer be a candidate. A day is 11,000 launches.

        A tape older than ``track_seconds`` can never be presented again — the
        candidate loop skips it by age — and a decision that has no open
        episode can never be settled. Neither is dropped from the census: the
        journal has every ``DISCOVERY`` and every ``DECISION`` on disk.
        """
        held = self.x.account.position
        keep_token = held.symbol if held is not None else None
        stale = [t for t, tape in self.tapes.items()
                 if t != keep_token
                 and int(cutoff) - int(tape.launched_at) > self.track_seconds * 2]
        for token in stale:
            tape = self.tapes.pop(token, None)
            if tape is not None:
                self.by_curve.pop(tape.curve, None)
        keep_ep = {held.episode_id} if held is not None else set()
        if self.pending is not None:
            keep_ep.add(int(self.pending.get("episode_id", -1)))
        if len(self.journal.decisions) > 64:
            for ep in [e for e in self.journal.decisions if e not in keep_ep]:
                self.journal.decisions.pop(ep, None)
        if len(self.trace) > KEEP_TICKS:
            del self.trace[:-KEEP_TICKS]
        if len(self.unresolved) > KEEP_TICKS:
            del self.unresolved[:-KEEP_TICKS]


__all__ = ["VERSION", "HOURLY_REQUEST_CAP", "WINDOW_S", "HOURLY_RESERVE",
           "NON_RETRYABLE", "KEEP_TICKS", "RollingRequestWindow", "RetryingRpc",
           "ProductLiveDriver", "FeedJournal", "ProductPaperExecution",
           "ProductLoop"]
