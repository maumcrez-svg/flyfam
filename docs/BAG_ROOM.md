# Bag Room — holder-controlled PAPER exits

Owner decision, 2026-09-15: **the fly chooses entry; snapshotted project-token
holders decide the normal exit.** This supersedes the old no-voting/fixed-hold
product policy only for positions opened after explicit Bag Room activation.
The reference brain, sensory encoder, admission, decoder and frozen CREDIT
semantics are unchanged. Existing pre-activation positions normally keep their original
recorded policy. The explicit Phase A cutover can adopt a uniquely verified
existing PAPER position without a pending close, as documented below. There is no voting contract or real-money execution.

The project token will launch **through PONS** on Robinhood Chain. It has **not launched**. The production contract and deployment
block are blank. The target chain is Robinhood Chain, 4663. Demo addresses and
holders have no relation to a real project token.

## Current Phase A integration (2026-09-15)

The actual main PAPER worker now feeds Bag Room with fixture holders, without
waiting for a project token. See [paper-bridge notes](paper-bridge notes)
for the current runtime, source labels, account-preserving adoption, browser
proof, and configuration-only switch to real holders. The isolated demo and
post-token-only instructions below describe the earlier release.

## Distribution update

For real-money activation, the current holder-profit path is the native
[Payout Wallet](payout notes), with signed off-chain claims and confirmed
native transfers. It does not require a distribution contract. Current PAPER /
TEST HOLDER bags still have no real claim allocations.

## Runtime components

- `flytrade/bags/store.py`: SQLite schema migration v1, WAL/FULL synchronization,
  short connections per operation, SQL uniqueness constraints, transactionally
  finalized rounds, and an immutable hash-linked audit journal.
- `indexer.py`: bounded range reads of the configured ERC-20's `Transfer` logs;
  integer balances, mint/burn accounting, durable cursor and block hash. No
  per-holder balanceOf fanout. Finalized cursor hash changes halt indexing.
- `service.py`: bags, immutable eligibility, EIP-712 challenges/actions, chat,
  rounds, history, participation leaderboard and reserved profit ledger.
- `worker.py`: independent indexing thread and 500 ms round clock. RPC catch-up
  does not block open voting rounds. It never loads a brain or executes orders.
- `bridge.py`: the PAPER worker's adapter. It reuses the existing curve/V4 quote,
  confirmation, settlement, frozen consequence and recovery paths.
- `http.py`: narrowly scoped same-origin signed action endpoints. Existing
  spectator/trading endpoints remain read-only. No `/buy` or `/sell` route.

## Configuration after the token launches

Copy `product/bag-room.env.example` to an owner-managed environment file and set:

```dotenv
PROJECT_TOKEN_ADDRESS=
PROJECT_TOKEN_DEPLOYMENT_BLOCK=
ELIGIBILITY_EXCLUDED_ADDRESSES=
BAG_ROOM_ORIGIN=http://localhost:8797
BAG_ROUND_SECONDS=30
BAG_PROFIT_TO_VAULT_BPS=10000
```

Addresses are validated and normalized. Exclusions are a comma-separated list
chosen by the owner: zero/dead, treasury, Holder Vault, project contracts, LPs
or other infrastructure **only when explicitly configured**. There are no
automatic router/factory/pool/contract-wallet filters. The zero address does not
accumulate a balance from mint/burn bookkeeping. A dead address with tokens is
otherwise an ordinary ledger holder unless excluded.

A token/deployment mismatch against an existing index refuses startup. Start
indexing at the provided deployment block; an incomplete ledger that would
produce negative balances refuses to advance. This is a standard ERC-20
Transfer ledger: balances must change through Transfer events. A rebasing or
otherwise nonstandard future token needs an explicit compatible indexing rule.

Policy changes are explicit configuration, journaled when no bag is active.
Finish the current bag before changing cadence or vault fraction. Already
materialized snapshots and completed results are never rewritten.

## Snapshot and votes

For the paper fill's entry block, choose `min(finalized, entry_block - 1)`.
Read/verify its hash; index through that height before opening voting. If the
index is already ahead, undo only its bounded Transfer tail to reconstruct the
entry snapshot. A target beyond that recovery bound fails visibly; it is never
replaced by current balances. If finality or index data is unavailable, the bag
stays `SNAPSHOT_PENDING` and cannot accept votes.

The sorted lowercase eligible address set is persisted per bag with a SHA-256
hash of its canonical compact JSON, block/hash and exclusion configuration.
Wallet membership is `balance > 0`, minus explicit exclusions. Weight is one.
Later buyers do not join the existing bag; later sellers keep its eligibility.

EIP-712 `BagAction` includes exact origin, wallet, action, bag_id, round_id,
choice, content, nonce, issued_at, expires_at and chain_id; the domain binds
name/version/chain. Backend-generated 120-second challenges are single-use.
EOA signatures use `eth-account==0.13.7`. ERC-1271 contract wallets can be
verified through the configured local metadata RPC. No private keys are
present in the production API or browser.

Connect signs AUTH; every vote and chat message signs its own bound action.
There is no gas transaction or reusable bearer credential. A second valid vote
updates that wallet's single effective vote for the round; both signed actions
remain in the audit journal. The wallet may change its mind until the deadline.
An expired challenge, ended round, different signer, domain/payload alteration,
unknown bag or non-eligible wallet is rejected server-side.

At 30 seconds, HOLD > EXIT continues. EXIT >= HOLD exits **only if votes exist**.
Zero votes produces `NO_QUORUM_HOLD`, then another round. The old 900-second
experiment horizon does not close a community bag. Rounds stop after an EXIT
result. Execution may wait for a usable quote and block confirmation; a voting
result is not a confirmed sale. The UI distinguishes requested, selling,
pending and closed states.

## Persistence and accounting

Canonical OPEN is the durable outbox source. Bag creation atomically inserts all
bag identity fields in its own database, uniquely keyed by that OPEN and its
episode. Delivery across product history and bag storage is replayable, not a
pretended cross-database transaction. Startup re-delivers the bounded event
stream after the saved activation frontier; identical OPEN/CLOSE deliveries
have no second effect. A closed bag paired with a stale open account fails
loudly rather than executing another exit.

An EXIT intent has one stable ID and timestamp per bag. The existing PAPER
executor pins its curve/V4 exit at that intent plus existing execution latency,
then uses the same confirmation/reorg checks as before. Pending V4 quotes keep
their existing durable evidence. Restart does not create a second winning round.

CLOSE supplies gross result, fees and net realized PnL. Positive net PnL is
reserved according to `BAG_PROFIT_TO_VAULT_BPS` (default 100%). Zero/loss emits
no positive credit. The ledger has one credit per bag/source CLOSE. The PAPER
account's existing float ETH arithmetic remains authoritative; integer display
amounts are explicitly rounded from it, never represented as exact chain money.

The community vault is a **reserve within PAPER custody**, excluded from the
fly's available entry capital and displayed bankroll equity. Entry must leave
that reserve and modeled exit gas intact. It is not a second wallet or a real
transfer. The vault is accrued/reserved, **not claimable**. There is no allocation,
claim, distribution, GOOGL payout, yield or token-fee implementation here.

## API and presentation

GET `/api/bags` returns a bounded current snapshot, round/tallies, latest chat,
closed receipts, participation leaderboard and compact events. `after` resumes
the stable audit sequence; `next_after` is the last event actually returned.
`id` selects a receipt; `wallet` adds immutable membership and own-vote state;
`before` paginates closed bags. GET `/api/bags/proof?id=&wallet=` returns snapshot
membership/evidence. GET `/api/bags/audit?id=&after=` returns up to 50 signed audit
rows per page, including previous/current hashes.

POST `/api/bags/challenge` accepts a bound action request; POST
`/api/bags/action` accepts only its nonce/signature. Exact Origin, JSON/body
limits, deadline, signature, nonce, eligibility, SQL uniqueness and rate limits
are enforced. No client vote count, PnL or round result is trusted. Round
finalization and executor access are not HTTP actions.

Anyone reads chat. Only eligible signed wallets write; text is limited to 400
characters and one message per three seconds. HTML is escaped. Leaderboard
counts **effective round votes**, HOLD/EXIT, distinct participating bags and
consecutive bag participation. Replacements remain auditable but do not inflate
participation counts. These are factual metrics, not a skill/profit ranking.

The right position panel contains the Bag Room while the position is active.
The fly, live price/accounting surfaces and replay remain intact. State-changing
reactions are theatrical animation. No-community-action does not pretend that
people voted. Completed bags have receipts, community vote timelines, episode
replay links, audit links and copyable `/?bag=<id>` URLs. Receipts show the latest
100 rounds; the paginated immutable audit retains the full history.

## Local demonstration (no project token required)

Durable checkout: `data/runtime/bag-room`.
Its `.venv` points to the separate verified `../bag-room-env` environment.
The running interactive fixture is **http://localhost:8798/?fixture=1**;
choose TEST CREW 1 or 2, CONNECT WALLET, then HOLD/EXIT.
The completed browser demonstration receipt is retained at port 8801 while
that separate review server is running.
The existing trader environment and services are untouched.

From that checkout:

```bash
.venv/bin/python tools/bags/demo.py --directory /tmp/fly-bag-demo-new --port 8798
```

Use a **fresh** directory: the demo never erases receipts. It starts a fresh,
loopback-only Anvil child with chain ID 4663 and **no fork**, deploys the committed
`FixtureToken.sol`, and mints one unit to one test wallet and ten million tokens
to another. The third wallet is a non-holder. The demo signer is isolated in
this server and absent from the production API. `TEST CREW 1 / 2` selects those
wallets, then CONNECT, HOLD/EXIT and chat use the actual signed-action API.

The Pons market is scripted fixture evidence. The frozen brain actually runs
and records its neural scores; a clearly declared scripted BUY guarantees the
mechanical entry demonstration. Paper execution, holder indexing, signatures,
round decisions, confirmation, CLOSE/CREDIT, vault and receipt are real code
paths. No demo market/entry/holder is presented as live Pons activity.

For an automatic complete demonstration, add `--auto`: two test wallets sign
HOLD in round one, then EXIT in round two. The worker confirms the close and
writes `demo.json` in that directory, including frozen-brain and accounting
results. The UI remains available for the archived receipt. Ctrl-C stops the
viewer and its isolated Anvil child. To rerun, use another directory.

Focused browser verification against a manual demo:

```bash
python tools/bags/browser.py \
  --url http://localhost:8799 --output /tmp/fly-bag-browser-qa
```

## Production process commands (after token configuration)

Install this release in the service checkout and use its verified environment for all three processes and the same absolute
data directory. The current live worker remains on its existing configuration
until activation. **Do not start a second paper worker beside its existing
user service.** The provided config enables community exits for new positions.

Load the owner-maintained environment file in the shell (or as EnvironmentFile
in each user unit). Then the process entrypoints are:

```bash
# Indexing + round clock; can run before the paper-worker policy switch.
.venv/bin/python product/run_bags.py \
  --sqlite-library data/runtime/viewer-sqlite-3.51.3/libsqlite3.so.0 \
  --database ./data/pons/live/bags.sqlite3 \
  --rpc http://127.0.0.1:8645

# Existing paper-worker service's replacement ExecStart, after stopping it cleanly:
.venv/bin/python product/run.py --config product/pons_bag_room_local.json

# Existing viewer's replacement ExecStart:
.venv/bin/python -m flytrade.product.api \
  --database ./data/pons/live/product.sqlite3 \
  --bag-database ./data/pons/live/bags.sqlite3 \
  --static-dir spectacle/static --port 8797 \
  --worker-pid ./data/pons/live/worker.pid \
  --metadata-rpc http://127.0.0.1:8645
```

`product/the-bags-user-unit` is the additional user-unit template. It is not
silently installed or enabled. Once configured/installed, lifecycle commands:

```bash
the user service start flytrade-bags flytrade-pons flytrade-viewer
the user service stop flytrade-pons flytrade-bags flytrade-viewer
the user service restart flytrade-bags flytrade-pons flytrade-viewer
the user service status flytrade-bags flytrade-pons flytrade-viewer
the service log -u flytrade-bags -u flytrade-pons -u flytrade-viewer -f
curl -sS http://localhost:8797/api/bags
curl -sS http://localhost:8797/api/health
xdg-open http://localhost:8797/
```

No sudo, automatic login/boot enable, real transactions or production-holder
simulation is performed. Public hosting/domain and the real project-token
address/deployment/exclusions remain owner-supplied configuration.

Signature references: [EIP-712](https://eips.ethereum.org/EIPS/eip-712),
[eth-account 0.13.7](https://eth-account.readthedocs.io/en/v0.13.7/eth_account.html).
