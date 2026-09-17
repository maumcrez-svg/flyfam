#!/usr/bin/env python
"""
The D9(b) target-alignment invariant — amendment §3.

    .venv/bin/python experiments/d9b/alignment.py

For every completed exact-H episode of every branch, the realised net outcome
is set beside the evaluator's corresponding fixed-H label, computed from the
same price file by :func:`flytrade.horizon.hold` — the same primitive
:class:`flytrade.historical.HistoricalExecution` locates its own fills with.
The amendment asks for one target definition; this is the number that says
whether there is one.

Two precisions are reported, because there are two:

* **realised** — the unrounded ``net_pnl`` the execution policy booked, taken
  from the ``outcomes_full_precision`` records ``run.py`` writes. The plan's
  tolerance of 1e-9 applies here.
* **as recorded** — the same quantity read back from ``events.jsonl``, where
  ``OutcomeRecord.as_dict`` rounds it to 8 decimals. Half of the last recorded
  digit is 5e-9, so a comparison at that precision cannot be tighter, and
  saying so is not the same as loosening the invariant.

Exceptional closures — ``SESSION_CLOSE_FILL``, ``END_OF_DATA``, a session
boundary reached before the horizon — are listed and counted **apart**. They
keep their accounting and are never presented as exact-H outcomes.

Nothing here books a number, moves a weight, touches an account or rewrites an
event. Writes ``withheld d9b alignment table`` and ``alignment.md``.
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from flytrade import historical as H                 # noqa: E402
from flytrade import horizon as HZ                   # noqa: E402
from flytrade import records as REC                  # noqa: E402

CONFIG = HERE / "config.json"
RUNS = HERE / "runs"
JSON_OUT = HERE / "alignment.json"
MD_OUT = HERE / "alignment.md"

#: the closure that means "the declared horizon expired, exactly"
EXACT = "POLICY_CLOSE_FIXED_HOLD"
#: everything else a position can end with, counted apart
EXCEPTIONAL = ("POLICY_CLOSE", "END_OF_DATA", "NEURAL_SELL")


def et(ts: int) -> str:
    return H.ny_datetime(int(ts)).strftime("%Y-%m-%d %H:%M ET")


def chains(log_path: Path, partition: str) -> dict:
    """``{episode_id: {kind: event}}`` for the chains inside one partition."""
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
    return out


def decision_tally(log_path: Path, partition: str) -> dict:
    """What the decoder did, and what the execution policy did with it."""
    c = Counter()
    inside = False
    for e in REC.EventLog(log_path).read():
        k = e.get("kind")
        if k == "PARTITION" and e.get("partition") == partition:
            inside = e.get("boundary") == "start"
            continue
        if not inside:
            continue
        c[f"kind:{k}"] += 1
        if k != "DECISION":
            continue
        c[f"action:{e.get('decoded_action')}"] += 1
        c[f"status:{e.get('readout_status')}"] += 1
        rj = (e.get("rejection") or {}).get("reason")
        if rj:
            c[f"rejected:{rj}"] += 1
    return dict(c)


def branch_rows(series, cfg, chain, outcomes_fp, hstar, delay, notional,
                fee_bps, slip_bps):
    """One row per completed episode, realised beside the label."""
    rows = []
    by_ep = {int(o["episode_id"]): o for o in outcomes_fp}
    for eid in sorted(by_ep):
        o = by_ep[eid]
        c = chain.get(eid, {})
        dec, lrn = c.get("DECISION"), c.get("LEARNING")
        logged = c.get("OUTCOME") or {}
        day = H.session_date(int(o["entry_ts"]))
        dm = (int(dec["bar_index"]) if dec is not None
              else int(o["entry_minute"]) - delay)
        exact = o["close_reason"] == EXACT

        h = HZ.hold(series, day, dm, hstar, delay=delay)
        label = None
        if h.ok:
            label = {
                "available": True,
                "entry_minute": h.entry_minute, "exit_minute": h.exit_minute,
                "entry_open": float(h.entry_open),
                "exit_open": float(h.exit_open),
                "exit_time": et(h.exit_ts),
                "gross_bps": float(h.gross_bps),
                "net_pnl": float(h.net_pnl(notional=notional, fee_bps=fee_bps,
                                           slippage_bps=slip_bps)),
                "Y": None}
            label["Y"] = int(label["net_pnl"] > 0.0)
        else:
            label = {"available": False, "reason": h.reason, "net_pnl": None,
                     "Y": None}

        d_live = d_logged = None
        same_bars = None
        if label["available"]:
            d_live = abs(label["net_pnl"] - float(o["net_pnl"]))
            if "net_pnl" in logged:
                d_logged = abs(label["net_pnl"] - float(logged["net_pnl"]))
            same_bars = (label["entry_minute"] == int(o["entry_minute"])
                         and label["exit_minute"] == int(o["exit_minute"]))

        rows.append({
            "episode_id": eid,
            "session": str(day),
            "decision_minute": dm,
            "information_cutoff": et(int(dec["cutoff_ts"])) if dec else None,
            "entry_time": et(int(o["entry_ts"])),
            "entry_minute": int(o["entry_minute"]),
            "exit_time": et(int(o["exit_ts"])),
            "exit_minute": int(o["exit_minute"]),
            "close_reason": o["close_reason"],
            "exact_h": exact,
            "entry_flag": o["entry_flag"], "exit_flag": o["exit_flag"],
            "market_minutes_held": int(o["market_minutes_held"]),
            "entry_reference_price": o["entry_reference_price"],
            "exit_reference_price": o["exit_reference_price"],
            "gross_reference_pnl": o["gross_reference_pnl"],
            "fees": o["fees"], "slippage": o["slippage"],
            "net_pnl": o["net_pnl"],
            "net_pnl_as_recorded": logged.get("net_pnl"),
            "return_on_notional": o["return_on_notional"],
            "sign": int(np.sign(o["net_pnl"])),
            "reinforcement_sign": (int(lrn["valence"]) if lrn else None),
            "reinforcement_amount": (float(lrn["amount"]) if lrn else None),
            "reinforcement_accepted": (bool(lrn["accepted"]) if lrn else None),
            "synapses_depressed": (int(lrn.get("synapses_depressed", 0))
                                   if lrn else None),
            "settlement": logged.get("settlement"),
            "label_H": label,
            "same_bars_as_label": same_bars,
            "abs_diff_realised": d_live,
            "abs_diff_as_recorded": d_logged,
        })
    return rows


def summarise(rows, hstar, tol):
    exact = [r for r in rows if r["exact_h"]]
    other = [r for r in rows if not r["exact_h"]]
    available = [r for r in exact if r["abs_diff_realised"] is not None]
    # the invariant's own precondition is "for the same entry": an episode
    # whose entry landed on a different bar than the label's — the sequencing
    # guard, or a vendor gap — is named and counted, never averaged in.
    comparable = [r for r in available if r["same_bars_as_label"]]
    displaced = [r for r in available if not r["same_bars_as_label"]]
    dl = [r["abs_diff_realised"] for r in comparable]
    dr = [r["abs_diff_as_recorded"] for r in comparable
          if r["abs_diff_as_recorded"] is not None]
    held = np.array([r["market_minutes_held"] for r in rows]) if rows \
        else np.array([0])
    return {
        "episodes": len(rows),
        "exact_h_closures": len(exact),
        "exceptional_closures": len(other),
        "exceptional_by_reason": {k: sum(1 for r in other
                                         if r["close_reason"] == k)
                                  for k in sorted({r["close_reason"]
                                                   for r in other})},
        "exceptional_by_flag": {k: sum(1 for r in other
                                       if r["exit_flag"] == k)
                                for k in sorted({r["exit_flag"]
                                                 for r in other})},
        "invariant": {
            "statement": "for the same entry and valid price availability, "
                         "the realised net fixed-hold outcome equals the "
                         "evaluator's corresponding net label",
            "compared": len(comparable),
            "label_unavailable": len(exact) - len(available),
            "same_entry_and_exit_bars": len(comparable),
            "different_bars_from_the_label": len(displaced),
            "different_bars_detail": [
                {"episode_id": r["episode_id"], "session": r["session"],
                 "decision_minute": r["decision_minute"],
                 "entry_minute": r["entry_minute"],
                 "label_entry_minute": r["label_H"]["entry_minute"],
                 "exit_minute": r["exit_minute"],
                 "label_exit_minute": r["label_H"]["exit_minute"],
                 "entry_flag": r["entry_flag"], "exit_flag": r["exit_flag"],
                 "abs_diff_realised": r["abs_diff_realised"]}
                for r in displaced],
            "tolerance": tol,
            "max_abs_diff_realised": (max(dl) if dl else None),
            "max_abs_diff_as_recorded": (max(dr) if dr else None),
            "holds": (bool(dl) and max(dl) <= tol) if comparable else None,
            "recorded_precision_note":
                "the event log rounds net_pnl to 8 decimals, so a comparison "
                "read back from it cannot be tighter than 5e-9",
        },
        "holding_minutes": {
            "H": hstar,
            "min": int(held.min()), "max": int(held.max()),
            "median": float(np.median(held)), "total": int(held.sum()),
            "exactly_H": int((held == hstar).sum()),
            "below_H": int((held < hstar).sum()),
            "above_H": int((held > hstar).sum()),
            "distribution": {str(int(v)): int((held == v).sum())
                             for v in sorted(set(held.tolist()))}},
        "sign_counts": {
            "positive": sum(1 for r in rows if r["sign"] > 0),
            "negative": sum(1 for r in rows if r["sign"] < 0),
            "zero": sum(1 for r in rows if r["sign"] == 0)},
        "reinforcement": {
            "reward": sum(1 for r in rows if r["reinforcement_sign"] == 1),
            "punishment": sum(1 for r in rows if r["reinforcement_sign"] == -1),
            "none": sum(1 for r in rows if r["reinforcement_sign"] is None),
            "accepted": sum(1 for r in rows if r["reinforcement_accepted"]),
            "settled_frozen": sum(1 for r in rows
                                  if r["settlement"] == "SETTLED_FROZEN")},
        "label_sign_counts": {
            "Y=1": sum(1 for r in rows
                       if (r["label_H"] or {}).get("Y") == 1),
            "Y=0": sum(1 for r in rows
                       if (r["label_H"] or {}).get("Y") == 0),
            "unavailable": sum(1 for r in rows
                               if not (r["label_H"] or {}).get("available"))},
        "money": {
            "executions": 2 * len(rows),
            "gross_reference_pnl": sum(r["gross_reference_pnl"] for r in rows),
            "fees": sum(r["fees"] for r in rows),
            "slippage": sum(r["slippage"] for r in rows),
            "net_pnl": sum(r["net_pnl"] for r in rows),
            "cost_exceeded_gross": sum(
                1 for r in rows
                if r["fees"] + r["slippage"] > abs(r["gross_reference_pnl"]))},
    }


def main() -> int:
    t0 = time.time()
    cfg = json.loads(CONFIG.read_text())
    hstar = int(cfg["horizon"]["H"])
    delay = int(cfg["execution"]["delay_minutes"])
    notional = float(cfg["execution"]["notional"])
    fee_bps = float(cfg["execution"]["fee_bps"])
    slip_bps = float(cfg["execution"]["slippage_bps"])
    tol = float(cfg["target_alignment_invariant"]["tolerance_net_pnl"])

    path = ROOT / "data" / "market" / cfg["instruments"][0]["file"]
    series = H.load_series(path, cfg["instruments"][0]["symbol"])

    learn = json.loads((HERE / "learning_summary.json").read_text())
    frozen = json.loads((HERE / "frozen_summary.json").read_text())
    run_id = learn["run_id"]
    if frozen["run_id"] != run_id:
        raise SystemExit("the two summaries are for different runs")

    branches = [("learned", "LEARNING", learn),
                ("frozen_trained", "FROZEN", frozen),
                ("frozen_reference", "FROZEN", frozen)]
    out = {"artifact": "flytrade-d9b-alignment-1",
           "wave": "D9(b)", "label": cfg["label"],
           "exit_policy": cfg["exit_policy"],
           "run_id": run_id, "H": hstar, "delay_minutes": delay,
           "written_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "tolerance_net_pnl": tol,
           "primitive": "flytrade.horizon.hold / locate, the same primitive "
                        "HistoricalExecution locates its fills with",
           "branches": {}}

    for name, part, summary in branches:
        log = RUNS / run_id / name / "events.jsonl"
        b = summary["branches"][name]
        rows = branch_rows(series, cfg, chains(log, part),
                           b["outcomes_full_precision"], hstar, delay,
                           notional, fee_bps, slip_bps)
        out["branches"][name] = {
            "partition": part,
            "log_sha256": b["log_sha256"],
            "exit_policy": b.get("exit_policy"),
            "episodes": rows,
            "summary": summarise(rows, hstar, tol),
            "decision_tally": decision_tally(log, part),
            "after_execution_constraints": b["partitions"][part]["tally"][
                "after_execution_constraints"]}

    allrows = [r for v in out["branches"].values() for r in v["episodes"]]
    out["all_branches"] = summarise(allrows, hstar, tol)
    out["elapsed_s"] = round(time.time() - t0, 2)
    JSON_OUT.write_text(json.dumps(out, indent=1))

    # ---- the human-readable table -------------------------------------
    L = []
    L.append(f"# D9(b) — target-alignment invariant ({run_id})\n")
    L.append("**RETROSPECTIVE COMPARISON ON PREVIOUSLY EXAMINED DATES.** "
             "Nothing here books a number, moves a weight or rewrites an "
             "event.\n")
    L.append(f"Anchor: the **entry fill minute** + H = {hstar} market "
             f"minutes, located by `flytrade.horizon.locate` — the one "
             f"primitive the executed exit and the evaluator's `Hold` both "
             f"call. Delay {delay} market minute, unchanged.\n")
    for name, v in out["branches"].items():
        s = v["summary"]
        inv = s["invariant"]
        L.append(f"\n## {name} ({v['partition']})\n")
        L.append(f"* episodes **{s['episodes']}**, exact-H closures "
                 f"**{s['exact_h_closures']}**, exceptional "
                 f"**{s['exceptional_closures']}** "
                 f"{s['exceptional_by_reason'] or ''}")
        L.append(f"* invariant compared on **{inv['compared']}** episodes, "
                 f"same entry and exit bars on "
                 f"**{inv['same_entry_and_exit_bars']}**, "
                 f"max |realised − label| = **{inv['max_abs_diff_realised']}** "
                 f"(tolerance {inv['tolerance']}), "
                 f"max |as recorded − label| = "
                 f"{inv['max_abs_diff_as_recorded']}")
        L.append(f"* holding minutes: min {s['holding_minutes']['min']}, "
                 f"median {s['holding_minutes']['median']}, max "
                 f"{s['holding_minutes']['max']}, exactly H "
                 f"{s['holding_minutes']['exactly_H']}")
        L.append(f"* outcomes {s['sign_counts']}, reinforcement "
                 f"{s['reinforcement']}")
        L.append(f"* money: gross at reference "
                 f"{s['money']['gross_reference_pnl']:+.4f}, fees "
                 f"{s['money']['fees']:.4f}, slippage "
                 f"{s['money']['slippage']:.4f}, net "
                 f"{s['money']['net_pnl']:+.4f}\n")
        if not v["episodes"]:
            L.append("_no completed episode in this branch._\n")
            continue
        L.append("| episode | session | dec | entry | exit | held | reason | "
                 "net | label | \\|diff\\| |")
        L.append("|---|---|---|---|---|---|---|---|---|---|")
        for r in v["episodes"]:
            lab = r["label_H"]
            ln = ("—" if not lab["available"]
                  else f"{lab['net_pnl']:+.6f}")
            df = ("—" if r["abs_diff_realised"] is None
                  else f"{r['abs_diff_realised']:.2e}")
            L.append(f"| {r['episode_id']} | {r['session']} | "
                     f"{r['decision_minute']} | {r['entry_minute']} | "
                     f"{r['exit_minute']} | {r['market_minutes_held']} | "
                     f"{r['close_reason']}{'/' + r['exit_flag'] if r['exit_flag'] else ''} | "
                     f"{r['net_pnl']:+.6f} | {ln} | {df} |")
        L.append("")
    MD_OUT.write_text("\n".join(L) + "\n")

    a = out["all_branches"]
    print(f"episodes {a['episodes']}  exact-H {a['exact_h_closures']}  "
          f"exceptional {a['exceptional_closures']} "
          f"{a['exceptional_by_reason']}")
    print(f"invariant: compared {a['invariant']['compared']}, max |diff| "
          f"realised {a['invariant']['max_abs_diff_realised']}, as recorded "
          f"{a['invariant']['max_abs_diff_as_recorded']}, holds "
          f"{a['invariant']['holds']}")
    print(f"holding minutes {a['holding_minutes']}")
    print(f"reinforcement {a['reinforcement']}  signs {a['sign_counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
