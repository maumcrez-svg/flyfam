"""
The measured k = 8 baseline, and the constants that carry it.

``flytrade/readout.py`` holds the two numbers in code the way
``flytrade/decoder.py`` holds the k = 1 pair measured by
``encoder_range.json``. This asserts the code has not drifted from the artifact
it claims to quote, that the artifact says what it was measured against, and
that the k = 1 constants have not been retrofitted to it.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from flytrade import decoder as D
from flytrade import readout as RO

ART = Path(__file__).resolve().parents[2] / RO.BASELINE_ARTIFACT


def test_the_constants_in_code_are_the_ones_in_the_artifact():
    assert ART.exists(), f"{ART} is missing"
    d = json.loads(ART.read_text())
    assert d["k"] == RO.K == 8
    assert d["baseline_hz"] == RO.BASELINE_HZ_K8
    assert d["sd_hz"] == RO.BASELINE_SD_HZ_K8
    assert d["theta_hz"] == RO.THETA_HZ_K8
    assert d["theta_sd"] == D.THETA_SD == 1.0
    assert d["n_batches"] == 64 == len(d["samples"])
    assert d["namespace"] == RO.BASELINE_NAMESPACE


def test_the_artifact_records_what_it_was_measured_against():
    d = json.loads(ART.read_text())
    assert len(d["graph_sha256"]) == 64
    assert len(d["state_digest"]) == 64
    assert len(d["commit"]) == 40
    assert d["stimulus"] == "neutral_reference"
    assert "never the standard error" in d["distribution"]
    assert d["decoder_version"] == D.VERSION
    assert d["readout_version"] == RO.VERSION
    # loading validates the k and the graph it belongs to
    b = RO.load_baseline(ART, k=8, graph_sha256=d["graph_sha256"])
    assert b.theta_hz == RO.THETA_HZ_K8
    with pytest.raises(ValueError, match="not a margin"):
        RO.load_baseline(ART, k=1)


def test_the_k1_constants_were_not_retrofitted_to_the_k8_measurement():
    assert D.BASELINE_HZ == -2.303340517241379
    assert D.BASELINE_SD_HZ == 3.241438214716715
    assert D.THETA_HZ == D.THETA_SD * D.BASELINE_SD_HZ
    # and the two margins are genuinely different numbers
    assert RO.THETA_HZ_K8 < D.THETA_HZ
    assert RO.decoder_k8().theta_hz == RO.THETA_HZ_K8
    assert RO.decoder_k8().baseline_hz == RO.BASELINE_HZ_K8


def test_the_k8_decoder_is_the_same_decoder_with_two_different_constants():
    k8 = RO.decoder_k8()
    assert k8.version == D.VERSION
    assert k8.max_kc_fraction == D.MAX_KC_FRACTION
    assert k8.saturated_hz == D.SATURATED_HZ
    # same formula, same sign, same rule order
    d = k8.decode_rates(30.0, 10.0)
    assert d.raw_valence_hz == pytest.approx(20.0)
    assert d.valence_hz == pytest.approx(20.0 - RO.BASELINE_HZ_K8)
    assert d.action is D.Action.BUY
    assert k8.decode_rates(10.0, 30.0).action is D.Action.SELL
    assert k8.decode_rates(0.0, 0.0).status is D.ReadoutStatus.NO_RESPONSE
    assert k8.decode_rates(10.0, 10.0, kc_fraction=0.9).status \
        is D.ReadoutStatus.INVALID_STATE
    # the margin is narrower at k = 8, which is the whole point of measuring
    # it: a readout that the k = 1 margin calls noise the k = 8 margin decides
    raw = 0.5
    assert -RO.BASELINE_HZ_K8 + raw > RO.THETA_HZ_K8
    assert -D.BASELINE_HZ + raw <= D.THETA_HZ
    assert k8.decode_rates(raw, 0.0).action is D.Action.BUY
    assert D.ActionDecoder().decode_rates(raw, 0.0).action is D.Action.WAIT


def test_the_policy_the_wave_runs_is_k8_with_the_k8_margin():
    p = RO.policy_k8()
    assert p.k == 8
    assert p.namespace == RO.ROUND_NAMESPACE
    assert p.decoder.theta_hz == RO.THETA_HZ_K8
    assert p.decoder_k1.theta_hz == D.THETA_HZ      # per-replicate record


# ---------------------------------------------------------------- D5 freeze

def test_d5_the_artifact_is_loaded_exactly_never_a_rounded_report_number():
    """The stored values are used at full precision, not transcribed.

    D5 §1: "Load the exact stored values. Do not replace them with rounded
    numbers copied from the report." The report prints 0.9117 Hz; the artifact
    holds 0.9117185769796697, and the two are not the same number.
    """
    d = json.loads(ART.read_text())
    assert repr(d["sd_hz"]) == "0.9117185769796697"
    assert repr(d["baseline_hz"]) == "-0.844389816810345"
    # a run loads the artifact and gets those, bit for bit
    b = RO.load_baseline(ART, k=8)
    assert b.sd_hz == d["sd_hz"] and b.baseline_hz == d["baseline_hz"]
    assert b.theta_hz == D.THETA_SD * d["sd_hz"]
    # the four-decimal versions the reports quote are NOT what decides
    assert b.theta_hz != 0.9117
    assert b.baseline_hz != -0.8444
    assert RO.decoder_k8().theta_hz == b.theta_hz


def test_d5_the_coefficient_is_one_and_theta_is_derived_not_typed():
    assert D.THETA_SD == 1.0
    assert RO.THETA_HZ_K8 == D.THETA_SD * RO.BASELINE_SD_HZ_K8
    assert D.THETA_HZ == D.THETA_SD * D.BASELINE_SD_HZ
    # the decoder carries no separate stored theta that could drift
    assert RO.baseline_k8().theta_sd == 1.0
    assert RO.baseline_k8().theta_hz == RO.THETA_HZ_K8


def test_d5_the_margin_carries_no_market_quantity():
    """theta is an action-decoding rule, not a probability of success.

    Nothing in the decoder's configuration is a price, a return, a fee, a
    horizon or an outcome; the only inputs are firing rates. This is asserted
    rather than asserted in prose: a future edit that smuggles a PnL-derived
    term into the decoder has to delete this test to do it.
    """
    cfg = RO.decoder_k8().as_dict()
    assert set(cfg) == {"version", "baseline_hz", "theta_hz", "theta_sd",
                        "baseline_sd_hz", "max_kc_fraction", "saturated_hz"}
    # and decoding depends on the two rates and the two regime guards only
    d1 = RO.decoder_k8().decode_rates(12.0, 9.0, kc_fraction=0.02,
                                      max_rate_hz=40.0)
    d2 = RO.decoder_k8().decode_rates(12.0, 9.0, kc_fraction=0.02,
                                      max_rate_hz=40.0)
    assert d1.as_dict() == d2.as_dict()
