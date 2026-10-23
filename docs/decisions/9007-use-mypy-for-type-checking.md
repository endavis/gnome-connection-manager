---
title: "ADR-9007: Use mypy for static type checking"
description: Use mypy in strict mode, run by doit check, the pre-commit hooks and CI
date: 2026-01-21
audience:
  - contributors
tags:
  - adr
  - tooling
---

# ADR-9007: Use mypy for static type checking

## Status

Accepted

## Decision

Use **mypy** in strict mode for static type checking, running as part of `doit check`, pre-commit hooks, and CI.

## Rationale

mypy is the most mature Python type checker with excellent IDE integration. Strict mode catches type errors early, improves code documentation through required type hints, and ensures consistent type safety. Well-integrated with ruff for a complete code quality pipeline.

## Related Issues

- Issue #61: Make doit check use strict mypy mode to match pre-commit hooks

## Related Documentation

- [Coding Standards](../development/coding-standards.md)
