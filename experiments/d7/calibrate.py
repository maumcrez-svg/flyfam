#!/usr/bin/env python
"""
The D7 horizon calibration — amendment §3 and §4, on WARMUP prices only.

    .venv/bin/python experiments/d7/calibrate.py

Reads the committed `config.json`, the already-hashed IBM file, and nothing
else. Writes `registered-horizon-artifact`: the qualifying-session table, the measured
round-trip cost C, the full A(H) table per session and in aggregate, and the
selected H* — or the bounded result `NO_HORIZON_MEETS_RULE` /
`INSUFFICIENT_WARMUP`, which are outcomes of this wave and not failures to
route around.

Three guards, none of them a promise:

* the series handed to the calibration is a :class:`WarmupOnly` view that
  **raises** if any code asks it for a day outside the WARMUP partition, so
  "calibration never reads a LEARNING or FROZEN price" is enforced rather than
  asserted;
* the origin set is built once per session for the **maximum** candidate
  horizon and reused for every H, so A(H) differences are horizon differences;
* C is measured by a flat-price round trip through the real
  :class:`flytrade.historical.HistoricalExecution` at the configured notional,
  never inferred from rounded report text.
"""
from __future__ import annotations

import hashlib
import json
import platform
import sys
import time
from datetime import date as _date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "upstream"))

from flytrade import execution as X        # noqa: E402
from flytrade import historical as H       # noqa: E402
from flytrade import horizon as HZ         # noqa: E402

MARKET = ROOT / "data" / "market"
CONFIG = HERE / "config.json"
ARTIFACT = HERE / "registered-horizon-artifact"


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class OutsideWarmup(RuntimeError):
    """Calibration asked for a session outside the WARMUP partition."""


class WarmupOnly:
    """A price series that exists only on the WARMUP sessions it was given.

    Amendment §2: "No observations from 2026-08-03 through 2026-09-04 may
    enter ... H calibration", and §4: "All prices used in these calibration
    returns must lie inside WARMUP and the same session." This wrapper is how
    that is enforced: every price lookup goes through it, and a lookup for any
    other day raises instead of returning a number.
    """

    def __init__(self, series, days):
        self._s = series
        self.days = frozenset(days)
        self.touched: set = set()

    def _check(self, day):
        if day not in self.days:
            raise OutsideWarmup(
                f"the calibration asked for {day}, which is not one of the "
                f"{len(self.days)} qualifying WARMUP sessions")
        self.touched.add(day)

    def next_available(self, day, m):
        self._check(day)
        return self._s.next_available(day, m)

    def bar(self, day, m):
        self._check(day)
        return self._s.bar(day, m)

    def status(self, day, m):
        self._check(day)
        return self._s.status(day, m)


# ------------------------------------------------------------- the cost C

def flat_series(symbol: str, day: _date, price: float, minutes: int = 390):
    """A one-session series at a single, constant price. No vendor data."""
    ts = H.session_minutes(day)
    rows = [H.VendorRow(bar_start=int(t), open=price, high=price, low=price,
                        close=price, volume=1000.0) for t in ts[:minutes]]
    report = H.ParseReport(
        path="<flat>", symbol=symbol, sha256="", bytes=0, lines=len(rows),
        rows=len(rows), time_format="HH:MM", first_bar=int(ts[0]),
        last_bar=int(ts[minutes - 1]), sessions=1, excluded_extended_hours=0,
        duplicates=0, blank_lines=0, exponent_prices=0)
    return H.HistoricalSeries(symbol, rows, report)


def measure_cost_bps(cfg, *, price: float = 100.0, day=_date(2026, 1, 2),
                     horizon: int = 8) -> dict:
    """C, measured: one flat-price round trip through the real policy.

    Fable addendum 2. The configured fee and slippage are both charged **per
    execution**, so the number that matters to the §4 rule is the round trip.
    Both the per-leg and the round-trip figure are recorded here and the
    measured figure — not the arithmetic in the config comment — governs.
    """
    xcfg = cfg["execution"]
    series = {"FLAT": flat_series("FLAT", day, price)}
    pol = H.HistoricalExecution(
        series, notional=xcfg["notional"], fee_bps=xcfg["fee_bps"],
        slippage_bps=xcfg["slippage_bps"],
        delay_minutes=xcfg["delay_minutes"], horizon_minutes=horizon,
        initial_cash=xcfg["initial_cash"])
    pol.start_session(day)
    pos = pol.open_long(episode_id=1, symbol="FLAT", stable_id=0,
                        decision_bar=10, day=day)
    if isinstance(pos, X.Rejection):
        raise SystemExit(f"the flat-price round trip was rejected: {pos}")
    out = pol.close(decision_bar=10 + 1 + horizon,
                    reason=X.CloseReason.POLICY_CLOSE, day=day)
    if isinstance(out, X.Rejection):
        raise SystemExit(f"the flat-price round trip did not close: {out}")
    notional = float(xcfg["notional"])
    round_trip_bps = -out.net_pnl / notional / HZ.BPS
    return {
        "method": "one flat-price round trip through "
                  "flytrade.historical.HistoricalExecution",
        "flat_price": price, "notional": notional,
        "fee_bps_per_execution": xcfg["fee_bps"],
        "slippage_bps_per_execution": xcfg["slippage_bps"],
        "per_leg_bps": xcfg["fee_bps"] + xcfg["slippage_bps"],
        "entry_reference_price": out.entry.reference_price,
        "entry_fill_price": out.entry.fill_price,
        "exit_reference_price": out.exit.reference_price,
        "exit_fill_price": out.exit.fill_price,
        "gross_reference_pnl": out.gross_reference_pnl,
        "fees": out.fees, "slippage": out.slippage, "net_pnl": out.net_pnl,
        "round_trip_cost_bps_measured": round_trip_bps,
        "note": "the measured figure governs; fee and slippage are charged "
                "per execution, so a completed round trip pays both twice",
    }


# ------------------------------------------------------- qualifying sessions

def qualifying(series, first: _date, last: _date, cfg) -> tuple[list, list]:
    """(qualifying sessions, the full table) under the §3 data-quality rule."""
    q = cfg["warmup_qualification"]
    min_frac = float(q["min_fraction_of_scheduled_bars"])
    min_org = int(q["min_common_origins"])
    hs = tuple(cfg["horizon_rule"]["H_SET"])
    delay = int(cfg["execution"]["delay_minutes"])
    rows, good = [], []
    for day in series.days:
        if not (first <= day <= last):
            continue
        s = series.sessions[day]
        frac = s.n_present / H.SESSION_MINUTES
        origins = HZ.common_origins(series, day, hs, delay=delay)
        ok = frac >= min_frac and len(origins) >= min_org
        rows.append({"session": str(day), "bars": s.n_present,
                     "missing": s.missing, "fraction": round(frac, 6),
                     "common_origins": len(origins),
                     "first_origin": origins[0] if origins else None,
                     "last_origin": origins[-1] if origins else None,
                     "qualifies": ok,
                     "reason": "" if ok else (
                         f"{frac:.4f} of scheduled bars" if frac < min_frac
                         else f"{len(origins)} common origins")})
        if ok:
            good.append(day)
    return good, rows


def main(argv) -> int:
    t0 = time.time()
    cfg = json.loads(CONFIG.read_text())
    spec = cfg["instruments"][0]
    path = MARKET / spec["file"]
    if not path.exists():
        raise SystemExit(f"{path} is absent; see data/MANIFEST.md")
    got = sha256_file(path)
    if got != spec["sha256"]:
        raise SystemExit(
            f"{spec['symbol']}: sha256 {got[:16]} != the manifested "
            f"{spec['sha256'][:16]}: the calibration is refused rather than "
            f"silently reading a substituted dataset")
    series = H.load_series(path, spec["symbol"])
    if series.report.rows != spec["rows"]:
        raise SystemExit(f"{series.report.rows} rows, {spec['rows']} registered")

    w = cfg["partitions"]["WARMUP"]
    first, last = _date.fromisoformat(w["first"]), _date.fromisoformat(w["last"])
    good, table = qualifying(series, first, last, cfg)

    cost = measure_cost_bps(cfg)
    C = float(cost["round_trip_cost_bps_measured"])
    rule = cfg["horizon_rule"]
    art = {
        "artifact": "flytrade-d7-horizon-1",
        "written_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "protocol": "experiments/d7/PROTOCOL.md",
        "config_sha256": hashlib.sha256(CONFIG.read_bytes()).hexdigest(),
        "instrument": spec["symbol"],
        "data_sha256": got,
        "partition": "WARMUP",
        "window": {"first": str(first), "last": str(last)},
        "python": platform.python_version(),
        "cost": cost,
        "warmup_sessions_examined": len(table),
        "warmup_qualification": cfg["warmup_qualification"],
        "per_session_qualification": table,
        "qualifying_sessions": [str(d) for d in good],
        "n_qualifying": len(good),
    }

    need = int(cfg["warmup_qualification"]["min_qualifying_sessions"])
    if len(good) < need:
        art["result"] = "INSUFFICIENT_WARMUP"
        art["selected_horizon_minutes"] = None
        art["detail"] = (f"{len(good)} qualifying sessions, {need} required; "
                         f"dates are not extended, criteria are not relaxed "
                         f"and no instrument is substituted")
        ARTIFACT.write_text(json.dumps(art, indent=1))
        print(f"INSUFFICIENT_WARMUP: {len(good)} of {need}")
        return 2

    view = WarmupOnly(series, good)
    cal = HZ.calibrate(view, good, horizons=tuple(rule["H_SET"]), cost_bps=C,
                       multiple=float(rule["multiple_of_cost"]),
                       delay=int(cfg["execution"]["delay_minutes"]),
                       min_origins=int(
                           cfg["warmup_qualification"]["min_common_origins"]))
    art["calibration"] = cal
    art["sessions_touched"] = sorted(str(d) for d in view.touched)
    art["A_bps"] = cal["A_bps"]
    art["threshold_bps"] = cal["threshold_bps"]
    art["result"] = cal["result"]
    art["selected_horizon_minutes"] = cal["selected_horizon_minutes"]
    art["elapsed_s"] = round(time.time() - t0, 2)
    ARTIFACT.write_text(json.dumps(art, indent=1))

    print(f"C measured  = {C:.6f} bps round trip "
          f"({cost['per_leg_bps']:.1f} bps per leg)")
    print(f"threshold   = {cal['multiple']} x C = {cal['threshold_bps']:.4f} bps")
    print(f"sessions    = {len(good)} qualifying of {len(table)} examined")
    print("  H   A(H) bps   >= 2C")
    for h in rule["H_SET"]:
        a = cal["A_bps"][str(h)]
        print(f"{h:>4}  {a:10.4f}   {'yes' if a >= cal['threshold_bps'] else 'no'}")
    print(f"result      = {cal['result']}  H* = "
          f"{cal['selected_horizon_minutes']}")
    return 0 if cal["result"] == "OK" else 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
