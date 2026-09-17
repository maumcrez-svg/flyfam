# k = 8 readout — pre-registration

**This file is committed before any k = 8 baseline or evaluation run exists,
and the commit that adds it contains nothing else.** The SHA ordering in
`git log` is the evidence that the baseline procedure, the evaluation stimuli,
the seed schedules, the metrics, the aggregate status rules and the pass/fail
thresholds were fixed before a single number was produced. It is the same
discipline `experiments/conditioning/PROTOCOL.md` (`b9655ea`) and
`docs/DECODER.md` (`f63825b`) were committed under. Any later change is
recorded as a **deviation** in `results.md`, with its reason, never by editing
this file silently.

Canonical amendment D4 §3 and §5, Fable addenda 1, 2, 5 and 8.

D4 is a readout-integration wave, not a new round of research on the brain. The
gain stays 0.10, the presentation window stays 20 ms, the encoder input range,
the sensory populations, the MBON membership, the decoder formula, its sign
convention and its dimensionless margin coefficient 1.0 are all exactly what
Phase One fixed. k = 8 is fixed: never increased for a difficult observation,
never stopped early after a desirable response, never retried until a response
appears.

---

## 1. Fixed material

| | |
|---|---|
| connectome | `data/malecns-v1.0/graph.npz`, sha256 `8feb08a0d2a80cbcf69328f9707d5dd748d73d2e12246526d96e48d995f843b9` |
| modulatory matrix | `data/malecns-v1.0/graph_mod.npz`, threshold ≥ 1 synapse |
| simulator | `upstream/flysim.py` at `5aab4e7895a1f5930319bf3bde8010b350a163a2`, unmodified |
| plasticity | `flytrade/mushroom.py`, `flytrade-mb-1` |
| encoder | `flytrade/encoder.py`, `flytrade-encoder-1`, budget 12,000 Hz, carrier 0.10 |
| decoder | `flytrade/decoder.py`, `flytrade-action-1`, formula and sign unchanged |
| readout policy | `flytrade/readout.py`, `flytrade-readout-1` |
| operating point | uniform gain 0.10, 100 steps × 0.2 ms = 20 ms |
| readout populations | 29 `avoid` (PAM-innervated, MBON01–07, 09, 10) + 16 `approach` (PPL1-innervated, MBON11–15) |
| k | **8**, fixed |
| k = 1 mode | replicate index 0 of the same schedule — a regression/comparison mode, never an automatic fallback |

Every dataset used in this wave is **SYNTHETIC**: seeded generators in
`flytrade/market.py` and nominal feature vectors placed at declared points of
the encoder's input range. There is no `data/market/` in the tree and no
download happens in this wave. Generators and seeds are named in §3 and §4.

## 2. Aggregate status rules

Declared before evaluation, exactly as Fable addendum 4 states them. Per batch
of k replicates:

1. **technical failure** — any replicate raises. The round aborts: one
   `ROUND_ABORTED` event with the reason, no `DECISION` event. Nothing is
   averaged over the successful subset and nothing is retried.
2. **INVALID** — the existing `INVALID_STATE` rule (Kenyon active fraction
   above 0.25, or a read neuron within 5 % of the refractory ceiling) holds in
   **any** replicate. The aggregate is `INVALID_STATE`; nothing is averaged.
   Saturation is never hidden by averaging it with quieter trials.
3. **NO_RESPONSE** — every one of the k replicates was silent over the 45
   decoder MBONs.
4. otherwise **VALID**, decoding `BUY` / `SELL` / `WAIT` from the aggregate,
   with `WAIT` iff `|V_8| ≤ θ_8`.

A technically successful **silent replicate inside an active batch contributes
its zero counts** and is never discarded to inflate the average.

Reporting units, fixed here so they cannot be chosen afterwards:

* `NO_RESPONSE` — unit **candidate evaluation (batch)**: numerator = batches
  whose aggregate status is `NO_RESPONSE`, denominator = batches evaluated;
* **silent replicates** — unit **presentation**: numerator = replicates with no
  spike over the 45 decoder MBONs, denominator = presentations made;
* `WAIT` is counted separately from `NO_RESPONSE` and never pooled with it;
* `INVALID_STATE` is counted separately from both.

## 3. The k = 8 baseline and the WAIT margin

The decoder's margin is stated in units of the measured dispersion of its own
baseline readout. Replacing one presentation by the mean of eight changes that
dispersion, so the baseline is re-measured for the k = 8 estimator. The
formula, the sign convention and the coefficient 1.0 do **not** change; two
constants do.

**Reference brain state.** Unlearned weights — every KC→MBON gain exactly 1.0 —
gain 0.10, the declared encoder range. The same reference `docs/DECODER.md` §1
measured the k = 1 constants at.

**Baseline stimulus.** The neutral reference `u = (0, 0, 0, 0, 0)`: every
feature at its own trailing median, a market with no information in it. One
stimulus, the same one as `docs/DECODER.md`.

**Seed schedule.** Namespace `flytrade-k8-baseline-1`, disjoint by construction
from the round schedule (`flytrade-k8-round-1`) and the evaluation schedule
(`flytrade-k8-eval-1`), and disjoint from every Phase One schedule, which drew
small integers below 2³² while these are 64-bit digests — the run asserts that
every drawn seed is ≥ 2³² and reports it. For batch `b` and replicate `r`:

    seed = sha256("flytrade-k8-baseline-1 : <state digest> : <obs id> : 0 : r")
    obs id = sha256("neutral_reference:batch-<b>" ‖ u)

**N = 64 batches**, i.e. 512 presentations.

**The distribution normalised**, stated so it cannot be quietly swapped later:
the **per-batch aggregate raw valence** `V_raw = mean(approach) − mean(avoid)`
at the neutral reference, one sample per batch, N = 64 samples. Its **sample
standard deviation with ddof = 1** — *not* the standard error of its mean, and
not a within-batch dispersion.

    BASELINE_HZ_K8 = mean of the 64 batch samples
    BASELINE_SD_HZ_K8 = their sample SD (ddof = 1)
    THETA_HZ_K8 = 1.0 × BASELINE_SD_HZ_K8

**Degenerate dispersion.** If the 64 batch samples are all identical the margin
has no unit. The wave **stops and reports it**. No substitute divisor, no
epsilon, no standard error in its place.

**Expectation, stated in advance.** With the replicates independent given a
frozen state, the SD of a mean of 8 is about `1/√8 ≈ 0.354` of the SD of one.
The k = 1 values are `BASELINE_HZ = −2.3033 Hz`, `BASELINE_SD_HZ = 3.2414 Hz`.
A ratio far from 0.354 is a **finding to report**, not something to fix.

**No future information.** No label, no PnL, no realised outcome and no desired
action rate participates. The baseline is frozen for this experiment version
and recorded with its provenance — graph sha256, brain state digest, seed
namespace, N, commit — in `baseline_k8.json`. It is not continuously recentred.

## 4. The independent integration check

### 4.1 Contexts — six, fixed here

Two are the conditioning **v2 pair**, carried over and labelled as what they
are: *selected after v1 failed on resolution*. Four are **new nominal encoder
patterns**, which is what amendment §5 means by "additional encoder patterns
not selected because they passed conditioning v2": they are feature vectors
placed at declared points of the input range, not bars that happened to pass a
previous test.

| id | what | feature vector `(r1, r5, r20, rv20, relvol)` |
|---|---|---|
| `V2_X` | `CTX3` at bar 218, synthetic series seed 903 | the encoder's own output for that observation |
| `V2_Y` | `CTX1` at bar 409, synthetic series seed 901 | the encoder's own output for that observation |
| `NOM_A` | nominal | `(−0.9, +0.9,  0.0,  0.0,  0.0)` |
| `NOM_B` | nominal | `(+0.9,  0.0,  0.0, +0.9,  0.0)` |
| `NOM_C` | nominal | `( 0.0,  0.0, +0.9,  0.0, +0.9)` |
| `NOM_D` | nominal | `(+0.9, +0.9, −0.9, −0.9, +0.9)` |

**Selection rule and its disclosure.** The four nominal patterns were chosen
from a declared pool — the 10 single-feature, 40 two-feature and 32 all-feature
sign corners at magnitude 0.9 — by two stimulus-side criteria and no other:
(i) the two `experiments/conditioning/PROTOCOL.md` §2 operating-range criteria
that admit a stimulus at all (mean Kenyon active fraction inside
`[0.010, 0.25)` and no silent MBON readout at the probe seeds), and (ii) the
minimal achievable pairwise Kenyon-cell Jaccard among four such patterns.

That measurement was taken **before this file was written**, and this paragraph
is the disclosure. Fable addendum 8 permits it in terms: "Jaccard is a stimulus
property, selection by it is allowed; selection by any readout result is not."
Nothing about stability, agreement, `NO_RESPONSE` counts, learning or any
k = 8 aggregate entered the choice; none of those existed. The measured
Jaccard matrix is reproduced by the evaluation script into `results.md`.

**The Jaccard threshold.** Pairwise Kenyon-cell Jaccard among the four nominal
contexts is ≤ **0.368** (the Phase One encoder-range bound). The full 6 × 6
matrix, including the cross terms with the v2 pair, is reported whatever it
says; the threshold is a property of the four new patterns, because the v2 pair
is a previously characterised pair with its own published overlap of 0.287.

### 4.2 Seed schedule

Namespace `flytrade-k8-eval-1`, disjoint from seeds 1–8 of Phase One and from
the baseline namespace. Per context `c`, batch `b ∈ 0..15`, replicate
`r ∈ 0..7`:

    obs id = sha256("<c>:batch-<b>" ‖ u_c)
    seed   = sha256("flytrade-k8-eval-1 : <state digest> : <obs id> : <c index> : r")

**16 batches per context**, i.e. 128 presentations per context and 768 in
total. **k = 1 is replicate 0 of each batch**, so the two arms are paired by
construction and not by a second run.

### 4.3 Metrics, per context

Computed over the 16 batches, for k = 8 and for k = 1 on the same batches:

* **within-context readout variability** — the sample SD (ddof = 1) of the
  centred valence `V` over the 16 batches. Primary: over **all 16**, which is
  the quantity the loop actually selects on. Secondary, reported alongside:
  over the `VALID` batches only.
* **decision agreement across repeated measurement batches** — the fraction of
  the 16 batches whose decision equals the modal decision of that arm.
* **`NO_RESPONSE`** — numerator/denominator, unit *candidate evaluation* for
  k = 8 and unit *presentation* for k = 1 (a k = 1 batch is one presentation);
  **silent replicates** separately, unit *presentation*, out of 128.
* **`WAIT`** counted separately from `NO_RESPONSE`, and **`INVALID_STATE`**
  separately from both.
* the k = 8 / k = 1 **SD ratio**, against the `1/√8 ≈ 0.354` expectation.

### 4.4 Learning, at k = 8

The §4 v2 appetitive and aversive checks, re-run with the k = 8 mechanism, on
**both** the v2 pair and one new pair. The new pair is declared here:
`X = NOM_B`, `Y = NOM_A`.

Each of the 20 training trials is one **batch of 8** presentations producing
eight eligibility traces, settled by **one** normalised learning event — the
mean of the eight proposed deltas computed from the same pre-update state
(amendment §4). Not eight sequential rewards. Measurement before and after is
one k = 8 batch decoded once with `THETA_HZ_K8`.

Conditions, 8 seeds each, unchanged from §4 v2: `APPETITIVE_ON`,
`APPETITIVE_OFF`, `AVERSIVE_ON`, `AVERSIVE_OFF`, `APPETITIVE_OTHER`,
`AVERSIVE_OTHER`. Predictions unchanged and following from the frozen sign
convention: `dV(X) > 0` under `APPETITIVE_ON`, `dV(X) < 0` under
`AVERSIVE_ON`, exactly `0.000` under both `_OFF`, and `dV(X)[ON] − dV(X)[OTHER]`
keeping the branch's sign.

## 5. Pass / fail, fixed before running

| id | criterion | threshold |
|---|---|--:|
| **C1** | `SD_8 < SD_1` (all-batch SD of `V`) | in **≥ 5 of 6** contexts |
| **C2** | `agreement_8 ≥ agreement_1` | in **≥ 5 of 6** contexts |
| **C3a** | appetitive sign correct: `dV(X) > 0` | **8/8** seeds, on **both** pairs |
| **C3b** | aversive sign correct: `dV(X) < 0` | **8/8** seeds, on **both** pairs |
| **C3c** | plasticity off moves nothing: `dV(X) == 0.000` exactly | **8/8** seeds, on **both** pairs |
| **C4** | the θ₈ estimator is non-degenerate | `SD_8 > 0` at the neutral reference |

Every context is reported, including the failures. Eight measurements of one
context are **not** eight independent market predictions and **not** eight
independent learning episodes.

Zero `NO_RESPONSE` is **not** promised and is not a criterion. Silence is never
relabelled and no threshold is lowered to meet a target. If the claimed readout
improvement does not appear outside the original v2 pair, that result is
reported as it stands: the stimuli, the gain, θ and k are not changed
afterwards.

Profitability is not required, not sought and not a criterion anywhere in this
protocol. Net PnL is not a gate metric.

## 6. Output

| artifact | produced by |
|---|---|
| `baseline_k8.json` | `baseline.py` — §3, committed with its provenance before the evaluation runs |
| `evaluation.json` | `evaluate.py` — §4 and §5 |
| `benchmark.json` | `benchmark.py` — D4 §7, six candidates at k = 1 and k = 8 |
| `demo_k8.json` | `run_demo_k8.py` — D4 §8, the Phase One demonstration at k = 8 |
| `results.md` | regenerated from the four, every number generated, none hand-entered |

The commit hash of this file goes into `results.md`.
