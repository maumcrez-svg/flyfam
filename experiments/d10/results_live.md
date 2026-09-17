# D10 — the live Pons loop (d10-live-001)

**LIVE COLLECTION, PAPER EXECUTION.** Every fill below is simulated. No transaction was signed, broadcast or sent; the package that talks to the chain has a six-method read-only allowlist and no key material anywhere, and the endpoint and its key appear in no artifact. A signal is not a fill, a paper buy is not an on-chain transaction, and a live connection is not fresh data.

**This file is the live run and nothing else.** The replay run `d10-001` is reported separately in `experiments/d10/results.md`; no number is carried across, and the two are never pooled.

Reading rules, fixed in `PLAN.md` and `live.json` before the run:

* zero episodes, and zero admitted candidates in the hour, are admissible results and are reported as such;
* nothing — gain, thresholds, scales, admission, the limits — was touched to produce activity;
* an episode still `PENDING_CONFIRMATION` at the stop is reported as pending, never as settled;
* a position still open at the stop is retained open, never closed at the last mark;
* the four conclusions below are separate and are never merged.

## 1. Provenance, and what was registered before the run

| item | value |
|---|---|
| run | `d10-live-001`, branch `live` |
| mode / learning | LIVE_PAPER / LEARN |
| registration commit | `56fc96df05de` — `live.json` + `LIVE_PLAN.md`, committed alone and **before** this run existed |
| `live.json` sha256 | `92ef92b6e029…` |
| `config.json` sha256 | `d5ba4221a4b1…` (unchanged since the replay run) |
| started from | `d10-001/learning`'s final checkpoint, digest `999d32450a3b…` — verified before the first request |
| graph | `8feb08a0d2a8…` |
| venue / chain | PONS / 4663 (`eth_chainId` verified = 4663) |
| endpoint | `<rpc-endpoint>` — read by key name at runtime, never printed, logged or written |
| started / stopped (UTC) | 2026-09-12T06:40:41Z → 2026-09-12T07:40:43Z |
| wall clock | 60.0 min, peak RSS 646 MiB |
| python · numpy | 3.13.9 · 2.4.2 |

## 2. The run, and how it stopped

| item | value |
|---|---|
| stop reason | **TIME_LIMIT** — 3600s wall clock |
| declared stop conditions | 60 minutes wall clock, 3,000 requests, the stop file flag or SIGTERM, whichever comes first |
| ticks | 111 (expected before the run: 120) |
| cadence | 30 s |
| first / last cutoff | 1789195500 → 1789198830 |
| start backfill | blocks 60864686 → 60900330, 19,815 events, 490 requests, 253.3 s, complete: True |
| errors | 0 |
| reorgs seen | 0 |

Two different lags, both measured per tick and neither a substitute for the other. **Unscanned lag** is head − cursor once the tick has scanned: how much of the chain the collector has not read, normally zero because a tick scans to the head it just read. **Cutoff age** is how old the decision's own data is when the tick finishes, which is what a reader means by "how far behind is it".

| lag | n | min | median | mean | max |
|---|---|---|---|---|---|
| unscanned (blocks) | 111 | 0 | 0 | 0.0 | 0 |
| unscanned (seconds) | 111 | 0 | 0 | 0.0 | 0 |
| cutoff age (seconds) | 111 | 4 | 5 | 5.1 | 26 |

Head and cursor progression (every tick, first and last five shown; the whole series is in `summary.json`):

| tick | cutoff | head | cursor | unscanned | cutoff age (s) | events | attempts |
|---|---|---|---|---|---|---|---|
| 1 | 1789195500 | 60,902,846 | 60,902,846 | 0 | 26 | 2431 | 537 |
| 2 | 1789195560 | 60,903,437 | 60,903,437 | 0 | 8 | 407 | 548 |
| 3 | 1789195590 | 60,903,731 | 60,903,731 | 0 | 5 | 154 | 556 |
| 4 | 1789195620 | 60,904,025 | 60,904,025 | 0 | 5 | 199 | 564 |
| 5 | 1789195650 | 60,904,332 | 60,904,332 | 0 | 5 | 194 | 572 |
| … | | | | | | | |
| 107 | 1789198710 | 60,934,438 | 60,934,438 | 0 | 5 | 112 | 1446 |
| 108 | 1789198740 | 60,934,731 | 60,934,731 | 0 | 5 | 151 | 1457 |
| 109 | 1789198770 | 60,935,024 | 60,935,024 | 0 | 4 | 128 | 1468 |
| 110 | 1789198800 | 60,935,321 | 60,935,321 | 0 | 5 | 175 | 1479 |
| 111 | 1789198830 | 60,935,614 | 60,935,614 | 0 | 5 | 131 | 1490 |

## 3. What the hour actually held

| item | value |
|---|---|
| blocks scanned | 70,928 |
| raw logs | 44,021 |
| normalised events | 44,021 |
| `TokenLaunched` seen | **917** |
| tracked curves at the stop | 359 |
| `CurveCompleted` seen | 3 |
| orphaned by a reorg | 0 |

**Launch rate over this run: 461 `TokenLaunched` per hour** — 917 launches over the 70,928 blocks this run scanned, backfill included, which is 119.4 minutes of chain time at the measured 0.101 s interval. The v2 documentation says *"public launches are closed, so only whitelisted addresses can create a token for now"*; both things are true at once, and the rate is the measurement. Beside it, the two earlier measurements of this wave: **≈ 523/h** over 3,001 blocks (dispatch 1's verification probe) and **440/h** over the 135-minute backfill window (dispatch 2). They are three measurements of three different windows, not a trend.

Admission, per token per tick — every launch gets a `DISCOVERY` record whether it is followed or not:

| reason | n |
|---|---|
| `ADMITTED` | 6,925 |
| `OBSERVATION_UNUSABLE` | 2,121 |
| `TAPE_OPENED` | 677 |
| `QUOTE_UNSUPPORTED|NO_INITIAL_STATE` | 191 |
| `NO_INITIAL_STATE` | 47 |
| `CURVE_COMPLETED` | 20 |
| `STATE_INVALID` | 20 |

| observation status | n |
|---|---|
| `OK` | 7,011 |
| `INSUFFICIENT_TAPE` | 2,101 |
| `ROUTE_COMPLETED` | 20 |

One admission fact differs from the replay and only one: `require_coverage` is **off**, because "the horizon lies inside the token's coverage" is addendum 10's *replay* clause and live has no end of data to keep a horizon inside. It was registered off in `live.json` before the run. Rotation is unchanged: round-robin on rounds-since-last-presentation and the launch order, blind to price, volume, flow, outcome and ticker.

## 4. What the decoder decided

Three denominators, never pooled.

| denominator | n | statuses | actions |
|---|---|---|---|
| per candidate evaluation | 236 | {'VALID': 236} | {'BUY': 4, 'SELL': 223, 'WAIT': 9} |
| per decision round | 85 | {'VALID': 85} | {'BUY': 4, 'SELL': 73, 'WAIT': 8} |

After the execution constraints:

| outcome of the round | n |
|---|---|
| `blocked_by_fixed_hold` | 55 |
| `NO_ORDER:SELL` | 18 |
| `NO_ORDER:WAIT` | 5 |
| `HOLD:WAIT` | 3 |
| `BUY` | 2 |
| `HOLD:BUY` | 2 |
| `UNRESOLVED:PENDING_CONFIRMATION` | 2 |
| `POLICY_CLOSE_FIXED_HOLD` | 1 |
| `UNRESOLVED:END_OF_DATA` | 1 |

Presentations 1,888, candidate evaluations 236, silent replicates 130 of 1,888, invalid replicates 0.

## 5. Episodes

Expected before the run: at most **4** episodes over 120 ticks, and fewer because an entry needs a decoded BUY, and settlement needs confirmation the last ten minutes of the run cannot supply. Observed: **1**.

| # | token | entry block | entry ts | fill (ETH/token) | exit block | exit fill | fees+gas (ETH) | impact (ETH) | net (ETH) | held (s) | confirmation | learning event |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `0x5322c601…` | 60,904,940 | 1789195712 | 1.690e-09 | 60,913,789 | 1.690e-09 | 0.000263162 | 0.000116337 | -0.000263162 | 900 | CONFIRMED | accepted |

| accounting | value |
|---|---|
| trades | 1 |
| wins / losses / flat | 0 / 1 / 0 |
| gross at reference prices | +0.000116337 |
| − price impact | 0.000116337 |
| − fees, taxes and gas | 0.000489676 |
| = net | -0.000263162 |
| reconciliation residual | -2.265e-04 |
| — the open position's entry fee, already paid | 0.000226514 |
| residual once that entry is set aside | -5.421e-20 |

**The residual is the open position's entry fee and nothing else.** The account's three-way identity (`gross_reference − slippage − fees = net`) closes over *settled* trades; a position still open at the stop has paid its entry fee and has no outcome yet, so its fee sits in `fees_paid` with nothing on the other side. Setting it aside leaves -5.421e-20, which is the same floating-point floor the replay run closed at. Nothing was written off and the exposure is retained.

### Confirmation status at the stop

The settlement rule is unchanged: the entry-fill block and the exit block must both be at least 594 blocks behind head **and** at or below the `safe` tag, and the grid anchor below each must still hash to what was stored. The safe tag was measured about 5,400 blocks (~9 minutes) behind head, so an episode whose exit block is inside the last ~10 minutes of the run will still be PENDING_CONFIRMATION at the stop and is reported as such, not settled.

| state at the stop | n |
|---|---|
| settled and confirmed | 1 |
| of those, waited for confirmation and then settled | 1 |
| `PENDING_CONFIRMATION` **at the stop** (reported pending, **not settled**) | 1 |
| `END_OF_DATA` | 1 |

| episode | token | reason | detail | retryable |
|---|---|---|---|---|
| 7000087 | `0x5322c601…` | `PENDING_CONFIRMATION` | entry True exit False | True |
| 72000315 | `0xbf4c964f…` | `PENDING_CONFIRMATION` | entry True exit False | True |
| 72000315 | `0xbf4c964f…` | `END_OF_DATA` | the window ended with the position still open | False |

An unresolved or pending position is **neither a loss nor a win**: the exposure is retained in the journal, nothing settles and nothing is taught. A position still open when the run stopped was **not** closed at the last mark.

Position marks recorded while holding: **86** ticks, of which 86 could be quoted and 0 could not. A mark is a mark: it is written into the tick record and displayed, and it never reached reinforcement.

| mark series (unrealised, ETH) | value |
|---|---|
| minimum | -0.000460162 |
| median | -0.000263162 |
| maximum | -0.000263162 |
| last | -0.000460162 |

## 6. What it cost, and what a subscription would have cost

| method | attempts | units (archive-weighted) | errors |
|---|---|---|---|
| `eth_call` | 1 | 2 | 0 |
| `eth_chainId` | 1 | 1 | 0 |
| `eth_getBlockByNumber` | 1,013 | 1,635 | 0 |
| `eth_getLogs` | 478 | 617 | 0 |
| **total** | **1,493** | **2,255** | 0 |

Against the caps: **1,493 of the 3,000** this run was allowed (addendum 15), and **2,748 of the 10,000** the wave is allowed (addendum 5), 4,719 archive-weighted units in the wave's ledger. A read 127 or more blocks behind the tip is billed at two units (docs.chainstack.com/docs/request-units); the ledger records attempts **and** units, and the cap is on attempts.

**WSS-equivalent for the same window: 114,951 billed messages** — 2 subscriptions + 44,021 log pushes + 70,928 header pushes, against the 1,493 attempts this HTTP run actually spent. docs.chainstack.com/docs/request-units: one request to open a subscription, then one per delivered push. A logs subscription would have pushed every log of the scanned range and a newHeads subscription every header. This is the comparison the owner asked for as a number rather than an opinion.

No endpoint error occurred. Nothing was retried, because nothing in this package retries.

## 7. Learning, and the state digest

| item | value |
|---|---|
| learning mode | LEARN |
| digest at the start | `999d32450a3b…` |
| digest at the stop | `c1e87b5a62c4…` |
| digest unchanged | False |
| settled episodes | 1 |
| accepted normalised updates **in this run** | 1 |
| credit rejections in this run | 0 |

The credit counters are durable: they ride in the checkpoint, so this run inherited 7 accepted update(s) from the replay checkpoint it started at and the row above subtracts them. The inherited total is not this run's work and is not reported as if it were.

Recovery at start: `nothing to do`, checkpoint loaded **True**, last settled episode 203000217. The learned state the run began from is the replay run's own final checkpoint, verified by digest before the first request.

## 8. The four conclusions, separated

### 1. Integration

**The live link works.** New PONS v2 events were received over HTTP from Robinhood Chain (chain id 4663) on the wall clock, normalised through the same path the replay dataset was written with, reconstructed into exact curve state, turned into causal context, encoded onto the olfactory path, measured by the existing k = 8 readout, decoded by the existing decoder, executed on paper against the integer-exact curve quote, and journalled through the existing recovery machinery, with the confirmation rule gating every settlement. The run stopped on `TIME_LIMIT` and persisted its cursor, ledger, journal and checkpoint.

### 2. The brain produced the observed behaviour

Every decision in this run came from the decoder applied once to the aggregate of 8 presentations of the encoded observation, under the `comparison_v1` seed schedule keyed to the observation's content hash and the token's stable id — never to its address spelling or its position in a list. No LLM, classifier, alpha score or technical rule is in the decision path; admission is seven objective facts (one of them registered off for live, §3) and the rotation is round-robin. 85 decision rounds were decoded and are in the log with their per-replicate scores.

### 3. Learning updated the declared eligible state

1 settled episode(s) produced 8 accepted normalised update(s), each credited to **the entry decision's own stored k = 8 eligibility trace set** by episode id through the existing `CreditAssigner`. The learned-state digest moved from `999d32450a3b…` to `c1e87b5a62c4…`. An episode that was still pending confirmation at the stop taught nothing, by construction.

### 4. Predictive usefulness

**Not tested — no predictive evaluation was designed for D10.** There is no probe grid, no label, no AUC, no holdout and no cohort split in this wave; `PLAN.md` says so before the run rather than after it. Nothing in this file may be read as evidence for or against predictive skill, and the number of episodes, their sign and their sum are not such evidence.

## 9. What this is not

* Not a prediction test, not a profitability claim, and not a measurement of skill.
* Not an hour that can be compared with the replay window: different blocks, different tokens, a different clock and a different number of ticks. The two reports are separate for that reason.
* Not multimodal: the `SensoryEncoder` returns `{"olfactory": Stimulus}` and names `visual`, `taste` and `mechanosensory` as unimplemented extension points routed nowhere.
* Not a market participant: the paper position never changed the public market, and no audience or copying effect is modelled.
* Not a real-money path: six read methods, no key material, nothing signed, approved, broadcast or moved.

