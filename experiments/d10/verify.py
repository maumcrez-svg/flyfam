#!/usr/bin/env python
"""Verify the configured endpoint really is Robinhood Chain, in <= 20 requests.

docs/SPEC.md D10 addendum 3. Nothing else in this wave is allowed to open a
socket until this has run and been read. It answers six questions and writes
them to ``experiments/d10/verification.json`` with the endpoint masked:

1. **Is this chain 4663?** ``eth_chainId``. If not, no collection happens.
2. **Is the v2 factory the contract we pinned?** ``eth_getCode`` and
   ``keccak256`` against the donor's expected hash.
3. **And the v1 factory?** Recorded for the same reason, and still UNSUPPORTED.
4. **How fast are blocks?** Measured from sampled headers, never remembered,
   because ``confirm_depth`` is derived from it (addendum 7).
5. **Does the endpoint answer the ``safe`` tag?** A probe, recorded either way.
6. **What is the launch rate right now?** One bounded ``eth_getLogs`` over
   roughly the last hour of the factory's ``TokenLaunched``. The v2
   documentation says "public launches are closed, so only whitelisted
   addresses can create a token for now"; this puts a measured number beside
   that sentence instead of an assumption in either direction.

A single error ends the network part with no retry — the donor saw
``RPC_ERROR_-32000`` on 2026-09-09 with an unconfirmed cause — and the offline
half of the wave (the replay dataset) does not depend on any of this.

Usage::

    .venv/bin/python experiments/d10/verify.py [--env-file F] [--env-key K]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from flytrade.pons.budget import BudgetStop, RequestLedger  # noqa: E402
from flytrade.pons.collector import measure_finality  # noqa: E402
from flytrade.pons.abi import V2_FACTORY_EVENTS  # noqa: E402
from flytrade.pons.manifest import load_manifest  # noqa: E402
from flytrade.pons.rpc import (DEFAULT_ENV_FILE, DEFAULT_ENV_KEY, MASK,  # noqa: E402
                               RpcClient, RpcError, keccak256_hex, mask,
                               read_endpoint)

HERE = Path(__file__).resolve().parent
MAX_REQUESTS = 20
LAUNCH_RATE_SECONDS = 3_600
MAX_LOG_CHUNKS = 3
INTERVAL_SAMPLE_BLOCKS = 2_000
#: Upper bound on the span one ``eth_getLogs`` may ask for. Robinhood Chain
#: runs at roughly ten blocks a second, so "the last hour" is ~36,000 blocks
#: and a provider will refuse that in one request long before our own cap
#: bites. The measured window is reported as the span actually covered.
MAX_LOG_BLOCKS = 3_000

TOKEN_LAUNCHED = next(e for e in V2_FACTORY_EVENTS if e.name == "TokenLaunched")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=DEFAULT_ENV_FILE)
    parser.add_argument("--env-key", default=DEFAULT_ENV_KEY)
    parser.add_argument("--ledger", default=str(HERE / "rpc_ledger.json"))
    parser.add_argument("--out", default=str(HERE / "verification.json"))
    parser.add_argument("--manifest", default=str(HERE / "deployments.json"))
    parser.add_argument("--clear-halt", metavar="WHY", default=None,
                        help=("lift a persisted provider halt, recording WHY in the "
                              "ledger. Operator action; nothing automatic uses it."))
    args = parser.parse_args(argv)

    manifest = load_manifest(args.manifest)
    ledger = RequestLedger(args.ledger, run_id="d10-verify", run_cap=MAX_REQUESTS)
    cleared = ledger.clear_halt(args.clear_halt) if args.clear_halt else None
    report: dict = {
        "version": "d10-verification-1",
        "at": _now(),
        "endpoint": MASK,
        "endpoint_source": {"env_file": args.env_file, "env_key": args.env_key,
                            "note": "read by key name at runtime; never stored"},
        "max_requests": MAX_REQUESTS,
        "chain_id_expected": manifest.chain_id,
        "chain_id": None,
        "code_hashes": [],
        "head": None,
        "safe_tag": {"supported": None, "detail": None},
        "block_interval": None,
        "launch_rate": None,
        "documentation_says": ("v2 docs: \"public launches are closed, so only "
                               "whitelisted addresses can create a token for now\""),
        "errors": [],
        "stopped": None,
        "cleared_halt": cleared,
    }

    url = None
    try:
        url = read_endpoint(args.env_file, args.env_key)
    except RpcError as exc:
        report["errors"].append({"stage": "endpoint", "code": exc.code,
                                 "detail": mask(exc.detail)})
        report["stopped"] = exc.code
        _write(args.out, report, ledger)
        return 2

    rpc = RpcClient(url, ledger)

    def fail(stage: str, exc) -> None:
        code = getattr(exc, "code", exc.__class__.__name__)
        report["errors"].append({"stage": stage, "code": code,
                                 "detail": rpc.mask(getattr(exc, "detail", str(exc)))})
        report["stopped"] = code

    def step(stage, fn, default=None):
        """One attempt at one planned call. A failure is recorded and the next
        *distinct* planned call still runs; nothing is ever retried."""
        try:
            return fn()
        except BudgetStop as exc:
            fail(stage, exc)
            raise
        except (RpcError, ValueError) as exc:
            fail(stage, exc)
            return default

    try:
        report["chain_id"] = step("eth_chainId", rpc.chain_id)
        if report["chain_id"] is not None and report["chain_id"] != manifest.chain_id:
            report["stopped"] = "WRONG_CHAIN"
            _write(args.out, report, ledger)
            return 3

        report["block_number"] = step("eth_blockNumber", rpc.block_number)
        head = step("eth_getBlockByNumber(latest)", lambda: rpc.block("latest"))
        if head is None:
            report["stopped"] = report["stopped"] or "NO_HEAD"
            _write(args.out, report, ledger)
            return 5
        head_number = int(str(head["number"]), 16)
        head_ts = int(str(head["timestamp"]), 16)
        report["head"] = {"number": head_number, "hash": head["hash"],
                          "timestamp": head_ts}

        # ``latest`` rather than the numeric head: this endpoint answers the
        # head header but not always state *at* that number, and reading the
        # tag is the call the node is built to serve. Recorded as the tag used.
        for deployment in manifest.deployments:
            if deployment.expected_code_hash is None:
                continue
            code = step(f"eth_getCode({deployment.id})",
                        lambda d=deployment: rpc.code(d.address, "latest"))
            if code is None:
                report["code_hashes"].append({
                    "id": deployment.id, "address": deployment.address,
                    "supported": deployment.supported, "status": deployment.status,
                    "expected": deployment.expected_code_hash, "observed": None,
                    "match": None, "empty": None, "block_tag": "latest"})
                continue
            digest = keccak256_hex(bytes.fromhex(code[2:]))
            report["code_hashes"].append({
                "id": deployment.id, "address": deployment.address,
                "supported": deployment.supported,
                "status": deployment.status,
                "expected": deployment.expected_code_hash,
                "observed": digest,
                "match": digest == deployment.expected_code_hash,
                "empty": code == "0x", "block_tag": "latest"})

        mismatch = [c for c in report["code_hashes"]
                    if c["match"] is False and c["supported"]]
        if mismatch:
            report["stopped"] = "FACTORY_CODE_CHANGED"
            _write(args.out, report, ledger)
            return 4

        # --- block interval, measured ------------------------------------
        earlier = step("eth_getBlockByNumber(head-2000)",
                       lambda: rpc.block(max(0, head_number - INTERVAL_SAMPLE_BLOCKS)))
        middle = step("eth_getBlockByNumber(head-1000)",
                      lambda: rpc.block(max(0, head_number - INTERVAL_SAMPLE_BLOCKS // 2)))
        headers = [{"number": int(str(b["number"]), 16),
                    "timestamp": int(str(b["timestamp"]), 16)}
                   for b in (earlier, middle, head) if b is not None]
        report["block_interval"] = {"samples": headers, "median_s": None}
        if len(headers) < 2:
            report["stopped"] = report["stopped"] or "NO_BLOCK_INTERVAL"
            _write(args.out, report, ledger)
            return 6

        # --- safe tag probe ----------------------------------------------
        try:
            safe = rpc.block("safe")
            report["safe_tag"] = {"supported": True,
                                  "detail": {"number": int(str(safe["number"]), 16),
                                             "hash": safe["hash"]}}
        except RpcError as exc:
            report["safe_tag"] = {"supported": False,
                                  "detail": {"code": exc.code,
                                             "message": rpc.mask(exc.detail)}}

        finality = measure_finality(headers,
                                    safe_tag_supported=bool(report["safe_tag"]["supported"]))
        report["block_interval"]["median_s"] = finality.median_interval_s
        report["finality"] = finality.as_dict()
        (HERE / "finality.json").write_text(
            json.dumps({"measured_at": _now(), "head": report["head"],
                        **finality.as_dict()}, indent=1) + "\n", encoding="utf-8")

        # --- launch rate over the last hour ------------------------------
        blocks = max(1, int(round(LAUNCH_RATE_SECONDS / finality.median_interval_s)))
        blocks = min(blocks, MAX_LOG_BLOCKS)
        start = max(0, head_number - blocks)
        remaining = MAX_REQUESTS - ledger.run_attempts
        chunks = min(MAX_LOG_CHUNKS, max(1, remaining))
        span = (head_number - start + 1 + chunks - 1) // chunks
        launches = 0
        seen = set()
        ranges = []
        lo = start
        used = 0
        while lo <= head_number and used < chunks:
            hi = min(lo + span - 1, head_number)
            logs = step(f"eth_getLogs({lo}-{hi})",
                        lambda a=lo, b=hi: rpc.logs([manifest.factory.address], a, b,
                                                    [TOKEN_LAUNCHED.topic0]))
            if logs is None:
                ranges.append({"from": lo, "to": hi, "logs": None,
                               "error": report["errors"][-1]["code"]})
                break
            for log in logs:
                key = (str(log["blockHash"]).lower(), str(log["transactionHash"]).lower(),
                       int(str(log["logIndex"]), 16))
                if key in seen:
                    continue
                seen.add(key)
                launches += 1
            ranges.append({"from": lo, "to": hi, "logs": len(logs)})
            lo = hi + 1
            used += 1
        covered = sum(r["to"] - r["from"] + 1 for r in ranges if r["logs"] is not None)
        seconds = covered * finality.median_interval_s
        report["launch_rate"] = {
            "topic0": TOKEN_LAUNCHED.topic0,
            "signature": TOKEN_LAUNCHED.signature,
            "factory": manifest.factory.address,
            "ranges": ranges,
            "blocks_covered": covered,
            "seconds_covered": seconds,
            "launches": launches,
            "per_hour": (launches * 3600.0 / seconds) if seconds else None,
        }
    except BudgetStop as exc:
        fail("budget", exc)
    except RpcError as exc:
        fail("rpc", exc)

    _write(args.out, report, ledger)
    print(json.dumps({k: report[k] for k in
                      ("chain_id", "code_hashes", "safe_tag", "block_interval",
                       "launch_rate", "errors", "stopped")
                      if k in report}, indent=1))
    return 0 if not report["errors"] else 1


def _write(path, report: dict, ledger: RequestLedger) -> None:
    ledger.flush()
    report["requests"] = {"attempts": ledger.run_attempts,
                          "units": ledger.units,
                          "wave_attempts": ledger.attempts,
                          "remaining": ledger.remaining()}
    Path(path).write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
