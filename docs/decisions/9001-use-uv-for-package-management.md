---
title: "ADR-9001: Use uv for package management"
description: Use uv for dependency management, virtual environments and package installation
date: 2026-01-21
audience:
  - contributors
tags:
  - adr
  - tooling
---

# ADR-9001: Use uv for package management

## Status

Accepted

## Decision

Use **uv** as the primary package manager for dependency management, virtual environment creation, and package installation.

## Rationale

uv is a modern Python package manager written in Rust by Astral (creators of ruff). It provides 10-100x faster dependency resolution and installation than pip, built-in virtual environment management, and compatibility with `pyproject.toml` standards. Using the same maintainers as ruff ensures aligned tooling philosophy across the project.

## Related Issues

- Issue #166: Block uv add in AI agent hooks/settings
- Issue #148: dodo.py uses Unix-only shell syntax for UV_CACHE_DIR

## Related Documentation

- [Installation Guide](../getting-started/installation.md)
- [Tools Reference](../template/tools-reference.md)
