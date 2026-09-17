# Upstream notes — Phase Zero audit

## The pin

| | |
|---|---|
| repository | https://github.com/fruitflydev/flycoinrh |
| commit | `5aab4e7895a1f5930319bf3bde8010b350a163a2` |
| tree | `5b8a6c70b40e1faa42eb21daf6d154e9d73b228d` |
| dated | 2026-09-11, "docs(readme): describe the voice and add the $FLYBRAIN launch row" |
| size | 1.8 MB working tree, 44 files, 5,280 lines of Python |
| license | **MIT**, © 2026 fruitflydev (`upstream/LICENSE`) |

Vendored into `upstream/` rather than gitignored: at 1.8 MB it is cheap to
carry, and pinning the exact bytes keeps this audit reproducible if upstream
is force-pushed or deleted. `docs/UPSTREAM_MANIFEST.txt` records the commit,
the tree hash and every blob hash, so the vendored copy can be diffed against
a fresh clone at that commit. The clone's own `.git` was removed; nothing else
was touched. **No upstream file is modified anywhere in this wave.**

### License and attribution

* Code: MIT. `upstream/LICENSE` is preserved verbatim. MIT requires the
  copyright notice and permission notice to travel with any copy or
  substantial portion, so it stays in the tree and is referenced from the root
  `NOTICE.md`.
* Connectome data: **not** covered by that MIT grant. `upstream/NOTICE` states
  the male *Drosophila* CNS dataset is © HHMI Janelia FlyEM, the Cambridge
  Connectomics Group and Google Research, released **CC-BY 4.0**, and stays
  CC-BY wherever it goes. The data itself is not in the repository (see
  "Not established" below), but the attribution obligation attaches the moment
  we download it.
* Upstream is not affiliated with Janelia, with pons, or with Robinhood.

### Does it match SPEC's description

Yes. It is a leaky integrate-and-fire simulation over the FlyEM male CNS
connectome — the files SPEC.md names all exist and do what it says they do.
Two differences from what SPEC implies:

* The connectome is **not vendored**. `build_graph.py` expects three feather
  files in `data/` totalling ~1.15 GB, downloaded from a public GCS bucket.
  Without them nothing but the pure-Python logic can run.
* Upstream's application is a browser-driving token launcher on Robinhood
  Chain, not a market experiment. The simulation core is reusable; the
  application layer is not, and most of the safety surface lives there.

## Environment

`.venv` (Python 3.13.9) pinned to upstream's own tested versions from
`upstream/requirements.txt`: numpy 2.4.2, scipy 1.17.1, pandas 3.0.1,
pyarrow 23.0.1, plus pytest 9.1.1. Nothing else. The chain, browser and
web-serving dependencies (eth-account, playwright, fastapi, uvicorn, Pillow,
requests) are deliberately **not** installed — no audited path needs them.

## 1. Matrix convention — VERIFIED

Established by running upstream over graphs whose direction is known by
construction, not by reading comments.
`tests/upstream_audit/test_matrix_convention.py`, 7 tests, all pass.

**`W[i, j]` is post-by-pre: row `i` is the postsynaptic neuron, column `j` the
presynaptic one.**

* `build_graph.py:97` `r = idx.loc[post_a]` — row = postsynaptic
* `build_graph.py:98` `c = idx.loc[pre_a]` — col = presynaptic
* `build_graph.py:99` `v = wt_a * MV_PER_SYNAPSE * sign[c]` — the sign is the
  **presynaptic** neuron's transmitter, indexed by `c`
* `build_graph.py:21` 0.275 mV per synapse (Shiu et al. 2024);
  `build_graph.py:22` pairs with fewer than 3 synapses are dropped
* `flysim.py:41` `self.W = W.tocsc()` — a **storage** change only. Logical
  indexing stays post-by-pre; `W[:, j]` is still "everything `j` projects to".
* `flysim.py:166-174` propagation gathers CSC column `fired` and adds
  `wdata[g]` into `v` at `indices[g]`, i.e. into the postsynaptic targets
* `flysim.py:173` `gain_per_neuron[fired]` — per-type gains scale **outgoing**
  weight, confirmed by silencing each type in turn

Also verified: `SIGN["dopamine"] = 0.0` (`build_graph.py:28`) combined with
`keep = v != 0.0` (`build_graph.py:101`) means **every edge whose presynaptic
neuron is dopaminergic is deleted from `graph.npz` entirely.** This is the
fact that decides section 2.

Minor robustness bug found by running it: `build_graph.py:75` sizes its lookup
table from the largest bodyId in the ≥3-synapse weight table, then indexes it
with every traced bodyId at line 76. A traced neuron whose bodyId exceeds that
maximum raises `IndexError`. It does not happen on the published dataset;
nothing in the code guarantees it cannot. Pinned by
`test_build_graph_crashes_if_the_highest_bodyid_has_no_kept_edge`.

## 2. mushroom.py — **INCONSISTENT**

`tests/upstream_audit/test_mushroom_orientation.py`, 11 pass + 2 strict xfail.

### What mushroom.py assumes

Correct, and verified against the convention above:

* `mushroom.py:81-88` walks CSC column `k` for each Kenyon cell and keeps the
  targets that are MBONs — **presynaptic KC, postsynaptic MBON**, the right
  way round, and `self.pos` really does index the weights the simulation reads
* `mushroom.py:116` `trace[active[self.pre]] = 1.0` — eligibility keyed on the
  presynaptic Kenyon cell, not on the MBON
* `mushroom.py:93` `side = side[self.post]` — the compartment is the
  postsynaptic MBON's
* `mushroom.py:131-132` depression only, `gain *= (1 - lr·amount·trace)`,
  clipped to `[floor, 1.0]`; no potentiation anywhere
* `mushroom.py:139` `forget()` drifts every gain back toward 1.0
* `mushroom.py:144` `apply()` writes `base * gain`, preserving every synapse's
  sign and only shrinking magnitude

Wrong:

* `mushroom.py:67` `pam_in = |W[pam][:, mbon].sum(axis=0)|`
* `mushroom.py:68` `ppl_in = |W[ppl1][:, mbon].sum(axis=0)|`

Its own docstring (`mushroom.py:17-23`) says these are "for each MBON, total
PAM input weight … against total PPL1 input weight". Under post-by-pre,
`W[pam]` selects PAM neurons as **post** and `[:, mbon]` selects MBONs as
**pre**, so what is computed is **MBON→DAN feedback**, not DAN→MBON
dopaminergic input. Both circuits are real; they are not the same circuit and
in the mushroom body they are systematically crossed. The documented read
would be `W[mbon][:, pam].sum(axis=1)`.

The comment on `mushroom.py:66` — `# CSC: column j = targets of presynaptic j`
— is true and is most likely what misled the author: it is a statement about
storage that reads like permission to treat the first index as presynaptic.

### The evidence

A 9-neuron synthetic graph (`tests/upstream_audit/synthetic.py`, `mb_graph`)
with orientation fixed by construction: PAM_x→MBON_avoid and
PPL1_y→MBON_approach as the dopaminergic input, MBON_approach→PAM_x and
MBON_avoid→PPL1_y as the crossed feedback. Every orientation question is asked
with the sign rule **bypassed**, so DAN→MBON edges are present at full weight
and a failure cannot be blamed on them having been deleted.

| graph | upstream's `reward_side` / `punish_side` |
|---|---|
| DAN→MBON only (exactly what the docstring says it reads) | **both empty** — `dopamine(±1)` returns 0, nothing is ever depressed |
| MBON→DAN feedback only, no DAN→MBON edge at all | fully populated |
| both | `reward_side = {MBON_approach}` — **inverted** w.r.t. anatomy |

So the split is determined **entirely** by MBON→DAN output weight and ignores
dopaminergic input completely.

The two strict-xfail tests state the biology mushroom.py itself commits to —
appetitive dopamine depresses the PAM-innervated compartment, aversive the
PPL1-innervated one — and both fail. `test_what_upstream_actually_does_instead`
pins the inverted outcome positively. `xfail_strict` is on, so if anyone ever
fixes `mushroom.py:67-68` the suite goes red and this note has to be revisited
rather than rotting.

### Why the naive fix breaks learning

`test_on_the_shipped_pipeline_the_documented_read_is_not_even_computable` runs
the same graph through upstream's own `build_graph.main()`. Because dopamine
is signed 0.0 and zero-valued edges are dropped, `W[mbon][:, pam]` and
`W[mbon][:, ppl1]` are **identically zero**. Transposing the indices alone,
against the shipped `graph.npz`, would leave both sides empty and switch
learning off entirely.

That also explains why the defect was never noticed: on the real connectome
the transposed read is the only one that returns anything at all, and it
returns a plausible-looking split, which upstream's README then cross-checks
against the literature (MBON01/02/03 vs MBON04/10/11) and calls "a reassuring
sign the split is finding real structure". That cross-check is not evidence
either way — it is UNDETERMINED here, because we could not run the real graph.

### What a fix requires (not applied in this wave)

Two changes, both ours, neither upstream's:

1. A dopaminergic connectivity source the sign rule does not erase — e.g. keep
   a second, unsigned synapse-count matrix for modulatory edges alongside the
   signed fast-weight matrix, built from the same feather.
2. `pam_in = |W[mbon][:, pam].sum(axis=1)|`, and the same for PPL1.

Then re-check the resulting MBON split against the literature on the real
connectome, because the labels upstream reports today were produced by the
wrong read and carry no evidential weight.

Note on naming, so it does not get re-litigated: upstream's `reward_side` is
the set of MBONs a **PAM** neuron addresses. In the fly those are the
avoidance-driving compartments, and reward depressing them is correct. The
name describes which dopaminergic neuron writes to the compartment, not what
the MBON drives. The mechanism is right; only the classification is
transposed.

## 3. Sensory path — VERIFIED (mechanism) / population sizes NOT ESTABLISHED

`tests/upstream_audit/test_sensory_and_readout.py`, 10 tests, all pass, run
against `flyeye.FlyEye` / `FlyPilot` unmodified over a synthetic retinotopic
graph.

**Exactly two populations receive external drive**, and nothing else in the
connectome does:

| population | selection | drive |
|---|---|---|
| L1 (lamina monopolar, ON) | `flyeye.py:26` `types == "L1"` **and** the annotation carries `assignedOlHex1/2` | `clip(lum, 0, 1) * 180 Hz` (`flyeye.py:76`) |
| L2 (lamina monopolar, OFF) | `flyeye.py:27` `types == "L2"`, same hex requirement | `clip(1 - lum, 0, 1) * 180 * 0.6 Hz` = max 108 Hz (`flyeye.py:77`) |

Injection mechanism, all measured:

* Units are **Hz**, converted at `flysim.py:124` to a per-step Bernoulli
  probability `rate * dt / 1000`, dt = 0.2 ms, `clip(0, 1)`. The drive
  therefore **saturates at 5000 Hz** and anything above is silently identical.
* The refractory period (2.2 ms, `flysim.py:29`) caps any neuron at ~416 Hz.
* Injection is a **voltage clamp, not a current**: `flysim.py:151`
  `v[hit] = thresh + 1.0` overwrites the membrane potential. A driven neuron's
  own synaptic input is discarded on every step the drive fires — verified by
  showing that overwhelming inhibition onto a driven cell has no effect at
  all. A sensory encoder that stimulates a recurrent population is silently
  overriding it.
* Normalisation: **none beyond the clip**. The image is expected in [0, 1]
  luminance; out-of-range values saturate without warning. There is no
  contrast normalisation, no adaptation, no temporal filter, no noise.
* Sampling is egocentric: a 300 × 210 px window centred on the cursor
  (`flyeye.py:54`), each column's pixel index clipped into the image
  (`flyeye.py:68-69`). At an image edge many columns land on the same pixel,
  so the retinal image is not translation invariant there.

Upstream **claims** 892 retinotopic hex columns and, unused, 2,635 ORNs across
53 receptor types with a working cVA→ORN_DA1→pC1 pathway at 222 Hz. Those
counts come from the README and could not be checked (see below). The
olfactory channel is genuinely unwired in code — nothing in this repository
stimulates it.

## 4. Output / motor path — VERIFIED (mechanism) / counts and baselines NOT ESTABLISHED

Upstream reads out exactly **seven** populations (`flyeye.py:109-117`), all by
exact cell-type name, one of them split by measured soma side:

| key | type | soma side | role in a fly | upstream's use |
|---|---|---|---|---|
| `steer_L` / `steer_R` | DNa02 | L / R | turning by left–right asymmetry | cursor x |
| `fwd_L` / `fwd_R` | DNa01 | L / R | forward walking | cursor y |
| `back` | MDN | — | Moonwalker, backward walking | reverse |
| `stop` | DNp09 | — | stopping | **the click** |
| `click` | MN9 | — | proboscis extension motor neuron | recorded, **unused** |

Decoding arithmetic, measured (`flyeye.py:130-148`):

```
turn  = (steer_R − steer_L) / 450        dx = clip(turn, −1, 1) · 90
fwd   = mean(fwd_L, fwd_R) / 450         dy = −speed · 90
speed = clip(fwd − back, −1, 1) · (1 − clip(stop, 0, 1))
click = stop ≥ 330 Hz  AND  speed < 0.25
```

Each group is reduced to one scalar: the **mean** firing rate over its
neurons. 450 is a hand-chosen normaliser, not a measurement.

The only discrete action upstream produces is that single `click` bit. It is
gated on DNp09, not on MN9 — `flyeye.py:142-147` says why in as many words:
MN9 is a taste motor neuron and measures a flat 0 Hz under visual drive, so
"arriving and halting on a target is the click". That is upstream's own
admission that its commit signal is a repurposed stop signal.

Also: `click` is returned as `np.bool_`, not `bool` (`flyeye.py:148` ands a
Python bool with a numpy comparison). Trivial, but a `DecisionRecord` that
json-serialises it will raise.

### Baseline activity

**Under no stimulus every population is at exactly 0 Hz, and this is
structural, not a property of our synthetic graph.** `v` starts at
`v_rest` = −52 mV (`flysim.py:26`, `flysim.py:101`), threshold is −45 mV, the
leak pulls toward rest, and the only term that can push a neuron over is the
external drive at `flysim.py:151`. There is no noise term, no bias current and
no resting rate anywhere in the model. Verified over the whole population in
`test_there_is_no_spontaneous_activity_at_all`.

Consequences for Phase One, and they are not small:

* A 0 Hz readout means "not stimulated". It does not mean "chose to stay
  still". **WAIT cannot be decoded as the absence of activity** without saying
  so explicitly, and probably cannot be decoded that way at all.
* `flysim.py:101` resets `v` at the top of every `run()`. Nothing carries
  across control steps except the weights. There is **no neural memory of the
  previous decision** — the readout is a pure function of the current frame
  plus the learned gains. Any state the experiment needs (position, cooldown,
  streak) lives outside the brain.

Measured on the synthetic rig (400 steps = 80 ms of brain time, seed 1), to
show the shape of the response rather than real magnitudes:

```
condition             steer_L steer_R  fwd_L  fwd_R   back   stop     dx     dy  click
no stimulus               0.0     0.0    0.0    0.0    0.0    0.0    0.0    0.0  False
uniform bright           87.5   112.5   87.5  112.5    0.0    0.0    5.0  -20.0  False
uniform dark              0.0     0.0    0.0    0.0  125.0  412.5    0.0    2.1   True
mid grey                 62.5    62.5   62.5   62.5   62.5  362.5    0.0   -0.0   True
```

Real magnitudes are not established. Upstream reports DNp09 at 167–417 Hz
under visual drive; against a 330 Hz threshold that is a narrow margin, and a
uniform mid-grey field clicks on our rig.

### Which desired actions have no defensible mapping yet

| SPEC action | status |
|---|---|
| **instrument selection** | plausible. DNa02 left–right asymmetry is a genuine continuous, signed, lateralised selection variable; the fly really does choose a direction with it. Needs the real connectome to know how many DNa02 there are per side and how much dynamic range the difference has. |
| **BUY / SELL** | **no defensible mapping today.** Nothing in the readout is a two-way signed decision about an external object. MDN (backward) vs DNa01 (forward) is the only natural antagonist pair and it is locomotor, not evaluative. The honest candidate is the MBON approach/avoidance axis — that *is* the fly's valence readout — but we cannot classify MBONs into approach and avoidance until section 2 is fixed, and upstream's current labels were produced by the wrong read. |
| **WAIT** | **no defensible mapping today.** DNp09 (stop) is the obvious candidate and it is what upstream uses for its click, but with zero spontaneous activity "stop" and "not stimulated" are the same reading, and a mid-grey field crosses the threshold on our rig. |
| **position sizing** | out of scope by SPEC; belongs to execution policy. |

The next wave should investigate the MBON output axis before anything else.
It is the only population in the animal whose measured job is "how good is
this, approach or avoid", which is what a trading decision actually is; the
descending neurons are a steering wheel that upstream borrowed because it
wanted a cursor. But it is blocked on the section 2 fix and on the real data.

## 5. Persistence — VERIFIED

`tests/upstream_audit/test_persistence.py`, 7 tests, all pass.

One file, `$FLY_STATE_DIR/mb_gains.npz` (default `upstream/build/`),
`mushroom.py:46`. Format `np.savez_compressed`. Contents, exhaustively:

| key | what |
|---|---|
| `gain` | the per-synapse multiplier, float32, one per KC→MBON synapse |
| `pos` | the positions those gains apply to, used as an identity check |
| `rewards`, `punishments` | two integer event counters |
| `at` | `time.time()` at save |

**Not saved**: the eligibility trace, the graph hash, any encoder or decoder
version, any per-event history, any timestamps other than the last save.

Behaviour, all verified by running it:

* **Overwritten in place on every save, no history.** There is one file and no
  append-only log, no per-season file, no way to recover a previous state.
  Directly against SPEC's "never rewrite historical results" — replaced, not
  reused.
* Loading is guarded: `mushroom.py:186` compares length and `pos` and
  **discards** a mismatched vector rather than misapplying it. Good, and
  worth keeping.
* `load()` falls back to a `SHIPPED` file inside the repo when the volume is
  empty (`mushroom.py:182`), so a fresh deploy silently inherits whatever
  learning was committed. For a reproducible experiment this must be explicit,
  not a fallback.
* **Both save and load swallow every exception** (`mushroom.py:170`,
  `mushroom.py:193`). A failed save is completely silent; a corrupt store
  silently restarts from baseline. Verified with an injected `OSError` and with
  a deliberately corrupt file.
* The eligibility trace is lost across a restart, so a dopamine event arriving
  immediately after a restart depresses nothing. Matters because SPEC's reward
  arrives after an outcome, potentially minutes after the decision.
* In `roam.py` the cadence is: `observe()` + `forget()` every control step
  (`roam.py:569-570`), `dopamine()` + `apply()` only on an event
  (`roam.py:634,644,659`), `save()` every 40 steps (`roam.py:670`). Note that
  `forget()` alone never reaches the simulation weights — the drift only lands
  when the next dopamine event calls `apply()`.
* Trace decay is 0.55 **per control step**, not per millisecond. At roam.py's
  2 Hz that is an eligibility window of roughly 0.5–1.5 s of wall time. It is
  a free parameter dressed as a biological constant.

## 6. Safety and money — inventory of what to keep out

None of this is reused. Recorded so it stays out.

| file | what touches money / the outside world |
|---|---|
| `rhwallet.py` | generates a secp256k1 key, writes `FLY_RH_SECRET` **into `.env` in plaintext** (`rhwallet.py:60`), refuses to overwrite an existing one. Never prints it. Chain id 4663, RPC `rpc.mainnet.chain.robinhood.com`. |
| `rhprovider.py` | injects an EIP-1193 `window.ethereum` into a real page. Key never enters the browser: `personal_sign`, `eth_signTypedData_v4` and `eth_sendTransaction` are handled in Python via `page.expose_function`. `send_transaction` (`rhprovider.py:178`) fills nonce/gas, signs and broadcasts `eth_sendRawTransaction`. **Everything not in its switch falls through to `__flyEthRpc`, an unrestricted RPC passthrough from page to node** (`rhprovider.py:64-66`, `158`). |
| `rhlive.py` | drives a browser through a launchpad and presses the button. 1,172 lines. |
| `roam.py` | drives a browser around the open internet, opens a **public ingress-helper ingress** and streams frames over it. |
| `voice.py` / `xpost.py` | calls an LLM through OpenRouter and posts to X. |
| `site/api/state.js`, `site/server/main.py` | read-only chain proxies. No key, no write method, hardcoded call set — not an arbitrary passthrough. |

Arming, verified by reading every reference:

* Two independent flags, both default `0`, both in `.env`:
  `FLY_ALLOW_BROWSER=1` before a browser opens at all (`rhlive.py:58`,
  `roam.py:783`), `FLY_RH_LIVE=1` before anything is signed
  (`rhlive.py:579`, `649`, `1016`). `allow_send=live_flag` is passed into the
  provider (`rhlive.py:676`), and `rhprovider.py:164-165` raises when it is
  false. A restart returns to the disarmed state because both are read fresh.
* **But** `envcfg.py:16` merges the process environment **over** `.env`:
  `{**env, **{k: v for k, v in os.environ.items() if k.startswith("FLY_")}}`.
  An exported `FLY_RH_LIVE=1` arms live signing even though `.env` says 0.
  Our arming must not have that property.
* `roam.py` rails: a domain allowlist (`roam.py:107-118`) which
  `FLY_ROAM_OPEN=1` removes entirely, a keyword blocklist the author correctly
  calls a second line of defence, and a click veto (`roam.py:134-138`) that
  refuses anything reading as submit/buy/sell/trade/connect-wallet/approve.
* `rhdryrun.py` exercises the whole signing path including signature recovery
  and contains no code path that can broadcast. A good pattern; worth copying.
* `rhlive.py:41` defaults the token's X handle to `elonmusk`. The README
  correctly calls this a test value and warns it is impersonation. It is still
  a default in code.
* `roam.py:169` hardcodes a Windows path in the author's home directory for
  `ingress-helper`. Portability artifact, harmless.

## Not established — and why

Everything below needs `data/*.feather` from
`storage.googleapis.com/flyem-male-cns/v1.0/connectome-data/` (~1.15 GB total;
the annotations file alone is 14 MB). **This wave was instructed not to use
the network beyond the clone and package installs, so nothing was
downloaded.** These are not failures of the audit; they are one authorisation
away.

1. **Real population names and counts** — how many L1, L2, DNa02 per side,
   DNa01, MDN, DNp09, MN9, KC, MBON, PAM, PPL1, ORN. Everything in sections 3
   and 4 above is mechanism verified on synthetic graphs plus README claims.
   Needs `body-annotations.feather` (14 MB) only.
2. **Real baseline firing rates** under the upstream stimulus. The zero-under-
   no-stimulus result is structural and does hold; the *magnitudes* under
   stimulus are not established. Needs the full 1.1 GB weights file and a
   `build_graph.py` run.
3. **Whether the real MBON split is inverted, or merely undocumented.**
   Upstream's MBON01/02/03-vs-MBON04/10/11 claim was produced by the
   transposed read; whether the corrected read agrees, disagrees or returns
   nothing is exactly the question and it needs the real graph.
4. **Upstream's headline numbers** — 165,122 neurons, 10,228,000 synapses,
   892 hex columns, 44,042 KC→MBON synapses, 2,635 ORNs. All unverified README
   claims. `assets/gains_ui.npz`, which was built against the real data,
   contains 260 tuned cell-type names with type codes up to 11662, implying at
   least 11,663 distinct cell types — consistent with a connectome of that
   size, and the only independent corroboration available offline. It contains
   L1, L2, R1-R6, DNa01, DNa02, DNp09, MDN, MN1/6/9 and no MBON, KC, PAM or
   PPL1, confirming the tuned gains cover the visuomotor loop only.
5. **The plasticity effect sizes** in the README (−6.0% reward-side, −0.9%
   punishment-side, +0.3% Kenyon cells over twenty encounters). Not reproduced.

## Verification status

| item | status |
|---|---|
| matrix orientation | **VERIFIED** by execution |
| pre/post indexing in mushroom.py's synapse selection | **VERIFIED** correct |
| eligibility traces | **VERIFIED** correct (keyed on presynaptic KC) |
| depression direction, floor, recovery | **VERIFIED** correct |
| PAM/PPL1 directionality | **INCONSISTENT** — transposed, `mushroom.py:67-68` |
| KC→MBON synapse selection | **VERIFIED** correct |
| persistence | **VERIFIED**, with defects listed above |
| sensory injection mechanism, units, normalisation | **VERIFIED** by execution |
| motor readout mechanism and arithmetic | **VERIFIED** by execution |
| no spontaneous activity | **VERIFIED** over the whole population |
| simulation determinism under a fixed seed | **VERIFIED** |
| real population names, counts, baseline rates | **NOT ESTABLISHED** — no data |
| the real MBON reward/punish split | **UNDETERMINED** — no data |
| upstream's headline counts and effect sizes | **UNVERIFIED** — README claims |

## Modified upstream behaviour

**None.** No file under `upstream/` is edited, patched or wrapped in this
wave. The tests import upstream modules and repoint module-level constants
(`build_graph.DATA`, `build_graph.BUILD`, `mushroom.SHIPPED`, `FLY_STATE_DIR`)
so nothing reads or writes the vendored tree; no upstream line is changed.

---

## Phase 0.5 addendum (2026-09-11) — what the data settled

The "Not established" list above was written when the connectome had not been
downloaded. It has been, under `data/malecns-v1.0/` (provenance in
`data/MANIFEST.md`). Detail lives in `docs/POPULATIONS.md` and
`docs/ARCHITECTURE.md` §v0.5 and is not repeated here; this is only the
status change.

| was | now |
|---|---|
| 1. real population names and counts | **established** — `docs/POPULATIONS.md` |
| 2. real baseline firing rates under stimulus | **established**, with a caveat that dominates everything: at upstream's default gains the network **saturates** — every KC and MBON at ~440 Hz and no odour selectivity at all. Magnitudes are only meaningful at a declared operating point (`ARCHITECTURE.md`, "Operating point") |
| 3. whether the real MBON split is inverted | **answered: it is materially wrong.** 46 of 97 MBONs and 12,606 of 44,042 KC→MBON synapses change compartment under the corrected read. MBON01–10 are PAM-innervated and MBON11–15 PPL1-innervated, which is where the literature puts them; upstream's read does not reproduce that, and puts MBON04 and MBON10 on the wrong side |
| 4. upstream's headline numbers | **all five confirmed** as arithmetic: 165,122 neurons, 10,228,000 edges, 892 hex columns, 2,635 ORNs, 44,042 KC→MBON synapses. Upstream's 27,939/14,349 split is also reproduced exactly — by running upstream's own code, which is what makes it evidence of the transposed read rather than of the anatomy |
| 5. the plasticity effect sizes (−6.0% / −0.9% / +0.3%) | **still not reproduced.** Our conditioning run is a different protocol with a different stimulus and a declared operating point, so its numbers are not comparable and no attempt was made to match them |

Two further facts, both new and both measured:

* **`receptorType` is empty for every traced neuron**, so `FlyBrain.where(receptor=…)`
  matches nothing on v1.0 and the README's "53 receptor types" is 53
  glomeruli, read out of `ORN_<glomerulus>` type names.
* **`build_graph.py:75`'s bounds bug does not fire on v1.0** but the lookup it
  builds would be 1.57 GB (max bodyId 1,571,825,087). `flytrade/graph.py` uses
  `searchsorted` against the sorted body index instead.

**Upstream is still unmodified.** The two strict xfails in
`tests/upstream_audit/test_mushroom_orientation.py` still fail, still strictly,
and `git diff --stat c26d680 -- tests/upstream_audit` is empty. The fix lives
in `flytrade/mushroom.py` and is tested separately in `tests/core/`.
