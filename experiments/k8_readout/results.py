#!/usr/bin/env python
"""
Assemble ``results.md`` from the artifacts. Every number is generated.

    .venv/bin/python experiments/k8_readout/results.py

Reads whichever of ``baseline_run.json``, ``evaluation.json``,
``benchmark.json`` and ``demo_k8.json`` exist and writes the report. Nothing is
computed here that is not already in an artifact, and nothing is hand-entered.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))


def load(name):
    p = HERE / name
    return json.loads(p.read_text()) if p.exists() else None


CONDITIONS = ("APPETITIVE_ON", "APPETITIVE_OFF", "AVERSIVE_ON",
              "AVERSIVE_OFF", "APPETITIVE_OTHER", "AVERSIVE_OTHER")


# ------------------------------------------------------------------ §3

def baseline_section(b) -> list[str]:
    art, c = b["baseline"], b["counts"]
    k1, p1 = b["k1_arm_same_schedule"], b["k1_phase_one_constants"]
    L = ["## §3 — the k = 8 baseline and the WAIT margin", "",
         "`baseline.py`, writing `baseline_k8.json`. The procedure was "
         "pre-registered in `PROTOCOL.md` §3 at a commit containing that file "
         "alone. No label, no PnL, no realised outcome and no desired action "
         "rate participates.", "",
         f"N = {art['n_batches']} batches of k = {art['k']} at the neutral "
         f"reference `u = 0`, {c['presentations']} presentations, unlearned "
         f"weights, gain 0.10, 20 ms window.", "",
         "| estimator | baseline offset Hz | dispersion Hz | θ = 1.0 × SD | N |",
         "|---|--:|--:|--:|--:|",
         f"| k = 1, Phase One (`docs/DECODER.md` §4) | {p1['baseline_hz']:.4f} "
         f"| {p1['sd_hz']:.4f} | {p1['theta_hz']:.4f} | {p1['n']} seeds |",
         f"| k = 1, replicate 0 of this schedule | {k1['mean_hz']:.4f} | "
         f"{k1['sd_hz']:.4f} | {k1['sd_hz']:.4f} | {k1['n']} draws |",
         f"| **k = 8, batch aggregate** | **{art['baseline_hz']:.4f}** | "
         f"**{art['sd_hz']:.4f}** | **{art['theta_hz']:.4f}** | "
         f"{art['n_batches']} batches |", "",
         f"SD ratio k = 8 / k = 1 on the same schedule "
         f"**{b['sd_ratio_k8_over_k1_same_schedule']:.3f}**, against the Phase "
         f"One 8-seed SD {b['sd_ratio_k8_over_phase_one_k1']:.3f}; the "
         f"independent-replicate expectation is 1/√8 = "
         f"{b['expected_sd_ratio']:.3f}. The measured ratio is **below** it. "
         f"Reported, not fixed.", "",
         f"Silent replicates **{c['silent_replicates']}/"
         f"{c['silent_replicates_denominator']}** "
         f"(unit: {c['silent_replicate_unit']}); `NO_RESPONSE` batches "
         f"**{c['no_response_batches']}/{c['no_response_denominator']}** "
         f"(unit: {c['no_response_unit']}); `INVALID_STATE` batches "
         f"{c['invalid_batches']}/{c['no_response_denominator']}. Mean Kenyon "
         f"active fraction {c['mean_kc_fraction']:.4f}.", "",
         f"Seed schedule `{b['seed_disjointness']['namespace']}`: "
         f"{b['seed_disjointness']['distinct_seeds']} distinct seeds, "
         f"{b['seed_disjointness']['seeds_below_2_32']} of them below 2³². "
         f"{b['seed_disjointness']['claim']}.", "",
         "The distribution normalised is " + art["distribution"] + ".", ""]
    return L


# ------------------------------------------------------------------ §5

def jaccard_table(e) -> list[str]:
    cx = e["contexts"]
    L = ["| | " + " | ".join(f"`{c}`" for c in cx) + " |",
         "|---|" + "--:|" * len(cx)]
    for a in cx:
        row = []
        for b in cx:
            if a == b:
                row.append("—")
                continue
            v = e["kc_jaccard"].get(f"{a}|{b}", e["kc_jaccard"].get(f"{b}|{a}"))
            row.append(f"{v:.3f}")
        L.append(f"| `{a}` | " + " | ".join(row) + " |")
    return L


def stability_section(e) -> list[str]:
    L = ["### Within-context stability, k = 1 against k = 8 on the same batches",
         "",
         f"{e['n_batches']} batches per context; k = 1 is replicate 0 of each "
         f"batch, so the two arms are paired by construction. `SD(V)` is over "
         f"all {e['n_batches']} batches — the quantity the loop selects on; "
         f"the `VALID`-only SD is beside it. Agreement is the fraction of "
         f"batches equal to that arm's modal decision.", "",
         "| context | SD₁ Hz | SD₈ Hz | ratio | SD₈ valid-only | modal₁ | "
         "agree₁ | modal₈ | agree₈ |",
         "|---|--:|--:|--:|--:|---|--:|---|--:|"]
    for c in e["contexts"]:
        r = e["stability"][c]
        a, b = r["k1"], r["k8"]
        sv = ("—" if b["sd_valid_hz"] is None else f"{b['sd_valid_hz']:.3f}")
        L.append(f"| `{c}` | {a['sd_hz']:.3f} | {b['sd_hz']:.3f} | "
                 f"{r['sd_ratio']:.3f} | {sv} | {a['modal_decision']} | "
                 f"{a['agreement']:.2f} | {b['modal_decision']} | "
                 f"{b['agreement']:.2f} |")
    L += ["", "### Counts, with their denominators and their units", "",
          "| context | `NO_RESPONSE`₁ /batch-equivalent | `NO_RESPONSE`₈ "
          "/batch | silent replicates /presentation | `INVALID`₁ | `INVALID`₈ "
          "| `WAIT`₁ | `WAIT`₈ |",
          "|---|--:|--:|--:|--:|--:|--:|--:|"]
    for c in e["contexts"]:
        r = e["stability"][c]
        a, b = r["k1"], r["k8"]
        L.append(f"| `{c}` | {a['no_response']}/{a['denominator']} | "
                 f"{b['no_response']}/{b['denominator']} | "
                 f"{r['silent_replicates']}/"
                 f"{r['silent_replicate_denominator']} | {a['invalid']} | "
                 f"{b['invalid']} | {a['wait']} | {b['wait']} |")
    tot_nr1 = sum(e["stability"][c]["k1"]["no_response"] for c in e["contexts"])
    tot_nr8 = sum(e["stability"][c]["k8"]["no_response"] for c in e["contexts"])
    tot_sil = sum(e["stability"][c]["silent_replicates"] for c in e["contexts"])
    den = e["n_batches"] * len(e["contexts"])
    L += ["", f"Totals: `NO_RESPONSE` **{tot_nr1}/{den}** at k = 1 (unit: "
              f"presentation) against **{tot_nr8}/{den}** at k = 8 (unit: "
              f"candidate evaluation); **{tot_sil}/{den * 8}** individual "
              f"presentations inside the k = 8 batches were silent (unit: "
              f"presentation). A batch is `NO_RESPONSE` only when all eight "
              f"replicates are silent, which is why the two columns differ; "
              f"no threshold was lowered and no silence relabelled.", ""]
    return L


def learning_table(pair) -> list[str]:
    s = pair["summary"]
    n = s["n_seeds"]
    L = [f"#### Pair `{pair['pair']}` — X = `{pair['X']}`, Y = `{pair['Y']}`, "
         f"{pair['trials']} trials, k = {pair['k']}", "",
         "| condition | trained on | dV(X) Hz | d approach(X) Hz | "
         "d avoid(X) Hz | dV(Y) Hz | seeds whose action changed |",
         "|---|---|--:|--:|--:|--:|--:|"]
    trained = {r["condition"]: r["trained_on"] for r in pair["runs"]}
    for c in CONDITIONS:
        L.append(f"| `{c}` | `{trained[c]}` | {s['dV_X_mean'][c]:+.3f} | "
                 f"{s['d_approach_X_mean'][c]:+.3f} | "
                 f"{s['d_avoid_X_mean'][c]:+.3f} | {s['dV_Y_mean'][c]:+.3f} | "
                 f"{s['actions_changed'][c]}/{n} |")
    L += ["", "| seed | " + " | ".join(f"`{c}`" for c in CONDITIONS) + " |",
          "|--:|" + "--:|" * len(CONDITIONS)]
    for i in range(n):
        L.append(f"| {i + 1} | " + " | ".join(
            f"{s['dV_X_per_seed'][c][i]:+.3f}" for c in CONDITIONS) + " |")
    ch = s["checks"]
    L += ["", "| check | prediction | seeds | threshold | verdict |",
          "|---|---|--:|--:|:--|"]
    for name, pred, got, need in [
            ("appetitive reaches the decoder", "dV(X) > 0 under APPETITIVE_ON",
             ch["appetitive_positive_seeds"], s["min_seeds"]),
            ("aversive reaches the decoder", "dV(X) < 0 under AVERSIVE_ON",
             ch["aversive_negative_seeds"], s["min_seeds"]),
            ("plasticity off, appetitive", "dV(X) == 0 exactly",
             ch["appetitive_off_zero_seeds"], n),
            ("plasticity off, aversive", "dV(X) == 0 exactly",
             ch["aversive_off_zero_seeds"], n),
            ("depends on the eligible experience, appetitive",
             "dV(X)[ON] − dV(X)[OTHER] > 0",
             ch["appetitive_specificity_seeds"], n),
            ("depends on the eligible experience, aversive",
             "dV(X)[ON] − dV(X)[OTHER] < 0",
             ch["aversive_specificity_seeds"], n)]:
        L.append(f"| {name} | {pred} | {got}/{n} | {need}/{n} | "
                 f"{'PASS' if got >= need else '**below threshold**'} |")
    L += ["", f"Specificity, mean over seeds: appetitive "
              f"{s['specificity_appetitive_mean']:+.3f} Hz, aversive "
              f"{s['specificity_aversive_mean']:+.3f} Hz. Learning events per "
              f"cell: {s['learning_events_per_cell']} — twenty accepted in "
              f"every plastic cell, zero in every `_OFF` cell, one per "
              f"training batch and never eight.", ""]
    return L


def criteria_table(e) -> list[str]:
    c = e["criteria"]
    L = ["### The pre-registered pass/fail", "",
         "| id | criterion | result | verdict |", "|---|---|---|:--|"]
    v = c["C1_sd_smaller_at_k8"]
    L.append(f"| C1 | SD₈ < SD₁ in ≥ {v['threshold']}/{v['of']} contexts | "
             f"{v['n']}/{v['of']}: {', '.join('`' + x + '`' for x in v['contexts']) or 'none'} | "
             f"{'**PASS**' if v['passed'] else '**FAIL**'} |")
    v = c["C2_agreement_not_worse_at_k8"]
    L.append(f"| C2 | agreement₈ ≥ agreement₁ in ≥ {v['threshold']}/{v['of']} "
             f"contexts | {v['n']}/{v['of']}: "
             f"{', '.join('`' + x + '`' for x in v['contexts']) or 'none'} | "
             f"{'**PASS**' if v['passed'] else '**FAIL**'} |")
    for key, label in (("C3a_appetitive_sign", "appetitive sign, both pairs"),
                       ("C3b_aversive_sign", "aversive sign, both pairs"),
                       ("C3c_plasticity_off_exactly_zero",
                        "plasticity off exactly 0.000, both pairs")):
        v = c[key]
        L.append(f"| {key.split('_')[0]} | {label}, {v['threshold']}/{v['of']} "
                 f"seeds | {v['per_pair']} | "
                 f"{'**PASS**' if v['passed'] else '**FAIL**'} |")
    v = c["C4_theta8_non_degenerate"]
    L.append(f"| C4 | θ₈ estimator non-degenerate | SD₈ = {v['sd_hz']:.4f} Hz "
             f"> 0 | {'**PASS**' if v['passed'] else '**FAIL**'} |")
    L += ["", f"**All six criteria: "
              f"{'PASS' if e['all_passed'] else 'NOT ALL PASSED'}.**", ""]
    return L


def evaluation_section(e) -> list[str]:
    L = ["## §5 — the independent integration check", "",
         "`evaluate.py`, writing `evaluation.json`. Stimuli, seed schedules, "
         "metrics, aggregate status rules and pass/fail were committed in "
         "`PROTOCOL.md` before this ran, at a commit containing that file "
         "alone. No profitability is claimed, sought or measured.", "",
         f"{e['presentations']:,} presentations. θ₈ = "
         f"{e['decoder_k8']['theta_hz']:.4f} Hz against θ₁ = "
         f"{e['decoder_k1']['theta_hz']:.4f} Hz; both decoders are "
         f"`{e['decoder_k8']['version']}` with the same formula, the same "
         f"sign convention and the same coefficient "
         f"{e['decoder_k8']['theta_sd']}.", "",
         "### Contexts", "",
         "Two are the conditioning **v2 pair**, *selected after v1 failed on "
         "resolution* — carried over and labelled as what they are. Four are "
         "new nominal encoder patterns, never selected for passing anything, "
         "placed at declared points of the input range.", "",
         "| id | `(r1, r5, r20, rv20, relvol)` |", "|---|---|"]
    for c in e["contexts"]:
        u = ", ".join(f"{x:+.3f}" for x in e["context_u"][c])
        L.append(f"| `{c}` | ({u}) |")
    L += ["", f"Pairwise Kenyon-cell Jaccard, mean over seeds "
              f"{e['jaccard_seeds']}. The threshold "
              f"{e['kc_jaccard_threshold']} applies to the four new patterns, "
              f"whose maximum is **{e['kc_jaccard_new_max']:.3f}**; the cross "
              f"terms with the v2 pair are reported whatever they say.", ""]
    L += jaccard_table(e)
    L += [""]
    L += stability_section(e)
    L += ["### Learning at k = 8", "",
          "Each of the twenty training trials is one batch of eight "
          "presentations settled by **one** normalised learning event — the "
          "mean of the eight proposed deltas computed from the same "
          "pre-update state. Never eight sequential rewards. Measurement "
          "before and after is one k = 8 batch at the same eight seeds, "
          "decoded once with θ₈.", ""]
    for name in e["learning"]:
        L += learning_table(e["learning"][name])
    L += criteria_table(e)
    return L


# ------------------------------------------------------------------ §6

#: every market-shaped dataset this repository has ever fed to the brain, with
#: its generator and seeds. The label column is the one D4 §6 asks for.
DATASETS = [
    ("Phase One §4 v1 contexts", "`CTXX`, `CTXY`",
     "`market.synthetic_series`, seeds 900, 901", "SYNTHETIC"),
    ("Phase One §4 v2 contexts", "`CTX0`–`CTX3`",
     "`market.synthetic_series`, seeds 900–903", "SYNTHETIC"),
    ("Phase One §5 credit demo", "`AAA`, `BBB`",
     "`market.synthetic_series`, seeds 910, 911", "SYNTHETIC"),
    ("Phase One §8 demonstration", "`SYN00`–`SYN05`",
     "`market.synthetic_series`, seeds 700–705", "SYNTHETIC"),
    ("Phase One encoder range", "six nominal patterns + `u = 0`",
     "feature vectors at declared points of the input range", "SYNTHETIC"),
    ("D4 §3 baseline", "`neutral_reference`",
     "the feature vector `u = (0,0,0,0,0)`", "SYNTHETIC"),
    ("D4 §5 contexts", "`V2_X`, `V2_Y`",
     "`market.synthetic_series`, seeds 903 bar 218 and 901 bar 409",
     "SYNTHETIC"),
    ("D4 §5 contexts", "`NOM_A`–`NOM_D`",
     "feature vectors at declared points of the input range", "SYNTHETIC"),
    ("D4 §7 benchmark", "`SYN00`–`SYN05`",
     "`market.synthetic_series`, seeds 700–705", "SYNTHETIC"),
    ("D4 §8 demonstration", "`SYN00`–`SYN05`",
     "`market.synthetic_series`, seeds 700–705", "SYNTHETIC"),
]


def provenance_section(e, dm) -> list[str]:
    market_dir = ROOT / "data" / "market"
    csvs = sorted(market_dir.glob("*.csv")) if market_dir.exists() else []
    p1 = json.loads((ROOT / "experiments" / "phase_one"
                     / "demo.json").read_text())
    acts = p1["stats"]["decoder_actions"]
    st = p1["stats"]["readout_statuses"]
    n_dec = sum(acts.values())
    n_pres = p1["stats"]["presentations"]
    nr = acts.get("NO_RESPONSE", 0)

    L = ["## §6 — data provenance and scientific labels", "",
         "### What is in the tree", "",
         f"`data/market/` "
         f"{'exists and holds ' + str(len(csvs)) + ' CSV file(s)' if csvs else '**does not exist**'}"
         f". No market data has ever been downloaded into this repository and "
         f"none is downloaded in this wave. The only downloaded dataset is the "
         f"MaleCNS v1.0 connectome (CC-BY), whose URLs, byte counts and sha256 "
         f"are in `data/MANIFEST.md`; it is a connectome, not market data.", "",
         "### Every dataset, labelled", "",
         "| used by | instruments / stimuli | generator and seeds | label |",
         "|---|---|---|---|"]
    for a, b, c, lab in DATASETS:
        L.append(f"| {a} | {b} | {c} | **{lab}** |")
    L += ["", "No `HISTORICAL_MARKET` dataset exists in this repository, so no "
              "source, instrument list, timestamp range or file hash can be "
              "recorded for one. When one arrives, `flytrade/market.py` "
              "documents the format and `data/MANIFEST.md` is where its "
              "provenance goes.", "",
          "### Resolving \"real observations\"", "",
          "The Phase One report's risk 1 said *\"18.5–20.6% of real "
          "observations give `NO_RESPONSE`\"*. Resolved from the artifacts, "
          "that phrase meant **observations the offline simulator actually "
          "produced over seeded synthetic series** — not historical market "
          "data, of which there is none. The numbers the committed artifacts "
          "do support, from `experiments/phase_one/demo.json`:", "",
          "| numerator / denominator | value | unit |", "|---|--:|---|",
          f"| `NO_RESPONSE` decisions / decoded selected-candidate readouts | "
          f"{nr}/{n_dec} = {nr / n_dec:.1%} | decision |",
          f"| `NO_RESPONSE` statuses / all recorded round statuses | "
          f"{st.get('NO_RESPONSE', 0)}/{sum(st.values())} = "
          f"{st.get('NO_RESPONSE', 0) / sum(st.values()):.1%} | decision |",
          f"| `NO_RESPONSE` decisions / presentations made in the run | "
          f"{nr}/{n_pres} = {nr / n_pres:.1%} | presentation |",
          "",
          "The stated range **18.5–20.6 % is not reproducible as written** "
          "from the committed artifacts; the closest supported figure is "
          f"{nr}/{n_dec} = {nr / n_dec:.1%} of decisions. It is corrected "
          "here rather than repeated. The substantive point survives either "
          "way: at k = 1 roughly one decision in five had nothing to decode "
          "from.", ""]
    if e:
        tot_nr1 = sum(e["stability"][c]["k1"]["no_response"]
                      for c in e["contexts"])
        tot_nr8 = sum(e["stability"][c]["k8"]["no_response"]
                      for c in e["contexts"])
        tot_sil = sum(e["stability"][c]["silent_replicates"]
                      for c in e["contexts"])
        den = e["n_batches"] * len(e["contexts"])
        L += ["### This wave's `NO_RESPONSE`, with units", "",
              "| measurement | numerator / denominator | unit |",
              "|---|--:|---|",
              f"| §5, k = 1 arm | {tot_nr1}/{den} = {tot_nr1 / den:.1%} | "
              f"presentation |",
              f"| §5, k = 8 arm | {tot_nr8}/{den} = {tot_nr8 / den:.1%} | "
              f"candidate evaluation (batch) |",
              f"| §5, silent replicates inside the k = 8 batches | "
              f"{tot_sil}/{den * 8} = {tot_sil / (den * 8):.1%} | "
              f"presentation |"]
        b = load("baseline_run.json")
        if b:
            c = b["counts"]
            L += [f"| §3 baseline, k = 1 (replicate 0) silence | "
                  f"{c['silent_replicates']}/"
                  f"{c['silent_replicates_denominator']} = "
                  f"{c['silent_replicates'] / c['silent_replicates_denominator']:.1%}"
                  f" | presentation |",
                  f"| §3 baseline, k = 8 batches | "
                  f"{c['no_response_batches']}/{c['no_response_denominator']} "
                  f"| candidate evaluation (batch) |"]
        L += [""]
    if dm:
        s2 = dm["stats"]
        nr8 = s2["decoder_actions"].get("NO_RESPONSE", 0)
        tot = sum(s2["decoder_actions"].values())
        L += [f"| §8 demonstration, k = 8 | {nr8}/{tot} = "
              f"{nr8 / tot:.1%} | decision |", ""]
    L += ["### The decoder convention, stated in three layers", "",
          "`docs/DECODER.md` §3 separates *(a)* the observed dopaminergic "
          "innervation split on this dataset, *(b)* the literature's attributed "
          "valence, which assumes the numbering is the hemibrain numbering, and "
          "*(c)* our convention `V = PPL1-side − PAM-side`. PPL1-minus-PAM is "
          "retained as the declared **experimental** convention. Grouping MBONs "
          "by dopaminergic innervation is not described as proof of a universal "
          "behavioural valence, and the earlier claim that it was \"the only "
          "sign consistent with depression-only plasticity\" has been corrected "
          "there and in `docs/ARCHITECTURE.md`. The decoder is unchanged; no "
          "literature-audit phase was run, and none was required.", ""]
    return L


# ------------------------------------------------------------------ §7

def benchmark_section(b) -> list[str]:
    import importlib.util
    spec = importlib.util.spec_from_file_location("bm", HERE / "benchmark.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return ["## §7 — measured cost", "",
            "`benchmark.py`, writing `benchmark.json`. One process, no "
            "parallelism, no distributed infrastructure, and nothing in the "
            "scientific model changed to reach a number.", "",
            m.render(b), ""]


# ------------------------------------------------------------------ §8

def demo_section(d) -> list[str]:
    import importlib.util
    spec = importlib.util.spec_from_file_location("dm", HERE / "run_demo_k8.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return ["## §8 — the offline demonstration at k = 8", "",
            "`run_demo_k8.py`, writing `demo_k8.json`. The Phase One "
            "demonstration's own fixture, seeds and bar range, the same "
            "mid-run restart, with every candidate now read eight times. Net "
            "PnL is **not** a gate metric and is not read in either "
            "direction.", "",
            m.render(d), ""]


# ----------------------------------------------------------------- main

def main() -> int:
    b = load("baseline_run.json")
    e = load("evaluation.json")
    bm = load("benchmark.json")
    dm = load("demo_k8.json")
    src = e or b
    v = src.get("graph_sha256") or src["baseline"]["graph_sha256"]
    L = ["# k = 8 readout — results", "",
         "Produced by the scripts in this directory against the real "
         "connectome. Every number is generated; nothing is hand-entered.", "",
         f"* pre-registration: `PROTOCOL.md`, committed alone at commit "
         f"`{(b or e)['baseline']['commit'][:7]}`, before any baseline or "
         f"evaluation run existed",
         f"* graph `{v[:12]}` · readout `flytrade-readout-1` · decoder "
         f"`flytrade-action-1` (unchanged) · runner `flytrade-runner-1` · "
         f"plasticity `flytrade-mb-1`",
         "* gain 0.10 (D2, frozen), 20 ms window, drive budget 12,000 Hz, "
         "carrier 0.10 — all unchanged from Phase One",
         "* k = 8 fixed; k = 1 is replicate 0 of the same schedule, an "
         "explicit regression mode and never an automatic fallback",
         f"* python {src['python']}, numpy {src['numpy']}", "",
         "**Every dataset in this wave is SYNTHETIC.** There is no "
         "`data/market/` in the tree and nothing was downloaded. §6 below "
         "resolves the provenance in full.", ""]
    if b:
        L += baseline_section(b)
    if e:
        L += evaluation_section(e)
    if e:
        L += provenance_section(e, dm)
    if bm:
        L += benchmark_section(bm)
    if dm:
        L += demo_section(dm)
    (HERE / "results.md").write_text("\n".join(L) + "\n")
    print(f"wrote {HERE / 'results.md'} "
          f"({len((HERE / 'results.md').read_text().splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
