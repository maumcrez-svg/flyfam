#!/usr/bin/env python
"""The two fitted v2 feature scales, by rule X. No outcome read anywhere.

docs/SPEC.md D11 amendment §4 and Fable addendum 4, register-then-compute step
(ii). ``experiments/d11/PLAN.md`` and ``config.json`` registered **rule X**
before this file was run:

    the scale of a fitted feature is p90 of |x| over the 30-second grid points
    of the tokens launched in the first 60 minutes of ``d10-backfill-v1`` at
    which ``admission_v2`` admits that token at that grid point, computed
    causally at each grid point with the tape truncated there, rounded to two
    significant figures.

Only ``trade_count_2m`` and ``gross_volume_2m`` are fitted. The other eight
scales are declared constants and are not recomputed here — nothing in this
file can move them.

**No outcome, no PnL, no post-cutoff return and no survival is computed
anywhere.** The only thing read past a cutoff is the next grid point's own
features, and ``tests/d11/test_scales.py`` asserts that this file contains no
outcome vocabulary at all.

Usage::

    .venv/bin/python experiments/d11/feature_scales_v2.py
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

from flytrade.pons.admission_v2 import AdmissionPolicyV2  # noqa: E402
from flytrade.pons.context import MIN_AGE_S, TokenTape  # noqa: E402
from flytrade.pons.context_v2 import context_v2  # noqa: E402
from flytrade.pons.curve import CurveState  # noqa: E402

HERE = Path(__file__).resolve().parent
DATASET = ROOT / "data" / "pons" / "d10-backfill-v1"
GRID_SECONDS = 30
SCALE_MINUTES = 60
FITTED = ("trade_count_2m", "gross_volume_2m")


def two_significant_figures(value: float) -> float:
    if value == 0 or not math.isfinite(value):
        return 0.0
    digits = -int(math.floor(math.log10(abs(value)))) + 1
    return round(value, digits)


def percentile(values, q: float) -> float:
    """The linear-interpolated quantile, the same one the reward rule uses."""
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


def tape_for(meta: dict, events: list[dict], coverage_end_ts: int) -> TokenTape:
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
        quote_asset=str(meta["quote_asset"]),
        deployment="pons-v2",
        coverage_end_ts=int(coverage_end_ts))
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
    config = json.loads((HERE / "config.json").read_text())
    initials, by_curve = load(directory)

    headers = [json.loads(line) for line
               in (directory / "headers.jsonl").read_text().splitlines()
               if line.strip()]
    last_header_ts = max(int(h["timestamp"]) for h in headers)
    last_event_ts = max((int(e["block_timestamp"])
                         for evs in by_curve.values() for e in evs),
                        default=0)
    coverage_end_ts = min(last_event_ts, last_header_ts)

    admission = AdmissionPolicyV2(
        size_wei=int(config["paper_size_wei"]) if "paper_size_wei" in config
        else 10_000_000_000_000_000,
        latency_s=2, horizon_s=900,
        max_candidates=int(config["admission"]["max_candidates_per_round"]),
        recent_window_s=int(config["admission"]["constants"]["recent_window_seconds"]),
        min_valid_trades_in_window=int(
            config["admission"]["constants"]["minimum_valid_trades_in_window"]),
        max_seconds_since_last_trade=int(
            config["admission"]["constants"]["maximum_seconds_since_last_trade"]),
        require_coverage=True)

    launches = sorted(int(m["launched_at"]) for m in initials.values())
    window_start = launches[0] if launches else 0
    cut = window_start + SCALE_MINUTES * 60

    samples = {name: [] for name in FITTED}
    reasons: dict[str, int] = {}
    tokens_in_hour = 0
    tokens_used = 0
    grid_points = 0
    admitted_points = 0
    for token, meta in sorted(initials.items()):
        if int(meta["launched_at"]) >= cut:
            continue
        tokens_in_hour += 1
        tape = tape_for(meta, by_curve.get(meta["curve"], []), coverage_end_ts)
        used = False
        cutoff = tape.launched_at + MIN_AGE_S
        while cutoff <= tape.coverage_end():
            grid_points += 1
            context = context_v2(tape, cutoff)
            candidate = admission.consider(tape, context, stable_id=0,
                                           cutoff=cutoff)
            if candidate.admitted:
                admitted_points += 1
                used = True
                for name in FITTED:
                    samples[name].append(abs(float(context.raw[name])))
                reasons["ADMITTED"] = reasons.get("ADMITTED", 0) + 1
            else:
                for reason in candidate.reasons:
                    reasons[reason] = reasons.get(reason, 0) + 1
            cutoff += GRID_SECONDS
        tokens_used += 1 if used else 0

    table = {}
    scales = {}
    for name in FITTED:
        values = samples[name]
        p90 = percentile(values, 0.90)
        scale = two_significant_figures(p90)
        if not scale or not math.isfinite(scale):
            raise SystemExit(
                f"{name}: rule X produced {scale!r}. A scale must be positive "
                f"and finite; it is not silently replaced by a guess.")
        table[name] = {
            "n": len(values),
            "median_abs": statistics.median(values) if values else float("nan"),
            "p90_abs": p90,
            "max_abs": max(values) if values else float("nan"),
            "scale": scale,
            "rule": ("p90(|x|) over the admitted 30-second grid points, "
                     "rounded to two significant figures (rule X)"),
        }
        scales[name] = scale

    report = {
        "version": "d11-feature-scales-1",
        "rule_x": config["features"]["rule_x"],
        "registered_before_this_file_ran": ["experiments/d11/PLAN.md",
                                            "experiments/d11/config.json"],
        "fitted_features": list(FITTED),
        "not_fitted_here": [n for n in config["features"]["order"]
                            if n not in FITTED],
        "dataset": manifest["dataset"],
        "dataset_sha256": {k: v["sha256"] for k, v in manifest["files"].items()},
        "window": manifest["window"],
        "coverage_end_ts": coverage_end_ts,
        "scale_window_minutes": SCALE_MINUTES,
        "scale_window_first_launch_ts": window_start,
        "scale_window_last_launch_ts_exclusive": cut,
        "grid_seconds": GRID_SECONDS,
        "min_age_seconds": MIN_AGE_S,
        "admission": admission.as_dict(),
        "tokens_launched_in_the_first_hour": tokens_in_hour,
        "tokens_with_at_least_one_admitted_grid_point": tokens_used,
        "grid_points_evaluated": grid_points,
        "grid_points_admitted": admitted_points,
        "grid_point_reasons": dict(sorted(reasons.items())),
        "statistics": table,
        "scales": scales,
        "no_outcome_computed": True,
        "note": ("p90 of |x| over the admitted grid points of the tokens "
                 "launched in the first hour of the window. No outcome, no "
                 "PnL, no post-cutoff return and no survival enters this file, "
                 "and the fit is never repeated after a run is observed."),
    }
    Path(args.out).write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({
        "scales": scales,
        "tokens_launched_in_the_first_hour": tokens_in_hour,
        "tokens_with_at_least_one_admitted_grid_point": tokens_used,
        "grid_points_evaluated": grid_points,
        "grid_points_admitted": admitted_points,
        "statistics": table,
        "grid_point_reasons": dict(sorted(reasons.items())),
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
