"""``LIVE_PAPER``: the wall-clock tick loop and its four ways to stop.

The endpoint is scripted (``tests.d10.scripted``, see its docstring): a chain
that produces a block a second on demand is exactly what a real node will not
do for a test, and a sixty-minute stop condition is exactly what a test cannot
wait for. **No number in this module is an observation of Robinhood Chain or of
PONS.** What is real: the whole client above the socket, the ledger and its
caps, the collector, the store, the normaliser, the block clock, the journal,
the checkpoint, the recovery rule and every line of
:class:`flytrade.pons.loop.LiveDriver`.

The stop conditions of addendum 15 — 60 minutes, 3,000 requests, the ``stop``
file flag and SIGTERM — are tested one by one, the last one against a real
process that is really signalled.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from flytrade import records as REC
from flytrade.market import Universe
from flytrade.pons import loop as LOOP
from flytrade.pons import paper as PAPER
from flytrade.pons.admission import AdmissionPolicy
from flytrade.pons.budget import RequestLedger
from flytrade.pons.collector import Collector, Finality
from flytrade.pons.manifest import load_manifest
from flytrade.pons.rpc import RpcClient
from flytrade.pons.seed import LAUNCH_SEED
from flytrade.pons.storage import ChainStore
from tests.d10 import scripted as S
from tests.d10 import test_loop as TL

ROOT = Path(__file__).resolve().parents[2]
URL = "https://nd-1-2-3.p2pify.com/deadbeefdeadbeefdeadbeefdeadbeef"
FINALITY = Finality(median_interval_s=1.0, confirm_depth=3,
                    safe_tag_supported=True, sample=3)


@pytest.fixture
def manifest():
    return load_manifest(ROOT / "experiments" / "d10" / "deployments.json")


class Clock:
    """A fake wall clock the driver's sleeps advance. Invented, like the chain."""

    def __init__(self, t0: float = 1_800_000_000.0):
        self.t = float(t0)
        self.slept = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        seconds = max(0.0, float(seconds))
        self.t += seconds
        self.slept += seconds


def pinned_launch(block: int, *, token=S.TOKEN, curve=S.CURVE) -> dict:
    """A launch on the **pinned** config, so its state is derivable."""
    return S.make_log(address=S.FACTORY, event=S.factory_event("TokenLaunched"),
                      indexed=[token, curve, S.BUYER],
                      data_values=[S.NATIVE,
                                   int(LAUNCH_SEED["launch_config_id"]),
                                   int(LAUNCH_SEED["graduation_threshold"])],
                      block=block)


def limits(**kw) -> LOOP.LiveLimits:
    base = dict(max_seconds=10, max_requests=5_000, reserve_requests=0,
                backfill_seconds=5, backfill_requests=100,
                backfill_wall_seconds=60)
    base.update(kw)
    return LOOP.LiveLimits(**base)


def stack(tmp_path, manifest, *, clock, lim=None, logs=None, name="live",
          head=1_000, run_cap=None):
    """A live driver over a scripted chain that ticks with ``clock``."""
    endpoint = S.TickingEndpoint(logs=logs or [], head=head, first=head - 200,
                                 clock=clock.now)
    lim = lim or limits()
    ledger = RequestLedger(tmp_path / "ledger.json", run_id=name,
                           run_cap=run_cap or lim.max_requests)
    rpc = RpcClient(URL, ledger, opener=endpoint)
    store = ChainStore(tmp_path / name / "chain").load()
    collector = Collector(rpc, manifest, store, finality=FINALITY,
                          chunk_blocks=500)
    driver = LOOP.LiveDriver(collector, finality=FINALITY, limits=lim,
                             label="scripted-live", now=clock.now,
                             sleep=clock.sleep)
    return endpoint, ledger, collector, driver


def drain(driver, cadence=2):
    """Run the tick loop to its stop, handing every cutoff its events."""
    cutoffs = []
    for cutoff in driver.ticks(cadence):
        cutoffs.append(cutoff)
        driver.advance(cutoff)
    return cutoffs


# ---------------------------------------------------------------- the ticks
def test_a_tick_is_the_head_two_filters_and_one_fill_anchor(tmp_path, manifest):
    clock = Clock()
    endpoint, ledger, collector, driver = stack(
        tmp_path, manifest, clock=clock, lim=limits(max_seconds=4))
    cutoffs = drain(driver, cadence=2)
    assert cutoffs, "the loop produced no tick at all"
    methods = [c[0] for c in endpoint.calls]
    assert set(methods) <= {"eth_getBlockByNumber", "eth_getLogs", "eth_call"}
    assert driver.ticks_done == len(cutoffs)
    # every cutoff is a real block timestamp, and they advance
    assert cutoffs == sorted(cutoffs)
    # the fill anchor is at or after cutoff + latency, which is what lets a
    # decision at the cutoff be priced at all
    assert driver.anchor["block_timestamp"] >= cutoffs[-1] + driver.latency_s
    assert driver.coverage_end_ts == driver.anchor["block_timestamp"]
    assert driver.block_clock.last_ts >= cutoffs[-1] + driver.latency_s


def test_it_stops_on_the_wall_clock_limit(tmp_path, manifest):
    clock = Clock()
    endpoint, ledger, collector, driver = stack(
        tmp_path, manifest, clock=clock, lim=limits(max_seconds=12))
    cutoffs = drain(driver, cadence=2)
    assert driver.stopped == "TIME_LIMIT"
    assert "12s" in driver.stop_detail
    assert 3 <= len(cutoffs) <= 7          # ~12 s of 2-second ticks
    assert clock.now() - driver.started_at >= 12


def test_it_stops_on_the_request_cap_before_the_budget_raises(tmp_path, manifest):
    clock = Clock()
    endpoint, ledger, collector, driver = stack(
        tmp_path, manifest, clock=clock,
        lim=limits(max_seconds=10_000, max_requests=20, reserve_requests=2,
                   backfill_requests=4))
    drain(driver, cadence=2)
    assert driver.stopped in ("REQUEST_CAP", "BACKFILL_REQUEST_CAP")
    assert ledger.run_attempts <= 20
    assert ledger.path.exists()


def test_it_stops_on_the_stop_file_flag(tmp_path, manifest):
    clock = Clock()
    flag = tmp_path / "stop"
    endpoint, ledger, collector, driver = stack(
        tmp_path, manifest, clock=clock,
        lim=limits(max_seconds=10_000, stop_file=str(flag)))
    driver.on_tick = lambda d: (flag.write_text("stop\n")
                                if d.ticks_done >= 2 else None)
    cutoffs = drain(driver, cadence=2)
    assert driver.stopped == "STOP_FILE"
    assert str(flag) in driver.stop_detail
    assert len(cutoffs) == 2


def test_an_endpoint_error_stops_the_run_and_nothing_retries(tmp_path, manifest):
    clock = Clock()
    endpoint, ledger, collector, driver = stack(
        tmp_path, manifest, clock=clock, lim=limits(max_seconds=10_000))
    driver.on_tick = lambda d: setattr(endpoint, "fail_after", len(endpoint.calls))
    drain(driver, cadence=2)
    assert driver.stopped == "RPC_TRANSPORT_FAILED"
    assert driver.errors and driver.errors[-1]["code"] == "RPC_TRANSPORT_FAILED"
    # one attempt, not two: there is no retry anywhere in this package
    failures = sum(1 for m, _ in endpoint.calls if m)          # every call made
    assert ledger.state["errors"] == 1
    assert failures == len(endpoint.calls)
    assert collector.store.cursor is not None                  # cursor on disk


def test_a_launch_is_held_until_its_first_trade_pins_the_creator_tax(tmp_path,
                                                                     manifest):
    """No state read per curve: the tax comes out of the trade's own integers."""
    clock = Clock()
    head = 1_000
    endpoint, ledger, collector, driver = stack(
        tmp_path, manifest, clock=clock, head=head,
        lim=limits(max_seconds=10_000, backfill_seconds=1))
    launch = pinned_launch(head + 2)
    endpoint.add(launch)
    ticks = driver.ticks(2)
    next(ticks)                                    # the launch arrives alone
    assert driver.launches_seen == 1
    assert driver.initial_states == {}, "released before its state was known"
    assert not [e for e in driver.pending
                if e.get("event") == "TokenLaunched"]
    endpoint.add(S.buy_log(driver.collector.cursor_block + 1, 10 ** 16,
                           10 ** 24, 10 ** 14, 2 * 10 ** 14, log_index=1))
    cutoff = next(ticks)
    record = driver.initial_states.get(S.TOKEN)
    assert record is not None, "the trade did not release the launch"
    assert record["source"] == "derived"
    assert record["state"]["creator_tax_bps"] == 200
    handed = driver.advance(cutoff)
    kinds = [e["event"] for e in handed]
    assert kinds[0] == "TokenLaunched" and "CurveBuy" in kinds
    ticks.close()
    assert ledger.state["by_method"].get("eth_call") is None   # no state read


# ------------------------------------------------------- the clean stop
class Credit(TL._FakeCredit):
    """The loop test's stub credit assigner, plus the two counters a real
    :meth:`flytrade.records.Journal.recover` restores from the checkpoint."""

    accepted = 0
    rejections: dict = {}


def live_loop(tmp_path, manifest, *, clock, lim, name="live", logs=None,
              head=1_000):
    """The real :class:`PonsLoop` over the live driver, on the stub brain."""
    endpoint, ledger, collector, driver = stack(
        tmp_path, manifest, clock=clock, lim=lim, name=name, logs=logs,
        head=head)
    mb = TL._FakeMB()
    credit = Credit(mb)
    journal = REC.Journal(tmp_path / name / "branch", mb=mb, credit=credit,
                          versions=TL._FakeJournal.versions)
    journal.save_checkpoint(last_settled_episode=-1)
    loop = LOOP.PonsLoop(
        driver=driver, run=TL._FakeRunner(), mb=mb, credit=credit,
        journal=journal, encoder=TL.FakeEncoder(),
        admission=AdmissionPolicy(require_coverage=False),
        execution=PAPER.PonsPaperExecution(), policy=TL._FakePolicy(),
        universe=Universe(), mode=LOOP.MODE_LIVE, learning=LOOP.LEARN,
        branch="live", run_id=name, cadence=2, log=lambda *a, **k: None)
    return endpoint, ledger, collector, driver, journal, loop


def test_a_clean_stop_persists_cursor_ledger_journal_and_checkpoint(tmp_path,
                                                                    manifest):
    clock = Clock()
    endpoint, ledger, collector, driver, journal, loop = live_loop(
        tmp_path, manifest, clock=clock, lim=limits(max_seconds=8))
    endpoint.add(pinned_launch(1_002))
    out = loop.run_branch()

    assert driver.stopped == "TIME_LIMIT"
    cursor = json.loads((tmp_path / "live" / "chain" / "cursor.json").read_text())
    assert cursor["chain_id"] == LOOP.CHAIN_ID
    assert cursor["block_number"] == collector.cursor_block
    assert cursor["confirmed_block"] is not None
    ledger_on_disk = json.loads(ledger.path.read_text())
    assert ledger_on_disk["attempts"] == ledger.attempts > 0
    assert journal.checkpoint_path.exists()
    assert journal.checkpoint_digest() == out["end_digest"]
    lines = [json.loads(line) for line in
             journal.log.path.read_text().splitlines() if line.strip()]
    boundaries = [e for e in lines if e["kind"] == "PARTITION"]
    assert [b["boundary"] for b in boundaries] == ["start", "end"]
    assert boundaries[0]["partition"] == "LIVE"
    assert all(e.get("mode") == LOOP.MODE_LIVE for e in lines
               if e["kind"] in ("ROUND", "DECISION", "PARTITION", "DISCOVERY"))
    assert out["mode"] == LOOP.MODE_LIVE and out["ticks"] == driver.ticks_done


def test_a_restarted_live_run_resumes_from_its_own_cursor_and_checkpoint(
        tmp_path, manifest):
    clock = Clock()
    first = live_loop(tmp_path, manifest, clock=clock, lim=limits(max_seconds=6))
    first[0].add(pinned_launch(1_002))
    out_a = first[5].run_branch()
    cursor_a = first[2].cursor_block
    digest_a = first[4].checkpoint_digest()
    raw_a = (tmp_path / "live" / "chain" / "raw.jsonl").read_text().splitlines()
    assert cursor_a and out_a["ticks"] >= 1

    # a second process, over the same two directories
    clock2 = Clock(clock.now())
    second = live_loop(tmp_path, manifest, clock=clock2,
                       lim=limits(max_seconds=6), head=first[0].head)
    collector_b, journal_b = second[2], second[4]
    assert collector_b.cursor_block == cursor_a          # the cursor came back
    report = journal_b.recover()
    assert report["checkpoint_loaded"] is True
    assert journal_b.checkpoint_digest() == digest_a
    out_b = second[5].run_branch()
    raw_b = (tmp_path / "live" / "chain" / "raw.jsonl").read_text().splitlines()
    ids = [json.loads(line)["log_id"] for line in raw_b]
    assert len(ids) == len(set(ids)), "a restart re-ingested a log it had"
    assert raw_b[:len(raw_a)] == raw_a                   # append-only, unrewritten
    assert second[2].cursor_block >= cursor_a
    assert out_b["ticks"] >= 1


# ------------------------------------------------------------- the health
def test_the_health_block_carries_what_addendum_15_names(tmp_path, manifest):
    clock = Clock()
    endpoint, ledger, collector, driver = stack(
        tmp_path, manifest, clock=clock, lim=limits(max_seconds=6))
    drain(driver, cadence=2)
    health = driver.health(run_id="d10-live-001")
    for key in ("data", "cursor_block", "head_block", "lag_blocks",
                "lag_seconds", "requests", "last_error", "fresh",
                "confirmed_block", "confirm_depth", "stop"):
        assert key in health, key
    assert health["data"] == "LIVE"
    assert health["requests"]["run_cap"] == driver.limits.max_requests
    assert (health["requests"]["run_remaining"]
            == driver.limits.max_requests - ledger.run_attempts)
    assert health["requests"]["wave_cap"] == 10_000
    assert health["lag_blocks"] is not None


def test_fresh_is_false_once_the_last_confirmed_block_is_older_than_120s(
        tmp_path, manifest):
    clock = Clock()
    endpoint, ledger, collector, driver = stack(
        tmp_path, manifest, clock=clock, lim=limits(max_seconds=6))
    drain(driver, cadence=2)
    assert driver.health()["fresh"] is True
    assert driver.health()["confirmed_age_s"] <= LOOP.FRESH_SECONDS
    clock.t += LOOP.FRESH_SECONDS + 1           # the worker stalls; nothing ticks
    stale = driver.health()
    assert stale["fresh"] is False
    assert stale["confirmed_age_s"] > LOOP.FRESH_SECONDS
    assert "not fresh data" in stale["fresh_rule"]


def test_the_observer_serves_the_health_block_and_recomputes_fresh(tmp_path,
                                                                   monkeypatch):
    """The viewer's `fresh` is read-time, from the file, with no RPC."""
    sys.path.insert(0, str(ROOT / "observer"))
    import importlib
    for name in ("serve", "projection"):
        sys.modules.pop(name, None)
    serve = importlib.import_module("serve")
    run = "d10-live-test"
    directory = tmp_path / "runs" / run
    directory.mkdir(parents=True)
    monkeypatch.setitem(serve.ROOTS[3], "runs", tmp_path / "runs")
    now = int(time.time())
    (directory / "health.json").write_text(json.dumps(
        {"data": "LIVE", "confirmed_ts": now - 5, "cursor_block": 7,
         "head_block": 10, "requests": {"run_attempts": 3}}))
    fresh = serve.live_health(run)
    assert fresh["fresh"] is True and fresh["confirmed_age_s"] <= 120
    assert fresh["worker"]["alive"] is False        # no pid file
    (directory / "health.json").write_text(json.dumps(
        {"data": "LIVE", "confirmed_ts": now - 600}))
    assert serve.live_health(run)["fresh"] is False
    (directory / "worker.pid").write_text(f"{os.getpid()}\n")
    assert serve.live_health(run)["worker"]["alive"] is True


def test_the_viewer_has_no_control_that_can_choose_a_token_or_start_anything():
    """Addendum 13: no frontend control may select the winner or start a run."""
    page = (ROOT / "observer" / "index.html").read_text()
    import re
    calls = re.findall(r"fetch\(\s*([`'\"])(.*?)\1", page)
    assert calls, "no fetch at all: the check would be vacuous"
    for _, target in calls:
        assert target.startswith("/api/"), target
    for forbidden in ("method: 'POST'", 'method: "POST"', "method:'POST'",
                      "XMLHttpRequest", "navigator.sendBeacon", "WebSocket(",
                      "EventSource("):
        assert forbidden not in page, forbidden
    for name in sorted(p.name for p in (ROOT / "observer" / "static").iterdir()):
        text = (ROOT / "observer" / "static" / name).read_text()
        assert "fetch(" not in text and "POST" not in text


# ------------------------------------------------- the registered start
@pytest.fixture(scope="module")
def live_cfg():
    return json.loads((ROOT / "experiments" / "d10" / "live.json").read_text())


def test_the_start_refuses_a_checkpoint_that_is_not_the_registered_one(live_cfg):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "d10_run", ROOT / "experiments" / "d10" / "run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class Journal:
        def __init__(self, digest):
            self.digest = digest

        def checkpoint_digest(self):
            return self.digest

    want = live_cfg["starts_from"]["state_digest"]
    assert module.verify_start_digest(Journal(want), want) == want
    with pytest.raises(SystemExit) as caught:
        module.verify_start_digest(Journal("f" * 64), want)
    assert "refused" in str(caught.value)


def test_the_registered_start_is_the_committed_replay_branch_end_digest(live_cfg):
    """Continuity replay → live, pinned to the number `results.md` published."""
    results = (ROOT / "experiments" / "d10" / "results.md").read_text()
    digest = live_cfg["starts_from"]["state_digest"]
    assert len(digest) == 64
    assert f"`{digest[:12]}…`" in results
    checkpoint = ROOT / live_cfg["starts_from"]["checkpoint"]
    if not checkpoint.exists():                      # runs/ is gitignored
        pytest.skip("d10-001 is not on this disk")
    import numpy as np
    stored = np.load(checkpoint, allow_pickle=False)
    assert str(stored["digest"]) == digest


def test_the_live_registration_was_committed_before_the_live_run():
    """Register-then-compute for stage E, checked against git."""
    def git(*args):
        return subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True,
                              text=True, check=True).stdout.strip()

    commit = git("log", "-1", "--format=%H", "--", "experiments/d10/live.json")
    plan = git("log", "-1", "--format=%H", "--", "experiments/d10/LIVE_PLAN.md")
    if not commit or not plan:
        pytest.skip("not a git checkout, or the registration is not committed")
    assert commit == plan              # committed together, and alone
    files = git("show", "--name-only", "--format=", commit).split()
    assert sorted(files) == ["experiments/d10/LIVE_PLAN.md",
                             "experiments/d10/live.json"]
    when = int(git("show", "-s", "--format=%ct", commit))
    summary = (ROOT / "experiments" / "d10" / "runs" / "d10-live-001"
               / "summary.json")
    if not summary.exists():
        pytest.skip("d10-live-001 has not been run; its output is gitignored")
    assert summary.stat().st_mtime > when


# ------------------------------------------------------------- SIGTERM
SIGTERM_WORKER = '''
import json, sys, time
from pathlib import Path
sys.path.insert(0, {root!r})
sys.path.insert(0, {root!r} + "/upstream")
from flytrade.pons.budget import RequestLedger
from flytrade.pons.collector import Collector, Finality
from flytrade.pons.loop import LiveDriver, LiveLimits
from flytrade.pons.manifest import load_manifest
from flytrade.pons.rpc import RpcClient
from flytrade.pons.storage import ChainStore
from tests.d10 import scripted as S

out = Path({out!r})
endpoint = S.TickingEndpoint(logs=[], head=1000, first=800)
finality = Finality(median_interval_s=1.0, confirm_depth=3,
                    safe_tag_supported=True, sample=3)
ledger = RequestLedger(out / "ledger.json", run_id="sigterm", run_cap=5000)
rpc = RpcClient("https://x/y" + "z" * 20, ledger, opener=endpoint)
store = ChainStore(out / "chain").load()
collector = Collector(rpc, load_manifest({manifest!r}), store, finality=finality,
                      chunk_blocks=500)
driver = LiveDriver(collector, finality=finality,
                    limits=LiveLimits(max_seconds=600, backfill_seconds=2,
                                      backfill_requests=20),
                    label="scripted-live").install_signal_handlers()
ticks = 0
for cutoff in driver.ticks(1):
    driver.advance(cutoff)
    ticks += 1
    (out / "ready").write_text(str(ticks))
(out / "stopped.json").write_text(json.dumps(
    {{"stopped": driver.stopped, "detail": driver.stop_detail, "ticks": ticks,
      "cursor": collector.cursor_block}}))
'''


def test_sigterm_stops_a_real_worker_process_cleanly(tmp_path, manifest):
    """The fourth stop condition, against a process that is really signalled."""
    out = tmp_path / "worker"
    out.mkdir()
    script = tmp_path / "worker.py"
    script.write_text(SIGTERM_WORKER.format(
        root=str(ROOT), out=str(out),
        manifest=str(ROOT / "experiments" / "d10" / "deployments.json")))
    proc = subprocess.Popen([sys.executable, str(script)], cwd=str(ROOT),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True)
    deadline = time.time() + 60
    while time.time() < deadline and not (out / "ready").exists():
        time.sleep(0.2)
        if proc.poll() is not None:
            stdout, stderr = proc.communicate()
            raise AssertionError(f"the worker died early: {stderr[-2000:]}")
    assert (out / "ready").exists(), "the worker never completed a tick"
    proc.send_signal(signal.SIGTERM)
    stdout, stderr = proc.communicate(timeout=60)
    assert proc.returncode == 0, stderr[-2000:]
    stopped = json.loads((out / "stopped.json").read_text())
    assert stopped["stopped"] == "SIGNAL"
    assert stopped["detail"] == "SIGTERM"
    assert stopped["ticks"] >= 1
    assert (out / "chain" / "cursor.json").exists()
    assert json.loads((out / "ledger.json").read_text())["attempts"] > 0


def test_the_chain_store_is_not_offered_to_the_viewer_as_a_branch(tmp_path,
                                                                  monkeypatch):
    """A live run keeps its chain evidence beside its journal. Only one is a branch.

    Both files are called `events.jsonl`, and the collector's is not a record
    stream: projecting it would hand the viewer chain logs dressed as
    decisions. One line tells them apart.
    """
    sys.path.insert(0, str(ROOT / "observer"))
    import importlib
    for name in ("serve", "projection"):
        sys.modules.pop(name, None)
    serve = importlib.import_module("serve")
    run = tmp_path / "runs" / "d10-live-test"
    (run / "live").mkdir(parents=True)
    (run / "chain").mkdir()
    (run / "live" / "events.jsonl").write_text(
        json.dumps({"kind": "PARTITION", "boundary": "start"}) + "\n")
    (run / "chain" / "events.jsonl").write_text(
        json.dumps({"event": "CurveBuy", "source": "curve", "status": "OK",
                    "log_id": "0xabc:0xdef:1"}) + "\n")
    assert serve.is_journal(run / "live" / "events.jsonl") is True
    assert serve.is_journal(run / "chain" / "events.jsonl") is False
    monkeypatch.setitem(serve.ROOTS[3], "runs", tmp_path / "runs")
    rows = [r for r in serve.list_runs() if r["run_id"] == "d10-live-test"]
    assert rows and [b["branch"] for b in rows[0]["branches"]] == ["live"]
