"""
Simulation semantics that Phase One depends on, verified by running upstream.

Relevant to SPEC's replay-determinism and sensory-encoding requirements:
how the external drive is injected, what units it is in, whether a seeded run
reproduces, and whether state carries across calls to ``run``.
"""
from __future__ import annotations

import numpy as np
import pytest

from .synthetic import Graph, Neuron, write_graph_npz


@pytest.fixture
def chain(flysim, tmp_path):
    """L1 -> KC_a -> MBON_avoid, all excitatory, all suprathreshold."""
    g = Graph(
        [Neuron("L1"), Neuron("KC_a"), Neuron("MBON_avoid")],
        [("L1", "KC_a", 60.0), ("KC_a", "MBON_avoid", 60.0)],
    )
    return flysim.FlyBrain(graph_path=write_graph_npz(g, tmp_path / "g.npz"))


def test_run_is_deterministic_for_a_fixed_seed(chain):
    rec = {"out": np.array([2])}
    a = chain.run({(0,): 200.0}, steps=400, record=rec, seed=7)
    b = chain.run({(0,): 200.0}, steps=400, record=rec, seed=7)
    assert a["out"].tolist() == b["out"].tolist()
    assert a["_spikes_per_sec"] == b["_spikes_per_sec"]
    assert a["_mean_mv"] == b["_mean_mv"]


def test_a_different_seed_gives_a_different_run(chain):
    rec = {"out": np.array([2])}
    a = chain.run({(0,): 200.0}, steps=400, record=rec, seed=7)
    b = chain.run({(0,): 200.0}, steps=400, record=rec, seed=8)
    assert a["out"].tolist() != b["out"].tolist()


def test_run_carries_no_membrane_state_between_calls(chain):
    """
    flysim.py:101 resets v to v_rest at the top of every ``run``. Each call is
    an independent window; only the weights (and whatever mushroom.apply wrote
    into them) persist. A Phase-One BrainRunner cannot rely on integration
    across decisions.
    """
    rec = {"out": np.array([2])}
    hot = chain.run({(0,): 400.0}, steps=400, record=rec, seed=3)
    cold = chain.run({}, steps=400, record=rec, seed=3)
    assert hot["out"].mean() > 0.0
    assert cold["out"].mean() == 0.0
    assert cold["_spikes_per_sec"] == 0.0


def test_drive_is_a_poisson_rate_in_hz_clipped_at_one_spike_per_step(chain):
    """
    flysim.py:124 ``p = rate * dt / 1000`` clipped to [0, 1], and dt = 0.2 ms.
    So the drive saturates at 5000 Hz and any rate above that is silently the
    same as 5000. The encoder in Phase One must normalise into that range
    itself -- nothing upstream will warn.
    """
    idx = np.array([0])
    rec = {"in": idx}
    r1 = chain.run({(0,): 5000.0}, steps=500, record=rec, seed=1)
    r2 = chain.run({(0,): 50000.0}, steps=500, record=rec, seed=1)
    assert r1["in"].mean() == pytest.approx(r2["in"].mean())
    # the ceiling is 1 spike per dt minus the refractory period
    assert r1["in"].mean() < 1000.0 / chain.p.dt


def test_refractory_period_caps_the_firing_rate(chain):
    """refractory 2.2 ms / dt 0.2 ms -> 11 steps -> about 416 Hz."""
    r = chain.run({(0,): 100000.0}, steps=2000,
                  record={"in": np.array([0])}, seed=1)
    hz = float(r["in"].mean())
    assert 380.0 < hz < 460.0


def test_drive_injection_is_a_voltage_clamp_not_a_current(flysim, tmp_path):
    """
    flysim.py:151 ``v[hit] = thresh + 1.0`` overwrites the membrane potential
    rather than adding to it. A driven neuron's own synaptic input is
    therefore discarded on any step where the drive fires -- the stimulated
    population is effectively feed-forward while the drive is on. Recorded
    because a sensory encoder that stimulates a recurrent population would be
    silently overriding it.
    """
    g = Graph(
        [Neuron("A"), Neuron("B", nt="gaba")],
        [("B", "A", 200.0)],           # strong inhibition onto the driven cell
    )
    fb = flysim.FlyBrain(graph_path=write_graph_npz(g, tmp_path / "clamp.npz"))
    r = fb.run({(0,): 4000.0, (1,): 4000.0}, steps=500,
               record={"A": np.array([0])}, seed=1)
    assert r["A"].mean() > 300.0       # inhibition did not suppress it at all


def test_record_counts_are_spikes_per_neuron_per_second(chain):
    """flysim.py:181-182: counts / (steps * dt / 1000)."""
    steps = 1000
    r = chain.run({(0,): 100000.0}, steps=steps,
                  record={"in": np.array([0])}, seed=1)
    secs = steps * chain.p.dt / 1000.0
    assert secs == pytest.approx(0.2)
    assert r["in"].mean() == pytest.approx(round(r["in"].mean() * secs) / secs,
                                           rel=1e-6)


def test_there_is_no_spontaneous_activity_at_all(chain):
    """
    The single most load-bearing fact for a Phase-One decoder.

    ``v`` starts at ``v_rest`` = -52 mV (flysim.py:26, 101), threshold is
    -45 mV (flysim.py:27), the leak pulls toward rest, and the only thing that
    can push a neuron over is the external drive at flysim.py:151. With no
    drive nothing fires, ever -- there is no noise term, no bias current and
    no resting rate anywhere in the model.

    So a 0 Hz readout means "not stimulated", not "chose to stay still", and
    WAIT cannot be decoded as the absence of activity without saying so.
    """
    r = chain.run({}, steps=5000, record={"all": np.arange(chain.n)}, seed=0)
    assert r["_spikes_per_sec"] == 0.0
    assert r["all"].sum() == 0.0
    assert len(r["_fired"]) == 0
    assert r["_mean_mv"] == pytest.approx(chain.p.v_rest)
