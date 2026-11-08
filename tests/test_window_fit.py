"""Dialogs must stay inside the monitor, OK/Cancel included (#82)."""

from __future__ import annotations

import os
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from tests.test_connections import glib_complaints


def workarea(width: int, height: int, x: int = 0, y: int = 0):
    return types.SimpleNamespace(x=x, y=y, width=width, height=height)


class WindowStub:
    """Only what onscreen_position asks of a window."""

    def __init__(self, x: int, y: int, scale: int = 1):
        self.position = (x, y)
        self.scale = scale

    def get_position(self):
        return self.position

    def get_scale_factor(self):
        return self.scale


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


def test_the_sentinel_is_the_sentinel_divided_by_the_scale(app_module):
    """At scale 2 the sentinel is -16384, which a threshold of -30000 does not catch (#552)."""
    unplaced = WindowStub(-16384, -16384, scale=2)
    assert app_module.onscreen_position(unplaced, workarea(720, 480), 236, 300) is None


def test_a_window_placed_at_scale_two_hanging_off_the_bottom_is_moved_up(app_module):
    """The scale only moves the threshold: a placed window is still fitted."""
    placed = app_module.onscreen_position(
        WindowStub(278, 300, scale=2), workarea(720, 480), 236, 300
    )
    assert placed is not None
    _, y = placed
    assert y + 300 + app_module.WINDOW_FRAME_ALLOWANCE <= 480


def test_a_window_is_never_pushed_off_the_top_to_fit(app_module):
    """A window taller than the screen still has to start inside it."""
    placed = app_module.onscreen_position(WindowStub(0, 500), workarea(1440, 960), 400, 2000)
    assert placed == (0, 0)


# -- the fit waits for the window manager to report the placement (#552) -------


class GdkWindowStub:
    """Only what placement_reported asks of a window's GdkWindow."""

    def __init__(self, x: int, y: int):
        self.origin = (x, y)

    def get_origin(self):
        # PyGObject gives (ret, x, y)
        return (1, *self.origin)


class DialogStub:
    """What fit_when_placed and show_dialog ask of a dialog.

    Its signal handling is GObject's: a handler is disconnected once, and a destroyed
    window has lost every one. `deliver` is the stub's own, a `configure-event` sent to
    the handlers still connected. Every other name here is held against the real
    Gtk.Window by `test_the_stubs_match_real_gtk`.
    """

    GTK_NAMES = (
        "connect",
        "disconnect",
        "handler_is_connected",
        "get_window",
        "get_display",
        "show",
        "present",
        "destroy",
    )

    def __init__(self, origin: tuple[int, int] = (894, 864), wayland: bool = False):
        self.gdk_window: GdkWindowStub | None = GdkWindowStub(*origin)
        self.origin = origin
        self.wayland = wayland
        self.handlers: dict[int, tuple[str, Any]] = {}
        self.calls: list[str] = []
        self.last_handler = 0

    def connect(self, signal, callback):
        self.calls.append(f"connect {signal}")
        self.last_handler += 1
        self.handlers[self.last_handler] = (signal, callback)
        return self.last_handler

    def disconnect(self, handler_id):
        self.calls.append("disconnect")
        del self.handlers[handler_id]  # GObject warns about a handler that is not there

    def handler_is_connected(self, handler_id):
        return handler_id in self.handlers

    def get_window(self):
        return self.gdk_window

    def get_display(self):
        name = "GdkWaylandDisplay" if self.wayland else "GdkX11Display"
        return types.SimpleNamespace(__gtype__=types.SimpleNamespace(name=name))

    def show(self):
        self.calls.append("show")

    def present(self):
        self.calls.append("present")

    def destroy(self):
        self.calls.append("destroy")
        self.handlers.clear()

    def deliver(self, event):
        for handler_id in list(self.handlers):
            if self.handler_is_connected(handler_id):
                signal, callback = self.handlers[handler_id]
                if signal == "configure-event":
                    callback(self, event)


class SourcesStub:
    """GLib's idles and timers as the code under test asked for them, recorded and not run.

    A source removed twice, or after its callback finished, raises here: GLib reports
    that as a critical, which a real-GTK scenario's stderr would show.
    """

    def __init__(self) -> None:
        self.idles: list[tuple[Any, tuple[Any, ...], Any]] = []
        self.timers: dict[int, tuple[int, Any]] = {}
        self.removed: list[int] = []
        self.last_source = 0

    def idle_add(self, callback, *args, priority=None):
        self.idles.append((callback, args, priority))
        self.last_source += 1
        return self.last_source

    def timeout_add(self, interval, callback, *args):
        self.last_source += 1
        self.timers[self.last_source] = (interval, callback)
        return self.last_source

    def source_remove(self, source):
        if source not in self.timers:
            raise AssertionError(f"source {source} is not there to remove")
        del self.timers[source]
        self.removed.append(source)
        return True

    def fire(self, source):
        """Run a timer's callback as GLib does, ending the source unless it answers True."""
        _interval, callback = self.timers[source]
        keep = callback()
        if not keep:
            self.timers.pop(source, None)  # unless the callback removed it, which is recorded
        return keep


@pytest.fixture
def sources(app_module, monkeypatch):
    stub = SourcesStub()
    monkeypatch.setattr(app_module.GLib, "idle_add", stub.idle_add)
    monkeypatch.setattr(app_module.GLib, "timeout_add", stub.timeout_add)
    monkeypatch.setattr(app_module.GLib, "source_remove", stub.source_remove)
    return stub


def configure(x: int, y: int, sent: bool = True):
    """A `configure-event`: `send_event` is what a window manager's carries."""
    return types.SimpleNamespace(send_event=int(sent), x=x, y=y)


def test_the_stubs_match_real_gtk():
    """A fake that offers what GTK lacks is how #30 and #41 shipped."""
    gi = pytest.importorskip("gi", reason="PyGObject not available")
    gi.require_version("Gdk", "3.0")
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gdk, Gtk

    for name in DialogStub.GTK_NAMES:
        assert hasattr(DialogStub, name), f"DialogStub is missing {name}"
        assert hasattr(Gtk.Window, name), f"Gtk.Window has no {name}"
    for name in ("get_position", "get_scale_factor"):
        assert hasattr(WindowStub, name), f"WindowStub is missing {name}"
        assert hasattr(Gtk.Window, name), f"Gtk.Window has no {name}"
    assert hasattr(GdkWindowStub, "get_origin")
    assert hasattr(Gdk.Window, "get_origin")
    for field in ("send_event", "x", "y"):
        assert hasattr(Gdk.EventConfigure, field), f"Gdk.EventConfigure has no {field}"


def test_a_report_at_a_place_relative_to_the_frame_is_not_the_placement(app_module):
    """Weston's reports before the placement are relative to the frame, (19, 29) at scale 2."""
    dialog = DialogStub(origin=(894, 864))

    assert not app_module.placement_reported(configure(19, 29), dialog)


def test_a_configure_event_no_window_manager_sent_is_not_the_placement(app_module):
    """Where GDK translates the position itself, `send_event` is false."""
    dialog = DialogStub(origin=(894, 864))

    assert not app_module.placement_reported(configure(894, 864, sent=False), dialog)


def test_a_window_that_is_not_realised_has_not_been_placed(app_module):
    dialog = DialogStub(origin=(894, 864))
    dialog.gdk_window = None

    assert not app_module.placement_reported(configure(894, 864), dialog)


def test_the_report_of_the_origin_is_the_placement(app_module):
    dialog = DialogStub(origin=(894, 864))

    assert app_module.placement_reported(configure(894, 864), dialog)


def test_a_report_at_a_place_relative_to_the_frame_queues_no_fit(app_module, sources):
    """The idle that read (0, 0) moved a dialog to a corner of the wrong monitor (#552)."""
    dialog = DialogStub(origin=(894, 864))
    app_module.fit_when_placed(dialog)

    dialog.deliver(configure(19, 29))

    assert sources.idles == []
    assert dialog.handlers and sources.timers, "the wait should go on"


def test_a_configure_event_no_window_manager_sent_queues_no_fit(app_module, sources):
    dialog = DialogStub(origin=(894, 864))
    app_module.fit_when_placed(dialog)

    dialog.deliver(configure(894, 864, sent=False))

    assert sources.idles == []
    assert dialog.handlers and sources.timers, "the wait should go on"


def test_the_report_of_the_placement_queues_the_fit_once(app_module, sources):
    dialog = DialogStub(origin=(894, 864))
    app_module.fit_when_placed(dialog)
    (timer,) = sources.timers

    dialog.deliver(configure(894, 864))
    dialog.deliver(configure(894, 864))  # nothing listens now

    assert sources.idles == [
        (app_module.fit_window_to_monitor, (dialog,), app_module.GLib.PRIORITY_LOW)
    ]
    assert dialog.handlers == {}, "the handler is disconnected"
    assert sources.removed == [timer] and sources.timers == {}, "the timer is removed"


def test_the_wait_gives_up_after_its_bound(app_module, sources):
    """A window manager that never reports must not have the fit run on a later drag."""
    dialog = DialogStub(origin=(894, 864))
    app_module.fit_when_placed(dialog)
    ((timer, (interval, _give_up)),) = sources.timers.items()
    assert interval == app_module.PLACEMENT_WAIT_MS

    assert sources.fire(timer) is False

    assert dialog.handlers == {}, "the handler is disconnected"
    assert sources.removed == [], "its source is finished: there is nothing to remove"
    dialog.deliver(configure(894, 864))
    assert sources.idles == []


def test_stopping_twice_does_nothing_more(app_module, sources):
    """The report and the bound can both come: the second stop disconnects and removes nothing."""
    dialog = DialogStub(origin=(894, 864))
    app_module.fit_when_placed(dialog)
    ((timer, (_interval, give_up)),) = sources.timers.items()

    dialog.deliver(configure(894, 864))
    give_up()

    assert dialog.calls.count("disconnect") == 1
    assert sources.removed == [timer]


def test_a_dialog_destroyed_before_its_placement_has_no_handler_to_disconnect(app_module, sources):
    """A destroyed window has lost its handlers already; disconnecting one is a GObject warning."""
    dialog = DialogStub(origin=(894, 864))
    app_module.fit_when_placed(dialog)
    ((timer, _wait),) = sources.timers.items()

    dialog.destroy()
    assert sources.fire(timer) is False

    assert "disconnect" not in dialog.calls
    assert sources.idles == []


def shown(app_module, monkeypatch, dialog):
    """Run `GladeComponent.show_dialog` on `dialog`, noting where it sizes the dialog."""
    monkeypatch.setattr(
        app_module, "size_window_for_monitor", lambda window: dialog.calls.append("size")
    )
    app_module.GladeComponent.show_dialog(types.SimpleNamespace(main_widget=dialog))


def test_under_x11_the_dialog_waits_for_the_report_armed_before_it_is_shown(
    app_module, sources, monkeypatch
):
    """Armed after the loop that follows show(), it could miss a report that loop dispatched."""
    dialog = DialogStub()

    shown(app_module, monkeypatch, dialog)

    assert dialog.calls == ["size", "connect configure-event", "show", "present"]
    assert sources.idles == [], "the fit is queued by the report"
    assert [interval for interval, _callback in sources.timers.values()] == [
        app_module.PLACEMENT_WAIT_MS
    ]


def test_under_wayland_the_fit_is_queued_on_an_idle_as_it_was(app_module, sources, monkeypatch):
    """`move()` does nothing there and the compositor places the window: nothing to wait for."""
    dialog = DialogStub(wayland=True)

    shown(app_module, monkeypatch, dialog)

    assert dialog.calls == ["size", "show", "present"]
    assert dialog.handlers == {} and sources.timers == {}, "nothing is waited for"
    assert sources.idles == [
        (app_module.fit_window_to_monitor, (dialog,), app_module.GLib.PRIORITY_LOW)
    ]


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

app.conf.CHECK_UPDATES = False
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


# Under X11 a dialog is fitted once the window manager reports where it placed it (#552),
# and the Xvfb these scenarios run on has none. So a scenario stands in for one: it sends
# the dialog a synthetic ConfigureNotify, as a window manager does, by ctypes as python-xlib
# is not a dependency. A `configure-event` handler gets it with `send_event` true and the
# (x, y) sent, as `placement_reported` reads it. The scenario also lengthens the wait, or its
# bound of 2 s runs out while the scenario settles, and counts the fits, so that a report the
# wait missed fails the scenario instead of passing it unfitted. Inserted at `# REPORTS`.
_REPORTS = r'''
import ctypes
gi.require_version("GdkX11", "3.0")
from gi.repository import GdkX11

class XConfigureEvent(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
                ("display", ctypes.c_void_p), ("event", ctypes.c_ulong), ("window", ctypes.c_ulong),
                ("x", ctypes.c_int), ("y", ctypes.c_int), ("width", ctypes.c_int),
                ("height", ctypes.c_int), ("border_width", ctypes.c_int), ("above", ctypes.c_ulong),
                ("override_redirect", ctypes.c_int)]

class XEvent(ctypes.Union):
    _fields_ = [("xconfigure", XConfigureEvent), ("pad", ctypes.c_long * 24)]

xlib = ctypes.CDLL("libX11.so.6")
xlib.XOpenDisplay.restype = ctypes.c_void_p
xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
xlib.XSendEvent.argtypes = [
    ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_long, ctypes.c_void_p]
xlib.XFlush.argtypes = [ctypes.c_void_p]
xlib.XCloseDisplay.argtypes = [ctypes.c_void_p]

def report_placement(window, x=None, y=None):
    """Say as a window manager does that `window` is at (x, y), by default where it is.

    Under Wayland no one reports a placement, and show_dialog queues the fit without."""
    gdk_window = window.get_window()
    if not isinstance(gdk_window, GdkX11.X11Window):
        return
    if x is None:
        _ok, x, y = gdk_window.get_origin()
    xdisplay = xlib.XOpenDisplay(None)
    assert xdisplay, "no connection to the display"
    xid = GdkX11.X11Window.get_xid(gdk_window)
    event = XEvent()
    event.xconfigure.type = 22  # ConfigureNotify
    event.xconfigure.event = event.xconfigure.window = xid
    scale = gdk_window.get_scale_factor()  # X counts pixels, GDK pixels divided by the scale
    event.xconfigure.x, event.xconfigure.y = x * scale, y * scale
    event.xconfigure.width = gdk_window.get_width() * scale
    event.xconfigure.height = gdk_window.get_height() * scale
    xlib.XSendEvent(xdisplay, xid, 0, 1 << 17, ctypes.byref(event))  # StructureNotifyMask
    xlib.XFlush(xdisplay)
    xlib.XCloseDisplay(xdisplay)

app.PLACEMENT_WAIT_MS = 60000
fits = []
real_fit = app.fit_window_to_monitor
def counted_fit(window):
    fits.append(window)
    return real_fit(window)
app.fit_window_to_monitor = counted_fit
'''

# The end-to-end check on whatever monitor is actually attached: where the button
# row lands on screen, which is what "I can't see the ok or cancel buttons" means.
_ONSCREEN_SCRIPT = """
import os, sys, tempfile, time
os.environ["HOME"] = tempfile.mkdtemp(); sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk, Gdk, GLib
from gnome_connection_manager import app
# REPORTS

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

app.conf.CHECK_UPDATES = False
app.wMain = app.Wmain(application=None)
area = app.monitor_workarea()
config = app.Wconfig()
settle()
window = config.get_widget("wConfig")
report_placement(window)
settle(0.5)
assert fits == [window], "expected one fit, of the dialog: %r" % (fits,)
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
""".replace("# REPORTS\n", _REPORTS)


@pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"),
    reason="needs a display for a real window",
)
@pytest.mark.parametrize("backend", ["", "x11"])
def test_preferences_buttons_land_on_screen_against_real_gtk(backend):
    """Under X11 the window manager places the dialog and reports where, and the fit
    moves it back if it hangs off the screen; a Wayland compositor places it itself, and
    the fit is queued on an idle. Both routes have to end on screen, after one fit."""
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

app.conf.CHECK_UPDATES = False
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


# -- a dialog is mapped at the size it keeps (#424) ----------------------------

_FIRST_SIZE_SCRIPT = """
import os, sys, tempfile, time
os.environ["HOME"] = tempfile.mkdtemp(); sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk, GObject
from gnome_connection_manager import app
# REPORTS

SCREEN = [1024, 600]
real_workarea = app.monitor_workarea
def small(window=None):
    area = real_workarea(window)
    if area is None:
        sys.exit("no monitor")
    if SCREEN[0]:
        area.x = area.y = 0
        area.width, area.height = SCREEN
    return area
app.monitor_workarea = small

first = {}
def on_map(*args):
    window = args[0]
    if isinstance(window, Gtk.Dialog):
        first.setdefault(window, window.get_size())
    return True
GObject.add_emission_hook(Gtk.Dialog, "map", on_map)

def settle(seconds=1.5):
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

app.conf.CHECK_UPDATES = False
app.wMain = app.Wmain(application=None)
settle()

def make_host():
    host = app.Host("g", "n", "", "example.test", "u", "", "", "22", "", "ssh")
    host.keep_alive = "0"
    host.commands = ""
    host.font_color = host.back_color = ""
    host.term = ""
    return host

def new_host():
    dialog = app.Whost()
    dialog.init("")
    return dialog

def edit_host():
    dialog = app.Whost()
    dialog.init("g", make_host())
    return dialog

builders = [
    ("Settings", app.Wconfig),
    ("New host", new_host),
    ("Edit host", edit_host),
    ("About", app.Wabout),
    ("Cluster", lambda: app.Wcluster(terms=[])),
]
for label, screen in (("real", [0, 0]), ("small", [1024, 400])):
    SCREEN[:] = screen
    for name, build in builders:
        first.clear()
        fits[:] = []
        component = build()
        settle()
        window = component.main_widget
        assert window in first, "%s/%s: never mapped" % (label, name)
        report_placement(window)
        settle(0.5)
        assert fits == [window], "%s/%s: expected one fit, of the dialog: %r" % (
            label, name, fits)
        assert first[window] == window.get_size(), "%s/%s: mapped at %r, ended at %r" % (
            label, name, first[window], window.get_size())
        if label == "small":
            # Cluster keeps its glade default size, 640x480, which no fit touches.
            if name != "Cluster":
                assert first[window][1] <= SCREEN[1], "%s: first height %r" % (name, first[window])
            for button in buttons(window, []):
                assert not in_a_scroller(button), "%s: %s scrolls" % (name, button.get_label())
        window.destroy()
print("FIRST-OK")
""".replace("# REPORTS\n", _REPORTS)


@pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"),
    reason="needs a display for a real window",
)
def test_a_dialog_is_mapped_at_the_size_it_keeps_against_real_gtk():
    """A dialog was presented empty and grown by new(), so the user saw it jump (#424)."""
    pytest.importorskip("gi", reason="PyGObject not available")
    result = subprocess.run(
        [sys.executable, "-c", _FIRST_SIZE_SCRIPT],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "GDK_BACKEND": "x11"},
        timeout=120,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert "FIRST-OK" in result.stdout


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
# REPORTS

SCREEN = [1024, 600]
real_workarea = app.monitor_workarea
def small(window=None):
    area = real_workarea(window)
    if area is None:
        sys.exit("no monitor")
    area.x = area.y = 0
    area.width, area.height = SCREEN
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

app.conf.CHECK_UPDATES = False
app.wMain = app.Wmain(application=None)
settle()

# The dialog has been through fit_window_to_monitor by the time it is checked: the
# window manager's report of its placement is sent first, and the fit counted, so this
# is the state the user is actually shown rather than a reconstruction of it.
def check(name, component, window_id, expected_first):
    window = component.get_widget(window_id)
    fits[:] = []
    report_placement(window)
    settle(0.5)
    assert fits == [window], "%s: expected one fit, of the dialog: %r" % (name, fits)
    nb = notebook_of(component)
    tabs = labels(nb)
    assert tabs[0] == expected_first, "%s: first tab is %r" % (name, tabs[0])
    scrolled = [i for i in range(nb.get_n_pages())
                if isinstance(nb.get_nth_page(i), Gtk.ScrolledWindow)]
    assert scrolled, "%s: no page was wrapped, so this proves nothing" % name
    current = nb.get_current_page()
    assert current == 0, "%s: opened on %r, not %r" % (name, tabs[current], expected_first)
    window.destroy()

config = app.Wconfig()
settle()
check("Settings", config, "wConfig", _("General"))

# Since SSH's options moved to a tab of their own (#277), Edit Host is about as tall as
# 1024x600 leaves room for: 4 pixels over where this was written, and under on CI, where
# it was not wrapped. A shorter screen makes it scroll whatever the font.
SCREEN[1] = 400
host = app.Host("g", "n", "", "example.test", "u", "", "", "22", "", "ssh")
# Host defaults some fields to ints; init() feeds them straight to set_text().
host.keep_alive = "0"
host.commands = ""
host.font_color = host.back_color = ""
host.term = ""
edit = app.Whost()
edit.init("g", host)
settle()
check("Edit Host", edit, "wHost", _("Properties"))

print("TABS-OK")
""".replace("# REPORTS\n", _REPORTS)


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

app.conf.CHECK_UPDATES = False
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


# -- a dialog is fitted once the window manager reports where it is (#552) ------

# Staged on an Xvfb: a parent low on the screen, and a dialog over it that GTK places with
# its bottom edge within the frame's allowance of the work area's bottom, or past it, which
# the script asserts first. The old idle fit moved it up at once, on a reading that was not
# the window manager's report. An Xvfb has no window manager, so nothing but
# `report_placement` says where the dialog is: first a place relative to the frame, as
# Weston's earlier reports are, then its own origin.
_PLACEMENT_SCRIPT = """
import os, sys, tempfile, time, types
os.environ["HOME"] = tempfile.mkdtemp(); sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk
from gnome_connection_manager import app
# REPORTS

def settle(seconds=0.5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        Gtk.main_iteration_do(False)
        time.sleep(0.005)

def origin(window):
    return tuple(window.get_window().get_origin()[1:])

def show(parent):
    # Its content asks for 400 by 600; set_default_size would not change the preferred
    # size the fit reads. The children are shown and the dialog is not, as GladeComponent
    # leaves one for show_dialog.
    dialog = Gtk.Dialog(title="dialog", transient_for=parent)
    filler = Gtk.Box()
    filler.set_size_request(400, 600)
    dialog.get_content_area().pack_start(filler, True, True, 0)
    dialog.add_button("OK", Gtk.ResponseType.OK)
    dialog.get_content_area().show_all()
    app.GladeComponent.show_dialog(types.SimpleNamespace(main_widget=dialog))
    return dialog

app.conf.CHECK_UPDATES = False
area = app.monitor_workarea()
bottom = area.y + area.height

parent = Gtk.Window(title="parent")
parent.set_default_size(300, 200)
parent.show_all()
parent.move(area.x + 100, bottom - 250)
settle()

dialog = show(parent)
placed = origin(dialog)
height = dialog.get_size()[1]
assert placed[1] + height + app.WINDOW_FRAME_ALLOWANCE > bottom, (
    "could not stage the fault: the dialog at %r, %d tall, is clear of the work area's bottom %d"
    % (placed, height, bottom))

# 1. Until the window manager reports, nothing is fitted and nothing moves.
settle()
assert fits == [], "fitted before the window manager reported: %r" % (fits,)
assert origin(dialog) == placed, "moved from %r to %r before the window manager reported" % (
    placed, origin(dialog))

# 2. A report relative to the frame is not the placement.
report_placement(dialog, 19, 29)
settle()
assert fits == [], "fitted on a report that was not the placement: %r" % (fits,)
assert origin(dialog) == placed, "moved from %r to %r on a report relative to the frame" % (
    placed, origin(dialog))

# 3. The report of its own place is, and the fit moves it up.
report_placement(dialog)
settle()
assert fits == [dialog], "expected one fit, of the dialog: %r" % (fits,)
y = origin(dialog)[1]
assert y + dialog.get_size()[1] + app.WINDOW_FRAME_ALLOWANCE <= bottom, (
    "the fit left the dialog at y=%d, %d tall; the work area ends at %d"
    % (y, dialog.get_size()[1], bottom))
assert y < placed[1], "the dialog was not moved up from y=%d" % placed[1]
dialog.destroy()

# The wait gives up after its bound: a report that comes later fits nothing. The bound is
# short and the pause long, so that a loaded machine cannot make the report come first.
app.PLACEMENT_WAIT_MS = 200
late = show(parent)
settle(1.2)
report_placement(late)
settle()
assert fits == [dialog], "a report after the wait gave up fitted a dialog: %r" % (fits,)
late.destroy()

# A dialog destroyed before it is placed leaves a wait that ends quietly.
gone = show(parent)
gone.destroy()
settle(1.2)
assert fits == [dialog], "a dialog that was destroyed was fitted: %r" % (fits,)
print("PLACED-OK")
""".replace("# REPORTS\n", _REPORTS)


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="needs an X server")
def test_a_dialog_is_fitted_once_the_manager_reports_its_place_against_real_gtk():
    """The idle fit read (0, 0) before Weston had placed a dialog, and moved it to the
    corner of a monitor its parent was not on (#552). The report of the placement queues the
    fit now; a report relative to the frame, and a wait that has given up, queue none."""
    pytest.importorskip("gi", reason="PyGObject not available")
    result = subprocess.run(
        [sys.executable, "-c", _PLACEMENT_SCRIPT],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "GDK_BACKEND": "x11"},
        timeout=90,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert "PLACED-OK" in result.stdout
    # PyGObject prints what a signal handler raises, and carries on.
    assert "Traceback" not in result.stderr, result.stderr[-2000:]
    assert glib_complaints(result.stderr) == []
