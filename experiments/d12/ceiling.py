#!/usr/bin/env python
"""Step (iii), numbers only: the lesson ceiling and the two grids' balances.

    .venv/bin/python experiments/d12/ceiling.py

**No brain runs here.** This is the market-only tracker of
``experiments/d11/retrospective.py`` — the one verified against D10's recorded
rounds — applied at every LEARNING tick with ``admission_v2``, plus the
evaluator-only label of ``experiments/d11/common.py``. It creates no trade,
alters no bankroll, produces no reinforcement and touches neither ledger nor
checkpoint, and it opens no socket.

What it computes, and nothing else:

* **the lesson ceiling** as PLAN.md §9 registers it — eligible candidate-ticks
  in LEARNING whose ``cutoff + 902 <= T``, in cohorts of ``n >= 3``;
* the **cohort-size distribution**, before and after the ``UNRESOLVED`` drop;
* the set of tokens that were eligible at least once in LEARNING — the tokens
  that would become lessons — so the **primary** FROZEN grid can be made
  token-disjoint from them;
* the **primary and secondary FROZEN row counts and class balances**, read off
  the reused ``d11-001`` rows and labels.

The pre-registered hard stop is applied here and stated: a ceiling under 2,000,
a primary grid under 100 labelled rows, or a class under 20 ends the wave with
these numbers and **no neural run**.
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

import d12lib as L                                        # noqa: E402
from common import CADENCE, SETTLE_S                      # noqa: E402  (D11's)
from flytrade.pons.context_v2 import context_v2           # noqa: E402
from retrospective import Tracker                         # noqa: E402

C = L.C
OUT = L.HERE / "ceiling.json"

#: PLAN.md §3
N_MIN = 3


def read_jsonl(path: Path):
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def learning_cohorts(*, log=print) -> dict:
    """Every LEARNING tick's eligible set, its labels and its cohort size."""
    cfg_v2, cfg_run = L.configs()
    man = C.manifest()
    window = man["window"]
    sp = L.split()
    admission_last_block = int(window["admission_last_block"])
    policy = C.admission_v2(cfg_v2, require_coverage=True,
                            max_candidates=10 ** 9)      # school: no cap
    gas = C.gas_constants(cfg_run)
    clock = C.block_clock()

    t_start = time.time()
    track = Tracker(C.DATASET, live=False)
    log(f"tracker: {len(track.tapes):,} tapes, "
        f"{track.unreconstructible} unreconstructible "
        f"({time.time() - t_start:.0f}s)")
    order = sorted(track.tapes.values(),
                   key=lambda t: (t.launch_block, t.launched_at, t.curve))
    stable = {t.token: i for i, t in enumerate(order)}

    T = int(sp["T"])
    ticks: list[dict] = []
    lesson_tokens: set[str] = set()
    eligible_tokens_learning: set[str] = set()
    unresolved_reasons: Counter = Counter()
    first_eligible = None
    for tick, cutoff in enumerate(
            range(sp["learning_first_tick"], sp["learning_last_tick"] + 1,
                  CADENCE), start=1):
        tapes = track.tracked_at(cutoff,
                                 admission_last_block=admission_last_block)
        eligible = []
        for tape in tapes:
            restore = Tracker.causal_completion(tape, cutoff)
            ctx = context_v2(tape, cutoff)
            cand = policy.consider(tape, ctx, stable_id=stable[tape.token],
                                   cutoff=cutoff)
            restore()
            if cand.admitted:
                eligible.append(tape)
        if eligible and first_eligible is None:
            first_eligible = int(cutoff)
        for tape in eligible:
            eligible_tokens_learning.add(tape.token)
        beyond = (int(cutoff) + SETTLE_S) > T
        settled = 0
        if eligible and not beyond:
            for tape in eligible:
                # the label is the *outcome*, so it reads the tape as
                # `experiments/d11/evaluate.py --labels` read it: unmasked, and
                # therefore able to see a completion inside the 15 minutes.
                # The causal mask above belongs to admission, which is a
                # decision, and not to the evaluator.
                label = L.safe_label(tape, int(cutoff), clock, gas=gas)
                if label["settled"]:
                    settled += 1
                else:
                    unresolved_reasons[label["reason"] or "UNRESOLVED"] += 1
        row = {"tick": tick, "cutoff_ts": int(cutoff),
               "eligible": len(eligible), "beyond_boundary": bool(beyond),
               "settled": int(settled)}
        ticks.append(row)
        if not beyond and len(eligible) >= N_MIN:
            for tape in eligible:
                lesson_tokens.add(tape.token)
        if tick % 100 == 0:
            log(f"  tick {tick}/{sp['learning_ticks']} cutoff {cutoff} "
                f"({time.time() - t_start:.0f}s)")

    inside = [r for r in ticks if not r["beyond_boundary"]]
    #: the registered ceiling: eligible candidate-ticks inside the boundary in
    #: cohorts of n >= 3
    ceiling = sum(r["eligible"] for r in inside if r["eligible"] >= N_MIN)
    #: the same count after the UNRESOLVED drop — reported beside it, never
    #: instead of it
    after_drop = sum(r["settled"] for r in inside if r["settled"] >= N_MIN)

    sizes = np.array([r["eligible"] for r in inside] or [0])
    sizes_settled = np.array([r["settled"] for r in inside] or [0])

    def dist(arr) -> dict:
        return {"ticks": int(arr.size), "min": int(arr.min()),
                "p25": float(np.percentile(arr, 25)),
                "median": float(np.median(arr)),
                "p75": float(np.percentile(arr, 75)),
                "p90": float(np.percentile(arr, 90)),
                "max": int(arr.max()), "mean": float(arr.mean()),
                "sum": int(arr.sum()),
                "ticks_below_n_min": int((arr < N_MIN).sum()),
                "ticks_at_zero": int((arr == 0).sum()),
                "histogram": {str(k): int(v) for k, v in
                              sorted(Counter(arr.tolist()).items())}}

    summary = {
        "tapes": len(track.tapes),
        "unreconstructible_launches": track.unreconstructible,
        "learning_ticks": len(ticks),
        "ticks_inside_the_boundary": len(inside),
        "ticks_discarded_at_the_boundary": len(ticks) - len(inside),
        "first_eligible_learning_tick": first_eligible,
        "n_min": N_MIN,
        "lesson_ceiling": int(ceiling),
        "lesson_ceiling_rule": (
            "eligible candidate-ticks in LEARNING whose cutoff + 902 <= T, in "
            "cohorts of n >= 3, from the market-only tracker; no brain"),
        "lesson_ceiling_after_unresolved_drop": int(after_drop),
        "eligible_candidate_ticks_inside_the_boundary": int(sizes.sum()),
        "eligible_candidate_ticks_at_the_boundary": int(
            sum(r["eligible"] for r in ticks if r["beyond_boundary"])),
        "cohort_size_distribution": dist(sizes),
        "cohort_size_distribution_after_unresolved_drop": dist(sizes_settled),
        "unresolved_reasons": dict(sorted(unresolved_reasons.items())),
        "tokens_eligible_at_least_once_in_learning": len(
            eligible_tokens_learning),
        "tokens_that_become_lessons": len(lesson_tokens),
        "per_tick": ticks,
    }
    return summary, lesson_tokens


def grid_balances(lesson_tokens: set[str]) -> dict:
    """The primary and secondary FROZEN row counts and class balances."""
    rows = {(r["cutoff_ts"], r["stable_id"]): r
            for r in read_jsonl(L.D11_GRID / "rows.jsonl")}
    labels = {(r["cutoff_ts"], r["stable_id"]): r
              for r in read_jsonl(L.D11_GRID / "labels.jsonl")}
    out = {}
    for name in ("secondary", "primary"):
        keys = [k for k, r in rows.items()
                if name == "secondary" or r["token"] not in lesson_tokens]
        settled = [labels[k] for k in keys
                   if labels.get(k) and labels[k].get("settled")]
        positive = sum(1 for lab in settled if lab["positive"])
        out[name] = {
            "rows": len(keys),
            "tokens": len({rows[k]["token"] for k in keys}),
            "settled_labels": len(settled),
            "unresolved_labels": len(keys) - len(settled),
            "positive": positive,
            "negative": len(settled) - positive,
            "positive_share": (positive / len(settled)) if settled else None,
        }
    out["primary"]["definition"] = (
        "FROZEN rows on tokens that were never eligible at a LEARNING tick "
        "inside the boundary — the tokens no lesson could ever have used")
    out["secondary"]["definition"] = "all FROZEN rows"
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)

    def log(*a):
        print(*a, flush=True)

    t0 = time.time()
    cohorts, lesson_tokens = learning_cohorts(log=log)
    man = C.manifest()
    sp = L.split()
    (L.HERE / "lesson_tokens.json").write_text(json.dumps(
        {"rule": ("every token eligible under admission_v2 at a LEARNING tick "
                  "whose cutoff + 902 <= T, in a cohort of n >= 3 — the tokens "
                  "that can become lessons; the primary FROZEN grid is "
                  "disjoint from this set by address"),
         "count": len(lesson_tokens),
         "tokens": sorted(lesson_tokens)}, indent=1) + "\n")
    balances = grid_balances(lesson_tokens)

    stops = []
    if cohorts["lesson_ceiling"] < 2000:
        stops.append(f"the lesson ceiling is {cohorts['lesson_ceiling']:,} "
                     f"(< 2,000)")
    if balances["primary"]["settled_labels"] < 100:
        stops.append(f"the primary grid carries "
                     f"{balances['primary']['settled_labels']:,} labelled "
                     f"rows (< 100)")
    smaller = min(balances["primary"]["positive"],
                  balances["primary"]["negative"])
    if smaller < 20:
        stops.append(f"a primary-grid class has {smaller:,} examples (< 20)")

    payload = {
        "version": "d12-001-ceiling-1",
        "run_id": L.RUN_ID,
        "dataset": man["dataset"],
        "split": sp,
        "no_brain_ran": True,
        "no_socket_was_opened": True,
        "creates_no_trade": True,
        "produces_no_reinforcement": True,
        "learning": cohorts,
        "frozen_grids": balances,
        "reused_d11_001_files": {
            name: L.sha256_file(L.D11_GRID / name) for name in L.REUSED},
        "preregistered_hard_stop": {
            "conditions": [
                "a lesson ceiling under 2,000",
                "a primary grid under 100 labelled rows",
                "either primary-grid class under 20"],
            "triggered": stops,
            "verdict": "STOP" if stops else "PROCEED"},
        "elapsed_s": round(time.time() - t0, 1),
    }
    L.atomic_write_json(Path(args.out), payload)
    log(json.dumps(payload["preregistered_hard_stop"], indent=1))
    log(f"lesson ceiling {cohorts['lesson_ceiling']:,} "
        f"(after the UNRESOLVED drop "
        f"{cohorts['lesson_ceiling_after_unresolved_drop']:,}); "
        f"primary {balances['primary']['settled_labels']:,} labelled "
        f"({balances['primary']['positive']:,}+/"
        f"{balances['primary']['negative']:,}-), secondary "
        f"{balances['secondary']['settled_labels']:,} labelled "
        f"({balances['secondary']['positive']:,}+/"
        f"{balances['secondary']['negative']:,}-)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
