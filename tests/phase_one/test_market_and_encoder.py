"""
Canonical amendment §1 — market observations and the sensory encoder.

What these tests are for: that the encoder is deterministic and versioned, that
its normalisation is causal, that unusable data is refused rather than
smoothed, that the drive it emits stays inside the declared bounds and touches
nothing but ORNs, and that the operating range `docs/ENCODER.md` declares is
the one the code actually implements.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from flytrade import encoder as E
from flytrade import market as MK
from flytrade import populations as P

from .conftest import requires_real_graph


# ------------------------------------------------------------ market data

def test_synthetic_series_is_deterministic_in_its_seed():
    a = MK.synthetic_series("X", seed=7)
    b = MK.synthetic_series("X", seed=7)
    c = MK.synthetic_series("X", seed=8)
    assert [x.close for x in a.bars] == [x.close for x in b.bars]
    assert [x.close for x in a.bars] != [x.close for x in c.bars]
    assert len(a) == sum(r.bars for r in MK.DEFAULT_REGIMES)
    assert all(b_.high >= max(b_.open, b_.close) for b_ in a.bars)
    assert all(b_.low <= min(b_.open, b_.close) for b_ in a.bars)
    assert all(b_.volume > 0 for b_ in a.bars)


def test_csv_round_trip_reproduces_the_series(tmp_path):
    s = MK.synthetic_series("ACME", seed=3)
    path = MK.write_csv(s, tmp_path / "ACME.csv")
    back = MK.load_csv(path)
    assert back.symbol == "ACME"
    assert back.interval_s == s.interval_s
    assert len(back) == len(s)
    for x, y in zip(s.bars, back.bars):
        assert x.ts == y.ts
        assert math.isclose(x.close, y.close, rel_tol=0, abs_tol=1e-6)


def test_csv_rejects_a_missing_column_and_unordered_timestamps(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("timestamp,open,high,low,close\n2024-01-01T00:00:00Z,1,1,1,1\n")
    with pytest.raises(ValueError, match="missing columns"):
        MK.load_csv(p)
    p.write_text("timestamp,open,high,low,close,volume\n"
                 "2024-01-01T01:00:00Z,1,1,1,1,1\n"
                 "2024-01-01T00:00:00Z,1,1,1,1,1\n")
    with pytest.raises(ValueError, match="not strictly increasing"):
        MK.load_csv(p)


# --------------------------------------------------------- observations

def test_short_history_is_insufficient_not_flat():
    s = MK.synthetic_series("X", seed=1)
    feed = MK.ObservationFeed({"X": s})
    o = feed.observe("X", MK.MIN_HISTORY_BARS - 2)
    assert o.status is MK.ObservationStatus.INSUFFICIENT_HISTORY
    assert not o.status.usable
    ok = feed.observe("X", MK.MIN_HISTORY_BARS - 1)
    assert ok.status is MK.ObservationStatus.OK


def test_nan_bar_and_timestamp_gap_are_reported_as_gaps():
    s = MK.synthetic_series("X", seed=1)
    i = 120
    bars = list(s.bars)
    bars[i - 3] = MK.Bar(ts=bars[i - 3].ts, open=float("nan"), high=1.0,
                         low=1.0, close=float("nan"), volume=1.0)
    feed = MK.ObservationFeed({"X": MK.Series("X", tuple(bars), s.interval_s)})
    assert feed.observe("X", i).status is MK.ObservationStatus.GAP

    bars = list(s.bars)
    shift = 5 * s.interval_s
    bars[i - 2:] = [MK.Bar(b.ts + shift, b.open, b.high, b.low, b.close, b.volume)
                    for b in bars[i - 2:]]
    feed = MK.ObservationFeed({"X": MK.Series("X", tuple(bars), s.interval_s)})
    assert feed.observe("X", i).status is MK.ObservationStatus.GAP


def test_stale_cutoff_is_reported_against_the_callers_clock():
    s = MK.synthetic_series("X", seed=1)
    feed = MK.ObservationFeed({"X": s}, max_staleness_s=2 * s.interval_s)
    i = 150
    ts = feed.cutoff_ts("X", i)
    assert feed.observe("X", i, as_of_ts=ts).status is MK.ObservationStatus.OK
    o = feed.observe("X", i, as_of_ts=ts + 10 * s.interval_s)
    assert o.status is MK.ObservationStatus.STALE
    assert "tolerance" in o.detail


def test_normalisation_is_causal():
    """Changing bars strictly after the cutoff cannot move the observation."""
    s = MK.synthetic_series("X", seed=11)
    i = 200
    base = MK.ObservationFeed({"X": s}).observe("X", i)

    bars = list(s.bars)
    for j in range(i + 1, len(bars)):
        b = bars[j]
        bars[j] = MK.Bar(b.ts, b.open * 3, b.high * 3, b.low * 3,
                         b.close * 3, b.volume * 7)
    tampered = MK.ObservationFeed(
        {"X": MK.Series("X", tuple(bars), s.interval_s)}).observe("X", i)

    assert np.array_equal(base.raw, tampered.raw)
    assert np.array_equal(base.normalized, tampered.normalized)


def test_observation_feed_exposes_no_forward_accessor():
    feed = MK.ObservationFeed({"X": MK.synthetic_series("X", seed=1)})
    public = {n for n in dir(feed) if not n.startswith("_")}
    assert public == {"series", "max_staleness_s", "symbols", "bars",
                      "cutoff_ts", "observe", "version"}


def test_normalized_features_are_bounded():
    series = {f"S{i}": MK.synthetic_series(f"S{i}", seed=40 + i) for i in range(3)}
    feed = MK.ObservationFeed(series)
    n = 0
    for sym, s in series.items():
        for i in range(MK.MIN_HISTORY_BARS - 1, len(s)):
            o = feed.observe(sym, i)
            assert o.status.usable
            assert np.all(np.abs(o.normalized) < 1.0)
            assert np.all(np.isfinite(o.raw))
            n += 1
    assert n > 500


# -------------------------------------------------------------- universe

def test_stable_ids_survive_renaming_and_ignore_spelling():
    u = MK.Universe(["AAA", "BBB", "CCC"])
    ids = dict(u.items())
    u.rename("BBB", "ZZZZZ")
    assert u.stable_id("ZZZZZ") == ids["BBB"]
    assert u.stable_id("AAA") == ids["AAA"]
    with pytest.raises(ValueError):
        u.rename("AAA", "CCC")


# --------------------------------------------------------------- encoder

@requires_real_graph
def test_channel_selection_matches_the_documented_rule(ann):
    enc = E.MarketToSensoryEncoder(ann)
    og, ug = P.orn_glomeruli(ann), P.upn_glomeruli(ann)
    from flytrade import sensory as S
    pool = [g for g in S.candidate_glomeruli(ann) if len(ug[g]) >= E.MIN_UPNS]
    ranked = sorted(pool, key=lambda g: (-len(og[g]), g))[:10]
    assert list(enc.glomeruli) == ranked
    assert enc.glomeruli == ("VL2a", "VM5d", "DL1", "VL1", "VM4",
                             "DM3", "DM6", "V", "DM2", "DA2")
    assert enc.n_orns == 703
    assert len(set(enc.glomeruli)) == 10


@requires_real_graph
def test_encoder_is_deterministic_and_bounded(ann):
    enc = E.MarketToSensoryEncoder(ann)
    rng = np.random.default_rng(0)
    for _ in range(50):
        u = rng.uniform(-1, 1, len(MK.FEATURES))
        a = enc.encode_features(u)
        b = enc.encode_features(u)
        assert a.rates == b.rates
        assert all(0.0 <= hz <= enc.drive_max_hz for hz in a.rates.values())
        assert math.isclose(a.total_drive_hz, enc.drive_budget_hz, rel_tol=1e-9)


@requires_real_graph
def test_encoder_drives_only_orns_of_the_declared_channels(ann):
    enc = E.MarketToSensoryEncoder(ann)
    stim = enc.encode_features((0.3, -0.4, 0.5, -0.6, 0.7))
    driven = np.concatenate([np.asarray(k, dtype=np.int64)
                             for k in stim.drive])
    assert len(driven) == len(set(int(i) for i in driven)) == enc.n_orns

    is_orn = P.orns(ann)
    assert is_orn[driven].all()
    for forbidden in (P.kenyon_cells(ann), P.mbons(ann), P.pam(ann),
                      P.ppl1(ann), P.upns(ann)):
        assert not forbidden[driven].any()

    og = P.orn_glomeruli(ann)
    allowed = set(int(i) for g in enc.glomeruli for i in og[g])
    assert set(int(i) for i in driven) == allowed


@requires_real_graph
def test_rectified_opponent_signs_go_the_right_way(ann):
    enc = E.MarketToSensoryEncoder(ann)
    up = enc.rates((+1.0, 0, 0, 0, 0))
    down = enc.rates((-1.0, 0, 0, 0, 0))
    c = enc.channels[0]
    assert up[c.positive] > up[c.negative]
    assert down[c.negative] > down[c.positive]
    assert math.isclose(up[c.negative] / up[c.positive], enc.carrier, rel_tol=1e-9)


@requires_real_graph
def test_unusable_observation_is_refused_not_encoded_as_flat(ann):
    enc = E.MarketToSensoryEncoder(ann)
    s = MK.synthetic_series("X", seed=1)
    feed = MK.ObservationFeed({"X": s})
    bad = feed.observe("X", 3)
    assert not bad.status.usable
    with pytest.raises(ValueError, match="INSUFFICIENT_HISTORY"):
        enc.encode(bad)


@requires_real_graph
def test_declared_operating_range_is_what_the_code_uses(ann):
    """docs/ENCODER.md §4 declares budget 12,000 Hz and carrier 0.10."""
    enc = E.MarketToSensoryEncoder(ann)
    assert enc.drive_budget_hz == 12000.0
    assert enc.carrier == 0.10
    assert enc.coding == "normalized"
    assert E.GLOBAL_GAIN == 0.10          # D2, frozen
    assert enc.drive_max_hz <= 150.0      # Fable addendum 1
    assert E.STEPS == 100                 # 20 ms, PROTOCOL.md §2


@requires_real_graph
def test_nominal_patterns_are_neither_silent_nor_saturated(brain, ann):
    """The three PROTOCOL.md §2 criteria, at the declared range, 8 seeds."""
    fb, mb, gains = brain
    enc = E.MarketToSensoryEncoder(ann)
    patterns = {
        "strong_up": (+0.80, +0.90, +0.90, +0.20, +0.50),
        "strong_down": (-0.80, -0.90, -0.90, +0.60, +0.70),
        "flat_low_vol": (0.0, 0.0, 0.0, -0.80, -0.60),
        "flat_high_vol": (0.0, 0.0, 0.0, +0.80, +0.60),
    }
    ceiling = 1000.0 / fb.p.refractory
    kc_sets, fractions = {}, []
    for name, u in patterns.items():
        stim = enc.encode_features(u, symbol=name)
        sets = []
        for s in range(1, 9):
            r = fb.run(stim.drive, steps=E.STEPS, gains=gains,
                       record={"kc": mb.kc, "mbon": mb.mbon}, seed=1000 + s)
            assert r["mbon"].sum() > 0, f"{name}/seed {s}: silent MBON readout"
            assert r["mbon"].max() < 0.95 * ceiling, f"{name}/seed {s}: saturated"
            sets.append(set(int(i) for i in mb.kc[r["kc"] > 0]))
            fractions.append(float((r["kc"] > 0).mean()))
        kc_sets[name] = sets
    assert float(np.mean(fractions)) < 0.25
    assert max(fractions) < 0.25

    names = list(patterns)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            j = float(np.mean([len(x & y) / len(x | y)
                               for x, y in zip(kc_sets[a], kc_sets[b])]))
            assert j < 0.40, f"{a} vs {b}: Kenyon-cell Jaccard {j:.3f}"
