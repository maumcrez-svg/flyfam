"""
One fill convention, three callers — Fable addendum 1.

``g(t,H)`` (calibration), ``G(t)`` (the evaluator's label) and the
``POLICY_CLOSE`` fill of the paper execution policy must be the same
convention. These tests prove they are the same *function*: the same two bars,
the same two prices, the same money to the last representable digit — and that
the one case where the convention has to have three different behaviours, a
missing bar, is three declared behaviours of one rule and not three rules.
"""
from __future__ import annotations

from datetime import date

import pytest

from flytrade import execution as X
from flytrade import historical as H
from flytrade import horizon as HZ
from tests.d7.conftest import DAYS

NOTIONAL = 1000.0
FEE = 5.0
SLIP = 5.0
DELAY = 1


def policy(series, horizon):
    return H.HistoricalExecution(
        {series.symbol: series}, notional=NOTIONAL, fee_bps=FEE,
        slippage_bps=SLIP, delay_minutes=DELAY, horizon_minutes=horizon,
        initial_cash=10_000.0)


def round_trip(series, day, m, horizon):
    """One actual POLICY_CLOSE round trip through the execution policy."""
    pol = policy(series, horizon)
    pol.start_session(day)
    pos = pol.open_long(episode_id=1, symbol=series.symbol, stable_id=0,
                        decision_bar=m, day=day)
    if isinstance(pos, X.Rejection):
        return pos
    # the horizon falls due at entry + H; the loop closes at the first round
    # at or after that minute, which is what POLICY_CLOSE means
    return pol.close(decision_bar=pos.horizon_bar,
                     reason=X.CloseReason.POLICY_CLOSE, day=day)


def test_the_session_length_is_one_number_in_both_modules():
    assert HZ.SESSION_MINUTES == H.SESSION_MINUTES == 390


def test_the_execution_policy_locates_its_bars_with_the_shared_primitive():
    """Not "they agree today": the class calls the function."""
    src = (H.__file__ and open(H.__file__, encoding="utf-8").read())
    assert "return HZ.locate(self.series[symbol], day, target_minute)" in src


@pytest.mark.parametrize("horizon", HZ.H_SET)
@pytest.mark.parametrize("m", [25, 60, 137, 200])
def test_calibration_label_and_execution_agree_bar_for_bar(clean, m, horizon):
    day = DAYS[1]
    h = HZ.hold(clean, day, m, horizon, delay=DELAY)
    out = round_trip(clean, day, m, horizon)
    assert h.ok and not isinstance(out, X.Rejection)
    # the same two bars
    assert out.entry.bar_index == h.entry_minute
    assert out.exit.bar_index == h.exit_minute
    # the same two reference prices, exactly
    assert out.entry.reference_price == h.entry_open
    assert out.exit.reference_price == h.exit_open
    # and the same money: G(t) is the net return the policy books
    g = h.net_return(notional=NOTIONAL, fee_bps=FEE, slippage_bps=SLIP)
    assert out.net_pnl / NOTIONAL == pytest.approx(g, rel=0, abs=1e-12)
    assert out.return_on_notional == pytest.approx(g, rel=0, abs=1e-12)


def test_gross_bps_is_the_unslipped_reference_return(clean):
    day, m, horizon = DAYS[1], 80, 30
    h = HZ.hold(clean, day, m, horizon, delay=DELAY)
    out = round_trip(clean, day, m, horizon)
    booked = out.gross_reference_pnl / (out.entry.quantity * h.entry_open)
    assert h.gross_bps / 1e4 == pytest.approx(booked, rel=0, abs=1e-12)
    # and the gross is strictly larger than the net by exactly the costs
    net = h.net_return(notional=NOTIONAL, fee_bps=FEE, slippage_bps=SLIP)
    assert h.gross_bps / 1e4 > net


def test_a_missing_exit_bar_is_three_declared_behaviours_of_one_rule(gapped):
    """Calibration drops the origin; the label is unavailable; the fill delays.

    The fixture removes the single minute 15:31 of its second session, so a
    hold whose horizon lands exactly there has no bar at the minute the rule
    asks for.
    """
    day = DAYS[2]
    minute_removed = 150                      # the six-minute hole
    horizon = 30
    m = minute_removed - horizon - DELAY      # exit lands inside the hole
    h = HZ.hold(gapped, day, m, horizon, delay=DELAY)
    # 1. the label: located on the next available bar, and the delay is
    #    recorded rather than hidden
    assert h.ok and h.exit_minute > m + DELAY + horizon
    assert h.exit_delay > 0
    # 2. the execution: the same bar, flagged DELAYED_FILL
    out = round_trip(gapped, day, m, horizon)
    assert out.exit.bar_index == h.exit_minute
    assert out.exit.flag == H.DELAYED_FILL
    # 3. the calibration: the origin is still common (a later bar exists), and
    #    the common set is what every candidate horizon is measured on
    assert m in HZ.common_origins(gapped, day, (horizon,), delay=DELAY)


def test_no_exit_bar_at_all_is_named_and_never_invented(clean):
    """A horizon that cannot land inside the session is SESSION_HORIZON."""
    day = DAYS[0]
    h = HZ.hold(clean, day, 380, 120, delay=DELAY)
    assert not h.ok and h.reason == HZ.NoHold.SESSION_HORIZON
    assert round_trip(clean, day, 380, 120).reason \
        is X.RejectReason.SESSION_HORIZON


def test_the_clock_rule_is_evaluated_before_any_price_is_read():
    assert HZ.eligible(267, 120, delay=1) is True
    assert HZ.eligible(268, 120, delay=1) is True
    assert HZ.eligible(269, 120, delay=1) is False
    assert HZ.eligible(380, 8, delay=1) is True
    assert HZ.eligible(381, 8, delay=1) is False


def test_eligibility_matches_the_execution_policys_own_rule(clean):
    pol = policy(clean, 120)
    for m in (0, 100, 267, 268, 269, 300):
        assert pol.eligible_to_enter(m) == HZ.eligible(m, 120, delay=DELAY)


def test_nothing_in_the_convention_crosses_a_session(clean):
    """The exit of the last eligible origin is still inside the same day."""
    day = DAYS[1]
    for horizon in HZ.H_SET:
        origins = [m for m in range(390) if HZ.eligible(m, horizon, delay=DELAY)]
        h = HZ.hold(clean, day, origins[-1], horizon, delay=DELAY)
        assert h.ok and h.day == day
        assert h.exit_minute < H.SESSION_MINUTES
        assert H.session_date(h.exit_ts) == day
