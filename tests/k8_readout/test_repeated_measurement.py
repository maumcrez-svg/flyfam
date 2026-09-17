"""
D4 §1 — repeated measurement semantics.

Eight presentations of one candidate, from equivalent transient states, under
one frozen learned state, on a declared reproducible schedule. The properties
asserted here are the ones §1 states as requirements, one test each:

* k is fixed — never increased for a difficult observation, never stopped early
  after a desirable response, never retried until something appears;
* the replicate streams are distinct and reproducible, and the schedule is a
  function of (learned state, observation content, stable id, replicate index)
  and of nothing else;
* every replicate starts from an equivalent copy of the declared transient
  state, so neither electrical state nor eligibility crosses between them;
* the eligibility decay acts once per round, not once per presentation;
* no learned weight moves during the batch.
"""
from __future__ import annotations

import numpy as np
import pytest

from flytrade import decoder as D
from flytrade import encoder as E
from flytrade import market as MK
from flytrade import mushroom as M
from flytrade import readout as RO
from flytrade import runner as R

from .conftest import requires_real_graph

SYMBOLS = ("ALFA", "BETA", "GAMA", "DLTA", "EPSI", "ZETA")
ROUND_INDEX = 12
CUTOFF = 260


def _series(symbols=SYMBOLS):
    return {s: MK.synthetic_series(s, seed=200 + i)
            for i, s in enumerate(symbols)}


def _runner(brain, ann, graph_sha256):
    fb, mb, gains = brain
    enc = E.MarketToSensoryEncoder(ann)
    return R.BrainRunner(fb, mb, enc,
                         D.readout_populations(ann, mb.compartments),
                         gains=gains, graph_sha256=graph_sha256)


def _obs(feed, universe, symbols=SYMBOLS, cutoff=CUTOFF):
    return [feed.observe(s, cutoff, stable_id=universe.stable_id(s))
            for s in symbols]


# ------------------------------------------------------------ the schedule

def test_the_replicate_seed_depends_on_the_declared_tuple_and_nothing_else():
    a = RO.replicate_seed(RO.ROUND_NAMESPACE, "dig", "obs", 3, 0)
    assert a == RO.replicate_seed(RO.ROUND_NAMESPACE, "dig", "obs", 3, 0)
    # every component of the tuple changes it
    assert a != RO.replicate_seed(RO.ROUND_NAMESPACE, "dig", "obs", 3, 1)
    assert a != RO.replicate_seed(RO.ROUND_NAMESPACE, "dig", "obs", 4, 0)
    assert a != RO.replicate_seed(RO.ROUND_NAMESPACE, "dig", "other", 3, 0)
    assert a != RO.replicate_seed(RO.ROUND_NAMESPACE, "other", "obs", 3, 0)
    # the namespaces are disjoint schedules, not decoration
    assert a != RO.replicate_seed(RO.BASELINE_NAMESPACE, "dig", "obs", 3, 0)
    assert a != RO.replicate_seed(RO.EVAL_NAMESPACE, "dig", "obs", 3, 0)
    assert 0 <= a < 2 ** RO.SEED_BITS


def test_k1_is_replicate_zero_of_the_k8_schedule_not_a_separate_run():
    eight = RO.ReadoutPolicy(k=8).seeds("dig", "obs", 5)
    one = RO.ReadoutPolicy.k1().seeds("dig", "obs", 5)
    assert len(eight) == 8 and len(set(eight)) == 8
    assert one == eight[:1]


@requires_real_graph
def test_the_observation_id_is_content_not_spelling(ann):
    series = _series(("AAA", "BBB"))
    feed = MK.ObservationFeed(series)
    uni = MK.Universe(("AAA", "BBB"))
    a = feed.observe("AAA", CUTOFF, stable_id=0)
    renamed = {"Z-9": MK.Series("Z-9", series["AAA"].bars,
                                series["AAA"].interval_s)}
    b = MK.ObservationFeed(renamed).observe("Z-9", CUTOFF, stable_id=0)
    assert a.symbol != b.symbol
    assert RO.observation_id(a) == RO.observation_id(b)
    # a different bar is a different observation
    c = feed.observe("AAA", CUTOFF + 1, stable_id=0)
    assert RO.observation_id(a) != RO.observation_id(c)
    # and so is a different instrument's bar
    d = feed.observe("BBB", CUTOFF, stable_id=1)
    assert RO.observation_id(a) != RO.observation_id(d)


# ------------------------------------------------------------- the batch

@requires_real_graph
def test_eight_presentations_happen_and_exactly_eight(brain, ann, fresh_weights,
                                                      graph_sha256):
    fb, mb, _ = brain
    run = _runner(brain, ann, graph_sha256)
    feed = MK.ObservationFeed(_series())
    uni = MK.Universe(SYMBOLS)
    policy = RO.ReadoutPolicy(k=RO.K)

    before = run.presentations
    rnd = run.evaluate_round(_obs(feed, uni), round_index=ROUND_INDEX,
                             score=policy.score, readout=policy)
    usable = [c for c in rnd.candidates if c.usable]
    assert usable, "the fixture produced no usable candidate"
    assert run.presentations - before == RO.K * len(usable)

    for c in usable:
        b = c.batch
        assert b.k == RO.K
        assert len(b.replicates) == RO.K
        assert len(b.traces.traces) == RO.K
        assert [r.index for r in b.replicates] == list(range(RO.K))
        assert len(set(r.seed for r in b.replicates)) == RO.K
        assert b.aggregate.k == RO.K


@requires_real_graph
def test_a_silent_replicate_is_kept_and_the_batch_is_not_extended(
        brain, ann, fresh_weights, graph_sha256):
    """A technically successful silent presentation contributes its zeros."""
    fb, mb, _ = brain
    run = _runner(brain, ann, graph_sha256)
    enc = run.encoder
    policy = RO.ReadoutPolicy(k=RO.K)
    # a deliberately weak stimulus: the flattest point of the declared range
    stim = enc.encode_features((0.0,) * len(MK.FEATURES), symbol="neutral",
                               stable_id=0)
    b = policy.measure(run, stim, episode_id=1,
                       state_dig=run.state_digest(),
                       obs_id=RO.features_id((0.0,) * len(MK.FEATURES),
                                             label="neutral"))
    assert len(b.replicates) == RO.K          # never extended, never retried
    # every replicate's counts are in the aggregate, silent ones included
    app = np.mean([r.presentation.mean(D.APPROACH) for r in b.replicates])
    assert b.aggregate.mean(D.APPROACH) == pytest.approx(app, rel=1e-12)


@requires_real_graph
def test_every_replicate_starts_from_an_equivalent_transient_state(
        brain, ann, fresh_weights, graph_sha256):
    fb, mb, _ = brain
    run = _runner(brain, ann, graph_sha256)
    policy = RO.ReadoutPolicy(k=RO.K)
    feed = MK.ObservationFeed(_series())
    uni = MK.Universe(SYMBOLS)
    obs = _obs(feed, uni)[0]
    stim = run.encoder.encode(obs)

    # dirty the eligibility layer, exactly as a previous episode would leave it
    mb.trace[:500] = 1.0
    mb.trace_episode[:500] = -99
    s0 = run.snapshot()
    ep = R.episode_id_for(ROUND_INDEX, obs.stable_id)
    b = policy.measure(run, stim, episode_id=ep, state_dig=run.state_digest(),
                       obs_id=RO.observation_id(obs), snapshot=s0)

    for rep in b.replicates:
        run.restore(s0)
        solo = run.present(stim, seed=rep.seed, episode_id=ep)
        solo_trace = run.capture_trace(ep)
        for name in rep.presentation.rates:
            assert np.array_equal(rep.presentation.rates[name],
                                  solo.rates[name])
        assert np.array_equal(rep.trace.index, solo_trace.index)
        assert np.array_equal(rep.trace.value, solo_trace.value)
    run.restore(s0)
    # the dirty trace is still S0's afterwards: the batch left no residue
    assert np.array_equal(mb.trace, s0.trace)
    assert np.array_equal(mb.trace_episode, s0.trace_episode)


@requires_real_graph
def test_the_eligibility_decay_acts_once_per_round_not_once_per_presentation(
        brain, ann, fresh_weights, graph_sha256):
    """Addendum 3: the experiment clock advances per round, not per replicate."""
    fb, mb, _ = brain
    run = _runner(brain, ann, graph_sha256)
    policy = RO.ReadoutPolicy(k=RO.K)
    feed = MK.ObservationFeed(_series())
    uni = MK.Universe(SYMBOLS)
    obs = _obs(feed, uni)[0]
    stim = run.encoder.encode(obs)

    mb.trace[:] = 1.0
    mb.trace_episode[:] = -99
    s0 = run.snapshot()
    ep = R.episode_id_for(ROUND_INDEX, obs.stable_id)
    b = policy.measure(run, stim, episode_id=ep, state_dig=run.state_digest(),
                       obs_id=RO.observation_id(obs), snapshot=s0)

    # after the batch the live layer is S0 again; during it, each replicate saw
    # exactly one decay of S0 rather than the r-th power of it
    run.restore(s0)
    run.present(stim, seed=b.replicates[-1].seed, episode_id=ep)
    once = mb.trace.copy()
    run.restore(s0)
    # eight decays in a row would leave the untouched synapses at 0.55**8
    eight = s0.trace * (mb.trace_decay ** RO.K)
    untouched = np.flatnonzero(once < 1.0)
    assert len(untouched) > 0
    assert np.allclose(once[untouched],
                       s0.trace[untouched] * mb.trace_decay, atol=1e-6)
    assert not np.allclose(once[untouched], eight[untouched], atol=1e-6)


@requires_real_graph
def test_no_learned_weight_moves_during_a_batch(brain, ann, fresh_weights,
                                                graph_sha256):
    fb, mb, _ = brain
    run = _runner(brain, ann, graph_sha256)
    policy = RO.ReadoutPolicy(k=RO.K)
    feed = MK.ObservationFeed(_series())
    uni = MK.Universe(SYMBOLS)
    before_gain, before_w = mb.gain.copy(), fb.wdata[mb.pos].copy()
    before_events = dict(mb.events)
    rnd = run.evaluate_round(_obs(feed, uni), round_index=ROUND_INDEX,
                             score=policy.score, readout=policy)
    assert np.array_equal(mb.gain, before_gain)
    assert np.array_equal(fb.wdata[mb.pos], before_w)
    assert mb.events == before_events
    # and every candidate was measured under the same learned-state version
    assert rnd.state_digest == run.state_digest()
    for c in rnd.candidates:
        if c.batch is not None:
            assert c.batch.state_digest == rnd.state_digest


@requires_real_graph
def test_a_batch_is_reproducible_from_its_declared_inputs(brain, ann,
                                                          fresh_weights,
                                                          graph_sha256):
    """Addendum 7: a batch is a pure function of (state, observation, schedule)."""
    fb, mb, _ = brain
    run = _runner(brain, ann, graph_sha256)
    policy = RO.ReadoutPolicy(k=RO.K)
    feed = MK.ObservationFeed(_series())
    uni = MK.Universe(SYMBOLS)
    obs = _obs(feed, uni)[0]
    stim = run.encoder.encode(obs)
    ep = R.episode_id_for(ROUND_INDEX, obs.stable_id)
    kw = dict(episode_id=ep, state_dig=run.state_digest(),
              obs_id=RO.observation_id(obs))

    a = policy.measure(run, stim, **kw)
    # something else happens in between, including a different candidate
    other = run.encoder.encode(_obs(feed, uni)[2])
    policy.measure(run, other, episode_id=ep + 1,
                   state_dig=run.state_digest(),
                   obs_id=RO.observation_id(_obs(feed, uni)[2]))
    b = policy.measure(run, stim, **kw)

    assert [r.seed for r in a.replicates] == [r.seed for r in b.replicates]
    for x, y in zip(a.replicates, b.replicates):
        for name in x.presentation.rates:
            assert np.array_equal(x.presentation.rates[name],
                                  y.presentation.rates[name])
        assert np.array_equal(x.trace.index, y.trace.index)


@requires_real_graph
def test_a_different_learned_state_is_a_different_schedule(brain, ann,
                                                           fresh_weights,
                                                           graph_sha256):
    fb, mb, _ = brain
    run = _runner(brain, ann, graph_sha256)
    policy = RO.ReadoutPolicy(k=RO.K)
    before = policy.seeds(run.state_digest(), "obs", 0)
    mb.gain[:100] = 0.5
    mb.apply()
    after = policy.seeds(run.state_digest(), "obs", 0)
    assert before != after
