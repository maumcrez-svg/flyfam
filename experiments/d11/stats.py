#!/usr/bin/env python
"""The statistics `d11_001.json` registered, and nothing it did not.

AUC is Mann-Whitney with ties counted a half. Uncertainty is a **paired cluster
bootstrap by ``stable_id``** — a token's rows move together — with 10,000
resamples at seed 20260913 and a percentile 95 % interval, overall and per
temporal block.

The wording rule the owner set travels with the number: an interval that
includes 0 is reported as *compatible with sampling variation*; one that does
not is reported with its bounds. Never "significant", never "proves", and an
AUC near 0.5 is not evidence that no signal exists. :func:`describe_interval`
is the only place that phrase is produced, so no caller can invent another.

Nothing here opens a socket and nothing here reads a configuration: the seed
and the resample count are passed in from the registered file.
"""

from __future__ import annotations

import numpy as np

RESAMPLES = 10_000
SEED = 20_260_913
LEVEL = 0.95


def auc(scores, labels) -> float | None:
    """Mann-Whitney U / (n_pos * n_neg), ties counted a half.

    ``labels`` is a boolean-like sequence: ``True`` for the positive class.
    Returns ``None`` when either class is empty — an AUC of an empty
    comparison is not 0.5, it does not exist.
    """
    s = np.asarray(scores, dtype=np.float64)
    y = np.asarray(labels).astype(bool)
    pos, neg = s[y], s[~y]
    if pos.size == 0 or neg.size == 0:
        return None
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(s.size, dtype=np.float64)
    sorted_s = s[order]
    i = 0
    while i < sorted_s.size:
        j = i
        while j + 1 < sorted_s.size and sorted_s[j + 1] == sorted_s[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0     # average rank, 1-based
        i = j + 1
    u = ranks[y].sum() - pos.size * (pos.size + 1) / 2.0
    return float(u / (pos.size * neg.size))


def spearman(x, y) -> float | None:
    """Spearman's rho with average ranks. ``None`` when either side is constant."""
    a, b = np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)
    if a.size < 2:
        return None
    ra, rb = _rank(a), _rank(b)
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def _rank(v: np.ndarray) -> np.ndarray:
    order = np.argsort(v, kind="mergesort")
    ranks = np.empty(v.size, dtype=np.float64)
    s = v[order]
    i = 0
    while i < s.size:
        j = i
        while j + 1 < s.size and s[j + 1] == s[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def cluster_bootstrap(clusters, statistic, *, resamples: int = RESAMPLES,
                      seed: int = SEED, level: float = LEVEL) -> dict:
    """Percentile interval of ``statistic`` under resampling **whole clusters**.

    ``clusters`` is a sequence of per-cluster payloads — here, the rows of one
    ``stable_id``. Each resample draws ``len(clusters)`` clusters with
    replacement and calls ``statistic`` on the concatenation, so every row of a
    token travels with it: a token that contributed forty correlated rows
    cannot be counted as forty independent observations.

    A resample for which the statistic does not exist (an empty class, say) is
    **counted and dropped**, never replaced by a zero. The result carries the
    number kept beside the interval, so a degenerate bootstrap is visible.
    """
    rows = list(clusters)
    point = statistic(_concat(rows))
    if not rows:
        return {"point": point, "resamples": 0, "kept": 0, "lo": None,
                "hi": None, "level": level, "seed": seed,
                "clusters": 0, "degenerate": True}
    rng = np.random.default_rng(int(seed))
    n = len(rows)
    kept: list[float] = []
    for _ in range(int(resamples)):
        pick = rng.integers(0, n, size=n)
        value = statistic(_concat([rows[i] for i in pick]))
        if value is not None and np.isfinite(value):
            kept.append(float(value))
    if not kept:
        return {"point": point, "resamples": int(resamples), "kept": 0,
                "lo": None, "hi": None, "level": level, "seed": seed,
                "clusters": n, "degenerate": True}
    arr = np.asarray(kept, dtype=np.float64)
    alpha = (1.0 - float(level)) / 2.0
    lo = float(np.percentile(arr, 100 * alpha))
    hi = float(np.percentile(arr, 100 * (1.0 - alpha)))
    return {"point": None if point is None else float(point),
            "resamples": int(resamples), "kept": len(kept),
            "lo": lo, "hi": hi, "level": float(level), "seed": int(seed),
            "clusters": n,
            "degenerate": bool(n <= 1 or arr.std() == 0.0)}


def _concat(cluster_rows) -> list:
    out = []
    for rows in cluster_rows:
        out.extend(rows)
    return out


def describe_interval(interval: dict, *, name: str = "the difference") -> str:
    """The owner's wording rule, in the one place it is allowed to be produced."""
    lo, hi = interval.get("lo"), interval.get("hi")
    point = interval.get("point")
    if lo is None or hi is None or point is None:
        return (f"{name} could not be given an interval "
                f"({interval.get('clusters', 0)} clusters, "
                f"{interval.get('kept', 0)} resamples kept)")
    body = f"{name} is {point:+.4f}, 95 % interval [{lo:+.4f}, {hi:+.4f}]"
    if lo <= 0.0 <= hi:
        return body + " — an interval that includes 0, compatible with " \
                      "sampling variation"
    return body + " — an interval that excludes 0"


def delta_auc_statistic(score_key_a: str, score_key_b: str, label_key: str):
    """A statistic for :func:`cluster_bootstrap`: AUC(a) - AUC(b) over rows."""
    def statistic(rows):
        if not rows:
            return None
        y = [r[label_key] for r in rows]
        a = auc([r[score_key_a] for r in rows], y)
        b = auc([r[score_key_b] for r in rows], y)
        if a is None or b is None:
            return None
        return a - b
    return statistic


def rate_statistic(key: str):
    """The share of rows where ``key`` is true."""
    def statistic(rows):
        if not rows:
            return None
        return float(sum(1 for r in rows if r[key]) / len(rows))
    return statistic


def class_contrast_statistic(key_a: str, key_b: str, label_key: str):
    """(trained-minus-reference change) in the negative class minus the positive.

    The pre-registered suppression reading: whether the change in the
    BUY-crossing rate depends on the later outcome class at all. Positive means
    the drop is larger in the negative class.
    """
    def statistic(rows):
        if not rows:
            return None
        out = {}
        for positive in (True, False):
            sub = [r for r in rows if bool(r[label_key]) is positive]
            if not sub:
                return None
            out[positive] = (sum(1 for r in sub if r[key_a]) / len(sub)
                             - sum(1 for r in sub if r[key_b]) / len(sub))
        return float(out[False] - out[True])
    return statistic


__all__ = ["RESAMPLES", "SEED", "LEVEL", "auc", "spearman", "cluster_bootstrap",
           "describe_interval", "delta_auc_statistic", "rate_statistic",
           "class_contrast_statistic"]
