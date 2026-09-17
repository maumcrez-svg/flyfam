#!/usr/bin/env python
"""Feature-scale statistics on the 2026-09-08 window. No outcome is read.

docs/SPEC.md D10 addendum 9 requires the Pons encoder's fixed scales to be set
from the donor's cohort statistics **on the 09-08 window only, before any Pons
outcome is looked at**, rounded, written into the config and never refitted.
This script produces those statistics and nothing else: median and 90th
percentile of ``|x|`` at 30-second grid points, over tokens that look
admissible (native ETH, curve still open, at least three trades) at an age of
at least 60 seconds.

It is **scale estimation, not the encoder**. The canonical feature
implementation belongs in ``flytrade/pons/context.py`` in the next dispatch;
this file exists so the scales are fixed before that code can see an outcome,
and the next dispatch must reproduce these definitions exactly.

Conventions declared here, because the addendum leaves them open:

* the marginal price is ``quote_reserve / token_reserve`` from the
  reconstructed state, phantom reserve included — never the last trade price
  and never an executable price;
* ``ret_*`` is zero when its window starts before the launch, as the addendum
  says;
* ``flow_imb_2m`` uses the reserve deltas — a buy's net in, a sell's gross out
  — and is zero with no trades;
* ``trade_rate_2m`` divides by the nominal two minutes even when the token is
  younger, so the feature keeps one fixed scale;
* ``drawdown_5m`` maxes over the token's whole life when five minutes predate
  the launch, which is well defined and still ``<= 0``.

Usage::

    .venv/bin/python experiments/d10/feature_scales.py [--window 2026-09-08]
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

from flytrade.pons.curve import CurveReconstruction, CurveState  # noqa: E402

DATASET = ROOT / "data" / "pons" / "d10-replay-v1"
GRID_SECONDS = 30
MIN_AGE = 60
MIN_TRADES = 3
FEATURES = ("age", "ret_30s", "ret_2m", "ret_5m", "flow_imb_2m",
            "trade_rate_2m", "rv_2m", "drawdown_5m")


def load_dataset(directory: Path) -> tuple[dict, dict]:
    initials = json.loads((directory / "initial_states.json").read_text())
    by_curve: dict[str, list[dict]] = {}
    with open(directory / "events.jsonl", encoding="utf-8") as fh:
        for line in fh:
            event = json.loads(line)
            if event.get("source") == "curve":
                by_curve.setdefault(event["address"], []).append(event)
    for events in by_curve.values():
        events.sort(key=lambda e: (e["block_number"], e["tx_index"], e["log_index"]))
    return initials, by_curve


def price_path(meta: dict, events: list[dict]) -> list[tuple[int, float, str, int]]:
    """``(timestamp, marginal price, kind, signed reserve flow)`` after each event.

    The first entry is the launch itself, at the calibrated initial state.
    """
    s = meta["state"]
    state = CurveState(
        quote_reserve=int(s["quote_reserve"]), token_reserve=int(s["token_reserve"]),
        real_quote_reserve=int(s["real_quote_reserve"]),
        sellable_tokens=int(s["sellable_tokens"]), fee_bps=int(s["fee_bps"]),
        creator_tax_bps=int(s["creator_tax_bps"]), snipe_tax_bps=0,
        graduated=bool(s["graduated"]))
    recon = CurveReconstruction(
        state, launch_block=meta["launch_block"], launched_at=meta["launched_at"],
        snipe_start_bps=meta["snipe_start_bps"],
        snipe_window_seconds=meta["snipe_window_seconds"])
    path = [(meta["launched_at"], state.marginal_price, "launch", 0)]
    for event in events:
        if event["block_number"] <= meta["launch_block"]:
            continue
        kind = event["event"]
        args = event["args"]
        flow = 0
        if kind == "CurveBuy":
            flow = int(args["quoteIn"]) - int(args["fee"]) - int(args["tax"])
        elif kind == "CurveSell":
            flow = -(int(args["quoteOut"]) + int(args["fee"]) + int(args["tax"]))
        recon.apply(event)
        path.append((event["block_timestamp"], recon.state.marginal_price, kind, flow))
        if recon.state.graduated:
            break
    return path


def price_at(path, when: int) -> float | None:
    price = None
    for timestamp, value, _kind, _flow in path:
        if timestamp <= when:
            price = value
        else:
            break
    return price


def features_at(path, launched_at: int, cutoff: int) -> dict:
    age = cutoff - launched_at
    here = price_at(path, cutoff)
    out = {"age": float(age)}
    for name, span in (("ret_30s", 30), ("ret_2m", 120), ("ret_5m", 300)):
        start = cutoff - span
        if start < launched_at or here is None or here <= 0:
            out[name] = 0.0
            continue
        earlier = price_at(path, start)
        out[name] = 0.0 if not earlier else math.log(here / earlier)
    window = [(t, p, k, f) for t, p, k, f in path
              if cutoff - 120 <= t <= cutoff and k in ("CurveBuy", "CurveSell")]
    buy_in = sum(f for _t, _p, _k, f in window if f > 0)
    sell_out = -sum(f for _t, _p, _k, f in window if f < 0)
    total = buy_in + sell_out
    out["flow_imb_2m"] = 0.0 if total == 0 else (buy_in - sell_out) / total
    out["trade_rate_2m"] = len(window) / 2.0
    steps = []
    previous = None
    for timestamp, price, kind, _flow in path:
        if previous is not None and cutoff - 120 <= timestamp <= cutoff \
                and kind in ("CurveBuy", "CurveSell") and price > 0 and previous > 0:
            steps.append(math.log(price / previous))
        previous = price
    out["rv_2m"] = statistics.stdev(steps) if len(steps) >= 2 else 0.0
    peak = max((p for t, p, _k, _f in path
                if max(launched_at, cutoff - 300) <= t <= cutoff), default=None)
    out["drawdown_5m"] = (0.0 if not peak or not here or here <= 0 or peak <= 0
                          else min(0.0, math.log(here / peak)))
    return out


def percentile(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = q * (len(ordered) - 1)
    low = int(math.floor(position))
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default=str(DATASET))
    parser.add_argument("--window", default="2026-09-08")
    parser.add_argument("--out", default=str(ROOT / "experiments" / "d10" /
                                             "feature_scales.json"))
    args = parser.parse_args(argv)
    initials, by_curve = load_dataset(Path(args.dataset))

    samples: dict[str, list[float]] = {name: [] for name in FEATURES}
    points = 0
    tokens_used = 0
    skipped = {"wrong_window": 0, "too_few_trades": 0, "no_grid_point": 0,
               "completed": 0}
    for token, meta in sorted(initials.items()):
        if meta["period"] != ("day8" if args.window == "2026-09-08" else "day9"):
            skipped["wrong_window"] += 1
            continue
        events = by_curve.get(meta["curve"], [])
        path = price_path(meta, events)
        trades = [e for e in path if e[2] in ("CurveBuy", "CurveSell")]
        if len(trades) < MIN_TRADES:
            skipped["too_few_trades"] += 1
            continue
        last = max(t for t, _p, _k, _f in path)
        used = False
        cutoff = meta["launched_at"] + MIN_AGE
        while cutoff <= last:
            values = features_at(path, meta["launched_at"], cutoff)
            for name in FEATURES:
                samples[name].append(values[name])
            points += 1
            used = True
            cutoff += GRID_SECONDS
        if used:
            tokens_used += 1
        else:
            skipped["no_grid_point"] += 1

    table = {}
    for name in FEATURES:
        magnitudes = [abs(v) for v in samples[name]]
        table[name] = {
            "n": len(magnitudes),
            "median_abs": statistics.median(magnitudes) if magnitudes else None,
            "p90_abs": percentile(magnitudes, 0.90) if magnitudes else None,
            "max_abs": max(magnitudes) if magnitudes else None,
            "all_zero": bool(magnitudes) and max(magnitudes) == 0.0,
        }
    report = {
        "window": args.window,
        "grid_seconds": GRID_SECONDS,
        "min_age_seconds": MIN_AGE,
        "min_trades": MIN_TRADES,
        "tokens_considered": sum(1 for m in initials.values()
                                 if m["period"] == ("day8" if args.window == "2026-09-08"
                                                    else "day9")),
        "tokens_with_a_grid_point": tokens_used,
        "grid_points": points,
        "skipped": skipped,
        "features": table,
        "note": ("features whose window predates the launch are zero by rule; with "
                 "this dataset's per-token coverage that makes ret_2m, ret_5m and "
                 "drawdown_5m unestimable here, which is reported rather than "
                 "papered over"),
    }
    Path(args.out).write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
