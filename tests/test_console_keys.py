"""A key typed into a console belongs to its program, except GCM's [shortcuts] (#419).

GCM's shortcuts are accelerators, which GTK runs before the focused widget sees the key. With
the defaults GCM had, Ctrl+S opened Save as in a console and never reached the program there,
and so for Ctrl+F, G, H, N and W, which are [shortcuts], and Ctrl+E, R and Q, F1, F9 and
Shift+F9, which are fixed. Each scenario runs real GCM, started as GCM starts so that its
shortcuts are the windows' accelerators, on an Xvfb of its own, with real key presses through
XTest. A logger stands in for the program in the console. It puts its terminal in raw mode, as
a full-screen program does, and writes what each read of it returned, in hex, to a file the
scenario reads.

The scenarios fail against the code before the fix, each for the key it names: Ctrl+S opened
Save buffer and the logger read nothing, and so for Ctrl+E, Ctrl+Q, and a [keys] sequence on
Ctrl+R. BackSpace in the Shortcut column of Preferences bound BackSpace.

Their own display, because they press keys with real X input, which go to whichever window
has the keyboard: on the display the other tests share, another test's window could take
them. XTest is reached through ctypes, so that python-xlib need not be a dependency.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_connections import glib_complaints
from tests.test_console_window import _private_display

REPO = Path(__file__).resolve().parents[1]

# The program in the console: what each read of its terminal returned, in hex, one per line.
# `start` is the program starting, so a second one is the console starting it again, and
# `ready` that the terminal is raw. The log is beside the program, wherever it is put.
_LOGGER = """#!/usr/bin/env python3
import os, tty

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "log")


def note(text):
    with open(LOG, "a") as handle:
        handle.write(text + "\\n")


note("start")
tty.setraw(0)
note("ready")
while True:
    data = os.read(0, 64)
    if not data:
        break
    note(data.hex())
"""

_SCRIPT = r'''
import ctypes, faulthandler, os, sys, tempfile, time
faulthandler.dump_traceback_later(100, exit=True)
scenario, scratch = sys.argv[1], sys.argv[2]
home = tempfile.mkdtemp()
os.environ["HOME"] = home
# A local console runs $SHELL, which is the logger, read when GCM is imported.
LOGGER, LOG = os.path.join(scratch, "logger"), os.path.join(scratch, "log")
os.environ["SHELL"] = LOGGER
sys.argv = ["gcm"]

if scenario == "an-existing-configuration":
    # What GCM saved before the new defaults: Save on Ctrl+S, and a sequence for Ctrl+R,
    # a key GCM took from consoles. CONFIG_FILE is chosen as GCM is imported.
    os.makedirs(os.path.join(home, ".config", "gcm"))
    with open(os.path.join(home, ".config", "gcm", "gcm.conf"), "w") as handle:
        handle.write("[shortcuts]\nsave = CTRL+S\n\n[keys]\nctrl+r = \\x1b[A\n")

import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gdk, Gtk, Vte
from gnome_connection_manager import app

app.conf.CONFIRM_ON_CLOSE_TAB = 0
app.conf.STARTUP_LOCAL = False
app.conf.CHECK_UPDATES = False
app.conf.AUTO_CLOSE_TAB = 0
app.conf.BELL_NOTIFY = 0
# Started as GCM starts, so that its shortcuts are the windows' accelerators. It is
# NON_UNIQUE, so it never reaches a GCM already running.
application = app.GcmApplication()
assert application.register(None)
application.activate()
w = application._controller
w.wMain.move(0, 0)
w.wMain.resize(1000, 700)

def pump(seconds=0.2):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        Gtk.main_iteration_do(False)
        time.sleep(0.005)

def until(condition, seconds=10):
    end = time.monotonic() + seconds
    while time.monotonic() < end and not condition():
        Gtk.main_iteration_do(False)
        time.sleep(0.005)
    return condition()

def use(window):
    window.present()
    assert until(window.is_active), window.get_title()

# Real input, through XTest, on the scenario's own display.
CONTROL, SHIFT, RETURN, BACKSPACE, DELETE = 0xFFE3, 0xFFE1, 0xFF0D, 0xFF08, 0xFFFF
F1, F9, F11 = 0xFFBE, 0xFFC6, 0xFFC8
X = {}

def xtest():
    if not X:
        x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
        xtst = ctypes.cdll.LoadLibrary("libXtst.so.6")
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XFlush.argtypes = [ctypes.c_void_p]
        x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        x11.XKeysymToKeycode.restype = ctypes.c_ubyte
        xtst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
        display = x11.XOpenDisplay(None)
        assert display, "no connection to the display for XTest"
        X.update(x11=x11, xtst=xtst, display=display)
    return X

def press(*keysyms):
    """Press the keys together, and let them go in reverse, as a person does."""
    x = xtest()
    codes = [x["x11"].XKeysymToKeycode(x["display"], keysym) for keysym in keysyms]
    for code in codes:
        x["xtst"].XTestFakeKeyEvent(x["display"], code, True, 0)
    for code in reversed(codes):
        x["xtst"].XTestFakeKeyEvent(x["display"], code, False, 0)
    x["x11"].XFlush(x["display"])
    pump(0.4)

# What the logger has written: `start`, `ready`, and one hex string for each read.
def log():
    try:
        with open(LOG) as handle:
            return handle.read().split()
    except FileNotFoundError:
        return []

def reads():
    return [line for line in log() if line not in ("start", "ready")]

def got(*keysyms):
    """Press the keys, and say what the program read, in hex: "" for nothing."""
    before = len(reads())
    press(*keysyms)
    until(lambda: len(reads()) > before, seconds=1)
    pump(0.1)
    return "".join(reads()[before:])

def open_console(host=None):
    """A local console running the logger, with the keyboard in it, once its terminal is raw."""
    ready = log().count("ready")
    w.addTab(w.nbConsole, host or app.Host("", "logger"))
    page = w.nbConsole.get_nth_page(w.nbConsole.get_n_pages() - 1)
    terminal = app.page_terminal(page)
    assert until(lambda: log().count("ready") > ready), log()
    # addTab gives the console the keyboard again from a 200 ms timer: wait that out
    pump(0.5)
    return page, terminal

# What GCM would do, recorded in place of doing it: the window a key opens would take the
# keyboard, and quitting would end the scenario.
calls = {"save": [], "edit": [], "refresh": [], "about": [], "quit": [], "next": [], "back": [],
         "full": []}
w.show_save_buffer = lambda terminal: calls["save"].append(terminal)
w.toggle_fullscreen = lambda: calls["full"].append(1)
w.on_bntEdit_clicked = lambda *_args: calls["edit"].append(1)
w.updateTree = lambda *_args: calls["refresh"].append(1)
w.on_acerca_de1_activate = lambda *_args: calls["about"].append(1)
w.request_quit = lambda: calls["quit"].append(1)
w.on_btnSearch_clicked = lambda *_args: calls["next"].append(1)
w.on_btnSearchBack_clicked = lambda *_args: calls["back"].append(1)

def taken():
    """How many times each recorded thing ran."""
    return {name: len(done) for name, done in calls.items() if done}

def toggles():
    """Whether the server panel and the toolbar show, as the actions that toggle them say."""
    return tuple(application.lookup_action(name).get_state().get_boolean()
                 for name in ("toggle-panel", "toggle-toolbar"))

if scenario == "the-default-keys":
    page, term = open_console()
    use(w.wMain)
    assert w.wMain.get_focus() is term, w.wMain.get_focus()
    assert log() == ["start", "ready"], log()

    # Ctrl+S, F, G, H, N and W are a program's, and GCM took them. Read in raw mode, each
    # is the control character the letter makes.
    for name, keys, expected in (
        ("Ctrl+S", (CONTROL, ord("s")), "13"),
        ("Ctrl+F", (CONTROL, ord("f")), "06"),
        ("Ctrl+G", (CONTROL, ord("g")), "07"),
        ("Ctrl+H", (CONTROL, ord("h")), "08"),
        ("Ctrl+N", (CONTROL, ord("n")), "0e"),
        ("Ctrl+W", (CONTROL, ord("w")), "17"),
    ):
        read = got(*keys)
        assert read == expected, f"{name}: the program read {read!r}, and GCM did {taken()}"
    assert taken() == {}, taken()
    assert w.nbConsole.get_n_pages() == 1, "a key closed the tab"
    assert log().count("start") == 1, "a key started the program again"

    # GCM's own are on Ctrl+Shift, which a program cannot tell from Ctrl+letter, so it
    # loses nothing it would have had. The program reads none of them.
    assert got(CONTROL, SHIFT, ord("s")) == ""
    assert taken() == {"save": 1} and calls["save"] == [term], taken()
    assert got(CONTROL, SHIFT, ord("g")) == ""
    assert got(CONTROL, SHIFT, ord("b")) == ""
    assert taken() == {"save": 1, "next": 1, "back": 1}, taken()
    assert got(CONTROL, SHIFT, ord("l")) == ""
    assert w.wMain.get_focus() is w.search_box(), w.wMain.get_focus()
    w.wMain.set_focus(term)
    pump(0.3)
    assert got(CONTROL, SHIFT, ord("r")) == ""
    assert until(lambda: log().count("ready") == 2), log()
    assert log().count("start") == 2, "Reconnect did not start the program again"
    assert w.nbConsole.get_n_pages() == 1
    assert got(CONTROL, SHIFT, ord("w")) == ""
    assert until(lambda: w.nbConsole.get_n_pages() == 0), "Close console left the tab open"

elif scenario == "the-fixed-keys":
    page, term = open_console()
    use(w.wMain)
    assert w.wMain.get_focus() is term, w.wMain.get_focus()
    assert toggles() == (True, True), toggles()

    # In a console they are the program's: Ctrl+E, Ctrl+R and Ctrl+Q as control characters,
    # and the function keys as the escape sequences VTE sends them as.
    for name, keys, expected in (
        ("Ctrl+E", (CONTROL, ord("e")), "05"),
        ("Ctrl+R", (CONTROL, ord("r")), "12"),
        ("Ctrl+Q", (CONTROL, ord("q")), "11"),
    ):
        read = got(*keys)
        assert read == expected, f"{name}: the program read {read!r}, and GCM did {taken()}"
    for name, keys in (("F1", (F1,)), ("F9", (F9,)), ("Shift+F9", (SHIFT, F9))):
        read = got(*keys)
        assert read.startswith("1b"), f"{name}: the program read {read!r}, and GCM did {taken()}"
    assert taken() == {}, taken()
    assert toggles() == (True, True), "F9 or Shift+F9 hid the panel or the toolbar in a console"

    # With the keyboard in the server tree, they act, as they did, and the program has none.
    reading = list(reads())
    w.treeServers.grab_focus()
    pump(0.3)
    assert w.wMain.get_focus() is w.treeServers, w.wMain.get_focus()
    press(CONTROL, ord("e"))
    assert taken() == {"edit": 1}, taken()
    press(CONTROL, ord("r"))
    assert taken() == {"edit": 1, "refresh": 1}, taken()
    press(F1)
    assert taken() == {"edit": 1, "refresh": 1, "about": 1}, taken()
    press(SHIFT, F9)
    assert toggles() == (True, False), toggles()
    press(CONTROL, ord("q"))
    assert taken() == {"edit": 1, "refresh": 1, "about": 1, "quit": 1}, taken()
    # Last, as it hides the panel the keyboard is in.
    press(F9)
    assert toggles() == (False, False), toggles()
    assert reads() == reading, "a key reached the program from the server tree"

elif scenario == "a-prefix-key":
    # Ctrl+B is a prefix, as tmux's is (#452). The key after it is the program's, GCM's
    # shortcut or not, and the key after that is GCM's again.
    app.conf.PREFIX_KEYS = "CTRL+B"
    page, term = open_console()
    use(w.wMain)
    assert w.wMain.get_focus() is term, w.wMain.get_focus()

    assert got(CONTROL, ord("b")) == "02", "the prefix did not reach the program"
    read = got(CONTROL, SHIFT, ord("s"))
    assert read == "13", f"the program read {read!r}, and GCM did {taken()}"
    assert taken() == {}, taken()
    # GCM acts again on the key after that.
    assert got(CONTROL, SHIFT, ord("s")) == ""
    assert taken() == {"save": 1}, taken()

    # A modifier alone between the two does not use the pass up.
    assert got(CONTROL, ord("b")) == "02"
    assert got(SHIFT) == ""
    read = got(CONTROL, SHIFT, ord("s"))
    assert read == "13", f"the program read {read!r}, and GCM did {taken()}"
    assert taken() == {"save": 1}, taken()

    # F11 is Fullscreen, and after a prefix it is the program's.
    assert got(CONTROL, ord("b")) == "02"
    read = got(F11)
    assert read.startswith("1b"), f"the program read {read!r}, and GCM did {taken()}"
    assert taken() == {"save": 1}, taken()
    assert got(F11) == "" and taken() == {"save": 1, "full": 1}, taken()

elif scenario == "a-hosts-prefix-key":
    # A host's prefix keys add to Preferences', and a host without them has Preferences' alone.
    app.conf.PREFIX_KEYS = "CTRL+B"
    host = app.Host("", "logger")
    host.prefix_keys = "CTRL+A"
    page, term = open_console(host)
    use(w.wMain)
    assert w.wMain.get_focus() is term, w.wMain.get_focus()

    assert got(CONTROL, ord("a")) == "01"
    assert got(CONTROL, SHIFT, ord("s")) == "13" and taken() == {}, taken()
    assert got(CONTROL, ord("b")) == "02"
    assert got(CONTROL, SHIFT, ord("s")) == "13" and taken() == {}, taken()
    assert got(CONTROL, SHIFT, ord("s")) == "" and taken() == {"save": 1}, taken()

    # A console of a host with none of its own: Ctrl+A is no prefix there.
    page, plain = open_console()
    use(w.wMain)
    assert w.wMain.get_focus() is plain, w.wMain.get_focus()
    assert got(CONTROL, ord("a")) == "01"
    assert got(CONTROL, SHIFT, ord("s")) == "" and taken() == {"save": 2}, taken()

elif scenario == "an-existing-configuration":
    assert app.CONFIG_FILE == os.path.join(home, ".config", "gcm", "gcm.conf"), app.CONFIG_FILE
    page, term = open_console()
    use(w.wMain)
    assert w.wMain.get_focus() is term, w.wMain.get_focus()

    # Save on Ctrl+S is kept, as the file says, and still Save buffer. So is Ctrl+Shift+S.
    assert got(CONTROL, ord("s")) == ""
    assert calls["save"] == [term], taken()
    assert got(CONTROL, SHIFT, ord("s")) == ""
    assert calls["save"] == [term, term], taken()
    # [keys] had no say over Ctrl+R, which GCM took. A console is given it first now, so
    # the sequence is sent, and the program reads it in place of Ctrl+R's own.
    read = got(CONTROL, ord("r"))
    assert read == "1b5b41", f"the program read {read!r}, and GCM did {taken()}"
    assert "refresh" not in taken(), taken()
    # A command the file does not name takes its new key, and leaves the old one to the program.
    assert got(CONTROL, ord("w")) == "17", "Ctrl+W did not reach the program"
    assert w.nbConsole.get_n_pages() == 1
    assert got(CONTROL, SHIFT, ord("w")) == ""
    assert until(lambda: w.nbConsole.get_n_pages() == 0), "Close console is not on Ctrl+Shift+W"

elif scenario == "an-ended-console":
    page, term = open_console()
    use(w.wMain)
    assert w.wMain.get_focus() is term, w.wMain.get_focus()
    # Running, the program has them: nothing acts (the-fixed-keys reads each in full).
    assert got(CONTROL, ord("q")) == "11"
    assert taken() == {}, taken()

    # End the program, and leave the tab open, as Close console, Never, does.
    pid = term.child_pid
    assert pid, pid
    os.kill(pid, 9)
    assert until(lambda: term.child_pid is None), "the console kept its child_pid"
    pump(0.5)
    assert w.nbConsole.get_n_pages() == 1, "the tab closed"
    w.wMain.set_focus(term)
    pump(0.3)
    assert w.wMain.get_focus() is term, w.wMain.get_focus()
    assert toggles() == (True, True), toggles()

    # With no program to read them, the six act as they do outside a console.
    press(CONTROL, ord("e"))
    assert taken() == {"edit": 1}, taken()
    press(CONTROL, ord("r"))
    assert taken() == {"edit": 1, "refresh": 1}, taken()
    press(F1)
    assert taken() == {"edit": 1, "refresh": 1, "about": 1}, taken()
    press(SHIFT, F9)
    assert toggles() == (True, False), toggles()
    press(CONTROL, ord("q"))
    assert taken() == {"edit": 1, "refresh": 1, "about": 1, "quit": 1}, taken()
    press(F9)
    assert toggles() == (False, False), toggles()

elif scenario == "a-console-window":
    page, term = open_console()
    w.toggle_console_window(page)
    pump(0.5)
    window = w.console_window_of(page.get_parent())
    assert window is not None, page.get_parent()
    use(window)
    assert until(lambda: window.get_focus() is term), window.get_focus()
    assert toggles() == (True, True), toggles()

    # The console window is a console: Ctrl+Q and F1 are the program's there too.
    assert got(CONTROL, ord("q")) == "11"
    assert got(F1).startswith("1b")
    assert got(F9).startswith("1b")
    assert taken() == {}, taken()
    assert toggles() == (True, True), toggles()
    assert w.console_window_of(page.get_parent()) is window

elif scenario == "a-cleared-shortcut":
    # Preferences, with real keys. No console is open: a program in one would have the keys.
    prefs = app.Wconfig()
    pump(0.5)
    window = prefs.get_widget("wConfig")
    notebook = prefs.get_widget("nbConfig")
    # The page with the list of commands, shown first: GTK drops a key sent to a widget that
    # is not realized yet, with a critical.
    page = prefs.treeCmd
    while page.get_parent() is not notebook:
        page = page.get_parent()
    notebook.set_current_page(notebook.page_num(page))
    use(window)
    pump(0.5)

    def shortcut_of(command):
        return next(row[1] for row in prefs.treeModel if row[0] == command)

    def edit_and_type(command, *keysyms):
        """Start the editor on the command's Shortcut, as a click on it does, and press keys."""
        for number, row in enumerate(prefs.treeModel):
            if row[0] == command:
                path = Gtk.TreePath.new_from_indices([number])
                break
        else:
            raise AssertionError(command)
        prefs.treeCmd.set_cursor(path, prefs.treeCmd.get_column(1), True)
        pump(0.3)
        for keys in keysyms:
            press(*keys)

    assert shortcut_of("save") and shortcut_of("find"), "both start with a key"
    edit_and_type("save", (BACKSPACE,), (RETURN,))
    assert shortcut_of("save") == "", f"BackSpace left {shortcut_of('save')!r}"
    edit_and_type("find", (DELETE,), (RETURN,))
    assert shortcut_of("find") == "", f"Delete left {shortcut_of('find')!r}"
    # A key with Ctrl held binds, and a letter alone binds nothing and is not typed into the
    # name either.
    before = shortcut_of("clone")
    edit_and_type("clone", (ord("x"),), (RETURN,))
    assert shortcut_of("clone") == before, f"a letter left {shortcut_of('clone')!r}"
    edit_and_type("copy_all", (CONTROL, ord("j")), (RETURN,))
    assert shortcut_of("copy_all") == "CTRL+J", shortcut_of("copy_all")

    prefs.on_okbutton1_clicked(None)
    pump(0.5)
    kept = {command[0]: key for key, command in app.shortcuts.items() if isinstance(command, list)}
    assert "save" not in kept and "find" not in kept, kept
    assert kept["copy_all"] == "CTRL+J", kept
    assert "" not in app.shortcuts, "two commands without a key share the key ''"
    assert app.unbound_commands == {"save", "find"}, app.unbound_commands
    written = open(app.CONFIG_FILE).read()
    shortcuts_section = written.split("[shortcuts]", 1)[1].split("\n[", 1)[0]
    lines = [line.replace(" ", "") for line in shortcuts_section.splitlines()]
    assert "save=" in lines and "find=" in lines, shortcuts_section
    assert "copy_all=CTRL+J" in lines, shortcuts_section

    # Across a restart: neither comes back on its default.
    w.loadConfig()
    kept = {command[0]: key for key, command in app.shortcuts.items() if isinstance(command, list)}
    assert "save" not in kept and "find" not in kept, kept
    assert app.unbound_commands == {"save", "find"}, app.unbound_commands
    assert "CTRL+SHIFT+S" not in app.shortcuts or app.shortcuts["CTRL+SHIFT+S"] != ["save"]
    # And Preferences lists them, with nothing in the Shortcut column to give them one.
    again = app.Wconfig()
    pump(0.5)
    rows = {row[0]: row[1] for row in again.treeModel}
    assert rows["save"] == "" and rows["find"] == "", rows
    assert rows["copy_all"] == "CTRL+J", rows

else:
    raise SystemExit("no scenario " + scenario)
print("OK")
'''


@pytest.mark.skipif(shutil.which("Xvfb") is None, reason="needs Xvfb for a display of its own")
@pytest.mark.parametrize(
    "scenario",
    [
        "the-default-keys",
        "the-fixed-keys",
        "a-prefix-key",
        "a-hosts-prefix-key",
        "an-existing-configuration",
        "a-console-window",
        "an-ended-console",
        "a-cleared-shortcut",
    ],
)
def test_console_keys_against_real_gtk(scenario, tmp_path):
    pytest.importorskip("gi", reason="PyGObject not available")
    logger = tmp_path / "logger"
    logger.write_text(_LOGGER)
    logger.chmod(0o755)
    process, display = _private_display()
    environment = dict(os.environ, DISPLAY=display, GDK_BACKEND="x11")
    for name in ("WAYLAND_DISPLAY", "GDK_SCALE", "GDK_DPI_SCALE", "XDG_CONFIG_HOME"):
        environment.pop(name, None)
    try:
        result = subprocess.run(
            [sys.executable, "-c", _SCRIPT, scenario, str(tmp_path)],
            capture_output=True,
            text=True,
            cwd=REPO,
            env=environment,
            timeout=120,
        )
    finally:
        process.terminate()
        process.wait()

    assert result.returncode == 0, result.stderr[-3000:] + result.stdout[-1500:]
    assert "OK" in result.stdout
    # PyGObject prints what a signal handler raises, and carries on.
    assert "Traceback" not in result.stderr, result.stderr[-3000:]
    assert glib_complaints(result.stderr) == []
