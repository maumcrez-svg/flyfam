#!/usr/bin/env python
"""The Pons runs: `d10-001` on the recorded window, `d10-live-001` on the wire.

    .venv/bin/python experiments/d10/run.py                  # both branches
    .venv/bin/python experiments/d10/run.py --branch learning
    .venv/bin/python experiments/d10/run.py --run-id d10-001r --runs-dir /tmp/x

The live exercise (addendum 15) is the same file in `--mode LIVE_PAPER`, with
**three commands** and nothing else:

    start   nohup .venv/bin/python experiments/d10/run.py --mode LIVE_PAPER \
              > experiments/d10/runs/d10-live-001/worker.out 2>&1 &
    stop    .venv/bin/python experiments/d10/run.py --mode LIVE_PAPER --stop
            (the alternative: kill -TERM $(cat .../worker.pid))
    status  .venv/bin/python experiments/d10/run.py --mode LIVE_PAPER --status

`start` writes a pid file and refuses to run beside a live worker: one process
owns the journal. `stop` writes a flag file the worker checks at every stop
point. `status` reads the files the worker writes and **opens no socket**.

Nothing in here chooses a number. Every parameter is read from `config.json`,
which was committed alone before this file existed; the dataset is verified
against the sha256 recorded there; the clean reference checkpoint is verified
against the digest recorded there; and the run refuses to start if either
disagrees.

Two branches:

`learning`          LEARN, from the clean reference checkpoint, strict
                    chronological order over the window, one brain carried
                    through, one declared mid-run restart.
`frozen_reference`  FROZEN, the same data and the same `comparison_v1` seeds
                    from the same clean checkpoint. The mechanical control:
                    its end digest must equal its start digest.

Writes `runs/<run_id>/<branch>/` (gitignored: event log, checkpoints, pending
episode) and `summary.json` beside this file.
"""

from __future__ import annotations

import argparse
import hashlib
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

from flytrade import decoder as D          # noqa: E402
from flytrade import execution as X        # noqa: E402
from flytrade import graph as G            # noqa: E402
from flytrade import market as MK          # noqa: E402
from flytrade import mushroom as M         # noqa: E402
from flytrade import populations as P      # noqa: E402
from flytrade import readout as RO         # noqa: E402
from flytrade import records as REC        # noqa: E402
from flytrade import runner as R           # noqa: E402
from flytrade import state as S            # noqa: E402
from flytrade.market import Universe       # noqa: E402
from flytrade.pons import context as CTX   # noqa: E402
from flytrade.pons import loop as LOOP     # noqa: E402
from flytrade.pons import paper as PAPER   # noqa: E402
from flytrade.pons.admission import AdmissionPolicy  # noqa: E402
from flytrade.pons.budget import _atomic_write_json  # noqa: E402
from flytrade.pons.collector import Finality  # noqa: E402
from flytrade.pons.encoder import SensoryEncoder  # noqa: E402
from flytrade.pons.rpc import DEFAULT_ENV_FILE, DEFAULT_ENV_KEY  # noqa: E402

DATA = ROOT / "data" / "malecns-v1.0"
RUNS = HERE / "runs"
CONFIG = HERE / "config.json"
#: the live exercise's own registration, committed before it ran (addendum 15).
#: `config.json` is not edited: its register-then-compute check pins it to the
#: commit that precedes the replay run.
LIVE_CONFIG = HERE / "live.json"


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_brain(cfg):
    """The same construction `experiments/historical/run.py::build_brain` uses."""
    import flysim
    fb = flysim.FlyBrain(graph_path=DATA / "graph.npz")
    mod = G.ModulatoryGraph(DATA / "graph_mod.npz", bodies=fb.bodies)
    ann = P.Annotations.load(DATA / "annotations.npz")
    sha = G.sha256_file(DATA / "graph.npz")
    want = cfg["brain"]["clean_reference_checkpoint"]["graph_sha256"]
    if sha != want:
        raise SystemExit(f"graph sha256 {sha[:12]} != the pre-registered "
                         f"{want[:12]}: the run is refused")
    mb = M.MushroomBody(fb, mod,
                        np.flatnonzero(P.kenyon_cells(ann)),
                        np.flatnonzero(P.mbons(ann)),
                        np.flatnonzero(P.pam(ann)),
                        np.flatnonzero(P.ppl1(ann)))
    encoder = SensoryEncoder(ann, cfg["features"]["scales"],
                             features=tuple(cfg["features"]["order"]))
    if list(encoder.features) != list(cfg["features"]["order"]):
        raise SystemExit("the encoder dropped a feature the config registered; "
                         "the run is refused")
    pops = D.readout_populations(ann, mb.compartments)
    run = R.BrainRunner(fb, mb, encoder.olfactory, pops, graph_sha256=sha)
    clean = S.learned_state_digest(mb.gain, mb.pos, sha)
    want_dig = cfg["brain"]["clean_reference_checkpoint"]["state_digest"]
    if clean != want_dig:
        raise SystemExit(f"clean reference digest {clean[:12]} != the "
                         f"pre-registered {want_dig[:12]}: the run is refused")
    return fb, mb, ann, encoder, pops, run, sha, clean


def verify_dataset(cfg) -> Path:
    directory = ROOT / cfg["dataset"]["directory"]
    if not directory.is_dir():
        raise SystemExit(f"{directory} is absent; see data/MANIFEST.md")
    for name, want in cfg["dataset"]["sha256"].items():
        path = directory / name
        if not path.exists():
            raise SystemExit(f"{path} is absent; the run is refused")
        got = sha256_file(path)
        if got != want:
            raise SystemExit(
                f"{name}: sha256 {got[:16]} != the registered {want[:16]}. The "
                f"file on disk is not the file the plan was registered against; "
                f"the run is refused rather than silently substituting a dataset.")
    return directory


def run_branch(*, name, cfg, directory, mb, run, encoder, sha, clean,
               run_id, runs_dir, learning, restart_after=None, log=print):
    mb.gain[:] = np.ones(len(mb.pos), dtype=np.float32)
    mb.trace[:] = 0.0
    mb.trace_episode[:] = -1
    mb.apply()

    finality = Finality(
        median_interval_s=float(cfg["dataset"]["window"]["median_block_interval_s"]),
        confirm_depth=int(cfg["settlement"]["confirm_depth_blocks"]),
        safe_tag_supported=bool(cfg["settlement"]["safe_tag_supported"]),
        sample=3)
    driver = LOOP.ReplayDriver(directory, finality=finality)
    store = Path(runs_dir) / run_id / name
    credit = R.CreditAssigner(mb)
    versions = REC.Versions(
        market=CTX.VERSION, encoder=encoder.version, runner=R.VERSION,
        decoder=D.VERSION, execution=PAPER.VERSION, mushroom=M.VERSION,
        graph_sha256=sha)
    journal = REC.Journal(store, mb=mb, credit=credit, versions=versions)
    journal.save_checkpoint(last_settled_episode=-1)

    execution = PAPER.PonsPaperExecution(
        size_wei=int(cfg["paper_size_wei"]),
        latency_s=int(cfg["latency_seconds"]),
        horizon_s=int(cfg["horizon_seconds"]),
        gas_buy_wei=int(cfg["gas"]["buy_wei"]),
        gas_sell_wei=int(cfg["gas"]["sell_wei"]),
        gas_approval_wei=int(cfg["gas"]["approval_wei"]),
        initial_cash_wei=int(float(cfg["initial_cash_eth"]) * PAPER.WEI))
    admission = AdmissionPolicy(
        size_wei=int(cfg["paper_size_wei"]),
        latency_s=int(cfg["latency_seconds"]),
        horizon_s=int(cfg["horizon_seconds"]),
        max_candidates=int(cfg["max_candidates_per_round"]))
    loop = LOOP.PonsLoop(
        driver=driver, run=run, mb=mb, credit=credit, journal=journal,
        encoder=encoder, admission=admission, execution=execution,
        policy=RO.policy_comparison(), universe=Universe(),
        mode=LOOP.MODE_REPLAY, learning=learning, branch=name, run_id=run_id,
        cadence=int(cfg["cadence_seconds"]),
        track_seconds=int(cfg["admission"]["track_seconds"]),
        restart_after=restart_after, log=log)
    log(f"[{run_id}/{name}] {driver.as_dict()['events']:,} events, "
        f"{len(list(driver.ticks(int(cfg['cadence_seconds'])))):,} ticks, "
        f"learning={learning}")
    out = loop.run_branch()
    out["clean_reference_digest"] = clean
    out["dataset"] = driver.as_dict()
    out["log_sha256"] = sha256_file(journal.log.path)
    out["log_bytes"] = journal.log.path.stat().st_size
    out["execution_policy"] = execution.as_dict()
    out["admission_policy"] = admission.as_dict()
    log(f"[{run_id}/{name}] done in {out['wall_s']}s: "
        f"{len(out['episodes'])} episodes, digest "
        f"{out['start_digest'][:12]} -> {out['end_digest'][:12]}")
    return out


# --------------------------------------------------------------------------
# `--mode LIVE_PAPER`: the worker, and the three commands
# --------------------------------------------------------------------------
def live_paths(runs_dir, run_id: str) -> dict:
    """Everything the worker writes. ``runs/`` is gitignored, as since D5."""
    d = Path(runs_dir) / run_id
    return {"dir": d, "branch": d / "live", "chain": d / "chain",
            "pid": d / "worker.pid", "stop": d / "stop",
            "health": d / "health.json", "summary": d / "summary.json",
            "log": d / "worker.log", "results": d / "results.md"}


def worker_alive(pid_path: Path) -> int | None:
    """The pid in the file if that process still exists, else ``None``."""
    try:
        pid = int(Path(pid_path).read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    return pid


def print_status(paths: dict, live_cfg: dict, run_id: str) -> int:
    """The health block, from the files the worker writes. **No RPC.**

    Nothing in this function opens a socket, and nothing it prints was
    computed here except ``fresh`` and the heartbeat age, which are
    now-relative by definition and are labelled as read-time facts.
    """
    pid = worker_alive(paths["pid"])
    print(f"run          {run_id}  "
          f"{live_cfg['venue']} / LIVE / PAPER / {live_cfg['learning']}")
    print(f"worker       {'alive pid ' + str(pid) if pid else 'not running'}"
          f"   (pid file {paths['pid']})")
    if not paths["health"].exists():
        print("health       no health.json yet")
        return 0
    h = json.loads(paths["health"].read_text())
    age = time.time() - paths["health"].stat().st_mtime
    now = int(time.time())
    confirmed_age = (None if h.get("confirmed_ts") is None
                     else now - int(h["confirmed_ts"]))
    fresh = confirmed_age is not None and confirmed_age <= 120
    req = h.get("requests", {})
    print(f"heartbeat    {h.get('updated_utc')}  ({age:.0f}s ago)")
    print(f"data         LIVE   ticks {h.get('ticks')}   "
          f"cutoff {h.get('cutoff_ts')} ({h.get('cutoff_age_s')}s old)")
    print(f"blocks       head {h.get('head_block')}   "
          f"cursor {h.get('cursor_block')}   "
          f"lag {h.get('lag_blocks')} blocks / {h.get('lag_seconds')} s")
    print(f"confirmed    block {h.get('confirmed_block')} "
          f"(depth {h.get('confirm_depth')}, safe {h.get('safe_block')}), "
          f"age {confirmed_age}s")
    print(f"fresh        {fresh}   "
          f"(false whenever the last confirmed block is older than 120 s)")
    print(f"requests     run {req.get('run_attempts')}/{req.get('run_cap')} "
          f"(left {req.get('run_remaining')})   "
          f"wave {req.get('wave_attempts')}/{req.get('wave_cap')} "
          f"(left {req.get('wave_remaining')})   units {req.get('units')}")
    print(f"errors       {h.get('errors')}   last {h.get('last_error')}")
    print(f"tracked      {h.get('tracked_curves')} curves   "
          f"launches seen {h.get('launches_seen')}   "
          f"reorgs {h.get('reorgs')}")
    print(f"position     {h.get('position') or 'flat'}")
    print(f"episodes     {h.get('episodes')}   "
          f"pending {h.get('pending_confirmation')}   "
          f"unresolved {h.get('unresolved')}")
    stop = h.get("stop", {})
    print(f"stop         {stop.get('reason') or 'running'} "
          f"{stop.get('detail') or ''}   "
          f"seconds left {stop.get('seconds_left')}")
    return 0


def verify_start_digest(journal, want: str) -> str:
    """The live run starts from a declared brain, or it does not start.

    Continuity replay → live is the point of starting from `d10-001/learning`'s
    final checkpoint, and a different learned state would not be that. The
    digest is registered in `live.json` before the run and compared here; a
    mismatch refuses the run rather than quietly training something else.
    """
    got = journal.checkpoint_digest()
    if got != str(want):
        raise SystemExit(
            f"the learned state on disk digests to {got[:12]}…, not the "
            f"registered {str(want)[:12]}…: the run is refused rather than "
            f"starting from a brain nobody declared")
    return got


def run_live(args, cfg, log) -> int:
    """One live worker: poll, decide, learn, stop cleanly. Addendum 15."""
    import shutil

    from flytrade.pons import loop as LOOP                       # noqa: F811
    from flytrade.pons.budget import BudgetStop, RequestLedger
    from flytrade.pons.collector import Collector
    from flytrade.pons.manifest import load_manifest
    from flytrade.pons.rpc import RpcClient, RpcError, read_endpoint
    from flytrade.pons.storage import ChainStore

    live_cfg = json.loads(LIVE_CONFIG.read_text())
    run_id = args.run_id or live_cfg["run_id"]
    paths = live_paths(args.runs_dir, run_id)
    paths["dir"].mkdir(parents=True, exist_ok=True)

    if args.status:
        return print_status(paths, live_cfg, run_id)
    if args.stop:
        paths["stop"].write_text(
            f"stop requested {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n")
        pid = worker_alive(paths["pid"])
        print(f"wrote {paths['stop']}; the worker stops at its next check "
              f"({'pid ' + str(pid) if pid else 'no worker running'}). "
              f"SIGTERM is the alternative: kill -TERM {pid or '<pid>'}")
        return 0

    alive = worker_alive(paths["pid"])
    if alive:
        raise SystemExit(f"a worker is already running (pid {alive}); one "
                         f"process owns this run, and a second would be a "
                         f"second brain on the same journal")
    if paths["stop"].exists():
        paths["stop"].unlink()

    limits = LOOP.LiveLimits(
        max_seconds=int(args.max_seconds or live_cfg["limits"]["max_seconds"]),
        max_requests=int(args.max_requests or live_cfg["limits"]["max_requests"]),
        reserve_requests=int(live_cfg["limits"]["reserve_requests"]),
        backfill_seconds=int(args.backfill_seconds
                             or live_cfg["limits"]["backfill_seconds"]),
        backfill_requests=int(live_cfg["limits"]["backfill_requests"]),
        backfill_wall_seconds=int(live_cfg["limits"]["backfill_wall_seconds"]),
        stop_file=str(paths["stop"]))

    paths["pid"].write_text(f"{os.getpid()}\n")
    started = time.time()
    log(f"[{run_id}] live worker pid {os.getpid()}, "
        f"limits {limits.as_dict()['rule']}")

    ledger = RequestLedger(HERE / "rpc_ledger.json", run_id=run_id,
                           run_cap=limits.max_requests)
    # snapshotted before the chain-id precondition, so the run's reported cost
    # is every request it made and not every request after the first one
    before = json.loads(json.dumps(ledger.state))
    if ledger.halted():
        raise SystemExit(f"the ledger is halted ({ledger.halted()}); nothing "
                         f"here may clear it or switch provider")
    url = read_endpoint(args.env_file, args.env_key)
    rpc = RpcClient(url, ledger)

    # Precondition, addendum 15: the chain, in one request, before anything else.
    chain = rpc.chain_id()
    if chain != LOOP.CHAIN_ID:
        raise SystemExit(f"eth_chainId returned {chain}, not {LOOP.CHAIN_ID}: "
                         f"this is not Robinhood Chain and nothing runs")
    log(f"[{run_id}] eth_chainId {chain} ✓   ledger wave "
        f"{ledger.attempts}/{ledger.wave_cap}")

    manifest = load_manifest(HERE / "deployments.json")
    finality = Finality(
        median_interval_s=float(cfg["dataset"]["window"]["median_block_interval_s"]),
        confirm_depth=int(cfg["settlement"]["confirm_depth_blocks"]),
        safe_tag_supported=bool(cfg["settlement"]["safe_tag_supported"]),
        sample=3)
    store = ChainStore(paths["chain"]).load()
    collector = Collector(rpc, manifest, store, finality=finality,
                          track_seconds=int(cfg["admission"]["track_seconds"]),
                          chunk_blocks=int(live_cfg["limits"]["tick_chunk_blocks"]))

    fb, mb, ann, encoder, pops, run, sha, clean = build_brain(cfg)
    base = RO.load_baseline(ROOT / cfg["readout"]["baseline_artifact"],
                            k=cfg["readout"]["k"], graph_sha256=sha)
    credit = R.CreditAssigner(mb)
    versions = REC.Versions(
        market=CTX.VERSION, encoder=encoder.version, runner=R.VERSION,
        decoder=D.VERSION, execution=PAPER.VERSION, mushroom=M.VERSION,
        graph_sha256=sha)
    paths["branch"].mkdir(parents=True, exist_ok=True)
    journal = REC.Journal(paths["branch"], mb=mb, credit=credit, versions=versions)

    want = live_cfg["starts_from"]["state_digest"]
    restart = journal.checkpoint_path.exists()
    if not restart:
        source = ROOT / live_cfg["starts_from"]["checkpoint"]
        if not source.exists():
            raise SystemExit(f"{source} is absent: the live run starts from "
                             f"{live_cfg['starts_from']['run']}/"
                             f"{live_cfg['starts_from']['branch']}'s final "
                             f"checkpoint and will not start from anything else")
        shutil.copy2(source, journal.checkpoint_path)
    report = journal.recover()
    got = verify_start_digest(journal, want)
    journal.save_checkpoint(last_settled_episode=report["last_settled_episode"])
    # the credit counters are durable and ride in the checkpoint, so the run
    # inherits the replay run's totals; this is what the live report subtracts
    # so "accepted in this run" is this run's number and not a carried one
    credit_at_start = json.loads(json.dumps(credit.stats(), default=str))
    origin = ("its own (restart)" if restart else
              f"{live_cfg['starts_from']['run']}/{live_cfg['starts_from']['branch']}")
    log(f"[{run_id}] learned state from {origin} checkpoint, digest "
        f"{got[:12]}…, recovery `{report['action']}`, "
        f"cursor {collector.cursor_block}")

    execution = PAPER.PonsPaperExecution(
        size_wei=int(cfg["paper_size_wei"]),
        latency_s=int(cfg["latency_seconds"]),
        horizon_s=int(cfg["horizon_seconds"]),
        gas_buy_wei=int(cfg["gas"]["buy_wei"]),
        gas_sell_wei=int(cfg["gas"]["sell_wei"]),
        gas_approval_wei=int(cfg["gas"]["approval_wei"]),
        initial_cash_wei=int(float(cfg["initial_cash_eth"]) * PAPER.WEI))
    admission = AdmissionPolicy(
        size_wei=int(cfg["paper_size_wei"]),
        latency_s=int(cfg["latency_seconds"]),
        horizon_s=int(cfg["horizon_seconds"]),
        max_candidates=int(cfg["max_candidates_per_round"]),
        require_coverage=bool(live_cfg["admission"]["require_coverage"]))

    cell: dict = {}

    def heartbeat(driver):
        position = execution.account.position
        payload = driver.health(
            run_id=run_id, branch="live", learning=live_cfg["learning"],
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
        collector, finality=finality, limits=limits,
        label=live_cfg["dataset_label"], latency_s=int(cfg["latency_seconds"]),
        log=log, on_tick=heartbeat).install_signal_handlers()

    loop = LOOP.PonsLoop(
        driver=driver, run=run, mb=mb, credit=credit, journal=journal,
        encoder=encoder, admission=admission, execution=execution,
        policy=RO.policy_comparison(), universe=Universe(),
        mode=LOOP.MODE_LIVE, learning=LOOP.LEARN, branch="live", run_id=run_id,
        cadence=int(cfg["cadence_seconds"]),
        track_seconds=int(cfg["admission"]["track_seconds"]), log=log)
    cell.update(episodes=loop.episodes, unresolved=loop.unresolved)

    def refresh(driver):                      # keep the heartbeat's view current
        cell["pending"] = loop.pending
        cell["marks"] = loop.marks
        heartbeat(driver)

    driver.on_tick = refresh

    skeleton = {
        "run_id": run_id, "venue": LOOP.VENUE, "chain_id": LOOP.CHAIN_ID,
        "mode": LOOP.MODE_LIVE, "learning": live_cfg["learning"],
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
        "status": "running", "config": cfg, "live": live_cfg,
        "config_sha256": sha256_file(args.config),
        "plan_sha256": sha256_file(HERE / "PLAN.md"),
        "live_sha256": sha256_file(LIVE_CONFIG),
        "graph_sha256": sha, "clean_reference_digest": clean,
        "starts_from_digest": got,
        # written into the skeleton too, so the viewer's provenance block is
        # complete while the run is still going rather than only after it
        "python": platform.python_version(), "numpy": np.__version__,
        "baseline": base.as_dict(), "encoder": encoder.as_dict(),
        "decoder": RO.decoder_k8().as_dict(),
        "readout": RO.policy_comparison().as_dict(),
        "branches": {"live": {"mode": LOOP.MODE_LIVE,
                              "learning": live_cfg["learning"],
                              "status": "running",
                              "start_digest": got, "episodes": []}},
    }
    _atomic_write_json(paths["summary"], skeleton)

    out = {}
    failure = None
    try:
        out = loop.run_branch()
    except (BudgetStop, RpcError) as exc:          # a stop that reached the loop
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
    raw_logs = len(collector.store.seen)
    events = len(collector.store.events)
    blocks_scanned = (0 if driver.first_ts == 0 else
                      max(0, (collector.cursor_block or 0)
                          - int(driver.backfill.get("first_block", 0) or 0)))
    summary = {
        **skeleton,
        "status": "stopped",
        "stopped_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_s": round(time.time() - started, 1),
        "peak_rss_mib": round(
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1),
        "python": platform.python_version(), "numpy": np.__version__,
        "baseline": base.as_dict(),
        "encoder": encoder.as_dict(),
        "decoder": RO.decoder_k8().as_dict(),
        "readout": RO.policy_comparison().as_dict(),
        "recovery": report,
        "credit_at_start": credit_at_start,
        "failure": failure,
        "driver": driver.as_dict(),
        "health": driver.health(run_id=run_id),
        "chain": {
            "raw_logs": raw_logs, "events": events,
            "blocks_scanned": blocks_scanned,
            "cursor": collector.store.cursor,
            "launches_seen": driver.launches_seen,
            "tracked_at_stop": len(collector.tracked(driver.last_ts or 0)),
            "completed_curves": len(collector.completed),
            "range_retreats": collector.range_retreats,
            "orphaned": len(collector.store.orphaned),
        },
        "requests": {
            "by_method": spent,
            "attempts": sum(v["attempts"] for v in spent.values()),
            "units": sum(v["units"] for v in spent.values()),
            "errors": sum(v["errors"] for v in spent.values()),
            "run_cap": limits.max_requests,
            "by_run": ledger.state.get("by_run", {}).get(run_id, {}),
            "wave_attempts": ledger.attempts, "wave_cap": ledger.wave_cap,
            "wave_units": ledger.units,
        },
        "wss_equivalent": {
            "subscriptions": 2,
            "log_pushes": raw_logs,
            "header_pushes": blocks_scanned,
            "total": 2 + raw_logs + blocks_scanned,
            "rule": ("docs.chainstack.com/docs/request-units: one request to "
                     "open a subscription, then one per delivered push. A logs "
                     "subscription would have pushed every log of the scanned "
                     "range and a newHeads subscription every header."),
        },
        "branches": {"live": {**(out or {}),
                              "mode": LOOP.MODE_LIVE,
                              "learning": live_cfg["learning"],
                              "status": "stopped",
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
        f"{summary['requests']['attempts']} requests "
        f"({summary['requests']['units']} units), digest "
        f"{got[:12]}… -> {out.get('end_digest', '?')[:12]}…")
    return 0

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(CONFIG))
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--runs-dir", default=str(RUNS))
    parser.add_argument("--branch", action="append", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--mode", default=LOOP.MODE_REPLAY, choices=LOOP.MODES,
                        help="REPLAY_PAPER (the default) or LIVE_PAPER")
    parser.add_argument("--stop", action="store_true",
                        help="LIVE_PAPER: write the stop flag and exit")
    parser.add_argument("--status", action="store_true",
                        help="LIVE_PAPER: print the health block. No RPC.")
    parser.add_argument("--max-seconds", type=int, default=None)
    parser.add_argument("--max-requests", type=int, default=None)
    parser.add_argument("--backfill-seconds", type=int, default=None,
                        help="LIVE_PAPER: shorten the start backfill. The "
                             "registered value is live.json's; this exists so "
                             "a smoke run can prove the path without buying "
                             "an hour of blocks first.")
    parser.add_argument("--env-file", default=DEFAULT_ENV_FILE)
    parser.add_argument("--env-key", default=DEFAULT_ENV_KEY)
    args = parser.parse_args(argv)

    t_start = time.time()
    cfg = json.loads(Path(args.config).read_text())
    live_mode = args.mode == LOOP.MODE_LIVE
    run_id = args.run_id or (json.loads(LIVE_CONFIG.read_text())["run_id"]
                             if live_mode else cfg["runs"]["id"])
    runs_dir = Path(args.runs_dir)
    (runs_dir / run_id).mkdir(parents=True, exist_ok=True)
    if live_mode and (args.stop or args.status):
        return run_live(args, cfg, print)
    logf = (runs_dir / run_id / ("worker.log" if live_mode else "run.log")).open(
        "a" if live_mode else "w")

    def log(*a, **kw):
        kw.pop("flush", None)
        stamp = time.strftime("%H:%M:%S", time.gmtime())
        print(*a, **kw)
        print(stamp, *a, file=logf)
        logf.flush()
        sys.stdout.flush()

    if live_mode:
        try:
            return run_live(args, cfg, log)
        finally:
            logf.close()

    log(f"run {run_id} starting "
        f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
    directory = verify_dataset(cfg)
    fb, mb, ann, encoder, pops, run, sha, clean = build_brain(cfg)
    log(f"graph {sha[:12]}, clean reference digest {clean[:12]}, "
        f"{len(mb.pos):,} plastic synapses, readout "
        f"{len(pops[D.AVOID])} avoid + {len(pops[D.APPROACH])} approach")
    base = RO.load_baseline(ROOT / cfg["readout"]["baseline_artifact"],
                            k=cfg["readout"]["k"], graph_sha256=sha)
    if base.theta_hz != RO.THETA_HZ_K8 or base.baseline_hz != RO.BASELINE_HZ_K8:
        raise SystemExit("the loaded baseline is not the stored artifact")
    log(f"baseline loaded exactly: BASELINE {base.baseline_hz!r}, "
        f"SD {base.sd_hz!r}, theta {base.theta_hz!r}")

    wanted = args.branch or ["learning", "frozen_reference"]
    branches = {}
    if "learning" in wanted:
        branches["learning"] = run_branch(
            name="learning", cfg=cfg, directory=directory, mb=mb, run=run,
            encoder=encoder, sha=sha, clean=clean, run_id=run_id,
            runs_dir=runs_dir, learning=LOOP.LEARN,
            restart_after=int(cfg["runs"]["restart_after_settled_episodes"]),
            log=log)
        branches["learning"]["learned_digest"] = S.learned_state_digest(
            mb.gain, mb.pos, sha)
    if "frozen_reference" in wanted:
        branches["frozen_reference"] = run_branch(
            name="frozen_reference", cfg=cfg, directory=directory, mb=mb,
            run=run, encoder=encoder, sha=sha, clean=clean, run_id=run_id,
            runs_dir=runs_dir, learning=LOOP.FROZEN, log=log)

    elapsed = time.time() - t_start
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    summary = {
        "run_id": run_id,
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t_start)),
        "elapsed_s": round(elapsed, 1),
        "peak_rss_mib": round(peak, 1),
        "python": platform.python_version(), "numpy": np.__version__,
        "machine": platform.processor() or platform.machine(),
        "config": cfg,
        "config_sha256": sha256_file(args.config),
        "plan_sha256": sha256_file(HERE / "PLAN.md"),
        "graph_sha256": sha,
        "clean_reference_digest": clean,
        "baseline": base.as_dict(),
        "encoder": encoder.as_dict(),
        "decoder": RO.decoder_k8().as_dict(),
        "readout": RO.policy_comparison().as_dict(),
        "venue": LOOP.VENUE, "chain_id": LOOP.CHAIN_ID,
        "branches": branches,
    }
    out = Path(args.out) if args.out else (runs_dir / run_id / "summary.json")
    out.write_text(json.dumps(summary, indent=1, default=str))
    log(f"run {run_id} finished in {elapsed / 60:.1f} min, peak RSS {peak:.0f} MiB")
    logf.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
