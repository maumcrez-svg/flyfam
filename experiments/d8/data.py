"""
The two D8 grids, the two stored representations, and their verification.

`experiments/d8/PLAN.md` §3, §4 and §5, and Fable addenda 1, 2 and 3. Everything
downstream — the feature/PC1 table, the four joint models, the report — asks
this module for its rows, so there is exactly one definition of "a fitting row"
and one definition of "an evaluation row" in the wave.

Stored inputs are **primary**. Every `DECISION` event of `d7-001` already
carries both representations:

* ``observation.normalized`` — the five causal features ``r1, r5, r20, rv20,
  relvol``, z-scored over a trailing 60-bar window ending at the cutoff and
  squashed by ``tanh(z / 2)``; exactly the vector
  ``MarketToSensoryEncoder.encode`` receives;
* ``stimulus.rates_hz`` — the deterministic per-ORN drive in Hz for the ten
  glomeruli, computed **before** Bernoulli spike sampling, one vector per
  presentation and constant over the 20 ms window. The encoder emits no
  sequence, so the amendment's ordered-sequence clause is vacuous here, and the
  eight replicates of a batch share one stimulus: one row per (session, minute),
  never eight.

Reconstruction from the price file is the **verification**, not the source:
:func:`verify` rebuilds both representations with the existing
``flytrade.historical`` / ``flytrade.encoder`` code, which sees only bars of the
same session at minutes <= m — ``bar_end <= market_ts`` — and asserts agreement
within 1e-12 on every row of both grids. A non-zero mismatch count stops the
wave before any model is fitted.

This module imports ``flytrade.historical`` (for the price series, the session
calendar and the causal observation) and ``flytrade.horizon`` (for the labels).
It does **not** import ``flytrade.execution``, ``flytrade.runner``,
``flytrade.mushroom``, ``flytrade.state`` or ``flytrade.readout``: it cannot
place an order, move a weight or write an event. ``tests/d8/test_isolation.py``
asserts that, and records the transitive imports those two modules carry.
"""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass, field
from datetime import date as _date
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (str(ROOT), str(ROOT / "upstream")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from flytrade import encoder as E             # noqa: E402
from flytrade import historical as H          # noqa: E402
from flytrade import horizon as HZ            # noqa: E402
from flytrade import market as MK             # noqa: E402
from flytrade import populations as P         # noqa: E402

CONFIG = json.loads((HERE / "config.json").read_text())
D7 = ROOT / "experiments" / "d7"
RUNS = D7 / "runs" / "d7-001"
ANNOTATIONS = ROOT / "data" / "malecns-v1.0" / "annotations.npz"

#: PLAN §4, fixed order. Asserted against the frozen encoder in :func:`encoder`.
FEATURES: tuple[str, ...] = tuple(CONFIG["representations"]["X_FEATURES"]["order"])
GLOMERULI: tuple[str, ...] = tuple(CONFIG["representations"]["X_SENSORY"]["order"])

#: PLAN §5. The stored ``rates_hz`` are rounded by ``Stimulus.as_dict``.
STORED_RATE_DECIMALS = 4
TOLERANCE = float(CONFIG["verification"]["tolerance"])


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def artifact_hashes() -> dict:
    """The eleven registered artifacts, hashed now."""
    return {k: sha256_file(ROOT / k) for k in CONFIG["artifacts"]}


def check_artifacts() -> dict:
    """Every registered artifact must still carry its pre-registered hash."""
    got = artifact_hashes()
    bad = {k: {"registered": v, "found": got[k]}
           for k, v in CONFIG["artifacts"].items() if got[k] != v}
    if bad:
        raise SystemExit(f"registered artifacts changed: {json.dumps(bad, indent=1)}")
    return got


# --------------------------------------------------------------- the rows

@dataclass(frozen=True)
class Rows:
    """One grid, joined to its stored representations."""

    name: str
    session: np.ndarray              # (n,) str
    minute: np.ndarray               # (n,) int
    market_ts: np.ndarray            # (n,) int
    exit_ts: np.ndarray              # (n,) int
    G: np.ndarray                    # (n,) float
    Y: np.ndarray                    # (n,) int
    X_FEATURES: np.ndarray           # (n, 5)
    X_SENSORY: np.ndarray            # (n, 10)
    meta: dict = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.Y)

    def x(self, rep: str) -> np.ndarray:
        return self.X_FEATURES if rep == "X_FEATURES" else self.X_SENSORY

    def sessions(self) -> list[str]:
        return sorted(set(self.session.tolist()))


CONFIG_D7 = json.loads((D7 / "config.json").read_text())


def series():
    """The manifested IBM price file, through the ordinary loader."""
    inst = CONFIG_D7["instruments"][0]
    path = ROOT / "data" / "market" / inst["file"]
    got = sha256_file(path)
    if got != inst["sha256"]:
        raise SystemExit("the price file is not the manifested one")
    return H.load_series(path, inst["symbol"])


def encoder() -> E.MarketToSensoryEncoder:
    """The frozen encoder, rebuilt from the same annotations the run used."""
    enc = E.MarketToSensoryEncoder(P.Annotations.load(ANNOTATIONS))
    if tuple(enc.features) != FEATURES:
        raise SystemExit(f"feature order moved: {enc.features} != {FEATURES}")
    if tuple(enc.glomeruli) != GLOMERULI:
        raise SystemExit(f"channel order moved: {enc.glomeruli} != {GLOMERULI}")
    return enc


# ------------------------------------------------------- reading the logs

def stored_decisions(log_path: Path, partition: str) -> tuple[dict, dict]:
    """``{(session, minute): DECISION event}`` inside one partition's span.

    The span is the index range between that partition's two ``PARTITION``
    boundary events, exactly as `experiments/d7/evaluate.py` slices FROZEN. The
    log is opened read-only in text mode and no field is derived or re-decoded.
    """
    rows, counts = {}, {}
    inside = False

    def bump(k):
        counts[k] = counts.get(k, 0) + 1

    with open(log_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            k = e.get("kind")
            if k == "PARTITION" and e.get("partition") == partition:
                inside = e.get("boundary") == "start"
                continue
            if not inside or k != "DECISION":
                continue
            bump("DECISION")
            key = (str(H.session_date(int(e["market_ts"]) - H.BAR_SECONDS)),
                   int(e["bar_index"]))
            if key in rows:
                bump("DUPLICATE_DECISION_AT_A_MINUTE")
                continue
            rows[key] = e
    return rows, counts


def stored_vectors(event: dict) -> tuple[np.ndarray, np.ndarray]:
    """(X_FEATURES row, X_SENSORY row) from one stored ``DECISION`` event."""
    norm = event["observation"]["normalized"]
    rates = event["stimulus"]["rates_hz"]
    xf = np.array([float(norm[f]) for f in FEATURES], dtype=np.float64)
    xs = np.array([float(rates[g]) for g in GLOMERULI], dtype=np.float64)
    return xf, xs


# ------------------------------------------------------------- the grids

def fitting_grid(ser, first: _date, last: _date, hstar: int, *,
                 delay: int) -> list[tuple[_date, int]]:
    """`experiments/d7/PROTOCOL.md` §6's grid rule, on the LEARNING sessions.

    Status ``OK`` and the clock rule ``(m + 1) + delay + H <= 390``. The session
    calendar and the price file are the only inputs: the rule never reads a
    position, a trade or an inventory state.
    """
    out = []
    for day in ser.days:
        if not (first <= day <= last):
            continue
        for m in range(H.SESSION_MINUTES):
            if not HZ.eligible(m, hstar, delay=delay):
                break
            if ser.status(day, m).value == "OK":
                out.append((day, m))
    return out


def fitting_rows(ser=None) -> Rows:
    """The fitting grid, its H = 90 labels, and the stored LEARNING inputs."""
    ser = ser if ser is not None else series()
    p = CONFIG["partitions"]["fitting"]
    tgt, grids = CONFIG["target"], CONFIG["grids"]
    hstar, delay = int(grids["H"]), int(grids["delay_minutes"])
    first, last = _date.fromisoformat(p["first"]), _date.fromisoformat(p["last"])
    grid = fitting_grid(ser, first, last, hstar, delay=delay)

    dec, counts = stored_decisions(ROOT / p["log"], "LEARNING")
    keep, drop = [], {"UNAVAILABLE_LABEL": {}, "NO_DECISION_EVENT": 0,
                      "NON_FINITE": 0}
    for day, m in grid:
        h = HZ.hold(ser, day, m, hstar, delay=delay)
        if not h.ok:
            drop["UNAVAILABLE_LABEL"][h.reason] = \
                drop["UNAVAILABLE_LABEL"].get(h.reason, 0) + 1
            continue
        e = dec.get((str(day), m))
        if e is None:
            drop["NO_DECISION_EVENT"] += 1
            continue
        xf, xs = stored_vectors(e)
        if not (np.all(np.isfinite(xf)) and np.all(np.isfinite(xs))):
            drop["NON_FINITE"] += 1
            continue
        g = h.net_return(notional=float(tgt["notional"]),
                         fee_bps=float(tgt["fee_bps"]),
                         slippage_bps=float(tgt["slippage_bps"]))
        keep.append((str(day), m, int(e["market_ts"]), int(h.exit_ts),
                     float(g), int(g > 0.0), xf, xs))

    return Rows(
        name="fitting",
        session=np.array([r[0] for r in keep]),
        minute=np.array([r[1] for r in keep], dtype=np.int64),
        market_ts=np.array([r[2] for r in keep], dtype=np.int64),
        exit_ts=np.array([r[3] for r in keep], dtype=np.int64),
        G=np.array([r[4] for r in keep], dtype=np.float64),
        Y=np.array([r[5] for r in keep], dtype=np.int64),
        X_FEATURES=np.array([r[6] for r in keep], dtype=np.float64).reshape(-1, 5),
        X_SENSORY=np.array([r[7] for r in keep], dtype=np.float64).reshape(-1, 10),
        meta={"grid_points": len(grid), "log_counts": counts,
              "exclusions": drop, "partition": "LEARNING",
              "first": p["first"], "last": p["last"],
              "rule": CONFIG["grids"]["fitting_rule"]})


def evaluation_rows() -> Rows:
    """`withheld-probe-table` as stored, joined to the FROZEN stimulus by (session, minute).

    The stimulus does not depend on the branch. `frozen_reference` supplies it;
    `frozen_trained` is asserted identical on every shared row and the count is
    reported in ``meta["frozen_trained_identical"]``.
    """
    p = CONFIG["partitions"]["evaluation"]
    probes = json.loads((D7 / "withheld-probe-table").read_text())
    ref, ref_counts = stored_decisions(ROOT / p["stimulus_log"], "FROZEN")
    tr, _ = stored_decisions(ROOT / p["stimulus_cross_check_log"], "FROZEN")

    keep = []
    drop = {"NO_DECISION_EVENT": 0, "NON_FINITE": 0}
    identical = {"compared": 0, "identical": 0, "differing": 0}
    for row in probes["rows"]:
        key = (row["session"], int(row["minute"]))
        e = ref.get(key)
        if e is None:
            drop["NO_DECISION_EVENT"] += 1
            continue
        xf, xs = stored_vectors(e)
        et = tr.get(key)
        if et is not None:
            identical["compared"] += 1
            tf, ts = stored_vectors(et)
            same = bool(np.array_equal(tf, xf) and np.array_equal(ts, xs))
            identical["identical" if same else "differing"] += 1
        if not (np.all(np.isfinite(xf)) and np.all(np.isfinite(xs))):
            drop["NON_FINITE"] += 1
            continue
        keep.append((row["session"], int(row["minute"]), int(row["market_ts"]),
                     int(row["exit_ts"]), float(row["G"]), int(row["Y"]),
                     xf, xs))

    return Rows(
        name="evaluation",
        session=np.array([r[0] for r in keep]),
        minute=np.array([r[1] for r in keep], dtype=np.int64),
        market_ts=np.array([r[2] for r in keep], dtype=np.int64),
        exit_ts=np.array([r[3] for r in keep], dtype=np.int64),
        G=np.array([r[4] for r in keep], dtype=np.float64),
        Y=np.array([r[5] for r in keep], dtype=np.int64),
        X_FEATURES=np.array([r[6] for r in keep], dtype=np.float64).reshape(-1, 5),
        X_SENSORY=np.array([r[7] for r in keep], dtype=np.float64).reshape(-1, 10),
        meta={"probes_n": int(probes["n"]), "log_counts": ref_counts,
              "exclusions": drop, "frozen_trained_identical": identical,
              "partition": "FROZEN", "first": p["first"], "last": p["last"],
              "rule": CONFIG["grids"]["evaluation_rule"],
              "probe_scores": {row["session"] + "|" + str(row["minute"]):
                               (row["v_trained"], row["v_reference"])
                               for row in probes["rows"]}})


# ---------------------------------------------- stored vs reconstructed

def reconstruct(ser, enc, session: str, minute: int) -> tuple[np.ndarray, np.ndarray]:
    """Rebuild both representations for one minute, from the price file only.

    ``HistoricalSeries.observe`` computes its raw features from bars at minutes
    <= ``minute`` of this session and z-scores them over the trailing 60 usable
    rows ending at this one, so nothing with ``bar_end > market_ts`` is read.
    """
    day = _date.fromisoformat(session)
    obs = ser.observe(day, int(minute), stable_id=0, bar_index=int(minute))
    if obs.status is not MK.ObservationStatus.OK:
        raise ValueError(f"{session} {minute}: observation is {obs.status.value}")
    st = enc.encode(obs)
    xf = np.asarray(obs.normalized, dtype=np.float64)
    xs = np.array([float(st.rates[g]) for g in GLOMERULI], dtype=np.float64)
    return xf, xs


def verify(rows: Rows, ser, enc) -> dict:
    """Assert stored == reconstructed within 1e-12 on every row of one grid.

    X_FEATURES is compared at full precision. X_SENSORY is compared after the
    same ``round(x, 4)`` the stored artifact applies, and the unrounded maximum
    absolute difference is reported as well.
    """
    n = len(rows)
    df = np.zeros(n)
    ds_rounded = np.zeros(n)
    ds_raw = np.zeros(n)
    cutoff_ok = 0
    for i in range(n):
        xf, xs = reconstruct(ser, enc, str(rows.session[i]), int(rows.minute[i]))
        df[i] = np.max(np.abs(xf - rows.X_FEATURES[i])) if n else 0.0
        ds_rounded[i] = np.max(np.abs(np.round(xs, STORED_RATE_DECIMALS)
                                      - rows.X_SENSORY[i]))
        ds_raw[i] = np.max(np.abs(xs - rows.X_SENSORY[i]))
        day = _date.fromisoformat(str(rows.session[i]))
        bar = ser.bar(day, int(rows.minute[i]))
        cutoff_ok += int(bar is not None
                         and bar.ts + H.BAR_SECONDS == int(rows.market_ts[i]))
    mism_f = int((df > TOLERANCE).sum())
    mism_s = int((ds_rounded > TOLERANCE).sum())
    return {
        "grid": rows.name, "n": n,
        "tolerance": TOLERANCE,
        "X_FEATURES_max_abs_diff": float(df.max()) if n else None,
        "X_FEATURES_mismatches": mism_f,
        "X_SENSORY_max_abs_diff_after_stored_rounding":
            float(ds_rounded.max()) if n else None,
        "X_SENSORY_mismatches": mism_s,
        "X_SENSORY_max_abs_diff_unrounded": float(ds_raw.max()) if n else None,
        "stored_rate_decimals": STORED_RATE_DECIMALS,
        "market_ts_equals_bar_end": cutoff_ok,
        "mismatches_total": mism_f + mism_s,
    }


# --------------------------------------------------------- descriptives

def describe(rows: Rows) -> dict:
    """Dimensions, finite coverage, constant channels and clipping, per §4."""
    out = {"grid": rows.name, "n": int(len(rows)),
           "sessions": rows.sessions(),
           "n_sessions": len(rows.sessions()),
           "class_counts": {"Y=1": int((rows.Y == 1).sum()),
                            "Y=0": int((rows.Y == 0).sum())},
           "per_session": {}}
    for s in rows.sessions():
        m = rows.session == s
        out["per_session"][s] = {"n": int(m.sum()),
                                 "Y=1": int((rows.Y[m] == 1).sum()),
                                 "Y=0": int((rows.Y[m] == 0).sum())}
    for rep, names in (("X_FEATURES", FEATURES), ("X_SENSORY", GLOMERULI)):
        X = rows.x(rep)
        finite = np.isfinite(X)
        col = {}
        for j, name in enumerate(names):
            v = X[:, j]
            col[name] = {"min": float(v.min()), "max": float(v.max()),
                         "mean": float(v.mean()), "sd": float(v.std(ddof=1)),
                         "constant": bool(v.min() == v.max()),
                         "finite": int(np.isfinite(v).sum())}
        out[rep] = {
            "dim": int(X.shape[1]),
            "shape": [int(X.shape[0]), int(X.shape[1])],
            "finite_coverage": float(finite.all(axis=1).mean()) if len(X) else None,
            "constant_channels": [n for n, c in col.items() if c["constant"]],
            "columns": col,
        }
    # clipping: X_FEATURES is tanh-squashed into (-1, 1) and the encoder clips
    # to [-1, 1] before coding; X_SENSORY is capped at DRIVE_MAX_HZ.
    out["X_FEATURES"]["at_or_beyond_clip_abs_1"] = int(
        (np.abs(rows.X_FEATURES) >= 1.0).sum())
    out["X_SENSORY"]["at_drive_max_hz"] = int(
        (rows.X_SENSORY >= E.DRIVE_MAX_HZ - 1e-9).sum())
    out["X_SENSORY"]["drive_max_hz"] = float(E.DRIVE_MAX_HZ)
    return out


def temporal_order(fit: Rows, ev: Rows) -> dict:
    """Every fitting label resolves strictly before evaluation begins."""
    fmax = int(fit.exit_ts.max())
    emin = int(ev.market_ts.min())
    return {"max_fitting_exit_ts": fmax,
            "min_evaluation_market_ts": emin,
            "max_fitting_exit_utc": H.ny_datetime(fmax).isoformat(),
            "min_evaluation_market_utc": H.ny_datetime(emin).isoformat(),
            "strictly_before": bool(fmax < emin),
            "gap_seconds": emin - fmax}
