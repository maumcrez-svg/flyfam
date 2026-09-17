"""The imported replay dataset, checked from the files rather than the importer.

``data/pons/d10-replay-v1/`` is git-ignored (the existing ``data/*/`` rule), so
these tests skip when it has not been built. When it is there they re-derive
the claims instead of trusting ``experiments/d10/dataset_report.json``: the
digests in ``MANIFEST.json`` are recomputed, the normalisation is re-run from
``raw.jsonl`` and compared with ``events.jsonl``, and real settled trades are
re-priced from the reconstructed pre-trade state.

Build it with ``.venv/bin/python experiments/d10/import_donor.py``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from flytrade.pons.collector import Normaliser
from flytrade.pons.curve import (CurveReconstruction, CurveState,
                                 quote_curve_buy, quote_curve_sell,
                                 snipe_tax_bps)
from flytrade.pons.manifest import load_manifest

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "data" / "pons" / "d10-replay-v1"
MANIFEST = ROOT / "experiments" / "d10" / "deployments.json"

pytestmark = pytest.mark.skipif(
    not (DATASET / "MANIFEST.json").exists(),
    reason="replay dataset not built (experiments/d10/import_donor.py)")


def read_jsonl(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


@pytest.fixture(scope="module")
def manifest():
    return json.loads((DATASET / "MANIFEST.json").read_text())


@pytest.fixture(scope="module")
def events():
    return read_jsonl(DATASET / "events.jsonl")


@pytest.fixture(scope="module")
def initials():
    return json.loads((DATASET / "initial_states.json").read_text())


def test_the_manifest_digests_match_the_files_on_disk(manifest):
    for name, digest in manifest["outputs"].items():
        if name == "MANIFEST.json":
            continue
        actual = hashlib.sha256((DATASET / name).read_bytes()).hexdigest()
        assert actual == digest, name


def test_the_dataset_cost_no_requests(manifest):
    assert manifest["rpc_requests"] == 0


def test_every_consistency_check_passed(manifest):
    assert manifest["consistency"]
    failed = {k: v for k, v in manifest["consistency"].items() if not v["ok"]}
    assert failed == {}


def test_the_census_is_not_built_from_survivors(manifest):
    counts = manifest["counts"]
    assert counts["launches_total"] == 1136
    assert counts["launches_native_eth"] == 546
    assert counts["launches_quote_unsupported"] == 590
    discovery = json.loads((DATASET / "discovery.json").read_text())
    assert len(discovery) == counts["launches_total"]
    unsupported = [d for d in discovery if d["reason"] == "QUOTE_UNSUPPORTED"]
    assert len(unsupported) == counts["launches_quote_unsupported"]
    assert all(not d["in_replay_dataset"] for d in unsupported)


def test_replay_goes_through_the_same_normalisation_as_live(events):
    """Re-normalise the raw logs and demand the identical events back."""
    raws = read_jsonl(DATASET / "raw.jsonl")
    headers = {h["hash"]: h for h in read_jsonl(DATASET / "headers.jsonl")}
    normaliser = Normaliser(load_manifest(MANIFEST))
    for event in events:
        if event["event"] == "TokenLaunched":
            normaliser.register_market(event["curve"],
                                       {"token": event["token"],
                                        "deployment": event["deployment"]})
    by_id = {e["log_id"]: e for e in events}
    checked = 0
    for entry in raws[:2000]:
        header = headers[str(entry["log"]["blockHash"]).lower()]
        again = normaliser.normalise(
            entry["log"], {"number": hex(header["number"]), "hash": header["hash"],
                           "parentHash": header["parentHash"],
                           "timestamp": hex(header["timestamp"])})
        assert again == by_id[entry["log_id"]]
        checked += 1
    assert checked == 2000


FORBIDDEN = ("pnl", "outcome", "return", "profit", "reward", "exit_price",
             "realised", "realized")


def _keys(node, out):
    if isinstance(node, dict):
        for key, value in node.items():
            out.add(key)
            _keys(value, out)
    elif isinstance(node, list):
        for value in node:
            _keys(value, out)


def test_no_outcome_or_pnl_field_reached_the_dataset(events, initials, manifest):
    """The import reads launches, logs, headers and state reads. Nothing else.

    Checked on field names rather than on the text, because a *value* may
    legitimately say "quoteOut" — that is a trade leg the chain emitted — while
    a *key* named for an outcome would mean this dispatch looked at one.
    """
    keys: set[str] = set()
    _keys(manifest, keys)
    _keys(initials, keys)
    _keys(json.loads((DATASET / "discovery.json").read_text()), keys)
    for event in events[:5000]:
        _keys(event, keys)
    offenders = sorted(k for k in keys
                       if any(word in k.lower() for word in FORBIDDEN))
    assert offenders == []


def test_every_native_curve_reconciles_with_the_donors_state_read(manifest):
    recon = manifest["reconstruction"]
    assert recon["tokens"] == 546
    assert recon["reconciled"] == 546
    assert recon["mismatched"] == 0
    assert recon["failed"] == 0


def _state(payload: dict) -> CurveState:
    return CurveState(
        quote_reserve=int(payload["quote_reserve"]),
        token_reserve=int(payload["token_reserve"]),
        real_quote_reserve=int(payload["real_quote_reserve"]),
        sellable_tokens=int(payload["sellable_tokens"]),
        fee_bps=int(payload["fee_bps"]),
        creator_tax_bps=int(payload["creator_tax_bps"]),
        snipe_tax_bps=0, graduated=bool(payload["graduated"]))


def test_real_settled_trades_are_repriced_from_the_pre_trade_state(events, initials):
    """Settled trade evidence, re-derived here from the written dataset.

    For each of the first tokens with trades: rebuild the curve from its
    calibrated launch state, and at every ``CurveBuy`` and ``CurveSell``
    recompute what the contract must have paid. Four numbers have to agree on
    a buy — spent, the fee the log reports (base plus snipe), the creator tax
    and the tokens delivered — and three on a sell.
    """
    by_curve: dict[str, list[dict]] = {}
    for event in events:
        if event.get("source") == "curve":
            by_curve.setdefault(event["address"], []).append(event)
    buys = sells = 0
    tokens_checked = 0
    for token, meta in sorted(initials.items()):
        stream = sorted(by_curve.get(meta["curve"], []),
                        key=lambda e: (e["block_number"], e["tx_index"], e["log_index"]))
        trades = [e for e in stream if e["event"] in ("CurveBuy", "CurveSell")]
        if len(trades) < 2:
            continue
        recon = CurveReconstruction(
            _state(meta["state"]), launch_block=meta["launch_block"],
            launched_at=meta["launched_at"],
            snipe_start_bps=meta["snipe_start_bps"],
            snipe_window_seconds=meta["snipe_window_seconds"])
        charged = {}
        for event in stream:
            if event["block_number"] <= meta["launch_block"]:
                continue
            if event["event"] == "SnipeTaxCharged":
                charged.setdefault(event["tx_hash"], []).append(
                    int(event["args"]["amount"]))
        for event in stream:
            if event["block_number"] <= meta["launch_block"]:
                continue
            args = event["args"]
            before = recon.state
            if event["event"] == "CurveBuy":
                age = event["block_timestamp"] - meta["launched_at"]
                formula = snipe_tax_bps(meta["snipe_start_bps"],
                                        meta["snipe_window_seconds"], max(0, age))
                effective = formula if (not formula or charged.get(event["tx_hash"])) else 0
                quote = quote_curve_buy(before.with_snipe(effective),
                                        int(args["quoteIn"]))
                assert quote.spent == int(args["quoteIn"])
                assert quote.emitted_fee == int(args["fee"])
                assert quote.fee_creator == int(args["tax"])
                assert quote.tokens_out == int(args["tokensOut"])
                buys += 1
            elif event["event"] == "CurveSell":
                quote = quote_curve_sell(before, int(args["tokensIn"]))
                assert quote.quote_out == int(args["quoteOut"])
                assert quote.fee_base == int(args["fee"])
                assert quote.fee_creator == int(args["tax"])
                sells += 1
            recon.apply(event)
        tokens_checked += 1
        if buys >= 25 and sells >= 25:
            break
    assert buys >= 3 and sells >= 3, (buys, sells)
    assert tokens_checked >= 1


def test_the_snipe_decay_holds_on_real_charged_events(events, initials):
    """Where the chain charged a snipe tax, the ported formula reproduces it.

    ``SnipeTaxCharged`` reports the wei actually taken. Recomputing it from the
    fourteen-halvings decay, the block timestamp and the launch timestamp is a
    check of the decay against settled evidence, not against a fixture.
    """
    by_curve: dict[str, list[dict]] = {}
    for event in events:
        if event.get("source") == "curve":
            by_curve.setdefault(event["address"], []).append(event)
    checked = 0
    for token, meta in sorted(initials.items()):
        stream = by_curve.get(meta["curve"], [])
        charged = {e["tx_hash"]: int(e["args"]["amount"]) for e in stream
                   if e["event"] == "SnipeTaxCharged"}
        if not charged:
            continue
        cap = (10_000 - int(meta["state"]["fee_bps"])
               - int(meta["state"]["creator_tax_bps"]) - 100)
        for event in stream:
            if event["event"] != "CurveBuy" or event["tx_hash"] not in charged:
                continue
            age = max(0, event["block_timestamp"] - meta["launched_at"])
            bps = min(snipe_tax_bps(meta["snipe_start_bps"],
                                    meta["snipe_window_seconds"], age), cap)
            spent = int(event["args"]["quoteIn"])
            assert spent * bps // 10_000 == charged[event["tx_hash"]]
            checked += 1
            if checked >= 50:
                return
    assert checked >= 3, checked
