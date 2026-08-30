#!/usr/bin/env python3
"""Claude Code SessionStart wrapper for the context-mode MCP CLI.

Forwards stdin to ``context-mode hook claude-code SessionStart`` and re-emits
stdout/stderr/exit-code. If the ``context-mode`` CLI is not installed, exits 0
silently — non-installation is a no-op, not an error.

For documentation and opt-in setup, see: docs/development/ai/token-efficiency-add-ons.md
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess  # nosec B404 - required to invoke context-mode CLI
import sys

EVENT_NAME = "SessionStart"
CLI_NAME = "context-mode"


def main() -> int:
    """Hook entry point. Forwards stdin to context-mode CLI or exits 0."""
    try:
        if shutil.which(CLI_NAME) is None:
            with contextlib.suppress(Exception):
                sys.stdin.buffer.read()  # drain stdin
            return 0

        try:
            raw = sys.stdin.buffer.read()
        except Exception:  # nosec B110
            return 0

        try:
            result = subprocess.run(  # nosec B603 B607 - shutil.which guard validates path
                [CLI_NAME, "hook", "claude-code", EVENT_NAME],
                input=raw,
                capture_output=True,
                check=False,
            )
        except (FileNotFoundError, OSError):
            return 0

        with contextlib.suppress(Exception):
            sys.stdout.buffer.write(result.stdout)
            sys.stdout.buffer.flush()
        with contextlib.suppress(Exception):
            sys.stderr.buffer.write(result.stderr)
            sys.stderr.buffer.flush()
        return result.returncode

    except Exception:  # nosec B110 - hook must never raise
        return 0


if __name__ == "__main__":
    sys.exit(main())
