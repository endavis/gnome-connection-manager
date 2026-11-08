"""Package-level integration tests for lightweight modules."""

from __future__ import annotations

import os
import pwd
import subprocess
import sys
import types
from pathlib import Path

import pytest

import gnome_connection_manager
from gnome_connection_manager import __main__ as gcm_entrypoint
from tests.test_connections import glib_complaints


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


def test_commitizen_is_told_the_changelog_is_written_by_hand() -> None:
    """CHANGELOG.md is written by hand, and `update_changelog_on_bump = false` says so
    (#311). Measured with commitizen 4.18.0, `cz bump --files-only` with the key true
    changed 197 lines of it as well as the version files. False is commitizen's default,
    and the template's `doit release` reads a missing key as false since
    pyproject-template#992, so nothing but this would notice the key go."""
    import tomllib

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    config = tomllib.loads(pyproject.read_text())["tool"]["commitizen"]

    assert config.get("update_changelog_on_bump") is False


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


# -- the shell a local console runs where SHELL is unset (#544) --------------


def _login_shell() -> str:
    """What `local_shell` gives where `SHELL` is unset: the shell of this user's passwd
    entry, or /bin/sh where there is no entry or its shell field is empty."""
    try:
        return pwd.getpwuid(os.getuid()).pw_shell or "/bin/sh"
    except KeyError:
        return "/bin/sh"


def _answer_passwd(
    monkeypatch: pytest.MonkeyPatch, app_module: types.ModuleType, shell: str | None
) -> list[int]:
    """Make the app's `pwd.getpwuid` answer with a passwd entry whose shell field is
    `shell`, or raise the KeyError it raises for a uid passwd has no line for when `shell`
    is None. The list returned gets each uid it is asked for."""
    asked: list[int] = []

    def getpwuid(uid: int) -> types.SimpleNamespace:
        asked.append(uid)
        if shell is None:
            raise KeyError(f"getpwuid(): uid not found: {uid}")
        return types.SimpleNamespace(pw_shell=shell)

    monkeypatch.setattr(app_module.pwd, "getpwuid", getpwuid)
    return asked


def test_a_local_console_runs_shell_where_it_is_set(
    monkeypatch: pytest.MonkeyPatch, app_module: types.ModuleType
) -> None:
    """Where `SHELL` is set the console runs it, as it did before #544, and the passwd entry
    is not read: a wrapper given as `SHELL` stays the shell."""
    asked = _answer_passwd(monkeypatch, app_module, "/bin/dash")

    assert app_module.local_shell({"SHELL": "/usr/bin/zsh"}) == "/usr/bin/zsh"
    assert asked == [], "the passwd entry was read although SHELL is set"


def test_a_local_console_runs_the_passwd_shell_where_shell_is_unset(
    monkeypatch: pytest.MonkeyPatch, app_module: types.ModuleType
) -> None:
    """Under `env -i`, with no `SHELL`, GCM stopped at import with `KeyError: 'SHELL'`
    (#544). The console runs the shell of the user's passwd entry now."""
    _answer_passwd(monkeypatch, app_module, "/bin/dash")

    assert app_module.local_shell({}) == "/bin/dash"


def test_an_empty_shell_counts_as_unset(
    monkeypatch: pytest.MonkeyPatch, app_module: types.ModuleType
) -> None:
    """`SHELL=` names no program, so it is read as unset."""
    _answer_passwd(monkeypatch, app_module, "/bin/dash")

    assert app_module.local_shell({"SHELL": ""}) == "/bin/dash"


def test_a_uid_passwd_has_no_line_for_runs_bin_sh(
    monkeypatch: pytest.MonkeyPatch, app_module: types.ModuleType
) -> None:
    """Measured, `getent passwd 54321` found no line and `pwd.getpwuid(54321)` raised
    `KeyError`: not every uid has an entry to read the shell from (#544)."""
    _answer_passwd(monkeypatch, app_module, None)

    assert app_module.local_shell({}) == "/bin/sh"


def test_an_empty_shell_field_in_the_passwd_entry_means_bin_sh(
    monkeypatch: pytest.MonkeyPatch, app_module: types.ModuleType
) -> None:
    """passwd(5): "If this field is empty, it defaults to the value /bin/sh." """
    _answer_passwd(monkeypatch, app_module, "")

    assert app_module.local_shell({}) == "/bin/sh"


def test_the_passwd_entry_read_is_the_real_uids(
    monkeypatch: pytest.MonkeyPatch, app_module: types.ModuleType
) -> None:
    """The entry is looked up by the real uid, `os.getuid()`."""
    asked = _answer_passwd(monkeypatch, app_module, "/bin/dash")
    monkeypatch.setattr(app_module.os, "getuid", lambda: 4242)

    assert app_module.local_shell({}) == "/bin/dash"
    assert asked == [4242]


_NO_SHELL_PROBE = """
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(); sys.argv = ["gcm"]
os.environ.pop("SHELL", None)
from gnome_connection_manager import app
print("SHELL-IS", app.SHELL)
"""


def test_the_app_imports_without_shell() -> None:
    """The import stopped with `KeyError: 'SHELL'` where `SHELL` was unset, as under
    `env -i`, and `gnome-connection-manager` exited before any window opened (#544). The
    shell is the passwd entry's now. The import opens no window, so this needs no display."""
    result = subprocess.run(
        [sys.executable, "-c", _NO_SHELL_PROBE],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=Path(__file__).resolve().parents[1],
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert f"SHELL-IS {_login_shell()}" in result.stdout.splitlines()


# GCM opens a local console as it starts, and nothing is typed or clicked. The script waits
# on conditions, each with a deadline, never on a pause of a fixed length.
_LOCAL_CONSOLE_SCRIPT = r"""
import faulthandler, os, sys, tempfile, time
faulthandler.dump_traceback_later(60, exit=True)
os.environ["HOME"] = tempfile.mkdtemp(); sys.argv = ["gcm"]
os.environ.pop("SHELL", None)
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk
from gnome_connection_manager import app

def until(condition, seconds=10):
    end = time.monotonic() + seconds
    while time.monotonic() < end and not condition():
        Gtk.main_iteration_do(False)
        time.sleep(0.005)
    return condition()

def program_of(pid):
    # What /proc says the process runs, its argv[0]: None once there is no such process, and
    # "" where its command line reads empty.
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as handle:
            return handle.read().split(b"\0")[0].decode()
    except OSError:
        return None

app.conf.CHECK_UPDATES = False
# The startup console, with no relay between GCM and its shell: with either option on, the
# child would be the relay's Python.
app.conf.STARTUP_LOCAL = True
app.conf.OSC52_ENABLED = 0
app.conf.RAW_SESSION_LOG = 0
app.wMain = app.Wmain(application=None)

notebook = app.wMain.nbConsole
assert notebook.get_n_pages() == 1, "expected the startup console, found %d tabs" % (
    notebook.get_n_pages())
terminal = app.page_terminal(notebook.get_nth_page(0))
assert terminal is not None, "the startup console holds no terminal"
assert until(lambda: getattr(terminal, "child_pid", None)), "the console started no process"
pid = terminal.child_pid

# The console runs `env -u VIRTUAL_ENV <shell>` and env execs the shell, so the process is
# env first and the shell after. A command line that reads empty is no more the shell's than
# env's, so it is waited out too, up to the deadline. A process that is gone is not waited for.
programs = []
def shell_started():
    programs.append(program_of(pid))
    return programs[-1] not in ("env", "")

assert until(shell_started), "the console's process %d was not the shell after 10 s: %r" % (
    pid, programs[-3:])
assert programs[-1], "the console's process %d has ended" % pid
print("SHELL-RAN", programs[-1])
"""


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="needs an X server")
def test_a_local_console_runs_the_login_shell_without_shell_against_real_gtk() -> None:
    """GCM opens a local console as it starts. With `SHELL` unset its process, once
    `env -u VIRTUAL_ENV` has started the shell, is the shell of the user's passwd entry
    (#544). Before, GCM stopped at import and opened no console at all."""
    pytest.importorskip("gi", reason="PyGObject not available")
    result = subprocess.run(
        [sys.executable, "-c", _LOCAL_CONSOLE_SCRIPT],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "GDK_BACKEND": "x11"},
        timeout=90,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert f"SHELL-RAN {_login_shell()}" in result.stdout.splitlines()
    # PyGObject prints what a signal handler raises, and carries on.
    assert "Traceback" not in result.stderr, result.stderr[-2000:]
    assert glib_complaints(result.stderr) == []
