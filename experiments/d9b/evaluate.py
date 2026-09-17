#!/usr/bin/env python
"""
The D9(b) frozen evaluation — amendment §5, Fable addendum 7.

    .venv/bin/python experiments/d9b/evaluate.py [run_id]

A **read-only post-run script**, and deliberately not a new evaluator. The
probe grid, the labels, the log reader, the coverage rule, the per-session AUC,
``DELTA_AUC``, the paired session bootstrap, matched participation and the
A/B/C classification are `experiments/d7/evaluate.py`'s and
`flytrade.metrics`'s, imported from the file **as committed** and not modified:

    §7 ... a `experiments/d9b/evaluate.py` may import from it but never
    modifies it, and D7's `withheld-probe-table` stays byte-identical.

The D7 module is loaded by explicit file path under the name ``d7_evaluate``
rather than by ``import evaluate``, because this file has the same name and
would otherwise import itself. Loading it executes its imports and constants
and nothing else: its ``main`` runs only under ``__main__``, so nothing of D7's
is written, and this script hashes ``withheld probe table`` and
``evaluate.py`` before and after itself to say so with a number.

Writes ``withheld d9b context summary`` and
``withheld probe table``. Opens the two FROZEN event logs read-only and
hashes them before and after.

**RETROSPECTIVE COMPARISON ON PREVIOUSLY EXAMINED DATES.**
"""
from __future__ import annotations

import importlib.util
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import date as _date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
D7 = ROOT / "experiments" / "d7"
sys.path.insert(0, str(ROOT))

from flytrade import historical as H       # noqa: E402
from flytrade import metrics as MET        # noqa: E402


def _load_d7():
    """The committed D7 evaluator, by path, under a name that is not ours."""
    spec = importlib.util.spec_from_file_location("d7_evaluate",
                                                  D7 / "evaluate.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["d7_evaluate"] = mod
    spec.loader.exec_module(mod)
    return mod


E7 = _load_d7()
sha256_file = E7.sha256_file
probe_grid = E7.probe_grid
labels = E7.labels
frozen_decisions = E7.frozen_decisions
integrity = E7.integrity
BRANCHES = E7.BRANCHES
SCORED = E7.SCORED

RUNS = HERE / "runs"
CONFIG = HERE / "config.json"
#: the D7 files this script must leave exactly as it found them
D7_IMMUTABLE = ("experiments/d7/evaluate.py", "withheld probe table",
                "withheld d7 context summary",
                "the registered horizon artifact", "experiments/d7/config.json")


def main(argv) -> int:
    t0 = time.time()
    cfg = json.loads(CONFIG.read_text())
    hstar = int(cfg["horizon"]["H"])
    xcfg = cfg["execution"]
    delay = int(xcfg["delay_minutes"])
    before_d7 = {p: sha256_file(ROOT / p) for p in D7_IMMUTABLE}

    summary = json.loads((HERE / "frozen_summary.json").read_text())
    if summary["config"]["exit_policy"] != cfg["exit_policy"]:
        raise SystemExit("the run was made under a different exit policy")
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
            "reject_trained": (et.get("rejection") or {}).get("reason"),
            "reject_reference": (er.get("rejection") or {}).get("reason"),
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
            rj = (e.get("rejection") or {}).get("reason")
            if rj:
                c[f"rejected:{rj}"] += 1
        ex = summary["branches"][b]["execution"]
        tal = summary["branches"][b]["partitions"]["FROZEN"]["tally"][
            "after_execution_constraints"]
        actions[b] = {"per_decision_round": dict(c),
                      "trades": ex["trades"], "wins": ex["wins"],
                      "losses": ex["losses"], "net_pnl": ex["net_pnl"],
                      "blocked_by_fixed_hold": tal.get("blocked_by_fixed_hold", 0),
                      "after_execution": tal}

    verdict = MET.classify(results, boot, cov)

    # ---- 7. the pre-stated INCONCLUSIVE rule, applied as written --------
    rule = cfg["inconclusive_rule_stated_before_the_run"]
    n_qual = len(qualifying)
    min_sessions = int(cfg["evaluation"]["min_qualifying_sessions"])
    inconclusive = {
        "rule_as_committed": rule,
        "qualifying_sessions": n_qual,
        "min_qualifying_sessions": min_sessions,
        "evaluation_inconclusive": n_qual < min_sessions,
        "coverage_limited": (cov["paired_coverage"]
                             < float(cfg["evaluation"]["min_coverage"]))}

    after = {b: sha256_file(p) for b, p in logs.items()}
    after_d7 = {p: sha256_file(ROOT / p) for p in D7_IMMUTABLE}
    out = {
        "artifact": "flytrade-d9b-context-1",
        "wave": "D9(b)",
        "label": cfg["label"],
        "exit_policy": cfg["exit_policy"],
        "run_id": run_id,
        "written_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "selected_horizon_minutes": hstar,
        "horizon_artifact_sha256": sha256_file(D7 / "registered-horizon-artifact"),
        "config_sha256": sha256_file(CONFIG),
        "price_file_sha256": got,
        "evaluator_reused": {
            "module": "experiments/d7/evaluate.py",
            "functions": ["probe_grid", "labels", "frozen_decisions",
                          "integrity", "sha256_file"],
            "constants": {"BRANCHES": list(BRANCHES), "SCORED": list(SCORED)},
            "modified": False,
            "sha256_before": before_d7, "sha256_after": after_d7,
            "unchanged": before_d7 == after_d7},
        "score": {
            "field": "DECISION.valence_hz",
            "definition": "the decoder's continuous centred V, before "
                          "thresholding and before inventory constraints",
            "statuses_scored": list(SCORED),
            "policy_reject_note":
                "under the fixed-hold exit policy a decoded SELL observed "
                "while holding is recorded as POLICY_REJECT with reason "
                "FIXED_HOLD. Its continuous V is the same reading it would "
                "have carried under any exit policy, and D7's rule already "
                "scores POLICY_REJECT, so the paired set stays "
                "inventory-blind."},
        "label_definition": {
            "definition": "G(t) = net return on notional of a hypothetical "
                          "fixed-notional long entered under the existing "
                          "fill convention and held H market minutes, "
                          "including unchanged costs",
            "Y": "1 when G(t) > 0, else 0",
            "notional": xcfg["notional"], "fee_bps": xcfg["fee_bps"],
            "slippage_bps": xcfg["slippage_bps"],
            "shared": "one common G(t) for both branches",
            "analysis_only": "no learning event, no bankroll change, never "
                             "summed into an executable PnL",
            "same_definition_as_the_executed_episode":
                "this wave's episodes were executed under the same anchor and "
                "the same costs; the alignment invariant in alignment.json "
                "reports the per-episode difference"},
        "grid": {"rule": "observation status OK and (m+1)+delay+H <= 390",
                 "computed_from": "session calendar and price file only, "
                                  "before either event log was opened",
                 "sessions": sorted({str(d) for d, _ in grid}),
                 "n": len(grid)},
        "coverage": cov,
        "per_branch": per_branch,
        "log_event_counts": logcounts,
        "sessions": [r.as_dict() for r in results],
        "delta_auc": d_auc,
        "n_qualifying_sessions": n_qual,
        "bootstrap": boot,
        "matched_participation": matched,
        "matched_participation_per_session": per_session_matched,
        "actions_and_trades": actions,
        "inconclusive_rule": inconclusive,
        "dependence": {
            "unique_sessions": len(by_session),
            "probes": len(rows),
            "probes_overlap": "each probe is one eligible minute and the "
                              f"holds are H = {hstar} minutes long, so "
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
        "exit_policy": cfg["exit_policy"],
        "columns": ["session", "minute", "market_ts", "v_trained",
                    "v_reference", "status_trained", "status_reference",
                    "action_trained", "action_reference", "reject_trained",
                    "reject_reference", "G", "Y", "gross_bps", "entry_minute",
                    "exit_minute", "exit_ts"],
        "n": len(rows), "rows": rows}, indent=0))

    print(f"H = {hstar}   paired probes {len(rows)} over "
          f"{len(by_session)} sessions")
    print(f"coverage trained {cov['trained_coverage']:.4f} reference "
          f"{cov['reference_coverage']:.4f} paired {cov['paired_coverage']:.4f}")
    for r in results:
        print(f"  {r.session}  n={r.n:4d} pos={r.n_pos:4d} neg={r.n_neg:4d}  "
              f"AUC_T={r.auc_trained if r.auc_trained is None else round(r.auc_trained, 4)}  "
              f"AUC_R={r.auc_reference if r.auc_reference is None else round(r.auc_reference, 4)}  "
              f"d={r.delta if r.delta is None else round(r.delta, 4)}  "
              f"{'qualifies' if r.qualifies else r.reason}")
    print(f"DELTA_AUC = {d_auc}  over {n_qual} qualifying sessions")
    if boot.get("draws"):
        print(f"bootstrap  mean {boot['mean']:+.4f}  sd {boot['sd']:.4f}  "
              f"2.5% {boot['p2.5']:+.4f}  97.5% {boot['p97.5']:+.4f}  "
              f"above zero {boot['fraction_of_draws_above_zero']:.3f}")
    print(f"conclusion {verdict['conclusion']}: {verdict['reason']}")
    print(f"pre-stated INCONCLUSIVE rule fires: "
          f"{inconclusive['evaluation_inconclusive']}")
    print(f"logs unchanged: {before == after}   "
          f"D7 files unchanged: {before_d7 == after_d7}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
