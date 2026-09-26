"""Which tab a console action acts on (#219).

A shortcut acts on the tab in use: the one showing in the pane the keyboard is in. An
item in a tab's menu acts on the tab the menu was opened for. Two leftovers used to
decide instead. The tab menu's context outlived a dismissed menu, so the next paste or
Ctrl+W went to that tab. Clone, Reset and Reconnect by key read the label of the last
tab whose menu was opened, and raised before any had been.

Terminal shortcuts are also application accelerators, which GTK runs before the focused
terminal sees the key, so the scenarios call the application's action handlers: the
path a key takes. Each runs against real GTK and real terminals, in a process of its own.
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
from gi.repository import Gtk, Gdk, Vte
from gnome_connection_manager import app

app.conf.CONFIRM_ON_CLOSE_TAB = 0
app.conf.STARTUP_LOCAL = False  # only the tabs each scenario opens
app.wMain = w = app.Wmain(application=None)
# The accelerator path: the application's action handlers, as a key reaches them.
application = app.GcmApplication()
application._controller = w

def pump(seconds=0.2):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        Gtk.main_iteration_do(False)
        time.sleep(0.005)

def consoles(notebook):
    pages = (notebook.get_nth_page(i) for i in range(notebook.get_n_pages()))
    return [page for page in pages if hasattr(notebook.get_tab_label(page), "rename")]

def names():
    """Each pane's tabs, by the name of the host each one runs."""
    return [[page.get_children()[0].host.name for page in consoles(notebook)]
            for notebook in w.collect_notebooks(w.hpMain)]

def page_of(name):
    for notebook in w.collect_notebooks(w.hpMain):
        for page in consoles(notebook):
            if page.get_children()[0].host.name == name:
                return page

def open_tabs(*hosts):
    for name in hosts:
        w.addTab(w.nbConsole, app.Host("", name))
    pump(0.5)

def use(name):
    """Show the tab and put the keyboard in its terminal, as clicking the two does."""
    page = page_of(name)
    notebook = page.get_parent()
    notebook.set_current_page(notebook.page_num(page))
    w.wMain.set_focus(page.get_children()[0])
    pump()

def open_menu_of(name):
    """What right-clicking a tab does: NotebookTabLabel.popupmenu makes it the context.

    The menu is not shown. A popup grabs the pointer, the suite's windows share one X
    display, and under xdist another test's grab kept it from opening.
    """
    w.set_context_tab_widget(page_of(name))

def dismiss_menu():
    """Escape, or a click elsewhere: GTK hides the menu, emitting hide, and nothing is chosen."""
    w.popupMenuTab.emit("hide")
    pump()

def text(name):
    terminal = page_of(name).get_children()[0]
    row = terminal.get_cursor_position()[1]
    whole, _ = terminal.get_text_range_format(Vte.Format.TEXT, 0, 0, row, 10000)
    return whole or ""

if scenario == "clone-before-any-menu":
    open_tabs("A", "B", "C")
    use("B")
    application._on_action_console_clone(None, None)
    pump(0.5)
    assert names() == [["A", "B", "C", "B"]], names()

elif scenario == "paste-after-a-dismissed-menu":
    open_tabs("A", "B")
    open_menu_of("A")
    dismiss_menu()
    use("B")
    Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text("echo GCM-PASTED", -1)
    pump()
    application._on_action_paste(None, None)
    pump(0.5)
    assert "GCM-PASTED" in text("B"), text("B")
    assert "GCM-PASTED" not in text("A"), text("A")

elif scenario == "close-after-a-dismissed-menu":
    open_tabs("A", "B")
    open_menu_of("A")
    dismiss_menu()
    use("B")
    application._on_action_console_close(None, None)
    pump()
    assert names() == [["A"]], names()

elif scenario == "clone-after-a-dismissed-menu":
    open_tabs("A", "B", "C")
    open_menu_of("C")
    dismiss_menu()
    use("A")
    application._on_action_console_clone(None, None)
    pump(0.5)
    assert names() == [["A", "B", "C", "A"]], names()

elif scenario == "an-item-chosen-from-a-tab-menu":
    open_tabs("A", "B", "C")
    use("A")
    open_menu_of("C")
    # GTK hides a menu before the chosen item's action runs, so the action comes
    # straight after the hide, before the idle that forgets the context.
    w.popupMenuTab.emit("hide")
    application._on_action_console_clone(None, None)
    pump(0.5)
    assert names() == [["A", "B", "C", "C"]], names()
    assert w._context_tab_widget is None and w._context_terminal is None, "context kept"

elif scenario == "clone-in-the-second-pane":
    open_tabs("A", "B")
    use("B")
    w.on_tab_focus(page_of("B").get_children()[0])
    w.split_notebook(app.HSPLIT)
    pump()
    assert names() == [["A"], ["B"]], names()
    # A click into a terminal does not update w.current, which the split left on A.
    use("A")
    use("B")
    application._on_action_console_clone(None, None)
    pump(0.5)
    assert names() == [["A"], ["B", "B"]], names()

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
        "clone-before-any-menu",
        "paste-after-a-dismissed-menu",
        "close-after-a-dismissed-menu",
        "clone-after-a-dismissed-menu",
        "an-item-chosen-from-a-tab-menu",
        "clone-in-the-second-pane",
    ],
)
def test_a_console_action_acts_on_the_tab_meant_against_real_gtk(scenario):
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
