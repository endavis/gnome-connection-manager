"""Tests for the ``session-resume-restore`` SessionStart hook.

The hook script lives at ``tools/hooks/ai/session-resume-restore.py``. Its filename
contains hyphens, so it isn't directly importable — we load it via ``importlib`` and
invoke ``main()`` directly with a stubbed stdin.
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
    Path(__file__).resolve().parents[1] / "tools" / "hooks" / "ai" / "session-resume-restore.py"
)


def _load_hook() -> types.ModuleType:
    """Load the hook script as a fresh module instance."""
    spec = importlib.util.spec_from_file_location("session_resume_restore", HOOK_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"could not load hook from {HOOK_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def hook() -> Iterator[types.ModuleType]:
    """Load a fresh copy of the hook module for each test."""
    module = _load_hook()
    sys.modules["session_resume_restore"] = module
    try:
        yield module
    finally:
        sys.modules.pop("session_resume_restore", None)


def _set_stdin(monkeypatch: pytest.MonkeyPatch, payload: str) -> None:
    """Replace ``sys.stdin`` with a StringIO containing *payload*."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))


def _payload(cwd: str) -> str:
    """Build a minimal SessionStart payload."""
    return json.dumps({"cwd": cwd})


def _make_checkpoint(checkpoints_dir: Path, name: str, body: str = "checkpoint body") -> Path:
    """Create a checkpoint file under *checkpoints_dir* and return its path."""
    checkpoints_dir.mkdir(parents=True, exist_ok=True)
    p = checkpoints_dir / name
    p.write_text(body, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Happy path: single auto-precompact checkpoint
# ---------------------------------------------------------------------------


def test_single_checkpoint_returned(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Single *-auto-precompact*.md → stdout JSON with additionalContext = file body."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    checkpoints_dir = tmp_path / "tmp" / "checkpoints"
    _make_checkpoint(checkpoints_dir, "9999999000-auto-precompact.md", "resume here")
    _set_stdin(monkeypatch, _payload(str(tmp_path)))

    assert hook.main() == 0

    captured = capsys.readouterr()
    out = json.loads(captured.out)
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert out["hookSpecificOutput"]["additionalContext"] == "resume here"


# ---------------------------------------------------------------------------
# Multiple checkpoints → lexically smallest (newest) selected
# ---------------------------------------------------------------------------


def test_multiple_checkpoints_newest_selected(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Lexically smallest name (smallest inv_epoch → newest) is selected.

    inv_epoch = 9999999999 - int(time.time()): it *decreases* as time advances.
    A smaller inv_epoch means more time has passed → the file was created later → it is newer.
    sorted() ascending picks the smallest inv_epoch first, which is the newest file.
    """
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    checkpoints_dir = tmp_path / "tmp" / "checkpoints"
    # Larger inv_epoch = fewer seconds elapsed → created earlier → older.
    _make_checkpoint(checkpoints_dir, "9999999000-auto-precompact.md", "older")
    # Smaller inv_epoch = more seconds elapsed → created later → newer.
    _make_checkpoint(checkpoints_dir, "9999998000-auto-precompact.md", "newer")
    _set_stdin(monkeypatch, _payload(str(tmp_path)))

    assert hook.main() == 0

    captured = capsys.readouterr()
    out = json.loads(captured.out)
    assert out["hookSpecificOutput"]["additionalContext"] == "newer"


# ---------------------------------------------------------------------------
# No checkpoint files → no-op
# ---------------------------------------------------------------------------


def test_no_checkpoints_is_noop(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No matching files → no stdout, exits 0."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    checkpoints_dir = tmp_path / "tmp" / "checkpoints"
    checkpoints_dir.mkdir(parents=True, exist_ok=True)
    _set_stdin(monkeypatch, _payload(str(tmp_path)))

    assert hook.main() == 0
    assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# tmp/checkpoints/ doesn't exist → no-op
# ---------------------------------------------------------------------------


def test_missing_checkpoints_dir_is_noop(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Missing tmp/checkpoints/ directory → no-op, exits 0."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    # Do NOT create the directory.
    _set_stdin(monkeypatch, _payload(str(tmp_path)))

    assert hook.main() == 0
    assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# CLAUDE_NO_AUTO_RESTORE=1 → no-op even when checkpoints exist
# ---------------------------------------------------------------------------


def test_no_auto_restore_env_skips(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLAUDE_NO_AUTO_RESTORE=1 → no-op even when a checkpoint exists."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("CLAUDE_NO_AUTO_RESTORE", "1")
    checkpoints_dir = tmp_path / "tmp" / "checkpoints"
    _make_checkpoint(checkpoints_dir, "9999999000-auto-precompact.md", "should not restore")
    _set_stdin(monkeypatch, _payload(str(tmp_path)))

    assert hook.main() == 0
    assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# Manual /checkpoint files (no auto-precompact slug) ignored by default glob
# ---------------------------------------------------------------------------


def test_manual_checkpoint_ignored_by_default(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Manual checkpoint (no auto-precompact slug) is ignored by default glob."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.delenv("CLAUDE_RESTORE_ANY", raising=False)
    checkpoints_dir = tmp_path / "tmp" / "checkpoints"
    _make_checkpoint(checkpoints_dir, "9999999000-my-manual-checkpoint.md", "manual")
    _set_stdin(monkeypatch, _payload(str(tmp_path)))

    assert hook.main() == 0
    assert capsys.readouterr().out == ""


def test_restore_any_env_includes_manual_checkpoint(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLAUDE_RESTORE_ANY=1 widens the glob to include manual checkpoints."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("CLAUDE_RESTORE_ANY", "1")
    checkpoints_dir = tmp_path / "tmp" / "checkpoints"
    _make_checkpoint(checkpoints_dir, "9999999000-my-manual-checkpoint.md", "manual body")
    _set_stdin(monkeypatch, _payload(str(tmp_path)))

    assert hook.main() == 0

    captured = capsys.readouterr()
    out = json.loads(captured.out)
    assert out["hookSpecificOutput"]["additionalContext"] == "manual body"


# ---------------------------------------------------------------------------
# Malformed stdin JSON → no-op
# ---------------------------------------------------------------------------


def test_malformed_stdin_is_noop(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Invalid JSON on stdin → no-op, exits 0."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    _set_stdin(monkeypatch, "not valid json {{")

    assert hook.main() == 0
    assert capsys.readouterr().out == ""
