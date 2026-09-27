"""RDP hosts, opened through FreeRDP in a window of its own (#225).

A tab runs FreeRDP's client, xfreerdp3 or xfreerdp, and shows what it prints: the
certificate question, the prompts, and why a connection failed. It ends with FreeRDP's
status. A stored password is typed at FreeRDP's prompt by ssh.expect, whose own tests
cover each prompt. These cover what GCM gives FreeRDP and the script.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import types
from pathlib import Path
from xml.etree import ElementTree

import pytest

REPO = Path(__file__).resolve().parents[1]


def rdp_host(app_module, **fields):
    host = app_module.Host("Work", "build box", "", "win.example.test", "me", "not-a-password")
    host.type, host.port = "rdp", "3389"
    for name, value in fields.items():
        setattr(host, name, value)
    return host


# -- which client ------------------------------------------------------------


@pytest.mark.parametrize(
    ("installed", "chosen"),
    [
        (("xfreerdp3", "xfreerdp"), "xfreerdp3"),
        (("xfreerdp",), "xfreerdp"),
        (("xfreerdp3",), "xfreerdp3"),
        ((), None),
    ],
)
def test_the_newest_freerdp_installed_is_used(app_module, monkeypatch, installed, chosen):
    """Ubuntu 24.04 installs FreeRDP 3 and 2 side by side, as xfreerdp3 and xfreerdp."""
    monkeypatch.setattr(
        app_module.shutil, "which", lambda name: f"/usr/bin/{name}" if name in installed else None
    )

    assert app_module.rdp_client() == chosen


# -- what FreeRDP is given ---------------------------------------------------


def test_freerdp_is_given_the_host_its_port_and_its_user(app_module):
    host = rdp_host(app_module, port="3390", user="CORP\\me")

    assert app_module.rdp_arguments(host) == ["/v:win.example.test", "/port:3390", "/u:CORP\\me"]


def test_extra_arguments_follow_as_the_shell_would_split_them(app_module):
    host = rdp_host(app_module, extra_params="/size:1280x800 '/t:Build box' +clipboard")

    assert app_module.rdp_arguments(host)[3:] == [
        "/size:1280x800",
        "/t:Build box",
        "+clipboard",
    ]


def test_without_a_user_freerdp_asks_for_one(app_module):
    host = rdp_host(app_module, user="", password="")

    assert app_module.rdp_arguments(host) == ["/v:win.example.test", "/port:3389"]


def test_the_password_is_never_among_freerdps_arguments(app_module):
    """FreeRDP 3 masks /p: in its own argv, measured, but not in its parent's, and a
    session runs under relay.py when raw recording or OSC 52 is on."""
    args = app_module.rdp_arguments(rdp_host(app_module))

    assert not [arg for arg in args if "not-a-password" in arg or arg.startswith("/p:")]


# -- the host dialog ---------------------------------------------------------


class Control:
    def __init__(self):
        self.sensitive = None
        self.text = None
        self.active = False

    def set_sensitive(self, value):
        self.sensitive = value

    def get_active(self):
        return self.active

    def set_text(self, text):
        self.text = text


class Grid:
    def __init__(self):
        self.visible = None

    def hide(self):
        self.visible = False

    def show(self):
        self.visible = True


SSH_ONLY = (
    "txtKeepAlive",
    "chkKeepAlive",
    "chkX11",
    "chkAgent",
    "chkCompression",
    "txtCompressionLevel",
    "txtPrivateKey",
    "btnBrowse",
)


def choose_type(app_module, ctype, *, commands_ticked=False):
    dialog = app_module.Whost.__new__(app_module.Whost)
    controls = {
        name: Control()
        for name in (
            *SSH_ONLY,
            "txtPort",
            "txtUser",
            "txtPassword",
            "txtHost",
            "txtExtraParams",
            "chkCommands",
            "txtCommands",
        )
    }
    controls["chkCommands"].active = commands_ticked
    for name, widget in controls.items():
        setattr(dialog, name, widget)
    grid = Grid()
    dialog.get_widget = lambda name: grid if name == "tunnelGrid" else controls.get(name)

    dialog.on_cmbType_changed(types.SimpleNamespace(get_active_text=lambda: ctype))
    return controls, grid


@pytest.mark.parametrize(("ctype", "port"), [("ssh", "22"), ("telnet", "23"), ("rdp", "3389")])
def test_choosing_a_type_offers_its_port(app_module, ctype, port):
    controls, _ = choose_type(app_module, ctype)

    assert controls["txtPort"].text == port


def test_an_rdp_host_is_offered_what_telnet_is(app_module):
    """No port forwarding tab, and the SSH-only controls greyed, as for Telnet. The
    host, port, user, password and extra arguments all apply."""
    controls, grid = choose_type(app_module, "rdp")

    assert grid.visible is False
    assert [name for name in SSH_ONLY if controls[name].sensitive is not False] == []
    for name in ("txtPort", "txtUser", "txtPassword", "txtHost", "txtExtraParams"):
        assert controls[name].sensitive is True, name


@pytest.mark.parametrize(
    ("ctype", "ticked", "box", "text"),
    [
        ("rdp", True, False, False),
        ("ssh", True, True, True),
        ("telnet", False, True, False),
    ],
)
def test_the_dialog_greys_an_rdp_hosts_commands(app_module, ctype, ticked, box, text):
    """An RDP host sends none, whatever the box says. Another type offers the box, and
    its text follows the tick, as it did."""
    controls, _ = choose_type(app_module, ctype, commands_ticked=ticked)

    assert controls["chkCommands"].sensitive is box
    assert controls["txtCommands"].sensitive is text


def test_an_rdp_host_sends_no_commands(app_module):
    """They would be typed into FreeRDP's questions: its certificate question, or the
    password prompt."""
    host = rdp_host(app_module, commands="dir", commands_enabled=True)
    assert app_module.host_sends_commands(host) is False

    host.type = "ssh"
    assert app_module.host_sends_commands(host) is True


def test_the_type_list_offers_rdp_untranslated():
    """The dialog saves the type as the list shows it, and addTab compares that text:
    a translation of rdp would be a type nothing opens."""
    glade = ElementTree.parse(REPO / "data" / "ui" / "gnome-connection-manager.glade")
    combo = next(o for o in glade.iter("object") if o.get("id") == "cmbType")
    items = {item.get("id"): item for item in combo.iter("item")}

    assert list(items) == ["ssh", "telnet", "rdp", "local"]
    assert items["rdp"].text == "rdp"
    assert items["rdp"].get("translatable") != "yes"


# -- against real GTK --------------------------------------------------------

# A first connection, as FreeRDP 3.31 makes one: the certificate question, then a domain
# and a password, the password with echo off. It prints its arguments first, and reports
# what it was given rather than the password.
_FAKE_XFREERDP = r"""#!/bin/sh
printf 'arguments:'; printf ' [%s]' "$@"; printf '\n'
printf "Certificate details for win.example.test:3389 (RDP-Server):\n"
printf "\tThumbprint:  GCM:TEST:THUMBPRINT\n"
printf "Do you trust the above certificate? (Y/T/N) "
read answer
printf "Domain:          "
read domain
stty -echo
printf "Password:        "
read pw
stty echo
printf "\nconnected (answer %s, domain [%s], password %s)\n" "$answer" "$domain" \
    "$([ "$pw" = not-a-password ] && echo right || echo wrong)"
"""

_SCRIPT = r"""
import os, sys, tempfile, time
scenario = sys.argv[1]
os.environ["HOME"] = tempfile.mkdtemp(); sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk, Vte
from gnome_connection_manager import app

app.conf.STARTUP_LOCAL = False
app.conf.AUTO_CLOSE_TAB = 0
shown_messages = []
app.msgbox = lambda text, *args, **kwargs: shown_messages.append(text)

def pump(until, what, limit=30):
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        Gtk.main_iteration_do(False)
        if until():
            return
        time.sleep(0.005)
    raise AssertionError("timed out waiting for " + what)

def settle(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        Gtk.main_iteration_do(False)
        time.sleep(0.005)

app.wMain = app.Wmain(application=None)
nb = app.wMain.nbConsole
host = app.Host("Work", "build box", "", "win.example.test", "me", "not-a-password")
host.type, host.port = "rdp", "3389"

def whole(v):
    # Every row, not the visible ones: a tab can be two rows tall on Xvfb.
    text, _ = v.get_text_range_format(Vte.Format.TEXT, 0, 0, v.get_cursor_position()[1], 10000)
    return text or ""

def in_order(shown, *parts):
    at = 0
    for part in parts:
        found = shown.find(part, at)
        assert found >= 0, "the tab lacks %r after %r: %r" % (part, shown[:at][-40:], shown)
        at = found + len(part)

if scenario == "a-stored-password-is-typed-at-the-prompt":
    app.wMain.addTab(nb, host)
    v = app.page_terminal(nb.get_nth_page(nb.get_n_pages() - 1))
    assert v.command == (
        app.SSH_COMMAND,
        [app.SSH_COMMAND, "rdp", "xfreerdp3", "/v:win.example.test", "/port:3389", "/u:me"],
        "not-a-password",
    ), v.command
    pump(lambda: "(Y/T/N) " in whole(v), "the certificate question")
    # The question is the user's (#216): a second is ample for an answer to show.
    settle(1)
    assert "Domain:" not in whole(v), whole(v)
    app.vte_feed(v, "Y\r")
    pump(lambda: "connected" in whole(v), "the login to finish")
    shown = whole(v)
    in_order(
        shown,
        "arguments: [/v:win.example.test] [/port:3389] [/u:me]",
        "Certificate details for win.example.test:3389 (RDP-Server):",
        "Do you trust the above certificate? (Y/T/N) Y",
        "Domain:",
        "Password:",
        "connected (answer Y, domain [], password right)",
    )
    assert "not-a-password" not in shown, shown
elif scenario == "without-a-stored-password-freerdp-asks":
    host.password = ""
    app.wMain.addTab(nb, host)
    v = app.page_terminal(nb.get_nth_page(nb.get_n_pages() - 1))
    assert v.command == (
        "xfreerdp3", ["xfreerdp3", "/v:win.example.test", "/port:3389", "/u:me"], ""
    ), v.command
    for prompt, answer in (("(Y/T/N) ", "T\r"), ("Domain:", "\r"), ("Password:", "not-a-password\r")):
        pump(lambda: whole(v).rstrip().endswith(prompt.rstrip()), prompt)
        app.vte_feed(v, answer)
    pump(lambda: "connected" in whole(v), "the login to finish")
    in_order(whole(v), "(Y/T/N) T", "connected (answer T, domain [], password right)")
elif scenario == "a-password-without-a-user-is-left-to-freerdp":
    # FreeRDP would ask for the user first, and the script has no answer for that.
    host.user = ""
    app.wMain.addTab(nb, host)
    v = app.page_terminal(nb.get_nth_page(nb.get_n_pages() - 1))
    assert v.command == ("xfreerdp3", ["xfreerdp3", "/v:win.example.test", "/port:3389"], ""), (
        v.command
    )
elif scenario == "without-freerdp-a-message-and-no-tab":
    app.RDP_CLIENTS = ("gcm-test-no-such-client",)
    before = nb.get_n_pages()
    app.wMain.addTab(nb, host)
    settle(0.3)
    assert nb.get_n_pages() == before, "a tab opened with nothing to run"
    assert shown_messages == [
        app._("Neither xfreerdp3 nor xfreerdp was found. Install FreeRDP to open RDP hosts.")
    ], shown_messages
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
        "a-stored-password-is-typed-at-the-prompt",
        "without-a-stored-password-freerdp-asks",
        "a-password-without-a-user-is-left-to-freerdp",
        "without-freerdp-a-message-and-no-tab",
    ],
)
def test_an_rdp_host_against_real_gtk(tmp_path, scenario):
    pytest.importorskip("gi", reason="PyGObject not available")
    if shutil.which("expect") is None:
        pytest.skip("needs expect")
    fake = tmp_path / "xfreerdp3"
    fake.write_text(_FAKE_XFREERDP)
    fake.chmod(0o755)
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT, scenario],
        capture_output=True,
        text=True,
        cwd=REPO,
        env={**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}"},
        timeout=120,
    )

    assert result.returncode == 0, result.stderr[-3000:]
    assert "OK" in result.stdout
