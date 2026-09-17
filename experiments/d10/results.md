# D10 — the Pons memecoin loop (d10-001)

**PAPER EXECUTION ON RECORDED ON-CHAIN EVENTS.** Every fill below is simulated. No transaction was signed, broadcast or sent; the package that talks to the chain has a six-method read-only allowlist and no key material anywhere. A signal is not a fill and a paper buy is not an on-chain transaction.

Reading rules, fixed in `PLAN.md` before the run:

* zero episodes is an admissible result and is reported as such;
* nothing — gain, thresholds, scales, admission, the window — was touched to produce activity;
* the four conclusions below are separate and are never merged;
* never any phrasing of the form "the fly learned";
* never reading an empty or negative result as an engineering failure.

## 1. Provenance, and the register-then-compute proof

| item | value |
|---|---|
| run | `d10-001`, branches `learning`, `frozen_reference` |
| plan + config commit | `a3899782dff4` — committed **alone**, before this run existed |
| `config.json` sha256 | `d5ba4221a4b1…` |
| `PLAN.md` sha256 | `ef283756db61…` |
| dataset | `d10-backfill-v1`, 80,198 blocks, 62,338 events |
| dataset `events.jsonl` sha256 | `3dfa76fbac31…` |
| graph | `8feb08a0d2a8…` |
| clean reference digest | `ba95b60503d6…` |
| venue / chain | PONS / 4663 |
| python · numpy | 3.13.9 · 2.4.2 |
| wall clock | 3.0 min, peak RSS 814 MiB |

**Every number in this file was produced after commit `a3899782dff4`**, which contains `PLAN.md` and `config.json` and nothing else. The scales, the horizon, the size, the latency, the gas constants, the admission rule and the expected activity were all fixed in it before the first tick.

## 2. What ran

| branch | mode | learning | ticks | discoveries | tapes | episodes | start digest | end digest | unchanged |
|---|---|---|---|---|---|---|---|---|---|
| `learning` | REPLAY_PAPER | LEARN | 272 | 991 | 617 | 7 | `ba95b60503d6…` | `999d32450a3b…` | False |
| `frozen_reference` | REPLAY_PAPER | FROZEN | 272 | 991 | 617 | 8 | `ba95b60503d6…` | `ba95b60503d6…` | True |

The frozen branch is the **mechanical control, not a scientific comparison**: same data, same `comparison_v1` seeds, same clean checkpoint. Its digest is unchanged (**True**), it counted 8 `SETTLED_FROZEN` settlements and accepted 0 learning updates.

## 3. Admission and rotation

Every launch seen gets a `DISCOVERY` record whether it is admitted or not, so this is the launches that happened and not the launches that survived.

| reason | n |
|---|---|
| `COVERAGE` | 7,172 |
| `ADMITTED` | 4,629 |
| `OBSERVATION_UNUSABLE` | 2,260 |
| `TAPE_OPENED` | 617 |
| `QUOTE_UNSUPPORTED|NO_INITIAL_STATE` | 319 |
| `STATE_INVALID` | 95 |
| `CURVE_COMPLETED` | 88 |
| `NO_INITIAL_STATE` | 55 |

Observation status, per token per tick:

| status | n |
|---|---|
| `OK` | 10,609 |
| `INSUFFICIENT_TAPE` | 2,172 |
| `ROUTE_COMPLETED` | 88 |

Rotation is round-robin on rounds-since-last-presentation and the launch order, blind to price, volume, flow, outcome and ticker. The omitted are recorded `ROTATED`.

## 4. What the decoder decided

Three denominators, never pooled.

| denominator | n | statuses | actions |
|---|---|---|---|
| per candidate evaluation | 348 | {'VALID': 347, 'INVALID_STATE': 1} | {'WAIT': 112, 'BUY': 75, 'NO_RESPONSE': 1, 'SELL': 160} |
| per decision round | 265 | {'NO_USABLE_CANDIDATE': 33, 'VALID': 232} | {'WAIT': 90, 'BUY': 67, 'SELL': 75} |

After the execution constraints:

| outcome of the round | n |
|---|---|
| `HOLD:WAIT` | 77 |
| `blocked_by_fixed_hold` | 72 |
| `HOLD:BUY` | 60 |
| `NO_ORDER:WAIT` | 13 |
| `BUY` | 7 |
| `POLICY_CLOSE_FIXED_HOLD` | 7 |
| `NO_ORDER:SELL` | 3 |

Presentations 2,784, candidate evaluations 348, silent replicates 187 of 2,784, invalid replicates 1.

## 5. Episodes

Expected before the run: at most 9 episodes over about 270 ticks. Observed in `learning`: **7** episodes over 272 ticks.

| # | token | entry block | entry ts | fill (ETH/token) | exit block | exit fill | fees+gas (ETH) | impact (ETH) | net (ETH) | held (s) | confirmation | learning event |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `0x60f73368…` | 60,722,130 | 1789177148 | 1.708e-09 | 60,731,000 | 1.753e-09 | 0.000265756 | 0.000118026 | -0.000006405 | 900 | CONFIRMED | accepted |
| 2 | `0xd41786b0…` | 60,731,590 | 1789178108 | 1.690e-09 | 60,740,446 | 1.690e-09 | 0.000655162 | 0.000111690 | -0.000655162 | 900 | CONFIRMED | accepted |
| 3 | `0x81498680…` | 60,741,037 | 1789179068 | 1.754e-09 | 60,749,919 | 1.749e-09 | 0.000262855 | 0.000113921 | -0.000293538 | 900 | CONFIRMED | accepted |
| 4 | `0x382bb253…` | 60,750,500 | 1789180028 | 1.697e-09 | 60,759,340 | 1.697e-09 | 0.000460162 | 0.000113756 | -0.000460162 | 900 | CONFIRMED | accepted |
| 5 | `0x84129729…` | 60,759,930 | 1789180988 | 1.690e-09 | 60,768,791 | 1.690e-09 | 0.000655162 | 0.000111690 | -0.000655162 | 900 | CONFIRMED | accepted |
| 6 | `0x0188995e…` | 60,769,680 | 1789181978 | 1.690e-09 | 60,778,520 | 1.690e-09 | 0.000263162 | 0.000116337 | -0.000263162 | 900 | CONFIRMED | accepted |
| 7 | `0x56d4a05d…` | 60,780,910 | 1789183118 | 1.690e-09 | 60,789,764 | 1.690e-09 | 0.000655162 | 0.000111690 | -0.000655162 | 900 | CONFIRMED | accepted |

`fees+gas` is the curve's base fee, the creator tax, the snipe tax and the three gas constants; `impact` is the price impact of our own size. `flytrade.execution`'s `FEE_BPS` and `SLIPPAGE_BPS` are not used on this route.

| accounting | value |
|---|---|
| trades | 7 |
| wins / losses / flat | 0 / 7 / 0 |
| gross at reference prices | +0.001025780 |
| − price impact | 0.000797111 |
| − fees, taxes and gas | 0.003217422 |
| = net | -0.002988753 |
| reconciliation residual | -8.674e-19 |

Unresolved positions: **0**. An unresolved position is neither a loss nor a win: the exposure is retained, nothing settles and nothing is taught.

Position marks recorded while holding: **217** ticks, of which 217 could be quoted and 0 could not. A mark is a mark: it is written into the tick record and displayed, and it never reached reinforcement — the learning rule takes the settled net outcome and nothing else.

| mark series (unrealised, ETH) | value |
|---|---|
| minimum | -0.000655162 |
| median | -0.000460162 |
| maximum | -0.000006405 |
| last | -0.000655162 |

Silence and saturation across the declared input range are measured separately in `experiments/d10/probe.json` — 273 nominal patterns, response rate 94.5%, saturated presentations 0, silent replicates 869 of 2,184. There is no PnL in it.

## 6. Restart, determinism and the frozen control

* Mid-run restart at tick 35, after 1 settled episode(s): the in-memory gains were destroyed and rebuilt from the checkpoint and the log. Recovery action `nothing to do`; **gains restored exactly: True**.
* Determinism: the `learning` branch was executed a second time. Event log identical after removing the two fields a second process cannot reproduce by construction (the wall-clock `t` on every line and the absolute checkpoint path): **True** (1,495 lines, `34a74b0b780e…`). Final state digest identical: **True**.

## 7. The four conclusions, separated

### 1. Integration

The integration works. Genuine PONS v2 events collected over HTTP from Robinhood Chain (chain id 4663) were normalised through one path, reconstructed into exact curve state, turned into causal context, encoded onto the olfactory path, measured by the existing k = 8 readout, decoded by the existing decoder, executed on paper against the integer-exact curve quote, settled under a confirmation rule and journalled through the existing recovery machinery. The one link not exercised in this dispatch is **live collection** (`LIVE_PAPER`), whose driver is a documented stub completed by the next dispatch; every other component it needs — the collector, the confirmation rule and the settlement — is already mode-agnostic and is exercised here.

### 2. The brain produced the observed behaviour

Every decision in this run came from the decoder applied once to the aggregate of 8 presentations of the encoded observation, under the `comparison_v1` seed schedule keyed to the observation's content hash and the token's stable id — never to its address spelling or its position in a list. No LLM, classifier, alpha score or technical rule is in the decision path; the admission rule is seven objective facts and the rotation is round-robin. 265 decision rounds were decoded and are in the log with their per-replicate scores.

### 3. Learning updated the declared eligible state

7 settled episode(s) produced 7 accepted normalised update(s), each credited to **the entry decision's own stored k = 8 eligibility trace set** by episode id through the existing `CreditAssigner`. The learned-state digest moved from `ba95b60503d6…` to `999d32450a3b…`. The frozen branch, on the same data and the same seeds, did not move (**True**), which is what makes the movement attributable to the updates and not to the loop.

Credit assignment counters: {"accepted": 7, "open": [], "settled": 7, "rejections": {"EPISODE_MISMATCH": 0, "ALREADY_SETTLED": 0, "UNKNOWN_EPISODE": 0, "TRACE_EXPIRED": 0, "SHAPE_MISMATCH": 0}, "rejections_total": 0}.

### 4. Predictive usefulness

**Not tested — no predictive evaluation was designed for D10.** There is no probe grid, no label, no AUC, no holdout and no cohort split in this wave; `PLAN.md` says so before the run rather than after it. Nothing in this file may be read as evidence for or against predictive skill, and the number of episodes, their sign and their sum are not such evidence.

## 8. Discovery records

991 launches were seen and recorded; 617 of them were native-ETH `pons-v2` launches with a reconstructable initial state and were followed. The rest carry their reason codes and were never followed — they are in the record, not dropped from it.

## 9. What this is not

* Not a prediction test, not a profitability claim, and not a measurement of skill.
* Not live: `LIVE_PAPER` is the next dispatch.
* Not multimodal: the `SensoryEncoder` returns `{"olfactory": Stimulus}` and names `visual`, `taste` and `mechanosensory` as unimplemented extension points routed nowhere.
* Not a market participant: the paper position never changed the recorded public market, and no audience or copying effect is modelled.

