"""Tests for the ``context-mode-test-runner-reminder`` PreToolUse advisory hook.

The hook script lives at ``tools/hooks/ai/context-mode-test-runner-reminder.py``. Its
filename contains hyphens, so it isn't directly importable as a module — we load it via
``importlib`` and invoke ``main()`` directly with a stubbed stdin.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import types
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

HOOK_PATH = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "hooks"
    / "ai"
    / "context-mode-test-runner-reminder.py"
)


def _load_hook() -> types.ModuleType:
    """Load the hook script as a fresh module instance."""
    spec = importlib.util.spec_from_file_location("context_mode_test_runner_reminder", HOOK_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"could not load hook from {HOOK_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def hook() -> Iterator[types.ModuleType]:
    """Load a fresh copy of the hook module for each test."""
    module = _load_hook()
    sys.modules["context_mode_test_runner_reminder"] = module
    try:
        yield module
    finally:
        sys.modules.pop("context_mode_test_runner_reminder", None)


def _set_stdin(monkeypatch: pytest.MonkeyPatch, payload: str) -> None:
    """Replace ``sys.stdin`` with a StringIO containing *payload*."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))


def _bash_payload(command: str) -> str:
    """Build a PreToolUse Bash payload for the given command string."""
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})


# ---------------------------------------------------------------------------
# Reminder emitted for test commands
# ---------------------------------------------------------------------------


def test_pytest_command_emits_reminder(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """pytest command triggers the reminder."""
    _set_stdin(monkeypatch, _bash_payload("pytest -v tests/"))
    assert hook.main() == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["hookSpecificOutput"]["additionalContext"] == hook.REMINDER


def test_npm_test_command_emits_reminder(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """npm test command triggers the reminder."""
    _set_stdin(monkeypatch, _bash_payload("npm test"))
    assert hook.main() == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "additionalContext" in data["hookSpecificOutput"]


def test_npm_run_test_command_emits_reminder(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """npm run test command triggers the reminder."""
    _set_stdin(monkeypatch, _bash_payload("npm run test"))
    assert hook.main() == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "additionalContext" in data["hookSpecificOutput"]


def test_go_test_command_emits_reminder(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """go test command triggers the reminder."""
    _set_stdin(monkeypatch, _bash_payload("go test ./..."))
    assert hook.main() == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "additionalContext" in data["hookSpecificOutput"]


def test_cargo_test_command_emits_reminder(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """cargo test command triggers the reminder."""
    _set_stdin(monkeypatch, _bash_payload("cargo test"))
    assert hook.main() == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "additionalContext" in data["hookSpecificOutput"]


def test_mvn_test_command_emits_reminder(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """mvn test command triggers the reminder."""
    _set_stdin(monkeypatch, _bash_payload("mvn test"))
    assert hook.main() == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "additionalContext" in data["hookSpecificOutput"]


def test_gradle_test_command_emits_reminder(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """gradle test command triggers the reminder."""
    _set_stdin(monkeypatch, _bash_payload("gradle test --info"))
    assert hook.main() == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "additionalContext" in data["hookSpecificOutput"]


# ---------------------------------------------------------------------------
# No reminder for non-test commands
# ---------------------------------------------------------------------------


def test_ls_command_no_output(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Non-test command produces no stdout output."""
    _set_stdin(monkeypatch, _bash_payload("ls -la"))
    assert hook.main() == 0
    captured = capsys.readouterr()
    assert captured.out == ""


def test_read_tool_no_output(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Non-Bash tool name produces no stdout output."""
    payload = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "/some/file.py"}})
    _set_stdin(monkeypatch, payload)
    assert hook.main() == 0
    captured = capsys.readouterr()
    assert captured.out == ""


# ---------------------------------------------------------------------------
# Edge cases: malformed / empty input
# ---------------------------------------------------------------------------


def test_malformed_json_exits_0_no_output(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Malformed JSON stdin exits 0 and produces no stdout."""
    _set_stdin(monkeypatch, "not valid json{{")
    assert hook.main() == 0
    captured = capsys.readouterr()
    assert captured.out == ""


def test_empty_tool_input_exits_0_no_output(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Missing tool_input exits 0 and produces no stdout."""
    payload = json.dumps({"tool_name": "Bash"})
    _set_stdin(monkeypatch, payload)
    assert hook.main() == 0
    captured = capsys.readouterr()
    assert captured.out == ""


# ---------------------------------------------------------------------------
# Output JSON shape
# ---------------------------------------------------------------------------


def test_output_hook_event_name_is_pretooluse(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """hookSpecificOutput.hookEventName is 'PreToolUse'."""
    _set_stdin(monkeypatch, _bash_payload("pytest tests/"))
    assert hook.main() == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["hookSpecificOutput"]["hookEventName"] == "PreToolUse"


def test_reminder_text_contains_ctx_batch_execute(hook: types.ModuleType) -> None:
    """REMINDER constant mentions ctx_batch_execute."""
    assert "ctx_batch_execute" in hook.REMINDER


def test_reminder_text_contains_ctx_search(hook: types.ModuleType) -> None:
    """REMINDER constant mentions ctx_search."""
    assert "ctx_search" in hook.REMINDER
