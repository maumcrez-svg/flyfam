"""
The four joint diagnostic models — PLAN §7, addendum 8, and §9's model tests.

scikit-learn is imported directly, with no ``importorskip``: a missing
``diagnostics`` extra must fail this suite loudly rather than skip it.

The XOR fixture at the end is the reason this file exists at all. Its purpose is
**not** to require any diagnostic model to solve every possible interaction; it
is to prevent the reporting layer from ever asserting that marginal chance
performance proves absent information.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

import models as MO                                  # experiments/d8
from flytrade import metrics as MET

ROOT = Path(__file__).resolve().parents[2]
D8 = ROOT / "experiments" / "d8"
CONFIG = json.loads((D8 / "config.json").read_text())
MODELS = json.loads((D8 / "models.json").read_text())

RNG = np.random.default_rng(20260911)


def xor_fixture(n: int = 2000):
    """Two balanced binary inputs whose XOR is the label.

    Each input alone is exactly uninformative — AUC 0.5, by construction and not
    by luck — while the joint oracle ``a != b`` ranks perfectly.
    """
    a = np.tile([0, 0, 1, 1], n // 4).astype(float)
    b = np.tile([0, 1, 0, 1], n // 4).astype(float)
    y = (a != b).astype(int)
    X = np.column_stack([a, b])
    oracle = (a != b).astype(float)
    return X, y, oracle


# ----------------------------------------------------------- the fixture

def test_each_xor_input_alone_is_exactly_chance():
    X, y, _ = xor_fixture()
    for j in range(2):
        assert MET.roc_auc(X[:, j], y) == 0.5
        assert MET.roc_auc_pairwise(X[:, j], y) == 0.5


def test_the_joint_xor_oracle_is_exactly_one():
    X, y, oracle = xor_fixture()
    assert MET.roc_auc(oracle, y) == 1.0


def test_pc1_of_the_xor_inputs_is_also_chance():
    """§2's third boundary, on data whose joint structure is perfect."""
    import orient as OR
    X, y, _ = xor_fixture()
    pca = OR.fit_pc1(X)
    assert not pca["degenerate"]
    assert MET.roc_auc(OR.pc1_scores(pca, X), y) == 0.5


def test_marginal_chance_therefore_does_not_prove_absent_information():
    """The whole point, stated as one assertion over the same arrays."""
    X, y, oracle = xor_fixture()
    marginals = [MET.roc_auc(X[:, j], y) for j in range(2)]
    assert marginals == [0.5, 0.5]
    assert MET.roc_auc(oracle, y) == 1.0


# ----------------------------------------------------------- determinism

def test_two_consecutive_linear_fits_give_identical_scores():
    X, y, _ = xor_fixture()
    X = X + RNG.normal(0, 0.1, X.shape)
    s1, _ = MO.fit_linear(X, y)
    s2, _ = MO.fit_linear(X, y)
    assert np.array_equal(s1(X), s2(X))


def test_two_consecutive_nonlinear_fits_give_identical_scores():
    X, y, _ = xor_fixture()
    X = X + RNG.normal(0, 0.1, X.shape)
    s1, _ = MO.fit_nonlinear(X, y)
    s2, _ = MO.fit_nonlinear(X, y)
    assert np.array_equal(s1(X), s2(X))


def test_omp_num_threads_is_pinned_by_importing_the_module():
    assert os.environ["OMP_NUM_THREADS"] == "1"
    assert MODELS["omp_num_threads"] == "1"


# ------------------------------------------- fitting sees no evaluation row

def test_the_scaler_is_fitted_on_the_fitting_rows_only():
    Xf = RNG.normal(3.0, 2.0, size=(500, 4))
    Xe = RNG.normal(-9.0, 7.0, size=(300, 4))
    y = (Xf[:, 0] > 3.0).astype(int)
    _, info = MO.fit_linear(Xf, y)
    assert np.allclose(info["scaler_mean_"], Xf.mean(axis=0))
    assert np.allclose(info["scaler_scale_"], Xf.std(axis=0))
    # the evaluation partition existed and changed nothing
    assert not np.allclose(info["scaler_mean_"], Xe.mean(axis=0))


def test_changing_every_evaluation_label_cannot_change_a_fitted_model():
    Xf = RNG.normal(size=(600, 4))
    yf = (Xf[:, 0] + Xf[:, 1] > 0).astype(int)
    Xe = RNG.normal(size=(400, 4))
    ye = (Xe[:, 2] > 0).astype(int)
    for fitter in (MO.fit_linear, MO.fit_nonlinear):
        score, info = fitter(Xf, yf)
        before = score(Xe)
        ye = 1 - ye                       # every evaluation label inverted
        score2, info2 = fitter(Xf, yf)
        assert np.array_equal(before, score2(Xe))
        assert info["classes_"] == info2["classes_"]
    assert set(np.unique(ye)) <= {0, 1}


def test_changing_evaluation_labels_cannot_change_an_already_generated_score():
    Xf = RNG.normal(size=(400, 3))
    yf = (Xf[:, 0] > 0).astype(int)
    Xe = RNG.normal(size=(200, 3))
    score, _ = MO.fit_linear(Xf, yf)
    s = score(Xe).copy()
    y_a = (Xe[:, 0] > 0).astype(int)
    y_b = 1 - y_a
    assert np.array_equal(s, score(Xe))
    # the AUC moves because the labels moved; the scores did not
    assert MET.roc_auc(s, y_a) is not None
    assert abs(MET.roc_auc(s, y_b) - (1.0 - MET.roc_auc(s, y_a))) < 1e-12


# ------------------------------------------ the parameters, exactly as §6

def test_the_two_families_carry_exactly_the_registered_parameters():
    lin = CONFIG["models"]["families"]["LINEAR"]
    non = CONFIG["models"]["families"]["NONLINEAR"]
    assert (lin["C"], lin["solver"], lin["max_iter"]) == (1.0, "lbfgs", 2000)
    assert lin["class_weight"] is None
    assert non["learning_rate"] == 0.1 and non["max_iter"] == 100
    assert non["max_depth"] == 3 and non["max_leaf_nodes"] == 8
    assert non["min_samples_leaf"] == 20 and non["l2_regularization"] == 1.0
    assert non["early_stopping"] is False and non["random_state"] == 8
    assert non["class_weight"] is None


def test_the_l2_default_is_the_deprecated_explicit_l2_bit_for_bit():
    """sklearn 1.9 deprecated ``penalty="l2"``; the default is pure L2.

    The plan says L2-regularised, so the estimator is built with the default
    rather than with a deprecated argument whose FutureWarning would then have
    to be swallowed. This asserts the two spellings fit identically.
    """
    import warnings as W
    X = RNG.normal(size=(500, 4))
    y = (X[:, 0] + 0.5 * X[:, 1] > 0).astype(int)
    Z = StandardScaler().fit_transform(X)
    default = LogisticRegression(C=1.0, solver="lbfgs", max_iter=2000).fit(Z, y)
    assert default.get_params()["l1_ratio"] == 0.0
    with W.catch_warnings(record=True) as caught:
        W.simplefilter("always")
        assert caught == []
    with W.catch_warnings():
        W.simplefilter("ignore", FutureWarning)
        old = LogisticRegression(C=1.0, solver="lbfgs", max_iter=2000,
                                 penalty="l2").fit(Z, y)
    assert np.array_equal(default.coef_, old.coef_)
    assert np.array_equal(default.intercept_, old.intercept_)


def test_the_estimators_actually_constructed_carry_those_parameters():
    X, y, _ = xor_fixture(400)
    ref_lin = LogisticRegression(C=1.0, solver="lbfgs", max_iter=2000).fit(
        StandardScaler().fit_transform(X), y)
    ref_non = HistGradientBoostingClassifier(
        learning_rate=0.1, max_iter=100, max_depth=3, max_leaf_nodes=8,
        min_samples_leaf=20, l2_regularization=1.0, early_stopping=False,
        random_state=8).fit(X, y)
    s_lin, _ = MO.fit_linear(X, y)
    s_non, _ = MO.fit_nonlinear(X, y)
    assert np.array_equal(
        s_lin(X), ref_lin.predict_proba(StandardScaler().fit(X).transform(X))[:, 1])
    assert np.array_equal(s_non(X), ref_non.predict_proba(X)[:, 1])


def test_max_iter_was_never_raised_and_nothing_was_silently_replaced():
    for m in MODELS["models"]:
        if m["family"] != "LINEAR":
            continue
        assert m["fit"]["max_iter"] == 2000
        assert m["fit"]["converged"] is True
        assert m["fit"]["convergence_warnings"] == []
        assert m["fit"]["other_warnings"] == []
        assert m["fit"]["penalty"] == "L2" and m["fit"]["l1_ratio"] == 0.0
        assert all(n <= 2000 for n in m["fit"]["n_iter_"])
    for m in MODELS["models"]:
        if m["family"] == "NONLINEAR":
            assert m["fit"]["warnings"] == []
            assert m["fit"]["early_stopping"] is False
            assert m["fit"]["n_iter_"] == 100


# ------------------------------------------------ the committed artifact

def test_there_are_exactly_four_fits_and_one_is_named_primary():
    names = [m["name"] for m in MODELS["models"]]
    assert len(names) == 4 and len(set(names)) == 4
    primary = [m["name"] for m in MODELS["models"] if m["primary"]]
    assert primary == ["NONLINEAR on X_SENSORY"]
    assert MODELS["primary"] == "NONLINEAR on X_SENSORY"
    assert CONFIG["models"]["primary"] == "NONLINEAR on X_SENSORY"


def test_every_model_reports_its_counts_sessions_coverage_and_exclusions():
    for m in MODELS["models"]:
        assert m["fitting"]["rows"] == 2789 and m["fitting"]["sessions"] == 10
        assert m["evaluation"]["rows"] == 2790 and m["evaluation"]["sessions"] == 10
        assert m["evaluation"]["coverage"] == 1.0
        assert m["evaluation"]["exclusions"] == ["2026-07-22"]
        assert m["evaluation"]["qualifying_sessions"] == 9
        assert len(m["per_session_auc"]) == 10
        assert m["bootstrap"]["draws"] == 2000
        assert m["bootstrap"]["n_sessions"] == 9


def test_the_paired_comparisons_use_the_same_rows_and_sessions():
    for m in MODELS["models"]:
        for fly in ("REFERENCE", "TRAINED"):
            p = m["paired_vs_fly"][fly]
            assert p["paired_rows"] == 2790
            assert p["paired_sessions"] == 9
            assert len(p["per_session_delta"]) == 9
            assert p["bootstrap"]["n_sessions"] == 9
            assert p["bootstrap"]["seed"] == CONFIG["bootstrap"]["paired"]["seed"]


def test_the_fly_levels_reproduce_the_d7_result_on_the_same_rows():
    """A consistency check: D7 reported 0.4904 trained and 0.4934 reference."""
    assert abs(MODELS["fly"]["TRAINED"]["mean_auc"] - 0.4904) < 5e-5
    assert abs(MODELS["fly"]["REFERENCE"]["mean_auc"] - 0.4934) < 5e-5


def test_no_matched_participation_table_was_produced():
    assert MODELS["matched_participation"].startswith("not computed")
    assert "matched_participation" not in json.dumps(
        [m["evaluation"] for m in MODELS["models"]])


def test_the_results_are_not_attributed_to_the_fly():
    assert "never" in MODELS["not_biological"]
    for m in MODELS["models"]:
        assert m["family"] in ("LINEAR", "NONLINEAR")
        assert "fly" not in m["name"].lower()
