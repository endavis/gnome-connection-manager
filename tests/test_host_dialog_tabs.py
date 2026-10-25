"""The host dialog's tabs per connection type, in the real dialog (#277): SSH's options
and its port forwarding only for SSH, and the Terminal tab only for a host whose tab is a
terminal. And a host saved before they moved, of each type, opens with every value in
place and is saved as it was."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_connections import glib_complaints

REPO = Path(__file__).resolve().parents[1]

# HOME is redirected so this can never touch a real configuration. A page is known by a
# widget on it, so that the tabs read the same in any language.
_SCRIPT = r"""
import configparser, json, os, sys, tempfile, time
scenario, vnc = sys.argv[1], sys.argv[2]
os.environ["HOME"] = tempfile.mkdtemp(); os.environ.pop("XDG_CONFIG_HOME", None)
sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk
from gnome_connection_manager import app
from gnome_connection_manager.utils import connections
from gnome_connection_manager.utils.configfile import HOST_PREFIX

app.conf.STARTUP_LOCAL = False
app.wMain = w = app.Wmain(application=None)
# As with gtk-vnc, which draws a VNC host's desktop in its tab, or without it, wherever
# this runs. Only whether VNC has a page is read.
app.TYPE_PAGES = {"vnc": object} if vnc == "drawn" else {}

def pump(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        Gtk.main_iteration_do(False)
        time.sleep(0.005)

MARKS = {
    "Properties": "txtName",
    "SSH": "txtPrivateKey",
    "Port forwarding": "treeTunel",
    "Commands": "txtCommands",
    "Terminal": "txtTerm",
}

def tabs(dialog):
    # The tabs drawn: a hidden page takes its tab with it.
    pump(0.2)
    notebook = dialog.get_widget("nbHost")
    drawn = []
    for n in range(notebook.get_n_pages()):
        page = notebook.get_nth_page(n)
        if not notebook.get_tab_label(page).get_mapped():
            continue
        names = [name for name, mark in MARKS.items() if dialog.get_widget(mark).is_ancestor(page)]
        names += [
            connections.named(type_id).settings_title
            for type_id, (own, _controls) in dialog.type_pages.items()
            if own is page
        ]
        assert len(names) == 1, (n, names)
        drawn += names
    return drawn

def opened(group="", host=None):
    dialog = app.Whost()
    dialog.init(group, host)
    dialog.get_widget("wHost").present()
    return dialog

shown = {}
if scenario == "tabs":
    for kind in connections.CONNECTION_TYPES:
        dialog = opened()
        dialog.cmbType.set_active_id(kind.id)
        shown[kind.id] = tabs(dialog)
        dialog.get_widget("wHost").destroy()
    # Back to SSH after a type that has none of its tabs.
    dialog = opened()
    spins = (dialog.get_widget("txtKeepAlive"), dialog.get_widget("txtCompressionLevel"))
    # Greyed as their boxes start, unticked, whatever the type.
    assert not any(spin.get_sensitive() for spin in spins)
    dialog.cmbType.set_active_id("web")
    tabs(dialog)
    dialog.cmbType.set_active_id("ssh")
    shown["ssh again"] = tabs(dialog)
    assert not any(spin.get_sensitive() for spin in spins)
    keep_alive = dialog.get_widget("chkKeepAlive")
    keep_alive.set_active(True)
    dialog.get_widget("chkCompression").set_active(True)
    assert all(spin.get_sensitive() for spin in spins)
    # Another type turns keep-alive off, and choosing SSH again shows it off. It stayed
    # ticked over a keep-alive of 0.
    dialog.cmbType.set_active_id("telnet")
    dialog.cmbType.set_active_id("ssh")
    assert not keep_alive.get_active() and not spins[0].get_sensitive()
    assert spins[0].get_text() == "0", spins[0].get_text()
    # Ten lines of commands at the least, in the font they are drawn in: the dialog is
    # as tall as its tallest page, and Properties is shorter now.
    commands = dialog.get_widget("txtCommands")
    notebook = dialog.get_widget("nbHost")
    [page] = [notebook.get_nth_page(n) for n in range(notebook.get_n_pages()) if commands.is_ancestor(notebook.get_nth_page(n))]
    notebook.set_current_page(notebook.page_num(page))
    pump(0.2)
    line = commands.create_pango_layout("Xg").get_pixel_size()[1]
    assert commands.get_parent().get_allocated_height() >= 10 * line, (commands.get_parent().get_allocated_height(), line)
    dialog.get_widget("wHost").destroy()
elif scenario == "round-trip":
    # A host of each type as an older GCM saved it, every value set, those of tabs its
    # type is no longer shown included. Port forwards are kept for SSH alone, and the
    # command after disconnecting for a host with a tab, as before, and its tab name (#349).
    for kind in connections.CONNECTION_TYPES:
        host = app.Host(
            "Work", kind.id + "-box", "kept as it was",
            "" if kind.id == "local" else "box.example", "alice", "s3cret",
            "/home/alice/.ssh/id_ed25519", "2222",
            "8080:localhost:80" if kind.ssh_options else "", kind.id,
            "ls\n##D=1000\npwd", "120", "#00ff00", "#002b36",
            True, True, True, "9", "-v", True, 1, 2, "xterm-256color", True,
            "id-" + kind.id,
        )
        host.before_command = "true"
        host.after_command = "true" if kind.opens_tab else ""
        host.tab_name = "tpl {name} ({type})" if kind.opens_tab else ""
        if kind.id == "command":
            host.type_settings = {"command.line": "echo {name}"}
        if kind.id == "rdp":
            # A choice, a flag and text, each off its default (#278).
            host.type_settings = {
                "rdp.display": "all-monitors", "rdp.resize": "False",
                "rdp.size": "1920x1080", "rdp.scale": "150",
            }
        app.groups.setdefault("Work", []).append(host)
    w.writeConfig()
    app.groups.clear()
    w.loadConfig()

    def sections():
        saved = configparser.RawConfigParser()
        saved.read(app.CONFIG_FILE)
        # By id, since an edit moves a host to the end of its folder's list. Not the
        # password, which is encrypted afresh with each save.
        return {
            saved.get(name, "id"): {key: value for key, value in saved.items(name) if key != "pass"}
            for name in saved.sections()
            if name.startswith(HOST_PREFIX)
        }

    before = sections()
    assert len(before) == len(connections.CONNECTION_TYPES), before
    for kind in connections.CONNECTION_TYPES:
        [host] = [host for host in app.groups["Work"] if host.type == kind.id]
        dialog = opened("Work", host)
        shown[kind.id] = tabs(dialog)
        dialog.on_okbutton1_clicked(None)
    after = sections()
    assert after == before, [(id, before[id], after.get(id)) for id in before if after.get(id) != before[id]]
    app.groups.clear()
    w.loadConfig()
    passwords = {host.type: host.password for host in app.groups["Work"]}
    assert set(passwords.values()) == {"s3cret"}, passwords
else:
    raise SystemExit("no scenario " + scenario)
print(json.dumps(shown))
"""

TERMINAL = ["Properties", "Commands", "Terminal"]


def expected_tabs(vnc):
    return {
        "ssh": ["Properties", "SSH", "Port forwarding", "Commands", "Terminal"],
        "telnet": TERMINAL,
        "rdp": ["Properties", "RDP", "Commands", "Terminal"],
        "local": TERMINAL,
        # It opens no tab, and so no terminal.
        "web": ["Properties", "Commands"],
        # A viewer runs in a terminal where gtk-vnc is missing.
        "vnc": ["Properties", "Commands"] if vnc == "drawn" else TERMINAL,
        "command": ["Properties", "Command line", "Commands", "Terminal"],
    }


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="needs a display for a real dialog")
@pytest.mark.parametrize("vnc", ["drawn", "viewer"])
@pytest.mark.parametrize("scenario", ["tabs", "round-trip"])
def test_the_host_dialog_against_real_gtk(scenario, vnc):
    pytest.importorskip("gi", reason="PyGObject not available")
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT, scenario, vnc],
        capture_output=True,
        text=True,
        cwd=REPO,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr[-3000:]
    assert "Traceback" not in result.stderr, result.stderr[-3000:]
    assert glib_complaints(result.stderr) == []
    shown = json.loads(result.stdout.splitlines()[-1])
    expected = expected_tabs(vnc)
    if scenario == "tabs":
        expected["ssh again"] = expected["ssh"]
    assert shown == expected
