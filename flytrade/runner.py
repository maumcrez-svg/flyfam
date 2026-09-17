"""
BrainRunner and fair sequential evaluation.

Canonical amendment §2 and Fable addendum 5. One persistent learned brain
evaluates every candidate in a round; there is no brain per instrument and no
learned weight is touched between candidates.

## What a round does

1. Freeze one observation cutoff and one learned-state version for the round.
2. Take **one** transient snapshot ``S0`` — the eligibility layer as it stands
   after the previous episode settled. The electrical layer is not in the
   snapshot because there is none to take: ``flysim.FlyBrain.run`` reinitialises
   every membrane potential at the top of every call (`flytrade/state.py`), so
   every presentation already starts from rest. That is recorded here rather
   than assumed.
3. For each candidate, in whatever order the caller supplies: restore ``S0``,
   encode, present, read out, capture the eligibility trace the presentation
   laid down, and restore ``S0`` again before the next one.
4. Select. Ties resolve by **lowest stable id**, never by a market quantity.
5. The selected candidate's post-presentation eligibility becomes the ongoing
   state; every other candidate's is discarded.

## Why the results cannot depend on order, spelling or position

The only randomness in a presentation is the Poisson drive inside
``FlyBrain.run``, and its seed is

    seed = sha256("<round_seed>:<stable_id>") truncated to 31 bits

— a function of the round and of the candidate's **stable id**, which is
assigned once at universe registration and is independent of the symbol string
and of any list position. The episode id is likewise
``round_index * EPISODE_STRIDE + stable_id``, so it too is invariant. Restoring
``S0`` before each candidate removes the other route by which order could
matter: a trace laid down by the previous candidate.

## D4 — the readout policy hook

``evaluate_round(..., readout=policy)`` replaces step 3's single presentation
with a batch of k, drawn from the schedule ``flytrade/readout.py`` declares, and
``CandidateEvaluation.presentation`` becomes the batch's **aggregate**. Steps
1, 2, 4 and 5 are unchanged, and so is the whole path when ``readout is None``:
that is the Phase One single-presentation mode, kept, with its own
``round_seed``-derived schedule.

An episode's eligibility is a :class:`StoredTraceSet` in both modes — one trace
at k = 1, k traces at k = 8 — so settlement has one code path and one rule.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from . import encoder as E
from . import market as MK
from . import mushroom as M

VERSION = "flytrade-runner-1"

#: episode ids are ``round_index * EPISODE_STRIDE + stable_id``; a universe
#: larger than this would collide, so it is checked rather than assumed.
EPISODE_STRIDE = 1_000_000


def candidate_seed(round_seed: int, stable_id: int) -> int:
    """Deterministic per-candidate RNG seed (Fable addendum 5)."""
    h = hashlib.sha256(f"{int(round_seed)}:{int(stable_id)}".encode()).digest()
    return int.from_bytes(h[:4], "big") & 0x7FFF_FFFF


def episode_id_for(round_index: int, stable_id: int) -> int:
    if not 0 <= stable_id < EPISODE_STRIDE:
        raise ValueError(f"stable id {stable_id} outside [0, {EPISODE_STRIDE})")
    return int(round_index) * EPISODE_STRIDE + int(stable_id)


# ------------------------------------------------------------- snapshots

@dataclass(frozen=True)
class TransientSnapshot:
    """The eligibility layer at one instant. The electrical layer is empty.

    Amendment §2 asks that candidate evaluations begin from equivalent
    transient-state snapshots. This is that snapshot; ``electrical_state`` is
    carried as an explicit ``None`` so nobody later assumes one was dropped.
    """

    trace: np.ndarray
    trace_episode: np.ndarray
    episode: int
    electrical_state: None = None


@dataclass(frozen=True)
class StoredTrace:
    """One evaluation's eligibility trace, kept outside the live layer.

    Sparse: only synapses above :data:`flytrade.mushroom.TRACE_EPS` are kept,
    because only those can ever be depressed. ``episode_id`` is what makes a
    later reinforcement addressable to *this* experience and no other.
    """

    episode_id: int
    index: np.ndarray          # positions into MushroomBody.trace
    value: np.ndarray          # trace strength at capture time
    n_synapses: int            # length of the full trace vector, for validation

    @property
    def n_eligible(self) -> int:
        return int(len(self.index))

    @property
    def max_trace(self) -> float:
        return float(self.value.max()) if len(self.value) else 0.0

    def as_dict(self) -> dict:
        return {"episode_id": self.episode_id, "n_eligible": self.n_eligible,
                "max_trace": round(self.max_trace, 6),
                "n_synapses": self.n_synapses}


@dataclass(frozen=True)
class StoredTraceSet:
    """The k eligibility traces of one episode's batch (D4 §4, addendum 6).

    One decision is one episode, whatever k is. A k = 1 episode holds a set of
    one, so there is a single settlement path and k = 1 is not a special case
    with its own arithmetic.

    Replicates are held **sorted by replicate index**, which is what makes
    "replicate permutation does not change the update" exact rather than
    exact-to-rounding: the average is always summed in the same order.
    """

    episode_id: int
    traces: tuple[StoredTrace, ...]

    @classmethod
    def of(cls, episode_id: int, traces) -> "StoredTraceSet":
        ts = tuple(traces)
        if not ts:
            raise ValueError("a stored trace set needs at least one trace")
        for t in ts:
            if t.episode_id != int(episode_id):
                raise ValueError(
                    f"trace of episode {t.episode_id} offered to the set of "
                    f"episode {episode_id}")
        return cls(episode_id=int(episode_id), traces=ts)

    @property
    def k(self) -> int:
        return len(self.traces)

    @property
    def n_synapses(self) -> int:
        return self.traces[0].n_synapses

    @property
    def max_trace(self) -> float:
        return max(t.max_trace for t in self.traces)

    @property
    def n_eligible(self) -> int:
        """Union over the replicates: how many synapses any replicate made
        eligible. The per-replicate counts are in ``per_replicate``."""
        return int(len(np.unique(np.concatenate(
            [t.index for t in self.traces])))) if self.traces else 0

    @property
    def per_replicate(self) -> tuple[int, ...]:
        return tuple(t.n_eligible for t in self.traces)

    def as_dict(self) -> dict:
        return {"episode_id": self.episode_id, "k": self.k,
                "n_eligible_union": self.n_eligible,
                "n_eligible_per_replicate": list(self.per_replicate),
                "max_trace": round(self.max_trace, 6),
                "n_synapses": self.n_synapses}


# ------------------------------------------------------------ readouts

@dataclass(frozen=True)
class Presentation:
    """What one 20 ms presentation produced. Pure measurement, no decoding."""

    symbol: str
    stable_id: int
    episode_id: int
    seed: int
    steps: int
    rates: dict[str, np.ndarray] = field(repr=False)
    kc_fraction: float = 0.0
    kc_active: int = 0
    total_hz: float = 0.0
    max_rate_hz: float = 0.0
    n_eligible: int = 0
    #: D4: how many presentations this readout aggregates. 1 for a single
    #: presentation, k for the aggregate of a batch. The fields below are
    #: meaningful only for an aggregate and are reported so that a record can
    #: never be mistaken for a single reading.
    k: int = 1
    seeds: tuple = ()
    kc_fraction_mean: float = 0.0
    silent_replicates: int = 0
    invalid_replicates: int = 0

    def mean(self, name: str) -> float:
        v = self.rates[name]
        return float(v.mean()) if len(v) else 0.0

    def as_dict(self) -> dict:
        d = {
            "symbol": self.symbol, "stable_id": self.stable_id,
            "episode_id": self.episode_id, "seed": self.seed,
            "steps": self.steps,
            "rates_hz": {k: round(self.mean(k), 6) for k in self.rates},
            "population_sizes": {k: int(len(v)) for k, v in self.rates.items()},
            "kc_fraction": round(self.kc_fraction, 6),
            "kc_active": self.kc_active,
            "max_rate_hz": round(self.max_rate_hz, 6),
            "n_eligible": self.n_eligible,
            "k": int(self.k),
        }
        if self.k != 1:
            d.update({"seeds": [int(x) for x in self.seeds],
                      "kc_fraction_mean": round(self.kc_fraction_mean, 6),
                      "silent_replicates": int(self.silent_replicates),
                      "invalid_replicates": int(self.invalid_replicates)})
        return d


@dataclass(frozen=True)
class CandidateEvaluation:
    """One candidate, evaluated under the round's frozen learned state."""

    symbol: str
    stable_id: int
    episode_id: int
    seed: int
    observation: MK.MarketObservation
    stimulus: E.Stimulus | None
    presentation: Presentation | None
    trace: StoredTrace | None
    rejected: str = ""          # non-empty when the observation was unusable
    #: D4: the k presentations behind ``presentation`` when a readout policy
    #: was used. ``presentation`` is then their **aggregate** and ``trace`` is
    #: replicate 0's, kept so that k = 1 and k = 8 hand the live eligibility
    #: layer the same thing; learning uses ``traces``, all k of them.
    batch: object | None = None
    traces: StoredTraceSet | None = None

    @property
    def usable(self) -> bool:
        return not self.rejected

    @property
    def k(self) -> int:
        return self.traces.k if self.traces is not None else 1

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol, "stable_id": self.stable_id,
            "episode_id": self.episode_id, "seed": self.seed,
            "observation": self.observation.as_dict(),
            "stimulus": self.stimulus.as_dict() if self.stimulus else None,
            "presentation": (self.presentation.as_dict()
                             if self.presentation else None),
            "trace": self.trace.as_dict() if self.trace else None,
            "traces": self.traces.as_dict() if self.traces else None,
            "batch": self.batch.as_dict() if self.batch is not None else None,
            "rejected": self.rejected,
        }


@dataclass
class RoundEvaluation:
    """Every candidate of one round, plus which one was selected and why."""

    round_index: int
    round_seed: int
    cutoff_ts: int
    candidates: tuple[CandidateEvaluation, ...]
    selected: CandidateEvaluation | None
    selection_rule: str
    scores: dict[int, float] = field(default_factory=dict)
    readout: dict | None = None
    state_digest: str = ""

    def by_symbol(self, symbol: str) -> CandidateEvaluation:
        for c in self.candidates:
            if c.symbol == symbol:
                return c
        raise KeyError(symbol)

    def as_dict(self) -> dict:
        return {
            "round_index": self.round_index, "round_seed": self.round_seed,
            "cutoff_ts": self.cutoff_ts,
            "candidates": [c.as_dict() for c in self.candidates],
            "selected_stable_id": (self.selected.stable_id
                                   if self.selected else None),
            "selection_rule": self.selection_rule,
            "scores": {str(k): round(float(v), 6) for k, v in self.scores.items()},
            "readout": self.readout,
            "state_digest": self.state_digest,
        }


# --------------------------------------------------------------- runner

class BrainRunner:
    """Presents stimuli to one persistent brain and reads named populations.

    ``populations`` maps a name to a neuron-index array; every presentation
    reports the per-neuron firing rate of each. The runner does no decoding:
    it never decides anything, and nothing here knows what a market is.
    """

    version = VERSION

    def __init__(self, fb, mb: M.MushroomBody, encoder: E.MarketToSensoryEncoder,
                 populations: dict[str, np.ndarray], *,
                 gains: np.ndarray | None = None, steps: int = E.STEPS,
                 graph_sha256: str = ""):
        self.fb = fb
        self.mb = mb
        self.encoder = encoder
        self.steps = int(steps)
        self.graph_sha256 = str(graph_sha256)
        self.populations = {k: np.asarray(v, dtype=np.int64)
                            for k, v in populations.items()}
        self.gains = (np.full(fb.n_types, E.GLOBAL_GAIN, dtype=np.float32)
                      if gains is None else np.asarray(gains, dtype=np.float32))
        self.presentations = 0

    # -- transient state --------------------------------------------------

    def state_digest(self) -> str:
        """The learned-state version every replicate seed is derived from.

        D4 amendment §1 ("All candidates use the same learned-state version")
        and Fable addendum 2. It is the same digest the checkpoint carries, so
        a record naming a state digest names a checkpoint.
        """
        from . import state as S
        return S.learned_state_digest(self.mb.gain, self.mb.pos,
                                      self.graph_sha256)

    def snapshot(self) -> TransientSnapshot:
        return TransientSnapshot(trace=self.mb.trace.copy(),
                                 trace_episode=self.mb.trace_episode.copy(),
                                 episode=int(self.mb.episode))

    def restore(self, snap: TransientSnapshot) -> None:
        self.mb.trace[:] = snap.trace
        self.mb.trace_episode[:] = snap.trace_episode
        self.mb.episode = snap.episode
        self.mb.reset_electrical()

    def clear_episode(self, episode_id: int) -> int:
        """Drop any live eligibility already carrying this episode id.

        The declared inputs of a batch are (learned state, observation, seed
        schedule). A trace left in the live layer under the *same* episode id —
        which a repeated round index can produce — is not among them, so it is
        cleared before a replicate rather than captured alongside what this
        presentation actually made eligible. Returns how many entries it found;
        in a forward-running loop that is always zero.
        """
        sel = self.mb.trace_episode == int(episode_id)
        n = int(sel.sum())
        if n:
            self.mb.trace[sel] = 0.0
            self.mb.trace_episode[sel] = -1
        return n

    def capture_trace(self, episode_id: int) -> StoredTrace:
        """Lift the current eligibility out of the live layer, sparsely."""
        idx = np.flatnonzero((self.mb.trace > M.TRACE_EPS)
                             & (self.mb.trace_episode == episode_id))
        return StoredTrace(episode_id=int(episode_id),
                           index=idx.astype(np.int64),
                           value=self.mb.trace[idx].copy(),
                           n_synapses=int(len(self.mb.trace)))

    # -- one presentation -------------------------------------------------

    def present(self, stimulus: E.Stimulus, *, seed: int, episode_id: int,
                observe: bool = True) -> Presentation:
        """Run one 20 ms window and read out. Never learns, never decides."""
        rec = dict(self.populations)
        rec["_kc"] = self.mb.kc
        r = self.fb.run(stimulus.drive, steps=self.steps, gains=self.gains,
                        record=rec, seed=int(seed))
        self.presentations += 1
        kc = r.pop("_kc")
        rates = {k: r[k] for k in self.populations}
        n_elig = 0
        if observe:
            self.mb.begin_episode(int(episode_id))
            n_elig = self.mb.observe(r["_fired"])
        return Presentation(
            symbol=stimulus.symbol, stable_id=stimulus.stable_id,
            episode_id=int(episode_id), seed=int(seed), steps=self.steps,
            rates=rates,
            kc_fraction=float((kc > 0).mean()) if len(kc) else 0.0,
            kc_active=int((kc > 0).sum()),
            total_hz=float(r["_total_hz"]),
            max_rate_hz=max((float(v.max()) for v in rates.values()
                             if len(v)), default=0.0),
            n_eligible=n_elig)

    # -- one round --------------------------------------------------------

    def evaluate_round(self, observations, *, round_index: int,
                       round_seed: int = 0, score,
                       readout=None,
                       selection_rule: str = "max score, ties to the "
                                             "lowest stable id"
                       ) -> RoundEvaluation:
        """Evaluate every candidate under one frozen learned state.

        ``observations`` is any iterable of :class:`MarketObservation`; their
        order is the caller's and must not change the outcome. ``score`` maps a
        :class:`CandidateEvaluation` to a float, or to ``None`` for a candidate
        that is not selectable at all.

        ``readout`` is a :class:`flytrade.readout.ReadoutPolicy`. With one, each
        candidate is presented k times from equivalent transient snapshots and
        ``presentation`` is the **aggregate** the fixed decoder is applied to
        once; the k replicates and their k eligibility traces are kept on the
        evaluation. Without one, this is the single-presentation Phase One path
        and its ``round_seed``-derived schedule, preserved unchanged.

        A replicate that raises propagates as
        :class:`flytrade.readout.TechnicalFailure`: the round aborts, and the
        caller records ``ROUND_ABORTED``. Nothing is averaged over a partial
        batch and nothing is retried.
        """
        s0 = self.snapshot()
        dig = self.state_digest() if readout is not None else ""
        evals: list[CandidateEvaluation] = []
        for obs in observations:
            ep = episode_id_for(round_index, obs.stable_id)
            self.restore(s0)
            if readout is None:
                seed = candidate_seed(round_seed, obs.stable_id)
            else:
                from . import readout as RO
                seed = readout.seeds(dig, RO.observation_id(obs),
                                     obs.stable_id)[0]
            if not obs.status.usable:
                evals.append(CandidateEvaluation(
                    symbol=obs.symbol, stable_id=obs.stable_id, episode_id=ep,
                    seed=seed, observation=obs, stimulus=None,
                    presentation=None, trace=None,
                    rejected=f"observation {obs.status.value}"))
                continue
            stim = self.encoder.encode(obs)
            if readout is None:
                pres = self.present(stim, seed=seed, episode_id=ep)
                tr = self.capture_trace(ep)
                evals.append(CandidateEvaluation(
                    symbol=obs.symbol, stable_id=obs.stable_id, episode_id=ep,
                    seed=seed, observation=obs, stimulus=stim,
                    presentation=pres, trace=tr,
                    traces=StoredTraceSet.of(ep, [tr])))
                continue
            from . import readout as RO
            batch = readout.measure(self, stim, episode_id=ep,
                                    state_dig=dig,
                                    obs_id=RO.observation_id(obs),
                                    snapshot=s0)
            evals.append(CandidateEvaluation(
                symbol=obs.symbol, stable_id=obs.stable_id, episode_id=ep,
                seed=seed, observation=obs, stimulus=stim,
                presentation=batch.aggregate, trace=batch.traces.traces[0],
                batch=batch, traces=batch.traces))
        self.restore(s0)

        scores: dict[int, float] = {}
        for c in evals:
            if not c.usable:
                continue
            v = score(c)
            if v is not None:
                scores[c.stable_id] = float(v)

        selected = None
        if scores:
            best = max(scores.values())
            winner_id = min(k for k, v in scores.items() if v == best)
            selected = next(c for c in evals if c.stable_id == winner_id)
            # the selected candidate's post-presentation eligibility becomes
            # the ongoing state; every other candidate's is discarded
            self.mb.trace[:] = 0.0
            self.mb.trace_episode[:] = -1
            self.mb.trace[selected.trace.index] = selected.trace.value
            self.mb.trace_episode[selected.trace.index] = selected.episode_id
            self.mb.episode = selected.episode_id

        return RoundEvaluation(
            round_index=round_index, round_seed=round_seed,
            cutoff_ts=max((o.cutoff_ts for o in
                           (c.observation for c in evals)), default=0),
            candidates=tuple(evals), selected=selected,
            selection_rule=selection_rule, scores=scores,
            readout=readout.as_dict() if readout is not None else None,
            state_digest=dig)


# ----------------------------------------------------- credit assignment

class RejectionReason(str, Enum):
    """Why a reinforcement was refused. Counted separately, never pooled.

    Amendment §5: "Separate rejection counters by reason. Do not use a large
    rejection count as evidence of correctness." A single total would make
    "the gate works" and "the gate rejects everything" indistinguishable.
    """

    #: the trace offered belongs to a different episode — another candidate of
    #: the same round, or another instrument entirely
    EPISODE_MISMATCH = "EPISODE_MISMATCH"
    #: this episode was already settled and its trace discarded
    ALREADY_SETTLED = "ALREADY_SETTLED"
    #: no trace is held for this episode
    UNKNOWN_EPISODE = "UNKNOWN_EPISODE"
    #: the trace decayed below the eligibility threshold before settlement
    TRACE_EXPIRED = "TRACE_EXPIRED"
    #: the trace was captured against a different set of plastic synapses
    SHAPE_MISMATCH = "SHAPE_MISMATCH"


@dataclass(frozen=True)
class LearningEvent:
    """One reinforcement, accepted or refused, with the numbers behind it."""

    episode_id: int
    valence: int
    amount: float
    accepted: bool
    synapses_depressed: int = 0
    reason: str = ""
    trace_eligible: int = 0
    trace_max: float = 0.0
    #: Fable addendum 6: reinforcement is applied to the trace stored at
    #: decision time, not to whatever the live eligibility layer holds now.
    eligibility_source: str = "replayed_from_decision"
    #: D4 §4: how many eligibility traces this one outcome was applied to, and
    #: how. ``mean_of_deltas`` is the canonical rule: each replicate's proposed
    #: delta computed from the SAME pre-update state, averaged, applied once.
    k: int = 1
    normalisation: str = "single_trace"
    depressed_per_replicate: tuple = ()

    def as_dict(self) -> dict:
        return {
            "episode_id": self.episode_id, "valence": self.valence,
            "amount": round(self.amount, 6), "accepted": self.accepted,
            "synapses_depressed": self.synapses_depressed,
            "reason": self.reason, "trace_eligible": self.trace_eligible,
            "trace_max": round(self.trace_max, 6),
            "eligibility_source": self.eligibility_source,
            "k": int(self.k), "normalisation": self.normalisation,
            "depressed_per_replicate": [int(x) for x
                                        in self.depressed_per_replicate],
        }


class CreditAssigner:
    """Episode-scoped reinforcement by stored-trace replay (addendum 6).

    The decision stores its eligibility trace when it is taken. The outcome
    arrives market-time later — hours of it, against an eligibility constant of
    836 ms — so the live eligibility layer is long gone by then and would be
    the wrong thing to reinforce anyway. Reinforcement is applied to the
    *stored* trace, which is then discarded and the episode closed.

    That is a **modelling convention**, stated as one. The biological time
    constants in ``flytrade/state.py`` are not stretched to cover a market
    horizon; they still govern what happens inside a simulation cycle, and the
    learning event records ``eligibility_source = "replayed_from_decision"`` so
    nobody reading the log can mistake the two.

    This class lives beside :class:`BrainRunner` because it is the other half
    of the same object: the runner decides which experience is the episode's,
    and this decides whether a later outcome is allowed to reach it.
    """

    version = VERSION

    def __init__(self, mb: M.MushroomBody):
        self.mb = mb
        self.open: dict[int, StoredTraceSet] = {}
        self.settled: set[int] = set()
        self.accepted = 0
        self.rejections: dict[str, int] = {r.value: 0 for r in RejectionReason}
        self.events: list[LearningEvent] = []

    # -- bookkeeping ------------------------------------------------------

    @staticmethod
    def as_set(trace) -> StoredTraceSet:
        """A :class:`StoredTraceSet` from either a set or a lone trace."""
        if isinstance(trace, StoredTraceSet):
            return trace
        return StoredTraceSet.of(trace.episode_id, [trace])

    def open_episode(self, trace) -> StoredTraceSet:
        """Register the selected candidate's eligibility as the open episode.

        ``trace`` is a :class:`StoredTraceSet` — the k traces of the selected
        candidate's batch — or a single :class:`StoredTrace`, which is wrapped
        into a set of one. One decision is one episode whatever k is.
        """
        ts = self.as_set(trace)
        if ts.episode_id in self.settled:
            raise ValueError(f"episode {ts.episode_id} is already settled")
        if ts.episode_id in self.open:
            raise ValueError(f"episode {ts.episode_id} is already open")
        self.open[ts.episode_id] = ts
        return ts

    def _reject(self, episode_id, valence, amount, reason: RejectionReason,
                trace: StoredTrace | None) -> LearningEvent:
        self.rejections[reason.value] += 1
        ev = LearningEvent(
            episode_id=int(episode_id), valence=int(valence),
            amount=float(amount), accepted=False, reason=reason.value,
            trace_eligible=trace.n_eligible if trace else 0,
            trace_max=trace.max_trace if trace else 0.0,
            k=trace.k if isinstance(trace, StoredTraceSet) else 1)
        self.events.append(ev)
        return ev

    # -- the gate ---------------------------------------------------------

    def settle(self, episode_id: int, valence: int, amount: float = 1.0, *,
               trace=None) -> LearningEvent:
        """Apply one outcome's reinforcement to one episode's stored eligibility.

        ``trace`` defaults to what is registered for ``episode_id`` — a
        :class:`StoredTraceSet` of k traces, or a single :class:`StoredTrace`,
        which is wrapped into a set of one. Passing one explicitly is how a
        caller — or a test — offers the *wrong* eligibility, and it is refused
        with a reason rather than silently applied.

        **One outcome, one update.** At k > 1 the k proposed deltas are each
        computed from the *same* pre-update learned state, averaged, and
        applied once, atomically (D4 §4, Fable addendum 6). There are never k
        sequential full-strength rewards, and the largest-update replicate is
        never selected. At k = 1 the arithmetic is Phase One's, unchanged.
        """
        episode_id = int(episode_id)
        if episode_id in self.settled:
            return self._reject(episode_id, valence, amount,
                                RejectionReason.ALREADY_SETTLED,
                                trace or self.open.get(episode_id))
        if trace is None:
            trace = self.open.get(episode_id)
        if trace is None:
            return self._reject(episode_id, valence, amount,
                                RejectionReason.UNKNOWN_EPISODE, None)
        ts = self.as_set(trace)
        if ts.episode_id != episode_id:
            return self._reject(episode_id, valence, amount,
                                RejectionReason.EPISODE_MISMATCH, ts)
        if ts.n_synapses != len(self.mb.trace):
            return self._reject(episode_id, valence, amount,
                                RejectionReason.SHAPE_MISMATCH, ts)
        if ts.max_trace <= M.TRACE_EPS:
            return self._reject(episode_id, valence, amount,
                                RejectionReason.TRACE_EXPIRED, ts)

        if ts.k == 1:
            n, per = self._apply_single(ts.traces[0], episode_id, valence,
                                        amount), ()
            norm = "single_trace"
        else:
            n, per = self._apply_normalised(ts, valence, amount)
            norm = "mean_of_deltas"

        self.open.pop(episode_id, None)
        self.settled.add(episode_id)
        self.accepted += 1
        ev = LearningEvent(
            episode_id=episode_id, valence=int(valence), amount=float(amount),
            accepted=True, synapses_depressed=int(n),
            trace_eligible=ts.n_eligible, trace_max=ts.max_trace,
            k=ts.k, normalisation=norm, depressed_per_replicate=tuple(per))
        self.events.append(ev)
        return ev

    # -- the two applications ---------------------------------------------

    def _apply_single(self, trace: StoredTrace, episode_id: int, valence: int,
                      amount: float) -> int:
        """Phase One's path, byte for byte: install, reinforce, discard."""
        self.mb.trace[:] = 0.0
        self.mb.trace_episode[:] = -1
        self.mb.trace[trace.index] = trace.value
        self.mb.trace_episode[trace.index] = episode_id
        self.mb.begin_episode(episode_id)
        n = self.mb.dopamine(int(valence), float(amount), episode_id=episode_id)
        self.mb.apply()
        self.mb.trace[:] = 0.0
        self.mb.trace_episode[:] = -1
        return int(n)

    def _apply_normalised(self, ts: StoredTraceSet, valence: int,
                          amount: float):
        """The canonical rule of D4 §4, in five lines.

        Every replicate's proposed delta is computed against ``g0``, the one
        pre-update state — not against the running result — so eight identical
        traces necessarily give the same update as one, and the order the
        replicates are visited in cannot matter. The mean is taken over the k
        replicates held sorted by index, so permutation invariance is exact.
        """
        g0 = self.mb.gain.astype(np.float64)
        total = np.zeros_like(g0)
        dense = np.zeros(len(self.mb.trace), dtype=np.float64)
        per = []
        for t in ts.traces:
            dense[:] = 0.0
            dense[t.index] = t.value
            d, n = self.mb.proposed_gain_delta(valence, amount, dense, gain=g0)
            total += d
            per.append(int(n))
        total /= float(ts.k)
        moved = int(np.count_nonzero(total))
        self.mb.gain[:] = np.clip(g0 + total, self.mb.floor,
                                  1.0).astype(np.float32)
        self.mb.apply()
        self.mb.events["reward" if valence > 0 else "punish"] += 1
        # the live eligibility layer is not where this came from and is not
        # left holding it: the traces were replayed from the decision record
        self.mb.trace[:] = 0.0
        self.mb.trace_episode[:] = -1
        self.mb.begin_episode(ts.episode_id)
        return moved, per

    def decay(self) -> None:
        """One decision cycle of recovery drift on the learned weights."""
        self.mb.forget()
        self.mb.apply()

    def stats(self) -> dict:
        return {"accepted": self.accepted, "open": sorted(self.open),
                "settled": len(self.settled),
                "rejections": dict(self.rejections),
                "rejections_total": sum(self.rejections.values())}
