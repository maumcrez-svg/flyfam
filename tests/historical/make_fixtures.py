"""
Vendor-shaped fixtures for the historical suite. Fable addendum 10.

    .venv/bin/python tests/historical/make_fixtures.py <dir>

**No downloaded market data ever enters a test.** These files are generated
here, from a declared seed, in the shape the Kibot format reference documents:
headerless, comma-delimited, ``MM/DD/YYYY``, seven fields, one row per minute,
America/New_York wall time, minutes without a trade simply absent.

They are deliberately small — three 120-minute sessions is enough to cross the
60-row causal-normalisation window twice — and they carry, on purpose, every
shape the importer has to have an opinion about:

======================  ====================================================
``A.txt``               the well-behaved instrument: three sessions, one
                        4-minute gap, one 10-minute gap that outlives the
                        staleness tolerance, and a session whose last
                        available bar is well before 16:00
``B.txt``               a second instrument on the same sessions, with its
                        gaps in *different* minutes, so a round can have one
                        usable and one ``DATA_GAP`` candidate
``seconds.txt``         the same shape with ``HH:MM:SS`` times
``extended.txt``        pre-market and after-hours rows that must be
                        excluded and counted, never kept
``exponent.txt``        a price in exponent form (``1E-06``)
``dup.txt``             a duplicate timestamp
``unordered.txt``       a timestamp that goes backwards
``ohlc.txt``            ``high`` below ``close``
``sixfields.txt``       six fields instead of seven
``nonpositive.txt``     a zero price
======================  ====================================================

Every file is a pure function of :data:`SEED` and the constants below, so two
runs of this script produce byte-identical files.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np

SEED = 20260911

#: the three fixture sessions: a Monday, a Tuesday, a Wednesday
DAYS = (date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5))
#: minutes of each session that the fixture covers at all (09:30 .. 11:29)
MINUTES = 120

#: gaps, per instrument, as ``{day index: (first minute, count)}``. A is the
#: instrument the execution tests use; B's gaps deliberately do not line up.
GAPS_A = {1: (100, 4), 2: (60, 10)}
GAPS_B = {0: (30, 7), 1: (45, 3), 2: (80, 12)}

HEADER_MINUTE = 9 * 60 + 30


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


def rows_for(symbol_seed: int, gaps: dict, *, start: float = 100.0,
             days=DAYS, minutes: int = MINUTES, seconds: bool = False):
    """The rows of one instrument, as ``(date, minute_of_day, o,h,l,c,v)``."""
    out = []
    price = start
    for di, day in enumerate(days):
        o, h, lo, c, v = _path(day, minutes, symbol_seed, price)
        hole = gaps.get(di)
        for m in range(minutes):
            if hole and hole[0] <= m < hole[0] + hole[1]:
                continue                      # the vendor omits the minute
            out.append((day, HEADER_MINUTE + m, o[m], h[m], lo[m], c[m], v[m]))
        price = float(c[-1])
    return out


def render(rows, *, seconds: bool = False) -> str:
    lines = []
    for day, mod, o, h, lo, c, v in rows:
        t = _hhmm(mod) + (":00" if seconds else "")
        lines.append(f"{day.strftime('%m/%d/%Y')},{t},"
                     f"{o:.4f},{h:.4f},{lo:.4f},{c:.4f},{v:.0f}")
    return "\n".join(lines) + "\n"


def write_all(directory) -> dict[str, Path]:
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}

    a = rows_for(SEED, GAPS_A, start=100.0)
    b = rows_for(SEED + 1, GAPS_B, start=250.0)
    out["A"] = d / "A.txt"
    out["A"].write_text(render(a))
    out["B"] = d / "B.txt"
    out["B"].write_text(render(b))

    out["seconds"] = d / "seconds.txt"
    out["seconds"].write_text(render(a[:200], seconds=True))

    # pre-market 08:00 and after-hours 16:30 rows around one clean session
    one = [r for r in a if r[0] == DAYS[0]]
    ext = ([(DAYS[0], 8 * 60, 99.0, 99.5, 98.5, 99.2, 500.0),
            (DAYS[0], 9 * 60, 99.2, 99.6, 99.0, 99.4, 400.0)]
           + one
           + [(DAYS[0], 16 * 60 + 30, 100.0, 100.2, 99.9, 100.1, 300.0),
              (DAYS[0], 18 * 60, 100.1, 100.3, 100.0, 100.2, 200.0)])
    out["extended"] = d / "extended.txt"
    out["extended"].write_text(render(ext))

    # exponent-form prices, which a fixed-point parser mis-reads
    out["exponent"] = d / "exponent.txt"
    out["exponent"].write_text(
        f"{DAYS[0].strftime('%m/%d/%Y')},09:30,1E-06,2E-06,5E-07,1.5E-06,100\n"
        f"{DAYS[0].strftime('%m/%d/%Y')},09:31,1.5E-06,2E-06,1E-06,1.8E-06,120\n")

    bad = {
        "dup": render(one[:10] + [one[9]] + one[10:20]),
        # 09:30..09:39, then 09:45..09:49, then 09:40..09:44: the last block
        # goes backwards without repeating any timestamp, so it is an
        # ordering violation and not a duplicate
        "unordered": render(one[:10] + one[15:20] + one[10:15]),
        "ohlc": render(one[:5]).replace(
            render(one[4:5]).strip(),
            f"{one[4][0].strftime('%m/%d/%Y')},{_hhmm(one[4][1])},"
            f"{one[4][2]:.4f},{min(one[4][5], one[4][4]) - 1:.4f},"
            f"{one[4][4]:.4f},{one[4][5]:.4f},{one[4][6]:.0f}"),
        "sixfields": "\n".join(
            ",".join(line.split(",")[:6]) for line in
            render(one[:5]).strip().splitlines()) + "\n",
        "nonpositive": render(one[:4]) +
        f"{DAYS[0].strftime('%m/%d/%Y')},09:34,0,0.1,0,0.05,100\n",
    }
    for name, text in bad.items():
        out[name] = d / f"{name}.txt"
        out[name].write_text(text)
    return out


def main(argv) -> int:
    target = Path(argv[1]) if len(argv) > 1 else Path("build/fixtures")
    paths = write_all(target)
    for name, p in sorted(paths.items()):
        print(f"{name:12s} {p}  {len(p.read_text().splitlines()):>4d} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
