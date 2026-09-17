# D7 — results

Run `d7-001`, IBM only, window 2026-06-15 … 07-31, **H\* = 90 market minutes**. Pre-registered in `PROTOCOL.md` and `config.json` (committed alone), calibrated in `registered-horizon-artifact` (committed alone). Python 3.13.9, NumPy 2.4.2, x86_64, one process, no parallelism.

Nothing here is a claim of skill, alpha or profitability, and net PnL is not a gate metric in either direction.

## 1. The horizon, selected on WARMUP alone

`C` measured by one flat-price round trip through the real `HistoricalExecution` at notional 1000: **19.990005 bps**, 10.0 bps per leg, gross at reference prices 0.0e+00. Threshold `2C` = **39.980010 bps**.

| H, market minutes | 8 | 15 | 30 | 60 | 90 | 120 |
|---|---|---|---|---|---|---|
| A(H), bps | 18.2734 | 24.3428 | 31.4495 | 38.5066 | 57.8625 | 65.6072 |
| ≥ 2C | no | no | no | no | **yes** | **yes** |

`A(H) = median across the 13 qualifying WARMUP sessions of [median across that session's common origins of |g(t,H)|]`. **H\* = 90**, the smallest candidate clearing the bar. Per session:

| session | common origins | H=8 | H=15 | H=30 | H=60 | H=90 | H=120 |
|---|---|---|---|---|---|---|---|
| 2026-06-15 | 190 | 11.60 | 18.83 | 18.22 | 25.28 | 32.77 | 43.88 |
| 2026-06-16 | 249 | 9.25 | 10.88 | 11.46 | 18.67 | 22.21 | 20.91 |
| 2026-06-17 | 249 | 12.33 | 22.16 | 40.03 | 58.08 | 76.19 | 85.05 |
| 2026-06-18 | 249 | 18.78 | 25.69 | 36.12 | 65.28 | 74.55 | 83.06 |
| 2026-06-22 | 249 | 18.27 | 26.08 | 41.03 | 52.71 | 63.55 | 76.00 |
| 2026-06-23 | 249 | 18.54 | 24.37 | 27.27 | 44.51 | 57.86 | 65.61 |
| 2026-06-24 | 249 | 21.62 | 24.46 | 31.45 | 31.86 | 24.47 | 40.19 |
| 2026-06-25 | 249 | 22.26 | 29.88 | 50.76 | 68.46 | 65.35 | 66.33 |
| 2026-06-26 | 249 | 14.60 | 18.96 | 25.84 | 36.18 | 42.84 | 48.53 |
| 2026-06-29 | 249 | 17.64 | 20.59 | 27.64 | 38.51 | 46.77 | 53.38 |
| 2026-06-30 | 249 | 11.81 | 20.28 | 29.00 | 30.42 | 59.00 | 76.65 |
| 2026-07-01 | 249 | 21.25 | 31.52 | 44.78 | 70.41 | 105.40 | 119.98 |
| 2026-07-02 | 249 | 20.60 | 24.34 | 35.61 | 26.64 | 44.21 | 34.92 |

All 13 WARMUP sessions qualified (10 required). The `WarmupOnly` view recorded exactly `2026-06-15, 2026-06-16 … 2026-07-02` as touched and would have raised on any other session.

## 2. LEARNING — what actually happened

`WARMUP` ran features only: 5,070 rounds, no brain, no `DECISION` event, 0.06 s. `LEARNING` ran 3,899 rounds in 15.0 min; digest `ba95b60503d6` → `8470c55b7f86`, moved: True.

**Three denominators, never pooled.**

| denominator | n | status | action |
|---|---|---|---|
| per candidate evaluation (one batch of k = 8) | 3699 | {"VALID": 3645, "NO_RESPONSE": 54} | {"WAIT": 756, "SELL": 2806, "BUY": 83, "NO_RESPONSE": 54} |
| per decision round (after selection) | 3899 | {"NO_USABLE_CANDIDATE": 251, "VALID": 3645, "NO_RESPONSE": 3} | {"WAIT": 756, "SELL": 2806, "BUY": 83, "NO_RESPONSE": 3} |
| after inventory and execution | — | {"NO_ORDER:WAIT": 699, "NO_ORDER:SELL": 2764, "BUY": 42, "HOLD:WAIT": 57, "HOLD:BUY": 29, "HOLD:NO_RESPONSE": 3, "NEURAL_SELL": 42, "POLICY_REJECT:SESSION_HORIZON": 12} | — |

Silent **presentations** 7,323 of 29,592 (24.7 %), counted apart from `NO_RESPONSE` batches. Invalid replicates 0. Rounds aborted 0.

Market status per round-minute: {"IBM": {"WARMUP": 200, "OK": 3699}}

Completed episodes **42** — 5 with net > 0, 37 with net < 0, 0 exactly flat. Exposure 131 market minutes of 3,899 round-minutes. Credit: {"accepted": 42, "open": [], "settled": 42, "rejections": {"EPISODE_MISMATCH": 0, "ALREADY_SETTLED": 0, "UNKNOWN_EPISODE": 0, "TRACE_EXPIRED": 0, "SHAPE_MISMATCH": 0}, "rejections_total": 0}.

**Accounting.** gross at reference prices +9.5396 − slippage 41.9838 − fees 41.9838 = net -74.4280, residual 0.0e+00. Not a gate metric.

**Exit reason × reward sign × holding minutes** (Fable addendum 7, written before the run):

| exit reason | reward sign | episodes | holding, market minutes |
|---|---|---|---|
| NEURAL_SELL | punishment (−) | 37 | 1′×20, 2′×8, 3′×4, 6′×2, 8′×1, 10′×1, 15′×1 |
| NEURAL_SELL | reward (+) | 5 | 2′×1, 3′×1, 5′×1, 9′×1, 19′×1 |

Holding-duration distribution over all 42 episodes: 1 min × 20, 2 min × 9, 3 min × 5, 5 min × 1, 6 min × 2, 8 min × 1, 9 min × 1, 10 min × 1, 15 min × 1, 19 min × 1.

**Observation-availability → fill delay** (amendment §5: printed so an off-by-one cannot stay hidden). The policy asks for the bar at `decision minute + 1`; the delay is how many market minutes later the fill actually landed: +1 min × 42. `DELAYED_FILL` flags 0.

**Mid-run restart** (declared, after 3 settled episodes): 2026-07-06 minute 56, `nothing to do`, gains restored exactly: True.

## 3. FROZEN — two branches, identical observations and seeds

TRAINED started from the LEARNING checkpoint (`8470c55b7f86`, verified equal to the LEARNING end digest before the branch ran); REFERENCE from the clean reference `ba95b60503d6`. Learning and forgetting off in both.

| branch | digest | unchanged | trades | exposure (min) | net | action per round | wall |
|---|---|---|---|---|---|---|---|
| frozen_trained | 8470c55b7f86 → 8470c55b7f86 | True | 2 | 3 | -2.4342 | {"WAIT": 536, "SELL": 3094, "BUY": 4} | 15.6 min |
| frozen_reference | ba95b60503d6 → ba95b60503d6 | True | 260 | 2213 | -466.9562 | {"WAIT": 1723, "BUY": 1488, "NO_RESPONSE": 42, "SELL": 425} | 15.7 min |

`frozen_trained` accounting: +1.5654 − 1.9998 − 1.9998 = -2.4342, residual 0.0e+00; `SETTLED_FROZEN` 2; LEARNING events accepted 0.

`frozen_reference` accounting: +52.8367 − 259.8965 − 259.8965 = -466.9562, residual -4.0e-13; `SETTLED_FROZEN` 260; LEARNING events accepted 0.

## 4. The paired frozen probe dataset

The grid is every FROZEN minute whose observation status is `OK` and which satisfies `(m+1)+1+90 ≤ 390`, computed from the calendar and the price file **before either log was opened**: **2,790 points** over 10 sessions.

| quantity | value |
|---|---|
| grid points | 2790 |
| label available | 2790 |
| UNAVAILABLE_LABEL | 0 {} |
| scored, TRAINED | 2790 |
| scored, REFERENCE | 2790 |
| paired probes | 2790 |
| coverage TRAINED / REFERENCE / paired | 100.00 % / 100.00 % / 100.00 % |

`frozen_trained` readout statuses over label-available grid points: {"VALID": 2737, "NO_RESPONSE": 53}

`frozen_reference` readout statuses over label-available grid points: {"VALID": 2739, "NO_RESPONSE": 51}

## 5. Context discrimination

| session | probes | Y=1 | Y=0 | AUC TRAINED | AUC REFERENCE | delta | note |
|---|---|---|---|---|---|---|---|
| 2026-07-20 | 279 | 119 | 160 | 0.4768 | 0.4976 | -0.0208 | qualifies |
| 2026-07-21 | 279 | 85 | 194 | 0.4138 | 0.5089 | -0.0951 | qualifies |
| 2026-07-22 | 279 | 7 | 272 | 0.2831 | 0.5987 | -0.3157 | 7 profitable and 272 nonprofitable labels, fewer than 10 in one class |
| 2026-07-23 | 279 | 156 | 123 | 0.5601 | 0.4568 | +0.1032 | qualifies |
| 2026-07-24 | 279 | 149 | 130 | 0.4727 | 0.4834 | -0.0108 | qualifies |
| 2026-07-27 | 279 | 54 | 225 | 0.6179 | 0.5209 | +0.0971 | qualifies |
| 2026-07-28 | 279 | 176 | 103 | 0.5392 | 0.4389 | +0.1003 | qualifies |
| 2026-07-29 | 279 | 175 | 104 | 0.3759 | 0.5303 | -0.1544 | qualifies |
| 2026-07-30 | 279 | 101 | 178 | 0.4789 | 0.4363 | +0.0426 | qualifies |
| 2026-07-31 | 279 | 213 | 66 | 0.4784 | 0.5671 | -0.0887 | qualifies |

**DELTA_AUC = -0.0030** over 9 qualifying sessions, each weighted equally. Mean AUC level: TRAINED 0.4904, REFERENCE 0.4934.

Paired session bootstrap, 2,000 draws of whole qualifying sessions with the seed declared in `config.json` (3219987367): mean -0.0022, sd 0.0301, 2.5–97.5 % -0.0621 … +0.0544, 47.6 % of draws above zero. Limited, day-resampled uncertainty conditional on this one training run; not a significance test. Overlapping 90-minute outcomes are not independent trials and individual minutes were never resampled.

**Matched participation**, top 20 % of probes in each branch independently, fractional tie weighting, pooled over the qualifying sessions (n = 2,511; both branches select 502.2 units of weight):

| slice | mean G(t) | profitable rate |
|---|---|---|
| TRAINED | +11.236 bps | 47.08 % |
| REFERENCE | +9.694 bps | 48.60 % |
| all probes | +12.609 bps | 48.90 % |

A ranking diagnostic, not a trading policy and not a backtested portfolio: the probes overlap by construction and are never summed into an executable PnL.

**Conclusion B** — DELTA_AUC -0.0030 over 9 qualifying sessions, 47.6% of paired draws above zero: no supported improvement in context ranking.

## 6. Guards

* PASS — frozen_trained: frozen weights unchanged: {"start_digest": "8470c55b7f86fc6f981a55726ff0e291ddb45706f7f45720a5697ccea0ac9127", "end_digest": "8470c55b7f86fc6f981a55726ff0e291ddb45706f7f45720a5697ccea0ac
* PASS — frozen_trained: start digest is the declared checkpoint: {"expected": "8470c55b7f86fc6f981a55726ff0e291ddb45706f7f45720a5697ccea0ac9127"}
* PASS — frozen_trained: gross - fees - slippage = net: {"residual": 0.0, "tolerance": 1e-06}
* PASS — frozen_trained: credit assigner accepted nothing: {"accepted": 0, "open": [], "settled": 2, "rejections": {"EPISODE_MISMATCH": 0, "ALREADY_SETTLED": 0, "UNKNOWN_EPISODE": 0, "TRACE_EXPIRED": 0, "SHAPE_MISMATCH"
* PASS — frozen_reference: frozen weights unchanged: {"start_digest": "ba95b60503d658e989b649ecd3994264791fbead92f0bdacfd555e5d86ab61f5", "end_digest": "ba95b60503d658e989b649ecd3994264791fbead92f0bdacfd555e5d86ab
* PASS — frozen_reference: start digest is the declared checkpoint: {"expected": "ba95b60503d658e989b649ecd3994264791fbead92f0bdacfd555e5d86ab61f5"}
* PASS — frozen_reference: gross - fees - slippage = net: {"residual": -3.979039320256561e-13, "tolerance": 1e-06}
* PASS — frozen_reference: credit assigner accepted nothing: {"accepted": 0, "open": [], "settled": 260, "rejections": {"EPISODE_MISMATCH": 0, "ALREADY_SETTLED": 0, "UNKNOWN_EPISODE": 0, "TRACE_EXPIRED": 0, "SHAPE_MISMATC

The evaluator hashed both event logs before and after itself: unchanged = **True**.

## 7. Reading

**The horizon rule worked and did not bind.** H\* = 90 was selected on WARMUP alone and frozen before any LEARNING price was read. It changed two things in the run: the label every probe carries, and the entry-eligibility window, which now closes at 14:28 ET rather than 15:50. It did **not** change how long a position was actually held: all 42 LEARNING episodes ended in a neural `SELL` after 1–19 market minutes, total exposure 131 minutes. Fable addendum 7 predicted exactly this before the run and asked for the cross-tabulation rather than a change, and nothing was changed to make H\* bind.

**The reward sign still barely varied with the decision.** 37 of 42 settled episodes were punishments. Over an actual hold of one to three minutes the round trip still costs 20.0 bps, which is the whole of the result; the longer horizon the rule selected never applied to a real trade because the decoder exited first.

**Neither brain ranks contexts.** Mean AUC 0.4904 (TRAINED) and 0.4934 (REFERENCE) are both at chance, and the per-session deltas change sign four times. DELTA_AUC -0.0030 with a 2.5–97.5 % day-resampled interval of -0.0621 … +0.0544 does not separate the two. §9 says a positive DELTA_AUC would have been insufficient anyway while TRAINED sits at or below chance; it is not positive.

**The one excluded session is excluded by a rule fixed before the data, and the exclusion is not flattering.** 2026-07-22 carried 7 profitable labels against 272 and fails the ≥ 10-per-class rule. Its delta was -0.3157, the largest negative in the set: including it would give -0.0342 rather than -0.0030. The conclusion is B either way.

**Matched participation says the same thing.** The mean `G(t)` over **all** 2,511 probes of the qualifying sessions is +12.61 bps with 48.9 % profitable — the FROZEN window drifted upward, which ROC-AUC is by construction blind to. Neither branch's own top-20 % slice beats that full-sample mean (+11.24 bps trained, +9.69 bps reference), so neither ranking is informative about which minute to enter.

**What did change is participation.** TRAINED decoded BUY in 4 of its valid rounds and traded 2 times; REFERENCE decoded BUY in 1488 and traded 260 times. That is the D5/D6 finding again — experience modified the decisions — measured this time against a metric that cannot reward it. The owner's wording holds: the comparison shows that experience modified the decisions; it does not show that the fly learned to recognise good and bad market contexts, and this wave now says so with a pre-registered measurement rather than by inference from an action mix.

Failure to demonstrate discrimination is not proof that this system can never learn any market structure, and a positive scientific outcome was never required for engineering completion.

