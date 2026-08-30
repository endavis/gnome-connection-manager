#!/usr/bin/env python3
"""
Claude Code PostToolUse hook that touches a sidecar marker file whenever a CBM MCP tool fires.

The marker file is used by the cbm-code-discovery-gate.py PreToolUse hook to open a
MARKER_TTL_SECONDS (120s) window during which Read/Grep/Glob on source files is allowed
without an additional CBM call.

This hook is intentionally tool-name-agnostic: the ``matcher`` in settings.local.json
(e.g., ``mcp__codebase-memory__.*``) determines which PostToolUse events reach this hook.
Operators with non-default CBM server names tune the matcher, not this file.

Exit codes:
  0 - Always (best-effort; never blocks a tool call)

For documentation and opt-in setup, see: docs/development/ai/token-efficiency-add-ons.md
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Marker file template. {ppid} interpolates to os.getppid() at runtime so the
# marker is scoped per-Claude-Code-session. Must match the constant in
# cbm-code-discovery-gate.py.
MARKER_FILE_TEMPLATE: str = "/tmp/cbm-mcp-used-{ppid}"  # nosec B108 - well-known path is intentional; operators must be able to touch it from any shell. Configurable via this constant.


def main() -> int:
    """Hook entry point. Always returns 0; never blocks. Tests call this directly."""
    try:
        try:
            json.load(sys.stdin)
        except (json.JSONDecodeError, ValueError):
            return 0  # Malformed JSON — best-effort, don't block.

        marker = Path(MARKER_FILE_TEMPLATE.format(ppid=os.getppid()))
        marker.touch()

    except Exception:  # nosec B110 - hook must never raise
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
