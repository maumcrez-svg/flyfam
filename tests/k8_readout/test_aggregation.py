"""
D4 §2 — aggregation before decoding, and the four statuses.

The aggregate is fed to the **unmodified** decoder through an aggregate
presentation whose rates are the per-neuron mean over the replicates and whose
Kenyon fraction and peak rate are maxima, so the decoder's own rule order
produces Fable addendum 4's status rules exactly:

* INVALID in any replicate  -> aggregate INVALID, nothing averaged;
* silent in every replicate -> aggregate NO_RESPONSE;
* otherwise VALID, and WAIT iff |V| <= theta.

What is asserted here is that no other rule crept in: no majority vote of eight
labels, no strongest replicate, no discarding of a silent trial, no averaging of
only the technically successful subset, and a technical failure aborting the
round instead of becoming a readout status.
"""
from __future__ import annotations

import numpy as np
import pytest

from flytrade import decoder as D
from flytrade import encoder as E
from flytrade import market as MK
from flytrade import readout as RO
from flytrade import records as REC
from flytrade import runner as R

from .conftest import requires_real_graph

SYMBOLS = ("ALFA", "BETA", "GAMA", "DLTA")
ROUND_INDEX = 21
CUTOFF = 260


def _series(symbols=SYMBOLS, seeds=None):
    seeds = seeds or [200 + i for i in range(len(symbols))]
    return {s: MK.synthetic_series(s, seed=seeds[i])
            for i, s in enumerate(symbols)}


def _runner(brain, ann, graph_sha256):
    fb, mb, gains = brain
    return R.BrainRunner(fb, mb, E.MarketToSensoryEncoder(ann),
                         D.readout_populations(ann, mb.compartments),
                         gains=gains, graph_sha256=graph_sha256)


def _obs(feed, uni, symbols=SYMBOLS, cutoff=CUTOFF):
    return [feed.observe(s, cutoff, stable_id=uni.stable_id(s))
            for s in symbols]


def _fake_presentation(app_hz, avo_hz, *, kc=0.01, seed=1, ep=1,
                       n_app=16, n_avo=29):
    return R.Presentation(
        symbol="X", stable_id=0, episode_id=ep, seed=seed, steps=100,
        rates={D.APPROACH: np.full(n_app, float(app_hz)),
               D.AVOID: np.full(n_avo, float(avo_hz))},
        kc_fraction=float(kc), kc_active=int(kc * 4064),
        max_rate_hz=float(max(app_hz, avo_hz)))


def _batch_of(pairs, dec=None, **kw):
    """A Batch assembled from (approach_hz, avoid_hz) pairs, no simulation."""
    dec = dec or D.ActionDecoder()
    reps = []
    for i, (a, b) in enumerate(pairs):
        pres = _fake_presentation(a, b, seed=100 + i, **kw)
        d = dec.decode(pres)
        reps.append(RO.Replicate(index=i, seed=100 + i, presentation=pres,
                                 trace=R.StoredTrace(
                                     episode_id=1,
                                     index=np.array([], dtype=np.int64),
                                     value=np.array([], dtype=np.float32),
                                     n_synapses=10),
                                 action=d.action.value, status=d.status.value,
                                 score_hz=d.valence_hz))
    stim = type("S", (), {"symbol": "X", "stable_id": 0})()
    return RO.Batch(
        stable_id=0, episode_id=1, k=len(reps), namespace="t",
        state_digest="d", observation_id="o", replicates=tuple(reps),
        aggregate=RO.aggregate_presentation(stim, reps, episode_id=1,
                                            k=len(reps)),
        traces=R.StoredTraceSet.of(1, [r.trace for r in reps]))


# --------------------------------------------------- the aggregate rules

def test_the_decoder_is_applied_once_to_the_mean_never_to_a_vote():
    """Eight labels that are mostly BUY still decode to what the mean says."""
    dec = D.ActionDecoder()
    # six replicates just over the BUY margin, two far below: the mean is SELL
    pairs = [(10.0, 6.0)] * 6 + [(0.0, 60.0)] * 2
    b = _batch_of(pairs, dec=dec)
    per_replicate = [r.action for r in b.replicates]
    assert per_replicate.count("BUY") == 6        # a vote would say BUY
    d = dec.decode(b.aggregate)
    app = float(np.mean([a for a, _ in pairs]))
    avo = float(np.mean([x for _, x in pairs]))
    assert d.approach_hz == pytest.approx(app, rel=1e-12)
    assert d.avoid_hz == pytest.approx(avo, rel=1e-12)
    assert d.action is D.Action.SELL
    # and it is not the most favourable replicate either
    assert d.valence_hz < max(r.score_hz for r in b.replicates)


def test_a_silent_replicate_contributes_its_zeros_and_is_not_discarded():
    dec = D.ActionDecoder()
    active = [(40.0, 10.0)] * 4
    b_all = _batch_of(active + [(0.0, 0.0)] * 4, dec=dec)
    b_subset = _batch_of(active, dec=dec)
    assert b_all.silent_replicates == 4
    assert dec.decode(b_all.aggregate).approach_hz == pytest.approx(20.0)
    assert dec.decode(b_subset.aggregate).approach_hz == pytest.approx(40.0)
    # averaging only the successful subset would double the reported response
    assert dec.decode(b_all.aggregate).status is D.ReadoutStatus.VALID


def test_no_response_iff_every_replicate_was_silent():
    dec = D.ActionDecoder()
    all_silent = _batch_of([(0.0, 0.0)] * 8, dec=dec)
    assert dec.decode(all_silent.aggregate).status is D.ReadoutStatus.NO_RESPONSE
    assert all_silent.silent_replicates == 8
    one_active = _batch_of([(0.0, 0.0)] * 7 + [(3.125, 0.0)], dec=dec)
    d = dec.decode(one_active.aggregate)
    assert d.status is D.ReadoutStatus.VALID
    assert one_active.silent_replicates == 7


def test_saturation_in_one_replicate_is_not_averaged_away():
    dec = D.ActionDecoder()
    quiet = [(10.0, 8.0)] * 7
    hot = [(0.99 * D.REFRACTORY_CEILING_HZ, 8.0)]
    b = _batch_of(quiet + hot, dec=dec)
    assert b.aggregate.max_rate_hz >= D.SATURATED_HZ      # max, not mean
    d = dec.decode(b.aggregate)
    assert d.status is D.ReadoutStatus.INVALID_STATE
    assert d.action is D.Action.NO_RESPONSE
    assert b.invalid_replicates == 1
    # the quiet seven alone are a perfectly valid batch
    assert dec.decode(_batch_of(quiet, dec=dec).aggregate).status \
        is D.ReadoutStatus.VALID


def test_over_recruitment_in_one_replicate_makes_the_aggregate_invalid():
    dec = D.ActionDecoder()
    b = _batch_of([(10.0, 8.0)] * 7 + [(10.0, 8.0)],
                  dec=dec, kc=0.01)
    assert dec.decode(b.aggregate).status is D.ReadoutStatus.VALID
    reps = list(b.replicates)
    hot = _fake_presentation(10.0, 8.0, kc=0.40, seed=999)
    d_hot = dec.decode(hot)
    reps[3] = RO.Replicate(index=3, seed=999, presentation=hot,
                           trace=reps[3].trace, action=d_hot.action.value,
                           status=d_hot.status.value,
                           score_hz=d_hot.valence_hz)
    stim = type("S", (), {"symbol": "X", "stable_id": 0})()
    agg = RO.aggregate_presentation(stim, reps, episode_id=1, k=8)
    assert agg.kc_fraction == pytest.approx(0.40)         # max
    assert agg.kc_fraction_mean < 0.10                    # mean, reported
    assert dec.decode(agg).status is D.ReadoutStatus.INVALID_STATE


def test_wait_is_reported_separately_from_no_response():
    dec = D.ActionDecoder()
    wait = _batch_of([(10.0, 12.0)] * 8, dec=dec)        # V near the baseline
    d = dec.decode(wait.aggregate)
    assert d.status is D.ReadoutStatus.VALID and d.action is D.Action.WAIT
    silent = _batch_of([(0.0, 0.0)] * 8, dec=dec)
    ds = dec.decode(silent.aggregate)
    assert ds.status is D.ReadoutStatus.NO_RESPONSE
    assert ds.action is D.Action.NO_RESPONSE and not ds.is_decision
    assert d.status is not ds.status


# ------------------------------------------------------ technical failure

@requires_real_graph
def test_a_replicate_that_raises_aborts_the_round(tmp_path, brain, ann,
                                                  fresh_weights, graph_sha256):
    fb, mb, _ = brain
    run = _runner(brain, ann, graph_sha256)
    policy = RO.ReadoutPolicy(k=RO.K)
    feed = MK.ObservationFeed(_series())
    uni = MK.Universe(SYMBOLS)

    calls = {"n": 0}
    real = run.present

    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 11:                 # replicate 2 of candidate 2
            raise MemoryError("simulated allocation failure")
        return real(*a, **kw)

    run.present = flaky
    with pytest.raises(RO.TechnicalFailure) as exc:
        run.evaluate_round(_obs(feed, uni), round_index=ROUND_INDEX,
                           score=policy.score, readout=policy)
    assert "MemoryError" in str(exc.value)
    run.present = real

    journal = REC.Journal(
        tmp_path, mb=mb, credit=R.CreditAssigner(mb),
        versions=REC.Versions(market=MK.VERSION, encoder=E.VERSION,
                              runner=R.VERSION, decoder=D.VERSION,
                              execution="flytrade-exec-1",
                              mushroom="flytrade-mb-1",
                              graph_sha256=graph_sha256))
    journal.record_round_aborted(round_index=ROUND_INDEX, cutoff_ts=1,
                                 reason=str(exc.value), stable_id=1,
                                 replicate=2)
    log = journal.log.read()
    kinds = [e["kind"] for e in log]
    assert kinds.count("ROUND_ABORTED") == 1
    assert "DECISION" not in kinds           # no decision came out of it
    assert log[-1]["replicate"] == 2


# ------------------------------------------- permutation and renaming

def _digest_of_round(run, policy, dec, feed, uni, symbols, versions,
                     graph_sha256):
    rnd = run.evaluate_round(_obs(feed, uni, symbols),
                             round_index=ROUND_INDEX, score=policy.score,
                             readout=policy)
    out = {}
    for c in rnd.candidates:
        d = dec.decode(c.presentation) if c.presentation else None
        if d is None:
            continue
        rec = REC.decision_record(
            c, d, round_index=ROUND_INDEX, bar_index=CUTOFF,
            versions=versions, checkpoint_digest="ck",
            n_candidates=len(rnd.candidates),
            readout_policy=policy.as_dict(), wall_clock=0.0,
            selected=rnd.selected is not None
            and c.stable_id == rnd.selected.stable_id)
        out[c.stable_id] = rec.digest()
    return out, rnd


@requires_real_graph
def test_permuting_candidates_and_renaming_tickers_keeps_the_decision_digest(
        brain, ann, fresh_weights, graph_sha256):
    """Fable addendum 2, in one test, on the DecisionRecord digest itself."""
    fb, mb, _ = brain
    run = _runner(brain, ann, graph_sha256)
    policy = RO.ReadoutPolicy(k=RO.K)
    dec = policy.decoder
    versions = REC.Versions(market=MK.VERSION, encoder=E.VERSION,
                            runner=R.VERSION, decoder=D.VERSION,
                            execution="flytrade-exec-1",
                            mushroom="flytrade-mb-1",
                            graph_sha256=graph_sha256)
    series = _series()
    uni = MK.Universe(SYMBOLS)
    before, rnd_a = _digest_of_round(run, policy, dec,
                                     MK.ObservationFeed(series), uni, SYMBOLS,
                                     versions, graph_sha256)

    new = {"ALFA": "ZZ9", "BETA": "A", "GAMA": "0000000000", "DLTA": "z-z"}
    renamed = {new[k]: MK.Series(new[k], v.bars, v.interval_s)
               for k, v in series.items()}
    for old, fresh in new.items():
        uni.rename(old, fresh)
    order = tuple(new[s] for s in reversed(SYMBOLS))       # and permuted
    after, rnd_b = _digest_of_round(run, policy, dec,
                                    MK.ObservationFeed(renamed), uni, order,
                                    versions, graph_sha256)

    assert before and before == after
    assert rnd_a.scores == rnd_b.scores
    assert new[rnd_a.selected.symbol] == rnd_b.selected.symbol
    # the digest is not vacuous: a different learned state changes it
    mb.gain[:200] = 0.5
    mb.apply()
    changed, _ = _digest_of_round(run, policy, dec,
                                  MK.ObservationFeed(renamed), uni, order,
                                  versions, graph_sha256)
    assert changed != after


# -------------------------------------------------- the k = 1 mode

@requires_real_graph
def test_k1_mode_is_replicate_zero_of_the_same_batch(brain, ann, fresh_weights,
                                                     graph_sha256):
    fb, mb, _ = brain
    run = _runner(brain, ann, graph_sha256)
    feed = MK.ObservationFeed(_series())
    uni = MK.Universe(SYMBOLS)
    eight = RO.ReadoutPolicy(k=8)
    one = RO.ReadoutPolicy.k1()

    r8 = run.evaluate_round(_obs(feed, uni), round_index=ROUND_INDEX,
                            score=eight.score, readout=eight)
    r1 = run.evaluate_round(_obs(feed, uni), round_index=ROUND_INDEX,
                            score=one.score, readout=one)
    for c8, c1 in zip(r8.candidates, r1.candidates):
        if c8.batch is None:
            continue
        assert c1.batch.k == 1
        assert c1.batch.replicates[0].seed == c8.batch.replicates[0].seed
        for name in c1.presentation.rates:
            assert np.array_equal(
                c1.presentation.rates[name],
                c8.batch.replicates[0].presentation.rates[name])
