"""
D9(b) Fable addendum 3 — the STOP condition, tested before any run existed.

D7 only ever settled episodes held **1 to 19 market minutes**. A fixed-hold
policy at H = 90 settles them 90 rounds after the decision, so the wave is
refused unless a stored eligibility trace replayed after 90 idle rounds
produces exactly the reinforcement it would have produced after 1.

"Idle" here is the real thing, not a sleep: each intervening round is a full
``BrainRunner.evaluate_round`` at k = 8 — eight ``clear_episode`` calls, eight
20 ms presentations, eight ``capture_trace`` calls and the snapshot restore
between them — so the live eligibility layer is written, cleared and rewritten
90 times between the capture and the settlement.

If this test ever fails, the fixed-hold wave stops before any neural run:
changing decay or eligibility is a science change, not an engineering fix.
"""
from __future__ import annotations

import numpy as np

from flytrade import mushroom as M
from flytrade import readout as RO
from flytrade import runner as R

from .conftest import DAYS, requires_real_graph

#: the horizon the D9(b) wave holds for, in market minutes, and therefore the
#: number of decision rounds between an entry and its settlement.
H = 90


def _usable(series, stable_id=0):
    """Every observation of the fixture the encoder would actually present."""
    out = []
    for day in DAYS:
        for m in range(120):
            o = series.observe(day, m, stable_id=stable_id)
            if o.status.usable:
                out.append(o)
    return out


def _capture(run, policy, obs, episode_id):
    """One k = 8 batch: the StoredTraceSet the loop would store at entry."""
    from flytrade import readout as _RO
    stim = run.encoder.encode(obs)
    batch = policy.measure(run, stim, episode_id=episode_id,
                           state_dig=run.state_digest(),
                           obs_id=_RO.observation_id(obs))
    return batch.traces


def _idle(run, policy, obs_pool, n, first_round):
    """``n`` full decision rounds that are not this episode's."""
    for i in range(n):
        obs = obs_pool[i % len(obs_pool)]
        run.evaluate_round([obs], round_index=first_round + i,
                           readout=policy, score=policy.score)


@requires_real_graph
def test_a_stored_trace_settles_identically_after_90_idle_rounds(
        runner, series_a):
    """The STOP condition of addendum 3, as a number, not as an argument."""
    run = runner
    mb = run.mb
    policy = RO.policy_k8()
    pool = _usable(series_a)
    assert len(pool) >= 10, "the fixture must offer real presentations"

    g0 = mb.gain.copy()
    entry_obs = pool[0]
    episode = 4242

    # the same capture in both arms: same clean weights, same observation,
    # same seed schedule, so the two stored trace sets are bit-identical
    ts_a = _capture(run, policy, entry_obs, episode)
    assert isinstance(ts_a, R.StoredTraceSet) and ts_a.k == RO.K == 8
    assert ts_a.max_trace > M.TRACE_EPS

    mb.gain[:] = g0
    mb.trace[:] = 0.0
    mb.trace_episode[:] = -1
    mb.apply()
    ts_b = _capture(run, policy, entry_obs, episode)
    assert ts_b.k == ts_a.k
    for a, b in zip(ts_a.traces, ts_b.traces):
        assert np.array_equal(a.index, b.index)
        assert np.array_equal(a.value, b.value)

    # ---- arm A: settle after ONE intervening round --------------------
    mb.gain[:] = g0
    mb.trace[:] = 0.0
    mb.trace_episode[:] = -1
    mb.apply()
    credit_a = R.CreditAssigner(mb)
    credit_a.open_episode(ts_a)
    _idle(run, policy, pool[1:], 1, first_round=10_000)
    ev_a = credit_a.settle(episode, -1, 0.5)
    gain_a = mb.gain.copy()

    # ---- arm B: settle after NINETY intervening rounds ----------------
    mb.gain[:] = g0
    mb.trace[:] = 0.0
    mb.trace_episode[:] = -1
    mb.apply()
    credit_b = R.CreditAssigner(mb)
    credit_b.open_episode(ts_b)
    held = [(t.index.copy(), t.value.copy()) for t in ts_b.traces]
    _idle(run, policy, pool[1:], H, first_round=20_000)
    # why it holds: the stored set is a copy that lives outside the live
    # eligibility layer, and 90 rounds of writing that layer never reach it
    for (i0, v0), t in zip(held, ts_b.traces):
        assert np.array_equal(i0, t.index)
        assert np.array_equal(v0, t.value)
    assert mb.episode != episode          # the live layer did move on
    ev_b = credit_b.settle(episode, -1, 0.5)
    gain_b = mb.gain.copy()

    # ---- the assertion the wave is gated on ---------------------------
    assert ev_a.accepted is True, ev_a.reason
    assert ev_b.accepted is True, ev_b.reason
    assert ev_b.synapses_depressed == ev_a.synapses_depressed > 0
    assert ev_b.trace_eligible == ev_a.trace_eligible > 0
    assert ev_b.trace_max == ev_a.trace_max
    assert ev_b.depressed_per_replicate == ev_a.depressed_per_replicate
    assert ev_b.as_dict() == ev_a.as_dict()
    assert np.array_equal(gain_b, gain_a)
    assert not np.array_equal(gain_a, g0)          # something did move
    assert credit_b.rejections["TRACE_EXPIRED"] == 0
    assert ev_b.eligibility_source == "replayed_from_decision"


def test_the_settlement_gate_reads_only_the_stored_set():
    """No wall clock, no round counter, no decay term is in the gate.

    :meth:`flytrade.runner.CreditAssigner.settle` admits or refuses on
    ``ts.max_trace``, ``ts.n_synapses`` and the settled/open bookkeeping —
    values fixed when the trace was captured. Nothing in it is a function of
    how much time or how many rounds have passed, which is why 90 rounds and
    1 round cannot differ.
    """
    import inspect
    src = inspect.getsource(R.CreditAssigner.settle)
    for forbidden in ("time.", "decay", "forget", "round_index", "now("):
        assert forbidden not in src, forbidden
    assert "ts.max_trace <= M.TRACE_EPS" in src
