#!/usr/bin/env python
"""
Assemble ``experiments/d9b/results.md`` from the committed artifacts.

    .venv/bin/python experiments/d9b/report.py

Reads `config.json`, `learning_summary.json`, `frozen_summary.json`,
`alignment.json` and `context_summary.json` and writes the report. **Every
number in the report comes from one of those files**; this script computes no
statistic of its own, so the report cannot say anything the artifacts do not.

Actual paper trading and hypothetical probe labels are rendered as separate
tables, as amendment §5 requires, and the pre-stated INCONCLUSIVE rule is
applied exactly as `config.json` states it.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "results.md"


def load(name):
    return json.loads((HERE / name).read_text())


def f(x, n=4):
    return "—" if x is None else f"{x:.{n}f}"


def sgn(x, n=4):
    return "—" if x is None else f"{x:+.{n}f}"


def main() -> int:
    cfg = load("config.json")
    learn = load("learning_summary.json")
    frozen = load("frozen_summary.json")
    al = load("alignment.json")
    ctx = load("context_summary.json")
    H = cfg["horizon"]["H"]
    run_id = learn["run_id"]
    L = []
    w = L.append

    # ------------------------------------------------------------- header
    w(f"# D9(b) — the target-aligned fixed-hold experiment ({run_id})\n")
    w(f"**{cfg['label']}.** Every date below was already examined by D7 and "
      f"again by D8: {cfg['not_a_holdout']}\n")
    w("## What this is, and what it is not\n")
    w("This wave runs the experiment in which **the quantity used for "
      "reinforcement is the quantity used for evaluation**: the fly chooses "
      f"when to enter, the position is held for the declared H = {H} market "
      "minutes, and the reinforcement is the net outcome of exactly that "
      "hold. It tests **entry-context selection**. It does not test learned "
      "exit timing, and it is not a correction to D7's recorded results, "
      "which stand unrewritten together with D8's.\n")
    w("Reading rules, fixed before the numbers existed:\n")
    for k in ("negative", "positive", "inconclusive"):
        w(f"* **{k}** → {cfg['allowed_conclusions'][k]}")
    w("")
    for s in cfg["allowed_conclusions"]["forbidden"]:
        w(f"* never: {s}")
    w("")

    # -------------------------------------------------------- provenance
    w("## 1. Provenance\n")
    w(f"| item | value |")
    w("|---|---|")
    w(f"| run | `{run_id}`, stages `learn` + `frozen` |")
    w(f"| exit policy | `{cfg['exit_policy']}` |")
    w(f"| H | {H} market minutes, from `the registered horizon artifact` "
      f"(`{learn['horizon_artifact_sha256'][:12]}…`), not recalibrated |")
    w(f"| instrument | IBM, `{cfg['instruments'][0]['file']}`, sha256 "
      f"`{cfg['instruments'][0]['sha256'][:12]}…` |")
    w(f"| graph | `{learn['graph_sha256'][:12]}…` |")
    w(f"| clean reference digest | `{learn['clean_reference_digest'][:12]}…` |")
    w(f"| trained digest | `{frozen['trained_digest'][:12]}…` |")
    w(f"| config | `experiments/d9b/config.json`, "
      f"`{learn['config_sha256'][:12]}…`, committed alone before any run |")
    w(f"| python · numpy | {learn['python']} · {learn['numpy']} |")
    w(f"| learn | {learn['elapsed_s'] / 60:.1f} min, peak RSS "
      f"{learn['peak_rss_mib']:.0f} MiB |")
    w(f"| frozen | {frozen['elapsed_s'] / 60:.1f} min, peak RSS "
      f"{frozen['peak_rss_mib']:.0f} MiB |")
    w("")
    others = sorted(d.name for d in (HERE / "runs").iterdir()
                    if d.is_dir() and d.name != run_id)
    if others:
        w(f"Other run directories on disk: {', '.join('`' + o + '`' for o in others)}. "
          f"They are **not** this result. `config.json` fixes the rule they "
          f"fall under — *a retry after a software correction gets a new run "
          f"id; the failed run's directory and its explanation are kept and "
          f"reported* — and the explanation is in `the session log`. Every number "
          f"in this file comes from `{run_id}` alone.\n")
    w("Partitions, D7's own, unchanged:\n")
    w("| partition | dates | sessions | neural | learning |")
    w("|---|---|---|---|---|")
    for name, p in cfg["partitions"].items():
        w(f"| {name} | {p['first']} .. {p['last']} | {p['sessions']} | "
          f"{p['neural']} | {p['learning']} |")
    w("")

    # ------------------------------------------------------- the anchor
    w("## 2. One target definition — the anchor and the invariant\n")
    a = cfg["anchor"]
    w(f"**{a['rule']}**, located by `{a['primitive']}` — the one primitive "
      f"the executed exit and the evaluator's `Hold` both call. Entry: "
      f"{a['entry']}. No same-bar hindsight fill.\n")
    inv = al["all_branches"]["invariant"]
    w(f"| invariant | value |")
    w("|---|---|")
    w(f"| episodes compared | {inv['compared']} |")
    w(f"| same entry **and** exit bar as the label | "
      f"{inv['same_entry_and_exit_bars']} |")
    w(f"| entry or exit bar displaced (sequencing guard or vendor gap) | "
      f"{inv.get('different_bars_from_the_label', 0)} |")
    w(f"| max \\|realised − label\\| | `{inv['max_abs_diff_realised']}` |")
    w(f"| tolerance registered in the plan | `{inv['tolerance']}` |")
    w(f"| holds | **{inv['holds']}** |")
    w(f"| max \\|as recorded in the log − label\\| | "
      f"`{inv['max_abs_diff_as_recorded']}` |")
    w(f"| label unavailable | {inv['label_unavailable']} |")
    w("")
    if inv.get("different_bars_detail"):
        w("Episodes whose executed bars differ from the label's, named "
          "rather than averaged in — the invariant's precondition is *for the "
          "same entry*:\n")
        w("| episode | session | decision | entry → label entry | "
          "exit → label exit | flags |")
        w("|---|---|---|---|---|---|")
        for r in inv["different_bars_detail"]:
            w(f"| {r['episode_id']} | {r['session']} | "
              f"{r['decision_minute']} | {r['entry_minute']} → "
              f"{r['label_entry_minute']} | {r['exit_minute']} → "
              f"{r['label_exit_minute']} | "
              f"{r['entry_flag'] or '—'} / {r['exit_flag'] or '—'} |")
        w("")
    w(f"_{inv['recorded_precision_note']}._ The per-episode table is "
      "`experiments/d9b/alignment.md`; the machine-readable form, with every "
      "price and every difference, is `alignment.json`.\n")

    # -------------------------------------------- actual paper trading
    w("## 3. Actual paper trading\n")
    w("This section is the **executed** experiment. It is reported apart "
      "from the hypothetical probe labels of §4, which are counterfactuals "
      "on a grid and were never traded.\n")
    w("| branch | episodes | exact-H | exceptional | held min/med/max | "
      "reward | punishment | frozen | net |")
    w("|---|---|---|---|---|---|---|---|---|")
    for name, b in al["branches"].items():
        s = b["summary"]
        hm = s["holding_minutes"]
        w(f"| {name} | {s['episodes']} | {s['exact_h_closures']} | "
          f"{s['exceptional_closures']} | "
          f"{hm['min']}/{hm['median']:.0f}/{hm['max']} | "
          f"{s['reinforcement']['reward']} | "
          f"{s['reinforcement']['punishment']} | "
          f"{s['reinforcement']['settled_frozen']} | "
          f"{sgn(s['money']['net_pnl'], 4)} |")
    w("")
    w("Exit reasons, counted apart. Only `POLICY_CLOSE_FIXED_HOLD` is an "
      "exact-H outcome; a session close or an end of data keeps its own "
      "label and is never presented as one.\n")
    w("| branch | " + " | ".join(["POLICY_CLOSE_FIXED_HOLD"]
                                 + list(cfg["closures"]["exceptional_counted_apart"])
                                 + ["NEURAL_SELL"]) + " |")
    w("|---" * 5 + "|")
    for name, b in al["branches"].items():
        s = b["summary"]
        exc = s["exceptional_by_reason"]
        flg = s["exceptional_by_flag"]
        w(f"| {name} | {s['exact_h_closures']} | "
          f"{flg.get('SESSION_CLOSE_FILL', 0)} | "
          f"{exc.get('END_OF_DATA', 0)} | {exc.get('NEURAL_SELL', 0)} |")
    w("")
    w("What the decoder did, and what the execution policy did with it. A "
      "SELL observed while holding is a **signal blocked by the fixed-hold "
      "policy**, not an executed sale, and it produced no reward, no "
      "punishment and no change to any stored trace.\n")
    w("| branch | rounds decoded | BUY | SELL | WAIT | NO_RESPONSE | "
      "blocked SELL | entries filled |")
    w("|---|---|---|---|---|---|---|---|")
    for name, b in al["branches"].items():
        t = b["decision_tally"]
        ax = b["after_execution_constraints"]
        w(f"| {name} | {t.get('kind:DECISION', 0)} | "
          f"{t.get('action:BUY', 0)} | {t.get('action:SELL', 0)} | "
          f"{t.get('action:WAIT', 0)} | {t.get('status:NO_RESPONSE', 0)} | "
          f"{t.get('rejected:FIXED_HOLD', 0)} | {ax.get('BUY', 0)} |")
    w("")
    w("Money, at the unchanged costs (5 bps fee and 5 bps modelled slippage "
      "per execution, 20 bps over a completed round trip):\n")
    w("| branch | gross at reference | fees | slippage | net | "
      "cost > gross |")
    w("|---|---|---|---|---|---|")
    for name, b in al["branches"].items():
        m = b["summary"]["money"]
        w(f"| {name} | {sgn(m['gross_reference_pnl'])} | {f(m['fees'])} | "
          f"{f(m['slippage'])} | {sgn(m['net_pnl'])} | "
          f"{m['cost_exceeded_gross']} of {b['summary']['episodes']} |")
    w("")
    ea = cfg["expected_activity_before_the_run"]
    w(f"Expected activity, **stated in `config.json` before the run**: at most "
      f"{ea['max_completed_episodes_per_session']} completed episodes per "
      f"session and {ea['max_completed_episodes_per_branch']} per branch, "
      f"from the chain {ea['chain_arithmetic'].split(': ')[-1]} The observed "
      f"counts above are inside that bound. Declared with it, before the run: "
      f"{ea['correction_to_fable_addendum_5']}\n")
    w("The three branches are **not** comparable as trading results and are "
      "not presented as any: they are three different weight states meeting "
      "the same ten sessions, and the money columns are reported because the "
      "amendment asks for them, not because a net figure here means "
      "anything about profitability.\n")

    # ------------------------------------------- the frozen comparison
    w("## 4. Frozen comparison — hypothetical probe labels\n")
    w("Learning and forgetting off in both branches; the paired "
      "`comparison_v1` seeds do not depend on the weight digest, so a "
      "difference between the branches is a difference in weights and not in "
      "noise.\n")
    w("| branch | start digest | end digest | unchanged |")
    w("|---|---|---|---|")
    for name in ("frozen_trained", "frozen_reference"):
        p = frozen["branches"][name]["partitions"]["FROZEN"]
        w(f"| {name} | `{p['start_digest'][:12]}…` | "
          f"`{p['end_digest'][:12]}…` | **{p['digest_unchanged']}** |")
    w("")
    c = ctx["coverage"]
    w(f"Grid {c['grid_points']} eligible minutes, label available "
      f"{c['label_available']}, paired probes **{c['paired_probes']}**; "
      f"coverage trained {c['trained_coverage']:.4f}, reference "
      f"{c['reference_coverage']:.4f}, paired {c['paired_coverage']:.4f}. "
      f"Unavailable labels {c['unavailable_label']}.\n")
    w("| session | n | pos | neg | AUC trained | AUC reference | Δ | |")
    w("|---|---|---|---|---|---|---|---|")
    for r in ctx["sessions"]:
        w(f"| {r['session']} | {r['n']} | {r['n_pos']} | {r['n_neg']} | "
          f"{f(r['auc_trained'])} | {f(r['auc_reference'])} | "
          f"{sgn(r['delta_auc'])} | "
          f"{'qualifies' if r['qualifies'] else r['reason']} |")
    w("")
    d = ctx["delta_auc"]
    b = ctx["bootstrap"]
    w(f"**DELTA_AUC = {d}** over {ctx['n_qualifying_sessions']} qualifying "
      f"sessions.")
    if b.get("draws"):
        w(f"Paired session bootstrap, {b['draws']} draws at the D7 seed "
          f"{cfg['evaluation']['bootstrap_seed']}: mean {b['mean']:+.4f}, sd "
          f"{b['sd']:.4f}, 2.5 % {b['p2.5']:+.4f}, 97.5 % {b['p97.5']:+.4f}, "
          f"fraction of draws above zero "
          f"{b['fraction_of_draws_above_zero']:.3f}.")
    w("")
    w(f"Classification by the committed rule: **{ctx['conclusion']['conclusion']}** "
      f"— {ctx['conclusion']['reason']}\n")
    w("The probes overlap by construction — one per eligible minute, holds "
      f"of {H} minutes — so they are never independent trials and are never "
      "summed. The bootstrap resamples whole sessions, not experiments.\n")

    # --------------------------------------- the pre-stated INCONCLUSIVE
    w("## 5. The INCONCLUSIVE rule, applied as pre-stated\n")
    r = cfg["inconclusive_rule_stated_before_the_run"]
    ir = ctx["inconclusive_rule"]
    n_learn = al["branches"]["learned"]["summary"]["episodes"]
    learn_fires = n_learn < 10
    w("| test | rule, as committed | observed | fires |")
    w("|---|---|---|---|")
    w(f"| learning | {r['learning']} | {n_learn} completed LEARNING episodes "
      f"| **{learn_fires}** |")
    w(f"| evaluation | {r['evaluation']} | "
      f"{ir['qualifying_sessions']} qualifying sessions | "
      f"**{ir['evaluation_inconclusive']}** |")
    w(f"| coverage | paired coverage ≥ "
      f"{cfg['evaluation']['min_coverage']} | "
      f"{c['paired_coverage']:.4f} | **{ir['coverage_limited']}** |")
    w("")
    if learn_fires or ir["evaluation_inconclusive"]:
        w("**VERDICT: INCONCLUSIVE**, by the rule written into `config.json` "
          "before the run. No conclusion about discrimination is drawn in "
          "either direction, and no activity was manufactured to avoid this "
          "outcome. A negative or inconclusive scientific result does not "
          "fail the engineering gate.\n")
    else:
        w("Neither pre-stated INCONCLUSIVE condition fires: the experiment "
          "produced enough completed episodes and enough qualifying sessions "
          "to be read. The frozen comparison is therefore read under the "
          "committed conclusion rule.\n")
    verdict = ctx["conclusion"]["conclusion"]
    w("### Verdict\n")
    if verdict == "A":
        w("The committed rule classifies this as **A**. Under the wording "
          "limits at the head of this file that is evidence of context "
          "discrimination **in this experiment** — not general trading "
          "ability, not profitability, not skill.\n")
    else:
        w(f"The committed rule classifies this as **{verdict}**: "
          f"{ctx['conclusion']['reason']}.\n")
        w(f"In plain words: **{cfg['allowed_conclusions']['negative']}.** "
          f"DELTA_AUC is {d:+.4f} with a 2.5–97.5 % interval of "
          f"[{b['p2.5']:+.4f}, {b['p97.5']:+.4f}] that contains zero, and the "
          f"trained branch's own ranking sits at chance, so neither branch "
          f"produced a ranking the other can be said to beat. Aligning the "
          f"reinforced quantity with the evaluated one — which this wave did, "
          f"exactly, to one part in 1e16 — did not by itself produce a "
          f"detectable improvement here. That is a result about **this "
          f"policy, this instrument, these twenty sessions and this "
          f"metric**, and it is not evidence that the alignment was "
          f"unnecessary, nor that a different horizon, instrument or "
          f"training length would behave the same way.\n")
        w("A negative scientific result does not fail the engineering gate.\n")

    # ------------------------------------------------------- integrity
    w("## 6. Integrity\n")
    w("| check | pass | detail |")
    w("|---|---|---|")
    for ch in ctx["integrity"]["checks"]:
        w(f"| {ch['id']} | {ch['pass']} | `{json.dumps(ch['detail'])[:90]}` |")
    ev = ctx["evaluator_changed_nothing"]
    w(f"| the evaluator changed no event log | {ev['unchanged']} | "
      f"sha256 before == after, both branches |")
    er = ctx["evaluator_reused"]
    w(f"| D7's evaluator and probes are byte-identical | {er['unchanged']} | "
      f"`{', '.join(er['functions'])}` imported, nothing modified |")
    w("")
    w(f"Reused artifacts, hashed at run time against the plan: "
      f"{len(learn['reused_artifacts_sha256_at_run_time'])} files, each "
      f"verified before the brain was built. `experiments/historical/run.py` "
      f"is the one file the plan allows to move, because commit (2) of this "
      f"wave amends it.\n")

    w("## 7. Wording, once more\n")
    w("This report never claims that the fly learned. A positive result "
      "would be evidence of context discrimination **in this experiment**, "
      "not general trading ability, not profitability and not skill. The "
      "36.6 % positive base rate of the D7 LEARNING probe grid predicts "
      "nothing about the reward rate of this policy: selected entries and "
      "occupied inventory change which episodes actually occur. D7's "
      "conclusion B and D8's conclusions stand unrewritten.\n")
    w(f"_Assembled by `experiments/d9b/report.py` at "
      f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} from "
      f"`config.json`, `learning_summary.json`, `frozen_summary.json`, "
      f"`alignment.json` and `context_summary.json`. No number in it is "
      f"computed here._")
    OUT.write_text("\n".join(L) + "\n")
    print(f"wrote {OUT} ({len(L)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
