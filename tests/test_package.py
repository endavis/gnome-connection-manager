"""Package-level integration tests for lightweight modules."""

from __future__ import annotations

import sys
from pathlib import Path

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
        "pyproject.toml": tomllib.loads((repo / "pyproject.toml").read_text())["project"][
            "version"
        ],
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


# -- importing the app must not block or exit (#118) -------------------------

_IMPORT_PROBE = """
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(); sys.argv = ["gcm"]
# No expect on PATH, and no display: the two conditions that used to hang the import.
os.environ["PATH"] = tempfile.mkdtemp()
os.environ.pop("DISPLAY", None); os.environ.pop("WAYLAND_DISPLAY", None)
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91")
from gnome_connection_manager import app
print("IMPORT-OK", callable(app.require_expect))
"""


def test_importing_the_app_neither_blocks_nor_exits() -> None:
    """The import used to run an expect check and report it with a modal dialog.

    `Gtk.MessageDialog.run()` waits for a button, so importing the module with nobody at
    the screen never returned, and `sys.exit(1)` on the failure path meant importing it
    could end the interpreter. It presented as CI taking seven minutes rather than as an
    error: every test importing the module in a subprocess sat on an invisible dialog
    until its own timeout.

    The timeout here is the assertion. If the import blocks again, this fails rather than
    hanging the suite.
    """
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-c", _IMPORT_PROBE],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=Path(__file__).resolve().parents[1],
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert "IMPORT-OK True" in result.stdout


def test_require_expect_reports_on_stderr_when_there_is_no_display(monkeypatch, capsys) -> None:
    """With no display there is nobody to click OK, so the dialog would be a hang."""
    import gnome_connection_manager.app as app_mod

    monkeypatch.setattr(app_mod, "expect_is_installed", lambda: False)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    with pytest.raises(SystemExit) as exit_info:
        app_mod.require_expect()

    assert exit_info.value.code == 1
    assert "install expect" in capsys.readouterr().err
