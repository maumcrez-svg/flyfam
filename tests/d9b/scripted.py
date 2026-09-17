"""
A scripted decision loop: the real loop, the real money, a scripted decoder.

``experiments/historical/run.py::run_branch`` is the code the D9(b) flag lives
in, and the properties this wave must prove — a blocked SELL does not close, a
horizon close lands on the anchor, one episode makes one learning update, a
restart duplicates nothing — are properties of **that** function, not of a
re-implementation of it. So these tests call it.

What is real here: the loop itself, :class:`flytrade.historical.HistoricalExecution`
with its fills, costs, delay and session rules, :class:`flytrade.records.Journal`
with its event log, checkpoints and pending file, :class:`flytrade.runner.CreditAssigner`
with its stored-trace replay, and a real :class:`flytrade.mushroom.MushroomBody`
over the built connectome, so a learning update really moves real gains.

What is scripted: the **simulator**. ``ScriptedRunner.evaluate_round`` returns a
round whose decoded action is read from a table instead of from 8 × 20 ms of
spiking. That is the point: a test that needs "a SELL at minute 40 while a
position is open" cannot wait for the decoder to feel like emitting one, and
nothing about the fixed-hold routing depends on where the SELL came from. The
eligibility traces it hands back are real ``StoredTrace`` objects over the real
plastic-synapse vector, so settlement, depression and the checkpoint digest are
the genuine arithmetic.

Nothing in this module is imported by anything under ``flytrade/`` or
``experiments/``.
"""
from __future__ import annotations

import sys
from datetime import date as _date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(ROOT / "upstream"), str(ROOT / "experiments" / "historical")):
    if p not in sys.path:
        sys.path.insert(0, p)

from flytrade import decoder as D            # noqa: E402
from flytrade import readout as RO           # noqa: E402
from flytrade import runner as R             # noqa: E402

#: how many plastic synapses each scripted eligibility trace covers
TRACE_WIDTH = 64
#: the eligibility value it carries, comfortably above ``TRACE_EPS``
TRACE_VALUE = 0.75


def config(symbol: str, *, horizon: int, days, learning_days=None,
           frozen_days=None, notional: float = 1000.0) -> dict:
    """A committed-config-shaped dict for one fixture instrument."""
    learning_days = tuple(learning_days if learning_days is not None else days)
    frozen_days = tuple(frozen_days if frozen_days is not None else ())
    w_first = min(days)
    return {
        "instruments": [{"symbol": symbol, "stable_id": 0}],
        "partitions": {
            "WARMUP": {"first": str(w_first), "last": str(w_first),
                       "learning": False, "neural": False},
            "LEARNING": {"first": str(min(learning_days)),
                         "last": str(max(learning_days)),
                         "learning": True, "neural": True},
            "FROZEN": {"first": str(min(frozen_days)) if frozen_days else "2099-01-01",
                       "last": str(max(frozen_days)) if frozen_days else "2099-01-01",
                       "learning": False, "neural": True},
        },
        "execution": {
            "notional": notional, "initial_cash": 10000.0,
            "fee_bps": 5.0, "slippage_bps": 5.0, "delay_minutes": 1,
            "horizon_minutes": int(horizon),
            "reinforce_full_scale": 0.01, "reinforce_cap": 1.0,
        },
    }


class ScriptedDecoder:
    """The decoder stand-in: one table lookup, no spikes."""

    VERSION = "scripted-decoder-1"

    def __init__(self, script, theta_hz: float = 1.0):
        self.script = dict(script)
        self.theta_hz = float(theta_hz)
        self.seen: list[tuple] = []

    def decode(self, presentation) -> D.Decision:
        key = presentation.symbol, presentation.episode_id
        name = self.script.get(presentation.seed, "WAIT")
        action = D.Action[name] if name != "NO_RESPONSE" else D.Action.WAIT
        status = (D.ReadoutStatus.NO_RESPONSE if name == "NO_RESPONSE"
                  else D.ReadoutStatus.VALID)
        v = {"BUY": 2.0, "SELL": -2.0}.get(name, 0.0)
        self.seen.append((key, name))
        return D.Decision(
            action=action, status=status, valence_hz=v, raw_valence_hz=v,
            approach_hz=max(v, 0.0), avoid_hz=max(-v, 0.0),
            kc_fraction=0.05, max_rate_hz=30.0, theta_hz=self.theta_hz,
            decoder_version=self.VERSION, reason="")


class ScriptedPolicy:
    """A :class:`flytrade.readout.ReadoutPolicy` stand-in at k = 8."""

    version = "scripted-policy-1"

    def __init__(self, script, namespace="scripted", k: int = RO.K):
        self.k = int(k)
        self.namespace = str(namespace)
        self.decoder = ScriptedDecoder(script)
        self.decoder_k1 = self.decoder

    def score(self, evaluation):
        p = evaluation.presentation
        return None if p is None else self.decoder.decode(p).valence_hz

    def as_dict(self) -> dict:
        return {"namespace": self.namespace, "k": self.k,
                "version": self.version,
                "decoder": {"version": self.decoder.VERSION}}


class ScriptedRunner:
    """A :class:`flytrade.runner.BrainRunner` stand-in over a real brain."""

    def __init__(self, mb, *, graph_sha256: str = "0" * 64):
        self.fb = None
        self.mb = mb
        self.graph_sha256 = graph_sha256
        self.rounds = 0

    def _traces(self, episode_id: int, k: int) -> R.StoredTraceSet:
        """k real stored traces over the real plastic-synapse vector."""
        n = len(self.mb.trace)
        base = (episode_id * 7) % max(1, n - TRACE_WIDTH)
        out = []
        for r in range(k):
            idx = np.arange(base + r, base + r + TRACE_WIDTH, dtype=np.int64)
            idx = idx[idx < n]
            out.append(R.StoredTrace(
                episode_id=int(episode_id), index=idx,
                value=np.full(len(idx), TRACE_VALUE, dtype=np.float32),
                n_synapses=n))
        return R.StoredTraceSet.of(int(episode_id), out)

    def evaluate_round(self, observations, *, round_index, score,
                       readout=None, round_seed: int = 0,
                       selection_rule="scripted"):
        self.rounds += 1
        k = readout.k if readout is not None else 1
        evals = []
        for obs in observations:
            ep = R.episode_id_for(round_index, obs.stable_id)
            if not obs.status.usable:
                evals.append(R.CandidateEvaluation(
                    symbol=obs.symbol, stable_id=obs.stable_id, episode_id=ep,
                    seed=0, observation=obs, stimulus=None, presentation=None,
                    trace=None,
                    rejected=f"observation {obs.status.value}"))
                continue
            ts = self._traces(ep, k)
            # the scripted decoder keys off the seed, and the seed is the
            # round's own market minute: that is how a test says "SELL at 40"
            pres = R.Presentation(
                symbol=obs.symbol, stable_id=obs.stable_id, episode_id=ep,
                seed=int(obs.bar_index), steps=100,
                rates={"approach": np.zeros(1), "avoid": np.zeros(1)},
                kc_fraction=0.05, kc_active=20, total_hz=30.0,
                max_rate_hz=30.0, n_eligible=ts.traces[0].n_eligible, k=k,
                seeds=tuple(range(k)))
            evals.append(R.CandidateEvaluation(
                symbol=obs.symbol, stable_id=obs.stable_id, episode_id=ep,
                seed=int(obs.bar_index), observation=obs, stimulus=None,
                presentation=pres, trace=ts.traces[0], traces=ts))

        scores = {}
        for c in evals:
            if c.usable:
                v = score(c)
                if v is not None:
                    scores[c.stable_id] = float(v)
        selected = None
        if scores:
            best = max(scores.values())
            wid = min(k2 for k2, v in scores.items() if v == best)
            selected = next(c for c in evals if c.stable_id == wid)
        return R.RoundEvaluation(
            round_index=round_index, round_seed=round_seed,
            cutoff_ts=max((c.observation.cutoff_ts for c in evals), default=0),
            candidates=tuple(evals), selected=selected,
            selection_rule=selection_rule, scores=scores,
            readout=readout.as_dict() if readout is not None else None,
            state_digest="")


def run_scripted(*, mb, series, symbol, script, store, horizon, days,
                 exit_policy=None, learning=True, name="learned",
                 run_id="d9b-test", graph_sha256="0" * 64, start_gain=None,
                 restart_after=None, log=lambda *a, **k: None):
    """Call the real ``run_branch`` with a scripted simulator.

    ``exit_policy=None`` omits the argument entirely, which is how a test
    reaches the loop's behaviour as it stood before the flag existed.
    """
    import run as HR
    from flytrade import historical as H

    cfg = config(symbol, horizon=horizon, days=days)
    parts = H.partitions_from(cfg["partitions"])
    policy = ScriptedPolicy(script)
    run = ScriptedRunner(mb, graph_sha256=graph_sha256)
    gain = (np.ones(len(mb.pos), dtype=np.float32) if start_gain is None
            else start_gain)
    kw = {} if exit_policy is None else {"exit_policy": exit_policy}
    out, journal, accounts, credit = HR.run_branch(
        name=name, cfg=cfg, series={symbol: series}, parts=parts,
        partitions=["LEARNING"], run=run, mb=mb, enc=None, pops=None,
        sha=graph_sha256, policy_for=lambda part: policy, run_id=run_id,
        learn_in={"LEARNING"} if learning else set(), start_gain=gain,
        round_base=0, restart_after=restart_after, log=log,
        runs_dir=Path(store), horizon_minutes=horizon, **kw)
    return out, journal, accounts, credit, policy
