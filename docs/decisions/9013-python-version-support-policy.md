---
title: "ADR-9013: Python version support policy with bookend CI strategy"
description: Support the last three Python versions, testing the oldest and newest on every PR and older ones on demand
date: 2026-01-21
audience:
  - contributors
tags:
  - adr
  - ci-cd
  - python
---

# ADR-9013: Python version support policy with bookend CI strategy

## Status

Accepted

## Decision

Adopt a tiered Python version support policy:

1. **Active support**: Last 3 major Python versions, tested on every PR using bookend strategy (oldest + newest)
2. **Passive compatibility**: Older versions that still pass CI, tested on-demand via `full-matrix` label
3. **Deprecation**: Versions removed from CI when tests fail, with final compatible release tagged

CI matrix strategy:
- **Default (6 jobs)**: Bookend versions (oldest + newest) × 3 OSes
- **Full matrix (+3 jobs per middle version)**: Middle versions only × 3 OSes, triggered by `full-matrix` label

Version configuration stored in `.github/python-versions.json`:
```json
{
  "oldest": "3.12",
  "newest": "3.14"
}
```

Middle versions are derived automatically. A `ci-complete` summary job aggregates results for branch protection, eliminating the need to update branch protection when versions change.

## Rationale

Testing every Python version on every PR creates excessive CI load without proportional benefit. The bookend strategy (testing oldest and newest supported versions) catches most compatibility issues:
- If code works on 3.12 and 3.14, it almost certainly works on 3.13
- Full matrix testing runs only middle versions (bookends already passed)
- Config-driven approach means no workflow or branch protection changes when versions update
- Passive compatibility allows supporting older versions without maintenance burden
- Clear deprecation process with tagged releases protects users on older Python versions

## Related Issues

- Issue #168: Add Python 3.14 to CI testing matrix
- Issue #413: Extract python-versions.json readers into a reusable composite action

## Related Documentation

- [CI/CD Testing Guide - Python Version Support Policy](../development/ci-cd-testing.md#python-version-support-policy)
