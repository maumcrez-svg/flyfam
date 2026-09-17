"""D11-001 addendum 4 — the loopback budget, separated from Chainstack.

Three things are asserted, in the order the addendum names them: **host
classification**, **cap independence** and **refusal without the flag**. A
fourth, cheaper than it looks, is that every D5-D10 ledger still behaves
exactly as it did — the new scope defaults to ``"any"``, which refuses nothing.

Nothing here opens a socket: the classification is made from a URL string and
the refusal happens at :class:`flytrade.pons.rpc.RpcClient` construction,
before any transport exists.
"""

from __future__ import annotations

import json

import pytest

from flytrade.pons import budget as B
from flytrade.pons.rpc import RpcClient


# ------------------------------------------------------- host classification
@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8645",
    "http://127.0.0.1:8547/",
    "HTTP://127.0.0.1:8545",
    "http://localhost:8545",
    "http://LocalHost:8545/rpc",
    "http://[::1]:8547",
    "https://127.0.0.1:8547",
])
def test_a_loopback_host_is_loopback(url):
    assert B.endpoint_class(url) == B.LOOPBACK


@pytest.mark.parametrize("url", [
    "https://nd-000-000-000.p2pify.com/deadbeef",
    "http://192.168.1.10:8545",
    "http://10.0.0.4:8547",
    "http://example.com:8545",
    "https://127.0.0.1.evil.example/rpc",
    "http://0.0.0.0:8545",
])
def test_anything_else_is_remote(url):
    assert B.endpoint_class(url) == B.REMOTE


def test_the_classification_never_resolves_a_name():
    """A host that *resolves* to loopback is still remote.

    A safety rule that must hold before a socket is opened cannot have its
    answer decided by a DNS reply, so the classification reads the URL and
    nothing else.
    """
    assert B.endpoint_class("http://localtest.me:8545") == B.REMOTE


# ------------------------------------------------------ refusal and the flag
def test_a_loopback_ledger_refuses_a_remote_endpoint_before_any_socket(tmp_path):
    ledger = B.RequestLedger(tmp_path / "local.json", run_id="probe",
                             scope=B.LOOPBACK, allow_remote=False)
    with pytest.raises(B.BudgetStop) as excinfo:
        RpcClient("https://nd-1.p2pify.com/key", ledger)
    assert excinfo.value.code == B.REMOTE_REFUSED
    assert "--allow-remote" in excinfo.value.detail
    # and it refused before it could spend anything
    assert ledger.attempts == 0
    assert ledger.run_attempts == 0


def test_the_same_ledger_accepts_the_local_node(tmp_path):
    ledger = B.RequestLedger(tmp_path / "local.json", run_id="probe",
                             scope=B.LOOPBACK, allow_remote=False)
    client = RpcClient("http://127.0.0.1:8645", ledger)
    assert client.endpoint_class == B.LOOPBACK
    assert ledger.endpoint_class == B.LOOPBACK


def test_allow_remote_is_the_only_way_past_the_refusal(tmp_path):
    ledger = B.RequestLedger(tmp_path / "local.json", run_id="probe",
                             scope=B.LOOPBACK, allow_remote=True)
    assert RpcClient("https://nd-1.p2pify.com/key", ledger).endpoint_class == B.REMOTE


def test_a_d10_ledger_is_unchanged_and_refuses_nothing(tmp_path):
    """Every D5-D10 ledger is opened with the default scope and still works."""
    ledger = B.RequestLedger(tmp_path / "rpc_ledger.json", run_id="d10-live-001")
    assert ledger.scope == B.ANY
    assert RpcClient("https://nd-1.p2pify.com/key", ledger).endpoint_class == B.REMOTE
    assert RpcClient("http://127.0.0.1:8645", ledger).endpoint_class == B.LOOPBACK


def test_an_unknown_scope_is_refused_at_construction(tmp_path):
    with pytest.raises(ValueError):
        B.RequestLedger(tmp_path / "x.json", run_id="r", scope="wherever")


# ------------------------------------------------------------ independence
def test_the_two_ledgers_share_no_counter(tmp_path):
    """Spending on the local node leaves the Chainstack ledger untouched."""
    remote_path = tmp_path / "rpc_ledger.json"
    local_path = tmp_path / "rpc_ledger_local.json"
    remote = B.RequestLedger(remote_path, run_id="d10-live-001")
    remote.record("eth_getLogs", units=2)
    remote.record("eth_getLogs", units=2)

    local = B.RequestLedger(local_path, run_id="d11-001-backfill",
                            wave_cap=22_200, run_cap=20_000, day_cap=22_200,
                            scope=B.LOOPBACK, allow_remote=False)
    for _ in range(50):
        local.record("eth_getBlockByNumber", units=1)

    assert json.loads(remote_path.read_text())["attempts"] == 2
    assert json.loads(local_path.read_text())["attempts"] == 50
    # and the caps are each ledger's own
    assert json.loads(remote_path.read_text())["caps"] == {
        "wave": B.WAVE_CAP, "run": B.RUN_CAP, "day": B.DAY_CAP}
    assert json.loads(local_path.read_text())["caps"] == {
        "wave": 22_200, "run": 20_000, "day": 22_200}


def test_the_chainstack_caps_did_not_move():
    """Addendum 4: the remote caps are unchanged by this wave."""
    assert (B.WAVE_CAP, B.RUN_CAP, B.DAY_CAP) == (10_000, 5_000, 10_000)


def test_a_loopback_cap_stops_the_loopback_ledger_and_nothing_else(tmp_path):
    local = B.RequestLedger(tmp_path / "local.json", run_id="probe",
                            wave_cap=22_200, run_cap=3, day_cap=22_200,
                            scope=B.LOOPBACK, allow_remote=False)
    for _ in range(3):
        local.reserve("eth_chainId")
        local.record("eth_chainId", units=1)
    with pytest.raises(B.BudgetStop) as excinfo:
        local.reserve("eth_chainId")
    assert excinfo.value.code == "RPC_BUDGET_STOP"
    assert "run cap 3" in excinfo.value.detail

    remote = B.RequestLedger(tmp_path / "remote.json", run_id="d10")
    remote.reserve("eth_chainId")           # entirely unaffected


def test_the_scope_and_class_are_written_into_the_ledger_file(tmp_path):
    path = tmp_path / "local.json"
    ledger = B.RequestLedger(path, run_id="probe", scope=B.LOOPBACK,
                             allow_remote=False)
    RpcClient("http://127.0.0.1:8645", ledger)
    ledger.flush()
    state = json.loads(path.read_text())
    assert state["scope"] == B.LOOPBACK
    assert state["endpoint_class"] == B.LOOPBACK
