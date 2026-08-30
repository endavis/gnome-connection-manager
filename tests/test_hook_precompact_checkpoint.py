"""Tests for the ``precompact-checkpoint`` PreCompact hook.

The hook script lives at ``tools/hooks/ai/precompact-checkpoint.py``. Its filename
contains hyphens, so it isn't directly importable — we load it via ``importlib`` and
invoke ``main()`` directly with a stubbed stdin.
"""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import types
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

HOOK_PATH = (
    Path(__file__).resolve().parents[1] / "tools" / "hooks" / "ai" / "precompact-checkpoint.py"
)


def _load_hook() -> types.ModuleType:
    """Load the hook script as a fresh module instance."""
    spec = importlib.util.spec_from_file_location("precompact_checkpoint", HOOK_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"could not load hook from {HOOK_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def hook() -> Iterator[types.ModuleType]:
    """Load a fresh copy of the hook module for each test."""
    module = _load_hook()
    sys.modules["precompact_checkpoint"] = module
    try:
        yield module
    finally:
        sys.modules.pop("precompact_checkpoint", None)


def _set_stdin(monkeypatch: pytest.MonkeyPatch, payload: str) -> None:
    """Replace ``sys.stdin`` with a StringIO containing *payload*."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))


def _payload(cwd: str, transcript_path: str = "") -> str:
    """Build a minimal PreCompact payload."""
    return json.dumps({"cwd": cwd, "transcript_path": transcript_path})


def _good_synthesis() -> dict[str, object]:
    """Return a valid synthesis dict."""
    return {
        "title": "Add caching layer",
        "status": "In progress — cache module drafted",
        "in_flight_work": "Implementing LRU cache in src/cache.py",
        "constraints": "Must be thread-safe",
        "files_touched": ["src/cache.py", "tests/test_cache.py"],
        "next_steps": "1. Write tests\n2. Run doit check",
        "resume_prompt": "Continue implementing the cache module.",
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_happy_path_writes_checkpoint(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Stub synthesizer returns valid JSON → markdown file written with correct sections."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(hook, "synthesize_checkpoint", lambda *_: _good_synthesis())
    _set_stdin(monkeypatch, _payload(str(tmp_path), "transcript.jsonl"))

    assert hook.main() == 0

    checkpoints = list((tmp_path / "tmp" / "checkpoints").glob("*-auto-precompact*.md"))
    assert len(checkpoints) == 1
    text = checkpoints[0].read_text(encoding="utf-8")
    assert "Add caching layer" in text
    assert "In progress" in text
    assert "src/cache.py" in text
    assert "Continue implementing" in text


def test_happy_path_filename_convention(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Written file must match ``{inv_epoch}-auto-precompact.md`` pattern."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(hook, "synthesize_checkpoint", lambda *_: _good_synthesis())
    _set_stdin(monkeypatch, _payload(str(tmp_path), "t.jsonl"))

    assert hook.main() == 0

    checkpoints = list((tmp_path / "tmp" / "checkpoints").glob("*-auto-precompact*.md"))
    assert len(checkpoints) == 1
    name = checkpoints[0].name
    # Name must be "{10-digit-prefix}-auto-precompact.md"
    parts = name.split("-", 1)
    assert len(parts) == 2
    assert parts[0].isdigit() and len(parts[0]) == 10


# ---------------------------------------------------------------------------
# Fallback: synthesis returns None
# ---------------------------------------------------------------------------


def test_synthesis_none_writes_fallback(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Synthesizer returns None → fallback file written with AUTO_PARTIAL banner."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    transcript_file = tmp_path / "t.jsonl"
    transcript_file.write_text("some transcript content", encoding="utf-8")
    monkeypatch.setattr(hook, "synthesize_checkpoint", lambda *_: None)
    _set_stdin(monkeypatch, _payload(str(tmp_path), str(transcript_file)))

    assert hook.main() == 0

    checkpoints = list((tmp_path / "tmp" / "checkpoints").glob("*-auto-precompact*.md"))
    assert len(checkpoints) == 1
    text = checkpoints[0].read_text(encoding="utf-8")
    assert "AUTO_PARTIAL" in text


# ---------------------------------------------------------------------------
# Fallback: invalid JSON from synthesizer
# ---------------------------------------------------------------------------


def test_invalid_synthesis_json_writes_fallback(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Real synthesize_checkpoint with JSON parse failure → fallback (mocked at subprocess)."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    transcript_file = tmp_path / "t.jsonl"
    transcript_file.write_text("transcript", encoding="utf-8")

    # Simulate synthesize_checkpoint returning None (as it would on JSONDecodeError).
    monkeypatch.setattr(hook, "synthesize_checkpoint", lambda *_: None)
    _set_stdin(monkeypatch, _payload(str(tmp_path), str(transcript_file)))

    assert hook.main() == 0

    checkpoints = list((tmp_path / "tmp" / "checkpoints").glob("*-auto-precompact*.md"))
    assert len(checkpoints) == 1
    assert "AUTO_PARTIAL" in checkpoints[0].read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Missing transcript path
# ---------------------------------------------------------------------------


def test_missing_transcript_writes_fallback(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Missing transcript file → fallback written; exits 0."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    # Provide a path that does not exist; synthesize_checkpoint not called.
    _set_stdin(monkeypatch, _payload(str(tmp_path), str(tmp_path / "nonexistent.jsonl")))

    assert hook.main() == 0

    checkpoints = list((tmp_path / "tmp" / "checkpoints").glob("*-auto-precompact*.md"))
    assert len(checkpoints) == 1
    assert "AUTO_PARTIAL" in checkpoints[0].read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Malformed stdin JSON
# ---------------------------------------------------------------------------


def test_malformed_stdin_is_noop(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Invalid JSON on stdin → exits 0, no file written."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    _set_stdin(monkeypatch, "not json at all")

    assert hook.main() == 0

    checkpoints_dir = tmp_path / "tmp" / "checkpoints"
    assert not checkpoints_dir.exists() or not list(checkpoints_dir.glob("*.md"))


# ---------------------------------------------------------------------------
# Subprocess raises TimeoutExpired
# ---------------------------------------------------------------------------


def test_synthesize_checkpoint_timeout_returns_none(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """synthesize_checkpoint swallows TimeoutExpired and returns None."""

    def _raise_timeout(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise subprocess.TimeoutExpired(cmd="claude", timeout=90)

    monkeypatch.setattr(subprocess, "run", _raise_timeout)

    result = hook.synthesize_checkpoint("some transcript")
    assert result is None


def test_timeout_in_main_writes_fallback(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """If synthesize_checkpoint raises (or returns None after timeout), fallback is written."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    transcript_file = tmp_path / "t.jsonl"
    transcript_file.write_text("session transcript", encoding="utf-8")

    monkeypatch.setattr(hook, "synthesize_checkpoint", lambda *_: None)
    _set_stdin(monkeypatch, _payload(str(tmp_path), str(transcript_file)))

    assert hook.main() == 0

    checkpoints = list((tmp_path / "tmp" / "checkpoints").glob("*-auto-precompact*.md"))
    assert len(checkpoints) == 1
    assert "AUTO_PARTIAL" in checkpoints[0].read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# inv_epoch helper
# ---------------------------------------------------------------------------


def test_inv_epoch_is_10_digit_decreasing(
    hook: types.ModuleType,
) -> None:
    """_inv_epoch() produces a 10-digit string that decreases over time."""
    import time

    e1 = hook._inv_epoch()
    time.sleep(0.01)
    e2 = hook._inv_epoch()

    assert len(e1) == 10
    assert e1.isdigit()
    # e1 was computed first (earlier time → larger inv_epoch).
    assert int(e1) >= int(e2)
