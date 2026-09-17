#!/usr/bin/env python
"""
The independent integration check — D4 §5, as PROTOCOL.md §4 and §5 fix it.

    .venv/bin/python experiments/k8_readout/evaluate.py

Two questions, both pre-registered before this file existed.

**Stability.** Over six contexts — the conditioning v2 pair, labelled as what it
is (*selected after v1 failed on resolution*), plus four new nominal encoder
patterns that were never chosen for passing anything — 16 measurement batches
each, k = 8 against k = 1 on the *same* batches, because k = 1 is replicate 0 of
each. Within-context variability of the readout, decision agreement across
repeated batches, `NO_RESPONSE` and silent-replicate counts with their
denominators and their units, `WAIT` counted apart from both, `INVALID_STATE`
apart from both.

**Learning.** The §4 v2 appetitive and aversive checks re-run with the k = 8
mechanism, on the v2 pair *and* on one new pair. Each of the 20 training trials
is one batch of eight presentations settled by **one** normalised learning
event — the mean of the eight proposed deltas from the same pre-update state —
never eight sequential rewards.

Eight measurements of one context are not eight independent market predictions
and not eight independent learning episodes. No profitability is claimed,
sought or measured anywhere in this file.

One measurement-schedule clarification, stated rather than buried: the *before*
and *after* measurements of a learning cell use the **same eight seeds**, which
is §4 v2's design and the only way `dV` measures learning rather than seed
noise. The learned-state digest enters a replicate seed in the live loop, where
there is no before/after pair to hold fixed; here the measurement schedule is
keyed to the (pair, condition, seed) cell instead. The training batches use
their own per-trial schedule.

Writes ``evaluation.json`` next to this file.
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
from flytrade import readout as RO       # noqa: E402
from flytrade import runner as R         # noqa: E402

DATA = ROOT / "data" / "malecns-v1.0"

# ---- PROTOCOL.md §4.1: the six contexts, fixed before this file existed ----

#: the conditioning v2 pair, by the synthetic series and bar it came from
V2 = {"V2_X": ("CTX3", 903, 218), "V2_Y": ("CTX1", 901, 409)}

#: the four new nominal encoder patterns, by their feature vectors
NOMINAL = {
    "NOM_A": (-0.9, +0.9, 0.0, 0.0, 0.0),
    "NOM_B": (+0.9, 0.0, 0.0, +0.9, 0.0),
    "NOM_C": (0.0, 0.0, +0.9, 0.0, +0.9),
    "NOM_D": (+0.9, +0.9, -0.9, -0.9, +0.9),
}
CONTEXTS = ["V2_X", "V2_Y", "NOM_A", "NOM_B", "NOM_C", "NOM_D"]

#: PROTOCOL.md §4.1: the threshold the four new patterns were selected under
MAX_JACCARD = 0.368
#: PROTOCOL.md §4.2
N_BATCHES = 16
#: PROTOCOL.md §4.4
PAIRS = {"v2": ("V2_X", "V2_Y"), "nominal": ("NOM_B", "NOM_A")}
SEEDS = list(range(1, 9))
TRIALS = 20
CONDITIONS = ("APPETITIVE_ON", "APPETITIVE_OFF", "AVERSIVE_ON",
              "AVERSIVE_OFF", "APPETITIVE_OTHER", "AVERSIVE_OTHER")
BRANCH = {"APPETITIVE_ON": +1, "APPETITIVE_OFF": +1, "APPETITIVE_OTHER": +1,
          "AVERSIVE_ON": -1, "AVERSIVE_OFF": -1, "AVERSIVE_OTHER": -1}
#: PROTOCOL.md §5: C3 is 8/8, not 7/8 — the k = 8 checks are stricter
MIN_SEEDS = 8
JACCARD_SEEDS = [7001, 7002, 7003, 7004]


# --------------------------------------------------------------- helpers

def build():
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
    pops = D.readout_populations(ann, mb.compartments)
    sha = G.sha256_file(DATA / "graph.npz")
    run = R.BrainRunner(fb, mb, enc, pops, graph_sha256=sha)
    return fb, mb, ann, enc, pops, run, sha


def stimuli(enc):
    """The six contexts as encoder stimuli, with their context index as id."""
    out, u = {}, {}
    for i, name in enumerate(CONTEXTS):
        if name in V2:
            sym, seed, bar = V2[name]
            feed = MK.ObservationFeed({sym: MK.synthetic_series(sym, seed=seed)})
            obs = feed.observe(sym, bar, stable_id=i)
            u[name] = tuple(float(x) for x in obs.normalized)
            out[name] = enc.encode_features(obs.normalized, symbol=name,
                                            stable_id=i, bar_index=bar,
                                            cutoff_ts=obs.cutoff_ts)
        else:
            u[name] = NOMINAL[name]
            out[name] = enc.encode_features(NOMINAL[name], symbol=name,
                                            stable_id=i)
    return out, u


def kc_jaccard(fb, mb, stims, gains):
    sets = {}
    for name, st in stims.items():
        sets[name] = []
        for s in JACCARD_SEEDS:
            r = fb.run(st.drive, steps=E.STEPS, gains=gains,
                       record={"kc": mb.kc}, seed=s)
            sets[name].append(set(int(i) for i in mb.kc[r["kc"] > 0]))
    out = {}
    for i, a in enumerate(CONTEXTS):
        for b in CONTEXTS[i + 1:]:
            out[f"{a}|{b}"] = float(np.mean(
                [len(x & y) / len(x | y) if (x | y) else 0.0
                 for x, y in zip(sets[a], sets[b])]))
    return out


def batch(policy, run, stim, *, state_dig, obs_id, episode_id=-9999):
    return policy.measure(run, stim, episode_id=episode_id,
                          state_dig=state_dig, obs_id=obs_id)


# ------------------------------------------------------------- stability

def stability(run, policy, dec8, dec1, stims, u):
    """PROTOCOL.md §4.3, per context, k = 8 against k = 1 on the same batches."""
    rows = {}
    for name in CONTEXTS:
        st = stims[name]
        v8, v1, a8, a1, s8, s1 = [], [], [], [], [], []
        silent_reps = 0
        for b in range(N_BATCHES):
            obs_id = RO.features_id(u[name], label=f"{name}:batch-{b}")
            bt = batch(policy, run, st, state_dig="", obs_id=obs_id,
                       episode_id=-9000 - b)
            d8 = dec8.decode(bt.aggregate)
            d1 = dec1.decode(bt.replicates[0].presentation)
            v8.append(d8.valence_hz); v1.append(d1.valence_hz)
            a8.append(d8.action.value); a1.append(d1.action.value)
            s8.append(d8.status.value); s1.append(d1.status.value)
            silent_reps += bt.silent_replicates

        def arm(v, a, s, unit):
            v = np.asarray(v, dtype=np.float64)
            valid = np.array([x == "VALID" for x in s])
            mode = max(set(a), key=a.count)
            return {
                "sd_hz": float(v.std(ddof=1)),
                "sd_valid_hz": (float(v[valid].std(ddof=1))
                                if valid.sum() >= 2 else None),
                "mean_v_hz": float(v.mean()),
                "valid_batches": int(valid.sum()),
                "modal_decision": mode,
                "agreement": a.count(mode) / len(a),
                "actions": {x: a.count(x) for x in sorted(set(a))},
                "no_response": sum(1 for x in s if x == "NO_RESPONSE"),
                "invalid": sum(1 for x in s if x == "INVALID_STATE"),
                "wait": a.count("WAIT"),
                "denominator": len(a), "unit": unit,
                "v_hz": [float(x) for x in v],
            }

        rows[name] = {
            "u": list(u[name]),
            "k8": arm(v8, a8, s8, "candidate evaluation (batch)"),
            "k1": arm(v1, a1, s1, "presentation"),
            "silent_replicates": silent_reps,
            "silent_replicate_denominator": N_BATCHES * policy.k,
            "sd_ratio": (float(np.std(v8, ddof=1) / np.std(v1, ddof=1))
                         if np.std(v1, ddof=1) else None),
        }
        r = rows[name]
        print(f"  {name:6s} SD8 {r['k8']['sd_hz']:7.3f}  SD1 "
              f"{r['k1']['sd_hz']:7.3f}  ratio "
              f"{(r['sd_ratio'] if r['sd_ratio'] is not None else float('nan')):5.3f}"
              f"  agree8 {r['k8']['agreement']:.2f} ({r['k8']['modal_decision']})"
              f"  agree1 {r['k1']['agreement']:.2f} ({r['k1']['modal_decision']})"
              f"  NR8 {r['k8']['no_response']}/{N_BATCHES}"
              f"  NR1 {r['k1']['no_response']}/{N_BATCHES}"
              f"  silent {r['silent_replicates']}/{N_BATCHES * policy.k}",
              flush=True)
    return rows


# -------------------------------------------------------------- learning

def measure_cell(policy, run, dec8, stim, u, key, phase="m"):
    bt = batch(policy, run, stim, state_dig=key,
               obs_id=RO.features_id(u, label=f"{key}:{phase}"),
               episode_id=-9999)
    d = dec8.decode(bt.aggregate)
    return {"valence_hz": d.valence_hz, "approach_hz": d.approach_hz,
            "avoid_hz": d.avoid_hz, "action": d.action.value,
            "status": d.status.value,
            "kc_fraction": bt.aggregate.kc_fraction_mean,
            "silent_replicates": bt.silent_replicates,
            "per_replicate_action": [r.action for r in bt.replicates]}


def train_cell(policy, run, mb, stim, u, key, condition):
    valence = BRANCH[condition]
    plastic = not condition.endswith("_OFF")
    credit = R.CreditAssigner(mb)
    log = []
    for trial in range(TRIALS):
        ep = 10_000 + trial
        bt = batch(policy, run, stim, state_dig=f"{key}:train",
                   obs_id=RO.features_id(u, label=f"{key}:train-{trial}"),
                   episode_id=ep)
        moved = 0
        if plastic:
            credit.open_episode(bt.traces)
            ev = credit.settle(ep, valence, 1.0)
            moved = ev.synapses_depressed
            assert ev.normalisation == "mean_of_deltas" and ev.k == policy.k
            mb.forget()
            mb.apply()
        log.append({"trial": trial, "depressed": int(moved),
                    "eligible_union": bt.traces.n_eligible})
    return log, credit


def learning(run, mb, policy, dec8, stims, u, pair_name, x, y):
    print(f"\n[learning, k = {policy.k}] pair {pair_name}: X = {x}, Y = {y}",
          flush=True)
    runs = []
    for cond in CONDITIONS:
        for s in SEEDS:
            mb.gain[:] = 1.0
            mb.trace[:] = 0.0
            mb.trace_episode[:] = -1
            mb.events = {"reward": 0, "punish": 0, "rejected_episode": 0}
            mb.apply()
            key = f"{pair_name}:{cond}:seed-{s}"
            pre_x = measure_cell(policy, run, dec8, stims[x], u[x], key, "X")
            pre_y = measure_cell(policy, run, dec8, stims[y], u[y], key, "Y")
            trained = y if cond.endswith("_OTHER") else x
            log, credit = train_cell(policy, run, mb, stims[trained],
                                     u[trained], key, cond)
            post_x = measure_cell(policy, run, dec8, stims[x], u[x], key, "X")
            post_y = measure_cell(policy, run, dec8, stims[y], u[y], key, "Y")
            moved = mb.gain < 0.995
            runs.append({
                "condition": cond, "seed": s, "trained_on": trained,
                "pre_X": pre_x, "post_X": post_x, "pre_Y": pre_y,
                "post_Y": post_y,
                "dV_X": post_x["valence_hz"] - pre_x["valence_hz"],
                "dV_Y": post_y["valence_hz"] - pre_y["valence_hz"],
                "d_approach_X": post_x["approach_hz"] - pre_x["approach_hz"],
                "d_avoid_X": post_x["avoid_hz"] - pre_x["avoid_hz"],
                "action_changed_X": post_x["action"] != pre_x["action"],
                "learning_events": credit.accepted,
                "rejections": credit.stats()["rejections_total"],
                "weights": {
                    "synapses_moved": int(moved.sum()),
                    "moved_pam_side": int((moved & (mb.side == 1)).sum()),
                    "moved_ppl1_side": int((moved & (mb.side == -1)).sum()),
                    "min_gain": float(mb.gain.min())},
                "trials": log,
            })
            r = runs[-1]
            print(f"  {cond:18s} seed {s}  dV_X={r['dV_X']:+8.3f}  "
                  f"{pre_x['action']:>11s} -> {post_x['action']:<11s}  "
                  f"events={r['learning_events']}  "
                  f"moved={r['weights']['synapses_moved']:,}", flush=True)
    mb.gain[:] = 1.0
    mb.apply()

    by = {(r["condition"], r["seed"]): r for r in runs}

    def dv(c):
        return np.array([by[(c, s)]["dV_X"] for s in SEEDS])

    app, ave = dv("APPETITIVE_ON"), dv("AVERSIVE_ON")
    checks = {
        "appetitive_positive_seeds": int((app > 0).sum()),
        "aversive_negative_seeds": int((ave < 0).sum()),
        "appetitive_off_zero_seeds": int((dv("APPETITIVE_OFF") == 0.0).sum()),
        "aversive_off_zero_seeds": int((dv("AVERSIVE_OFF") == 0.0).sum()),
        "appetitive_specificity_seeds": int(
            ((app - dv("APPETITIVE_OTHER")) > 0).sum()),
        "aversive_specificity_seeds": int(
            ((ave - dv("AVERSIVE_OTHER")) < 0).sum()),
    }
    n = len(SEEDS)
    return {
        "pair": pair_name, "X": x, "Y": y, "k": policy.k, "trials": TRIALS,
        "runs": runs,
        "summary": {
            "dV_X_mean": {c: float(dv(c).mean()) for c in CONDITIONS},
            "dV_X_per_seed": {c: [float(v) for v in dv(c)] for c in CONDITIONS},
            "dV_Y_mean": {c: float(np.mean([by[(c, s)]["dV_Y"]
                                            for s in SEEDS]))
                          for c in CONDITIONS},
            "d_approach_X_mean": {c: float(np.mean([by[(c, s)]["d_approach_X"]
                                                    for s in SEEDS]))
                                  for c in CONDITIONS},
            "d_avoid_X_mean": {c: float(np.mean([by[(c, s)]["d_avoid_X"]
                                                 for s in SEEDS]))
                               for c in CONDITIONS},
            "actions_changed": {c: int(sum(by[(c, s)]["action_changed_X"]
                                           for s in SEEDS))
                                for c in CONDITIONS},
            "learning_events_per_cell": sorted(
                set(r["learning_events"] for r in runs)),
            "specificity_appetitive_mean": float(
                (app - dv("APPETITIVE_OTHER")).mean()),
            "specificity_aversive_mean": float(
                (ave - dv("AVERSIVE_OTHER")).mean()),
            "checks": checks, "n_seeds": n, "min_seeds": MIN_SEEDS,
        },
    }


# ------------------------------------------------------------------ main

def main() -> int:
    t0 = time.time()
    fb, mb, ann, enc, pops, run, sha = build()
    gains = run.gains
    base = RO.load_baseline(HERE / "baseline_k8.json", k=RO.K, graph_sha256=sha)
    policy = RO.policy_k8(namespace=RO.EVAL_NAMESPACE)
    dec8, dec1 = policy.decoder, policy.decoder_k1
    stims, u = stimuli(enc)

    mb.gain[:] = 1.0
    mb.apply()
    print(f"k = {policy.k}, theta_8 = {dec8.theta_hz:.4f} Hz, "
          f"theta_1 = {dec1.theta_hz:.4f} Hz; {len(CONTEXTS)} contexts, "
          f"{N_BATCHES} batches each", flush=True)

    jac = kc_jaccard(fb, mb, stims, gains)
    new_pairs = {k: v for k, v in jac.items()
                 if all(n.startswith("NOM") for n in k.split("|"))}
    print(f"\nKenyon-cell Jaccard among the four new patterns: max "
          f"{max(new_pairs.values()):.3f} (threshold {MAX_JACCARD})",
          flush=True)

    print("\n[stability]", flush=True)
    stab = stability(run, policy, dec8, dec1, stims, u)

    learn = {name: learning(run, mb, policy, dec8, stims, u, name, x, y)
             for name, (x, y) in PAIRS.items()}

    # ---- PROTOCOL.md §5, the pre-registered pass/fail -------------------
    c1 = [n for n in CONTEXTS
          if stab[n]["k8"]["sd_hz"] < stab[n]["k1"]["sd_hz"]]
    c2 = [n for n in CONTEXTS
          if stab[n]["k8"]["agreement"] >= stab[n]["k1"]["agreement"]]
    ch = {n: learn[n]["summary"]["checks"] for n in learn}
    criteria = {
        "C1_sd_smaller_at_k8": {
            "contexts": c1, "n": len(c1), "threshold": 5, "of": 6,
            "passed": len(c1) >= 5},
        "C2_agreement_not_worse_at_k8": {
            "contexts": c2, "n": len(c2), "threshold": 5, "of": 6,
            "passed": len(c2) >= 5},
        "C3a_appetitive_sign": {
            "per_pair": {n: ch[n]["appetitive_positive_seeds"] for n in ch},
            "threshold": MIN_SEEDS, "of": len(SEEDS),
            "passed": all(v["appetitive_positive_seeds"] >= MIN_SEEDS
                          for v in ch.values())},
        "C3b_aversive_sign": {
            "per_pair": {n: ch[n]["aversive_negative_seeds"] for n in ch},
            "threshold": MIN_SEEDS, "of": len(SEEDS),
            "passed": all(v["aversive_negative_seeds"] >= MIN_SEEDS
                          for v in ch.values())},
        "C3c_plasticity_off_exactly_zero": {
            "per_pair": {n: [ch[n]["appetitive_off_zero_seeds"],
                             ch[n]["aversive_off_zero_seeds"]] for n in ch},
            "threshold": len(SEEDS), "of": len(SEEDS),
            "passed": all(v["appetitive_off_zero_seeds"] == len(SEEDS)
                          and v["aversive_off_zero_seeds"] == len(SEEDS)
                          for v in ch.values())},
        "C4_theta8_non_degenerate": {
            "sd_hz": base.sd_hz, "passed": base.sd_hz > 0.0},
    }
    out = {
        "protocol": "experiments/k8_readout/PROTOCOL.md",
        "protocol_commit": base.commit,
        "baseline": base.as_dict(),
        "decoder_k8": dec8.as_dict(), "decoder_k1": dec1.as_dict(),
        "readout": policy.as_dict(), "encoder": enc.as_dict(),
        "graph_sha256": sha, "contexts": CONTEXTS,
        "context_u": {k: list(v) for k, v in u.items()},
        "kc_jaccard": jac, "kc_jaccard_new_max": max(new_pairs.values()),
        "kc_jaccard_threshold": MAX_JACCARD,
        "jaccard_seeds": JACCARD_SEEDS,
        "n_batches": N_BATCHES, "stability": stab, "learning": learn,
        "criteria": criteria,
        "all_passed": all(v["passed"] for v in criteria.values()),
        "presentations": run.presentations,
        "python": platform.python_version(), "numpy": np.__version__,
        "elapsed_s": time.time() - t0,
    }
    (HERE / "evaluation.json").write_text(json.dumps(out, indent=2))
    print("\n" + "\n".join(
        f"{k}: {'PASS' if v['passed'] else 'FAIL'}"
        for k, v in criteria.items()))
    print(f"\nwrote {HERE / 'evaluation.json'} in {out['elapsed_s']:.1f}s "
          f"({out['presentations']:,} presentations)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
