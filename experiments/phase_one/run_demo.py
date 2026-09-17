#!/usr/bin/env python
"""
The Phase One vertical slice, end to end — canonical amendment §8.

    .venv/bin/python experiments/phase_one/run_demo.py

Offline and replayable: historical market context -> sensory sequence ->
connectome activity -> fixed neural readout -> instrument/action decision ->
simulated execution -> realised outcome -> episode-specific reinforcement ->
persistent learning -> next decision. Six synthetic instruments, one persistent
learned brain, one open position at a time.

Nothing in here chooses anything on the basis of PnL. The decoder is the one
pre-registered in `docs/DECODER.md` at a commit that precedes every line of
execution code; the execution fixture is the one declared in
`docs/EXECUTION.md`; both are used exactly as written.

## The loop

*Flat.* Evaluate every instrument sequentially from one transient snapshot
under one frozen learned state, decode each with the fixed decoder, select
``argmax V`` with ties to the lowest stable id. If the selected candidate
decodes ``BUY``, the execution policy opens at the next bar's open and the
candidate's stored eligibility trace becomes the open episode, written durably.
Otherwise nothing is executed and the decision is recorded with its status.

*Holding.* Only the held instrument is presented. A decoded ``SELL`` closes the
position (``NEURAL_SELL``); the horizon expiring closes it mechanically
(``POLICY_CLOSE``). The two are never conflated.

*On close.* The net realised PnL maps to a dopamine valence and amount, which
is applied to the episode's **stored** trace through the modulatory matrix,
then the episode is closed and checkpointed. The entry stimulus is presented
once more, with the same seed, so the trace can report what the same market
context now decodes to.

## Mid-run restart

After :data:`RESTART_AFTER_TRADES` settled episodes the demonstration
deliberately destroys its in-memory state — the learned gains are overwritten
with zeros — and rebuilds from the checkpoint and the event log, then carries
on. Amendment §7 asks for restart and replay results; this is them, inside the
run rather than beside it.

Writes ``demo.json`` and regenerates ``results.md``.
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
from flytrade import records as REC      # noqa: E402
from flytrade import runner as R         # noqa: E402

DATA = ROOT / "data" / "malecns-v1.0"
STORE = HERE / "run"

N_INSTRUMENTS = 6
SERIES_SEED0 = 700
ROUND_SEED = 20260911
FIRST_BAR = MK.MIN_HISTORY_BARS - 1
LAST_BAR = 400
RESTART_AFTER_TRADES = 3


def build(fb, mod, ann):
    mb = M.MushroomBody(fb, mod,
                        np.flatnonzero(P.kenyon_cells(ann)),
                        np.flatnonzero(P.mbons(ann)),
                        np.flatnonzero(P.pam(ann)),
                        np.flatnonzero(P.ppl1(ann)))
    enc = E.MarketToSensoryEncoder(ann)
    dec = D.ActionDecoder()
    run = R.BrainRunner(fb, mb, enc, D.readout_populations(ann, mb.compartments))
    return mb, enc, dec, run


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
    mb, enc, dec, run = build(fb, mod, ann)
    credit = R.CreditAssigner(mb)

    symbols = tuple(f"SYN{i:02d}" for i in range(N_INSTRUMENTS))
    series = {s: MK.synthetic_series(s, seed=SERIES_SEED0 + i)
              for i, s in enumerate(symbols)}
    feed = MK.ObservationFeed(series)
    exec_feed = MK.ExecutionFeed(series)
    universe = MK.Universe(symbols)
    policy = X.ExecutionPolicy(exec_feed)

    versions = REC.Versions(market=MK.VERSION, encoder=E.VERSION,
                            runner=R.VERSION, decoder=D.VERSION,
                            execution=X.VERSION, mushroom=M.VERSION,
                            graph_sha256=graph_sha)
    journal = REC.Journal(STORE, mb=mb, credit=credit, versions=versions)
    journal.save_checkpoint(last_settled_episode=-1)

    print(f"{len(symbols)} instruments, bars {FIRST_BAR}..{LAST_BAR}, "
          f"readout {len(run.populations[D.AVOID])} avoid + "
          f"{len(run.populations[D.APPROACH])} approach")

    trace: list[dict] = []
    open_rec: REC.DecisionRecord | None = None
    open_stim = None
    open_seed = None
    open_v = None
    restarts: list[dict] = []
    status_counts: dict[str, int] = {}
    action_counts: dict[str, int] = {}

    def note(**kw):
        trace.append({"bar": kw.pop("bar"), **kw})

    for bar in range(FIRST_BAR, min(LAST_BAR, min(len(s) for s in
                                                  series.values()) - 2)):
        holding = policy.account.position is not None
        scan = ((policy.account.position.symbol,) if holding else symbols)
        obs = [feed.observe(s, bar, stable_id=universe.stable_id(s))
               for s in scan]
        rnd = run.evaluate_round(obs, round_index=bar, round_seed=ROUND_SEED,
                                 score=dec.score)
        journal.record_round(rnd)

        chosen = rnd.selected or (rnd.candidates[0] if holding else None)
        if chosen is None or chosen.presentation is None:
            for c in rnd.candidates:
                status_counts["NO_CANDIDATE"] = status_counts.get(
                    "NO_CANDIDATE", 0) + 1
            continue
        d = dec.decode(chosen.presentation)
        status_counts[d.status.value] = status_counts.get(d.status.value, 0) + 1
        action_counts[d.action.value] = action_counts.get(d.action.value, 0) + 1

        rec = REC.DecisionRecord(
            episode_id=chosen.episode_id, round_index=bar,
            round_seed=ROUND_SEED, candidate_seed=chosen.seed,
            symbol=chosen.symbol, stable_id=chosen.stable_id, bar_index=bar,
            cutoff_ts=chosen.observation.cutoff_ts, wall_clock=time.time(),
            versions=versions.as_dict(),
            checkpoint_digest=journal.checkpoint_digest(),
            observation=chosen.observation.as_dict(),
            stimulus=chosen.stimulus.as_dict(),
            readout=chosen.presentation.as_dict(),
            decoded_action=d.action.value, readout_status=d.status.value,
            decoder=d.as_dict(), trace=chosen.trace.as_dict(),
            n_candidates=len(rnd.candidates), selected=True)

        # ---- flat: may open ------------------------------------------
        if not holding:
            if d.action is not D.Action.BUY:
                journal.record_decision(rec)
                continue
            opened = policy.open_long(episode_id=chosen.episode_id,
                                      symbol=chosen.symbol,
                                      stable_id=chosen.stable_id,
                                      decision_bar=bar)
            if isinstance(opened, X.Rejection):
                rec.readout_status = D.ReadoutStatus.POLICY_REJECT.value
                rec.rejection = opened.as_dict()
                journal.record_decision(rec)
                continue
            journal.record_decision(rec)
            journal.open_episode(rec, chosen.trace, opened.entry.as_dict())
            open_rec, open_stim = rec, chosen.stimulus
            open_seed, open_v = chosen.seed, d.valence_hz
            note(bar=bar, event="BUY", symbol=chosen.symbol,
                 u=[round(float(x), 3) for x in chosen.observation.normalized],
                 approach=round(d.approach_hz, 2), avoid=round(d.avoid_hz, 2),
                 v=round(d.valence_hz, 3), kc=chosen.presentation.kc_active,
                 eligible=chosen.trace.n_eligible,
                 fill=round(opened.entry.fill_price, 4),
                 candidates=len(rnd.candidates),
                 scores={c.symbol: round(rnd.scores[c.stable_id], 2)
                         for c in rnd.candidates if c.stable_id in rnd.scores})
            continue

        # ---- holding: may close --------------------------------------
        journal.record_decision(rec)
        pos = policy.account.position
        reason = None
        if policy.due_for_horizon(bar):
            reason = X.CloseReason.POLICY_CLOSE
        elif d.action is D.Action.SELL:
            reason = X.CloseReason.NEURAL_SELL
        if reason is None:
            continue

        gains_before = mb.gain.copy()
        outcome = policy.close(decision_bar=bar, reason=reason)
        if isinstance(outcome, X.Rejection):
            rec.rejection = outcome.as_dict()
            continue
        valence, amount = policy.reinforcement(outcome)
        if valence == 0:
            ev = R.LearningEvent(episode_id=outcome.episode_id, valence=0,
                                 amount=0.0, accepted=False,
                                 reason="net outcome exactly flat")
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

        # what the very same context decodes to now
        after = None
        if open_stim is not None:
            s0 = run.snapshot()
            pres = run.present(open_stim, seed=open_seed,
                               episode_id=-1, observe=False)
            run.restore(s0)
            after = dec.decode(pres)

        note(bar=bar, event=reason.value, symbol=outcome.symbol,
             v=round(d.valence_hz, 3), bars_held=outcome.bars_held,
             entry=round(outcome.entry.fill_price, 4),
             exit=round(outcome.exit.fill_price, 4),
             net_pnl=round(outcome.net_pnl, 4),
             r=round(outcome.return_on_notional, 5),
             dopamine=f"{'PAM' if valence > 0 else 'PPL1' if valence < 0 else '-'}"
                      f" x{amount:.3f}",
             depressed=ev.synapses_depressed, weights_moved=moved,
             v_entry=round(open_v, 3) if open_v is not None else None,
             v_same_context_now=round(after.valence_hz, 3) if after else None,
             action_same_context_now=after.action.value if after else None,
             cash=round(policy.account.cash, 2),
             realized=round(policy.account.realized_pnl, 4))
        open_rec = open_stim = open_seed = open_v = None

        # ---- mid-run restart -----------------------------------------
        if len(policy.outcomes) == RESTART_AFTER_TRADES and not restarts:
            saved = mb.gain.copy()
            mb.gain[:] = 0.0                       # destroy in-memory state
            mb.apply()
            fresh = R.CreditAssigner(mb)
            journal = REC.Journal(STORE, mb=mb, credit=fresh,
                                  versions=versions)
            report = journal.recover()
            run.mb = mb
            credit = fresh
            restored = bool(np.array_equal(mb.gain, saved))
            restarts.append({"bar": bar, "after_trades": len(policy.outcomes),
                             "report": report,
                             "gains_restored_exactly": restored})
            note(bar=bar, event="RESTART",
                 detail=report["action"],
                 last_settled=report["last_settled_episode"],
                 gains_restored_exactly=restored)
            if not restored:
                raise RuntimeError("restart did not restore the learned gains")

    if policy.account.position is not None:
        out = policy.close(decision_bar=LAST_BAR,
                           reason=X.CloseReason.END_OF_DATA)
        if not isinstance(out, X.Rejection):
            v, a = policy.reinforcement(out)
            if v != 0:
                journal.settle(out.episode_id, out.as_dict(), v, a)

    stats = {
        "instruments": len(symbols), "bars": [FIRST_BAR, LAST_BAR],
        "presentations": run.presentations,
        "decoder_actions": action_counts, "readout_statuses": status_counts,
        "execution": policy.stats(), "credit": credit.stats(),
        "journal": journal.stats(),
        "restarts": restarts,
        "outcomes": [o.as_dict() for o in policy.outcomes],
    }
    out = {
        "versions": versions.as_dict(), "encoder": enc.as_dict(),
        "decoder": dec.as_dict(), "execution_policy": policy.as_dict(),
        "python": platform.python_version(), "numpy": np.__version__,
        "symbols": list(symbols), "series_seed0": SERIES_SEED0,
        "round_seed": ROUND_SEED, "stats": stats, "trace": trace,
        "elapsed_s": time.time() - t0,
    }
    (HERE / "demo.json").write_text(json.dumps(out, indent=2))
    print(render(out))
    write_results(out)
    print(f"\nwrote {HERE / 'demo.json'} and {HERE / 'results.md'} "
          f"in {out['elapsed_s']:.1f}s")
    return 0


# --------------------------------------------------------------- render

def render(out: dict) -> str:
    s = out["stats"]
    ex, cr = s["execution"], s["credit"]
    L = []
    a = L.append
    a(f"{s['instruments']} instruments, bars {s['bars'][0]}-{s['bars'][1]}, "
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
    a(f"| **net realised PnL** | **{ex['net_pnl']:+.2f}** |")
    a(f"| cash | {ex['cash']:.2f} |")
    a(f"| reinforcements accepted | {cr['accepted']} |")
    a(f"| reinforcements rejected | {cr['rejections_total']} |")
    a(f"| execution rejections | {ex['rejections_total']} "
      f"{ex['rejections'] or ''} |")
    a(f"| event-log entries | {s['journal']['events']:,} |")
    a("")
    a("Decoder output over every round (a single 20 ms presentation each):\n")
    a("| " + " | ".join(f"`{k}`" for k in sorted(s["decoder_actions"]))
      + " |")
    a("|" + "--:|" * len(s["decoder_actions"]))
    a("| " + " | ".join(str(s["decoder_actions"][k])
                        for k in sorted(s["decoder_actions"])) + " |")
    a("")
    a("Readout status over every round:\n")
    a("| " + " | ".join(f"`{k}`" for k in sorted(s["readout_statuses"]))
      + " |")
    a("|" + "--:|" * len(s["readout_statuses"]))
    a("| " + " | ".join(str(s["readout_statuses"][k])
                        for k in sorted(s["readout_statuses"])) + " |")
    a("")
    a("### Chronological trace\n")
    a("`u` is the normalised feature vector `(r1, r5, r20, rv20, relvol)` the "
      "encoder saw; `V` the centred valence the fixed decoder computed; "
      "`eligible` the synapses the presentation made eligible; `depressed` "
      "the ones the outcome's dopamine event actually moved.\n")
    a("```")
    for t in out["trace"]:
        if t["event"] == "BUY":
            a(f"bar {t['bar']:>3}  BUY  {t['symbol']}  u={t['u']}")
            a(f"          readout approach {t['approach']:>6.2f} Hz  avoid "
              f"{t['avoid']:>6.2f} Hz -> V {t['v']:+7.3f}  "
              f"({t['kc']} Kenyon cells, {t['eligible']:,} eligible synapses)")
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
            a(f"          dopamine {t['dopamine']} -> {t['depressed']:,} "
              f"synapses depressed, {t['weights_moved']:,} weights moved; "
              f"cash {t['cash']}")
            a(f"          same context, same seed: V {t['v_entry']:+.3f} at "
              f"entry -> {t['v_same_context_now']:+.3f} now "
              f"({t['action_same_context_now']})")
    a("```")
    return "\n".join(L)


def write_results(demo: dict) -> None:
    """Regenerate results.md from the three artefacts."""
    import importlib.util

    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, HERE / path)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    learn = load("ld", "learning_demo.py")
    cred = load("cd", "credit_demo.py")
    lj = json.loads((HERE / "learning.json").read_text())
    cj = json.loads((HERE / "credit.json").read_text())

    v = demo["versions"]
    L = [
        "# Phase One — results", "",
        "Produced by the scripts in this directory against the real "
        "connectome. Every number is generated; nothing is hand-entered.", "",
        f"* graph `{v['graph_sha256'][:12]}` · encoder `{v['encoder']}` · "
        f"decoder `{v['decoder']}` · runner `{v['runner']}` · execution "
        f"`{v['execution']}` · plasticity `{v['mushroom']}`",
        f"* gain {demo['encoder']['global_gain']} (D2, frozen), drive budget "
        f"{demo['encoder']['drive_budget_hz']:,.0f} Hz, carrier "
        f"{demo['encoder']['carrier']}, {demo['encoder']['steps']}-step "
        f"(20 ms) window",
        "* operating-range measurements: `docs/ENCODER.md` and "
        "`encoder_range.json`",
        "* decoder specification: `docs/DECODER.md`, pre-registered alone at "
        "commit `f63825b`",
        f"* python {demo['python']}, numpy {demo['numpy']}", "",
        "## §4 — does reinforcement reach the decoder?", "",
        "`learning_demo.py`, writing `learning.json`. Both branches, four "
        "controls, eight seeds, twenty trials. No price, no position, no PnL: "
        "the reinforcement valence is delivered directly as an experimental "
        "variable.", "",
        learn.render(lj), "",
        "## §5 — episode-specific credit assignment", "",
        "`credit_demo.py`, writing `credit.json`. The amendment's own "
        "scenario: evaluate A, then B, select A, settle A. Reinforcement "
        "reaches the selected episode's **stored** trace (Fable addendum 6), "
        "which is then discarded and the episode closed.", "",
        cred.render(cj), "",
        "## §6 and §8 — the vertical slice, end to end", "",
        "`run_demo.py`, writing `demo.json`. Six seeded synthetic "
        "instruments, one persistent learned brain, one open position at a "
        "time, the execution fixture of `docs/EXECUTION.md` exactly as "
        "declared. No profitability threshold is claimed or sought.", "",
        render(demo), "",
    ]
    (HERE / "results.md").write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
