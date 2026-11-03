"""The status bar that gives a tab's whole title (#405).

Each scenario runs against real GTK and real terminals, in a process of its own.
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
os.environ["HOME"] = tempfile.mkdtemp(); sys.argv = ["gcm"]
os.environ["SHELL"] = "/bin/sh"; os.environ.pop("ENV", None)
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk, Gdk, GLib, Vte
from gnome_connection_manager import app

app.conf.CONFIRM_ON_CLOSE_TAB = 0
app.conf.STARTUP_LOCAL = False
app.conf.CHECK_UPDATES = False
app.wMain = w = app.Wmain(application=None)
application = app.GcmApplication()
application._controller = w
LONG = "a-host-with-a-name-far-longer-than-the-cut-the-tab-label-makes"

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

def page_of(name):
    for notebook in w.collect_notebooks(w.console_side()) + [x.notebook for x in w.console_windows]:
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

def bar_text(bar):
    return bar.get_message_area().get_children()[0].get_text()

def show(name):
    page = page_of(name)
    page.get_parent().set_current_page(page.get_parent().page_num(page))
    pump()

def split_off(name):
    show(name)
    w.wMain.set_focus(terminal(name))
    pump()
    application._on_action_split_horizontal(None, None)
    pump()

def hidden(bar):
    return not bar.get_visible()

if scenario == "default-off":
    assert app.conf.SHOW_STATUS_BAR is False
    open_tabs("one")
    assert hidden(w.status_bar)
    w.toggle_console_window(page_of("one")); pump()
    assert hidden(w.console_windows[0].status_bar)
elif scenario == "follows-the-tab":
    app.conf.SHOW_STATUS_BAR = True
    open_tabs(LONG, "short")
    w.apply_settings_to_open_consoles(); pump()
    show(LONG)
    assert w.status_bar.get_visible()
    assert bar_text(w.status_bar) == label_of(LONG).get_display_text().strip()
    assert len(bar_text(w.status_bar)) > 30
    show("short")
    assert bar_text(w.status_bar) == "short", bar_text(w.status_bar)
    show(LONG)
    assert bar_text(w.status_bar).startswith(LONG)
    terminal(LONG).feed(b"\x1b]0;T-from-program\x07"); pump()
    assert bar_text(w.status_bar).endswith("T-from-program"), bar_text(w.status_bar)
    label_of(LONG).rename("renamed-it")
    pump()
    assert bar_text(w.status_bar) == "renamed-it", bar_text(w.status_bar)
elif scenario == "follows-the-pane":
    app.conf.SHOW_STATUS_BAR = True
    app.conf.UPDATE_TITLE = 0
    open_tabs("first", "second")
    split_off("second")
    before = w.wMain.get_title()
    w.wMain.set_focus(terminal("first")); pump()
    assert bar_text(w.status_bar) == "first", bar_text(w.status_bar)
    w.wMain.set_focus(terminal("second")); pump()
    assert bar_text(w.status_bar) == "second", bar_text(w.status_bar)
    assert w.wMain.get_title() == before
elif scenario == "console-window":
    app.conf.SHOW_STATUS_BAR = True
    open_tabs("main-one", "moved")
    w.apply_settings_to_open_consoles()
    w.toggle_console_window(page_of("moved")); pump()
    window = w.console_windows[0]
    assert window.status_bar is not w.status_bar
    assert window.status_bar.get_visible()
    assert bar_text(window.status_bar) == "moved", bar_text(window.status_bar)
    show("main-one")
    assert bar_text(w.status_bar) == "main-one", bar_text(w.status_bar)
    assert bar_text(window.status_bar) == "moved"
elif scenario == "setting-off-and-on":
    w.apply_settings_to_open_consoles()  # no console open
    assert hidden(w.status_bar)
    app.conf.SHOW_STATUS_BAR = True
    w.apply_settings_to_open_consoles()
    assert w.status_bar.get_visible()
    open_tabs("one")
    w.toggle_console_window(page_of("one")); pump()
    window = w.console_windows[0]
    assert window.status_bar.get_visible()
    app.conf.SHOW_STATUS_BAR = False
    w.apply_settings_to_open_consoles()
    assert hidden(w.status_bar) and hidden(window.status_bar)
    app.conf.SHOW_STATUS_BAR = True
    w.apply_settings_to_open_consoles()
    assert w.status_bar.get_visible() and window.status_bar.get_visible()
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
        "default-off",
        "follows-the-tab",
        "follows-the-pane",
        "console-window",
        "setting-off-and-on",
    ],
)
def test_the_status_bar_against_real_gtk(scenario):
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
    assert "Traceback" not in result.stderr, result.stderr[-3000:]
