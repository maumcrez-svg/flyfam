"""
Ranking metrics for the D7 context-discrimination evaluation.

Canonical amendment D7 §7, §8 and §9. Four things live here and nothing else:
a pairwise ROC-AUC that treats ties explicitly, the paired session bootstrap,
the matched-participation selection with fractional tie weighting, and the
qualification rules that decide which session may enter an aggregate.

This module is arithmetic. It imports nothing from :mod:`flytrade.runner`,
:mod:`flytrade.mushroom`, :mod:`flytrade.execution` or :mod:`flytrade.records`;
it holds no state; it cannot read or move a weight, place an order or touch an
account. It is used by a read-only evaluator that runs **after** both frozen
branches have finished.

## ROC-AUC, and what it may not reward

    AUC = P(score of a profitable context > score of a nonprofitable one)
          + 0.5 * P(equal)

computed over all ``n_pos * n_neg`` pairs. Stated that way, the metric is
invariant to any strictly increasing transformation of the scores — in
particular to **subtracting a constant** and to **positive rescaling**. That
invariance is the point of the amendment's choice of metric: a brain that
lowered every response by the same amount, and so buys less everywhere, gets
exactly no credit for context discrimination. The required tests in §7 are
tests of that property.

A session with one class present has **undefined** AUC, not 0.5, and is
excluded by name. A constant score with both classes present is exactly 0.5,
because every pair is a tie.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np

VERSION = "flytrade-metrics-1"

#: §7: a session qualifies only with at least this many probes of each class
MIN_PER_CLASS = 10

#: §7: at least this many qualifying sessions before an aggregate is stated
MIN_SESSIONS = 5

#: §7: per-branch and paired coverage below this is coverage-limited
MIN_COVERAGE = 0.95

#: §8: the fixed matched-participation fraction. Not searched over.
TOP_FRACTION = 0.20

#: §9: bootstrap draws of whole sessions
BOOTSTRAP_DRAWS = 2000


# ------------------------------------------------------------------ AUC

def _midranks(x: np.ndarray) -> np.ndarray:
    """Average ranks, ties sharing their mean rank."""
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(len(x), dtype=np.float64)
    xs = x[order]
    i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[j + 1] == xs[i]:
            j += 1
        ranks[order[i:j + 1]] = 0.5 * (i + j) + 1.0
        i = j + 1
    return ranks


def roc_auc(scores, labels) -> float | None:
    """Pairwise ROC-AUC with ties at 0.5 credit, or ``None`` for one class.

    ``labels`` is 1 for a profitable context and 0 for a nonprofitable one.
    Implemented by midranks, which is the same number as the explicit double
    loop over pairs — a test proves that on random inputs, including on inputs
    made entirely of ties.
    """
    s = np.asarray(scores, dtype=np.float64)
    y = np.asarray(labels).astype(int)
    if s.shape != y.shape or s.ndim != 1:
        raise ValueError("scores and labels must be one-dimensional and equal")
    n_pos = int((y == 1).sum())
    n_neg = int((y == 0).sum())
    if n_pos == 0 or n_neg == 0:
        return None                       # undefined, never 0.5
    r = _midranks(s)
    return float((r[y == 1].sum() - n_pos * (n_pos + 1) / 2.0)
                 / (n_pos * n_neg))


def roc_auc_pairwise(scores, labels) -> float | None:
    """The definition itself, O(n^2). The reference the fast path is tested on."""
    s = np.asarray(scores, dtype=np.float64)
    y = np.asarray(labels).astype(int)
    pos, neg = s[y == 1], s[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return None
    total = 0.0
    for p in pos:
        total += float((p > neg).sum()) + 0.5 * float((p == neg).sum())
    return total / (len(pos) * len(neg))


# ------------------------------------------------- session qualification

@dataclass(frozen=True)
class SessionResult:
    """One FROZEN session's paired result. ``None`` AUC means undefined."""

    session: str
    n: int
    n_pos: int
    n_neg: int
    auc_trained: float | None
    auc_reference: float | None
    qualifies: bool
    reason: str = ""

    @property
    def delta(self) -> float | None:
        if self.auc_trained is None or self.auc_reference is None:
            return None
        return self.auc_trained - self.auc_reference

    def as_dict(self) -> dict:
        return {"session": self.session, "n": self.n, "n_pos": self.n_pos,
                "n_neg": self.n_neg,
                "auc_trained": self.auc_trained,
                "auc_reference": self.auc_reference,
                "delta_auc": self.delta, "qualifies": self.qualifies,
                "reason": self.reason}


def session_result(session: str, trained_scores, reference_scores, labels, *,
                   min_per_class: int = MIN_PER_CLASS) -> SessionResult:
    """Both AUCs for one session, on the **same paired set** of probes."""
    y = np.asarray(labels).astype(int)
    n_pos, n_neg = int((y == 1).sum()), int((y == 0).sum())
    ok = n_pos >= min_per_class and n_neg >= min_per_class
    reason = "" if ok else (
        f"{n_pos} profitable and {n_neg} nonprofitable labels, "
        f"fewer than {min_per_class} in one class")
    return SessionResult(
        session=session, n=len(y), n_pos=n_pos, n_neg=n_neg,
        auc_trained=roc_auc(trained_scores, y),
        auc_reference=roc_auc(reference_scores, y),
        qualifies=ok, reason=reason)


def delta_auc(results) -> float | None:
    """Mean of ``AUC_TRAINED - AUC_REFERENCE`` over qualifying sessions.

    Equal weight per session, as §7 requires, whatever a session's probe count.
    """
    d = [r.delta for r in results if r.qualifies and r.delta is not None]
    return float(np.mean(d)) if d else None


# --------------------------------------------------------- the bootstrap

def declared_seed(label: str) -> int:
    """A bootstrap seed that is a declared string, not a lucky integer."""
    return int.from_bytes(hashlib.sha256(label.encode()).digest()[:4], "big")


def paired_session_bootstrap(results, *, draws: int = BOOTSTRAP_DRAWS,
                             seed: int) -> dict:
    """Resample whole qualifying sessions, both branches kept paired.

    §9: this is limited, day-resampled uncertainty **conditional on this
    training run**, not a significance test, and individual minute rows are
    never resampled as if they were independent — overlapping H-minute
    outcomes are not independent trials.
    """
    d = np.array([r.delta for r in results
                  if r.qualifies and r.delta is not None], dtype=np.float64)
    if len(d) == 0:
        return {"draws": 0, "seed": int(seed), "n_sessions": 0,
                "note": "no qualifying session"}
    rng = np.random.default_rng(int(seed))
    idx = rng.integers(0, len(d), size=(int(draws), len(d)))
    means = d[idx].mean(axis=1)
    return {
        "draws": int(draws),
        "seed": int(seed),
        "unit": "whole qualifying session, both branches paired",
        "n_sessions": int(len(d)),
        "observed_delta_auc": float(d.mean()),
        "mean": float(means.mean()),
        "sd": float(means.std(ddof=1)),
        "p2.5": float(np.percentile(means, 2.5)),
        "p50": float(np.percentile(means, 50.0)),
        "p97.5": float(np.percentile(means, 97.5)),
        "fraction_of_draws_above_zero": float((means > 0).mean()),
        "caveat": "day-resampled uncertainty conditional on this one training "
                  "run; not a definitive significance test",
    }


# ---------------------------------------------- matched participation

def top_fraction_weights(scores, fraction: float = TOP_FRACTION) -> np.ndarray:
    """Weights selecting the highest-scoring ``fraction`` of probes.

    §8: both branches select the **same fraction**, so "buying less" cannot
    explain an advantage here. Boundary ties are handled by **fractional
    weighting** — every probe tied at the cutoff score carries the same
    fractional weight, so the total weight is exactly ``fraction * n`` and the
    selection never depends on the order rows happen to be in, on a later
    label, or on time.
    """
    s = np.asarray(scores, dtype=np.float64)
    n = len(s)
    w = np.zeros(n, dtype=np.float64)
    if n == 0:
        return w
    budget = float(fraction) * n
    order = np.argsort(-s, kind="mergesort")
    taken = 0.0
    i = 0
    ss = s[order]
    while i < n and taken < budget - 1e-12:
        j = i
        while j + 1 < n and ss[j + 1] == ss[i]:
            j += 1
        size = j - i + 1
        room = budget - taken
        share = 1.0 if size <= room else room / size
        w[order[i:j + 1]] = share
        taken += share * size
        i = j + 1
    return w


def matched_participation(trained_scores, reference_scores, g, y, *,
                          fraction: float = TOP_FRACTION) -> dict:
    """Mean ``G(t)`` and profitable rate inside each branch's own top slice.

    A retrospective ranking diagnostic, not a trading policy and not a
    backtested portfolio: the probes overlap in time and are never summed into
    an executable PnL.
    """
    g = np.asarray(g, dtype=np.float64)
    y = np.asarray(y).astype(float)
    out = {"fraction": float(fraction), "n": int(len(g))}
    for name, s in (("trained", trained_scores), ("reference", reference_scores)):
        w = top_fraction_weights(s, fraction)
        tw = float(w.sum())
        out[name] = {
            "selected_weight": tw,
            "selected_rows_nonzero_weight": int((w > 0).sum()),
            "mean_G": float((w * g).sum() / tw) if tw else None,
            "profitable_rate": float((w * y).sum() / tw) if tw else None,
        }
    out["all_probes"] = {"mean_G": float(g.mean()) if len(g) else None,
                         "profitable_rate": float(y.mean()) if len(y) else None}
    if out["trained"]["mean_G"] is not None \
            and out["reference"]["mean_G"] is not None:
        out["difference"] = {
            "mean_G": out["trained"]["mean_G"] - out["reference"]["mean_G"],
            "profitable_rate": (out["trained"]["profitable_rate"]
                                - out["reference"]["profitable_rate"])}
    return out


# ------------------------------------------------------------- coverage

def coverage(n_available: int, n_used: int) -> float:
    """Fraction of otherwise label-available probes a branch actually covers."""
    return float(n_used) / float(n_available) if n_available else 0.0


def classify(results, bootstrap: dict, cov: dict, *,
             min_sessions: int = MIN_SESSIONS,
             min_coverage: float = MIN_COVERAGE) -> dict:
    """A, B or C, exactly as §9 defines them, with the reason it is that one.

    This function states which of the three the numbers support; it does not
    soften C into A and it does not read profitability. ``B`` and ``C`` are
    distinguished by whether the evidence is *absent* (C: too few sessions,
    inadequate coverage, unstable effects) or *present and negative* (B:
    enough informative sessions, adequate coverage, no supported improvement
    in ranking).
    """
    q = [r for r in results if r.qualifies and r.delta is not None]
    d = delta_auc(results)
    covs = [v for k, v in cov.items() if k.endswith("_coverage")]
    low = [k for k, v in cov.items()
           if k.endswith("_coverage") and v < min_coverage]
    trained_mean = (float(np.mean([r.auc_trained for r in q])) if q else None)
    ref_mean = (float(np.mean([r.auc_reference for r in q])) if q else None)
    frac = bootstrap.get("fraction_of_draws_above_zero")
    reasons = []
    if len(q) < min_sessions:
        reasons.append(f"{len(q)} qualifying sessions, fewer than "
                       f"{min_sessions}")
    if low:
        reasons.append("coverage below "
                       f"{min_coverage:.0%} for: {', '.join(sorted(low))}")
    if reasons:
        verdict, why = "C", "; ".join(reasons)
    elif d is None:
        verdict, why = "C", "DELTA_AUC undefined"
    elif d > 0 and trained_mean is not None and trained_mean > 0.5 \
            and frac is not None and frac >= 0.975:
        verdict = "A"
        why = (f"DELTA_AUC {d:+.4f} with trained AUC {trained_mean:.4f} above "
               f"chance and {frac:.1%} of paired session draws above zero")
    elif d > 0 and (trained_mean is None or trained_mean <= 0.5):
        verdict = "C"
        why = (f"DELTA_AUC {d:+.4f} is positive but trained AUC "
               f"{trained_mean:.4f} is at or below chance-level ranking, "
               f"which §9 says is insufficient on its own")
    else:
        verdict = "B"
        why = (f"DELTA_AUC {d:+.4f} over {len(q)} qualifying sessions, "
               f"{('%.1f%%' % (100 * frac)) if frac is not None else 'n/a'} "
               f"of paired draws above zero: no supported improvement in "
               f"context ranking")
    return {"conclusion": verdict, "reason": why,
            "qualifying_sessions": len(q),
            "mean_auc_trained": trained_mean,
            "mean_auc_reference": ref_mean,
            "delta_auc": d,
            "min_coverage_seen": min(covs) if covs else None,
            "definitions": {
                "A": "context-discrimination evidence in this experiment",
                "B": "suppression without demonstrated discrimination "
                     "improvement",
                "C": "inconclusive"}}
