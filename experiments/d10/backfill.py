#!/usr/bin/env python
"""The bounded genuine backfill, `data/pons/d10-backfill-v1`.

docs/SPEC.md D10, reviewer decision 1. Dispatch 1's donor dataset covers only
the first ~62 seconds of each token, so a 15-minute horizon admits nothing on
it. This script collects a **new** window through the same collector, the same
normalisation path and the same ledger the live driver uses:

* **Window.** The 135 minutes of blocks ending at the ``safe`` block recorded
  by ``verification.json`` (60,801,426), the block count computed from
  ``finality.json``'s measured interval. Chosen by that rule and by nothing
  observed inside it. The first 120 minutes are where a launch may be
  admitted; the last 15 minutes are the settlement tail for a position opened
  at the end of minute 120.
* **Scope.** Native-ETH v2 launches only. Every other launch is still
  recorded, with ``QUOTE_UNSUPPORTED`` in its ``DISCOVERY`` record; it is
  simply not followed.
* **Chunks.** 1,000 blocks for the factory filter, 500 for the tracked-curve
  filter, halved on ``RPC_RANGE_TOO_LARGE`` down to 25 and then stopped.
* **Headers.** One per 100 blocks (the sparse grid) plus each tick's
  ``latest``; every timestamp derived between anchors is stored with
  ``interpolated: true`` and the declared precision.
* **Cap.** 3,000 requests for this collection, as the ledger's per-run cap.
  The cursor and the ledger are persisted as it goes, and if the cap is
  reached the dataset ends there and the report says so.

Usage::

    .venv/bin/python experiments/d10/backfill.py [--dry-run] [--minutes 135]

``--dry-run`` opens no socket: it prints the window arithmetic and the
predicted request count.
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

from flytrade.pons import abi  # noqa: E402
from flytrade.pons.budget import BudgetStop, RequestLedger  # noqa: E402
from flytrade.pons.collector import (CURVE_CHUNK_BLOCKS,  # noqa: E402
                                     FACTORY_CHUNK_BLOCKS, HEADER_GRID_BLOCKS,
                                     Collector, Finality)
from flytrade.pons.curve import CurveState  # noqa: E402
from flytrade.pons.manifest import NATIVE_QUOTE, load_manifest  # noqa: E402
from flytrade.pons.rpc import (DEFAULT_ENV_FILE, DEFAULT_ENV_KEY,  # noqa: E402
                               RpcClient, RpcError, mask, read_endpoint)
from flytrade.pons.seed import (LAUNCH_SEED, creator_tax_from_trade,  # noqa: E402
                                seed_state)
from flytrade.pons.storage import ChainStore  # noqa: E402

HERE = Path(__file__).resolve().parent
DATASET = ROOT / "data" / "pons" / "d10-backfill-v1"
DATASET_LABEL = "d10-backfill-v1"

#: reviewer decision 1, verbatim.
WINDOW_MINUTES = 135
ADMISSION_MINUTES = 120
REQUEST_CAP = 3_000
SAFE_BLOCK_KEY = "safe_tag"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def window_for(verification: dict, finality: dict, minutes: int,
               admission_minutes: int) -> dict:
    """The block window, computed from the recorded safe block and interval."""
    interval = float(finality["median_block_interval_s"])
    last = int(verification[SAFE_BLOCK_KEY]["detail"]["number"])
    blocks = int(round(minutes * 60 / interval))
    admission_blocks = int(round(admission_minutes * 60 / interval))
    first = last - blocks + 1
    return {
        "rule": ("the N minutes of blocks ending at the safe block recorded by "
                 "verification.json, block count from the measured interval"),
        "safe_block": last, "first_block": first, "last_block": last,
        "blocks": blocks, "minutes": minutes,
        "median_block_interval_s": interval,
        "admission_minutes": admission_minutes,
        "admission_blocks": admission_blocks,
        "admission_last_block": first + admission_blocks - 1,
        "settlement_tail_minutes": minutes - admission_minutes,
    }


def predicted_requests(window: dict) -> dict:
    blocks = window["blocks"]
    headers = blocks // HEADER_GRID_BLOCKS + 2
    factory = -(-blocks // FACTORY_CHUNK_BLOCKS)
    curves = -(-blocks // CURVE_CHUNK_BLOCKS)
    return {"grid_headers": headers, "factory_getLogs": factory,
            "curve_getLogs_per_address_batch": curves,
            "note": "curve filters are multiplied by the number of address batches"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=DEFAULT_ENV_FILE)
    parser.add_argument("--env-key", default=DEFAULT_ENV_KEY)
    parser.add_argument("--ledger", default=str(HERE / "rpc_ledger.json"))
    parser.add_argument("--out", default=str(DATASET))
    parser.add_argument("--minutes", type=int, default=WINDOW_MINUTES)
    parser.add_argument("--admission-minutes", type=int, default=ADMISSION_MINUTES)
    parser.add_argument("--cap", type=int, default=REQUEST_CAP)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    verification = json.loads((HERE / "verification.json").read_text())
    finality_json = json.loads((HERE / "finality.json").read_text())
    manifest = load_manifest(HERE / "deployments.json")
    window = window_for(verification, finality_json, args.minutes,
                        args.admission_minutes)
    print(json.dumps({"window": window,
                      "predicted_requests": predicted_requests(window)}, indent=1))
    if args.dry_run:
        return 0

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ledger = RequestLedger(args.ledger, run_id="d10-backfill", run_cap=args.cap)
    before = json.loads(json.dumps(ledger.state))
    url = read_endpoint(args.env_file, args.env_key)
    rpc = RpcClient(url, ledger)
    finality = Finality(
        median_interval_s=float(finality_json["median_block_interval_s"]),
        confirm_depth=int(finality_json["confirm_depth_blocks"]),
        safe_tag_supported=bool(finality_json["safe_tag_supported"]),
        sample=int(finality_json["headers_sampled"]))
    store = ChainStore(out).load()
    collector = Collector(rpc, manifest, store, finality=finality,
                          track_seconds=3_600)

    t0 = time.time()
    started = _now()
    resume = (store.cursor or {}).get("block_number")
    first = window["first_block"] if resume is None else int(resume) + 1
    summary = collector.backfill_window(
        first, window["last_block"], quote_asset=NATIVE_QUOTE,
        on_segment=lambda top, s, c: print(
            f"  segment to {top} ({top - window['first_block'] + 1}/"
            f"{window['blocks']} blocks) events={s['events']} "
            f"launches={len(c.launches)} attempts={ledger.attempts}", flush=True))
    elapsed = time.time() - t0

    after = ledger.state
    spent = {}
    for method, entry in after["by_method"].items():
        was = before["by_method"].get(method, {"attempts": 0, "units": 0, "errors": 0})
        spent[method] = {
            "attempts": entry["attempts"] - was["attempts"],
            "units": entry["units"] - was["units"],
            "errors": entry["errors"] - was["errors"]}

    report = collect_artifacts(collector, window, summary, spent, out,
                               started=started, elapsed=elapsed,
                               rpc=rpc, ledger=ledger)
    (out / "MANIFEST.json").write_text(json.dumps(report["manifest"], indent=1) + "\n")
    (HERE / "backfill_summary.json").write_text(
        json.dumps(report["summary"], indent=1) + "\n")
    print(json.dumps({k: v for k, v in report["summary"].items()
                      if k != "discovery_sample"}, indent=1)[:4000])
    return 0


def collect_artifacts(collector, window, summary, spent, out: Path, *,
                      started: str, elapsed: float, rpc, ledger) -> dict:
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
            state = derive_initial_state(record, trades, rpc)
            entry["initial_state_source"] = state["source"]
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

    files = {}
    for name in sorted(p.name for p in out.iterdir() if p.is_file()
                       and p.name != "MANIFEST.json"):
        path = out / name
        files[name] = {"sha256": sha256_file(path), "bytes": path.stat().st_size}

    headers = len(collector.store.headers)
    raw_lines = sum(1 for _ in open(out / "raw.jsonl", encoding="utf-8")) \
        if (out / "raw.jsonl").exists() else 0
    native_launches = sum(1 for d in discovery if not d["reasons"]
                          or d["reasons"][0] != "QUOTE_UNSUPPORTED")
    manifest = {
        "version": "d10-backfill-manifest-1",
        "dataset": DATASET_LABEL,
        "created": started,
        "chain_id": 4663, "venue": "PONS",
        "window": window,
        "collection": summary,
        "files": files,
        "normaliser": collector.normalise.version,
        "header_grid_blocks": HEADER_GRID_BLOCKS,
        "header_precision_s": collector.grid.precision_s,
        "request_units": spent,
        "note": ("collected over HTTP through flytrade/pons/collector.py, the "
                 "same normalisation path the live driver uses; on-chain public "
                 "data"),
    }
    counts = {
        "run": "d10-backfill",
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
        "initial_states_derived": sum(
            1 for d in discovery if d.get("initial_state_source") == "derived"),
        "initial_states_read": sum(
            1 for d in discovery if d.get("initial_state_source") == "eth_call"),
        "initial_states_unavailable": sum(
            1 for d in discovery if d.get("initial_state_source") == "unavailable"),
        "request_units": spent,
        "request_attempts": sum(v["attempts"] for v in spent.values()),
        "request_units_total": sum(v["units"] for v in spent.values()),
        "range_retreats": collector.range_retreats,
        "errors": sum(v["errors"] for v in spent.values()),
        "wss_equivalent": {
            "subscriptions": 2,
            "log_pushes": raw_lines,
            "header_pushes": window["blocks"],
            "total": 2 + raw_lines + window["blocks"],
            "rule": ("docs.chainstack.com/docs/request-units: one request to "
                     "open a subscription, then one per delivered push. A logs "
                     "subscription would have pushed every log and a newHeads "
                     "subscription every block header of this window."),
        },
        "files": files,
    }
    return {"manifest": manifest, "summary": counts}


def derive_initial_state(record: dict, trades: list[dict], rpc) -> dict:
    """The curve's state at launch, derived offline where that is exact.

    Proven on all 546 donor calibrations (``tests/d10/test_seed.py``): for a
    native-ETH v2 launch with ``launchConfigId`` 0 and the 4.2 ETH graduation
    threshold, the pre-trade state is the pinned seed plus the creator tax, and
    the creator tax is uniquely recoverable from the first trade's ``tax``
    against its quote leg. A launch that does not match the pinned config, or
    whose first trade does not pin the tax uniquely, falls back to one
    ``eth_call`` for ``creatorTaxBps`` at the launch block — and a launch with
    no trade at all can never be admitted (admission needs three), so it is
    left unavailable rather than paid for.
    """
    config = str(record.get("launch_config_id"))
    threshold = str(record.get("graduation_threshold"))
    if (config, threshold) != (str(LAUNCH_SEED["launch_config_id"]),
                               str(LAUNCH_SEED["graduation_threshold"])):
        return {"state": None, "source": "unavailable",
                "reason": "LAUNCH_CONFIG_NOT_PINNED"}
    tax = creator_tax_from_trade(trades[0]) if trades else None
    if tax is None:
        if not trades:
            return {"state": None, "source": "unavailable",
                    "reason": "NO_TRADE_TO_PIN_THE_CREATOR_TAX"}
        tax = read_creator_tax(rpc, record["curve"], record["launch_block"])
        if tax is None:
            return {"state": None, "source": "unavailable",
                    "reason": "CREATOR_TAX_UNREADABLE"}
        return {"state": seed_state(tax), "source": "eth_call"}
    return {"state": seed_state(tax), "source": "derived"}


def read_creator_tax(rpc, curve: str, block: int) -> int | None:
    from flytrade.pons.collector import selector
    try:
        payload = rpc.call("eth_call", [{"to": str(curve).lower(),
                                         "data": selector("creatorTaxBps()")},
                                        hex(int(block))])
    except (RpcError, BudgetStop):
        return None
    return int.from_bytes(bytes.fromhex(str(payload)[2:])[:32], "big")


if __name__ == "__main__":
    raise SystemExit(main())
