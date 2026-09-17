#!/usr/bin/env python
"""The product worker: one frozen fly, live paper, until it is stopped.

    start    the live-loop launcher start        (or the user service start flytrade-pons)
    stop     the live-loop launcher stop
    status   the live-loop launcher status
    tail     the live-loop launcher tail

    .venv/bin/python product/run.py            # the worker, in the foreground
    .venv/bin/python product/run.py --stop     # write the stop flag
    .venv/bin/python product/run.py --status   # print the state file. No RPC.

docs/SPEC.md P1 addenda 3-5. Every parameter is read from
``product/pons_live.json`` and from the D11 environment it points at; nothing
here chooses a number. The brain is ``brains/trader-v1`` and the run refuses to
start unless the state on disk digests to the registered value; the chain is
verified to be 4663 before anything else; and there is no wall-clock stop.

``start`` writes a pid file and refuses to run beside a live worker: one
process owns the journal, and a second would be a second fly on the same
account. ``stop`` writes a flag the worker checks at every stop point.
``status`` reads ``state.json`` and opens no socket.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import resource
import shutil
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for _p in (str(ROOT), str(ROOT / "upstream"), str(ROOT / "experiments" / "d11")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import common as C                                        # noqa: E402 (D11's)
from flytrade import decoder as D                         # noqa: E402
from flytrade import readout as RO                        # noqa: E402
from flytrade import records as REC                       # noqa: E402
from flytrade import runner as R                          # noqa: E402
from flytrade import state as S                           # noqa: E402
from flytrade.market import Universe                      # noqa: E402
from flytrade.pons import context_v2 as CTX2              # noqa: E402
from flytrade.pons import loop as LOOP                    # noqa: E402
from flytrade.pons import paper as PAPER                  # noqa: E402
from flytrade.pons.budget import (BudgetStop, RequestLedger,  # noqa: E402
                                  _atomic_write_json)
from flytrade.pons.collector import Collector, Finality   # noqa: E402
from flytrade.pons.manifest import load_manifest          # noqa: E402
from flytrade.pons.rpc import RpcClient, RpcError, read_endpoint  # noqa: E402
from flytrade.pons.storage import ChainStore              # noqa: E402
from flytrade.product import feed as FEED                 # noqa: E402
from flytrade.product import live as PL                   # noqa: E402
from flytrade.product import state as PS                  # noqa: E402

CONFIG = HERE / "pons_live.json"
DEPLOYMENTS = ROOT / "experiments" / "d10" / "deployments.json"
BRAIN = ROOT / "brains" / "trader-v1"


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def paths_of(cfg: dict, root: Path = ROOT) -> dict:
    p = cfg["paths"]
    d = root / p["directory"]
    return {"dir": d, "journal": root / p["journal"], "chain": root / p["chain"],
            "ledger": root / p["ledger"], "pid": root / p["pid"],
            "stop": root / p["stop"], "log": root / p["log"],
            "summary": root / p["summary"], "state": root / p["state"]}


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


def endpoint_url(cfg: dict, env_file: str | None, env_key: str | None) -> str:
    """The endpoint, by key name: the environment first, then the dotenv file.

    The service unit sets ``EnvironmentFile`` to the same ``.env``, so under
    systemd the value is already in the process environment; run by hand it is
    not, and the file is read the way ``d10-live-001`` read it. Either way the
    value is a secret: it is never printed, logged or written anywhere.
    """
    key = env_key or cfg["endpoint"]["env_key"]
    value = os.environ.get(key)
    if value:
        return value.strip().strip('"').strip("'")
    return read_endpoint(env_file or cfg["endpoint"]["env_file"], key)


# --------------------------------------------------------------------------
# status and stop
# --------------------------------------------------------------------------
def print_status(paths: dict, cfg: dict) -> int:
    """What ``status`` prints, from ``state.json`` alone. **No RPC.**"""
    pid = worker_alive(paths["pid"])
    print(f"run          {cfg['run_id']}  {cfg['venue']} / LIVE / PAPER / "
          f"{cfg['learning']}   brain {cfg['brain']['artifact']}")
    print(f"worker       {'alive pid ' + str(pid) if pid else 'not running'}"
          f"   (pid file {paths['pid']})")
    state = FEED.SpectacleFeed.read_state(paths["dir"])
    if not state:
        print("state        no state.json yet")
        return 0
    h = state.get("health") or {}
    a = state.get("account") or {}
    r = state.get("requests") or {}
    pos = state.get("position")
    age = int(time.time()) - int(state.get("updated_epoch") or 0)
    print(f"updated      {state.get('updated_utc')}  ({age}s ago)   "
          f"uptime {h.get('uptime_s')}s   tick {h.get('tick')}")
    print(f"brain        {h.get('brain_digest', '')[:12]}…  learning "
          f"{h.get('learning')}   (recorded, never applied)")
    print(f"account      cash {a.get('cash_eth')} ETH   realised "
          f"{a.get('realized_pnl_eth')} ETH   trades {a.get('trades')}   "
          f"unrealised {a.get('unrealised_eth')}")
    if pos:
        print(f"position     {pos.get('token')}  entry {pos.get('entry_price_eth_per_token')} "
              f"at {pos.get('entry_ts')}  age {pos.get('age_s')}s  "
              f"to horizon {pos.get('seconds_to_horizon')}s  "
              f"unrealised {pos.get('unrealised_eth')}")
    else:
        print("position     flat")
    print(f"requests     {r.get('hour')}/{r.get('hour_cap')} this hour   "
          f"total {r.get('total_attempts')} attempts / {r.get('total_units')} "
          f"units   throttled {h.get('throttled')}")
    print(f"chain        head {h.get('head_block')}  cursor {h.get('cursor_block')}  "
          f"lag {h.get('lag_blocks')} blocks  cutoff age {h.get('cutoff_age_s')}s  "
          f"tracked {h.get('tracked_curves')}  reorgs {h.get('reorgs')}")
    print(f"errors       {h.get('errors')} (retries {h.get('retries')})   "
          f"last {(h.get('last_error') or {}).get('code')}")
    sn = state.get("sniffed") or {}
    print(f"sniffed      {sn.get('candidates')} candidates over "
          f"{sn.get('ticks')} ticks   admitted {sn.get('admitted')}   "
          f"rejected {sn.get('rejected')}   episodes "
          f"{len(state.get('episodes') or [])}")
    print("last 10 events")
    for e in (state.get("events") or [])[-10:]:
        detail = {"SNIFF": lambda x: f"{x.get('considered')} considered, "
                                     f"{x.get('admitted')} admitted",
                  "PICK": lambda x: f"{x.get('token')} {x.get('action')} "
                                    f"v={x.get('valence_hz')}",
                  "HEARTBEAT": lambda x: f"req {(x.get('requests') or {}).get('hour')}"
                                         f"/h, {x.get('rss_mib')} MiB",
                  }.get(e.get("kind"), lambda x: "")(e)
        print(f"  {e.get('utc')}  {e.get('kind'):<10} {detail}")
    return 0


# --------------------------------------------------------------------------
# the worker
# --------------------------------------------------------------------------
def build(cfg: dict, *, paths: dict, log=print, env_file=None, env_key=None,
          opener=None, now=None, sleep=None):
    """Everything the loop needs, in the order the preconditions bite."""
    fixed = cfg["fixed_for_the_whole_wave"]
    cfg_v2 = json.loads((ROOT / "experiments" / "d11" / "config.json").read_text())

    ledger = RequestLedger(paths["ledger"], run_id=cfg["run_id"],
                           wave_cap=int(cfg["limits"]["ledger_caps"]["wave"]),
                           run_cap=int(cfg["limits"]["ledger_caps"]["run"]),
                           day_cap=int(cfg["limits"]["ledger_caps"]["day"]))
    if ledger.halted():
        raise SystemExit(f"the ledger is halted ({ledger.halted()}); nothing "
                         f"here may clear it or switch provider")
    client = RpcClient(endpoint_url(cfg, env_file, env_key), ledger,
                       opener=opener)

    feed = FEED.SpectacleFeed(
        paths["dir"], run_id=cfg["run_id"], now=now,
        stamp={"venue": cfg["venue"], "chain_id": cfg["chain_id"],
               "mode": cfg["mode"], "learning": cfg["learning"],
               "data": "LIVE", "execution": "PAPER"},
        keep_events=int(cfg["feed"]["keep_events_in_state"]),
        keep_episodes=int(cfg["feed"]["keep_episodes_in_state"]))
    previous = FEED.SpectacleFeed.read_state(paths["dir"]) or {}
    if previous:
        feed.resume(previous)

    # the stop file is the only way out of a retry loop until the driver
    # exists, so it is honoured from the very first request
    rpc = PL.RetryingRpc(client, now=now, sleep=sleep,
                         should_stop=lambda: Path(paths["stop"]).exists())

    # Precondition, addendum 3(a): the chain, before anything else.
    chain = rpc.chain_id()
    if chain != LOOP.CHAIN_ID:
        raise SystemExit(f"eth_chainId returned {chain}, not {LOOP.CHAIN_ID}: "
                         f"this is not Robinhood Chain and nothing runs")

    manifest = load_manifest(DEPLOYMENTS)
    settlement = cfg["settlement"]
    finality = Finality(
        median_interval_s=float(settlement["median_block_interval_s"]),
        confirm_depth=int(settlement["confirm_depth_blocks"]),
        safe_tag_supported=bool(settlement["safe_tag_supported"]), sample=3)
    store = ChainStore(paths["chain"]).load()
    collector = Collector(rpc, manifest, store, finality=finality,
                          track_seconds=int(fixed["track_seconds"]),
                          chunk_blocks=int(cfg["limits"]["tick_chunk_blocks"]))

    fb, mb, ann, encoder, pops, run, sha, clean = C.build_brain(cfg_v2)
    if clean != cfg["brain"]["state_digest"]:
        raise SystemExit("the constructed clean reference is not the brain "
                         "this configuration registers")
    base = RO.load_baseline(ROOT / "experiments" / "k8_readout" / "baseline_k8.json",
                            k=int(fixed["readout_k"]), graph_sha256=sha)
    if base.theta_hz != RO.THETA_HZ_K8 or base.baseline_hz != RO.BASELINE_HZ_K8:
        raise SystemExit("the loaded baseline is not the stored artifact")
    credit = R.CreditAssigner(mb)
    versions = REC.Versions(
        market=CTX2.VERSION, encoder=encoder.version, runner=R.VERSION,
        decoder=D.VERSION, execution=PAPER.VERSION,
        mushroom=__import__("flytrade.mushroom", fromlist=["VERSION"]).VERSION,
        graph_sha256=sha)
    paths["journal"].mkdir(parents=True, exist_ok=True)
    journal = PL.FeedJournal(paths["journal"], mb=mb, credit=credit,
                             versions=versions, feed=feed)
    journal.schema_meta = encoder.schema_metadata()
    journal.from_clean_reference = True
    journal.clean_reference_digest = clean

    first_start = not journal.checkpoint_path.exists()
    if first_start:
        shutil.copy2(BRAIN / "brain.npz", journal.checkpoint_path)
    report = journal.recover()
    digest = journal.checkpoint_digest()
    if digest != cfg["brain"]["state_digest"]:
        raise SystemExit(
            f"the learned state on disk digests to {digest[:12]}…, not the "
            f"registered {cfg['brain']['state_digest'][:12]}…: the loop is "
            f"refused rather than trading a brain nobody declared")
    journal.save_checkpoint(last_settled_episode=report["last_settled_episode"])
    log(f"[start] brain {digest[:12]}… asserted "
        f"({'copied from brains/trader-v1' if first_start else 'own checkpoint'}), "
        f"recovery `{report['action']}`, cursor {collector.cursor_block}")

    execution = PL.ProductPaperExecution(
        size_wei=int(fixed["paper_size_wei"]),
        latency_s=int(fixed["latency_seconds"]),
        horizon_s=int(fixed["horizon_seconds"]),
        gas_buy_wei=int(fixed["gas_wei"]["buy"]),
        gas_sell_wei=int(fixed["gas_wei"]["sell"]),
        gas_approval_wei=int(fixed["gas_wei"]["approval"]),
        initial_cash_wei=int(float(fixed["initial_cash_eth"]) * PAPER.WEI),
        reinforce_full_scale=float(fixed["reinforce_full_scale"]),
        reinforce_cap=float(fixed["reinforce_cap"]))
    resumed = PS.restore_into(previous, execution=execution, log=log)

    window = PL.RollingRequestWindow(
        cap=int(cfg["limits"]["hourly_request_cap"]),
        window_s=int(cfg["limits"]["window_seconds"]),
        reserve=int(cfg["limits"]["hourly_reserve"]))
    window.restore(resumed.get("request_window"))

    limits = LOOP.LiveLimits(
        max_seconds=10 ** 9,                    # never: stop_reason ignores it
        max_requests=int(cfg["limits"]["ledger_caps"]["run"]),
        reserve_requests=0,
        backfill_seconds=int(cfg["limits"]["backfill_seconds"]),
        backfill_requests=int(cfg["limits"]["backfill_requests"]),
        backfill_wall_seconds=int(cfg["limits"]["backfill_wall_seconds"]),
        stop_file=str(paths["stop"]))
    driver = PL.ProductLiveDriver(
        collector, finality=finality, limits=limits, feed=feed, window=window,
        label=cfg["run_id"], latency_s=int(fixed["latency_seconds"]),
        log=log, now=now, sleep=sleep)
    rpc._should_stop = lambda: driver.stop_reason() is not None

    def on_rpc_error(**kw):
        driver._note_error(kw.get("code", "RPC_ERROR"), kw.get("detail", ""))
        feed.emit(FEED.RPC_ERROR, tick=driver.ticks_done, **kw)
    rpc._on_error = on_rpc_error

    loop = PL.ProductLoop(
        driver=driver, run=run, mb=mb, credit=credit, journal=journal,
        encoder=encoder,
        admission=C.admission_v2(cfg_v2, require_coverage=bool(
            cfg["admission"]["require_coverage"])),
        execution=execution, policy=RO.policy_comparison(), universe=Universe(),
        mode=LOOP.MODE_LIVE, learning=LOOP.FROZEN, branch=cfg["branch"],
        run_id=cfg["run_id"], cadence=int(fixed["cadence_seconds"]),
        track_seconds=int(fixed["track_seconds"]), context_fn=CTX2.context_v2,
        feed=feed, tick_offset=int(resumed.get("tick", 0)), log=log)
    journal.loop = loop
    loop.pending = resumed.get("pending")
    counters = resumed.get("counters") or {}
    loop.credits.update(counters.get("credits") or {})
    loop.sniffed.update(counters.get("sniffed") or {})
    loop.rejected_session.update(counters.get("rejected_session") or {})
    return {"cfg": cfg, "cfg_v2": cfg_v2, "feed": feed, "rpc": rpc,
            "ledger": ledger, "collector": collector, "driver": driver,
            "journal": journal, "loop": loop, "execution": execution,
            "encoder": encoder, "graph_sha256": sha, "digest": digest,
            "recovery": report, "resumed": resumed, "baseline": base,
            "first_start": first_start, "mb": mb}


def wire_state(built: dict, *, started_at: float) -> None:
    """The state file's sections, refreshed before every write it makes."""
    loop, driver, feed = built["loop"], built["driver"], built["feed"]
    cfg = built["cfg"]

    def sections():
        cutoff = driver.last_ts or 0
        feed.update(
            brain={"artifact": cfg["brain"]["artifact"],
                   "digest": built["digest"],
                   "graph_sha256": built["graph_sha256"],
                   "input_schema_sha256": cfg["brain"]["input_schema_sha256"],
                   "plastic_synapses": int(len(built["mb"].pos)),
                   "learning": "FROZEN",
                   "asserted_at_start": True,
                   "credit_recorded_never_applied": True},
            account=PS.account_section(loop.x),
            position=PS.position_section(loop, cutoff),
            health=PS.health_section(loop, driver, started_at=started_at,
                                     brain_digest=built["digest"],
                                     rpc=built["rpc"]),
            requests=PS.requests_section(driver),
            sniffed=dict(loop.sniffed),
            rejected={"session": dict(loop.rejected_session),
                      "last_hour": loop.rejected_last_hour()},
            credits=dict(loop.credits),
            restore=PS.restore_block(loop, driver))
    feed.on_state = sections

    seen = {"episodes": 0}

    def state_hook(lp, cutoff: int):
        driver.trim()
        while seen["episodes"] < len(lp.episodes):
            episode = lp.episodes[seen["episodes"]]
            seen["episodes"] += 1
            feed.add_episode(PS.episode_row(episode, lp.last_credit))
        feed.emit(
            FEED.HEARTBEAT, tick=lp.global_tick, cutoff_ts=int(cutoff),
            uptime_s=int(time.time() - started_at),
            requests=PS.requests_section(driver),
            account=PS.account_section(lp.x),
            position=PS.position_section(lp, cutoff),
            head_block=(driver.head_track[-1]["head"]
                        if driver.head_track else None),
            cursor_block=driver.collector.cursor_block,
            cutoff_age_s=(driver.cutoff_ages[-1] if driver.cutoff_ages
                          else None),
            tracked=len(lp.tapes), launches_seen=driver.launches_seen,
            reorgs=driver.reorgs, errors=built["rpc"].errors,
            throttled=driver.throttled,
            episodes=len(lp.episodes), unresolved=len(lp.unresolved),
            pending_confirmation=(None if lp.pending is None
                                  else lp.pending.get("episode_id")),
            brain_digest=lp.journal.checkpoint_digest(),
            rss_mib=round(resource.getrusage(
                resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1))
    loop.state_hook = state_hook


def run_worker(args, cfg: dict, log) -> int:
    paths = paths_of(cfg)
    paths["dir"].mkdir(parents=True, exist_ok=True)
    alive = worker_alive(paths["pid"])
    if alive:
        raise SystemExit(f"a worker is already running (pid {alive}); one "
                         f"process owns this journal, and a second would be a "
                         f"second fly on the same account")
    paths["stop"].unlink(missing_ok=True)
    paths["pid"].write_text(f"{os.getpid()}\n")
    started = time.time()
    log(f"[start] pid {os.getpid()}  {cfg['run_id']}  {cfg['mode']} / "
        f"{cfg['learning']}  cap {cfg['limits']['hourly_request_cap']}/h "
        f"rolling, no wall-clock stop")
    built = failure = None
    out: dict = {}
    try:
        built = build(cfg, paths=paths, log=log, env_file=args.env_file,
                      env_key=args.env_key)
        wire_state(built, started_at=started)
        built["driver"].install_signal_handlers()
        out = built["loop"].run_branch()
    except (BudgetStop, RpcError) as exc:
        failure = {"code": exc.code, "detail": exc.detail}
        log(f"[stop] {exc.code}: {exc.detail}")
    finally:
        paths["pid"].unlink(missing_ok=True)
        if built is not None:
            built["ledger"].flush()
    if built is None:
        return 1

    driver, loop, ledger = built["driver"], built["loop"], built["ledger"]
    summary = {
        "version": "pons-live-summary-1",
        "run_id": cfg["run_id"], "venue": cfg["venue"],
        "chain_id": cfg["chain_id"], "mode": cfg["mode"],
        "learning": cfg["learning"],
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
        "stopped_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_s": round(time.time() - started, 1),
        "peak_rss_mib": round(
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1),
        "python": platform.python_version(), "numpy": np.__version__,
        "config_sha256": sha256_file(CONFIG),
        "brain": {"artifact": cfg["brain"]["artifact"],
                  "digest_at_start": built["digest"],
                  "digest_at_stop": loop.journal.checkpoint_digest(),
                  "unchanged": built["digest"] == loop.journal.checkpoint_digest(),
                  "manifest_sha256": sha256_file(BRAIN / "manifest.json")},
        "recovery": built["recovery"],
        "resumed": {k: v for k, v in (built["resumed"] or {}).items()
                    if k != "request_window"},
        "first_start": built["first_start"],
        "stop": {"reason": driver.stopped, "detail": driver.stop_detail},
        "failure": failure,
        "ticks_this_process": driver.ticks_done,
        "tick_at_stop": loop.global_tick,
        "driver": {k: v for k, v in driver.as_dict().items()
                   if k not in ("head_track", "lag_blocks", "lag_seconds",
                                "cutoff_ages")},
        "throttle": {"events": driver.throttle_events,
                     "seconds": round(driver.throttle_seconds, 1)},
        "rpc": built["rpc"].stats(),
        "requests": {"by_method": {k: dict(v) for k, v in
                                   (ledger.state.get("by_method") or {}).items()},
                     "attempts_total": ledger.attempts,
                     "units_total": ledger.units,
                     "this_process": ledger.run_attempts,
                     "by_run": (ledger.state.get("by_run") or {}).get(
                         cfg["run_id"], {})},
        "chain": {"raw_logs": len(built["collector"].store.seen),
                  "events": len(built["collector"].store.events),
                  "cursor": built["collector"].store.cursor,
                  "launches_seen": driver.launches_seen,
                  "reorgs": driver.reorgs,
                  "orphaned": len(built["collector"].store.orphaned),
                  "range_retreats": len(built["collector"].range_retreats)},
        "feed": {"kinds": dict(built["feed"].counts),
                 "seq": built["feed"].seq,
                 "day_file": FEED.day_file(paths["dir"], time.time()).name},
        "loop": {k: out.get(k) for k in
                 ("branch", "run_id", "mode", "learning", "ticks",
                  "start_digest", "end_digest", "digest_unchanged",
                  "tokens_discovered", "tapes", "marks", "tally", "account",
                  "credit", "wall_s")},
        "episodes": out.get("episodes", []),
        "unresolved": out.get("unresolved", []),
        "credits": dict(loop.credits),
        "sniffed": dict(loop.sniffed),
        "rejected_session": dict(loop.rejected_session),
    }
    _atomic_write_json(paths["summary"], summary)
    built["feed"].write_state()
    log(f"[stop] {driver.stopped} {driver.stop_detail}; "
        f"{driver.ticks_done} ticks this process (tick {loop.global_tick}), "
        f"{len(out.get('episodes', []))} episodes, "
        f"{ledger.run_attempts} requests, digest "
        f"{built['digest'][:12]}… -> {loop.journal.checkpoint_digest()[:12]}…")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(CONFIG))
    parser.add_argument("--stop", action="store_true",
                        help="write the stop flag and exit")
    parser.add_argument("--status", action="store_true",
                        help="print the state file. No RPC.")
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--env-key", default=None)
    args = parser.parse_args(argv)

    cfg = json.loads(Path(args.config).read_text())
    paths = paths_of(cfg)
    paths["dir"].mkdir(parents=True, exist_ok=True)
    if args.status:
        return print_status(paths, cfg)
    if args.stop:
        paths["stop"].write_text(
            f"stop requested {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n")
        pid = worker_alive(paths["pid"])
        print(f"wrote {paths['stop']}; the worker stops at its next check "
              f"({'pid ' + str(pid) if pid else 'no worker running'}). "
              f"SIGTERM is the alternative: kill -TERM {pid or '<pid>'}")
        return 0

    logf = paths["log"].open("a")

    def log(*a, **kw):
        kw.pop("flush", None)
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        print(*a, **kw)
        print(stamp, *a, file=logf)
        logf.flush()
        sys.stdout.flush()

    try:
        return run_worker(args, cfg, log)
    finally:
        logf.close()


if __name__ == "__main__":
    raise SystemExit(main())
