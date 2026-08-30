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


# -- one version, four places it is written down ----------------------------

def _declared_versions() -> dict[str, str]:
    """Every place the release version is spelled out, and what it currently says."""
    import re
    import tomllib
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    found = {
        "pyproject.toml": tomllib.loads(
            (repo / "pyproject.toml").read_text()
        )["project"]["version"],
        "__init__.py": gnome_connection_manager.__version__,
    }
    app_source = (repo / "src/gnome_connection_manager/app.py").read_text()
    found["app.py app_version"] = re.search(
        r'^app_version = "([^"]+)"', app_source, re.MULTILINE
    ).group(1)
    found["Makefile PKG_VERSION"] = re.search(
        r"^PKG_VERSION=(\S+)", (repo / "Makefile").read_text(), re.MULTILINE
    ).group(1)
    return found


def test_every_declared_version_agrees() -> None:
    """Four files carry the version and nothing kept them in step.

    Measured at the time this was written: pyproject.toml and __init__.py said 1.2.0,
    app.py said 1.2.1 and the Makefile said 1.2.2 -- so the About dialog reported a
    different release from the .deb the user had installed.
    """
    declared = _declared_versions()

    assert len(set(declared.values())) == 1, f"version drift: {declared}"
