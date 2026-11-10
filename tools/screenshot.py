"""The README's screenshot, taken from a checkout (#546).

`docs/images/screenshot.png` is a real GCM window, not a mock-up (#271). `doit screenshot`
writes it again with no step by hand, and this module is what it runs. It has two halves:

- `run`, the task's half, starts an Xvfb of its own through `tests/xdisplay.py`, writes a
  scratch HOME holding `gcm.conf`, a `SHELL` wrapper and its `demo.rc`, and runs the window
  half on that Xvfb under a deadline. It replaces the README's file only after a run that
  exited 0 in time, printed no traceback and wrote a PNG the size of the window.
- `window`, which `python tools/screenshot.py --window <png>` runs, is GCM itself: it opens
  the tabs, checks what is on the screen and saves the window's picture. It ends the process
  at once, through `os._exit`, on an exception or a failed check. An exception in a GLib
  callback is printed and the main loop carries on, so a run that failed in one never ended;
  and a run with a wrong tree wrote a PNG all the same, with its size right (#546).

Both halves are one file so that what `window` checks and what `run` seeds come from the one
`TREE`. At module level it imports only the standard library and GCM's GTK-free `utils`, as
`tools/sandbox.py` does. `window` imports GTK and `app` itself, after it has checked its HOME,
and `run` imports `tools.sandbox` and `tests.xdisplay`, which a file run by its path cannot.

The console of each tab shows the checkout's `git log` and `git status -sb`, so the shot
shows a clean one only from a checkout with nothing to commit.
"""

from __future__ import annotations

import configparser
import os
import shlex
import shutil
import struct
import subprocess  # nosec B404  # runs the window half, the point of this module
import sys
import tempfile
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

from gnome_connection_manager.utils.folders import FolderTree
from gnome_connection_manager.utils.hosts import ERASE_BINDING_AUTO, Host, HostUtils

if TYPE_CHECKING:
    from collections.abc import Callable

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "images" / "screenshot.png"

# The window's size in pixels, which the README's shot has.
SIZE = (1180, 700)
# GCM opens one local tab at start; `window` opens the others.
TABS = 4
# Seconds `run` gives the window half. A run takes about 5 s, so the rest is for a hang.
DEADLINE = 60.0

# (folder path, host names). A folder is every prefix of a path, so `Projects` is a row
# though no host's group is `Projects` alone.
TREE = (
    ("Home lab/Edge", ("opnsense", "switch-01")),
    ("Home lab", ("nas",)),
    ("Projects/gnome-connection-manager", ("build", "docs")),
    ("Projects/pyproject-template", ("ci-runner",)),
)

# The prompt of each tab's shell, as bash reads it.
PROMPT = r"\[\e[01;32m\]you@workstation\[\e[00m\]:\[\e[01;34m\]~/src/gcm\[\e[00m\]\$ "

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# How much of the window half's standard error `run` shows when it fails.
STDERR_TAIL = 3000
USAGE = (
    "The command is `uv run doit screenshot`. `--window <png>` is the half of it that "
    "task starts, under a HOME it has prepared."
)


def write_config(path: Path) -> None:
    """Write a gcm.conf holding `TREE`, as `tools/sandbox.py` writes its own.

    It is written with GCM's own writers, so it has the shape a current GCM saves
    (ADR-0002), and update checks are off (#316).
    """
    cp = configparser.RawConfigParser()
    cp.add_section("options")
    cp.set("options", "check-updates", "False")
    tree = FolderTree()
    number = 0
    for group, names in TREE:
        folder = tree.ensure_path(group)
        for name in names:
            number += 1
            host = Host(
                group, name, "", f"{name}.invalid", "you", "", "", "22", "", "ssh", "",
                "0", "", "", "False", "False", "False", "", "", "False",
                ERASE_BINDING_AUTO, ERASE_BINDING_AUTO, "", "False", "", folder,
            )  # fmt: skip
            section = f"host {number}"
            cp.add_section(section)
            HostUtils.save_host_to_ini(cp, section, host, "")
            # save_host_to_ini encrypts even an empty password, and a fresh HOME has no
            # .gcm.key to decrypt it with: put the empty one back.
            cp.set(section, "pass", "")
    tree.save(cp)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        cp.write(stream)


def prepare(home: Path, repo: Path) -> Path:
    """Fill `home` with what the window half runs against; the `SHELL` wrapper's path.

    - `gcm.conf`, holding `TREE`.
    - `.sudo_as_admin_successful`, or /etc/bash.bashrc prints its hint about sudo in the
      console, for a user in the sudo group.
    - `demo.rc`: `cd` to `repo`, the prompt, then the checkout's `git log` and `git status`.
    - `demo-shell`, which runs bash with that `demo.rc`. A wrapper, as `SHELL` names one
      program. No GTK `settings.ini` is written, so the font is GTK's default.

    `window` takes the `demo.rc` as the sign that it runs under a HOME made here.
    """
    from tools import sandbox

    home.mkdir(parents=True, exist_ok=True)
    (home / ".sudo_as_admin_successful").touch()
    rc = home / "demo.rc"
    rc.write_text(
        f"cd {shlex.quote(str(repo))}\n"
        f"PS1={shlex.quote(PROMPT)}\n"
        "git --no-pager log --oneline --decorate --color=always -6; echo; "
        "git -c color.status=always status -sb; echo\n",
        encoding="utf-8",
    )
    shell = home / "demo-shell"
    shell.write_text(f"#!/bin/sh\nexec bash --rcfile {shlex.quote(str(rc))} -i\n", encoding="utf-8")
    shell.chmod(0o755)
    write_config(sandbox.config_file(home))
    return shell


def environment(base: dict[str, str], home: Path, display: str, shell: Path) -> dict[str, str]:
    """`base` as the window half runs in: under `home`, on `display`, in English.

    `tools/sandbox.py` removes what points GCM at another configuration, checkout, agent or
    desktop. On top of that the locale is pinned, or a developer's own gives the README a
    translated GCM, and `GTK_THEME` is removed, as it overrides the GTK default the scratch
    HOME is there for.
    """
    from tools import sandbox

    env = sandbox.environment(base, home, None, display=display)
    for name in list(env):
        if name in ("LANGUAGE", "GTK_THEME") or name.startswith("LC_"):
            del env[name]
    env["LANG"] = "C.UTF-8"
    env["SHELL"] = str(shell)
    return env


def png_size(path: Path) -> tuple[int, int] | None:
    """The width and height in a PNG's IHDR, or None for a file that is not a PNG.

    It reads the first 24 bytes, the signature and the first chunk's length, type, width and
    height, and never raises on a bad file.
    """
    try:
        with path.open("rb") as stream:
            head = stream.read(24)
    except OSError:
        return None
    if len(head) < 24 or head[:8] != PNG_SIGNATURE or head[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", head[16:24])
    return width, height


def run(out: Path, deadline: float = DEADLINE) -> bool:
    """Take the screenshot and put it at `out`. False, with `out` as it was, on a failure.

    The window half runs with the checkout's interpreter, `sys.executable`, and not `uv run`,
    whose cache would be sought under the scratch HOME. `out` is replaced only after a run
    that exited 0 within `deadline` seconds, printed no traceback and wrote a PNG of `SIZE`:
    a run can write a PNG of that size with the tree empty, and one can fail in a callback
    and never end. The Xvfb is stopped on every way out Python handles: a failure, Ctrl+C
    and the deadline. Unlike `doit sandbox --xvfb` (#527), it does not handle a SIGTERM sent
    to this process alone, which leaves the Xvfb running.
    """
    from tests import xdisplay

    started = xdisplay.start()
    if started is None:
        print("No Xvfb came up: sudo apt install xvfb")
        return False
    xvfb, display = started
    try:
        # A killed run's shells may still write to HOME as it is removed.
        with tempfile.TemporaryDirectory(
            prefix="gcm-screenshot-", ignore_cleanup_errors=True
        ) as scratch:
            home = Path(scratch) / "home"
            shot = Path(scratch) / "screenshot.png"
            shell = prepare(home, REPO)
            env = environment(dict(os.environ), home, display, shell)
            print(f"GCM on {display} under HOME={home}")
            try:
                done = subprocess.run(  # nosec B603
                    [sys.executable, "-u", str(Path(__file__).resolve()), "--window", str(shot)],
                    env=env,
                    cwd=REPO,
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=deadline,
                    check=False,
                )
            except subprocess.TimeoutExpired as expired:
                # Bytes or None, whatever `text` says.
                raw = expired.stderr
                stderr = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else ""
                return fail(f"GCM was still running after {deadline:g} s, and was killed", stderr)
            if done.returncode != 0:
                return fail(f"GCM exited with status {done.returncode}", done.stderr)
            if "Traceback" in done.stderr:
                return fail("GCM printed a traceback", done.stderr)
            size = png_size(shot)
            if size != SIZE:
                return fail(f"the PNG is {size}, not {SIZE}", done.stderr)
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(shot, out)
            print(f"Wrote {out}")
            return True
    finally:
        xdisplay.stop(xvfb)


def fail(why: str, stderr: str) -> bool:
    """Say why a run failed and show what GCM printed last; always False."""
    print(f"No screenshot: {why}.")
    if stderr.strip():
        print(stderr[-STDERR_TAIL:])
    return False


def expected_rows() -> tuple[list[str], list[str]]:
    """The folder paths and the host paths the server tree must show, each sorted."""
    folders: set[str] = set()
    hosts: list[str] = []
    for group, names in TREE:
        parts = group.split("/")
        folders.update("/".join(parts[:count]) for count in range(1, len(parts) + 1))
        hosts.extend(f"{group}/{name}" for name in names)
    return sorted(folders), sorted(hosts)


def tree_rows(model: Any, view: Any) -> tuple[list[str], list[str], list[str]]:
    """The folder paths, host paths and collapsed folder paths of a server tree, each sorted.

    `model`'s column 0 holds a row's name and column 1 its host, None on a folder row. A path
    is the names from the top down, joined by `/`. The lists are sorted and not sets, so a
    row drawn twice shows. A folder is collapsed where `view` does not show it expanded.
    """
    folders: list[str] = []
    hosts: list[str] = []
    collapsed: list[str] = []

    def walk(parent: Any, prefix: str) -> None:
        row = model.iter_children(parent)
        while row is not None:
            path = prefix + model.get_value(row, 0)
            if model.get_value(row, 1) is None:
                folders.append(path)
                if not view.row_expanded(model.get_path(row)):
                    collapsed.append(path)
            else:
                hosts.append(path)
            walk(row, path + "/")
            row = model.iter_next(row)

    walk(None, "")
    return sorted(folders), sorted(hosts), sorted(collapsed)


def problems(w: Any, gtk: Any) -> list[str]:
    """What is wrong with the main window `w` before its picture is taken; none when right.

    A read of a window returns what covers it, so any other window showing is a problem.
    """
    found: list[str] = []
    pages = w.nbConsole.get_n_pages()
    if pages != TABS:
        found.append(f"{pages} tabs are open, not {TABS}")
    folders, hosts, collapsed = tree_rows(w.treeModel, w.treeServers)
    want_folders, want_hosts = expected_rows()
    if folders != want_folders:
        found.append(f"the tree's folders are {folders}, not {want_folders}")
    if hosts != want_hosts:
        found.append(f"the tree's hosts are {hosts}, not {want_hosts}")
    if collapsed:
        found.append(f"these folders are collapsed: {collapsed}")
    others = [
        f"{type(other).__name__} {other.get_title()!r}"
        for other in gtk.Window.list_toplevels()
        if other is not w.wMain
        and other.get_visible()
        and other.get_window_type() == gtk.WindowType.TOPLEVEL
    ]
    if others:
        found.append(f"another window is showing: {others}")
    return found


def die(message: str) -> NoReturn:
    """Say `message` on stderr and end the process at once, with status 1."""
    print(message, file=sys.stderr, flush=True)
    os._exit(1)


def or_die(step: Callable[[], None]) -> Callable[[], bool]:
    """A GLib callback that runs `step` once, and ends the process if it raises.

    PyGObject prints an exception from a callback and carries on, so GCM would stay up,
    waiting for a capture that never comes. `os._exit` ends GCM at once, and the shells in
    its tabs end with their terminals: after runs that ended so, no shell, GCM or Xvfb
    was left (#546).
    """

    def callback() -> bool:
        try:
            step()
        except Exception:
            traceback.print_exc()
            sys.stderr.flush()
            os._exit(1)
        return False

    return callback


def main_window(application: Any) -> Any:
    """GCM's main window, which `application` has only once it has activated."""
    w = application._controller
    if w is None:
        die("GCM had not opened its main window when the window half needed it.")
    return w


def window(shot: Path) -> int:
    """Run GCM, open its tabs, check its window and save its picture to `shot`.

    The script of docs/PROBING.md that took the README's shot (#494), as a function. 0 is
    returned once the picture is saved and GCM quit; the process ends with 1 at once where
    a step raised or a check failed, with nothing written. It runs only under the HOME
    `prepare` made: run by hand it would start GCM on the person's own, and GCM saves its
    window's size to `gcm.conf` as it quits.
    """
    if not (Path.home() / "demo.rc").exists():
        print(USAGE, file=sys.stderr)
        return 2

    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, GLib, Gtk

    from gnome_connection_manager import app

    app.conf.CHECK_UPDATES = False
    application = app.GcmApplication()
    saved = False

    def capture() -> None:
        nonlocal saved
        w = main_window(application)
        found = problems(w, Gtk)
        if found:
            die("The window is not the README's:\n" + "\n".join(found))
        width, height = w.wMain.get_allocated_width(), w.wMain.get_allocated_height()
        pixbuf = Gdk.pixbuf_get_from_window(w.wMain.get_window(), 0, 0, width, height)
        if pixbuf is None:
            die("The window's picture could not be read: it is not on the screen.")
        pixbuf.savev(str(shot), "png", [], [])
        saved = True
        application.quit()

    def start() -> None:
        w = main_window(application)
        w.treeServers.expand_all()
        w.wMain.resize(*SIZE)
        w.hpMain.set_position(250)
        for _ in range(TABS - w.nbConsole.get_n_pages()):
            application.activate_action("new-local", None)
        GLib.timeout_add(3000, or_die(capture))

    GLib.timeout_add(1500, or_die(start))
    code = application.run(["gcm"])
    return 0 if saved and code == 0 else 1


def main(argv: list[str] | None = None) -> int:
    """`--window <png>` runs `window`; anything else says what the command is, and fails."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) == 2 and args[0] == "--window":
        return window(Path(args[1]))
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
