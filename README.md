# FLYFAM

A fruit-fly connectome brain that trades Pons v2 memecoins on Robinhood Chain
(chain id 4663), watched and voted on by token holders in a public bag room.

[flyfam.xyz](https://flyfam.xyz) · [brand kit](https://flyfam.xyz/brand.html) ·
[Telegram](https://t.me/flyfamrh) · [X](https://x.com/flyfamrh)

## Status — 2026-09-17

- **Trading is PAPER.** Real Pons data, paper execution. Nothing is signed or
  broadcast; the chain package has a six-method read-only allowlist and holds no
  key material.
- **REAL_HOLDERS is live.** The public site runs PAPER / REAL_HOLDERS with 20
  on-chain holders (minus two exclusions: the bonding curve and the bump bot).
  Test autoexit is off, so a bag now closes **only** on real-holder EXIT votes.
  Bag #11, opened 11:18:31 UTC, is the first bag voted by real holders. The ops
  wallet votes like any other holder starting at bag #12.
- **No real claims.** `/api/claims/<wallet>` and `/api/bags/claims` return
  `{"claims":[]}`; `/api/vault/summary` reports `configured:false`; the signed
  POST refuses a foreign Origin.
- **No fee split running.** Creator-fee facts are recorded; the split worker
  is not written. Real money is not live.
- The $FLYFAM contract strip is shown on the site.

## What it is

**The brain is measured anatomy, not a metaphor.** It runs the FlyEM male *Drosophila*
CNS connectome v1.0 — 165,122 traced neurons — as a leaky integrate-and-fire simulation.
The graph build keeps anatomy first and produces three matrices sharing one body index,
all `[post, pre]`: `graph_anat.npz` (unsigned synapse counts), `graph.npz` (signed fast
weights, 10,228,000 edges) and `graph_mod.npz` (dopaminergic counts, never given a fast
weight). See `docs/ARCHITECTURE.md`.

**The mushroom-body fix.** Upstream classifies PAM/PPL1 compartments from MBON→DAN
feedback — a transposed read. Against the shipped graph the documented read returns
nothing, which is why the transposed one shipped. Our `flytrade/mushroom.py` reads
`D[mbon][:, dan].sum(axis=1)`: the dopaminergic synapses each MBON actually *receives*.
`upstream/` is vendored untouched; the fix lives only in our code. See
`docs/UPSTREAM_NOTES.md` and `docs/POPULATIONS.md`.

**The decoder was pre-registered before any PnL existed.** It reads the centred valence
`approach − avoid` over MBON01–MBON15 (16 PPL1-innervated and 29 PAM-innervated neurons,
the other 52 MBONs excluded rather than guessed) and compares it against θ = 3.241438
Hz, one measured baseline SD. Saturation first, then silence, then the margin; anything
inside the margin is `WAIT`. θ is an action-decoding rule, not a probability of
financial success. See `docs/DECODER.md`.

**Learning is frozen.** `brains/trader-v1/brain.npz` is the clean reference checkpoint
of the D11/D12 experiments, digest `ba95b605…`, every plastic KC→MBON gain at 1.0. The
product loop applies no plasticity: a settled episode becomes a CREDIT event and changes
no weight.

**Nothing here is evidence of skill, and the record says so.** D7's pre-registered
readout put context ranking at chance in both branches (AUC 0.4904 trained / 0.4934
reference); D11 and D12 closed INCONCLUSIVE by their own pre-registered conditions. The
product decision of 2026-09-13 was to stop the scientific track, freeze the brain and
run the Pons paper loop as spectacle. No claim of beating chance is made anywhere in
this repository.

**The loop and the bag room.** Every thirty seconds the frozen fly looks at the
memecoins launched on Pons v2, admits candidates, picks one and opens a paper position.
The fly chooses the entry; snapshotted on-chain holders decide the normal exit by
HOLD/EXIT vote. Autoexit v2 is a PAPER/test-holder fallback only — bands at ±20%
**gross** return, 600 s of market silence, a 3600 s maximum hold. Gross, because a round
trip on these curves costs 2.5–8.6% of notional and the old net stop was measuring its
own costs; net is still computed and displayed and decides nothing.

**The front end** is the spectacle: a stdlib `http.server` process serving an original
animated fly, browser-native JS and CSS, no build step and no external assets. It reads
the contract in `docs/SPECTACLE_FEED.md` — kinds SNIFF · PICK · OPEN · MARK · CLOSE ·
CREDIT · HEARTBEAT · THROTTLED · RPC_ERROR — and nothing else.

## Repository map

| path | what it is |
|---|---|
| `flytrade/` | our code — graph build, encoder, decoder, mushroom-body fix, Pons client, paper execution, product loop, bag room |
| `upstream/` | fruitflydev/flycoinrh vendored at `5aab4e78`, MIT, **unmodified**; byte-pinned by `docs/UPSTREAM_MANIFEST.txt` |
| `brains/` | the frozen product artifact `trader-v1/brain.npz` plus its manifest |
| `experiments/` | pre-registered experiments D1–D12: plan, config and report committed before any number |
| `tests/` | pytest suites, including `tests/upstream_audit/` which pins upstream's verified behaviour |
| `observer/` | the read-only event viewer over recorded experiment runs |
| `product/` | the freeze tool, the runner and the example configs for the continuous Pons paper loop |
| `spectacle/` | the public site and the 3D fly |
| `art/` | character and brand source |
| `contracts/` | HolderVault and related Solidity |
| `docs/` | architecture, upstream audit, populations, encoder, decoder, execution, spec, feed contract, bag room |
| `data/` | gitignored runtime, connectome and market data; only `data/MANIFEST.md` is committed |

## Running locally

Python 3.13, on upstream's own pins (`pyproject.toml`: numpy 2.4.2, scipy
1.17.1, pandas 3.0.1, pyarrow 23.0.1, pytest 9.1.1).

```sh
python3.13 -m venv .venv
.venv/bin/pip install -e '.[dev]'

# the gate the waves run
.venv/bin/python -m pytest tests/

# the upstream audit alone, or any focused suite
.venv/bin/python -m pytest tests/upstream_audit/
```

Suites that read the connectome need the three feather files downloaded first;
they are not in the repository, and `data/MANIFEST.md` has the URLs and hashes.

The experiment viewer is a stdlib server on loopback (port 8765):

```sh
.venv/bin/python observer/serve.py
```

The public product is the site at [flyfam.xyz](https://flyfam.xyz). The
spectacle frontend in this tree is `spectacle/`.

## Docs

- `docs/ARCHITECTURE.md` — the upstream seam, the three matrices, the plasticity fix, the operating point, per wave.
- `docs/UPSTREAM_NOTES.md` — the Phase Zero audit of flycoinrh: verified, transposed, and unverifiable.
- `docs/POPULATIONS.md` — every population counted off the dataset, split into observed connectivity, literature interpretation and our modelling rule.
- `docs/DECODER.md` — the pre-registered readout: populations, aggregation, θ, the four statuses, the tie rule.
- `docs/ENCODER.md`, `docs/EXECUTION.md` — market → ORN encoding, and the paper execution model.
- `docs/SPEC.md` — the canonical specification, every owner amendment and the reviewer addenda.
- `docs/SPECTACLE_FEED.md` — the feed contract the front end reads.
- `docs/BAG_ROOM.md`, `docs/AUTO_EXIT.md`, `docs/HOLDER_ACCESS.md`, `docs/PRODUCT_V1.md`, `docs/FRONTEND_V1.md` — the public product surface.
- `CHANGELOG.md` — dates and what shipped.

## Data and licensing

- **Connectome** — FlyEM male *Drosophila* CNS v1.0, © HHMI Janelia FlyEM, the
  Cambridge Connectomics Group and Google Research, **CC-BY 4.0**. The files are
  not in this repository; `data/MANIFEST.md` records source URLs, byte sizes and
  sha256 so the download is reproducible. The attribution obligation travels with
  every derived artifact, a built graph and any public figure included.
- **Market data** — Kibot, licensed for internal use. Never committed, never
  redistributed.
- **`upstream/`** — MIT, © 2026 fruitflydev. Vendored verbatim with its `LICENSE`
  and `NOTICE`; see `NOTICE.md`.
- **Pons contracts** — the frozen Sourcify copies under `experiments/d10/evidence/`
  are MIT, © the Pons authors. `PonsTickMath.sol` is GPL-2.0-or-later and is not
  used, copied, ported or linked here.
- **Our code** — © 2026 FLYFAM. All rights reserved.

Not affiliated with HHMI Janelia, Google Research, Pons, Robinhood or Uniswap.

## Secrets

No private key, env file or credential is tracked. `.env` and `data/*/` are
gitignored. The one tracked `*.env` is `experiments/d11/local_node.env`, which
holds a loopback RPC URL and nothing else.
