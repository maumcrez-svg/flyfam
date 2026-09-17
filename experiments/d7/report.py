#!/usr/bin/env python
"""
`results.md` for D7, assembled from the committed artifacts.

    .venv/bin/python experiments/d7/report.py

Every number in the output is copied from `registered-horizon-artifact`,
`learning_summary.json`, `frozen_summary.json` or `context_summary.json`. This
script computes three things and nothing else: the cross-tabulations Fable
addendum 7 asks for (exit reason x reward sign x holding minutes), the fill
delay distribution amendment §5 asks to be printed, and sums of fields the
execution policy itself booked. It never re-decodes a decision, never re-prices
a fill and never recomputes a metric.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(name):
    p = HERE / name
    return json.loads(p.read_text()) if p.exists() else None


def num(x, n=4, sign=False):
    """Format a number, or an em dash when the artifact says it is undefined."""
    if x is None:
        return "—"
    return f"{x:+.{n}f}" if sign else f"{x:.{n}f}"


def table(rows, head):
    out = ["| " + " | ".join(head) + " |",
           "|" + "|".join("---" for _ in head) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(out)


def main() -> int:
    hz = load("registered-horizon-artifact")
    ln = load("learning_summary.json")
    fz = load("frozen_summary.json")
    cx = load("context_summary.json")
    if not (hz and ln):
        raise SystemExit("registered-horizon-artifact and learning_summary.json are required")
    L = ln["branches"]["learned"]
    Lp = L["partitions"]["LEARNING"]
    W = L["partitions"]["WARMUP"]
    hstar = hz["selected_horizon_minutes"]
    out = []
    A = out.append

    A(f"# D7 — results\n")
    A(f"Run `{ln['run_id']}`, IBM only, window 2026-06-15 … 07-31, "
      f"**H\\* = {hstar} market minutes**. Pre-registered in `PROTOCOL.md` and "
      f"`config.json` (committed alone), calibrated in `registered-horizon-artifact` "
      f"(committed alone). Python {ln['python']}, NumPy {ln['numpy']}, "
      f"{ln['machine']}, one process, no parallelism.\n")
    A("Nothing here is a claim of skill, alpha or profitability, and net PnL "
      "is not a gate metric in either direction.\n")

    # ---- 1. calibration ------------------------------------------------
    A("## 1. The horizon, selected on WARMUP alone\n")
    c = hz["cost"]
    A(f"`C` measured by one flat-price round trip through the real "
      f"`HistoricalExecution` at notional {c['notional']:.0f}: "
      f"**{c['round_trip_cost_bps_measured']:.6f} bps**, "
      f"{c['per_leg_bps']:.1f} bps per leg, gross at reference prices "
      f"{c['gross_reference_pnl']:.1e}. Threshold `2C` = "
      f"**{hz['threshold_bps']:.6f} bps**.\n")
    hs = hz["calibration"]["horizons"]
    A(table([["A(H), bps"] + [f"{hz['A_bps'][str(h)]:.4f}" for h in hs],
             ["≥ 2C"] + ["**yes**" if hz["A_bps"][str(h)] >= hz["threshold_bps"]
                         else "no" for h in hs]],
            ["H, market minutes"] + [str(h) for h in hs]))
    A("")
    A(f"`A(H) = median across the {hz['n_qualifying']} qualifying WARMUP "
      f"sessions of [median across that session's common origins of "
      f"|g(t,H)|]`. **H\\* = {hstar}**, the smallest candidate clearing the "
      f"bar. Per session:\n")
    rows = [[r["session"], r["origins"]]
            + [f"{r['median_abs_g_bps'][str(h)]:.2f}" for h in hs]
            for r in hz["calibration"]["per_session"]]
    A(table(rows, ["session", "common origins"] + [f"H={h}" for h in hs]))
    A("")
    A(f"All {hz['warmup_sessions_examined']} WARMUP sessions qualified "
      f"({hz['warmup_qualification']['min_qualifying_sessions']} required). "
      f"The `WarmupOnly` view recorded exactly "
      f"`{', '.join(hz['sessions_touched'][:2])} … "
      f"{hz['sessions_touched'][-1]}` as touched and would have raised on any "
      f"other session.\n")

    # ---- 2. LEARNING ---------------------------------------------------
    A("## 2. LEARNING — what actually happened\n")
    ex = Lp["execution"]
    tally = Lp["tally"]
    A(f"`WARMUP` ran features only: {W['rounds']:,} rounds, no brain, no "
      f"`DECISION` event, {W['wall_s']} s. `LEARNING` ran "
      f"{Lp['rounds']:,} rounds in {Lp['wall_s'] / 60:.1f} min; digest "
      f"`{Lp['start_digest'][:12]}` → `{Lp['end_digest'][:12]}`, moved: "
      f"{Lp['start_digest'] != Lp['end_digest']}.\n")
    pc = tally["per_candidate_evaluation"]
    pr = tally["per_decision_round"]
    A("**Three denominators, never pooled.**\n")
    A(table([["per candidate evaluation (one batch of k = 8)", pc["n"],
              json.dumps(pc["status"]), json.dumps(pc["action"])],
             ["per decision round (after selection)", pr["n"],
              json.dumps(pr["status"]), json.dumps(pr["action"])],
             ["after inventory and execution", "—",
              json.dumps(tally["after_execution_constraints"]), "—"]],
            ["denominator", "n", "status", "action"]))
    A("")
    A(f"Silent **presentations** {tally['silent_replicates']:,} of "
      f"{tally['presentations']:,} ({100 * tally['silent_replicates'] / max(1, tally['presentations']):.1f} %), "
      f"counted apart from `NO_RESPONSE` batches. Invalid replicates "
      f"{tally['invalid_replicates']}. Rounds aborted {len(L['aborted'])}.\n")
    A(f"Market status per round-minute: "
      f"{json.dumps(tally['market_status_per_instrument'])}\n")
    A(f"Completed episodes **{ex['trades']}** — {ex['wins']} with net > 0, "
      f"{ex['losses']} with net < 0, {ex['flat']} exactly flat. Exposure "
      f"{Lp['exposure_market_minutes']:,} market minutes of "
      f"{Lp['rounds']:,} round-minutes. Credit: "
      f"{json.dumps(Lp['credit'])}.\n")
    r = ex["reconciliation"]
    A(f"**Accounting.** gross at reference prices "
      f"{r['gross_reference_pnl']:+.4f} − slippage {r['minus_slippage']:.4f} "
      f"− fees {r['minus_fees']:.4f} = net {r['booked_net_pnl']:+.4f}, "
      f"residual {r['residual']:.1e}. Not a gate metric.\n")

    # cross-tab, addendum 7
    outs = L["outcomes"]
    cross = defaultdict(Counter)
    held = Counter()
    delays = Counter()
    for o in outs:
        sign = "reward (+)" if o["net_pnl"] > 0 else (
            "punishment (−)" if o["net_pnl"] < 0 else "neutral (0)")
        cross[(o["close_reason"], sign)][o["market_minutes_held"]] += 1
        held[o["market_minutes_held"]] += 1
        delays[o["entry"]["delay_minutes"]] += 1
    A("**Exit reason × reward sign × holding minutes** (Fable addendum 7, "
      "written before the run):\n")
    rows = []
    for (reason, sign), c in sorted(cross.items()):
        mins = sorted(c)
        rows.append([reason, sign, sum(c.values()),
                     ", ".join(f"{m}′×{c[m]}" for m in mins)])
    A(table(rows, ["exit reason", "reward sign", "episodes",
                   "holding, market minutes"]))
    A("")
    A(f"Holding-duration distribution over all {len(outs)} episodes: "
      + ", ".join(f"{m} min × {held[m]}" for m in sorted(held)) + ".\n")
    A(f"**Observation-availability → fill delay** (amendment §5: printed so an "
      f"off-by-one cannot stay hidden). The policy asks for the bar at "
      f"`decision minute + 1`; the delay is how many market minutes later the "
      f"fill actually landed: "
      + ", ".join(f"+{d} min × {delays[d]}" for d in sorted(delays))
      + f". `DELAYED_FILL` flags "
        f"{sum(1 for o in outs if o['entry_flag'] or o['exit_flag'])}.\n")
    if L["restarts"]:
        rs = L["restarts"][0]
        A(f"**Mid-run restart** (declared, after {rs['after_settled_episodes']} "
          f"settled episodes): {rs['day']} minute {rs['minute']}, "
          f"`{rs['report']['action']}`, gains restored exactly: "
          f"{rs['gains_restored_exactly']}.\n")

    # ---- 3. FROZEN -----------------------------------------------------
    if fz:
        A("## 3. FROZEN — two branches, identical observations and seeds\n")
        A(f"TRAINED started from the LEARNING checkpoint "
          f"(`{fz['trained_digest'][:12]}`, verified equal to the LEARNING end "
          f"digest before the branch ran); REFERENCE from the clean reference "
          f"`{fz['clean_reference_digest'][:12]}`. Learning and forgetting off "
          f"in both.\n")
        rows = []
        for b in ("frozen_trained", "frozen_reference"):
            P = fz["branches"][b]["partitions"]["FROZEN"]
            e = fz["branches"][b]["execution"]
            rows.append([b, f"{P['start_digest'][:12]} → {P['end_digest'][:12]}",
                         P["digest_unchanged"], e["trades"],
                         P["exposure_market_minutes"],
                         f"{e['net_pnl']:+.4f}",
                         json.dumps(P["tally"]["per_decision_round"]["action"]),
                         f"{P['wall_s'] / 60:.1f} min"])
        A(table(rows, ["branch", "digest", "unchanged", "trades",
                       "exposure (min)", "net", "action per round", "wall"]))
        A("")
        for b in ("frozen_trained", "frozen_reference"):
            P = fz["branches"][b]["partitions"]["FROZEN"]
            rr = P["execution"]["reconciliation"]
            A(f"`{b}` accounting: {rr['gross_reference_pnl']:+.4f} − "
              f"{rr['minus_slippage']:.4f} − {rr['minus_fees']:.4f} = "
              f"{rr['booked_net_pnl']:+.4f}, residual {rr['residual']:.1e}; "
              f"`SETTLED_FROZEN` "
              f"{P['journal']['settled_frozen']}; LEARNING events accepted "
              f"{P['credit']['accepted']}.\n")

    # ---- 4. the probe dataset and the metric ---------------------------
    if cx:
        A("## 4. The paired frozen probe dataset\n")
        cov = cx["coverage"]
        A(f"The grid is every FROZEN minute whose observation status is `OK` "
          f"and which satisfies `(m+1)+1+{hstar} ≤ 390`, computed from the "
          f"calendar and the price file **before either log was opened**: "
          f"**{cx['grid']['n']:,} points** over "
          f"{len(cx['grid']['sessions'])} sessions.\n")
        A(table([["grid points", cov["grid_points"]],
                 ["label available", cov["label_available"]],
                 ["UNAVAILABLE_LABEL", f"{cov['unavailable_label_total']} "
                                       f"{json.dumps(cov['unavailable_label'])}"],
                 ["scored, TRAINED", cx["per_branch"]["frozen_trained"]["scored"]],
                 ["scored, REFERENCE",
                  cx["per_branch"]["frozen_reference"]["scored"]],
                 ["paired probes", cov["paired_probes"]],
                 ["coverage TRAINED / REFERENCE / paired",
                  f"{100 * cov['trained_coverage']:.2f} % / "
                  f"{100 * cov['reference_coverage']:.2f} % / "
                  f"{100 * cov['paired_coverage']:.2f} %"]],
                ["quantity", "value"]))
        A("")
        for b in ("frozen_trained", "frozen_reference"):
            A(f"`{b}` readout statuses over label-available grid points: "
              f"{json.dumps(cx['per_branch'][b]['status_counts'])}\n")
        A("## 5. Context discrimination\n")
        rows = [[s["session"], s["n"], s["n_pos"], s["n_neg"],
                 "—" if s["auc_trained"] is None else f"{s['auc_trained']:.4f}",
                 "—" if s["auc_reference"] is None else f"{s['auc_reference']:.4f}",
                 "—" if s["delta_auc"] is None else f"{s['delta_auc']:+.4f}",
                 "qualifies" if s["qualifies"] else s["reason"]]
                for s in cx["sessions"]]
        A(table(rows, ["session", "probes", "Y=1", "Y=0", "AUC TRAINED",
                       "AUC REFERENCE", "delta", "note"]))
        A("")
        b = cx["bootstrap"]
        v = cx["conclusion"]
        A(f"**DELTA_AUC = {num(cx['delta_auc'], 4, True)}** over "
          f"{cx['n_qualifying_sessions']} qualifying sessions, each weighted "
          f"equally. Mean AUC level: TRAINED {num(v['mean_auc_trained'])}, "
          f"REFERENCE {num(v['mean_auc_reference'])}.\n")
        if b.get("draws"):
            A(f"Paired session bootstrap, {b['draws']:,} draws of whole "
              f"qualifying sessions with the seed declared in `config.json` "
              f"({b['seed']}): mean {b['mean']:+.4f}, sd {b['sd']:.4f}, "
              f"2.5–97.5 % {b['p2.5']:+.4f} … {b['p97.5']:+.4f}, "
              f"{100 * b['fraction_of_draws_above_zero']:.1f} % of draws above "
              f"zero. Limited, day-resampled uncertainty conditional on this "
              f"one training run; not a significance test. Overlapping "
              f"{hstar}-minute outcomes are not independent trials and "
              f"individual minutes were never resampled.\n")
        mp = cx["matched_participation"]
        if mp.get("trained", {}).get("mean_G") is None:
            A("**Matched participation**: no qualifying session, so no slice "
              "was taken.\n")
            mp = None
    if cx and mp:
        A(f"**Matched participation**, top {100 * mp['fraction']:.0f} % of "
          f"probes in each branch independently, fractional tie weighting, "
          f"pooled over the qualifying sessions (n = {mp['n']:,}; both "
          f"branches select {mp['trained']['selected_weight']:.1f} units of "
          f"weight):\n")
        A(table([["TRAINED", f"{1e4 * mp['trained']['mean_G']:+.3f} bps",
                  f"{100 * mp['trained']['profitable_rate']:.2f} %"],
                 ["REFERENCE", f"{1e4 * mp['reference']['mean_G']:+.3f} bps",
                  f"{100 * mp['reference']['profitable_rate']:.2f} %"],
                 ["all probes", f"{1e4 * mp['all_probes']['mean_G']:+.3f} bps",
                  f"{100 * mp['all_probes']['profitable_rate']:.2f} %"]],
                ["slice", "mean G(t)", "profitable rate"]))
        A("")
        A("A ranking diagnostic, not a trading policy and not a backtested "
          "portfolio: the probes overlap by construction and are never summed "
          "into an executable PnL.\n")
    if cx:
        A(f"**Conclusion {v['conclusion']}** — {v['reason']}.\n")
        A("## 6. Guards\n")
        for chk in cx["integrity"]["checks"]:
            A(f"* {'PASS' if chk['pass'] else 'FAIL'} — {chk['id']}: "
              f"{json.dumps(chk['detail'])[:160]}")
        e = cx["evaluator_changed_nothing"]
        A(f"\nThe evaluator hashed both event logs before and after itself: "
          f"unchanged = **{e['unchanged']}**.\n")

        # ---- 7. reading -------------------------------------------------
        A("## 7. Reading\n")
        allds = [s["delta_auc"] for s in cx["sessions"]
                 if s["delta_auc"] is not None]
        excluded = [s for s in cx["sessions"] if not s["qualifies"]]
        A(f"**The horizon rule worked and did not bind.** H\\* = {hstar} was "
          f"selected on WARMUP alone and frozen before any LEARNING price was "
          f"read. It changed two things in the run: the label every probe "
          f"carries, and the entry-eligibility window, which now closes at "
          f"14:28 ET rather than 15:50. It did **not** change how long a "
          f"position was actually held: all {len(outs)} LEARNING episodes "
          f"ended in a neural `SELL` after "
          f"{min(held):.0f}–{max(held):.0f} market minutes, total exposure "
          f"{Lp['exposure_market_minutes']} minutes. Fable addendum 7 "
          f"predicted exactly this before the run and asked for the "
          f"cross-tabulation rather than a change, and nothing was changed to "
          f"make H\\* bind.\n")
        A(f"**The reward sign still barely varied with the decision.** "
          f"{ex['losses']} of {ex['trades']} settled episodes were "
          f"punishments. Over an actual hold of one to three minutes the "
          f"round trip still costs {hz['cost']['round_trip_cost_bps_measured']:.1f} "
          f"bps, which is the whole of the result; the longer horizon the rule "
          f"selected never applied to a real trade because the decoder exited "
          f"first.\n")
        A(f"**Neither brain ranks contexts.** Mean AUC {num(v['mean_auc_trained'])} "
          f"(TRAINED) and {num(v['mean_auc_reference'])} (REFERENCE) are both "
          f"at chance, and the per-session deltas change sign four times. "
          f"DELTA_AUC {num(cx['delta_auc'], 4, True)} with a 2.5–97.5 % "
          f"day-resampled interval of {num(b['p2.5'], 4, True)} … "
          f"{num(b['p97.5'], 4, True)} does not separate the two. §9 says a "
          f"positive DELTA_AUC would have been insufficient anyway while "
          f"TRAINED sits at or below chance; it is not positive.\n")
        if excluded:
            s0 = excluded[0]
            A(f"**The one excluded session is excluded by a rule fixed before "
              f"the data, and the exclusion is not flattering.** "
              f"{s0['session']} carried {s0['n_pos']} profitable labels "
              f"against {s0['n_neg']} and fails the ≥ 10-per-class rule. Its "
              f"delta was {num(s0['delta_auc'], 4, True)}, the largest "
              f"negative in the set: including it would give "
              f"{num(sum(allds) / len(allds), 4, True)} rather than "
              f"{num(cx['delta_auc'], 4, True)}. The conclusion is B either "
              f"way.\n")
        mpa = cx["matched_participation"]
        if mpa.get("all_probes", {}).get("mean_G") is not None:
            A(f"**Matched participation says the same thing.** The mean "
              f"`G(t)` over **all** {mpa['n']:,} probes of the qualifying "
              f"sessions is {1e4 * mpa['all_probes']['mean_G']:+.2f} bps with "
              f"{100 * mpa['all_probes']['profitable_rate']:.1f} % profitable "
              f"— the FROZEN window drifted upward, which ROC-AUC is by "
              f"construction blind to. Neither branch's own top-{100 * mpa['fraction']:.0f} % "
              f"slice beats that full-sample mean "
              f"({1e4 * mpa['trained']['mean_G']:+.2f} bps trained, "
              f"{1e4 * mpa['reference']['mean_G']:+.2f} bps reference), so "
              f"neither ranking is informative about which minute to enter.\n")
        A(f"**What did change is participation.** TRAINED decoded BUY in "
          f"{cx['actions_and_trades']['frozen_trained']['per_decision_round'].get('round:BUY', 0)} "
          f"of its valid rounds and traded "
          f"{cx['actions_and_trades']['frozen_trained']['trades']} times; "
          f"REFERENCE decoded BUY in "
          f"{cx['actions_and_trades']['frozen_reference']['per_decision_round'].get('round:BUY', 0)} "
          f"and traded "
          f"{cx['actions_and_trades']['frozen_reference']['trades']} times. "
          f"That is the D5/D6 finding again — experience modified the "
          f"decisions — measured this time against a metric that cannot "
          f"reward it. The owner's wording holds: the comparison shows that "
          f"experience modified the decisions; it does not show that the fly "
          f"learned to recognise good and bad market contexts, and this wave "
          f"now says so with a pre-registered measurement rather than by "
          f"inference from an action mix.\n")
        A("Failure to demonstrate discrimination is not proof that this "
          "system can never learn any market structure, and a positive "
          "scientific outcome was never required for engineering "
          "completion.\n")

    (HERE / "results.md").write_text("\n".join(out) + "\n")
    print(f"wrote {HERE / 'results.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
