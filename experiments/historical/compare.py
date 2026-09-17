#!/usr/bin/env python
"""
The learned-versus-reference comparison — D6 §6, from the two event logs.

    .venv/bin/python experiments/historical/compare.py [run_id]

Reads `summary.json` and the two branches' canonical `events.jsonl`, and writes
`comparison.json`. It computes nothing the run did not already record: every
figure here is a count of events, or a sum of a money field the execution
policy itself booked and wrote.

What it reports, for both branches, without choosing a winner:

* readout status and action distributions at all three denominators;
* completed trades, exposure in market minutes, delayed and session-close
  fills;
* gross at reference prices, slippage, fees and net, with the residual;
* the same, per instrument;
* and the one check that makes the comparison a *paired* one: that the
  `comparison_v1` schedule handed both branches the **same seed** for the same
  (observation, instrument, replicate) even though their learned weights
  differ.

The untrained reference is not a full test against chance, and nothing here is
a claim of trading skill. No profitability requirement is part of the gate.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"


def events(run_id: str, branch: str, partition: str | None = None):
    log = RUNS / run_id / branch / "events.jsonl"
    span = None
    if partition:
        lo = hi = None
        with open(log, encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if '"PARTITION"' not in line:
                    continue
                e = json.loads(line)
                if e.get("partition") != partition:
                    continue
                if e.get("boundary") == "start":
                    lo = i
                else:
                    hi = i
        span = (lo, hi)
    with open(log, encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if span and (i < span[0] or (span[1] is not None and i > span[1])):
                continue
            line = line.strip()
            if line:
                yield json.loads(line)


def branch_report(run_id: str, branch: str, partition: str) -> dict:
    status = Counter()
    action = Counter()
    per_instrument = defaultdict(Counter)
    close_reasons = Counter()
    flags = Counter()
    settlement = Counter()
    seeds: dict[tuple, int] = {}
    money = dict(gross_reference_pnl=0.0, slippage=0.0, fees=0.0, net_pnl=0.0)
    trades = 0
    exposure = 0
    held_minutes = 0
    holding = False
    rounds = 0
    silent = presentations = batches = 0
    learning_events = 0
    accepted = 0
    depressed = 0
    account = None

    for e in events(run_id, branch, partition):
        k = e.get("kind")
        if k == "ROUND":
            rounds += 1
            for c in e.get("candidates", []):
                if c.get("status") == "OK":
                    batches += 1
                    presentations += int(c.get("k", 0))
                    silent += int(c.get("silent_replicates", 0))
            if holding:
                exposure += 1
        elif k == "DECISION":
            status[e["readout_status"]] += 1
            action[e["decoded_action"]] += 1
            per_instrument[e["symbol"]][e["readout_status"]] += 1
            per_instrument[e["symbol"]]["action:" + e["decoded_action"]] += 1
            seeds[(e["market_ts"], e["symbol"])] = e["seed"]
        elif k == "EXECUTION":
            holding = True
            if e.get("flag"):
                flags[e["flag"]] += 1
        elif k == "OUTCOME":
            holding = False
            trades += 1
            close_reasons[e.get("close_reason", "?")] += 1
            if e.get("exit_flag"):
                flags[e["exit_flag"]] += 1
            settlement[e.get("settlement", "SETTLED_WITH_LEARNING")] += 1
            held_minutes += int(e.get("market_minutes_held", 0) or 0)
            for f in money:
                money[f] += float(e.get(f, 0.0))
            per_instrument[e["symbol"]]["trades"] += 1
            per_instrument[e["symbol"]]["net_pnl"] = round(
                per_instrument[e["symbol"]].get("net_pnl", 0.0)
                + float(e["net_pnl"]), 8)
            account = e.get("account")
        elif k == "LEARNING":
            learning_events += 1
            if e.get("accepted"):
                accepted += 1
                depressed += int(e.get("synapses_depressed", 0) or 0)

    residual = (money["gross_reference_pnl"] - money["fees"]
                - money["slippage"] - money["net_pnl"])
    return {
        "run_id": run_id, "branch": branch, "partition": partition,
        "rounds": rounds,
        "candidate_evaluations": batches,
        "presentations": presentations,
        "silent_presentations": silent,
        "readout_status_per_round": dict(status),
        "action_per_round": dict(action),
        "per_instrument": {s: dict(c) for s, c in per_instrument.items()},
        "trades": trades,
        "rounds_while_holding": exposure,
        "exposure_market_minutes": held_minutes,
        "close_reasons": dict(close_reasons),
        "fill_flags": dict(flags),
        "settlement": dict(settlement),
        "learning_events": learning_events,
        "learning_accepted": accepted,
        "synapses_depressed_total": depressed,
        "money": {k: round(v, 6) for k, v in money.items()},
        "reconciliation_residual": round(residual, 9),
        "final_account": account,
        "seeds": seeds,
    }


def main(argv) -> int:
    run_id = argv[1] if len(argv) > 1 else None
    path = HERE / "summary.json"
    if not path.exists() and run_id:
        path = RUNS / run_id / "smoke_summary.json"
    summary = json.loads(path.read_text())
    run_id = run_id or summary["run_id"]
    learned = branch_report(run_id, "learned", "FROZEN")
    reference = branch_report(run_id, "reference", "FROZEN")

    shared = set(learned["seeds"]) & set(reference["seeds"])
    same = sum(1 for k in shared
               if learned["seeds"][k] == reference["seeds"][k])
    pairing = {
        "schedule": "comparison_v1",
        "shared_observation_instrument_pairs": len(shared),
        "identical_seed": same,
        "differing_seed": len(shared) - same,
        "learned_only": len(set(learned["seeds"]) - shared),
        "reference_only": len(set(reference["seeds"]) - shared),
        "paired": same == len(shared) and len(shared) > 0,
    }
    for b in (learned, reference):
        b.pop("seeds")

    out = {
        "run_id": run_id,
        "partition": "FROZEN",
        "window": summary["config"]["partitions"]["FROZEN"],
        "seed_pairing": pairing,
        "learned": learned,
        "reference": reference,
        "learned_start_digest":
            summary["branches"]["learned"]["partitions"]["FROZEN"]["start_digest"],
        "learned_end_digest":
            summary["branches"]["learned"]["partitions"]["FROZEN"]["end_digest"],
        "reference_start_digest":
            summary["branches"]["reference"]["partitions"]["FROZEN"]["start_digest"],
        "reference_end_digest":
            summary["branches"]["reference"]["partitions"]["FROZEN"]["end_digest"],
        "clean_reference_digest": summary["clean_reference_digest"],
        "caveats": [
            "The untrained reference is not a full test against chance.",
            "One five-session window establishes no trading skill.",
            "No profitability requirement is part of the engineering gate; "
            "net PnL is not a gate metric in either direction.",
            "Both branches ran the same observations, the same baseline "
            "artifact, the same paper policy and the same comparison_v1 "
            "seeds; the only difference is the learned weights.",
        ],
    }
    (HERE / "comparison.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items()
                      if k not in ("learned", "reference")}, indent=1))
    for b in (learned, reference):
        print(f"\n{b['branch']:>10}: rounds {b['rounds']:,}  "
              f"decisions {sum(b['action_per_round'].values()):,}  "
              f"trades {b['trades']}  exposure "
              f"{b['exposure_market_minutes']} market minutes")
        print(f"{'':>10}  actions {b['action_per_round']}")
        print(f"{'':>10}  statuses {b['readout_status_per_round']}")
        print(f"{'':>10}  money {b['money']}  residual "
              f"{b['reconciliation_residual']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
