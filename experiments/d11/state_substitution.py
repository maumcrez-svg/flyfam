#!/usr/bin/env python
"""The pruned node's historical state, substituted and **verified**.

    .venv/bin/python experiments/d11/state_substitution.py --verify-offline
    .venv/bin/python experiments/d11/state_substitution.py --probe-latest
    .venv/bin/python experiments/d11/state_substitution.py --rescue

docs/SPEC.md, the owner's amendment after dispatch (2026-09-13): the local
Nitro node is pruned, the archive-state hard stop is withdrawn, and each kind
of historical ``eth_call`` the D10 backfill made must be classified and
substituted rather than abandoned.

**The D10 backfill made exactly one kind** — ``creatorTaxBps()`` at a launch
block, the declared fallback of ``experiments/d10/backfill.py`` when the
arithmetic of a launch's first trade does not pin the tax. It was used **3
times in 991 launches**. (``flytrade.pons.collector.read_initial_state``'s nine
reads are reachable from no run path; a test asserts it.)

The creator tax is a **launch parameter of the curve**, so under the
amendment's scheme it is class **(a), immutable per curve**, and the
substitution is to read it at ``latest``. That claim is not asserted here, it
is **measured**:

``--verify-offline``  class **(b)**, local files only, no request: re-derive
                      every one of ``d10-backfill-v1``'s recorded initial
                      states from that store's own events with this wave's
                      "pin from any trade" rule, and require an exact match on
                      every field of every curve. This is the rule the D11-001
                      collection actually used.
``--probe-latest``    class **(a)**, a bounded ledgered loopback probe: read
                      ``creatorTaxBps()`` at ``latest`` for every D10 curve
                      with a recorded initial state and compare with the
                      recorded ``creator_tax_bps``. Every curve the node
                      answers for must match exactly, which is what makes
                      "immutable" a measurement.
``--rescue``          apply class **(a)** to the D11-001 store's own residue:
                      the curves whose tax no recorded trade pins. Their state
                      is written with ``source: latest_block_immutable`` and
                      the counts go into the MANIFEST. A curve the node does
                      not answer for stays class **(c)** — unsupported,
                      counted, **never guessed**.
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

HERE = Path(__file__).resolve().parent
D10 = ROOT / "experiments" / "d10"
D10_STORE = ROOT / "data" / "pons" / "d10-backfill-v1"
D11_STORE = ROOT / "data" / "pons" / "d11-backfill-v1"
OUT = HERE / "state_substitution.json"
LEDGER = HERE / "rpc_ledger_local.json"

sys.path.insert(0, str(HERE))
from backfill import derive_initial_state  # noqa: E402
from flytrade.pons.budget import (BudgetStop, LOOPBACK,  # noqa: E402
                                  RequestLedger)
from flytrade.pons.collector import selector  # noqa: E402
from flytrade.pons.manifest import NATIVE_QUOTE  # noqa: E402
from flytrade.pons.rpc import RpcClient, RpcError, read_endpoint  # noqa: E402
from flytrade.pons.seed import LAUNCH_SEED, seed_state  # noqa: E402

#: the one kind of historical state read the D10 backfill made.
SUBSTITUTIONS = [{
    "call": "eth_call creatorTaxBps() at the launch block",
    "made_by": "experiments/d10/backfill.py::read_creator_tax, the declared "
               "fallback when a launch's first trade does not pin the tax",
    "d10_usage": {"launches": 991, "used_the_call": 3, "share": 0.0030272451},
    "class": "(a) immutable per curve — it is a launch parameter of the curve",
    "substitution": "read at `latest` instead of at the launch block; and, "
                    "before that, avoid the read entirely by pinning the tax "
                    "from ANY recorded trade of the launch rather than only "
                    "the first (class (b), reconstruct from events)",
    "state_source": "latest_block_immutable",
}]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def store_events(store: Path) -> tuple[dict, dict]:
    """``(launches by curve, curve events by address)`` from a store's log."""
    launches: dict = {}
    by_curve: dict = {}
    with open(store / "events.jsonl", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            if e.get("status") != "OK":
                continue
            if e.get("source") == "factory" and e.get("event") == "TokenLaunched":
                launches.setdefault(e["curve"], e)
            elif e.get("source") == "curve":
                by_curve.setdefault(e["address"], []).append(e)
    for evs in by_curve.values():
        evs.sort(key=lambda e: (e["block_number"], e["tx_index"], e["log_index"]))
    return launches, by_curve


def verify_offline(store: Path = D10_STORE) -> dict:
    """Class (b): re-derive every recorded initial state from the events alone.

    No request of any kind. Every field of every curve must match the value
    ``d10-backfill-v1`` recorded, or the substitution is not verified.
    """
    recorded = json.loads((store / "initial_states.json").read_text())
    launches, by_curve = store_events(store)
    checked = matched = 0
    mismatches = []
    sources: dict = {}
    for token, entry in sorted(recorded.items()):
        curve = entry["curve"]
        launch = launches.get(curve)
        if launch is None:
            mismatches.append({"token": token, "why": "no TokenLaunched"})
            continue
        args = launch.get("args") or {}
        record = {"launch_config_id": args.get("launchConfigId"),
                  "graduation_threshold": args.get("graduationThreshold"),
                  "curve": curve}
        trades = [e for e in by_curve.get(curve, [])
                  if e["event"] in ("CurveBuy", "CurveSell")]
        got = derive_initial_state(record, trades)
        checked += 1
        sources[got["source"]] = sources.get(got["source"], 0) + 1
        if got["state"] is None:
            mismatches.append({"token": token, "why": got["reason"]})
            continue
        want = entry["state"]
        have = got["state"].as_dict()
        diff = {k: (want.get(k), have.get(k)) for k in want
                if str(want.get(k)) != str(have.get(k))}
        if diff:
            mismatches.append({"token": token, "diff": diff})
        else:
            matched += 1
    return {
        "class": "(b) reconstruct from events",
        "store": str(store),
        "recorded_initial_states": len(recorded),
        "checked": checked, "matched_exactly": matched,
        "mismatches": mismatches[:50],
        "mismatch_count": len(mismatches),
        "sources": sources,
        "opened_no_socket": True,
        "rule": ("this wave's derive_initial_state pins the creator tax from "
                 "any recorded trade of the launch, in chain order, and "
                 "rebuilds the pinned seed state from it. Every field of "
                 "CurveState is compared."),
    }


def probe_latest(curves: list[dict], *, ledger, rpc, log=print) -> dict:
    """Class (a): read ``creatorTaxBps()`` at ``latest`` and compare."""
    data = selector("creatorTaxBps()")
    answered = matched = 0
    unanswered: list[dict] = []
    differed: list[dict] = []
    t0 = time.time()
    for i, row in enumerate(curves, start=1):
        try:
            payload = rpc.call("eth_call",
                               [{"to": str(row["curve"]).lower(), "data": data},
                                "latest"])
            value = int.from_bytes(bytes.fromhex(str(payload)[2:])[:32], "big")
        except (RpcError, BudgetStop) as exc:
            unanswered.append({"curve": row["curve"], "token": row.get("token"),
                               "error": f"{exc.code}"})
            continue
        answered += 1
        want = row.get("creator_tax_bps")
        if want is None:
            row["latest_creator_tax_bps"] = value
            continue
        if int(value) == int(want):
            matched += 1
        else:
            differed.append({"curve": row["curve"], "token": row.get("token"),
                             "recorded": int(want), "at_latest": int(value)})
        row["latest_creator_tax_bps"] = value
        if i % 100 == 0:
            log(f"  {i}/{len(curves)} probed ({time.time() - t0:.0f}s)")
    return {"probed": len(curves), "answered": answered,
            "matched_exactly": matched,
            "differed": differed[:50], "differ_count": len(differed),
            "unanswered": unanswered[:50], "unanswered_count": len(unanswered),
            "elapsed_s": round(time.time() - t0, 1)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-offline", action="store_true")
    parser.add_argument("--probe-latest", action="store_true")
    parser.add_argument("--rescue", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--env-file", default=str(HERE / "local_node.env"))
    parser.add_argument("--env-key", default="LOCAL_NITRO_RPC_HTTP")
    parser.add_argument("--allow-remote", action="store_true",
                        help="never passed by this wave")
    args = parser.parse_args(argv)

    report = (json.loads(OUT.read_text()) if OUT.exists() else
              {"version": "d11-001-state-substitution-1",
               "amendment": ("docs/SPEC.md, the owner's amendment after "
                             "dispatch (2026-09-13): the node is pruned and "
                             "the archive-state hard stop is withdrawn"),
               "substitutions": SUBSTITUTIONS})
    report["at"] = _now()

    if args.verify_offline:
        report["verification_b"] = verify_offline()
        OUT.write_text(json.dumps(report, indent=1) + "\n")
        print(json.dumps({k: v for k, v in report["verification_b"].items()
                          if k != "mismatches"}, indent=1))
        return 0

    if args.probe_latest or args.rescue:
        cfg_run = json.loads((HERE / "d11_001.json").read_text())
        caps = cfg_run["budget"]["projection"]["loopback_caps"]
        ledger = RequestLedger(LEDGER, run_id="d11-001-state-substitution",
                               wave_cap=int(caps["wave"]),
                               run_cap=int(caps["run"]),
                               day_cap=int(caps["day"]), scope=LOOPBACK,
                               allow_remote=bool(args.allow_remote))
        url = read_endpoint(args.env_file, args.env_key)
        rpc = RpcClient(url, ledger)
        if rpc.endpoint_class != LOOPBACK:
            raise SystemExit("loopback only")

    if args.probe_latest:
        recorded = json.loads((D10_STORE / "initial_states.json").read_text())
        curves = [{"token": t, "curve": e["curve"],
                   "creator_tax_bps": int(e["state"]["creator_tax_bps"])}
                  for t, e in sorted(recorded.items())]
        if args.limit:
            curves = curves[:args.limit]
        out = probe_latest(curves, ledger=ledger, rpc=rpc)
        out["class"] = "(a) immutable per curve, read at latest"
        out["population"] = ("every d10-backfill-v1 curve with a recorded "
                             "initial state")
        ledger.flush()
        report["verification_a"] = out
        OUT.write_text(json.dumps(report, indent=1) + "\n")
        print(json.dumps({k: v for k, v in out.items()
                          if k not in ("differed", "unanswered")}, indent=1))
        return 0

    if args.rescue:
        discovery = json.loads((D11_STORE / "discovery.json").read_text())
        states = json.loads((D11_STORE / "initial_states.json").read_text())
        need = [d for d in discovery
                if "CREATOR_TAX_UNREADABLE" in (d.get("reasons") or [])]
        print(f"{len(need)} curves whose tax no recorded trade pins")
        rows = [{"token": d["token"], "curve": d["curve"]} for d in need]
        out = probe_latest(rows, ledger=ledger, rpc=rpc)
        out["class"] = "(a) immutable per curve, read at latest"
        rescued = 0
        by_token = {r["token"]: r for r in rows}
        for entry in discovery:
            row = by_token.get(entry.get("token"))
            if row is None or row.get("latest_creator_tax_bps") is None:
                continue
            state = seed_state(int(row["latest_creator_tax_bps"]))
            states[entry["token"]] = {
                "token": entry["token"], "curve": entry["curve"],
                "launch_block": entry["launch_block"],
                "launch_block_hash": None,
                "launched_at": entry["launched_at"],
                "quote_asset": entry.get("quote_asset") or NATIVE_QUOTE,
                "snipe_start_bps": LAUNCH_SEED["snipe_start_bps"],
                "snipe_window_seconds": LAUNCH_SEED["snipe_window_seconds"],
                "graduation_seen": bool(entry.get("curve_completed")),
                "state": state.as_dict(),
                "source": "latest_block_immutable",
            }
            entry["initial_state_source"] = "latest_block_immutable"
            entry["reasons"] = [r for r in entry["reasons"]
                                if r != "CREATOR_TAX_UNREADABLE"]
            entry["creator_tax_bps_at_latest"] = int(row["latest_creator_tax_bps"])
            rescued += 1
        still = len(need) - rescued
        out["rescued"] = rescued
        out["still_class_c"] = still
        (D11_STORE / "discovery.json").write_text(
            json.dumps(discovery, indent=1) + "\n")
        (D11_STORE / "initial_states.json").write_text(
            json.dumps(states, indent=1, sort_keys=True) + "\n")

        man = json.loads((D11_STORE / "MANIFEST.json").read_text())
        for name in ("discovery.json", "initial_states.json"):
            path = D11_STORE / name
            man["files"][name] = {"sha256": sha256_file(path),
                                  "bytes": path.stat().st_size}
        man["initial_states"]["from_latest_block_immutable"] = rescued
        man["initial_states"]["unavailable"] = (
            int(man["initial_states"]["unavailable"]) - rescued)
        man["initial_states"]["still_unsupported_class_c"] = still
        man["initial_states"]["state_source"] = "latest_block_immutable"
        man["state_substitution"] = {
            "amendment": report["amendment"],
            "substitutions": SUBSTITUTIONS,
            "verification_b": (report.get("verification_b") or {}).get(
                "matched_exactly"),
            "verification_b_checked": (report.get("verification_b") or {}).get(
                "checked"),
            "verification_a": {k: out.get(k) for k in
                               ("probed", "answered", "rescued",
                                "still_class_c")},
            "artifact": "experiments/d11/state_substitution.json",
        }
        (D11_STORE / "MANIFEST.json").write_text(json.dumps(man, indent=1) + "\n")
        ledger.flush()
        report["rescue"] = out
        OUT.write_text(json.dumps(report, indent=1) + "\n")
        print(json.dumps({k: v for k, v in out.items()
                          if k not in ("differed", "unanswered")}, indent=1))
        return 0

    raise SystemExit("pass --verify-offline, --probe-latest or --rescue")


if __name__ == "__main__":
    raise SystemExit(main())
