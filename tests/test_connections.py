"""Connection types behind a registry (#228).

Each kind of host is a class in `utils/connections.py`, and what used to compare
`host.type` with a name asks the type instead. These pin how a host's type is found,
what the host dialog asks of each type, the command each builds, and how a type's own
settings are read and kept, without a display. Against real GTK, they check that the
dialog lists the registry's types, that `addTab` opens a host as its type says, and that
a type's settings get a page of the dialog and reach gcm.conf and back.

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
