# D12 — school mode: relative cohort reinforcement

One section, registered **before any D12 number exists** (step (ii) of the
register-then-compute order). It is committed together with
`experiments/d12/d12_001.json` and with nothing else.

## `d12-001` — the teacher changes, and nothing else does

The owner's D12 spec (`docs/SPEC.md`, 2026-09-13, verbatim) and the fourteen
Fable addenda beneath it are the authority; this section is the operational
form of addendum 4 (ii) and restates no number that D11 already registered.

### 0. What moves and what does not

`d11-001` ran the absolute rule — *lost money → punishment* — and produced 15
episodes, 0 rewards, 15 punishments and a trained ranking that is close to the
untrained one inverted. D12 changes **one thing: the teacher.** Every other
object is the same object:

* the store `data/pons/d11-backfill-v1`, unchanged, read-only, no collection,
  no RPC, no live hour, no real money;
* the same 30-second tick grid anchored at `t0`, the same cutoff
  `T = t0 + 30,240 s`, the same LEARNING and FROZEN partitions and the same
  boundary rules `common.split()` computes;
* the clean reference `ba95b60503d6…`, `pons_encoder_v2` (input schema
  `3bf4f34c…`), `admission_v2`, readout k = 8 under `comparison_v1`, the stored
  k = 8 decoder, horizon 900 s, latency 2 s, the plasticity operator of
  `flytrade.mushroom` and its learning rate, no forgetting;
* the evaluator-only fixed-15-minute net label of `experiments/d11/common.py`
  `label_row`, integer-exact, which creates no trade and touches no checkpoint;
* the FROZEN grid rows, their labels and the REFERENCE scores, **reused** from
  `experiments/d11/runs/d11-001/grid/` rather than recomputed — the sha256 of
  each reused file is recorded in the run summary, and at least 200 rows are
  re-scored under the clean reference and compared at 1e-9 Hz before any
  comparison is made. If a single row disagrees the wave stops and says so.

The absolute rule stays byte-identical behind `reinforcement.rule =
absolute_profit_v1`, which is what a D10 and a D11 configuration select (a
configuration with no `rule` key selects it too). The new rule is selected by
`reinforcement.rule = relative_cohort_v1`. PONS is not touched and no wallet
feature enters the brain.

### 1. School mode

The LEARNING branch **opens no paper position and holds none.** There is no
bankroll, no entry, no exit and no PnL in the school; the financial columns
that appear on a lesson are the evaluator's, not an account's.

At every LEARNING tick (`cutoff <= T`):

1. the driver advances the recorded event stream to the cutoff and the tapes
   with it, exactly as the D11 replay does;
2. every `admission_v2`-eligible candidate is presented — **no cap of six, no
   rotation, no hold mode** — through the standard readout: k = 8 replicates
   under `comparison_v1`, seeded from `(observation_id, stable_id, replicate)`
   and not from the learned state, decoded once by the stored k = 8 decoder;
3. one `ROUND` record carries every presented candidate, as today;
4. each presented candidate's **eligibility trace set** — the k traces
   `BrainRunner.evaluate_round` already builds for every candidate, the same
   object the D11 learning path stores for the one it bought — is kept as a
   *pending lesson* keyed `(cutoff_ts, stable_id)`, together with the valence
   the readout produced at presentation.

Nothing in the plasticity rule changes: the same
`CreditAssigner.settle` → `MushroomBody.proposed_gain_delta` path, the same
learning rate, the same floor, the same mean-of-k-deltas normalisation. Only
**where the sign and the amount come from**, and **what triggers an update**,
are new.

### 2. Maturity, the pending queue, and no lookahead

A lesson matures at the **first tick whose `cutoff >= lesson cutoff + 902 s`**
(latency 2 s + horizon 900 s). Because 902 is not a multiple of the 30-second
cadence, that tick is always `lesson cutoff + 930 s`, which is 28 s after the
outcome the lesson is computed from: the brain is never taught an outcome
before that outcome exists.

* Matured lessons **of one cohort are applied together, in `stable_id` order,
  before that tick's presentations.**
* A lesson whose `cutoff + 902 > T` is **discarded, counted and never
  applied.** No lesson is ever applied at a FROZEN tick; the school replay does
  not run one.
* A presentation without a matured lesson changes no weight.
* The queue is bounded by construction: at most 31 ticks of lessons are pending
  at once. Its size, the lessons applied and the lessons discarded by reason
  are recorded per tick.

### 3. The relative signal, `relative_cohort_v1`

The **cohort** is the eligible candidates of one tick that have a settled
evaluator label. A member whose label is `UNRESOLVED` (route transition,
coverage, an exhausted curve) **leaves the cohort and is counted**; it never
becomes a lesson.

Let `n` be the cohort size after those drops and let the ranks be **ascending
by net, with average ranks for ties** (`rank = 1` is the worst net):

```
s_i = 2 * (rank_i - 1) / (n - 1) - 1     in [-1, +1]
```

so the worst is `-1`, the best is `+1`, and the mean of `s` over a cohort is
exactly 0 by construction. `net` is the label's **integer wei** figure
(`net_wei`), not its float rendering.

* **`n_min = 3`.** A cohort with `n < 3` produces **no lesson at all**, and is
  counted.
* `s > 0` is a reward, `s < 0` a punishment, of **amount `|s|`**.
* `s == 0` is neutral: **no update**, the existing neutral treatment, recorded
  as an accepted-nothing lesson.
* **No clipping can occur.** `REINFORCE_CAP` and `reinforce_full_scale` are not
  consulted by this rule and appear nowhere in its arithmetic.
* Rank rather than z-score: scale-free, immune to the tail that saturated two
  calibrations, and zero-mean per cohort by construction.

**Known answer, registered here.** Both of the owner's examples —
`+14 / +3 / −2 / −7 / −18 / −61 %` and `−3 / −8 / −15 / −28 / −50 / −82 %` —
give `s = +1, +0.6, +0.2, −0.2, −0.6, −1`. A test asserts both before the rule
is ever run on the store.

**The financial net and the pedagogical signal are two columns and are never
merged.** A cohort in which every member lost money still teaches which member
lost least. That is an explicitly different objective and it is called
*relative cohort reinforcement*, never a profit reward. Nothing here
falsifies a profit: the net is reported as it is.

### 4. Records

* `LESSON` — a new record kind — carries `cutoff_ts`, `stable_id`, `token`,
  cohort size `n`, `net_wei`, `rank`, `s`, `valence_at_presentation_hz`,
  `applied_at_tick` and the **checkpoint digest after** the update.
* `ROUND` for every presented candidate, as today.
* Per tick: the pending-queue size, lessons applied, lessons discarded by
  reason (`UNRESOLVED`, `COHORT_TOO_SMALL`, `BOUNDARY`).
* The durable checkpoint file is written every 500 applied lessons and at the
  end of the partition; the digest **recorded on every LESSON record** is the
  in-memory digest of the weights immediately after that lesson, so the
  weight-by-weight history is auditable without 13,000 file writes. Declared
  here, before the run.
* The final checkpoint is `SCHOOL` and its digest is recorded in the run
  summary and in the scoring manifest.

### 5. The mirror diagnostic (the owner's cheap account, before any new run)

Computed in step (iii) from the **existing** `d11-001` score files
`grid/scores_trained.jsonl` and `grid/scores_reference.jsonl`, over the rows
`VALID` in both, and written to `experiments/d12/mirror_diagnostic.md`:

* Pearson `r`, Spearman `ρ` and Kendall `τ` between trained and reference
  valence;
* OLS `trained = a + b · reference` with `R²`;
* the fraction of row pairs whose order is reversed;
* the same per temporal block and **within tick** (cohort-wise `τ` — the
  quantity that matters for ranking);
* `AUC(−reference)` beside `AUC(trained)`, and the residual of `AUC(trained)`
  from `1 − AUC(reference)`.

**Wording: numbers.** The mechanistic reading — that fifteen punishments
depressed the approach pathway in proportion to the prior valence, so the
trained valence is a decreasing affine function of the untrained one — is a
**hypothesis** that `b` and `τ` test. It is not a finding until the owner
states it as one.

### 6. The two grids

Same grid machinery as `d11-001`, same rows, same labels.

* **Primary** — FROZEN rows on tokens that were **never a lesson**: tokens
  whose first `admission_v2` eligibility is at a tick `>= T`. These are the
  owner's *"tokens posteriores que ela nunca recebeu como aula"*. The
  token-disjointness is enforced by address and is asserted by a test.
* **Secondary** — **all** FROZEN rows, reported regardless of the verdict, for
  comparability with `d11-001`'s 5,013 labelled rows.

Branches: **SCHOOL** (the final LEARNING checkpoint) and **REFERENCE** (the
clean brain, scores reused). Both brains are loaded read-only and their digests
are verified before and after every scoring pass.

### 7. Statistics

As D11-001 addendum 9, unchanged:

* `ΔAUC = AUC(SCHOOL) − AUC(REFERENCE)` over rows `VALID` in both branches that
  carry a settled label;
* AUC is Mann–Whitney `U / (n_pos · n_neg)` with ties counted one half;
* uncertainty is a **paired cluster bootstrap by `stable_id`** — a token's rows
  move together — with **10,000** resamples at seed **20260913** and a
  percentile **95 %** interval, **overall and per temporal block**, on the
  **primary** and on the **secondary** grid;
* descriptive beside it: Spearman(score, net) per branch, the distribution of
  the per-row score difference, and the suppression check (BUY-crossing rate
  per branch, overall, per block and by later outcome class).

**Pre-registered readings, fixed here and not rewritten afterwards:**

| interval | what is written |
|---|---|
| entirely above 0 | *the school-trained ranking of later tokens is higher than the untrained one, not compatible with sampling variation* |
| includes 0 | *compatible with sampling variation* |
| entirely below 0 | *the inversion persists* |

Never "significant", never "proves", no rate asserted as measured, and an AUC
near 0.5 is not evidence that no signal exists. A lower BUY rate alone is not
learning success. Profit is not learning.

### 8. Learning curve and weights, descriptive

For **every** lesson: the valence at presentation and the `s` that arrives
902 s later. Rolling over LEARNING, every **500 applied lessons**:

* Spearman between valence-at-presentation and `s`;
* the mean within-cohort Kendall `τ` between valence and `s`.

Both are **prospective by construction**: the brain has not yet been taught
those lessons when it scores them.

Every **500 applied lessons**, the plastic KC→MBON weights: mean, L2 norm, the
fraction at the floor (`gain <= 0.25 + 1e-9`) and the fraction at the ceiling
(`gain >= 1.0 − 1e-9`), with the checkpoint digest.

**A property of the operator, registered before the run so it cannot be
mistaken for a result:** the plasticity rule only depresses, the clean
reference starts with **every** gain exactly at `1.0`, and the ceiling is
`1.0`. A synapse "at the ceiling" is therefore a synapse **no lesson has ever
depressed**. The floor fraction and the ceiling fraction are reported
separately as well as summed, so the reader can see which one the combined
number is made of. The condition below is applied exactly as addendum 9 words
it; the split is additive and loosens nothing.

### 9. The inconclusive conditions, pre-registered and not loosened

1. fewer than **2,000** lessons applied;
2. fewer than **100** paired labels on the **primary** grid;
3. either outcome class under **20** on the **primary** grid;
4. paired coverage under **95 %**;
5. encoder saturation over **5 %** of (row, channel) pairs, or `INVALID_STATE`
   over **5 %**;
6. more than **25 %** of plastic synapses at floor or ceiling at the end of
   LEARNING.

The secondary grid is reported regardless of the verdict. These thresholds are
not loosened after the run. Three of them are pre-computable and are checked in
step (iii), before the brain runs at all: a **lesson ceiling under 2,000**, a
**primary grid under 100 labelled rows**, or a **class under 20** ends the wave
with the numbers and no neural run.

### 10. Determinism

The first **100 LEARNING ticks** of the school replay, run twice from the clean
reference, give an **identical checkpoint digest** and an **identical sha256 of
the LESSON log**. A test asserts it. The full run is not repeated.

### 11. Frozen loop branches, descriptive

SCHOOL and REFERENCE replays over the FROZEN partition with paper trading as in
`d11-001` — one position at a time, `SETTLED_FROZEN`, end digest equal to start
digest. Their PnL and action frequencies are **the** paper results of this
wave. **The LEARNING branch has no paper results by design**, and the report
says so rather than leaving a blank.

### 12. The order, and where each step stops

| step | commit | contains |
|---|---|---|
| (i) | `a661cbb` | the owner's spec and the fourteen addenda |
| (ii) | this commit | `PLAN.md` **and** `d12_001.json`, **alone**, before any D12 number exists |
| (iii) | numbers only | the lesson ceiling and the cohort-size distribution from the market-only tracker (**no brain**), the primary and secondary FROZEN row counts and class balances, and `mirror_diagnostic.md` from the existing `d11-001` scores |
| then | the run | the school replay, the SCHOOL scoring pass, the two frozen loops, the report |

Nothing is re-chosen after a result: not `T`, not the cadence, not `n_min`, not
the rule, not the learning rate, not the horizon, not a threshold, not the
statistics. If something cannot be done as specified, the deviation is declared
in this plan, in the report and in `the session log`, and **nothing is absorbed
silently**.

### 13. What `d12-001` cannot say

It cannot say that the fly is profitable, and it is not asked to. It cannot
attribute a difference to anything but the teaching rule *within this window* —
one brain saw 8.4 hours of school and one saw none. It cannot compare itself
with `d10-001`, which ran another environment on another window; it compares
itself with `d11-001` only on the **secondary** grid, which is the same rows,
the same labels and the same reference scores, and that comparison is
descriptive.
