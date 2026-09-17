#!/usr/bin/env python
"""Import the donor's raw PONS evidence into a replay dataset. Zero RPC.

docs/SPEC.md D10 addendum 8. The owner's private Pons radar
(``~/Documentos/PONS``) already collected, hash-anchored to a known head, the
raw factory and curve logs for two one-hour launch windows. This script reads
that evidence **read-only**, checks its internal consistency, pushes every raw
log through the *same* :class:`flytrade.pons.collector.Normaliser` the live
collector uses, and writes ``data/pons/d10-replay-v1/``.

It costs zero requests by construction: nothing here opens a socket.

What is imported
----------------
* every ``TokenLaunched`` in both windows — **1,136 launches, not the 546
  survivors** — so the dataset carries the ones with an unsupported quote
  asset and the ones that never traded, exactly as amendment section 7 asks;
* the curve logs of the 546 native-ETH launches, with their block headers;
* the calibrated launch-block curve state per native token, and the donor's
  later state read per token, which is what the reconstruction is checked
  against.

What is deliberately **not** imported: any outcome, label, PnL, return or
post-cutoff quantity the donor computed. This script reads launches, logs,
headers and state reads and nothing else.

Usage::

    .venv/bin/python experiments/d10/import_donor.py [--donor DIR] [--out DIR]
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from flytrade.pons.collector import Normaliser  # noqa: E402
from flytrade.pons.curve import (  # noqa: E402
    CurveReconstruction, CurveState, ReconstructionError)
from flytrade.pons.manifest import NATIVE_QUOTE, load_manifest  # noqa: E402
from flytrade.pons.storage import log_id, order_key  # noqa: E402

DATASET = "d10-replay-v1"
DONOR = Path.home() / "Documentos" / "PONS"
MANIFEST_PATH = ROOT / "experiments" / "d10" / "deployments.json"


def sha256_file(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hexint(value) -> int:
    text = str(value)
    return int(text, 16) if text.startswith("0x") else int(text)


def _header(payload: dict) -> dict:
    return {"number": _hexint(payload["number"]),
            "hash": str(payload["hash"]).lower(),
            "parentHash": str(payload["parentHash"]).lower(),
            "timestamp": _hexint(payload["timestamp"])}


class Problem(RuntimeError):
    pass


# --------------------------------------------------------------------------
# Reading the donor, read-only
# --------------------------------------------------------------------------
def read_windows(donor: Path) -> list[dict]:
    """The two launch windows, their block bounds and their full launch census."""
    windows = []
    for label, cohort, features in (
            ("2026-09-08", "micro-cohort/day-2026-09-08.json", "micro-features"),
            ("2026-09-09", "micro-cohort-day9/day-2026-09-09.json",
             "micro-features-day9")):
        day = json.loads((donor / "artifacts" / cohort).read_text())
        rows = {}
        for path in sorted(glob.glob(str(donor / "artifacts" / features / "batch-*.json"))):
            batch = json.loads(Path(path).read_text())
            for row in batch["rows"]:
                rows[str(row["subject"]["token"]).lower()] = {
                    "token": str(row["subject"]["token"]).lower(),
                    "quote": str(row["subject"]["quote"]).lower(),
                    "curve": str(row["market"]["address"]).lower(),
                    "launch": row["subject"]["launch"],
                    "launch_header": _header(row["launchHeader"]),
                    "launched_at": int(row["launched"]),
                }
        census = {str(r["token"]).lower() for r in day["rows"]}
        missing = census - set(rows)
        if missing:
            raise Problem(f"{label}: {len(missing)} launches without a launch header")
        windows.append({
            "label": label,
            "start": day["window"]["start"],
            "end": day["window"]["end"],
            "from_block": int(day["fromBlock"]),
            "launch_end_exclusive": int(day["launchEndExclusive"]),
            "follow_end_block": int(day["followEndBlock"]),
            "launches": [rows[t] for t in sorted(census)],
            "sources": [str(donor / "artifacts" / cohort)] + sorted(
                glob.glob(str(donor / "artifacts" / features / "batch-*.json"))),
        })
    return windows


def read_simulation(donor: Path) -> dict:
    """The curve-event batches, their headers, their calibrations, the plan."""
    base = donor / "artifacts" / "curve-simulation"
    plan = json.loads((base / "plan.json").read_text())
    head_hash = str(plan["head"]["hash"]).lower()
    batches = sorted(glob.glob(str(base / "batch-*.json")),
                     key=lambda p: int(Path(p).stem.split("-")[1]))
    events: list[dict] = []
    headers: dict[str, dict] = {}
    calibrations: dict[str, dict] = {}
    ranges: list[dict] = []
    sources = [str(base / "plan.json")]
    for path in batches:
        batch = json.loads(Path(path).read_text())
        if str(batch["headHash"]).lower() != head_hash:
            raise Problem(f"{path}: headHash differs from plan.json")
        sources.append(path)
        for entry in batch["events"]:
            events.append(entry)
        for header in batch["headers"]:
            parsed = _header(header["payload"])
            headers[parsed["hash"]] = parsed
        for calibration in batch["calibrations"]:
            token = str(calibration["token"]).lower()
            calibrations[token] = {
                "block": _header(calibration["block"]["payload"]),
                "state": calibration["state"],
            }
        for entry in batch["ranges"]:
            ranges.append({"addresses": [a.lower() for a in entry["params"][0]],
                           "from_block": int(entry["params"][1]),
                           "to_block": int(entry["params"][2]),
                           "payload_count": len(entry["payload"])})
    initials: dict[str, dict] = {}
    for token in plan["tokens"]:
        token = str(token).lower()
        path = base / f"initial-{token}.json"
        raw = json.loads(path.read_text())
        initials[token] = raw
        sources.append(str(path))
    return {"plan": plan, "head_hash": head_hash, "events": events,
            "headers": headers, "calibrations": calibrations,
            "ranges": ranges, "initials": initials, "sources": sources}


# --------------------------------------------------------------------------
# Consistency (addendum 8)
# --------------------------------------------------------------------------
def check_consistency(sim: dict, windows: list[dict]) -> dict:
    checks: dict[str, dict] = {}

    ids = [log_id(e["raw"]) for e in sim["events"]]
    duplicates = len(ids) - len(set(ids))
    checks["unique_log_ids"] = {
        "checked": len(ids), "duplicates": duplicates, "ok": duplicates == 0}

    missing_headers = {e["raw"]["blockHash"].lower() for e in sim["events"]
                       } - set(sim["headers"])
    checks["every_event_block_hash_has_a_header"] = {
        "checked": len(ids), "missing": len(missing_headers),
        "ok": not missing_headers}

    tokens = {str(t).lower() for t in sim["plan"]["tokens"]}
    missing_cal = tokens - set(sim["calibrations"])
    missing_init = tokens - set(sim["initials"])
    checks["every_token_has_a_calibration"] = {
        "checked": len(tokens), "missing": len(missing_cal), "ok": not missing_cal}
    checks["every_token_has_an_initial_state"] = {
        "checked": len(tokens), "missing": len(missing_init), "ok": not missing_init}

    # Every event must fall inside one of the ranges that were actually asked
    # for, at an address that range asked about. A log outside its own filter
    # is the failure the donor's client refuses; the same refusal here.
    covered = 0
    for event in sim["events"]:
        number = _hexint(event["raw"]["blockNumber"])
        address = str(event["raw"]["address"]).lower()
        if any(r["from_block"] <= number <= r["to_block"] and address in r["addresses"]
               for r in sim["ranges"]):
            covered += 1
    checks["events_inside_a_requested_range"] = {
        "checked": len(ids), "covered": covered, "ok": covered == len(ids)}

    heads = {sim["head_hash"]}
    checks["head_hash_consistent_across_batches"] = {
        "checked": len(sim["sources"]), "distinct": len(heads), "ok": len(heads) == 1}

    native = sum(1 for w in windows for l in w["launches"] if l["quote"] == NATIVE_QUOTE)
    checks["native_launches_match_the_plan"] = {
        "census_native": native, "plan_tokens": len(tokens),
        "ok": native == len(tokens)}

    removed = sum(1 for e in sim["events"] if e["raw"].get("removed"))
    checks["no_removed_logs_in_the_archive"] = {
        "removed": removed, "ok": removed == 0}
    return checks


# --------------------------------------------------------------------------
# Reconstruction (addendum 8)
# --------------------------------------------------------------------------
def initial_state(raw: dict) -> tuple[CurveState, dict]:
    init = raw["initial"]
    reserves = init["getReserves"]
    state = CurveState(
        quote_reserve=int(reserves[0]), token_reserve=int(reserves[1]),
        real_quote_reserve=int(init["realQuoteReserve"]),
        sellable_tokens=int(init["sellableTokens"]),
        fee_bps=int(init["feeBps"]), creator_tax_bps=int(init["creatorTaxBps"]),
        snipe_tax_bps=0, graduated=bool(init["graduated"]))
    meta = {
        "token": str(init["token"]).lower(),
        "curve": str(raw["market"]["address"]).lower(),
        "quote_asset": str(raw["market"]["quote"]).lower(),
        "launch_block": _hexint(raw["launchHeader"]["number"]),
        "launch_block_hash": str(raw["launchHeader"]["hash"]).lower(),
        "launched_at": int(raw["launched"]),
        "snipe_start_bps": int(init["snipeTaxStartBps"]),
        "snipe_window_seconds": int(init["snipeTaxSeconds"]),
        "period": raw["subject"]["period"],
        "graduation_seen": raw["subject"]["graduation"] is not None,
    }
    return state, meta


def replay_trades(events_by_curve: dict, initials: dict,
                  calibrations: dict) -> dict:
    """Re-price every settled ``CurveBuy`` / ``CurveSell`` from the state before it.

    This is the amendment's "validate sampled calculations against known
    settled trade evidence", done on all of them rather than a sample. For a
    buy the check is four numbers at once — what was spent, the fee the log
    reports (base **plus** snipe), the creator tax and the tokens delivered —
    recomputed from the reconstructed pre-trade reserves and the snipe tax the
    decay formula says a non-exempt recipient owed at that block's timestamp.

    A buy whose recipient was exempted at launch pays no snipe tax while the
    formula says it should; those are counted separately rather than excused,
    and the ``SnipeTaxCharged`` log in the same transaction is what tells the
    two apart. Where that log is present its **amount** is checked against the
    formula, which is how the fourteen-halvings decay is validated on real
    settled evidence rather than on a fixture.
    """
    from flytrade.pons.curve import (QuoteError, quote_curve_buy,
                                     quote_curve_sell, snipe_tax_bps)

    out = {"buys": 0, "buys_ok": 0, "sells": 0, "sells_ok": 0,
           "snipe_taxed_buys": 0, "snipe_amount_ok": 0, "snipe_exempt_buys": 0,
           "partial_fill_buys": 0, "quote_errors": 0, "failures": []}
    for token, raw in sorted(initials.items()):
        state, meta = initial_state(raw)
        recon = CurveReconstruction(
            state, launch_block=meta["launch_block"],
            launched_at=meta["launched_at"],
            snipe_start_bps=meta["snipe_start_bps"],
            snipe_window_seconds=meta["snipe_window_seconds"],
            token=token, curve=meta["curve"])
        stream = sorted(events_by_curve.get(meta["curve"], []),
                        key=lambda e: (e["block_number"], e["tx_index"], e["log_index"]))
        applicable = [e for e in stream if e["block_number"] > meta["launch_block"]]
        charged = {}
        for event in applicable:
            if event["event"] == "SnipeTaxCharged":
                charged.setdefault(event["tx_hash"], []).append(
                    int(event["args"]["amount"]))
        try:
            for event in applicable:
                kind = event["event"]
                if kind not in ("CurveBuy", "CurveSell"):
                    recon.apply(event)
                    continue
                before = recon.state
                args = event["args"]
                age = event["block_timestamp"] - meta["launched_at"]
                if kind == "CurveBuy":
                    out["buys"] += 1
                    formula = snipe_tax_bps(meta["snipe_start_bps"],
                                            meta["snipe_window_seconds"], max(0, age))
                    taxed = charged.get(event["tx_hash"])
                    if formula and not taxed:
                        out["snipe_exempt_buys"] += 1
                        effective = 0
                    else:
                        effective = formula
                    try:
                        quote = quote_curve_buy(before.with_snipe(effective),
                                                int(args["quoteIn"]))
                    except QuoteError:
                        out["quote_errors"] += 1
                        recon.apply(event)
                        continue
                    if quote.refund:
                        out["partial_fill_buys"] += 1
                    ok = (quote.spent == int(args["quoteIn"])
                          and quote.emitted_fee == int(args["fee"])
                          and quote.fee_creator == int(args["tax"])
                          and quote.tokens_out == int(args["tokensOut"]))
                    if ok:
                        out["buys_ok"] += 1
                    elif len(out["failures"]) < 20:
                        out["failures"].append({
                            "token": token, "kind": kind,
                            "log_id": event["log_id"],
                            "spent": [quote.spent, int(args["quoteIn"])],
                            "fee": [quote.emitted_fee, int(args["fee"])],
                            "tax": [quote.fee_creator, int(args["tax"])],
                            "tokens_out": [quote.tokens_out, int(args["tokensOut"])]})
                    if effective and taxed:
                        out["snipe_taxed_buys"] += 1
                        if quote.fee_snipe in taxed:
                            out["snipe_amount_ok"] += 1
                else:
                    out["sells"] += 1
                    try:
                        quote = quote_curve_sell(before, int(args["tokensIn"]))
                    except QuoteError:
                        out["quote_errors"] += 1
                        recon.apply(event)
                        continue
                    ok = (quote.quote_out == int(args["quoteOut"])
                          and quote.fee_base == int(args["fee"])
                          and quote.fee_creator == int(args["tax"]))
                    if ok:
                        out["sells_ok"] += 1
                    elif len(out["failures"]) < 20:
                        out["failures"].append({
                            "token": token, "kind": kind,
                            "log_id": event["log_id"],
                            "quote_out": [quote.quote_out, int(args["quoteOut"])],
                            "fee": [quote.fee_base, int(args["fee"])],
                            "tax": [quote.fee_creator, int(args["tax"])]})
                recon.apply(event)
        except ReconstructionError:
            continue
    return out


def reconstruct(events_by_curve: dict, initials: dict, calibrations: dict) -> dict:
    """Replay every native curve and reconcile it with the donor's state read."""
    reconciled = 0
    mismatched: list[dict] = []
    failed: list[dict] = []
    coverage: dict[str, dict] = {}
    for token, raw in sorted(initials.items()):
        state, meta = initial_state(raw)
        recon = CurveReconstruction(
            state, launch_block=meta["launch_block"],
            launched_at=meta["launched_at"],
            snipe_start_bps=meta["snipe_start_bps"],
            snipe_window_seconds=meta["snipe_window_seconds"],
            token=token, curve=meta["curve"])
        stream = sorted(events_by_curve.get(meta["curve"], []),
                        key=lambda e: (e["block_number"], e["tx_index"], e["log_index"]))
        # The calibrated state is read *at the launch block*, so it already
        # contains that block's own events; replaying them would double count.
        applicable = [e for e in stream if e["block_number"] > meta["launch_block"]]
        calibration = calibrations.get(token)
        target = calibration["block"]["number"] if calibration else None
        try:
            for event in applicable:
                if target is not None and event["block_number"] > target:
                    break
                recon.apply(event)
        except ReconstructionError as exc:
            failed.append({"token": token, "code": exc.code, "detail": exc.detail})
            continue
        if calibration is not None:
            want = calibration["state"]
            got = recon.state
            deltas = {
                "quote_reserve": got.quote_reserve - int(want["getReserves"][0]),
                "token_reserve": got.token_reserve - int(want["getReserves"][1]),
                "real_quote_reserve": got.real_quote_reserve - int(want["realQuoteReserve"]),
                "sellable_tokens": got.sellable_tokens - int(want["sellableTokens"]),
            }
            if any(deltas.values()) or got.graduated != bool(want["graduated"]):
                mismatched.append({"token": token, "deltas": deltas,
                                   "graduated": [got.graduated, want["graduated"]]})
            else:
                reconciled += 1
        blocks = [e["block_number"] for e in stream]
        times = [e["block_timestamp"] for e in stream]
        coverage[token] = {
            "curve": meta["curve"],
            "period": meta["period"],
            "launch_block": meta["launch_block"],
            "launched_at": meta["launched_at"],
            "events": len(stream),
            "trades": sum(1 for e in stream if e["event"] in ("CurveBuy", "CurveSell")),
            "first_block": min(blocks) if blocks else None,
            "last_block": max(blocks) if blocks else None,
            "last_event_age_s": (max(times) - meta["launched_at"]) if times else None,
            "calibration_block": target,
            "completed": recon.completed_at is not None,
        }
    return {"reconciled": reconciled, "mismatched": mismatched, "failed": failed,
            "coverage": coverage, "tokens": len(initials)}


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------
def write_jsonl(path: Path, records) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, sort_keys=True))
            fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    return sha256_file(path)


def write_json(path: Path, payload) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    return sha256_file(path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--donor", default=str(DONOR))
    parser.add_argument("--out", default=str(ROOT / "data" / "pons" / DATASET))
    parser.add_argument("--report", default=str(ROOT / "experiments" / "d10" /
                                                "dataset_report.json"))
    args = parser.parse_args(argv)
    donor = Path(args.donor)
    out = Path(args.out)

    manifest = load_manifest(MANIFEST_PATH)
    windows = read_windows(donor)
    sim = read_simulation(donor)
    checks = check_consistency(sim, windows)

    # ---- normalise every launch through the one path --------------------
    normaliser = Normaliser(manifest)
    headers: dict[str, dict] = dict(sim["headers"])
    raw_records: list[dict] = []
    launch_events: list[dict] = []
    for window in windows:
        for launch in window["launches"]:
            header = launch["launch_header"]
            headers[header["hash"]] = header
            raw = launch["launch"]
            raw_records.append({"log_id": log_id(raw), "source": "factory",
                                "window": window["label"], "log": raw})
            launch_events.append(normaliser.normalise(
                raw, {"number": hex(header["number"]), "hash": header["hash"],
                      "parentHash": header["parentHash"],
                      "timestamp": hex(header["timestamp"])}))
    for event in launch_events:
        if event["event"] == "TokenLaunched":
            normaliser.register_market(event["curve"], {
                "token": event["token"], "deployment": event["deployment"]})

    # ---- normalise every curve log through the same path ----------------
    curve_events: list[dict] = []
    for entry in sorted(sim["events"], key=lambda e: order_key(e["raw"])):
        raw = entry["raw"]
        header = headers[str(raw["blockHash"]).lower()]
        raw_records.append({"log_id": log_id(raw), "source": "curve",
                            "window": None, "log": raw})
        curve_events.append(normaliser.normalise(
            raw, {"number": hex(header["number"]), "hash": header["hash"],
                  "parentHash": header["parentHash"],
                  "timestamp": hex(header["timestamp"])}))

    events = sorted(launch_events + curve_events,
                    key=lambda e: (e["block_number"], e["tx_index"], e["log_index"]))
    events_by_curve: dict[str, list[dict]] = {}
    for event in curve_events:
        events_by_curve.setdefault(event["address"], []).append(event)

    recon = reconstruct(events_by_curve, sim["initials"], sim["calibrations"])
    trades = replay_trades(events_by_curve, sim["initials"], sim["calibrations"])

    initial_states = {}
    for token, raw in sorted(sim["initials"].items()):
        state, meta = initial_state(raw)
        calibration = sim["calibrations"].get(token)
        initial_states[token] = {
            "state": state.as_dict(), **meta,
            "calibration": None if calibration is None else {
                "block": calibration["block"]["number"],
                "block_hash": calibration["block"]["hash"],
                "state": calibration["state"]},
        }

    discovery = []
    for window in windows:
        for launch in window["launches"]:
            native = launch["quote"] == NATIVE_QUOTE
            discovery.append({
                "token": launch["token"], "curve": launch["curve"],
                "quote_asset": launch["quote"], "window": window["label"],
                "launch_block": launch["launch_header"]["number"],
                "launched_at": launch["launched_at"],
                "in_replay_dataset": native and launch["token"] in sim["initials"],
                "reason": None if native else "QUOTE_UNSUPPORTED",
            })

    digests = {
        "raw.jsonl": write_jsonl(out / "raw.jsonl", raw_records),
        "events.jsonl": write_jsonl(out / "events.jsonl", events),
        "headers.jsonl": write_jsonl(
            out / "headers.jsonl",
            sorted(headers.values(), key=lambda h: (h["number"], h["hash"]))),
        "initial_states.json": write_json(out / "initial_states.json", initial_states),
        "discovery.json": write_json(out / "discovery.json", discovery),
    }
    sources = {}
    for path in sim["sources"] + [p for w in windows for p in w["sources"]]:
        sources[str(Path(path).relative_to(donor))] = sha256_file(path)

    manifest_payload = {
        "dataset": DATASET,
        "created_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "chain_id": manifest.chain_id,
        "venue": "PONS",
        "deployment": manifest.factory.id,
        "factory": manifest.factory.address,
        "normaliser": normaliser.version,
        "rpc_requests": 0,
        "donor_root": str(donor),
        "donor_head": sim["plan"]["head"],
        "windows": [{k: w[k] for k in ("label", "start", "end", "from_block",
                                       "launch_end_exclusive", "follow_end_block")}
                    for w in windows],
        "counts": {
            "launches_total": len(discovery),
            "launches_native_eth": sum(1 for d in discovery if d["reason"] is None),
            "launches_quote_unsupported": sum(1 for d in discovery
                                              if d["reason"] == "QUOTE_UNSUPPORTED"),
            "curve_events": len(curve_events),
            "events_total": len(events),
            "headers": len(headers),
            "tokens_with_initial_state": len(initial_states),
        },
        "consistency": checks,
        "reconstruction": {
            "tokens": recon["tokens"], "reconciled": recon["reconciled"],
            "mismatched": len(recon["mismatched"]), "failed": len(recon["failed"])},
        "settled_trade_replay": {k: v for k, v in trades.items() if k != "failures"},
        "outputs": digests,
        "sources": sources,
        "licence": ("public on-chain data; the donor artifacts are the owner's own. "
                    "No Kibot or other licensed market data is involved."),
    }
    digests["MANIFEST.json"] = write_json(out / "MANIFEST.json", manifest_payload)

    report = {
        "manifest": manifest_payload,
        "coverage": recon["coverage"],
        "mismatched": recon["mismatched"][:20],
        "failed": recon["failed"][:20],
        "trade_failures": trades["failures"],
        "discovery_counts_by_window": {
            w["label"]: {
                "launches": sum(1 for d in discovery if d["window"] == w["label"]),
                "native": sum(1 for d in discovery
                              if d["window"] == w["label"] and d["reason"] is None),
                "quote_unsupported": sum(
                    1 for d in discovery if d["window"] == w["label"]
                    and d["reason"] == "QUOTE_UNSUPPORTED")}
            for w in windows},
    }
    write_json(Path(args.report), report)
    print(json.dumps({k: manifest_payload[k]
                      for k in ("counts", "reconstruction", "settled_trade_replay")},
                     indent=1))
    print("dataset:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
