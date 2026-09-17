#!/usr/bin/env python
"""Silence, saturation and discrimination across the declared Pons input range.

    .venv/bin/python experiments/d10/probe.py

docs/SPEC.md D10 addendum 9, last paragraph, and amendment §8: *"Measure
silence, saturation and response discrimination across the declared Pons input
range without optimizing PnL."*

The clean reference brain, k = 8, `comparison_v1`, the same decoder the run
uses, presented with nominal feature vectors placed at declared points of the
input range rather than with observations that happen to sit there:

* the **2^8 = 256 corners** at ±1 on every axis;
* the **centre**, all zeros;
* **±0.5 on each axis alone**, sixteen patterns.

Reported: the response rate (a decoded status of VALID, against NO_RESPONSE),
the fraction of presentations that saturated an MBON, the silent replicates,
the Kenyon-cell recruitment, and the pairwise discrimination of the D7 kind —
the gap in the decoder's continuous centred valence — on a handful of declared
pairs.

**There is no PnL in this file, and no outcome, label or return is read.** It
measures what the encoder and the brain do with an input range; it does not
measure whether that is profitable, and it is not allowed to select anything.
"""

from __future__ import annotations

import argparse
import itertools
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

from flytrade import decoder as D          # noqa: E402
from flytrade import readout as RO         # noqa: E402
from flytrade import state as S            # noqa: E402

CONFIG = HERE / "config.json"

#: a readout is "saturated" when an MBON sits within 5 % of the refractory
#: ceiling. ``flytrade.decoder.SATURATED_HZ``, unchanged.
SATURATED_HZ = D.SATURATED_HZ

#: the declared pairs. Chosen for what they ask, not for what they answer:
#: the two extreme corners, a corner against the centre, and the two halves of
#: one axis against each other.
PAIRS = (
    ("corner_all_plus", "corner_all_minus"),
    ("corner_all_plus", "centre"),
    ("corner_all_minus", "centre"),
    ("axis_ret_30s_plus_half", "axis_ret_30s_minus_half"),
    ("axis_flow_imb_2m_plus_half", "axis_flow_imb_2m_minus_half"),
    ("axis_rv_2m_plus_half", "axis_rv_2m_minus_half"),
)


def patterns(features: tuple[str, ...]) -> dict[str, np.ndarray]:
    """The declared input-range grid. Nothing here is a market observation."""
    out: dict[str, np.ndarray] = {}
    n = len(features)
    for signs in itertools.product((1.0, -1.0), repeat=n):
        vector = np.array(signs, dtype=np.float64)
        if all(s > 0 for s in signs):
            name = "corner_all_plus"
        elif all(s < 0 for s in signs):
            name = "corner_all_minus"
        else:
            name = "corner_" + "".join("+" if s > 0 else "-" for s in signs)
        out[name] = vector
    out["centre"] = np.zeros(n, dtype=np.float64)
    for i, feature in enumerate(features):
        for sign, tag in ((0.5, "plus_half"), (-0.5, "minus_half")):
            vector = np.zeros(n, dtype=np.float64)
            vector[i] = sign
            out[f"axis_{feature}_{tag}"] = vector
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(CONFIG))
    parser.add_argument("--out", default=str(HERE / "probe.json"))
    args = parser.parse_args(argv)

    from run import build_brain  # noqa: PLC0415 - the run's own construction
    cfg = json.loads(Path(args.config).read_text())
    t0 = time.time()
    fb, mb, ann, encoder, pops, run, sha, clean = build_brain(cfg)
    features = tuple(encoder.features)
    policy = RO.policy_comparison()
    grid = patterns(features)
    print(f"{len(grid)} nominal patterns over {len(features)} features, "
          f"k = {policy.k}, clean reference digest {clean[:12]}")

    rows = {}
    for index, (name, vector) in enumerate(sorted(grid.items())):
        stim = encoder.olfactory.encode_features(
            vector, symbol=name, stable_id=index, bar_index=-1, cutoff_ts=0)
        batch = policy.measure(
            run, stim, episode_id=1_000_000 + index, state_dig=clean,
            obs_id=RO.features_id(vector, label=name))
        decision = policy.decode(batch)
        aggregate = batch.aggregate
        saturated = sum(1 for r in batch.replicates
                        if r.presentation.max_rate_hz >= SATURATED_HZ)
        rows[name] = {
            "vector": [float(x) for x in vector],
            "action": decision.action.value,
            "status": decision.status.value,
            "valence_hz": float(decision.valence_hz),
            "approach_hz": aggregate.mean(D.APPROACH),
            "avoid_hz": aggregate.mean(D.AVOID),
            "kc_fraction": float(aggregate.kc_fraction),
            "kc_active": int(aggregate.kc_active),
            "max_rate_hz": float(aggregate.max_rate_hz),
            "total_drive_hz": float(stim.total_drive_hz),
            "silent_replicates": int(aggregate.silent_replicates),
            "saturated_replicates": int(saturated),
            "k": int(batch.k),
        }
        if (index + 1) % 32 == 0:
            print(f"  {index + 1}/{len(grid)} patterns, "
                  f"{round(time.time() - t0, 1)}s", flush=True)

    presentations = len(rows) * policy.k
    responded = sum(1 for r in rows.values()
                    if r["status"] == D.ReadoutStatus.VALID.value)
    saturated = sum(r["saturated_replicates"] for r in rows.values())
    silent = sum(r["silent_replicates"] for r in rows.values())
    pairs = []
    for a, b in PAIRS:
        ra, rb = rows.get(a), rows.get(b)
        if ra is None or rb is None:
            continue
        pairs.append({
            "a": a, "b": b,
            "valence_a_hz": ra["valence_hz"], "valence_b_hz": rb["valence_hz"],
            "abs_delta_valence_hz": abs(ra["valence_hz"] - rb["valence_hz"]),
            "theta_hz": float(policy.decoder.theta_hz),
            "separated_by_more_than_theta":
                abs(ra["valence_hz"] - rb["valence_hz"]) > policy.decoder.theta_hz,
            "action_a": ra["action"], "action_b": rb["action"],
            "different_action": ra["action"] != rb["action"],
            "abs_delta_kc_fraction": abs(ra["kc_fraction"] - rb["kc_fraction"]),
        })

    by_action: dict[str, int] = {}
    for row in rows.values():
        by_action[row["action"]] = by_action.get(row["action"], 0) + 1
    report = {
        "version": "d10-probe-1",
        "what_this_is": ("silence, saturation and discrimination across the "
                         "declared Pons input range. No PnL, no outcome, no "
                         "label and no return is read anywhere in it."),
        "config": str(Path(args.config).name),
        "graph_sha256": sha,
        "clean_reference_digest": clean,
        "features": list(features),
        "scales": dict(encoder.scales),
        "k": policy.k,
        "readout": policy.as_dict(),
        "decoder": policy.decoder.as_dict(),
        "patterns": len(rows),
        "presentations": presentations,
        "response_rate": responded / len(rows),
        "responded": responded,
        "no_response": len(rows) - responded,
        "decoded_actions": by_action,
        "saturated_presentations": saturated,
        "saturated_fraction": saturated / presentations,
        "saturated_hz": float(SATURATED_HZ),
        "silent_replicates": silent,
        "silent_fraction": silent / presentations,
        "kc_fraction_min": min(r["kc_fraction"] for r in rows.values()),
        "kc_fraction_max": max(r["kc_fraction"] for r in rows.values()),
        "kc_fraction_ceiling": float(D.MAX_KC_FRACTION),
        "pairs": pairs,
        "rows": rows,
        "elapsed_s": round(time.time() - t0, 1),
        "python": platform.python_version(), "numpy": np.__version__,
    }
    Path(args.out).write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps({k: v for k, v in report.items()
                      if k not in ("rows", "readout", "decoder", "pairs")},
                     indent=1))
    for pair in pairs:
        print(f"  {pair['a']} vs {pair['b']}: "
              f"|dV| = {pair['abs_delta_valence_hz']:.3f} Hz "
              f"({pair['action_a']} vs {pair['action_b']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
