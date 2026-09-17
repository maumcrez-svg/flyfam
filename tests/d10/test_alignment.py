"""Entry and outcome are the same episode, at the blocks the rule names.

Addendum 11 and amendment §9: "Training and evaluation labels must use the
same entry, horizon, actual modeled costs and settlement conventions." There
is no separate evaluation label in D10, so the alignment that matters is the
one *inside* an episode: the outcome that settled is the entry that opened, at
the horizon the policy declared, on blocks the confirmation rule accepted.

Read out of `d10-001`'s own event log. If the run is not on disk (its output
is gitignored) these skip and say so.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "experiments" / "d10" / "runs" / "d10-001"


@pytest.fixture(scope="module")
def branch():
    log = RUN / "learning" / "events.jsonl"
    if not log.is_file():
        pytest.skip("d10-001 has not been run; its output is gitignored")
    events = [json.loads(line) for line in log.read_text().splitlines()
              if line.strip()]
    summary = json.loads((RUN / "summary.json").read_text())
    return events, summary["branches"]["learning"], summary["config"]


def _by(events, kind):
    return [e for e in events if e["kind"] == kind]


def test_every_execution_has_exactly_one_outcome_and_one_learning(branch):
    events, _, _ = branch
    entries = {e["episode_id"] for e in _by(events, "EXECUTION")}
    outcomes = [e["episode_id"] for e in _by(events, "OUTCOME")]
    learning = [e["episode_id"] for e in _by(events, "LEARNING")]
    assert entries
    assert sorted(outcomes) == sorted(set(outcomes))     # never twice
    assert sorted(learning) == sorted(set(learning))
    assert set(outcomes) <= entries
    assert set(learning) == set(outcomes)


def test_the_outcome_settles_the_entry_it_opened(branch):
    events, _, _ = branch
    entry_block = {e["episode_id"]: e["bar_index"] for e in _by(events, "EXECUTION")}
    for outcome in _by(events, "OUTCOME"):
        assert outcome["entry"]["bar_index"] == entry_block[outcome["episode_id"]]
        assert outcome["entry"]["side"] == "BUY"
        assert outcome["exit"]["side"] == "SELL"
        assert outcome["exit"]["bar_index"] > outcome["entry"]["bar_index"]


def test_the_exit_is_the_declared_horizon_after_the_entry_fill(branch):
    events, _, cfg = branch
    horizon = int(cfg["horizon_seconds"])
    precision = float(cfg["budgets"]["header_precision_seconds"])
    for outcome in _by(events, "OUTCOME"):
        held = outcome["exit"]["ts"] - outcome["entry"]["ts"]
        # the exit is the first block at or after entry_fill + horizon, and a
        # block's timestamp is known to the declared grid precision
        assert horizon <= held <= horizon + precision + 1, held


def test_the_entry_is_at_least_the_declared_latency_after_the_cutoff(branch):
    events, _, cfg = branch
    latency = int(cfg["latency_seconds"])
    cutoffs = {e["episode_id"]: e["cutoff_ts"] for e in _by(events, "EXECUTION")}
    for execution in _by(events, "EXECUTION"):
        assert execution["ts"] - cutoffs[execution["episode_id"]] >= latency


def test_no_outcome_was_written_on_an_unconfirmed_block(branch):
    events, _, _ = branch
    for outcome in _by(events, "OUTCOME"):
        confirmation = outcome["confirmation"]
        assert confirmation["entry"]["confirmed"] is True
        assert confirmation["exit"]["confirmed"] is True


def test_the_learning_event_carries_the_sign_of_the_settled_net(branch):
    events, _, _ = branch
    net = {e["episode_id"]: e["net_pnl"] for e in _by(events, "OUTCOME")}
    for event in _by(events, "LEARNING"):
        expected = 1 if net[event["episode_id"]] > 0 else (
            -1 if net[event["episode_id"]] < 0 else 0)
        assert event["valence"] == expected
        assert 0.0 <= event["amount"] <= 1.0


def test_the_episode_table_and_the_log_agree(branch):
    events, learn, _ = branch
    logged = {e["episode_id"]: e for e in _by(events, "OUTCOME")}
    assert len(learn["episodes"]) == len(logged)
    for episode in learn["episodes"]:
        outcome = logged[episode["episode_id"]]
        # the log rounds its money to eight places (``OutcomeRecord.as_dict``);
        # the summary keeps the float. Agreement to that rounding is agreement.
        assert round(episode["net_pnl"], 8) == outcome["net_pnl"]
        assert episode["entry_block"] == outcome["entry"]["bar_index"]
        assert episode["exit_block"] == outcome["exit"]["bar_index"]
        assert episode["close_reason"] == "POLICY_CLOSE_FIXED_HOLD"


def test_no_reward_came_from_a_mark_or_a_blocked_sell(branch):
    events, learn, _ = branch
    learning = _by(events, "LEARNING")
    outcomes = _by(events, "OUTCOME")
    assert len(learning) == len(outcomes)
    blocked = learn["tally"]["after_execution_constraints"].get(
        "blocked_by_fixed_hold", 0)
    assert blocked > 0                       # there really were blocked SELLs
    assert len(learning) < blocked           # and they taught nothing
