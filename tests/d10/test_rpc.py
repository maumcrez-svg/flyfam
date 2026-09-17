"""The RPC client: what it refuses, what it hides, what it counts.

Scripted transport (``tests.d10.scripted``), real client. The three properties
under test are the three the wave's safety rests on: there is no way to sign
or broadcast anything, the endpoint never reaches a log or an artifact, and
every attempt is charged to a ledger that survives a restart.
"""

from __future__ import annotations

import json

import pytest

from flytrade.pons.budget import (ARCHIVE_DEPTH, BudgetStop, RequestLedger,
                                  archive_units)
from flytrade.pons.rpc import (ALLOWED_METHODS, MASK, RpcClient, RpcError, mask,
                               keccak256_hex, read_endpoint)
from tests.d10.scripted import ScriptedEndpoint

SECRET_URL = "https://nd-123-456-789.p2pify.com/ab12cd34ef56ab78cd90ef12ab34cd56"

#: The five methods whose absence is the "no signing or broadcast path" proof.
SIGNING_METHODS = ("eth_sendRawTransaction", "eth_sendTransaction", "eth_sign",
                   "personal_sign", "eth_accounts")


def client(tmp_path, endpoint=None, **kw):
    ledger = RequestLedger(tmp_path / "ledger.json", run_id="test", **kw)
    return RpcClient(SECRET_URL, ledger, opener=endpoint or ScriptedEndpoint())


def test_keccak256_of_the_empty_string(tmp_path):
    assert keccak256_hex(b"") == (
        "0xc5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470")


@pytest.mark.parametrize("method", SIGNING_METHODS)
def test_signing_methods_are_refused_before_a_socket_opens(tmp_path, method):
    endpoint = ScriptedEndpoint()
    rpc = client(tmp_path, endpoint)
    with pytest.raises(RpcError) as caught:
        rpc.call(method, [])
    assert caught.value.code == "RPC_METHOD_NOT_ALLOWED"
    assert endpoint.calls == []
    assert rpc.ledger.attempts == 0


def test_the_allowlist_has_exactly_six_read_methods():
    assert ALLOWED_METHODS == {"eth_chainId", "eth_blockNumber",
                               "eth_getBlockByNumber", "eth_getLogs",
                               "eth_getCode", "eth_call"}
    assert not ALLOWED_METHODS & set(SIGNING_METHODS)


def test_the_endpoint_is_masked_out_of_every_error_string(tmp_path):
    endpoint = ScriptedEndpoint()

    def leaky(url, body, timeout):
        raise OSError(f"connection to {url} refused")

    endpoint.__call__ = leaky
    rpc = client(tmp_path)
    rpc._opener = leaky
    with pytest.raises(RpcError) as caught:
        rpc.chain_id()
    text = str(caught.value)
    assert SECRET_URL not in text and "p2pify.com" not in text
    assert MASK in text
    assert rpc.masked_url == MASK


def test_masking_covers_host_key_and_any_url(tmp_path):
    masked = mask(f"boom at {SECRET_URL} on nd-123-456-789.p2pify.com", SECRET_URL)
    assert "p2pify" not in masked and "ab12cd34ef56ab78cd90ef12ab34cd56" not in masked


def test_the_ledger_records_every_attempt_including_errors(tmp_path):
    endpoint = ScriptedEndpoint()
    rpc = client(tmp_path, endpoint)
    rpc.chain_id()
    rpc.block_number()
    endpoint.fail_after = 2
    with pytest.raises(RpcError):
        rpc.chain_id()
    ledger = json.loads((tmp_path / "ledger.json").read_text())
    assert ledger["attempts"] == 3
    assert ledger["errors"] == 1
    assert ledger["by_method"]["eth_chainId"]["attempts"] == 2


def test_a_restart_does_not_reset_the_ledger(tmp_path):
    rpc = client(tmp_path)
    rpc.chain_id()
    again = RequestLedger(tmp_path / "ledger.json", run_id="second")
    assert again.attempts == 1
    assert again.run_attempts == 0


def test_archive_reads_are_weighted_at_two_units(tmp_path):
    assert archive_units(1_000, 1_000 + ARCHIVE_DEPTH) == 2
    assert archive_units(1_000, 1_000 + ARCHIVE_DEPTH - 1) == 1
    assert archive_units(None, 5) == 1
    endpoint = ScriptedEndpoint(head=100_000)
    rpc = client(tmp_path, endpoint)
    rpc.block("latest")                     # 1 unit, and sets the known head
    rpc.block(100_000 - ARCHIVE_DEPTH)      # 2 units: an archive read
    rpc.block(100_000 - 1)                  # 1 unit: recent
    ledger = json.loads((tmp_path / "ledger.json").read_text())
    assert ledger["attempts"] == 3
    assert ledger["units"] == 4


def test_http_429_halts_with_the_ledger_persisted(tmp_path):
    endpoint = ScriptedEndpoint(faults={"http_429"})
    rpc = client(tmp_path, endpoint)
    with pytest.raises(BudgetStop) as caught:
        rpc.chain_id()
    assert caught.value.code == "RPC_QUOTA_STOP"
    ledger = json.loads((tmp_path / "ledger.json").read_text())
    assert ledger["halted"]["reason"] == "HTTP_429"
    with pytest.raises(BudgetStop):
        rpc.chain_id()  # still halted; nothing retried, no second provider


def test_a_provider_quota_message_halts_and_keeps_the_words(tmp_path):
    endpoint = ScriptedEndpoint(faults={"quota"})
    rpc = client(tmp_path, endpoint)
    with pytest.raises(BudgetStop) as caught:
        rpc.chain_id()
    assert "monthly quota exceeded" in caught.value.detail
    ledger = json.loads((tmp_path / "ledger.json").read_text())
    assert "monthly quota exceeded" in ledger["halted"]["reason"]


def test_a_cap_stops_before_the_call_and_says_which(tmp_path):
    rpc = client(tmp_path, run_cap=2)
    rpc.chain_id()
    rpc.chain_id()
    with pytest.raises(BudgetStop) as caught:
        rpc.chain_id()
    assert caught.value.code == "RPC_BUDGET_STOP"
    assert "run cap 2" in caught.value.detail


def test_there_is_no_retry(tmp_path):
    endpoint = ScriptedEndpoint()
    endpoint.fail_after = 0
    rpc = client(tmp_path)
    rpc._opener = endpoint
    with pytest.raises(RpcError):
        rpc.chain_id()
    assert len(endpoint.calls) == 1


def test_a_mismatched_envelope_id_is_refused(tmp_path):
    def opener(url, body, timeout):
        return 200, json.dumps({"jsonrpc": "2.0", "id": 999, "result": "0x1"}).encode()

    ledger = RequestLedger(tmp_path / "ledger.json", run_id="test")
    rpc = RpcClient(SECRET_URL, ledger, opener=opener)
    with pytest.raises(RpcError) as caught:
        rpc.chain_id()
    assert caught.value.code == "RPC_INVALID_ENVELOPE"


def test_logs_outside_the_filter_are_refused(tmp_path):
    endpoint = ScriptedEndpoint()
    rpc = client(tmp_path, endpoint)
    endpoint.dispatch = lambda method, params: [{
        "address": "0x" + "9" * 40, "blockHash": "0x" + "0" * 64,
        "blockNumber": "0x1", "transactionHash": "0x" + "0" * 64,
        "transactionIndex": "0x0", "logIndex": "0x0", "topics": [], "data": "0x",
        "removed": False}]
    with pytest.raises(RpcError) as caught:
        rpc.logs(["0x" + "1" * 40], 1, 2)
    assert caught.value.code == "RPC_LOG_OUTSIDE_FILTER"


def test_the_endpoint_is_read_by_key_name_only(tmp_path):
    env = tmp_path / ".env"
    env.write_text("OTHER=nope\nMY_KEY='https://example.invalid/abc'\n#c=1\n")
    assert read_endpoint(str(env), "MY_KEY") == "https://example.invalid/abc"
    with pytest.raises(RpcError) as caught:
        read_endpoint(str(env), "ABSENT")
    assert caught.value.code == "RPC_NOT_CONFIGURED"
    with pytest.raises(RpcError) as caught:
        read_endpoint(str(tmp_path / "missing.env"), "MY_KEY")
    assert caught.value.code == "RPC_ENV_UNREADABLE"
