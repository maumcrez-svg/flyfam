"""``pons_context_v1`` — what a memecoin looks like at one decision cutoff.

docs/SPEC.md D10 addendum 9, as amended by reviewer decision 3. Eight
measurements, all of them reconstructed from confirmed-or-fast events at or
before the cutoff and from nothing after it:

============== =========================================================
``age``        seconds since the launch block
``ret_30s``    log change of the **marginal curve price** over 30 s
``ret_2m``     the same over 2 minutes
``ret_5m``     the same over 5 minutes
``flow_imb_2m``(buy quote in − sell quote out) / (their sum), in [−1, 1]
``trade_rate_2m`` trades per minute over the last 2 minutes
``rv_2m``      SD of per-trade log marginal-price changes over 2 minutes
``drawdown_5m``log distance below the 5-minute maximum, ≤ 0
============== =========================================================

**Clipped, not zeroed** (reviewer decision 3). A window that starts before the
launch is measured *from the launch*: ``ret_w = log(p(cutoff) /
p(max(cutoff − w, launch)))``, and ``drawdown_5m`` maxes from
``max(cutoff − 5 min, launch)``. Dispatch 1's scale statistics, which zeroed
those features instead, found ``ret_2m``, ``ret_5m`` and ``drawdown_5m``
identically zero on a dataset whose tokens live ~62 s — which is what the
amendment is fixing.

**Three prices, never interchangeable** (amendment §6). The *marginal price*
``quote_reserve / token_reserve`` with the phantom reserve included is the only
one that enters a feature. The *last trade price* is what the most recent
``CurveBuy`` / ``CurveSell`` actually paid per token. The *executable
amount-out* is what 0.01 ETH would buy right now through the integer-exact
curve quote, snipe tax and all. All three are separate fields of the
observation record.

**Absent is not neutral.** A token younger than 60 s, one with fewer than three
trades, or one whose reconstructed state fails its own arithmetic is
``unusable``: it is not presented to the brain and its reason is recorded. A
two-minute window with no trades is a *valid measurement* — rate 0, imbalance
0 — and is presented.

Nothing in this module reads the network, reads an outcome, or knows what a
position is.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

import numpy as np

from .. import market as MK
from .curve import (CurveState, QuoteError, ReconstructionError,
                    quote_curve_buy, snipe_tax_bps)

VERSION = "pons_context_v1"

#: The feature order. The encoder maps channel pairs to it in this order, and
#: a feature dropped for want of glomeruli is dropped **from the end**.
PONS_FEATURES: tuple[str, ...] = (
    "age", "ret_30s", "ret_2m", "ret_5m",
    "flow_imb_2m", "trade_rate_2m", "rv_2m", "drawdown_5m")

#: Window, in seconds, of each windowed feature.
FEATURE_WINDOWS = {"ret_30s": 30, "ret_2m": 120, "ret_5m": 300,
                   "flow_imb_2m": 120, "trade_rate_2m": 120, "rv_2m": 120,
                   "drawdown_5m": 300}

#: Addendum 9: a token below either of these is not presented at all.
MIN_AGE_S = 60
MIN_TRADES = 3

#: The paper size, in wei. Recorded here because the executable amount-out is
#: quoted for exactly this size and for no other (addendum 2).
PAPER_SIZE_WEI = 10_000_000_000_000_000

TRADE_KINDS = ("CurveBuy", "CurveSell")


class ContextError(ValueError):
    """The tape cannot answer this question. Never silently zeroed."""


@dataclass(frozen=True)
class TapePoint:
    """The curve's exact state immediately after one event."""

    ts: int
    block_number: int
    kind: str
    quote_reserve: int
    token_reserve: int
    real_quote_reserve: int
    sellable_tokens: int
    graduated: bool
    #: signed quote flow of this event: + for a buy's net in, − for a sell's
    #: gross out, 0 for everything else.
    flow: int = 0
    #: quote per token of this trade, or ``None`` when it was not a trade.
    trade_price: float | None = None
    log_id: str = ""

    @property
    def marginal_price(self) -> float:
        return 0.0 if self.token_reserve <= 0 else self.quote_reserve / self.token_reserve


@dataclass
class TokenTape:
    """One curve's history, advanced event by event from its launch state.

    The tape is the only thing a context is computed from, and it is advanced
    strictly forward. :meth:`context` reads **only** points at or before the
    cutoff it is given, so feeding the tape more history than the cutoff
    covers cannot change the answer — which is what
    ``tests/d10/test_context.py`` asserts by truncating the stream.
    """

    token: str
    curve: str
    launch_block: int
    launched_at: int
    initial: CurveState
    snipe_start_bps: int = 9_900
    snipe_window_seconds: int = 3
    quote_asset: str = "0x" + "0" * 40
    deployment: str = "pons-v2"
    points: list[TapePoint] = field(default_factory=list)
    inconsistent: str = ""
    completed_at: int | None = None
    applied: int = 0
    #: The last chain second the **dataset** covers for this token, which is
    #: not the same as its last trade: a curve that stops trading is still
    #: covered, and its state is still known, until the window ends. Set by the
    #: driver; ``None`` falls back to the last event, which is what a live tape
    #: knows.
    coverage_end_ts: int | None = None

    def __post_init__(self):
        if not self.points:
            self.points.append(TapePoint(
                ts=int(self.launched_at), block_number=int(self.launch_block),
                kind="launch",
                quote_reserve=self.initial.quote_reserve,
                token_reserve=self.initial.token_reserve,
                real_quote_reserve=self.initial.real_quote_reserve,
                sellable_tokens=self.initial.sellable_tokens,
                graduated=self.initial.graduated))

    # ------------------------------------------------------------- advance
    @property
    def last(self) -> TapePoint:
        return self.points[-1]

    @property
    def state(self) -> CurveState:
        return self._state_of(self.last)

    def _state_of(self, point: TapePoint) -> CurveState:
        return CurveState(
            quote_reserve=point.quote_reserve, token_reserve=point.token_reserve,
            real_quote_reserve=point.real_quote_reserve,
            sellable_tokens=point.sellable_tokens,
            fee_bps=self.initial.fee_bps,
            creator_tax_bps=self.initial.creator_tax_bps,
            snipe_tax_bps=0, graduated=point.graduated)

    def apply(self, event: dict) -> None:
        """Advance by one normalised curve event, checking its arithmetic.

        A stream that does not reproduce the curve's own numbers marks the tape
        ``inconsistent`` — which makes every later observation unusable with
        that reason, rather than quietly producing a wrong price.
        """
        from .curve import CurveReconstruction

        kind = event.get("event")
        if self.inconsistent:
            return
        point = self.last
        recon = CurveReconstruction(
            self._state_of(point), launch_block=self.launch_block,
            launched_at=self.launched_at, snipe_start_bps=self.snipe_start_bps,
            snipe_window_seconds=self.snipe_window_seconds,
            token=self.token, curve=self.curve)
        try:
            state = recon.apply(event)
        except ReconstructionError as exc:
            self.inconsistent = f"{exc.code}: {exc.detail}"
            return
        args = event.get("args") or {}
        flow = 0
        price = None
        if kind == "CurveBuy":
            flow = int(args["quoteIn"]) - int(args["fee"]) - int(args["tax"])
            tokens = int(args["tokensOut"])
            price = (int(args["quoteIn"]) / tokens) if tokens else None
        elif kind == "CurveSell":
            gross = int(args["quoteOut"]) + int(args["fee"]) + int(args["tax"])
            flow = -gross
            tokens = int(args["tokensIn"])
            price = (int(args["quoteOut"]) / tokens) if tokens else None
        self.points.append(TapePoint(
            ts=int(event["block_timestamp"]),
            block_number=int(event["block_number"]), kind=str(kind),
            quote_reserve=state.quote_reserve, token_reserve=state.token_reserve,
            real_quote_reserve=state.real_quote_reserve,
            sellable_tokens=state.sellable_tokens, graduated=state.graduated,
            flow=flow, trade_price=price, log_id=str(event.get("log_id", ""))))
        self.applied += 1
        if kind == "CurveCompleted":
            self.completed_at = int(event["block_timestamp"])

    # ------------------------------------------------------------- queries
    def _upto(self, cutoff: int) -> list[TapePoint]:
        return [p for p in self.points if p.ts <= int(cutoff)]

    def point_at(self, cutoff: int) -> TapePoint | None:
        upto = self._upto(cutoff)
        return upto[-1] if upto else None

    def state_at(self, cutoff: int) -> CurveState | None:
        """The reconstructed state at ``cutoff``, with the snipe tax of that instant."""
        point = self.point_at(cutoff)
        if point is None:
            return None
        state = self._state_of(point)
        return state.with_snipe(snipe_tax_bps(
            self.snipe_start_bps, self.snipe_window_seconds,
            max(0, int(cutoff) - self.launched_at)))

    def completed_by(self, cutoff: int) -> bool:
        return self.completed_at is not None and self.completed_at <= int(cutoff)

    def trades_by(self, cutoff: int) -> int:
        return sum(1 for p in self._upto(cutoff) if p.kind in TRADE_KINDS)

    def coverage_end(self) -> int:
        """The last chain second this tape can answer for.

        Addendum 8: coverage per token is launch → the earlier of
        ``CurveCompleted`` and the end of the window. A quiet curve is still
        covered — its reserves simply did not move — so the last *event* is not
        the limit of what is known.
        """
        end = self.coverage_end_ts
        if end is None:
            end = self.points[-1].ts
        if self.completed_at is not None:
            end = min(end, self.completed_at)
        return int(end)

    # ------------------------------------------------------------ features
    def context(self, cutoff: int, *, tick: int = -1,
                stable_id: int = -1, size_wei: int = PAPER_SIZE_WEI) -> "PonsContext":
        """The eight measurements at ``cutoff``, and the three prices beside them."""
        cutoff = int(cutoff)
        upto = self._upto(cutoff)
        age = cutoff - self.launched_at
        blank = dict(token=self.token, curve=self.curve, cutoff_ts=cutoff,
                     tick=tick, stable_id=stable_id, age_s=age,
                     launch_block=self.launch_block, launched_at=self.launched_at,
                     version=VERSION)
        if not upto:
            return PonsContext(status=MK.ObservationStatus.INSUFFICIENT_TAPE,
                               reason="the cutoff precedes the launch block",
                               **blank)
        if self.inconsistent:
            return PonsContext(status=MK.ObservationStatus.INCONSISTENT_STATE,
                               reason=self.inconsistent, **blank)
        if self.completed_by(cutoff):
            # The curve graduated onto the Uniswap V4 route this wave does not
            # price. That is a route change, not a broken reconstruction, and
            # it gets its own status so the two never share a counter.
            return PonsContext(status=MK.ObservationStatus.ROUTE_COMPLETED,
                               reason="the curve completed before the cutoff",
                               completed=True, **blank)
        trades = [p for p in upto if p.kind in TRADE_KINDS]
        if age < MIN_AGE_S:
            return PonsContext(status=MK.ObservationStatus.INSUFFICIENT_TAPE,
                               reason=f"age {age}s < {MIN_AGE_S}s", **blank)
        if len(trades) < MIN_TRADES:
            return PonsContext(status=MK.ObservationStatus.INSUFFICIENT_TAPE,
                               reason=f"{len(trades)} trades < {MIN_TRADES}",
                               **blank)
        here = upto[-1]
        price = here.marginal_price
        if price <= 0 or here.token_reserve <= 0 or here.quote_reserve <= 0:
            return PonsContext(status=MK.ObservationStatus.INCONSISTENT_STATE,
                               reason="non-positive reserves at the cutoff",
                               **blank)

        raw = {"age": float(age)}
        for name in ("ret_30s", "ret_2m", "ret_5m"):
            start = max(cutoff - FEATURE_WINDOWS[name], self.launched_at)
            earlier = self._price_at(upto, start)
            raw[name] = (0.0 if earlier is None or earlier <= 0
                         else math.log(price / earlier))
        window = [p for p in trades if p.ts >= cutoff - FEATURE_WINDOWS["flow_imb_2m"]]
        buy_in = sum(p.flow for p in window if p.flow > 0)
        sell_out = -sum(p.flow for p in window if p.flow < 0)
        total = buy_in + sell_out
        raw["flow_imb_2m"] = 0.0 if total == 0 else (buy_in - sell_out) / total
        raw["trade_rate_2m"] = len(window) * 60.0 / FEATURE_WINDOWS["trade_rate_2m"]
        raw["rv_2m"] = self._realised_volatility(upto, cutoff)
        peak = max((p.marginal_price for p in upto
                    if p.ts >= max(cutoff - FEATURE_WINDOWS["drawdown_5m"],
                                   self.launched_at)), default=price)
        raw["drawdown_5m"] = (0.0 if peak <= 0 else min(0.0, math.log(price / peak)))

        last_trade = trades[-1].trade_price if trades else None
        executable, quote_error = self._executable(cutoff, size_wei)
        return PonsContext(
            status=MK.ObservationStatus.OK, reason="",
            raw=raw, marginal_price=price, last_trade_price=last_trade,
            executable_tokens_out=executable, executable_size_wei=int(size_wei),
            executable_error=quote_error, trades=len(trades),
            trades_2m=len(window), completed=self.completed_by(cutoff),
            state=self._state_of(here).as_dict(), **blank)

    @staticmethod
    def _price_at(upto: list[TapePoint], when: int) -> float | None:
        price = None
        for point in upto:
            if point.ts <= when:
                price = point.marginal_price
            else:
                break
        return price

    @staticmethod
    def _realised_volatility(upto: list[TapePoint], cutoff: int) -> float:
        steps = []
        previous = None
        for point in upto:
            if (previous is not None and point.kind in TRADE_KINDS
                    and point.ts >= cutoff - FEATURE_WINDOWS["rv_2m"]
                    and point.marginal_price > 0 and previous > 0):
                steps.append(math.log(point.marginal_price / previous))
            previous = point.marginal_price
        return statistics.stdev(steps) if len(steps) >= 2 else 0.0

    def _executable(self, cutoff: int, size_wei: int) -> tuple[int | None, str]:
        state = self.state_at(cutoff)
        if state is None:
            return None, "NO_STATE"
        try:
            return quote_curve_buy(state, int(size_wei)).tokens_out, ""
        except QuoteError as exc:
            return None, exc.code


@dataclass(frozen=True)
class PonsContext:
    """One token at one cutoff: the features, the three prices, the status."""

    token: str
    curve: str
    cutoff_ts: int
    tick: int
    stable_id: int
    age_s: int
    launch_block: int
    launched_at: int
    version: str
    status: MK.ObservationStatus
    reason: str = ""
    raw: dict = field(default_factory=dict)
    marginal_price: float = float("nan")
    last_trade_price: float | None = None
    executable_tokens_out: int | None = None
    executable_size_wei: int = PAPER_SIZE_WEI
    executable_error: str = ""
    trades: int = 0
    trades_2m: int = 0
    completed: bool = False
    state: dict = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        return self.status.usable

    def vector(self, features: tuple[str, ...] = PONS_FEATURES) -> np.ndarray:
        return np.array([float(self.raw.get(f, 0.0)) for f in features],
                        dtype=np.float64)

    def normalized(self, scales: dict, features: tuple[str, ...] = PONS_FEATURES
                   ) -> np.ndarray:
        """``tanh(raw / scale)``, the existing squashing convention."""
        out = []
        for name in features:
            scale = float(scales[name])
            if scale <= 0:
                raise ContextError(f"scale for {name!r} must be positive")
            out.append(math.tanh(float(self.raw.get(name, 0.0)) / scale))
        return np.array(out, dtype=np.float64)

    def observation(self, scales: dict, *, symbol: str,
                    features: tuple[str, ...] = PONS_FEATURES
                    ) -> MK.MarketObservation:
        """The :class:`flytrade.market.MarketObservation` the brain path takes.

        The same object D5–D9(b) used, carrying this wave's eight features and
        their names, so the readout's ``observation_id``, the encoder and the
        journal all keep working unchanged.
        """
        zeros = np.zeros(len(features), dtype=np.float64)
        usable = self.usable
        return MK.MarketObservation(
            symbol=symbol, stable_id=int(self.stable_id),
            bar_index=int(self.tick), cutoff_ts=int(self.cutoff_ts),
            status=self.status,
            raw=self.vector(features) if usable else zeros.copy(),
            normalized=self.normalized(scales, features) if usable else zeros.copy(),
            z=zeros.copy(), close=float(self.marginal_price),
            detail=self.reason, feature_names=tuple(features))

    def as_dict(self, features: tuple[str, ...] = PONS_FEATURES) -> dict:
        return {
            "version": self.version, "token": self.token, "curve": self.curve,
            "cutoff_ts": self.cutoff_ts, "tick": self.tick,
            "stable_id": self.stable_id, "age_s": self.age_s,
            "launch_block": self.launch_block, "launched_at": self.launched_at,
            "status": self.status.value, "reason": self.reason,
            "raw": {k: float(self.raw[k]) for k in features if k in self.raw},
            "marginal_price": self.marginal_price,
            "last_trade_price": self.last_trade_price,
            "executable_tokens_out": (None if self.executable_tokens_out is None
                                      else str(self.executable_tokens_out)),
            "executable_size_wei": str(self.executable_size_wei),
            "executable_error": self.executable_error,
            "trades": self.trades, "trades_2m": self.trades_2m,
            "curve_completed": self.completed,
            "state": self.state,
        }


__all__ = ["VERSION", "PONS_FEATURES", "FEATURE_WINDOWS", "MIN_AGE_S",
           "MIN_TRADES", "PAPER_SIZE_WEI", "TapePoint", "TokenTape",
           "PonsContext", "ContextError"]
