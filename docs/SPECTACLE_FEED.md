# The spectacle feed — the contract

**This file is the contract.** GPT/Astra read `data/pons/live/` and nothing
else, and what follows describes every key of both files it contains. It is
written for a reader who has not read the repository: everything a spectacle
needs is here, and everything here is written by
[`flytrade/product/feed.py`](../flytrade/product/feed.py) out of what
[`flytrade/product/live.py`](../flytrade/product/live.py) and the Pons loop
computed. `docs/SPEC.md` P1 addendum 4 is the requirement this answers.

## 0. What the feed is, and what it is not

A frozen fly brain — `brains/trader-v1`, the clean reference checkpoint of the
D11/D12 experiments, digest `ba95b605…`, every plastic KC→MBON gain at 1.0 —
looks at the memecoins launched on PONS v2 (Robinhood Chain, chain id 4663)
every thirty seconds, picks one, and buys and sells it **on paper**.

* **Live data, paper execution.** No transaction is signed, broadcast or sent.
  The package that talks to the chain has a six-method read-only allowlist and
  no key material anywhere. A paper position never moved the real market.
* **The brain does not learn here.** Learning is `FROZEN`. Every settled
  episode is scored REWARD / PUNISHMENT / NEUTRAL by the existing
  reinforcement rule and written as a `CREDIT` event **with `applied: false`** —
  the number is for the show, and no weight moves. The event carries the
  brain's digest before and after the settlement and they are the same.
  (Why: the science says the trained fly stopped trading. `the session log`
  2026-09-13 (m).)
* **Nothing here is a prediction, a result or a measurement of skill.** PnL is
  descriptive. A win is not evidence and a loss is not evidence.
* **No endpoint, no key, no PII** is in either file, ever. Error details are
  masked to `<rpc-endpoint>` before they are written.

## 1. The two files

| path | what it is |
|---|---|
| `data/pons/live/events-YYYY-MM-DD.jsonl` | append-only, one JSON object per line, one file per **UTC** day. Never rewritten, never deleted, never committed. |
| `data/pons/live/state.json` | the current picture, rewritten **atomically** (write-temp-rename-fsync) after **every** event. A reader always sees a whole document. |

Everything else in that directory is the loop's own machinery — `journal/`
(the audit log, the checkpoint, the pending episode), `chain/` (the raw logs,
the normalised events, the cursor), `rpc_ledger.json`, `worker.pid`, `stop`,
`worker.log`, `summary.json`. **A spectacle does not need to read any of
them**; they are the durable state a restart is rebuilt from.

## 2. The event stream

Every line has the same head, then the fields of its kind:

| key | meaning |
|---|---|
| `seq` | strictly increasing, from 1, and it carries on across a restart |
| `ts` / `utc` | wall clock when the line was written (epoch seconds / ISO-8601 Z) |
| `kind` | one of the nine below |
| `run_id` | `pons-live` |
| `venue` / `chain_id` | `PONS` / `4663` |
| `mode` / `learning` | `LIVE_PAPER` / `FROZEN` |
| `data` / `execution` | `LIVE` / `PAPER` |
| `tick` | the loop's tick number; monotone across restarts |
| `cutoff_ts` | the chain second the decision was taken at — the timestamp of the newest block the tick had read. **This, not `ts`, is market time.** |

### `SNIFF` — one per tick, never one per candidate

What the fly smelled this tick and what admission said about each of them.

| key | meaning |
|---|---|
| `tracked` | tapes the loop is following |
| `considered` | tokens admission looked at this tick |
| `admitted` | how many passed |
| `rejected` | how many did not |
| `presented` | the tokens that reached the brain this tick (at most 6, round-robin) |
| `rotated` | admitted but not presented, because the round-robin gave the slot to someone else |
| `reasons` | `{reason: count}` over the rejected — **the whole tick, never truncated** |
| `candidates` | `[{token, admitted, reasons}]`, ordered presented → admitted → rejected and cut at 250 rows |
| `candidates_listed` / `candidates_truncated` | how many rows are in the list and how many were cut |
| `holding` | `true` on a tick where a position is open: the loop observes what it holds and sniffs no new candidate |
| `held_token` / `tape_missing` | on a holding tick: which token, and whether its tape has not been rebuilt yet after a restart |

The rejection reasons are `admission_v2`'s own: `INACTIVE` (fewer than 2 valid
trades in the last 120 s, or the last one more than 60 s ago),
`INSUFFICIENT_HISTORY` (younger than 60 s), `STATE_INVALID`, `ROUTE_COMPLETED`
(the curve graduated), `CURVE_EXHAUSTED`, `QUOTE_UNSUPPORTED`,
`DEPLOYMENT_UNSUPPORTED`, `COLLECTOR_LAG`, `ROTATED`.

### `PICK` — the fly chose, and this is its brain at that instant

| key | meaning |
|---|---|
| `token` / `curve` / `stable_id` / `episode_id` | who was picked |
| `context` | `FLAT` (a pick among candidates) or `HELD` (the token it already holds, re-observed) |
| `action` | `BUY`, `SELL` or `WAIT`, decoded |
| `readout_status` | `VALID`, `NO_RESPONSE`, `INVALID_STATE` or `POLICY_REJECT` |
| `rejection` | why the execution policy refused a decoded action, or `null` |
| `valence_hz` | approach − avoid, centred. **The fly's opinion, in hertz** |
| `approach_hz` / `avoid_hz` / `theta_hz` | the two MBON populations and the decision threshold |
| `mbon_rates_hz` / `population_sizes` | mean firing rate per readout population, and how many neurons are in each |
| `kc_active` / `kc_fraction` | Kenyon cells that fired, and their fraction |
| `k` / `replicate_scores` / `silent_replicates` | the 8 presentations behind the aggregate, their individual scores, and how many were silent |
| `n_candidates` | how many were in the round |
| `age_s` / `marginal_price` / `last_trade_price` | the token at that instant |
| `admission_reasons` | empty when it was admitted outright |
| `brain_digest` | the learned state that decided. It never changes |

### `OPEN` — a paper position was taken

`token`, `curve`, `episode_id`, `entry_block`, `entry_ts`, `entry_fill_price`
(ETH per token, unrounded), `entry_reference_price` (before our own impact),
`quantity` (tokens), `tokens_out_wei` (the exact integer the curve handed
over), `fee_eth` (curve fee + creator tax + gas), `horizon_ts` (when it will be
closed) and `size_eth` (0.01, fixed).

### `MARK` — what the open position would fetch right now

`token`, `episode_id`, `available`, `block_number`, `mark_value_eth`,
`cost_eth`, `unrealised_eth`, `marginal_price`, and `reason`/`detail` when the
position could not be quoted. **A mark is a mark**: it is displayed and it
never reaches reinforcement.

### `CLOSE` — the horizon expired and the position was settled

`episode_id`, `token`, `curve`, `entry_*` and `exit_*` (block, ts, fill price
and reference price — the price before our own impact), `quantity`,
`gross_pnl_eth`, `gross_reference_pnl_eth`, `slippage_eth`,
`fees_eth`, `net_pnl_eth`, `return_on_notional`, `seconds_held`,
`close_reason` (always `POLICY_CLOSE_FIXED_HOLD`: a timer, not a decision),
`confirmation` (the entry and exit blocks' confirmation state) and
`settlement` (`SETTLED_FROZEN`). A position whose blocks are not confirmed yet
is **not** closed and produces no `CLOSE`; it stays open and is retried.

### `CREDIT` — REWARD / PUNISHMENT / NEUTRAL, recorded and never applied

| key | meaning |
|---|---|
| `label` | `REWARD`, `PUNISHMENT` or `NEUTRAL` |
| `valence` / `amount` | +1 / −1 / 0 and the normalised magnitude |
| `rule` | `absolute_profit_v1` — the existing rule, unchanged |
| `reinforce_full_scale` / `reinforce_cap` / `clipped` | the scale it was divided by, the cap, and whether it hit it |
| `net_pnl_eth` / `return_on_notional` | the money the label came from |
| `applied` | **always `false`** |
| `brain_digest_before` / `brain_digest_after` | equal, always. The loop raises and stops if they ever differ |

### `HEARTBEAT` — one per tick, whatever else happened

`uptime_s`, `requests` (see §3), `account`, `position`, `head_block`,
`cursor_block`, `cutoff_age_s`, `tracked`, `launches_seen`, `reorgs`,
`errors`, `throttled`, `episodes`, `unresolved`, `pending_confirmation`,
`brain_digest`, `rss_mib`.

### `THROTTLED` — the hourly request cap was reached; the loop waits

`reason` (`HOURLY_REQUEST_CAP`), `spent_in_window`, `cap`, `reserve`,
`window_s`, `resume_at` / `resume_utc`. **It is not a stop**: the loop waits
for the rolling window to free and carries on.

### `RPC_ERROR` — an endpoint failure, counted

`code`, `detail` (masked), `method`, `attempt`, `backoff_s`, `retried`,
`errors`. Transient failures are retried with exponential backoff from 1 s to
60 s and the loop survives them; the four codes a retry cannot cure are raised
instead.

## 3. `state.json`

| key | meaning |
|---|---|
| `version` | `pons-live-state-1` |
| `run_id`, `venue`, `chain_id`, `mode`, `learning`, `data`, `execution` | the same stamp every event carries |
| `updated_epoch` / `updated_utc` | when this file was last written |
| `day_file` | the name of today's event file |
| `seq` | the sequence number of the last event written |
| `kinds` | `{kind: count}` since the feed began, across restarts |
| `brain` | `artifact`, `digest`, `graph_sha256`, `input_schema_sha256`, `plastic_synapses`, `learning`, `asserted_at_start`, `credit_recorded_never_applied` |
| `account` | `initial_cash_eth`, `cash_eth`/`cash_wei`, `realized_pnl_eth`/`realized_pnl_wei`, `unrealised_eth`/`unrealised_wei`, `equity_eth`, `fees_paid_eth`, `slippage_paid_eth`, `trades`, `size_eth`, `wei_rendering` |
| `position` | `null` when flat; otherwise `token`, `curve`, `episode_id`, `stable_id`, `entry_ts`, `entry_block`, `entry_price_eth_per_token`, `entry_reference_price`, `size_eth`, `quantity_tokens`, `tokens_wei`, `cost_eth`, `entry_fee_eth`, `age_s`, `horizon_ts`, `seconds_to_horizon`, `last_mark`, `unrealised_eth`/`unrealised_wei`, `pending_confirmation`, `never_closed_at_a_restart` |
| `last_pick` | the last `PICK` event, whole — the brain snapshot the show draws |
| `events` | the last 200 events, oldest first, each exactly as the day file has it — with one exception: a `SNIFF`'s `candidates` row list is replaced by `[]` plus `candidates_in_the_day_file`, because two hundred of those is half a megabyte rewritten ten times a tick. The counts and the reason histogram stay; the rows are one line away, in the day file |
| `episodes` | the last 100 closed episodes: `episode_id`, `token`, `entry_ts`, `exit_ts`, `entry_block`, `exit_block`, `seconds_held`, `gross_pnl_eth`, `fees_eth`, `slippage_eth`, `net_pnl_eth`/`net_pnl_wei`, `return_on_notional`, `close_reason`, `settlement`, and `credit` (`label`, `valence`, `amount`, `applied: false`) |
| `biggest_win` / `biggest_loss` | the extreme episodes, in the same shape, or `null` |
| `rejected` | `{session: {reason: n}, last_hour: {reason: n}}` |
| `sniffed` | `ticks`, `candidates`, `admitted`, `rejected`, `picked`, `last_tick` |
| `credits` | `{REWARD, PUNISHMENT, NEUTRAL}` counts |
| `requests` | `hour`, `hour_cap`, `hour_remaining`, `window_s`, `this_process`, `total_attempts`, `total_units`, `by_method`, `backfill` |
| `health` | `started_epoch`/`started_utc`, `uptime_s`, `ticks_this_process`, `tick`, `last_cutoff_ts`, `cutoff_age_s`, `head_block`, `cursor_block`, `lag_blocks`, `tracked_curves`, `launches_seen`, `throttled`, `throttle_events`, `throttled_seconds`, `reorgs`, `errors`, `retries`, `last_error`, `tape_missing_ticks`, `brain_digest`, `learning`, `stop`, `ledger_halted` |
| `restore` | what the **next process** reads to be this one: the tick, the last cutoff, the account, the open position with its own reserve delta and horizon, the pending confirmation, the counters and the rolling request window. A spectacle can ignore it |

Money is reported as the account's own ETH float **and** a wei rendering of it
(`round(eth * 1e18)`). The rendering is derived; the exact integers of a fill
are in the journal's `OUTCOME` record.

## 4. One real tick, from the proof run

`2026-09-13`, tick 2 of `pons-live`. Four lines of
`events-2026-09-13.jsonl`, whole, and the fields of the `SNIFF` census
abbreviated where the file lists 250 rows.

```json
{"seq": 5, "ts": 1789336208, "utc": "2026-09-13T21:50:08Z", "kind": "SNIFF", "run_id": "pons-live", "venue": "PONS", "chain_id": 4663, "mode": "LIVE_PAPER", "learning": "FROZEN", "data": "LIVE", "execution": "PAPER", "tick": 2, "cutoff_ts": 1789336200, "tracked": 741, "considered": 0, "admitted": 0, "presented": [], "rotated": 0, "rejected": 0, "reasons": {}, "candidates": [], "holding": true, "held_token": "0x040cc8dd000cd518022e2e0ac42c1f8fa791f5d6", "tape_missing": false, "note": "a position is open: the loop observes the token it holds and sniffs no new candidate"}
{"seq": 6, "ts": 1789336208, "utc": "2026-09-13T21:50:08Z", "kind": "MARK", "tick": 2, "cutoff_ts": 1789336200, "token": "0x040cc8dd000cd518022e2e0ac42c1f8fa791f5d6", "episode_id": 1000583, "available": true, "reason": null, "detail": null, "block_number": 62288694, "mark_value_eth": 0.00976335156624, "cost_eth": 0.010026513686360001, "unrealised_eth": -0.00026316212012000156, "marginal_price": 2.5212577265182897e-09}
{"seq": 7, "ts": 1789336209, "utc": "2026-09-13T21:50:09Z", "kind": "PICK", "tick": 2, "cutoff_ts": 1789336200, "context": "HELD", "token": "0x040cc8dd000cd518022e2e0ac42c1f8fa791f5d6", "curve": "0x71a9fc2fbb421ce8354c4992cb3cab54bed17b12", "stable_id": 583, "episode_id": 2000583, "action": "WAIT", "readout_status": "VALID", "rejection": null, "valence_hz": 0.170898, "approach_hz": 17.5, "avoid_hz": 18.240517, "theta_hz": 0.911719, "mbon_rates_hz": {"avoid": 18.240517, "approach": 17.5}, "population_sizes": {"avoid": 29, "approach": 16}, "kc_active": 261, "kc_fraction": 0.136623, "k": 8, "replicate_scores": [-0.916935, 1.010776, -2.166935, 4.083345, 0.833065, 0.833065, 1.010776, 2.010776], "silent_replicates": 0, "n_candidates": 1, "age_s": 58, "marginal_price": 2.5212577265182897e-09, "last_trade_price": 2.521257726518289e-09, "admission_reasons": [], "brain_digest": "ba95b60503d658e989b649ecd3994264791fbead92f0bdacfd555e5d86ab61f5"}
{"seq": 8, "ts": 1789336209, "utc": "2026-09-13T21:50:09Z", "kind": "HEARTBEAT", "tick": 2, "cutoff_ts": 1789336200, "uptime_s": 442, "requests": {"hour": 79, "hour_cap": 3000, "hour_remaining": 2861, "window_s": 3600, "this_process": 620, "total_attempts": 620, "total_units": 1224, "by_method": {"eth_chainId": {"attempts": 1, "units": 1, "errors": 0}, "eth_getBlockByNumber": {"attempts": 405, "units": 803, "errors": 0}, "eth_getLogs": {"attempts": 211, "units": 414, "errors": 0}, "eth_call": {"attempts": 3, "units": 6, "errors": 0}}, "backfill": {"requests": 536, "events": 37910, "wall_s": 353.5, "first_block": 62248783, "last_block": 62284427, "resumed_from_cursor": false}}, "account": {"initial_cash_eth": 10.0, "cash_eth": 9.98997348631364, "cash_wei": "9989973486313639936", "realized_pnl_eth": 0.0, "realized_pnl_wei": "0", "unrealised_eth": -0.00026316212012000156, "unrealised_wei": "-263162120120001", "equity_eth": 9.999736837879879, "fees_paid_eth": 0.00012651368636, "slippage_paid_eth": 0.0, "trades": 0, "size_eth": 0.01}, "position": {"token": "0x040cc8dd000cd518022e2e0ac42c1f8fa791f5d6", "episode_id": 1000583, "entry_ts": 1789336142, "entry_block": 62288101, "entry_price_eth_per_token": 2.5091297268948275e-09, "quantity_tokens": 3945591.132209709, "age_s": 58, "horizon_ts": 1789337042, "seconds_to_horizon": 842, "unrealised_eth": -0.00026316212012000156}, "head_block": 62288694, "cursor_block": 62288694, "cutoff_age_s": 8, "tracked": 741, "launches_seen": 883, "reorgs": 0, "errors": 0, "throttled": false, "episodes": 0, "unresolved": 0, "pending_confirmation": null, "brain_digest": "ba95b60503d658e989b649ecd3994264791fbead92f0bdacfd555e5d86ab61f5", "rss_mib": 656.6}
```

The first `SNIFF` of that same run, at tick 1, is the other shape — the fly
flat and smelling everything:

```json
{"seq": 1, "ts": 1789336196, "utc": "2026-09-13T21:49:56Z", "kind": "SNIFF", "tick": 1, "cutoff_ts": 1789336140, "tracked": 735, "considered": 636, "admitted": 19, "presented": ["0x53366269f4031eeb0a82ee938b610fc30ab59143", "0xfeb2f46ba853d23ef7c2e16676406246156530b8", "0x5c15c4d8d92c2987ddd2ff06c0b0aa1545730cc5", "0x8bef6dd283d4bf487e6de5668caaaa6f8b46d190", "0x040cc8dd000cd518022e2e0ac42c1f8fa791f5d6", "0xace7a4cc1bac9031a4952095e9082edcff0dcc50"], "rotated": 13, "rejected": 617, "reasons": {"INACTIVE": 617, "ROUTE_COMPLETED": 6, "STATE_INVALID": 6}, "candidates": [{"token": "0x53366269f4031eeb0a82ee938b610fc30ab59143", "admitted": true, "reasons": []}, "… 249 more rows, presented first, then admitted, then rejected …"], "candidates_listed": 250, "candidates_truncated": 386, "holding": false}
```

And the end of an episode — the position opened by the process that
was signalled, settled by the one that replaced it, and the reinforcement
the absolute rule computed for it and **nobody applied**:

```json
{"seq": 370, "ts": 1789339237, "utc": "2026-09-13T22:40:37Z", "kind": "CLOSE", "run_id": "pons-live", "venue": "PONS", "chain_id": 4663, "mode": "LIVE_PAPER", "learning": "FROZEN", "data": "LIVE", "execution": "PAPER", "tick": 102, "episode_id": 52000955, "token": "0x373a0dd32be418a8bdb33963ca45565b0ca844de", "curve": "0xf3620405a9653f8e0cf6bd11c1c2698e0259c87e", "cutoff_ts": 1789338602, "entry_block": 62303486, "entry_ts": 1789337702, "entry_fill_price": 1.720099428684231e-09, "entry_reference_price": 1.7101111024875554e-09, "exit_block": 62312329, "exit_ts": 1789338602, "exit_fill_price": 1.7200994286842305e-09, "exit_reference_price": 1.7301460941666206e-09, "quantity": 5755481.244228356, "gross_pnl_eth": -2.3804112505691365e-18, "gross_reference_pnl_eth": 0.0001153110188371313, "slippage_eth": 0.00011531101883713367, "fees_eth": 0.000263162120119999, "net_pnl_eth": -0.0002631621201200014, "return_on_notional": -0.02631621201200014, "seconds_held": 900, "close_reason": "POLICY_CLOSE_FIXED_HOLD", "confirmation": {"entry": {"block_number": 62303486, "confirmed": true, "head": 62318504, "safe_block": 62314306, "confirm_depth": 594, "anchor": 62303467, "anchor_hash_matches": true}, "exit": {"block_number": 62312329, "confirmed": true, "head": 62318504, "safe_block": 62314306, "confirm_depth": 594, "anchor": 62312309, "anchor_hash_matches": true}}, "settlement": "SETTLED_FROZEN", "account": {"cash": 10.00093159, "initial_cash": 10.0, "realized_pnl": 0.00093159, "fees_paid": 0.00054105, "slippage_paid": 0.00022188, "equity": 10.00093159, "trades": 2, "position": null}}
{"seq": 371, "ts": 1789339237, "utc": "2026-09-13T22:40:37Z", "kind": "CREDIT", "run_id": "pons-live", "venue": "PONS", "chain_id": 4663, "mode": "LIVE_PAPER", "learning": "FROZEN", "data": "LIVE", "execution": "PAPER", "tick": 102, "cutoff_ts": 1789339230, "episode_id": 52000955, "token": "0x373a0dd32be418a8bdb33963ca45565b0ca844de", "label": "PUNISHMENT", "valence": -1, "amount": 0.20083740503800904, "rule": "absolute_profit_v1", "reinforce_full_scale": 0.131032424, "reinforce_cap": 1.0, "clipped": false, "net_pnl_eth": -0.0002631621201200014, "return_on_notional": -0.02631621201200014, "applied": false, "brain_digest_before": "ba95b60503d658e989b649ecd3994264791fbead92f0bdacfd555e5d86ab61f5", "brain_digest_after": "ba95b60503d658e989b649ecd3994264791fbead92f0bdacfd555e5d86ab61f5", "note": "recorded, never applied: the product brain is frozen and its digest is asserted unchanged across this settlement"}
```

## 5. Reading it, in one paragraph

Follow the day file. `SNIFF` is the fly smelling the market — show
`considered`, `admitted`, `rejected` and the reasons. `PICK` is the fly
choosing, and it is the only place the brain is visible: `valence_hz` is its
opinion, `mbon_rates_hz` the two output populations, `kc_active` how much of
the mushroom body lit up, `replicate_scores` the eight tries behind the
average. `OPEN`, `MARK` and `CLOSE` are the position and the money;
`CREDIT` is the REWARD or PUNISHMENT it *would* have learned from, and never
did. `HEARTBEAT` is the pulse. For a page that renders "now", read
`state.json` alone: it has the account, the position, the last pick, the last
200 events, the closed episodes with their credit labels, the biggest win and
the biggest loss, the rejection census and the health of the loop.

## 6. Operating it

```
the live-loop launcher start | stop | status | tail
the user service start|stop|status flytrade-pons
the service log -u flytrade-pons -f
```

The loop has no wall-clock stop. It stops on the stop file, on
`SIGTERM`/`SIGINT`, or on an invariant violation (the brain's digest is not the
registered one, or the chain is not 4663). It survives a restart: the brain is
reloaded and its digest asserted, and the account, the open position, the
pending confirmation, the last cutoff, the tick counter and the rolling
request window come back from `state.json`. **A position open across a restart
stays open and is never closed at a restart mark.**
