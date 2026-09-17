"""
Canonical amendment §4 — reinforcement has to reach the *decoder*.

The full demonstration, with its controls, its eight seeds and its
pre-registered decision rule, is
``experiments/phase_one/learning_demo.py``. These are the integration tests
that keep it from silently breaking: one per reinforcement branch, one for
plasticity disabled, and one that the reinforcement travels the modulatory
matrix rather than being written into the weights by hand.

A counter increment and a changed weight are explicitly not enough
(amendment §4), so every test here asserts on the decoder's own output.
"""
from __future__ import annotations

import numpy as np
import pytest

from flytrade import decoder as D
from flytrade import encoder as E
from flytrade import market as MK
from flytrade import runner as R

from .conftest import requires_real_graph

TRIALS = 12
REPEATS = 8
MEASURE_SEED = 1010
TRAIN_SEED0 = 4000


def _setup(brain, ann):
    fb, mb, gains = brain
    enc = E.MarketToSensoryEncoder(ann)
    dec = D.ActionDecoder()
    pops = D.readout_populations(ann, mb.compartments)
    return R.BrainRunner(fb, mb, enc, pops, gains=gains), dec


def _contexts(run, ann):
    """The v2 rule: the extreme twenty-bar returns over a declared window."""
    k = MK.FEATURES.index("r20")
    syms = tuple(f"CTX{i}" for i in range(4))
    feed = MK.ObservationFeed({s: MK.synthetic_series(s, seed=900 + i)
                               for i, s in enumerate(syms)})
    uni = MK.Universe(syms)
    best = []
    for sym in syms:
        for i in range(200, min(420, feed.bars(sym))):
            o = feed.observe(sym, i, stable_id=uni.stable_id(sym))
            if o.status.usable:
                best.append(o)
    up = max(best, key=lambda o: o.normalized[k])
    dn = min(best, key=lambda o: o.normalized[k])
    return run.encoder.encode(up), run.encoder.encode(dn)


def _measure(run, dec, stim, seed=MEASURE_SEED, repeats=REPEATS):
    s0 = run.snapshot()
    app, avo = [], []
    for m in range(repeats):
        p = run.present(stim, seed=seed + m, episode_id=-1, observe=False)
        app.append(p.mean(D.APPROACH))
        avo.append(p.mean(D.AVOID))
    run.restore(s0)
    return dec.decode_rates(float(np.mean(app)), float(np.mean(avo)))


def _train(run, mb, stim, valence, trials=TRIALS, plastic=True):
    for t in range(trials):
        ep = 50_000 + t
        run.present(stim, seed=TRAIN_SEED0 + t, episode_id=ep)
        if plastic:
            mb.dopamine(valence, 1.0, episode_id=ep)
            mb.apply()
            mb.forget()


@requires_real_graph
@pytest.mark.parametrize("valence,name", [(+1, "appetitive"), (-1, "aversive")])
def test_reinforcement_moves_the_decoders_output_in_the_declared_direction(
        brain, ann, fresh_weights, valence, name):
    """docs/DECODER.md §3: appetitive raises V, aversive lowers it."""
    fb, mb, _ = brain
    run, dec = _setup(brain, ann)
    stim_x, _ = _contexts(run, ann)

    before = _measure(run, dec, stim_x)
    _train(run, mb, stim_x, valence)
    after = _measure(run, dec, stim_x)

    dv = after.valence_hz - before.valence_hz
    if valence > 0:
        assert dv > 0, f"{name}: V moved {dv:+.3f} Hz, expected up"
        # appetitive addresses the PAM-innervated compartment, i.e. `avoid`
        assert after.avoid_hz < before.avoid_hz
        assert (mb.gain[mb.side == -1] == 1.0).all()
    else:
        assert dv < 0, f"{name}: V moved {dv:+.3f} Hz, expected down"
        assert after.approach_hz < before.approach_hz
        assert (mb.gain[mb.side == 1] == 1.0).all()
    assert before.status is after.status is D.ReadoutStatus.VALID


@requires_real_graph
@pytest.mark.parametrize("valence", [+1, -1])
def test_disabled_plasticity_removes_the_change_exactly(brain, ann,
                                                        fresh_weights, valence):
    fb, mb, _ = brain
    run, dec = _setup(brain, ann)
    stim_x, _ = _contexts(run, ann)

    before = _measure(run, dec, stim_x)
    _train(run, mb, stim_x, valence, plastic=False)
    after = _measure(run, dec, stim_x)

    assert after.valence_hz == before.valence_hz
    assert after.approach_hz == before.approach_hz
    assert after.avoid_hz == before.avoid_hz
    assert after.action is before.action
    assert (mb.gain == 1.0).all()
    assert mb.events == {"reward": 0, "punish": 0, "rejected_episode": 0}


@requires_real_graph
def test_the_effect_depends_on_the_eligible_sensory_experience(brain, ann,
                                                               fresh_weights):
    """Training on a different market context moves X less than training on X."""
    fb, mb, _ = brain
    run, dec = _setup(brain, ann)
    stim_x, stim_y = _contexts(run, ann)

    before = _measure(run, dec, stim_x)
    _train(run, mb, stim_x, +1)
    paired = _measure(run, dec, stim_x).valence_hz - before.valence_hz

    mb.gain[:] = 1.0
    mb.trace[:] = 0.0
    mb.trace_episode[:] = -1
    mb.apply()

    before2 = _measure(run, dec, stim_x)
    _train(run, mb, stim_y, +1)
    other = _measure(run, dec, stim_x).valence_hz - before2.valence_hz

    assert paired > 0 and other > 0          # depression generalises; it must
    assert paired > other, (f"paired {paired:+.3f} Hz is not larger than "
                            f"other-context {other:+.3f} Hz")


@requires_real_graph
@pytest.mark.parametrize("valence,side", [(+1, 1), (-1, -1)])
def test_reinforcement_travels_the_modulatory_matrix_not_a_direct_write(
        brain, ann, fresh_weights, valence, side):
    """Only KC->MBON synapses of the addressed compartment may move."""
    fb, mb, _ = brain
    run, dec = _setup(brain, ann)
    stim_x, _ = _contexts(run, ann)

    all_before = fb.wdata.copy()
    _train(run, mb, stim_x, valence, trials=6)

    changed = np.flatnonzero(fb.wdata != all_before)
    assert len(changed) > 0
    # every changed weight is a plastic KC->MBON synapse ...
    assert set(int(i) for i in changed) <= set(int(i) for i in mb.pos)
    # ... in the compartment the valence addresses, and nowhere else
    pos_changed = np.isin(mb.pos, changed)
    assert (mb.side[pos_changed] == side).all()
    assert (mb.gain[mb.side == -side] == 1.0).all()
    # and the weights the simulator reads are exactly base * gain. forget()
    # drifts the gain after the last apply(), so re-apply before comparing.
    mb.apply()
    assert np.array_equal(fb.wdata[mb.pos], mb.base * mb.gain)
    # the compartment map itself came from the modulatory matrix, unsigned
    assert set(int(i) for i in mb.compartments.pam_side).isdisjoint(
        int(i) for i in mb.compartments.ppl1_side)
