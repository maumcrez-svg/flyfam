#!/usr/bin/env python
"""
D8 stage 1 — the two grids, and stored versus reconstructed.

    .venv/bin/python experiments/d8/grids.py

Read-only. It writes one small artifact, `experiments/d8/grids.json`: the
registered artifact hashes as found now, both grids' sizes, class counts and
exclusions, the descriptive tables of §4, the temporal-order check of §3, and
the stored-versus-reconstructed comparison of §5.

**A non-zero mismatch count stops the wave here**, before any model is fitted:
the script exits non-zero and `grids.json` records the count. That is the rule
`PLAN.md` §5 fixed before the numbers existed.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import data as D                                     # noqa: E402


def main() -> int:
    t0 = time.time()
    found = D.check_artifacts()
    ser = D.series()
    enc = D.encoder()

    fit = D.fitting_rows(ser)
    ev = D.evaluation_rows()

    ver_fit = D.verify(fit, ser, enc)
    ver_ev = D.verify(ev, ser, enc)
    order = D.temporal_order(fit, ev)

    out = {
        "artifact": "flytrade-d8-grids-1",
        "label": D.CONFIG["label"],
        "written_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sklearn_pin": D.CONFIG["dependency"]["pin"],
        "artifact_hashes_found": found,
        "artifact_hashes_match_registration": True,
        "encoder": {"version": enc.version, "features": list(D.FEATURES),
                    "glomeruli": list(D.GLOMERULI),
                    "orn_count": enc.orn_count, "n_orns": enc.n_orns,
                    "sequence": "none: one constant rate vector per "
                                "presentation, so the amendment's ordered-"
                                "sequence clause is vacuous",
                    "rows_per_minute": 1},
        "fitting": {**D.describe(fit), "meta": fit.meta},
        "evaluation": {**D.describe(ev), "meta": {
            k: v for k, v in ev.meta.items() if k != "probe_scores"}},
        "temporal_order": order,
        "verification": {"fitting": ver_fit, "evaluation": ver_ev},
        "mismatches_total": ver_fit["mismatches_total"] + ver_ev["mismatches_total"],
        "elapsed_s": round(time.time() - t0, 2),
    }
    (HERE / "grids.json").write_text(json.dumps(out, indent=1))

    print(f"fitting    n={len(fit):5d}  sessions={out['fitting']['n_sessions']}"
          f"  Y=1 {out['fitting']['class_counts']['Y=1']}"
          f"  Y=0 {out['fitting']['class_counts']['Y=0']}"
          f"  grid {fit.meta['grid_points']}  exclusions {fit.meta['exclusions']}")
    print(f"evaluation n={len(ev):5d}  sessions={out['evaluation']['n_sessions']}"
          f"  Y=1 {out['evaluation']['class_counts']['Y=1']}"
          f"  Y=0 {out['evaluation']['class_counts']['Y=0']}"
          f"  probes {ev.meta['probes_n']}  exclusions {ev.meta['exclusions']}")
    print(f"frozen_trained stimulus identical on shared rows: "
          f"{ev.meta['frozen_trained_identical']}")
    print(f"temporal order: max fitting exit {order['max_fitting_exit_utc']} < "
          f"min evaluation cutoff {order['min_evaluation_market_utc']} = "
          f"{order['strictly_before']}")
    for name, v in (("fitting", ver_fit), ("evaluation", ver_ev)):
        print(f"reconstruction {name}: X_FEATURES max |d| "
              f"{v['X_FEATURES_max_abs_diff']:.3e} ({v['X_FEATURES_mismatches']} "
              f"mismatches)  X_SENSORY max |d| after stored rounding "
              f"{v['X_SENSORY_max_abs_diff_after_stored_rounding']:.3e} "
              f"({v['X_SENSORY_mismatches']} mismatches); unrounded "
              f"{v['X_SENSORY_max_abs_diff_unrounded']:.3e}; "
              f"market_ts == bar_end on {v['market_ts_equals_bar_end']}/{v['n']}")
    if out["mismatches_total"]:
        print(f"STOP: {out['mismatches_total']} row(s) disagree with the "
              f"reconstruction. No model is fitted.")
        return 2
    if not order["strictly_before"]:
        print("STOP: a fitting label resolves at or after evaluation begins.")
        return 3
    print(f"ok in {out['elapsed_s']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
