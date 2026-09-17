#!/usr/bin/env python
"""
The offline vertical slice at k = 8 — D4 §8, Fable addendum 9.

    .venv/bin/python experiments/k8_readout/run_demo_k8.py

The Phase One demonstration, unchanged in every respect except the one this
wave changes: the same six seeded synthetic instruments, the same series seeds,
the same bar range, the same execution fixture, the same mid-run restart — with
every candidate now read **eight times** and decoded once, against the k = 8
baseline and margin measured in §3.

    8 neural measurements per candidate -> 1 aggregate readout -> 1 decision
    -> at most 1 execution episode -> 1 outcome-linked learning event.

The k = 1 demonstration is **not** re-run here; its numbers stand in
`experiments/phase_one/results.md` and the two are compared only where the
comparison is measured, which is the §7 benchmark. Net PnL is not a gate metric
and is not read in either direction.

One reporting detail the Phase One run could not have: the per-decision counts
of `NO_RESPONSE`, `WAIT` and `INVALID_STATE` are kept apart, and the silent
*replicates* inside the batches are counted separately with their own unit.

The "same context, same seeds" line after each settlement re-measures the entry
stimulus on the entry batch's own schedule — the same eight seeds before and
after — so that what moved is the learning and not the draw.

Writes ``demo_k8.json`` next to this file.
"""
from __future__ import annotations

import json
import platform
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "upstream"))

from flytrade import decoder as D        # noqa: E402
from flytrade import encoder as E        # noqa: E402
from flytrade import execution as X      # noqa: E402
from flytrade import graph as G          # noqa: E402
from flytrade import market as MK        # noqa: E402
from flytrade import mushroom as M       # noqa: E402
from flytrade import populations as P    # noqa: E402
from flytrade import readout as RO       # noqa: E402
from flytrade import records as REC      # noqa: E402
from flytrade import runner as R         # noqa: E402

DATA = ROOT / "data" / "malecns-v1.0"
STORE = HERE / "run"

#: identical to experiments/phase_one/run_demo.py
N_INSTRUMENTS = 6
SERIES_SEED0 = 700
ROUND_SEED = 20260911
FIRST_BAR = MK.MIN_HISTORY_BARS - 1
LAST_BAR = 400
RESTART_AFTER_TRADES = 3


def main() -> int:
    t0 = time.time()
    import flysim

    if STORE.exists():
        for p in sorted(STORE.iterdir()):
            p.unlink()

    fb = flysim.FlyBrain(graph_path=DATA / "graph.npz")
    mod = G.ModulatoryGraph(DATA / "graph_mod.npz", bodies=fb.bodies)
    ann = P.Annotations.load(DATA / "annotations.npz")
    graph_sha = G.sha256_file(DATA / "graph.npz")
    mb = M.MushroomBody(fb, mod,
                        np.flatnonzero(P.kenyon_cells(ann)),
                        np.flatnonzero(P.mbons(ann)),
                        np.flatnonzero(P.pam(ann)),
                        np.flatnonzero(P.ppl1(ann)))
    enc = E.MarketToSensoryEncoder(ann)
    pops = D.readout_populations(ann, mb.compartments)
    run = R.BrainRunner(fb, mb, enc, pops, graph_sha256=graph_sha)
    credit = R.CreditAssigner(mb)
    base = RO.load_baseline(HERE / "baseline_k8.json", k=RO.K,
                            graph_sha256=graph_sha)
    policy = RO.policy_k8()
    dec = policy.decoder

    symbols = tuple(f"SYN{i:02d}" for i in range(N_INSTRUMENTS))
    series = {s: MK.synthetic_series(s, seed=SERIES_SEED0 + i)
              for i, s in enumerate(symbols)}
    feed = MK.ObservationFeed(series)
    universe = MK.Universe(symbols)
    policy_x = X.ExecutionPolicy(MK.ExecutionFeed(series))

    versions = REC.Versions(market=MK.VERSION, encoder=E.VERSION,
                            runner=R.VERSION, decoder=D.VERSION,
                            execution=X.VERSION, mushroom=M.VERSION,
                            graph_sha256=graph_sha)
    journal = REC.Journal(STORE, mb=mb, credit=credit, versions=versions)
    journal.save_checkpoint(last_settled_episode=-1)

    print(f"{len(symbols)} instruments, bars {FIRST_BAR}..{LAST_BAR}, k = "
          f"{policy.k}, theta_8 = {dec.theta_hz:.4f} Hz, readout "
          f"{len(pops[D.AVOID])} avoid + {len(pops[D.APPROACH])} approach",
          flush=True)

    trace: list[dict] = []
    open_stim = open_batch = open_v = None
    restarts: list[dict] = []
    aborted: list[dict] = []
    status_counts: dict[str, int] = {}
    action_counts: dict[str, int] = {}
    silent_reps = presentations_in_batches = 0
    batches = 0

    def note(**kw):
        trace.append({"bar": kw.pop("bar"), **kw})

    last = min(LAST_BAR, min(len(s) for s in series.values()) - 2)
    for bar in range(FIRST_BAR, last):
        holding = policy_x.account.position is not None
        scan = ((policy_x.account.position.symbol,) if holding else symbols)
        obs = [feed.observe(s, bar, stable_id=universe.stable_id(s))
               for s in scan]
        try:
            rnd = run.evaluate_round(obs, round_index=bar,
                                     round_seed=ROUND_SEED, readout=policy,
                                     score=policy.score)
        except RO.TechnicalFailure as exc:      # never seen; handled, not hoped
            journal.record_round_aborted(round_index=bar,
                                         cutoff_ts=obs[0].cutoff_ts,
                                         reason=str(exc))
            aborted.append({"bar": bar, "reason": str(exc)})
            continue
        journal.record_round(rnd)
        for c in rnd.candidates:
            if c.batch is not None:
                batches += 1
                silent_reps += c.batch.silent_replicates
                presentations_in_batches += c.batch.k

        chosen = rnd.selected or (rnd.candidates[0] if holding else None)
        if chosen is None or chosen.presentation is None:
            status_counts["NO_CANDIDATE"] = status_counts.get(
                "NO_CANDIDATE", 0) + len(rnd.candidates)
            continue
        d = dec.decode(chosen.presentation)
        status_counts[d.status.value] = status_counts.get(d.status.value, 0) + 1
        action_counts[d.action.value] = action_counts.get(d.action.value, 0) + 1

        rec = REC.decision_record(
            chosen, d, round_index=bar, bar_index=bar, round_seed=ROUND_SEED,
            versions=versions, checkpoint_digest=journal.checkpoint_digest(),
            n_candidates=len(rnd.candidates),
            readout_policy=policy.as_dict())

        # ---- flat: may open ------------------------------------------
        if not holding:
            if d.action is not D.Action.BUY:
                journal.record_decision(rec)
                continue
            opened = policy_x.open_long(episode_id=chosen.episode_id,
                                        symbol=chosen.symbol,
                                        stable_id=chosen.stable_id,
                                        decision_bar=bar)
            if isinstance(opened, X.Rejection):
                rec.readout_status = D.ReadoutStatus.POLICY_REJECT.value
                rec.rejection = opened.as_dict()
                journal.record_decision(rec)
                continue
            journal.record_decision(rec)
            journal.open_episode(rec, chosen.traces, opened.entry.as_dict())
            open_stim, open_batch, open_v = (chosen.stimulus, chosen.batch,
                                             d.valence_hz)
            note(bar=bar, event="BUY", symbol=chosen.symbol,
                 u=[round(float(x), 3) for x in chosen.observation.normalized],
                 approach=round(d.approach_hz, 2), avoid=round(d.avoid_hz, 2),
                 v=round(d.valence_hz, 3), kc=chosen.presentation.kc_active,
                 eligible=chosen.traces.n_eligible,
                 eligible_per_replicate=list(chosen.traces.per_replicate),
                 silent_replicates=chosen.batch.silent_replicates,
                 replicate_actions=[r.action for r in chosen.batch.replicates],
                 fill=round(opened.entry.fill_price, 4),
                 candidates=len(rnd.candidates),
                 scores={c.symbol: round(rnd.scores[c.stable_id], 2)
                         for c in rnd.candidates if c.stable_id in rnd.scores})
            continue

        # ---- holding: may close --------------------------------------
        journal.record_decision(rec)
        reason = None
        if policy_x.due_for_horizon(bar):
            reason = X.CloseReason.POLICY_CLOSE
        elif d.action is D.Action.SELL:
            reason = X.CloseReason.NEURAL_SELL
        if reason is None:
            continue

        gains_before = mb.gain.copy()
        outcome = policy_x.close(decision_bar=bar, reason=reason)
        if isinstance(outcome, X.Rejection):
            rec.rejection = outcome.as_dict()
            continue
        valence, amount = policy_x.reinforcement(outcome)
        if valence == 0:
            ev = R.LearningEvent(episode_id=outcome.episode_id, valence=0,
                                 amount=0.0, accepted=False,
                                 reason="net outcome exactly flat",
                                 k=policy.k)
            journal.log.append(REC.EventType.OUTCOME,
                               {"episode_id": outcome.episode_id,
                                **outcome.as_dict()})
            journal.log.append(REC.EventType.LEARNING,
                               {"episode_id": outcome.episode_id,
                                **ev.as_dict()})
            REC.clear_pending(journal.pending_path)
            credit.open.pop(outcome.episode_id, None)
            credit.settled.add(outcome.episode_id)
        else:
            ev = journal.settle(outcome.episode_id, outcome.as_dict(),
                                valence, amount)
        moved = int((mb.gain != gains_before).sum())

        # what the very same context decodes to now, on the entry schedule
        after = None
        if open_stim is not None and open_batch is not None:
            s0 = run.snapshot()
            again = policy.measure(run, open_stim, episode_id=-777,
                                   state_dig=open_batch.state_digest,
                                   obs_id=open_batch.observation_id,
                                   snapshot=s0)
            run.restore(s0)
            after = dec.decode(again.aggregate)

        note(bar=bar, event=reason.value, symbol=outcome.symbol,
             v=round(d.valence_hz, 3), bars_held=outcome.bars_held,
             entry=round(outcome.entry.fill_price, 4),
             exit=round(outcome.exit.fill_price, 4),
             net_pnl=round(outcome.net_pnl, 4),
             r=round(outcome.return_on_notional, 5),
             dopamine=f"{'PAM' if valence > 0 else 'PPL1' if valence < 0 else '-'}"
                      f" x{amount:.3f}",
             depressed=ev.synapses_depressed, weights_moved=moved,
             k=ev.k, normalisation=ev.normalisation,
             depressed_per_replicate=list(ev.depressed_per_replicate),
             v_entry=round(open_v, 3) if open_v is not None else None,
             v_same_context_now=round(after.valence_hz, 3) if after else None,
             action_same_context_now=after.action.value if after else None,
             cash=round(policy_x.account.cash, 2),
             realized=round(policy_x.account.realized_pnl, 4))
        open_stim = open_batch = open_v = None

        # ---- mid-run restart -----------------------------------------
        if len(policy_x.outcomes) == RESTART_AFTER_TRADES and not restarts:
            saved = mb.gain.copy()
            mb.gain[:] = 0.0                    # destroy in-memory state
            mb.apply()
            fresh = R.CreditAssigner(mb)
            journal = REC.Journal(STORE, mb=mb, credit=fresh,
                                  versions=versions)
            report = journal.recover()
            run.mb = mb
            credit = fresh
            restored = bool(np.array_equal(mb.gain, saved))
            restarts.append({"bar": bar, "after_trades": len(policy_x.outcomes),
                             "report": report,
                             "gains_restored_exactly": restored})
            note(bar=bar, event="RESTART", detail=report["action"],
                 last_settled=report["last_settled_episode"],
                 gains_restored_exactly=restored)
            if not restored:
                raise RuntimeError("restart did not restore the learned gains")

    if policy_x.account.position is not None:
        out = policy_x.close(decision_bar=LAST_BAR,
                             reason=X.CloseReason.END_OF_DATA)
        if not isinstance(out, X.Rejection):
            v, a = policy_x.reinforcement(out)
            if v != 0:
                journal.settle(out.episode_id, out.as_dict(), v, a)

    stats = {
        "instruments": len(symbols), "bars": [FIRST_BAR, LAST_BAR],
        "k": policy.k, "batches": batches,
        "presentations": run.presentations,
        "silent_replicates": silent_reps,
        "silent_replicate_denominator": presentations_in_batches,
        "decoder_actions": action_counts, "readout_statuses": status_counts,
        "rounds_aborted": aborted,
        "execution": policy_x.stats(), "credit": credit.stats(),
        "journal": journal.stats(), "restarts": restarts,
        "outcomes": [o.as_dict() for o in policy_x.outcomes],
    }
    out = {
        "versions": versions.as_dict(), "encoder": enc.as_dict(),
        "decoder": dec.as_dict(), "readout": policy.as_dict(),
        "baseline": base.as_dict(), "execution_policy": policy_x.as_dict(),
        "python": platform.python_version(), "numpy": np.__version__,
        "symbols": list(symbols), "series_seed0": SERIES_SEED0,
        "series_label": "SYNTHETIC (flytrade.market.synthetic_series)",
        "round_seed": ROUND_SEED, "stats": stats, "trace": trace,
        "elapsed_s": time.time() - t0,
    }
    (HERE / "demo_k8.json").write_text(json.dumps(out, indent=2))
    print(render(out))
    print(f"\nwrote {HERE / 'demo_k8.json'} in {out['elapsed_s']:.1f}s")
    return 0


# --------------------------------------------------------------- render

def render(out: dict) -> str:
    s = out["stats"]
    ex, cr = s["execution"], s["credit"]
    L = []
    a = L.append
    a(f"{s['instruments']} instruments, bars {s['bars'][0]}-{s['bars'][1]}, "
      f"k = {s['k']}: {s['batches']:,} candidate evaluations, "
      f"{s['presentations']:,} presentations of 20 ms.\n")
    a("| | |")
    a("|---|--:|")
    a(f"| completed decision/outcome cycles | {ex['trades']} |")
    a(f"| closed by a neural SELL | "
      f"{ex['close_reasons'].get('NEURAL_SELL', 0)} |")
    a(f"| closed by the horizon (POLICY_CLOSE) | "
      f"{ex['close_reasons'].get('POLICY_CLOSE', 0)} |")
    a(f"| closed at end of data | "
      f"{ex['close_reasons'].get('END_OF_DATA', 0)} |")
    a(f"| wins / losses / flat | {ex['wins']} / {ex['losses']} / "
      f"{ex['flat']} |")
    a(f"| gross PnL | {ex['gross_pnl']:+.2f} |")
    a(f"| fees paid | {ex['fees_paid']:.2f} |")
    a(f"| net realised PnL (**not a gate metric**) | {ex['net_pnl']:+.2f} |")
    a(f"| cash | {ex['cash']:.2f} |")
    a(f"| reinforcements accepted | {cr['accepted']} |")
    a(f"| reinforcements rejected | {cr['rejections_total']} |")
    a(f"| execution rejections | {ex['rejections_total']} "
      f"{ex['rejections'] or ''} |")
    a(f"| rounds aborted (technical failure) | {len(s['rounds_aborted'])} |")
    a(f"| event-log entries | {s['journal']['events']:,} |")
    a("")
    a(f"Decoder output over every decision (one aggregate of k = {s['k']} "
      f"each):\n")
    a("| " + " | ".join(f"`{k}`" for k in sorted(s["decoder_actions"])) + " |")
    a("|" + "--:|" * len(s["decoder_actions"]))
    a("| " + " | ".join(str(s["decoder_actions"][k])
                        for k in sorted(s["decoder_actions"])) + " |")
    a("")
    a("Readout status over every decision:\n")
    a("| " + " | ".join(f"`{k}`" for k in sorted(s["readout_statuses"]))
      + " |")
    a("|" + "--:|" * len(s["readout_statuses"]))
    a("| " + " | ".join(str(s["readout_statuses"][k])
                        for k in sorted(s["readout_statuses"])) + " |")
    a("")
    tot = sum(s["decoder_actions"].values())
    nr = s["decoder_actions"].get("NO_RESPONSE", 0)
    inv = s["readout_statuses"].get("INVALID_STATE", 0)
    a(f"`NO_RESPONSE` **{nr}/{tot}** (unit: decision — a candidate evaluation "
      f"of {s['k']} presentations); `WAIT` "
      f"{s['decoder_actions'].get('WAIT', 0)}/{tot} counted separately; "
      f"`INVALID_STATE` {inv}/{tot} separately from both. Inside the batches, "
      f"**{s['silent_replicates']:,}/{s['silent_replicate_denominator']:,}** "
      f"individual presentations were silent (unit: presentation) — a batch is "
      f"`NO_RESPONSE` only when all {s['k']} of its replicates are.")
    a("")
    r = s["restarts"][0] if s["restarts"] else None
    if r:
        a(f"Mid-run restart at bar {r['bar']} after "
          f"{r['after_trades']} settled episodes: in-memory gains destroyed, "
          f"rebuilt from the checkpoint and the log, "
          f"`{r['report']['action']}`, gains restored exactly: "
          f"**{r['gains_restored_exactly']}**.")
        a("")
    a("### Chronological trace\n")
    a("`u` is the normalised feature vector `(r1, r5, r20, rv20, relvol)`; `V` "
      "the centred valence the fixed decoder computed from the aggregate of "
      "eight; `eligible` the union of the eight replicates' eligible "
      "synapses; `depressed` the ones the one normalised dopamine event "
      "actually moved.\n")
    a("```")
    for t in out["trace"]:
        if t["event"] == "BUY":
            a(f"bar {t['bar']:>3}  BUY  {t['symbol']}  u={t['u']}")
            a(f"          readout approach {t['approach']:>6.2f} Hz  avoid "
              f"{t['avoid']:>6.2f} Hz -> V {t['v']:+7.3f}  "
              f"({t['kc']} Kenyon cells, {t['eligible']:,} eligible synapses "
              f"over 8 replicates, {t['silent_replicates']} of them silent)")
            a(f"          per-replicate decode {t['replicate_actions']}")
            a(f"          selected from {t['candidates']} candidates "
              f"{t['scores']}, filled at {t['fill']}")
        elif t["event"] == "RESTART":
            a(f"bar {t['bar']:>3}  RESTART  {t['detail']}; last settled "
              f"episode {t['last_settled']}; gains restored exactly: "
              f"{t['gains_restored_exactly']}")
        else:
            a(f"bar {t['bar']:>3}  {t['event']}  {t['symbol']}  held "
              f"{t['bars_held']} bars  {t['entry']} -> {t['exit']}  "
              f"net {t['net_pnl']:+.3f} ({t['r']:+.4%})")
            a(f"          dopamine {t['dopamine']} -> one {t['normalisation']} "
              f"event over k = {t['k']}: {t['depressed']:,} synapses "
              f"depressed (per replicate {t['depressed_per_replicate']}), "
              f"{t['weights_moved']:,} weights moved; cash {t['cash']}")
            a(f"          same context, same eight seeds: V "
              f"{t['v_entry']:+.3f} at entry -> "
              f"{t['v_same_context_now']:+.3f} now "
              f"({t['action_same_context_now']})")
    a("```")
    return "\n".join(L)


if __name__ == "__main__":
    raise SystemExit(main())
