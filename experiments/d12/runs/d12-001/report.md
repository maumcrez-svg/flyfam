# d12-001 — school mode: relative cohort reinforcement

**One thing changed: the teacher.** The store, the cutoff `T`, the tick grid, the partitions, the clean reference, `pons_encoder_v2`, `admission_v2`, the k = 8 `comparison_v1` readout, the stored decoder, the 900-second horizon, the plasticity operator and its learning rate are the objects `d11-001` ran. What is new is `relative_cohort_v1` — a candidate is graded against the other candidates of its own tick — and school mode, in which **no position is ever opened** and every eligible candidate becomes a lesson.

Registered before any number existed: `experiments/d12/PLAN.md` and `experiments/d12/d12_001.json`, committed alone (step (ii)); then the lesson ceiling, the cohort-size distribution, the two grids' balances and the mirror diagnostic, numbers only and with no brain (step (iii)); then the run. **No RPC, no live hour, no signing, no funds, no real money.**

Profit is recorded and is **not** the criterion. Predictive learning is not declared from PnL, failure is not declared because the fly loses money, an interval that includes 0 is reported as *compatible with sampling variation*, and a lower BUY rate alone is not learning success.

## 1. The owner's cheap account first — is the trained brain the negative of the untrained one?

Computed in step (iii) from the two score files `d11-001` already wrote, over the **5,168** rows `VALID` under both brains. No brain ran and nothing was recomputed. Full table: `experiments/d12/mirror_diagnostic.md`.

| quantity | value |
|---|---|
| Pearson r (trained, reference) | 0.0046 |
| Spearman ρ | 0.0135 |
| Kendall τ | 0.0117 |
| OLS `trained = a + b · reference`: a | -3.4865 Hz |
| OLS b | **0.0045** |
| R² | 0.0000 |
| row pairs reversed | 49.21 % of 13,351,528 |
| mean within-tick Kendall τ | **0.0030** over 402 ticks |
| ticks with τ exactly −1 | 0 |
| AUC(trained) | 0.4116 |
| AUC(reference) | 0.5885 |
| AUC(−reference) | 0.4115 |
| AUC(trained) − (1 − AUC(reference)) | **0.0000** |

The mechanistic reading — that fifteen punishments depressed the approach pathway in proportion to the prior valence, so the trained valence is a decreasing affine function of the untrained one — is a **hypothesis** that `b` and `τ` test. It is **not a finding** until the owner states it as one.

## 2. The teacher — `relative_cohort_v1`

The cohort is the `admission_v2`-eligible candidates of **one tick** that have a settled evaluator label. With `n` the cohort size after the `UNRESOLVED` drop and ranks ascending by the label's integer net in wei, average ranks for ties:

```
s_i = 2 · (rank_i − 1) / (n − 1) − 1        in [−1, +1]
```

`s > 0` is a reward and `s < 0` a punishment of amount `|s|`; `s = 0` is neutral and delivers nothing. **`n_min = 3`**: a smaller cohort teaches nothing and is counted. **No clipping can occur** — `|s| ≤ 1` by construction — and neither `REINFORCE_CAP` nor `reinforce_full_scale` is consulted. Both of the owner's examples, `+14/+3/−2/−7/−18/−61 %` and `−3/−8/−15/−28/−50/−82 %`, give `s = +1, +0.6, +0.2, −0.2, −0.6, −1`; a known-answer test asserts it.

**The financial net and the pedagogical signal are two columns on every `LESSON` record and are never merged.** A cohort in which every member lost money still teaches which member lost least. No profit is falsified: the net is reported as it is. This is relative cohort reinforcement and is never called a profit reward.

Against D11's absolute rule, which met this window with 15 punishments, 0 rewards and 11 of 15 updates clipped at the 0.131 scale: this wave applied **19,665 lessons** — **9,629 reward**, **9,551 punishment**, 485 neutral — and **0 clipped**, because clipping is impossible under this rule.

## 3. The school — every eligible candidate is a lesson

`SCHOOL`, `LEARN`, over the **1,009** LEARNING ticks from the clean reference `ba95b60503d6…` under `from_clean_reference`. **No paper position was opened or held**, no cap of six, no rotation, no hold mode. Final digest **`29d22e83b900…`** (SCHOOL).

| | value |
|---|---|
| candidate evaluations (presentations of a candidate) | 20,488 |
| readout presentations (k = 8 replicates each) | 163,904 |
| **lesson ceiling**, registered in step (iii) before the brain ran | **20,152** (after the `UNRESOLVED` drop 19,665) |
| cohorts formed | 975 |
| **lessons applied** | **19,665** (19,180 accepted by the credit assigner, 485 neutral, 0 refused) |
| lessons discarded | 823 `{'UNRESOLVED': 487, 'BOUNDARY': 336}` |
| cohort size applied | min 3, median 22.0, max 44 |
| amount `\|s\|` | min 0.0000, median 0.5263, max 1.0000 |
| clipped at a cap | **0** (impossible under this rule) |
| cohort-size distribution in LEARNING (market only, step (iii)) | median 21.0, max 44, 3 ticks below n_min |

**Maturity and no lookahead.** A lesson matures at the first tick whose `cutoff ≥ lesson cutoff + 902 s`; 902 is not a multiple of the 30-second cadence, so that tick is always `cutoff + 930` — 28 seconds after the outcome it is graded on. Matured lessons of one cohort are applied together, in `stable_id` order, **before** that tick's presentations. A lesson whose `cutoff + 902 > T` is discarded, counted and never applied, and no lesson is ever applied at a FROZEN tick.

**Determinism.** The first 100 LEARNING ticks, run twice from the clean reference: `runs/d12-001/determinism.json`, and a test asserts the checkpoint digest and the `LESSON`-log sha256 are identical.

## 4. The learning curve, and the weights

For every lesson, the valence the readout produced **at presentation** and the `s` that arrived 902 seconds later. It is prospective by construction: the brain had not been taught these lessons when it scored them. The window is the last 500 applied lessons.

| lessons | window n | Spearman(valence, s) | mean within-cohort τ | cumulative Spearman | weights: mean | at floor | at ceiling |
|---|---|---|---|---|---|---|---|
| 500 | 500 | -0.0208 | -0.0444 | -0.0208 | 0.919303 | 5.44 % | 76.69 % |
| 1,000 | 500 | 0.0300 | 0.0087 | 0.0029 | 0.899692 | 8.37 % | 73.85 % |
| 1,500 | 500 | 0.0253 | 0.0420 | 0.0092 | 0.888832 | 9.53 % | 73.29 % |
| 2,000 | 500 | -0.0070 | -0.0101 | 0.0051 | 0.883052 | 10.00 % | 72.84 % |
| 2,500 | 500 | 0.1182 | 0.0984 | 0.0259 | 0.878327 | 10.55 % | 72.48 % |
| 3,000 | 500 | -0.0354 | 0.0085 | 0.0166 | 0.874022 | 11.15 % | 71.78 % |
| 3,500 | 500 | 0.0192 | -0.0202 | 0.0166 | 0.871162 | 11.37 % | 71.51 % |
| 4,000 | 500 | -0.0608 | -0.0348 | 0.0076 | 0.868101 | 12.12 % | 71.36 % |
| 4,500 | 500 | -0.0346 | -0.0174 | 0.0033 | 0.865626 | 12.39 % | 71.33 % |
| 5,000 | 500 | -0.1196 | -0.0732 | -0.0089 | 0.863517 | 12.55 % | 71.27 % |
| 5,500 | 500 | -0.0523 | -0.0492 | -0.0125 | 0.861588 | 12.72 % | 71.24 % |
| 6,000 | 500 | 0.1121 | 0.0718 | -0.0024 | 0.860121 | 12.73 % | 71.18 % |
| 6,500 | 500 | -0.0162 | 0.0103 | -0.0031 | 0.858426 | 12.77 % | 71.10 % |
| 7,000 | 500 | -0.0866 | -0.0864 | -0.0090 | 0.856621 | 12.83 % | 70.85 % |
| 7,500 | 500 | -0.0563 | -0.0241 | -0.0120 | 0.855450 | 12.91 % | 70.74 % |
| 8,000 | 500 | 0.0410 | 0.0541 | -0.0089 | 0.854611 | 12.91 % | 70.67 % |
| 8,500 | 500 | -0.1758 | -0.1272 | -0.0189 | 0.853210 | 13.06 % | 70.39 % |
| 9,000 | 500 | 0.0109 | 0.0178 | -0.0170 | 0.851861 | 13.37 % | 70.36 % |
| 9,500 | 500 | -0.0675 | -0.0446 | -0.0198 | 0.851018 | 13.40 % | 70.34 % |
| 10,000 | 500 | 0.0170 | 0.0144 | -0.0180 | 0.849998 | 13.48 % | 70.29 % |
| 10,500 | 500 | 0.0179 | -0.0006 | -0.0165 | 0.848865 | 13.51 % | 70.20 % |
| 11,000 | 500 | -0.0708 | 0.0162 | -0.0192 | 0.847810 | 13.64 % | 70.07 % |
| 11,500 | 500 | -0.0346 | -0.0135 | -0.0200 | 0.847236 | 13.67 % | 70.07 % |
| 12,000 | 500 | 0.0266 | 0.0080 | -0.0181 | 0.846571 | 13.97 % | 70.07 % |
| 12,500 | 500 | -0.0895 | -0.0831 | -0.0209 | 0.845733 | 14.03 % | 70.05 % |
| 13,000 | 500 | 0.0567 | 0.0455 | -0.0179 | 0.845100 | 14.36 % | 69.97 % |
| 13,500 | 500 | 0.0163 | 0.0236 | -0.0167 | 0.844299 | 14.44 % | 69.94 % |
| 14,000 | 500 | 0.0255 | 0.0148 | -0.0151 | 0.843765 | 14.44 % | 69.94 % |
| 14,500 | 500 | -0.0966 | -0.0567 | -0.0178 | 0.843343 | 14.46 % | 69.91 % |
| 15,000 | 500 | -0.0287 | -0.0316 | -0.0181 | 0.842541 | 14.72 % | 69.80 % |
| 15,500 | 500 | -0.0002 | 0.0148 | -0.0174 | 0.841908 | 14.77 % | 69.61 % |
| 16,000 | 500 | -0.0147 | 0.0061 | -0.0172 | 0.841398 | 14.79 % | 69.58 % |
| 16,500 | 500 | 0.1754 | 0.0872 | -0.0114 | 0.840740 | 14.91 % | 69.45 % |
| 17,000 | 500 | 0.0044 | -0.0077 | -0.0111 | 0.840131 | 14.96 % | 69.42 % |
| 17,500 | 500 | -0.1022 | -0.0816 | -0.0135 | 0.839691 | 14.98 % | 69.40 % |
| 18,000 | 500 | -0.0353 | -0.0177 | -0.0142 | 0.839374 | 15.00 % | 69.37 % |
| 18,500 | 500 | 0.0843 | 0.0551 | -0.0114 | 0.839001 | 15.04 % | 69.35 % |
| 19,000 | 500 | -0.0502 | -0.0673 | -0.0124 | 0.838587 | 15.04 % | 69.25 % |
| 19,500 | 500 | -0.0252 | -0.0365 | -0.0126 | 0.838273 | 15.04 % | 69.20 % |
| 19,665 | 500 | -0.0609 | -0.0738 | -0.0142 | 0.838224 | 15.04 % | 69.20 % |

At the end of LEARNING: mean gain **0.838224**, L2 norm 186.542, min 0.250000, **15.04 %** of 44,042 plastic KC→MBON synapses at the floor (0.25) and **69.20 %** at the ceiling (1.0).

**A property of the operator, registered before the run so it cannot be mistaken for a result:** the plasticity rule only depresses and the clean reference starts with every gain exactly at 1.0, so a synapse *at the ceiling* is a synapse **no lesson has ever depressed**. The two fractions are reported separately as well as summed; the pre-registered condition reads the sum, as addendum 9 words it.

## 5. The frozen proof — later tokens she never received as lessons

The FROZEN grid is `d11-001`'s, **reused**: the same rows, the same evaluator labels and the same REFERENCE scores, verified rather than assumed. 200 rows were re-scored under the clean reference and compared with the reused valences: **200 compared, 0 mismatched**, worst |difference| 0.000e+00 Hz against a 1e-9 Hz tolerance → **REUSE_VERIFIED**.

* **primary** — FROZEN rows on tokens that were **never a lesson**: 5,044 rows over 1,045 tokens, 3,788 with a settled label (416 positive / 3,372 negative).
* **secondary** — all FROZEN rows: 5,177 rows, 3,890 labelled (432 positive / 3,458 negative), reported regardless of the verdict.

Both brains read-only, digests verified before and after: SCHOOL `29d22e83b900…`, REFERENCE `ba95b60503d6…`. Paired neural coverage **77.57 %** of 5,177 rows.

**Where the coverage went, as counts.** The readout status of every grid row under each brain:

| branch | NO_RESPONSE | VALID |
|---|---|---|
| school | 1,161 | 4,016 |
| reference | 9 | 5,168 |

`NO_RESPONSE` is the decoder's name for a presentation whose k = 8 replicates produced no usable readout. It is 0.17 % of the rows under REFERENCE and **22.43 %** under SCHOOL — the whole of the coverage shortfall, and the reason condition 4 fails below. It is a number, not a reading.

### Primary grid

| | n | positive | AUC SCHOOL | AUC REFERENCE | ΔAUC | 95 % interval |
|---|---|---|---|---|---|---|
| **overall** | 3,788 | 416 | 0.4337 | 0.5666 | **-0.1329** | [-0.1941, -0.0655] |
| block 1 | 1,271 | 174 | 0.4414 | 0.5496 | -0.1082 | [-0.2264, -0.0103] |
| block 2 | 1,409 | 144 | 0.4159 | 0.5588 | -0.1429 | [-0.2242, +0.0456] |
| block 3 | 1,108 | 98 | 0.4434 | 0.6077 | -0.1643 | [-0.2808, -0.0034] |

**delta AUC (SCHOOL - REFERENCE) is -0.1329, 95 % interval [-0.1941, -0.0655] — an interval that excludes 0.**

The pre-registered reading of addendum 7, applied to that interval: **the inversion persists**.

* block 1 delta AUC is -0.1082, 95 % interval [-0.2264, -0.0103] — an interval that excludes 0 — the inversion persists.
* block 2 delta AUC is -0.1429, 95 % interval [-0.2242, +0.0456] — an interval that includes 0, compatible with sampling variation — compatible with sampling variation.
* block 3 delta AUC is -0.1643, 95 % interval [-0.2808, -0.0034] — an interval that excludes 0 — the inversion persists.

Descriptive: Spearman(score, net) is 0.0010 for SCHOOL and -0.0324 for REFERENCE. The per-row score difference SCHOOL − REFERENCE has mean -1.1532 Hz, SD 2.1632, range [-11.0722, 3.8524].

### Secondary grid

| | n | positive | AUC SCHOOL | AUC REFERENCE | ΔAUC | 95 % interval |
|---|---|---|---|---|---|---|
| **overall** | 3,890 | 432 | 0.4326 | 0.5645 | **-0.1319** | [-0.1905, -0.0683] |
| block 1 | 1,373 | 190 | 0.4394 | 0.5453 | -0.1058 | [-0.2147, -0.0197] |
| block 2 | 1,409 | 144 | 0.4159 | 0.5588 | -0.1429 | [-0.2242, +0.0456] |
| block 3 | 1,108 | 98 | 0.4434 | 0.6077 | -0.1643 | [-0.2808, -0.0034] |

**delta AUC (SCHOOL - REFERENCE) is -0.1319, 95 % interval [-0.1905, -0.0683] — an interval that excludes 0.**

The pre-registered reading of addendum 7, applied to that interval: **the inversion persists**.

* block 1 delta AUC is -0.1058, 95 % interval [-0.2147, -0.0197] — an interval that excludes 0 — the inversion persists.
* block 2 delta AUC is -0.1429, 95 % interval [-0.2242, +0.0456] — an interval that includes 0, compatible with sampling variation — compatible with sampling variation.
* block 3 delta AUC is -0.1643, 95 % interval [-0.2808, -0.0034] — an interval that excludes 0 — the inversion persists.

Descriptive: Spearman(score, net) is 0.0045 for SCHOOL and -0.0349 for REFERENCE. The per-row score difference SCHOOL − REFERENCE has mean -1.1695 Hz, SD 2.1764, range [-12.5943, 3.8524].

**An AUC near 0.5 is not evidence that no signal exists**, and nothing above is a claim about a rate in the market.

## 6. Suppression

θ = 0.911719 Hz, the stored k = 8 margin.

| grid | rows | BUY rate SCHOOL | BUY rate REFERENCE | change |
|---|---|---|---|---|
| primary | 3,896 | 0.05 % | 43.58 % | -43.53 pp |
| secondary | 4,016 | 0.05 % | 43.85 % | -43.80 pp |
| secondary, later outcome positive | 432 | 0.00 % | 53.24 % | -53.24 pp |
| secondary, later outcome negative | 3,458 | 0.06 % | 42.48 % | -42.42 pp |
| secondary, block 1 | 1,436 | 0.00 % | 44.85 % | -44.85 pp |
| secondary, block 2 | 1,444 | 0.00 % | 42.45 % | -42.45 pp |
| secondary, block 3 | 1,136 | 0.18 % | 44.37 % | -44.19 pp |

* **primary** — the between-class difference of the school-minus-reference change in the BUY-crossing rate is +0.1095, 95 % interval [+0.0437, +0.1707] — an interval that excludes 0; under the registered rule that is **contextual**.
* **secondary** — the between-class difference of the school-minus-reference change in the BUY-crossing rate is +0.1082, 95 % interval [+0.0470, +0.1681] — an interval that excludes 0; under the registered rule that is **contextual**.

**A lower BUY rate alone is not learning success**, and nothing else is said in words.

Continuous scores over the rows valid in both branches:

| grid | branch | mean | SD | min | median | max |
|---|---|---|---|---|---|---|
| primary | school | -0.278 | 0.778 | -4.113 | -0.018 | 1.639 |
| primary | reference | 0.875 | 1.567 | -3.223 | 0.683 | 8.361 |
| secondary | school | -0.286 | 0.785 | -4.113 | -0.058 | 1.639 |
| secondary | reference | 0.884 | 1.575 | -3.223 | 0.696 | 8.872 |

## 7. `d11-001` beside `d12-001`, on the same secondary grid

The same rows, the same labels and the same REFERENCE scores. The only difference between the two lines is the brain in the left-hand column and the teacher that made it. This is **descriptive**: two runs, one window, and no interval was pre-registered for the difference between them.

| wave | teacher | lessons or episodes | AUC (trained/school) | AUC REFERENCE | ΔAUC | 95 % interval | BUY rate |
|---|---|---|---|---|---|---|---|
| `d11-001` | absolute profit | 15 episodes, 0 reward / 15 punishment, 11 clipped | 0.4116 | 0.5885 | -0.1769 | [-0.2180, -0.1246] | 0.00 % |
| `d12-001` | relative cohort | 19,665 lessons, 9,629 reward / 9,551 punishment, 0 clipped | 0.4326 | 0.5645 | -0.1319 | [-0.1905, -0.0683] | 0.05 % |

Per block, ΔAUC with its interval:

| block | `d11-001` | `d12-001` |
|---|---|---|
| 1 | -0.2081 [-0.2696, -0.1139] | -0.1058 [-0.2147, -0.0197] |
| 2 | -0.1404 [-0.1960, -0.0247] | -0.1429 [-0.2242, +0.0456] |
| 3 | -0.1753 [-0.2994, -0.0421] | -0.1643 [-0.2808, -0.0034] |

`d11-001`'s labelled denominator was 5,013 rows (488 positive / 4,525 negative) against 3,890 here (432 / 3,458); the small difference is the rows one branch or the other did not score `VALID`.

## 8. The two FROZEN loop branches (paper results, descriptive)

The loop over the FROZEN partition with learning off, one position at a time, the market rebuilt from `t0` without the brain. They are **not** the primary comparison — two loop branches cannot share rows, which is why the grid exists — and their PnL is descriptive. **The school branch has no paper results by design: it never opened a position.**

| branch | episodes | settled frozen | net (ETH) | fees | wins | holds (s) | unresolved | digest unchanged |
|---|---|---|---|---|---|---|---|---|
| frozen_school | 0 | 0 | 0 | 0 | 0 | —–— | 0 | yes |
| frozen_reference | 6 | 6 | 0.00511362 | 0.00268236 | 3 | 900–900 | 2 | yes |

* **frozen_school** — per-round actions `{'WAIT': 401, 'SELL': 1}`, after execution `{'NO_ORDER:WAIT': 401, 'NO_ORDER:SELL': 1}`
* **frozen_reference** — per-round actions `{'BUY': 144, 'SELL': 8, 'WAIT': 41}`, after execution `{'BUY': 7, 'blocked_by_fixed_hold': 8, 'HOLD:WAIT': 40, 'HOLD:BUY': 137, 'POLICY_CLOSE_FIXED_HOLD': 6, 'SETTLED_FROZEN': 6, 'NO_ORDER:WAIT': 1, 'UNRESOLVED:ROUTE_TRANSITION': 1, 'UNRESOLVED:END_OF_DATA': 1}`

## 9. The six inconclusive conditions, one by one

| condition (verbatim, addendum 9) | measured | threshold | verdict |
|---|---|---|---|
| fewer than 2,000 lessons applied | 19,665 lessons applied (19,180 accepted, 485 neutral) | 2000 | PASS |
| fewer than 100 paired labels on the primary grid | 3,788 primary rows valid in both branches with a settled label | 100 | PASS |
| either outcome class under 20 on the primary grid | 416 positive / 3,372 negative | 20 | PASS |
| paired coverage under 95 % | 77.57 % of 5,177 rows valid in both branches | 0.95 | **FAIL** |
| encoder saturation over 5 % of (row, channel) pairs or INVALID_STATE over 5 % | saturation 2.820 % of (row, channel) pairs; INVALID_STATE school 0.000 %, reference 0.000 % | 0.05 | PASS |
| more than 25 % of plastic synapses at floor or ceiling at the end of LEARNING | 84.24 % of 44,042 plastic synapses (15.04 % at the floor, 69.20 % at the ceiling, which is where the clean reference starts) | 0.25 | **FAIL** |

**2 condition(s) failed, so the learning evaluation is declared INCONCLUSIVE** rather than stretching the interpretation. The thresholds were registered before the run and are not loosened after it. The ΔAUC above is reported with its interval and is **not** interpreted as a finding about learning.

The secondary grid is reported regardless of the verdict, as registered.

## 10. What this cannot say

It cannot say the fly is profitable, and it was not asked to. Within this window the only thing that changed between SCHOOL and REFERENCE is 8.4 hours of school, so a difference is a difference between one brain that was taught and one that was not — but it is one window, one store and one seed schedule. It is **not** comparable with `d10-001`. It is compared with `d11-001` only on the secondary grid, and that comparison is descriptive.

PONS — the wallet/sniper track in `~/Documentos/PONS` — was **not** touched, and no wallet feature entered the brain: adding it here would have changed what the fly sees at the same time as the teacher, and nothing could then have been attributed to either.

No real money, no signing, no funds, no network connection of any kind. **This wave made zero RPC calls.**
