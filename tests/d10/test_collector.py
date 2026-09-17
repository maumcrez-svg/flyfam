"""The collector, against a scripted endpoint that misbehaves on demand.

Everything below the wire is real: the real client, ledger, store, decoder and
normaliser, on a real temporary directory. The endpoint is scripted
(``tests.d10.scripted``, see its docstring) because gaps, duplicates,
out-of-order deliveries, removed logs and a two-block reorg are exactly the
events one cannot ask a real node to perform.
"""

from __future__ import annotations

import json

import pytest

from flytrade.pons.budget import BudgetStop, RequestLedger
from flytrade.pons.collector import (BACKFILL_SECONDS, CHUNK_BLOCKS,
                                     HEADER_GRID_BLOCKS, MIN_CHUNK_BLOCKS,
                                     Collector, Finality, Normaliser,
                                     is_confirmed, measure_finality,
                                     read_initial_state)
from flytrade.pons.manifest import load_manifest
from flytrade.pons.rpc import RpcClient, RpcError, classify_provider_error
from flytrade.pons.storage import ChainStore
from tests.d10 import scripted as S

MANIFEST = None
URL = "https://nd-1-2-3.p2pify.com/deadbeefdeadbeefdeadbeefdeadbeef"


@pytest.fixture
def manifest():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    return load_manifest(root / "experiments" / "d10" / "deployments.json")


FINALITY = Finality(median_interval_s=0.1, confirm_depth=3,
                    safe_tag_supported=True, sample=3)


def build(tmp_path, manifest, endpoint, *, name="run", run_cap=5_000):
    ledger = RequestLedger(tmp_path / "ledger.json", run_id=name, run_cap=run_cap)
    rpc = RpcClient(URL, ledger, opener=endpoint)
    store = ChainStore(tmp_path / name / "chain").load()
    return Collector(rpc, manifest, store, finality=FINALITY)


def a_normal_chain():
    return [
        S.launch_log(101),
        S.buy_log(103, 10 ** 16, 10 ** 24, 10 ** 14, 2 * 10 ** 14, log_index=1),
        S.sell_log(104, 5 * 10 ** 23, 4 * 10 ** 15, 4 * 10 ** 13, 8 * 10 ** 13,
                   log_index=2),
        S.buy_log(106, 2 * 10 ** 16, 3 * 10 ** 24, 2 * 10 ** 14, 4 * 10 ** 14,
                  log_index=3),
    ]


def test_one_tick_queries_the_head_then_two_filters_however_many_curves(tmp_path,
                                                                          manifest):
    endpoint = S.ScriptedEndpoint(logs=a_normal_chain(), head=110)
    collector = build(tmp_path, manifest, endpoint)
    result = collector.tick(from_block=100)
    assert result["requests"] == 3          # latest, factory logs, curve logs
    assert result["events"] == 4
    assert [c[0] for c in endpoint.calls][:3] == [
        "eth_getBlockByNumber", "eth_getLogs", "eth_getLogs"]


def test_headers_are_bought_on_a_sparse_grid_not_one_per_event_block(tmp_path,
                                                                     manifest):
    """Reviewer decision 2: a header per 100 blocks, not one per event block.

    Dispatch 1 measured the header as the dominant live cost — a 30-second
    tick spans ~300 blocks at the measured 0.101 s interval and most of them
    carry something. The grid replaces "one ``eth_getBlockByNumber`` per
    distinct block that carried an event" with one per
    :data:`HEADER_GRID_BLOCKS` blocks plus the tick's ``latest``. Four event
    blocks inside one grid cell therefore cost one anchor, not four.
    """
    endpoint = S.ScriptedEndpoint(logs=a_normal_chain(), head=110)
    collector = build(tmp_path, manifest, endpoint)
    collector.tick(from_block=100)
    headers = [c for c in endpoint.calls
               if c[0] == "eth_getBlockByNumber" and c[1][0] != "latest"]
    assert [int(c[1][0], 16) for c in headers] == [100]      # the one anchor
    # The second tick pays nothing again for anchors it already has.
    before = len(endpoint.calls)
    endpoint.head = 111
    collector.tick(from_block=100)
    repeats = [c for c in endpoint.calls[before:]
               if c[0] == "eth_getBlockByNumber" and c[1][0] != "latest"]
    assert repeats == []


def test_an_interpolated_timestamp_says_so_and_declares_its_precision(tmp_path,
                                                                     manifest):
    """A derived timestamp is never allowed to look like a read one."""
    endpoint = S.ScriptedEndpoint(logs=a_normal_chain(), head=110)
    collector = build(tmp_path, manifest, endpoint)
    collector.tick(from_block=100)
    events = {e["block_number"]: e for e in collector.store.live_events()}
    for number in (101, 103, 104, 106):
        event = events[number]
        assert event["block_timestamp_interpolated"] is True
        assert event["block_timestamp_precision_s"] == pytest.approx(
            HEADER_GRID_BLOCKS * FINALITY.median_interval_s)
        # the scripted chain runs at exactly one second a block, so linear
        # interpolation between the two anchors reproduces it exactly
        assert event["block_timestamp"] == 1_700_000_000 + number


def test_a_block_with_its_own_header_is_exact_and_carries_no_flag(tmp_path,
                                                                 manifest):
    grid_at_event = S.ScriptedEndpoint(logs=[S.launch_log(200)], head=260)
    collector = build(tmp_path, manifest, grid_at_event)
    collector.tick(from_block=150)
    event = collector.store.live_events()[0]
    assert "block_timestamp_interpolated" not in event
    assert event["block_timestamp"] == 1_700_000_200


def test_a_range_refusal_halves_the_chunk_and_is_not_a_quota_halt(tmp_path,
                                                                  manifest):
    """Reviewer decision 1. The two provider refusals are different things."""

    class Refuser(S.ScriptedEndpoint):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.refused = []

        def dispatch(self, method, params):
            if method == "eth_getLogs":
                lo = int(str(params[0]["fromBlock"]), 16)
                hi = int(str(params[0]["toBlock"]), 16)
                if hi - lo + 1 > 50:
                    self.refused.append((lo, hi))
                    return {"__error__": {
                        "code": -32005,
                        "message": "logs matched by this request exceed the limit"}}
            return super().dispatch(method, params)

    endpoint = Refuser(logs=a_normal_chain(), head=300)
    collector = build(tmp_path, manifest, endpoint)
    got = collector.fetch_logs([S.FACTORY], 100, 300, chunk=200, label="factory")
    assert [int(str(g["blockNumber"]), 16) for g in got] == [101]
    assert endpoint.refused                       # it really did refuse first
    assert collector.range_retreats[0]["action"] == "halved"
    # nothing halted: the ledger is clean and the next call still works
    assert collector.rpc.ledger.halted() is None
    assert collector.rpc.ledger.state["by_method"]["eth_getLogs"]["errors"] >= 1


def test_a_range_refusal_that_survives_the_floor_stops_rather_than_looping(
        tmp_path, manifest):
    class AlwaysRefuses(S.ScriptedEndpoint):
        def dispatch(self, method, params):
            if method == "eth_getLogs":
                return {"__error__": {"code": -32005,
                                      "message": "block range is too large"}}
            return super().dispatch(method, params)

    endpoint = AlwaysRefuses(logs=[], head=300)
    collector = build(tmp_path, manifest, endpoint)
    with pytest.raises(RpcError) as caught:
        collector.fetch_logs([S.FACTORY], 100, 300, chunk=200, label="factory")
    assert caught.value.code == "RPC_RANGE_TOO_LARGE"
    assert collector.range_retreats[-1]["chunk"] == MIN_CHUNK_BLOCKS
    assert collector.rpc.ledger.halted() is None


def test_a_quota_message_still_halts_and_a_range_message_never_does():
    assert classify_provider_error("monthly quota exceeded") == "QUOTA"
    assert classify_provider_error("You have been rate-limited") == "QUOTA"
    assert classify_provider_error(
        "logs matched by this request exceed the limit") == "RANGE"
    assert classify_provider_error("block range too large") == "RANGE"
    assert classify_provider_error(
        "query returned more than 10000 results") == "RANGE"
    assert classify_provider_error("execution reverted") is None


def test_the_confirmation_check_rereads_the_nearest_grid_header_below(tmp_path,
                                                                     manifest):
    """Addendum 7 as amended: one re-read of the anchor, not of the block."""
    endpoint = S.ScriptedEndpoint(logs=a_normal_chain(), head=110)
    collector = build(tmp_path, manifest, endpoint)
    collector.tick(from_block=100)
    before = len(endpoint.calls)
    verdict = collector.confirmation(103, head=1_000, safe_block=900)
    assert verdict["confirmed"] is True
    assert verdict["anchor"] == 100
    assert verdict["anchor_hash_matches"] is True
    reread = [c for c in endpoint.calls[before:] if c[0] == "eth_getBlockByNumber"]
    assert len(reread) == 1 and int(reread[0][1][0], 16) == 100
    # a block that is not deep enough is not confirmed, and costs no request
    before = len(endpoint.calls)
    assert collector.confirmation(999, head=1_000, safe_block=900)["confirmed"] is False
    assert len(endpoint.calls) == before


def test_a_reorg_under_the_anchor_unconfirms_the_block(tmp_path, manifest):
    endpoint = S.ScriptedEndpoint(logs=a_normal_chain(), head=110)
    collector = build(tmp_path, manifest, endpoint)
    collector.tick(from_block=100)
    endpoint.fork = "b"                     # the node now serves another branch
    verdict = collector.confirmation(103, head=1_000, safe_block=900)
    assert verdict["confirmed"] is False
    assert verdict["anchor_hash_matches"] is False
    assert verdict["reason"] == "REORG_BELOW_BLOCK"


def test_a_launch_in_the_same_batch_makes_its_own_curve_logs_readable(tmp_path, manifest):
    endpoint = S.ScriptedEndpoint(logs=a_normal_chain(), head=110)
    collector = build(tmp_path, manifest, endpoint)
    collector.tick(from_block=100)
    kinds = [e["event"] for e in collector.store.live_events()]
    assert kinds == ["TokenLaunched", "CurveBuy", "CurveSell", "CurveBuy"]
    assert all(e["status"] == "OK" for e in collector.store.live_events())


def test_duplicate_deliveries_collapse_on_the_log_id(tmp_path, manifest):
    endpoint = S.ScriptedEndpoint(logs=a_normal_chain(), head=110,
                                  faults={"duplicate"})
    collector = build(tmp_path, manifest, endpoint)
    result = collector.tick(from_block=100)
    assert result["events"] == 4
    assert len(collector.store.live_events()) == 4


def test_out_of_order_delivery_is_sorted_before_anything_reads_it(tmp_path, manifest):
    endpoint = S.ScriptedEndpoint(logs=a_normal_chain(), head=110, faults={"shuffle"})
    collector = build(tmp_path, manifest, endpoint)
    collector.tick(from_block=100)
    numbers = [e["block_number"] for e in collector.store.live_events()]
    assert numbers == sorted(numbers)
    assert [e["event"] for e in collector.store.live_events()][0] == "TokenLaunched"


def test_no_block_falls_between_two_ticks(tmp_path, manifest):
    """The cursor is the contract: tick two starts where tick one stopped.

    A log that only *appears* after its block was already passed is a
    different matter, and the one the confirmation rule exists for; this is
    about the range arithmetic, which must leave no hole.
    """
    logs = a_normal_chain()
    endpoint = S.ScriptedEndpoint(logs=logs, head=102)
    collector = build(tmp_path, manifest, endpoint)
    collector.tick(from_block=100)
    assert collector.cursor_block == 102
    assert [e["block_number"] for e in collector.store.live_events()] == [101]
    endpoint.head = 108
    result = collector.tick()
    assert result["from"] == 103
    assert [e["block_number"] for e in collector.store.live_events()] == [101, 103, 104, 106]


def test_a_removed_log_orphans_its_block_and_rewinds(tmp_path, manifest):
    endpoint = S.ScriptedEndpoint(logs=a_normal_chain(), head=110)
    collector = build(tmp_path, manifest, endpoint)
    collector.tick(from_block=100)
    assert len(collector.store.live_events()) == 4
    gone = S.buy_log(106, 2 * 10 ** 16, 3 * 10 ** 24, 2 * 10 ** 14, 4 * 10 ** 14,
                     log_index=3, removed=True)
    endpoint.logs = [gone]
    endpoint.head = 111
    result = collector.tick(from_block=106)
    assert result["reorg"] is True
    assert result["orphaned"]
    live = collector.store.live_events()
    assert [e["block_number"] for e in live] == [101, 103, 104]
    # The raw evidence is kept: nothing is deleted, only disbelieved.
    raw = (collector.store.raw_path).read_text().strip().splitlines()
    assert any('"blockNumber": "0x6a"' in line for line in raw)


def test_a_reorg_replacing_the_last_two_blocks_orphans_both(tmp_path, manifest):
    endpoint = S.ScriptedEndpoint(logs=a_normal_chain(), head=110)
    collector = build(tmp_path, manifest, endpoint)
    collector.tick(from_block=100)
    assert len(collector.store.live_events()) == 4
    # Blocks 104 and 106 are replaced by a competing fork "b".
    removed = [
        S.sell_log(104, 5 * 10 ** 23, 4 * 10 ** 15, 4 * 10 ** 13, 8 * 10 ** 13,
                   log_index=2),
        S.buy_log(106, 2 * 10 ** 16, 3 * 10 ** 24, 2 * 10 ** 14, 4 * 10 ** 14,
                  log_index=3),
    ]
    for log in removed:
        log["removed"] = True
    replacement = S.buy_log(104, 10 ** 16, 10 ** 24, 10 ** 14, 2 * 10 ** 14,
                            log_index=9, fork="b")
    endpoint.logs = removed + [replacement]
    endpoint.head = 112
    endpoint.fork = "b"          # the node now serves the winning branch
    result = collector.tick(from_block=104)
    assert result["reorg"] is True
    live = collector.store.live_events()
    assert [e["block_number"] for e in live] == [101, 103, 104]
    assert live[-1]["log_index"] == 9         # the fork-b log, not the orphaned one
    assert live[-1]["block_hash"] == S.block_hash(104, "b")


def test_a_restart_mid_tick_reproduces_the_same_normalised_stream(tmp_path, manifest):
    logs = a_normal_chain()
    endpoint = S.ScriptedEndpoint(logs=logs, head=110)
    whole = build(tmp_path, manifest, endpoint, name="whole")
    whole.tick(from_block=100)
    reference = [dict(e) for e in whole.store.live_events()]

    endpoint_a = S.ScriptedEndpoint(logs=logs, head=104)
    torn = build(tmp_path, manifest, endpoint_a, name="torn")
    torn.tick(from_block=100)
    cursor = json.loads((tmp_path / "torn" / "chain" / "cursor.json").read_text())
    assert cursor["block_number"] == 104

    # A new process, a new store object, the same directory: resume and finish.
    endpoint_b = S.ScriptedEndpoint(logs=logs, head=110)
    resumed = build(tmp_path, manifest, endpoint_b, name="torn")
    resumed.tick()
    assert [(e["log_id"], e["event"], e["args"]) for e in resumed.store.live_events()] \
        == [(e["log_id"], e["event"], e["args"]) for e in reference]


def test_a_budget_stop_mid_tick_leaves_the_cursor_on_disk(tmp_path, manifest):
    endpoint = S.ScriptedEndpoint(logs=a_normal_chain(), head=110)
    collector = build(tmp_path, manifest, endpoint, run_cap=2)
    with pytest.raises(BudgetStop) as caught:
        collector.tick(from_block=100)
    assert caught.value.code == "RPC_BUDGET_STOP"
    ledger = json.loads((tmp_path / "ledger.json").read_text())
    assert ledger["attempts"] == 2
    # The head was fetched and stored before the stop, so a resume knows where
    # it was even though this tick produced no events.
    assert (tmp_path / "run" / "chain" / "headers.jsonl").exists()


def test_the_tracked_set_drops_completed_curves_and_keeps_held_ones(tmp_path, manifest):
    logs = a_normal_chain()
    endpoint = S.ScriptedEndpoint(logs=logs, head=110)
    collector = build(tmp_path, manifest, endpoint)
    collector.tick(from_block=100)
    launch_ts = 1_700_000_000 + 101
    assert collector.tracked(launch_ts) == [S.CURVE]
    # An hour later it has aged out, unless we hold it.
    assert collector.tracked(launch_ts + 3_601) == []
    collector.held.add(S.CURVE)
    assert collector.tracked(launch_ts + 3_601) == [S.CURVE]
    # Completion removes it either way: the route has changed.
    collector.completed.add(S.CURVE)
    assert collector.tracked(launch_ts) == []


def test_a_log_from_an_address_we_never_launched_is_not_decoded(tmp_path, manifest):
    stranger = S.buy_log(103, 1, 2, 3, 4)
    stranger["address"] = "0x" + "9" * 40
    endpoint = S.ScriptedEndpoint(logs=[stranger], head=110)
    collector = build(tmp_path, manifest, endpoint)
    normalised = Normaliser(manifest).normalise(stranger, endpoint.header(103))
    assert normalised["status"] == "UNKNOWN_SOURCE"
    assert normalised["event"] == "unmapped"
    assert normalised["args"] == {}


def test_a_log_from_an_unsupported_deployment_is_recorded_with_its_reason(manifest):
    v1 = S.buy_log(103, 1, 2, 3, 4)
    v1["address"] = manifest.by_id("pons-v1").address
    normalised = Normaliser(manifest).normalise(
        v1, S.ScriptedEndpoint().header(103))
    assert normalised["status"] == "UNSUPPORTED"
    assert normalised["deployment"] == "pons-v1"
    assert "Uniswap V3" in normalised["reason"]


def test_a_header_that_does_not_match_the_log_is_refused(manifest):
    log = S.buy_log(103, 1, 2, 3, 4)
    wrong = S.ScriptedEndpoint(fork="b").header(103)
    with pytest.raises(Exception) as caught:
        Normaliser(manifest).normalise(log, wrong)
    assert "HEADER_HASH_MISMATCH" in str(caught.value)


# ------------------------------------------------------------------ finality
def test_the_block_interval_is_measured_and_the_depth_follows_from_it():
    headers = [{"number": 1_000, "timestamp": 1_000_000},
               {"number": 2_000, "timestamp": 1_000_100},
               {"number": 3_000, "timestamp": 1_000_200}]
    finality = measure_finality(headers, safe_tag_supported=True)
    assert finality.median_interval_s == pytest.approx(0.1)
    assert finality.confirm_depth == 600           # 60 seconds of blocks
    assert finality.as_dict()["confirm_seconds"] == 60


def test_confirmation_needs_both_depth_and_the_safe_tag_when_it_exists():
    finality = Finality(0.1, 600, safe_tag_supported=True, sample=3)
    assert not is_confirmed(999_900, head=1_000_000, finality=finality,
                            safe_block=999_000)
    assert not is_confirmed(999_100, head=1_000_000, finality=finality,
                            safe_block=999_000)      # deep enough, not yet safe
    assert is_confirmed(998_000, head=1_000_000, finality=finality,
                        safe_block=999_000)
    without = Finality(0.1, 600, safe_tag_supported=False, sample=3)
    assert is_confirmed(999_100, head=1_000_000, finality=without, safe_block=None)


def test_the_backfill_is_bounded_to_one_hour_of_blocks(tmp_path, manifest):
    endpoint = S.ScriptedEndpoint(logs=[], head=10 ** 6)
    collector = build(tmp_path, manifest, endpoint)
    start = collector.backfill_start(10 ** 6, 1_700_000_000)
    assert 10 ** 6 - start == round(BACKFILL_SECONDS / FINALITY.median_interval_s)


def test_a_large_range_is_chunked_and_a_small_one_is_not(tmp_path, manifest):
    endpoint = S.ScriptedEndpoint(logs=[], head=10 ** 6)
    collector = build(tmp_path, manifest, endpoint)
    assert collector._ranges(1, 50) == [(1, 50)]
    chunks = collector._ranges(1, 500)
    assert len(chunks) == (500 + CHUNK_BLOCKS - 1) // CHUNK_BLOCKS
    assert all(hi - lo + 1 <= CHUNK_BLOCKS for lo, hi in chunks)
    assert chunks[0][0] == 1 and chunks[-1][1] == 500


# ------------------------------------------------------- lazy state reads
def test_the_initial_state_is_read_once_per_curve_and_then_cached(tmp_path, manifest):
    reserves = ("0x" + S.word(10 ** 18) + S.word(10 ** 27))

    class Reader(S.ScriptedEndpoint):
        def dispatch(self, method, params):
            if method != "eth_call":
                return super().dispatch(method, params)
            data = params[0]["data"]
            from flytrade.pons.collector import selector
            if data == selector("getReserves()"):
                return reserves
            if data == selector("realQuoteReserve()"):
                return "0x" + S.word(5 * 10 ** 17)
            if data == selector("sellableTokens()"):
                return "0x" + S.word(5 * 10 ** 26)
            if data == selector("feeBps()"):
                return "0x" + S.word(100)
            if data == selector("creatorTaxBps()"):
                return "0x" + S.word(200)
            if data == selector("snipeTaxStartBps()"):
                return "0x" + S.word(9_900)
            if data == selector("snipeTaxSeconds()"):
                return "0x" + S.word(3)
            if data == selector("launchedAt()"):
                return "0x" + S.word(1_700_000_101)
            return "0x" + S.word(0)

    endpoint = Reader(head=110)
    ledger = RequestLedger(tmp_path / "ledger.json", run_id="reads")
    rpc = RpcClient(URL, ledger, opener=endpoint)
    cache: dict = {}
    state, meta = read_initial_state(rpc, S.CURVE, 101, cache=cache)
    assert state.quote_reserve == 10 ** 18
    assert state.sellable_tokens == 5 * 10 ** 26
    assert meta["snipe_start_bps"] == 9_900 and meta["snipe_window_seconds"] == 3
    assert ledger.attempts == 9
    read_initial_state(rpc, S.CURVE, 101, cache=cache)
    assert ledger.attempts == 9            # cached: a second admission is free


def test_the_known_selectors_match_the_donor_observed_calldata():
    from flytrade.pons.collector import selector
    assert selector("getReserves()") == "0x0902f1ac"
    assert selector("realQuoteReserve()") == "0x4f1f58fd"
