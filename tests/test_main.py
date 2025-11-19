"""Tests for the lightweight entry point logic."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from gnome_connection_manager import main as gcm_main


@pytest.fixture(autouse=True)
def clear_gcm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure each test starts with a clean environment."""
    for key in ("GCM_DATA_DIR", "GCM_GLADE_DIR", "GCM_SCRIPTS_DIR"):
        monkeypatch.delenv(key, raising=False)


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
