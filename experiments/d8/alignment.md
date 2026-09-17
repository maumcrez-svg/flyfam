# D8 — target-alignment audit

**RETROSPECTIVE DIAGNOSTIC — D7 RESULTS PREVIOUSLY OBSERVED**

The 42 actual LEARNING episodes of `d7-001`, beside the fixed-H = 90 quantity D7's evaluation scored. Read from the event log through `flytrade.records` parsing only.

> These counterfactuals reuse the original entry times. They do **not** simulate the trades a fixed-hold policy would actually have taken, because that policy changes inventory and later entry opportunities. Nothing here updates a weight, replays a reward, modifies an account or rewrites an original event, and no hypothetical outcome is booked as portfolio PnL. This audit measures **alignment**, not whether fixed-hold training would succeed.

| episode | information cutoff | entry | exit | reason | held, min | actual gross | actual net | reinf. | hyp. net at H=90 | hyp. Y |
|---|---|---|---|---|---:|---:|---:|:---:|---:|:---:|
| 25000000 | 2026-07-06 09:55 ET | 2026-07-06 09:55 ET | 2026-07-06 10:14 ET | NEURAL_SELL | 19 | +3.1369 | +2.1353 | + | +9.7600 | 1 |
| 45000000 | 2026-07-06 10:15 ET | 2026-07-06 10:15 ET | 2026-07-06 10:24 ET | NEURAL_SELL | 9 | +2.2740 | +1.2729 | + | +10.0092 | 1 |
| 56000000 | 2026-07-06 10:26 ET | 2026-07-06 10:26 ET | 2026-07-06 10:27 ET | NEURAL_SELL | 1 | +0.5177 | -0.4826 | − | +11.2106 | 1 |
| 59000000 | 2026-07-06 10:29 ET | 2026-07-06 10:29 ET | 2026-07-06 10:30 ET | NEURAL_SELL | 1 | +0.4986 | -0.5016 | − | +9.1891 | 1 |
| 62000000 | 2026-07-06 10:32 ET | 2026-07-06 10:32 ET | 2026-07-06 10:42 ET | NEURAL_SELL | 10 | -3.1840 | -4.1824 | − | +6.9696 | 1 |
| 73000000 | 2026-07-06 10:43 ET | 2026-07-06 10:43 ET | 2026-07-06 10:58 ET | NEURAL_SELL | 15 | +0.3499 | -0.6503 | − | +6.3076 | 1 |
| 90000000 | 2026-07-06 11:00 ET | 2026-07-06 11:00 ET | 2026-07-06 11:03 ET | NEURAL_SELL | 3 | -2.3268 | -3.3256 | − | +2.1497 | 1 |
| 96000000 | 2026-07-06 11:06 ET | 2026-07-06 11:06 ET | 2026-07-06 11:12 ET | NEURAL_SELL | 6 | -1.1677 | -2.1671 | − | +2.7087 | 1 |
| 107000000 | 2026-07-06 11:17 ET | 2026-07-06 11:17 ET | 2026-07-06 11:19 ET | NEURAL_SELL | 2 | -1.4371 | -2.4364 | − | +6.7229 | 1 |
| 110000000 | 2026-07-06 11:20 ET | 2026-07-06 11:20 ET | 2026-07-06 11:22 ET | NEURAL_SELL | 2 | -0.9995 | -1.9990 | − | +6.1110 | 1 |
| 115000000 | 2026-07-06 11:25 ET | 2026-07-06 11:25 ET | 2026-07-06 11:27 ET | NEURAL_SELL | 2 | -1.3849 | -2.3842 | − | +1.8192 | 1 |
| 118000000 | 2026-07-06 11:28 ET | 2026-07-06 11:28 ET | 2026-07-06 11:31 ET | NEURAL_SELL | 3 | +1.2422 | +0.2416 | + | -0.0427 | 0 |
| 126000000 | 2026-07-06 11:36 ET | 2026-07-06 11:36 ET | 2026-07-06 11:41 ET | NEURAL_SELL | 5 | +1.4572 | +0.4565 | + | +0.9743 | 1 |
| 140000000 | 2026-07-06 11:50 ET | 2026-07-06 11:50 ET | 2026-07-06 11:52 ET | NEURAL_SELL | 2 | +1.2492 | +0.2485 | + | -1.5162 | 0 |
| 144000000 | 2026-07-06 11:54 ET | 2026-07-06 11:54 ET | 2026-07-06 12:00 ET | NEURAL_SELL | 6 | -1.7819 | -2.7811 | − | -3.5631 | 0 |
| 152000000 | 2026-07-06 12:02 ET | 2026-07-06 12:02 ET | 2026-07-06 12:03 ET | NEURAL_SELL | 1 | -1.0661 | -2.0656 | − | -3.5637 | 0 |
| 158000000 | 2026-07-06 12:08 ET | 2026-07-06 12:08 ET | 2026-07-06 12:11 ET | NEURAL_SELL | 3 | -1.4834 | -2.4827 | − | -4.3840 | 0 |
| 173000000 | 2026-07-06 12:23 ET | 2026-07-06 12:23 ET | 2026-07-06 12:26 ET | NEURAL_SELL | 3 | -2.7506 | -3.7492 | − | -3.0022 | 0 |
| 177000000 | 2026-07-06 12:27 ET | 2026-07-06 12:27 ET | 2026-07-06 12:35 ET | NEURAL_SELL | 8 | -0.6996 | -1.6992 | − | -3.3571 | 0 |
| 188000000 | 2026-07-06 12:38 ET | 2026-07-06 12:38 ET | 2026-07-06 12:39 ET | NEURAL_SELL | 1 | -1.1168 | -2.1162 | − | -2.4510 | 0 |
| 190000000 | 2026-07-06 12:40 ET | 2026-07-06 12:40 ET | 2026-07-06 12:42 ET | NEURAL_SELL | 2 | -0.3300 | -1.3298 | − | -3.2370 | 0 |
| 198000000 | 2026-07-06 12:48 ET | 2026-07-06 12:48 ET | 2026-07-06 12:49 ET | NEURAL_SELL | 1 | -1.1284 | -2.1278 | − | -5.3821 | 0 |
| 217000000 | 2026-07-06 13:07 ET | 2026-07-06 13:07 ET | 2026-07-06 13:09 ET | NEURAL_SELL | 2 | -0.3000 | -1.2999 | − | -6.5932 | 0 |
| 227000000 | 2026-07-06 13:17 ET | 2026-07-06 13:17 ET | 2026-07-06 13:18 ET | NEURAL_SELL | 1 | -1.7650 | -2.7642 | − | -6.1408 | 0 |
| 230000000 | 2026-07-06 13:20 ET | 2026-07-06 13:20 ET | 2026-07-06 13:21 ET | NEURAL_SELL | 1 | -2.1316 | -3.1305 | − | -5.3437 | 0 |
| 240000000 | 2026-07-06 13:30 ET | 2026-07-06 13:30 ET | 2026-07-06 13:32 ET | NEURAL_SELL | 2 | -2.7146 | -3.7132 | − | -5.0780 | 0 |
| 256000000 | 2026-07-06 13:46 ET | 2026-07-06 13:46 ET | 2026-07-06 13:47 ET | NEURAL_SELL | 1 | -0.1960 | -1.1959 | − | -0.0915 | 0 |
| 266000000 | 2026-07-06 13:56 ET | 2026-07-06 13:56 ET | 2026-07-06 13:57 ET | NEURAL_SELL | 1 | -2.0889 | -3.0878 | − | +5.2040 | 1 |
| 447000000 | 2026-07-07 10:27 ET | 2026-07-07 10:27 ET | 2026-07-07 10:28 ET | NEURAL_SELL | 1 | +0.0377 | -0.9623 | − | +21.5813 | 1 |
| 513000000 | 2026-07-07 11:33 ET | 2026-07-07 11:33 ET | 2026-07-07 11:34 ET | NEURAL_SELL | 1 | +0.9746 | -0.0259 | − | +4.9876 | 1 |
| 597000000 | 2026-07-07 12:57 ET | 2026-07-07 12:57 ET | 2026-07-07 12:58 ET | NEURAL_SELL | 1 | -0.9512 | -1.9507 | − | +0.6716 | 1 |
| 662000000 | 2026-07-07 14:02 ET | 2026-07-07 14:02 ET | 2026-07-07 14:04 ET | NEURAL_SELL | 2 | -0.0847 | -1.0847 | − | -9.0087 | 0 |
| 911000000 | 2026-07-08 11:41 ET | 2026-07-08 11:41 ET | 2026-07-08 11:44 ET | NEURAL_SELL | 3 | -1.3816 | -2.3809 | − | +1.1727 | 1 |
| 997000000 | 2026-07-08 13:07 ET | 2026-07-08 13:07 ET | 2026-07-08 13:08 ET | NEURAL_SELL | 1 | -2.3707 | -3.3695 | − | -1.9990 | 0 |
| 1307000000 | 2026-07-09 11:47 ET | 2026-07-09 11:47 ET | 2026-07-09 11:48 ET | NEURAL_SELL | 1 | -0.8646 | -1.8641 | − | -10.4963 | 0 |
| 1363000000 | 2026-07-09 12:43 ET | 2026-07-09 12:43 ET | 2026-07-09 12:44 ET | NEURAL_SELL | 1 | -1.0504 | -2.0498 | − | -3.4734 | 0 |
| 1441000000 | 2026-07-09 14:01 ET | 2026-07-09 14:01 ET | 2026-07-09 14:02 ET | NEURAL_SELL | 1 | -0.9655 | -1.9650 | − | -0.7411 | 0 |
| 1455000000 | 2026-07-09 14:15 ET | 2026-07-09 14:15 ET | 2026-07-09 14:16 ET | NEURAL_SELL | 1 | -1.3390 | -2.3384 | − | -0.7434 | 0 |
| 1726000000 | 2026-07-10 12:16 ET | 2026-07-10 12:16 ET | 2026-07-10 12:17 ET | NEURAL_SELL | 1 | -0.8619 | -1.8614 | − | -3.7185 | 0 |
| 1798000000 | 2026-07-10 13:29 ET | 2026-07-10 13:29 ET | 2026-07-10 13:30 ET | NEURAL_SELL | 1 | -0.8271 | -1.8267 | − | -4.2221 | 0 |
| 1980000000 | 2026-07-13 10:01 ET | 2026-07-13 10:01 ET | 2026-07-13 10:03 ET | NEURAL_SELL | 2 | -3.1659 | -4.1643 | − | +8.1744 | 1 |
| 2062000000 | 2026-07-13 11:23 ET | 2026-07-13 11:23 ET | 2026-07-13 11:24 ET | NEURAL_SELL | 1 | -0.2666 | -1.2665 | − | -10.5735 | 0 |

## Summary

* **Episodes**: 42. Exit reasons: {'NEURAL_SELL': 42}.
* **Exits before H = 90**: 42 of 42; at or after H: 0.
* **Actual holding minutes**: min 1, median 2.0, max 19, total 131.
* **Actual outcome signs**: {'positive': 5, 'negative': 37, 'zero': 0}. Reinforcement: {'reward': 5, 'punishment': 37, 'none': 0}.
* **Hypothetical-label availability**: 42 available, 0 not ({}). Label counts {'Y=1': 18, 'Y=0': 24}.
* **Actual versus fixed-H signs**: 42 compared, 25 agree, 17 disagree — proportion disagreeing 0.4048. Disagreements by actual sign: {'actual_positive': 2, 'actual_negative': 15}; agreements: {'actual_positive': 3, 'actual_negative': 22}.
* **Costs**: 84 executions at 5.0 bps fee + 5.0 bps slippage each (20.0 bps nominal per round trip); fees 41.9838, slippage 41.9838, total cost 83.9676 against a gross at reference prices of +9.5396 and a net of -74.4280. Cost exceeded gross in 37 of 42 episodes.
* **Entry-fill identity**: the hypothetical entry equals the actual entry on 42 of 42 episodes at the reference price and 42 of 42 after the unchanged slippage; max |difference| 0.00e+00.
* The hypothetical net outcomes are **not** summed into a portfolio PnL and are booked nowhere.
