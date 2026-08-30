---
title: Auto-Checkpoint and Session-Restore Hooks
description: PreCompact and SessionStart hooks that preserve context across autocompact events
audience:
  - contributors
  - ai-agents
tags:
  - ai
  - hooks
  - checkpoint
---

# Auto-Checkpoint and Session-Restore Hooks

Two Claude Code hooks that wire the existing `/checkpoint` and `/restore` primitives into the
`PreCompact` and `SessionStart` lifecycle events, so context is preserved automatically when
autocompact fires mid-task — no human in the loop required.

## What They Do

### PreCompact hook (`precompact-checkpoint.py`)

Before Claude Code compacts the conversation context, the hook:

1. Reads the `transcript_path` from the hook payload.
2. Takes up to 200 KB from the tail of the JSONL transcript.
3. Spawns `claude -p --bare --model claude-sonnet-5` with a strict-JSON prompt asking for:
   `{title, status, in_flight_work, constraints, files_touched, next_steps, resume_prompt}`.
4. Parses the JSON response and renders it into a markdown checkpoint file matching the
   `/checkpoint` section structure (Title, Status, In-flight work, Constraints, Files touched,
   Next steps, Resume prompt).
5. Writes the file to `tmp/checkpoints/{inv_epoch}-auto-precompact.md` where `inv_epoch` is a
   10-digit decreasing integer (newest sorts first under default `ls`).
6. On any failure (timeout, missing CLI, non-zero exit, JSON parse error, missing transcript),
   falls back to a banner + raw transcript tail tagged `AUTO_PARTIAL`.
7. Always exits 0 — the hook never blocks the compaction event.

### SessionStart hook (`session-resume-restore.py`)

When Claude Code starts a session whose trigger contains "compact" or "resume":

1. Globs `tmp/checkpoints/*-auto-precompact*.md` and picks the lexically smallest file
   (newest by `inv_epoch` convention).
2. Reads the file and emits it as `hookSpecificOutput.additionalContext` so the model sees
   the checkpoint body as injected context at session start.
3. If no matching file exists, no-ops silently.
4. Always exits 0.

## Filename Convention

Auto-checkpoint filenames follow the same `{inv_epoch}-{slug}.md` convention as manual
`/checkpoint` files:

```
tmp/checkpoints/9999999999-auto-precompact.md
```

The `inv_epoch` is computed as `9999999999 - int(time.time())`, matching Step 1 of
`.claude/commands/checkpoint.md` exactly. On same-second collision (rare), a single letter
suffix is appended: `…-auto-precompact-a.md`, `…-auto-precompact-b.md`, etc.

Because the convention is shared, manual `/restore` can also load auto-precompact files
by slug: `/restore auto-precompact`.

## Opt-Out and Widening

| Env var | Effect |
|---|---|
| `CLAUDE_NO_AUTO_RESTORE=1` | SessionStart hook no-ops even when checkpoints exist |
| `CLAUDE_RESTORE_ANY=1` | SessionStart hook widens glob to `*.md`, restoring any checkpoint (not just auto-precompact ones) |

Set these in `.claude/settings.local.json` (gitignored) or in your shell profile:

```json
{
  "env": {
    "CLAUDE_NO_AUTO_RESTORE": "1"
  }
}
```

## Synthesis Prompt Shape

The PreCompact hook sends a structured prompt requesting strict JSON output:

```
{title, status, in_flight_work, constraints, files_touched (array),
 next_steps, resume_prompt}
```

If the model wraps the JSON in markdown fences, the hook strips them before parsing.
On any parse failure, the hook falls back to `AUTO_PARTIAL` mode (raw transcript tail).

## Fallback Behavior

| Condition | Result |
|---|---|
| Synthesis succeeds, JSON valid | Full structured checkpoint written |
| Synthesis returns non-zero exit | `AUTO_PARTIAL` fallback written |
| `claude` CLI not found (`FileNotFoundError`) | `AUTO_PARTIAL` fallback written |
| Synthesis times out (90 s) | `AUTO_PARTIAL` fallback written |
| JSON parse fails | `AUTO_PARTIAL` fallback written |
| Transcript file missing | `AUTO_PARTIAL` fallback written (empty tail) |
| Malformed stdin JSON | Exits 0, no file written |

`AUTO_PARTIAL` files are tagged in their title so you can identify them and know the
structured fields are absent.

## Settings Wiring

`.claude/settings.json`:

```json
{
  "hooks": {
    "PreCompact": [
      {
        "hooks": [
          {
            "type": "command",
            "timeout": 90,
            "command": "python3 $CLAUDE_PROJECT_DIR/tools/hooks/ai/precompact-checkpoint.py"
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "matcher": "compact|resume",
        "hooks": [
          {
            "type": "command",
            "command": "python3 $CLAUDE_PROJECT_DIR/tools/hooks/ai/session-resume-restore.py"
          }
        ]
      }
    ]
  }
}
```

The `timeout: 90` on `PreCompact` matches the synthesis subprocess timeout so the hook
does not hang indefinitely if the CLI is slow to respond.

## Manual Verification

These steps cannot be run by a subagent but are provided for contributor verification:

1. Start a long session; run `/compact` to force a `PreCompact` event. Confirm a new file
   appears in `tmp/checkpoints/` with the `-auto-precompact.md` suffix.
2. Read the file. Confirm it has the expected sections — not just an `AUTO_PARTIAL` dump.
3. Start a fresh session via `claude --resume`. Confirm the checkpoint body appears inlined
   in the new session's initial context.
4. Set `CLAUDE_NO_AUTO_RESTORE=1`, repeat step 3; confirm no inlining.
5. Force a synthesis failure (temporarily rename `claude` on PATH); repeat step 1; confirm
   the `AUTO_PARTIAL` fallback file is produced.

## Files

| File | Description |
|---|---|
| [`tools/hooks/ai/precompact-checkpoint.py`](../../../tools/hooks/ai/precompact-checkpoint.py) | PreCompact hook script |
| [`tools/hooks/ai/session-resume-restore.py`](../../../tools/hooks/ai/session-resume-restore.py) | SessionStart hook script |
| [`tests/test_hook_precompact_checkpoint.py`](../../../tests/test_hook_precompact_checkpoint.py) | Pytest coverage for PreCompact hook |
| [`tests/test_hook_session_resume_restore.py`](../../../tests/test_hook_session_resume_restore.py) | Pytest coverage for SessionStart hook |
| [`.claude/settings.json`](../../../.claude/settings.json) | Wires both hooks into the lifecycle |

## Related

- [AI Command Blocking](command-blocking.md) — sibling `PreToolUse` hook for dangerous commands
- [Ruff Auto-Fix on Edit](ruff-fix-hook.md) — sibling `PostToolUse` hook for Python formatting
- [Slash Commands and Workflows](slash-commands.md) — the `/checkpoint` and `/restore` manual commands
- [AGENTS.md](../../../AGENTS.md) — `tmp/checkpoints/` convention and cross-agent portability
