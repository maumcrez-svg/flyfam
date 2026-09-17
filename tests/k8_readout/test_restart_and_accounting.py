"""
D4 §7 — restart, replay and exactly-once accounting, with eight measurements.

Four points are covered, one test each:

* **interruption during the eight-measurement batch.** A batch is a pure
  function of (learned state, observation, seed schedule), so a restart
  **recomputes** it rather than resuming it, and must land on an identical
  DecisionRecord digest. Nothing is written to the log until the batch
  completes, so an interrupted round leaves no DECISION behind — only one
  ``ROUND_ABORTED``.
* **completion of a decision** and **outcome persistence** — the Phase One
  crash test's four fault points, now with a k = 8 eligibility set.
* **application of the normalised learning update** — after any of those
  crashes the weights equal exactly *one* normalised application, never zero
  and never two, and the mean-of-deltas after a restart is the mean of the same
  eight traces in the same order.
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

SYMBOLS = ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF")
ROUND_INDEX = 41
CUTOFF = 300
VALENCE, AMOUNT = -1, 0.8
OUTCOME = {"net_pnl": -12.5, "gross_pnl": -11.0, "fees": 1.5,
           "close_reason": "POLICY_CLOSE", "symbol": SYMBOLS[0]}
#: the kill point Fable addendum 7 names: replicate 3 of candidate 4
KILL_CANDIDATE, KILL_REPLICATE = 3, 3


def _versions(sha):
    return REC.Versions(market=MK.VERSION, encoder=E.VERSION, runner=R.VERSION,
                        decoder=D.VERSION, execution="flytrade-exec-1",
                        mushroom="flytrade-mb-1", graph_sha256=sha)


def _runner(brain, ann, sha):
    fb, mb, gains = brain
    return R.BrainRunner(fb, mb, E.MarketToSensoryEncoder(ann),
                         D.readout_populations(ann, mb.compartments),
                         gains=gains, graph_sha256=sha)


def _obs():
    series = {s: MK.synthetic_series(s, seed=920 + i)
              for i, s in enumerate(SYMBOLS)}
    feed = MK.ObservationFeed(series)
    uni = MK.Universe(SYMBOLS)
    return [feed.observe(s, CUTOFF, stable_id=uni.stable_id(s))
            for s in SYMBOLS]


def _record(cand, rnd, policy, versions, digest):
    return REC.decision_record(
        cand, policy.decoder.decode(cand.presentation),
        round_index=ROUND_INDEX, bar_index=CUTOFF, versions=versions,
        checkpoint_digest=digest, n_candidates=len(rnd.candidates),
        readout_policy=policy.as_dict(), wall_clock=0.0)


def _round(run, policy, select=SYMBOLS[0]):
    return run.evaluate_round(_obs(), round_index=ROUND_INDEX, readout=policy,
                              score=lambda c: 1.0 if c.symbol == select else 0.0)


# ------------------------------------------- interruption mid-batch

@requires_real_graph
def test_an_interrupted_batch_is_recomputed_to_an_identical_decision(
        tmp_path, brain, ann, fresh_weights, graph_sha256):
    fb, mb, _ = brain
    run = _runner(brain, ann, graph_sha256)
    policy = RO.policy_k8()
    versions = _versions(graph_sha256)
    journal = REC.Journal(tmp_path, mb=mb, credit=R.CreditAssigner(mb),
                          versions=versions)

    # a learned state that is not the trivial one, checkpointed
    mb.gain[:3000] = 0.8
    mb.apply()
    journal.save_checkpoint(last_settled_episode=-1)
    digest0 = journal.checkpoint_digest()

    clean = _round(run, policy)
    rec_clean = _record(clean.selected, clean, policy, versions, digest0)
    journal.record_decision(rec_clean)
    want = rec_clean.digest()

    # --- the interruption: replicate 3 of candidate 4 raises -------------
    calls = {"n": 0}
    real = run.present
    target = KILL_CANDIDATE * RO.K + KILL_REPLICATE

    def dying(*a, **kw):
        if calls["n"] == target:
            calls["n"] += 1
            raise OSError("power lost mid-batch")
        calls["n"] += 1
        return real(*a, **kw)

    run.present = dying
    before = len(journal.log.read())
    with pytest.raises(RO.TechnicalFailure) as exc:
        _round(run, policy)
    run.present = real
    assert calls["n"] == target + 1, "the batch ran past the kill point"
    journal.record_round_aborted(round_index=ROUND_INDEX, cutoff_ts=0,
                                 reason=str(exc.value),
                                 stable_id=KILL_CANDIDATE,
                                 replicate=KILL_REPLICATE)
    after = journal.log.read()
    # nothing was written for the round but the abort itself
    assert len(after) == before + 1
    assert after[-1]["kind"] == "ROUND_ABORTED"
    assert after[-1]["replicate"] == KILL_REPLICATE
    assert len([e for e in after if e["kind"] == "DECISION"]) == 1  # the clean one

    # --- restart: a fresh process, nothing in memory ---------------------
    mb.gain[:] = 0.0
    mb.apply()
    mb.trace[:] = 0.0                    # eligibility never survives a restart
    mb.trace_episode[:] = -1
    journal2 = REC.Journal(tmp_path, mb=mb, credit=R.CreditAssigner(mb),
                           versions=versions)
    report = journal2.recover()
    assert report["checkpoint_loaded"]
    assert journal2.checkpoint_digest() == digest0

    # --- recompute from scratch: the same decision, to the digest --------
    again = _round(run, policy)
    rec = _record(again.selected, again, policy, versions,
                  journal2.checkpoint_digest())
    assert rec.digest() == want
    assert again.selected.symbol == clean.selected.symbol
    assert again.state_digest == clean.state_digest
    assert [r.seed for r in again.selected.batch.replicates] == \
        [r.seed for r in clean.selected.batch.replicates]
    assert again.scores == clean.scores


# ------------------------------------------- the four fault points

@requires_real_graph
@pytest.mark.parametrize("fault", REC.FAULT_POINTS)
def test_a_k8_outcome_is_neither_lost_nor_applied_twice_across_a_crash(
        tmp_path, brain, ann, fresh_weights, graph_sha256, fault):
    fb, mb, _ = brain
    run = _runner(brain, ann, graph_sha256)
    policy = RO.policy_k8()
    versions = _versions(graph_sha256)
    rnd = _round(run, policy)
    sel = rnd.selected
    assert sel.traces.k == 8

    journal = REC.Journal(tmp_path, mb=mb, credit=R.CreditAssigner(mb),
                          versions=versions)
    journal.save_checkpoint(last_settled_episode=-1)
    before = mb.gain.copy()

    # what exactly one normalised application must produce
    g0 = before.astype(np.float64)
    dense = np.zeros(len(mb.trace), dtype=np.float64)
    deltas = []
    for t in sel.traces.traces:
        dense[:] = 0.0
        dense[t.index] = t.value
        deltas.append(mb.proposed_gain_delta(VALENCE, AMOUNT, dense,
                                             gain=g0)[0])
    expected = np.clip(g0 + np.mean(deltas, axis=0), mb.floor,
                       1.0).astype(np.float32)

    rec = _record(sel, rnd, policy, versions, journal.checkpoint_digest())
    journal.record_decision(rec)
    journal.open_episode(rec, sel.traces, {"bar_index": CUTOFF + 1})
    assert REC.read_pending(journal.pending_path)["k"] == 8

    with pytest.raises(REC.InjectedFault):
        journal.settle(sel.episode_id, OUTCOME, VALENCE, AMOUNT, fault=fault)

    # --- restart ---------------------------------------------------------
    mb.gain[:] = 0.0
    mb.apply()
    fresh = R.CreditAssigner(mb)
    journal2 = REC.Journal(tmp_path, mb=mb, credit=fresh, versions=versions)
    report = journal2.recover()
    if report["reapplied"]:
        assert report["pending_k"] == 8
        ev = fresh.settle(sel.episode_id, VALENCE, AMOUNT)
        assert ev.accepted and ev.k == 8
        assert ev.normalisation == "mean_of_deltas"
        journal2.save_checkpoint(last_settled_episode=sel.episode_id)
        REC.clear_pending(journal2.pending_path)
        journal2.log.append(REC.EventType.LEARNING,
                            {"episode_id": sel.episode_id, **ev.as_dict()})

    final = mb.gain.copy()
    assert not np.array_equal(final, before), "the outcome was lost"
    assert np.allclose(final, expected, atol=1e-6), (
        "the outcome was applied a number of times other than once")

    log = journal2.log.read()
    outs = [e for e in log if e["kind"] == "OUTCOME"
            and e["episode_id"] == sel.episode_id]
    lrn = [e for e in log if e["kind"] == "LEARNING"
           and e["episode_id"] == sel.episode_id]
    assert len(outs) == 1 and len(lrn) == 1
    assert REC.read_pending(journal2.pending_path) is None
    assert journal2.last_settled_episode == sel.episode_id

    again = fresh.settle(sel.episode_id, VALENCE, AMOUNT, trace=sel.traces)
    assert not again.accepted
    assert again.reason == R.RejectionReason.ALREADY_SETTLED.value
    assert np.array_equal(mb.gain, final)


# ------------------------------------------- the eight traces survive

@requires_real_graph
def test_the_eight_traces_survive_a_restart_in_order(tmp_path, brain, ann,
                                                     fresh_weights,
                                                     graph_sha256):
    fb, mb, _ = brain
    run = _runner(brain, ann, graph_sha256)
    policy = RO.policy_k8()
    sel = _round(run, policy).selected

    p = tmp_path / "pending.npz"
    REC.write_pending(p, episode_id=sel.episode_id, symbol=sel.symbol,
                      stable_id=sel.stable_id, trace=sel.traces,
                      decision_bar=CUTOFF, graph_sha256=graph_sha256)
    back = REC.read_pending(p, graph_sha256=graph_sha256)
    assert back["k"] == 8 and back["traces"].k == 8
    for a, b in zip(sel.traces.traces, back["traces"].traces):
        assert np.array_equal(a.index, b.index)
        assert np.array_equal(a.value, b.value)
        assert a.n_synapses == b.n_synapses

    # the update from the restored set is the update from the original set
    base = mb.gain.copy()
    c1 = R.CreditAssigner(mb)
    c1.open_episode(sel.traces)
    c1.settle(sel.episode_id, VALENCE, AMOUNT)
    from_live = mb.gain.copy()

    mb.gain[:] = base
    mb.apply()
    c2 = R.CreditAssigner(mb)
    c2.open_episode(back["traces"])
    c2.settle(sel.episode_id, VALENCE, AMOUNT)
    assert np.array_equal(mb.gain, from_live)
    assert not np.array_equal(from_live, base)

    # a pending set from another graph is still refused
    from flytrade import state as S
    with pytest.raises(S.CheckpointError, match="graph"):
        REC.read_pending(p, graph_sha256="a" * 64)
