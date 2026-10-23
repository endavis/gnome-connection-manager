---
title: "ADR-9003: Use ruff for linting and formatting"
description: Use ruff as the one tool for linting and formatting, in place of flake8, black and isort
date: 2026-01-21
audience:
  - contributors
tags:
  - adr
  - ruff
---

# ADR-9003: Use ruff for linting and formatting

## Status

Accepted

## Decision

Use **ruff** as the single tool for both linting and code formatting, replacing flake8, black, isort, and other tools.

## Rationale

ruff is an extremely fast Python linter and formatter written in Rust that consolidates multiple tools into one. It includes linting rules from flake8, pylint, and others, plus a Black-compatible formatter and import sorting. Single configuration in `pyproject.toml` and 10-100x faster execution than traditional Python-based tools.

## Related Issues

- Issue #128: Align pre-commit, CI, and doit check to use consistent checks

## Related Documentation

- [Coding Standards](../development/coding-standards.md)
