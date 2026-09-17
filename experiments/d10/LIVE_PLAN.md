# D10 — the live exercise, registered before it runs

**Why this is a separate file.** `PLAN.md` and `config.json` were committed
alone before the replay run and are pinned there by
`tests/d10/test_scales_hygiene.py`, which asserts that the last commit touching
either is the commit containing exactly those two files and that it precedes
the run. Amending them now would break that proof of register-then-compute for
`d10-001`. So stage E registers itself here and in `experiments/d10/live.json`,
committed together and **before** `d10-live-001` existed. Nothing in
`config.json` changes: the cadence, the size, the horizon, the latency, the
gas, the scales, the admission rule, the budgets and the settlement rule are
the ones the replay run used.

Stage E of the amendment and addendum 15. `d10-live-001`, **LIVE_PAPER**,
**LEARN**, one branch, starting from `d10-001/learning`'s final checkpoint
(`999d32450a3b…`, the digest `results.md` published for that branch) so the
continuity replay → live is exercised rather than asserted. The parameters are
in `experiments/d10/live.json`, committed with this section and before the run;
`config.json` is **not** edited, because its own register-then-compute check
pins it to the commit that precedes the replay run.

The loop is the same object. What changes is the driver: a wall clock instead
of a virtual one, the collector's poll instead of a file, and four ways to
stop — **60 minutes, 3,000 requests, a `stop` file flag, SIGTERM**, whichever
comes first, then a clean stop with the cursor, the ledger, the journal and the
checkpoint persisted. The run stops on the **first** endpoint error: no retry,
no fallback, no provider switch. Two live-only mechanics are declared in
`flytrade/pons/loop.py`: one header per tick is read **after** the poll so a
fill at `cutoff + 2 s` has a block to land on, and a launch is held until its
first trade pins the creator tax (the arithmetic dispatch 2 measured on 546 of
546 calibrations) rather than bought with a state read per curve.

One admission fact differs and only one: `require_coverage` is **off**. "The
horizon lies inside the token's coverage" is addendum 10's *replay* clause;
live has no end of data to keep a horizon inside. Admission therefore never
closes, and a position still open when the run stops is **retained and reported
open or pending — never closed at the last mark**.

Expected before the run: 120 ticks, at most **4** episodes, and fewer because an
entry needs a decoded BUY and because settlement needs blocks confirmed at least
594 deep **and** at or below `safe`, which the measured ~9-minute `safe` lag
cannot supply for the last stretch of the hour. **Zero episodes, and zero
admitted candidates in the hour, are admissible results** and are reported as
such. The live report is written separately from the replay's, the four
conclusions stay separate, and conclusion 4 still reads *not tested*.
