"""
Partition boundaries and the round grid.

Amendment D6 §4: three inclusive date ranges, regular-session observations
only, nothing crossing a boundary, no date reshuffled or replaced. Fable
addendum 3: one decision round per regular-session minute bar, at that bar's
``bar_end``.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from flytrade import historical as H
from tests.historical import make_fixtures as MF

D0, D1, D2 = MF.DAYS

SPEC = {
    "WARMUP": {"first": "2026-08-03", "last": "2026-08-03",
               "learning": False, "neural": False},
    "LEARNING": {"first": "2026-08-04", "last": "2026-08-04",
                 "learning": True, "neural": True},
    "FROZEN": {"first": "2026-08-05", "last": "2026-08-05",
               "learning": False, "neural": True},
}


def test_the_three_partitions_are_inclusive_disjoint_and_ordered():
    parts = H.partitions_from(SPEC)
    assert [p.name for p in parts] == ["WARMUP", "LEARNING", "FROZEN"]
    assert [p.first for p in parts] == [D0, D1, D2]
    assert [p.last for p in parts] == [D0, D1, D2]
    for p in parts:
        assert p.contains(p.first) and p.contains(p.last)
    # disjoint: every day belongs to at most one
    for day in (D0, D1, D2, date(2026, 8, 6)):
        hits = [p for p in parts if p.contains(day)]
        assert len(hits) <= 1


def test_warmup_runs_no_neural_simulation_and_frozen_runs_no_learning():
    w, l, f = H.partitions_from(SPEC)
    assert (w.neural, w.learning) == (False, False)
    assert (l.neural, l.learning) == (True, True)
    assert (f.neural, f.learning) == (True, False)


def test_partition_of_names_the_partition_or_nothing():
    parts = H.partitions_from(SPEC)
    assert H.partition_of(parts, D1).name == "LEARNING"
    assert H.partition_of(parts, date(2026, 8, 6)) is None
    assert H.partition_of(parts, date(2026, 8, 2)) is None


def test_a_round_happens_at_every_minute_any_instrument_reported(universe):
    grid = H.round_grid(universe, D0, D2)
    # A and B have different gaps, so the union is larger than either alone
    only_a = H.round_grid({"A": universe["A"]}, D0, D2)
    only_b = H.round_grid({"B": universe["B"]}, D0, D2)
    assert len(grid) > len(only_a) and len(grid) > len(only_b)
    assert set(grid) == set(only_a) | set(only_b)
    # every entry is inside the regular session, on a session the file has
    for day, m in grid:
        assert day in (D0, D1, D2)
        assert 0 <= m < H.SESSION_MINUTES
    # the grid is chronological
    assert grid == sorted(grid)


def test_a_gap_in_one_instrument_does_not_remove_the_round(universe):
    """A round with one usable and one DATA_GAP candidate is still a round."""
    grid = set(H.round_grid(universe, D0, D2))
    a, b = universe["A"], universe["B"]
    hit = [(D2, m) for m in range(80, 92)
           if b.status(D2, m) is H.HistoricalStatus.DATA_GAP
           and a.status(D2, m) is H.HistoricalStatus.OK]
    assert hit, "the fixtures must contain such a minute"
    for key in hit:
        assert key in grid


def test_the_window_selects_dates_and_never_shifts_them(universe):
    one = H.round_grid(universe, D1, D1)
    assert {d for d, _ in one} == {D1}
    empty = H.round_grid(universe, date(2026, 8, 10), date(2026, 8, 12))
    assert empty == []
    # a window wider than the data yields exactly the data, not padding
    wide = H.round_grid(universe, date(2026, 7, 1), date(2026, 9, 30))
    assert wide == H.round_grid(universe, D0, D2)


def test_coverage_reports_bars_and_missing_minutes_per_day(universe):
    cov = universe["A"].coverage(D0, D2)
    assert cov["symbol"] == "A"
    assert cov["label"] == "HISTORICAL_MARKET"
    assert cov["n_days"] == 3
    assert [d["date"] for d in cov["days"]] == [str(D0), str(D1), str(D2)]
    assert cov["days"][0]["bars"] == 120
    assert cov["days"][0]["missing"] == H.SESSION_MINUTES - 120
    assert cov["days"][1]["bars"] == 116          # the 4-minute gap
    assert cov["days"][2]["bars"] == 110          # the 10-minute gap
    assert cov["bars"] + cov["missing"] == cov["complete"] == 3 * 390


def test_the_committed_config_if_present_parses_into_partitions():
    cfg = Path(__file__).resolve().parents[2] / "experiments" / "historical" \
        / "config.json"
    if not cfg.exists():
        pytest.skip("the protocol commit has not landed yet")
    d = json.loads(cfg.read_text())
    parts = H.partitions_from(d["partitions"])
    assert [p.name for p in parts] == ["WARMUP", "LEARNING", "FROZEN"]
    assert parts[0].first == date(2026, 8, 3)
    assert parts[-1].last == date(2026, 9, 4)
    # inclusive, contiguous over business days, and in order
    assert parts[0].last < parts[1].first < parts[1].last < parts[2].first
    assert not parts[0].neural and not parts[0].learning
    assert parts[1].neural and parts[1].learning
    assert parts[2].neural and not parts[2].learning
