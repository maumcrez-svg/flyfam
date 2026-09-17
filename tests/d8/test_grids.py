"""
The two grids, and the causal reconstruction — PLAN §3 and §5, addenda 2 and 3.

Two different things are checked here.

**The property, on a generated fixture.** An observation at minute ``m`` may not
depend on any bar after ``m``. ``make_fixtures.py`` writes two vendor-shaped
files that are identical up to a cut minute and differ at every later bar, so
this is a comparison of two real series rather than a promise about call order.

**The recorded outcome, on the real grids.** ``experiments/d8/grids.py`` ran the
same comparison over every row of both grids and wrote the counts to
``grids.json``. The rule `PLAN.md` §5 fixed before the numbers existed is that a
non-zero mismatch count stops the wave, so the committed artifact must record
zero, and the tests below fail if it ever records anything else.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np

from tests.d8 import make_fixtures as MF
from tests.d8.conftest import requires_real_graph

ROOT = Path(__file__).resolve().parents[2]
D8 = ROOT / "experiments" / "d8"
CONFIG = json.loads((D8 / "config.json").read_text())
GRIDS = json.loads((D8 / "grids.json").read_text())

CUT_DAY, CUT_MINUTE = MF.CUT


# ------------------------------------------- the property, on a fixture

def test_an_observation_cannot_see_a_bar_after_its_own_minute(
        clean, future_changed):
    """Every minute at or before the cut observes identically in both series."""
    day = MF.DAYS[CUT_DAY]
    compared = 0
    for m in range(CUT_MINUTE + 1):
        a = clean.observe(day, m, stable_id=0, bar_index=m)
        b = future_changed.observe(day, m, stable_id=0, bar_index=m)
        assert a.status is b.status, (day, m)
        if a.status.value != "OK":
            continue
        assert np.array_equal(a.raw, b.raw), (day, m)
        assert np.array_equal(a.normalized, b.normalized), (day, m)
        assert a.cutoff_ts == b.cutoff_ts
        compared += 1
    assert compared > 100


def test_the_fixture_really_does_change_the_future(clean, future_changed):
    """Otherwise the test above would pass on two identical files."""
    day = MF.DAYS[CUT_DAY]
    later = [m for m in range(CUT_MINUTE + 1, MF.MINUTES)
             if clean.observe(day, m).status.value == "OK"]
    assert later
    differing = sum(
        1 for m in later
        if not np.array_equal(clean.observe(day, m).normalized,
                              future_changed.observe(day, m).normalized))
    assert differing > 0
    # and a whole later session moves too
    nxt = MF.DAYS[CUT_DAY + 1]
    assert not np.array_equal(clean.observe(nxt, 200).raw,
                              future_changed.observe(nxt, 200).raw)


def test_the_cutoff_timestamp_is_bar_end_never_bar_start(clean):
    from flytrade import historical as H
    day = MF.DAYS[CUT_DAY]
    for m in (100, 200, 300):
        obs = clean.observe(day, m)
        bar = clean.bar(day, m)
        assert obs.cutoff_ts == bar.ts + H.BAR_SECONDS


@requires_real_graph
def test_the_encoded_stimulus_is_causal_too(clean, future_changed, ann):
    """The deterministic rate vector inherits the observation's causality."""
    from flytrade import encoder as E
    enc = E.MarketToSensoryEncoder(ann)
    day = MF.DAYS[CUT_DAY]
    compared = 0
    for m in range(100, CUT_MINUTE + 1):
        a, b = clean.observe(day, m), future_changed.observe(day, m)
        if a.status.value != "OK":
            continue
        ra, rb = enc.encode(a).rates, enc.encode(b).rates
        assert ra == rb, (day, m)
        compared += 1
    assert compared > 50


@requires_real_graph
def test_the_channel_order_the_plan_registered_is_the_encoder_s_own(ann):
    from flytrade import encoder as E
    enc = E.MarketToSensoryEncoder(ann)
    schema = CONFIG["representations"]
    assert list(enc.features) == schema["X_FEATURES"]["order"]
    assert list(enc.glomeruli) == schema["X_SENSORY"]["order"]
    assert {g: enc.orn_count[g] for g in enc.glomeruli} == \
        schema["X_SENSORY"]["orn_count"]
    for c in enc.channels:
        assert schema["X_SENSORY"]["channel_pairs"][c.feature] == \
            [c.positive, c.negative]


# --------------------------------------- the recorded outcome, real grids

def test_stored_and_reconstructed_agree_on_every_row_of_both_grids():
    for grid in ("fitting", "evaluation"):
        v = GRIDS["verification"][grid]
        assert v["tolerance"] == 1e-12
        assert v["X_FEATURES_mismatches"] == 0, grid
        assert v["X_SENSORY_mismatches"] == 0, grid
        assert v["X_FEATURES_max_abs_diff"] == 0.0, grid
        assert v["market_ts_equals_bar_end"] == v["n"], grid
    assert GRIDS["mismatches_total"] == 0


def test_the_stored_sensory_rounding_is_declared_and_bounded():
    """`Stimulus.as_dict` rounds to 4 decimals; that is the whole difference."""
    for grid in ("fitting", "evaluation"):
        v = GRIDS["verification"][grid]
        assert v["stored_rate_decimals"] == 4
        assert v["X_SENSORY_max_abs_diff_unrounded"] <= 0.5 * 10 ** -4


def test_no_fitting_label_resolves_after_evaluation_begins():
    o = GRIDS["temporal_order"]
    assert o["max_fitting_exit_ts"] < o["min_evaluation_market_ts"]
    assert o["strictly_before"] is True
    assert o["gap_seconds"] > 0


def test_the_two_grids_are_the_registered_partitions():
    f, e = GRIDS["fitting"], GRIDS["evaluation"]
    assert f["meta"]["partition"] == "LEARNING"
    assert (f["meta"]["first"], f["meta"]["last"]) == ("2026-07-06", "2026-07-17")
    assert e["meta"]["partition"] == "FROZEN"
    assert (e["meta"]["first"], e["meta"]["last"]) == ("2026-07-20", "2026-07-31")
    assert f["n_sessions"] == 10 and e["n_sessions"] == 10
    assert set(f["sessions"]).isdisjoint(e["sessions"])
    assert max(f["sessions"]) < min(e["sessions"])


def test_the_evaluation_grid_is_probes_json_as_stored():
    e = GRIDS["evaluation"]
    assert e["meta"]["probes_n"] == 2790
    assert e["n"] == 2790
    assert e["meta"]["exclusions"] == {"NO_DECISION_EVENT": 0, "NON_FINITE": 0}
    assert all(v["n"] == 279 for v in e["per_session"].values())


def test_the_fitting_grid_dropped_nothing_it_could_not_label():
    f = GRIDS["fitting"]
    assert f["n"] == f["meta"]["grid_points"]
    assert f["meta"]["exclusions"]["NO_DECISION_EVENT"] == 0
    assert f["meta"]["exclusions"]["NON_FINITE"] == 0


def test_the_stimulus_does_not_depend_on_the_branch():
    ident = GRIDS["evaluation"]["meta"]["frozen_trained_identical"]
    assert ident["compared"] == 2790
    assert ident["identical"] == 2790
    assert ident["differing"] == 0


def test_the_representations_have_the_registered_dimensions():
    for grid in ("fitting", "evaluation"):
        g = GRIDS[grid]
        assert g["X_FEATURES"]["dim"] == 5
        assert g["X_SENSORY"]["dim"] == 10
        assert g["X_FEATURES"]["finite_coverage"] == 1.0
        assert g["X_SENSORY"]["finite_coverage"] == 1.0
        assert g["X_FEATURES"]["constant_channels"] == []
        assert g["X_SENSORY"]["constant_channels"] == []


def test_there_is_one_row_per_minute_not_one_per_replicate():
    """k = 8 replicates share one stimulus; eight rows a minute would be a lie."""
    assert GRIDS["encoder"]["rows_per_minute"] == 1
    for grid in ("fitting", "evaluation"):
        g = GRIDS[grid]
        assert g["X_SENSORY"]["shape"] == [g["n"], 10]
        assert sum(v["n"] for v in g["per_session"].values()) == g["n"]


def test_the_encoder_delivers_no_sequence_and_the_plan_says_so():
    assert GRIDS["encoder"]["sequence"].startswith("none")
    assert CONFIG["representations"]["X_SENSORY"]["sequence"].startswith("none")
