#!/usr/bin/env python
"""
Does reinforcement change what the *decoder* says? — canonical amendment §4.

    .venv/bin/python experiments/phase_one/learning_demo.py

Phase 0.5 showed that a paired stimulus changes a later neural response. That
is not the same claim as "experience changes the decision the system produces",
and the amendment is explicit that it must not be treated as one. This script
runs the same experimental shape through the **fixed, pre-registered decoder**
of `docs/DECODER.md` and asks the harder question, for both reinforcement
branches.

Nothing here trades. There is no price, no position, no PnL, no execution
policy: the reinforcement valence is delivered directly, as an experimental
variable, exactly as `experiments/conditioning/run.py` delivered it.

## Two protocols, and why there are two

``v1`` is the protocol as it was pre-registered in this file's first commit and
run. **It failed**, and it is kept and re-run unchanged because a failed
pre-registration is evidence, not something to quietly replace. Its contexts
are the first bar index at or after ``CUTOFF_FROM`` at which both instruments
give a non-silent decoder readout, and each measurement is a single 20 ms
presentation.

``v2`` is a **declared deviation**, written after v1's numbers were seen, with
its reason stated. Two changes, both aimed at the measured cause of v1's
failure and neither at its direction:

1. *Contexts are chosen for sensory contrast.* v1 took whatever bar came first,
   and drew two contexts that share most of their Kenyon cells; training on Y
   then moved X more than training on X did, which is not specificity failing
   so much as the two stimuli not being distinct. v2 scans a declared window
   over four instruments and takes the observation with the **largest positive**
   twenty-bar return as ``X`` and the one with the **largest negative** as
   ``Y``. That is a rule over the *sensory* content of the stimulus, the direct
   analogue of `PROTOCOL.md` §3 choosing two odours with no glomerulus in
   common. No outcome, no PnL and no profitability enters it.
2. *Measurement averages over ``MEASURE_REPEATS`` presentations.* A 20 ms
   window over 29 and 16 neurons quantises the readout at 1.724 Hz and
   3.125 Hz per spike — every non-zero ``dV`` in v1 is an exact multiple of
   those. Half the per-seed effects were smaller than one spike and were
   recorded as exactly zero. Averaging eight presentations (same eight seeds
   before and after) resolves an eighth of a spike. The **actions** are still
   decoded from single presentations and are reported as a count over the
   eight, because a single presentation is what the live loop decodes from.

The presentation window stays 20 ms, the gain stays 0.10 and the decoder is
untouched: Fable addendum 1 fixes the first two and addendum 3 the third.

## Contexts

Two market contexts, reached through the whole path — bars, causal features,
encoder, ORNs, Kenyon cells, MBONs — not two hand-made stimuli. ``X`` is the
reinforced context; ``Y`` is never reinforced in the paired conditions and is
the stimulus-specificity control.

## Conditions, 8 seeds each, 20 trials each

=========================  ==================================================
``APPETITIVE_ON``          present X, observe, dopamine(+1) -> PAM, apply, forget
``APPETITIVE_OFF``         identical schedule and seeds, plasticity never applied
``AVERSIVE_ON``            present X, observe, dopamine(-1) -> PPL1, apply, forget
``AVERSIVE_OFF``           identical schedule and seeds, plasticity never applied
``APPETITIVE_OTHER``       present **Y**, dopamine(+1); X is never reinforced
``AVERSIVE_OTHER``         present **Y**, dopamine(-1); X is never reinforced
=========================  ==================================================

The ``OTHER`` conditions are the informative controls and they are the ones the
verdict rests on. Phase 0.5's ``UNPAIRED`` control is deliberately **not**
repeated: it is zero by construction — after six decay cycles nothing is
eligible, so the dopamine event depresses nothing — and the Fable review of
that wave recorded that it is not on its own evidence of associative
selectivity. Citing it here as such would be repeating a mistake already
caught.

## Predictions, pre-registered

They follow from the sign convention in `docs/DECODER.md` §3 and from
depression-only plasticity, and they are stated before the run:

* ``APPETITIVE_ON`` depresses PAM-innervated synapses, so ``avoid`` falls and
  **V rises**: ``dV_X > 0``.
* ``AVERSIVE_ON`` depresses PPL1-innervated synapses, so ``approach`` falls and
  **V falls**: ``dV_X < 0``.
* Both ``OFF`` conditions move nothing: ``dV_X == 0`` exactly.
* Each ``OTHER`` condition moves X less than its paired condition does, in the
  same direction: ``dV_X[ON] - dV_X[OTHER]`` keeps the branch's sign.

## Decision rule

The demonstration counts as made iff all four hold:

1. ``dV_X > 0`` in at least 7 of 8 seeds under ``APPETITIVE_ON``;
2. ``dV_X < 0`` in at least 7 of 8 seeds under ``AVERSIVE_ON``;
3. ``dV_X == 0`` in 8 of 8 seeds under both ``OFF`` conditions;
4. ``dV_X[ON] - dV_X[OTHER]`` keeps the branch's sign in at least 7 of 8 seeds,
   for both branches.

Decoded actions are **reported, not gated**: the amendment says not to require
every trial to flip a discrete action.

Writes ``learning.json`` next to this file.
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

from flytrade import decoder as D        # noqa: E402
from flytrade import encoder as E        # noqa: E402
from flytrade import graph as G          # noqa: E402
from flytrade import market as MK        # noqa: E402
from flytrade import mushroom as M       # noqa: E402
from flytrade import populations as P    # noqa: E402
from flytrade import runner as R         # noqa: E402

DATA = ROOT / "data" / "malecns-v1.0"

SEEDS = list(range(1, 9))
TRIALS = 20
CUTOFF_FROM = 300
CONTEXT_SEEDS = (900, 901)          # v1: the two synthetic instruments
#: v2: four instruments scanned over a declared window for feature contrast
V2_CONTEXT_SEEDS = (900, 901, 902, 903)
V2_SCAN = (200, 420)
#: v2: presentations averaged per measurement, to resolve below one spike
MEASURE_REPEATS = 8
CONDITIONS = ("APPETITIVE_ON", "APPETITIVE_OFF", "AVERSIVE_ON",
              "AVERSIVE_OFF", "APPETITIVE_OTHER", "AVERSIVE_OTHER")
BRANCH = {"APPETITIVE_ON": +1, "APPETITIVE_OFF": +1, "APPETITIVE_OTHER": +1,
          "AVERSIVE_ON": -1, "AVERSIVE_OFF": -1, "AVERSIVE_OTHER": -1}
DECISION_MIN_SEEDS = 7


def measurement_seed(s: int) -> int:
    return 1000 + s


def training_seed(s: int, trial: int) -> int:
    return 3000 + 100 * s + trial


def measure(run, dec, stim, seed, repeats: int = 1) -> dict:
    """Present ``repeats`` times and decode. Never observes, never learns.

    With ``repeats == 1`` this is v1's measurement. With more, the readout
    rates are averaged before decoding — which resolves below the one-spike
    quantum — while the per-presentation actions are kept separately, because
    a single presentation is what the live loop decodes from.
    """
    s0 = run.snapshot()
    app, avo, kcf, kca, acts, stats = [], [], [], [], [], []
    for m in range(repeats):
        pres = run.present(stim, seed=seed + m, episode_id=-1, observe=False)
        d = dec.decode(pres)
        app.append(d.approach_hz)
        avo.append(d.avoid_hz)
        kcf.append(pres.kc_fraction)
        kca.append(pres.kc_active)
        acts.append(d.action.value)
        stats.append(d.status.value)
    run.restore(s0)
    mean = dec.decode_rates(float(np.mean(app)), float(np.mean(avo)),
                            kc_fraction=float(np.mean(kcf)))
    return {"valence_hz": mean.valence_hz, "raw_valence_hz": mean.raw_valence_hz,
            "approach_hz": mean.approach_hz, "avoid_hz": mean.avoid_hz,
            "action": mean.action.value, "status": mean.status.value,
            "kc_fraction": float(np.mean(kcf)), "kc_active": float(np.mean(kca)),
            "repeats": repeats,
            "actions": acts, "statuses": stats,
            "n_buy": acts.count("BUY"), "n_sell": acts.count("SELL"),
            "n_wait": acts.count("WAIT"),
            "n_no_response": acts.count("NO_RESPONSE")}


def train(run, mb, stim, s, condition) -> list[dict]:
    log = []
    valence = BRANCH[condition]
    plastic = not condition.endswith("_OFF")
    for trial in range(TRIALS):
        ep = 10_000 + trial
        run.present(stim, seed=training_seed(s, trial), episode_id=ep)
        depressed = 0
        if plastic:
            depressed = mb.dopamine(valence, 1.0, episode_id=ep)
            mb.apply()
            mb.forget()
        log.append({"trial": trial, "depressed": int(depressed),
                    "max_trace": float(mb.trace.max())})
    return log


def weight_report(mb) -> dict:
    moved = mb.gain < 0.995
    return {
        "synapses_moved": int(moved.sum()),
        "moved_pam_side": int((moved & (mb.side == 1)).sum()),
        "moved_ppl1_side": int((moved & (mb.side == -1)).sum()),
        "mean_gain": float(mb.gain.mean()),
        "min_gain": float(mb.gain.min()),
    }


def pick_contexts_v1(run, dec, feed, universe, symbols) -> tuple:
    """v1: first cutoff at or after CUTOFF_FROM where both contexts read out."""
    n = min(feed.bars(s) for s in symbols)
    for i in range(CUTOFF_FROM, n):
        obs = [feed.observe(s, i, stable_id=universe.stable_id(s))
               for s in symbols]
        if not all(o.status.usable for o in obs):
            continue
        stims = [run.encoder.encode(o) for o in obs]
        reads = [measure(run, dec, st, measurement_seed(1)) for st in stims]
        if all(r["status"] == D.ReadoutStatus.VALID.value for r in reads):
            return obs, stims, reads, {"rule": "first usable cutoff at or "
                                       f"after bar {CUTOFF_FROM}",
                                       "bars": {o.symbol: o.bar_index
                                                for o in obs}}
    raise RuntimeError("no cutoff at or after CUTOFF_FROM gives both contexts "
                       "a valid decoder readout")


def pick_contexts_v2(run, dec, feed, universe, symbols) -> tuple:
    """v2: maximal sensory contrast — the extreme twenty-bar returns.

    A rule over the stimulus's own sensory content, not over any outcome: X is
    the usable observation in the declared scan window with the largest
    positive ``r20``, Y the one with the largest negative ``r20``.
    """
    k = MK.FEATURES.index("r20")
    lo, hi = V2_SCAN
    best_up = best_dn = None
    for sym in symbols:
        for i in range(max(lo, MK.MIN_HISTORY_BARS - 1),
                       min(hi, feed.bars(sym))):
            o = feed.observe(sym, i, stable_id=universe.stable_id(sym))
            if not o.status.usable:
                continue
            u = float(o.normalized[k])
            if best_up is None or u > float(best_up.normalized[k]):
                best_up = o
            if best_dn is None or u < float(best_dn.normalized[k]):
                best_dn = o
    obs = [best_up, best_dn]
    stims = [run.encoder.encode(o) for o in obs]
    reads = [measure(run, dec, st, measurement_seed_v2(1), MEASURE_REPEATS)
             for st in stims]
    return obs, stims, reads, {
        "rule": f"extreme r20 over bars {lo}..{hi} of {len(symbols)} "
                "instruments",
        "bars": {f"{o.symbol}@{o.bar_index}": round(float(o.normalized[k]), 4)
                 for o in obs}}


def kc_overlap(run, stims, seed, repeats) -> float:
    """Mean Kenyon-cell Jaccard between the two contexts, over the repeats."""
    sets = []
    for st in stims:
        s0 = run.snapshot()
        acc = []
        for m in range(repeats):
            rec = {"kc": run.mb.kc}
            r = run.fb.run(st.drive, steps=run.steps, gains=run.gains,
                           record=rec, seed=seed + m)
            acc.append(set(int(i) for i in run.mb.kc[r["kc"] > 0]))
        run.restore(s0)
        sets.append(acc)
    js = [len(a & b) / len(a | b) if (a | b) else 0.0
          for a, b in zip(*sets)]
    return float(np.mean(js))


def run_protocol(run, mb, dec, name, obs, stims, reads, meta, seed_fn,
                 repeats) -> dict:
    stim_x, stim_y = stims
    jac = kc_overlap(run, stims, seed_fn(1), max(repeats, 4))
    print(f"\n[{name}] contexts: X={stim_x.symbol}@{stim_x.bar_index} "
          f"V={reads[0]['valence_hz']:+.3f} {reads[0]['action']}; "
          f"Y={stim_y.symbol}@{stim_y.bar_index} "
          f"V={reads[1]['valence_hz']:+.3f} {reads[1]['action']}")
    results = []
    for cond in CONDITIONS:
        for s in SEEDS:
            mb.gain[:] = 1.0
            mb.trace[:] = 0.0
            mb.trace_episode[:] = -1
            mb.events = {"reward": 0, "punish": 0, "rejected_episode": 0}
            mb.apply()

            ms = seed_fn(s)
            pre_x = measure(run, dec, stim_x, ms, repeats)
            pre_y = measure(run, dec, stim_y, ms, repeats)
            trained = stim_y if cond.endswith("_OTHER") else stim_x
            log = train(run, mb, trained, s, cond)
            post_x = measure(run, dec, stim_x, ms, repeats)
            post_y = measure(run, dec, stim_y, ms, repeats)

            results.append({
                "condition": cond, "seed": s, "trained_on": trained.symbol,
                "pre_X": pre_x, "post_X": post_x,
                "pre_Y": pre_y, "post_Y": post_y,
                "dV_X": post_x["valence_hz"] - pre_x["valence_hz"],
                "dV_Y": post_y["valence_hz"] - pre_y["valence_hz"],
                "d_approach_X": post_x["approach_hz"] - pre_x["approach_hz"],
                "d_avoid_X": post_x["avoid_hz"] - pre_x["avoid_hz"],
                "d_kc_fraction_X": post_x["kc_fraction"] - pre_x["kc_fraction"],
                "action_changed_X": post_x["action"] != pre_x["action"],
                "weights": weight_report(mb), "events": dict(mb.events),
                "trials": log,
            })
            r = results[-1]
            print(f"  {cond:18s} seed {s}  dV_X={r['dV_X']:+8.3f}  "
                  f"{r['pre_X']['action']:>11s} -> {r['post_X']['action']:<11s} "
                  f"moved={r['weights']['synapses_moved']:,}")

    mb.gain[:] = 1.0
    mb.apply()

    by = {(r["condition"], r["seed"]): r for r in results}

    def dv(cond):
        return np.array([by[(cond, s)]["dV_X"] for s in SEEDS])

    app, ave = dv("APPETITIVE_ON"), dv("AVERSIVE_ON")
    app_off, ave_off = dv("APPETITIVE_OFF"), dv("AVERSIVE_OFF")
    spec_app = app - dv("APPETITIVE_OTHER")
    spec_ave = ave - dv("AVERSIVE_OTHER")

    checks = {
        "appetitive_positive_seeds": int((app > 0).sum()),
        "aversive_negative_seeds": int((ave < 0).sum()),
        "appetitive_off_zero_seeds": int((app_off == 0.0).sum()),
        "aversive_off_zero_seeds": int((ave_off == 0.0).sum()),
        "appetitive_specificity_seeds": int((spec_app > 0).sum()),
        "aversive_specificity_seeds": int((spec_ave < 0).sum()),
    }
    n, k = len(SEEDS), DECISION_MIN_SEEDS
    passed = (checks["appetitive_positive_seeds"] >= k
              and checks["aversive_negative_seeds"] >= k
              and checks["appetitive_off_zero_seeds"] == n
              and checks["aversive_off_zero_seeds"] == n
              and checks["appetitive_specificity_seeds"] >= k
              and checks["aversive_specificity_seeds"] >= k)
    return {
        "protocol": name, "meta": meta, "repeats": repeats,
        "kc_jaccard_xy": jac,
        "symbols": [stim_x.symbol, stim_y.symbol],
        "bars": [stim_x.bar_index, stim_y.bar_index],
        "baseline_readouts": {"X": reads[0], "Y": reads[1]},
        "runs": results,
        "summary": {
            "dV_X_mean": {c: float(dv(c).mean()) for c in CONDITIONS},
            "dV_X_per_seed": {c: [float(x) for x in dv(c)] for c in CONDITIONS},
            "specificity_appetitive_mean": float(spec_app.mean()),
            "specificity_aversive_mean": float(spec_ave.mean()),
            "actions_changed": {
                c: int(sum(by[(c, s)]["action_changed_X"] for s in SEEDS))
                for c in CONDITIONS},
            "checks": checks, "min_seeds": k, "n_seeds": n,
            "passed": bool(passed),
        },
    }


def measurement_seed_v2(s: int) -> int:
    """v2 spaces the seeds so the eight repeats of one seed never collide."""
    return 1000 + 10 * s


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
    enc = E.MarketToSensoryEncoder(ann)
    dec = D.ActionDecoder()
    pops = D.readout_populations(ann, mb.compartments)
    run = R.BrainRunner(fb, mb, enc, pops)
    print(f"readout: {len(pops[D.AVOID])} avoid (PAM-innervated) + "
          f"{len(pops[D.APPROACH])} approach (PPL1-innervated); "
          f"spike quantum {1000.0 / (E.STEPS * 0.2) / len(pops[D.AVOID]):.3f} "
          f"and {1000.0 / (E.STEPS * 0.2) / len(pops[D.APPROACH]):.3f} Hz")

    v1_syms = ("CTXX", "CTXY")
    v1_feed = MK.ObservationFeed({s: MK.synthetic_series(s, seed=CONTEXT_SEEDS[i])
                                  for i, s in enumerate(v1_syms)})
    v1_uni = MK.Universe(v1_syms)
    v1 = run_protocol(run, mb, dec, "v1",
                      *pick_contexts_v1(run, dec, v1_feed, v1_uni, v1_syms),
                      seed_fn=measurement_seed, repeats=1)

    v2_syms = tuple(f"CTX{i}" for i in range(len(V2_CONTEXT_SEEDS)))
    v2_feed = MK.ObservationFeed(
        {s: MK.synthetic_series(s, seed=V2_CONTEXT_SEEDS[i])
         for i, s in enumerate(v2_syms)})
    v2_uni = MK.Universe(v2_syms)
    v2_ctx = pick_contexts_v2(run, dec, v2_feed, v2_uni, v2_syms)
    v2 = run_protocol(run, mb, dec, "v2", *v2_ctx,
                      seed_fn=measurement_seed_v2, repeats=MEASURE_REPEATS)
    out = {
        "decoder": dec.as_dict(), "encoder": enc.as_dict(),
        "mushroom_version": M.VERSION, "runner_version": R.VERSION,
        "graph_sha256": G.sha256_file(DATA / "graph.npz"),
        "python": platform.python_version(), "numpy": np.__version__,
        "seeds": SEEDS, "trials": TRIALS,
        "readout_sizes": {k: int(len(v)) for k, v in pops.items()},
        "spike_quantum_hz": {k: 1000.0 / (E.STEPS * 0.2) / len(v)
                             for k, v in pops.items()},
        "protocols": {"v1": v1, "v2": v2},
        "elapsed_s": time.time() - t0,
    }
    (HERE / "learning.json").write_text(json.dumps(out, indent=2))
    print("\n" + render(out))
    print(f"\nwrote {HERE / 'learning.json'} in {out['elapsed_s']:.1f}s")
    return 0


def render_protocol(out, key) -> str:
    p = out["protocols"][key]
    by = {(r["condition"], r["seed"]): r for r in p["runs"]}
    S = out["seeds"]
    L = []
    a = L.append
    a(f"#### Contexts ({key}) — {p['meta']['rule']}\n")
    a(f"Kenyon-cell Jaccard between X and Y: **{p['kc_jaccard_xy']:.3f}**\n")
    for k, i in (("X", 0), ("Y", 1)):
        r = p["baseline_readouts"][k]
        a(f"* **{k}** = `{p['symbols'][i]}` at bar {p['bars'][i]}: approach "
          f"{r['approach_hz']:.2f} Hz, avoid {r['avoid_hz']:.2f} Hz, "
          f"V {r['valence_hz']:+.3f} Hz, decoded **{r['action']}**, "
          f"Kenyon fraction {r['kc_fraction']:.4f}")
    a("")
    a(f"#### Table — the decoder's output, before and after {out['trials']} "
      f"trials ({key}, mean over {len(S)} seeds)\n")
    a("| condition | trained on | dV(X) Hz | d approach(X) Hz | d avoid(X) Hz "
      "| dV(Y) Hz | seeds whose action changed | synapses moved PAM / PPL1 |")
    a("|---|---|--:|--:|--:|--:|--:|---|")
    for c in CONDITIONS:
        rows = [by[(c, s)] for s in S]
        m = lambda k: float(np.mean([r[k] for r in rows]))
        w = lambda k: int(np.mean([r["weights"][k] for r in rows]))
        a(f"| `{c}` | {rows[0]['trained_on']} | {m('dV_X'):+.3f} | "
          f"{m('d_approach_X'):+.3f} | {m('d_avoid_X'):+.3f} | "
          f"{m('dV_Y'):+.3f} | {p['summary']['actions_changed'][c]}/{len(S)} | "
          f"{w('moved_pam_side'):,} / {w('moved_ppl1_side'):,} |")
    a("")
    a(f"#### Table — dV(X) per seed ({key})\n")
    a("| seed | " + " | ".join(f"`{c}`" for c in CONDITIONS) + " |")
    a("|--:|" + "--:|" * len(CONDITIONS))
    for i, s in enumerate(S):
        a(f"| {s} | " + " | ".join(
            f"{p['summary']['dV_X_per_seed'][c][i]:+.3f}" for c in CONDITIONS)
          + " |")
    a("")
    ch = p["summary"]["checks"]
    n, k = p["summary"]["n_seeds"], p["summary"]["min_seeds"]
    a(f"#### Table — the decision rule ({key})\n")
    a("| check | prediction | seeds | threshold | verdict |")
    a("|---|---|--:|--:|:--|")
    for name, pred, got, need in [
            ("appetitive reaches the decoder", "dV(X) > 0 under APPETITIVE_ON",
             ch["appetitive_positive_seeds"], k),
            ("aversive reaches the decoder", "dV(X) < 0 under AVERSIVE_ON",
             ch["aversive_negative_seeds"], k),
            ("plasticity off, appetitive", "dV(X) == 0 exactly",
             ch["appetitive_off_zero_seeds"], n),
            ("plasticity off, aversive", "dV(X) == 0 exactly",
             ch["aversive_off_zero_seeds"], n),
            ("depends on the eligible experience, appetitive",
             "dV(X)[ON] - dV(X)[OTHER] > 0",
             ch["appetitive_specificity_seeds"], k),
            ("depends on the eligible experience, aversive",
             "dV(X)[ON] - dV(X)[OTHER] < 0",
             ch["aversive_specificity_seeds"], k)]:
        a(f"| {name} | {pred} | {got}/{n} | {need}/{n} | "
          f"{'PASS' if got >= need else '**FAIL**'} |")
    a("")
    a(f"**Verdict ({key}): {'PASS' if p['summary']['passed'] else 'FAIL'}.** "
      f"Stimulus specificity, mean over seeds: appetitive "
      f"{p['summary']['specificity_appetitive_mean']:+.3f} Hz, aversive "
      f"{p['summary']['specificity_aversive_mean']:+.3f} Hz.")
    return "\n".join(L)


def render(out: dict) -> str:
    q = out["spike_quantum_hz"]
    L = [f"Readout: {out['readout_sizes'][D.AVOID]} `avoid` + "
         f"{out['readout_sizes'][D.APPROACH]} `approach` neurons. One spike in "
         f"the 20 ms window is worth {q[D.AVOID]:.3f} Hz of `avoid` and "
         f"{q[D.APPROACH]:.3f} Hz of `approach`; that quantum is the whole "
         f"story of v1 below.", ""]
    L += ["### v1 — the protocol as pre-registered, and its failure", ""]
    L.append(render_protocol(out, "v1"))
    L += ["", "### v2 — declared deviation: contrast-selected contexts, "
              "measurement averaged over 8 presentations", ""]
    L.append(render_protocol(out, "v2"))
    L += ["", "### Reading it honestly", "",
          "* Phase 0.5's `UNPAIRED` control is **not** repeated and is not "
          "cited. It is zero by construction and the reviewer of that wave "
          "recorded that it is not on its own evidence of associative "
          "selectivity. The controls that carry weight are the two `_OFF` "
          "conditions (plasticity disabled, identical schedule and seeds) and "
          "the two `_OTHER` conditions (real weight change, driven by a "
          "different market context).",
          "* The `_OTHER` conditions do move X. Contexts share Kenyon cells, "
          "so a synapse depressed for one is depressed for the other. The "
          "specificity claim is that X moves *more* when X is the reinforced "
          "context, never that the other context leaves X untouched.",
          "* A changed weight and a changed counter are not the claim. The "
          "claim is that the same market context, presented to the same fixed "
          "decoder at the same measurement seeds, decodes differently after "
          "reinforcement than before."]
    return "\n".join(L)


if __name__ == "__main__":
    raise SystemExit(main())
