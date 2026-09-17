#!/usr/bin/env python
"""
The historical run — D6 §4, §5 and §6, exactly as PROTOCOL.md pre-registers it.

    .venv/bin/python experiments/historical/run.py

Three partitions over two real instruments, then one untrained reference branch
over the frozen partition:

    WARMUP    2026-08-03..08-14   features only, no brain, no decisions
    LEARNING  2026-08-17..08-28   the complete loop, learning on
    FROZEN    2026-08-31..09-04   learning and forgetting off, twice:
                                  the learned checkpoint, and a clean one

Nothing in here chooses a number. Every parameter is read from `config.json`,
which was committed alone before this file existed; the two instruments are
verified against the hashes recorded there; the clean reference checkpoint is
verified against the digest recorded there; and the run refuses to start if any
of them disagrees.

Writes `runs/<run_id>/` (gitignored: event log, checkpoints, pending episode)
and `summary.json` + `comparison.json` beside this file.
"""
from __future__ import annotations

import json
import platform
import resource
import sys
import time
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "upstream"))

from flytrade import decoder as D          # noqa: E402
from flytrade import encoder as E          # noqa: E402
from flytrade import execution as X        # noqa: E402
from flytrade import graph as G            # noqa: E402
from flytrade import historical as H       # noqa: E402
from flytrade import market as MK          # noqa: E402
from flytrade import mushroom as M         # noqa: E402
from flytrade import populations as P      # noqa: E402
from flytrade import readout as RO         # noqa: E402
from flytrade import records as REC        # noqa: E402
from flytrade import runner as R           # noqa: E402
from flytrade import state as S            # noqa: E402

DATA = ROOT / "data" / "malecns-v1.0"
MARKET = ROOT / "data" / "market"
RUNS = HERE / "runs"
CONFIG = HERE / "config.json"

#: settled episodes after which the LEARNING partition destroys its in-memory
#: state and rebuilds it from the checkpoint and the log. Declared here, not
#: chosen by what happened.
RESTART_AFTER_TRADES = 3

#: D9(b) §2 — the exit policy, the one behavioural switch this loop carries.
#:
#: ``neural_or_horizon``
#:     D5/D6/D7, **the default**: a decoded SELL while holding closes the
#:     position (``NEURAL_SELL``); the horizon closes it otherwise
#:     (``POLICY_CLOSE``).
#: ``fixed_hold``
#:     D9(b): a decoded SELL while holding is refused by the execution policy
#:     with ``RejectReason.FIXED_HOLD`` and closes nothing; the position closes
#:     only at the declared horizon, labelled ``POLICY_CLOSE_FIXED_HOLD``.
#:
#: Entry is the decoder's in both: nothing here forces a trade. Only the exit
#: changes, and the default value is what every committed run so far used.
NEURAL_OR_HORIZON = "neural_or_horizon"
FIXED_HOLD = "fixed_hold"
EXIT_POLICIES = (NEURAL_OR_HORIZON, FIXED_HOLD)


# --------------------------------------------------------------- helpers

def allocate_run_id() -> str:
    RUNS.mkdir(parents=True, exist_ok=True)
    n = 1
    while (RUNS / f"hist-{n:03d}").exists():
        n += 1
    return f"hist-{n:03d}"


def sha256_file(path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Tally:
    """Three denominators, never pooled (PROTOCOL §7)."""

    def __init__(self):
        self.per_candidate = Counter()          # status/action of one batch
        self.per_candidate_action = Counter()
        self.per_instrument = defaultdict(Counter)
        self.per_round = Counter()              # after selection
        self.per_round_action = Counter()
        self.after_execution = Counter()        # what became an order
        self.market_status = defaultdict(Counter)
        self.silent_replicates = 0
        self.presentations = 0
        self.batches = 0
        self.invalid_replicates = 0

    def as_dict(self) -> dict:
        return {
            "per_candidate_evaluation": {
                "status": dict(self.per_candidate),
                "action": dict(self.per_candidate_action),
                "n": sum(self.per_candidate.values())},
            "per_decision_round": {
                "status": dict(self.per_round),
                "action": dict(self.per_round_action),
                "n": sum(self.per_round.values())},
            "after_execution_constraints": dict(self.after_execution),
            "per_instrument": {k: dict(v) for k, v in self.per_instrument.items()},
            "market_status_per_instrument": {
                k: dict(v) for k, v in self.market_status.items()},
            "silent_replicates": self.silent_replicates,
            "silent_replicate_denominator": self.presentations,
            "invalid_replicates": self.invalid_replicates,
            "candidate_evaluations": self.batches,
            "presentations": self.presentations,
        }


# ------------------------------------------------------------- the brain

def build_brain(cfg):
    import flysim
    fb = flysim.FlyBrain(graph_path=DATA / "graph.npz")
    mod = G.ModulatoryGraph(DATA / "graph_mod.npz", bodies=fb.bodies)
    ann = P.Annotations.load(DATA / "annotations.npz")
    sha = G.sha256_file(DATA / "graph.npz")
    want = cfg["brain"]["clean_reference_checkpoint"]["graph_sha256"]
    if sha != want:
        raise SystemExit(f"graph sha256 {sha[:12]} != the pre-registered "
                         f"{want[:12]}: the run is refused")
    mb = M.MushroomBody(fb, mod,
                        np.flatnonzero(P.kenyon_cells(ann)),
                        np.flatnonzero(P.mbons(ann)),
                        np.flatnonzero(P.pam(ann)),
                        np.flatnonzero(P.ppl1(ann)))
    enc = E.MarketToSensoryEncoder(ann)
    pops = D.readout_populations(ann, mb.compartments)
    run = R.BrainRunner(fb, mb, enc, pops, graph_sha256=sha)
    clean = S.learned_state_digest(mb.gain, mb.pos, sha)
    want_dig = cfg["brain"]["clean_reference_checkpoint"]["state_digest"]
    if clean != want_dig:
        raise SystemExit(f"clean reference digest {clean[:12]} != the "
                         f"pre-registered {want_dig[:12]}: the run is refused")
    return fb, mb, ann, enc, pops, run, sha, clean


def load_market(cfg):
    series, reports = {}, {}
    for spec in cfg["instruments"]:
        path = MARKET / spec["file"]
        if not path.exists():
            raise SystemExit(f"{path} is absent; see data/MANIFEST.md")
        got = sha256_file(path)
        if got != spec["sha256"]:
            raise SystemExit(
                f"{spec['symbol']}: sha256 {got[:16]} != the manifested "
                f"{spec['sha256'][:16]}. The file on disk is not the file the "
                f"protocol was registered against; the run is refused rather "
                f"than silently substituting a dataset.")
        s = H.load_series(path, spec["symbol"])
        if s.report.rows != spec["rows"]:
            raise SystemExit(f"{spec['symbol']}: {s.report.rows} rows, "
                             f"{spec['rows']} registered")
        series[spec["symbol"]] = s
        reports[spec["symbol"]] = s.report.as_dict()
    return series, reports


# -------------------------------------------------------------- the loop

def run_branch(*, name, cfg, series, parts, partitions, run, mb, enc, pops,
               sha, policy_for, run_id, learn_in, start_gain, round_base=0,
               restart_after=None, log=print, runs_dir=None,
               horizon_minutes=None, exit_policy=NEURAL_OR_HORIZON):
    """One branch: a sequence of partitions over one brain and one account.

    ``runs_dir`` and ``horizon_minutes`` are D7 additions and both default to
    the D5/D6 behaviour: the run store lives under this directory's ``runs/``
    and the holding horizon is the one in the committed config. The D7 wave
    passes its own run directory and the horizon its WARMUP calibration
    selected, so that one loop serves both experiments instead of a second
    copy of the decision loop drifting away from this one.

    ``exit_policy`` is the D9(b) addition and defaults to
    :data:`NEURAL_OR_HORIZON`, which is exactly what D5/D6/D7 ran: with the
    default, every branch of this function behaves as it did before the flag
    existed, and a test asserts the closure sequence event for event.
    """
    if str(exit_policy) not in EXIT_POLICIES:
        raise SystemExit(f"unknown exit_policy {exit_policy!r}; "
                         f"expected one of {EXIT_POLICIES}")
    fixed_hold = str(exit_policy) == FIXED_HOLD
    #: what a horizon expiry is called in this branch. A separate reason, not
    #: a relabelling: the log says which policy the run was under.
    horizon_close = (X.CloseReason.POLICY_CLOSE_FIXED_HOLD if fixed_hold
                     else X.CloseReason.POLICY_CLOSE)
    fb = run.fb
    mb.gain[:] = start_gain
    mb.trace[:] = 0.0
    mb.trace_episode[:] = -1
    mb.apply()

    store = (RUNS if runs_dir is None else Path(runs_dir)) / run_id / name
    credit = R.CreditAssigner(mb)
    versions = REC.Versions(market=MK.VERSION, encoder=E.VERSION,
                            runner=R.VERSION, decoder=D.VERSION,
                            execution=H.HistoricalExecution.version,
                            mushroom=M.VERSION, graph_sha256=sha)
    journal = REC.Journal(store, mb=mb, credit=credit, versions=versions)
    journal.save_checkpoint(last_settled_episode=-1)

    xcfg = cfg["execution"]

    def new_account():
        """A fresh account per partition.

        Nothing crosses a partition boundary — no position, no pending
        episode — so a partition's accounting starts flat. That is what makes
        the frozen partition's numbers comparable between the learned and the
        reference branch: neither carries the other's history.
        """
        return H.HistoricalExecution(
            series, notional=xcfg["notional"], fee_bps=xcfg["fee_bps"],
            slippage_bps=xcfg["slippage_bps"],
            delay_minutes=xcfg["delay_minutes"],
            horizon_minutes=(xcfg["horizon_minutes"]
                             if horizon_minutes is None else
                             int(horizon_minutes)),
            initial_cash=xcfg["initial_cash"],
            reinforce_full_scale=xcfg["reinforce_full_scale"],
            reinforce_cap=xcfg["reinforce_cap"])

    pol_x = new_account()
    accounts: dict[str, H.HistoricalExecution] = {}

    symbols = tuple(s["symbol"] for s in cfg["instruments"])
    stable = {s["symbol"]: s["stable_id"] for s in cfg["instruments"]}
    out = {"branch": name, "exit_policy": str(exit_policy), "partitions": {},
           "restarts": [], "aborted": []}
    rix = int(round_base)
    trace: list[dict] = []

    for part in partitions:
        p = next(x for x in parts if x.name == part)
        t0 = time.time()
        tally = Tally()
        pol_x = new_account()
        accounts[part] = pol_x
        exposure_minutes = 0
        grid = H.round_grid(series, p.first, p.last)
        learning_on = part in learn_in
        policy = policy_for(part)
        dec = policy.decoder
        journal.record_partition(name=part, boundary="start", branch=name,
                                 rounds=len(grid), learning=learning_on,
                                 neural=p.neural, run_id=run_id)
        start_digest = journal.checkpoint_digest()
        log(f"[{run_id}/{name}] {part} {p.first}..{p.last}: {len(grid)} rounds, "
            f"neural={p.neural} learning={learning_on} "
            f"exit_policy={exit_policy}", flush=True)

        # every instrument's market status at every round minute, whether or
        # not it was scanned: the denominator of the market-side taxonomy
        for day, m in grid:
            for sym in symbols:
                tally.market_status[sym][series[sym].status(day, m).value] += 1

        if not p.neural:
            per_session = defaultdict(Counter)
            for day, m in grid:
                for sym in symbols:
                    per_session[day][f"{sym}:{series[sym].status(day, m).value}"] += 1
            for day in sorted(per_session):
                journal.record_warmup(session=str(day),
                                      counts=dict(per_session[day]),
                                      observations=len(symbols) * sum(
                                          1 for d, _ in grid if d == day))
            out["partitions"][part] = {
                "first": str(p.first), "last": str(p.last),
                "rounds": len(grid), "neural": False, "learning": False,
                "decisions": 0, "note": "features only; no brain was run",
                "tally": tally.as_dict(),
                "start_digest": start_digest,
                "end_digest": journal.checkpoint_digest(),
                "wall_s": round(time.time() - t0, 2)}
            journal.record_partition(name=part, boundary="end", branch=name,
                                     run_id=run_id)
            continue

        cur_day = None
        for day, m in grid:
            if day != cur_day:
                if pol_x.account.position is not None:
                    _session_close(journal, pol_x, credit, learning_on, trace,
                                   tally, cur_day, partition=part, branch=name)
                pol_x.start_session(day)
                cur_day = day
            rix += 1
            holding = pol_x.account.position is not None
            scan = ((pol_x.account.position.symbol,) if holding else symbols)
            obs = [series[s].observe(day, m, stable_id=stable[s]) for s in scan]
            if holding:
                exposure_minutes += 1

            try:
                rnd = run.evaluate_round(obs, round_index=rix, readout=policy,
                                         score=policy.score)
            except RO.TechnicalFailure as exc:
                journal.record_round_aborted(round_index=rix,
                                             cutoff_ts=obs[0].cutoff_ts,
                                             reason=str(exc))
                out["aborted"].append({"round": rix, "day": str(day),
                                       "minute": m, "reason": str(exc)})
                continue
            journal.record_round(rnd)

            for c in rnd.candidates:
                if c.presentation is None:
                    continue
                tally.batches += 1
                tally.presentations += c.k
                if c.batch is not None:
                    tally.silent_replicates += c.batch.silent_replicates
                    tally.invalid_replicates += c.batch.invalid_replicates
                dc = dec.decode(c.presentation)
                tally.per_candidate[dc.status.value] += 1
                tally.per_candidate_action[dc.action.value] += 1
                tally.per_instrument[c.symbol][dc.status.value] += 1
                tally.per_instrument[c.symbol][f"action:{dc.action.value}"] += 1

            chosen = rnd.selected or (rnd.candidates[0] if holding else None)
            if chosen is None or chosen.presentation is None:
                tally.per_round["NO_USABLE_CANDIDATE"] += 1
                # D7: a candidate that was measured but is not selectable —
                # the decoder read NO_RESPONSE or INVALID_STATE while the
                # account was flat — still produced a readout, and the D7
                # evaluator's probe grid is branch-blind and inventory-blind
                # by construction. Writing the event here is log-only: no
                # weight, account, seed, order or counter changes, and the
                # round still takes no decision. Without it the probe dataset
                # would silently depend on which branch happened to be
                # holding a position, which amendment D7 section 6 forbids.
                for c in rnd.candidates:
                    if c.presentation is None:
                        continue
                    dc = dec.decode(c.presentation)
                    journal.record_decision(REC.decision_record(
                        c, dc, round_index=rix, bar_index=m,
                        versions=versions,
                        checkpoint_digest=journal.checkpoint_digest(),
                        n_candidates=len(rnd.candidates),
                        readout_policy=policy.as_dict(), partition=part,
                        branch=name, run_id=run_id,
                        dataset_label=H.DATASET_LABEL, selected=False))
                # a horizon that fell due while the instrument had no usable
                # readout still closes: a timer is not a decision
                if holding and pol_x.due_for_horizon(m) \
                        and series[pol_x.account.position.symbol].bar(day, m):
                    _close(journal, pol_x, credit, learning_on, trace, tally,
                           day, m, horizon_close, None, rec=None,
                           partition=part, branch=name)
                continue

            d = dec.decode(chosen.presentation)
            tally.per_round[d.status.value] += 1
            tally.per_round_action[d.action.value] += 1
            rec = REC.decision_record(
                chosen, d, round_index=rix, bar_index=m, versions=versions,
                checkpoint_digest=journal.checkpoint_digest(),
                n_candidates=len(rnd.candidates),
                readout_policy=policy.as_dict(), partition=part, branch=name,
                run_id=run_id, dataset_label=H.DATASET_LABEL)

            if not holding:
                if d.action is not D.Action.BUY:
                    tally.after_execution[f"NO_ORDER:{d.action.value}"] += 1
                    journal.record_decision(rec)
                    continue
                opened = pol_x.open_long(episode_id=chosen.episode_id,
                                         symbol=chosen.symbol,
                                         stable_id=chosen.stable_id,
                                         decision_bar=m, day=day)
                if isinstance(opened, X.Rejection):
                    rec.readout_status = D.ReadoutStatus.POLICY_REJECT.value
                    rec.rejection = opened.as_dict()
                    tally.after_execution[
                        f"POLICY_REJECT:{opened.reason.value}"] += 1
                    journal.record_decision(rec)
                    continue
                journal.record_decision(rec)
                journal.open_episode(rec, chosen.traces,
                                     {**opened.entry.as_dict(),
                                      "market_ts": opened.entry.ts,
                                      "partition": part, "branch": name})
                tally.after_execution["BUY"] += 1
                if opened.entry.flag:
                    tally.after_execution[opened.entry.flag] += 1
                trace.append({"event": "BUY", "day": str(day), "minute": m,
                              "symbol": chosen.symbol,
                              "episode_id": chosen.episode_id,
                              "v": round(d.valence_hz, 3),
                              "fill": round(opened.entry.fill_price, 4),
                              "flag": opened.entry.flag,
                              "partition": part})
                continue

            reason = blocked = None
            if pol_x.due_for_horizon(m):
                reason = horizon_close
            elif d.action is D.Action.SELL:
                if fixed_hold:
                    # D9(b) §2: the decoder did decide SELL, and that stays in
                    # the log. Under this exit policy the execution policy
                    # refuses to act on it, so nothing is sold, no outcome is
                    # settled, no reward or punishment is delivered and no
                    # stored trace is touched. It is a signal, not a sale.
                    blocked = pol_x.reject(
                        "SELL", pol_x.account.position.symbol, m,
                        X.RejectReason.FIXED_HOLD)
                    rec.readout_status = D.ReadoutStatus.POLICY_REJECT.value
                    rec.rejection = blocked.as_dict()
                else:
                    reason = X.CloseReason.NEURAL_SELL
            journal.record_decision(rec)
            if blocked is not None:
                tally.after_execution["blocked_by_fixed_hold"] += 1
                continue
            if reason is None:
                tally.after_execution[f"HOLD:{d.action.value}"] += 1
                continue
            _close(journal, pol_x, credit, learning_on, trace, tally, day, m,
                   reason, d, rec=rec, partition=part, branch=name)

            # ---- one declared mid-run restart, as the demos do ----------
            if (restart_after is not None and learning_on
                    and not out["restarts"]
                    and len(pol_x.outcomes) >= restart_after):
                saved = mb.gain.copy()
                mb.gain[:] = 0.0                    # destroy in-memory state
                mb.apply()
                credit = R.CreditAssigner(mb)
                journal = REC.Journal(store, mb=mb, credit=credit,
                                      versions=versions)
                report = journal.recover()
                restored = bool(np.array_equal(mb.gain, saved))
                out["restarts"].append({
                    "day": str(day), "minute": m, "round": rix,
                    "after_settled_episodes": len(pol_x.outcomes),
                    "report": report,
                    "gains_restored_exactly": restored})
                log(f"[{run_id}/{name}] restart at {day} {m}: "
                    f"{report['action']}; gains restored exactly: {restored}",
                    flush=True)
                if not restored:
                    raise SystemExit("restart did not restore the learned "
                                     "gains; the run is refused")

        if pol_x.account.position is not None:
            _session_close(journal, pol_x, credit, learning_on, trace, tally,
                           cur_day, partition=part, branch=name)

        end_digest = journal.checkpoint_digest()
        journal.record_partition(name=part, boundary="end", branch=name,
                                 run_id=run_id)
        out["partitions"][part] = {
            "first": str(p.first), "last": str(p.last), "rounds": len(grid),
            "neural": True, "learning": learning_on,
            "start_digest": start_digest, "end_digest": end_digest,
            "digest_unchanged": start_digest == end_digest,
            "tally": tally.as_dict(),
            "execution": pol_x.stats(),
            "credit": credit.stats(),
            "journal": {"settled_frozen": journal.frozen_settled},
            "exposure_market_minutes": exposure_minutes,
            "wall_s": round(time.time() - t0, 2),
            "policy": policy.as_dict()["namespace"]}
        log(f"[{run_id}/{name}] {part} done in "
            f"{out['partitions'][part]['wall_s']}s, trades "
            f"{pol_x.stats()['trades']}, digest "
            f"{start_digest[:12]} -> {end_digest[:12]}", flush=True)

    every = [o for a in accounts.values() for o in a.outcomes]
    out["execution"] = {
        "trades": len(every),
        "wins": sum(1 for o in every if o.net_pnl > 0),
        "losses": sum(1 for o in every if o.net_pnl < 0),
        "flat": sum(1 for o in every if o.net_pnl == 0),
        "gross_pnl": sum(o.gross_pnl for o in every),
        "gross_reference_pnl": sum(o.gross_reference_pnl for o in every),
        "slippage_paid": sum(o.slippage for o in every),
        "fees_paid": sum(o.fees for o in every),
        "net_pnl": sum(o.net_pnl for o in every)}
    out["accounts"] = {k: a.account.as_dict() for k, a in accounts.items()}
    out["credit"] = credit.stats()
    out["journal"] = journal.stats()
    out["outcomes"] = [o.as_dict() for o in every]
    out["trace"] = trace
    out["final_digest"] = journal.checkpoint_digest()
    out["log_path"] = str(journal.log.path)
    out["log_sha256"] = sha256_file(journal.log.path)
    out["log_bytes"] = journal.log.path.stat().st_size
    out["execution_policy"] = pol_x.as_dict()
    out["exit_policy"] = str(exit_policy)
    return out, journal, accounts, credit


def _reinforce(journal, credit, pol_x, outcome, learning_on, tally, *,
               partition="", branch=""):
    """One settled outcome: one normalised learning event, or none if frozen."""
    payload = {**outcome.as_dict(),
               "account": pol_x.account.as_dict(),
               "cumulative_realized_pnl": round(
                   pol_x.account.realized_pnl, 8),
               "market_ts": outcome.exit.ts,
               "partition": partition, "branch": branch}
    if not learning_on:
        journal.settle_frozen(outcome.episode_id, payload)
        tally.after_execution["SETTLED_FROZEN"] += 1
        return None
    valence, amount = pol_x.reinforcement(outcome)
    if valence == 0:
        ev = R.LearningEvent(episode_id=outcome.episode_id, valence=0,
                             amount=0.0, accepted=False,
                             reason="net outcome exactly flat", k=RO.K)
        journal.log.append(REC.EventType.OUTCOME,
                           {"episode_id": outcome.episode_id, **payload})
        journal.log.append(REC.EventType.LEARNING,
                           {"episode_id": outcome.episode_id, **ev.as_dict()})
        REC.clear_pending(journal.pending_path)
        credit.open.pop(outcome.episode_id, None)
        credit.settled.add(outcome.episode_id)
        return ev
    return journal.settle(outcome.episode_id, payload, valence, amount)


def _close(journal, pol_x, credit, learning_on, trace, tally, day, m, reason,
           d, *, rec=None, partition="", branch=""):
    outcome = pol_x.close(decision_bar=m, reason=reason, day=day)
    if isinstance(outcome, X.Rejection):
        tally.after_execution[f"CLOSE_REJECT:{outcome.reason.value}"] += 1
        if rec is not None:
            rec.rejection = outcome.as_dict()
        return None
    ev = _reinforce(journal, credit, pol_x, outcome, learning_on, tally,
                    partition=partition, branch=branch)
    tally.after_execution[reason.value] += 1
    if outcome.exit.flag:
        tally.after_execution[outcome.exit.flag] += 1
    trace.append({"event": reason.value, "day": str(day), "minute": m,
                  "symbol": outcome.symbol, "episode_id": outcome.episode_id,
                  "net_pnl": round(outcome.net_pnl, 4),
                  "market_minutes_held": outcome.market_minutes_held,
                  "flag": outcome.exit.flag,
                  "depressed": ev.synapses_depressed if ev else 0,
                  "v": round(d.valence_hz, 3) if d is not None else None})
    return outcome


def _session_close(journal, pol_x, credit, learning_on, trace, tally, day, *,
                   partition="", branch=""):
    p = pol_x.account.position
    last = pol_x.session_last_minute(day, p.symbol)
    outcome = pol_x.close(decision_bar=last, reason=X.CloseReason.POLICY_CLOSE,
                          day=day, session_close=True)
    if isinstance(outcome, X.Rejection):
        tally.after_execution[f"CLOSE_REJECT:{outcome.reason.value}"] += 1
        return None
    _reinforce(journal, credit, pol_x, outcome, learning_on, tally,
               partition=partition, branch=branch)
    tally.after_execution["POLICY_CLOSE"] += 1
    tally.after_execution["SESSION_CLOSE_FILL"] += 1
    trace.append({"event": "SESSION_CLOSE", "day": str(day), "minute": last,
                  "symbol": outcome.symbol,
                  "net_pnl": round(outcome.net_pnl, 4),
                  "market_minutes_held": outcome.market_minutes_held,
                  "flag": outcome.exit.flag})
    return outcome


# ---------------------------------------------------------------- main

def main() -> int:
    t_start = time.time()
    cfg_path = Path(sys.argv[1]) if len(sys.argv) > 1 else CONFIG
    cfg = json.loads(cfg_path.read_text())
    run_id = allocate_run_id()
    (RUNS / run_id).mkdir(parents=True, exist_ok=True)
    logf = (RUNS / run_id / "run.log").open("w")

    def log(*a, **kw):
        kw.pop("flush", None)
        print(*a, **kw)
        print(*a, file=logf)
        logf.flush()
        sys.stdout.flush()

    log(f"run {run_id} starting {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
    fb, mb, ann, enc, pops, run, sha, clean = build_brain(cfg)
    series, reports = load_market(cfg)
    log(f"graph {sha[:12]}, clean reference digest {clean[:12]}, "
        f"{len(mb.pos):,} plastic synapses, readout "
        f"{len(pops[D.AVOID])} avoid + {len(pops[D.APPROACH])} approach")

    base = RO.load_baseline(ROOT / cfg["readout"]["baseline_artifact"],
                            k=cfg["readout"]["k"], graph_sha256=sha)
    if base.theta_hz != RO.THETA_HZ_K8 or base.baseline_hz != RO.BASELINE_HZ_K8:
        raise SystemExit("the loaded baseline is not the stored artifact")
    log(f"baseline loaded exactly: BASELINE {base.baseline_hz!r}, "
        f"SD {base.sd_hz!r}, theta {base.theta_hz!r}")

    parts = H.partitions_from(cfg["partitions"])
    coverage = {s: series[s].coverage(parts[0].first, parts[-1].last)
                for s in series}
    for s, c in coverage.items():
        log(f"{s}: {c['n_days']} sessions, {c['bars']:,} bars, "
            f"{c['missing']:,} missing minutes in the window")

    def policy_for(part):
        return (RO.policy_comparison() if part == "FROZEN"
                else RO.policy_k8())

    clean_gain = np.ones(len(mb.pos), dtype=np.float32)

    # ---- branch 1: the learned brain, all three partitions --------------
    learned, j1, x1, c1 = run_branch(
        name="learned", cfg=cfg, series=series, parts=parts,
        partitions=["WARMUP", "LEARNING", "FROZEN"], run=run, mb=mb, enc=enc,
        pops=pops, sha=sha, policy_for=policy_for, run_id=run_id,
        learn_in={"LEARNING"}, start_gain=clean_gain, round_base=0,
        restart_after=RESTART_AFTER_TRADES, log=log)
    learned_gain = mb.gain.copy()
    learned["clean_reference_digest"] = clean
    learned["learned_digest"] = S.learned_state_digest(learned_gain, mb.pos, sha)

    # ---- branch 2: the untrained reference, FROZEN only ------------------
    reference, j2, x2, c2 = run_branch(
        name="reference", cfg=cfg, series=series, parts=parts,
        partitions=["FROZEN"], run=run, mb=mb, enc=enc, pops=pops, sha=sha,
        policy_for=policy_for, run_id=run_id, learn_in=set(),
        start_gain=clean_gain, round_base=0, log=log)
    reference["clean_reference_digest"] = clean

    elapsed = time.time() - t_start
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    summary = {
        "run_id": run_id,
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                     time.gmtime(t_start)),
        "elapsed_s": round(elapsed, 1),
        "peak_rss_mib": round(peak, 1),
        "python": platform.python_version(), "numpy": np.__version__,
        "machine": platform.processor() or platform.machine(),
        "config": cfg,
        "dataset_label": H.DATASET_LABEL,
        "vendor_reports": reports,
        "coverage": coverage,
        "graph_sha256": sha,
        "clean_reference_digest": clean,
        "baseline": base.as_dict(),
        "encoder": enc.as_dict(),
        "decoder": RO.decoder_k8().as_dict(),
        "readout_learning": RO.policy_k8().as_dict(),
        "readout_frozen": RO.policy_comparison().as_dict(),
        "branches": {"learned": learned, "reference": reference},
    }
    summary["config_path"] = str(cfg_path)
    out_name = "summary.json" if cfg_path == CONFIG else "smoke_summary.json"
    (HERE / out_name).write_text(json.dumps(summary, indent=1, default=str))
    log(f"run {run_id} finished in {elapsed / 60:.1f} min, peak RSS "
        f"{peak:.0f} MiB")
    log(f"learned  final digest {learned['final_digest'][:12]}  "
        f"trades {learned['execution']['trades']}  "
        f"net {learned['execution']['net_pnl']:+.2f}")
    log(f"reference final digest {reference['final_digest'][:12]}  "
        f"trades {reference['execution']['trades']}  "
        f"net {reference['execution']['net_pnl']:+.2f}")
    logf.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
