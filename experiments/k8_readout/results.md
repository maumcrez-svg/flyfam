# k = 8 readout — results

Produced by the scripts in this directory against the real connectome. Every number is generated; nothing is hand-entered.

* pre-registration: `PROTOCOL.md`, committed alone at commit `4b8e082`, before any baseline or evaluation run existed
* graph `8feb08a0d2a8` · readout `flytrade-readout-1` · decoder `flytrade-action-1` (unchanged) · runner `flytrade-runner-1` · plasticity `flytrade-mb-1`
* gain 0.10 (D2, frozen), 20 ms window, drive budget 12,000 Hz, carrier 0.10 — all unchanged from Phase One
* k = 8 fixed; k = 1 is replicate 0 of the same schedule, an explicit regression mode and never an automatic fallback
* python 3.13.9, numpy 2.4.2

**Every dataset in this wave is SYNTHETIC.** There is no `data/market/` in the tree and nothing was downloaded. §6 below resolves the provenance in full.

## §3 — the k = 8 baseline and the WAIT margin

`baseline.py`, writing `baseline_k8.json`. The procedure was pre-registered in `PROTOCOL.md` §3 at a commit containing that file alone. No label, no PnL, no realised outcome and no desired action rate participates.

N = 64 batches of k = 8 at the neutral reference `u = 0`, 512 presentations, unlearned weights, gain 0.10, 20 ms window.

| estimator | baseline offset Hz | dispersion Hz | θ = 1.0 × SD | N |
|---|--:|--:|--:|--:|
| k = 1, Phase One (`docs/DECODER.md` §4) | -2.3033 | 3.2414 | 3.2414 | 8 seeds |
| k = 1, replicate 0 of this schedule | -0.8031 | 2.9064 | 2.9064 | 64 draws |
| **k = 8, batch aggregate** | **-0.8444** | **0.9117** | **0.9117** | 64 batches |

SD ratio k = 8 / k = 1 on the same schedule **0.314**, against the Phase One 8-seed SD 0.281; the independent-replicate expectation is 1/√8 = 0.354. The measured ratio is **compatible with sampling variation** — 64 draws give an SD with ≈ 9 % relative error, the ratio of two with ≈ 13 %, and 0.314 is 11 % off — and the results do not establish another cause. Reported, not fixed, not investigated.

Silent replicates **145/512** (unit: presentation); `NO_RESPONSE` batches **0/64** (unit: candidate evaluation (batch)); `INVALID_STATE` batches 0/64. Mean Kenyon active fraction 0.0260.

Seed schedule `flytrade-k8-baseline-1`: 512 distinct seeds, 0 of them below 2³². every Phase One schedule drew integers below 2**32; these are 64-bit digests under their own namespace.

The distribution normalised is the k-presentation aggregate raw valence V_raw = mean(approach) - mean(avoid) at the neutral reference, one sample per BATCH, sample standard deviation with ddof=1 - never the standard error of that mean.

## §5 — the independent integration check

`evaluate.py`, writing `evaluation.json`. Stimuli, seed schedules, metrics, aggregate status rules and pass/fail were committed in `PROTOCOL.md` before this ran, at a commit containing that file alone. No profitability is claimed, sought or measured.

19,200 presentations. θ₈ = 0.9117 Hz against θ₁ = 3.2414 Hz; both decoders are `flytrade-action-1` with the same formula, the same sign convention and the same coefficient 1.0.

### Contexts

Two are the conditioning **v2 pair**, *selected after v1 failed on resolution* — carried over and labelled as what they are. Four are new nominal encoder patterns, never selected for passing anything, placed at declared points of the input range.

| id | `(r1, r5, r20, rv20, relvol)` |
|---|---|
| `V2_X` | (+0.501, +0.497, +0.888, -0.580, -0.565) |
| `V2_Y` | (-0.442, -0.402, -0.922, +0.564, -0.879) |
| `NOM_A` | (-0.900, +0.900, +0.000, +0.000, +0.000) |
| `NOM_B` | (+0.900, +0.000, +0.000, +0.900, +0.000) |
| `NOM_C` | (+0.000, +0.000, +0.900, +0.000, +0.900) |
| `NOM_D` | (+0.900, +0.900, -0.900, -0.900, +0.900) |

Pairwise Kenyon-cell Jaccard, mean over seeds [7001, 7002, 7003, 7004]. The threshold 0.368 applies to the four new patterns, whose maximum is **0.354**; the cross terms with the v2 pair are reported whatever they say.

| | `V2_X` | `V2_Y` | `NOM_A` | `NOM_B` | `NOM_C` | `NOM_D` |
|---|--:|--:|--:|--:|--:|--:|
| `V2_X` | — | 0.109 | 0.367 | 0.249 | 0.513 | 0.517 |
| `V2_Y` | 0.109 | — | 0.179 | 0.110 | 0.078 | 0.117 |
| `NOM_A` | 0.367 | 0.179 | — | 0.232 | 0.232 | 0.338 |
| `NOM_B` | 0.249 | 0.110 | 0.232 | — | 0.348 | 0.288 |
| `NOM_C` | 0.513 | 0.078 | 0.232 | 0.348 | — | 0.354 |
| `NOM_D` | 0.517 | 0.117 | 0.338 | 0.288 | 0.354 | — |

### Within-context stability, k = 1 against k = 8 on the same batches

16 batches per context; k = 1 is replicate 0 of each batch, so the two arms are paired by construction. `SD(V)` is over all 16 batches — the quantity the loop selects on; the `VALID`-only SD is beside it. Agreement is the fraction of batches equal to that arm's modal decision.

| context | SD₁ Hz | SD₈ Hz | ratio | SD₈ valid-only | modal₁ | agree₁ | modal₈ | agree₈ |
|---|--:|--:|--:|--:|---|--:|---|--:|
| `V2_X` | 4.303 | 1.392 | 0.323 | 1.392 | BUY | 0.56 | WAIT | 0.69 |
| `V2_Y` | 2.053 | 0.697 | 0.339 | 0.697 | WAIT | 0.62 | WAIT | 0.88 |
| `NOM_A` | 2.596 | 1.015 | 0.391 | 1.015 | WAIT | 0.62 | WAIT | 0.62 |
| `NOM_B` | 6.461 | 2.420 | 0.375 | 2.420 | BUY | 0.75 | BUY | 1.00 |
| `NOM_C` | 6.858 | 1.510 | 0.220 | 1.510 | BUY | 0.75 | BUY | 1.00 |
| `NOM_D` | 3.233 | 1.614 | 0.499 | 1.614 | BUY | 0.75 | BUY | 0.88 |

### Counts, with their denominators and their units

| context | `NO_RESPONSE`₁ /batch-equivalent | `NO_RESPONSE`₈ /batch | silent replicates /presentation | `INVALID`₁ | `INVALID`₈ | `WAIT`₁ | `WAIT`₈ |
|---|--:|--:|--:|--:|--:|--:|--:|
| `V2_X` | 2/16 | 0/16 | 15/128 | 0 | 0 | 5 | 11 |
| `V2_Y` | 6/16 | 0/16 | 62/128 | 0 | 0 | 10 | 14 |
| `NOM_A` | 5/16 | 0/16 | 18/128 | 0 | 0 | 10 | 10 |
| `NOM_B` | 0/16 | 0/16 | 1/128 | 0 | 0 | 4 | 0 |
| `NOM_C` | 1/16 | 0/16 | 1/128 | 0 | 0 | 3 | 0 |
| `NOM_D` | 0/16 | 0/16 | 2/128 | 0 | 0 | 4 | 2 |

Totals: `NO_RESPONSE` **14/96** at k = 1 (unit: presentation) against **0/96** at k = 8 (unit: candidate evaluation); **99/768** individual presentations inside the k = 8 batches were silent (unit: presentation). A batch is `NO_RESPONSE` only when all eight replicates are silent, which is why the two columns differ; no threshold was lowered and no silence relabelled.

### Learning at k = 8

Each of the twenty training trials is one batch of eight presentations settled by **one** normalised learning event — the mean of the eight proposed deltas computed from the same pre-update state. Never eight sequential rewards. Measurement before and after is one k = 8 batch at the same eight seeds, decoded once with θ₈.

#### Pair `v2` — X = `V2_X`, Y = `V2_Y`, 20 trials, k = 8

| condition | trained on | dV(X) Hz | d approach(X) Hz | d avoid(X) Hz | dV(Y) Hz | seeds whose action changed |
|---|---|--:|--:|--:|--:|--:|
| `APPETITIVE_ON` | `V2_X` | +6.159 | -0.684 | -6.843 | +3.093 | 4/8 |
| `APPETITIVE_OFF` | `V2_X` | +0.000 | +0.000 | +0.000 | +0.000 | 0/8 |
| `AVERSIVE_ON` | `V2_X` | -6.423 | -7.178 | -0.754 | -1.948 | 6/8 |
| `AVERSIVE_OFF` | `V2_X` | +0.000 | +0.000 | +0.000 | +0.000 | 0/8 |
| `APPETITIVE_OTHER` | `V2_Y` | +3.721 | -0.293 | -4.014 | +2.549 | 4/8 |
| `AVERSIVE_OTHER` | `V2_Y` | -3.639 | -3.369 | +0.269 | -2.019 | 6/8 |

| seed | `APPETITIVE_ON` | `APPETITIVE_OFF` | `AVERSIVE_ON` | `AVERSIVE_OFF` | `APPETITIVE_OTHER` | `AVERSIVE_OTHER` |
|--:|--:|--:|--:|--:|--:|--:|
| 1 | +4.674 | +0.000 | -3.475 | +0.000 | +2.842 | -5.078 |
| 2 | +6.425 | +0.000 | -10.466 | +0.000 | +3.664 | -2.950 |
| 3 | +5.805 | +0.000 | -4.512 | +0.000 | +4.741 | -3.125 |
| 4 | +7.112 | +0.000 | -7.812 | +0.000 | +5.253 | -1.913 |
| 5 | +5.388 | +0.000 | -3.906 | +0.000 | +2.883 | -2.856 |
| 6 | +7.368 | +0.000 | -8.270 | +0.000 | +2.155 | -4.688 |
| 7 | +8.190 | +0.000 | -4.256 | +0.000 | +4.741 | -5.374 |
| 8 | +4.310 | +0.000 | -8.688 | +0.000 | +3.489 | -3.125 |

| check | prediction | seeds | threshold | verdict |
|---|---|--:|--:|:--|
| appetitive reaches the decoder | dV(X) > 0 under APPETITIVE_ON | 8/8 | 8/8 | PASS |
| aversive reaches the decoder | dV(X) < 0 under AVERSIVE_ON | 8/8 | 8/8 | PASS |
| plasticity off, appetitive | dV(X) == 0 exactly | 8/8 | 8/8 | PASS |
| plasticity off, aversive | dV(X) == 0 exactly | 8/8 | 8/8 | PASS |
| depends on the eligible experience, appetitive | dV(X)[ON] − dV(X)[OTHER] > 0 | 8/8 | 8/8 | PASS |
| depends on the eligible experience, aversive | dV(X)[ON] − dV(X)[OTHER] < 0 | 6/8 | 8/8 | **below threshold** |

Specificity, mean over seeds: appetitive +2.438 Hz, aversive -2.785 Hz. Learning events per cell: [0, 20] — twenty accepted in every plastic cell, zero in every `_OFF` cell, one per training batch and never eight.

#### Pair `nominal` — X = `NOM_B`, Y = `NOM_A`, 20 trials, k = 8

| condition | trained on | dV(X) Hz | d approach(X) Hz | d avoid(X) Hz | dV(Y) Hz | seeds whose action changed |
|---|---|--:|--:|--:|--:|--:|
| `APPETITIVE_ON` | `NOM_B` | +19.503 | -0.244 | -19.747 | +6.314 | 0/8 |
| `APPETITIVE_OFF` | `NOM_B` | +0.000 | +0.000 | +0.000 | +0.000 | 0/8 |
| `AVERSIVE_ON` | `NOM_B` | -25.338 | -25.635 | -0.296 | -5.285 | 8/8 |
| `AVERSIVE_OFF` | `NOM_B` | +0.000 | +0.000 | +0.000 | +0.000 | 0/8 |
| `APPETITIVE_OTHER` | `NOM_A` | +7.897 | +0.488 | -7.408 | +4.554 | 0/8 |
| `AVERSIVE_OTHER` | `NOM_A` | -8.442 | -7.715 | +0.727 | -3.723 | 7/8 |

| seed | `APPETITIVE_ON` | `APPETITIVE_OFF` | `AVERSIVE_ON` | `AVERSIVE_OFF` | `APPETITIVE_OTHER` | `AVERSIVE_OTHER` |
|--:|--:|--:|--:|--:|--:|--:|
| 1 | +22.468 | +0.000 | -31.829 | +0.000 | +6.331 | -8.957 |
| 2 | +20.434 | +0.000 | -23.316 | +0.000 | +11.732 | -9.159 |
| 3 | +15.571 | +0.000 | -31.748 | +0.000 | +6.991 | -9.941 |
| 4 | +17.794 | +0.000 | -26.832 | +0.000 | +8.473 | -8.473 |
| 5 | +21.134 | +0.000 | -15.450 | +0.000 | +9.537 | -6.183 |
| 6 | +21.659 | +0.000 | -21.875 | +0.000 | +7.435 | -9.631 |
| 7 | +17.282 | +0.000 | -27.249 | +0.000 | +5.294 | -6.910 |
| 8 | +19.679 | +0.000 | -24.407 | +0.000 | +7.381 | -8.284 |

| check | prediction | seeds | threshold | verdict |
|---|---|--:|--:|:--|
| appetitive reaches the decoder | dV(X) > 0 under APPETITIVE_ON | 8/8 | 8/8 | PASS |
| aversive reaches the decoder | dV(X) < 0 under AVERSIVE_ON | 8/8 | 8/8 | PASS |
| plasticity off, appetitive | dV(X) == 0 exactly | 8/8 | 8/8 | PASS |
| plasticity off, aversive | dV(X) == 0 exactly | 8/8 | 8/8 | PASS |
| depends on the eligible experience, appetitive | dV(X)[ON] − dV(X)[OTHER] > 0 | 8/8 | 8/8 | PASS |
| depends on the eligible experience, aversive | dV(X)[ON] − dV(X)[OTHER] < 0 | 8/8 | 8/8 | PASS |

Specificity, mean over seeds: appetitive +11.606 Hz, aversive -16.896 Hz. Learning events per cell: [0, 20] — twenty accepted in every plastic cell, zero in every `_OFF` cell, one per training batch and never eight.

### The pre-registered pass/fail

| id | criterion | result | verdict |
|---|---|---|:--|
| C1 | SD₈ < SD₁ in ≥ 5/6 contexts | 6/6: `V2_X`, `V2_Y`, `NOM_A`, `NOM_B`, `NOM_C`, `NOM_D` | **PASS** |
| C2 | agreement₈ ≥ agreement₁ in ≥ 5/6 contexts | 6/6: `V2_X`, `V2_Y`, `NOM_A`, `NOM_B`, `NOM_C`, `NOM_D` | **PASS** |
| C3a | appetitive sign, both pairs, 8/8 seeds | {'v2': 8, 'nominal': 8} | **PASS** |
| C3b | aversive sign, both pairs, 8/8 seeds | {'v2': 8, 'nominal': 8} | **PASS** |
| C3c | plasticity off exactly 0.000, both pairs, 8/8 seeds | {'v2': [8, 8], 'nominal': [8, 8]} | **PASS** |
| C4 | θ₈ estimator non-degenerate | SD₈ = 0.9117 Hz > 0 | **PASS** |

**All six criteria: PASS.**

## §6 — data provenance and scientific labels

### What is in the tree

`data/market/` **does not exist**. No market data has ever been downloaded into this repository and none is downloaded in this wave. The only downloaded dataset is the MaleCNS v1.0 connectome (CC-BY), whose URLs, byte counts and sha256 are in `data/MANIFEST.md`; it is a connectome, not market data.

### Every dataset, labelled

| used by | instruments / stimuli | generator and seeds | label |
|---|---|---|---|
| Phase One §4 v1 contexts | `CTXX`, `CTXY` | `market.synthetic_series`, seeds 900, 901 | **SYNTHETIC** |
| Phase One §4 v2 contexts | `CTX0`–`CTX3` | `market.synthetic_series`, seeds 900–903 | **SYNTHETIC** |
| Phase One §5 credit demo | `AAA`, `BBB` | `market.synthetic_series`, seeds 910, 911 | **SYNTHETIC** |
| Phase One §8 demonstration | `SYN00`–`SYN05` | `market.synthetic_series`, seeds 700–705 | **SYNTHETIC** |
| Phase One encoder range | six nominal patterns + `u = 0` | feature vectors at declared points of the input range | **SYNTHETIC** |
| D4 §3 baseline | `neutral_reference` | the feature vector `u = (0,0,0,0,0)` | **SYNTHETIC** |
| D4 §5 contexts | `V2_X`, `V2_Y` | `market.synthetic_series`, seeds 903 bar 218 and 901 bar 409 | **SYNTHETIC** |
| D4 §5 contexts | `NOM_A`–`NOM_D` | feature vectors at declared points of the input range | **SYNTHETIC** |
| D4 §7 benchmark | `SYN00`–`SYN05` | `market.synthetic_series`, seeds 700–705 | **SYNTHETIC** |
| D4 §8 demonstration | `SYN00`–`SYN05` | `market.synthetic_series`, seeds 700–705 | **SYNTHETIC** |

No `HISTORICAL_MARKET` dataset exists in this repository, so no source, instrument list, timestamp range or file hash can be recorded for one. When one arrives, `flytrade/market.py` documents the format and `data/MANIFEST.md` is where its provenance goes.

### Resolving "real observations"

The Phase One report's risk 1 said *"18.5–20.6% of real observations give `NO_RESPONSE`"*. Resolved from the artifacts, that phrase meant **observations the offline simulator actually produced over seeded synthetic series** — not historical market data, of which there is none. The numbers the committed artifacts do support, from `experiments/phase_one/demo.json`:

| numerator / denominator | value | unit |
|---|--:|---|
| `NO_RESPONSE` decisions / decoded selected-candidate readouts | 60/319 = 18.8% | decision |
| `NO_RESPONSE` statuses / all recorded round statuses | 60/325 = 18.5% | decision |
| `NO_RESPONSE` decisions / presentations made in the run | 60/558 = 10.8% | presentation |

The stated range **18.5–20.6 % is not reproducible as written** from the committed artifacts; the closest supported figure is 60/319 = 18.8% of decisions. It is corrected here rather than repeated. The substantive point survives either way: at k = 1 roughly one decision in five had nothing to decode from.

### This wave's `NO_RESPONSE`, with units

| measurement | numerator / denominator | unit |
|---|--:|---|
| §5, k = 1 arm | 14/96 = 14.6% | presentation |
| §5, k = 8 arm | 0/96 = 0.0% | candidate evaluation (batch) |
| §5, silent replicates inside the k = 8 batches | 99/768 = 12.9% | presentation |
| §3 baseline, k = 1 (replicate 0) silence | 145/512 = 28.3% | presentation |
| §3 baseline, k = 8 batches | 0/64 | candidate evaluation (batch) |

| §8 demonstration, k = 8 | 1/320 = 0.3% | decision |

### The decoder convention, stated in three layers

`docs/DECODER.md` §3 separates *(a)* the observed dopaminergic innervation split on this dataset, *(b)* the literature's attributed valence, which assumes the numbering is the hemibrain numbering, and *(c)* our convention `V = PPL1-side − PAM-side`. PPL1-minus-PAM is retained as the declared **experimental** convention. Grouping MBONs by dopaminergic innervation is not described as proof of a universal behavioural valence, and the earlier claim that it was "the only sign consistent with depression-only plasticity" has been corrected there and in `docs/ARCHITECTURE.md`. The decoder is unchanged; no literature-audit phase was run, and none was required.

## §7 — measured cost

`benchmark.py`, writing `benchmark.json`. One process, no parallelism, no distributed infrastructure, and nothing in the scientific model changed to reach a number.

6 candidates per round, 24 rounds per arm after 2 warm-up rounds, same fixture and same brain.

| | k = 1 | k = 8 | ratio |
|---|--:|--:|--:|
| presentations per round | 6 | 48 | 8.0× |
| round latency, median | 161.8 ms | 1194.4 ms | 7.38× |
| round latency, p95 | 167.1 ms | 1257.7 ms | 7.52× |
| neural evaluation, median | 151.9 ms | 1182.6 ms | 7.79× |
| checkpoint + logging, median | 8.5 ms | 9.7 ms | 1.14× |
| neural share of the round | 93.8% | 99.0% | |
| per presentation | 25.3 ms | 24.7 ms | |
| peak RSS | 562 MiB | 562 MiB | |

Peak process memory 562 MiB, of which 560 MiB is the loaded connectome; the k = 8 arm adds 3 MiB over that high-water mark. ru_maxrss high-water mark of the whole process; the connectome dominates it and k does not move it.

Hardware: AMD Ryzen 5 7600X 6-Core Processor, 12 logical cores, 62.0 GB RAM, Linux-7.0.0-31-generic-x86_64-with-glibc2.39, Python 3.13.9, NumPy 2.4.2. one process, one thread of control, no parallelism and no distributed infrastructure.

## §8 — the offline demonstration at k = 8

`run_demo_k8.py`, writing `demo_k8.json`. The Phase One demonstration's own fixture, seeds and bar range, the same mid-run restart, with every candidate now read eight times. Net PnL is **not** a gate metric and is not read in either direction.

6 instruments, bars 80-400, k = 8: 1,625 candidate evaluations, 13,168 presentations of 20 ms.

| | |
|---|--:|
| completed decision/outcome cycles | 21 |
| closed by a neural SELL | 19 |
| closed by the horizon (POLICY_CLOSE) | 2 |
| closed at end of data | 0 |
| wins / losses / flat | 7 / 14 / 0 |
| gross PnL | -90.50 |
| fees paid | 20.95 |
| net realised PnL (**not a gate metric**) | -111.46 |
| cash | 9888.54 |
| reinforcements accepted | 21 |
| reinforcements rejected | 0 |
| execution rejections | 0  |
| rounds aborted (technical failure) | 0 |
| event-log entries | 726 |

Decoder output over every decision (one aggregate of k = 8 each):

| `BUY` | `NO_RESPONSE` | `SELL` | `WAIT` |
|--:|--:|--:|--:|
| 36 | 1 | 94 | 189 |

Readout status over every decision:

| `NO_RESPONSE` | `VALID` |
|--:|--:|
| 1 | 319 |

`NO_RESPONSE` **1/320** (unit: decision — a candidate evaluation of 8 presentations); `WAIT` 189/320 counted separately; `INVALID_STATE` 0/320 separately from both. Inside the batches, **3,503/13,000** individual presentations were silent (unit: presentation) — a batch is `NO_RESPONSE` only when all 8 of its replicates are.

Mid-run restart at bar 97 after 3 settled episodes: in-memory gains destroyed, rebuilt from the checkpoint and the log, `nothing to do`, gains restored exactly: **True**.

### Chronological trace

`u` is the normalised feature vector `(r1, r5, r20, rv20, relvol)`; `V` the centred valence the fixed decoder computed from the aggregate of eight; `eligible` the union of the eight replicates' eligible synapses; `depressed` the ones the one normalised dopamine event actually moved.

```
bar  80  BUY  SYN03  u=[0.425, -0.084, 0.261, 0.055, 0.435]
          readout approach  26.17 Hz  avoid  22.20 Hz -> V  +4.818  (330 Kenyon cells, 7,520 eligible synapses over 8 replicates, 0 of them silent)
          per-replicate decode ['BUY', 'BUY', 'WAIT', 'WAIT', 'BUY', 'WAIT', 'BUY', 'BUY']
          selected from 6 candidates {'SYN00': -0.27, 'SYN01': -0.39, 'SYN02': 3.05, 'SYN03': 4.82, 'SYN04': 0.08, 'SYN05': 4.16}, filled at 108.5407
bar  89  POLICY_CLOSE  SYN03  held 9 bars  108.5407 -> 108.776  net +1.167 (+0.1170%)
          dopamine PAM x0.117 -> one mean_of_deltas event over k = 8: 4,229 synapses depressed (per replicate [1376, 4008, 2187, 1442, 1052, 511, 2599, 3619]), 4,229 weights moved; cash 10001.17
          same context, same eight seeds: V +4.818 at entry -> +4.818 now (BUY)
bar  90  BUY  SYN03  u=[0.558, 0.289, 0.171, 0.421, -0.185]
          readout approach  26.17 Hz  avoid  21.55 Hz -> V  +5.465  (337 Kenyon cells, 7,634 eligible synapses over 8 replicates, 0 of them silent)
          per-replicate decode ['WAIT', 'BUY', 'BUY', 'BUY', 'BUY', 'WAIT', 'BUY', 'BUY']
          selected from 6 candidates {'SYN00': -1.11, 'SYN01': 0.59, 'SYN02': 0.8, 'SYN03': 5.46, 'SYN04': -0.54, 'SYN05': 1.88}, filled at 109.5374
bar  91  NEURAL_SELL  SYN03  held 1 bars  109.5374 -> 109.6114  net -0.325 (-0.0330%)
          dopamine PPL1 x0.033 -> one mean_of_deltas event over k = 8: 3,322 synapses depressed (per replicate [471, 1756, 3112, 1207, 2866, 1616, 1299, 981]), 3,322 weights moved; cash 10000.84
          same context, same eight seeds: V +5.465 at entry -> +5.465 now (BUY)
bar  92  BUY  SYN02  u=[0.706, 0.088, 0.3, -0.552, -0.12]
          readout approach  21.88 Hz  avoid  18.97 Hz -> V  +3.754  (292 Kenyon cells, 5,653 eligible synapses over 8 replicates, 0 of them silent)
          per-replicate decode ['BUY', 'BUY', 'WAIT', 'WAIT', 'BUY', 'BUY', 'BUY', 'BUY']
          selected from 6 candidates {'SYN00': 0.84, 'SYN01': 0.32, 'SYN02': 3.75, 'SYN03': -0.95, 'SYN04': 3.4, 'SYN05': -0.14}, filled at 104.7161
bar  97  NEURAL_SELL  SYN02  held 5 bars  104.7161 -> 103.6891  net -10.803 (-1.0800%)
          dopamine PPL1 x1.000 -> one mean_of_deltas event over k = 8: 2,473 synapses depressed (per replicate [2225, 1555, 918, 1087, 1450, 1276, 1429, 1767]), 2,473 weights moved; cash 9990.04
          same context, same eight seeds: V +3.754 at entry -> +2.582 now (BUY)
bar  97  RESTART  nothing to do; last settled episode 92000002; gains restored exactly: True
bar  98  BUY  SYN01  u=[0.727, 0.417, 0.263, 0.52, 0.239]
          readout approach  14.06 Hz  avoid  13.15 Hz -> V  +1.760  (222 Kenyon cells, 5,811 eligible synapses over 8 replicates, 0 of them silent)
          per-replicate decode ['BUY', 'WAIT', 'WAIT', 'BUY', 'BUY', 'WAIT', 'BUY', 'WAIT']
          selected from 6 candidates {'SYN00': 0.6, 'SYN01': 1.76, 'SYN02': -0.17, 'SYN03': 0.4, 'SYN04': 1.69, 'SYN05': -0.89}, filled at 109.7184
bar 101  NEURAL_SELL  SYN01  held 3 bars  109.7184 -> 108.6538  net -10.699 (-1.0700%)
          dopamine PPL1 x1.000 -> one mean_of_deltas event over k = 8: 2,530 synapses depressed (per replicate [2475, 541, 320, 1419, 1564, 582, 1151, 909]), 2,530 weights moved; cash 9979.34
          same context, same eight seeds: V +1.760 at entry -> +1.585 now (BUY)
bar 102  BUY  SYN03  u=[0.499, 0.784, 0.041, -0.13, -0.824]
          readout approach  16.80 Hz  avoid  15.73 Hz -> V  +1.909  (246 Kenyon cells, 5,187 eligible synapses over 8 replicates, 0 of them silent)
          per-replicate decode ['WAIT', 'BUY', 'WAIT', 'BUY', 'WAIT', 'WAIT', 'WAIT', 'BUY']
          selected from 6 candidates {'SYN00': -3.2, 'SYN01': 0.82, 'SYN02': 1.63, 'SYN03': 1.91, 'SYN04': -1.74, 'SYN05': -0.53}, filled at 112.1676
bar 105  NEURAL_SELL  SYN03  held 3 bars  112.1676 -> 112.7508  net +4.196 (+0.4200%)
          dopamine PAM x0.420 -> one mean_of_deltas event over k = 8: 2,911 synapses depressed (per replicate [929, 1850, 2187, 2277, 1506, 910, 656, 2356]), 2,911 weights moved; cash 9983.54
          same context, same eight seeds: V +1.909 at entry -> +2.340 now (BUY)
bar 106  BUY  SYN04  u=[-0.438, -0.589, -0.604, -0.4, -0.108]
          readout approach   8.98 Hz  avoid   8.84 Hz -> V  +0.993  (156 Kenyon cells, 3,870 eligible synapses over 8 replicates, 2 of them silent)
          per-replicate decode ['WAIT', 'NO_RESPONSE', 'NO_RESPONSE', 'BUY', 'BUY', 'WAIT', 'WAIT', 'BUY']
          selected from 6 candidates {'SYN00': 0.64, 'SYN01': 0.09, 'SYN02': -2.29, 'SYN03': -0.62, 'SYN04': 0.99, 'SYN05': -1.51}, filled at 101.2141
bar 113  NEURAL_SELL  SYN04  held 7 bars  101.2141 -> 101.5314  net +2.133 (+0.2130%)
          dopamine PAM x0.213 -> one mean_of_deltas event over k = 8: 2,182 synapses depressed (per replicate [524, 258, 38, 2035, 1482, 769, 1291, 1678]), 2,182 weights moved; cash 9985.67
          same context, same eight seeds: V +0.993 at entry -> +1.208 now (BUY)
bar 116  BUY  SYN05  u=[0.614, -0.392, 0.367, 0.629, -0.205]
          readout approach  27.34 Hz  avoid  23.92 Hz -> V  +4.266  (372 Kenyon cells, 6,825 eligible synapses over 8 replicates, 0 of them silent)
          per-replicate decode ['BUY', 'BUY', 'WAIT', 'WAIT', 'BUY', 'BUY', 'WAIT', 'BUY']
          selected from 6 candidates {'SYN00': 0.18, 'SYN01': -0.56, 'SYN02': -0.79, 'SYN03': -0.14, 'SYN04': 0.13, 'SYN05': 4.27}, filled at 106.5881
bar 125  POLICY_CLOSE  SYN05  held 9 bars  106.5881 -> 105.6336  net -9.950 (-0.9950%)
          dopamine PPL1 x0.995 -> one mean_of_deltas event over k = 8: 2,966 synapses depressed (per replicate [2655, 2109, 973, 1866, 2001, 1491, 1204, 2389]), 2,966 weights moved; cash 9975.72
          same context, same eight seeds: V +4.266 at entry -> +2.137 now (BUY)
bar 127  BUY  SYN00  u=[0.769, 0.205, -0.114, 0.925, 0.484]
          readout approach  25.78 Hz  avoid  24.78 Hz -> V  +1.841  (391 Kenyon cells, 9,358 eligible synapses over 8 replicates, 0 of them silent)
          per-replicate decode ['BUY', 'BUY', 'WAIT', 'BUY', 'BUY', 'WAIT', 'WAIT', 'WAIT']
          selected from 6 candidates {'SYN00': 1.84, 'SYN01': -0.57, 'SYN02': -0.8, 'SYN03': -0.3, 'SYN04': -2.36, 'SYN05': -1.69}, filled at 103.5666
bar 129  NEURAL_SELL  SYN00  held 2 bars  103.5666 -> 102.0558  net -15.580 (-1.5580%)
          dopamine PPL1 x1.000 -> one mean_of_deltas event over k = 8: 4,087 synapses depressed (per replicate [4087, 1802, 2258, 1912, 2618, 1074, 1107, 614]), 4,087 weights moved; cash 9960.14
          same context, same eight seeds: V +1.841 at entry -> +0.844 now (WAIT)
bar 130  BUY  SYN04  u=[0.633, -0.026, 0.751, 0.886, 0.456]
          readout approach  17.97 Hz  avoid  17.67 Hz -> V  +1.141  (290 Kenyon cells, 5,782 eligible synapses over 8 replicates, 0 of them silent)
          per-replicate decode ['BUY', 'WAIT', 'BUY', 'BUY', 'WAIT', 'WAIT', 'BUY', 'BUY']
          selected from 6 candidates {'SYN00': -2.51, 'SYN01': -1.32, 'SYN02': -1.73, 'SYN03': -1.18, 'SYN04': 1.14, 'SYN05': -0.1}, filled at 103.8783
bar 131  NEURAL_SELL  SYN04  held 1 bars  103.8783 -> 104.5934  net +5.881 (+0.5880%)
          dopamine PAM x0.588 -> one mean_of_deltas event over k = 8: 3,262 synapses depressed (per replicate [1915, 537, 2155, 3052, 847, 1305, 2385, 2646]), 3,262 weights moved; cash 9966.02
          same context, same eight seeds: V +1.141 at entry -> +1.141 now (BUY)
bar 132  BUY  SYN05  u=[-0.694, -0.955, -0.952, 0.897, -0.328]
          readout approach   9.77 Hz  avoid   9.70 Hz -> V  +0.912  (170 Kenyon cells, 4,737 eligible synapses over 8 replicates, 2 of them silent)
          per-replicate decode ['BUY', 'NO_RESPONSE', 'NO_RESPONSE', 'WAIT', 'WAIT', 'BUY', 'WAIT', 'BUY']
          selected from 6 candidates {'SYN00': -0.44, 'SYN01': -1.1, 'SYN02': -1.35, 'SYN03': -0.38, 'SYN04': -0.96, 'SYN05': 0.91}, filled at 101.777
bar 133  NEURAL_SELL  SYN05  held 1 bars  101.777 -> 101.5807  net -2.928 (-0.2930%)
          dopamine PPL1 x0.293 -> one mean_of_deltas event over k = 8: 2,070 synapses depressed (per replicate [1581, 70, 180, 625, 728, 1565, 388, 1746]), 2,070 weights moved; cash 9963.09
          same context, same eight seeds: V +0.912 at entry -> +0.912 now (BUY)
bar 135  BUY  SYN03  u=[0.71, -0.121, -0.863, 0.789, 0.212]
          readout approach  25.00 Hz  avoid  23.49 Hz -> V  +2.353  (361 Kenyon cells, 8,115 eligible synapses over 8 replicates, 0 of them silent)
          per-replicate decode ['WAIT', 'WAIT', 'BUY', 'BUY', 'BUY', 'BUY', 'WAIT', 'WAIT']
          selected from 6 candidates {'SYN00': 1.36, 'SYN01': -3.55, 'SYN02': -0.23, 'SYN03': 2.35, 'SYN04': -1.3, 'SYN05': -0.77}, filled at 104.6854
bar 137  NEURAL_SELL  SYN03  held 2 bars  104.6854 -> 105.209  net +3.999 (+0.4000%)
          dopamine PAM x0.400 -> one mean_of_deltas event over k = 8: 4,584 synapses depressed (per replicate [1315, 813, 2077, 3659, 4366, 4071, 530, 1410]), 4,584 weights moved; cash 9967.09
          same context, same eight seeds: V +2.353 at entry -> +1.706 now (BUY)
bar 138  BUY  SYN02  u=[0.674, -0.524, -0.817, 0.835, 0.004]
          readout approach  24.22 Hz  avoid  23.28 Hz -> V  +1.787  (374 Kenyon cells, 7,256 eligible synapses over 8 replicates, 0 of them silent)
          per-replicate decode ['WAIT', 'BUY', 'WAIT', 'BUY', 'BUY', 'BUY', 'BUY', 'WAIT']
          selected from 6 candidates {'SYN00': -2.24, 'SYN01': -0.13, 'SYN02': 1.79, 'SYN03': -1.15, 'SYN04': 0.98, 'SYN05': 0.31}, filled at 97.4468
bar 140  NEURAL_SELL  SYN02  held 2 bars  97.4468 -> 97.4058  net -1.420 (-0.1420%)
          dopamine PPL1 x0.142 -> one mean_of_deltas event over k = 8: 3,151 synapses depressed (per replicate [673, 2347, 1690, 1469, 1582, 2539, 1461, 3031]), 3,151 weights moved; cash 9965.67
          same context, same eight seeds: V +1.787 at entry -> +1.787 now (BUY)
bar 142  BUY  SYN04  u=[0.707, -0.126, 0.528, 0.662, -0.351]
          readout approach  20.31 Hz  avoid  18.97 Hz -> V  +2.191  (310 Kenyon cells, 7,401 eligible synapses over 8 replicates, 0 of them silent)
          per-replicate decode ['WAIT', 'BUY', 'WAIT', 'BUY', 'BUY', 'WAIT', 'WAIT', 'BUY']
          selected from 6 candidates {'SYN00': -0.06, 'SYN01': 1.8, 'SYN02': 1.18, 'SYN03': 1.65, 'SYN04': 2.19, 'SYN05': -3.63}, filled at 104.0325
bar 143  NEURAL_SELL  SYN04  held 1 bars  104.0325 -> 104.1013  net -0.339 (-0.0340%)
          dopamine PPL1 x0.034 -> one mean_of_deltas event over k = 8: 3,225 synapses depressed (per replicate [582, 1663, 1514, 3046, 1183, 855, 471, 2921]), 3,225 weights moved; cash 9965.33
          same context, same eight seeds: V +2.191 at entry -> +2.191 now (BUY)
bar 144  BUY  SYN05  u=[0.509, -0.789, -0.901, 0.713, 0.44]
          readout approach  21.09 Hz  avoid  19.83 Hz -> V  +2.111  (330 Kenyon cells, 6,903 eligible synapses over 8 replicates, 0 of them silent)
          per-replicate decode ['WAIT', 'BUY', 'WAIT', 'BUY', 'WAIT', 'WAIT', 'WAIT', 'BUY']
          selected from 6 candidates {'SYN00': 0.41, 'SYN01': -1.51, 'SYN02': 1.84, 'SYN03': -0.5, 'SYN04': -1.04, 'SYN05': 2.11}, filled at 97.1714
bar 147  NEURAL_SELL  SYN05  held 3 bars  97.1714 -> 94.7502  net -25.905 (-2.5900%)
          dopamine PPL1 x1.000 -> one mean_of_deltas event over k = 8: 2,990 synapses depressed (per replicate [440, 2398, 1412, 1841, 1284, 1368, 1333, 2917]), 2,990 weights moved; cash 9939.43
          same context, same eight seeds: V +2.111 at entry -> +0.764 now (WAIT)
bar 149  BUY  SYN00  u=[0.659, 0.115, 0.674, 0.655, 0.306]
          readout approach  18.75 Hz  avoid  17.46 Hz -> V  +2.137  (285 Kenyon cells, 7,646 eligible synapses over 8 replicates, 3 of them silent)
          per-replicate decode ['BUY', 'WAIT', 'BUY', 'NO_RESPONSE', 'BUY', 'WAIT', 'NO_RESPONSE', 'NO_RESPONSE']
          selected from 6 candidates {'SYN00': 2.14, 'SYN01': -1.93, 'SYN02': 0.84, 'SYN03': -1.18, 'SYN04': 0.2, 'SYN05': -1.2}, filled at 102.8352
bar 150  NEURAL_SELL  SYN00  held 1 bars  102.8352 -> 103.3249  net +3.760 (+0.3760%)
          dopamine PAM x0.376 -> one mean_of_deltas event over k = 8: 4,313 synapses depressed (per replicate [3890, 1515, 3819, 152, 2803, 1592, 548, 115]), 4,313 weights moved; cash 9943.19
          same context, same eight seeds: V +2.137 at entry -> +2.137 now (BUY)
bar 151  BUY  SYN04  u=[0.447, 0.535, 0.099, 0.746, -0.095]
          readout approach  17.58 Hz  avoid  17.03 Hz -> V  +1.397  (299 Kenyon cells, 7,465 eligible synapses over 8 replicates, 1 of them silent)
          per-replicate decode ['SELL', 'NO_RESPONSE', 'BUY', 'BUY', 'WAIT', 'BUY', 'WAIT', 'WAIT']
          selected from 6 candidates {'SYN00': 0.98, 'SYN01': -0.96, 'SYN02': 1.01, 'SYN03': -1.82, 'SYN04': 1.4, 'SYN05': -4.26}, filled at 105.3237
bar 153  NEURAL_SELL  SYN04  held 2 bars  105.3237 -> 106.4611  net +9.794 (+0.9790%)
          dopamine PAM x0.979 -> one mean_of_deltas event over k = 8: 4,225 synapses depressed (per replicate [706, 315, 2975, 2160, 693, 3734, 1654, 2999]), 4,225 weights moved; cash 9952.98
          same context, same eight seeds: V +1.397 at entry -> +2.043 now (BUY)
bar 156  BUY  SYN04  u=[0.475, 0.29, 0.144, 0.66, -0.224]
          readout approach  13.67 Hz  avoid  12.50 Hz -> V  +2.016  (262 Kenyon cells, 6,643 eligible synapses over 8 replicates, 2 of them silent)
          per-replicate decode ['BUY', 'BUY', 'NO_RESPONSE', 'SELL', 'NO_RESPONSE', 'WAIT', 'BUY', 'BUY']
          selected from 6 candidates {'SYN00': -2.01, 'SYN01': -0.96, 'SYN02': -0.7, 'SYN03': 1.72, 'SYN04': 2.02, 'SYN05': -0.64}, filled at 106.4431
bar 158  NEURAL_SELL  SYN04  held 2 bars  106.4431 -> 104.7827  net -16.591 (-1.6590%)
          dopamine PPL1 x1.000 -> one mean_of_deltas event over k = 8: 2,889 synapses depressed (per replicate [2140, 2708, 115, 955, 99, 1343, 1818, 1182]), 2,889 weights moved; cash 9936.39
          same context, same eight seeds: V +2.016 at entry -> +0.804 now (WAIT)
bar 160  BUY  SYN05  u=[-0.565, -0.084, -0.505, 0.369, 0.776]
          readout approach  24.61 Hz  avoid  23.28 Hz -> V  +2.178  (384 Kenyon cells, 6,331 eligible synapses over 8 replicates, 0 of them silent)
          per-replicate decode ['SELL', 'WAIT', 'BUY', 'BUY', 'BUY', 'BUY', 'WAIT', 'WAIT']
          selected from 6 candidates {'SYN00': -2.04, 'SYN01': -0.85, 'SYN02': -1.55, 'SYN03': -2.5, 'SYN04': -2.15, 'SYN05': 2.18}, filled at 90.6649
bar 161  NEURAL_SELL  SYN05  held 1 bars  90.6649 -> 88.0582  net -29.737 (-2.9740%)
          dopamine PPL1 x1.000 -> one mean_of_deltas event over k = 8: 2,757 synapses depressed (per replicate [1185, 1609, 2245, 1504, 2295, 2419, 1609, 2287]), 2,757 weights moved; cash 9906.65
          same context, same eight seeds: V +2.178 at entry -> -0.206 now (WAIT)
bar 166  BUY  SYN01  u=[0.658, 0.014, -0.403, 0.614, -0.071]
          readout approach  17.58 Hz  avoid  15.52 Hz -> V  +2.905  (289 Kenyon cells, 6,792 eligible synapses over 8 replicates, 2 of them silent)
          per-replicate decode ['NO_RESPONSE', 'WAIT', 'BUY', 'BUY', 'BUY', 'WAIT', 'BUY', 'NO_RESPONSE']
          selected from 6 candidates {'SYN00': -3.12, 'SYN01': 2.91, 'SYN02': -2.63, 'SYN03': -0.95, 'SYN04': -1.26, 'SYN05': -2.04}, filled at 83.55
bar 167  NEURAL_SELL  SYN01  held 1 bars  83.55 -> 82.8881  net -8.918 (-0.8920%)
          dopamine PPL1 x0.892 -> one mean_of_deltas event over k = 8: 2,976 synapses depressed (per replicate [19, 1304, 2895, 2086, 1706, 1624, 1604, 235]), 2,976 weights moved; cash 9897.74
          same context, same eight seeds: V +2.905 at entry -> +2.447 now (BUY)
bar 172  BUY  SYN01  u=[0.487, 0.128, -0.147, 0.524, -0.597]
          readout approach  22.27 Hz  avoid  21.34 Hz -> V  +1.774  (380 Kenyon cells, 7,677 eligible synapses over 8 replicates, 1 of them silent)
          per-replicate decode ['WAIT', 'BUY', 'WAIT', 'WAIT', 'NO_RESPONSE', 'BUY', 'BUY', 'WAIT']
          selected from 6 candidates {'SYN00': -2.25, 'SYN01': 1.77, 'SYN02': -3.36, 'SYN03': -3.87, 'SYN04': -1.7, 'SYN05': -3.2}, filled at 81.3545
bar 173  NEURAL_SELL  SYN01  held 1 bars  81.3545 -> 80.9508  net -5.960 (-0.5960%)
          dopamine PPL1 x0.596 -> one mean_of_deltas event over k = 8: 3,340 synapses depressed (per replicate [1610, 2047, 2696, 2023, 87, 2449, 3080, 1031]), 3,340 weights moved; cash 9891.78
          same context, same eight seeds: V +1.774 at entry -> +0.993 now (BUY)
bar 390  BUY  SYN02  u=[-0.187, 0.459, -0.483, 0.411, 0.249]
          readout approach   2.34 Hz  avoid   2.16 Hz -> V  +1.033  (71 Kenyon cells, 4,190 eligible synapses over 8 replicates, 7 of them silent)
          per-replicate decode ['NO_RESPONSE', 'NO_RESPONSE', 'NO_RESPONSE', 'NO_RESPONSE', 'NO_RESPONSE', 'BUY', 'NO_RESPONSE', 'NO_RESPONSE']
          selected from 6 candidates {'SYN00': -5.43, 'SYN01': -2.58, 'SYN02': 1.03, 'SYN03': -2.48, 'SYN04': -1.81, 'SYN05': -2.85}, filled at 115.7076
bar 392  NEURAL_SELL  SYN02  held 2 bars  115.7076 -> 115.4491  net -3.232 (-0.3230%)
          dopamine PPL1 x0.323 -> one mean_of_deltas event over k = 8: 1,840 synapses depressed (per replicate [195, 100, 268, 63, 270, 1840, 122, 77]), 1,840 weights moved; cash 9888.54
          same context, same eight seeds: V +1.033 at entry -> +1.033 now (BUY)
```

