#!/usr/bin/env python3
"""
Claude Code SessionStart hook that re-injects the CBM gate protocol reminder.

Triggered when Claude Code starts a session whose trigger contains "compact", "resume",
or "clear" (configured via the matcher in ``.claude/settings.local.json``). Reads
``cbm-session-reminder.md`` (a sibling file) and injects its contents into the new
session via ``hookSpecificOutput.additionalContext``.

This re-injection ensures that CBM gate conventions stay active throughout a session
regardless of how many autocompact events have occurred. Without it, the model may
honour the CBM protocol at session start but drift to raw Read/Grep/Glob late in a
long session once the context has been compacted.

The hook is best-effort: any failure (missing reminder file, malformed stdin) is
swallowed and the hook exits 0 so it never blocks session startup.

For documentation and opt-in setup, see: docs/development/ai/token-efficiency-add-ons.md
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Path to the reminder text. Sibling to the hook so it is portable.
REMINDER_TEXT_PATH: Path = Path(__file__).resolve().parent / "cbm-session-reminder.md"


def main() -> int:
    """Hook entry point. Always returns 0; tests call this directly."""
    try:
        try:
            json.load(sys.stdin)
        except (json.JSONDecodeError, ValueError):
            return 0  # Malformed JSON — best-effort, don't block.

        try:
            body = REMINDER_TEXT_PATH.read_text(encoding="utf-8")
        except (OSError, PermissionError):
            return 0  # Missing or unreadable reminder file — degrade gracefully.

        output = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": body,
            }
        }
        sys.stdout.write(json.dumps(output))
        sys.stdout.flush()

    except Exception:  # nosec B110 - hook must never raise
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
