#!/usr/bin/env python3
"""Claude Code PreToolUse advisory: remind Claude to use ctx_batch_execute for test commands.

Emits a ``hookSpecificOutput.additionalContext`` reminder when a Bash command matches
one of the common test-runner patterns (pytest, npm test, go test, cargo test, mvn test,
gradle test). Does not shell out to any external CLI — entirely self-contained.

For documentation and opt-in setup, see: docs/development/ai/token-efficiency-add-ons.md
"""

from __future__ import annotations

import json
import re
import sys

TEST_COMMAND_PATTERNS: tuple[str, ...] = (
    r"\bpytest\b",
    r"\bnpm\s+(?:run\s+)?test\b",
    r"\bgo\s+test\b",
    r"\bcargo\s+test\b",
    r"\bmvn\s+test\b",
    r"\bgradle\s+test\b",
)
REMINDER = (
    "Reminder: this command can produce large output. If `context-mode` MCP is "
    "available, prefer `ctx_batch_execute` for multi-command runs (test + lint + "
    "typecheck). Output is summarised; use `ctx_search` to retrieve detail."
)


def main() -> int:
    """Hook entry point. Always returns 0; tests call this directly."""
    try:
        try:
            data = json.load(sys.stdin)
        except (json.JSONDecodeError, ValueError):
            return 0
        if not isinstance(data, dict) or data.get("tool_name") != "Bash":
            return 0
        cmd = (data.get("tool_input") or {}).get("command", "")
        if not isinstance(cmd, str) or not any(re.search(p, cmd) for p in TEST_COMMAND_PATTERNS):
            return 0
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": REMINDER,
            }
        }
        sys.stdout.write(json.dumps(output))
        sys.stdout.flush()
    except Exception:  # nosec B110
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
