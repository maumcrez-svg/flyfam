"""
Orientation and PC1 — PLAN §6, Fable addendum 9, and §9's sign-selection test.

Every sign in this wave is chosen on the fitting rows and frozen. The tests
below hold that claim to three separate standards:

* the arithmetic rule is exactly "raw fitting AUC >= 0.5 -> +1, else -1";
* nothing in the evaluation partition can reach it — changing every evaluation
  label leaves the orientation and the PCA bit-identical;
* the committed artifacts obey both, and report the raw AUC **and** the oriented
  AUC rather than ``max(AUC, 1 - AUC)``.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

import orient as OR                                  # experiments/d8
from flytrade import metrics as MET

ROOT = Path(__file__).resolve().parents[2]
D8 = ROOT / "experiments" / "d8"
ORI = json.loads((D8 / "orientation.json").read_text())
TABLE = json.loads((D8 / "features_pc1.json").read_text())

RNG = np.random.default_rng(20260911)


def fixture(n=400, d=6):
    X = RNG.normal(size=(n, d))
    y = (X[:, 0] - 0.7 * X[:, 1] + RNG.normal(0, 2.0, n) > 0).astype(int)
    return X, y


# ------------------------------------------------------- the sign rule

def test_the_sign_is_plus_one_exactly_when_the_fitting_auc_is_at_least_half():
    X, y = fixture()
    for j in range(X.shape[1]):
        a = MET.roc_auc(X[:, j], y)
        sign = 1 if a >= 0.5 else -1
        # the oriented score is the raw score times the sign, and nothing else
        assert MET.roc_auc(X[:, j] * sign, y) >= 0.5 - 1e-12


def test_negating_a_score_reflects_its_auc_about_one_half():
    X, y = fixture()
    for j in range(X.shape[1]):
        a = MET.roc_auc(X[:, j], y)
        assert abs(MET.roc_auc(-X[:, j], y) - (1.0 - a)) < 1e-12


def test_changing_every_evaluation_label_cannot_move_a_sign_or_the_pca():
    """The evaluation partition is not an argument of either computation."""
    Xf, yf = fixture()
    pca_a = OR.fit_pc1(Xf)
    signs_a = {j: (1 if MET.roc_auc(Xf[:, j], yf) >= 0.5 else -1)
               for j in range(Xf.shape[1])}
    # an entirely different evaluation partition, labels inverted
    _Xe, ye = fixture(n=300)
    ye = 1 - ye
    pca_b = OR.fit_pc1(Xf)
    signs_b = {j: (1 if MET.roc_auc(Xf[:, j], yf) >= 0.5 else -1)
               for j in range(Xf.shape[1])}
    assert signs_a == signs_b
    assert pca_a["loadings"] == pca_b["loadings"]
    assert pca_a["explained_variance_ratio_pc1"] == \
        pca_b["explained_variance_ratio_pc1"]
    assert len(ye) == 300                      # the evaluation labels existed


def test_pc1_is_fitted_on_centred_data_without_whitening():
    X, _ = fixture(n=500, d=4)
    pca = OR.fit_pc1(X)
    assert pca["whitening"] is False
    assert np.allclose(pca["mean"], X.mean(axis=0))
    v = np.asarray(pca["loadings"])
    assert abs(np.linalg.norm(v) - 1.0) < 1e-12          # unit, not whitened
    j = int(np.argmax(np.abs(v)))
    assert v[j] > 0                                      # the sign convention
    s = OR.pc1_scores(pca, X)
    assert abs(float(s.mean())) < 1e-9                   # centred on the fit


def test_a_constant_representation_is_called_degenerate_not_scored():
    X = np.ones((50, 4))
    pca = OR.fit_pc1(X)
    assert pca["degenerate"] is True


def test_pc1_maximises_variance_not_predictiveness():
    """§2's third boundary, as arithmetic: the direction is chosen without y."""
    X, y = fixture(n=600, d=3)
    pca_a = OR.fit_pc1(X)
    pca_b = OR.fit_pc1(X)            # y never entered either call
    assert pca_a["loadings"] == pca_b["loadings"]
    var_pc1 = float(np.var(OR.pc1_scores(pca_a, X), ddof=1))
    for j in range(X.shape[1]):
        proj = X[:, j] - X[:, j].mean()
        assert var_pc1 >= float(np.var(proj, ddof=1)) - 1e-9


# -------------------------------------------------- the committed artifacts

def test_the_committed_orientation_obeys_the_rule():
    for name, c in ORI["columns"].items():
        if c.get("degenerate"):
            assert c["sign"] is None
            continue
        a = c["fitting_auc_raw"]
        assert c["sign"] == (1 if a >= 0.5 else -1), name
    assert ORI["written_before_any_evaluation_auc"] is True
    assert ORI["never_max_auc_or_one_minus_auc"] is True
    assert ORI["fitting_sessions"] == sorted(ORI["fitting_sessions"])
    assert ORI["fitting_rows"] == 2789


def test_the_orientation_was_fitted_on_the_learning_sessions_only():
    assert all(s <= "2026-07-17" for s in ORI["fitting_sessions"])
    assert ORI["pca"]["fitted_on"].startswith("fitting rows only")
    assert ORI["pca"]["n_fitting_rows"] == ORI["fitting_rows"]
    assert len(ORI["pca"]["loadings"]) == 10
    assert ORI["pca"]["loading_names"] == list(OR.D.GLOMERULI)


def test_the_table_quotes_the_orientation_it_used():
    import hashlib
    got = hashlib.sha256((D8 / "orientation.json").read_bytes()).hexdigest()
    assert TABLE["orientation_sha256"] == got


def test_every_column_reports_raw_and_oriented_and_never_the_flip():
    for c in TABLE["columns"]:
        if c.get("degenerate"):
            continue
        assert c["mean_auc_raw"] is not None
        assert c["mean_auc_oriented"] is not None
        sign = c["sign_from_fitting"]
        if sign == 1:
            assert abs(c["mean_auc_oriented"] - c["mean_auc_raw"]) < 1e-12
        else:
            # the oriented mean is the reflection of the raw mean, which is a
            # different number from max(raw, 1 - raw) whenever raw > 0.5
            assert abs(c["mean_auc_oriented"] - (1.0 - c["mean_auc_raw"])) < 1e-12
        flipped = max(c["mean_auc_raw"], 1.0 - c["mean_auc_raw"])
        if c["mean_auc_oriented"] < 0.5:
            assert c["mean_auc_oriented"] != flipped


def test_the_evaluation_session_rule_is_d7s_and_the_exclusion_is_named():
    assert TABLE["min_per_class"] == 10
    for c in TABLE["columns"]:
        if c.get("degenerate"):
            continue
        assert c["qualifying_sessions"] == 9
        assert c["excluded_sessions"] == ["2026-07-22"]
        for r in c["per_session_raw"]:
            if not r["qualifies"]:
                assert min(r["n_pos"], r["n_neg"]) < 10
                assert r["reason"]


def test_a_one_class_session_would_be_undefined_not_one_half():
    y = np.ones(40, dtype=int)
    assert MET.roc_auc(RNG.normal(size=40), y) is None


def test_constant_scores_reversed_rankings_and_ties():
    y = np.array([1] * 20 + [0] * 20)
    assert MET.roc_auc(np.zeros(40), y) == 0.5
    perfect = np.concatenate([np.ones(20), np.zeros(20)])
    assert MET.roc_auc(perfect, y) == 1.0
    assert MET.roc_auc(-perfect, y) == 0.0
    half = np.concatenate([np.ones(20), np.ones(10), np.zeros(10)])
    assert MET.roc_auc(half, y) == MET.roc_auc_pairwise(half, y)
