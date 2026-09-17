#!/usr/bin/env python
"""`data/pons/d11-backfill-v1` — twelve contiguous hours through the local node.

    .venv/bin/python experiments/d11/backfill.py [--dry-run]

D11-001, the owner's decision on the data and Fable addendum 6. The same
collector, the same normalisation path and the same store layout D10 used; what
changes is the transport (the verified loopback Nitro node), the ledger (its
own, in loopback scope) and the size of the window.

* **Window.** Twelve contiguous hours ending at the **confirmed head** at probe
  time: ``end_block = min(head - confirm_depth, safe)`` under the collector's
  own confirmation rule, and ``start_block`` the smallest block whose timestamp
  is at least ``timestamp(end_block) - 43,200``, found by bisection on
  timestamps. It **must not overlap** ``d10-backfill-v1`` and the run is
  refused if it would.
* **Scope.** Native-ETH v2 launches only. Every other launch is still recorded
  with ``QUOTE_UNSUPPORTED`` in its ``DISCOVERY``; it is simply not followed.
* **Initial states.** Derived offline from the recorded trades — and, declared
  before the collection, from **any** trade of the launch rather than only the
  first, the same arithmetic on the same data with no request. That is what
  ``experiments/d11/retrospective.py``'s offline tracker already does, and it
  is what keeps the pruned local node's refusal of a historical ``eth_call``
  down to the residue reported as ``initial_states_unavailable``.
* **Cap.** The registered loopback caps of ``d11_001.json``, on
  ``experiments/d11/rpc_ledger_local.json``. Cursor and ledger are persisted as
  it goes; if a cap is reached the dataset ends there and the report says so.
* **``--allow-remote`` exists so the refusal can be tested.** This wave never
  passes it and its remote request count is 0.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from flytrade.pons.budget import (BudgetStop, LOOPBACK,  # noqa: E402
                                  RequestLedger)
from flytrade.pons.collector import (CURVE_CHUNK_BLOCKS,  # noqa: E402
                                     FACTORY_CHUNK_BLOCKS, HEADER_GRID_BLOCKS,
                                     Collector, Finality, selector)
from flytrade.pons.manifest import NATIVE_QUOTE, load_manifest  # noqa: E402
from flytrade.pons.rpc import (RpcClient, RpcError,  # noqa: E402
                               read_endpoint)
from flytrade.pons.seed import (LAUNCH_SEED,  # noqa: E402
                                creator_tax_from_trade, matches_pinned_config,
                                seed_state)
from flytrade.pons.storage import ChainStore  # noqa: E402

HERE = Path(__file__).resolve().parent
D10 = ROOT / "experiments" / "d10"
CONFIG = HERE / "d11_001.json"
DATASET = ROOT / "data" / "pons" / "d11-backfill-v1"
DATASET_LABEL = "d11-backfill-v1"
ENV_FILE = HERE / "local_node.env"
ENV_KEY = "LOCAL_NITRO_RPC_HTTP"
LEDGER = HERE / "rpc_ledger_local.json"

#: addendum 6, verbatim.
WINDOW_SECONDS = 43_200
ADMISSION_MINUTES = 705
SETTLEMENT_TAIL_MINUTES = 15

#: the window d11-backfill-v1 may not touch.
D10_WINDOW = {"first_block": 60_721_229, "last_block": 60_801_426,
              "first_ts": 1_789_181_856, "last_ts": 1_789_190_005,
              "label": "d10-backfill-v1"}

#: bisection bound for the start of the window.
MAX_BISECTION_STEPS = 40


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_window(rpc, *, probe: dict, seconds: int = WINDOW_SECONDS,
                   admission_minutes: int = ADMISSION_MINUTES) -> dict:
    """The twelve-hour window, from the chain and from the registered rule.

    ``end_block`` is the confirmed head — ``min(head - confirm_depth, safe)`` —
    and ``start_block`` is the smallest block whose timestamp is at least
    ``timestamp(end_block) - seconds``, found by bisection on timestamps so the
    window is defined by **time**, not by an assumed block rate.
    """
    finality = probe["capability"]["finality"]
    interval = float(finality["median_block_interval_s"])
    depth = int(finality["confirm_depth_blocks"])
    head = rpc.block_number()
    safe = None
    if finality["safe_tag_supported"]:
        safe = int(str(rpc.block("safe")["number"]), 16)
    end_block = head - depth if safe is None else min(head - depth, safe)
    end_ts = int(str(rpc.block(end_block)["timestamp"]), 16)
    want = end_ts - int(seconds)

    def ts_of(block: int) -> int:
        return int(str(rpc.block(int(block))["timestamp"]), 16)

    lo = max(1, end_block - int(round(seconds / interval * 1.2)))
    steps = 0
    while ts_of(lo) > want and lo > 1:
        steps += 1
        if steps > 8:
            raise SystemExit("could not bracket the start of the window")
        lo = max(1, lo - int(round(seconds / interval * 0.5)))
    hi = end_block
    while hi - lo > 1:
        steps += 1
        if steps > MAX_BISECTION_STEPS:
            raise SystemExit("the window bisection did not converge")
        mid = (lo + hi) // 2
        if ts_of(mid) >= want:
            hi = mid
        else:
            lo = mid
    start_block = hi if ts_of(hi) >= want else end_block
    start_ts = ts_of(start_block)

    blocks = end_block - start_block + 1
    admission_blocks = int(round(admission_minutes * 60 / interval))
    window = {
        "rule": ("twelve contiguous hours ending at the confirmed head at "
                 "probe time; end_block = min(head - confirm_depth, safe), "
                 "start_block = the smallest block whose timestamp is at "
                 "least timestamp(end_block) - 43200"),
        "head_block": head, "safe_block": safe,
        "confirm_depth_blocks": depth,
        "first_block": start_block, "last_block": end_block,
        "safe_block_used_as_end": end_block == safe,
        "blocks": blocks,
        "first_ts": start_ts, "last_ts": end_ts,
        "seconds": end_ts - start_ts,
        "window_seconds_requested": int(seconds),
        "minutes": round((end_ts - start_ts) / 60.0, 2),
        "median_block_interval_s": interval,
        "admission_minutes": admission_minutes,
        "admission_blocks": admission_blocks,
        "admission_last_block": start_block + admission_blocks - 1,
        "settlement_tail_minutes": SETTLEMENT_TAIL_MINUTES,
        "bisection_steps": steps,
        "first_ts_utc": datetime.fromtimestamp(start_ts, timezone.utc)
                                .isoformat().replace("+00:00", "Z"),
        "last_ts_utc": datetime.fromtimestamp(end_ts, timezone.utc)
                               .isoformat().replace("+00:00", "Z"),
    }
    overlap = not (window["last_block"] < D10_WINDOW["first_block"]
                   or window["first_block"] > D10_WINDOW["last_block"])
    overlap_ts = not (window["last_ts"] < D10_WINDOW["first_ts"]
                      or window["first_ts"] > D10_WINDOW["last_ts"])
    window["overlaps_d10_backfill_v1"] = bool(overlap or overlap_ts)
    window["d10_backfill_v1"] = dict(D10_WINDOW)
    if window["overlaps_d10_backfill_v1"]:
        raise SystemExit(
            f"the window {window['first_block']}-{window['last_block']} "
            f"overlaps {D10_WINDOW['label']} "
            f"({D10_WINDOW['first_block']}-{D10_WINDOW['last_block']}): the "
            f"collection is refused rather than contaminating the baseline")
    return window


def predicted_requests(window: dict) -> dict:
    blocks = window["blocks"]
    headers = blocks // HEADER_GRID_BLOCKS + 2
    factory = -(-blocks // FACTORY_CHUNK_BLOCKS)
    curves = -(-blocks // FACTORY_CHUNK_BLOCKS) * (
        FACTORY_CHUNK_BLOCKS // CURVE_CHUNK_BLOCKS)
    return {"grid_headers": headers, "factory_getLogs": factory,
            "curve_getLogs_per_address_batch": curves,
            "note": "curve filters are multiplied by the number of address "
                    "batches (250 addresses each)"}


def derive_initial_state(record: dict, trades: list[dict]) -> dict:
    """The curve's state at launch, from the recorded trades and nothing else.

    Proven on all 546 donor calibrations (``tests/d10/test_seed.py``): for a
    native-ETH v2 launch on the pinned config, the pre-trade state is the
    pinned seed plus the creator tax, and the tax is uniquely recoverable from
    a trade's ``tax`` against its quote leg.

    **Declared before the collection (D11-001, PLAN.md §7.12).** D10 asked only
    the *first* trade and fell back to one ``eth_call`` when that one did not
    pin — three launches in 991. The local Nitro node is pruned and refuses a
    state read older than about three hours, so this asks **every** trade of
    the launch in chain order, which is the same arithmetic on the same
    recorded data with **no request at all**, and is exactly what
    ``experiments/d11/retrospective.py``'s offline tracker already does. A
    launch no trade pins is left ``unavailable`` rather than guessed, and a
    launch with no trade at all could never have been admitted.
    """
    if not matches_pinned_config(record.get("launch_config_id"),
                                 record.get("graduation_threshold")):
        return {"state": None, "source": "unavailable",
                "reason": "LAUNCH_CONFIG_NOT_PINNED"}
    if not trades:
        return {"state": None, "source": "unavailable",
                "reason": "NO_TRADE_TO_PIN_THE_CREATOR_TAX"}
    for index, trade in enumerate(trades):
        tax = creator_tax_from_trade(trade)
        if tax is not None:
            return {"state": seed_state(int(tax)),
                    "source": "derived" if index == 0 else "derived_later_trade",
                    "pinned_by_trade_index": index}
    return {"state": None, "source": "unavailable",
            "reason": "CREATOR_TAX_UNREADABLE",
            "detail": (f"none of the launch's {len(trades)} recorded trades "
                       f"pins the creator tax, and the local node is pruned: "
                       f"a historical eth_call is not available and Chainstack "
                       f"is not a fallback")}


def collect_artifacts(collector, window, summary, spent, out: Path, *,
                      started: str, elapsed: float, ledger, probe) -> dict:
    """Discovery records, derived initial states, manifest and the counts."""
    events = collector.store.live_events()
    by_curve: dict[str, list[dict]] = {}
    kinds: dict[str, int] = {}
    for event in events:
        kinds[event.get("event", "?")] = kinds.get(event.get("event", "?"), 0) + 1
        if event.get("source") == "curve":
            by_curve.setdefault(event["address"], []).append(event)

    discovery = []
    initial_states = {}
    unsupported_quote = 0
    for curve, record in sorted(collector.launches.items()):
        quote = record.get("quote_asset")
        native = quote == NATIVE_QUOTE
        reasons = []
        if not native:
            reasons.append("QUOTE_UNSUPPORTED")
            unsupported_quote += 1
        trades = [e for e in by_curve.get(curve, [])
                  if e["event"] in ("CurveBuy", "CurveSell")]
        completed = curve in collector.completed
        entry = {
            "token": record.get("token"), "curve": curve,
            "deployment": record.get("deployment"),
            "quote_asset": quote,
            "launch_block": record["launch_block"],
            "launched_at": record["launch_timestamp"],
            "launch_config_id": record.get("launch_config_id"),
            "graduation_threshold": record.get("graduation_threshold"),
            "trades_seen": len(trades),
            "curve_completed": completed,
            "in_admission_window":
                record["launch_block"] <= window["admission_last_block"],
            "reasons": reasons,
        }
        if native:
            state = derive_initial_state(record, trades)
            entry["initial_state_source"] = state["source"]
            if state.get("pinned_by_trade_index") is not None:
                entry["pinned_by_trade_index"] = state["pinned_by_trade_index"]
            if state["state"] is None:
                entry["reasons"].append(state["reason"])
            else:
                initial_states[record["token"]] = {
                    "token": record["token"], "curve": curve,
                    "launch_block": record["launch_block"],
                    "launch_block_hash": None,
                    "launched_at": record["launch_timestamp"],
                    "quote_asset": quote,
                    "snipe_start_bps": LAUNCH_SEED["snipe_start_bps"],
                    "snipe_window_seconds": LAUNCH_SEED["snipe_window_seconds"],
                    "graduation_seen": completed,
                    "state": state["state"].as_dict(),
                    "source": state["source"],
                }
        discovery.append(entry)

    (out / "discovery.json").write_text(json.dumps(discovery, indent=1) + "\n")
    (out / "initial_states.json").write_text(
        json.dumps(initial_states, indent=1, sort_keys=True) + "\n")
    if not initial_states:
        raise SystemExit("initial_states.json is empty: the offline tracker "
                         "cannot reconstruct anything and the store is refused")

    files = {}
    for name in sorted(p.name for p in out.iterdir() if p.is_file()
                       and p.name != "MANIFEST.json"):
        path = out / name
        files[name] = {"sha256": sha256_file(path), "bytes": path.stat().st_size}

    headers = len(collector.store.headers)
    raw_lines = sum(1 for _ in open(out / "raw.jsonl", encoding="utf-8")) \
        if (out / "raw.jsonl").exists() else 0
    native_launches = sum(1 for d in discovery
                          if "QUOTE_UNSUPPORTED" not in d["reasons"])
    pinned_later = sum(1 for d in discovery
                       if d.get("initial_state_source") == "derived_later_trade")
    manifest = {
        "version": "d11-backfill-manifest-1",
        "dataset": DATASET_LABEL,
        "created": started,
        "chain_id": 4663, "venue": "PONS",
        "run_id": "d11-001",
        "window": window,
        "collection": summary,
        "files": files,
        "normaliser": collector.normalise.version,
        "header_grid_blocks": HEADER_GRID_BLOCKS,
        "header_precision_s": collector.grid.precision_s,
        "request_units": spent,
        "endpoint": {
            "class": probe["requests"]["endpoint_class"],
            "host": probe["host"],
            "port": probe["verified"]["port"],
            "source": probe["verified"].get("source"),
            "image": probe["verified"].get("image"),
            "chain_id": probe["verified"]["chain_id"],
            "ledger": str(ledger.path),
            "remote_requests": 0,
        },
        "initial_states": {
            "derived_from_the_first_trade": sum(
                1 for d in discovery if d.get("initial_state_source") == "derived"),
            "derived_from_a_later_trade": pinned_later,
            "unavailable": sum(
                1 for d in discovery
                if d.get("initial_state_source") == "unavailable"),
            "from_eth_call": 0,
            "rule": ("pinned offline from any recorded trade of the launch; "
                     "the local node is pruned and no historical eth_call is "
                     "made. PLAN.md 7.12."),
        },
        "note": ("collected over HTTP through flytrade/pons/collector.py, the "
                 "same normalisation path the live driver uses, from the "
                 "verified loopback Nitro node; on-chain public data"),
    }
    counts = {
        "run": "d11-001-backfill",
        "started_utc": started,
        "elapsed_s": round(elapsed, 1),
        "window": window,
        "collection": summary,
        "blocks": window["blocks"],
        "raw_logs": raw_lines,
        "events": len(events),
        "events_by_kind": dict(sorted(kinds.items())),
        "headers_fetched": headers,
        "grid_anchors_expected": window["blocks"] // HEADER_GRID_BLOCKS + 2,
        "launches_total": len(collector.launches),
        "launches_native": native_launches,
        "launches_quote_unsupported": unsupported_quote,
        "curve_completed": len(collector.completed),
        "initial_states": manifest["initial_states"],
        "initial_states_reasons": {
            r: sum(1 for d in discovery if r in d["reasons"])
            for r in ("NO_TRADE_TO_PIN_THE_CREATOR_TAX",
                      "LAUNCH_CONFIG_NOT_PINNED", "CREATOR_TAX_UNREADABLE")},
        "request_units": spent,
        "request_attempts": sum(v["attempts"] for v in spent.values()),
        "request_units_total": sum(v["units"] for v in spent.values()),
        "loopback_attempts": sum(v["attempts"] for v in spent.values()),
        "remote_attempts": 0,
        "range_retreats": collector.range_retreats,
        "errors": sum(v["errors"] for v in spent.values()),
        "files": files,
    }
    return {"manifest": manifest, "summary": counts}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=str(ENV_FILE))
    parser.add_argument("--env-key", default=ENV_KEY)
    parser.add_argument("--ledger", default=str(LEDGER))
    parser.add_argument("--out", default=str(DATASET))
    parser.add_argument("--seconds", type=int, default=WINDOW_SECONDS)
    parser.add_argument("--admission-minutes", type=int, default=ADMISSION_MINUTES)
    parser.add_argument("--cap", type=int, default=None)
    parser.add_argument("--allow-remote", action="store_true",
                        help="the budget layer's escape hatch. Never passed by "
                             "this wave; the report states the remote count.")
    parser.add_argument("--dry-run", action="store_true",
                        help="resolve the window, print it, collect nothing")
    args = parser.parse_args(argv)

    cfg = json.loads(CONFIG.read_text())
    probe = json.loads((HERE / "node_probe.json").read_text())
    if not (probe.get("verified") or {}).get("verified"):
        raise SystemExit("experiments/d11/node_probe.json carries no verified "
                         "endpoint: run experiments/d11/probe.py first")
    caps = cfg["budget"]["projection"]["loopback_caps"]
    run_cap = int(args.cap if args.cap is not None
                  else cfg["budget"]["projection"]["per_entry_point_run_caps"]["backfill"])

    ledger = RequestLedger(args.ledger, run_id="d11-001-backfill",
                           wave_cap=int(caps["wave"]), run_cap=run_cap,
                           day_cap=int(caps["day"]), scope=LOOPBACK,
                           allow_remote=bool(args.allow_remote))
    before = json.loads(json.dumps(ledger.state))
    if ledger.halted():
        raise SystemExit(f"the ledger is halted ({ledger.halted()})")
    url = read_endpoint(args.env_file, args.env_key)
    rpc = RpcClient(url, ledger)
    chain = rpc.chain_id()
    if chain != int(cfg["chain_id"]):
        raise SystemExit(f"eth_chainId returned {chain}, not {cfg['chain_id']}")

    # Resolved once and persisted: a resume must collect the window the run
    # started on, not a later one, and the split registered in step (iii) is
    # computed from these timestamps.
    pinned = HERE / "window.json"
    if pinned.exists() and not args.dry_run:
        window = json.loads(pinned.read_text())
        print(f"window read from {pinned.name} (resolved "
              f"{window.get('resolved_at')})")
    else:
        window = resolve_window(rpc, probe=probe, seconds=args.seconds,
                                admission_minutes=args.admission_minutes)
        window["resolved_at"] = _now()
    print(json.dumps({"window": window,
                      "predicted_requests": predicted_requests(window),
                      "registered_projection":
                          cfg["budget"]["projection"]["projected_requests"],
                      "loopback_caps": caps}, indent=1))
    if args.dry_run:
        ledger.flush()
        return 0

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if not pinned.exists():
        pinned.write_text(json.dumps(window, indent=1) + "\n")

    manifest_deployments = load_manifest(D10 / "deployments.json")
    finality_json = probe["capability"]["finality"]
    finality = Finality(
        median_interval_s=float(finality_json["median_block_interval_s"]),
        confirm_depth=int(finality_json["confirm_depth_blocks"]),
        safe_tag_supported=bool(finality_json["safe_tag_supported"]),
        sample=int(finality_json["headers_sampled"]))
    store = ChainStore(out).load()
    collector = Collector(rpc, manifest_deployments, store, finality=finality,
                          track_seconds=3_600)

    t0 = time.time()
    started = _now()
    resume = (store.cursor or {}).get("block_number")
    first = window["first_block"] if resume is None else int(resume) + 1
    if resume is not None:
        print(f"resuming from block {first} (cursor on disk)")
    progress = HERE / "backfill_progress.json"

    def on_segment(top, s, c):
        done = top - window["first_block"] + 1
        payload = {"top_block": top, "blocks_done": done,
                   "blocks_total": window["blocks"],
                   "fraction": round(done / max(1, window["blocks"]), 5),
                   "events": s["events"], "launches": len(c.launches),
                   "attempts": ledger.attempts,
                   "elapsed_s": round(time.time() - t0, 1),
                   "updated": _now()}
        progress.write_text(json.dumps(payload, indent=1) + "\n")
        if s["segments"] % 10 == 0 or done >= window["blocks"]:
            print(f"  segment to {top} ({done}/{window['blocks']} blocks, "
                  f"{payload['fraction']:.1%}) events={s['events']} "
                  f"launches={len(c.launches)} attempts={ledger.attempts} "
                  f"elapsed={payload['elapsed_s']:.0f}s", flush=True)

    summary = collector.backfill_window(
        first, window["last_block"], quote_asset=NATIVE_QUOTE,
        on_segment=on_segment)
    elapsed = time.time() - t0

    after = ledger.state
    spent = {}
    for method, entry in after["by_method"].items():
        was = before["by_method"].get(method, {"attempts": 0, "units": 0,
                                               "errors": 0})
        spent[method] = {
            "attempts": entry["attempts"] - was["attempts"],
            "units": entry["units"] - was["units"],
            "errors": entry["errors"] - was["errors"]}

    report = collect_artifacts(collector, window, summary, spent, out,
                               started=started, elapsed=elapsed,
                               ledger=ledger, probe=probe)
    (out / "MANIFEST.json").write_text(json.dumps(report["manifest"], indent=1) + "\n")
    (HERE / "backfill_summary.json").write_text(
        json.dumps(report["summary"], indent=1) + "\n")
    ledger.flush()
    print(json.dumps({k: v for k, v in report["summary"].items()
                      if k not in ("files", "window")}, indent=1)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
