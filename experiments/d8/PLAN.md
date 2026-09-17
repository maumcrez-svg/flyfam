# PLAN — D8, the bounded input and target-alignment diagnostic

**RETROSPECTIVE DIAGNOSTIC — D7 RESULTS PREVIOUSLY OBSERVED.**

**Pre-registered.** This file and `config.json` are committed **alone**, before
any D8 number exists. The D7 results on these dates were already seen and
recorded in `experiments/d7/results.md` and in `the session log`; fixing this plan
before the new computations limits opportunistic choices, it does not erase
prior knowledge of those results. **These evaluation dates are not a pristine
holdout**, and nothing in this wave may describe them as one.

Canonical amendment: `docs/SPEC.md` §D8 (owner, 2026-09-11), its recorded owner
rationale, and the **thirteen Fable addenda 0–12** that close it. The owner
text is canonical; where it and an addendum could be read differently, the
addendum's concrete rule applies and this file says which rule was applied.

This wave is **evaluator-only**. No new market-neural run, no retraining, no
checkpoint modification, no parameter search, no download, no new instrument,
no change under `flytrade/`, `upstream/`, `tests/upstream_audit/`, `observer/`
or `experiments/d7/`, and nothing written under `experiments/d7/runs/`.

---

## 0. What is frozen, and therefore not decided by this wave

k = 8 · gain 0.10 · the 20 ms / 100-step presentation window · the encoder's
mapping, normalisation and bounds · the decoder formula and its sign · MBON
membership · `THETA_SD = 1.0` and the k = 8 baseline artifact · the plasticity
rule · market and brain clock semantics · long-only inventory-aware execution,
sizing, fees and modelled slippage · the execution delay and session-boundary
rules · **H = 90** · early-`SELL` semantics · the datasets, dates and run
identities · `upstream/` and `tests/upstream_audit/`.

**D7's conclusion is preserved: B — suppression without demonstrated
discrimination improvement.** D8 does not rewrite it.

## 1. The inference boundaries, recorded before the measurement

Amendment §2, reproduced verbatim at the head of `results.md`'s conclusions:

* An untrained brain near AUC 0.5 does not establish that its inputs contain no
  predictive information.
* Univariate AUCs near 0.5 do not exclude joint interactions or non-monotonic
  relationships.
* PC1 maximizes represented variance, not predictiveness. A nonpredictive PC1
  does not establish a nonpredictive complete sensory representation.
* Failure of the diagnostic models below is evidence about these models, data
  and target, not a universal input ceiling.
* D7 measured fixed-90-minute context ranking, while actual learning outcomes
  followed earlier neural exits.

Addendum 0: reading (2) of the (f) review — that REFERENCE AUC 0.4934 bounds
what the input carries — is **withdrawn**, and so is any reading of univariate
or PC1 chance as an input ceiling.

## 2. Provenance — the artifacts, hashed before any D8 number

| artifact | sha256 |
|---|---|
| `withheld probe table` | `108f11a9e80634885dc0ad64e0855b4118a3f48b2723cc53e41a88b93d5f5c46` |
| `the registered horizon artifact` | `bb494cac316edefb4d9e8146894e2630cc12ca4831b4f5f6841d6acbe0639c52` |
| `experiments/d7/config.json` | `e7e1e6eb1d2d5f2953acbba8d606d34c9db70cafd9be9eb6edc922aec6c7a555` |
| `withheld d7 context summary` | `f37b1dc56a0f2c6806f367a370c08cc9da9060732cf3ca9f07f5cbec131ab867` |
| `data/market/IBM_1min_unadjusted.txt` | `b1ace385f069764c6030f1c292595548166c2478e0390284f1875507e2673db9` |
| `runs/d7-001/learned/events.jsonl` | `f24748be0c5af63e1e794a698c7e987d56e4cfb7cbcfe95411e887b2de876206` |
| `runs/d7-001/frozen_trained/events.jsonl` | `e5a2a4351608791732b03a250f7701f9309d1c67f0dea0d21d1543c608763e21` |
| `runs/d7-001/frozen_reference/events.jsonl` | `df8fdb223196b17e8376ecac1cd08d9932fd14ca2d06ca73f2bead2c3a70f87d` |
| `runs/d7-001/learned/brain.npz` | `bafb87839b8fe1657e169cb4d4d3320adfc4b0b87da5588a637d3bd2d6635ba6` |
| `runs/d7-001/frozen_trained/brain.npz` | `2b713cea00152449a3059d8d396a11ddb4b778895a68fc72f7cd8504a529192a` |
| `runs/d7-001/frozen_reference/brain.npz` | `9c85fe87dd8f0b9e1fb57f7f8869fe08ea07825dfb742b4591c39ba450ba3e6b` |

All eleven are re-hashed at the close and both sets appear in `results.md`. The
three event logs and the three checkpoints must be unchanged.

**The probe count is reconciled, not asserted.** `withheld-probe-table` carries
`n = 2790` rows over ten FROZEN sessions, 279 per session, `H* = 90`, run
`d7-001`. That is the reported 2,790 and it is taken from the artifact.

## 3. The two grids

**Fitting grid** — `experiments/d7/PROTOCOL.md` §6's grid rule applied to the
ten LEARNING sessions **2026-07-06 … 07-17**: a market minute whose
`HistoricalSeries` observation status is `OK` — which already means past the
20-minute per-session feature lookback and past the 60-row causal normalisation
window — and which satisfies the clock rule `(m + 1) + 1 + 90 ≤ 390`, and whose
H = 90 label is available from `flytrade.horizon.hold` on the price file. The
rule reads the session calendar and the price file only: it is **independent of
positions, trades and inventory**, exactly as the FROZEN grid was branch-blind.

**Evaluation grid** — the `withheld-probe-table` rows **as stored**, with `Y` as stored.
No row is added, dropped or relabelled.

**Labels.** `G(t)` = net return on notional of a hypothetical fixed-notional
LONG entered under the `flytrade.horizon` fill convention (entry = the open of
the first available bar with `bar_start ≥ t + 1` market minute, same session;
exit = the open of the first available bar with `bar_start ≥ entry_minute + 90`,
same session) and held H = 90 market minutes, at notional 1000 with the
original 5 bps fee and 5 bps slippage per execution. `Y(t) = 1` when `G(t) > 0`,
else 0. Fitting labels are computed by `horizon.hold`; evaluation labels are
taken from `withheld-probe-table`.

**Every fitting label resolves before evaluation begins.** Holds are
session-bounded, so no fitting label can resolve after 2026-07-17 16:00. That
argument is not the test: the test asserts, **from the data**, that
`max(exit_ts)` over the fitting rows is strictly less than `min(market_ts)` over
the evaluation rows.

**The −22 % overnight discontinuity between 2026-07-13 and 07-14 lies inside the
fitting partition.** No session-bounded quantity spans it. None of the five
features is price-level dependent: `r1`, `r5`, `r20` are log ratios of closes,
`rv20` is the SD of log returns, `relvol` is a log volume ratio, and each is
then z-scored over its own trailing 60-row window. `results.md` names the
discontinuity.

**Joining.** Rows are joined to the stored representations by `(session,
minute)`: fitting rows to `runs/d7-001/learned/`, evaluation rows to
`runs/d7-001/frozen_reference/`. A grid row with no `DECISION` event at its
minute is excluded and counted; coverage is reported.

## 4. The two representations

Stored inputs are **primary** (addendum 1: every `DECISION` event already
carries both).

**X_FEATURES**, 5 dimensions, fixed order `r1, r5, r20, rv20, relvol` —
`DECISION.observation.normalized`, the causal features z-scored over a trailing
60-bar window ending at the cutoff and squashed by `u = tanh(z / 2)`, in
(−1, 1), dimensionless. This is exactly the vector
`MarketToSensoryEncoder.encode` receives. Stored at full float64 precision.

**X_SENSORY**, 10 dimensions, fixed channel order

| feature | positive glomerulus | negative glomerulus |
|---|---|---|
| `r1` | `VL2a` (98 ORNs) | `VM5d` (84) |
| `r5` | `DL1` (83) | `VL1` (82) |
| `r20` | `VM4` (78) | `DM3` (63) |
| `rv20` | `DM6` (58) | `V` (55) |
| `relvol` | `DM2` (54) | `DA2` (48) |

— `DECISION.stimulus.rates_hz`, the deterministic per-ORN drive in Hz before
Bernoulli spike sampling, one vector per presentation, constant over the 20 ms
window. **The encoder delivers no sequence**, so the amendment's ordered-
sequence clause is satisfied vacuously and `results.md` says so. The eight
replicates of a batch share one stimulus, so there is **one row per (session,
minute)**, never eight. `n_orns` and `total_drive_hz` are provenance, not
features. `Stimulus.as_dict` rounds `rates_hz` to 4 decimals; the stored,
rounded values are what the models see.

Not included, by rule: ticker or date identifiers, brain outputs, learned-state
hashes, account state, rewards, future labels, new technical indicators.

Reported for both: exact dimensions, finite-value coverage, constant channels
and clipping.

## 5. Stored versus reconstructed — the causality check, and a STOP

Both representations are rebuilt from the price file with the existing code:
`flytrade.historical.HistoricalSeries.observe` (whose per-session feature table
uses bars at minutes ≤ m of the same session, i.e. `bar_end ≤ market_ts`, and
whose trailing z-window reaches backwards only) and
`flytrade.encoder.MarketToSensoryEncoder` built from the same annotations.

Agreement is asserted **within 1e-12 on every row of both grids**. X_FEATURES is
compared at full precision. X_SENSORY is compared after applying the same
`round(x, 4)` the stored artifact applies, and the unrounded maximum absolute
difference is reported as well.

**The mismatch count is a reported number, and a non-zero count STOPS the wave
before any model is fitted.** This is also §9's feature-reconstruction-with-
causal-timestamps test.

The `frozen_trained` log must carry an **identical** stimulus on every shared
evaluation row — the stimulus does not depend on the branch — and the count is
reported.

## 6. The descriptive feature and PC1 table

Per-session **raw** AUC for each of the five scalar features against the same
`Y`, on the evaluation rows, by `flytrade.metrics.roc_auc`.

A feature with AUC below 0.5 may rank in the opposite direction; it is not
called uninformative for that reason. For an oriented score, the sign is chosen
on the **fitting rows only**: raw AUC on the fitting rows, sign = +1 if that AUC
≥ 0.5, else −1. The signs are written to `experiments/d8/orientation.json`
**before any evaluation AUC is computed**, and that file's sha256 appears in
`results.md`. Evaluation reports the raw **and** the oriented per-session AUC.
`max(AUC, 1 − AUC)` is never reported.

PC1: `numpy.linalg.svd` on the **fitting-centred** X_SENSORY, fitting rows only,
**no whitening**, no evaluation-period PCA fitting. The explained-variance
ratio, the ten loadings and the sign convention (the component is signed so
that its largest-magnitude loading is positive) are recorded. Its target-based
orientation sign is a separate factor, chosen on fitting rows only, by the same
rule. A constant or rank-deficient representation makes the PC1 line read
**degenerate**, not a number.

This table describes marginal rankings and one projection. **It is not the final
input-informativeness verdict.**

## 7. The four joint diagnostic models

Exactly two families on both representations, four fits, excluding synthetic
unit tests.

**LINEAR** — `StandardScaler` fitted on the fitting rows only, then
`LogisticRegression(C=1.0, solver="lbfgs", max_iter=2000)`, L2, **no class
rebalancing and no feature selection**. `n_iter_` is reported; a
`ConvergenceWarning` is reported, never silenced, and `max_iter` is never
raised.

**NONLINEAR** — `HistGradientBoostingClassifier(learning_rate=0.1,
max_iter=100, max_depth=3, max_leaf_nodes=8, min_samples_leaf=20,
l2_regularization=1.0, early_stopping=False, random_state=8)`, no class
rebalancing, no scaling.

The score is `predict_proba(...)[:, 1]`, continuous.

**The primary joint diagnostic is NONLINEAR on X_SENSORY**, named here before
any number exists. The other three are secondary comparisons **whatever they
show**.

No parameter tuning, no additional families, no seed search, no model selected
on evaluation performance. Fitting failures are reported without silent
replacement.

**Determinism.** The four fits run with `OMP_NUM_THREADS=1`, recorded, and a
test asserts that two consecutive fits of each family on a fixture produce
identical scores.

**These are external measurement tools with supervised access to historical
labels. They are not biological models and their results are never attributed
to the fly.** They have no runtime path to the decoder, orders, reward,
plasticity or observer decisions: no module under `experiments/d8/` directly
imports `flytrade.execution`, `flytrade.runner`, `flytrade.mushroom`,
`flytrade.state` or `flytrade.readout`, and `observer/serve.py` contains no path
under `experiments/d8`.

Resolved dependency: **`scikit-learn==1.9.1`**, the newest release that installs
against the frozen `numpy==2.4.2` / `scipy==1.17.1` on Python 3.13.9 without
moving them, added as the optional extra `diagnostics` in `pyproject.toml`. The
main `dependencies` list is untouched. D8 tests import sklearn directly, with no
`importorskip`.

## 8. Evaluation

`flytrade.metrics.roc_auc` — midranks, ties at 0.5 credit, a one-class session
**undefined (`None`), never 0.5**. D7's session rule is retained: an evaluation
session qualifies with **at least 10 probes of each class**; if 2026-07-22 drops
as it did in D7, the drop is reported. Every qualifying session carries equal
weight.

Reported per diagnostic: fitting and evaluation row counts, unique sessions,
class counts, per-session AUC, equal-session mean AUC, coverage and exclusions.
Fitting uses all resolved rows of all ten LEARNING sessions and their
per-session class counts are reported for information.

Comparisons between X_FEATURES, X_SENSORY and the fly use the **same paired
evaluation rows**, and the paired counts are shown.

**No matched-participation table.** It is a trading-style readout that §2 and
§10 would then have to disclaim, and AUC already answers the ranking question.
`flytrade.metrics.matched_participation` is not called by D8.

**Bootstrap**, both uses seeded from `flytrade.metrics.declared_seed` on a label
recorded in `config.json`:

* **level** — for each of the four models, each oriented feature and PC1: 2,000
  whole-session draws of the qualifying evaluation sessions, mean AUC per draw,
  2.5–97.5 % interval. Seed label `flytrade-d8-bootstrap-1` → `2954118192`.
  Implemented in `experiments/d8/bootstrap.py` and unit-tested on a fixture
  against `flytrade.metrics.paired_session_bootstrap`.
* **paired** — paired deltas on identical rows and sessions, each diagnostic
  minus the REFERENCE fly and minus the TRAINED fly, through
  `flytrade.metrics.paired_session_bootstrap` with the diagnostic in the first
  slot. Seed label `flytrade-d8-paired-1` → `1942182944`.

No fitting happens inside a bootstrap. The intervals are **descriptive and
conditional on this dataset and this model fit**. Minute probes with overlapping
90-minute labels are **not independent examples**. Secondary intervals are not
simultaneous family-wise evidence.

**All diagnostics are shown.** A discovery is not declared by selecting the best
column or the one interval that excludes 0.5. A result on these reused dates is
a lead, not independent proof of trading ability or of a theoretical learning
ceiling.

## 9. The target-alignment audit

Using only the existing actual LEARNING episodes — the
`ROUND → DECISION → EXECUTION → OUTCOME → LEARNING` chains of the LEARNING
partition of `runs/d7-001/learned/events.jsonl`, parsed through
`flytrade.records`.

Per episode: entry time and information cutoff; actual exit time and reason;
actual holding duration; gross and net actual outcome; actual reinforcement
sign; hypothetical net outcome at H = 90 when available; hypothetical fixed-H
label. The hypothetical quantity is `flytrade.horizon.hold` at the **original
decision minute** with the **original cost constants**, and its entry fill must
equal the actual entry fill price on every episode — the count is reported.

Summarised: how many exits occurred before H; actual versus fixed-H outcome
signs; the proportion of sign disagreements; counts and magnitude of costs;
hypothetical-label availability; plus min / median / max actual holding minutes
and the sign-disagreement count split by actual sign.

Written to `withheld d8 alignment table` and `experiments/d8/alignment.md`.
**Nothing updates a weight, replays a reward, modifies an account or rewrites an
original event, and no hypothetical outcome is booked as portfolio PnL.**

These counterfactuals reuse the original entry times. **They do not simulate the
trades a fixed-hold policy would actually have taken**, because that policy
changes inventory and later entry opportunities. This audit measures
**alignment**, not whether fixed-hold training would succeed. A future
fixed-hold wave requires a separate explicit policy amendment.

## 10. Tests

Under `tests/d8/`, committed with the section they test, importing sklearn
directly:

* no evaluation row is used in scaler, PCA or model fitting;
* no fitting label resolves after evaluation begins — asserted from the data;
* feature reconstruction with causal timestamps (§5's 1e-12 agreement);
* changing evaluation labels cannot change a fitted model or an already
  generated score;
* sign selection uses fitting data only;
* constant scores, reversed rankings, ties and one-class AUC;
* evaluator imports cannot execute orders or apply learning;
* immutable checkpoint and source-log hashes;
* counterfactual outcomes cannot affect bankroll;
* determinism: two consecutive fits give identical scores;
* the **XOR fixture**: each input alone has AUC 0.5 and a joint oracle score has
  AUC 1.0. Its purpose is to prevent the reporting layer from asserting that
  marginal chance performance proves absent information. It does **not** require
  every diagnostic model to solve every possible interaction.

## 11. Conclusions and stop

`results.md` reproduces amendment §2's five statements verbatim at the head of
its conclusions and then reports, separately:

* **INPUT DIAGNOSTICS** — what these limited tests detected or failed to detect,
  before and after encoding;
* **TARGET ALIGNMENT** — how actual reinforcement outcomes differ from the
  fixed-horizon quantity used in D7's evaluation;
* **NEXT-STEP RECOMMENDATION** — bounded, not an automatic authorisation.

The permitted readings are §10's: detectable ranking from X_SENSORY but not from
the fly supports investigating learning / readout / target alignment without
proving which component caused the difference; ranking from X_FEATURES but not
X_SENSORY motivates inspecting encoding or diagnostic-model mismatch without
proving irreversible information loss; and no stable ranking reads **"no
detectable signal with these methods on these periods"**, never "nothing can
learn from these inputs".

A negative D8 result does not logically prohibit fixed-hold experiments; a
positive result does not guarantee they work. **Option (c) is not launched.**

The regression gate runs twice at closure. The wave stops after this single
evaluator-only pass. Downloaded and derived market data stay outside Git.
