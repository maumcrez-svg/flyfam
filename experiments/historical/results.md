# The historical run — results

Run **`hist-003`**, started 2026-09-11T12:35:33Z, finished in **49.4 minutes**.
Pre-registered in `PROTOCOL.md` + `config.json` at commit `7b21c8e`, which
contains those two files alone and precedes every run reported here.

**No profitability is claimed anywhere in this document, and net PnL is not a
gate metric in either direction.** What is claimed, and shown, is that real
exchange minute bars travelled the whole chain — sensory encoding, eight
neural presentations, one decoded action, a paper execution, a settled
outcome, one normalised learning event — and that the frozen evaluation froze.

---

## 0. Runs, including the ones that are not results

| run | what it was | kept |
|---|---|---|
| `hist-001` | **pre-flight smoke test** on a *shortened* config (2 WARMUP + 1 LEARNING + 1 FROZEN session) to measure wall time per partition before committing to the full window. Not the registered experiment. It exposed two defects — the account was shared across partitions inside a branch, and exposure accumulated across them — both fixed before `hist-003`. | yes, with `WHAT_THIS_IS.txt` |
| `hist-002` | the registered config, **abandoned after ~10 minutes on purpose**. Building the observer showed that the `DECISION` event carried the action and the valence but **not** the encoded sensory channels and not the per-replicate measurement, so the observer could not have shown what amendment §7 requires without inventing it. The fix was additive and touched only what is written to the log; no decision, seed, weight, price or threshold changed. Per addendum 11 the retry took a new run id. | yes, with `WHAT_THIS_IS.txt` and its partial log |
| **`hist-003`** | **the registered experiment.** `config.json` unchanged, all three partitions, both branches. | yes |

All three live under gitignored `experiments/historical/runs/`. Nothing was
discarded for having started before the protocol commit, because nothing did.

## 1. Data, as the importer saw it

`HISTORICAL_MARKET`, the two authorised Kibot samples, verified by sha256
against `config.json` at load — a mismatch refuses the run rather than
substituting a dataset.

| | IBM | OIH |
|---|--:|--:|
| rows parsed | 23,777 | 20,373 |
| sessions in file | 61 | 61 |
| first bar (ET) | 2026-06-15 09:30 | 2026-06-15 09:30 |
| last bar (ET) | 2026-09-10 15:59 | 2026-09-10 15:59 |
| time format seen | `HH:MM` | `HH:MM` |
| rows rejected as malformed | 0 | 0 |
| extended-hours rows excluded | 0 | 0 |
| duplicate timestamps | 0 | 0 |
| blank lines | 0 | 0 |
| exponent-form prices | 0 | 0 |

Validated and would have been refused: field count, `MM/DD/YYYY` dates,
`HH:MM`/`HH:MM:SS` times on a minute boundary, finite and strictly positive
prices, non-negative volume, `high ≥ max(open, close) ≥ min(open, close) ≥
low`, strictly increasing timestamps, no duplicates, regular-session
membership. **Nothing in either file failed any of them**; the rejection paths
are exercised by the committed fixtures instead.

Coverage in the window 2026-08-03 → 2026-09-04 (25 sessions, 390 minutes each):

| | IBM | OIH |
|---|--:|--:|
| bars | 9,738 | 7,928 |
| missing minutes | 12 (0.12 %) | 1,822 (18.7 %) |

## 2. What the market statuses were, before a brain saw anything

Per instrument, over every round minute of each partition. These are **market**
statuses and none of them is a neural result.

| partition | rounds | instrument | `OK` | `WARMUP` | `DATA_GAP` | `STALE_DATA` |
|---|--:|---|--:|--:|--:|--:|
| WARMUP | 3,898 | IBM | 3,697 | 200 | 1 | 0 |
| WARMUP | | OIH | 2,909 | 184 | 797 | 8 |
| LEARNING | 3,900 | IBM | 3,695 | 200 | 5 | 0 |
| LEARNING | | OIH | 2,991 | 183 | 726 | 0 |
| FROZEN | 1,949 | IBM | 1,846 | 100 | 3 | 0 |
| FROZEN | | OIH | 1,558 | 95 | 296 | 0 |

`WARMUP` here is the first 20 market minutes of each session, where no lookback
may cross the session open — 20 × 10 = 200 for IBM's ten complete LEARNING
sessions, fewer for OIH because some of those minutes are already `DATA_GAP`.
The eight `STALE_DATA` minutes are OIH in the warm-up window, after a gap
longer than the declared 5-minute tolerance.

**The `WARMUP` partition ran features only.** 3,898 rounds, 0.02 s, no brain
was started, no `DECISION` event exists, and ten `WARMUP` events record the
per-session status counts.

## 3. Status and action frequencies, three denominators, never pooled

`docs/DECODER.md` §9: the per-candidate rate, the per-round rate after
selection, and what survived inventory and execution are three different
numbers with three different denominators.

### LEARNING (learned branch, 3,900 rounds)

**Per candidate evaluation** — one batch of k = 8 presentations, n = 6,591:

| `VALID` | `NO_RESPONSE` | `INVALID_STATE` | → `BUY` | `SELL` | `WAIT` |
|--:|--:|--:|--:|--:|--:|
| 6,504 | 87 | **0** | 62 | 5,471 | 971 |

**Per decision round** — after selection among the round's candidates,
n = 3,900:

| `VALID` | `NO_RESPONSE` | no usable candidate | → `BUY` | `SELL` | `WAIT` |
|--:|--:|--:|--:|--:|--:|
| 3,686 | 3 | 211 | 60 | 2,735 | 891 |

**After inventory and execution constraints:**

| outcome | n |
|---|--:|
| `BUY` executed | 37 |
| `POLICY_REJECT` / `SESSION_HORIZON` | 1 |
| `NEURAL_SELL` close | 34 |
| `POLICY_CLOSE` (horizon) close | 3 |
| `SESSION_CLOSE_FILL` | 0 |
| `DELAYED_FILL` | 5 |
| `SELL` decoded with nothing to sell (no order) | 2,700 |
| `WAIT` decoded (no order) | 855 |
| `WAIT`/`BUY`/`NO_RESPONSE` decoded while already holding | 35 / 21 / 3 |
| `ROUND_ABORTED` | 0 |

Per instrument, per candidate evaluation:

| | `VALID` | `NO_RESPONSE` | `BUY` | `SELL` | `WAIT` |
|---|--:|--:|--:|--:|--:|
| IBM | 3,589 | 46 | 31 | 3,016 | 542 |
| OIH | 2,915 | 41 | 31 | 2,455 | 429 |

Silent **presentations** inside the batches: **12,537 / 52,728** (23.8 %, unit:
presentation). A batch is `NO_RESPONSE` only when all eight are, which is why
87 of 6,591 batches are silent while a quarter of the individual presentations
were. Clipping: `tanh` bounds the encoder input and nothing reached the bound;
`INVALID_STATE` fired **zero** times in either branch, so the Kenyon
recruitment stayed inside the declared operating range throughout.

### FROZEN, learned branch (1,949 rounds)

Per candidate evaluation, n = 3,401: `VALID` 3,346, `NO_RESPONSE` 55,
`INVALID_STATE` 0 → `BUY` 3, `SELL` 2,936, `WAIT` 407.
Per round, n = 1,949: `VALID` 1,842, `NO_RESPONSE` 1, no usable candidate 106
→ `BUY` 3, `SELL` 1,457, `WAIT` 382.
After execution: `BUY` 3, `NEURAL_SELL` 3, `SETTLED_FROZEN` 3, no delayed or
session-close fills. Silent presentations 6,617 / 27,208.

Per instrument: IBM `VALID` 1,813 / `NO_RESPONSE` 31, actions SELL 1,593 /
WAIT 219 / BUY 1; OIH `VALID` 1,533 / `NO_RESPONSE` 24, actions SELL 1,343 /
WAIT 188 / BUY 2.

## 4. Checkpoints

| boundary | branch | state digest |
|---|---|---|
| clean reference, pre-registered | — | `ba95b60503d658e989b649ecd3994264791fbead92f0bdacfd555e5d86ab61f5` |
| WARMUP start and end | learned | `ba95b605…` (unchanged — no brain ran) |
| LEARNING start | learned | `ba95b605…` |
| **LEARNING end** | learned | **`dcb0f822c1e1d293f890a4588ac3057bad1ea6ec2b0d486c70e720b859bdd083`** |
| FROZEN start | learned | `dcb0f822…` |
| **FROZEN end** | learned | **`dcb0f822…` — identical** |
| FROZEN start | reference | `ba95b605…` |
| **FROZEN end** | reference | **`ba95b605…` — identical** |

The run began from the clean reference checkpoint, whose digest was recorded in
`config.json` **before** the run and re-derived and compared at start-up; a
mismatch refuses to run.

**Mid-run restart**, declared in `run.py` and not chosen after the fact: after
the third settled episode, at 2026-08-17 minute 43, the in-memory gains were
zeroed and the process state rebuilt from the checkpoint and the log.
`gains_restored_exactly = true`, recovery action `nothing to do` (nothing was
in flight), last settled episode 35,000,000, outcomes and learning both
recorded for 22000000 / 32000001 / 35000000.

## 5. Accounting, reconciled three ways

Fee 5 bps and slippage 5 bps are charged **per execution** — on the entry and
again on the exit — so a completed round trip costs **20 bps**. Neither is
applied twice to one execution.

| branch / partition | trades | W/L | gross at reference prices | − slippage | − fees | = net | residual |
|---|--:|--:|--:|--:|--:|--:|--:|
| learned / LEARNING | 37 | 2 / 35 | **+0.040102** | 36.981529 | 36.981529 | **−73.922956** | 0.0 |
| learned / FROZEN | 3 | 0 / 3 | **−0.810129** | 2.998096 | 2.998096 | **−6.806321** | 8.9 × 10⁻¹⁶ |
| reference / FROZEN | 242 | 13 / 229 | **+17.648011** | 241.887885 | 241.887880 | **−466.127753** | −2.3 × 10⁻¹³ |

Each partition opens its own account at 10,000.00; nothing crosses a partition
because nothing crosses a session. Final cash: LEARNING 9,926.08, FROZEN
learned 9,993.19, FROZEN reference 9,533.87, each equal to its initial cash
plus its realised PnL (`Account.check()` asserts this on every close).

**The gross at reference prices is approximately zero in all three cases and
the costs are the whole of the result.** Over 37 round trips the learned brain
moved +0.04 currency units before costs and paid 73.96 in them. That is a
statement about a 20 bps round-trip cost against one-minute moves, not about
the brain.

## 6. Did market context actually pass through the chain?

All nine pre-registered pass conditions, plus two log invariants, **PASS**
(`pass_conditions.json`, produced by `verify.py` from the log alone).

| | condition | evidence |
|---|---|---|
| P1 | an `OK` observation per instrument, encoded inside the declared budget | IBM episode 22000000, OIH 21000001; total ORN drive exactly 12,000.0 Hz in both, the declared budget |
| P2 | the stimuli vary with the market | 2,183 distinct normalised feature vectors for IBM, 1,506 for OIH; 595 and 541 distinct Kenyon active fractions |
| P3 | a `VALID` decision on a `HISTORICAL_MARKET` observation | **3,685** of them; first is episode 21000001 at market time 1786974660 (2026-08-17 09:51 ET); BUY 59 / SELL 2,735 / WAIT 891 |
| P4 | an `EXECUTION` carrying that decision's episode id | 37 execution events, **37 of 37** linked to a `VALID` decision; first 22000000 |
| P5 | an `OUTCOME` settling it, with a net PnL and an `ACCOUNT` field | 37 outcomes, **37 of 37** carry `account`; first is 22000000, net −5.77741082 |
| P6 | an accepted `LEARNING` event that moved synapses, and a digest that moved | 37 learning events, **37 accepted**, **103,782 synapses depressed** in total; `ba95b605…` → `dcb0f822…` |
| P7 | the whole chain replayable for one episode from the log alone | episode 22000000 appears in a `ROUND` event and in `DECISION`, `EXECUTION`, `OUTCOME`, `LEARNING`, `CHECKPOINT` |
| P8 | frozen means frozen | learned FROZEN `dcb0f822…` → `dcb0f822…`; reference `ba95b605…` → `ba95b605…`; **zero** `LEARNING` events in either frozen branch; 245 outcomes settled as `SETTLED_FROZEN` |
| P9 | accounting residual below 1e-6 | 0.0, 8.9e-16, −2.3e-13 |
| — | `DECISION` < `EXECUTION` < `OUTCOME` for every settled episode, both branches | pass |
| — | market time non-decreasing within each event kind, both branches | pass |

One worked example, episode **22000000**, IBM, 2026-08-17 09:52 ET, read end to
end from the log:

```
observation  bar close 231.59, status OK, cutoff = bar_end = 13:52:00Z
features     r1 +0.589  r5 −0.771  r20 +0.834  rv20 +0.983  relvol −0.377
stimulus     DA2 17.3  DL1 3.9  DM2 3.9  DM3 3.9  DM6 38.7  V 3.9
             VL1 31.2  VL2a 24.8  VM4 33.4  VM5d 3.9  Hz/ORN
             703 ORNs, 12,000.0 Hz total — the declared budget
readout      8 presentations, 0 silent, 254 Kenyon cells (10.58 %),
             approach 17.1875 Hz (16 MBONs), avoid 15.3017 Hz (29 MBONs)
decision     V = +2.730166 Hz  >  θ = +0.911719 Hz   →   BUY   (VALID)
execution    fill at the open of minute 22, 231.496 → 231.611748 after
             5 bps slippage, 4.3175702815 units, fee 0.500, delay 1 minute
outcome      POLICY_CLOSE 8 market minutes later at 230.62 → 230.50469,
             gross at reference −3.78219157, slippage 0.99760915,
             fees 0.99761010, net −5.77741082
learning     valence −1 (PPL1 side) × 0.577741, one mean_of_deltas update
             over k = 8, 2,461 synapses depressed
             (per replicate 457 / 667 / 2105 / 373 / 1689 / 1515 / 1757 / 1604)
```

That is market context reaching the weights. It is not evidence that the
weights should have moved that way.

### What the learning did to behaviour

This is the wave's most consequential observation and it is reported, not
explained away. With 35 of the first 37 outcomes negative, 37 punishment
events depressed 103,782 synapses on the PPL1-innervated (approach) side. The
decoder's approach term fell, `V` fell with it, and the action mix collapsed
towards `SELL`:

| | per-candidate `BUY` | `SELL` | `WAIT` |
|---|--:|--:|--:|
| LEARNING, all 3,900 rounds | 62 / 6,591 | 5,471 | 971 |
| FROZEN, learned brain | 3 / 3,401 | 2,936 | 407 |
| FROZEN, untrained reference | 887 / 2,113 | 253 | 933 |

A brain that says `SELL` with no inventory produces no order, so the learned
branch made **3 trades in five sessions** against the reference's 242. Whether
"trade almost never after losing 35 times" is a good policy is not established
by anything here; what is established is that the learning signal reached the
decoder and changed what it does, in the direction the depression-only
plasticity rule predicts.

## 7. Compute

| | rounds | wall | presentations |
|---|--:|--:|--:|
| WARMUP (features only) | 3,898 | 0.02 s | 0 |
| LEARNING | 3,900 | 1,598.5 s (26.6 min) | 52,728 |
| FROZEN, learned | 1,949 | 823.4 s (13.7 min) | 27,208 |
| FROZEN, reference | 1,949 | 538.9 s (9.0 min) | 16,904 |
| **total** | | **49.4 min** | **96,840** |

Estimated before the run: 47 minutes against a 90-minute ceiling, so the
reduction rule of PROTOCOL §10 did not fire and `k` was never touched. Peak RSS
**740.8 MiB**, one process, no parallelism. AMD Ryzen 5 7600X, 12 logical
cores, 62 GB, Python 3.13.9, NumPy 2.4.2.

## 8. Artifacts

| what | where |
|---|---|
| learned branch event log | `experiments/historical/runs/hist-003/learned/events.jsonl` — 20,739,140 bytes, sha256 `875d3e9db485221cefcce1259ae9c528eafbc12f3a5b3b98c7d848c37d06fc97`, 11,556 events |
| learned branch checkpoint | `…/learned/brain.npz` — sha256 `032a8a2345466fe131cbfa354b98f1e290fcaaef8d4158859f1e67b525cf4a5b` |
| reference branch event log | `experiments/historical/runs/hist-003/reference/events.jsonl` — 7,020,802 bytes, sha256 `ee901ca67093088cdadc4c5918825684f24f30c8da70d58703cd4637ea05bd50`, 4,426 events |
| reference branch checkpoint | `…/reference/brain.npz` — sha256 `a10cfad8f899d6a6c9205dab200b88adcfadab5cbcaa6e41e1dd7206b28af6f7` |
| committed summary | `summary.json` |
| committed pass conditions | `pass_conditions.json` |

The event logs total 27.8 MB and are **not committed** — `runs/` is gitignored,
like the market data and the connectome. Their paths and hashes are above, and
everything the report quotes from them is in `summary.json`,
`pass_conditions.json` and `comparison.json`, which are committed.

Event kinds written, learned branch: `ROUND` 5,849 · `DECISION` 5,532 ·
`EXECUTION` 40 · `OUTCOME` 40 · `LEARNING` 37 · `CHECKPOINT` 41 · `PARTITION` 6
· `WARMUP` 10 · `RECOVERY` 1. Reference branch: `ROUND` 1,949 · `DECISION`
1,748 · `EXECUTION` 242 · `OUTCOME` 242 · `CHECKPOINT` 243 · `PARTITION` 2 —
and, as P8 requires, no `LEARNING` at all.

## 9. One thing the log does that looks wrong and is not

At a **horizon settlement**, the `OUTCOME` event's market timestamp is 60 s
*before* the `DECISION` event written immediately above it. That happens 3
times in the learned branch and 99 in the reference branch, always exactly
60 s, always between a `DECISION` and an `OUTCOME`, and always at a
`POLICY_CLOSE`.

The reason: a horizon exit fills at the **open** of minute *m*, while the round
at minute *m* decides at its `bar_end`, which is 60 s later. The exit minute was
fixed by the horizon clock when the position was opened and uses nothing from
that round; the price used is that bar's open, not its close. Within each event
kind market time is strictly non-decreasing, and every episode's own order is
`DECISION` < `EXECUTION` < `OUTCOME`, so a replay cursor can never show an
outcome before the decision that caused it.

---

## 10. Learned versus untrained reference — the frozen window

Amendment §6. During `FROZEN` a second branch ran the **same observations, the
same baseline artifact, the same paper policy and the same `comparison_v1`
seeds**, from the clean reference checkpoint, with learning and forgetting off.
Separate account, separate journal, separate event log, separate episode-id
space; neither branch can see the other.

### The pairing actually held

`comparison_v1` keys a replicate seed to (observation id, instrument stable id,
replicate index) and **not** to the learned-state digest, so that a difference
between the branches is a difference in weights and not in the stimulus
realisation. Measured from the two logs:

| | |
|---|--:|
| (observation, instrument) pairs where **both** branches decided | **1,001** |
| of which drew an **identical** seed | **1,001** |
| drew a differing seed | **0** |

The branches also decided on 842 and 747 observations the other did not,
because a branch holding a position scans only the instrument it holds — and
the two branches held very different amounts of the time. The 1,001 shared
pairs are where the comparison is paired, and every one of them matched.

### The comparison, both branches, no winner chosen

| | learned | untrained reference |
|---|--:|--:|
| start digest | `dcb0f822…` | `ba95b605…` |
| end digest | `dcb0f822…` (unchanged) | `ba95b605…` (unchanged) |
| rounds | 1,949 | 1,949 |
| candidate evaluations | 3,401 | 2,113 |
| presentations | 27,208 | 16,904 |
| silent presentations | 6,617 (24.3 %) | 4,223 (25.0 %) |
| **per round** `VALID` | 1,842 | 1,698 |
| `NO_RESPONSE` | 1 | 32 |
| `POLICY_REJECT` | 0 | 18 (all `SESSION_HORIZON`) |
| `INVALID_STATE` | 0 | 0 |
| **per round** `BUY` | 3 | 819 |
| `SELL` | 1,457 | 167 |
| `WAIT` | 382 | 730 |
| completed trades | **3** | **242** |
| exposure, market minutes held | 4 | 1,315 |
| closed by `NEURAL_SELL` | 3 | 144 |
| closed by `POLICY_CLOSE` | 0 | 98 |
| `DELAYED_FILL` | 0 | 26 |
| `SESSION_CLOSE_FILL` | 0 | 0 |
| settled `SETTLED_FROZEN` | 3 | 242 |
| `LEARNING` events | **0** | **0** |
| gross at reference prices | −0.810129 | +17.648011 |
| − slippage | 2.998096 | 241.887885 |
| − fees | 2.998096 | 241.887880 |
| **= net realised** | **−6.806321** | **−466.127753** |
| residual | 8.9 × 10⁻¹⁶ | −2.3 × 10⁻¹³ |
| wins / losses | 0 / 3 | 13 / 229 |
| final cash | 9,993.19 | 9,533.87 |

By instrument:

| | learned IBM | learned OIH | reference IBM | reference OIH |
|---|--:|--:|--:|--:|
| `VALID` decisions | 1,060 | 782 | 1,026 | 672 |
| `NO_RESPONSE` | 1 | 0 | 20 | 12 |
| `BUY` | 1 | 2 | 492 | 327 |
| `SELL` | 851 | 606 | 99 | 68 |
| `WAIT` | 208 | 174 | 446 | 284 |
| trades | 1 | 2 | 138 | 104 |
| net | −1.717800 | −5.088521 | −272.392975 | −193.734778 |

### What this does and does not say

The two branches differ in exactly one thing: the learned weights. They saw
the same minutes, drew the same Poisson streams, used the same θ, the same
notional and the same costs. The learned brain decided `SELL` in 1,457 of
1,842 valid rounds and therefore almost never entered; the untrained one
decided `BUY` in 819 and entered 242 times.

The untrained branch's loss is a cost statement: 242 round trips at 20 bps
against one-minute moves gives +17.65 of gross at reference prices against
483.78 of costs. The learned branch avoided almost all of that by trading
almost never.

**That is not evidence of skill.** It is a single five-session window; the
learned brain's behaviour came from 35 losses in 37 episodes on a horizon and
a cost structure where losses were near-certain; and "trade less when trading
loses money" is the only behaviour depression-only plasticity could have
produced here — it has no mechanism for learning *when* to trade, only for
suppressing what preceded punishment. **The untrained comparison is not a full
test against chance, no profitability requirement is part of the engineering
gate, and no seed was chosen after the fact.**

---

## 11. The local observer

```
.venv/bin/python observer/serve.py          #  http://localhost:8765/
```

`observer/index.html` is vanilla HTML, CSS and JavaScript — no framework, no
build step, no npm, no external script or stylesheet. `observer/serve.py` is
stdlib `http.server` bound to **127.0.0.1** only; it has no write path, no
`POST`, and no public ingress. It reads the run's own `events.jsonl`, parses
each line, and hands the events over unchanged; a partition selection is a
**line range** found from the run's own `PARTITION` boundary events, so
slicing cannot alter content.

Playback is an **event-index cursor**. Play, pause, speed and the scrub bar
move that index and nothing else: no brain time, no seed, no choice, no
weight and no logged event is touched, and stepping back to an index
reproduces exactly the same display. The page counts statuses; it never sums
money — every currency figure it shows is a field of the last `OUTCOME` event
the cursor has reached.

It shows, all from the log: the `HISTORICAL REPLAY · PAPER` label and the
"simulated fills" note; market time in New York and UTC and brain time in
cycles and seconds; partition and branch; the instrument being presented with
its observation status and bar close; the five normalised features and the
per-glomerulus ORN drive with the total against the declared budget; the
measured population rates with their MBON counts, the Kenyon recruitment, the
peak rate, k, the silent-replicate count and the eight per-replicate decodes;
the action with `V` against ±θ on a gauge; the open paper position with its
fill, quantity, fee and fill-timing flag; the realised outcome with its
three-term reconciliation and the reinforcement event; cash, equity,
cumulative realised PnL, fees and slippage; and running counts of completed
trades, `WAIT`, `NO_RESPONSE` and every other status reached so far.

It does **not** show per-neuron spikes — only population rates were recorded,
and the page says so on the panel rather than inventing them.

### Verified in a headless browser

Stepped to episode **22000000** in `hist-003 / learned / LEARNING` and compared
every displayed field against the log line. Page → log:

```
08/17/2026, 09:52 ET / 2026-08-17 13:52Z   ← market_ts 1786974720
brain cycle 22, brain time 11.0 s          ← brain_cycle 22, brain_ms 11000.0
LEARNING · learned                         ← partition, branch
IBM, OK, close 231.59, 2 candidates,       ← symbol, observation_status,
  HISTORICAL_MARKET                            observation.close, n_candidates
r1 +0.589 r5 −0.771 r20 +0.834             ← observation.normalized
  rv20 +0.983 relvol −0.377
DA2 17.3 / DL1 3.9 / DM2 3.9 / DM3 3.9     ← stimulus.rates_hz
  DM6 38.7 / V 3.9 / VL1 31.2 / VL2a 24.8
  VM4 33.4 / VM5d 3.9 Hz
12,000 Hz total, 703 ORNs                  ← stimulus.total_drive_hz, n_orns
approach 17.188 Hz (16 MBONs)              ← readout.rates_hz.approach 17.1875
avoid    15.302 Hz (29 MBONs)              ← readout.rates_hz.avoid  15.301724
254 Kenyon cells (10.58 %), peak 150.0 Hz  ← kc_active 254, kc_fraction 0.105807
k 8, silent 0 / 8                          ← k 8, silent_replicates 0
BUY, V +2.730 Hz, ±0.9117 Hz, VALID        ← 2.730166, 0.911719, VALID
```

At that index the outcome panel read *"no outcome has been reached yet"* and
the account fields read `–`; at the next index the position showed
`231.6117 @ 09:52 ET`, qty `4.3176`, fee `0.5000`, *"next minute, as asked"*
(log: `fill_price 231.611748`, `quantity 4.3175702815`, `fee 0.5`,
`delay_minutes 1`, `flag ""`). At index 43, one before the outcome, the outcome
panel was still hidden and cash still `–`. At index 44 it showed
`POLICY_CLOSE`, `8 market minutes`, gross `−3.7822`, slippage `0.9976`, fees
`0.9976`, net `−5.7774`, cash `9,994.22`, equity `9,994.22`, cumulative PnL
`−5.7774`, trades `1` — against log `gross_reference_pnl −3.78219157`,
`slippage 0.99760915`, `fees 0.9976101`, `net_pnl −5.77741082`,
`account.cash 9994.22258918`. Learning still read *"not reached yet"*. At index
46 it read `PPL1 (−1) ×0.578`, `2,461` synapses, `accepted · mean_of_deltas
k=8` — log `valence −1`, `amount 0.577741`, `synapses_depressed 2461`,
`normalisation mean_of_deltas`, `k 8`.

On the reference branch's first frozen outcome the page read settlement
`SETTLED_FROZEN`, dopamine *"none — learning is off"*, `0` synapses, learning
*"none written (frozen)"*, net `−1.6990`, cash `9,998.30` — log `settlement
SETTLED_FROZEN`, `net_pnl −1.69897015`, `account.cash 9998.30102985`, and no
`LEARNING` event anywhere in that log.

Playing for 1.2 s at 20 events/s advanced the cursor by 24 and left the loaded
event array identical; scrubbing back to index 46 reproduced the same values
character for character. **Zero console errors or warnings.**
