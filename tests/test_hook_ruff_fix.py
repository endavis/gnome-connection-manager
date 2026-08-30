"""Tests for the ``ruff-fix-on-edit`` PostToolUse hook.

The hook script lives at ``tools/hooks/ai/ruff-fix-on-edit.py``. Its filename
contains hyphens, so it isn't directly importable as a module — we load it via
``importlib`` and invoke ``main()`` directly with a stubbed stdin.
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

HOOK_PATH = Path(__file__).resolve().parents[1] / "tools" / "hooks" / "ai" / "ruff-fix-on-edit.py"


def _load_hook() -> types.ModuleType:
    """Load the hook script as a fresh module instance."""
    spec = importlib.util.spec_from_file_location("ruff_fix_on_edit", HOOK_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"could not load hook from {HOOK_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def hook(monkeypatch: pytest.MonkeyPatch) -> Iterator[types.ModuleType]:
    """Load a fresh copy of the hook module for each test."""
    module = _load_hook()
    sys.modules["ruff_fix_on_edit"] = module
    try:
        yield module
    finally:
        sys.modules.pop("ruff_fix_on_edit", None)


@pytest.fixture
def call_log(hook: types.ModuleType, monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Replace ``run_ruff`` with a recorder; return the list of received paths."""
    calls: list[Path] = []

    def _record(path: Path) -> None:
        calls.append(path)

    monkeypatch.setattr(hook, "run_ruff", _record)
    return calls


def _set_stdin(monkeypatch: pytest.MonkeyPatch, payload: str) -> None:
    """Replace ``sys.stdin`` with a StringIO containing *payload*."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))


def _payload(file_path: str) -> str:
    """Build a minimal Edit-tool payload referencing *file_path*."""
    return json.dumps({"tool_name": "Edit", "tool_input": {"file_path": file_path}})


def _setup_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point ``CLAUDE_PROJECT_DIR`` at *tmp_path*."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))


def _touch(tmp_path: Path, rel: str, contents: str = "x = 1\n") -> Path:
    """Create *rel* under *tmp_path* with *contents* and return the absolute path."""
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(contents, encoding="utf-8")
    return target


def test_non_python_file_is_noop(
    hook: types.ModuleType,
    call_log: list[Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """README.md (non-.py) should not invoke ruff."""
    _setup_project(tmp_path, monkeypatch)
    _touch(tmp_path, "README.md", "# hi\n")
    _set_stdin(monkeypatch, _payload("README.md"))

    assert hook.main() == 0
    assert call_log == []


def test_python_file_outside_scope_is_noop(
    hook: types.ModuleType,
    call_log: list[Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A .py file outside src/tests/tools and not bootstrap.py is skipped."""
    _setup_project(tmp_path, monkeypatch)
    _touch(tmp_path, "scripts/adhoc.py")
    _set_stdin(monkeypatch, _payload("scripts/adhoc.py"))

    assert hook.main() == 0
    assert call_log == []


def test_python_file_in_src_invokes_ruff(
    hook: types.ModuleType,
    call_log: list[Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """src/foo.py triggers a ruff fix."""
    _setup_project(tmp_path, monkeypatch)
    target = _touch(tmp_path, "src/foo.py")
    _set_stdin(monkeypatch, _payload("src/foo.py"))

    assert hook.main() == 0
    assert call_log == [target]


def test_python_file_in_tests_invokes_ruff(
    hook: types.ModuleType,
    call_log: list[Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """tests/test_foo.py triggers a ruff fix."""
    _setup_project(tmp_path, monkeypatch)
    target = _touch(tmp_path, "tests/test_foo.py")
    _set_stdin(monkeypatch, _payload("tests/test_foo.py"))

    assert hook.main() == 0
    assert call_log == [target]


def test_python_file_in_tools_invokes_ruff(
    hook: types.ModuleType,
    call_log: list[Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """tools/doit/github.py triggers a ruff fix."""
    _setup_project(tmp_path, monkeypatch)
    target = _touch(tmp_path, "tools/doit/github.py", "pass\n")
    _set_stdin(monkeypatch, _payload("tools/doit/github.py"))

    assert hook.main() == 0
    assert call_log == [target]


def test_bootstrap_py_invokes_ruff(
    hook: types.ModuleType,
    call_log: list[Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """bootstrap.py at the project root triggers a ruff fix."""
    _setup_project(tmp_path, monkeypatch)
    target = _touch(tmp_path, "bootstrap.py")
    _set_stdin(monkeypatch, _payload("bootstrap.py"))

    assert hook.main() == 0
    assert call_log == [target]


def test_missing_file_is_noop(
    hook: types.ModuleType,
    call_log: list[Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A path that does not exist on disk is skipped (likely a deletion)."""
    _setup_project(tmp_path, monkeypatch)
    # Note: we do NOT create tests/nope.py.
    _set_stdin(monkeypatch, _payload("tests/nope.py"))

    assert hook.main() == 0
    assert call_log == []


def test_ruff_failure_still_exits_zero(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """If ``run_ruff`` raises a generic exception, main() still returns 0."""
    _setup_project(tmp_path, monkeypatch)
    _touch(tmp_path, "src/foo.py")

    def _boom(_path: Path) -> None:
        raise RuntimeError("ruff exploded")

    monkeypatch.setattr(hook, "run_ruff", _boom)
    _set_stdin(monkeypatch, _payload("src/foo.py"))

    assert hook.main() == 0


def test_ruff_timeout_still_exits_zero(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """If ``run_ruff`` raises ``TimeoutExpired``, main() still returns 0."""
    _setup_project(tmp_path, monkeypatch)
    _touch(tmp_path, "src/foo.py")

    def _timeout(_path: Path) -> None:
        raise subprocess.TimeoutExpired(cmd="ruff", timeout=30)

    monkeypatch.setattr(hook, "run_ruff", _timeout)
    _set_stdin(monkeypatch, _payload("src/foo.py"))

    assert hook.main() == 0


def test_malformed_stdin_is_noop(
    hook: types.ModuleType,
    call_log: list[Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Invalid JSON on stdin returns 0 with no ruff call."""
    _setup_project(tmp_path, monkeypatch)
    _set_stdin(monkeypatch, "not json")

    assert hook.main() == 0
    assert call_log == []


def test_missing_tool_input_is_noop(
    hook: types.ModuleType,
    call_log: list[Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """JSON without ``tool_input.file_path`` returns 0 with no ruff call."""
    _setup_project(tmp_path, monkeypatch)
    _set_stdin(monkeypatch, json.dumps({"tool_name": "Edit", "tool_input": {}}))

    assert hook.main() == 0
    assert call_log == []


def test_absolute_path_inside_project(
    hook: types.ModuleType,
    call_log: list[Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An absolute path inside the project is normalized and fixed."""
    _setup_project(tmp_path, monkeypatch)
    target = _touch(tmp_path, "src/foo.py")
    _set_stdin(monkeypatch, _payload(str(target)))

    assert hook.main() == 0
    assert call_log == [target]
