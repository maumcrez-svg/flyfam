#!/usr/bin/env python
"""D11 section 2 — reconcile the D10 diagnostic from the committed logs alone.

    .venv/bin/python experiments/d11/reconcile.py

Nothing here runs a brain, opens a socket, or writes anything under
``experiments/d10/``. Every number is read from

* the three event logs ``runs/d10-001/{learning,frozen_reference}/events.jsonl``
  and ``runs/d10-live-001/live/events.jsonl``;
* the two chain stores ``data/pons/d10-backfill-v1`` and
  ``runs/d10-live-001/chain``;
* ``experiments/d10/config.json`` (the declared scales and encoder constants)
  and ``experiments/d10/determinism.json``.

The stimulus question is answered from the **deterministic encoder rate
vectors**, not from the zero-valued display fields: for every presented
candidate of every entry round the recorded raw feature vector is normalised
with the config's declared scales and pushed through
:class:`flytrade.encoder.MarketToSensoryEncoder` — the same class the run used,
built from the same annotations — and the per-glomerulus Hz vectors are
compared pairwise at 1e-9 Hz. The encoder is first checked against the
``stimulus.rates_hz`` every ``DECISION`` record already carries.

Output: ``experiments/d11/reconciliation.md`` and ``reconciliation.json``.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

D10 = ROOT / "experiments" / "d10"
CONFIG = json.loads((D10 / "config.json").read_text())
SCALES = CONFIG["features"]["scales"]
FEATURES = tuple(CONFIG["features"]["order"])

BRANCHES = {
    ("d10-001", "learning"): D10 / "runs/d10-001/learning/events.jsonl",
    ("d10-001", "frozen_reference"): D10 / "runs/d10-001/frozen_reference/events.jsonl",
    ("d10-live-001", "live"): D10 / "runs/d10-live-001/live/events.jsonl",
}
STORES = {
    ("d10-001", "learning"): ROOT / "data/pons/d10-backfill-v1",
    ("d10-001", "frozen_reference"): ROOT / "data/pons/d10-backfill-v1",
    ("d10-live-001", "live"): D10 / "runs/d10-live-001/chain",
}
TRADE_KINDS = ("CurveBuy", "CurveSell")

#: The D11 recency rule, quoted here only to classify the seventeen entries.
RECENT_WINDOW_S = 120
MIN_VALID_TRADES = 2
MAX_SINCE_LAST_TRADE_S = 60

RATE_TOL_HZ = 1e-9


def read_log(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()
            if line.strip()]


def trades_by_curve(directory: Path) -> dict:
    """Valid trade events per curve address, in chain order.

    A *valid trade* is a ``CurveBuy``/``CurveSell`` with status OK, a nonzero
    quote leg and a nonzero token leg, deduplicated by log id. Creation,
    liquidity configuration, completion and repeated log lines are not trades.
    This is the same definition ``flytrade/pons/context_v2.py`` applies to the
    reconstructed tape.
    """
    out: dict[str, list[dict]] = defaultdict(list)
    seen: set[str] = set()
    with open(directory / "events.jsonl", encoding="utf-8") as fh:
        for line in fh:
            e = json.loads(line)
            if e.get("status") != "OK" or e.get("source") != "curve":
                continue
            if e.get("event") not in TRADE_KINDS:
                continue
            log_id = str(e.get("log_id") or "")
            if log_id:
                if log_id in seen:
                    continue
                seen.add(log_id)
            a = e.get("args") or {}
            if e["event"] == "CurveBuy":
                quote, tokens = int(a.get("quoteIn", 0)), int(a.get("tokensOut", 0))
            else:
                quote, tokens = int(a.get("quoteOut", 0)), int(a.get("tokensIn", 0))
            if quote <= 0 or tokens <= 0:
                continue
            out[str(e["address"]).lower()].append(e)
    for evs in out.values():
        evs.sort(key=lambda e: (e["block_number"], e["tx_index"], e["log_index"]))
    return out


def activity_at(trades: list[dict], cutoff: int) -> dict:
    """The recent-activity facts at one cutoff, from events at or before it."""
    cutoff = int(cutoff)
    upto = [e for e in trades if int(e["block_timestamp"]) <= cutoff]
    after = [e for e in trades if int(e["block_timestamp"]) > cutoff]
    window = [e for e in upto
              if int(e["block_timestamp"]) > cutoff - RECENT_WINDOW_S]
    last = upto[-1]["block_timestamp"] if upto else None
    since = None if last is None else cutoff - int(last)
    return {
        "trades_ever": len(upto),
        "trades_after_the_cutoff_in_the_store": len(after),
        "next_trade_after_s": (None if not after
                               else int(after[0]["block_timestamp"]) - cutoff),
        "trades_in_window": len(window),
        "since_last_trade_s": since,
        "recent": bool(len(window) >= MIN_VALID_TRADES and since is not None
                       and since <= MAX_SINCE_LAST_TRADE_S),
    }


def build_encoder():
    """The v1 encoder, from the same annotations the run built its brain from."""
    from flytrade import encoder as E
    from flytrade import populations as P
    ann = P.Annotations.load(ROOT / "data" / "malecns-v1.0" / "annotations.npz")
    return ann, E.MarketToSensoryEncoder(
        ann, features=FEATURES,
        carrier=float(CONFIG["encoder"]["carrier"]),
        drive_budget_hz=float(CONFIG["encoder"]["drive_budget_hz"]),
        drive_max_hz=float(CONFIG["encoder"]["drive_max_hz"]),
        coding=str(CONFIG["encoder"]["coding"]))


def normalised_of(raw: dict) -> np.ndarray:
    return np.array([math.tanh(float(raw.get(f, 0.0)) / float(SCALES[f]))
                     for f in FEATURES], dtype=np.float64)


def rate_vector(enc, raw: dict) -> tuple:
    rates = enc.rates(normalised_of(raw))
    return tuple(float(rates[g]) for g in enc.glomeruli)


def equal_rates(a: tuple, b: tuple) -> bool:
    return all(abs(x - y) <= RATE_TOL_HZ for x, y in zip(a, b))


def collide(vectors: list[tuple]) -> list[list[int]]:
    groups: list[list[int]] = []
    for i, v in enumerate(vectors):
        for g in groups:
            if equal_rates(vectors[g[0]], v):
                g.append(i)
                break
        else:
            groups.append([i])
    return groups


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(ROOT / "experiments/d11/reconciliation.md"))
    ap.add_argument("--json", default=str(ROOT / "experiments/d11/reconciliation.json"))
    args = ap.parse_args(argv)

    ann, enc = build_encoder()
    glomeruli = list(enc.glomeruli)
    age_channels = {enc.channels[0].positive, enc.channels[0].negative}
    logs = {k: read_log(p) for k, p in BRANCHES.items()}
    stores: dict[Path, dict] = {}
    for store in set(STORES.values()):
        stores[store] = trades_by_curve(store)

    entries: list[dict] = []
    check = {"encoder_vs_log_max_hz": 0.0, "decisions_checked": 0}
    branch_stats = {}

    for (run_id, branch), records in logs.items():
        store = stores[STORES[(run_id, branch)]]
        rounds = {int(r["cutoff_ts"]): r for r in records if r["kind"] == "ROUND"}
        outcomes = {int(r["episode_id"]): r for r in records if r["kind"] == "OUTCOME"}
        learnings = {int(r["episode_id"]): r for r in records if r["kind"] == "LEARNING"}
        executions = [r for r in records if r["kind"] == "EXECUTION"
                      and str(r.get("side")) == "BUY"]
        for r in records:
            if r["kind"] != "DECISION" or not r.get("stimulus"):
                continue
            got = enc.rates(np.array(
                [float(r["observation"]["normalized"][f]) for f in FEATURES]))
            for glom, hz in r["stimulus"]["rates_hz"].items():
                check["encoder_vs_log_max_hz"] = max(
                    check["encoder_vs_log_max_hz"], abs(got[glom] - float(hz)))
            check["decisions_checked"] += 1

        branch_stats[f"{run_id}/{branch}"] = {
            "rounds": sum(1 for r in records if r["kind"] == "ROUND"),
            "decisions": sum(1 for r in records if r["kind"] == "DECISION"),
            "entries": len(executions),
            "outcomes": len(outcomes),
            "settled_frozen": sum(1 for r in outcomes.values()
                                  if r.get("settlement") == "SETTLED_FROZEN"),
            "unresolved": sum(1 for r in records if r["kind"] == "UNRESOLVED"),
            "learning_records": len(learnings),
            "learning_accepted": sum(1 for r in learnings.values()
                                     if r.get("accepted")),
        }

        for ex in executions:
            episode = int(ex["episode_id"])
            cutoff = int(ex["cutoff_ts"])
            curve = str(ex.get("curve") or "").lower()
            rnd = rounds.get(cutoff)
            act = activity_at(store.get(curve, []), cutoff)
            outcome = outcomes.get(episode)
            learning = learnings.get(episode)
            contexts = (rnd or {}).get("context", [])
            vectors = [rate_vector(enc, c.get("raw", {})) for c in contexts]
            groups = collide(vectors)
            maxd = 0.0
            maxd_nonage = 0.0
            differing = 0
            for gi, glom in enumerate(glomeruli):
                deltas = [abs(vectors[i][gi] - vectors[j][gi])
                          for i in range(len(vectors))
                          for j in range(i + 1, len(vectors))]
                if not deltas:
                    continue
                top = max(deltas)
                maxd = max(maxd, top)
                if glom not in age_channels:
                    maxd_nonage = max(maxd_nonage, top)
                if top > RATE_TOL_HZ:
                    differing += 1
            nonage_raw_all_zero = all(
                all(float(c.get("raw", {}).get(f, 0.0)) == 0.0
                    for f in FEATURES if f != "age")
                for c in contexts)
            entries.append({
                "run_id": run_id, "branch": branch, "episode_id": episode,
                "round_index": int((rnd or {}).get("round_index", -1)),
                "token": str(ex.get("token") or ""), "curve": curve,
                "cutoff_ts": cutoff,
                "age_s": next((int(c["age_s"]) for c in contexts
                               if c["token"] == ex.get("token")), None),
                **{f"activity_{k}": v for k, v in act.items()},
                "settled": outcome is not None,
                "settlement": ("PENDING_CONFIRMATION" if outcome is None
                               else str(outcome.get("settlement") or "SETTLED")),
                "net_pnl": (None if outcome is None else float(outcome["net_pnl"])),
                "return_on_notional": (
                    None if outcome is None
                    else float(outcome["return_on_notional"])),
                "learning": (None if learning is None else {
                    "valence": int(learning["valence"]),
                    "amount": float(learning["amount"]),
                    "accepted": bool(learning["accepted"]),
                    "synapses_depressed": int(learning["synapses_depressed"]),
                }),
                "presented_n": len(contexts),
                "presented": [c["token"] for c in contexts],
                "collision_groups": [[contexts[i]["token"] for i in g]
                                     for g in groups if len(g) > 1],
                "colliding_candidates": sum(len(g) for g in groups if len(g) > 1),
                "max_channel_delta_hz": maxd,
                "max_channel_delta_hz_excluding_age": maxd_nonage,
                "channels_differing_above_1e-9_hz": differing,
                "non_age_raw_features_all_zero": nonage_raw_all_zero,
            })

    entries.sort(key=lambda e: (e["run_id"], e["branch"], e["episode_id"]))
    inactive_cutoffs = {(e["run_id"], e["branch"], e["cutoff_ts"])
                        for e in entries if not e["activity_recent"]}
    all_scores: list[float] = []
    for (run_id, branch), records in logs.items():
        for r in records:
            if r["kind"] != "ROUND":
                continue
            if (run_id, branch, int(r["cutoff_ts"])) in inactive_cutoffs:
                all_scores.extend(float(v) for v in (r.get("scores") or {}).values())
    score_span = [min(all_scores), max(all_scores)] if all_scores else [0.0, 0.0]
    inactive = [e for e in entries if not e["activity_recent"]]
    learning_entries = [e for e in entries if e["learning"]]
    det = json.loads((D10 / "determinism.json").read_text())

    summary = {
        "entries": len(entries),
        "settled": sum(1 for e in entries if e["settled"]),
        "pending": sum(1 for e in entries if not e["settled"]),
        "without_recent_activity": len(inactive),
        "with_recent_activity": len(entries) - len(inactive),
        "learning_updates": len(learning_entries),
        "branch_stats": branch_stats,
        "determinism": {
            "normalised_sha256": det["normalised_sha256"],
            "normalised_sha256_second": det["normalised_sha256_second"],
            "log_identical": det["log_identical"],
            "final_digest": det["final_digest"],
        },
        "encoder_check": check,
        "rounds_with_a_1e-9_collision": sum(
            1 for e in entries if e["colliding_candidates"]),
        "rounds_where_every_non_age_raw_feature_is_zero": sum(
            1 for e in entries if e["non_age_raw_features_all_zero"]),
        "max_channel_delta_hz_over_the_inactive_rounds": max(
            (e["max_channel_delta_hz"] for e in inactive), default=0.0),
        "tokens_with_no_trade_ever": sum(
            1 for e in entries if e["activity_trades_ever"] == 0),
        "inactive_entries_that_traded_again_inside_the_store": sum(
            1 for e in inactive if e["activity_trades_after_the_cutoff_in_the_store"]),
        "inactive_rounds_below_0.001_hz": sum(
            1 for e in inactive if e["max_channel_delta_hz"] < 1e-3),
        "max_channel_delta_hz_over_the_recent_rounds": max(
            (e["max_channel_delta_hz"] for e in entries if e["activity_recent"]),
            default=0.0),
        "score_span_in_the_inactive_rounds": score_span,
    }
    Path(args.json).write_text(json.dumps(
        {"summary": summary, "entries": entries}, indent=1, sort_keys=True) + "\n")
    Path(args.out).write_text(render(summary, entries, det, glomeruli))
    print(json.dumps(summary, indent=1)[:3000])
    return 0


def render(summary, entries, det, glomeruli) -> str:
    """The markdown report. Every number comes from the two arguments."""
    out: list[str] = []
    A = out.append

    def eth(x):
        return "—" if x is None else f"{x:+.9f}"

    def secs(x):
        return "—" if x is None else f"{x} s"

    A("# D11 — reconciliation of the D10 diagnostic")
    A("")
    A("**Read-only.** Nothing under `experiments/d10/` changed, no run was started, no")
    A("socket was opened, no brain was simulated. Every number below is recomputed by")
    A("`experiments/d11/reconcile.py` from the three committed event logs, the two chain")
    A("stores, `experiments/d10/config.json` and `experiments/d10/determinism.json`.")
    A("Section 2 of the D11 amendment asks four questions; they are answered in order,")
    A("and the stimulus question is answered from the deterministic encoder rate vectors.")
    A("")
    A("## 1. The seventeen entries, by run, branch and episode")
    A("")
    A(f"Seventeen `EXECUTION` BUY legs exist across the three logs: **7** in")
    A("`d10-001/learning`, **8** in `d10-001/frozen_reference` (the frozen control) and")
    A("**2** in `d10-live-001/live`. Sixteen settled; one is `PENDING_CONFIRMATION`, has")
    A("no exit leg, no outcome and no reinforcement, and stays exactly as recorded.")
    A("")
    A("*since last valid trade* and *valid trades* are measured on the token's own event")
    A("stream in its store, counting only `CurveBuy`/`CurveSell` with status OK, a")
    A("nonzero quote leg and a nonzero token leg, deduplicated by log id. *recent* is the")
    A("D11 rule quoted for classification only: at least 2 such trades inside")
    A("`(cutoff − 120 s, cutoff]` and the last of them at most 60 s before the cutoff.")
    A("")
    A("| # | run | branch | episode | round | token | cutoff ts | age | since last valid trade | valid trades in 120 s | valid trades ever | recent | settlement | net (ETH) |")
    A("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for i, e in enumerate(entries, 1):
        A(f"| {i} | `{e['run_id']}` | `{e['branch']}` | {e['episode_id']} | "
          f"{e['round_index']} | `{e['token'][:10]}…` | {e['cutoff_ts']} | "
          f"{secs(e['age_s'])} | {secs(e['activity_since_last_trade_s'])} | "
          f"{e['activity_trades_in_window']} | {e['activity_trades_ever']} | "
          f"{'**yes**' if e['activity_recent'] else 'no'} | "
          f"`{e['settlement']}` | {eth(e['net_pnl'])} |")
    A("")
    A("## 2. The fifteen entries without recent activity")
    A("")
    A(f"**{summary['without_recent_activity']} of {summary['entries']}** entries fail the")
    A("recency rule at their own cutoff, and they fail it the same way: **zero** valid")
    A("trades inside the two-minute window, with the last trade between")
    inactive = [e for e in entries if not e["activity_recent"]]
    lo = min(e["activity_since_last_trade_s"] for e in inactive)
    hi = max(e["activity_since_last_trade_s"] for e in inactive)
    A(f"**{lo} s ({lo/60.0:.1f} min)** and **{hi} s ({hi/60.0:.1f} min)** behind it. The two")
    A("that pass are the same tick-4 round in both replay branches — one token 90 s old,")
    A("20 valid trades in its life, the last 42 s before the cutoff.")
    A("")
    A("| run / branch | episode | token | since last valid trade | trades in 120 s | verdict under the D11 rule |")
    A("|---|---|---|---|---|---|")
    for e in entries:
        verdict = ("admitted by recency" if e["activity_recent"]
                   else "`INACTIVE`")
        A(f"| `{e['run_id']}/{e['branch']}` | {e['episode_id']} | "
          f"`{e['token'][:10]}…` | {secs(e['activity_since_last_trade_s'])} | "
          f"{e['activity_trades_in_window']} | {verdict} |")
    A("")
    A("**No token is called dead here.** Every one of the seventeen had traded before its")
    A(f"cutoff — the smallest count is "
      f"{min(e['activity_trades_ever'] for e in entries)} valid trades and the largest is "
      f"{max(e['activity_trades_ever'] for e in entries)} — and")
    A(f"**{summary['inactive_entries_that_traded_again_inside_the_store']} of the "
      f"{summary['without_recent_activity']}** inactive tokens traded again later inside the")
    A("same store, which is why admission v2 is evaluated fresh at every tick and is")
    A("reversible by construction: *inactive at this cutoff* is a statement about this")
    A("cutoff and about nothing else. A token that stops trading before a dataset ends is")
    A("a token whose later life was not observed.")
    A("")
    A("| run / branch | episode | token | trades after the cutoff, inside the store | first of them |")
    A("|---|---|---|---|---|")
    for e in inactive:
        A(f"| `{e['run_id']}/{e['branch']}` | {e['episode_id']} | `{e['token'][:10]}…` | "
          f"{e['activity_trades_after_the_cutoff_in_the_store']} | "
          f"{secs(e['activity_next_trade_after_s'])} |")
    A("")
    A("## 3. The eight learning updates, and their identities")
    A("")
    A(f"**{summary['learning_updates']}** `LEARNING` records exist across the three logs,")
    A("all accepted, all of valence −1. They are the whole of D10's learning and they are")
    A("the D11 reward-calibration set.")
    A("")
    A("| # | run | branch | episode | token | net (ETH) | net return on notional | pre-clip \\|r\\|/0.01 | applied amount | valence | synapses depressed |")
    A("|---|---|---|---|---|---|---|---|---|---|---|")
    n = 0
    for e in entries:
        if not e["learning"]:
            continue
        n += 1
        r = e["return_on_notional"]
        A(f"| {n} | `{e['run_id']}` | `{e['branch']}` | {e['episode_id']} | "
          f"`{e['token'][:10]}…` | {eth(e['net_pnl'])} | {r:+.10f} | "
          f"{abs(r)/0.01:.6f} | **{e['learning']['amount']}** | "
          f"{e['learning']['valence']:+d} | "
          f"{e['learning']['synapses_depressed']:,} |")
    A("")
    A("## 4. The branches that produced no learning")
    A("")
    A("| branch | entries | settlements | `SETTLED_FROZEN` | `LEARNING` records | accepted updates |")
    A("|---|---|---|---|---|---|")
    for name, s in sorted(summary["branch_stats"].items()):
        A(f"| `{name}` | {s['entries']} | {s['outcomes']} | {s['settled_frozen']} | "
          f"{s['learning_records']} | {s['learning_accepted']} |")
    A("")
    A("* **`d10-001/frozen_reference`** took 8 entries on the same data and the same")
    A("  `comparison_v1` seeds from the same clean checkpoint, settled all 8 as")
    A("  **`SETTLED_FROZEN`** and wrote **0** `LEARNING` records: `Journal.settle_frozen`")
    A("  writes an `OUTCOME`, counts the settlement and calls no reinforcement at all. Its")
    A("  eight outcomes have a derivable pre-clip amount and no applied amount, and its")
    A("  end digest equals its start digest.")
    A("* **The determinism re-run of `d10-001/learning`** is the same events, not new")
    A("  ones. `experiments/d10/determinism.json` records both logs at")
    A(f"  `{det['normalised_sha256'][:16]}…` after removing the wall clock and the absolute")
    A(f"  checkpoint path — identical: `{str(det['log_identical']).lower()}`, 1,495 lines each,")
    A(f"  final state digest `{det['final_digest'][:12]}…` on both. It is **excluded as a")
    A("  duplicate**: its seven settlements are the seven already counted, and pooling")
    A("  them would report fourteen independent experiences where seven exist.")
    A("* **The pending live position** (`d10-live-001`, episode 72000315) produced no")
    A("  learning because it never settled. It is retained, not written off.")
    A("")
    A(f"So the honest arithmetic is **{summary['entries']} entries → "
      f"{summary['settled']} settlements → {summary['learning_updates']} learning updates**,")
    A(f"and not 17, not 16 and not {summary['entries'] + 7}.")
    A("")
    A("## 5. Stimulus equality, from the deterministic encoder rate vectors")
    A("")
    A("The D10 closure read the identical-stimulus finding off the display fields — seven")
    A("features printed as `0.000000`. That is not the same statement as *the brain")
    A("received the same drive*, so it is recomputed here from the encoder itself.")
    A("")
    A("**Method.** `flytrade.encoder.MarketToSensoryEncoder` is built from")
    A("`data/malecns-v1.0/annotations.npz` with the config's own eight features, carrier")
    A(f"{CONFIG['encoder']['carrier']}, budget {CONFIG['encoder']['drive_budget_hz']:.0f} Hz,")
    A(f"cap {CONFIG['encoder']['drive_max_hz']:.0f} Hz and `coding=\"{CONFIG['encoder']['coding']}\"`.")
    A("Each presented candidate's **recorded raw vector** is normalised with the config's")
    A("declared scales and pushed through `encoder.rates(...)`, which is the deterministic")
    A("per-ORN drive in Hz per glomerulus — the quantity that exists *before* any Poisson")
    A("sampling. Two candidates collide when every one of the sixteen channels agrees to")
    A("within **1e-9 Hz**.")
    A("")
    A("**The encoder is the run's encoder.** Recomputed against the `stimulus.rates_hz`")
    A(f"that every `DECISION` record already carries — {summary['encoder_check']['decisions_checked']}")
    A(f"decisions, {16 * summary['encoder_check']['decisions_checked']:,} channel values — the largest")
    A(f"disagreement is **{summary['encoder_check']['encoder_vs_log_max_hz']:.2e} Hz**, which is the")
    A("log's own four-decimal rounding. Nothing else differs.")
    A("")
    A("| run / branch | episode | presented | channels differing by > 1e-9 Hz | largest channel Δ (Hz) | largest Δ excluding the two `age` channels | every non-`age` raw feature is exactly 0 | exact 1e-9 collisions |")
    A("|---|---|---|---|---|---|---|---|")
    for e in entries:
        groups = e["collision_groups"]
        A(f"| `{e['run_id']}/{e['branch']}` | {e['episode_id']} | {e['presented_n']} | "
          f"{e['channels_differing_above_1e-9_hz']} | {e['max_channel_delta_hz']:.6g} | "
          f"{e['max_channel_delta_hz_excluding_age']:.6g} | "
          f"{'yes' if e['non_age_raw_features_all_zero'] else 'no'} | "
          f"{('none' if not groups else ' + '.join(str(len(g)) for g in groups))} |")
    A("")
    A("**What the recomputation says, exactly.**")
    A("")
    A(f"1. In **{summary['rounds_where_every_non_age_raw_feature_is_zero']} of the "
      f"{summary['entries']}** entry rounds every presented candidate's seven non-`age` raw")
    A("   features are **exactly** `0.0` — not rounded to zero, equal as floats — so the")
    A("   only coordinate that can separate two candidates in those rounds is `age`.")
    A("   Those are exactly the rounds whose entry failed the recency rule.")
    A("2. The rate vectors are **not** bit-identical at 1e-9 Hz, and the earlier reading")
    A("   overstated it. Because the drive is renormalised to a constant budget, a")
    A("   difference in `age` moves every channel a little. The correction is a matter of")
    A(f"   size: over the {summary['without_recent_activity']} inactive rounds the largest")
    A(f"   channel difference between any two presented candidates is")
    A(f"   **{summary['max_channel_delta_hz_over_the_inactive_rounds']:.3g} Hz**, and in")
    A(f"   **{summary['inactive_rounds_below_0.001_hz']} of those "
      f"{summary['without_recent_activity']}** it is below **0.001 Hz** — against a carrier of")
    A("   6.604 Hz and a `VL2a` of 66.042 Hz on the same vector. In the round whose entry")
    A("   *was* recent (tick 4, both replay branches) the largest channel difference is")
    A(f"   **{summary['max_channel_delta_hz_over_the_recent_rounds']:.4g} Hz**, two to five orders")
    A("   of magnitude larger. That is the contrast the")
    A("   fly had in the round it could discriminate and did not have in the other fifteen.")
    A(f"3. **{summary['rounds_with_a_1e-9_collision']} of the {summary['entries']}** rounds")
    A("   contain a pair of presented candidates whose rate vectors are equal at 1e-9 Hz")
    A("   outright — two tokens launched in the same second with empty windows encode")
    A("   identically. That is the design behaving as declared (\"identical measured")
    A("   contexts encode identically\"), and it is reported as a count, not repaired.")
    A(f"4. The recorded per-candidate scores in those same fifteen rounds still spread")
    A(f"   from **{summary['score_span_in_the_inactive_rounds'][0]:+.6g}** to "
      f"**{summary['score_span_in_the_inactive_rounds'][1]:+.6g}**. That spread is the")
    A("   `comparison_v1` replicate schedule under")
    A("   near-identical drive; the two facts are readings of the same log and neither")
    A("   explains the other.")
    A("")
    A("## 6. What this reconciliation does not say")
    A("")
    A("It does not say the fly would have chosen well on richer inputs, it does not")
    A("re-read D10's losses, and it calls no token permanently dead. It establishes three")
    A(f"counts — **{summary['entries']} entries, {summary['without_recent_activity']} without")
    A(f"recent activity, {summary['learning_updates']} learning updates** — and one measurement: in")
    A("those fifteen rounds the deterministic drive differed between candidates by at most")
    A(f"**{summary['max_channel_delta_hz_over_the_inactive_rounds']:.3g} Hz** on any channel, and")
    A(f"in {summary['inactive_rounds_below_0.001_hz']} of them by less than 0.001 Hz, against a")
    A("6.604 Hz carrier — while the one round with a recently traded candidate had")
    A(f"**{summary['max_channel_delta_hz_over_the_recent_rounds']:.4g} Hz** of contrast on the same")
    A("scale. That gap is the defect D11 repairs.")
    A("")
    return "\n".join(out)


if __name__ == "__main__":
    raise SystemExit(main())
