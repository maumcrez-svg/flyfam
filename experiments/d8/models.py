#!/usr/bin/env python
"""
D8 stage 3 — the four joint diagnostic models.

    OMP_NUM_THREADS=1 .venv/bin/python experiments/d8/models.py

Exactly two families on exactly two representations, four fits, with exactly the
parameters `docs/SPEC.md` D8 §6 lists and `PLAN.md` §7 repeats. No tuning, no
extra family, no seed search, no model chosen on evaluation performance.

**The primary joint diagnostic is NONLINEAR on X_SENSORY**, named in the plan
before any number existed. The other three are secondary comparisons whatever
they show.

These are external measurement tools with supervised access to historical
labels. **They are not biological models and their results are never attributed
to the fly.** Nothing here can reach the decoder, an order, a reward, a plastic
weight or an observer decision.

Writes ``withheld d8 model table``: fitting and evaluation row counts, unique
sessions and class counts; per-session AUC; the equal-session mean; the
whole-session bootstrap of that mean; and the paired deltas against the
REFERENCE fly and against the TRAINED fly on identical rows and sessions.
"""
from __future__ import annotations

import json
import os
import sys
import time
import warnings
from pathlib import Path

# OpenMP must be pinned before scikit-learn initialises its thread pool:
# HistGradientBoosting reduces histograms across threads, and that reduction is
# the one thing that could make two identical fits differ (Fable addendum 8).
os.environ["OMP_NUM_THREADS"] = "1"

import numpy as np                                   # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier   # noqa: E402
from sklearn.exceptions import ConvergenceWarning    # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.preprocessing import StandardScaler     # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bootstrap as BS                               # noqa: E402
import data as D                                     # noqa: E402
from flytrade import metrics as MET                  # noqa: E402

OUT = HERE / "models.json"

LINEAR = D.CONFIG["models"]["families"]["LINEAR"]
NONLINEAR = D.CONFIG["models"]["families"]["NONLINEAR"]


def fit_linear(X_fit: np.ndarray, y_fit: np.ndarray):
    """StandardScaler fitted on the fitting rows only, then L2 logistic.

    The scaler never sees an evaluation row: it is fitted here, on ``X_fit``,
    and the same fitted object transforms the evaluation rows afterwards.
    """
    scaler = StandardScaler().fit(X_fit)
    # scikit-learn 1.9 deprecated the explicit ``penalty="l2"`` spelling in
    # favour of ``l1_ratio``; the constructor default is ``l1_ratio=0.0``,
    # which is pure L2 and fits bit-identically to the deprecated spelling
    # (``tests/d8/test_models.py`` asserts that equality). So the estimator is
    # built with the default and the resolved ``l1_ratio`` is recorded, rather
    # than passing a deprecated argument and swallowing its FutureWarning.
    clf = LogisticRegression(C=float(LINEAR["C"]), solver=LINEAR["solver"],
                             max_iter=int(LINEAR["max_iter"]))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        clf.fit(scaler.transform(X_fit), y_fit)
    conv = [str(w.message) for w in caught
            if issubclass(w.category, ConvergenceWarning)]
    info = {"n_iter_": [int(v) for v in np.atleast_1d(clf.n_iter_)],
            "max_iter": int(LINEAR["max_iter"]),
            "converged": not conv,
            "convergence_warnings": conv,
            "other_warnings": [f"{w.category.__name__}: {w.message}"
                               for w in caught
                               if not issubclass(w.category, ConvergenceWarning)],
            "penalty": "L2",
            "l1_ratio": float(clf.get_params()["l1_ratio"] or 0.0),
            "classes_": [int(c) for c in clf.classes_],
            "coef_": [float(v) for v in clf.coef_.ravel()],
            "intercept_": float(clf.intercept_[0]),
            "scaler_mean_": [float(v) for v in scaler.mean_],
            "scaler_scale_": [float(v) for v in scaler.scale_]}
    return (lambda X: clf.predict_proba(scaler.transform(X))[:, 1]), info


def fit_nonlinear(X_fit: np.ndarray, y_fit: np.ndarray):
    """The small HistGradientBoosting of §6, no scaling and no rebalancing."""
    clf = HistGradientBoostingClassifier(
        learning_rate=float(NONLINEAR["learning_rate"]),
        max_iter=int(NONLINEAR["max_iter"]),
        max_depth=int(NONLINEAR["max_depth"]),
        max_leaf_nodes=int(NONLINEAR["max_leaf_nodes"]),
        min_samples_leaf=int(NONLINEAR["min_samples_leaf"]),
        l2_regularization=float(NONLINEAR["l2_regularization"]),
        early_stopping=False,
        random_state=int(NONLINEAR["random_state"]))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        clf.fit(X_fit, y_fit)
    info = {"n_iter_": int(clf.n_iter_),
            "n_trees_per_iteration_": int(clf.n_trees_per_iteration_),
            "early_stopping": False,
            "warnings": [f"{w.category.__name__}: {w.message}" for w in caught],
            "classes_": [int(c) for c in clf.classes_]}
    return (lambda X: clf.predict_proba(X)[:, 1]), info


FAMILIES = {"LINEAR": fit_linear, "NONLINEAR": fit_nonlinear}


def session_results(rows: D.Rows, a: np.ndarray, b: np.ndarray, *,
                    min_per_class: int):
    """One :class:`SessionResult` per evaluation session, ``a`` in the first slot."""
    return [MET.session_result(s, a[rows.session == s], b[rows.session == s],
                               rows.Y[rows.session == s],
                               min_per_class=min_per_class)
            for s in rows.sessions()]


def mean_auc(results, which: str):
    v = [getattr(r, which) for r in results
         if r.qualifies and getattr(r, which) is not None]
    return float(np.mean(v)) if v else None


def main() -> int:
    t0 = time.time()
    D.check_artifacts()
    ser = D.series()
    fit = D.fitting_rows(ser)
    ev = D.evaluation_rows()

    mpc = int(D.CONFIG["evaluation_metric"]["min_per_class"])
    seed_level = int(D.CONFIG["bootstrap"]["level"]["seed"])
    seed_paired = int(D.CONFIG["bootstrap"]["paired"]["seed"])
    draws = int(D.CONFIG["bootstrap"]["draws"])

    # the fly's two score columns, on the very same rows, in the same order
    ps = ev.meta["probe_scores"]
    v_trained = np.array([ps[f"{s}|{m}"][0] for s, m in
                          zip(ev.session, ev.minute)], dtype=np.float64)
    v_reference = np.array([ps[f"{s}|{m}"][1] for s, m in
                            zip(ev.session, ev.minute)], dtype=np.float64)

    fly = {}
    for name, v in (("REFERENCE", v_reference), ("TRAINED", v_trained)):
        rs = session_results(ev, v, v, min_per_class=mpc)
        fly[name] = {"per_session": [r.as_dict()["auc_trained"] for r in rs],
                     "mean_auc": mean_auc(rs, "auc_trained")}

    models = []
    for rep in ("X_FEATURES", "X_SENSORY"):
        Xf, Xe = fit.x(rep), ev.x(rep)
        for fam, fitter in FAMILIES.items():
            score, info = fitter(Xf, fit.Y)
            s_fit = score(Xf)
            s_ev = score(Xe)
            rs = session_results(ev, s_ev, s_ev, min_per_class=mpc)
            per = [{"session": r.session, "n": r.n, "n_pos": r.n_pos,
                    "n_neg": r.n_neg, "auc": r.auc_trained,
                    "qualifies": r.qualifies, "reason": r.reason} for r in rs]
            q = [r.auc_trained for r in rs
                 if r.qualifies and r.auc_trained is not None]

            paired = {}
            for fly_name, v in (("REFERENCE", v_reference),
                                ("TRAINED", v_trained)):
                pr = session_results(ev, s_ev, v, min_per_class=mpc)
                paired[fly_name] = {
                    "delta_auc": MET.delta_auc(pr),
                    "paired_rows": int(len(ev)),
                    "paired_sessions": int(sum(1 for r in pr if r.qualifies)),
                    "per_session_delta": [
                        {"session": r.session, "delta": r.delta}
                        for r in pr if r.qualifies],
                    "bootstrap": MET.paired_session_bootstrap(
                        pr, draws=draws, seed=seed_paired)}

            models.append({
                "name": f"{fam} on {rep}",
                "family": fam,
                "representation": rep,
                "primary": bool(f"{fam} on {rep}" == D.CONFIG["models"]["primary"]),
                "parameters": LINEAR if fam == "LINEAR" else NONLINEAR,
                "fit": info,
                "fitting": {"rows": int(len(fit)),
                            "sessions": len(fit.sessions()),
                            "class_counts": {"Y=1": int((fit.Y == 1).sum()),
                                             "Y=0": int((fit.Y == 0).sum())},
                            "in_sample_auc": MET.roc_auc(s_fit, fit.Y),
                            "in_sample_note": "in-sample on the rows the model "
                                              "was fitted on; a description of "
                                              "the fit, not evidence"},
                "evaluation": {"rows": int(len(ev)),
                               "sessions": len(ev.sessions()),
                               "class_counts": {"Y=1": int((ev.Y == 1).sum()),
                                                "Y=0": int((ev.Y == 0).sum())},
                               "coverage": 1.0,
                               "exclusions": [r["session"] for r in per
                                              if not r["qualifies"]],
                               "qualifying_sessions": len(q)},
                "per_session_auc": per,
                "mean_auc": float(np.mean(q)) if q else None,
                "bootstrap": BS.session_bootstrap(q, draws=draws,
                                                  seed=seed_level),
                "paired_vs_fly": paired,
            })

    out = {
        "artifact": "flytrade-d8-models-1",
        "label": D.CONFIG["label"],
        "written_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sklearn": __import__("sklearn").__version__,
        "omp_num_threads": os.environ["OMP_NUM_THREADS"],
        "primary": D.CONFIG["models"]["primary"],
        "min_per_class": mpc,
        "bootstrap": {"draws": draws, "level_seed": seed_level,
                      "paired_seed": seed_paired,
                      "level_seed_label":
                          D.CONFIG["bootstrap"]["level"]["seed_label"],
                      "paired_seed_label":
                          D.CONFIG["bootstrap"]["paired"]["seed_label"]},
        "fly": fly,
        "models": models,
        "not_biological": "external measurement tools with supervised access "
                          "to historical labels; their results are never "
                          "attributed to the fly",
        "matched_participation": "not computed by D8 (Fable addendum 4)",
        "elapsed_s": round(time.time() - t0, 2),
    }
    OUT.write_text(json.dumps(out, indent=1))

    print(f"sklearn {out['sklearn']}  OMP_NUM_THREADS="
          f"{out['omp_num_threads']}  fitting {len(fit)} rows / "
          f"{len(fit.sessions())} sessions, evaluation {len(ev)} rows / "
          f"{len(ev.sessions())} sessions")
    print(f"fly REFERENCE mean AUC {fly['REFERENCE']['mean_auc']:.4f}   "
          f"TRAINED {fly['TRAINED']['mean_auc']:.4f}")
    print(f"{'model':26s} {'insample':>9s} {'meanAUC':>8s} {'2.5%':>8s} "
          f"{'97.5%':>8s} {'dREF':>8s} {'dTRN':>8s}")
    for m in models:
        b = m["bootstrap"]
        print(f"{m['name']:26s} {m['fitting']['in_sample_auc']:9.4f} "
              f"{m['mean_auc']:8.4f} {b['p2.5']:8.4f} {b['p97.5']:8.4f} "
              f"{m['paired_vs_fly']['REFERENCE']['delta_auc']:+8.4f} "
              f"{m['paired_vs_fly']['TRAINED']['delta_auc']:+8.4f}"
              f"{'   <- primary' if m['primary'] else ''}")
    for m in models:
        f = m["fit"]
        if m["family"] == "LINEAR":
            print(f"{m['name']:26s} n_iter_={f['n_iter_']} "
                  f"converged={f['converged']} warnings={f['convergence_warnings']}")
    print(f"ok in {out['elapsed_s']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
