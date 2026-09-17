"""
(b)+(c) What convention does mushroom.py assume, and does it match (a)?

mushroom.py's own claim, verbatim from its docstring (mushroom.py:17-23):

    "Which MBONs count as reward-side and which as punishment-side is not
     hardcoded from a table. It is read out of this connectome: for each MBON,
     total PAM input weight is compared against total PPL1 input weight and
     the stronger one wins."

The lines that are supposed to do it:

    mushroom.py:66   W = fb.W            # CSC: column j = targets of pre j
    mushroom.py:67   pam_in = |W[pam][:, mbon].sum(axis=0)|
    mushroom.py:68   ppl_in = |W[ppl1][:, mbon].sum(axis=0)|
    mushroom.py:69   reward_side = mbon[pam_in > ppl_in]
    mushroom.py:70   punish_side = mbon[ppl_in > pam_in]

Under the convention established in test_matrix_convention.py -- W[i, j] is
post-by-pre -- ``W[pam]`` selects PAM neurons as POSTsynaptic and
``[:, mbon]`` selects MBONs as PREsynaptic. ``pam_in`` is therefore the
MBON->PAM feedback weight, not the PAM->MBON dopaminergic input the docstring
names. Both are real circuits and they are not the same circuit.

The rest of mushroom.py uses the convention correctly:

    mushroom.py:82-88  gathers CSC column ``k`` for each KC and keeps targets
                       that are MBONs -- presynaptic KC, postsynaptic MBON,
                       which is the right way round
    mushroom.py:116    ``trace[active[self.pre]] = 1.0`` -- eligibility keyed
                       on the presynaptic Kenyon cell
    mushroom.py:131    gain multiplied by (1 - lr*amount*trace) -- depression
                       only, never potentiation

These tests run unmodified upstream code over graphs built in
``synthetic.py`` whose orientation is fixed by construction.
"""
from __future__ import annotations

import numpy as np
import pytest

from .synthetic import (Graph, Neuron, build_via_upstream, mb_graph,
                        write_graph_npz)

INCONSISTENT = (
    "UPSTREAM DEFECT (mushroom.py:67-68): pam_in/ppl_in read W[dan][:, mbon], "
    "which under the post-by-pre convention of build_graph.py:97-98 is "
    "MBON->DAN feedback, not the DAN->MBON dopaminergic input the docstring "
    "claims. Not patched in this wave by instruction."
)


def _mb(mushroom, flysim, tmp_path, *, dan_to_mbon=True, mbon_to_dan=True,
        apply_sign_rule=False, name="g.npz"):
    """A MushroomBody over a synthetic graph, upstream code unmodified.

    ``apply_sign_rule=False`` is the charitable setting: it leaves DAN->MBON
    edges in the matrix at full weight, which the shipped pipeline does not.
    Every orientation question is asked under that charitable setting so a
    failure cannot be blamed on the sign rule having deleted the evidence.
    """
    g = mb_graph(dan_to_mbon=dan_to_mbon, mbon_to_dan=mbon_to_dan)
    p = write_graph_npz(g, tmp_path / name, apply_sign_rule=apply_sign_rule)
    fb = flysim.FlyBrain(graph_path=p)
    mb = mushroom.MushroomBody(fb)
    idx = {t: i for i, t in enumerate(map(str, fb.types))}
    return fb, mb, idx


def _depressed(mb, idx, mbon_name):
    """Mean gain over the KC->MBON synapses landing on one MBON."""
    sel = mb.post == idx[mbon_name]
    assert sel.any()
    return float(mb.gain[sel].mean())


# --- the parts of mushroom.py that DO follow the convention -----------------

def test_kc_to_mbon_selection_is_presynaptic_kc_postsynaptic_mbon(
        mushroom, flysim, tmp_path):
    """mushroom.py:81-88 walks CSC columns of KCs; targets must be MBONs."""
    fb, mb, idx = _mb(mushroom, flysim, tmp_path)
    kc = {idx["KC_a"], idx["KC_b"]}
    mbon = {idx["MBON_approach"], idx["MBON_avoid"]}
    assert len(mb.pos) == 4
    assert set(mb.pre.tolist()) == kc
    assert set(mb.post.tolist()) == mbon
    # and the positions really point at those weights in the running sim
    for pos, pre, post in zip(mb.pos, mb.pre, mb.post):
        assert fb.wdata[pos] == fb.W[int(post), int(pre)]


def test_eligibility_is_keyed_on_the_presynaptic_kc(mushroom, flysim, tmp_path):
    """Only a synapse whose KC fired becomes eligible; MBON firing does not."""
    fb, mb, idx = _mb(mushroom, flysim, tmp_path)

    mb.observe(np.array([idx["KC_a"]]))
    assert mb.trace[mb.pre == idx["KC_a"]].min() == pytest.approx(1.0)
    assert mb.trace[mb.pre == idx["KC_b"]].max() == 0.0

    mb.trace[:] = 0.0
    mb.observe(np.array([idx["MBON_approach"], idx["MBON_avoid"]]))
    assert mb.trace.max() == 0.0


def test_dopamine_depresses_and_never_potentiates(mushroom, flysim, tmp_path):
    fb, mb, idx = _mb(mushroom, flysim, tmp_path)
    mb.observe(np.array([idx["KC_a"], idx["KC_b"]]))
    before = mb.gain.copy()
    mb.dopamine(+1, 1.0)
    mb.dopamine(-1, 1.0)
    assert (mb.gain <= before + 1e-9).all()
    assert (mb.gain < before).any()


def test_depression_stops_at_the_floor(mushroom, flysim, tmp_path):
    fb, mb, idx = _mb(mushroom, flysim, tmp_path)
    for _ in range(400):
        mb.observe(np.array([idx["KC_a"], idx["KC_b"]]))
        mb.dopamine(+1, 1.0)
        mb.dopamine(-1, 1.0)
    assert mb.gain.min() == pytest.approx(mb.floor)
    assert mb.gain.max() <= 1.0


def test_forgetting_drifts_back_toward_baseline(mushroom, flysim, tmp_path):
    fb, mb, idx = _mb(mushroom, flysim, tmp_path)
    mb.observe(np.array([idx["KC_a"], idx["KC_b"]]))
    mb.dopamine(+1, 1.0)
    mb.dopamine(-1, 1.0)
    low = mb.gain.copy()
    for _ in range(2000):
        mb.forget()
    assert (mb.gain > low).all()
    assert (mb.gain <= 1.0 + 1e-6).all()


def test_apply_writes_gains_into_the_running_weights(mushroom, flysim, tmp_path):
    fb, mb, idx = _mb(mushroom, flysim, tmp_path)
    mb.observe(np.array([idx["KC_a"], idx["KC_b"]]))
    mb.dopamine(+1, 1.0)
    mb.dopamine(-1, 1.0)
    mb.apply()
    assert np.allclose(fb.wdata[mb.pos], mb.base * mb.gain)
    # magnitude only shrinks; sign of every synapse is preserved
    assert (np.abs(fb.wdata[mb.pos]) <= np.abs(mb.base) + 1e-9).all()
    assert (np.sign(fb.wdata[mb.pos]) == np.sign(mb.base)).all()


# --- the part that does NOT -------------------------------------------------

def test_classification_ignores_dan_to_mbon_input_entirely(
        mushroom, flysim, tmp_path):
    """
    Graph containing ONLY the edges the docstring says are read:
    PAM_x -> MBON_avoid and PPL1_y -> MBON_approach, at full weight.

    Upstream finds no reward side and no punishment side, and therefore never
    learns: ``dopamine()`` returns 0 for both valences.
    """
    fb, mb, idx = _mb(mushroom, flysim, tmp_path,
                      dan_to_mbon=True, mbon_to_dan=False)
    assert len(mb.pos) == 4, "the plastic synapses are there"
    assert list(mb.reward_side) == []
    assert list(mb.punish_side) == []
    mb.observe(np.array([idx["KC_a"], idx["KC_b"]]))
    assert mb.dopamine(+1, 1.0) == 0
    assert mb.dopamine(-1, 1.0) == 0
    assert (mb.gain == 1.0).all()


def test_classification_is_driven_entirely_by_mbon_to_dan_feedback(
        mushroom, flysim, tmp_path):
    """
    Mirror image: remove every DAN->MBON edge, keep only MBON->DAN feedback.
    Upstream still produces a full split, which pins where it is really
    reading from.
    """
    fb, mb, idx = _mb(mushroom, flysim, tmp_path,
                      dan_to_mbon=False, mbon_to_dan=True)
    assert list(mb.reward_side) == [idx["MBON_approach"]]
    assert list(mb.punish_side) == [idx["MBON_avoid"]]


def test_the_split_upstream_produces_is_the_transposed_read(
        mushroom, flysim, tmp_path):
    """
    Exact characterisation of the mismatch: what upstream computes equals
    W[mbon][:, dan].T -- i.e. W[dan][:, mbon] -- rather than W[mbon][:, dan].
    """
    fb, mb, idx = _mb(mushroom, flysim, tmp_path)
    W = fb.W
    pam = np.array([idx["PAM_x"]])
    ppl = np.array([idx["PPL1_y"]])
    mbon = mb.mbon

    as_written = (np.abs(np.asarray(W[pam][:, mbon].sum(axis=0)).ravel()),
                  np.abs(np.asarray(W[ppl][:, mbon].sum(axis=0)).ravel()))
    as_documented = (np.abs(np.asarray(W[mbon][:, pam].sum(axis=1)).ravel()),
                     np.abs(np.asarray(W[mbon][:, ppl].sum(axis=1)).ravel()))

    assert list(mb.reward_side) == list(mbon[as_written[0] > as_written[1]])
    assert list(mb.reward_side) != list(mbon[as_documented[0] > as_documented[1]])
    # and the documented read is the anatomically correct one
    assert list(mbon[as_documented[0] > as_documented[1]]) == [idx["MBON_avoid"]]


def test_on_the_shipped_pipeline_the_documented_read_is_not_even_computable(
        mushroom, flysim, tmp_path):
    """
    build_graph.py gives dopamine sign 0.0 (line 28) and drops zero-valued
    edges (line 101), so no PAM->MBON or PPL1->MBON edge survives into
    graph.npz. Run through upstream's own build_graph, the documented
    comparison is 0 vs 0 for every MBON.

    Consequence: the transposition is not merely a mislabel. Correcting the
    indexing alone, against the shipped graph, would leave both sides empty
    and switch learning off. A fix needs a dopaminergic connectivity source
    the sign rule does not erase.
    """
    g = mb_graph(dan_to_mbon=True, mbon_to_dan=True)
    p = build_via_upstream(g, tmp_path)
    fb = flysim.FlyBrain(graph_path=p)
    mb = mushroom.MushroomBody(fb)
    idx = {t: i for i, t in enumerate(map(str, fb.types))}

    pam = np.array([idx["PAM_x"]])
    ppl = np.array([idx["PPL1_y"]])
    documented_pam = np.abs(np.asarray(fb.W[mb.mbon][:, pam].sum(axis=1)).ravel())
    documented_ppl = np.abs(np.asarray(fb.W[mb.mbon][:, ppl].sum(axis=1)).ravel())
    assert documented_pam.sum() == 0.0
    assert documented_ppl.sum() == 0.0

    # yet upstream still reports a full split, out of the feedback edges
    assert len(mb.reward_side) + len(mb.punish_side) == len(mb.mbon)


# --- what the intended biology requires -------------------------------------
#
# Strict xfail: these assert the biology mushroom.py's own docstring commits
# to. They are expected to fail against upstream as it stands, and pytest is
# told to fail the run if they ever start passing -- so if upstream (or a
# later wave of ours) fixes mushroom.py:67-68, this file goes red and has to
# be revisited rather than silently rotting.

@pytest.mark.xfail(strict=True, reason=INCONSISTENT)
def test_appetitive_dopamine_depresses_the_pam_innervated_compartment(
        mushroom, flysim, tmp_path):
    """
    PAM_x innervates MBON_avoid by construction. Appetitive dopamine must
    depress KC->MBON_avoid and leave KC->MBON_approach alone.
    """
    fb, mb, idx = _mb(mushroom, flysim, tmp_path)
    mb.observe(np.array([idx["KC_a"], idx["KC_b"]]))
    mb.dopamine(+1, 1.0)
    assert _depressed(mb, idx, "MBON_avoid") < 1.0
    assert _depressed(mb, idx, "MBON_approach") == 1.0


@pytest.mark.xfail(strict=True, reason=INCONSISTENT)
def test_aversive_dopamine_depresses_the_ppl1_innervated_compartment(
        mushroom, flysim, tmp_path):
    """
    PPL1_y innervates MBON_approach by construction. Aversive dopamine must
    depress KC->MBON_approach and leave KC->MBON_avoid alone.
    """
    fb, mb, idx = _mb(mushroom, flysim, tmp_path)
    mb.observe(np.array([idx["KC_a"], idx["KC_b"]]))
    mb.dopamine(-1, 1.0)
    assert _depressed(mb, idx, "MBON_approach") < 1.0
    assert _depressed(mb, idx, "MBON_avoid") == 1.0


def test_what_upstream_actually_does_instead(mushroom, flysim, tmp_path):
    """The inverted outcome, pinned so the regression is unambiguous."""
    fb, mb, idx = _mb(mushroom, flysim, tmp_path)
    mb.observe(np.array([idx["KC_a"], idx["KC_b"]]))
    mb.dopamine(+1, 1.0)
    assert _depressed(mb, idx, "MBON_approach") < 1.0   # wrong compartment
    assert _depressed(mb, idx, "MBON_avoid") == 1.0

    mb2 = mushroom.MushroomBody(flysim.FlyBrain(graph_path=tmp_path / "g.npz"))
    mb2.observe(np.array([idx["KC_a"], idx["KC_b"]]))
    mb2.dopamine(-1, 1.0)
    assert _depressed(mb2, idx, "MBON_avoid") < 1.0     # wrong compartment
    assert _depressed(mb2, idx, "MBON_approach") == 1.0
