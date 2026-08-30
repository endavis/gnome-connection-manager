"""Dialogs must stay inside the monitor, OK/Cancel included (#82)."""

from __future__ import annotations

import os
import subprocess
import sys
import types
from pathlib import Path

import pytest


def workarea(width: int, height: int, x: int = 0, y: int = 0):
    return types.SimpleNamespace(x=x, y=y, width=width, height=height)


class WindowStub:
    """Only what onscreen_position asks of a window."""

    def __init__(self, x: int, y: int):
        self.position = (x, y)

    def get_position(self):
        return self.position


def test_clamp_leaves_a_size_that_already_fits(app_module):
    assert app_module.clamp_to_workarea(400, 300, workarea(1920, 1080)) == (400, 300)


def test_clamp_shrinks_a_size_larger_than_the_screen(app_module):
    """The preferences dialog asks for 1017px of height on a 960px screen."""
    assert app_module.clamp_to_workarea(561, 1017, workarea(1440, 960)) == (561, 960)


def test_clamp_keeps_room_for_the_window_frame(app_module):
    allowance = app_module.WINDOW_FRAME_ALLOWANCE
    assert app_module.clamp_to_workarea(561, 1017, workarea(1440, 960), allowance) == (
        561,
        960 - allowance,
    )


def test_clamp_never_returns_a_size_below_one_pixel(app_module):
    """A work area smaller than the allowance must not produce a zero or negative size."""
    assert app_module.clamp_to_workarea(500, 500, workarea(40, 40), 200) == (1, 1)


def test_clamp_passes_the_size_through_without_a_work_area(app_module):
    assert app_module.clamp_to_workarea(900, 600, None) == (900, 600)


def test_a_window_that_fits_is_left_where_it_is(app_module):
    assert app_module.onscreen_position(WindowStub(100, 100), workarea(1440, 960), 400, 300) is None


def test_a_window_hanging_off_the_bottom_is_moved_up(app_module):
    """The dialog is placed while empty, then grows downward past the screen edge."""
    placed = app_module.onscreen_position(WindowStub(556, 307), workarea(1440, 960), 473, 863)
    assert placed is not None
    _, y = placed
    assert y + 863 + app_module.WINDOW_FRAME_ALLOWANCE <= 960


def test_a_window_the_manager_has_not_placed_yet_is_left_alone(app_module):
    """GTK reports a sentinel until placement; it places the window at its final size."""
    unplaced = WindowStub(-32768, -32768)
    assert app_module.onscreen_position(unplaced, workarea(1440, 960), 473, 863) is None


def test_a_window_is_never_pushed_off_the_top_to_fit(app_module):
    """A window taller than the screen still has to start inside it."""
    placed = app_module.onscreen_position(WindowStub(0, 500), workarea(1440, 960), 400, 2000)
    assert placed == (0, 0)


# conftest stubs gi for the whole session, so the dialog cannot be built in process.
# This runs in a clean interpreter, the only way to size a real GtkDialog. The work
# area is faked small so the assertions mean the same thing on any monitor.
_FIT_SCRIPT = """
import os, sys, tempfile, time
os.environ["HOME"] = tempfile.mkdtemp(); sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk, Gdk, GLib
from gnome_connection_manager import app

SCREEN_W, SCREEN_H = 1024, 600
real_workarea = app.monitor_workarea
def small(window=None):
    area = real_workarea(window)
    if area is None:
        sys.exit("no monitor")
    area.x = area.y = 0
    area.width, area.height = SCREEN_W, SCREEN_H
    return area
app.monitor_workarea = small

def settle(seconds=2.0):
    # Not Gtk.main(): an assertion raised inside a callback there would be printed
    # and swallowed, and the script would hang instead of failing.
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        Gtk.main_iteration_do(False)
        time.sleep(0.005)

def in_a_scroller(widget):
    parent = widget.get_parent()
    while parent is not None:
        if isinstance(parent, Gtk.ScrolledWindow):
            return True
        parent = parent.get_parent()
    return False

def buttons(widget, found):
    if isinstance(widget, Gtk.Button) and (widget.get_label() or "") in ("OK", "Cancel"):
        found.append(widget)
    if isinstance(widget, Gtk.Container):
        for child in widget.get_children():
            buttons(child, found)
    return found

app.wMain = app.Wmain(application=None)
config = app.Wconfig()
settle()
window = config.get_widget("wConfig")

minimum = window.get_preferred_height()[0]
assert minimum <= SCREEN_H, "the dialog cannot be resized to fit: minimum is %d" % minimum
assert window.get_size()[1] <= SCREEN_H, "opened taller than the screen: %r" % (window.get_size(),)

row = buttons(window, [])
assert len(row) == 2, "expected OK and Cancel, got %r" % [b.get_label() for b in row]
for button in row:
    assert not in_a_scroller(button), "%s scrolls away with the content" % button.get_label()

table = config.get_widget("tblGeneral")
assert in_a_scroller(table), "the options cannot be reached: the page does not scroll"

window.destroy()
print("OK")
"""


@pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"),
    reason="needs a display for a real window",
)
def test_preferences_dialog_fits_a_small_monitor_against_real_gtk():
    """tblGeneral grows a row per option, past the screen, hiding OK and Cancel."""
    pytest.importorskip("gi", reason="PyGObject not available")
    result = subprocess.run(
        [sys.executable, "-c", _FIT_SCRIPT],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        timeout=90,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert "OK" in result.stdout


# The end-to-end check on whatever monitor is actually attached: where the button
# row lands on screen, which is what "I can't see the ok or cancel buttons" means.
_ONSCREEN_SCRIPT = """
import os, sys, tempfile, time
os.environ["HOME"] = tempfile.mkdtemp(); sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk, Gdk, GLib
from gnome_connection_manager import app

def settle(seconds=2.0):
    # Not Gtk.main(): an assertion raised inside a callback there would be printed
    # and swallowed, and the script would hang instead of failing.
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        Gtk.main_iteration_do(False)
        time.sleep(0.005)

def buttons(widget, found):
    if isinstance(widget, Gtk.Button) and (widget.get_label() or "") in ("OK", "Cancel"):
        found.append(widget)
    if isinstance(widget, Gtk.Container):
        for child in widget.get_children():
            buttons(child, found)
    return found

app.wMain = app.Wmain(application=None)
area = app.monitor_workarea()
config = app.Wconfig()
settle()
window = config.get_widget("wConfig")
surface = window.get_window()

for button in buttons(window, []):
    allocation = button.get_allocation()
    _, bottom = surface.get_root_coords(allocation.x, allocation.y + allocation.height)
    assert bottom <= area.y + area.height, (
        "%s reaches y=%d, the work area ends at %d"
        % (button.get_label(), bottom, area.y + area.height)
    )

window.destroy()
print("OK")
"""


@pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"),
    reason="needs a display for a real window",
)
@pytest.mark.parametrize("backend", ["", "x11"])
def test_preferences_buttons_land_on_screen_against_real_gtk(backend):
    """Under X11 the dialog keeps the place it was given while empty, and has to be
    moved back; a compositor places it itself. Both routes have to end on screen."""
    pytest.importorskip("gi", reason="PyGObject not available")
    if backend == "x11" and not os.environ.get("DISPLAY"):
        pytest.skip("no X server or Xwayland to talk to")
    environment = dict(os.environ)
    if backend:
        environment["GDK_BACKEND"] = backend
    result = subprocess.run(
        [sys.executable, "-c", _ONSCREEN_SCRIPT],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        timeout=90,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert "OK" in result.stdout


# Where the window manager leaves a dialog is its own business and varies with
# timing, so put one in the bad place deliberately: X11 keeps the position the
# dialog was given while it was still empty, which is how the button row ends up
# below the screen once new() has grown it. move() is an X11 lever only -- a
# Wayland compositor places its own windows and needs no rescue.
_REPLACE_SCRIPT = """
import os, sys, tempfile, time
os.environ["HOME"] = tempfile.mkdtemp(); sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk, Gdk, GLib
from gnome_connection_manager import app

def settle(seconds=2.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        Gtk.main_iteration_do(False)
        time.sleep(0.005)

def lowest_button(window):
    found = []
    def walk(widget):
        if isinstance(widget, Gtk.Button) and (widget.get_label() or "") in ("OK", "Cancel"):
            allocation = widget.get_allocation()
            found.append(window.get_window().get_root_coords(
                allocation.x, allocation.y + allocation.height)[1])
        if isinstance(widget, Gtk.Container):
            for child in widget.get_children():
                walk(child)
    walk(window)
    assert found, "no OK or Cancel button in the dialog"
    return max(found)

app.wMain = app.Wmain(application=None)
area = app.monitor_workarea()
bottom = area.y + area.height
config = app.Wconfig()
settle()
window = config.get_widget("wConfig")

window.move(area.x, bottom - 100)
settle(1.0)
assert lowest_button(window) > bottom, (
    "could not stage the fault: the buttons are still on screen at y=%d" % lowest_button(window))

app.fit_window_to_monitor(window)
settle(1.0)
assert lowest_button(window) <= bottom, (
    "the buttons were left off screen at y=%d, the work area ends at %d"
    % (lowest_button(window), bottom))

window.destroy()
print("OK")
"""


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="needs an X server or Xwayland")
def test_a_dialog_left_below_the_screen_is_brought_back_against_real_gtk():
    pytest.importorskip("gi", reason="PyGObject not available")
    result = subprocess.run(
        [sys.executable, "-c", _REPLACE_SCRIPT],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "GDK_BACKEND": "x11"},
        timeout=90,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert "OK" in result.stdout


# -- wrapping the pages must not move the selected tab (#89) ------------------

# Same shape as the script above: a real GtkNotebook is the only thing that shows
# this, because remove_page() moving the selection is GTK's behaviour, not ours.
_TAB_SCRIPT = """
import os, sys, tempfile, time
os.environ["HOME"] = tempfile.mkdtemp(); sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk
from gnome_connection_manager import app

real_workarea = app.monitor_workarea
def small(window=None):
    area = real_workarea(window)
    if area is None:
        sys.exit("no monitor")
    area.x = area.y = 0
    area.width, area.height = 1024, 600
    return area
app.monitor_workarea = small

def settle(seconds=1.5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        Gtk.main_iteration_do(False)
        time.sleep(0.005)

def notebook_of(component):
    return [w for w in component.get_widgets() if isinstance(w, Gtk.Notebook)][0]

def labels(nb):
    return [nb.get_tab_label_text(nb.get_nth_page(i)) for i in range(nb.get_n_pages())]

app.wMain = app.Wmain(application=None)
settle()

# The dialog has already been through fit_window_to_monitor by the time this runs:
# its constructor queues that on idle and settle() has run it, so this is the state
# the user is actually shown rather than a reconstruction of it.
def check(name, component, window_id, expected_first):
    nb = notebook_of(component)
    tabs = labels(nb)
    assert tabs[0] == expected_first, "%s: first tab is %r" % (name, tabs[0])
    scrolled = [i for i in range(nb.get_n_pages())
                if isinstance(nb.get_nth_page(i), Gtk.ScrolledWindow)]
    assert scrolled, "%s: no page was wrapped, so this proves nothing" % name
    current = nb.get_current_page()
    assert current == 0, "%s: opened on %r, not %r" % (name, tabs[current], expected_first)
    component.get_widget(window_id).destroy()

config = app.Wconfig()
settle()
check("Settings", config, "wConfig", "General")

host = app.Host("g", "n", "", "example.test", "u", "", "", "22", "", "ssh")
# Host defaults some fields to ints; init() feeds them straight to set_text().
host.keep_alive = "0"
host.commands = ""
host.font_color = host.back_color = ""
host.term = ""
edit = app.Whost()
edit.init("g", host)
settle()
check("Edit Host", edit, "wHost", "Properties")

print("TABS-OK")
"""


@pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"),
    reason="needs a display for a real window",
)
def test_wrapping_pages_leaves_the_selected_tab_alone_against_real_gtk():
    """Making a dialog scrollable must not change which tab it opens on.

    Wrapping removes and reinserts every page, and GTK moves the selection off a
    page it removes -- so down a whole notebook the selection walks past the first
    tab and the second. Edit Host opened on Commands and Settings on Shortcuts,
    never on the tab between them, and only on a screen small enough to trigger the
    wrapping at all (#89).
    """
    pytest.importorskip("gi", reason="PyGObject not available")
    result = subprocess.run(
        [sys.executable, "-c", _TAB_SCRIPT],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        timeout=90,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert "TABS-OK" in result.stdout


# -- the dialog must be measured against the monitor it is really on (#94) ----


class MonitorStub:
    def __init__(self, x, y, width, height):
        self.rect = workarea(width, height, x, y)

    def get_geometry(self):
        return self.rect

    def get_workarea(self):
        return self.rect


class DisplayStub:
    def __init__(self, *monitors):
        self.monitors = list(monitors)

    def get_n_monitors(self):
        return len(self.monitors)

    def get_monitor(self, index):
        return self.monitors[index]


class PlacedWindow:
    """Only what monitor_showing asks of a window."""

    def __init__(self, x, y, width=800, height=600, realised=True):
        self.position = (x, y)
        self.size = (width, height)
        self.realised = realised

    def get_window(self):
        return object() if self.realised else None

    def get_position(self):
        return self.position

    def get_size(self):
        return self.size


def test_overlap_of_two_rectangles(app_module):
    assert app_module.overlap_area((0, 0, 100, 100), (50, 50, 100, 100)) == 2500


def test_rectangles_that_only_touch_do_not_overlap(app_module):
    assert app_module.overlap_area((0, 0, 100, 100), (100, 0, 100, 100)) == 0


def test_rectangles_apart_do_not_overlap(app_module):
    assert app_module.overlap_area((0, 0, 10, 10), (500, 500, 10, 10)) == 0


def test_the_monitor_showing_a_window_is_the_one_holding_most_of_it(app_module):
    left = MonitorStub(0, 0, 1000, 1000)
    right = MonitorStub(1000, 0, 1000, 1000)
    display = DisplayStub(left, right)

    # 900 of its 1000 px sit on the right-hand monitor
    window = PlacedWindow(900, 0, width=1000, height=500)

    assert app_module.monitor_showing(display, window) is right


def test_a_window_touching_no_monitor_is_on_none_of_them(app_module):
    """GDK answers this case with its *first* monitor, which is what caused #94.

    The main window sits at (0, 0) on a display whose monitors start at y = 3, so
    it overlaps nothing -- and the arbitrary answer was a screen the application
    was not on, 2880x1920 at (606, 1083).
    """
    display = DisplayStub(MonitorStub(606, 1083, 2880, 1920), MonitorStub(0, 3, 1920, 1080))

    assert app_module.monitor_showing(display, PlacedWindow(-40000, -40000)) is None


def test_a_window_the_manager_has_not_placed_is_on_no_monitor(app_module):
    display = DisplayStub(MonitorStub(0, 0, 1920, 1080))
    unplaced = PlacedWindow(app_module.UNPLACED_WINDOW_COORD, 0)

    assert app_module.monitor_showing(display, unplaced) is None


def test_an_unrealised_window_is_on_no_monitor(app_module):
    display = DisplayStub(MonitorStub(0, 0, 1920, 1080))

    assert app_module.monitor_showing(display, PlacedWindow(10, 10, realised=False)) is None


def test_monitor_showing_nothing_is_on_no_monitor(app_module):
    assert app_module.monitor_showing(DisplayStub(MonitorStub(0, 0, 800, 600)), None) is None


def test_a_dialog_falls_back_to_the_monitor_its_parent_is_on(app_module, monkeypatch):
    """A dialog is measured on the idle after it is shown, often before placement.

    Guessing at that point picked an arbitrary screen. The dialog opens on its
    parent's monitor, and the parent is placed, so that is the answer to use.
    """
    wrong = MonitorStub(606, 1083, 2880, 1920)
    right = MonitorStub(0, 3, 1920, 1080)
    display = DisplayStub(wrong, right)
    parent = PlacedWindow(20, 20, width=900, height=600)
    dialog = PlacedWindow(0, 0, realised=False)
    dialog.get_transient_for = lambda: parent

    monkeypatch.setattr(app_module.Gdk.Display, "get_default", staticmethod(lambda: display))
    display.get_primary_monitor = lambda: None

    assert app_module.monitor_workarea(dialog) is right.rect


# The checks above fake the work area small, which is what makes them repeatable --
# but it also means they never exercise *which* monitor is chosen, and that is where
# #94 lived. This one deliberately uses the real display.
_REAL_MONITOR_SCRIPT = """
import os, sys, tempfile, time
os.environ["HOME"] = tempfile.mkdtemp(); sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91"); gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk
from gnome_connection_manager import app

def settle(seconds=2.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        Gtk.main_iteration_do(False)
        time.sleep(0.005)

app.wMain = app.Wmain(application=None)
settle()
config = app.Wconfig()
settle()
window = config.get_widget("wConfig")

width, height = window.get_size()
x, y = window.get_position()

# the monitor the dialog is really on, worked out from its own rectangle
display = Gdk.Display.get_default()
best, best_area = None, 0
for index in range(display.get_n_monitors()):
    g = display.get_monitor(index).get_geometry()
    area = app.overlap_area((x, y, width, height), (g.x, g.y, g.width, g.height))
    if area > best_area:
        best, best_area = g, area
assert best is not None, "the dialog is on no monitor at all: %r" % ((x, y, width, height),)

assert height <= best.height, (
    "dialog is %dpx tall on a %dpx screen -- measured against the wrong monitor"
    % (height, best.height))
assert width <= best.width, "dialog is %dpx wide on a %dpx screen" % (width, best.width)
assert y + height <= best.y + best.height, (
    "the dialog runs %dpx past the bottom of its screen"
    % (y + height - best.y - best.height))

window.destroy()
print("REAL-MONITOR-OK")
"""


@pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"),
    reason="needs a display for a real window",
)
def test_the_dialog_fits_the_monitor_it_is_really_on():
    """Against the attached display, with nothing faked.

    `Gdk.Display.get_monitor_at_window` cannot report "no monitor" -- it answers
    with its first one -- so a dialog that is not placed yet, or a main window at
    (0, 0) on a display whose monitors start at y = 3, was measured against
    whichever monitor happened to be first. Measured before the fix, on three
    monitors with no primary set: the preferences dialog opened 1617px tall on a
    1080px screen, with OK and Cancel 633px below the bottom edge (#94).
    """
    pytest.importorskip("gi", reason="PyGObject not available")
    result = subprocess.run(
        [sys.executable, "-c", _REAL_MONITOR_SCRIPT],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        timeout=90,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert "REAL-MONITOR-OK" in result.stdout
