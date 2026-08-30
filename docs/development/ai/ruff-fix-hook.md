---
title: Ruff Auto-Fix on Edit Hook
description: PostToolUse hook that runs ruff --fix on edited Python files
audience:
  - contributors
  - ai-agents
tags:
  - ai
  - hooks
  - ruff
---

# Ruff Auto-Fix on Edit

A Claude Code `PostToolUse` hook that runs `ruff --fix` plus `ruff format` on a Python file immediately after an AI agent edits it. Cuts the feedback loop on trivial issues (unused imports, unused variables, import ordering) from "discovered at `doit check` many turns later" to "fixed before the next tool call".

## What It Does

After every `Edit`, `Write`, or `MultiEdit` call, the hook:

1. Reads the tool payload from stdin and extracts `tool_input.file_path`.
2. Skips the file unless it's a tracked Python source path (see scope below).
3. Runs `uv run ruff check --fix --select F401,F841,I --quiet <path>`.
4. Runs `uv run ruff format --quiet <path>`.
5. Always exits 0. Hook errors must never block tool calls.

The hook is best-effort — timeouts, missing `ruff`, malformed payloads, and ruff non-zero exits are all swallowed silently. The next `doit check` will surface anything genuine.

## Scope

| Path pattern | Auto-fixed? |
|---|---|
| `src/**/*.py` | yes |
| `tests/**/*.py` | yes |
| `tools/**/*.py` | yes |
| `bootstrap.py` | yes |
| Anything else (including `scripts/*.py`, `*.md`, `*.toml`, etc.) | no |

This mirrors the scope `doit format` and `doit lint` already target.

## Rules Fixed

Only deterministic, judgment-free rules are selected:

| Rule | Description |
|---|---|
| `F401` | Unused imports |
| `F841` | Unused local variables |
| `I` | Import sorting (`isort`-compatible) |

All other ruff rules (`E`, `W`, `B`, `RUF`, etc.) are intentionally **not** enabled by the hook — they require human judgment. They still run as part of `doit lint` / `doit check`.

## Disabling Locally

Override the hook entry in `.claude/settings.local.json` (gitignored):

```json
{
  "hooks": {
    "PostToolUse": []
  }
}
```

Restart Claude Code for the change to take effect.

## Known Limitation: Stale `old_string` After Reorder

If you make two consecutive `Edit` calls on the same file and the first edit's ruff pass reorders imports or removes a line you were about to target, the second `Edit`'s `old_string` may no longer match. Mitigations:

- Use `Write` for large rewrites that touch many lines.
- Re-`Read` the file between consecutive `Edit` calls on imports or unused-variable-adjacent code.

The friction is intentional — silencing the noise on every other turn is worth the occasional re-read.

## Files

| File | Description |
|---|---|
| [`tools/hooks/ai/ruff-fix-on-edit.py`](../../../tools/hooks/ai/ruff-fix-on-edit.py) | The hook script |
| [`tests/test_hook_ruff_fix.py`](../../../tests/test_hook_ruff_fix.py) | Pytest coverage |
| [`.claude/settings.json`](../../../.claude/settings.json) | Wires the hook into `PostToolUse` |

## Related

- [AI Command Blocking](command-blocking.md) — sibling `PreToolUse` hook for dangerous commands
