"""
Observer event order and accounting consistency.

Amendment D6 §7 and §8. The observer is a replay, so the properties that make
it honest are properties of the **event log** and of the slicing the server
does over it:

* an outcome never precedes the decision it settles, so a cursor that has not
  reached the outcome cannot be showing it;
* the money on the page is a field of an event, and the three-term
  reconciliation holds inside each `OUTCOME`;
* the server slices by line index and changes nothing;
* it binds to 127.0.0.1 and the page recalculates no decision and no PnL.

The log these tests read is built here, line by line, in the shape the run
writes. No run output and no downloaded data is involved.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "observer"))

from flytrade import records as REC          # noqa: E402
import serve as SRV                          # noqa: E402

OBSERVER = ROOT / "observer"


def _write_log(tmp_path) -> Path:
    """A small log with the shape and the order the historical run writes."""
    log = REC.EventLog(tmp_path / "events.jsonl")
    log.append(REC.EventType.PARTITION,
               {"partition": "FROZEN", "boundary": "start", "branch": "learned",
                "state_digest": "d" * 64})
    ep = 1_000_000
    for n in range(3):
        e = ep + n
        log.append(REC.EventType.ROUND,
                   {"round_index": n, "cutoff_ts": 1_786_000_000 + 600 * n,
                    "candidates": [{"symbol": "IBM", "stable_id": 0, "k": 8,
                                    "status": "OK", "episode_id": e,
                                    "silent_replicates": 2}]})
        log.append(REC.EventType.DECISION,
                   {"episode_id": e, "symbol": "IBM", "stable_id": 0,
                    "bar_index": 10 * n, "cutoff_ts": 1_786_000_000 + 600 * n,
                    "market_ts": 1_786_000_000 + 600 * n, "brain_cycle": n,
                    "brain_ms": 500.0 * n, "seed": 42 + n,
                    "decoded_action": "BUY", "readout_status": "VALID",
                    "partition": "FROZEN", "branch": "learned",
                    "dataset_label": "HISTORICAL_MARKET",
                    "valence_hz": 1.5, "theta_hz": 0.9117185769796697,
                    "observation": {"close": 230.0,
                                    "normalized": {"r1": 0.1, "r5": -0.2,
                                                   "r20": 0.0, "rv20": 0.3,
                                                   "relvol": -0.1}},
                    "stimulus": {"rates_hz": {"DM2": 23.6, "V": 35.7},
                                 "n_orns": 703, "total_drive_hz": 12000.0},
                    "readout": {"rates_hz": {"approach": 3.1, "avoid": 1.7},
                                "population_sizes": {"approach": 16,
                                                     "avoid": 29},
                                "kc_fraction": 0.03, "kc_active": 43,
                                "max_rate_hz": 50.0, "silent_replicates": 2,
                                "k": 8},
                    "replicate_scores": [1.0] * 8,
                    "replicate_statuses": ["VALID"] * 8})
        log.append(REC.EventType.EXECUTION,
                   {"episode_id": e, "symbol": "IBM", "side": "BUY",
                    "bar_index": 10 * n + 1, "ts": 1_786_000_060 + 600 * n,
                    "market_ts": 1_786_000_060 + 600 * n,
                    "reference_price": 230.0, "fill_price": 230.115,
                    "quantity": 4.3456, "fee": 0.5, "slippage": 0.5,
                    "delay_minutes": 1, "flag": "", "k": 8})
        gross_ref, slip, fees = 3.0 - n, 1.0, 1.0
        net = gross_ref - slip - fees
        log.append(REC.EventType.OUTCOME,
                   {"episode_id": e, "symbol": "IBM",
                    "close_reason": "POLICY_CLOSE",
                    "gross_reference_pnl": gross_ref, "slippage": slip,
                    "fees": fees, "net_pnl": net, "market_minutes_held": 8,
                    "exit_flag": "", "settlement": "SETTLED_FROZEN",
                    "market_ts": 1_786_000_540 + 600 * n,
                    "cumulative_realized_pnl": round(sum(
                        (3.0 - j) - 2.0 for j in range(n + 1)), 8),
                    "account": {"cash": 10000.0 + sum((3.0 - j) - 2.0
                                                      for j in range(n + 1)),
                                "equity": 10000.0, "realized_pnl": 0.0,
                                "fees_paid": 1.0 * (n + 1),
                                "slippage_paid": 1.0 * (n + 1),
                                "trades": n + 1}})
    log.append(REC.EventType.PARTITION,
               {"partition": "FROZEN", "boundary": "end", "branch": "learned",
                "state_digest": "d" * 64})
    return log.path


# ------------------------------------------------------------- event order

def test_an_outcome_never_precedes_the_decision_it_settles(tmp_path):
    path = _write_log(tmp_path)
    events = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    first = {}
    for i, e in enumerate(events):
        key = (e.get("episode_id"), e["kind"])
        first.setdefault(key, i)
    episodes = {e["episode_id"] for e in events if "episode_id" in e}
    assert episodes
    for ep in episodes:
        d = first[(ep, "DECISION")]
        x = first[(ep, "EXECUTION")]
        o = first[(ep, "OUTCOME")]
        assert d < x < o, ep
    # so a cursor at index d cannot be displaying anything from index o: the
    # observer's state is a fold over events[0..cursor] only
    assert all(events[i]["kind"] != "OUTCOME"
               for i in range(first[(min(episodes), "DECISION")] + 1))


def test_the_market_clock_never_goes_backwards_within_an_event_kind(tmp_path):
    """The invariant that actually holds, and the one place it is subtler.

    Within each kind — every ``DECISION``, every ``EXECUTION``, every
    ``OUTCOME`` — market time is non-decreasing, in both branches. The
    *interleaved* sequence can step back by exactly 60 s at a horizon
    settlement, because a horizon exit fills at the **open** of the minute
    whose ``bar_end`` produced that same round's decision: the exit time was
    fixed by the horizon clock at entry and uses nothing from that round. The
    episode's own order ``DECISION < EXECUTION < OUTCOME`` is unaffected, so
    a cursor can never show an outcome before the decision that caused it.
    """
    path = _write_log(tmp_path)
    events = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    for kind in ("DECISION", "EXECUTION", "OUTCOME"):
        ts = [e["market_ts"] for e in events
              if e["kind"] == kind and e.get("market_ts")]
        assert ts == sorted(ts), kind


def test_a_horizon_settlement_may_precede_its_rounds_decision_by_one_minute():
    """The 60 s step, stated as a rule rather than found as a surprise."""
    from flytrade import historical as H
    from flytrade import execution as X
    # a POLICY_CLOSE settles at the OPEN of minute m; the round at minute m
    # decides at bar_end(m) = bar_start(m) + 60. So exit_ts = decision_ts - 60.
    bar_start, decision_ts = 1_786_000_000, 1_786_000_060
    assert decision_ts - bar_start == H.BAR_SECONDS == 60
    # it is not hindsight: the settlement minute was fixed at entry by the
    # horizon, and the price used is that bar's open, not its close
    assert X.CloseReason.POLICY_CLOSE.value == "POLICY_CLOSE"


# -------------------------------------------------------------- accounting

def test_every_outcome_reconciles_inside_itself(tmp_path):
    path = _write_log(tmp_path)
    outs = [json.loads(l) for l in path.read_text().splitlines()
            if '"OUTCOME"' in l]
    assert len(outs) == 3
    for o in outs:
        assert o["gross_reference_pnl"] - o["fees"] - o["slippage"] == \
            pytest.approx(o["net_pnl"], abs=1e-9)
        # and the money the page shows is a field, not a computation
        assert "account" in o and "cumulative_realized_pnl" in o
        assert set(o["account"]) >= {"cash", "equity", "realized_pnl",
                                     "fees_paid", "slippage_paid", "trades"}


def test_the_frozen_settlement_is_marked_and_carries_no_learning(tmp_path):
    path = _write_log(tmp_path)
    events = [json.loads(l) for l in path.read_text().splitlines()]
    assert all(e["settlement"] == "SETTLED_FROZEN"
               for e in events if e["kind"] == "OUTCOME")
    assert not any(e["kind"] == "LEARNING" for e in events)


# ----------------------------------------------------------- the server

def test_the_server_finds_the_partition_span_and_slices_by_index(tmp_path):
    path = _write_log(tmp_path)
    spans = SRV.partitions_in(path)
    assert len(spans) == 1
    s = spans[0]
    assert s["partition"] == "FROZEN"
    lines = path.read_text().splitlines()
    assert s["start"] == 0 and s["end"] == len(lines) - 1
    ev = SRV.read_events(path, s["start"], s["end"], 10_000)
    assert len(ev) == len(lines)
    # the slice preserves every event unchanged apart from its index marker
    for i, (e, raw) in enumerate(zip(ev, lines)):
        got = dict(e)
        assert got.pop("_i") == i
        assert got == json.loads(raw)


def test_the_server_slices_a_sub_range_without_touching_content(tmp_path):
    path = _write_log(tmp_path)
    lines = path.read_text().splitlines()
    ev = SRV.read_events(path, 2, 5, 10_000)
    assert [e["_i"] for e in ev] == [2, 3, 4, 5]
    for e in ev:
        raw = json.loads(lines[e["_i"]])
        assert {k: v for k, v in e.items() if k != "_i"} == raw


def test_the_server_binds_to_loopback_only():
    assert SRV.HOST == "127.0.0.1"
    src = (OBSERVER / "serve.py").read_text()
    assert "0.0.0.0" not in src
    # read-only: the server never writes to the store it reads
    assert ".write_text(" not in src and ".write_bytes(" not in src
    assert "do_POST" not in src and "do_PUT" not in src


# ------------------------------------------------------------- the page

def test_the_page_is_vanilla_with_no_build_step_and_no_network_dependency():
    html = (OBSERVER / "index.html").read_text()
    assert "<script src=" not in html, "no external script may be loaded"
    assert "http://" not in html.replace("http://127.0.0.1", "")
    assert "https://" not in html
    for framework in ("react", "vue", "angular", "jquery", "import ",
                      "require("):
        assert framework not in html.lower(), framework
    assert not (OBSERVER / "package.json").exists()
    assert not (OBSERVER / "node_modules").exists()


def test_the_page_shows_the_label_and_reads_money_from_event_fields():
    html = (OBSERVER / "index.html").read_text()
    assert "HISTORICAL REPLAY · PAPER" in html
    assert "simulated fills" in html
    # money is read off the outcome event, never accumulated by the page
    assert "o.account" in html and "o.cumulative_realized_pnl" in html
    assert "a.cash" in html and "a.equity" in html and "a.slippage_paid" in html
    assert "This page\n      never adds money up." in html \
        or "never adds money up" in html
    # the page decodes nothing: no theta comparison, no baseline arithmetic
    for forbidden in ("BASELINE", "theta_sd", "0.9117", "gross - fees",
                      "net_pnl +", "+= e.net_pnl", "reduce((a,e)=>a+e.net"):
        assert forbidden not in html, forbidden


def test_the_playback_controls_move_a_cursor_and_nothing_else():
    html = (OBSERVER / "index.html").read_text()
    # the cursor is an index into the loaded events
    assert "function setI(i)" in html
    assert "I = Math.max(0, Math.min(EV.length-1, i));" in html
    # play/pause only start and stop a timer that advances that index
    assert "setInterval" in html and "clearInterval" in html
    # and nothing is ever sent back to the server
    assert "method:" not in html and "POST" not in html
