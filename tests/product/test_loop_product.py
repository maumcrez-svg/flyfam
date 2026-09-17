"""The continuous loop: no clock stop, a rolling hour, backoff, resume, CREDIT.

P1 addendum 3, paragraph by paragraph. The chain is scripted
(``tests/product/harness.py``), the clock is fake, and **no number here is an
observation of anything**. What is real: the driver, the collector, the store,
the journal, the checkpoint, the recovery rule, the paper execution, the curve
quotes, the feed and the state file.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from flytrade import state as S
from flytrade.pons.rpc import RANGE_TOO_LARGE, RpcError
from flytrade.product import live as PL
from tests.d10 import scripted as SC
from tests.product import harness as H

ROOT = Path(__file__).resolve().parents[2]
REGISTERED = "ba95b60503d658e989b649ecd3994264791fbead92f0bdacfd555e5d86ab61f5"
GRAPH = "8feb08a0d2a80cbcf69328f9707d5dd748d73d2e12246526d96e48d995f843b9"


def chain(head: int = 1_000, n_trades: int = 200):
    return [H.pinned_launch(head + 2)] + H.trades(head + 5, n_trades, every=10)


# ------------------------------------------------------------ 3(a) stopping
def test_no_wall_clock_stop_exists_in_the_product_driver(tmp_path):
    built = H.stack(tmp_path, logs=chain())
    driver = built["driver"]
    driver.started_at = driver._now() - 10 ** 6
    driver.deadline = driver._now() - 1                 # long past
    driver.collector.rpc.ledger.run_attempts = 10 ** 6  # far past D10's cap
    assert driver.stop_reason() is None
    assert driver.health()["stop"]["deadline_epoch"] is None
    assert driver.health()["stop"]["seconds_left"] is None


def test_the_stop_file_stops_it(tmp_path):
    built = H.stack(tmp_path, logs=chain())
    assert built["driver"].stop_reason() is None
    Path(built["paths"]["stop"]).write_text("stop\n")
    assert built["driver"].stop_reason()[0] == "STOP_FILE"


def test_a_signal_stops_it(tmp_path):
    """The handler is really installed, and it really is what stops the loop.

    A real ``SIGTERM`` against a real worker is exercised twice over: by
    ``tests/d10/test_live.py`` on the driver this one inherits, and by the
    proof run of this wave, which was signalled at its midpoint and restarted.
    """
    import signal
    before = (signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT))
    try:
        built = H.stack(tmp_path, logs=chain())
        driver = built["driver"].install_signal_handlers()
        for sig in (signal.SIGTERM, signal.SIGINT):
            handler = signal.getsignal(sig)
            assert callable(handler) and handler not in (signal.SIG_DFL,
                                                         signal.SIG_IGN)
        # the handler records the name and nothing else: a signal that killed
        # the process where it stood could leave a half-written tick
        signal.getsignal(signal.SIGTERM)(int(signal.SIGTERM), None)
        assert driver.signalled == "SIGTERM"
        assert driver.stop_reason() == ("SIGNAL", "SIGTERM")
    finally:
        signal.signal(signal.SIGTERM, before[0])
        signal.signal(signal.SIGINT, before[1])


def test_a_provider_halt_stops_it(tmp_path):
    built = H.stack(tmp_path, logs=chain())
    built["driver"].collector.rpc.ledger.halt("PROVIDER_QUOTA (scripted)")
    assert built["driver"].stop_reason()[0] == "RPC_QUOTA_STOP"


def test_a_chain_that_is_not_4663_refuses_the_start(tmp_path, monkeypatch):
    cfg = H.config(tmp_path)
    from tests.product.harness import RUN
    clock = H.Clock()
    endpoint = SC.TickingEndpoint(logs=[], head=1_000, first=800,
                                  clock=clock.now, chain_id=1)
    paths = RUN.paths_of(cfg, tmp_path / "other")
    paths["dir"].mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv(cfg["endpoint"]["env_key"], H.URL)
    with pytest.raises(SystemExit, match="not 4663"):
        RUN.build(cfg, paths=paths, log=lambda *a, **k: None, opener=endpoint,
                  now=clock.now, sleep=clock.sleep)


def test_a_brain_that_is_not_the_registered_one_refuses_the_start(tmp_path):
    built = H.stack(tmp_path, logs=chain())
    path = built["loop"].journal.checkpoint_path
    ck = S.load_checkpoint(path, graph_sha256=GRAPH)
    S.save_checkpoint(path, gain=np.asarray(ck["gain"]) * np.float32(0.5),
                      pos=ck["pos"], graph_sha256=ck["graph_sha256"],
                      rng_seed=0, episode=-1, events=dict(ck["events"]))
    with pytest.raises(SystemExit, match="refused"):
        H.stack(tmp_path, logs=chain())


# ------------------------------------------------------------ 3(b) throttle
def test_the_window_counts_a_rolling_hour_off_the_ledger():
    w = PL.RollingRequestWindow(cap=100, window_s=3_600, reserve=0, min_gap_s=0)
    w.sample(1_000.0, 0)
    w.sample(1_100.0, 40)
    assert w.spent(1_100.0, 40) == 40
    assert not w.full(1_100.0, 40)
    w.sample(1_200.0, 100)
    assert w.spent(1_200.0, 100) == 100 and w.full(1_200.0, 100)
    # an hour after the first forty, that spending has left the window: the
    # baseline is the newest sample at or before the edge, so what is counted
    # is only what was spent after it
    assert w.spent(1_100.0 + 3_601, 100) == 60
    assert w.resume_at(1_200.0, 100) == pytest.approx(1_100.0 + 3_600)


def test_the_window_is_a_window_and_not_a_total():
    w = PL.RollingRequestWindow(cap=10, window_s=60, reserve=0, min_gap_s=0)
    for i in range(10):
        w.sample(1_000.0 + i, i)
    assert w.spent(1_000.0 + 9, 9) == 9
    assert w.spent(1_000.0 + 500, 9) == 0        # everything aged out


def test_at_the_cap_the_loop_throttles_and_does_not_exit(tmp_path):
    cfg = H.config(tmp_path)
    cfg["limits"]["hourly_request_cap"] = 5
    cfg["limits"]["hourly_reserve"] = 0
    cfg["limits"]["window_seconds"] = 120
    built = H.stack(tmp_path, cfg=cfg, logs=chain())
    H.stop_after(built, 8)
    built["loop"].run_branch()
    events = H.read_events(built)
    throttled = [e for e in events if e["kind"] == "THROTTLED"]
    assert throttled, "the cap was never reached in this fixture"
    assert throttled[0]["reason"] == "HOURLY_REQUEST_CAP"
    assert throttled[0]["cap"] == 5
    assert throttled[0]["resume_at"] > throttled[0]["ts"]
    # it waited and went on: the stop was the stop file, never the cap
    assert built["driver"].stopped == "STOP_FILE"
    assert built["driver"].throttle_events >= 1
    assert built["driver"].throttle_seconds > 0
    assert built["driver"].ticks_done >= 8


def test_the_throttle_lifts_when_the_window_frees(tmp_path):
    cfg = H.config(tmp_path)
    cfg["limits"]["hourly_request_cap"] = 5
    cfg["limits"]["hourly_reserve"] = 0
    cfg["limits"]["window_seconds"] = 60
    built = H.stack(tmp_path, cfg=cfg, logs=chain())
    H.stop_after(built, 6)
    built["loop"].run_branch()
    assert built["driver"].ticks_done >= 6
    assert built["driver"].throttled is False
    state = H.read_state(built)
    assert state["health"]["throttled"] is False
    assert state["health"]["throttle_events"] >= 1


def test_the_rolling_window_survives_a_restart(tmp_path):
    built = H.stack(tmp_path, logs=chain())
    H.stop_after(built, 3)
    built["loop"].run_branch()
    samples = H.read_state(built)["restore"]["request_window"]
    assert samples
    again = H.stack(tmp_path, clock=H.Clock(built["clock"].now()),
                    logs=chain(), head=built["endpoint"].head)
    assert list(again["driver"].window.samples)[:len(samples)] == [
        (float(t), int(n)) for t, n in samples]


# ---------------------------------------------------------- 3(d) rpc errors
class Flaky:
    """An opener that fails on chosen call numbers. Scripted, like the chain."""

    def __init__(self, inner, fail_on):
        self.inner = inner
        self.fail_on = set(fail_on)
        self.n = 0

    def __call__(self, url, body, timeout):
        self.n += 1
        if self.n in self.fail_on:
            raise OSError("scripted transport failure")
        return self.inner(url, body, timeout)


class AlwaysFails:
    """A client stub that raises one code, and counts the attempts."""

    def __init__(self, code="RPC_TRANSPORT_FAILED"):
        self.code = code
        self.calls = 0
        self.ledger = None

    def block(self, tag):
        self.calls += 1
        raise RpcError(self.code, "scripted")


def test_a_transient_endpoint_error_is_retried_and_the_loop_survives(tmp_path,
                                                                     monkeypatch):
    from tests.product.harness import RUN
    cfg = H.config(tmp_path)
    clock = H.Clock()
    inner = SC.TickingEndpoint(logs=chain(), head=1_000, first=600,
                               clock=clock.now)
    flaky = Flaky(inner, fail_on={12, 13, 20})
    paths = RUN.paths_of(cfg, tmp_path)
    paths["dir"].mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv(cfg["endpoint"]["env_key"], H.URL)
    built = RUN.build(cfg, paths=paths, log=lambda *a, **k: None, opener=flaky,
                      now=clock.now, sleep=clock.sleep)
    built.update(paths=paths, endpoint=inner, clock=clock, cfg=cfg)
    RUN.wire_state(built, started_at=clock.now())
    H.stop_after(built, 6)
    built["loop"].run_branch()

    assert built["rpc"].errors >= 1 and built["rpc"].retries >= 1
    assert built["driver"].stopped == "STOP_FILE"       # never the error
    assert built["driver"].ticks_done >= 6
    errors = [e for e in H.read_events(built) if e["kind"] == "RPC_ERROR"]
    assert errors, "no RPC_ERROR event was written"
    assert errors[0]["code"] == "RPC_TRANSPORT_FAILED"
    assert errors[0]["retried"] is True
    assert errors[0]["backoff_s"] >= 1.0
    assert "<rpc-endpoint>" in errors[0]["detail"] or "scripted" in errors[0]["detail"]


def test_the_backoff_doubles_and_is_capped():
    slept: list[float] = []
    client = AlwaysFails()
    stop = {"now": False}
    rpc = PL.RetryingRpc(client, sleep=lambda s: slept.append(s),
                         now=lambda: 0.0,
                         should_stop=lambda: stop["now"])
    seen = []

    def on_error(**kw):
        seen.append(kw)
        if len(seen) >= 10:
            stop["now"] = True
    rpc._on_error = on_error
    with pytest.raises(RpcError):
        rpc.block("latest")
    waited = [round(sum(1 for _ in ()) or s, 3) for s in slept]
    assert waited[:4] == [1.0, 1.0, 1.0, 1.0]     # one-second slices of 1, 2, 4…
    assert sum(slept) == pytest.approx(1 + 2 + 4 + 8 + 16 + 32 + 60 + 60 + 60,
                                       abs=1e-6)
    assert max(kw["backoff_s"] for kw in seen) == PL.BACKOFF_MAX_S
    assert client.calls == 10


def test_a_range_refusal_is_not_retried_here():
    client = AlwaysFails(RANGE_TOO_LARGE)
    seen = []
    rpc = PL.RetryingRpc(client, sleep=lambda s: None, now=lambda: 0.0,
                         on_error=lambda **kw: seen.append(kw))
    with pytest.raises(RpcError):
        rpc.block("latest")
    assert client.calls == 1, "a range refusal is the collector's to halve"
    assert seen[0]["retried"] is False
    assert RANGE_TOO_LARGE in PL.NON_RETRYABLE


# ------------------------------------------------------------- 3(f) credit
@pytest.fixture(scope="module")
def settled(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("credit")
    built = H.stack(tmp, logs=chain(), decoder=H.ScriptedDecoder(None, buys=1))
    H.stop_after(built, 40)
    out = built["loop"].run_branch()
    assert out["episodes"], "the fixture settled no episode"
    return built, out


def test_the_credit_is_the_absolute_rule_and_says_it_was_not_applied(settled):
    built, out = settled
    credits = [e for e in H.read_events(built) if e["kind"] == "CREDIT"]
    assert len(credits) == len(out["episodes"])
    episode = out["episodes"][0]
    credit = credits[0]
    valence, amount = built["execution"].reinforcement(
        built["execution"].outcomes[0])
    assert credit["rule"] == "absolute_profit_v1"
    assert credit["valence"] == valence
    assert credit["amount"] == pytest.approx(amount)
    assert credit["label"] == ("REWARD" if valence > 0 else
                               "PUNISHMENT" if valence < 0 else "NEUTRAL")
    assert credit["applied"] is False
    assert credit["learning"] == "FROZEN"
    assert credit["net_pnl_eth"] == pytest.approx(episode["net_pnl"])
    assert credit["reinforce_full_scale"] == pytest.approx(0.131032424)


def test_the_digest_is_unchanged_after_a_settled_episode(settled):
    built, out = settled
    credit = [e for e in H.read_events(built) if e["kind"] == "CREDIT"][0]
    assert credit["brain_digest_before"] == REGISTERED
    assert credit["brain_digest_after"] == REGISTERED
    assert out["digest_unchanged"] is True
    assert built["loop"].credits["REWARD"] + built["loop"].credits["PUNISHMENT"] \
        + built["loop"].credits["NEUTRAL"] == len(out["episodes"])


# ------------------------------------------------------------- 3(c) resume
@pytest.fixture(scope="module")
def restarted(tmp_path_factory):
    """Two processes over one directory, with a position open across the cut."""
    tmp = tmp_path_factory.mktemp("resume")
    logs = chain()
    first = H.stack(tmp, logs=logs, decoder=H.ScriptedDecoder(None, buys=1))
    H.stop_after(first, 12)
    out_a = first["loop"].run_branch()
    state_a = H.read_state(first)
    assert state_a["position"], "the fixture stopped with no position open"

    second = H.stack(tmp, clock=H.Clock(first["clock"].now()), logs=logs,
                     head=first["endpoint"].head,
                     decoder=H.ScriptedDecoder(None, buys=1))
    acc = second["execution"].account
    at_start = {"account": {"cash": acc.cash, "realized_pnl": acc.realized_pnl,
                            "trades": acc.trades, "fees_paid": acc.fees_paid},
                "position": (None if acc.position is None else {
                    "episode_id": acc.position.episode_id,
                    "symbol": acc.position.symbol,
                    "entry_ts": acc.position.entry.ts,
                    "entry_block": acc.position.entry.bar_index,
                    "fill_price": acc.position.entry.fill_price,
                    "quantity": acc.position.entry.quantity}),
                "tick_offset": second["loop"].tick_offset,
                "digest": second["digest"],
                "resumed": dict(second["resumed"]),
                "recovery": dict(second["recovery"])}
    H.stop_after(second, 40)
    out_b = second["loop"].run_branch()
    return first, out_a, state_a, second, out_b, H.read_state(second), at_start


def test_a_restart_restores_the_account_the_cutoff_and_the_position(restarted):
    first, out_a, state_a, second, out_b, state_b, at_start = restarted
    resumed = at_start["resumed"]
    assert resumed["restored"] is True
    assert resumed["account"] is True
    assert resumed["position"]["token"] == state_a["position"]["token"]
    assert resumed["last_cutoff_ts"] == state_a["health"]["last_cutoff_ts"]
    # the account came back exactly, to the float, before the second tick ran
    assert at_start["account"]["cash"] == state_a["account"]["cash_eth"]
    assert (at_start["account"]["realized_pnl"]
            == state_a["account"]["realized_pnl_eth"])
    assert at_start["account"]["trades"] == state_a["account"]["trades"]
    assert at_start["position"]["episode_id"] == state_a["position"]["episode_id"]
    assert (at_start["position"]["fill_price"]
            == state_a["position"]["entry_price_eth_per_token"])
    assert at_start["position"]["entry_ts"] == state_a["position"]["entry_ts"]
    assert (at_start["position"]["quantity"]
            == state_a["position"]["quantity_tokens"])
    # the brain was asserted at both starts
    assert first["digest"] == REGISTERED and at_start["digest"] == REGISTERED
    assert at_start["recovery"]["checkpoint_loaded"] is True


def test_the_open_position_is_not_closed_at_a_restart_mark(restarted):
    first, out_a, state_a, second, out_b, state_b, at_start = restarted
    assert not out_a["episodes"], "the first process settled the position"
    episode_a = state_a["position"]["episode_id"]
    # the second process carried the same episode and closed it at ITS horizon
    assert [e["episode_id"] for e in out_b["episodes"]] == [episode_a]
    closed = out_b["episodes"][0]
    assert closed["entry_ts"] == state_a["position"]["entry_ts"]
    assert closed["entry_block"] == state_a["position"]["entry_block"]
    assert closed["seconds_held"] >= 900
    assert closed["close_reason"] == "POLICY_CLOSE_FIXED_HOLD"
    # no CLOSE was written between the two starts
    events = H.read_events(second)
    opens = [e for e in events if e["kind"] == "OPEN"]
    closes = [e for e in events if e["kind"] == "CLOSE"]
    assert len(opens) == 1 and len(closes) == 1
    assert closes[0]["seq"] > opens[0]["seq"]


def test_a_pending_confirmation_is_restored_too(tmp_path):
    """Addendum 3(c) names it beside the account and the position.

    A settlement whose blocks are not confirmed yet is retried at every later
    tick; a restart that forgot it would leave the position open with nobody
    retrying until the next horizon check.
    """
    built = H.stack(tmp_path, logs=chain(),
                    decoder=H.ScriptedDecoder(None, buys=1))
    H.stop_after(built, 12)
    built["loop"].run_branch()
    held = built["loop"].x.account.position
    assert held is not None
    pending = {"episode_id": held.episode_id, "token": held.symbol,
               "entry": {"confirmed": True}, "exit": {"confirmed": False},
               "since_tick": built["loop"].global_tick}
    built["loop"].pending = pending
    built["feed"].write_state()                     # the tick's own writer

    again = H.stack(tmp_path, clock=H.Clock(built["clock"].now()),
                    logs=chain(), head=built["endpoint"].head)
    assert again["resumed"]["pending"] == pending
    assert again["loop"].pending == pending
    assert H.read_state(built)["position"]["pending_confirmation"] == \
        held.episode_id


def test_episode_ids_stay_monotone_across_a_restart(restarted):
    first, out_a, state_a, second, out_b, state_b, at_start = restarted
    assert at_start["tick_offset"] == state_a["restore"]["tick"]
    assert second["loop"].global_tick > first["loop"].global_tick
    picks = [e for e in H.read_events(second) if e["kind"] == "PICK"]
    ids = [e["episode_id"] for e in picks]
    assert ids == sorted(ids), "a restart reused an episode id"
    assert len(set(ids)) == len(ids)


def test_the_feed_and_its_history_carry_across_a_restart(restarted):
    first, out_a, state_a, second, out_b, state_b, at_start = restarted
    assert state_b["seq"] > state_a["seq"]
    assert state_b["kinds"]["SNIFF"] >= state_a["kinds"]["SNIFF"]
    assert state_b["sniffed"]["ticks"] >= state_a["sniffed"]["ticks"]
    assert len(state_b["episodes"]) == 1


def test_a_held_token_whose_tape_has_not_come_back_marks_nothing(tmp_path):
    """A restart that has not replayed the tape yet retains the exposure.

    Both entry points are guarded — the holding tick and the pending
    settlement — because a ``KeyError`` on a tape is not a reason to lose a
    position.
    """
    built = H.stack(tmp_path, logs=chain(),
                    decoder=H.ScriptedDecoder(None, buys=1))
    H.stop_after(built, 12)
    built["loop"].run_branch()
    loop = built["loop"]
    held = loop.x.account.position
    assert held is not None, "the fixture stopped with no position open"
    loop.tapes.pop(held.symbol, None)
    before = loop.tape_missing

    loop._tick_holding(built["driver"].last_ts, 1, held)
    assert loop.tape_missing == before + 1
    assert loop.x.account.position is held

    loop.pending = {"episode_id": held.episode_id, "token": held.symbol}
    loop._settle_pending(built["driver"].last_ts)        # must not raise
    assert loop.x.account.position is held
    sniffs = [e for e in H.read_events(built) if e["kind"] == "SNIFF"]
    assert sniffs[-1]["tape_missing"] is True
    assert sniffs[-1]["holding"] is True
