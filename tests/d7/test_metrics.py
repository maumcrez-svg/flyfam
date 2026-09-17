"""
The ranking metrics — amendment §7's required tests, §8 and §9.

The point of every test in this file is the same one: **blanket inhibition may
not be counted as improved context ranking.** A brain that lowers every
response by the same amount, or scales them all down, buys less everywhere and
must earn exactly nothing here.
"""
from __future__ import annotations

import numpy as np
import pytest

from flytrade import metrics as MET

RNG = np.random.default_rng(20260911)


def random_case(n=200, p=0.4):
    y = (RNG.random(n) < p).astype(int)
    s = RNG.normal(y * 0.5, 1.0, n)
    return s, y


# ------------------------------------------------- the required §7 tests

def test_subtracting_a_constant_from_every_score_does_not_improve_auc():
    s, y = random_case()
    base = MET.roc_auc(s, y)
    for c in (0.1, 1.0, 5.0, 1e6):
        assert MET.roc_auc(s - c, y) == pytest.approx(base, abs=1e-12)


def test_positive_uniform_rescaling_does_not_improve_auc():
    s, y = random_case()
    base = MET.roc_auc(s, y)
    for k in (0.01, 0.5, 2.0, 1000.0):
        assert MET.roc_auc(s * k, y) == pytest.approx(base, abs=1e-12)


def test_an_affine_squash_towards_zero_does_not_improve_auc():
    """The shape "responds less, everywhere" in one transformation."""
    s, y = random_case()
    base = MET.roc_auc(s, y)
    assert MET.roc_auc(0.05 * s - 3.0, y) == pytest.approx(base, abs=1e-12)


def test_a_constant_score_is_exactly_one_half_when_both_classes_exist():
    y = np.array([1, 0, 1, 0, 1, 0])
    assert MET.roc_auc(np.zeros(6), y) == 0.5
    assert MET.roc_auc(np.full(6, 7.25), y) == 0.5


def test_a_one_class_session_has_an_undefined_auc_not_one_half():
    assert MET.roc_auc(np.arange(5.0), np.ones(5, dtype=int)) is None
    assert MET.roc_auc(np.arange(5.0), np.zeros(5, dtype=int)) is None


def test_perfect_and_reversed_rankings_behave_correctly():
    y = np.array([0, 0, 0, 1, 1, 1])
    perfect = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
    assert MET.roc_auc(perfect, y) == 1.0
    assert MET.roc_auc(-perfect, y) == 0.0


def test_ties_receive_half_credit_and_are_handled_explicitly():
    # one profitable and one nonprofitable probe at the same score
    assert MET.roc_auc(np.array([1.0, 1.0]), np.array([1, 0])) == 0.5
    # half the pairs tied, half correctly ordered
    s = np.array([1.0, 1.0, 0.0])
    y = np.array([1, 0, 0])
    assert MET.roc_auc(s, y) == pytest.approx(0.75)


def test_the_fast_auc_is_the_pairwise_definition_itself():
    for _ in range(25):
        n = int(RNG.integers(4, 120))
        y = (RNG.random(n) < RNG.uniform(0.2, 0.8)).astype(int)
        if y.sum() in (0, n):
            continue
        s = np.round(RNG.normal(0, 1, n), 1)        # deliberately tie-heavy
        assert MET.roc_auc(s, y) == pytest.approx(MET.roc_auc_pairwise(s, y))


def test_all_ties_give_one_half_through_both_implementations():
    y = np.array([1, 1, 0, 0, 0])
    s = np.full(5, 2.0)
    assert MET.roc_auc(s, y) == 0.5 == MET.roc_auc_pairwise(s, y)


# -------------------------------------------- session qualification, §7

def test_a_session_needs_ten_of_each_class_to_qualify():
    y = np.array([1] * 9 + [0] * 40)
    r = MET.session_result("s", RNG.normal(0, 1, 49), RNG.normal(0, 1, 49), y)
    assert not r.qualifies and "fewer than 10" in r.reason
    y = np.array([1] * 10 + [0] * 39)
    r = MET.session_result("s", RNG.normal(0, 1, 49), RNG.normal(0, 1, 49), y)
    assert r.qualifies


def test_both_branches_are_scored_on_the_same_paired_set():
    y = np.array([1] * 20 + [0] * 20)
    a, b = RNG.normal(0, 1, 40), RNG.normal(0, 1, 40)
    r = MET.session_result("s", a, b, y)
    assert r.n == 40 and r.n_pos == 20 and r.n_neg == 20
    assert r.delta == pytest.approx(MET.roc_auc(a, y) - MET.roc_auc(b, y))


def test_delta_auc_gives_every_qualifying_session_equal_weight():
    y_big = np.array([1] * 500 + [0] * 500)
    y_small = np.array([1] * 10 + [0] * 10)
    big = MET.SessionResult("big", 1000, 500, 500, 0.60, 0.50, True)
    small = MET.SessionResult("small", 20, 10, 10, 0.40, 0.50, True)
    assert MET.delta_auc([big, small]) == pytest.approx(0.0)
    assert len(y_big) != len(y_small)          # the weights ignore the sizes


def test_a_nonqualifying_session_enters_no_aggregate():
    ok = MET.SessionResult("a", 40, 20, 20, 0.7, 0.5, True)
    bad = MET.SessionResult("b", 40, 2, 38, 0.9, 0.1, False, "too few")
    assert MET.delta_auc([ok, bad]) == pytest.approx(0.2)


# ------------------------------------------------------ the bootstrap, §9

def test_the_bootstrap_resamples_whole_sessions_and_is_reproducible():
    res = [MET.SessionResult(f"s{i}", 40, 20, 20, 0.5 + 0.02 * i, 0.5, True)
           for i in range(8)]
    a = MET.paired_session_bootstrap(res, draws=2000, seed=12345)
    b = MET.paired_session_bootstrap(res, draws=2000, seed=12345)
    c = MET.paired_session_bootstrap(res, draws=2000, seed=999)
    assert a == b and a["mean"] != c["mean"]
    assert a["n_sessions"] == 8 and a["draws"] == 2000
    assert a["observed_delta_auc"] == pytest.approx(MET.delta_auc(res))
    assert a["p2.5"] < a["p50"] < a["p97.5"]


def test_the_bootstrap_says_so_when_no_session_qualifies():
    res = [MET.SessionResult("s", 4, 2, 2, 0.5, 0.5, False, "too few")]
    out = MET.paired_session_bootstrap(res, draws=10, seed=1)
    assert out["draws"] == 0 and out["n_sessions"] == 0


def test_a_declared_seed_is_a_string_not_a_lucky_integer():
    assert MET.declared_seed("flytrade-d7-bootstrap-1") == \
        MET.declared_seed("flytrade-d7-bootstrap-1")
    assert MET.declared_seed("a") != MET.declared_seed("b")


# ------------------------------------------- matched participation, §8

def test_the_top_slice_is_exactly_the_declared_fraction():
    s = RNG.normal(0, 1, 137)
    w = MET.top_fraction_weights(s, 0.2)
    assert w.sum() == pytest.approx(0.2 * 137)
    assert ((w >= 0) & (w <= 1)).all()


def test_both_branches_select_the_same_total_weight_however_they_score():
    a = RNG.normal(0, 1, 200)
    b = a - 5.0                       # "responds less, everywhere"
    wa, wb = MET.top_fraction_weights(a, 0.2), MET.top_fraction_weights(b, 0.2)
    assert wa.sum() == pytest.approx(wb.sum())
    assert (wa == wb).all()           # and a constant shift selects the same rows


def test_boundary_ties_are_weighted_fractionally_not_broken_by_order():
    s = np.array([3.0, 1.0, 1.0, 1.0, 1.0])        # 20% of 5 = 1.0 row
    w = MET.top_fraction_weights(s, 0.4)           # 2.0 rows: 3.0 plus one tie
    assert w[0] == 1.0
    assert w[1:] == pytest.approx(np.full(4, 0.25))
    assert w.sum() == pytest.approx(2.0)
    # the same scores in another order give the same weights, permuted
    perm = np.array([1.0, 1.0, 3.0, 1.0, 1.0])
    wp = MET.top_fraction_weights(perm, 0.4)
    assert wp[2] == 1.0 and wp[[0, 1, 3, 4]] == pytest.approx(np.full(4, 0.25))


def test_ties_are_never_broken_by_a_later_label_or_by_time():
    s = np.ones(10)
    w = MET.top_fraction_weights(s, 0.2)
    assert w == pytest.approx(np.full(10, 0.2))     # every tied probe equal


def test_matched_participation_reports_both_branches_on_the_same_labels():
    n = 100
    g = RNG.normal(0, 0.001, n)
    y = (g > 0).astype(int)
    trained = g + RNG.normal(0, 0.0005, n)          # informative
    reference = RNG.normal(0, 1, n)                 # noise
    out = MET.matched_participation(trained, reference, g, y, fraction=0.2)
    assert out["trained"]["selected_weight"] == \
        pytest.approx(out["reference"]["selected_weight"])
    assert out["trained"]["mean_G"] > out["reference"]["mean_G"]
    assert 0.0 <= out["trained"]["profitable_rate"] <= 1.0


def test_a_uniformly_lowered_score_wins_nothing_at_matched_participation():
    n = 100
    g = RNG.normal(0, 0.001, n)
    y = (g > 0).astype(int)
    s = RNG.normal(0, 1, n)
    out = MET.matched_participation(s - 10.0, s, g, y, fraction=0.2)
    assert out["difference"]["mean_G"] == pytest.approx(0.0, abs=1e-15)
    assert out["difference"]["profitable_rate"] == pytest.approx(0.0)


# ------------------------------------------------------ the verdict, §9

def _boot(frac):
    return {"fraction_of_draws_above_zero": frac}


def test_too_few_qualifying_sessions_is_inconclusive():
    res = [MET.SessionResult(f"s{i}", 40, 20, 20, 0.9, 0.5, True)
           for i in range(4)]
    v = MET.classify(res, _boot(1.0), {"paired_coverage": 1.0})
    assert v["conclusion"] == "C" and "qualifying sessions" in v["reason"]


def test_low_coverage_is_inconclusive_however_large_the_effect():
    res = [MET.SessionResult(f"s{i}", 40, 20, 20, 0.9, 0.5, True)
           for i in range(8)]
    v = MET.classify(res, _boot(1.0), {"paired_coverage": 0.80,
                                       "trained_coverage": 0.99})
    assert v["conclusion"] == "C" and "coverage" in v["reason"]


def test_a_positive_delta_below_chance_level_is_not_evidence():
    res = [MET.SessionResult(f"s{i}", 40, 20, 20, 0.49, 0.40, True)
           for i in range(8)]
    v = MET.classify(res, _boot(1.0), {"paired_coverage": 1.0})
    assert v["conclusion"] == "C" and "chance" in v["reason"]


def test_no_supported_improvement_is_suppression_not_inconclusive():
    res = [MET.SessionResult(f"s{i}", 40, 20, 20, 0.50, 0.52, True)
           for i in range(8)]
    v = MET.classify(res, _boot(0.10), {"paired_coverage": 1.0})
    assert v["conclusion"] == "B"


def test_evidence_needs_all_three_of_delta_level_and_uncertainty():
    res = [MET.SessionResult(f"s{i}", 40, 20, 20, 0.62, 0.50, True)
           for i in range(8)]
    v = MET.classify(res, _boot(0.99), {"paired_coverage": 1.0})
    assert v["conclusion"] == "A"
