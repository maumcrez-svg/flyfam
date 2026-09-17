# D11 — retrospective admission and encoding diagnostic

**This is not a backtest, and it computes no trade the corrected brain
would have made** — no PnL, no corrected outcome, no counterfactual reward.
It answers one question on cutoffs two D10 runs already recorded: *which
candidates would admission v2 have made eligible, and would they still have
smelled the same?*

Every eligibility calculation stops at its historical cutoff. Each tape is
read only through events at or before it — including the curve's own
completion, which is masked back to what the loop had ingested — and no
later trade is inspected to decide admission. No socket was opened, no brain
was simulated, and nothing under `experiments/d10/` was written.

Rules and constants: `experiments/d11/config.json`, registered in `481dd3e`
and calibrated in `87b8b2f`, both before this file was run.

## 1. Per run: what changes

| | `d10-001/learning` | `d10-live-001/live` |
|---|---|---|
| ticks | 272 | 111 |
| `ROUND` records in the log | 240 | 111 |
| tapes reconstructed offline | 617 | 679 |
| launches whose state could not be reconstructed offline | 55 | 47 |
| **candidate-ticks admitted by v1** (recomputed) | 41,947 | 30,076 |
| candidates actually presented by v1 (as recorded) | 348 | 236 |
| **candidate-ticks admitted by v2** | 2,130 | 1,355 |
| ticks with zero eligible under v1 | 32 | 0 |
| **ticks with zero eligible under v2** | 32 | 0 |
| ticks with 1–5 eligible under v2 | 33 | 0 |
| ticks with 6 or more eligible under v2 | 207 | 111 |
| most eligible in any one tick under v2 | 16 | 19 |
| median eligible per tick under v2 | 9.0 | 12.0 |
| rounds that would be `DATA_LAG` | 0 | 0 |

A *candidate-tick* is one (token, tick) pair: a token tracked for an hour
contributes to up to 120 of them, so these are not counts of tokens.

**The two rules, side by side.** v1 asked for three trades *ever*; v2 asks
for two valid trades inside the last two minutes with the last one at most
sixty seconds back. On the replay that takes 41,947
eligible candidate-ticks down to **2,130**
(5.1 %), and on
the live hour 30,076 down to **1,355**
(4.5 %). That is the
corpses leaving the pool, and it is reported, not softened: **section 6**
states the limitation and the rule is not loosened because of it.

**Faithfulness of the recomputation.** The tracker rebuilds the tapes the
loop tracked and re-runs `admission_v1` at the recorded cutoffs; on the flat
ticks that carry a `ROUND` record it must reproduce the record's own
`considered` and `admitted` counts.

| run | flat ticks checked | `considered` reproduced | `admitted` reproduced |
|---|---|---|---|
| `d10-001/learning` | 23 | 23 | 23 |
| `d10-live-001/live` | 25 | 2 | 5 |

The replay reproduces **exactly**: 23 of 23 on both counts. **The live run
does not, and the difference is declared rather than hidden.** The live
chain store carries no `initial_states.json` — the live driver derived each
launch state from the curve's own first trade — so 47
launches could not be reconstructed offline at all, and the driver's
*hold a launch until its first trade pins the creator tax* rule (D10
deviation 17) released tapes on a schedule this file cannot replay. The
offline tracked set therefore sits **+1 candidate** on 23 of the 25 flat
ticks and the recomputed v1 admitted count **−1** on 20 of them. Every live
number in this file carries that ±1-per-tick uncertainty; none of the
conclusions turns on a single candidate.

## 2. Why candidates are excluded

Counted per (token, tick) pair over every tick of the run, so one token
quiet for an hour contributes to many ticks. A candidate may carry several
reasons and every one of them is counted.

| reason | `learning` v1 | `learning` v2 | `live` v1 | `live` v2 |
|---|---|---|---|---|
| `ADMITTED` | 41,947 | 2,130 | 30,076 | 1,355 |
| `COVERAGE` | 7,461 | 7,461 | 0 | 0 |
| `CURVE_COMPLETED` | 377 | 0 | 101 | 0 |
| `INACTIVE` | 0 | 54,906 | 0 | 37,583 |
| `OBSERVATION_UNUSABLE` | 9,486 | 0 | 8,864 | 0 |
| `ROUTE_COMPLETED` | 0 | 377 | 0 | 101 |
| `STATE_INVALID` | 414 | 414 | 117 | 117 |

Reading the table:

* **`INACTIVE` is the whole of the change.** It is a *new* code and it
  absorbs what v1 admitted: a complete tape, a valid state, a curve that
  never graduated, and no trade in two minutes.
* **`INSUFFICIENT_HISTORY` is zero in both runs, and that is correct.** The
  loop only ever considers a token already 60 s old (`PonsLoop._candidates`
  filters on age before admission sees it), so the tapes that reach
  admission can always answer. v1's `OBSERVATION_UNUSABLE` at those ticks is
  entirely its *fewer than three trades ever* clause — the clause v2
  removes — and those candidates reappear under `INACTIVE` or as admitted,
  by their recent activity rather than their lifetime count.
* **`COLLECTOR_LAG` is zero, and it could not have been anything else.**
  Replay cannot lag by construction, and the live run's own health file
  reported the confirmed block 64–92 s old in 165 of 165 samples against a
  two-tick bound — this diagnostic recomputes from the persisted store,
  which has no lag at all, so the code path is exercised by
  `tests/d11/test_admission_v2.py` and not by this table.
* `COVERAGE` and `STATE_INVALID` are identical between v1 and v2 because
  v2 keeps those two clauses unchanged; `ROUTE_COMPLETED` is v1's
  `CURVE_COMPLETED` renamed, at the same count.

## 3. Deterministic sensory collisions, before and after

A *collision* is two candidates in the same round whose **deterministic**
per-glomerulus ORN drive agrees on every channel to within 1e-9 Hz — the
vector the encoder produces **before** any Poisson sampling, never a display
field. *Before* is v1's sixteen channels over the candidates the run
actually presented, with their recorded raw vectors. *After* is v2's twenty
channels over the set v2 would have made eligible at the same cutoff.

| | `learning` before | `learning` after | `live` before | `live` after |
|---|---|---|---|---|
| candidates in a colliding group | 8 | 0 | 11 | 0 |
| colliding groups | 4 | 0 | 5 | 0 |
| ticks containing a collision | 4 | 0 | 5 | 0 |
| candidates in the denominator | 348 | 2,130 | 236 | 1,355 |

**8 of 348 presented candidates (2.3 %) on the replay
and 11 of 236 (4.7 %) live carried a
drive vector identical to another candidate in the same round. Under v2,
**0 of 2,130** and
**0 of 1,355** do.

The two denominators are **different sets** and the comparison is a rate,
not a difference of counts: v1's denominator is what the fly was shown,
v2's is what it would have been eligible to be shown. And the zero is not a
promise of uniqueness — `pons_context_v2` still encodes two identical
measured contexts identically, by design, and
`tests/d11/test_encoder_v2.py` asserts exactly that. It is the statement
that on these cutoffs no two *eligible* candidates had identical
measurements, because a candidate now has to have traded in the last two
minutes to be eligible at all, and two such tokens rarely agree on ten
numbers at once.

## 4. The seventeen entries, under v2

Each entry re-evaluated at its own cutoff with the tape truncated there.

| run / branch | episode | token | `since_last_trade` | `trade_count_2m` | v2 verdict | reasons |
|---|---|---|---|---|---|---|
| `d10-001/frozen_reference` | 4000000 | `0x60f73368…` | 42 s | 20 | **ADMITTED** | — |
| `d10-001/frozen_reference` | 36000009 | `0xd41786b0…` | 510 s | 0 | **EXCLUDED** | `INACTIVE` |
| `d10-001/frozen_reference` | 68000016 | `0x6dce4fbd…` | 693 s | 0 | **EXCLUDED** | `INACTIVE` |
| `d10-001/frozen_reference` | 100000021 | `0x5987cb92…` | 2570 s | 0 | **EXCLUDED** | `INACTIVE` |
| `d10-001/frozen_reference` | 132000030 | `0xf4a9c152…` | 2684 s | 0 | **EXCLUDED** | `INACTIVE` |
| `d10-001/frozen_reference` | 164000102 | `0x3d03602b…` | 3520 s | 0 | **EXCLUDED** | `INACTIVE` |
| `d10-001/frozen_reference` | 196000173 | `0xb5ef24de…` | 3266 s | 0 | **EXCLUDED** | `INACTIVE` |
| `d10-001/frozen_reference` | 228000250 | `0xdf7624ba…` | 3467 s | 0 | **EXCLUDED** | `INACTIVE` |
| `d10-001/learning` | 4000000 | `0x60f73368…` | 42 s | 20 | **ADMITTED** | — |
| `d10-001/learning` | 36000009 | `0xd41786b0…` | 510 s | 0 | **EXCLUDED** | `INACTIVE` |
| `d10-001/learning` | 68000017 | `0x81498680…` | 882 s | 0 | **EXCLUDED** | `INACTIVE` |
| `d10-001/learning` | 100000022 | `0x382bb253…` | 2617 s | 0 | **EXCLUDED** | `INACTIVE` |
| `d10-001/learning` | 132000028 | `0x84129729…` | 1656 s | 0 | **EXCLUDED** | `INACTIVE` |
| `d10-001/learning` | 165000109 | `0x0188995e…` | 3280 s | 0 | **EXCLUDED** | `INACTIVE` |
| `d10-001/learning` | 203000217 | `0x56d4a05d…` | 1742 s | 0 | **EXCLUDED** | `INACTIVE` |
| `d10-live-001/live` | 7000087 | `0x5322c601…` | 3038 s | 0 | **EXCLUDED** | `INACTIVE` |
| `d10-live-001/live` | 72000315 | `0xbf4c964f…` | 1373 s | 0 | **EXCLUDED** | `INACTIVE` |

**15 of the 17 entries would not have been eligible at all**,
every one of them `INACTIVE` and nothing else — the state was valid, the
curve had not graduated, the coverage reached the horizon, and the token
simply had not traded. The two that survive are the same tick-4 round in
both replay branches: 20 valid trades in the window, the last 42 s back.

This says which candidates would have been *eligible*. It says nothing
about which one the fly would have chosen, or what that would have paid.

## 5. The four distinctions, on real tokens

Drawn from `d10-backfill-v1`, each at a real cutoff, with the v2 rate vector
the encoder produces. Rates are per-ORN drive in Hz per glomerulus on the
same constant 12,000 Hz budget across 1,070 ORNs; the carrier alone is
about 5.7 Hz on twenty channels.

### A — no trades in the observed interval

`0x0001fcacda980a6d5a4b94924439240ca1427156` at cutoff **1789182365**, status `OK`.

| feature | raw | normalised |
|---|---|---|
| `age` | 600 | +0.761594 |
| `since_last_trade` | 600 | +1.000000 |
| `ret_30s` | 0 | +0.000000 |
| `ret_2m` | 0 | +0.000000 |
| `ret_5m` | 0 | +0.000000 |
| `flow_imb_2m` | 0 | +0.000000 |
| `trade_count_2m` | 0 | +0.000000 |
| `gross_volume_2m` | 0 | +0.000000 |
| `rv_2m` | 0 | +0.000000 |
| `drawdown_5m` | 0 | +0.000000 |

Rate vector, Hz per ORN:

| VL2a | VM5d | DL1 | VL1 | VM4 | DM3 | DM6 | V | DM2 | DA2 | VL2p | VM3 | VC4 | VM7d | DC3 | DM5 | DA3 | VC3 | VM5v | DP1l |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 37.87 | 4.822 | 48.22 | 4.822 | 4.822 | 4.822 | 4.822 | 4.822 | 4.822 | 4.822 | 4.822 | 4.822 | 4.822 | 4.822 | 4.822 | 4.822 | 4.822 | 4.822 | 4.822 | 4.822 |

### B — many trades, almost no net price change

`0xaa24984594dec6b81a9ee28f78fc29fced6c0018` at cutoff **1789181363**, status `OK`.

| feature | raw | normalised |
|---|---|---|
| `age` | 60 | +0.099668 |
| `since_last_trade` | 3 | +0.049958 |
| `ret_30s` | 0.0022203 | +0.409785 |
| `ret_2m` | 0.0038085 | +0.034609 |
| `ret_5m` | 0.0038085 | +0.010579 |
| `flow_imb_2m` | 0.0160112 | +0.016010 |
| `trade_count_2m` | 67 | +0.338707 |
| `gross_volume_2m` | 0.200617 | +0.035181 |
| `rv_2m` | 0.00923959 | +0.308246 |
| `drawdown_5m` | -0.0484304 | -0.094677 |

Rate vector, Hz per ORN:

| VL2a | VM5d | DL1 | VL1 | VM4 | DM3 | DM6 | V | DM2 | DA2 | VL2p | VM3 | VC4 | VM7d | DC3 | DM5 | DA3 | VC3 | VM5v | DP1l |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 12.92 | 6.811 | 9.873 | 6.811 | 31.93 | 6.811 | 8.932 | 6.811 | 7.459 | 6.811 | 7.792 | 6.811 | 27.57 | 6.811 | 8.967 | 6.811 | 25.7 | 6.811 | 6.811 | 12.61 |

### C — balanced buys and sells with meaningful gross volume

`0x025d5ba6f2beb6e06f049b524c618ccb5ecdef8a` at cutoff **1789180018**, status `OK`.

| feature | raw | normalised |
|---|---|---|
| `age` | 60 | +0.099668 |
| `since_last_trade` | 13 | +0.213339 |
| `ret_30s` | -0.0357026 | -0.999998 |
| `ret_2m` | -0.140094 | -0.854765 |
| `ret_5m` | -0.140094 | -0.370627 |
| `flow_imb_2m` | 0.0315135 | +0.031503 |
| `trade_count_2m` | 22 | +0.115275 |
| `gross_volume_2m` | 1.37165 | +0.236100 |
| `rv_2m` | 0.0714196 | +0.985586 |
| `drawdown_5m` | -0.648924 | -0.854447 |

Rate vector, Hz per ORN:

| VL2a | VM5d | DL1 | VL1 | VM4 | DM3 | DM6 | V | DM2 | DA2 | VL2p | VM3 | VC4 | VM7d | DC3 | DM5 | DA3 | VC3 | VM5v | DP1l |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 7.228 | 3.81 | 11.13 | 3.81 | 3.81 | 38.1 | 3.81 | 33.12 | 3.81 | 16.52 | 4.891 | 3.81 | 7.763 | 3.81 | 11.91 | 3.81 | 37.61 | 3.81 | 3.81 | 33.11 |

### D — missing or incomplete observation — NOT PRESENTED

`0x0001fcacda980a6d5a4b94924439240ca1427156` at cutoff **1789181795**, status `INSUFFICIENT_TAPE` (age 30s < 60s).

| feature | raw | normalised |
|---|---|---|
| `age` | — | — |
| `since_last_trade` | — | — |
| `ret_30s` | — | — |
| `ret_2m` | — | — |
| `ret_5m` | — | — |
| `flow_imb_2m` | — | — |
| `trade_count_2m` | — | — |
| `gross_volume_2m` | — | — |
| `rv_2m` | — | — |
| `drawdown_5m` | — | — |

**No rate vector exists**: the observation is not usable, so it is
not encoded at all. There is no zero vector standing in for it —
that is the whole of distinction D.

The four are distinguishable in the deterministic vector, which is what
section 4 of the amendment asks for: **A** carries `trade_count_2m` and
`gross_volume_2m` at exactly zero with `since_last_trade` large; **B**
carries a high count and near-zero returns with small `rv_2m`; **C** carries
real gross volume with `flow_imb_2m` near zero; **D** carries nothing,
because it is not presented.

## 6. The limitation, stated and not worked around

**Admission v2 leaves few candidates, and the rule is not loosened.**

* On the replay, the median tick has **9** eligible
  candidates and the busiest has 16; 33 of 272 ticks would present fewer
  than the six the rotation allows, and 32 would
  present none at all — the same number v1 presents none at, so v2 creates
  no new empty round on this window.
* Live, the median tick has **12** eligible candidates,
  the thinnest has 8 and the
  busiest 19; **no tick is empty and no tick falls
  below six.**
* The scale fit saw the same shrinkage from the other side: 1,197 of 56,932
  grid points admitted in the first hour of the window
  (`experiments/d11/feature_scales_v2.json`).

That is what a two-minute liveness rule costs on a venue where 59 % of
launches are silent five minutes after birth. It is the intended effect —
the pool stops being corpses — and it is also a real constraint on how much
choice a round offers. It is recorded here so the next wave argues about it
with a number, and **no criterion was relaxed to make the tables look
better**.

## 7. What this file does not say

It does not compute a trade, a fill, a PnL or a reward. It does not say the
corrected brain would have chosen better, or at all. It does not compare
D10's losses with anything. It measures two things — how many candidates
survive the new rule, and how often two of them smell identical — and both
are properties of the *environment*, not of the fly.
