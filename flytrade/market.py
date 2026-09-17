"""
Market observations — the only place bar data enters the system.

Canonical amendment §1 and Fable addendum 7. Two rules shape this module and
neither is negotiable:

**Offline only.** There is no provider, no client, no URL and no key anywhere
in Flytrade. A series comes either from a local CSV in the documented format
below or from a seeded synthetic generator. Both are deterministic.

**Observation and outcome are different interfaces.** :class:`ObservationFeed`
can only ever see bars at or before a cutoff index — it has no method that
returns a later bar, so the encoder and the brain cannot read a future label
even by mistake. :class:`ExecutionFeed` is the *only* object that reads bars
after the cutoff, and it is used exclusively by ``flytrade/execution.py``.

## Local CSV format

One file per symbol, ``data/market/<SYMBOL>.csv`` (gitignored), header
required, rows in strictly increasing timestamp order::

    timestamp,open,high,low,close,volume
    2024-01-02T00:00:00Z,100.0,101.5,99.2,100.8,12345

``timestamp`` is ISO-8601 UTC. A row whose ``close`` is empty or unparseable
becomes a bar with ``NaN`` fields and is reported as a data gap rather than
silently dropped or interpolated: a missing bar is a fact about the data, not
something to smooth over.

## Features

Five measurements, all causal — computed from bars at or before the cutoff and
from nothing else:

===========  =======================================================
``r1``       one-bar log return
``r5``       five-bar log return
``r20``      twenty-bar log return
``rv20``     realised volatility, SD of the last 20 one-bar log returns
``relvol``   log of bar volume over its own trailing 20-bar mean
===========  =======================================================

## Normalisation

Each raw feature is z-scored against its own trailing distribution over the
last ``Z_WINDOW`` bars **ending at the cutoff**, then squashed:

    u = tanh(z / Z_SCALE),     u in (-1, 1)

The trailing window is recomputed at every cutoff and never looks forward, so
normalisation constants cannot leak information from the evaluation period.
This is the reason the encoder needs ``MIN_HISTORY_BARS`` of history and
reports ``INSUFFICIENT_HISTORY`` rather than guessing when it does not have it.
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

import numpy as np

VERSION = "flytrade-market-1"

#: feature names, in the fixed order the encoder maps to channels
FEATURES = ("r1", "r5", "r20", "rv20", "relvol")

#: bars of trailing distribution used by the causal z-score
Z_WINDOW = 60
#: longest raw-feature lookback (r20 / rv20 / relvol)
FEATURE_LOOKBACK = 20
#: bars of history an observation needs before it can be encoded at all
MIN_HISTORY_BARS = Z_WINDOW + FEATURE_LOOKBACK + 1      # 81

#: z divided by this before tanh; 2 sigma maps to tanh(1) = 0.762
Z_SCALE = 2.0

#: a trailing window flatter than this is treated as having no scale, and the
#: z-score of the current value is reported as 0 rather than as a huge number
Z_MIN_SD = 1e-9


class ObservationStatus(str, Enum):
    """Why an observation may not be usable. Never silently ignored."""

    OK = "OK"
    #: fewer than MIN_HISTORY_BARS bars at or before the cutoff
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    #: the cutoff bar is older than the caller's staleness tolerance
    STALE = "STALE"
    #: a NaN bar or a timestamp gap inside the window
    GAP = "GAP"

    # D6. The historical path (``flytrade/historical.py``) needs its own three
    # names, because amendment §3 requires that a gap in a vendor file, a
    # not-yet-warm normaliser and a stale reference price never share a counter
    # with each other or with a neural NO_RESPONSE. They are separate members
    # rather than aliases of the three above so that a report can never flatten
    # "the vendor omitted this minute" into "the synthetic series had a NaN".
    #: causal history not yet available: fewer than FEATURE_LOOKBACK elapsed
    #: market minutes in this session, or fewer than Z_WINDOW usable rows
    WARMUP = "WARMUP"

    # D10. The Pons path needs its own two names for the same reason D6 needed
    # three: a memecoin ninety seconds old and a curve whose reconstructed
    # reserves fail their own arithmetic are different conditions, and neither
    # may ever share a counter with a vendor gap in a minute-bar file.
    #: fewer than MIN_AGE_S seconds since the launch block, or fewer than
    #: MIN_TRADES trades at the cutoff (``flytrade.pons.context``)
    INSUFFICIENT_TAPE = "INSUFFICIENT_TAPE"
    #: the curve state reconstructed from the event stream does not reproduce
    #: the curve's own arithmetic, so no price may be quoted from it
    INCONSISTENT_STATE = "INCONSISTENT_STATE"
    #: the bonding curve completed and the market moved to the Uniswap V4 route
    #: this wave does not price. Not an inconsistency and not a missing
    #: measurement: the route changed, and it has its own name for that reason.
    ROUTE_COMPLETED = "ROUTE_COMPLETED"
    #: no bar reported at this market minute for this instrument
    DATA_GAP = "DATA_GAP"
    #: a lookback's backing bar is older than the declared tolerance
    STALE_DATA = "STALE_DATA"

    @property
    def usable(self) -> bool:
        return self is ObservationStatus.OK


@dataclass(frozen=True)
class Bar:
    """One OHLCV bar. ``ts`` is epoch seconds, UTC."""

    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def is_nan(self) -> bool:
        return not all(math.isfinite(x) for x in
                       (self.open, self.high, self.low, self.close, self.volume))


def _parse_ts(s: str) -> int:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _f(s: str) -> float:
    s = s.strip()
    if not s:
        return float("nan")
    try:
        return float(s)
    except ValueError:
        return float("nan")


@dataclass
class Series:
    """One instrument's bars, in strictly increasing time order."""

    symbol: str
    bars: tuple[Bar, ...]
    interval_s: int

    def __len__(self) -> int:
        return len(self.bars)

    def __getitem__(self, i: int) -> Bar:
        return self.bars[i]

    @property
    def close(self) -> np.ndarray:
        return np.array([b.close for b in self.bars], dtype=np.float64)

    @property
    def volume(self) -> np.ndarray:
        return np.array([b.volume for b in self.bars], dtype=np.float64)


def load_csv(path, symbol: str | None = None) -> Series:
    """Read one symbol's bars from the documented local CSV format."""
    path = Path(path)
    symbol = symbol or path.stem
    rows: list[Bar] = []
    with open(path, newline="", encoding="utf-8") as fh:
        rd = csv.DictReader(fh)
        need = {"timestamp", "open", "high", "low", "close", "volume"}
        missing = need - set(rd.fieldnames or ())
        if missing:
            raise ValueError(f"{path}: CSV is missing columns {sorted(missing)}")
        for n, row in enumerate(rd, start=2):
            rows.append(Bar(ts=_parse_ts(row["timestamp"]),
                            open=_f(row["open"]), high=_f(row["high"]),
                            low=_f(row["low"]), close=_f(row["close"]),
                            volume=_f(row["volume"])))
    if len(rows) < 2:
        raise ValueError(f"{path}: needs at least two bars")
    ts = [b.ts for b in rows]
    if any(b <= a for a, b in zip(ts, ts[1:])):
        raise ValueError(f"{path}: timestamps are not strictly increasing")
    diffs = sorted(b - a for a, b in zip(ts, ts[1:]))
    interval = int(diffs[len(diffs) // 2])          # median spacing
    return Series(symbol=symbol, bars=tuple(rows), interval_s=interval)


# ------------------------------------------------------------- synthetic

#: one synthetic bar of simulated market time
BAR_SECONDS = 3600
#: epoch of the first synthetic bar (2024-01-02T00:00:00Z)
SYNTHETIC_EPOCH = 1704153600


@dataclass(frozen=True)
class Regime:
    """A stretch of synthetic market with its own drift and volatility."""

    bars: int
    drift: float          # per-bar log drift
    vol: float            # per-bar log-return SD


#: the default regime programme: quiet drift up, sharp fall, chop, rally.
DEFAULT_REGIMES = (
    Regime(bars=120, drift=+0.0006, vol=0.004),
    Regime(bars=90, drift=-0.0018, vol=0.011),
    Regime(bars=110, drift=+0.0000, vol=0.006),
    Regime(bars=100, drift=+0.0014, vol=0.005),
)


def synthetic_series(symbol: str, seed: int, *, regimes=DEFAULT_REGIMES,
                     start_price: float = 100.0,
                     interval_s: int = BAR_SECONDS,
                     start_ts: int = SYNTHETIC_EPOCH) -> Series:
    """A seeded random walk with regime shifts. Deterministic in ``seed``.

    Bars are built from a log-return path; the high/low straddle the bar and
    the volume is lognormal with a mild volatility coupling, so ``relvol``
    carries information rather than noise alone.
    """
    rng = np.random.default_rng(seed)
    rets, vols = [], []
    for rg in regimes:
        rets.append(rng.normal(rg.drift, rg.vol, size=rg.bars))
        vols.append(np.full(rg.bars, rg.vol, dtype=np.float64))
    r = np.concatenate(rets)
    v = np.concatenate(vols)
    n = len(r)
    price = start_price * np.exp(np.cumsum(r))
    prev = np.concatenate(([start_price], price[:-1]))
    spread = np.abs(r) + 0.4 * v
    hi = np.maximum(prev, price) * (1.0 + spread * rng.uniform(0.2, 1.0, n))
    lo = np.minimum(prev, price) * (1.0 - spread * rng.uniform(0.2, 1.0, n))
    base_vol = 1.0e6
    vol_mult = np.exp(rng.normal(0.0, 0.35, n) + 12.0 * np.abs(r))
    volume = base_vol * vol_mult

    bars = tuple(
        Bar(ts=start_ts + i * interval_s, open=float(prev[i]), high=float(hi[i]),
            low=float(lo[i]), close=float(price[i]), volume=float(volume[i]))
        for i in range(n))
    return Series(symbol=symbol, bars=bars, interval_s=interval_s)


def write_csv(series: Series, path) -> Path:
    """Write a series in the documented local CSV format."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for b in series.bars:
            ts = datetime.fromtimestamp(b.ts, tz=timezone.utc)
            w.writerow([ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        f"{b.open:.6f}", f"{b.high:.6f}", f"{b.low:.6f}",
                        f"{b.close:.6f}", f"{b.volume:.2f}"])
    return path


# ------------------------------------------------------------ observation

@dataclass(frozen=True)
class MarketObservation:
    """Everything the encoder is allowed to know about one instrument.

    ``raw`` and ``normalized`` are aligned to :data:`FEATURES`. ``normalized``
    is all-zero whenever ``status`` is not OK; a caller must check ``status``
    and never treat an unusable observation as a flat market.
    """

    symbol: str
    stable_id: int
    bar_index: int
    cutoff_ts: int
    status: ObservationStatus
    raw: np.ndarray = field(default_factory=lambda: np.zeros(len(FEATURES)))
    normalized: np.ndarray = field(default_factory=lambda: np.zeros(len(FEATURES)))
    z: np.ndarray = field(default_factory=lambda: np.zeros(len(FEATURES)))
    close: float = float("nan")
    detail: str = ""
    #: D10: which features ``raw`` and ``normalized`` are aligned to. Defaults
    #: to this module's five, so every D5-D9(b) record is unchanged; the Pons
    #: path passes its own eight, so ``as_dict`` names them correctly instead
    #: of silently truncating to five under ``zip``.
    feature_names: tuple[str, ...] = FEATURES

    def as_dict(self) -> dict:
        names = self.feature_names
        return {
            "symbol": self.symbol, "stable_id": self.stable_id,
            "bar_index": self.bar_index, "cutoff_ts": self.cutoff_ts,
            "status": self.status.value, "close": self.close,
            "raw": {k: float(v) for k, v in zip(names, self.raw)},
            "normalized": {k: float(v) for k, v in zip(names, self.normalized)},
            "detail": self.detail,
        }


def _raw_features(close: np.ndarray, volume: np.ndarray, i: int) -> np.ndarray:
    """The five raw measurements at bar ``i``, from bars <= i only."""
    lr = math.log(close[i] / close[i - 1])
    r5 = math.log(close[i] / close[i - 5])
    r20 = math.log(close[i] / close[i - 20])
    seg = np.log(close[i - 19:i + 1] / close[i - 20:i])
    rv20 = float(seg.std(ddof=1))
    vm = float(volume[i - 19:i + 1].mean())
    relvol = math.log(volume[i] / vm) if vm > 0 and volume[i] > 0 else 0.0
    return np.array([lr, r5, r20, rv20, relvol], dtype=np.float64)


class ObservationFeed:
    """Reads bars **at or before** a cutoff. It has no forward accessor.

    ``max_staleness_s`` is compared against the wall of simulated market time
    the caller passes as ``as_of_ts``; with ``as_of_ts=None`` the cutoff bar is
    by definition current and no staleness check applies.
    """

    version = VERSION

    def __init__(self, series: dict[str, Series], *,
                 max_staleness_s: int | None = None):
        self.series = dict(series)
        self.max_staleness_s = max_staleness_s
        self._cache: dict[str, tuple[np.ndarray, np.ndarray]] = {
            s: (v.close, v.volume) for s, v in self.series.items()}

    def symbols(self) -> tuple[str, ...]:
        return tuple(sorted(self.series))

    def __len__(self) -> int:
        return len(self.series)

    def bars(self, symbol: str) -> int:
        return len(self.series[symbol])

    def cutoff_ts(self, symbol: str, i: int) -> int:
        return self.series[symbol][i].ts

    def observe(self, symbol: str, i: int, *, stable_id: int = -1,
                as_of_ts: int | None = None) -> MarketObservation:
        """Encode-ready observation of ``symbol`` as known at bar ``i``."""
        s = self.series[symbol]
        if i < 0 or i >= len(s):
            raise IndexError(f"{symbol}: bar {i} outside 0..{len(s) - 1}")
        bar = s[i]
        blank = dict(symbol=symbol, stable_id=stable_id, bar_index=i,
                     cutoff_ts=bar.ts, close=bar.close)

        if i + 1 < MIN_HISTORY_BARS:
            return MarketObservation(
                status=ObservationStatus.INSUFFICIENT_HISTORY,
                detail=f"{i + 1} bars available, {MIN_HISTORY_BARS} required",
                **blank)

        lo = i - MIN_HISTORY_BARS + 1
        win = s.bars[lo:i + 1]
        if any(b.is_nan for b in win):
            k = sum(b.is_nan for b in win)
            return MarketObservation(status=ObservationStatus.GAP,
                                     detail=f"{k} NaN bar(s) in the window",
                                     **blank)
        gaps = [(b.ts - a.ts) for a, b in zip(win, win[1:])]
        if any(g > 1.5 * s.interval_s for g in gaps):
            return MarketObservation(
                status=ObservationStatus.GAP,
                detail=f"timestamp gap {max(gaps)}s > 1.5 x {s.interval_s}s",
                **blank)

        if (self.max_staleness_s is not None and as_of_ts is not None
                and as_of_ts - bar.ts > self.max_staleness_s):
            return MarketObservation(
                status=ObservationStatus.STALE,
                detail=f"cutoff bar is {as_of_ts - bar.ts}s old, tolerance "
                       f"{self.max_staleness_s}s",
                **blank)

        close, volume = self._cache[symbol]
        raw = _raw_features(close, volume, i)
        hist = np.stack([_raw_features(close, volume, j)
                         for j in range(i - Z_WINDOW + 1, i + 1)])
        mu = hist.mean(axis=0)
        sd = hist.std(axis=0, ddof=1)
        z = np.where(sd > Z_MIN_SD, (raw - mu) / np.where(sd > Z_MIN_SD, sd, 1.0), 0.0)
        u = np.tanh(z / Z_SCALE)
        return MarketObservation(status=ObservationStatus.OK, raw=raw,
                                 normalized=u, z=z, **blank)


class ExecutionFeed:
    """Reads bars **after** a cutoff. The only forward-looking accessor.

    Kept as a separate class, with a separate name, so that "did anything
    downstream of the encoder see a future bar?" is answerable by grepping for
    this one type. Only ``flytrade/execution.py`` constructs it.
    """

    version = VERSION

    def __init__(self, series: dict[str, Series]):
        self.series = dict(series)

    def bar(self, symbol: str, i: int) -> Bar:
        return self.series[symbol][i]

    def n_bars(self, symbol: str) -> int:
        return len(self.series[symbol])


# ---------------------------------------------------------------- universe

class Universe:
    """Symbol registry handing out position-independent integer ids.

    Fable addendum 5: the per-candidate RNG seed is derived from the *stable
    id*, which is assigned once at registration and never from the symbol
    string, its spelling or its position in a candidate list. Renaming a
    symbol therefore cannot change any number the brain sees.
    """

    def __init__(self, symbols=()):
        self._ids: dict[str, int] = {}
        for s in symbols:
            self.register(s)

    def register(self, symbol: str) -> int:
        if symbol in self._ids:
            return self._ids[symbol]
        self._ids[symbol] = len(self._ids)
        return self._ids[symbol]

    def stable_id(self, symbol: str) -> int:
        return self._ids[symbol]

    def symbol(self, stable_id: int) -> str:
        for s, i in self._ids.items():
            if i == stable_id:
                return s
        raise KeyError(stable_id)

    def rename(self, old: str, new: str) -> None:
        """Change a symbol's spelling, keeping its stable id."""
        if new in self._ids:
            raise ValueError(f"{new} is already registered")
        self._ids[new] = self._ids.pop(old)

    def __len__(self) -> int:
        return len(self._ids)

    def __contains__(self, symbol: str) -> bool:
        return symbol in self._ids

    def items(self):
        return tuple(sorted(self._ids.items(), key=lambda kv: kv[1]))
