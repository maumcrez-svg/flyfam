"""Paper fills on the PONS v2 curve route. Simulated, and never a transaction.

docs/SPEC.md D10 addendum 12 and amendment §10. The point of this module is
that a fill here costs what the curve would actually have charged: the base
fee, the creator tax, the snipe tax with its decay, the price impact of our own
size, and three declared gas constants. ``FEE_BPS`` and ``SLIPPAGE_BPS`` of
:mod:`flytrade.execution` are **not used** on this route.

**The fill rule.** A decision at cutoff ``t`` fills at the reconstructed state
of the first block whose timestamp is at or after ``t + latency`` (2 s,
declared). The exit is the same rule at ``t_entry + horizon``. Nothing is ever
priced at a state the decision could not have reached.

**Our own delta is carried.** The buy's reserve change is applied to the tape's
state for our own account (the donor's ``ownNet``), so the exit quote sees our
own impact *plus* the external flow that actually happened. The recorded public
market is unchanged by it: a paper position does not move real reserves and
this wave never claims that it does.

**The accounting identity is kept without changing the account.** The curve
fees and the creator tax go into :attr:`Fill.fee` together with the gas, and
the price impact goes into the gap between ``reference_price`` and
``fill_price``, which is what :class:`flytrade.execution.Account` already calls
slippage. So ``gross_reference − slippage − fees = net`` and
``net = gross − fees`` both still hold, and the existing invariant tests still
bite.

**An exit that is not available is not a loss.** A curve that completed before
the horizon is ``UNRESOLVED(ROUTE_TRANSITION)``; a horizon beyond the data is
``UNRESOLVED(COVERAGE)``; a settlement whose blocks are not yet confirmed is
``PENDING_CONFIRMATION``. None of the three settles an outcome, and none of
them teaches anything.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import execution as X
from .context import PAPER_SIZE_WEI, TokenTape
from .curve import (BuyQuote, CurveState, QuoteError, SellQuote,
                    quote_curve_buy, quote_curve_sell)

VERSION = "pons_paper_v1"

WEI = 10 ** 18

#: Addendum 12: observation/decision/execution latency, in seconds of chain
#: time. A fill may not use a state the decision could not have reached.
LATENCY_S = 2

#: The fixed holding horizon, in seconds of chain time (amendment §9: fifteen
#: minutes, a product-test setting and not an optimised one).
HORIZON_S = 900

#: Gas, in wei, from the donor's calibration medians over 40 buy and 40 sell
#: receipts (``artifacts/curve-simulation/gas.json``). ``approval`` is a
#: 60,000-gas **assumption** at the same gas price, not a receipt, and is
#: recorded as such.
GAS_BUY_WEI = 26_513_686_360_000
GAS_SELL_WEI = 21_543_833_760_000
GAS_APPROVAL_WEI = 16_104_600_000_000

#: Why a position is still open with no outcome. Never a PnL.
ROUTE_TRANSITION = "ROUTE_TRANSITION"
COVERAGE = "COVERAGE"
PENDING_CONFIRMATION = "PENDING_CONFIRMATION"


class Unresolved(RuntimeError):
    """The exit could not be priced. The exposure is retained, not written off."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason if not detail else f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class FillPlan:
    """What a decision would actually get, before anything is booked."""

    block_number: int
    block_timestamp: int
    state: CurveState
    quote: BuyQuote | SellQuote
    reference_price: float
    fill_price: float
    quantity: float
    fee: float
    gas_wei: int
    delay_s: int

    def as_dict(self) -> dict:
        return {"block_number": self.block_number,
                "block_timestamp": self.block_timestamp,
                "reference_price": self.reference_price,
                "fill_price": self.fill_price, "quantity": self.quantity,
                "fee": self.fee, "gas_wei": str(self.gas_wei),
                "delay_s": self.delay_s}


def fill_at(tape: TokenTape, when: int, clock) -> dict:
    """The block and the curve state a fill at ``when`` would actually get.

    The whole of the latency rule: a decision at ``t`` may only be filled at a
    block the chain produced at or after ``t + latency``. ``clock`` names that
    block (:class:`flytrade.pons.collector.BlockClock`); the state is the tape
    reconstructed through every event at or before that block's timestamp, so a
    curve nobody traded in the meantime fills at the state it was left in and a
    busy one fills at the state the intervening trades produced. Neither is the
    last price we happen to hold, and neither looks forward.

    Raises :class:`Unresolved` with ``COVERAGE`` past the end of the data, and
    with ``ROUTE_TRANSITION`` once the curve has completed.
    """
    when = int(when)
    # Order matters: a curve that completed and a window that ran out are two
    # different answers, and the completion is the more specific one. Asking
    # about coverage first would report every route transition as missing data.
    if tape.completed_at is not None and when > tape.completed_at:
        raise Unresolved(ROUTE_TRANSITION,
                         f"the curve completed at {tape.completed_at}")
    if tape.coverage_end_ts is not None and when > tape.coverage_end_ts:
        raise Unresolved(COVERAGE,
                         f"{when} is past the dataset's coverage "
                         f"({tape.coverage_end_ts})")
    if tape.coverage_end_ts is None and when > tape.coverage_end():
        raise Unresolved(COVERAGE,
                         f"{when} is past the token's last known block "
                         f"({tape.coverage_end()})")
    at = clock.block_at_or_after(when)
    if not at:
        raise Unresolved(COVERAGE, f"no block at or after {when}")
    stamp = int(at["block_timestamp"])
    if tape.completed_by(stamp):
        raise Unresolved(ROUTE_TRANSITION, "the curve completed before the fill")
    state = tape.state_at(stamp)
    if state is None:
        raise Unresolved(COVERAGE, f"no reconstructed state at {stamp}")
    return {"block_number": int(at["block_number"]), "block_timestamp": stamp,
            "state": state, "interpolated": bool(at["interpolated"]),
            "precision_s": float(at["precision_s"])}


def reinforce_full_scale_from_config(config: dict | None) -> float:
    """The per-experiment reinforcement full scale, or the repository default.

    D11 amendment §5 makes ``reinforce_full_scale`` a **per-experiment**
    parameter instead of a module constant, so this venue's scale can be
    calibrated and frozen without moving
    :data:`flytrade.execution.REINFORCE_FULL_SCALE`, which stays 0.01 and keeps
    every D5-D10 code path — the IBM historical loop included — byte-identical.

    Read in this order from the experiment's ``config.json``:

    1. ``reinforcement.reinforce_full_scale``, when a later configuration
       spells the parameter by its own name;
    2. ``reinforcement.new_full_scale``, which is what the D11 registration
       committed as a ``null`` before the calibration and what the calibration
       commit filled in. **Declared decision:** the D11 config was registered
       with that key before this reader existed, and it is read rather than
       renamed, because renaming it would mean editing a registered file after
       its numbers were computed;
    3. the repository default, when neither key carries a value.

    ``None`` and a missing ``reinforcement`` block both mean "the default".
    A present but non-positive value is refused rather than silently ignored:
    a zero scale would send every outcome to the cap and a negative one would
    invert the punishment.
    """
    block = ((config or {}).get("reinforcement") or {})
    for key in ("reinforce_full_scale", "new_full_scale"):
        value = block.get(key)
        if value is None:
            continue
        value = float(value)
        if not value > 0.0:
            raise ValueError(
                f"reinforcement.{key} must be positive, got {value!r}")
        return value
    return float(X.REINFORCE_FULL_SCALE)


class PonsPaperExecution(X.ExecutionPolicy):
    """One open position, priced on the curve, settled in ETH.

    Subclasses :class:`flytrade.execution.ExecutionPolicy` for its
    :meth:`_settle` — the three-way reconciliation every previous wave used —
    and for :meth:`reinforcement`, which is the existing normalised mapping and
    is **not** re-derived here. Everything that touches a price is this
    module's.
    """

    version = VERSION

    def __init__(self, *, size_wei: int = PAPER_SIZE_WEI,
                 latency_s: int = LATENCY_S, horizon_s: int = HORIZON_S,
                 gas_buy_wei: int = GAS_BUY_WEI,
                 gas_sell_wei: int = GAS_SELL_WEI,
                 gas_approval_wei: int = GAS_APPROVAL_WEI,
                 initial_cash_wei: int = 10 * WEI,
                 reinforce_full_scale: float = X.REINFORCE_FULL_SCALE,
                 reinforce_cap: float = X.REINFORCE_CAP):
        self.feed = None
        self.size_wei = int(size_wei)
        self.latency_s = int(latency_s)
        self.horizon_s = int(horizon_s)
        self.gas_buy_wei = int(gas_buy_wei)
        self.gas_sell_wei = int(gas_sell_wei)
        self.gas_approval_wei = int(gas_approval_wei)
        self.notional = self.size_wei / WEI
        self.fee_bps = 0.0            # not used on this route (addendum 12)
        self.slippage_bps = 0.0       # not used on this route (addendum 12)
        self.delay_bars = 1
        self.horizon_bars = 1
        self.reinforce_full_scale = float(reinforce_full_scale)
        self.reinforce_cap = float(reinforce_cap)
        self.account = X.Account(cash=initial_cash_wei / WEI,
                                 initial_cash=initial_cash_wei / WEI)
        self.outcomes: list[X.OutcomeRecord] = []
        self.rejections: list[X.Rejection] = []
        self.unresolved: list[dict] = []
        #: the reserve delta our own paper position has taken out of the curve
        self.own_delta: dict = {}
        self.entry_quote: BuyQuote | None = None
        self.entry_tokens_wei: int | None = None
        self.entry_cutoff: int | None = None
        self.horizon_ts: int | None = None

    # ------------------------------------------------------------ pricing
    def carry(self, tape: TokenTape, state: CurveState) -> CurveState:
        """``state`` with our own paper position's reserve delta applied.

        The donor's ``ownNet``. Our buy took tokens out and put quote in for
        *our* account, so the exit quote must see its own impact on top of the
        external flow that actually happened. The recorded public market is
        untouched: this delta exists only in this object.
        """
        delta = self.own_delta.get(tape.curve)
        if delta is not None:
            state = CurveState(
                quote_reserve=state.quote_reserve + delta["quote"],
                token_reserve=state.token_reserve - delta["tokens"],
                real_quote_reserve=state.real_quote_reserve + delta["quote"],
                sellable_tokens=max(state.sellable_tokens - delta["tokens"], 0),
                fee_bps=state.fee_bps, creator_tax_bps=state.creator_tax_bps,
                snipe_tax_bps=0, graduated=state.graduated)
        return state

    def plan_buy(self, tape: TokenTape, cutoff: int, clock) -> FillPlan:
        """Price the entry at the first block at or after ``cutoff + latency``."""
        when = int(cutoff) + self.latency_s
        at = fill_at(tape, when, clock)
        point, state = at["block_number"], self.carry(tape, at["state"])
        quote = quote_curve_buy(state, self.size_wei)
        if quote.refund > 0:
            raise Unresolved("WOULD_EXHAUST_CURVE",
                             f"refund {quote.refund} on a {self.size_wei} buy")
        tokens = quote.tokens_out / WEI
        net_in = quote.net_into_curve
        fees = quote.fee_base + quote.fee_creator + quote.fee_snipe
        return FillPlan(
            block_number=point, block_timestamp=at["block_timestamp"],
            state=state, quote=quote,
            reference_price=state.quote_reserve / state.token_reserve,
            fill_price=(net_in / WEI) / tokens,
            quantity=tokens,
            fee=(fees + self.gas_buy_wei) / WEI,
            gas_wei=self.gas_buy_wei,
            delay_s=at["block_timestamp"] - int(cutoff))

    def plan_sell(self, tape: TokenTape, when: int, tokens: float, clock, *,
                  tokens_wei: int | None = None) -> FillPlan:
        """Price the exit. ``tokens_wei`` is the exact integer the buy produced.

        The float ``quantity`` on the position is for the account's arithmetic;
        the curve is asked in the integer it actually handed us, so a round trip
        sells exactly what it bought and no rounding creeps into the quote.
        """
        at = fill_at(tape, int(when), clock)
        state = self.carry(tape, at["state"])
        tokens_in = int(tokens_wei if tokens_wei is not None
                        else round(tokens * WEI))
        try:
            quote = quote_curve_sell(state, tokens_in)
        except QuoteError as exc:
            raise Unresolved(exc.code, exc.detail) from None
        gross = quote.gross_quote_out
        fees = quote.fee_base + quote.fee_creator
        return FillPlan(
            block_number=at["block_number"], block_timestamp=at["block_timestamp"],
            state=state, quote=quote,
            reference_price=state.quote_reserve / state.token_reserve,
            fill_price=(gross / WEI) / tokens,
            quantity=tokens,
            fee=(fees + self.gas_sell_wei + self.gas_approval_wei) / WEI,
            gas_wei=self.gas_sell_wei + self.gas_approval_wei,
            delay_s=at["block_timestamp"] - int(when))

    # ------------------------------------------------------------ opening
    def open_long(self, *, episode_id: int, tape: TokenTape, stable_id: int,
                  cutoff: int, clock):
        """Execute a decoded BUY. Returns a ``Position``, ``Rejection`` or raises."""
        if self.account.position is not None:
            return self.reject("BUY", tape.token, int(cutoff),
                               X.RejectReason.POSITION_OPEN)
        try:
            plan = self.plan_buy(tape, cutoff, clock)
        except Unresolved as exc:
            if exc.reason == "WOULD_EXHAUST_CURVE":
                return self.reject("BUY", tape.token, int(cutoff),
                                   X.RejectReason.CURVE_EXHAUSTED)
            return self.reject("BUY", tape.token, int(cutoff),
                               X.RejectReason.NO_FUTURE_BAR
                               if exc.reason == COVERAGE
                               else X.RejectReason.ROUTE_UNAVAILABLE)
        spend = plan.quantity * plan.fill_price + plan.fee
        if spend > self.account.cash:
            return self.reject("BUY", tape.token, int(cutoff),
                               X.RejectReason.INSUFFICIENT_CASH)
        entry = X.Fill(side=X.Side.BUY, symbol=tape.token,
                       bar_index=plan.block_number, ts=plan.block_timestamp,
                       reference_price=plan.reference_price,
                       fill_price=plan.fill_price, quantity=plan.quantity,
                       fee=plan.fee, delay_minutes=plan.delay_s, flag="")
        self.account.cash -= spend
        self.account.fees_paid += plan.fee
        self.account.position = X.Position(
            episode_id=int(episode_id), symbol=tape.token,
            stable_id=int(stable_id), entry=entry,
            horizon_bar=plan.block_number, day=tape.curve)
        quote = plan.quote
        self.own_delta[tape.curve] = {"quote": quote.net_into_curve,
                                      "tokens": quote.tokens_out}
        self.entry_quote = quote
        self.entry_tokens_wei = quote.tokens_out
        self.entry_cutoff = int(cutoff)
        self.horizon_ts = plan.block_timestamp + self.horizon_s
        return self.account.position

    # -------------------------------------------------------------- marks
    def mark(self, tape: TokenTape, cutoff: int, clock) -> dict:
        """What the open position would fetch right now. A mark, never a reward.

        It is written into every tick's record while a position is open and it
        never reaches reinforcement: the learning rule takes the *settled* net
        outcome and nothing else (amendment §9).
        """
        position = self.account.position
        if position is None:
            return {}
        try:
            plan = self.plan_sell(tape, int(cutoff), position.quantity, clock,
                                  tokens_wei=self.entry_tokens_wei)
        except Unresolved as exc:
            return {"cutoff_ts": int(cutoff), "available": False,
                    "reason": exc.reason, "detail": exc.detail}
        value = plan.quantity * plan.fill_price - plan.fee
        cost = position.quantity * position.entry.fill_price + position.entry.fee
        return {"cutoff_ts": int(cutoff), "available": True,
                "block_number": plan.block_number,
                "mark_value_eth": value, "cost_eth": cost,
                "unrealised_eth": value - cost,
                "marginal_price": plan.reference_price,
                "is_a_reward": False}

    # ------------------------------------------------------------ closing
    def due_for_horizon(self, cutoff: int) -> bool:
        return (self.account.position is not None and self.horizon_ts is not None
                and int(cutoff) >= self.horizon_ts)

    def close(self, *, tape: TokenTape, reason: X.CloseReason, cutoff: int,
              clock) -> X.OutcomeRecord | X.Rejection:
        """Close at the horizon. Raises :class:`Unresolved` rather than inventing."""
        position = self.account.position
        if position is None:
            return self.reject("SELL", "", int(cutoff),
                               X.RejectReason.NO_POSITION)
        plan = self.plan_sell(tape, self.horizon_ts, position.quantity, clock,
                              tokens_wei=self.entry_tokens_wei)
        exit_fill = X.Fill(side=X.Side.SELL, symbol=position.symbol,
                           bar_index=plan.block_number, ts=plan.block_timestamp,
                           reference_price=plan.reference_price,
                           fill_price=plan.fill_price, quantity=plan.quantity,
                           fee=plan.fee, delay_minutes=plan.delay_s, flag="")
        seconds = exit_fill.ts - position.entry.ts
        outcome = self._settle(position, exit_fill, reason,
                               market_minutes=seconds // 60)
        self.own_delta.pop(tape.curve, None)
        self.entry_quote = None
        self.entry_tokens_wei = None
        self.horizon_ts = None
        self.entry_cutoff = None
        return outcome

    def record_unresolved(self, *, episode_id: int, token: str, reason: str,
                          detail: str = "", cutoff: int = 0) -> dict:
        """The exposure is retained and nothing is settled. Recorded, not dropped."""
        entry = {"episode_id": int(episode_id), "token": token,
                 "reason": reason, "detail": detail, "cutoff_ts": int(cutoff),
                 "settled": False, "is_a_loss": False}
        self.unresolved.append(entry)
        return entry

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "size_wei": str(self.size_wei),
            "notional_eth": self.notional,
            "latency_s": self.latency_s,
            "horizon_s": self.horizon_s,
            "gas_buy_wei": str(self.gas_buy_wei),
            "gas_sell_wei": str(self.gas_sell_wei),
            "gas_approval_wei": str(self.gas_approval_wei),
            "gas_source": ("donor calibration medians over 40 buy and 40 sell "
                           "receipts; the approval leg is a 60,000-gas "
                           "assumption at the same gas price, not a receipt"),
            "fee_bps_unused": True, "slippage_bps_unused": True,
            "cost_model": ("curve base fee + creator tax + decaying snipe tax "
                           "into `fees` with the gas; price impact into "
                           "`slippage` as the gap between the pre-trade "
                           "marginal price and the achieved price"),
            "initial_cash_eth": self.account.initial_cash,
            "reinforce_full_scale": self.reinforce_full_scale,
            "reinforce_cap": self.reinforce_cap,
            "own_impact_carried": True,
            "changes_the_public_market": False,
            "unresolved_reasons": [ROUTE_TRANSITION, COVERAGE,
                                   PENDING_CONFIRMATION],
        }


__all__ = ["VERSION", "LATENCY_S", "HORIZON_S", "GAS_BUY_WEI", "GAS_SELL_WEI",
           "GAS_APPROVAL_WEI", "ROUTE_TRANSITION", "COVERAGE",
           "PENDING_CONFIRMATION", "Unresolved", "FillPlan",
           "PonsPaperExecution", "fill_at", "WEI"]
