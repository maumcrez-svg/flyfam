"""
Time, memory and persistence — the four state layers kept apart.

Canonical amendment §6. The point of this module is that four things that get
casually called "the fly's state" have different lifetimes, and mixing them is
how a delayed reward ends up applied to the wrong experience.

| layer | lives for | persists across a restart |
|---|---|---|
| **electrical** | one `FlyBrain.run()` call | **no** — and it cannot, see below |
| **eligibility traces** | a few decision cycles | **no**, deliberately |
| **learned weights** | the life of the experiment | **yes**, checkpointed |
| **episode log** | forever, append-only | **yes**, never rewritten |

*Electrical.* `flysim.py:101` re-initialises every membrane potential at the
top of every `run()`. There is no electrical state to save and saving one
would be a lie. `MushroomBody.reset_electrical()` exists only so the layer has
a named entry point.

*Eligibility.* A trace records "this Kenyon cell fired recently". After a
process restart the fly did not fire recently; it did not exist. Restoring a
trace would let a reward earned before the restart depress synapses that were
never active in this process. Traces start empty, always.

*Learned weights.* The 44,042 KC→MBON gains, and nothing else in the
connectome is plastic.

*Episode log.* Append-only. A new record never edits an old one.

## Time

The unit is one **decision cycle** — one observation, one brain window, one
decision. Its length is a property of the experiment, not of how often a
frontend happens to call:

    DECISION_CYCLE_MS = 500 ms

Upstream hard-codes a trace decay of 0.55 *per control step* and a recovery of
0.0008 *per step* (`mushroom.py:53`), with `roam.py` stepping at 2 Hz. Those
are per-call constants dressed as biology: change the call rate and the memory
duration changes with it. We convert them once into time constants and derive
the per-cycle factor from the cycle length:

    decay_per_cycle    = exp(-cycle_ms / ELIGIBILITY_TAU_MS)
    recovery_per_cycle = 1 - exp(-cycle_ms / RECOVERY_TAU_MS)

`ELIGIBILITY_TAU_MS` and `RECOVERY_TAU_MS` are chosen so that **at a 500 ms
cycle the factors reproduce upstream's 0.55 and 0.0008 exactly** — the
parameters are unchanged, the dependence on call rate is gone. τ_eligibility
≈ 836 ms; τ_recovery ≈ 625 s (~10.4 min).

Both are modelling choices of ours. The measured eligibility window for
dopamine-dependent depression in *Drosophila* is on the order of seconds
(Cohn, Morantte & Ruta 2015, *Cell* 163:1742; Aso & Rubin 2016, *eLife*
5:e16135), which is the right order of magnitude but is not what these numbers
were fitted to. They came from upstream and we have kept them; that is the
honest description.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

SCHEMA_VERSION = "flytrade-state-1"

#: one observation -> one brain window -> one decision
DECISION_CYCLE_MS = 500.0

#: derived so exp(-500/tau) == 0.55, upstream's per-step trace decay
ELIGIBILITY_TAU_MS = -DECISION_CYCLE_MS / math.log(0.55)

#: derived so 1 - exp(-500/tau) == 0.0008, upstream's per-step recovery
RECOVERY_TAU_MS = -DECISION_CYCLE_MS / math.log(1.0 - 0.0008)


def trace_decay_per_cycle(cycle_ms: float = DECISION_CYCLE_MS,
                          tau_ms: float = ELIGIBILITY_TAU_MS) -> float:
    """Multiplier applied to the eligibility trace once per decision cycle."""
    return math.exp(-cycle_ms / tau_ms)


def recovery_per_cycle(cycle_ms: float = DECISION_CYCLE_MS,
                       tau_ms: float = RECOVERY_TAU_MS) -> float:
    """Fraction of the way back to baseline a gain drifts per decision cycle."""
    return 1.0 - math.exp(-cycle_ms / tau_ms)


# ------------------------------------------------------------------- layers

@dataclass
class ElectricalState:
    """Membrane potentials. Intentionally empty.

    ``flysim.FlyBrain.run`` resets ``v`` to rest at the start of every call, so
    no electrical state survives a window, let alone a restart. Recorded as a
    layer so nobody later assumes one exists.
    """
    persists_across_cycles: bool = False
    persists_across_restart: bool = False


@dataclass
class EligibilityState:
    """Which KC→MBON synapses are currently eligible, and for which episode."""
    trace: np.ndarray
    episode: np.ndarray
    persists_across_restart: bool = False

    @classmethod
    def empty(cls, n: int) -> "EligibilityState":
        return cls(trace=np.zeros(n, dtype=np.float32),
                   episode=np.full(n, -1, dtype=np.int64))


@dataclass
class EpisodeRecord:
    """One episode. Append-only: fields are written once."""
    episode_id: int
    started_at: float
    stimulus: str
    rng_seed: int
    readout: dict = field(default_factory=dict)
    reinforcement: dict | None = None
    synapses_depressed: int = 0


class EpisodeLog:
    """Append-only episode history, optionally mirrored to a JSONL file.

    Never rewrites a record. ``append`` is the only mutator.
    """

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else None
        self._records: list[EpisodeRecord] = []
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, rec: EpisodeRecord) -> EpisodeRecord:
        if any(r.episode_id == rec.episode_id for r in self._records):
            raise ValueError(f"episode {rec.episode_id} is already logged; "
                             "the log is append-only")
        self._records.append(rec)
        if self.path is not None:
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(rec), sort_keys=True) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        return rec

    def __len__(self):
        return len(self._records)

    def __iter__(self):
        return iter(tuple(self._records))

    @property
    def records(self) -> tuple[EpisodeRecord, ...]:
        return tuple(self._records)


# --------------------------------------------------------------- checkpoint

class CheckpointError(RuntimeError):
    """Raised for every checkpoint failure. Never swallowed.

    Upstream's ``mushroom.save``/``load`` catch ``Exception`` and ``pass``
    (`mushroom.py:170`, `mushroom.py:193`): a failed write is silent and a
    corrupt store silently restarts from baseline. Both are forbidden here.
    """


_REQUIRED = ("schema", "gain", "pos", "graph_sha256", "rng_seed",
             "episode", "digest")


def _digest(gain: np.ndarray, pos: np.ndarray, graph_sha256: str) -> str:
    h = hashlib.sha256()
    h.update(np.ascontiguousarray(gain, dtype=np.float32).tobytes())
    h.update(np.ascontiguousarray(pos, dtype=np.int64).tobytes())
    h.update(graph_sha256.encode())
    return h.hexdigest()


#: public name for the same digest. The checkpoint uses it to detect a corrupt
#: store; ``flytrade/readout.py`` uses it as the *learned-state version* that
#: enters every replicate seed, so a batch taken under different weights is a
#: different batch (D4 amendment §1, Fable addendum 2).
learned_state_digest = _digest


def save_checkpoint(path, *, gain: np.ndarray, pos: np.ndarray,
                    graph_sha256: str, rng_seed: int, episode: int,
                    events: dict | None = None,
                    cycle_ms: float = DECISION_CYCLE_MS) -> Path:
    """Write the learned weights atomically. Raises on any failure.

    Atomicity: write into a temporary file in the destination directory,
    ``flush`` + ``fsync`` it, ``os.replace`` it over the target (atomic on
    POSIX), then ``fsync`` the directory so the rename itself is durable. A
    crash at any point leaves either the previous checkpoint or the new one,
    never a half-written file.
    """
    path = Path(path)
    gain = np.ascontiguousarray(gain, dtype=np.float32)
    pos = np.ascontiguousarray(pos, dtype=np.int64)
    if len(gain) != len(pos):
        raise CheckpointError(
            f"gain ({len(gain)}) and pos ({len(pos)}) must have equal length")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        os.close(fd)
        tmp = Path(tmp)
        with open(tmp, "wb") as fh:
            np.savez(
                fh,
                schema=np.str_(SCHEMA_VERSION),
                gain=gain, pos=pos,
                graph_sha256=np.str_(graph_sha256),
                rng_seed=np.int64(rng_seed),
                episode=np.int64(episode),
                cycle_ms=np.float64(cycle_ms),
                eligibility_tau_ms=np.float64(ELIGIBILITY_TAU_MS),
                recovery_tau_ms=np.float64(RECOVERY_TAU_MS),
                events=np.str_(json.dumps(events or {}, sort_keys=True)),
                saved_at=np.float64(time.time()),
                digest=np.str_(_digest(gain, pos, graph_sha256)),
            )
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        dfd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except CheckpointError:
        raise
    except Exception as exc:                       # never silently swallowed
        raise CheckpointError(f"failed to write checkpoint {path}: {exc}") from exc
    return path


def load_checkpoint(path, *, graph_sha256: str, expect_pos: np.ndarray | None = None):
    """Load a checkpoint, validating version, graph hash and contents.

    Raises :class:`CheckpointError` on a missing file, an unreadable or
    truncated file, an unknown schema version, a graph-hash mismatch, a
    position-vector mismatch or a content-digest mismatch. It never returns a
    silently-discarded default: a caller who wants to start fresh must say so
    by not calling this.
    """
    path = Path(path)
    if not path.exists():
        raise CheckpointError(f"no checkpoint at {path}")
    try:
        z = np.load(path, allow_pickle=False)
        keys = set(z.files)
    except Exception as exc:
        raise CheckpointError(f"checkpoint {path} is unreadable: {exc}") from exc

    missing = [k for k in _REQUIRED if k not in keys]
    if missing:
        raise CheckpointError(f"checkpoint {path} is missing {missing}")

    schema = str(z["schema"])
    if schema != SCHEMA_VERSION:
        raise CheckpointError(
            f"checkpoint {path} has schema {schema!r}, expected "
            f"{SCHEMA_VERSION!r}")

    try:
        gain = z["gain"].astype(np.float32)
        pos = z["pos"].astype(np.int64)
        stored_graph = str(z["graph_sha256"])
        digest = str(z["digest"])
    except Exception as exc:
        raise CheckpointError(f"checkpoint {path} is corrupt: {exc}") from exc

    if stored_graph != graph_sha256:
        raise CheckpointError(
            f"checkpoint {path} was written against graph {stored_graph[:12]} "
            f"but the graph in use is {graph_sha256[:12]}; learned weights are "
            "meaningless against a different set of synapses")
    if _digest(gain, pos, stored_graph) != digest:
        raise CheckpointError(f"checkpoint {path} failed its content digest")
    if expect_pos is not None and not np.array_equal(pos, np.asarray(expect_pos)):
        raise CheckpointError(
            f"checkpoint {path} holds {len(pos)} synapse positions that do not "
            f"match the {len(expect_pos)} in the running mushroom body")

    try:
        return {
            "gain": gain, "pos": pos, "graph_sha256": stored_graph,
            "rng_seed": int(z["rng_seed"]), "episode": int(z["episode"]),
            "cycle_ms": float(z["cycle_ms"]),
            "eligibility_tau_ms": float(z["eligibility_tau_ms"]),
            "recovery_tau_ms": float(z["recovery_tau_ms"]),
            "events": json.loads(str(z["events"])),
            "saved_at": float(z["saved_at"]),
            "schema": schema,
        }
    except Exception as exc:
        raise CheckpointError(f"checkpoint {path} is corrupt: {exc}") from exc
