#!/usr/bin/env python
"""
D8 stage 2 — the orientation artifact, then the feature / PC1 table.

    .venv/bin/python experiments/d8/orient.py

Two files, written in this order and for that reason:

1. ``experiments/d8/orientation.json`` — the five scalar features' signs and
   PC1's, each chosen on the **fitting rows only** (raw fitting AUC; sign = +1
   if that AUC >= 0.5, else -1), together with the PCA fitted on the
   fitting-centred X_SENSORY by numpy SVD, no whitening. Written to disk
   **before a single evaluation AUC exists**, and its sha256 is quoted in
   `results.md`.
2. ``withheld d8 pc1 table`` — per-session **raw** and **oriented**
   evaluation AUCs, the equal-session means, and the whole-session bootstrap of
   each oriented column.

A feature whose AUC is below 0.5 may rank in the opposite direction; it is not
called uninformative for that. ``max(AUC, 1 - AUC)`` is never reported, and no
sign is ever chosen or flipped on an evaluation day.

This table describes marginal rankings and one projection. **It is not the final
input-informativeness verdict** — amendment §2 and §5.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bootstrap as BS                              # noqa: E402
import data as D                                    # noqa: E402
from flytrade import metrics as MET                 # noqa: E402

ORIENTATION = HERE / "orientation.json"
TABLE = HERE / "features_pc1.json"


def sha256_text(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ------------------------------------------------------------------- PCA

def fit_pc1(X_fit: np.ndarray) -> dict:
    """PC1 of the fitting-centred X_SENSORY, by SVD. No whitening.

    The component is signed so that its largest-magnitude loading is positive;
    that convention is arithmetic, and is separate from the target-based
    orientation sign chosen below. A constant or rank-deficient representation
    is reported as **degenerate** rather than turned into a score.
    """
    mean = X_fit.mean(axis=0)
    Z = X_fit - mean
    u, s, vt = np.linalg.svd(Z, full_matrices=False)
    var = (s ** 2) / max(len(Z) - 1, 1)
    total = float(var.sum())
    rank = int(np.linalg.matrix_rank(Z))
    degenerate = bool(total <= 0.0 or s[0] <= 0.0 or rank < 1)
    v1 = vt[0].copy()
    j = int(np.argmax(np.abs(v1)))
    convention_sign = 1.0 if v1[j] >= 0 else -1.0
    v1 = v1 * convention_sign
    return {
        "degenerate": degenerate,
        "rank": rank,
        "n_fitting_rows": int(len(Z)),
        "mean": [float(x) for x in mean],
        "loadings": [float(x) for x in v1],
        "loading_names": list(D.GLOMERULI),
        "singular_values": [float(x) for x in s],
        "explained_variance": [float(x) for x in var],
        "explained_variance_ratio": [float(x / total) for x in var] if total else None,
        "explained_variance_ratio_pc1": float(var[0] / total) if total else None,
        "sign_convention": "the component is signed so that its "
                           "largest-magnitude loading is positive",
        "largest_loading_channel": D.GLOMERULI[j],
        "whitening": False,
        "fitted_on": "fitting rows only, centred on the fitting mean",
        "method": "numpy.linalg.svd",
    }


def pc1_scores(pca: dict, X: np.ndarray) -> np.ndarray:
    return (X - np.asarray(pca["mean"])) @ np.asarray(pca["loadings"])


# ----------------------------------------------------------- orientation

def orientation(fit: D.Rows, pca: dict) -> dict:
    """Signs from the fitting rows only, and nothing else."""
    cols = {}
    for j, name in enumerate(D.FEATURES):
        a = MET.roc_auc(fit.X_FEATURES[:, j], fit.Y)
        cols[name] = {"representation": "X_FEATURES", "column": j,
                      "fitting_auc_raw": a,
                      "sign": (1 if (a is not None and a >= 0.5) else -1)}
    if pca["degenerate"]:
        cols["PC1"] = {"representation": "X_SENSORY", "column": "PC1",
                       "fitting_auc_raw": None, "sign": None,
                       "degenerate": True}
    else:
        a = MET.roc_auc(pc1_scores(pca, fit.X_SENSORY), fit.Y)
        cols["PC1"] = {"representation": "X_SENSORY", "column": "PC1",
                       "fitting_auc_raw": a,
                       "sign": (1 if (a is not None and a >= 0.5) else -1),
                       "degenerate": False}
    return {
        "artifact": "flytrade-d8-orientation-1",
        "label": D.CONFIG["label"],
        "written_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "rule": D.CONFIG["orientation"]["rule"],
        "fitting_rows": int(len(fit)),
        "fitting_sessions": fit.sessions(),
        "fitting_class_counts": {"Y=1": int((fit.Y == 1).sum()),
                                 "Y=0": int((fit.Y == 0).sum())},
        "written_before_any_evaluation_auc": True,
        "never_max_auc_or_one_minus_auc": True,
        "columns": cols,
        "pca": pca,
    }


# ------------------------------------------------------------ evaluation

def per_session_auc(rows: D.Rows, scores: np.ndarray, *, min_per_class: int):
    """Raw per-session AUC and the qualification flag, D7's rule unchanged."""
    out = []
    for s in rows.sessions():
        m = rows.session == s
        y = rows.Y[m]
        npos, nneg = int((y == 1).sum()), int((y == 0).sum())
        out.append({
            "session": s, "n": int(m.sum()), "n_pos": npos, "n_neg": nneg,
            "auc": MET.roc_auc(scores[m], y),
            "qualifies": bool(npos >= min_per_class and nneg >= min_per_class),
            "reason": "" if (npos >= min_per_class and nneg >= min_per_class)
                      else (f"{npos} profitable and {nneg} nonprofitable "
                            f"labels, fewer than {min_per_class} in one class"),
        })
    return out


def column_result(name: str, rows: D.Rows, raw_scores: np.ndarray, sign,
                  *, min_per_class: int, seed: int) -> dict:
    """One column of the table: raw and oriented, per session and in the mean."""
    raw = per_session_auc(rows, raw_scores, min_per_class=min_per_class)
    ori = per_session_auc(rows, raw_scores * float(sign),
                          min_per_class=min_per_class)
    q_raw = [r["auc"] for r in raw if r["qualifies"] and r["auc"] is not None]
    q_ori = [r["auc"] for r in ori if r["qualifies"] and r["auc"] is not None]
    return {
        "column": name,
        "sign_from_fitting": int(sign),
        "per_session_raw": raw,
        "per_session_oriented": ori,
        "mean_auc_raw": float(np.mean(q_raw)) if q_raw else None,
        "mean_auc_oriented": float(np.mean(q_ori)) if q_ori else None,
        "qualifying_sessions": len(q_ori),
        "excluded_sessions": [r["session"] for r in ori if not r["qualifies"]],
        "bootstrap_oriented": BS.session_bootstrap(q_ori, seed=seed),
    }


def main() -> int:
    t0 = time.time()
    D.check_artifacts()
    ser = D.series()
    fit = D.fitting_rows(ser)
    ev = D.evaluation_rows()

    # ---- 1. fitting only: the PCA and every sign, written before any
    #         evaluation AUC exists ------------------------------------------
    pca = fit_pc1(fit.X_SENSORY)
    ori = orientation(fit, pca)
    ORIENTATION.write_text(json.dumps(ori, indent=1))
    print(f"orientation.json written  sha256 {sha256_text(ORIENTATION)}")
    for name, c in ori["columns"].items():
        print(f"  {name:8s} fitting raw AUC "
              f"{'degenerate' if c['fitting_auc_raw'] is None else round(c['fitting_auc_raw'], 4)}"
              f"  sign {c['sign']}")
    print(f"  PC1 explained variance ratio "
          f"{pca['explained_variance_ratio_pc1']:.6f}  rank {pca['rank']}  "
          f"degenerate {pca['degenerate']}")

    # ---- 2. only now, the evaluation AUCs -----------------------------------
    mpc = int(D.CONFIG["evaluation_metric"]["min_per_class"])
    seed = int(D.CONFIG["bootstrap"]["level"]["seed"])
    cols = []
    for j, name in enumerate(D.FEATURES):
        cols.append(column_result(name, ev, ev.X_FEATURES[:, j],
                                  ori["columns"][name]["sign"],
                                  min_per_class=mpc, seed=seed))
    if pca["degenerate"]:
        cols.append({"column": "PC1", "degenerate": True,
                     "note": "the fitting representation is constant or "
                             "rank-deficient; no PC1 score is manufactured"})
    else:
        cols.append(column_result("PC1", ev, pc1_scores(pca, ev.X_SENSORY),
                                  ori["columns"]["PC1"]["sign"],
                                  min_per_class=mpc, seed=seed))

    out = {
        "artifact": "flytrade-d8-features-pc1-1",
        "label": D.CONFIG["label"],
        "written_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "orientation_sha256": sha256_text(ORIENTATION),
        "evaluation_rows": int(len(ev)),
        "evaluation_sessions": ev.sessions(),
        "min_per_class": mpc,
        "bootstrap_seed": seed,
        "bootstrap_seed_label": D.CONFIG["bootstrap"]["level"]["seed_label"],
        "bootstrap_draws": int(D.CONFIG["bootstrap"]["draws"]),
        "columns": cols,
        "caveat": "marginal rankings and one projection; not the final "
                  "input-informativeness verdict. A column below 0.5 may rank "
                  "in the opposite direction; max(AUC, 1 - AUC) is never "
                  "reported and no sign was chosen on an evaluation day.",
        "elapsed_s": round(time.time() - t0, 2),
    }
    TABLE.write_text(json.dumps(out, indent=1))

    print("\nevaluation, equal-session mean AUC over qualifying sessions:")
    print(f"{'column':8s} {'sign':>5s} {'raw':>8s} {'oriented':>9s} "
          f"{'2.5%':>8s} {'97.5%':>8s}  excluded")
    for c in cols:
        if c.get("degenerate"):
            print(f"{c['column']:8s}  degenerate")
            continue
        b = c["bootstrap_oriented"]
        print(f"{c['column']:8s} {c['sign_from_fitting']:+5d} "
              f"{c['mean_auc_raw']:8.4f} {c['mean_auc_oriented']:9.4f} "
              f"{b['p2.5']:8.4f} {b['p97.5']:8.4f}  {c['excluded_sessions']}")
    print(f"ok in {out['elapsed_s']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
