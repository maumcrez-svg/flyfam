"""``pons_context_v2`` — what a memecoin looks like, with its activity kept.

docs/SPEC.md D11 amendment §4 and Fable addendum 4. ``pons_context_v1``
(:mod:`flytrade.pons.context`) is left **byte-identical** beside this module so
every D10 log, test and the determinism check keep reproducing; this is the
version D11 registers and the version ``d11-001`` would run.

What v1 got wrong is not a bug in its arithmetic. It is that a token quiet for
ten seconds and a token quiet for fifty minutes arrived at the brain as the
same vector: every window empties, every windowed feature reads a *valid* zero,
and only ``age`` keeps moving — and ``tanh(age / 600)`` has already reached
0.99998 at fifty-eight minutes. Ten features replace the eight:

================== ====================================================
``age``            seconds since the launch block
``since_last_trade`` seconds since the last **valid** trade, so quiet has
                   a duration; the age when the token has never traded
``ret_30s``        log change of the marginal curve price over 30 s
``ret_2m``         the same over 120 s
``ret_5m``         the same over 300 s
``flow_imb_2m``    (buy quote in − sell quote out) / (their sum), in [−1, 1]
``trade_count_2m`` valid trades inside the 120 s window (replaces
                   ``trade_rate_2m``, which was this count per minute)
``gross_volume_2m`` Σ |curve-side quote delta| of those trades, in ETH:
                   the **gross** traded volume, not the net signed flow
``rv_2m``          SD of per-trade log marginal-price changes over 120 s
``drawdown_5m``    log distance below the 5-minute maximum, ≤ 0
================== ====================================================

**A valid trade** is a ``CurveBuy`` / ``CurveSell`` with a nonzero quote leg and
a nonzero token leg, deduplicated by log id. Creation, liquidity configuration,
``CurveCompleted`` and repeated log lines are not trades; a snipe-tax exemption
is not a trade and a snipe-taxed buy is an ordinary one. Buys and sells count
the same. :mod:`flytrade.pons.admission_v2` applies the identical definition,
from this module, so the recency rule and the sensory input can never disagree
about what a trade is.

**Causal and clipped to the launch**, exactly as D10 clips: every feature is
computed from tape points at or before the cutoff and from nothing after it,
and a window that starts before the launch is measured *from the launch*.

**Absent is still not neutral.** A token younger than 60 s, one whose
reconstructed state fails its own arithmetic, or one whose curve completed onto
the unsupported route is not presented and its reason is recorded. What v1's
"fewer than three trades ever" gate did is now done by the *recency* rule in
admission v2, where it belongs: a token with a short tape is
``INSUFFICIENT_HISTORY`` and a token with a long quiet one is ``INACTIVE``, and
those are different facts.

Nothing in this module reads the network, reads an outcome, or knows what a
position is.
"""

from __future__ import annotations

import math
import statistics

from .. import market as MK
from .context import (MIN_AGE_S, PAPER_SIZE_WEI, TRADE_KINDS, PonsContext,
                      TapePoint, TokenTape)
from .curve import QuoteError, quote_curve_buy

VERSION = "pons_context_v2"

#: The feature order. The encoder maps channel pairs to it in this order, and a
#: feature dropped for want of glomeruli is dropped **from the end**.
PONS_FEATURES_V2: tuple[str, ...] = (
    "age", "since_last_trade", "ret_30s", "ret_2m", "ret_5m",
    "flow_imb_2m", "trade_count_2m", "gross_volume_2m", "rv_2m",
    "drawdown_5m")

#: Window, in seconds, of each windowed feature.
FEATURE_WINDOWS_V2 = {"ret_30s": 30, "ret_2m": 120, "ret_5m": 300,
                      "flow_imb_2m": 120, "trade_count_2m": 120,
                      "gross_volume_2m": 120, "rv_2m": 120,
                      "drawdown_5m": 300}

#: The declared scale of ``since_last_trade``: the admission bound itself, so
#: an admitted token spans ``tanh(x / 60) ∈ (0, 0.76]`` and a held token that
#: goes quiet keeps rising toward 1. Not fitted to any sample (addendum 4).
SINCE_LAST_TRADE_SCALE_S = 60.0

#: Wei per ETH. ``gross_volume_2m`` is denominated in ETH.
WEI = 10 ** 18

#: Features whose sign never changes. They keep the two-channel rule anyway,
#: declared as D10 declared its three. ``rv_2m`` is a standard deviation and is
#: non-negative by construction too; as in D10 it is not listed here.
SINGLE_SIGNED = ("age", "since_last_trade", "trade_count_2m",
                 "gross_volume_2m", "drawdown_5m")


def is_valid_trade(point: TapePoint) -> bool:
    """One tape point, and whether it is a trade the rules may count.

    ``trade_price`` is ``quote / tokens`` of that leg and is ``None`` when the
    token leg was zero, so ``trade_price is not None and trade_price > 0``
    is exactly "nonzero quote leg and nonzero token leg". Nothing else in a
    :class:`~flytrade.pons.context.TapePoint` can carry a zero-amount trade.
    """
    return (point.kind in TRADE_KINDS
            and point.trade_price is not None
            and float(point.trade_price) > 0.0)


def valid_trades(points, *, window: tuple[int, int] | None = None) -> list:
    """The valid trades among ``points``, deduplicated by log id.

    ``window`` is the half-open ``(start, cutoff]`` in chain seconds. A point
    with an empty log id — the synthetic launch point, and a tape built by a
    fixture that does not carry log ids — is never deduplicated away.
    """
    seen: set[str] = set()
    out = []
    for point in points:
        if not is_valid_trade(point):
            continue
        log_id = str(point.log_id or "")
        if log_id:
            if log_id in seen:
                continue
            seen.add(log_id)
        if window is not None:
            start, cutoff = window
            if not (start < int(point.ts) <= int(cutoff)):
                continue
        out.append(point)
    return out


def _price_at(upto, when: int) -> float | None:
    price = None
    for point in upto:
        if point.ts <= when:
            price = point.marginal_price
        else:
            break
    return price


def _realised_volatility(upto, window_trades, cutoff: int) -> float:
    """SD of the per-trade log marginal-price steps inside the window.

    The step of a trade is measured against the marginal price of whatever
    point preceded it — the same convention ``pons_context_v1`` uses — so only
    the *selection* of which points count as trades differs from v1.
    """
    inside = {id(p) for p in window_trades}
    steps = []
    previous = None
    for point in upto:
        if (previous is not None and id(point) in inside
                and point.marginal_price > 0 and previous > 0):
            steps.append(math.log(point.marginal_price / previous))
        previous = point.marginal_price
    return statistics.stdev(steps) if len(steps) >= 2 else 0.0


def context_v2(tape: TokenTape, cutoff: int, *, tick: int = -1,
               stable_id: int = -1,
               size_wei: int = PAPER_SIZE_WEI) -> PonsContext:
    """The ten measurements at ``cutoff``, and the three prices beside them.

    Returns the same :class:`~flytrade.pons.context.PonsContext` record v1
    returns — the observation, the journal and the readout all keep working
    unchanged — carrying ``version = "pons_context_v2"`` and this wave's ten
    features in ``raw``.
    """
    cutoff = int(cutoff)
    upto = tape._upto(cutoff)
    age = cutoff - tape.launched_at
    blank = dict(token=tape.token, curve=tape.curve, cutoff_ts=cutoff,
                 tick=tick, stable_id=stable_id, age_s=age,
                 launch_block=tape.launch_block, launched_at=tape.launched_at,
                 version=VERSION)
    if not upto:
        return PonsContext(status=MK.ObservationStatus.INSUFFICIENT_TAPE,
                           reason="the cutoff precedes the launch block",
                           **blank)
    if tape.inconsistent:
        return PonsContext(status=MK.ObservationStatus.INCONSISTENT_STATE,
                           reason=tape.inconsistent, **blank)
    if tape.completed_by(cutoff):
        return PonsContext(status=MK.ObservationStatus.ROUTE_COMPLETED,
                           reason="the curve completed before the cutoff",
                           completed=True, **blank)
    if age < MIN_AGE_S:
        return PonsContext(status=MK.ObservationStatus.INSUFFICIENT_TAPE,
                           reason=f"age {age}s < {MIN_AGE_S}s", **blank)
    here = upto[-1]
    price = here.marginal_price
    if price <= 0 or here.token_reserve <= 0 or here.quote_reserve <= 0:
        return PonsContext(status=MK.ObservationStatus.INCONSISTENT_STATE,
                           reason="non-positive reserves at the cutoff",
                           **blank)

    trades = valid_trades(upto)
    window = valid_trades(
        upto, window=(cutoff - FEATURE_WINDOWS_V2["trade_count_2m"], cutoff))

    raw = {"age": float(age)}
    # Quiet has a duration again. With no trade at all it is the age: the same
    # clipped-to-launch convention every windowed feature uses, and never a
    # zero that would read as "it just traded".
    raw["since_last_trade"] = float(cutoff - trades[-1].ts) if trades else float(age)
    for name in ("ret_30s", "ret_2m", "ret_5m"):
        start = max(cutoff - FEATURE_WINDOWS_V2[name], tape.launched_at)
        earlier = _price_at(upto, start)
        raw[name] = (0.0 if earlier is None or earlier <= 0
                     else math.log(price / earlier))
    buy_in = sum(p.flow for p in window if p.flow > 0)
    sell_out = -sum(p.flow for p in window if p.flow < 0)
    total = buy_in + sell_out
    raw["flow_imb_2m"] = 0.0 if total == 0 else (buy_in - sell_out) / total
    raw["trade_count_2m"] = float(len(window))
    raw["gross_volume_2m"] = float(sum(abs(int(p.flow)) for p in window)) / WEI
    raw["rv_2m"] = _realised_volatility(upto, window, cutoff)
    peak = max((p.marginal_price for p in upto
                if p.ts >= max(cutoff - FEATURE_WINDOWS_V2["drawdown_5m"],
                               tape.launched_at)), default=price)
    raw["drawdown_5m"] = (0.0 if peak <= 0 else min(0.0, math.log(price / peak)))

    state = tape.state_at(cutoff)
    executable, quote_error = (None, "NO_STATE")
    if state is not None:
        try:
            executable, quote_error = quote_curve_buy(
                state, int(size_wei)).tokens_out, ""
        except QuoteError as exc:
            executable, quote_error = None, exc.code
    return PonsContext(
        status=MK.ObservationStatus.OK, reason="",
        raw=raw, marginal_price=price,
        last_trade_price=(trades[-1].trade_price if trades else None),
        executable_tokens_out=executable, executable_size_wei=int(size_wei),
        executable_error=quote_error, trades=len(trades),
        trades_2m=len(window), completed=tape.completed_by(cutoff),
        state=tape._state_of(here).as_dict(), **blank)


def recent_activity(tape: TokenTape, cutoff: int, *, window_s: int = 120
                    ) -> dict:
    """``(count in the window, seconds since the last valid trade)``.

    The one place the recency facts are measured, shared by
    :mod:`flytrade.pons.admission_v2` and by every D11 diagnostic, so the rule
    and the feature can never drift apart.
    """
    cutoff = int(cutoff)
    upto = tape._upto(cutoff)
    trades = valid_trades(upto)
    window = valid_trades(upto, window=(cutoff - int(window_s), cutoff))
    return {
        "trades_ever": len(trades),
        "trades_in_window": len(window),
        "since_last_trade_s": (None if not trades
                               else cutoff - int(trades[-1].ts)),
    }


__all__ = ["VERSION", "PONS_FEATURES_V2", "FEATURE_WINDOWS_V2",
           "SINCE_LAST_TRADE_SCALE_S", "SINGLE_SIGNED", "WEI",
           "is_valid_trade", "valid_trades", "context_v2", "recent_activity"]
