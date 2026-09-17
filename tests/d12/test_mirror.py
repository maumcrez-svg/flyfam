"""The mirror diagnostic's primitives, on toy data with known answers.

Addendum 13 names the one that matters: *an exact negative gives τ = −1 and
b = −1*. Kendall's τ-b is implemented rather than imported, so it is checked
against a brute-force O(n²) count on tied data as well.
"""

from __future__ import annotations

import itertools
import math
import random

import pytest

import mirror as MIR
import stats as ST


def brute_tau_b(x, y):
    n = len(x)
    con = dis = 0
    for i, j in itertools.combinations(range(n), 2):
        s = (x[i] - x[j]) * (y[i] - y[j])
        if s > 0:
            con += 1
        elif s < 0:
            dis += 1
    tx = sum(1 for i, j in itertools.combinations(range(n), 2) if x[i] == x[j])
    ty = sum(1 for i, j in itertools.combinations(range(n), 2) if y[i] == y[j])
    total = n * (n - 1) // 2
    return (con - dis) / math.sqrt((total - tx) * (total - ty))


# ------------------------------------------------------- the known answer
def test_an_exact_negative_gives_tau_minus_one_and_slope_minus_one():
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    y = [-v for v in x]
    assert MIR.kendall_tau_b(x, y) == -1.0
    fit = MIR.ols(x, y)
    assert fit["b"] == -1.0
    assert fit["r2"] == 1.0
    assert MIR.reversed_pair_fraction(x, y)["fraction"] == 1.0
    assert ST.spearman(x, y) == pytest.approx(-1.0)
    assert MIR.pearson(x, y) == pytest.approx(-1.0)


def test_an_exact_negative_with_an_offset_still_gives_tau_minus_one():
    """A shifted mirror is still a mirror: τ is rank-based, a absorbs the shift."""
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    y = [7.5 - v for v in x]
    assert MIR.kendall_tau_b(x, y) == -1.0
    fit = MIR.ols(x, y)
    assert fit["b"] == pytest.approx(-1.0)
    assert fit["a"] == pytest.approx(7.5)


def test_an_identity_gives_tau_plus_one_and_no_reversed_pair():
    x = [1.0, 2.0, 3.0, 4.0]
    assert MIR.kendall_tau_b(x, x) == 1.0
    assert MIR.reversed_pair_fraction(x, x)["fraction"] == 0.0
    assert MIR.ols(x, x)["b"] == 1.0


def test_a_constant_side_has_no_tau_and_no_slope():
    assert MIR.kendall_tau_b([1.0, 2.0, 3.0], [5.0, 5.0, 5.0]) is None
    assert MIR.ols([5.0, 5.0, 5.0], [1.0, 2.0, 3.0])["b"] is None


# -------------------------------------------------------- against brute force
@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_kendall_tau_b_matches_a_brute_force_count_with_ties(seed):
    rng = random.Random(seed)
    x = [rng.choice([1.0, 2.0, 3.0]) for _ in range(40)]
    y = [rng.choice([1.0, 2.0, 3.0, 4.0]) for _ in range(40)]
    assert MIR.kendall_tau_b(x, y) == pytest.approx(brute_tau_b(x, y), abs=1e-12)


def test_tau_does_not_depend_on_the_order_of_the_rows():
    rng = random.Random(11)
    x = [rng.random() for _ in range(30)]
    y = [rng.random() for _ in range(30)]
    pairs = list(zip(x, y))
    rng.shuffle(pairs)
    assert MIR.kendall_tau_b(x, y) == pytest.approx(
        MIR.kendall_tau_b([a for a, _ in pairs], [b for _, b in pairs]),
        abs=1e-12)


# ------------------------------------------------------------------- AUC
def test_the_auc_of_the_negated_score_is_one_minus_the_auc():
    """Why AUC(-reference) belongs beside AUC(trained) in the mirror table."""
    scores = [0.1, 0.9, 0.4, 0.7, 0.2]
    y = [False, True, False, True, False]
    a = ST.auc(scores, y)
    b = ST.auc([-v for v in scores], y)
    assert a + b == pytest.approx(1.0)


def test_the_registered_mirror_quantities_are_all_produced():
    payload_keys = {"pearson_r", "spearman_rho", "kendall_tau",
                    "ols_trained_on_reference", "reversed_pairs"}
    rows = [{"trained": float(i), "reference": float(-i), "tick": 1,
             "block": 1, "settled": False, "y": None} for i in range(5)]
    assert set(MIR.describe(rows)) >= payload_keys


def test_the_inversion_counter_is_exact_on_a_known_permutation():
    assert MIR._inversions([1, 2, 3]) == 0
    assert MIR._inversions([3, 2, 1]) == 3
    assert MIR._inversions([2, 1, 3]) == 1
    assert MIR._inversions([1, 1, 1]) == 0
