## What this changes

<!-- One concern per PR. Say what changed and why, not how. -->

## Why

<!-- The problem this solves. Link the issue if there is one. -->

## How it was verified

<!-- The test that fails without this change, by name. -->

```sh
.venv/bin/python -m pytest tests/core tests/upstream_audit tests/phase_one \
                          tests/k8_readout tests/d7 tests/historical
```

Summary line:

```

```

Platform and Python version:

## Checklist

- [ ] The six offline suites are green, and the summary line is pasted above
- [ ] A test fails without this change (or this is documentation only)
- [ ] No file under `upstream/` is modified
- [ ] The two strict xfails in `tests/upstream_audit/test_mushroom_orientation.py` still xfail
- [ ] Any new matrix indexing is `[post, pre]` and is proven by a synthetic-graph test
- [ ] Docs updated in this PR if behaviour changed, including `docs/SPECTACLE_FEED.md` if the feed changed
- [ ] No new required runtime dependency
- [ ] No secrets, keys, endpoints, wallet addresses, holder lists or operational detail
- [ ] Nothing here signs, broadcasts or sends a transaction
- [ ] No claim of trading skill, edge or profitability in code, comments, docs or UI
