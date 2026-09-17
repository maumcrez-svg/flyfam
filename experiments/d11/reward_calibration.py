#!/usr/bin/env python
"""The reinforcement full scale, by the rule registered before it was computed.

docs/SPEC.md D11 amendment §5 and Fable addendum 5, register-then-compute step
(ii). ``experiments/d11/PLAN.md`` and ``config.json`` registered, before this
file was run, both the **calibration set's selection rule** and the
**calibration rule** itself:

    q = 90th percentile of abs(net_return) over the calibration set, with
        linear interpolation.
    new_full_scale = max(old_full_scale, 2 * q)

with ``old_full_scale = 0.01``.

The calibration set is the eight LEARNING records that exist — the distinct,
confirmed D10 LEARN outcomes that actually generated the reported updates.
Excluded and named: the determinism re-run (the same events), the eight
``SETTLED_FROZEN`` outcomes of the frozen control (no reinforcement was ever
called), and the pending live position (no exit leg, no settlement).

Each ``net_return`` is reconstructed **twice** and the two must agree: once
from the ``OUTCOME`` record's own ``net_pnl`` over the 0.01 ETH notional, and
once from the **leg integers** published in
``experiments/d10/closure_complement.md`` —
``net = quote_out − spent − (gas_buy + gas_sell_and_approval)``, in wei, every
cost included. Nothing is estimated and nothing is refitted.

Usage::

    .venv/bin/python experiments/d11/reward_calibration.py
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

HERE = Path(__file__).resolve().parent
D10 = ROOT / "experiments" / "d10"
WEI = 10 ** 18
NOTIONAL_WEI = 10_000_000_000_000_000        # 0.01 ETH
OLD_FULL_SCALE = 0.01
REINFORCE_CAP = 1.0

LOGS = {
    ("d10-001", "learning"): D10 / "runs/d10-001/learning/events.jsonl",
    ("d10-live-001", "live"): D10 / "runs/d10-live-001/live/events.jsonl",
}
#: Which closure-complement section carries each branch's leg integers.
SECTIONS = {("d10-001", "learning"): "### A.1",
            ("d10-live-001", "live"): "### A.3"}


def percentile(values, q: float) -> float:
    """The linear-interpolated quantile named in the rule. No other method."""
    ordered = sorted(values)
    if not ordered:
        raise ValueError("the calibration set is empty")
    if len(ordered) == 1:
        return ordered[0]
    position = q * (len(ordered) - 1)
    low = int(math.floor(position))
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def amount(r: float, full_scale: float) -> float:
    """``ExecutionPolicy.reinforcement``'s amount, with the scale as a knob."""
    return min(abs(r) / full_scale, REINFORCE_CAP)


# ------------------------------------------------------- the leg integers
def _rows(table: str) -> list[list[str]]:
    out = []
    for line in table.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells):
            continue
        out.append(cells)
    return out


def _table_after(text: str, heading: str) -> list[list[str]]:
    start = text.index(heading) + len(heading)
    block = text[start:]
    # the table is the first run of lines beginning with '|'
    lines = []
    started = False
    for line in block.splitlines():
        if line.strip().startswith("|"):
            started = True
            lines.append(line)
        elif started:
            break
    return _rows("\n".join(lines))


def _int(cell: str) -> int:
    return int(cell.replace(",", "").replace("*", "").strip())


def leg_integers(section: str) -> dict:
    """``{row number: {spent, quote_out, gas}}`` in wei, from the markdown."""
    text = (D10 / "closure_complement.md").read_text()
    start = text.index(section)
    end = len(text)
    for nxt in ("\n### ", "\n## "):
        here = text.find(nxt, start + 1)
        if here != -1:
            end = min(end, here)
    body = text[start:end]
    buy = _table_after(body, "**The buy leg, as quoted.**")
    sell = _table_after(body, "**The sell leg, as quoted.**")
    header_buy = buy[0]
    header_sell = sell[0]
    i_spent = header_buy.index("spent")
    i_gas_buy = header_buy.index("gas buy")
    i_quote_out = header_sell.index("quote out")
    i_gas_sell = header_sell.index("gas sell + approval")
    legs: dict[int, dict] = {}
    for row in buy[1:]:
        legs[_int(row[0])] = {"spent": _int(row[i_spent]),
                              "gas_buy": _int(row[i_gas_buy])}
    for row in sell[1:]:
        n = _int(row[0])
        if n not in legs or "—" in row[i_quote_out]:
            continue
        legs[n]["quote_out"] = _int(row[i_quote_out])
        legs[n]["gas_sell_and_approval"] = _int(row[i_gas_sell])
    return legs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(HERE / "reward_calibration.json"))
    args = ap.parse_args(argv)

    outcomes = []
    for (run_id, branch), path in LOGS.items():
        records = [json.loads(line) for line in path.read_text().splitlines()
                   if line.strip()]
        learn = {int(r["episode_id"]): r for r in records if r["kind"] == "LEARNING"}
        out = {int(r["episode_id"]): r for r in records if r["kind"] == "OUTCOME"}
        entries = [r for r in records if r["kind"] == "EXECUTION"
                   and str(r.get("side")) == "BUY"]
        legs = leg_integers(SECTIONS[(run_id, branch)])
        for n, ex in enumerate(entries, 1):
            episode = int(ex["episode_id"])
            if episode not in learn:
                continue                     # never settled, or never taught
            record = out[episode]
            leg = legs.get(n, {})
            net_wei = None
            if {"spent", "gas_buy", "quote_out",
                    "gas_sell_and_approval"} <= set(leg):
                net_wei = (leg["quote_out"] - leg["spent"]
                           - leg["gas_buy"] - leg["gas_sell_and_approval"])
            r_record = float(record["return_on_notional"])
            r_legs = None if net_wei is None else net_wei / NOTIONAL_WEI
            outcomes.append({
                "n": n,
                "run_id": run_id, "branch": branch, "episode_id": episode,
                "token": str(record.get("token") or record.get("symbol")),
                "notional_eth": float(record["notional"]),
                "notional_wei": str(NOTIONAL_WEI),
                "net_pnl_eth_from_the_outcome_record": float(record["net_pnl"]),
                "net_wei_from_the_leg_integers": (None if net_wei is None
                                                  else str(net_wei)),
                "legs_wei": {k: str(v) for k, v in sorted(leg.items())},
                "net_return_from_the_outcome_record": r_record,
                "net_return_from_the_leg_integers": r_legs,
                "abs_net_return": abs(r_record),
                "agreement_abs_difference": (None if r_legs is None
                                             else abs(r_record - r_legs)),
                "valence": int(learn[episode]["valence"]),
                "old_amount_recorded": float(learn[episode]["amount"]),
            })

    outcomes.sort(key=lambda o: (o["run_id"], o["episode_id"]))
    magnitudes = [o["abs_net_return"] for o in outcomes]
    q = percentile(magnitudes, 0.90)
    new_full_scale = max(OLD_FULL_SCALE, 2.0 * q)

    tolerance = 5e-9          # the OUTCOME record rounds net_pnl to 8 decimals
    disagreements = []
    for o in outcomes:
        delta = o["agreement_abs_difference"]
        o["old_amount"] = amount(o["net_return_from_the_outcome_record"],
                                 OLD_FULL_SCALE)
        o["new_amount"] = amount(o["net_return_from_the_outcome_record"],
                                 new_full_scale)
        o["old_amount_clipped"] = (abs(o["net_return_from_the_outcome_record"])
                                   / OLD_FULL_SCALE) > REINFORCE_CAP
        o["new_amount_clipped"] = (abs(o["net_return_from_the_outcome_record"])
                                   / new_full_scale) > REINFORCE_CAP
        o["old_amount_matches_the_log"] = (
            abs(o["old_amount"] - o["old_amount_recorded"]) <= 1e-6)
        if delta is None or delta > tolerance:
            disagreements.append(o["episode_id"])
        if not o["old_amount_matches_the_log"]:
            disagreements.append(f"amount:{o['episode_id']}")
    if disagreements:
        raise SystemExit(
            "the two reconstructions of net_return disagree, or the recomputed "
            f"old amount does not reproduce the log: {disagreements}. The "
            "calibration is refused rather than run on a number that two "
            "sources do not agree on.")

    report = {
        "version": "d11-reward-calibration-1",
        "registered_before_this_file_ran": ["experiments/d11/PLAN.md",
                                            "experiments/d11/config.json"],
        "calibration_rule": ("q = 90th percentile of abs(net_return) over the "
                             "calibration set, with linear interpolation; "
                             "new_full_scale = max(old_full_scale, 2 * q)"),
        "calibration_set_rule": (
            "the distinct, confirmed D10 LEARN outcomes that actually "
            "generated the reported learning updates: the eight LEARNING "
            "records that exist"),
        "excluded": {
            "the_determinism_rerun_of_d10-001_learning": (
                "the same events, not new ones; same normalised sha256 "
                "34a74b0b780e420d39cc3ade6bc77aade3e37961d25c3cdf1cd72479bea7830c"),
            "d10-001_frozen_reference": (
                "eight SETTLED_FROZEN outcomes; Journal.settle_frozen calls no "
                "reinforcement at all, so they generated no learning update"),
            "d10-live-001_episode_72000315": (
                "PENDING_CONFIRMATION at the stop and then END_OF_DATA: no exit "
                "leg was ever quoted, so it has no settled net return"),
            "estimated_or_unavailable_settlements": "none exist",
        },
        "reconstruction": (
            "each net_return is reconstructed twice and the two must agree to "
            "the OUTCOME record's own 8-decimal rounding: from the record's "
            "net_pnl over the 0.01 ETH notional, and from the leg integers in "
            "experiments/d10/closure_complement.md as "
            "quote_out - spent - gas_buy - gas_sell_and_approval, in wei, "
            "every cost included"),
        "agreement_tolerance": tolerance,
        "max_agreement_difference": max(
            o["agreement_abs_difference"] for o in outcomes),
        "n": len(outcomes),
        "notional_eth": 0.01,
        "abs_net_returns_sorted": sorted(magnitudes),
        "q": q,
        "old_full_scale": OLD_FULL_SCALE,
        "new_full_scale": new_full_scale,
        "reinforce_cap": REINFORCE_CAP,
        "clipped_under_the_old_scale": sum(1 for o in outcomes
                                           if o["old_amount_clipped"]),
        "clipped_under_the_new_scale": sum(1 for o in outcomes
                                           if o["new_amount_clipped"]),
        "at_or_above_full_scale_old": sum(
            1 for o in outcomes
            if abs(o["net_return_from_the_outcome_record"]) >= OLD_FULL_SCALE),
        "at_or_above_full_scale_new": sum(
            1 for o in outcomes
            if abs(o["net_return_from_the_outcome_record"]) >= new_full_scale),
        "outcomes": outcomes,
        "what_does_not_move": [
            "REINFORCE_CAP = 1.0",
            "the signed normalisation and clipping mechanism",
            "the neutral treatment: r == 0 delivers nothing",
            "the learning rate and the eligibility rules",
            "one normalised update per settled outcome",
            "flytrade.execution.REINFORCE_FULL_SCALE, which stays 0.01 for the IBM path and every D5-D10 code path",
        ],
        "same_scale_for_both_signs": True,
        "frozen": ("frozen for the next experiment version; no rolling "
                   "recalibration during operation and no tuning after "
                   "observing a BUY frequency or a run's performance"),
        "not_applied_to_old_checkpoints": True,
        "coarse_engineering_reference": (
            "eight selected outcomes from one 15-minute-horizon window on one "
            "instrument class. A coarse engineering reference for a scale "
            "parameter, not an estimate of the memecoin market's return "
            "distribution."),
    }
    Path(args.out).write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps({k: report[k] for k in (
        "n", "q", "old_full_scale", "new_full_scale",
        "clipped_under_the_old_scale", "clipped_under_the_new_scale",
        "max_agreement_difference", "abs_net_returns_sorted")}, indent=1))
    for o in outcomes:
        print(f"  {o['run_id']}/{o['branch']} ep {o['episode_id']:>9} "
              f"|r|={o['abs_net_return']:.10f} old={o['old_amount']:.6f} "
              f"new={o['new_amount']:.6f} "
              f"legs_delta={o['agreement_abs_difference']:.2e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
