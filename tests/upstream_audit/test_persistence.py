"""
(5) How upstream persists learned state, verified by running it.

mushroom.py:163-194. Saved: the gain vector, the synapse positions, the two
event counters, a wall-clock timestamp. Nothing else. Not saved: the
eligibility trace, the graph identity, any encoder/decoder version, any
history -- the file is overwritten in place on every save.
"""
from __future__ import annotations

import numpy as np
import pytest

from .synthetic import mb_graph, write_graph_npz


def _fb(flysim, tmp_path, name="g.npz", **kw):
    g = mb_graph(**kw)
    p = write_graph_npz(g, tmp_path / name, apply_sign_rule=False)
    return flysim.FlyBrain(graph_path=p)


def test_saved_state_is_exactly_gain_pos_counters_and_time(
        mushroom, flysim, tmp_path):
    mb = mushroom.MushroomBody(_fb(flysim, tmp_path))
    mb.observe(np.array([0, 1]))
    mb.dopamine(+1, 1.0)
    mb.save()
    z = np.load(mushroom.STORE)
    assert sorted(z.files) == ["at", "gain", "pos", "punishments", "rewards"]
    assert z["gain"].shape == mb.gain.shape
    assert int(z["rewards"]) == 1
    assert int(z["punishments"]) == 0
    # the eligibility trace is NOT persisted
    assert "trace" not in z.files


def test_learning_survives_a_restart(mushroom, flysim, tmp_path):
    mb = mushroom.MushroomBody(_fb(flysim, tmp_path))
    mb.observe(np.array([0, 1]))
    mb.dopamine(+1, 1.0)
    mb.dopamine(-1, 1.0)
    mb.save()
    learned = mb.gain.copy()

    fb2 = _fb(flysim, tmp_path, name="g2.npz")
    mb2 = mushroom.MushroomBody(fb2)        # load() runs in __init__
    assert np.allclose(mb2.gain, learned)
    assert mb2.events == {"reward": 1, "punish": 1}
    # and the loaded gains are already written into the simulation weights
    assert np.allclose(fb2.wdata[mb2.pos], mb2.base * learned)


def test_state_from_a_different_graph_is_discarded_not_misapplied(
        mushroom, flysim, tmp_path):
    """mushroom.py:186 compares length and pos; a mismatch resets to 1.0."""
    mb = mushroom.MushroomBody(_fb(flysim, tmp_path))
    mb.observe(np.array([0, 1]))
    mb.dopamine(+1, 1.0)
    mb.save()

    # a graph with a different KC->MBON synapse set
    from .synthetic import Graph, Neuron, KC_TO_MBON, DAN_TO_MBON, MBON_TO_DAN
    g = Graph(
        mb_graph().neurons,
        KC_TO_MBON[:2] + DAN_TO_MBON + MBON_TO_DAN + [
            ("L1", "KC_a", 5.0), ("L1", "KC_b", 5.0),
            ("MBON_approach", "DNa02", 7.0), ("MBON_avoid", "DNa02", 7.0),
            ("APL", "KC_a", 4.0)],
    )
    p = write_graph_npz(g, tmp_path / "other.npz", apply_sign_rule=False)
    other = mushroom.MushroomBody(flysim.FlyBrain(graph_path=p))
    assert len(other.pos) != len(mb.pos)
    assert (other.gain == 1.0).all()
    assert other.events == {"reward": 0, "punish": 0}


def test_save_overwrites_and_keeps_no_history(mushroom, flysim, tmp_path):
    """
    There is one file and it is rewritten in place -- no append-only log, no
    per-season file, no way to recover a previous learned state. Relevant to
    SPEC 'never rewrite historical results'.
    """
    mb = mushroom.MushroomBody(_fb(flysim, tmp_path))
    mb.observe(np.array([0, 1]))
    mb.dopamine(+1, 1.0)
    mb.save()
    first = np.load(mushroom.STORE)["gain"].copy()

    for _ in range(5):
        mb.observe(np.array([0, 1]))
        mb.dopamine(+1, 1.0)
    mb.save()
    second = np.load(mushroom.STORE)["gain"]

    assert not np.allclose(first, second)
    assert list(mushroom.STORE.parent.glob("*.npz")) == [mushroom.STORE]


def test_save_swallows_every_error(mushroom, flysim, tmp_path, monkeypatch):
    """
    mushroom.py:170 is a bare ``except Exception: pass``. A failed save is
    silent -- learning can be lost with no signal at all. Recorded, not fixed.
    """
    mb = mushroom.MushroomBody(_fb(flysim, tmp_path))
    monkeypatch.setattr(mushroom.np, "savez_compressed",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    mb.save()                       # must not raise
    assert not mushroom.STORE.exists()


def test_load_of_a_corrupt_store_is_also_silent(mushroom, flysim, tmp_path):
    """mushroom.py:193 swallows a corrupt file and starts from baseline."""
    mushroom.STORE.parent.mkdir(parents=True, exist_ok=True)
    mushroom.STORE.write_bytes(b"not an npz")
    mb = mushroom.MushroomBody(_fb(flysim, tmp_path))
    assert (mb.gain == 1.0).all()


def test_eligibility_trace_is_lost_across_a_restart(mushroom, flysim, tmp_path):
    """
    A dopamine event arriving immediately after a restart depresses nothing,
    because the trace starts at zero. Matters for SPEC's outcome->reward gap.
    """
    mb = mushroom.MushroomBody(_fb(flysim, tmp_path))
    mb.observe(np.array([0, 1]))
    mb.save()
    mb2 = mushroom.MushroomBody(_fb(flysim, tmp_path, name="g3.npz"))
    assert (mb2.trace == 0.0).all()
    assert mb2.dopamine(+1, 1.0) == 0
