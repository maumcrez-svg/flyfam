# d11-001 — the preregistered Pons learning evaluation

**One replay on twelve hours of genuine PONS v2 market collected through a verified local Nitro node, split 70/30 by time, one brain carried through the earlier part and then frozen, and a market-only grid over the later part scored by that brain and by an untouched clean reference.** Preregistered in `experiments/d11/d11_001.json` and `PLAN.md` §7 before the first request; the window, the cutoff, the tick counts, the geometric ceiling, the grid and the class balance in `experiments/d11/split.json` before the brain ran.

Profit is recorded and is **not** the criterion. Predictive learning is not declared from PnL, and failure is not declared because the fly loses money. An interval that includes 0 is reported as *compatible with sampling variation*.

## 1. The node, and every request this wave made

| port | source | chain id | latest block age | verified |
|---|---|---|---|---|
| 8547 | addendum 3 | — | — | no — RPC_TRANSPORT_FAILED: URLError(ConnectionRefusedError(111, 'Connection refused')) |
| 8545 | addendum 3 | — | — | no — RPC_TRANSPORT_FAILED: URLError(ConnectionRefusedError(111, 'Connection refused')) |
| 8645 | container | 4,663 | 1 s | **yes** |

Verified endpoint **127.0.0.1:8645**, the loopback host port the `offchainlabs/nitro-node:v3.11.1-8512b8c` container publishes for its own 8547. `eth_chainId` **4663**, `latest` block **1 s** from wall clock. Measured finality: median block interval **0.10150 s**, confirm depth **591**, `safe` supported.

**One declared degradation.** The creator-tax state read at a twelve-hour-old block returned *missing trie node … state is not available*: the node is pruned. The probe bisected the boundary — the oldest block whose state it serves is **61,557,072**, **111,943** blocks (≈ 11,362 s ≈ 3.16 h) behind head. Every call the collection *needs* — the headers, the `safe` tag and a collector-sized log range at the old end of the window — answered. The creator-tax read is a **declared fallback** whose failure the collector's own code names `CREATOR_TAX_UNREADABLE` and leaves `unavailable`; `experiments/d11/backfill.py` pins the tax from any recorded trade rather than only the first, with no request, and the residue is **17 launches of 9,474** (0.26 % of the 6,599 native ones). **No Chainstack request was made, `--allow-remote` was never passed, and the remote request count is 0.**

**Requests, all loopback.** Ledger `experiments/d11/rpc_ledger_local.json`, wave and day caps 22,200 — three times the registered projection of 7,400 — with a per-entry-point run cap. Total **9,122 attempts / 16,825 units / 13 errors**; **remote requests: 0**. Every one of the 13 errors is accounted for: 11 refused state reads from the probe's deliberate retained-depth bisection, and 2 connection refusals on the two ports addendum 3 names, which nothing listens on.

| method | attempts | units | errors |
|---|---|---|---|
| `eth_blockNumber` | 3 | 3 | 0 |
| `eth_call` | 664 | 693 | 11 |
| `eth_chainId` | 6 | 6 | 2 |
| `eth_getBlockByNumber` | 5,309 | 10,203 | 0 |
| `eth_getLogs` | 3,140 | 5,920 | 0 |

| run | attempts | units |
|---|---|---|
| `d11-001-backfill` | 6,961 | 13,915 |
| `d11-001-probe` | 34 | 60 |
| `d11-001-state-substitution` | 634 | 634 |
| `d11-live-001` | 1,493 | 2,216 |

### The pruned node's historical state: every substituted call, its class, and how it was verified

The owner's amendment after dispatch withdrew the archive-state hard stop and asked for classification and substitution instead. **The D10 backfill made exactly one kind of historical state read** — the creator-tax fallback at a launch block, used **3 times in 991 launches**. (`flytrade.pons.collector.read_initial_state`'s nine reads are reachable from no run path.) The creator tax is a launch parameter of the curve, so it is class **(a) immutable per curve** — measured, not claimed.

| substituted call | class | substitution | verification | result |
|---|---|---|---|---|
| the creator-tax state read at the launch block | **(b)** reconstruct from events | pin the tax from **any** recorded trade of the launch, not only the first — no request at all | re-derive every recorded initial state of `d10-backfill-v1` from that store's own events, local files only | **615 of 617 matched exactly** on every field; 2 unpinnable from events alone |
| the same read | **(a)** immutable per curve | read at `latest` instead of at a pruned block | a ledgered loopback probe over the same population, compared with the value recorded at the launch block | **617 of 617 answered, 617 matched exactly**, 0 differed, 0 unanswered |
| applied to this wave's own residue | **(a)** | the curves whose tax no recorded trade pins, read at `latest` and written with `source: latest_block_immutable` | the store's `MANIFEST.json` under `initial_states` and `state_substitution` | **17 rescued of 17**; class **(c)** residue **0** |

**Class (c)** — mutable and not reconstructible — would have been marked unsupported and counted, and nothing would have been guessed. There are **0** such curves.

**The window against the twelve-hour target.** Twelve hours is what the node served: headers and logs contiguous across all 425,595 blocks with **0 errors** and **0 range retreats**, and the probe's log range at the old end returned 26 real logs. **No shrinking was needed**, and the earliest block served is the window's own `first_block`. One factory log in the window carried a `topic0` outside the pinned ABI and is stored `UNMAPPED` and undecoded, which is the collector's declared behaviour.

## 2. The window, the split, and the geometric ceiling

**`d11-backfill-v1`** — blocks **61,237,774 – 61,663,368** (425,595 blocks), **2026-09-12T16:12:44Z – 2026-09-13T04:12:44Z**, exactly **43,200 s**. It does **not** overlap `d10-backfill-v1` (blocks 60,721,229 – 60,801,426), which stays untouched as the historical baseline.

Collected once in 225 s: **462,056 events**, **9,474 launches** (6,599 native ETH, 2,875 on another quote), 79 curves completed, 4,258 headers. Initial states: 6,110 pinned from the first trade, 4 from a later one, 485 unavailable (468 never traded at all). Every later step reads this store; nothing after the collection reaches the chain.

| | value |
|---|---|
| t0 = timestamp(start_block) | 1789229564 |
| t1 = timestamp(end_block) | 1789272764 |
| **T** = t0 + floor(0.7·(t1−t0)) on the 30 s grid | **1789259804** (70.00 % of the span) |
| LEARNING ticks (cutoff ≤ T) | 1,009 |
| last LEARNING tick that may enter (cutoff + 902 ≤ T) | 1789258874 |
| FROZEN ticks (T ≤ cutoff, cutoff + 902 ≤ t1) | 402 |
| temporal blocks | 134 / 134 / 134 ticks |
| **geometric ceiling** (932 s slots) | **32** |
| **LEARNING episodes produced** | **15** (15 settled and reinforced) |

## 3. LEARNING replay

`REPLAY_PAPER`, `LEARN`, from the clean reference `ba95b60503d6…` under `from_clean_reference`, `pons_encoder_v2` schema `3bf4f34c334a…`, `admission_v2`, reinforcement full scale **0.131032424**. Entry refused at the partition boundary, and **no position was open at T** (`position_open_at_end` = no).

Ticks 1,009, tapes 4,643, tokens discovered 7,356. Digest `ba95b60503d6…` → **`bbca5c4ba65c…`** (TRAINED). Restarts: 0.

### Reinforcement, beside D10's 7 of 8

**15 updates** — 0 reward, 15 punishment, 0 neutral — and **11 clipped at the cap**. Normalised amount: min 0.2008, median 1.0000, max 1.0000. Raw return on notional ranged -0.811086 to -0.026316.

| # | episode | net (ETH) | return on notional | valence | normalised amount | clipped | synapses |
|---|---|---|---|---|---|---|---|
| 1 | 5000005 | -0.00178654 | -0.178654 | -1 | 1.0000 | yes | 2,060 |
| 2 | 37000026 | -0.00224675 | -0.224675 | -1 | 1.0000 | yes | 3,002 |
| 3 | 70000232 | -0.00450713 | -0.450713 | -1 | 1.0000 | yes | 2,075 |
| 4 | 103000376 | -0.00028612 | -0.028612 | -1 | 0.2184 | no | 2,735 |
| 5 | 137000573 | -0.00026316 | -0.026316 | -1 | 0.2008 | no | 1,724 |
| 6 | 170000699 | -0.00476361 | -0.476361 | -1 | 1.0000 | yes | 2,358 |
| 7 | 202000714 | -0.00205671 | -0.205671 | -1 | 1.0000 | yes | 4,115 |
| 8 | 252001081 | -0.00746210 | -0.746210 | -1 | 1.0000 | yes | 2,184 |
| 9 | 312001359 | -0.00312265 | -0.312265 | -1 | 1.0000 | yes | 2,891 |
| 10 | 360001615 | -0.00084816 | -0.084816 | -1 | 0.6473 | no | 2,066 |
| 11 | 414001805 | -0.00811086 | -0.811086 | -1 | 1.0000 | yes | 2,387 |
| 12 | 487002148 | -0.00503639 | -0.503639 | -1 | 1.0000 | yes | 2,981 |
| 13 | 540002454 | -0.00208714 | -0.208714 | -1 | 1.0000 | yes | 2,386 |
| 14 | 634002756 | -0.00453551 | -0.453551 | -1 | 1.0000 | yes | 3,064 |
| 15 | 766003602 | -0.00059705 | -0.059705 | -1 | 0.4557 | no | 3,241 |

**Historical context, not a comparison.** D10 ran the same rule at full scale 0.01 and clipped 7 of 8 updates at the cap, discarding the size of the outcome and keeping only its sign. The scale was calibrated once, before this run, and is not touched because this distribution looks weak or strong.

### Paper results (descriptive, never the learning metric)

Trades 15, gross -0.03733075 ETH, fees 0.01037912 ETH, slippage 0.00109753 ETH, **net -0.04770987 ETH**; holds 900–900 s (median 900 s); unresolved 0; marks 465.

Per-round actions: `{'WAIT': 364, 'BUY': 104, 'SELL': 523}`. After execution: `{'NO_ORDER:WAIT': 257, 'BUY': 15, 'HOLD:WAIT': 107, 'HOLD:BUY': 89, 'POLICY_CLOSE_FIXED_HOLD': 15, 'blocked_by_fixed_hold': 254, 'NO_ORDER:SELL': 269}`.

## 4. The FROZEN evaluation grid

**The grid is not the loop.** While a position is held the loop presents only the held token and the round-robin advances with evaluated rounds, so two frozen loop branches cannot share rows. Every FROZEN tick's tapes are rebuilt from the store, `admission_v2` is applied at that cutoff and **all** eligible candidates are taken — no cap of six, no rotation, no hold mode — then each is scored by **both** frozen brains with the standard k = 8 `comparison_v1` readout, whose seeds are keyed to `(observation_id, stable_id, replicate)` and **not** to the checkpoint digest. Rows are keyed `(cutoff_ts, stable_id)` and are built once, so the branches are identical by construction.

* **trained** — 5,177 rows, digest `bbca5c4ba65c…` before and after, unchanged: **yes**.
* **reference** — 5,177 rows, digest `ba95b60503d6…` before and after, unchanged: **yes**.

| | value |
|---|---|
| grid rows | 5,177 |
| rows VALID in both branches | 5,168 |
| **paired neural coverage** | **99.83 %** |
| rows with a settled label (the AUC denominator) | 5,013 |
| label class balance | 488 positive / 4,525 negative |
| UNRESOLVED labels | 156 ({'ROUTE_TRANSITION:SELL': 156}) |
| tokens (bootstrap clusters) | 1,042 |
| saturated (row, channel) pairs | 1,460 of 51,770 = 2.820 % |
| rows with at least one saturated channel | 1,424 (27.51 %) |
| INVALID_STATE rate, trained | 0.000 % |
| INVALID_STATE rate, reference | 0.000 % |

The evaluator-only label: a hypothetical buy of 10^16 wei at cutoff + 2 s through PonsPaperExecution.plan_buy on a fresh execution object, the position's own reserve delta carried as the loop carries it, the exit priced by plan_sell at entry_fill_block_timestamp + 900 s; net = quote_out - spent - gas_buy - gas_sell - approval, positive iff net > 0. Unresolved (route transition, coverage) or a QuoteError is UNRESOLVED, excluded from the AUC and counted. Its known-answer test — `tests/d11/test_label.py`, written and run **before** the grid's label pass — reproduces all **16 settled D10 entries**: `tokens_out_wei` exactly, the entry and exit blocks and instants exactly, and `net_pnl` and `return_on_notional` at the precision the records store them. Net over the settled rows: median -0.00066565 ETH, min -0.00919419, max 0.03321692.

## 5. The primary question — does training change the ranking?

AUC is Mann–Whitney with ties counted a half; the interval is a paired **cluster bootstrap by `stable_id`** — a token's rows move together — with 10,000 resamples at seed 20260913, percentile 95 %.

| | n | positive | AUC trained | AUC reference | ΔAUC | 95 % interval |
|---|---|---|---|---|---|---|
| **overall** | 5,013 | 488 | 0.4116 | 0.5885 | **-0.1769** | [-0.2180, -0.1246] |
| block 1 | 1,772 | 208 | 0.3739 | 0.5820 | -0.2081 | [-0.2696, -0.1139] |
| block 2 | 1,825 | 165 | 0.4358 | 0.5762 | -0.1404 | [-0.1960, -0.0247] |
| block 3 | 1,416 | 115 | 0.4429 | 0.6182 | -0.1753 | [-0.2994, -0.0421] |

**delta AUC (trained - reference) is -0.1769, 95 % interval [-0.2180, -0.1246] — an interval that excludes 0.**

* block 1 delta AUC is -0.2081, 95 % interval [-0.2696, -0.1139] — an interval that excludes 0.
* block 2 delta AUC is -0.1404, 95 % interval [-0.1960, -0.0247] — an interval that excludes 0.
* block 3 delta AUC is -0.1753, 95 % interval [-0.2994, -0.0421] — an interval that excludes 0.

Secondary, descriptive: Spearman(score, net) is -0.0867 for TRAINED and -0.0581 for REFERENCE. The per-row score difference TRAINED − REFERENCE has mean -4.0642 Hz, SD 2.1885, median -3.9062, range [-13.6315, 0.0404].

**An AUC near 0.5 is not evidence that no signal exists**, and nothing above is a claim about a rate in the market.

## 6. Suppression

θ = 0.911719 Hz, the stored k = 8 margin. BUY-crossing rate over the 5,168 rows valid in both branches: **TRAINED 0.00 %**, **REFERENCE 35.29 %**.

| | n | BUY rate trained | BUY rate reference | change |
|---|---|---|---|---|
| overall | 5,168 | 0.00 % | 35.29 % | -35.29 pp |
| block 1 | 1,853 | 0.00 % | 36.16 % | -36.16 pp |
| block 2 | 1,864 | 0.00 % | 33.91 % | -33.91 pp |
| block 3 | 1,451 | 0.00 % | 35.98 % | -35.98 pp |
| later outcome positive | 488 | 0.00 % | 47.95 % | -47.95 pp |
| later outcome negative | 4,525 | 0.00 % | 33.77 % | -33.77 pp |

The pre-registered reading is the **between-class difference of the trained-minus-reference change**, with the same clustered interval: the between-class difference of the trained-minus-reference change in the BUY-crossing rate is +0.1418, 95 % interval [+0.0848, +0.1950] — an interval that excludes 0. Under the registered rule that is **contextual (larger drop in the positive class)**. **A lower BUY rate alone is not learning success**, and nothing else is said in words.

One arithmetic fact belongs beside that label and is stated without interpretation: **the trained branch's BUY-crossing rate is exactly 0 in every cell** — overall, in each block and in each outcome class. When one side of a difference of differences is identically zero, the between-class contrast is the *reference* branch's own class difference with its sign flipped, and it says nothing about context sensitivity in the trained branch. The registered label is reported because it was registered; the zero is reported because it is what the numbers are.

Continuous scores over the same rows:

| branch | mean | SD | min | p25 | median | p75 | max |
|---|---|---|---|---|---|---|---|
| trained | -3.484 | 1.544 | -8.463 | -4.557 | -3.520 | -2.429 | 0.629 |
| reference | 0.580 | 1.558 | -3.439 | -0.503 | 0.373 | 1.424 | 8.872 |

Decoded actions and readout statuses over all grid rows:

* **trained** — actions `{'SELL': 4899, 'WAIT': 269, 'NO_RESPONSE': 9}`, statuses `{'VALID': 5168, 'NO_RESPONSE': 9}`
* **reference** — actions `{'SELL': 749, 'BUY': 1824, 'WAIT': 2595, 'NO_RESPONSE': 9}`, statuses `{'VALID': 5168, 'NO_RESPONSE': 9}`

## 7. Context and admission

Candidates per FROZEN tick: median 13.0, mean 12.9, range 4–23 over 402 ticks with at least one row. Zero-eligible ticks: **0** (`{}`).

**Deterministic sensory collisions**, from the encoder's rate vectors at 1e-9 Hz before any Poisson sampling, per tick: **0 of 5,177 rows** in 0 groups of equals. D10's failure mode — a round in which every presented candidate carried effectively the same vector — is measured here rather than asserted.

| feature among admitted rows | min | p25 | median | p75 | p90 | max |
|---|---|---|---|---|---|---|
| `since_last_trade` (s) | 0.000 | 4.000 | 17.000 | 37.000 | 51.000 | 60.000 |
| `trade_count_2m` | 2.000 | 4.000 | 13.000 | 41.000 | 124.000 | 988.000 |
| `gross_volume_2m` (ETH) | 0.000 | 0.080 | 0.374 | 1.347 | 4.492 | 31.419 |
| `age` (s) | 60.000 | 105.000 | 241.000 | 697.000 | 1,822.400 | 3,596.000 |

Admission verdicts over every considered (tape, tick) of the FROZEN partition:

| reason | count |
|---|---|
| `INACTIVE` | 166,236 |
| `ADMITTED` | 5,177 |
| `STATE_INVALID` | 1,944 |
| `COVERAGE` | 1,892 |
| `ROUTE_COMPLETED` | 1,892 |

## 8. The two FROZEN loop branches (paper results, descriptive)

These are the loop run over the FROZEN partition with learning off, the market rebuilt from t0 without the brain. They are **not** the primary comparison — their rows differ by construction, which is why the grid exists — and their PnL is descriptive.

| branch | ticks | episodes | settled frozen | net (ETH) | fees | holds (s) | unresolved | digest unchanged |
|---|---|---|---|---|---|---|---|---|
| frozen_trained | 402 | 0 | 0 | 0 | 0 | —–— | 0 | yes |
| frozen_reference | 402 | 6 | 6 | 0.00511362 | 0.00268236 | 900–900 | 2 | yes |

* **frozen_trained** — per-round actions `{'SELL': 263, 'WAIT': 139}`, after execution `{'NO_ORDER:SELL': 263, 'NO_ORDER:WAIT': 139}`, digest `bbca5c4ba65c…` → `bbca5c4ba65c…`
* **frozen_reference** — per-round actions `{'BUY': 144, 'SELL': 8, 'WAIT': 41}`, after execution `{'BUY': 7, 'blocked_by_fixed_hold': 8, 'HOLD:WAIT': 40, 'HOLD:BUY': 137, 'POLICY_CLOSE_FIXED_HOLD': 6, 'SETTLED_FROZEN': 6, 'NO_ORDER:WAIT': 1, 'UNRESOLVED:ROUTE_TRANSITION': 1, 'UNRESOLVED:END_OF_DATA': 1}`, digest `ba95b60503d6…` → `ba95b60503d6…`

## 9. The live hour

`LIVE_PAPER`, learning **enabled** — the declared d11-001 live branch — from the TRAINED checkpoint `bbca5c4ba65c…`, verified on disk against the digest the replay recorded. Against the same local node under the loopback ledger, with the chain-id gate and the 120-second freshness rule.

Started 2026-09-13T05:31:45Z, stopped 2026-09-13T06:31:50Z after 3,604 s: `TIME_LIMIT` 3600s wall clock. 119 ticks, 1 episodes, 1 unresolved, net -0.00220716 ETH. Requests 1,493 (2,216 units), **remote 0**. Digest `bbca5c4ba65c…` → `7fdd624083f5…`.


Reinforcement in the live hour: **1 update(s)** — 0 reward, 1 punishment, 1 clipped at the cap.

| episode | net (ETH) | return on notional | valence | normalised amount | clipped | synapses |
|---|---|---|---|---|---|---|
| 40000486 | -0.00220716 | -0.220716 | -1 | 1.0000 | yes | 3,067 |

The one `UNRESOLVED` entry is the `PENDING_CONFIRMATION` the episode carried while its exit block waited for the confirmation rule; it settled inside the hour and is not a loss, a coverage gap or a route transition.

Chain: 91,587 events, 1,060 launches seen.

**A finished run is a record of an hour that already ended, never a fly operating now.**

## 10. The five inconclusive conditions, one by one

| condition (verbatim) | measured | threshold | verdict |
|---|---|---|---|
| fewer than 20 completed LEARNING episodes | 15 completed LEARNING episodes | 20 | **FAIL** |
| fewer than 100 paired FROZEN candidate labels | 5,013 rows valid in both branches with a settled label | 100 | PASS |
| either positive or negative outcome class has fewer than 20 labeled examples | 488 positive / 4,525 negative | 20 | PASS |
| paired neural coverage below 95% | 99.83 % of 5,177 rows valid in both branches | 0.95 | PASS |
| material encoder saturation or invalid-state rate above 5% | saturation 2.820 % of (row, channel) pairs; INVALID_STATE trained 0.000 %, reference 0.000 % | 0.05 | PASS |

**1 condition(s) failed: the learning evaluation is declared INCONCLUSIVE** rather than stretching interpretation. The thresholds are not loosened after the run.

Geometric ceiling **32** beside the **15** LEARNING episodes actually produced.

## 11. What this cannot say

D11 moved admission, the sensory context and the reinforcement scale **together**. A difference between TRAINED and REFERENCE here is a difference between one brain that saw 8.4 hours of this environment and one that saw none; it can **never** be attributed to any one of the three. `d11-001` is not comparable with `d10-001`, which ran a different environment on a different window. Profit is recorded and is not the criterion: **predictive learning is not declared from PnL, and failure is not declared because the fly loses money.**

No real money, no signing, no funds. The RPC method allowlist carries no signing method and this wave added none. Every request went to `127.0.0.1`; **the remote request count is 0**.

