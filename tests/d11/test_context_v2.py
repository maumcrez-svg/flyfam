"""``pons_context_v2``: quiet has a duration, and absence is not a zero.

Owner bullets 10, 11 and 12. Tapes are scripted (``tests.d11.fixtures``, whose
numbers are invented and labelled as such); the context arithmetic, the curve
quote and the tape reconstruction are real.
"""

from __future__ import annotations

import math

import pytest

from flytrade import market as MK
from flytrade.pons.context import PONS_FEATURES
from flytrade.pons.context_v2 import (PONS_FEATURES_V2,
                                      SINCE_LAST_TRADE_SCALE_S, context_v2,
                                      recent_activity, valid_trades)
from tests.d11 import fixtures as F


def raw_at(tape, cutoff):
    return context_v2(tape, cutoff).raw


# --------------------------------------------- the declared shape of v2
def test_the_ten_features_are_in_the_declared_order():
    assert PONS_FEATURES_V2 == (
        "age", "since_last_trade", "ret_30s", "ret_2m", "ret_5m",
        "flow_imb_2m", "trade_count_2m", "gross_volume_2m", "rv_2m",
        "drawdown_5m")


def test_since_last_trade_uses_the_admission_bound_as_its_declared_scale():
    from flytrade.pons.admission_v2 import MAX_SECONDS_SINCE_LAST_TRADE
    assert SINCE_LAST_TRADE_SCALE_S == float(MAX_SECONDS_SINCE_LAST_TRADE)


def test_v1_is_untouched():
    """The eight-feature order and module are exactly what D10 committed."""
    from flytrade.pons import context as C1
    assert C1.VERSION == "pons_context_v1"
    assert PONS_FEATURES == ("age", "ret_30s", "ret_2m", "ret_5m",
                             "flow_imb_2m", "trade_rate_2m", "rv_2m",
                             "drawdown_5m")


# ------------------------ bullet 10: active-flat versus inactive inputs
def test_a_busy_flat_market_and_a_dead_one_are_different_inputs():
    """The defect D11 repairs: under v1 these two collapse to one vector."""
    busy = F.flat_but_busy_tape()
    dead = F.quiet_tape()
    cutoff = F.FIRST_TS + 300
    b, d = raw_at(busy, cutoff), raw_at(dead, cutoff)
    assert b["trade_count_2m"] > 10 and d["trade_count_2m"] == 0.0
    assert b["gross_volume_2m"] > 0.0 and d["gross_volume_2m"] == 0.0
    assert b["since_last_trade"] < 30 and d["since_last_trade"] > 200
    for name in ("since_last_trade", "trade_count_2m", "gross_volume_2m"):
        assert b[name] != d[name]


def test_quiet_for_ten_minutes_and_quiet_for_fifty_are_different_inputs():
    """Under v1 both saturate ``age`` and nothing else moves."""
    tape = F.quiet_tape(coverage_seconds=6_000)
    ten = raw_at(tape, F.FIRST_TS + 60 + 600)
    fifty = raw_at(tape, F.FIRST_TS + 60 + 3_000)
    assert fifty["since_last_trade"] - ten["since_last_trade"] == 2400.0
    a = math.tanh(ten["since_last_trade"] / SINCE_LAST_TRADE_SCALE_S)
    b = math.tanh(fifty["since_last_trade"] / SINCE_LAST_TRADE_SCALE_S)
    assert a > 0.99 and b > 0.99, "both saturate, as declared"
    assert ten["since_last_trade"] != fifty["since_last_trade"]


def test_the_four_owner_distinctions_are_measurable():
    cutoff = F.FIRST_TS + 300
    # A: no trades in the interval
    a = raw_at(F.quiet_tape(), cutoff)
    assert a["trade_count_2m"] == 0.0 and a["gross_volume_2m"] == 0.0
    assert a["since_last_trade"] >= 120
    # B and C: many trades, buys and sells cancelling, real gross volume
    busy = raw_at(F.flat_but_busy_tape(), cutoff)
    assert busy["trade_count_2m"] >= 10
    assert busy["gross_volume_2m"] > 0.0
    assert abs(busy["flow_imb_2m"]) < 0.9, "gross volume without a net direction"
    # D: not presented at all
    young = context_v2(F.traded_at((5, 10, 20)), F.FIRST_TS + 30)
    assert not young.usable
    assert young.status is MK.ObservationStatus.INSUFFICIENT_TAPE
    assert young.raw == {}


def test_gross_volume_is_gross_and_flow_imbalance_is_net():
    """The two read the same trades and answer different questions."""
    tape = F.flat_but_busy_tape()
    cutoff = F.FIRST_TS + 300
    window = valid_trades(tape._upto(cutoff), window=(cutoff - 120, cutoff))
    assert any(p.flow > 0 for p in window) and any(p.flow < 0 for p in window)
    gross = sum(abs(int(p.flow)) for p in window) / 10 ** 18
    net = sum(int(p.flow) for p in window) / 10 ** 18
    buy_in = sum(int(p.flow) for p in window if p.flow > 0)
    sell_out = -sum(int(p.flow) for p in window if p.flow < 0)
    r = raw_at(tape, cutoff)
    assert r["gross_volume_2m"] == pytest.approx(gross)
    assert gross > abs(net), "both signs present: the gross exceeds the net"
    assert r["flow_imb_2m"] == pytest.approx(
        (buy_in - sell_out) / (buy_in + sell_out))


def test_net_signed_flow_alone_cannot_tell_a_dead_token_from_a_balanced_one():
    """The reason gross volume is a feature at all."""
    cutoff = F.FIRST_TS + 300
    balanced = F.traded_at((250, 290), sells={290})
    dead = F.quiet_tape()
    b, d = raw_at(balanced, cutoff), raw_at(dead, cutoff)
    assert b["gross_volume_2m"] > 0.0 and d["gross_volume_2m"] == 0.0
    assert b["trade_count_2m"] == 2.0 and d["trade_count_2m"] == 0.0


def test_trade_count_replaces_the_rate_and_counts_the_same_events():
    tape = F.traded_at((200, 230, 260, 290))
    cutoff = F.FIRST_TS + 300
    v2 = raw_at(tape, cutoff)
    v1 = tape.context(cutoff).raw
    assert v2["trade_count_2m"] == 4.0
    assert v1["trade_rate_2m"] == pytest.approx(4.0 * 60.0 / 120.0)


# ------------------------------------- bullet 11: zero versus missing
def test_a_measured_zero_and_a_missing_measurement_are_not_the_same_object():
    quiet = context_v2(F.quiet_tape(), F.FIRST_TS + 300)
    young = context_v2(F.traded_at((5, 10)), F.FIRST_TS + 30)
    assert quiet.usable and quiet.raw["trade_count_2m"] == 0.0
    assert not young.usable and young.raw == {}
    assert quiet.status is MK.ObservationStatus.OK
    assert young.status is MK.ObservationStatus.INSUFFICIENT_TAPE


def test_an_inconsistent_tape_is_never_priced_as_a_flat_market():
    tape = F.traded_at((20, 250))
    tape.inconsistent = "SCRIPTED: the arithmetic did not reproduce"
    ctx = context_v2(tape, F.FIRST_TS + 300)
    assert not ctx.usable
    assert ctx.status is MK.ObservationStatus.INCONSISTENT_STATE
    assert ctx.raw == {}


def test_a_completed_curve_keeps_its_own_status():
    tape = F.traded_at((20, 250, 290))
    tape.apply(F.completed_event(tape.curve, at_seconds=295))
    ctx = context_v2(tape, F.FIRST_TS + 300)
    assert ctx.status is MK.ObservationStatus.ROUTE_COMPLETED
    assert ctx.raw == {}


def test_a_token_that_never_traded_reports_its_age_not_a_zero():
    """``since_last_trade`` clipped to the launch, like every other window."""
    tape = F.tape()
    ctx = context_v2(tape, F.FIRST_TS + 300)
    assert ctx.usable
    assert ctx.raw["since_last_trade"] == 300.0 == ctx.raw["age"]
    assert ctx.raw["since_last_trade"] != 0.0


# ------------------------------------------------- causality and clipping
def test_every_feature_is_causal_at_the_cutoff():
    short = F.traded_at((20, 250, 290))
    long = F.traded_at((20, 250, 290, 320, 400, 500))
    cutoff = F.FIRST_TS + 300
    assert raw_at(short, cutoff) == raw_at(long, cutoff)


def test_windows_are_clipped_to_the_launch_and_not_zeroed():
    tape = F.traded_at((20, 40, 55))
    ctx = context_v2(tape, F.FIRST_TS + 60)
    assert ctx.usable
    assert ctx.raw["ret_5m"] != 0.0, "measured from the launch, not zeroed"


def test_the_valid_trade_definition_is_shared_with_admission():
    from flytrade.pons import admission_v2 as A
    from flytrade.pons import context_v2 as C
    assert A.recent_activity is C.recent_activity


def test_recent_activity_agrees_with_the_feature_it_shares():
    tape = F.traded_at((20, 250, 290))
    cutoff = F.FIRST_TS + 300
    act = recent_activity(tape, cutoff, window_s=120)
    ctx = context_v2(tape, cutoff)
    assert act["trades_in_window"] == ctx.raw["trade_count_2m"]
    assert act["since_last_trade_s"] == ctx.raw["since_last_trade"]
    assert act["trades_ever"] == ctx.trades


def test_valid_trades_deduplicates_and_windows_half_open():
    tape = F.traded_at((20, 250, 290))
    upto = tape._upto(F.FIRST_TS + 300)
    assert len(valid_trades(upto)) == 3
    assert len(valid_trades(upto, window=(F.FIRST_TS + 180, F.FIRST_TS + 300))) == 2
