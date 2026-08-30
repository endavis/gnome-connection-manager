#!/usr/bin/env python3
"""
Claude Code PreToolUse hook to block raw shell commands when native tools are available.

This hook intercepts Bash commands before execution and blocks those that AI agents
should be using native file tools for instead (Read, Grep, Glob, Edit, Write).

Blocks:
  - Leading banned commands: cat, head, tail, find, grep, rg, wc

Escape hatch:
  Touch <project>/tmp/agents/claude/bash-raw-unlock (where <project> is resolved
  from the CLAUDE_PROJECT_DIR env var or the cwd field in the hook's stdin payload)
  to allow banned commands for 10 minutes. The file auto-expires — no cleanup needed.
  The unlock file is scoped to the project so one project's unlock does not affect
  any other project running concurrently.

Exit codes:
  0 - Allow command
  1 - Malformed JSON input
  2 - Block command (shows stderr to Claude)

This hook is Claude-only (reads {"tool_name": "Bash", "tool_input": {"command": "..."}}).
For always-on dangerous-command blocking, see: tools/hooks/ai/block-dangerous-commands.py
For documentation, see: docs/development/ai/token-efficiency-add-ons.md
"""

import json
import os
import shlex
import sys
import time
from pathlib import Path

# Commands that AI agents should never use via Bash when native tools are available
BANNED_COMMANDS: frozenset[str] = frozenset({"cat", "head", "tail", "find", "grep", "rg", "wc"})

# Relative path (from project root) of the per-project escape-hatch file
UNLOCK_FILE_RELATIVE: str = "tmp/agents/claude/bash-raw-unlock"

# How long the escape hatch stays valid after the file is touched (seconds)
UNLOCK_WINDOW_SECONDS: int = 600

# Native tool suggestions for each banned command
_SUGGESTIONS: dict[str, str] = {
    "cat": "Read",
    "head": "Read",
    "tail": "Read",
    "find": "Glob",
    "grep": "Grep",
    "rg": "Grep",
    "wc": "Read (then count lines/words in the result)",
}


def tokenize(command: str) -> list[str]:
    """
    Tokenize command using shlex for proper shell quote handling.

    Returns list of tokens with quotes stripped from values.
    Falls back to non-POSIX mode, then simple whitespace split on malformed input.
    """
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        try:
            return shlex.split(command, posix=False)
        except ValueError:
            return command.split()


def _resolve_unlock_path(input_data: dict[str, object]) -> Path | None:
    """
    Resolve the per-project unlock file path.

    Reads CLAUDE_PROJECT_DIR env var first; falls back to the ``cwd`` field in
    *input_data*.  Returns ``None`` when neither is available (project root
    cannot be determined).
    """
    project_dir: str = os.environ.get("CLAUDE_PROJECT_DIR", "") or str(input_data.get("cwd", ""))
    if not project_dir:
        return None
    return Path(project_dir) / UNLOCK_FILE_RELATIVE


def is_unlocked(unlock_path: Path | None) -> bool:
    """Return True iff *unlock_path* exists and was modified within UNLOCK_WINDOW_SECONDS."""
    if unlock_path is None:
        return False
    try:
        mtime = unlock_path.stat().st_mtime
        return (time.time() - mtime) <= UNLOCK_WINDOW_SECONDS
    except OSError:
        return False


def find_banned_leading(tokens: list[str]) -> str | None:
    """Return the first token if it is in BANNED_COMMANDS, else None."""
    if tokens and tokens[0] in BANNED_COMMANDS:
        return tokens[0]
    return None


def _build_reason(offending: str, unlock_path: Path | None) -> str:
    """Build a human-readable block reason for the given offending command."""
    suggestion = _SUGGESTIONS.get(offending, "a native tool")
    if unlock_path is not None:
        hatch_line = (
            f"Escape hatch: `touch {unlock_path}` (run from any shell) to allow "
            f"raw commands for {UNLOCK_WINDOW_SECONDS // 60} minutes. "
            f"The unlock is scoped to this project."
        )
    else:
        hatch_line = (
            "Escape hatch unavailable: project root could not be determined "
            "(CLAUDE_PROJECT_DIR is unset and no cwd was provided). "
            "Set CLAUDE_PROJECT_DIR to the project root to enable the escape hatch."
        )
    return (
        f"Blocked: `{offending}` is a raw shell command.\n"
        f"Use the native `{suggestion}` tool instead — it produces a better result "
        f"with fewer tokens.\n"
        f"{hatch_line}"
    )


def main() -> int:
    """Main entry point."""
    try:
        input_data: dict[str, object] = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Invalid JSON input: {e}", file=sys.stderr)
        return 1

    # This hook is Claude-only: expects {"tool_name": ..., "tool_input": {...}}
    tool_name = input_data.get("tool_name", "")
    if tool_name != "Bash":
        return 0

    tool_input = input_data.get("tool_input", {})
    if not isinstance(tool_input, dict):
        return 0

    command = tool_input.get("command", "")
    if not isinstance(command, str) or not command:
        return 0

    unlock_path = _resolve_unlock_path(input_data)

    # Escape hatch: allow if unlock file is fresh
    if is_unlocked(unlock_path):
        return 0

    tokens = tokenize(command)

    # Check for banned leading command
    offending = find_banned_leading(tokens)
    if offending is not None:
        print(_build_reason(offending, unlock_path), file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
