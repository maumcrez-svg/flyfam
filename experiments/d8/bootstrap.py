"""
The whole-session bootstrap D8 needs that `flytrade.metrics` does not have.

Fable addenda 5 and 6. `flytrade/` is not modified by this wave, so the one
helper D8 needs and D7 did not — an **unpaired** resampling of whole sessions,
for a single diagnostic's mean AUC level — is written here and unit-tested on a
fixture against `flytrade.metrics.paired_session_bootstrap`, which stays the
implementation used for every **paired** delta.

Both are the same arithmetic: resample whole qualifying sessions with
replacement, take the equal-session mean of the per-session quantity in each
draw, and report the 2.5–97.5 % range of those means. Individual minute rows are
never resampled: overlapping 90-minute labels are not independent trials.

The interval is **descriptive and conditional** on this dataset and this model
fit. It is not a significance test and the secondary lines are not simultaneous
family-wise evidence.
"""
from __future__ import annotations

import numpy as np

#: PLAN §8
DRAWS = 2000


def session_bootstrap(values, *, draws: int = DRAWS, seed: int) -> dict:
    """Resample whole sessions; report the distribution of the equal-session mean.

    ``values`` is one number per qualifying session — an AUC, or a delta. The
    draw indices are produced exactly as
    :func:`flytrade.metrics.paired_session_bootstrap` produces them, from
    ``numpy.random.default_rng(seed).integers(0, n, size=(draws, n))``, so the
    two agree draw for draw on the same seed and the same vector.
    """
    d = np.asarray([v for v in values if v is not None], dtype=np.float64)
    if len(d) == 0:
        return {"draws": 0, "seed": int(seed), "n_sessions": 0,
                "note": "no qualifying session"}
    rng = np.random.default_rng(int(seed))
    idx = rng.integers(0, len(d), size=(int(draws), len(d)))
    means = d[idx].mean(axis=1)
    return {
        "draws": int(draws),
        "seed": int(seed),
        "unit": "whole qualifying evaluation session",
        "n_sessions": int(len(d)),
        "observed": float(d.mean()),
        "mean": float(means.mean()),
        "sd": float(means.std(ddof=1)),
        "p2.5": float(np.percentile(means, 2.5)),
        "p50": float(np.percentile(means, 50.0)),
        "p97.5": float(np.percentile(means, 97.5)),
        "fraction_of_draws_above_half": float((means > 0.5).mean()),
        "caveat": "descriptive, day-resampled and conditional on this dataset "
                  "and this model fit; not a significance test",
    }
