"""Tests for the lightweight entry point logic."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from unittest import mock

import pytest

from gnome_connection_manager import main as gcm_main

if TYPE_CHECKING:
    from collections.abc import Iterator

PATH_VARIABLES = ("GCM_DATA_DIR", "GCM_GLADE_DIR", "GCM_SCRIPTS_DIR")


@pytest.fixture(autouse=True)
def clear_gcm_env() -> Iterator[None]:
    """Start each test without the path variables, and put the environment back
    afterwards as it was. `monkeypatch.delenv` records nothing for a variable that is not
    set, so the values `main.run` sets outlived the test, and every later test on the
    same worker read GCM's data from /usr/share (#281)."""
    with mock.patch.dict(os.environ):
        for key in PATH_VARIABLES:
            os.environ.pop(key, None)
        yield


@pytest.fixture
def dummy_app(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Stub out the heavy GTK application main entry point."""
    calls = {"count": 0}

    def fake_main() -> None:
        calls["count"] += 1

    module = sys.modules.get("gnome_connection_manager.app")
    if module is None:
        import gnome_connection_manager.app as module  # noqa: F401

        module = sys.modules["gnome_connection_manager.app"]

    monkeypatch.setattr(module, "main", fake_main)
    monkeypatch.setattr("gnome_connection_manager.app", module)
    return calls


def test_run_sets_default_paths(dummy_app: dict[str, int]) -> None:
    exit_code = gcm_main.run([])

    assert exit_code == 0
    assert dummy_app["count"] == 1

    expected_data = Path(gcm_main.__file__).resolve().parent.parent.parent / "data"
    assert os.environ["GCM_DATA_DIR"] == str(expected_data)
    assert os.environ["GCM_GLADE_DIR"] == str(expected_data / "ui")
    assert os.environ["GCM_SCRIPTS_DIR"] == str(expected_data / "scripts")


def test_run_falls_back_to_installed_paths(
    monkeypatch: pytest.MonkeyPatch, dummy_app: dict[str, int]
) -> None:
    expected_data = Path(gcm_main.__file__).resolve().parent.parent.parent / "data"
    real_exists = Path.exists

    def fake_exists(self: Path) -> bool:  # type: ignore[override]
        if self == expected_data:
            return False
        return real_exists(self)

    monkeypatch.setattr(Path, "exists", fake_exists, raising=False)

    gcm_main.run([])

    assert os.environ["GCM_DATA_DIR"] == "/usr/share/gnome-connection-manager"
    assert dummy_app["count"] == 1


def test_run_respects_preconfigured_environment(
    dummy_app: dict[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GCM_DATA_DIR", "/tmp/custom-data")
    monkeypatch.setenv("GCM_GLADE_DIR", "/tmp/custom-ui")
    monkeypatch.setenv("GCM_SCRIPTS_DIR", "/tmp/custom-scripts")

    gcm_main.run([])

    assert os.environ["GCM_DATA_DIR"] == "/tmp/custom-data"
    assert os.environ["GCM_GLADE_DIR"] == "/tmp/custom-ui"
    assert os.environ["GCM_SCRIPTS_DIR"] == "/tmp/custom-scripts"
    assert dummy_app["count"] == 1


def test_these_tests_leave_the_environment_as_they_found_it(tmp_path: Path) -> None:
    """Which test runs after these is xdist's choice, so they run in a pytest of their
    own, followed by one that reads what they left: a variable that was not set must
    still not be, and one that was must keep its value (#281)."""
    probe = tmp_path / "test_left_behind.py"
    expected = {"GCM_DATA_DIR": None, "GCM_GLADE_DIR": None, "GCM_SCRIPTS_DIR": "/before"}
    probe.write_text(
        "import os\n\n\n"
        "def test_left_behind():\n"
        f"    assert {{key: os.environ.get(key) for key in {PATH_VARIABLES!r}}} == {expected!r}\n"
    )
    root = Path(__file__).resolve().parent.parent
    tests = [
        f"{__file__}::{name}"
        for name in (
            "test_run_sets_default_paths",
            "test_run_falls_back_to_installed_paths",
            "test_run_respects_preconfigured_environment",
        )
    ]
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in PATH_VARIABLES and not key.startswith("PYTEST_")
    }
    env["GCM_SCRIPTS_DIR"] = "/before"
    # These tests open no window, so the run needs no Xvfb of its own.
    env["GCM_TEST_REAL_DISPLAY"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--no-cov",
            "--rootdir",
            str(root),
            "-c",
            str(root / "pyproject.toml"),
            *tests,
            str(probe),
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]
    assert "4 passed" in result.stdout, result.stdout[-3000:]
