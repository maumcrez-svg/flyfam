"""
One fixed-hold long, under one fill convention, used by three callers.

Canonical amendment D7 §4 and §6, and Fable addendum 1: ``g(t,H)`` — the
calibration return — ``G(t)`` — the evaluator's label — and the ``POLICY_CLOSE``
fill of :class:`flytrade.historical.HistoricalExecution` are **one function
with three callers**, not three conventions that happen to agree. This module
is that function.

## The convention, stated once

A decision is taken at ``bar_end(t)`` of market minute ``t`` of one regular
session. From there, with a delay of ``delay`` market minutes and a horizon of
``H`` market minutes:

===========  =================================================================
entry        the **open** of the first available bar with
             ``bar_start >= t + delay``, same session
exit         the **open** of the first available bar with
             ``bar_start >= entry_minute + H``, same session
eligibility  ``(t + 1) + delay + H <= 390`` — a clock rule, checked before any
             price is read
===========  =================================================================

That is exactly the rule ``flytrade.historical.HistoricalExecution`` was
pre-registered with in D5/D6 addendum 4, and :func:`locate` below is the
primitive that class now calls, so the three callers cannot drift apart.

## The three behaviours of the same convention

A bar that the convention asks for may not exist — the vendor omits minutes
without a reported trade. The convention does not change; what each caller
does with the absence is declared, and is different because the three are
answering different questions:

=================  =============================================================
calibration        the origin is dropped from the **common origin set**, so
                   every candidate horizon is measured on the same origins
evaluator label    ``UNAVAILABLE_LABEL``, counted; never replaced by a loss
                   and never invented
execution          the fill lands on the next available bar and carries
                   ``DELAYED_FILL`` with the elapsed market minutes, exactly
                   as it does today
=================  =============================================================

:func:`hold` returns a :class:`Hold` with the elapsed minutes recorded, or a
:class:`NoHold` naming the reason, and the caller decides. Nothing here fills a
gap, shifts a date, crosses a session or invents a price.

## Money

``g(t,H)`` is the **gross** return at the reference (unslipped) opens, in basis
points, before any cost. ``G(t)`` is the **net** return on notional of the same
hold after the unchanged costs: slippage on both fills, always against the
trader, and the fee on both executions. Both come from the same two prices.

This module imports nothing from :mod:`flytrade.runner`,
:mod:`flytrade.mushroom` or :mod:`flytrade.execution`: it is arithmetic over a
price series, it has no state, and it can neither read nor move a weight.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

VERSION = "flytrade-horizon-1"

#: minutes in a regular session, 09:30 … 15:59. The same number
#: ``flytrade.historical.SESSION_MINUTES`` carries; a test asserts they agree.
SESSION_MINUTES = 390

#: one basis point
BPS = 1e-4

#: D7 §4, the candidate holding horizons, in elapsed market minutes
H_SET = (8, 15, 30, 60, 90, 120)


# --------------------------------------------------------------- primitive

def locate(series, day, target_minute: int):
    """First available bar at or after ``target_minute`` in ``day``'s session.

    Returns ``(minute, bar)`` or ``(None, None)``. This is the only place a
    "the minute the policy asked for may not exist" decision is made, and
    :class:`flytrade.historical.HistoricalExecution` calls it for its own
    fills, so the execution path and this module cannot disagree about which
    bar a rule points at.
    """
    m = series.next_available(day, int(target_minute))
    if m is None:
        return None, None
    return m, series.bar(day, m)


def eligible(decision_minute: int, horizon: int, *, delay: int = 1) -> bool:
    """The clock rule: ``(t + 1) + delay + H <= 390``, same session.

    Checked before any price is read, from declared session boundaries only —
    never from advance knowledge of prices or of where the gaps are.
    """
    return (int(decision_minute) + 1) + int(delay) + int(horizon) \
        <= SESSION_MINUTES


# ------------------------------------------------------------------ a hold

@dataclass(frozen=True)
class Hold:
    """One hypothetical fixed-notional long, located on real bars."""

    day: object
    decision_minute: int
    delay_minutes: int
    horizon_minutes: int
    entry_minute: int
    exit_minute: int
    entry_open: float
    exit_open: float
    entry_ts: int
    exit_ts: int

    @property
    def entry_delay(self) -> int:
        """Market minutes between the minute asked for and the fill."""
        return self.entry_minute - (self.decision_minute + self.delay_minutes)

    @property
    def exit_delay(self) -> int:
        return self.exit_minute - (self.entry_minute + self.horizon_minutes)

    @property
    def market_minutes_held(self) -> int:
        return self.exit_minute - self.entry_minute

    @property
    def gross_bps(self) -> float:
        """``g(t,H)``: gross return at the reference opens, in basis points."""
        return (self.exit_open / self.entry_open - 1.0) / BPS

    @property
    def log_return(self) -> float:
        return math.log(self.exit_open / self.entry_open)

    def net_return(self, *, notional: float, fee_bps: float,
                   slippage_bps: float) -> float:
        """``G(t)``: net return on notional, costs unchanged.

        Computed exactly as :meth:`flytrade.execution.ExecutionPolicy._settle`
        computes a realised outcome: quantity from the slipped entry price,
        slippage against the trader on both fills, the fee charged on each
        execution, and the result divided by the notional.
        """
        s = slippage_bps * BPS
        f = fee_bps * BPS
        entry_fill = self.entry_open * (1.0 + s)
        exit_fill = self.exit_open * (1.0 - s)
        qty = notional / entry_fill
        gross = qty * (exit_fill - entry_fill)
        fees = abs(qty * entry_fill) * f + abs(qty * exit_fill) * f
        return (gross - fees) / notional

    def net_pnl(self, *, notional: float, fee_bps: float,
                slippage_bps: float) -> float:
        return notional * self.net_return(notional=notional, fee_bps=fee_bps,
                                          slippage_bps=slippage_bps)

    @property
    def ok(self) -> bool:
        return True

    def as_dict(self) -> dict:
        return {"day": str(self.day), "decision_minute": self.decision_minute,
                "delay_minutes": self.delay_minutes,
                "horizon_minutes": self.horizon_minutes,
                "entry_minute": self.entry_minute,
                "exit_minute": self.exit_minute,
                "entry_open": round(self.entry_open, 8),
                "exit_open": round(self.exit_open, 8),
                "entry_ts": self.entry_ts, "exit_ts": self.exit_ts,
                "entry_delay": self.entry_delay, "exit_delay": self.exit_delay,
                "market_minutes_held": self.market_minutes_held,
                "gross_bps": round(self.gross_bps, 6)}


@dataclass(frozen=True)
class NoHold:
    """The convention asked for a bar that is not there. Named, never faked."""

    day: object
    decision_minute: int
    horizon_minutes: int
    reason: str

    #: the reasons, exhaustively
    SESSION_HORIZON = "SESSION_HORIZON"
    NO_ENTRY_BAR = "NO_ENTRY_BAR"
    NO_EXIT_BAR = "NO_EXIT_BAR"
    BAD_PRICE = "BAD_PRICE"

    @property
    def ok(self) -> bool:
        return False

    def as_dict(self) -> dict:
        return {"day": str(self.day), "decision_minute": self.decision_minute,
                "horizon_minutes": self.horizon_minutes, "reason": self.reason}


def hold(series, day, decision_minute: int, horizon: int, *,
         delay: int = 1) -> Hold | NoHold:
    """The one function. A fixed-hold long from ``decision_minute``.

    ``series`` is any object with ``next_available(day, m)`` and
    ``bar(day, m)`` — in practice a
    :class:`flytrade.historical.HistoricalSeries`. Nothing is read outside
    ``day``'s own session.
    """
    m, H = int(decision_minute), int(horizon)
    if not eligible(m, H, delay=delay):
        return NoHold(day, m, H, NoHold.SESSION_HORIZON)
    em, ebar = locate(series, day, m + int(delay))
    if ebar is None:
        return NoHold(day, m, H, NoHold.NO_ENTRY_BAR)
    if ebar.is_nan or ebar.open <= 0:
        return NoHold(day, m, H, NoHold.BAD_PRICE)
    if em + H >= SESSION_MINUTES:
        return NoHold(day, m, H, NoHold.SESSION_HORIZON)
    xm, xbar = locate(series, day, em + H)
    if xbar is None:
        return NoHold(day, m, H, NoHold.NO_EXIT_BAR)
    if xbar.is_nan or xbar.open <= 0:
        return NoHold(day, m, H, NoHold.BAD_PRICE)
    return Hold(day=day, decision_minute=m, delay_minutes=int(delay),
                horizon_minutes=H, entry_minute=int(em), exit_minute=int(xm),
                entry_open=float(ebar.open), exit_open=float(xbar.open),
                entry_ts=int(ebar.ts), exit_ts=int(xbar.ts))


# ------------------------------------------------------------- calibration

def common_origins(series, day, horizons=H_SET, *, delay: int = 1,
                   require_ok: bool = True) -> list[int]:
    """The origins usable by **every** candidate horizon, in one session.

    D7 §4: an origin must have causally available market features, permit the
    entry delay, permit the **maximum** candidate horizon inside the session,
    and have the required observed entry and exit prices. The set is built once
    per session and used for every ``H``, so a difference between two ``A(H)``
    values is a difference in horizon and never a difference in sample.
    """
    hs = tuple(int(h) for h in horizons)
    hmax = max(hs)
    out: list[int] = []
    for m in range(SESSION_MINUTES):
        if not eligible(m, hmax, delay=delay):
            break
        if require_ok and series.status(day, m).value != "OK":
            continue
        if all(hold(series, day, m, h, delay=delay).ok for h in hs):
            out.append(m)
    return out


def median(values) -> float:
    """Plain median, on a sorted copy. No interpolation beyond the midpoint."""
    v = sorted(float(x) for x in values)
    n = len(v)
    if n == 0:
        raise ValueError("median of an empty sample")
    mid = n // 2
    return v[mid] if n % 2 else 0.5 * (v[mid - 1] + v[mid])


def session_table(series, day, horizons=H_SET, *, delay: int = 1) -> dict:
    """``median |g(t,H)|`` over one session's common origins, for every H."""
    origins = common_origins(series, day, horizons, delay=delay)
    row = {"session": str(day), "origins": len(origins),
           "first_origin": origins[0] if origins else None,
           "last_origin": origins[-1] if origins else None,
           "median_abs_g_bps": {}}
    for h in horizons:
        gs = [abs(hold(series, day, m, h, delay=delay).gross_bps)
              for m in origins]
        row["median_abs_g_bps"][str(h)] = median(gs) if gs else None
    return row


def calibrate(series, sessions, *, horizons=H_SET, cost_bps: float,
              multiple: float = 2.0, delay: int = 1,
              min_origins: int = 100) -> dict:
    """``A(H)``, the selection, and everything it was computed from.

    ``sessions`` is the list of qualifying WARMUP session dates, decided by the
    committed protocol's data-quality rule before this is called. Only those
    sessions are ever touched: this function never asks ``series`` for a day it
    was not given.

    ``A(H) = median across sessions of [median across common origins of
    |g(t,H)|]`` and ``H* = the smallest H in H_SET with A(H) >= multiple *
    cost_bps``. If no candidate qualifies the result carries
    ``selected = None`` and ``result = "NO_HORIZON_MEETS_RULE"``; nothing falls
    back to the largest horizon and no multiplier is tried twice.
    """
    rows = [session_table(series, d, horizons, delay=delay) for d in sessions]
    short = [r["session"] for r in rows if r["origins"] < min_origins]
    a: dict[str, float] = {}
    for h in horizons:
        per = [r["median_abs_g_bps"][str(h)] for r in rows
               if r["median_abs_g_bps"][str(h)] is not None]
        a[str(h)] = median(per) if per else None
    threshold = float(multiple) * float(cost_bps)
    selected = None
    for h in horizons:
        if a[str(h)] is not None and a[str(h)] >= threshold:
            selected = int(h)
            break
    return {
        "version": VERSION,
        "rule": "H* = smallest H in H_SET with A(H) >= multiple * C",
        "horizons": list(horizons),
        "delay_minutes": int(delay),
        "cost_bps": float(cost_bps),
        "multiple": float(multiple),
        "threshold_bps": threshold,
        "sessions_used": [r["session"] for r in rows],
        "n_sessions": len(rows),
        "sessions_below_min_origins": short,
        "min_origins": int(min_origins),
        "per_session": rows,
        "A_bps": a,
        "selected_horizon_minutes": selected,
        "result": ("OK" if selected is not None else "NO_HORIZON_MEETS_RULE"),
    }
