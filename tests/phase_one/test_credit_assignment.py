"""
Canonical amendment §5 — episode-specific credit assignment.

One test, as Fable addendum 10 requires, and it is the concrete one the
amendment names: **evaluate A, then B, select A, settle A.** It asserts both
halves of the claim, because the amendment says the rejection counter alone
settles nothing:

* the correct trace **is accepted** — weights change, and they change exactly
  on the synapses A's own presentation made eligible in the addressed
  compartment, and nowhere else;
* B's trace, an unrelated episode's, an expired trace and an already-settled
  episode are all refused, each with its own counter.
"""
from __future__ import annotations

import numpy as np

from flytrade import decoder as D
from flytrade import encoder as E
from flytrade import market as MK
from flytrade import mushroom as M
from flytrade import runner as R

from .conftest import requires_real_graph

SYMBOLS = ("AAA", "BBB")
ROUND_INDEX = 11
ROUND_SEED = 555
CUTOFF = 300


@requires_real_graph
def test_evaluate_a_then_b_select_a_settle_a(brain, ann, fresh_weights):
    fb, mb, gains = brain
    enc = E.MarketToSensoryEncoder(ann)
    dec = D.ActionDecoder()
    run = R.BrainRunner(fb, mb, enc, D.readout_populations(ann, mb.compartments),
                        gains=gains)
    credit = R.CreditAssigner(mb)

    series = {s: MK.synthetic_series(s, seed=910 + i)
              for i, s in enumerate(SYMBOLS)}
    feed = MK.ObservationFeed(series)
    universe = MK.Universe(SYMBOLS)

    # --- evaluate A then B, under one frozen learned state ---------------
    rnd = run.evaluate_round(
        [feed.observe(s, CUTOFF, stable_id=universe.stable_id(s))
         for s in SYMBOLS],
        round_index=ROUND_INDEX, round_seed=ROUND_SEED,
        # select A deliberately, so the test controls which episode is open
        score=lambda c: 1.0 if c.symbol == SYMBOLS[0] else 0.0)

    a = rnd.by_symbol(SYMBOLS[0])
    b = rnd.by_symbol(SYMBOLS[1])
    assert rnd.selected is a
    assert a.episode_id != b.episode_id
    assert a.trace.n_eligible > 0 and b.trace.n_eligible > 0

    # B made some synapses eligible that A did not: that difference is what
    # makes the test able to tell the two traces apart at all
    only_b = np.setdiff1d(b.trace.index, a.trace.index)
    assert len(only_b) > 0

    credit.open_episode(a.trace)
    baseline = mb.gain.copy()

    # --- the wrong traces are refused, each for its own reason -----------
    ev = credit.settle(a.episode_id, -1, 1.0, trace=b.trace)
    assert not ev.accepted
    assert ev.reason == R.RejectionReason.EPISODE_MISMATCH.value
    assert np.array_equal(mb.gain, baseline)

    ev = credit.settle(b.episode_id, -1, 1.0)
    assert not ev.accepted
    assert ev.reason == R.RejectionReason.UNKNOWN_EPISODE.value
    assert np.array_equal(mb.gain, baseline)

    stale = R.StoredTrace(episode_id=a.episode_id, index=a.trace.index,
                          value=a.trace.value * (M.TRACE_EPS / 2.0),
                          n_synapses=a.trace.n_synapses)
    ev = credit.settle(a.episode_id, -1, 1.0, trace=stale)
    assert not ev.accepted
    assert ev.reason == R.RejectionReason.TRACE_EXPIRED.value
    assert np.array_equal(mb.gain, baseline)

    wrong_shape = R.StoredTrace(episode_id=a.episode_id, index=a.trace.index,
                                value=a.trace.value, n_synapses=7)
    ev = credit.settle(a.episode_id, -1, 1.0, trace=wrong_shape)
    assert not ev.accepted
    assert ev.reason == R.RejectionReason.SHAPE_MISMATCH.value
    assert np.array_equal(mb.gain, baseline)

    # --- the correct trace IS accepted -----------------------------------
    ev = credit.settle(a.episode_id, -1, 1.0)
    assert ev.accepted
    assert ev.synapses_depressed > 0
    assert ev.eligibility_source == "replayed_from_decision"
    assert ev.episode_id == a.episode_id

    moved = np.flatnonzero(mb.gain != baseline)
    assert len(moved) == ev.synapses_depressed > 0
    # every moved synapse was eligible in A's own presentation ...
    assert set(int(i) for i in moved) <= set(int(i) for i in a.trace.index)
    # ... and sits in the compartment the valence addressed, PPL1-innervated
    assert (mb.side[moved] == -1).all()
    # nothing that only B made eligible moved
    assert not (set(int(i) for i in only_b) & set(int(i) for i in moved))
    # and the expected set is exactly the one that moved: A's eligible
    # synapses on the addressed side
    expected = a.trace.index[mb.side[a.trace.index] == -1]
    assert np.array_equal(np.sort(moved), np.sort(expected))
    # the learned change reached the weights the simulator reads
    assert np.array_equal(fb.wdata[mb.pos], mb.base * mb.gain)

    # --- settling twice is refused, and changes nothing ------------------
    after = mb.gain.copy()
    ev = credit.settle(a.episode_id, -1, 1.0, trace=a.trace)
    assert not ev.accepted
    assert ev.reason == R.RejectionReason.ALREADY_SETTLED.value
    assert np.array_equal(mb.gain, after)

    # --- counters are separated by reason --------------------------------
    st = credit.stats()
    assert st["accepted"] == 1
    assert st["rejections"] == {
        R.RejectionReason.EPISODE_MISMATCH.value: 1,
        R.RejectionReason.ALREADY_SETTLED.value: 1,
        R.RejectionReason.UNKNOWN_EPISODE.value: 1,
        R.RejectionReason.TRACE_EXPIRED.value: 1,
        R.RejectionReason.SHAPE_MISMATCH.value: 1,
    }
    assert st["rejections_total"] == 5
    assert st["open"] == []
    assert st["settled"] == 1

    # --- the live eligibility layer is empty afterwards -------------------
    assert not (mb.trace > M.TRACE_EPS).any()
    assert (mb.trace_episode == -1).all()
