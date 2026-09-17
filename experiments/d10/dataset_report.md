# D10 — the replay dataset, what it contains and what it cannot answer

`data/pons/d10-replay-v1/`, built by `experiments/d10/import_donor.py` on
2026-09-12 from the owner's own PONS radar artifacts, **at zero RPC cost**.
Machine-readable form: `experiments/d10/dataset_report.json` and
`data/pons/d10-replay-v1/MANIFEST.json`.

Nothing in this report is an outcome. No PnL, no label, no post-cutoff return
was computed or read while building it; `tests/d10/test_dataset.py` checks
that no field name in the dataset is outcome-shaped.

## 1. Launches per window — the whole census, not the survivors

| window (UTC) | block range of launches | launches | native ETH | `QUOTE_UNSUPPORTED` |
|---|---|---:|---:|---:|
| 2026-09-08 06:00 → 07:00 | 57,459,402 → 57,495,067 | 487 | 269 | 218 |
| 2026-09-09 05:00 → 06:00 | 58,280,121 → 58,315,789 | 649 | 277 | 372 |
| **total** | | **1,136** | **546** | **590** |

Every launch the factory emitted in each window is in `discovery.json` with
its quote asset and its reason; only the 546 native-ETH ones carry curve
events, because native ETH is the only quote asset this wave prices.

**Quote-asset breakdown of the 590.** They are not one foreign token but many:
the largest single one is `0xd0601ce1…` (101 on 09-08, 222 on 09-09),
then `0x5fc5360d…` (54 / 34), `0x4a0e65a3…` (0 / 31), `0xaf3d76f1…` (10 / 8),
`0xc9a981fe…` (0 / 14), and a long tail. Each is recorded, none is decoded, and
none is compared with an ETH amount as though the units were the same
(amendment section 6).

## 2. Events by kind

19,926 normalised events, **all with status `OK`** — no unmapped topic, no
decode error, no removed log anywhere in the archive.

| kind | count | source |
|---|---:|---|
| `CurveBuy` | 9,418 | curve |
| `CurveSell` | 4,813 | curve |
| `SnipeTaxExempted` | 2,490 | curve |
| `TokenLaunched` | 1,136 | factory |
| `SnipeTaxCharged` | 895 | curve |
| `FeesSwept` | 604 | curve |
| `Initialized` | 546 | curve |
| `CreatorFeeRecipientUpdated` | 15 | curve |
| `BuybackLocked` | 3 | curve |
| `CurveBuyRefunded` | 3 | curve |
| **`CurveCompleted`** | **3** | curve |

**Three graduations in 546 launches**, one on 09-08 and two on 09-09 — inside
the ~62 seconds of coverage each token has. That is the observed count in this
window, not a graduation rate for PONS.

## 3. Coverage per token — the limit that matters

The donor collected the **opening minute** of each launch and stopped:

| | 09-08 | 09-09 |
|---|---:|---:|
| native tokens | 269 | 277 |
| curve events | 9,088 | 9,702 |
| trades (`CurveBuy` + `CurveSell`) | 6,827 | 7,404 |
| median trades per token | 7 | 6 |
| **median age of the last event** | **26 s** | **35 s** |
| 90th percentile | 61 s | 62 s |
| maximum | 62 s | 62 s |
| tokens reaching 60 s | 42 | 58 |
| tokens with ≥ 3 trades | 193 | 177 |
| `CurveCompleted` | 1 | 2 |

The donor's own plan says so: `sampleEndSeconds: 62`.

> **This contradicts two SPEC addenda and must not be worked around.**
> Addendum 14 expects replay episodes at a **15-minute** fixed horizon, and
> addendum 10 admits a token only when `cutoff + latency + 900 s` lies inside
> its coverage. On this dataset **no token satisfies that** — the longest
> coverage is 62 seconds. Replaying a 15-minute hold here is impossible
> without inventing the fourteen minutes that were never collected, which
> amendment section 6 forbids in as many words ("If historical state cannot be
> reconstructed or queried within the budget, report the missing coverage
> rather than fabricating quotes"). The next dispatch has to choose openly
> between a **shorter replay horizon** that fits the evidence, a **new bounded
> collection** that extends it, and running the 15-minute policy **live only**.
> Recorded here, not adapted silently.

## 4. Consistency checks, and their results

Eight checks at import; **all eight passed**.

| check | scope | result |
|---|---|---|
| log ids unique (`blockHash:txHash:logIndex`) | 18,790 curve logs | 0 duplicates |
| every event's block hash has a header | 18,790 | 0 missing |
| every token has a calibration read | 546 | 0 missing |
| every token has a launch-block initial state | 546 | 0 missing |
| every event falls inside a range actually requested, at an address that range asked about | 18,790 | 18,790 covered |
| one head hash across all batches | 575 source files | 1 distinct |
| native census matches the plan's token list | 546 vs 546 | equal |
| no removed logs in the archive | 18,790 | 0 |

**Reconstruction.** All **546 of 546** curves were replayed from their
calibrated launch-block state through their events and reconciled against the
donor's independent on-chain state read at a later block: **546 reconciled, 0
mismatched, 0 failed**, on all four reserve quantities and the graduated flag.

**Settled trades re-priced.** Every trade after the launch block was re-quoted
from the reconstructed pre-trade state:

| | attempted | exact | notes |
|---|---:|---:|---|
| `CurveBuy` | 8,891 | **8,891** | spent, emitted fee (base + snipe), creator tax and tokens out, all four |
| `CurveSell` | 4,813 | **4,813** | quote out, fee, tax |
| snipe-taxed buys | 895 | **895** | `SnipeTaxCharged` amount reproduced by the fourteen-halvings decay |
| snipe-exempt recipients | 743 | — | formula says a tax was due, chain charged none: creator/bundle wallets exempted at launch |
| quote errors | 0 | — | |

The 527 buys not attempted are those in the launch block itself, already
inside the calibrated initial state.

## 5. Feature-scale statistics — 09-08 window only

`experiments/d10/feature_scales.py`, written to
`experiments/d10/feature_scales.json`. Addendum 9 fixes the encoder's scales
from the 09-08 window **before any Pons outcome is looked at**; this is that
measurement. 30-second grid, tokens with ≥ 3 trades, grid points at age ≥ 60 s.

Of 269 native tokens on 09-08: 96 had fewer than 3 trades, 133 never reached
60 seconds of coverage, leaving **40 tokens and 40 grid points** — one per
token, because coverage ends at 62 s.

| feature | n | median &#124;x&#124; | p90 &#124;x&#124; | max &#124;x&#124; |
|---|---:|---:|---:|---:|
| `age` (s) | 40 | 60.0 | 60.0 | 60.0 |
| `ret_30s` | 40 | 0.0909 | 0.5824 | 2.0321 |
| `ret_2m` | 40 | **0** | **0** | **0** |
| `ret_5m` | 40 | **0** | **0** | **0** |
| `flow_imb_2m` | 40 | 0.2442 | 0.7654 | 1.0000 |
| `trade_rate_2m` (per min) | 40 | 40.75 | 92.75 | 151.50 |
| `rv_2m` | 40 | 0.0472 | 0.0671 | 0.0838 |
| `drawdown_5m` | 40 | 0.1791 | 0.6081 | 2.0700 |

**Read the zeros correctly.** `ret_2m` and `ret_5m` are zero **by the
addendum's own rule** — a return window that starts before the launch is zero
— not because prices did not move. With 62 seconds of coverage no 2-minute or
5-minute return exists to measure, so **their scales cannot be set from this
dataset**. `age` is constant at 60 for the same reason, so it carries no
spread here either. Four features are genuinely estimated: `ret_30s`,
`flow_imb_2m`, `trade_rate_2m`, `rv_2m`, and `drawdown_5m` (whose maximum is
taken over the token's whole life when five minutes predate the launch).

**Forty tokens is a thin basis for a fixed scale**, and it is the whole 09-08
window under the stated filter, not a selection. The next dispatch must decide
in the open whether to (a) keep only the estimable features, (b) shorten the
windows to what the data supports, or (c) collect more before fixing scales —
and must not quietly refit scales after seeing an outcome.

Conventions this script declares, because the addendum leaves them open: the
marginal price is `quote_reserve / token_reserve` from the reconstructed state
with the phantom reserve included (never the last trade price, never an
executable price); `flow_imb_2m` uses reserve deltas — a buy's net in, a
sell's gross out; `trade_rate_2m` divides by the nominal two minutes even when
the token is younger, so the scale stays fixed. The canonical implementation
belongs in `flytrade/pons/context.py` in the next dispatch and must reproduce
these definitions exactly.

## 6. What this dataset is, in one paragraph

The complete first minute of 1,136 real PONS launches over two hours on two
days, with every log, every block header and a calibrated curve state per
native-ETH token; internally consistent on eight checks; reconstructed to the
wei on all 546 priceable curves; and re-priced exactly on all 13,704 settled
trades. It supports questions about the opening seconds of a launch. It does
not support a fifteen-minute hold, a graduation rate, or anything about the
09-08 and 09-09 windows other than the hours actually collected — and the two
hours were already examined by the donor for other purposes, so they are not a
virgin holdout.
