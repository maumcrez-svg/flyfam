"""
HISTORICAL_MARKET — the vendor file, its clock, and causal features on it.

Canonical amendment D6 §3 and Fable addenda 2-4. This module is the only place
a vendor file is read, and it exists because a minute bar from an exchange is
not the same object as a bar from ``flytrade.market.synthetic_series``:

* the timestamp on the row is the bar's **opening** minute, so the row's final
  OHLCV does not exist yet at that instant;
* minutes without a reported trade are **absent from the file**, so the *n*-th
  row is not *n* minutes after the first;
* everything is in America/New_York wall time, which is UTC-4 or UTC-5
  depending on the date.

Nothing here fills a gap, shifts a date, compresses time, or invents a price.

## 1. The file

Headerless, comma-delimited, seven fields::

    Date,Time,Open,High,Low,Close,Volume
    08/03/2026,09:30,272,272.25,269.07,270.54,176225

``Date`` is ``MM/DD/YYYY``. ``Time`` is ``HH:MM`` in the free samples and
``HH:MM:SS`` in the vendor's own format reference; both are accepted and which
one was seen is recorded. Prices may be written in exponent form (``1E-06``),
which ``float`` parses correctly and a fixed-point parser would not.

:func:`parse_kibot_minute` validates and rejects rather than repairs. Field
count, numeric parseability, ``high >= max(open, close) >= min(open, close) >=
low``, strictly positive prices, non-negative volume, strictly increasing
timestamps and the absence of duplicates are all checked, and a violation
raises :class:`VendorFormatError` naming the row. Rows outside the regular
session are **counted and excluded**, never silently kept: the free samples
contain none, a paid file would.

## 2. The clock

Three times, and they are not interchangeable:

=============  =========================================================
``bar_start``  the minute stamped on the row, in UTC seconds
``bar_end``    ``bar_start + 60`` — the first instant the bar's final
               OHLCV exists, and therefore the earliest instant any
               decision may use it
session        ``09:30 <= bar_start < 16:00`` America/New_York, one
               session per calendar date, never crossed by a lookback,
               a horizon or a position
=============  =========================================================

A **market minute** is a slot on the 390-minute session grid, present or not.
Elapsed time is always counted in market minutes; row distance is never used
for anything.

## 3. Features, causally, in elapsed market minutes

The five features of ``flytrade.market`` are unchanged in definition. What
changes is how the prices behind them are located, because the minute a
lookback points at may not exist::

    price_at(tau) = close of the last bar of this session with bar_end <= tau

That is the last price actually printed at or before ``tau`` — a real trade,
not an interpolation — and it is used **only** as a feature input. No execution
price is ever located this way: :class:`HistoricalExecution` takes the *open of
a bar that exists* and flags the delay when the bar it wanted was missing.

Two guards keep that rule from quietly becoming a forward fill:

* **staleness**. If the bar backing any lookback is more than
  :data:`MAX_REF_STALENESS_MIN` market minutes older than the instant the
  lookback points at, the observation is ``STALE_DATA`` and is not encoded.
* **same session**. Every lookback is bounded by the session open, so no
  overnight return ever enters a one-minute feature. The first
  :data:`FEATURE_LOOKBACK` market minutes of every session are therefore
  ``WARMUP``.

``relvol`` divides the bar's own volume by the mean volume **per market
minute** over the trailing 20 market minutes — the sum of the volumes that are
there, divided by 20, because a minute the vendor omitted is a minute in which
nothing traded. That is the one place an absent bar contributes a number, and
the number it contributes is zero.

## 4. Normalisation

The causal z-score of ``flytrade.market`` is preserved exactly: each raw
feature is z-scored against the trailing :data:`Z_WINDOW` **usable feature
rows ending at the cutoff**, then squashed by ``tanh(z / Z_SCALE)``. The window
is a window over this instrument's own past observations; it never contains a
row from the future, never contains a row from the evaluation period while the
learning period is running, and is never computed over the whole file.

Until :data:`Z_WINDOW` usable rows exist the observation is ``WARMUP``.

## 5. The status taxonomy

Amendment §3 requires that "a gap in the data" and "the fly said nothing" never
land in the same counter. Four observation statuses, none of which is a neural
result:

===============  =======================================================
``OK``           encodable
``WARMUP``       causal history not yet available — fewer than 20
                 elapsed market minutes in this session, or fewer than
                 60 usable feature rows behind it
``DATA_GAP``     no bar at this market minute for this instrument
``STALE_DATA``   a lookback's backing bar is older than the tolerance
===============  =======================================================

``NO_RESPONSE``, ``WAIT``, ``INVALID_STATE`` and ``POLICY_REJECT`` are decoder
and policy outcomes and live in ``flytrade/decoder.py``. Nothing in this module
can produce one and nothing in this module is counted as one.

## 6. Execution in historical time

:class:`HistoricalExecution` is ``flytrade.execution.ExecutionPolicy`` with the
bar arithmetic replaced by the clock rules of Fable addendum 4, and with its
sizing, costs, delay and horizon **unchanged** — only reinterpreted into market
minutes. See that class's docstring for the five rules.
"""
from __future__ import annotations

import csv
import hashlib
import math
from dataclasses import dataclass, field
from datetime import date as _date, datetime, time as _time, timezone
from enum import Enum
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from . import execution as X
from . import horizon as HZ
from . import market as MK

VERSION = "flytrade-historical-1"

#: the label this dataset carries everywhere, kept apart from SYNTHETIC
DATASET_LABEL = "HISTORICAL_MARKET"

#: the vendor's wall clock
EXCHANGE_TZ = "America/New_York"
NY = ZoneInfo(EXCHANGE_TZ)

#: regular session, inclusive of the open minute and exclusive of the close
SESSION_OPEN = _time(9, 30)
SESSION_CLOSE = _time(16, 0)
#: 09:30 .. 15:59 inclusive
SESSION_MINUTES = 390

#: one bar
BAR_SECONDS = 60

#: longest raw-feature lookback, in **market minutes**, inside one session
FEATURE_LOOKBACK = MK.FEATURE_LOOKBACK          # 20

#: trailing usable feature rows the causal z-score is taken over
Z_WINDOW = MK.Z_WINDOW                          # 60
#: z divided by this before tanh, unchanged from Phase One
Z_SCALE = MK.Z_SCALE
Z_MIN_SD = MK.Z_MIN_SD

#: how far a lookback's backing bar may lag the instant it points at, in
#: market minutes, before the observation is STALE_DATA rather than encoded
MAX_REF_STALENESS_MIN = 5


class VendorFormatError(ValueError):
    """The vendor file is not what the format reference says it is."""


class HistoricalStatus(str, Enum):
    """Why a historical observation may not be encodable. Never a neural state."""

    OK = "OK"
    WARMUP = "WARMUP"
    DATA_GAP = "DATA_GAP"
    STALE_DATA = "STALE_DATA"

    @property
    def usable(self) -> bool:
        return self is HistoricalStatus.OK


#: the market-side statuses, in the order every report lists them
STATUSES = tuple(s.value for s in HistoricalStatus)


# ----------------------------------------------------------------- time

def ny_minute_ts(day: _date, minute_of_day: int) -> int:
    """UTC epoch seconds of an America/New_York wall-clock minute."""
    h, m = divmod(int(minute_of_day), 60)
    dt = datetime.combine(day, _time(h % 24, m), tzinfo=NY)
    return int(dt.timestamp())


def session_minutes(day: _date) -> np.ndarray:
    """The 390 ``bar_start`` timestamps of one regular session."""
    base = 9 * 60 + 30
    return np.array([ny_minute_ts(day, base + i) for i in range(SESSION_MINUTES)],
                    dtype=np.int64)


def ny_datetime(ts: int) -> datetime:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(NY)


def session_date(ts: int) -> _date:
    return ny_datetime(ts).date()


def minute_index(ts: int) -> int:
    """Position of a ``bar_start`` on its session's 390-minute grid."""
    d = ny_datetime(ts)
    return (d.hour * 60 + d.minute) - (9 * 60 + 30)


def in_regular_session(ts: int) -> bool:
    t = ny_datetime(ts).time()
    return SESSION_OPEN <= t < SESSION_CLOSE


# ----------------------------------------------------------------- parse

@dataclass(frozen=True)
class VendorRow:
    """One parsed row, before it is placed on a session grid."""

    bar_start: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class ParseReport:
    """What the importer saw, validated and rejected. Never a summary only."""

    path: str
    symbol: str
    sha256: str
    bytes: int
    lines: int
    rows: int
    time_format: str
    first_bar: int
    last_bar: int
    sessions: int
    excluded_extended_hours: int
    duplicates: int
    blank_lines: int
    exponent_prices: int
    dataset_label: str = DATASET_LABEL
    importer_version: str = VERSION

    def as_dict(self) -> dict:
        d = dict(self.__dict__)
        d["first_bar_ny"] = str(ny_datetime(self.first_bar))
        d["last_bar_ny"] = str(ny_datetime(self.last_bar))
        return d


def _parse_price(s: str, path, n: int, what: str) -> float:
    try:
        v = float(s)
    except ValueError:
        raise VendorFormatError(
            f"{path}:{n}: {what} {s!r} is not a number") from None
    if not math.isfinite(v):
        raise VendorFormatError(f"{path}:{n}: {what} {s!r} is not finite")
    return v


def parse_kibot_minute(path, symbol: str | None = None) -> tuple[list[VendorRow],
                                                                ParseReport]:
    """Parse and validate one Kibot one-minute file. Rejects, never repairs."""
    path = Path(path)
    symbol = symbol or path.stem.split("_")[0]
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    rows: list[VendorRow] = []
    seen: set[int] = set()
    lines = blank = excluded = duplicates = exponent = 0
    time_formats: set[str] = set()
    first = last = 0

    for n, line in enumerate(text.splitlines(), start=1):
        lines += 1
        if not line.strip():
            blank += 1
            continue
        f = next(csv.reader([line]))
        if len(f) != 7:
            raise VendorFormatError(
                f"{path}:{n}: {len(f)} fields, the one-minute format has 7 "
                f"(Date,Time,Open,High,Low,Close,Volume)")
        ds, tsf = f[0].strip(), f[1].strip()
        try:
            day = datetime.strptime(ds, "%m/%d/%Y").date()
        except ValueError:
            raise VendorFormatError(
                f"{path}:{n}: date {ds!r} is not MM/DD/YYYY") from None
        for fmt, tag in (("%H:%M", "HH:MM"), ("%H:%M:%S", "HH:MM:SS")):
            try:
                tm = datetime.strptime(tsf, fmt).time()
                time_formats.add(tag)
                break
            except ValueError:
                tm = None
        if tm is None:
            raise VendorFormatError(
                f"{path}:{n}: time {tsf!r} is neither HH:MM nor HH:MM:SS")
        if tm.second:
            raise VendorFormatError(
                f"{path}:{n}: time {tsf!r} is not on a minute boundary")
        o = _parse_price(f[2], path, n, "open")
        h = _parse_price(f[3], path, n, "high")
        lo = _parse_price(f[4], path, n, "low")
        c = _parse_price(f[5], path, n, "close")
        v = _parse_price(f[6], path, n, "volume")
        if any("e" in x.lower() for x in f[2:6]):
            exponent += 1
        if min(o, h, lo, c) <= 0.0:
            raise VendorFormatError(
                f"{path}:{n}: non-positive price in {f[2:6]}")
        if v < 0.0:
            raise VendorFormatError(f"{path}:{n}: negative volume {f[6]!r}")
        if not (h >= max(o, c) and lo <= min(o, c) and h >= lo):
            raise VendorFormatError(
                f"{path}:{n}: OHLC relationship violated "
                f"(o={o} h={h} l={lo} c={c})")
        ts = int(datetime.combine(day, tm, tzinfo=NY).timestamp())
        if not in_regular_session(ts):
            excluded += 1
            continue
        if ts in seen:
            duplicates += 1
            raise VendorFormatError(
                f"{path}:{n}: duplicate timestamp {ny_datetime(ts)}")
        if rows and ts <= rows[-1].bar_start:
            raise VendorFormatError(
                f"{path}:{n}: timestamps are not strictly increasing "
                f"({ny_datetime(ts)} after {ny_datetime(rows[-1].bar_start)})")
        seen.add(ts)
        rows.append(VendorRow(bar_start=ts, open=o, high=h, low=lo, close=c,
                              volume=v))

    if len(rows) < 2:
        raise VendorFormatError(f"{path}: {len(rows)} usable rows, needs at "
                                f"least two")
    first, last = rows[0].bar_start, rows[-1].bar_start
    report = ParseReport(
        path=str(path), symbol=symbol,
        sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw), lines=lines,
        rows=len(rows), time_format="/".join(sorted(time_formats)),
        first_bar=first, last_bar=last,
        sessions=len({session_date(r.bar_start) for r in rows}),
        excluded_extended_hours=excluded, duplicates=duplicates,
        blank_lines=blank, exponent_prices=exponent)
    return rows, report


# ---------------------------------------------------------------- series

@dataclass
class Session:
    """One regular session of one instrument, on the dense 390-minute grid.

    Absent minutes are represented, never removed: ``present`` says which of
    the 390 slots the vendor actually reported. Nothing is forward-filled into
    ``open``/``close``; the forward reference used by the *features* is the
    separate ``ref_close``/``ref_age`` pair, and it never reaches an execution.
    """

    day: _date
    bar_start: np.ndarray          # (390,) int64, UTC seconds
    present: np.ndarray            # (390,) bool
    open: np.ndarray               # (390,) float64, NaN where absent
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray             # (390,) float64, 0.0 where absent
    ref_close: np.ndarray = field(repr=False, default=None)   # type: ignore
    ref_age: np.ndarray = field(repr=False, default=None)     # type: ignore

    @property
    def n_present(self) -> int:
        return int(self.present.sum())

    @property
    def missing(self) -> int:
        return SESSION_MINUTES - self.n_present

    @property
    def last_present_minute(self) -> int:
        return int(np.flatnonzero(self.present)[-1])

    def build_reference(self) -> None:
        """``ref_close[m]`` = last printed close at or before minute ``m``."""
        n = SESSION_MINUTES
        rc = np.full(n, np.nan)
        ra = np.full(n, 10 ** 6, dtype=np.int64)
        lastc, lastm = np.nan, -1
        for m in range(n):
            if self.present[m]:
                lastc, lastm = self.close[m], m
            rc[m] = lastc
            ra[m] = (m - lastm) if lastm >= 0 else 10 ** 6
        self.ref_close, self.ref_age = rc, ra


class HistoricalSeries:
    """One instrument's sessions, the market-minute grid, and its features.

    The feature table is computed once, forward, for every market minute of
    every session in the file. Row ``i`` uses bars at or before minute ``i`` of
    its own session and nothing else, so the table is causal by construction
    rather than by a promise about the order calls arrive in.
    """

    version = VERSION
    label = DATASET_LABEL

    def __init__(self, symbol: str, rows, report: ParseReport):
        self.symbol = symbol
        self.report = report
        by_day: dict[_date, list[VendorRow]] = {}
        for r in rows:
            by_day.setdefault(session_date(r.bar_start), []).append(r)
        self.sessions: dict[_date, Session] = {}
        for day, rs in by_day.items():
            ts = session_minutes(day)
            idx = {int(t): i for i, t in enumerate(ts)}
            n = SESSION_MINUTES
            s = Session(day=day, bar_start=ts,
                        present=np.zeros(n, dtype=bool),
                        open=np.full(n, np.nan), high=np.full(n, np.nan),
                        low=np.full(n, np.nan), close=np.full(n, np.nan),
                        volume=np.zeros(n))
            for r in rs:
                i = idx[r.bar_start]
                s.present[i] = True
                s.open[i], s.high[i] = r.open, r.high
                s.low[i], s.close[i] = r.low, r.close
                s.volume[i] = r.volume
            s.build_reference()
            self.sessions[day] = s
        self.days = tuple(sorted(self.sessions))
        self._features: dict[_date, tuple[np.ndarray, np.ndarray]] = {}
        for day in self.days:
            self._features[day] = self._session_features(self.sessions[day])
        self._usable_history: dict[int, np.ndarray] = {}
        self._build_usable_history()

    # -- raw features ----------------------------------------------------

    def _session_features(self, s: Session) -> tuple[np.ndarray, np.ndarray]:
        """(raw features (390, 5), status code (390,)) for one session.

        Status codes: 0 OK, 1 WARMUP, 2 DATA_GAP, 3 STALE_DATA.
        """
        n = SESSION_MINUTES
        raw = np.zeros((n, len(MK.FEATURES)))
        code = np.full(n, 2, dtype=np.int8)             # DATA_GAP by default
        rc, ra = s.ref_close, s.ref_age
        for m in range(n):
            if not s.present[m]:
                continue                                 # DATA_GAP
            if m < FEATURE_LOOKBACK:
                code[m] = 1                              # WARMUP: session start
                continue
            lags = (1, 5, FEATURE_LOOKBACK)
            need = set(lags) | set(range(1, FEATURE_LOOKBACK + 1))
            stale = False
            for k in need:
                j = m - k
                if not np.isfinite(rc[j]) or ra[j] > MAX_REF_STALENESS_MIN:
                    stale = True
                    break
            if stale:
                code[m] = 3                              # STALE_DATA
                continue
            p0 = float(s.close[m])
            r1 = math.log(p0 / rc[m - 1])
            r5 = math.log(p0 / rc[m - 5])
            r20 = math.log(p0 / rc[m - FEATURE_LOOKBACK])
            steps = np.empty(FEATURE_LOOKBACK)
            prev = p0
            for j in range(1, FEATURE_LOOKBACK + 1):
                cur = rc[m - j]
                steps[j - 1] = math.log(prev / cur)
                prev = cur
            rv20 = float(steps.std(ddof=1))
            vm = float(s.volume[m - FEATURE_LOOKBACK + 1:m + 1].sum()
                       / FEATURE_LOOKBACK)
            v0 = float(s.volume[m])
            relvol = math.log(v0 / vm) if vm > 0.0 and v0 > 0.0 else 0.0
            raw[m] = (r1, r5, r20, rv20, relvol)
            code[m] = 0
        return raw, code

    def _build_usable_history(self) -> None:
        """For every OK minute, how many OK rows precede it in this file."""
        count = 0
        for day in self.days:
            _, code = self._features[day]
            arr = np.full(SESSION_MINUTES, -1, dtype=np.int64)
            for m in range(SESSION_MINUTES):
                if code[m] == 0:
                    arr[m] = count
                    count += 1
            self._usable_history[int(self.sessions[day].bar_start[0])] = arr
        self.n_usable = count
        # the chronological table of usable raw rows, for the trailing z-window
        self._usable_raw = np.zeros((count, len(MK.FEATURES)))
        i = 0
        for day in self.days:
            rawm, code = self._features[day]
            for m in range(SESSION_MINUTES):
                if code[m] == 0:
                    self._usable_raw[i] = rawm[m]
                    i += 1

    # -- lookups ---------------------------------------------------------

    def has_session(self, day: _date) -> bool:
        return day in self.sessions

    def bar(self, day: _date, m: int):
        s = self.sessions.get(day)
        if s is None or not (0 <= m < SESSION_MINUTES) or not s.present[m]:
            return None
        return MK.Bar(ts=int(s.bar_start[m]), open=float(s.open[m]),
                      high=float(s.high[m]), low=float(s.low[m]),
                      close=float(s.close[m]), volume=float(s.volume[m]))

    def next_available(self, day: _date, m: int) -> int | None:
        """First present minute ``>= m`` in this session, or None."""
        s = self.sessions.get(day)
        if s is None or m >= SESSION_MINUTES:
            return None
        m = max(0, int(m))
        nz = np.flatnonzero(s.present[m:])
        return None if len(nz) == 0 else int(m + nz[0])

    def last_minute(self, day: _date) -> int | None:
        s = self.sessions.get(day)
        return None if s is None else s.last_present_minute

    def status(self, day: _date, m: int) -> HistoricalStatus:
        s = self.sessions.get(day)
        if s is None:
            return HistoricalStatus.DATA_GAP
        code = self._features[day][1][m]
        st = (HistoricalStatus.OK, HistoricalStatus.WARMUP,
              HistoricalStatus.DATA_GAP, HistoricalStatus.STALE_DATA)[int(code)]
        if st is HistoricalStatus.OK and \
                self._usable_history[int(s.bar_start[0])][m] < Z_WINDOW - 1:
            return HistoricalStatus.WARMUP
        return st

    # -- one observation -------------------------------------------------

    def observe(self, day: _date, m: int, *, stable_id: int = -1,
                bar_index: int = -1) -> MK.MarketObservation:
        """The encoder-ready observation of this instrument at ``bar_end(m)``.

        ``cutoff_ts`` is ``bar_end`` — the first instant the bar's final OHLCV
        exists — and never ``bar_start``. An unusable observation carries all
        zeros and its own status, exactly as ``flytrade.market`` does.
        """
        s = self.sessions.get(day)
        ts0 = int(s.bar_start[m]) if s is not None else ny_minute_ts(
            day, 9 * 60 + 30 + m)
        blank = dict(symbol=self.symbol, stable_id=int(stable_id),
                     bar_index=int(bar_index) if bar_index >= 0 else int(m),
                     cutoff_ts=ts0 + BAR_SECONDS,
                     close=float(s.close[m]) if (s is not None and s.present[m])
                     else float("nan"))
        st = self.status(day, m)
        if st is not HistoricalStatus.OK:
            return MK.MarketObservation(
                status=_MARKET_STATUS[st], detail=_DETAIL[st], **blank)
        raw = self._features[day][0][m]
        j = int(self._usable_history[int(s.bar_start[0])][m])
        hist = self._usable_raw[j - Z_WINDOW + 1:j + 1]
        mu = hist.mean(axis=0)
        sd = hist.std(axis=0, ddof=1)
        z = np.where(sd > Z_MIN_SD, (raw - mu) / np.where(sd > Z_MIN_SD, sd, 1.0),
                     0.0)
        u = np.tanh(z / Z_SCALE)
        return MK.MarketObservation(status=MK.ObservationStatus.OK, raw=raw,
                                    normalized=u, z=z, **blank)

    # -- reporting -------------------------------------------------------

    def coverage(self, first: _date, last: _date) -> dict:
        out = {"symbol": self.symbol, "label": self.label, "days": [],
               "bars": 0, "missing": 0, "complete": 0}
        for day in self.days:
            if not (first <= day <= last):
                continue
            s = self.sessions[day]
            out["days"].append({"date": str(day), "bars": s.n_present,
                                "missing": s.missing})
            out["bars"] += s.n_present
            out["missing"] += s.missing
            out["complete"] += SESSION_MINUTES
        out["n_days"] = len(out["days"])
        return out

    def status_counts(self, first: _date, last: _date) -> dict:
        out = {s.value: 0 for s in HistoricalStatus}
        for day in self.days:
            if first <= day <= last:
                for m in range(SESSION_MINUTES):
                    out[self.status(day, m).value] += 1
        return out


#: the historical statuses, expressed in the enum the encoder already branches
#: on. ``flytrade.market.ObservationStatus`` gained these three members in this
#: wave so that a historical status never has to be flattened into a Phase One
#: name to travel through the existing pipeline.
_MARKET_STATUS = {
    HistoricalStatus.OK: MK.ObservationStatus.OK,
    HistoricalStatus.WARMUP: MK.ObservationStatus.WARMUP,
    HistoricalStatus.DATA_GAP: MK.ObservationStatus.DATA_GAP,
    HistoricalStatus.STALE_DATA: MK.ObservationStatus.STALE_DATA,
}
_DETAIL = {
    HistoricalStatus.OK: "",
    HistoricalStatus.WARMUP: "causal history not yet available",
    HistoricalStatus.DATA_GAP: "no bar reported at this market minute",
    HistoricalStatus.STALE_DATA:
        f"a lookback reference is more than {MAX_REF_STALENESS_MIN} market "
        f"minutes stale",
}


def load_series(path, symbol: str | None = None) -> HistoricalSeries:
    rows, report = parse_kibot_minute(path, symbol)
    return HistoricalSeries(report.symbol, rows, report)


# ------------------------------------------------------------ partitions

@dataclass(frozen=True)
class Partition:
    """One inclusive date range of the fixed historical protocol."""

    name: str
    first: _date
    last: _date
    learning: bool
    neural: bool

    def contains(self, day: _date) -> bool:
        return self.first <= day <= self.last

    def as_dict(self) -> dict:
        return {"name": self.name, "first": str(self.first),
                "last": str(self.last), "learning": self.learning,
                "neural": self.neural}


def partitions_from(spec: dict) -> tuple[Partition, ...]:
    """Build the partitions from the committed config's date strings."""
    out = []
    for name in ("WARMUP", "LEARNING", "FROZEN"):
        d = spec[name]
        out.append(Partition(
            name=name, first=_date.fromisoformat(d["first"]),
            last=_date.fromisoformat(d["last"]),
            learning=bool(d["learning"]), neural=bool(d["neural"])))
    return tuple(out)


def partition_of(parts, day: _date) -> Partition | None:
    for p in parts:
        if p.contains(day):
            return p
    return None


def round_grid(series: dict[str, HistoricalSeries], first: _date,
               last: _date) -> list[tuple[_date, int]]:
    """Every market minute in the window at which **any** instrument has a bar.

    The round cadence is one decision round per regular-session minute bar
    (Fable addendum 3). An instrument with no bar at that minute is a
    ``DATA_GAP`` candidate in that round; it does not remove the round.
    """
    days: set[_date] = set()
    for s in series.values():
        days |= {d for d in s.days if first <= d <= last}
    grid: list[tuple[_date, int]] = []
    for day in sorted(days):
        any_present = np.zeros(SESSION_MINUTES, dtype=bool)
        for s in series.values():
            if s.has_session(day):
                any_present |= s.sessions[day].present
        grid.extend((day, int(m)) for m in np.flatnonzero(any_present))
    return grid


# ------------------------------------------------------- execution rules

#: fill-timing flags. Absent means the fill landed on the minute the policy
#: asked for; these say it did not, and why.
DELAYED_FILL = "DELAYED_FILL"
SESSION_CLOSE_FILL = "SESSION_CLOSE_FILL"

#: D9(b): the closure reasons that mean "the declared horizon expired". Both
#: settle at ``max(round minute, entry fill minute + H)`` — the anchor
#: :func:`flytrade.horizon.locate` gives the evaluator's ``Hold`` — and never
#: at ``decision + delay``, which is where a *decided* exit would land.
POLICY_CLOSURES = (X.CloseReason.POLICY_CLOSE,
                   X.CloseReason.POLICY_CLOSE_FIXED_HOLD)


class HistoricalExecution(X.ExecutionPolicy):
    """Paper execution on historical minute bars. Fable addendum 4, verbatim.

    The v1 policy's numbers are untouched — fixed notional, one open long,
    fee and slippage in basis points **per execution**, delay 1, horizon 8.
    What this class fixes is what "1" and "8" mean when the minute they point
    at may not exist:

    1. The decision is taken at ``bar_end(t)``. That is the first instant the
       bar's final OHLCV exists, so no order can use a price that was not yet
       published, and no order uses the decision bar's own high, low or close.
    2. The fill is the **open** of the first available regular-session bar with
       ``bar_start >= bar_end(t)`` in the same session. If that is not the next
       calendar minute, the fill carries ``DELAYED_FILL`` and the elapsed
       market minutes.
    3. The horizon is ``horizon_minutes`` **market minutes** measured from the
       fill's ``bar_start``. Settlement is the open of the first available bar
       with ``bar_start >= fill + H``, flagged the same way when delayed.
    4. Entry eligibility is a clock rule and is checked before anything is
       measured against a price: ``bar_end(t) + (H + 1) minutes <= 16:00`` in
       the same session. A decision that fails it is ``POLICY_REJECT`` with
       reason ``SESSION_HORIZON``.
    5. A position still open at the session's last available bar — reachable
       only through gaps — is closed at that bar's **close** with
       ``SESSION_CLOSE_FILL`` and counted apart. Nothing crosses a day, so
       nothing crosses a partition.

    A due fill or settlement with no valid price is never invented: it is a
    recorded :class:`flytrade.execution.Rejection` with its own reason.

    One sequencing guard that is not in the addendum but follows from "one
    open position": an entry may not *fill* before the previous exit filled.
    A delayed exit therefore delays the next entry, and the delay is flagged
    like any other. Without it a gap could let a new position open behind an
    exit that had not yet landed.
    """

    version = X.VERSION + "+historical-1"

    #: costs, stated once. Both are charged **per execution**, i.e. twice per
    #: round trip: FEE_BPS on the entry and again on the exit, SLIPPAGE_BPS
    #: against the trader on each fill. A 5 bps fee and 5 bps slippage are
    #: therefore 20 bps over a completed round trip, and neither parameter is
    #: applied twice to the same execution.
    COST_BASIS = "per execution (charged on entry and again on exit)"

    def __init__(self, series: dict[str, HistoricalSeries], *,
                 horizon_minutes: int = X.HORIZON_BARS,
                 delay_minutes: int = X.DELAY_BARS, **kw):
        super().__init__(feed=None, horizon_bars=horizon_minutes,
                         delay_bars=delay_minutes, **kw)
        self.series = dict(series)
        self.horizon_minutes = int(horizon_minutes)
        self.delay_minutes = int(delay_minutes)
        self.day: _date | None = None
        self.session_close_fills = 0
        self.delayed_fills = 0
        self._last_exit_minute = -1

    # -- the clock rules --------------------------------------------------

    def start_session(self, day: _date) -> None:
        """Begin a session. Nothing carries over: no position, no fill floor."""
        if self.account.position is not None:
            raise AssertionError(
                f"a position was still open entering {day}: nothing may cross "
                f"a session boundary")
        self.day = day
        self._last_exit_minute = -1

    def eligible_to_enter(self, m: int) -> bool:
        """Rule 4. ``bar_end + 1 min + H <= 16:00`` on the same session."""
        return (int(m) + 1) + 1 + self.horizon_minutes <= SESSION_MINUTES

    def _locate(self, symbol: str, day: _date, target_minute: int):
        """First available bar at or after ``target_minute``, same session.

        D7 Fable addendum 1: this is :func:`flytrade.horizon.locate`, the one
        primitive the calibration return ``g(t,H)`` and the evaluator label
        ``G(t)`` also locate their bars with, so the fill convention has one
        implementation and three callers rather than three implementations
        that agree today.
        """
        return HZ.locate(self.series[symbol], day, target_minute)

    # -- opening ----------------------------------------------------------

    def open_long(self, *, episode_id: int, symbol: str, stable_id: int,
                  decision_bar: int, day: _date | None = None
                  ) -> X.Position | X.Rejection:
        day = self.day if day is None else day
        m = int(decision_bar)
        if self.account.position is not None:
            return self.reject("BUY", symbol, m, X.RejectReason.POSITION_OPEN)
        if not self.eligible_to_enter(m):
            return self.reject("BUY", symbol, m, X.RejectReason.SESSION_HORIZON)
        want = max(m + self.delay_minutes, self._last_exit_minute + 1)
        fm, bar = self._locate(symbol, day, want)
        if bar is None:
            return self.reject("BUY", symbol, m, X.RejectReason.NO_FUTURE_BAR)
        if bar.is_nan or bar.open <= 0:
            return self.reject("BUY", symbol, m, X.RejectReason.BAD_PRICE)
        if fm + self.horizon_minutes >= SESSION_MINUTES:
            return self.reject("BUY", symbol, m, X.RejectReason.SESSION_HORIZON)
        delay = fm - m
        price = self._fill_price(bar.open, X.Side.BUY)
        qty = self.notional / price
        fee = self._fee(qty, price)
        if qty * price + fee > self.account.cash:
            return self.reject("BUY", symbol, m,
                               X.RejectReason.INSUFFICIENT_CASH)
        flag = "" if delay == self.delay_minutes else DELAYED_FILL
        if flag:
            self.delayed_fills += 1
        entry = X.Fill(side=X.Side.BUY, symbol=symbol, bar_index=fm,
                       ts=bar.ts, reference_price=bar.open, fill_price=price,
                       quantity=qty, fee=fee, delay_minutes=delay, flag=flag)
        self.account.cash -= qty * price + fee
        self.account.fees_paid += fee
        self.account.position = X.Position(
            episode_id=int(episode_id), symbol=symbol,
            stable_id=int(stable_id), entry=entry,
            horizon_bar=fm + self.horizon_minutes, day=day)
        return self.account.position

    # -- closing ----------------------------------------------------------

    def due_for_horizon(self, bar_index: int) -> bool:
        p = self.account.position
        return p is not None and int(bar_index) >= p.horizon_bar

    def session_last_minute(self, day: _date, symbol: str) -> int | None:
        return self.series[symbol].last_minute(day)

    def close(self, *, decision_bar: int, reason: X.CloseReason,
              day: _date | None = None, session_close: bool = False
              ) -> X.OutcomeRecord | X.Rejection:
        day = self.day if day is None else day
        p = self.account.position
        m = int(decision_bar)
        if p is None:
            return self.reject("SELL", "", m, X.RejectReason.NO_POSITION)
        s = self.series[p.symbol]
        if session_close:
            lm = s.last_minute(day)
            bar = s.bar(day, lm) if lm is not None else None
            if bar is None or bar.is_nan or bar.close <= 0:
                return self.reject("SELL", p.symbol, m,
                                   X.RejectReason.BAD_PRICE)
            fm, ref, flag = lm, bar.close, SESSION_CLOSE_FILL
            self.session_close_fills += 1
            delay = max(0, fm - p.horizon_bar)
        else:
            want = (max(m, p.horizon_bar)
                    if reason in POLICY_CLOSURES
                    else m + self.delay_minutes)
            fm, bar = self._locate(p.symbol, day, want)
            if bar is None:
                # no bar left in this session: rule 5, the session close
                return self.close(decision_bar=m, reason=reason, day=day,
                                  session_close=True)
            if bar.is_nan or bar.open <= 0:
                return self.reject("SELL", p.symbol, m,
                                   X.RejectReason.BAD_PRICE)
            ref = bar.open
            delay = fm - want
            flag = "" if fm == want else DELAYED_FILL
            if flag:
                self.delayed_fills += 1
        price = self._fill_price(ref, X.Side.SELL)
        fee = self._fee(p.quantity, price)
        exit_fill = X.Fill(side=X.Side.SELL, symbol=p.symbol, bar_index=fm,
                           ts=int(s.sessions[day].bar_start[fm]),
                           reference_price=ref, fill_price=price,
                           quantity=p.quantity, fee=fee,
                           delay_minutes=int(delay), flag=flag)
        self._last_exit_minute = int(fm)
        return self._settle(p, exit_fill, reason,
                            market_minutes=fm - p.entry.bar_index)

    # -- reporting --------------------------------------------------------

    def as_dict(self) -> dict:
        d = super().as_dict()
        d.update({"version": self.version,
                  "delay_minutes": self.delay_minutes,
                  "horizon_minutes": self.horizon_minutes,
                  "cost_basis": self.COST_BASIS,
                  "entry_eligibility":
                      "bar_end + 1 market minute + H <= 16:00, same session",
                  "fill_rule":
                      "open of the first available regular-session bar with "
                      "bar_start >= bar_end(decision)",
                  "settlement_rule":
                      "open of the first available bar with bar_start >= "
                      "fill bar_start + H market minutes",
                  "session_close_rule":
                      "close of the session's last available bar, flagged "
                      "SESSION_CLOSE_FILL",
                  "dataset_label": DATASET_LABEL})
        return d

    def stats(self) -> dict:
        d = super().stats()
        d.update({"delayed_fills": self.delayed_fills,
                  "session_close_fills": self.session_close_fills})
        return d
