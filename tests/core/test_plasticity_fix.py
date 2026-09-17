"""
The five proofs the canonical amendment §3 requires, on a small synthetic
graph whose orientation is fixed by construction.

    - orientação DAN→alvo                                     (1)
    - preservação das conexões modulatórias                   (2)
    - seleção correta das sinapses KC→MBON                    (3)
    - atualização somente das sinapses elegíveis              (4)
    - aplicação efetiva dos pesos atualizados na simulação
      seguinte                                                (5)

``tests/upstream_audit/`` stays byte-identical: the upstream defect keeps its
two strict xfails and is not "fixed" by editing upstream or weakening an
assertion. These are tests of *our* code.
"""
from __future__ import annotations

import numpy as np
import pytest

from flytrade import graph as G
from flytrade import mushroom as M

from . import synthetic


def _mb(out_dir, flysim, **kw):
    fb = flysim.FlyBrain(graph_path=out_dir / "graph.npz")
    mod = G.ModulatoryGraph(out_dir / "graph_mod.npz", bodies=fb.bodies)
    i = synthetic.index_of
    kc = np.array([i("KC_a"), i("KC_b")])
    mbon = np.array([i("MBON_pam"), i("MBON_ppl1")])
    pam = np.array([i("PAM_x")])
    ppl1 = np.array([i("PPL1_y")])
    return fb, mod, M.MushroomBody(fb, mod, kc, mbon, pam, ppl1, **kw)


# -- (1) DAN -> target orientation -------------------------------------------

def test_compartments_come_from_dan_to_mbon_input_not_mbon_to_dan_feedback(
        synth, flysim):
    """PAM_x innervates MBON_pam; the feedback edges point the other way.

    Upstream's ``W[pam][:, mbon]`` would answer ``MBON_ppl1`` here, because the
    feedback in this graph is crossed. Ours answers ``MBON_pam``.
    """
    fb, mod, mb = _mb(synth, flysim)
    i = synthetic.index_of
    assert list(mb.pam_side) == [i("MBON_pam")]
    assert list(mb.ppl1_side) == [i("MBON_ppl1")]
    assert list(mb.compartments.unclassified) == []

    # and it is genuinely the [post, pre] read. Ours:
    D = mod.D
    mbon = mb.mbon
    pam = np.array([i("PAM_x")])
    ppl1 = np.array([i("PPL1_y")])
    documented = (np.asarray(D[mbon][:, pam].sum(axis=1)).ravel(),
                  np.asarray(D[mbon][:, ppl1].sum(axis=1)).ravel())
    assert list(mbon[documented[0] > documented[1]]) == [i("MBON_pam")]

    # upstream's read, on the matrix upstream reads it from (mushroom.py:67):
    # W[pam][:, mbon] is MBON->PAM feedback, and on this graph it answers the
    # other MBON. Reproduced here so the two readings are visibly different on
    # the same data, not merely asserted to be.
    W = fb.W
    up = (np.abs(np.asarray(W[pam][:, mbon].sum(axis=0)).ravel()),
          np.abs(np.asarray(W[ppl1][:, mbon].sum(axis=0)).ravel()))
    assert list(mbon[up[0] > up[1]]) == [i("MBON_ppl1")]


def test_dan_to_mbon_edge_weights_are_the_synapse_counts_we_put_in(
        synth, flysim):
    fb, mod, mb = _mb(synth, flysim)
    i = synthetic.index_of
    assert mod.D[i("MBON_pam"), i("PAM_x")] == pytest.approx(100.0)
    assert mod.D[i("MBON_ppl1"), i("PPL1_y")] == pytest.approx(100.0)
    # ... and nothing in the other direction, because there is no such edge
    assert mod.D[i("PAM_x"), i("MBON_pam")] == 0.0


def test_removing_the_feedback_does_not_change_our_answer(tmp_path, flysim):
    """Mirror of the upstream test: upstream's split is *determined* by the
    feedback edges. Ours must not move when they are deleted."""
    out = synthetic.build(tmp_path, mbon_to_dan=False)
    fb, mod, mb = _mb(out, flysim)
    i = synthetic.index_of
    assert list(mb.pam_side) == [i("MBON_pam")]
    assert list(mb.ppl1_side) == [i("MBON_ppl1")]


def test_removing_the_dan_input_leaves_the_mbons_unclassified(
        tmp_path, flysim):
    """The converse: with no DAN->MBON edge there is no evidence, and we say
    so instead of inventing a split out of the feedback."""
    out = synthetic.build(tmp_path, dan_to_mbon=False)
    fb, mod, mb = _mb(out, flysim)
    assert list(mb.pam_side) == []
    assert list(mb.ppl1_side) == []
    assert sorted(mb.compartments.unclassified) == sorted(mb.mbon)
    mb.observe(np.array([synthetic.index_of("KC_a")]))
    assert mb.dopamine(+1) == 0
    assert mb.dopamine(-1) == 0


# -- (2) the modulatory connections survive the build -------------------------

def test_the_sign_rule_deletes_dan_edges_from_the_fast_matrix(synth, flysim):
    """The defect's root cause, reproduced on our own build: dopamine is
    signed 0.0 and the zero-valued edge is dropped, so the fast matrix has no
    DAN->MBON edge at all. That is why part 1 of the fix is needed."""
    fb = flysim.FlyBrain(graph_path=synth / "graph.npz")
    i = synthetic.index_of
    assert fb.W[i("MBON_pam"), i("PAM_x")] == 0.0
    assert fb.W[i("MBON_ppl1"), i("PPL1_y")] == 0.0
    assert G.SIGN["dopamine"] == 0.0


def test_the_modulatory_matrix_keeps_them_and_the_anatomy_keeps_everything(
        synth, flysim):
    import scipy.sparse as sp
    i = synthetic.index_of
    z = np.load(synth / "graph_anat.npz", allow_pickle=False)
    A = sp.csr_matrix((z["data"], z["indices"], z["indptr"]),
                      shape=tuple(z["shape"]))
    # anatomy: non-negative, and the dopaminergic edges are present
    assert (A.data >= 0).all()
    assert A[i("MBON_pam"), i("PAM_x")] == pytest.approx(100.0)

    zm = np.load(synth / "graph_mod.npz", allow_pickle=False)
    D = sp.csr_matrix((zm["data"], zm["indices"], zm["indptr"]),
                      shape=tuple(zm["shape"]))
    assert (D.data > 0).all(), "modulatory weights are unsigned synapse counts"
    assert D.nnz == 2, "only the two DAN->MBON edges are dopaminergic here"
    # dopamine is never turned into fast excitation
    assert D.dtype == np.float32
    assert D[i("MBON_pam"), i("PAM_x")] == pytest.approx(100.0)


def test_all_three_matrices_share_one_index_and_shape(synth, flysim):
    import scipy.sparse as sp
    fb = flysim.FlyBrain(graph_path=synth / "graph.npz")
    for name in ("graph_anat.npz", "graph_mod.npz"):
        z = np.load(synth / name, allow_pickle=False)
        assert np.array_equal(z["bodies"], fb.bodies)
        assert tuple(z["shape"]) == fb.W.shape
    # and a mismatched index is refused rather than silently misapplied
    with pytest.raises(ValueError):
        G.ModulatoryGraph(synth / "graph_mod.npz",
                          bodies=fb.bodies[::-1].copy())


# -- (3) KC -> MBON synapse selection ----------------------------------------

def test_kc_to_mbon_selection_is_presynaptic_kc_postsynaptic_mbon(
        synth, flysim):
    fb, mod, mb = _mb(synth, flysim)
    i = synthetic.index_of
    assert len(mb.pos) == 4
    assert set(mb.pre.tolist()) == {i("KC_a"), i("KC_b")}
    assert set(mb.post.tolist()) == {i("MBON_pam"), i("MBON_ppl1")}
    # every position really indexes that synapse in the running simulation
    for pos, pre, post in zip(mb.pos, mb.pre, mb.post):
        assert fb.wdata[pos] == fb.W[int(post), int(pre)]
    # the MBON->DAN feedback edges are NOT selected, though they touch MBONs
    for pos in mb.pos:
        assert int(fb.indices[pos]) in {i("MBON_pam"), i("MBON_ppl1")}


def test_selection_ignores_non_kc_inputs_to_mbons(synth, flysim):
    """APL->KC and ORN->KC are in the graph; neither may enter ``pos``."""
    fb, mod, mb = _mb(synth, flysim)
    i = synthetic.index_of
    assert i("APL") not in set(mb.pre.tolist())
    assert i("ORN_TEST") not in set(mb.pre.tolist())


# -- (4) only eligible synapses are updated ----------------------------------

def test_only_the_addressed_compartment_is_depressed(synth, flysim):
    fb, mod, mb = _mb(synth, flysim)
    i = synthetic.index_of
    mb.observe(np.array([i("KC_a"), i("KC_b")]))
    n = mb.dopamine(+1, 1.0)
    assert n == 2                               # two KCs onto MBON_pam
    assert (mb.gain[mb.post == i("MBON_pam")] < 1.0).all()
    assert (mb.gain[mb.post == i("MBON_ppl1")] == 1.0).all()


def test_only_the_kenyon_cells_that_fired_are_depressed(synth, flysim):
    fb, mod, mb = _mb(synth, flysim)
    i = synthetic.index_of
    mb.observe(np.array([i("KC_a")]))           # KC_b silent
    assert mb.dopamine(+1, 1.0) == 1
    hit = (mb.pre == i("KC_a")) & (mb.post == i("MBON_pam"))
    assert (mb.gain[hit] < 1.0).all()
    assert (mb.gain[~hit] == 1.0).all()


def test_mbon_activity_alone_makes_nothing_eligible(synth, flysim):
    fb, mod, mb = _mb(synth, flysim)
    i = synthetic.index_of
    mb.observe(np.array([i("MBON_pam"), i("MBON_ppl1"), i("PAM_x")]))
    assert mb.trace.max() == 0.0
    assert mb.dopamine(+1, 1.0) == 0
    assert (mb.gain == 1.0).all()


def test_a_decayed_trace_stops_being_eligible(synth, flysim):
    fb, mod, mb = _mb(synth, flysim, trace_decay=0.55)
    i = synthetic.index_of
    mb.observe(np.array([i("KC_a"), i("KC_b")]))
    for _ in range(6):                          # 0.55**6 = 0.0277 < 0.05
        mb.observe(None)
    assert mb.trace.max() < M.TRACE_EPS
    assert mb.dopamine(+1, 1.0) == 0
    assert (mb.gain == 1.0).all()


def test_reinforcement_never_reaches_another_episodes_trace(synth, flysim):
    """Canonical §6: a delayed outcome must not be applied to the activity of
    a different episode."""
    fb, mod, mb = _mb(synth, flysim)
    i = synthetic.index_of
    mb.begin_episode(7)
    mb.observe(np.array([i("KC_a"), i("KC_b")]))
    mb.begin_episode(8)                          # the trace still exists ...
    assert mb.trace.max() == 1.0
    assert mb.dopamine(+1, 1.0) == 0             # ... but belongs to episode 7
    assert (mb.gain == 1.0).all()
    assert mb.events["rejected_episode"] == 4
    # the reward for the episode that earned it still lands
    assert mb.dopamine(+1, 1.0, episode_id=7) == 2


def test_depression_has_a_floor_and_never_potentiates(synth, flysim):
    fb, mod, mb = _mb(synth, flysim)
    i = synthetic.index_of
    before = mb.gain.copy()
    for _ in range(500):
        mb.observe(np.array([i("KC_a"), i("KC_b")]))
        mb.dopamine(+1, 1.0)
        mb.dopamine(-1, 1.0)
    assert (mb.gain <= before + 1e-9).all()
    assert mb.gain.min() == pytest.approx(mb.floor)
    assert mb.gain.max() <= 1.0


def test_forgetting_drifts_back_toward_baseline(synth, flysim):
    fb, mod, mb = _mb(synth, flysim)
    i = synthetic.index_of
    mb.observe(np.array([i("KC_a"), i("KC_b")]))
    mb.dopamine(+1, 1.0)
    mb.dopamine(-1, 1.0)
    low = mb.gain.copy()
    for _ in range(3000):
        mb.forget()
    assert (mb.gain >= low).all()
    assert (mb.gain <= 1.0 + 1e-6).all()


# -- (5) the updated weights are used by the next simulation -----------------

def _mbon_rate(fb, mb, kc_drive_hz=400.0, steps=200, seed=0):
    i = synthetic.index_of
    drive = {(i("ORN_TEST"),): kc_drive_hz}
    r = fb.run(drive, steps=steps, record={
        "pam": np.array([i("MBON_pam")]),
        "ppl1": np.array([i("MBON_ppl1")]),
        "kc": np.array([i("KC_a"), i("KC_b")]),
    }, seed=seed)
    return {k: float(r[k].mean()) for k in ("pam", "ppl1", "kc")}


def test_the_stimulus_reaches_the_kenyon_cells_and_the_mbons(synth, flysim):
    fb, mod, mb = _mb(synth, flysim)
    before = _mbon_rate(fb, mb)
    assert before["kc"] > 0.0
    assert before["pam"] > 0.0 and before["ppl1"] > 0.0


def test_applied_gains_change_the_next_simulations_mbon_rate(synth, flysim):
    """The whole point: depression must be visible in the *behaviour* of the
    next run, not only in the gain array."""
    fb, mod, mb = _mb(synth, flysim)
    i = synthetic.index_of
    before = _mbon_rate(fb, mb)

    for _ in range(400):                        # drive the gain to the floor
        mb.observe(np.array([i("KC_a"), i("KC_b")]))
        mb.dopamine(+1, 1.0)
    assert mb.gain[mb.post == i("MBON_pam")].max() == pytest.approx(mb.floor)
    mb.apply()

    after = _mbon_rate(fb, mb)
    assert after["pam"] < before["pam"], "the depressed compartment must fall"
    assert after["ppl1"] == pytest.approx(before["ppl1"]), \
        "the compartment no dopamine addressed must not move"
    assert after["kc"] == pytest.approx(before["kc"]), \
        "KC drive is upstream of the plastic synapse and must not move"


def test_apply_preserves_every_synapse_sign_and_only_shrinks_magnitude(
        synth, flysim):
    fb, mod, mb = _mb(synth, flysim)
    i = synthetic.index_of
    mb.observe(np.array([i("KC_a"), i("KC_b")]))
    mb.dopamine(+1, 1.0)
    mb.dopamine(-1, 1.0)
    mb.apply()
    assert np.allclose(fb.wdata[mb.pos], mb.base * mb.gain)
    assert (np.abs(fb.wdata[mb.pos]) <= np.abs(mb.base) + 1e-9).all()
    assert (np.sign(fb.wdata[mb.pos]) == np.sign(mb.base)).all()


def test_nothing_outside_the_kc_to_mbon_synapses_is_ever_written(
        synth, flysim):
    fb, mod, mb = _mb(synth, flysim)
    i = synthetic.index_of
    untouched = fb.wdata.copy()
    mb.observe(np.array([i("KC_a"), i("KC_b")]))
    mb.dopamine(+1, 1.0)
    mb.dopamine(-1, 1.0)
    mb.apply()
    mask = np.ones(len(untouched), dtype=bool)
    mask[mb.pos] = False
    assert np.array_equal(fb.wdata[mask], untouched[mask])
