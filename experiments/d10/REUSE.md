# D10 — what was reused from the donor, and what "reuse" means here

The amendment's section 2 asks for a reuse table against the owner's other
local project. This is that table, plus the two things the table alone would
not make clear: what kind of reuse actually happened, and what licence
obligations came with it.

## The donor, identified

`~/Documentos/PONS` — the owner's private PONS radar. TypeScript 7 / Node 22 /
PostgreSQL 16 / `viem` 2.56.3 / `zod` 4.5.4.

**There is no commit to cite.** The directory contains a `.git` with branch
`master` and **zero commits**; every file is untracked. Files are therefore
identified below by **sha256 of the bytes read on 2026-09-12**, which is what
the SPEC addenda already assumed ("not a git repository (no commit to cite;
files are identified by sha256)"). The only refinement worth recording is that
a `.git` directory does exist and is empty of history — so "no commit to cite"
is right, and "not a git repository" is loose.

The donor was inspected **read-only**. Its PostgreSQL (port 55432) was not
started; nothing under `~/Documentos/PONS` was executed; no `.env` was read or
copied. Its RPC credential is read at runtime **by key name only**, from the
file and key the config names, exactly as the donor reads it.

## What reuse means in this wave

Flytrade is a Python project whose runtime dependencies are numpy, scipy,
pandas and pyarrow. The donor is a TypeScript application with a PostgreSQL
schema and a `viem` dependency. "Adapt the donor's EVM collector" therefore
**cannot** mean importing or running its code, and it did not. Reuse here is
three specific things and no others:

1. **Its raw evidence, imported** — the hash-anchored logs, headers and state
   reads it already collected, pushed through Flytrade's own normalisation
   path and written to `data/pons/d10-replay-v1/` at zero RPC cost.
2. **Its manifests, ABIs, contract evidence and test fixtures, copied** — with
   sha256 and origin path, into `experiments/d10/evidence/`.
3. **Its semantics, ported and proven against its own fixtures** — the request
   budget, the method allowlist, the durable cursor and reorg discipline, the
   log id, and the integer-exact curve quote. Each port is a *re-expression in
   Python*, checked against the donor's captured numbers where captured
   numbers exist.

No TypeScript runs. No second copy of the donor's database exists. No line of
its source is vendored. Where the table below says "port", it means a Python
function written from the donor's source and the frozen Solidity, whose output
is then compared with the donor's recorded output — not a translation trusted
on sight.

## The table

| component | actual source (path + sha256, "no git") | reuse/adapt/reject | reason | tests |
|---|---|---|---|---|
| RPC client, method allowlist, 15 s timeout, no retry, no fallback, 429/quota halt | `src/rpc.ts` `5536c3d831dcecd563ac14e59db783a4f31f6a7e2810b80a4b5c1bb0031b1166` (no git) | **port** → `flytrade/pons/rpc.py` | Same discipline, different runtime. Our allowlist is **narrower**: the donor allows `eth_getBalance` and `eth_getTransactionReceipt`; this wave needs neither, so six methods, not eight. | `tests/d10/test_rpc.py` (5 signing methods refused before a socket; masking; 429; quota; envelope id; log-filter check; no retry) |
| Request budget: per-run and per-day caps, attempts not successes, halt persisted | `src/rpc.ts` (above) + `src/config.ts` `a9a6144b4b59002a9cdc925bfd82084311d9d2352f0697b4ce9dc0295812f191` + `sql/001_init.sql` `0a681e99db6767775701be55f17675c0a50f86bfd737467743b396a481df6435` (`rpc_usage`) | **adapt** → `flytrade/pons/budget.py` | The donor's cap lives in PostgreSQL; ours lives in an atomically replaced JSON file, because this project has no database. **Added**: a wave cap, and Chainstack archive weighting (2 units at ≥ 127 blocks behind tip), which the donor does not model. | `tests/d10/test_rpc.py::test_archive_reads_are_weighted_at_two_units`, `::test_a_restart_does_not_reset_the_ledger`, `::test_a_cap_stops_before_the_call_and_says_which` |
| Event ABI declarations (v1 factory, v2 factory, curve, V3 pool) | `src/adapters.ts` `c63cae8659b7cd2ac2a5f374a08e5f6294edae2ce3855f88ec8f535c1de46026` (no git) | **port** → `flytrade/pons/abi.py` | The donor decodes with `viem`; we decode by hand (topics + 32-byte words) because every supported event is static and a 300-line decoder is cheaper than an ABI library. Its strict shape check is reproduced verbatim in behaviour. | `tests/d10/test_abi.py` (8 pinned topic0 recomputed by keccak; extra topics / trailing data / truncation / dirty address word refused; v1 and V3 recognised and refused) |
| ABI provenance (topic0 ↔ declaration ↔ source commit) | `config/event-evidence.json` → `experiments/d10/evidence/event-evidence.json` `07361fc75f1f008cd9508b2fb432ad8d91e5d08b91a31af66aab9a7477b7790d` | **reuse (copied)** | It pins PONS source commit `8b9bf371030279133017b5c1b713823f5889c5d2` and Sourcify factory match `43289536`. Copying it keeps the provenance with the code. | `tests/d10/test_abi.py::test_every_pinned_topic0_is_reproduced_from_its_signature` |
| Deployment manifest (chain 4663, factories, expected code hashes) | `config/deployments.json` → `experiments/d10/evidence/deployments.json` `34db176fa34fe4d3b548fb9581b189310dc1b5db33bf3a9b286e82ddc4e4c064`; schema in `src/types.ts` `c75a8e535ce40539d780dcffff51881b2d20fb7b7cc1073cc5a9500ca6c04ee1` | **adapt** → `experiments/d10/deployments.json` + `flytrade/pons/manifest.py` | Same two factories and the same two code hashes; **extended** with the legacy v1 factory, the V4 post-graduation hook and quoter, an explicit `supported` flag, a required `reason` on every unsupported entry, and native-ETH-only quote assets. | `tests/d10/test_manifest.py` (7 refusals) |
| Curve quote: `quoteCurveBuy` / `quoteCurveSell` / round trip | `src/curve-quotes.ts` `5a68fed042853ba0386292baa52e968646fab6b8838e04c6155c8570f804c3fc`, itself a port of `docs/evidence/PonsV2BondingCurveMath.sol` `e4486d95391daf7b3925219766307d3c7c78db80304bd824241f379146e59e58` and `PonsV2BondingCurve.sourcify.sol` `9e19cebed3b4ac659b9e3406fe3f8139ff8d59eb1da6e76bd9cbab915cd12684` | **port** → `flytrade/pons/curve.py` | Fees, creator tax, capped and time-decaying snipe tax, partial fill with refund, `QUOTE_EXCEEDS_REAL_RESERVE`, dust. Python `int` is the `uint256`; the one expression that can go negative truncates toward zero as BigInt does. | `tests/d10/test_curve.py` — **3 of 3 fixture rows reproduced field for field** against `pons-quotes-curve.json`; `tests/d10/test_dataset.py` — real settled trades re-priced |
| Curve state reconstructed from events | `src/curve-simulation.ts` `695940ee63a6a38980962780b9e3223e74248d4de5020767afcea88a68eb69d6` (`replayCurve`, `snipeAt`) | **port** → `flytrade/pons/curve.py::CurveReconstruction` | The donor's rules, with two things made explicit: `FeesSwept` moves nothing while `BuybackLocked` moves both sides (verified against `_sweepFees` in the frozen source), and an unknown event kind raises rather than silently doing nothing. | `tests/d10/test_curve.py` (reserve deltas, constant-product refusal, completion, unknown kind) + the 546-token reconciliation |
| Durable cursor, chunking, reorg refusal, `logId`, dedup | `src/ingest.ts` `6114f8994c28c1034992c8782660e3953046f29bb52ffcdecce37cd839261177`, `src/store.ts` `8dd8f3d810e2037ab3e14083a989a1d5bfa027ee112fae932b207e7dfc25d0b8`, `sql/001_init.sql` (above), `src/types.ts` (`logId`) | **adapt** → `flytrade/pons/storage.py` + `collector.py` | `logId = blockHash:txHash:logIndex` and the 25-block chunk are the donor's. **Changed**: the donor *refuses* a `removed` log because it takes snapshots; a live cursor must *accept* it, orphan what it invalidates and rewind. Cursor and events are JSONL + one atomically replaced pointer instead of a PostgreSQL transaction. | `tests/d10/test_collector.py` (gap, duplicate, out-of-order, removed, two-block reorg, restart mid-tick, budget stop with cursor persisted) |
| Replay-is-decode-only discipline | `src/replay.ts` `5166cf1524e556c3e024ff1ffde58337bd6fb1b9dee66e3cb4eb8ddc09f52a0b` | **reuse (idea)** | "Pure decoding: no transport, no secret loading, no current on-chain reads, no timestamp replacement." The import obeys it literally: `import_donor.py` opens no socket. | `tests/d10/test_dataset.py::test_the_dataset_cost_no_requests`, `::test_replay_goes_through_the_same_normalisation_as_live` |
| Paper position mechanics (`ownNet`, exit at the state the buy left) | `src/paper-live.ts` `6ac7e9e9345c2cc2614e2fe8b3858b7814fbec87a471e40563b26eefab63963e` | **port** → `flytrade/pons/paper.py` (dispatch 2) | The `ownNet` idea — the position's own reserve delta carried so its exit sees its own impact plus the external flow that actually happened. **Changed**: the costs go into `Fill.fee` and the impact into the reference/fill price gap, so `flytrade.execution.Account`'s existing three-way reconciliation holds unchanged; and an exit that cannot be priced is `UNRESOLVED`, never a loss. | `tests/d10/test_paper.py` (latency, costs, the own-delta carry, the identity, the three unavailable exits, the refused entry) |
| Collected raw evidence: 546 native launches, two windows | `artifacts/curve-simulation/plan.json` `779b483fbd442ad9a8bdb8173a6e694d0dcc8348d0ab17d14978ec9a380a7aef` + 28 `batch-*.json` + 546 `initial-*.json` | **reuse (imported)** | The wave's replay dataset. 575 source files, each sha256'd into `data/pons/d10-replay-v1/MANIFEST.json`. | `tests/d10/test_dataset.py` (digests, 8 consistency checks, 546/546 reconciled) |
| Launch windows and the full launch census | `artifacts/micro-cohort/day-2026-09-08.json`, `artifacts/micro-cohort-day9/day-2026-09-09.json`, plus `artifacts/micro-features*/batch-*.json` for the launch headers | **reuse (imported)** | Window bounds and **all 1,136** launches, so the dataset is not the 546 survivors. `micro-features` was added beyond the addendum's list because it is the only place carrying a launch **header** for the non-native launches; declared as a deviation. | `tests/d10/test_dataset.py::test_the_census_is_not_built_from_survivors` |
| Gas calibration medians (40 buy + 40 sell receipts) | `artifacts/curve-simulation/gas.json` `23e3df06cc2a986734b7ca661107d0397a15b5f77ff6db0e30ac7d2d1b726daf`, plan `1cad6e33dfe62701596987ecbffc335959cd1fdc8a560857d9745a1f6d576015` | **reuse (three constants, in `config.json`)** | Median scenario, wei: **buy 26,513,686,360,000 · sell 21,543,833,760,000 · approval 16,104,600,000,000** (approval is a 60,000-gas *assumption*, not a receipt). p95: 63,851,872,400,000 / 64,821,012,144,000 / 16,381,680,000,000. These are the three constants addendum 12 wants in `config.json`, and they are in it. | `tests/d10/test_paper.py::test_gas_is_charged_on_both_legs_and_the_approval_once` |
| PostgreSQL schema, panel/server, social research, V4 quoter path, cluster research | `src/server.ts`, `src/social*.ts`, `src/v4*.ts`, `src/clusters.ts`, `sql/002-006` | **reject** | Out of scope. The V4 route is UNSUPPORTED this wave by addenda correction (d); social text is display metadata and explicitly not a predictive input (amendment section 1); a web panel duplicates the existing observer. | — |
| `PonsTickMath.sol` (GPL-2.0-or-later) | upstream `ponsfamily` repository | **reject** | GPL, and only needed for the Uniswap V3/V4 routes this wave does not price. Never copied, ported or linked. | `NOTICE.md` |

## Files copied into `experiments/d10/evidence/`

Each is byte-identical to the donor's; the sha256 is of the copy, and it
matches the origin.

| file | origin under `~/Documentos/PONS/` | sha256 |
|---|---|---|
| `deployments.json` | `config/deployments.json` | `34db176fa34fe4d3b548fb9581b189310dc1b5db33bf3a9b286e82ddc4e4c064` |
| `event-evidence.json` | `config/event-evidence.json` | `07361fc75f1f008cd9508b2fb432ad8d91e5d08b91a31af66aab9a7477b7790d` |
| `pons-v2-read-abi.json` | `config/pons-v2-read-abi.json` | `226b9e1a8bb7d91a039a96d235df62d0689b93748f484f73406d371fa1e8ba4c` |
| `quote-deployments.json` | `config/quote-deployments.json` | `78981a14212dce4fbd6b2b479eee52014a6fd327cfbcb0e50b77bd15282d7435` |
| `PonsV2BondingCurve.sourcify.sol` | `docs/evidence/PonsV2BondingCurve.sourcify.sol` | `9e19cebed3b4ac659b9e3406fe3f8139ff8d59eb1da6e76bd9cbab915cd12684` |
| `PonsV2BondingCurveMath.sol` | `docs/evidence/PonsV2BondingCurveMath.sol` | `e4486d95391daf7b3925219766307d3c7c78db80304bd824241f379146e59e58` |
| `pons-quotes-curve.json` | `test/fixtures/pons-quotes-curve.json` | `4e6c80b6a9b8f10f1f981f71e3842c75d3ce67da5ad97b03d9448a881e04761b` |
| `pons-quotes-transition.json` | `test/fixtures/pons-quotes-transition.json` | `fc276f1352e172f9cec4314211f0cf102ca5ad36e6a581fc0e2d520768a82598` |
| `pons-v2-launch.json` | `test/fixtures/pons-v2-launch.json` | `b0532c41252468292b56dc30d907bd9bd0896acd7ac2625f287d9e3dced1b34a` |
| `pons-v2-graduation.json` | `test/fixtures/pons-v2-graduation.json` | `685602fe10d0318c4993baaa2e3d4a33ca12b6d15a55c04443cd94e2314cc6b1` |
| `pons-sample-20260909.json` | `test/fixtures/pons-sample-20260909.json` | `d4dd74a2bce7e40502212234e651781bf308021347eaacb9e960607e3f86f192` |

The two `.sol` hashes match the values the donor itself recorded in
`config/quote-deployments.json`, which is an independent check that the copies
are the frozen sources and not something later.

The 575 donor artifact files read by `import_donor.py` are not copied; their
sha256 values are listed in `data/pons/d10-replay-v1/MANIFEST.json`.

## Licence obligations

* **PONS first-party contracts — MIT.** `PonsV2BondingCurve.sourcify.sol` and
  `PonsV2BondingCurveMath.sol` are copied verbatim and their arithmetic is
  ported into `flytrade/pons/curve.py`. MIT requires the copyright and
  permission notice to travel with any copy or substantial portion.
  Attribution added to `NOTICE.md`; the SPDX headers inside the files are
  preserved and must not be stripped.
* **`PonsTickMath.sol` — GPL-2.0-or-later.** Not used, not copied, not ported,
  not linked. It belongs to the Uniswap V3/V4 routes, which this wave records
  as UNSUPPORTED.
* **`pycryptodome` — BSD-2-Clause / public domain dual.** Added as an optional
  `chain` dependency for keccak-256 only. No obligation beyond keeping its own
  notice, which ships inside the package.
* **The donor's own code — no licence file.** It is the owner's, it is not
  published, and nothing from it is vendored: what crossed the boundary is
  configuration, evidence, fixtures and ported semantics.
* **The chain data — none.** Public on-chain events and state. The Kibot
  agreement governs `data/market/` and has nothing to do with this dataset.

## What dispatch 2 added to this table

Two rows above moved from "deferred" to "done": the paper mechanics and the
gas constants. Nothing else in the table changed, and no new donor file was
read — the bounded backfill of reviewer decision 1
(`data/pons/d10-backfill-v1`) is a **new collection from the endpoint**, not
donor evidence, and its provenance is in `data/MANIFEST.md` rather than here.

One donor-derived fact was promoted from evidence to arithmetic:
`flytrade/pons/seed.py` records that a pinned-config launch's pre-trade curve
state is a constant plus the creator tax, measured on **546 of 546** of the
donor's calibrations, and that the creator tax is uniquely recoverable from one
trade (489 of the 489 tokens that traded, 0 wrong). That is what let the
backfill derive 614 of 617 initial states instead of buying an `eth_call` for
each.

## What dispatch 3 added to this table

**Nothing, and that is the finding.** Stage E — the live driver, the worker,
the health block and the live exercise — read no donor file, copied none and
ported none. Every donor-derived component it needed was already in the table
and was exercised on the wire rather than changed: the RPC client and its
allowlist, the budget and its ledger, the durable cursor and the reorg rule,
the integer-exact curve quote, the `ownNet` carry of `paper-live.ts`, and the
event ABI.

One row is worth re-reading in the live light. `flytrade/pons/seed.py` — the
arithmetic that recovers a curve's launch state from its config and its first
trade, measured on 546 of 546 donor calibrations — is what makes a **live**
curve free as well as a backfilled one: the live driver holds a launch until
its own first trade pins the creator tax, so a token that never trades and can
never be admitted is never bought a state read. In the live hour it resolved
**676 of the 677 followed launches** from their own first trade; the declared
`eth_call` fallback was needed **once**, and that single call is the only
`eth_call` in the run's ledger.
