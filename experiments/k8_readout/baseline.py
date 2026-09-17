#!/usr/bin/env python
"""
The k = 8 baseline and WAIT margin — D4 §3, exactly as PROTOCOL.md §3 fixes it.

    .venv/bin/python experiments/k8_readout/baseline.py

The decoder states its WAIT margin in units of the measured dispersion of its
own baseline readout. Phase One measured that dispersion for a single 20 ms
presentation; a readout that averages eight has a different one, so it is
re-measured here under the same rule. The formula, the sign convention and the
dimensionless coefficient 1.0 are untouched — two constants change and nothing
else.

Everything about this measurement was fixed before it ran: reference brain
state, stimulus, seed schedule, N, the distribution normalised, and what
happens if that distribution turns out to be degenerate. No label, no PnL, no
realised outcome and no desired action rate participates.

Writes ``baseline_k8.json`` next to this file.
"""
from __future__ import annotations

import json
import platform
import subprocess
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

#: PROTOCOL.md §3: the neutral reference, every feature at its own trailing
#: median. The same stimulus ``docs/DECODER.md`` §1 measured the k = 1
#: constants at.
NEUTRAL = (0.0, 0.0, 0.0, 0.0, 0.0)
STIMULUS = "neutral_reference"

#: PROTOCOL.md §3: N = 64 batches
N_BATCHES = 64


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT),
                              capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:
        return ""


def batch_obs_id(b: int) -> str:
    return RO.features_id(NEUTRAL, label=f"{STIMULUS}:batch-{b}")


def main() -> int:
    t0 = time.time()
    import flysim

    fb = flysim.FlyBrain(graph_path=DATA / "graph.npz")
    mod = G.ModulatoryGraph(DATA / "graph_mod.npz", bodies=fb.bodies)
    ann = P.Annotations.load(DATA / "annotations.npz")
    graph_sha = G.sha256_file(DATA / "graph.npz")
    mb = M.MushroomBody(fb, mod,
                        np.flatnonzero(P.kenyon_cells(ann)),
                        np.flatnonzero(P.mbons(ann)),
                        np.flatnonzero(P.pam(ann)),
                        np.flatnonzero(P.ppl1(ann)))
    # the declared reference brain state: unlearned weights, gain 0.10
    mb.gain[:] = 1.0
    mb.trace[:] = 0.0
    mb.trace_episode[:] = -1
    mb.apply()

    enc = E.MarketToSensoryEncoder(ann)
    pops = D.readout_populations(ann, mb.compartments)
    run = R.BrainRunner(fb, mb, enc, pops, graph_sha256=graph_sha)
    dig = run.state_digest()
    policy = RO.ReadoutPolicy(k=RO.K, namespace=RO.BASELINE_NAMESPACE)
    stim = enc.encode_features(NEUTRAL, symbol=STIMULUS, stable_id=0)

    print(f"k = {policy.k}, N = {N_BATCHES} batches at the neutral reference; "
          f"readout {len(pops[D.AVOID])} avoid + {len(pops[D.APPROACH])} "
          f"approach; state digest {dig[:12]}")

    v8, v1, seeds_all = [], [], []
    silent_reps = silent_batches = invalid_batches = 0
    kc = []
    for b in range(N_BATCHES):
        batch = policy.measure(run, stim, episode_id=-1000 - b,
                               state_dig=dig, obs_id=batch_obs_id(b))
        agg = batch.aggregate
        v8.append(agg.mean(D.APPROACH) - agg.mean(D.AVOID))
        r0 = batch.replicates[0].presentation
        v1.append(r0.mean(D.APPROACH) - r0.mean(D.AVOID))
        seeds_all += [r.seed for r in batch.replicates]
        silent_reps += batch.silent_replicates
        kc.append(agg.kc_fraction_mean)
        d8 = policy.decoder_k1.decode(agg)      # status only; theta is not set yet
        if d8.status is D.ReadoutStatus.NO_RESPONSE:
            silent_batches += 1
        if d8.status is D.ReadoutStatus.INVALID_STATE:
            invalid_batches += 1

    # the disjointness claim of PROTOCOL.md §3, asserted rather than asserted-to
    below = sum(1 for s in seeds_all if s < 2 ** 32)
    assert len(set(seeds_all)) == len(seeds_all), "the schedule repeated a seed"

    base = RO.Baseline.from_samples(
        v8, k=RO.K, namespace=RO.BASELINE_NAMESPACE, stimulus=STIMULUS,
        graph_sha256=graph_sha, state_digest=dig, commit=git_commit(),
        measured_at=time.time())
    base.save(HERE / "baseline_k8.json")

    a8, s8 = base.baseline_hz, base.sd_hz
    a1 = float(np.mean(v1))
    s1 = float(np.std(v1, ddof=1))
    ratio = s8 / s1 if s1 else float("nan")

    out = {
        "protocol": "experiments/k8_readout/PROTOCOL.md §3",
        "baseline": base.as_dict(),
        "k1_arm_same_schedule": {
            "mean_hz": a1, "sd_hz": s1, "n": len(v1),
            "samples": [float(x) for x in v1],
            "note": "replicate 0 of each of the same 64 batches; paired with "
                    "the k = 8 arm by construction",
        },
        "k1_phase_one_constants": {
            "baseline_hz": D.BASELINE_HZ, "sd_hz": D.BASELINE_SD_HZ,
            "theta_hz": D.THETA_HZ, "n": 8,
            "source": "experiments/phase_one/encoder_range.json, "
                      "neutral_reference.attributed_diff_hz_*",
        },
        "sd_ratio_k8_over_k1_same_schedule": ratio,
        "sd_ratio_k8_over_phase_one_k1": s8 / D.BASELINE_SD_HZ,
        "expected_sd_ratio": 1.0 / np.sqrt(RO.K),
        "counts": {
            "batches": N_BATCHES, "presentations": N_BATCHES * RO.K,
            "silent_replicates": silent_reps,
            "silent_replicates_denominator": N_BATCHES * RO.K,
            "silent_replicate_unit": "presentation",
            "no_response_batches": silent_batches,
            "no_response_denominator": N_BATCHES,
            "no_response_unit": "candidate evaluation (batch)",
            "invalid_batches": invalid_batches,
            "mean_kc_fraction": float(np.mean(kc)),
        },
        "seed_disjointness": {
            "namespace": RO.BASELINE_NAMESPACE,
            "distinct_seeds": len(set(seeds_all)),
            "seeds_below_2_32": below,
            "claim": "every Phase One schedule drew integers below 2**32; "
                     "these are 64-bit digests under their own namespace",
        },
        "python": platform.python_version(), "numpy": np.__version__,
        "encoder": enc.as_dict(), "readout": policy.as_dict(),
        "elapsed_s": time.time() - t0,
    }
    (HERE / "baseline_run.json").write_text(json.dumps(out, indent=2))
    print(render(out))
    print(f"\nwrote {HERE / 'baseline_k8.json'} and baseline_run.json "
          f"in {out['elapsed_s']:.1f}s")
    return 0


def render(out: dict) -> str:
    b, c = out["baseline"], out["counts"]
    k1, p1 = out["k1_arm_same_schedule"], out["k1_phase_one_constants"]
    L = []
    a = L.append
    a(f"N = {b['n_batches']} batches of k = {b['k']} at the "
      f"`{b['stimulus']}`, {c['presentations']} presentations, unlearned "
      f"weights, gain 0.10, 20 ms window.\n")
    a("| estimator | baseline offset Hz | dispersion Hz | θ = 1.0 × SD | N |")
    a("|---|--:|--:|--:|--:|")
    a(f"| k = 1, Phase One (`docs/DECODER.md`) | {p1['baseline_hz']:.4f} | "
      f"{p1['sd_hz']:.4f} | {p1['theta_hz']:.4f} | {p1['n']} seeds |")
    a(f"| k = 1, replicate 0 of this schedule | {k1['mean_hz']:.4f} | "
      f"{k1['sd_hz']:.4f} | {k1['sd_hz']:.4f} | {k1['n']} |")
    a(f"| **k = 8, aggregate** | **{b['baseline_hz']:.4f}** | "
      f"**{b['sd_hz']:.4f}** | **{b['theta_hz']:.4f}** | "
      f"{b['n_batches']} batches |")
    a("")
    a(f"SD ratio k = 8 / k = 1 on the same schedule: "
      f"**{out['sd_ratio_k8_over_k1_same_schedule']:.3f}** "
      f"(against the Phase One k = 1 SD: "
      f"{out['sd_ratio_k8_over_phase_one_k1']:.3f}); the independent-replicate "
      f"expectation is 1/√8 = {out['expected_sd_ratio']:.3f}.")
    a("")
    a(f"Silent replicates {c['silent_replicates']}/"
      f"{c['silent_replicates_denominator']} (unit: presentation). "
      f"`NO_RESPONSE` batches {c['no_response_batches']}/"
      f"{c['no_response_denominator']} (unit: candidate evaluation). "
      f"`INVALID_STATE` batches {c['invalid_batches']}/"
      f"{c['no_response_denominator']}. Mean Kenyon active fraction "
      f"{c['mean_kc_fraction']:.4f}.")
    a("")
    s = out["seed_disjointness"]
    a(f"Seed schedule `{s['namespace']}`: {s['distinct_seeds']} distinct "
      f"seeds, {s['seeds_below_2_32']} of them below 2³² — {s['claim']}.")
    a("")
    a("The distribution normalised: " + b["distribution"] + ".")
    return "\n".join(L)


if __name__ == "__main__":
    raise SystemExit(main())
