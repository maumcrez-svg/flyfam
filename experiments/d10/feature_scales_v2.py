#!/usr/bin/env python
"""The declared feature scales, from the backfill's first hour. No outcome read.

docs/SPEC.md D10 addendum 9 as amended by reviewer decision 3. The scales are
set from the tokens launched in the **first 60 minutes** of the
``d10-backfill-v1`` window, sampled at 30-second grid points, restricted to
age ≥ 60 s and ≥ 3 trades, on the median and 90th percentile of ``|x|``.

Two rules make this a registration rather than a fit:

* it runs **before** ``PLAN.md`` and ``config.json`` are committed, and those
  two are committed alone before any run;
* it computes **no outcome, no PnL and no post-cutoff return anywhere**. The
  only thing it reads past a cutoff is the next grid point's own features. A
  grep in ``tests/d10/test_scales.py`` asserts that this file contains no
  outcome vocabulary at all.

Each scale is ``p90(|x|)`` rounded to two significant figures, except ``age``,
which is declared as the constant 600 s — the horizon's length in seconds of
token life, not a fitted quantity.

Usage::

    .venv/bin/python experiments/d10/feature_scales_v2.py
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from flytrade.pons.context import (MIN_AGE_S, MIN_TRADES,  # noqa: E402
                                   PONS_FEATURES, TokenTape)
from flytrade.pons.curve import CurveState  # noqa: E402

HERE = Path(__file__).resolve().parent
DATASET = ROOT / "data" / "pons" / "d10-backfill-v1"
GRID_SECONDS = 30
SCALE_MINUTES = 60

#: Declared, not fitted: the holding horizon expressed as a token age.
AGE_SCALE_S = 600.0


def two_significant_figures(value: float) -> float:
    if value == 0 or not math.isfinite(value):
        return 0.0
    digits = -int(math.floor(math.log10(abs(value)))) + 1
    return round(value, digits)


def percentile(values, q: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = q * (len(ordered) - 1)
    low = int(math.floor(position))
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def load(directory: Path):
    initials = json.loads((directory / "initial_states.json").read_text())
    by_curve: dict[str, list[dict]] = {}
    with open(directory / "events.jsonl", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            event = json.loads(line)
            if event.get("source") == "curve" and event.get("status") == "OK":
                by_curve.setdefault(event["address"], []).append(event)
    for events in by_curve.values():
        events.sort(key=lambda e: (e["block_number"], e["tx_index"], e["log_index"]))
    return initials, by_curve


def tape_for(meta: dict, events: list[dict]) -> TokenTape:
    s = meta["state"]
    tape = TokenTape(
        token=meta["token"], curve=meta["curve"],
        launch_block=int(meta["launch_block"]),
        launched_at=int(meta["launched_at"]),
        initial=CurveState(
            quote_reserve=int(s["quote_reserve"]),
            token_reserve=int(s["token_reserve"]),
            real_quote_reserve=int(s["real_quote_reserve"]),
            sellable_tokens=int(s["sellable_tokens"]),
            fee_bps=int(s["fee_bps"]), creator_tax_bps=int(s["creator_tax_bps"]),
            snipe_tax_bps=0, graduated=bool(s["graduated"])),
        snipe_start_bps=int(meta["snipe_start_bps"]),
        snipe_window_seconds=int(meta["snipe_window_seconds"]),
        quote_asset=str(meta["quote_asset"]))
    for event in events:
        tape.apply(event)
    return tape


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default=str(DATASET))
    parser.add_argument("--out", default=str(HERE / "feature_scales_v2.json"))
    args = parser.parse_args(argv)
    directory = Path(args.dataset)
    manifest = json.loads((directory / "MANIFEST.json").read_text())
    initials, by_curve = load(directory)

    launches = sorted(int(m["launched_at"]) for m in initials.values())
    window_start = launches[0] if launches else 0
    cut = window_start + SCALE_MINUTES * 60

    samples = {name: [] for name in PONS_FEATURES}
    tokens_used = 0
    points = 0
    skipped = {"launched_after_the_first_hour": 0, "too_few_trades": 0,
               "no_grid_point": 0}
    for token, meta in sorted(initials.items()):
        if int(meta["launched_at"]) >= cut:
            skipped["launched_after_the_first_hour"] += 1
            continue
        tape = tape_for(meta, by_curve.get(meta["curve"], []))
        if tape.trades_by(tape.coverage_end()) < MIN_TRADES:
            skipped["too_few_trades"] += 1
            continue
        used = False
        cutoff = tape.launched_at + MIN_AGE_S
        while cutoff <= tape.coverage_end():
            context = tape.context(cutoff)
            if context.usable:
                for name in PONS_FEATURES:
                    samples[name].append(float(context.raw[name]))
                points += 1
                used = True
            cutoff += GRID_SECONDS
        tokens_used += 1 if used else 0
        skipped["no_grid_point"] += 0 if used else 1

    table = {}
    scales = {}
    for name in PONS_FEATURES:
        magnitudes = [abs(v) for v in samples[name]]
        median = statistics.median(magnitudes) if magnitudes else float("nan")
        p90 = percentile(magnitudes, 0.90)
        if name == "age":
            scale = AGE_SCALE_S
            rule = "declared constant, 600 s (the horizon as a token age)"
        else:
            scale = two_significant_figures(p90)
            rule = "p90(|x|) rounded to two significant figures"
        if not scale or not math.isfinite(scale):
            raise SystemExit(f"{name}: a scale must be positive and finite, got {scale}")
        table[name] = {
            "n": len(magnitudes),
            "median_abs": median,
            "p90_abs": p90,
            "max_abs": max(magnitudes) if magnitudes else float("nan"),
            "scale": scale, "rule": rule}
        scales[name] = scale

    report = {
        "version": "d10-feature-scales-2",
        "supersedes": ("experiments/d10/feature_scales.json, which was computed "
                       "on the donor replay dataset with the windows zeroed at "
                       "the launch; reviewer decision 3 clips them to the launch "
                       "instead and moves the statistics to this window"),
        "dataset": manifest["dataset"],
        "dataset_sha256": {k: v["sha256"] for k, v in manifest["files"].items()},
        "window": manifest["window"],
        "scale_window_minutes": SCALE_MINUTES,
        "scale_window_first_launch_ts": window_start,
        "scale_window_last_launch_ts_exclusive": cut,
        "grid_seconds": GRID_SECONDS,
        "min_age_seconds": MIN_AGE_S,
        "min_trades": MIN_TRADES,
        "tokens_in_the_first_hour": sum(
            1 for m in initials.values() if int(m["launched_at"]) < cut),
        "tokens_with_a_grid_point": tokens_used,
        "grid_points": points,
        "skipped": skipped,
        "features": table,
        "scales": scales,
        "computed_before": ["experiments/d10/PLAN.md", "experiments/d10/config.json"],
        "no_outcome_computed": True,
        "note": ("median and p90 of |x| over the grid points of the tokens "
                 "launched in the first hour of the window; no outcome, no PnL "
                 "and no post-cutoff return enters this file"),
    }
    Path(args.out).write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"scales": scales, "grid_points": points,
                      "tokens": tokens_used, "skipped": skipped,
                      "features": {k: {"median_abs": v["median_abs"],
                                       "p90_abs": v["p90_abs"],
                                       "scale": v["scale"]}
                                   for k, v in table.items()}}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
