"""A host's commands run on this computer, before connecting and after disconnecting (#238).

Each scenario runs against real GTK and real terminals, in a process of its own. The
session is a fake `ssh`, which marks a file as it starts and ends when a status is typed
into its tab, and the commands mark the same file, so the order they ran in is read back
from it. Nothing reaches the network.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = r"""
import os, sys, tempfile, time
scenario = sys.argv[1]
root = tempfile.mkdtemp()
os.environ["HOME"] = root; sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk, Gdk, GLib, Vte
from gnome_connection_manager import app

app.conf.CONFIRM_ON_CLOSE_TAB = 0
app.conf.STARTUP_LOCAL = False  # only the tabs each scenario opens
app.conf.AUTO_CLOSE_TAB = 0  # an ended tab stays, to be read
app.wMain = w = app.Wmain(application=None)
w.wMain.resize(1200, 800)  # room for every line: a small terminal scrolls the first away
application = app.GcmApplication()
application._controller = w
shown = []
app.msgbox = lambda text, *args, **kwargs: shown.append(text)
MARKS = os.path.join(root, "marks")
FLAG = os.path.join(root, "flag")

def pump(seconds=0.2):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        Gtk.main_iteration_do(False)
        time.sleep(0.005)

def until(done, seconds=10):
    end = time.monotonic() + seconds
    while not done() and time.monotonic() < end:
        pump(0.05)
    pump(0.3)  # and a little longer, for anything that should not follow

def marks():
    return open(MARKS).read().splitlines() if os.path.exists(MARKS) else []

def script(name, body):
    path = os.path.join(root, name)
    with open(path, "w") as out:
        out.write("#!/bin/sh\n" + body + "\n")
    os.chmod(path, 0o755)
    return path

# The session: marks the file, and ends with the status typed into its tab.
app.SSH_BIN = script("ssh", f'echo session >> {MARKS}\necho "session up"\nread code\nexit "$code"')

def open_host(before="", after="", name="db-01", kind="ssh", address="10.9.9.9", port="22"):
    host = app.Host("prod", name, "", address, "ops", "", "", port, "", kind)
    host.before_command = before
    host.after_command = after
    w.addTab(w.nbConsole, host)
    return host

def pages():
    notebook = w.nbConsole
    return [notebook.get_nth_page(n) for n in range(notebook.get_n_pages())]

def label(page):
    return page.get_parent().get_tab_label(page)

def terminal(page):
    return app.page_terminal(page)

def screen(page):
    return terminal(page).get_text_format(Vte.Format.TEXT)

def end_session(page, status):
    terminal(page).feed_child(f"{status}\n".encode())

if scenario == "the-session-waits-for-the-command-before":
    open_host(before=f"echo before >> {MARKS}; sleep 1; echo prepared")
    until(lambda: marks() == ["before"], 5)
    assert marks() == ["before"], marks()  # and not yet the session
    until(lambda: "session" in marks())
    assert marks() == ["before", "session"], marks()
    [page] = pages()
    text = screen(page)
    assert "prepared" in text and text.index("prepared") < text.index("session up"), text
    assert label(page).is_active

elif scenario == "a-failing-command-before-connects-nothing":
    open_host(before=f"echo before >> {MARKS}; exit 3", after=f"echo after >> {MARKS}")
    [page] = pages()
    until(lambda: not label(page).is_active)
    pump(1.0)
    assert marks() == ["before"], marks()
    assert not label(page).is_active

elif scenario == "a-failing-command-before-is-not-a-clean-exit":
    app.conf.AUTO_CLOSE_TAB = 2  # Only on clean exit
    open_host(before="exit 3")
    until(lambda: not label(pages()[0]).is_active)
    assert len(pages()) == 1, pages()

elif scenario == "ctrl-c-stops-the-command-before":
    open_host(before=f"echo before >> {MARKS}; sleep 30; echo late >> {MARKS}", after=f"echo after >> {MARKS}")
    [page] = pages()
    until(lambda: marks() == ["before"])
    pump(0.5)
    # Ctrl+C as typed: a key event through the window, to the terminal with the keyboard.
    w.wMain.set_focus(terminal(page))
    keymap = Gdk.Keymap.get_for_display(Gdk.Display.get_default())
    keyboard = Gdk.Display.get_default().get_default_seat().get_keyboard()
    for kind in (Gdk.EventType.KEY_PRESS, Gdk.EventType.KEY_RELEASE):
        event = Gdk.Event.new(kind)
        event.key.window = w.wMain.get_window()
        event.key.time = Gdk.CURRENT_TIME
        event.key.state = Gdk.ModifierType.CONTROL_MASK
        event.key.keyval = Gdk.KEY_c
        found, keys = keymap.get_entries_for_keyval(Gdk.KEY_c)
        event.key.hardware_keycode, event.key.group = keys[0].keycode, keys[0].group
        event.set_device(keyboard)
        Gtk.main_do_event(event)
    until(lambda: not label(page).is_active, 5)
    assert not label(page).is_active
    pump(1.0)
    assert marks() == ["before"], marks()

elif scenario == "closing-the-tab-during-the-command-before":
    open_host(before=f"echo before >> {MARKS}; sleep 30", after=f"echo after >> {MARKS}")
    [page] = pages()
    until(lambda: marks() == ["before"])
    label(page).close_tab(page)
    pump(1.5)
    assert marks() == ["before"], marks()
    assert pages() == []

elif scenario == "the-command-after-runs-when-the-session-ends":
    # Quoted for the shell: the name is one argument, and its ; ends nothing.
    open_host(after=f"echo after {{name}} {{address}} >> {MARKS}", name="web 01; x")
    [page] = pages()
    until(lambda: marks() == ["session"])
    end_session(page, 0)
    until(lambda: len(marks()) == 2)
    assert marks() == ["session", "after web 01; x 10.9.9.9"], marks()
    assert shown == [], shown

elif scenario == "a-failing-command-after-is-reported":
    open_host(after="exit 5", name="db-01")
    [page] = pages()
    until(lambda: marks() == ["session"])
    end_session(page, 0)
    until(lambda: shown)
    assert shown == ["The command after disconnecting from db-01 exited with status 5"], shown

elif scenario == "closing-the-tab-runs-the-command-after":
    open_host(after=f"echo after >> {MARKS}")
    [page] = pages()
    until(lambda: marks() == ["session"])
    label(page).close_tab(page)
    until(lambda: len(marks()) == 2)
    pump(1.0)
    assert marks() == ["session", "after"], marks()

elif scenario == "ctrl-q-runs-the-command-after-once":
    app.Wmain.quit_application = lambda self: None  # the rest of quitting, not the exit
    open_host(after=f"echo after >> {MARKS}")
    [page] = pages()
    until(lambda: marks() == ["session"])
    application._on_action_quit(None, None)
    until(lambda: len(marks()) == 2)
    assert marks() == ["session", "after"], marks()
    end_session(page, 0)  # the session's own end afterwards runs nothing more
    until(lambda: not label(page).is_active)
    pump(1.0)
    assert marks() == ["session", "after"], marks()

elif scenario == "closing-the-window-runs-the-command-after":
    # Measured, VTE reports each session's end as the window's terminals are destroyed.
    app.Wmain.quit_application = lambda self: None
    open_host(after=f"echo after >> {MARKS}")
    until(lambda: marks() == ["session"])
    w.wMain.destroy()
    until(lambda: len(marks()) == 2)
    pump(1.0)
    assert marks() == ["session", "after"], marks()

elif scenario == "reconnect-runs-the-command-before-again":
    # Fails the first time, before anything was spawned, and Reconnect still connects.
    open_host(before=f"echo before >> {MARKS}; test -e {FLAG}", after=f"echo after >> {MARKS}")
    [page] = pages()
    until(lambda: not label(page).is_active)
    assert marks() == ["before"], marks()
    open(FLAG, "w").close()
    application._on_action_console_reconnect(None, None)
    until(lambda: "session" in marks())
    assert marks() == ["before", "before", "session"], marks()
    end_session(page, 0)
    until(lambda: "after" in marks())
    application._on_action_console_reconnect(None, None)
    until(lambda: marks().count("session") == 2)
    assert marks() == ["before", "before", "session", "after", "before", "session"], marks()

elif scenario == "reconnect-sends-no-commands-after-login":
    # As before #238: the first connection sends them, and Reconnect does not. A host with
    # no address runs the local shell, here a fake that marks each line it is sent.
    app.SHELL = script("shell", f'while read line; do echo "got $line" >> {MARKS}; [ "$line" = quit ] && exit 0; done')
    host = app.Host("prod", "local-1", "", "", "ops", "", "", "22", "", "ssh", "hello")
    host.commands_enabled = True
    host.before_command = f"echo before >> {MARKS}"
    w.addTab(w.nbConsole, host)
    [page] = pages()
    until(lambda: "got hello" in marks())
    end_session(page, "quit")
    until(lambda: not label(page).is_active)
    application._on_action_console_reconnect(None, None)
    until(lambda: marks().count("before") == 2)
    pump(2.0)  # the commands went 700 ms after the first connection
    assert marks() == ["before", "got hello", "got quit", "before"], marks()

elif scenario == "clone-runs-the-command-before-again":
    open_host(before=f"echo before >> {MARKS}")
    until(lambda: marks() == ["before", "session"])
    application._on_action_console_clone(None, None)
    until(lambda: marks().count("session") == 2)
    assert marks() == ["before", "session", "before", "session"], marks()
    assert len(pages()) == 2

elif scenario == "a-host-without-them-connects-at-once":
    started = time.monotonic()
    open_host()
    until(lambda: marks() == ["session"])
    assert marks() == ["session"], marks()
    [page] = pages()
    assert not hasattr(terminal(page), "before_then") or terminal(page).before_then is None

elif scenario in ("a-page-waits-for-the-command-before", "a-page-that-cannot-be-prepared"):
    # A type drawn by a page of its own, as VNC's is, without needing gtk-vnc.
    opened = []

    class Page(Gtk.Box):
        def __init__(self, host, ended):
            super().__init__()
            self.ended = ended
            self.keyboard = Gtk.DrawingArea()
            self.keyboard.set_can_focus(True)
            self.add(self.keyboard)
            self.show_all()

        def open(self):
            opened.append(time.monotonic())

    app.TYPE_PAGES = {"vnc": Page}
    status = 0 if scenario == "a-page-waits-for-the-command-before" else 4
    open_host(before=f"echo before >> {MARKS}; sleep 0.5; exit {status}", after=f"echo after >> {MARKS}", kind="vnc")
    assert pages() == [] and opened == [], pages()  # not before the command has run
    until(lambda: opened or shown, 5)
    if status:
        assert pages() == [] and opened == [], pages()
        assert shown == ["The command before connecting to db-01 exited with status 4"], shown
    else:
        [page] = pages()
        assert marks() == ["before"] and len(opened) == 1, (marks(), opened)
        page.ended(0)
        until(lambda: "after" in marks())
        assert marks() == ["before", "after"], marks()  # from its end, with the tab open
        label(page).close_tab(page)  # its end came first: nothing more runs
        pump(1.0)
        assert marks() == ["before", "after"], marks()

elif scenario == "closing-a-pages-tab-runs-the-command-after":
    class Page(Gtk.Box):
        def __init__(self, host, ended):
            super().__init__()
            self.keyboard = Gtk.DrawingArea()
            self.add(self.keyboard)
            self.show_all()

        def open(self):
            pass

    app.TYPE_PAGES = {"vnc": Page}
    open_host(after=f"echo after >> {MARKS}", kind="vnc")
    [page] = pages()
    label(page).close_tab(page)
    until(lambda: "after" in marks())
    assert marks() == ["after"], marks()

elif scenario == "a-web-host-waits-for-the-command-before":
    browsed = []
    app.open_in_browser = browsed.append
    open_host(before=f"echo before >> {MARKS}", kind="web", address="bmc.example", port="443")
    assert browsed == [], browsed
    until(lambda: browsed)
    assert browsed == ["https://bmc.example"] and marks() == ["before"], (browsed, marks())
    open_host(before="exit 1", kind="web", address="bmc.example", port="443", name="bmc")
    until(lambda: shown)
    assert browsed == ["https://bmc.example"], browsed
    assert shown == ["The command before connecting to bmc exited with status 1"], shown

elif scenario == "the-host-dialog":
    host = app.Host("prod", "db-01", "", "10.9.9.9", "ops", "", "", "22", "", "ssh")
    host.before_command = "nmcli con up office"
    host.after_command = "nmcli con down office"
    host.keep_alive = "0"  # text, as a host read from gcm.conf has it
    dialog = app.Whost()
    dialog.init("prod", host)
    before = dialog.get_widget("txtBeforeCommand")
    after = dialog.get_widget("txtAfterCommand")
    assert (before.get_text(), after.get_text()) == (host.before_command, host.after_command)
    assert before.get_sensitive() and after.get_sensitive()

    def choose(kind):
        model = dialog.cmbType.get_model()
        dialog.cmbType.set_active([row[0] for row in model].index(kind))
        pump()

    choose("web")
    assert before.get_sensitive() and before.get_text() == host.before_command
    assert not after.get_sensitive() and after.get_text() == ""
    choose("vnc")
    assert after.get_sensitive()
    dialog.get_widget("wHost").destroy()

else:
    raise SystemExit("no scenario " + scenario)
print("OK")
"""


@pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"),
    reason="needs a display for a real terminal",
)
@pytest.mark.parametrize(
    "scenario",
    [
        "the-session-waits-for-the-command-before",
        "a-failing-command-before-connects-nothing",
        "a-failing-command-before-is-not-a-clean-exit",
        "ctrl-c-stops-the-command-before",
        "closing-the-tab-during-the-command-before",
        "the-command-after-runs-when-the-session-ends",
        "a-failing-command-after-is-reported",
        "closing-the-tab-runs-the-command-after",
        "ctrl-q-runs-the-command-after-once",
        "closing-the-window-runs-the-command-after",
        "reconnect-runs-the-command-before-again",
        "reconnect-sends-no-commands-after-login",
        "clone-runs-the-command-before-again",
        "a-host-without-them-connects-at-once",
        "a-page-waits-for-the-command-before",
        "a-page-that-cannot-be-prepared",
        "closing-a-pages-tab-runs-the-command-after",
        "a-web-host-waits-for-the-command-before",
        "the-host-dialog",
    ],
)
def test_a_hosts_local_commands_against_real_gtk(scenario):
    pytest.importorskip("gi", reason="PyGObject not available")
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT, scenario],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        timeout=120,
    )

    assert result.returncode == 0, result.stderr[-3000:]
    assert "OK" in result.stdout
