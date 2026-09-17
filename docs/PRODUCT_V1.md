# Strong V1 — implementation record

The V2 frontend and paper worker were activated locally on 2026-09-14.
See `live-activation notes` for installed services, commands, recovery evidence and
the current unresolved exit-route limitation. Development remains on
`/tmp/flytrade-strong-v1`, branch `product/strong-v1`; installed code is a separate
durable worktree. Public hosting and complete Strong V1 acceptance are not implied.

## Character and state

One frozen reference brain, one canonical paper executor. Raw selection is
baseline-centered approach minus avoidance firing rate in Hz, k=8. Every actual
candidate presentation is recorded; eligibility filtering is separate. A bar
may visualize the raw quantity, never a probability or aesthetic 0-100 score.
Only final measured aggregate scores are available: no fake intra-round spikes.

Server phases follow SNIFFING -> PICK / ENTRY_REJECTED -> POSITION_OPEN ->
POSITION -> CONSEQUENCE, then the next canonical sniff. PICK is distinct from
OPEN. Browser presentation can stage durable moments without changing the
canonical state or delaying worker processing.

## Accounting and history

MARK uses canonical unrealised ETH / paper notional; raw token move uses the
observed reference price separately. Fees/slippage, modeled exit value,
peak/trough, giveback and drawdown are backend fields. Missing marks form gaps.
CLOSE supplies booked episode result. Canonical account snapshots supply account
value only if available; an absent starting bankroll is never invented.

Career stores closed outcomes, net/gross/costs, streaks and deterministic records.
Neutral results break a streak. Episode career-at-close is retained independently
of later totals. Observation counts are labeled observations/presentations, not
unique tokens or probability. Migration counters remain unavailable without
migration evidence.

Old P1 contains one rounded close result. The projection exposes both the sum of
closed episode results and canonical account realized PnL, with a reconciliation
delta and status. The captured history's delta was 2.799616193e-9 ETH. It is not
silently distributed into past episodes. Imported legacy candidate scores retain
their recorded six-decimal precision; ambiguous ranks and missing population or
decoder fields are explicitly unavailable. Existing OPEN/CLOSE/credit evidence
is not rewritten. Importing old internal metadata after public events enriches
episode watchlists; historical career snapshots retain their then-known census.

## Systematic follow-ups

Track first recorded observation per run/chain/token/launch/category. Every
recorded filtered candidate belongs to FILTERED_OUT; actual presented,
non-selected candidates belong to FLY_REJECTED. These never merge. Stable IDs,
original reason, raw score/rank when available and chosen alternative persist.
Repeating the same token does not reset its window or cherry-pick a better entry.

Windows are 5, 15 and 30 minutes after the seen timestamp. Raw movement uses
canonical curve state. Hypothetical net return separately calls the unchanged
paper quote primitives with entry latency, own impact, curve fees/tax and gas;
it never opens a position or changes the account. Exit is quoted at seen+window,
so modeled holding duration is window minus entry latency, explicitly recorded.
Each result retains quote/state/block evidence. Incomplete, unconfirmed,
inconsistent or completed routes do not become fabricated returns.

Pending follow-ups extend observation only, preserving neural admission rules.
Confirmation/coverage may wait 300 seconds beyond due; unavailable results then
close the window without retaining a token forever. Legacy follow-ups cannot
claim observations beyond the old collector's track window. Expired raw tapes
are explicitly unavailable; this does not retroactively manufacture old misses.

BIGGEST_MISS = highest positive valid modeled net at 15 minutes among
FLY_REJECTED. BEST_SAVE = lowest negative modeled net under the same rule.
FILTER_MISS = highest positive raw price movement at 30 minutes, FILTERED_OUT.
Largest rejected price rise/collapse is a separate raw-price category, never
claimed as executable paper profit. Today uses UTC due-window dates; ties use
earlier due time then target identity order.

## Running the read-only API

From this worktree, using an initialized product database:

```sh
data/runtime/bag-room-env/bin/python product/run_viewer.py --sqlite-library data/runtime/viewer-sqlite-3.51.3/libsqlite3.so.0 --database /ABSOLUTE/DATA/product.sqlite3 --port 8797 --worker-pid /ABSOLUTE/DATA/worker.pid
```

Optional `--static-dir` serves a built frontend with safe rooted asset resolution.
The default has no static frontend configured. All presentation endpoints are
GET/HEAD; POST/PUT/PATCH/DELETE return 405. There is no RPC proxy, arbitrary file
read or viewer-triggered decision. CSP, nosniff, referrer and permissions headers
are applied. Do not render token metadata as HTML. Public endpoint details live
in `SPECTACLE_FEED.md`. This command does not start another brain.

The worker retains its `product/run.py --config PATH`, `--status`, and `--stop`
interface. The user-authorized local systemd migration is recorded in
`live-activation notes`. Boot persistence and public hosting remain disabled.

## Evidence

`tools/benchmark-spectacle-projection.py` captures closed lines from existing P1
journals into an isolated directory, without RPC or writes to the source. The
recorded run in `STRONG_V1_PROJECTION_REHEARSAL.json` imported 12,558 canonical
events, rebuilt projection in 1.04 s and follow-up targets in 0.21 s. All 14
closed episodes linked to their actual recorded watchlists. Live snapshot was
33,685 bytes; sampled projection reads averaged below 1 ms. These are backend
measurements, not browser CPU, viewer bandwidth or continuous-worker proof.
The rehearsal has no market tapes and does not claim resolved historical misses.

Backend tests exercise accounting, fixed windows, category separation, missing
coverage, valid overtakes, replay caps, reconnect cursors, immutable history,
checkpoint recovery, retention, disk safety and read-only HTTP. The final visual,
share and live-operation acceptance remains part of this same product wave.

Checkpoint regression: `tests/product tests/strong_v1`, 121 passed in 180.90 s.
This does not replace the requested rendered-browser and migrated-runtime gates.
