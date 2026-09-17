"""``state.json``: what the loop currently is, and what a restart needs back.

docs/SPEC.md P1 addendum 4 lists what the state file holds and addendum 3(c)
what a restart restores. Both are here, in one module, because they are two
views of one thing: the sections a reader displays and the ``restore`` block
the next process reads are written by the same tick.

Every number in a section is the ETH float the account keeps **and** its wei
rendering. The rendering is ``round(eth * 1e18)`` and is labelled as derived:
the exact integers of a fill are in the journal's own ``OUTCOME`` record, and
this file is a display surface, not a ledger.
"""

from __future__ import annotations

import time

from .. import execution as X
from ..pons.paper import WEI

VERSION = "pons-live-restore-1"


def wei(eth) -> str:
    return "0" if eth is None else str(int(round(float(eth) * WEI)))


def _fill(f: X.Fill) -> dict:
    return {"side": f.side.value, "symbol": f.symbol,
            "bar_index": int(f.bar_index), "ts": int(f.ts),
            "reference_price": float(f.reference_price),
            "fill_price": float(f.fill_price),
            "quantity": float(f.quantity), "fee": float(f.fee),
            "delay_minutes": int(f.delay_minutes), "flag": str(f.flag)}


def _fill_from(d: dict) -> X.Fill:
    return X.Fill(side=X.Side(d["side"]), symbol=d["symbol"],
                  bar_index=int(d["bar_index"]), ts=int(d["ts"]),
                  reference_price=float(d["reference_price"]),
                  fill_price=float(d["fill_price"]),
                  quantity=float(d["quantity"]), fee=float(d["fee"]),
                  delay_minutes=int(d.get("delay_minutes", 0)),
                  flag=str(d.get("flag", "")))


# --------------------------------------------------------------- sections
def account_section(execution) -> dict:
    a = execution.account
    mark = execution.last_mark if isinstance(getattr(execution, "last_mark", None),
                                             dict) else {}
    unrealised = mark.get("unrealised_eth") if a.position is not None else None
    return {
        "initial_cash_eth": float(a.initial_cash),
        "cash_eth": float(a.cash), "cash_wei": wei(a.cash),
        "realized_pnl_eth": float(a.realized_pnl),
        "realized_pnl_wei": wei(a.realized_pnl),
        "unrealised_eth": (None if unrealised is None else float(unrealised)),
        "unrealised_wei": (None if unrealised is None else wei(unrealised)),
        "equity_eth": float(a.cash) + float(unrealised or 0.0)
        + (0.0 if a.position is None else
           float(a.position.quantity) * float(a.position.entry.fill_price)
           + float(a.position.entry.fee)),
        "fees_paid_eth": float(a.fees_paid),
        "slippage_paid_eth": float(a.slippage_paid),
        "trades": int(a.trades),
        "size_eth": float(execution.notional),
        "wei_rendering": ("round(eth * 1e18) of the account's own float; the "
                          "exact integers of a fill are in the journal's "
                          "OUTCOME record"),
    }


def position_section(loop, cutoff: int | None = None) -> dict | None:
    p = loop.x.account.position
    if p is None:
        return None
    mark = loop.x.last_mark if isinstance(getattr(loop.x, "last_mark", None),
                                          dict) else {}
    tape = loop.tapes.get(p.symbol)
    now = int(cutoff or 0)
    cost = float(p.quantity) * float(p.entry.fill_price) + float(p.entry.fee)
    return {
        "token": p.symbol, "curve": (None if tape is None else tape.curve),
        "episode_id": int(p.episode_id), "stable_id": int(p.stable_id),
        "entry_ts": int(p.entry.ts), "entry_block": int(p.entry.bar_index),
        "entry_price_eth_per_token": float(p.entry.fill_price),
        "entry_reference_price": float(p.entry.reference_price),
        "size_eth": float(loop.x.notional),
        "quantity_tokens": float(p.quantity),
        "tokens_wei": (None if loop.x.entry_tokens_wei is None
                       else str(int(loop.x.entry_tokens_wei))),
        "cost_eth": cost,
        "entry_fee_eth": float(p.entry.fee),
        "age_s": (None if not now else max(0, now - int(p.entry.ts))),
        "horizon_ts": (None if loop.x.horizon_ts is None
                       else int(loop.x.horizon_ts)),
        "seconds_to_horizon": (None if (not now or loop.x.horizon_ts is None)
                               else int(loop.x.horizon_ts) - now),
        "last_mark": mark or None,
        "unrealised_eth": mark.get("unrealised_eth"),
        "unrealised_wei": (None if mark.get("unrealised_eth") is None
                           else wei(mark.get("unrealised_eth"))),
        "pending_confirmation": (None if loop.pending is None
                                 else loop.pending.get("episode_id")),
        "never_closed_at_a_restart": True,
    }


def episode_row(episode: dict, credit: dict | None) -> dict:
    """One closed episode, with its credit label beside its money."""
    return {
        "episode_id": episode.get("episode_id"), "token": episode.get("token"),
        "entry_ts": episode.get("entry_ts"), "exit_ts": episode.get("exit_ts"),
        "entry_block": episode.get("entry_block"),
        "exit_block": episode.get("exit_block"),
        "seconds_held": episode.get("seconds_held"),
        "gross_pnl_eth": episode.get("gross_pnl"),
        "fees_eth": episode.get("fees_eth"),
        "slippage_eth": episode.get("slippage_eth"),
        "net_pnl_eth": episode.get("net_pnl"),
        "net_pnl_wei": wei(episode.get("net_pnl")),
        "return_on_notional": episode.get("return_on_notional"),
        "close_reason": episode.get("close_reason"),
        "settlement": episode.get("settlement"),
        "credit": (None if credit is None else
                   {"label": credit.get("label"),
                    "valence": credit.get("valence"),
                    "amount": credit.get("amount"),
                    "applied": False}),
    }


def health_section(loop, driver, *, started_at: float, brain_digest: str,
                   rpc=None) -> dict:
    now = time.time()
    ledger = driver.collector.rpc.ledger
    last = driver.head_track[-1] if driver.head_track else {}
    return {
        "started_epoch": int(started_at),
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                     time.gmtime(started_at)),
        "uptime_s": int(now - started_at),
        "ticks_this_process": int(driver.ticks_done),
        "tick": int(loop.global_tick),
        "last_tick_epoch": int(last.get("cutoff_ts") or 0) or None,
        "last_cutoff_ts": int(driver.last_ts or 0) or None,
        "cutoff_age_s": last.get("cutoff_age_s"),
        "head_block": last.get("head"), "cursor_block": last.get("cursor"),
        "lag_blocks": last.get("lag_blocks"),
        "tracked_curves": len(loop.tapes),
        "launches_seen": int(driver.launches_seen),
        "throttled": bool(driver.throttled),
        "throttle_events": int(driver.throttle_events),
        "throttled_seconds": round(float(driver.throttle_seconds), 1),
        "reorgs": int(driver.reorgs),
        "errors": int(getattr(rpc, "errors", 0) or 0),
        "retries": int(getattr(rpc, "retries", 0) or 0),
        "last_error": getattr(rpc, "last_error", None),
        "tape_missing_ticks": int(loop.tape_missing),
        "brain_digest": brain_digest,
        "learning": loop.learning,
        "stop": {"reason": driver.stopped, "detail": driver.stop_detail},
        "ledger_halted": ledger.halted(),
    }


def requests_section(driver) -> dict:
    ledger = driver.collector.rpc.ledger
    now = time.time()
    return {
        "hour": driver.window.spent(now, ledger.attempts),
        "hour_cap": driver.window.cap,
        "hour_remaining": max(0, driver.window.usable
                              - driver.window.spent(now, ledger.attempts)),
        "window_s": driver.window.window_s,
        "this_process": int(ledger.run_attempts),
        "total_attempts": int(ledger.attempts),
        "total_units": int(ledger.units),
        "by_method": {k: dict(v) for k, v in
                      (ledger.state.get("by_method") or {}).items()},
        "backfill": {k: driver.backfill.get(k) for k in
                     ("requests", "events", "wall_s", "first_block",
                      "last_block", "resumed_from_cursor")},
    }


def restore_block(loop, driver) -> dict:
    """Everything the next process needs to be this one. Addendum 3(c)."""
    a = loop.x.account
    p = a.position
    curve = None if p is None else (loop.tapes[p.symbol].curve
                                    if p.symbol in loop.tapes else None)
    delta = None if curve is None else loop.x.own_delta.get(curve)
    ledger = driver.collector.rpc.ledger
    return {
        "version": VERSION,
        "tick": int(loop.global_tick),
        "last_cutoff_ts": int(driver.last_ts or 0) or None,
        "account": {"cash": float(a.cash), "initial_cash": float(a.initial_cash),
                    "realized_pnl": float(a.realized_pnl),
                    "fees_paid": float(a.fees_paid),
                    "slippage_paid": float(a.slippage_paid),
                    "trades": int(a.trades)},
        "position": (None if p is None else {
            "episode_id": int(p.episode_id), "symbol": p.symbol,
            "stable_id": int(p.stable_id), "curve": curve,
            "entry": _fill(p.entry), "horizon_bar": int(p.horizon_bar),
            "horizon_ts": (None if loop.x.horizon_ts is None
                           else int(loop.x.horizon_ts)),
            "entry_cutoff": (None if loop.x.entry_cutoff is None
                             else int(loop.x.entry_cutoff)),
            "entry_tokens_wei": (None if loop.x.entry_tokens_wei is None
                                 else str(int(loop.x.entry_tokens_wei))),
            "own_delta": (None if delta is None else
                          {"quote": str(int(delta["quote"])),
                           "tokens": str(int(delta["tokens"]))})}),
        "pending": loop.pending,
        "credits": dict(loop.credits),
        "sniffed": dict(loop.sniffed),
        "rejected_session": dict(loop.rejected_session),
        "settled_episodes": len(loop.x.outcomes),
        "unresolved_seen": len(loop._unresolved_seen),
        "request_window": [[round(t, 3), int(n)]
                           for t, n in driver.window.samples],
        "request_attempts_total": int(ledger.attempts),
    }


def restore_into(state: dict, *, execution, log=print) -> dict:
    """Put a previous process's account and position back. Returns what it did.

    A position open across a restart **stays open**: it is restored with its
    entry fill, its own reserve delta and its horizon, and it is never closed
    at a restart mark. Nothing here re-prices anything; the numbers are the
    ones the previous process wrote.
    """
    block = (state or {}).get("restore") or {}
    out = {"restored": False, "position": None, "tick": 0,
           "last_cutoff_ts": None, "account": False}
    if not block:
        return out
    acc = block.get("account") or {}
    if acc:
        a = execution.account
        a.cash = float(acc.get("cash", a.cash))
        a.initial_cash = float(acc.get("initial_cash", a.initial_cash))
        a.realized_pnl = float(acc.get("realized_pnl", 0.0))
        a.fees_paid = float(acc.get("fees_paid", 0.0))
        a.slippage_paid = float(acc.get("slippage_paid", 0.0))
        a.trades = int(acc.get("trades", 0))
        out["account"] = True
    pos = block.get("position")
    if pos:
        execution.account.position = X.Position(
            episode_id=int(pos["episode_id"]), symbol=pos["symbol"],
            stable_id=int(pos["stable_id"]), entry=_fill_from(pos["entry"]),
            horizon_bar=int(pos["horizon_bar"]), day=pos.get("curve"))
        execution.horizon_ts = (None if pos.get("horizon_ts") is None
                                else int(pos["horizon_ts"]))
        execution.entry_cutoff = (None if pos.get("entry_cutoff") is None
                                  else int(pos["entry_cutoff"]))
        execution.entry_tokens_wei = (None if pos.get("entry_tokens_wei") is None
                                      else int(pos["entry_tokens_wei"]))
        delta, curve = pos.get("own_delta"), pos.get("curve")
        if delta and curve:
            execution.own_delta[curve] = {"quote": int(delta["quote"]),
                                          "tokens": int(delta["tokens"])}
        out["position"] = {"token": pos["symbol"],
                           "episode_id": int(pos["episode_id"]),
                           "entry_ts": int(pos["entry"]["ts"]),
                           "horizon_ts": pos.get("horizon_ts")}
    out["restored"] = True
    out["tick"] = int(block.get("tick", 0))
    out["last_cutoff_ts"] = block.get("last_cutoff_ts")
    out["pending"] = block.get("pending")
    out["request_window"] = block.get("request_window") or []
    out["counters"] = {"credits": block.get("credits") or {},
                       "sniffed": block.get("sniffed") or {},
                       "rejected_session": block.get("rejected_session") or {}}
    log(f"[resume] account cash {execution.account.cash:.8f} ETH, realised "
        f"{execution.account.realized_pnl:.8f} ETH, "
        f"{execution.account.trades} trades, tick {out['tick']}, position "
        f"{out['position']['token'] if out['position'] else 'flat'}")
    return out


__all__ = ["VERSION", "wei", "account_section", "position_section",
           "episode_row", "health_section", "requests_section",
           "restore_block", "restore_into"]
