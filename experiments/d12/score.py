#!/usr/bin/env python
"""The SCHOOL scoring pass on the reused FROZEN grid, and the reuse check.

    .venv/bin/python experiments/d12/score.py --reuse
    .venv/bin/python experiments/d12/score.py --verify-reference
    .venv/bin/python experiments/d12/score.py --score

D12 reuses `d11-001`'s FROZEN grid rather than rebuilding it: the same cutoff
`T`, the same partition, the same `admission_v2` and the same store give the
same rows, the same evaluator labels and — since the ``comparison_v1`` seeds
are keyed to ``(observation_id, stable_id, replicate)`` and **not** to the
learned state — the same REFERENCE valences. Reuse is *checked*, not assumed:

* ``--reuse`` copies ``rows.jsonl``, ``labels.jsonl`` and
  ``scores_reference.jsonl`` into this run's grid directory and records the
  sha256 of the source and of the copy;
* ``--verify-reference`` **re-scores at least 200 rows** under the clean
  reference and compares them with the reused valences at 1e-9 Hz. Identical
  seeds and identical weights must give identical numbers; a single
  disagreement stops the wave;
* ``--score`` scores every row under the SCHOOL checkpoint, read-only, with the
  learned-state digest verified before and after.

The scoring itself is ``experiments/d11/grid.py``'s own ``score_branch``,
imported and not reimplemented, so the two branches go through one function.
**Nothing here opens a socket.**
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import d12lib as L                                        # noqa: E402
import grid as G                                          # noqa: E402  (D11's)

C = L.C
GRID = L.RUNS / L.RUN_ID / "grid"

#: Fable addendum 1: "a recomputation check on at least 200 rows"
VERIFY_ROWS = 200
#: the tolerance the addendum names
TOLERANCE_HZ = 1e-9


def read_jsonl(path: Path):
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def reuse(out: Path, *, log=print) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    record = {}
    for name in L.REUSED:
        src = L.D11_GRID / name
        dst = out / name
        shutil.copy2(src, dst)
        record[name] = {"source": str(src), "source_sha256": L.sha256_file(src),
                        "copy_sha256": L.sha256_file(dst),
                        "lines": sum(1 for _ in read_jsonl(dst))}
        if record[name]["source_sha256"] != record[name]["copy_sha256"]:
            raise SystemExit(f"{name} did not copy intact")
        log(f"reused {name}: {record[name]['lines']:,} lines, "
            f"{record[name]['source_sha256'][:12]}…")
    payload = {"version": "d12-001-reuse-1", "files": record,
               "rule": ("the same store, the same cutoff T, the same "
                        "admission_v2 and comparison_v1 seeds that are not "
                        "keyed to the learned state; reuse is checked by "
                        "--verify-reference, never assumed")}
    L.atomic_write_json(out / "reuse.json", payload)
    return payload


def verify_reference(out: Path, *, rows: int = VERIFY_ROWS, log=print) -> dict:
    """Re-score a spread of rows under the clean reference and compare."""
    all_rows = list(read_jsonl(out / "rows.jsonl"))
    if len(all_rows) < rows:
        rows = len(all_rows)
    picks = sorted(set(np.linspace(0, len(all_rows) - 1, rows).astype(int)
                       .tolist()))
    subset = [all_rows[i] for i in picks]
    tmp = out / "verify"
    tmp.mkdir(parents=True, exist_ok=True)
    with open(tmp / "rows.jsonl", "w", encoding="utf-8") as fh:
        for row in subset:
            fh.write(json.dumps(row) + "\n")
    log(f"re-scoring {len(subset):,} of {len(all_rows):,} rows under the clean "
        f"reference")
    summary = G.score_branch("reference", Path("/dev/null"), tmp, log=log)
    got = {(r["cutoff_ts"], r["stable_id"]): r
           for r in read_jsonl(tmp / "scores_reference.jsonl")}
    want = {(r["cutoff_ts"], r["stable_id"]): r
            for r in read_jsonl(out / "scores_reference.jsonl")}
    worst = 0.0
    compared = mismatched = 0
    examples = []
    for key, row in got.items():
        ref = want.get(key)
        if ref is None:
            mismatched += 1
            examples.append({"key": list(key), "why": "absent from the reused file"})
            continue
        if row.get("status") != ref.get("status"):
            mismatched += 1
            examples.append({"key": list(key), "why": "status",
                             "recomputed": row.get("status"),
                             "reused": ref.get("status")})
            continue
        if row.get("valence_hz") is None or ref.get("valence_hz") is None:
            compared += 1
            continue
        d = abs(float(row["valence_hz"]) - float(ref["valence_hz"]))
        worst = max(worst, d)
        compared += 1
        if d > TOLERANCE_HZ:
            mismatched += 1
            examples.append({"key": list(key), "why": "valence",
                             "recomputed": row["valence_hz"],
                             "reused": ref["valence_hz"], "difference": d})
    payload = {
        "version": "d12-001-reference-verification-1",
        "rows_recomputed": len(subset), "rows_in_the_grid": len(all_rows),
        "compared": compared, "mismatched": mismatched,
        "max_abs_difference_hz": worst, "tolerance_hz": TOLERANCE_HZ,
        "start_digest": summary["start_digest"],
        "digest_unchanged": summary["digest_unchanged"],
        "examples": examples[:10],
        "rule": ("identical seeds and identical weights must give identical "
                 "valences; a single disagreement stops the wave"),
        "verdict": "REUSE_VERIFIED" if not mismatched else "REUSE_REFUSED",
    }
    L.atomic_write_json(out / "reference_verification.json", payload)
    log(f"verification: {compared:,} compared, {mismatched} mismatched, worst "
        f"|difference| {worst:.3e} Hz -> {payload['verdict']}")
    if mismatched:
        raise SystemExit("the reused REFERENCE scores do not reproduce; the "
                         "wave stops rather than comparing two different "
                         "objects")
    return payload


def score_school(out: Path, checkpoint: Path, *, log=print) -> dict:
    if not checkpoint.exists():
        raise SystemExit(f"{checkpoint} is absent: the SCHOOL scoring pass "
                         f"starts from the school's final checkpoint")
    return G.score_branch("school", checkpoint, out, log=log)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(GRID))
    parser.add_argument("--reuse", action="store_true")
    parser.add_argument("--verify-reference", action="store_true")
    parser.add_argument("--verify-rows", type=int, default=VERIFY_ROWS)
    parser.add_argument("--score", action="store_true")
    parser.add_argument("--checkpoint", default=None)
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    logf = (out / "score.log").open("a")

    def log(*a):
        print(*a, flush=True)
        print(time.strftime("%H:%M:%S", time.gmtime()), *a, file=logf,
              flush=True)

    did = False
    if args.reuse:
        reuse(out, log=log); did = True
    if args.verify_reference:
        verify_reference(out, rows=args.verify_rows, log=log); did = True
    if args.score:
        checkpoint = Path(args.checkpoint or
                          (L.RUNS / L.RUN_ID / "school" / "brain.npz"))
        score_school(out, checkpoint, log=log); did = True
    logf.close()
    if not did:
        raise SystemExit("nothing to do: pass --reuse, --verify-reference or "
                         "--score")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
