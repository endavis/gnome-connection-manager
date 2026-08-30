"""Tests for the ``context-mode-pretooluse`` PreToolUse hook.

The hook script lives at ``tools/hooks/ai/context-mode-pretooluse.py``. Its filename
contains hyphens, so it isn't directly importable as a module — we load it via
``importlib`` and invoke ``main()`` directly with a stubbed stdin.
"""

from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
import types
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

HOOK_PATH = (
    Path(__file__).resolve().parents[1] / "tools" / "hooks" / "ai" / "context-mode-pretooluse.py"
)


class _BytesStdin:
    """Minimal stdin stub whose .buffer attribute is a BytesIO."""

    def __init__(self, data: bytes) -> None:
        self.buffer = io.BytesIO(data)


def _load_hook() -> types.ModuleType:
    """Load the hook script as a fresh module instance."""
    spec = importlib.util.spec_from_file_location("context_mode_pretooluse", HOOK_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"could not load hook from {HOOK_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def hook() -> Iterator[types.ModuleType]:
    """Load a fresh copy of the hook module for each test."""
    module = _load_hook()
    sys.modules["context_mode_pretooluse"] = module
    try:
        yield module
    finally:
        sys.modules.pop("context_mode_pretooluse", None)


# ---------------------------------------------------------------------------
# CLI not installed: exit 0, subprocess never called
# ---------------------------------------------------------------------------


def test_cli_not_installed_exits_0(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When shutil.which returns None, main() returns 0."""
    monkeypatch.setattr(hook.shutil, "which", lambda _: None)
    monkeypatch.setattr(sys, "stdin", _BytesStdin(b'{"tool_name":"Bash"}'))
    assert hook.main() == 0


def test_cli_not_installed_subprocess_not_called(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When CLI is not installed, subprocess.run is never invoked."""
    monkeypatch.setattr(hook.shutil, "which", lambda _: None)
    monkeypatch.setattr(sys, "stdin", _BytesStdin(b"{}"))
    run_mock = MagicMock()
    monkeypatch.setattr(hook.subprocess, "run", run_mock)
    hook.main()
    run_mock.assert_not_called()


# ---------------------------------------------------------------------------
# CLI installed: correct invocation and stdout passthrough
# ---------------------------------------------------------------------------


def test_cli_installed_calls_subprocess_with_correct_args(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """subprocess.run is called with [CLI_NAME, 'hook', 'claude-code', EVENT_NAME]."""
    monkeypatch.setattr(hook.shutil, "which", lambda _: "/usr/bin/context-mode")
    payload = b'{"tool_name":"Bash"}'
    monkeypatch.setattr(sys, "stdin", _BytesStdin(payload))

    mock_result = subprocess.CompletedProcess(
        args=[hook.CLI_NAME, "hook", "claude-code", hook.EVENT_NAME],
        returncode=0,
        stdout=b"ok",
        stderr=b"",
    )
    run_mock = MagicMock(return_value=mock_result)
    monkeypatch.setattr(hook.subprocess, "run", run_mock)

    assert hook.main() == 0
    run_mock.assert_called_once_with(
        [hook.CLI_NAME, "hook", "claude-code", hook.EVENT_NAME],
        input=payload,
        capture_output=True,
        check=False,
    )


def test_cli_installed_stdout_passthrough(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """stdout bytes from subprocess are written to sys.stdout.buffer."""
    monkeypatch.setattr(hook.shutil, "which", lambda _: "/usr/bin/context-mode")
    monkeypatch.setattr(sys, "stdin", _BytesStdin(b"{}"))

    captured_stdout = io.BytesIO()
    mock_stdout = MagicMock()
    mock_stdout.buffer = captured_stdout
    monkeypatch.setattr(sys, "stdout", mock_stdout)

    mock_result = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=b"summary output",
        stderr=b"",
    )
    monkeypatch.setattr(hook.subprocess, "run", MagicMock(return_value=mock_result))

    assert hook.main() == 0
    assert captured_stdout.getvalue() == b"summary output"


def test_cli_installed_returns_subprocess_returncode(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """main() propagates the subprocess exit code."""
    monkeypatch.setattr(hook.shutil, "which", lambda _: "/usr/bin/context-mode")
    monkeypatch.setattr(sys, "stdin", _BytesStdin(b"{}"))

    mock_stdout = MagicMock()
    mock_stdout.buffer = io.BytesIO()
    mock_stderr = MagicMock()
    mock_stderr.buffer = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", mock_stdout)
    monkeypatch.setattr(sys, "stderr", mock_stderr)

    mock_result = subprocess.CompletedProcess(args=[], returncode=1, stdout=b"", stderr=b"")
    monkeypatch.setattr(hook.subprocess, "run", MagicMock(return_value=mock_result))
    assert hook.main() == 1


def test_cli_installed_returncode_2(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """main() propagates returncode 2."""
    monkeypatch.setattr(hook.shutil, "which", lambda _: "/usr/bin/context-mode")
    monkeypatch.setattr(sys, "stdin", _BytesStdin(b"{}"))

    mock_stdout = MagicMock()
    mock_stdout.buffer = io.BytesIO()
    mock_stderr = MagicMock()
    mock_stderr.buffer = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", mock_stdout)
    monkeypatch.setattr(sys, "stderr", mock_stderr)

    mock_result = subprocess.CompletedProcess(args=[], returncode=2, stdout=b"", stderr=b"")
    monkeypatch.setattr(hook.subprocess, "run", MagicMock(return_value=mock_result))
    assert hook.main() == 2


def test_subprocess_file_not_found_exits_0(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FileNotFoundError from subprocess.run exits 0."""
    monkeypatch.setattr(hook.shutil, "which", lambda _: "/usr/bin/context-mode")
    monkeypatch.setattr(sys, "stdin", _BytesStdin(b"{}"))
    monkeypatch.setattr(hook.subprocess, "run", MagicMock(side_effect=FileNotFoundError))
    assert hook.main() == 0


def test_empty_stdin_calls_subprocess(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty stdin still calls subprocess with input=b'' and propagates returncode."""
    monkeypatch.setattr(hook.shutil, "which", lambda _: "/usr/bin/context-mode")
    monkeypatch.setattr(sys, "stdin", _BytesStdin(b""))

    mock_stdout = MagicMock()
    mock_stdout.buffer = io.BytesIO()
    mock_stderr = MagicMock()
    mock_stderr.buffer = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", mock_stdout)
    monkeypatch.setattr(sys, "stderr", mock_stderr)

    mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")
    run_mock = MagicMock(return_value=mock_result)
    monkeypatch.setattr(hook.subprocess, "run", run_mock)

    assert hook.main() == 0
    run_mock.assert_called_once_with(
        [hook.CLI_NAME, "hook", "claude-code", hook.EVENT_NAME],
        input=b"",
        capture_output=True,
        check=False,
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_event_name_constant(hook: types.ModuleType) -> None:
    """EVENT_NAME is 'PreToolUse'."""
    assert hook.EVENT_NAME == "PreToolUse"


def test_cli_name_constant(hook: types.ModuleType) -> None:
    """CLI_NAME is 'context-mode'."""
    assert hook.CLI_NAME == "context-mode"
