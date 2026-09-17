#!/usr/bin/env python
"""`d12-001`: the school replay — every eligible candidate is a lesson.

    .venv/bin/python experiments/d12/school.py
    .venv/bin/python experiments/d12/school.py --ticks 100 --label prefix_a
    .venv/bin/python experiments/d12/school.py --determinism

The owner's D12 spec, in code. The LEARNING partition of
``data/pons/d11-backfill-v1`` is replayed from the clean reference with **no
paper position at all**: at every tick every ``admission_v2``-eligible
candidate is presented through the standard k = 8 ``comparison_v1`` readout,
its eligibility trace is kept as a *pending lesson*, and 902 seconds later that
lesson is graded **against the other candidates of its own tick** rather than
against zero.

Nothing in the plasticity rule changes. The brain, the runner, the readout, the
decoder, the trace formation, the ``CreditAssigner`` and the journal are the
objects ``flytrade.pons.loop.PonsLoop`` already drives — this file *drives that
loop's own methods* tick by tick instead of calling ``run_branch``, so tape
bookkeeping, admission, observation building and the ``ROUND`` record cannot
drift from the D11 learning path. Only **where the sign and the amount come
from** (``flytrade.pons.reinforcement.relative_cohort_v1``) and **what triggers
an update** (a matured cohort, not a closed position) are new.

**No socket is opened here, no order is placed, no bankroll moves and no real
money exists anywhere in this wave.**
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import resource
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import d12lib as L                                        # noqa: E402
from common import CADENCE, SETTLE_S                      # noqa: E402  (D11's)
from flytrade import decoder as D                         # noqa: E402
from flytrade import readout as RO                        # noqa: E402
from flytrade import records as REC                       # noqa: E402
from flytrade import runner as R                          # noqa: E402
from flytrade import state as S                           # noqa: E402
from flytrade.market import Universe                      # noqa: E402
from flytrade.pons import context_v2 as CTX2              # noqa: E402
from flytrade.pons import paper as PAPER                  # noqa: E402
from flytrade.pons import reinforcement as RF             # noqa: E402

C = L.C
LOOP = L.LOOP

#: PLAN.md §4: the durable checkpoint file is written this often, and at the
#: end. The digest on every LESSON record is the in-memory one, so the weight
#: history is auditable without a file write per lesson.
CHECKPOINT_EVERY = 500

#: PLAN.md §8: the learning curve and the weight diagnostics sample here.
DIAGNOSTIC_EVERY = 500

#: ``experiments/d10/determinism.py``'s convention, unchanged: the wall clock
#: every event line carries and the absolute checkpoint path are the two fields
#: a second process cannot reproduce by construction.
VOLATILE = ("t", "path")


def normalised_digest(lines) -> tuple[str, int]:
    h = hashlib.sha256()
    n = 0
    for line in lines:
        record = json.loads(line)
        for key in VOLATILE:
            record.pop(key, None)
        h.update(json.dumps(record, sort_keys=True).encode())
        h.update(b"\n")
        n += 1
    return h.hexdigest(), n


def log_digests(path: Path) -> dict:
    rows = [line for line in Path(path).read_text().splitlines() if line.strip()]
    lessons = [line for line in rows if json.loads(line).get("kind") == "LESSON"]
    all_sha, all_n = normalised_digest(rows)
    lesson_sha, lesson_n = normalised_digest(lessons)
    return {"log_normalised_sha256": all_sha, "log_lines": all_n,
            "lesson_log_sha256": lesson_sha, "lesson_lines": lesson_n,
            "normalisation": (f"the fields {list(VOLATILE)} are removed before "
                              f"hashing, as experiments/d10/determinism.py "
                              f"does: a second process cannot reproduce a wall "
                              f"clock or an absolute path")}


def maturity_cutoff(cutoff: int, t0: int, cadence: int = CADENCE) -> int:
    """The first tick on the grid at or after ``cutoff + 902``.

    902 is not a multiple of 30, so this is always ``cutoff + 930`` on this
    grid — 28 s after the outcome the lesson is graded on, never before it.
    """
    need = int(cutoff) + SETTLE_S
    return int(t0) + -(-(need - int(t0)) // int(cadence)) * int(cadence)


def grade_cohort(cohort, labels: dict, *, n_min: int = RF.N_MIN
                 ) -> tuple[list[dict], Counter]:
    """One tick's pending lessons, graded. Pure: no brain, no tape, no I/O.

    ``cohort`` is the pending lessons of one tick and ``labels`` maps a
    lesson's ``stable_id`` to its evaluator label. A member whose label is
    missing or unsettled **leaves the cohort** and is counted ``UNRESOLVED``; a
    cohort with fewer than ``n_min`` survivors teaches nothing and is counted
    ``COHORT_TOO_SMALL``. What comes back is the survivors, each carrying
    ``n``, ``rank`` and ``s``, **in ``stable_id`` order** — the order they are
    applied in — and the counter of what was dropped.
    """
    dropped: Counter = Counter()
    settled = []
    for lesson in cohort:
        label = labels.get(lesson["stable_id"])
        if label is None or not label.get("settled"):
            dropped[RF.UNRESOLVED] += 1
            if label is not None:
                lesson["unresolved_reason"] = label.get("reason") or "UNRESOLVED"
            continue
        lesson["net_wei"] = int(label["net_wei"])
        lesson["net_eth"] = float(label.get("net", 0.0))
        lesson["return_on_notional"] = float(label.get("return_on_notional", 0.0))
        settled.append(lesson)
    n = len(settled)
    if n < int(n_min):
        dropped[RF.COHORT_TOO_SMALL] += n
        return [], dropped
    nets = [lesson["net_wei"] for lesson in settled]
    signals = RF.relative_cohort_signals(nets, n_min=n_min)
    ranks = RF.average_ranks(nets)
    for lesson, rank, s in zip(settled, ranks, signals):
        lesson["n"] = n
        lesson["rank"] = float(rank)
        lesson["s"] = float(s)
    return sorted(settled, key=lambda r: r["stable_id"]), dropped


class School:
    """One school replay: the pending queue, the cohorts, and the lessons."""

    def __init__(self, *, store: Path, ticks: int | None = None,
                 label: str = "school", branch: str | None = None, log=print):
        self.log = log
        self.cfg_v2, self.cfg_run = L.configs()
        self.rule = RF.rule_from_config(self.cfg_run)
        if self.rule != RF.RELATIVE_COHORT_V1:
            raise SystemExit(
                f"experiments/d12/school.py is the {RF.RELATIVE_COHORT_V1} "
                f"teacher; d12_001.json selects {self.rule!r}")
        self.n_min = int(self.cfg_run["reinforcement"][RF.RELATIVE_COHORT_V1]
                         ["n_min"])
        self.sp = L.split()
        self.store = Path(store)
        self.store.mkdir(parents=True, exist_ok=True)
        self.label = label
        #: what the journal stamps on every record. The determinism check runs
        #: the same 100 ticks twice into two directories, and the *name* the
        #: harness gave each run is not a result: both are stamped ``prefix``
        #: so the two LESSON logs can be compared as logs rather than as
        #: labels. Everywhere else it is the label.
        self.branch = str(branch or label)
        directory = L.verify_dataset()
        self.man = C.manifest()

        first = int(self.sp["learning_first_tick"])
        last = int(self.sp["learning_last_tick"])
        if ticks is not None:
            last = min(last, first + (int(ticks) - 1) * CADENCE)
        self.driver = L.PartitionReplayDriver(
            directory, finality=L.finality(), first_tick=first, last_tick=last,
            anchor_ts=int(self.sp["t0"]))
        self.prefix_ticks = ticks

        fb, mb, ann, encoder, pops, run, sha, clean = C.build_brain(self.cfg_v2)
        self.mb, self.encoder, self.runner, self.sha, self.clean = (
            mb, encoder, run, sha, clean)
        mb.gain[:] = np.ones(len(mb.pos), dtype=np.float32)
        mb.trace[:] = 0.0
        mb.trace_episode[:] = -1
        mb.apply()
        self.credit = R.CreditAssigner(mb)
        versions = REC.Versions(
            market=CTX2.VERSION, encoder=encoder.version, runner=R.VERSION,
            decoder=D.VERSION, execution=PAPER.VERSION,
            mushroom=__import__("flytrade.mushroom",
                                fromlist=["VERSION"]).VERSION,
            graph_sha256=sha)
        self.journal = REC.Journal(self.store, mb=mb, credit=self.credit,
                                   versions=versions)
        self.journal.schema_meta = encoder.schema_metadata()
        self.journal.from_clean_reference = True
        self.journal.clean_reference_digest = clean
        self.journal.save_checkpoint(last_settled_episode=-1)

        fixed = self.cfg_run["fixed_for_the_whole_wave"]
        self.gas = C.gas_constants(self.cfg_run)
        execution = PAPER.PonsPaperExecution(
            size_wei=int(fixed["paper_size_wei"]),
            latency_s=int(fixed["latency_seconds"]),
            horizon_s=int(fixed["horizon_seconds"]),
            initial_cash_wei=int(float(fixed["initial_cash_eth"]) * PAPER.WEI),
            reinforce_full_scale=PAPER.reinforce_full_scale_from_config(
                self.cfg_v2),
            reinforce_cap=float(fixed["reinforce_cap"]), **self.gas)
        # the school presents every eligible candidate: no cap, no rotation
        admission = C.admission_v2(self.cfg_v2, require_coverage=True,
                                   max_candidates=10 ** 9)
        self.loop = LOOP.PonsLoop(
            driver=self.driver, run=run, mb=mb, credit=self.credit,
            journal=self.journal, encoder=encoder, admission=admission,
            execution=execution, policy=RO.policy_comparison(),
            universe=Universe(), mode=LOOP.MODE_REPLAY, learning=LOOP.LEARN,
            branch=self.branch, run_id=L.RUN_ID,
            cadence=int(fixed["cadence_seconds"]),
            track_seconds=int(self.cfg_v2["admission"]["track_seconds"]),
            context_fn=CTX2.context_v2,
            entry_deadline_ts=int(self.sp["T"]), log=log)
        self.decoder = self.loop.decoder
        self.clock = self.driver.block_clock

        #: maturity cutoff -> the cohort of pending lessons queued from one tick
        self.pending: dict[int, list[dict]] = {}
        self.applied: list[dict] = []
        self.per_tick: list[dict] = []
        self.discarded: Counter = Counter()
        self.cohorts = {"formed": 0, "too_small": 0, "boundary": 0,
                        "queued_lessons": 0}
        self.status_counts: Counter = Counter()
        self.action_counts: Counter = Counter()
        self.curve: list[dict] = []
        self.weights: list[dict] = []
        self.checkpoints = 0
        self.rejected_by_credit: Counter = Counter()
        self.neutral = 0
        self.accepted = 0

    # ------------------------------------------------------------ lessons
    def queue(self, rnd, cutoff: int, tick: int) -> int:
        """Every presented candidate of this tick becomes a pending lesson."""
        T = int(self.sp["T"])
        beyond = (int(cutoff) + SETTLE_S) > T
        cohort = []
        for c in rnd.candidates:
            if c.presentation is None or c.traces is None:
                continue
            decision = self.decoder.decode(c.presentation)
            self.status_counts[decision.status.value] += 1
            self.action_counts[decision.action.value] += 1
            cohort.append({
                "cutoff_ts": int(cutoff), "tick": int(tick),
                "stable_id": int(c.stable_id), "token": c.symbol,
                "episode_id": int(c.episode_id), "traces": c.traces,
                "valence_hz": float(decision.valence_hz),
                "readout_status": decision.status.value,
                "action": decision.action.value,
            })
        if not cohort:
            return 0
        if beyond:
            # PLAN.md §2: cutoff + 902 > T. Discarded, counted, never applied.
            self.discarded[RF.BOUNDARY] += len(cohort)
            self.cohorts["boundary"] += 1
            return 0
        matures = maturity_cutoff(cutoff, int(self.sp["t0"]))
        if matures in self.pending:                        # cannot happen
            raise SystemExit(f"two cohorts mature at {matures}")
        self.pending[matures] = cohort
        self.cohorts["queued_lessons"] += len(cohort)
        return len(cohort)

    def mature(self, cutoff: int, tick: int) -> dict:
        """Apply the cohort that matures at this tick, before its presentations."""
        cohort = self.pending.pop(int(cutoff), None)
        out = {"applied": 0, "accepted": 0, "neutral": 0, "rejected": 0,
               "discarded": {}}
        if not cohort:
            return out
        source = int(cohort[0]["cutoff_ts"])
        if int(cutoff) < source + SETTLE_S:               # cannot happen
            raise SystemExit(f"a lesson from {source} matured at {cutoff}, "
                             f"before {source + SETTLE_S}")
        labels = {}
        for lesson in cohort:
            tape = self.loop.tapes.get(lesson["token"])
            if tape is None:                               # cannot happen
                continue
            labels[lesson["stable_id"]] = L.safe_label(
                tape, source, self.clock, gas=self.gas)
        settled, dropped = grade_cohort(cohort, labels, n_min=self.n_min)
        if dropped.get(RF.COHORT_TOO_SMALL):
            self.cohorts["too_small"] += 1
        for reason, count in dropped.items():
            self.discarded[reason] += count
        out["discarded"] = dict(dropped)
        if not settled:
            return out
        self.cohorts["formed"] += 1
        # PLAN.md section 2: applied together, in stable_id order
        for lesson in settled:
            self.apply_one(lesson, int(cutoff), int(tick))
            out["applied"] += 1
        out["accepted"] = sum(1 for lesson in settled if lesson.get("accepted"))
        out["neutral"] = sum(1 for lesson in settled
                             if lesson.get("reason") == "neutral")
        out["rejected"] = out["applied"] - out["accepted"] - out["neutral"]
        return out

    def apply_one(self, lesson: dict, cutoff: int, tick: int) -> None:
        valence, amount = RF.reinforcement_for(self.rule, signal=lesson["s"])
        if valence == 0:
            # the existing neutral treatment: nothing is delivered, the episode
            # is closed, and the record says so
            self.credit.open.pop(lesson["episode_id"], None)
            self.credit.settled.add(lesson["episode_id"])
            lesson.update(accepted=False, reason="neutral",
                          synapses_depressed=0)
            self.neutral += 1
        else:
            ev = self.credit.settle(lesson["episode_id"], int(valence),
                                    float(amount), trace=lesson["traces"])
            lesson.update(accepted=bool(ev.accepted), reason=ev.reason,
                          synapses_depressed=int(ev.synapses_depressed or 0),
                          trace_eligible=int(ev.trace_eligible or 0),
                          k=int(ev.k or 0))
            if ev.accepted:
                self.accepted += 1
            else:
                self.rejected_by_credit[str(ev.reason)] += 1
        digest = self.journal.checkpoint_digest()
        lesson["valence"] = int(valence)
        lesson["amount"] = float(amount)
        lesson["applied_at_tick"] = int(tick)
        lesson["applied_at_cutoff_ts"] = int(cutoff)
        lesson["digest_after"] = digest
        self.journal.record_lesson(
            cutoff_ts=lesson["cutoff_ts"], tick=lesson["tick"],
            stable_id=lesson["stable_id"], token=lesson["token"],
            episode_id=lesson["episode_id"], n=lesson["n"],
            net_wei=str(lesson["net_wei"]), net_eth=lesson["net_eth"],
            return_on_notional=lesson["return_on_notional"],
            rank=lesson["rank"], s=lesson["s"],
            valence=int(valence), amount=float(amount),
            rule=self.rule,
            valence_at_presentation_hz=lesson["valence_hz"],
            readout_status_at_presentation=lesson["readout_status"],
            applied_at_tick=int(tick), applied_at_cutoff_ts=int(cutoff),
            accepted=bool(lesson.get("accepted")),
            reason=lesson.get("reason"),
            synapses_depressed=int(lesson.get("synapses_depressed") or 0),
            checkpoint_digest_after=digest,
            clipped=False,
            the_two_columns_are_never_merged=(
                "net_wei is the financial outcome and s is the pedagogical "
                "signal; this is relative cohort reinforcement, not a profit "
                "reward"))
        lesson.pop("traces", None)                # the memory, not the record
        self.applied.append(lesson)
        self.maybe_diagnose()

    # -------------------------------------------------------- diagnostics
    def maybe_diagnose(self) -> None:
        n = len(self.applied)
        if n % DIAGNOSTIC_EVERY:
            return
        self.curve.append(self.learning_curve_point(n))
        digest = self.journal.checkpoint_digest()
        self.weights.append({"lessons": n,
                             **L.weight_diagnostics(self.mb, digest=digest)})
        if n % CHECKPOINT_EVERY == 0:
            self.journal.save_checkpoint(last_settled_episode=int(
                self.applied[-1]["episode_id"]))
            self.checkpoints += 1
        self.log(f"  [{self.label}] {n:,} lessons applied, digest "
                 f"{digest[:12]}, weights at floor "
                 f"{self.weights[-1]['at_floor_fraction']:.4f} / ceiling "
                 f"{self.weights[-1]['at_ceiling_fraction']:.4f}")

    def learning_curve_point(self, n: int) -> dict:
        """Spearman(valence, s) and the mean within-cohort tau over a window.

        The window is the last :data:`DIAGNOSTIC_EVERY` applied lessons — that
        is the curve. The cumulative figure over every lesson so far is
        reported beside it; it is additive and replaces nothing.
        """
        import stats as ST                                 # noqa: PLC0415
        from mirror import kendall_tau_b                    # noqa: PLC0415

        window = self.applied[-DIAGNOSTIC_EVERY:]

        def summarise(rows):
            v = [r["valence_hz"] for r in rows]
            s = [r["s"] for r in rows]
            taus = []
            by_cohort: dict[int, list] = {}
            for r in rows:
                by_cohort.setdefault(r["cutoff_ts"], []).append(r)
            for sub in by_cohort.values():
                if len(sub) < 2:
                    continue
                tau = kendall_tau_b([x["valence_hz"] for x in sub],
                                    [x["s"] for x in sub])
                if tau is not None:
                    taus.append(tau)
            return {"n": len(rows),
                    "spearman_valence_vs_s": ST.spearman(v, s),
                    "cohorts_with_a_tau": len(taus),
                    "mean_within_cohort_kendall_tau": (
                        float(np.mean(taus)) if taus else None)}

        return {"lessons": n, "window": summarise(window),
                "cumulative": summarise(self.applied),
                "window_size": DIAGNOSTIC_EVERY,
                "prospective": ("the brain had not been taught these lessons "
                                "when it scored them")}

    # --------------------------------------------------------------- run
    def run(self) -> dict:
        started = time.time()
        loop = self.loop
        start_digest = self.journal.checkpoint_digest()
        self.journal.record_partition(
            name="SCHOOL", boundary="start", branch=self.branch,
            run_id=L.RUN_ID, learning=True, neural=True, venue=LOOP.VENUE,
            chain_id=LOOP.CHAIN_ID, mode=LOOP.MODE_REPLAY,
            reinforcement_rule=self.rule, dataset=self.driver.as_dict(),
            school=("no paper position is opened or held; every eligible "
                    "candidate is presented and becomes a pending lesson"))
        tick = 0
        t_last = time.time()
        for cutoff in self.driver.ticks(loop.cadence):
            tick += 1
            loop._ingest(self.driver.advance(cutoff))
            loop._refresh_coverage()
            matured = self.mature(int(cutoff), tick)
            considered, presented, omitted = loop._candidates(int(cutoff), tick)
            queued = 0
            if presented:
                contexts = [c.context.as_dict(self.encoder.features)
                            for c in presented]
                extra = loop._round_extra(int(cutoff), tick, considered,
                                          presented, omitted, contexts)
                extra.update({
                    "school": True, "reinforcement_rule": self.rule,
                    "pending_lessons": sum(len(v) for v in
                                           self.pending.values()),
                    "pending_cohorts": len(self.pending),
                    "lessons_applied_this_tick": matured["applied"],
                    "lessons_discarded_this_tick": matured["discarded"],
                    "lessons_applied_total": len(self.applied),
                })
                rnd = loop._evaluate(presented, int(cutoff), tick, extra)
                if rnd is not None:
                    queued = self.queue(rnd, int(cutoff), tick)
            else:
                loop._empty_round(int(cutoff), tick, considered)
            self.per_tick.append({
                "tick": tick, "cutoff_ts": int(cutoff),
                "considered": len(considered), "presented": len(presented),
                "queued": queued,
                "pending_lessons": sum(len(v) for v in self.pending.values()),
                "pending_cohorts": len(self.pending),
                "applied": matured["applied"],
                "discarded": matured["discarded"],
            })
            if tick % 50 == 0:
                now = time.time()
                self.log(f"[{self.label}] tick {tick} cutoff {cutoff}: "
                         f"{len(presented)} presented, "
                         f"{len(self.applied):,} lessons applied, "
                         f"{sum(len(v) for v in self.pending.values())} pending "
                         f"({now - started:.0f}s, {now - t_last:.0f}s since "
                         f"the last note)")
                t_last = now

        # every lesson still pending at the end of the partition is a lesson
        # the boundary took: counted, never applied
        left = sum(len(v) for v in self.pending.values())
        if left:
            self.discarded[RF.BOUNDARY] += left
            self.cohorts["boundary"] += len(self.pending)
            self.pending.clear()

        self.journal.save_checkpoint(last_settled_episode=(
            int(self.applied[-1]["episode_id"]) if self.applied else -1))
        self.checkpoints += 1
        end_digest = self.journal.checkpoint_digest()
        self.journal.record_partition(
            name="SCHOOL", boundary="end", branch=self.branch, run_id=L.RUN_ID,
            venue=LOOP.VENUE, chain_id=LOOP.CHAIN_ID, mode=LOOP.MODE_REPLAY,
            lessons_applied=len(self.applied))
        final_weights = L.weight_diagnostics(self.mb, digest=end_digest)
        if not self.curve or self.curve[-1]["lessons"] != len(self.applied):
            self.curve.append(self.learning_curve_point(len(self.applied)))
            self.weights.append({"lessons": len(self.applied), **final_weights})

        digests = log_digests(self.journal.log.path)
        return {
            "branch": self.branch, "label": self.label, "run_id": L.RUN_ID,
            "mode": LOOP.MODE_REPLAY, "learning": LOOP.LEARN,
            "reinforcement_rule": self.rule, "n_min": self.n_min,
            "school": {
                "no_paper_position": True,
                "every_eligible_candidate_is_presented": True,
                "max_candidates_per_round": None,
                "rotation": False, "hold_mode": False},
            "ticks": tick,
            "prefix_ticks": self.prefix_ticks,
            "partition": {"first_tick": self.driver.first_tick,
                          "last_tick": self.driver.last_tick,
                          "T": int(self.sp["T"])},
            "start_digest": start_digest, "end_digest": end_digest,
            "clean_reference_digest": self.clean,
            "digest_unchanged": start_digest == end_digest,
            "learned_digest": S.learned_state_digest(self.mb.gain, self.mb.pos,
                                                     self.sha),
            "tapes": len(loop.tapes), "tokens_discovered": len(loop.discovered),
            # the school opens no position: these are recorded so a test can
            # assert the zero rather than trust the prose
            "episodes": len(loop.episodes),
            "account": loop.x.account.as_dict(),
            "execution": loop.x.stats(),
            "position_open_at_end": loop.x.account.position is not None,
            "presentations": loop.tally.presentations,
            "candidate_evaluations": loop.tally.batches,
            "tally": loop.tally.as_dict(),
            "readout_status_at_presentation": dict(self.status_counts),
            "decoded_action_at_presentation": dict(self.action_counts),
            "cohorts": self.cohorts,
            "lessons": {
                "applied": len(self.applied),
                "accepted": self.accepted,
                "neutral": self.neutral,
                "rejected_by_credit": dict(self.rejected_by_credit),
                "rejected_by_credit_total": sum(
                    self.rejected_by_credit.values()),
                "discarded": dict(self.discarded),
                "discarded_total": sum(self.discarded.values()),
                "reward": sum(1 for r in self.applied if r["valence"] > 0),
                "punishment": sum(1 for r in self.applied if r["valence"] < 0),
                "amount": {
                    "min": min((r["amount"] for r in self.applied), default=None),
                    "median": (float(np.median([r["amount"] for r in self.applied]))
                               if self.applied else None),
                    "max": max((r["amount"] for r in self.applied), default=None)},
                "clipped": 0,
                "clipping_is_impossible_under_this_rule": True,
            },
            "cohort_size": {
                "min": min((r["n"] for r in self.applied), default=None),
                "median": (float(np.median([r["n"] for r in self.applied]))
                           if self.applied else None),
                "max": max((r["n"] for r in self.applied), default=None)},
            "learning_curve": self.curve,
            "weights": self.weights,
            "final_weights": final_weights,
            "checkpoints_written": self.checkpoints,
            "credit": self.credit.stats(),
            "journal": self.journal.stats(),
            "log_path": str(self.journal.log.path),
            "log_bytes": self.journal.log.path.stat().st_size,
            **digests,
            "per_tick": self.per_tick,
            "wall_s": round(time.time() - started, 2),
        }


def lessons_jsonl(applied, path: Path) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for row in applied:
            fh.write(json.dumps({k: v for k, v in row.items()
                                 if k != "traces"}, default=str) + "\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", default=str(L.RUNS))
    parser.add_argument("--label", default="school")
    parser.add_argument("--ticks", type=int, default=None,
                        help="run only the first N LEARNING ticks")
    parser.add_argument("--determinism", action="store_true",
                        help="run the first 100 ticks twice and compare")
    args = parser.parse_args(argv)

    run_dir = Path(args.runs_dir) / L.RUN_ID
    run_dir.mkdir(parents=True, exist_ok=True)
    logf = (run_dir / f"{args.label}.log").open("a")

    def log(*a, **kw):
        kw.pop("flush", None)
        print(*a, **kw)
        print(time.strftime("%H:%M:%S", time.gmtime()), *a, file=logf)
        logf.flush()
        sys.stdout.flush()

    if args.determinism:
        return determinism(run_dir, log=log)

    t0 = time.time()
    log(f"[{args.label}] starting "
        f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"
        + (f", first {args.ticks} ticks only" if args.ticks else ""))
    school = School(store=run_dir / args.label, ticks=args.ticks,
                    label=args.label, log=log)
    out = school.run()
    out["python"] = platform.python_version()
    out["numpy"] = np.__version__
    out["peak_rss_mib"] = round(
        resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1)
    lessons_jsonl(school.applied, run_dir / args.label / "lessons.jsonl")
    L.atomic_write_json(run_dir / f"{args.label}_summary.json", out)
    log(f"[{args.label}] {out['ticks']:,} ticks, "
        f"{out['lessons']['applied']:,} lessons applied "
        f"({out['lessons']['reward']:,} reward / "
        f"{out['lessons']['punishment']:,} punishment / "
        f"{out['lessons']['neutral']:,} neutral), "
        f"{out['lessons']['discarded_total']:,} discarded, digest "
        f"{out['start_digest'][:12]} -> {out['end_digest'][:12]} in "
        f"{(time.time() - t0) / 60:.1f} min")
    logf.close()
    return 0


def determinism(run_dir: Path, *, log=print) -> int:
    """PLAN.md §10: the first 100 LEARNING ticks twice, compared."""
    out = {}
    for label in ("prefix_a", "prefix_b"):
        store = run_dir / "determinism" / label
        if store.exists():
            import shutil
            shutil.rmtree(store)
        log(f"[determinism] {label}: the first 100 LEARNING ticks")
        # the same branch stamp for both: the name the harness gave a run is
        # not a result, and the two LESSON logs must differ in nothing at all
        school = School(store=store, ticks=100, label=label, branch="prefix",
                        log=log)
        out[label] = school.run()
    a, b = out["prefix_a"], out["prefix_b"]
    report = {
        "version": "d12-001-determinism-1",
        "ticks": 100,
        "rule": ("the first 100 LEARNING ticks of the school replay, run twice "
                 "from the clean reference, give an identical checkpoint "
                 "digest and an identical sha256 of the LESSON log"),
        "first": {k: a[k] for k in ("end_digest", "learned_digest",
                                    "lesson_log_sha256", "lesson_lines",
                                    "log_normalised_sha256", "log_lines",
                                    "ticks", "wall_s")},
        "second": {k: b[k] for k in ("end_digest", "learned_digest",
                                     "lesson_log_sha256", "lesson_lines",
                                     "log_normalised_sha256", "log_lines",
                                     "ticks", "wall_s")},
        "lessons_applied": a["lessons"]["applied"],
        "digest_identical": a["end_digest"] == b["end_digest"],
        "lesson_log_identical": (a["lesson_log_sha256"] == b["lesson_log_sha256"]
                                 and a["lesson_lines"] == b["lesson_lines"]),
        "whole_log_identical": (
            a["log_normalised_sha256"] == b["log_normalised_sha256"]
            and a["log_lines"] == b["log_lines"]),
        "normalisation": a["normalisation"],
        "both_runs_are_stamped": "prefix",
        "why": ("the journal stamps its branch on every record; the two runs "
                "live in two directories but are stamped with one name, so a "
                "difference in the logs can only be a difference in the run"),
    }
    L.atomic_write_json(run_dir / "determinism.json", report)
    log(json.dumps({k: report[k] for k in
                    ("lessons_applied", "digest_identical",
                     "lesson_log_identical", "whole_log_identical")}, indent=1))
    if not (report["digest_identical"] and report["lesson_log_identical"]):
        raise SystemExit("the school replay is not deterministic")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
