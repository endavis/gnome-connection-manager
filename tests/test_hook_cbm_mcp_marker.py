"""Tests for the ``cbm-mcp-marker`` PostToolUse hook.

The hook script lives at ``tools/hooks/ai/cbm-mcp-marker.py``. Its filename
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

HOOK_PATH = Path(__file__).resolve().parents[1] / "tools" / "hooks" / "ai" / "cbm-mcp-marker.py"


def _load_hook() -> types.ModuleType:
    """Load the hook script as a fresh module instance."""
    spec = importlib.util.spec_from_file_location("cbm_mcp_marker", HOOK_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"could not load hook from {HOOK_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def hook() -> Iterator[types.ModuleType]:
    """Load a fresh copy of the hook module for each test."""
    module = _load_hook()
    sys.modules["cbm_mcp_marker"] = module
    try:
        yield module
    finally:
        sys.modules.pop("cbm_mcp_marker", None)


def _set_stdin(monkeypatch: pytest.MonkeyPatch, payload: str) -> None:
    """Replace ``sys.stdin`` with a StringIO containing *payload*."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))


def _cbm_tool_payload(tool_name: str = "mcp__codebase-memory__search_graph") -> str:
    """Build a typical PostToolUse payload for a CBM MCP tool call."""
    return json.dumps(
        {
            "tool_name": tool_name,
            "tool_input": {"query": "find main function"},
            "tool_response": {"result": "..."},
        }
    )


# ---------------------------------------------------------------------------
# Marker file creation
# ---------------------------------------------------------------------------


def test_marker_file_is_created(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Marker file is created when it does not already exist."""
    monkeypatch.setattr(hook, "MARKER_FILE_TEMPLATE", str(tmp_path / "marker-{ppid}"))
    marker = tmp_path / f"marker-{os.getppid()}"
    assert not marker.exists()

    _set_stdin(monkeypatch, _cbm_tool_payload())
    assert hook.main() == 0

    assert marker.exists()


def test_marker_file_mtime_is_fresh(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Marker file mtime is within 5 seconds of now after hook runs."""
    monkeypatch.setattr(hook, "MARKER_FILE_TEMPLATE", str(tmp_path / "marker-{ppid}"))
    marker = tmp_path / f"marker-{os.getppid()}"

    before = time.time()
    _set_stdin(monkeypatch, _cbm_tool_payload())
    assert hook.main() == 0
    after = time.time()

    mtime = marker.stat().st_mtime
    assert before - 1 <= mtime <= after + 1


def test_marker_file_mtime_is_updated(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Marker file mtime is updated when the file already exists."""
    monkeypatch.setattr(hook, "MARKER_FILE_TEMPLATE", str(tmp_path / "marker-{ppid}"))
    marker = tmp_path / f"marker-{os.getppid()}"
    marker.touch()
    old_mtime = time.time() - 60
    os.utime(str(marker), (old_mtime, old_mtime))

    _set_stdin(monkeypatch, _cbm_tool_payload())
    assert hook.main() == 0

    new_mtime = marker.stat().st_mtime
    assert new_mtime > old_mtime


# ---------------------------------------------------------------------------
# Marker path uses MARKER_FILE_TEMPLATE
# ---------------------------------------------------------------------------


def test_marker_path_uses_configured_template(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Marker is created at the path derived from MARKER_FILE_TEMPLATE."""
    custom_template = str(tmp_path / "custom-marker-{ppid}")
    monkeypatch.setattr(hook, "MARKER_FILE_TEMPLATE", custom_template)
    expected_marker = tmp_path / f"custom-marker-{os.getppid()}"

    _set_stdin(monkeypatch, _cbm_tool_payload())
    assert hook.main() == 0

    assert expected_marker.exists()


# ---------------------------------------------------------------------------
# Malformed JSON: best-effort, no crash
# ---------------------------------------------------------------------------


def test_malformed_json_exits_0(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed JSON exits 0 — the marker hook never blocks (best-effort)."""
    _set_stdin(monkeypatch, "not valid json{{")
    assert hook.main() == 0
