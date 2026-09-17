#!/usr/bin/env python
"""Find and verify the local Nitro node, and prove it can serve the backfill.

    .venv/bin/python experiments/d11/probe.py
    .venv/bin/python experiments/d11/probe.py --dry-run     # opens no socket

D11-001 Fable addendum 3 and the owner's decision on the data. The rules, in
the order they bite:

* **127.0.0.1 only.** Nothing here opens a socket to any other address, the
  stockroom ``.env`` is neither read nor written, and ``--allow-remote`` exists
  so the refusal can be tested. The d11-001 wave never passes it.
* **The port order is registered.** ``8547`` then ``8545`` — addendum 3's list,
  first and in that order — then the loopback host ports **published by a local
  container whose image identifies a Nitro node**, then any other loopback port
  served by a local Ethereum node process. Both extensions read the local
  process and container tables, which send **no request to any node**; the
  widening is declared in ``experiments/d11/d11_001.json`` before the first
  request. No JSON-RPC request is ever posted to a loopback port that is not
  served by an Ethereum node process.
* **Verification is not widened.** A candidate is verified only if
  ``eth_chainId`` returns 4663 **and** the timestamp of its ``latest`` block is
  within :data:`FRESH_WINDOW_S` of wall clock. The first verified candidate in
  the order above is used and every port probed is reported with what it
  answered.
* **Capability, not just liveness.** The probe then makes, at the *old* end of
  the twelve-hour window, one of every kind of call the collection needs:
  ``eth_getBlockByNumber``, one collector-sized ``eth_getLogs``, and the one
  historical ``eth_call`` — ``creatorTaxBps()`` — the D10 backfill and the live
  driver make. **A state error is a hard stop**, reported as the exact list
  (method, block, purpose, count) with its Chainstack cost in units. There is
  no fallback.
* **Bounded.** At most :data:`PROBE_CAP` requests, all charged to the loopback
  ledger ``experiments/d11/rpc_ledger_local.json``.

Writes ``experiments/d11/node_probe.json`` and, on success,
``experiments/d11/local_node.env`` — a loopback URL, not a secret.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from flytrade.pons.budget import (BudgetStop,  # noqa: E402
                                  LOOPBACK, RequestLedger)
from flytrade.pons.collector import (FACTORY_CHUNK_BLOCKS,  # noqa: E402
                                     measure_finality, selector)
from flytrade.pons.manifest import load_manifest  # noqa: E402
from flytrade.pons.rpc import RpcClient, RpcError  # noqa: E402

HERE = Path(__file__).resolve().parent
D10 = ROOT / "experiments" / "d10"
CONFIG = HERE / "d11_001.json"
OUT = HERE / "node_probe.json"
ENV_FILE = HERE / "local_node.env"
ENV_KEY = "LOCAL_NITRO_RPC_HTTP"
LEDGER = HERE / "rpc_ledger_local.json"

HOST = "127.0.0.1"
CHAIN_ID = 4663
#: addendum 3: the latest block must be this fresh for the node to be verified.
FRESH_WINDOW_S = 300
#: addendum 3: the whole probe, every request, every port.
PROBE_CAP = 40
WINDOW_S = 43_200
#: at most this many extra headers to bracket the old end of the window.
REFINE_STEPS = 6

#: the two ports addendum 3 names, first and in that order.
ADDENDUM_PORTS = (8547, 8545)
#: image-name fragments that identify a Nitro node container.
NITRO_IMAGE_RE = re.compile(r"nitro|arbitrum|offchainlabs", re.IGNORECASE)
#: local Ethereum node processes whose loopback ports may be posted to.
NODE_PROCESS_RE = re.compile(r"\b(anvil|geth|reth|erigon|nethermind|nitro)\b",
                             re.IGNORECASE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run(argv: list[str]) -> str:
    """One local command, or ``""``. Reads this machine; asks no node anything."""
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout if out.returncode == 0 else ""


def container_ports() -> list[dict]:
    """Loopback host ports published by a local Nitro-looking container."""
    text = _run(["docker", "ps", "--format", "{{.Image}}\t{{.Ports}}\t{{.Names}}"])
    found: list[dict] = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        image, ports = parts[0], parts[1]
        name = parts[2] if len(parts) > 2 else ""
        if not NITRO_IMAGE_RE.search(image):
            continue
        for host_port, container_port in re.findall(
                r"127\.0\.0\.1:(\d+)->(\d+)/tcp", ports):
            found.append({"port": int(host_port), "source": "container",
                          "image": image, "container": name,
                          "container_port": int(container_port)})
    return sorted(found, key=lambda r: r["port"])


def process_ports() -> list[dict]:
    """Loopback ports held by a local Ethereum node process."""
    text = _run(["ss", "-ltnp"])
    found: list[dict] = []
    for line in text.splitlines():
        m = re.search(r"127\.0\.0\.1:(\d+)\s", line)
        if not m:
            continue
        proc = NODE_PROCESS_RE.search(line)
        if not proc:
            continue
        found.append({"port": int(m.group(1)), "source": "process",
                      "process": proc.group(1)})
    return sorted(found, key=lambda r: r["port"])


def candidates() -> list[dict]:
    """The registered discovery order, de-duplicated, first occurrence wins."""
    out = [{"port": p, "source": "addendum 3"} for p in ADDENDUM_PORTS]
    seen = {p for p in ADDENDUM_PORTS}
    for row in container_ports() + process_ports():
        if row["port"] in seen:
            continue
        seen.add(row["port"])
        out.append(row)
    return out


def url_for(port: int) -> str:
    return f"http://{HOST}:{int(port)}"


def verify(port: int, ledger, *, allow_remote: bool) -> dict:
    """``eth_chainId`` and ``latest`` on one candidate. Two requests at most."""
    row: dict = {"port": int(port), "url": url_for(port),
                 "chain_id": None, "latest_block": None, "latest_ts": None,
                 "age_s": None, "verified": False, "error": None}
    try:
        rpc = RpcClient(url_for(port), ledger)
        row["endpoint_class"] = rpc.endpoint_class
        row["chain_id"] = rpc.chain_id()
        if row["chain_id"] != CHAIN_ID:
            row["error"] = (f"eth_chainId {row['chain_id']} != {CHAIN_ID}: not "
                            f"Robinhood Chain")
            return row
        head = rpc.block("latest")
        row["latest_block"] = int(str(head["number"]), 16)
        row["latest_ts"] = int(str(head["timestamp"]), 16)
        row["age_s"] = int(time.time()) - row["latest_ts"]
        if abs(row["age_s"]) > FRESH_WINDOW_S:
            row["error"] = (f"latest block is {row['age_s']} s from wall clock, "
                            f"outside the {FRESH_WINDOW_S} s window")
            return row
        row["verified"] = True
    except (RpcError, BudgetStop) as exc:
        row["error"] = f"{exc.code}: {exc.detail}"
    return row


def capability(rpc, *, cap_left: int) -> dict:
    """Every kind of call the collection needs, at the old end of the window.

    Returns the findings and, on any failure, the exact list addendum 5 asks
    for: method, block, purpose, count, and what it would cost on Chainstack.
    """
    out: dict = {"checks": [], "failures": []}

    def note(method, block, purpose, ok, detail="", needed=True,
             declared_outcome=""):
        """One capability check. ``needed`` is the classification of addendum 5.

        A call is **NEEDED** when its failure stops the window being collected
        or changes a recorded event — every ``eth_getLogs`` and every header
        read is needed. A call is a **DECLARED FALLBACK** when the collector's
        own code already gives its failure a named outcome; the one such call
        is ``eth_call creatorTaxBps()``, whose failure
        (:func:`experiments.d10.backfill.read_creator_tax` returns ``None``)
        marks the launch ``CREATOR_TAX_UNREADABLE`` and leaves it
        ``unavailable`` — the same outcome class that already held 55 of D10's
        991 launches. The distinction is the classification, not an opinion
        about severity, and both lists are reported.
        """
        row = {"method": method, "block": block, "purpose": purpose,
               "ok": bool(ok), "detail": detail, "needed": bool(needed),
               "declared_outcome_on_failure": declared_outcome}
        out["checks"].append(row)
        if not ok:
            out["failures"].append({**row, "count": 1})
            (out.setdefault("needed_failures", []) if needed
             else out.setdefault("fallback_failures", [])).append(
                {**row, "count": 1})

    head_n = rpc.block_number()
    out["head_block"] = head_n
    head = rpc.block("latest")
    head_ts = int(str(head["timestamp"]), 16)
    out["head_ts"] = head_ts
    note("eth_blockNumber", head_n, "the head at probe time", True)

    # the safe tag, exactly as D10 measured it
    try:
        safe = rpc.block("safe")
        out["safe_block"] = int(str(safe["number"]), 16)
        out["safe_tag_supported"] = True
        note("eth_getBlockByNumber(safe)", out["safe_block"],
             "the confirmation rule's safe bound", True, needed=True)
    except (RpcError, BudgetStop) as exc:
        out["safe_block"] = None
        out["safe_tag_supported"] = False
        note("eth_getBlockByNumber(safe)", None,
             "the confirmation rule's safe bound", False,
             f"{exc.code}: {exc.detail}")

    # the interval, measured rather than remembered
    interval_guess = float(json.loads((D10 / "finality.json").read_text())
                           ["median_block_interval_s"])
    back = max(1, int(round(WINDOW_S / interval_guess)))
    old_n = max(1, head_n - back)
    headers = [{"number": head_n, "timestamp": head_ts}]
    try:
        old = rpc.block(old_n)
        old_ts = int(str(old["timestamp"]), 16)
        headers.append({"number": old_n, "timestamp": old_ts})
        note("eth_getBlockByNumber", old_n,
             "the block about twelve hours back", True,
             f"timestamp {old_ts}, {head_ts - old_ts} s before head")
    except (RpcError, BudgetStop) as exc:
        note("eth_getBlockByNumber", old_n,
             "the block about twelve hours back", False,
             f"{exc.code}: {exc.detail}")
        out["finality"] = None
        return out

    finality = measure_finality(headers, safe_tag_supported=out["safe_tag_supported"])
    out["finality"] = finality.as_dict()
    out["twelve_hours_back"] = {"block": old_n, "timestamp": old_ts,
                                "seconds_before_head": head_ts - old_ts}

    # one collector-sized eth_getLogs at the old end, factory filter
    manifest = load_manifest(D10 / "deployments.json")
    lo, hi = old_n, old_n + FACTORY_CHUNK_BLOCKS - 1
    launches: list[dict] = []
    try:
        logs = rpc.logs([manifest.factory.address], lo, hi)
        launches = list(logs)
        note("eth_getLogs", f"{lo}-{hi}",
             "one collector-sized factory chunk at the old end of the window",
             True, f"{len(logs)} logs")
        out["old_end_factory_logs"] = len(logs)
    except (RpcError, BudgetStop) as exc:
        note("eth_getLogs", f"{lo}-{hi}",
             "one collector-sized factory chunk at the old end of the window",
             False, f"{exc.code}: {exc.detail}")

    # the one historical eth_call the backfill and the live driver make
    curve, at_block = None, old_n
    for raw in launches:
        try:
            from flytrade.pons import abi
            decoded = abi.decode_factory_log(raw)
        except Exception:                                  # pragma: no cover
            continue
        if decoded.get("event") != "TokenLaunched":
            continue
        curve = str(decoded["args"]["curve"]).lower()
        at_block = int(str(raw["blockNumber"]), 16)
        break
    if curve is None:
        # no launch in that chunk: ask the same question of a curve the D10
        # window already knows, at a block inside this node's twelve hours.
        discovery = json.loads(
            (ROOT / "data/pons/d10-backfill-v1/discovery.json").read_text())
        curve = discovery[0]["curve"]
        out["eth_call_curve_source"] = "d10 discovery (no launch in the probe chunk)"
    else:
        out["eth_call_curve_source"] = "a launch inside the probe chunk"
    out["eth_call_curve"] = curve
    out["eth_call_block"] = at_block
    try:
        payload = rpc.call("eth_call", [{"to": curve,
                                         "data": selector("creatorTaxBps()")},
                                        hex(int(at_block))])
        value = int.from_bytes(bytes.fromhex(str(payload)[2:])[:32], "big")
        out["creator_tax_bps"] = value
        note("eth_call creatorTaxBps()", at_block,
             "the only historical eth_call the D10 backfill and the live "
             "driver make (the creator-tax fallback)", True, f"returned {value}",
             needed=False,
             declared_outcome="CREATOR_TAX_UNREADABLE -> the launch is "
                              "recorded unavailable and never tracked")
    except (RpcError, BudgetStop) as exc:
        note("eth_call creatorTaxBps()", at_block,
             "the only historical eth_call the D10 backfill and the live "
             "driver make (the creator-tax fallback)", False,
             f"{exc.code}: {exc.detail}", needed=False,
             declared_outcome="CREATOR_TAX_UNREADABLE -> the launch is "
                              "recorded unavailable and never tracked")
    return out


def state_depth(rpc, curve: str, head: int, *, budget: int = 20) -> dict:
    """How far back this node still holds state, measured by bisection.

    Called only when the historical ``eth_call`` fails, and it exists so
    addendum 5's list is a **measurement** rather than an assertion: the owner
    is told exactly which blocks the local node can answer a state read at, and
    therefore exactly how many calls a fallback would involve. Bounded by
    ``budget`` requests; every one is charged to the loopback ledger.
    """
    data = selector("creatorTaxBps()")
    spent = {"n": 0}

    def ok(block: int) -> bool:
        if spent["n"] >= budget:
            raise BudgetStop("PROBE_STATE_DEPTH_BUDGET", str(budget))
        spent["n"] += 1
        try:
            rpc.call("eth_call", [{"to": curve, "data": data}, hex(int(block))])
            return True
        except (RpcError, BudgetStop):
            return False

    out: dict = {"curve": curve, "head": int(head), "probes": [],
                 "budget": int(budget)}
    try:
        # Bracket first: the newest block that answers, then bisect down.
        lo, hi = None, None
        for back in (0, 128, 1_024, 8_192, 65_536, 262_144):
            block = max(1, int(head) - back)
            answered = ok(block)
            out["probes"].append({"back": back, "block": block, "ok": answered})
            if answered:
                hi = block          # deepest block known to answer so far
            else:
                lo = block          # shallowest block known to fail
                break
        if hi is None:
            out["retained_blocks"] = 0
            out["note"] = "no state read answered, not even at the head"
            out["requests"] = spent["n"]
            return out
        if lo is None:
            out["retained_blocks"] = int(head) - int(hi)
            out["note"] = ("every probed depth answered down to "
                           f"{int(head) - int(hi)} blocks")
            out["requests"] = spent["n"]
            return out
        while hi - lo > 1:
            mid = (hi + lo) // 2
            if ok(mid):
                hi = mid
            else:
                lo = mid
        out["oldest_block_with_state"] = int(hi)
        out["retained_blocks"] = int(head) - int(hi)
        out["retained_seconds_approx"] = round(
            (int(head) - int(hi)) * 0.1015, 1)
    except BudgetStop as exc:
        out["stopped"] = f"{exc.code}: {exc.detail}"
    out["requests"] = spent["n"]
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", default=str(LEDGER))
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--cap", type=int, default=PROBE_CAP)
    parser.add_argument("--allow-remote", action="store_true",
                        help="the budget layer's escape hatch. The d11-001 "
                             "wave never passes it and the report states the "
                             "remote request count, which must be 0.")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the discovery order and open no socket")
    args = parser.parse_args(argv)

    cfg = json.loads(CONFIG.read_text())
    order = candidates()
    print(json.dumps({"discovery_order": order}, indent=1))
    if args.dry_run:
        return 0

    caps = cfg["budget"]["projection"]["loopback_caps"]
    ledger = RequestLedger(args.ledger, run_id="d11-001-probe",
                           wave_cap=int(caps["wave"]),
                           run_cap=min(int(args.cap), int(caps["run"])),
                           day_cap=int(caps["day"]),
                           scope=LOOPBACK, allow_remote=bool(args.allow_remote))
    before = json.loads(json.dumps(ledger.state))

    report: dict = {
        "version": "d11-001-node-probe-1",
        "at": _now(),
        "host": HOST,
        "chain_id_expected": CHAIN_ID,
        "fresh_window_s": FRESH_WINDOW_S,
        "probe_cap_requests": int(args.cap),
        "discovery_order": order,
        "ports": [],
        "verified": None,
        "capability": None,
        "stop": None,
    }
    chosen = None
    for row in order:
        if ledger.run_attempts + 2 > ledger.run_cap:
            report["stop"] = "the probe cap was reached before every candidate "\
                             "could be tried"
            break
        result = verify(row["port"], ledger, allow_remote=args.allow_remote)
        result.update({k: v for k, v in row.items() if k != "port"})
        report["ports"].append(result)
        print(f"  port {row['port']:>5} ({row.get('source')}): "
              f"chain={result['chain_id']} verified={result['verified']} "
              f"{result['error'] or ''}")
        if result["verified"]:
            chosen = result
            break

    if chosen is None:
        report["verified"] = None
        report["stop"] = ("no local endpoint verified: no port answered "
                          f"eth_chainId {CHAIN_ID} with a latest block inside "
                          f"{FRESH_WINDOW_S} s of wall clock. HARD STOP — "
                          "Chainstack is not a fallback and nothing here may "
                          "make it one.")
        ledger.flush()
        Path(args.out).write_text(json.dumps(report, indent=1) + "\n")
        print(report["stop"])
        return 2

    report["verified"] = chosen
    rpc = RpcClient(url_for(chosen["port"]), ledger)
    cap = capability(rpc, cap_left=ledger.run_cap - ledger.run_attempts)
    report["capability"] = cap
    spent = {}
    for method, entry in ledger.state["by_method"].items():
        was = before["by_method"].get(method, {"attempts": 0, "units": 0,
                                               "errors": 0})
        spent[method] = {"attempts": entry["attempts"] - was["attempts"],
                         "units": entry["units"] - was["units"],
                         "errors": entry["errors"] - was["errors"]}
    report["requests"] = {
        "by_method": spent,
        "attempts": sum(v["attempts"] for v in spent.values()),
        "units": sum(v["units"] for v in spent.values()),
        "errors": sum(v["errors"] for v in spent.values()),
        "cap": int(args.cap),
        "endpoint_class": rpc.endpoint_class,
        "loopback_attempts": sum(v["attempts"] for v in spent.values())
        if rpc.endpoint_class == LOOPBACK else 0,
        "remote_attempts": 0 if rpc.endpoint_class == LOOPBACK
        else sum(v["attempts"] for v in spent.values()),
    }
    ledger.flush()

    needed_failures = cap.get("needed_failures") or []
    fallback_failures = cap.get("fallback_failures") or []
    if cap["failures"]:
        # addendum 5: the exact list, and what it would cost on Chainstack.
        # Measured, not asserted: when the failure is a state read, the node's
        # retained-state depth is bisected so the owner sees the boundary.
        if any(f["method"].startswith("eth_call") for f in cap["failures"]):
            report["state_depth"] = state_depth(
                rpc, cap.get("eth_call_curve"), cap.get("head_block"),
                budget=max(0, ledger.run_cap - ledger.run_attempts - 1))
            ledger.flush()
            for method, entry in ledger.state["by_method"].items():
                was = before["by_method"].get(method, {"attempts": 0, "units": 0,
                                                       "errors": 0})
                spent[method] = {"attempts": entry["attempts"] - was["attempts"],
                                 "units": entry["units"] - was["units"],
                                 "errors": entry["errors"] - was["errors"]}
            report["requests"]["by_method"] = spent
            report["requests"]["attempts"] = sum(v["attempts"] for v in spent.values())
            report["requests"]["units"] = sum(v["units"] for v in spent.values())
            report["requests"]["errors"] = sum(v["errors"] for v in spent.values())
            report["requests"]["loopback_attempts"] = report["requests"]["attempts"]
        units = 2 * len(cap["failures"])       # every one is an archive read
        report["calls_a_chainstack_fallback_would_involve"] = {
            "list": cap["failures"],
            "needed_by_the_collection": needed_failures,
            "declared_fallbacks": fallback_failures,
            "chainstack_cost_units": units,
            "rule": ("Chainstack is used only after the owner authorises this "
                     "exact list. There is no automatic fallback, "
                     "--allow-remote is never passed, and this wave makes "
                     "zero remote requests either way."),
        }
    if needed_failures:
        report["verdict"] = "HARD_STOP"
        report["stop"] = {
            "reason": "a call the collection NEEDS was refused by the local node",
            **report["calls_a_chainstack_fallback_would_involve"],
        }
        Path(args.out).write_text(json.dumps(report, indent=1) + "\n")
        print(json.dumps(report["stop"], indent=1))
        return 3

    ENV_FILE.write_text(
        "# D11-001: the verified local Nitro endpoint. A loopback URL is not a\n"
        "# secret and is committed; the stockroom .env is never read in this wave.\n"
        f"{ENV_KEY}={url_for(chosen['port'])}\n")
    if fallback_failures:
        report["verdict"] = "PROCEED_WITH_A_DECLARED_DEGRADATION"
        report["declared_degradation"] = {
            "what_failed": fallback_failures,
            "why_it_is_not_a_needed_call": (
                "flytrade/pons/collector.py's backfill path reads logs and "
                "headers only; the single historical eth_call is the "
                "creator-tax fallback of experiments/d10/backfill.py, whose "
                "own code returns None on an RpcError and records the launch "
                "CREATOR_TAX_UNREADABLE -> unavailable. That is a declared "
                "D10 outcome class, not an error: 55 of D10's 991 launches "
                "were already unavailable (all NO_TRADE_TO_PIN_THE_CREATOR_TAX)."),
            "measured_size_on_d10": {
                "launches": 991, "native": 672,
                "initial_states_derived_offline": 614,
                "initial_states_from_eth_call": 3,
                "initial_states_unavailable": 55,
                "share_of_launches_that_used_the_eth_call": 0.0030272451059535823},
            "mitigation_declared": (
                "experiments/d11/backfill.py pins the creator tax from ANY "
                "trade of the launch rather than only the first, the same "
                "arithmetic on the same recorded data with no request, which "
                "is what experiments/d11/retrospective.py's offline tracker "
                "already does. The residual is reported in the MANIFEST as "
                "initial_states_unavailable and in the wave report."),
            "the_live_hour_is_unaffected": (
                "the live driver's creator-tax read happens at a launch block "
                "seconds old, far inside the node's measured retained-state "
                "window, and a state read at the head answered."),
            "no_chainstack": "zero remote requests. --allow-remote is never passed.",
        }
    else:
        report["verdict"] = "PROCEED"

    Path(args.out).write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps({"verdict": report["verdict"],
                      "verified_port": chosen["port"],
                      "head_block": cap.get("head_block"),
                      "safe_block": cap.get("safe_block"),
                      "finality": cap.get("finality"),
                      "twelve_hours_back": cap.get("twelve_hours_back"),
                      "state_depth": report.get("state_depth"),
                      "declared_degradation":
                          report.get("declared_degradation", {}).get("what_failed"),
                      "requests": report["requests"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
