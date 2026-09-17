#!/usr/bin/env python
"""
Measured cost of the k = 8 readout — D4 §7.

    .venv/bin/python experiments/k8_readout/benchmark.py

Six candidates per round, the demonstration's own fixture, k = 1 and k = 8 on
the same rounds and the same brain. What is measured, per arm:

* **round latency** — wall clock from the first candidate's first presentation
  to the selected decision being durable: median and p95 over the rounds;
* **neural evaluation time** — the simulator alone, summed over the round's
  presentations;
* **checkpoint and logging overhead** — the journal's share: the round event,
  the decision event, the atomic checkpoint;
* **peak memory** — the process high-water mark (``ru_maxrss``), reported as
  the absolute peak and as the increment over the brain-loaded baseline;
* **hardware and process configuration** — CPU, cores, RAM, Python, NumPy,
  thread environment.

Eight times the presentations is not eight times the latency and the numbers
say by how much. Nothing here changes the scientific model to meet a target and
no infrastructure is introduced: one process, one thread of control, the same
simulator call the loop makes.

Writes ``benchmark.json`` next to this file.
"""
from __future__ import annotations

import json
import os
import platform
import resource
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
from flytrade import records as REC      # noqa: E402
from flytrade import runner as R         # noqa: E402

DATA = ROOT / "data" / "malecns-v1.0"
STORE = HERE / "bench"

N_INSTRUMENTS = 6
SERIES_SEED0 = 700          # the §8 demonstration's own fixture
FIRST_BAR = 120
N_ROUNDS = 24
WARMUP = 2


def rss_mb() -> float:
    """Process high-water mark in MiB. Linux reports ru_maxrss in KiB."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return platform.processor() or "unknown"


def total_ram_gb() -> float:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal"):
                return int(line.split()[1]) / (1024.0 ** 2)
    except Exception:
        pass
    return float("nan")


def arm(run, mb, policy, dec, journal, feed, universe, symbols, label):
    """One arm: N_ROUNDS rounds of six candidates, fully journalled."""
    lat, neural, journal_s = [], [], []
    print(f"\n[{label}] k = {policy.k}", flush=True)
    for i in range(-WARMUP, N_ROUNDS):
        bar = FIRST_BAR + max(i, 0)
        obs = [feed.observe(s, bar, stable_id=universe.stable_id(s))
               for s in symbols]
        t0 = time.perf_counter()
        rnd = run.evaluate_round(obs, round_index=bar, readout=policy,
                                 score=policy.score)
        t_eval = time.perf_counter() - t0
        n_time = sum(c.batch.compute_s for c in rnd.candidates
                     if c.batch is not None)

        t1 = time.perf_counter()
        journal.record_round(rnd)
        chosen = rnd.selected
        if chosen is not None:
            d = dec.decode(chosen.presentation)
            rec = REC.decision_record(
                chosen, d, round_index=bar, bar_index=bar,
                versions=journal.versions,
                checkpoint_digest=journal.checkpoint_digest(),
                n_candidates=len(rnd.candidates),
                readout_policy=policy.as_dict())
            journal.record_decision(rec)
        journal.save_checkpoint(last_settled_episode=-1)
        t_journal = time.perf_counter() - t1

        if i < 0:
            continue
        lat.append(t_eval + t_journal)
        neural.append(n_time)
        journal_s.append(t_journal)

    lat, neural, journal_s = (np.array(x) for x in (lat, neural, journal_s))
    out = {
        "k": policy.k, "rounds": int(len(lat)),
        "candidates_per_round": len(symbols),
        "presentations_per_round": len(symbols) * policy.k,
        "round_latency_ms": {
            "median": float(np.median(lat) * 1e3),
            "p95": float(np.percentile(lat, 95) * 1e3),
            "min": float(lat.min() * 1e3), "max": float(lat.max() * 1e3),
            "mean": float(lat.mean() * 1e3)},
        "neural_ms": {"median": float(np.median(neural) * 1e3),
                      "p95": float(np.percentile(neural, 95) * 1e3),
                      "mean": float(neural.mean() * 1e3)},
        "journal_ms": {"median": float(np.median(journal_s) * 1e3),
                       "p95": float(np.percentile(journal_s, 95) * 1e3),
                       "mean": float(journal_s.mean() * 1e3)},
        "neural_share": float(neural.sum() / lat.sum()),
        "journal_share": float(journal_s.sum() / lat.sum()),
        "per_presentation_ms": float(
            neural.sum() / (len(lat) * len(symbols) * policy.k) * 1e3),
        "peak_rss_mb": rss_mb(),
    }
    print(f"  round latency median {out['round_latency_ms']['median']:.1f} ms, "
          f"p95 {out['round_latency_ms']['p95']:.1f} ms; neural "
          f"{out['neural_ms']['median']:.1f} ms; journal "
          f"{out['journal_ms']['median']:.1f} ms; peak RSS "
          f"{out['peak_rss_mb']:.0f} MiB", flush=True)
    return out


def main() -> int:
    t0 = time.time()
    import flysim

    if STORE.exists():
        for p in sorted(STORE.iterdir()):
            p.unlink()

    rss_start = rss_mb()
    fb = flysim.FlyBrain(graph_path=DATA / "graph.npz")
    mod = G.ModulatoryGraph(DATA / "graph_mod.npz", bodies=fb.bodies)
    ann = P.Annotations.load(DATA / "annotations.npz")
    sha = G.sha256_file(DATA / "graph.npz")
    mb = M.MushroomBody(fb, mod,
                        np.flatnonzero(P.kenyon_cells(ann)),
                        np.flatnonzero(P.mbons(ann)),
                        np.flatnonzero(P.pam(ann)),
                        np.flatnonzero(P.ppl1(ann)))
    enc = E.MarketToSensoryEncoder(ann)
    pops = D.readout_populations(ann, mb.compartments)
    run = R.BrainRunner(fb, mb, enc, pops, graph_sha256=sha)
    rss_loaded = rss_mb()

    symbols = tuple(f"SYN{i:02d}" for i in range(N_INSTRUMENTS))
    series = {s: MK.synthetic_series(s, seed=SERIES_SEED0 + i)
              for i, s in enumerate(symbols)}
    feed = MK.ObservationFeed(series)
    universe = MK.Universe(symbols)
    versions = REC.Versions(market=MK.VERSION, encoder=E.VERSION,
                            runner=R.VERSION, decoder=D.VERSION,
                            execution="flytrade-exec-1", mushroom=M.VERSION,
                            graph_sha256=sha)
    journal = REC.Journal(STORE, mb=mb, credit=R.CreditAssigner(mb),
                          versions=versions)

    k8 = RO.policy_k8(namespace=RO.BENCH_NAMESPACE)
    k1 = RO.ReadoutPolicy.k1(namespace=RO.BENCH_NAMESPACE,
                             decoder=RO.decoder_k8())
    one = arm(run, mb, k1, k1.decoder, journal, feed, universe, symbols,
              "k = 1")
    rss_after_k1 = rss_mb()
    eight = arm(run, mb, k8, k8.decoder, journal, feed, universe, symbols,
                "k = 8")

    out = {
        "fixture": {"instruments": len(symbols), "series_seed0": SERIES_SEED0,
                    "first_bar": FIRST_BAR, "rounds": N_ROUNDS,
                    "warmup_rounds": WARMUP,
                    "label": "SYNTHETIC (flytrade.market.synthetic_series)"},
        "k1": one, "k8": eight,
        "ratios": {
            "presentations": eight["presentations_per_round"]
            / one["presentations_per_round"],
            "median_round_latency": eight["round_latency_ms"]["median"]
            / one["round_latency_ms"]["median"],
            "p95_round_latency": eight["round_latency_ms"]["p95"]
            / one["round_latency_ms"]["p95"],
            "median_neural": eight["neural_ms"]["median"]
            / one["neural_ms"]["median"],
            "median_journal": eight["journal_ms"]["median"]
            / one["journal_ms"]["median"],
        },
        "memory_mb": {
            "at_start": rss_start, "after_brain_loaded": rss_loaded,
            "after_k1_arm": rss_after_k1, "peak": rss_mb(),
            "increment_over_loaded_brain": rss_mb() - rss_loaded,
            "note": "ru_maxrss high-water mark of the whole process; the "
                    "connectome dominates it and k does not move it",
        },
        "hardware": {
            "cpu": cpu_model(),
            "logical_cores": os.cpu_count(),
            "total_ram_gb": round(total_ram_gb(), 1),
            "platform": platform.platform(),
            "python": platform.python_version(), "numpy": np.__version__,
            "process": "one process, one thread of control, no parallelism "
                       "and no distributed infrastructure",
            "threads_env": {k: os.environ.get(k) for k in
                            ("OMP_NUM_THREADS", "MKL_NUM_THREADS",
                             "OPENBLAS_NUM_THREADS")},
        },
        "elapsed_s": time.time() - t0,
    }
    (HERE / "benchmark.json").write_text(json.dumps(out, indent=2))
    print("\n" + render(out))
    print(f"\nwrote {HERE / 'benchmark.json'} in {out['elapsed_s']:.1f}s")
    return 0


def render(out: dict) -> str:
    a, b, r, m = out["k1"], out["k8"], out["ratios"], out["memory_mb"]
    h = out["hardware"]
    L = []
    add = L.append
    add(f"{a['candidates_per_round']} candidates per round, "
        f"{a['rounds']} rounds per arm after {out['fixture']['warmup_rounds']} "
        f"warm-up rounds, same fixture and same brain.\n")
    add("| | k = 1 | k = 8 | ratio |")
    add("|---|--:|--:|--:|")
    add(f"| presentations per round | {a['presentations_per_round']} | "
        f"{b['presentations_per_round']} | {r['presentations']:.1f}× |")
    add(f"| round latency, median | {a['round_latency_ms']['median']:.1f} ms | "
        f"{b['round_latency_ms']['median']:.1f} ms | "
        f"{r['median_round_latency']:.2f}× |")
    add(f"| round latency, p95 | {a['round_latency_ms']['p95']:.1f} ms | "
        f"{b['round_latency_ms']['p95']:.1f} ms | "
        f"{r['p95_round_latency']:.2f}× |")
    add(f"| neural evaluation, median | {a['neural_ms']['median']:.1f} ms | "
        f"{b['neural_ms']['median']:.1f} ms | {r['median_neural']:.2f}× |")
    add(f"| checkpoint + logging, median | {a['journal_ms']['median']:.1f} ms | "
        f"{b['journal_ms']['median']:.1f} ms | {r['median_journal']:.2f}× |")
    add(f"| neural share of the round | {a['neural_share']:.1%} | "
        f"{b['neural_share']:.1%} | |")
    add(f"| per presentation | {a['per_presentation_ms']:.1f} ms | "
        f"{b['per_presentation_ms']:.1f} ms | |")
    add(f"| peak RSS | {a['peak_rss_mb']:.0f} MiB | {b['peak_rss_mb']:.0f} MiB "
        f"| |")
    add("")
    add(f"Peak process memory {m['peak']:.0f} MiB, of which "
        f"{m['after_brain_loaded']:.0f} MiB is the loaded connectome; the "
        f"k = 8 arm adds {m['increment_over_loaded_brain']:.0f} MiB over that "
        f"high-water mark. {m['note']}.")
    add("")
    add(f"Hardware: {h['cpu']}, {h['logical_cores']} logical cores, "
        f"{h['total_ram_gb']} GB RAM, {h['platform']}, Python "
        f"{h['python']}, NumPy {h['numpy']}. {h['process']}.")
    return "\n".join(L)


if __name__ == "__main__":
    raise SystemExit(main())
