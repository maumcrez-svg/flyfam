# Encoder — market context to olfactory drive

`flytrade/market.py` and `flytrade/encoder.py`, version `flytrade-encoder-1`.
Canonical amendment §1, Fable addenda 1 and 2. Every number below is produced
by `experiments/phase_one/encoder_range.py` and stored in
`experiments/phase_one/encoder_range.json`; nothing here is hand-entered.

The gain is **0.10** everywhere, frozen by D2, and is never tuned in this or
any later wave. Where something had to give, the declared *input range* gave.

## 1. Observations

Bars only, offline only. Two sources, both deterministic: a seeded synthetic
generator (random walk with four regime shifts) and a local CSV in the format
documented at the top of `flytrade/market.py`, one file per symbol under
`data/market/` (gitignored, no provider, no network).

`ObservationFeed` can only read bars at or before a cutoff; `ExecutionFeed` is
a separate class and is the only thing in the repository that reads a later
bar. That separation is the mechanism behind "the brain and encoder cannot
access future labels" — it is structural, not a convention.

**Features**, all causal, computed from bars `<= i`:

| name | measurement |
|---|---|
| `r1` | one-bar log return |
| `r5` | five-bar log return |
| `r20` | twenty-bar log return |
| `rv20` | realised volatility, SD of the last 20 one-bar log returns |
| `relvol` | log of bar volume over its own trailing 20-bar mean |

**Normalisation.** Each feature is z-scored against its own trailing
distribution over the last 60 bars *ending at the cutoff*, then squashed with
`tanh(z / 2)`, giving `u` in (-1, 1). The window is recomputed at every cutoff
and never looks forward, so no normalisation constant can carry information
from the evaluation period. Minimum history is therefore `60 + 20 + 1 = 81`
bars.

**Missing and stale data** are explicit, never smoothed over.
`ObservationStatus` is one of `OK`, `INSUFFICIENT_HISTORY` (fewer than 81 bars),
`GAP` (a NaN bar, or a timestamp gap wider than 1.5 intervals, inside the
window) or `STALE` (the cutoff bar is older than the caller's tolerance).
`encode()` **raises** on anything but `OK`: an unusable observation is not a
flat market and the encoder refuses to pretend otherwise.

## 2. Channels

Candidate pool: the 46 glomeruli with both ORNs and uniglomerular PNs minus the
four pheromone channels, i.e. exactly the pool pre-registered in
`experiments/conditioning/PROTOCOL.md` §3. No new population is introduced;
addendum 1 forbids it.

Selection rule, with no market quantity in it: keep candidates with at least 4
uniglomerular PNs, rank by ORN count descending (ties alphabetical), take the
first ten, pair them consecutively. Consecutive pairing keeps the two halves of
a feature close in ORN count, so the *sign* of a feature is not confounded with
the *strength* of its channel.

### Channel map

| feature | + glomerulus | ORNs | uPNs | - glomerulus | ORNs | uPNs |
|---|---|--:|--:|---|--:|--:|
| `r1` | VL2a | 98 | 8 | VM5d | 84 | 12 |
| `r5` | DL1 | 83 | 4 | VL1 | 82 | 4 |
| `r20` | VM4 | 78 | 8 | DM3 | 63 | 4 |
| `rv20` | DM6 | 58 | 7 | V | 55 | 4 |
| `relvol` | DM2 | 54 | 4 | DA2 | 48 | 10 |

Body ids are not listed here: they are an artefact of the dataset build and
are recovered from the glomerulus name at any time with
`flytrade.populations.orn_glomeruli(ann)[<glomerulus>]`, against
`annotations.npz`, whose provenance and sha256 are in `data/MANIFEST.md`.
The ten channels together drive **703 ORNs**.

## 3. Coding rule

Each feature's pair is driven antagonistically, half-wave rectified over a
small always-on carrier `C`, and the result is scaled to a **constant total
drive budget** `B`:

```
w(+glomerulus) = C + (1 - C) * max(0, +u)
w(-glomerulus) = C + (1 - C) * max(0, -u)
rate(g)        = min(150 Hz, B * w(g) / sum_h w(h) * n_orns(h))
```

Rectification is what makes two market states recruit two different sets of
Kenyon cells. The budget is what keeps "which market state" from being
confounded with "how much drive": every state delivers the same total ORN
spikes per second, so a flat tape is a *different* odour rather than a
*fainter* one. The antennal lobe normalises divisively across glomeruli
(Olsen, Bhandawat & Wilson 2010, *Neuron* 66:287), so a constant-budget input
is the regime the downstream circuit is built for.

Per-ORN rates stay in `[0, 150]` Hz by construction, which is addendum 1's
window. Presentation is 100 steps x 0.2 ms = **20 ms** of brain time, unchanged
from PROTOCOL.md §2. Channel strength is **not** equalised across features: the
budget is shared in proportion to `w(g) * n_orns(g)`, so VL2a (98 ORNs) claims
more of it than DA2 (48). Equalising would need per-ORN rates far above the
150 Hz ceiling for the small glomeruli, so the anatomy is left to do the
weighting and the weighting is stated rather than hidden.

**Ticker identity is not encoded.** Two instruments with identical normalised
features produce an identical stimulus. Amendment §1: ticker identity is
metadata.

**Nothing but ORNs is stimulated.** No Kenyon cell, MBON, PAM or PPL1 neuron is
ever driven directly, and no reinforcement pathway is used as a shortcut around
the sensory path.

## 4. Operating range — measured, and what it cost

D2 asks for the encoder's actual input range at gain 0.10: silence, saturation,
KC recruitment, MBON response variation, discrimination. Addendum 1 adds that
if the nominal patterns fail the three PROTOCOL.md §2 sanity criteria, the
**declared input range is restricted and the gain never raised**. That is what
happened, twice, and both failures are reproducible from the same script.

Six nominal patterns, in feature order `(r1, r5, r20, rv20, relvol)`:

| pattern | u |
|---|---|
| `strong_up` | (+0.80, +0.90, +0.90, +0.20, +0.50) |
| `strong_down` | (-0.80, -0.90, -0.90, +0.60, +0.70) |
| `flat_low_vol` | (0, 0, 0, -0.80, -0.60) |
| `flat_high_vol` | (0, 0, 0, +0.80, +0.60) |
| `corner_plus` | (+1, +1, +1, +1, +1) |
| `corner_minus` | (-1, -1, -1, -1, -1) |

Criteria, unchanged from `PROTOCOL.md` §2: (i) no silent MBON readout in any
seed; (ii) mean Kenyon-cell active fraction below 0.25; (iii) pairwise
Kenyon-cell Jaccard below 0.40. Criterion (iii) is applied to the four nominal
*market states*; `corner_plus` is deliberately a more extreme `strong_up`, so a
low Jaccard between them would mean the encoder is discontinuous, not that it
discriminates. All fifteen pairs are reported anyway.

### Two rejected codings


| coding | per-ORN ceiling Hz | max KC fraction | max nominal KC Jaccard | silent | verdict |
|---|--:|--:|--:|--:|---|
| `balanced` | 150 | 0.249 | 0.775 | 0/48 | rejected — max nominal KC Jaccard 0.775 >= 0.4 |
| `balanced` | 90 | 0.198 | 0.673 | 0/48 | rejected — max nominal KC Jaccard 0.673 >= 0.4 |
| `rectified` | 150 | 0.257 | 0.678 | 0/48 | rejected — max KC fraction 0.257 >= 0.25; max nominal KC Jaccard 0.678 >= 0.4 |
| `rectified` | 90 | 0.209 | 0.572 | 1/48 | rejected — 1 silent MBON trials; max nominal KC Jaccard 0.572 >= 0.4 |

The two failures point in opposite directions and that is the whole finding.
`balanced` drives all ten glomeruli whatever the market does, so every state
recruits the same Kenyon cells (Jaccard 0.67-0.78) — lowering the ceiling from
150 to 90 Hz barely moves it. `rectified` separates the states, but couples
discrimination to drive: it reaches Jaccard 0.57 at 90 Hz only by starting to
fall silent. A wider exploration of that coding, over per-ORN ceiling
{150, 120, 90, 60, 40} Hz x carrier {0.30, 0.20, 0.10, 0.05, 0.00}, found no
cell satisfying all three criteria: the single cell reaching Jaccard < 0.40
(40 Hz / 0.05, Jaccard 0.366) had 5 silent trials of 48, and no cell with zero
silent trials fell below Jaccard 0.59. The four cells in the table above are
the ones the script still reproduces; they are representative of that boundary.
Constant-budget normalisation is what breaks the coupling.

### The declared range

| budget Hz | carrier | KC fraction min..max | max nominal KC Jaccard | max KC Jaccard, all pairs | silent | saturated | verdict |
|--:|--:|---|--:|--:|--:|--:|---|
| 24000 | 0.20 | 0.052..0.136 | 0.657 | 0.684 | 0/48 | 0/48 | fail — max nominal KC Jaccard 0.657 >= 0.4 |
| 24000 | 0.10 | 0.048..0.169 | 0.638 | 0.660 | 0/48 | 0/48 | fail — max nominal KC Jaccard 0.638 >= 0.4 |
| 24000 | 0.05 | 0.039..0.177 | 0.696 | 0.696 | 0/48 | 0/48 | fail — max nominal KC Jaccard 0.696 >= 0.4 |
| 18000 | 0.20 | 0.031..0.091 | 0.625 | 0.625 | 1/48 | 0/48 | fail — 1 silent MBON trials; max nominal KC Jaccard 0.625 >= 0.4 |
| 18000 | 0.10 | 0.018..0.129 | 0.548 | 0.589 | 0/48 | 0/48 | fail — max nominal KC Jaccard 0.548 >= 0.4 |
| 18000 | 0.05 | 0.020..0.160 | 0.590 | 0.671 | 0/48 | 0/48 | fail — max nominal KC Jaccard 0.590 >= 0.4 |
| 12000 | 0.20 | 0.015..0.058 | 0.383 | 0.550 | 1/48 | 0/48 | fail — 1 silent MBON trials |
| 12000 | 0.10 | 0.010..0.084 | 0.368 | 0.526 | 0/48 | 0/48 | **PASS** |
| 12000 | 0.05 | 0.017..0.115 | 0.417 | 0.528 | 0/48 | 0/48 | fail — max nominal KC Jaccard 0.417 >= 0.4 |
| 8000 | 0.20 | 0.004..0.023 | 0.305 | 0.325 | 6/48 | 0/48 | fail — 6 silent MBON trials |
| 8000 | 0.10 | 0.003..0.033 | 0.245 | 0.461 | 2/48 | 0/48 | fail — 2 silent MBON trials |
| 8000 | 0.05 | 0.004..0.049 | 0.233 | 0.407 | 2/48 | 0/48 | fail — 2 silent MBON trials |
| 5000 | 0.20 | 0.000..0.004 | 0.057 | 0.324 | 26/48 | 0/48 | fail — 26 silent MBON trials |
| 5000 | 0.10 | 0.000..0.009 | 0.153 | 0.166 | 21/48 | 0/48 | fail — 21 silent MBON trials |
| 5000 | 0.05 | 0.000..0.021 | 0.235 | 0.277 | 16/48 | 0/48 | fail — 16 silent MBON trials |

**Declared input operating range: drive budget 12,000 Hz, carrier 0.10.** One
cell of fifteen satisfies all three criteria, by the declared rule (largest
budget that passes, then smallest carrier). At that point the encoder is
neither silent nor saturated for any of the six patterns at any of the eight
seeds, Kenyon-cell recruitment runs 0.010-0.084 and the four market states are
pairwise distinguishable at Jaccard 0.167-0.368.

### Addendum-2 table — gain sensitivity, report only

Gains {0.08, 0.10, 0.12} x 8 seeds x six patterns, at the declared range. The
gain stays 0.10 whatever this says; it is a sensitivity check, not a selection.

| gain | pattern | max ORN Hz | MBON mean Hz | MBON SD across seeds | PAM-side Hz | PPL1-side Hz | KC fraction | silent | saturated |
|--:|---|--:|--:|--:|--:|--:|--:|--:|--:|
| 0.08 | `strong_up` | 36 | 0.90 | 0.60 | 0.15 | 1.45 | 0.001 | 1/8 | 0/8 |
| 0.08 | `strong_down` | 35 | 0.71 | 0.38 | 0.00 | 1.23 | 0.000 | 0/8 | 0/8 |
| 0.08 | `flat_low_vol` | 72 | 0.26 | 0.28 | 0.00 | 0.45 | 0.000 | 4/8 | 0/8 |
| 0.08 | `flat_high_vol` | 70 | 0.52 | 0.28 | 0.00 | 0.89 | 0.001 | 1/8 | 0/8 |
| 0.08 | `corner_plus` | 30 | 1.03 | 0.39 | 0.00 | 1.79 | 0.001 | 0/8 | 0/8 |
| 0.08 | `corner_minus` | 33 | 0.64 | 0.82 | 0.61 | 0.67 | 0.000 | 4/8 | 0/8 |
| 0.10 | `strong_up` | 36 | 11.15 | 6.40 | 13.87 | 9.15 | 0.048 | 0/8 | 0/8 |
| 0.10 | `strong_down` | 35 | 6.06 | 6.49 | 6.10 | 6.03 | 0.022 | 0/8 | 0/8 |
| 0.10 | `flat_low_vol` | 72 | 3.61 | 2.61 | 4.12 | 3.24 | 0.010 | 0/8 | 0/8 |
| 0.10 | `flat_high_vol` | 70 | 13.92 | 7.32 | 15.55 | 12.72 | 0.063 | 0/8 | 0/8 |
| 0.10 | `corner_plus` | 30 | 20.10 | 10.11 | 23.78 | 17.41 | 0.084 | 0/8 | 0/8 |
| 0.10 | `corner_minus` | 33 | 9.54 | 7.58 | 11.28 | 8.26 | 0.038 | 0/8 | 0/8 |
| 0.12 | `strong_up` | 36 | 60.82 | 21.13 | 71.19 | 53.24 | 0.296 | 0/8 | 0/8 |
| 0.12 | `strong_down` | 35 | 35.37 | 11.16 | 40.85 | 31.36 | 0.173 | 0/8 | 0/8 |
| 0.12 | `flat_low_vol` | 72 | 16.37 | 5.60 | 17.38 | 15.62 | 0.067 | 0/8 | 0/8 |
| 0.12 | `flat_high_vol` | 70 | 55.93 | 8.49 | 65.70 | 48.77 | 0.256 | 0/8 | 0/8 |
| 0.12 | `corner_plus` | 30 | 60.24 | 17.53 | 70.12 | 53.01 | 0.306 | 0/8 | 0/8 |
| 0.12 | `corner_minus` | 33 | 32.86 | 14.44 | 38.11 | 29.02 | 0.157 | 0/8 | 0/8 |

Pairwise discrimination at gain 0.10 (KC Jaccard, mean over seeds; nominal pairs first):

| pattern pair | KC Jaccard | abs valence gap Hz |
|---|--:|--:|
| strong_up vs strong_down | 0.279 | 4.65 |
| strong_up vs flat_low_vol | 0.179 | 3.84 |
| strong_up vs flat_high_vol | 0.368 | 1.89 |
| strong_down vs flat_low_vol | 0.329 | 0.81 |
| strong_down vs flat_high_vol | 0.273 | 2.75 |
| flat_low_vol vs flat_high_vol | 0.167 | 1.95 |
| strong_up vs corner_plus | 0.526 | 1.65 |
| strong_up vs corner_minus | 0.384 | 1.70 |
| strong_down vs corner_plus | 0.254 | 6.30 |
| strong_down vs corner_minus | 0.353 | 2.95 |
| flat_low_vol vs corner_plus | 0.120 | 5.49 |
| flat_low_vol vs corner_minus | 0.300 | 2.14 |
| flat_high_vol vs corner_plus | 0.428 | 3.54 |
| flat_high_vol vs corner_minus | 0.369 | 0.20 |
| corner_plus vs corner_minus | 0.339 | 3.35 |

Baseline readout SD across the 8 seeds, per pattern — the unit the decoder's WAIT margin is expressed in:

| pattern | PAM-side SD Hz | PPL1-side SD Hz | (PPL1 - PAM) SD Hz |
|---|--:|--:|--:|
| `strong_up` | 8.295 | 5.068 | 3.505 |
| `strong_down` | 7.141 | 6.070 | 1.703 |
| `flat_low_vol` | 4.321 | 1.504 | 3.114 |
| `flat_high_vol` | 8.788 | 6.327 | 3.025 |
| `corner_plus` | 11.788 | 9.130 | 4.378 |
| `corner_minus` | 9.143 | 6.504 | 3.117 |

Mean (PPL1 - PAM) SD over the six patterns: **3.140 Hz**; max 4.378 Hz.

**The operating point is narrow and this is the wave's main instability.** A
20% cut in gain (0.10 -> 0.08) collapses the encoder into near-silence: Kenyon
recruitment falls to 0.000-0.001, and 10 of 48 trials produce no MBON spike at
all. A 20% rise (0.10 -> 0.12) pushes recruitment to 0.306, past the 0.25
criterion, and Jaccard to 0.687 — the beginnings of the saturated regime
Phase 0.5 documented. Gain 0.10 is not a comfortable plateau; it is a ledge
between silence and saturation, roughly one decade of MBON rate wide in each
direction. Everything downstream inherits that.

Seed-to-seed variation is large at the operating point: the MBON population
mean moves by 2.6-10.1 Hz SD across eight seeds against means of 3.6-20.1 Hz.
The readout is a noisy measurement of a sparse code, which is why the decoder's
WAIT margin is expressed in units of that noise and not in Hz picked by hand.

### Part C — baseline readout at the neutral reference (u = 0, gain 0.10, unlearned weights, 8 seeds)

| quantity | mean | SD across seeds |
|---|--:|--:|
| PAM-side rate, Hz | 6.555 | 4.560 |
| PPL1-side rate, Hz | 4.129 | 3.373 |
| difference PPL1 - PAM, Hz | -2.425 | 1.873 |
| PAM-side rate, attributed subset (29 of 41), Hz | 5.819 | 3.793 |
| PPL1-side rate, attributed subset (16 of 56), Hz | 3.516 | 5.132 |
| **difference, attributed subset, Hz** | **-2.3033** | **3.2414** |
| Kenyon-cell active fraction | 0.0250 | — |

Per-ORN drive at the reference 17.1 Hz, total 12,000 Hz, silent trials 0/8.

This is the baseline the decoder's margin rule is calibrated against; see
`docs/DECODER.md`. It is measured **before** any decoder exists, with unlearned
weights, at the declared operating range, over the eight declared seeds.

## 5. Timing and seeds

| clock | unit | value |
|---|---|---|
| market time | one bar | 3,600 s in the synthetic fixtures; whatever the CSV says otherwise |
| simulation time | one decision cycle | 500 ms (`flytrade/state.py`) |
| presentation | one brain window | 20 ms = 100 x 0.2 ms steps |

The encoder itself is **deterministic and seedless**: the same observation
always produces the same drive dict. Randomness enters one step later, in the
Poisson drive of `flysim.FlyBrain.run`, whose seed is
`hash(round_seed, candidate_stable_id)` (Fable addendum 5) and is recorded in
every `DecisionRecord`. The stable id is assigned at universe registration and
is independent of the symbol string and of position in any list, which is what
makes the renaming and permutation tests in `tests/phase_one/` meaningful.

## 6. Where the synthetic fixtures land in the declared range

Over 4 seeded synthetic series, 196 usable observations (every 7th bar),
per-feature mean `|u|`: `r1` 0.350, `r5` 0.358, `r20` 0.425, `rv20` 0.467,
`relvol` 0.344. The fixtures exercise the middle of the declared range and
reach the corners rarely, which is the intended relationship between the
nominal patterns (which probe the boundary) and the demonstration data (which
lives inside it).
