"""Connection types behind a registry (#228).

Each kind of host is a class in `utils/connections.py`, and what used to compare
`host.type` with a name asks the type instead. These pin how a host's type is found,
what the host dialog asks of each type, and the command each builds, without a display.
Against real GTK, they check that the dialog lists the registry's types and that `addTab`
opens a host as its type says.

When the registry replaced the branches, the command `addTab` built was recorded for a
matrix of hosts before and after and came out the same. That comparison is in the pull
request; the tests below pin its parts.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from gnome_connection_manager.utils import connections
from gnome_connection_manager.utils.hosts import Host

REPO = Path(__file__).resolve().parents[1]
PROGRAMS = connections.Programs(
    expect="/gcm/ssh.expect", username="localme", ssh="ssh", telnet="telnet"
)
SSH, TELNET, RDP, LOCAL = connections.SSH, connections.TELNET, connections.RDP, connections.LOCAL


def host(ctype="ssh", address="example.test", user="me", password="", **fields):
    record = Host("Work", "box", "", address, user, password)
    record.type, record.port = ctype, "2222"
    settings = {
        "keep_alive": "0",
        "tunnel": [""],
        "x11": False,
        "agent": False,
        "compression": False,
        "compressionLevel": "",
        "private_key": "",
        "extra_params": "",
        **fields,
    }
    for name, value in settings.items():
        setattr(record, name, value)
    return record


# -- the registry ------------------------------------------------------------


def test_the_types_in_the_order_the_dialog_offers_them():
    assert [kind.id for kind in connections.CONNECTION_TYPES] == ["ssh", "telnet", "rdp", "local"]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("ssh", SSH),
        ("telnet", TELNET),
        ("rdp", RDP),
        ("local", LOCAL),
        ("vnc", TELNET),
        ("", TELNET),
        (None, TELNET),
    ],
)
def test_a_type_is_found_by_name_and_one_gcm_does_not_know_is_telnet(name, expected):
    """addTab ran telnet for any name it did not know, and still does."""
    assert connections.named(name) is expected


@pytest.mark.parametrize(
    ("ctype", "address", "expected"),
    [
        ("ssh", "", LOCAL),  # the Local button's host
        ("rdp", "", LOCAL),
        ("telnet", None, LOCAL),
        ("ssh", "example.test", SSH),
        ("telnet", "example.test", TELNET),
        ("rdp", "example.test", RDP),
        ("vnc", "example.test", TELNET),
        # The dialog never saves a local host with an address; addTab ran telnet for one.
        ("local", "example.test", TELNET),
    ],
)
def test_what_a_host_opens_as(ctype, address, expected):
    assert connections.for_host(host(ctype, address)) is expected


def test_what_the_host_dialog_asks_of_each_type():
    """Port, whether the connection fields apply, whether SSH's controls and Port
    forwarding do, and whether commands follow a login."""
    asked = {
        kind.id: (kind.default_port, kind.remote, kind.ssh_options, kind.sends_commands)
        for kind in connections.CONNECTION_TYPES
    }

    assert asked == {
        "ssh": ("22", True, True, True),
        "telnet": ("23", True, False, True),
        "rdp": ("3389", True, False, False),
        # 23, not empty: the dialog refuses to save a host without a valid port.
        "local": ("23", False, False, True),
    }


def test_only_rdp_needs_a_program_gcm_can_find_missing(monkeypatch):
    monkeypatch.setattr(connections.shutil, "which", lambda _name: None)

    missing = {kind.id: kind.missing() for kind in connections.CONNECTION_TYPES}

    assert missing == {
        "ssh": None,
        "telnet": None,
        "rdp": "Neither xfreerdp3 nor xfreerdp was found. Install FreeRDP to open RDP hosts.",
        "local": None,
    }


def test_a_local_shell_is_opened_by_addtab_not_by_a_command():
    with pytest.raises(NotImplementedError):
        LOCAL.command(host("local", ""), PROGRAMS)


# -- ssh ---------------------------------------------------------------------


def test_ssh_without_a_password_runs_ssh():
    command = SSH.command(host(), PROGRAMS)

    assert command.argv == ["ssh", "-l", "me", "-p", "2222", "example.test"]
    assert command.program == "ssh"
    assert command.password == ""


def test_ssh_with_a_password_runs_the_script_which_types_it():
    command = SSH.command(host(password="pw"), PROGRAMS)

    assert command.argv == ["/gcm/ssh.expect", "ssh", "-l", "me", "-p", "2222", "example.test"]
    assert command.program == "/gcm/ssh.expect"
    assert command.password == "pw"


def test_ssh_gets_each_option_the_host_sets_in_order():
    record = host(
        keep_alive="30",
        tunnel=["8080:localhost:80", "", "1080:*:*"],
        x11=True,
        agent=True,
        compression=True,
        compressionLevel="6",
        private_key="/keys/id",
        extra_params="-o Foo=bar 'a b'",
    )

    assert SSH.command(record, PROGRAMS).argv[5:] == [
        "-o",
        "ServerAliveInterval=30",
        "-L",
        "8080:localhost:80",
        "-D",
        "1080",
        "-X",
        "-A",
        "-C",
        "-o",
        "CompressionLevel=6",
        "-i",
        "/keys/id",
        "-o",
        "Foo=bar",
        "a b",
        "example.test",
    ]


@pytest.mark.parametrize("keep_alive", ["0", ""])
def test_ssh_without_a_keep_alive_or_a_compression_level_gets_neither(keep_alive):
    command = SSH.command(host(keep_alive=keep_alive, compression=True), PROGRAMS)

    assert command.argv == ["ssh", "-l", "me", "-p", "2222", "-C", "example.test"]


def test_an_ssh_host_without_a_user_is_given_the_local_one():
    record = host(user="")

    assert SSH.command(record, PROGRAMS).argv[:3] == ["ssh", "-l", "localme"]
    assert record.user == "localme"  # into the host itself, as addTab always did


# -- telnet ------------------------------------------------------------------


@pytest.mark.parametrize(("user", "password"), [("", "pw"), ("me", ""), ("", "")])
def test_telnet_without_a_user_and_a_password_runs_telnet(user, password):
    record = host("telnet", user=user, password=password, extra_params="-e ^]")

    command = TELNET.command(record, PROGRAMS)

    assert command.argv == ["telnet", "-e", "^]", "example.test", "2222"]
    assert command.password == ""


def test_telnet_with_a_user_and_a_password_runs_the_script():
    command = TELNET.command(host("telnet", password="pw"), PROGRAMS)

    assert command.argv == ["/gcm/ssh.expect", "telnet", "-l", "me", "example.test", "2222"]
    assert command.password == "pw"


def test_a_type_gcm_does_not_know_gives_the_script_its_own_name():
    """As addTab always did. The script runs any name but telnet and rdp as ssh."""
    record = host("vnc", password="pw")

    command = connections.for_host(record).command(record, PROGRAMS)

    assert command.argv[:2] == ["/gcm/ssh.expect", "vnc"]


# -- against real GTK --------------------------------------------------------

_SCRIPT = r"""
import os, shutil, sys, tempfile, time
scenario = sys.argv[1]
os.environ["HOME"] = tempfile.mkdtemp(); sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk
from gnome_connection_manager import app

app.conf.STARTUP_LOCAL = False
app.wMain = w = app.Wmain(application=None)

def pump(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        Gtk.main_iteration_do(False)
        time.sleep(0.005)

if scenario == "the-dialog-lists-the-registry":
    dialog = app.Whost()
    dialog.init("")
    listed = [row[0] for row in dialog.cmbType.get_model()]
    assert listed == ["ssh", "telnet", "rdp", "local"], listed
    assert dialog.cmbType.get_active_text() == "ssh"
    ports = {}
    for kind in listed:
        assert dialog.cmbType.set_active_id(kind), kind
        ports[kind] = dialog.txtPort.get_text()
    assert ports == {"ssh": "22", "telnet": "23", "rdp": "3389", "local": "23"}, ports
    dialog.get_widget("wHost").destroy()
elif scenario == "addtab-opens-each-host-as-its-type-says":
    ran, typed = [], []
    app.vte_run = lambda terminal, command, arg=None: ran.append((command, arg))
    w.send_data = lambda terminal, data: typed.append(data)
    shutil.which = lambda name, *args, **kwargs: "/usr/bin/xfreerdp3" if name == "xfreerdp3" else None

    def open_host(ctype, address, user="me", password=""):
        record = app.Host("Work", ctype, "", address, user, password)
        record.type, record.port, record.keep_alive = ctype, "2222", "0"
        before = len(ran)
        w.addTab(w.nbConsole, record)
        terminal = app.page_terminal(w.nbConsole.get_nth_page(w.nbConsole.get_n_pages() - 1))
        return ran[before:], getattr(terminal, "command", None)

    shown, command = open_host("ssh", "")  # the Local button's host is of type ssh
    assert shown == [(app.SHELL, None)] and command is None, (shown, command)

    shown, command = open_host("ssh", "example.test", password="pw")
    argv = [app.SSH_COMMAND, "ssh", "-l", "me", "-p", "2222", "example.test"]
    assert shown == [(app.SSH_COMMAND, argv)] and command == (app.SSH_COMMAND, argv, "pw"), shown

    shown, command = open_host("telnet", "example.test")
    argv = ["telnet", "example.test", "2222"]
    assert shown == [("telnet", argv)] and command == ("telnet", argv, ""), shown

    shown, command = open_host("rdp", "example.test")
    argv = ["xfreerdp3", "/v:example.test", "/port:2222", "/u:me"]
    assert shown == [("xfreerdp3", argv)] and command == ("xfreerdp3", argv, ""), shown

    pump(2.5)  # the stored password is typed 2 s after its spawn, and only it
    assert typed == ["pw"], typed
else:
    raise SystemExit("no scenario " + scenario)
print("OK")
"""


@pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"),
    reason="needs a display for a real terminal",
)
@pytest.mark.parametrize(
    "scenario", ["the-dialog-lists-the-registry", "addtab-opens-each-host-as-its-type-says"]
)
def test_the_registry_against_real_gtk(scenario):
    pytest.importorskip("gi", reason="PyGObject not available")
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT, scenario],
        capture_output=True,
        text=True,
        cwd=REPO,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr[-3000:]
    assert "OK" in result.stdout
