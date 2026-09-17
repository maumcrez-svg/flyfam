# D9(b) — target-alignment invariant (d9b-002)

**RETROSPECTIVE COMPARISON ON PREVIOUSLY EXAMINED DATES.** Nothing here books a number, moves a weight or rewrites an event.

Anchor: the **entry fill minute** + H = 90 market minutes, located by `flytrade.horizon.locate` — the one primitive the executed exit and the evaluator's `Hold` both call. Delay 1 market minute, unchanged.


## learned (LEARNING)

* episodes **28**, exact-H closures **28**, exceptional **0** 
* invariant compared on **28** episodes, same entry and exit bars on **28**, max |realised − label| = **2.220446049250313e-16** (tolerance 1e-09), max |as recorded − label| = 4.898696559507698e-09
* holding minutes: min 90, median 90.0, max 90, exactly H 28
* outcomes {'positive': 12, 'negative': 16, 'zero': 0}, reinforcement {'reward': 12, 'punishment': 16, 'none': 0, 'accepted': 28, 'settled_frozen': 0}
* money: gross at reference -28.5954, fees 27.9717, slippage 27.9717, net -84.5388

| episode | session | dec | entry | exit | held | reason | net | label | \|diff\| |
|---|---|---|---|---|---|---|---|---|---|
| 25000000 | 2026-07-06 | 24 | 25 | 115 | 90 | POLICY_CLOSE_FIXED_HOLD | +9.760030 | +9.760030 | 0.00e+00 |
| 119000000 | 2026-07-06 | 118 | 119 | 209 | 90 | POLICY_CLOSE_FIXED_HOLD | -1.865516 | -1.865516 | 0.00e+00 |
| 211000000 | 2026-07-06 | 210 | 211 | 301 | 90 | POLICY_CLOSE_FIXED_HOLD | -3.138366 | -3.138366 | 0.00e+00 |
| 413000000 | 2026-07-07 | 22 | 23 | 113 | 90 | POLICY_CLOSE_FIXED_HOLD | +13.708500 | +13.708500 | 0.00e+00 |
| 505000000 | 2026-07-07 | 114 | 115 | 205 | 90 | POLICY_CLOSE_FIXED_HOLD | +10.067428 | +10.067428 | 0.00e+00 |
| 597000000 | 2026-07-07 | 206 | 207 | 297 | 90 | POLICY_CLOSE_FIXED_HOLD | +0.671563 | +0.671563 | 2.22e-16 |
| 803000000 | 2026-07-08 | 22 | 23 | 113 | 90 | POLICY_CLOSE_FIXED_HOLD | +2.325249 | +2.325249 | 0.00e+00 |
| 896000000 | 2026-07-08 | 115 | 116 | 206 | 90 | POLICY_CLOSE_FIXED_HOLD | +6.073023 | +6.073023 | 0.00e+00 |
| 988000000 | 2026-07-08 | 207 | 208 | 298 | 90 | POLICY_CLOSE_FIXED_HOLD | -4.159937 | -4.159937 | 0.00e+00 |
| 1192000000 | 2026-07-09 | 21 | 22 | 112 | 90 | POLICY_CLOSE_FIXED_HOLD | +1.591755 | +1.591755 | 2.22e-16 |
| 1285000000 | 2026-07-09 | 114 | 115 | 205 | 90 | POLICY_CLOSE_FIXED_HOLD | -9.929236 | -9.929236 | 0.00e+00 |
| 1377000000 | 2026-07-09 | 206 | 207 | 297 | 90 | POLICY_CLOSE_FIXED_HOLD | +0.648689 | +0.648689 | 0.00e+00 |
| 1582000000 | 2026-07-10 | 21 | 22 | 112 | 90 | POLICY_CLOSE_FIXED_HOLD | -18.345216 | -18.345216 | 0.00e+00 |
| 1674000000 | 2026-07-10 | 113 | 114 | 204 | 90 | POLICY_CLOSE_FIXED_HOLD | -6.485953 | -6.485953 | 0.00e+00 |
| 1770000000 | 2026-07-10 | 209 | 210 | 300 | 90 | POLICY_CLOSE_FIXED_HOLD | -6.209112 | -6.209112 | 0.00e+00 |
| 1970000000 | 2026-07-13 | 20 | 21 | 111 | 90 | POLICY_CLOSE_FIXED_HOLD | +12.960074 | +12.960074 | 0.00e+00 |
| 2062000000 | 2026-07-13 | 112 | 113 | 203 | 90 | POLICY_CLOSE_FIXED_HOLD | -10.573541 | -10.573541 | 0.00e+00 |
| 2163000000 | 2026-07-13 | 213 | 214 | 304 | 90 | POLICY_CLOSE_FIXED_HOLD | -6.748052 | -6.748052 | 0.00e+00 |
| 2365000000 | 2026-07-14 | 25 | 26 | 116 | 90 | POLICY_CLOSE_FIXED_HOLD | -39.075676 | -39.075676 | 0.00e+00 |
| 2461000000 | 2026-07-14 | 121 | 122 | 212 | 90 | POLICY_CLOSE_FIXED_HOLD | +13.864674 | +13.864674 | 0.00e+00 |
| 2553000000 | 2026-07-14 | 213 | 214 | 304 | 90 | POLICY_CLOSE_FIXED_HOLD | +6.403693 | +6.403693 | 0.00e+00 |
| 2754000000 | 2026-07-15 | 24 | 25 | 115 | 90 | POLICY_CLOSE_FIXED_HOLD | -24.348745 | -24.348745 | 0.00e+00 |
| 2854000000 | 2026-07-15 | 124 | 125 | 215 | 90 | POLICY_CLOSE_FIXED_HOLD | -8.138756 | -8.138756 | 0.00e+00 |
| 2947000000 | 2026-07-15 | 217 | 218 | 308 | 90 | POLICY_CLOSE_FIXED_HOLD | -4.476554 | -4.476554 | 0.00e+00 |
| 3292000000 | 2026-07-16 | 172 | 173 | 263 | 90 | POLICY_CLOSE_FIXED_HOLD | +13.592745 | +13.592745 | 0.00e+00 |
| 3391000000 | 2026-07-16 | 271 | 272 | 362 | 90 | POLICY_CLOSE_FIXED_HOLD | -3.671723 | -3.671723 | 0.00e+00 |
| 3548000000 | 2026-07-17 | 38 | 39 | 129 | 90 | POLICY_CLOSE_FIXED_HOLD | -13.575621 | -13.575621 | 0.00e+00 |
| 3711000000 | 2026-07-17 | 201 | 202 | 292 | 90 | POLICY_CLOSE_FIXED_HOLD | -15.464239 | -15.464239 | 0.00e+00 |


## frozen_trained (FROZEN)

* episodes **13**, exact-H closures **13**, exceptional **0** 
* invariant compared on **13** episodes, same entry and exit bars on **13**, max |realised − label| = **0.0** (tolerance 1e-09), max |as recorded − label| = 4.8622350590221686e-09
* holding minutes: min 90, median 90.0, max 90, exactly H 13
* outcomes {'positive': 4, 'negative': 9, 'zero': 0}, reinforcement {'reward': 0, 'punishment': 0, 'none': 13, 'accepted': 0, 'settled_frozen': 13}
* money: gross at reference -4.7480, fees 12.9911, slippage 12.9911, net -30.7302

| episode | session | dec | entry | exit | held | reason | net | label | \|diff\| |
|---|---|---|---|---|---|---|---|---|---|
| 28000000 | 2026-07-20 | 27 | 28 | 118 | 90 | POLICY_CLOSE_FIXED_HOLD | -10.087456 | -10.087456 | 0.00e+00 |
| 167000000 | 2026-07-20 | 166 | 167 | 257 | 90 | POLICY_CLOSE_FIXED_HOLD | -3.183242 | -3.183242 | 0.00e+00 |
| 662000000 | 2026-07-21 | 271 | 272 | 362 | 90 | POLICY_CLOSE_FIXED_HOLD | -3.319270 | -3.319270 | 0.00e+00 |
| 806000000 | 2026-07-22 | 25 | 26 | 116 | 90 | POLICY_CLOSE_FIXED_HOLD | -1.737793 | -1.737793 | 0.00e+00 |
| 930000000 | 2026-07-22 | 149 | 150 | 240 | 90 | POLICY_CLOSE_FIXED_HOLD | -14.800295 | -14.800295 | 0.00e+00 |
| 1403000000 | 2026-07-23 | 232 | 233 | 323 | 90 | POLICY_CLOSE_FIXED_HOLD | +8.471458 | +8.471458 | 0.00e+00 |
| 1671000000 | 2026-07-24 | 110 | 111 | 201 | 90 | POLICY_CLOSE_FIXED_HOLD | -2.370372 | -2.370372 | 0.00e+00 |
| 2018000000 | 2026-07-27 | 67 | 68 | 158 | 90 | POLICY_CLOSE_FIXED_HOLD | -6.881367 | -6.881367 | 0.00e+00 |
| 2431000000 | 2026-07-28 | 90 | 91 | 181 | 90 | POLICY_CLOSE_FIXED_HOLD | +5.078463 | +5.078463 | 0.00e+00 |
| 2541000000 | 2026-07-28 | 200 | 201 | 291 | 90 | POLICY_CLOSE_FIXED_HOLD | -2.700133 | -2.700133 | 0.00e+00 |
| 2903000000 | 2026-07-29 | 172 | 173 | 263 | 90 | POLICY_CLOSE_FIXED_HOLD | -2.894781 | -2.894781 | 0.00e+00 |
| 3237000000 | 2026-07-30 | 116 | 117 | 207 | 90 | POLICY_CLOSE_FIXED_HOLD | +1.549360 | +1.549360 | 0.00e+00 |
| 3731000000 | 2026-07-31 | 220 | 221 | 311 | 90 | POLICY_CLOSE_FIXED_HOLD | +2.145191 | +2.145191 | 0.00e+00 |


## frozen_reference (FROZEN)

* episodes **32**, exact-H closures **32**, exceptional **0** 
* invariant compared on **32** episodes, same entry and exit bars on **32**, max |realised − label| = **2.220446049250313e-16** (tolerance 1e-09), max |as recorded − label| = 4.594523428380626e-09
* holding minutes: min 90, median 90.0, max 90, exactly H 32
* outcomes {'positive': 12, 'negative': 20, 'zero': 0}, reinforcement {'reward': 0, 'punishment': 0, 'none': 32, 'accepted': 0, 'settled_frozen': 32}
* money: gross at reference +81.4001, fees 32.0247, slippage 32.0247, net +17.3507

| episode | session | dec | entry | exit | held | reason | net | label | \|diff\| |
|---|---|---|---|---|---|---|---|---|---|
| 22000000 | 2026-07-20 | 21 | 22 | 112 | 90 | POLICY_CLOSE_FIXED_HOLD | -4.032415 | -4.032415 | 0.00e+00 |
| 116000000 | 2026-07-20 | 115 | 116 | 206 | 90 | POLICY_CLOSE_FIXED_HOLD | +22.662942 | +22.662942 | 0.00e+00 |
| 209000000 | 2026-07-20 | 208 | 209 | 299 | 90 | POLICY_CLOSE_FIXED_HOLD | -4.113277 | -4.113277 | 0.00e+00 |
| 414000000 | 2026-07-21 | 23 | 24 | 114 | 90 | POLICY_CLOSE_FIXED_HOLD | -6.348120 | -6.348120 | 0.00e+00 |
| 509000000 | 2026-07-21 | 118 | 119 | 209 | 90 | POLICY_CLOSE_FIXED_HOLD | +2.125593 | +2.125593 | 0.00e+00 |
| 601000000 | 2026-07-21 | 210 | 211 | 301 | 90 | POLICY_CLOSE_FIXED_HOLD | -1.337523 | -1.337523 | 2.22e-16 |
| 803000000 | 2026-07-22 | 22 | 23 | 113 | 90 | POLICY_CLOSE_FIXED_HOLD | -2.568407 | -2.568407 | 0.00e+00 |
| 901000000 | 2026-07-22 | 120 | 121 | 211 | 90 | POLICY_CLOSE_FIXED_HOLD | -10.782353 | -10.782353 | 0.00e+00 |
| 996000000 | 2026-07-22 | 215 | 216 | 306 | 90 | POLICY_CLOSE_FIXED_HOLD | -16.228336 | -16.228336 | 0.00e+00 |
| 1195000000 | 2026-07-23 | 24 | 25 | 115 | 90 | POLICY_CLOSE_FIXED_HOLD | +17.965090 | +17.965090 | 0.00e+00 |
| 1287000000 | 2026-07-23 | 116 | 117 | 207 | 90 | POLICY_CLOSE_FIXED_HOLD | -2.980287 | -2.980287 | 0.00e+00 |
| 1380000000 | 2026-07-23 | 209 | 210 | 300 | 90 | POLICY_CLOSE_FIXED_HOLD | -4.716010 | -4.716010 | 0.00e+00 |
| 1581000000 | 2026-07-24 | 20 | 21 | 111 | 90 | POLICY_CLOSE_FIXED_HOLD | +20.282189 | +20.282189 | 0.00e+00 |
| 1673000000 | 2026-07-24 | 112 | 113 | 203 | 90 | POLICY_CLOSE_FIXED_HOLD | -2.138326 | -2.138326 | 0.00e+00 |
| 1766000000 | 2026-07-24 | 205 | 206 | 296 | 90 | POLICY_CLOSE_FIXED_HOLD | +1.650593 | +1.650593 | 2.22e-16 |
| 1859000000 | 2026-07-24 | 298 | 299 | 389 | 90 | POLICY_CLOSE_FIXED_HOLD | -8.300738 | -8.300738 | 0.00e+00 |
| 1976000000 | 2026-07-27 | 25 | 26 | 116 | 90 | POLICY_CLOSE_FIXED_HOLD | -9.055706 | -9.055706 | 0.00e+00 |
| 2072000000 | 2026-07-27 | 121 | 122 | 212 | 90 | POLICY_CLOSE_FIXED_HOLD | -5.645257 | -5.645257 | 0.00e+00 |
| 2167000000 | 2026-07-27 | 216 | 217 | 307 | 90 | POLICY_CLOSE_FIXED_HOLD | -1.768613 | -1.768613 | 0.00e+00 |
| 2363000000 | 2026-07-28 | 22 | 23 | 113 | 90 | POLICY_CLOSE_FIXED_HOLD | +33.409138 | +33.409138 | 0.00e+00 |
| 2461000000 | 2026-07-28 | 120 | 121 | 211 | 90 | POLICY_CLOSE_FIXED_HOLD | +10.957633 | +10.957633 | 0.00e+00 |
| 2555000000 | 2026-07-28 | 214 | 215 | 305 | 90 | POLICY_CLOSE_FIXED_HOLD | -6.143878 | -6.143878 | 0.00e+00 |
| 2752000000 | 2026-07-29 | 21 | 22 | 112 | 90 | POLICY_CLOSE_FIXED_HOLD | +0.036499 | +0.036499 | 0.00e+00 |
| 2846000000 | 2026-07-29 | 115 | 116 | 206 | 90 | POLICY_CLOSE_FIXED_HOLD | -0.101632 | -0.101632 | 0.00e+00 |
| 2939000000 | 2026-07-29 | 208 | 209 | 299 | 90 | POLICY_CLOSE_FIXED_HOLD | +7.025853 | +7.025853 | 0.00e+00 |
| 3141000000 | 2026-07-30 | 20 | 21 | 111 | 90 | POLICY_CLOSE_FIXED_HOLD | -9.238413 | -9.238413 | 0.00e+00 |
| 3233000000 | 2026-07-30 | 112 | 113 | 203 | 90 | POLICY_CLOSE_FIXED_HOLD | +0.878663 | +0.878663 | 0.00e+00 |
| 3326000000 | 2026-07-30 | 205 | 206 | 296 | 90 | POLICY_CLOSE_FIXED_HOLD | -3.483326 | -3.483326 | 0.00e+00 |
| 3418000000 | 2026-07-30 | 297 | 298 | 388 | 90 | POLICY_CLOSE_FIXED_HOLD | -2.584156 | -2.584156 | 0.00e+00 |
| 3532000000 | 2026-07-31 | 21 | 22 | 112 | 90 | POLICY_CLOSE_FIXED_HOLD | -9.637930 | -9.637930 | 0.00e+00 |
| 3625000000 | 2026-07-31 | 114 | 115 | 205 | 90 | POLICY_CLOSE_FIXED_HOLD | +8.781284 | +8.781284 | 0.00e+00 |
| 3718000000 | 2026-07-31 | 207 | 208 | 298 | 90 | POLICY_CLOSE_FIXED_HOLD | +2.779925 | +2.779925 | 0.00e+00 |

