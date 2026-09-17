#!/usr/bin/env python
"""
D8 stage 4 — the target-alignment audit.

    .venv/bin/python experiments/d8/alignment.py

`docs/SPEC.md` D8 §8 and Fable addendum 11. The 42 actual LEARNING episodes of
`d7-001`, read out of the event log through `flytrade.records` parsing only, set
beside the fixed-90-minute quantity D7's evaluation asked about.

What this is: a measurement of **alignment** between the outcome the fly was
reinforced on and the outcome the evaluation scored.

What this is **not**: a simulation of the trades a fixed-hold policy would have
taken. These counterfactuals reuse the original entry times, and a fixed-hold
policy changes inventory and therefore later entry opportunities. Nothing here
updates a weight, replays a reward, changes an account or rewrites an original
event, and **no hypothetical outcome is booked as portfolio PnL**. Whether
fixed-hold training would succeed is not measured here, and a future fixed-hold
wave needs its own explicit policy amendment.

Writes ``withheld d8 alignment table`` and ``experiments/d8/alignment.md``.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date as _date
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import data as D                                     # noqa: E402
from flytrade import historical as H                 # noqa: E402
from flytrade import horizon as HZ                   # noqa: E402
from flytrade import records as REC                  # noqa: E402

JSON_OUT = HERE / "alignment.json"
MD_OUT = HERE / "alignment.md"


def et(ts: int) -> str:
    return H.ny_datetime(int(ts)).strftime("%Y-%m-%d %H:%M ET")


def chains(log_path: Path, partition: str) -> dict:
    """``{episode_id: {kind: event}}`` for the chains inside one partition.

    ``flytrade.records.EventLog.read`` is the parser; nothing is re-derived and
    no field is recomputed from the raw line.
    """
    events = REC.EventLog(log_path).read()
    out: dict[int, dict] = {}
    inside = False
    for e in events:
        k = e.get("kind")
        if k == "PARTITION" and e.get("partition") == partition:
            inside = e.get("boundary") == "start"
            continue
        if not inside or "episode_id" not in e:
            continue
        if k not in ("DECISION", "EXECUTION", "OUTCOME", "LEARNING"):
            continue
        out.setdefault(int(e["episode_id"]), {})[k] = e
    return {eid: c for eid, c in out.items() if "OUTCOME" in c}


def main() -> int:
    t0 = time.time()
    D.check_artifacts()
    ser = D.series()
    cfg = D.CONFIG
    tgt = cfg["target"]
    hstar = int(cfg["grids"]["H"])
    delay = int(cfg["grids"]["delay_minutes"])
    notional = float(tgt["notional"])
    fee_bps, slip_bps = float(tgt["fee_bps"]), float(tgt["slippage_bps"])

    ch = chains(D.ROOT / cfg["partitions"]["fitting"]["log"], "LEARNING")

    rows = []
    fill_checks = {"compared": 0, "reference_price_equal": 0,
                   "slipped_fill_equal": 0, "max_abs_diff": 0.0}
    for eid in sorted(ch):
        c = ch[eid]
        dec, ex, out, lrn = (c.get("DECISION"), c.get("EXECUTION"),
                             c["OUTCOME"], c.get("LEARNING"))
        entry, exit_ = out["entry"], out["exit"]
        day = H.session_date(int(entry["ts"]))
        dm = int(dec["bar_index"]) if dec is not None else int(entry["bar_index"]) - delay

        h = HZ.hold(ser, day, dm, hstar, delay=delay)
        if h.ok:
            fill_checks["compared"] += 1
            d_ref = abs(float(h.entry_open) - float(entry["reference_price"]))
            d_fill = abs(float(h.entry_open) * (1.0 + slip_bps * HZ.BPS)
                         - float(entry["fill_price"]))
            fill_checks["reference_price_equal"] += int(d_ref <= 1e-9)
            fill_checks["slipped_fill_equal"] += int(d_fill <= 1e-6)
            fill_checks["max_abs_diff"] = max(fill_checks["max_abs_diff"], d_ref)
            hyp_net = h.net_pnl(notional=notional, fee_bps=fee_bps,
                                slippage_bps=slip_bps)
            hyp = {"available": True,
                   "entry_minute": h.entry_minute, "exit_minute": h.exit_minute,
                   "entry_open": float(h.entry_open),
                   "exit_open": float(h.exit_open),
                   "exit_time": et(h.exit_ts),
                   "gross_bps": float(h.gross_bps),
                   "net_pnl": float(hyp_net),
                   "net_return_on_notional": float(h.net_return(
                       notional=notional, fee_bps=fee_bps,
                       slippage_bps=slip_bps)),
                   "label_Y": int(hyp_net > 0.0),
                   "sign": int(np.sign(hyp_net))}
        else:
            hyp = {"available": False, "reason": h.reason, "label_Y": None,
                   "net_pnl": None, "sign": None}

        rows.append({
            "episode_id": eid,
            "session": str(day),
            "decision_minute": dm,
            "information_cutoff": et(int(dec["cutoff_ts"])) if dec else None,
            "information_cutoff_ts": int(dec["cutoff_ts"]) if dec else None,
            "entry_time": et(int(entry["ts"])),
            "entry_minute": int(entry["bar_index"]),
            "entry_reference_price": float(entry["reference_price"]),
            "entry_fill_price": float(entry["fill_price"]),
            "actual_exit_time": et(int(exit_["ts"])),
            "actual_exit_minute": int(exit_["bar_index"]),
            "actual_exit_reason": out["close_reason"],
            "actual_holding_minutes": int(out["market_minutes_held"]),
            "actual_gross_pnl": float(out["gross_pnl"]),
            "actual_gross_reference_pnl": float(out["gross_reference_pnl"]),
            "actual_net_pnl": float(out["net_pnl"]),
            "actual_fees": float(out["fees"]),
            "actual_slippage": float(out["slippage"]),
            "actual_return_on_notional": float(out["return_on_notional"]),
            "actual_sign": int(np.sign(float(out["net_pnl"]))),
            "reinforcement_sign": (int(lrn["valence"]) if lrn else None),
            "reinforcement_amount": (float(lrn["amount"]) if lrn else None),
            "reinforcement_accepted": (bool(lrn["accepted"]) if lrn else None),
            "hypothetical_H90": hyp,
        })

    held = np.array([r["actual_holding_minutes"] for r in rows])
    avail = [r for r in rows if r["hypothetical_H90"]["available"]]
    both = [r for r in avail if r["actual_sign"] != 0
            and r["hypothetical_H90"]["sign"] is not None]
    agree = [r for r in both
             if r["actual_sign"] == r["hypothetical_H90"]["sign"]]
    disagree = [r for r in both
                if r["actual_sign"] != r["hypothetical_H90"]["sign"]]

    summary = {
        "episodes": len(rows),
        "exit_reasons": {k: int(sum(1 for r in rows
                                    if r["actual_exit_reason"] == k))
                         for k in sorted({r["actual_exit_reason"] for r in rows})},
        "exits_before_H": int((held < hstar).sum()),
        "exits_at_or_after_H": int((held >= hstar).sum()),
        "H": hstar,
        "holding_minutes": {"min": int(held.min()), "median": float(np.median(held)),
                            "max": int(held.max()), "total": int(held.sum()),
                            "distribution": {str(int(v)): int((held == v).sum())
                                             for v in sorted(set(held.tolist()))}},
        "actual_sign_counts": {"positive": int(sum(1 for r in rows if r["actual_sign"] > 0)),
                               "negative": int(sum(1 for r in rows if r["actual_sign"] < 0)),
                               "zero": int(sum(1 for r in rows if r["actual_sign"] == 0))},
        "reinforcement_sign_counts": {
            "reward": int(sum(1 for r in rows if r["reinforcement_sign"] == 1)),
            "punishment": int(sum(1 for r in rows if r["reinforcement_sign"] == -1)),
            "none": int(sum(1 for r in rows if r["reinforcement_sign"] is None))},
        "hypothetical_label_availability": {
            "available": len(avail), "unavailable": len(rows) - len(avail),
            "reasons": {k: int(sum(1 for r in rows
                                   if not r["hypothetical_H90"]["available"]
                                   and r["hypothetical_H90"].get("reason") == k))
                        for k in sorted({r["hypothetical_H90"].get("reason")
                                         for r in rows
                                         if not r["hypothetical_H90"]["available"]})}},
        "hypothetical_label_counts": {
            "Y=1": int(sum(1 for r in avail if r["hypothetical_H90"]["label_Y"] == 1)),
            "Y=0": int(sum(1 for r in avail if r["hypothetical_H90"]["label_Y"] == 0))},
        "sign_comparison": {
            "compared": len(both), "agree": len(agree), "disagree": len(disagree),
            "proportion_disagreeing": (len(disagree) / len(both)) if both else None,
            "disagreements_by_actual_sign": {
                "actual_positive": int(sum(1 for r in disagree if r["actual_sign"] > 0)),
                "actual_negative": int(sum(1 for r in disagree if r["actual_sign"] < 0))},
            "agreements_by_actual_sign": {
                "actual_positive": int(sum(1 for r in agree if r["actual_sign"] > 0)),
                "actual_negative": int(sum(1 for r in agree if r["actual_sign"] < 0))}},
        "costs": {
            "executions": 2 * len(rows),
            "fee_bps_per_execution": fee_bps,
            "slippage_bps_per_execution": slip_bps,
            "round_trip_bps_nominal": 2.0 * (fee_bps + slip_bps),
            "total_fees": float(sum(r["actual_fees"] for r in rows)),
            "total_slippage": float(sum(r["actual_slippage"] for r in rows)),
            "total_cost": float(sum(r["actual_fees"] + r["actual_slippage"]
                                    for r in rows)),
            "total_gross_reference_pnl": float(
                sum(r["actual_gross_reference_pnl"] for r in rows)),
            "total_net_pnl": float(sum(r["actual_net_pnl"] for r in rows)),
            "episodes_whose_cost_exceeds_gross_reference":
                int(sum(1 for r in rows
                        if (r["actual_fees"] + r["actual_slippage"])
                        > r["actual_gross_reference_pnl"]))},
        "entry_fill_identity": fill_checks,
        "hypothetical_totals_note":
            "the hypothetical net outcomes are NOT summed into a portfolio PnL "
            "and are not booked anywhere; they are per-episode counterfactuals "
            "at the original entry times",
    }

    out = {
        "artifact": "flytrade-d8-alignment-1",
        "label": D.CONFIG["label"],
        "written_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_log": cfg["partitions"]["fitting"]["log"],
        "parser": "flytrade.records.EventLog.read",
        "H": hstar, "delay_minutes": delay,
        "costs_used": {"notional": notional, "fee_bps": fee_bps,
                       "slippage_bps": slip_bps,
                       "note": "the original constants, unchanged"},
        "caveat": cfg["alignment_audit"]["caveat"],
        "forbidden": cfg["alignment_audit"]["forbidden"],
        "summary": summary,
        "episodes": rows,
        "elapsed_s": round(time.time() - t0, 2),
    }
    JSON_OUT.write_text(json.dumps(out, indent=1))

    # ------------------------------------------------------------ markdown
    md = ["# D8 — target-alignment audit", "",
          f"**{D.CONFIG['label']}**", "",
          "The 42 actual LEARNING episodes of `d7-001`, beside the "
          f"fixed-H = {hstar} quantity D7's evaluation scored. "
          "Read from the event log through `flytrade.records` parsing only.",
          "",
          "> These counterfactuals reuse the original entry times. They do "
          "**not** simulate the trades a fixed-hold policy would actually have "
          "taken, because that policy changes inventory and later entry "
          "opportunities. Nothing here updates a weight, replays a reward, "
          "modifies an account or rewrites an original event, and no "
          "hypothetical outcome is booked as portfolio PnL. This audit "
          "measures **alignment**, not whether fixed-hold training would "
          "succeed.", "",
          "| episode | information cutoff | entry | exit | reason | held, min "
          "| actual gross | actual net | reinf. | hyp. net at H=90 | hyp. Y |",
          "|---|---|---|---|---|---:|---:|---:|:---:|---:|:---:|"]
    for r in rows:
        h = r["hypothetical_H90"]
        hyp_net = ("n/a (" + h["reason"] + ")" if not h["available"]
                   else f"{h['net_pnl']:+.4f}")
        hyp_y = "—" if not h["available"] else str(h["label_Y"])
        md.append(
            f"| {r['episode_id']} | {r['information_cutoff']} | "
            f"{r['entry_time']} | {r['actual_exit_time']} | "
            f"{r['actual_exit_reason']} | {r['actual_holding_minutes']} | "
            f"{r['actual_gross_pnl']:+.4f} | {r['actual_net_pnl']:+.4f} | "
            f"{'+' if r['reinforcement_sign'] == 1 else '−'} | {hyp_net} | "
            f"{hyp_y} |")
    s = summary
    md += ["", "## Summary", "",
           f"* **Episodes**: {s['episodes']}. Exit reasons: "
           f"{s['exit_reasons']}.",
           f"* **Exits before H = {hstar}**: {s['exits_before_H']} of "
           f"{s['episodes']}; at or after H: {s['exits_at_or_after_H']}.",
           f"* **Actual holding minutes**: min {s['holding_minutes']['min']}, "
           f"median {s['holding_minutes']['median']}, max "
           f"{s['holding_minutes']['max']}, total "
           f"{s['holding_minutes']['total']}.",
           f"* **Actual outcome signs**: {s['actual_sign_counts']}. "
           f"Reinforcement: {s['reinforcement_sign_counts']}.",
           f"* **Hypothetical-label availability**: "
           f"{s['hypothetical_label_availability']['available']} available, "
           f"{s['hypothetical_label_availability']['unavailable']} not "
           f"({s['hypothetical_label_availability']['reasons']}). Label "
           f"counts {s['hypothetical_label_counts']}.",
           f"* **Actual versus fixed-H signs**: "
           f"{s['sign_comparison']['compared']} compared, "
           f"{s['sign_comparison']['agree']} agree, "
           f"{s['sign_comparison']['disagree']} disagree — proportion "
           f"disagreeing "
           f"{s['sign_comparison']['proportion_disagreeing']:.4f}. "
           f"Disagreements by actual sign: "
           f"{s['sign_comparison']['disagreements_by_actual_sign']}; "
           f"agreements: "
           f"{s['sign_comparison']['agreements_by_actual_sign']}.",
           f"* **Costs**: {s['costs']['executions']} executions at "
           f"{s['costs']['fee_bps_per_execution']} bps fee + "
           f"{s['costs']['slippage_bps_per_execution']} bps slippage each "
           f"({s['costs']['round_trip_bps_nominal']} bps nominal per round "
           f"trip); fees {s['costs']['total_fees']:.4f}, slippage "
           f"{s['costs']['total_slippage']:.4f}, total cost "
           f"{s['costs']['total_cost']:.4f} against a gross at reference "
           f"prices of {s['costs']['total_gross_reference_pnl']:+.4f} and a "
           f"net of {s['costs']['total_net_pnl']:+.4f}. Cost exceeded gross in "
           f"{s['costs']['episodes_whose_cost_exceeds_gross_reference']} of "
           f"{s['episodes']} episodes.",
           f"* **Entry-fill identity**: the hypothetical entry equals the "
           f"actual entry on "
           f"{s['entry_fill_identity']['reference_price_equal']} of "
           f"{s['entry_fill_identity']['compared']} episodes at the reference "
           f"price and "
           f"{s['entry_fill_identity']['slipped_fill_equal']} of "
           f"{s['entry_fill_identity']['compared']} after the unchanged "
           f"slippage; max |difference| "
           f"{s['entry_fill_identity']['max_abs_diff']:.2e}.",
           f"* The hypothetical net outcomes are **not** summed into a "
           f"portfolio PnL and are booked nowhere.", ""]
    MD_OUT.write_text("\n".join(md))

    print(f"episodes {s['episodes']}  exits before H {s['exits_before_H']}  "
          f"held min/median/max {s['holding_minutes']['min']}/"
          f"{s['holding_minutes']['median']}/{s['holding_minutes']['max']}")
    print(f"reinforcement {s['reinforcement_sign_counts']}  actual signs "
          f"{s['actual_sign_counts']}")
    print(f"hypothetical labels {s['hypothetical_label_availability']} "
          f"{s['hypothetical_label_counts']}")
    print(f"sign comparison {s['sign_comparison']}")
    print(f"costs total {s['costs']['total_cost']:.4f} vs gross reference "
          f"{s['costs']['total_gross_reference_pnl']:+.4f}, net "
          f"{s['costs']['total_net_pnl']:+.4f}")
    print(f"entry-fill identity {s['entry_fill_identity']}")
    print(f"ok in {out['elapsed_s']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
