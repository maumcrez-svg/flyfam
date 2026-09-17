# D11 — recent-activity admission, sensory context v2 and the reinforcement scale

**Registration, written before any D11 number exists.** This file and
`experiments/d11/config.json` are committed **alone**, before the reward
calibration is computed, before the two fitted feature scales are fitted and
before the retrospective diagnostic is run. That is Fable addendum 2, step (i),
and it is the same discipline `a389978` held for D10 and `56fc96d` for D10's
live stage.

Source: `docs/SPEC.md`, the D11 canonical amendment (owner, 2026-09-12), the
owner rationale recorded with it, and the nine Fable addenda. Starting point
`e9c1632`, tree clean. Reconciliation of section 2: `1eb10b7`. The v2
modules: `462b3b9`.

---

## 0. What this wave is, and what it is not

D11 corrects the **preparation of the Pons experience** — which candidates are
admitted, what the brain smells, and how the size of an outcome reaches the
dopamine event. It is design, implementation and focused tests.

**D11 runs no neural experiment.** No new RPC collection, no live exercise, no
historical or live market-neural run, no parameter search, no visual work, no
real money. The only numbers computed in this wave are the reward calibration,
the two fitted feature scales and the retrospective admission/encoder
diagnostic — all from artifacts already on disk.

Nothing under `experiments/d10/` changes. The D10 identities, logs,
checkpoints and the **pending live position** (`d10-live-001`, episode
72000315) stay exactly as recorded, recoverable under their original policy,
and are not cancelled, closed or migrated because the observation exercise
ended.

D10's result is not rewritten. Seven losses of seven was never a measurement
of the brain, and correcting the environment does not turn it into one.

---

## 1. Admission v2 — recent activity

`flytrade/pons/admission_v2.py`, beside `admission_v1`, which stays
byte-identical so every D10 log, test and the determinism check keep
reproducing.

**Constants, fixed engineering defaults, registered here before anything is
computed:**

| constant | value |
|---|---|
| `recent_window_seconds` | **120** |
| `minimum_valid_trades_in_window` | **2** |
| `maximum_seconds_since_last_trade` | **60** |

These three numbers are an explicit initial engineering choice, not a discovery
about which tokens profit. They are not searched, not tuned, and not revisited
after a run is observed.

**A new entry is admitted iff** every `admission_v1` condition holds **except**
its "≥ 3 trades ever" — route `pons-v2`, native ETH quote, curve not completed
at the cutoff, reconstructed state valid, the 0.01 ETH paper buy does not
exhaust the curve, age ≥ 60 s, and in replay `cutoff + latency + horizon`
inside coverage — **and**, at the cutoff, there are at least **2 valid trades**
inside `(cutoff − 120 s, cutoff]` **and** the last of them is at most **60 s**
before the cutoff.

**A valid trade** is a `CurveBuy` or `CurveSell` with a nonzero quote leg and a
nonzero token leg, deduplicated by log id, with orphaned and removed logs
excluded. Creation, liquidity configuration, `CurveCompleted` and duplicated
log lines are not trades; a snipe-tax exemption is not a trade, and a
snipe-taxed buy is an ordinary one. **Buys and sells count the same.** The same
definition is shared with `pons_context_v2`.

Everything is evaluated against the canonical market-information cutoff, from
events available at that cutoff. No future event enters an admission decision.

**Admission is never ranked** by future returns, eventual survival, ticker, the
direction of the recent return, promoter identity or a desired trading outcome.
These are recent-activity filters. They are **not** an organic-flow,
anti-manipulation or profitability classifier.

**Reversible by construction:** admission is recomputed fresh at every tick from
the tape as it stands, so an inactive candidate returns the moment new
qualifying activity appears. Nothing is carried between ticks except the
rotation counter.

**Reason codes**, distinct from each other and from the neural statuses:

`INACTIVE` · `INSUFFICIENT_HISTORY` · `COLLECTOR_LAG` · `QUOTE_UNSUPPORTED` ·
`ROUTE_COMPLETED` · `STATE_INVALID` · `COVERAGE` · `CURVE_EXHAUSTED`

plus two carried unchanged from v1: `ROTATED` (admitted but not presented this
round) and **`DEPLOYMENT_UNSUPPORTED`** — a **declared addition** to the eight
the addendum names, because dropping it would either admit a v1-factory curve
or mislabel it as `QUOTE_UNSUPPORTED`. The round's record carries the per-token
reasons.

`COLLECTOR_LAG` means the observation's confirmed/fast block is more than two
ticks (60 s) behind the cutoff clock; in replay it can never fire. **A
collector outage is never a sea of `INACTIVE`:** when every considered token is
excluded by `COLLECTOR_LAG` the round is marked **`DATA_LAG`**.

Rotation is unchanged, round-robin, blind to every price. Fewer than six
candidates are used when fewer qualify. When none qualify the round is
**`NO_ELIGIBLE_CANDIDATES`**, nothing is presented, and no criterion is ever
relaxed automatically to force a decision.

**Admission controls new entries only.** A held position is observed, marked
and settled at its own horizon regardless of whether its token still satisfies
admission.

---

## 2. Context v2 and encoder v2 — preserve the difference

`flytrade/pons/context_v2.py` and `flytrade/pons/encoder_v2.py`, beside the v1
modules, which stay byte-identical.

**Ten features, in this order, all causal at the cutoff and clipped to the
launch exactly as D10 clips:**

| # | feature | what it measures | scale | rule for that scale |
|---|---|---|---|---|
| 1 | `age` | seconds since the launch block | **600 s** | fixed constant, carried from `experiments/d10/config.json` |
| 2 | **`since_last_trade`** | seconds since the last valid trade; the age when the token never traded | **60 s** | **declared constant**, equal to `maximum_seconds_since_last_trade`, so an admitted token spans `tanh(x/60) ∈ (0, 0.76]` and a held token that goes quiet keeps rising toward 1. Not fitted to any sample |
| 3 | `ret_30s` | log change of the marginal curve price over 30 s | **0.0051** | fixed constant, carried from D10 |
| 4 | `ret_2m` | the same over 120 s | **0.11** | fixed constant, carried from D10 |
| 5 | `ret_5m` | the same over 300 s | **0.36** | fixed constant, carried from D10 |
| 6 | `flow_imb_2m` | `(buy quote in − sell quote out) / (their sum)` over the window | **1.0** | fixed constant, carried from D10 (the feature is bounded in `[−1, 1]`) |
| 7 | **`trade_count_2m`** | valid trades inside `(cutoff − 120 s, cutoff]`; replaces D10's `trade_rate_2m` | **fitted by rule X, value pending the calibration commit** | rule X, below |
| 8 | **`gross_volume_2m`** | Σ \|curve-side quote delta\| over the valid trades of the window, in ETH | **fitted by rule X, value pending the calibration commit** | rule X, below |
| 9 | `rv_2m` | SD of per-trade log marginal-price changes over the window | **0.029** | fixed constant, carried from D10 |
| 10 | `drawdown_5m` | log distance below the 5-minute maximum, ≤ 0 | **0.51** | fixed constant, carried from D10 |

`gross_volume_2m` is the **gross** traded volume, the absolute sum, against
`flow_imb_2m`'s signed one: a buy contributes its net quote into the curve
(`quoteIn − fee − tax`) and a sell its gross quote out of it
(`quoteOut + fee + tax`) — the same signed quantity `TokenTape.apply` stores as
`flow`, summed in absolute value. That per-leg convention is a **declared
definition**, chosen because it is exactly what the reconstructed tape carries.

**Rule X, registered before it is computed.** The scale of a fitted feature is
**p90 of |x| over the 30-second grid points of the tokens launched in the first
60 minutes of `d10-backfill-v1` at which `admission_v2` admits that token at
that grid point**, computed causally at each grid point with the tape truncated
there, **rounded to two significant figures**. No outcome, no post-cutoff
return, no PnL and no survival is computed anywhere in the fitting, and the fit
is never repeated after a run is observed. The denominator is the admitted
(token, grid point) pairs and its size is recorded in
`experiments/d11/feature_scales_v2.json`.

**`since_last_trade` is a sensory input.** It enters the olfactory channels like
every other feature and is never fed to a reward or output neuron.

**The four owner distinctions become measurable in the deterministic rate
vector:**

* **A** — no trades in the interval: `trade_count_2m = gross_volume_2m = 0`,
  `since_last_trade` large.
* **B** — many trades, almost no net price change: count and volume high,
  returns ≈ 0, `rv_2m` small.
* **C** — balanced buys and sells with meaningful gross volume: volume high,
  `flow_imb_2m ≈ 0`.
* **D** — missing or incomplete: **not presented at all**; the status is
  `INSUFFICIENT_TAPE`, `INCONSISTENT_STATE` or `COLLECTOR_LAG` and the reason
  is recorded. **Never a zero vector.**

**Missing data is never turned into a legitimate zero**, and no random jitter,
ticker-dependent stimulation or invented activity is added. Identical measured
contexts are allowed to encode identically: two tokens with equal raw vectors
and different addresses must produce equal rate vectors, and a test asserts it.

Ten features → **20 channels of the 31 candidate glomeruli**, 1,070 ORNs. The
channel map is written into `config.json`. Five features never change sign —
`age`, `since_last_trade`, `trade_count_2m`, `gross_volume_2m`, `drawdown_5m` —
and keep the two-channel rule anyway, declared as D10 declared its three.
`rv_2m` is non-negative by construction and, as in D10, is not listed among
them.

The existing verified olfactory pathway is used unchanged. **No gain and no
decoder retune** to compensate for an encoding error.

**Encoder version and schema hash.** `pons_encoder_v2` carries
`encoder_version = "pons_encoder_v2"` and
`input_schema_sha256` = sha256 of the canonical JSON
`{"features": [ordered names], "scales": {name: scale}, "channels": [channel map]}`
with sorted keys and no whitespace. Both are written into the **checkpoint
metadata**. **Loading a checkpoint whose metadata carries a different schema
hash for continued learning raises**, unless the run is declared
`from_clean_reference` **and** the checkpoint is the clean reference — which
predates the field and is the only checkpoint allowed to lack it. The hash
cannot exist until the two fitted scales do, so it is written by the
calibration commit with them.

---

## 3. The reinforcement scale — one fixed rule, registered before it is computed

**The calibration set, selected before any value is computed:** the distinct,
confirmed D10 LEARN outcomes that actually generated the reported learning
updates — the **eight** `LEARNING` records that exist:
`d10-001/learning` episodes **4000000, 36000009, 68000017, 100000022,
132000028, 165000109, 203000217** and `d10-live-001` episode **7000087**.

Excluded, and why:

* the **determinism re-run** of `d10-001/learning` — the same events, not new
  ones (same normalised sha256 `34a74b0b780e…`);
* the eight **`SETTLED_FROZEN`** outcomes of `d10-001/frozen_reference` — no
  reinforcement was ever called on them;
* the **pending** live position `d10-live-001` episode 72000315 —
  `PENDING_CONFIRMATION`, no exit leg, no settlement;
* every estimated or unavailable settlement.

`net_return = net_pnl / notional` with notional **0.01 ETH**, read back from the
`OUTCOME` records **and** re-derived from the leg integers published in
`experiments/d10/closure_complement.md`; the two must agree. Every cost stays
included.

**The calibration rule, verbatim:**

```
q = 90th percentile of abs(net_return)
    over the calibration set, with linear interpolation.

new_full_scale = max(old_full_scale, 2 * q)
```

with `old_full_scale = 0.01`.

The existing signed normalisation/clipping mechanism, the neutral treatment
(`r == 0` delivers nothing), the learning rate, `REINFORCE_CAP = 1.0` and the
eligibility rules are all preserved. **Only the full-scale parameter is
replaced.** The same scale is used for positive and negative outcomes: no
average loss subtracted, no cost refunded through the reward, no net loss
converted into positive reinforcement.

**`reinforce_full_scale` becomes a per-experiment configuration parameter**,
carried in this wave's `config.json` and read by the Pons loop's execution
policy. `flytrade.execution.REINFORCE_FULL_SCALE` stays **0.01**, every
D5–D10 code path stays byte-identical, and the IBM historical loop keeps
reading its own config's 0.01 — asserted by a test on a fixed outcome.

The scale is **frozen** for the next experiment version. No rolling
recalibration during operation, and the multiplier, the quantile and the scale
are never tuned after observing a BUY frequency or a run's performance. The
proposed rewards are **not** applied to any old checkpoint.

This small, selected sample — eight outcomes, one 15-minute horizon, one
instrument class, one window — is a **coarse engineering reference for a scale
parameter**, not an estimate of the memecoin market's return distribution.

---

## 4. Local evidence without a new neural run

`experiments/d11/retrospective.py` → `experiments/d11/retrospective.md`, over
the recorded decision cutoffs of `d10-001/learning` (272 ticks) and
`d10-live-001` (111 ticks) and the chain stores those runs read. Per tick: the
candidates admitted by v1 (as recorded) and by v2 (recomputed at that cutoff,
with the tape truncated there), the exclusion reasons, the rounds with zero
eligible candidates, the available candidate counts and rotation coverage, the
**deterministic sensory collisions** before and after — from the encoder's rate
vectors at 1e-9 Hz, before Poisson sampling, never from display fields — the
seventeen entries re-identified with their v2 verdict, and worked A/B/C/D
examples drawn from real tokens with their rate vectors.

**Every eligibility calculation stops at the historical cutoff.** No subsequent
trade is inspected to decide admission.

It is a retrospective admission/encoder diagnostic. **It is not a backtest, and
it computes no trade the corrected brain would have made.** If v2 leaves few
candidates, that limitation is reported; the admission rule is **not** loosened
because of it.

---

## 5. Register-then-compute, the two commits

* **Step (i)** — this file and `config.json`, **alone**, before any D11 number
  exists. It is the commit this file is first added in; its hash is filled in
  below by a later docs commit, because a commit cannot cite itself.
* **Step (ii)** — one commit that writes the computed `reinforce_full_scale`,
  the two fitted feature scales and the `input_schema_sha256` those numbers
  determine into `config.json`, together with `reward_calibration.json` and
  `feature_scales_v2.json`, **and nothing else**.

Both hashes are cited here by a **following docs commit**, never by the
calibration commit itself, which must contain the numbers and nothing else:

| step | contents | commit |
|---|---|---|
| (i) registration | `PLAN.md` + `config.json`, alone — exactly two files | **`481dd3e`** |
| (ii) calibration | the two artifacts and the nulls they fill in `config.json` — exactly three files | **`87b8b2f`** |

**The citation lives in a following docs commit**, not in `87b8b2f`, which
carries the numbers and nothing else. The numbers `87b8b2f` wrote are
`reinforce_full_scale` **0.131032424** (from q = 0.065516212),
`trade_count_2m` **190.0**, `gross_volume_2m` **5.7** and
`input_schema_sha256`
**`3bf4f34c334a47cc960ad2619e091c4978f24d3eab0add63bb5c0a9501ff4615`**.

Nothing in either artifact is changed after step (ii).

---

## 6. The next run, declared and not run

**`d11-001`**, from the declared **clean reference checkpoint
`ba95b60503d658e989b649ecd3994264791fbead92f0bdacfd555e5d86ab61f5`** (graph
`8feb08a0d2a8…`, 44,042 plastic synapses, gain 1.0) — one replay branch on
`data/pons/d10-backfill-v1`, then one live hour, with an evaluation designed
**before** the run.

It is an explicit **new encoder/environment experiment** under a new identity,
not a silent erasure of D10's losses or learned state. And because admission,
sensory context and the reinforcement scale move together, a later behavioural
difference **cannot** be attributed to any one of them: `d11-001` must be
reported as an integrated environment repair, never as isolated proof about one
component.

D11 stops before it. The decision is the owner's.

---

## 7. `d11-001` — the preregistered Pons learning evaluation

**Registration, written before any `d11-001` number exists.** This section and
`experiments/d11/d11_001.json` are committed **alone**, before the first
request to any node, before the collection, before the split and before the
brain runs. That is step (ii) of Fable addendum 2 for this wave, the same
discipline `481dd3e` held for D11's design and `a389978` for D10.

Source: `docs/SPEC.md` — the owner's D11-001 spec (2026-09-13, verbatim), the
owner's decision on the data, and the thirteen Fable addenda that go with them.
Starting point `e4193a6`, tree clean. Everything section 1–5 registered —
`admission_v2`'s three constants, `pons_context_v2`'s ten features and their
scales, `pons_encoder_v2`'s `input_schema_sha256`, `reinforce_full_scale`
0.131032424 and the clean reference `ba95b60503d6…` — is **read from
`experiments/d11/config.json` and is not restated**, so there is one place
where each of those numbers lives.

### 7.1 What changes from the spec, and why

The owner's spec says "use only `d10-backfill-v1`". The owner's own decision,
recorded beneath it, replaces that: `d10-backfill-v1` spans 135.8 minutes, its
70 % learning partition is 95 minutes, and with one position at a time and a
900-second hold the **geometric ceiling is 5 to 6 completed episodes against a
floor of 20** — inconclusive by construction. The chosen remedy is more
market, not a changed experiment: a **new 12-hour backfill, `d11-backfill-v1`,
collected through the local Nitro node**, with the executor untouched — one
open position, a 15-minute hold, `k = 8`, `admission_v2`, `pons_context_v2`,
scale 0.131032424. `d10-backfill-v1` stays immutable as the historical
baseline. Nothing else in the spec moves.

### 7.2 The three steps, and where each stops

| step | contents | when |
|---|---|---|
| (i) | the spec commit — the owner's D11-001 spec, the data decision and the addenda | `e4193a6` |
| (ii) | **this section and `d11_001.json`, alone** — the window rule, the loopback budget and its projected cap, the split rule, the grid and label definitions, the statistics plan, the inconclusive conditions verbatim, the saturation definition | before any request |
| (iii) | numbers only — window blocks and timestamps, the cutoff `T`, tick counts per partition, the geometric ceiling, grid rows and label class balance | after the collection, before the brain |

**Hard stops**, each ending the wave with a report and no neural run: no
verified local node; any historical call that needs state the node does not
hold; or a pre-computable inconclusive condition already failed by construction
(fewer than 100 settled grid labels, fewer than 20 in either class, or a
geometric ceiling under 20). Nothing is re-chosen after a stop — the owner
decides.

### 7.3 The node, and the one declared widening

Addendum 3 names `127.0.0.1:8547` then `127.0.0.1:8545`. Those two are probed
first and in that order. **Declared deviation, registered here before the first
request:** if neither verifies, the probe continues over the loopback host
ports **published by a local container whose image identifies a Nitro node**,
then over any other loopback port served by a local Ethereum node process —
both read from the local process and container tables, which send no request to
any node. The owner's decision put the address in the agent's hands
("*Agente descobre sozinho*") and told it to *verify* rather than assume a
port; a fixed two-port list would turn a node that exists into a false hard
stop. **The verification rule is not widened at all:** `eth_chainId` must
return 4663 **and** the `latest` block's timestamp must be within 300 s of wall
clock. No JSON-RPC request is ever posted to a loopback port that is not served
by an Ethereum node process.

The endpoint is committed as `experiments/d11/local_node.env`
(`LOCAL_NITRO_RPC_HTTP`), a loopback URL and not a secret, and is passed
through the existing `--env-file/--env-key` path. **The stockroom `.env` is
neither read nor written in this wave.**

### 7.4 The budget, separated

`flytrade/pons/budget.py` classifies an endpoint by host — `127.0.0.1`,
`localhost` and `::1` are **loopback** — and a ledger opened in loopback scope
refuses a remote endpoint with `RPC_REMOTE_REFUSED` **before the socket opens**
unless `--allow-remote` is passed. **The agent never passes it**, and the final
report states the remote request count, which must be **0**. The loopback
ledger is `experiments/d11/rpc_ledger_local.json`, with its own counters; the
Chainstack caps, ledger and accounting do not move.

**The projection, stated before the first request.** 43,200 s at the measured
0.101 s median block interval is **427,723 blocks**; one header per 100 blocks
plus two is **4,279**; one factory `eth_getLogs` per 1,000-block segment is
**428**; the curve filter is 428 segments × address batches of 250 × two
500-block chunks, measured at 3.94 per segment on D10 and projected at six,
**2,568**; the `creatorTaxBps` fallback, 3 in 991 launches on D10, scaled and
rounded up, **20**; chain-id, head and safe reads **10**; the probe **40**.
**7,345, rounded to 7,400**, so the loopback caps are **3 × 7,400 = 22,200**
(wave, day and run), registered here and not raised afterwards.

### 7.5 The window, the split and the ceiling

**Window.** Twelve contiguous hours ending at the **confirmed head** at probe
time: `end_block` is `min(head − confirm_depth, safe)` under the collector's
own confirmation rule, and `start_block` is the smallest block whose timestamp
is at least `timestamp(end_block) − 43,200`. The window **must not overlap**
`d10-backfill-v1` (2026-09-12T01:37:36Z–03:53:25Z, blocks 60,721,229–60,801,426);
if it would, the end moves earlier until it does not. The `MANIFEST` records
`admission_minutes` **705**, `settlement_tail_minutes` **15**, the blocks, the
timestamps, the endpoint class and port, the per-method request counts and the
sha256 of every file. `initial_states.json` is **mandatory** — the offline
tracker needs it for exact reconstruction.

**Collected once.** Every later step reads the store; a test parses `run.py`,
`grid.py` and `evaluate.py` for network verbs and for `flytrade.pons.rpc`.

**Split, from timestamps only.** `t0 = timestamp(start_block)`,
`t1 = timestamp(end_block)`, `T = t0 + floor(0.7 · (t1 − t0))` snapped **down**
to the 30-second tick grid anchored at `t0`. One grid serves every partition,
every replay branch and the evaluation, so a cutoff is the same instant
everywhere. `T` is recorded in step (iii) before any outcome and before the
first neural number.

*LEARNING* ticks are `cutoff ≤ T`; an **entry** is allowed only if
`cutoff + 2 + 900 ≤ T`; ticks in `(T − 902, T]` observe, mark and settle and
never enter; **the run fails if a learning position is open at `T`**.
*FROZEN* ticks are `T ≤ cutoff` and `cutoff + 902 ≤ t1`, in **three temporal
blocks of equal duration** over the frozen grid's span.

**Geometric ceiling:** the number of non-overlapping 932-second slots (902 s
plus one tick) between the first LEARNING tick with at least one v2-eligible
candidate and `T − 902`. It is reported **beside** the episodes actually
produced.

### 7.6 The grid is a market-only scoring pass, not the loop

Presentation inside the loop depends on run state — while a position is held
only the held token is presented, and the round-robin rotation advances with
evaluated rounds — so **two frozen loop branches cannot share rows**. The
primary grid is therefore built from the store alone: at every FROZEN tick the
tapes are reconstructed offline, `admission_v2` is applied at that cutoff, and
**all** eligible candidates are taken — no cap of six, no rotation, no hold
mode, a superset of anything either loop branch could have presented. Each is
then scored by **both** frozen brains with the standard readout: `k = 8`
replicates under `comparison_v1`, seeded from `(observation_id, stable_id,
replicate index)` and **independent of the checkpoint digest**, which is what
makes the two branches draw the same Poisson stream for the same row. Rows are
keyed `(cutoff_ts, stable_id)` and are identical across branches by
construction. Both brains are loaded read-only and their digests are verified
before and after. **No execution, no bankroll, no reinforcement and no
checkpoint write happens in the grid.**

### 7.7 The evaluator-only label

Per row: a hypothetical buy of 10^16 wei at `cutoff + 2 s` through
`PonsPaperExecution.plan_buy` on a **fresh** execution object, the position's
own reserve delta carried exactly as the loop's settlement path carries it, and
the exit priced by `plan_sell` on the tape advanced by the recorded external
events at `entry_fill_block_timestamp + 900 s`. `net = quote_out − spent −
gas_buy − gas_sell − approval` with the D10 constants, by the same arithmetic
`ExecutionPolicy._settle` uses; the label is **positive iff `net > 0`**. An
`Unresolved` (route transition, coverage) or a `QuoteError` (exhausted curve)
is **UNRESOLVED**, excluded from the AUC and counted.

**It creates no trade, alters no bankroll, produces no reinforcement and
touches neither ledger nor checkpoint.** A known-answer test, written **before
the grid runs**, reproduces the recorded net of each of the **16 settled D10
entries** at their recorded cutoffs **to the wei**.

### 7.8 Statistics, fixed here

**Primary:** `ΔAUC = AUC(TRAINED) − AUC(REFERENCE)` over rows valid in both
branches carrying a settled label; AUC is Mann–Whitney with ties counted a
half. **Uncertainty:** a paired **cluster bootstrap by `stable_id`** — a
token's rows move together — **10,000 resamples, seed 20260913**, percentile
95 % interval, overall and per block.

**Wording, the owner's rule.** An interval that includes 0 is reported as
*compatible with sampling variation*; one that does not is reported with its
bounds. Never "significant", never "proves", no rate asserted as measured, and
an AUC near 0.5 is **not** evidence that no signal exists.

**Secondary, descriptive:** Spearman(score, net) per branch and their
difference, and the distribution of the per-row score difference
TRAINED − REFERENCE.

**Suppression on the grid:** the BUY-crossing rate (`V > θ`) per branch,
overall, per block and **by later outcome class**. The preregistered reading is
the between-class difference of the trained-minus-reference change with the
same clustered interval — **"global"** if that interval includes 0,
**"contextual"** if it excludes 0 with the larger drop in the negative class.
Nothing else is said in words, and **a lower BUY rate alone is not learning
success**.

**Known-answer tests:** AUC 1, 0 and ½ on perfect, reversed and constant toy
data; ties; identical branches → `ΔAUC` exactly 0; a one-cluster bootstrap is
degenerate.

### 7.9 Saturation, and the inconclusive conditions

**Saturation** is computed offline from the logged normalised vectors: a
channel is saturated when its normalised value sits at the clip bound. Both the
fraction of **(row, channel)** pairs and the fraction of **rows with at least
one** are reported; the inconclusive condition reads the (row, channel)
fraction.

The owner's five conditions, **verbatim**, not loosened after the run:

* fewer than 20 completed LEARNING episodes;
* fewer than 100 paired FROZEN candidate labels;
* either positive or negative outcome class has fewer than 20 labeled examples;
* paired neural coverage below 95 %;
* material encoder saturation or invalid-state rate above 5 %.

Each is evaluated **one by one** in the report, PASS or FAIL, with its number.

### 7.10 The order of the runs, and the live hour

LEARNING replay → the grid → the two FROZEN loop branches (descriptive paper
results, `SETTLED_FROZEN`, end digest equal to start digest) → the report →
**only then** one hour of `LIVE_PAPER` from the TRAINED checkpoint with
**learning enabled** (the declared d11-001 live branch), `starts_from_digest`
verified and recorded, against the local node under the loopback ledger with
the chain-id gate and the 120-second freshness rule. **If the node is not fresh
at start the live hour is not started and that is reported**, not worked
around. No parameter moves between replay and live, and the two are reported
separately.

**No real money, no signing, no funds.** The RPC method allowlist carries no
signing method and this wave adds none.

### 7.11 What d11-001 cannot say

D11 moved admission, the sensory context and the reinforcement scale
**together**. A difference between TRAINED and REFERENCE here is a difference
between one brain that saw 8.4 hours of this environment and one that saw none
— it can **never** be attributed to any one of the three. Profit is recorded
and is not the criterion: predictive learning is not declared from PnL, and
failure is not declared because the fly loses money. **Stop after d11-001.**

### 7.12 The probe's finding, and the one declared degradation

**Written after the probe and before the collection. It changes no parameter
of the experiment; it records what the local node can and cannot answer.**

Ports `8547` and `8545` — addendum 3's list — refused the connection. The
verified endpoint is **`127.0.0.1:8645`**, the loopback host port published by
the `offchainlabs/nitro-node:v3.11.1` container `nitro-robinhood` for its own
`8547`: `eth_chainId` **4663**, `latest` block **1 s** from wall clock.
`eth_blockNumber`, `eth_getBlockByNumber` (head, `safe`, and a block twelve
hours back), and a collector-sized `eth_getLogs` at the **old** end of the
window all answered. Measured finality: median block interval **0.10150 s**,
confirm depth **591**, `safe` supported.

**One call did not answer: `eth_call creatorTaxBps()` at a block twelve hours
back** — `missing trie node … state is not available`. The node is pruned, not
archival. The probe then **measured the boundary by bisection**: the oldest
block whose state it serves is **61,557,072**, about **111,900 blocks ≈ 3.16
hours** behind the head.

**This is a declared degradation, not a hard stop, and the classification is
written down rather than asserted.** A call is *needed* when its failure stops
the window being collected or changes a recorded event — every `eth_getLogs`
and every header read is needed, and every one of them answered. A call is a
*declared fallback* when the collector's own code already gives its failure a
named outcome. `eth_call creatorTaxBps()` is the only one:
`experiments/d10/backfill.py::read_creator_tax` returns `None` on an
`RpcError`, the launch is recorded `CREATOR_TAX_UNREADABLE` and left
`unavailable`, and it is never tracked. That is an outcome class D10 already
had **55 of 991** launches in.

**Its measured size.** On `d10-backfill-v1`: 991 launches, 614 initial states
derived offline from the recorded trades, **3 (0.30 %)** from this `eth_call`,
55 unavailable — all 55 for `NO_TRADE_TO_PIN_THE_CREATOR_TAX`, which no node
could have helped. So the worst case here is that **about three launches in a
thousand** lose their initial state and are not tracked.

**Mitigation, declared before the collection.** `experiments/d11/backfill.py`
pins the creator tax from **any** trade of the launch rather than only the
first — the same arithmetic on the same recorded data, with **no request** —
which is exactly what `experiments/d11/retrospective.py`'s offline tracker
already does. The residual is reported in the `MANIFEST` as
`initial_states_unavailable` and in the wave report.

**The live hour is unaffected**: its creator-tax read happens at a launch block
seconds old, far inside the node's 3.16-hour retained-state window, and a state
read at the head answered.

**No Chainstack.** The list a remote fallback would involve is recorded in
`experiments/d11/node_probe.json` under
`calls_a_chainstack_fallback_would_involve` with its cost — **1 call, 2
units** for the probe's own instance — and it is not used. `--allow-remote` is
never passed and the wave's remote request count is **0**.

The probe cost **34 loopback requests** of its 40-request cap (24 of them the
depth bisection), on `experiments/d11/rpc_ledger_local.json`.

### 7.13 One correction to the cutoff, before any neural number

`0.7 × 43200` is **30239.999999999996** in float64. Its floor is 30239, and
snapped down to the 30-second grid that is **30,210** — one tick short of the
30,240 the registered rule means. The first write of `split.json` carried that
artifact.

**It is corrected in integer arithmetic — `(7 × span) // 10` — which is the
rule as registered**, and `T` moves one 30-second tick later, from
`t0 + 30,210` to `t0 + 30,240`.

**The correction is arithmetic and is informed by no result.** No brain had
been run, no score, AUC or interval existed, and the only numbers observed were
the grid's row count and its class balance, which moved by one tick's worth:
5,182 rows / 489 positive / 4,531 — precisely, 5,182 / 489 / 4,536 became
**5,175 / 488 / 4,531**. The geometric ceiling is 32 either way. A test
(`tests/d11/test_d11_001.py::test_the_split_floor_is_rational_and_not_a_float_artifact`)
now pins the rational floor on five spans so the artifact cannot return.

Nothing else about the split, the window, the hold, the concurrency or the
scale moves, then or later.

### 7.14 The owner's amendment after dispatch, and the substitution it prescribes

The owner amended the wave mid-flight: *"Ele nao eh archive, tive q prunar, te
vira com ele, porra analisa dos inferno, pega ate onde da."* The archive-state
hard stop of addenda 3 and 5 is **withdrawn**; each historical `eth_call` the
D10 backfill made must be classified and substituted rather than abandoned, and
the substitution must be **verified**, not asserted. Chainstack stays
forbidden, `--allow-remote` is never passed, the stockroom `.env` is never
read.

**One call, one class.** The D10 backfill made exactly one kind of historical
state read: the creator-tax fallback at a launch block, used **3 times in 991
launches**. (`flytrade.pons.collector.read_initial_state`'s nine reads are
reachable from no run path.) The creator tax is a launch parameter of the
curve, so it is class **(a) immutable per curve** — and that is measured, not
claimed.

| verification | population | result |
|---|---|---|
| **(b)** reconstruct from events, **local files only, no request** — re-derive every recorded initial state of `d10-backfill-v1` with this wave's "pin from any trade" rule | **617** recorded initial states | **615 matched exactly** on every field (614 from the first trade, **1** from a later trade that D10 had paid an `eth_call` for); **2** unpinnable from events alone |
| **(a)** immutable per curve, read at `latest`, a ledgered loopback probe | the same **617** curves | **617 answered, 617 matched the value recorded at the launch block exactly** — 0 differed, 0 unanswered |

Class (a) is therefore verified on 617 of 617: the value does not move, and
reading it at `latest` is a sound substitution for reading it at a block the
node has pruned.

**Applied to `d11-backfill-v1`.** The collection's own class (b) rule left
**17** curves whose creator tax no recorded trade pins — class (c) under (b),
unavailable and untracked. All **17 were read at `latest`, all 17 answered**,
and their states are written with `source: latest_block_immutable`. **The class
(c) residue is 0.** The counts ride in the store's `MANIFEST.json` under
`initial_states` and `state_substitution`, and the artifact is
`experiments/d11/state_substitution.json`.

**The window met its target.** Twelve hours is what the node served, contiguous
in headers and logs across all 425,595 blocks, with **0 errors** and **0 range
retreats**; the `getLogs` probe at the old end returned 17 real logs. No
shrinking was needed and the earliest block served is the window's own
`first_block` 61,237,774.

**One re-run, and no selection.** The in-flight LEARNING replay was **stopped at
74 % and deleted before it produced a final episode count**, so there is exactly
one replay on exactly one store. The grid and the labels were rebuilt on the
completed store: 5,175 rows / 488 positive / 4,531 negative became **5,177 /
488 / 4,533**, from 6,114 reconstructed tapes to **6,131**. The geometric
ceiling is **32** either way. Nothing about the split, the window, the hold,
the concurrency or the scale moved.
