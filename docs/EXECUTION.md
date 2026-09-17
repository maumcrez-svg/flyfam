# Execution — paper fixture v1, accounting, and time

`flytrade/execution.py`, version `flytrade-exec-1`. Canonical amendment §6,
Fable addendum 8. Everything here was declared before it was run against any
price series, and nothing in it was chosen after inspecting evaluation-period
PnL.

Offline in the strict sense: no venue, no key, no order router, no provider.
The only object in the repository that may read a bar after the decision cutoff
is `flytrade.market.ExecutionFeed`, and it is constructed here and nowhere
else.

## 1. The policy

| | |
|---|---|
| decision | at the **close** of bar `t` |
| execution | at the **open** of bar `t + 1` |
| declared delay | **1 bar**, never zero — `delay_bars < 1` raises |
| sizing | fixed notional **1,000** |
| exposure | **one** open position, **long only** |
| fee | **5 bps** of traded value, charged on entry *and* on exit |
| slippage | **5 bps**, always against the trader |
| horizon | **8 bars**, then `POLICY_CLOSE` |
| initial cash | 10,000 |
| outcome | **net realised** PnL, after both fees |

Round-trip cost on a flat tape is therefore 10 bps of slippage plus 10 bps of
fee: a position opened and closed at an unchanged price loses exactly 2.00 on
1,000 of notional, and that is asserted as a test rather than left implicit.

### Action semantics

`BUY` opens the one permitted long. `SELL` reduces existing exposure — with no
position open, a decoded `SELL` is a `POLICY_REJECT` with reason `NO_POSITION`,
never an unimplemented short. `WAIT` leaves exposure unchanged.

### Closes, and what is not a decision

| reason | meaning |
|---|---|
| `NEURAL_SELL` | the decoder emitted `SELL` while the position was open |
| `POLICY_CLOSE` | the evaluation horizon expired — mechanical |
| `END_OF_DATA` | the series ran out before the horizon did |

Only `NEURAL_SELL` is a decision. A timer firing is the easiest way to inflate
the number of decisions a system appears to make, so the record keeps the three
apart and the demonstration reports them separately.

### Rejections

Each is counted by reason, never pooled: `POSITION_OPEN`, `NO_POSITION`,
`NO_FUTURE_BAR`, `INSUFFICIENT_CASH`, `BAD_PRICE`. A `NaN` bar is a
`BAD_PRICE` rejection; it is never traded through or interpolated.

## 2. Accounting

```
open :  qty   = notional / fill_price
        cash -= qty * fill_price + fee
close:  cash += qty * fill_price - fee
        gross = qty * (exit_fill - entry_fill)
        net   = gross - entry_fee - exit_fee
        realized_pnl += net
```

`Account.check()` runs on every close and raises unless

```
cash == initial_cash + realized_pnl        (while flat)
```

Equity while a position is open is `cash + qty * mark`. Unrealised movement
appears there and **nowhere else**: it never reaches a reinforcement.

## 3. Outcome to reinforcement

```
r       = net_pnl / notional
valence = +1 if r > 0,  -1 if r < 0,  0 if exactly flat
amount  = min(|r| / 0.01, 1.0)
```

A net return of +1% of notional is a full-strength dopamine event; anything
larger is clipped at the declared cap. `valence = +1` routes the event to the
**PAM-innervated** compartment and `-1` to the **PPL1-innervated** one, by
calling `MushroomBody.dopamine(valence, amount, episode_id=...)`, which reads
the compartment map built from `graph_mod.npz`. **No weight is ever written
directly**, and a test asserts that the only weights that change are plastic
KC→MBON synapses on the addressed side.

Three rules that follow, and are tested:

* reinforcement comes from **realised** PnL only — an open position at a
  profit reinforces nothing;
* an outcome of exactly zero delivers **no** dopamine event at all, rather than
  an arbitrary one;
* **no counterfactual reward** is computed for an instrument that was not
  chosen. There is no outcome record for a candidate that was never opened.

For how that reinforcement is then gated to the correct episode, see
`flytrade/runner.py`'s `CreditAssigner`: it is applied to the trace the
decision **stored**, not to the live eligibility layer.

## 4. Time — four clocks, and the gap between two of them

| clock | unit | value |
|---|---|---|
| **market time** | one bar | 3,600 s in the synthetic fixtures; whatever a CSV declares otherwise |
| | execution delay | 1 bar = 3,600 s |
| | evaluation horizon | 8 bars = 28,800 s |
| | outcome arrival, after the decision | 9 bars = **32,400 s** |
| **simulation time** | one decision cycle | 500 ms (`flytrade/state.py`) |
| | one presentation window | 20 ms of brain time |
| | one round of *k* candidates | *k* presentations, each from the same snapshot |
| **eligibility decay** | τ | 836 ms; 0.55 per 500 ms cycle |
| | trace below `TRACE_EPS` after | 5.01 cycles ≈ 3 s |
| **weight recovery** | τ | 624.8 s (~10.4 min) |

The gap is the whole design problem. An outcome arrives **32,400 s** of market
time after the decision that caused it. The eligibility trace that decision laid
down is gone after about **3 s** of simulation time (5.01 cycles of 0.55 take
the trace below `TRACE_EPS`) — the outcome arrives some **38,700 eligibility
time constants** late.

Two dishonest ways out, both refused:

* stretching τ from 836 ms to hours, which would mean quietly rewriting a
  biological constant to fit a market;
* reinforcing whatever happens to be eligible when the outcome lands, which is
  exactly the mis-assignment amendment §5 forbids.

The convention actually used (Fable addendum 6) is **stored-trace replay**: the
decision stores its eligibility trace at decision time; when the outcome
arrives, reinforcement is applied to that stored trace, which is then discarded
and the episode closed. The time constants in `state.py` are **unchanged** and
still govern what happens inside a simulation cycle. Every learning event
records `eligibility_source = "replayed_from_decision"` and its episode id, so
the log never lets the two be confused.

It is a modelling convention and it is stated as one. What it does not claim:
that a fly can bridge nine hours with a 836 ms trace.

## 5. Data

Amendment §6 and addendum 7: no purchase, no provider account, no network.

* **Synthetic fixtures**, seeded, deterministic — a random walk through four
  regimes (quiet drift up, sharp fall, chop, rally). The demonstration runs on
  these.
* **Local CSV**, the format documented at the top of `flytrade/market.py`, one
  file per symbol under `data/market/` (gitignored). The same runner accepts a
  dropped-in file; `load_csv` and `write_csv` round-trip, which is tested.

One open trade at a time, so there is exactly one unresolved decision in flight
(amendment §5).

---

## Historical time — D6

`flytrade.historical.HistoricalExecution` is this policy with the bar
arithmetic replaced and **every number preserved**. Notional 1000, one open
long, fee 5 bps, slippage 5 bps, delay 1, horizon 8, initial cash 10000,
`REINFORCE_FULL_SCALE` 0.01, cap 1.0 — all unchanged. What D6 fixes is what
"1" and "8" mean when the minute they point at may not exist in the file.

### Costs, stated once

Both costs are charged **per execution**, that is twice per round trip: the
fee on the entry and again on the exit, the slippage against the trader on
each fill. **A completed round trip therefore costs 20 bps in total.** Neither
parameter is applied twice to the same execution, and the run reconciles it:

```
gross_reference_pnl  −  fees  −  modelled slippage  =  net realised PnL
```

`gross_reference_pnl` is computed at the unslipped bar prices; `gross_pnl`
keeps its Phase One meaning at the fill prices, so `net = gross − fees` stays
true as well. The residual of the three-term identity must be zero to 1e-6 and
is reported per branch.

### The five clock rules

1. **Decision at `bar_end(t)`.** The first instant the bar's final OHLCV
   exists. No order uses the decision bar's own high, low or close, and no
   order uses a later bar's prices as information available at the decision.
2. **Fill** = the *open* of the first available regular-session bar with
   `bar_start ≥ bar_end(t)`, same session. Not the next calendar minute →
   `DELAYED_FILL`, with the elapsed market minutes on the fill.
3. **Settlement** = the *open* of the first available bar with
   `bar_start ≥ fill.bar_start + 8 market minutes`, flagged the same way.
4. **Entry eligibility** is a clock rule checked before any price is read:
   `bar_end(t) + 1 min + 8 min ≤ 16:00` on the same session, i.e.
   `bar_start(t) ≤ 15:50`. Refused entries are `POLICY_REJECT` with reason
   `SESSION_HORIZON` — a declared boundary, never advance knowledge of prices
   or of where the gaps are.
5. **Session close.** A position still open at its instrument's last available
   bar of the session — reachable only through gaps — is closed at that bar's
   *close* with `SESSION_CLOSE_FILL` and `close_reason = POLICY_CLOSE`, counted
   separately. Nothing crosses a day, therefore nothing crosses a partition.

One guard follows from "one open position" and is declared rather than
discovered: **an entry may not fill before the previous exit filled.** A
delayed exit delays the next entry, flagged like any other delay.

### What is never invented

A due fill or settlement without a valid price is a recorded `Rejection` with
its own reason (`BAD_PRICE`, `NO_FUTURE_BAR`), never a fabricated price and
never a quietly dropped episode. `BUY`, inventory-reducing `SELL`, `WAIT`,
`POLICY_REJECT` and `POLICY_CLOSE` remain five different things in every
record, and `DELAYED_FILL` and `SESSION_CLOSE_FILL` are counted apart from all
of them.

### Frozen settlement

In the `FROZEN` partition an outcome is settled **for accounting only**:
`Journal.settle_frozen` writes the `OUTCOME` event with
`settlement = SETTLED_FROZEN`, marks the episode settled so a restart cannot
replay it, clears the pending file, and writes **no** `LEARNING` event and
calls no reinforcement. The checkpoint's episode counter moves; the gains do
not, so the partition's end digest equals its start digest.
