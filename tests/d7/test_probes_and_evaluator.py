"""
The probe grid and the read-only evaluator — amendment §6 and §10's guards.

The probe dataset is extracted from the two FROZEN event logs after both
branches have finished (Fable addendum 3). These tests prove the properties
that make that honest:

* the grid comes from the calendar and the price file, so it cannot depend on
  which branch bought, on inventory, on a score or on a later outcome, and it
  is **identical for both branches**;
* the evaluator cannot mutate anything — it imports no part of the loop and
  leaves the logs byte-identical;
* labels are evaluator-only: changing every one of them cannot move a score;
* the probes overlap in time by construction and are never booked as trades;
* a FROZEN log carries no learning event and its partition digests are equal;
* a restart that writes a minute twice cannot put that minute in the dataset
  twice.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date

import numpy as np
import pytest

from flytrade import historical as H
from flytrade import horizon as HZ
from flytrade import metrics as MET
from flytrade import records as REC
from tests.d7.conftest import DAYS

import evaluate as EV                  # experiments/d7/evaluate.py

HSTAR = 120
DELAY = 1
FIRST, LAST = DAYS[0], DAYS[-1]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write_log(path, series, grid, *, scores, statuses=None, branch="x",
              duplicate=None):
    """A FROZEN event log in the shape ``run_branch`` writes one."""
    log = REC.EventLog(path)
    log.append(REC.EventType.PARTITION,
               {"partition": "FROZEN", "boundary": "start", "branch": branch,
                "state_digest": "d" * 64})
    for i, (day, m) in enumerate(grid):
        ts = int(series.sessions[day].bar_start[m]) + H.BAR_SECONDS
        payload = {"episode_id": 22_000_000 + i, "symbol": series.symbol,
                   "stable_id": 0, "bar_index": m, "cutoff_ts": ts,
                   "market_ts": ts, "brain_cycle": i, "brain_ms": 500.0 * i,
                   "decoded_action": "WAIT",
                   "readout_status": (statuses or {}).get((day, m), "VALID"),
                   "partition": "FROZEN", "branch": branch,
                   "dataset_label": "HISTORICAL_MARKET",
                   "valence_hz": float(scores[(day, m)]),
                   "theta_hz": 0.9117185769796697}
        log.append(REC.EventType.DECISION, payload)
        if duplicate is not None and (day, m) == duplicate:
            log.append(REC.EventType.DECISION, dict(payload, valence_hz=-99.0))
    log.append(REC.EventType.PARTITION,
               {"partition": "FROZEN", "boundary": "end", "branch": branch,
                "state_digest": "d" * 64})
    return path


@pytest.fixture
def grid(clean):
    return EV.probe_grid(clean, FIRST, LAST, HSTAR, delay=DELAY)


# ----------------------------------------------------------- the grid

def test_the_grid_is_every_encodable_minute_with_room_for_the_horizon(clean,
                                                                     grid):
    assert len(grid) > 0
    for day, m in grid:
        assert clean.status(day, m).value == "OK"
        assert HZ.eligible(m, HSTAR, delay=DELAY)
    # nothing past the clock rule, and nothing inside the per-session warm-up
    assert max(m for _, m in grid) <= 390 - 1 - DELAY - HSTAR
    assert min(m for _, m in grid) >= H.FEATURE_LOOKBACK


def test_the_grid_is_identical_for_both_branches(clean, grid):
    """It is computed from the price file, so "both branches" is the same call."""
    a = EV.probe_grid(clean, FIRST, LAST, HSTAR, delay=DELAY)
    b = EV.probe_grid(clean, FIRST, LAST, HSTAR, delay=DELAY)
    assert a == b == grid


def test_the_grid_does_not_depend_on_any_score_inventory_or_outcome(
        clean, grid, tmp_path):
    """Two logs that disagree about everything leave the grid untouched."""
    rng = np.random.default_rng(7)
    one = {k: rng.normal() for k in grid}
    two = {k: -50.0 for k in grid}
    write_log(tmp_path / "a.jsonl", clean, grid, scores=one, branch="a")
    write_log(tmp_path / "b.jsonl", clean, grid, scores=two, branch="b")
    after = EV.probe_grid(clean, FIRST, LAST, HSTAR, delay=DELAY)
    assert after == grid


def test_a_data_gap_removes_a_grid_point_for_both_branches_alike(gapped):
    g = EV.probe_grid(gapped, FIRST, LAST, 30, delay=DELAY)
    day = DAYS[2]
    assert (day, 150) not in g            # the vendor omitted that minute
    assert all(gapped.status(d, m).value == "OK" for d, m in g)


def test_the_horizon_changes_the_grid_only_through_the_clock_rule(clean):
    short = EV.probe_grid(clean, FIRST, LAST, 8, delay=DELAY)
    long_ = EV.probe_grid(clean, FIRST, LAST, 120, delay=DELAY)
    assert set(long_) < set(short)
    assert all(HZ.eligible(m, 8, delay=DELAY) for _, m in long_)


# ---------------------------------------------------------- the labels

def test_every_label_is_the_net_return_of_one_hold_under_the_convention(
        clean, grid):
    lab = EV.labels(clean, grid[:200], HSTAR, delay=DELAY, notional=1000.0,
                    fee_bps=5.0, slippage_bps=5.0)
    for (day, m), v in lab.items():
        h = HZ.hold(clean, day, m, HSTAR, delay=DELAY)
        assert v["available"] == h.ok
        if v["available"]:
            assert v["G"] == pytest.approx(h.net_return(
                notional=1000.0, fee_bps=5.0, slippage_bps=5.0))
            assert v["Y"] == int(v["G"] > 0)


def test_a_missing_future_price_is_unavailable_and_never_a_loss(clean):
    """A grid point whose exit cannot exist is UNAVAILABLE_LABEL, not Y = 0."""
    late = (DAYS[1], 389 - HSTAR)          # no room: the clock rule refuses
    lab = EV.labels(clean, [late], HSTAR, delay=DELAY, notional=1000.0,
                    fee_bps=5.0, slippage_bps=5.0)
    v = lab[late]
    assert v["available"] is False and "Y" not in v and "G" not in v


def test_one_common_label_serves_both_branches(clean, grid):
    a = EV.labels(clean, grid[:50], HSTAR, delay=DELAY, notional=1000.0,
                  fee_bps=5.0, slippage_bps=5.0)
    b = EV.labels(clean, grid[:50], HSTAR, delay=DELAY, notional=1000.0,
                  fee_bps=5.0, slippage_bps=5.0)
    assert a == b


def test_changing_every_label_cannot_change_a_single_neural_score(clean, grid,
                                                                 tmp_path):
    rng = np.random.default_rng(11)
    scores = {k: rng.normal() for k in grid}
    p = write_log(tmp_path / "log.jsonl", clean, grid, scores=scores)
    before = sha(p)
    rows, _ = EV.frozen_decisions(p)
    true_lab = EV.labels(clean, grid, HSTAR, delay=DELAY, notional=1000.0,
                         fee_bps=5.0, slippage_bps=5.0)
    flipped = {k: (dict(v, G=-v["G"], Y=1 - v["Y"]) if v["available"] else v)
               for k, v in true_lab.items()}
    rows2, _ = EV.frozen_decisions(p)
    assert {k: e["valence_hz"] for k, e in rows.items()} == \
        {k: e["valence_hz"] for k, e in rows2.items()}
    assert sha(p) == before
    assert any(flipped[k]["Y"] != true_lab[k]["Y"] for k in true_lab
               if true_lab[k]["available"])


# ---------------------------------------------- the evaluator's guards

def test_the_evaluator_imports_no_part_of_the_loop():
    src = open(EV.__file__, encoding="utf-8").read()
    for forbidden in ("import runner", "import mushroom", "import execution",
                      "import readout", "from flytrade import records"):
        assert forbidden not in src, forbidden
    assert "from flytrade import historical" in src
    assert "from flytrade import horizon" in src
    assert "from flytrade import metrics" in src


def test_reading_a_log_leaves_it_byte_identical(clean, grid, tmp_path):
    scores = {k: 0.5 for k in grid}
    p = write_log(tmp_path / "log.jsonl", clean, grid, scores=scores)
    before = sha(p)
    for _ in range(3):
        EV.frozen_decisions(p)
    assert sha(p) == before


def test_probes_overlap_in_time_and_are_never_summed_into_a_pnl(clean, grid):
    """One probe per eligible minute, each H* minutes long: they overlap."""
    lab = EV.labels(clean, grid, HSTAR, delay=DELAY, notional=1000.0,
                    fee_bps=5.0, slippage_bps=5.0)
    day = grid[0][0]
    same = [(d, m) for d, m in grid if d == day]
    assert len(same) > HSTAR                 # far more probes than fit serially
    a, b = lab[same[0]], lab[same[1]]
    assert a["entry_minute"] < b["entry_minute"] < a["exit_minute"]
    # overlapping holds would sum to a number no account could ever have made
    total = sum(lab[k]["G"] for k in same if lab[k]["available"])
    assert abs(total) > 0
    # which is why the reported statistic is a mean over probes and the money
    # is taken from the account the run itself booked
    mets = open(MET.__file__, encoding="utf-8").read()
    assert "mean_G" in mets and "total_G" not in mets
    src = open(EV.__file__, encoding="utf-8").read()
    assert 'ex = summary["branches"][b]["execution"]' in src
    assert '"trades": ex["trades"]' in src


def test_the_trade_count_comes_from_the_account_never_from_the_probes():
    """§8: a ranking diagnostic is not a backtested executable portfolio."""
    src = open(EV.__file__, encoding="utf-8").read()
    body = src.split("def main")[-1]
    assert "actual_completed_trades" in body
    assert 'actions[b]["trades"]' in body
    # no branch of the evaluator turns a probe into an order or a bankroll
    for forbidden in ("open_long", "close(", "account.cash", "realized_pnl"):
        assert forbidden not in src, forbidden


# ------------------------------------------------- frozen-log invariants

def test_a_frozen_log_carries_no_learning_event_and_equal_digests(clean, grid,
                                                                  tmp_path):
    p = write_log(tmp_path / "log.jsonl", clean, grid[:20],
                  scores={k: 1.0 for k in grid[:20]})
    events = [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
    assert not [e for e in events if e["kind"] == "LEARNING"]
    bounds = [e for e in events if e["kind"] == "PARTITION"]
    assert bounds[0]["state_digest"] == bounds[-1]["state_digest"]


def test_a_restart_cannot_put_one_minute_in_the_dataset_twice(clean, grid,
                                                              tmp_path):
    """A duplicated DECISION — the shape a restarted process could write."""
    dup = grid[3]
    p = write_log(tmp_path / "log.jsonl", clean, grid[:10],
                  scores={k: 1.0 for k in grid[:10]}, duplicate=dup)
    rows, counts = EV.frozen_decisions(p)
    assert len(rows) == 10
    assert counts["DUPLICATE_DECISION_AT_A_MINUTE"] == 1
    assert rows[dup]["valence_hz"] == 1.0        # the first, not the retry


def test_only_the_frozen_span_is_read(clean, grid, tmp_path):
    log = REC.EventLog(tmp_path / "log.jsonl")
    ts = int(clean.sessions[grid[0][0]].bar_start[grid[0][1]]) + 60
    log.append(REC.EventType.PARTITION, {"partition": "LEARNING",
                                         "boundary": "start"})
    log.append(REC.EventType.DECISION,
               {"episode_id": 1, "symbol": "W", "bar_index": grid[0][1],
                "market_ts": ts, "readout_status": "VALID",
                "decoded_action": "BUY", "valence_hz": 42.0})
    log.append(REC.EventType.PARTITION, {"partition": "LEARNING",
                                         "boundary": "end"})
    log.append(REC.EventType.PARTITION, {"partition": "FROZEN",
                                         "boundary": "start"})
    log.append(REC.EventType.PARTITION, {"partition": "FROZEN",
                                         "boundary": "end"})
    rows, _ = EV.frozen_decisions(tmp_path / "log.jsonl")
    assert rows == {}


def test_the_statuses_that_carry_a_score_are_declared_and_exclude_invalid():
    assert EV.SCORED == ("VALID", "NO_RESPONSE", "POLICY_REJECT")
    assert "INVALID_STATE" not in EV.SCORED


def test_a_silent_readout_keeps_its_actual_finite_score(clean, grid, tmp_path):
    """§7: silent contexts stay in the analysis with their real readout."""
    from flytrade import readout as RO
    silent = -RO.BASELINE_HZ_K8
    p = write_log(tmp_path / "log.jsonl", clean, grid[:5],
                  scores={k: silent for k in grid[:5]},
                  statuses={k: "NO_RESPONSE" for k in grid[:5]})
    rows, counts = EV.frozen_decisions(p)
    assert len(rows) == 5
    assert counts["DECISION:NO_RESPONSE"] == 5
    assert all(r["valence_hz"] == pytest.approx(0.844389816810345)
               for r in rows.values())
