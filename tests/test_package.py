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


def _declared_versions(repo: Path | None = None) -> dict[str, str]:
    """Every place the release version is spelled out, by the file's path from the root
    of `repo`, this repository unless given, and what it currently says."""
    import re
    import tomllib

    repo = repo or Path(__file__).resolve().parents[1]

    def written(path: str, pattern: str) -> str:
        match = re.search(pattern, (repo / path).read_text(), re.MULTILINE)
        assert match, f"{path} no longer matches {pattern}"
        return match.group(1)

    return {
        "pyproject.toml": tomllib.loads((repo / "pyproject.toml").read_text())["project"][
            "version"
        ],
        "src/gnome_connection_manager/__init__.py": written(
            "src/gnome_connection_manager/__init__.py", r'^__version__ = "([^"]+)"'
        ),
        "src/gnome_connection_manager/app.py": written(
            "src/gnome_connection_manager/app.py", r'^app_version = "([^"]+)"'
        ),
        "Makefile": written("Makefile", r"^PKG_VERSION=(\S+)"),
    }


def test_every_declared_version_agrees() -> None:
    """Four files carry the version and nothing kept them in step.

    Measured at the time this was written: pyproject.toml and __init__.py said 1.2.0,
    app.py said 1.2.1 and the Makefile said 1.2.2 -- so the About dialog reported a
    different release from the .deb the user had installed.
    """
    declared = _declared_versions()

    assert len(set(declared.values())) == 1, f"version drift: {declared}"


def test_commitizen_names_every_declared_version_file() -> None:
    """A release writes the version with `cz bump --files-only` (#291), which rewrites
    `[project].version` through its pep621 provider and each file in `version_files`, and
    nothing else. A file named above alone would keep the old version through a release;
    one named there alone would be bumped outside the test that keeps them equal."""
    import tomllib

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    config = tomllib.loads(pyproject.read_text())["tool"]["commitizen"]
    named = {entry.split(":")[0] for entry in config["version_files"]}

    assert config["version_provider"] == "pep621"
    assert named | {"pyproject.toml"} == set(_declared_versions())


def test_a_release_bump_reaches_every_declared_version(tmp_path: Path) -> None:
    """Naming the right files is not enough. Measured with commitizen 4.18.0, a
    `version_files` pattern that matches no line, `^app_versio_typo` for app.py, left that
    file at the old version and still exited 0. So bump a copy of the four files as a
    release does, and read them back."""
    import os
    import shutil
    import subprocess

    repo = Path(__file__).resolve().parents[1]
    for path in _declared_versions():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(repo / path, tmp_path / path)
    # commitizen refuses to run outside a git repository, though it needs no commit. git
    # exports GIT_DIR and its like to a hook, and run from one, these would act on the
    # repository the hook is for.
    env = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, env=env, check=True)

    subprocess.run(
        [sys.executable, "-m", "commitizen", "bump", "--files-only", "--yes", "9.9.9"],
        cwd=tmp_path,
        env=env,
        stdin=subprocess.DEVNULL,
        check=True,
        timeout=60,
    )

    assert _declared_versions(tmp_path) == dict.fromkeys(_declared_versions(), "9.9.9")


def test_the_readme_does_not_write_the_version_out() -> None:
    """Four files carry the version and a test keeps them in step. The README was a fifth,
    twice over, in prose and in an apt command -- outside that test and so free to rot the
    moment the others moved (#194). `make deb` prints the name it wrote; the README says so
    and installs with a glob."""
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()
    version = _declared_versions()["pyproject.toml"]

    assert version not in readme, (
        f"README.md writes the version ({version}) out; let `make deb` name the file instead"
    )


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
