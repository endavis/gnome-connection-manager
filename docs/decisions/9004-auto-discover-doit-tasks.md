---
title: "ADR-9004: Auto-discover doit tasks from modules"
description: Import every task_* function under tools/doit/ automatically instead of listing each one in dodo.py
date: 2026-01-21
audience:
  - contributors
tags:
  - adr
  - doit
---

# ADR-9004: Auto-discover doit tasks from modules

## Status

Accepted

## Decision

Implement automatic task discovery that scans `tools/doit/` modules and imports all `task_*` functions automatically, rather than requiring manual imports in `dodo.py`.

## Rationale

Manual imports were error-prone - developers would forget to add imports for new tasks, and the import blocks grew unwieldy. Auto-discovery means new tasks are automatically available without editing `dodo.py`, eliminating "forgot to import" errors and keeping `dodo.py` minimal (3 lines instead of 50+).

## Related Issues

- Issue #173: Auto-discover doit tasks from tools/doit modules

## Related Documentation

- [Tools Reference](../template/tools-reference.md)
