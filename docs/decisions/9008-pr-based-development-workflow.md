---
title: "ADR-9008: PR-based development workflow"
description: Every change goes Issue → Branch → Commit → PR → Merge, and nothing is committed to main directly
date: 2026-01-21
audience:
  - contributors
tags:
  - adr
  - workflow
---

# ADR-9008: PR-based development workflow

## Status

Accepted

## Decision

Adopt a PR-based workflow: Issue → Branch → Commit → PR → Merge. Never commit directly to main. Branch names must follow `<type>/<issue>-<description>` convention. Merge commits must include PR and issue references.

## Rationale

Provides clear audit trail linking issues to PRs to commits, enables code review on every change, ensures CI runs before merge, and makes changes easy to revert (single squash commit per PR). Works well with AI agents due to structured, predictable process.

## Related Issues

- Issue #80: Add doit issue and doit pr commands for GitHub workflow
- Issue #48: Enforce workflow by blocking direct commits to main
- Issue #176: Add doit pr_merge task with enforced commit format
- Issue #853: Make doit pr_merge refuse a PR whose base isn't the default branch
- Issue #855: Add --base to doit pr for work that builds on an unmerged branch (see ADR-9021)

## Related Documentation

- [CI/CD Testing Guide](../development/ci-cd-testing.md)
- [CONTRIBUTING.md](../../.github/CONTRIBUTING.md)
