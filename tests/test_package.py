"""Package-level integration tests for lightweight modules."""

from __future__ import annotations

import sys

import pytest

import gnome_connection_manager
from gnome_connection_manager import __main__ as gcm_entrypoint


def test_package_exports_run_from_main_module() -> None:
    from gnome_connection_manager import main as gcm_main

    assert gnome_connection_manager.run is gcm_main.run
    assert "run" in gnome_connection_manager.__all__


def test_main_dunder_module_invokes_run(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_run(argv: list[str]) -> int:
        captured["argv"] = list(argv)
        return 123

    monkeypatch.setattr("gnome_connection_manager.main.run", fake_run)

    result = gcm_entrypoint.main()

    assert result == 123
    assert captured["argv"] == sys.argv
