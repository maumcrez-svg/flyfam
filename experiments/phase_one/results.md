# Phase One — results

Produced by the scripts in this directory against the real connectome. Every number is generated; nothing is hand-entered.

* graph `8feb08a0d2a8` · encoder `flytrade-encoder-1` · decoder `flytrade-action-1` · runner `flytrade-runner-1` · execution `flytrade-exec-1` · plasticity `flytrade-mb-1`
* gain 0.1 (D2, frozen), drive budget 12,000 Hz, carrier 0.1, 100-step (20 ms) window
* operating-range measurements: `docs/ENCODER.md` and `encoder_range.json`
* decoder specification: `docs/DECODER.md`, pre-registered alone at commit `f63825b`
* python 3.13.9, numpy 2.4.2

## §4 — does reinforcement reach the decoder?

`learning_demo.py`, writing `learning.json`. Both branches, four controls, eight seeds, twenty trials. No price, no position, no PnL: the reinforcement valence is delivered directly as an experimental variable.

Readout: 29 `avoid` + 16 `approach` neurons. One spike in the 20 ms window is worth 1.724 Hz of `avoid` and 3.125 Hz of `approach`; that quantum is the whole story of v1 below.

### v1 — the protocol as pre-registered, and its failure

#### Contexts (v1) — first usable cutoff at or after bar 300

Kenyon-cell Jaccard between X and Y: **0.511**

* **X** = `CTXX` at bar 300: approach 9.38 Hz, avoid 12.07 Hz, V -0.391 Hz, decoded **WAIT**, Kenyon fraction 0.0330
* **Y** = `CTXY` at bar 300: approach 6.25 Hz, avoid 10.34 Hz, V -1.791 Hz, decoded **WAIT**, Kenyon fraction 0.0320

#### Table — the decoder's output, before and after 20 trials (v1, mean over 8 seeds)

| condition | trained on | dV(X) Hz | d approach(X) Hz | d avoid(X) Hz | dV(Y) Hz | seeds whose action changed | synapses moved PAM / PPL1 |
|---|---|--:|--:|--:|--:|--:|---|
| `APPETITIVE_ON` | CTXX | +2.761 | +0.391 | -2.371 | +1.078 | 2/8 | 1,463 / 0 |
| `APPETITIVE_OFF` | CTXX | +0.000 | +0.000 | +0.000 | +0.000 | 0/8 | 0 / 0 |
| `AVERSIVE_ON` | CTXX | -0.310 | -1.172 | -0.862 | +0.256 | 0/8 | 0 / 1,156 |
| `AVERSIVE_OFF` | CTXX | +0.000 | +0.000 | +0.000 | +0.000 | 0/8 | 0 / 0 |
| `APPETITIVE_OTHER` | CTXY | +3.408 | +0.391 | -3.017 | +2.155 | 4/8 | 2,044 / 0 |
| `AVERSIVE_OTHER` | CTXY | -0.700 | -1.562 | -0.862 | -0.525 | 1/8 | 0 / 1,608 |

#### Table — dV(X) per seed (v1)

| seed | `APPETITIVE_ON` | `APPETITIVE_OFF` | `AVERSIVE_ON` | `AVERSIVE_OFF` | `APPETITIVE_OTHER` | `AVERSIVE_OTHER` |
|--:|--:|--:|--:|--:|--:|--:|
| 1 | +6.573 | +0.000 | -2.478 | +0.000 | +8.297 | -2.478 |
| 2 | +5.172 | +0.000 | +0.000 | +0.000 | +6.897 | +0.000 |
| 3 | +5.172 | +0.000 | +0.000 | +0.000 | +5.172 | +0.000 |
| 4 | +5.172 | +0.000 | +0.000 | +0.000 | +6.897 | -3.125 |
| 5 | +0.000 | +0.000 | +0.000 | +0.000 | +0.000 | +0.000 |
| 6 | +0.000 | +0.000 | +0.000 | +0.000 | +0.000 | +0.000 |
| 7 | +0.000 | +0.000 | +0.000 | +0.000 | +0.000 | +0.000 |
| 8 | +0.000 | +0.000 | +0.000 | +0.000 | +0.000 | +0.000 |

#### Table — the decision rule (v1)

| check | prediction | seeds | threshold | verdict |
|---|---|--:|--:|:--|
| appetitive reaches the decoder | dV(X) > 0 under APPETITIVE_ON | 4/8 | 7/8 | **FAIL** |
| aversive reaches the decoder | dV(X) < 0 under AVERSIVE_ON | 1/8 | 7/8 | **FAIL** |
| plasticity off, appetitive | dV(X) == 0 exactly | 8/8 | 8/8 | PASS |
| plasticity off, aversive | dV(X) == 0 exactly | 8/8 | 8/8 | PASS |
| depends on the eligible experience, appetitive | dV(X)[ON] - dV(X)[OTHER] > 0 | 0/8 | 7/8 | **FAIL** |
| depends on the eligible experience, aversive | dV(X)[ON] - dV(X)[OTHER] < 0 | 0/8 | 7/8 | **FAIL** |

**Verdict (v1): FAIL.** Stimulus specificity, mean over seeds: appetitive -0.647 Hz, aversive +0.391 Hz.

### v2 — declared deviation: contrast-selected contexts, measurement averaged over 8 presentations

#### Contexts (v2) — extreme r20 over bars 200..420 of 4 instruments

Kenyon-cell Jaccard between X and Y: **0.287**

* **X** = `CTX3` at bar 218: approach 10.16 Hz, avoid 11.21 Hz, V +1.253 Hz, decoded **WAIT**, Kenyon fraction 0.0425
* **Y** = `CTX1` at bar 409: approach 6.64 Hz, avoid 7.33 Hz, V +1.616 Hz, decoded **WAIT**, Kenyon fraction 0.0273

#### Table — the decoder's output, before and after 20 trials (v2, mean over 8 seeds)

| condition | trained on | dV(X) Hz | d approach(X) Hz | d avoid(X) Hz | dV(Y) Hz | seeds whose action changed | synapses moved PAM / PPL1 |
|---|---|--:|--:|--:|--:|--:|---|
| `APPETITIVE_ON` | CTX3 | +5.071 | +0.195 | -4.876 | +2.780 | 6/8 | 2,680 / 0 |
| `APPETITIVE_OFF` | CTX3 | +0.000 | +0.000 | +0.000 | +0.000 | 0/8 | 0 / 0 |
| `AVERSIVE_ON` | CTX3 | -4.477 | -4.639 | -0.162 | -2.382 | 4/8 | 0 / 2,052 |
| `AVERSIVE_OFF` | CTX3 | +0.000 | +0.000 | +0.000 | +0.000 | 0/8 | 0 / 0 |
| `APPETITIVE_OTHER` | CTX1 | +3.061 | +0.098 | -2.963 | +1.950 | 2/8 | 1,842 / 0 |
| `AVERSIVE_OTHER` | CTX1 | -2.495 | -2.441 | +0.054 | -1.850 | 2/8 | 0 / 1,366 |

#### Table — dV(X) per seed (v2)

| seed | `APPETITIVE_ON` | `APPETITIVE_OFF` | `AVERSIVE_ON` | `AVERSIVE_OFF` | `APPETITIVE_OTHER` | `AVERSIVE_OTHER` |
|--:|--:|--:|--:|--:|--:|--:|
| 1 | +6.250 | +0.000 | -5.738 | +0.000 | +4.310 | -1.994 |
| 2 | +4.485 | +0.000 | -2.344 | +0.000 | +2.546 | -1.172 |
| 3 | +3.839 | +0.000 | -1.172 | +0.000 | +2.977 | -0.781 |
| 4 | +3.017 | +0.000 | -1.953 | +0.000 | +1.940 | -1.172 |
| 5 | +7.287 | +0.000 | -7.031 | +0.000 | +3.879 | -3.516 |
| 6 | +5.388 | +0.000 | -5.078 | +0.000 | +3.448 | -3.906 |
| 7 | +4.526 | +0.000 | -3.906 | +0.000 | +2.155 | -2.344 |
| 8 | +5.779 | +0.000 | -8.594 | +0.000 | +3.233 | -5.078 |

#### Table — the decision rule (v2)

| check | prediction | seeds | threshold | verdict |
|---|---|--:|--:|:--|
| appetitive reaches the decoder | dV(X) > 0 under APPETITIVE_ON | 8/8 | 7/8 | PASS |
| aversive reaches the decoder | dV(X) < 0 under AVERSIVE_ON | 8/8 | 7/8 | PASS |
| plasticity off, appetitive | dV(X) == 0 exactly | 8/8 | 8/8 | PASS |
| plasticity off, aversive | dV(X) == 0 exactly | 8/8 | 8/8 | PASS |
| depends on the eligible experience, appetitive | dV(X)[ON] - dV(X)[OTHER] > 0 | 8/8 | 7/8 | PASS |
| depends on the eligible experience, aversive | dV(X)[ON] - dV(X)[OTHER] < 0 | 8/8 | 7/8 | PASS |

**Verdict (v2): PASS.** Stimulus specificity, mean over seeds: appetitive +2.010 Hz, aversive -1.982 Hz.

### Reading it honestly

* Phase 0.5's `UNPAIRED` control is **not** repeated and is not cited. It is zero by construction and the reviewer of that wave recorded that it is not on its own evidence of associative selectivity. The controls that carry weight are the two `_OFF` conditions (plasticity disabled, identical schedule and seeds) and the two `_OTHER` conditions (real weight change, driven by a different market context).
* The `_OTHER` conditions do move X. Contexts share Kenyon cells, so a synapse depressed for one is depressed for the other. The specificity claim is that X moves *more* when X is the reinforced context, never that the other context leaves X untouched.
* A changed weight and a changed counter are not the claim. The claim is that the same market context, presented to the same fixed decoder at the same measurement seeds, decodes differently after reinforcement than before.

## §5 — episode-specific credit assignment

`credit_demo.py`, writing `credit.json`. The amendment's own scenario: evaluate A, then B, select A, settle A. Reinforcement reaches the selected episode's **stored** trace (Fable addendum 6), which is then discarded and the episode closed.

Round 11, seed 555, both instruments observed at bar 300. A is selected by construction so the demonstration controls which episode is open.

| candidate | stable id | episode id | Poisson seed | Kenyon cells active | eligible synapses | V Hz | decoded |
|---|--:|--:|--:|--:|--:|--:|---|
| `AAA` **selected** | 0 | 11000000 | 1453158519 | 98 | 1,161 | -1.468 | WAIT |
| `BBB` | 1 | 11000001 | 903030395 | 365 | 4,126 | +7.691 | BUY |

Eligible synapses: 65 only A, 3,030 only B, 1,096 shared. The 3,030 that are B's alone are what makes the two traces distinguishable at all.

| offer | accepted | reason | synapses depressed | weights moved |
|---|:--|---|--:|--:|
| B's trace, offered against A's episode | no | EPISODE_MISMATCH | 0 | 0 |
| B's own episode, never opened | no | UNKNOWN_EPISODE | 0 | 0 |
| A's trace, decayed below the eligibility threshold | no | TRACE_EXPIRED | 0 | 0 |
| A's trace, captured against a different synapse set | no | SHAPE_MISMATCH | 0 | 0 |
| A's own stored trace | **yes** | — | 525 | 525 |
| A again, already settled | no | ALREADY_SETTLED | 0 | 0 |

The accepted event moved **525** synapses. They are exactly A's own eligible synapses in the addressed compartment: set equality True, 0 of them eligible only under B, 0 on the unaddressed side. `eligibility_source` = `replayed_from_decision`.

Counters: 1 accepted, 5 rejected — EPISODE_MISMATCH 1, ALREADY_SETTLED 1, UNKNOWN_EPISODE 1, TRACE_EXPIRED 1, SHAPE_MISMATCH 1. Open episodes afterwards: none.

## §6 and §8 — the vertical slice, end to end

`run_demo.py`, writing `demo.json`. Six seeded synthetic instruments, one persistent learned brain, one open position at a time, the execution fixture of `docs/EXECUTION.md` exactly as declared. No profitability threshold is claimed or sought.

6 instruments, bars 80-400, 558 presentations of 20 ms.

| | |
|---|--:|
| completed decision/outcome cycles | 33 |
| closed by a neural SELL | 6 |
| closed by the horizon (POLICY_CLOSE) | 27 |
| closed at end of data | 0 |
| wins / losses / flat | 19 / 14 / 0 |
| gross PnL | +25.06 |
| fees paid | 33.01 |
| **net realised PnL** | **-7.95** |
| cash | 9992.05 |
| reinforcements accepted | 33 |
| reinforcements rejected | 0 |
| execution rejections | 0  |
| event-log entries | 773 |

Decoder output over every round (a single 20 ms presentation each):

| `BUY` | `NO_RESPONSE` | `SELL` | `WAIT` |
|--:|--:|--:|--:|
| 133 | 60 | 6 | 120 |

Readout status over every round:

| `NO_CANDIDATE` | `NO_RESPONSE` | `VALID` |
|--:|--:|--:|
| 6 | 60 | 259 |

### Chronological trace

`u` is the normalised feature vector `(r1, r5, r20, rv20, relvol)` the encoder saw; `V` the centred valence the fixed decoder computed; `eligible` the synapses the presentation made eligible; `depressed` the ones the outcome's dopamine event actually moved.

```
bar  80  BUY  SYN02  u=[0.071, -0.297, -0.181, 0.62, 0.593]
          readout approach  53.12 Hz  avoid  37.93 Hz -> V +17.497  (557 Kenyon cells, 6,171 eligible synapses)
          selected from 6 candidates {'SYN00': 3.06, 'SYN01': 0.26, 'SYN02': 17.5, 'SYN03': 5.97, 'SYN04': -3.19, 'SYN05': 4.46}, filled at 103.198
bar  89  POLICY_CLOSE  SYN02  held 9 bars  103.198 -> 104.3615  net +10.269 (+1.0270%)
          dopamine PAM x1.000 -> 3,501 synapses depressed, 3,501 weights moved; cash 10010.27
          same context, same seed: V +17.497 at entry -> +19.221 now (BUY)
bar  90  BUY  SYN03  u=[0.558, 0.289, 0.171, 0.421, -0.185]
          readout approach  34.38 Hz  avoid  20.69 Hz -> V +15.989  (447 Kenyon cells, 5,005 eligible synapses)
          selected from 6 candidates {'SYN00': -1.47, 'SYN01': -3.19, 'SYN02': -3.19, 'SYN03': 15.99, 'SYN04': -0.07, 'SYN05': 8.66}, filled at 109.5374
bar  99  POLICY_CLOSE  SYN03  held 9 bars  109.5374 -> 110.7406  net +9.978 (+0.9980%)
          dopamine PAM x0.998 -> 2,828 synapses depressed, 2,828 weights moved; cash 10020.25
          same context, same seed: V +15.989 at entry -> +15.989 now (BUY)
bar 100  BUY  SYN03  u=[0.45, 0.387, 0.062, 0.007, -0.026]
          readout approach  62.50 Hz  avoid  44.83 Hz -> V +19.976  (629 Kenyon cells, 6,945 eligible synapses)
          selected from 6 candidates {'SYN00': 2.73, 'SYN02': 10.82, 'SYN03': 19.98, 'SYN04': 14.91}, filled at 111.4051
bar 109  POLICY_CLOSE  SYN03  held 9 bars  111.4051 -> 112.3267  net +7.269 (+0.7270%)
          dopamine PAM x0.727 -> 3,920 synapses depressed, 3,920 weights moved; cash 10027.52
          same context, same seed: V +19.976 at entry -> +19.976 now (BUY)
bar 109  RESTART  nothing to do; last settled episode 100000003; gains restored exactly: True
bar 110  BUY  SYN02  u=[-0.502, 0.157, 0.141, 0.1, 0.391]
          readout approach  53.12 Hz  avoid  34.48 Hz -> V +20.946  (561 Kenyon cells, 6,226 eligible synapses)
          selected from 6 candidates {'SYN00': 7.91, 'SYN02': 20.95, 'SYN03': 17.07}, filled at 105.7403
bar 119  POLICY_CLOSE  SYN02  held 9 bars  105.7403 -> 105.5559  net -2.743 (-0.2740%)
          dopamine PPL1 x0.274 -> 2,708 synapses depressed, 2,708 weights moved; cash 10024.77
          same context, same seed: V +20.946 at entry -> +20.946 now (BUY)
bar 120  BUY  SYN02  u=[0.662, 0.149, 0.143, 0.066, -0.292]
          readout approach  40.62 Hz  avoid  31.03 Hz -> V +11.894  (533 Kenyon cells, 5,985 eligible synapses)
          selected from 6 candidates {'SYN00': 4.46, 'SYN01': 1.33, 'SYN02': 11.89, 'SYN03': 0.26, 'SYN04': -1.47}, filled at 106.4012
bar 129  POLICY_CLOSE  SYN02  held 9 bars  106.4012 -> 101.5238  net -46.816 (-4.6820%)
          dopamine PPL1 x1.000 -> 2,616 synapses depressed, 2,616 weights moved; cash 9977.96
          same context, same seed: V +11.894 at entry -> +8.769 now (BUY)
bar 131  BUY  SYN02  u=[-0.704, -0.827, -0.921, 0.864, 0.204]
          readout approach  12.50 Hz  avoid   8.62 Hz -> V  +6.183  (155 Kenyon cells, 1,808 eligible synapses)
          selected from 6 candidates {'SYN00': -2.87, 'SYN02': 6.18, 'SYN03': 1.98}, filled at 100.3621
bar 140  POLICY_CLOSE  SYN02  held 9 bars  100.3621 -> 97.4058  net -30.442 (-3.0440%)
          dopamine PPL1 x1.000 -> 807 synapses depressed, 807 weights moved; cash 9947.51
          same context, same seed: V +6.183 at entry -> -0.067 now (WAIT)
bar 141  BUY  SYN02  u=[0.53, 0.753, -0.645, 0.754, -0.274]
          readout approach  28.12 Hz  avoid  20.69 Hz -> V  +9.739  (348 Kenyon cells, 3,914 eligible synapses)
          selected from 6 candidates {'SYN00': -0.07, 'SYN01': 0.26, 'SYN02': 9.74, 'SYN03': -3.19, 'SYN05': 0.26}, filled at 98.2476
bar 150  POLICY_CLOSE  SYN02  held 9 bars  98.2476 -> 97.8381  net -5.166 (-0.5170%)
          dopamine PPL1 x0.517 -> 1,716 synapses depressed, 1,716 weights moved; cash 9942.35
          same context, same seed: V +9.739 at entry -> +9.739 now (BUY)
bar 151  BUY  SYN02  u=[0.915, 0.15, 0.275, 0.688, 0.417]
          readout approach  28.12 Hz  avoid  20.69 Hz -> V  +9.739  (425 Kenyon cells, 4,800 eligible synapses)
          selected from 6 candidates {'SYN00': 1.98, 'SYN01': 0.58, 'SYN02': 9.74, 'SYN03': -4.59, 'SYN04': 0.58, 'SYN05': 6.94}, filled at 100.6274
bar 160  POLICY_CLOSE  SYN02  held 9 bars  100.6274 -> 94.6913  net -59.962 (-5.9960%)
          dopamine PPL1 x1.000 -> 2,082 synapses depressed, 2,082 weights moved; cash 9882.39
          same context, same seed: V +9.739 at entry -> +6.614 now (BUY)
bar 161  BUY  SYN03  u=[-0.551, 0.232, -0.25, 0.488, 0.689]
          readout approach  34.38 Hz  avoid  24.14 Hz -> V +12.540  (417 Kenyon cells, 4,672 eligible synapses)
          selected from 6 candidates {'SYN00': -1.14, 'SYN01': -0.39, 'SYN03': 12.54, 'SYN05': 5.21}, filled at 94.918
bar 170  POLICY_CLOSE  SYN03  held 9 bars  94.918 -> 94.7319  net -2.960 (-0.2960%)
          dopamine PPL1 x0.296 -> 2,029 synapses depressed, 2,029 weights moved; cash 9879.43
          same context, same seed: V +12.540 at entry -> +12.540 now (BUY)
bar 171  BUY  SYN03  u=[-0.789, -0.332, 0.184, 0.176, 0.631]
          readout approach  40.62 Hz  avoid  31.03 Hz -> V +11.894  (533 Kenyon cells, 5,952 eligible synapses)
          selected from 6 candidates {'SYN01': 3.49, 'SYN02': -1.47, 'SYN03': 11.89, 'SYN05': -6.64}, filled at 92.6499
bar 178  NEURAL_SELL  SYN03  held 7 bars  92.6499 -> 93.0497  net +3.313 (+0.3310%)
          dopamine PAM x0.331 -> 3,363 synapses depressed, 3,363 weights moved; cash 9882.74
          same context, same seed: V +11.894 at entry -> +13.618 now (BUY)
bar 179  BUY  SYN03  u=[0.724, 0.688, 0.69, 0.464, -0.15]
          readout approach  25.00 Hz  avoid  22.41 Hz -> V  +4.890  (334 Kenyon cells, 3,819 eligible synapses)
          selected from 6 candidates {'SYN00': 0.58, 'SYN01': 2.41, 'SYN02': -1.14, 'SYN03': 4.89}, filled at 94.5159
bar 188  POLICY_CLOSE  SYN03  held 9 bars  94.5159 -> 92.2131  net -25.352 (-2.5350%)
          dopamine PPL1 x1.000 -> 1,667 synapses depressed, 1,667 weights moved; cash 9857.39
          same context, same seed: V +4.890 at entry -> +4.890 now (BUY)
bar 190  BUY  SYN03  u=[0.901, 0.639, 0.707, 0.965, 0.82]
          readout approach  31.25 Hz  avoid  25.86 Hz -> V  +7.691  (498 Kenyon cells, 5,581 eligible synapses)
          selected from 6 candidates {'SYN00': 1.33, 'SYN01': 1.98, 'SYN03': 7.69, 'SYN05': -6.64}, filled at 94.7791
bar 197  NEURAL_SELL  SYN03  held 7 bars  94.7791 -> 92.036  net -29.928 (-2.9930%)
          dopamine PPL1 x1.000 -> 2,420 synapses depressed, 2,420 weights moved; cash 9827.46
          same context, same seed: V +7.691 at entry -> +7.691 now (BUY)
bar 199  BUY  SYN02  u=[0.26, 0.05, 0.193, -0.603, 0.359]
          readout approach  37.50 Hz  avoid  36.21 Hz -> V  +3.596  (533 Kenyon cells, 5,950 eligible synapses)
          selected from 6 candidates {'SYN00': -5.24, 'SYN01': -1.47, 'SYN02': 3.6, 'SYN04': -1.14, 'SYN05': -4.59}, filled at 97.5558
bar 208  POLICY_CLOSE  SYN02  held 9 bars  97.5558 -> 101.2485  net +36.834 (+3.6830%)
          dopamine PAM x1.000 -> 3,370 synapses depressed, 3,370 weights moved; cash 9864.29
          same context, same seed: V +3.596 at entry -> +7.368 now (BUY)
bar 210  BUY  SYN02  u=[-0.213, 0.5, 0.424, 0.021, 0.72]
          readout approach  25.00 Hz  avoid  22.41 Hz -> V  +4.890  (446 Kenyon cells, 4,986 eligible synapses)
          selected from 6 candidates {'SYN02': 4.89, 'SYN05': -0.07}, filled at 101.745
bar 216  NEURAL_SELL  SYN02  held 6 bars  101.745 -> 101.6004  net -2.421 (-0.2420%)
          dopamine PPL1 x0.242 -> 2,167 synapses depressed, 2,167 weights moved; cash 9861.87
          same context, same seed: V +4.890 at entry -> +4.890 now (BUY)
bar 217  BUY  SYN04  u=[-0.067, -0.58, -0.628, 0.182, -0.292]
          readout approach  15.62 Hz  avoid  13.79 Hz -> V  +4.135  (282 Kenyon cells, 3,233 eligible synapses)
          selected from 6 candidates {'SYN00': -1.47, 'SYN03': 3.49, 'SYN04': 4.14, 'SYN05': 3.81}, filled at 110.4405
bar 226  POLICY_CLOSE  SYN04  held 9 bars  110.4405 -> 110.8689  net +2.877 (+0.2880%)
          dopamine PAM x0.288 -> 1,824 synapses depressed, 1,824 weights moved; cash 9864.75
          same context, same seed: V +4.135 at entry -> +4.135 now (BUY)
bar 227  BUY  SYN00  u=[0.308, 0.412, 0.046, -0.864, -0.09]
          readout approach  15.62 Hz  avoid  12.07 Hz -> V  +5.859  (388 Kenyon cells, 4,388 eligible synapses)
          selected from 6 candidates {'SYN00': 5.86, 'SYN02': 1.01, 'SYN03': 4.57, 'SYN04': -1.14, 'SYN05': -3.19}, filled at 83.5071
bar 236  POLICY_CLOSE  SYN00  held 9 bars  83.5071 -> 85.3919  net +21.558 (+2.1560%)
          dopamine PAM x1.000 -> 2,478 synapses depressed, 2,478 weights moved; cash 9886.31
          same context, same seed: V +5.859 at entry -> +5.859 now (BUY)
bar 238  BUY  SYN02  u=[0.292, -0.011, 0.409, -0.824, 0.395]
          readout approach  31.25 Hz  avoid  17.24 Hz -> V +16.312  (441 Kenyon cells, 4,922 eligible synapses)
          selected from 6 candidates {'SYN02': 16.31, 'SYN03': 9.09, 'SYN04': -1.14, 'SYN05': 0.26}, filled at 105.8189
bar 247  POLICY_CLOSE  SYN02  held 9 bars  105.8189 -> 107.8616  net +18.294 (+1.8290%)
          dopamine PAM x1.000 -> 2,784 synapses depressed, 2,784 weights moved; cash 9904.6
          same context, same seed: V +16.312 at entry -> +13.187 now (BUY)
bar 248  BUY  SYN02  u=[0.048, 0.394, 0.064, -0.64, -0.323]
          readout approach  21.88 Hz  avoid  17.24 Hz -> V  +6.937  (335 Kenyon cells, 3,870 eligible synapses)
          selected from 6 candidates {'SYN00': -1.47, 'SYN02': 6.94, 'SYN03': 1.01, 'SYN04': -1.14}, filled at 108.285
bar 252  NEURAL_SELL  SYN02  held 4 bars  108.285 -> 108.392  net -0.012 (-0.0010%)
          dopamine PPL1 x0.001 -> 1,700 synapses depressed, 1,700 weights moved; cash 9904.59
          same context, same seed: V +6.937 at entry -> +6.937 now (BUY)
bar 253  BUY  SYN04  u=[0.178, 0.098, 0.072, -0.471, 0.473]
          readout approach  37.50 Hz  avoid  24.14 Hz -> V +15.665  (488 Kenyon cells, 5,465 eligible synapses)
          selected from 6 candidates {'SYN00': -1.14, 'SYN01': -2.87, 'SYN02': 1.66, 'SYN03': 11.14, 'SYN04': 15.67, 'SYN05': 2.41}, filled at 109.7627
bar 262  POLICY_CLOSE  SYN04  held 9 bars  109.7627 -> 107.299  net -23.434 (-2.3430%)
          dopamine PPL1 x1.000 -> 2,377 synapses depressed, 2,377 weights moved; cash 9881.16
          same context, same seed: V +15.665 at entry -> +12.540 now (BUY)
bar 263  BUY  SYN04  u=[0.541, -0.14, -0.349, -0.187, 0.375]
          readout approach  18.75 Hz  avoid  13.79 Hz -> V  +7.260  (294 Kenyon cells, 3,362 eligible synapses)
          selected from 6 candidates {'SYN01': -1.79, 'SYN02': 5.64, 'SYN03': -6.64, 'SYN04': 7.26, 'SYN05': 1.98}, filled at 108.3232
bar 272  POLICY_CLOSE  SYN04  held 9 bars  108.3232 -> 110.0499  net +14.932 (+1.4930%)
          dopamine PAM x1.000 -> 1,889 synapses depressed, 1,889 weights moved; cash 9896.09
          same context, same seed: V +7.260 at entry -> +7.260 now (BUY)
bar 273  BUY  SYN05  u=[0.416, -0.243, -0.134, 0.471, 0.299]
          readout approach  28.12 Hz  avoid  18.97 Hz -> V +11.463  (442 Kenyon cells, 5,041 eligible synapses)
          selected from 6 candidates {'SYN01': -1.14, 'SYN02': 3.06, 'SYN03': -4.59, 'SYN05': 11.46}, filled at 77.9903
bar 277  NEURAL_SELL  SYN05  held 4 bars  77.9903 -> 79.1771  net +14.210 (+1.4210%)
          dopamine PAM x1.000 -> 2,840 synapses depressed, 2,840 weights moved; cash 9910.3
          same context, same seed: V +11.463 at entry -> +11.463 now (BUY)
bar 278  BUY  SYN03  u=[0.304, -0.378, -0.538, 0.192, -0.671]
          readout approach  28.12 Hz  avoid  18.97 Hz -> V +11.463  (502 Kenyon cells, 5,624 eligible synapses)
          selected from 6 candidates {'SYN00': -1.14, 'SYN01': 0.58, 'SYN02': 10.82, 'SYN03': 11.46, 'SYN05': -3.19}, filled at 94.0717
bar 286  NEURAL_SELL  SYN03  held 8 bars  94.0717 -> 94.7962  net +6.697 (+0.6700%)
          dopamine PAM x0.670 -> 3,185 synapses depressed, 3,185 weights moved; cash 9917.0
          same context, same seed: V +11.463 at entry -> +13.187 now (BUY)
bar 287  BUY  SYN02  u=[0.21, 0.34, -0.212, 0.143, 0.326]
          readout approach  34.38 Hz  avoid  22.41 Hz -> V +14.265  (473 Kenyon cells, 5,256 eligible synapses)
          selected from 6 candidates {'SYN00': 0.58, 'SYN01': -0.07, 'SYN02': 14.26}, filled at 106.8571
bar 296  POLICY_CLOSE  SYN02  held 9 bars  106.8571 -> 106.6023  net -3.383 (-0.3380%)
          dopamine PPL1 x0.338 -> 2,278 synapses depressed, 2,278 weights moved; cash 9913.61
          same context, same seed: V +14.265 at entry -> +11.140 now (BUY)
bar 297  BUY  SYN01  u=[-0.145, 0.403, -0.52, -0.459, 0.683]
          readout approach  12.50 Hz  avoid   8.62 Hz -> V  +6.183  (260 Kenyon cells, 2,991 eligible synapses)
          selected from 6 candidates {'SYN01': 6.18, 'SYN02': 0.26, 'SYN03': -1.47}, filled at 83.1263
bar 306  POLICY_CLOSE  SYN01  held 9 bars  83.1263 -> 82.685  net -6.306 (-0.6310%)
          dopamine PPL1 x0.631 -> 1,320 synapses depressed, 1,320 weights moved; cash 9907.31
          same context, same seed: V +6.183 at entry -> -0.067 now (WAIT)
bar 308  BUY  SYN00  u=[-0.026, -0.582, -0.577, -0.718, 0.736]
          readout approach   9.38 Hz  avoid   6.90 Hz -> V  +4.782  (215 Kenyon cells, 2,480 eligible synapses)
          selected from 6 candidates {'SYN00': 4.78, 'SYN01': 1.33, 'SYN03': 0.58, 'SYN04': 4.46}, filled at 83.8919
bar 317  POLICY_CLOSE  SYN00  held 9 bars  83.8919 -> 85.654  net +19.994 (+1.9990%)
          dopamine PAM x1.000 -> 1,375 synapses depressed, 1,375 weights moved; cash 9927.3
          same context, same seed: V +4.782 at entry -> +6.506 now (BUY)
bar 318  BUY  SYN02  u=[0.206, -0.533, -0.23, -0.272, 0.423]
          readout approach  25.00 Hz  avoid  15.52 Hz -> V +11.786  (450 Kenyon cells, 5,002 eligible synapses)
          selected from 6 candidates {'SYN00': -2.87, 'SYN01': 2.73, 'SYN02': 11.79, 'SYN03': 5.54, 'SYN04': 0.58}, filled at 104.5101
bar 327  POLICY_CLOSE  SYN02  held 9 bars  104.5101 -> 105.0329  net +4.000 (+0.4000%)
          dopamine PAM x0.400 -> 2,838 synapses depressed, 2,838 weights moved; cash 9931.3
          same context, same seed: V +11.786 at entry -> +11.463 now (BUY)
bar 328  BUY  SYN03  u=[0.774, 0.901, 0.475, 0.513, -0.356]
          readout approach  34.38 Hz  avoid  24.14 Hz -> V +12.540  (524 Kenyon cells, 5,866 eligible synapses)
          selected from 6 candidates {'SYN01': -1.14, 'SYN03': 12.54, 'SYN04': 1.66, 'SYN05': -1.14}, filled at 92.7314
bar 337  POLICY_CLOSE  SYN03  held 9 bars  92.7314 -> 93.7582  net +10.068 (+1.0070%)
          dopamine PAM x1.000 -> 3,326 synapses depressed, 3,326 weights moved; cash 9941.37
          same context, same seed: V +12.540 at entry -> +14.265 now (BUY)
bar 338  BUY  SYN03  u=[0.264, 0.185, 0.623, 0.241, -0.007]
          readout approach  18.75 Hz  avoid  10.34 Hz -> V +10.709  (395 Kenyon cells, 4,477 eligible synapses)
          selected from 6 candidates {'SYN00': 1.98, 'SYN03': 10.71, 'SYN04': -1.14, 'SYN05': 0.58}, filled at 94.15
bar 347  POLICY_CLOSE  SYN03  held 9 bars  94.15 -> 95.5294  net +13.645 (+1.3640%)
          dopamine PAM x1.000 -> 2,528 synapses depressed, 2,528 weights moved; cash 9955.01
          same context, same seed: V +10.709 at entry -> +10.709 now (BUY)
bar 350  BUY  SYN03  u=[0.242, 0.098, 0.251, -0.59, 0.107]
          readout approach  18.75 Hz  avoid  13.79 Hz -> V  +7.260  (423 Kenyon cells, 4,819 eligible synapses)
          selected from 6 candidates {'SYN00': 0.26, 'SYN03': 7.26, 'SYN05': 3.38}, filled at 95.1667
bar 359  POLICY_CLOSE  SYN03  held 9 bars  95.1667 -> 96.4481  net +12.459 (+1.2460%)
          dopamine PAM x1.000 -> 2,717 synapses depressed, 2,717 weights moved; cash 9967.47
          same context, same seed: V +7.260 at entry -> +7.260 now (BUY)
bar 360  BUY  SYN02  u=[-0.123, -0.192, 0.733, 0.571, 0.725]
          readout approach  31.25 Hz  avoid  18.97 Hz -> V +14.588  (541 Kenyon cells, 6,040 eligible synapses)
          selected from 6 candidates {'SYN01': 0.26, 'SYN02': 14.59, 'SYN03': 8.98}, filled at 111.1527
bar 369  POLICY_CLOSE  SYN02  held 9 bars  111.1527 -> 114.1085  net +25.578 (+2.5580%)
          dopamine PAM x1.000 -> 3,417 synapses depressed, 3,417 weights moved; cash 9993.05
          same context, same seed: V +14.588 at entry -> +18.036 now (BUY)
bar 370  BUY  SYN03  u=[0.364, 0.56, 0.372, -0.45, -0.415]
          readout approach  21.88 Hz  avoid  12.07 Hz -> V +12.109  (460 Kenyon cells, 5,167 eligible synapses)
          selected from 6 candidates {'SYN00': 3.7, 'SYN03': 12.11, 'SYN05': 7.91}, filled at 98.6875
bar 379  POLICY_CLOSE  SYN03  held 9 bars  98.6875 -> 99.68  net +9.053 (+0.9050%)
          dopamine PAM x0.905 -> 2,928 synapses depressed, 2,928 weights moved; cash 10002.1
          same context, same seed: V +12.109 at entry -> +13.834 now (BUY)
bar 380  BUY  SYN02  u=[0.615, -0.443, 0.052, 0.149, 0.478]
          readout approach  37.50 Hz  avoid  13.79 Hz -> V +26.010  (513 Kenyon cells, 5,724 eligible synapses)
          selected from 6 candidates {'SYN02': 26.01}, filled at 114.1398
bar 389  POLICY_CLOSE  SYN02  held 9 bars  114.1398 -> 115.6758  net +12.450 (+1.2450%)
          dopamine PAM x1.000 -> 3,221 synapses depressed, 3,221 weights moved; cash 10014.55
          same context, same seed: V +26.010 at entry -> +26.010 now (BUY)
bar 390  BUY  SYN03  u=[0.574, 0.171, -0.182, 0.274, 0.055]
          readout approach  43.75 Hz  avoid  29.31 Hz -> V +16.743  (691 Kenyon cells, 7,653 eligible synapses)
          selected from 6 candidates {'SYN00': 14.16, 'SYN01': 0.58, 'SYN02': 5.43, 'SYN03': 16.74}, filled at 101.2636
bar 399  POLICY_CLOSE  SYN03  held 9 bars  101.2636 -> 99.0848  net -22.505 (-2.2510%)
          dopamine PPL1 x1.000 -> 3,351 synapses depressed, 3,351 weights moved; cash 9992.05
          same context, same seed: V +16.743 at entry -> +16.743 now (BUY)
```

