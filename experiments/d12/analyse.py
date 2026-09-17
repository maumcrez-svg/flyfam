#!/usr/bin/env python
"""The d12-001 comparison and its report. Primary and secondary grids.

    .venv/bin/python experiments/d12/analyse.py --report
    .venv/bin/python experiments/d12/analyse.py --report-md

**Declared deviation of form.** ``d12_001.json``'s registered entry-point list
names this file ``evaluate.py``. It is ``analyse.py``, and the renderer beside
it is ``render.py`` rather than ``report.py``, because ``experiments/d7`` and
``experiments/d11`` already own the module name ``evaluate`` and
``experiments/d8`` owns ``report``, and one pytest session shares one
``sys.modules``. The registered file is **not** edited after registration —
D11's deviation 3 set that precedent — so the rename is declared here, in the
report and in ``the session log``, and absorbed nowhere.

`ΔAUC = AUC(SCHOOL) − AUC(REFERENCE)` over the rows `VALID` in both branches
that carry a settled label, with a paired cluster bootstrap by ``stable_id`` at
10,000 resamples and seed 20260913, overall and per temporal block, on the
**primary** grid (tokens that were never a lesson) and on the **secondary**
grid (all FROZEN rows). The statistics are ``experiments/d11/stats.py``'s,
imported and not reimplemented, so the two waves' numbers are produced by one
function.

The **pre-registered wording of addendum 7** is produced in exactly one place,
:func:`preregistered_reading`, so no caller can invent another. Never
"significant", never "proves". An AUC near 0.5 is not evidence that no signal
exists; a lower BUY rate alone is not learning success; profit is not learning.

**Nothing here opens a socket.**
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import d12lib as L                                        # noqa: E402
import stats as ST                                        # noqa: E402  (D11's)

C = L.C
RUN = L.RUNS / L.RUN_ID
GRID = RUN / "grid"

#: addendum 9, verbatim
CONDITIONS = (
    "fewer than 2,000 lessons applied",
    "fewer than 100 paired labels on the primary grid",
    "either outcome class under 20 on the primary grid",
    "paired coverage under 95 %",
    "encoder saturation over 5 % of (row, channel) pairs or INVALID_STATE "
    "over 5 %",
    "more than 25 % of plastic synapses at floor or ceiling at the end of "
    "LEARNING",
)


def preregistered_reading(interval: dict) -> str:
    """Addendum 7's three readings, and nothing else, from one place."""
    lo, hi = interval.get("lo"), interval.get("hi")
    if lo is None or hi is None:
        return ("no interval could be formed, so no reading applies "
                f"({interval.get('clusters', 0)} clusters, "
                f"{interval.get('kept', 0)} resamples kept)")
    if lo > 0.0:
        return ("the school-trained ranking of later tokens is higher than "
                "the untrained one, not compatible with sampling variation")
    if hi < 0.0:
        return "the inversion persists"
    return "compatible with sampling variation"


def read_jsonl(path: Path):
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def load() -> tuple[list[dict], dict]:
    rows = {(r["cutoff_ts"], r["stable_id"]): r
            for r in read_jsonl(GRID / "rows.jsonl")}
    labels = {(r["cutoff_ts"], r["stable_id"]): r
              for r in read_jsonl(GRID / "labels.jsonl")}
    scores = {}
    for branch in ("school", "reference"):
        scores[branch] = {(r["cutoff_ts"], r["stable_id"]): r
                          for r in read_jsonl(GRID / f"scores_{branch}.jsonl")}
    lessons = json.loads((L.HERE / "lesson_tokens.json").read_text())
    lesson_tokens = set(lessons["tokens"])
    blocks = L.split()["temporal_blocks"]
    theta = C.RO.THETA_HZ_K8
    joined, missing = [], Counter()
    for key, row in rows.items():
        sc = scores["school"].get(key)
        rf = scores["reference"].get(key)
        label = labels.get(key)
        if sc is None:
            missing["school"] += 1
        if rf is None:
            missing["reference"] += 1
        if label is None:
            missing["label"] += 1
        valid = bool(sc is not None and rf is not None
                     and sc.get("status") == "VALID"
                     and rf.get("status") == "VALID")
        joined.append({
            "cutoff_ts": key[0], "stable_id": key[1], "token": row["token"],
            "tick": row["tick"], "block": C.block_of(key[0], blocks),
            "never_a_lesson": row["token"] not in lesson_tokens,
            "saturated_channels": int(row["saturated_channels"]),
            "valid_both": valid,
            "school_status": None if sc is None else sc.get("status"),
            "reference_status": None if rf is None else rf.get("status"),
            "school_action": None if sc is None else sc.get("action"),
            "reference_action": None if rf is None else rf.get("action"),
            "school": (float(sc["valence_hz"])
                       if sc and sc.get("valence_hz") is not None else None),
            "reference": (float(rf["valence_hz"])
                          if rf and rf.get("valence_hz") is not None else None),
            "settled": bool(label and label.get("settled")),
            "net": float(label["net"]) if label and label.get("settled") else None,
            "y": bool(label["positive"]) if label and label.get("settled")
            else None,
        })
        if valid:
            joined[-1]["school_buy"] = joined[-1]["school"] > theta
            joined[-1]["reference_buy"] = joined[-1]["reference"] > theta
    meta = {"rows": len(rows), "missing_joins": dict(missing),
            "theta_hz": theta,
            "lesson_tokens": len(lesson_tokens),
            "school_digest": next(iter(scores["school"].values()))
            ["checkpoint_digest"],
            "reference_digest": next(iter(scores["reference"].values()))
            ["checkpoint_digest"]}
    return joined, meta


def primary_rows(rows, lesson_tokens) -> list[dict]:
    """The primary grid: the rows on tokens that were never a lesson.

    By **address**, not by stable id: the two grids were built by different
    passes and a stable id means nothing across them. Pure, so a test can hand
    it invented rows and a set.
    """
    tokens = set(lesson_tokens)
    return [r for r in rows if r["token"] not in tokens]


def clusters_of(rows):
    by_token = defaultdict(list)
    for r in rows:
        by_token[r["stable_id"]].append(r)
    return list(by_token.values())


def grid_analysis(rows: list[dict], *, name: str, blocks, log=print) -> dict:
    """One grid's ΔAUC, its intervals, its suppression and its coverage."""
    n_rows = len(rows)
    valid = [r for r in rows if r["valid_both"]]
    paired = [r for r in valid if r["settled"]]
    stat = ST.delta_auc_statistic("school", "reference", "y")

    def auc_block(sub):
        y = [r["y"] for r in sub]
        a = ST.auc([r["school"] for r in sub], y)
        b = ST.auc([r["reference"] for r in sub], y)
        return a, b

    a, b = auc_block(paired) if paired else (None, None)
    overall = {
        "n": len(paired),
        "positive": sum(1 for r in paired if r["y"]),
        "negative": sum(1 for r in paired if not r["y"]),
        "clusters": len({r["stable_id"] for r in paired}),
        "tokens": len({r["token"] for r in paired}),
        "auc_school": a, "auc_reference": b,
        "delta_auc": None if (a is None or b is None) else a - b,
        "spearman_school": ST.spearman([r["school"] for r in paired],
                                       [r["net"] for r in paired]) if paired
        else None,
        "spearman_reference": ST.spearman([r["reference"] for r in paired],
                                          [r["net"] for r in paired]) if paired
        else None,
    }
    log(f"[{name}] bootstrapping the overall interval "
        f"({overall['clusters']:,} clusters) ...")
    overall["interval"] = ST.cluster_bootstrap(clusters_of(paired), stat)
    overall["wording"] = ST.describe_interval(
        overall["interval"], name="delta AUC (SCHOOL - REFERENCE)")
    overall["preregistered_reading"] = preregistered_reading(
        overall["interval"])

    per_block = []
    for row in blocks:
        sub = [r for r in paired if r["block"] == row["block"]]
        aa, bb = auc_block(sub) if sub else (None, None)
        entry = {"block": row["block"], "from_ts": row["from_ts"],
                 "to_ts": row["to_ts"], "n": len(sub),
                 "positive": sum(1 for r in sub if r["y"]),
                 "negative": sum(1 for r in sub if not r["y"]),
                 "clusters": len({r["stable_id"] for r in sub}),
                 "auc_school": aa, "auc_reference": bb,
                 "delta_auc": None if (aa is None or bb is None) else aa - bb}
        log(f"[{name}] bootstrapping block {row['block']} ...")
        entry["interval"] = ST.cluster_bootstrap(clusters_of(sub), stat)
        entry["wording"] = ST.describe_interval(
            entry["interval"], name=f"block {row['block']} delta AUC")
        entry["preregistered_reading"] = preregistered_reading(entry["interval"])
        per_block.append(entry)

    def rate(sub, key):
        return (sum(1 for r in sub if r[key]) / len(sub)) if sub else None

    diffs = [r["school"] - r["reference"] for r in valid]
    suppression = {
        "rows_valid_in_both": len(valid),
        "buy_rate_school": rate(valid, "school_buy"),
        "buy_rate_reference": rate(valid, "reference_buy"),
        "per_block": [{
            "block": row["block"],
            "n": len([r for r in valid if r["block"] == row["block"]]),
            "buy_rate_school": rate(
                [r for r in valid if r["block"] == row["block"]], "school_buy"),
            "buy_rate_reference": rate(
                [r for r in valid if r["block"] == row["block"]],
                "reference_buy")} for row in blocks],
        "by_outcome_class": {
            ("positive" if positive else "negative"): {
                "n": len([r for r in paired if r["y"] is positive]),
                "buy_rate_school": rate(
                    [r for r in paired if r["y"] is positive], "school_buy"),
                "buy_rate_reference": rate(
                    [r for r in paired if r["y"] is positive],
                    "reference_buy")} for positive in (True, False)},
        "score": {branch: {
            "mean": float(np.mean([r[branch] for r in valid])) if valid else None,
            "sd": float(np.std([r[branch] for r in valid], ddof=1))
            if len(valid) > 1 else None,
            "min": float(np.min([r[branch] for r in valid])) if valid else None,
            "median": float(np.median([r[branch] for r in valid])) if valid else None,
            "max": float(np.max([r[branch] for r in valid])) if valid else None,
        } for branch in ("school", "reference")},
        "score_difference": {
            "mean": float(np.mean(diffs)) if diffs else None,
            "sd": float(np.std(diffs, ddof=1)) if len(diffs) > 1 else None,
            "median": float(np.median(diffs)) if diffs else None,
            "min": float(np.min(diffs)) if diffs else None,
            "max": float(np.max(diffs)) if diffs else None},
        "a_lower_buy_rate_alone_is_not_learning_success": True,
    }
    log(f"[{name}] bootstrapping the suppression contrast ...")
    contrast = ST.cluster_bootstrap(
        clusters_of(paired),
        ST.class_contrast_statistic("school_buy", "reference_buy", "y"))
    suppression["class_contrast"] = contrast
    suppression["class_contrast_wording"] = ST.describe_interval(
        contrast, name="the between-class difference of the school-minus-"
                       "reference change in the BUY-crossing rate")
    if contrast["lo"] is None or contrast["hi"] is None:
        suppression["reading"] = "no interval"
    elif contrast["lo"] <= 0.0 <= contrast["hi"]:
        suppression["reading"] = "global"
    else:
        suppression["reading"] = "contextual"

    return {
        "name": name,
        "rows": n_rows,
        "tokens": len({r["token"] for r in rows}),
        "rows_valid_in_both": len(valid),
        "paired_neural_coverage": (len(valid) / n_rows) if n_rows else None,
        "paired_labelled_rows": len(paired),
        "class_balance": {"positive": overall["positive"],
                          "negative": overall["negative"]},
        "overall": overall, "per_block": per_block,
        "suppression": suppression,
    }


def analyse(*, log=print) -> dict:
    rows, meta = load()
    blocks = L.split()["temporal_blocks"]
    cfg_v2, cfg_run = L.configs()
    channels = len(cfg_v2["features"]["order"])

    school = json.loads((RUN / "school_summary.json").read_text())
    frozen_path = RUN / "frozen_summary.json"
    frozen = json.loads(frozen_path.read_text()) if frozen_path.exists() else {}
    ceiling = json.loads((L.HERE / "ceiling.json").read_text())
    mirror = json.loads((L.HERE / "mirror_diagnostic.json").read_text())
    reuse = json.loads((GRID / "reuse.json").read_text())
    verification = json.loads((GRID / "reference_verification.json").read_text())
    d11 = json.loads((L.D11_GRID / "evaluation.json").read_text())

    secondary = grid_analysis(rows, name="secondary", blocks=blocks, log=log)
    lesson_tokens = set(json.loads(
        (L.HERE / "lesson_tokens.json").read_text())["tokens"])
    primary = grid_analysis(primary_rows(rows, lesson_tokens),
                            name="primary", blocks=blocks, log=log)

    sat_pairs = sum(r["saturated_channels"] for r in rows)
    sat_rows = sum(1 for r in rows if r["saturated_channels"] > 0)
    saturation = {
        "rows": len(rows), "channels_per_row": channels,
        "row_channel_pairs": len(rows) * channels,
        "saturated_row_channel_pairs": sat_pairs,
        "saturated_row_channel_fraction": (
            sat_pairs / (len(rows) * channels)) if rows else None,
        "rows_with_at_least_one": sat_rows,
        "rows_with_at_least_one_fraction": (sat_rows / len(rows)) if rows else None,
    }
    status_counts = {b: dict(Counter(r[f"{b}_status"] for r in rows))
                     for b in ("school", "reference")}
    invalid = {b: sum(1 for r in rows if r[f"{b}_status"] == "INVALID_STATE")
               for b in ("school", "reference")}
    invalid_rate = {b: (v / len(rows)) if rows else None
                    for b, v in invalid.items()}

    applied = int(school["lessons"]["applied"])
    weights = school["final_weights"]
    worst_sat = max(saturation["saturated_row_channel_fraction"] or 0.0,
                    max((v or 0.0) for v in invalid_rate.values()))
    smaller_class = min(primary["class_balance"]["positive"],
                        primary["class_balance"]["negative"])
    conditions = [
        {"condition": CONDITIONS[0], "measured": applied, "threshold": 2000,
         "detail": f"{applied:,} lessons applied "
                   f"({school['lessons']['accepted']:,} accepted, "
                   f"{school['lessons']['neutral']:,} neutral)",
         "fails": applied < 2000},
        {"condition": CONDITIONS[1],
         "measured": primary["paired_labelled_rows"], "threshold": 100,
         "detail": f"{primary['paired_labelled_rows']:,} primary rows valid in "
                   f"both branches with a settled label",
         "fails": primary["paired_labelled_rows"] < 100},
        {"condition": CONDITIONS[2], "measured": smaller_class, "threshold": 20,
         "detail": f"{primary['class_balance']['positive']:,} positive / "
                   f"{primary['class_balance']['negative']:,} negative",
         "fails": smaller_class < 20},
        {"condition": CONDITIONS[3],
         "measured": secondary["paired_neural_coverage"], "threshold": 0.95,
         "detail": f"{(secondary['paired_neural_coverage'] or 0) * 100:.2f} % "
                   f"of {secondary['rows']:,} rows valid in both branches",
         "fails": (secondary["paired_neural_coverage"] or 0) < 0.95},
        {"condition": CONDITIONS[4], "measured": worst_sat, "threshold": 0.05,
         "detail": f"saturation "
                   f"{(saturation['saturated_row_channel_fraction'] or 0) * 100:.3f} % "
                   f"of (row, channel) pairs; INVALID_STATE "
                   + ", ".join(f"{b} {(v or 0) * 100:.3f} %"
                               for b, v in invalid_rate.items()),
         "fails": worst_sat > 0.05},
        {"condition": CONDITIONS[5],
         "measured": weights["saturated_fraction"], "threshold": 0.25,
         "detail": f"{(weights['saturated_fraction'] or 0) * 100:.2f} % of "
                   f"{weights['synapses']:,} plastic synapses "
                   f"({(weights['at_floor_fraction'] or 0) * 100:.2f} % at the "
                   f"floor, {(weights['at_ceiling_fraction'] or 0) * 100:.2f} % "
                   f"at the ceiling, which is where the clean reference starts)",
         "fails": (weights["saturated_fraction"] or 0) > 0.25},
    ]
    failed = [c for c in conditions if c["fails"]]

    payload = {
        "version": "d12-001-evaluation-1",
        "run_id": L.RUN_ID,
        "reinforcement_rule": school["reinforcement_rule"],
        "meta": meta,
        "split": L.split(),
        "reuse": reuse, "reference_verification": verification,
        "saturation": saturation,
        "readout_status": status_counts,
        "no_response_rate": {b: (c.get("NO_RESPONSE", 0) / len(rows))
                             if rows else None
                             for b, c in status_counts.items()},
        "invalid_state": {"counts": invalid, "rates": invalid_rate},
        "primary": primary, "secondary": secondary,
        "conditions": conditions,
        "verdict": ("INCONCLUSIVE" if failed else "CONCLUSIVE_BY_ITS_OWN_FLOOR"),
        "conditions_failed": len(failed),
        "school": {k: school[k] for k in (
            "ticks", "start_digest", "end_digest", "learned_digest",
            "reinforcement_rule", "n_min", "cohorts", "lessons", "cohort_size",
            "learning_curve", "weights", "final_weights", "presentations",
            "candidate_evaluations", "readout_status_at_presentation",
            "decoded_action_at_presentation", "lesson_log_sha256",
            "log_normalised_sha256", "checkpoints_written", "wall_s")},
        "ceiling": {k: ceiling["learning"][k] for k in (
            "lesson_ceiling", "lesson_ceiling_after_unresolved_drop",
            "cohort_size_distribution", "tokens_that_become_lessons",
            "first_eligible_learning_tick")},
        "mirror": {"overall": mirror["overall"], "auc": mirror["auc"],
                   "within_tick": mirror["within_tick"]},
        "frozen": {name: b.get("paper") for name, b in
                   (frozen.get("branches") or {}).items()},
        "frozen_digests": {name: {"start": b.get("start_digest"),
                                  "end": b.get("end_digest"),
                                  "unchanged": b.get("digest_unchanged")}
                           for name, b in (frozen.get("branches") or {}).items()},
        "d11_001_secondary": {
            "rows": d11["rows"], "rows_valid_in_both": d11["rows_valid_in_both"],
            "paired_labelled_rows": d11["paired_labelled_rows"],
            "class_balance": d11["class_balance"],
            "auc_trained": d11["primary"]["overall"]["auc_trained"],
            "auc_reference": d11["primary"]["overall"]["auc_reference"],
            "delta_auc": d11["primary"]["overall"]["delta_auc"],
            "interval": {k: d11["primary"]["overall"]["interval"][k]
                         for k in ("lo", "hi", "point", "clusters", "kept")},
            "per_block": [{"block": r["block"], "delta_auc": r["delta_auc"],
                           "lo": r["interval"]["lo"], "hi": r["interval"]["hi"]}
                          for r in d11["primary"]["per_block"]],
            "buy_rate_trained": d11["suppression"]["buy_rate_trained"],
            "buy_rate_reference": d11["suppression"]["buy_rate_reference"],
        },
        "wording_rule": (
            "an interval that includes 0 is reported as compatible with "
            "sampling variation; never 'significant', never 'proves'; an AUC "
            "near 0.5 is not evidence that no signal exists; a lower BUY rate "
            "alone is not learning success; profit is not learning"),
    }
    L.atomic_write_json(GRID / "evaluation.json", payload)
    return payload


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--report-md", action="store_true")
    args = parser.parse_args(argv)

    def log(*a):
        print(*a, flush=True)

    if args.report:
        t0 = time.time()
        payload = analyse(log=log)
        print(json.dumps({
            "verdict": payload["verdict"],
            "conditions_failed": payload["conditions_failed"],
            "primary": {k: payload["primary"][k] for k in
                        ("rows", "paired_labelled_rows", "class_balance")},
            "secondary": {k: payload["secondary"][k] for k in
                          ("rows", "paired_labelled_rows", "class_balance")},
        }, indent=1))
        for name in ("primary", "secondary"):
            o = payload[name]["overall"]
            print(f"{name}: AUC(SCHOOL) {o['auc_school']} vs "
                  f"AUC(REFERENCE) {o['auc_reference']} -> {o['wording']}")
            print(f"  reading: {o['preregistered_reading']}")
        print(f"{time.time() - t0:.0f}s")
        return 0
    if args.report_md:
        import render                                       # noqa: PLC0415
        render.write(json.loads((GRID / "evaluation.json").read_text()),
                     RUN / "report.md", log=log)
        return 0
    raise SystemExit("nothing to do: pass --report or --report-md")


if __name__ == "__main__":
    raise SystemExit(main())
