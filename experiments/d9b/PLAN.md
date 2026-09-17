# D9(b) — the target-aligned fixed-hold experiment

**RETROSPECTIVE COMPARISON ON PREVIOUSLY EXAMINED DATES.**
Every date below was already examined by D7 and again by D8. This is not a new
untouched holdout, and no report of this wave may call it one.

This file and `config.json` are committed **alone, before any D9(b) run
exists**. Nothing here is chosen after a number is seen.

Canonical: `docs/SPEC.md`, section *D9(b) — target-aligned fixed-hold
experiment*, its owner rationale and its fourteen Fable addenda. Where this
file and the amendment differ, the amendment governs; the one place this file
knowingly corrects an addendum is §5 below, and it says so.

---

## 1. The question

D8 measured that D7 reinforced one quantity and evaluated another: all 42
LEARNING episodes exited before the horizon, at holds of 1 to 19 market
minutes, while the evaluator scored a 90-minute hold on the same entries, and
the two disagreed in sign on 17 of 42. This wave runs the experiment in which
**the quantity used for reinforcement is the quantity used for evaluation**.

It tests **entry-context selection**. It does not test learned exit timing,
and it is not a correction to D7's recorded results, which stand.

## 2. What changes, exactly

One flag, `exit_policy`, in the shared loop `experiments/historical/run.py`:

| value | behaviour |
|---|---|
| `neural_or_horizon` | **the default** — D5/D6/D7, unchanged: a decoded SELL while holding closes the position (`NEURAL_SELL`); the horizon closes it otherwise (`POLICY_CLOSE`) |
| `fixed_hold` | **this wave** — a decoded SELL while holding is refused by the execution policy with `RejectReason.FIXED_HOLD` and closes nothing; the position closes only at the declared horizon, labelled `CloseReason.POLICY_CLOSE_FIXED_HOLD` |

Under `fixed_hold`:

* when flat, the **existing neural decision** determines entry. No entry is
  forced to manufacture a training example;
* after a fill, one position is kept open; it is never increased and never
  reversed;
* a neural SELL observed while holding stays in the diagnostic log as a
  **signal blocked by the fixed-hold policy** — recorded as a rejection in the
  decision's execution record and tallied under `blocked_by_fixed_hold`. It is
  never an executed sale, and it produces no reward, no punishment and no
  change to any stored trace;
* the decoder, gain, thresholds, k, MBON membership, sizing, delay, fees,
  slippage and the normalised learning rule are **not** modified to compensate
  for removing early exits.

Nothing else in `flytrade/` changes: two enum members
(`CloseReason.POLICY_CLOSE_FIXED_HOLD`, `RejectReason.FIXED_HOLD`) and the
routing that uses them.

## 3. One target definition — the anchor

Read from the code before any of this was written:

* `HistoricalExecution.open_long` fills at the open of the first available bar
  with `bar_start >= decision minute + delay`, and sets
  `horizon_bar = entry fill minute + H`;
* `HistoricalExecution.close` under a policy closure locates its exit bar at
  `max(round minute, horizon_bar)` through `flytrade.horizon.locate`;
* `flytrade.horizon.Hold` — the evaluator's label — locates its exit at
  `entry_minute + H` through the **same** `locate`, and its `net_return` is
  documented as computed exactly as `ExecutionPolicy._settle` computes a
  realised outcome.

**The anchor is the entry fill minute.** H = 90 market minutes are counted
from it, by both the executed episode and the evaluator's label, through one
primitive. The execution delay is unchanged at 1 market minute and no fill
uses its own decision bar.

**Invariant.** For every completed `POLICY_CLOSE_FIXED_HOLD` outcome, the
realised net PnL equals `Hold.net_pnl` for the same decision minute, H, delay,
notional and costs. Expected **exactly**; the tolerance of `1e-9` is a float
guard, not a modelling allowance. Reported per episode with the maximum
absolute difference, never assumed. If it breaks, the run is reported
`INVARIANT_BROKEN` and no AUC conclusion is drawn from it.

**Boundaries.** `eligible_to_enter` refuses any entry whose horizon would
cross the session: `(m+1) + 1 + 90 <= 390`, so the last eligible decision
minute is **298**. Nothing crosses a day and therefore nothing crosses a
partition.

**Exceptional closures.** A missing price at a due fill or settlement is a
recorded `Rejection`, never an invented price. A position still open at the
session's last available bar closes at that bar's close with
`SESSION_CLOSE_FILL`; `END_OF_DATA` keeps its own label. These keep their
accounting and their log lines, are **counted apart**, and are never reported
as exact-H outcomes.

## 4. Reinforcement

One completed episode produces **at most one** normalised learning update,
attributed to the entry decision's stored eligibility trace set
(`eligibility_source = replayed_from_decision`) — never to an observation made
later while the position was open. No intermediate-PnL reward, no
counterfactual reward for a skipped entry, no reward from a blocked SELL, no
repeated punishment for one open position. The net-outcome reward rule and the
costs are unchanged.

**The STOP condition of addendum 3, discharged before this file was
committed.** D7 only ever settled episodes held 1 to 19 minutes; a fixed hold
settles them 90 rounds later. `tests/d9b/test_eligibility_replay.py` captures
one k = 8 stored trace set, runs **90 full intervening k = 8 decision rounds**
against it — 720 presentations, 720 `clear_episode` calls, the live
eligibility layer written and cleared 90 times — and asserts that the
resulting `LearningEvent` and the resulting gains are identical to the
1-round arm, with `TRACE_EXPIRED` zero. It passes. Had it failed, the wave
would have stopped before any run: changing decay or eligibility is a science
change the owner has not authorised.

## 5. Expected activity, stated before the run

A decision at minute *m* fills at *m+1* and closes at *m+91*; the next
decision is at *m+92*, fills at *m+93* and closes at *m+183*. D7's event log
shows the first usable observation of a LEARNING session at market minute 20,
so the chain of a fully occupied session is

    20 -> 111,  112 -> 203,  204 -> 295,  296 -> 387

and a fifth entry would need a decision at minute 388, past the last eligible
minute 298. **At most 4 completed episodes per session, at most 40 per branch**
over 10 sessions.

> **Correction to Fable addendum 5, declared here and not absorbed.** The
> addendum states at most 3 per session and 30 per branch. The arithmetic
> above gives 4 and 40. The corrected bound is recorded before the run so it
> cannot be read as a result.

The realised number will be lower: an entry also needs a decoded BUY inside
the open window, and vendor gaps delay fills. D7 executed 42 LEARNING entries
over 3,699 rounds under an exit policy that released the inventory after 1 to
19 minutes; a 90-minute lock-out necessarily produces fewer.

**The 36.6 % LEARNING-grid positive base rate predicts nothing about the
reward rate of this policy.** Selected entries and occupied inventory change
which episodes actually occur.

## 6. INCONCLUSIVE rule, stated numerically before the run

* **fewer than 10 completed LEARNING episodes** → INCONCLUSIVE for the
  learning side;
* **fewer than 5 qualifying FROZEN sessions** under D7's rule — at least 10
  probes of each label class in the session, paired coverage at least 0.95 —
  → INCONCLUSIVE for the frozen comparison.

Either firing, the wave reports INCONCLUSIVE plainly and draws no conclusion
about discrimination in either direction. Activity is never manufactured: the
dates, the decoder, the thresholds and the seeds are not changed to produce
more trades. **A negative scientific result does not fail the engineering
gate.**

## 7. Frozen evaluation

Two branches over FROZEN 2026-07-20..07-31, learning and forgetting off,
start digest asserted equal to end digest:

* `frozen_trained` — from the final LEARNING checkpoint of this wave;
* `frozen_reference` — from the clean untrained reference
  `ba95b60503d6…`.

Seeds are `comparison_v1`, **independent of the learned-state digest**, so a
difference between the branches is a difference in weights and not in noise.

The evaluation is D7's, reused and not touched: `experiments/d9b/evaluate.py`
imports `probe_grid`, `labels` and `frozen_decisions` from
`experiments/d7/evaluate.py`, which is not modified, and
`withheld probe table` must be **byte-identical** at the end of the
wave. Common probe grid (`status OK and (m+1)+delay+H <= 390`, computed from
the calendar and the price file before any event log is opened), the same
continuous score `DECISION.valence_hz`, the same coverage rules, the same
per-session AUC with ties at 0.5, the same `DELTA_AUC`, the same 2,000-draw
paired session bootstrap at seed `3219987367`, the same 0.20 top fraction.

**Actual paper trading is reported separately from hypothetical probe
labels**, and context *ranking* is compared, not the number of BUY actions.

## 8. What is delivered

Configuration and provenance; checkpoint hashes; the chronological event log;
the target-alignment invariant table; the actual episode / holding-duration
table with exit reasons including exceptional closures, reward and punishment
counts, BUY / SELL / WAIT / NO_RESPONSE, the blocked-SELL count and
gross / net / costs; the frozen comparison with paired differences and
session-level intervals; the regression suite run twice; commits, a clean tree
and an updated `the session log`.

The existing observer opens the new run through its existing contract — one
new root and two label mappings, no redesign.

## 9. Allowed conclusions

* **negative** → "no improvement detected under the fixed-hold policy on these
  periods";
* **positive** → evidence of context discrimination **in this experiment**;
  not general trading ability, not profitability, not skill;
* **inconclusive** → too few completed episodes or qualifying sessions, per §6.

Never "the fly learned". The 36.6 % grid base rate predicts nothing. D7's
conclusion B and D8's conclusions stand unrewritten.

## 10. Order of work

1. `PLAN.md` + `config.json`, **alone**  ← this commit
2. the flag, the two enum members, the routing and their tests
3. the observer mapping and its tests
4. the run: `run.py learn`, `run.py frozen`, `evaluate.py`, `alignment.py`,
   `results.md`, the JSON artifacts
5. `the session log`

Event logs and checkpoints stay gitignored, as for D7. Stop after D9(b): no
live data, no static hosting, no real execution.
