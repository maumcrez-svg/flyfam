"""
Execution and outcome integrity in historical time.

Amendment D6 §5 and Fable addendum 4. Every number in the v1 paper policy is
preserved; what is tested here is that "delay 1" and "horizon 8" mean *market
minutes on the session grid* and not *rows in a file*, that no order can see a
price that did not exist when the decision was taken, and that a fill which
cannot happen is recorded rather than invented.
"""
from __future__ import annotations

from datetime import date

import pytest

from flytrade import execution as X
from flytrade import historical as H
from tests.historical import make_fixtures as MF

D0, D1, D2 = MF.DAYS


@pytest.fixture
def policy(universe):
    p = H.HistoricalExecution(universe)
    p.start_session(D0)
    return p


def _fresh(universe, day):
    p = H.HistoricalExecution(universe)
    p.start_session(day)
    return p


# ------------------------------------------------------------- the delay

def test_the_fill_is_the_open_of_the_next_minute_never_the_decision_bar(
        policy, series_a):
    pos = policy.open_long(episode_id=1, symbol="A", stable_id=0,
                           decision_bar=50)
    assert isinstance(pos, X.Position)
    assert pos.entry.bar_index == 51                 # bar_end(50) = minute 51
    assert pos.entry.delay_minutes == 1
    assert pos.entry.flag == ""
    bar51 = series_a.bar(D0, 51)
    assert pos.entry.reference_price == pytest.approx(bar51.open)
    # nothing about bar 50 other than "it ended" entered the fill
    bar50 = series_a.bar(D0, 50)
    for p in (bar50.high, bar50.low, bar50.close):
        assert pos.entry.reference_price != p or bar51.open == p
    # and the decision instant is bar_end(50), which is bar_start(51)
    assert pos.entry.ts == int(series_a.sessions[D0].bar_start[51])


def test_a_missing_next_minute_delays_the_fill_and_says_so(universe):
    p = _fresh(universe, D1)
    pos = p.open_long(episode_id=2, symbol="A", stable_id=0, decision_bar=99)
    assert pos.entry.bar_index == 104                # 100..103 are absent
    assert pos.entry.delay_minutes == 5
    assert pos.entry.flag == H.DELAYED_FILL
    assert p.delayed_fills == 1
    # the horizon is measured from the fill, not from the decision
    assert pos.horizon_bar == 104 + 8


def test_the_horizon_is_eight_market_minutes_from_the_fill(policy, series_a):
    pos = policy.open_long(episode_id=3, symbol="A", stable_id=0,
                           decision_bar=50)
    assert pos.horizon_bar == 59 == pos.entry.bar_index + 8
    assert not policy.due_for_horizon(58)
    assert policy.due_for_horizon(59)
    out = policy.close(decision_bar=59, reason=X.CloseReason.POLICY_CLOSE)
    assert out.exit.bar_index == 59
    assert out.exit.flag == ""
    assert out.market_minutes_held == 8
    assert out.exit.ts - out.entry.ts == 8 * 60
    assert out.close_reason is X.CloseReason.POLICY_CLOSE


def test_a_missing_settlement_minute_delays_the_settlement_and_says_so(
        universe):
    p = _fresh(universe, D1)
    pos = p.open_long(episode_id=4, symbol="A", stable_id=0, decision_bar=94)
    assert pos.entry.bar_index == 95 and pos.horizon_bar == 103
    out = p.close(decision_bar=103, reason=X.CloseReason.POLICY_CLOSE)
    assert out.exit.bar_index == 104                 # 103 is absent
    assert out.exit.flag == H.DELAYED_FILL
    assert out.exit.delay_minutes == 1
    assert out.market_minutes_held == 9               # nine market minutes


# --------------------------------------------------- entry eligibility

def test_entry_eligibility_is_a_clock_rule_evaluated_before_any_price(
        universe):
    p = _fresh(universe, D0)
    # bar_end + 1 + H <= 16:00  ->  m <= 380 with H = 8
    assert p.eligible_to_enter(380)
    assert not p.eligible_to_enter(381)
    assert not p.eligible_to_enter(H.SESSION_MINUTES - 1)
    r = p.open_long(episode_id=5, symbol="A", stable_id=0, decision_bar=381)
    assert isinstance(r, X.Rejection)
    assert r.reason is X.RejectReason.SESSION_HORIZON
    # the clock rule and "the data ran out" are different refusals
    r2 = p.open_long(episode_id=6, symbol="A", stable_id=0, decision_bar=380)
    assert r2.reason is X.RejectReason.NO_FUTURE_BAR
    assert {x.reason for x in p.rejections} == {
        X.RejectReason.SESSION_HORIZON, X.RejectReason.NO_FUTURE_BAR}


def test_nothing_crosses_a_session_or_a_partition(universe):
    p = _fresh(universe, D0)
    pos = p.open_long(episode_id=7, symbol="A", stable_id=0, decision_bar=114)
    assert pos.horizon_bar == 123                     # past the last bar, 119
    out = p.close(decision_bar=119, reason=X.CloseReason.POLICY_CLOSE,
                  session_close=True)
    assert out.exit.bar_index == 119
    assert out.exit.flag == H.SESSION_CLOSE_FILL
    assert out.close_reason is X.CloseReason.POLICY_CLOSE
    assert p.session_close_fills == 1
    assert p.account.position is None
    # a new session may then begin; it would raise if anything were still open
    p.start_session(D1)
    assert p.day == D1


def test_a_session_may_not_begin_with_a_position_still_open(universe):
    p = _fresh(universe, D0)
    p.open_long(episode_id=8, symbol="A", stable_id=0, decision_bar=50)
    with pytest.raises(AssertionError, match="cross a session"):
        p.start_session(D1)


def test_the_session_close_fill_uses_the_close_of_the_last_available_bar(
        universe, series_a):
    p = _fresh(universe, D0)
    p.open_long(episode_id=9, symbol="A", stable_id=0, decision_bar=114)
    out = p.close(decision_bar=119, reason=X.CloseReason.POLICY_CLOSE,
                  session_close=True)
    assert out.exit.reference_price == pytest.approx(
        series_a.bar(D0, 119).close)
    # every other fill in this module is an OPEN; this one is the exception
    assert out.entry.reference_price == pytest.approx(
        series_a.bar(D0, 115).open)


# ---------------------------------------------------------- no hindsight

def test_no_order_uses_a_price_that_did_not_exist_at_the_decision(universe,
                                                                  series_a):
    p = _fresh(universe, D0)
    pos = p.open_long(episode_id=10, symbol="A", stable_id=0, decision_bar=40)
    out = p.close(decision_bar=49, reason=X.CloseReason.POLICY_CLOSE)
    # both fills are strictly after the bar the decision read
    assert pos.entry.bar_index > 40
    assert out.exit.bar_index > pos.entry.bar_index
    # and each reference price is the OPEN of its own bar, so no high, low or
    # close of any bar is ever used as an execution price
    for fill, m in ((out.entry, out.entry.bar_index),
                    (out.exit, out.exit.bar_index)):
        assert fill.reference_price == pytest.approx(series_a.bar(D0, m).open)


def test_a_fill_without_a_valid_price_is_recorded_not_invented(universe):
    p = _fresh(universe, D2)
    # the session has no bars at all after minute 119
    r = p.open_long(episode_id=11, symbol="A", stable_id=0, decision_bar=200)
    assert isinstance(r, X.Rejection)
    assert r.reason is X.RejectReason.NO_FUTURE_BAR
    assert p.account.position is None
    assert len(p.outcomes) == 0                       # nothing was fabricated


# -------------------------------------------------- costs and accounting

def test_fee_and_slippage_are_charged_per_execution_and_never_twice(
        universe, series_a):
    p = _fresh(universe, D0)
    pos = p.open_long(episode_id=12, symbol="A", stable_id=0, decision_bar=30)
    ref_in = series_a.bar(D0, 31).open
    assert pos.entry.fill_price == pytest.approx(
        ref_in * (1 + X.SLIPPAGE_BPS * X.BPS))
    assert pos.entry.fee == pytest.approx(
        pos.entry.quantity * pos.entry.fill_price * X.FEE_BPS * X.BPS)
    out = p.close(decision_bar=39, reason=X.CloseReason.POLICY_CLOSE)
    ref_out = series_a.bar(D0, 39).open
    assert out.exit.fill_price == pytest.approx(
        ref_out * (1 - X.SLIPPAGE_BPS * X.BPS))
    # exactly two fees and exactly two slippage charges, one per execution
    assert out.fees == pytest.approx(out.entry.fee + out.exit.fee)
    assert out.slippage == pytest.approx(
        out.entry.slippage + out.exit.slippage)
    assert out.entry.slippage == pytest.approx(
        out.entry.quantity * ref_in * X.SLIPPAGE_BPS * X.BPS)
    # and the declared cost basis says so in one place
    assert "per execution" in H.HistoricalExecution.COST_BASIS
    assert "per execution" in p.as_dict()["cost_basis"]


def test_gross_minus_fees_minus_slippage_equals_net(universe):
    p = _fresh(universe, D0)
    for i, m in enumerate((20, 40, 60, 80)):
        p.open_long(episode_id=100 + i, symbol="A", stable_id=0,
                    decision_bar=m)
        out = p.close(decision_bar=m + 9, reason=X.CloseReason.POLICY_CLOSE)
        assert isinstance(out, X.OutcomeRecord)
        assert out.gross_reference_pnl - out.slippage - out.fees == \
            pytest.approx(out.net_pnl, abs=1e-9)
        # and the Phase One identity still holds at the fill prices
        assert out.net_pnl == pytest.approx(out.gross_pnl - out.fees, abs=1e-9)
    rec = p.stats()["reconciliation"]
    assert rec["residual"] == pytest.approx(0.0, abs=1e-6)
    assert rec["booked_net_pnl"] == pytest.approx(p.account.realized_pnl)
    p.account.check()


def test_the_four_policy_outcomes_stay_four_different_things(universe):
    p = _fresh(universe, D0)
    # SELL with nothing open is a rejection, never an unimplemented short
    r1 = p.close(decision_bar=10, reason=X.CloseReason.NEURAL_SELL)
    assert isinstance(r1, X.Rejection) and \
        r1.reason is X.RejectReason.NO_POSITION
    p.open_long(episode_id=13, symbol="A", stable_id=0, decision_bar=20)
    # a BUY while holding is a different rejection
    r2 = p.open_long(episode_id=14, symbol="B", stable_id=1, decision_bar=21)
    assert r2.reason is X.RejectReason.POSITION_OPEN
    # an inventory-reducing SELL is a NEURAL_SELL, not a timer
    out = p.close(decision_bar=25, reason=X.CloseReason.NEURAL_SELL)
    assert out.close_reason is X.CloseReason.NEURAL_SELL
    assert out.exit.bar_index == 26                   # delay 1 from bar_end
    st = p.stats()
    assert st["close_reasons"] == {"NEURAL_SELL": 1}
    assert st["rejections"] == {"NO_POSITION": 1, "POSITION_OPEN": 1}


def test_an_entry_may_not_fill_before_the_previous_exit_filled(universe):
    """The sequencing guard declared in PROTOCOL §6."""
    p = _fresh(universe, D1)
    p.open_long(episode_id=15, symbol="A", stable_id=0, decision_bar=94)
    out = p.close(decision_bar=103, reason=X.CloseReason.POLICY_CLOSE)
    assert out.exit.bar_index == 104
    # a decision taken at minute 99 would otherwise fill at 104 as well
    pos = p.open_long(episode_id=16, symbol="A", stable_id=0, decision_bar=99)
    assert pos.entry.bar_index == 105 > out.exit.bar_index
    assert pos.entry.flag == H.DELAYED_FILL


def test_the_reinforcement_rule_is_the_existing_net_outcome_rule(universe):
    p = _fresh(universe, D0)
    p.open_long(episode_id=17, symbol="A", stable_id=0, decision_bar=20)
    out = p.close(decision_bar=29, reason=X.CloseReason.POLICY_CLOSE)
    valence, amount = p.reinforcement(out)
    r = out.net_pnl / out.notional
    assert valence == (1 if r > 0 else -1 if r < 0 else 0)
    if valence:
        assert amount == pytest.approx(
            min(abs(r) / X.REINFORCE_FULL_SCALE, X.REINFORCE_CAP))


def test_the_v1_numbers_are_preserved_exactly(universe):
    p = _fresh(universe, D0)
    d = p.as_dict()
    assert d["notional"] == X.NOTIONAL == 1000.0
    assert d["fee_bps"] == X.FEE_BPS == 5.0
    assert d["slippage_bps"] == X.SLIPPAGE_BPS == 5.0
    assert d["delay_minutes"] == X.DELAY_BARS == 1
    assert d["horizon_minutes"] == X.HORIZON_BARS == 8
    assert d["initial_cash"] == X.INITIAL_CASH == 10000.0
    assert d["reinforce_full_scale"] == X.REINFORCE_FULL_SCALE == 0.01
    assert d["reinforce_cap"] == X.REINFORCE_CAP == 1.0
    assert d["dataset_label"] == "HISTORICAL_MARKET"
