"""
Canonical amendment §2 — fair sequential evaluation.

The two tests the amendment names explicitly are here, one each as Fable
addendum 10 requires: candidate-order permutation and ticker renaming. Both
assert on the **neural readout**, not on an action: no decoder exists at this
commit, and the property being tested is a property of the evaluation, not of
any later decoding.
"""
from __future__ import annotations

import numpy as np
import pytest

from flytrade import encoder as E
from flytrade import market as MK
from flytrade import runner as R

from .conftest import requires_real_graph

SYMBOLS = ("ALFA", "BETA", "GAMA", "DLTA")
ROUND_SEED = 77
ROUND_INDEX = 4
CUTOFF = 260


def _series():
    return {s: MK.synthetic_series(s, seed=200 + i)
            for i, s in enumerate(SYMBOLS)}


def _runner(brain, ann):
    fb, mb, gains = brain
    enc = E.MarketToSensoryEncoder(ann)
    pops = {"pam_side": mb.compartments.pam_side,
            "ppl1_side": mb.compartments.ppl1_side,
            "mbon": mb.mbon}
    return R.BrainRunner(fb, mb, enc, pops, gains=gains)


def _observations(feed, universe, symbols, cutoff=CUTOFF):
    return [feed.observe(s, cutoff, stable_id=universe.stable_id(s))
            for s in symbols]


def _fingerprint(rnd: R.RoundEvaluation) -> dict:
    """Everything about a round that must not depend on presentation order."""
    out = {}
    for c in rnd.candidates:
        out[c.stable_id] = (
            c.seed, c.episode_id,
            tuple(round(float(x), 12) for x in c.observation.normalized),
            tuple(round(c.presentation.mean(k), 12)
                  for k in sorted(c.presentation.rates)),
            c.presentation.kc_active,
            c.trace.n_eligible, round(c.trace.max_trace, 12),
            tuple(int(i) for i in c.trace.index[:64]),
        )
    return out


# ------------------------------------------------------- seeds and ids

def test_candidate_seed_and_episode_id_depend_only_on_round_and_stable_id():
    assert R.candidate_seed(3, 5) == R.candidate_seed(3, 5)
    assert R.candidate_seed(3, 5) != R.candidate_seed(3, 6)
    assert R.candidate_seed(3, 5) != R.candidate_seed(4, 5)
    assert 0 <= R.candidate_seed(10 ** 9, 12) < 2 ** 31
    assert R.episode_id_for(2, 7) == 2 * R.EPISODE_STRIDE + 7
    assert R.episode_id_for(2, 7) != R.episode_id_for(7, 2)
    with pytest.raises(ValueError):
        R.episode_id_for(0, R.EPISODE_STRIDE)


# ------------------------------------------------------ the two tests

@requires_real_graph
def test_candidate_order_permutation_changes_nothing(brain, ann, fresh_weights):
    """Amendment §2: results must not depend on iteration order."""
    feed = MK.ObservationFeed(_series())
    universe = MK.Universe(SYMBOLS)
    run = _runner(brain, ann)

    forward = run.evaluate_round(
        _observations(feed, universe, SYMBOLS),
        round_index=ROUND_INDEX, round_seed=ROUND_SEED,
        score=lambda c: c.presentation.mean("ppl1_side"))
    reverse = run.evaluate_round(
        _observations(feed, universe, tuple(reversed(SYMBOLS))),
        round_index=ROUND_INDEX, round_seed=ROUND_SEED,
        score=lambda c: c.presentation.mean("ppl1_side"))

    assert _fingerprint(forward) == _fingerprint(reverse)
    assert forward.scores == reverse.scores
    assert forward.selected.symbol == reverse.selected.symbol
    assert [c.symbol for c in forward.candidates] == list(SYMBOLS)
    assert [c.symbol for c in reverse.candidates] == list(reversed(SYMBOLS))


@requires_real_graph
def test_renaming_every_ticker_changes_nothing(brain, ann, fresh_weights):
    """Amendment §2: results must not depend on symbol spelling."""
    series = _series()
    universe = MK.Universe(SYMBOLS)
    run = _runner(brain, ann)
    before = run.evaluate_round(
        _observations(MK.ObservationFeed(series), universe, SYMBOLS),
        round_index=ROUND_INDEX, round_seed=ROUND_SEED,
        score=lambda c: c.presentation.mean("ppl1_side"))

    new = {"ALFA": "ZZ9", "BETA": "A", "GAMA": "0000000000", "DLTA": "z-z"}
    renamed = {new[k]: MK.Series(new[k], v.bars, v.interval_s)
               for k, v in series.items()}
    for old, fresh in new.items():
        universe.rename(old, fresh)
    after = run.evaluate_round(
        _observations(MK.ObservationFeed(renamed), universe,
                      tuple(new[s] for s in SYMBOLS)),
        round_index=ROUND_INDEX, round_seed=ROUND_SEED,
        score=lambda c: c.presentation.mean("ppl1_side"))

    assert _fingerprint(before) == _fingerprint(after)
    assert before.scores == after.scores
    assert new[before.selected.symbol] == after.selected.symbol


# ---------------------------------------------- the mechanism underneath

@requires_real_graph
def test_every_candidate_starts_from_the_same_transient_snapshot(brain, ann,
                                                                 fresh_weights):
    """A trace laid down by one candidate must not reach the next one."""
    fb, mb, _ = brain
    feed = MK.ObservationFeed(_series())
    universe = MK.Universe(SYMBOLS)
    run = _runner(brain, ann)

    # deliberately dirty the eligibility layer before the round
    mb.trace[:200] = 1.0
    mb.trace_episode[:200] = -99
    s0 = run.snapshot()

    rnd = run.evaluate_round(_observations(feed, universe, SYMBOLS),
                             round_index=ROUND_INDEX, round_seed=ROUND_SEED,
                             score=lambda c: c.presentation.mean("ppl1_side"))

    # every candidate saw the dirty trace in S0, and none of it leaked into a
    # captured trace: what was captured is exactly what this presentation made
    # eligible, no more
    for c in rnd.candidates:
        assert c.trace.episode_id == R.episode_id_for(ROUND_INDEX, c.stable_id)
        assert c.trace.n_eligible == c.presentation.n_eligible
    # a candidate whose Kenyon cells never fired lays no trace at all; that is
    # the NO_RESPONSE case and it does occur on real observations
    assert any(c.trace.n_eligible > 0 for c in rnd.candidates)

    # and each candidate, re-presented alone from S0, reproduces exactly
    for c in rnd.candidates:
        run.restore(s0)
        again = run.present(c.stimulus, seed=c.seed, episode_id=c.episode_id)
        for k in c.presentation.rates:
            assert np.array_equal(again.rates[k], c.presentation.rates[k])


@requires_real_graph
def test_selected_candidate_state_becomes_the_ongoing_state(brain, ann,
                                                            fresh_weights):
    fb, mb, _ = brain
    feed = MK.ObservationFeed(_series())
    universe = MK.Universe(SYMBOLS)
    run = _runner(brain, ann)
    rnd = run.evaluate_round(_observations(feed, universe, SYMBOLS),
                             round_index=ROUND_INDEX, round_seed=ROUND_SEED,
                             score=lambda c: c.presentation.mean("ppl1_side"))
    sel = rnd.selected
    assert sel is not None
    live = np.flatnonzero(mb.trace > 0)
    assert np.array_equal(np.sort(live), np.sort(sel.trace.index))
    assert np.all(mb.trace_episode[live] == sel.episode_id)
    assert mb.episode == sel.episode_id
    for c in rnd.candidates:
        if c.stable_id != sel.stable_id:
            assert not np.any(mb.trace_episode == c.episode_id)


@requires_real_graph
def test_ties_resolve_to_the_lowest_stable_id(brain, ann, fresh_weights):
    feed = MK.ObservationFeed(_series())
    universe = MK.Universe(SYMBOLS)
    run = _runner(brain, ann)
    rnd = run.evaluate_round(_observations(feed, universe, SYMBOLS),
                             round_index=ROUND_INDEX, round_seed=ROUND_SEED,
                             score=lambda c: 1.0)
    assert rnd.selected.stable_id == min(c.stable_id for c in rnd.candidates)
    assert rnd.selected.symbol == SYMBOLS[0]

    # the tie-break is on the id, not on the order the candidates arrive in
    rnd2 = run.evaluate_round(
        _observations(feed, universe, tuple(reversed(SYMBOLS))),
        round_index=ROUND_INDEX, round_seed=ROUND_SEED, score=lambda c: 1.0)
    assert rnd2.selected.stable_id == rnd.selected.stable_id


@requires_real_graph
def test_learned_weights_do_not_move_during_a_round(brain, ann, fresh_weights):
    """Amendment §2: no reinforcement between candidates."""
    fb, mb, _ = brain
    feed = MK.ObservationFeed(_series())
    universe = MK.Universe(SYMBOLS)
    run = _runner(brain, ann)
    before_gain = mb.gain.copy()
    before_w = fb.wdata[mb.pos].copy()
    run.evaluate_round(_observations(feed, universe, SYMBOLS),
                       round_index=ROUND_INDEX, round_seed=ROUND_SEED,
                       score=lambda c: c.presentation.mean("ppl1_side"))
    assert np.array_equal(mb.gain, before_gain)
    assert np.array_equal(fb.wdata[mb.pos], before_w)
    assert mb.events == {"reward": 0, "punish": 0, "rejected_episode": 0}


@requires_real_graph
def test_unusable_candidate_is_recorded_not_silently_dropped(brain, ann,
                                                             fresh_weights):
    series = _series()
    universe = MK.Universe(SYMBOLS)
    feed = MK.ObservationFeed(series)
    run = _runner(brain, ann)
    obs = _observations(feed, universe, SYMBOLS)
    obs[1] = feed.observe(SYMBOLS[1], 5, stable_id=universe.stable_id(SYMBOLS[1]))
    rnd = run.evaluate_round(obs, round_index=ROUND_INDEX,
                             round_seed=ROUND_SEED,
                             score=lambda c: c.presentation.mean("ppl1_side"))
    bad = rnd.by_symbol(SYMBOLS[1])
    assert len(rnd.candidates) == len(SYMBOLS)
    assert not bad.usable
    assert bad.rejected == "observation INSUFFICIENT_HISTORY"
    assert bad.presentation is None and bad.trace is None
    assert bad.stable_id not in rnd.scores
    assert rnd.selected.symbol != SYMBOLS[1]
