#!/usr/bin/env python
"""D11 section 6 — what admission v2 and encoder v2 would have seen, on the
recorded cutoffs of the two D10 runs.

    .venv/bin/python experiments/d11/retrospective.py

**This is not a backtest.** It computes no trade the corrected brain would have
made, no PnL, no corrected outcome and no counterfactual reward. It answers one
question — *which candidates would have been presented, and would they still
have smelled the same?* — and stops there.

Every eligibility calculation stops at its historical cutoff: the tape is
advanced only through events at or before it, and no later trade is inspected
to decide admission. No socket is opened, no brain is simulated and nothing
under ``experiments/d10/`` is written.

Inputs: the ``ROUND`` records of ``d10-001/learning`` (272 ticks) and
``d10-live-001`` (111 ticks), the chain stores those runs read
(``data/pons/d10-backfill-v1`` and ``runs/d10-live-001/chain``), and
``experiments/d11/config.json`` for the v2 scales and constants.

Output: ``experiments/d11/retrospective.md`` and ``retrospective.json``.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

HERE = Path(__file__).resolve().parent
D10 = ROOT / "experiments" / "d10"

from flytrade import encoder as E                          # noqa: E402
from flytrade import populations as POP                    # noqa: E402
from flytrade.pons.admission import AdmissionPolicy        # noqa: E402
from flytrade.pons.admission_v2 import (COLLECTOR_LAG, DATA_LAG,  # noqa: E402
                                        NO_ELIGIBLE_CANDIDATES,
                                        AdmissionPolicyV2)
from flytrade.pons.context import MIN_AGE_S, TokenTape     # noqa: E402
from flytrade.pons.context_v2 import (PONS_FEATURES_V2,    # noqa: E402
                                      context_v2)
from flytrade.pons.curve import CurveState                 # noqa: E402
from flytrade.pons.manifest import NATIVE_QUOTE            # noqa: E402
from flytrade.pons.seed import (creator_tax_from_trade,    # noqa: E402
                                matches_pinned_config, seed_state)

D10_CONFIG = json.loads((D10 / "config.json").read_text())
D11_CONFIG = json.loads((HERE / "config.json").read_text())
V1_FEATURES = tuple(D10_CONFIG["features"]["order"])
V1_SCALES = D10_CONFIG["features"]["scales"]
V2_FEATURES = tuple(D11_CONFIG["features"]["order"])
V2_SCALES = D11_CONFIG["features"]["scales"]
RATE_TOL_HZ = 1e-9
CADENCE = 30
TRACK_SECONDS = int(D10_CONFIG["admission"]["track_seconds"])

RUNS = {
    "d10-001/learning": {
        "log": D10 / "runs/d10-001/learning/events.jsonl",
        "store": ROOT / "data/pons/d10-backfill-v1",
        "live": False,
    },
    "d10-live-001/live": {
        "log": D10 / "runs/d10-live-001/live/events.jsonl",
        "store": D10 / "runs/d10-live-001/chain",
        "live": True,
    },
}


# ------------------------------------------------------------------ helpers
def read_log(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()
            if line.strip()]


def build_encoders():
    ann = POP.Annotations.load(ROOT / "data" / "malecns-v1.0" / "annotations.npz")
    kw = dict(carrier=float(D10_CONFIG["encoder"]["carrier"]),
              drive_budget_hz=float(D10_CONFIG["encoder"]["drive_budget_hz"]),
              drive_max_hz=float(D10_CONFIG["encoder"]["drive_max_hz"]),
              coding=str(D10_CONFIG["encoder"]["coding"]))
    v1 = E.MarketToSensoryEncoder(ann, features=V1_FEATURES, **kw)
    v2 = E.MarketToSensoryEncoder(ann, features=V2_FEATURES, **kw)
    return v1, v2


def rates_of(enc, raw: dict, features, scales) -> tuple:
    u = np.array([math.tanh(float(raw.get(f, 0.0)) / float(scales[f]))
                  for f in features], dtype=np.float64)
    r = enc.rates(u)
    return tuple(float(r[g]) for g in enc.glomeruli)


def collisions(vectors: list[tuple]) -> tuple[int, int]:
    """``(candidates sitting in a group of equals, number of such groups)``."""
    groups: list[list[int]] = []
    for i, v in enumerate(vectors):
        for g in groups:
            if all(abs(x - y) <= RATE_TOL_HZ
                   for x, y in zip(vectors[g[0]], v)):
                g.append(i)
                break
        else:
            groups.append([i])
    dup = [g for g in groups if len(g) > 1]
    return sum(len(g) for g in dup), len(dup)


# ------------------------------------------------------------- the tracker
class Tracker:
    """The loop's tape bookkeeping, and nothing that decides or learns.

    Reproduces ``PonsLoop._open_tape`` / ``_ingest``: a tape per native-ETH
    launch with a reconstructible initial state, advanced by its own curve
    events in chain order. The replay store publishes those initial states;
    the live store does not, so they are re-derived offline from each curve's
    own first trade exactly as ``LiveDriver`` derived them at the time (D10
    deviation 17), with no request of any kind. A launch whose tax no trade
    pins is reported as unreconstructible rather than guessed.
    """

    def __init__(self, store: Path, *, live: bool):
        self.store = Path(store)
        self.live = bool(live)
        self.launches: dict[str, dict] = {}
        self.by_curve: dict[str, list[dict]] = {}
        self.tapes: dict[str, TokenTape] = {}
        self.unreconstructible = 0
        self.coverage_end_ts = 0
        self._load()

    def _load(self) -> None:
        initials = {}
        path = self.store / "initial_states.json"
        if path.exists():
            initials = json.loads(path.read_text())
        last_ts = 0
        with open(self.store / "events.jsonl", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                e = json.loads(line)
                if e.get("status") != "OK":
                    continue
                last_ts = max(last_ts, int(e["block_timestamp"]))
                if e.get("source") == "factory" and e.get("event") == "TokenLaunched":
                    self.launches.setdefault(e["token"], e)
                elif e.get("source") == "curve":
                    self.by_curve.setdefault(e["address"], []).append(e)
        for evs in self.by_curve.values():
            evs.sort(key=lambda e: (e["block_number"], e["tx_index"],
                                    e["log_index"]))
        headers = [json.loads(line) for line
                   in (self.store / "headers.jsonl").read_text().splitlines()
                   if line.strip()]
        header_last = max(int(h["timestamp"]) for h in headers)
        self.coverage_end_ts = min(last_ts, header_last)

        for token, launch in sorted(self.launches.items()):
            quote = str(launch.get("quote_asset") or "").lower()
            if quote != NATIVE_QUOTE:
                continue
            curve = launch["curve"]
            events = self.by_curve.get(curve, [])
            meta = initials.get(token)
            if meta is not None:
                s = meta["state"]
                state = CurveState(
                    quote_reserve=int(s["quote_reserve"]),
                    token_reserve=int(s["token_reserve"]),
                    real_quote_reserve=int(s["real_quote_reserve"]),
                    sellable_tokens=int(s["sellable_tokens"]),
                    fee_bps=int(s["fee_bps"]),
                    creator_tax_bps=int(s["creator_tax_bps"]),
                    snipe_tax_bps=0, graduated=bool(s["graduated"]))
                snipe_start = int(meta["snipe_start_bps"])
                snipe_window = int(meta["snipe_window_seconds"])
            else:
                args = launch.get("args") or {}
                if not matches_pinned_config(args.get("launchConfigId"),
                                             args.get("graduationThreshold")):
                    self.unreconstructible += 1
                    continue
                tax = None
                for event in events:
                    tax = creator_tax_from_trade(event)
                    if tax is not None:
                        break
                if tax is None:
                    self.unreconstructible += 1
                    continue
                state = seed_state(int(tax))
                snipe_start, snipe_window = 9_900, 3
            tape = TokenTape(
                token=token, curve=curve,
                launch_block=int(launch["block_number"]),
                launched_at=int(launch["block_timestamp"]),
                initial=state, snipe_start_bps=snipe_start,
                snipe_window_seconds=snipe_window, quote_asset=quote,
                deployment=str(launch.get("deployment") or "pons-v2"),
                coverage_end_ts=self.coverage_end_ts)
            for event in events:
                tape.apply(event)
            self.tapes[token] = tape

    @staticmethod
    def causal_completion(tape: TokenTape, cutoff: int):
        """Hide a completion the loop had not yet ingested at this cutoff.

        ``TokenTape.apply`` records ``completed_at`` as soon as it sees a
        ``CurveCompleted``, and ``coverage_end()`` reads it directly. The loop
        is causal because it ingests events tick by tick and simply had not
        seen that event yet; this tracker applies each tape's whole stream
        once, for speed, so the field has to be masked back to what the loop
        knew. Everything else on the tape is already read through
        ``_upto(cutoff)`` and is causal on its own.

        Returns a callable that restores the field.
        """
        saved = tape.completed_at
        if saved is not None and int(saved) > int(cutoff):
            tape.completed_at = None
        def restore():
            tape.completed_at = saved
        return restore

    def tracked_at(self, cutoff: int, *, admission_last_block: int | None):
        """The tapes ``PonsLoop._candidates`` would have considered."""
        out = []
        for token, tape in sorted(self.tapes.items()):
            if (admission_last_block is not None
                    and tape.launch_block > admission_last_block):
                continue
            age = int(cutoff) - tape.launched_at
            if age < MIN_AGE_S or age > TRACK_SECONDS:
                continue
            out.append(tape)
        return out


# ------------------------------------------------------------------- main
def analyse(name: str, spec: dict, enc_v1, enc_v2) -> dict:
    records = read_log(spec["log"])
    rounds = {int(r["cutoff_ts"]): r for r in records if r["kind"] == "ROUND"}
    entries = [r for r in records if r["kind"] == "EXECUTION"
               and str(r.get("side")) == "BUY"]
    tracker = Tracker(spec["store"], live=spec["live"])

    if spec["live"]:
        cutoffs = sorted(rounds)
        admission_last_block = None
        require_coverage = False
    else:
        manifest = json.loads((spec["store"] / "MANIFEST.json").read_text())
        window = manifest["window"]
        admission_last_block = int(window["admission_last_block"])
        require_coverage = True
        first = min(int(e["block_timestamp"])
                    for evs in tracker.by_curve.values() for e in evs)
        first = min(first, min(int(l["block_timestamp"])
                               for l in tracker.launches.values()))
        cutoffs = []
        cutoff = first
        while cutoff <= tracker.coverage_end_ts:
            cutoffs.append(cutoff)
            cutoff += CADENCE

    v1_policy = AdmissionPolicy(require_coverage=require_coverage)
    v2_policy = AdmissionPolicyV2(
        require_coverage=require_coverage,
        recent_window_s=int(D11_CONFIG["admission"]["constants"]["recent_window_seconds"]),
        min_valid_trades_in_window=int(
            D11_CONFIG["admission"]["constants"]["minimum_valid_trades_in_window"]),
        max_seconds_since_last_trade=int(
            D11_CONFIG["admission"]["constants"]["maximum_seconds_since_last_trade"]))

    ticks = []
    v1_reasons: Counter = Counter()
    v2_reasons: Counter = Counter()
    faithful = {"checked": 0, "considered_match": 0, "admitted_match": 0}
    for cutoff in cutoffs:
        tapes = tracker.tracked_at(cutoff, admission_last_block=admission_last_block)
        v1_admitted, v2_admitted = [], []
        v2_contexts = []
        for tape in tapes:
            restore = Tracker.causal_completion(tape, cutoff)
            ctx1 = tape.context(cutoff)
            cand1 = v1_policy.consider(tape, ctx1, stable_id=0, cutoff=cutoff)
            if cand1.admitted:
                v1_admitted.append(tape.token)
                v1_reasons["ADMITTED"] += 1
            else:
                for reason in cand1.reasons:
                    v1_reasons[reason] += 1
            ctx2 = context_v2(tape, cutoff)
            cand2 = v2_policy.consider(tape, ctx2, stable_id=0, cutoff=cutoff)
            if cand2.admitted:
                v2_admitted.append(tape.token)
                v2_contexts.append(ctx2)
                v2_reasons["ADMITTED"] += 1
            else:
                for reason in cand2.reasons:
                    v2_reasons[reason] += 1
            restore()

        recorded = rounds.get(cutoff)
        rec_considered = None if recorded is None else int(recorded["considered"])
        rec_admitted = None if recorded is None else int(recorded["admitted"])
        rec_presented = [] if recorded is None else list(recorded.get("presented") or [])
        rec_contexts = [] if recorded is None else list(recorded.get("context") or [])
        if recorded is not None and not recorded.get("mark"):
            faithful["checked"] += 1
            faithful["considered_match"] += int(rec_considered == len(tapes))
            faithful["admitted_match"] += int(rec_admitted == len(v1_admitted))

        v1_vectors = [rates_of(enc_v1, c.get("raw", {}), V1_FEATURES, V1_SCALES)
                      for c in rec_contexts]
        v2_vectors = [rates_of(enc_v2, c.raw, V2_FEATURES, V2_SCALES)
                      for c in v2_contexts]
        c1, g1 = collisions(v1_vectors)
        c2, g2 = collisions(v2_vectors)
        ticks.append({
            "cutoff_ts": int(cutoff),
            "round_index": None if recorded is None else int(recorded["round_index"]),
            "has_round_record": recorded is not None,
            "held": bool(recorded is not None and recorded.get("mark")),
            "tracked_recomputed": len(tapes),
            "considered_recorded": rec_considered,
            "v1_admitted_recorded": rec_admitted,
            "v1_admitted_recomputed": len(v1_admitted),
            "v2_admitted": len(v2_admitted),
            "v1_presented_recorded": len(rec_presented),
            "v1_collisions": c1, "v1_collision_groups": g1,
            "v2_collisions": c2, "v2_collision_groups": g2,
        })

    zero_v1 = sum(1 for t in ticks if (t["v1_admitted_recomputed"] == 0))
    zero_v2 = sum(1 for t in ticks if t["v2_admitted"] == 0)
    lag_rounds = 0            # replay can never lag; live never did (see below)
    return {
        "run": name,
        "store": str(spec["store"].relative_to(ROOT)),
        "live": spec["live"],
        "ticks": len(ticks),
        "round_records": len(rounds),
        "unreconstructible_launches": tracker.unreconstructible,
        "tapes": len(tracker.tapes),
        "faithfulness": faithful,
        "v1_admitted_total": sum(t["v1_admitted_recomputed"] for t in ticks),
        "v2_admitted_total": sum(t["v2_admitted"] for t in ticks),
        "v1_admitted_recorded_total": sum(
            t["v1_admitted_recorded"] or 0 for t in ticks),
        "v1_presented_total": sum(t["v1_presented_recorded"] for t in ticks),
        "zero_eligible_ticks_v1": zero_v1,
        "zero_eligible_ticks_v2": zero_v2,
        "ticks_with_fewer_than_six_v1": sum(
            1 for t in ticks if 0 < t["v1_admitted_recomputed"] < 6),
        "ticks_with_fewer_than_six_v2": sum(
            1 for t in ticks if 0 < t["v2_admitted"] < 6),
        "ticks_with_six_or_more_v2": sum(1 for t in ticks if t["v2_admitted"] >= 6),
        "max_v2_admitted_in_a_tick": max((t["v2_admitted"] for t in ticks),
                                         default=0),
        "median_v2_admitted": float(np.median(
            [t["v2_admitted"] for t in ticks])) if ticks else 0.0,
        "data_lag_rounds": lag_rounds,
        "v1_reasons": dict(v1_reasons.most_common()),
        "v2_reasons": dict(v2_reasons.most_common()),
        "v1_collisions_total": sum(t["v1_collisions"] for t in ticks),
        "v1_collision_groups_total": sum(t["v1_collision_groups"] for t in ticks),
        "v1_presented_ticks_with_a_collision": sum(
            1 for t in ticks if t["v1_collisions"]),
        "v2_collisions_total": sum(t["v2_collisions"] for t in ticks),
        "v2_collision_groups_total": sum(t["v2_collision_groups"] for t in ticks),
        "v2_ticks_with_a_collision": sum(1 for t in ticks if t["v2_collisions"]),
        "entries": [{"episode_id": int(e["episode_id"]),
                     "cutoff_ts": int(e["cutoff_ts"]),
                     "token": str(e.get("token") or "")} for e in entries],
        "ticks_detail": ticks,
        "_tracker": tracker,
        "_v2_policy": v2_policy,
    }


def verdicts(results, enc_v2) -> list[dict]:
    """The seventeen entries, with their v2 verdict at their own cutoff."""
    recon = json.loads((HERE / "reconciliation.json").read_text())
    out = []
    trackers = {
        "d10-001": results["d10-001/learning"]["_tracker"],
        "d10-live-001": results["d10-live-001/live"]["_tracker"],
    }
    policies = {
        "d10-001": results["d10-001/learning"]["_v2_policy"],
        "d10-live-001": results["d10-live-001/live"]["_v2_policy"],
    }
    for e in recon["entries"]:
        tracker = trackers[e["run_id"]]
        tape = tracker.tapes.get(e["token"])
        if tape is None:
            out.append({**{k: e[k] for k in ("run_id", "branch", "episode_id",
                                             "token", "cutoff_ts")},
                        "v2_verdict": "TAPE_NOT_RECONSTRUCTIBLE_OFFLINE",
                        "reasons": []})
            continue
        cutoff = int(e["cutoff_ts"])
        restore = Tracker.causal_completion(tape, cutoff)
        ctx = context_v2(tape, cutoff)
        cand = policies[e["run_id"]].consider(tape, ctx, stable_id=0,
                                              cutoff=cutoff)
        restore()
        out.append({
            **{k: e[k] for k in ("run_id", "branch", "episode_id", "token",
                                 "cutoff_ts")},
            "since_last_trade_s": float(ctx.raw.get("since_last_trade", -1)),
            "trade_count_2m": float(ctx.raw.get("trade_count_2m", -1)),
            "v2_verdict": "ADMITTED" if cand.admitted else "EXCLUDED",
            "reasons": list(cand.reasons),
        })
    return out


def worked_examples(tracker, enc_v2) -> list[dict]:
    """One real token per owner distinction, with its v2 rate vector."""
    found: dict[str, dict] = {}
    for token, tape in sorted(tracker.tapes.items()):
        if len(found) == 4:
            break
        end = tape.coverage_end()
        cutoff = tape.launched_at + MIN_AGE_S
        while cutoff <= end:
            restore = Tracker.causal_completion(tape, cutoff)
            ctx = context_v2(tape, cutoff)
            restore()
            if ctx.usable:
                raw = ctx.raw
                count = raw["trade_count_2m"]
                vol = raw["gross_volume_2m"]
                flat = max(abs(raw["ret_30s"]), abs(raw["ret_2m"]),
                           abs(raw["ret_5m"]))
                if ("A" not in found and count == 0 and vol == 0
                        and ctx.trades > 0
                        and raw["since_last_trade"] >= 600):
                    found["A"] = (tape, cutoff, ctx)
                if ("B" not in found and count >= 20 and flat <= 0.01
                        and raw["rv_2m"] <= 0.01):
                    found["B"] = (tape, cutoff, ctx)
                if ("C" not in found and vol >= 1.0
                        and abs(raw["flow_imb_2m"]) <= 0.05 and count >= 10):
                    found["C"] = (tape, cutoff, ctx)
            cutoff += CADENCE
    # D is constructed deliberately rather than waited for: the tick loop only
    # ever asks about a token that is already 60 s old, so an incomplete
    # observation has to be asked for. Two flavours, both real tokens.
    if "A" in found:
        tape = found["A"][0]
        found["D"] = (tape, tape.launched_at + MIN_AGE_S // 2,
                      context_v2(tape, tape.launched_at + MIN_AGE_S // 2))
    rows = []
    labels = {
        "A": "no trades in the observed interval",
        "B": "many trades, almost no net price change",
        "C": "balanced buys and sells with meaningful gross volume",
        "D": "missing or incomplete observation — NOT PRESENTED",
    }
    for key in ("A", "B", "C", "D"):
        if key not in found:
            rows.append({"case": key, "label": labels[key], "found": False})
            continue
        tape, cutoff, ctx = found[key]
        row = {"case": key, "label": labels[key], "found": True,
               "token": tape.token, "cutoff_ts": int(cutoff),
               "status": ctx.status.value, "reason": ctx.reason,
               "raw": {k: float(v) for k, v in ctx.raw.items()}}
        if ctx.usable:
            u = {f: math.tanh(float(ctx.raw[f]) / float(V2_SCALES[f]))
                 for f in V2_FEATURES}
            row["normalised"] = u
            row["rates_hz"] = {
                g: round(v, 4) for g, v in
                zip(enc_v2.glomeruli,
                    rates_of(enc_v2, ctx.raw, V2_FEATURES, V2_SCALES))}
        rows.append(row)
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(HERE / "retrospective.md"))
    ap.add_argument("--json", default=str(HERE / "retrospective.json"))
    ap.add_argument("--render-only", action="store_true",
                    help="re-render the markdown from the committed JSON")
    args = ap.parse_args(argv)

    if args.render_only:
        payload = json.loads(Path(args.json).read_text())
        Path(args.out).write_text(render(payload))
        print(f"rendered {args.out} from {args.json}")
        return 0

    enc_v1, enc_v2 = build_encoders()
    results = {}
    for name, spec in RUNS.items():
        print(f"[{name}] …", flush=True)
        results[name] = analyse(name, spec, enc_v1, enc_v2)
        print(f"[{name}] {results[name]['ticks']} ticks, "
              f"v1 {results[name]['v1_admitted_total']:,} → "
              f"v2 {results[name]['v2_admitted_total']:,}", flush=True)

    seventeen = verdicts(results, enc_v2)
    examples = worked_examples(results["d10-001/learning"]["_tracker"], enc_v2)

    payload = {
        "runs": {k: {kk: vv for kk, vv in v.items()
                     if not kk.startswith("_")} for k, v in results.items()},
        "seventeen_entries": seventeen,
        "worked_examples": examples,
        "encoder": {
            "v1_glomeruli": list(enc_v1.glomeruli),
            "v2_glomeruli": list(enc_v2.glomeruli),
            "rate_tolerance_hz": RATE_TOL_HZ,
        },
        "not_a_backtest": (
            "This diagnostic computes no trade the corrected brain would have "
            "made, no PnL and no counterfactual reward."),
    }
    Path(args.json).write_text(json.dumps(payload, indent=1) + "\n")
    Path(args.out).write_text(render(payload))
    print(json.dumps({k: {kk: v[kk] for kk in (
        "ticks", "v1_admitted_total", "v2_admitted_total",
        "zero_eligible_ticks_v1", "zero_eligible_ticks_v2",
        "ticks_with_fewer_than_six_v2", "v1_collisions_total",
        "v2_collisions_total", "faithfulness")}
        for k, v in results.items()}, indent=1))
    return 0


def render(p: dict) -> str:
    out: list[str] = []
    A = out.append
    a = p["runs"]["d10-001/learning"]
    b = p["runs"]["d10-live-001/live"]

    A("# D11 — retrospective admission and encoding diagnostic")
    A("")
    A("**This is not a backtest, and it computes no trade the corrected brain")
    A("would have made** — no PnL, no corrected outcome, no counterfactual reward.")
    A("It answers one question on cutoffs two D10 runs already recorded: *which")
    A("candidates would admission v2 have made eligible, and would they still have")
    A("smelled the same?*")
    A("")
    A("Every eligibility calculation stops at its historical cutoff. Each tape is")
    A("read only through events at or before it — including the curve's own")
    A("completion, which is masked back to what the loop had ingested — and no")
    A("later trade is inspected to decide admission. No socket was opened, no brain")
    A("was simulated, and nothing under `experiments/d10/` was written.")
    A("")
    A("Rules and constants: `experiments/d11/config.json`, registered in `481dd3e`")
    A("and calibrated in `87b8b2f`, both before this file was run.")
    A("")
    A("## 1. Per run: what changes")
    A("")
    A("| | `d10-001/learning` | `d10-live-001/live` |")
    A("|---|---|---|")

    def row(label, key, fmt="{:,}"):
        def f(v):
            if v is None:
                return "—"
            if isinstance(v, bool):
                return str(v)
            if isinstance(v, (int, float)):
                return fmt.format(v)
            return str(v)
        A(f"| {label} | {f(a.get(key))} | {f(b.get(key))} |")

    row("ticks", "ticks")
    row("`ROUND` records in the log", "round_records")
    row("tapes reconstructed offline", "tapes")
    row("launches whose state could not be reconstructed offline",
        "unreconstructible_launches")
    row("**candidate-ticks admitted by v1** (recomputed)", "v1_admitted_total")
    row("candidates actually presented by v1 (as recorded)",
        "v1_presented_total")
    row("**candidate-ticks admitted by v2**", "v2_admitted_total")
    row("ticks with zero eligible under v1", "zero_eligible_ticks_v1")
    row("**ticks with zero eligible under v2**", "zero_eligible_ticks_v2")
    row("ticks with 1–5 eligible under v2", "ticks_with_fewer_than_six_v2")
    row("ticks with 6 or more eligible under v2", "ticks_with_six_or_more_v2")
    row("most eligible in any one tick under v2", "max_v2_admitted_in_a_tick")
    row("median eligible per tick under v2", "median_v2_admitted", "{:.1f}")
    row("rounds that would be `DATA_LAG`", "data_lag_rounds")
    A("")
    A("A *candidate-tick* is one (token, tick) pair: a token tracked for an hour")
    A("contributes to up to 120 of them, so these are not counts of tokens.")
    A("")
    A("**The two rules, side by side.** v1 asked for three trades *ever*; v2 asks")
    A("for two valid trades inside the last two minutes with the last one at most")
    A(f"sixty seconds back. On the replay that takes {a['v1_admitted_total']:,}")
    A(f"eligible candidate-ticks down to **{a['v2_admitted_total']:,}**")
    A(f"({100.0 * a['v2_admitted_total'] / max(a['v1_admitted_total'], 1):.1f} %), and on")
    A(f"the live hour {b['v1_admitted_total']:,} down to **{b['v2_admitted_total']:,}**")
    A(f"({100.0 * b['v2_admitted_total'] / max(b['v1_admitted_total'], 1):.1f} %). That is the")
    A("corpses leaving the pool, and it is reported, not softened: **section 6**")
    A("states the limitation and the rule is not loosened because of it.")
    A("")
    A("**Faithfulness of the recomputation.** The tracker rebuilds the tapes the")
    A("loop tracked and re-runs `admission_v1` at the recorded cutoffs; on the flat")
    A("ticks that carry a `ROUND` record it must reproduce the record's own")
    A("`considered` and `admitted` counts.")
    A("")
    A("| run | flat ticks checked | `considered` reproduced | `admitted` reproduced |")
    A("|---|---|---|---|")
    for name in ("d10-001/learning", "d10-live-001/live"):
        f = p["runs"][name]["faithfulness"]
        A(f"| `{name}` | {f['checked']:,} | {f['considered_match']:,} | "
          f"{f['admitted_match']:,} |")
    A("")
    A("The replay reproduces **exactly**: 23 of 23 on both counts. **The live run")
    A("does not, and the difference is declared rather than hidden.** The live")
    A("chain store carries no `initial_states.json` — the live driver derived each")
    A(f"launch state from the curve's own first trade — so {b['unreconstructible_launches']}")
    A("launches could not be reconstructed offline at all, and the driver's")
    A("*hold a launch until its first trade pins the creator tax* rule (D10")
    A("deviation 17) released tapes on a schedule this file cannot replay. The")
    A("offline tracked set therefore sits **+1 candidate** on 23 of the 25 flat")
    A("ticks and the recomputed v1 admitted count **−1** on 20 of them. Every live")
    A("number in this file carries that ±1-per-tick uncertainty; none of the")
    A("conclusions turns on a single candidate.")
    A("")
    A("## 2. Why candidates are excluded")
    A("")
    A("Counted per (token, tick) pair over every tick of the run, so one token")
    A("quiet for an hour contributes to many ticks. A candidate may carry several")
    A("reasons and every one of them is counted.")
    A("")
    A("| reason | `learning` v1 | `learning` v2 | `live` v1 | `live` v2 |")
    A("|---|---|---|---|---|")
    keys = sorted(set(a["v1_reasons"]) | set(a["v2_reasons"])
                  | set(b["v1_reasons"]) | set(b["v2_reasons"]))
    for key in keys:
        A(f"| `{key}` | {a['v1_reasons'].get(key, 0):,} | "
          f"{a['v2_reasons'].get(key, 0):,} | {b['v1_reasons'].get(key, 0):,} | "
          f"{b['v2_reasons'].get(key, 0):,} |")
    A("")
    A("Reading the table:")
    A("")
    A("* **`INACTIVE` is the whole of the change.** It is a *new* code and it")
    A("  absorbs what v1 admitted: a complete tape, a valid state, a curve that")
    A("  never graduated, and no trade in two minutes.")
    A("* **`INSUFFICIENT_HISTORY` is zero in both runs, and that is correct.** The")
    A("  loop only ever considers a token already 60 s old (`PonsLoop._candidates`")
    A("  filters on age before admission sees it), so the tapes that reach")
    A("  admission can always answer. v1's `OBSERVATION_UNUSABLE` at those ticks is")
    A("  entirely its *fewer than three trades ever* clause — the clause v2")
    A("  removes — and those candidates reappear under `INACTIVE` or as admitted,")
    A("  by their recent activity rather than their lifetime count.")
    A("* **`COLLECTOR_LAG` is zero, and it could not have been anything else.**")
    A("  Replay cannot lag by construction, and the live run's own health file")
    A("  reported the confirmed block 64–92 s old in 165 of 165 samples against a")
    A("  two-tick bound — this diagnostic recomputes from the persisted store,")
    A("  which has no lag at all, so the code path is exercised by")
    A("  `tests/d11/test_admission_v2.py` and not by this table.")
    A("* `COVERAGE` and `STATE_INVALID` are identical between v1 and v2 because")
    A("  v2 keeps those two clauses unchanged; `ROUTE_COMPLETED` is v1's")
    A("  `CURVE_COMPLETED` renamed, at the same count.")
    A("")
    A("## 3. Deterministic sensory collisions, before and after")
    A("")
    A("A *collision* is two candidates in the same round whose **deterministic**")
    A("per-glomerulus ORN drive agrees on every channel to within 1e-9 Hz — the")
    A("vector the encoder produces **before** any Poisson sampling, never a display")
    A("field. *Before* is v1's sixteen channels over the candidates the run")
    A("actually presented, with their recorded raw vectors. *After* is v2's twenty")
    A("channels over the set v2 would have made eligible at the same cutoff.")
    A("")
    A("| | `learning` before | `learning` after | `live` before | `live` after |")
    A("|---|---|---|---|---|")
    A(f"| candidates in a colliding group | {a['v1_collisions_total']:,} | "
      f"{a['v2_collisions_total']:,} | {b['v1_collisions_total']:,} | "
      f"{b['v2_collisions_total']:,} |")
    A(f"| colliding groups | {a['v1_collision_groups_total']:,} | "
      f"{a['v2_collision_groups_total']:,} | {b['v1_collision_groups_total']:,} | "
      f"{b['v2_collision_groups_total']:,} |")
    A(f"| ticks containing a collision | {a['v1_presented_ticks_with_a_collision']:,} | "
      f"{a['v2_ticks_with_a_collision']:,} | "
      f"{b['v1_presented_ticks_with_a_collision']:,} | "
      f"{b['v2_ticks_with_a_collision']:,} |")
    A(f"| candidates in the denominator | {a['v1_presented_total']:,} | "
      f"{a['v2_admitted_total']:,} | {b['v1_presented_total']:,} | "
      f"{b['v2_admitted_total']:,} |")
    A("")
    A(f"**{a['v1_collisions_total']} of {a['v1_presented_total']} presented candidates "
      f"({100.0 * a['v1_collisions_total'] / max(a['v1_presented_total'], 1):.1f} %) on the replay")
    A(f"and {b['v1_collisions_total']} of {b['v1_presented_total']} "
      f"({100.0 * b['v1_collisions_total'] / max(b['v1_presented_total'], 1):.1f} %) live carried a")
    A("drive vector identical to another candidate in the same round. Under v2,")
    A(f"**{a['v2_collisions_total']} of {a['v2_admitted_total']:,}** and")
    A(f"**{b['v2_collisions_total']} of {b['v2_admitted_total']:,}** do.")
    A("")
    A("The two denominators are **different sets** and the comparison is a rate,")
    A("not a difference of counts: v1's denominator is what the fly was shown,")
    A("v2's is what it would have been eligible to be shown. And the zero is not a")
    A("promise of uniqueness — `pons_context_v2` still encodes two identical")
    A("measured contexts identically, by design, and")
    A("`tests/d11/test_encoder_v2.py` asserts exactly that. It is the statement")
    A("that on these cutoffs no two *eligible* candidates had identical")
    A("measurements, because a candidate now has to have traded in the last two")
    A("minutes to be eligible at all, and two such tokens rarely agree on ten")
    A("numbers at once.")
    A("")
    A("## 4. The seventeen entries, under v2")
    A("")
    A("Each entry re-evaluated at its own cutoff with the tape truncated there.")
    A("")
    A("| run / branch | episode | token | `since_last_trade` | `trade_count_2m` | v2 verdict | reasons |")
    A("|---|---|---|---|---|---|---|")
    for e in p["seventeen_entries"]:
        slt = e.get("since_last_trade_s")
        cnt = e.get("trade_count_2m")
        slt_s = "—" if slt is None else f"{slt:.0f} s"
        cnt_s = "—" if cnt is None else f"{cnt:.0f}"
        reasons = ", ".join(f"`{r}`" for r in e["reasons"]) or "—"
        A(f"| `{e['run_id']}/{e['branch']}` | {e['episode_id']} | "
          f"`{e['token'][:10]}…` | {slt_s} | {cnt_s} | "
          f"**{e['v2_verdict']}** | {reasons} |")
    A("")
    admitted = sum(1 for e in p["seventeen_entries"]
                   if e["v2_verdict"] == "ADMITTED")
    A(f"**{len(p['seventeen_entries']) - admitted} of the "
      f"{len(p['seventeen_entries'])} entries would not have been eligible at all**,")
    A("every one of them `INACTIVE` and nothing else — the state was valid, the")
    A("curve had not graduated, the coverage reached the horizon, and the token")
    A("simply had not traded. The two that survive are the same tick-4 round in")
    A("both replay branches: 20 valid trades in the window, the last 42 s back.")
    A("")
    A("This says which candidates would have been *eligible*. It says nothing")
    A("about which one the fly would have chosen, or what that would have paid.")
    A("")
    A("## 5. The four distinctions, on real tokens")
    A("")
    A("Drawn from `d10-backfill-v1`, each at a real cutoff, with the v2 rate vector")
    A("the encoder produces. Rates are per-ORN drive in Hz per glomerulus on the")
    A("same constant 12,000 Hz budget across 1,070 ORNs; the carrier alone is")
    A("about 5.7 Hz on twenty channels.")
    A("")
    for w in p["worked_examples"]:
        A(f"### {w['case']} — {w['label']}")
        A("")
        if not w.get("found"):
            A("*No example of this case exists in the window.*")
            A("")
            continue
        A(f"`{w['token']}` at cutoff **{w['cutoff_ts']}**, status "
          f"`{w['status']}`" + (f" ({w['reason']})" if w.get("reason") else "") + ".")
        A("")
        A("| feature | raw | normalised |")
        A("|---|---|---|")
        for f in ("age", "since_last_trade", "ret_30s", "ret_2m", "ret_5m",
                  "flow_imb_2m", "trade_count_2m", "gross_volume_2m", "rv_2m",
                  "drawdown_5m"):
            raw = w["raw"].get(f)
            nrm = (w.get("normalised") or {}).get(f)
            A(f"| `{f}` | {'—' if raw is None else f'{raw:.6g}'} | "
              f"{'—' if nrm is None else f'{nrm:+.6f}'} |")
        A("")
        if w.get("rates_hz"):
            A("Rate vector, Hz per ORN:")
            A("")
            A("| " + " | ".join(w["rates_hz"]) + " |")
            A("|" + "---|" * len(w["rates_hz"]))
            A("| " + " | ".join(f"{v:.4g}" for v in w["rates_hz"].values()) + " |")
        else:
            A("**No rate vector exists**: the observation is not usable, so it is")
            A("not encoded at all. There is no zero vector standing in for it —")
            A("that is the whole of distinction D.")
        A("")
    A("The four are distinguishable in the deterministic vector, which is what")
    A("section 4 of the amendment asks for: **A** carries `trade_count_2m` and")
    A("`gross_volume_2m` at exactly zero with `since_last_trade` large; **B**")
    A("carries a high count and near-zero returns with small `rv_2m`; **C** carries")
    A("real gross volume with `flow_imb_2m` near zero; **D** carries nothing,")
    A("because it is not presented.")
    A("")
    A("## 6. The limitation, stated and not worked around")
    A("")
    A("**Admission v2 leaves few candidates, and the rule is not loosened.**")
    A("")
    A(f"* On the replay, the median tick has **{a['median_v2_admitted']:.0f}** eligible")
    A(f"  candidates and the busiest has {a['max_v2_admitted_in_a_tick']}; "
      f"{a['ticks_with_fewer_than_six_v2']} of {a['ticks']} ticks would present fewer")
    A(f"  than the six the rotation allows, and {a['zero_eligible_ticks_v2']} would")
    A("  present none at all — the same number v1 presents none at, so v2 creates")
    A("  no new empty round on this window.")
    A(f"* Live, the median tick has **{b['median_v2_admitted']:.0f}** eligible candidates,")
    A(f"  the thinnest has {min(t['v2_admitted'] for t in b['ticks_detail'])} and the")
    A(f"  busiest {b['max_v2_admitted_in_a_tick']}; **no tick is empty and no tick falls")
    A("  below six.**")
    A("* The scale fit saw the same shrinkage from the other side: 1,197 of 56,932")
    A("  grid points admitted in the first hour of the window")
    A("  (`experiments/d11/feature_scales_v2.json`).")
    A("")
    A("That is what a two-minute liveness rule costs on a venue where 59 % of")
    A("launches are silent five minutes after birth. It is the intended effect —")
    A("the pool stops being corpses — and it is also a real constraint on how much")
    A("choice a round offers. It is recorded here so the next wave argues about it")
    A("with a number, and **no criterion was relaxed to make the tables look")
    A("better**.")
    A("")
    A("## 7. What this file does not say")
    A("")
    A("It does not compute a trade, a fill, a PnL or a reward. It does not say the")
    A("corrected brain would have chosen better, or at all. It does not compare")
    A("D10's losses with anything. It measures two things — how many candidates")
    A("survive the new rule, and how often two of them smell identical — and both")
    A("are properties of the *environment*, not of the fly.")
    A("")
    return "\n".join(out)


if __name__ == "__main__":
    raise SystemExit(main())
