#!/usr/bin/env python
"""What the D12 scripts share: the paths, the split, the driver, the weights.

D12 reuses the **D11 environment unchanged** — ``experiments/d11/config.json``
carries the ``admission_v2`` constants, the ``pons_context_v2`` features and
scales, the ``pons_encoder_v2`` input schema and the clean reference — and
changes only the teacher, which lives in ``experiments/d12/d12_001.json``. So
this module imports ``experiments/d11/common.py`` rather than restating any of
it, and nothing under ``experiments/d11/`` or ``data/pons/`` is written.

It is deliberately **not** called ``common.py``: ``experiments/d11`` is on the
import path and already owns that name.

**Nothing in this module, or in any D12 script, opens a socket.** A test parses
each of them for ``flytrade.pons.rpc`` and for network verbs.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
D11 = ROOT / "experiments" / "d11"
for _p in (str(HERE), str(D11), str(ROOT), str(ROOT / "upstream")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import common as C                                       # noqa: E402  (D11's)
from flytrade.pons import loop as LOOP                   # noqa: E402
from flytrade.pons.collector import Finality             # noqa: E402

RUN_ID = "d12-001"
RUNS = HERE / "runs"
CONFIG_RUN = HERE / "d12_001.json"
#: the D11 environment, read and never written
CONFIG_V2 = C.CONFIG_V2
DATASET = C.DATASET
D11_RUN = C.RUNS / C.RUN_ID
D11_GRID = D11_RUN / "grid"

#: the reused d11-001 artifacts, by name. Their sha256 is recorded in the
#: d12-001 summary and at least 200 of the reference scores are recomputed.
REUSED = ("rows.jsonl", "labels.jsonl", "scores_reference.jsonl")

#: where the plasticity operator's gains live and what bounds them
#: (:class:`flytrade.mushroom.MushroomBody`): ``floor`` up to ``1.0``.
GAIN_CEILING = 1.0
GAIN_EPS = 1e-9


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def configs() -> tuple[dict, dict]:
    """``(the D11 environment, the d12-001 registration)``."""
    return json.loads(CONFIG_V2.read_text()), json.loads(CONFIG_RUN.read_text())


def verify_dataset() -> Path:
    """The store on disk is the store its MANIFEST describes, or nothing runs."""
    directory = C.DATASET
    man = C.manifest()
    for name, entry in man["files"].items():
        path = directory / name
        if not path.exists():
            raise SystemExit(f"{path} is absent; the run is refused")
        got = sha256_file(path)
        if got != entry["sha256"]:
            raise SystemExit(
                f"{name}: sha256 {got[:16]} != the recorded "
                f"{entry['sha256'][:16]}. The file on disk is not the file "
                f"collected; the run is refused.")
    if not (directory / "initial_states.json").exists():
        raise SystemExit("initial_states.json is mandatory")
    return directory


def split() -> dict:
    """The registered split, recomputed, and asserted equal to d11-001's.

    D12 must run on the *same* cutoff as d11-001 or the grids it reuses do not
    belong to it. This recomputes the split from the store's own MANIFEST and
    refuses to continue if it differs from the one `d11-001`'s summary
    recorded.
    """
    sp = C.split(C.manifest()["window"])
    recorded = json.loads((D11_RUN / "summary.json").read_text())["split"]
    for key in ("t0", "t1", "T", "learning_first_tick", "learning_last_tick",
                "frozen_first_tick", "frozen_last_tick", "learning_ticks",
                "frozen_ticks", "cadence_s", "latency_s", "horizon_s"):
        if sp[key] != recorded[key]:
            raise SystemExit(
                f"the recomputed split disagrees with d11-001 on {key}: "
                f"{sp[key]} != {recorded[key]}; the run is refused rather than "
                f"comparing two different windows")
    return sp


def finality() -> Finality:
    man = C.manifest()
    return Finality(
        median_interval_s=float(man["window"]["median_block_interval_s"]),
        confirm_depth=int(man["window"]["confirm_depth_blocks"]),
        safe_tag_supported=True, sample=3)


class PartitionReplayDriver(LOOP.ReplayDriver):
    """A recorded window read over one partition's ticks, on one fixed grid.

    The same driver ``experiments/d11/run.py`` defines, carried here so that no
    D12 script imports the module whose ``--mode LIVE_PAPER`` path can open a
    socket. The tick grid is anchored at ``t0``, so the school partition, the
    two frozen branches and the evaluation grid all speak about the same
    instants.
    """

    def __init__(self, directory, *, finality, first_tick: int, last_tick: int,
                 anchor_ts: int):
        super().__init__(directory, finality=finality)
        self.anchor_ts = int(anchor_ts)
        self.first_tick = int(first_tick)
        self.last_tick = int(last_tick)
        if (self.first_tick - self.anchor_ts) % LOOP.CADENCE_S:
            raise SystemExit("the first tick is not on the anchored grid")

    def ticks(self, cadence: int = LOOP.CADENCE_S):
        cutoff = self.first_tick
        while cutoff <= self.last_tick:
            yield int(cutoff)
            cutoff += int(cadence)

    def as_dict(self) -> dict:
        return {**super().as_dict(), "anchor_ts": self.anchor_ts,
                "first_tick": self.first_tick, "last_tick": self.last_tick,
                "partition_ticks": (self.last_tick - self.first_tick)
                // LOOP.CADENCE_S + 1}


def safe_label(tape, cutoff: int, clock, *, gas: dict) -> dict:
    """``common.label_row``, with a ``QuoteError`` reported as ``UNRESOLVED``.

    ``d11_001.json``'s label definition already says *"Unresolved (route
    transition, coverage) or QuoteError (exhausted curve) -> label UNRESOLVED,
    excluded from AUC and counted"*, and ``experiments/d11/evaluate.py`` never
    met one on the FROZEN grid, so ``label_row`` lets it propagate. A LEARNING
    tick does meet one — a curve whose ``sellable_tokens`` reach zero raises
    ``CURVE_REQUIRES_V4`` — so the declared behaviour is applied here rather
    than by editing D11, which is read-only in this wave. **The arithmetic of a
    settled label is untouched**: this only names the failure.
    """
    from flytrade.pons.curve import QuoteError              # noqa: PLC0415
    try:
        return C.label_row(tape, int(cutoff), clock, gas=gas)
    except QuoteError as exc:
        return {"cutoff_ts": int(cutoff), "token": tape.token,
                "curve": tape.curve, "settled": False, "status": C.UNRESOLVED,
                "reason": f"QUOTE_ERROR:{exc.args[0] if exc.args else 'QUOTE'}",
                "net": None, "positive": None}


def weight_diagnostics(mb, *, digest: str | None = None) -> dict:
    """Mean, norm and the saturated fraction of the plastic KC->MBON gains.

    The operator only **depresses** and the clean reference starts with every
    gain exactly at ``1.0``, so *at the ceiling* means *never depressed by any
    lesson*. Registered in ``PLAN.md`` §8 before the run, reported split as
    well as summed, and the pre-registered condition reads the sum.
    """
    g = np.asarray(mb.gain, dtype=np.float64)
    n = int(g.size)
    at_floor = int((g <= float(mb.floor) + GAIN_EPS).sum())
    at_ceiling = int((g >= GAIN_CEILING - GAIN_EPS).sum())
    return {
        "synapses": n,
        "mean": float(g.mean()) if n else None,
        "l2_norm": float(np.linalg.norm(g)) if n else None,
        "min": float(g.min()) if n else None,
        "max": float(g.max()) if n else None,
        "floor": float(mb.floor), "ceiling": GAIN_CEILING,
        "at_floor": at_floor, "at_ceiling": at_ceiling,
        "at_floor_fraction": (at_floor / n) if n else None,
        "at_ceiling_fraction": (at_ceiling / n) if n else None,
        "saturated_fraction": ((at_floor + at_ceiling) / n) if n else None,
        "digest": digest,
        "note": ("the operator only depresses and the clean reference starts "
                 "with every gain at 1.0, so a synapse at the ceiling is one "
                 "no lesson has depressed"),
    }


def atomic_write_json(path, payload) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1, default=str) + "\n")
    tmp.replace(path)


__all__ = ["HERE", "ROOT", "D11", "RUN_ID", "RUNS", "CONFIG_RUN", "CONFIG_V2",
           "DATASET", "D11_RUN", "D11_GRID", "REUSED", "GAIN_CEILING",
           "GAIN_EPS", "C", "LOOP", "sha256_file", "configs", "verify_dataset",
           "split", "finality", "PartitionReplayDriver", "safe_label",
           "weight_diagnostics",
           "atomic_write_json"]
