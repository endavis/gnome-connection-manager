"""An RDP host's desktop shown in its tab (#227).

A host whose Display is In its tab runs FreeRDP with `/parent-window:`, naming a window of
GCM's own, and `/size:`, the tab's. The tab is FreeRDP's terminal while it connects, and
the desktop once FreeRDP's window appears there. Where GCM does not run on X11, or Windows
Remote Desktop is the client, the host opens in a window of its own, and its tab says why.

The scenarios run real GCM on an Xvfb of their own, with a fake FreeRDP that draws a real
X window into the one it is given, at the size it is given, and logs each key, click and
size that reaches it. Their own, because they move X's keyboard focus and press keys and
buttons through XTest, which on the display the other tests share could reach another
test's windows. What the fake leaves out of FreeRDP was measured against FreeRDP 3.32.1
and 2.11.5 with FreeRDP's shadow server and Weston's RDP backend, written up on #227.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

from gnome_connection_manager.utils import connections
from gnome_connection_manager.utils.hosts import Host
from tests.test_connections import glib_complaints
from tests.test_console_window import _private_display

REPO = Path(__file__).resolve().parents[1]
FREERDP = connections.Programs(expect="/gcm/ssh.expect", username="localme")
WINDOWS = connections.Programs(expect="/gcm/ssh.expect", username="localme", rdp_client="mstsc")
TAB = connections.TabWindow(0x2000DD, 892, 592)


def rdp_host(**settings):
    host = Host("Work", "build box", "", "win.example.test", "me", "")
    host.type, host.port = "rdp", "3389"
    host.type_settings = {f"rdp.{key}": value for key, value in settings.items()}
    return host


def installed(monkeypatch, *names):
    """Pretend that only `names` are found, mstsc.exe where WSL finds Windows' own."""
    places = {connections.WINDOWS_RDP_CLIENT: "/mnt/c/WINDOWS/system32/mstsc.exe"}
    monkeypatch.setattr(
        connections.shutil,
        "which",
        lambda name: places.get(name, f"/usr/bin/{name}") if name in names else None,
    )


# -- the setting ---------------------------------------------------------------


def test_in_its_tab_is_offered_and_a_window_stays_the_default():
    """A changed default would move every host that never chose a Display into its tab."""
    [display] = [setting for setting in connections.RDP.settings if setting.key == "display"]

    assert ("tab", "In its tab") in display.choices
    assert display.default == "window"
    assert connections.RDP.settings_of(rdp_host())["display"] == "window"


# -- what FreeRDP is given -----------------------------------------------------


def test_in_its_tab_freerdp_draws_into_the_window_given_at_the_tabs_size():
    """FreeRDP makes its desktop the size it is given, never its parent's, measured."""
    args = connections.rdp_arguments(rdp_host(display="tab", size="1280x720"), TAB)

    assert args == [
        "/v:win.example.test",
        "/port:3389",
        "/u:me",
        "/parent-window:2097373",
        "/size:892x592",
        "/dynamic-resolution",
    ]


@pytest.mark.parametrize(
    ("width", "height", "size"),
    [(199, 32767, "/size:200x32766"), (200, 32766, "/size:200x32766"), (1, 0, "/size:200x200")],
)
def test_a_tab_is_given_as_a_size_freerdp_takes(width, height, size):
    """FreeRDP refuses to connect under 200 pixels or over 32766 on a side, measured (#278)."""
    window = connections.TabWindow(1, width, height)

    assert size in connections.rdp_arguments(rdp_host(display="tab"), window)


def test_in_its_tab_without_a_window_opens_in_a_window_with_its_size():
    """Where GCM cannot draw it in the tab, the host opens as In a window would."""
    in_tab = connections.rdp_arguments(rdp_host(display="tab", size="1280x720"))

    assert in_tab == connections.rdp_arguments(rdp_host(display="window", size="1280x720"))
    assert "/size:1280x720" in in_tab


@pytest.mark.parametrize("display", ["window", "full-screen", "all-monitors"])
def test_a_window_is_given_only_to_a_host_shown_in_its_tab(display):
    args = connections.rdp_arguments(rdp_host(display=display), TAB)

    assert args == connections.rdp_arguments(rdp_host(display=display))
    assert not [arg for arg in args if arg.startswith("/parent-window:")]


def test_the_extra_arguments_still_come_last_in_its_tab():
    host = rdp_host(display="tab")
    host.extra_params = "/smart-sizing"

    assert connections.rdp_arguments(host, TAB)[3:] == [
        "/parent-window:2097373",
        "/size:892x592",
        "/smart-sizing",
    ]


def test_windows_remote_desktop_opens_in_its_tab_as_in_a_window():
    """mstsc draws in a window of its own whatever it is given."""
    assert connections.mstsc_arguments(rdp_host(display="tab", size="1280x720")) == [
        "/v:win.example.test:3389",
        "/w:1280",
        "/h:720",
    ]


# -- which hosts are shown in their tab ----------------------------------------


@pytest.mark.parametrize(
    ("display", "programs", "shown"),
    [
        ("tab", FREERDP, True),
        ("window", FREERDP, False),
        ("full-screen", FREERDP, False),
        ("tab", WINDOWS, False),
    ],
)
def test_freerdp_shows_a_host_in_its_tab_when_its_display_says_so(
    monkeypatch, display, programs, shown
):
    installed(monkeypatch, "mstsc.exe", "xfreerdp3")

    assert connections.RDP.in_tab(rdp_host(display=display), programs) is shown


def test_the_command_carries_the_window_only_for_a_host_shown_in_its_tab(monkeypatch):
    installed(monkeypatch, "mstsc.exe", "xfreerdp3")
    programs = connections.Programs("/gcm/ssh.expect", "localme", tab_window=TAB)

    in_tab = connections.RDP.command(rdp_host(display="tab"), programs).argv
    in_window = connections.RDP.command(rdp_host(), programs).argv
    windows = connections.RDP.command(
        rdp_host(display="tab"), connections.Programs("e", "u", rdp_client="mstsc", tab_window=TAB)
    ).argv

    assert in_tab[:1] == ["xfreerdp3"] and "/parent-window:2097373" in in_tab
    assert not [arg for arg in in_window + windows if "2097373" in arg]


@pytest.mark.parametrize(
    ("display", "programs", "x11", "reason"),
    [
        ("tab", FREERDP, True, None),
        ("window", FREERDP, False, None),
        ("window", WINDOWS, True, None),
        (
            "tab",
            FREERDP,
            False,
            "GCM is not running on X11, so FreeRDP shows the desktop in a window of its own.",
        ),
        ("tab", WINDOWS, True, "Windows Remote Desktop shows the desktop in a window of its own."),
        ("tab", WINDOWS, False, "Windows Remote Desktop shows the desktop in a window of its own."),
    ],
)
def test_a_host_asking_for_its_tab_says_why_it_opens_in_a_window(
    monkeypatch, display, programs, x11, reason
):
    installed(monkeypatch, "mstsc.exe", "xfreerdp3")

    assert connections.RDP.window_instead(rdp_host(display=display), programs, x11) == reason


def test_a_desktop_is_shown_in_a_tab_only_on_x11(app_module, monkeypatch):
    """Elsewhere, on Wayland or without GDK's X11 bindings, such a host opens in a window."""

    class X11Display:
        pass

    def display(found):
        monkeypatch.setattr(app_module.Gdk, "Display", types.SimpleNamespace(get_default=found))

    monkeypatch.setattr(app_module, "GdkX11", types.SimpleNamespace(X11Display=X11Display))
    display(X11Display)
    assert app_module.can_show_desktops() is True
    display(object)
    assert app_module.can_show_desktops() is False
    display(X11Display)
    monkeypatch.setattr(app_module, "GdkX11", None)
    assert app_module.can_show_desktops() is False


# -- against real GTK ----------------------------------------------------------

# FreeRDP, as far as GCM sees it: its arguments in its terminal, the certificate question
# there before any window when FAKE_RDP_ASK is set, then a window in the one
# /parent-window: names, at the size /size: gives. FAKE_RDP_SERVER_SIZE makes it what a
# server with a size of its own does, measured with FreeRDP's shadow server: FreeRDP
# makes its window that size as it finishes connecting. 0.02 s after it made the window,
# measured on this computer, and here a second, as a server farther away answers later:
# after GCM has found the window and fitted it to the tab once. It logs what reaches the window,
# and ends on SIGHUP, which a terminal sends as it closes, as FreeRDP does.
_FAKE_FREERDP = r"""
import ctypes, os, sys, time

log = open(os.environ["FAKE_RDP_LOG"], "a", buffering=1)
log.write("pid %d\n" % os.getpid())
log.write("arguments " + " ".join(sys.argv[1:]) + "\n")
print("arguments:", *sys.argv[1:], flush=True)
if os.environ.get("FAKE_RDP_ASK"):
    print("Do you trust the above certificate? (Y/T/N) ", end="", flush=True)
    log.write("answer %s\n" % sys.stdin.readline().strip())
options = dict(arg[1:].partition(":")[::2] for arg in sys.argv[1:] if arg.startswith("/"))
width, height = (int(side) for side in options.get("size", "1024x768").split("x"))


class Input(ctypes.Structure):
    # XKeyEvent, and XButtonEvent, whose button is where a key event has its keycode.
    _fields_ = [
        ("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p), ("window", ctypes.c_ulong), ("root", ctypes.c_ulong),
        ("subwindow", ctypes.c_ulong), ("time", ctypes.c_ulong), ("x", ctypes.c_int),
        ("y", ctypes.c_int), ("x_root", ctypes.c_int), ("y_root", ctypes.c_int),
        ("state", ctypes.c_uint), ("detail", ctypes.c_uint), ("same_screen", ctypes.c_int),
    ]


class Configure(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p), ("event", ctypes.c_ulong), ("window", ctypes.c_ulong),
        ("x", ctypes.c_int), ("y", ctypes.c_int), ("width", ctypes.c_int),
        ("height", ctypes.c_int), ("border_width", ctypes.c_int), ("above", ctypes.c_ulong),
        ("override_redirect", ctypes.c_int),
    ]


class Event(ctypes.Union):
    _fields_ = [
        ("type", ctypes.c_int), ("input", Input), ("configure", Configure),
        ("pad", ctypes.c_long * 24),
    ]


x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
x11.XOpenDisplay.restype = ctypes.c_void_p
x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
x11.XDefaultRootWindow.restype = ctypes.c_ulong
x11.XCreateSimpleWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong] + [ctypes.c_int] * 2 + [
    ctypes.c_uint
] * 3 + [ctypes.c_ulong] * 2
x11.XCreateSimpleWindow.restype = ctypes.c_ulong
x11.XSelectInput.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_long]
x11.XMapWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
x11.XResizeWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_uint, ctypes.c_uint]
x11.XFlush.argtypes = [ctypes.c_void_p]
x11.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.POINTER(Event)]
x11.XLookupKeysym.argtypes = [ctypes.POINTER(Input), ctypes.c_int]
x11.XLookupKeysym.restype = ctypes.c_ulong
x11.XKeysymToString.argtypes = [ctypes.c_ulong]
x11.XKeysymToString.restype = ctypes.c_char_p
display = x11.XOpenDisplay(None)
parent = int(options.get("parent-window") or x11.XDefaultRootWindow(display))
window = x11.XCreateSimpleWindow(display, parent, 0, 0, width, height, 0, 0, 0xFF00FF)
# KeyPress, ButtonPress and StructureNotify.
x11.XSelectInput(display, window, (1 << 0) | (1 << 2) | (1 << 17))
x11.XMapWindow(display, window)
x11.XFlush(display)
log.write("window %d\n" % window)
if os.environ.get("FAKE_RDP_SERVER_SIZE"):
    time.sleep(1)
    width, height = (int(side) for side in os.environ["FAKE_RDP_SERVER_SIZE"].split("x"))
    x11.XResizeWindow(display, window, width, height)
    x11.XFlush(display)
    log.write("server size %dx%d\n" % (width, height))
event, size = Event(), None
while True:
    x11.XNextEvent(display, ctypes.byref(event))
    if event.type == 2:
        name = x11.XKeysymToString(x11.XLookupKeysym(ctypes.byref(event.input), 0))
        log.write("key %s\n" % name.decode())
    elif event.type == 4:
        log.write("button %d at %d,%d\n" % (event.input.detail, event.input.x, event.input.y))
    elif event.type == 22 and event.configure.window == window:
        if (event.configure.width, event.configure.height) != size:
            size = (event.configure.width, event.configure.height)
            log.write("size %dx%d\n" % size)
"""

_SCRIPT = r"""
import ctypes, faulthandler, os, signal, sys, tempfile, time
faulthandler.dump_traceback_later(100, exit=True)
scenario, scratch = sys.argv[1], sys.argv[2]
os.environ["HOME"] = tempfile.mkdtemp(); os.environ["SHELL"] = "/bin/sh"; sys.argv = ["gcm"]
LOG = os.path.join(scratch, "freerdp.log")
os.environ["FAKE_RDP_LOG"] = LOG
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0")
gi.require_version("GdkX11", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gdk, GdkX11, Gtk, Vte
from gnome_connection_manager import app

app.conf.CONFIRM_ON_CLOSE_TAB = 0
app.conf.STARTUP_LOCAL = False
app.conf.CHECK_UPDATES = False
app.conf.AUTO_CLOSE_TAB = 0
app.conf.BELL_NOTIFY = 0
# Started as GCM starts, so that its windows are the application's.
application = app.GcmApplication()
assert application.register(None)
application.activate()
w = application._controller
w.wMain.move(0, 0)
w.wMain.resize(1000, 700)
w.wMain.present()

def pump(seconds=0.2):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        Gtk.main_iteration_do(False)
        time.sleep(0.005)

def until(condition, seconds=10):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        Gtk.main_iteration_do(False)
        if condition():
            return True
        time.sleep(0.005)
    return False

assert until(w.wMain.is_active), "GCM's window never became active"

def said():
    with open(LOG) as file:
        return file.read().splitlines()

def logged(line, seconds=10):
    return until(lambda: line in said(), seconds)

def fake_pid():
    return int([line for line in said() if line.startswith("pid ")][-1].split()[1])

def ended(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    # A child VTE has not reaped yet is a zombie, and ended as far as this goes.
    with open("/proc/%d/stat" % pid) as file:
        return file.read().split(") ")[1].startswith("Z")

x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
xtst = ctypes.cdll.LoadLibrary("libXtst.so.6")
x11.XOpenDisplay.restype = ctypes.c_void_p
x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
x11.XFlush.argtypes = [ctypes.c_void_p]
x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
x11.XKeysymToKeycode.restype = ctypes.c_ubyte
x11.XGetInputFocus.argtypes = [
    ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int)
]
x11.XQueryTree.argtypes = [
    ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
    ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),
    ctypes.POINTER(ctypes.c_uint),
]
x11.XGetGeometry.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)]
x11.XGetGeometry.argtypes += [ctypes.POINTER(ctypes.c_int)] * 2
x11.XGetGeometry.argtypes += [ctypes.POINTER(ctypes.c_uint)] * 4
x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
x11.XDefaultRootWindow.restype = ctypes.c_ulong
x11.XCreateSimpleWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong] + [ctypes.c_int] * 2
x11.XCreateSimpleWindow.argtypes += [ctypes.c_uint] * 3 + [ctypes.c_ulong] * 2
x11.XCreateSimpleWindow.restype = ctypes.c_ulong
x11.XMapWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
x11.XSetInputFocus.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
xtst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
xtst.XTestFakeButtonEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
xtst.XTestFakeMotionEvent.argtypes = [
    ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong
]
dpy = x11.XOpenDisplay(None)

def press(keysym):
    code = x11.XKeysymToKeycode(dpy, keysym)
    xtst.XTestFakeKeyEvent(dpy, code, True, 0)
    xtst.XTestFakeKeyEvent(dpy, code, False, 0)
    x11.XFlush(dpy)
    pump(0.3)

def point(x, y):
    xtst.XTestFakeMotionEvent(dpy, -1, int(x), int(y), 0)
    x11.XFlush(dpy)
    pump(0.3)

def click(x, y):
    point(x, y)
    xtst.XTestFakeButtonEvent(dpy, 1, True, 0)
    xtst.XTestFakeButtonEvent(dpy, 1, False, 0)
    x11.XFlush(dpy)
    pump(0.3)

def chord(*keysyms):
    # Press the keys together, and let them go in reverse.
    codes = [x11.XKeysymToKeycode(dpy, keysym) for keysym in keysyms]
    for code in codes:
        xtst.XTestFakeKeyEvent(dpy, code, True, 0)
    for code in reversed(codes):
        xtst.XTestFakeKeyEvent(dpy, code, False, 0)
    x11.XFlush(dpy)
    pump(0.4)

def centre(widget):
    # Where `widget` is on the screen. A tab's text draws on its own event box's window.
    allocation = widget.get_allocation()
    _, x, y = widget.get_window().get_origin()
    return x + allocation.x + allocation.width // 2, y + allocation.y + allocation.height // 2

def focus():
    window, revert = ctypes.c_ulong(), ctypes.c_int()
    x11.XGetInputFocus(dpy, ctypes.byref(window), ctypes.byref(revert))
    return window.value

def parent_of(xid):
    root, parent = ctypes.c_ulong(), ctypes.c_ulong()
    found, count = ctypes.POINTER(ctypes.c_ulong)(), ctypes.c_uint()
    assert x11.XQueryTree(dpy, xid, ctypes.byref(root), ctypes.byref(parent), found, count)
    return parent.value

def exists(xid):
    # An X error on this connection is GDK's handler's to ignore, measured on #227.
    root, x, y = ctypes.c_ulong(), ctypes.c_int(), ctypes.c_int()
    sides = [ctypes.c_uint() for _ in range(4)]
    return bool(x11.XGetGeometry(dpy, xid, root, x, y, *sides))

def size_of(xid):
    root, x, y = ctypes.c_ulong(), ctypes.c_int(), ctypes.c_int()
    sides = [ctypes.c_uint() for _ in range(4)]
    assert x11.XGetGeometry(dpy, xid, root, x, y, *sides)
    return (sides[0].value, sides[1].value)

def xid(widget):
    return GdkX11.X11Window.get_xid(widget.get_window())

def origin(widget):
    got = widget.get_window().get_origin()
    return got[-2], got[-1]

def pixels(widget):
    scale = widget.get_scale_factor()
    return (widget.get_allocated_width() * scale, widget.get_allocated_height() * scale)

def text(v):
    whole, _ = v.get_text_range_format(Vte.Format.TEXT, 0, 0, v.get_cursor_position()[1], 10000)
    return whole or ""

host = app.Host("Work", "desk", "", "win.example.test", "me", "")
host.type, host.port = "rdp", "3389"
host.type_settings = {"rdp.display": "tab"}

def open_desktop(shown=True):
    w.addTab(w.nbConsole, host)
    page = w.nbConsole.get_nth_page(w.nbConsole.get_current_page())
    v = app.page_terminal(page)
    if shown:
        assert until(lambda: v.desktop.get_visible()), said()
        pump(0.3)
    return page, v, v.desktop

def window_id():
    return int([line for line in said() if line.startswith("window ")][-1].split()[1])

if scenario == "the-desktop-takes-the-terminals-place":
    page, v, desktop = open_desktop(shown=False)
    # FreeRDP draws into GCM's window, at the tab's size.
    program, argv, environment = v.command
    width, height = pixels(page)
    assert argv[3:6] == [
        "/u:me", "/parent-window:%d" % desktop.holder, "/size:%dx%d" % (width, height)
    ], argv
    assert until(desktop.get_visible), said()
    pump(0.3)
    assert not v.get_visible(), "the terminal still shows beside the desktop"
    window = window_id()
    assert parent_of(window) == desktop.holder
    assert parent_of(desktop.holder) == xid(desktop)
    assert size_of(window) == pixels(desktop) == size_of(desktop.holder), (
        size_of(window), pixels(desktop)
    )
    assert w.wMain.get_focus() is desktop

elif scenario == "a-server-of-its-own-size-is-fitted-to-the-tab":
    os.environ["FAKE_RDP_SERVER_SIZE"] = "1920x1080"
    page, v, desktop = open_desktop()
    assert logged("server size 1920x1080"), said()
    assert until(lambda: size_of(window_id()) == pixels(desktop)), size_of(window_id())

elif scenario == "it-follows-the-tab":
    page, v, desktop = open_desktop()
    w.wMain.resize(1300, 900)
    assert until(lambda: pixels(desktop)[0] > 1000), pixels(desktop)
    pump(0.3)
    assert size_of(window_id()) == pixels(desktop), (size_of(window_id()), pixels(desktop))
    assert logged("size %dx%d" % pixels(desktop)), said()

elif scenario == "keys-and-clicks-reach-it":
    page, v, desktop = open_desktop()
    assert until(lambda: focus() == window_id()), "FreeRDP's window never got X's focus"
    x, y = origin(desktop)
    # Off the desktop, the keys still go to it: it has the keyboard.
    point(x + 40, y - 15)
    press(0x61)
    assert logged("key a"), said()
    # A click lands where it is made. The pointer settles first: FreeRDP sent a press
    # made in the same instant as a move before the move, measured.
    click(x + 120, y + 90)
    assert logged("button 1 at 120,90"), said()

elif scenario == "choosing-its-tab-gives-it-the-keyboard":
    page, v, desktop = open_desktop()
    w.addTab(w.nbConsole, "local")
    local_page = w.nbConsole.get_nth_page(w.nbConsole.get_current_page())
    local = app.page_terminal(local_page)
    assert until(lambda: w.wMain.get_focus() is local)
    # By its key, Alt+1, from the local console's terminal.
    chord(0xFFE9, 0x31)
    assert until(lambda: w.nbConsole.get_current_page() == w.nbConsole.page_num(page))
    assert until(lambda: w.wMain.get_focus() is desktop), w.wMain.get_focus()
    assert until(lambda: focus() == window_id()), "the desktop never got X's focus"
    # By a click on the local console's tab, and then on its own.
    click(*centre(w.nbConsole.get_tab_label(local_page).label))
    assert until(lambda: w.nbConsole.get_current_page() == w.nbConsole.page_num(local_page))
    assert until(lambda: focus() == xid(w.wMain)), (focus(), xid(w.wMain))
    click(*centre(w.nbConsole.get_tab_label(page).label))
    assert until(lambda: w.nbConsole.get_current_page() == w.nbConsole.page_num(page))
    assert until(lambda: w.wMain.get_focus() is desktop), w.wMain.get_focus()
    assert until(lambda: focus() == window_id()), "the desktop never got X's focus"

elif scenario == "the-keyboard-comes-back-to-gcm":
    page, v, desktop = open_desktop()
    w.addTab(w.nbConsole, "local")
    local = app.page_terminal(w.nbConsole.get_nth_page(w.nbConsole.get_current_page()))
    # The local console in a pane of its own, beside the desktop, both in sight.
    application._on_action_split_horizontal(None, None)
    pump(0.5)
    # The desktop takes the keyboard as the open-console list gives it, not its terminal.
    w.focus_console(page.get_parent(), page)
    assert w.wMain.get_focus() is desktop and desktop.get_mapped()
    assert until(lambda: focus() == window_id())
    w.wMain.set_focus(local)
    toplevel = xid(w.wMain)
    assert until(lambda: focus() == toplevel), (focus(), toplevel)
    x, y = origin(local)
    point(x + 20, y + 20)
    press(0x62)
    assert until(lambda: "b" in text(local)), text(local)
    assert "key b" not in said()

elif scenario == "another-window-keeps-the-keyboard-it-took":
    page, v, desktop = open_desktop()
    assert until(lambda: focus() == window_id())
    other = x11.XCreateSimpleWindow(dpy, x11.XDefaultRootWindow(dpy), 0, 0, 100, 100, 0, 0, 0)
    x11.XMapWindow(dpy, other)
    x11.XSync(dpy, 0)
    pump(0.3)
    x11.XSetInputFocus(dpy, other, 2, 0)
    x11.XFlush(dpy)
    assert until(lambda: not w.wMain.is_active()), "GCM's window stayed active"
    pump(0.5)
    assert focus() == other, "GCM took the keyboard back from another window"

elif scenario == "moved-to-another-pane-and-a-window-of-its-own":
    page, v, desktop = open_desktop()
    pid, window = fake_pid(), window_id()
    w.addTab(w.nbConsole, "local")
    application._on_action_split_horizontal(None, None)
    pump(0.5)
    other = [nb for nb in w.console_notebooks() if nb is not page.get_parent()][0]
    w.move_page(page, other)
    other.set_current_page(other.page_num(page))
    assert until(desktop.get_realized)
    pump(0.5)
    assert parent_of(desktop.holder) == xid(desktop)
    assert parent_of(window) == desktop.holder
    assert size_of(window) == pixels(desktop), (size_of(window), pixels(desktop))
    w.toggle_console_window(page)
    assert until(lambda: w.console_windows and desktop.get_realized())
    pump(0.5)
    assert desktop.get_toplevel() is w.console_windows[0]
    assert parent_of(desktop.holder) == xid(desktop)
    assert parent_of(window) == desktop.holder
    assert not ended(pid), "FreeRDP ended as its tab moved"

elif scenario == "the-certificate-question-is-the-users":
    os.environ["FAKE_RDP_ASK"] = "1"
    page, v, desktop = open_desktop(shown=False)
    assert until(lambda: "(Y/T/N)" in text(v)), text(v)
    # The question is the user's (#216): nothing answers it, and no desktop hides it.
    pump(1)
    assert v.get_visible() and not desktop.get_visible()
    assert not [line for line in said() if line.startswith("answer")]
    app.vte_feed(v, "T\r")
    assert logged("answer T"), said()
    assert until(desktop.get_visible)

elif scenario == "an-end-shows-the-terminal-and-reconnect-the-desktop":
    page, v, desktop = open_desktop()
    holder, tab = desktop.holder, page.get_parent().get_tab_label(page)
    os.kill(fake_pid(), signal.SIGTERM)
    assert until(v.get_visible), "the terminal never came back"
    assert not desktop.get_visible()
    assert "arguments:" in text(v)
    assert w.wMain.get_focus() is v
    # The tab changes size before the reconnect, which is given the size it has now.
    w.wMain.resize(1200, 800)
    assert until(lambda: pixels(page)[0] > 1000), pixels(page)
    w.reconnect(v, tab)
    assert until(desktop.get_visible), said()
    assert "/parent-window:%d" % holder in v.command[1]
    assert "/size:%dx%d" % pixels(page) in v.command[1], (v.command[1], pixels(page))
    assert parent_of(window_id()) == holder

elif scenario == "closing-the-tab-ends-freerdp":
    page, v, desktop = open_desktop()
    pid, holder = fake_pid(), desktop.holder
    page.get_parent().get_tab_label(page).close_tab(None)
    assert until(lambda: ended(pid)), "FreeRDP outlived its tab"
    assert not exists(holder), "GCM's window for the tab outlived it"

elif scenario == "not-on-x11-a-window-and-why":
    app.can_show_desktops = lambda: False
    w.addTab(w.nbConsole, host)
    v = app.page_terminal(w.nbConsole.get_nth_page(w.nbConsole.get_current_page()))
    assert not hasattr(v, "desktop")
    assert not [arg for arg in v.command[1] if arg.startswith("/parent-window:")]
    assert until(lambda: "arguments:" in text(v))
    reason = "GCM is not running on X11, so FreeRDP shows the desktop in a window of its own."
    assert text(v).index(reason) < text(v).index("arguments:"), text(v)

elif scenario == "x-calls-are-made-on-gdks-own-connection":
    display = Gdk.Display.get_default()
    calls = app.X11(display)
    root = GdkX11.X11Window.get_xid(Gdk.get_default_root_window())
    calls.lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    calls.lib.XDefaultRootWindow.restype = ctypes.c_ulong
    assert calls.lib.XDefaultRootWindow(calls.xdisplay) == root
    # A window that is gone raises an X error, which GDK's trap takes.
    gone = calls.make_window()
    calls.destroy(gone)
    calls.resize(gone, 10, 10)
    calls.focus(gone)
    assert calls.children(gone) == [] and calls.size(gone) is None
    display.sync()
    pump(0.3)

else:
    raise SystemExit("no scenario " + scenario)
print("OK")
"""


@pytest.mark.skipif(shutil.which("Xvfb") is None, reason="needs Xvfb for a display of its own")
@pytest.mark.parametrize(
    ("scenario", "scale"),
    [
        ("the-desktop-takes-the-terminals-place", None),
        # A tab measured in GTK's pixels, and FreeRDP's window in the screen's.
        ("the-desktop-takes-the-terminals-place", "2"),
        ("a-server-of-its-own-size-is-fitted-to-the-tab", None),
        ("it-follows-the-tab", None),
        ("keys-and-clicks-reach-it", None),
        ("choosing-its-tab-gives-it-the-keyboard", None),
        ("the-keyboard-comes-back-to-gcm", None),
        ("another-window-keeps-the-keyboard-it-took", None),
        ("moved-to-another-pane-and-a-window-of-its-own", None),
        ("the-certificate-question-is-the-users", None),
        ("an-end-shows-the-terminal-and-reconnect-the-desktop", None),
        ("closing-the-tab-ends-freerdp", None),
        ("not-on-x11-a-window-and-why", None),
        ("x-calls-are-made-on-gdks-own-connection", None),
    ],
)
def test_an_rdp_desktop_in_its_tab_against_real_gtk(scenario, scale, tmp_path):
    pytest.importorskip("gi", reason="PyGObject not available")
    fake = tmp_path / "fake_freerdp.py"
    fake.write_text(_FAKE_FREERDP)
    client = tmp_path / "xfreerdp3"
    client.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{fake}" "$@"\n')
    client.chmod(0o755)
    process, display = _private_display()
    environment = dict(os.environ, DISPLAY=display, GDK_BACKEND="x11")
    environment["PATH"] = f"{tmp_path}{os.pathsep}{environment['PATH']}"
    for name in ("WAYLAND_DISPLAY", "GDK_SCALE", "GDK_DPI_SCALE", "XDG_CONFIG_HOME"):
        environment.pop(name, None)
    if scale:
        environment["GDK_SCALE"] = scale
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
