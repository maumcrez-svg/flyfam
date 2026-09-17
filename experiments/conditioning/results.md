# Conditioning results

Produced by `experiments/conditioning/run.py` against the protocol pre-registered in `PROTOCOL.md`. Every number here comes from that run; nothing is hand-entered.

* graph `8feb08a0d2a8` · modulatory `22b29abc1a30` · plasticity `flytrade-mb-1` · odours `flytrade-odour-1`
* odour A = DL2d, DL2v, VL2a, DM6, VC3 (228 ORNs); odour B = VM5d, DA2, VM4, DM5, VM7d (281 ORNs)
* global gain 0.1, drive 150.0 Hz, 100 steps (20 ms), 20 training trials, seeds [1, 2, 3, 4, 5, 6, 7, 8]
* readout: 56 PPL1-innervated MBONs (secondary: 41 PAM-innervated)
* python 3.13.9, numpy 2.4.2, 19.0 s

## Table 1 — which weights changed

Of the 44,042 KC→MBON synapses. Reinforcement addresses the PPL1-innervated compartment only.

| condition | seed | synapses moved | PPL1-side | PAM-side | mean gain (moved) | min gain | total |Δw| mV |
|---|--:|--:|--:|--:|--:|--:|--:|
| PAIRED_ON | 1 | 6,818 | 6,818 | 0 | 0.4853 | 0.2949 | 7968.2 |
| PAIRED_ON | 2 | 7,214 | 7,214 | 0 | 0.4950 | 0.2949 | 8289.6 |
| PAIRED_ON | 3 | 7,477 | 7,477 | 0 | 0.5135 | 0.2949 | 8279.0 |
| PAIRED_ON | 4 | 6,536 | 6,536 | 0 | 0.5025 | 0.2949 | 7392.1 |
| PAIRED_ON | 5 | 6,854 | 6,854 | 0 | 0.5102 | 0.2949 | 7640.0 |
| PAIRED_ON | 6 | 7,661 | 7,661 | 0 | 0.5701 | 0.2949 | 7503.8 |
| PAIRED_ON | 7 | 6,621 | 6,621 | 0 | 0.4851 | 0.2949 | 7758.8 |
| PAIRED_ON | 8 | 6,764 | 6,764 | 0 | 0.4782 | 0.2949 | 8035.3 |
| PAIRED_OFF | 1 | 0 | 0 | 0 | 1.0000 | 1.0000 | 0.0 |
| PAIRED_OFF | 2 | 0 | 0 | 0 | 1.0000 | 1.0000 | 0.0 |
| PAIRED_OFF | 3 | 0 | 0 | 0 | 1.0000 | 1.0000 | 0.0 |
| PAIRED_OFF | 4 | 0 | 0 | 0 | 1.0000 | 1.0000 | 0.0 |
| PAIRED_OFF | 5 | 0 | 0 | 0 | 1.0000 | 1.0000 | 0.0 |
| PAIRED_OFF | 6 | 0 | 0 | 0 | 1.0000 | 1.0000 | 0.0 |
| PAIRED_OFF | 7 | 0 | 0 | 0 | 1.0000 | 1.0000 | 0.0 |
| PAIRED_OFF | 8 | 0 | 0 | 0 | 1.0000 | 1.0000 | 0.0 |
| UNPAIRED | 1 | 0 | 0 | 0 | 1.0000 | 1.0000 | 0.0 |
| UNPAIRED | 2 | 0 | 0 | 0 | 1.0000 | 1.0000 | 0.0 |
| UNPAIRED | 3 | 0 | 0 | 0 | 1.0000 | 1.0000 | 0.0 |
| UNPAIRED | 4 | 0 | 0 | 0 | 1.0000 | 1.0000 | 0.0 |
| UNPAIRED | 5 | 0 | 0 | 0 | 1.0000 | 1.0000 | 0.0 |
| UNPAIRED | 6 | 0 | 0 | 0 | 1.0000 | 1.0000 | 0.0 |
| UNPAIRED | 7 | 0 | 0 | 0 | 1.0000 | 1.0000 | 0.0 |
| UNPAIRED | 8 | 0 | 0 | 0 | 1.0000 | 1.0000 | 0.0 |
| OTHER_ODOUR | 1 | 2,697 | 2,697 | 0 | 0.6377 | 0.2949 | 2287.6 |
| OTHER_ODOUR | 2 | 2,883 | 2,883 | 0 | 0.7254 | 0.2949 | 1850.7 |
| OTHER_ODOUR | 3 | 3,239 | 3,239 | 0 | 0.7196 | 0.2949 | 2116.0 |
| OTHER_ODOUR | 4 | 3,188 | 3,188 | 0 | 0.6979 | 0.3133 | 2236.2 |
| OTHER_ODOUR | 5 | 3,137 | 3,137 | 0 | 0.7196 | 0.2949 | 2055.7 |
| OTHER_ODOUR | 6 | 3,333 | 3,333 | 0 | 0.6939 | 0.2949 | 2386.5 |
| OTHER_ODOUR | 7 | 3,061 | 3,061 | 0 | 0.6964 | 0.2949 | 2173.8 |
| OTHER_ODOUR | 8 | 3,359 | 3,359 | 0 | 0.7102 | 0.3134 | 2279.8 |

## Table 2 — which neural responses changed

Firing rate in Hz, mean over the population, 20 ms window. `pre` and `post` use the same measurement seed, so a difference can only come from the weights.

| condition | seed | A PPL1 pre → post | Δ | B PPL1 pre → post | Δ | A PAM Δ | A KC frac Δ |
|---|--:|---|--:|---|--:|--:|--:|
| PAIRED_ON | 1 | 41.07 → 13.39 | -27.68 | 22.32 → 7.14 | -15.18 | +4.88 | -0.0017 |
| PAIRED_ON | 2 | 44.64 → 14.29 | -30.36 | 32.14 → 10.71 | -21.43 | +10.98 | +0.0002 |
| PAIRED_ON | 3 | 27.68 → 7.14 | -20.54 | 2.68 → 1.79 | -0.89 | +4.88 | -0.0002 |
| PAIRED_ON | 4 | 32.14 → 10.71 | -21.43 | 29.46 → 7.14 | -22.32 | +3.66 | +0.0027 |
| PAIRED_ON | 5 | 46.43 → 11.61 | -34.82 | 15.18 → 6.25 | -8.93 | +1.22 | -0.0153 |
| PAIRED_ON | 6 | 27.68 → 8.04 | -19.64 | 4.46 → 1.79 | -2.68 | +2.44 | +0.0002 |
| PAIRED_ON | 7 | 16.07 → 4.46 | -11.61 | 15.18 → 6.25 | -8.93 | +3.66 | -0.0020 |
| PAIRED_ON | 8 | 43.75 → 11.61 | -32.14 | 6.25 → 4.46 | -1.79 | +2.44 | +0.0273 |
| PAIRED_OFF | 1 | 41.07 → 41.07 | +0.00 | 22.32 → 22.32 | +0.00 | +0.00 | +0.0000 |
| PAIRED_OFF | 2 | 44.64 → 44.64 | +0.00 | 32.14 → 32.14 | +0.00 | +0.00 | +0.0000 |
| PAIRED_OFF | 3 | 27.68 → 27.68 | +0.00 | 2.68 → 2.68 | +0.00 | +0.00 | +0.0000 |
| PAIRED_OFF | 4 | 32.14 → 32.14 | +0.00 | 29.46 → 29.46 | +0.00 | +0.00 | +0.0000 |
| PAIRED_OFF | 5 | 46.43 → 46.43 | +0.00 | 15.18 → 15.18 | +0.00 | +0.00 | +0.0000 |
| PAIRED_OFF | 6 | 27.68 → 27.68 | +0.00 | 4.46 → 4.46 | +0.00 | +0.00 | +0.0000 |
| PAIRED_OFF | 7 | 16.07 → 16.07 | +0.00 | 15.18 → 15.18 | +0.00 | +0.00 | +0.0000 |
| PAIRED_OFF | 8 | 43.75 → 43.75 | +0.00 | 6.25 → 6.25 | +0.00 | +0.00 | +0.0000 |
| UNPAIRED | 1 | 41.07 → 41.07 | +0.00 | 22.32 → 22.32 | +0.00 | +0.00 | +0.0000 |
| UNPAIRED | 2 | 44.64 → 44.64 | +0.00 | 32.14 → 32.14 | +0.00 | +0.00 | +0.0000 |
| UNPAIRED | 3 | 27.68 → 27.68 | +0.00 | 2.68 → 2.68 | +0.00 | +0.00 | +0.0000 |
| UNPAIRED | 4 | 32.14 → 32.14 | +0.00 | 29.46 → 29.46 | +0.00 | +0.00 | +0.0000 |
| UNPAIRED | 5 | 46.43 → 46.43 | +0.00 | 15.18 → 15.18 | +0.00 | +0.00 | +0.0000 |
| UNPAIRED | 6 | 27.68 → 27.68 | +0.00 | 4.46 → 4.46 | +0.00 | +0.00 | +0.0000 |
| UNPAIRED | 7 | 16.07 → 16.07 | +0.00 | 15.18 → 15.18 | +0.00 | +0.00 | +0.0000 |
| UNPAIRED | 8 | 43.75 → 43.75 | +0.00 | 6.25 → 6.25 | +0.00 | +0.00 | +0.0000 |
| OTHER_ODOUR | 1 | 41.07 → 27.68 | -13.39 | 22.32 → 13.39 | -8.93 | +2.44 | -0.0081 |
| OTHER_ODOUR | 2 | 44.64 → 38.39 | -6.25 | 32.14 → 14.29 | -17.86 | +2.44 | +0.0000 |
| OTHER_ODOUR | 3 | 27.68 → 22.32 | -5.36 | 2.68 → 1.79 | -0.89 | +1.22 | +0.0000 |
| OTHER_ODOUR | 4 | 32.14 → 24.11 | -8.04 | 29.46 → 18.75 | -10.71 | -1.22 | +0.0000 |
| OTHER_ODOUR | 5 | 46.43 → 33.93 | -12.50 | 15.18 → 8.04 | -7.14 | -2.44 | -0.0066 |
| OTHER_ODOUR | 6 | 27.68 → 17.86 | -9.82 | 4.46 → 1.79 | -2.68 | -1.22 | +0.0000 |
| OTHER_ODOUR | 7 | 16.07 → 13.39 | -2.68 | 15.18 → 8.04 | -7.14 | +2.44 | -0.0012 |
| OTHER_ODOUR | 8 | 43.75 → 25.00 | -18.75 | 6.25 → 4.46 | -1.79 | -1.22 | +0.0258 |

## Table 3 — the association-dependent effect

Primary metric: `assoc(s) = ΔA_ppl1[PAIRED_ON] − ΔA_ppl1[UNPAIRED]`, predicted negative.

| seed | ΔA_ppl1 paired | ΔA_ppl1 unpaired | assoc | sign | ΔA_ppl1 other-odour | ΔA−ΔB paired |
|--:|--:|--:|--:|:--|--:|--:|
| 1 | -27.679 | +0.000 | -27.679 | − | -13.393 | -12.500 |
| 2 | -30.357 | +0.000 | -30.357 | − | -6.250 | -8.929 |
| 3 | -20.536 | +0.000 | -20.536 | − | -5.357 | -19.643 |
| 4 | -21.429 | +0.000 | -21.429 | − | -8.036 | +0.893 |
| 5 | -34.821 | +0.000 | -34.821 | − | -12.500 | -25.893 |
| 6 | -19.643 | +0.000 | -19.643 | − | -9.821 | -16.964 |
| 7 | -11.607 | +0.000 | -11.607 | − | -2.679 | -2.679 |
| 8 | -32.143 | +0.000 | -32.143 | − | -18.750 | -30.357 |

**Sign test.** 8 of 8 seeds negative (one-sided, threshold 7/8, p = 9/256 = 0.035). Mean effect -24.777 Hz (threshold 1.0 Hz). Plasticity-off condition moved nothing: True.

**Verdict: PASS** against the decision rule in PROTOCOL.md §7.

### Secondary metrics (pre-registered, not gating)

| metric | mean over seeds | seeds with the predicted sign |
|---|--:|--:|
| stimulus specificity within a run, ΔA−ΔB in PAIRED_ON | -14.509 Hz | 7/8 |
| odour specificity, ΔA[PAIRED_ON]−ΔA[OTHER_ODOUR] | -15.179 Hz | 8/8 |
| compartment not addressed, ΔA_pam in PAIRED_ON | +4.268 Hz | — |
| Kenyon-cell active fraction, ΔA in PAIRED_ON | +0.00141 | — |

### Reading the controls honestly

* `UNPAIRED` is **exactly zero in every seed, by construction**: after six decay-only cycles no synapse is eligible, so the dopamine event depresses nothing. It proves the eligibility gate works; it is not on its own evidence of association, because it produces no weight change to compare against.
* `OTHER_ODOUR` is the informative control: it delivers the same 20 dopamine events, paired with a real odour, and does change weights. Compare its effect on A with the paired condition's.
* Odour B is depressed too in `PAIRED_ON`. That is expected and is not a defect: A and B share Kenyon cells (measured Jaccard overlap 0.27), and a shared KC→MBON synapse depressed for A is depressed for B as well. The question the primary metric asks is whether A moves *more*.
* Only synapses in the addressed compartment move. The PAM-side response drifts in the opposite direction; it is a network consequence of the PPL1-side MBONs going quiet, not plasticity, since no PAM-side synapse changed at all.

## Deviations from PROTOCOL.md

None.
