#!/usr/bin/env python
"""
The D7 context-discrimination evaluator — amendment §6, §7, §8 and §9.

    .venv/bin/python experiments/d7/evaluate.py [run_id]

A **read-only post-run script**. It opens the two FROZEN event logs and the
price file, and writes `withheld-probe-table` (the paired probe dataset) and
`context_summary.json` (per-session AUCs, DELTA_AUC, the paired session
bootstrap, matched participation, coverage and the A/B/C conclusion).

Fable addendum 3, and the reason there is no runtime probe hook: the ordinary
per-round readout **is** the probe. `experiments/historical/run.py` evaluates
one candidate every round — with IBM alone, the held symbol while holding and
IBM itself while flat — under the `comparison_v1` seeds, and writes its
continuous decoder score into the `DECISION` event. So the probe dataset is
extracted from the log after both branches have finished. No second neural
pass, no duplicated work, and the "cannot mutate" guards are structural rather
than promised:

* this module imports **nothing** from `flytrade.runner`, `flytrade.mushroom`,
  `flytrade.execution`, `flytrade.records` or `flytrade.readout`: it cannot
  present a stimulus, move a weight, open an account or write an event;
* it opens every file it reads in text-read mode and writes only its own two
  output files, and it hashes both event logs before and after itself so that
  "the evaluator changed nothing" is a number in the output, not a claim;
* the probe grid is computed from the session calendar and the price file
  **before either log is opened**, so it cannot depend on which branch bought,
  on inventory, on a score, or on a later outcome.

The labels are analysis-only counterfactuals. They generate no learning event,
touch no bankroll, and are never summed into an executable PnL: the probes
overlap in time by construction, one per eligible minute.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import date as _date
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from flytrade import historical as H       # noqa: E402
from flytrade import horizon as HZ         # noqa: E402
from flytrade import metrics as MET        # noqa: E402

RUNS = HERE / "runs"
CONFIG = HERE / "config.json"
HORIZON = HERE / "registered-horizon-artifact"

#: the two FROZEN branches, by their run-store names
BRANCHES = ("frozen_trained", "frozen_reference")

#: readout statuses that carry a decoder reading, and therefore a probe score.
#: ``POLICY_REJECT`` is a post-decoder execution refusal on a reading that was
#: ``VALID``; §7 asks for the continuous score "before thresholding and before
#: inventory constraints", so excluding it would make the paired set depend on
#: inventory, which §6 forbids.
SCORED = ("VALID", "NO_RESPONSE", "POLICY_REJECT")


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------- the branch-blind grid

def probe_grid(series, first: _date, last: _date, hstar: int, *,
               delay: int) -> list[tuple[_date, int]]:
    """Every eligible one-minute decision origin of the FROZEN partition.

    Fable addendum 5: status ``OK`` (which already contains "past the
    per-session warm-up", both the 20-minute feature lookback and the 60-row
    causal normalisation window), and the existing clock rule with H*. The
    calendar and the price file are the only inputs.
    """
    out = []
    for day in series.days:
        if not (first <= day <= last):
            continue
        for m in range(H.SESSION_MINUTES):
            if not HZ.eligible(m, hstar, delay=delay):
                break
            if series.status(day, m).value == "OK":
                out.append((day, m))
    return out


def labels(series, grid, hstar: int, *, delay: int, notional: float,
           fee_bps: float, slippage_bps: float) -> dict:
    """``G(t)`` and ``Y(t)`` for every grid point, or ``UNAVAILABLE_LABEL``."""
    out = {}
    for day, m in grid:
        h = HZ.hold(series, day, m, hstar, delay=delay)
        if not h.ok:
            out[(day, m)] = {"available": False, "reason": h.reason}
            continue
        g = h.net_return(notional=notional, fee_bps=fee_bps,
                         slippage_bps=slippage_bps)
        out[(day, m)] = {
            "available": True, "G": float(g), "Y": int(g > 0.0),
            "gross_bps": float(h.gross_bps),
            "entry_minute": h.entry_minute, "exit_minute": h.exit_minute,
            "exit_ts": h.exit_ts,
            "entry_delay": h.entry_delay, "exit_delay": h.exit_delay}
    return out


# ------------------------------------------------------- reading the logs

def frozen_decisions(log_path: Path) -> tuple[dict, dict]:
    """``{(session, minute): decision event}`` inside the FROZEN span.

    The span is the index range between the partition's two ``PARTITION``
    boundary events, exactly as the observer and `compare.py` slice it. The
    log is opened read-only and every line is parsed and handed over
    unchanged; no field is derived and no decision is re-decoded.
    """
    rows, counts = {}, Counter()
    inside = False
    with open(log_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            k = e.get("kind")
            if k == "PARTITION" and e.get("partition") == "FROZEN":
                inside = e.get("boundary") == "start"
                continue
            if not inside:
                continue
            counts[k] += 1
            if k != "DECISION":
                continue
            ts = int(e["market_ts"]) - H.BAR_SECONDS          # bar_start
            key = (H.session_date(ts), int(e["bar_index"]))
            counts[f"DECISION:{e['readout_status']}"] += 1
            if key in rows:
                counts["DUPLICATE_DECISION_AT_A_MINUTE"] += 1
                continue
            rows[key] = e
    return rows, dict(counts)


def integrity(run_id: str, summary: dict) -> dict:
    """The run-level guards §10 asks to be shown, read from the run's own record."""
    out = {"run_id": run_id, "checks": []}

    def add(name, ok, detail):
        out["checks"].append({"id": name, "pass": bool(ok), "detail": detail})

    for b in BRANCHES:
        p = summary["branches"][b]["partitions"]["FROZEN"]
        add(f"{b}: frozen weights unchanged",
            p["start_digest"] == p["end_digest"],
            {"start_digest": p["start_digest"], "end_digest": p["end_digest"]})
        add(f"{b}: start digest is the declared checkpoint",
            p["start_digest"] == summary["branches"][b]["start_digest_expected"],
            {"expected": summary["branches"][b]["start_digest_expected"]})
        r = p["execution"]["reconciliation"]
        add(f"{b}: gross - fees - slippage = net",
            abs(r["residual"]) < 1e-6,
            {"residual": r["residual"], "tolerance": 1e-6})
        add(f"{b}: credit assigner accepted nothing",
            p["credit"]["accepted"] == 0, p["credit"])
    return out


# ------------------------------------------------------------------ main

def main(argv) -> int:
    t0 = time.time()
    cfg = json.loads(CONFIG.read_text())
    art = json.loads(HORIZON.read_text())
    if art.get("result") != "OK":
        raise SystemExit(f"the calibration artifact says {art['result']!r}: "
                         f"there is nothing to evaluate")
    hstar = int(art["selected_horizon_minutes"])
    xcfg = cfg["execution"]
    delay = int(xcfg["delay_minutes"])

    summary = json.loads((HERE / "frozen_summary.json").read_text())
    run_id = argv[1] if len(argv) > 1 else summary["run_id"]
    logs = {b: RUNS / run_id / b / "events.jsonl" for b in BRANCHES}
    before = {b: sha256_file(p) for b, p in logs.items()}

    # ---- 1. the grid and the labels, from the calendar and the price file
    path = ROOT / "data" / "market" / cfg["instruments"][0]["file"]
    got = sha256_file(path)
    if got != cfg["instruments"][0]["sha256"]:
        raise SystemExit("the price file is not the manifested one")
    series = H.load_series(path, cfg["instruments"][0]["symbol"])
    f = cfg["partitions"]["FROZEN"]
    first, last = _date.fromisoformat(f["first"]), _date.fromisoformat(f["last"])
    grid = probe_grid(series, first, last, hstar, delay=delay)
    lab = labels(series, grid, hstar, delay=delay, notional=xcfg["notional"],
                 fee_bps=xcfg["fee_bps"], slippage_bps=xcfg["slippage_bps"])
    unavailable = Counter(v["reason"] for v in lab.values()
                          if not v["available"])

    # ---- 2. only now are the logs opened -------------------------------
    dec, logcounts = {}, {}
    for b in BRANCHES:
        dec[b], logcounts[b] = frozen_decisions(logs[b])

    # ---- 3. per-branch and paired coverage ------------------------------
    label_available = [k for k in grid if lab[k]["available"]]
    per_branch, scored = {}, {}
    for b in BRANCHES:
        st = Counter()
        keep = set()
        for k in label_available:
            e = dec[b].get(k)
            if e is None:
                st["NO_DECISION_EVENT"] += 1
                continue
            st[e["readout_status"]] += 1
            if e["readout_status"] in SCORED and e.get("valence_hz") is not None:
                keep.add(k)
        scored[b] = keep
        per_branch[b] = {
            "status_counts": dict(st),
            "label_available_probes": len(label_available),
            "scored": len(keep),
            "coverage": MET.coverage(len(label_available), len(keep))}
    paired = sorted(scored[BRANCHES[0]] & scored[BRANCHES[1]])
    cov = {"trained_coverage": per_branch["frozen_trained"]["coverage"],
           "reference_coverage": per_branch["frozen_reference"]["coverage"],
           "paired_coverage": MET.coverage(len(label_available), len(paired)),
           "grid_points": len(grid),
           "label_available": len(label_available),
           "unavailable_label": dict(unavailable),
           "unavailable_label_total": sum(unavailable.values()),
           "paired_probes": len(paired)}

    # ---- 4. the paired probe dataset ------------------------------------
    rows = []
    for day, m in paired:
        L = lab[(day, m)]
        et = dec["frozen_trained"][(day, m)]
        er = dec["frozen_reference"][(day, m)]
        rows.append({
            "session": str(day), "minute": m,
            "market_ts": int(et["market_ts"]),
            "v_trained": float(et["valence_hz"]),
            "v_reference": float(er["valence_hz"]),
            "status_trained": et["readout_status"],
            "status_reference": er["readout_status"],
            "action_trained": et["decoded_action"],
            "action_reference": er["decoded_action"],
            "G": L["G"], "Y": L["Y"], "gross_bps": L["gross_bps"],
            "entry_minute": L["entry_minute"], "exit_minute": L["exit_minute"],
            "exit_ts": L["exit_ts"]})
    rows.sort(key=lambda r: (r["session"], r["minute"]))

    # ---- 5. per-session AUC, DELTA_AUC, bootstrap, matched participation -
    by_session = defaultdict(list)
    for r in rows:
        by_session[r["session"]].append(r)
    results = []
    for s in sorted(by_session):
        rs = by_session[s]
        results.append(MET.session_result(
            s, [r["v_trained"] for r in rs], [r["v_reference"] for r in rs],
            [r["Y"] for r in rs]))
    d_auc = MET.delta_auc(results)
    seed = int(cfg["evaluation"]["bootstrap_seed"])
    boot = MET.paired_session_bootstrap(
        results, draws=int(cfg["evaluation"]["bootstrap_draws"]), seed=seed)

    qualifying = {r.session for r in results if r.qualifies}
    mp_rows = [r for r in rows if r["session"] in qualifying]
    matched = {"scope": "qualifying sessions only, pooled",
               "sessions": sorted(qualifying)}
    matched.update(MET.matched_participation(
        [r["v_trained"] for r in mp_rows], [r["v_reference"] for r in mp_rows],
        [r["G"] for r in mp_rows], [r["Y"] for r in mp_rows],
        fraction=float(cfg["evaluation"]["top_fraction"])))
    per_session_matched = []
    for s in sorted(qualifying):
        rs = by_session[s]
        m1 = MET.matched_participation(
            [r["v_trained"] for r in rs], [r["v_reference"] for r in rs],
            [r["G"] for r in rs], [r["Y"] for r in rs],
            fraction=float(cfg["evaluation"]["top_fraction"]))
        m1["session"] = s
        per_session_matched.append(m1)

    # ---- 6. actual trading, action mixes, and the guards ----------------
    actions = {}
    for b in BRANCHES:
        c = Counter()
        for k, e in dec[b].items():
            c[f"round:{e['decoded_action']}"] += 1
            c[f"status:{e['readout_status']}"] += 1
        ex = summary["branches"][b]["execution"]
        actions[b] = {"per_decision_round": dict(c),
                      "trades": ex["trades"], "wins": ex["wins"],
                      "losses": ex["losses"], "net_pnl": ex["net_pnl"],
                      "after_execution": summary["branches"][b]["partitions"]
                      ["FROZEN"]["tally"]["after_execution_constraints"]}

    verdict = MET.classify(results, boot, cov)

    after = {b: sha256_file(p) for b, p in logs.items()}
    out = {
        "artifact": "flytrade-d7-context-1",
        "run_id": run_id,
        "written_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "selected_horizon_minutes": hstar,
        "horizon_artifact_sha256": sha256_file(HORIZON),
        "config_sha256": sha256_file(CONFIG),
        "price_file_sha256": got,
        "score": {
            "field": "DECISION.valence_hz",
            "definition": "the decoder's continuous centred V, before "
                          "thresholding and before inventory constraints",
            "statuses_scored": list(SCORED),
            "no_response_rule":
                "the decoder records V on NO_RESPONSE as well: with both "
                "readout populations silent, V = 0 - BASELINE_HZ_K8 = "
                "+0.844389816810345 Hz at full artifact precision. Fable "
                "addendum 4's fallback computation is therefore not needed, "
                "and silent contexts stay in the analysis with their actual "
                "finite readout, as §7 requires."},
        "label": {
            "definition": "G(t) = net return on notional of a hypothetical "
                          "fixed-notional long entered under the existing "
                          "fill convention and held H* market minutes, "
                          "including unchanged costs",
            "Y": "1 when G(t) > 0, else 0",
            "notional": xcfg["notional"], "fee_bps": xcfg["fee_bps"],
            "slippage_bps": xcfg["slippage_bps"],
            "shared": "one common G(t) for both branches",
            "analysis_only": "no learning event, no bankroll change, never "
                             "summed into an executable PnL"},
        "grid": {"rule": "observation status OK and (m+1)+delay+H* <= 390",
                 "computed_from": "session calendar and price file only, "
                                  "before either event log was opened",
                 "sessions": sorted({str(d) for d, _ in grid}),
                 "n": len(grid)},
        "coverage": cov,
        "per_branch": per_branch,
        "log_event_counts": logcounts,
        "sessions": [r.as_dict() for r in results],
        "delta_auc": d_auc,
        "n_qualifying_sessions": len(qualifying),
        "bootstrap": boot,
        "matched_participation": matched,
        "matched_participation_per_session": per_session_matched,
        "actions_and_trades": actions,
        "dependence": {
            "unique_sessions": len(by_session),
            "probes": len(rows),
            "probes_overlap": "each probe is one eligible minute and the "
                              f"holds are H* = {hstar} minutes long, so "
                              f"consecutive probes overlap by construction; "
                              f"they are never independent trials and are "
                              f"never summed",
            "actual_completed_trades": {b: actions[b]["trades"]
                                        for b in BRANCHES}},
        "conclusion": verdict,
        "integrity": integrity(run_id, summary),
        "evaluator_changed_nothing": {
            "event_log_sha256_before": before,
            "event_log_sha256_after": after,
            "unchanged": before == after},
        "elapsed_s": round(time.time() - t0, 2),
    }
    (HERE / "context_summary.json").write_text(json.dumps(out, indent=1))
    (HERE / "withheld-probe-table").write_text(json.dumps({
        "run_id": run_id, "selected_horizon_minutes": hstar,
        "columns": ["session", "minute", "market_ts", "v_trained",
                    "v_reference", "status_trained", "status_reference",
                    "action_trained", "action_reference", "G", "Y",
                    "gross_bps", "entry_minute", "exit_minute", "exit_ts"],
        "n": len(rows), "rows": rows}, indent=0))

    print(f"H* = {hstar}   paired probes {len(rows)} over "
          f"{len(by_session)} sessions")
    print(f"coverage trained {cov['trained_coverage']:.4f} reference "
          f"{cov['reference_coverage']:.4f} paired {cov['paired_coverage']:.4f}")
    for r in results:
        print(f"  {r.session}  n={r.n:4d} pos={r.n_pos:4d} neg={r.n_neg:4d}  "
              f"AUC_T={r.auc_trained if r.auc_trained is None else round(r.auc_trained, 4)}  "
              f"AUC_R={r.auc_reference if r.auc_reference is None else round(r.auc_reference, 4)}  "
              f"d={r.delta if r.delta is None else round(r.delta, 4)}  "
              f"{'qualifies' if r.qualifies else r.reason}")
    print(f"DELTA_AUC = {d_auc}  over {len(qualifying)} qualifying sessions")
    if boot.get("draws"):
        print(f"bootstrap  mean {boot['mean']:+.4f}  sd {boot['sd']:.4f}  "
              f"2.5% {boot['p2.5']:+.4f}  97.5% {boot['p97.5']:+.4f}  "
              f"above zero {boot['fraction_of_draws_above_zero']:.3f}")
    print(f"conclusion {verdict['conclusion']}: {verdict['reason']}")
    print(f"logs unchanged: {before == after}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
