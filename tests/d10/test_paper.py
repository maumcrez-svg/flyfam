"""Paper fills on the curve: the latency rule, the costs, the unavailable exits.

Tapes and clocks are scripted (``tests.d10.fixtures``). The quote, the fee, tax
and impact arithmetic, and the account's three-way reconciliation are real.
"""

from __future__ import annotations

import pytest

from flytrade import execution as X
from flytrade.pons import paper as PAPER
from flytrade.pons.context import PAPER_SIZE_WEI
from tests.d10 import fixtures as F


def execution(**kw) -> PAPER.PonsPaperExecution:
    return PAPER.PonsPaperExecution(**kw)


# --------------------------------------------------------------- latency rule
def test_a_fill_lands_at_the_first_block_at_or_after_cutoff_plus_latency():
    x = execution()
    tape = F.traded_tape()
    clock = F.clock()
    cutoff = tape.launched_at + 200
    plan = x.plan_buy(tape, cutoff, clock)
    assert plan.block_timestamp >= cutoff + x.latency_s
    assert plan.block_timestamp - cutoff == x.latency_s
    assert plan.block_number == F.block_at(202)


def test_a_fill_never_uses_a_state_the_decision_could_not_have_reached():
    """A trade between the cutoff and the fill **is** in the fill's state."""
    x = execution()
    tape = F.traded_tape()
    clock = F.clock()
    cutoff = tape.launched_at + 200
    before = x.plan_buy(tape, cutoff, clock).quote.tokens_out
    tape.apply(F.buy_event(tape.curve, at_seconds=201, quote_in=5 * 10 ** 17,
                           state=tape.state, log_index=50))
    after = x.plan_buy(tape, cutoff, clock).quote.tokens_out
    assert after < before          # the intervening buy raised the price
    # and a trade *after* the fill block does not
    tape.apply(F.buy_event(tape.curve, at_seconds=900, quote_in=5 * 10 ** 17,
                           state=tape.state, log_index=51))
    assert x.plan_buy(tape, cutoff, clock).quote.tokens_out == after


# ------------------------------------------------------------------- the costs
def test_the_costs_are_the_curves_own_and_not_a_flat_twenty_bps():
    x = execution()
    tape = F.traded_tape()
    plan = x.plan_buy(tape, tape.launched_at + 200, F.clock())
    quote = plan.quote
    assert quote.fee_base == PAPER_SIZE_WEI * tape.initial.fee_bps // 10_000
    assert quote.fee_creator == (PAPER_SIZE_WEI
                                 * tape.initial.creator_tax_bps // 10_000)
    assert quote.fee_snipe == 0          # 200 s after launch, the window closed
    assert x.fee_bps == 0.0 and x.slippage_bps == 0.0


def test_the_snipe_tax_is_charged_when_the_fill_is_inside_its_window():
    x = execution(latency_s=2)
    tape = F.traded_tape(trades=((0, 10 ** 16), (1, 10 ** 16), (2, 10 ** 16)))
    # a fill two seconds after the launch really does pay the decaying tax
    plan = x.plan_buy(tape, tape.launched_at, F.clock())
    assert plan.quote.fee_snipe > 0


def test_gas_is_charged_on_both_legs_and_the_approval_once():
    x = execution()
    tape = F.traded_tape()
    clock = F.clock()
    buy = x.plan_buy(tape, tape.launched_at + 200, clock)
    assert buy.gas_wei == x.gas_buy_wei
    sell = x.plan_sell(tape, tape.launched_at + 1_100, buy.quantity, clock,
                       tokens_wei=buy.quote.tokens_out)
    assert sell.gas_wei == x.gas_sell_wei + x.gas_approval_wei


def test_the_accounting_identity_holds_on_a_real_round_trip():
    x = execution()
    tape = F.traded_tape()
    clock = F.clock()
    cutoff = tape.launched_at + 200
    position = x.open_long(episode_id=1, tape=tape, stable_id=0, cutoff=cutoff,
                           clock=clock)
    assert isinstance(position, X.Position)
    outcome = x.close(tape=tape, reason=X.CloseReason.POLICY_CLOSE_FIXED_HOLD,
                      cutoff=cutoff + 900, clock=clock)
    assert isinstance(outcome, X.OutcomeRecord)
    assert outcome.net_pnl == pytest.approx(outcome.gross_pnl - outcome.fees,
                                            abs=1e-15)
    assert outcome.net_pnl == pytest.approx(
        outcome.gross_reference_pnl - outcome.slippage - outcome.fees, abs=1e-12)
    x.account.check()          # cash == initial + realised, when flat
    stats = x.stats()
    assert abs(stats["reconciliation"]["residual"]) < 1e-9


def test_a_quiet_round_trip_loses_exactly_the_costs():
    """No external flow between entry and exit: the curve is reversible.

    The position gets back exactly what it put in, so the whole of the net is
    the fees, the taxes and the gas. That is the arithmetic saying the own-delta
    carry is right, not a claim about memecoins.
    """
    x = execution()
    tape = F.traded_tape()
    clock = F.clock()
    cutoff = tape.launched_at + 200
    x.open_long(episode_id=1, tape=tape, stable_id=0, cutoff=cutoff, clock=clock)
    outcome = x.close(tape=tape, reason=X.CloseReason.POLICY_CLOSE_FIXED_HOLD,
                      cutoff=cutoff + 900, clock=clock)
    assert outcome.gross_pnl == pytest.approx(0.0, abs=1e-12)
    assert outcome.net_pnl == pytest.approx(-outcome.fees, abs=1e-12)


def test_the_positions_own_impact_is_carried_into_its_exit():
    x = execution()
    tape = F.traded_tape()
    clock = F.clock()
    cutoff = tape.launched_at + 200
    x.open_long(episode_id=1, tape=tape, stable_id=0, cutoff=cutoff, clock=clock)
    assert x.own_delta[tape.curve]["tokens"] == x.entry_tokens_wei
    carried = x.carry(tape, tape.state_at(cutoff + 900))
    plain = tape.state_at(cutoff + 900)
    assert carried.token_reserve < plain.token_reserve
    assert carried.quote_reserve > plain.quote_reserve


def test_the_paper_position_does_not_change_the_recorded_market():
    x = execution()
    tape = F.traded_tape()
    clock = F.clock()
    before = [p.token_reserve for p in tape.points]
    x.open_long(episode_id=1, tape=tape, stable_id=0,
                cutoff=tape.launched_at + 200, clock=clock)
    assert [p.token_reserve for p in tape.points] == before
    assert x.as_dict()["changes_the_public_market"] is False


# ------------------------------------------------------------ unavailable exits
def test_a_curve_that_completes_before_the_horizon_is_ROUTE_TRANSITION():
    x = execution()
    tape = F.traded_tape()
    clock = F.clock()
    cutoff = tape.launched_at + 200
    x.open_long(episode_id=1, tape=tape, stable_id=0, cutoff=cutoff, clock=clock)
    tape.apply(F.completed_event(tape.curve, at_seconds=400))
    with pytest.raises(PAPER.Unresolved) as caught:
        x.plan_sell(tape, cutoff + 900, 1.0, clock,
                    tokens_wei=x.entry_tokens_wei)
    assert caught.value.reason == PAPER.ROUTE_TRANSITION
    assert x.account.position is not None        # the exposure is retained


def test_a_horizon_past_the_data_is_COVERAGE_and_not_a_loss():
    x = execution()
    tape = F.traded_tape(coverage_seconds=300)
    clock = F.clock()
    with pytest.raises(PAPER.Unresolved) as caught:
        x.plan_sell(tape, tape.launched_at + 2_000, 1.0, clock, tokens_wei=10 ** 20)
    assert caught.value.reason == PAPER.COVERAGE


def test_an_unresolved_record_is_not_a_loss_and_says_so():
    x = execution()
    entry = x.record_unresolved(episode_id=7, token="0xabc",
                                reason=PAPER.ROUTE_TRANSITION, cutoff=1)
    assert entry["is_a_loss"] is False and entry["settled"] is False
    assert x.outcomes == []                 # nothing was booked


def test_an_rpc_failure_is_not_a_minus_one_hundred_per_cent_trade():
    """There is no path from a transport error to a booked loss.

    The settlement asks for a quote; a failure raises ``Unresolved`` and the
    account is untouched. Nothing in this module can write a PnL without a
    successful quote on both legs.
    """
    x = execution()
    tape = F.traded_tape()
    clock = F.clock()
    x.open_long(episode_id=1, tape=tape, stable_id=0,
                cutoff=tape.launched_at + 200, clock=clock)
    cash = x.account.cash

    class Broken:
        def block_at_or_after(self, ts):
            raise OSError("scripted transport failure")

    with pytest.raises(OSError):
        x.plan_sell(tape, tape.launched_at + 1_100, 1.0, Broken(),
                    tokens_wei=x.entry_tokens_wei)
    assert x.account.cash == cash
    assert x.outcomes == []
    assert x.account.position is not None


def test_an_entry_that_would_exhaust_the_curve_is_refused_not_resized():
    x = execution(size_wei=10 ** 22)
    tape = F.traded_tape()
    refused = x.open_long(episode_id=1, tape=tape, stable_id=0,
                          cutoff=tape.launched_at + 200, clock=F.clock())
    assert isinstance(refused, X.Rejection)
    assert refused.reason is X.RejectReason.CURVE_EXHAUSTED
    assert x.account.position is None


def test_a_second_entry_while_holding_is_refused():
    x = execution()
    tape = F.traded_tape()
    clock = F.clock()
    x.open_long(episode_id=1, tape=tape, stable_id=0,
                cutoff=tape.launched_at + 200, clock=clock)
    again = x.open_long(episode_id=2, tape=tape, stable_id=0,
                        cutoff=tape.launched_at + 230, clock=clock)
    assert isinstance(again, X.Rejection)
    assert again.reason is X.RejectReason.POSITION_OPEN


# ------------------------------------------------------------------- the mark
def test_the_mark_is_a_mark_and_never_a_reward():
    x = execution()
    tape = F.traded_tape()
    clock = F.clock()
    x.open_long(episode_id=1, tape=tape, stable_id=0,
                cutoff=tape.launched_at + 200, clock=clock)
    mark = x.mark(tape, tape.launched_at + 500, clock)
    assert mark["available"] is True
    assert mark["is_a_reward"] is False
    assert "unrealised_eth" in mark
    assert x.outcomes == [] and x.account.realized_pnl == 0.0


def test_reinforcement_uses_the_settled_outcome_and_the_existing_rule():
    x = execution()
    tape = F.traded_tape()
    clock = F.clock()
    cutoff = tape.launched_at + 200
    x.open_long(episode_id=1, tape=tape, stable_id=0, cutoff=cutoff, clock=clock)
    outcome = x.close(tape=tape, reason=X.CloseReason.POLICY_CLOSE_FIXED_HOLD,
                      cutoff=cutoff + 900, clock=clock)
    valence, amount = x.reinforcement(outcome)
    assert valence == (1 if outcome.net_pnl > 0 else -1)
    expected = min(abs(outcome.return_on_notional) / x.reinforce_full_scale,
                   x.reinforce_cap)
    assert amount == pytest.approx(expected)
    assert x.reinforce_full_scale == X.REINFORCE_FULL_SCALE
    assert x.reinforce_cap == X.REINFORCE_CAP
