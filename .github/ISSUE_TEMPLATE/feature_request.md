---
name: Feature request
about: Propose a change to the simulation, the product loop or the docs
title: ''
labels: enhancement
assignees: ''
---

## What is missing

<!-- The problem, not the solution. What can you not do today? -->

## What you propose

<!-- Concretely: which module, which document, what changes. -->

## How it would be verified

<!-- Which test would fail without it. For anything touching connectivity or a
     readout: a synthetic graph whose direction is known by construction. -->

## Check these before proposing

- [ ] It does not modify anything under `upstream/` (fixes go in our code)
- [ ] It does not weaken the two strict xfails that pin the upstream defect
- [ ] It does not add signing, key material, a broadcast call or a write RPC method
- [ ] It does not claim, imply or measure trading skill, edge or profitability
- [ ] It adds no new required runtime dependency, or explains why one is unavoidable

## Anything else

<!-- Prior art, the relevant paper, the relevant section of docs/SPEC.md. -->
