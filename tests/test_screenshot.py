"""`doit screenshot` (#546): the README's screenshot, written from a checkout.

One test runs the real thing, GCM on an Xvfb of its own, and reads the PNG it writes. The
rest give `run` a made-up window half and a made-up Xvfb, to hold what it does with each way
that half can end: the file is replaced only after a run that ended as it should, and the
Xvfb is stopped however the run ended. What the console shows is not checked: it is the
checkout's `git log`, which every commit changes.
"""

from __future__ import annotations

import os
import shlex
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from gnome_connection_manager.utils import configfile
from tests import xdisplay
from tests.test_sandbox import hosts_of
from tools import screenshot
from tools.doit import gcm

if TYPE_CHECKING:
    from collections.abc import Callable

needs_xvfb = pytest.mark.skipif(shutil.which("Xvfb") is None, reason="needs Xvfb")

REPO = Path(__file__).resolve().parents[1]
FAKE_BODY = b"made by the fake"


def header(width: int, height: int) -> bytes:
    """The first 24 bytes of a PNG: its signature, then an IHDR chunk's length, type, size."""
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I4sII", 13, b"IHDR", width, height)


def fake_run(
    *,
    code: int = 0,
    stderr: str | None = "",
    size: tuple[int, int] | None = (1180, 700),
    timeout: bool = False,
    calls: list[dict[str, Any]] | None = None,
) -> Callable[..., subprocess.CompletedProcess[str]]:
    """A `subprocess.run` for the window half: writes a PNG where it is told, then ends.

    It writes first, as finding 3's run did, for a run that ends badly can have written a PNG.
    A deadline raises as the real one does, with its standard error as bytes, or as None where
    the child wrote none.
    """

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if size is not None:
            Path(argv[-1]).write_bytes(header(*size) + FAKE_BODY)
        if calls is not None:
            home = Path(kwargs["env"]["HOME"])
            calls.append(
                {"argv": argv, "home": home, "prepared": (home / "demo.rc").is_file(), **kwargs}
            )
        if timeout:
            raw = None if stderr is None else stderr.encode()
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"], stderr=raw)
        return subprocess.CompletedProcess(argv, code, "", stderr or "")

    return run


@pytest.fixture
def xvfb(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """A made-up Xvfb on :99. The list holds each process `stop` was asked to end."""
    stopped: list[Any] = []
    monkeypatch.setattr(xdisplay, "start", lambda *args, **kwargs: ("an Xvfb", ":99"))
    monkeypatch.setattr(xdisplay, "stop", lambda process, *args, **kwargs: stopped.append(process))
    return stopped


@needs_xvfb
def test_the_screenshot_is_a_png_the_size_of_the_window(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pytest.importorskip("gi", reason="PyGObject not available")
    out = tmp_path / "shot.png"

    written = screenshot.run(out)

    output = capsys.readouterr().out
    assert written is True, output
    data = out.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert data[12:16] == b"IHDR"
    assert struct.unpack(">II", data[16:24]) == (1180, 700)


FAILURES = [
    pytest.param(
        {"code": 1, "stderr": "the tabs check failed\n"},
        "exited with status 1",
        "the tabs check failed",
        id="exit-status",
    ),
    pytest.param(
        {"stderr": "Traceback (most recent call last):\nValueError: boom\n"},
        "printed a traceback",
        "ValueError: boom",
        id="traceback-after-exit-0",
    ),
    pytest.param(
        {"timeout": True, "stderr": "still waiting\n"},
        "still running after 7 s",
        "still waiting",
        id="deadline",
    ),
    pytest.param(
        {"timeout": True, "stderr": None},
        "still running after 7 s",
        "",
        id="deadline-with-no-stderr",
    ),
    pytest.param({"size": (1180, 701)}, "not (1180, 700)", "", id="wrong-size"),
    pytest.param({"size": None}, "the PNG is None", "", id="no-png"),
]


@pytest.mark.parametrize(("child", "why", "shown"), FAILURES)
def test_a_run_that_fails_leaves_out_as_it_was(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    xvfb: list[Any],
    child: dict[str, Any],
    why: str,
    shown: str,
) -> None:
    out = tmp_path / "shot.png"
    out.write_bytes(b"the committed shot")
    monkeypatch.setattr(screenshot.subprocess, "run", fake_run(**child))

    assert screenshot.run(out, deadline=7) is False

    output = capsys.readouterr().out
    assert why in output
    assert shown in output
    assert "Wrote" not in output
    assert out.read_bytes() == b"the committed shot"
    assert xvfb == ["an Xvfb"], "the Xvfb is stopped after a failure too"


def test_a_failed_run_makes_no_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, xvfb: list[Any]
) -> None:
    out = tmp_path / "docs" / "images" / "shot.png"
    monkeypatch.setattr(screenshot.subprocess, "run", fake_run(code=1))

    assert screenshot.run(out) is False

    assert not (tmp_path / "docs").exists()


def test_a_run_that_ends_as_it_should_replaces_out(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    xvfb: list[Any],
) -> None:
    out = tmp_path / "docs" / "images" / "shot.png"
    monkeypatch.setattr(screenshot.subprocess, "run", fake_run())

    assert screenshot.run(out) is True

    assert out.read_bytes() == header(1180, 700) + FAKE_BODY
    assert f"Wrote {out}" in capsys.readouterr().out
    assert xvfb == ["an Xvfb"]


def test_a_run_that_ends_as_it_should_replaces_what_out_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, xvfb: list[Any]
) -> None:
    out = tmp_path / "shot.png"
    out.write_bytes(b"the committed shot")
    monkeypatch.setattr(screenshot.subprocess, "run", fake_run())

    assert screenshot.run(out) is True

    assert out.read_bytes() == header(1180, 700) + FAKE_BODY


@pytest.mark.parametrize("error", [KeyboardInterrupt, OSError])
def test_the_xvfb_is_stopped_when_the_run_is_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, xvfb: list[Any], error: type[BaseException]
) -> None:
    def interrupted(argv: list[str], **kwargs: Any) -> None:
        raise error

    out = tmp_path / "shot.png"
    monkeypatch.setattr(screenshot.subprocess, "run", interrupted)

    with pytest.raises(error):
        screenshot.run(out)

    assert xvfb == ["an Xvfb"]
    assert not out.exists()


def test_without_an_xvfb_no_window_half_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("a process was started")

    monkeypatch.setattr(xdisplay, "start", lambda *args, **kwargs: None)
    monkeypatch.setattr(screenshot.subprocess, "run", refuse)

    assert screenshot.run(tmp_path / "shot.png") is False

    assert "sudo apt install xvfb" in capsys.readouterr().out


def test_the_window_half_is_started_as_the_task_says(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, xvfb: list[Any]
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(screenshot.subprocess, "run", fake_run(calls=calls))
    out = tmp_path / "shot.png"

    assert screenshot.run(out, deadline=7) is True

    (call,) = calls
    argv, env = call["argv"], call["env"]
    assert argv[:3] == [sys.executable, "-u", str(Path(screenshot.__file__).resolve())]
    assert argv[3] == "--window"
    assert Path(argv[4]).name == "screenshot.png" and Path(argv[4]) != out
    assert (call["timeout"], call["cwd"], call["check"]) == (7, screenshot.REPO, False)
    assert call["capture_output"] is True and call["text"] is True
    assert (env["DISPLAY"], env["GDK_BACKEND"]) == (":99", "x11")
    assert call["prepared"], "the HOME holds what the window half needs when it starts"
    assert env["SHELL"] == str(call["home"] / "demo-shell")
    assert not call["home"].exists(), "the scratch HOME goes with the run"


def test_the_environment_is_english_on_its_own_display(tmp_path: Path) -> None:
    base = {
        "DISPLAY": ":0",
        "WAYLAND_DISPLAY": "wayland-0",
        "GDK_BACKEND": "wayland",
        "GDK_DPI_SCALE": "2",
        "LANG": "de_DE.UTF-8",
        "LANGUAGE": "de:en",
        "LC_ALL": "de_DE.UTF-8",
        "LC_MESSAGES": "de_DE.UTF-8",
        "GTK_THEME": "Adwaita:dark",
        "XDG_CONFIG_HOME": "/real/config",
        "GCM_DATA_DIR": "/installed/data",
        "SSH_AUTH_SOCK": "/real/agent",
        "SHELL": "/usr/bin/zsh",
        "PATH": "/usr/bin",
    }
    home, shell = tmp_path / "home", tmp_path / "home" / "demo-shell"

    env = screenshot.environment(base, home, ":97", shell)

    assert env["LANG"] == "C.UTF-8"
    assert not {"LANGUAGE", "LC_ALL", "LC_MESSAGES", "GTK_THEME"} & set(env)
    assert (env["DISPLAY"], env["GDK_BACKEND"], env["HOME"]) == (":97", "x11", str(home))
    assert env["SHELL"] == str(shell)
    assert env["PATH"] == "/usr/bin"
    assert not {"WAYLAND_DISPLAY", "GDK_DPI_SCALE", "XDG_CONFIG_HOME", "GCM_DATA_DIR"} & set(env)
    assert "SSH_AUTH_SOCK" not in env
    assert base["LANG"] == "de_DE.UTF-8", "the caller's own environment is left alone"


def test_the_window_half_refuses_a_home_prepare_did_not_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    # None in sys.modules makes `import gi` raise, so a window that went on to start GTK fails.
    monkeypatch.setitem(sys.modules, "gi", None)

    assert screenshot.window(tmp_path / "shot.png") == 2

    assert "doit screenshot" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_main_runs_the_window_half_only_when_asked(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[Path] = []
    monkeypatch.setattr(screenshot, "window", lambda shot: seen.append(shot) or 0)

    assert screenshot.main(["--window", "a.png"]) == 0
    assert seen == [Path("a.png")]
    for args in ([], ["a.png"], ["--window"], ["--window", "a.png", "b.png"], ["--other", "a"]):
        assert screenshot.main(args) == 2
    assert seen == [Path("a.png")]
    assert "doit screenshot" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("content", "size"),
    [
        (header(1180, 700), (1180, 700)),
        (header(1, 2) + b"more", (1, 2)),
        (None, None),
        (header(1180, 700)[:23], None),
        (b"", None),
        (b"GIF89a" + header(1180, 700)[6:], None),
        (header(1180, 700)[:12] + b"IDAT" + header(1180, 700)[16:], None),
    ],
    ids=["valid", "valid-with-more", "missing", "short", "empty", "not-a-png", "not-ihdr-first"],
)
def test_png_size(tmp_path: Path, content: bytes | None, size: tuple[int, int] | None) -> None:
    path = tmp_path / "file.png"
    if content is not None:
        path.write_bytes(content)

    assert screenshot.png_size(path) == size


def test_png_size_of_a_folder_is_none(tmp_path: Path) -> None:
    assert screenshot.png_size(tmp_path) is None


def test_the_task_writes_where_out_says(monkeypatch: pytest.MonkeyPatch) -> None:
    task = gcm.task_screenshot()
    assert task["verbosity"] == 2
    assert task["actions"] == [gcm._write_screenshot]
    (param,) = task["params"]
    assert (param["name"], param["long"]) == ("out", "out")
    assert param["default"] == str(REPO / "docs" / "images" / "screenshot.png")
    assert param["default"] == str(screenshot.OUT)
    seen: list[Path] = []

    def fake(out: Path, deadline: float = 0) -> bool:
        seen.append(out)
        return len(seen) == 1

    monkeypatch.setattr(screenshot, "run", fake)

    assert gcm._write_screenshot("some/where.png") is True
    assert gcm._write_screenshot("other.png") is False
    assert seen == [Path("some/where.png"), Path("other.png")]


def test_prepare_makes_a_home_the_window_half_runs_against(tmp_path: Path) -> None:
    repo = tmp_path / "it's a repo"
    home = tmp_path / "home"

    shell = screenshot.prepare(home, repo)

    assert shell == home / "demo-shell"
    assert os.access(shell, os.X_OK)
    assert (home / ".sudo_as_admin_successful").is_file()
    assert not (home / ".config" / "gtk-3.0" / "settings.ini").exists()
    # Each line reads back as one command, whatever the path holds.
    wrapper = shell.read_text(encoding="utf-8").splitlines()
    assert wrapper[0] == "#!/bin/sh"
    assert shlex.split(wrapper[1]) == ["exec", "bash", "--rcfile", str(home / "demo.rc"), "-i"]
    rc = (home / "demo.rc").read_text(encoding="utf-8").splitlines()
    assert shlex.split(rc[0]) == ["cd", str(repo)]
    assert shlex.split(rc[1]) == [f"PS1={screenshot.PROMPT}"]
    assert (
        rc[2].startswith("git --no-pager log ") and "git -c color.status=always status -sb" in rc[2]
    )
    assert (home / ".config" / "gcm" / "gcm.conf").is_file()


def test_the_config_holds_the_tree_the_window_checks_for(tmp_path: Path) -> None:
    path = tmp_path / "gcm.conf"
    screenshot.write_config(path)

    hosts, tree, fixes = hosts_of(path)

    assert fixes == []
    folders = sorted(tree.path_for(folder) for folder in tree.folders)
    assert (folders, sorted(f"{host.group}/{host.name}" for host in hosts)) == (
        screenshot.expected_rows()
    )
    assert all(host.password == "" for host in hosts)
    assert all(host.host == f"{host.name}.invalid" for host in hosts)
    assert len({host.id for host in hosts}) == len(hosts)
    assert configfile.load(path).config.get("options", "check-updates") == "False"


def test_the_rows_the_tree_must_show() -> None:
    folders, hosts = screenshot.expected_rows()

    # Projects is a row, though no host's group is Projects alone.
    assert folders == [
        "Home lab",
        "Home lab/Edge",
        "Projects",
        "Projects/gnome-connection-manager",
        "Projects/pyproject-template",
    ]
    assert hosts == [
        "Home lab/Edge/opnsense",
        "Home lab/Edge/switch-01",
        "Home lab/nas",
        "Projects/gnome-connection-manager/build",
        "Projects/gnome-connection-manager/docs",
        "Projects/pyproject-template/ci-runner",
    ]
