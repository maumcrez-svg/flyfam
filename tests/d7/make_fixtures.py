"""
Vendor-shaped fixtures for the D7 suite. Amendment D7 §10.

    .venv/bin/python tests/d7/make_fixtures.py <dir>

**No downloaded market data ever enters a test.** These files are generated
here, from a declared seed, in the shape the Kibot format reference documents:
headerless, comma-delimited, ``MM/DD/YYYY``, seven fields, one row per minute,
America/New_York wall time, minutes without a trade simply absent.

They differ from ``tests/historical/make_fixtures.py`` in one way that the D7
wave needs: the sessions are **full 390-minute sessions**, because the
candidate horizons run to 120 market minutes and a 120-minute fixture session
would have no eligible origin at all.

===================  =========================================================
``W.txt``            six complete sessions with **no** gaps — the WARMUP-shaped
                     instrument the calibration is exercised on
``P.txt``            the same six sessions with the **later three** sessions'
                     prices multiplied by a constant: the §10 guard fixture,
                     identical to ``W.txt`` inside the WARMUP dates and
                     different everywhere else
``G.txt``            the same six sessions with gaps, including one that
                     removes the exact minute a horizon exit lands on and one
                     that removes an entry minute
===================  =========================================================

Every file is a pure function of :data:`SEED` and the constants below, so two
runs of this script produce byte-identical files.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np

SEED = 20260911

#: six consecutive weekday sessions
DAYS = (date(2026, 6, 15), date(2026, 6, 16), date(2026, 6, 17),
        date(2026, 6, 18), date(2026, 6, 22), date(2026, 6, 23))

#: the first three are the fixture's "WARMUP"; the last three stand for
#: LEARNING and FROZEN and must never be read by a calibration
WARMUP_DAYS = DAYS[:3]
LATER_DAYS = DAYS[3:]

#: a complete regular session
MINUTES = 390
HEADER_MINUTE = 9 * 60 + 30

#: gaps in ``G.txt``, as ``{day index: [(first minute, count), ...]}``
GAPS_G = {
    1: [(200, 1), (331, 1)],          # a lone missing minute, and 15:31
    2: [(150, 6)],                    # a six-minute hole
}

#: the constant the later sessions of ``P.txt`` are multiplied by
PERTURB = 1.37


def _hhmm(minute_of_day: int) -> str:
    return f"{minute_of_day // 60:02d}:{minute_of_day % 60:02d}"


def _path(day: date, n: int, seed: int, start: float):
    """A deterministic minute path: close, and an OHLC that brackets it."""
    rng = np.random.default_rng(seed + day.toordinal())
    r = rng.normal(0.0, 0.0006, size=n)
    close = start * np.exp(np.cumsum(r))
    prev = np.concatenate(([start], close[:-1]))
    spread = np.abs(r) + 0.0004
    high = np.maximum(prev, close) * (1.0 + spread * rng.uniform(0.2, 1.0, n))
    low = np.minimum(prev, close) * (1.0 - spread * rng.uniform(0.2, 1.0, n))
    vol = np.round(1000.0 * np.exp(rng.normal(0.0, 0.4, n)) + 100.0)
    return prev, high, low, close, vol


def rows_for(symbol_seed: int, gaps: dict | None = None, *,
             start: float = 100.0, days=DAYS, minutes: int = MINUTES,
             scale_later: float = 1.0):
    """The rows of one instrument, as ``(date, minute_of_day, o,h,l,c,v)``."""
    out = []
    price = start
    for di, day in enumerate(days):
        o, h, lo, c, v = _path(day, minutes, symbol_seed, price)
        price = float(c[-1])
        k = scale_later if day in LATER_DAYS else 1.0
        holes = (gaps or {}).get(di, [])
        for m in range(minutes):
            if any(a <= m < a + n for a, n in holes):
                continue                      # the vendor omits the minute
            out.append((day, HEADER_MINUTE + m, o[m] * k, h[m] * k,
                        lo[m] * k, c[m] * k, v[m]))
    return out


def render(rows) -> str:
    lines = []
    for day, mod, o, h, lo, c, v in rows:
        lines.append(f"{day.strftime('%m/%d/%Y')},{_hhmm(mod)},"
                     f"{o:.4f},{h:.4f},{lo:.4f},{c:.4f},{v:.0f}")
    return "\n".join(lines) + "\n"


def write_all(directory) -> dict[str, Path]:
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}
    out["W"] = d / "W.txt"
    out["W"].write_text(render(rows_for(SEED, start=100.0)))
    out["P"] = d / "P.txt"
    out["P"].write_text(render(rows_for(SEED, start=100.0,
                                        scale_later=PERTURB)))
    out["G"] = d / "G.txt"
    out["G"].write_text(render(rows_for(SEED, GAPS_G, start=100.0)))
    return out


def main(argv) -> int:
    target = Path(argv[1]) if len(argv) > 1 else Path("build/fixtures-d7")
    paths = write_all(target)
    for name, p in sorted(paths.items()):
        print(f"{name:12s} {p}  {len(p.read_text().splitlines()):>5d} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
