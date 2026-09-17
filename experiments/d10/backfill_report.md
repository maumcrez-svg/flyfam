# D10 — the bounded genuine backfill, `d10-backfill-v1`

Reviewer decision 1 after dispatch 1 (docs/SPEC.md). The donor dataset
`d10-replay-v1` covers roughly the first 62 seconds of each token, so a
fifteen-minute horizon admits nothing on it. This is the new collection the
replay run of addendum 14 uses. Everything below is measured; nothing in this
file is a fixture.

## 1. The window, and why it is this window

| item | value |
|---|---|
| rule | the 135 minutes of blocks **ending at the `safe` block recorded by `verification.json`** |
| safe block | 60,801,426 (`0x397677bd42b3…`) |
| first block | 60,721,229 |
| last block | 60,801,426 |
| blocks | **80,198** |
| measured block interval | 0.101 s (`finality.json`, dispatch 1) |
| admission window | first 120 minutes → block 60,792,515 |
| settlement tail | last 15 minutes, for a position opened at the end of minute 120 |
| chain | Robinhood Chain, id 4663 |

The window is fixed by the rule and by the two numbers dispatch 1 recorded. No
property of the data inside it entered the choice.

## 2. What was collected

| item | value |
|---|---|
| raw logs | 62,338 |
| normalised events | 62,338 |
| grid headers | 804 |
| launches (`TokenLaunched`) | **991** |
| native-ETH launches, followed | **672** |
| launches on another quote, recorded `QUOTE_UNSUPPORTED`, not followed | **319** |
| `CurveCompleted` | **7** |
| curves with a derived initial state | 614 |
| curves with a read initial state (one `eth_call` each) | 3 |
| curves left without a state (no trade to pin the tax) | 55 |

Events by kind:

| kind | n |
|---|---|
| `CurveBuy` | 27,165 |
| `CurveSell` | 24,906 |
| `SnipeTaxExempted` | 4,819 |
| `FeesSwept` | 2,029 |
| `SnipeTaxCharged` | 1,527 |
| `TokenLaunched` | 991 |
| `Initialized` | 672 |
| `CreatorFeeRecipientUpdated` | 145 |
| `GraduationTokensPermanentlyLocked` | 23 |
| `LaunchSwept` | 23 |
| `PoolGraduated` | 23 |
| `CurveCompleted` | 7 |
| `CurveBuyRefunded` | 7 |
| `BuybackLocked` | 1 |

The measured launch rate over the window is 991 / 135 min = **440 per hour**,
beside dispatch 1's 523 per hour over five minutes and beside the v2
documentation's "public launches are closed, so only whitelisted addresses can
create a token for now". Both are measurements of what the factory did; neither
is a statement about who may call it.

**Coverage.** Every followed curve is covered from its launch block to the end
of the window or to its `CurveCompleted`, whichever comes first. A launch in
the last 15 minutes has a tape but can never be admitted, because admission
requires `cutoff + latency + 900 s` to lie inside its coverage. That is the
purpose of the settlement tail.

## 3. What it cost

| method | attempts | units (archive-weighted) | errors |
|---|---|---|---|
| `eth_getBlockByNumber` | 812 | 1,623 | 1 |
| `eth_getLogs` | 343 | 685 | 0 |
| `eth_call` | 3 | 6 | 0 |
| **total for `d10-backfill`** | **1,158** | **2,314** | **1** |

Cap for this collection: **3,000**. Not reached; the dataset ends at the end of
the window, not at the cap. Chainstack bills a read 127 or more blocks behind
the tip at two units, and every read here was, so units are almost exactly twice
attempts.

**Range retreats: none.** No `RPC_RANGE_TOO_LARGE` was returned at 1,000 blocks
for the factory filter or 500 for the tracked-curve filter, so the halving path
was never entered on the wire (it is exercised against a scripted endpoint in
`tests/d10/test_collector.py`).

**One error, and what it did.** A single `RPC_TRANSPORT_FAILED` on an
`eth_getBlockByNumber` ended the first pass at block 60,768,228. There is no
retry anywhere in this package, so the process stopped with the cursor, the
events and the ledger on disk; a second process resumed from that cursor and
finished the window. That is the durable cursor doing its job, and it is
reported rather than hidden. **No quota halt occurred** and the ledger is not
halted.

## 4. HTTP against the WSS equivalent

| route | billed requests for this window |
|---|---|
| what this collection actually spent (HTTP polling) | **1,158** |
| a `logs` + `newHeads` subscription would have been billed | **142,538** |

Computed from the endpoint's own charging model
(docs.chainstack.com/docs/request-units, verified 2026-09-12): "Setting up the
subscription counts as one request — and then each push notification the node
sends to you counts as one more request." Two subscriptions, plus 62,338 log
pushes, plus 80,198 header pushes. The owner's caution was right: swapping
polling for WebSocket and calling it cheap would have cost **123 times** as
much on this window.

The header grid is what made the HTTP side small. Without it, normalising
62,338 logs would have needed a header per distinct block carrying an event —
tens of thousands of requests. One header per 100 blocks plus linear
interpolation costs 804, and every timestamp derived that way is stored with
`block_timestamp_interpolated: true` and a declared precision of ± 10.1 s.

## 5. Integrity

* Collected through `flytrade/pons/collector.py`: the same filters, the same
  `Normaliser` and the same durable cursor the live driver uses. Replay and
  live are one code path.
* `MANIFEST.json` carries the sha256 of every file, the window, the ledger and
  the two collection passes.
* The endpoint URL and key appear nowhere in any artifact; every error string
  that leaves the client is masked, and `tests/d10/test_secrets.py` greps the
  wave's artifacts for them.
* **No outcome, label, PnL or post-cutoff return was read or computed during
  the collection.**
