"""The curve's state at launch, derived rather than read.

docs/SPEC.md D10, reviewer decision 1, which asks dispatch 2 to *check first*
whether the initial curve state is a function of ``(launchConfigId,
graduationThreshold)`` plus the creator tax, and to derive it for every token
if it is, instead of spending an ``eth_call`` per admitted curve.

It is. Measured on **all 546** native-ETH calibrations the donor collected
(``data/pons/d10-replay-v1/initial_states.json``,
``tests/d10/test_seed.py``): for every one of them, the state recorded at the
launch block equals the constants below advanced by that launch block's own
``CurveBuy`` events — the deployer's initial buy, which is an ordinary logged
trade and not a hidden parameter. The two things that vary between launches
are therefore the creator tax and whatever the deployer bought, and the second
is already in the event stream.

The creator tax is recoverable from any trade without a request, because the
contract charges ``tax = quote * creatorTaxBps / 10_000`` in integer
arithmetic: at wei scale the floor admits exactly one ``bps`` for a given
(quote, tax) pair. Checked on the same 546: **489 uniquely and correctly
recovered, 0 wrong, 57 with no trade at all** — and a token with no trade can
never be admitted, because admission requires three.

So this module is an arithmetic fact with a measured provenance, not a guess.
Where the arithmetic does *not* pin the answer — a launch config we have not
pinned, or a recovery that is not unique — the caller falls back to one
``eth_call`` for ``creatorTaxBps``, which is the rule the reviewer decision
gives as the alternative.
"""

from __future__ import annotations

from .curve import BPS, CurveState

#: The pinned launch configuration. Every one of the 546 donor calibrations
#: carries this pair, and a launch that does not is not derived from the seed.
LAUNCH_SEED = {
    "launch_config_id": 0,
    "graduation_threshold": 4_200_000_000_000_000_000,
    "quote_reserve": 1_680_000_000_000_000_000,
    "token_reserve": 1_000_000_000_000_000_000_000_000_000,
    "real_quote_reserve": 0,
    "sellable_tokens": 714_285_714_285_714_285_714_285_715,
    "fee_bps": 100,
    "snipe_start_bps": 9_900,
    "snipe_window_seconds": 3,
    "measured_on": "546 of 546 native-ETH calibrations in data/pons/d10-replay-v1",
}


def seed_state(creator_tax_bps: int) -> CurveState:
    """The pre-trade state of a freshly launched pinned-config curve."""
    return CurveState(
        quote_reserve=int(LAUNCH_SEED["quote_reserve"]),
        token_reserve=int(LAUNCH_SEED["token_reserve"]),
        real_quote_reserve=int(LAUNCH_SEED["real_quote_reserve"]),
        sellable_tokens=int(LAUNCH_SEED["sellable_tokens"]),
        fee_bps=int(LAUNCH_SEED["fee_bps"]),
        creator_tax_bps=int(creator_tax_bps),
        snipe_tax_bps=0, graduated=False)


def matches_pinned_config(launch_config_id, graduation_threshold) -> bool:
    return (str(launch_config_id) == str(LAUNCH_SEED["launch_config_id"])
            and str(graduation_threshold)
            == str(LAUNCH_SEED["graduation_threshold"]))


def quote_leg(event: dict) -> int | None:
    """The quote amount the creator tax was charged on, for one trade event."""
    args = event.get("args") or {}
    if event.get("event") == "CurveBuy":
        return int(args["quoteIn"])
    if event.get("event") == "CurveSell":
        return int(args["quoteOut"]) + int(args["fee"]) + int(args["tax"])
    return None


def creator_tax_from_trade(event: dict) -> int | None:
    """The unique ``creatorTaxBps`` consistent with this trade, or ``None``.

    ``None`` means *not pinned* — either the event is not a trade, or more than
    one bps value floors to the same tax — and the caller must read the getter
    instead. It never guesses.
    """
    base = quote_leg(event)
    if base is None or base <= 0:
        return None
    tax = int((event.get("args") or {}).get("tax", 0))
    if tax < 0 or tax > base:
        return None
    # bps must satisfy base * bps // BPS == tax, i.e. bps in
    # [ceil(tax*BPS/base), floor(((tax+1)*BPS - 1)/base)].
    low = -(-tax * BPS // base)
    high = ((tax + 1) * BPS - 1) // base
    high = min(high, BPS)
    if low != high or low < 0 or low > BPS:
        return None
    return int(low)


__all__ = ["LAUNCH_SEED", "seed_state", "matches_pinned_config",
           "creator_tax_from_trade", "quote_leg"]
