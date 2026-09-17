"""``pons_encoder_v1``: determinism, invalid input, the channel budget.

The brain's annotation set is real (``data/malecns-v1.0``); the contexts are
scripted (``tests.d10.fixtures``). If the connectome is not on disk the tests
that need it skip and say so.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from flytrade import encoder as E
from flytrade import populations as P
from flytrade.market import ObservationStatus
from flytrade.pons.context import PONS_FEATURES
from flytrade.pons.encoder import (EXTENSION_POINTS, OLFACTORY, SensoryEncoder,
                                   UnusableObservation)
from tests.d10 import fixtures as F

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "malecns-v1.0"
SCALES = {"age": 600.0, "ret_30s": 0.0051, "ret_2m": 0.11, "ret_5m": 0.36,
          "flow_imb_2m": 1.0, "trade_rate_2m": 6.0, "rv_2m": 0.029,
          "drawdown_5m": 0.51}


@pytest.fixture(scope="module")
def ann():
    if not (DATA / "annotations.npz").exists():
        pytest.skip(f"{DATA} is not on disk; see data/MANIFEST.md")
    return P.Annotations.load(DATA / "annotations.npz")


@pytest.fixture(scope="module")
def encoder(ann):
    return SensoryEncoder(ann, SCALES)


def test_all_eight_features_fit_and_none_is_dropped(encoder):
    assert encoder.features == PONS_FEATURES
    assert encoder.dropped == ()
    assert len(encoder.olfactory.channels) == 8
    assert len(encoder.olfactory.glomeruli) == 16


def test_a_feature_is_dropped_from_the_end_when_the_channels_run_out(ann):
    """The declared rule, exercised by asking for more channels than exist."""
    with pytest.raises(ValueError):
        E.channel_glomeruli(ann, n_features=40)
    encoder = SensoryEncoder(ann, {**SCALES, **{f"x{i}": 1.0 for i in range(40)}},
                             features=PONS_FEATURES + tuple(f"x{i}" for i in range(40)))
    assert encoder.dropped
    assert encoder.features == tuple(
        (PONS_FEATURES + tuple(f"x{i}" for i in range(40)))[:len(encoder.features)])
    assert encoder.dropped[-1] == "x39"          # dropped from the end
    assert encoder.as_dict()["features_dropped"] == list(encoder.dropped)


def test_the_encoder_returns_only_the_olfactory_modality(encoder):
    tape = F.traded_tape()
    context = tape.context(tape.launched_at + 200, stable_id=0)
    out = encoder.encode(context, symbol=tape.token)
    assert set(out) == {OLFACTORY}
    assert encoder.modalities == (OLFACTORY,)
    assert set(EXTENSION_POINTS) == {"visual", "taste", "mechanosensory"}
    assert encoder.as_dict()["extension_points_implemented"] is False


def test_the_extension_points_are_named_and_nowhere_else(encoder):
    """Correction (c): named, unimplemented, and not routed anywhere."""
    tape = F.traded_tape()
    context = tape.context(tape.launched_at + 200, stable_id=0)
    out = encoder.encode(context, symbol=tape.token)
    for name in EXTENSION_POINTS:
        assert name not in out
    source = (ROOT / "flytrade" / "pons" / "encoder.py").read_text()
    for name in EXTENSION_POINTS:
        # exactly once each, in the declaration; no stub returning zeros
        assert source.count(f'"{name}"') == 1


def test_the_same_context_always_gives_the_identical_stimulus(encoder):
    tape = F.traded_tape()
    context = tape.context(tape.launched_at + 200, stable_id=3)
    first = encoder.encode(context, symbol=tape.token)[OLFACTORY]
    for _ in range(5):
        again = encoder.encode(context, symbol=tape.token)[OLFACTORY]
        assert again.rates == first.rates
        assert np.array_equal(again.normalized, first.normalized)
        assert again.total_drive_hz == first.total_drive_hz


def test_an_unusable_observation_is_refused_with_its_status_and_reason(encoder):
    tape = F.traded_tape()
    context = tape.context(tape.launched_at + 10, stable_id=0)
    with pytest.raises(UnusableObservation) as caught:
        encoder.encode(context, symbol=tape.token)
    assert caught.value.status is ObservationStatus.INSUFFICIENT_TAPE
    assert caught.value.reason


def test_a_missing_scale_is_refused_at_construction(ann):
    with pytest.raises(ValueError) as caught:
        SensoryEncoder(ann, {k: v for k, v in SCALES.items() if k != "rv_2m"})
    assert "rv_2m" in str(caught.value)


def test_the_drive_stays_inside_the_declared_window(encoder):
    """Addendum 1's window: per-ORN rates in [0, 150] Hz, whatever the input."""
    for value in (-1.0, -0.5, 0.0, 0.5, 1.0):
        rates = encoder.olfactory.rates(np.full(8, value))
        assert all(0.0 <= hz <= E.DRIVE_MAX_HZ for hz in rates.values())
    extreme = encoder.olfactory.rates(np.array(
        [1.0, -1.0, 1.0, -1.0, 1.0, -1.0, 1.0, -1.0]))
    assert all(0.0 <= hz <= E.DRIVE_MAX_HZ for hz in extreme.values())


def test_two_tokens_with_identical_features_give_an_identical_stimulus(encoder):
    """Ticker identity is metadata, and is not encoded."""
    a = F.traded_tape(token="0x" + "a" * 40, curve="0x" + "1" * 40)
    b = F.traded_tape(token="0x" + "f" * 40, curve="0x" + "2" * 40)
    ca = a.context(a.launched_at + 200, stable_id=0)
    cb = b.context(b.launched_at + 200, stable_id=7)
    sa = encoder.encode(ca, symbol=a.token)[OLFACTORY]
    sb = encoder.encode(cb, symbol=b.token)[OLFACTORY]
    assert sa.rates == sb.rates
    assert np.array_equal(sa.normalized, sb.normalized)


def test_a_non_finite_feature_is_refused_rather_than_encoded(encoder):
    with pytest.raises(ValueError):
        encoder.olfactory.rates(np.array([np.nan] + [0.0] * 7))
    with pytest.raises(ValueError):
        encoder.olfactory.rates(np.array([np.inf] + [0.0] * 7))


def test_the_channel_map_is_recorded_in_full(encoder, ann):
    table = encoder.as_dict()["channels"]
    assert [row["feature"] for row in table] == list(PONS_FEATURES)
    assert all(row["pos_orns"] > 0 and row["neg_orns"] > 0 for row in table)
    assert all(row["pos_upns"] >= E.MIN_UPNS and row["neg_upns"] >= E.MIN_UPNS
               for row in table)
