---
title: "ADR-9002: Use doit for task automation"
description: Use doit as the task runner for testing, linting, building and other routine operations
date: 2026-01-21
audience:
  - contributors
tags:
  - adr
  - doit
---

# ADR-9002: Use doit for task automation

## Status

Accepted

## Decision

Use **doit** as the task automation framework for common operations like testing, linting, building, and deployment.

## Rationale

doit is a Python-based build tool that uses pure Python for task definitions (no DSL to learn), provides automatic task dependency resolution and incremental builds, and encourages modular task organization. Being Python-native means no context switching for developers already working in Python.

## Scope

doit is a **development task runner only**. It exists to make contributor
workflows (testing, linting, releases, issue and PR creation) reproducible
and discoverable. It is not part of the published package's public API.

- doit must **not** be used to front the application's user-facing CLI. The
  application's CLI is a console script under `src/__PACKAGE_NAME__/`. End users
  of the published package should never need to install `doit` to use it.
- `doit` is a **development dependency only**, declared under
  `[project.optional-dependencies] dev` in `pyproject.toml`. It is not
  installed when adopters install the published package. (Historical note:
  it was briefly placed in `[project] dependencies` per #65 as a packaging
  convenience; #348 moved it to dev to align with the boundary above.)

For the broader layering rationale, see
[Tooling Roles and Architectural Boundaries](../development/tooling-roles.md).

## Related Issues

- Issue #170: Rename tools/tasks to tools/doit
- Issue #87: Add shell completions for doit tasks
- Issue #80: Add doit issue and doit pr commands for GitHub workflow
- Issue #65: Promote doit and rich to runtime dependencies
- Issue #340: Document tooling roles and architectural boundaries
- Issue #341: Add application CLI guide (implements the runtime-CLI half of the split)
- Issue #348: Move doit from runtime to dev dependencies

## Related Decisions

- [ADR-9014: Use click for application CLI](9014-use-click-for-application-cli.md) — defines the runtime CLI surface that complements doit's dev-only role.

## Related Documentation

- [Tools Reference](../template/tools-reference.md)
- [CLI Guide](../usage/cli.md)
