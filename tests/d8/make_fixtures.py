"""
Vendor-shaped fixtures for the D8 suite.

    .venv/bin/python tests/d8/make_fixtures.py <dir>

**No downloaded market data ever enters a test.** These files are generated
here from a declared seed, in the shape the Kibot format reference documents:
headerless, comma-delimited, ``MM/DD/YYYY``, seven fields, one row per minute,
America/New_York wall time.

Two files, and the pair is the point:

===========  ==================================================================
``A.txt``    four complete 390-minute sessions, no gaps
``F.txt``    **byte-identical to A.txt up to and including** the cut minute
             :data:`CUT`, and every later bar multiplied by :data:`PERTURB` —
             price and volume alike
===========  ==================================================================

So "an observation at minute m <= CUT cannot depend on a bar after m" becomes a
comparison of two real series rather than a promise about call order. Every file
is a pure function of :data:`SEED` and the constants below, so two runs produce
byte-identical files.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np

SEED = 20260911

#: four consecutive weekday sessions
DAYS = (date(2026, 6, 15), date(2026, 6, 16), date(2026, 6, 17),
        date(2026, 6, 18))

MINUTES = 390
HEADER_MINUTE = 9 * 60 + 30

#: the cut: (day index, minute of session). Deep enough inside the third
#: session that the 20-bar lookback and the 60-row causal z-window are warm,
#: and far enough from its end that there are many later bars to perturb.
CUT = (2, 200)

#: the constant every bar after the cut is multiplied by in ``F.txt``
PERTURB = 1.37


def _hhmm(minute_of_day: int) -> str:
    return f"{minute_of_day // 60:02d}:{minute_of_day % 60:02d}"


def _path(day: date, n: int, seed: int, start: float):
    rng = np.random.default_rng(seed + day.toordinal())
    r = rng.normal(0.0, 0.0006, size=n)
    close = start * np.exp(np.cumsum(r))
    prev = np.concatenate(([start], close[:-1]))
    spread = np.abs(r) + 0.0004
    high = np.maximum(prev, close) * (1.0 + spread * rng.uniform(0.2, 1.0, n))
    low = np.minimum(prev, close) * (1.0 - spread * rng.uniform(0.2, 1.0, n))
    vol = np.round(1000.0 * np.exp(rng.normal(0.0, 0.4, n)) + 100.0)
    return prev, high, low, close, vol


def rows_for(*, perturb_after_cut: bool, start: float = 100.0):
    """Rows as ``(date, minute_of_day, o, h, l, c, v)``."""
    out = []
    price = start
    cut_day, cut_minute = CUT
    for di, day in enumerate(DAYS):
        o, h, lo, c, v = _path(day, MINUTES, SEED, price)
        price = float(c[-1])
        for m in range(MINUTES):
            after = perturb_after_cut and (
                di > cut_day or (di == cut_day and m > cut_minute))
            k = PERTURB if after else 1.0
            out.append((day, HEADER_MINUTE + m, o[m] * k, h[m] * k,
                        lo[m] * k, c[m] * k, v[m] * k))
    return out


def render(rows) -> str:
    return "\n".join(
        f"{day.strftime('%m/%d/%Y')},{_hhmm(mod)},"
        f"{o:.4f},{h:.4f},{lo:.4f},{c:.4f},{v:.0f}"
        for day, mod, o, h, lo, c, v in rows) + "\n"


def write_all(directory) -> dict[str, Path]:
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    out = {"A": d / "A.txt", "F": d / "F.txt"}
    out["A"].write_text(render(rows_for(perturb_after_cut=False)))
    out["F"].write_text(render(rows_for(perturb_after_cut=True)))
    return out


def main(argv) -> int:
    target = Path(argv[1]) if len(argv) > 1 else Path("build/fixtures-d8")
    for name, p in sorted(write_all(target).items()):
        print(f"{name}  {p}  {len(p.read_text().splitlines()):>5d} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
