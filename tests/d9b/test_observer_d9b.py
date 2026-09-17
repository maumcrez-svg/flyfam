"""
D9(b) Fable addendum 9 — the viewer, minimally.

Three things and no more: the new run directory is a root the server knows,
``POLICY_CLOSE_FIXED_HOLD`` reads as a policy closure, and a ``FIXED_HOLD``
rejection reads as a blocked SELL signal rather than as an executed sale. The
fourth is the one that matters most — the D5/D6/D7 projections must be exactly
what they were — and it is asserted by projecting the D9(a) fixtures
themselves and finding nothing new in them.

``tests/observer/`` is not modified by this wave: the fixtures are built by
calling its own committed builders and adding the D9(b) field to the returned
event, which is what a real log would carry.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "observer"))
sys.path.insert(0, str(ROOT))

import projection as P                                  # noqa: E402
import serve as SRV                                     # noqa: E402

from tests.observer import fixtures as F                # noqa: E402

T0 = F.T0
FIXED_HOLD_CLOSE = "POLICY_CLOSE_FIXED_HOLD"


def fixed_hold_branch() -> F.Log:
    """One fixed-hold episode: entry, a blocked SELL, the horizon closure."""
    log = F.Log()
    F.partition(log, "LEARNING", "start", branch="learned", learning=True)

    F.round_(log, i=1, ts=T0 + 60)
    F.decision(log, episode_id=1000, ts=T0 + 60, action="BUY", status="VALID",
               valence=3.0, branch="learned", partition_name="LEARNING")
    F.execution(log, episode_id=1000, ts=T0 + 120)

    # while holding: the decoder says SELL and the policy refuses to act
    F.round_(log, i=2, ts=T0 + 180)
    blocked = F.decision(log, episode_id=2000, ts=T0 + 180, action="SELL",
                         status="POLICY_REJECT", valence=-3.0,
                         branch="learned", partition_name="LEARNING")
    blocked["rejection"] = {"action": "SELL", "symbol": "SYN",
                            "bar_index": 2, "reason": "FIXED_HOLD"}

    # the horizon expires and the position closes, under its own name
    F.round_(log, i=3, ts=T0 + 240)
    F.decision(log, episode_id=3000, ts=T0 + 240, action="WAIT",
               status="VALID", valence=0.1, branch="learned",
               partition_name="LEARNING")
    F.outcome(log, episode_id=1000, ts=T0 + 240, net=-1.25,
              close_reason=FIXED_HOLD_CLOSE, held=5)
    F.learning(log, episode_id=1000, valence=-1, amount=0.4)
    F.partition(log, "LEARNING", "end", branch="learned", learning=True)
    return log


@pytest.fixture(scope="module")
def fixed():
    return P.project(fixed_hold_branch().events, horizon_minutes=5,
                     horizon_source="fixture")


# ------------------------------------------------ the closure is a closure

def test_a_fixed_hold_closure_counts_as_a_policy_closure(fixed):
    last = fixed["frames"][-1]["at"]
    counters = dict(zip(fixed["meta"]["counters"], last["c"]))
    assert counters["policy_close"] == 1
    assert counters["neural_sell"] == 0
    assert counters["outcomes"] == 1
    assert counters["learning"] == 1


def test_the_closure_keeps_its_own_name_on_the_frame(fixed):
    o = [f for f in fixed["frames"] if f["kind"] == "OUTCOME"][0]
    assert o["ev"]["close_reason"] == FIXED_HOLD_CLOSE
    assert o["ev"]["market_minutes_held"] == 5
    # a timer is not a neural choice, and the two are never merged
    assert P.POLICY_CLOSE_FIXED_HOLD in P.POLICY_CLOSURES
    assert P.NEURAL_SELL not in P.POLICY_CLOSURES


# ------------------------------------------- the blocked SELL is a signal

def test_a_blocked_sell_reaches_the_frame_with_its_reason(fixed):
    d = [f for f in fixed["frames"]
         if f["kind"] == "DECISION" and f["ev"].get("reject_reason")]
    assert len(d) == 1
    ev = d[0]["ev"]
    assert ev["reject_reason"] == P.FIXED_HOLD_REJECTION == "FIXED_HOLD"
    assert ev["action"] == "SELL"
    assert ev["status"] == "POLICY_REJECT"
    # the position was open at that frame: this is not "SELL with no position"
    assert d[0]["at"].get("position") is not None


def test_the_page_names_the_fixed_hold_block_and_never_calls_it_a_sale():
    page = (ROOT / "observer" / "index.html").read_text()
    assert 'SELL signal · blocked by fixed-hold policy' in page
    assert 'e.reject_reason === "FIXED_HOLD"' in page
    # the wording the amendment forbids never appears
    assert "executed sale" not in page.replace(
        "is not an executed sale", "")


def test_the_contract_states_the_two_new_mappings():
    c = (ROOT / "observer" / "CONTRACT.md").read_text()
    assert FIXED_HOLD_CLOSE in c
    assert "blocked by fixed-hold policy" in c


# ------------------------------------- nothing else in the viewer moved

def test_the_d9a_fixtures_project_with_no_new_key(monkeypatch):
    """The earlier runs carry no rejection, so no frame gains a field."""
    for log in (F.learning_branch(), F.frozen_branch()):
        out = P.project(log.events, horizon_minutes=5,
                        horizon_source="fixture")
        blob = json.dumps(out, sort_keys=True)
        assert "reject_reason" not in blob
        assert FIXED_HOLD_CLOSE not in blob


def test_the_policy_reject_branch_of_d9a_is_unchanged():
    """A POLICY_REJECT with no recorded reason still reads as it did."""
    out = P.project(F.learning_branch().events, horizon_minutes=5,
                    horizon_source="fixture")
    rejects = [f for f in out["frames"]
               if f["kind"] == "DECISION"
               and f["ev"].get("status") == "POLICY_REJECT"]
    for f in rejects:
        assert "reject_reason" not in f["ev"]


# ------------------------------------------------- the server knows the root

def test_the_d9b_run_directory_is_a_root_the_server_knows():
    waves = [r["wave"] for r in SRV.ROOTS]
    # D10 appended a fourth root. D9(b) stays the third and everything this
    # test asserts about it is unchanged; only the list it sits in grew.
    assert waves[:3] == ["D5/D6", "D7", "D9(b)"]
    d9b = SRV.ROOTS[2]
    assert d9b["runs"] == ROOT / "experiments" / "d9b" / "runs"
    assert d9b["summary"] == ROOT / "experiments" / "d9b" / "frozen_summary.json"
    # the artifacts it exposes are committed, read-only JSON and nothing else
    for name, path in d9b["extra"].items():
        assert path.suffix == ".json"
        assert path.parent == ROOT / "experiments" / "d9b"
    assert set(d9b["extra"]) == {"plan", "context", "probes", "alignment",
                                 "learning"}
    # the D5/D6 and D7 roots are untouched, and the default is still D5/D6
    assert SRV.RUNS == SRV.ROOTS[0]["runs"]
    assert SRV.ROOTS[1]["runs"] == ROOT / "experiments" / "d7" / "runs"


def test_no_new_route_and_no_new_static_file_were_added():
    assert set(SRV.STATIC) == {"watch.css", "NOTICE"}
    assert SRV.HOST == "127.0.0.1"
    src = (ROOT / "observer" / "serve.py").read_text()
    assert "do_POST" not in src and "do_PUT" not in src
