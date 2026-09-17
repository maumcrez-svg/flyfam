# Contributing

Thanks for looking. This repository is a curated public snapshot of a working system, so
please read the rules below before opening a pull request — a few of them are hard
constraints rather than style preferences, and a PR that breaks one cannot be merged no
matter how good it is.

## Run the tests first

```sh
python3.13 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest tests/core tests/upstream_audit tests/phase_one \
                          tests/k8_readout tests/d7 tests/historical
# 305 passed, 74 skipped, 2 xfailed
```

Those six suites are the ones that run on a clean clone with no connectome download, no
network and no credentials. The README's [Quickstart](README.md#quickstart) explains what
each of the other suites additionally needs and why it is not expected to pass here.

The skips are suites that self-skip when `data/malecns-v1.0/` is absent. If you want to
run them, [`data/MANIFEST.md`](data/MANIFEST.md) has the download URLs and sha256 for the
three feather tables (~1.15 GB, CC-BY 4.0).

## Rules that are not negotiable

**1. `upstream/` is vendored untouched.** Every file under `upstream/` is
[fruitflydev/flycoinrh](https://github.com/fruitflydev/flycoinrh) at
`5aab4e7895a1f5930319bf3bde8010b350a163a2`, byte-pinned by
[`docs/UPSTREAM_MANIFEST.txt`](docs/UPSTREAM_MANIFEST.txt). It exists so the audit stays
reproducible against a fresh clone. Fixes go in *our* code, never in theirs. A PR that
edits a file under `upstream/` will be closed.

**2. The two strict xfails in `tests/upstream_audit/test_mushroom_orientation.py` pin a
real upstream defect.** They must keep failing. `xfail_strict = true` is on, so "fixing"
them turns the suite red — which is the point. Do not weaken them, do not mark them skip.

**3. Matrices are `[post, pre]`.** Row is the postsynaptic neuron, column is the
presynaptic one, for `graph.npz`, `graph_anat.npz` and `graph_mod.npz` alike. The entire
mushroom-body bug this project exists to fix is one transposed read of exactly this
convention, so any new indexing needs a test that proves its direction on a synthetic graph
whose direction is known by construction — see `tests/upstream_audit/synthetic.py` and
`tests/core/synthetic.py` for the pattern.

**4. Experiments are pre-registered.** The protocol, plan and config of an experiment are
committed *before* it is run, in a commit that contains nothing else; the `git log` order
is the evidence. Results never edit a protocol — a change after the fact is recorded as a
named deviation in the results file, with its reason.

**5. No claim of skill, edge or profit.** Not in code, not in comments, not in docs, not in
the UI. Results are reported as what was measured under the stated conditions, and a
finding compatible with chance is written down as such. Descriptive PnL is fine; "the fly
beats the market" is not.

**6. Nothing in this repository signs a transaction.** The chain package is a read-only
allowlist with no key material. A PR that adds signing, a private key path, a broadcast
call or a write RPC method is out of scope here.

## What a pull request needs

- **One concern per PR**, with a title that says what changed.
- **A test that fails without your change**, unless the change is documentation only.
- **The six offline suites green**, pasted into the PR description, with your platform and
  Python version.
- **Docs updated in the same PR** when behaviour changes. The document is the contract:
  [`docs/SPECTACLE_FEED.md`](docs/SPECTACLE_FEED.md) is literally the feed's specification,
  and `tests/product/test_feed.py` checks the code against it.
- **No new runtime dependencies** without saying why in the PR. The dependency list is
  deliberately upstream's own pins and nothing else; extras that only some paths need go in
  an `[project.optional-dependencies]` group, imported inside the function that needs them.
- **No secrets, wallet addresses, holder lists, endpoints or operational detail** in code,
  tests, fixtures or docs. Fixtures are generated, never captured from production.

## Reporting a bug

Use the [bug report template](.github/ISSUE_TEMPLATE/bug_report.md). If it is a security
issue, read [`SECURITY.md`](SECURITY.md) first and do not open a public issue.

## Style

Plain Python 3.13, standard library first. No formatter is enforced; match the file you are
editing. Comments explain *why*, because the *what* is already in the code.
