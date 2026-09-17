#!/usr/bin/env python
"""The two FROZEN loop branches with paper trading. Descriptive, never primary.

    .venv/bin/python experiments/d12/frozen.py --branch frozen_reference
    .venv/bin/python experiments/d12/frozen.py --branch frozen_school

`d11-001`'s two frozen branches, run again with the school brain in the place
of the D11 trained one: the loop over the FROZEN partition with learning off,
one position at a time, `SETTLED_FROZEN` settlements, no `LEARNING` record, and
an end digest that must equal the start digest. Their PnL and action
frequencies are **the** paper results of this wave — the school branch has none
by design, because it never opens a position.

They are **not** the primary comparison. Two loop branches cannot share rows:
while a position is held only the held token is presented and the round-robin
advances with evaluated rounds. That is what the market-only grid is for.

`frozen_reference` starts from the same clean reference on the same partition
with the same configuration as `d11-001`'s, so its episodes and its digest are
a **reuse check** on top of being a paper result.

**Nothing here opens a socket**: the driver is the recorded-window replay
driver of ``d12lib``, and no D12 script imports the live client.
"""

from __future__ import annotations

import argparse
import json
import platform
import resource
import shutil
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import d12lib as L                                        # noqa: E402
from flytrade import decoder as D                         # noqa: E402
from flytrade import readout as RO                        # noqa: E402
from flytrade import records as REC                       # noqa: E402
from flytrade import runner as R                          # noqa: E402
from flytrade.market import Universe                      # noqa: E402
from flytrade.pons import context_v2 as CTX2              # noqa: E402
from flytrade.pons import paper as PAPER                  # noqa: E402

C = L.C
LOOP = L.LOOP
BRANCHES = ("frozen_reference", "frozen_school")


def make_execution(cfg_v2: dict, cfg_run: dict) -> PAPER.PonsPaperExecution:
    fixed = cfg_run["fixed_for_the_whole_wave"]
    return PAPER.PonsPaperExecution(
        size_wei=int(fixed["paper_size_wei"]),
        latency_s=int(fixed["latency_seconds"]),
        horizon_s=int(fixed["horizon_seconds"]),
        initial_cash_wei=int(float(fixed["initial_cash_eth"]) * PAPER.WEI),
        reinforce_full_scale=PAPER.reinforce_full_scale_from_config(cfg_v2),
        reinforce_cap=float(fixed["reinforce_cap"]),
        **C.gas_constants(cfg_run))


def run_branch(name: str, *, run_dir: Path, from_checkpoint: Path | None,
               log=print) -> dict:
    cfg_v2, cfg_run = L.configs()
    sp = L.split()
    directory = L.verify_dataset()
    fb, mb, ann, encoder, pops, run, sha, clean = C.build_brain(cfg_v2)
    mb.gain[:] = np.ones(len(mb.pos), dtype=np.float32)
    mb.trace[:] = 0.0
    mb.trace_episode[:] = -1
    mb.apply()

    driver = L.PartitionReplayDriver(
        directory, finality=L.finality(),
        first_tick=int(sp["frozen_first_tick"]),
        last_tick=int(sp["frozen_last_tick"]), anchor_ts=int(sp["t0"]))
    store = run_dir / name
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
        log(f"[{name}] learned state from {from_checkpoint}, digest "
            f"{start_from[:12]}, recovery `{report['action']}`")
    journal.save_checkpoint(last_settled_episode=-1)

    loop = LOOP.PonsLoop(
        driver=driver, run=run, mb=mb, credit=credit, journal=journal,
        encoder=encoder, admission=C.admission_v2(cfg_v2,
                                                  require_coverage=True),
        execution=make_execution(cfg_v2, cfg_run), policy=RO.policy_comparison(),
        universe=Universe(), mode=LOOP.MODE_REPLAY, learning=LOOP.FROZEN,
        branch=name, run_id=L.RUN_ID,
        cadence=int(cfg_run["fixed_for_the_whole_wave"]["cadence_seconds"]),
        track_seconds=int(cfg_v2["admission"]["track_seconds"]),
        context_fn=CTX2.context_v2, entry_deadline_ts=int(sp["t1"]), log=log)
    log(f"[{name}] {driver.as_dict()['events']:,} events, "
        f"{sp['frozen_ticks']:,} ticks, learning=FROZEN")
    out = loop.run_branch()
    out["clean_reference_digest"] = clean
    out["starts_from_digest"] = start_from
    out["dataset"] = driver.as_dict()
    out["log_sha256"] = L.sha256_file(journal.log.path)
    out["partition"] = {"first_tick": driver.first_tick,
                        "last_tick": driver.last_tick,
                        "ticks": sp["frozen_ticks"]}
    out["position_open_at_end"] = loop.x.account.position is not None
    if not out["digest_unchanged"]:
        raise SystemExit(f"[{name}] a frozen branch moved the learned state: "
                         f"{out['start_digest'][:12]} -> "
                         f"{out['end_digest'][:12]}")
    log(f"[{name}] done in {out['wall_s']}s: {len(out['episodes'])} episodes, "
        f"digest {out['start_digest'][:12]} unchanged")
    return out


def paper_results(branch: dict) -> dict:
    """Trades, gross, costs, net, holds, unresolved. Descriptive, never primary."""
    episodes = branch.get("episodes") or []
    account = branch.get("account") or {}
    holds = [e["seconds_held"] for e in episodes if e.get("seconds_held")]
    nets = [e["net_pnl"] for e in episodes if e.get("net_pnl") is not None]
    return {
        "episodes": len(episodes),
        "settled_frozen": sum(1 for e in episodes
                              if e.get("settlement") == "SETTLED_FROZEN"),
        "gross_pnl_eth": sum(e.get("gross_pnl", 0.0) for e in episodes),
        "fees_eth": sum(e.get("fees_eth", 0.0) for e in episodes),
        "slippage_eth": sum(e.get("slippage_eth", 0.0) for e in episodes),
        "net_pnl_eth": sum(nets),
        "realized_pnl_eth": account.get("realized_pnl"),
        "trades": account.get("trades"),
        "wins": sum(1 for v in nets if v > 0),
        "holding_seconds": {"min": min(holds) if holds else None,
                            "max": max(holds) if holds else None,
                            "median": float(np.median(holds)) if holds else None},
        "unresolved_count": len(branch.get("unresolved") or []),
        "marks": branch.get("marks"),
        "per_round_action": (branch.get("tally") or {}).get(
            "per_decision_round", {}).get("action", {}),
        "per_candidate_action": (branch.get("tally") or {}).get(
            "per_candidate_evaluation", {}).get("action", {}),
        "after_execution": (branch.get("tally") or {}).get(
            "after_execution_constraints", {}),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", default=str(L.RUNS))
    parser.add_argument("--branch", action="append", default=None,
                        choices=list(BRANCHES))
    parser.add_argument("--school-checkpoint", default=None)
    args = parser.parse_args(argv)

    run_dir = Path(args.runs_dir) / L.RUN_ID
    run_dir.mkdir(parents=True, exist_ok=True)
    logf = (run_dir / "frozen.log").open("a")

    def log(*a, **kw):
        kw.pop("flush", None)
        print(*a, **kw)
        print(time.strftime("%H:%M:%S", time.gmtime()), *a, file=logf)
        logf.flush()
        sys.stdout.flush()

    path = run_dir / "frozen_summary.json"
    summary = json.loads(path.read_text()) if path.exists() else {
        "version": "d12-001-frozen-1", "run_id": L.RUN_ID,
        "python": platform.python_version(), "numpy": np.__version__,
        "branches": {}}
    for name in (args.branch or list(BRANCHES)):
        checkpoint = None
        if name == "frozen_school":
            checkpoint = Path(args.school_checkpoint or
                              (run_dir / "school" / "brain.npz"))
            if not checkpoint.exists():
                raise SystemExit(f"{checkpoint} is absent: frozen_school "
                                 f"starts from the school's final checkpoint")
        out = run_branch(name, run_dir=run_dir, from_checkpoint=checkpoint,
                         log=log)
        out["paper"] = paper_results(out)
        summary["branches"][name] = out
        summary["peak_rss_mib"] = round(
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1)
        L.atomic_write_json(path, summary)
    logf.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
