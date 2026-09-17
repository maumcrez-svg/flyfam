"""D11-001 addendum 9 — the AUC and the cluster bootstrap, on known answers.

Written and run **before** the frozen comparison is computed. The four the
addendum names — AUC 1, 0 and a half on perfect, reversed and constant data;
ties; identical branches giving exactly zero; a one-cluster bootstrap being
degenerate — plus the wording rule, which is asserted as text because it is the
rule the owner set and a caller must not be able to say anything else.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments" / "d11"))

import stats as ST                                       # noqa: E402


# ------------------------------------------------------------------- AUC
def test_a_perfect_ranking_is_one():
    assert ST.auc([3.0, 2.0, 1.0, 0.0], [True, True, False, False]) == 1.0


def test_a_reversed_ranking_is_zero():
    assert ST.auc([0.0, 1.0, 2.0, 3.0], [True, True, False, False]) == 0.0


def test_a_constant_score_is_one_half():
    assert ST.auc([1.0] * 6, [True, True, True, False, False, False]) == 0.5


def test_ties_count_a_half():
    # one positive and one negative tied, one positive clearly above
    got = ST.auc([2.0, 1.0, 1.0], [True, True, False])
    assert got == pytest.approx(0.75)


def test_an_empty_class_has_no_auc_rather_than_one_half():
    assert ST.auc([1.0, 2.0], [True, True]) is None
    assert ST.auc([1.0, 2.0], [False, False]) is None


def test_the_auc_does_not_depend_on_the_order_of_the_rows():
    rng = np.random.default_rng(7)
    s = rng.normal(size=200)
    y = rng.random(200) < 0.4
    order = rng.permutation(200)
    assert ST.auc(s, y) == pytest.approx(ST.auc(s[order], y[order]))


def test_the_auc_is_invariant_under_a_monotone_rescaling():
    rng = np.random.default_rng(11)
    s = rng.normal(size=150)
    y = rng.random(150) < 0.5
    assert ST.auc(s, y) == pytest.approx(ST.auc(3.0 * s + 100.0, y))


# --------------------------------------------------------------- delta AUC
def _rows(n, rng, *, same=False):
    out = []
    for i in range(n):
        a = float(rng.normal())
        out.append({"a": a, "b": a if same else float(rng.normal()),
                    "y": bool(rng.random() < 0.5)})
    return out


def test_identical_branches_give_exactly_zero():
    rng = np.random.default_rng(3)
    rows = _rows(400, rng, same=True)
    stat = ST.delta_auc_statistic("a", "b", "y")
    assert stat(rows) == 0.0


def test_identical_branches_give_an_interval_that_is_exactly_zero_wide():
    rng = np.random.default_rng(5)
    clusters = [_rows(10, rng, same=True) for _ in range(20)]
    out = ST.cluster_bootstrap(clusters, ST.delta_auc_statistic("a", "b", "y"),
                               resamples=200, seed=ST.SEED)
    assert out["point"] == 0.0
    assert out["lo"] == 0.0 and out["hi"] == 0.0
    assert out["degenerate"] is True


# --------------------------------------------------------------- bootstrap
def test_one_cluster_is_degenerate():
    rng = np.random.default_rng(9)
    out = ST.cluster_bootstrap([_rows(30, rng)],
                               ST.delta_auc_statistic("a", "b", "y"),
                               resamples=200, seed=ST.SEED)
    assert out["clusters"] == 1
    assert out["degenerate"] is True
    # every resample draws the same single cluster, so the interval is a point
    assert out["lo"] == out["hi"] == out["point"]


def test_the_bootstrap_is_reproducible_under_its_seed():
    rng = np.random.default_rng(13)
    clusters = [_rows(8, rng) for _ in range(25)]
    stat = ST.delta_auc_statistic("a", "b", "y")
    first = ST.cluster_bootstrap(clusters, stat, resamples=500, seed=20260913)
    second = ST.cluster_bootstrap(clusters, stat, resamples=500, seed=20260913)
    assert first == second
    other = ST.cluster_bootstrap(clusters, stat, resamples=500, seed=1)
    assert (other["lo"], other["hi"]) != (first["lo"], first["hi"])


def test_the_bootstrap_resamples_whole_clusters_and_not_rows():
    """A cluster is all-or-nothing: its rows never split across a resample."""
    seen: list[int] = []

    def statistic(rows):
        seen.append(len(rows))
        return 0.0

    clusters = [[{"i": i}] * 7 for i in range(5)]
    ST.cluster_bootstrap(clusters, statistic, resamples=50, seed=1)
    # every resample has exactly 5 clusters of 7 rows
    assert set(seen[1:]) == {35}


def test_a_resample_without_the_statistic_is_dropped_and_counted():
    rng = np.random.default_rng(17)
    # one positive cluster and one negative cluster: many resamples draw only
    # one class and have no AUC at all
    clusters = [[{"a": 1.0, "b": 0.0, "y": True}] * 4,
                [{"a": 0.0, "b": 1.0, "y": False}] * 4]
    out = ST.cluster_bootstrap(clusters, ST.delta_auc_statistic("a", "b", "y"),
                               resamples=400, seed=ST.SEED)
    assert out["kept"] < out["resamples"]
    assert out["kept"] > 0


def test_the_registered_constants_are_what_the_plan_says():
    assert (ST.RESAMPLES, ST.SEED, ST.LEVEL) == (10_000, 20_260_913, 0.95)


# ----------------------------------------------------------- the wording
def test_an_interval_including_zero_is_compatible_with_sampling_variation():
    text = ST.describe_interval({"point": 0.004, "lo": -0.02, "hi": 0.03,
                                 "clusters": 9, "kept": 10_000})
    assert "compatible with sampling variation" in text
    assert "significant" not in text.lower()
    assert "prove" not in text.lower()


def test_an_interval_excluding_zero_is_reported_with_its_bounds():
    text = ST.describe_interval({"point": 0.08, "lo": 0.02, "hi": 0.14,
                                 "clusters": 9, "kept": 10_000})
    assert "excludes 0" in text
    assert "+0.0200" in text and "+0.1400" in text
    assert "significant" not in text.lower()
    assert "prove" not in text.lower()


def test_a_missing_interval_says_so_rather_than_inventing_one():
    text = ST.describe_interval({"point": None, "lo": None, "hi": None,
                                 "clusters": 0, "kept": 0})
    assert "could not be given an interval" in text


# --------------------------------------------------------------- spearman
def test_spearman_is_one_on_a_monotone_pair_and_minus_one_reversed():
    assert ST.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert ST.spearman([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)


def test_spearman_of_a_constant_does_not_exist():
    assert ST.spearman([1, 1, 1, 1], [1, 2, 3, 4]) is None


# ----------------------------------------------------------- suppression
def test_the_class_contrast_is_the_negative_class_change_minus_the_positive():
    rows = (
        [{"a": True, "b": True, "y": True}] * 10 +          # positive: no change
        [{"a": False, "b": True, "y": False}] * 10          # negative: -1.0
    )
    stat = ST.class_contrast_statistic("a", "b", "y")
    assert stat(rows) == pytest.approx(-1.0 - 0.0)


def test_the_class_contrast_needs_both_classes():
    rows = [{"a": True, "b": True, "y": True}] * 4
    assert ST.class_contrast_statistic("a", "b", "y")(rows) is None
