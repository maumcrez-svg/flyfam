#!/usr/bin/env python
"""`d11-001`: the LEARNING replay, the two frozen loop branches, the live hour.

    .venv/bin/python experiments/d11/run.py --branch learning
    .venv/bin/python experiments/d11/run.py --branch frozen_reference
    .venv/bin/python experiments/d11/run.py --branch frozen_trained
    .venv/bin/python experiments/d11/run.py --mode LIVE_PAPER            # start
    .venv/bin/python experiments/d11/run.py --mode LIVE_PAPER --status   # no RPC
    .venv/bin/python experiments/d11/run.py --mode LIVE_PAPER --stop

Nothing here chooses a number. Every parameter comes from
``experiments/d11/config.json`` (the D11 environment) and
``experiments/d11/d11_001.json`` (this run's registration), both committed
before the collection; the dataset is verified against the sha256 its own
MANIFEST records; the clean reference checkpoint is verified against the
digest the configuration registered; and the run refuses to start if either
disagrees.

Three replay branches over one recorded window, split by time and by nothing
else:

``learning``          ``LEARN`` over ``[t0, T]``, from the clean reference,
                      one brain carried through. An entry is refused at the
                      partition boundary — ``cutoff + 902 > T`` — so every
                      episode settles inside the partition, and the run fails
                      if a position is open at ``T``.
``frozen_reference``  ``FROZEN`` over ``[T, t1]`` from the clean reference.
``frozen_trained``    ``FROZEN`` over ``[T, t1]`` from ``learning``'s final
                      checkpoint. Both rebuild the market from ``t0`` without
                      the brain: the first frozen tick ingests every event at
                      or before ``T``.

The frozen branches are **descriptive paper results**. The primary comparison
is the market-only grid of ``grid.py``, which is the only pass whose rows two
branches can share.

**The replay path opens no socket.** ``flytrade.pons.rpc``'s client is imported
inside ``run_live`` and nowhere else, as D10's runner does, and a test asserts
it.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import common as C                                      # noqa: E402
from common import ROOT                                 # noqa: E402
from flytrade import decoder as D                       # noqa: E402
from flytrade import readout as RO                      # noqa: E402
from flytrade import records as REC                     # noqa: E402
from flytrade import runner as R                        # noqa: E402
from flytrade import state as S                         # noqa: E402
from flytrade.market import Universe                    # noqa: E402
from flytrade.pons import context_v2 as CTX2            # noqa: E402
from flytrade.pons import loop as LOOP                  # noqa: E402
from flytrade.pons import paper as PAPER                # noqa: E402
from flytrade.pons.budget import _atomic_write_json     # noqa: E402
from flytrade.pons.collector import Finality            # noqa: E402

RUNS = C.RUNS
RUN_ID = C.RUN_ID
LIVE_RUN_ID = "d11-live-001"
REPLAY_BRANCHES = ("learning", "frozen_reference", "frozen_trained")


def sha256_file(path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_dataset() -> Path:
    """The store on disk is the store the MANIFEST describes, or nothing runs."""
    directory = C.DATASET
    man = C.manifest()
    for name, entry in man["files"].items():
        path = directory / name
        if not path.exists():
            raise SystemExit(f"{path} is absent; the run is refused")
        got = sha256_file(path)
        if got != entry["sha256"]:
            raise SystemExit(
                f"{name}: sha256 {got[:16]} != the recorded {entry['sha256'][:16]}. "
                f"The file on disk is not the file collected; the run is "
                f"refused rather than silently substituting a dataset.")
    if not (directory / "initial_states.json").exists():
        raise SystemExit("initial_states.json is mandatory (addendum 1)")
    return directory


class PartitionReplayDriver(LOOP.ReplayDriver):
    """A recorded window read over one partition's ticks, on one fixed grid.

    The tick grid is anchored at ``t0`` — the window's first block timestamp —
    so the LEARNING partition, the two FROZEN branches and the evaluation grid
    all speak about the same instants. A branch that starts at ``T`` still
    receives every event at or before ``T`` on its first tick, which is how the
    market is rebuilt from ``t0`` without the brain evaluating anything before
    the boundary.
    """

    def __init__(self, directory, *, finality, first_tick: int, last_tick: int,
                 anchor_ts: int):
        super().__init__(directory, finality=finality)
        self.anchor_ts = int(anchor_ts)
        self.first_tick = int(first_tick)
        self.last_tick = int(last_tick)
        if (self.first_tick - self.anchor_ts) % LOOP.CADENCE_S:
            raise SystemExit("the first tick is not on the anchored grid")

    def ticks(self, cadence: int = LOOP.CADENCE_S):
        cutoff = self.first_tick
        while cutoff <= self.last_tick:
            yield int(cutoff)
            cutoff += int(cadence)

    def as_dict(self) -> dict:
        return {**super().as_dict(), "anchor_ts": self.anchor_ts,
                "first_tick": self.first_tick, "last_tick": self.last_tick,
                "partition_ticks": (self.last_tick - self.first_tick)
                // LOOP.CADENCE_S + 1}


def make_execution(cfg_v2: dict, cfg_run: dict) -> PAPER.PonsPaperExecution:
    fixed = cfg_run["fixed_for_the_whole_wave"]
    gas = C.gas_constants(cfg_run)
    scale = PAPER.reinforce_full_scale_from_config(cfg_v2)
    return PAPER.PonsPaperExecution(
        size_wei=int(fixed["paper_size_wei"]),
        latency_s=int(fixed["latency_seconds"]),
        horizon_s=int(fixed["horizon_seconds"]),
        initial_cash_wei=int(float(fixed["initial_cash_eth"]) * PAPER.WEI),
        reinforce_full_scale=scale,
        reinforce_cap=float(fixed["reinforce_cap"]), **gas)


def run_branch(*, name, cfg_v2, cfg_run, directory, mb, run, encoder, sha,
               clean, runs_dir, run_id, learning, first_tick, last_tick,
               anchor_ts, entry_deadline_ts, from_checkpoint=None, log=print):
    import shutil

    man = C.manifest()
    if from_checkpoint is None:
        mb.gain[:] = np.ones(len(mb.pos), dtype=np.float32)
    mb.trace[:] = 0.0
    mb.trace_episode[:] = -1
    mb.apply()

    finality = Finality(
        median_interval_s=float(man["window"]["median_block_interval_s"]),
        confirm_depth=int(man["window"]["confirm_depth_blocks"]),
        safe_tag_supported=True, sample=3)
    driver = PartitionReplayDriver(directory, finality=finality,
                                   first_tick=first_tick, last_tick=last_tick,
                                   anchor_ts=anchor_ts)
    store = Path(runs_dir) / run_id / name
    store.mkdir(parents=True, exist_ok=True)
    credit = R.CreditAssigner(mb)
    versions = REC.Versions(
        market=CTX2.VERSION, encoder=encoder.version, runner=R.VERSION,
        decoder=D.VERSION, execution=PAPER.VERSION,
        mushroom=__import__("flytrade.mushroom", fromlist=["VERSION"]).VERSION,
        graph_sha256=sha)
    journal = REC.Journal(store, mb=mb, credit=credit, versions=versions)
    journal.schema_meta = encoder.schema_metadata()
    journal.from_clean_reference = True
    journal.clean_reference_digest = clean

    start_from = None
    if from_checkpoint is not None:
        if not journal.checkpoint_path.exists():
            shutil.copy2(from_checkpoint, journal.checkpoint_path)
        report = journal.recover()
        start_from = journal.checkpoint_digest()
        log(f"[{run_id}/{name}] learned state from {from_checkpoint}, digest "
            f"{start_from[:12]}, recovery `{report['action']}`")
    journal.save_checkpoint(last_settled_episode=-1)

    execution = make_execution(cfg_v2, cfg_run)
    admission = C.admission_v2(cfg_v2, require_coverage=True)
    loop = LOOP.PonsLoop(
        driver=driver, run=run, mb=mb, credit=credit, journal=journal,
        encoder=encoder, admission=admission, execution=execution,
        policy=RO.policy_comparison(), universe=Universe(),
        mode=LOOP.MODE_REPLAY, learning=learning, branch=name, run_id=run_id,
        cadence=int(cfg_run["fixed_for_the_whole_wave"]["cadence_seconds"]),
        track_seconds=int(cfg_v2["admission"]["track_seconds"]),
        context_fn=CTX2.context_v2,
        entry_deadline_ts=entry_deadline_ts, log=log)
    ticks = (last_tick - first_tick) // LOOP.CADENCE_S + 1
    log(f"[{run_id}/{name}] {driver.as_dict()['events']:,} events, "
        f"{ticks:,} ticks [{first_tick}, {last_tick}], learning={learning}, "
        f"entry deadline {entry_deadline_ts}, scale "
        f"{execution.reinforce_full_scale}")
    out = loop.run_branch()
    out["clean_reference_digest"] = clean
    out["starts_from_digest"] = start_from
    out["dataset"] = driver.as_dict()
    out["log_sha256"] = sha256_file(journal.log.path)
    out["log_bytes"] = journal.log.path.stat().st_size
    out["execution_policy"] = execution.as_dict()
    out["admission_policy"] = admission.as_dict()
    out["partition"] = {"first_tick": first_tick, "last_tick": last_tick,
                        "ticks": ticks, "entry_deadline_ts": entry_deadline_ts}
    out["position_open_at_end"] = execution.account.position is not None
    if learning == LOOP.LEARN and out["position_open_at_end"]:
        raise SystemExit(
            f"[{run_id}/{name}] a learning position is still open at the "
            f"partition boundary {entry_deadline_ts}: the entry deadline did "
            f"not hold and the run is refused")
    log(f"[{run_id}/{name}] done in {out['wall_s']}s: "
        f"{len(out['episodes'])} episodes, digest "
        f"{out['start_digest'][:12]} -> {out['end_digest'][:12]}")
    return out


# --------------------------------------------------------------------------
# `--mode LIVE_PAPER`
# --------------------------------------------------------------------------
def live_paths(runs_dir, run_id: str) -> dict:
    d = Path(runs_dir) / run_id
    return {"dir": d, "branch": d / "live", "chain": d / "chain",
            "pid": d / "worker.pid", "stop": d / "stop",
            "health": d / "health.json", "summary": d / "summary.json",
            "log": d / "worker.log", "results": d / "results.md"}


def worker_alive(pid_path: Path) -> int | None:
    try:
        pid = int(Path(pid_path).read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    return pid


def print_status(paths: dict, run_id: str) -> int:
    """The health block, from the files the worker writes. **No RPC.**"""
    pid = worker_alive(paths["pid"])
    print(f"run          {run_id}  PONS / LIVE / PAPER / LEARN")
    print(f"worker       {'alive pid ' + str(pid) if pid else 'not running'}")
    if not paths["health"].exists():
        print("health       no health.json yet")
        return 0
    h = json.loads(paths["health"].read_text())
    now = int(time.time())
    confirmed_age = (None if h.get("confirmed_ts") is None
                     else now - int(h["confirmed_ts"]))
    fresh = confirmed_age is not None and confirmed_age <= LOOP.FRESH_SECONDS
    req = h.get("requests", {})
    print(f"heartbeat    {h.get('updated_utc')}")
    print(f"data         LIVE   ticks {h.get('ticks')}   "
          f"cutoff {h.get('cutoff_ts')} ({h.get('cutoff_age_s')}s old)")
    print(f"blocks       head {h.get('head_block')}   "
          f"cursor {h.get('cursor_block')}   lag {h.get('lag_blocks')} blocks")
    print(f"confirmed    block {h.get('confirmed_block')}  age {confirmed_age}s")
    print(f"fresh        {fresh}")
    print(f"requests     run {req.get('run_attempts')}/{req.get('run_cap')}   "
          f"wave {req.get('wave_attempts')}/{req.get('wave_cap')}")
    print(f"position     {h.get('position') or 'flat'}")
    print(f"episodes     {h.get('episodes')}   "
          f"pending {h.get('pending_confirmation')}   "
          f"unresolved {h.get('unresolved')}")
    stop = h.get("stop", {})
    print(f"stop         {stop.get('reason') or 'running'} "
          f"{stop.get('detail') or ''}")
    return 0


def run_live(args, cfg_v2, cfg_run, log) -> int:
    """One live hour from the TRAINED checkpoint, learning enabled."""
    import shutil

    from flytrade.pons.budget import (LOOPBACK, BudgetStop,  # noqa: PLC0415
                                      RequestLedger)
    from flytrade.pons.collector import Collector          # noqa: PLC0415
    from flytrade.pons.manifest import load_manifest       # noqa: PLC0415
    from flytrade.pons.rpc import (RpcClient, RpcError,    # noqa: PLC0415
                                   read_endpoint)
    from flytrade.pons.storage import ChainStore           # noqa: PLC0415

    run_id = args.run_id or LIVE_RUN_ID
    paths = live_paths(args.runs_dir, run_id)
    paths["dir"].mkdir(parents=True, exist_ok=True)
    if args.status:
        return print_status(paths, run_id)
    if args.stop:
        paths["stop"].write_text(
            f"stop requested {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n")
        pid = worker_alive(paths["pid"])
        print(f"wrote {paths['stop']}; the worker stops at its next check "
              f"({'pid ' + str(pid) if pid else 'no worker running'})")
        return 0

    alive = worker_alive(paths["pid"])
    if alive:
        raise SystemExit(f"a worker is already running (pid {alive})")
    if paths["stop"].exists():
        paths["stop"].unlink()

    live_cfg = cfg_run["live_hour"]
    caps = cfg_run["budget"]["projection"]["loopback_caps"]
    run_cap = int(cfg_run["budget"]["projection"]
                  ["per_entry_point_run_caps"]["live"])
    limits = LOOP.LiveLimits(
        max_seconds=int(args.max_seconds or live_cfg["seconds"]),
        max_requests=int(args.max_requests or run_cap),
        reserve_requests=30,
        backfill_seconds=int(args.backfill_seconds or 3600),
        backfill_requests=1_200, backfill_wall_seconds=900,
        stop_file=str(paths["stop"]))

    paths["pid"].write_text(f"{os.getpid()}\n")
    started = time.time()
    ledger = RequestLedger(HERE / "rpc_ledger_local.json", run_id=run_id,
                           wave_cap=int(caps["wave"]),
                           run_cap=limits.max_requests,
                           day_cap=int(caps["day"]), scope=LOOPBACK,
                           allow_remote=bool(args.allow_remote))
    before = json.loads(json.dumps(ledger.state))
    if ledger.halted():
        raise SystemExit(f"the ledger is halted ({ledger.halted()})")
    url = read_endpoint(args.env_file, args.env_key)
    rpc = RpcClient(url, ledger)
    if rpc.endpoint_class != LOOPBACK:
        raise SystemExit("the live hour runs against the local node only")

    chain = rpc.chain_id()
    if chain != LOOP.CHAIN_ID:
        raise SystemExit(f"eth_chainId returned {chain}, not {LOOP.CHAIN_ID}")
    head = rpc.block("latest")
    head_ts = int(str(head["timestamp"]), 16)
    age = int(time.time()) - head_ts
    log(f"[{run_id}] eth_chainId {chain}, head {int(str(head['number']), 16)} "
        f"age {age}s")
    if abs(age) > LOOP.FRESH_SECONDS:
        ledger.flush()
        paths["pid"].unlink(missing_ok=True)
        _atomic_write_json(paths["summary"], {
            "run_id": run_id, "status": "not_started",
            "reason": "NOT_FRESH_AT_START",
            "detail": (f"the local node's latest block is {age} s old, beyond "
                       f"the {LOOP.FRESH_SECONDS} s freshness rule; the live "
                       f"hour was not started and this is reported rather "
                       f"than worked around"),
            "head_ts": head_ts, "checked_utc": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        raise SystemExit(f"the node is not fresh ({age}s): the live hour is "
                         f"not started")

    man = C.manifest()
    deployments = load_manifest(ROOT / "experiments/d10/deployments.json")
    finality = Finality(
        median_interval_s=float(man["window"]["median_block_interval_s"]),
        confirm_depth=int(man["window"]["confirm_depth_blocks"]),
        safe_tag_supported=True, sample=3)
    store = ChainStore(paths["chain"]).load()
    collector = Collector(rpc, deployments, store, finality=finality,
                          track_seconds=int(cfg_v2["admission"]["track_seconds"]),
                          chunk_blocks=500)

    fb, mb, ann, encoder, pops, run, sha, clean = C.build_brain(cfg_v2)
    base = RO.load_baseline(ROOT / "experiments/k8_readout/baseline_k8.json",
                            k=RO.K, graph_sha256=sha)
    credit = R.CreditAssigner(mb)
    versions = REC.Versions(
        market=CTX2.VERSION, encoder=encoder.version, runner=R.VERSION,
        decoder=D.VERSION, execution=PAPER.VERSION,
        mushroom=__import__("flytrade.mushroom", fromlist=["VERSION"]).VERSION,
        graph_sha256=sha)
    paths["branch"].mkdir(parents=True, exist_ok=True)
    journal = REC.Journal(paths["branch"], mb=mb, credit=credit, versions=versions)
    journal.schema_meta = encoder.schema_metadata()
    journal.from_clean_reference = True
    journal.clean_reference_digest = clean

    trained = Path(args.runs_dir) / RUN_ID / "learning" / "brain.npz"
    want = json.loads((Path(args.runs_dir) / RUN_ID /
                       "summary.json").read_text())["branches"]["learning"][
                           "learned_digest"]
    if not journal.checkpoint_path.exists():
        if not trained.exists():
            raise SystemExit(f"{trained} is absent: the live hour starts from "
                             f"the TRAINED checkpoint and nothing else")
        shutil.copy2(trained, journal.checkpoint_path)
    report = journal.recover()
    got = journal.checkpoint_digest()
    if got != str(want):
        raise SystemExit(f"the learned state on disk digests to {got[:12]}, "
                         f"not the recorded TRAINED {str(want)[:12]}: the run "
                         f"is refused rather than starting from a brain "
                         f"nobody declared")
    journal.save_checkpoint(last_settled_episode=report["last_settled_episode"])
    credit_at_start = json.loads(json.dumps(credit.stats(), default=str))
    log(f"[{run_id}] starts from TRAINED {got[:12]}, recovery "
        f"`{report['action']}`")

    execution = make_execution(cfg_v2, cfg_run)
    admission = C.admission_v2(cfg_v2, require_coverage=False)
    cell: dict = {}

    def heartbeat(driver):
        position = execution.account.position
        payload = driver.health(
            run_id=run_id, branch="live", learning=LOOP.LEARN,
            pid=os.getpid(), pid_file=str(paths["pid"]),
            stop_file=str(paths["stop"]),
            episodes=len(cell.get("episodes", [])),
            pending_confirmation=(None if cell.get("pending") is None
                                  else cell["pending"].get("episode_id")),
            unresolved=len(cell.get("unresolved", [])),
            position=(None if position is None else {
                "token": position.symbol, "episode_id": position.episode_id,
                "entry_block": position.entry.bar_index,
                "entry_ts": position.entry.ts,
                "horizon_ts": execution.horizon_ts}),
            marks=cell.get("marks", 0))
        _atomic_write_json(paths["health"], payload)

    driver = LOOP.LiveDriver(
        collector, finality=finality, limits=limits, label=run_id,
        latency_s=int(cfg_run["fixed_for_the_whole_wave"]["latency_seconds"]),
        log=log, on_tick=heartbeat).install_signal_handlers()
    loop = LOOP.PonsLoop(
        driver=driver, run=run, mb=mb, credit=credit, journal=journal,
        encoder=encoder, admission=admission, execution=execution,
        policy=RO.policy_comparison(), universe=Universe(),
        mode=LOOP.MODE_LIVE, learning=LOOP.LEARN, branch="live", run_id=run_id,
        cadence=int(cfg_run["fixed_for_the_whole_wave"]["cadence_seconds"]),
        track_seconds=int(cfg_v2["admission"]["track_seconds"]),
        context_fn=CTX2.context_v2, log=log)
    cell.update(episodes=loop.episodes, unresolved=loop.unresolved)

    def refresh(drv):
        cell["pending"] = loop.pending
        cell["marks"] = loop.marks
        heartbeat(drv)

    driver.on_tick = refresh

    skeleton = {
        "run_id": run_id, "venue": LOOP.VENUE, "chain_id": LOOP.CHAIN_ID,
        "mode": LOOP.MODE_LIVE, "learning": LOOP.LEARN,
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
        "status": "running", "config": cfg_v2, "run_config": cfg_run,
        "starts_from": {"run": RUN_ID, "branch": "learning",
                        "checkpoint": str(trained), "state_digest": want},
        "starts_from_digest": got,
        "graph_sha256": sha, "clean_reference_digest": clean,
        "python": platform.python_version(), "numpy": np.__version__,
        "baseline": base.as_dict(), "encoder": encoder.as_dict(),
        "decoder": RO.decoder_k8().as_dict(),
        "readout": RO.policy_comparison().as_dict(),
        "endpoint_class": rpc.endpoint_class,
        "a_finished_run_is_a_record": (
            "a finished run is a record of an hour that already ended, never "
            "a fly operating now"),
        "branches": {"live": {"mode": LOOP.MODE_LIVE, "learning": LOOP.LEARN,
                              "status": "running", "start_digest": got,
                              "episodes": []}},
    }
    _atomic_write_json(paths["summary"], skeleton)

    out: dict = {}
    failure = None
    try:
        out = loop.run_branch()
    except (BudgetStop, RpcError) as exc:
        failure = {"code": exc.code, "detail": exc.detail}
        log(f"[{run_id}] stopped by {exc.code}: {exc.detail}")
    finally:
        ledger.flush()
        paths["pid"].unlink(missing_ok=True)

    spent = {}
    for method, entry in ledger.state["by_method"].items():
        was = before["by_method"].get(method, {"attempts": 0, "units": 0,
                                               "errors": 0})
        spent[method] = {"attempts": entry["attempts"] - was["attempts"],
                         "units": entry["units"] - was["units"],
                         "errors": entry["errors"] - was["errors"]}
    summary = {
        **skeleton,
        "status": "stopped",
        "stopped_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_s": round(time.time() - started, 1),
        "peak_rss_mib": round(
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1),
        "recovery": report, "credit_at_start": credit_at_start,
        "failure": failure,
        "driver": driver.as_dict(),
        "health": driver.health(run_id=run_id),
        "chain": {"raw_logs": len(collector.store.seen),
                  "events": len(collector.store.events),
                  "cursor": collector.store.cursor,
                  "launches_seen": driver.launches_seen,
                  "completed_curves": len(collector.completed),
                  "orphaned": len(collector.store.orphaned)},
        "requests": {
            "by_method": spent,
            "attempts": sum(v["attempts"] for v in spent.values()),
            "units": sum(v["units"] for v in spent.values()),
            "errors": sum(v["errors"] for v in spent.values()),
            "run_cap": limits.max_requests,
            "endpoint_class": rpc.endpoint_class,
            "loopback_attempts": sum(v["attempts"] for v in spent.values()),
            "remote_attempts": 0,
            "wave_attempts": ledger.attempts, "wave_cap": ledger.wave_cap},
        "branches": {"live": {**(out or {}), "mode": LOOP.MODE_LIVE,
                              "learning": LOOP.LEARN, "status": "stopped",
                              "stop_reason": driver.stopped,
                              "stop_detail": driver.stop_detail}},
    }
    if out:
        summary["branches"]["live"]["learned_digest"] = S.learned_state_digest(
            mb.gain, mb.pos, sha)
    _atomic_write_json(paths["summary"], summary)
    try:
        driver.on_tick = None
        heartbeat(driver)
    except Exception:                                       # pragma: no cover
        pass
    log(f"[{run_id}] stopped: {driver.stopped} {driver.stop_detail}; "
        f"{driver.ticks_done} ticks, {len(out.get('episodes', []))} episodes, "
        f"{summary['requests']['attempts']} requests, digest {got[:12]} -> "
        f"{out.get('end_digest', '?')[:12]}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", default=str(RUNS))
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--branch", action="append", default=None,
                        choices=list(REPLAY_BRANCHES))
    parser.add_argument("--mode", default=LOOP.MODE_REPLAY, choices=LOOP.MODES)
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--max-seconds", type=int, default=None)
    parser.add_argument("--max-requests", type=int, default=None)
    parser.add_argument("--backfill-seconds", type=int, default=None)
    parser.add_argument("--env-file", default=str(HERE / "local_node.env"))
    parser.add_argument("--env-key", default="LOCAL_NITRO_RPC_HTTP")
    parser.add_argument("--allow-remote", action="store_true",
                        help="never passed by this wave")
    args = parser.parse_args(argv)

    cfg_v2, cfg_run = C.configs()
    runs_dir = Path(args.runs_dir)
    live_mode = args.mode == LOOP.MODE_LIVE
    run_id = args.run_id or (LIVE_RUN_ID if live_mode else RUN_ID)
    (runs_dir / run_id).mkdir(parents=True, exist_ok=True)
    if live_mode and (args.stop or args.status):
        return run_live(args, cfg_v2, cfg_run, print)
    logf = (runs_dir / run_id / ("worker.log" if live_mode else "run.log")).open(
        "a" if live_mode else "a")

    def log(*a, **kw):
        kw.pop("flush", None)
        stamp = time.strftime("%H:%M:%S", time.gmtime())
        print(*a, **kw)
        print(stamp, *a, file=logf)
        logf.flush()
        sys.stdout.flush()

    if live_mode:
        try:
            return run_live(args, cfg_v2, cfg_run, log)
        finally:
            logf.close()

    t_start = time.time()
    log(f"run {run_id} starting "
        f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
    directory = verify_dataset()
    man = C.manifest()
    sp = C.split(man["window"])
    fb, mb, ann, encoder, pops, run, sha, clean = C.build_brain(cfg_v2)
    log(f"graph {sha[:12]}, clean reference digest {clean[:12]}, "
        f"{len(mb.pos):,} plastic synapses, encoder {encoder.version} "
        f"schema {encoder.input_schema_sha256[:12]}")
    base = RO.load_baseline(ROOT / "experiments/k8_readout/baseline_k8.json",
                            k=RO.K, graph_sha256=sha)
    if base.theta_hz != RO.THETA_HZ_K8 or base.baseline_hz != RO.BASELINE_HZ_K8:
        raise SystemExit("the loaded baseline is not the stored artifact")

    summary_path = runs_dir / run_id / "summary.json"
    summary = (json.loads(summary_path.read_text())
               if summary_path.exists() else
               {"run_id": run_id, "venue": LOOP.VENUE, "chain_id": LOOP.CHAIN_ID,
                "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                             time.gmtime(t_start)),
                "python": platform.python_version(), "numpy": np.__version__,
                "machine": platform.processor() or platform.machine(),
                "config": cfg_v2, "run_config": cfg_run,
                "config_sha256": sha256_file(C.CONFIG_V2),
                "run_config_sha256": sha256_file(C.CONFIG_RUN),
                "plan_sha256": sha256_file(HERE / "PLAN.md"),
                "dataset_manifest_sha256": sha256_file(
                    C.DATASET / "MANIFEST.json"),
                "graph_sha256": sha, "clean_reference_digest": clean,
                "baseline": base.as_dict(), "encoder": encoder.as_dict(),
                "decoder": RO.decoder_k8().as_dict(),
                "readout": RO.policy_comparison().as_dict(),
                "split": sp, "branches": {}})

    wanted = args.branch or list(REPLAY_BRANCHES)
    for name in wanted:
        if name == "learning":
            out = run_branch(
                name=name, cfg_v2=cfg_v2, cfg_run=cfg_run, directory=directory,
                mb=mb, run=run, encoder=encoder, sha=sha, clean=clean,
                runs_dir=runs_dir, run_id=run_id, learning=LOOP.LEARN,
                first_tick=sp["learning_first_tick"],
                last_tick=sp["learning_last_tick"], anchor_ts=sp["t0"],
                entry_deadline_ts=sp["T"], log=log)
            out["learned_digest"] = S.learned_state_digest(mb.gain, mb.pos, sha)
        elif name == "frozen_reference":
            out = run_branch(
                name=name, cfg_v2=cfg_v2, cfg_run=cfg_run, directory=directory,
                mb=mb, run=run, encoder=encoder, sha=sha, clean=clean,
                runs_dir=runs_dir, run_id=run_id, learning=LOOP.FROZEN,
                first_tick=sp["frozen_first_tick"],
                last_tick=sp["frozen_last_tick"], anchor_ts=sp["t0"],
                entry_deadline_ts=sp["t1"], log=log)
        else:
            trained = runs_dir / run_id / "learning" / "brain.npz"
            if not trained.exists():
                raise SystemExit(f"{trained} is absent: frozen_trained starts "
                                 f"from the learning branch's final checkpoint")
            out = run_branch(
                name=name, cfg_v2=cfg_v2, cfg_run=cfg_run, directory=directory,
                mb=mb, run=run, encoder=encoder, sha=sha, clean=clean,
                runs_dir=runs_dir, run_id=run_id, learning=LOOP.FROZEN,
                first_tick=sp["frozen_first_tick"],
                last_tick=sp["frozen_last_tick"], anchor_ts=sp["t0"],
                entry_deadline_ts=sp["t1"], from_checkpoint=trained, log=log)
        summary["branches"][name] = out
        summary["elapsed_s"] = round(time.time() - t_start, 1)
        summary["peak_rss_mib"] = round(
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1)
        summary_path.write_text(json.dumps(summary, indent=1, default=str))

    log(f"run {run_id} finished in {(time.time() - t_start) / 60:.1f} min, "
        f"peak RSS {summary['peak_rss_mib']:.0f} MiB")
    logf.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
