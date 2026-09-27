"""Connection types behind a registry (#228).

Each kind of host is a class in `utils/connections.py`, and what used to compare
`host.type` with a name asks the type instead. These pin how a host's type is found,
what the host dialog asks of each type, the command each builds, and how a type's own
settings are read and kept, without a display. Against real GTK, they check that the
dialog lists the registry's types, that `addTab` opens a host as its type says, a type
with a page of its own in a tab, and that a type's settings get a page of the dialog and
reach gcm.conf and back.

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
WEB, VNC = connections.WEB, connections.VNC


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
    assert [kind.id for kind in connections.CONNECTION_TYPES] == [
        "ssh",
        "telnet",
        "rdp",
        "local",
        "web",
        "vnc",
    ]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("ssh", SSH),
        ("telnet", TELNET),
        ("rdp", RDP),
        ("local", LOCAL),
        ("web", WEB),
        ("vnc", VNC),
        ("spice", TELNET),
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
        ("web", "example.test", WEB),
        ("web", "", LOCAL),
        ("vnc", "example.test", VNC),
        ("spice", "example.test", TELNET),
        # The dialog never saves a local host with an address; addTab ran telnet for one.
        ("local", "example.test", TELNET),
    ],
)
def test_what_a_host_opens_as(ctype, address, expected):
    assert connections.for_host(host(ctype, address)) is expected


def test_what_the_host_dialog_asks_of_each_type():
    """Port; whether the connection fields apply, and of them the user and password, and
    the extra arguments; whether SSH's controls and Port forwarding do; whether commands
    follow a login; and whether the host opens a tab."""
    asked = {
        kind.id: (
            kind.default_port,
            kind.remote,
            kind.credentials,
            kind.arguments,
            kind.ssh_options,
            kind.sends_commands,
            kind.opens_tab,
        )
        for kind in connections.CONNECTION_TYPES
    }

    assert asked == {
        "ssh": ("22", True, True, True, True, True, True),
        "telnet": ("23", True, True, True, False, True, True),
        "rdp": ("3389", True, True, True, False, False, True),
        # 23, not empty: the dialog refuses to save a host without a valid port.
        "local": ("23", False, True, True, False, True, True),
        "web": ("443", True, False, False, False, False, False),
        # The user and password answer gtk-vnc, and the extra arguments go to a viewer.
        "vnc": ("5900", True, True, True, False, False, True),
    }


def test_what_a_type_needs_that_gcm_cannot_find(monkeypatch):
    monkeypatch.setattr(connections.shutil, "which", lambda _name: None)

    missing = {kind.id: kind.missing() for kind in connections.CONNECTION_TYPES}

    assert missing == {
        "ssh": None,
        "telnet": None,
        "rdp": "Neither xfreerdp3 nor xfreerdp was found. Install FreeRDP to open RDP hosts.",
        "local": None,
        "web": "xdg-open was not found. Install xdg-utils to open web hosts.",
        "vnc": "Neither gtk-vnc's GObject bindings nor a VNC viewer was found."
        " Install either to open VNC hosts.",
    }


def test_a_web_host_needs_only_xdg_open(monkeypatch):
    monkeypatch.setattr(
        connections.shutil,
        "which",
        lambda name: "/usr/bin/xdg-open" if name == "xdg-open" else None,
    )

    assert WEB.missing() is None


def test_a_local_shell_is_opened_by_addtab_not_by_a_command():
    with pytest.raises(NotImplementedError):
        LOCAL.command(host("local", ""), PROGRAMS)


def test_a_web_host_runs_no_command_and_a_tab_has_no_url():
    with pytest.raises(NotImplementedError):
        WEB.command(host("web"), PROGRAMS)
    with pytest.raises(NotImplementedError):
        SSH.url(host())


# -- web ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("address", "port", "url"),
    [
        ("bmc.example", "443", "https://bmc.example"),
        ("bmc.example", "8443", "https://bmc.example:8443"),
        ("bmc.example/console/", "443", "https://bmc.example/console/"),
        ("bmc.example/console", "8443", "https://bmc.example:8443/console"),
        ("10.0.0.5", "443", "https://10.0.0.5"),
        ("fe80::1", "443", "https://[fe80::1]"),
        ("2001:db8::5", "8443", "https://[2001:db8::5]:8443"),
        (" bmc.example ", "", "https://bmc.example"),
        # With a scheme, the address is the URL, and the port is not added to it.
        ("http://switch.example", "443", "http://switch.example"),
        ("https://nas.example:5001/ui?x=1", "8443", "https://nas.example:5001/ui?x=1"),
    ],
)
def test_a_web_hosts_url(address, port, url):
    record = host("web", address)
    record.port = port

    assert WEB.url(record) == url


# -- vnc: the viewer, where gtk-vnc cannot draw the desktop in a tab ---------


@pytest.mark.parametrize(
    ("installed", "viewer"),
    [
        ({"vncviewer", "xtigervncviewer", "xtightvncviewer"}, "vncviewer"),
        ({"xtigervncviewer", "xtightvncviewer"}, "xtigervncviewer"),
        ({"xtightvncviewer"}, "xtightvncviewer"),
    ],
)
def test_a_vnc_host_runs_the_first_viewer_installed(monkeypatch, installed, viewer):
    monkeypatch.setattr(
        connections.shutil, "which", lambda name: f"/usr/bin/{name}" if name in installed else None
    )

    assert VNC.missing() is None
    assert VNC.command(host("vnc"), PROGRAMS).program == viewer


@pytest.mark.parametrize(
    ("address", "extra", "argv"),
    [
        ("example.test", "", ["xtigervncviewer", "example.test::2222"]),
        # Options come before the host, as the viewers' usage has them.
        (
            "10.0.0.5",
            "-ViewOnly -Shared",
            ["xtigervncviewer", "-ViewOnly", "-Shared", "10.0.0.5::2222"],
        ),
        ("fe80::1", "", ["xtigervncviewer", "[fe80::1]::2222"]),
    ],
)
def test_a_vnc_viewer_is_given_its_arguments_then_the_host_and_port(
    monkeypatch, address, extra, argv
):
    monkeypatch.setattr(
        connections.shutil,
        "which",
        lambda name: "/usr/bin/xtigervncviewer" if name == "xtigervncviewer" else None,
    )

    command = VNC.command(host("vnc", address, password="pw", extra_params=extra), PROGRAMS)

    # Never the stored password: the viewer asks for it, and GCM types nothing.
    assert (command.argv, command.password) == (argv, "")


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
    record = host("spice", password="pw")

    command = connections.for_host(record).command(record, PROGRAMS)

    assert command.argv[:2] == ["/gcm/ssh.expect", "spice"]


# -- settings of a type's own ------------------------------------------------
#
# None of the types here has any yet, so these use a type of their own, as the first
# type with settings will declare them.


class Example(connections.ConnectionType):
    id = "example"
    settings_title = "Example"
    settings = (
        connections.Setting("view-only", "View only", False),
        connections.Setting("quality", "Quality", "high"),
    )


EXAMPLE = Example()


def test_a_type_added_to_the_registry_is_found_by_name(monkeypatch):
    monkeypatch.setattr(connections, "CONNECTION_TYPES", (*connections.CONNECTION_TYPES, EXAMPLE))

    assert connections.named("example") is EXAMPLE


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (None, False),
        ("True", True),
        ("False", False),
        # What configparser's getboolean reads, as the other flags of a host are read.
        ("yes", True),
        ("on", True),
        ("0", False),
        ("maybe", False),
    ],
)
def test_a_flag_reads_what_a_host_stored_or_its_default(text, expected):
    flag = connections.Setting("view-only", "View only", False)

    assert flag.is_flag
    assert flag.value(text) is expected


@pytest.mark.parametrize(("text", "expected"), [(None, "high"), ("low", "low"), ("", "")])
def test_text_reads_what_a_host_stored_or_its_default(text, expected):
    text_setting = connections.Setting("quality", "Quality", "high")

    assert not text_setting.is_flag
    assert text_setting.value(text) == expected


@pytest.mark.parametrize("key", ["viewOnly", "view only", "view.only", "view=only", ""])
def test_a_key_configparser_would_not_give_back_is_refused(key):
    """It folds an option's name to lower case as it writes it, so `viewOnly` would be
    written as `example.viewonly` and never found again."""
    with pytest.raises(ValueError, match="lower case"):
        connections.Setting(key, "Label")


def test_a_types_settings_are_found_under_its_prefix_and_others_are_not_its_own():
    record = host("example")
    record.type_settings = {"example.quality": "low", "other.quality": "medium"}

    assert EXAMPLE.option("quality") == "example.quality"
    assert EXAMPLE.settings_of(record) == {"view-only": False, "quality": "low"}


@pytest.mark.parametrize(
    ("values", "stored"),
    [
        ({"view-only": False, "quality": "high"}, {}),
        ({"view-only": True, "quality": "high"}, {"example.view-only": "True"}),
        ({"view-only": False, "quality": ""}, {"example.quality": ""}),
        (
            {"view-only": True, "quality": "low"},
            {"example.view-only": "True", "example.quality": "low"},
        ),
    ],
)
def test_a_host_keeps_only_what_differs_from_a_default_and_reads_it_back(values, stored):
    record = host("example")

    record.type_settings = EXAMPLE.stored_settings(values)

    assert record.type_settings == stored
    assert EXAMPLE.settings_of(record) == values


def test_a_type_without_settings_keeps_none():
    assert SSH.stored_settings({}) == {}
    assert SSH.settings_of(host()) == {}


# -- against real GTK --------------------------------------------------------

# -- which sessions dropped (#239) ---------------------------------------------

# Each line as the client printed it when the session ended so, measured against a
# non-root sshd 9.6p1 and busybox telnetd with OpenSSH 9.6p1 and inetutils telnet 2.5.
SSH_ENDINGS = [
    # (how it ended, status, last lines, dropped, refused)
    ("remote exit", 0, "$ exit\nConnection to 10.0.0.5 closed.\n", False, False),
    ("remote exit 3", 3, "$ exit 3\nConnection to 10.0.0.5 closed.\n", False, False),
    ("ssh's ~. escape", 255, "$ Connection to 10.0.0.5 closed.\n", False, False),
    ("the remote shell killed", 255, "$ Connection to 10.0.0.5 closed.\n", False, False),
    (
        "the server shut down",
        255,
        "$ Connection to 10.0.0.5 closed by remote host.\nConnection to 10.0.0.5 closed.\n",
        True,
        False,
    ),
    ("the server froze", 255, "$ Timeout, server 10.0.0.5 not responding.\n", True, False),
    ("a refused key", 255, "ops@10.0.0.5: Permission denied (publickey).\n", False, True),
    (
        "a refused host key",
        255,
        "No ED25519 host key is known for 10.0.0.5 and you have requested strict checking.\n"
        "Host key verification failed.\n",
        False,
        True,
    ),
    (
        "a name that does not resolve",
        255,
        "ssh: Could not resolve hostname db.invalid: Name or service not known\n",
        False,
        False,
    ),
    # While a server is rebooting: not a drop, not refused, so an attempt that failed.
    (
        "the connection refused",
        255,
        "ssh: connect to host 10.0.0.5 port 22: Connection refused\n",
        False,
        False,
    ),
    # The same words from a program run in the session are not ssh's: its status is not 255.
    ("a program's own output", 1, "Connection to x closed by remote host.\n", False, False),
]


@pytest.mark.parametrize(
    ("ending", "status", "tail", "dropped", "refused"), SSH_ENDINGS, ids=[e[0] for e in SSH_ENDINGS]
)
def test_which_ssh_sessions_dropped(ending, status, tail, dropped, refused):
    assert SSH.dropped(status, tail) is dropped
    assert SSH.refused(status, tail) is refused


@pytest.mark.parametrize(
    ("status", "dropped", "refused"),
    [
        (147, True, False),
        (0, False, False),
        (134, False, True),
        (143, False, True),
        (140, False, False),
    ],
)
def test_which_rdp_sessions_dropped(status, dropped, refused):
    """FreeRDP 3's statuses measured for #225: 147 Network disconnect, 0 its window
    closed, 134 a logon failure, 143 a certificate not trusted, 140 a name not found."""
    assert RDP.dropped(status, "") is dropped
    assert RDP.refused(status, "") is refused


@pytest.mark.parametrize(
    "tail",
    ["$ exit\nConnection closed by foreign host.\n", "telnet> quit\nConnection closed.\n"],
)
def test_telnet_never_drops(tail):
    """It exits 0 however the session ends, and a server that dies says what a remote
    `exit` says, measured: nothing tells a drop apart."""
    for status in (0, 1, 255):
        assert not TELNET.dropped(status, tail)
        assert not TELNET.refused(status, tail)


def test_nor_does_a_local_shell_a_web_host_or_vnc():
    """VNC is out of #239's scope: its viewer, in a tab or a terminal, is not asked."""
    for kind in (LOCAL, WEB, VNC):
        assert not kind.dropped(255, "Connection to x closed by remote host.\n")


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
    assert listed == ["ssh", "telnet", "rdp", "local", "web", "vnc"], listed
    assert dialog.cmbType.get_active_text() == "ssh"
    ports = {}
    for kind in listed:
        assert dialog.cmbType.set_active_id(kind), kind
        ports[kind] = dialog.txtPort.get_text()
    expected = {"ssh": "22", "telnet": "23", "rdp": "3389", "local": "23", "web": "443", "vnc": "5900"}
    assert ports == expected, ports
    dialog.get_widget("wHost").destroy()
elif scenario == "addtab-opens-each-host-as-its-type-says":
    ran, typed = [], []
    app.vte_run = lambda terminal, command, arg=None: ran.append((command, arg))
    w.send_data = lambda terminal, data: typed.append(data)
    app.TYPE_PAGES = {}  # as without gtk-vnc, wherever this runs
    found = {
        "xfreerdp3": "/usr/bin/xfreerdp3",
        "xdg-open": "/usr/bin/xdg-open",
        "xtigervncviewer": "/usr/bin/xtigervncviewer",
    }
    shutil.which = lambda name, *args, **kwargs: found.get(name)
    browsed = []
    app.open_in_browser = browsed.append

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

    # A web host opens in the browser, and no tab: nothing is spawned or added.
    tabs = w.nbConsole.get_n_pages()
    record = app.Host("Work", "bmc", "", "bmc.example/console", "me", "pw")
    record.type, record.port = "web", "8443"
    w.addTab(w.nbConsole, record)
    assert browsed == ["https://bmc.example:8443/console"], browsed
    assert w.nbConsole.get_n_pages() == tabs and len(ran) == 4, (w.nbConsole.get_n_pages(), ran)

    # Without gtk-vnc, a VNC host runs a viewer in a terminal, which asks for the password.
    shown, command = open_host("vnc", "example.test", password="pw")
    argv = ["xtigervncviewer", "example.test::2222"]
    assert shown == [("xtigervncviewer", argv)] and command == ("xtigervncviewer", argv, ""), shown

    pump(2.5)  # the stored password is typed 2 s after its spawn, and only ssh's
    assert typed == ["pw"], typed
elif scenario == "a-types-page-opens-in-a-tab":
    ran = []
    app.vte_run = lambda terminal, command, arg=None: ran.append((command, arg))
    shutil.which = lambda name, *args, **kwargs: None  # no viewer: the page needs none
    shown = []
    app.msgbox = shown.append
    opened = []

    class Page(Gtk.Box):
        # A page of a type's own, as TYPE_PAGES holds, which records what GCM asks of it.
        def __init__(self, host, ended):
            Gtk.Box.__init__(self)
            self.host, self.ended = host, ended
            self.keyboard = Gtk.DrawingArea(can_focus=True)
            self.pack_start(self.keyboard, True, True, 0)

        def open(self):
            opened.append((self.host.name, self.get_parent() is not None))

    app.TYPE_PAGES = {"vnc": Page}

    def open_host(name):
        record = app.Host("Work", name, "", "example.test", "me", "pw")
        record.type, record.port = "vnc", "5900"
        w.addTab(w.nbConsole, record)
        pump(0.3)
        page = w.nbConsole.get_nth_page(w.nbConsole.get_n_pages() - 1)
        return page, w.nbConsole.get_tab_label(page)

    page, label = open_host("desk")
    assert isinstance(page, Page) and label.get_text().strip() == "desk", (page, label.get_text())
    # Opened once it is a tab, with the keyboard in it, and without a viewer or a message.
    assert opened == [("desk", True)] and ran == [] and shown == [], (opened, ran, shown)
    assert w.wMain.get_focus() is page.keyboard, w.wMain.get_focus()

    # It ends as a terminal's tab does. Only on clean exit keeps it after a failure.
    app.conf.AUTO_CLOSE_TAB, app.conf.ENDED_MARK_TAB = 2, 1
    other, other_label = open_host("other")  # the first is now out of sight
    page.ended(1)
    pump(0.2)
    assert page.get_parent() is w.nbConsole and not label.is_active, "a failed end closed the tab"
    assert label.needs_attention and not other_label.needs_attention
    other.ended(0)
    pump(0.2)
    assert other.get_parent() is None, "a clean end left the tab open"

    app.conf.ENDED_MARK_TAB = 0
    quiet, quiet_label = open_host("quiet")
    w.nbConsole.set_current_page(w.nbConsole.page_num(page))
    quiet.ended(1)
    assert not quiet_label.needs_attention, "marked with Mark tab when the session ends off"
elif scenario == "open-in-browser":
    # A fake xdg-open on PATH, which records what it was given and exits as told.
    shown = []
    app.msgbox = shown.append
    bin_dir = tempfile.mkdtemp()
    opened = os.path.join(bin_dir, "opened")

    def xdg_open_exits(status):
        path = os.path.join(bin_dir, "xdg-open")
        with open(path, "w") as script:
            script.write(f'#!/bin/sh\nprintf "%s\\n" "$@" >> {opened}\nexit {status}\n')
        os.chmod(path, 0o755)

    os.environ["PATH"] = bin_dir + os.pathsep + os.environ["PATH"]
    xdg_open_exits(0)
    app.open_in_browser("https://bmc.example:8443/a b?x=1")
    pump(1.0)
    assert open(opened).read().splitlines() == ["https://bmc.example:8443/a b?x=1"]
    assert shown == [], shown

    xdg_open_exits(4)
    app.open_in_browser("https://down.example/")
    pump(1.0)
    assert shown == ["Could not open https://down.example/: xdg-open exited with status 4"], shown

    shown.clear()
    os.environ["PATH"] = tempfile.mkdtemp()  # no xdg-open at all
    app.open_in_browser("https://gone.example/")
    assert len(shown) == 1 and shown[0].startswith("Could not open https://gone.example/: "), shown
elif scenario == "xdg-open-reaches-the-browser":
    # The real xdg-open, given a browser of its own through a desktop file, and a second
    # one through BROWSER, each leaving a mark, so that it can never reach a real one. A
    # mail client too, which a Ctrl+click on an address opens (#232).
    root = tempfile.mkdtemp()
    opened = os.path.join(root, "opened")
    for name in ("desktop", "envvar", "mail"):
        with open(os.path.join(root, name), "w") as script:
            script.write(f'#!/bin/sh\nprintf "{name} %s\\n" "$@" >> {opened}\n')
        os.chmod(os.path.join(root, name), 0o755)
    os.makedirs(os.path.join(root, "share", "applications"))
    with open(os.path.join(root, "share", "applications", "fake-browser.desktop"), "w") as entry:
        entry.write(
            "[Desktop Entry]\nType=Application\nName=Fake browser\n"
            f"Exec={root}/desktop %u\nMimeType=x-scheme-handler/https;\nNoDisplay=true\n"
        )
    with open(os.path.join(root, "share", "applications", "fake-mail.desktop"), "w") as entry:
        entry.write(
            "[Desktop Entry]\nType=Application\nName=Fake mail\n"
            f"Exec={root}/mail %u\nMimeType=x-scheme-handler/mailto;\nNoDisplay=true\n"
        )
    os.environ.update(
        XDG_DATA_HOME=os.path.join(root, "share"),
        XDG_DATA_DIRS=os.path.join(root, "share"),
        XDG_CONFIG_HOME=root,
        XDG_CONFIG_DIRS=root,
        BROWSER=os.path.join(root, "envvar"),
    )
    for name in ("XDG_CURRENT_DESKTOP", "DESKTOP_SESSION", "KDE_FULL_SESSION", "GNOME_DESKTOP_SESSION_ID"):
        os.environ.pop(name, None)
    shown = []
    app.msgbox = shown.append
    # xdg-open finds a handler by the scheme as written, and sent these two to BROWSER
    # until open_in_browser lowered it. Only the scheme: a path keeps its case.
    urls = ["https://bmc.example/console", "HTTPS://bmc.example/Console", "MAILTO:ops@example.test"]
    for url in urls:
        app.open_in_browser(url)
    end = time.monotonic() + 10
    while (not os.path.exists(opened) or len(open(opened).readlines()) < len(urls)) and time.monotonic() < end:
        pump(0.1)
    pump(0.5)
    assert sorted(open(opened).read().splitlines()) == [
        "desktop https://bmc.example/Console",
        "desktop https://bmc.example/console",
        "mail mailto:ops@example.test",
    ], open(opened).read()
    assert shown == [], shown
elif scenario == "no-shipped-type-adds-a-page":
    dialog = app.Whost()
    dialog.init("")
    notebook = dialog.get_widget("nbHost")
    assert dialog.type_pages == {} and notebook.get_n_pages() == 4, notebook.get_n_pages()
    dialog.get_widget("wHost").destroy()
elif scenario == "a-types-page-in-the-host-dialog":
    from gnome_connection_manager.utils import connections

    class Example(connections.ConnectionType):
        id = "example"
        settings_title = "Example"
        settings = (
            connections.Setting("view-only", "View only", False),
            connections.Setting("quality", "Quality", "high"),
            connections.Setting("shared", "Shared", True),
        )

    connections.CONNECTION_TYPES = (*connections.CONNECTION_TYPES, Example())
    # A type marks its labels with N_, and the dialog translates them as it draws them.
    ours = ("Example", "View only", "Quality", "Shared")
    app._ = lambda text, gettext=app._: text.upper() if text in ours else gettext(text)

    def shown(dialog):
        # The tabs drawn: a hidden page takes its tab with it.
        notebook = dialog.get_widget("nbHost")
        pump(0.2)
        pages = [notebook.get_nth_page(n) for n in range(notebook.get_n_pages())]
        return [notebook.get_tab_label(page) for page in pages if notebook.get_tab_label(page).get_mapped()]

    dialog = app.Whost()
    dialog.init("")
    notebook = dialog.get_widget("nbHost")
    page, controls = dialog.type_pages["example"]
    tunnels, example_tab = dialog.get_widget("tunnelGrid"), notebook.get_tab_label(page)
    assert example_tab.get_text() == "EXAMPLE"
    assert notebook.page_num(page) == notebook.page_num(tunnels) + 1

    ssh_tabs = shown(dialog)  # a new host is ssh
    assert notebook.get_tab_label(tunnels) in ssh_tabs and example_tab not in ssh_tabs
    dialog.cmbType.set_active_id("example")
    example_tabs = shown(dialog)
    assert example_tab in example_tabs and notebook.get_tab_label(tunnels) not in example_tabs
    assert len(example_tabs) == len(ssh_tabs)

    # Drawn as Properties is: a check box for a flag, an entry for text, each labelled.
    notebook.set_current_page(notebook.page_num(page))
    pump(0.2)
    assert isinstance(controls["view-only"], Gtk.CheckButton) and controls["view-only"].get_mapped()
    assert isinstance(controls["quality"], Gtk.Entry) and controls["quality"].get_mapped()
    # At their defaults, which a new host starts with.
    assert controls["quality"].get_text() == "high" and not controls["view-only"].get_active()
    assert controls["shared"].get_active()
    labels = {child.get_text() for child in page.get_children() if isinstance(child, Gtk.Label)}
    assert labels == {"VIEW ONLY", "QUALITY", "SHARED"}, labels

    # What was typed survives choosing another type and coming back.
    controls["view-only"].set_active(True)
    controls["quality"].set_text("low")
    dialog.cmbType.set_active_id("ssh")
    dialog.cmbType.set_active_id("example")
    assert controls["view-only"].get_active() and controls["quality"].get_text() == "low"

    dialog.cmbGroup.get_children()[0].set_text("Work")
    dialog.txtName.set_text("box")
    dialog.txtHost.set_text("example.test")
    dialog.on_okbutton1_clicked(None)
    saved = {"example.view-only": "True", "example.quality": "low"}
    assert app.groups["Work"][0].type_settings == saved, app.groups["Work"][0].type_settings
    written = [line.strip() for line in open(app.CONFIG_FILE) if line.startswith("example.")]
    assert written == ["example.view-only = True", "example.quality = low"], written

    # Read back as GCM starts, and shown again for an edit.
    app.groups.clear()
    w.loadConfig()
    loaded = app.groups["Work"][0]
    assert loaded.type_settings == saved, loaded.type_settings
    edit = app.Whost()
    edit.init("Work", loaded)
    page, controls = edit.type_pages["example"]
    assert edit.get_widget("nbHost").get_tab_label(page) in shown(edit)
    assert controls["view-only"].get_active() and controls["quality"].get_text() == "low"

    # Back to the defaults, a host keeps nothing; and a host of another type keeps none
    # of what a hidden page holds. Text is read stripped, as the dialog's other fields are.
    controls["view-only"].set_active(False)
    controls["quality"].set_text("  high ")
    edit.on_okbutton1_clicked(None)
    assert app.groups["Work"][0].type_settings == {}, app.groups["Work"][0].type_settings
    written = [line.strip() for line in open(app.CONFIG_FILE) if line.startswith("example.")]
    assert written == [], written  # a save rewrites the host's section, not adds to it
    other = app.Whost()
    other.init("Work", app.groups["Work"][0])
    other.type_pages["example"][1]["quality"].set_text("low")
    other.cmbType.set_active_id("telnet")
    other.on_okbutton1_clicked(None)
    assert app.groups["Work"][0].type == "telnet" and app.groups["Work"][0].type_settings == {}
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
        "the-dialog-lists-the-registry",
        "addtab-opens-each-host-as-its-type-says",
        "a-types-page-opens-in-a-tab",
        "open-in-browser",
        "xdg-open-reaches-the-browser",
        "no-shipped-type-adds-a-page",
        "a-types-page-in-the-host-dialog",
    ],
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
    assert glib_complaints(result.stderr) == []


def glib_complaints(stderr):
    """The criticals GLib reported, as PyGObject prints them or as GLib does itself.

    Opening a web host once gave two: addTab made a terminal before it knew it needed
    none, and VTE 0.76 reports criticals as a terminal that never joined a window is
    dropped. Warnings are left out: on CI, GTK warns that it has no accessibility bus
    and no icon theme, which says nothing about GCM.
    """
    return [line for line in stderr.splitlines() if ": Warning: " in line or "-CRITICAL **" in line]
