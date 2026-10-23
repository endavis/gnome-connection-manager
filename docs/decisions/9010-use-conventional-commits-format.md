---
title: "ADR-9010: Use conventional commits format"
description: Write every commit message, merge commits included, in the Conventional Commits format
date: 2026-01-21
audience:
  - contributors
tags:
  - adr
  - workflow
---

# ADR-9010: Use conventional commits format

## Status

Accepted

## Decision

Adopt **Conventional Commits** format (`<type>: <subject>`) for all commit messages. Types include feat, fix, docs, refactor, test, chore, ci, perf. Merge commits follow `<type>: <subject> (merges PR #XX, addresses #YY)`.

## Rationale

Provides consistent, readable git history, enables automated changelog generation, and allows easy filtering by change type. Works well with semantic versioning for automated version bumps based on commit types.

## Related Issues

- Issue #176: Add doit pr_merge task with enforced commit format
- Issue #175: Add PR title validation to enforce merge commit format
- Issue #235: Replace "Closes/Part of" with "Addresses" in PR workflow

## Related Documentation

- [CONTRIBUTING.md](../../.github/CONTRIBUTING.md)
