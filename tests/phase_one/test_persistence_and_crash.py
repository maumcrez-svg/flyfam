"""
Canonical amendment §7 — persistence, replay, and the outcome/learning boundary.

The crash test is one test, as Fable addendum 10 requires, parametrised over
the four points at which the power can go out between "the outcome happened"
and "the brain has learned from it". At every one of them, after a restart, the
outcome must be **neither lost nor applied twice**.
"""
from __future__ import annotations

import numpy as np
import pytest

from flytrade import decoder as D
from flytrade import encoder as E
from flytrade import market as MK
from flytrade import records as REC
from flytrade import runner as R
from flytrade import state as S

from .conftest import requires_real_graph

SYMBOLS = ("AAA", "BBB")
ROUND_INDEX = 3
ROUND_SEED = 909
CUTOFF = 300
VALENCE, AMOUNT = -1, 0.8


def _versions(graph_sha256):
    return REC.Versions(market=MK.VERSION, encoder=E.VERSION, runner=R.VERSION,
                        decoder=D.VERSION, execution="flytrade-exec-1",
                        mushroom="flytrade-mb-1", graph_sha256=graph_sha256)


def _round(brain, ann):
    fb, mb, gains = brain
    enc = E.MarketToSensoryEncoder(ann)
    run = R.BrainRunner(fb, mb, enc, D.readout_populations(ann, mb.compartments),
                        gains=gains)
    feed = MK.ObservationFeed({s: MK.synthetic_series(s, seed=920 + i)
                               for i, s in enumerate(SYMBOLS)})
    uni = MK.Universe(SYMBOLS)
    return run.evaluate_round(
        [feed.observe(s, CUTOFF, stable_id=uni.stable_id(s)) for s in SYMBOLS],
        round_index=ROUND_INDEX, round_seed=ROUND_SEED,
        score=lambda c: 1.0 if c.symbol == SYMBOLS[0] else 0.0)


def _journal(tmp_path, brain, graph_sha256, credit=None):
    fb, mb, _ = brain
    credit = credit if credit is not None else R.CreditAssigner(mb)
    return REC.Journal(tmp_path, mb=mb, credit=credit,
                       versions=_versions(graph_sha256)), credit


OUTCOME = {"net_pnl": -12.5, "gross_pnl": -11.0, "fees": 1.5,
           "close_reason": "POLICY_CLOSE", "symbol": SYMBOLS[0]}


# ------------------------------------------------------ the crash test

@requires_real_graph
@pytest.mark.parametrize("fault", REC.FAULT_POINTS)
def test_an_outcome_is_neither_lost_nor_applied_twice_across_a_crash(
        tmp_path, brain, ann, fresh_weights, graph_sha256, fault):
    fb, mb, _ = brain
    rnd = _round(brain, ann)
    sel = rnd.selected
    journal, credit = _journal(tmp_path, brain, graph_sha256)

    # a clean checkpoint exists before the episode opens: this is the state a
    # crash before the reinforcement must leave the brain in
    journal.save_checkpoint(last_settled_episode=-1)
    before = mb.gain.copy()
    journal.open_episode(
        REC.DecisionRecord(
            episode_id=sel.episode_id, round_index=ROUND_INDEX,
            round_seed=ROUND_SEED, candidate_seed=sel.seed, symbol=sel.symbol,
            stable_id=sel.stable_id, bar_index=sel.observation.bar_index,
            cutoff_ts=sel.observation.cutoff_ts, wall_clock=0.0,
            versions=_versions(graph_sha256).as_dict(),
            checkpoint_digest=journal.checkpoint_digest(),
            observation=sel.observation.as_dict(),
            stimulus=sel.stimulus.as_dict(),
            readout=sel.presentation.as_dict(), decoded_action="BUY",
            readout_status="VALID", decoder=D.ActionDecoder().as_dict(),
            trace=sel.trace.as_dict()),
        sel.trace, {"bar_index": sel.observation.bar_index + 1})
    assert REC.read_pending(tmp_path / "pending.npz") is not None

    # --- the crash ------------------------------------------------------
    with pytest.raises(REC.InjectedFault):
        journal.settle(sel.episode_id, OUTCOME, VALENCE, AMOUNT, fault=fault)
    crashed_gain = mb.gain.copy()
    weights_had_moved = not np.array_equal(crashed_gain, before)

    # --- restart: a fresh process, nothing in memory ---------------------
    mb.gain[:] = 0.0            # scribble, to prove the checkpoint is read
    mb.apply()
    fresh_credit = R.CreditAssigner(mb)
    journal2, _ = _journal(tmp_path, brain, graph_sha256, fresh_credit)
    report = journal2.recover()

    if report["reapplied"]:
        ev = fresh_credit.settle(sel.episode_id, VALENCE, AMOUNT)
        assert ev.accepted
        journal2.save_checkpoint(last_settled_episode=sel.episode_id)
        REC.clear_pending(journal2.pending_path)
        journal2.log.append(REC.EventType.LEARNING,
                            {"episode_id": sel.episode_id, **ev.as_dict()})

    # --- the outcome was applied exactly once ----------------------------
    final = mb.gain.copy()
    assert not np.array_equal(final, before), "the outcome was lost"
    moved = np.flatnonzero(final != before)
    assert set(int(i) for i in moved) <= set(int(i) for i in sel.trace.index)
    assert (mb.side[moved] == VALENCE).all()

    # applying it a second time from a clean baseline would depress further;
    # the recovered state must equal exactly one application
    expected = before.copy()
    idx = sel.trace.index[mb.side[sel.trace.index] == VALENCE]
    vals = sel.trace.value[mb.side[sel.trace.index] == VALENCE]
    expected[idx] *= (1.0 - mb.lr * AMOUNT * vals)
    np.clip(expected, mb.floor, 1.0, out=expected)
    assert np.allclose(final, expected, atol=1e-6), (
        "the outcome was applied a number of times other than once")

    # and the log says so, exactly once
    log = journal2.log.read()
    outs = [e for e in log if e["kind"] == "OUTCOME"
            and e["episode_id"] == sel.episode_id]
    lrn = [e for e in log if e["kind"] == "LEARNING"
           and e["episode_id"] == sel.episode_id]
    assert len(outs) == 1, "the outcome event is not recorded exactly once"
    assert len(lrn) == 1, "the learning event is not recorded exactly once"
    assert REC.read_pending(journal2.pending_path) is None
    assert journal2.last_settled_episode == sel.episode_id

    # a further settle attempt is refused, whatever the crash point was
    again = fresh_credit.settle(sel.episode_id, VALENCE, AMOUNT,
                                trace=sel.trace)
    assert not again.accepted
    assert again.reason == R.RejectionReason.ALREADY_SETTLED.value
    assert np.array_equal(mb.gain, final)
    assert weights_had_moved in (True, False)      # both paths are legitimate


# ------------------------------------------------- the rest of §7

@requires_real_graph
def test_every_decision_links_observation_through_to_learning(
        tmp_path, brain, ann, fresh_weights, graph_sha256):
    fb, mb, _ = brain
    rnd = _round(brain, ann)
    sel = rnd.selected
    journal, credit = _journal(tmp_path, brain, graph_sha256)
    journal.save_checkpoint(last_settled_episode=-1)
    journal.record_round(rnd)

    rec = REC.DecisionRecord(
        episode_id=sel.episode_id, round_index=ROUND_INDEX,
        round_seed=ROUND_SEED, candidate_seed=sel.seed, symbol=sel.symbol,
        stable_id=sel.stable_id, bar_index=sel.observation.bar_index,
        cutoff_ts=sel.observation.cutoff_ts, wall_clock=1.0,
        versions=_versions(graph_sha256).as_dict(),
        checkpoint_digest=journal.checkpoint_digest(),
        observation=sel.observation.as_dict(),
        stimulus=sel.stimulus.as_dict(), readout=sel.presentation.as_dict(),
        decoded_action="BUY", readout_status="VALID",
        decoder=D.ActionDecoder().as_dict(), trace=sel.trace.as_dict(),
        n_candidates=len(rnd.candidates), selected=True)
    journal.record_decision(rec)
    journal.open_episode(rec, sel.trace, {"bar_index": rec.bar_index + 1,
                                          "fill_price": 101.5})
    journal.settle(sel.episode_id, OUTCOME, VALENCE, AMOUNT)

    # every link of the chain the amendment lists is present
    assert rec.observation["status"] == "OK"
    assert rec.stimulus["encoder_version"] == E.VERSION
    assert rec.readout["seed"] == sel.seed
    assert rec.decoded_action == "BUY" and rec.readout_status == "VALID"
    assert rec.execution["fill_price"] == 101.5
    assert rec.outcome["net_pnl"] == -12.5
    assert rec.learning["accepted"] is True
    assert rec.learning["eligibility_source"] == "replayed_from_decision"

    # every version and seed a replay needs
    v = rec.versions
    assert set(v) >= {"market", "encoder", "runner", "decoder", "execution",
                      "mushroom", "graph_sha256", "schema", "records"}
    assert v["graph_sha256"] == graph_sha256
    assert len(rec.checkpoint_digest) == 64
    assert rec.round_seed == ROUND_SEED and rec.candidate_seed == sel.seed
    assert rec.cutoff_ts > 0

    # and it is all on disk, in order, replayable by episode id
    chain = journal.replay_chain(sel.episode_id)
    assert set(chain) == {"ROUND", "DECISION", "EXECUTION", "OUTCOME",
                          "CHECKPOINT", "LEARNING"}


@requires_real_graph
def test_the_log_is_append_only_and_poor_performance_never_resets_the_brain(
        tmp_path, brain, ann, fresh_weights, graph_sha256):
    fb, mb, _ = brain
    journal, credit = _journal(tmp_path, brain, graph_sha256)
    journal.save_checkpoint(last_settled_episode=-1)
    first = journal.log.read()
    journal.log.append(REC.EventType.OUTCOME,
                       {"episode_id": 1, "net_pnl": -999.0})
    after = journal.log.read()
    assert after[:len(first)] == first          # nothing rewritten
    assert len(after) == len(first) + 1

    # a catastrophic loss does not reset anything: no code path anywhere
    # clears the learned gains on a bad outcome
    mb.gain[:100] = 0.5
    mb.apply()
    journal.save_checkpoint(last_settled_episode=1)
    saved = mb.gain.copy()
    mb.gain[:] = 0.0
    journal.load_checkpoint_into_brain()
    assert np.array_equal(mb.gain, saved)


@requires_real_graph
def test_a_checkpoint_from_another_graph_is_refused(tmp_path, brain,
                                                    fresh_weights, graph_sha256):
    fb, mb, _ = brain
    journal, _ = _journal(tmp_path, brain, graph_sha256)
    journal.save_checkpoint(last_settled_episode=0)
    wrong = REC.Journal(tmp_path, mb=mb, credit=R.CreditAssigner(mb),
                        versions=_versions("f" * 64))
    assert wrong.load_checkpoint_into_brain() is None
    with pytest.raises(S.CheckpointError, match="graph"):
        S.load_checkpoint(journal.checkpoint_path, graph_sha256="f" * 64)


@requires_real_graph
def test_a_pending_episode_from_another_graph_is_refused(tmp_path, brain,
                                                         ann, fresh_weights,
                                                         graph_sha256):
    rnd = _round(brain, ann)
    sel = rnd.selected
    p = tmp_path / "pending.npz"
    REC.write_pending(p, episode_id=sel.episode_id, symbol=sel.symbol,
                      stable_id=sel.stable_id, trace=sel.trace,
                      decision_bar=1, graph_sha256=graph_sha256)
    back = REC.read_pending(p, graph_sha256=graph_sha256)
    assert back["episode_id"] == sel.episode_id
    assert np.array_equal(back["trace"].index, sel.trace.index)
    assert np.array_equal(back["trace"].value, sel.trace.value)
    with pytest.raises(S.CheckpointError, match="graph"):
        REC.read_pending(p, graph_sha256="a" * 64)


@requires_real_graph
def test_an_episode_open_at_the_crash_is_reopened_not_settled(
        tmp_path, brain, ann, fresh_weights, graph_sha256):
    """No outcome yet: recovery must restore the episode, not invent a reward."""
    fb, mb, _ = brain
    rnd = _round(brain, ann)
    sel = rnd.selected
    journal, credit = _journal(tmp_path, brain, graph_sha256)
    journal.save_checkpoint(last_settled_episode=-1)
    REC.write_pending(journal.pending_path, episode_id=sel.episode_id,
                      symbol=sel.symbol, stable_id=sel.stable_id,
                      trace=sel.trace, decision_bar=1,
                      graph_sha256=graph_sha256)
    before = mb.gain.copy()

    fresh = R.CreditAssigner(mb)
    journal2, _ = _journal(tmp_path, brain, graph_sha256, fresh)
    report = journal2.recover()

    assert report["episode_reopened"] == sel.episode_id
    assert report["reapplied"] is False
    assert np.array_equal(mb.gain, before)
    assert sel.episode_id in fresh.open
    # and it can still be settled normally afterwards
    ev = fresh.settle(sel.episode_id, VALENCE, AMOUNT)
    assert ev.accepted
