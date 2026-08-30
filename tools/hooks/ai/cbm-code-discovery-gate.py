#!/usr/bin/env python3
"""
Claude Code PreToolUse hook to gate code-discovery tools behind a CBM (Codebase Memory MCP) call.

This hook intercepts Read, Grep, and Glob calls before execution and blocks those targeting
source-code files unless a CBM tool has been called recently (within MARKER_TTL_SECONDS) or
the path matches the allow-list (configs, docs, tests, hooks, settings).

The gate exists to encourage agents to query the CBM knowledge graph first — which answers
structural queries for far fewer tokens than reading files directly — and only fall back to
raw file reads for targets that CBM cannot help with (config, docs, test files).

Allow-list:
  File extensions: .json .yaml .yml .md .toml .lock .txt .env .sh
  Path fragments:  .claude/ CLAUDE.md settings hooks/ tests/ _test.

Escape hatch:
  CBM marker: any call to a CBM MCP tool (matched by the PostToolUse marker hook) touches
  MARKER_FILE_TEMPLATE, opening a MARKER_TTL_SECONDS window during which Read/Grep/Glob
  on source files is allowed.

Exit codes:
  0 - Allow (allow-list match, marker fresh, or non-gated tool)
  1 - Malformed JSON input
  2 - Block (source file + no fresh marker; shows stderr to Claude)

This hook is Claude-only (reads {"tool_name": ..., "tool_input": {...}}).
For documentation and opt-in setup, see: docs/development/ai/token-efficiency-add-ons.md
"""

import json
import os
import re
import sys
import time
from pathlib import Path

# Tool names this gate applies to (the matcher does the first cut, but defensively re-check).
GATED_TOOLS: frozenset[str] = frozenset({"Read", "Grep", "Glob"})

# Files / paths that always pass through (configs, docs, tests, project metadata).
# Source-code files (.py, .js, .ts, .go, etc.) are NOT in the allow-list and require
# a recent CBM call.
ALLOWLIST_REGEX: re.Pattern[str] = re.compile(
    r"\.(json|yaml|yml|md|toml|lock|txt|env|sh)$"
    r"|\.claude/|CLAUDE\.md|settings|hooks/|(^|/)tests?/|_test\."
)

# Marker file template. {ppid} interpolates to os.getppid() at runtime so the
# marker is scoped per-Claude-Code-session.
MARKER_FILE_TEMPLATE: str = "/tmp/cbm-mcp-used-{ppid}"  # nosec B108 - well-known path is intentional; operators must be able to touch it from any shell. Configurable via this constant.

# How long the marker stays valid after the last CBM tool call (seconds).
MARKER_TTL_SECONDS: int = 120


def _marker_fresh() -> bool:
    """Return True iff the CBM marker file exists and was modified within MARKER_TTL_SECONDS."""
    path = Path(MARKER_FILE_TEMPLATE.format(ppid=os.getppid()))
    try:
        mtime = path.stat().st_mtime
        return (time.time() - mtime) <= MARKER_TTL_SECONDS
    except OSError:
        return False


def _build_block_reason(tool_name: str, path_value: str) -> str:
    """Build a human-readable block reason naming the gated tool and recovery steps."""
    marker_path = MARKER_FILE_TEMPLATE.format(ppid=os.getppid())
    target_desc = f"`{path_value}`" if path_value else "a whole-repo search"
    return (
        f"Blocked: `{tool_name}` on {target_desc} requires a recent CBM call.\n"
        f"Call `mcp__codebase-memory__search_graph` (or another CBM tool) first, "
        f"then retry within {MARKER_TTL_SECONDS}s.\n"
        f"CBM marker: {marker_path}\n"
        f"Allow-list bypass: configs, docs, tests, and settings files are always allowed."
    )


def main() -> int:
    """Main entry point."""
    try:
        input_data: dict[str, object] = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Invalid JSON input: {e}", file=sys.stderr)
        return 1

    # Defensive check: this hook is Claude-only and expects a specific payload shape.
    tool_name = input_data.get("tool_name", "")
    if not isinstance(tool_name, str) or tool_name not in GATED_TOOLS:
        return 0

    tool_input = input_data.get("tool_input", {})
    if not isinstance(tool_input, dict):
        return 0

    # Extract the path argument. Read uses "file_path"; Grep/Glob use "path".
    # If path is absent (whole-repo Grep/Glob), path_value is "" — NOT auto-allowed.
    if tool_name == "Read":
        path_value = tool_input.get("file_path", "")
    else:
        path_value = tool_input.get("path", "")

    if not isinstance(path_value, str):
        path_value = ""

    # Allow-list: configs, docs, tests, hooks, settings always pass through.
    if path_value and ALLOWLIST_REGEX.search(path_value):
        return 0

    # CBM escape hatch: marker file exists and is fresh (written by cbm-mcp-marker.py).
    if _marker_fresh():
        return 0

    # Block: source file (or whole-repo search) without a fresh CBM call.
    print(_build_block_reason(tool_name, path_value), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
