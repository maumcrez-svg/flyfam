"""Read-only recomputation behind ``experiments/d10/closure_complement.md``.

Nothing here writes into the repository, opens a socket, loads a brain or
touches a run. It reads the committed logs of ``d10-001`` and ``d10-live-001``,
the two datasets under ``data/pons/``, ``rpc_ledger.json`` and ``config.json``,
re-derives the numbers the closure document quotes, and prints them as JSON on
stdout. Every quantity it produces is traceable to a log record (by ``kind``
and ``episode_id`` or ``cutoff_ts``) or to a dataset file.

The curve arithmetic is :mod:`flytrade.pons.curve`, unchanged and imported, so
a leg recomputed here is the same integer-exact quote the run used; the
reproduction of each logged ``tokens_out`` is asserted rather than assumed.
The encoder drive is recomputed from ``config.json``'s declared channel map and
the three declared constants, and is checked against a logged stimulus, so no
connectome is loaded.

    .venv/bin/python experiments/d10/closure_complement.py > /dev/null
"""

from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
D10 = ROOT / "experiments" / "d10"
WEI = 10 ** 18

import sys
sys.path.insert(0, str(ROOT))

from flytrade.pons.collector import BlockClock            # noqa: E402
from flytrade.pons.curve import (CurveReconstruction, CurveState,  # noqa: E402
                                 quote_curve_buy, quote_curve_sell,
                                 snipe_tax_bps)

CONFIG = json.loads((D10 / "config.json").read_text())
GAS_BUY = int(CONFIG["gas"]["buy_wei"])
GAS_SELL = int(CONFIG["gas"]["sell_wei"])
GAS_APPROVAL = int(CONFIG["gas"]["approval_wei"])
SCALES = CONFIG["features"]["scales"]
FEATURES = tuple(CONFIG["features"]["order"])
CHANNELS = CONFIG["encoder"]["channel_map"]
CARRIER = float(CONFIG["encoder"]["carrier"])
BUDGET = float(CONFIG["encoder"]["drive_budget_hz"])
DRIVE_MAX = float(CONFIG["encoder"]["drive_max_hz"])

TRADES = ("CurveBuy", "CurveSell")

BRANCHES = {
    "learning": D10 / "runs/d10-001/learning/events.jsonl",
    "frozen_reference": D10 / "runs/d10-001/frozen_reference/events.jsonl",
    "live": D10 / "runs/d10-live-001/live/events.jsonl",
}
STORES = {
    "learning": ROOT / "data/pons/d10-backfill-v1",
    "frozen_reference": ROOT / "data/pons/d10-backfill-v1",
    "live": D10 / "runs/d10-live-001/chain",
}


# ----------------------------------------------------------------- loading
def read_log(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def read_events(directory: Path):
    """Curve events by curve address, and launches by token, sorted on chain order."""
    by_curve: dict[str, list[dict]] = defaultdict(list)
    launches: dict[str, dict] = {}
    with open(directory / "events.jsonl", encoding="utf-8") as fh:
        for line in fh:
            e = json.loads(line)
            if e.get("status") != "OK":
                continue
            if e.get("source") == "factory" and e.get("event") == "TokenLaunched":
                launches.setdefault(e["token"], e)
            elif e.get("source") == "curve":
                by_curve[e["address"]].append(e)
    for evs in by_curve.values():
        evs.sort(key=lambda e: (e["block_number"], e["tx_index"], e["log_index"]))
    return by_curve, launches


def flow_of(event: dict) -> int:
    """Signed quote flow of one trade: + a buy's net in, − a sell's gross out."""
    a = event.get("args") or {}
    if event["event"] == "CurveBuy":
        return int(a["quoteIn"]) - int(a["fee"]) - int(a["tax"])
    if event["event"] == "CurveSell":
        return -(int(a["quoteOut"]) + int(a["fee"]) + int(a["tax"]))
    return 0


# ------------------------------------------------------------- A. episodes
def state_from(record: dict) -> CurveState:
    return CurveState(
        quote_reserve=int(record["quote_reserve"]),
        token_reserve=int(record["token_reserve"]),
        real_quote_reserve=int(record["real_quote_reserve"]),
        sellable_tokens=int(record["sellable_tokens"]),
        fee_bps=int(record["fee_bps"]),
        creator_tax_bps=int(record["creator_tax_bps"]),
        snipe_tax_bps=0, graduated=bool(record["graduated"]))


def advance(state: CurveState, events, lo: int, hi: int, *, launch_block: int,
            launched_at: int):
    """``state`` advanced through every event with ``lo < ts <= hi``."""
    rec = CurveReconstruction(state, launch_block=launch_block,
                              launched_at=launched_at, snipe_start_bps=9900,
                              snipe_window_seconds=3)
    used = []
    for e in events:
        if lo < e["block_timestamp"] <= hi:
            rec.apply(e)
            used.append(e)
    return rec.state, used


def carry(state: CurveState, delta_quote: int, delta_tokens: int) -> CurveState:
    """``PonsPaperExecution.carry``: our own reserve delta, and nothing else."""
    return CurveState(
        quote_reserve=state.quote_reserve + delta_quote,
        token_reserve=state.token_reserve - delta_tokens,
        real_quote_reserve=state.real_quote_reserve + delta_quote,
        sellable_tokens=max(state.sellable_tokens - delta_tokens, 0),
        fee_bps=state.fee_bps, creator_tax_bps=state.creator_tax_bps,
        snipe_tax_bps=0, graduated=state.graduated)


def block_clock(directory: Path) -> BlockClock:
    headers = [json.loads(line) for line
               in (directory / "headers.jsonl").read_text().splitlines()
               if line.strip()]
    return BlockClock(headers, interval_s=0.101, grid_blocks=100)


def episodes(branch: str) -> list[dict]:
    log = read_log(BRANCHES[branch])
    by_curve, _ = read_events(STORES[branch])
    clock = block_clock(STORES[branch])
    rounds = {r["cutoff_ts"]: r for r in log if r.get("kind") == "ROUND"}
    decisions = {r["episode_id"]: r for r in log if r.get("kind") == "DECISION"}
    learning = {r["episode_id"]: r for r in log if r.get("kind") == "LEARNING"}
    outcomes = {r["episode_id"]: r for r in log if r.get("kind") == "OUTCOME"}
    unresolved = [r for r in log if r.get("kind") == "UNRESOLVED"]
    out = []
    for ex in [r for r in log if r.get("kind") == "EXECUTION"]:
        ep = ex["episode_id"]
        row = {"branch": branch, "episode_id": ep, "token": ex["token"],
               "curve": ex["curve"], "entry_cutoff_ts": ex["cutoff_ts"],
               "entry_fill_ts": ex["market_ts"], "entry_block": ex["block_number"],
               "horizon_ts": ex["horizon_ts"]}
        dec = decisions.get(ep)
        rnd = rounds.get(ex["cutoff_ts"])
        ctx = None
        if rnd:
            row["tick"] = rnd["tick"]
            for c in rnd["context"]:
                if c["token"] == ex["token"]:
                    ctx = c
        at = clock.block_at_or_after(ex["cutoff_ts"])
        row["cutoff_block_from_the_grid"] = at.get("block_number")
        row["cutoff_block_interpolated"] = at.get("interpolated")
        row["decision_record_block_number_is_the_launch_block"] = (
            dec["block_number"] if dec else None)
        row["launched_at"] = ctx["launched_at"] if ctx else None
        row["launch_block"] = ctx["launch_block"] if ctx else None
        row["age_at_decision_s"] = ctx["age_s"] if ctx else None
        row["marginal_price_at_decision"] = ctx["marginal_price"] if ctx else None
        row["raw"] = dec["observation"]["raw"] if dec else None
        row["normalized"] = dec["observation"]["normalized"] if dec else None
        row["decoded_action"] = dec["decoded_action"] if dec else None

        evs = by_curve.get(ex["curve"], [])
        cutoff = ex["cutoff_ts"]
        trades = [e for e in evs if e["event"] in TRADES]
        before = [e for e in trades if e["block_timestamp"] <= cutoff]
        row["trades_before_cutoff"] = len(before)
        row["last_trade_ts_at_or_before_cutoff"] = (
            before[-1]["block_timestamp"] if before else None)
        row["seconds_since_last_trade_at_decision"] = (
            cutoff - before[-1]["block_timestamp"] if before else None)
        for w in (30, 120, 300):
            row[f"trades_prev_{w}s"] = sum(
                1 for e in before if e["block_timestamp"] > cutoff - w)
        row["net_flow_prev_120s_wei"] = sum(
            flow_of(e) for e in before if e["block_timestamp"] > cutoff - 120)

        # --- the buy leg, re-quoted at the fill block
        st = state_from(ctx["state"])
        fill_state_raw, _ = advance(st, evs, cutoff, ex["market_ts"],
                                    launch_block=ctx["launch_block"],
                                    launched_at=ctx["launched_at"])
        snipe = snipe_tax_bps(9900, 3, max(0, ex["market_ts"] - ctx["launched_at"]))
        fill_state = fill_state_raw.with_snipe(snipe)
        buy = quote_curve_buy(fill_state, int(CONFIG["paper_size_wei"]))
        assert str(buy.tokens_out) == ex["tokens_out_wei"], (branch, ep)
        row["buy"] = {
            "block": ex["block_number"], "ts": ex["market_ts"],
            "requested_wei": str(buy.requested), "spent_wei": str(buy.spent),
            "refund_wei": str(buy.refund), "tokens_out_wei": str(buy.tokens_out),
            "fee_base_wei": str(buy.fee_base),
            "fee_creator_wei": str(buy.fee_creator),
            "fee_snipe_wei": str(buy.fee_snipe),
            "snipe_tax_bps_at_fill": snipe,
            "net_into_curve_wei": str(buy.net_into_curve),
            "state_before": fill_state.as_dict(),
            "state_after": buy.next_state.as_dict(),
            "core_price_impact_bps": buy.core_price_impact_bps,
            "all_in_price_impact_bps": buy.all_in_price_impact_bps,
            "gas_wei": str(GAS_BUY),
        }

        others = []
        if rnd:
            for c in rnd["context"]:
                if c["token"] == ex["token"]:
                    continue
                others.append({"token": c["token"], "status": c["status"],
                               "age_s": c["age_s"], "trades_2m": c.get("trades_2m"),
                               "raw": c.get("raw"),
                               "normalized": {f: math.tanh(c["raw"][f] / SCALES[f])
                                              for f in FEATURES} if c.get("raw") else None})
            stable = {c["symbol"]: c["stable_id"] for c in rnd["candidates"]}
            for o in others:
                o["stable_id"] = stable.get(o["token"])
                o["score"] = (rnd.get("scores") or {}).get(str(o["stable_id"]))
        row["other_candidates"] = others
        row["round_scores"] = rnd.get("scores") if rnd else None
        row["round_selected_stable_id"] = rnd.get("selected_stable_id") if rnd else None
        row["round_considered"] = rnd.get("considered") if rnd else None
        row["round_admitted"] = rnd.get("admitted") if rnd else None
        row["round_rotated"] = rnd.get("rotated") if rnd else None

        oc = outcomes.get(ep)
        if oc is None:
            row["settled"] = False
            row["unresolved"] = [u for u in unresolved
                                 if u.get("episode_id") == ep]
            out.append(row)
            continue
        row["settled"] = True
        exit_ts = oc["exit"]["ts"]
        row["exit_ts"] = exit_ts
        row["exit_block"] = oc["exit_block"]
        row["close_reason"] = oc["close_reason"]
        row["confirmation"] = oc.get("confirmation")

        # --- external activity during the hold
        during = [e for e in trades
                  if ex["market_ts"] < e["block_timestamp"] <= exit_ts]
        row["external_trades_during"] = len(during)
        row["external_buys_during"] = sum(1 for e in during if e["event"] == "CurveBuy")
        row["external_sells_during"] = sum(1 for e in during if e["event"] == "CurveSell")
        row["external_net_flow_during_wei"] = sum(flow_of(e) for e in during)

        # --- the sell leg, re-quoted at the exit block on the carried state
        # the loop's own path: the *market* tape is advanced by the external
        # events, and our own delta is carried onto it at quote time. The
        # reconstruction's constant-product check is therefore always applied
        # to the market-only state, never to one holding our paper position.
        market_tape, used = advance(fill_state.with_snipe(0), evs,
                                    ex["market_ts"], exit_ts,
                                    launch_block=ctx["launch_block"],
                                    launched_at=ctx["launched_at"])
        sell_state = carry(market_tape, buy.net_into_curve, buy.tokens_out)
        sell = quote_curve_sell(sell_state, buy.tokens_out)
        row["sell"] = {
            "block": oc["exit_block"], "ts": exit_ts,
            "tokens_in_wei": str(sell.tokens_in),
            "gross_quote_out_wei": str(sell.gross_quote_out),
            "fee_base_wei": str(sell.fee_base),
            "fee_creator_wei": str(sell.fee_creator),
            "quote_out_wei": str(sell.quote_out),
            "state_used": sell_state.as_dict(),
            "market_only_state": market_tape.as_dict(),
            "post_buy_state": buy.next_state.as_dict(),
            "carry_equals_post_buy_plus_external": {
                "post_buy_quote": str(buy.next_state.quote_reserve),
                "external_quote_delta": str(market_tape.quote_reserve
                                            - fill_state.quote_reserve),
                "sum": str(buy.next_state.quote_reserve + market_tape.quote_reserve
                           - fill_state.quote_reserve),
                "state_used_quote": str(sell_state.quote_reserve),
                "equal": (buy.next_state.quote_reserve + market_tape.quote_reserve
                          - fill_state.quote_reserve) == sell_state.quote_reserve,
            },
            "gas_wei": str(GAS_SELL + GAS_APPROVAL),
            "events_applied_between_fill_and_exit": len(used),
        }

        # --- the counterfactual: the same sell on the market-only state
        try:
            alt = quote_curve_sell(market_tape, buy.tokens_out)
            row["sell_market_only"] = {
                "quotable": True,
                "gross_quote_out_wei": str(alt.gross_quote_out),
                "quote_out_wei": str(alt.quote_out),
                "delta_quote_out_wei": str(sell.quote_out - alt.quote_out),
                "delta_quote_out_eth": (sell.quote_out - alt.quote_out) / WEI,
            }
        except Exception as exc:                    # the honest answer, reported
            gross_needed = (buy.tokens_out * market_tape.quote_reserve
                            // (market_tape.token_reserve + buy.tokens_out))
            row["sell_market_only"] = {
                "quotable": False,
                "code": getattr(exc, "code", type(exc).__name__),
                "gross_needed_wei": str(gross_needed),
                "market_only_real_quote_reserve_wei": str(
                    market_tape.real_quote_reserve),
                "shortfall_wei": str(gross_needed - market_tape.real_quote_reserve),
                "shortfall_eth": (gross_needed - market_tape.real_quote_reserve) / WEI,
                "own_quote_in_the_reserve_wei": str(buy.net_into_curve),
            }

        # --- money, three ways
        gas_total = GAS_BUY + GAS_SELL + GAS_APPROVAL
        net_wei = sell.quote_out - buy.spent - gas_total
        row["money"] = {
            "gas_buy_wei": str(GAS_BUY), "gas_sell_wei": str(GAS_SELL),
            "gas_approval_wei": str(GAS_APPROVAL), "gas_total_wei": str(gas_total),
            "recomputed_net_eth": net_wei / WEI,
            "logged_net_pnl_eth": oc["net_pnl"],
            "logged_gross_pnl_eth": oc["gross_pnl"],
            "logged_gross_reference_pnl_eth": oc["gross_reference_pnl"],
            "logged_fees_eth": oc["fees"],
            "logged_slippage_eth": oc["slippage"],
            "identity_gross_ref_minus_slip_minus_fees": round(
                oc["gross_reference_pnl"] - oc["slippage"] - oc["fees"], 12),
            "fees_recomputed_eth": (
                (buy.fee_base + buy.fee_creator + buy.fee_snipe + GAS_BUY
                 + sell.fee_base + sell.fee_creator + GAS_SELL + GAS_APPROVAL) / WEI),
            "return_on_notional": oc["return_on_notional"],
        }

        ev = learning.get(ep)
        r = oc["return_on_notional"]
        row["reinforcement"] = {
            "raw_return_on_notional": r,
            "pre_clip_amount": abs(r) / 0.01,
            "applied_amount": ev["amount"] if ev else None,
            "valence": ev["valence"] if ev else None,
            "synapses_depressed": ev["synapses_depressed"] if ev else None,
            "depressed_per_replicate": ev["depressed_per_replicate"] if ev else None,
            "accepted": ev["accepted"] if ev else None,
            "at_cap": bool(ev and abs(ev["amount"] - 1.0) < 1e-12),
        }

        out.append(row)
    return out


# ------------------------------------------------------- B.1 lifetimes
def quantiles(xs):
    xs = sorted(xs)
    if not xs:
        return {}
    def q(p):
        if len(xs) == 1:
            return xs[0]
        i = p * (len(xs) - 1)
        lo, hi = int(math.floor(i)), int(math.ceil(i))
        return xs[lo] + (xs[hi] - xs[lo]) * (i - lo)
    return {"n": len(xs), "min": xs[0], "p25": q(0.25), "median": q(0.50),
            "p75": q(0.75), "p90": q(0.90), "max": xs[-1]}


def replay_v1_last_event():
    """The number the '26–35 s median' came from, recomputed on d10-replay-v1."""
    d = ROOT / "data/pons/d10-replay-v1"
    manifest = json.loads((d / "MANIFEST.json").read_text())
    windows = manifest["windows"]
    launches, last_event, last_trade = {}, {}, {}
    curve_of = {}
    with open(d / "events.jsonl", encoding="utf-8") as fh:
        for line in fh:
            e = json.loads(line)
            if e.get("status") != "OK":
                continue
            tok = e.get("token")
            if not tok:
                continue
            if e.get("source") == "factory" and e.get("event") == "TokenLaunched":
                launches.setdefault(tok, e)
                curve_of[tok] = e.get("curve")
            elif e.get("source") == "curve":
                ts = e["block_timestamp"]
                last_event[tok] = max(last_event.get(tok, ts), ts)
                if e["event"] in TRADES:
                    last_trade[tok] = max(last_trade.get(tok, ts), ts)
    states = json.loads((d / "initial_states.json").read_text())
    out = {"windows": windows, "by_window": {}}
    for w in windows:
        ages_ev, ages_tr = [], []
        for tok, rec in states.items():
            launched = int(rec["launched_at"])
            if not (w["from_block"] <= int(rec["launch_block"]) < w["launch_end_exclusive"]):
                continue
            if tok in last_event:
                ages_ev.append(last_event[tok] - launched)
            if tok in last_trade:
                ages_tr.append(last_trade[tok] - launched)
        out["by_window"][w["label"]] = {
            "tokens_with_an_event": len(ages_ev),
            "last_event_age_s": quantiles(ages_ev),
            "tokens_with_a_trade": len(ages_tr),
            "last_trade_age_s": quantiles(ages_tr),
        }
    return out


def backfill_lifetimes(store: Path, *, admission_last_ts=None,
                       coverage_end_ts=None, label=""):
    by_curve, launches = read_events(store)
    rows = []
    for token, launch in launches.items():
        if str(launch.get("quote_asset") or "").lower() != "0x" + "0" * 40:
            continue
        launched = int(launch["block_timestamp"])
        if admission_last_ts is not None and launched > admission_last_ts:
            continue
        curve = launch.get("curve")
        trades = [e for e in by_curve.get(curve, []) if e["event"] in TRADES]
        last = max((e["block_timestamp"] for e in trades), default=None)
        rows.append({
            "token": token, "launched_at": launched,
            "n_trades": len(trades),
            "last_trade_age_s": None if last is None else last - launched,
            "follow_s": coverage_end_ts - launched,
            "still_trading_at_the_end": (last is not None
                                         and coverage_end_ts - last <= 60),
        })
    uncensored = [r for r in rows if r["follow_s"] >= 900]
    censored = [r for r in rows if r["follow_s"] < 900]
    traded = [r for r in uncensored if r["last_trade_age_s"] is not None]
    ages = [r["last_trade_age_s"] for r in traded]
    cohort = len(uncensored)
    def frac(limit):
        if not cohort:
            return None
        quiet = sum(1 for r in uncensored
                    if r["last_trade_age_s"] is None or r["last_trade_age_s"] <= limit)
        return {"n": quiet, "of": cohort, "fraction": quiet / cohort}
    return {
        "label": label,
        "native_launches_considered": len(rows),
        "no_trade_after_60s_whole_cohort": frac(60),
        "no_trade_after_300s_whole_cohort": frac(300),
        "no_trade_after_900s_whole_cohort": frac(900),
        "with_at_least_15_min_of_follow": len(uncensored),
        "cut_by_the_end_of_the_collection": len(censored),
        "uncensored_with_no_trade_at_all": len(uncensored) - len(traded),
        "uncensored_with_a_trade": len(traded),
        "last_trade_age_s": quantiles(ages),
        "fraction_no_trade_after_60s": (
            sum(1 for a in ages if a <= 60) / len(ages)) if ages else None,
        "fraction_no_trade_after_300s": (
            sum(1 for a in ages if a <= 300) / len(ages)) if ages else None,
        "fraction_no_trade_after_900s": (
            sum(1 for a in ages if a <= 900) / len(ages)) if ages else None,
        "still_trading_within_60s_of_the_window_end": sum(
            1 for r in traded if r["still_trading_at_the_end"]),
        "trades_per_token": quantiles([r["n_trades"] for r in uncensored]),
    }


# ---------------------------------------------- B.2 the quiet stimulus
def rates_for(normalized: dict) -> dict:
    """``MarketToSensoryEncoder.rates`` from the declared channel map."""
    w, orns = {}, {}
    for ch in CHANNELS:
        x = max(-1.0, min(1.0, float(normalized[ch["feature"]])))
        w[ch["positive"]] = CARRIER + (1 - CARRIER) * max(0.0, x)
        w[ch["negative"]] = CARRIER + (1 - CARRIER) * max(0.0, -x)
        orns[ch["positive"]] = ch["pos_orns"]
        orns[ch["negative"]] = ch["neg_orns"]
    load = sum(v * orns[g] for g, v in w.items())
    k = BUDGET / load
    return {g: min(DRIVE_MAX, k * v) for g, v in w.items()}


def check_encoder_against_a_log() -> dict:
    """Reproduce one logged DECISION's stimulus from the config's channel map."""
    log = read_log(BRANCHES["learning"])
    dec = next(r for r in log if r.get("kind") == "DECISION")
    mine = rates_for(dec["observation"]["normalized"])
    theirs = dec["stimulus"]["rates_hz"]
    worst = max(abs(mine[g] - theirs[g]) for g in theirs)
    return {"decision_episode_id": dec["episode_id"],
            "max_abs_difference_hz": worst, "reproduced": worst < 5e-4}


def quiet_stimuli(token: str = None, extra_cutoff: int = 0) -> dict:
    """One real token, its own tape, at a quiet-10-s and a quiet-2-min cutoff."""
    store = ROOT / "data/pons/d10-backfill-v1"
    by_curve, launches = read_events(store)
    states = json.loads((store / "initial_states.json").read_text())
    from flytrade.pons.context import TokenTape
    coverage_end = 1789185205
    chosen = None
    for tok, rec in sorted(states.items()):
        curve = rec["curve"]
        trades = [e for e in by_curve.get(curve, []) if e["event"] in TRADES]
        if len(trades) < 3:
            continue
        launched = int(rec["launched_at"])
        last = trades[-1]["block_timestamp"]
        if last - launched < 60 or coverage_end - last < 300:
            continue
        if token and tok != token:
            continue
        chosen = (tok, rec, curve, trades)
        break
    tok, rec, curve, trades = chosen
    st = rec["state"]
    tape = TokenTape(
        token=tok, curve=curve, launch_block=int(rec["launch_block"]),
        launched_at=int(rec["launched_at"]), initial=state_from(st),
        snipe_start_bps=int(rec["snipe_start_bps"]),
        snipe_window_seconds=int(rec["snipe_window_seconds"]),
        coverage_end_ts=coverage_end)
    for e in by_curve[curve]:
        tape.apply(e)
    last_trade_ts = trades[-1]["block_timestamp"]
    out = {"token": tok, "curve": curve,
           "launched_at": int(rec["launched_at"]),
           "last_trade_ts": last_trade_ts,
           "n_trades": len(trades), "cases": []}
    cases = [("quiet_10s", last_trade_ts + 10),
             ("quiet_2min", last_trade_ts + 120),
             ("quiet_2min_plus_30s", last_trade_ts + 150)]
    if extra_cutoff:
        cases.append((f"the_run_s_own_decision_cutoff", int(extra_cutoff)))
    for label, cutoff in cases:
        ctx = tape.context(cutoff)
        raw = {f: float(ctx.raw.get(f, 0.0)) for f in FEATURES}
        norm = {f: math.tanh(raw[f] / SCALES[f]) for f in FEATURES}
        out["cases"].append({
            "label": label, "cutoff_ts": cutoff, "status": ctx.status.value,
            "age_s": ctx.age_s, "trades_2m": ctx.trades_2m,
            "seconds_since_last_trade": cutoff - last_trade_ts,
            "raw": raw, "normalized": norm, "rates_hz": rates_for(norm)})
    a, b = out["cases"][0]["rates_hz"], out["cases"][1]["rates_hz"]
    out["per_channel_difference_hz_10s_to_2min"] = {g: b[g] - a[g] for g in a}
    out["identical"] = all(abs(b[g] - a[g]) < 1e-9 for g in a)
    return out


# ------------------------------------------------- B.4 reinforcement
def reinforcement_census() -> dict:
    rows, at_cap = [], 0
    for branch, path in BRANCHES.items():
        log = read_log(path)
        outcomes = {r["episode_id"]: r for r in log if r.get("kind") == "OUTCOME"}
        for ev in [r for r in log if r.get("kind") == "LEARNING"]:
            oc = outcomes.get(ev["episode_id"], {})
            r = oc.get("return_on_notional")
            rows.append({"branch": branch, "episode_id": ev["episode_id"],
                         "raw_return_on_notional": r,
                         "pre_clip_amount": None if r is None else abs(r) / 0.01,
                         "applied_amount": ev["amount"], "valence": ev["valence"],
                         "synapses_depressed": ev["synapses_depressed"]})
            if abs(ev["amount"] - 1.0) < 1e-12:
                at_cap += 1
    absr = [abs(x["raw_return_on_notional"]) for x in rows
            if x["raw_return_on_notional"] is not None]
    return {"records": rows, "n": len(rows), "at_cap": at_cap,
            "reinforce_full_scale": 0.01, "reinforce_cap": 1.0,
            "abs_return_quantiles": quantiles(absr),
            "n_abs_return_above_full_scale": sum(1 for a in absr if a >= 0.01),
            "frozen_learning_records": sum(
                1 for r in read_log(BRANCHES["frozen_reference"])
                if r.get("kind") == "LEARNING")}


# --------------------------------------------------------- C. the ledger
def ledger() -> dict:
    led = json.loads((D10 / "rpc_ledger.json").read_text())
    by_run = led["by_run"]
    total_attempts = sum(v["attempts"] for v in by_run.values())
    total_units = sum(v["units"] for v in by_run.values())
    return {"ledger": led,
            "sum_of_runs_attempts": total_attempts,
            "sum_of_runs_units": total_units,
            "ledger_attempts": led["attempts"], "ledger_units": led["units"],
            "consistent": (total_attempts == led["attempts"]
                           and total_units == led["units"])}


# --------------------------------------------------- D. replay vs live
def decision_mix() -> dict:
    out = {}
    for branch, path in BRANCHES.items():
        log = read_log(path)
        per_candidate, per_round, statuses = Counter(), Counter(), Counter()
        for d in [r for r in log if r.get("kind") == "DECISION"]:
            per_candidate[d["decoded_action"]] += 1
            statuses[d["readout_status"]] += 1
        rounds = [r for r in log if r.get("kind") == "ROUND"]
        for r in rounds:
            sel = r.get("selected_stable_id")
            if sel is None:
                continue
        summary = json.loads(
            (path.parent.parent / "summary.json").read_text())
        out[branch] = {
            "decisions_per_candidate": dict(per_candidate),
            "decisions_per_candidate_total": sum(per_candidate.values()),
            "readout_statuses": dict(statuses),
            "rounds": len(rounds),
            "learning_events": sum(1 for r in log if r.get("kind") == "LEARNING"),
            "executions": sum(1 for r in log if r.get("kind") == "EXECUTION"),
            "outcomes": sum(1 for r in log if r.get("kind") == "OUTCOME"),
            "discoveries": sum(1 for r in log if r.get("kind") == "DISCOVERY"),
            "summary_keys": sorted(summary)[:0],
        }
    return out


def main() -> int:
    result = {
        "A_episodes": {b: episodes(b) for b in BRANCHES},
        "B1_replay_v1_last_event": replay_v1_last_event(),
        "B1_backfill": backfill_lifetimes(
            ROOT / "data/pons/d10-backfill-v1",
            admission_last_ts=1789184256, coverage_end_ts=1789185205,
            label="d10-backfill-v1, native ETH, launched in the first 120 min"),
        "B1_live": backfill_lifetimes(
            D10 / "runs/d10-live-001/chain",
            admission_last_ts=1789197934, coverage_end_ts=1789198834,
            label="d10-live-001 chain store, native ETH, launched with >= 15 min of follow"),
        "B2_encoder_check": check_encoder_against_a_log(),
        "B2_quiet": quiet_stimuli(extra_cutoff=1789181976),
        "B4_reinforcement": reinforcement_census(),
        "C_ledger": ledger(),
        "D_decisions": decision_mix(),
    }
    print(json.dumps(result, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
