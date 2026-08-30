"""Tests for the ``bash-ban-raw-tools`` PreToolUse hook.

The hook script lives at ``tools/hooks/ai/bash-ban-raw-tools.py``. Its filename
contains hyphens, so it isn't directly importable as a module — we load it via
``importlib`` and invoke ``main()`` directly with a stubbed stdin.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import time
import types
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

HOOK_PATH = Path(__file__).resolve().parents[1] / "tools" / "hooks" / "ai" / "bash-ban-raw-tools.py"


def _load_hook() -> types.ModuleType:
    """Load the hook script as a fresh module instance."""
    spec = importlib.util.spec_from_file_location("bash_ban_raw_tools", HOOK_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"could not load hook from {HOOK_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def hook() -> Iterator[types.ModuleType]:
    """Load a fresh copy of the hook module for each test."""
    module = _load_hook()
    sys.modules["bash_ban_raw_tools"] = module
    try:
        yield module
    finally:
        sys.modules.pop("bash_ban_raw_tools", None)


def _set_stdin(monkeypatch: pytest.MonkeyPatch, payload: str) -> None:
    """Replace ``sys.stdin`` with a StringIO containing *payload*."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))


def _bash_payload(command: str, cwd: str | None = None) -> str:
    """Build a Bash tool payload for the given command.

    If *cwd* is provided it is included in the payload so the hook can resolve
    the per-project unlock path without relying on ``CLAUDE_PROJECT_DIR``.
    """
    data: dict[str, object] = {"tool_name": "Bash", "tool_input": {"command": command}}
    if cwd is not None:
        data["cwd"] = cwd
    return json.dumps(data)


def _non_bash_payload(tool_name: str) -> str:
    """Build a non-Bash tool payload."""
    return json.dumps({"tool_name": tool_name, "tool_input": {"file_path": "README.md"}})


def _make_unlock(project_root: Path) -> Path:
    """Create the per-project unlock file and return its path."""
    unlock = project_root / "tmp" / "agents" / "claude" / "bash-raw-unlock"
    unlock.parent.mkdir(parents=True, exist_ok=True)
    unlock.touch()
    return unlock


# ---------------------------------------------------------------------------
# Allow cases
# ---------------------------------------------------------------------------


def test_non_bash_tool_is_allowed(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-Bash tools (e.g. Read) are always allowed."""
    _set_stdin(monkeypatch, _non_bash_payload("Read"))
    with pytest.raises(SystemExit) as exc_info:
        sys.exit(hook.main())
    assert exc_info.value.code == 0


def test_benign_bash_command_is_allowed(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Safe Bash commands like ``ls -la`` are allowed."""
    _set_stdin(monkeypatch, _bash_payload("ls -la"))
    with pytest.raises(SystemExit) as exc_info:
        sys.exit(hook.main())
    assert exc_info.value.code == 0


def test_malformed_json_exits_1(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed JSON input exits with code 1 (parity with block-dangerous-commands)."""
    _set_stdin(monkeypatch, "not valid json{{")
    with pytest.raises(SystemExit) as exc_info:
        sys.exit(hook.main())
    assert exc_info.value.code == 1


def test_banned_word_as_non_leading_non_pipe_token_is_allowed(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``echo cat`` — banned word is not the leading token and not after a pipe."""
    _set_stdin(monkeypatch, _bash_payload("echo cat"))
    with pytest.raises(SystemExit) as exc_info:
        sys.exit(hook.main())
    assert exc_info.value.code == 0


@pytest.mark.parametrize(
    "command",
    [
        "ls | head",
        "ls | tail -100",
        "cmd | head -n 5",
    ],
)
def test_piped_truncator_is_allowed(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    """Piped truncators (``... | head``, ``... | tail``) are allowed — no native replacement."""
    _set_stdin(monkeypatch, _bash_payload(command))
    with pytest.raises(SystemExit) as exc_info:
        sys.exit(hook.main())
    assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# Block: banned leading commands
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "cat README.md",
        "head foo.txt",
        "tail -f log.txt",
        "find . -name '*.py'",
        "grep pattern file.py",
        "rg pattern",
        "wc -l file.txt",
    ],
)
def test_banned_leading_command_exits_2(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    """Each banned leading command is blocked with exit code 2."""
    _set_stdin(monkeypatch, _bash_payload(command))
    with pytest.raises(SystemExit) as exc_info:
        sys.exit(hook.main())
    assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# Escape hatch: unlock file
# ---------------------------------------------------------------------------


def test_fresh_unlock_file_allows_banned_command(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """When unlock file exists and mtime is within window, banned commands are allowed."""
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    _make_unlock(tmp_path)

    _set_stdin(monkeypatch, _bash_payload("cat README.md", cwd=str(tmp_path)))
    with pytest.raises(SystemExit) as exc_info:
        sys.exit(hook.main())
    assert exc_info.value.code == 0


def test_stale_unlock_file_blocks_banned_command(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """When unlock file mtime is older than UNLOCK_WINDOW_SECONDS, command is blocked."""
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    unlock = _make_unlock(tmp_path)
    # Set mtime to well past the window
    stale_mtime = time.time() - (hook.UNLOCK_WINDOW_SECONDS + 60)
    os.utime(str(unlock), (stale_mtime, stale_mtime))

    _set_stdin(monkeypatch, _bash_payload("cat README.md", cwd=str(tmp_path)))
    with pytest.raises(SystemExit) as exc_info:
        sys.exit(hook.main())
    assert exc_info.value.code == 2


def test_missing_unlock_file_blocks_banned_command(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """When unlock file does not exist, banned commands are blocked."""
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    # Do NOT create the file; just pass a valid cwd so path resolution works

    _set_stdin(monkeypatch, _bash_payload("grep pattern file.py", cwd=str(tmp_path)))
    with pytest.raises(SystemExit) as exc_info:
        sys.exit(hook.main())
    assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# Stderr reason content checks
# ---------------------------------------------------------------------------


def test_stderr_reason_mentions_offending_command(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The stderr block reason mentions the offending command."""
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    _set_stdin(monkeypatch, _bash_payload("cat README.md", cwd=str(tmp_path)))

    with pytest.raises(SystemExit):
        sys.exit(hook.main())

    captured = capsys.readouterr()
    assert "cat" in captured.err


def test_stderr_reason_mentions_unlock_file(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The stderr block reason mentions the escape hatch (per-project unlock path)."""
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    _set_stdin(monkeypatch, _bash_payload("cat README.md", cwd=str(tmp_path)))

    with pytest.raises(SystemExit):
        sys.exit(hook.main())

    captured = capsys.readouterr()
    expected_path = str(tmp_path / "tmp" / "agents" / "claude" / "bash-raw-unlock")
    assert expected_path in captured.err


# ---------------------------------------------------------------------------
# New tests: per-project isolation, fail-closed, env precedence
# ---------------------------------------------------------------------------


def test_unlock_file_in_one_project_does_not_unlock_another(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Unlock file in project_a does NOT unlock commands run with cwd=project_b."""
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    project_a = tmp_path / "project_a"
    project_b = tmp_path / "project_b"
    project_a.mkdir()
    project_b.mkdir()

    # Touch unlock in project_a only
    _make_unlock(project_a)

    # Run hook as if we're in project_b — should still be blocked
    _set_stdin(monkeypatch, _bash_payload("cat README.md", cwd=str(project_b)))
    with pytest.raises(SystemExit) as exc_info:
        sys.exit(hook.main())
    assert exc_info.value.code == 2


def test_no_project_dir_blocks_with_unlock_unavailable_message(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No CLAUDE_PROJECT_DIR and no cwd: command is blocked; stderr says hatch unavailable."""
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    # No cwd in payload
    _set_stdin(monkeypatch, _bash_payload("cat README.md"))

    with pytest.raises(SystemExit) as exc_info:
        sys.exit(hook.main())

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "unavailable" in captured.err.lower() or "project root" in captured.err.lower()


def test_claude_project_dir_env_overrides_cwd(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """CLAUDE_PROJECT_DIR env var wins over cwd in the payload."""
    project_a = tmp_path / "project_a"
    project_b = tmp_path / "project_b"
    project_a.mkdir()
    project_b.mkdir()

    # Unlock only in project_a; env points to project_a; cwd points to project_b
    _make_unlock(project_a)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project_a))

    # Even though cwd is project_b, env var should win → allowed
    _set_stdin(monkeypatch, _bash_payload("cat README.md", cwd=str(project_b)))
    with pytest.raises(SystemExit) as exc_info:
        sys.exit(hook.main())
    assert exc_info.value.code == 0
