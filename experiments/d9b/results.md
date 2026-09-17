# D9(b) — the target-aligned fixed-hold experiment (d9b-002)

**RETROSPECTIVE COMPARISON ON PREVIOUSLY EXAMINED DATES.** Every date below was already examined by D7 and again by D8: every date below was already examined by D7 and D8. This is not a new untouched holdout and no report may call it one.

## What this is, and what it is not

This wave runs the experiment in which **the quantity used for reinforcement is the quantity used for evaluation**: the fly chooses when to enter, the position is held for the declared H = 90 market minutes, and the reinforcement is the net outcome of exactly that hold. It tests **entry-context selection**. It does not test learned exit timing, and it is not a correction to D7's recorded results, which stand unrewritten together with D8's.

Reading rules, fixed before the numbers existed:

* **negative** → no improvement detected under the fixed-hold policy on these periods
* **positive** → evidence of context discrimination in this experiment; NOT general trading ability, NOT profitability, NOT skill
* **inconclusive** → too few completed episodes or qualifying sessions under the rule above

* never: any phrasing of the form 'the fly learned'
* never: inferring the realised reward rate from the 36.6 % LEARNING-grid positive base rate: selected entries and occupied inventory change which episodes occur
* never: rewriting D7 conclusion B or any D8 conclusion
* never: calling these dates a pristine or untouched holdout
* never: reading a negative scientific result as an engineering-gate failure

## 1. Provenance

| item | value |
|---|---|
| run | `d9b-002`, stages `learn` + `frozen` |
| exit policy | `fixed_hold` |
| H | 90 market minutes, from `the registered horizon artifact` (`bb494cac316e…`), not recalibrated |
| instrument | IBM, `IBM_1min_unadjusted.txt`, sha256 `b1ace385f069…` |
| graph | `8feb08a0d2a8…` |
| clean reference digest | `ba95b60503d6…` |
| trained digest | `f4ddbf0de147…` |
| config | `experiments/d9b/config.json`, `7781a1b985fc…`, committed alone before any run |
| python · numpy | 3.13.9 · 2.4.2 |
| learn | 20.0 min, peak RSS 675 MiB |
| frozen | 41.3 min, peak RSS 682 MiB |

Other run directories on disk: `d9b-001`. They are **not** this result. `config.json` fixes the rule they fall under — *a retry after a software correction gets a new run id; the failed run's directory and its explanation are kept and reported* — and the explanation is in `the session log`. Every number in this file comes from `d9b-002` alone.

Partitions, D7's own, unchanged:

| partition | dates | sessions | neural | learning |
|---|---|---|---|---|
| WARMUP | 2026-06-15 .. 2026-07-02 | 13 | False | False |
| LEARNING | 2026-07-06 .. 2026-07-17 | 10 | True | True |
| FROZEN | 2026-07-20 .. 2026-07-31 | 10 | True | False |

## 2. One target definition — the anchor and the invariant

**the exit is the open of the first available bar with bar_start >= the ENTRY FILL minute + H, in the same session**, located by `flytrade.horizon.locate` — the one primitive the executed exit and the evaluator's `Hold` both call. Entry: the open of the first available bar with bar_start >= decision minute + delay, same session; delay = 1, unchanged. No same-bar hindsight fill.

| invariant | value |
|---|---|
| episodes compared | 73 |
| same entry **and** exit bar as the label | 73 |
| entry or exit bar displaced (sequencing guard or vendor gap) | 0 |
| max \|realised − label\| | `2.220446049250313e-16` |
| tolerance registered in the plan | `1e-09` |
| holds | **True** |
| max \|as recorded in the log − label\| | `4.898696559507698e-09` |
| label unavailable | 0 |

_the event log rounds net_pnl to 8 decimals, so a comparison read back from it cannot be tighter than 5e-9._ The per-episode table is `experiments/d9b/alignment.md`; the machine-readable form, with every price and every difference, is `alignment.json`.

## 3. Actual paper trading

This section is the **executed** experiment. It is reported apart from the hypothetical probe labels of §4, which are counterfactuals on a grid and were never traded.

| branch | episodes | exact-H | exceptional | held min/med/max | reward | punishment | frozen | net |
|---|---|---|---|---|---|---|---|---|
| learned | 28 | 28 | 0 | 90/90/90 | 12 | 16 | 0 | -84.5388 |
| frozen_trained | 13 | 13 | 0 | 90/90/90 | 0 | 0 | 13 | -30.7302 |
| frozen_reference | 32 | 32 | 0 | 90/90/90 | 0 | 0 | 32 | +17.3507 |

Exit reasons, counted apart. Only `POLICY_CLOSE_FIXED_HOLD` is an exact-H outcome; a session close or an end of data keeps its own label and is never presented as one.

| branch | POLICY_CLOSE_FIXED_HOLD | SESSION_CLOSE_FILL | END_OF_DATA | NEURAL_SELL |
|---|---|---|---|---|
| learned | 28 | 0 | 0 | 0 |
| frozen_trained | 13 | 0 | 0 | 0 |
| frozen_reference | 32 | 0 | 0 | 0 |

What the decoder did, and what the execution policy did with it. A SELL observed while holding is a **signal blocked by the fixed-hold policy**, not an executed sale, and it produced no reward, no punishment and no change to any stored trace.

| branch | rounds decoded | BUY | SELL | WAIT | NO_RESPONSE | blocked SELL | entries filled |
|---|---|---|---|---|---|---|---|
| learned | 3699 | 1020 | 1015 | 1598 | 65 | 609 | 28 |
| frozen_trained | 3700 | 22 | 2613 | 963 | 102 | 834 | 13 |
| frozen_reference | 3700 | 1488 | 425 | 1723 | 64 | 341 | 32 |

Money, at the unchanged costs (5 bps fee and 5 bps modelled slippage per execution, 20 bps over a completed round trip):

| branch | gross at reference | fees | slippage | net | cost > gross |
|---|---|---|---|---|---|
| learned | -28.5954 | 27.9717 | 27.9717 | -84.5388 | 3 of 28 |
| frozen_trained | -4.7480 | 12.9911 | 12.9911 | -30.7302 | 6 of 13 |
| frozen_reference | +81.4001 | 32.0247 | 32.0247 | +17.3507 | 8 of 32 |

Expected activity, **stated in `config.json` before the run**: at most 4 completed episodes per session and 40 per branch, from the chain a decision at minute m fills at m+1 and closes at m+91; the next decision is at m+92, fills at m+93 and closes at m+183. D7's log shows the first usable observation of a LEARNING session at market minute 20, so the chain is 20 -> 111, 112 -> 203, 204 -> 295, 296 -> 387, and a fifth entry would need a decision at minute 388 > 298. The observed counts above are inside that bound. Declared with it, before the run: addendum 5 states at most 3 episodes per session and at most 30 per branch. The arithmetic above gives 4 and 40. The corrected bound is recorded here, before the run, so it cannot be read as a result.

The three branches are **not** comparable as trading results and are not presented as any: they are three different weight states meeting the same ten sessions, and the money columns are reported because the amendment asks for them, not because a net figure here means anything about profitability.

## 4. Frozen comparison — hypothetical probe labels

Learning and forgetting off in both branches; the paired `comparison_v1` seeds do not depend on the weight digest, so a difference between the branches is a difference in weights and not in noise.

| branch | start digest | end digest | unchanged |
|---|---|---|---|
| frozen_trained | `f4ddbf0de147…` | `f4ddbf0de147…` | **True** |
| frozen_reference | `ba95b60503d6…` | `ba95b60503d6…` | **True** |

Grid 2790 eligible minutes, label available 2790, paired probes **2790**; coverage trained 1.0000, reference 1.0000, paired 1.0000. Unavailable labels {}.

| session | n | pos | neg | AUC trained | AUC reference | Δ | |
|---|---|---|---|---|---|---|---|
| 2026-07-20 | 279 | 119 | 160 | 0.4526 | 0.4976 | -0.0451 | qualifies |
| 2026-07-21 | 279 | 85 | 194 | 0.4321 | 0.5089 | -0.0769 | qualifies |
| 2026-07-22 | 279 | 7 | 272 | 0.3800 | 0.5987 | -0.2188 | 7 profitable and 272 nonprofitable labels, fewer than 10 in one class |
| 2026-07-23 | 279 | 156 | 123 | 0.5843 | 0.4568 | +0.1275 | qualifies |
| 2026-07-24 | 279 | 149 | 130 | 0.5115 | 0.4834 | +0.0281 | qualifies |
| 2026-07-27 | 279 | 54 | 225 | 0.6238 | 0.5209 | +0.1030 | qualifies |
| 2026-07-28 | 279 | 176 | 103 | 0.5381 | 0.4389 | +0.0992 | qualifies |
| 2026-07-29 | 279 | 175 | 104 | 0.3601 | 0.5303 | -0.1702 | qualifies |
| 2026-07-30 | 279 | 101 | 178 | 0.4956 | 0.4363 | +0.0592 | qualifies |
| 2026-07-31 | 279 | 213 | 66 | 0.4946 | 0.5671 | -0.0724 | qualifies |

**DELTA_AUC = 0.005819315575120566** over 9 qualifying sessions.
Paired session bootstrap, 2000 draws at the D7 seed 3219987367: mean +0.0064, sd 0.0319, 2.5 % -0.0584, 97.5 % +0.0664, fraction of draws above zero 0.587.

Classification by the committed rule: **C** — DELTA_AUC +0.0058 is positive but trained AUC 0.4992 is at or below chance-level ranking, which §9 says is insufficient on its own

The probes overlap by construction — one per eligible minute, holds of 90 minutes — so they are never independent trials and are never summed. The bootstrap resamples whole sessions, not experiments.

## 5. The INCONCLUSIVE rule, applied as pre-stated

| test | rule, as committed | observed | fires |
|---|---|---|---|
| learning | fewer than 10 completed LEARNING episodes -> INCONCLUSIVE for the learning side | 28 completed LEARNING episodes | **False** |
| evaluation | fewer than 5 qualifying FROZEN sessions under D7's rule (>= 10 of each label class, paired coverage >= 0.95) -> INCONCLUSIVE for the frozen comparison | 9 qualifying sessions | **False** |
| coverage | paired coverage ≥ 0.95 | 1.0000 | **False** |

Neither pre-stated INCONCLUSIVE condition fires: the experiment produced enough completed episodes and enough qualifying sessions to be read. The frozen comparison is therefore read under the committed conclusion rule.

### Verdict

The committed rule classifies this as **C**: DELTA_AUC +0.0058 is positive but trained AUC 0.4992 is at or below chance-level ranking, which §9 says is insufficient on its own.

In plain words: **no improvement detected under the fixed-hold policy on these periods.** DELTA_AUC is +0.0058 with a 2.5–97.5 % interval of [-0.0584, +0.0664] that contains zero, and the trained branch's own ranking sits at chance, so neither branch produced a ranking the other can be said to beat. Aligning the reinforced quantity with the evaluated one — which this wave did, exactly, to one part in 1e16 — did not by itself produce a detectable improvement here. That is a result about **this policy, this instrument, these twenty sessions and this metric**, and it is not evidence that the alignment was unnecessary, nor that a different horizon, instrument or training length would behave the same way.

A negative scientific result does not fail the engineering gate.

## 6. Integrity

| check | pass | detail |
|---|---|---|
| frozen_trained: frozen weights unchanged | True | `{"start_digest": "f4ddbf0de1473e9b5a6a67d0849525ec4f2260da05e9722f3bcbff8dbed5ffaf", "end_` |
| frozen_trained: start digest is the declared checkpoint | True | `{"expected": "f4ddbf0de1473e9b5a6a67d0849525ec4f2260da05e9722f3bcbff8dbed5ffaf"}` |
| frozen_trained: gross - fees - slippage = net | True | `{"residual": 7.105427357601002e-15, "tolerance": 1e-06}` |
| frozen_trained: credit assigner accepted nothing | True | `{"accepted": 0, "open": [], "settled": 13, "rejections": {"EPISODE_MISMATCH": 0, "ALREADY_` |
| frozen_reference: frozen weights unchanged | True | `{"start_digest": "ba95b60503d658e989b649ecd3994264791fbead92f0bdacfd555e5d86ab61f5", "end_` |
| frozen_reference: start digest is the declared checkpoint | True | `{"expected": "ba95b60503d658e989b649ecd3994264791fbead92f0bdacfd555e5d86ab61f5"}` |
| frozen_reference: gross - fees - slippage = net | True | `{"residual": 0.0, "tolerance": 1e-06}` |
| frozen_reference: credit assigner accepted nothing | True | `{"accepted": 0, "open": [], "settled": 32, "rejections": {"EPISODE_MISMATCH": 0, "ALREADY_` |
| the evaluator changed no event log | True | sha256 before == after, both branches |
| D7's evaluator and probes are byte-identical | True | `probe_grid, labels, frozen_decisions, integrity, sha256_file` imported, nothing modified |

Reused artifacts, hashed at run time against the plan: 10 files, each verified before the brain was built. `experiments/historical/run.py` is the one file the plan allows to move, because commit (2) of this wave amends it.

## 7. Wording, once more

This report never claims that the fly learned. A positive result would be evidence of context discrimination **in this experiment**, not general trading ability, not profitability and not skill. The 36.6 % positive base rate of the D7 LEARNING probe grid predicts nothing about the reward rate of this policy: selected entries and occupied inventory change which episodes actually occur. D7's conclusion B and D8's conclusions stand unrewritten.

_Assembled by `experiments/d9b/report.py` at 2026-09-12T02:40:42Z from `config.json`, `learning_summary.json`, `frozen_summary.json`, `alignment.json` and `context_summary.json`. No number in it is computed here._
