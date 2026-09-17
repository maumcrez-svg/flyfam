---
name: Bug report
about: Something in the code, the tests or the docs does not do what it says
title: ''
labels: bug
assignees: ''
---

**Not for security issues.** If this could be exploited, read
[SECURITY.md](../../SECURITY.md) and report it privately instead.

## What happened

<!-- One or two sentences. -->

## What you expected

<!-- And where that expectation comes from: a doc, a docstring, a test name. -->

## How to reproduce

<!-- The exact commands. Paste the full output, not a summary of it. -->

```sh

```

## Which suites are green

<!-- Paste the summary line. On a clean clone the offline subset should give
     305 passed, 74 skipped, 2 xfailed. -->

```sh
.venv/bin/python -m pytest tests/core tests/upstream_audit tests/phase_one \
                          tests/k8_readout tests/d7 tests/historical
```

## Environment

- OS:
- Python (`python3 -VV`):
- Commit (`git rev-parse --short HEAD`):
- Connectome data present (`data/malecns-v1.0/`): yes / no

## Anything else

<!-- If it touches connectivity or indexing, say which matrix and which
     orientation you believe is wrong: these are all [post, pre]. -->
