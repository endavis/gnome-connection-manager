#!/usr/bin/env python3
"""
Claude Code PostToolUse hook that runs ``ruff --fix`` on edited Python files.

Triggered after ``Edit``/``Write``/``MultiEdit`` tool calls. When the touched
file is a tracked Python source path, runs a fast ``ruff check --fix`` for
unused imports/variables and import ordering, followed by ``ruff format``.

The hook is best-effort: any failure (timeout, ruff missing, malformed payload)
is swallowed and the hook exits 0 so it never blocks a tool call. The next
``doit check`` will surface any genuine issue.

For full documentation, see: docs/development/ai/ruff-fix-hook.md
"""

import json
import os
import subprocess  # nosec B404 - required to invoke ruff
import sys
from pathlib import Path

# Path roots whose Python files are eligible for the auto-fix.
# Mirrors the scope of ``doit format`` / ``doit lint``.
ALLOWED_ROOTS: tuple[str, ...] = ("src/", "tests/", "tools/")

# Specific files at the project root that are also eligible.
ALLOWED_FILES: tuple[str, ...] = ("bootstrap.py",)

# Ruff rule selectors restricted to deterministic, judgment-free fixes:
#   F401 - unused imports
#   F841 - unused local variables
#   I    - import ordering
SELECTED_RULES = "F401,F841,I"

# Per-invocation timeout for ruff (covers both ``check`` and ``format`` calls).
RUFF_TIMEOUT_SECONDS = 30


def _is_in_scope(rel_path: str) -> bool:
    """Return True iff *rel_path* is a Python file inside the auto-fix scope."""
    if not rel_path.endswith(".py"):
        return False
    if rel_path in ALLOWED_FILES:
        return True
    return any(rel_path.startswith(root) for root in ALLOWED_ROOTS)


def run_ruff(path: Path) -> None:
    """Run ``ruff check --fix`` then ``ruff format`` on *path*.

    Best-effort: every exception is swallowed. This function must never raise.
    """
    try:
        subprocess.run(  # nosec B603 B607 - trusted ruff invocation
            [
                "uv",
                "run",
                "ruff",
                "check",
                "--fix",
                "--select",
                SELECTED_RULES,
                "--quiet",
                str(path),
            ],
            capture_output=True,
            timeout=RUFF_TIMEOUT_SECONDS,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    except Exception:  # nosec B110 - hook must never raise; errors would block tool calls
        pass

    try:
        subprocess.run(  # nosec B603 B607 - trusted ruff invocation
            ["uv", "run", "ruff", "format", "--quiet", str(path)],
            capture_output=True,
            timeout=RUFF_TIMEOUT_SECONDS,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    except Exception:  # nosec B110 - hook must never raise; errors would block tool calls
        pass


def _normalize_path(raw_path: str, project_dir: str) -> str | None:
    """Return *raw_path* as a project-relative POSIX-style string.

    Returns None if the path is absolute and outside the project directory
    (we never auto-fix files we don't own).
    """
    path = Path(raw_path)
    if not path.is_absolute():
        return raw_path

    if not project_dir:
        return None

    try:
        return path.relative_to(project_dir).as_posix()
    except ValueError:
        return None


def main() -> int:
    """Hook entry point. Always returns 0; tests call this directly."""
    try:
        try:
            input_data = json.load(sys.stdin)
        except (json.JSONDecodeError, ValueError):
            return 0

        if not isinstance(input_data, dict):
            return 0

        tool_input = input_data.get("tool_input")
        if not isinstance(tool_input, dict):
            return 0

        raw_file_path = tool_input.get("file_path")
        if not isinstance(raw_file_path, str) or not raw_file_path:
            return 0

        project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
        rel_path = _normalize_path(raw_file_path, project_dir)
        if rel_path is None:
            return 0

        if not _is_in_scope(rel_path):
            return 0

        # Resolve to an absolute path for the existence check and ruff call.
        target = Path(project_dir) / rel_path if project_dir else Path(rel_path)
        if not target.is_file():
            return 0

        run_ruff(target)
    except Exception:  # hook must never raise
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
