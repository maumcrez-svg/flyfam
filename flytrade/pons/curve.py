"""The PONS v2 bonding curve: its quote, and its state reconstructed from events.

Two things live here, and they are separate on purpose.

**The quote** is an integer-exact port of the donor's ``src/curve-quotes.ts``,
itself a port of the frozen ``PonsV2BondingCurveMath.sol`` and the ``buy`` /
``sell`` bodies of ``PonsV2BondingCurve.sourcify.sol`` (both copied to
``experiments/d10/evidence/`` with their sha256). Everything is Python ``int``,
which is the arbitrary-precision integer the ``uint256`` arithmetic needs;
every division is a floor division on non-negative operands, matching Solidity
and the donor's BigInt, and the one expression that can go negative
(:func:`_impact_bps`) truncates toward zero as JavaScript BigInt does rather
than flooring. docs/SPEC.md D10 addendum 12.

**The reconstruction** replays the curve's own events from a calibrated
initial state (addendum 8). It is not a model: each ``CurveBuy`` and
``CurveSell`` is *checked* against the constant product before it is applied,
so a state that drifts is an error, not a silent approximation.

Nothing in this module reads the network, and nothing in it knows what an
outcome is.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

BPS = 10_000
UINT256_MAX = (1 << 256) - 1

#: The decay is fourteen successive halvings spread evenly across the window,
#: by right shift, anchored at ``launchedAt``. PonsV2BondingCurve.sourcify.sol
#: ``currentSnipeTaxBps``.
SNIPE_HALVINGS = 14


class QuoteError(ValueError):
    """A quote could not be produced. The code is the donor's code."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(code if not detail else f"{code}: {detail}")
        self.code = code
        self.detail = detail


class ReconstructionError(ValueError):
    """The event stream does not reproduce the curve's arithmetic."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(code if not detail else f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _uint(value: int) -> int:
    value = int(value)
    if value < 0 or value > UINT256_MAX:
        raise QuoteError("QUOTE_UINT256_RANGE", str(value))
    return value


def _mul(a: int, b: int) -> int:
    return _uint(int(a) * int(b))


def _truncdiv(a: int, b: int) -> int:
    """Division truncated toward zero, as Solidity and BigInt do."""
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q


@dataclass(frozen=True)
class CurveState:
    """Everything a quote needs, all of it exact integers.

    ``quote_reserve`` includes the phantom (virtual) reserve seeded at deploy;
    ``real_quote_reserve`` is the part actually backed by ETH, which is what a
    sell can be paid out of. ``sellable_tokens`` is the tradable allocation:
    the balance above ``reservedTokens``, which belongs to the graduated pool.
    """

    quote_reserve: int
    token_reserve: int
    real_quote_reserve: int
    sellable_tokens: int
    fee_bps: int
    creator_tax_bps: int
    snipe_tax_bps: int = 0
    graduated: bool = False

    @property
    def phantom_quote(self) -> int:
        return self.quote_reserve - self.real_quote_reserve

    @property
    def reserved_tokens(self) -> int:
        return self.token_reserve - self.sellable_tokens

    @property
    def marginal_price(self) -> float:
        """quote per token at the margin, phantom reserve included.

        A float, and only ever a *feature*: every amount that becomes money
        goes through the integer quote. It is not the last trade price and it
        is not an executable price (amendment section 6).
        """
        if self.token_reserve <= 0:
            return 0.0
        return self.quote_reserve / self.token_reserve

    def with_snipe(self, snipe_tax_bps: int) -> "CurveState":
        return replace(self, snipe_tax_bps=int(snipe_tax_bps))

    def as_dict(self) -> dict:
        return {
            "quote_reserve": str(self.quote_reserve),
            "token_reserve": str(self.token_reserve),
            "real_quote_reserve": str(self.real_quote_reserve),
            "sellable_tokens": str(self.sellable_tokens),
            "fee_bps": self.fee_bps,
            "creator_tax_bps": self.creator_tax_bps,
            "snipe_tax_bps": self.snipe_tax_bps,
            "graduated": self.graduated,
        }


def snipe_tax_bps(start_bps: int, window_seconds: int, elapsed_seconds: int) -> int:
    """``currentSnipeTaxBps`` for a non-exempt recipient, ported exactly.

    Zero when the tax is disabled or the window has closed; otherwise
    ``start >> ((elapsed * 14) // window)``. Never assumed zero: a fill two
    seconds after launch really does pay it.
    """
    start_bps = int(start_bps)
    window_seconds = int(window_seconds)
    elapsed_seconds = int(elapsed_seconds)
    if start_bps == 0 or window_seconds <= 0:
        return 0
    if elapsed_seconds >= window_seconds:
        return 0
    if elapsed_seconds < 0:
        raise QuoteError("SNIPE_ELAPSED_NEGATIVE", str(elapsed_seconds))
    return start_bps >> ((elapsed_seconds * SNIPE_HALVINGS) // window_seconds)


def _validate(state: CurveState) -> None:
    for value in (state.quote_reserve, state.token_reserve,
                  state.real_quote_reserve, state.sellable_tokens,
                  state.fee_bps, state.creator_tax_bps, state.snipe_tax_bps):
        _uint(value)
    if state.graduated or state.sellable_tokens == 0:
        raise QuoteError("CURVE_REQUIRES_V4")
    if (state.quote_reserve == 0 or state.token_reserve == 0
            or state.sellable_tokens > state.token_reserve
            or state.real_quote_reserve > state.quote_reserve
            or state.fee_bps + state.creator_tax_bps > 9_900):
        raise QuoteError("CURVE_STATE_INVALID")


def _amount_out(amount_in: int, reserve_in: int, reserve_out: int) -> int:
    """``PonsV2BondingCurveMath.getAmountOut`` with ``feeBps = 0``.

    The fee legs come off the input before this is called, exactly as ``buy``
    does, so the curve itself is priced fee-free.
    """
    if amount_in <= 0:
        raise QuoteError("QUOTE_ZERO_INPUT")
    weighted = _mul(amount_in, BPS)
    value = _mul(weighted, reserve_out) // _uint(_mul(reserve_in, BPS) + weighted)
    if value == 0:
        raise QuoteError("QUOTE_DUST_OUTPUT")
    return value


def _impact_bps(spend: int, output: int, reserve_in: int, reserve_out: int) -> int:
    return _truncdiv((spend * reserve_out - output * reserve_in) * BPS,
                     spend * reserve_out)


@dataclass(frozen=True)
class BuyQuote:
    requested: int
    spent: int
    refund: int
    tokens_out: int
    fee_base: int
    fee_creator: int
    fee_snipe: int
    core_price_impact_bps: int
    all_in_price_impact_bps: int
    next_state: CurveState

    @property
    def net_into_curve(self) -> int:
        return self.spent - self.fee_base - self.fee_creator - self.fee_snipe

    @property
    def emitted_fee(self) -> int:
        """What a ``CurveBuy`` log reports as ``fee``: base **plus** snipe."""
        return self.fee_base + self.fee_snipe


@dataclass(frozen=True)
class SellQuote:
    tokens_in: int
    gross_quote_out: int
    quote_out: int
    fee_base: int
    fee_creator: int
    core_price_impact_bps: int
    all_in_price_impact_bps: int


def quote_curve_buy(state: CurveState, requested: int) -> BuyQuote:
    """Price a buy of ``requested`` quote units, with partial fill and refund.

    A buy that would take more than the tradable allocation is **clamped**, not
    refused: the fill is priced from the token side, grossed back up so the fee
    legs still come out of the input, and the unspent remainder is refunded —
    the contract's own behaviour, and the reason ``refund`` is a field here
    rather than an error.
    """
    _validate(state)
    requested = _uint(requested)
    if requested == 0:
        raise QuoteError("QUOTE_ZERO_INPUT")
    max_snipe = BPS - state.fee_bps - state.creator_tax_bps - 100
    snipe = min(state.snipe_tax_bps, max_snipe)

    def fees(amount: int) -> tuple[int, int, int]:
        return (_mul(amount, state.fee_bps) // BPS,
                _mul(amount, state.creator_tax_bps) // BPS,
                _mul(amount, snipe) // BPS)

    spent = requested
    base, creator, snipe_fee = fees(spent)
    tokens_out = _amount_out(spent - base - creator - snipe_fee,
                             state.quote_reserve, state.token_reserve)
    if tokens_out > state.sellable_tokens:
        tokens_out = state.sellable_tokens
        # getAmountIn(sellable, quoteReserve, tokenReserve, feeBps = 0)
        net_needed = (_mul(_mul(tokens_out, state.quote_reserve), BPS)
                      // _mul(state.token_reserve - tokens_out, BPS)) + 1
        divisor = BPS - state.fee_bps - state.creator_tax_bps - snipe
        gross = _uint((net_needed * BPS + divisor - 1) // divisor)
        spent = gross if gross < requested else requested
        base, creator, snipe_fee = fees(spent)
    net = spent - base - creator - snipe_fee
    return BuyQuote(
        requested=requested, spent=spent, refund=requested - spent,
        tokens_out=tokens_out, fee_base=base, fee_creator=creator,
        fee_snipe=snipe_fee,
        core_price_impact_bps=_impact_bps(net, tokens_out, state.quote_reserve,
                                          state.token_reserve),
        all_in_price_impact_bps=_impact_bps(spent, tokens_out, state.quote_reserve,
                                            state.token_reserve),
        next_state=replace(
            state,
            quote_reserve=_uint(state.quote_reserve + net),
            real_quote_reserve=_uint(state.real_quote_reserve + net),
            token_reserve=state.token_reserve - tokens_out,
            sellable_tokens=state.sellable_tokens - tokens_out))


def quote_curve_sell(state: CurveState, tokens_in: int) -> SellQuote:
    """Price a sell of ``tokens_in`` tokens back into the curve.

    The fee comes off the quote output here, so it is quote-denominated on
    both legs. ``QUOTE_EXCEEDS_REAL_RESERVE`` is the honest answer when the
    curve's *phantom* reserve would be needed to pay: the ETH is not there.
    """
    _validate(state)
    tokens_in = _uint(tokens_in)
    gross = _amount_out(tokens_in, state.token_reserve, state.quote_reserve)
    if gross > state.real_quote_reserve:
        raise QuoteError("QUOTE_EXCEEDS_REAL_RESERVE")
    base = _mul(gross, state.fee_bps) // BPS
    creator = _mul(gross, state.creator_tax_bps) // BPS
    quote_out = gross - base - creator
    if quote_out == 0:
        raise QuoteError("QUOTE_DUST_OUTPUT")
    return SellQuote(
        tokens_in=tokens_in, gross_quote_out=gross, quote_out=quote_out,
        fee_base=base, fee_creator=creator,
        core_price_impact_bps=_impact_bps(tokens_in, gross, state.token_reserve,
                                          state.quote_reserve),
        all_in_price_impact_bps=_impact_bps(tokens_in, quote_out,
                                            state.token_reserve,
                                            state.quote_reserve))


def quote_curve_round_trip(state: CurveState, amount: int) -> dict:
    """Buy then sell the tokens back at the state the buy itself left behind."""
    buy = quote_curve_buy(state, amount)
    if buy.next_state.sellable_tokens == 0:
        return {"buy": buy, "sell": None, "route": "requires-v4-after-buy",
                "loss_before_gas": None}
    sell = quote_curve_sell(buy.next_state, buy.tokens_out)
    return {"buy": buy, "sell": sell, "route": "curve-then-curve",
            "loss_before_gas": buy.spent - sell.quote_out}


# --------------------------------------------------------------------------
# State reconstructed from events (addendum 8)
# --------------------------------------------------------------------------
#: Events that provably move no reserve. Listed rather than defaulted, so a new
#: event kind is an error instead of a silent no-op.
NEUTRAL_EVENTS = frozenset({
    "FeesSwept", "SnipeTaxCharged", "SnipeTaxExempted", "Initialized",
    "CurveBuyRefunded", "AutoGraduationFailed", "BuybackEnabledUpdated",
    "CreatorFeeRecipientUpdated", "FeesRescued",
})

RESERVE_EVENTS = frozenset({"CurveBuy", "CurveSell", "BuybackLocked",
                            "CurveCompleted"})


class CurveReconstruction:
    """One curve's exact state, advanced event by event from its calibration.

    ``FeesSwept`` moves nothing: the fee buckets leave ``quoteFeeBalance`` and
    ``trackedQuote`` together, so the reserve is unchanged — unless the sweep
    executed an internal buyback, and that is exactly what ``BuybackLocked``
    reports, so the buyback's quote and tokens are applied from *that* event.
    Verified against ``_sweepFees`` in the frozen source.
    """

    def __init__(self, initial: CurveState, *, launch_block: int,
                 launched_at: int, snipe_start_bps: int, snipe_window_seconds: int,
                 token: str = "", curve: str = ""):
        if initial.token_reserve < initial.sellable_tokens:
            raise ReconstructionError("SIM_INITIAL_RESERVES", "reserved < 0")
        if initial.quote_reserve < initial.real_quote_reserve:
            raise ReconstructionError("SIM_INITIAL_RESERVES", "phantom < 0")
        self.initial = initial
        self.state = initial
        self.reserved = initial.reserved_tokens
        self.phantom = initial.phantom_quote
        self.launch_block = int(launch_block)
        self.launched_at = int(launched_at)
        self.snipe_start_bps = int(snipe_start_bps)
        self.snipe_window_seconds = int(snipe_window_seconds)
        self.token = token
        self.curve = curve
        self.applied = 0
        self.completed_at: int | None = None

    # ------------------------------------------------------------- queries
    def state_at(self, timestamp: int) -> CurveState:
        """The current state with the snipe tax a buy would pay at ``timestamp``."""
        return self.state.with_snipe(snipe_tax_bps(
            self.snipe_start_bps, self.snipe_window_seconds,
            max(0, int(timestamp) - self.launched_at)))

    # -------------------------------------------------------------- apply
    def apply(self, event: dict, *, check: bool = True) -> CurveState:
        """Advance by one normalised curve event, checking the arithmetic.

        ``check=False`` skips the constant-product verification and only
        applies the deltas; it exists for nothing in the loop, only for tests
        that deliberately feed a corrupted stream.
        """
        kind = event.get("event")
        args = event.get("args") or {}
        if kind in NEUTRAL_EVENTS:
            self.applied += 1
            return self.state
        if kind not in RESERVE_EVENTS:
            raise ReconstructionError("SIM_UNMAPPED_REPLAY", str(kind))
        s = self.state
        if kind == "CurveCompleted":
            self.state = CurveState(
                quote_reserve=self.phantom, token_reserve=0,
                real_quote_reserve=0, sellable_tokens=0,
                fee_bps=s.fee_bps, creator_tax_bps=s.creator_tax_bps,
                snipe_tax_bps=0, graduated=True)
            self.completed_at = int(event.get("block_number", 0)) or None
            self.applied += 1
            return self.state
        if s.graduated:
            raise ReconstructionError("SIM_TRADE_AFTER_GRADUATION", str(kind))
        if kind == "CurveBuy":
            # The log's ``fee`` is base + snipe (the contract adds them before
            # emitting), so ``quoteIn - fee - tax`` is the net that reaches the
            # reserve regardless of how the snipe tax was split.
            net = int(args["quoteIn"]) - int(args["fee"]) - int(args["tax"])
            tokens = int(args["tokensOut"])
            if check:
                expected = net * s.token_reserve // (s.quote_reserve + net)
                if expected > s.sellable_tokens:
                    expected = s.sellable_tokens
                if expected != tokens:
                    raise ReconstructionError(
                        "SIM_BUY_REPLAY_MISMATCH", f"{expected} != {tokens}")
            quote_reserve = s.quote_reserve + net
            real = s.real_quote_reserve + net
            token_reserve = s.token_reserve - tokens
        elif kind == "CurveSell":
            tokens = int(args["tokensIn"])
            gross = int(args["quoteOut"]) + int(args["fee"]) + int(args["tax"])
            if check:
                expected = tokens * s.quote_reserve // (s.token_reserve + tokens)
                if expected != gross:
                    raise ReconstructionError(
                        "SIM_SELL_REPLAY_MISMATCH", f"{expected} != {gross}")
            quote_reserve = s.quote_reserve - gross
            real = s.real_quote_reserve - gross
            token_reserve = s.token_reserve + tokens
        else:  # BuybackLocked
            quote = int(args["quoteSpent"])
            locked = int(args["tokensLocked"])
            quote_reserve = s.quote_reserve + quote
            real = s.real_quote_reserve + quote
            token_reserve = s.token_reserve - locked
        if real < 0 or token_reserve < 0 or quote_reserve < 0:
            raise ReconstructionError("SIM_NEGATIVE_REPLAY", kind)
        self.state = replace(
            s, quote_reserve=quote_reserve, real_quote_reserve=real,
            token_reserve=token_reserve,
            sellable_tokens=max(token_reserve - self.reserved, 0))
        self.applied += 1
        return self.state
