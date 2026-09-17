# D11 — reconciliation of the D10 diagnostic

**Read-only.** Nothing under `experiments/d10/` changed, no run was started, no
socket was opened, no brain was simulated. Every number below is recomputed by
`experiments/d11/reconcile.py` from the three committed event logs, the two chain
stores, `experiments/d10/config.json` and `experiments/d10/determinism.json`.
Section 2 of the D11 amendment asks four questions; they are answered in order,
and the stimulus question is answered from the deterministic encoder rate vectors.

## 1. The seventeen entries, by run, branch and episode

Seventeen `EXECUTION` BUY legs exist across the three logs: **7** in
`d10-001/learning`, **8** in `d10-001/frozen_reference` (the frozen control) and
**2** in `d10-live-001/live`. Sixteen settled; one is `PENDING_CONFIRMATION`, has
no exit leg, no outcome and no reinforcement, and stays exactly as recorded.

*since last valid trade* and *valid trades* are measured on the token's own event
stream in its store, counting only `CurveBuy`/`CurveSell` with status OK, a
nonzero quote leg and a nonzero token leg, deduplicated by log id. *recent* is the
D11 rule quoted for classification only: at least 2 such trades inside
`(cutoff − 120 s, cutoff]` and the last of them at most 60 s before the cutoff.

| # | run | branch | episode | round | token | cutoff ts | age | since last valid trade | valid trades in 120 s | valid trades ever | recent | settlement | net (ETH) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `d10-001` | `frozen_reference` | 4000000 | 4 | `0x60f73368…` | 1789177146 | 90 s | 42 s | 20 | 20 | **yes** | `SETTLED_FROZEN` | -0.000006400 |
| 2 | `d10-001` | `frozen_reference` | 36000009 | 36 | `0xd41786b0…` | 1789178106 | 965 s | 510 s | 0 | 6 | no | `SETTLED_FROZEN` | -0.000655160 |
| 3 | `d10-001` | `frozen_reference` | 68000016 | 68 | `0x6dce4fbd…` | 1789179066 | 1781 s | 693 s | 0 | 26 | no | `SETTLED_FROZEN` | -0.000289970 |
| 4 | `d10-001` | `frozen_reference` | 100000021 | 100 | `0x5987cb92…` | 1789180026 | 2645 s | 2570 s | 0 | 4 | no | `SETTLED_FROZEN` | -0.000263160 |
| 5 | `d10-001` | `frozen_reference` | 132000030 | 132 | `0xf4a9c152…` | 1789180986 | 3538 s | 2684 s | 0 | 6 | no | `SETTLED_FROZEN` | -0.000460160 |
| 6 | `d10-001` | `frozen_reference` | 164000102 | 164 | `0x3d03602b…` | 1789181946 | 3527 s | 3520 s | 0 | 82 | no | `SETTLED_FROZEN` | -0.000263160 |
| 7 | `d10-001` | `frozen_reference` | 196000173 | 196 | `0xb5ef24de…` | 1789182906 | 3530 s | 3266 s | 0 | 4 | no | `SETTLED_FROZEN` | -0.000263160 |
| 8 | `d10-001` | `frozen_reference` | 228000250 | 228 | `0xdf7624ba…` | 1789183866 | 3515 s | 3467 s | 0 | 15 | no | `SETTLED_FROZEN` | -0.000460160 |
| 9 | `d10-001` | `learning` | 4000000 | 4 | `0x60f73368…` | 1789177146 | 90 s | 42 s | 20 | 20 | **yes** | `SETTLED` | -0.000006400 |
| 10 | `d10-001` | `learning` | 36000009 | 36 | `0xd41786b0…` | 1789178106 | 965 s | 510 s | 0 | 6 | no | `SETTLED` | -0.000655160 |
| 11 | `d10-001` | `learning` | 68000017 | 68 | `0x81498680…` | 1789179066 | 1762 s | 882 s | 0 | 22 | no | `SETTLED` | -0.000293540 |
| 12 | `d10-001` | `learning` | 100000022 | 100 | `0x382bb253…` | 1789180026 | 2629 s | 2617 s | 0 | 14 | no | `SETTLED` | -0.000460160 |
| 13 | `d10-001` | `learning` | 132000028 | 132 | `0x84129729…` | 1789180986 | 3543 s | 1656 s | 0 | 24 | no | `SETTLED` | -0.000655160 |
| 14 | `d10-001` | `learning` | 165000109 | 165 | `0x0188995e…` | 1789181976 | 3468 s | 3280 s | 0 | 4 | no | `SETTLED` | -0.000263160 |
| 15 | `d10-001` | `learning` | 203000217 | 203 | `0x56d4a05d…` | 1789183116 | 3235 s | 1742 s | 0 | 20 | no | `SETTLED` | -0.000655160 |
| 16 | `d10-live-001` | `live` | 7000087 | 7 | `0x5322c601…` | 1789195710 | 3040 s | 3038 s | 0 | 12 | no | `SETTLED` | -0.000263160 |
| 17 | `d10-live-001` | `live` | 72000315 | 72 | `0xbf4c964f…` | 1789197660 | 2711 s | 1373 s | 0 | 159 | no | `PENDING_CONFIRMATION` | — |

## 2. The fifteen entries without recent activity

**15 of 17** entries fail the
recency rule at their own cutoff, and they fail it the same way: **zero** valid
trades inside the two-minute window, with the last trade between
**510 s (8.5 min)** and **3520 s (58.7 min)** behind it. The two
that pass are the same tick-4 round in both replay branches — one token 90 s old,
20 valid trades in its life, the last 42 s before the cutoff.

| run / branch | episode | token | since last valid trade | trades in 120 s | verdict under the D11 rule |
|---|---|---|---|---|---|
| `d10-001/frozen_reference` | 4000000 | `0x60f73368…` | 42 s | 20 | admitted by recency |
| `d10-001/frozen_reference` | 36000009 | `0xd41786b0…` | 510 s | 0 | `INACTIVE` |
| `d10-001/frozen_reference` | 68000016 | `0x6dce4fbd…` | 693 s | 0 | `INACTIVE` |
| `d10-001/frozen_reference` | 100000021 | `0x5987cb92…` | 2570 s | 0 | `INACTIVE` |
| `d10-001/frozen_reference` | 132000030 | `0xf4a9c152…` | 2684 s | 0 | `INACTIVE` |
| `d10-001/frozen_reference` | 164000102 | `0x3d03602b…` | 3520 s | 0 | `INACTIVE` |
| `d10-001/frozen_reference` | 196000173 | `0xb5ef24de…` | 3266 s | 0 | `INACTIVE` |
| `d10-001/frozen_reference` | 228000250 | `0xdf7624ba…` | 3467 s | 0 | `INACTIVE` |
| `d10-001/learning` | 4000000 | `0x60f73368…` | 42 s | 20 | admitted by recency |
| `d10-001/learning` | 36000009 | `0xd41786b0…` | 510 s | 0 | `INACTIVE` |
| `d10-001/learning` | 68000017 | `0x81498680…` | 882 s | 0 | `INACTIVE` |
| `d10-001/learning` | 100000022 | `0x382bb253…` | 2617 s | 0 | `INACTIVE` |
| `d10-001/learning` | 132000028 | `0x84129729…` | 1656 s | 0 | `INACTIVE` |
| `d10-001/learning` | 165000109 | `0x0188995e…` | 3280 s | 0 | `INACTIVE` |
| `d10-001/learning` | 203000217 | `0x56d4a05d…` | 1742 s | 0 | `INACTIVE` |
| `d10-live-001/live` | 7000087 | `0x5322c601…` | 3038 s | 0 | `INACTIVE` |
| `d10-live-001/live` | 72000315 | `0xbf4c964f…` | 1373 s | 0 | `INACTIVE` |

**No token is called dead here.** Every one of the seventeen had traded before its
cutoff — the smallest count is 4 valid trades and the largest is 159 — and
**2 of the 15** inactive tokens traded again later inside the
same store, which is why admission v2 is evaluated fresh at every tick and is
reversible by construction: *inactive at this cutoff* is a statement about this
cutoff and about nothing else. A token that stops trading before a dataset ends is
a token whose later life was not observed.

| run / branch | episode | token | trades after the cutoff, inside the store | first of them |
|---|---|---|---|---|
| `d10-001/frozen_reference` | 36000009 | `0xd41786b0…` | 0 | — |
| `d10-001/frozen_reference` | 68000016 | `0x6dce4fbd…` | 2 | 32 s |
| `d10-001/frozen_reference` | 100000021 | `0x5987cb92…` | 0 | — |
| `d10-001/frozen_reference` | 132000030 | `0xf4a9c152…` | 0 | — |
| `d10-001/frozen_reference` | 164000102 | `0x3d03602b…` | 0 | — |
| `d10-001/frozen_reference` | 196000173 | `0xb5ef24de…` | 0 | — |
| `d10-001/frozen_reference` | 228000250 | `0xdf7624ba…` | 0 | — |
| `d10-001/learning` | 36000009 | `0xd41786b0…` | 0 | — |
| `d10-001/learning` | 68000017 | `0x81498680…` | 1 | 212 s |
| `d10-001/learning` | 100000022 | `0x382bb253…` | 0 | — |
| `d10-001/learning` | 132000028 | `0x84129729…` | 0 | — |
| `d10-001/learning` | 165000109 | `0x0188995e…` | 0 | — |
| `d10-001/learning` | 203000217 | `0x56d4a05d…` | 0 | — |
| `d10-live-001/live` | 7000087 | `0x5322c601…` | 0 | — |
| `d10-live-001/live` | 72000315 | `0xbf4c964f…` | 0 | — |

## 3. The eight learning updates, and their identities

**8** `LEARNING` records exist across the three logs,
all accepted, all of valence −1. They are the whole of D10's learning and they are
the D11 reward-calibration set.

| # | run | branch | episode | token | net (ETH) | net return on notional | pre-clip \|r\|/0.01 | applied amount | valence | synapses depressed |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `d10-001` | `learning` | 4000000 | `0x60f73368…` | -0.000006400 | -0.0006404628 | 0.064046 | **0.064046** | -1 | 2,438 |
| 2 | `d10-001` | `learning` | 36000009 | `0xd41786b0…` | -0.000655160 | -0.0655162120 | 6.551621 | **1.0** | -1 | 2,830 |
| 3 | `d10-001` | `learning` | 68000017 | `0x81498680…` | -0.000293540 | -0.0293537590 | 2.935376 | **1.0** | -1 | 2,917 |
| 4 | `d10-001` | `learning` | 100000022 | `0x382bb253…` | -0.000460160 | -0.0460162120 | 4.601621 | **1.0** | -1 | 2,081 |
| 5 | `d10-001` | `learning` | 132000028 | `0x84129729…` | -0.000655160 | -0.0655162120 | 6.551621 | **1.0** | -1 | 2,901 |
| 6 | `d10-001` | `learning` | 165000109 | `0x0188995e…` | -0.000263160 | -0.0263162120 | 2.631621 | **1.0** | -1 | 2,815 |
| 7 | `d10-001` | `learning` | 203000217 | `0x56d4a05d…` | -0.000655160 | -0.0655162120 | 6.551621 | **1.0** | -1 | 2,714 |
| 8 | `d10-live-001` | `live` | 7000087 | `0x5322c601…` | -0.000263160 | -0.0263162120 | 2.631621 | **1.0** | -1 | 2,831 |

## 4. The branches that produced no learning

| branch | entries | settlements | `SETTLED_FROZEN` | `LEARNING` records | accepted updates |
|---|---|---|---|---|---|
| `d10-001/frozen_reference` | 8 | 8 | 8 | 0 | 0 |
| `d10-001/learning` | 7 | 7 | 0 | 7 | 7 |
| `d10-live-001/live` | 2 | 1 | 0 | 1 | 1 |

* **`d10-001/frozen_reference`** took 8 entries on the same data and the same
  `comparison_v1` seeds from the same clean checkpoint, settled all 8 as
  **`SETTLED_FROZEN`** and wrote **0** `LEARNING` records: `Journal.settle_frozen`
  writes an `OUTCOME`, counts the settlement and calls no reinforcement at all. Its
  eight outcomes have a derivable pre-clip amount and no applied amount, and its
  end digest equals its start digest.
* **The determinism re-run of `d10-001/learning`** is the same events, not new
  ones. `experiments/d10/determinism.json` records both logs at
  `34a74b0b780e420d…` after removing the wall clock and the absolute
  checkpoint path — identical: `true`, 1,495 lines each,
  final state digest `999d32450a3b…` on both. It is **excluded as a
  duplicate**: its seven settlements are the seven already counted, and pooling
  them would report fourteen independent experiences where seven exist.
* **The pending live position** (`d10-live-001`, episode 72000315) produced no
  learning because it never settled. It is retained, not written off.

So the honest arithmetic is **17 entries → 16 settlements → 8 learning updates**,
and not 17, not 16 and not 24.

## 5. Stimulus equality, from the deterministic encoder rate vectors

The D10 closure read the identical-stimulus finding off the display fields — seven
features printed as `0.000000`. That is not the same statement as *the brain
received the same drive*, so it is recomputed here from the encoder itself.

**Method.** `flytrade.encoder.MarketToSensoryEncoder` is built from
`data/malecns-v1.0/annotations.npz` with the config's own eight features, carrier
0.1, budget 12000 Hz,
cap 150 Hz and `coding="normalized"`.
Each presented candidate's **recorded raw vector** is normalised with the config's
declared scales and pushed through `encoder.rates(...)`, which is the deterministic
per-ORN drive in Hz per glomerulus — the quantity that exists *before* any Poisson
sampling. Two candidates collide when every one of the sixteen channels agrees to
within **1e-9 Hz**.

**The encoder is the run's encoder.** Recomputed against the `stimulus.rates_hz`
that every `DECISION` record already carries — 564
decisions, 9,024 channel values — the largest
disagreement is **4.99e-05 Hz**, which is the
log's own four-decimal rounding. Nothing else differs.

| run / branch | episode | presented | channels differing by > 1e-9 Hz | largest channel Δ (Hz) | largest Δ excluding the two `age` channels | every non-`age` raw feature is exactly 0 | exact 1e-9 collisions |
|---|---|---|---|---|---|---|---|
| `d10-001/frozen_reference` | 4000000 | 4 | 16 | 43.7899 | 43.7899 | no | none |
| `d10-001/frozen_reference` | 36000009 | 6 | 16 | 0.509092 | 0.0596069 | yes | none |
| `d10-001/frozen_reference` | 68000016 | 6 | 16 | 0.0875973 | 0.0102563 | yes | none |
| `d10-001/frozen_reference` | 100000021 | 6 | 16 | 0.00079414 | 9.29818e-05 | yes | 2 |
| `d10-001/frozen_reference` | 132000030 | 6 | 16 | 0.000190224 | 2.22724e-05 | yes | 2 |
| `d10-001/frozen_reference` | 164000102 | 6 | 16 | 0.000133108 | 1.5585e-05 | yes | none |
| `d10-001/frozen_reference` | 196000173 | 6 | 16 | 0.00015585 | 1.82477e-05 | yes | none |
| `d10-001/frozen_reference` | 228000250 | 6 | 16 | 0.000160185 | 1.87552e-05 | yes | none |
| `d10-001/learning` | 4000000 | 4 | 16 | 43.7899 | 43.7899 | no | none |
| `d10-001/learning` | 36000009 | 6 | 16 | 0.509092 | 0.0596069 | yes | none |
| `d10-001/learning` | 68000017 | 6 | 16 | 0.0875973 | 0.0102563 | yes | none |
| `d10-001/learning` | 100000022 | 6 | 16 | 0.00079414 | 9.29818e-05 | yes | 2 |
| `d10-001/learning` | 132000028 | 6 | 16 | 0.000190224 | 2.22724e-05 | yes | 2 |
| `d10-001/learning` | 165000109 | 6 | 16 | 9.07029e-05 | 1.06199e-05 | yes | none |
| `d10-001/learning` | 203000217 | 6 | 16 | 0.000151678 | 1.77591e-05 | yes | none |
| `d10-live-001/live` | 7000087 | 6 | 16 | 0.000963992 | 0.000112869 | yes | none |
| `d10-live-001/live` | 72000315 | 6 | 16 | 0.00100589 | 0.000117775 | yes | 2 |

**What the recomputation says, exactly.**

1. In **15 of the 17** entry rounds every presented candidate's seven non-`age` raw
   features are **exactly** `0.0` — not rounded to zero, equal as floats — so the
   only coordinate that can separate two candidates in those rounds is `age`.
   Those are exactly the rounds whose entry failed the recency rule.
2. The rate vectors are **not** bit-identical at 1e-9 Hz, and the earlier reading
   overstated it. Because the drive is renormalised to a constant budget, a
   difference in `age` moves every channel a little. The correction is a matter of
   size: over the 15 inactive rounds the largest
   channel difference between any two presented candidates is
   **0.509 Hz**, and in
   **10 of those 15** it is below **0.001 Hz** — against a carrier of
   6.604 Hz and a `VL2a` of 66.042 Hz on the same vector. In the round whose entry
   *was* recent (tick 4, both replay branches) the largest channel difference is
   **43.79 Hz**, two to five orders
   of magnitude larger. That is the contrast the
   fly had in the round it could discriminate and did not have in the other fifteen.
3. **5 of the 17** rounds
   contain a pair of presented candidates whose rate vectors are equal at 1e-9 Hz
   outright — two tokens launched in the same second with empty windows encode
   identically. That is the design behaving as declared ("identical measured
   contexts encode identically"), and it is reported as a count, not repaired.
4. The recorded per-candidate scores in those same fifteen rounds still spread
   from **-4.93417** to **+4.52165**. That spread is the
   `comparison_v1` replicate schedule under
   near-identical drive; the two facts are readings of the same log and neither
   explains the other.

## 6. What this reconciliation does not say

It does not say the fly would have chosen well on richer inputs, it does not
re-read D10's losses, and it calls no token permanently dead. It establishes three
counts — **17 entries, 15 without
recent activity, 8 learning updates** — and one measurement: in
those fifteen rounds the deterministic drive differed between candidates by at most
**0.509 Hz** on any channel, and
in 10 of them by less than 0.001 Hz, against a
6.604 Hz carrier — while the one round with a recently traded candidate had
**43.79 Hz** of contrast on the same
scale. That gap is the defect D11 repairs.
