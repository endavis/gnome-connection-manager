"""Reconnecting a dropped session, when Preferences asks for it (#239).

Each scenario runs against real GTK and real terminals, in a process of its own. The
session is a fake `ssh`, `telnet` or `xfreerdp3`, which takes what each connection does
from a queue, one line per attempt: how long it stays up, the status it ends with, and
the line the real client printed ending so, as measured for #239. `wait` stays up until
a status is typed into its tab. Every attempt marks a file, which is what is counted.
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
root = tempfile.mkdtemp()
os.environ["HOME"] = root; sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk, Gdk, GLib, Vte
from gnome_connection_manager import app

app.conf.CONFIRM_ON_CLOSE_TAB = 0
app.conf.STARTUP_LOCAL = False  # only the tabs each scenario opens
app.conf.AUTO_CLOSE_TAB = 0  # an ended tab stays, to be read
DEFAULT_ATTEMPTS = app.conf.RECONNECT_ATTEMPTS
app.conf.RECONNECT_ATTEMPTS = 3
app.RECONNECT_DELAY = 1
app.wMain = w = app.Wmain(application=None)
w.wMain.resize(1200, 800)
application = app.GcmApplication()
application._controller = w
shown = []
app.msgbox = lambda text, *args, **kwargs: shown.append(text)
MARKS = os.path.join(root, "marks")
QUEUE = os.path.join(root, "queue")
bin_dir = os.path.join(root, "bin")
os.makedirs(bin_dir)
os.environ["PATH"] = bin_dir + os.pathsep + os.environ["PATH"]

def pump(seconds=0.2):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        Gtk.main_iteration_do(False)
        time.sleep(0.005)

def until(done, seconds=15):
    end = time.monotonic() + seconds
    while not done() and time.monotonic() < end:
        pump(0.05)

def marks():
    return open(MARKS).read().splitlines() if os.path.exists(MARKS) else []

def attempts():
    return marks().count("attempt")

FAKE = f"""#!/bin/sh
echo attempt >> {MARKS}
line=$(head -n 1 {QUEUE})
tail -n +2 {QUEUE} > {QUEUE}.next; mv {QUEUE}.next {QUEUE}
[ -z "$line" ] && line="wait 0"
set -- $line
up=$1; status=$2; shift 2
echo "session up"
if [ "$up" = wait ]; then read code; exit "$code"; fi
sleep "$up"
printf '%s\\n' "$*"
exit "$status"
"""
for name in ("ssh", "telnet", "xfreerdp3"):
    path = os.path.join(bin_dir, name)
    with open(path, "w") as out:
        out.write(FAKE)
    os.chmod(path, 0o755)
app.SSH_BIN = os.path.join(bin_dir, "ssh")
app.TEL_BIN = os.path.join(bin_dir, "telnet")

DROP = "255 Connection to 10.9.9.9 closed by remote host."
REFUSED_CONNECTION = "0 255 ssh: connect to host 10.9.9.9 port 22: Connection refused"

def queue(*lines):
    with open(QUEUE, "w") as out:
        out.write("".join(line + "\n" for line in lines))

def open_host(kind="ssh", name="db-01", before=""):
    host = app.Host("prod", name, "", "10.9.9.9", "ops", "", "", "22", "", kind)
    host.before_command = before
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

def key(page, keyval):
    """A key typed into the page's terminal, through the window, as GTK delivers one."""
    w.wMain.set_focus(terminal(page))
    keymap = Gdk.Keymap.get_for_display(Gdk.Display.get_default())
    keyboard = Gdk.Display.get_default().get_default_seat().get_keyboard()
    for kind in (Gdk.EventType.KEY_PRESS, Gdk.EventType.KEY_RELEASE):
        event = Gdk.Event.new(kind)
        event.key.window = w.wMain.get_window()
        event.key.time = Gdk.CURRENT_TIME
        event.key.keyval = keyval
        found, keys = keymap.get_entries_for_keyval(keyval)
        event.key.hardware_keycode, event.key.group = keys[0].keycode, keys[0].group
        # As GDK sets it under X11, measured with real input for #239: never, Shift and
        # Control included.
        event.key.is_modifier = False
        event.set_device(keyboard)
        Gtk.main_do_event(event)
    pump(0.1)

if scenario == "off-by-default":
    app.conf.RECONNECT_ATTEMPTS = DEFAULT_ATTEMPTS
    queue("0.2 " + DROP)
    open_host()
    [page] = pages()
    until(lambda: not label(page).is_active)
    pump(2.5)
    assert attempts() == 1, marks()
    assert "Reconnecting" not in screen(page)

elif scenario == "a-dropped-session-is-reconnected":
    queue("0.2 " + DROP)
    open_host()
    [page] = pages()
    until(lambda: "Reconnecting" in screen(page))
    assert "Reconnecting in 1 s, attempt 1 of 3. Press a key to stop." in screen(page), screen(page)
    assert not label(page).is_active  # shown as ended while it counts down
    until(lambda: attempts() == 2)
    pump(0.5)
    assert attempts() == 2 and label(page).is_active, marks()

elif scenario in ("an-exit-is-not-reconnected", "ssh-escape-is-not-reconnected", "telnet-is-never-reconnected"):
    ending, kind = {
        "an-exit-is-not-reconnected": ("0.2 0 Connection to 10.9.9.9 closed.", "ssh"),
        "ssh-escape-is-not-reconnected": ("0.2 255 Connection to 10.9.9.9 closed.", "ssh"),
        "telnet-is-never-reconnected": ("0.2 0 Connection closed by foreign host.", "telnet"),
    }[scenario]
    queue(ending)
    open_host(kind)
    [page] = pages()
    until(lambda: not label(page).is_active)
    pump(2.5)
    assert attempts() == 1, marks()
    assert "Reconnecting" not in screen(page), screen(page)

elif scenario == "an-rdp-session-that-dropped":
    queue("0.2 147 Network disconnect!")
    open_host("rdp")
    until(lambda: attempts() == 2)
    assert attempts() == 2, marks()

elif scenario == "a-refused-login-ends-the-attempts":
    queue("0.2 " + DROP, "0 255 ops@10.9.9.9: Permission denied (publickey).")
    open_host()
    [page] = pages()
    until(lambda: attempts() == 2)
    until(lambda: not label(page).is_active)
    pump(2.5)
    assert attempts() == 2, marks()
    assert not label(page).is_active

elif scenario == "failures-to-connect-use-up-the-attempts":
    queue("0.2 " + DROP, REFUSED_CONNECTION, REFUSED_CONNECTION, REFUSED_CONNECTION)
    open_host()
    w.addTab(w.nbConsole, "local")  # in sight instead, so the first tab can be marked
    pump(0.5)
    page = pages()[0]
    w.nbConsole.set_current_page(1)
    until(lambda: attempts() == 3)
    assert not label(page).needs_attention  # not while attempts remain
    until(lambda: attempts() == 4)
    until(lambda: label(page).needs_attention, 5)
    pump(2.0)
    assert attempts() == 4, marks()
    assert label(page).needs_attention and not label(page).is_active

elif scenario == "close-console-waits-for-the-last-attempt":
    app.conf.AUTO_CLOSE_TAB = 1  # Always
    queue("0.2 " + DROP, REFUSED_CONNECTION)
    app.conf.RECONNECT_ATTEMPTS = 1
    open_host()
    [page] = pages()
    # Asked during the countdown: once the attempt starts, it fails and closes the tab
    # within one pump, so asking after it raced that close.
    until(lambda: pages() == [] or "Reconnecting" in screen(page))
    assert pages() == [page], marks()  # kept through the drop, to reconnect in
    until(lambda: pages() == [], 5)
    assert pages() == [] and attempts() == 2, marks()

elif scenario == "a-key-stops-the-countdown":
    app.RECONNECT_DELAY = 3
    queue("0.2 " + DROP)
    open_host()
    [page] = pages()
    until(lambda: "Reconnecting" in screen(page))
    for modifier in (Gdk.KEY_Shift_L, Gdk.KEY_Control_R, Gdk.KEY_Alt_L, Gdk.KEY_Super_L):
        key(page, modifier)  # alone, on its way to Alt+Tab, say
        assert terminal(page).reconnect_pending is not None, Gdk.keyval_name(modifier)
    key(page, Gdk.KEY_a)
    assert "Reconnecting stopped." in screen(page), screen(page)
    pump(4.0)
    assert attempts() == 1, marks()
    assert not label(page).is_active

elif scenario == "close-console-closes-a-tab-stopped-by-a-key":
    app.conf.AUTO_CLOSE_TAB = 1  # Always
    app.RECONNECT_DELAY = 3
    queue("0.2 " + DROP)
    open_host()
    [page] = pages()
    until(lambda: "Reconnecting" in screen(page))
    assert pages() == [page]  # kept while it counts down
    key(page, Gdk.KEY_a)  # which ends the attempts as running out of them does
    until(lambda: pages() == [], 2)
    assert pages() == [] and attempts() == 1, marks()

elif scenario == "closing-the-tab-stops-the-countdown":
    app.RECONNECT_DELAY = 2
    queue("0.2 " + DROP)
    open_host()
    [page] = pages()
    until(lambda: "Reconnecting" in screen(page))
    reconnected = []
    reconnect = w.reconnect
    w.reconnect = lambda terminal, tab: (reconnected.append(tab), reconnect(terminal, tab))
    label(page).close_tab(page)
    pump(3.5)
    # Counted as well as the attempts: a spawn in a destroyed terminal fails without a
    # word, so a countdown that carried on after its tab would not show in them.
    assert reconnected == [] and attempts() == 1 and pages() == [], marks()

elif scenario == "reconnect-during-the-countdown":
    app.RECONNECT_DELAY = 3
    queue("0.2 " + DROP)
    open_host()
    [page] = pages()
    until(lambda: "Reconnecting" in screen(page))
    application._on_action_console_reconnect(None, None)
    until(lambda: attempts() == 2)
    pump(4.0)  # past where the countdown would have ended
    assert attempts() == 2, marks()

elif scenario == "a-drop-after-a-while-starts-the-count-over":
    app.conf.RECONNECT_ATTEMPTS = 1
    app.RECONNECT_ESTABLISHED = 1.0
    queue("0.2 " + DROP, "1.5 " + DROP, REFUSED_CONNECTION)
    open_host()
    [page] = pages()
    until(lambda: attempts() == 3)
    until(lambda: not label(page).is_active and terminal(page).reconnect_pending is None)
    pump(2.5)
    assert attempts() == 3, marks()

elif scenario == "a-quick-drop-uses-up-an-attempt":
    app.conf.RECONNECT_ATTEMPTS = 2
    app.RECONNECT_ESTABLISHED = 30
    queue("0.2 " + DROP, "0.2 " + DROP, "0.2 " + DROP, "0.2 " + DROP)
    open_host()
    until(lambda: attempts() == 3)
    pump(3.5)
    assert attempts() == 3, marks()

elif scenario == "an-exit-soon-after-a-reconnect-is-final":
    # Logged in again and out before RECONNECT_ESTABLISHED: an end, not a failure.
    queue("0.2 " + DROP, "0.2 0 logout")
    open_host()
    [page] = pages()
    until(lambda: attempts() == 2)
    until(lambda: not label(page).is_active)
    pump(2.5)
    assert attempts() == 2, marks()
    assert terminal(page).reconnect_pending is None
    assert screen(page).count("Reconnecting in") == 1, screen(page)

elif scenario == "the-command-before-runs-again":
    queue("0.2 " + DROP)
    open_host(before=f"echo before >> {MARKS}")
    until(lambda: attempts() == 2)
    assert marks() == ["before", "attempt", "before", "attempt"], marks()

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
        "off-by-default",
        "a-dropped-session-is-reconnected",
        "an-exit-is-not-reconnected",
        "ssh-escape-is-not-reconnected",
        "telnet-is-never-reconnected",
        "an-rdp-session-that-dropped",
        "a-refused-login-ends-the-attempts",
        "failures-to-connect-use-up-the-attempts",
        "close-console-waits-for-the-last-attempt",
        "a-key-stops-the-countdown",
        "close-console-closes-a-tab-stopped-by-a-key",
        "closing-the-tab-stops-the-countdown",
        "reconnect-during-the-countdown",
        "a-drop-after-a-while-starts-the-count-over",
        "a-quick-drop-uses-up-an-attempt",
        "an-exit-soon-after-a-reconnect-is-final",
        "the-command-before-runs-again",
    ],
)
def test_reconnecting_a_dropped_session_against_real_gtk(scenario):
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
    # A timer left running after its tab closed raised from its callback, which GLib
    # prints and carries on from.
    assert "Traceback" not in result.stderr, result.stderr[-3000:]
