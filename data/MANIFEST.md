# Data manifest — MaleCNS connectome v1.0

Downloaded 2026-09-11 for Phase 0.5. **The files themselves are never
committed** (`.gitignore`: `data/*/`, `*.feather`, `*.npz`). This manifest is
the committed record; anyone can reproduce the download from it and check the
hashes.

## Source

Links taken from the dataset's own download page,
<https://male-cns.janelia.org/download/>, which lists the flat-connectome
tables under `gs://flyem-male-cns/v1.0/connectome-data/flat-connectome/`.
HTTPS base URL:

```
https://storage.googleapis.com/flyem-male-cns/v1.0/connectome-data/flat-connectome/
```

Downloaded with `curl -L -C - --retry 5 -o <file> <url>`. Local directory:
`data/malecns-v1.0/`.

## The three files

| file | bytes | sha256 |
|---|---:|---|
| `body-annotations-male-cns-v1.0-minconf-0.5.feather` | 14,483,314 | `2177e246113e4cfbf1e7772ec37c6da1955ff22e8063d0b1f833101f99a9a3b2` |
| `body-neurotransmitters-male-cns-v1.0.feather` | 43,282,834 | `95c9289220663abeb3409f3ad9e5a7f8a53f8093f5139d15502cd08da8879621` |
| `connectome-weights-male-cns-v1.0-minconf-0.5.feather` | 1,051,241,946 | `e35da783d1c686b2b58b3b87cd6a403ae43bfcfba8bff28e08ef752c1a56afc1` |

Total 1,109,008,094 bytes (1.03 GiB).

**Integrity.** The download page publishes approximate sizes only (13 MB,
42 MB, 1.1 GB) and **no checksums**, so there is nothing upstream to verify
the sha256 against. What was verified instead: a separate `HEAD` request per
file returned a `Content-Length` identical to the bytes on disk for all three
(14,483,314 / 43,282,834 / 1,051,241,946), and all three parse as valid Arrow
Feather with the expected schema (below). The sha256 values above are ours, so
that a later re-download can be compared against this snapshot.

Nothing else was downloaded: no EM volumes, no meshes, no skeletons, no neo4j
database, no `syn-points`, `syn-partners`, `tbar-neurotransmitters` or
`body-stats` table.

## Schema, as validated before the graph build

| file | rows | columns used by the build |
|---|---:|---|
| annotations | 211,577 | `bodyId`, `status`, `statusLabel`, `type`, `flywireType`, `instance`, `superclass`, `subclass`, `class`, `receptorType`, `fruDsx`, `somaSide`, `rootSide`, `somaNeuromere`, `assignedOlHex1/2`, `hemibrainType` (36 columns present) |
| neurotransmitters | 1,835,518 | `body` (int64), `consensus_nt` (string) (10 columns present) |
| weights | 151,856,684 | `body_pre` (int64), `body_post` (int64), `weight` (int64) — exactly 3 columns |

Every column `upstream/build_graph.py` reads is present. Upstream expects the
files under the short names `connectome-weights.feather`,
`body-annotations.feather`, `body-neurotransmitters.feather`; we read the
published long names directly from `flytrade/graph.py` and do not rename or
copy them.

## Licence and attribution

The MaleCNS dataset is licensed **CC-BY 4.0**
(<https://creativecommons.org/licenses/by/4.0/>), as stated on the download
page: *"The Male CNS is licensed under CC-BY."*

Attribution, in the download page's own words:

> This project is a collaboration between FlyEM (HHMI Janelia), the University
> of Cambridge (Dept. of Zoology), the MRC Laboratory of Molecular Biology, and
> Google Research.

The CC-BY obligation travels with the data and with anything derived from it,
including the matrices built in `data/malecns-v1.0/*.npz`. See `NOTICE.md`.

## Upstream pin (unchanged by this wave)

`upstream/` remains the vendored, unmodified clone of
<https://github.com/fruitflydev/flycoinrh> at commit

```
5aab4e7895a1f5930319bf3bde8010b350a163a2
```

tree `5b8a6c70b40e1faa42eb21daf6d154e9d73b228d`, MIT licensed. Blob-level
manifest in `docs/UPSTREAM_MANIFEST.txt`.

## Derived artefacts (also gitignored)

Built by `flytrade/graph.py` into `data/malecns-v1.0/`:

| file | what |
|---|---|
| `graph.npz` | fast signed weights, upstream's exact key set, loadable by `flysim.FlyBrain` |
| `graph_mod.npz` | unsigned dopaminergic synapse counts, `[post, pre]`, same body index |
| `graph_anat.npz` | non-negative anatomical synapse counts, `[post, pre]`, same body index |
| `annotations.npz` | per-neuron annotation columns aligned to the same body index |
| `build_report.json` | the counts printed by the build |

Their hashes are in `build_report.json` and quoted in `docs/ARCHITECTURE.md`;
the checkpoint format in `flytrade/state.py` stores `graph.npz`'s sha256 so a
learned-weight file can never be loaded against a different graph.

## Datasets used by the experiments — labels

*(This paragraph describes the repository as of the k = 8 wave, D4. The D6
wave below downloaded market data for the first time; the statement is kept
with its correction rather than rewritten.)*

At D4 the connectome above was the only downloaded dataset in the repository:
**no market data had ever been downloaded and there was no `data/market/`
directory**; `flytrade/market.py` documented the local CSV format it *would*
read, and that path was exercised only by a round-trip test that writes its own
file. **That changed at D6**: `data/market/` now holds the two Kibot samples
recorded in the second manifest below, labelled `HISTORICAL_MARKET`, still
gitignored and still absent from every committed test.

Every market-shaped dataset any experiment has used is therefore **SYNTHETIC**,
generated by `flytrade.market.synthetic_series` from a declared integer seed, or
a nominal feature vector placed at a declared point of the encoder's input
range. `experiments/k8_readout/results.md` §6 lists each one with its generator
and seeds, and resolves what the Phase One report's phrase "real observations"
referred to.

---

# Data manifest — Kibot free intraday samples (HISTORICAL_MARKET)

Downloaded 2026-09-11 for the D6 historical-market wave, under the owner's
authorisation in `docs/SPEC.md` §D6. **The files themselves are never
committed** (`.gitignore`: `data/*/`). They are internal-use inputs, not
repository fixtures and not files to redistribute with the application: no
committed test reads them, and the observer serves only the run's own event
log, never a raw vendor file.

This dataset is labelled **`HISTORICAL_MARKET`** and is kept distinct from
every `SYNTHETIC` fixture in the repository. The two never mix in one run.

## Source page, validated before downloading

<https://www.kibot.com/free-historical-intraday-data.html>, fetched
2026-09-11T11:52Z (HTTP 200, 35,957 bytes). The page's own markup still
attaches the two links named in the amendment to the **unadjusted** samples of
the two intended instruments; both were checked against the anchor text, not
guessed from the URL:

```html
<span class="free-symbol">IBM</span> … International Business Machines
  <a … href="https://api.kibot.com/?get=XHuKFdi7" …>Adjusted</a>
  <a … href="https://api.kibot.com/?get=e4Vuqcxk" …>Unadjusted</a>
<span class="free-symbol">OIH</span> … Market Vectors Oil Services ETF
  <a … href="https://api.kibot.com/?get=HaJS3GR4" …>Adjusted</a>
  <a … href="https://api.kibot.com/?get=NaatWNJD" …>Unadjusted</a>
```

`e4Vuqcxk` → IBM unadjusted and `NaatWNJD` → OIH unadjusted, exactly as the
amendment records them. No substitution was made and no adjusted file was
downloaded. The four other free samples on that page (IVE, WDC tick and
bid/ask) were **not** downloaded. No account was created, no paid product was
ordered, and no API key exists anywhere in this repository.

## The vendor's own words on the two semantics that matter

From the format reference,
<https://www.kibot.com/file-format/data-format-reference.html>, fetched
2026-09-11T11:52Z (HTTP 200, 39,599 bytes):

> **Timestamp convention matters.** For bar data (second, minute, daily), the
> timestamp represents the **bar open time**, the moment the bar begins, not
> when it closes. A bar stamped `10:30:00` on 1-minute data covers the period
> from 10:30:00 through 10:30:59. This convention is consistent across all
> Kibot standard formats […]

> **Periods with no activity.** If no trades occur during a given interval,
> Kibot simply omits the bar rather than emitting a zero-volume placeholder.
> The next row in the file is the next bar with actual activity, and any gap
> between its timestamp and the previous row's timestamp corresponds to time
> during which nothing was reported. […] Code that iterates Kibot files by
> wall-clock time, rather than by row, must reconstruct the empty intervals
> itself.

Two more the importer depends on:

> **Timestamps:** Eastern Time (ET) by default, EST (UTC-5) or EDT (UTC-4)
> depending on the date […] **Header row:** None. Data begins on the first
> line.

> Very small values are written in scientific notation. A price recorded as
> `1E-06` stands for `0.000001`.

And from the source page, on what the free intraday samples contain:

> Seven columns: `Date` and `Time` as separate fields, then OHLC and Volume.
> One row per minute, **regular session only (09:30 to 16:00 ET)**. Pre-market
> and after-hours bars are excluded from the free intraday samples […]

The consequence for this wave, in one line: **a missing minute is the vendor's
documented behaviour, not corruption**, and "five rows later" is not "five
minutes later".

## The two files

Downloaded with `curl -sS -L`, retrieved **2026-09-11T11:52:17Z** (IBM) and
**2026-09-11T11:52:22Z** (OIH). Local directory `data/market/`.

| | IBM | OIH |
|---|---|---|
| URL | `https://api.kibot.com/?get=e4Vuqcxk` | `https://api.kibot.com/?get=NaatWNJD` |
| instrument | International Business Machines, US equity | Market Vectors Oil Services ETF |
| adjustment status | **unadjusted** (page anchor text) | **unadjusted** (page anchor text) |
| local file | `IBM_1min_unadjusted.txt` | `OIH_1min_unadjusted.txt` |
| bytes | 1,243,177 | 1,027,065 |
| sha256 | `b1ace385f069764c6030f1c292595548166c2478e0390284f1875507e2673db9` | `12311994a99525d4f0f4aaea3a17458192f7020a9775409206fd93b805da9dad` |
| rows | 23,777 | 20,373 |
| first bar (ET, bar open) | 2026-06-15 09:30 | 2026-06-15 09:30 |
| last bar (ET, bar open) | 2026-09-10 15:59 | 2026-09-10 15:59 |
| trading days in file | 61 | 61 |
| rows outside 09:30 ≤ t < 16:00 ET | **0** | **0** |
| extended-hours bars present | **no** | **no** |
| duplicate timestamps | 0 | 0 |
| strictly increasing | yes | yes |
| malformed rows | 0 | 0 |
| non-positive prices | 0 | 0 |
| rows violating high ≥ max(o,c) ≥ min(o,c) ≥ low | 0 | 0 |
| zero-volume rows | 0 | 0 |
| price range in file | 199.19 – 311.80 | 356.76 – 440.105 |

Both responses carried `content-disposition: attachment; filename=IBM.txt` /
`OIH.txt` and the header `x-kibot-data-through: 09/10/2026`, which agrees with
the last row of each file. The vendor publishes no checksums for the free
samples, so — as with the connectome above — the sha256 values are ours, so
that a later re-download can be compared against this snapshot. The raw
response headers are kept beside each file as `<SYM>_headers.txt`, also
gitignored.

**Format observed, against the documentation.** Headerless, comma-delimited,
seven fields `Date,Time,Open,High,Low,Close,Volume`; `Date` as `MM/DD/YYYY`;
`Time` as **`HH:MM`** in both files, not the `HH:MM:SS` the format reference
shows for minute bars — the importer accepts both and records which it saw. No
exponent-form prices appear in either file; the importer parses them anyway.

## Coverage inside the requested window

Requested window, inclusive: **2026-08-03 → 2026-09-04**. It lies wholly
inside both files, so no date was shifted and no partition was moved. 25
regular-session trading days, and 25 in each file — no session is missing
entirely from either instrument. There is no US market holiday inside the
window (Labor Day 2026 falls on 09-07, three days after it ends).

A complete regular session is 390 one-minute bars (09:30 … 15:59 inclusive).

| | IBM | OIH |
|---|--:|--:|
| trading days in window | 25 | 25 |
| bars in window | 9,738 | 7,928 |
| complete-session maximum | 9,750 | 9,750 |
| **missing minutes** | **12** (0.12 %) | **1,822** (18.7 %) |
| best day | 390/390 | 360/390 (08-10) |
| worst day | 387/390 (08-25) | 244/390 (08-07) |

Per day, bars present out of 390:

| date | partition | IBM | OIH |
|---|---|--:|--:|
| 2026-08-03 | WARMUP | 390 | 337 |
| 2026-08-04 | WARMUP | 390 | 325 |
| 2026-08-05 | WARMUP | 390 | 335 |
| 2026-08-06 | WARMUP | 390 | 306 |
| 2026-08-07 | WARMUP | 389 | 244 |
| 2026-08-10 | WARMUP | 390 | 360 |
| 2026-08-11 | WARMUP | 389 | 338 |
| 2026-08-12 | WARMUP | 390 | 273 |
| 2026-08-13 | WARMUP | 390 | 277 |
| 2026-08-14 | WARMUP | 389 | 306 |
| 2026-08-17 | LEARNING | 390 | 353 |
| 2026-08-18 | LEARNING | 390 | 282 |
| 2026-08-19 | LEARNING | 390 | 314 |
| 2026-08-20 | LEARNING | 389 | 345 |
| 2026-08-21 | LEARNING | 389 | 323 |
| 2026-08-24 | LEARNING | 390 | 326 |
| 2026-08-25 | LEARNING | 387 | 280 |
| 2026-08-26 | LEARNING | 390 | 302 |
| 2026-08-27 | LEARNING | 390 | 330 |
| 2026-08-28 | LEARNING | 390 | 319 |
| 2026-08-31 | FROZEN | 389 | 349 |
| 2026-09-01 | FROZEN | 388 | 350 |
| 2026-09-02 | FROZEN | 389 | 321 |
| 2026-09-03 | FROZEN | 390 | 325 |
| 2026-09-04 | FROZEN | 390 | 308 |

IBM is nearly complete. **OIH is not**, and that is the vendor's documented
omission of minutes without reported trades, visible in a sector ETF whose
minute volume is often in the hundreds of shares. It is reported here, used as
it is, and never filled in.

## Licence and use

The Kibot free samples are offered without registration for format
verification. They are treated here as **internal-use inputs**: gitignored,
never redistributed, never served by the observer, never committed as test
fixtures. The committed tests run on vendor-*shaped* fixtures generated by
`tests/historical/make_fixtures.py`, which contains no vendor data.

## Two instruments now, six supported

The run uses exactly the two real instruments the amendment authorises. The
loop's configurable capacity for six is retained and unchanged; no series is
duplicated, renamed, resampled or synthesised to manufacture a sixth
historical instrument.

## Coverage inside the D7 window — IBM only

Appended for the D7 wave (`docs/SPEC.md`, D7 canonical amendment, Fable
addendum 11: *coverage first, dates never move*). **No file was downloaded for
D7.** This is the same `IBM_1min_unadjusted.txt` recorded above, re-read from
disk and re-hashed before the table was written:

```
sha256  b1ace385f069764c6030f1c292595548166c2478e0390284f1875507e2673db9
rows    23,777      first bar 2026-06-15 09:30 ET      last bar 2026-09-10 15:59 ET
```

OIH is excluded from D7 by the amendment (§1) because of the availability
problem reported in the previous window, not because of its returns. It stays
in the repository and in `data/market/`, untouched.

Requested window, inclusive: **2026-06-15 → 2026-07-31**. It lies wholly
inside the file, so no date was shifted and no partition was moved. A complete
regular session is 390 one-minute bars (09:30 … 15:59 inclusive).

**Scheduled sessions.** 35 weekdays fall in the window; **33** are regular
sessions and all 33 are present in the file. The two weekdays absent from it
are **2026-06-19** (Juneteenth, observed Friday) and **2026-07-03**
(Independence Day, observed Friday — 2026-07-04 is a Saturday). Both are NYSE
holidays, both are named in the amendment, and neither is a missing session:
the amendment's counts — 13 WARMUP, 10 LEARNING, 10 FROZEN — are exactly what
the file contains.

**Early closes: none.** Every one of the 33 sessions has its first bar at
09:30 and its last bar at 15:59.

| | WARMUP | LEARNING | FROZEN | window |
|---|--:|--:|--:|--:|
| dates | 06-15 → 07-02 | 07-06 → 07-17 | 07-20 → 07-31 | 06-15 → 07-31 |
| sessions | 13 | 10 | 10 | 33 |
| bars present | 5,070 | 3,899 | 3,900 | 12,869 |
| complete-session maximum | 5,070 | 3,900 | 3,900 | 12,870 |
| **missing minutes** | **0** | **1** | **0** | **1** (0.008 %) |
| worst session, bars/390 | 390 | 389 (07-10) | 390 | 389 |

The one missing minute is **2026-07-10 13:06 ET**. Every session in the window
is at 100.0 % or 99.74 % of its scheduled bars, so all 13 WARMUP sessions clear
the amendment's 95 % data-quality bar by a wide margin; the qualifying count is
decided by the committed D7 protocol, not here.

Per session, bars present out of 390:

| date | partition | bars | missing | first bar | last bar | early close |
|---|---|--:|--:|---|---|---|
| 2026-06-15 | WARMUP | 390 | 0 | 09:30 | 15:59 | no |
| 2026-06-16 | WARMUP | 390 | 0 | 09:30 | 15:59 | no |
| 2026-06-17 | WARMUP | 390 | 0 | 09:30 | 15:59 | no |
| 2026-06-18 | WARMUP | 390 | 0 | 09:30 | 15:59 | no |
| 2026-06-22 | WARMUP | 390 | 0 | 09:30 | 15:59 | no |
| 2026-06-23 | WARMUP | 390 | 0 | 09:30 | 15:59 | no |
| 2026-06-24 | WARMUP | 390 | 0 | 09:30 | 15:59 | no |
| 2026-06-25 | WARMUP | 390 | 0 | 09:30 | 15:59 | no |
| 2026-06-26 | WARMUP | 390 | 0 | 09:30 | 15:59 | no |
| 2026-06-29 | WARMUP | 390 | 0 | 09:30 | 15:59 | no |
| 2026-06-30 | WARMUP | 390 | 0 | 09:30 | 15:59 | no |
| 2026-07-01 | WARMUP | 390 | 0 | 09:30 | 15:59 | no |
| 2026-07-02 | WARMUP | 390 | 0 | 09:30 | 15:59 | no |
| 2026-07-06 | LEARNING | 390 | 0 | 09:30 | 15:59 | no |
| 2026-07-07 | LEARNING | 390 | 0 | 09:30 | 15:59 | no |
| 2026-07-08 | LEARNING | 390 | 0 | 09:30 | 15:59 | no |
| 2026-07-09 | LEARNING | 390 | 0 | 09:30 | 15:59 | no |
| 2026-07-10 | LEARNING | 389 | 1 | 09:30 | 15:59 | no |
| 2026-07-13 | LEARNING | 390 | 0 | 09:30 | 15:59 | no |
| 2026-07-14 | LEARNING | 390 | 0 | 09:30 | 15:59 | no |
| 2026-07-15 | LEARNING | 390 | 0 | 09:30 | 15:59 | no |
| 2026-07-16 | LEARNING | 390 | 0 | 09:30 | 15:59 | no |
| 2026-07-17 | LEARNING | 390 | 0 | 09:30 | 15:59 | no |
| 2026-07-20 | FROZEN | 390 | 0 | 09:30 | 15:59 | no |
| 2026-07-21 | FROZEN | 390 | 0 | 09:30 | 15:59 | no |
| 2026-07-22 | FROZEN | 390 | 0 | 09:30 | 15:59 | no |
| 2026-07-23 | FROZEN | 390 | 0 | 09:30 | 15:59 | no |
| 2026-07-24 | FROZEN | 390 | 0 | 09:30 | 15:59 | no |
| 2026-07-27 | FROZEN | 390 | 0 | 09:30 | 15:59 | no |
| 2026-07-28 | FROZEN | 390 | 0 | 09:30 | 15:59 | no |
| 2026-07-29 | FROZEN | 390 | 0 | 09:30 | 15:59 | no |
| 2026-07-30 | FROZEN | 390 | 0 | 09:30 | 15:59 | no |
| 2026-07-31 | FROZEN | 390 | 0 | 09:30 | 15:59 | no |

**Two properties of this window that the reader should know before any number
is computed on it**, both visible in the file and neither of them a defect:

1. **A large overnight discontinuity between 2026-07-13 and 2026-07-14** —
   last close 290.32, next open 226.48, about −22 %. The file is *unadjusted*,
   so a corporate action appears as a gap between sessions. Nothing in this
   system crosses a session: features, calibration returns and evaluator
   labels are all built inside one session, so no feature, no `g(t,H)` and no
   `G(t)` spans it. It is recorded because it is the largest single fact about
   the window's prices.
2. **The three partitions sit at different price levels and different
   volatilities** — WARMUP trades roughly 244–294, LEARNING 204–312 and
   FROZEN 199–231. Returns are scale-free, so the level does not matter to a
   basis-point rule; the volatility does. A horizon calibrated on WARMUP is
   therefore calibrated on a period whose daily ranges are visibly wider than
   FROZEN's, and that is a stated limitation of the D7 design, not a result.

The window **2026-08-03 → 2026-09-04** used by `hist-003` is disjoint from this
one and no bar from it enters D7 feature initialisation, calibration, learning
or evaluation.

---

# Data manifest — PONS replay dataset `d10-replay-v1`

Built 2026-09-12 for D10 by `experiments/d10/import_donor.py`, **at zero RPC
cost**. As with the connectome and the Kibot bars, **the files themselves are
never committed** (`.gitignore`: `data/*/`); this manifest and
`data/pons/d10-replay-v1/MANIFEST.json` are the committed record, and the
import is reproducible from the donor artifacts it names.

Local directory: `data/pons/d10-replay-v1/`.

## Source and licence

The content is **public on-chain data** from Robinhood Chain (chain id 4663):
raw event logs, block headers and contract state reads of the PONS v2 launch
factory `0x7ed598bcef8bd9edd8c97a195c6d13f40801ec7e` and the bonding curves it
deployed. There is no licence restriction on it and none is claimed here.

It was not collected by this project. It was collected by the **owner's own**
private Pons radar at `~/Documentos/PONS` — not a published repository, and
not a third party's data — which recorded it hash-anchored to a known head.
This project read those artifacts **read-only**, never executed the donor,
never started its database and copied no credential. Nothing licensed under
the Kibot agreement is involved; that agreement governs `data/market/` only.

The PONS first-party contracts whose arithmetic the reconstruction reproduces
are MIT; the attribution is in `NOTICE.md`.

## What it contains

Two one-hour launch windows, complete — **every** launch in each window, not
the survivors:

| window (UTC) | launches | native ETH | other quote asset |
|---|---:|---:|---:|
| 2026-09-08 06:00 → 07:00 | 487 | 269 | 218 |
| 2026-09-09 05:00 → 06:00 | 649 | 277 | 372 |
| **total** | **1,136** | **546** | **590** |

The 590 non-native launches carry `QUOTE_UNSUPPORTED` and no curve events; the
546 native-ETH launches carry their curve logs, block headers and a calibrated
launch-block state read each.

| file | contents |
|---|---|
| `raw.jsonl` | 19,926 logs exactly as the endpoint returned them |
| `events.jsonl` | the same logs normalised by `flytrade.pons.collector.Normaliser` |
| `headers.jsonl` | 17,983 block headers (number, hash, parent, timestamp) |
| `initial_states.json` | 546 calibrated launch-block curve states + snipe parameters |
| `discovery.json` | the 1,136-launch census with its admission reasons |
| `MANIFEST.json` | sha256 of every output **and of every donor source file** |

**Coverage, stated plainly:** the donor collected roughly the **first 62
seconds after launch** per token (median last event at 32 s). This dataset can
answer questions about the first minute of a launch and cannot answer
questions about the fifteenth.

## Integrity

`MANIFEST.json` lists the sha256 of all 575 donor source files read and of the
five outputs, so a re-import can be diffed byte for byte. Eight internal
consistency checks ran at import and all passed: unique log ids, a header for
every event's block hash, a calibration and an initial state for every token,
every event inside a range that was actually requested from an address that
range asked about, one head hash across all batches, the native census
matching the plan's token list, and no removed logs in the archive. All **546**
reconstructed curves reconcile exactly with the donor's independent on-chain
state read, and all **13,704** settled trades in the dataset re-price exactly
from the reconstructed pre-trade state.

**No outcome, label, PnL or post-cutoff return was read or computed during the
import.** Field names are checked for that in `tests/d10/test_dataset.py`.

---

# `data/pons/d10-backfill-v1/` — the D10 replay dataset, collected over HTTP

Added by the D10 wave (dispatch 2), 2026-09-12. `data/` is gitignored; this
entry is the provenance record, as for the connectome and the Kibot files.

## Why a second Pons dataset exists

`d10-replay-v1` above is the donor's evidence, imported at zero RPC cost, and
it covers roughly the first **62 seconds** of each token. D10's holding
horizon is **fifteen minutes**, so that dataset admits nothing: a token is
never old enough for a decision whose exit still lies inside its coverage.
Reviewer decision 1 (docs/SPEC.md, after dispatch 1) therefore keeps
`d10-replay-v1` as validation evidence and probe material and orders a new
bounded collection for the run itself. This is that collection.

## Source and window

Public on-chain events and block headers of **Robinhood Chain, chain id 4663**,
read over HTTPS JSON-RPC from the endpoint named by key in the stockroom
`.env`. No licence attaches to public chain data; the Kibot agreement governs
`data/market/` and has nothing to do with this.

| item | value |
|---|---|
| window rule | the 135 minutes of blocks **ending at the `safe` block** recorded by `experiments/d10/verification.json` |
| safe / last block | 60,801,426 |
| first block | 60,721,229 |
| blocks | 80,198 (135 min at the measured 0.101 s interval) |
| admission window | the first 120 minutes, to block 60,792,515 |
| settlement tail | the last 15 minutes |
| scope | native-ETH `pons-v2` launches are followed; every other launch is recorded with `QUOTE_UNSUPPORTED` and not followed |
| collector | `flytrade/pons/collector.py`, the same normalisation path the live driver uses |
| header grid | one header per 100 blocks (± 10.1 s declared precision) plus each tick's `latest`; interpolated timestamps carry `block_timestamp_interpolated` |
| chunks | 1,000 blocks for the factory filter, 500 for the tracked-curve filter |
| request cap | 3,000 units for this collection; **2,314 spent** |

The window was chosen by that rule and by nothing observed inside it.

## What it contains

| file | contents |
|---|---|
| `raw.jsonl` | 62,338 logs exactly as the endpoint returned them |
| `events.jsonl` | the same logs normalised by `flytrade.pons.collector.Normaliser` |
| `headers.jsonl` | 804 sparse grid headers |
| `initial_states.json` | 617 native-ETH launch-block curve states |
| `discovery.json` | the 991-launch census with its admission reasons |
| `MANIFEST.json` | sha256 of every file, the window, and the request ledger |

991 launches (672 native ETH, 319 on an unsupported quote), 27,165 `CurveBuy`,
24,906 `CurveSell`, 7 `CurveCompleted`.

## Initial curve state: derived, not read

614 of the 617 states were **derived** and 3 read with one `eth_call`. The
derivation is an arithmetic fact with a measured provenance
(`flytrade/pons/seed.py`, `tests/d10/test_seed.py`): on all **546** donor
calibrations the pre-trade state of a pinned-config launch is a constant plus
the creator tax, and the creator tax is uniquely recoverable from one trade
(489 of 489 tokens that traded, 0 wrong). A launch that does not match the
pinned config, or whose first trade does not pin the tax uniquely, falls back
to one `eth_call`; a launch with no trade at all can never be admitted and is
left unavailable rather than paid for.

## Integrity

Collected in two passes: the first stopped at block 60,768,228 on a single
transport failure — there is no retry anywhere in this package, so the process
stopped with the cursor and the ledger on disk — and the second resumed from
that cursor and finished the window. No range retreat was needed and no quota
halt occurred. **No outcome, label, PnL or post-cutoff return was read or
computed during the collection.**
