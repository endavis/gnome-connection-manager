#!/usr/bin/env python3
"""
Claude Code SessionStart hook that restores the most recent auto-precompact checkpoint.

Triggered when Claude Code starts a session whose trigger contains "compact" or "resume"
(configured via the matcher in ``.claude/settings.json``). Reads the newest
``*-auto-precompact*.md`` from ``tmp/checkpoints/`` and injects its contents into the
new session via ``hookSpecificOutput.additionalContext``.

Opt-out: set ``CLAUDE_NO_AUTO_RESTORE=1`` to disable restoration entirely.
Widen: set ``CLAUDE_RESTORE_ANY=1`` to restore any ``*.md`` checkpoint, not just
``*-auto-precompact*.md`` ones.

The hook is best-effort: any failure (missing directory, no matching files, malformed
stdin) is swallowed and the hook exits 0 so it never blocks session startup.

For full documentation, see: docs/development/ai/auto-checkpoint-hook.md
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Default glob: only auto-precompact checkpoints.
DEFAULT_GLOB = "*-auto-precompact*.md"

# Widened glob: any checkpoint (enabled when CLAUDE_RESTORE_ANY=1).
ANY_GLOB = "*.md"


def _find_newest_checkpoint(checkpoints_dir: Path, glob: str) -> Path | None:
    """Return the lexically smallest (newest by inv_epoch) matching file, or None."""
    try:
        matches = sorted(checkpoints_dir.glob(glob))
        return matches[0] if matches else None
    except (OSError, PermissionError):
        return None
    except Exception:  # nosec B110 - defensive
        return None


def main() -> int:
    """Hook entry point. Always returns 0; tests call this directly."""
    try:
        # Opt-out check.
        if os.environ.get("CLAUDE_NO_AUTO_RESTORE"):
            return 0

        try:
            input_data = json.load(sys.stdin)
        except (json.JSONDecodeError, ValueError):
            return 0

        if not isinstance(input_data, dict):
            return 0

        cwd = input_data.get("cwd", "")
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "") or cwd
        if not project_dir:
            return 0

        checkpoints_dir = Path(project_dir) / "tmp" / "checkpoints"
        if not checkpoints_dir.is_dir():
            return 0

        # Choose glob based on env var.
        glob = ANY_GLOB if os.environ.get("CLAUDE_RESTORE_ANY") else DEFAULT_GLOB

        newest = _find_newest_checkpoint(checkpoints_dir, glob)
        if newest is None:
            return 0

        try:
            body = newest.read_text(encoding="utf-8")
        except (OSError, PermissionError):
            return 0
        except Exception:  # nosec B110 - defensive
            return 0

        output = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": body,
            }
        }
        sys.stdout.write(json.dumps(output))
        sys.stdout.flush()

    except Exception:  # hook must never raise
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
