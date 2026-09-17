#!/usr/bin/env python
"""
Episode-specific credit assignment, demonstrated — canonical amendment §5.

    .venv/bin/python experiments/phase_one/credit_demo.py

The amendment's own scenario, run on the real connectome and reported with
numbers: **evaluate A, then B, select A, settle A.** Both halves of the claim
are measured, because a rejection counter on its own settles nothing:

* the correct trace is **accepted**, and the synapses that move are exactly
  A's own eligible synapses in the compartment the valence addressed;
* four different wrong offers are **refused**, each with its own counter, and
  none of them moves a weight.

The reinforcement here is delivered as an experimental variable. There is no
price, no position and no PnL in this file; §6 is where those appear.

Writes ``credit.json`` next to this file.
"""
from __future__ import annotations

import json
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

SYMBOLS = ("AAA", "BBB")
SERIES_SEEDS = (910, 911)
ROUND_INDEX = 11
ROUND_SEED = 555
CUTOFF = 300
VALENCE = -1            # aversive, so the addressed compartment is PPL1-side
AMOUNT = 1.0


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
    run = R.BrainRunner(fb, mb, enc, D.readout_populations(ann, mb.compartments))
    credit = R.CreditAssigner(mb)

    feed = MK.ObservationFeed({s: MK.synthetic_series(s, seed=SERIES_SEEDS[i])
                               for i, s in enumerate(SYMBOLS)})
    universe = MK.Universe(SYMBOLS)

    rnd = run.evaluate_round(
        [feed.observe(s, CUTOFF, stable_id=universe.stable_id(s))
         for s in SYMBOLS],
        round_index=ROUND_INDEX, round_seed=ROUND_SEED,
        score=lambda c: 1.0 if c.symbol == SYMBOLS[0] else 0.0,
        selection_rule="A is selected by construction, so the demonstration "
                       "controls which episode is open")
    a, b = rnd.by_symbol(SYMBOLS[0]), rnd.by_symbol(SYMBOLS[1])
    only_b = np.setdiff1d(b.trace.index, a.trace.index)
    shared = np.intersect1d(a.trace.index, b.trace.index)

    credit.open_episode(a.trace)
    baseline = mb.gain.copy()

    offers = []

    def offer(label, episode_id, trace):
        before = mb.gain.copy()
        ev = credit.settle(episode_id, VALENCE, AMOUNT, trace=trace)
        moved = int((mb.gain != before).sum())
        offers.append({"offer": label, "episode_id": episode_id,
                       "accepted": ev.accepted, "reason": ev.reason,
                       "synapses_depressed": ev.synapses_depressed,
                       "weights_moved": moved})
        return ev

    offer("B's trace, offered against A's episode", a.episode_id, b.trace)
    offer("B's own episode, never opened", b.episode_id, None)
    offer("A's trace, decayed below the eligibility threshold", a.episode_id,
          R.StoredTrace(a.episode_id, a.trace.index,
                        a.trace.value * (M.TRACE_EPS / 2.0),
                        a.trace.n_synapses))
    offer("A's trace, captured against a different synapse set", a.episode_id,
          R.StoredTrace(a.episode_id, a.trace.index, a.trace.value, 7))
    accepted = offer("A's own stored trace", a.episode_id, None)
    offer("A again, already settled", a.episode_id, a.trace)

    moved = np.flatnonzero(mb.gain != baseline)
    expected = a.trace.index[mb.side[a.trace.index] == VALENCE]
    out = {
        "graph_sha256": G.sha256_file(DATA / "graph.npz"),
        "runner_version": R.VERSION, "mushroom_version": M.VERSION,
        "decoder": dec.as_dict(),
        "round": {"index": ROUND_INDEX, "seed": ROUND_SEED, "cutoff": CUTOFF},
        "candidates": {
            c.symbol: {"stable_id": c.stable_id, "episode_id": c.episode_id,
                       "seed": c.seed, "eligible": c.trace.n_eligible,
                       "kc_active": c.presentation.kc_active,
                       "valence_hz": dec.decode(c.presentation).valence_hz,
                       "action": dec.decode(c.presentation).action.value}
            for c in rnd.candidates},
        "selected": rnd.selected.symbol,
        "trace_overlap": {"a_only": int(len(np.setdiff1d(a.trace.index,
                                                         b.trace.index))),
                          "b_only": int(len(only_b)),
                          "shared": int(len(shared))},
        "offers": offers,
        "accepted_event": accepted.as_dict(),
        "weights_moved": int(len(moved)),
        "moved_equals_a_eligible_on_addressed_side":
            bool(np.array_equal(np.sort(moved), np.sort(expected))),
        "moved_intersect_b_only": int(len(np.intersect1d(moved, only_b))),
        "moved_on_unaddressed_side": int((mb.side[moved] != VALENCE).sum()),
        "stats": credit.stats(),
        "elapsed_s": time.time() - t0,
    }
    (HERE / "credit.json").write_text(json.dumps(out, indent=2))
    print(render(out))
    print(f"\nwrote {HERE / 'credit.json'} in {out['elapsed_s']:.1f}s")
    return 0


def render(out: dict) -> str:
    L = []
    a = L.append
    c = out["candidates"]
    a("Round {index}, seed {seed}, both instruments observed at bar {cutoff}. "
      "A is selected by construction so the demonstration controls which "
      "episode is open.\n".format(**out["round"]))
    a("| candidate | stable id | episode id | Poisson seed | Kenyon cells "
      "active | eligible synapses | V Hz | decoded |")
    a("|---|--:|--:|--:|--:|--:|--:|---|")
    for sym, v in c.items():
        a(f"| `{sym}`{' **selected**' if sym == out['selected'] else ''} | "
          f"{v['stable_id']} | {v['episode_id']} | {v['seed']} | "
          f"{v['kc_active']} | {v['eligible']:,} | {v['valence_hz']:+.3f} | "
          f"{v['action']} |")
    t = out["trace_overlap"]
    a("")
    a(f"Eligible synapses: {t['a_only']:,} only A, {t['b_only']:,} only B, "
      f"{t['shared']:,} shared. The {t['b_only']:,} that are B's alone are "
      f"what makes the two traces distinguishable at all.\n")
    a("| offer | accepted | reason | synapses depressed | weights moved |")
    a("|---|:--|---|--:|--:|")
    for o in out["offers"]:
        a(f"| {o['offer']} | {'**yes**' if o['accepted'] else 'no'} | "
          f"{o['reason'] or '—'} | {o['synapses_depressed']:,} | "
          f"{o['weights_moved']:,} |")
    a("")
    a(f"The accepted event moved **{out['weights_moved']:,}** synapses. They "
      f"are exactly A's own eligible synapses in the addressed compartment: "
      f"set equality {out['moved_equals_a_eligible_on_addressed_side']}, "
      f"{out['moved_intersect_b_only']} of them eligible only under B, "
      f"{out['moved_on_unaddressed_side']} on the unaddressed side. "
      f"`eligibility_source` = "
      f"`{out['accepted_event']['eligibility_source']}`.\n")
    s = out["stats"]
    a(f"Counters: {s['accepted']} accepted, {s['rejections_total']} rejected — "
      + ", ".join(f"{k} {v}" for k, v in s["rejections"].items() if v)
      + f". Open episodes afterwards: {s['open'] or 'none'}.")
    return "\n".join(L)


if __name__ == "__main__":
    raise SystemExit(main())
