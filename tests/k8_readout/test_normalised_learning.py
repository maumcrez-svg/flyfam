"""
D4 §4 — one normalised learning event per outcome.

    eight measurements -> one aggregate -> one decision -> at most one episode
    -> ONE outcome-linked learning event.

The canonical rule: each replicate's proposed weight delta is computed from the
**same** pre-update learning state and the same outcome, with all existing
eligibility, compartment and floor rules; the k deltas are averaged; one atomic
update is applied. Never eight sequential full-strength rewards, never the
replicate that yields the largest update.

The six invariants the amendment requires are one test each, plus the extended
A/B credit-assignment test it names: evaluate A eight times, then B eight
times, choose A, settle A.
"""
from __future__ import annotations

import numpy as np
import pytest

from flytrade import decoder as D
from flytrade import encoder as E
from flytrade import market as MK
from flytrade import mushroom as M
from flytrade import readout as RO
from flytrade import records as REC
from flytrade import runner as R

from .conftest import requires_real_graph

SYMBOLS = ("AAA", "BBB")
ROUND_INDEX = 31
CUTOFF = 300
VALENCE, AMOUNT = -1, 1.0


def _setup(brain, ann, graph_sha256):
    fb, mb, gains = brain
    enc = E.MarketToSensoryEncoder(ann)
    run = R.BrainRunner(fb, mb, enc,
                        D.readout_populations(ann, mb.compartments),
                        gains=gains, graph_sha256=graph_sha256)
    return run, R.CreditAssigner(mb)


def _round(run, ann, *, select=SYMBOLS[0], policy=None):
    policy = policy or RO.policy_k8()
    series = {s: MK.synthetic_series(s, seed=910 + i)
              for i, s in enumerate(SYMBOLS)}
    feed = MK.ObservationFeed(series)
    uni = MK.Universe(SYMBOLS)
    return run.evaluate_round(
        [feed.observe(s, CUTOFF, stable_id=uni.stable_id(s)) for s in SYMBOLS],
        round_index=ROUND_INDEX, readout=policy,
        score=lambda c: 1.0 if c.symbol == select else 0.0)


def _dense(mb, trace):
    d = np.zeros(len(mb.trace), dtype=np.float64)
    d[trace.index] = trace.value
    return d


# ------------------------------------------------ invariant 1 and vacuity

@requires_real_graph
def test_eight_identical_traces_update_exactly_as_one_does(brain, ann,
                                                           fresh_weights,
                                                           graph_sha256):
    fb, mb, _ = brain
    run, _ = _setup(brain, ann, graph_sha256)
    rnd = _round(run, ann)
    t = rnd.selected.traces.traces[0]
    ep = rnd.selected.episode_id
    assert t.n_eligible > 0

    base = mb.gain.copy()

    # one trace, the Phase One path
    one = R.CreditAssigner(mb)
    one.open_episode(t)
    ev1 = one.settle(ep, VALENCE, AMOUNT)
    after_one = mb.gain.copy()
    assert ev1.accepted and ev1.k == 1 and ev1.normalisation == "single_trace"

    # eight copies of that same trace, the k = 8 path
    mb.gain[:] = base
    mb.apply()
    eight = R.CreditAssigner(mb)
    eight.open_episode(R.StoredTraceSet.of(ep, [t] * 8))
    ev8 = eight.settle(ep, VALENCE, AMOUNT)
    after_eight = mb.gain.copy()
    assert ev8.accepted and ev8.k == 8
    assert ev8.normalisation == "mean_of_deltas"
    assert ev8.eligibility_source == "replayed_from_decision"

    assert np.allclose(after_eight, after_one, rtol=1e-12, atol=0.0)
    assert not np.array_equal(after_one, base), "nothing moved at all"

    # ... and the test is not vacuous: applying the single update eight times
    # in sequence depresses strictly further than the normalised one does
    mb.gain[:] = base
    mb.apply()
    seq = R.CreditAssigner(mb)
    for i in range(8):
        seq.open_episode(R.StoredTraceSet.of(ep + 1000 + i, [
            R.StoredTrace(episode_id=ep + 1000 + i, index=t.index,
                          value=t.value, n_synapses=t.n_synapses)]))
        seq.settle(ep + 1000 + i, VALENCE, AMOUNT)
    after_seq = mb.gain.copy()
    moved = np.flatnonzero(after_one != base)
    assert len(moved) > 0
    assert (after_seq[moved] < after_one[moved] - 1e-9).all(), (
        "eight sequential rewards must depress further than one normalised "
        "update, or the equivalence above proves nothing")


# --------------------------------------------------------- invariant 2

@requires_real_graph
def test_permuting_the_replicates_changes_nothing(brain, ann, fresh_weights,
                                                  graph_sha256):
    fb, mb, _ = brain
    run, _ = _setup(brain, ann, graph_sha256)
    rnd = _round(run, ann)
    ts = rnd.selected.traces
    ep = ts.episode_id
    assert ts.k == 8
    assert len(set(t.n_eligible for t in ts.traces)) > 1, \
        "the replicates are identical; permutation would be trivial"

    base = mb.gain.copy()
    a = R.CreditAssigner(mb)
    a.open_episode(ts)
    a.settle(ep, VALENCE, AMOUNT)
    forward = mb.gain.copy()

    for perm in ([7, 0, 3, 5, 1, 6, 2, 4], list(reversed(range(8)))):
        mb.gain[:] = base
        mb.apply()
        c = R.CreditAssigner(mb)
        c.open_episode(R.StoredTraceSet.of(ep, [ts.traces[i] for i in perm]))
        c.settle(ep, VALENCE, AMOUNT)
        assert np.array_equal(mb.gain, forward), "permutation moved the update"


# --------------------------------------------------------- invariant 3

@requires_real_graph
def test_the_unselected_candidate_contributes_nothing(brain, ann,
                                                      fresh_weights,
                                                      graph_sha256):
    fb, mb, _ = brain
    run, _ = _setup(brain, ann, graph_sha256)
    rnd = _round(run, ann, select=SYMBOLS[0])
    a, b = rnd.by_symbol(SYMBOLS[0]), rnd.by_symbol(SYMBOLS[1])
    assert rnd.selected is a

    only_b = np.setdiff1d(
        np.unique(np.concatenate([t.index for t in b.traces.traces])),
        np.unique(np.concatenate([t.index for t in a.traces.traces])))
    assert len(only_b) > 0

    base = mb.gain.copy()
    credit = R.CreditAssigner(mb)
    credit.open_episode(a.traces)
    ev = credit.settle(a.episode_id, VALENCE, AMOUNT)
    assert ev.accepted

    moved = np.flatnonzero(mb.gain != base)
    assert len(moved) == ev.synapses_depressed > 0
    assert not (set(int(i) for i in only_b) & set(int(i) for i in moved))
    # exactly A's own eligible synapses on the addressed side, over all eight
    union = np.unique(np.concatenate([t.index for t in a.traces.traces]))
    expected = union[mb.side[union] == VALENCE]
    assert np.array_equal(np.sort(moved), np.sort(expected))
    assert (mb.side[moved] == VALENCE).all()


# --------------------------------------------------------- invariant 4

@requires_real_graph
def test_a_rejected_or_ineligible_trace_set_cannot_move_a_weight(
        brain, ann, fresh_weights, graph_sha256):
    fb, mb, _ = brain
    run, _ = _setup(brain, ann, graph_sha256)
    rnd = _round(run, ann)
    a, b = rnd.by_symbol(SYMBOLS[0]), rnd.by_symbol(SYMBOLS[1])
    credit = R.CreditAssigner(mb)
    credit.open_episode(a.traces)
    base = mb.gain.copy()

    ev = credit.settle(a.episode_id, VALENCE, AMOUNT, trace=b.traces)
    assert ev.reason == R.RejectionReason.EPISODE_MISMATCH.value
    assert ev.k == 8 and np.array_equal(mb.gain, base)

    ev = credit.settle(b.episode_id, VALENCE, AMOUNT)
    assert ev.reason == R.RejectionReason.UNKNOWN_EPISODE.value
    assert np.array_equal(mb.gain, base)

    expired = R.StoredTraceSet.of(a.episode_id, [
        R.StoredTrace(episode_id=a.episode_id, index=t.index,
                      value=t.value * (M.TRACE_EPS / 2.0),
                      n_synapses=t.n_synapses) for t in a.traces.traces])
    ev = credit.settle(a.episode_id, VALENCE, AMOUNT, trace=expired)
    assert ev.reason == R.RejectionReason.TRACE_EXPIRED.value
    assert np.array_equal(mb.gain, base)

    wrong = R.StoredTraceSet.of(a.episode_id, [
        R.StoredTrace(episode_id=a.episode_id, index=t.index, value=t.value,
                      n_synapses=7) for t in a.traces.traces])
    ev = credit.settle(a.episode_id, VALENCE, AMOUNT, trace=wrong)
    assert ev.reason == R.RejectionReason.SHAPE_MISMATCH.value
    assert np.array_equal(mb.gain, base)

    assert credit.stats()["accepted"] == 0
    assert credit.stats()["rejections_total"] == 4


# ---------------------------------------------------- invariants 5 and 6

@requires_real_graph
def test_one_outcome_counts_once_and_a_duplicate_moves_nothing(
        brain, ann, fresh_weights, graph_sha256):
    fb, mb, _ = brain
    run, _ = _setup(brain, ann, graph_sha256)
    rnd = _round(run, ann)
    a = rnd.selected
    credit = R.CreditAssigner(mb)
    credit.open_episode(a.traces)

    ev = credit.settle(a.episode_id, VALENCE, AMOUNT)
    assert ev.accepted
    after = mb.gain.copy()
    assert credit.accepted == 1
    assert len([e for e in credit.events if e.accepted]) == 1

    for _ in range(3):
        again = credit.settle(a.episode_id, VALENCE, AMOUNT, trace=a.traces)
        assert not again.accepted
        assert again.reason == R.RejectionReason.ALREADY_SETTLED.value
    assert np.array_equal(mb.gain, after)
    assert credit.accepted == 1
    assert credit.stats()["rejections"][
        R.RejectionReason.ALREADY_SETTLED.value] == 3


# ------------------------------------------- the rule, not just the result

@requires_real_graph
def test_the_update_is_the_mean_of_the_eight_proposals_from_one_pre_state(
        brain, ann, fresh_weights, graph_sha256):
    fb, mb, _ = brain
    run, _ = _setup(brain, ann, graph_sha256)
    rnd = _round(run, ann)
    ts = rnd.selected.traces
    g0 = mb.gain.astype(np.float64)

    deltas = []
    for t in ts.traces:
        d, _ = mb.proposed_gain_delta(VALENCE, AMOUNT, _dense(mb, t), gain=g0)
        deltas.append(d)
    expected = g0 + np.mean(deltas, axis=0)

    credit = R.CreditAssigner(mb)
    credit.open_episode(ts)
    ev = credit.settle(ts.episode_id, VALENCE, AMOUNT)
    assert np.allclose(mb.gain, expected.astype(np.float32), rtol=1e-12)

    # never the largest-update replicate, and never the smallest
    per = [float(d.sum()) for d in deltas]
    total = float(np.mean(deltas, axis=0).sum())
    assert min(per) < total < max(per)
    assert len(set(ev.depressed_per_replicate)) > 1
    assert ev.synapses_depressed >= max(ev.depressed_per_replicate)
    # the learned change reached the weights the simulator reads
    assert np.array_equal(fb.wdata[mb.pos], mb.base * mb.gain)


@requires_real_graph
def test_the_floor_is_applied_per_replicate_before_averaging(brain, ann,
                                                             fresh_weights,
                                                             graph_sha256):
    """A declared modelling convention (Fable addendum 6), asserted as one."""
    fb, mb, _ = brain
    run, _ = _setup(brain, ann, graph_sha256)
    rnd = _round(run, ann)
    ts = rnd.selected.traces
    # drive the update hard enough that per-replicate proposals hit the floor
    mb.gain[:] = mb.floor + 1e-3
    mb.apply()
    g0 = mb.gain.astype(np.float64)
    per = [mb.proposed_gain_delta(VALENCE, 1.0, _dense(mb, t), gain=g0)[0]
           for t in ts.traces]
    floored = [(g0 + d) for d in per]
    assert min(float(f.min()) for f in floored) >= mb.floor - 1e-12

    credit = R.CreditAssigner(mb)
    credit.open_episode(ts)
    credit.settle(ts.episode_id, VALENCE, 1.0)
    assert np.allclose(mb.gain, np.mean(floored, axis=0).astype(np.float32),
                       rtol=1e-12)
    assert float(mb.gain.min()) >= mb.floor - 1e-6


# --------------------------------- the A/B test the amendment names

@requires_real_graph
def test_evaluate_a_eight_times_then_b_eight_times_select_a_settle_a(
        tmp_path, brain, ann, fresh_weights, graph_sha256):
    """D4 §4: only eligible contributions from A may be applied."""
    fb, mb, _ = brain
    run, _ = _setup(brain, ann, graph_sha256)
    policy = RO.policy_k8()
    rnd = _round(run, ann, select=SYMBOLS[0], policy=policy)
    a, b = rnd.by_symbol(SYMBOLS[0]), rnd.by_symbol(SYMBOLS[1])

    assert rnd.selected is a
    assert a.k == b.k == 8
    assert run.presentations == 16
    assert a.episode_id != b.episode_id
    a_union = np.unique(np.concatenate([t.index for t in a.traces.traces]))
    b_union = np.unique(np.concatenate([t.index for t in b.traces.traces]))
    only_b = np.setdiff1d(b_union, a_union)
    assert len(only_b) > 0

    # the eligibility survives a restart as a set of eight, in order
    credit = R.CreditAssigner(mb)
    versions = REC.Versions(market=MK.VERSION, encoder=E.VERSION,
                            runner=R.VERSION, decoder=D.VERSION,
                            execution="flytrade-exec-1",
                            mushroom="flytrade-mb-1",
                            graph_sha256=graph_sha256)
    journal = REC.Journal(tmp_path, mb=mb, credit=credit, versions=versions)
    journal.save_checkpoint(last_settled_episode=-1)
    rec = REC.decision_record(a, policy.decoder.decode(a.presentation),
                              round_index=ROUND_INDEX, bar_index=CUTOFF,
                              versions=versions,
                              checkpoint_digest=journal.checkpoint_digest(),
                              n_candidates=2, readout_policy=policy.as_dict())
    journal.record_decision(rec)
    journal.open_episode(rec, a.traces, {"bar_index": CUTOFF + 1})
    back = REC.read_pending(journal.pending_path, graph_sha256=graph_sha256)
    assert back["k"] == 8
    assert [t.n_eligible for t in back["traces"].traces] == \
        [t.n_eligible for t in a.traces.traces]

    base = mb.gain.copy()
    ev = journal.settle(a.episode_id, {"net_pnl": -3.0}, VALENCE, AMOUNT)
    assert ev.accepted and ev.k == 8 and ev.normalisation == "mean_of_deltas"

    moved = np.flatnonzero(mb.gain != base)
    expected = a_union[mb.side[a_union] == VALENCE]
    assert np.array_equal(np.sort(moved), np.sort(expected))
    assert not (set(int(i) for i in only_b) & set(int(i) for i in moved))
    assert (mb.side[moved] == VALENCE).all()

    log = journal.log.read()
    assert len([e for e in log if e["kind"] == "OUTCOME"]) == 1
    lrn = [e for e in log if e["kind"] == "LEARNING"]
    assert len(lrn) == 1
    assert lrn[0]["k"] == 8
    assert lrn[0]["normalisation"] == "mean_of_deltas"
    assert len(lrn[0]["depressed_per_replicate"]) == 8
    assert rec.k == 8 and len(rec.replicates) == 8
    assert rec.traces["k"] == 8
