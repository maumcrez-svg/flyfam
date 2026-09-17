"""
The horizon calibration — amendment §4 and §10's first three guards.

What these prove, on generated fixtures:

* every candidate horizon is measured on the **same** origins inside a
  session, so a difference between two ``A(H)`` values is a difference in
  horizon and never a difference in sample;
* the calibration never reads a price outside the sessions it was given — it
  is not merely that it does not, but that it *cannot*: the view it is handed
  raises;
* changing every LEARNING and FROZEN price cannot change ``H*``;
* the selection rule is "the smallest H that clears the bar", and when nothing
  clears it the result is ``NO_HORIZON_MEETS_RULE`` rather than the largest
  horizon or a smaller multiplier.
"""
from __future__ import annotations

import json

import pytest

from flytrade import horizon as HZ
from tests.d7.conftest import DAYS, LATER_DAYS, WARMUP_DAYS

import calibrate as CAL            # experiments/d7/calibrate.py

DELAY = 1


def test_the_common_origin_set_is_shared_by_every_candidate_horizon(clean):
    day = DAYS[1]
    common = HZ.common_origins(clean, day, HZ.H_SET, delay=DELAY)
    assert len(common) > 100
    for h in HZ.H_SET:
        for m in common:
            assert HZ.hold(clean, day, m, h, delay=DELAY).ok, (h, m)
    # and the set is exactly what the longest horizon allows, intersected with
    # the encodable minutes: no horizon gets an origin the others do not have
    assert max(common) <= 390 - 1 - DELAY - max(HZ.H_SET)


def test_the_origin_set_does_not_depend_on_the_horizon_it_is_asked_for(clean):
    day = DAYS[1]
    a = HZ.common_origins(clean, day, HZ.H_SET, delay=DELAY)
    b = HZ.common_origins(clean, day, tuple(reversed(HZ.H_SET)), delay=DELAY)
    assert a == b


def test_a_gap_removes_an_origin_from_the_common_set_for_every_horizon(gapped):
    """An origin one horizon cannot use is used by none of them."""
    day = DAYS[2]
    common = HZ.common_origins(gapped, day, HZ.H_SET, delay=DELAY)
    for m in common:
        assert all(HZ.hold(gapped, day, m, h, delay=DELAY).ok for h in HZ.H_SET)


def test_the_calibration_cannot_read_a_session_it_was_not_given(clean):
    view = CAL.WarmupOnly(clean, WARMUP_DAYS)
    HZ.calibrate(view, list(WARMUP_DAYS), cost_bps=20.0, delay=DELAY,
                 min_origins=10)
    assert view.touched == set(WARMUP_DAYS)
    with pytest.raises(CAL.OutsideWarmup):
        view.bar(LATER_DAYS[0], 100)
    with pytest.raises(CAL.OutsideWarmup):
        view.next_available(LATER_DAYS[0], 100)
    with pytest.raises(CAL.OutsideWarmup):
        view.status(LATER_DAYS[0], 100)


def test_changing_learning_and_frozen_prices_cannot_change_the_selection(
        clean, perturbed):
    """The §10 guard fixture: same WARMUP bytes, every later price scaled."""
    a = HZ.calibrate(CAL.WarmupOnly(clean, WARMUP_DAYS), list(WARMUP_DAYS),
                     cost_bps=1.0, delay=DELAY, min_origins=10)
    b = HZ.calibrate(CAL.WarmupOnly(perturbed, WARMUP_DAYS),
                     list(WARMUP_DAYS), cost_bps=1.0, delay=DELAY,
                     min_origins=10)
    assert a["A_bps"] == b["A_bps"]
    assert a["selected_horizon_minutes"] == b["selected_horizon_minutes"]
    # and the fixtures really do differ outside WARMUP, or the test is vacuous
    assert clean.bar(LATER_DAYS[0], 100).open \
        != perturbed.bar(LATER_DAYS[0], 100).open
    assert clean.bar(WARMUP_DAYS[0], 100).open \
        == perturbed.bar(WARMUP_DAYS[0], 100).open


def test_a_h_is_a_median_of_medians_in_that_order(clean):
    cal = HZ.calibrate(CAL.WarmupOnly(clean, WARMUP_DAYS), list(WARMUP_DAYS),
                       cost_bps=1.0, delay=DELAY, min_origins=10)
    for h in HZ.H_SET:
        per = [r["median_abs_g_bps"][str(h)] for r in cal["per_session"]]
        assert cal["A_bps"][str(h)] == pytest.approx(HZ.median(per))
        for r, day in zip(cal["per_session"], WARMUP_DAYS):
            gs = [abs(HZ.hold(clean, day, m, h, delay=DELAY).gross_bps)
                  for m in HZ.common_origins(clean, day, HZ.H_SET, delay=DELAY)]
            assert r["median_abs_g_bps"][str(h)] == pytest.approx(HZ.median(gs))


def test_the_rule_takes_the_smallest_qualifying_horizon(clean):
    cal = HZ.calibrate(CAL.WarmupOnly(clean, WARMUP_DAYS), list(WARMUP_DAYS),
                       cost_bps=0.0, delay=DELAY, min_origins=10)
    assert cal["selected_horizon_minutes"] == min(HZ.H_SET)
    assert cal["result"] == "OK"


def test_nothing_qualifying_is_a_bounded_result_not_a_fallback(clean):
    cal = HZ.calibrate(CAL.WarmupOnly(clean, WARMUP_DAYS), list(WARMUP_DAYS),
                       cost_bps=1e6, delay=DELAY, min_origins=10)
    assert cal["result"] == "NO_HORIZON_MEETS_RULE"
    assert cal["selected_horizon_minutes"] is None


def test_a_h_rises_with_the_horizon_on_this_fixture(clean):
    """Not a criterion — a sanity check that |g| is not constant in H."""
    cal = HZ.calibrate(CAL.WarmupOnly(clean, WARMUP_DAYS), list(WARMUP_DAYS),
                       cost_bps=1.0, delay=DELAY, min_origins=10)
    a = [cal["A_bps"][str(h)] for h in HZ.H_SET]
    assert a == sorted(a)


def test_the_measured_cost_is_a_real_round_trip_not_arithmetic():
    cfg = {"execution": {"notional": 1000.0, "fee_bps": 5.0,
                         "slippage_bps": 5.0, "delay_minutes": 1,
                         "initial_cash": 10000.0}}
    c = CAL.measure_cost_bps(cfg)
    # a flat price means the whole of the loss is cost
    assert c["gross_reference_pnl"] == pytest.approx(0.0, abs=1e-9)
    assert c["round_trip_cost_bps_measured"] == pytest.approx(20.0, abs=0.02)
    assert c["per_leg_bps"] == 10.0
    # and it is charged per execution, never twice on one execution
    assert c["fees"] == pytest.approx(2 * 0.0005 * 1000.0, rel=1e-3)


def test_the_measured_cost_follows_the_configured_numbers():
    cfg = {"execution": {"notional": 1000.0, "fee_bps": 2.5,
                         "slippage_bps": 7.5, "delay_minutes": 1,
                         "initial_cash": 10000.0}}
    c = CAL.measure_cost_bps(cfg)
    assert c["round_trip_cost_bps_measured"] == pytest.approx(20.0, abs=0.02)
    cfg["execution"]["fee_bps"] = 0.0
    cfg["execution"]["slippage_bps"] = 0.0
    assert CAL.measure_cost_bps(cfg)["round_trip_cost_bps_measured"] \
        == pytest.approx(0.0, abs=1e-9)


def test_the_committed_config_if_present_declares_the_rule_this_code_applies():
    p = CAL.CONFIG
    if not p.exists():
        pytest.skip("config.json is not committed yet")
    cfg = json.loads(p.read_text())
    assert tuple(cfg["horizon_rule"]["H_SET"]) == HZ.H_SET
    assert cfg["horizon_rule"]["multiple_of_cost"] == 2
    assert cfg["horizon_rule"]["selection"] == \
        "smallest H in H_SET with A(H) >= multiple * C"
    assert "horizon_minutes" not in cfg["execution"], \
        "the horizon is an output of the calibration, not a configured input"
