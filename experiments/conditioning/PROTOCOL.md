# Conditioning protocol — pre-registration

**This file is committed before `run.py` is executed.** The commit that adds it
contains nothing else; the SHA ordering in `git log` is the evidence that the
readout, the conditions, the metric and the decision rule were fixed before any
conditioning result existed. Any later change is recorded as a **deviation** in
`results.md`, with the reason, and never by editing this file silently.

Canonical amendment §5. Nothing here is about markets: there is no instrument,
no price, no profit, and no decoder. The question is only whether a stimulus
paired with reinforcement changes the later neural response to that stimulus,
causally and reproducibly.

## 1. Fixed material

| | |
|---|---|
| connectome | `data/malecns-v1.0/graph.npz`, sha256 `8feb08a0d2a80cbcf69328f9707d5dd748d73d2e12246526d96e48d995f843b9` |
| modulatory matrix | `data/malecns-v1.0/graph_mod.npz`, threshold ≥1 synapse |
| simulator | `upstream/flysim.py` at commit `5aab4e7895a1f5930319bf3bde8010b350a163a2`, unmodified |
| plasticity | `flytrade/mushroom.py`, version `flytrade-mb-1` |
| neurons | 165,122 · KC 4,064 · MBON 97 · PAM 316 · PPL1 16 |
| plastic synapses | 44,042 KC→MBON (24,005 PAM-side, 20,037 PPL1-side) |

## 2. Operating point, and why

Measured before this protocol was written, from the sensory-path diagnosis
(`docs/ARCHITECTURE.md`, "Operating point"). With `gains=None` — every synapse
at its full 0.275 mV — the network saturates: driving 204 ORNs at 100 Hz makes
**every** Kenyon cell and **every** MBON fire at ~440 Hz, 39,448 of 165,122
neurons spike in 20 ms, and the MBON response is identical for two completely
different odours. In that regime nothing can be learned because nothing is
selective, and the readout is pinned against the 454 Hz refractory ceiling.

`flysim.run(gains=...)` is upstream's own free parameter for exactly this —
synaptic efficacy is the one thing EM cannot measure (`flysim.py:11-13`). We
set a **single uniform scalar** `g` for every cell type. It is a modelling
choice, ours, and it is declared here rather than tuned later:

> **g = 0.10.** Chosen as the largest value in {0.09, 0.10, …, 0.14} for which,
> over 8 seeds: (i) neither odour produced a silent MBON readout in any seed,
> (ii) the mean Kenyon-cell active fraction stayed below 0.25 for both odours,
> and (iii) the Kenyon-cell Jaccard overlap between the two odours stayed below
> 0.40. Measured values at g = 0.10: KC active fraction 0.227 (A) and 0.067
> (B), Jaccard 0.268, MBON mean 48.0 Hz (A) and 15.2 Hz (B), 0 silent trials.
> At g = 0.11 the KC fraction for A is 0.335 and criterion (ii) fails.

Criterion (ii) is anchored on the sparse, decorrelated Kenyon-cell code
measured in *Drosophila* — a few per cent to ~20% of KCs respond to an odour
(Turner, Bazhenov & Laurent 2008, *J Neurophysiol* 99:734; Honegger, Campbell &
Turner 2011, *J Neurosci* 31:11772; Lin, Bygrave, de Calignon et al. 2014,
*Nat Neurosci* 17:559). Our model has no spike-frequency adaptation, so it is
not expected to reproduce those numbers exactly; the criterion is a guard
against the saturated regime, not a claim of biological fidelity.

Other fixed parameters: **drive 150 Hz** per stimulated ORN (within the range
of measured *Drosophila* ORN odour responses, de Bruyne, Foster & Carlson 2001,
*Neuron* 30:537); **window 100 steps × 0.2 ms = 20 ms** of brain time per
presentation, which is upstream's own control step; `lr = 0.06`,
`floor = 0.25`, `recover = 0.0008`, `trace_decay = 0.55` per decision cycle,
all upstream's defaults, carried unchanged.

## 3. Stimuli

Chosen on sensory-path grounds only, before any conditioning run
(`docs/POPULATIONS.md`, last section):

* candidates = the 50 glomeruli with both ORNs and uniglomerular PNs, minus the
  four pheromone channels DA1, VA1v, VA1d, DL3 (PNs biased to the lateral horn
  rather than the calyx; Jefferis, Potter, Chan et al. 2007, *Cell* 128:1187);
* take the ten candidates with the most uniglomerular PNs, ties alphabetical,
  and snake-draft them into two sets, which balances uPN count.

| | glomeruli | ORNs driven | uPNs |
|---|---|---:|---:|
| **odour A** | DL2d, DL2v, VL2a, DM6, VC3 | 228 | 43 |
| **odour B** | VM5d, DA2, VM4, DM5, VM7d | 281 | 44 |

A and B share no glomerulus. A is the CS+ (reinforced) because it drives the
mushroom body more strongly of the two — a sensory-path fact, established
before any reinforcement was ever delivered.

## 4. Reinforcement

`MushroomBody.dopamine(valence=-1, amount=1.0)` — the **PPL1-innervated**
compartment, i.e. aversive. One event per training trial, immediately after the
odour presentation, in the same episode.

**Predicted direction, pre-registered.** The measured rule in *Drosophila* is
that dopamine arriving shortly after Kenyon-cell activity **depresses** that
KC→MBON synapse in the compartment the dopaminergic neuron innervates; there is
no potentiation (Hige, Aso, Modi, Rubin & Turner 2015, *Neuron* 88:985; Cohn,
Morantte & Ruta 2015, *Cell* 163:1742; Aso & Rubin 2016, *eLife* 5:e16135).
Upstream implements depression with a floor and a slow drift back to baseline,
and that part of upstream is correct and is kept unchanged — only the
compartment assignment was wrong. **We therefore predict that the response of
the PPL1-innervated MBONs to odour A goes DOWN after paired training, and that
this decrease is larger than in every control condition.** The sign is fixed
here and will not be flipped after seeing results.

## 5. Conditions

Each of the four conditions runs independently, from a fresh set of weights
(all gains reset to 1.0, all traces cleared), for every seed.

| | name | training trial |
|---|---|---|
| i | `PAIRED_ON` | present A (20 ms) → `observe(fired)` → `dopamine(-1)` → `apply()` → `forget()` |
| ii | `PAIRED_OFF` | identical schedule and seeds, but `dopamine()` and `apply()` are never called |
| iii | `UNPAIRED` | present A → **6 decay-only cycles** (`observe(None)`; 0.55⁶ = 0.0277 < 0.05, so no synapse is eligible) → `dopamine(-1)` → `apply()` → `forget()` |
| iv | `OTHER_ODOUR` | present **B** → `observe` → `dopamine(-1)` → `apply()` → `forget()`; A is never reinforced |

20 training trials per condition, matching the "twenty encounters" upstream
reports. (iii) tests temporal contiguity — the same number of odour
presentations and the same number of dopamine events, never coincident. (iv)
tests stimulus specificity — real weight change, driven by a different odour.
Odour B is additionally a within-run never-reinforced control in (i) and (iii).

## 6. Measurement

Before training and after training, present A and then B once each and record
firing rates. Measurement runs never call `observe`, `dopamine` or `apply`:
they only read.

* **Primary readout:** mean firing rate over the **56 PPL1-innervated MBON
  neurons** (the compartment the reinforcement addresses), in the 20 ms window.
* **Secondary readout:** mean firing rate over the 41 PAM-innervated MBONs (the
  compartment no dopamine addressed), and the Kenyon-cell active fraction
  (upstream of the plastic synapse; must not move).
* The **same measurement seed** is used pre and post within a realization, so a
  difference can only come from the weights. Training uses different seeds, so
  training is not a replay of the measurement.

Seeds, 8 realizations `s = 1…8`: measurement seed `1000 + s`; training-trial
seed `2000 + 100·s + trial`.

## 7. Primary metric and decision rule

For odour X and readout R, `Δ = rate_post(X, R) − rate_pre(X, R)`.

**Primary, association-specific effect, per seed:**

```
assoc(s) = ΔA_ppl1 [PAIRED_ON](s) − ΔA_ppl1 [UNPAIRED](s)
```

Predicted **negative**. Sign test across the 8 seeds, one-sided.

**"The response was modified by experience, causally and reproducibly" counts
as demonstrated iff all three hold:**

1. `assoc(s) < 0` in **at least 7 of 8** seeds (one-sided sign test,
   p = 9/256 = 0.035);
2. `ΔA_ppl1[PAIRED_OFF](s) == 0` for every seed — nothing moves without
   plasticity;
3. `mean |assoc| ≥ 1.0 Hz` — a numerically trivial change does not pass.

If any of the three fails, the demonstration fails and is reported as failing.

**Secondary metrics, reported but not gating:**

* stimulus specificity within a run: `ΔA_ppl1 − ΔB_ppl1` in `PAIRED_ON`;
* odour specificity: `ΔA_ppl1[PAIRED_ON] − ΔA_ppl1[OTHER_ODOUR]`;
* compartment specificity: `ΔA_pam` in `PAIRED_ON`;
* Kenyon-cell active fraction, pre vs post, in every condition.

## 8. Output

`run.py` writes `results.json` (machine-readable, every seed and condition) and
`results.md` with **three separate tables**:

1. **weights changed** — how many of the 44,042 KC→MBON synapses moved, by
   compartment, with mean/min gain and the total change in mV;
2. **neural responses changed** — per readout, per condition, per seed, pre and
   post;
3. **association-dependent effect** — the primary metric per seed, the sign
   test, and the verdict against the decision rule above.

No post-hoc change to the readout. If anything must change, it is written into
`results.md` as a deviation with its reason, and this file stays as it is.
