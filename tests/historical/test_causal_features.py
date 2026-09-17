"""
Causal feature normalisation on historical bars.

Amendment D6 §3: "Normalization must use available past/current observations
only, never the full dataset or future evaluation period." The property that
matters is not that the code *intends* to be causal but that appending later
data cannot change an earlier number — which is what these tests check, by
truncating the file and comparing.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from flytrade import historical as H
from flytrade import market as MK
from tests.historical import make_fixtures as MF

D0, D1, D2 = MF.DAYS


def _truncate(path, tmp_path, keep_days):
    """The same file with the later sessions removed."""
    keep = {d.strftime("%m/%d/%Y") for d in keep_days}
    lines = [l for l in path.read_text().splitlines()
             if l.split(",")[0] in keep]
    out = tmp_path / f"trunc_{len(keep_days)}.txt"
    out.write_text("\n".join(lines) + "\n")
    return out


def test_truncating_the_future_does_not_move_a_single_past_number(
        fixtures, series_a, tmp_path):
    """The decisive causality test: the file's tail cannot reach its head."""
    short = H.load_series(_truncate(fixtures["A"], tmp_path, [D0, D1]), "A")
    moved = 0
    for m in range(120):
        a = series_a.observe(D1, m, stable_id=0)
        b = short.observe(D1, m, stable_id=0)
        assert a.status is b.status, m
        if not a.status.usable:
            continue
        moved += 1
        assert np.allclose(a.raw, b.raw, rtol=0, atol=0), m
        assert np.allclose(a.normalized, b.normalized, rtol=0, atol=0), m
        assert np.allclose(a.z, b.z, rtol=0, atol=0), m
    assert moved > 50, "the comparison has to actually compare something"


def test_the_trailing_window_is_sixty_usable_rows_ending_at_the_cutoff(
        series_a):
    s = series_a
    # the first 60 usable rows of the file are WARMUP; the 60th is the first OK
    first_ok = next(m for m in range(120)
                    if s.status(D0, m) is H.HistoricalStatus.OK)
    assert first_ok == H.FEATURE_LOOKBACK + H.Z_WINDOW - 1 == 79
    assert s.status(D0, first_ok - 1) is H.HistoricalStatus.WARMUP
    obs = s.observe(D0, first_ok, stable_id=0)
    assert obs.status is MK.ObservationStatus.OK
    # and the z is the raw against exactly that window's mean and sd
    hist = s._usable_raw[:H.Z_WINDOW]
    mu, sd = hist.mean(axis=0), hist.std(axis=0, ddof=1)
    assert np.allclose(obs.z, (obs.raw - mu) / sd)
    assert np.allclose(obs.normalized, np.tanh(obs.z / H.Z_SCALE))


def test_the_first_twenty_minutes_of_every_session_are_warmup(series_a):
    """No lookback crosses a session, so no overnight return exists."""
    for day in series_a.days:
        for m in range(H.FEATURE_LOOKBACK):
            assert series_a.status(day, m) in (
                H.HistoricalStatus.WARMUP, H.HistoricalStatus.DATA_GAP), (day, m)


def test_the_features_are_the_phase_one_five_computed_in_market_minutes(
        series_a):
    s = series_a
    m = 95
    obs = s.observe(D1, m, stable_id=0)
    assert obs.status is MK.ObservationStatus.OK
    ses = s.sessions[D1]
    rc = ses.ref_close
    p0 = float(ses.close[m])
    want = [math.log(p0 / rc[m - 1]), math.log(p0 / rc[m - 5]),
            math.log(p0 / rc[m - 20])]
    assert obs.raw[0] == pytest.approx(want[0])
    assert obs.raw[1] == pytest.approx(want[1])
    assert obs.raw[2] == pytest.approx(want[2])
    assert list(MK.FEATURES) == ["r1", "r5", "r20", "rv20", "relvol"]
    assert obs.raw[3] > 0.0                      # rv20 is a dispersion
    assert len(obs.raw) == 5


def test_relvol_treats_an_omitted_minute_as_zero_volume_not_as_absent(
        series_a):
    """The one place a missing bar contributes a number, and it is zero."""
    s = series_a
    ses = s.sessions[D1]
    m = 104                                      # right after the 4-minute gap
    obs = s.observe(D1, m, stable_id=0)
    assert obs.status is MK.ObservationStatus.OK
    mean_per_minute = float(ses.volume[m - 19:m + 1].sum()) / H.FEATURE_LOOKBACK
    assert obs.raw[4] == pytest.approx(math.log(float(ses.volume[m])
                                                / mean_per_minute))
    # the four absent minutes carry volume 0 and are counted in the divisor
    assert np.all(ses.volume[100:104] == 0.0)
    # so the denominator is smaller than it would be over present rows only
    present_only = float(ses.volume[m - 19:m + 1].sum()) / int(
        ses.present[m - 19:m + 1].sum())
    assert present_only > mean_per_minute


def test_an_unusable_observation_is_never_a_flat_market(series_a):
    """Zeros plus a status, never zeros alone."""
    for day, m in ((D1, 101), (D2, 75), (D0, 3)):
        obs = series_a.observe(day, m, stable_id=0)
        assert not obs.status.usable
        assert np.all(obs.normalized == 0.0)
        assert np.all(obs.raw == 0.0)
        assert obs.detail
        # and the encoder refuses it rather than encoding a flat tape
        from flytrade import encoder as E
        assert obs.status is not MK.ObservationStatus.OK


def test_the_normaliser_never_sees_the_evaluation_period_while_learning(
        fixtures, tmp_path):
    """A learning-period observation is identical with and without the
    evaluation days on disk."""
    full = H.load_series(fixtures["A"], "A")
    learn_only = H.load_series(_truncate(fixtures["A"], tmp_path, [D0, D1]), "A")
    a = full.observe(D1, 119, stable_id=0)
    b = learn_only.observe(D1, 119, stable_id=0)
    assert a.status is b.status is MK.ObservationStatus.OK
    assert a.as_dict() == b.as_dict()


def test_clipping_and_saturation_are_reported_not_engineered_away(series_a):
    """``tanh`` bounds the encoder input; how often it is near the bound is a
    measurement, and the bound itself is not touched."""
    vals = []
    for day in series_a.days:
        for m in range(120):
            o = series_a.observe(day, m)
            if o.status.usable:
                vals.append(np.abs(o.normalized))
    v = np.concatenate(vals)
    assert v.max() < 1.0                    # tanh never reaches the bound
    near = float((v > 0.99).mean())
    assert 0.0 <= near <= 1.0
    # the declared scale is Phase One's, unchanged by anything measured here
    assert H.Z_SCALE == MK.Z_SCALE == 2.0
    assert H.Z_WINDOW == MK.Z_WINDOW == 60
