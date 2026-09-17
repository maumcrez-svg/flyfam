# PAPER / test-holder autoexit

Owner-approved on 2026-09-16. This fallback is restricted to REAL_PONS_PAPER
positions with FIXTURE holders. Real holders and LIVE money are not enabled.

Two consecutive completed NO_QUORUM_HOLD rounds arm autoexit, and nothing can
arm in the first 600 seconds after the entry. Armed, it requests the same
worker/executor to sell when a fresh canonical liquidation mark:
- reaches +20% gross return;
- reaches -20% gross return;
- confirms at least 600 seconds without market trades;
- or the bag has been open 3600 seconds with no finalized HOLD vote.

The deciding return is GROSS: quantity x (the mark's marginal liquidation
price - the entry fill price), over the paper entry principal. That is the
same quantity the close books as gross_pnl_wei over entry_principal_wei,
except that a mark publishes a marginal price and not an exit fill, so it runs
0.22 to 0.58 percentage points optimistic (the position's own curve impact at
liquidation, measured on bags 1-12 of 2026-09-16). Net liquidation PnL is
still computed, published and shown; it no longer decides anything.
BAG_AUTOEXIT_RETURN_BASIS=NET restores the original net rule for tests.
Thresholds trigger an exit intent, not a guaranteed fill price or confirmed
settlement. Only fresh marks (at most 90 seconds old, not future dated)
qualify, for the maximum-hold trigger as well. An active market inside both
return limits still holds until the maximum hold.

## Why the net basis was replaced

A paper round trip on these curves costs 2.5% to 8.6% of notional, so a bag
was born below a -5% net stop. On 2026-09-16 bags 3 to 10 were all sold by
AUTO_EXIT_STOP_LOSS 64 to 75 seconds after opening, before any market move
could be read: bag 6 at gross +4.38% with 8.63% of costs (net -4.25%), bag 7
at gross -0.00% (net -6.53%), bag 10 at gross -0.22% (net -6.75%). The stop
was measuring the entry fee, not the market. Gross return, a minimum hold and
wider bands separate the two; a maximum hold still guarantees that a bag no
one votes on ends.

A valid vote in the current round pauses autoexit while the round is pending,
the maximum hold included. At finalization HOLD restores community control,
resets the empty-round streak and restarts the maximum-hold clock from that
round's close; EXIT requests the ordinary community exit. Two later empty
rounds can arm the fallback again. An already committed exit cannot be
canceled by a vote. The maximum-hold clock therefore runs from the later of
the entry and the last finalized COMMUNITY_HOLD.

The round worker creates a stable per-bag exit intent inside the same SQL
transaction that freezes voting. No vote is fabricated. Source AUTO_EXIT and
reason AUTO_EXIT_TAKE_PROFIT / AUTO_EXIT_STOP_LOSS / AUTO_EXIT_INACTIVE /
AUTO_EXIT_MAX_HOLD are retained in the immutable audit and bag receipt. The worker records CLOSE with
close_reason=AUTO_EXIT, waits for its existing confirmation rule, and performs
the existing PAPER settlement. Failures remain explicit pending exits.

## Activity evidence

Curve inactivity uses valid canonical curve trades through a covered cutoff.
A flat price, stale observation, missing tape or failed RPC is not inactivity.
MARK carries activity evidence and its observation timestamp. Evidence
gathered over a window shorter than the policy's still qualifies when it
carries the last observed trade itself and that trade is older than the policy
window: a longer measured silence is strictly stronger evidence. A shorter
measured silence never qualifies.

Post-migration inactivity queries only Swap logs of the verified Pons V4
PoolManager and exact verified pool ID, over a bounded block range covering
the complete idle window. Chain 4663 produced 6,000 blocks in 606 seconds on
2026-09-16, so a 600-second window needs about 5,950 blocks against the
10,000-block ceiling; windows beyond roughly 1,000 seconds would exceed it and
silently withhold the trigger rather than assert a false silence. Endpoint headers are checked before/after;
coverage failure, reorg, unavailable or oversized logs disable this trigger.
A slightly wider start is conservative: boundary trades may delay inactivity.
The Swap ABI follows the canonical
[Uniswap IPoolManager interface](https://github.com/Uniswap/v4-core/blob/main/src/interfaces/IPoolManager.sol).
This adds no trade signing, neural input, or neural learning.

## Configuration and persistence

Explicit enable only: BAG_TEST_AUTOEXIT_ENABLED=YES.
Defaults, configurable before a bag's policy is recorded:

    BAG_AUTOEXIT_EMPTY_ROUNDS=2
    BAG_AUTOEXIT_RETURN_BASIS=GROSS
    BAG_AUTOEXIT_PROFIT_BPS=2000
    BAG_AUTOEXIT_LOSS_BPS=2000
    BAG_AUTOEXIT_IDLE_SECONDS=600
    BAG_AUTOEXIT_MIN_HOLD_SECONDS=600
    BAG_AUTOEXIT_MAX_HOLD_SECONDS=3600
    BAG_AUTOEXIT_MARK_MAX_AGE=90

Bounds: MIN_HOLD 0-86400, MAX_HOLD 300-86400 and strictly above MIN_HOLD,
PROFIT/LOSS 1-10000 bps, IDLE 30-3600 s, MARK_MAX_AGE 1-90 s.

The policy is persisted per bag in the existing meta store and audited on
first activation. Existing open test bags can activate against their actual
recent completed rounds; their OPEN, snapshot and old audit are not rewritten.
A restart retains the policy, round history, intent and original executor.
There is no schema migration or new journal.

GET /api/bags adds bag.auto_exit (policy, control state, empty-round count,
observation status, bag age, seconds since the last community action, and the
current gross and net returns). The browser displays these values
without computing its own financial thresholds. The existing private
bag-room.env is shared by the PAPER worker, round worker and both viewers.
Activation requires restarting those processes to load code/config. Only the
Bag worker decides autoexit; the PAPER trader publishes the marks, so the
activity window in the evidence follows the trader's own restart. The
public-DNS ingress and signing/payout services need no change.

## Installed proof

WUKONG Bag #2 closed once through the original worker after AUTO_EXIT_INACTIVE,
net PAPER -3.108756680545102%. Entry/snapshot and 2,777 old audit rows were
preserved. No test wallet voted. The next naturally selected Bag #3 exercised
the stop-loss trigger after two empty rounds; profit triggering is a synthetic
test, not an observed market win.

The confirmed-close delay was 498.37 seconds because the local node's safe tag
lagged the exit block. Existing confirmation requirements were retained.
An index-thread SQLITE_BUSY recovery issue observed at restart was corrected
and regression-tested. Evidence and the focused tests are under
output/autoexit/ (73 at the v1 install, 89 after the gross rule). Chromium/WebKit covered desktop, 390/430px and the receipt.
