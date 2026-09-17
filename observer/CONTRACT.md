# The read-only presentation contract

D9(a) §8. *"Define a small presentation-event contract so another data source
can be connected later, but do not implement that future live integration
now."*

This is that contract. It is what the local observer's page consumes, and it
is the only thing it consumes. Anything that can produce these frames can
drive the watch screen; nothing that produces them is thereby allowed to
trade, learn or write.

Start it with:

    .venv/bin/python observer/serve.py          # http://localhost:8765/

---

## 1. The endpoints

| route | what it returns |
|---|---|
| `GET /` | `index.html`, the watch screen |
| `GET /static/<name>` | one file from an **exact-name allowlist** (`watch.css`, `NOTICE`). The client's string is a dictionary key, never a path component: nothing is joined, so `..` has nothing to act on |
| `GET /api/runs` | the runs, branches and partition spans on disk (D6) |
| `GET /api/summary?run=` | that wave's `summary.json`, unchanged (D6) |
| `GET /api/events?run=&branch=&partition=` | the canonical events, unchanged (D6) |
| `GET /api/artifact?run=&name=` | one committed read-only artifact: `horizon`, `context`, `probes`, `learning` (D7) |
| **`GET /api/presentation?run=&branch=`** | **D9(a): the whole branch as the frame stream below** |
| **`GET /api/detail?run=&branch=&seq=`** | **D9(a): one canonical event, the line `seq` of that log, handed over unchanged** |

Everything else is 404. The server binds to `127.0.0.1` only, defines no
`do_POST` / `do_PUT` / `do_DELETE`, and writes nothing anywhere. Run and
branch ids are validated (`[A-Za-z0-9._-]`, no separator, no `..`) and then
matched against the set discovered on disk, so an unknown id is a 404 rather
than a filesystem probe. `Content-Encoding: gzip` is used when the client
offers it.

`/api/presentation` returns HTTP 404 with `{"state": "MISSING_DATA"}` when the
run directory is absent. Both run stores are gitignored; the viewer and its
tests work with them present and absent.

---

## 2. The presentation event

`/api/presentation` returns `{"meta": {...}, "frames": [...]}`.

There is exactly **one frame per line** of `events.jsonl`, in file order.

```json
{"seq": 88,
 "ts": 1783347240,
 "kind": "LEARNING",
 "ev":  { ...this event's display payload... },
 "at":  { ...the state after this event... }}
```

* **`seq`** — the line index in `events.jsonl`, and the index of the frame in
  `frames`. This is the tie-break §5 asks for: when two events share a
  timestamp, file order decides, always. It is also the identity
  `/api/detail?seq=` takes.
* **`ts`** — this event's own **market** timestamp (`market_ts`, else
  `cutoff_ts`, else `ts` on `EXECUTION`/`OUTCOME`), in epoch seconds. Absent
  when the event carries none. The journal's `t` — the wall clock of the
  machine that ran the experiment — is never used as market time.
* **`kind`** — one of the ten canonical `EventType` values, or `TORN` for a
  line that is not JSON (an append-only log can end mid-write).

### The absence rule

**A key absent from `ev` or `at` means the canonical field was absent or
null.** The page renders it as *unavailable*, never as zero. This is the only
way the projection reports missing optional telemetry, and it is what keeps
the stream inside its payload budget.

### `at` — the state after events `0..seq`

| key | meaning |
|---|---|
| `ts` | the market frontier: the last market timestamp seen. Omitted when it equals the frame's own `ts` |
| `p` | index into `meta.partition_table` — the partition, its branch, its `learning` flag, and whether it has closed |
| `decision`, `round` | `seq` of the last `DECISION` / `ROUND` |
| `position` | `seq` of the `EXECUTION` whose position is still open; absent when flat |
| `held` | distinct recorded market minutes since that fill |
| `horizon_left` | `H − held`, floored at 0; absent when the run records no `H` |
| `outcome` | `seq` of the last settled `OUTCOME` |
| `learning` | `seq` of the `LEARNING` event that settled it — **absent at the outcome's own frame**, because that event has not been written yet, and absent for ever under `SETTLED_FROZEN` |
| `settlement` | the last outcome's `settlement` field, e.g. `SETTLED_FROZEN` |
| `c` | the cumulative counters, as a list in `meta.counters` order |

`at` is produced by one forward pass and never looks ahead. `at` at index `N`
equals the projection of events `0..N` — a pytest case
(`test_no_frame_carries_anything_from_a_later_event`) asserts exactly that for
every prefix. Seeking backwards is therefore an array index, not a re-fold,
and double counting is structurally impossible.

"This round produced no decision" is settled by the event that *follows* the
round, never by looking ahead from the round itself.

---

## 3. Which canonical field feeds which visual

Source of truth: `flytrade/records.py` — `record_round` (462), `record_decision`
(483), `record_round_aborted`, `open_episode` (537), `settle` (556),
`settle_frozen` (594), `record_warmup`.

### Mode strip (§2A)

| display | canonical field |
|---|---|
| source: HISTORICAL REPLAY / SYNTHETIC FIXTURE | `DECISION.dataset_label` (`meta.dataset_label`) |
| PAPER | fixed label — this system has no other execution mode |
| phase · branch · learning on/off | `PARTITION.partition`, `.branch`, `.learning` via `meta.partition_table` |
| market timestamp | `frame.ts` / `at.ts` |
| playback state and speed | the page's own cursor and timer — never a recorded field |
| run · branch | the selected ids, and `meta.provenance.run_id` |

### Context and senses (§2B)

| display | canonical field |
|---|---|
| instrument | `DECISION.symbol` |
| observation status | `DECISION.observation_status`, else `ROUND.candidates[].status` |
| bar close | `DECISION.observation.close` |
| candidates this round | `ROUND.candidates` length |
| the five feature bars | `DECISION.observation.normalized`, in `meta.features` order (`r1, r5, r20, rv20, relvol`) |
| the glomerulus bars | `DECISION.stimulus.rates_hz`, in `meta.channels` order |
| total ORN drive · driven ORNs | `DECISION.stimulus.total_drive_hz` · `.n_orns` |

### The fly and the neural response (§2C)

| display | canonical field |
|---|---|
| glomerulus marks in the figure | `DECISION.stimulus.rates_hz` |
| Kenyon-cell block | `DECISION.readout.kc_fraction` as a **proportion of the block**, labelled as a proportion and not as identified cells; the count is `readout.kc_active` |
| approach / avoid discs and numbers | `DECISION.readout.rates_hz.approach` / `.avoid` (population sizes from `readout.population_sizes`) |
| decoder box | `DECISION.valence_hz` |
| dashed plasticity overlay | drawn **only** on a frame whose own event is a `LEARNING` record with `accepted = true`; the caption is `LEARNING.valence` and `LEARNING.synapses_depressed` |
| peak read rate | `DECISION.readout.max_rate_hz` |
| presentations (k) · silent replicates | `DECISION.readout.k` · `.silent_replicates` |
| the eight replicate marks | `DECISION.replicate_statuses` and `.replicate_scores`, presented as a **completed measurement**. The log holds no per-replicate timing, so none is animated |

### Decision (§2D, §4)

| display | canonical field |
|---|---|
| the action | `DECISION.decoded_action` |
| readout status | `DECISION.readout_status` — `VALID`, `NO_RESPONSE`, `INVALID_STATE`, `POLICY_REJECT` stay four different things |
| V, ±θ, the gauge | `DECISION.valence_hz`, `.theta_hz` |
| "SELL signal · no position open" | `decoded_action == SELL` **and** `at.position` absent |
| "execution policy refused this BUY" | `readout_status == POLICY_REJECT`, with `DECISION.rejection.reason` named after it when the log carries one (`ev.reject_reason`) |
| "SELL signal · blocked by fixed-hold policy" | `readout_status == POLICY_REJECT` **and** `ev.reject_reason == FIXED_HOLD` (D9(b)). The decoder did emit SELL; under that exit policy nothing was sold and nothing was reinforced |
| "no response — nothing was decoded" | `readout_status == NO_RESPONSE` |
| "invalid readout — outside the operating range" | `readout_status == INVALID_STATE` |

### Position (§2D)

| display | canonical field |
|---|---|
| state, instrument, quantity, entry fee | `EXECUTION.side`, `.symbol`, `.quantity`, `.fee` |
| entry fill | `EXECUTION.fill_price` at `EXECUTION.market_ts` |
| fill timing | `EXECUTION.flag` and `.delay_minutes` (e.g. `DELAYED_FILL`) |
| market minutes held | `at.held` — distinct recorded market minutes since the fill |
| remaining maximum policy horizon | `at.horizon_left` against `meta.horizon_minutes`, whose source is `meta.horizon_source`: `summary.selected_horizon_minutes` (D7: H = 90) or `summary.config.execution.horizon_minutes` (D5/D6: H = 8). **Unavailable** when neither exists, and then no countdown is drawn |

### Result and memory (§2E, §4, §5)

| display | canonical field |
|---|---|
| closed by | `OUTCOME.close_reason` — `NEURAL_SELL` and `POLICY_CLOSE` are different events and are never merged. `POLICY_CLOSE_FIXED_HOLD` (D9(b)) is the horizon expiry under the fixed-hold exit policy: a timer, counted with `POLICY_CLOSE` in `at.c`, and shown under its own name |
| held | `OUTCOME.market_minutes_held` |
| gross (reference prices) | `OUTCOME.gross_reference_pnl` |
| − modelled slippage | `OUTCOME.slippage` |
| − fees | `OUTCOME.fees` |
| = net realised | `OUTCOME.net_pnl` |
| fill timing | `OUTCOME.exit_flag` |
| settlement | `OUTCOME.settlement` |
| "result — learning frozen" | `OUTCOME.settlement == "SETTLED_FROZEN"` — **the marker `settle_frozen` writes**, never the branch name |
| dopamine | `LEARNING.valence` (+1 PAM, −1 PPL1) and `.amount` |
| synapses depressed | `LEARNING.synapses_depressed` |
| learning event | `LEARNING.accepted` and `.reason` — a refused update shows its reason and a zero change |
| cash, equity, fees paid, slippage paid, trades | `OUTCOME.account.cash` / `.equity` / `.fees_paid` / `.slippage_paid` / `.trades` |
| cumulative realised PnL | `OUTCOME.cumulative_realized_pnl` |

**There is no second PnL engine.** Every money figure above is a field of the
`OUTCOME` event the cursor has reached, copied. The page adds nothing up and
carries nothing forward. **Unrealised result and marked equity between
settlements were never recorded and cannot be reconstructed from the log; they
are shown as unavailable, not estimated.** No starting balance is invented:
`account.initial_cash` is the run's own field or nothing.

### Counters

`at.c`, in `meta.counters` order: `rounds`, `rounds_no_decision`, `decisions`,
`buy`, `sell`, `wait`, `no_response`, `invalid_state`, `policy_reject`,
`executions`, `outcomes`, `neural_sell`, `policy_close`, `learning`,
`settled_frozen`, `aborted`, `warmup`. A `POLICY_REJECT` decision is counted as
a rejection and **not** as a decoded BUY.

### Detail panel (§7)

`/api/detail` returns the canonical event unchanged, which is where the large
arrays live: `observation.raw`, `versions`, `checkpoint_digest`,
`decision_digest`, `replicate_scores`, `depressed_per_replicate`. The panel
also lists the linked decision / fill / outcome / learning lines, taken from
the `at` pointers, so nothing later than the cursor is ever listed.

### Experiment record (§7)

Behind an explicit action, never in watch mode: D7's and D8's accepted
wording, and the committed artifacts `registered-horizon-artifact`, `withheld-probe-table`,
`context_summary.json` served by `/api/artifact` and displayed unchanged. A
probe's label stays sealed until the replay passes the minute its exit price
printed; the context summary stays sealed until the cursor reaches the end of
the branch.

---

## 4. The states the page distinguishes

| state | when |
|---|---|
| **loading** | the presentation stream has been requested and has not arrived |
| **playing · N events/s** | the timer is advancing the cursor |
| **paused** | it is not |
| **completed** | the cursor is at the last frame. *A completed replay is not an outage* |
| **missing data** | no event log for this run and branch on this machine (the run stores are not committed) |
| **disconnected** | the fetch failed; the error is displayed and the stream is empty |
| **skipped interval** | a jump moved the cursor past events: how many, and how many market minutes passed with no event of that kind |

---

## 5. What a future source would have to provide

To drive this screen from something other than a committed run directory,
implement `/api/presentation` and `/api/detail` with the shapes above. Nothing
else is needed, and nothing else is permitted: the page holds no credentials,
sends no request but `GET`, and has no code path that can place an order,
change a weight or write a file. **That future integration is not implemented
here** and D9(a) does not authorise it.
