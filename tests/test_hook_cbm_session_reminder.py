"""Tests for the ``cbm-session-reminder`` SessionStart hook.

The hook script lives at ``tools/hooks/ai/cbm-session-reminder.py``. Its filename
contains hyphens, so it isn't directly importable as a module — we load it via
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
    Path(__file__).resolve().parents[1] / "tools" / "hooks" / "ai" / "cbm-session-reminder.py"
)

# Sibling reminder file (used to verify real content in integration-style tests).
REAL_REMINDER_PATH = (
    Path(__file__).resolve().parents[1] / "tools" / "hooks" / "ai" / "cbm-session-reminder.md"
)


def _load_hook() -> types.ModuleType:
    """Load the hook script as a fresh module instance."""
    spec = importlib.util.spec_from_file_location("cbm_session_reminder", HOOK_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"could not load hook from {HOOK_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def hook() -> Iterator[types.ModuleType]:
    """Load a fresh copy of the hook module for each test."""
    module = _load_hook()
    sys.modules["cbm_session_reminder"] = module
    try:
        yield module
    finally:
        sys.modules.pop("cbm_session_reminder", None)


def _set_stdin(monkeypatch: pytest.MonkeyPatch, payload: str) -> None:
    """Replace ``sys.stdin`` with a StringIO containing *payload*."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))


def _session_start_payload(trigger: str = "compact") -> str:
    """Build a SessionStart payload with the given trigger."""
    return json.dumps({"trigger": trigger, "cwd": "/some/project"})


# ---------------------------------------------------------------------------
# Stdout JSON shape
# ---------------------------------------------------------------------------


def test_stdout_is_valid_json(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Hook emits valid JSON on stdout."""
    reminder = tmp_path / "reminder.md"
    reminder.write_text("# Reminder\nUse CBM tools.", encoding="utf-8")
    monkeypatch.setattr(hook, "REMINDER_TEXT_PATH", reminder)

    _set_stdin(monkeypatch, _session_start_payload())
    assert hook.main() == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert isinstance(data, dict)


def test_stdout_hook_event_name_is_session_start(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """hookSpecificOutput.hookEventName is 'SessionStart'."""
    reminder = tmp_path / "reminder.md"
    reminder.write_text("# Reminder\nUse CBM tools.", encoding="utf-8")
    monkeypatch.setattr(hook, "REMINDER_TEXT_PATH", reminder)

    _set_stdin(monkeypatch, _session_start_payload())
    assert hook.main() == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["hookSpecificOutput"]["hookEventName"] == "SessionStart"


def test_stdout_additional_context_matches_reminder_file(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """additionalContext equals the full contents of the reminder file."""
    reminder_body = "# CBM Reminder\nUse search_graph first.\n"
    reminder = tmp_path / "reminder.md"
    reminder.write_text(reminder_body, encoding="utf-8")
    monkeypatch.setattr(hook, "REMINDER_TEXT_PATH", reminder)

    _set_stdin(monkeypatch, _session_start_payload())
    assert hook.main() == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["hookSpecificOutput"]["additionalContext"] == reminder_body


# ---------------------------------------------------------------------------
# Real reminder file integration
# ---------------------------------------------------------------------------


def test_real_reminder_file_produces_non_empty_context(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The shipped cbm-session-reminder.md produces non-empty additionalContext."""
    # Uses the real REMINDER_TEXT_PATH from the hook (no monkeypatch needed).
    _set_stdin(monkeypatch, _session_start_payload())
    assert hook.main() == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert len(data["hookSpecificOutput"]["additionalContext"]) > 0


# ---------------------------------------------------------------------------
# Missing reminder file: degrade gracefully
# ---------------------------------------------------------------------------


def test_missing_reminder_file_exits_0_no_stdout(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When reminder file is missing, hook exits 0 and produces no stdout."""
    monkeypatch.setattr(hook, "REMINDER_TEXT_PATH", tmp_path / "nonexistent.md")

    _set_stdin(monkeypatch, _session_start_payload())
    assert hook.main() == 0

    captured = capsys.readouterr()
    assert captured.out == ""


# ---------------------------------------------------------------------------
# Malformed JSON: best-effort, no crash
# ---------------------------------------------------------------------------


def test_malformed_json_exits_0(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed JSON exits 0 — the reminder hook never blocks (best-effort)."""
    _set_stdin(monkeypatch, "not valid json{{")
    assert hook.main() == 0
