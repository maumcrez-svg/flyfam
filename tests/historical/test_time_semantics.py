"""
Bar open versus availability, and missing minutes that stay missing.

Amendment D6 §3: "Kibot minute timestamps identify bar opening time … Final
OHLCV values are unavailable before bar_end", and "Do not silently compress
missing time or forward-fill executable prices … Use elapsed market time for
outcome horizons, not row count."

These are the two facts about the vendor's clock that, if they were wrong,
would make every number downstream wrong in a way no PnL could reveal.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from flytrade import historical as H
from flytrade import market as MK
from tests.historical import make_fixtures as MF

D0, D1, D2 = MF.DAYS


def test_the_timestamp_is_the_bar_open_and_the_observation_is_at_bar_end(
        series_a):
    """The row stamped 09:30 covers 09:30:00-09:30:59; nothing may read its
    close before 09:31:00."""
    s = series_a
    m = 90                                     # a minute with an OK status
    assert s.status(D0, m) is H.HistoricalStatus.OK
    bar_start = int(s.sessions[D0].bar_start[m])
    obs = s.observe(D0, m, stable_id=0)
    assert obs.cutoff_ts == bar_start + H.BAR_SECONDS
    assert obs.cutoff_ts - bar_start == 60
    # the observation's price is the bar's close, and that close belongs to a
    # bar whose window has already ended at the cutoff
    assert obs.close == pytest.approx(float(s.sessions[D0].close[m]))
    assert H.ny_datetime(bar_start).strftime("%H:%M") == "11:00"
    assert H.ny_datetime(obs.cutoff_ts).strftime("%H:%M") == "11:01"


def test_no_observation_is_built_from_a_bar_that_has_not_closed(series_a):
    """Every price behind an observation has ``bar_end <= cutoff``."""
    s = series_a
    for m in (80, 95, 110):
        obs = s.observe(D0, m)
        if not obs.status.usable:
            continue
        cutoff = obs.cutoff_ts
        # every bar of this session whose close could have entered the
        # features starts at or before cutoff - 60
        used = [int(t) for t, p in zip(s.sessions[D0].bar_start,
                                       s.sessions[D0].present)
                if p and int(t) <= int(s.sessions[D0].bar_start[m])]
        assert all(t + H.BAR_SECONDS <= cutoff for t in used)


def test_a_missing_minute_is_a_data_gap_and_not_a_corrupt_file(series_a):
    """The vendor omits minutes without trades; the importer says so."""
    s = series_a
    gone = [m for m in range(120)
            if s.status(D1, m) is H.HistoricalStatus.DATA_GAP]
    assert gone == [100, 101, 102, 103]
    for m in gone:
        assert s.bar(D1, m) is None
        obs = s.observe(D1, m, stable_id=0)
        assert obs.status is MK.ObservationStatus.DATA_GAP
        assert not obs.status.usable
        assert np.all(obs.normalized == 0.0)
        assert "no bar reported" in obs.detail
    # the file around them is fine: the session still parses and still trades
    assert s.status(D1, 99) is H.HistoricalStatus.OK
    assert s.status(D1, 104) is H.HistoricalStatus.OK


def test_time_is_never_compressed_row_distance_is_not_minute_distance(
        series_a):
    """Five rows later is not five minutes later."""
    s = series_a
    ses = s.sessions[D1]
    present = np.flatnonzero(ses.present)
    i = int(np.flatnonzero(present == 99)[0])
    # the row after minute 99 is minute 104: one row, five market minutes
    assert present[i + 1] == 104
    dt = int(ses.bar_start[104]) - int(ses.bar_start[99])
    assert dt == 5 * 60
    # and the dense grid keeps the four absent slots rather than closing up
    assert len(ses.bar_start) == H.SESSION_MINUTES
    assert ses.n_present == H.SESSION_MINUTES - ses.missing
    assert ses.missing == H.SESSION_MINUTES - 116          # 120 - 4 present


def test_a_gap_longer_than_the_tolerance_is_stale_not_forward_filled(
        series_a):
    """A 10-minute hole makes the next 20 minutes unencodable, not smoothed."""
    s = series_a
    gap = [m for m in range(120)
           if s.status(D2, m) is H.HistoricalStatus.DATA_GAP]
    stale = [m for m in range(120)
             if s.status(D2, m) is H.HistoricalStatus.STALE_DATA]
    assert gap == list(range(60, 70))
    assert stale == list(range(70, 90))
    for m in stale:
        obs = s.observe(D2, m, stable_id=0)
        assert obs.status is MK.ObservationStatus.STALE_DATA
        assert np.all(obs.normalized == 0.0)
        assert "stale" in obs.detail
    # the staleness window is exactly the declared tolerance plus the lookback
    assert H.MAX_REF_STALENESS_MIN == 5
    assert s.status(D2, 90) is H.HistoricalStatus.OK


def test_a_reference_price_is_a_printed_close_never_an_interpolation(
        series_a):
    """``ref_close`` holds the last price that actually traded."""
    s = series_a
    ses = s.sessions[D1]
    printed = set(np.round(ses.close[ses.present], 10))
    for m in range(120):
        if np.isfinite(ses.ref_close[m]):
            assert round(float(ses.ref_close[m]), 10) in printed
    # inside the gap the reference is minute 99's close, and its age grows
    for k, m in enumerate(range(100, 104)):
        assert ses.ref_close[m] == pytest.approx(float(ses.close[99]))
        assert int(ses.ref_age[m]) == k + 1
    assert int(ses.ref_age[99]) == 0


def test_the_status_taxonomy_never_collides_with_a_neural_one(series_a):
    """DATA_GAP / STALE_DATA / WARMUP are market facts, not brain states."""
    from flytrade import decoder as D
    market = {s.value for s in H.HistoricalStatus}
    neural = {s.value for s in D.ReadoutStatus} | {a.value for a in D.Action}
    assert market & neural == {"OK"} - {"OK"} | set()    # empty intersection
    assert market == {"OK", "WARMUP", "DATA_GAP", "STALE_DATA"}
    assert "NO_RESPONSE" not in market and "WAIT" not in market
    # and every market status maps to a distinct member of the enum the
    # encoder branches on, so nothing is flattened on the way through
    mapped = {H._MARKET_STATUS[s] for s in H.HistoricalStatus}
    assert len(mapped) == 4


def test_horizons_are_counted_in_market_minutes_not_rows(series_a):
    """``fill + H`` is a clock statement about the session grid."""
    s = series_a
    # minute 96 plus 8 market minutes is minute 104, which exists; the four
    # rows between them do not, and the row count between them is 1
    assert s.next_available(D1, 96) == 96
    assert s.next_available(D1, 96 + 8) == 104
    ses = s.sessions[D1]
    rows_between = int(ses.present[97:104].sum())
    assert rows_between == 3                    # minutes 97, 98, 99
    # eight market minutes, three rows: counting rows would have settled at
    # minute 108 instead, five minutes late
    assert int(ses.bar_start[104]) - int(ses.bar_start[96]) == 8 * 60
    present = np.flatnonzero(ses.present)
    row_of_96 = int(np.flatnonzero(present == 96)[0])
    assert int(present[row_of_96 + 8]) == 108


def test_next_available_never_looks_into_another_session(series_a):
    s = series_a
    assert s.next_available(D0, 119) == 119
    assert s.next_available(D0, 120) is None
    assert s.next_available(D0, H.SESSION_MINUTES) is None
    assert s.last_minute(D0) == 119
    assert s.last_minute(date(2026, 8, 6)) is None
