"""A tab that holds something other than a terminal (#223).

A VNC host's desktop is such a tab (#234), and web views and in-tab RDP will be. These
scenarios open a kind of page of their own through `add_page`, as those do, so that they
need neither gtk-vnc nor a server: a label, which cannot take the keyboard, or a drawing
area, which can. Measured with real X
input, clicking the tab of either leaves the keyboard on the notebook itself, and
`show` puts it there.

Before this, an action with such a tab in use went to the last terminal given the
keyboard, on a tab nobody was looking at: a paste went into it and Ctrl+W closed it.
Reset and Reconnect raised, and Clone opened a local shell. Each scenario runs against
real GTK and real terminals, in a process of its own, through the application's
action handlers: the path a key takes.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = r'''
import os, sys, tempfile, time
scenario = sys.argv[1]
os.environ["HOME"] = tempfile.mkdtemp(); sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk, Gdk, GLib, Vte
from gnome_connection_manager import app

app.conf.CONFIRM_ON_CLOSE_TAB = 0
app.conf.STARTUP_LOCAL = False  # only the tabs each scenario opens
app.wMain = w = app.Wmain(application=None)
application = app.GcmApplication()
application._controller = w

def pump(seconds=0.2):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        Gtk.main_iteration_do(False)
        time.sleep(0.005)

def tabs(notebook):
    pages = (notebook.get_nth_page(i) for i in range(notebook.get_n_pages()))
    return [page for page in pages if hasattr(notebook.get_tab_label(page), "rename")]

def title(page):
    return page.get_parent().get_tab_label(page).get_text().strip()

def names():
    """Each pane's tabs, by title."""
    return [[title(page) for page in tabs(notebook)] for notebook in w.collect_notebooks(w.hpMain)]

def page_of(name):
    for notebook in w.collect_notebooks(w.hpMain):
        for page in tabs(notebook):
            if title(page) == name:
                return page

def label_of(name):
    page = page_of(name)
    return page.get_parent().get_tab_label(page)

def terminal(name):
    return page_of(name).get_children()[0]

def open_tabs(*hosts):
    for name in hosts:
        w.addTab(w.nbConsole, app.Host("", name))
    pump(0.5)

def open_page(name, focusable=False, notebook=None):
    """A tab of a kind GCM does not have yet."""
    page = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
    inside = Gtk.DrawingArea() if focusable else Gtk.Label(label=name)
    inside.set_can_focus(focusable)
    page.pack_start(inside, True, True, 0)
    w.add_page(notebook or w.nbConsole, page, name)
    pump()
    return page

def use(name):
    """Show a terminal's tab and put the keyboard in it, as clicking the two does."""
    page = page_of(name)
    notebook = page.get_parent()
    notebook.set_current_page(notebook.page_num(page))
    w.wMain.set_focus(page.get_children()[0])
    pump()

def show(name):
    """Show a tab, leaving the keyboard on its notebook, as clicking the tab does."""
    page = page_of(name)
    notebook = page.get_parent()
    notebook.set_current_page(notebook.page_num(page))
    notebook.grab_focus()
    pump()

def split_off(name):
    """Split H with `name` in use, which moves it into a pane of its own."""
    use(name)
    application._on_action_split_horizontal(None, None)
    pump()

def text(name):
    v = terminal(name)
    row = v.get_cursor_position()[1]
    whole, _ = v.get_text_range_format(Vte.Format.TEXT, 0, 0, row, 10000)
    return whole or ""

def menu_items(name):
    """The tab menu's items shown for `name`'s tab, then the menu dismissed."""
    label_of(name).prepare_menu()
    shown = [item for item in ("mnuRename", "mnuReset", "mnuClear", "mnuReopen", "mnuClone",
                               "mnuLog", "mnuTranscript", "mnuSplitH", "mnuSplitV")
             if getattr(w.popupMenuTab, item).get_visible()]
    w.popupMenuTab.emit("hide")
    pump()
    return shown

if scenario == "terminal-actions-leave-the-other-tabs-alone":
    open_tabs("A")
    terminal("A").feed(b"ON-SCREEN\r\n")
    open_page("N")
    use("A")
    show("N")
    assert w.wMain.get_focus() == w.nbConsole, "the keyboard is not where a click leaves it"
    assert w.get_target_terminal() is None, w.get_target_terminal()
    opened = []
    for method in ("show_save_buffer", "show_buffer_viewer", "save_session_transcript"):
        setattr(w, method, lambda *args, method=method: opened.append(method))
    Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text("echo GCM-PASTED", -1)
    pump()
    scale = terminal("A").get_font_scale()
    for action in ("paste", "paste_single_line", "copy", "copy_paste", "select_all", "copy_all",
                   "zoom_in", "zoom_out", "zoom_reset", "view_buffer", "save_buffer",
                   "save_transcript", "console_reset", "console_reset_clear",
                   "console_reconnect", "console_clone"):
        getattr(application, "_on_action_" + action)(None, None)
        pump()
    application._on_action_console_log(None, GLib.Variant("b", True))
    app.snippets.append(app.snippetlib.Snippet("c0ffee00", "custom", "echo GCM-CUSTOM\r"))
    application._on_action_send_snippet(None, GLib.Variant("s", "c0ffee00"))
    w.on_guardar_como1_activate(None)
    w.get_widget("txtSearch").set_text("ON-SCREEN")
    w.on_btnSearch_clicked(None)
    pump(0.5)
    assert names() == [["A", "N"]], names()
    assert "GCM-PASTED" not in text("A") and "GCM-CUSTOM" not in text("A"), text("A")
    assert "ON-SCREEN" in text("A"), "A was reset"
    assert terminal("A").get_font_scale() == scale, "A was zoomed"
    assert not getattr(terminal("A"), "log_handler_id", 0), "A's log was turned on"
    assert opened == [], opened
    assert not getattr(w, "search", None), w.search

elif scenario == "ctrl-w-closes-it":
    open_tabs("A")
    open_page("N")
    use("A")
    show("N")
    application._on_action_console_close(None, None)
    pump()
    assert names() == [["A"]], names()

elif scenario == "split-moves-it":
    open_tabs("A")
    open_page("N")
    use("A")
    show("N")
    application._on_action_split_horizontal(None, None)
    pump()
    assert names() == [["A"], ["N"]], names()

elif scenario == "split-from-its-menu-moves-it":
    open_tabs("A", "B")
    open_page("N")
    use("A")
    label_of("N").prepare_menu()
    # GTK hides the menu before the chosen item's action runs.
    w.popupMenuTab.emit("hide")
    application._on_action_split_horizontal(None, None)
    pump()
    assert names() == [["A", "B"], ["N"]], names()

elif scenario == "rename-from-its-menu":
    open_tabs("A")
    open_page("N")
    use("A")
    app.inputbox = lambda *args, **kwargs: "renamed"
    label_of("N").prepare_menu()
    w.popupMenuTab.emit("hide")
    application._on_action_console_rename(None, None)
    pump()
    assert names() == [["A", "renamed"]], names()

elif scenario == "its-menu-offers-what-applies":
    open_tabs("A")
    open_page("N")
    assert menu_items("N") == ["mnuRename", "mnuSplitH", "mnuSplitV"], menu_items("N")
    everything = ["mnuRename", "mnuReset", "mnuClear", "mnuClone", "mnuLog", "mnuTranscript",
                  "mnuSplitH", "mnuSplitV"]
    assert menu_items("A") == everything, menu_items("A")

elif scenario == "the-open-console-list":
    open_tabs("A")
    open_page("N")
    open_page("F", focusable=True)
    def marked():
        return [e.text for _nb, entries in w.open_console_groups() for e in entries if e.current]
    use("A")
    show("N")
    assert marked() == ["N"], marked()
    use("A")
    assert marked() == ["A"], marked()
    w.focus_console(w.nbConsole, page_of("N"))
    pump()
    assert w.nbConsole.get_nth_page(w.nbConsole.get_current_page()) == page_of("N")
    assert w.wMain.get_focus() == w.nbConsole, w.wMain.get_focus()
    assert marked() == ["N"], marked()
    w.focus_console(w.nbConsole, page_of("F"))
    pump()
    assert w.wMain.get_focus() == page_of("F").get_children()[0], w.wMain.get_focus()
    assert marked() == ["F"], marked()

elif scenario == "the-cluster-window-leaves-it-out":
    open_tabs("A")
    open_page("N")
    listed = []
    class Cluster:
        def __init__(self, terms):
            listed.extend(title.strip() for title, _terminal in terms)
        def get_widget(self, _name):
            return Gtk.Window()
    app.Wcluster = Cluster
    w.on_btnCluster_clicked(None)
    assert listed == ["A"], listed

elif scenario == "the-pane-last-in-use-for-a-tab-without-a-terminal":
    open_tabs("A", "B")
    split_off("B")
    open_page("N", notebook=page_of("B").get_parent())
    show("N")
    use("A")
    show("N")
    w.treeServers.grab_focus()  # the keyboard leaves the consoles
    pump()
    application._on_action_console_close(None, None)
    pump()
    assert names() == [["A"], ["B"]], names()

elif scenario == "the-pane-last-in-use-after-a-click":
    open_tabs("A", "B")
    split_off("B")
    use("A")
    use("B")
    w.treeServers.grab_focus()
    pump()
    application._on_action_console_close(None, None)
    pump()
    assert names() == [["A"], []], names()

elif scenario == "preferences-with-it-open":
    open_tabs("A")
    open_page("N")
    w.apply_settings_to_open_consoles()
    pump()
    assert names() == [["A", "N"]], names()

else:
    raise SystemExit("no scenario " + scenario)
print("OK")
'''


@pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"),
    reason="needs a display for a real terminal",
)
@pytest.mark.parametrize(
    "scenario",
    [
        "terminal-actions-leave-the-other-tabs-alone",
        "ctrl-w-closes-it",
        "split-moves-it",
        "split-from-its-menu-moves-it",
        "rename-from-its-menu",
        "its-menu-offers-what-applies",
        "the-open-console-list",
        "the-cluster-window-leaves-it-out",
        "the-pane-last-in-use-for-a-tab-without-a-terminal",
        "the-pane-last-in-use-after-a-click",
        "preferences-with-it-open",
    ],
)
def test_a_tab_without_a_terminal_against_real_gtk(scenario):
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
