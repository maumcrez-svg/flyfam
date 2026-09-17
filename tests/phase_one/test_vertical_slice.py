"""
Canonical amendment §8 — the vertical slice, as an invariant check.

The demonstration itself is ``experiments/phase_one/run_demo.py``. This is a
short run of the same loop asserting the properties that must hold however the
market happens to move: the accounting identity, one open position, exactly one
learning event per outcome, a complete replayable chain per episode, and a
horizon expiry never being reported as a neural decision.
"""
from __future__ import annotations

import numpy as np
import pytest

from flytrade import decoder as D
from flytrade import encoder as E
from flytrade import execution as X
from flytrade import market as MK
from flytrade import records as REC
from flytrade import runner as R

from .conftest import requires_real_graph

SYMBOLS = ("AA", "BB", "CC")
ROUND_SEED = 4242
FIRST_BAR = MK.MIN_HISTORY_BARS - 1
LAST_BAR = FIRST_BAR + 60


def _versions(graph_sha256):
    return REC.Versions(market=MK.VERSION, encoder=E.VERSION, runner=R.VERSION,
                        decoder=D.VERSION, execution=X.VERSION,
                        mushroom="flytrade-mb-1", graph_sha256=graph_sha256)


@requires_real_graph
def test_the_loop_runs_and_its_invariants_hold(tmp_path, brain, ann,
                                               fresh_weights, graph_sha256):
    fb, mb, gains = brain
    enc = E.MarketToSensoryEncoder(ann)
    dec = D.ActionDecoder()
    run = R.BrainRunner(fb, mb, enc, D.readout_populations(ann, mb.compartments),
                        gains=gains)
    credit = R.CreditAssigner(mb)
    series = {s: MK.synthetic_series(s, seed=750 + i)
              for i, s in enumerate(SYMBOLS)}
    feed = MK.ObservationFeed(series)
    universe = MK.Universe(SYMBOLS)
    policy = X.ExecutionPolicy(MK.ExecutionFeed(series))
    versions = _versions(graph_sha256)
    journal = REC.Journal(tmp_path, mb=mb, credit=credit, versions=versions)
    journal.save_checkpoint(last_settled_episode=-1)

    opened_episodes, settled_episodes = [], []

    for bar in range(FIRST_BAR, LAST_BAR):
        holding = policy.account.position is not None
        scan = (policy.account.position.symbol,) if holding else SYMBOLS
        rnd = run.evaluate_round(
            [feed.observe(s, bar, stable_id=universe.stable_id(s))
             for s in scan],
            round_index=bar, round_seed=ROUND_SEED, score=dec.score)
        journal.record_round(rnd)

        chosen = rnd.selected or (rnd.candidates[0] if holding else None)
        if chosen is None or chosen.presentation is None:
            continue
        d = dec.decode(chosen.presentation)

        # an unusable readout is never an action
        if d.status is not D.ReadoutStatus.VALID:
            assert d.action is D.Action.NO_RESPONSE
            assert not d.is_decision

        rec = REC.DecisionRecord(
            episode_id=chosen.episode_id, round_index=bar,
            round_seed=ROUND_SEED, candidate_seed=chosen.seed,
            symbol=chosen.symbol, stable_id=chosen.stable_id, bar_index=bar,
            cutoff_ts=chosen.observation.cutoff_ts, wall_clock=0.0,
            versions=versions.as_dict(),
            checkpoint_digest=journal.checkpoint_digest(),
            observation=chosen.observation.as_dict(),
            stimulus=chosen.stimulus.as_dict(),
            readout=chosen.presentation.as_dict(),
            decoded_action=d.action.value, readout_status=d.status.value,
            decoder=d.as_dict(), trace=chosen.trace.as_dict(),
            n_candidates=len(rnd.candidates), selected=True)
        journal.record_decision(rec)

        if not holding:
            if d.action is not D.Action.BUY:
                continue
            opened = policy.open_long(episode_id=chosen.episode_id,
                                      symbol=chosen.symbol,
                                      stable_id=chosen.stable_id,
                                      decision_bar=bar)
            if isinstance(opened, X.Rejection):
                continue
            journal.open_episode(rec, chosen.trace, opened.entry.as_dict())
            opened_episodes.append(chosen.episode_id)
            assert REC.read_pending(journal.pending_path) is not None
            continue

        reason = (X.CloseReason.POLICY_CLOSE if policy.due_for_horizon(bar)
                  else X.CloseReason.NEURAL_SELL
                  if d.action is D.Action.SELL else None)
        if reason is None:
            continue
        outcome = policy.close(decision_bar=bar, reason=reason)
        if isinstance(outcome, X.Rejection):
            continue
        v, amt = policy.reinforcement(outcome)
        if v == 0:
            REC.clear_pending(journal.pending_path)
            credit.open.pop(outcome.episode_id, None)
            credit.settled.add(outcome.episode_id)
        else:
            ev = journal.settle(outcome.episode_id, outcome.as_dict(), v, amt)
            assert ev.accepted
            assert ev.eligibility_source == "replayed_from_decision"
        settled_episodes.append(outcome.episode_id)
        assert REC.read_pending(journal.pending_path) is None

    # --- the run did something ------------------------------------------
    assert len(policy.outcomes) >= 3, "the loop completed too few cycles"
    assert len(set(o.symbol for o in policy.outcomes)) >= 2, \
        "the loop never touched a second instrument"
    assert run.presentations > 50

    # --- one open position, ever ----------------------------------------
    # episodes settle in the order they opened, and at most one may still be
    # open when the run stops
    assert opened_episodes[:len(settled_episodes)] == settled_episodes
    assert len(opened_episodes) - len(settled_episodes) <= 1
    assert (policy.account.position is not None) == (
        len(opened_episodes) > len(settled_episodes))
    assert len(set(opened_episodes)) == len(opened_episodes)

    # --- close anything still open, so the run ends flat -----------------
    if policy.account.position is not None:
        last = policy.account.position.episode_id
        out = policy.close(decision_bar=LAST_BAR,
                           reason=X.CloseReason.END_OF_DATA)
        assert not isinstance(out, X.Rejection)
        v, amt = policy.reinforcement(out)
        if v != 0:
            assert journal.settle(last, out.as_dict(), v, amt).accepted
        else:
            REC.clear_pending(journal.pending_path)
        settled_episodes.append(last)
    assert opened_episodes == settled_episodes

    # --- accounting ------------------------------------------------------
    policy.account.check()
    assert policy.account.cash == pytest.approx(
        policy.account.initial_cash + policy.account.realized_pnl, abs=1e-9)
    assert policy.account.realized_pnl == pytest.approx(
        sum(o.net_pnl for o in policy.outcomes), abs=1e-9)
    assert policy.account.fees_paid == pytest.approx(
        sum(o.fees for o in policy.outcomes), abs=1e-9)
    for o in policy.outcomes:
        assert o.entry.bar_index >= 0
        assert o.exit.bar_index > o.entry.bar_index
        assert o.net_pnl == pytest.approx(o.gross_pnl - o.fees, abs=1e-9)
        # every fill happened at least one bar after its decision
        assert o.bars_held >= 1

    # --- a horizon expiry is never a neural decision ---------------------
    for o in policy.outcomes:
        if o.close_reason is X.CloseReason.POLICY_CLOSE:
            assert o.bars_held >= policy.horizon_bars

    # --- exactly one learning event per outcome --------------------------
    log = journal.log.read()
    outs = [e["episode_id"] for e in log if e["kind"] == "OUTCOME"]
    lrn = [e["episode_id"] for e in log if e["kind"] == "LEARNING"]
    assert sorted(outs) == sorted(set(outs))
    assert sorted(lrn) == sorted(set(lrn))
    assert set(outs) == set(lrn)
    assert credit.stats()["rejections_total"] == 0
    assert credit.stats()["accepted"] == len(outs)

    # --- every settled episode replays end to end ------------------------
    for ep in settled_episodes:
        if ep not in outs:
            continue
        chain = journal.replay_chain(ep)
        assert {"ROUND", "DECISION", "EXECUTION", "OUTCOME",
                "LEARNING"} <= set(chain)
        dec_e = chain["DECISION"][0]
        assert dec_e["versions"]["graph_sha256"] == graph_sha256
        assert dec_e["versions"]["encoder"] == E.VERSION
        assert dec_e["versions"]["decoder"] == D.VERSION
        assert dec_e["versions"]["execution"] == X.VERSION
        assert dec_e["seed"] >= 0
        assert dec_e["readout_status"] in {s.value for s in D.ReadoutStatus}

    # --- the learned state survives a restart ----------------------------
    saved = mb.gain.copy()
    assert not np.array_equal(saved, np.ones_like(saved)), \
        "nothing was learned in the whole run"
    mb.gain[:] = 0.0
    mb.apply()
    REC.Journal(tmp_path, mb=mb, credit=R.CreditAssigner(mb),
                versions=versions).recover()
    assert np.array_equal(mb.gain, saved)
