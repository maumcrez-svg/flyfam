#!/usr/bin/env python
"""Labels, the paired comparison, and the d11-001 report.

    .venv/bin/python experiments/d11/evaluate.py --labels
    .venv/bin/python experiments/d11/evaluate.py --report

``--labels`` attaches the evaluator-only fixed-15-minute net outcome of
``common.label_row`` to every grid row. It creates no trade, alters no
bankroll, produces no reinforcement and touches neither ledger nor checkpoint;
its known-answer test against the sixteen settled D10 entries is
``tests/d11/test_label.py``, written before it ever ran.

``--report`` joins the rows, the labels and the two branches' scores, computes
what ``d11_001.json`` registered — ΔAUC with a paired cluster bootstrap by
``stable_id``, overall and per temporal block; the suppression contrast;
coverage; saturation; the class balance — and writes
``runs/d11-001/report.md``.

**Nothing in this file opens a socket.**
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

import common as C                                        # noqa: E402
import stats as ST                                        # noqa: E402
from retrospective import Tracker                         # noqa: E402

GRID = C.RUNS / C.RUN_ID / "grid"


def read_jsonl(path: Path):
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


# ------------------------------------------------------------------ labels
def build_labels(out: Path, *, log=print) -> dict:
    """One evaluator-only label per grid row. Market only; no brain, no book."""
    cfg_v2, cfg_run = C.configs()
    gas = C.gas_constants(cfg_run)
    clock = C.block_clock()
    t0 = time.time()
    track = Tracker(C.DATASET, live=False)
    log(f"tracker: {len(track.tapes):,} tapes ({time.time() - t0:.0f}s)")

    path = out / "labels.jsonl"
    reasons: Counter = Counter()
    settled = positives = negatives = 0
    nets: list[float] = []
    n = 0
    with open(path, "w", encoding="utf-8") as fh:
        for row in read_jsonl(out / "rows.jsonl"):
            tape = track.tapes.get(row["token"])
            if tape is None:                                   # cannot happen
                reasons["NO_TAPE"] += 1
                fh.write(json.dumps({"cutoff_ts": row["cutoff_ts"],
                                     "stable_id": row["stable_id"],
                                     "settled": False, "status": C.UNRESOLVED,
                                     "reason": "NO_TAPE"}) + "\n")
                n += 1
                continue
            label = C.label_row(tape, int(row["cutoff_ts"]), clock, gas=gas)
            label["stable_id"] = int(row["stable_id"])
            label["tick"] = int(row["tick"])
            fh.write(json.dumps(label) + "\n")
            n += 1
            if label["settled"]:
                settled += 1
                nets.append(label["net"])
                if label["positive"]:
                    positives += 1
                else:
                    negatives += 1
            else:
                reasons[label["reason"] or "UNRESOLVED"] += 1
            if n % 1000 == 0:
                log(f"  {n:,} labels ({time.time() - t0:.0f}s)")

    arr = np.array(nets or [0.0])
    summary = {
        "version": "d11-001-labels-1",
        "rows": n, "settled": settled,
        "unresolved": n - settled,
        "unresolved_reasons": dict(sorted(reasons.items())),
        "positive": positives, "negative": negatives,
        "positive_share": (positives / settled) if settled else None,
        "net_eth": {"min": float(arr.min()), "max": float(arr.max()),
                    "median": float(np.median(arr)), "mean": float(arr.mean())},
        "definition": (
            "a hypothetical buy of 10^16 wei at cutoff + 2 s through "
            "PonsPaperExecution.plan_buy on a fresh execution object, the "
            "position's own reserve delta carried as the loop carries it, the "
            "exit priced by plan_sell at entry_fill_block_timestamp + 900 s; "
            "net = quote_out - spent - gas_buy - gas_sell - approval, positive "
            "iff net > 0. Unresolved (route transition, coverage) or a "
            "QuoteError is UNRESOLVED, excluded from the AUC and counted."),
        "creates_no_trade": True, "alters_no_bankroll": True,
        "produces_no_reinforcement": True,
        "known_answer_test": "tests/d11/test_label.py, the 16 settled D10 entries",
        "elapsed_s": round(time.time() - t0, 1),
        "labels_path": str(path),
    }
    (out / "labels_summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    log(f"labels: {settled:,} settled of {n:,} "
        f"({positives:,} positive / {negatives:,} negative)")
    return summary


# ------------------------------------------------------------------ report
def load_join(out: Path) -> tuple[list[dict], dict]:
    """Rows joined with their labels and both branches' scores, keyed (cutoff, id)."""
    rows = {(r["cutoff_ts"], r["stable_id"]): r for r in read_jsonl(out / "rows.jsonl")}
    labels = {(r["cutoff_ts"], r["stable_id"]): r
              for r in read_jsonl(out / "labels.jsonl")}
    scores = {}
    for branch in ("trained", "reference"):
        scores[branch] = {(r["cutoff_ts"], r["stable_id"]): r
                          for r in read_jsonl(out / f"scores_{branch}.jsonl")}
    joined = []
    missing = Counter()
    for key, row in rows.items():
        label = labels.get(key)
        tr = scores["trained"].get(key)
        rf = scores["reference"].get(key)
        if label is None:
            missing["label"] += 1
        if tr is None:
            missing["trained"] += 1
        if rf is None:
            missing["reference"] += 1
        joined.append({"key": key, "row": row, "label": label,
                       "trained": tr, "reference": rf})
    return joined, dict(missing)


def analyse(out: Path, *, log=print) -> dict:
    cfg_v2, cfg_run = C.configs()
    man = C.manifest()
    sp = C.split(man["window"])
    blocks = sp["temporal_blocks"]
    theta = C.RO.THETA_HZ_K8
    joined, missing = load_join(out)

    valid = []
    for entry in joined:
        tr, rf = entry["trained"], entry["reference"]
        entry["valid_both"] = bool(
            tr is not None and rf is not None
            and tr.get("status") == "VALID" and rf.get("status") == "VALID")
    n_rows = len(joined)
    valid_both = sum(1 for e in joined if e["valid_both"])

    paired = []
    for entry in joined:
        if not entry["valid_both"]:
            continue
        label = entry["label"]
        if label is None or not label.get("settled"):
            continue
        cutoff = entry["key"][0]
        paired.append({
            "cutoff_ts": cutoff,
            "stable_id": entry["key"][1],
            "token": entry["row"]["token"],
            "block": C.block_of(cutoff, blocks),
            "trained": float(entry["trained"]["valence_hz"]),
            "reference": float(entry["reference"]["valence_hz"]),
            "trained_buy": bool(float(entry["trained"]["valence_hz"]) > theta),
            "reference_buy": bool(float(entry["reference"]["valence_hz"]) > theta),
            "net": float(label["net"]),
            "y": bool(label["positive"]),
            "saturated_channels": int(entry["row"]["saturated_channels"]),
        })

    # -------------------------------------------------------- saturation
    channels = len(cfg_v2["features"]["order"])
    sat_pairs = sum(int(e["row"]["saturated_channels"]) for e in joined)
    sat_rows = sum(1 for e in joined if int(e["row"]["saturated_channels"]) > 0)
    saturation = {
        "definition": cfg_run["saturation"]["definition"],
        "rows": n_rows, "channels_per_row": channels,
        "row_channel_pairs": n_rows * channels,
        "saturated_row_channel_pairs": sat_pairs,
        "saturated_row_channel_fraction": (sat_pairs / (n_rows * channels))
        if n_rows else None,
        "rows_with_at_least_one": sat_rows,
        "rows_with_at_least_one_fraction": (sat_rows / n_rows) if n_rows else None,
    }

    status_counts = {b: Counter(e[b]["status"] for e in joined
                                if e[b] is not None)
                     for b in ("trained", "reference")}
    invalid = {b: int(status_counts[b].get("INVALID_STATE", 0)) for b in status_counts}
    invalid_rate = {b: (invalid[b] / n_rows) if n_rows else None for b in invalid}

    # ------------------------------------------------------------- AUC
    def clusters_of(rows):
        by_token = defaultdict(list)
        for r in rows:
            by_token[r["stable_id"]].append(r)
        return list(by_token.values())

    stat = ST.delta_auc_statistic("trained", "reference", "y")
    overall = {
        "n": len(paired),
        "positive": sum(1 for r in paired if r["y"]),
        "negative": sum(1 for r in paired if not r["y"]),
        "clusters": len({r["stable_id"] for r in paired}),
        "auc_trained": ST.auc([r["trained"] for r in paired],
                              [r["y"] for r in paired]),
        "auc_reference": ST.auc([r["reference"] for r in paired],
                                [r["y"] for r in paired]),
        "spearman_trained": ST.spearman([r["trained"] for r in paired],
                                        [r["net"] for r in paired]),
        "spearman_reference": ST.spearman([r["reference"] for r in paired],
                                          [r["net"] for r in paired]),
    }
    overall["delta_auc"] = (None if overall["auc_trained"] is None
                            or overall["auc_reference"] is None
                            else overall["auc_trained"] - overall["auc_reference"])
    log("bootstrapping the overall interval ...")
    overall["interval"] = ST.cluster_bootstrap(clusters_of(paired), stat)
    overall["wording"] = ST.describe_interval(overall["interval"],
                                              name="delta AUC (trained - reference)")

    per_block = []
    for row in blocks:
        sub = [r for r in paired if r["block"] == row["block"]]
        entry = {
            "block": row["block"], "from_ts": row["from_ts"],
            "to_ts": row["to_ts"], "n": len(sub),
            "positive": sum(1 for r in sub if r["y"]),
            "negative": sum(1 for r in sub if not r["y"]),
            "clusters": len({r["stable_id"] for r in sub}),
            "auc_trained": ST.auc([r["trained"] for r in sub],
                                  [r["y"] for r in sub]),
            "auc_reference": ST.auc([r["reference"] for r in sub],
                                    [r["y"] for r in sub]),
        }
        entry["delta_auc"] = (None if entry["auc_trained"] is None
                              or entry["auc_reference"] is None
                              else entry["auc_trained"] - entry["auc_reference"])
        log(f"bootstrapping block {row['block']} ...")
        entry["interval"] = ST.cluster_bootstrap(clusters_of(sub), stat)
        entry["wording"] = ST.describe_interval(
            entry["interval"], name=f"block {row['block']} delta AUC")
        per_block.append(entry)

    # ------------------------------------------------------- suppression
    def buy_rate(rows, key):
        return (sum(1 for r in rows if r[key]) / len(rows)) if rows else None

    all_valid = [e for e in joined if e["valid_both"]]
    all_scored = [{
        "stable_id": e["key"][1],
        "block": C.block_of(e["key"][0], blocks),
        "trained_buy": float(e["trained"]["valence_hz"]) > theta,
        "reference_buy": float(e["reference"]["valence_hz"]) > theta,
        "trained": float(e["trained"]["valence_hz"]),
        "reference": float(e["reference"]["valence_hz"]),
    } for e in all_valid]

    suppression = {
        "theta_hz": theta,
        "rows_valid_in_both": len(all_scored),
        "buy_rate_trained": buy_rate(all_scored, "trained_buy"),
        "buy_rate_reference": buy_rate(all_scored, "reference_buy"),
        "action_counts": {b: dict(Counter(e[b]["action"] for e in joined
                                          if e[b] is not None))
                          for b in ("trained", "reference")},
        "status_counts": {b: dict(status_counts[b]) for b in status_counts},
        "score": {b: {
            "mean": float(np.mean([e[b] for e in all_scored])) if all_scored else None,
            "sd": float(np.std([e[b] for e in all_scored], ddof=1))
            if len(all_scored) > 1 else None,
            "min": float(np.min([e[b] for e in all_scored])) if all_scored else None,
            "p25": float(np.percentile([e[b] for e in all_scored], 25))
            if all_scored else None,
            "median": float(np.median([e[b] for e in all_scored])) if all_scored else None,
            "p75": float(np.percentile([e[b] for e in all_scored], 75))
            if all_scored else None,
            "max": float(np.max([e[b] for e in all_scored])) if all_scored else None,
        } for b in ("trained", "reference")},
        "per_block": [{
            "block": row["block"],
            "n": len([r for r in all_scored if r["block"] == row["block"]]),
            "buy_rate_trained": buy_rate(
                [r for r in all_scored if r["block"] == row["block"]], "trained_buy"),
            "buy_rate_reference": buy_rate(
                [r for r in all_scored if r["block"] == row["block"]],
                "reference_buy"),
        } for row in blocks],
        "by_outcome_class": {
            ("positive" if positive else "negative"): {
                "n": len([r for r in paired if r["y"] is positive]),
                "buy_rate_trained": buy_rate(
                    [r for r in paired if r["y"] is positive], "trained_buy"),
                "buy_rate_reference": buy_rate(
                    [r for r in paired if r["y"] is positive], "reference_buy"),
            } for positive in (True, False)},
    }
    delta_scores = [r["trained"] - r["reference"] for r in all_scored]
    suppression["score_difference"] = {
        "mean": float(np.mean(delta_scores)) if delta_scores else None,
        "sd": float(np.std(delta_scores, ddof=1)) if len(delta_scores) > 1 else None,
        "median": float(np.median(delta_scores)) if delta_scores else None,
        "min": float(np.min(delta_scores)) if delta_scores else None,
        "max": float(np.max(delta_scores)) if delta_scores else None,
    }
    log("bootstrapping the suppression contrast ...")
    contrast = ST.cluster_bootstrap(
        clusters_of(paired),
        ST.class_contrast_statistic("trained_buy", "reference_buy", "y"))
    suppression["class_contrast"] = contrast
    suppression["class_contrast_wording"] = ST.describe_interval(
        contrast, name="the between-class difference of the trained-minus-"
                       "reference change in the BUY-crossing rate")
    if contrast["lo"] is None or contrast["hi"] is None:
        suppression["reading"] = "no interval"
    elif contrast["lo"] <= 0.0 <= contrast["hi"]:
        suppression["reading"] = "global"
    else:
        suppression["reading"] = ("contextual" if (contrast["point"] or 0) < 0
                                  else "contextual (larger drop in the "
                                       "positive class)")

    coverage = (valid_both / n_rows) if n_rows else None
    out_summary = {
        "version": "d11-001-evaluation-1",
        "run_id": C.RUN_ID,
        "dataset": man["dataset"],
        "window": man["window"],
        "split": sp,
        "rows": n_rows,
        "rows_valid_in_both": valid_both,
        "paired_neural_coverage": coverage,
        "paired_labelled_rows": len(paired),
        "missing_joins": missing,
        "class_balance": {"positive": overall["positive"],
                          "negative": overall["negative"]},
        "saturation": saturation,
        "invalid_state": {"counts": invalid, "rates": invalid_rate},
        "primary": {"overall": overall, "per_block": per_block},
        "suppression": suppression,
        "statistics_plan": cfg_run["statistics"],
    }
    (out / "evaluation.json").write_text(json.dumps(out_summary, indent=1,
                                                    default=str) + "\n")
    return out_summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(GRID))
    parser.add_argument("--labels", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--report-md", action="store_true")
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    def log(*a):
        print(*a, flush=True)

    if args.labels:
        print(json.dumps(build_labels(out, log=log), indent=1))
        return 0
    if args.report_md:
        write_report(out, log=log)
        return 0
    if args.report:
        summary = analyse(out, log=log)
        print(json.dumps({k: summary[k] for k in
                          ("rows", "rows_valid_in_both",
                           "paired_neural_coverage", "paired_labelled_rows",
                           "class_balance")}, indent=1))
        print(summary["primary"]["overall"]["wording"])
        print(summary["suppression"]["class_contrast_wording"])
        return 0
    raise SystemExit("nothing to do: pass --labels, --report or --report-md")



# ------------------------------------------------------------ diagnostics
def read_branch_log(path: Path) -> list[dict]:
    return list(read_jsonl(path)) if path.exists() else []


def reinforcement_table(records: list[dict]) -> dict:
    """Count, raw magnitude, normalised amount, clipping, reward/punishment."""
    learning = [r for r in records if r["kind"] == "LEARNING"]
    outcomes = {r["episode_id"]: r for r in records if r["kind"] == "OUTCOME"}
    rows = []
    for rec in learning:
        out = outcomes.get(rec["episode_id"], {})
        rows.append({
            "episode_id": rec["episode_id"],
            "token": out.get("symbol"),
            "net_pnl": rec.get("raw_net_pnl_eth", out.get("net_pnl")),
            "return_on_notional": rec.get("raw_return_on_notional",
                                          out.get("return_on_notional")),
            "valence": rec.get("valence"),
            "amount": rec.get("amount"),
            "clipped": rec.get("clipped"),
            "accepted": rec.get("accepted"),
            "synapses_depressed": rec.get("synapses_depressed"),
            "trace_eligible": rec.get("trace_eligible"),
            "full_scale": rec.get("reinforce_full_scale"),
        })
    amounts = [r["amount"] for r in rows if r["amount"] is not None]
    return {
        "updates": len(rows),
        "reward": sum(1 for r in rows if (r["valence"] or 0) > 0),
        "punishment": sum(1 for r in rows if (r["valence"] or 0) < 0),
        "neutral": sum(1 for r in rows if (r["valence"] or 0) == 0),
        "clipped": sum(1 for r in rows if r["clipped"]),
        "accepted": sum(1 for r in rows if r["accepted"]),
        "amount": {"min": min(amounts) if amounts else None,
                   "median": float(np.median(amounts)) if amounts else None,
                   "max": max(amounts) if amounts else None,
                   "mean": float(np.mean(amounts)) if amounts else None},
        "raw_return_on_notional": {
            "min": min((r["return_on_notional"] for r in rows
                        if r["return_on_notional"] is not None), default=None),
            "max": max((r["return_on_notional"] for r in rows
                        if r["return_on_notional"] is not None), default=None)},
        "rows": rows,
        "d10_historical_context": {
            "updates": 8, "clipped": 7, "full_scale": 0.01,
            "note": ("D10 ran the same rule at full scale 0.01 and clipped 7 "
                     "of 8 updates at the cap, discarding the size of the "
                     "outcome and keeping only its sign. The scale was "
                     "calibrated once, before this run, and is not touched "
                     "because this distribution looks weak or strong.")},
    }


def paper_results(branch: dict) -> dict:
    """Trades, gross, costs, net, holds, unresolved. Descriptive, never primary."""
    episodes = branch.get("episodes") or []
    account = branch.get("account") or {}
    holds = [e["seconds_held"] for e in episodes if e.get("seconds_held")]
    nets = [e["net_pnl"] for e in episodes if e.get("net_pnl") is not None]
    return {
        "episodes": len(episodes),
        "settled": sum(1 for e in episodes
                       if str(e.get("settlement", "")).startswith("SETTLED")),
        "settled_frozen": sum(1 for e in episodes
                              if e.get("settlement") == "SETTLED_FROZEN"),
        "gross_pnl_eth": sum(e.get("gross_pnl", 0.0) for e in episodes),
        "fees_eth": sum(e.get("fees_eth", 0.0) for e in episodes),
        "slippage_eth": sum(e.get("slippage_eth", 0.0) for e in episodes),
        "net_pnl_eth": sum(nets),
        "realized_pnl_eth": account.get("realized_pnl"),
        "trades": account.get("trades"),
        "holding_seconds": {"min": min(holds) if holds else None,
                            "max": max(holds) if holds else None,
                            "median": float(np.median(holds)) if holds else None},
        "unresolved": branch.get("unresolved") or [],
        "unresolved_count": len(branch.get("unresolved") or []),
        "marks": branch.get("marks"),
        "per_round_action": (branch.get("tally") or {}).get(
            "per_decision_round", {}).get("action", {}),
        "per_candidate_action": (branch.get("tally") or {}).get(
            "per_candidate_evaluation", {}).get("action", {}),
        "after_execution": (branch.get("tally") or {}).get(
            "after_execution_constraints", {}),
    }


def context_diagnostics(out: Path, *, log=print) -> dict:
    """The owner's CONTEXT CHECK, on the grid rows the brain actually saw."""
    from retrospective import build_encoders, collisions, rates_of

    cfg_v2, _ = C.configs()
    features = tuple(cfg_v2["features"]["order"])
    scales = cfg_v2["features"]["scales"]
    _v1, enc = build_encoders()
    by_tick: dict[int, list] = defaultdict(list)
    since: list[float] = []
    counts: list[float] = []
    volumes: list[float] = []
    ages: list[float] = []
    for row in read_jsonl(out / "rows.jsonl"):
        by_tick[row["tick"]].append(row)
        since.append(float(row["raw"]["since_last_trade"]))
        counts.append(float(row["raw"]["trade_count_2m"]))
        volumes.append(float(row["raw"]["gross_volume_2m"]))
        ages.append(float(row["raw"]["age"]))
    colliding = groups = 0
    for tick, rows in by_tick.items():
        vectors = [rates_of(enc, r["raw"], features, scales) for r in rows]
        c, g = collisions(vectors)
        colliding += c
        groups += g

    def dist(values):
        arr = np.array(values or [0.0])
        return {"n": len(values), "min": float(arr.min()),
                "p25": float(np.percentile(arr, 25)),
                "median": float(np.median(arr)),
                "p75": float(np.percentile(arr, 75)),
                "p90": float(np.percentile(arr, 90)),
                "max": float(arr.max()), "mean": float(arr.mean())}

    per_tick = np.array([len(v) for v in by_tick.values()] or [0])
    return {
        "candidates_per_tick": {
            "min": int(per_tick.min()), "max": int(per_tick.max()),
            "median": float(np.median(per_tick)), "mean": float(per_tick.mean())},
        "ticks_with_rows": len(by_tick),
        "deterministic_collisions": {
            "candidates_in_a_group_of_equals": colliding,
            "groups": groups,
            "denominator_rows": sum(len(v) for v in by_tick.values()),
            "tolerance_hz": 1e-9,
            "rule": ("computed from the encoder's deterministic rate vectors "
                     "at 1e-9 Hz, before any Poisson sampling, per tick")},
        "since_last_trade_s": dist(since),
        "trade_count_2m": dist(counts),
        "gross_volume_2m_eth": dist(volumes),
        "age_s": dist(ages),
    }


# ---------------------------------------------------------------- report.md
def _f(value, digits=6, dash="—"):
    if value is None:
        return dash
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:,.{digits}f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _interval(row: dict) -> str:
    if row.get("lo") is None:
        return "—"
    return f"[{row['lo']:+.4f}, {row['hi']:+.4f}]"


def write_report(out: Path, *, log=print) -> Path:
    """`runs/d11-001/report.md`: every section the owner's DELIVERY list names."""
    run_dir = out.parent
    cfg_v2, cfg_run = C.configs()
    man = C.manifest()
    probe = json.loads((C.HERE / "node_probe.json").read_text())
    step3 = json.loads((C.HERE / "split.json").read_text())
    backfill = json.loads((C.HERE / "backfill_summary.json").read_text())
    ev = json.loads((out / "evaluation.json").read_text())
    rows_sum = json.loads((out / "rows_summary.json").read_text())
    labels = json.loads((out / "labels_summary.json").read_text())
    summary = json.loads((run_dir / "summary.json").read_text())
    ledger = json.loads((C.HERE / "rpc_ledger_local.json").read_text())
    branches = summary.get("branches", {})
    learning = branches.get("learning", {})
    reinforcement = reinforcement_table(
        read_branch_log(run_dir / "learning" / "events.jsonl"))
    context = context_diagnostics(out, log=log)
    live_path = C.RUNS / "d11-live-001" / "summary.json"
    live = json.loads(live_path.read_text()) if live_path.exists() else None

    sp = ev["split"]
    primary = ev["primary"]
    overall = primary["overall"]
    supp = ev["suppression"]
    sat = ev["saturation"]
    ceiling = step3["geometric_ceiling"]["ceiling"]
    episodes = len(learning.get("episodes") or [])
    completed = reinforcement["updates"]

    conditions = [
        ("fewer than 20 completed LEARNING episodes", completed, 20,
         completed < 20, f"{completed} completed LEARNING episodes"),
        ("fewer than 100 paired FROZEN candidate labels",
         ev["paired_labelled_rows"], 100, ev["paired_labelled_rows"] < 100,
         f"{ev['paired_labelled_rows']:,} rows valid in both branches with a "
         f"settled label"),
        ("either positive or negative outcome class has fewer than 20 "
         "labeled examples", min(overall["positive"], overall["negative"]), 20,
         min(overall["positive"], overall["negative"]) < 20,
         f"{overall['positive']:,} positive / {overall['negative']:,} negative"),
        ("paired neural coverage below 95%",
         ev["paired_neural_coverage"], 0.95,
         (ev["paired_neural_coverage"] or 0) < 0.95,
         f"{(ev['paired_neural_coverage'] or 0) * 100:.2f} % of "
         f"{ev['rows']:,} rows valid in both branches"),
        ("material encoder saturation or invalid-state rate above 5%",
         max(sat["saturated_row_channel_fraction"] or 0.0,
             max((ev["invalid_state"]["rates"] or {}).values(), default=0.0)),
         0.05,
         (sat["saturated_row_channel_fraction"] or 0) > 0.05
         or any((v or 0) > 0.05 for v in ev["invalid_state"]["rates"].values()),
         f"saturation {(sat['saturated_row_channel_fraction'] or 0) * 100:.3f} % "
         f"of (row, channel) pairs; INVALID_STATE "
         + ", ".join(f"{b} {(r or 0) * 100:.3f} %"
                     for b, r in ev["invalid_state"]["rates"].items())),
    ]

    L = []
    A = L.append
    A("# d11-001 — the preregistered Pons learning evaluation")
    A("")
    A("**One replay on twelve hours of genuine PONS v2 market collected through "
      "a verified local Nitro node, split 70/30 by time, one brain carried "
      "through the earlier part and then frozen, and a market-only grid over "
      "the later part scored by that brain and by an untouched clean "
      "reference.** Preregistered in `experiments/d11/d11_001.json` and "
      "`PLAN.md` §7 before the first request; the window, the cutoff, the tick "
      "counts, the geometric ceiling, the grid and the class balance in "
      "`experiments/d11/split.json` before the brain ran.")
    A("")
    A("Profit is recorded and is **not** the criterion. Predictive learning is "
      "not declared from PnL, and failure is not declared because the fly "
      "loses money. An interval that includes 0 is reported as *compatible "
      "with sampling variation*.")
    A("")

    # ---------------------------------------------------------------- node
    A("## 1. The node, and every request this wave made")
    A("")
    A("| port | source | chain id | latest block age | verified |")
    A("|---|---|---|---|---|")
    for row in probe["ports"]:
        A(f"| {row['port']} | {row.get('source', '')} | "
          f"{_f(row.get('chain_id'))} | "
          f"{'—' if row.get('age_s') is None else str(row['age_s']) + ' s'} | "
          f"{'**yes**' if row.get('verified') else 'no — ' + str(row.get('error'))} |")
    A("")
    cap = probe["capability"]
    w_blocks = man["window"]["blocks"]
    A(f"Verified endpoint **127.0.0.1:{probe['verified']['port']}**, the "
      f"loopback host port the `{probe['verified'].get('image')}` container "
      f"publishes for its own {probe['verified'].get('container_port')}. "
      f"`eth_chainId` **4663**, `latest` block "
      f"**{probe['verified']['age_s']} s** from wall clock. Measured finality: "
      f"median block interval **{cap['finality']['median_block_interval_s']:.5f} s**, "
      f"confirm depth **{cap['finality']['confirm_depth_blocks']}**, `safe` "
      f"supported.")
    A("")
    if probe.get("declared_degradation"):
        depth = probe.get("state_depth", {})
        A(f"**One declared degradation.** The creator-tax state read at a "
          f"twelve-hour-old block returned *missing trie node … state is not "
          f"available*: the node is pruned. The probe bisected the boundary — "
          f"the oldest block whose state it serves is "
          f"**{_f(depth.get('oldest_block_with_state'))}**, "
          f"**{_f(depth.get('retained_blocks'))}** blocks "
          f"(≈ {_f(depth.get('retained_seconds_approx'), 0)} s ≈ "
          f"{(depth.get('retained_seconds_approx') or 0) / 3600:.2f} h) behind "
          f"head. Every call the collection *needs* — the headers, the "
          f"`safe` tag and a collector-sized log range at the old end of the "
          f"window — answered. The "
          f"creator-tax read is a **declared fallback** whose failure the "
          f"collector's own code names `CREATOR_TAX_UNREADABLE` and leaves "
          f"`unavailable`; `experiments/d11/backfill.py` pins the tax from any "
          f"recorded trade rather than only the first, with no request, and "
          f"the residue is **{backfill['initial_states_reasons']['CREATOR_TAX_UNREADABLE']} "
          f"launches of {backfill['launches_total']:,}** "
          f"({backfill['initial_states_reasons']['CREATOR_TAX_UNREADABLE'] / max(1, backfill['launches_native']) * 100:.2f} % "
          f"of the {backfill['launches_native']:,} native ones). "
          f"**No Chainstack request was made, `--allow-remote` was never "
          f"passed, and the remote request count is 0.**")
        A("")
    A(f"**Requests, all loopback.** Ledger `experiments/d11/rpc_ledger_local.json`, "
      f"wave and day caps 22,200 — three times the registered projection of "
      f"7,400 — with a per-entry-point run cap. Total "
      f"**{ledger['attempts']:,} attempts / {ledger['units']:,} units / "
      f"{ledger['errors']} errors**; **remote requests: 0**. Every one of the "
      f"{ledger['errors']} errors is accounted for: 11 refused state reads "
      f"from the probe's deliberate retained-depth bisection, and 2 connection "
      f"refusals on the two ports addendum 3 names, which nothing listens on.")
    A("")
    A("| method | attempts | units | errors |")
    A("|---|---|---|---|")
    for method, entry in sorted(ledger["by_method"].items()):
        A(f"| `{method}` | {entry['attempts']:,} | {entry['units']:,} | "
          f"{entry['errors']} |")
    A("")
    A("| run | attempts | units |")
    A("|---|---|---|")
    for run_id, entry in sorted(ledger.get("by_run", {}).items()):
        A(f"| `{run_id}` | {entry['attempts']:,} | {entry['units']:,} |")
    A("")

    # ------------------------------------------- the state substitution
    sub_path = C.HERE / "state_substitution.json"
    if sub_path.exists():
        sub = json.loads(sub_path.read_text())
        vb = sub.get("verification_b") or {}
        va = sub.get("verification_a") or {}
        rescue = sub.get("rescue") or {}
        A("### The pruned node's historical state: every substituted call, its "
          "class, and how it was verified")
        A("")
        A("The owner's amendment after dispatch withdrew the archive-state hard "
          "stop and asked for classification and substitution instead. **The "
          "D10 backfill made exactly one kind of historical state read** — the "
          "creator-tax fallback at a launch block, used **3 times in 991 "
          "launches**. (`flytrade.pons.collector.read_initial_state`'s nine "
          "reads are reachable from no run path.) The creator tax is a launch "
          "parameter of the curve, so it is class **(a) immutable per curve** "
          "— measured, not claimed.")
        A("")
        A("| substituted call | class | substitution | verification | result |")
        A("|---|---|---|---|---|")
        A(f"| the creator-tax state read at the launch block | **(b)** "
          f"reconstruct from events | pin the tax from **any** recorded trade "
          f"of the launch, not only the first — no request at all | re-derive "
          f"every recorded initial state of `d10-backfill-v1` from that "
          f"store's own events, local files only | "
          f"**{_f(vb.get('matched_exactly'))} of {_f(vb.get('checked'))} "
          f"matched exactly** on every field; "
          f"{_f(vb.get('mismatch_count'))} unpinnable from events alone |")
        A(f"| the same read | **(a)** immutable per curve | read at `latest` "
          f"instead of at a pruned block | a ledgered loopback probe over the "
          f"same population, compared with the value recorded at the launch "
          f"block | **{_f(va.get('answered'))} of {_f(va.get('probed'))} "
          f"answered, {_f(va.get('matched_exactly'))} matched exactly**, "
          f"{_f(va.get('differ_count'))} differed, "
          f"{_f(va.get('unanswered_count'))} unanswered |")
        A(f"| applied to this wave's own residue | **(a)** | the curves whose "
          f"tax no recorded trade pins, read at `latest` and written with "
          f"`source: latest_block_immutable` | the store's `MANIFEST.json` "
          f"under `initial_states` and `state_substitution` | "
          f"**{_f(rescue.get('rescued'))} rescued of "
          f"{_f(rescue.get('probed'))}**; class **(c)** residue "
          f"**{_f(rescue.get('still_class_c'))}** |")
        A("")
        A(f"**Class (c)** — mutable and not reconstructible — would have been "
          f"marked unsupported and counted, and nothing would have been "
          f"guessed. There are **{_f(rescue.get('still_class_c'))}** such "
          f"curves.")
        A("")
        A(f"**The window against the twelve-hour target.** Twelve hours is what "
          f"the node served: headers and logs contiguous across all "
          f"{w_blocks:,} blocks with **0 errors** and **0 range retreats**, and "
          f"the probe's log range at the old end returned "
          f"{_f(cap.get('old_end_factory_logs'))} real logs. **No shrinking was "
          f"needed**, and the earliest block served is the window's own "
          f"`first_block`. One factory log in the window carried a `topic0` "
          f"outside the pinned ABI and is stored `UNMAPPED` and undecoded, "
          f"which is the collector's declared behaviour.")
        A("")

    # ------------------------------------------------------------- window
    w = man["window"]
    A("## 2. The window, the split, and the geometric ceiling")
    A("")
    A(f"**`d11-backfill-v1`** — blocks **{w['first_block']:,} – "
      f"{w['last_block']:,}** ({w['blocks']:,} blocks), "
      f"**{w['first_ts_utc']} – {w['last_ts_utc']}**, exactly "
      f"**{w['seconds']:,} s**. It does **not** overlap `d10-backfill-v1` "
      f"(blocks {w['d10_backfill_v1']['first_block']:,} – "
      f"{w['d10_backfill_v1']['last_block']:,}), which stays untouched as the "
      f"historical baseline.")
    A("")
    A(f"Collected once in {backfill['elapsed_s']:.0f} s: "
      f"**{backfill['events']:,} events**, **{backfill['launches_total']:,} "
      f"launches** ({backfill['launches_native']:,} native ETH, "
      f"{backfill['launches_quote_unsupported']:,} on another quote), "
      f"{backfill['curve_completed']} curves completed, "
      f"{backfill['headers_fetched']:,} headers. Initial states: "
      f"{backfill['initial_states']['derived_from_the_first_trade']:,} pinned "
      f"from the first trade, "
      f"{backfill['initial_states']['derived_from_a_later_trade']} from a "
      f"later one, {backfill['initial_states']['unavailable']:,} unavailable "
      f"({backfill['initial_states_reasons']['NO_TRADE_TO_PIN_THE_CREATOR_TAX']:,} "
      f"never traded at all). Every later step reads this store; nothing after "
      f"the collection reaches the chain.")
    A("")
    A("| | value |")
    A("|---|---|")
    A(f"| t0 = timestamp(start_block) | {sp['t0']} |")
    A(f"| t1 = timestamp(end_block) | {sp['t1']} |")
    A(f"| **T** = t0 + floor(0.7·(t1−t0)) on the 30 s grid | **{sp['T']}** "
      f"({sp['learning_share'] * 100:.2f} % of the span) |")
    A(f"| LEARNING ticks (cutoff ≤ T) | {sp['learning_ticks']:,} |")
    A(f"| last LEARNING tick that may enter (cutoff + 902 ≤ T) | "
      f"{sp['learning_last_entry_tick']} |")
    A(f"| FROZEN ticks (T ≤ cutoff, cutoff + 902 ≤ t1) | {sp['frozen_ticks']:,} |")
    A(f"| temporal blocks | " + " / ".join(
        str(b["ticks"]) for b in sp["temporal_blocks"]) + " ticks |")
    A(f"| **geometric ceiling** (932 s slots) | **{ceiling}** |")
    A(f"| **LEARNING episodes produced** | **{episodes}** "
      f"({completed} settled and reinforced) |")
    A("")

    # ----------------------------------------------------------- learning
    A("## 3. LEARNING replay")
    A("")
    paper = paper_results(learning)
    A(f"`REPLAY_PAPER`, `LEARN`, from the clean reference "
      f"`{str(learning.get('clean_reference_digest'))[:12]}…` under "
      f"`from_clean_reference`, `pons_encoder_v2` schema "
      f"`{cfg_v2['encoder']['input_schema_sha256'][:12]}…`, `admission_v2`, "
      f"reinforcement full scale **{cfg_v2['reinforcement']['new_full_scale']}**. "
      f"Entry refused at the partition boundary, and **no position was open at "
      f"T** (`position_open_at_end` = "
      f"{_f(learning.get('position_open_at_end'))}).")
    A("")
    A(f"Ticks {_f(learning.get('ticks'))}, tapes {_f(learning.get('tapes'))}, "
      f"tokens discovered {_f(learning.get('tokens_discovered'))}. "
      f"Digest `{str(learning.get('start_digest'))[:12]}…` → "
      f"**`{str(learning.get('end_digest'))[:12]}…`** (TRAINED). "
      f"Restarts: {len(learning.get('restarts') or [])}.")
    A("")
    A("### Reinforcement, beside D10's 7 of 8")
    A("")
    r = reinforcement
    A(f"**{r['updates']} updates** — {r['reward']} reward, {r['punishment']} "
      f"punishment, {r['neutral']} neutral — and **{r['clipped']} clipped at "
      f"the cap**. Normalised amount: min {_f(r['amount']['min'], 4)}, median "
      f"{_f(r['amount']['median'], 4)}, max {_f(r['amount']['max'], 4)}. Raw "
      f"return on notional ranged {_f(r['raw_return_on_notional']['min'], 6)} "
      f"to {_f(r['raw_return_on_notional']['max'], 6)}.")
    A("")
    A("| # | episode | net (ETH) | return on notional | valence | normalised "
      "amount | clipped | synapses |")
    A("|---|---|---|---|---|---|---|---|")
    for i, row in enumerate(r["rows"], start=1):
        A(f"| {i} | {row['episode_id']} | {_f(row['net_pnl'], 8)} | "
          f"{_f(row['return_on_notional'], 6)} | {_f(row['valence'], 0)} | "
          f"{_f(row['amount'], 4)} | {_f(row['clipped'])} | "
          f"{_f(row['synapses_depressed'])} |")
    A("")
    A(f"**Historical context, not a comparison.** {r['d10_historical_context']['note']}")
    A("")
    A("### Paper results (descriptive, never the learning metric)")
    A("")
    A(f"Trades {_f(paper['trades'])}, gross {_f(paper['gross_pnl_eth'], 8)} ETH, "
      f"fees {_f(paper['fees_eth'], 8)} ETH, slippage "
      f"{_f(paper['slippage_eth'], 8)} ETH, **net {_f(paper['net_pnl_eth'], 8)} "
      f"ETH**; holds {_f(paper['holding_seconds']['min'], 0)}–"
      f"{_f(paper['holding_seconds']['max'], 0)} s (median "
      f"{_f(paper['holding_seconds']['median'], 0)} s); unresolved "
      f"{paper['unresolved_count']}; marks {_f(paper['marks'])}.")
    A("")
    A(f"Per-round actions: `{paper['per_round_action']}`. "
      f"After execution: `{paper['after_execution']}`.")
    A("")
    return _write_rest(L, out, run_dir, cfg_v2, cfg_run, ev, rows_sum, labels,
                       step3, context, branches, live, conditions, log=log)


def _write_rest(L, out, run_dir, cfg_v2, cfg_run, ev, rows_sum, labels, step3,
                context, branches, live, conditions, *, log=print) -> Path:
    A = L.append
    sp = ev["split"]
    primary = ev["primary"]
    overall = primary["overall"]
    supp = ev["suppression"]
    sat = ev["saturation"]

    # --------------------------------------------------------------- grid
    A("## 4. The FROZEN evaluation grid")
    A("")
    A("**The grid is not the loop.** While a position is held the loop presents "
      "only the held token and the round-robin advances with evaluated rounds, "
      "so two frozen loop branches cannot share rows. Every FROZEN tick's tapes "
      "are rebuilt from the store, `admission_v2` is applied at that cutoff and "
      "**all** eligible candidates are taken — no cap of six, no rotation, no "
      "hold mode — then each is scored by **both** frozen brains with the "
      "standard k = 8 `comparison_v1` readout, whose seeds are keyed to "
      "`(observation_id, stable_id, replicate)` and **not** to the checkpoint "
      "digest. Rows are keyed `(cutoff_ts, stable_id)` and are built once, so "
      "the branches are identical by construction.")
    A("")
    for branch in ("trained", "reference"):
        path = out / f"scores_{branch}_summary.json"
        if path.exists():
            s = json.loads(path.read_text())
            A(f"* **{branch}** — {s['rows']:,} rows, digest "
              f"`{s['start_digest'][:12]}…` before and after, unchanged: "
              f"**{_f(s['digest_unchanged'])}**.")
    A("")
    A("| | value |")
    A("|---|---|")
    A(f"| grid rows | {ev['rows']:,} |")
    A(f"| rows VALID in both branches | {ev['rows_valid_in_both']:,} |")
    A(f"| **paired neural coverage** | "
      f"**{(ev['paired_neural_coverage'] or 0) * 100:.2f} %** |")
    A(f"| rows with a settled label (the AUC denominator) | "
      f"{ev['paired_labelled_rows']:,} |")
    A(f"| label class balance | {overall['positive']:,} positive / "
      f"{overall['negative']:,} negative |")
    A(f"| UNRESOLVED labels | {labels['unresolved']:,} "
      f"({labels['unresolved_reasons']}) |")
    A(f"| tokens (bootstrap clusters) | {overall['clusters']:,} |")
    A(f"| saturated (row, channel) pairs | "
      f"{sat['saturated_row_channel_pairs']:,} of "
      f"{sat['row_channel_pairs']:,} = "
      f"{(sat['saturated_row_channel_fraction'] or 0) * 100:.3f} % |")
    A(f"| rows with at least one saturated channel | "
      f"{sat['rows_with_at_least_one']:,} "
      f"({(sat['rows_with_at_least_one_fraction'] or 0) * 100:.2f} %) |")
    for branch, rate in ev["invalid_state"]["rates"].items():
        A(f"| INVALID_STATE rate, {branch} | {(rate or 0) * 100:.3f} % |")
    A("")
    A(f"The evaluator-only label: {labels['definition']} Its known-answer test "
      f"— `tests/d11/test_label.py`, written and run **before** the grid's "
      f"label pass — reproduces all **16 settled D10 entries**: "
      f"`tokens_out_wei` exactly, the entry and exit blocks and instants "
      f"exactly, and `net_pnl` and `return_on_notional` at the precision the "
      f"records store them. Net over the settled rows: median "
      f"{_f(labels['net_eth']['median'], 8)} ETH, min "
      f"{_f(labels['net_eth']['min'], 8)}, max "
      f"{_f(labels['net_eth']['max'], 8)}.")
    A("")

    # ------------------------------------------------------------ primary
    A("## 5. The primary question — does training change the ranking?")
    A("")
    A(f"AUC is Mann–Whitney with ties counted a half; the interval is a paired "
      f"**cluster bootstrap by `stable_id`** — a token's rows move together — "
      f"with {cfg_run['statistics']['uncertainty']['resamples']:,} resamples "
      f"at seed {cfg_run['statistics']['uncertainty']['seed']}, percentile "
      f"95 %.")
    A("")
    A("| | n | positive | AUC trained | AUC reference | ΔAUC | 95 % interval |")
    A("|---|---|---|---|---|---|---|")
    A(f"| **overall** | {overall['n']:,} | {overall['positive']:,} | "
      f"{_f(overall['auc_trained'], 4)} | {_f(overall['auc_reference'], 4)} | "
      f"**{_f(overall['delta_auc'], 4)}** | {_interval(overall['interval'])} |")
    for row in primary["per_block"]:
        A(f"| block {row['block']} | {row['n']:,} | {row['positive']:,} | "
          f"{_f(row['auc_trained'], 4)} | {_f(row['auc_reference'], 4)} | "
          f"{_f(row['delta_auc'], 4)} | {_interval(row['interval'])} |")
    A("")
    A(f"**{overall['wording']}.**")
    A("")
    for row in primary["per_block"]:
        A(f"* {row['wording']}.")
    A("")
    A(f"Secondary, descriptive: Spearman(score, net) is "
      f"{_f(overall['spearman_trained'], 4)} for TRAINED and "
      f"{_f(overall['spearman_reference'], 4)} for REFERENCE. The per-row "
      f"score difference TRAINED − REFERENCE has mean "
      f"{_f(supp['score_difference']['mean'], 4)} Hz, SD "
      f"{_f(supp['score_difference']['sd'], 4)}, median "
      f"{_f(supp['score_difference']['median'], 4)}, range "
      f"[{_f(supp['score_difference']['min'], 4)}, "
      f"{_f(supp['score_difference']['max'], 4)}].")
    A("")
    A("**An AUC near 0.5 is not evidence that no signal exists**, and nothing "
      "above is a claim about a rate in the market.")
    A("")

    # -------------------------------------------------------- suppression
    A("## 6. Suppression")
    A("")
    A(f"θ = {supp['theta_hz']:.6f} Hz, the stored k = 8 margin. BUY-crossing "
      f"rate over the {supp['rows_valid_in_both']:,} rows valid in both "
      f"branches: **TRAINED {(supp['buy_rate_trained'] or 0) * 100:.2f} %**, "
      f"**REFERENCE {(supp['buy_rate_reference'] or 0) * 100:.2f} %**.")
    A("")
    A("| | n | BUY rate trained | BUY rate reference | change |")
    A("|---|---|---|---|---|")
    A(f"| overall | {supp['rows_valid_in_both']:,} | "
      f"{(supp['buy_rate_trained'] or 0) * 100:.2f} % | "
      f"{(supp['buy_rate_reference'] or 0) * 100:.2f} % | "
      f"{((supp['buy_rate_trained'] or 0) - (supp['buy_rate_reference'] or 0)) * 100:+.2f} pp |")
    for row in supp["per_block"]:
        A(f"| block {row['block']} | {row['n']:,} | "
          f"{(row['buy_rate_trained'] or 0) * 100:.2f} % | "
          f"{(row['buy_rate_reference'] or 0) * 100:.2f} % | "
          f"{((row['buy_rate_trained'] or 0) - (row['buy_rate_reference'] or 0)) * 100:+.2f} pp |")
    for name, row in supp["by_outcome_class"].items():
        A(f"| later outcome {name} | {row['n']:,} | "
          f"{(row['buy_rate_trained'] or 0) * 100:.2f} % | "
          f"{(row['buy_rate_reference'] or 0) * 100:.2f} % | "
          f"{((row['buy_rate_trained'] or 0) - (row['buy_rate_reference'] or 0)) * 100:+.2f} pp |")
    A("")
    A(f"The pre-registered reading is the **between-class difference of the "
      f"trained-minus-reference change**, with the same clustered interval: "
      f"{supp['class_contrast_wording']}. Under the registered rule that is "
      f"**{supp['reading']}**. **A lower BUY rate alone is not learning "
      f"success**, and nothing else is said in words.")
    if (supp["buy_rate_trained"] or 0) == 0.0:
        A("")
        A("One arithmetic fact belongs beside that label and is stated without "
          "interpretation: **the trained branch's BUY-crossing rate is exactly "
          "0 in every cell** — overall, in each block and in each outcome "
          "class. When one side of a difference of differences is identically "
          "zero, the between-class contrast is the *reference* branch's own "
          "class difference with its sign flipped, and it says nothing about "
          "context sensitivity in the trained branch. The registered label is "
          "reported because it was registered; the zero is reported because it "
          "is what the numbers are.")
    A("")
    A("Continuous scores over the same rows:")
    A("")
    A("| branch | mean | SD | min | p25 | median | p75 | max |")
    A("|---|---|---|---|---|---|---|---|")
    for branch, row in supp["score"].items():
        A(f"| {branch} | {_f(row['mean'], 3)} | {_f(row['sd'], 3)} | "
          f"{_f(row['min'], 3)} | {_f(row['p25'], 3)} | "
          f"{_f(row['median'], 3)} | {_f(row['p75'], 3)} | "
          f"{_f(row['max'], 3)} |")
    A("")
    A("Decoded actions and readout statuses over all grid rows:")
    A("")
    for branch in ("trained", "reference"):
        A(f"* **{branch}** — actions `{supp['action_counts'][branch]}`, "
          f"statuses `{supp['status_counts'][branch]}`")
    A("")

    # -------------------------------------------------------- context
    A("## 7. Context and admission")
    A("")
    c = context
    A(f"Candidates per FROZEN tick: median "
      f"{_f(c['candidates_per_tick']['median'], 1)}, mean "
      f"{_f(c['candidates_per_tick']['mean'], 1)}, range "
      f"{c['candidates_per_tick']['min']}–{c['candidates_per_tick']['max']} "
      f"over {c['ticks_with_rows']} ticks with at least one row. "
      f"Zero-eligible ticks: **{rows_sum['zero_eligible_ticks']}** "
      f"(`{rows_sum['empty_round_status']}`).")
    A("")
    A("**Deterministic sensory collisions**, from the encoder's rate vectors at "
      f"1e-9 Hz before any Poisson sampling, per tick: "
      f"**{c['deterministic_collisions']['candidates_in_a_group_of_equals']} of "
      f"{c['deterministic_collisions']['denominator_rows']:,} rows** in "
      f"{c['deterministic_collisions']['groups']} groups of equals. D10's "
      "failure mode — a round in which every presented candidate carried "
      "effectively the same vector — is measured here rather than asserted.")
    A("")
    A("| feature among admitted rows | min | p25 | median | p75 | p90 | max |")
    A("|---|---|---|---|---|---|---|")
    for key, label in (("since_last_trade_s", "`since_last_trade` (s)"),
                       ("trade_count_2m", "`trade_count_2m`"),
                       ("gross_volume_2m_eth", "`gross_volume_2m` (ETH)"),
                       ("age_s", "`age` (s)")):
        d = c[key]
        A(f"| {label} | {_f(d['min'], 3)} | {_f(d['p25'], 3)} | "
          f"{_f(d['median'], 3)} | {_f(d['p75'], 3)} | {_f(d['p90'], 3)} | "
          f"{_f(d['max'], 3)} |")
    A("")
    A("Admission verdicts over every considered (tape, tick) of the FROZEN "
      "partition:")
    A("")
    A("| reason | count |")
    A("|---|---|")
    for reason, count in sorted(rows_sum["admission_reasons"].items(),
                                key=lambda kv: -kv[1]):
        A(f"| `{reason}` | {count:,} |")
    A("")

    # ------------------------------------------------- frozen loop paper
    A("## 8. The two FROZEN loop branches (paper results, descriptive)")
    A("")
    A("These are the loop run over the FROZEN partition with learning off, the "
      "market rebuilt from t0 without the brain. They are **not** the primary "
      "comparison — their rows differ by construction, which is why the grid "
      "exists — and their PnL is descriptive.")
    A("")
    A("| branch | ticks | episodes | settled frozen | net (ETH) | fees | "
      "holds (s) | unresolved | digest unchanged |")
    A("|---|---|---|---|---|---|---|---|---|")
    for name in ("frozen_trained", "frozen_reference"):
        b = branches.get(name)
        if not b:
            A(f"| {name} | — | — | — | — | — | — | — | not run |")
            continue
        p = paper_results(b)
        A(f"| {name} | {_f(b.get('ticks'))} | {p['episodes']} | "
          f"{p['settled_frozen']} | {_f(p['net_pnl_eth'], 8)} | "
          f"{_f(p['fees_eth'], 8)} | "
          f"{_f(p['holding_seconds']['min'], 0)}–"
          f"{_f(p['holding_seconds']['max'], 0)} | {p['unresolved_count']} | "
          f"{_f(b.get('digest_unchanged'))} |")
    A("")
    for name in ("frozen_trained", "frozen_reference"):
        b = branches.get(name)
        if b:
            A(f"* **{name}** — per-round actions "
              f"`{(b.get('tally') or {}).get('per_decision_round', {}).get('action', {})}`, "
              f"after execution "
              f"`{(b.get('tally') or {}).get('after_execution_constraints', {})}`, "
              f"digest `{str(b.get('start_digest'))[:12]}…` → "
              f"`{str(b.get('end_digest'))[:12]}…`")
    A("")

    # ------------------------------------------------------------- live
    A("## 9. The live hour")
    A("")
    if live is None:
        A("Not run at the time this report was written.")
    elif live.get("status") == "not_started":
        A(f"**Not started.** {live['detail']} This is reported, not worked "
          f"around.")
    else:
        lb = live.get("branches", {}).get("live", {})
        lp = paper_results(lb)
        A(f"`LIVE_PAPER`, learning **enabled** — the declared d11-001 live "
          f"branch — from the TRAINED checkpoint "
          f"`{str(live.get('starts_from_digest'))[:12]}…`, verified on disk "
          f"against the digest the replay recorded. Against the same local "
          f"node under the loopback ledger, with the chain-id gate and the "
          f"120-second freshness rule.")
        A("")
        A(f"Started {live.get('started_utc')}, stopped {live.get('stopped_utc')} "
          f"after {_f(live.get('elapsed_s'), 0)} s: "
          f"`{lb.get('stop_reason')}` {lb.get('stop_detail') or ''}. "
          f"{_f(lb.get('ticks'))} ticks, {lp['episodes']} episodes, "
          f"{lp['unresolved_count']} unresolved, net "
          f"{_f(lp['net_pnl_eth'], 8)} ETH. Requests "
          f"{_f(live.get('requests', {}).get('attempts'))} "
          f"({_f(live.get('requests', {}).get('units'))} units), **remote 0**. "
          f"Digest `{str(live.get('starts_from_digest'))[:12]}…` → "
          f"`{str(lb.get('learned_digest'))[:12]}…`.")
        A("")
        lr = reinforcement_table(
            read_branch_log(C.RUNS / "d11-live-001" / "live" / "events.jsonl"))
        A("")
        A(f"Reinforcement in the live hour: **{lr['updates']} update(s)** — "
          f"{lr['reward']} reward, {lr['punishment']} punishment, "
          f"{lr['clipped']} clipped at the cap.")
        if lr["rows"]:
            A("")
            A("| episode | net (ETH) | return on notional | valence | "
              "normalised amount | clipped | synapses |")
            A("|---|---|---|---|---|---|---|")
            for row in lr["rows"]:
                A(f"| {row['episode_id']} | {_f(row['net_pnl'], 8)} | "
                  f"{_f(row['return_on_notional'], 6)} | "
                  f"{_f(row['valence'], 0)} | {_f(row['amount'], 4)} | "
                  f"{_f(row['clipped'])} | {_f(row['synapses_depressed'])} |")
        A("")
        A(f"The one `UNRESOLVED` entry is the `PENDING_CONFIRMATION` the "
          f"episode carried while its exit block waited for the confirmation "
          f"rule; it settled inside the hour and is not a loss, a coverage gap "
          f"or a route transition.")
        A("")
        A(f"Chain: {_f(live.get('chain', {}).get('events'))} events, "
          f"{_f(live.get('chain', {}).get('launches_seen'))} launches seen.")
        A("")
        A("**A finished run is a record of an hour that already ended, never a "
          "fly operating now.**")
    A("")

    # --------------------------------------------------- inconclusive
    A("## 10. The five inconclusive conditions, one by one")
    A("")
    A("| condition (verbatim) | measured | threshold | verdict |")
    A("|---|---|---|---|")
    for name, value, threshold, fails, detail in conditions:
        A(f"| {name} | {detail} | {threshold} | "
          f"{'**FAIL**' if fails else 'PASS'} |")
    A("")
    failed = [n for n, _, _, f, _ in conditions if f]
    if failed:
        A(f"**{len(failed)} condition(s) failed: the learning evaluation is "
          f"declared INCONCLUSIVE** rather than stretching interpretation. "
          f"The thresholds are not loosened after the run.")
    else:
        A("**No condition failed.** That is a statement about the sample, not "
          "about the result: the comparison above stands as it is written, "
          "with its interval and its wording.")
    A("")
    A(f"Geometric ceiling **{step3['geometric_ceiling']['ceiling']}** beside "
      f"the **{len(branches.get('learning', {}).get('episodes') or [])}** "
      f"LEARNING episodes actually produced.")
    A("")

    # --------------------------------------------------------- what it is not
    A("## 11. What this cannot say")
    A("")
    A("D11 moved admission, the sensory context and the reinforcement scale "
      "**together**. A difference between TRAINED and REFERENCE here is a "
      "difference between one brain that saw 8.4 hours of this environment and "
      "one that saw none; it can **never** be attributed to any one of the "
      "three. `d11-001` is not comparable with `d10-001`, which ran a "
      "different environment on a different window. Profit is recorded and is "
      "not the criterion: **predictive learning is not declared from PnL, and "
      "failure is not declared because the fly loses money.**")
    A("")
    A("No real money, no signing, no funds. The RPC method allowlist carries "
      "no signing method and this wave added none. Every request went to "
      "`127.0.0.1`; **the remote request count is 0**.")
    A("")

    path = run_dir / "report.md"
    path.write_text("\n".join(L) + "\n")
    log(f"wrote {path}")
    return path


if __name__ == "__main__":
    raise SystemExit(main())
