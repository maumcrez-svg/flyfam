# D8 — results

**RETROSPECTIVE DIAGNOSTIC — D7 RESULTS PREVIOUSLY OBSERVED**

Evaluator-only. **No neural run, no download, no change under `flytrade/`, `upstream/`, `tests/upstream_audit/`, `observer/` or `experiments/d7/`.** Pre-registered in `PLAN.md` and `config.json`, committed alone before any D8 number existed. Python 3.13.9, NumPy 2.4.2, SciPy 1.17.1, **scikit-learn 1.9.1** as the new optional extra `diagnostics`, one process, `OMP_NUM_THREADS=1`.

**The D7 results on these dates were already observed.** This is an additional retrospective analysis, not an independent confirmation on untouched data. **The evaluation dates are not a pristine holdout.** Fixing the plan before the new computations limits opportunistic choices; it does not erase prior knowledge of the results.

D7's conclusion is preserved: **B — suppression without demonstrated discrimination improvement**. Nothing here rewrites it.

## 1. Provenance

The eleven registered artifacts, hashed **before** any D8 number existed (in `config.json`, commit `ec2927f`) and **again now**:

| artifact | sha256 before | sha256 after | unchanged |
|---|---|---|:---:|
| `withheld probe table` | `108f11a9e8063488…` | `108f11a9e8063488…` | **yes** |
| `the registered horizon artifact` | `bb494cac316edefb…` | `bb494cac316edefb…` | **yes** |
| `experiments/d7/config.json` | `e7e1e6eb1d2d5f29…` | `e7e1e6eb1d2d5f29…` | **yes** |
| `withheld d7 context summary` | `f37b1dc56a0f2c68…` | `f37b1dc56a0f2c68…` | **yes** |
| `data/market/IBM_1min_unadjusted.txt` | `b1ace385f069764c…` | `b1ace385f069764c…` | **yes** |
| `experiments/d7/runs/d7-001/learned/events.jsonl` | `f24748be0c5af63e…` | `f24748be0c5af63e…` | **yes** |
| `experiments/d7/runs/d7-001/frozen_trained/events.jsonl` | `e5a2a43516087917…` | `e5a2a43516087917…` | **yes** |
| `experiments/d7/runs/d7-001/frozen_reference/events.jsonl` | `df8fdb223196b17e…` | `df8fdb223196b17e…` | **yes** |
| `experiments/d7/runs/d7-001/learned/brain.npz` | `bafb87839b8fe165…` | `bafb87839b8fe165…` | **yes** |
| `experiments/d7/runs/d7-001/frozen_trained/brain.npz` | `2b713cea00152449…` | `2b713cea00152449…` | **yes** |
| `experiments/d7/runs/d7-001/frozen_reference/brain.npz` | `9c85fe87dd8f0b9e…` | `9c85fe87dd8f0b9e…` | **yes** |

All eleven unchanged: **True**. The three `d7-001` event logs and the three checkpoints are among them; nothing was written under `experiments/d7/` or `experiments/d7/runs/`.

`experiments/d8/orientation.json` sha256 `b81929007fbd0071ce40016fe887faa2a672104450d030649ae6f219572e6655` — the file the feature and PC1 table quotes, written before the first evaluation AUC.

## 2. The two grids, and stored versus reconstructed

| | fitting (LEARNING) | evaluation (FROZEN) |
|---|---:|---:|
| dates | 2026-07-06 … 2026-07-17 | 2026-07-20 … 2026-07-31 |
| sessions | 10 | 10 |
| rows | 2789 | 2790 |
| Y = 1 | 1020 | 1235 |
| Y = 0 | 1769 | 1555 |
| grid points before joining | 2789 | 2790 (`withheld-probe-table` as stored) |
| rows dropped | {'UNAVAILABLE_LABEL': {}, 'NO_DECISION_EVENT': 0, 'NON_FINITE': 0} | {'NO_DECISION_EVENT': 0, 'NON_FINITE': 0} |

The fitting grid is `experiments/d7/PROTOCOL.md` §6's rule applied to the ten LEARNING sessions — observation status `OK`, the clock rule `(m+1)+1+90 ≤ 390`, and an available H = 90 label from `horizon.hold` — computed from the session calendar and the price file alone, **independent of positions, trades and inventory**. 279 minutes a session, less the one minute the vendor omits on 2026-07-10, gives 2789. The evaluation grid is the **2790** `withheld-probe-table` rows as stored, with `Y` as stored; that reconciles the reported 2,790 as 279 × 10 from the artifact rather than by assertion.

**Every fitting label resolves before evaluation begins**, asserted from the data and not from the session-bounded argument: max fitting `exit_ts` 2026-07-17T15:59:00-04:00 < min evaluation `market_ts` 2026-07-20T09:51:00-04:00 — True, a gap of 237,120 s.

**Representations.** Stored inputs are primary; every `DECISION` event of `d7-001` carries both.

| | X_FEATURES | X_SENSORY |
|---|---|---|
| source | `observation.normalized` | `stimulus.rates_hz` |
| dimensions | 5 | 10 |
| order | r1, r5, r20, rv20, relvol | VL2a, VM5d, DL1, VL1, VM4, DM3, DM6, V, DM2, DA2 |
| units | dimensionless, `u = tanh(z/2)` ∈ (−1, 1) | Hz per ORN, before Bernoulli spike sampling |
| finite coverage, fitting / evaluation | 1.0000 / 1.0000 | 1.0000 / 1.0000 |
| constant channels | none | none |
| clipping | 0 fitting / 0 evaluation values at \|u\| ≥ 1 | 0 fitting / 0 evaluation values at the 150 Hz ceiling |

**The encoder delivers no sequence.** One constant rate vector per presentation, held over the 20 ms window, so the amendment's ordered-sequence clause is satisfied vacuously: nothing was replaced by its mean, last frame or PC1 because there was no sequence to replace. The eight replicates of a batch share one stimulus, so there is **one row per (session, minute)**, never eight. `n_orns` and `total_drive_hz` are provenance, not features. Ticker and date identifiers, brain outputs, learned-state hashes, account state, rewards, future labels and new technical indicators are all absent by rule.

**Stored versus reconstructed** — §5's STOP condition, on every row of both grids. The reconstruction uses `HistoricalSeries.observe` and `MarketToSensoryEncoder`, which see only bars of the same session at minutes ≤ m, i.e. `bar_end ≤ market_ts`:

| grid | rows | X_FEATURES max \|d\| | mismatches | X_SENSORY max \|d\| after the stored `round(x, 4)` | mismatches | unrounded max \|d\| | `market_ts == bar_end` |
|---|---:|---:|---:|---:|---:|---:|---:|
| fitting | 2789 | 0.0e+00 | 0 | 0.0e+00 | 0 | 4.999e-05 | 2789/2789 |
| evaluation | 2790 | 0.0e+00 | 0 | 0.0e+00 | 0 | 4.999e-05 | 2790/2790 |

**0 mismatches on 5,579 rows**, at a tolerance of 1e-12. `Stimulus.as_dict` rounds `rates_hz` to four decimals, so the stored vector is compared after the same rounding; the unrounded residual is 4.999e-05, below half an ulp of the stored precision, and it is reported rather than hidden. This is also §9's causal-reconstruction test on real rows; the property itself is tested on a generated fixture pair that is identical up to a cut minute and perturbed at every later bar.

**The stimulus does not depend on the branch.** `frozen_trained` carries an identical stimulus on 2790 of 2790 shared evaluation rows; 0 differ.

**The −22 % overnight discontinuity between 2026-07-13 and 2026-07-14 lies inside the fitting partition.** No session-bounded quantity spans it and no row crosses it. None of the five features is price-level dependent: `r1`, `r5`, `r20` are log ratios of closes, `rv20` is the SD of log returns, `relvol` is a log volume ratio, and each is then z-scored over its own trailing 60-row window. It is recorded here, not investigated.

## 3. The descriptive feature and PC1 table

Signs were chosen on the **fitting rows only** — raw fitting AUC, sign = +1 if that AUC ≥ 0.5 else −1 — and written to `orientation.json` before the first evaluation AUC existed. A column below 0.5 may rank in the opposite direction and is not called uninformative for that; **`max(AUC, 1 − AUC)` is never reported** and no sign was chosen or flipped on an evaluation day.

PC1: `numpy.linalg.svd` on the fitting-centred X_SENSORY (2789 rows), **no whitening**, rank 10, explained-variance ratio **0.243304**, degenerate False. Sign convention: the component is signed so that its largest-magnitude loading is positive (that is `DM3`). Loadings, in channel order:

| VL2a | VM5d | DL1 | VL1 | VM4 | DM3 | DM6 | V | DM2 | DA2 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| -0.2168 | +0.2457 | -0.3570 | +0.4194 | -0.4685 | +0.5582 | +0.0951 | -0.1852 | -0.0594 | +0.1064 |

Equal-session mean AUC over the qualifying evaluation sessions, with the 2,000-draw whole-session interval on the oriented column:

| column | fitting raw AUC | sign | evaluation raw | evaluation oriented | 2.5 % | 97.5 % | qualifying sessions |
|---|---:|:---:|---:|---:|---:|---:|---:|
| `r1` | 0.4998 | -1 | 0.5006 | 0.4994 | 0.4834 | 0.5151 | 9 |
| `r5` | 0.4956 | -1 | 0.4862 | 0.5138 | 0.4740 | 0.5530 | 9 |
| `r20` | 0.4957 | -1 | 0.5045 | 0.4955 | 0.4318 | 0.5630 | 9 |
| `rv20` | 0.4962 | -1 | 0.4713 | 0.5287 | 0.4272 | 0.6316 | 9 |
| `relvol` | 0.4848 | -1 | 0.5135 | 0.4865 | 0.4398 | 0.5321 | 9 |
| `PC1` | 0.5043 | +1 | 0.4898 | 0.4898 | 0.4411 | 0.5366 | 9 |

Per-session **raw** AUC (the oriented value is the raw value for a `+1` column and its reflection about 0.5 for a `−1` column):

| session | n | Y=1 | Y=0 | `r1` | `r5` | `r20` | `rv20` | `relvol` | `PC1` | note |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 2026-07-20 | 279 | 119 | 160 | 0.5311 | 0.5751 | 0.6224 | 0.4438 | 0.5617 | 0.3633 | qualifies |
| 2026-07-21 | 279 | 85 | 194 | 0.4910 | 0.3853 | 0.3606 | 0.3038 | 0.5115 | 0.5884 | qualifies |
| 2026-07-22 | 279 | 7 | 272 | 0.5520 | 0.2721 | 0.3739 | 0.6633 | 0.7647 | 0.6838 | 7 profitable and 272 nonprofitable labels, fewer than 10 in one class |
| 2026-07-23 | 279 | 156 | 123 | 0.4767 | 0.4980 | 0.6314 | 0.6314 | 0.4536 | 0.4520 | qualifies |
| 2026-07-24 | 279 | 149 | 130 | 0.5208 | 0.4426 | 0.4587 | 0.5916 | 0.3994 | 0.5769 | qualifies |
| 2026-07-27 | 279 | 54 | 225 | 0.5019 | 0.4535 | 0.5022 | 0.7505 | 0.4706 | 0.5573 | qualifies |
| 2026-07-28 | 279 | 176 | 103 | 0.5374 | 0.5872 | 0.5859 | 0.4838 | 0.4807 | 0.3940 | qualifies |
| 2026-07-29 | 279 | 175 | 104 | 0.4882 | 0.4636 | 0.3351 | 0.2484 | 0.6370 | 0.5177 | qualifies |
| 2026-07-30 | 279 | 101 | 178 | 0.4581 | 0.4620 | 0.5916 | 0.3102 | 0.5017 | 0.4281 | qualifies |
| 2026-07-31 | 279 | 213 | 66 | 0.5006 | 0.5088 | 0.4526 | 0.4784 | 0.6051 | 0.5304 | qualifies |

2026-07-22 is excluded by D7's ≥ 10-per-class rule, exactly as it was in D7, and the exclusion is named rather than absorbed. A one-class session would be **undefined**, not 0.5; there is none here.

This table describes marginal rankings and one projection. **It is not the final input-informativeness verdict.**

## 4. The four joint diagnostic models

Two families on two representations, four fits, exactly the parameters of amendment §6. No tuning, no extra family, no seed search, no model selected on evaluation performance. `StandardScaler` was fitted on the fitting rows only. **The primary joint diagnostic is NONLINEAR on X_SENSORY**, named in `PLAN.md` before any number existed; the other three are secondary comparisons whatever they show.

**These are external measurement tools with supervised access to historical labels. They are not biological models, and their results are never attributed to the fly.** They have no runtime path to the decoder, orders, reward, plasticity or observer decisions.

| model | in-sample AUC | evaluation mean AUC | 2.5 % | 97.5 % | qualifying sessions | rôle |
|---|---:|---:|---:|---:|---:|---|
| LINEAR on X_FEATURES | 0.5166 | **0.5020** | 0.4661 | 0.5410 | 9 | secondary |
| NONLINEAR on X_FEATURES | 0.7809 | **0.4988** | 0.4610 | 0.5384 | 9 | secondary |
| LINEAR on X_SENSORY | 0.5315 | **0.5110** | 0.4774 | 0.5459 | 9 | secondary |
| NONLINEAR on X_SENSORY | 0.7786 | **0.5039** | 0.4737 | 0.5381 | 9 | **primary** |
| REFERENCE fly (D7) | — | 0.4934 | — | — | 9 | comparison |
| TRAINED fly (D7) | — | 0.4904 | — | — | 9 | comparison |

The in-sample column is a description of the fit, not evidence: the nonlinear family reaches 0.78 on the rows it was fitted on and 0.50 on the evaluation rows. It had the capacity to separate the fitting labels and that separation did not generalise to these periods.

Fitting: 2,789 rows over 10 sessions, 1,020 / 1,769. Evaluation: 2,790 rows over 10 sessions, 1,235 / 1,555, coverage 1.0000, one session excluded (2026-07-22). Both logistic fits converged — LINEAR on X_FEATURES `n_iter_` [6], LINEAR on X_SENSORY `n_iter_` [7] against `max_iter` 2000, which was never raised — with **no `ConvergenceWarning` and no warning of any kind**; the HistGradientBoosting fits ran their full 100 iterations with `early_stopping=False`.

Per-session evaluation AUC:

| session | n | Y=1 | Y=0 | LINEAR on X_FEATURES | NONLINEAR on X_FEATURES | LINEAR on X_SENSORY | NONLINEAR on X_SENSORY | REFERENCE | TRAINED | note |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 2026-07-20 | 279 | 119 | 160 | 0.4553 | 0.4319 | 0.4929 | 0.4745 | 0.4976 | 0.4768 | qualifies |
| 2026-07-21 | 279 | 85 | 194 | 0.5964 | 0.5583 | 0.4650 | 0.5572 | 0.5089 | 0.4138 | qualifies |
| 2026-07-22 | 279 | 7 | 272 | 0.3204 | 0.5783 | 0.4669 | 0.5378 | 0.5987 | 0.2831 | 7 profitable and 272 nonprofitable labels, fewer than 10 in one class |
| 2026-07-23 | 279 | 156 | 123 | 0.4723 | 0.6141 | 0.5221 | 0.5964 | 0.4568 | 0.5601 | qualifies |
| 2026-07-24 | 279 | 149 | 130 | 0.5934 | 0.4662 | 0.6286 | 0.5528 | 0.4834 | 0.4727 | qualifies |
| 2026-07-27 | 279 | 54 | 225 | 0.4785 | 0.5315 | 0.5418 | 0.4903 | 0.5209 | 0.6179 | qualifies |
| 2026-07-28 | 279 | 176 | 103 | 0.4805 | 0.5009 | 0.4224 | 0.4659 | 0.4389 | 0.5392 | qualifies |
| 2026-07-29 | 279 | 175 | 104 | 0.4821 | 0.4949 | 0.4986 | 0.4381 | 0.5303 | 0.3759 | qualifies |
| 2026-07-30 | 279 | 101 | 178 | 0.5442 | 0.4896 | 0.4875 | 0.4997 | 0.4363 | 0.4789 | qualifies |
| 2026-07-31 | 279 | 213 | 66 | 0.4155 | 0.4014 | 0.5397 | 0.4601 | 0.5671 | 0.4784 | qualifies |

Paired deltas, on **identical rows and sessions** (2,790 paired rows, 9 paired sessions), each diagnostic minus the fly, with the 2,000-draw paired whole-session interval:

| model | Δ vs REFERENCE | 2.5 % | 97.5 % | above 0 | Δ vs TRAINED | 2.5 % | 97.5 % | above 0 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| LINEAR on X_FEATURES | +0.0087 | -0.0463 | +0.0599 | 62.3% | +0.0116 | -0.0554 | +0.0776 | 62.7% |
| NONLINEAR on X_FEATURES | +0.0054 | -0.0521 | +0.0580 | 56.6% | +0.0083 | -0.0404 | +0.0599 | 61.7% |
| LINEAR on X_SENSORY | +0.0176 | -0.0163 | +0.0581 | 82.1% | +0.0205 | -0.0327 | +0.0774 | 76.6% |
| NONLINEAR on X_SENSORY | +0.0105 | -0.0396 | +0.0605 | 64.8% | +0.0135 | -0.0368 | +0.0598 | 69.9% |

Seeds, declared in `config.json` before any draw: level `flytrade-d8-bootstrap-1` → 2954118192, paired `flytrade-d8-paired-1` → 1942182944, both through `flytrade.metrics.declared_seed`. **These intervals are descriptive and conditional on this dataset and this model fit.** Minute probes with overlapping 90-minute labels are not independent examples; whole sessions are resampled and individual minutes never are. Secondary intervals are not simultaneous family-wise evidence, and no discovery is declared by picking the best column or the one interval that excludes 0.5 — **every diagnostic is shown above**.

**No matched-participation table.** It is a trading-style readout that §2 and §10 would then have to disclaim, and AUC already answers the ranking question; `flytrade.metrics.matched_participation` is not called by D8.

## 5. The target-alignment audit

The 42 actual LEARNING episodes of `d7-001`, read through `flytrade.records` parsing only. The full per-episode table is `alignment.md`; `alignment.json` carries every column §8 lists.

| quantity | value |
|---|---|
| episodes | 42 |
| exit reasons | {'NEURAL_SELL': 42} |
| exits before H = 90 | **42 of 42**; at or after H: 0 |
| actual holding minutes | min 1, median 2, max 19, total 131 |
| actual outcome signs | 5 positive, 37 negative, 0 flat |
| reinforcement signs | 5 reward, 37 punishment |
| hypothetical H = 90 label availability | 42 available, 0 unavailable  |
| hypothetical fixed-H labels | 18 profitable / 24 not |
| actual versus fixed-H signs | 42 compared, 25 agree, **17 disagree** — proportion **0.4048** |
| disagreements by actual sign | 2 where the actual outcome was positive, 15 where it was negative |
| agreements by actual sign | 3 positive, 22 negative |
| costs | 84 executions at 5 bps fee + 5 bps slippage each (20 bps nominal per round trip); fees 41.9838 + slippage 41.9838 = **83.9676** against a gross at reference prices of +9.5396 and a net of -74.4280 |
| cost exceeded gross | 37 of 42 episodes |
| hypothetical entry == actual entry | 42/42 at the reference price, 42/42 after the unchanged slippage, max \|difference\| 0.00e+00 |

The information cutoff and the entry time print as the same clock minute because `bar_end(t)` **is** `bar_start(t+1)`: the decision is taken at the close of minute *t* and the fill is the open of minute *t+1*, which is the same instant. The one-minute execution delay is unchanged.

> These counterfactuals reuse the original entry times. **They do not simulate the trades a fixed-hold policy would actually have taken**, because that policy changes inventory and later entry opportunities. Nothing here updates a weight, replays a reward, modifies an account or rewrites an original event, and **no hypothetical outcome is booked as portfolio PnL** — the per-episode counterfactuals are never summed. This audit measures **alignment**, not whether fixed-hold training would succeed. A future fixed-hold wave requires a separate explicit policy amendment.

## 6. Guards and tests

* No module under `experiments/d8/` imports `flytrade.execution`, `flytrade.runner`, `flytrade.mushroom`, `flytrade.state` or `flytrade.readout`, and none names a mutating API, an account, a cash balance or a bankroll — checked by a static scan of the parsed syntax trees. **Declared**: `flytrade.historical`, which D8 needs to read the price file causally, itself imports `flytrade.execution`; and `flytrade.records`, which addendum 11 *requires* the alignment audit to parse the log with, itself imports `flytrade.runner` and `flytrade.state`. Those transitive imports are unavoidable and are the reason the guard is on direct imports and on named identifiers rather than on `sys.modules`.
* `observer/serve.py` contains no path under `experiments/d8` and was not modified.
* The XOR fixture of §9: each input alone AUC exactly 0.5, PC1 of the pair exactly 0.5, the joint oracle exactly 1.0. Its purpose is to stop the reporting layer ever asserting that marginal chance performance proves absent information. **It does not require any diagnostic model to solve every possible interaction.**
* Determinism: two consecutive fits of each family on the fixture give bit-identical scores, with `OMP_NUM_THREADS=1`.
* No evaluation row reaches a scaler, the PCA or a model fit; changing every evaluation label leaves the fitted models, the signs, the PCA and the already-generated scores bit-identical.
* Constant scores give exactly 0.5 with both classes present, a reversed ranking exactly 0.0, a one-class session `None`; the fast AUC equals the pairwise definition on tie-heavy inputs.
* No downloaded market data enters any test: the D8 suite runs on a deterministic generated fixture pair, and the tree-wide guard in `tests/historical/test_vendor_format.py` enforces it.
* **The D7 evaluator was re-run, read-only, at the close.** `withheld probe table` came back **byte-identical** (sha256 `108f11a9e8063488…` before and after) and every result in `context_summary.json` — the per-session AUCs, `DELTA_AUC` −0.0030, the paired bootstrap and conclusion **B** — reproduced exactly. The file itself differs in two fields only, `written_utc` and `elapsed_s` (1.06 s → 1.08 s): a wall-clock stamp and a measured compute time, neither of which is a result. It was **restored from git**, so `git diff --stat -- experiments/d7` is empty and the registered hash still holds.
* `git diff --stat cc9faaf -- upstream tests/upstream_audit` is empty.

## 7. Conclusions

Amendment §2, reproduced verbatim from `docs/SPEC.md`:

```
2. CORRECT THE INFERENCE BOUNDARIES

Record explicitly:

- An untrained brain near AUC 0.5 does not establish that
  its inputs contain no predictive information.

- Univariate AUCs near 0.5 do not exclude joint interactions
  or non-monotonic relationships.

- PC1 maximizes represented variance, not predictiveness.
  A nonpredictive PC1 does not establish a nonpredictive
  complete sensory representation.

- Failure of the diagnostic models below is evidence about
  these models, data and target, not a universal input ceiling.

- D7 measured fixed-90-minute context ranking, while actual
  learning outcomes followed earlier neural exits.

Do not rewrite D7 as a success. Preserve its conclusion:
suppression without demonstrated improvement on its metric.
```

### INPUT DIAGNOSTICS

**No detectable signal with these methods on these periods.** The primary joint diagnostic — NONLINEAR on X_SENSORY — reaches an equal-session mean AUC of **0.5039** over 9 qualifying evaluation sessions, with a 2.5–97.5 % whole-session interval of 0.4737 … 0.5381 that contains 0.5. The three secondary joint models sit at 0.5020, 0.4988, 0.5110, every interval containing 0.5. Each of the five features and PC1, oriented on the fitting rows alone, sits between 0.4865 and 0.5287, every interval containing 0.5. Paired against the fly on identical rows and sessions, the deltas run +0.0054 to +0.0176 against REFERENCE and +0.0083 to +0.0205 against TRAINED, every interval spanning zero.

**Before and after encoding, the answer is the same.** X_FEATURES and X_SENSORY give the same verdict under both families; there is no detected ranking in the five features that the ten-glomerulus stimulus loses, and none in the stimulus that the features lack. Neither of the amendment's two asymmetric readings applies, because neither side produced a detectable ranking to compare.

This is a statement about **these models, this data and this target**. It is *not* the statement that nothing can learn from these inputs, and §2's five boundaries above are the binding wording: an untrained brain at 0.49 bounds nothing about its inputs; univariate and PC1 chance do not exclude joint structure — the XOR fixture in `tests/d8/` is a concrete case where both marginals are exactly 0.5 and the joint is exactly 1.0; PC1 maximises represented variance, not predictiveness, and here it captures 24.3% of the variance of a representation whose ten channels are five antagonistic pairs. The failure of two small supervised models with fixed parameters, fitted on 2,789 minutes of one instrument over ten days and evaluated on 2,790 minutes over ten more, is evidence about that procedure and not a universal input ceiling.

**A result on these reused dates is a lead, not independent proof** of trading ability or of a theoretical learning ceiling — and here there is not even a lead.

### TARGET ALIGNMENT

**D7 reinforced one quantity and scored another, and the two disagree on 17 of 42 episodes (40.5%).** All 42 of 42 LEARNING episodes exited by neural `SELL` between 1 and 19 market minutes, median 2, 131 minutes of exposure in total; the H = 90 horizon never bound on a single one. The outcome the fly was reinforced on was 5 reward against 37 punishment. The fixed-90-minute label on the same 42 entries, at the same fills and the same costs, is 18 profitable against 24. Of the 17 disagreements, 15 are episodes whose actual outcome was a loss and whose 90-minute counterfactual is a gain, and 2 the other way.

**The arithmetic behind that is the cost, not a prediction.** A 20 bps round trip on a one-to-three minute hold is the whole of the result: total cost 83.9676 against a gross at reference prices of +9.5396, and cost exceeded gross in 37 of 42 episodes. The hypothetical entry is the actual entry on every episode (42/42, max \|difference\| 0.00e+00), so the disagreement is a difference in **holding duration**, not in entry, fill or cost model.

This **limits the interpretation of D7's measurement; it does not invalidate D7's recorded results**, and it is not evidence that aligning the two would produce learning. The counterfactuals reuse the original entry times and do not simulate the trades a fixed-hold policy would have taken. Nothing was booked.

### NEXT-STEP RECOMMENDATION

**Bounded, and not an authorisation.**

1. **Nothing in the input diagnostics supports a new neural wave.** Both of the amendment's readings that would motivate investigating learning, readout or encoding require a *detectable* ranking on one side; there is none on either. The correct record of this wave is "no detectable signal with these methods on these periods", and the correct next action on that basis is **none**.
2. **Option (c) is not launched, and D8 does not authorise it.** Its justification was never an AUC, and D8 produced no AUC that could supply one. The alignment audit is the only substantive positive finding here, and it is a finding about *measurement*, not about learnability. If the owner chooses to open a fixed-hold wave, it requires a separate explicit policy amendment, and the numbers it should be argued from are the audit's (42/42 exits before H, 40.5% sign disagreement, 18/24 against 5/37) — not any ranking result in this document.
3. **A negative D8 does not prohibit fixed-hold experiments, and a positive one would not have guaranteed they work.** Neither does this wave close the scientific question: it closes one bounded test of it.
4. **The product stance is unchanged.** The interface and the spectacle are not hostage to a proof of profitability, and this wave adds no claim of skill, alpha or profitability in either direction.

The wave stops here, as §10 requires. Nothing was reopened: graph, plasticity, gain, window, MBON groups, θ, baseline, encoder, decoder, k, H = 90, costs, sizing, early-`SELL` semantics, datasets and run identities are all exactly as D7 left them.

<!-- generated by experiments/d8/report.py, 2026-09-11T22:27:38Z -->
