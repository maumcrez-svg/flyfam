# Architecture — v0 (end of Phase Zero)

Scope of this version: what we reuse from upstream, what we replace, and every
upstream behaviour that could not be independently verified. It is written
from the Phase Zero audit only — no product code exists yet. Detail and
file:line citations live in `docs/UPSTREAM_NOTES.md` and are not repeated.

## The seam

Upstream is two things stacked: a connectome simulator, and a browser-driving
token launcher. The simulator is good and we reuse it. The launcher is an
application we do not want, and almost the entire safety surface lives there.

```
                      REUSE                     REPLACE
  connectome  ─────►  build_graph.py       │
  simulation  ─────►  flysim.FlyBrain      │
  plasticity  ─────►  mushroom.py (fixed)  │
                                           │
  sensory     ─────────────────────────────┤  flyeye.FlyEye  →  SensoryEncoder
  action      ─────────────────────────────┤  flyeye.FlyPilot →  ActionDecoder
  loop        ─────────────────────────────┤  roam.py / rhlive.py
  execution   ─────────────────────────────┤  rhprovider.py / rhwallet.py
  telemetry   ─────────────────────────────┤  site/ , web/
  narration   ─────────────────────────────┤  voice.py / xpost.py  (deleted, not replaced)
```

## Reused as-is

| upstream | why |
|---|---|
| `build_graph.py` | The connectome→matrix build. Convention verified. Two changes are needed and both are additive: a second, unsigned matrix for modulatory (dopaminergic) edges, which the current sign rule deletes, and a bounds guard at line 75. |
| `flysim.FlyBrain` | LIF simulation, Shiu et al. 2024 parameters. Deterministic under a fixed seed, carries no state between windows, has no spontaneous activity. All verified. Its `where()` annotation selector is the right interface for population selection. |
| `mushroom.MushroomBody` | The plasticity mechanism — site, direction, eligibility, floor, recovery — is correct and verified. The compartment classification is not (see below). |

## Reused with a known fix required before use

**`mushroom.py` PAM/PPL1 classification is transposed** (`mushroom.py:67-68`).
The split is computed from MBON→DAN feedback instead of DAN→MBON dopaminergic
input, and against the shipped `graph.npz` the documented read returns nothing
at all because dopaminergic edges are signed 0.0 and dropped. Fixing the
indexing alone would switch learning off; the fix needs a modulatory
connectivity source as well. Evidence, the exact mismatch, and the two-part fix
are in `UPSTREAM_NOTES.md` §2. **Not applied in this wave.** Nothing downstream
of the MBON split — including any approach/avoidance action mapping — may be
built until it is.

## Replaced

* **Sensory.** `flyeye.FlyEye` is a retina: it samples a screenshot into L1/L2
  through measured hex columns. We are not feeding it a screen. The
  *mechanism* it demonstrates is what we keep — drive a named population at a
  rate in Hz, one value per neuron — and `SensoryEncoder` will be a new,
  versioned, deterministic module built on `FlyBrain.where()`. What upstream
  does **not** give us and we must build: normalisation (it only clips),
  saturation handling (the drive silently saturates at 5000 Hz), and any
  guarantee that stimulating a population does not overwrite its own recurrent
  input (injection is a voltage clamp, not a current).
* **Action.** `flyeye.FlyPilot` decodes seven descending-neuron populations
  into a cursor. Its arithmetic is hand-tuned for a cursor (a `/450`
  normaliser, a 330 Hz click threshold) and its own comments admit the commit
  signal is a repurposed stop signal. `ActionDecoder` is new. The open
  question it inherits is which populations BUY/SELL/WAIT can honestly come
  from — see `UPSTREAM_NOTES.md` §4; today, two of the three have no
  defensible mapping.
* **Loop, persistence, execution, telemetry.** `roam.py` and `rhlive.py` are
  browser rigs. Upstream persistence is a single overwritten `.npz` with no
  history, which SPEC forbids. Everything SPEC asks for — DecisionRecord,
  OutcomeRecord, event log, seasons, replay, bounded execution — has no
  upstream counterpart and is built new.
* **Nothing from the chain integration is carried over.** Not the wallet, not
  the EIP-1193 provider, not the RPC passthrough, not the ingress. Inventory in
  `UPSTREAM_NOTES.md` §6, kept so it stays out.
* **`voice.py` / `xpost.py` are deleted outright**, not replaced. An LLM
  narrating the fly is exactly the thing SPEC's decision-integrity rule exists
  to prevent from creeping inward, and we have no need for the entry point.

## Constraints the upstream imposes on everything downstream

These are measured facts, not preferences, and they shape Phase One:

1. **No spontaneous activity.** Nothing fires unless driven. 0 Hz means "not
   stimulated", never "chose to wait".
2. **No memory between control steps.** `run()` resets every membrane
   potential. The brain is a pure function of (current stimulus, learned
   gains, seed). All experiment state lives outside it.
3. **Learning is subtraction only.** The mushroom body can only depress, with
   a floor and a slow drift back to baseline. There is no mechanism by which
   the fly gets better at something, only one by which it stops doing things.
4. **The only plastic weights are KC→MBON.** Everything else is fixed anatomy.
5. **Determinism is seed-scoped.** Same seed and same drive reproduce exactly;
   the seed must be in the DecisionRecord.

## Could not be independently verified

Everything here is either an upstream claim we have no way to check offline,
or a measurement that needs the connectome data this wave was not permitted to
download. Listed so no later document treats any of it as established.

| claim | source | status |
|---|---|---|
| 165,122 traced neurons, 10,228,000 signed edges | README | unverified |
| 892 retinotopic hex columns | README | unverified |
| 2,635 ORNs across 53 receptor types; cVA→ORN_DA1→pC1 at 222 Hz | README | unverified; the olfactory path is genuinely unwired in code |
| 44,042 KC→MBON synapses, 27,939 / 14,349 split | README, `mushroom.py:31-34` | unverified, and produced by the transposed read |
| MBON01/02/03 reward-side, MBON04/10/11 punish-side | README, `mushroom.py:20-22` | **undetermined** — produced by the transposed read; the corrected read may agree, disagree or return nothing |
| −6.0% / −0.9% / +0.3% plasticity effect sizes | README | not reproduced |
| DNp09 at 167–417 Hz under visual drive | README | unverified; matters, because the click threshold is 330 Hz |
| real population counts and baseline rates for any population | — | not established, no data |

Corroboration available offline: `upstream/assets/gains_ui.npz` was built
against the real dataset and carries 260 tuned cell-type names with type codes
up to 11662, implying at least 11,663 distinct cell types. It contains L1, L2,
R1-R6, DNa01, DNa02, DNp09, MDN and MN1/6/9, and no MBON, KC, PAM or PPL1 —
i.e. upstream's trained gains cover the visuomotor loop only, and the mushroom
body runs untrained.

---

# Architecture — v0.5 (Phase 0.5)

What changed: the connectome is real, the graph build is ours, and the
plasticity fix is applied in our code. `upstream/` is still untouched at
`5aab4e7895a1f5930319bf3bde8010b350a163a2`; `flysim.FlyBrain` is still run
unmodified, over a `graph.npz` we produce in its exact format.

## Three matrices, one index

Upstream produces one matrix and folds the neurotransmitter sign into it at
build time, which deletes every dopaminergic edge (sign 0.0, then
`keep = v != 0.0`). We keep the anatomy first:

| artefact | content | convention | threshold |
|---|---|---|---|
| `graph_anat.npz` | `A[post, pre]` = synapse count, **non-negative**, no sign | [post, pre] | ≥3 synapses |
| `graph.npz` | `W[post, pre]` = `A · 0.275 mV · sign(nt of pre)`, zero-signed edges dropped | [post, pre] | ≥3 synapses |
| `graph_mod.npz` | `D[post, pre]` = dopaminergic synapse count, **unsigned**, never given a fast weight | [post, pre] | **≥1 synapse** |
| `annotations.npz` | 16 annotation columns aligned to the same body index | — | — |

All four share one `bodies` vector (sorted ascending, 165,122 entries), and
`ModulatoryGraph` raises rather than proceed if the index does not match.

Measured on MaleCNS v1.0:

```
traced neurons                                       165,122
neuron->neuron edges at >=1 synapse                25,563,197
anatomical edges at >=3 synapses                   10,511,038   (104,213,652 synapses)
fast edges after signing                           10,228,000   (+6,268,194 / -3,959,806)
edges deleted by the sign rule                        283,038
  ... of which DAN outgoing                            54,171
modulatory edges kept (>=1 synapse)                   241,702   (583,124 synapses, 392 DANs)
```

### Modulatory threshold — a separate decision, measured

The fast layer's ≥3-synapse cut (`build_graph.py:22`) exists to suppress
reconstruction noise in a *voltage sum*, where a 1–2 synapse pair contributes
~0.3–0.6 mV against a 7 mV gap. The modulatory layer computes something else
entirely — which compartment a dopaminergic neuron addresses — so the filter
was re-evaluated rather than inherited:

| threshold | dopaminergic edges | synapses | MBONs PAM / PPL1 / unclassified |
|---:|---:|---:|---|
| ≥1 | 241,702 | 583,124 | 41 / 56 / 0 |
| ≥2 | 103,163 | 444,585 | 40 / 56 / 1 |
| ≥3 | 54,171 | 346,601 | 39 / 56 / 2 |
| ≥5 | 22,777 | 241,879 | 36 / 54 / 7 |

**≥1 chosen.** It keeps every MBON classifiable; the ≥3 cut discards 77.6% of
the dopaminergic edges and leaves two MBONs with no dopaminergic input at all.
94 of 97 MBONs get the same side at either threshold, so the split is not an
artefact of the choice; the three that move (MBON10, MBON22, MBON34) are the
weakly innervated ones and are listed as ambiguities in `docs/POPULATIONS.md`.

## The plasticity fix

`flytrade/mushroom.py`, version `flytrade-mb-1`. Two parts, as
`UPSTREAM_NOTES.md` §2 specified:

1. the compartment assignment is read from `graph_mod.npz`, which the sign rule
   never touched — dopamine is **not** converted into fast excitation anywhere;
2. the read is `D[mbon][:, dan].sum(axis=1)`, post-by-pre, "synapses each MBON
   receives", instead of upstream's `W[dan][:, mbon].sum(axis=0)`.

Everything upstream had right is kept unchanged: the plastic site (KC→MBON
found by walking CSC columns of Kenyon cells), eligibility keyed on the
presynaptic KC, depression only with a floor, drift back toward baseline, and
`apply()` writing `base · gain` so every synapse keeps its sign.

Two things are added: an MBON with no dopaminergic input is **unclassified**
rather than silently on neither side, and a reinforcement is **scoped to an
episode** so a delayed outcome cannot depress traces laid down in a different
episode.

Consequence on the real connectome: 41 PAM-innervated and 56 PPL1-innervated
MBONs (24,005 / 20,037 plastic synapses), against upstream's 45 / 47
(27,939 / 14,349). 46 of 97 MBONs and 12,606 of 44,042 synapses change
compartment.

## Operating point

**The default parameters saturate the network and must not be used.** With
`gains=None` (every synapse at 0.275 mV), driving 204 ORNs at 100 Hz for 20 ms
makes every Kenyon cell and every MBON fire at ~440 Hz — against a 454 Hz
refractory ceiling — and 39,448 of 165,122 neurons spike. Two completely
different odours produce an identical readout (Kenyon-cell Jaccard 1.000). This
is a property of the model, not of our stimulus: threshold sits 7 mV above
rest, one 26-synapse connection crosses it in a single step, and there is no
adaptation anywhere.

`flysim.run(gains=…)` is upstream's own free parameter for synaptic efficacy
(`flysim.py:11-13`). We use a single uniform scalar over all cell types.
**g = 0.10**, drive 150 Hz, window 100 steps (20 ms). Selection rule, criteria
and the measured sweep are in `experiments/conditioning/PROTOCOL.md` §2. At
that point: KC active fraction 0.227 (odour A) / 0.067 (odour B), Jaccard
0.268, MBON mean 48.0 / 15.2 Hz, no silent trials in 8 seeds.

Sensitivity of the readout to the plastic weights, measured by scaling all
44,042 KC→MBON weights uniformly (a mechanism check, not a conditioning
result): PAM-side MBONs 59.5 → 48.3 → 27.1 → 15.9 Hz and PPL1-side 38.6 →
32.3 → 21.8 → 9.8 Hz at gains 1.00 / 0.75 / 0.50 / 0.25, with the Kenyon-cell
active fraction unchanged (0.217 → 0.207). The readout moves when the plastic
synapse moves, and only then.

## Performance

One `run()` over the full 165,122-neuron graph, 100 steps, costs **0.3 s**
(12-core machine, 61 GB RAM; the graph itself is 37 MB compressed and loads in
0.4 s). No subgraph is needed and none is used — every measurement in this
wave is on the whole connectome.

## State layers, time and the checkpoint

`flytrade/state.py`, schema `flytrade-state-1`. Four things get called "the
fly's state" and they have different lifetimes; mixing them is how a delayed
reward ends up applied to the wrong experience.

| layer | container | lives for | survives a restart |
|---|---|---|---|
| electrical | `ElectricalState` (deliberately empty) | one `run()` call | **no** — `flysim.py:101` resets every membrane potential, so there is nothing to save and saving one would be a lie |
| eligibility | `EligibilityState` (`trace`, `episode`) | a few decision cycles | **no**, deliberately — after a restart the fly did not fire recently; it did not exist |
| learned weights | the 44,042 KC→MBON gains | the experiment | **yes**, checkpointed |
| episode history | `EpisodeLog` (append-only, JSONL) | forever | **yes**, never rewritten |

**Time.** The unit is one **decision cycle** = one observation, one brain
window, one decision. `DECISION_CYCLE_MS = 500`. Upstream's trace decay of
0.55 and recovery of 0.0008 are *per call* (`mushroom.py:53`), so at
`roam.py`'s 2 Hz the memory duration is an accident of the call rate. We
convert them once into time constants and derive the per-cycle factor:

```
decay_per_cycle    = exp(-cycle_ms / ELIGIBILITY_TAU_MS)     tau = 836.4 ms
recovery_per_cycle = 1 - exp(-cycle_ms / RECOVERY_TAU_MS)    tau = 624.8 s
```

Both taus are chosen so that **at a 500 ms cycle the factors are exactly
upstream's 0.55 and 0.0008** — same parameters, no dependence on call rate.
Four cycles of 500 ms and eight of 250 ms now leave the same trace
(`tests/core/test_state.py`). The measured eligibility window in *Drosophila*
is on the order of seconds (Cohn et al. 2015; Aso & Rubin 2016), which is the
right order of magnitude but is not what these numbers were fitted to; they
came from upstream and we kept them, and that is the honest description.

**Reinforcement is scoped to an episode.** `MushroomBody.begin_episode(k)`
stamps every trace laid down afterwards; `dopamine(..., episode_id=k)` only
depresses synapses whose trace belongs to episode `k` and counts the rest in
`events["rejected_episode"]`. A reward that arrives late cannot depress the
activity of a different episode.

**Checkpoint.** Learned gains + synapse positions + `graph.npz`'s sha256 +
schema version + rng seed + event counters + the time constants. Written
atomically: temp file in the destination directory, `flush`, `fsync`,
`os.replace`, then `fsync` of the directory. Loading validates the schema
version, the graph hash, the position vector and a content digest, and
**raises `CheckpointError`** on any failure — no silent fallback to baseline,
no `SHIPPED` file inside the repository, and no `except Exception: pass`,
which is what upstream does on both save and load (`mushroom.py:170`, `:193`).

## Action space

`flytrade/decoder.py` contains an enum and no logic. `BUY`, `SELL`, `WAIT`,
`NO_RESPONSE`. `NO_RESPONSE` is a distinct member because the simulation has
no spontaneous activity: 0 Hz means "not driven", which is not the proposition
"chose to stay still". It may result in no order; it is never reported as a
demonstrated neural choice. No decoder is written in this wave, and there is
no market logic anywhere in `flytrade/`. DNa02 and the MBONs remain candidates
until measured.


---

# Architecture — Phase One

The offline vertical slice: market context → sensory encoder → connectome →
fixed decoder → instrument/action → simulated execution → realised outcome →
episode-specific reinforcement → persistent learning → next decision. Six
instruments, 33 completed cycles in the demonstration, one persistent learned
brain. `upstream/` is still untouched at `5aab4e7895a1f5930319bf3bde8010b350a163a2`;
the graph build and the plasticity fix of v0.5 are unchanged.

```
market.ObservationFeed ─ bars at or before the cutoff ───┐   (no forward accessor)
                                                         ▼
        encoder.MarketToSensoryEncoder ─ 5 causal features → 10 glomeruli, 703 ORNs
                                                         ▼
        runner.BrainRunner ─ one snapshot S0 per round, restored per candidate
                                                         ▼
        decoder.ActionDecoder ─ V = (approach − avoid) − BASELINE_HZ, |V| vs θ
                                                         ▼
        execution.ExecutionPolicy ─ fill at bar t+1, one long, horizon 8 bars
                                                         ▼
        records.Journal ─ append-only log, atomic checkpoint, pending episode
                                                         ▼
        runner.CreditAssigner ─ stored-trace replay into MushroomBody.dopamine
```

| module | what it owns | version |
|---|---|---|
| `flytrade/market.py` | bars, CSV, synthetic fixtures, causal features, the observation/execution split, stable ids | `flytrade-market-1` |
| `flytrade/encoder.py` | feature → glomerulus drive, the declared operating range | `flytrade-encoder-1` |
| `flytrade/runner.py` | sequential evaluation, transient snapshots, stored traces, credit assignment | `flytrade-runner-1` |
| `flytrade/decoder.py` | the fixed readout, θ, the four statuses | `flytrade-action-1` |
| `flytrade/execution.py` | paper fills, fees, accounting, outcome → dopamine | `flytrade-exec-1` |
| `flytrade/records.py` | DecisionRecord, event log, journal, crash-safe settlement | `flytrade-records-2` |
| `flytrade/readout.py` | k, the replicate seed schedule, aggregation, the k = 8 baseline | `flytrade-readout-1` |

Specifications, one fact in one place: `docs/ENCODER.md` (channels, operating
range, seeds, timing), `docs/DECODER.md` (pre-registered readout and margin),
`docs/EXECUTION.md` (policy, accounting, the four clocks). Measurements:
`experiments/phase_one/results.md`.

## The three findings that shaped it

**The encoder cost two designs.** A balanced opponent code recruits the same
Kenyon cells for every market state (Jaccard 0.67–0.78 against a 0.40
criterion); a rectified code with a fixed per-ORN rate couples discrimination
to drive and falls silent before it discriminates. Constant-budget divisive
normalisation breaks the coupling. Declared range: budget 12,000 Hz, carrier
0.10 — one cell of fifteen passes all three PROTOCOL.md §2 criteria. The gain
never moved from 0.10; the input range gave instead.

**The operating point is a ledge, not a plateau.** At gain 0.08 the encoder is
effectively silent (Kenyon fraction 0.000–0.001, 10 of 48 trials with no MBON
spike); at 0.12 recruitment is 0.306, past the criterion. Everything downstream
inherits that narrowness.

**The readout is quantised and the first §4 protocol failed because of it.**
29 and 16 neurons over 20 ms means one spike is worth 1.724 Hz and 3.125 Hz;
half the per-seed learning effects were smaller than one spike and were
recorded as exactly zero. The declared deviation — contrast-selected contexts
and measurement averaged over eight presentations — passes all six checks 8/8,
and both protocols are kept and re-run.

## The action mapping, and what it is not

`V = mean(approach) − mean(avoid) − BASELINE_HZ`, where `approach` is the 16
PPL1-innervated MBONs of MBON11–15 and `avoid` the 29 PAM-innervated ones of
MBON01–10. The direction is the literature's, not the convenient one:
PAM-innervated "reward" compartments hold avoidance-promoting MBONs. Under
depression-only plasticity this convention is *self-consistent* — profit
depresses `avoid` and the same context decodes closer to BUY next time — and
the opposite convention would move the readout the other way, which makes the
two distinguishable. That is a reason to prefer it, not proof that grouping by
dopaminergic innervation establishes a behavioural valence; the three layers
are separated in `docs/DECODER.md` §3 (D4 §6).

Still not established: that this system has any edge, that the MBON numbering
is the hemibrain numbering (assumed, `docs/POPULATIONS.md` ambiguity 1), or
that a 20 ms readout of 45 neurons is a good instrument. The gate was a
working, auditable loop, and that is what exists.


---

# Architecture — D4, the k = 8 readout

One thing changed and the rest was held still. `flytrade/readout.py` sits
between the runner and the decoder:

```
        runner.BrainRunner.evaluate_round(readout=policy)
                 │  restore S0, present, capture the trace ─── ×8 per candidate
                 ▼
        readout.ReadoutPolicy ─ seeds = sha256(namespace : state digest :
                 │               observation id : stable id : r)[:8]
                 ▼
        readout.Batch ─ 8 Presentations + 8 StoredTraces + 1 aggregate
                 │      rates = mean, kc_fraction and peak rate = max
                 ▼
        decoder.ActionDecoder ─ applied ONCE, θ₈ = 0.9117 Hz
                 ▼
        one decision → at most one episode → ONE normalised learning event
                       Δ = mean_r Δ_r, every Δ_r from the same pre-update state
```

`k = 1` is replicate index 0 of the same schedule: an explicit regression mode,
never an automatic fallback. The Phase One path — `readout=None`, one
presentation, the `round_seed` schedule — is untouched and still tested.

**What the eight readings buy, measured** (`experiments/k8_readout/results.md`):
the SD of `V` within a context falls in 6 of 6 evaluation contexts, ratios
0.220–0.499, compatible with sampling variation around the 1/√8 ≈ 0.354
expectation (16 batches each, ≈ 18 % relative error per ratio); decision
agreement across
repeated batches is equal or better in 6 of 6; `NO_RESPONSE` goes from 14 of 96
single presentations to 0 of 96 batches, and from 60/319 decisions in the Phase
One demonstration to 1/320 here, while 3,503 of the 13,000 individual
presentations inside those batches were still silent. Nothing was relabelled: a
batch is `NO_RESPONSE` only when all eight of its replicates are.

**What it costs**: 7.4× median round latency for 8× the presentations — the
journal's per-decision cost is paid once whatever `k` is — and no extra memory,
because the connectome dominates the process.

**What it changes downstream, and this is not an improvement claim.** θ₈ is
3.6× narrower than θ₁, so the same margin rule decides far more often: the
k = 8 demonstration emits 94 `SELL` against 6 at k = 1, and closes 19 of 21
positions by a neural `SELL` where the k = 1 run closed 27 of 33 by the horizon
timer. The fly is deciding rather than waiting. Whether it decides *well* is not
established by anything in this wave, and net PnL is not a gate metric.

**Still not established**, unchanged from Phase One: that this system has any
edge; that the MBON numbering is the hemibrain numbering; that a 20 ms readout
of 45 neurons is a good instrument. What eight of them buy is a smaller
measurement noise on the same instrument.

---

## D6 — the historical market path

`flytrade/historical.py` is the only place a vendor file is read. It exists
because an exchange minute bar is not a bar from `synthetic_series`, and the
three differences are all consequential.

**The timestamp is the bar's open.** A row stamped 09:30 covers 09:30:00
through 09:30:59, so its final OHLCV does not exist until 09:31:00. Every
observation's `cutoff_ts` is therefore `bar_start + 60`, and the decision that
reads it is taken at that instant. This is the vendor's own documented
convention, quoted in `data/MANIFEST.md`; getting it backwards would give every
decision one free minute of hindsight and no PnL would ever reveal it.

**A missing minute is data, not corruption.** The vendor omits any interval
without a reported trade. The importer keeps the dense 390-slot session grid
and marks the absent slots; nothing is forward-filled, nothing is compressed,
and row distance is never used as time. Everything downstream counts **elapsed
market minutes**.

**Features are located by the clock, not by the row.** The price behind a
lookback is `price_at(τ)` — the close of the last bar of this session with
`bar_end ≤ τ` — which is a price that actually printed. It is a feature input
only; no execution price is ever located that way. Two guards keep it from
becoming a forward fill: a lookback whose backing bar is more than 5 market
minutes stale makes the observation `STALE_DATA`, and every lookback is bounded
by the session open, so no overnight return enters a one-minute feature. The
first 20 market minutes of every session are `WARMUP` for that reason.

```
vendor row        09:30,272.00,272.25,269.07,270.54,176225
  ↓ parse + validate (7 fields, OHLC relations, ordering, session membership)
bar_start 13:30:00Z ──────── bar_end 13:31:00Z
                                 ↓  the first instant this bar may be read
observation      cutoff_ts = bar_end, 5 causal features in market minutes
  ↓ z-score over the trailing 60 usable rows ending at the cutoff, tanh(z/2)
encoder → brain → decoder → execution → outcome → learning   (unchanged)
```

**Four market statuses, none of them neural.** `OK`, `WARMUP`, `DATA_GAP`,
`STALE_DATA` live in `flytrade/market.ObservationStatus` alongside the Phase
One three, as separate members rather than aliases, so a report can never
flatten "the vendor omitted this minute" into "the readout was silent".
`NO_RESPONSE`, `WAIT`, `INVALID_STATE` and `POLICY_REJECT` remain what they
were and are counted apart from all four.

**Causality is tested by truncation, not asserted.** `tests/historical/`
reloads the file with the later sessions deleted and requires every earlier
observation to be identical bit for bit. A normaliser that had seen the
evaluation period would fail that test; no amount of reading the code would.

The Phase One synthetic path — `market.ObservationFeed`, `ExecutionFeed`,
`synthetic_series`, hourly bars, `MIN_HISTORY_BARS` — is untouched and still
carries the k = 8 demonstration and the whole existing suite.
