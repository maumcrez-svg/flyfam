# PROTOCOL — the historical run

**Pre-registered.** This file and `config.json` are committed **alone**, before
any historical run exists and before the historical execution code is written.
Nothing in this directory has been executed against `HISTORICAL_MARKET` data at
the moment of this commit. Any run started before this commit is discarded and
said so, exactly as `experiments/conditioning/PROTOCOL.md` (`b9655ea`) and
`experiments/k8_readout/PROTOCOL.md` (`4b8e082`) were handled.

Canonical amendment: `docs/SPEC.md` §D5/D6 (owner, 2026-09-11) and the eleven
Fable addenda that close it. Where the two speak, this file quotes them; where
a choice was left open, this file makes it here and not later.

---

## 0. What is frozen, and therefore not decided by this run

k = 8 · gain 0.10 · the 20 ms / 100-step presentation window · the encoder's
channel rule, coding, `DRIVE_BUDGET_HZ = 12000`, `CARRIER = 0.10` and declared
input bounds · the MBON membership (29 avoid, 16 approach) · the decoder
formula `V = mean(approach) − mean(avoid) − BASELINE` and its sign · the
dimensionless margin coefficient `THETA_SD = 1.0` · the stored k = 8 baseline
artifact `experiments/k8_readout/baseline_k8.json`, loaded at full precision ·
one normalised learning update per settled outcome · the paper execution
defaults (notional, fees, slippage, delay, horizon, long-only, one open
position) · `upstream/` and `tests/upstream_audit/`.

**None of these is recalibrated, retuned or widened using anything measured in
this run.** If the historical inputs produce silence, `INVALID_STATE`, or no
completed learning episodes, that is the result and it is reported as one. No
heuristic trader is inserted and no threshold is moved.

---

## 1. Data

`HISTORICAL_MARKET`, the two Kibot free one-minute samples authorised by the
amendment, recorded with URLs, retrieval times, sha256, byte counts and
per-day coverage in `data/MANIFEST.md` (commit `92b6261`, which precedes this
one).

| | file | sha256 (first 16) | rows | adjustment |
|---|---|---|---|---|
| IBM | `IBM_1min_unadjusted.txt` | `b1ace385f069764c` | 23,777 | unadjusted |
| OIH | `OIH_1min_unadjusted.txt` | `12311994a9952544` | 20,373 | unadjusted |

Two real instruments. The loop's capacity for six is retained and unused: no
series is duplicated, renamed or resampled to manufacture a sixth.

The raw files stay under gitignored `data/market/`. No committed test reads
them. The importer is `flytrade/historical.py` (commit `b49cc5b`), which
precedes this one and has never seen a run.

Stable ids are assigned once, alphabetically, at universe registration:
**IBM = 0, OIH = 1**. They enter every seed and every episode id; a ticker's
spelling never does.

## 2. Clock and cadence

* **Bar timestamp = bar open.** A row stamped 09:30 covers 09:30:00 → 09:30:59.
* **`bar_end = bar_start + 60 s`** is the first instant that bar may be read.
* **Regular session only**: `09:30 ≤ bar_start < 16:00` America/New_York, 390
  minutes, one session per calendar date. Canonical storage is UTC.
* **One decision round per regular-session minute bar**, taken at that bar's
  `bar_end`, over the union of minutes at which *any* instrument reported a
  bar (Fable addendum 3). An instrument with no bar at that minute is a
  `DATA_GAP` candidate in that round; it does not remove the round.
* **Two clocks, both in every `DECISION` event**: market time (`cutoff_ts`,
  and its New York rendering) and brain time (`brain_cycle`, one decision
  cycle per round, `brain_ms = brain_cycle × 500 ms` from
  `flytrade/state.py`).
* **Decay acts per round, in brain time.** The eligibility trace decays once
  per round: every replicate is presented from the round's restored snapshot
  `S0`, so `MushroomBody.observe`'s 0.55 factor applies once per round and not
  once per presentation (`flytrade/readout.py` §1). The learned-weight
  recovery drift `MushroomBody.forget()` is **not** called in the loop, in any
  partition — exactly as in the Phase One and D4 demonstrations. That is
  "current experiment-clock semantics, preserved"; turning it on here would be
  a change to learning dynamics outside the frozen set.
* **Lookbacks never cross a session.** The first 20 market minutes of every
  session are `WARMUP` for that reason, and no overnight return enters a
  one-minute feature.

## 3. Partitions

Inclusive, as the owner fixed them. No date is shifted, reshuffled or replaced,
and nothing crosses a boundary.

| partition | first | last | sessions | neural simulation | learning | forgetting |
|---|---|---|---|---:|---|---|
| `WARMUP` | 2026-08-03 | 2026-08-14 | 10 | **off** | off | off |
| `LEARNING` | 2026-08-17 | 2026-08-28 | 10 | on | **on** | off |
| `FROZEN` | 2026-08-31 | 2026-09-04 | 5 | on | **off** | off |

* `WARMUP` populates the causal feature history only. **No brain is run, no
  `DECISION` event is written**; one `WARMUP` status is recorded per
  observation (Fable addendum 3).
* `LEARNING` runs the complete sequential loop: observation → encoder → eight
  presentations → one aggregate → one decision → at most one execution episode
  → outcome → one normalised learning event.
* `FROZEN` evaluates the learned checkpoint on later observations. **Learning
  and forgetting are off; transient simulation stays on.** Eligibility traces
  are still laid down and are never applied. `OUTCOME` events are emitted and
  settled for accounting, the settlement counter records `SETTLED_FROZEN`, and
  **no `LEARNING` event is written**. The end-of-partition checkpoint hash of
  the learned branch **must equal its start hash**; a mismatch fails the run.

## 4. The starting brain

A **clean reference checkpoint**, not a checkpoint trained on the odour
demonstrations and not one carried over from the k = 8 demo:

```
graph sha256      8feb08a0d2a80cbcf69328f9707d5dd748d73d2e12246526d96e48d995f843b9
plastic synapses  44042  (KC→MBON)
gain vector       1.0 everywhere — no learning has been applied
state digest      ba95b60503d658e989b649ecd3994264791fbead92f0bdacfd555e5d86ab61f5
```

The digest is `flytrade.state.learned_state_digest(gain, pos, graph_sha256)`,
the same function the checkpoint and the seed schedule use. It is recorded
here, before the run, so that "the run started clean" is checkable rather than
claimed.

## 5. Seed schedules, both declared before running

**`LEARNING` — the D4 policy, unchanged.** Namespace
`flytrade-k8-round-1`; the replicate seed is

```
seed = sha256("flytrade-k8-round-1:<state digest>:<observation id>:<stable id>:<r>")[:8]
```

keyed to the **learned-state digest**, so a batch taken under different weights
is a different batch. This is exactly `flytrade/readout.py` §2 and is not
touched.

**`FROZEN` — `comparison_v1`, the paired schedule.**

```
seed = sha256("comparison_v1:<observation id>:<stable id>:<r>")[:8]
```

The state digest is **deliberately absent**. Amendment §6: "The comparison
random schedule must not change merely because the learned weights differ. A
seed derived from the weight digest would change the stimulus realization
between branches." Keyed to (observation id, instrument stable id, replicate)
and to nothing else, the learned branch and the untrained reference branch draw
**the same Poisson stream for the same observation**, so a difference between
them is a difference in weights and not in noise.

`comparison_v1` is a new, versioned namespace. The D4 schedule and its
artifacts are preserved untouched as historical regression evidence, and the
k = 1 regression mode remains replicate index 0 of the D4 schedule.

Both branches of `FROZEN` use `comparison_v1`. The `replicate` index runs
0…7 exactly as in `LEARNING`.

## 6. Execution, in historical time

The v1 paper policy's numbers are **preserved exactly**; only the unit of
"delay" and "horizon" is made explicit.

| parameter | value | unit | historical interpretation |
|---|--:|---|---|
| `NOTIONAL` | 1000.00 | currency | fixed notional per position |
| `INITIAL_CASH` | 10000.00 | currency | one account per branch |
| exposure | 1 | position | long only; `SELL` reduces, never shorts |
| `FEE_BPS` | 5.0 | bps of traded value | **per execution** — charged on the entry and again on the exit |
| `SLIPPAGE_BPS` | 5.0 | bps | **per execution**, always against the trader |
| `DELAY_BARS` → delay | 1 | **market minute** | the fill may not be on the decision's own bar |
| `HORIZON_BARS` → horizon | 8 | **market minutes** | measured from the fill's `bar_start` |
| `REINFORCE_FULL_SCALE` | 0.01 | return on notional | net return mapping to a full-strength dopamine event |
| `REINFORCE_CAP` | 1.0 | — | hard cap |

**A completed round trip therefore costs 20 bps** — 5 fee + 5 slippage on the
entry, 5 + 5 on the exit. Neither parameter is applied twice to one execution.
This is stated once, here, and the run reconciles it:

```
gross_reference_pnl − fees − modelled slippage = net realised PnL
```

with `gross_reference_pnl` computed at the unslipped bar prices. The residual
must be zero to 1e-6.

**The five clock rules** (Fable addendum 4):

1. The decision is taken at `bar_end(t)`. No order uses the decision bar's own
   high, low or close, and no order uses any later bar's prices as information.
2. **Fill** = the *open* of the first available regular-session bar with
   `bar_start ≥ bar_end(t)`, same session. If that is not the next calendar
   minute, the fill carries `DELAYED_FILL` and the elapsed market minutes.
3. **Settlement** = the *open* of the first available bar with
   `bar_start ≥ fill.bar_start + 8 market minutes`, flagged `DELAYED_FILL`
   likewise when delayed.
4. **Entry eligibility** is a clock rule, checked before any price is read:
   `bar_end(t) + 1 minute + 8 minutes ≤ 16:00` on the same session, i.e.
   `bar_start(t) ≤ 15:50`. A decision refused by it is recorded with
   `readout_status = POLICY_REJECT` and `reason = SESSION_HORIZON`. This uses
   declared session boundaries only — never advance knowledge of prices or of
   where the gaps are.
5. A position still open at the session's **last available bar** of its own
   instrument — reachable only through gaps — is closed at that bar's *close*
   with `SESSION_CLOSE_FILL`, `close_reason = POLICY_CLOSE`, and is counted
   separately. Nothing crosses a day, so nothing crosses a partition.

One sequencing guard follows from "one open position" and is declared here
rather than discovered later: **an entry may not fill before the previous exit
filled.** A delayed exit delays the next entry, and that delay is flagged like
any other.

A due fill or settlement with no valid price is never invented: it is a
recorded `Rejection` with its own reason (`BAD_PRICE`, `NO_FUTURE_BAR`), and no
episode is silently dropped.

## 7. The status taxonomy, in full

Four market statuses, produced by `flytrade/historical.py`, none of them a
neural result:

| status | meaning |
|---|---|
| `OK` | encodable |
| `WARMUP` | causal history not yet available: fewer than 20 elapsed market minutes in this session, or fewer than 60 usable feature rows behind it. Also the status of every `WARMUP`-partition observation, which is never presented to the brain. |
| `DATA_GAP` | the vendor reported no bar at this market minute for this instrument |
| `STALE_DATA` | a lookback's backing bar is more than 5 market minutes older than the instant it points at |

Four readout statuses, produced by `flytrade/decoder.py`, unchanged:

| status | meaning |
|---|---|
| `VALID` | a real readout, decoded to `BUY`, `SELL` or `WAIT` |
| `NO_RESPONSE` | **all eight** replicates silent over the 45 decoder MBONs |
| `INVALID_STATE` | **any** replicate saturated or over-recruited |
| `POLICY_REJECT` | the decoder produced a valid action and the execution policy refused it |

Plus `ROUND_ABORTED` (a replicate raised; no decision, nothing averaged), and
the execution-side labels `POLICY_CLOSE`, `NEURAL_SELL`, `DELAYED_FILL`,
`SESSION_CLOSE_FILL` and the five `RejectReason` values.

**These eleven-plus counters are never pooled.** Every report gives, per
partition and per instrument, three separate frequency tables with three
different denominators (`docs/DECODER.md` §9):

1. **per candidate evaluation** — one batch of eight presentations;
2. **per decision round** — after selection among the round's candidates;
3. **after inventory and execution constraints** — what became an order.

Silent *presentations* inside batches are counted separately again, with
"presentation" as the unit.

## 8. Pass conditions for "market context passed through the chain"

Amendment §8: "Do not claim completion because the importer returns rows." The
run passes this gate only if **all** of the following hold, each reported with
the event ids or counts behind it. Failure of any one is reported as a failure,
not worked around.

| # | condition |
|---|---|
| P1 | ≥ 1 `OK` observation per instrument in `LEARNING`, encoded into a stimulus whose total ORN drive is inside the declared budget |
| P2 | the presented stimuli vary with the market: > 1 distinct normalised feature vector per instrument, and a non-constant Kenyon active fraction across the partition |
| P3 | ≥ 1 `DECISION` event with `readout_status = VALID` whose observation carries `dataset_label = HISTORICAL_MARKET` |
| P4 | ≥ 1 `EXECUTION` event carrying the same `episode_id` as such a decision |
| P5 | ≥ 1 `OUTCOME` event settling that episode, with a net PnL and an `ACCOUNT` field |
| P6 | ≥ 1 accepted `LEARNING` event in `LEARNING` with `synapses_depressed > 0`, and the end-of-`LEARNING` state digest **different** from the clean reference digest |
| P7 | for at least one episode, `Journal.replay_chain` returns `ROUND`, `DECISION`, `EXECUTION`, `OUTCOME` and `LEARNING` from the log alone |
| P8 | `FROZEN`, learned branch: end-of-partition checkpoint hash **equals** the start hash, and zero `LEARNING` events were written |
| P9 | the accounting residual `gross_reference − fees − slippage − net` is 0 to 1e-6 in every branch |

## 9. The comparison

During `FROZEN`, a second, independent branch runs the **same observations,
the same baseline, the same paper policy and the same `comparison_v1` seeds**
from the clean reference checkpoint, with learning and forgetting off. Separate
account, separate journal, separate event log, separate episode-id space; no
state is shared with the learned branch and neither can see the other.

Reported for both branches without choosing a winner: readout-status
distribution, action frequencies at all three denominators, completed trades,
exposure in market minutes, gross and net, and the same broken down by
instrument.

This is **not** a full test against chance and no trading skill is claimed from
one five-session window. **No profitability requirement is part of the
engineering gate**, and net PnL is not a gate metric in either direction.

## 10. Compute budget

Measured before the run, on this machine: **29.3 ms per 20 ms presentation**
(one process, no parallelism).

| partition | rounds | candidates/round (expected) | presentations | estimate |
|---|--:|--:|--:|--:|
| `WARMUP` | 3,898 | 0 (no neural) | 0 | ≈ 0 |
| `LEARNING` | 3,900 | ≈ 1.6 | ≈ 50,000 | **≈ 24 min** |
| `FROZEN`, learned | 1,949 | ≈ 1.5 | ≈ 23,400 | **≈ 11.5 min** |
| `FROZEN`, reference | 1,949 | ≈ 1.5 | ≈ 23,400 | **≈ 11.5 min** |
| | | | | **≈ 47 min** |

Under the 90-minute ceiling, so the reduction rule below does **not** fire. It
is written anyway, before the run, because writing it afterwards would not be
a rule:

> **Reduction rule.** If the pre-run estimate exceeds 90 minutes, `LEARNING`
> is run on its **last N sessions** only, N being the largest integer for
> which the total estimate falls under 90 minutes. The dropped sessions are
> named in the report. `WARMUP` and `FROZEN` are never shortened, dates are
> never shifted, and **k is never reduced.**

The experiment runs in the background while the observer is built.

## 11. Runs, retries and failures

Every invocation gets a run id `hist-NNN`, allocated in order and stamped into
every event, the summary and the checkpoint directory
(`experiments/historical/runs/<run_id>/`, gitignored). A retry after a software
correction gets a **new** run id; the failed run's directory and its
explanation are kept, and both appear in the results and in `the session log`.

A run is *discarded* — and said to be discarded — if it started before this
commit, if it read an adjusted or substituted dataset, or if the frozen-branch
checkpoint hash moved.

## 12. Deliverables

`results.md` (coverage, status tables, comparison, accounting reconciliation,
the nine pass conditions), `summary.json`, `comparison.json`, the event-log
paths with their sha256, the start and end checkpoint hashes of every branch,
`observer/` with its exact startup command, and the tests listed in amendment
§8 with their outcomes.
