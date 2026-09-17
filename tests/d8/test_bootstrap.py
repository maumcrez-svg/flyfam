"""
The D8 session bootstrap — Fable addenda 5 and 6.

`flytrade/` is not modified by this wave, so the one helper D8 needs and D7 did
not — an unpaired resampling of whole sessions for a single diagnostic's mean
AUC level — lives in ``experiments/d8/bootstrap.py``. It must be the same
arithmetic as ``flytrade.metrics.paired_session_bootstrap``, and these tests
prove that on a fixture rather than asserting it in a docstring.
"""
from __future__ import annotations

import numpy as np

import bootstrap as BS                              # experiments/d8
from flytrade import metrics as MET

SEED = MET.declared_seed("flytrade-d8-bootstrap-test")


class R:
    """The minimum a ``SessionResult`` needs to enter the paired bootstrap."""

    def __init__(self, delta):
        self.qualifies = True
        self.delta = delta


def test_the_two_bootstraps_agree_draw_for_draw_on_the_same_seed():
    rng = np.random.default_rng(7)
    d = rng.normal(0.0, 0.05, size=9)
    mine = BS.session_bootstrap(d, draws=2000, seed=SEED)
    theirs = MET.paired_session_bootstrap([R(x) for x in d], draws=2000,
                                          seed=SEED)
    for k in ("mean", "sd", "p2.5", "p50", "p97.5"):
        assert abs(mine[k] - theirs[k]) < 1e-12, k
    assert mine["n_sessions"] == theirs["n_sessions"] == 9
    assert mine["observed"] == theirs["observed_delta_auc"]


def test_it_resamples_whole_sessions_not_minutes():
    d = np.array([0.4, 0.5, 0.6])
    out = BS.session_bootstrap(d, draws=500, seed=SEED)
    assert out["unit"].startswith("whole qualifying")
    assert out["n_sessions"] == 3
    # every draw mean must be a mean of three values drawn from {0.4, 0.5, 0.6}
    assert 0.4 - 1e-12 <= out["p2.5"] <= out["p97.5"] <= 0.6 + 1e-12


def test_no_qualifying_session_is_reported_not_invented():
    out = BS.session_bootstrap([], draws=100, seed=SEED)
    assert out["draws"] == 0 and out["n_sessions"] == 0


def test_none_values_are_dropped_never_read_as_one_half():
    out = BS.session_bootstrap([0.6, None, 0.6], draws=100, seed=SEED)
    assert out["n_sessions"] == 2
    assert abs(out["observed"] - 0.6) < 1e-12


def test_the_seeds_are_declared_strings_not_lucky_integers():
    assert MET.declared_seed("flytrade-d8-bootstrap-1") == 2954118192
    assert MET.declared_seed("flytrade-d8-paired-1") == 1942182944
