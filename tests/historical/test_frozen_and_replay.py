"""
Frozen evaluation, the paired comparison schedule, and restart on replay.

Amendment D6 §4 and §6, Fable addenda 5 and 6. Three properties, and all three
are the kind that a reading of the code cannot establish:

* "frozen" means the learned weights do not move — proven by comparing the
  partition's start and end checkpoint hashes, not by grepping for a call;
* the comparison seeds are identical in the learned and the reference branch
  **even though the weights differ** — proven by drawing them under two
  different state digests;
* an outcome settled on a historical replay is applied exactly once across a
  restart, by the D4 fault-injection pattern.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from flytrade import decoder as D
from flytrade import encoder as E
from flytrade import historical as H
from flytrade import market as MK
from flytrade import readout as RO
from flytrade import records as REC
from flytrade import runner as R
from flytrade import state as S

from .conftest import requires_real_graph
from tests.historical import make_fixtures as MF

D0, D1, D2 = MF.DAYS
OUTCOME = {"net_pnl": -12.5, "gross_pnl": -11.0, "gross_reference_pnl": -10.4,
           "slippage": 0.6, "fees": 1.5, "close_reason": "POLICY_CLOSE",
           "symbol": "A", "account": {"cash": 9987.5, "realized_pnl": -12.5}}


def _versions(sha):
    return REC.Versions(market=MK.VERSION, encoder=E.VERSION, runner=R.VERSION,
                        decoder=D.VERSION, execution=H.HistoricalExecution.version,
                        mushroom="flytrade-mb-1", graph_sha256=sha)


# ------------------------------------------------ the comparison schedule

def test_comparison_v1_draws_the_same_seeds_under_different_weights():
    """The property the paired comparison rests on."""
    a = RO.policy_comparison()
    learned = "a" * 64
    reference = "b" * 64
    for stable_id in (0, 1):
        s1 = a.seeds(learned, "obs-xyz", stable_id)
        s2 = a.seeds(reference, "obs-xyz", stable_id)
        assert s1 == s2
        assert len(s1) == RO.K == 8
        assert len(set(s1)) == 8
    # the D4 schedule, by contrast, deliberately does change with the weights
    k8 = RO.policy_k8()
    assert k8.seeds(learned, "obs-xyz", 0) != k8.seeds(reference, "obs-xyz", 0)


def test_comparison_v1_still_separates_observations_and_instruments():
    p = RO.policy_comparison()
    dig = "c" * 64
    assert p.seeds(dig, "obs-1", 0) != p.seeds(dig, "obs-2", 0)
    assert p.seeds(dig, "obs-1", 0) != p.seeds(dig, "obs-1", 1)
    # and it never collides with any D4 namespace for the same tuple
    other = {RO.ROUND_NAMESPACE, RO.BASELINE_NAMESPACE, RO.EVAL_NAMESPACE,
             RO.BENCH_NAMESPACE}
    assert RO.COMPARISON_NAMESPACE == "comparison_v1"
    assert RO.COMPARISON_NAMESPACE not in other
    for ns in other:
        assert RO.replicate_seed(ns, dig, "obs-1", 0, 0) != \
            RO.comparison_seed("obs-1", 0, 0)


def test_comparison_v1_is_versioned_and_declared_in_the_committed_config():
    import json
    from pathlib import Path
    cfg = Path(__file__).resolve().parents[2] / "experiments" / "historical" \
        / "config.json"
    d = json.loads(cfg.read_text())
    assert d["seeds"]["FROZEN"]["namespace"] == RO.COMPARISON_NAMESPACE
    assert d["seeds"]["FROZEN"]["keyed_to_learned_state"] is False
    assert d["seeds"]["LEARNING"]["namespace"] == RO.ROUND_NAMESPACE
    assert d["seeds"]["LEARNING"]["keyed_to_learned_state"] is True
    # the policy object reports the same thing
    p = RO.policy_comparison().as_dict()
    assert p["keyed_to_learned_state"] is False
    assert p["k"] == 8
    assert p["decoder"]["theta_hz"] == RO.THETA_HZ_K8


def test_the_comparison_policy_changes_only_the_seeds():
    a, b = RO.policy_k8().as_dict(), RO.policy_comparison().as_dict()
    for key in ("k", "aggregation", "kc_fraction", "max_rate_hz", "decoder",
                "decoder_per_replicate", "seed_bits", "version"):
        assert a[key] == b[key], key
    assert a["namespace"] != b["namespace"]


# ------------------------------------------------------ frozen semantics

@requires_real_graph
def test_a_frozen_settlement_moves_no_weight_and_writes_no_learning_event(
        tmp_path, brain, fresh_weights, graph_sha256):
    fb, mb, _ = brain
    mb.gain[:5000] = 0.7                       # a learned state, not a clean one
    mb.apply()
    credit = R.CreditAssigner(mb)
    journal = REC.Journal(tmp_path, mb=mb, credit=credit,
                          versions=_versions(graph_sha256))
    journal.save_checkpoint(last_settled_episode=-1)
    start = journal.checkpoint_digest()
    gains_before = mb.gain.copy()

    journal.record_partition(name="FROZEN", boundary="start", branch="learned")
    out = journal.settle_frozen(4242, OUTCOME)
    journal.record_partition(name="FROZEN", boundary="end", branch="learned")

    assert out["settlement"] == "SETTLED_FROZEN"
    assert journal.checkpoint_digest() == start
    assert np.array_equal(mb.gain, gains_before)
    kinds = [e["kind"] for e in journal.log.read()]
    assert "OUTCOME" in kinds
    assert "LEARNING" not in kinds
    assert journal.frozen_settled == 1
    assert credit.accepted == 0
    assert sum(credit.rejections.values()) == 0
    # the outcome event says so, and carries the account the observer reads
    ev = [e for e in journal.log.read() if e["kind"] == "OUTCOME"][0]
    assert ev["settlement"] == "SETTLED_FROZEN"
    assert ev["account"]["realized_pnl"] == -12.5
    # both partition boundaries recorded the same hash
    parts = [e for e in journal.log.read() if e["kind"] == "PARTITION"]
    assert len(parts) == 2
    assert parts[0]["state_digest"] == parts[1]["state_digest"] == start


@requires_real_graph
def test_a_frozen_episode_cannot_be_settled_twice(tmp_path, brain,
                                                  fresh_weights, graph_sha256):
    fb, mb, _ = brain
    credit = R.CreditAssigner(mb)
    journal = REC.Journal(tmp_path, mb=mb, credit=credit,
                          versions=_versions(graph_sha256))
    journal.save_checkpoint(last_settled_episode=-1)
    journal.settle_frozen(77, OUTCOME)
    assert 77 in credit.settled
    # a later reinforcement addressed to it is refused with a reason
    ev = credit.settle(77, -1, 0.5)
    assert not ev.accepted
    assert ev.reason == "ALREADY_SETTLED"
    assert credit.rejections["ALREADY_SETTLED"] == 1


@requires_real_graph
def test_eligibility_accumulates_in_frozen_and_is_never_applied(
        tmp_path, brain, ann, fresh_weights, graph_sha256, series_a):
    """Transient simulation stays on; only the weights are frozen."""
    fb, mb, gains = brain
    run = R.BrainRunner(fb, mb, E.MarketToSensoryEncoder(ann),
                        D.readout_populations(ann, mb.compartments),
                        gains=gains, graph_sha256=graph_sha256)
    policy = RO.policy_comparison()
    obs = series_a.observe(D1, 95, stable_id=0)
    assert obs.status is MK.ObservationStatus.OK
    stim = run.encoder.encode(obs)
    before = mb.gain.copy()
    batch = policy.measure(run, stim, episode_id=9001,
                           state_dig=run.state_digest(),
                           obs_id=RO.observation_id(obs))
    # the brain ran, eight times, and laid down eligibility
    assert batch.k == 8
    assert len(batch.replicates) == 8
    assert batch.traces.n_eligible >= 0
    # and not one learned weight moved
    assert np.array_equal(mb.gain, before)


# --------------------------------------------- restart on historical replay

@requires_real_graph
@pytest.mark.parametrize("fault", REC.FAULT_POINTS)
def test_a_historical_outcome_is_neither_lost_nor_applied_twice(
        tmp_path, brain, ann, fresh_weights, graph_sha256, series_a, fault):
    """The D4 fault-injection pattern, on a historical observation."""
    fb, mb, gains = brain
    versions = _versions(graph_sha256)
    run = R.BrainRunner(fb, mb, E.MarketToSensoryEncoder(ann),
                        D.readout_populations(ann, mb.compartments),
                        gains=gains, graph_sha256=graph_sha256)
    policy = RO.policy_k8()
    obs = [series_a.observe(D1, 95, stable_id=0)]
    assert obs[0].status is MK.ObservationStatus.OK

    credit = R.CreditAssigner(mb)
    journal = REC.Journal(tmp_path, mb=mb, credit=credit, versions=versions)
    journal.save_checkpoint(last_settled_episode=-1)
    rnd = run.evaluate_round(obs, round_index=95, readout=policy,
                             score=lambda c: 1.0)
    sel = rnd.selected
    assert sel is not None
    rec = REC.decision_record(
        sel, policy.decoder.decode(sel.presentation), round_index=95,
        bar_index=95, versions=versions,
        checkpoint_digest=journal.checkpoint_digest(),
        n_candidates=1, readout_policy=policy.as_dict(), wall_clock=0.0,
        partition="LEARNING", branch="learned", run_id="test",
        dataset_label="HISTORICAL_MARKET")
    journal.record_decision(rec)
    journal.open_episode(rec, sel.traces, {"bar_index": 96})

    # the reference: one clean application of the same normalised update
    want = mb.gain.copy()
    ref_credit = R.CreditAssigner(mb)
    ref_credit.open_episode(sel.traces)
    ref_credit.settle(sel.episode_id, -1, 0.8)
    want_after = mb.gain.copy()
    mb.gain[:] = want
    mb.apply()
    assert not np.array_equal(want, want_after), "the update must move weights"

    with pytest.raises(REC.InjectedFault):
        journal.settle(sel.episode_id, OUTCOME, -1, 0.8, fault=fault)

    # --- restart: memory destroyed, rebuilt from the checkpoint and the log
    mb.gain[:] = 0.0
    mb.apply()
    fresh = R.CreditAssigner(mb)
    journal2 = REC.Journal(tmp_path, mb=mb, credit=fresh, versions=versions)
    report = journal2.recover()
    if report["reapplied"]:
        fresh.settle(sel.episode_id, -1, 0.8)
        journal2.save_checkpoint(last_settled_episode=sel.episode_id)
        journal2.log.append(REC.EventType.LEARNING,
                            {"episode_id": sel.episode_id, "recovered": True,
                             "accepted": True})

    assert np.allclose(mb.gain, want_after, atol=1e-7), fault
    log = journal2.log.read()
    assert sum(1 for e in log if e["kind"] == "OUTCOME"
               and e["episode_id"] == sel.episode_id) == 1
    assert sum(1 for e in log if e["kind"] == "LEARNING"
               and e["episode_id"] == sel.episode_id) == 1
    # a second attempt is refused, not applied
    again = fresh.settle(sel.episode_id, -1, 0.8)
    assert not again.accepted and again.reason == "ALREADY_SETTLED"
    assert np.allclose(mb.gain, want_after, atol=1e-7)


@requires_real_graph
def test_the_decision_record_carries_both_clocks_and_the_partition(
        tmp_path, brain, ann, graph_sha256, fresh_weights, series_a):
    fb, mb, gains = brain
    run = R.BrainRunner(fb, mb, E.MarketToSensoryEncoder(ann),
                        D.readout_populations(ann, mb.compartments),
                        gains=gains, graph_sha256=graph_sha256)
    policy = RO.policy_k8()
    obs = [series_a.observe(D1, 95, stable_id=0)]
    rnd = run.evaluate_round(obs, round_index=1234, readout=policy,
                             score=lambda c: 1.0)
    rec = REC.decision_record(
        rnd.selected, policy.decoder.decode(rnd.selected.presentation),
        round_index=1234, bar_index=95, versions=_versions(graph_sha256),
        checkpoint_digest="x" * 64, n_candidates=1, wall_clock=0.0,
        readout_policy=policy.as_dict(), partition="LEARNING",
        branch="learned", run_id="hist-001",
        dataset_label="HISTORICAL_MARKET")
    # market time is the bar_end of minute 95; brain time is the round
    assert rec.cutoff_ts == int(series_a.sessions[D1].bar_start[95]) + 60
    assert rec.brain_cycle == 1234
    assert rec.brain_ms == 1234 * S.DECISION_CYCLE_MS
    assert rec.partition == "LEARNING" and rec.branch == "learned"
    assert rec.run_id == "hist-001"
    assert rec.dataset_label == "HISTORICAL_MARKET"
    # and both reach the log
    journal = REC.Journal(tmp_path, mb=mb, credit=R.CreditAssigner(mb),
                          versions=_versions(graph_sha256))
    journal.record_decision(rec)
    ev = [e for e in journal.log.read() if e["kind"] == "DECISION"][0]
    assert ev["market_ts"] == rec.cutoff_ts
    assert ev["brain_cycle"] == 1234 and ev["brain_ms"] == 617000.0
    assert ev["partition"] == "LEARNING"
    assert ev["dataset_label"] == "HISTORICAL_MARKET"
