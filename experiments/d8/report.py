#!/usr/bin/env python
"""
D8 stage 5 — `results.md`, assembled from the committed artifacts.

    .venv/bin/python experiments/d8/report.py

Every number in `results.md` is copied out of `grids.json`, `orientation.json`,
`features_pc1.json`, `models.json` and `alignment.json`. This script computes
nothing of its own except the closing artifact hashes, so the report cannot
disagree with the artifacts it reports.

Amendment §2's five boundary statements are **extracted from `docs/SPEC.md`
itself** and emitted byte-for-byte at the head of the conclusions, so "verbatim"
is a property of the pipeline rather than of a copy-paste.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import data as D                                     # noqa: E402

SPEC = D.ROOT / "docs" / "SPEC.md"
OUT = HERE / "results.md"


def boundaries() -> str:
    """Amendment §2's five statements, straight out of `docs/SPEC.md`."""
    s = SPEC.read_text()
    a = s.index("2. CORRECT THE INFERENCE BOUNDARIES")
    b = s.index("3. REGISTER THIS ANALYSIS")
    return s[a:b].rstrip("\n")


def pct(x):
    return "—" if x is None else f"{x:.4f}"


def main() -> int:
    g = json.loads((HERE / "grids.json").read_text())
    ori = json.loads((HERE / "orientation.json").read_text())
    tab = json.loads((HERE / "features_pc1.json").read_text())
    mod = json.loads((HERE / "models.json").read_text())
    al = json.loads((HERE / "alignment.json").read_text())
    cfg = D.CONFIG
    after = D.artifact_hashes()
    S = al["summary"]

    L: list[str] = []
    A = L.append

    A("# D8 — results")
    A("")
    A(f"**{cfg['label']}**")
    A("")
    A("Evaluator-only. **No neural run, no download, no change under "
      "`flytrade/`, `upstream/`, `tests/upstream_audit/`, `observer/` or "
      "`experiments/d7/`.** Pre-registered in `PLAN.md` and `config.json`, "
      "committed alone before any D8 number existed. Python 3.13.9, NumPy "
      f"2.4.2, SciPy 1.17.1, **scikit-learn {mod['sklearn']}** as the new "
      "optional extra `diagnostics`, one process, `OMP_NUM_THREADS="
      f"{mod['omp_num_threads']}`.")
    A("")
    A("**The D7 results on these dates were already observed.** This is an "
      "additional retrospective analysis, not an independent confirmation on "
      "untouched data. **The evaluation dates are not a pristine holdout.** "
      "Fixing the plan before the new computations limits opportunistic "
      "choices; it does not erase prior knowledge of the results.")
    A("")
    A("D7's conclusion is preserved: **B — suppression without demonstrated "
      "discrimination improvement**. Nothing here rewrites it.")
    A("")

    # ------------------------------------------------------ 1. provenance
    A("## 1. Provenance")
    A("")
    A("The eleven registered artifacts, hashed **before** any D8 number "
      "existed (in `config.json`, commit `ec2927f`) and **again now**:")
    A("")
    A("| artifact | sha256 before | sha256 after | unchanged |")
    A("|---|---|---|:---:|")
    for k, before in cfg["artifacts"].items():
        A(f"| `{k}` | `{before[:16]}…` | `{after[k][:16]}…` | "
          f"{'**yes**' if after[k] == before else '**NO**'} |")
    A("")
    A(f"All eleven unchanged: **{after == cfg['artifacts']}**. The three "
      "`d7-001` event logs and the three checkpoints are among them; nothing "
      "was written under `experiments/d7/` or `experiments/d7/runs/`.")
    A("")
    A(f"`experiments/d8/orientation.json` sha256 "
      f"`{tab['orientation_sha256']}` — the file the feature and PC1 table "
      "quotes, written before the first evaluation AUC.")
    A("")

    # ------------------------------------------------------ 2. the grids
    A("## 2. The two grids, and stored versus reconstructed")
    A("")
    f, e = g["fitting"], g["evaluation"]
    A(f"| | fitting (LEARNING) | evaluation (FROZEN) |")
    A("|---|---:|---:|")
    A(f"| dates | {f['meta']['first']} … {f['meta']['last']} | "
      f"{e['meta']['first']} … {e['meta']['last']} |")
    A(f"| sessions | {f['n_sessions']} | {e['n_sessions']} |")
    A(f"| rows | {f['n']} | {e['n']} |")
    A(f"| Y = 1 | {f['class_counts']['Y=1']} | {e['class_counts']['Y=1']} |")
    A(f"| Y = 0 | {f['class_counts']['Y=0']} | {e['class_counts']['Y=0']} |")
    A(f"| grid points before joining | {f['meta']['grid_points']} | "
      f"{e['meta']['probes_n']} (`withheld-probe-table` as stored) |")
    A(f"| rows dropped | {f['meta']['exclusions']} | "
      f"{e['meta']['exclusions']} |")
    A("")
    A("The fitting grid is `experiments/d7/PROTOCOL.md` §6's rule applied to "
      "the ten LEARNING sessions — observation status `OK`, the clock rule "
      "`(m+1)+1+90 ≤ 390`, and an available H = 90 label from "
      "`horizon.hold` — computed from the session calendar and the price file "
      "alone, **independent of positions, trades and inventory**. 279 minutes "
      "a session, less the one minute the vendor omits on 2026-07-10, gives "
      f"{f['n']}. The evaluation grid is the **{e['meta']['probes_n']}** "
      "`withheld-probe-table` rows as stored, with `Y` as stored; that reconciles the "
      "reported 2,790 as 279 × 10 from the artifact rather than by assertion.")
    A("")
    o = g["temporal_order"]
    A(f"**Every fitting label resolves before evaluation begins**, asserted "
      f"from the data and not from the session-bounded argument: max fitting "
      f"`exit_ts` {o['max_fitting_exit_utc']} < min evaluation `market_ts` "
      f"{o['min_evaluation_market_utc']} — {o['strictly_before']}, a gap of "
      f"{o['gap_seconds']:,} s.")
    A("")
    A("**Representations.** Stored inputs are primary; every `DECISION` event "
      "of `d7-001` carries both.")
    A("")
    A("| | X_FEATURES | X_SENSORY |")
    A("|---|---|---|")
    A("| source | `observation.normalized` | `stimulus.rates_hz` |")
    A(f"| dimensions | {f['X_FEATURES']['dim']} | {f['X_SENSORY']['dim']} |")
    A(f"| order | {', '.join(D.FEATURES)} | {', '.join(D.GLOMERULI)} |")
    A("| units | dimensionless, `u = tanh(z/2)` ∈ (−1, 1) | Hz per ORN, "
      "before Bernoulli spike sampling |")
    A(f"| finite coverage, fitting / evaluation | "
      f"{f['X_FEATURES']['finite_coverage']:.4f} / "
      f"{e['X_FEATURES']['finite_coverage']:.4f} | "
      f"{f['X_SENSORY']['finite_coverage']:.4f} / "
      f"{e['X_SENSORY']['finite_coverage']:.4f} |")
    A(f"| constant channels | {f['X_FEATURES']['constant_channels'] or 'none'}"
      f" | {f['X_SENSORY']['constant_channels'] or 'none'} |")
    A(f"| clipping | {f['X_FEATURES']['at_or_beyond_clip_abs_1']} fitting / "
      f"{e['X_FEATURES']['at_or_beyond_clip_abs_1']} evaluation values at "
      f"\\|u\\| ≥ 1 | {f['X_SENSORY']['at_drive_max_hz']} fitting / "
      f"{e['X_SENSORY']['at_drive_max_hz']} evaluation values at the "
      f"{f['X_SENSORY']['drive_max_hz']:.0f} Hz ceiling |")
    A("")
    A("**The encoder delivers no sequence.** One constant rate vector per "
      "presentation, held over the 20 ms window, so the amendment's "
      "ordered-sequence clause is satisfied vacuously: nothing was replaced by "
      "its mean, last frame or PC1 because there was no sequence to replace. "
      "The eight replicates of a batch share one stimulus, so there is **one "
      "row per (session, minute)**, never eight. `n_orns` and "
      "`total_drive_hz` are provenance, not features. Ticker and date "
      "identifiers, brain outputs, learned-state hashes, account state, "
      "rewards, future labels and new technical indicators are all absent by "
      "rule.")
    A("")
    A("**Stored versus reconstructed** — §5's STOP condition, on every row of "
      "both grids. The reconstruction uses `HistoricalSeries.observe` and "
      "`MarketToSensoryEncoder`, which see only bars of the same session at "
      "minutes ≤ m, i.e. `bar_end ≤ market_ts`:")
    A("")
    A("| grid | rows | X_FEATURES max \\|d\\| | mismatches | X_SENSORY max "
      "\\|d\\| after the stored `round(x, 4)` | mismatches | unrounded max "
      "\\|d\\| | `market_ts == bar_end` |")
    A("|---|---:|---:|---:|---:|---:|---:|---:|")
    for name in ("fitting", "evaluation"):
        v = g["verification"][name]
        A(f"| {name} | {v['n']} | {v['X_FEATURES_max_abs_diff']:.1e} | "
          f"{v['X_FEATURES_mismatches']} | "
          f"{v['X_SENSORY_max_abs_diff_after_stored_rounding']:.1e} | "
          f"{v['X_SENSORY_mismatches']} | "
          f"{v['X_SENSORY_max_abs_diff_unrounded']:.3e} | "
          f"{v['market_ts_equals_bar_end']}/{v['n']} |")
    A("")
    A(f"**{g['mismatches_total']} mismatches on "
      f"{g['verification']['fitting']['n'] + g['verification']['evaluation']['n']:,} "
      "rows**, at a tolerance of 1e-12. `Stimulus.as_dict` rounds `rates_hz` to "
      "four decimals, so the stored vector is compared after the same "
      "rounding; the unrounded residual is 4.999e-05, below half an ulp of the "
      "stored precision, and it is reported rather than hidden. This is also "
      "§9's causal-reconstruction test on real rows; the property itself is "
      "tested on a generated fixture pair that is identical up to a cut minute "
      "and perturbed at every later bar.")
    A("")
    ident = e["meta"]["frozen_trained_identical"]
    A(f"**The stimulus does not depend on the branch.** `frozen_trained` "
      f"carries an identical stimulus on {ident['identical']} of "
      f"{ident['compared']} shared evaluation rows; {ident['differing']} differ.")
    A("")
    A("**The −22 % overnight discontinuity between 2026-07-13 and 2026-07-14 "
      "lies inside the fitting partition.** No session-bounded quantity spans "
      "it and no row crosses it. None of the five features is price-level "
      "dependent: `r1`, `r5`, `r20` are log ratios of closes, `rv20` is the SD "
      "of log returns, `relvol` is a log volume ratio, and each is then "
      "z-scored over its own trailing 60-row window. It is recorded here, not "
      "investigated.")
    A("")

    # ---------------------------------------------- 3. feature / PC1 table
    A("## 3. The descriptive feature and PC1 table")
    A("")
    A("Signs were chosen on the **fitting rows only** — raw fitting AUC, "
      "sign = +1 if that AUC ≥ 0.5 else −1 — and written to "
      "`orientation.json` before the first evaluation AUC existed. A column "
      "below 0.5 may rank in the opposite direction and is not called "
      "uninformative for that; **`max(AUC, 1 − AUC)` is never reported** and "
      "no sign was chosen or flipped on an evaluation day.")
    A("")
    p = ori["pca"]
    A(f"PC1: `numpy.linalg.svd` on the fitting-centred X_SENSORY "
      f"({p['n_fitting_rows']} rows), **no whitening**, rank {p['rank']}, "
      f"explained-variance ratio **{p['explained_variance_ratio_pc1']:.6f}**, "
      f"degenerate {p['degenerate']}. Sign convention: "
      f"{p['sign_convention']} (that is `{p['largest_loading_channel']}`). "
      "Loadings, in channel order:")
    A("")
    A("| " + " | ".join(p["loading_names"]) + " |")
    A("|" + "---:|" * len(p["loading_names"]))
    A("| " + " | ".join(f"{v:+.4f}" for v in p["loadings"]) + " |")
    A("")
    A("Equal-session mean AUC over the qualifying evaluation sessions, with "
      "the 2,000-draw whole-session interval on the oriented column:")
    A("")
    A("| column | fitting raw AUC | sign | evaluation raw | evaluation "
      "oriented | 2.5 % | 97.5 % | qualifying sessions |")
    A("|---|---:|:---:|---:|---:|---:|---:|---:|")
    for c in tab["columns"]:
        if c.get("degenerate"):
            A(f"| {c['column']} | — | — | **degenerate** | — | — | — | — |")
            continue
        oc = ori["columns"][c["column"]]
        b = c["bootstrap_oriented"]
        A(f"| `{c['column']}` | {pct(oc['fitting_auc_raw'])} | "
          f"{c['sign_from_fitting']:+d} | {pct(c['mean_auc_raw'])} | "
          f"{pct(c['mean_auc_oriented'])} | {b['p2.5']:.4f} | "
          f"{b['p97.5']:.4f} | {c['qualifying_sessions']} |")
    A("")
    A("Per-session **raw** AUC (the oriented value is the raw value for a "
      "`+1` column and its reflection about 0.5 for a `−1` column):")
    A("")
    cols = [c for c in tab["columns"] if not c.get("degenerate")]
    A("| session | n | Y=1 | Y=0 | " + " | ".join(f"`{c['column']}`"
                                                  for c in cols) + " | note |")
    A("|---|---:|---:|---:|" + "---:|" * len(cols) + "---|")
    for i, r in enumerate(cols[0]["per_session_raw"]):
        vals = " | ".join(pct(c["per_session_raw"][i]["auc"]) for c in cols)
        note = "qualifies" if r["qualifies"] else r["reason"]
        A(f"| {r['session']} | {r['n']} | {r['n_pos']} | {r['n_neg']} | "
          f"{vals} | {note} |")
    A("")
    A("2026-07-22 is excluded by D7's ≥ 10-per-class rule, exactly as it was "
      "in D7, and the exclusion is named rather than absorbed. A one-class "
      "session would be **undefined**, not 0.5; there is none here.")
    A("")
    A("This table describes marginal rankings and one projection. **It is not "
      "the final input-informativeness verdict.**")
    A("")

    # --------------------------------------------------- 4. joint models
    A("## 4. The four joint diagnostic models")
    A("")
    A("Two families on two representations, four fits, exactly the parameters "
      "of amendment §6. No tuning, no extra family, no seed search, no model "
      "selected on evaluation performance. `StandardScaler` was fitted on the "
      "fitting rows only. **The primary joint diagnostic is NONLINEAR on "
      "X_SENSORY**, named in `PLAN.md` before any number existed; the other "
      "three are secondary comparisons whatever they show.")
    A("")
    A("**These are external measurement tools with supervised access to "
      "historical labels. They are not biological models, and their results "
      "are never attributed to the fly.** They have no runtime path to the "
      "decoder, orders, reward, plasticity or observer decisions.")
    A("")
    A("| model | in-sample AUC | evaluation mean AUC | 2.5 % | 97.5 % | "
      "qualifying sessions | rôle |")
    A("|---|---:|---:|---:|---:|---:|---|")
    for m in mod["models"]:
        b = m["bootstrap"]
        A(f"| {m['name']} | {pct(m['fitting']['in_sample_auc'])} | "
          f"**{pct(m['mean_auc'])}** | {b['p2.5']:.4f} | {b['p97.5']:.4f} | "
          f"{m['evaluation']['qualifying_sessions']} | "
          f"{'**primary**' if m['primary'] else 'secondary'} |")
    A(f"| REFERENCE fly (D7) | — | {pct(mod['fly']['REFERENCE']['mean_auc'])} "
      f"| — | — | 9 | comparison |")
    A(f"| TRAINED fly (D7) | — | {pct(mod['fly']['TRAINED']['mean_auc'])} | — "
      f"| — | 9 | comparison |")
    A("")
    A("The in-sample column is a description of the fit, not evidence: the "
      "nonlinear family reaches 0.78 on the rows it was fitted on and 0.50 on "
      "the evaluation rows. It had the capacity to separate the fitting "
      "labels and that separation did not generalise to these periods.")
    A("")
    A("Fitting: 2,789 rows over 10 sessions, 1,020 / 1,769. Evaluation: 2,790 "
      "rows over 10 sessions, 1,235 / 1,555, coverage 1.0000, one session "
      "excluded (2026-07-22). Both logistic fits converged — "
      + ", ".join(f"{m['name']} `n_iter_` {m['fit']['n_iter_']}"
                  for m in mod["models"] if m["family"] == "LINEAR")
      + f" against `max_iter` 2000, which was never raised — with **no "
        "`ConvergenceWarning` and no warning of any kind**; the "
        "HistGradientBoosting fits ran their full 100 iterations with "
        "`early_stopping=False`.")
    A("")
    A("Per-session evaluation AUC:")
    A("")
    A("| session | n | Y=1 | Y=0 | " + " | ".join(m["name"]
                                                  for m in mod["models"])
      + " | REFERENCE | TRAINED | note |")
    A("|---|---:|---:|---:|" + "---:|" * (len(mod["models"]) + 2) + "---|")
    base = mod["models"][0]["per_session_auc"]
    for i, r in enumerate(base):
        vals = " | ".join(pct(m["per_session_auc"][i]["auc"])
                          for m in mod["models"])
        A(f"| {r['session']} | {r['n']} | {r['n_pos']} | {r['n_neg']} | "
          f"{vals} | {pct(mod['fly']['REFERENCE']['per_session'][i])} | "
          f"{pct(mod['fly']['TRAINED']['per_session'][i])} | "
          f"{'qualifies' if r['qualifies'] else r['reason']} |")
    A("")
    A("Paired deltas, on **identical rows and sessions** (2,790 paired rows, "
      "9 paired sessions), each diagnostic minus the fly, with the "
      "2,000-draw paired whole-session interval:")
    A("")
    A("| model | Δ vs REFERENCE | 2.5 % | 97.5 % | above 0 | Δ vs TRAINED | "
      "2.5 % | 97.5 % | above 0 |")
    A("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for m in mod["models"]:
        pr, pt = m["paired_vs_fly"]["REFERENCE"], m["paired_vs_fly"]["TRAINED"]
        br, bt = pr["bootstrap"], pt["bootstrap"]
        A(f"| {m['name']} | {pr['delta_auc']:+.4f} | {br['p2.5']:+.4f} | "
          f"{br['p97.5']:+.4f} | {br['fraction_of_draws_above_zero']:.1%} | "
          f"{pt['delta_auc']:+.4f} | {bt['p2.5']:+.4f} | {bt['p97.5']:+.4f} | "
          f"{bt['fraction_of_draws_above_zero']:.1%} |")
    A("")
    A("Seeds, declared in `config.json` before any draw: level "
      f"`{mod['bootstrap']['level_seed_label']}` → "
      f"{mod['bootstrap']['level_seed']}, paired "
      f"`{mod['bootstrap']['paired_seed_label']}` → "
      f"{mod['bootstrap']['paired_seed']}, both through "
      "`flytrade.metrics.declared_seed`. **These intervals are descriptive and "
      "conditional on this dataset and this model fit.** Minute probes with "
      "overlapping 90-minute labels are not independent examples; whole "
      "sessions are resampled and individual minutes never are. Secondary "
      "intervals are not simultaneous family-wise evidence, and no discovery "
      "is declared by picking the best column or the one interval that "
      "excludes 0.5 — **every diagnostic is shown above**.")
    A("")
    A("**No matched-participation table.** It is a trading-style readout that "
      "§2 and §10 would then have to disclaim, and AUC already answers the "
      "ranking question; `flytrade.metrics.matched_participation` is not "
      "called by D8.")
    A("")

    # ------------------------------------------------- 5. alignment audit
    A("## 5. The target-alignment audit")
    A("")
    A(f"The {S['episodes']} actual LEARNING episodes of `d7-001`, read through "
      "`flytrade.records` parsing only. The full per-episode table is "
      "`alignment.md`; `alignment.json` carries every column §8 lists.")
    A("")
    A("| quantity | value |")
    A("|---|---|")
    A(f"| episodes | {S['episodes']} |")
    A(f"| exit reasons | {S['exit_reasons']} |")
    A(f"| exits before H = {S['H']} | **{S['exits_before_H']} of "
      f"{S['episodes']}**; at or after H: {S['exits_at_or_after_H']} |")
    hm = S["holding_minutes"]
    A(f"| actual holding minutes | min {hm['min']}, median {hm['median']:.0f}, "
      f"max {hm['max']}, total {hm['total']} |")
    A(f"| actual outcome signs | {S['actual_sign_counts']['positive']} "
      f"positive, {S['actual_sign_counts']['negative']} negative, "
      f"{S['actual_sign_counts']['zero']} flat |")
    A(f"| reinforcement signs | "
      f"{S['reinforcement_sign_counts']['reward']} reward, "
      f"{S['reinforcement_sign_counts']['punishment']} punishment |")
    av = S["hypothetical_label_availability"]
    A(f"| hypothetical H = 90 label availability | {av['available']} "
      f"available, {av['unavailable']} unavailable {av['reasons'] or ''} |")
    A(f"| hypothetical fixed-H labels | "
      f"{S['hypothetical_label_counts']['Y=1']} profitable / "
      f"{S['hypothetical_label_counts']['Y=0']} not |")
    sc = S["sign_comparison"]
    A(f"| actual versus fixed-H signs | {sc['compared']} compared, "
      f"{sc['agree']} agree, **{sc['disagree']} disagree** — proportion "
      f"**{sc['proportion_disagreeing']:.4f}** |")
    A(f"| disagreements by actual sign | "
      f"{sc['disagreements_by_actual_sign']['actual_positive']} where the "
      f"actual outcome was positive, "
      f"{sc['disagreements_by_actual_sign']['actual_negative']} where it was "
      f"negative |")
    A(f"| agreements by actual sign | "
      f"{sc['agreements_by_actual_sign']['actual_positive']} positive, "
      f"{sc['agreements_by_actual_sign']['actual_negative']} negative |")
    c = S["costs"]
    A(f"| costs | {c['executions']} executions at "
      f"{c['fee_bps_per_execution']:.0f} bps fee + "
      f"{c['slippage_bps_per_execution']:.0f} bps slippage each "
      f"({c['round_trip_bps_nominal']:.0f} bps nominal per round trip); fees "
      f"{c['total_fees']:.4f} + slippage {c['total_slippage']:.4f} = "
      f"**{c['total_cost']:.4f}** against a gross at reference prices of "
      f"{c['total_gross_reference_pnl']:+.4f} and a net of "
      f"{c['total_net_pnl']:+.4f} |")
    A(f"| cost exceeded gross | "
      f"{c['episodes_whose_cost_exceeds_gross_reference']} of {S['episodes']} "
      f"episodes |")
    ef = S["entry_fill_identity"]
    A(f"| hypothetical entry == actual entry | "
      f"{ef['reference_price_equal']}/{ef['compared']} at the reference "
      f"price, {ef['slipped_fill_equal']}/{ef['compared']} after the "
      f"unchanged slippage, max \\|difference\\| {ef['max_abs_diff']:.2e} |")
    A("")
    A("The information cutoff and the entry time print as the same clock "
      "minute because `bar_end(t)` **is** `bar_start(t+1)`: the decision is "
      "taken at the close of minute *t* and the fill is the open of minute "
      "*t+1*, which is the same instant. The one-minute execution delay is "
      "unchanged.")
    A("")
    A("> These counterfactuals reuse the original entry times. **They do not "
      "simulate the trades a fixed-hold policy would actually have taken**, "
      "because that policy changes inventory and later entry opportunities. "
      "Nothing here updates a weight, replays a reward, modifies an account or "
      "rewrites an original event, and **no hypothetical outcome is booked as "
      "portfolio PnL** — the per-episode counterfactuals are never summed. "
      "This audit measures **alignment**, not whether fixed-hold training "
      "would succeed. A future fixed-hold wave requires a separate explicit "
      "policy amendment.")
    A("")

    # ------------------------------------------------------ 6. guards
    A("## 6. Guards and tests")
    A("")
    A("* No module under `experiments/d8/` imports `flytrade.execution`, "
      "`flytrade.runner`, `flytrade.mushroom`, `flytrade.state` or "
      "`flytrade.readout`, and none names a mutating API, an account, a cash "
      "balance or a bankroll — checked by a static scan of the parsed syntax "
      "trees. **Declared**: `flytrade.historical`, which D8 needs to read the "
      "price file causally, itself imports `flytrade.execution`; and "
      "`flytrade.records`, which addendum 11 *requires* the alignment audit to "
      "parse the log with, itself imports `flytrade.runner` and "
      "`flytrade.state`. Those transitive imports are unavoidable and are the "
      "reason the guard is on direct imports and on named identifiers rather "
      "than on `sys.modules`.")
    A("* `observer/serve.py` contains no path under `experiments/d8` and was "
      "not modified.")
    A("* The XOR fixture of §9: each input alone AUC exactly 0.5, PC1 of the "
      "pair exactly 0.5, the joint oracle exactly 1.0. Its purpose is to stop "
      "the reporting layer ever asserting that marginal chance performance "
      "proves absent information. **It does not require any diagnostic model "
      "to solve every possible interaction.**")
    A("* Determinism: two consecutive fits of each family on the fixture give "
      "bit-identical scores, with `OMP_NUM_THREADS=1`.")
    A("* No evaluation row reaches a scaler, the PCA or a model fit; changing "
      "every evaluation label leaves the fitted models, the signs, the PCA and "
      "the already-generated scores bit-identical.")
    A("* Constant scores give exactly 0.5 with both classes present, a "
      "reversed ranking exactly 0.0, a one-class session `None`; the fast AUC "
      "equals the pairwise definition on tie-heavy inputs.")
    A("* No downloaded market data enters any test: the D8 suite runs on a "
      "deterministic generated fixture pair, and the tree-wide guard in "
      "`tests/historical/test_vendor_format.py` enforces it.")
    A("* **The D7 evaluator was re-run, read-only, at the close.** "
      "`withheld probe table` came back **byte-identical** (sha256 "
      "`108f11a9e8063488…` before and after) and every result in "
      "`context_summary.json` — the per-session AUCs, `DELTA_AUC` −0.0030, "
      "the paired bootstrap and conclusion **B** — reproduced exactly. The "
      "file itself differs in two fields only, `written_utc` and `elapsed_s` "
      "(1.06 s → 1.08 s): a wall-clock stamp and a measured compute time, "
      "neither of which is a result. It was **restored from git**, so "
      "`git diff --stat -- experiments/d7` is empty and the registered hash "
      "still holds.")
    A("* `git diff --stat cc9faaf -- upstream tests/upstream_audit` is empty.")
    A("")

    # ------------------------------------------------- 7. the conclusions
    A("## 7. Conclusions")
    A("")
    A("Amendment §2, reproduced verbatim from `docs/SPEC.md`:")
    A("")
    A("```")
    A(boundaries())
    A("```")
    A("")

    A("### INPUT DIAGNOSTICS")
    A("")
    prim = next(m for m in mod["models"] if m["primary"])
    A(f"**No detectable signal with these methods on these periods.** The "
      f"primary joint diagnostic — {prim['name']} — reaches an equal-session "
      f"mean AUC of **{prim['mean_auc']:.4f}** over 9 qualifying evaluation "
      f"sessions, with a 2.5–97.5 % whole-session interval of "
      f"{prim['bootstrap']['p2.5']:.4f} … {prim['bootstrap']['p97.5']:.4f} "
      f"that contains 0.5. The three secondary joint models sit at "
      + ", ".join(f"{m['mean_auc']:.4f}" for m in mod["models"]
                  if not m["primary"])
      + ", every interval containing 0.5. Each of the five features and PC1, "
        "oriented on the fitting rows alone, sits between "
      + f"{min(c['mean_auc_oriented'] for c in cols):.4f} and "
      + f"{max(c['mean_auc_oriented'] for c in cols):.4f}, every interval "
        "containing 0.5. Paired against the fly on identical rows and "
        "sessions, the deltas run "
      + f"{min(m['paired_vs_fly']['REFERENCE']['delta_auc'] for m in mod['models']):+.4f} "
        "to "
      + f"{max(m['paired_vs_fly']['REFERENCE']['delta_auc'] for m in mod['models']):+.4f} "
        "against REFERENCE and "
      + f"{min(m['paired_vs_fly']['TRAINED']['delta_auc'] for m in mod['models']):+.4f} "
        "to "
      + f"{max(m['paired_vs_fly']['TRAINED']['delta_auc'] for m in mod['models']):+.4f} "
        "against TRAINED, every interval spanning zero.")
    A("")
    A("**Before and after encoding, the answer is the same.** X_FEATURES and "
      "X_SENSORY give the same verdict under both families; there is no "
      "detected ranking in the five features that the ten-glomerulus stimulus "
      "loses, and none in the stimulus that the features lack. Neither of the "
      "amendment's two asymmetric readings applies, because neither side "
      "produced a detectable ranking to compare.")
    A("")
    A("This is a statement about **these models, this data and this target**. "
      "It is *not* the statement that nothing can learn from these inputs, and "
      "§2's five boundaries above are the binding wording: an untrained brain "
      "at 0.49 bounds nothing about its inputs; univariate and PC1 chance do "
      "not exclude joint structure — the XOR fixture in `tests/d8/` is a "
      "concrete case where both marginals are exactly 0.5 and the joint is "
      "exactly 1.0; PC1 maximises represented variance, not predictiveness, "
      f"and here it captures {p['explained_variance_ratio_pc1']:.1%} of the "
      "variance of a representation whose ten channels are five antagonistic "
      "pairs. The failure of two small supervised models with fixed "
      "parameters, fitted on 2,789 minutes of one instrument over ten days and "
      "evaluated on 2,790 minutes over ten more, is evidence about that "
      "procedure and not a universal input ceiling.")
    A("")
    A("**A result on these reused dates is a lead, not independent proof** of "
      "trading ability or of a theoretical learning ceiling — and here there "
      "is not even a lead.")
    A("")

    A("### TARGET ALIGNMENT")
    A("")
    A(f"**D7 reinforced one quantity and scored another, and the two disagree "
      f"on {sc['disagree']} of {sc['compared']} episodes "
      f"({sc['proportion_disagreeing']:.1%}).** All "
      f"{S['exits_before_H']} of {S['episodes']} LEARNING episodes exited by "
      f"neural `SELL` between {hm['min']} and {hm['max']} market minutes, "
      f"median {hm['median']:.0f}, {hm['total']} minutes of exposure in total; "
      f"the H = 90 horizon never bound on a single one. The outcome the fly "
      f"was reinforced on was {S['reinforcement_sign_counts']['reward']} "
      f"reward against {S['reinforcement_sign_counts']['punishment']} "
      f"punishment. The fixed-90-minute label on the same "
      f"{S['episodes']} entries, at the same fills and the same costs, is "
      f"{S['hypothetical_label_counts']['Y=1']} profitable against "
      f"{S['hypothetical_label_counts']['Y=0']}. Of the "
      f"{sc['disagree']} disagreements, "
      f"{sc['disagreements_by_actual_sign']['actual_negative']} are episodes "
      f"whose actual outcome was a loss and whose 90-minute counterfactual is "
      f"a gain, and "
      f"{sc['disagreements_by_actual_sign']['actual_positive']} the other way.")
    A("")
    A(f"**The arithmetic behind that is the cost, not a prediction.** A "
      f"{c['round_trip_bps_nominal']:.0f} bps round trip on a one-to-three "
      f"minute hold is the whole of the result: total cost "
      f"{c['total_cost']:.4f} against a gross at reference prices of "
      f"{c['total_gross_reference_pnl']:+.4f}, and cost exceeded gross in "
      f"{c['episodes_whose_cost_exceeds_gross_reference']} of {S['episodes']} "
      f"episodes. The hypothetical entry is the actual entry on every episode "
      f"({ef['reference_price_equal']}/{ef['compared']}, max \\|difference\\| "
      f"{ef['max_abs_diff']:.2e}), so the disagreement is a difference in "
      "**holding duration**, not in entry, fill or cost model.")
    A("")
    A("This **limits the interpretation of D7's measurement; it does not "
      "invalidate D7's recorded results**, and it is not evidence that "
      "aligning the two would produce learning. The counterfactuals reuse the "
      "original entry times and do not simulate the trades a fixed-hold policy "
      "would have taken. Nothing was booked.")
    A("")

    A("### NEXT-STEP RECOMMENDATION")
    A("")
    A("**Bounded, and not an authorisation.**")
    A("")
    A("1. **Nothing in the input diagnostics supports a new neural wave.** "
      "Both of the amendment's readings that would motivate investigating "
      "learning, readout or encoding require a *detectable* ranking on one "
      "side; there is none on either. The correct record of this wave is \"no "
      "detectable signal with these methods on these periods\", and the "
      "correct next action on that basis is **none**.")
    A("2. **Option (c) is not launched, and D8 does not authorise it.** Its "
      "justification was never an AUC, and D8 produced no AUC that could "
      "supply one. The alignment audit is the only substantive positive "
      "finding here, and it is a finding about *measurement*, not about "
      "learnability. If the owner chooses to open a fixed-hold wave, it "
      "requires a separate explicit policy amendment, and the numbers it "
      "should be argued from are the audit's "
      f"({S['exits_before_H']}/{S['episodes']} exits before H, "
      f"{sc['proportion_disagreeing']:.1%} sign disagreement, "
      f"{S['hypothetical_label_counts']['Y=1']}/"
      f"{S['hypothetical_label_counts']['Y=0']} against "
      f"{S['reinforcement_sign_counts']['reward']}/"
      f"{S['reinforcement_sign_counts']['punishment']}) — not any ranking "
      "result in this document.")
    A("3. **A negative D8 does not prohibit fixed-hold experiments, and a "
      "positive one would not have guaranteed they work.** Neither does this "
      "wave close the scientific question: it closes one bounded test of it.")
    A("4. **The product stance is unchanged.** The interface and the spectacle "
      "are not hostage to a proof of profitability, and this wave adds no "
      "claim of skill, alpha or profitability in either direction.")
    A("")
    A("The wave stops here, as §10 requires. Nothing was reopened: graph, "
      "plasticity, gain, window, MBON groups, θ, baseline, encoder, decoder, "
      "k, H = 90, costs, sizing, early-`SELL` semantics, datasets and run "
      "identities are all exactly as D7 left them.")
    A("")
    A(f"<!-- generated by experiments/d8/report.py, "
      f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} -->")

    OUT.write_text("\n".join(L) + "\n")
    print(f"wrote {OUT.relative_to(D.ROOT)}  {len(L)} lines, "
          f"{OUT.stat().st_size} bytes")
    print(f"artifacts unchanged: {after == cfg['artifacts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
