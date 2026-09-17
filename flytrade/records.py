"""
Records, the append-only event log, and crash-safe settlement.

Canonical amendment §7. Extends `flytrade/state.py` rather than replacing it:
the atomic checkpoint, the schema validation and the refusal to swallow a
corrupt store are all reused unchanged.

## Every decision is linked end to end

One :class:`DecisionRecord` carries the whole chain the amendment lists —
observation, encoded stimulus, brain version, readout, action, execution,
outcome, learning event — together with every seed, version and timestamp a
replay needs:

* seeds: the round seed and the candidate's own Poisson seed;
* versions: market, encoder, runner, decoder, execution, plasticity, and the
  graph's sha256 plus the brain checkpoint's content digest;
* timestamps: the observation cutoff in market time, the wall clock at the
  decision, and the bar indices of both fills;
* ``readout_status``, so `VALID`+`WAIT`, `NO_RESPONSE`, `INVALID_STATE` and
  `POLICY_REJECT` stay four different things in every record (Fable addendum 4).

## Crash safety at the outcome/learning boundary

An outcome must be applied exactly once. The order is fixed:

1. append ``OUTCOME`` to the log and fsync it;
2. apply the reinforcement to the episode's stored trace;
3. write the checkpoint atomically, stamped with this episode as the **last
   settled** one;
4. remove the pending-episode file;
5. append ``LEARNING`` to the log.

Recovery reads the checkpoint's ``last_settled_episode`` and the log, and an
outcome counts as still owed iff there is an ``OUTCOME`` event for it, no
``LEARNING`` event, **and** the checkpoint does not already name it as settled.
A crash between 1 and 3 replays the reinforcement onto weights that never
received it; a crash between 3 and 5 re-appends only the log line. Neither path
can apply it twice and neither can lose it.

The pending file is where the selected episode's stored trace lives between
decision and outcome. It is a **record of the episode**, not the live
eligibility layer: `state.py`'s rule that traces never survive a restart is
unchanged, and this file is no more a live trace than the DecisionRecord is a
live readout.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path

import numpy as np

from . import runner as R
from . import state as S

VERSION = "flytrade-records-2"
#: bumped by D4: the pending episode now stores k eligibility traces, not one
SCHEMA = "flytrade-k8-1"


class EventType(str, Enum):
    ROUND = "ROUND"
    #: D4 addendum 4: a replicate raised. No decision was taken and the round
    #: produced nothing else. Kept distinct from every readout status, because
    #: a technical execution failure is not a neural result.
    ROUND_ABORTED = "ROUND_ABORTED"
    DECISION = "DECISION"
    EXECUTION = "EXECUTION"
    OUTCOME = "OUTCOME"
    LEARNING = "LEARNING"
    CHECKPOINT = "CHECKPOINT"
    RECOVERY = "RECOVERY"
    #: D6 Fable addendum 3: the WARMUP partition runs features only. No brain
    #: is run and no DECISION is written; one of these records the session's
    #: observation statuses so the partition is auditable rather than absent.
    WARMUP = "WARMUP"
    #: D6: a partition or a branch opened or closed, with the checkpoint hash
    #: at that boundary. This is what makes "the frozen branch did not learn"
    #: a comparison of two recorded hashes rather than a claim.
    PARTITION = "PARTITION"
    #: D10 addendum 13: one launch was seen, and whether it was admitted, with
    #: its reason codes. Nothing existing fits: it is not a round, not a
    #: decision and not a warmup session. It is what makes the dataset the
    #: launches that happened rather than the launches that survived
    #: (amendment section 7).
    DISCOVERY = "DISCOVERY"
    #: D12 addendum 12: one relative-cohort lesson was applied. It is not an
    #: OUTCOME — no position was ever opened, no PnL is booked and no account
    #: moved — and it is not a LEARNING record either, because it carries the
    #: cohort the signal came from: the size, the rank, the integer net and the
    #: signal s beside it. The financial net and the pedagogical signal are two
    #: columns on it and are never merged.
    LESSON = "LESSON"
    #: D10 addendum 12: a position is still open and could not be settled — the
    #: curve completed onto the unsupported route, the data does not reach the
    #: horizon, or the blocks are not confirmed yet. It is **not** an OUTCOME:
    #: no PnL is booked, no reward is delivered and the exposure is retained.
    UNRESOLVED = "UNRESOLVED"

    # P1 addendum 4: the nine kinds the **product feed** writes
    # (``flytrade.product.feed``). They are record kinds of this repository
    # like every member above — the observer's vocabulary is asserted equal to
    # this enum — but no :class:`Journal` method writes one: the journal keeps
    # the audit stream it always kept, and the feed is the spectacle's own
    # append-only day file. No log written before P1 contains any of them.
    #: one per tick: the candidates seen, with their admission outcome
    SNIFF = "SNIFF"
    #: the round's selected candidate, with the brain's snapshot and the action
    PICK = "PICK"
    #: a paper position was opened
    OPEN = "OPEN"
    #: what the open position would fetch at this tick. A mark, never a reward
    MARK = "MARK"
    #: a paper position was closed at its horizon
    CLOSE = "CLOSE"
    #: the reinforcement the absolute rule **would** deliver for one settled
    #: episode, recorded and **not applied**: the product loop is FROZEN
    CREDIT = "CREDIT"
    #: one tick happened, with the counters, the account and the position
    HEARTBEAT = "HEARTBEAT"
    #: the rolling hourly request cap was reached; the loop waits, it does not
    #: exit
    THROTTLED = "THROTTLED"
    #: an endpoint failure, counted, with the backoff it caused
    RPC_ERROR = "RPC_ERROR"


@dataclass(frozen=True)
class Versions:
    """Everything a replay has to pin down. Copied into every record."""

    market: str
    encoder: str
    runner: str
    decoder: str
    execution: str
    mushroom: str
    graph_sha256: str
    schema: str = SCHEMA
    records: str = VERSION

    def as_dict(self) -> dict:
        return asdict(self)


#: keys stripped before a DecisionRecord is digested. ``symbol`` because the
#: digest must be invariant under renaming a ticker (D4 §1, Fable addendum 2);
#: ``wall_clock`` because it is measurement compute time, not the experiment or
#: market clock, and a deterministic recompute after a restart cannot reproduce
#: it (addendum 3 and 7).
DIGEST_EXCLUDED = ("symbol", "wall_clock", "compute_s")


def _canonical(obj):
    if isinstance(obj, dict):
        return {k: _canonical(v) for k, v in obj.items()
                if k not in DIGEST_EXCLUDED}
    if isinstance(obj, (list, tuple)):
        return [_canonical(v) for v in obj]
    return obj


@dataclass
class DecisionRecord:
    """One decision, from the bar it saw to the weights it eventually moved."""

    episode_id: int
    round_index: int
    round_seed: int
    candidate_seed: int
    symbol: str
    stable_id: int
    bar_index: int
    cutoff_ts: int
    wall_clock: float
    versions: dict
    checkpoint_digest: str
    observation: dict
    stimulus: dict | None
    readout: dict | None
    decoded_action: str
    readout_status: str
    decoder: dict
    trace: dict | None
    n_candidates: int = 0
    selected: bool = False
    #: D6 Fable addendum 3: market time and brain time are two clocks and both
    #: are in every decision. ``cutoff_ts`` above is market time (bar_end, UTC);
    #: these are brain time, one decision cycle per round.
    brain_cycle: int = 0
    brain_ms: float = 0.0
    #: D6: where this decision sits in the fixed historical protocol
    partition: str = ""
    branch: str = ""
    run_id: str = ""
    dataset_label: str = ""
    #: D4. ``k`` presentations went into ``readout``, which is their aggregate;
    #: ``replicates`` is every per-replicate measurement §2 requires stored -
    #: rates, spike counts, status, continuous score, seed, eligibility -
    #: and ``traces`` is the k-trace eligibility set the outcome will reach.
    k: int = 1
    readout_policy: dict | None = None
    replicates: list | None = None
    traces: dict | None = None
    executed_action: str | None = None
    execution: dict | None = None
    rejection: dict | None = None
    outcome: dict | None = None
    learning: dict | None = None

    def as_dict(self) -> dict:
        return asdict(self)

    def digest(self) -> str:
        """Content digest of the decision, for restart and invariance checks.

        Everything the decision was computed from and everything it produced,
        minus the ticker's spelling and minus wall-clock time. Two runs that
        agree on this digest took the same decision from the same measurements:
        it is what addendum 2's permutation/renaming test and addendum 7's
        mid-batch restart test both compare.
        """
        payload = json.dumps(_canonical(self.as_dict()), sort_keys=True,
                             default=_json_default)
        return hashlib.sha256(payload.encode()).hexdigest()


def decision_record(cand, decision, *, round_index: int, bar_index: int,
                    versions: Versions, checkpoint_digest: str,
                    n_candidates: int, round_seed: int = 0,
                    readout_policy: dict | None = None, selected: bool = True,
                    wall_clock: float | None = None,
                    brain_cycle: int | None = None, brain_ms: float | None = None,
                    partition: str = "", branch: str = "", run_id: str = "",
                    dataset_label: str = "") -> DecisionRecord:
    """One :class:`DecisionRecord` from one evaluated candidate.

    The k = 1 and k = 8 loops build the same record from the same fields; this
    is that construction, in one place, so the two cannot drift apart.
    """
    batch = getattr(cand, "batch", None)
    return DecisionRecord(
        episode_id=cand.episode_id, round_index=int(round_index),
        round_seed=int(round_seed), candidate_seed=int(cand.seed),
        symbol=cand.symbol, stable_id=cand.stable_id,
        bar_index=int(bar_index), cutoff_ts=cand.observation.cutoff_ts,
        wall_clock=time.time() if wall_clock is None else float(wall_clock),
        versions=versions.as_dict(), checkpoint_digest=checkpoint_digest,
        observation=cand.observation.as_dict(),
        stimulus=cand.stimulus.as_dict() if cand.stimulus else None,
        readout=cand.presentation.as_dict() if cand.presentation else None,
        decoded_action=decision.action.value,
        readout_status=decision.status.value, decoder=decision.as_dict(),
        trace=cand.trace.as_dict() if cand.trace else None,
        n_candidates=int(n_candidates), selected=bool(selected),
        k=cand.k, readout_policy=readout_policy,
        replicates=([r.as_dict() for r in batch.replicates]
                    if batch is not None else None),
        traces=cand.traces.as_dict() if cand.traces else None,
        brain_cycle=int(round_index if brain_cycle is None else brain_cycle),
        brain_ms=float(
            (round_index if brain_cycle is None else brain_cycle)
            * S.DECISION_CYCLE_MS if brain_ms is None else brain_ms),
        partition=partition, branch=branch, run_id=run_id,
        dataset_label=dataset_label)


class EventLog:
    """Append-only JSONL. A record is never edited, only followed.

    Each append is flushed and fsynced, so an event that the caller believes is
    on disk is on disk. That is what makes the recovery rule below decidable.
    """

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, kind: EventType, payload: dict) -> dict:
        rec = {"t": time.time(), "kind": EventType(kind).value, **payload}
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, sort_keys=True, default=_json_default)
                     + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return rec

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        with open(self.path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    # a torn final line is the only corruption a crash can
                    # produce in an append-only file; it is dropped and said so
                    out.append({"kind": "TORN", "raw": line})
        return out

    def episodes_with(self, kind: EventType) -> set[int]:
        k = EventType(kind).value
        return {int(r["episode_id"]) for r in self.read()
                if r.get("kind") == k and "episode_id" in r}

    def __len__(self) -> int:
        return len(self.read())


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, Enum):
        return o.value
    raise TypeError(f"{type(o)} is not JSON serialisable")


# ------------------------------------------------------ pending episode

def write_pending(path, *, episode_id: int, symbol: str, stable_id: int,
                  trace, decision_bar: int, graph_sha256: str) -> Path:
    """Store the open episode's eligibility atomically. Same discipline as state.py.

    ``trace`` is a :class:`flytrade.runner.StoredTraceSet` — the k traces the
    outcome will be applied to — or a single trace, wrapped into a set of one.
    The k replicates are stored concatenated with their lengths, in replicate
    order, so that what comes back is the same set in the same order and the
    normalised update is the same after a restart as before it.
    """
    ts = R.CreditAssigner.as_set(trace)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    os.close(fd)
    tmp = Path(tmp)
    lens = np.array([len(t.index) for t in ts.traces], dtype=np.int64)
    idx = (np.concatenate([t.index for t in ts.traces]) if ts.k
           else np.array([], dtype=np.int64))
    val = (np.concatenate([t.value for t in ts.traces]) if ts.k
           else np.array([], dtype=np.float32))
    try:
        with open(tmp, "wb") as fh:
            np.savez(fh, schema=np.str_(SCHEMA),
                     episode_id=np.int64(episode_id), symbol=np.str_(symbol),
                     stable_id=np.int64(stable_id),
                     k=np.int64(ts.k), lengths=lens,
                     index=np.ascontiguousarray(idx, dtype=np.int64),
                     value=np.ascontiguousarray(val, dtype=np.float32),
                     n_synapses=np.int64(ts.n_synapses),
                     decision_bar=np.int64(decision_bar),
                     graph_sha256=np.str_(graph_sha256))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        dfd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except Exception as exc:
        raise S.CheckpointError(f"failed to write {path}: {exc}") from exc
    return path


def read_pending(path, *, graph_sha256: str | None = None) -> dict | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        z = np.load(path, allow_pickle=False)
        schema = str(z["schema"])
        if schema != SCHEMA:
            raise S.CheckpointError(
                f"pending episode {path} has schema {schema!r}, expected "
                f"{SCHEMA!r}")
        stored_graph = str(z["graph_sha256"])
        if graph_sha256 is not None and stored_graph != graph_sha256:
            raise S.CheckpointError(
                f"pending episode {path} was stored against graph "
                f"{stored_graph[:12]} but the graph in use is "
                f"{graph_sha256[:12]}")
        ep = int(z["episode_id"])
        n_syn = int(z["n_synapses"])
        lens = z["lengths"].astype(np.int64)
        idx, val = z["index"].astype(np.int64), z["value"].astype(np.float32)
        cuts = np.concatenate(([0], np.cumsum(lens)))
        traces = [R.StoredTrace(episode_id=ep, index=idx[a:b],
                                value=val[a:b], n_synapses=n_syn)
                  for a, b in zip(cuts[:-1], cuts[1:])]
        ts = R.StoredTraceSet.of(ep, traces)
        return {
            "episode_id": ep, "symbol": str(z["symbol"]),
            "stable_id": int(z["stable_id"]),
            "decision_bar": int(z["decision_bar"]),
            "graph_sha256": stored_graph, "k": int(z["k"]),
            "traces": ts, "trace": ts.traces[0],
        }
    except S.CheckpointError:
        raise
    except Exception as exc:
        raise S.CheckpointError(f"pending episode {path} is corrupt: {exc}") from exc


def clear_pending(path) -> None:
    path = Path(path)
    if path.exists():
        path.unlink()
        dfd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)


# ------------------------------------------------------------- journal

class InjectedFault(RuntimeError):
    """Raised by the test harness at a named point of the settlement."""


#: the points at which the crash test may cut power
FAULT_POINTS = ("after_outcome_event", "after_learning_applied",
                "after_checkpoint", "after_pending_cleared")


class Journal:
    """Durable state for one running loop: log, checkpoint, pending episode."""

    version = VERSION

    def __init__(self, directory, *, mb, credit: R.CreditAssigner,
                 versions: Versions):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.log = EventLog(self.dir / "events.jsonl")
        self.checkpoint_path = self.dir / "brain.npz"
        self.pending_path = self.dir / "pending.npz"
        self.mb = mb
        self.credit = credit
        self.versions = versions
        self.decisions: dict[int, DecisionRecord] = {}
        #: D6: outcomes settled for accounting with learning off
        self.frozen_settled = 0
        #: D10 addendum 13: fields stamped onto **every** event this journal
        #: writes — ``venue``, ``chain_id``, ``mode``, ``learning``. Empty for
        #: every wave before D10, so their logs and their committed
        #: projections are unchanged.
        self.stamp: dict = {}
        #: D11 addendum 4: the input schema this journal's checkpoints were
        #: written under — ``encoder_version`` and ``input_schema_sha256``.
        #: It rides inside the checkpoint's digest-protected ``events`` blob
        #: and is checked on every load that would continue learning. Empty
        #: for every wave before D11, so their checkpoints and their logs are
        #: byte-identical and their recovery path is unchanged.
        self.schema_meta: dict = {}
        #: Set by the runner when the run is declared to start from the clean
        #: reference checkpoint, which predates the schema field and is the
        #: only checkpoint allowed to lack it.
        self.from_clean_reference: bool = False
        self.clean_reference_digest: str | None = None
        #: P1 addendum 3(c): a FROZEN settlement writes an ``OUTCOME`` marked
        #: ``SETTLED_FROZEN``, saves the checkpoint and writes **no**
        #: ``LEARNING`` record, because nothing was learned. A restart of such
        #: a loop must therefore not read those outcomes as outcomes whose
        #: learning went missing. With this flag on, :meth:`recover` counts a
        #: ``SETTLED_FROZEN`` outcome as already accounted for. ``False`` —
        #: every wave before P1 — leaves the recovery path exactly as it was.
        self.frozen_settlement_completes_the_log: bool = False

    # -- checkpoint -------------------------------------------------------

    @property
    def last_settled_episode(self) -> int:
        try:
            ck = S.load_checkpoint(self.checkpoint_path,
                                   graph_sha256=self.versions.graph_sha256,
                                   expect_pos=self.mb.pos)
        except S.CheckpointError:
            return -1
        return int(ck["episode"])

    def checkpoint_digest(self) -> str:
        return S._digest(self.mb.gain, self.mb.pos, self.versions.graph_sha256)

    def save_checkpoint(self, *, last_settled_episode: int) -> Path:
        """``episode`` in the checkpoint means *last settled episode* here.

        state.py already carries an episode counter and validates it under the
        same atomic replace; reusing it keeps the schema unchanged and keeps
        the settled marker inside the digest-protected, atomically-replaced
        file rather than beside it.
        """
        p = S.save_checkpoint(
            self.checkpoint_path, gain=self.mb.gain, pos=self.mb.pos,
            graph_sha256=self.versions.graph_sha256,
            rng_seed=0, episode=int(last_settled_episode),
            events={**self.credit.stats(), **self.schema_meta})
        self._append(EventType.CHECKPOINT,
                     {"episode_id": int(last_settled_episode),
                      "digest": self.checkpoint_digest(),
                      "path": str(self.checkpoint_path)})
        return p

    def load_checkpoint_into_brain(self) -> dict | None:
        try:
            ck = S.load_checkpoint(self.checkpoint_path,
                                   graph_sha256=self.versions.graph_sha256,
                                   expect_pos=self.mb.pos)
        except S.CheckpointError:
            return None
        self.check_schema(ck)
        self.mb.gain[:] = ck["gain"]
        self.mb.apply()
        return ck

    def check_schema(self, checkpoint: dict) -> str | None:
        """Refuse to continue learning under a different input schema.

        A no-op unless :attr:`schema_meta` was set, so every wave before D11
        loads exactly as it always did. When it is set, the checkpoint's own
        metadata must carry the same ``input_schema_sha256``; the one
        exemption is the declared clean reference of a ``from_clean_reference``
        run, which predates the field. Raises
        :class:`flytrade.pons.encoder_v2.SchemaMismatch` otherwise, because a
        brain whose weights address sixteen channels has no meaning on twenty.
        """
        want = self.schema_meta.get("input_schema_sha256")
        if not want:
            return None
        from .pons import encoder_v2 as E2
        return E2.check_checkpoint_schema(
            checkpoint.get("events") or {},
            input_schema_sha256=str(want),
            encoder_version=str(self.schema_meta.get(
                "encoder_version", E2.VERSION)),
            from_clean_reference=bool(self.from_clean_reference),
            checkpoint_digest=S._digest(
                checkpoint["gain"], checkpoint["pos"],
                checkpoint["graph_sha256"]),
            clean_reference_digest=self.clean_reference_digest)

    # -- the loop's events ------------------------------------------------

    def _append(self, kind: EventType, payload: dict) -> dict:
        """One event, with this journal's stamp merged in.

        The stamp is empty unless a caller set it, so this is a no-op for every
        wave before D10 and their logs stay byte-identical.
        """
        return self.log.append(kind, {**payload, **self.stamp}
                               if self.stamp else payload)

    def record_discovery(self, **fields) -> dict:
        """One launch was seen. D10 addendum 10: admitted or not, with reasons."""
        return self._append(EventType.DISCOVERY, dict(fields))

    def record_unresolved(self, **fields) -> dict:
        """A position could not be settled. Retained, never written off."""
        return self._append(EventType.UNRESOLVED, dict(fields))

    def record_lesson(self, **fields) -> dict:
        """One relative-cohort lesson was applied. D12 addendum 12.

        The caller passes the cohort the signal came from — ``cutoff_ts``,
        ``stable_id``, ``token``, ``n``, ``net_wei``, ``rank``, ``s``, the
        valence the readout produced at presentation, ``applied_at_tick`` and
        the state digest **after** the update. Nothing is computed here: this
        is the record, not the rule.
        """
        return self._append(EventType.LESSON, dict(fields))

    def record_round(self, rnd: R.RoundEvaluation, extra: dict | None = None
                     ) -> dict:
        return self._append(EventType.ROUND, {**(extra or {}), **{
            "round_index": rnd.round_index, "round_seed": rnd.round_seed,
            "cutoff_ts": rnd.cutoff_ts,
            "selection_rule": rnd.selection_rule,
            "scores": {str(k): round(float(v), 6)
                       for k, v in rnd.scores.items()},
            "readout": rnd.readout, "state_digest": rnd.state_digest,
            "candidates": [
                {"symbol": c.symbol, "stable_id": c.stable_id,
                 "episode_id": c.episode_id, "seed": c.seed, "k": c.k,
                 "status": c.observation.status.value,
                 "eligible": c.trace.n_eligible if c.trace else 0,
                 "eligible_union": (c.traces.n_eligible if c.traces else 0),
                 "silent_replicates": (
                     c.presentation.silent_replicates if c.presentation
                     else 0)}
                for c in rnd.candidates],
            "selected_stable_id": (rnd.selected.stable_id
                                   if rnd.selected else None),
        }})

    def record_decision(self, rec: DecisionRecord,
                        extra: dict | None = None) -> DecisionRecord:
        self.decisions[rec.episode_id] = rec
        self._append(EventType.DECISION, {**(extra or {}), **{
            "episode_id": rec.episode_id, "symbol": rec.symbol,
            "stable_id": rec.stable_id, "bar_index": rec.bar_index,
            "cutoff_ts": rec.cutoff_ts, "seed": rec.candidate_seed,
            "decoded_action": rec.decoded_action,
            "readout_status": rec.readout_status,
            "checkpoint_digest": rec.checkpoint_digest,
            "decision_digest": rec.digest(),
            "k": int(rec.k),
            # the two clocks, both, in every decision (Fable addendum 3)
            "market_ts": rec.cutoff_ts, "brain_cycle": rec.brain_cycle,
            "brain_ms": rec.brain_ms,
            "partition": rec.partition, "branch": rec.branch,
            "run_id": rec.run_id, "dataset_label": rec.dataset_label,
            "observation_status": rec.observation.get("status", ""),
            # D9(b): the execution policy's refusal, when there was one. The
            # DecisionRecord has carried this field since D5; writing it makes
            # "which rule refused this action" readable from the log instead
            # of inferred from the status. ``None`` when nothing refused.
            "rejection": rec.rejection,
            "valence_hz": rec.decoder.get("valence_hz"),
            "approach_hz": rec.decoder.get("approach_hz"),
            "avoid_hz": rec.decoder.get("avoid_hz"),
            "theta_hz": rec.decoder.get("theta_hz"),
            # what the market looked like, what it was encoded into, and what
            # was actually measured. A presentation layer may only display
            # telemetry that was recorded (amendment §7), so the fields it
            # needs are written here rather than reconstructed there.
            "observation": {
                "close": rec.observation.get("close"),
                "normalized": rec.observation.get("normalized"),
                "raw": rec.observation.get("raw"),
                "bar_index": rec.observation.get("bar_index")},
            "stimulus": None if rec.stimulus is None else {
                "rates_hz": rec.stimulus.get("rates_hz"),
                "n_orns": rec.stimulus.get("n_orns"),
                "total_drive_hz": rec.stimulus.get("total_drive_hz")},
            "readout": None if rec.readout is None else {
                "rates_hz": rec.readout.get("rates_hz"),
                "population_sizes": rec.readout.get("population_sizes"),
                "kc_fraction": rec.readout.get("kc_fraction"),
                "kc_active": rec.readout.get("kc_active"),
                "max_rate_hz": rec.readout.get("max_rate_hz"),
                "silent_replicates": rec.readout.get("silent_replicates"),
                "k": rec.readout.get("k")},
            "replicate_scores": (
                None if not rec.replicates
                else [r.get("score_hz") for r in rec.replicates]),
            "replicate_statuses": (
                None if not rec.replicates
                else [r.get("status") for r in rec.replicates]),
            "n_candidates": rec.n_candidates,
            "versions": rec.versions,
        }})
        return rec

    def record_round_aborted(self, *, round_index: int, cutoff_ts: int,
                             reason: str, stable_id: int | None = None,
                             replicate: int | None = None) -> dict:
        """A replicate raised. One event, no decision, nothing averaged.

        Addendum 4: a technical failure aborts the round. It is not a readout
        status, it is not a WAIT, and the partial batch is discarded rather
        than averaged over its successful subset.
        """
        return self._append(EventType.ROUND_ABORTED, {
            "round_index": int(round_index), "cutoff_ts": int(cutoff_ts),
            "reason": str(reason),
            "stable_id": None if stable_id is None else int(stable_id),
            "replicate": None if replicate is None else int(replicate)})

    def open_episode(self, rec: DecisionRecord, trace, execution: dict) -> None:
        """A decision became a position: store its eligibility durably.

        ``trace`` is the selected candidate's :class:`StoredTraceSet` — all k
        of them — or a single trace at k = 1.
        """
        rec.executed_action = "BUY"
        rec.execution = execution
        ts = self.credit.open_episode(trace)
        write_pending(self.pending_path, episode_id=rec.episode_id,
                      symbol=rec.symbol, stable_id=rec.stable_id, trace=ts,
                      decision_bar=rec.bar_index,
                      graph_sha256=self.versions.graph_sha256)
        self._append(EventType.EXECUTION,
                     {"episode_id": rec.episode_id, "symbol": rec.symbol,
                      "k": ts.k, **execution})

    # -- the boundary the crash test attacks ------------------------------

    def settle(self, episode_id: int, outcome: dict, valence: int,
               amount: float, *, fault: str | None = None,
               extra: dict | None = None) -> R.LearningEvent:
        """Apply one outcome exactly once. Steps 1-5 of the module docstring.

        ``extra`` is additive and optional (D11-001 addendum 10): fields the
        caller wants on the ``LEARNING`` record beside the event's own — the
        raw net outcome, the full scale it was divided by and whether the
        amount clipped at the cap. They are written **under** the event's
        fields, so nothing the event names can be overwritten by a caller, and
        a caller that passes nothing produces exactly the record every D5-D10
        run produced.
        """
        if fault is not None and fault not in FAULT_POINTS:
            raise ValueError(f"unknown fault point {fault!r}")

        self._append(EventType.OUTCOME,
                     {"episode_id": int(episode_id), **outcome})
        if fault == "after_outcome_event":
            raise InjectedFault("power lost after the outcome was recorded")

        ev = self.credit.settle(int(episode_id), int(valence), float(amount))
        if fault == "after_learning_applied":
            raise InjectedFault("power lost after the weights moved")

        self.save_checkpoint(last_settled_episode=int(episode_id))
        if fault == "after_checkpoint":
            raise InjectedFault("power lost after the checkpoint was durable")

        clear_pending(self.pending_path)
        if fault == "after_pending_cleared":
            raise InjectedFault("power lost after the pending episode was "
                                "cleared")

        self._append(EventType.LEARNING,
                     {"episode_id": int(episode_id), **(extra or {}),
                      **ev.as_dict()})
        rec = self.decisions.get(int(episode_id))
        if rec is not None:
            rec.outcome = outcome
            rec.learning = ev.as_dict()
        return ev

    def settle_frozen(self, episode_id: int, outcome: dict) -> dict:
        """Settle one outcome **for accounting only**. D6 §4, addendum 6.

        Frozen means the learned weights do not change. The transient
        simulation still runs and eligibility is still laid down; it is simply
        never applied. So this writes the ``OUTCOME`` event, marks the episode
        settled so a restart cannot replay it, clears the pending file — and
        writes **no** ``LEARNING`` event and calls no reinforcement. The
        settlement counter records ``SETTLED_FROZEN`` instead.

        The checkpoint is saved with the episode as last-settled, which moves
        the episode counter and **not** the gains, so the partition's end
        digest equals its start digest.
        """
        ep = int(episode_id)
        self._append(EventType.OUTCOME,
                     {"episode_id": ep, "settlement": "SETTLED_FROZEN",
                      **outcome})
        self.credit.open.pop(ep, None)
        self.credit.settled.add(ep)
        self.frozen_settled += 1
        self.save_checkpoint(last_settled_episode=ep)
        clear_pending(self.pending_path)
        rec = self.decisions.get(ep)
        if rec is not None:
            rec.outcome = outcome
            rec.learning = {"accepted": False, "settlement": "SETTLED_FROZEN",
                            "reason": "frozen evaluation: learning is off"}
        return {"episode_id": ep, "settlement": "SETTLED_FROZEN"}

    def record_warmup(self, *, session: str, counts: dict,
                      observations: int) -> dict:
        """One WARMUP event per session: the partition ran, and what it saw."""
        return self._append(EventType.WARMUP, {
            "session": str(session), "observations": int(observations),
            "status_counts": dict(counts),
            "neural": False, "decisions": 0,
            "note": "features only; no brain was run and no decision taken"})

    def record_partition(self, *, name: str, boundary: str, branch: str = "",
                         **extra) -> dict:
        """A partition or branch boundary, stamped with the state digest."""
        return self._append(EventType.PARTITION, {
            "partition": str(name), "boundary": str(boundary),
            "branch": str(branch),
            "state_digest": self.checkpoint_digest(),
            "last_settled_episode": self.last_settled_episode, **extra})

    # -- recovery ---------------------------------------------------------

    def recover(self) -> dict:
        """Bring a restarted process back to a consistent state.

        Returns a summary naming exactly what was done, so a caller can assert
        on it instead of inferring it.
        """
        ck = self.load_checkpoint_into_brain()
        settled = -1 if ck is None else int(ck["episode"])
        events = self.log.read()
        outcomes = {int(e["episode_id"]) for e in events
                    if e.get("kind") == EventType.OUTCOME.value}
        learned = {int(e["episode_id"]) for e in events
                   if e.get("kind") == EventType.LEARNING.value}
        if self.frozen_settlement_completes_the_log:
            learned |= {int(e["episode_id"]) for e in events
                        if e.get("kind") == EventType.OUTCOME.value
                        and e.get("settlement") == "SETTLED_FROZEN"}
        pending = read_pending(self.pending_path,
                               graph_sha256=self.versions.graph_sha256)

        # the settled set is durable state, not memory: rebuild it from the
        # log's LEARNING lines and from the checkpoint's own settled marker,
        # so a restarted process cannot accept an outcome it already applied
        self.credit.settled |= learned
        if settled >= 0:
            self.credit.settled.add(settled)
        # the accept/reject counters are durable too: they ride in the
        # checkpoint's events field, so a restarted process reports the run's
        # totals rather than starting the tally again from zero
        if ck is not None and isinstance(ck.get("events"), dict):
            ev = ck["events"]
            self.credit.accepted = max(self.credit.accepted,
                                       int(ev.get("accepted", 0)))
            for k, v in (ev.get("rejections") or {}).items():
                if k in self.credit.rejections:
                    self.credit.rejections[k] = max(
                        self.credit.rejections[k], int(v))

        out = {"checkpoint_loaded": ck is not None,
               "last_settled_episode": settled,
               "outcomes_recorded": sorted(outcomes),
               "learning_recorded": sorted(learned),
               "pending_episode": pending["episode_id"] if pending else None,
               "action": "nothing to do", "reapplied": False,
               "episode_reopened": None, "log_completed": False}

        if pending is None:
            # nothing in flight. Any outcome without a LEARNING line whose
            # episode the checkpoint already names as settled only needs the
            # log line; the weights are already correct.
            owed = sorted(e for e in outcomes - learned if e > settled)
            if owed:
                out["action"] = ("outcome recorded with no stored trace and no "
                                 "settled marker: cannot be replayed")
                out["unrecoverable"] = owed
            else:
                for e in sorted(outcomes - learned):
                    self.log.append(EventType.LEARNING,
                                    {"episode_id": e, "accepted": True,
                                     "recovered": True,
                                     "reason": "checkpoint already names this "
                                               "episode as settled",
                                     "eligibility_source":
                                         "replayed_from_decision"})
                    self.credit.settled.add(e)
                    self.credit.open.pop(e, None)
                    out["log_completed"] = True
                    out["action"] = "completed the log for an applied outcome"
            self.log.append(EventType.RECOVERY, dict(out))
            return out

        ep = pending["episode_id"]
        if ep <= settled:
            # the weights already have it: finish the paperwork only
            clear_pending(self.pending_path)
            if ep not in learned:
                self.log.append(EventType.LEARNING, {
                    "episode_id": ep, "accepted": True, "recovered": True,
                    "reason": "checkpoint already names this episode as "
                              "settled; learning was applied before the crash",
                    "eligibility_source": "replayed_from_decision"})
                out["log_completed"] = True
            out["action"] = "learning was already applied; completed the log"
            self.credit.settled.add(ep)
            self.credit.open.pop(ep, None)
        elif ep in outcomes:
            # the outcome is on disk and the weights never got it: replay
            self.credit.open.setdefault(ep, pending["traces"])
            out["action"] = "replayed the stored trace for a recorded outcome"
            out["reapplied"] = True
            out["pending_k"] = pending["k"]
            out["pending_trace_eligible"] = pending["traces"].n_eligible
        else:
            # the episode is genuinely still open
            self.credit.open.setdefault(ep, pending["traces"])
            out["pending_k"] = pending["k"]
            out["action"] = "reopened an episode that had no outcome yet"
            out["episode_reopened"] = ep

        self.log.append(EventType.RECOVERY, dict(out))
        return out

    # -- reporting --------------------------------------------------------

    def replay_chain(self, episode_id: int) -> dict:
        """The full observation -> learning chain for one episode, from disk."""
        want = int(episode_id)
        chain: dict[str, list] = {}
        for e in self.log.read():
            if e.get("episode_id") == want or (
                    e.get("kind") == EventType.ROUND.value
                    and any(c.get("episode_id") == want
                            for c in e.get("candidates", []))):
                chain.setdefault(e["kind"], []).append(e)
        return chain

    def stats(self) -> dict:
        events = self.log.read()
        kinds: dict[str, int] = {}
        for e in events:
            kinds[e.get("kind", "?")] = kinds.get(e.get("kind", "?"), 0) + 1
        return {"events": len(events), "by_kind": kinds,
                "settled_frozen": self.frozen_settled,
                "last_settled_episode": self.last_settled_episode,
                "pending": (read_pending(self.pending_path) or {}).get(
                    "episode_id"),
                "credit": self.credit.stats()}
