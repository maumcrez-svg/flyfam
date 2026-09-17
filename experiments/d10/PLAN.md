# D10 — the Pons memecoin loop, registered before the run

This file and `config.json` are committed **alone**, before `d10-001` exists
and before any Pons outcome has been computed. Everything either of them says
is a decision, not a finding. `docs/SPEC.md` holds the owner's amendment, the
nineteen Fable addenda and the reviewer decisions after dispatch 1; where this
file and the addenda differ, the addenda win and the difference is a declared
deviation.

## 1. What is being run

A simulated fly brain observes memecoins launched through PONS v2 on Robinhood
Chain, receives their market context through the olfactory path this repository
has already measured, chooses among eligible candidates under the documented
decoder, enters one paper position, is held to a fixed fifteen-minute horizon,
experiences the settled net outcome, and carries the learned state into the
next token.

**What this is not.** It is not a prediction test. No probe grid, no label, no
AUC and no holdout is designed for D10, so conclusion 4 of amendment section 13
reads *not tested — no predictive evaluation was designed for D10*. It is not a
claim about profitability; profitability is not a gate metric here and never
has been. It is not a multimodal system: the `SensoryEncoder` interface exists
and returns `{"olfactory": Stimulus}`, and `visual`, `taste` and
`mechanosensory` are named as unimplemented extension points and routed
nowhere.

## 2. The data

`data/pons/d10-backfill-v1` — 80,198 blocks, the 135 minutes ending at the
`safe` block dispatch 1 recorded (60,801,426), collected over HTTP through
`flytrade/pons/collector.py`, the same normalisation path the live driver uses.
991 launches, 672 of them native-ETH and followed, 319 on another quote
recorded `QUOTE_UNSUPPORTED` and not followed, 62,338 events, 7
`CurveCompleted`. The window was chosen by that rule and by nothing observed
inside it. `backfill_report.md` has the numbers and the cost; `config.json`
carries the sha256 of every file.

The donor dataset `d10-replay-v1` is **not** the run's data: it covers roughly
the first 62 seconds of each token, so a fifteen-minute horizon admits nothing
on it. It stays as validation evidence — the curve port reproduces 546/546 of
its calibrations and 13,704/13,704 of its settled trades — and as the material
the launch-state derivation was proven on.

## 3. What the fly sees

`pons_context_v1`, eight measurements at the cutoff and nothing after it:
`age`, `ret_30s`, `ret_2m`, `ret_5m`, `flow_imb_2m`, `trade_rate_2m`, `rv_2m`,
`drawdown_5m`. Returns are of the **marginal curve price**
`quote_reserve / token_reserve` with the phantom reserve included, and windows
are **clipped to the launch** rather than zeroed: a token younger than the
window measures since its launch.

Three prices are separate fields and are never interchangeable: the last trade
price, the marginal curve price, and the executable amount-out for exactly
0.01 ETH. Only the marginal price enters a feature.

A token younger than 60 s, one with fewer than three trades, or one whose
reconstructed state fails the curve's own arithmetic is **not presented**, and
the reason is recorded. A two-minute window with no trades is a valid
measurement — rate 0, imbalance 0 — and is presented. Absent is not neutral.

Each feature is `tanh(raw / scale)` with the scale fixed in `config.json` from
the tokens launched in the **first hour** of the window, at 30-second grid
points, age ≥ 60 s and ≥ 3 trades, as `p90(|x|)` to two significant figures.
`age` is the declared constant 600 s. The scales are set before this file is
committed and are never refitted. **No outcome, PnL or post-cutoff return was
computed to produce them.**

Three of the eight features never change sign (`age`, `trade_rate_2m`,
`drawdown_5m`), so one glomerulus of each of those antagonistic pairs only ever
receives the carrier. That is a property of the measurement, declared here
rather than hidden.

## 4. What the fly does

Sixteen channels are available at the declared `MIN_UPNS`, so all eight
features are carried and none is dropped. Each round presents at most six
admitted candidates through `ComparisonReadoutPolicy` at k = 8 under
`comparison_v1` — the schedule that is **not** keyed to the weight digest, so
the LEARN and FROZEN branches draw the same Poisson stream for the same
observation and order- and metadata-invariance hold by construction. The
decoder is the existing one at the stored k = 8 baseline and margin.

Admission (`admission_v1`) is seven objective facts and no opinion; rotation is
round-robin on rounds-since-last-presentation and the launch order, blind to
price, volume, flow, outcome and ticker. Every launch gets a `DISCOVERY`
record whether admitted or not, so the dataset is the launches that happened
and not the launches that survived.

One position at a time. A decoded BUY opens at the reconstructed state of the
first block at or after `cutoff + 2 s`. A decoded SELL while holding is
recorded and then refused with `RejectReason.FIXED_HOLD`: it is a signal, not a
sale. The position closes at `entry_fill_time + 900 s` with
`CloseReason.POLICY_CLOSE_FIXED_HOLD`. While it is open, every tick still
records the token's context, the candidates' neural response and the position's
**mark** — the exit quote of exactly this position at the reconstructed state.
A mark is a mark: it is displayed and it never reaches reinforcement.

## 5. What a fill costs

The integer-exact port of the frozen `PonsV2BondingCurveMath.sol`: base fee,
creator tax, and the snipe tax with its cap and its fourteen-halving decay
computed from the fill block's own timestamp — zero after five seconds, never
assumed zero. The position's own reserve delta is carried, so its exit quote
sees its own impact plus the external flow that actually happened; the recorded
public market is unchanged by it and this wave claims no market impact of any
kind.

`FEE_BPS` and `SLIPPAGE_BPS` of `flytrade/execution.py` are **not used**. The
curve costs and the three gas constants go into `fees`; the price impact of our
own size goes into `slippage`. So `gross_reference − slippage − fees = net` and
`net = gross − fees` both still hold and the account's existing invariant tests
still bite.

An entry that would exhaust the curve is refused (`CURVE_EXHAUSTED`), not
resized. An exit that cannot be priced is not a loss: a curve that completed
onto the unsupported Uniswap V4 route is `UNRESOLVED(ROUTE_TRANSITION)`, a
horizon past the data is `UNRESOLVED(COVERAGE)`, and unconfirmed blocks are
`PENDING_CONFIRMATION`, retried. The exposure is retained in all three cases and
none of them teaches anything.

## 6. What the fly learns

**One** normalised update per settled episode, credited to the entry decision's
stored k = 8 eligibility trace set by episode id, through the existing
`CreditAssigner`. The mapping, in one sentence: *`valence` is the sign of the
settled net outcome and `amount` is
`min(|net_pnl / notional| / 0.01, 1.0)` — `ExecutionPolicy.reinforcement`,
unchanged, with no new constant added by this wave.* A memecoin's
fifteen-minute return on a 0.01 ETH notional will usually exceed 1 %, so
`amount` will usually saturate at the cap; that is a consequence of reusing the
existing rule and is recorded here before the run rather than fixed afterwards
by inventing a Pons-specific scale.

No interim reward. No reward from a mark, from a blocked SELL or from a skipped
entry. No reset when a new token appears or after a loss. The `OUTCOME` event
itself is written only once the entry-fill block and the exit block are both
confirmed — at least 594 blocks behind head and at or below `safe` — so a
rollback cannot have taught anything by construction.

After the first settled episode the learning branch destroys its in-memory
gains, rebuilds the journal and recovers from the checkpoint and the log. The
run is refused unless the gains come back exactly.

## 7. The runs, and how they will be read

`d10-001`, two branches:

* **`learning`** — LEARN, from the clean reference checkpoint
  (`ba95b60503d6…`), strict chronological order over the window.
* **`frozen_reference`** — FROZEN, the same data and the same seeds from the
  same clean checkpoint. Its end digest must equal its start digest, its
  settlements must all count `SETTLED_FROZEN` and credit accepted must be 0. It
  is the mechanical control, not a scientific comparison.

`learning` is then executed a second time and must reproduce the first bit for
bit, after removing the two fields a second process cannot reproduce by
construction: the wall-clock `t` stamped on every event line and the absolute
checkpoint path.

Expected activity, stated in advance: 270 ticks; at most **9** episodes, since
one position at a time each lock 30 ticks and admission closes after minute
120; probably fewer, because an entry also needs a decoded BUY and a curve that
completes before the horizon settles nothing. **Zero episodes is an admissible
result and will be reported as such.** Nothing — gain, thresholds, scales,
admission, the window — is touched to produce activity.

The four conclusions of amendment section 13 are reported separately and never
merged:

1. **Integration** — works, or a named blocker.
2. **The brain produced the observed behaviour** — whether the decisions came
   from the decoder on the recorded neural response and from nothing else.
3. **Learning updated the declared eligible state** — whether the settled
   episodes moved the weights they were supposed to move, and only those.
4. **Predictive usefulness** — *not tested; no predictive evaluation was
   designed for D10.*

Forbidden phrasings, fixed here: any form of "the fly learned"; reading the
number of episodes as evidence of anything; reading a negative or empty result
as an engineering failure; describing this window as a holdout; describing a
paper fill as a transaction or a signal as a fill.
