"""A host's commands after login go once its session has started, and what is typed into
its tab before then goes after them (#312).

Each scenario runs against real GTK and a real terminal, in a process of its own. The
session is a fake `ssh` that sets its terminal's modes as ssh does: canonical with echo
while it connects and asks about a host key, without echo while it reads a password, and
raw once the session has started. Each step it takes is a line in a log, with the time,
and each read is the bytes it got, so the order things arrived in is read back from it.
Keys are typed as key events through the window. Nothing reaches the network.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = r"""
import json, os, sys, tempfile, time
scenario = sys.argv[1]
root = tempfile.mkdtemp()
os.environ["HOME"] = root; sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk, Gdk, GLib, Vte
from gnome_connection_manager import app
from gnome_connection_manager.utils import afterlogin

app.conf.CONFIRM_ON_CLOSE_TAB = 0
app.conf.STARTUP_LOCAL = False
app.conf.CHECK_UPDATES = False
app.conf.AUTO_CLOSE_TAB = 0  # an ended tab stays, to be read
app.wMain = w = app.Wmain(application=None)
w.wMain.resize(1200, 800)
application = app.GcmApplication()
application._controller = w
LOG = os.path.join(root, "log")
PLAN = os.path.join(root, "plan")

# The session. Run directly, its name is ssh's, as /proc gives it, which is how GCM finds it.
FAKE = r'''
import json, os, sys, termios, time, tty
def note(kind, text=""):
    with open(%(log)r, "a") as log:
        log.write(json.dumps([time.monotonic(), kind, text]) + "\n")
def modes(on, off):
    attrs = termios.tcgetattr(0)
    attrs[3] = (attrs[3] | on) & ~off
    # As ssh's readpassphrase does: a question discards what was typed before it.
    termios.tcsetattr(0, termios.TCSAFLUSH, attrs)
cooked = termios.tcgetattr(0)
note("start", str(os.getpid()))
for step, *arg in json.load(open(%(plan)r)):
    arg = arg[0] if arg else None
    if step == "sleep":
        time.sleep(arg)
    elif step == "say":
        os.write(1, arg.encode())
    elif step == "ask":
        modes(termios.ECHO, 0)
        os.write(1, arg.encode())
        note("answer", os.read(0, 1024).decode())
    elif step == "secret":
        modes(0, termios.ECHO)
        os.write(1, arg.encode())
        secret = os.read(0, 1024).decode()
        modes(termios.ECHO, 0)
        os.write(1, b"\n")
        note("secret", secret)
    elif step == "raw":
        # As ssh enters its session: after what is written has gone, and keeping what
        # has been typed, which the session then reads.
        tty.setraw(0, termios.TCSADRAIN)
        note("raw")
    elif step == "cooked":
        termios.tcsetattr(0, termios.TCSADRAIN, cooked)
        note("cooked")
    elif step == "motd":
        for line in range(arg[0]):
            os.write(1, f"line {line}\r\n".encode())
            note("motd")
            time.sleep(arg[1])
    elif step == "dots":
        for _ in range(arg[0]):
            os.write(1, b".")
            note("dot")
            time.sleep(arg[1])
    elif step == "exit":
        sys.exit(arg)
    elif step == "session":
        while data := os.read(0, 1024):
            note("got", data.decode())
''' % {"log": LOG, "plan": PLAN}
FAKE_PY = os.path.join(root, "fake.py")
with open(FAKE_PY, "w") as out:
    out.write(FAKE)

def fake(name, body):
    path = os.path.join(root, name)
    with open(path, "w") as out:
        out.write(body)
    os.chmod(path, 0o755)
    return path

app.SSH_BIN = fake("ssh", f"#!{sys.executable}\n" + FAKE)

def pump(seconds=0.2):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        Gtk.main_iteration_do(False)
        time.sleep(0.005)

def until(done, seconds=10):
    end = time.monotonic() + seconds
    while not done() and time.monotonic() < end:
        pump(0.05)
    assert done(), "timed out"
    pump(0.3)  # and a little longer, for anything that should not follow

def log():
    if not os.path.exists(LOG):
        return []
    with open(LOG) as lines:
        return [json.loads(line) for line in lines]

def got():
    return "".join(text for _t, kind, text in log() if kind == "got")

def when(kind):
    return next(t for t, k, _text in log() if k == kind)

def text_of(kind):
    return next(text for _t, k, text in log() if k == kind)

def open_host(plan, commands="echo one", kind="ssh", password=""):
    with open(PLAN, "w") as out:
        json.dump(plan, out)
    host = app.Host("prod", "db-01", "", "10.9.9.9", "ops", password, "", "22", "", kind, commands)
    host.keep_alive = "0"
    host.commands_enabled = True
    opened = time.monotonic()
    w.addTab(w.nbConsole, host)
    pump(0.3)  # past addTab's own second look for the keyboard
    w.wMain.set_focus(terminal())
    return opened

def terminal():
    return app.page_terminal(w.nbConsole.get_nth_page(w.nbConsole.get_n_pages() - 1))

def label():
    page = w.nbConsole.get_nth_page(w.nbConsole.get_n_pages() - 1)
    return w.nbConsole.get_tab_label(page)

def screen():
    text = terminal().get_text_format(Vte.Format.TEXT)
    return text or ""

def press(keyval, state=0):
    keymap = Gdk.Keymap.get_for_display(Gdk.Display.get_default())
    keyboard = Gdk.Display.get_default().get_default_seat().get_keyboard()
    found, keys = keymap.get_entries_for_keyval(keyval)
    for kind in (Gdk.EventType.KEY_PRESS, Gdk.EventType.KEY_RELEASE):
        event = Gdk.Event.new(kind)
        event.key.window = w.wMain.get_window()
        event.key.time = Gdk.CURRENT_TIME
        event.key.state = state
        event.key.keyval = keyval
        if found:
            event.key.hardware_keycode, event.key.group = keys[0].keycode, keys[0].group
        event.set_device(keyboard)
        Gtk.main_do_event(event)
    pump(0.02)

def type_text(text):
    for ch in text:
        press(Gdk.KEY_Return if ch == "\n" else Gdk.unicode_to_keyval(ord(ch)))

def held():
    gate = getattr(terminal(), "commands_gate", None)
    return None if gate is None else len(gate.held)

SESSION = [["raw"], ["say", "Welcome\r\n$ "], ["session"]]

if scenario == "typed-while-connecting-goes-after-the-commands":
    open_host([["sleep", 1.0], *SESSION], commands="echo one\necho two")
    type_text("ls")
    press(Gdk.KEY_Page_Up, Gdk.ModifierType.SHIFT_MASK)  # scrolls, and is not held
    press(Gdk.KEY_Shift_L)  # nor is a modifier alone
    assert held() == 2, held()
    until(lambda: "ls" in got())
    assert got() == "echo one\recho two\rls", repr(got())
    text = screen()
    assert "ls" not in text[: text.index("Welcome")], text  # held, so never echoed early
    assert held() is None

elif scenario == "a-slow-login-is-waited-for":
    # Longer than the 3 s the commands used to wait. Typed then, the terminal would have
    # turned their Enter into a new line, and echoed them before the session.
    open_host([["sleep", 3.6], *SESSION])
    until(lambda: got())
    assert got() == "echo one\r", repr(got())
    assert when("got") - when("raw") >= afterlogin.QUIET, log()
    assert "echo one" not in screen()

elif scenario in ("a-host-key-question-is-answered-first", "a-question-that-echoes-is-answered-first"):
    if scenario == "a-host-key-question-is-answered-first":
        question = "Are you sure you want to continue connecting (yes/no/[fingerprint])? "
    else:
        question = "Passcode or option (1-3): "  # a server's, through keyboard-interactive
    opened = open_host([["sleep", 0.5], ["ask", question], ["sleep", 1.0], *SESSION])
    type_text("ls")  # before the question
    until(lambda: question in screen())
    pump(3.5 - (time.monotonic() - opened))  # where the commands used to answer it
    type_text("yes\n")
    until(lambda: any(kind == "answer" for _t, kind, _text in log()))
    type_text("pwd")  # once answered, held again
    until(lambda: "pwd" in got())
    assert text_of("answer") == "yes\n", log()
    assert got() == "echo one\rlspwd", repr(got())

elif scenario == "a-password-typed-at-its-prompt":
    open_host([["sleep", 0.4], ["secret", "ops@db-01's password: "], ["sleep", 1.0], *SESSION])
    type_text("ls")
    until(lambda: "password: " in screen())
    type_text("s3cret\n")
    until(lambda: any(kind == "secret" for _t, kind, _text in log()))
    type_text("pwd")
    until(lambda: "pwd" in got())
    assert text_of("secret") == "s3cret\n", log()
    assert got() == "echo one\rlspwd", repr(got())

elif scenario == "output-after-the-session-starts-is-waited-for":
    # A message of the day, a line every 0.1 s: the commands wait for it to end, and what
    # is typed meanwhile waits for them.
    # The fake reads nothing until it has printed it, so GCM's own typing is timed.
    typed = []
    send_data = w.send_data
    w.send_data = lambda v, data: typed.append(time.monotonic()) or send_data(v, data)
    open_host([["sleep", 0.3], ["raw"], ["motd", [8, 0.1]], ["say", "$ "], ["session"]])
    until(lambda: any(kind == "motd" for _t, kind, _text in log()))
    type_text("ls")
    until(lambda: "ls" in got())
    assert got() == "echo one\rls", repr(got())
    last = max(t for t, kind, _text in log() if kind == "motd")
    assert typed[0] - last >= afterlogin.QUIET, (typed, log())

elif scenario == "the-remote-prompt-before-the-commands":
    # A prompt shows, and output goes on after it: what is typed at it, Ctrl+C too, waits
    # for the commands, since the session has started.
    open_host([["sleep", 0.3], ["raw"], ["say", "$ "], ["dots", [6, 0.15]], ["session"]])
    until(lambda: any(kind == "dot" for _t, kind, _text in log()), 5)
    type_text("ls")
    press(Gdk.KEY_c, Gdk.ModifierType.CONTROL_MASK)
    assert held() == 3, held()
    until(lambda: "\x03" in got())
    assert got() == "echo one\rls\x03", repr(got())

elif scenario == "ctrl-c-ends-the-login":
    open_host([["sleep", 30], *SESSION])
    type_text("ls")
    press(Gdk.KEY_c, Gdk.ModifierType.CONTROL_MASK)
    until(lambda: not label().is_active, 5)
    assert getattr(terminal(), "commands_gate", None) is None
    assert getattr(terminal(), "commands_timer", None) is None
    pump(1.0)
    assert [kind for _t, kind, _text in log()] == ["start"], log()

elif scenario == "a-session-without-a-terminal-of-its-own":
    # As ssh -T has it: lines, and never raw. The commands go once GCM gives up waiting.
    afterlogin.GIVE_UP = 1.5
    opened = open_host([["sleep", 0.2], ["say", "Welcome\r\n"], ["session"]])
    type_text("ls")
    until(lambda: got())
    assert got() == "echo one\n", repr(got())  # a line, as the terminal is canonical
    assert when("got") - opened >= 1.5, log()
    pump(0.3)
    assert held() is None
    type_text("\n")  # the held ls was typed after the commands, and ends its line now
    until(lambda: got() == "echo one\nls\n")

elif scenario == "a-program-gcm-does-not-find":
    # Its name is not ssh's, so the commands go as they always went: 3 s after the spawn.
    app.SSH_BIN = fake("connect", f"#!/bin/sh\nexec {sys.executable} {FAKE_PY}\n")
    opened = open_host([["sleep", 0.5], ["raw"], ["say", "Welcome\r\n"], ["session"]])
    type_text("ls")
    until(lambda: "ls" in got())
    assert got() == "echo one\rls", repr(got())
    assert when("got") - opened >= afterlogin.FIND_WAIT - 0.1, log()

elif scenario == "under-ssh-expect":
    # A host with a stored password runs the script as it ships, its ssh the fake.
    text = open(app.SSH_COMMAND).read()
    assert text.count('"/usr/bin/ssh"') == 1
    app.SSH_COMMAND = fake("ssh.expect", text.replace('"/usr/bin/ssh"', '"%s"' % app.SSH_BIN))
    open_host([["sleep", 0.5], ["secret", "ops@db-01's password: "], *SESSION], password="pw")
    type_text("ls")
    until(lambda: "ls" in got())
    assert text_of("secret") == "pw\n", log()
    assert got() == "echo one\rls", repr(got())

elif scenario == "under-the-relay":
    app.conf.RAW_SESSION_LOG = 1
    app.conf.LOG_PATH = os.path.join(root, "logs")
    open_host([["sleep", 1.0], *SESSION])
    type_text("ls")
    until(lambda: "ls" in got())
    assert got() == "echo one\rls", repr(got())
    assert terminal().raw_path, "not under the relay"

elif scenario == "the-session-ends-first":
    open_host([["sleep", 0.5], ["exit", 255]])
    type_text("ls")
    until(lambda: not label().is_active, 5)
    assert getattr(terminal(), "commands_gate", None) is None
    assert getattr(terminal(), "commands_timer", None) is None
    type_text("x")  # nothing waits any more
    assert held() is None
    pump(3.5)
    assert [kind for _t, kind, _text in log()] == ["start"], log()

elif scenario == "closing-the-tab-while-waiting":
    open_host([["sleep", 30], *SESSION])
    type_text("ls")
    v = terminal()
    label().close_tab(v.get_parent())
    pump(1.0)
    assert w.nbConsole.get_n_pages() == 0
    assert getattr(v, "commands_gate", None) is None
    assert getattr(v, "commands_timer", None) is None

elif scenario == "the-waits-between-commands":
    open_host([["sleep", 0.6], *SESSION], commands="cd /srv\n##D=600\nmake")
    type_text("ls")
    until(lambda: got())
    type_text("x")  # while the second group waits
    assert held() == 3, held()
    until(lambda: got().endswith("lsx"))
    assert got() == "cd /srv\rmake\rlsx", repr(got())
    reads = [(t, text) for t, kind, text in log() if kind == "got"]
    second = next(t for t, text in reads if text.startswith("make"))
    assert second - reads[0][0] >= 0.55, reads

elif scenario == "a-question-of-sshs-own-in-the-session":
    # UpdateHostKeys=ask: ssh leaves raw mode to ask, after the session has started.
    question = "Accept updated hostkeys? (yes/no): "
    opened = open_host(
        [["sleep", 0.3], ["raw"], ["say", "Welcome\r\n"], ["cooked"], ["ask", question], *SESSION]
    )
    until(lambda: question in screen())
    pump(3.5 - (time.monotonic() - opened))
    type_text("yes\n")
    until(lambda: got())
    assert text_of("answer") == "yes\n", log()
    assert got() == "echo one\r", repr(got())

elif scenario == "reconnect-while-waiting-sends-nothing":
    # Reconnect sends no commands after login, and what was held goes with the session.
    open_host([["sleep", 1.0], *SESSION])
    type_text("ls")
    application._on_action_console_reconnect(None, None)
    until(lambda: [kind for _t, kind, _text in log()].count("raw") == 1)
    assert held() is None
    pump(3.5)
    assert got() == "", repr(got())

elif scenario == "a-session-that-ends-between-commands":
    # Its commands still to come are not typed into the next.
    open_host([["sleep", 0.5], *SESSION], commands="one\n##D=1500\ntwo")
    until(lambda: "one" in got())
    os.kill(int(text_of("start")), 9)
    until(lambda: not label().is_active, 5)
    application._on_action_console_reconnect(None, None)
    until(lambda: [kind for _t, kind, _text in log()].count("raw") == 2)
    pump(2.0)
    assert got() == "one\r", repr(got())

elif scenario == "telnet-keeps-its-wait":
    # GCM does not follow telnet's session, and types its commands at 3 s, as it always did.
    app.TEL_BIN = fake("telnet", f"#!{sys.executable}\n" + FAKE)
    opened = open_host([*SESSION], kind="telnet")
    type_text("ls")
    assert held() is None
    until(lambda: "echo one" in got())
    assert got() == "lsecho one\r", repr(got())
    assert when("got") < opened + 1, log()

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
        "typed-while-connecting-goes-after-the-commands",
        "a-slow-login-is-waited-for",
        "a-host-key-question-is-answered-first",
        "a-question-that-echoes-is-answered-first",
        "a-password-typed-at-its-prompt",
        "output-after-the-session-starts-is-waited-for",
        "the-remote-prompt-before-the-commands",
        "ctrl-c-ends-the-login",
        "a-session-without-a-terminal-of-its-own",
        "a-program-gcm-does-not-find",
        "under-ssh-expect",
        "under-the-relay",
        "the-session-ends-first",
        "closing-the-tab-while-waiting",
        "the-waits-between-commands",
        "a-question-of-sshs-own-in-the-session",
        "reconnect-while-waiting-sends-nothing",
        "a-session-that-ends-between-commands",
        "telnet-keeps-its-wait",
    ],
)
def test_commands_after_login_against_real_gtk(scenario):
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
    # A signal handler's exception is printed and the scenario carries on.
    assert "Traceback" not in result.stderr, result.stderr[-3000:]


class Terminal:
    """A terminal whose session addTab built, as far as the Reconnect key reads it."""

    command = ("ssh", ["ssh", "db-01"], None)

    def __init__(self):
        tab = type("Tab", (), {"mark_tab_as_active": lambda _tab: None})()
        notebook = type("Notebook", (), {"get_tab_label": lambda _nb, _page: tab})()
        self.page = type("Page", (), {"get_parent": lambda _page: notebook})()

    def get_parent(self):
        return self.page


def test_the_reconnect_key_stops_the_wait(app_module, monkeypatch):
    """on_terminal_keypress starts the session again itself where no accelerator took the
    key first, and Reconnect sends no commands after login: nothing waits for them."""
    from gnome_connection_manager.utils import afterlogin

    monkeypatch.setattr(app_module, "vte_run", lambda *_args: None)
    monkeypatch.setattr(app_module, "get_key_name", lambda _event: "CTRL+N")
    monkeypatch.setattr(app_module, "shortcuts", {"CTRL+N": app_module._CONSOLE_RECONNECT})
    monkeypatch.setattr(app_module, "custom_keys", {})
    removed: list[int] = []
    monkeypatch.setattr(app_module.GLib, "source_remove", removed.append)
    terminal = Terminal()
    terminal.commands_gate = afterlogin.Gate("ssh", [(0, "echo one")], 0.0)
    terminal.commands_timer = 7

    assert object.__new__(app_module.Wmain).on_terminal_keypress(terminal, object()) is True

    assert terminal.commands_gate is None
    assert removed == [7]
