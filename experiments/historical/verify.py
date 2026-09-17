#!/usr/bin/env python
"""
The nine pass conditions of PROTOCOL §8, checked against the run's own log.

    .venv/bin/python experiments/historical/verify.py [run_id]

Amendment D6 §8: "Do not claim completion because the importer returns rows.
Show actual market context passing through the existing sensory / neural /
decision / outcome / learning chain."

Each condition below is answered from the canonical `events.jsonl` and from
`summary.json`, and each answer carries the event ids or counts behind it, so
that a reader can go to the line in the log rather than trust the verdict.
Writes `pass_conditions.json`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
RUNS = HERE / "runs"


def load(run_id: str, branch: str):
    log = RUNS / run_id / branch / "events.jsonl"
    return [json.loads(l) for l in log.read_text().splitlines() if l.strip()]


def main(argv) -> int:
    summary = json.loads((HERE / "summary.json").read_text())
    run_id = argv[1] if len(argv) > 1 else summary["run_id"]
    ev = load(run_id, "learned")
    ref = load(run_id, "reference")

    def span(log, name):
        """The index range between a partition's two PARTITION events.

        Selecting by index rather than by a ``partition`` field is what makes
        this work for every event kind: only the decision-side events carry
        that field, while the boundary markers bracket all of them.
        """
        lo = hi = None
        for i, e in enumerate(log):
            if e["kind"] == "PARTITION" and e.get("partition") == name:
                if e.get("boundary") == "start":
                    lo = i
                else:
                    hi = i
        return log[lo:hi + 1] if lo is not None and hi is not None else []

    learning = span(ev, "LEARNING")
    frozen_learned = span(ev, "FROZEN")
    out = []

    def add(name, ok, detail):
        out.append({"id": name, "pass": bool(ok), "detail": detail})

    # P1 --------------------------------------------------------------
    dec = [e for e in learning if e["kind"] == "DECISION"]
    by_sym = {}
    for e in dec:
        if e.get("observation_status") == "OK" and e.get("stimulus"):
            by_sym.setdefault(e["symbol"], e)
    budget = summary["encoder"]["drive_budget_hz"]
    inside = all(abs(e["stimulus"]["total_drive_hz"] - budget) < 1e-6
                 for e in by_sym.values())
    add("P1", len(by_sym) == 2 and inside,
        {"instruments_with_an_encoded_OK_observation": sorted(by_sym),
         "example_episode_ids": {k: v["episode_id"] for k, v in by_sym.items()},
         "declared_drive_budget_hz": budget,
         "total_drive_hz": {k: v["stimulus"]["total_drive_hz"]
                            for k, v in by_sym.items()}})

    # P2 --------------------------------------------------------------
    vecs, kcs = {}, {}
    for e in dec:
        o = e.get("observation") or {}
        if o.get("normalized"):
            vecs.setdefault(e["symbol"], set()).add(
                tuple(round(v, 9) for v in o["normalized"].values()))
        r = e.get("readout") or {}
        if r.get("kc_fraction") is not None:
            kcs.setdefault(e["symbol"], set()).add(round(r["kc_fraction"], 9))
    add("P2", all(len(v) > 1 for v in vecs.values())
        and all(len(v) > 1 for v in kcs.values()),
        {"distinct_normalised_feature_vectors": {k: len(v) for k, v in vecs.items()},
         "distinct_kenyon_active_fractions": {k: len(v) for k, v in kcs.items()}})

    # P3 --------------------------------------------------------------
    valid = [e for e in dec if e["readout_status"] == "VALID"
             and e.get("dataset_label") == "HISTORICAL_MARKET"]
    add("P3", len(valid) > 0,
        {"valid_decisions_on_historical_observations": len(valid),
         "first_episode_id": valid[0]["episode_id"] if valid else None,
         "first_market_ts": valid[0]["market_ts"] if valid else None,
         "actions": {a: sum(1 for e in valid if e["decoded_action"] == a)
                     for a in ("BUY", "SELL", "WAIT")}})

    # P4 --------------------------------------------------------------
    dec_eps = {e["episode_id"] for e in valid}
    execs = [e for e in learning if e["kind"] == "EXECUTION"]
    linked = [e for e in execs if e["episode_id"] in dec_eps]
    add("P4", len(linked) > 0,
        {"execution_events": len(execs), "linked_to_a_valid_decision": len(linked),
         "first_episode_id": linked[0]["episode_id"] if linked else None})

    # P5 --------------------------------------------------------------
    exec_eps = {e["episode_id"] for e in linked}
    outs = [e for e in learning if e["kind"] == "OUTCOME"
            and e["episode_id"] in exec_eps]
    with_account = [e for e in outs if e.get("account")]
    add("P5", len(with_account) > 0,
        {"outcome_events": len(outs), "with_an_ACCOUNT_field": len(with_account),
         "first_episode_id": outs[0]["episode_id"] if outs else None,
         "first_net_pnl": outs[0]["net_pnl"] if outs else None})

    # P6 --------------------------------------------------------------
    learns = [e for e in learning if e["kind"] == "LEARNING"]
    accepted = [e for e in learns if e.get("accepted")
                and int(e.get("synapses_depressed", 0) or 0) > 0]
    p = summary["branches"]["learned"]["partitions"]["LEARNING"]
    add("P6", len(accepted) > 0
        and p["end_digest"] != summary["clean_reference_digest"],
        {"learning_events": len(learns), "accepted_with_depression": len(accepted),
         "total_synapses_depressed": sum(int(e["synapses_depressed"])
                                         for e in accepted),
         "start_digest": p["start_digest"], "end_digest": p["end_digest"],
         "clean_reference_digest": summary["clean_reference_digest"],
         "digest_moved": p["end_digest"] != p["start_digest"]})

    # P7 --------------------------------------------------------------
    chain_ep = accepted[0]["episode_id"] if accepted else None
    kinds = sorted({e["kind"] for e in ev if e.get("episode_id") == chain_ep})
    need = {"DECISION", "EXECUTION", "OUTCOME", "LEARNING"}
    in_round = any(e["kind"] == "ROUND"
                   and any(c.get("episode_id") == chain_ep
                           for c in e.get("candidates", []))
                   for e in ev)
    add("P7", need <= set(kinds) and in_round,
        {"episode_id": chain_ep, "kinds_found": kinds,
         "appears_in_a_ROUND_event": in_round})

    # P8 --------------------------------------------------------------
    f = summary["branches"]["learned"]["partitions"]["FROZEN"]
    frozen_learns = [e for e in frozen_learned if e["kind"] == "LEARNING"]
    settled = [e for e in ev if e["kind"] == "OUTCOME"
               and e.get("settlement") == "SETTLED_FROZEN"]
    r = summary["branches"]["reference"]["partitions"]["FROZEN"]
    ref_learns = [e for e in ref if e["kind"] == "LEARNING"]
    add("P8", f["start_digest"] == f["end_digest"]
        and not frozen_learns and not ref_learns
        and r["start_digest"] == r["end_digest"],
        {"learned_start_digest": f["start_digest"],
         "learned_end_digest": f["end_digest"],
         "learned_digest_unchanged": f["start_digest"] == f["end_digest"],
         "reference_start_digest": r["start_digest"],
         "reference_end_digest": r["end_digest"],
         "reference_digest_unchanged": r["start_digest"] == r["end_digest"],
         "LEARNING_events_in_frozen": {"learned": len(frozen_learns),
                                       "reference": len(ref_learns)},
         "settled_frozen_outcomes": len(settled)})

    # P9 --------------------------------------------------------------
    res = {}
    for bname, b in summary["branches"].items():
        for pname, part in b["partitions"].items():
            if "execution" in part:
                res[f"{bname}/{pname}"] = part["execution"]["reconciliation"][
                    "residual"]
    add("P9", all(abs(v) < 1e-6 for v in res.values()),
        {"residuals": res, "tolerance": 1e-6})

    # -- event-order and clock invariants over the real logs ------------
    order_ok, clock_ok = True, True
    steps = {}
    for name, log in (("learned", ev), ("reference", ref)):
        first = {}
        for i, e in enumerate(log):
            first.setdefault((e.get("episode_id"), e["kind"]), i)
        for ep in {e["episode_id"] for e in log if e.get("kind") == "OUTCOME"}:
            if not (first[(ep, "DECISION")] < first[(ep, "EXECUTION")]
                    < first[(ep, "OUTCOME")]):
                order_ok = False
        for kind in ("DECISION", "EXECUTION", "OUTCOME"):
            ts = [e["market_ts"] for e in log
                  if e["kind"] == kind and e.get("market_ts")]
            if ts != sorted(ts):
                clock_ok = False
        # the one place the *interleaved* market clock steps back, and why
        seq = [(e["kind"], e["market_ts"]) for e in log if e.get("market_ts")]
        back = [(a, b) for a, b in zip(seq, seq[1:]) if b[1] < a[1]]
        steps[name] = {
            "backward_steps": len(back),
            "all_exactly_60s": all(a[1] - b[1] == 60 for a, b in back),
            "all_decision_to_outcome": all(
                {a[0], b[0]} == {"DECISION", "OUTCOME"} for a, b in back),
            "horizon_settlements": sum(
                1 for e in log if e["kind"] == "OUTCOME"
                and e.get("close_reason") == "POLICY_CLOSE")}
    add("OBSERVER-ORDER", order_ok,
        {"rule": "DECISION < EXECUTION < OUTCOME for every settled episode, "
                 "in both branches"})
    add("OBSERVER-CLOCK", clock_ok,
        {"rule": "market_ts is non-decreasing within each event kind, in "
                 "both branches",
         "interleaved_backward_steps": steps,
         "explanation":
             "a horizon settlement fills at the OPEN of the minute whose "
             "bar_end produced that same round's decision, so the OUTCOME's "
             "market_ts is 60 s before the DECISION written just above it. "
             "The exit time was fixed by the horizon clock at entry and uses "
             "no information from that round; the episode's own order "
             "DECISION < EXECUTION < OUTCOME is unaffected."})

    result = {"run_id": run_id, "conditions": out,
              "all_pass": all(c["pass"] for c in out)}
    (HERE / "pass_conditions.json").write_text(json.dumps(result, indent=1))
    for c in out:
        print(f"{c['id']:<16} {'PASS' if c['pass'] else 'FAIL'}  "
              f"{json.dumps(c['detail'])[:150]}")
    print(f"\nall_pass = {result['all_pass']}")
    return 0 if result["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
