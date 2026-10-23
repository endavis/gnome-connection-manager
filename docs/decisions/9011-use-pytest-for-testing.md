---
title: "ADR-9011: Use pytest for testing"
description: Use pytest, with pytest-xdist for parallel runs and pytest-cov for coverage
date: 2026-01-21
audience:
  - contributors
tags:
  - adr
  - testing
---

# ADR-9011: Use pytest for testing

## Status

Accepted

## Decision

Use **pytest** as the testing framework with pytest-xdist for parallel execution and pytest-cov for coverage reporting.

## Rationale

pytest minimizes boilerplate (plain functions, no classes required), has a powerful fixture system, excellent assertion introspection, and is the industry standard for Python testing. Parallel execution via xdist speeds up CI significantly.

## Related Issues

- Issue #126: Add tests for template tools and exclude from generated projects
- Issue #83: Add multi-OS CI testing (Windows, macOS)

## Related Documentation

- [CI/CD Testing Guide](../development/ci-cd-testing.md)
- [Coding Standards](../development/coding-standards.md)
