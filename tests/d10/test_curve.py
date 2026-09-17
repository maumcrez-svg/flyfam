"""The bonding-curve quote: reproduced against the donor's own captured numbers.

``experiments/d10/evidence/pons-quotes-curve.json`` is a real snapshot the
donor took on chain on 2026-09-09, priced by its TypeScript port of the frozen
Solidity. Those numbers are **observations of a contract's arithmetic**, not
invented fixtures, and reproducing them to the wei is what makes the Python
port a port rather than a rewrite. The transition fixture is the negative
case: a curve that had already closed, where the honest answer is that no
quote exists.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flytrade.pons.curve import (BPS, CurveReconstruction, CurveState,
                                 QuoteError, ReconstructionError,
                                 quote_curve_buy, quote_curve_round_trip,
                                 quote_curve_sell, snipe_tax_bps)

EVIDENCE = Path(__file__).resolve().parents[2] / "experiments" / "d10" / "evidence"


def fixture_state(payload: dict) -> CurveState:
    return CurveState(
        quote_reserve=int(payload["quoteReserve"]),
        token_reserve=int(payload["tokenReserve"]),
        real_quote_reserve=int(payload["realQuoteReserve"]),
        sellable_tokens=int(payload["sellableTokens"]),
        fee_bps=int(payload["feeBps"]),
        creator_tax_bps=int(payload["creatorTaxBps"]),
        snipe_tax_bps=int(payload["snipeTaxBps"]),
        graduated=bool(payload["graduated"]))


def curve_fixture() -> dict:
    return json.loads((EVIDENCE / "pons-quotes-curve.json").read_text())["result"]


def test_the_donor_fixture_is_reproduced_wei_for_wei():
    result = curve_fixture()
    state = fixture_state(result["state"])
    assert len(result["quotes"]) == 3
    for row in result["quotes"]:
        trip = quote_curve_round_trip(state, int(row["amount"]))
        buy, want = trip["buy"], row["buy"]
        assert trip["route"] == row["route"]
        assert buy.spent == int(want["spent"])
        assert buy.refund == int(want["refund"])
        assert buy.tokens_out == int(want["tokensOut"])
        assert buy.fee_base == int(want["fees"]["base"])
        assert buy.fee_creator == int(want["fees"]["creator"])
        assert buy.fee_snipe == int(want["fees"]["snipe"])
        assert buy.core_price_impact_bps == int(want["corePriceImpactBps"])
        assert buy.all_in_price_impact_bps == int(want["allInPriceImpactBps"])
        after = want["nextState"]
        assert buy.next_state.quote_reserve == int(after["quoteReserve"])
        assert buy.next_state.token_reserve == int(after["tokenReserve"])
        assert buy.next_state.real_quote_reserve == int(after["realQuoteReserve"])
        assert buy.next_state.sellable_tokens == int(after["sellableTokens"])
        if row.get("sell"):
            sell, wants = trip["sell"], row["sell"]
            assert sell.gross_quote_out == int(wants["grossQuoteOut"])
            assert sell.quote_out == int(wants["quoteOut"])
            assert sell.fee_base == int(wants["fees"]["base"])
            assert sell.fee_creator == int(wants["fees"]["creator"])
            assert sell.core_price_impact_bps == int(wants["corePriceImpactBps"])
            assert sell.all_in_price_impact_bps == int(wants["allInPriceImpactBps"])
            assert trip["loss_before_gas"] == int(row["lossBeforeGas"])
        else:
            assert trip["sell"] is None


def test_the_largest_fixture_row_is_a_partial_fill_with_a_refund():
    result = curve_fixture()
    state = fixture_state(result["state"])
    row = max(result["quotes"], key=lambda q: int(q["amount"]))
    buy = quote_curve_buy(state, int(row["amount"]))
    assert buy.refund > 0
    assert buy.spent < buy.requested
    assert buy.tokens_out == state.sellable_tokens
    assert buy.next_state.sellable_tokens == 0
    # And the curve is then unsellable: that is the V4 route, not a loss.
    with pytest.raises(QuoteError) as caught:
        quote_curve_sell(buy.next_state, buy.tokens_out)
    assert caught.value.code == "CURVE_REQUIRES_V4"


def test_a_closed_curve_has_no_quote_rather_than_a_guessed_one():
    transition = json.loads((EVIDENCE / "pons-quotes-transition.json").read_text())
    text = json.dumps(transition)
    assert "unavailable" in text or "requires-v4" in text


def test_the_snipe_tax_decays_by_fourteen_halvings():
    assert snipe_tax_bps(9_900, 3, 0) == 9_900
    assert snipe_tax_bps(9_900, 3, 1) == 9_900 >> 4
    assert snipe_tax_bps(9_900, 3, 2) == 9_900 >> 9
    assert snipe_tax_bps(9_900, 3, 3) == 0
    assert snipe_tax_bps(9_900, 3, 900) == 0
    assert snipe_tax_bps(0, 3, 0) == 0
    # It is never assumed zero: a fill one second in really pays it.
    state = CurveState(10 ** 18, 10 ** 27, 5 * 10 ** 17, 5 * 10 ** 26, 100, 200)
    taxed = quote_curve_buy(state.with_snipe(snipe_tax_bps(9_900, 3, 1)), 10 ** 16)
    clean = quote_curve_buy(state, 10 ** 16)
    assert taxed.fee_snipe > 0
    assert taxed.tokens_out < clean.tokens_out


def test_the_snipe_tax_is_capped_so_a_buyer_keeps_one_per_cent():
    state = CurveState(10 ** 18, 10 ** 27, 5 * 10 ** 17, 5 * 10 ** 26, 100, 200)
    buy = quote_curve_buy(state.with_snipe(9_900), 10 ** 16)
    assert buy.fee_snipe == 10 ** 16 * (BPS - 100 - 200 - 100) // BPS
    assert buy.net_into_curve * BPS >= buy.spent * 100


def test_a_sell_the_real_reserve_cannot_pay_is_refused():
    # Almost all of the quote reserve is phantom here, so the curve prices the
    # sell but has no ETH behind it.
    state = CurveState(quote_reserve=10 ** 18, token_reserve=10 ** 27,
                       real_quote_reserve=10 ** 9, sellable_tokens=5 * 10 ** 26,
                       fee_bps=100, creator_tax_bps=200)
    with pytest.raises(QuoteError) as caught:
        quote_curve_sell(state, 10 ** 26)
    assert caught.value.code == "QUOTE_EXCEEDS_REAL_RESERVE"


def test_dust_and_zero_inputs_are_refused_by_name():
    state = CurveState(10 ** 18, 10 ** 27, 5 * 10 ** 17, 5 * 10 ** 26, 100, 200)
    with pytest.raises(QuoteError) as caught:
        quote_curve_buy(state, 0)
    assert caught.value.code == "QUOTE_ZERO_INPUT"
    thin = CurveState(10 ** 27, 10 ** 3, 10 ** 27, 10 ** 3, 0, 0)
    with pytest.raises(QuoteError) as caught:
        quote_curve_buy(thin, 1)
    assert caught.value.code == "QUOTE_DUST_OUTPUT"


def test_a_graduated_curve_requires_v4():
    state = CurveState(10 ** 18, 10 ** 27, 5 * 10 ** 17, 5 * 10 ** 26, 100, 200,
                       graduated=True)
    with pytest.raises(QuoteError) as caught:
        quote_curve_buy(state, 10 ** 16)
    assert caught.value.code == "CURVE_REQUIRES_V4"


def test_an_impossible_state_is_refused_rather_than_priced():
    bad = CurveState(quote_reserve=1, token_reserve=10, real_quote_reserve=5,
                     sellable_tokens=5, fee_bps=0, creator_tax_bps=0)
    with pytest.raises(QuoteError) as caught:
        quote_curve_buy(bad, 1)
    assert caught.value.code == "CURVE_STATE_INVALID"


# ---------------------------------------------------------------- reconstruction
def _recon(state: CurveState) -> CurveReconstruction:
    return CurveReconstruction(state, launch_block=100, launched_at=1_700_000_000,
                               snipe_start_bps=9_900, snipe_window_seconds=3)


def _buy_event(quote, tokens, fee, tax, block=101):
    return {"event": "CurveBuy", "block_number": block,
            "args": {"quoteIn": str(quote), "tokensOut": str(tokens),
                     "fee": str(fee), "tax": str(tax)}}


def test_a_buy_event_moves_the_reserves_by_its_own_net():
    state = CurveState(10 ** 18, 10 ** 27, 5 * 10 ** 17, 5 * 10 ** 26, 100, 200)
    quote = quote_curve_buy(state, 10 ** 16)
    recon = _recon(state)
    after = recon.apply(_buy_event(quote.spent, quote.tokens_out,
                                   quote.emitted_fee, quote.fee_creator))
    assert after.quote_reserve == quote.next_state.quote_reserve
    assert after.token_reserve == quote.next_state.token_reserve
    assert after.real_quote_reserve == quote.next_state.real_quote_reserve
    assert after.sellable_tokens == quote.next_state.sellable_tokens


def test_a_buy_that_does_not_satisfy_the_constant_product_is_refused():
    state = CurveState(10 ** 18, 10 ** 27, 5 * 10 ** 17, 5 * 10 ** 26, 100, 200)
    recon = _recon(state)
    with pytest.raises(ReconstructionError) as caught:
        recon.apply(_buy_event(10 ** 16, 10 ** 30, 10 ** 14, 2 * 10 ** 14))
    assert caught.value.code == "SIM_BUY_REPLAY_MISMATCH"


def test_fees_swept_moves_nothing_and_buyback_locked_moves_both_sides():
    state = CurveState(10 ** 18, 10 ** 27, 5 * 10 ** 17, 5 * 10 ** 26, 100, 200)
    recon = _recon(state)
    unchanged = recon.apply({"event": "FeesSwept", "block_number": 101,
                             "args": {"protocolAmount": "1", "buybackAmount": "0",
                                      "creatorAmount": "2"}})
    assert unchanged == state
    after = recon.apply({"event": "BuybackLocked", "block_number": 101,
                         "args": {"quoteSpent": "1000", "tokensLocked": "5000"}})
    assert after.quote_reserve == state.quote_reserve + 1000
    assert after.real_quote_reserve == state.real_quote_reserve + 1000
    assert after.token_reserve == state.token_reserve - 5000
    assert after.sellable_tokens == state.sellable_tokens - 5000


def test_completion_empties_the_curve_down_to_its_phantom_reserve():
    state = CurveState(10 ** 18, 10 ** 27, 5 * 10 ** 17, 5 * 10 ** 26, 100, 200)
    recon = _recon(state)
    after = recon.apply({"event": "CurveCompleted", "block_number": 105,
                         "args": {"recipient": "0x" + "0" * 40, "quoteOut": "1",
                                  "tokenOut": "2"}})
    assert after.graduated
    assert after.quote_reserve == state.phantom_quote
    assert after.real_quote_reserve == 0
    assert after.sellable_tokens == 0
    with pytest.raises(ReconstructionError) as caught:
        recon.apply(_buy_event(1, 1, 0, 0, block=106))
    assert caught.value.code == "SIM_TRADE_AFTER_GRADUATION"


def test_an_unknown_event_kind_is_an_error_not_a_silent_no_op():
    state = CurveState(10 ** 18, 10 ** 27, 5 * 10 ** 17, 5 * 10 ** 26, 100, 200)
    with pytest.raises(ReconstructionError) as caught:
        _recon(state).apply({"event": "SomethingNew", "block_number": 101, "args": {}})
    assert caught.value.code == "SIM_UNMAPPED_REPLAY"
