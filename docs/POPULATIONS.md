# Populations — MaleCNS v1.0, measured

Every number here comes from `data/malecns-v1.0/annotations.npz` and
`graph.npz`, built by `flytrade/graph.py` from the three feather tables in
`data/MANIFEST.md`. Nothing is quoted from a README.

Each population is given in the owner's three-way split:

* **(a) observed connectivity** — what the dataset says, no interpretation;
* **(b) literature interpretation** — what the field says the population does,
  with a citation, kept separate from (a);
* **(c) our modelling rule** — the choice *we* made, which is neither (a) nor
  (b) and must never be presented as either.

## The annotation fields

Distinct values, counted over the 165,122 traced non-glia neurons:

| field | distinct | notes |
|---|---:|---|
| `status` | 1 | every neuron in the index is `Traced`, by construction |
| `statusLabel` | 7 | `Roughly traced` 71,979 · `Reviewed` 54,066 · `Prelim Roughly traced` 36,387 · `RT Hard to trace` 2,019 · `Leaves` 528 · `PRT Orphan` 140 · `RT Orphan` 3 |
| `superclass` | 27 | `ol_intrinsic` 89,390 · `cb_intrinsic` 32,160 · `vnc_intrinsic` 13,151 · `visual_projection` 9,201 · `vnc_sensory` 6,365 · `cb_sensory` 4,868 · `ol_sensory` 4,114 · `ascending_neuron` 1,846 · `descending_neuron` 1,314 · `vnc_motor` 708 · … |
| `class` | 22 | empty for 140,598. Non-empty: `visual` 4,107 · `Kenyon_Cell` 4,064 · `CX` 2,950 · `olfactory` 2,639 · `mechanosensory_tactile` 2,558 · `mechanosensory` 1,733 · `unknown_sensory` 1,707 · `mechanosensory_proprioceptive` 1,454 · `gustatory` 1,428 · `ALPN` 686 · `ALLN` 420 · `DAN` 340 · `ol_bilateral` 116 · `MBON` 97 · `hygrosensory` 66 · `chemosensory` 58 · `SEZPN` 27 · `thermosensory` 25 · `ALIN` 24 · `ALON` 14 · `mechanosensory_tbc` 11 |
| `subclass` | 50 | empty for 143,198; mostly sensory-organ subtypes (`mechanosensory bristle`, `chordotonal organ`, …) and optic-lobe codes |
| `somaSide` | 4 | `R` 74,430 · `L` 74,220 · `` 16,080 · `M` 392 |
| `rootSide` | 4 | empty for 149,219 |
| `receptorType` | 1 | **empty for every traced neuron** — see the ORN ambiguity below |

`class` is the curated functional label and is the field we select on wherever
it exists. `type` (falling back to `flywireType`, then `instance`, exactly as
`build_graph.py:59` does) is what upstream matches regexes against.

## Counts

| population | selector (`flytrade/populations.py`) | count |
|---|---|---:|
| Kenyon cells | `class == Kenyon_Cell` | **4,064** |
| MBONs | `class == MBON` | **97** |
| — canonical `MBON<nn>` | `class == MBON` and type fullmatches `MBON\d+` | 87 |
| — `…-like` | the remainder | 10 |
| PAM | type `^PAM` | **316** |
| PPL1 | type `^PPL1` | **16** |
| PPL2 | type `^PPL2` | 8 |
| DAN (curated class) | `class == DAN` | 340 |
| dopaminergic (consensus NT) | `consensus_nt == dopamine` | 392 |
| APL | `type == APL` | **2** (1 L, 1 R) |
| ORNs | `class == olfactory` and type `^ORN_` | **2,635** across 53 glomeruli |
| uniglomerular AL PNs | `class == ALPN`, excluding `M_`/`MZ_`/`CB####` prefixes and names containing `+` | **284** across 55 glomerulus prefixes |
| all AL PNs | `class == ALPN` | 686 across 181 types |
| DNa02 | `type == DNa02` | **2** (1 L, 1 R) |
| DNa01 | `type == DNa01` | 2 (1 L, 1 R) |
| MDN | `type == MDN` | 4 (2 L, 2 R) |
| DNp09 | `type == DNp09` | 2 (1 L, 1 R) |
| MN9 | `type == MN9` | 2 (1 L, 1 R) |
| L1 | `type == L1` | 1,776 (1,767 with a hex column) |
| L2 | `type == L2` | 1,779 (1,767 with a hex column) |
| retinotopic hex columns | distinct `(assignedOlHex1, assignedOlHex2)` over L1 | **892** |

Kenyon-cell subtypes: `KCg-m` 1,342 · `KCab-s` 657 · `KCab-m` 536 ·
`KCab-c` 488 · `KCa'b'-ap2` 291 · `KCg-d` 206 · `KCa'b'-m` 205 ·
`KCa'b'-ap1` 199 · `KCab-p` 129 · `KCg-s1..s4` 2 each · `KC` 2 · `KCg` 1.

Neurotransmitters over the whole index: acetylcholine 103,718 · glutamate
29,296 · GABA 22,055 · histamine 5,910 · unclear 3,100 · unknown 502 ·
dopamine 392 · octopamine 101 · serotonin 48.

### Upstream's headline counts, checked

| upstream README claim | measured here | verdict |
|---|---|---|
| 165,122 traced neurons | 165,122 | **confirmed** |
| 10,228,000 signed edges | 10,228,000 | **confirmed** |
| 892 retinotopic hex columns | 892 | **confirmed** |
| 2,635 ORNs across 53 receptor types | 2,635 ORNs, 53 glomeruli | **confirmed** (as glomeruli, not receptors — see ambiguity 2) |
| 44,042 KC→MBON synapses | 44,042 | **confirmed** |
| 27,939 / 14,349 reward/punish split | reproduced exactly by running upstream over our `graph.npz` | **confirmed as upstream's output**, and it is the transposed read; the corrected read gives **24,005 / 20,037** |
| MBON01/02/03 reward-side, MBON04/10/11 punish-side | reproduced from upstream's code | **confirmed as upstream's output**; corrected read puts MBON04 and MBON10 on the PAM side |

## Comparison with upstream's selectors

| upstream | ours | difference |
|---|---|---|
| `^KC` (`mushroom.py:62`) | `class == Kenyon_Cell` | **none** — both select the same 4,064 |
| `^MBON` (`mushroom.py:63`) | `class == MBON` | **none** — same 97 |
| `^PAM` (`mushroom.py:64`) | type `^PAM` | **none** — same 316, all class `DAN`, all dopaminergic |
| `^PPL1` (`mushroom.py:64`) | type `^PPL1` | **none** — same 16. `^PPL1` silently excludes the 8 PPL2 neurons; that is correct (PPL2 is a different cluster) but it is accidental, not stated |
| `types == "L1"` **and** a hex assignment (`flyeye.py:26`) | same | none; 9 of 1,776 L1 neurons carry no hex column and are dropped |
| `fb.where(type_re="^DNa02$")` split by `somaSide` | same | none; 1 per side |

No selector mismatch was found. That is worth stating plainly: the population
selection in upstream is fine. The defect is in what it does with the matrix
afterwards.

## The DAN → MBON compartment map (corrected read)

Computed from `graph_mod.npz` as `D[mbon][:, dan].sum(axis=1)` — for each
MBON, the dopaminergic **synapses it receives**. Upstream computes
`W[dan][:, mbon].sum(axis=0)`, which under the `[post, pre]` convention is
MBON→DAN feedback (`docs/UPSTREAM_NOTES.md` §2).

**(a) observed.** Per MBON type: synapses received from PAM vs from PPL1.

| type | n | PAM syn | PPL1 syn | side | | type | n | PAM syn | PPL1 syn | side |
|---|--:|--:|--:|:--|---|---|--:|--:|--:|:--|
| MBON01 | 2 | 2,317 | 5 | PAM | | MBON19 | 4 | 0 | 108 | PPL1 |
| MBON02 | 2 | 1,327 | 10 | PAM | | MBON20 | 2 | 37 | 155 | PPL1 |
| MBON03 | 2 | 4,734 | 11 | PAM | | MBON21 | 2 | 1,147 | 21 | PAM |
| MBON04 | 2 | 1,746 | 279 | PAM | | MBON22 | 2 | 48 | 1 | PAM |
| MBON05 | 2 | 3,420 | 50 | PAM | | MBON23 | 2 | 2 | 130 | PPL1 |
| MBON06 | 2 | 3,918 | 45 | PAM | | MBON24 | 2 | 600 | 8 | PAM |
| MBON07 | 4 | 2,038 | 9 | PAM | | MBON25 | 2 | 5 | 124 | PPL1 |
| MBON09 | 4 | 3,618 | 23 | PAM | | MBON25-like | 4 | 2 | 109 | PPL1 |
| MBON10 | 9 | 415 | 31 | PAM | | MBON26 | 2 | 1,383 | 53 | PAM |
| MBON11 | 2 | 304 | 2,467 | PPL1 | | MBON27 | 2 | 603 | 25 | PAM |
| MBON12 | 4 | 22 | 852 | PPL1 | | MBON28 | 2 | 0 | 174 | PPL1 |
| MBON13 | 2 | 7 | 670 | PPL1 | | MBON29 | 2 | 493 | 15 | PAM |
| MBON14 | 4 | 0 | 864 | PPL1 | | MBON30 | 2 | 132 | 326 | PPL1 |
| MBON15 | 4 | 19 | 159 | PPL1 | | MBON31 | 2 | 34 | 735 | PPL1 |
| MBON15-like | 4 | 3 | 225 | PPL1 | | MBON32 | 2 | 9 | 1,074 | PPL1 |
| MBON16 | 2 | 0 | 303 | PPL1 | | MBON33 | 2 | 151 | 356 | PPL1 |
| MBON17 | 2 | 1 | 120 | PPL1 | | MBON34 | 2 | 3 | 14 | PPL1 |
| MBON17-like | 2 | 0 | 61 | PPL1 | | MBON35 | 2 | 8 | 1,017 | PPL1 |
| MBON18 | 2 | 0 | 441 | PPL1 | | | | | | |

Totals: **41 MBONs PAM-innervated, 56 PPL1-innervated, 0 unclassified**;
28,546 PAM synapses and 11,070 PPL1 synapses onto MBONs; **24,005 of the
44,042 KC→MBON synapses sit in a PAM-innervated compartment and 20,037 in a
PPL1-innervated one**.

Against upstream's transposed read, run over the same `graph.npz`:
**46 of 97 MBONs (47%) change side**, and **12,606 of 44,042 KC→MBON synapses
(28.6%) change compartment**. The ones that move include MBON04 (2 neurons)
and MBON10 (9 neurons) from punish-side to PAM-side, and MBON12, 13, 25,
25-like, 30, 31, 34 and 35 from reward-side to PPL1-side.

**(b) literature.** In *Drosophila* the mushroom-body lobes are divided into
15 compartments, each innervated by a distinct dopaminergic-neuron type and
read out by a distinct MBON type; PAM-cluster neurons innervate the
appetitive/reward-signalling compartments (γ5, β′2, β′1, γ4, β1, α1) and
PPL1-cluster neurons the aversive ones (γ1pedc, γ2α′1, α′2, α3, α′1)
(Aso, Hattori, Yu et al. 2014, *eLife* 3:e04577; Aso, Sitaraman, Ichinose et
al. 2014, *eLife* 3:e04580). Under the hemibrain MBON numbering (Li, Lindsey,
Marin et al. 2020, *eLife* 9:e62576), MBON01–MBON10 sit in PAM-innervated
compartments and MBON11–MBON15 in PPL1-innervated ones. **The corrected read
reproduces exactly that pattern** (MBON01–10 PAM, MBON11–15 PPL1) and
upstream's read does not.

**(c) our modelling rule.** An MBON is assigned to the compartment whose DAN
population contributes more dopaminergic synapses onto it, strictly. Equality
or zero input from both leaves it unclassified and it takes no part in
learning. `valence = +1` addresses the PAM-innervated set, `-1` the
PPL1-innervated set; the plasticity is depression in both cases, which is
upstream's mapping and the measured rule. We do **not** claim that a
PAM-innervated MBON drives approach or that a PPL1-innervated one drives
avoidance — that is a separate, behavioural claim which this wave does not
test. Greater PAM or PPL1 input is evidence about *innervation*, not about
behavioural valence.

## Ambiguities recorded

These are open; none of them is resolved by inventing an equivalence.

1. **The MBON numbering is assumed, not verified, to be the hemibrain
   numbering.** The correspondence in (b) above — MBON01 = γ5β′2a and so on —
   comes from the hemibrain literature. MaleCNS v1.0 uses the same `MBONnn`
   type strings, and the compartment pattern the corrected read produces
   matches the hemibrain assignment, which is strong circumstantial support.
   It is not a check against a published MaleCNS-specific table, and we did
   not download one. **Treat "MBON11 is γ1pedc>α/β" as literature
   interpretation, never as a measurement from this dataset.**

2. **`receptorType` is empty for every traced neuron.** Upstream's
   `FlyBrain.where(receptor=…)` therefore matches nothing on v1.0, and the
   README's "53 receptor types" is really 53 *glomeruli*, read out of the
   `ORN_<glomerulus>` type names. Odorant-receptor identity is not in the data
   we downloaded. We select ORNs by glomerulus and say so.

3. **"Dopaminergic" has two incompatible definitions in the data.** 392
   neurons have `consensus_nt == dopamine`; 340 have `class == DAN`; the sets
   are not nested. 54 dopaminergic neurons are not class DAN (ExR2, FB1C,
   FB2A, FB4L, FB4M, FB1H, FB5H — central-complex; LoVC18, LoVC22, PPM1201-03,
   PPM1205, AVLP476, AVLP610, LAL128, SIP106m, and **DPM**), and 2 class-DAN
   neurons (in PPL2) have `consensus_nt == unclear`. Our modulatory matrix is
   built on `consensus_nt == dopamine` (the transmitter, which is what
   modulation depends on) while the compartment split uses the `^PAM`/`^PPL1`
   type names (the cluster, which is what the literature is about). Those are
   different criteria and we use each where it belongs; DPM in particular is
   serotonergic/peptidergic in most of the literature and is here predicted
   dopaminergic, which we neither resolve nor rely on.

4. **A handful of MBON neurons rest on thin evidence.** The closest compartment calls,
   by winner/loser ratio: MBON33 (92 vs 198), MBON30 (74 vs 170), MBON20
   (26 vs 64), MBON33 (59 vs 158), MBON30 (58 vs 156), MBON10 (12 vs 4). The
   smallest total dopaminergic inputs are MBON34 (5 and 12 synapses), MBON10
   (16), MBON19 (19), MBON25-like (22). Raising the modulatory threshold from
   1 to 3 synapses moves MBON10, MBON22 and MBON34; at ≥5 it moves five
   neurons and leaves seven unclassified. Nothing downstream should rest on
   those specific cells.

5. **`MBON15-like`, `MBON17-like`, `MBON25-like`** (10 neurons) are, by their
   names, cells the curators judged similar to but not identical with a
   canonical MBON. We include them in the MBON set — they receive KC input and
   dopaminergic input like the others — and flag them here. No claim is made
   that `MBON15-like` is `MBON15`.

6. **DNa02 is two neurons, one per side.** Any decoder built on DNa02
   left–right asymmetry is reading a difference between two single cells.
   That is exactly how the fly does it, and it is also the entire dynamic
   range available. Recorded because SPEC's instrument-selection idea depends
   on it.

7. **Uniglomerular PN selection is a naming rule, not an anatomical
   measurement.** We exclude `M_`/`MZ_` (the dataset's multiglomerular prefix)
   and names containing `+` (several glomeruli listed) and `CB####` (no
   glomerulus in the name). 284 of 686 ALPNs survive. We did not verify
   against synapse-level glomerular innervation, which would need
   `syn-points`, deliberately not downloaded.

## Sensory populations chosen for Phase 0.5

Fixed **before** any conditioning result was looked at, on sensory-path
grounds only. See `experiments/conditioning/PROTOCOL.md` for the exact rule
and `docs/ARCHITECTURE.md` for the operating point.

* Candidate channels: the 50 glomeruli that have **both** ORNs and
  uniglomerular PNs, minus the four pheromone channels DA1, VA1v, VA1d and
  DL3, whose PNs are biased toward the lateral horn rather than the
  mushroom-body calyx (Jefferis, Potter, Chan et al. 2007, *Cell*
  128:1187–1203). 46 candidates remain.
* Odour **A** = ORNs of DL2d, DL2v, VL2a, DM6, VC3 — 228 ORNs, 43 uPNs.
* Odour **B** = ORNs of VM5d, DA2, VM4, DM5, VM7d — 281 ORNs, 44 uPNs.
* The split is a snake draft over the ten candidates with the most
  uniglomerular PNs (ties alphabetical), which balances uPN count (43 vs 44)
  without reference to any downstream measurement.
