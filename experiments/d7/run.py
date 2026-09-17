#!/usr/bin/env python
"""
The D7 run — amendment §5 and §6, in two stages, IBM only.

    .venv/bin/python experiments/d7/run.py learn
    .venv/bin/python experiments/d7/run.py frozen [run_id]

Stage ``learn``  : WARMUP 2026-06-15..07-02 (features only, no brain) and
                   LEARNING 2026-07-06..07-17, the complete loop, from the
                   declared clean reference checkpoint. Writes
                   ``learning_summary.json``.
Stage ``frozen`` : FROZEN 2026-07-20..07-31, twice — TRAINED, from the final
                   LEARNING checkpoint of the named run, and REFERENCE, from
                   the clean checkpoint — with learning and forgetting off and
                   the paired ``comparison_v1`` seeds. Writes
                   ``frozen_summary.json``.

Two stages, not one, because the amendment's commit order puts the LEARNING
result on the record **before** any frozen evaluation exists. The hand-off
between them is the checkpoint file itself: stage ``frozen`` loads
``runs/<run>/learned/brain.npz``, validates it against the graph hash and the
plastic-synapse positions, and refuses to start unless its digest equals the
LEARNING end digest that stage ``learn`` recorded.

**Nothing in here chooses a number.** The dates, instrument, seeds, costs and
checkpoints come from `config.json`, committed alone before any D7 run
existed; the holding horizon comes from `registered-horizon-artifact`, the calibration
artifact committed alone before this file was ever executed. The decision loop
itself is `experiments/historical/run.py::run_branch` — the same loop
`hist-003` ran, called with this wave's run directory and horizon, so the two
experiments cannot drift apart.
"""
from __future__ import annotations

import hashlib
import json
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
sys.path.insert(0, str(ROOT / "experiments" / "historical"))

import run as HR                           # noqa: E402  the D5/D6 loop
from flytrade import decoder as D          # noqa: E402
from flytrade import historical as H       # noqa: E402
from flytrade import readout as RO         # noqa: E402
from flytrade import state as S            # noqa: E402

RUNS = HERE / "runs"
CONFIG = HERE / "config.json"
HORIZON = HERE / "registered-horizon-artifact"


def allocate_run_id() -> str:
    RUNS.mkdir(parents=True, exist_ok=True)
    n = 1
    while (RUNS / f"d7-{n:03d}").exists():
        n += 1
    return f"d7-{n:03d}"


def latest_run_id() -> str:
    ds = sorted(d.name for d in RUNS.iterdir() if d.is_dir())
    if not ds:
        raise SystemExit("no D7 run on disk; run the learn stage first")
    return ds[-1]


def load_horizon(cfg) -> int:
    """H*, from the artifact the calibration committed before any run."""
    if not HORIZON.exists():
        raise SystemExit(
            f"{HORIZON} is absent. The holding horizon is not a configuration "
            f"choice: it is the output of the WARMUP calibration, and the run "
            f"is refused until that artifact exists.")
    art = json.loads(HORIZON.read_text())
    if art.get("result") != "OK" or art.get("selected_horizon_minutes") is None:
        raise SystemExit(
            f"the calibration artifact says {art.get('result')!r}: there is no "
            f"H* and no LEARNING or FROZEN run may claim one")
    want = hashlib.sha256(CONFIG.read_bytes()).hexdigest()
    if art.get("config_sha256") != want:
        raise SystemExit("the calibration artifact was produced against a "
                         "different config.json; the run is refused")
    h = int(art["selected_horizon_minutes"])
    if h not in tuple(cfg["horizon_rule"]["H_SET"]):
        raise SystemExit(f"H* = {h} is not one of the candidate horizons")
    return h


def policy_for_factory(cfg):
    def policy_for(part):
        return (RO.policy_comparison() if part == "FROZEN" else RO.policy_k8())
    return policy_for


def common_setup(cfg, log):
    fb, mb, ann, enc, pops, run, sha, clean = HR.build_brain(cfg)
    series, reports = HR.load_market(cfg)
    log(f"graph {sha[:12]}, clean reference digest {clean[:12]}, "
        f"{len(mb.pos):,} plastic synapses, readout "
        f"{len(pops[D.AVOID])} avoid + {len(pops[D.APPROACH])} approach")
    base = RO.load_baseline(ROOT / cfg["readout"]["baseline_artifact"],
                            k=cfg["readout"]["k"], graph_sha256=sha)
    if base.theta_hz != RO.THETA_HZ_K8 or base.baseline_hz != RO.BASELINE_HZ_K8:
        raise SystemExit("the loaded baseline is not the stored artifact")
    log(f"baseline loaded exactly: BASELINE {base.baseline_hz!r}, "
        f"SD {base.sd_hz!r}, theta {base.theta_hz!r}")
    return fb, mb, ann, enc, pops, run, sha, clean, series, reports, base


def envelope(cfg, run_id, t_start, sha, clean, base, enc, reports, hstar):
    return {
        "run_id": run_id,
        "wave": "D7",
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t_start)),
        "python": platform.python_version(), "numpy": np.__version__,
        "machine": platform.processor() or platform.machine(),
        "config": cfg,
        "config_sha256": hashlib.sha256(CONFIG.read_bytes()).hexdigest(),
        "horizon_artifact_sha256": hashlib.sha256(
            HORIZON.read_bytes()).hexdigest(),
        "selected_horizon_minutes": hstar,
        "dataset_label": H.DATASET_LABEL,
        "vendor_reports": reports,
        "graph_sha256": sha,
        "clean_reference_digest": clean,
        "baseline": base.as_dict(),
        "encoder": enc.as_dict(),
        "decoder": RO.decoder_k8().as_dict(),
        "readout_learning": RO.policy_k8().as_dict(),
        "readout_frozen": RO.policy_comparison().as_dict(),
    }


# ------------------------------------------------------------ stage: learn

def stage_learn(cfg) -> int:
    t_start = time.time()
    run_id = allocate_run_id()
    (RUNS / run_id).mkdir(parents=True, exist_ok=True)
    logf = (RUNS / run_id / "learn.log").open("w")

    def log(*a, **kw):
        kw.pop("flush", None)
        print(*a, **kw)
        print(*a, file=logf)
        logf.flush()
        sys.stdout.flush()

    hstar = load_horizon(cfg)
    log(f"D7 run {run_id} stage=learn  H* = {hstar} market minutes")
    fb, mb, ann, enc, pops, run, sha, clean, series, reports, base = \
        common_setup(cfg, log)
    parts = H.partitions_from(cfg["partitions"])
    cov = {s: series[s].coverage(parts[0].first, parts[-1].last)
           for s in series}
    for s, c in cov.items():
        log(f"{s}: {c['n_days']} sessions, {c['bars']:,} bars, "
            f"{c['missing']:,} missing minutes in the window")

    clean_gain = np.ones(len(mb.pos), dtype=np.float32)
    learned, journal, accounts, credit = HR.run_branch(
        name="learned", cfg=cfg, series=series, parts=parts,
        partitions=["WARMUP", "LEARNING"], run=run, mb=mb, enc=enc, pops=pops,
        sha=sha, policy_for=policy_for_factory(cfg), run_id=run_id,
        learn_in={"LEARNING"}, start_gain=clean_gain, round_base=0,
        restart_after=HR.RESTART_AFTER_TRADES, log=log, runs_dir=RUNS,
        horizon_minutes=hstar)
    learned["clean_reference_digest"] = clean
    learned["learned_digest"] = S.learned_state_digest(mb.gain, mb.pos, sha)
    journal.save_checkpoint(
        last_settled_episode=journal.last_settled_episode)

    summary = envelope(cfg, run_id, t_start, sha, clean, base, enc, reports,
                       hstar)
    summary.update({
        "stage": "learn",
        "coverage": cov,
        "elapsed_s": round(time.time() - t_start, 1),
        "peak_rss_mib": round(
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1),
        "branches": {"learned": learned},
        "checkpoint": str(journal.checkpoint_path),
    })
    (HERE / "learning_summary.json").write_text(
        json.dumps(summary, indent=1, default=str))
    log(f"learn finished in {summary['elapsed_s'] / 60:.1f} min, peak RSS "
        f"{summary['peak_rss_mib']:.0f} MiB")
    log(f"LEARNING digest {clean[:12]} -> {learned['learned_digest'][:12]}, "
        f"trades {learned['execution']['trades']}, "
        f"net {learned['execution']['net_pnl']:+.2f}")
    logf.close()
    return 0


# ----------------------------------------------------------- stage: frozen

def stage_frozen(cfg, run_id: str | None) -> int:
    t_start = time.time()
    run_id = run_id or latest_run_id()
    logf = (RUNS / run_id / "frozen.log").open("w")

    def log(*a, **kw):
        kw.pop("flush", None)
        print(*a, **kw)
        print(*a, file=logf)
        logf.flush()
        sys.stdout.flush()

    hstar = load_horizon(cfg)
    log(f"D7 run {run_id} stage=frozen  H* = {hstar} market minutes")
    fb, mb, ann, enc, pops, run, sha, clean, series, reports, base = \
        common_setup(cfg, log)

    prev = json.loads((HERE / "learning_summary.json").read_text())
    if prev["run_id"] != run_id:
        raise SystemExit(f"learning_summary.json is for {prev['run_id']}, not "
                         f"{run_id}")
    ck_path = RUNS / run_id / "learned" / "brain.npz"
    ck = S.load_checkpoint(ck_path, graph_sha256=sha, expect_pos=mb.pos)
    trained_gain = np.asarray(ck["gain"], dtype=np.float32).copy()
    trained_digest = S.learned_state_digest(trained_gain, mb.pos, sha)
    want = prev["branches"]["learned"]["partitions"]["LEARNING"]["end_digest"]
    if trained_digest != want:
        raise SystemExit(f"the checkpoint digest {trained_digest[:12]} is not "
                         f"the LEARNING end digest {want[:12]}; refused")
    log(f"TRAINED checkpoint loaded from {ck_path}: digest "
        f"{trained_digest[:12]} == LEARNING end digest")

    parts = H.partitions_from(cfg["partitions"])
    clean_gain = np.ones(len(mb.pos), dtype=np.float32)
    out = {}
    for name, gain in (("frozen_trained", trained_gain),
                       ("frozen_reference", clean_gain)):
        b, _, _, _ = HR.run_branch(
            name=name, cfg=cfg, series=series, parts=parts,
            partitions=["FROZEN"], run=run, mb=mb, enc=enc, pops=pops,
            sha=sha, policy_for=policy_for_factory(cfg), run_id=run_id,
            learn_in=set(), start_gain=gain, round_base=0, log=log,
            runs_dir=RUNS, horizon_minutes=hstar)
        b["start_digest_expected"] = (trained_digest if name == "frozen_trained"
                                      else clean)
        out[name] = b

    summary = envelope(cfg, run_id, t_start, sha, clean, base, enc, reports,
                       hstar)
    summary.update({
        "stage": "frozen",
        "trained_checkpoint": str(ck_path),
        "trained_digest": trained_digest,
        "elapsed_s": round(time.time() - t_start, 1),
        "peak_rss_mib": round(
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1),
        "branches": out,
    })
    (HERE / "frozen_summary.json").write_text(
        json.dumps(summary, indent=1, default=str))
    for name, b in out.items():
        p = b["partitions"]["FROZEN"]
        log(f"{name}: digest {p['start_digest'][:12]} -> "
            f"{p['end_digest'][:12]} unchanged={p['digest_unchanged']} "
            f"trades {b['execution']['trades']} "
            f"net {b['execution']['net_pnl']:+.2f}")
    log(f"frozen finished in {summary['elapsed_s'] / 60:.1f} min")
    logf.close()
    return 0


def main(argv) -> int:
    cfg = json.loads(CONFIG.read_text())
    stage = argv[1] if len(argv) > 1 else ""
    if stage == "learn":
        return stage_learn(cfg)
    if stage == "frozen":
        return stage_frozen(cfg, argv[2] if len(argv) > 2 else None)
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
