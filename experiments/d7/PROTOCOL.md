# PROTOCOL — D7, the WARMUP-selected horizon and context discrimination

**Pre-registered.** This file and `config.json` are committed **alone**, before
any D7 calibration, run or evaluation exists, and before `registered-horizon-artifact`
exists. Nothing in this directory has been executed against the 2026-06-15 …
07-31 window at the moment of this commit. Any run started before it is
discarded and said to be discarded, exactly as
`experiments/conditioning/PROTOCOL.md` (`b9655ea`),
`experiments/k8_readout/PROTOCOL.md` (`4b8e082`) and
`experiments/historical/PROTOCOL.md` (`7b21c8e`) were handled.

Canonical amendment: `docs/SPEC.md` §D7 (owner, 2026-09-11), its recorded
owner rationale, and the **twelve Fable addenda** that close it. The owner text
is canonical; where it and an addendum could be read differently, the
addendum's concrete rule applies and this file says which rule was applied and
why.

---

## 0. What is frozen, and therefore not decided by this wave

k = 8 · gain 0.10 · the 20 ms / 100-step presentation window · the encoder's
mapping, normalisation algorithm and declared bounds · MBON membership (29
avoid, 16 approach) · the decoder formula and its sign · `THETA_SD = 1.0` and
the stored k = 8 baseline artifact, loaded at full precision · one normalised
learning update per settled outcome · episode-specific credit assignment ·
market and brain clock semantics · long-only inventory-aware execution,
position sizing, fees and modelled slippage · the execution delay and the
session-boundary rules · `upstream/` and `tests/upstream_audit/`.

**The one permitted behavioural parameter change is the fixed holding horizon
H\*, and it is selected by the rule in §4 from WARMUP data alone.**

`SELL` does not become `SHORT`. Early neural `SELL` decisions are not disabled
to improve a result. The reward rule is unchanged and is not replaced by gross
PnL. Costs are not reduced to manufacture positive reinforcement. Success is
not defined as profitability, as more BUY actions, as more reward events or as
a preferred reward/punishment balance.

---

## 1. Data, instrument and window

`HISTORICAL_MARKET`, the **already hashed** Kibot IBM sample. Nothing was
downloaded for this wave and the file is not replaced by a newer rolling
sample:

```
IBM_1min_unadjusted.txt   sha256 b1ace385f069764c…   23,777 rows
first bar 2026-06-15 09:30 ET      last bar 2026-09-10 15:59 ET
```

**IBM only.** OIH is excluded by amendment §1 because of the availability
problem reported in the previous window — 18.7 % of its minutes are absent —
and not because of its returns. It stays in `data/market/` and in the system,
and the loop's capacity for six instruments is retained and unused. No series
is duplicated, renamed or resampled.

Coverage for the new window was appended to `data/MANIFEST.md` in commit
`e4ca27d`, **before** this file, exactly as Fable addendum 11 requires: 33
regular sessions, 12,869 of 12,870 scheduled bars, one missing minute
(2026-07-10 13:06 ET), no early close, and 2026-06-19 and 2026-07-03 recorded
as NYSE holidays rather than gaps. Dates never move. A coverage failure is a
reported blocker, not permission to choose different dates.

| partition | first | last | sessions | neural | learning | forgetting |
|---|---|---|---:|---|---|---|
| `WARMUP` | 2026-06-15 | 2026-07-02 | 13 | **off** | off | off |
| `LEARNING` | 2026-07-06 | 2026-07-17 | 10 | on | **on** | off |
| `FROZEN` | 2026-07-20 | 2026-07-31 | 10 | on | **off** | off |

No observation from **2026-08-03 … 09-04** — the `hist-003` window — enters
feature initialisation, H calibration, learning, evaluation or baseline
recalibration. The two windows are disjoint by date and the file is read
through `HistoricalSeries`, whose causal feature table is built per session and
whose trailing normalisation window is a window over this instrument's own
earlier **usable rows in this file**. That window reaches backwards only, so a
LEARNING minute can see WARMUP rows and never the reverse.

This is a **revised historical experiment**. It is not prospective evidence:
the design was informed by `hist-003`, and only the numerical calibration and
evaluation use disjoint dates.

## 2. Clock and cadence — unchanged

Bar timestamp = bar open; `bar_end = bar_start + 60 s` is the first instant the
bar may be read; regular session only, 390 minutes, America/New_York, canonical
storage UTC (**Fable addendum 1: the timestamps already are UTC epoch seconds
on an America/New_York session grid — there is no clock migration in this
wave**); one decision round per regular-session minute bar at which the
instrument reported a bar; two clocks in every `DECISION` event; decay once per
round in brain time; `MushroomBody.forget()` is not called in the loop, in any
partition; lookbacks never cross a session, so the first 20 market minutes of
every session are `WARMUP` and so are the first 60 usable rows of the file.

A bar's completed OHLCV is never used at its own opening timestamp, and missing
clock time is never compressed.

## 3. One fill convention, three callers — Fable addendum 1

`flytrade/horizon.py` holds the convention, once:

* **entry** = the open of the first available bar with
  `bar_start ≥ t + 1 market minute`, same session;
* **exit** = the open of the first available bar with
  `bar_start ≥ entry_minute + H`, same session;
* **eligibility** = `(t + 1) + 1 + H ≤ 390`, a clock rule checked before any
  price is read.

`HistoricalExecution._locate` **calls** `horizon.locate`, so the calibration
return `g(t,H)`, the evaluator label `G(t)` and the `POLICY_CLOSE` fill locate
their bars with one function rather than with three implementations that agree
today. `tests/d7/test_fill_convention.py` proves the three produce the same two
bars, the same two reference prices and the same money to 1e-12 on every
candidate horizon, and that a **missing bar** is three declared behaviours of
the one rule: the origin leaves the common set (calibration), the label is
`UNAVAILABLE_LABEL` (evaluator), the fill is delayed and flagged `DELAYED_FILL`
(execution).

`g(t,H)` is **gross**, at the unslipped reference opens, in basis points.
`G(t)` is the **net** return on notional of the same hold after unchanged
costs. Both come from the same two prices.

## 4. The horizon-selection rule, in full

```
H_SET   = [8, 15, 30, 60, 90, 120]           elapsed market minutes
C       = the round-trip cost in basis points, MEASURED
A(H)    = median across qualifying WARMUP sessions of
          [median across that session's common origins of |g(t,H)|]
H*      = the smallest H in H_SET with A(H) >= 2 * C
```

**C is measured, not asserted** (Fable addendum 2). `calibrate.py` runs one
flat-price round trip through the real `HistoricalExecution` at the configured
notional and takes `-net_pnl / notional` in basis points. The config's 5 bps
fee and 5 bps slippage are charged **per execution**, so the arithmetic
expectation is 10 bps per leg and C = 20 bps, 2C = 40 bps; the **measured**
figure governs and both the per-leg and the round-trip lines appear in
`registered-horizon-artifact`. A round-trip charge is never reinterpreted as a per-leg charge
and C is never read off rounded report text.

**A qualifying WARMUP session** (amendment §3) has at least 95 % of its 390
scheduled one-minute bars, valid deduplicated OHLCV — enforced by
`parse_kibot_minute`, which rejects rather than repairs — and at least **100
usable common calibration origins**. Eligibility is data quality only: never
volatility, profitability or reward balance. **All** qualifying sessions in the
fixed window are used; ten are not cherry-picked from thirteen. Fewer than ten
qualifying sessions is reported as `INSUFFICIENT_WARMUP`, and dates are not
extended, criteria are not relaxed and no instrument is substituted.

**The common origin set** (Fable addendum 6) is built once per session and
shared by every candidate horizon, so a difference between two `A(H)` values is
a difference in horizon and never a difference in sample. An origin must have
causally available features (status `OK`), permit the entry delay, permit the
**maximum** candidate horizon inside the session — the clock rule with H = 120,
i.e. `t ≤ 268` — and have observed entry and exit opens for **all six** H.

**Only WARMUP prices are ever read.** This is enforced, not promised: the
calibration is handed a `WarmupOnly` view of the series that **raises** if any
code asks it for a session outside the qualifying WARMUP set, and the view
records which sessions it touched into the artifact. The §10 guard test is a
fixture whose WARMUP bytes are identical and whose every later price is
multiplied by a constant; it must give the same `A(H)` table and the same H\*.

This is a fixed movement-versus-cost operating rule. **It is not a forecast of
profitability and not a claim that returns are predictable.** H\* is not
selected by strategy PnL, mean signed return, win rate, reward balance, decoder
output, or any LEARNING or FROZEN result. Horizons are not interpolated and no
second multiplier is tried.

If no candidate qualifies: **`NO_HORIZON_MEETS_RULE`**. The calibration table,
the implementation and the tests are delivered; H = 120 is not silently chosen;
the multiplier is not lowered; and no LEARNING experiment is started or
claimed. H\* is frozen for every subsequent D7 run, and `run.py` refuses to
start without the artifact.

## 5. The LEARNING run

The existing chronological paper-learning loop —
`experiments/historical/run.py::run_branch`, the same function `hist-003` ran —
over `LEARNING` at H\*, from the **declared clean reference checkpoint**
(`ba95b605…`, re-derived at start-up and compared), with the D4 training seed
schedule unchanged. One preregistered seed schedule: no search over training
seeds and no retained winner.

Only actual settled paper episodes generate reinforcement. No reward is
computed for an unchosen action or for a hypothetical probe trade. Session
boundaries and the existing handling of delayed and missing fills are
preserved. One declared mid-run restart after 3 settled episodes, exactly as
`hist-003` declared it, and the restored gains must match exactly or the run is
refused.

Reported: completed episodes; gross, net and the cost breakdown; reward,
punishment and neutral counts; the **actual holding-duration distribution**;
neural `SELL`, `POLICY_CLOSE` and session-close counts; `INVALID_STATE`, `WAIT`
and `NO_RESPONSE`; and the observation-availability → fill delay distribution,
printed so that an off-by-one in the timing cannot stay hidden.

**H\* is a maximum/fixed policy horizon under the existing execution semantics,
not a guarantee that a neural trade lasts H\* minutes.** Fable addendum 7 says
this before the run: `hist-003` exited 34 of 37 episodes by neural `SELL`, and
if that repeats, actual exposure stays one or two minutes whatever H\* is and
the reward distribution is nearly `hist-003`'s. The report therefore
cross-tabulates **exit reason × reward sign × holding minutes**, so a reader
can see whether H\* bound at all. That is a finding. Nothing is changed to make
it bind, and early `SELL` decisions are not suppressed.

## 6. FROZEN, two branches, and the probe grid

Two fixed checkpoints over the same FROZEN observations:

* **TRAINED** — the final D7 LEARNING checkpoint, loaded from
  `runs/<id>/learned/brain.npz` and refused unless its digest equals the
  LEARNING end digest that stage `learn` recorded;
* **REFERENCE** — the clean reference checkpoint, untrained.

Learning and forgetting are off in both; the end-of-partition hash must equal
the start hash in both. Separate accounts, journals, event logs and episode-id
spaces. Both branches draw the paired `comparison_v1` seeds, which are keyed to
(observation id, stable id, replicate) and **not** to the weight digest, so a
difference between the branches is a difference in weights and not in noise.

**The probe is the ordinary per-round readout** (Fable addendum 3). With IBM
alone, `run_branch` evaluates exactly one candidate every round — the held
symbol while holding, IBM itself while flat — so every round already carries
one readout under the comparison seeds. The probe dataset is therefore
extracted by a **read-only post-run evaluator** over the two FROZEN event logs
plus the price file, after both branches have finished. There is no runtime
hook, no second neural pass, and nothing about the probes can touch weights,
eligibility, orders, reinforcement or the experiment clock, because nothing
about the probes runs while the experiment does.

One **log-only** change to `run_branch` is declared here and was made in commit
`090c0d7`, before this protocol: a round whose only measured candidate is not
selectable — the decoder read `NO_RESPONSE` or `INVALID_STATE` while the
account was flat — now writes its `DECISION` event. No weight, account, seed,
order or counter moves, and the round still takes no decision. Without it the
probe dataset would silently depend on which branch happened to be holding a
position, which amendment §6 forbids.

**The probe grid** (Fable addendum 5) is branch-blind by construction: it is
computed from the session calendar and the price file **before either event log
is opened**. A grid point is a FROZEN minute whose observation status is `OK` —
which already means past the 20-minute per-session feature warm-up and past the
60-row causal normalisation window — and which satisfies the clock rule with
H\*: `(m + 1) + 1 + H* ≤ 390`. It does not depend on which branch bought, on
inventory, on score sign or magnitude, or on any later outcome.

**The score** is the `DECISION` event's continuous `valence_hz`: the decoder's
centred V, before thresholding and before inventory constraints. The BUY flag
itself is never the score. Fable addendum 4 asks which case applies, and it is
the first: **the decoder does record V on `NO_RESPONSE`** —
`ActionDecoder.decode_rates` computes `V = raw − baseline` before it branches on
status, so a silent readout carries `V = 0 − BASELINE_HZ₈ = +0.844389816810345`
at full artifact precision. The fallback recomputation in addendum 4 is
therefore **not needed and not used**, and silent contexts stay in the analysis
with their actual finite readout, as §7 requires. `INVALID_STATE`, `DATA_GAP`,
`STALE_DATA` and `WARMUP` are exclusions, counted per branch; the paired set is
the intersection.

One reading the addenda leave open, decided here rather than later:
**`POLICY_REJECT` rounds keep their score.** A `POLICY_REJECT` is an execution
refusal applied *after* a reading that was `VALID`; §7 asks for the continuous
score "before thresholding and before inventory constraints", and dropping
those rounds would make the paired set depend on inventory, which §6 forbids.
They are counted separately and reported.

**The label**, attached only after the scores are recorded:

```
G(t) = net return on notional of a hypothetical fixed-notional LONG entered
       under the existing fill convention and held for H*, costs unchanged
Y(t) = 1 when G(t) > 0, else 0
```

One common `G(t)` serves both branches. The labels measure fixed-horizon
**entry-context** quality and not the quality of every possible exit action.
They are analysis-only counterfactuals: no learning event, no change to any
paper bankroll, and **no summing of overlapping probes into an executable
PnL** — there is one probe per eligible minute and each hold is H\* minutes
long, so consecutive probes overlap by construction. A missing future price is
`UNAVAILABLE_LABEL` with an explicit count; a fill is never invented and an
unavailable label is never replaced by a loss. Future labels exist only inside
the evaluator.

## 7. The primary metric

For each FROZEN session with **at least 10 profitable and 10 nonprofitable**
probe labels, ROC-AUC is computed separately for TRAINED and REFERENCE **on the
same paired set**:

```
AUC       = P(profitable scores higher than nonprofitable), ties at 0.5 credit
DELTA_AUC = mean across qualifying sessions of [AUC_TRAINED - AUC_REFERENCE]
```

Every qualifying session carries equal weight whatever its probe count. Both
mean AUC levels and every session's result are reported. **At least five
qualifying sessions** are required before an aggregate context-discrimination
conclusion is stated. A constant score with both classes present is exactly
0.5; a one-class session is **undefined**, not 0.5, and is listed by name with
its class counts.

Technically successful silent responses stay in the analysis with their actual
finite readout; `NO_RESPONSE` is preserved as a separate status and silent
contexts are never dropped to improve an AUC. Exclusions are disclosed per
branch and paired, and both AUCs use the same paired set. **If either branch or
the paired set covers less than 95 % of otherwise label-available probes, the
aggregate inference is marked coverage-limited / inconclusive.**

The §7 metric tests are committed (`tests/d7/test_metrics.py`): subtracting a
constant from every reference score does not improve AUC; positive uniform
rescaling does not improve AUC; constant scores give 0.5 when both classes
exist; perfect and reversed rankings give 1.0 and 0.0; ties and missing classes
are handled explicitly; and the fast implementation equals the pairwise
definition itself on tie-heavy random inputs. This is what stops blanket
inhibition from being counted as improved context ranking.

## 8. The secondary check, at matched participation

Within each session, the highest-scoring **20 %** of probes is selected for
each branch independently, and the two slices' mean `G(t)` and profitable-label
rate are compared. Both branches select the same fraction, so "buying less"
cannot explain an advantage. Boundary ties are handled by **fractional
weighting** — every probe tied at the cutoff carries the same fractional weight
and the total weight is exactly `0.20 × n` — and ties are never broken by a
future label or by time order. 20 % is fixed and no percentile is searched
over.

This is a retrospective ranking diagnostic. It is **not** a new trading policy
and **not** a backtested executable portfolio. Actual BUY / SELL / WAIT
frequencies are reported separately, at their own denominators, and a useful
score ranking with almost no executable BUY actions is not described as
profitable trading behaviour.

## 9. Dependence, uncertainty and the three conclusions

Overlapping H-minute outcomes are **not independent trials**. Reported: unique
sessions, probe counts and class counts, actual completed trade counts, and
every session's effect.

Uncertainty is a **paired session resampling**: 2,000 bootstrap draws of whole
qualifying sessions, both branches kept paired, with the seed declared here
before any draw — `3219987367`, which is `sha256("flytrade-d7-bootstrap-1")[:4]`
as a big-endian unsigned integer. It is described as limited, day-resampled
uncertainty **conditional on this training run**, not a definitive significance
test. Individual minute rows are never bootstrapped as independent data.

The closing conclusion is exactly one of:

* **A — context-discrimination evidence in this experiment**: improved
  within-session ranking relative to the reference, considered alongside the
  trained AUC level, the uncertainty summary, coverage and matched
  participation;
* **B — suppression without demonstrated discrimination improvement**: lower
  BUY frequency without a supported improvement in context ranking;
* **C — inconclusive**: too few informative sessions, inadequate coverage,
  unstable effects, or uncertainty that does not resolve the question.

A positive `DELTA_AUC` alone is insufficient if TRAINED remains at or below
chance-level ranking. Failure to demonstrate discrimination is **not** proof
that this system can never learn any market structure, and a positive
scientific outcome is not required for engineering completion.

## 10. Guards, observer, compute and delivery

Committed tests (`tests/d7/`, on generated fixtures only — no downloaded data
enters a test and a test enforces it): changing LEARNING/FROZEN prices cannot
change H selection; the calibration cannot access a price outside WARMUP; all H
candidates use the declared common origins; changing evaluator labels cannot
change a neural score; probes cannot mutate learning, accounts or decisions —
the evaluator imports no part of the loop and leaves both logs byte-identical,
which it also records as a hash pair in its own output; FROZEN weights remain
unchanged; overlapping hypothetical probes are not booked as trades and the
trade count comes from the account the run booked; a restart cannot put one
minute into the dataset twice.

**Observer.** `.venv/bin/python observer/serve.py` → `http://localhost:8765/`,
unchanged in kind: vanilla JS, no build, no npm, stdlib `http.server` on
127.0.0.1, read-only, and it still computes nothing. Four additions and no
others: the selected H and its calibration provenance; an explicit *actual*
versus *hypothetical / probe* distinction wherever both appear; the current
phase and historical timestamp; and the final context-discrimination summary
**after** the evaluation. No future probe label is revealed during earlier
playback: a probe's label is displayed only once the replay cursor has passed
the minute at which that label's exit price existed, and the context summary is
revealed only at the end of the replayed partition. No new frontend.

**Compute** (Fable addendum 9), measured before the run at 29.3 ms per 20 ms
presentation, one process, no parallelism:

| stage | rounds | encodable | presentations | estimate |
|---|--:|--:|--:|--:|
| `WARMUP` | 5,070 | 4,751 | 0 (no neural) | ≈ 0 |
| `LEARNING` | 3,899 | 3,699 | 29,592 | **≈ 14.5 min** |
| `FROZEN`, trained | 3,900 | 3,700 | 29,600 | **≈ 14.5 min** |
| `FROZEN`, reference | 3,900 | 3,700 | 29,600 | **≈ 14.5 min** |
| | | | | **≈ 43.5 min** |

Under the 90-minute ceiling, so the reduction rule does **not** fire. It is
written anyway, before the run, because writing it afterwards would not be a
rule:

> **Reduction rule.** If the pre-run estimate exceeds 90 minutes, `LEARNING` is
> run on its **last N sessions** only, N being the largest integer for which
> the total estimate falls under 90 minutes. The dropped sessions are named in
> the report. `WARMUP` and `FROZEN` are never shortened, dates are never
> shifted, and **k is never reduced.**

The neural stages run in the background while the observer additions are
written.

**Runs and retries.** Every invocation is stamped with a run id `d7-NNN` under
`experiments/d7/runs/` (gitignored). A retry after a software correction gets a
new run id; the failed run's directory and its explanation are kept and
reported. `hist-003` and every earlier artifact are untouched.

**Commit order** (Fable addendum 12), one Opus agent, sequential:

1. the coverage manifest — `e4ca27d`;
2. the calibration module, the evaluator and the metric tests on fixtures —
   `090c0d7`;
3. **this file and `config.json`, alone** — before any D7 number exists;
4. the calibration run and the H\* artifact, alone;
5. the LEARNING run; 6. FROZEN, both branches; 7. the evaluator run;
8. the observer additions; 9. `the session log`.

`.venv/bin/python -m pytest tests/` twice, only at closure. Repeated
deterministic runs are not independent experiments.

**Delivered**: this preregistration commit, the data and coverage manifest, the
full `A(H)` table and the H\* artifact, the checkpoint hashes, the
chronological actual-trading log, the paired frozen probe dataset, per-session
AUCs with `DELTA_AUC` and the uncertainty summary, the matched-participation
comparison, reward counts, holding durations and the cost breakdown, the tests
with their exact commands and outcomes, the commits and the clean-tree status,
and a `the session log` block whose engineering and experimental conclusions are
stated apart.

If the calibration rule fails, the wave closes with that bounded result.
Nothing here expands into another parameter search, another instrument or
another date window.
