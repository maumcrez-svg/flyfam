"""
Time, memory and persistence — canonical amendment §6.

Upstream's persistence swallows every exception (`mushroom.py:170`, `:193`),
overwrites in place with no history, and falls back to a `SHIPPED` file inside
the repository. None of that is reproduced here, and these tests pin that.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from flytrade import state as St


# -- time --------------------------------------------------------------------

def test_the_upstream_constants_are_reproduced_at_a_500ms_cycle():
    """The parameters are unchanged; only their dependence on call rate is."""
    assert St.trace_decay_per_cycle() == pytest.approx(0.55, abs=1e-12)
    assert St.recovery_per_cycle() == pytest.approx(0.0008, abs=1e-12)


def test_memory_duration_does_not_depend_on_the_call_rate():
    """Two cycle lengths, the same wall-clock elapsed time, the same trace.

    This is the property upstream lacks: at 0.55 *per call*, doubling the
    frontend's rate halves the eligibility window.
    """
    slow = St.trace_decay_per_cycle(500.0) ** 4     # 4 cycles of 500 ms
    fast = St.trace_decay_per_cycle(250.0) ** 8     # 8 cycles of 250 ms = 2 s
    assert slow == pytest.approx(fast, rel=1e-12)
    # and it is a real exponential decay with the documented time constant
    assert St.ELIGIBILITY_TAU_MS == pytest.approx(836.4, abs=0.1)
    assert math.exp(-St.ELIGIBILITY_TAU_MS / St.ELIGIBILITY_TAU_MS) == \
        pytest.approx(1 / math.e)


def test_recovery_time_constant_is_minutes_not_steps():
    assert St.RECOVERY_TAU_MS / 1000.0 == pytest.approx(624.8, abs=0.5)


# -- the four layers ---------------------------------------------------------

def test_electrical_state_persists_nowhere():
    e = St.ElectricalState()
    assert e.persists_across_cycles is False
    assert e.persists_across_restart is False


def test_eligibility_starts_empty_and_is_never_restored():
    el = St.EligibilityState.empty(10)
    assert el.trace.sum() == 0.0
    assert (el.episode == -1).all()
    assert el.persists_across_restart is False
    # and nothing in the checkpoint format can carry one
    assert "trace" not in St._REQUIRED


def test_the_episode_log_is_append_only(tmp_path):
    log = St.EpisodeLog(tmp_path / "episodes.jsonl")
    log.append(St.EpisodeRecord(0, 1.0, "A", 7))
    log.append(St.EpisodeRecord(1, 2.0, "B", 8))
    assert len(log) == 2
    with pytest.raises(ValueError):
        log.append(St.EpisodeRecord(0, 3.0, "A", 9))
    lines = (tmp_path / "episodes.jsonl").read_text().splitlines()
    assert len(lines) == 2
    # a second log appends rather than truncating
    St.EpisodeLog(tmp_path / "episodes.jsonl").append(
        St.EpisodeRecord(2, 4.0, "A", 10))
    assert len((tmp_path / "episodes.jsonl").read_text().splitlines()) == 3


# -- checkpoint --------------------------------------------------------------

GRAPH = "8feb08a0d2a80cbcf69328f9707d5dd748d73d2e12246526d96e48d995f843b9"


def _ck(tmp_path, **kw):
    gain = np.linspace(0.3, 1.0, 64, dtype=np.float32)
    pos = np.arange(64, dtype=np.int64) * 3
    args = dict(gain=gain, pos=pos, graph_sha256=GRAPH, rng_seed=11,
                episode=4, events={"punish": 20})
    args.update(kw)
    return St.save_checkpoint(tmp_path / "learned.npz", **args), args


def test_round_trip(tmp_path):
    path, args = _ck(tmp_path)
    got = St.load_checkpoint(path, graph_sha256=GRAPH, expect_pos=args["pos"])
    assert np.array_equal(got["gain"], args["gain"])
    assert np.array_equal(got["pos"], args["pos"])
    assert got["rng_seed"] == 11 and got["episode"] == 4
    assert got["events"] == {"punish": 20}
    assert got["schema"] == St.SCHEMA_VERSION
    assert got["cycle_ms"] == St.DECISION_CYCLE_MS
    assert got["eligibility_tau_ms"] == pytest.approx(St.ELIGIBILITY_TAU_MS)


def test_a_different_graph_hash_raises(tmp_path):
    path, _ = _ck(tmp_path)
    with pytest.raises(St.CheckpointError, match="different set of synapses"):
        St.load_checkpoint(path, graph_sha256="0" * 64)


def test_a_truncated_file_raises(tmp_path):
    path, _ = _ck(tmp_path)
    raw = path.read_bytes()
    path.write_bytes(raw[: len(raw) // 2])
    with pytest.raises(St.CheckpointError):
        St.load_checkpoint(path, graph_sha256=GRAPH)


def test_a_corrupted_payload_raises(tmp_path):
    """Flip bytes inside the stored gain array; the digest must catch it."""
    path, args = _ck(tmp_path)
    raw = bytearray(path.read_bytes())
    # np.savez is an uncompressed zip of .npy members; corrupt the middle
    mid = len(raw) // 2
    for i in range(mid, mid + 32):
        raw[i] ^= 0xFF
    path.write_bytes(bytes(raw))
    with pytest.raises(St.CheckpointError):
        St.load_checkpoint(path, graph_sha256=GRAPH)


def test_a_missing_file_raises(tmp_path):
    with pytest.raises(St.CheckpointError, match="no checkpoint"):
        St.load_checkpoint(tmp_path / "nope.npz", graph_sha256=GRAPH)


def test_a_foreign_schema_raises(tmp_path):
    p = tmp_path / "old.npz"
    np.savez(p, schema=np.str_("someone-elses-format-9"),
             gain=np.ones(4, np.float32), pos=np.arange(4, dtype=np.int64),
             graph_sha256=np.str_(GRAPH), rng_seed=np.int64(0),
             episode=np.int64(0), digest=np.str_("x"))
    with pytest.raises(St.CheckpointError, match="schema"):
        St.load_checkpoint(p, graph_sha256=GRAPH)


def test_a_position_vector_mismatch_raises(tmp_path):
    path, args = _ck(tmp_path)
    with pytest.raises(St.CheckpointError, match="synapse positions"):
        St.load_checkpoint(path, graph_sha256=GRAPH,
                           expect_pos=np.arange(10, dtype=np.int64))


def test_a_failed_write_raises_rather_than_passing_silently(tmp_path):
    with pytest.raises(St.CheckpointError):
        St.save_checkpoint(tmp_path / "x.npz", gain=np.ones(3, np.float32),
                           pos=np.arange(5, dtype=np.int64),
                           graph_sha256=GRAPH, rng_seed=0, episode=0)


def test_the_write_is_atomic_and_leaves_no_temporary_behind(tmp_path):
    path, _ = _ck(tmp_path)
    _ck(tmp_path)                      # overwrite
    assert [p.name for p in tmp_path.iterdir()] == ["learned.npz"]


def test_an_overwrite_replaces_the_previous_checkpoint_completely(tmp_path):
    path, args = _ck(tmp_path)
    new_gain = np.full(64, 0.5, dtype=np.float32)
    St.save_checkpoint(path, gain=new_gain, pos=args["pos"],
                       graph_sha256=GRAPH, rng_seed=99, episode=12)
    got = St.load_checkpoint(path, graph_sha256=GRAPH)
    assert np.array_equal(got["gain"], new_gain)
    assert got["rng_seed"] == 99


# -- the three layers, end to end on the synthetic graph ---------------------

def test_learned_weights_survive_a_restart_and_traces_do_not(synth, flysim,
                                                             tmp_path):
    from flytrade import graph as G
    from flytrade import mushroom as M
    from . import synthetic

    def build_mb():
        fb = flysim.FlyBrain(graph_path=synth / "graph.npz")
        mod = G.ModulatoryGraph(synth / "graph_mod.npz", bodies=fb.bodies)
        i = synthetic.index_of
        return fb, M.MushroomBody(
            fb, mod,
            np.array([i("KC_a"), i("KC_b")]),
            np.array([i("MBON_pam"), i("MBON_ppl1")]),
            np.array([i("PAM_x")]), np.array([i("PPL1_y")]))

    fb, mb = build_mb()
    i = synthetic.index_of
    mb.begin_episode(3)
    mb.observe(np.array([i("KC_a"), i("KC_b")]))
    mb.dopamine(+1, 1.0)
    mb.apply()
    learned = mb.gain.copy()
    assert (learned < 1.0).any()
    assert mb.trace.max() > 0

    sha = G.sha256_file(synth / "graph.npz")
    p = St.save_checkpoint(tmp_path / "mb.npz", gain=mb.gain, pos=mb.pos,
                           graph_sha256=sha, rng_seed=5, episode=mb.episode,
                           events=mb.events)

    # "restart": a brand-new brain and mushroom body
    fb2, mb2 = build_mb()
    assert (mb2.gain == 1.0).all()
    assert mb2.trace.max() == 0.0, "eligibility never comes back"
    got = St.load_checkpoint(p, graph_sha256=sha, expect_pos=mb2.pos)
    mb2.gain[:] = got["gain"]
    mb2.apply()
    assert np.array_equal(mb2.gain, learned)
    assert np.allclose(fb2.wdata[mb2.pos], mb2.base * learned)
    assert mb2.trace.max() == 0.0
