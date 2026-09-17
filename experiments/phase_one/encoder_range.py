#!/usr/bin/env python
"""
Encoder operating-range measurement — canonical amendment D2, Fable addendum 2.

    .venv/bin/python experiments/phase_one/encoder_range.py

The gain is frozen at 0.10 throughout and is never a free parameter here. D2
orders that if nominal encoder inputs collapse into silence or saturation, the
*declared input operating range* is restricted — never the gain. This script is
that restriction, measured.

**Part 0 — the two rejected codings.** Reported so the design history is
reproducible instead of anecdotal. ``balanced`` and ``rectified`` are measured
at two representative per-ORN drive ceilings each. Both fail, and they fail in
opposite directions, which is the finding that produced the final rule.

**Part A — the declared input operating range.** For the ``normalized`` coding,
the grid ``DRIVE_BUDGETS_HZ x CARRIERS`` against the three sanity criteria
pre-registered in ``experiments/conditioning/PROTOCOL.md`` §2: no silent MBON
readout, mean Kenyon-cell active fraction below 0.25, pairwise Kenyon-cell
Jaccard below 0.40. One declared selection rule: among cells satisfying all
three take the **largest** budget, and among those the **smallest** carrier —
a larger carrier only costs discrimination. One pass, no further sweep, no
market quantity anywhere in the choice.

Scope of criterion (iii). The Jaccard threshold is applied to the four nominal
market states addendum 2 names (strong up, strong down, flat/low-vol,
flat/high-vol). The two corner patterns are range probes for silence and
saturation: ``corner_plus`` is deliberately a more extreme version of
``strong_up``, so a *low* Jaccard between them would mean the encoder is
discontinuous, not that it is discriminating. Every pair is reported anyway.

**Part C — the baseline readout at the neutral reference.** Addendum 4 requires
the decoder's WAIT margin to be stated in units of the measured seed-to-seed SD
of the baseline readout, so that measurement has to exist before
``docs/DECODER.md`` is written. The neutral reference is ``u = 0`` — every
feature at its own trailing median, i.e. a market with no information in it —
presented at the declared range with unlearned weights over the declared 8
seeds. Reported for the full compartments and for the subset of MBONs the
valence literature attributes a direction to (``populations.mbon_attributed``,
MBON01-MBON15), because that subset is what a decoder is entitled to read.

**Part B — the addendum-2 table.** Gains {0.08, 0.10, 0.12} x 8 seeds x six
nominal patterns at the declared range: silence, saturation, KC recruitment,
MBON response SD across seeds, pairwise discrimination. Report only; nothing is
selected on it and the gain stays 0.10 whatever it says.

Writes ``encoder_range.json`` next to this file. The markdown tables it prints
are the ones reproduced in ``docs/ENCODER.md``.
"""
from __future__ import annotations

import json
import platform
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "upstream"))

from flytrade import encoder as E        # noqa: E402
from flytrade import graph as G          # noqa: E402
from flytrade import market as MK        # noqa: E402
from flytrade import mushroom as M       # noqa: E402
from flytrade import populations as P    # noqa: E402

DATA = ROOT / "data" / "malecns-v1.0"

SEEDS = list(range(1, 9))
DRIVE_BUDGETS_HZ = (24000.0, 18000.0, 12000.0, 8000.0, 5000.0)   # largest first
CARRIERS = (0.20, 0.10, 0.05)                                    # largest first
GAINS = (0.08, 0.10, 0.12)
FROZEN_GAIN = 0.10

#: Part 0: the rejected codings, at two per-ORN ceilings each
REJECTED = (("balanced", 150.0), ("balanced", 90.0),
            ("rectified", 150.0), ("rectified", 90.0))

#: the four nominal market states criterion (iii) is applied to
DISCRIMINATION_PATTERNS = ("strong_up", "strong_down",
                           "flat_low_vol", "flat_high_vol")

#: PROTOCOL.md §2 criteria, unchanged
MAX_KC_FRACTION = 0.25
MAX_JACCARD = 0.40

#: a readout is "saturated" if an MBON sits within 5% of the refractory
#: ceiling, 1000 / 2.2 ms = 454.5 Hz
REFRACTORY_CEILING_HZ = 1000.0 / 2.2
SATURATED_HZ = 0.95 * REFRACTORY_CEILING_HZ

#: six nominal patterns spanning the declared input range, in the fixed
#: feature order (r1, r5, r20, rv20, relvol). Addendum 2 asks for at least
#: four: strong up, strong down, flat/low-vol, flat/high-vol. The two corners
#: are added because they are where silence and saturation would appear first.
PATTERNS = {
    "strong_up":     (+0.80, +0.90, +0.90, +0.20, +0.50),
    "strong_down":   (-0.80, -0.90, -0.90, +0.60, +0.70),
    "flat_low_vol":  (0.00, 0.00, 0.00, -0.80, -0.60),
    "flat_high_vol": (0.00, 0.00, 0.00, +0.80, +0.60),
    "corner_plus":   (+1.00, +1.00, +1.00, +1.00, +1.00),
    "corner_minus":  (-1.00, -1.00, -1.00, -1.00, -1.00),
}

#: the neutral reference: every feature at its own trailing median
NEUTRAL = (0.00, 0.00, 0.00, 0.00, 0.00)


def jaccard(a: set, b: set) -> float:
    u = len(a | b)
    return float(len(a & b) / u) if u else 0.0


def measure(fb, mb, stim, gains, seed) -> dict:
    rec = {"mbon": mb.mbon, "kc": mb.kc,
           "pam": mb.compartments.pam_side, "ppl1": mb.compartments.ppl1_side}
    r = fb.run(stim.drive, steps=E.STEPS, gains=gains, record=rec, seed=seed)
    mbon, kc = r["mbon"], r["kc"]
    return {
        "mbon_mean_hz": float(mbon.mean()),
        "mbon_max_hz": float(mbon.max()),
        "mbon_active_fraction": float((mbon > 0).mean()),
        "pam_hz": float(r["pam"].mean()),
        "ppl1_hz": float(r["ppl1"].mean()),
        "kc_fraction": float((kc > 0).mean()),
        "kc_hz": float(kc.mean()),
        "silent": bool(mbon.sum() == 0.0),
        "saturated_mbons": int((mbon >= SATURATED_HZ).sum()),
        "total_hz": float(r["_total_hz"]),
        "kc_set": set(int(i) for i in mb.kc[kc > 0]),
    }


def sweep(fb, mb, ann, gain_value, **enc_kw) -> dict:
    enc = E.MarketToSensoryEncoder(ann, **enc_kw)
    gains = np.full(fb.n_types, float(gain_value), dtype=np.float32)
    per_pattern, kc_sets = {}, {}
    for name, u in PATTERNS.items():
        stim = enc.encode_features(u, symbol=name)
        rows = [measure(fb, mb, stim, gains, 1000 + s) for s in SEEDS]
        kc_sets[name] = [r.pop("kc_set") for r in rows]
        agg = {k: float(np.mean([r[k] for r in rows]))
               for k in ("mbon_mean_hz", "mbon_max_hz", "mbon_active_fraction",
                         "pam_hz", "ppl1_hz", "kc_fraction", "kc_hz",
                         "total_hz")}
        agg["mbon_sd_hz"] = float(np.std([r["mbon_mean_hz"] for r in rows], ddof=1))
        agg["pam_sd_hz"] = float(np.std([r["pam_hz"] for r in rows], ddof=1))
        agg["ppl1_sd_hz"] = float(np.std([r["ppl1_hz"] for r in rows], ddof=1))
        agg["valence_mean_hz"] = float(np.mean(
            [r["ppl1_hz"] - r["pam_hz"] for r in rows]))
        agg["valence_sd_hz"] = float(np.std(
            [r["ppl1_hz"] - r["pam_hz"] for r in rows], ddof=1))
        agg["silent_trials"] = int(sum(r["silent"] for r in rows))
        agg["saturated_trials"] = int(sum(r["saturated_mbons"] > 0 for r in rows))
        agg["total_drive_hz"] = float(stim.total_drive_hz)
        agg["max_orn_hz"] = float(max(stim.rates.values()))
        per_pattern[name] = agg

    names = list(PATTERNS)
    pairs = {}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            j = [jaccard(x, y) for x, y in zip(kc_sets[a], kc_sets[b])]
            pairs[f"{a}|{b}"] = {
                "kc_jaccard": float(np.mean(j)),
                "valence_gap_hz": abs(per_pattern[a]["valence_mean_hz"]
                                      - per_pattern[b]["valence_mean_hz"])}
    nominal = [v["kc_jaccard"] for k, v in pairs.items()
               if all(x in DISCRIMINATION_PATTERNS for x in k.split("|"))]
    return {
        "encoder": enc.as_dict(), "gain": gain_value,
        "patterns": per_pattern, "pairs": pairs,
        "max_kc_fraction": max(p["kc_fraction"] for p in per_pattern.values()),
        "min_kc_fraction": min(p["kc_fraction"] for p in per_pattern.values()),
        "max_jaccard_nominal": max(nominal),
        "max_jaccard_all": max(p["kc_jaccard"] for p in pairs.values()),
        "silent_trials": sum(p["silent_trials"] for p in per_pattern.values()),
        "saturated_trials": sum(p["saturated_trials"] for p in per_pattern.values()),
    }


def criteria_pass(res: dict) -> tuple[bool, str]:
    reasons = []
    if res["silent_trials"]:
        reasons.append(f"{res['silent_trials']} silent MBON trials")
    if res["max_kc_fraction"] >= MAX_KC_FRACTION:
        reasons.append(f"max KC fraction {res['max_kc_fraction']:.3f} "
                       f">= {MAX_KC_FRACTION}")
    if res["max_jaccard_nominal"] >= MAX_JACCARD:
        reasons.append(f"max nominal KC Jaccard "
                       f"{res['max_jaccard_nominal']:.3f} >= {MAX_JACCARD}")
    return (not reasons), "; ".join(reasons) or "all three criteria met"


def line(tag, res, ok, why):
    print(f"  {tag:34s} KCmax {res['max_kc_fraction']:.3f}  "
          f"Jnom {res['max_jaccard_nominal']:.3f}  "
          f"Jall {res['max_jaccard_all']:.3f}  "
          f"silent {res['silent_trials']:2d}/48  "
          f"sat {res['saturated_trials']:2d}/48  -> "
          f"{'PASS' if ok else 'FAIL: ' + why}")


def main() -> int:
    t0 = time.time()
    import flysim

    fb = flysim.FlyBrain(graph_path=DATA / "graph.npz")
    mod = G.ModulatoryGraph(DATA / "graph_mod.npz", bodies=fb.bodies)
    ann = P.Annotations.load(DATA / "annotations.npz")
    mb = M.MushroomBody(fb, mod,
                        np.flatnonzero(P.kenyon_cells(ann)),
                        np.flatnonzero(P.mbons(ann)),
                        np.flatnonzero(P.pam(ann)),
                        np.flatnonzero(P.ppl1(ann)))

    probe = E.MarketToSensoryEncoder(ann)
    print(f"channels: {probe.glomeruli}  ORNs {probe.n_orns}")

    # ---- Part 0: the rejected codings ----------------------------------
    part0 = {}
    for coding, hz in REJECTED:
        res = sweep(fb, mb, ann, FROZEN_GAIN, coding=coding, drive_max_hz=hz,
                    carrier=0.10)
        ok, why = criteria_pass(res)
        res["passes"], res["reason"] = ok, why
        part0[f"{coding}/{hz:.0f}"] = res
        line(f"[rejected] {coding} {hz:.0f} Hz", res, ok, why)

    # ---- Part A: declared input operating range -------------------------
    part_a, passing = {}, []
    for b in DRIVE_BUDGETS_HZ:
        for c in CARRIERS:
            res = sweep(fb, mb, ann, FROZEN_GAIN, drive_budget_hz=b, carrier=c)
            ok, why = criteria_pass(res)
            res["passes"], res["reason"] = ok, why
            part_a[f"{b:.0f}/{c:.2f}"] = res
            line(f"budget {b:.0f} Hz carrier {c:.2f}", res, ok, why)
            if ok:
                passing.append((b, c))

    chosen_budget = chosen_carrier = None
    if passing:
        chosen_budget = max(b for b, _ in passing)
        chosen_carrier = min(c for b, c in passing if b == chosen_budget)
        print(f"  declared operating range: budget {chosen_budget:.0f} Hz, "
              f"carrier {chosen_carrier:.2f}")
    else:
        print("NO cell of the grid satisfies the criteria; the declared "
              "operating range is EMPTY and this is reported as such, not "
              "worked around by raising the gain.")

    # ---- Part B: the addendum-2 table ----------------------------------
    part_b = {}
    if chosen_budget is not None:
        key = f"{chosen_budget:.0f}/{chosen_carrier:.2f}"
        for g in GAINS:
            res = (part_a[key] if g == FROZEN_GAIN else
                   sweep(fb, mb, ann, g, drive_budget_hz=chosen_budget,
                         carrier=chosen_carrier))
            part_b[str(g)] = res
            print(f"  gain {g:.2f}  KCmax {res['max_kc_fraction']:.3f}  "
                  f"Jnom {res['max_jaccard_nominal']:.3f}  "
                  f"silent {res['silent_trials']}/48  "
                  f"sat {res['saturated_trials']}/48")

    # ---- Part C: baseline readout at the neutral reference --------------
    reference = None
    if chosen_budget is not None:
        enc = E.MarketToSensoryEncoder(ann, drive_budget_hz=chosen_budget,
                                       carrier=chosen_carrier)
        gains = np.full(fb.n_types, FROZEN_GAIN, dtype=np.float32)
        stim = enc.encode_features(NEUTRAL, symbol="neutral_reference")
        att = np.flatnonzero(P.mbon_attributed(ann))
        pam_a = np.array([i for i in mb.compartments.pam_side if i in set(att)])
        ppl1_a = np.array([i for i in mb.compartments.ppl1_side if i in set(att)])
        rec = {"pam": mb.compartments.pam_side, "ppl1": mb.compartments.ppl1_side,
               "pam_a": pam_a, "ppl1_a": ppl1_a, "kc": mb.kc, "mbon": mb.mbon}
        acc = {k: [] for k in rec}
        for s in SEEDS:
            r = fb.run(stim.drive, steps=E.STEPS, gains=gains, record=rec,
                       seed=1000 + s)
            for k in rec:
                acc[k].append(r[k])
        g = lambda k: np.array([x.mean() for x in acc[k]])
        pam, ppl1 = g("pam"), g("ppl1")
        pam_ar, ppl1_ar = g("pam_a"), g("ppl1_a")
        diff, diff_a = ppl1 - pam, ppl1_ar - pam_ar
        reference = {
            "normalized": list(NEUTRAL),
            "orn_hz": float(max(stim.rates.values())),
            "total_drive_hz": float(stim.total_drive_hz),
            "n_pam": int(len(mb.compartments.pam_side)),
            "n_ppl1": int(len(mb.compartments.ppl1_side)),
            "n_pam_attributed": int(len(pam_a)),
            "n_ppl1_attributed": int(len(ppl1_a)),
            "pam_hz_mean": float(pam.mean()), "pam_hz_sd": float(pam.std(ddof=1)),
            "ppl1_hz_mean": float(ppl1.mean()), "ppl1_hz_sd": float(ppl1.std(ddof=1)),
            "diff_hz_mean": float(diff.mean()), "diff_hz_sd": float(diff.std(ddof=1)),
            "attributed_pam_hz_mean": float(pam_ar.mean()),
            "attributed_pam_hz_sd": float(pam_ar.std(ddof=1)),
            "attributed_ppl1_hz_mean": float(ppl1_ar.mean()),
            "attributed_ppl1_hz_sd": float(ppl1_ar.std(ddof=1)),
            "attributed_diff_hz_mean": float(diff_a.mean()),
            "attributed_diff_hz_sd": float(diff_a.std(ddof=1)),
            "attributed_diff_per_seed": [float(x) for x in diff_a],
            "kc_fraction": float(np.mean([(x > 0).mean() for x in acc["kc"]])),
            "silent_trials": int(sum(x.sum() == 0.0 for x in acc["mbon"])),
        }
        print(f"  neutral reference: all-compartment diff "
              f"{reference['diff_hz_mean']:+.3f} +/- {reference['diff_hz_sd']:.3f} Hz; "
              f"attributed ({len(pam_a)} PAM-side / {len(ppl1_a)} PPL1-side) "
              f"{reference['attributed_diff_hz_mean']:+.4f} +/- "
              f"{reference['attributed_diff_hz_sd']:.4f} Hz")

    # ---- where do real observations land? -------------------------------
    series = {f"SYN{i}": MK.synthetic_series(f"SYN{i}", seed=100 + i)
              for i in range(4)}
    feed = MK.ObservationFeed(series)
    us = [o.normalized for sym, s in series.items()
          for i in range(MK.MIN_HISTORY_BARS - 1, len(s))
          for o in (feed.observe(sym, i),) if o.status.usable]
    U = np.stack(us)
    in_range = {
        "n_observations": int(len(U)),
        "min": [float(x) for x in U.min(axis=0)],
        "max": [float(x) for x in U.max(axis=0)],
        "p01": [float(x) for x in np.percentile(U, 1, axis=0)],
        "p99": [float(x) for x in np.percentile(U, 99, axis=0)],
        "abs_mean": [float(x) for x in np.abs(U).mean(axis=0)],
    }
    print("  synthetic observations, per-feature mean |u|: "
          + ", ".join(f"{n}={v:.3f}" for n, v in
                      zip(MK.FEATURES, in_range["abs_mean"])))

    out = {
        "encoder_version": E.VERSION, "market_version": MK.VERSION,
        "mushroom_version": M.VERSION,
        "graph_sha256": G.sha256_file(DATA / "graph.npz"),
        "python": platform.python_version(), "numpy": np.__version__,
        "seeds": SEEDS, "patterns": {k: list(v) for k, v in PATTERNS.items()},
        "criteria": {"max_kc_fraction": MAX_KC_FRACTION,
                     "max_jaccard": MAX_JACCARD,
                     "saturated_hz": SATURATED_HZ,
                     "discrimination_patterns": list(DISCRIMINATION_PATTERNS)},
        "part0_rejected_codings": part0,
        "part_a_operating_range": part_a,
        "chosen_drive_budget_hz": chosen_budget,
        "chosen_carrier": chosen_carrier,
        "part_b_gain_table": part_b,
        "neutral_reference": reference,
        "synthetic_observation_range": in_range,
        "channel_table": probe.channel_table(ann),
        "elapsed_s": time.time() - t0,
    }
    (HERE / "encoder_range.json").write_text(json.dumps(out, indent=2))
    print(render(out))
    print(f"wrote {HERE / 'encoder_range.json'} in {out['elapsed_s']:.1f}s")
    return 0


def render(out: dict) -> str:
    L = ["", "### Channel map", "",
         "| feature | + glomerulus | ORNs | uPNs | - glomerulus | ORNs | uPNs |",
         "|---|---|--:|--:|---|--:|--:|"]
    for r in out["channel_table"]:
        L.append(f"| `{r['feature']}` | {r['positive']} | {r['pos_orns']} | "
                 f"{r['pos_upns']} | {r['negative']} | {r['neg_orns']} | "
                 f"{r['neg_upns']} |")

    L += ["", "### Part 0 — the two rejected codings (gain 0.10, carrier 0.10)",
          "", "| coding | per-ORN ceiling Hz | max KC fraction | "
              "max nominal KC Jaccard | silent | verdict |",
          "|---|--:|--:|--:|--:|---|"]
    for key, r in out["part0_rejected_codings"].items():
        coding, hz = key.split("/")
        L.append(f"| `{coding}` | {float(hz):.0f} | {r['max_kc_fraction']:.3f} "
                 f"| {r['max_jaccard_nominal']:.3f} | {r['silent_trials']}/48 "
                 f"| rejected — {r['reason']} |")

    L += ["", "### Part A — declared input operating range (gain 0.10, "
              "8 seeds x 6 patterns per cell = 48 trials)", "",
          "| budget Hz | carrier | KC fraction min..max | "
          "max nominal KC Jaccard | max KC Jaccard, all pairs | silent | "
          "saturated | verdict |", "|--:|--:|---|--:|--:|--:|--:|---|"]
    for key, r in out["part_a_operating_range"].items():
        e = r["encoder"]
        L.append(f"| {e['drive_budget_hz']:.0f} | {e['carrier']:.2f} | "
                 f"{r['min_kc_fraction']:.3f}..{r['max_kc_fraction']:.3f} | "
                 f"{r['max_jaccard_nominal']:.3f} | {r['max_jaccard_all']:.3f} "
                 f"| {r['silent_trials']}/48 | {r['saturated_trials']}/48 | "
                 f"{'**PASS**' if r['passes'] else 'fail — ' + r['reason']} |")

    if out["part_b_gain_table"]:
        L += ["", f"### Part B — addendum 2, at the declared range "
                  f"(budget {out['chosen_drive_budget_hz']:.0f} Hz, carrier "
                  f"{out['chosen_carrier']:.2f})", "",
              "| gain | pattern | max ORN Hz | MBON mean Hz | MBON SD across "
              "seeds | PAM-side Hz | PPL1-side Hz | KC fraction | silent | "
              "saturated |", "|--:|---|--:|--:|--:|--:|--:|--:|--:|--:|"]
        for g, r in out["part_b_gain_table"].items():
            for name, p in r["patterns"].items():
                L.append(f"| {float(g):.2f} | `{name}` | {p['max_orn_hz']:.0f} "
                         f"| {p['mbon_mean_hz']:.2f} | {p['mbon_sd_hz']:.2f} | "
                         f"{p['pam_hz']:.2f} | {p['ppl1_hz']:.2f} | "
                         f"{p['kc_fraction']:.3f} | {p['silent_trials']}/8 | "
                         f"{p['saturated_trials']}/8 |")
        L += ["", "Pairwise discrimination at gain 0.10 (KC Jaccard, mean over "
                  "seeds; nominal pairs first):", "",
              "| pattern pair | KC Jaccard | abs valence gap Hz |",
              "|---|--:|--:|"]
        prs = out["part_b_gain_table"][str(FROZEN_GAIN)]["pairs"]
        nom = out["criteria"]["discrimination_patterns"]
        for k in sorted(prs, key=lambda k: not all(
                x in nom for x in k.split("|"))):
            v = prs[k]
            L.append(f"| {k.replace('|', ' vs ')} | {v['kc_jaccard']:.3f} | "
                     f"{v['valence_gap_hz']:.2f} |")
        base = out["part_b_gain_table"][str(FROZEN_GAIN)]["patterns"]
        L += ["", "Baseline readout SD across the 8 seeds, per pattern — the "
                  "unit the decoder's WAIT margin is expressed in:", "",
              "| pattern | PAM-side SD Hz | PPL1-side SD Hz | "
              "(PPL1 - PAM) SD Hz |", "|---|--:|--:|--:|"]
        for name, p in base.items():
            L.append(f"| `{name}` | {p['pam_sd_hz']:.3f} | "
                     f"{p['ppl1_sd_hz']:.3f} | {p['valence_sd_hz']:.3f} |")
        sds = [p["valence_sd_hz"] for p in base.values()]
        L += ["", f"Mean (PPL1 - PAM) SD over the six patterns: "
                  f"**{float(np.mean(sds)):.3f} Hz**; max "
                  f"{float(np.max(sds)):.3f} Hz."]

    r = out.get("neutral_reference")
    if r:
        L += ["", "### Part C — baseline readout at the neutral reference "
                  "(u = 0, gain 0.10, unlearned weights, 8 seeds)", "",
              "| quantity | mean | SD across seeds |", "|---|--:|--:|",
              f"| PAM-side rate, Hz | {r['pam_hz_mean']:.3f} | "
              f"{r['pam_hz_sd']:.3f} |",
              f"| PPL1-side rate, Hz | {r['ppl1_hz_mean']:.3f} | "
              f"{r['ppl1_hz_sd']:.3f} |",
              f"| difference PPL1 - PAM, Hz | {r['diff_hz_mean']:+.3f} | "
              f"{r['diff_hz_sd']:.3f} |",
              f"| PAM-side rate, attributed subset "
              f"({r['n_pam_attributed']} of {r['n_pam']}), Hz | "
              f"{r['attributed_pam_hz_mean']:.3f} | "
              f"{r['attributed_pam_hz_sd']:.3f} |",
              f"| PPL1-side rate, attributed subset "
              f"({r['n_ppl1_attributed']} of {r['n_ppl1']}), Hz | "
              f"{r['attributed_ppl1_hz_mean']:.3f} | "
              f"{r['attributed_ppl1_hz_sd']:.3f} |",
              f"| **difference, attributed subset, Hz** | "
              f"**{r['attributed_diff_hz_mean']:+.4f}** | "
              f"**{r['attributed_diff_hz_sd']:.4f}** |",
              f"| Kenyon-cell active fraction | {r['kc_fraction']:.4f} | — |",
              "",
              f"Per-ORN drive at the reference {r['orn_hz']:.1f} Hz, total "
              f"{r['total_drive_hz']:,.0f} Hz, silent trials "
              f"{r['silent_trials']}/8."]
    return "\n".join(L)


if __name__ == "__main__":
    raise SystemExit(main())
