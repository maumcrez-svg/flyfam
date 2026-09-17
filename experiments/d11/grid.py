#!/usr/bin/env python
"""The FROZEN evaluation grid: one market-only pass, then two read-only brains.

    .venv/bin/python experiments/d11/grid.py --rows
    .venv/bin/python experiments/d11/grid.py --score --branch reference
    .venv/bin/python experiments/d11/grid.py --score --branch trained

D11-001 Fable addendum 7. **The grid is not the loop.** Presentation inside the
loop depends on run state — while a position is held only the held token is
presented, and the round-robin rotation advances with evaluated rounds — so two
frozen loop branches cannot share rows. The grid is therefore built from the
store alone:

* at every FROZEN tick the tapes are reconstructed offline by the same tracker
  ``experiments/d11/retrospective.py`` verified against D10's recorded rounds;
* ``admission_v2`` is applied at that cutoff and **all** eligible candidates are
  taken — no cap of six, no rotation, no hold mode, a superset of anything
  either loop branch could have presented;
* each row is then scored by **both** frozen brains with the standard readout:
  k = 8 replicates under ``comparison_v1``, seeded from ``(observation_id,
  stable_id, replicate index)`` and independent of the checkpoint digest, which
  is what makes the two branches draw the same Poisson stream for the same row.

Rows are keyed ``(cutoff_ts, stable_id)`` and are built **once**, so the two
branches are identical by construction rather than by comparison. Both brains
are loaded read-only and their digests are verified before and after the pass.
**No execution, no bankroll, no reinforcement and no checkpoint write happens
here, and nothing in this file opens a socket.**
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import common as C                                        # noqa: E402
from common import ROOT                                   # noqa: E402
from flytrade import decoder as D                         # noqa: E402
from flytrade import market as MK                         # noqa: E402
from flytrade import readout as RO                        # noqa: E402
from flytrade import state as S                           # noqa: E402
from flytrade.pons.admission_v2 import (COLLECTOR_LAG,     # noqa: E402
                                        DATA_LAG,
                                        NO_ELIGIBLE_CANDIDATES)
from flytrade.pons.context_v2 import context_v2           # noqa: E402
from retrospective import Tracker                          # noqa: E402

GRID = C.RUNS / C.RUN_ID / "grid"


def tracker() -> Tracker:
    return Tracker(C.DATASET, live=False)


# ------------------------------------------------------------------- rows
def build_rows(out: Path, *, log=print) -> dict:
    """Every v2-eligible (cutoff, token) of the FROZEN partition, market only."""
    cfg_v2, cfg_run = C.configs()
    man = C.manifest()
    window = man["window"]
    sp = C.split(window)
    admission_last_block = int(window["admission_last_block"])
    policy = C.admission_v2(cfg_v2, require_coverage=True,
                            max_candidates=10 ** 9)     # no cap: addendum 7
    features = tuple(cfg_v2["features"]["order"])
    scales = cfg_v2["features"]["scales"]

    t_start = time.time()
    track = tracker()
    log(f"tracker: {len(track.tapes):,} tapes, "
        f"{track.unreconstructible} unreconstructible, coverage_end "
        f"{track.coverage_end_ts}, {time.time() - t_start:.0f}s")

    # stable ids, assigned once in launch order: deterministic, independent of
    # the branch, of the tick and of the address spelling's sort position.
    order = sorted(track.tapes.values(),
                   key=lambda t: (t.launch_block, t.launched_at, t.curve))
    stable = {t.token: i for i, t in enumerate(order)}

    # (a) the first LEARNING tick with at least one v2-eligible candidate,
    #     which is where the geometric ceiling starts.
    first_eligible = None
    scanned = 0
    for cutoff in range(sp["t0"], sp["T"] + 1, C.CADENCE):
        scanned += 1
        tapes = track.tracked_at(cutoff, admission_last_block=admission_last_block)
        for tape in tapes:
            restore = Tracker.causal_completion(tape, cutoff)
            ctx = context_v2(tape, cutoff)
            cand = policy.consider(tape, ctx, stable_id=stable[tape.token],
                                   cutoff=cutoff)
            restore()
            if cand.admitted:
                first_eligible = cutoff
                break
        if first_eligible is not None:
            break
    log(f"first eligible LEARNING tick {first_eligible} after {scanned} ticks")
    ceiling = C.geometric_ceiling(first_eligible, sp["T"])

    # (b) the FROZEN grid itself
    out.mkdir(parents=True, exist_ok=True)
    rows_path = out / "rows.jsonl"
    reasons: Counter = Counter()
    per_tick = []
    empty = Counter()
    written = 0
    tokens = set()
    t_grid = time.time()
    with open(rows_path, "w", encoding="utf-8") as fh:
        for tick, cutoff in enumerate(
                range(sp["frozen_first_tick"], sp["frozen_last_tick"] + 1,
                      C.CADENCE), start=1):
            tapes = track.tracked_at(cutoff,
                                     admission_last_block=admission_last_block)
            eligible = 0
            considered = []
            for tape in tapes:
                restore = Tracker.causal_completion(tape, cutoff)
                ctx = context_v2(tape, cutoff)
                cand = policy.consider(tape, ctx, stable_id=stable[tape.token],
                                       cutoff=cutoff)
                restore()
                considered.append(cand)
                if not cand.admitted:
                    for reason in cand.reasons:
                        reasons[reason] += 1
                    continue
                reasons["ADMITTED"] += 1
                eligible += 1
                tokens.add(tape.token)
                normalised = ctx.normalized(scales, features)
                fh.write(json.dumps({
                    "cutoff_ts": int(cutoff), "tick": int(tick),
                    "stable_id": int(stable[tape.token]),
                    "token": tape.token, "curve": tape.curve,
                    "launch_block": int(tape.launch_block),
                    "launched_at": int(tape.launched_at),
                    "status": ctx.status.value,
                    "age_s": int(ctx.age_s),
                    "marginal_price": float(ctx.marginal_price),
                    "trades": int(ctx.trades),
                    "raw": {f: float(ctx.raw.get(f, 0.0)) for f in features},
                    "normalized": [float(v) for v in normalised],
                    "saturated_channels": int(C.saturated(normalised).sum()),
                }) + "\n")
                written += 1
            per_tick.append(eligible)
            if eligible == 0:
                rows = [c for c in considered]
                empty[DATA_LAG if rows and all(COLLECTOR_LAG in (c.reasons or ())
                                               for c in rows)
                      else NO_ELIGIBLE_CANDIDATES] += 1
            if tick % 50 == 0:
                log(f"  tick {tick}/{sp['frozen_ticks']} cutoff {cutoff} "
                    f"rows {written:,} ({time.time() - t_grid:.0f}s)")

    per_tick_arr = np.array(per_tick or [0])
    summary = {
        "version": "d11-001-grid-rows-1",
        "dataset": man["dataset"],
        "window": window,
        "split": sp,
        "geometric_ceiling": ceiling,
        "stable_id_rule": ("assigned once over the reconstructible native "
                           "launches in launch order (launch_block, "
                           "launched_at, curve); never from the address "
                           "spelling's sort position"),
        "admission": policy.as_dict(),
        "tapes": len(track.tapes),
        "unreconstructible_launches": track.unreconstructible,
        "rows": written,
        "tokens_with_at_least_one_row": len(tokens),
        "ticks": len(per_tick),
        "zero_eligible_ticks": int((per_tick_arr == 0).sum()),
        "empty_round_status": dict(empty),
        "eligible_per_tick": {
            "min": int(per_tick_arr.min()), "max": int(per_tick_arr.max()),
            "median": float(np.median(per_tick_arr)),
            "mean": float(per_tick_arr.mean())},
        "admission_reasons": dict(sorted(reasons.items())),
        "rows_path": str(rows_path),
        "elapsed_s": round(time.time() - t_start, 1),
    }
    (out / "rows_summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    log(f"rows: {written:,} over {len(per_tick)} ticks in "
        f"{summary['elapsed_s']:.0f}s")
    return summary


# ------------------------------------------------------------------ score
def read_rows(path: Path):
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def observation_of(row: dict, features, scales) -> MK.MarketObservation:
    """The same object the loop's ``PonsContext.observation`` builds.

    Rebuilt from the row rather than recomputed from the tape, so the two
    branches are given **the same bytes** and ``observation_id`` — a content
    hash over the normalised vector — is identical by construction.
    """
    raw = np.array([float(row["raw"][f]) for f in features], dtype=np.float64)
    normalized = np.array(row["normalized"], dtype=np.float64)
    zeros = np.zeros(len(features), dtype=np.float64)
    return MK.MarketObservation(
        symbol=row["token"], stable_id=int(row["stable_id"]),
        bar_index=int(row["tick"]), cutoff_ts=int(row["cutoff_ts"]),
        status=MK.ObservationStatus(row["status"]),
        raw=raw, normalized=normalized, z=zeros.copy(),
        close=float(row["marginal_price"]), detail="",
        feature_names=tuple(features))


def score_branch(branch: str, checkpoint: Path, out: Path, *, log=print) -> dict:
    """Score every grid row under one frozen brain. Read-only, digest-checked."""
    cfg_v2, cfg_run = C.configs()
    features = tuple(cfg_v2["features"]["order"])
    scales = cfg_v2["features"]["scales"]
    fb, mb, ann, encoder, pops, run, sha, clean = C.build_brain(cfg_v2)

    if branch != "reference":
        ck = S.load_checkpoint(checkpoint, graph_sha256=sha, expect_pos=mb.pos)
        mb.gain[:] = ck["gain"]
        mb.apply()
    start_digest = S.learned_state_digest(mb.gain, mb.pos, sha)
    log(f"[{branch}] start digest {start_digest[:12]}")

    policy = RO.policy_comparison()
    decoder = policy.decoder
    rows_path = out / "rows.jsonl"
    scores_path = out / f"scores_{branch}.jsonl"
    statuses: Counter = Counter()
    actions: Counter = Counter()
    n = 0
    t0 = time.time()
    with open(scores_path, "w", encoding="utf-8") as fh:
        batch: list[dict] = []
        current = None
        for row in read_rows(rows_path):
            if current is not None and row["tick"] != current:
                n += flush(batch, current, fh, run, policy, decoder, features,
                           scales, statuses, actions, start_digest, branch)
                batch = []
                if n and (current % 50 == 0):
                    log(f"  [{branch}] tick {current} rows {n:,} "
                        f"({time.time() - t0:.0f}s)")
            current = row["tick"]
            batch.append(row)
        if batch:
            n += flush(batch, current, fh, run, policy, decoder, features,
                       scales, statuses, actions, start_digest, branch)

    end_digest = S.learned_state_digest(mb.gain, mb.pos, sha)
    summary = {
        "version": "d11-001-grid-scores-1",
        "branch": branch,
        "checkpoint": str(checkpoint) if branch != "reference" else None,
        "start_digest": start_digest, "end_digest": end_digest,
        "digest_unchanged": start_digest == end_digest,
        "clean_reference_digest": clean,
        "rows": n,
        "readout": policy.as_dict(),
        "decoder": decoder.as_dict(),
        "status": dict(statuses), "action": dict(actions),
        "elapsed_s": round(time.time() - t0, 1),
        "scores_path": str(scores_path),
    }
    (out / f"scores_{branch}_summary.json").write_text(
        json.dumps(summary, indent=1) + "\n")
    if not summary["digest_unchanged"]:
        raise SystemExit(f"[{branch}] the learned state moved during a frozen "
                         f"scoring pass: {start_digest[:12]} -> "
                         f"{end_digest[:12]}")
    log(f"[{branch}] {n:,} rows in {summary['elapsed_s']:.0f}s, digest "
        f"{start_digest[:12]} unchanged")
    return summary


def flush(batch, tick, fh, run, policy, decoder, features, scales,
          statuses, actions, digest, branch) -> int:
    """One tick's rows through the standard k = 8 readout, in one round."""
    if not batch:
        return 0
    observations = [observation_of(r, features, scales) for r in batch]
    try:
        rnd = run.evaluate_round(observations, round_index=int(tick),
                                 readout=policy, score=policy.score)
    except RO.TechnicalFailure as exc:
        for row in batch:
            statuses["ROUND_ABORTED"] += 1
            fh.write(json.dumps({
                "cutoff_ts": row["cutoff_ts"], "stable_id": row["stable_id"],
                "tick": row["tick"], "branch": branch,
                "status": "ROUND_ABORTED", "detail": str(exc),
                "valence_hz": None, "action": None,
                "checkpoint_digest": digest}) + "\n")
        return len(batch)
    by_id = {c.stable_id: c for c in rnd.candidates}
    for row in batch:
        cand = by_id.get(int(row["stable_id"]))
        payload = {"cutoff_ts": row["cutoff_ts"], "stable_id": row["stable_id"],
                   "tick": row["tick"], "token": row["token"],
                   "branch": branch, "checkpoint_digest": digest}
        if cand is None or cand.presentation is None:
            payload.update({"status": "NO_PRESENTATION", "valence_hz": None,
                            "action": None})
            statuses["NO_PRESENTATION"] += 1
        else:
            decision = decoder.decode(cand.presentation)
            payload.update({
                "status": decision.status.value,
                "action": decision.action.value,
                "valence_hz": float(decision.valence_hz),
                "raw_valence_hz": float(decision.raw_valence_hz)
                if hasattr(decision, "raw_valence_hz") else None,
                "approach_hz": float(cand.presentation.mean(D.APPROACH)),
                "avoid_hz": float(cand.presentation.mean(D.AVOID)),
                "silent_replicates": int(cand.batch.silent_replicates)
                if cand.batch is not None else None,
                "invalid_replicates": int(cand.batch.invalid_replicates)
                if cand.batch is not None else None,
                "observation_id": RO.observation_id(cand.observation),
                "seed": int(cand.seed),
            })
            statuses[decision.status.value] += 1
            actions[decision.action.value] += 1
        fh.write(json.dumps(payload) + "\n")
    return len(batch)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(GRID))
    parser.add_argument("--rows", action="store_true",
                        help="build the market-only grid rows")
    parser.add_argument("--score", action="store_true",
                        help="score the rows under one frozen brain")
    parser.add_argument("--branch", default=None,
                        choices=["trained", "reference"])
    parser.add_argument("--checkpoint", default=None)
    args = parser.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    logf = (out / f"grid_{'rows' if args.rows else args.branch}.log").open("a")

    def log(*a):
        print(*a, flush=True)
        print(time.strftime("%H:%M:%S", time.gmtime()), *a, file=logf, flush=True)

    if args.rows:
        build_rows(out, log=log)
        return 0
    if args.score:
        if args.branch is None:
            raise SystemExit("--score needs --branch trained|reference")
        checkpoint = Path(args.checkpoint) if args.checkpoint else (
            C.RUNS / C.RUN_ID / "learning" / "brain.npz")
        score_branch(args.branch, checkpoint, out, log=log)
        return 0
    raise SystemExit("nothing to do: pass --rows or --score")


if __name__ == "__main__":
    raise SystemExit(main())
