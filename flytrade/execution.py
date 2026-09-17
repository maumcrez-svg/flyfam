"""
Paper execution, accounting and the outcome -> reinforcement mapping.

Canonical amendment §6 and Fable addendum 8. One simple, versioned policy,
declared in full before it was ever run against a price series. Everything in
here is offline: there is no venue, no key, no order router, and
:class:`flytrade.market.ExecutionFeed` is the only object in the repository
that may read a bar after the decision cutoff.

## The policy, v1

============================  ==========================================
decision                      at the **close** of bar ``t``
execution                     at the **open** of bar ``t + DELAY_BARS``
delay                         1 bar, declared, never zero
sizing                        fixed notional, :data:`NOTIONAL`
exposure                      one open position, long only
fees                          :data:`FEE_BPS` basis points of traded value,
                              charged on entry and on exit
slippage                      :data:`SLIPPAGE_BPS` basis points, always
                              against the trader
horizon                       :data:`HORIZON_BARS` bars, then ``POLICY_CLOSE``
outcome                       net realised PnL, after both fees
============================  ==========================================

``SELL`` reduces existing exposure. It is never an unimplemented short: with no
position open, a decoded ``SELL`` is a ``POLICY_REJECT`` and is recorded as one.

A horizon expiry closes the position mechanically and is labelled
``POLICY_CLOSE``. It is **not** a neural ``SELL`` and the record keeps them
apart, because reporting a timer as a decision would be the easiest and least
honest way to inflate the number of decisions this system appears to make.

## Outcome to reinforcement

Reward and punishment depend on the **net realised** outcome only. Unrealised
price movement reinforces nothing, and no counterfactual reward is ever
computed for an instrument that was not chosen::

    r        = net_pnl / notional
    valence  = +1 if r > 0 else -1 if r < 0 else 0   (0 delivers nothing)
    amount   = min(|r| / REINFORCE_FULL_SCALE, REINFORCE_CAP)

``valence = +1`` addresses the PAM-innervated compartment and ``-1`` the
PPL1-innervated one, through the modulatory matrix, by calling
``MushroomBody.dopamine``. No weight is ever written directly.

Position sizing, thresholds, the horizon and the outcome rule are all fixed in
this module's constants and in ``docs/EXECUTION.md``, and were fixed before any
evaluation-period PnL existed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from . import market as MK

VERSION = "flytrade-exec-1"

#: bars between the decision and its fill. 1, declared, never 0.
DELAY_BARS = 1
#: bars a position is held before a mechanical POLICY_CLOSE
HORIZON_BARS = 8
#: currency value of one position
NOTIONAL = 1000.0
#: starting cash
INITIAL_CASH = 10000.0
#: commission, basis points of traded value, charged on entry and on exit
FEE_BPS = 5.0
#: execution slippage, basis points, always against the trader
SLIPPAGE_BPS = 5.0

#: net return on notional that maps to a full-strength dopamine event
REINFORCE_FULL_SCALE = 0.01
#: hard cap on the dopamine amount, whatever the outcome
REINFORCE_CAP = 1.0

BPS = 1e-4


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class CloseReason(str, Enum):
    """Why a position was closed. A timer is not a decision."""

    #: the decoder emitted SELL while the position was open
    NEURAL_SELL = "NEURAL_SELL"
    #: the evaluation horizon expired — mechanical, not a neural choice
    POLICY_CLOSE = "POLICY_CLOSE"
    #: D9(b): the same mechanical horizon expiry, under the ``fixed_hold``
    #: exit policy, where it is the **only** way an ordinary position closes.
    #: A separate member, not a relabelling: a log must say which policy the
    #: run was under without consulting its configuration.
    POLICY_CLOSE_FIXED_HOLD = "POLICY_CLOSE_FIXED_HOLD"
    #: the series ran out before the horizon did
    END_OF_DATA = "END_OF_DATA"


class RejectReason(str, Enum):
    """Why the execution policy refused a decoded action."""

    POSITION_OPEN = "POSITION_OPEN"
    NO_POSITION = "NO_POSITION"
    NO_FUTURE_BAR = "NO_FUTURE_BAR"
    INSUFFICIENT_CASH = "INSUFFICIENT_CASH"
    BAD_PRICE = "BAD_PRICE"
    #: D6, Fable addendum 4: the clock rule. There is not enough regular
    #: session left for delay + horizon, so the entry is refused before any
    #: price is looked at. Nothing crosses a session or a partition.
    SESSION_HORIZON = "SESSION_HORIZON"
    #: D9(b): the decoder emitted SELL while a fixed-hold position was open.
    #: The signal is real and is kept in the log; under this exit policy the
    #: execution policy refuses to act on it, so nothing is sold and the
    #: position runs to its declared horizon.
    FIXED_HOLD = "FIXED_HOLD"

    # D10. The curve route has two refusals a minute-bar market does not.
    #: the declared paper size would take the whole tradable allocation, so the
    #: buy would be partially filled and refunded. Refused rather than resized.
    CURVE_EXHAUSTED = "CURVE_EXHAUSTED"
    #: the market route is not priced at this instant — the curve completed and
    #: the position would have to be quoted on the unsupported post-graduation
    #: route. Refused, never quoted with the wrong adapter.
    ROUTE_UNAVAILABLE = "ROUTE_UNAVAILABLE"


@dataclass(frozen=True)
class Fill:
    """One executed side of a trade, with the price it actually got."""

    side: Side
    symbol: str
    bar_index: int
    ts: int
    reference_price: float      # the bar open, before slippage
    fill_price: float           # after slippage
    quantity: float
    fee: float
    #: D6: market minutes between the minute the policy asked for and the
    #: minute it got. 0 on the synthetic path, where the bar always exists.
    delay_minutes: int = 0
    #: "" when the fill landed where the policy asked; otherwise
    #: ``DELAYED_FILL`` or ``SESSION_CLOSE_FILL``. Never inferred later.
    flag: str = ""

    @property
    def value(self) -> float:
        return self.quantity * self.fill_price

    @property
    def slippage(self) -> float:
        """Modelled slippage on this execution, always against the trader."""
        d = self.fill_price - self.reference_price
        return abs(d) * self.quantity

    def as_dict(self) -> dict:
        return {"side": self.side.value, "symbol": self.symbol,
                "bar_index": self.bar_index, "ts": self.ts,
                "reference_price": round(self.reference_price, 8),
                "fill_price": round(self.fill_price, 8),
                "quantity": round(self.quantity, 10),
                "fee": round(self.fee, 8), "value": round(self.value, 8),
                "slippage": round(self.slippage, 8),
                "delay_minutes": int(self.delay_minutes), "flag": self.flag}


@dataclass
class Position:
    """The one open position. There is never more than one."""

    episode_id: int
    symbol: str
    stable_id: int
    entry: Fill
    horizon_bar: int
    #: D6: the session this position lives in. Nothing crosses a day.
    day: object = None

    @property
    def quantity(self) -> float:
        return self.entry.quantity

    def bars_held(self, bar_index: int) -> int:
        return bar_index - self.entry.bar_index

    def as_dict(self) -> dict:
        return {"episode_id": self.episode_id, "symbol": self.symbol,
                "stable_id": self.stable_id, "entry": self.entry.as_dict(),
                "horizon_bar": self.horizon_bar}


@dataclass(frozen=True)
class OutcomeRecord:
    """One completed decision/outcome cycle. The only source of reinforcement."""

    episode_id: int
    symbol: str
    stable_id: int
    entry: Fill
    exit: Fill
    close_reason: CloseReason
    gross_pnl: float
    fees: float
    net_pnl: float
    notional: float
    bars_held: int
    market_seconds_held: int
    execution_version: str = VERSION
    #: D6 §5: gross PnL at the **reference** prices, before slippage. The
    #: three-term reconciliation the amendment asks for is
    #: ``gross_reference_pnl - slippage - fees == net_pnl``; ``gross_pnl``
    #: keeps its Phase One meaning (at the fill prices, slippage already in)
    #: so that ``net_pnl == gross_pnl - fees`` stays true as well.
    gross_reference_pnl: float = 0.0
    slippage: float = 0.0
    #: elapsed **market minutes** between entry and exit fills, on the
    #: historical path. Row distance is never used for this.
    market_minutes_held: int = 0

    @property
    def return_on_notional(self) -> float:
        return self.net_pnl / self.notional if self.notional else 0.0

    def as_dict(self) -> dict:
        return {
            "episode_id": self.episode_id, "symbol": self.symbol,
            "stable_id": self.stable_id, "entry": self.entry.as_dict(),
            "exit": self.exit.as_dict(),
            "close_reason": self.close_reason.value,
            "gross_pnl": round(self.gross_pnl, 8),
            "gross_reference_pnl": round(self.gross_reference_pnl, 8),
            "slippage": round(self.slippage, 8),
            "fees": round(self.fees, 8), "net_pnl": round(self.net_pnl, 8),
            "notional": self.notional, "bars_held": self.bars_held,
            "market_seconds_held": self.market_seconds_held,
            "market_minutes_held": self.market_minutes_held,
            "entry_flag": self.entry.flag, "exit_flag": self.exit.flag,
            "return_on_notional": round(self.return_on_notional, 10),
            "execution_version": self.execution_version,
        }


@dataclass(frozen=True)
class Rejection:
    """A decoded action the policy refused. Recorded, never discarded."""

    action: str
    symbol: str
    bar_index: int
    reason: RejectReason

    def as_dict(self) -> dict:
        return {"action": self.action, "symbol": self.symbol,
                "bar_index": self.bar_index, "reason": self.reason.value}


@dataclass
class Account:
    """Cash, inventory and realised PnL. The accounting identity is checked."""

    cash: float = INITIAL_CASH
    initial_cash: float = INITIAL_CASH
    realized_pnl: float = 0.0
    fees_paid: float = 0.0
    #: D6 §5: modelled slippage, accumulated as its own term so that
    #: gross - fees - slippage = net can be checked rather than asserted
    slippage_paid: float = 0.0
    trades: int = 0
    position: Position | None = None

    def equity(self, mark: float | None = None) -> float:
        """Cash plus inventory marked at ``mark`` (the bar close, when given)."""
        if self.position is None:
            return self.cash
        if mark is None:
            mark = self.position.entry.fill_price
        return self.cash + self.position.quantity * mark

    def check(self) -> None:
        """When flat, cash must be exactly initial cash plus realised PnL."""
        if self.position is None:
            drift = abs(self.cash - (self.initial_cash + self.realized_pnl))
            if drift > 1e-6:
                raise AssertionError(
                    f"accounting broken: cash {self.cash:.8f} != initial "
                    f"{self.initial_cash:.8f} + realised "
                    f"{self.realized_pnl:.8f} (drift {drift:.3e})")

    def as_dict(self) -> dict:
        return {"cash": round(self.cash, 8),
                "initial_cash": self.initial_cash,
                "realized_pnl": round(self.realized_pnl, 8),
                "fees_paid": round(self.fees_paid, 8),
                "slippage_paid": round(self.slippage_paid, 8),
                "equity": round(self.equity(), 8),
                "trades": self.trades,
                "position": self.position.as_dict() if self.position else None}


class ExecutionPolicy:
    """Paper execution, v1. Declared in full before it ever saw a price."""

    version = VERSION

    def __init__(self, feed: MK.ExecutionFeed, *,
                 notional: float = NOTIONAL,
                 fee_bps: float = FEE_BPS,
                 slippage_bps: float = SLIPPAGE_BPS,
                 delay_bars: int = DELAY_BARS,
                 horizon_bars: int = HORIZON_BARS,
                 initial_cash: float = INITIAL_CASH,
                 reinforce_full_scale: float = REINFORCE_FULL_SCALE,
                 reinforce_cap: float = REINFORCE_CAP):
        if delay_bars < 1:
            raise ValueError("execution may not happen on the decision bar: "
                             "delay_bars must be at least 1")
        if horizon_bars < 1:
            raise ValueError("horizon_bars must be at least 1")
        self.feed = feed
        self.notional = float(notional)
        self.fee_bps = float(fee_bps)
        self.slippage_bps = float(slippage_bps)
        self.delay_bars = int(delay_bars)
        self.horizon_bars = int(horizon_bars)
        self.reinforce_full_scale = float(reinforce_full_scale)
        self.reinforce_cap = float(reinforce_cap)
        self.account = Account(cash=float(initial_cash),
                               initial_cash=float(initial_cash))
        self.outcomes: list[OutcomeRecord] = []
        self.rejections: list[Rejection] = []

    # -- prices -----------------------------------------------------------

    def execution_bar(self, decision_bar: int) -> int:
        return decision_bar + self.delay_bars

    def _fill_price(self, reference: float, side: Side) -> float:
        s = self.slippage_bps * BPS
        return reference * (1.0 + s) if side is Side.BUY else reference * (1.0 - s)

    def _fee(self, quantity: float, price: float) -> float:
        return abs(quantity * price) * self.fee_bps * BPS

    # -- opening ----------------------------------------------------------

    def reject(self, action: str, symbol: str, bar_index: int,
               reason: RejectReason) -> Rejection:
        r = Rejection(action=action, symbol=symbol, bar_index=bar_index,
                      reason=reason)
        self.rejections.append(r)
        return r

    def open_long(self, *, episode_id: int, symbol: str, stable_id: int,
                  decision_bar: int) -> Position | Rejection:
        """Execute a decoded BUY at the open of the next bar."""
        if self.account.position is not None:
            return self.reject("BUY", symbol, decision_bar,
                               RejectReason.POSITION_OPEN)
        i = self.execution_bar(decision_bar)
        if i >= self.feed.n_bars(symbol):
            return self.reject("BUY", symbol, decision_bar,
                               RejectReason.NO_FUTURE_BAR)
        bar = self.feed.bar(symbol, i)
        if bar.is_nan or bar.open <= 0:
            return self.reject("BUY", symbol, decision_bar,
                               RejectReason.BAD_PRICE)
        price = self._fill_price(bar.open, Side.BUY)
        qty = self.notional / price
        fee = self._fee(qty, price)
        if qty * price + fee > self.account.cash:
            return self.reject("BUY", symbol, decision_bar,
                               RejectReason.INSUFFICIENT_CASH)
        entry = Fill(side=Side.BUY, symbol=symbol, bar_index=i, ts=bar.ts,
                     reference_price=bar.open, fill_price=price,
                     quantity=qty, fee=fee)
        self.account.cash -= qty * price + fee
        self.account.fees_paid += fee
        self.account.position = Position(
            episode_id=int(episode_id), symbol=symbol,
            stable_id=int(stable_id), entry=entry,
            horizon_bar=i + self.horizon_bars)
        return self.account.position

    # -- closing ----------------------------------------------------------

    def due_for_horizon(self, bar_index: int) -> bool:
        p = self.account.position
        return p is not None and bar_index >= p.horizon_bar

    def close(self, *, decision_bar: int, reason: CloseReason
              ) -> OutcomeRecord | Rejection:
        """Close the open position at the open of the next bar."""
        p = self.account.position
        if p is None:
            return self.reject("SELL", "", decision_bar,
                               RejectReason.NO_POSITION)
        i = self.execution_bar(decision_bar)
        n = self.feed.n_bars(p.symbol)
        if i >= n:
            i = n - 1
            reason = CloseReason.END_OF_DATA
        bar = self.feed.bar(p.symbol, i)
        if bar.is_nan or bar.open <= 0:
            return self.reject("SELL", p.symbol, decision_bar,
                               RejectReason.BAD_PRICE)
        price = self._fill_price(bar.open, Side.SELL)
        fee = self._fee(p.quantity, price)
        exit_fill = Fill(side=Side.SELL, symbol=p.symbol, bar_index=i,
                         ts=bar.ts, reference_price=bar.open,
                         fill_price=price, quantity=p.quantity, fee=fee)
        return self._settle(p, exit_fill, reason)

    # -- the accounting tail, shared with the historical policy ------------

    def _settle(self, p: Position, exit_fill: Fill, reason: CloseReason, *,
                market_minutes: int = 0) -> OutcomeRecord:
        """Book one closed round trip and reconcile it three ways.

        ``gross_pnl`` is at the fill prices, so ``net == gross - fees`` — the
        Phase One identity, unchanged. ``gross_reference_pnl`` is the same PnL
        at the unslipped reference prices, so amendment §5's reconciliation
        ``gross_reference - slippage - fees == net`` holds as well, with the
        slippage as its own term rather than hidden inside the gross.
        """
        price, fee = exit_fill.fill_price, exit_fill.fee
        gross = p.quantity * (price - p.entry.fill_price)
        gross_ref = p.quantity * (exit_fill.reference_price
                                  - p.entry.reference_price)
        slippage = p.entry.slippage + exit_fill.slippage
        fees = p.entry.fee + fee
        net = gross - fees
        self.account.cash += p.quantity * price - fee
        self.account.fees_paid += fee
        self.account.slippage_paid += slippage
        self.account.realized_pnl += net
        self.account.trades += 1
        self.account.position = None
        self.account.check()

        rec = OutcomeRecord(
            episode_id=p.episode_id, symbol=p.symbol, stable_id=p.stable_id,
            entry=p.entry, exit=exit_fill, close_reason=reason,
            gross_pnl=gross, fees=fees, net_pnl=net,
            notional=self.notional,
            bars_held=exit_fill.bar_index - p.entry.bar_index,
            market_seconds_held=exit_fill.ts - p.entry.ts,
            gross_reference_pnl=gross_ref, slippage=slippage,
            market_minutes_held=int(market_minutes))
        self.outcomes.append(rec)
        return rec

    # -- reinforcement ----------------------------------------------------

    def reinforcement(self, outcome: OutcomeRecord) -> tuple[int, float]:
        """(valence, amount) for one realised outcome. Never unrealised.

        ``valence`` +1 routes the dopamine event to the PAM-innervated
        compartment and -1 to the PPL1-innervated one; 0 means deliver nothing.
        ``amount`` is the dopamine strength, proportional to the net return on
        notional and clipped at the declared cap.
        """
        r = outcome.return_on_notional
        if r == 0.0:
            return 0, 0.0
        valence = 1 if r > 0 else -1
        amount = min(abs(r) / self.reinforce_full_scale, self.reinforce_cap)
        return valence, float(amount)

    # -- reporting --------------------------------------------------------

    def as_dict(self) -> dict:
        return {"version": self.version, "notional": self.notional,
                "fee_bps": self.fee_bps, "slippage_bps": self.slippage_bps,
                "delay_bars": self.delay_bars,
                "horizon_bars": self.horizon_bars,
                "initial_cash": self.account.initial_cash,
                "reinforce_full_scale": self.reinforce_full_scale,
                "reinforce_cap": self.reinforce_cap}

    def stats(self) -> dict:
        by_reason: dict[str, int] = {}
        for r in self.rejections:
            by_reason[r.reason.value] = by_reason.get(r.reason.value, 0) + 1
        closes: dict[str, int] = {}
        for o in self.outcomes:
            closes[o.close_reason.value] = closes.get(o.close_reason.value, 0) + 1
        flags: dict[str, int] = {}
        for o in self.outcomes:
            for f in (o.entry.flag, o.exit.flag):
                if f:
                    flags[f] = flags.get(f, 0) + 1
        wins = sum(1 for o in self.outcomes if o.net_pnl > 0)
        gross_ref = sum(o.gross_reference_pnl for o in self.outcomes)
        slip = sum(o.slippage for o in self.outcomes)
        return {
            "trades": len(self.outcomes),
            "wins": wins, "losses": sum(1 for o in self.outcomes if o.net_pnl < 0),
            "flat": sum(1 for o in self.outcomes if o.net_pnl == 0),
            "gross_pnl": sum(o.gross_pnl for o in self.outcomes),
            "gross_reference_pnl": gross_ref,
            "slippage_paid": slip,
            "fees_paid": self.account.fees_paid,
            "net_pnl": self.account.realized_pnl,
            "reconciliation": {
                "gross_reference_pnl": gross_ref,
                "minus_fees": self.account.fees_paid,
                "minus_slippage": slip,
                "equals_net_pnl": gross_ref - self.account.fees_paid - slip,
                "booked_net_pnl": self.account.realized_pnl,
                "residual": (gross_ref - self.account.fees_paid - slip
                             - self.account.realized_pnl)},
            "cash": self.account.cash,
            "equity": self.account.equity(),
            "close_reasons": closes,
            "fill_flags": flags,
            "rejections": by_reason,
            "rejections_total": len(self.rejections),
        }
