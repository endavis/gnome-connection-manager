"""A console moved to a window of its own, and back (#255).

Each scenario runs real GCM, started as GCM starts so that its shortcuts are the windows'
accelerators, with real terminals, on an Xvfb of its own. Its own, because these move the
keyboard between windows and press keys and drag tabs with real X input, through XTest:
on the display the other tests share, a key could reach another test's window, and their
windows could take the keyboard from these. XTest is reached through ctypes, so that
python-xlib need not be a dependency.

Measured with that input under X11 and no window manager: a window joined to the
application runs its shortcuts, presenting a window makes it active before the next key
arrives, and a tab dropped on the bare root window asks its notebook for a window with the
pointer's position.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.conftest import _free_display, _x_display_is_up
from tests.test_connections import glib_complaints

REPO = Path(__file__).resolve().parents[1]

_SCRIPT = r'''
import ctypes, faulthandler, os, sys, tempfile, time
faulthandler.dump_traceback_later(100, exit=True)
scenario, scratch = sys.argv[1], sys.argv[2]
os.environ["HOME"] = tempfile.mkdtemp(); os.environ["SHELL"] = "/bin/sh"; sys.argv = ["gcm"]
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
TITLE = app.conf.APP_TITLE

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

def tabs(notebook):
    pages = (notebook.get_nth_page(i) for i in range(notebook.get_n_pages()))
    return [page for page in pages if hasattr(notebook.get_tab_label(page), "rename")]

def title(page):
    return page.get_parent().get_tab_label(page).get_text().strip()

def names():
    """Each pane's tabs, and then each console window's, by title."""
    return [[title(page) for page in tabs(notebook)] for notebook in w.console_notebooks()]

def page_of(name):
    for notebook in w.console_notebooks():
        for page in tabs(notebook):
            if title(page) == name:
                return page

def label_of(name):
    page = page_of(name)
    return page.get_parent().get_tab_label(page)

def terminal(name):
    return page_of(name).get_children()[0]

def window_of(name):
    return w.console_window_of(page_of(name).get_parent())

def open_tabs(*hosts, log=False):
    for name in hosts:
        host = app.Host("", name)
        host.log = log
        w.addTab(w.nbConsole, host)
    pump(0.5)

def screen(name):
    v = terminal(name)
    row = v.get_cursor_position()[1]
    whole, _ = v.get_text_range_format(Vte.Format.TEXT, 0, 0, row, 10000)
    return whole or ""

def run(name, command, expect):
    """Type `command` into `name`'s shell and wait for `expect` on its screen."""
    app.vte_feed(terminal(name), command + "\r")
    assert until(lambda: expect in screen(name)), screen(name)

def use(window):
    window.present()
    assert until(window.is_active), window.get_title()

def split_off(name):
    """Split H with `name` in use, which moves it into a pane of its own."""
    page = page_of(name)
    page.get_parent().set_current_page(page.get_parent().page_num(page))
    w.wMain.set_focus(terminal(name))
    pump()
    application._on_action_split_horizontal(None, None)
    pump()

# Real input, through XTest, on the scenario's own display.
CONTROL, SHIFT, RETURN, ESCAPE, F11 = 0xFFE3, 0xFFE1, 0xFF0D, 0xFF1B, 0xFFC8
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
        xtst.XTestFakeButtonEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
        xtst.XTestFakeMotionEvent.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong
        ]
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

def point(x_, y_):
    x = xtest()
    x["xtst"].XTestFakeMotionEvent(x["display"], -1, int(x_), int(y_), 0)
    x["x11"].XFlush(x["display"])

def button(number, down):
    x = xtest()
    x["xtst"].XTestFakeButtonEvent(x["display"], number, down, 0)
    x["x11"].XFlush(x["display"])

def centre(widget):
    """Where `widget` is on the screen. A tab's text draws on its own event box's window.

    Aim at the text, not the middle of the tab: that is the close button's edge.
    """
    allocation = widget.get_allocation()
    _, x, y = widget.get_window().get_origin()
    return x + allocation.x + allocation.width // 2, y + allocation.y + allocation.height // 2

def drag(start, end):
    """Press at `start`, move to `end` in steps, as a hand does, and let go there."""
    point(*start)
    pump(0.1)
    button(1, True)
    pump(0.1)
    steps = 25
    for step in range(1, steps + 1):
        point(start[0] + (end[0] - start[0]) * step // steps,
              start[1] + (end[1] - start[1]) * step // steps)
        pump(0.03)
    pump(0.2)
    button(1, False)
    pump(0.8)

def terminal_menu(name):
    """Open `name`'s terminal menu by a real Ctrl+right-click, and report its Split items."""
    x = xtest()
    point(*centre(terminal(name)))
    pump(0.1)
    control = x["x11"].XKeysymToKeycode(x["display"], CONTROL)
    x["xtst"].XTestFakeKeyEvent(x["display"], control, True, 0)
    button(3, True)
    button(3, False)
    x["xtst"].XTestFakeKeyEvent(x["display"], control, False, 0)
    x["x11"].XFlush(x["display"])
    assert until(lambda: w.popupMenu.get_visible()), "the terminal's menu did not open"
    shown = (w.popupMenu.mnuSplitH.get_visible(), w.popupMenu.mnuSplitV.get_visible())
    w.popupMenu.popdown()
    pump()
    return shown

if scenario == "out-by-its-menu-and-back-by-its-key":
    app.conf.LOG_PATH = scratch
    open_tabs("A", "C")
    open_tabs("B", log=True)
    run("B", "KEPT=yes; echo ready", "ready")
    label, kept = label_of("B"), terminal("B")
    label.prepare_menu()
    item = w.popupMenuTab.mnuWindow
    assert item.get_visible() and item.get_label() == "Move to New Window", item.get_label()
    item.activate()
    w.popupMenuTab.emit("hide")
    pump(0.5)

    window = window_of("B")
    assert window is not None and window.get_visible(), names()
    assert names() == [["A", "C"], ["B"]], names()
    # The same tab, label and terminal, so the same session: its shell kept its variable.
    assert label_of("B") is label and terminal("B") is kept
    assert until(window.is_active)
    assert w.page_in_use() is page_of("B")
    assert window.get_focus() is kept, window.get_focus()
    assert window.get_title() == TITLE + " - B", window.get_title()
    run("B", "echo out-$KEPT", "out-yes")

    press(CONTROL, SHIFT, ord("m"))
    assert until(lambda: w.console_windows == ()), names()
    assert not window.get_visible()
    assert names() == [["A", "C", "B"]], names()
    assert label_of("B") is label and terminal("B") is kept
    assert until(w.wMain.is_active)
    assert w.page_in_use() is page_of("B")
    assert w.wMain.get_focus() is kept, w.wMain.get_focus()
    run("B", "echo back-$KEPT", "back-yes")
    # Its log went on through both moves.
    app.vte_feed(kept, "echo LOGGED-$KEPT\r")
    logs = [p for p in __import__("pathlib").Path(scratch).rglob("*.log")]
    assert until(lambda: any("LOGGED-yes" in p.read_text(errors="replace") for p in logs)), logs

elif scenario == "a-key-in-a-console-window-acts-on-its-tab":
    open_tabs("A", "B")
    run("B", "KEPT=yes; echo ready", "ready")
    w.toggle_console_window(page_of("B"))
    window = window_of("B")
    assert until(window.is_active)

    press(CONTROL, SHIFT, ord("d"))  # Clone
    assert until(lambda: names() == [["A"], ["B", "B"]]), names()
    press(CONTROL, ord("w"))  # Close console: the clone, which is in use there
    assert until(lambda: names() == [["A"], ["B"]]), names()
    press(CONTROL, SHIFT, ord("n"))  # New local console
    assert until(lambda: names() == [["A"], ["B", "local"]]), names()
    press(CONTROL, ord("w"))
    assert until(lambda: names() == [["A"], ["B"]]), names()

    # Find searches this window's tab, from a search box of its own.
    press(CONTROL, ord("f"))
    assert window.search_bar.get_search_mode()
    assert window.get_focus() is window.search_entry, window.get_focus()
    window.search_entry.set_text("KEPT")
    press(RETURN)
    assert w.search["terminal"] is terminal("B"), w.search
    press(ESCAPE)
    assert not window.search_bar.get_search_mode()
    assert until(lambda: window.get_focus() is terminal("B")), window.get_focus()

    # A key only the application has, which the terminal's own handler would not take.
    opened = []

    class Cluster:
        def __init__(self, terms):
            opened.append(terms)

        def get_widget(self, _name):
            return Gtk.Window()

    app.Wcluster = Cluster
    press(CONTROL, SHIFT, ord("u"))
    assert [term for _title, term in opened[0]] == [terminal("A"), terminal("B")], opened

    # F11 fills the screen with this window, not the main one.
    asked = []
    window.fullscreen = lambda: asked.append("fullscreen")
    press(F11)
    assert asked == ["fullscreen"], asked
    assert not w._current_fullscreen_state
    assert w.get_widget("toolbar1").get_visible()

    # Back in the main window, a key acts on the main window's tab.
    use(w.wMain)
    press(CONTROL, ord("w"))
    assert until(lambda: names() == [[], ["B"]]), names()
    run("B", "echo still-$KEPT", "still-yes")

elif scenario == "a-mark-flags-the-console-window":
    open_tabs("A", "B")
    w.toggle_console_window(page_of("B"))
    window = window_of("B")
    use(w.wMain)
    assert not w.is_watched(terminal("B"))
    app.vte_feed(terminal("B"), "printf '\\a'\r")
    assert until(lambda: label_of("B").needs_attention)
    assert window.get_urgency_hint() and not w.wMain.get_urgency_hint()

    use(window)
    assert not window.get_urgency_hint()
    assert w.is_watched(terminal("B"))
    app.vte_feed(terminal("A"), "printf '\\a'\r")
    assert until(lambda: label_of("A").needs_attention)
    assert w.wMain.get_urgency_hint() and not window.get_urgency_hint()

elif scenario == "closing-it-moves-its-consoles-back":
    open_tabs("A", "B", "C", "D")
    split_off("D")
    second = page_of("D").get_parent()
    w.wMain.set_focus(terminal("D"))  # the main window's pane in use is D's
    pump()
    w.toggle_console_window(page_of("B"))
    window = window_of("B")
    w.move_page(page_of("C"), window.notebook)
    window.notebook.set_current_page(1)
    run("B", "KEPT=b; echo ready", "ready")
    run("C", "KEPT=c; echo ready", "ready")
    ended = []
    w.session_ended = ended.append
    assert names() == [["A"], ["D"], ["B", "C"]], names()
    assert w.main_notebook() is second
    # One moved back by the command goes there too, and out again.
    w.toggle_console_window(page_of("B"))
    assert names() == [["A"], ["D", "B"], ["C"]], names()
    w.move_page(page_of("B"), window.notebook)
    window.notebook.set_current_page(0)
    pump()

    window.close()
    assert until(lambda: w.console_windows == ()), names()
    assert not window.get_visible()
    # Into the main window's pane in use, in their order, and none of them ended.
    assert names() == [["A"], ["D", "C", "B"]], names()
    assert ended == [], ended
    assert label_of("B").is_active and label_of("C").is_active
    assert until(w.wMain.is_active)
    assert w.page_in_use() is page_of("C")
    assert w.wMain.get_focus() is terminal("C"), w.wMain.get_focus()
    run("B", "echo back-$KEPT", "back-b")
    run("C", "echo back-$KEPT", "back-c")

elif scenario == "it-closes-when-its-last-tab-leaves":
    open_tabs("A", "B", "C")
    # Dropped into a pane: GTK's drag takes the page out and puts it in with its label.
    w.toggle_console_window(page_of("B"))
    window = window_of("B")
    page, label = page_of("B"), label_of("B")
    window.notebook.detach_tab(page)
    w.nbConsole.append_page(page, label)
    assert until(lambda: w.console_windows == ()), names()
    assert not window.get_visible()

    # Its close button.
    w.toggle_console_window(page_of("B"))
    window = window_of("B")
    label_of("B").close_tab(None)
    assert until(lambda: w.console_windows == ()), names()
    assert not window.get_visible()

    # Close console, which takes the page out another way.
    w.toggle_console_window(page_of("C"))
    window = window_of("C")
    assert until(window.is_active)
    application.activate_action("console-close", None)
    assert until(lambda: w.console_windows == ()), names()
    assert not window.get_visible()
    assert names() == [["A"]], names()

elif scenario == "every-window-is-reached":
    open_tabs("A", "B")
    w.toggle_console_window(page_of("B"))
    window = window_of("B")

    # The open-console list, chosen from the main window.
    use(w.wMain)
    menu = Gtk.Menu()
    w.build_console_menu(menu)
    rows = [item for item in menu.get_children() if not isinstance(item, Gtk.SeparatorMenuItem)]
    texts = [item.get_child().get_text() for item in rows]
    assert texts[0] == "Pane 1" and texts[2] == "Window 1", texts
    assert texts[1].endswith("A") and texts[3].endswith("B"), texts
    rows[3].activate()
    assert until(window.is_active)
    assert w.window_in_use is window
    assert window.get_focus() is terminal("B"), window.get_focus()

    # The cluster window.
    opened = []

    class Cluster:
        def __init__(self, terms):
            opened.append(terms)

        def get_widget(self, _name):
            return Gtk.Window()

    app.Wcluster = Cluster
    w.on_btnCluster_clicked(None)
    assert [term for _title, term in opened[0]] == [terminal("A"), terminal("B")], opened

    # Preferences.
    app.conf.BUFFER_LINES = 4321
    w.apply_settings_to_open_consoles()
    assert terminal("B").get_scrollback_lines() == 4321

    # Quitting: the question counts every window's consoles, and every session ends.
    asked = []
    app.msgconfirm = lambda text: asked.append(text) or Gtk.ResponseType.CANCEL
    app.conf.CONFIRM_ON_EXIT = True
    assert w.on_wMain_delete_event(w.wMain) is True
    assert " 2 " in asked[0], asked
    ended = []
    w.session_ended = ended.append
    w.end_sessions()
    assert ended == [terminal("A"), terminal("B")], ended
    ended.clear()
    kept = terminal("B")
    # Closing the main window quits, and ends the console window's session with it.
    w.wMain.destroy()
    assert until(lambda: kept in ended), ended
    assert not window.get_visible()

elif scenario == "no-splits-in-a-console-window":
    open_tabs("A", "B", "C", "D")
    w.toggle_console_window(page_of("B"))
    window = window_of("B")
    w.move_page(page_of("C"), window.notebook)
    pump()

    label_of("B").prepare_menu()
    menu = w.popupMenuTab
    assert not menu.mnuSplitH.get_visible() and not menu.mnuSplitV.get_visible()
    assert menu.mnuWindow.get_label() == "Move to Main Window", menu.mnuWindow.get_label()
    # Split, asked for anyway, does nothing there.
    application.activate_action("split-horizontal", None)
    menu.emit("hide")
    pump()
    assert window.notebook.get_parent().get_parent() is window
    assert names() == [["A", "D"], ["B", "C"]], names()

    label_of("A").prepare_menu()
    assert menu.mnuSplitH.get_visible() and menu.mnuSplitV.get_visible()
    assert menu.mnuWindow.get_label() == "Move to New Window", menu.mnuWindow.get_label()
    menu.emit("hide")
    pump()

    use(window)
    assert terminal_menu("B") == (False, False)
    use(w.wMain)
    assert terminal_menu("A") == (True, True)

    # A double-click on its tab strip, past the last tab, opens a local console there.
    use(window)
    last = label_of("C")
    _, x, y = last.get_window().get_origin()
    allocation = last.get_allocation()
    point(x + allocation.x + allocation.width + 60, y + allocation.y + allocation.height // 2)
    pump(0.1)
    for _click in range(2):
        button(1, True)
        button(1, False)
    assert until(lambda: names()[-1] == ["B", "C", "local"]), names()
    w.toggle_console_window(page_of("local"))
    assert until(lambda: names()[-1] == ["B", "C"]), names()

    # Its open-console button opens the list, there.
    use(window)
    point(*centre(window.notebook.get_action_widget(Gtk.PackType.END)))
    pump(0.1)
    button(1, True)
    button(1, False)

    def shown_menu():
        for top in Gtk.Window.list_toplevels():
            child = top.get_child() if top.get_mapped() else None
            if isinstance(child, Gtk.Menu):
                return child

    assert until(lambda: shown_menu() is not None), "the open-console list did not open"
    texts = [item.get_child().get_text() for item in shown_menu().get_children()
             if not isinstance(item, Gtk.SeparatorMenuItem)]
    assert "Window 1" in texts, texts
    press(ESCAPE)
    assert until(lambda: shown_menu() is None)

    # Its title is its tab's, Dynamic title or not.
    assert not app.conf.UPDATE_TITLE
    window.notebook.set_current_page(window.notebook.page_num(page_of("B")))
    assert window.get_title() == TITLE + " - B", window.get_title()
    window.notebook.set_current_page(window.notebook.page_num(page_of("C")))
    assert window.get_title() == TITLE + " - C", window.get_title()
    assert w.wMain.get_title() == TITLE, w.wMain.get_title()

elif scenario == "a-tab-dropped-outside-every-notebook":
    open_tabs("A", "B")
    run("B", "KEPT=yes; echo ready", "ready")
    label, kept = label_of("B"), terminal("B")
    drag(centre(label.label), (1500, 850))
    window = window_of("B")
    assert window is not None, names()
    assert names() == [["A"], ["B"]], names()
    assert label_of("B") is label and terminal("B") is kept
    assert window.get_position() == (1500, 850), window.get_position()
    assert until(window.is_active)
    assert until(lambda: window.get_focus() is kept), window.get_focus()
    run("B", "echo out-$KEPT", "out-yes")

    # Out of that window onto the desktop again: a window of its own once more, and the
    # one it left, now empty, closes.
    drag(centre(label_of("B").label), (1200, 200))
    second = window_of("B")
    assert second is not None and second is not window, names()
    assert until(lambda: w.console_windows == (second,)), names()
    assert not window.get_visible()
    assert second.get_position() == (1200, 200), second.get_position()
    window = second

    # And back, dropped on the main window's tab strip.
    drag(centre(label_of("B").label), centre(label_of("A").label))
    assert until(lambda: w.console_windows == ()), names()
    assert not window.get_visible()
    assert sorted(names()[0]) == ["A", "B"], names()
    assert label_of("B") is label and terminal("B") is kept
    run("B", "echo back-$KEPT", "back-yes")

else:
    raise SystemExit("no scenario " + scenario)
print("OK")
'''


def _private_display():
    """An Xvfb of the scenario's own, as (process, display).

    The number is chosen free and then bound, and two workers can choose the same one.
    The one that loses sees the other's server come up, and its own exits only once it
    finds the lock taken, which under load took longer than the wait meant for it. Two
    scenarios then shared a display: each one's keys reached the other's windows, and
    the first to finish took the server down under the other, which exited with status
    1 and no word why. So a display counts as its own only once the lock file Xvfb
    writes names its own process.
    """
    for _attempt in range(10):
        number = _free_display()
        if number is None:
            break
        process = subprocess.Popen(
            ["Xvfb", f":{number}", "-screen", "0", "1920x1080x24", "-nolisten", "tcp"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        lock = Path(f"/tmp/.X{number}-lock")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and process.poll() is None:
            if _x_display_is_up(number) and _holder(lock) == process.pid:
                return process, f":{number}"
            time.sleep(0.02)
        process.kill()
        process.wait()
    pytest.fail("no Xvfb of its own came up")


def _holder(lock):
    """The process a display's lock file names, or None while it names none yet."""
    try:
        return int(lock.read_text().strip())
    except (OSError, ValueError):
        return None


@pytest.mark.skipif(shutil.which("Xvfb") is None, reason="needs Xvfb for a display of its own")
@pytest.mark.parametrize(
    "scenario",
    [
        "out-by-its-menu-and-back-by-its-key",
        "a-key-in-a-console-window-acts-on-its-tab",
        "a-mark-flags-the-console-window",
        "closing-it-moves-its-consoles-back",
        "it-closes-when-its-last-tab-leaves",
        "every-window-is-reached",
        "no-splits-in-a-console-window",
        "a-tab-dropped-outside-every-notebook",
    ],
)
def test_a_console_window_against_real_gtk(scenario, tmp_path):
    pytest.importorskip("gi", reason="PyGObject not available")
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

    assert result.returncode == 0, result.stderr[-3000:]
    assert "OK" in result.stdout
    # PyGObject prints what a signal handler raises, and carries on.
    assert "Traceback" not in result.stderr, result.stderr[-3000:]
    assert glib_complaints(result.stderr) == []
