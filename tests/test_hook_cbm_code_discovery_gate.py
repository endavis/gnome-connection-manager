"""Tests for the ``cbm-code-discovery-gate`` PreToolUse hook.

The hook script lives at ``tools/hooks/ai/cbm-code-discovery-gate.py``. Its filename
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

HOOK_PATH = (
    Path(__file__).resolve().parents[1] / "tools" / "hooks" / "ai" / "cbm-code-discovery-gate.py"
)


def _load_hook() -> types.ModuleType:
    """Load the hook script as a fresh module instance."""
    spec = importlib.util.spec_from_file_location("cbm_code_discovery_gate", HOOK_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"could not load hook from {HOOK_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def hook() -> Iterator[types.ModuleType]:
    """Load a fresh copy of the hook module for each test."""
    module = _load_hook()
    sys.modules["cbm_code_discovery_gate"] = module
    try:
        yield module
    finally:
        sys.modules.pop("cbm_code_discovery_gate", None)


def _set_stdin(monkeypatch: pytest.MonkeyPatch, payload: str) -> None:
    """Replace ``sys.stdin`` with a StringIO containing *payload*."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))


def _read_payload(path: str) -> str:
    """Build a Read tool payload for the given path."""
    return json.dumps({"tool_name": "Read", "tool_input": {"file_path": path}})


def _grep_payload(path: str | None = None) -> str:
    """Build a Grep tool payload. If path is None, simulate a whole-repo search."""
    tool_input: dict[str, str] = {}
    if path is not None:
        tool_input["path"] = path
    return json.dumps({"tool_name": "Grep", "tool_input": tool_input})


def _glob_payload(path: str | None = None) -> str:
    """Build a Glob tool payload. If path is None, simulate a whole-repo search."""
    tool_input: dict[str, str] = {}
    if path is not None:
        tool_input["path"] = path
    return json.dumps({"tool_name": "Glob", "tool_input": tool_input})


def _non_gated_payload(tool_name: str) -> str:
    """Build a non-gated tool payload."""
    return json.dumps({"tool_name": tool_name, "tool_input": {"command": "ls -la"}})


# ---------------------------------------------------------------------------
# Allow cases: non-gated tool
# ---------------------------------------------------------------------------


def test_non_gated_tool_is_allowed(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-gated tools (e.g. Bash) are always allowed — gate only applies to Read/Grep/Glob."""
    _set_stdin(monkeypatch, _non_gated_payload("Bash"))
    with pytest.raises(SystemExit) as exc_info:
        sys.exit(hook.main())
    assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# Allow cases: allow-list extension matches
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "pyproject.toml",
        "README.md",
        "requirements.txt",
        "config.yaml",
        "config.yml",
        "data.json",
        "poetry.lock",
        ".env",
        "setup.sh",
    ],
)
def test_allowlist_extension_allows_read(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    """Read on an allow-listed extension always passes through."""
    _set_stdin(monkeypatch, _read_payload(path))
    with pytest.raises(SystemExit) as exc_info:
        sys.exit(hook.main())
    assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# Allow cases: allow-list path fragment matches
# ---------------------------------------------------------------------------


def test_allowlist_claude_dir_allows_read(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read on a .claude/ path always passes through."""
    _set_stdin(monkeypatch, _read_payload(".claude/settings.json"))
    with pytest.raises(SystemExit) as exc_info:
        sys.exit(hook.main())
    assert exc_info.value.code == 0


def test_allowlist_tests_dir_allows_read(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read on a tests/ path always passes through."""
    _set_stdin(monkeypatch, _read_payload("tests/test_foo.py"))
    with pytest.raises(SystemExit) as exc_info:
        sys.exit(hook.main())
    assert exc_info.value.code == 0


def test_allowlist_hooks_dir_allows_read(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read on a hooks/ path always passes through."""
    _set_stdin(monkeypatch, _read_payload("tools/hooks/ai/bash-ban-raw-tools.py"))
    with pytest.raises(SystemExit) as exc_info:
        sys.exit(hook.main())
    assert exc_info.value.code == 0


def test_allowlist_grep_on_docs_allows(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Grep on a .md file (docs) always passes through."""
    _set_stdin(monkeypatch, _grep_payload("docs/foo.md"))
    with pytest.raises(SystemExit) as exc_info:
        sys.exit(hook.main())
    assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# Allow cases: fresh CBM marker
# ---------------------------------------------------------------------------


def test_fresh_marker_allows_source_file_read(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Read on a source file is allowed when the CBM marker is fresh."""
    monkeypatch.setattr(hook, "MARKER_FILE_TEMPLATE", str(tmp_path / "marker-{ppid}"))
    marker = tmp_path / f"marker-{os.getppid()}"
    marker.touch()

    _set_stdin(monkeypatch, _read_payload("src/main.py"))
    with pytest.raises(SystemExit) as exc_info:
        sys.exit(hook.main())
    assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# Block cases: source file without fresh marker
# ---------------------------------------------------------------------------


def test_missing_marker_blocks_source_file_read(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Read on a source file is blocked when the CBM marker does not exist."""
    monkeypatch.setattr(hook, "MARKER_FILE_TEMPLATE", str(tmp_path / "marker-{ppid}"))
    # Do NOT create the marker file.

    _set_stdin(monkeypatch, _read_payload("src/main.py"))
    with pytest.raises(SystemExit) as exc_info:
        sys.exit(hook.main())
    assert exc_info.value.code == 2


def test_stale_marker_blocks_source_file_read(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Read on a source file is blocked when the CBM marker mtime is older than TTL."""
    monkeypatch.setattr(hook, "MARKER_FILE_TEMPLATE", str(tmp_path / "marker-{ppid}"))
    marker = tmp_path / f"marker-{os.getppid()}"
    marker.touch()
    stale_mtime = time.time() - (hook.MARKER_TTL_SECONDS + 60)
    os.utime(str(marker), (stale_mtime, stale_mtime))

    _set_stdin(monkeypatch, _read_payload("src/main.py"))
    with pytest.raises(SystemExit) as exc_info:
        sys.exit(hook.main())
    assert exc_info.value.code == 2


def test_whole_repo_grep_no_marker_is_blocked(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Grep with no path (whole-repo) is blocked when no CBM marker exists."""
    monkeypatch.setattr(hook, "MARKER_FILE_TEMPLATE", str(tmp_path / "marker-{ppid}"))
    # No marker file.

    _set_stdin(monkeypatch, _grep_payload(None))
    with pytest.raises(SystemExit) as exc_info:
        sys.exit(hook.main())
    assert exc_info.value.code == 2


def test_whole_repo_glob_no_marker_is_blocked(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Glob with no path (whole-repo) is blocked when no CBM marker exists."""
    monkeypatch.setattr(hook, "MARKER_FILE_TEMPLATE", str(tmp_path / "marker-{ppid}"))
    # No marker file.

    _set_stdin(monkeypatch, _glob_payload(None))
    with pytest.raises(SystemExit) as exc_info:
        sys.exit(hook.main())
    assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# Stderr content checks
# ---------------------------------------------------------------------------


def test_stderr_mentions_gated_tool(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The stderr block reason names the gated tool."""
    monkeypatch.setattr(hook, "MARKER_FILE_TEMPLATE", str(tmp_path / "marker-{ppid}"))
    _set_stdin(monkeypatch, _read_payload("src/main.py"))

    with pytest.raises(SystemExit):
        sys.exit(hook.main())

    captured = capsys.readouterr()
    assert "Read" in captured.err


def test_stderr_mentions_marker_path(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The stderr block reason references the CBM marker mechanism."""
    monkeypatch.setattr(hook, "MARKER_FILE_TEMPLATE", str(tmp_path / "marker-{ppid}"))
    _set_stdin(monkeypatch, _read_payload("src/main.py"))

    with pytest.raises(SystemExit):
        sys.exit(hook.main())

    captured = capsys.readouterr()
    # The marker path (with ppid filled in) should appear in stderr.
    assert str(tmp_path) in captured.err


# ---------------------------------------------------------------------------
# Malformed JSON
# ---------------------------------------------------------------------------


def test_malformed_json_exits_1(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed JSON input exits with code 1 (parity with bash-ban-raw-tools)."""
    _set_stdin(monkeypatch, "not valid json{{")
    with pytest.raises(SystemExit) as exc_info:
        sys.exit(hook.main())
    assert exc_info.value.code == 1
