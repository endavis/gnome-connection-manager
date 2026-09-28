"""VNC hosts drawn in their tab by gtk-vnc (#234), against a real VNC server.

Each scenario runs in a process of its own with real GTK and gtk-vnc, and starts
TigerVNC's `Xtigervnc` on a free port for its host to connect to. They are skipped where
either is missing: CI installs both, and a machine without them has only the fallback,
a VNC viewer in a terminal tab, which `tests/test_connections.py` covers.

What the server does was measured with gtk-vnc 1.3.1 and Xtigervnc 1.13.1, and the
scenarios pin GCM's side of it: which credentials it gives, what the tab says, and how
the tab ends. The end is clean only when GCM closed the connection. gtk-vnc reports a
failed login and a server going away as errors, and drops a server it has no security
type in common with without one.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_connections import glib_complaints

REPO = Path(__file__).resolve().parents[1]

_SCRIPT = r'''
import ctypes, os, signal, socket, subprocess, sys, tempfile, time
scenario, scratch = sys.argv[1], sys.argv[2]

def dies_with_us():
    # A server or logger this starts ends with it, however it ends: a failed assertion
    # or the test's timeout. Left running, they held its output open and the test waited.
    ctypes.CDLL(None).prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG
os.environ["HOME"] = tempfile.mkdtemp(); sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0"); gi.require_version("Vte", "2.91")
gi.require_version("GtkVnc", "2.0")
from gi.repository import Gdk, Gtk, GtkVnc
from gnome_connection_manager import app

app.conf.CONFIRM_ON_CLOSE_TAB = 0
app.conf.STARTUP_LOCAL = False
app.conf.AUTO_CLOSE_TAB = 2  # Only on clean exit
# Started as GCM starts, so that its shortcuts are the window's accelerators. It is
# NON_UNIQUE, so it never reaches a GCM already running.
application = app.GcmApplication()
assert application.register(None)
application.activate()
app.wMain = w = application._controller
PASSWORD = "sekrit12"

def never_asked(*args, **kwargs):
    raise AssertionError("GCM asked for what the host stores")

app.inputbox = never_asked

def pump(seconds):
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

class Server:
    """Xtigervnc on a free port, with a desktop of 800x600."""

    def __init__(self, *security):
        passwords = os.path.join(scratch, "passwd")
        typed = subprocess.run(["tigervncpasswd", "-f"], input=(PASSWORD + "\n").encode(),
                               capture_output=True, check=True)
        with open(passwords, "wb") as out:
            out.write(typed.stdout)
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        self.port = probe.getsockname()[1]
        probe.close()
        security = security or ("-SecurityTypes", "VncAuth")
        # A number of its own, tried until one is free: another worker may take the same.
        for number in range(400, 500):
            if os.path.exists(f"/tmp/.X{number}-lock"):
                continue
            self.log = os.path.join(scratch, f"server-{number}.log")
            self.process = subprocess.Popen(
                ["Xtigervnc", f":{number}", "-rfbport", str(self.port), "-localhost", *security,
                 "-PasswordFile", passwords, "-geometry", "800x600", "-nolisten", "tcp"],
                stdout=subprocess.DEVNULL, stderr=open(self.log, "w"), preexec_fn=dies_with_us)
            end = time.monotonic() + 10
            while time.monotonic() < end and self.process.poll() is None and not self.said("Listening for VNC"):
                time.sleep(0.02)
            if self.said("Listening for VNC"):
                self.display = f":{number}"
                return
            self.stop()
        raise SystemExit("no Xtigervnc came up")

    def said(self, text):
        with open(self.log) as log:
            return text in log.read()

    def stop(self):
        self.process.terminate()
        self.process.wait()

def open_desk(server, password=PASSWORD, user=""):
    record = app.Host("Work", "desk", "", "127.0.0.1", user, password)
    record.type, record.port = "vnc", str(server.port)
    w.addTab(w.nbConsole, record)
    page = w.nbConsole.get_nth_page(w.nbConsole.get_n_pages() - 1)
    return page, w.nbConsole.get_tab_label(page)

def ended(label):
    return lambda: not label.is_active

def press(keyval):
    """Ctrl and a key, pressed and let go, through the main window as a key typed is."""
    keymap = Gdk.Keymap.get_for_display(Gdk.Display.get_default())
    keyboard = Gdk.Display.get_default().get_default_seat().get_keyboard()
    held = Gdk.ModifierType.CONTROL_MASK
    for kind, value, state in ((Gdk.EventType.KEY_PRESS, Gdk.KEY_Control_L, 0),
                               (Gdk.EventType.KEY_PRESS, keyval, held),
                               (Gdk.EventType.KEY_RELEASE, keyval, held),
                               (Gdk.EventType.KEY_RELEASE, Gdk.KEY_Control_L, held)):
        event = Gdk.Event.new(kind)
        event.key.window = w.wMain.get_window()
        event.key.time = Gdk.CURRENT_TIME
        event.key.state = state
        event.key.keyval = value
        found, keys = keymap.get_entries_for_keyval(value)
        event.key.hardware_keycode, event.key.group = keys[0].keycode, keys[0].group
        event.set_device(keyboard)
        Gtk.main_do_event(event)
    pump(0.3)

def on_screen(display):
    """The colour drawn at the middle of the display, read back from the X server.

    Every test's windows open on the one Xvfb, at the same place, and measured, a read
    of a window another covers returns what covers it: another test's console, black
    (#250). So the window is raised first, and `until` waits while GTK draws again what
    the raise uncovered.
    """
    display.get_toplevel().get_window().raise_()
    pixels = Gdk.pixbuf_get_from_window(display.get_window(), display.get_allocated_width() // 2,
                                        display.get_allocated_height() // 2, 1, 1)
    return tuple(pixels.get_pixels()[:3])

if scenario == "a-stored-password-connects":
    server = Server()
    page, label = open_desk(server)
    assert isinstance(page, app.VncPage), page
    assert label.get_text().strip() == "desk"
    assert page.status.get_visible() and page.status.get_text() == f"Connecting to 127.0.0.1:{server.port}"
    assert until(lambda: page.initialized), page.status.get_text()
    pump(0.3)
    # The desktop is drawn and scaled to fit, the line above it has gone, and the keyboard is in it.
    assert (page.display.get_width(), page.display.get_height()) == (800, 600)
    assert page.display.get_scaling() and page.display.get_keep_aspect_ratio()
    assert not page.status.get_visible() and label.is_active
    assert w.wMain.get_focus() is page.display, w.wMain.get_focus()
    # The line is shown only while it has something to say, whatever shows the window.
    w.wMain.show_all()
    pump(0.1)
    assert not page.status.get_visible()
    server.stop()
elif scenario == "gcm-asks-for-a-password-it-does-not-store":
    asked = []

    def answer(title, text, default="", password=False, parent=None):
        asked.append((title, password, parent is w.wMain))
        return PASSWORD

    app.inputbox = answer
    server = Server()
    page, label = open_desk(server, password="")
    assert until(lambda: page.initialized), page.status.get_text()
    assert asked == [("desk", True, True)], asked
    server.stop()
elif scenario == "cancelling-the-password-closes-the-connection":
    app.inputbox = lambda *args, **kwargs: None
    server = Server()
    # With Close console at Never, the tab stays to say so.
    app.conf.AUTO_CLOSE_TAB = 0
    page, label = open_desk(server, password="")
    assert until(ended(label)), page.status.get_text()
    assert page.status.get_text() == "Disconnected" and page.get_parent() is w.nbConsole
    assert until(lambda: server.said("Connections: closed"))
    # Closed by GCM, the end is clean: Only on clean exit closes the tab.
    app.conf.AUTO_CLOSE_TAB = 2
    page, label = open_desk(server, password="")
    assert until(lambda: page.get_parent() is None), page.status.get_text()
    server.stop()
elif scenario == "a-wrong-password-says-why":
    server = Server()
    page, label = open_desk(server, password="wrong")
    assert until(ended(label)), page.status.get_text()
    assert page.status.get_visible() and page.status.get_text() == "Authentication failure"
    assert page.get_parent() is w.nbConsole, "a failed login closed the tab"
    server.stop()
elif scenario == "a-user-name-answers-a-server-that-asks-for-one":
    # TLSPlain asks for a user name and a password. The server checks them with PAM and
    # refuses, as there is no user "me", which shows the login went on with both.
    given = []
    real_open = app.VncPage.open

    def open_recording(page):
        # What GCM gives gtk-vnc, recorded on the way.
        def set_credential(kind, value):
            given.append((GtkVnc.DisplayCredential(kind).value_nick, value))
            return GtkVnc.Display.set_credential(page.display, kind, value)

        page.display.set_credential = set_credential
        real_open(page)

    app.VncPage.open = open_recording
    server = Server("-SecurityTypes", "TLSPlain", "-PlainUsers", "me")
    page, label = open_desk(server, user="me")
    assert until(ended(label), 20), page.status.get_text()
    assert page.status.get_text().startswith("Authentication failure"), page.status.get_text()
    assert given == [("username", "me"), ("password", PASSWORD)], given
    asked = []

    def answer(title, text, default="", password=False, parent=None):
        asked.append(password)
        return "typed-password" if password else "typed-user"

    app.inputbox = answer
    given.clear()
    page, label = open_desk(server, user="", password="")
    assert until(ended(label), 20), page.status.get_text()
    assert page.status.get_text().startswith("Authentication failure"), page.status.get_text()
    assert asked == [False, True], asked  # the user name, then the password
    assert given == [("username", "typed-user"), ("password", "typed-password")], given
    server.stop()
elif scenario == "the-server-going-away-ends-the-tab":
    server = Server()
    page, label = open_desk(server)
    # gtk-vnc's words depend on what it was doing: "Server closed the connection" when
    # it was reading, and "Failed to flush data" when it was writing, measured.
    reported = []
    page.display.connect("vnc-error", lambda display, message: reported.append(message))
    assert until(lambda: page.initialized), page.status.get_text()
    server.stop()
    assert until(ended(label)), page.status.get_text()
    assert len(reported) == 1 and page.status.get_visible(), reported
    assert page.status.get_text() == reported[0], (page.status.get_text(), reported)
    assert page.get_parent() is w.nbConsole, "the tab closed as if the end were clean"
elif scenario == "closing-the-tab-closes-the-connection":
    server = Server()
    page, label = open_desk(server)
    assert until(lambda: page.initialized), page.status.get_text()
    assert not server.said("Connections: closed")
    label.close_tab(None)
    assert until(lambda: server.said("Connections: closed")), "the connection outlived its tab"
    server.stop()
elif scenario == "a-server-gtk-vnc-cannot-log-in-to":
    # RA2 is TigerVNC's own, and gtk-vnc disconnects without an error.
    server = Server("-SecurityTypes", "RA2")
    page, label = open_desk(server)
    assert until(ended(label)), page.status.get_text()
    text = page.status.get_text()
    assert text.startswith("Disconnected before the desktop was shown") and "security types" in text, text
    assert page.get_parent() is w.nbConsole, "the tab closed as if the end were clean"
    server.stop()
elif scenario == "the-desktop-gets-every-key-while-it-has-the-keyboard":
    server = Server()
    helper = os.path.join(os.getcwd(), "tests", "helpers", "remote_key_logger.py")
    logger = subprocess.Popen([sys.executable, helper], env=dict(os.environ, DISPLAY=server.display),
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                              preexec_fn=dies_with_us)
    assert logger.stdout.readline().strip() == "ready"
    os.set_blocking(logger.stdout.fileno(), False)
    typed = []

    def remote():
        typed.extend(line.strip() for line in logger.stdout.readlines())
        return typed

    w.addTab(w.nbConsole, app.Host("", "shell"))
    page, label = open_desk(server)
    assert until(lambda: page.initialized), page.status.get_text()
    assert w.wMain.get_focus() is page.display
    # Ctrl+W is GCM's Close console and Ctrl+Tab its Next console. With the keyboard in
    # the desktop, the desktop gets both.
    showing = w.nbConsole.get_current_page()
    press(Gdk.KEY_w)
    press(Gdk.KEY_Tab)
    assert until(lambda: "Tab control" in remote()), remote()
    assert "w control" in remote(), remote()
    assert page.get_parent() is w.nbConsole, "Ctrl+W closed the tab instead"
    assert w.nbConsole.get_current_page() == showing, "Ctrl+Tab switched tabs instead"
    # With the keyboard on the notebook, as clicking a tab's label leaves it, they are
    # GCM's. The notebook has a Ctrl+Tab of its own, which GCM's comes before.
    w.nbConsole.grab_focus()
    pump(0.2)
    press(Gdk.KEY_Tab)
    assert w.nbConsole.get_current_page() != showing, "Ctrl+Tab did not switch tabs"
    w.nbConsole.set_current_page(w.nbConsole.page_num(page))
    w.nbConsole.grab_focus()
    pump(0.2)
    press(Gdk.KEY_w)
    assert page.get_parent() is None, "Ctrl+W left the tab open"
    pump(0.5)
    assert remote().count("w control") == 1 and remote().count("Tab control") == 1, remote()
    # Once the session has ended gtk-vnc leaves the keys, and they are GCM's again.
    page, label = open_desk(server)
    assert until(lambda: page.initialized), page.status.get_text()
    logger.kill()
    server.stop()
    assert until(ended(label)), page.status.get_text()
    assert w.wMain.get_focus() is page.display
    press(Gdk.KEY_w)
    assert page.get_parent() is None, "Ctrl+W did nothing in a tab that had ended"
    # Only a desktop gets a key first: in a terminal, Ctrl+W is still GCM's.
    shell = w.nbConsole.get_nth_page(w.nbConsole.get_n_pages() - 1)
    w.wMain.set_focus(app.page_terminal(shell))
    pump(0.2)
    press(Gdk.KEY_w)
    assert shell.get_parent() is None, "Ctrl+W in a terminal left its tab open"
elif scenario == "the-desktop-moves-with-its-tab":
    server = Server()
    w.addTab(w.nbConsole, app.Host("", "shell"))
    page, label = open_desk(server)
    assert until(lambda: page.initialized), page.status.get_text()
    remote = dict(os.environ, DISPLAY=server.display)
    subprocess.run(["xsetroot", "-solid", "#ff0000"], env=remote, check=True)
    assert until(lambda: on_screen(page.display) == (255, 0, 0)), on_screen(page.display)
    # Split with the desktop in use moves it into a pane of its own, still connected.
    application._on_action_split_horizontal(None, None)
    pump(0.5)
    assert page.get_parent() not in (None, w.nbConsole), page.get_parent()
    assert page.get_parent().get_tab_label(page) is label and label.is_active
    subprocess.run(["xsetroot", "-solid", "#0000ff"], env=remote, check=True)
    assert until(lambda: on_screen(page.display) == (0, 0, 255)), on_screen(page.display)
    server.stop()
else:
    raise SystemExit("no scenario " + scenario)
print("OK")
'''


def gtk_vnc_installed():
    try:
        import gi

        gi.require_version("GtkVnc", "2.0")
    except (ImportError, ValueError):
        return False
    return True


@pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"),
    reason="needs a display for real GTK",
)
@pytest.mark.skipif(
    not (shutil.which("Xtigervnc") and shutil.which("tigervncpasswd") and shutil.which("xsetroot")),
    reason="needs TigerVNC's server and tools, and xsetroot",
)
@pytest.mark.skipif(not gtk_vnc_installed(), reason="needs gtk-vnc's GObject bindings")
@pytest.mark.parametrize(
    "scenario",
    [
        "a-stored-password-connects",
        "gcm-asks-for-a-password-it-does-not-store",
        "cancelling-the-password-closes-the-connection",
        "a-wrong-password-says-why",
        "a-user-name-answers-a-server-that-asks-for-one",
        "the-server-going-away-ends-the-tab",
        "closing-the-tab-closes-the-connection",
        "a-server-gtk-vnc-cannot-log-in-to",
        "the-desktop-gets-every-key-while-it-has-the-keyboard",
        "the-desktop-moves-with-its-tab",
    ],
)
def test_a_vnc_host_against_a_real_server(scenario, tmp_path):
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT, scenario, str(tmp_path)],
        capture_output=True,
        text=True,
        cwd=REPO,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr[-3000:]
    assert "OK" in result.stdout
    assert glib_complaints(result.stderr) == []
