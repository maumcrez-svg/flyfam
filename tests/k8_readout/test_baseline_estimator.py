"""
D4 §3 — the WAIT margin for a k-presentation estimator.

The decoder states its margin in units of the measured dispersion of its own
baseline readout, so replacing one presentation by the mean of k requires that
dispersion to be re-measured for the new estimator. This file tests the
estimator, not the number: the measurement itself is pre-registered in
``experiments/k8_readout/PROTOCOL.md`` and its artifact is committed separately.

What must hold whatever the number turns out to be:

* the distribution normalised is the **batch** distribution, and the divisor is
  its sample standard deviation, never the standard error of its mean;
* zero dispersion is an explicit failure, never an epsilon or a substitute;
* the dimensionless coefficient stays 1.0 and the decoder formula and sign
  convention are untouched;
* a margin measured for one k is not a margin for another, and an artifact says
  which graph and which brain state it was measured against.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from flytrade import decoder as D
from flytrade import readout as RO


def _samples(n=64, seed=3):
    rng = np.random.default_rng(seed)
    return list(rng.normal(-2.3, 1.15, size=n))


def test_the_divisor_is_the_sample_sd_of_the_batches_not_a_standard_error():
    x = _samples()
    b = RO.Baseline.from_samples(x, k=8)
    assert b.sd_hz == pytest.approx(float(np.std(x, ddof=1)), rel=1e-12)
    assert b.baseline_hz == pytest.approx(float(np.mean(x)), rel=1e-12)
    assert b.n_batches == len(x)
    # the standard error would be smaller by sqrt(n) and is NOT what is used
    se = float(np.std(x, ddof=1)) / np.sqrt(len(x))
    assert abs(b.sd_hz - se) > 1e-6
    assert "never the standard error" in b.distribution


def test_the_margin_coefficient_stays_one_and_the_formula_is_untouched():
    b = RO.Baseline.from_samples(_samples(), k=8)
    assert b.theta_sd == D.THETA_SD == 1.0
    assert b.theta_hz == pytest.approx(b.sd_hz, rel=1e-15)
    dec = b.decoder()
    assert dec.baseline_hz == b.baseline_hz
    assert dec.theta_hz == b.theta_hz
    # same rule, same sign: approach above avoid by more than theta is BUY
    d = dec.decode_rates(50.0, 10.0)
    assert d.action is D.Action.BUY
    assert d.raw_valence_hz == pytest.approx(40.0)
    assert d.valence_hz == pytest.approx(40.0 - b.baseline_hz)
    assert dec.decode_rates(10.0, 50.0).action is D.Action.SELL
    assert dec.max_kc_fraction == D.MAX_KC_FRACTION
    assert dec.saturated_hz == D.SATURATED_HZ


def test_zero_dispersion_stops_the_estimator_instead_of_inventing_a_divisor():
    with pytest.raises(RO.DegenerateBaseline, match="identical"):
        RO.Baseline.from_samples([-2.3] * 64, k=8)
    with pytest.raises(RO.DegenerateBaseline, match="two batches"):
        RO.Baseline.from_samples([-2.3], k=8)
    with pytest.raises(RO.DegenerateBaseline, match="finite"):
        RO.Baseline.from_samples([0.0, float("nan")], k=8)


def test_an_artifact_round_trips_and_carries_what_it_was_measured_against(
        tmp_path):
    b = RO.Baseline.from_samples(_samples(), k=8, graph_sha256="a" * 64,
                                 state_digest="b" * 64, commit="deadbee",
                                 measured_at=1.0)
    p = b.save(tmp_path / "baseline_k8.json")
    back = RO.load_baseline(p, k=8, graph_sha256="a" * 64)
    assert back.as_dict() == b.as_dict()
    assert back.theta_hz == b.theta_hz
    assert json.loads(p.read_text())["theta_sd"] == 1.0

    # a margin measured for one k is not a margin for another
    with pytest.raises(ValueError, match="not a margin"):
        RO.load_baseline(p, k=1)
    # nor is one measured against another graph
    with pytest.raises(ValueError, match="graph"):
        RO.load_baseline(p, graph_sha256="c" * 64)


def test_a_policy_built_from_a_baseline_decodes_with_that_margin(tmp_path):
    b = RO.Baseline.from_samples(_samples(), k=8)
    pol = RO.ReadoutPolicy.from_baseline(b)
    assert pol.k == 8
    assert pol.decoder.theta_hz == b.theta_hz
    # the per-replicate decoder keeps the k = 1 constants: a single
    # presentation is a k = 1 reading and is recorded as one
    assert pol.decoder_k1.theta_hz == D.THETA_HZ
    assert pol.decoder_k1.baseline_hz == D.BASELINE_HZ
    assert pol.as_dict()["decoder"]["theta_hz"] == b.theta_hz


def test_the_k1_constants_in_the_decoder_are_left_exactly_where_they_were():
    """The k = 1 mode keeps the Phase One constants, measured before any PnL."""
    assert D.BASELINE_HZ == -2.303340517241379
    assert D.BASELINE_SD_HZ == 3.241438214716715
    assert D.THETA_HZ == D.THETA_SD * D.BASELINE_SD_HZ
    assert D.THETA_SD == 1.0
