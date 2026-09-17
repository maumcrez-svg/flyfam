#!/usr/bin/env python
"""
The D9(b) run — the target-aligned fixed-hold experiment, in two stages.

    .venv/bin/python experiments/d9b/run.py learn
    .venv/bin/python experiments/d9b/run.py frozen [run_id]

Stage ``learn``  : WARMUP 2026-06-15..07-02 (features only, no brain) and
                   LEARNING 2026-07-06..07-17, the complete loop **under the
                   fixed-hold exit policy**, from the declared clean reference
                   checkpoint. Writes ``learning_summary.json``.
Stage ``frozen`` : FROZEN 2026-07-20..07-31, twice — TRAINED, from the final
                   LEARNING checkpoint of the named run, and REFERENCE, from
                   the clean checkpoint — with learning and forgetting off and
                   the paired ``comparison_v1`` seeds. Writes
                   ``frozen_summary.json``.

**Nothing in here chooses a number.** The dates, instrument, seeds, costs,
checkpoints, the exit policy and H = 90 come from `config.json`, committed
alone before any D9(b) run existed; H itself comes from
`the registered horizon artifact`, the calibration artifact D7 committed before
either wave ran, and is not recalibrated here. The decision loop is
`experiments/historical/run.py::run_branch` — the same loop D5/D6/D7 ran,
called with `exit_policy="fixed_hold"` — so the two experiments differ in the
exit rule and in nothing else.

This is a **RETROSPECTIVE COMPARISON ON PREVIOUSLY EXAMINED DATES**. D7 and D8
already looked at every session below.
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

import run as HR                           # noqa: E402  the shared loop
from flytrade import decoder as D          # noqa: E402
from flytrade import historical as H       # noqa: E402
from flytrade import readout as RO         # noqa: E402
from flytrade import state as S            # noqa: E402

RUNS = HERE / "runs"
CONFIG = HERE / "config.json"
#: the calibration artifact is D7's, by the amendment's §1. It is read, hashed
#: and never written; H is not a configuration choice of this wave.
D7 = ROOT / "experiments" / "d7"
HORIZON = D7 / "registered-horizon-artifact"
D7_CONFIG = D7 / "config.json"


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def allocate_run_id() -> str:
    RUNS.mkdir(parents=True, exist_ok=True)
    n = 1
    while (RUNS / f"d9b-{n:03d}").exists():
        n += 1
    return f"d9b-{n:03d}"


def latest_run_id() -> str:
    ds = sorted(d.name for d in RUNS.iterdir() if d.is_dir())
    if not ds:
        raise SystemExit("no D9(b) run on disk; run the learn stage first")
    return ds[-1]


def check_artifacts(cfg) -> dict:
    """Every reused artifact, hashed against what the plan registered."""
    got = {}
    for rel, want in cfg["reused_artifacts_sha256"].items():
        path = ROOT / rel
        if not path.exists():
            raise SystemExit(f"{rel} is absent; the run is refused")
        got[rel] = sha256_file(path)
        if rel == "experiments/historical/run.py":
            continue          # amended by this wave's commit (2), as declared
        if got[rel] != want:
            raise SystemExit(
                f"{rel}: sha256 {got[rel][:16]} != the registered "
                f"{want[:16]}. The file on disk is not the file the plan was "
                f"registered against; the run is refused.")
    return got


def load_horizon(cfg) -> int:
    """H, from D7's calibration artifact. Not a choice of this wave."""
    art = json.loads(HORIZON.read_text())
    if art.get("result") != "OK" or art.get("selected_horizon_minutes") is None:
        raise SystemExit(f"the calibration artifact says {art.get('result')!r}")
    want = hashlib.sha256(D7_CONFIG.read_bytes()).hexdigest()
    if art.get("config_sha256") != want:
        raise SystemExit("the calibration artifact was produced against a "
                         "different D7 config.json; the run is refused")
    if want != cfg["horizon"]["artifact_config_sha256"]:
        raise SystemExit("the D7 config.json is not the one this plan "
                         "registered; the run is refused")
    h = int(art["selected_horizon_minutes"])
    if h != int(cfg["horizon"]["H"]) or h != int(cfg["execution"]["horizon_minutes"]):
        raise SystemExit(f"H* = {h} is not the H the plan registered")
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


def full_precision(accounts) -> list[dict]:
    """Every realised outcome at full float precision.

    ``OutcomeRecord.as_dict`` rounds ``net_pnl`` to 8 decimals for the event
    log, which is the right thing for a log and the wrong thing for the §3
    invariant: half of the last recorded digit is 5e-9, five times the
    tolerance the plan registered. These records carry the unrounded values,
    so the invariant is checked against what the policy actually booked.
    """
    out = []
    for part, acc in accounts.items():
        for o in acc.outcomes:
            out.append({
                "partition": part,
                "episode_id": int(o.episode_id), "symbol": o.symbol,
                "close_reason": o.close_reason.value,
                "entry_minute": int(o.entry.bar_index),
                "exit_minute": int(o.exit.bar_index),
                "entry_ts": int(o.entry.ts), "exit_ts": int(o.exit.ts),
                "entry_reference_price": float(o.entry.reference_price),
                "exit_reference_price": float(o.exit.reference_price),
                "entry_fill_price": float(o.entry.fill_price),
                "exit_fill_price": float(o.exit.fill_price),
                "entry_flag": o.entry.flag, "exit_flag": o.exit.flag,
                "quantity": float(o.entry.quantity),
                "market_minutes_held": int(o.market_minutes_held),
                "gross_pnl": float(o.gross_pnl),
                "gross_reference_pnl": float(o.gross_reference_pnl),
                "fees": float(o.fees), "slippage": float(o.slippage),
                "net_pnl": float(o.net_pnl),
                "return_on_notional": float(o.return_on_notional),
                "notional": float(o.notional)})
    return out


def envelope(cfg, run_id, t_start, sha, clean, base, enc, reports, hstar,
             hashes):
    return {
        "run_id": run_id,
        "wave": "D9(b)",
        "label": cfg["label"],
        "exit_policy": cfg["exit_policy"],
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t_start)),
        "python": platform.python_version(), "numpy": np.__version__,
        "machine": platform.processor() or platform.machine(),
        "config": cfg,
        "config_sha256": sha256_file(CONFIG),
        "reused_artifacts_sha256_at_run_time": hashes,
        "horizon_artifact": "the registered horizon artifact",
        "horizon_artifact_sha256": sha256_file(HORIZON),
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

    hashes = check_artifacts(cfg)
    hstar = load_horizon(cfg)
    policy = cfg["exit_policy"]
    log(f"D9(b) run {run_id} stage=learn  H = {hstar} market minutes  "
        f"exit_policy={policy}")
    log(f"RETROSPECTIVE COMPARISON ON PREVIOUSLY EXAMINED DATES")
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
        restart_after=cfg["runs"]["restart_after_settled_episodes"],
        log=log, runs_dir=RUNS, horizon_minutes=hstar, exit_policy=policy)
    learned["clean_reference_digest"] = clean
    learned["learned_digest"] = S.learned_state_digest(mb.gain, mb.pos, sha)
    learned["outcomes_full_precision"] = full_precision(accounts)
    journal.save_checkpoint(
        last_settled_episode=journal.last_settled_episode)

    summary = envelope(cfg, run_id, t_start, sha, clean, base, enc, reports,
                       hstar, hashes)
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
    tal = learned["partitions"]["LEARNING"]["tally"][
        "after_execution_constraints"]
    log(f"closures {dict((k, v) for k, v in sorted(tal.items()))}")
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

    hashes = check_artifacts(cfg)
    hstar = load_horizon(cfg)
    policy = cfg["exit_policy"]
    log(f"D9(b) run {run_id} stage=frozen  H = {hstar}  exit_policy={policy}")
    fb, mb, ann, enc, pops, run, sha, clean, series, reports, base = \
        common_setup(cfg, log)

    prev = json.loads((HERE / "learning_summary.json").read_text())
    if prev["run_id"] != run_id:
        raise SystemExit(f"learning_summary.json is for {prev['run_id']}, not "
                         f"{run_id}")
    if prev["config"]["exit_policy"] != policy:
        raise SystemExit("the learning stage ran under a different exit policy")
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
        b, _, accounts, _ = HR.run_branch(
            name=name, cfg=cfg, series=series, parts=parts,
            partitions=["FROZEN"], run=run, mb=mb, enc=enc, pops=pops,
            sha=sha, policy_for=policy_for_factory(cfg), run_id=run_id,
            learn_in=set(), start_gain=gain, round_base=0, log=log,
            runs_dir=RUNS, horizon_minutes=hstar, exit_policy=policy)
        b["start_digest_expected"] = (trained_digest if name == "frozen_trained"
                                      else clean)
        b["outcomes_full_precision"] = full_precision(accounts)
        out[name] = b

    summary = envelope(cfg, run_id, t_start, sha, clean, base, enc, reports,
                       hstar, hashes)
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
        if not p["digest_unchanged"]:
            log(f"WARNING: {name} moved a weight in a frozen branch")
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
