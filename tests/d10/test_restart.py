"""Learning survives a restart, and a frozen branch's digest does not move.

The real journal, the real checkpoint, the real credit assigner and the real
recovery rule, over a small real mushroom body. The D5/D6 mid-run restart test,
repeated for the Pons loop as addendum 11 requires: kill after a settled
episode, resume, gains restored exactly.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from flytrade import graph as G
from flytrade import mushroom as M
from flytrade import populations as P
from flytrade import records as REC
from flytrade import runner as R
from flytrade import state as S

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "malecns-v1.0"


@pytest.fixture
def mushroom():
    if not (DATA / "graph.npz").exists():
        pytest.skip(f"{DATA} is not on disk; see data/MANIFEST.md")
    import flysim
    fb = flysim.FlyBrain(graph_path=DATA / "graph.npz")
    mod = G.ModulatoryGraph(DATA / "graph_mod.npz", bodies=fb.bodies)
    ann = P.Annotations.load(DATA / "annotations.npz")
    sha = G.sha256_file(DATA / "graph.npz")
    mb = M.MushroomBody(fb, mod, np.flatnonzero(P.kenyon_cells(ann)),
                        np.flatnonzero(P.mbons(ann)),
                        np.flatnonzero(P.pam(ann)),
                        np.flatnonzero(P.ppl1(ann)))
    return fb, mb, sha


def _versions(sha):
    return REC.Versions(market="pons_context_v1", encoder="pons_encoder_v1",
                        runner=R.VERSION, decoder="d", execution="pons_paper_v1",
                        mushroom=M.VERSION, graph_sha256=sha)


def test_a_restart_after_a_settled_episode_restores_the_gains_exactly(
        tmp_path, mushroom):
    fb, mb, sha = mushroom
    credit = R.CreditAssigner(mb)
    journal = REC.Journal(tmp_path / "learning", mb=mb, credit=credit,
                          versions=_versions(sha))
    journal.stamp = {"venue": "PONS", "chain_id": 4663, "mode": "REPLAY_PAPER",
                     "learning": "LEARN"}
    journal.save_checkpoint(last_settled_episode=-1)

    # one episode: lay down an eligibility trace, then settle it
    mb.begin_episode(7)
    mb.trace[:8] = 1.0
    mb.trace_episode[:8] = 7
    traces = R.StoredTraceSet.of(7, [R.StoredTrace(
        episode_id=7, index=np.arange(8), value=np.ones(8, dtype=np.float32),
        n_synapses=int(len(mb.trace)))])
    rec = REC.DecisionRecord(
        episode_id=7, round_index=1, round_seed=0, candidate_seed=1,
        symbol="0x" + "a" * 40, stable_id=0, bar_index=1, cutoff_ts=1,
        wall_clock=0.0, versions=_versions(sha).as_dict(),
        checkpoint_digest=journal.checkpoint_digest(), observation={},
        stimulus=None, readout=None, decoded_action="BUY",
        readout_status="VALID", decoder={}, trace=None)
    journal.record_decision(rec)
    journal.open_episode(rec, traces, {"side": "BUY", "token": rec.symbol})
    before = journal.checkpoint_digest()
    journal.settle(7, {"net_pnl": -0.0005}, -1, 0.5)
    after = journal.checkpoint_digest()
    assert after != before                      # the update really moved them

    saved = mb.gain.copy()
    # the restart: destroy the in-memory state and rebuild from disk
    mb.gain[:] = 0.0
    mb.apply()
    credit2 = R.CreditAssigner(mb)
    journal2 = REC.Journal(tmp_path / "learning", mb=mb, credit=credit2,
                           versions=_versions(sha))
    report = journal2.recover()
    assert np.array_equal(mb.gain, saved)
    assert journal2.checkpoint_digest() == after
    assert 7 in credit2.settled
    assert report["action"]


def test_a_restart_cannot_apply_the_same_episode_twice(tmp_path, mushroom):
    fb, mb, sha = mushroom
    credit = R.CreditAssigner(mb)
    journal = REC.Journal(tmp_path / "learning", mb=mb, credit=credit,
                          versions=_versions(sha))
    journal.save_checkpoint(last_settled_episode=-1)
    mb.begin_episode(3)
    traces = R.StoredTraceSet.of(3, [R.StoredTrace(
        episode_id=3, index=np.arange(8), value=np.ones(8, dtype=np.float32),
        n_synapses=int(len(mb.trace)))])
    credit.open_episode(traces)
    REC.write_pending(journal.pending_path, episode_id=3, symbol="t",
                      stable_id=0, trace=traces, decision_bar=1,
                      graph_sha256=sha)
    journal.log.append(REC.EventType.OUTCOME, {"episode_id": 3})
    journal.settle(3, {"net_pnl": 1.0}, 1, 0.5)
    digest = journal.checkpoint_digest()

    credit2 = R.CreditAssigner(mb)
    journal2 = REC.Journal(tmp_path / "learning", mb=mb, credit=credit2,
                           versions=_versions(sha))
    journal2.recover()
    assert journal2.checkpoint_digest() == digest
    assert 3 in credit2.settled


def test_a_frozen_settlement_moves_the_episode_counter_and_not_the_gains(
        tmp_path, mushroom):
    fb, mb, sha = mushroom
    credit = R.CreditAssigner(mb)
    journal = REC.Journal(tmp_path / "frozen_reference", mb=mb, credit=credit,
                          versions=_versions(sha))
    journal.stamp = {"venue": "PONS", "chain_id": 4663, "mode": "REPLAY_PAPER",
                     "learning": "FROZEN"}
    journal.save_checkpoint(last_settled_episode=-1)
    before = journal.checkpoint_digest()
    journal.settle_frozen(11, {"net_pnl": -0.0004, "token": "0xabc"})
    assert journal.checkpoint_digest() == before
    assert journal.frozen_settled == 1
    assert credit.stats()["accepted"] == 0
    lines = [json.loads(line) for line in
             journal.log.path.read_text().splitlines() if line.strip()]
    kinds = [line["kind"] for line in lines]
    assert "LEARNING" not in kinds
    assert any(line.get("settlement") == "SETTLED_FROZEN" for line in lines)
    assert all(line["venue"] == "PONS" for line in lines)


def test_the_stamp_is_empty_for_a_pre_d10_journal(tmp_path, mushroom):
    """So D5-D9(b) logs are unchanged by the stamping machinery existing."""
    fb, mb, sha = mushroom
    journal = REC.Journal(tmp_path / "old", mb=mb, credit=R.CreditAssigner(mb),
                          versions=_versions(sha))
    assert journal.stamp == {}
    journal.save_checkpoint(last_settled_episode=-1)
    line = json.loads(journal.log.path.read_text().splitlines()[0])
    assert set(line) == {"t", "kind", "episode_id", "digest", "path"}
