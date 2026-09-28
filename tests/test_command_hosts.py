"""Command hosts (#248): a host that runs a command line of its own.

A host of type `command` runs its line through sh in a terminal tab, with the host's
values filled in and quoted for the shell, and `{password}` given to the command in its
environment, as GCM_PASSWORD, never in a command line. These pin the command the type
builds, run through a real sh; the environment reaching VTE, for a session and for both
ways of reconnecting one; and against real GTK, the tab running it, directly and under
the relay, Reconnect running it again, and the host dialog's page for it.
"""

from __future__ import annotations

import configparser
import os
import subprocess
import sys
from pathlib import Path

import pytest

from gnome_connection_manager.utils import connections
from gnome_connection_manager.utils.hosts import Host, HostUtils
from tests.test_connections import glib_complaints
from tests.test_hosts import make_sample_host, reread

REPO = Path(__file__).resolve().parents[1]
PROGRAMS = connections.Programs(expect="/gcm/ssh.expect", username="localme")
COMMAND = connections.COMMAND


def command_host(line, address="bmc.test", user="admin", password="", name="rack 4", **fields):
    record = Host(fields.get("group", "Lab"), name, "", address, user, password)
    record.type, record.port = "command", fields.get("port", "623")
    record.type_settings = {"command.line": line}
    return record


def run(command):
    """Run what addTab would spawn, with the environment VTE would add to it."""
    return subprocess.run(
        command.argv,
        env={**os.environ, **(command.environment or {})},
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    ).stdout


# -- the command a command host runs ------------------------------------------


def test_a_command_host_runs_its_line_through_sh():
    command = COMMAND.command(command_host("mosh {user}@{address}"), PROGRAMS)

    assert command.argv == ["sh", "-c", "mosh admin@bmc.test"]
    assert command.password == "", "nothing is typed at a command host's prompts"


@pytest.mark.parametrize(
    "value", ["two words", "semi;colon", "it's", "$(echo hi)", "`echo hi`", "*"]
)
def test_each_value_reaches_the_command_as_one_argument_as_written(value):
    line = "printf '[%s]\\n' {name} {address} {user} {port} {group} {type}"
    host = command_host(line, address=value, user=value, name=value, group=value)

    printed = run(COMMAND.command(host, PROGRAMS)).splitlines()

    assert printed == [f"[{value}]"] * 3 + ["[623]", f"[{value}]", "[command]"]


def test_the_password_reaches_the_command_in_its_environment():
    host = command_host("printf '[%s]\\n' {password}", password="s3cret 'pass'")
    command = COMMAND.command(host, PROGRAMS)

    assert command.environment == {"GCM_PASSWORD": "s3cret 'pass'"}
    assert run(command) == "[s3cret 'pass']\n"


def test_the_password_is_never_in_a_command_line():
    """Every user can read a process's command line, and only its owner its environment:
    /proc/<pid>/cmdline is mode 444 and /proc/<pid>/environ 400, measured."""
    line = "tr '\\0' ' ' < /proc/$$/cmdline; echo; printf '%s\\n' {password}"
    command = COMMAND.command(command_host(line, password="s3cret"), PROGRAMS)

    shells_own, printed = run(command).splitlines()

    assert "s3cret" not in " ".join(command.argv) and "s3cret" not in shells_own, shells_own
    assert '"$GCM_PASSWORD"' in shells_own
    assert printed == "s3cret"


def test_a_line_that_names_no_password_is_given_none():
    host = command_host("kubectl exec -it {name} -- sh", password="s3cret")

    assert COMMAND.command(host, PROGRAMS).environment is None


def test_a_host_without_a_stored_password_gives_an_empty_one():
    """Rather than leave the variable to whatever GCM was itself started with."""
    assert COMMAND.command(command_host("x {password}"), PROGRAMS).environment == {
        "GCM_PASSWORD": ""
    }


def test_braces_the_type_does_not_know_are_left_as_written():
    command = COMMAND.command(command_host("kubectl get pods | awk '{print $1}'"), PROGRAMS)

    assert command.argv[2] == "kubectl get pods | awk '{print $1}'"


def test_a_host_without_an_address_runs_its_command():
    """Where a host of any other type without one opens a local shell."""
    host = command_host("kubectl exec -it {name} -- sh", address="")

    assert connections.for_host(host) is COMMAND
    assert COMMAND.command(host, PROGRAMS).argv == ["sh", "-c", "kubectl exec -it 'rack 4' -- sh"]


@pytest.mark.parametrize("line", ["", "   "])
def test_a_command_host_without_a_command_cannot_be_saved(line):
    assert COMMAND.invalid({"line": line}) == (
        "A command host needs a command, on its Command line tab."
    )


def test_one_with_a_command_can_and_no_other_type_refuses_its_settings():
    assert COMMAND.invalid({"line": "mosh {address}"}) is None
    others = [kind for kind in connections.CONNECTION_TYPES if kind is not COMMAND]
    assert [kind.invalid({}) for kind in others] == [None] * len(others)


@pytest.mark.parametrize(
    ("status", "tail"), [(255, "Connection to bmc.test closed by remote host."), (0, ""), (1, "")]
)
def test_a_command_host_never_reconnects_by_itself(status, tail):
    """GCM cannot tell a lost connection from a command that ended (#239)."""
    assert not COMMAND.dropped(status, tail)
    assert not COMMAND.refused(status, tail)


def test_the_command_line_is_kept_through_a_save_and_a_clone():
    """Export and import write and read hosts as a save does."""
    host = make_sample_host()
    host.type, host.type_settings = "command", {"command.line": "mosh {user}@{address}"}
    config = configparser.RawConfigParser()
    config.add_section("host 1")
    HostUtils.save_host_to_ini(config, "host 1", host, pwd="k")
    config = reread(config)

    loaded = HostUtils.load_host_from_ini(config, "host 1", pwd="k")

    assert config.get("host 1", "command.line") == "mosh {user}@{address}"
    assert loaded.type == "command"
    assert loaded.type_settings == {"command.line": "mosh {user}@{address}"}
    assert loaded.clone().type_settings == loaded.type_settings


# -- the environment reaching VTE ----------------------------------------------


def spawned(app_module, monkeypatch, environment, spawn_async=True):
    """What vte_run hands VTE: the argv, the environment, and whether GCM's own
    environment held the password while it did. `spawn_async` False is a VTE older than
    0.48, which only has spawn_sync."""
    captured = {}

    class Terminal:
        def __init__(self):
            self.host = type("Host", (), {"term": ""})()

        def spawn_async(self, *args, **_kwargs):
            captured["argv"], captured["envv"] = args[2], args[3]
            captured["own"] = os.environ.get("GCM_PASSWORD")

        spawn_sync = spawn_async

    # As tests/test_osc52.py does: the stub's flags are opaque, and must survive a `|`.
    monkeypatch.setattr(app_module.GLib.SpawnFlags, "DEFAULT", 1)
    monkeypatch.setattr(app_module.GLib.SpawnFlags, "FILE_AND_ARGV_ZERO", 2)
    monkeypatch.setattr(app_module.GLib.SpawnFlags, "SEARCH_PATH", 4)
    for name in ("MAJOR_VERSION", "MINOR_VERSION", "MICRO_VERSION"):
        monkeypatch.setattr(app_module.Vte, name, 0)
    monkeypatch.setattr(app_module.conf, "RAW_SESSION_LOG", 0)
    monkeypatch.setattr(app_module.conf, "OSC52_ENABLED", 0)
    monkeypatch.delenv("GCM_PASSWORD", raising=False)
    monkeypatch.setattr(app_module, "TERMINAL_V048", spawn_async)
    app_module.vte_run(Terminal(), "sh", ["sh", "-c", "true"], environment)
    return captured


@pytest.mark.parametrize("spawn_async", [True, False])
def test_vte_is_given_the_commands_environment(app_module, monkeypatch, spawn_async):
    spawn = spawned(app_module, monkeypatch, {"GCM_PASSWORD": "s3cret"}, spawn_async)

    assert spawn["envv"] == ["GCM_PASSWORD=s3cret"]
    assert spawn["own"] is None, "the password was put in GCM's own environment"


@pytest.mark.parametrize("spawn_async", [True, False])
def test_a_command_without_one_gives_vte_none(app_module, monkeypatch, spawn_async):
    """None is what every spawn passed before, so every other host spawns as it did."""
    assert spawned(app_module, monkeypatch, None, spawn_async)["envv"] is None


class Session:
    """A terminal whose session addTab built, as far as starting it again reads it."""

    def __init__(self):
        self.host = Host("Lab", "rack 4", "", "", "admin", "s3cret")
        self.host.type = "command"
        self.command = ("sh", ["sh", "-c", "x"], "", {"GCM_PASSWORD": "s3cret"})
        self.marked: list[bool] = []
        tab = type("Tab", (), {"mark_tab_as_active": lambda _tab: self.marked.append(True)})()
        notebook = type("Notebook", (), {"get_tab_label": lambda _nb, _page: tab})()
        self.page = type("Page", (), {"get_parent": lambda _page: notebook})()

    def get_parent(self):
        return self.page

    def queue_draw(self):
        pass


def test_starting_a_session_again_gives_it_its_environment(app_module, monkeypatch):
    """What addTab and Reconnect both start a session with (#238)."""
    ran = []
    monkeypatch.setattr(
        app_module,
        "vte_run",
        lambda _t, command, arg=None, environment=None: ran.append(environment),
    )
    terminal = Session()

    object.__new__(app_module.Wmain).start_session(terminal, commands=False)

    assert ran == [{"GCM_PASSWORD": "s3cret"}]


def test_the_reconnect_key_in_the_terminal_gives_it_its_environment(app_module, monkeypatch):
    """on_terminal_keypress starts the session again itself, where no accelerator took
    the key first."""
    ran = []
    monkeypatch.setattr(
        app_module,
        "vte_run",
        lambda _t, command, arg=None, environment=None: ran.append(environment),
    )
    monkeypatch.setattr(app_module, "get_key_name", lambda _event: "CTRL+N")
    monkeypatch.setattr(app_module, "shortcuts", {"CTRL+N": app_module._CONSOLE_RECONNECT})
    monkeypatch.setattr(app_module, "custom_keys", {})
    terminal = Session()

    handled = object.__new__(app_module.Wmain).on_terminal_keypress(terminal, object())

    assert handled is True and terminal.marked == [True]
    assert ran == [{"GCM_PASSWORD": "s3cret"}]


# -- against real GTK ----------------------------------------------------------

_SCRIPT = r"""
import os, sys, tempfile, time
scenario = sys.argv[1]
os.environ["HOME"] = tempfile.mkdtemp(); sys.argv = ["gcm"]
os.environ.pop("GCM_PASSWORD", None)
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

app.wMain = w = app.Wmain(application=None)
nb = w.nbConsole

def whole(v):
    # Every row, not the visible ones: a tab can be two rows tall on Xvfb.
    text, _ = v.get_text_range_format(Vte.Format.TEXT, 0, 0, v.get_cursor_position()[1], 10000)
    return text or ""

def open_host(line, password="s3cret pass"):
    host = app.Host("Lab", "rack 4", "", "", "admin", password)
    host.type, host.port = "command", "623"
    host.type_settings = {"command.line": line}
    w.addTab(nb, host)
    page = nb.get_nth_page(nb.get_n_pages() - 1)
    return app.page_terminal(page), nb.get_tab_label(page)

def shown_tabs(dialog):
    notebook = dialog.get_widget("nbHost")
    settle(0.2)
    labels = [notebook.get_tab_label(notebook.get_nth_page(n)) for n in range(notebook.get_n_pages())]
    return [label.get_text() for label in labels if label.get_mapped()]

if scenario in ("a-command-host-runs-in-a-tab", "a-command-host-runs-under-the-relay"):
    # Raw recording puts the relay between the command and VTE, in its own process.
    app.conf.RAW_SESSION_LOG = scenario.endswith("relay")
    v, _tab = open_host(
        "tr '\\0' ' ' < /proc/$$/cmdline; echo; printf 'ran [%s] [%s]\\n' {name} {password}"
    )
    # Not "ran [": sh's own command line, printed first, holds that too.
    pump(lambda: "ran [rack 4]" in whole(v), "the command to run")
    shown = whole(v)
    assert "ran [rack 4] [s3cret pass]" in shown, shown
    # The command line sh was given holds a reference to the password, not the password.
    assert shown.count("s3cret") == 1 and '"$GCM_PASSWORD"' in shown, shown
    assert (getattr(v, "raw_path", None) is not None) == app.conf.RAW_SESSION_LOG, v.raw_path
    assert shown_messages == [], shown_messages
elif scenario == "reconnect-runs-it-again":
    v, tab = open_host("printf 'run [%s]\\n' {password}")
    pump(lambda: "run [s3cret pass]" in whole(v), "the command to run")
    settle(0.5)  # and end
    w.reconnect(v, tab)
    pump(lambda: whole(v).count("run [s3cret pass]") == 2, "the command to run again")
elif scenario == "the-dialog-edits-a-command-host":
    dialog = app.Whost()
    dialog.init("")
    notebook = dialog.get_widget("nbHost")
    page, controls = dialog.type_pages["command"]
    assert "Command line" not in shown_tabs(dialog)  # a new host is ssh
    dialog.txtExtraParams.set_text("-v")
    dialog.cmbType.set_active_id("command")
    assert "Command line" in shown_tabs(dialog), shown_tabs(dialog)
    # The line is the whole command, so there are no extra arguments. The rest is the
    # host's, for the line to name.
    assert dialog.txtExtraParams.get_text() == "" and not dialog.txtExtraParams.get_sensitive()
    for field in (dialog.txtHost, dialog.txtUser, dialog.txtPassword, dialog.txtPort):
        assert field.get_sensitive(), field.get_name()
    # Its page says what the line can name, under the line.
    notebook.set_current_page(notebook.page_num(page))
    settle(0.2)
    grid, hint = page.get_children()
    assert controls["line"].get_mapped() and hint.get_mapped()
    assert "{password}" in hint.get_text() and "GCM_PASSWORD" in hint.get_text(), hint.get_text()
    # At its own height, at the top, and as wide as the page lets it be: a grid given the
    # whole page drew this entry half a page tall.
    _minimum, natural = controls["line"].get_preferred_height()
    assert controls["line"].get_allocated_height() <= natural, controls["line"].get_allocated_height()
    assert controls["line"].get_allocated_width() > page.get_allocated_width() / 2

    # Refused without a command, and saved without an address.
    dialog.cmbGroup.get_children()[0].set_text("Lab")
    dialog.txtName.set_text("rack 4")
    dialog.on_okbutton1_clicked(None)
    assert shown_messages == ["A command host needs a command, on its Command line tab."], shown_messages
    assert "Lab" not in app.groups, app.groups
    controls["line"].set_text("  mosh {user}@{address}  ")
    dialog.on_okbutton1_clicked(None)
    saved = app.groups["Lab"][0]
    assert (saved.type, saved.host) == ("command", ""), (saved.type, saved.host)
    assert saved.type_settings == {"command.line": "mosh {user}@{address}"}, saved.type_settings
    written = [line.strip() for line in open(app.CONFIG_FILE) if line.startswith("command.")]
    assert written == ["command.line = mosh {user}@{address}"], written

    # Read back as GCM starts, and shown again for an edit.
    app.groups.clear()
    w.loadConfig()
    edit = app.Whost()
    edit.init("Lab", app.groups["Lab"][0])
    assert edit.type_pages["command"][1]["line"].get_text() == "mosh {user}@{address}"
    assert "Command line" in shown_tabs(edit)
    edit.get_widget("wHost").destroy()

    # A host of any other type still needs an address.
    shown_messages.clear()
    other = app.Whost()
    other.init("")
    other.cmbGroup.get_children()[0].set_text("Lab")
    other.txtName.set_text("web")
    other.on_okbutton1_clicked(None)
    assert shown_messages == [app._("Los campos grupo, nombre y host son obligatorios")], shown_messages
else:
    raise SystemExit("no scenario " + scenario)
print("OK")
"""


@pytest.mark.parametrize(
    "scenario",
    [
        "a-command-host-runs-in-a-tab",
        "a-command-host-runs-under-the-relay",
        "reconnect-runs-it-again",
        "the-dialog-edits-a-command-host",
    ],
)
def test_a_command_host_against_real_gtk(scenario):
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
