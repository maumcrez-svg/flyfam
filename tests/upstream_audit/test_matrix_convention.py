"""
(a) What convention does the upstream matrix actually use?

Established by running upstream ``build_graph.main()`` and ``flysim.FlyBrain``
over graphs whose direction is known by construction -- not by reading the
comments.

Claims under test, with the lines they come from:

  build_graph.py:97  ``r = idx.loc[post_a]``  -- row = postsynaptic
  build_graph.py:98  ``c = idx.loc[pre_a]``   -- col = presynaptic
  build_graph.py:99  ``v = wt_a * MV_PER_SYNAPSE * sign[c]`` -- sign is the
                     PREsynaptic neuron's transmitter
  build_graph.py:101 ``keep = v != 0.0``      -- zero-signed edges are dropped
  flysim.py:41       ``self.W = W.tocsc()``   -- storage only; W[i, j] stays
                     post-by-pre
  flysim.py:166-174  spike propagation gathers CSC column ``fired`` and adds
                     into ``v`` at ``indices`` -- so the gathered indices are
                     postsynaptic targets
  flysim.py:173      ``gain_per_neuron[fired]`` -- gains scale OUTGOING weight
"""
from __future__ import annotations

import numpy as np
import pytest

from .synthetic import Graph, Neuron, build_via_upstream, write_graph_npz


def test_build_graph_rows_are_postsynaptic(tmp_path, upstream_path):
    """A -> B must land at W[B, A], not W[A, B]."""
    g = Graph(
        [Neuron("A"), Neuron("B")],
        [("A", "B", 50.0)],
    )
    import scipy.sparse as sp
    z = np.load(build_via_upstream(g, tmp_path), allow_pickle=False)
    W = sp.csr_matrix((z["data"], z["indices"], z["indptr"]),
                      shape=tuple(z["shape"])).toarray()
    a, b = 0, 1
    assert W[b, a] == pytest.approx(50.0 * 0.275)
    assert W[a, b] == 0.0


def test_sign_comes_from_the_presynaptic_transmitter(tmp_path):
    """An inhibitory presynaptic neuron makes the edge negative."""
    import scipy.sparse as sp
    g = Graph(
        [Neuron("A", nt="gaba"), Neuron("B", nt="acetylcholine")],
        [("A", "B", 50.0), ("B", "A", 50.0)],
    )
    z = np.load(build_via_upstream(g, tmp_path), allow_pickle=False)
    W = sp.csr_matrix((z["data"], z["indices"], z["indptr"]),
                      shape=tuple(z["shape"])).toarray()
    assert W[1, 0] < 0          # gaba A -> B
    assert W[0, 1] > 0          # ach  B -> A


def test_dopaminergic_edges_are_deleted_by_the_sign_rule(tmp_path):
    """
    SIGN['dopamine'] == 0.0 and ``keep = v != 0.0``, so every edge whose
    presynaptic neuron is dopaminergic is absent from the shipped matrix.

    This is the fact that decides whether mushroom.py's documented
    PAM-input-vs-PPL1-input comparison is even computable on graph.npz.
    """
    import scipy.sparse as sp
    g = Graph(
        [Neuron("PAM_x", nt="dopamine"), Neuron("MBON_avoid")],
        [("PAM_x", "MBON_avoid", 100.0)],
    )
    z = np.load(build_via_upstream(g, tmp_path), allow_pickle=False)
    W = sp.csr_matrix((z["data"], z["indices"], z["indptr"]),
                      shape=tuple(z["shape"])).toarray()
    assert W.sum() == 0.0
    assert int(z["shape"][0]) == 2


def test_propagation_runs_pre_to_post(tmp_path, flysim):
    """Driving A makes B fire. Driving B does not make A fire."""
    g = Graph([Neuron("A"), Neuron("B")], [("A", "B", 60.0)])
    p = write_graph_npz(g, tmp_path / "graph.npz")
    fb = flysim.FlyBrain(graph_path=p)

    a, b = np.array([0]), np.array([1])
    fwd = fb.run({tuple(a): 300.0}, steps=500,
                 record={"A": a, "B": b}, seed=1)
    assert fwd["A"].mean() > 100.0
    assert fwd["B"].mean() > 100.0

    rev = fb.run({tuple(b): 300.0}, steps=500,
                 record={"A": a, "B": b}, seed=1)
    assert rev["B"].mean() > 100.0
    assert rev["A"].mean() == 0.0


def test_inhibitory_presynaptic_does_not_drive_its_target(tmp_path, flysim):
    g = Graph([Neuron("A", nt="gaba"), Neuron("B")], [("A", "B", 60.0)])
    p = write_graph_npz(g, tmp_path / "graph.npz")
    fb = flysim.FlyBrain(graph_path=p)
    r = fb.run({(0,): 300.0}, steps=500,
               record={"B": np.array([1])}, seed=1)
    assert r["B"].mean() == 0.0


def test_gains_scale_outgoing_not_incoming(tmp_path, flysim):
    """
    ``gain_per_neuron[fired]`` at flysim.py:173 multiplies the weight of the
    firing (presynaptic) neuron. Silencing A's type must silence B; silencing
    B's own type must not.
    """
    g = Graph([Neuron("A"), Neuron("B")], [("A", "B", 60.0)])
    p = write_graph_npz(g, tmp_path / "graph.npz")
    fb = flysim.FlyBrain(graph_path=p)
    b = np.array([1])

    names = list(fb.type_names)
    zero_a = np.ones(fb.n_types, dtype=np.float32)
    zero_a[names.index("A")] = 0.0
    zero_b = np.ones(fb.n_types, dtype=np.float32)
    zero_b[names.index("B")] = 0.0

    base = fb.run({(0,): 300.0}, steps=500, record={"B": b}, seed=1)["B"].mean()
    off_a = fb.run({(0,): 300.0}, steps=500, gains=zero_a,
                   record={"B": b}, seed=1)["B"].mean()
    off_b = fb.run({(0,): 300.0}, steps=500, gains=zero_b,
                   record={"B": b}, seed=1)["B"].mean()

    assert base > 100.0
    assert off_a == 0.0
    assert off_b == pytest.approx(base)


def test_build_graph_crashes_if_the_highest_bodyid_has_no_kept_edge(tmp_path):
    """
    Minor upstream robustness bug, found by running it.

    build_graph.py:75 sizes its lookup table from ``max(pre_a.max(),
    post_a.max())`` -- the largest bodyId *in the >=3-synapse weight table* --
    and then indexes it with every traced bodyId at line 76. A traced neuron
    whose bodyId exceeds that maximum raises IndexError. Nothing in the
    pipeline guarantees it cannot happen; it merely does not happen on the
    published dataset.
    """
    g = Graph(
        [Neuron("A"), Neuron("B"), Neuron("Z_unconnected")],
        [("A", "B", 50.0)],
    )
    with pytest.raises(IndexError):
        build_via_upstream(g, tmp_path)
