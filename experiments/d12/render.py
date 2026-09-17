#!/usr/bin/env python
"""`runs/d12-001/report.md`: every paragraph of the owner's D12 spec, answered.

Rendering only. Every number comes from ``grid/evaluation.json``, which
``experiments/d12/analyse.py`` wrote; nothing is computed here, so the report
cannot disagree with the artifact it reads.

**Declared deviation of form**: ``d12_001.json`` registers the analysis entry
point as ``evaluate.py``; it is ``analyse.py`` and this renderer is
``render.py``, because ``evaluate`` and ``report`` are module names
``experiments/d7``, ``d8`` and ``d11`` already own and one pytest session
shares one ``sys.modules``. The registered file is not edited after
registration.
"""

from __future__ import annotations

import json
from pathlib import Path


def _f(v, digits=4, dash="—"):
    if v is None:
        return dash
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:,.{digits}f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def _i(row: dict) -> str:
    if not row or row.get("lo") is None:
        return "—"
    return f"[{row['lo']:+.4f}, {row['hi']:+.4f}]"


def _pct(v, digits=2):
    return "—" if v is None else f"{v * 100:.{digits}f} %"


def write(ev: dict, path: Path, *, log=print) -> Path:
    L: list[str] = []
    A = L.append
    school = ev["school"]
    ceiling = ev["ceiling"]
    mirror = ev["mirror"]
    primary, secondary = ev["primary"], ev["secondary"]
    d11 = ev["d11_001_secondary"]
    weights = school["final_weights"]

    A("# d12-001 — school mode: relative cohort reinforcement")
    A("")
    A("**One thing changed: the teacher.** The store, the cutoff `T`, the tick "
      "grid, the partitions, the clean reference, `pons_encoder_v2`, "
      "`admission_v2`, the k = 8 `comparison_v1` readout, the stored decoder, "
      "the 900-second horizon, the plasticity operator and its learning rate "
      "are the objects `d11-001` ran. What is new is `relative_cohort_v1` — a "
      "candidate is graded against the other candidates of its own tick — and "
      "school mode, in which **no position is ever opened** and every eligible "
      "candidate becomes a lesson.")
    A("")
    A("Registered before any number existed: `experiments/d12/PLAN.md` and "
      "`experiments/d12/d12_001.json`, committed alone (step (ii)); then the "
      "lesson ceiling, the cohort-size distribution, the two grids' balances "
      "and the mirror diagnostic, numbers only and with no brain (step (iii)); "
      "then the run. **No RPC, no live hour, no signing, no funds, no real "
      "money.**")
    A("")
    A("Profit is recorded and is **not** the criterion. Predictive learning is "
      "not declared from PnL, failure is not declared because the fly loses "
      "money, an interval that includes 0 is reported as *compatible with "
      "sampling variation*, and a lower BUY rate alone is not learning "
      "success.")
    A("")

    # ------------------------------------------------------------ mirror
    A("## 1. The owner's cheap account first — is the trained brain the "
      "negative of the untrained one?")
    A("")
    mo, ma, mw = mirror["overall"], mirror["auc"], mirror["within_tick"]
    ols = mo["ols_trained_on_reference"]
    A(f"Computed in step (iii) from the two score files `d11-001` already "
      f"wrote, over the **{mo['n']:,}** rows `VALID` under both brains. No "
      f"brain ran and nothing was recomputed. Full table: "
      f"`experiments/d12/mirror_diagnostic.md`.")
    A("")
    A("| quantity | value |")
    A("|---|---|")
    A(f"| Pearson r (trained, reference) | {_f(mo['pearson_r'])} |")
    A(f"| Spearman ρ | {_f(mo['spearman_rho'])} |")
    A(f"| Kendall τ | {_f(mo['kendall_tau'])} |")
    A(f"| OLS `trained = a + b · reference`: a | {_f(ols['a'])} Hz |")
    A(f"| OLS b | **{_f(ols['b'])}** |")
    A(f"| R² | {_f(ols['r2'])} |")
    A(f"| row pairs reversed | "
      f"{_pct(mo['reversed_pairs']['fraction'])} of "
      f"{mo['reversed_pairs']['pairs']:,} |")
    A(f"| mean within-tick Kendall τ | **{_f(mw['mean_tau'])}** over "
      f"{mw['ticks_with_a_tau']:,} ticks |")
    A(f"| ticks with τ exactly −1 | {mw['ticks_with_tau_at_minus_one']:,} |")
    A(f"| AUC(trained) | {_f(ma['auc_trained'])} |")
    A(f"| AUC(reference) | {_f(ma['auc_reference'])} |")
    A(f"| AUC(−reference) | {_f(ma['auc_minus_reference'])} |")
    A(f"| AUC(trained) − (1 − AUC(reference)) | "
      f"**{_f(ma['residual_of_auc_trained_from_one_minus_auc_reference'])}** |")
    A("")
    A("The mechanistic reading — that fifteen punishments depressed the "
      "approach pathway in proportion to the prior valence, so the trained "
      "valence is a decreasing affine function of the untrained one — is a "
      "**hypothesis** that `b` and `τ` test. It is **not a finding** until the "
      "owner states it as one.")
    A("")

    # ----------------------------------------------------------- the rule
    A("## 2. The teacher — `relative_cohort_v1`")
    A("")
    A("The cohort is the `admission_v2`-eligible candidates of **one tick** "
      "that have a settled evaluator label. With `n` the cohort size after the "
      "`UNRESOLVED` drop and ranks ascending by the label's integer net in "
      "wei, average ranks for ties:")
    A("")
    A("```")
    A("s_i = 2 · (rank_i − 1) / (n − 1) − 1        in [−1, +1]")
    A("```")
    A("")
    A(f"`s > 0` is a reward and `s < 0` a punishment of amount `|s|`; `s = 0` "
      f"is neutral and delivers nothing. **`n_min = {school['n_min']}`**: a "
      f"smaller cohort teaches nothing and is counted. **No clipping can "
      f"occur** — `|s| ≤ 1` by construction — and neither `REINFORCE_CAP` nor "
      f"`reinforce_full_scale` is consulted. Both of the owner's examples, "
      f"`+14/+3/−2/−7/−18/−61 %` and `−3/−8/−15/−28/−50/−82 %`, give "
      f"`s = +1, +0.6, +0.2, −0.2, −0.6, −1`; a known-answer test asserts it.")
    A("")
    A("**The financial net and the pedagogical signal are two columns on every "
      "`LESSON` record and are never merged.** A cohort in which every member "
      "lost money still teaches which member lost least. No profit is "
      "falsified: the net is reported as it is. This is relative cohort "
      "reinforcement and is never called a profit reward.")
    A("")
    A(f"Against D11's absolute rule, which met this window with 15 "
      f"punishments, 0 rewards and 11 of 15 updates clipped at the 0.131 "
      f"scale: this wave applied **{school['lessons']['applied']:,} lessons** — "
      f"**{school['lessons']['reward']:,} reward**, "
      f"**{school['lessons']['punishment']:,} punishment**, "
      f"{school['lessons']['neutral']:,} neutral — and **0 clipped**, because "
      f"clipping is impossible under this rule.")
    A("")

    # ---------------------------------------------------------- the school
    A("## 3. The school — every eligible candidate is a lesson")
    A("")
    A(f"`SCHOOL`, `LEARN`, over the **{school['ticks']:,}** LEARNING ticks from "
      f"the clean reference `{school['start_digest'][:12]}…` under "
      f"`from_clean_reference`. **No paper position was opened or held**, no "
      f"cap of six, no rotation, no hold mode. Final digest "
      f"**`{school['end_digest'][:12]}…`** (SCHOOL).")
    A("")
    A("| | value |")
    A("|---|---|")
    A(f"| candidate evaluations (presentations of a candidate) | "
      f"{school['candidate_evaluations']:,} |")
    A(f"| readout presentations (k = 8 replicates each) | "
      f"{school['presentations']:,} |")
    A(f"| **lesson ceiling**, registered in step (iii) before the brain ran | "
      f"**{ceiling['lesson_ceiling']:,}** (after the `UNRESOLVED` drop "
      f"{ceiling['lesson_ceiling_after_unresolved_drop']:,}) |")
    A(f"| cohorts formed | {school['cohorts']['formed']:,} |")
    A(f"| **lessons applied** | **{school['lessons']['applied']:,}** "
      f"({school['lessons']['accepted']:,} accepted by the credit assigner, "
      f"{school['lessons']['neutral']:,} neutral, "
      f"{school['lessons']['rejected_by_credit_total']:,} refused) |")
    A(f"| lessons discarded | {school['lessons']['discarded_total']:,} "
      f"`{school['lessons']['discarded']}` |")
    A(f"| cohort size applied | min {_f(school['cohort_size']['min'])}, "
      f"median {_f(school['cohort_size']['median'], 1)}, max "
      f"{_f(school['cohort_size']['max'])} |")
    A(f"| amount `\\|s\\|` | min {_f(school['lessons']['amount']['min'])}, "
      f"median {_f(school['lessons']['amount']['median'])}, max "
      f"{_f(school['lessons']['amount']['max'])} |")
    A(f"| clipped at a cap | **{school['lessons']['clipped']}** (impossible "
      f"under this rule) |")
    A(f"| cohort-size distribution in LEARNING (market only, step (iii)) | "
      f"median {_f(ceiling['cohort_size_distribution']['median'], 1)}, max "
      f"{ceiling['cohort_size_distribution']['max']}, "
      f"{ceiling['cohort_size_distribution']['ticks_below_n_min']:,} ticks "
      f"below n_min |")
    A("")
    A("**Maturity and no lookahead.** A lesson matures at the first tick whose "
      "`cutoff ≥ lesson cutoff + 902 s`; 902 is not a multiple of the 30-second "
      "cadence, so that tick is always `cutoff + 930` — 28 seconds after the "
      "outcome it is graded on. Matured lessons of one cohort are applied "
      "together, in `stable_id` order, **before** that tick's presentations. A "
      "lesson whose `cutoff + 902 > T` is discarded, counted and never applied, "
      "and no lesson is ever applied at a FROZEN tick.")
    A("")
    A("**Determinism.** The first 100 LEARNING ticks, run twice from the clean "
      "reference: `runs/d12-001/determinism.json`, and a test asserts the "
      "checkpoint digest and the `LESSON`-log sha256 are identical.")
    A("")

    # -------------------------------------------------------- the curve
    A("## 4. The learning curve, and the weights")
    A("")
    A("For every lesson, the valence the readout produced **at presentation** "
      "and the `s` that arrived 902 seconds later. It is prospective by "
      "construction: the brain had not been taught these lessons when it "
      "scored them. The window is the last 500 applied lessons.")
    A("")
    A("| lessons | window n | Spearman(valence, s) | mean within-cohort τ | "
      "cumulative Spearman | weights: mean | at floor | at ceiling |")
    A("|---|---|---|---|---|---|---|---|")
    for point, w in zip(school["learning_curve"], school["weights"]):
        win, cum = point["window"], point["cumulative"]
        A(f"| {point['lessons']:,} | {win['n']:,} | "
          f"{_f(win['spearman_valence_vs_s'])} | "
          f"{_f(win['mean_within_cohort_kendall_tau'])} | "
          f"{_f(cum['spearman_valence_vs_s'])} | {_f(w['mean'], 6)} | "
          f"{_pct(w['at_floor_fraction'])} | {_pct(w['at_ceiling_fraction'])} |")
    A("")
    A(f"At the end of LEARNING: mean gain **{_f(weights['mean'], 6)}**, L2 norm "
      f"{_f(weights['l2_norm'], 3)}, min {_f(weights['min'], 6)}, "
      f"**{_pct(weights['at_floor_fraction'])}** of "
      f"{weights['synapses']:,} plastic KC→MBON synapses at the floor "
      f"({_f(weights['floor'], 2)}) and "
      f"**{_pct(weights['at_ceiling_fraction'])}** at the ceiling (1.0).")
    A("")
    A("**A property of the operator, registered before the run so it cannot be "
      "mistaken for a result:** the plasticity rule only depresses and the "
      "clean reference starts with every gain exactly at 1.0, so a synapse *at "
      "the ceiling* is a synapse **no lesson has ever depressed**. The two "
      "fractions are reported separately as well as summed; the pre-registered "
      "condition reads the sum, as addendum 9 words it.")
    A("")

    # ------------------------------------------------------------- grids
    A("## 5. The frozen proof — later tokens she never received as lessons")
    A("")
    A(f"The FROZEN grid is `d11-001`'s, **reused**: the same rows, the same "
      f"evaluator labels and the same REFERENCE scores, verified rather than "
      f"assumed. "
      f"{ev['reference_verification']['rows_recomputed']:,} rows were re-scored "
      f"under the clean reference and compared with the reused valences: "
      f"**{ev['reference_verification']['compared']:,} compared, "
      f"{ev['reference_verification']['mismatched']} mismatched**, worst "
      f"|difference| "
      f"{ev['reference_verification']['max_abs_difference_hz']:.3e} Hz against "
      f"a 1e-9 Hz tolerance → "
      f"**{ev['reference_verification']['verdict']}**.")
    A("")
    A(f"* **primary** — FROZEN rows on tokens that were **never a lesson**: "
      f"{primary['rows']:,} rows over {primary['tokens']:,} tokens, "
      f"{primary['paired_labelled_rows']:,} with a settled label "
      f"({primary['class_balance']['positive']:,} positive / "
      f"{primary['class_balance']['negative']:,} negative).")
    A(f"* **secondary** — all FROZEN rows: {secondary['rows']:,} rows, "
      f"{secondary['paired_labelled_rows']:,} labelled "
      f"({secondary['class_balance']['positive']:,} positive / "
      f"{secondary['class_balance']['negative']:,} negative), reported "
      f"regardless of the verdict.")
    A("")
    A(f"Both brains read-only, digests verified before and after: SCHOOL "
      f"`{ev['meta']['school_digest'][:12]}…`, REFERENCE "
      f"`{ev['meta']['reference_digest'][:12]}…`. Paired neural coverage "
      f"**{_pct(secondary['paired_neural_coverage'])}** of "
      f"{secondary['rows']:,} rows.")
    A("")
    status = ev.get("readout_status") or {}
    if status:
        A("**Where the coverage went, as counts.** The readout status of every "
          "grid row under each brain:")
        A("")
        A("| branch | " + " | ".join(sorted(
            {k for c in status.values() for k in c})) + " |")
        keys = sorted({k for c in status.values() for k in c})
        A("|---|" + "---|" * len(keys))
        for branch, counts in status.items():
            A(f"| {branch} | " + " | ".join(f"{counts.get(k, 0):,}"
                                            for k in keys) + " |")
        A("")
        A(f"`NO_RESPONSE` is the decoder's name for a presentation whose k = 8 "
          f"replicates produced no usable readout. It is "
          f"{_pct((ev.get('no_response_rate') or {}).get('reference'))} of the "
          f"rows under REFERENCE and "
          f"**{_pct((ev.get('no_response_rate') or {}).get('school'))}** under "
          f"SCHOOL — the whole of the coverage shortfall, and the reason "
          f"condition 4 fails below. It is a number, not a reading.")
        A("")
    for name, block in (("primary", primary), ("secondary", secondary)):
        o = block["overall"]
        A(f"### {name.capitalize()} grid")
        A("")
        A("| | n | positive | AUC SCHOOL | AUC REFERENCE | ΔAUC | 95 % interval |")
        A("|---|---|---|---|---|---|---|")
        A(f"| **overall** | {o['n']:,} | {o['positive']:,} | "
          f"{_f(o['auc_school'])} | {_f(o['auc_reference'])} | "
          f"**{_f(o['delta_auc'])}** | {_i(o['interval'])} |")
        for row in block["per_block"]:
            A(f"| block {row['block']} | {row['n']:,} | {row['positive']:,} | "
              f"{_f(row['auc_school'])} | {_f(row['auc_reference'])} | "
              f"{_f(row['delta_auc'])} | {_i(row['interval'])} |")
        A("")
        A(f"**{o['wording']}.**")
        A("")
        A(f"The pre-registered reading of addendum 7, applied to that "
          f"interval: **{o['preregistered_reading']}**.")
        A("")
        for row in block["per_block"]:
            A(f"* {row['wording']} — {row['preregistered_reading']}.")
        A("")
        A(f"Descriptive: Spearman(score, net) is {_f(o['spearman_school'])} for "
          f"SCHOOL and {_f(o['spearman_reference'])} for REFERENCE. The "
          f"per-row score difference SCHOOL − REFERENCE has mean "
          f"{_f(block['suppression']['score_difference']['mean'])} Hz, SD "
          f"{_f(block['suppression']['score_difference']['sd'])}, range "
          f"[{_f(block['suppression']['score_difference']['min'])}, "
          f"{_f(block['suppression']['score_difference']['max'])}].")
        A("")
    A("**An AUC near 0.5 is not evidence that no signal exists**, and nothing "
      "above is a claim about a rate in the market.")
    A("")

    # ------------------------------------------------------- suppression
    A("## 6. Suppression")
    A("")
    A(f"θ = {ev['meta']['theta_hz']:.6f} Hz, the stored k = 8 margin.")
    A("")
    A("| grid | rows | BUY rate SCHOOL | BUY rate REFERENCE | change |")
    A("|---|---|---|---|---|")
    for name, block in (("primary", primary), ("secondary", secondary)):
        s = block["suppression"]
        A(f"| {name} | {s['rows_valid_in_both']:,} | "
          f"{_pct(s['buy_rate_school'])} | {_pct(s['buy_rate_reference'])} | "
          f"{((s['buy_rate_school'] or 0) - (s['buy_rate_reference'] or 0)) * 100:+.2f} pp |")
    for name, row in secondary["suppression"]["by_outcome_class"].items():
        A(f"| secondary, later outcome {name} | {row['n']:,} | "
          f"{_pct(row['buy_rate_school'])} | {_pct(row['buy_rate_reference'])} "
          f"| {((row['buy_rate_school'] or 0) - (row['buy_rate_reference'] or 0)) * 100:+.2f} pp |")
    for row in secondary["suppression"]["per_block"]:
        A(f"| secondary, block {row['block']} | {row['n']:,} | "
          f"{_pct(row['buy_rate_school'])} | {_pct(row['buy_rate_reference'])} "
          f"| {((row['buy_rate_school'] or 0) - (row['buy_rate_reference'] or 0)) * 100:+.2f} pp |")
    A("")
    for name, block in (("primary", primary), ("secondary", secondary)):
        s = block["suppression"]
        A(f"* **{name}** — {s['class_contrast_wording']}; under the registered "
          f"rule that is **{s['reading']}**.")
    A("")
    A("**A lower BUY rate alone is not learning success**, and nothing else is "
      "said in words.")
    A("")
    A("Continuous scores over the rows valid in both branches:")
    A("")
    A("| grid | branch | mean | SD | min | median | max |")
    A("|---|---|---|---|---|---|---|")
    for name, block in (("primary", primary), ("secondary", secondary)):
        for branch, row in block["suppression"]["score"].items():
            A(f"| {name} | {branch} | {_f(row['mean'], 3)} | "
              f"{_f(row['sd'], 3)} | {_f(row['min'], 3)} | "
              f"{_f(row['median'], 3)} | {_f(row['max'], 3)} |")
    A("")

    # ------------------------------------------------------- d11 beside
    A("## 7. `d11-001` beside `d12-001`, on the same secondary grid")
    A("")
    A("The same rows, the same labels and the same REFERENCE scores. The only "
      "difference between the two lines is the brain in the left-hand column "
      "and the teacher that made it. This is **descriptive**: two runs, one "
      "window, and no interval was pre-registered for the difference between "
      "them.")
    A("")
    A("| wave | teacher | lessons or episodes | AUC (trained/school) | "
      "AUC REFERENCE | ΔAUC | 95 % interval | BUY rate |")
    A("|---|---|---|---|---|---|---|---|")
    so = secondary["overall"]
    A(f"| `d11-001` | absolute profit | 15 episodes, 0 reward / 15 punishment, "
      f"11 clipped | {_f(d11['auc_trained'])} | {_f(d11['auc_reference'])} | "
      f"{_f(d11['delta_auc'])} | {_i(d11['interval'])} | "
      f"{_pct(d11['buy_rate_trained'])} |")
    A(f"| `d12-001` | relative cohort | {school['lessons']['applied']:,} "
      f"lessons, {school['lessons']['reward']:,} reward / "
      f"{school['lessons']['punishment']:,} punishment, 0 clipped | "
      f"{_f(so['auc_school'])} | {_f(so['auc_reference'])} | "
      f"{_f(so['delta_auc'])} | {_i(so['interval'])} | "
      f"{_pct(secondary['suppression']['buy_rate_school'])} |")
    A("")
    A("Per block, ΔAUC with its interval:")
    A("")
    A("| block | `d11-001` | `d12-001` |")
    A("|---|---|---|")
    for a_, b_ in zip(d11["per_block"], secondary["per_block"]):
        A(f"| {a_['block']} | {_f(a_['delta_auc'])} "
          f"[{a_['lo']:+.4f}, {a_['hi']:+.4f}] | {_f(b_['delta_auc'])} "
          f"{_i(b_['interval'])} |")
    A("")
    A(f"`d11-001`'s labelled denominator was {d11['paired_labelled_rows']:,} "
      f"rows ({d11['class_balance']['positive']:,} positive / "
      f"{d11['class_balance']['negative']:,} negative) against "
      f"{secondary['paired_labelled_rows']:,} here "
      f"({secondary['class_balance']['positive']:,} / "
      f"{secondary['class_balance']['negative']:,}); the small difference is "
      f"the rows one branch or the other did not score `VALID`.")
    A("")

    # ------------------------------------------------------ frozen loops
    A("## 8. The two FROZEN loop branches (paper results, descriptive)")
    A("")
    A("The loop over the FROZEN partition with learning off, one position at a "
      "time, the market rebuilt from `t0` without the brain. They are **not** "
      "the primary comparison — two loop branches cannot share rows, which is "
      "why the grid exists — and their PnL is descriptive. **The school branch "
      "has no paper results by design: it never opened a position.**")
    A("")
    A("| branch | episodes | settled frozen | net (ETH) | fees | wins | "
      "holds (s) | unresolved | digest unchanged |")
    A("|---|---|---|---|---|---|---|---|---|")
    for name in ("frozen_school", "frozen_reference"):
        p = (ev.get("frozen") or {}).get(name)
        d = (ev.get("frozen_digests") or {}).get(name) or {}
        if not p:
            A(f"| {name} | — | — | — | — | — | — | — | not run |")
            continue
        A(f"| {name} | {p['episodes']} | {p['settled_frozen']} | "
          f"{_f(p['net_pnl_eth'], 8)} | {_f(p['fees_eth'], 8)} | "
          f"{p['wins']} | {_f(p['holding_seconds']['min'], 0)}–"
          f"{_f(p['holding_seconds']['max'], 0)} | {p['unresolved_count']} | "
          f"{_f(d.get('unchanged'))} |")
    A("")
    for name in ("frozen_school", "frozen_reference"):
        p = (ev.get("frozen") or {}).get(name)
        if p:
            A(f"* **{name}** — per-round actions `{p['per_round_action']}`, "
              f"after execution `{p['after_execution']}`")
    A("")

    # ------------------------------------------------------- conditions
    A("## 9. The six inconclusive conditions, one by one")
    A("")
    A("| condition (verbatim, addendum 9) | measured | threshold | verdict |")
    A("|---|---|---|---|")
    for c in ev["conditions"]:
        A(f"| {c['condition']} | {c['detail']} | {c['threshold']} | "
          f"{'**FAIL**' if c['fails'] else 'PASS'} |")
    A("")
    failed = [c for c in ev["conditions"] if c["fails"]]
    if failed:
        A(f"**{len(failed)} condition(s) failed, so the learning evaluation is "
          f"declared INCONCLUSIVE** rather than stretching the interpretation. "
          f"The thresholds were registered before the run and are not loosened "
          f"after it. The ΔAUC above is reported with its interval and is "
          f"**not** interpreted as a finding about learning.")
    else:
        A("**No condition failed.** That is a statement about the sample, not "
          "about the result: the comparison above stands as it is written, "
          "with its interval and its pre-registered wording.")
    A("")
    A("The secondary grid is reported regardless of the verdict, as "
      "registered.")
    A("")

    # ------------------------------------------------------ what it cannot
    A("## 10. What this cannot say")
    A("")
    A("It cannot say the fly is profitable, and it was not asked to. Within "
      "this window the only thing that changed between SCHOOL and REFERENCE is "
      "8.4 hours of school, so a difference is a difference between one brain "
      "that was taught and one that was not — but it is one window, one store "
      "and one seed schedule. It is **not** comparable with `d10-001`. It is "
      "compared with `d11-001` only on the secondary grid, and that comparison "
      "is descriptive.")
    A("")
    A("PONS — the wallet/sniper track in `~/Documentos/PONS` — was **not** "
      "touched, and no wallet feature entered the brain: adding it here would "
      "have changed what the fly sees at the same time as the teacher, and "
      "nothing could then have been attributed to either.")
    A("")
    A("No real money, no signing, no funds, no network connection of any "
      "kind. **This wave made zero RPC calls.**")

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L) + "\n")
    log(f"wrote {path}")
    return path


def main(argv=None) -> int:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import d12lib as L                                      # noqa: PLC0415
    run = L.RUNS / L.RUN_ID
    write(json.loads((run / "grid" / "evaluation.json").read_text()),
          run / "report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
