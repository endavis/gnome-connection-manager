"""Tests for the snippet library (#240): utils/snippets.py, gcm.conf, and GCM itself.

Snippets replace custom commands. Measured before they did: a command was kept only with
a key, listed by its first 30 characters, and stored with an encoding that turned a
backslash and an n in it into a newline.
"""

from __future__ import annotations

import configparser
import io
import subprocess
import sys
import types
from pathlib import Path
from textwrap import dedent

import pytest

from gnome_connection_manager.utils import snippets
from gnome_connection_manager.utils.snippets import Snippet
from tests.test_connections import glib_complaints

REPO = Path(__file__).resolve().parents[1]


def through_a_file(config):
    """`config` written out and read back, as a save and the next start do."""
    out = io.StringIO()
    config.write(out)
    back = configparser.RawConfigParser()
    back.read_string(out.getvalue())
    return back


# -- names ------------------------------------------------------------------------------


def test_a_name_is_the_first_line_that_is_not_blank():
    assert snippets.name_for("\n  cd /srv  \nls\n") == "cd /srv"


def test_a_long_first_line_is_cut_for_the_menus():
    name = snippets.name_for("x" * 100)

    assert len(name) == snippets.NAME_MAX
    assert name.endswith("…")


def test_a_text_with_nothing_but_blanks_is_named_as_written():
    assert snippets.name_for("\n") == repr("\n")


# -- the text in gcm.conf ---------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "printf 'a\\nb\\n'",
        "cd ",
        "  indented\n\tline\n",
        'quote " and backslash \\',
        "über ✓",
        "carriage\rreturn",
        "a = b ; c # d",
    ],
)
def test_a_text_comes_back_from_the_file_as_it_was(text):
    config = configparser.RawConfigParser()
    snippets.save(config, [Snippet("5e1ec7ed", "x", text)])

    [back] = snippets.load(through_a_file(config))

    assert back.text == text


def test_the_old_encoding_did_not_bring_a_command_back():
    """What custom commands were stored with: why snippets are not."""
    text = "printf 'a\\nb\\n'"

    assert snippets.legacy_decode(snippets.legacy_encode(text)) != text


@pytest.mark.parametrize(
    ("value", "text"),
    [
        ("echo hi", "echo hi"),
        ('"unterminated', '"unterminated'),
        ('"a" and "b"', '"a" and "b"'),
        ("12", "12"),
        ('"echo hi\\n"', "echo hi\n"),
    ],
)
def test_a_text_written_by_hand_is_taken_as_written(value, text):
    assert snippets.decode(value) == text


# -- records ----------------------------------------------------------------------------


def test_a_record_holds_what_it_has_and_nothing_empty():
    config = configparser.RawConfigParser()
    snippets.save(
        config,
        [
            Snippet("aa11bb22", "disk", "df -h", "F8", "ops/storage", "free space"),
            Snippet("cc33dd44", "up", "uptime"),
        ],
    )

    assert dict(config.items("snippet aa11bb22")) == {
        "name": "disk",
        "text": '"df -h"',
        "key": "F8",
        "folder": "ops/storage",
        "description": "free space",
    }
    assert dict(config.items("snippet cc33dd44")) == {"name": "up", "text": '"uptime"'}


def test_loading_takes_records_only_and_names_one_without_a_name():
    config = configparser.RawConfigParser()
    config.read_string(
        dedent("""\
            [host 1]
            name = web

            [snippet aa11bb22]
            text = "df -h"
            key =  F8

            [snippet cc33dd44]
            name = nothing to send

            [snippet ]
            name = no id
            text = uptime
            """)
    )

    first, second = snippets.load(config)

    assert first == Snippet("aa11bb22", "df -h", "df -h", "F8")
    assert (second.name, second.text) == ("no id", "uptime")
    assert len(second.id) == 2 * snippets.ID_BYTES


def test_ids_are_minted_apart_from_those_taken():
    taken = {snippets.new_snippet_id() for _ in range(50)}

    assert snippets.new_snippet_id(taken) not in taken


# -- custom commands --------------------------------------------------------------------


def legacy(pairs):
    config = configparser.RawConfigParser()
    config.add_section("shortcuts")
    config.set("shortcuts", "copy", "CTRL+SHIFT+C")
    for number, (key, command) in enumerate(pairs, 1):
        config.set("shortcuts", f"shortcut{number}", key)
        config.set("shortcuts", f"command{number}", command)
    return config


def test_custom_commands_become_snippets_with_their_keys_and_text():
    config = legacy([("ALT+R", "reboot\\nnow"), ("F8", "df -h")])

    migrated = snippets.migrate(config, [])

    assert [(s.name, s.text, s.key) for s in migrated] == [
        ("reboot", "reboot\nnow", "ALT+R"),
        ("df -h", "df -h", "F8"),
    ]
    assert len({s.id for s in migrated}) == 2


def test_a_command_whose_key_a_snippet_has_is_its_copy():
    """What a save writes back for an older GCM: taken again, it would be a duplicate."""
    config = legacy([("F8", "df -h"), ("F9", "added by an older GCM")])

    migrated = snippets.migrate(config, [Snippet("aa11bb22", "disk", "df -h", "F8")])

    assert [(s.text, s.key) for s in migrated] == [("added by an older GCM", "F9")]


def test_of_two_commands_with_one_key_the_later_is_kept():
    """It was the one the key sent."""
    config = legacy([("F8", "first"), ("F8", "second")])

    assert [s.text for s in snippets.migrate(config, [])] == ["second"]


def test_the_pairs_are_read_up_to_the_first_that_is_not_whole():
    config = legacy([("F7", "a"), ("F8", "b"), ("F9", "c")])
    config.remove_option("shortcuts", "command2")

    assert snippets.legacy_commands(config) == [("F7", "a")]
    assert snippets.legacy_commands(configparser.RawConfigParser()) == []


def test_of_snippets_with_one_key_the_last_keeps_it():
    library = [Snippet("1", "a", "a", "F8"), Snippet("2", "b", "b", "F8"), Snippet("3", "c", "c")]

    snippets.drop_repeated_keys(library)

    assert [s.key for s in library] == ["", "F8", ""]


# -- the menus --------------------------------------------------------------------------


def drawn(folder):
    return [(child.name, drawn(child)) for child in folder.folders] + [
        s.name for s in folder.snippets
    ]


def test_the_menus_file_snippets_by_folder_and_name():
    library = [
        Snippet("1", "restart", "r"),
        Snippet("2", "disk", "d", folder="ops/storage"),
        Snippet("3", "Apache logs", "a", folder=" ops /"),
        Snippet("4", "alpha", "x"),
        Snippet("5", "backup", "b", folder="Backups"),
    ]

    assert drawn(snippets.tree(library)) == [
        ("Backups", ["backup"]),
        ("ops", [("storage", ["disk"]), "Apache logs"]),
        "alpha",
        "restart",
    ]


# -- gcm.conf, through GCM's own load and save ------------------------------------------


@pytest.fixture
def gcm(app_module, monkeypatch, tmp_path):
    """GCM's loadConfig and writeConfig against a gcm.conf of the test's own."""
    config = tmp_path / "gcm.conf"
    monkeypatch.setattr(app_module, "CONFIG_FILE", str(config))
    monkeypatch.setattr(app_module, "groups", {})
    monkeypatch.setattr(app_module, "shortcuts", {})
    monkeypatch.setattr(app_module, "snippets", [])
    monkeypatch.setattr(app_module.crypto, "encrypt", lambda _pwd, value: value)
    monkeypatch.setattr(app_module.crypto, "decrypt", lambda _pwd, value, **_kw: value)

    def load():
        object.__new__(app_module.Wmain).loadConfig()

    def save():
        wmain = object.__new__(app_module.Wmain)
        wmain.hpMain = types.SimpleNamespace(get_position=lambda: 200)
        wmain.wMain = types.SimpleNamespace(is_maximized=lambda: False)
        wmain.get_collapsed_nodes = lambda: []
        wmain.get_collapsed_folder_ids = lambda: []
        wmain.writeConfig()

    def read():
        written = configparser.RawConfigParser()
        written.read(config)
        return written

    return types.SimpleNamespace(app=app_module, file=config, load=load, save=save, read=read)


OLD_GCM = dedent("""\
    [shortcuts]
    copy = CTRL+SHIFT+C
    shortcut1 = ALT+R
    command1 = reboot\\nnow
    shortcut2 = F8
    command2 = df -h
    """)


def test_custom_commands_become_snippets_once(gcm):
    gcm.file.write_text(OLD_GCM)

    gcm.load()
    found = [(s.id, s.name, s.text, s.key) for s in gcm.app.snippets]
    for _ in range(2):
        gcm.save()
        gcm.load()

    assert [(name, text, key) for _id, name, text, key in found] == [
        ("reboot", "reboot\nnow", "ALT+R"),
        ("df -h", "df -h", "F8"),
    ]
    assert [(s.id, s.name, s.text, s.key) for s in gcm.app.snippets] == found
    assert [name for name in gcm.read().sections() if name.startswith("snippet ")] == [
        f"snippet {snippet_id}" for snippet_id, *_ in found
    ]


def test_an_older_gcm_still_reads_its_custom_commands(gcm):
    gcm.file.write_text(OLD_GCM)
    gcm.load()
    gcm.save()

    written = gcm.read()

    assert snippets.legacy_commands(written) == [("ALT+R", "reboot\nnow"), ("F8", "df -h")]
    assert written.get("shortcuts", "copy") == "CTRL+SHIFT+C"


def test_a_command_an_older_gcm_added_is_taken_up(gcm):
    gcm.file.write_text(OLD_GCM)
    gcm.load()
    gcm.save()
    written = gcm.read()
    written.set("shortcuts", "shortcut3", "F9")
    written.set("shortcuts", "command3", "uptime")
    with gcm.file.open("w") as out:
        written.write(out)

    gcm.load()

    assert [(s.text, s.key) for s in gcm.app.snippets] == [
        ("reboot\nnow", "ALT+R"),
        ("df -h", "F8"),
        ("uptime", "F9"),
    ]


def test_a_snippets_key_is_bound_after_the_built_in_commands(gcm):
    """So that it keeps a key one of them also has, as the custom command did."""
    gcm.file.write_text(OLD_GCM.replace("ALT+R", "CTRL+SHIFT+C"))

    gcm.load()

    assert gcm.app.shortcuts["CTRL+SHIFT+C"] is gcm.app.snippets[0]


def test_of_two_records_with_one_key_the_later_keeps_it(gcm):
    """It is the one the key sends. The earlier is kept without it, so that the menus do
    not show the key on both."""
    gcm.file.write_text(
        dedent("""\
            [snippet aa11bb22]
            name = first
            text = "first"
            key = F8

            [snippet cc33dd44]
            name = second
            text = "second"
            key = F8
            """)
    )

    gcm.load()

    first, second = gcm.app.snippets
    assert (first.key, second.key) == ("", "F8")
    assert gcm.app.shortcuts["F8"] is second


def test_a_snippet_deleted_in_preferences_is_gone_from_gcm_conf(gcm):
    gcm.file.write_text(OLD_GCM)
    gcm.load()
    gcm.save()
    kept = gcm.app.snippets[1]
    wconfig = object.__new__(gcm.app.Wconfig)
    wconfig.library = [kept]  # the page's copies, the other deleted

    gcm.app.snippets = wconfig.kept_snippets()
    shortcuts: dict = {}
    gcm.app.bind_snippet_keys(shortcuts, gcm.app.snippets)
    gcm.app.shortcuts = shortcuts
    gcm.save()
    gcm.load()

    assert gcm.app.snippets == [kept]
    assert [name for name in gcm.read().sections() if name.startswith("snippet ")] == [
        f"snippet {kept.id}"
    ]
    assert snippets.legacy_commands(gcm.read()) == [("F8", "df -h")]


def test_a_snippet_without_a_key_is_kept(gcm):
    gcm.app.snippets = [Snippet("aa11bb22", "tail", "tail -f /var/log/syslog")]

    gcm.save()
    gcm.load()

    assert gcm.app.snippets == [Snippet("aa11bb22", "tail", "tail -f /var/log/syslog")]
    assert snippets.legacy_commands(gcm.read()) == []


# -- against real GTK -------------------------------------------------------------------

_SCRIPT = r'''
import os, sys, tempfile, time
scenario = sys.argv[1]
root = tempfile.mkdtemp()
os.environ["HOME"] = root; sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gdk, GLib, Gtk, Vte
from gnome_connection_manager import app

app.conf.CONFIRM_ON_CLOSE_TAB = 0
app.conf.STARTUP_LOCAL = False
# A session that types back what it is sent.
bin_dir = os.path.join(root, "bin")
os.makedirs(bin_dir)
app.SSH_BIN = os.path.join(bin_dir, "ssh")
with open(app.SSH_BIN, "w") as out:
    out.write("#!/bin/sh\necho session up\nexec cat\n")
os.chmod(app.SSH_BIN, 0o755)
# Started as GCM starts, so that its menubar and accelerators are there.
application = app.GcmApplication()
assert application.register(None)
application.activate()
app.wMain = w = application._controller
w.wMain.resize(1200, 800)
Snippet = app.snippetlib.Snippet
asked = []
answers = {}

def inputbox(title, text, default="", password=False, parent=None):
    asked.append((title, text))
    return answers.get(text)

app.inputbox = inputbox

def pump(seconds=0.2):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        Gtk.main_iteration_do(False)
        time.sleep(0.005)

def until(done, seconds=10):
    end = time.monotonic() + seconds
    while not done() and time.monotonic() < end:
        pump(0.05)

def text_of(item):
    """An item's text as drawn, or None for one without a label, a separator."""
    child = item.get_child()
    return child.get_text() if isinstance(child, Gtk.Label) else None

def drawn(menu):
    """What a menu shows: each item's text as drawn, a submenu as (text, its items)."""
    items = []
    for item in menu.get_children():
        submenu = item.get_submenu()
        items.append((text_of(item), drawn(submenu)) if submenu is not None else text_of(item))
    return items

def find(menu, text):
    for item in menu.get_children():
        if text_of(item) == text:
            return item.get_submenu()
        if item.get_submenu() is not None:
            found = find(item.get_submenu(), text)
            if found is not None:
                return found
    return None

def listed(prefs):
    """The Snippets page's list as drawn: a folder as (name, its rows)."""
    model = prefs.snippet_store

    def rows(parent):
        items = []
        row = model.iter_children(parent)
        while row is not None:
            name = model[row][0]
            items.append((name, rows(row)) if model[row][2] == "" else name)
            row = model.iter_next(row)
        return items

    return rows(None)

def press(window, keyval, state=0):
    """A key pressed and released in `window`, as GTK delivers one."""
    keymap = Gdk.Keymap.get_for_display(Gdk.Display.get_default())
    keyboard = Gdk.Display.get_default().get_default_seat().get_keyboard()
    found, keys = keymap.get_entries_for_keyval(keyval)
    for kind in (Gdk.EventType.KEY_PRESS, Gdk.EventType.KEY_RELEASE):
        event = Gdk.Event.new(kind)
        event.key.window = window.get_window()
        event.key.time = Gdk.CURRENT_TIME
        event.key.keyval = keyval
        event.key.state = state
        event.key.hardware_keycode, event.key.group = keys[0].keycode, keys[0].group
        event.set_device(keyboard)
        Gtk.main_do_event(event)
    pump(0.1)

def leave(widget):
    """The keyboard leaving `widget`, as GTK tells it when another widget takes it."""
    event = Gdk.Event.new(Gdk.EventType.FOCUS_CHANGE)
    event.focus_change.window = widget.get_window()
    event.focus_change.in_ = 0
    widget.send_focus_change(event)
    pump()

def pickers():
    return [win for win in Gtk.Window.list_toplevels() if isinstance(win, app.SnippetPicker) and win.get_visible()]

def open_host():
    # A name with a space, which a shell would quote: a snippet's values are not.
    host = app.Host("prod", "db 01", "", "10.9.9.9", "ops", "", "", "22", "", "ssh")
    w.addTab(w.nbConsole, host)
    terminal = app.page_terminal(w.nbConsole.get_nth_page(w.nbConsole.get_n_pages() - 1))
    until(lambda: "session up" in screen(terminal))
    return terminal

def screen(terminal):
    return terminal.get_text_format(Vte.Format.TEXT)

def send(snippet_id):
    application.activate_action("send-snippet", GLib.Variant("s", snippet_id))
    pump(0.3)

if scenario == "the-menus-list-snippets-by-name-in-folders":
    app.snippets = [
        Snippet("00000001", "restart_service", "systemctl restart x\r", "F8"),
        Snippet("00000002", "disk", "df -h\r", "", "ops/storage"),
        Snippet("00000003", "Apache logs", "tail -f error.log\r", "", "ops"),
        Snippet("00000004", "alpha", "echo alpha\r"),
    ]
    w.populateCommandsMenu()
    pump()
    # The picker, a separator, then the library.
    expected = [
        "Find Snippet…",
        None,
        ("ops", [("storage", ["disk"]), "Apache logs"]),
        "alpha",
        "[F8] restart_service",
    ]
    assert drawn(w.popupMenu.mnuCommands) == expected, drawn(w.popupMenu.mnuCommands)
    # The menubar reads "_" as a mnemonic, and drew restart_service as restartservice.
    menubar = find(w.menubar, "Snippets")
    assert drawn(menubar) == expected, drawn(menubar)

elif scenario == "a-menu-sends-a-snippet-filled-in-for-the-tab":
    terminal = open_host()
    app.snippets = [Snippet("00000001", "where", "echo {user}@{address} {name} {?Port}\r")]
    answers["Port"] = "2222"
    send("00000001")
    until(lambda: "ops@10.9.9.9 db 01 2222" in screen(terminal))
    assert "ops@10.9.9.9 db 01 2222" in screen(terminal), screen(terminal)
    assert asked == [("where", "Port")], asked

elif scenario == "a-label-is-asked-once-and-cancelling-sends-nothing":
    terminal = open_host()
    app.snippets = [Snippet("00000001", "copy", "cp {?File} {?Dest}/{?File}\r")]
    answers["File"] = "a.log"  # and Dest cancelled
    send("00000001")
    pump(0.5)
    assert asked == [("copy", "File"), ("copy", "Dest")], asked
    assert "cp" not in screen(terminal), screen(terminal)
    asked.clear()
    answers["Dest"] = "/tmp"
    send("00000001")
    until(lambda: "cp a.log /tmp/a.log" in screen(terminal))
    assert "cp a.log /tmp/a.log" in screen(terminal), screen(terminal)
    assert asked == [("copy", "File"), ("copy", "Dest")], asked

elif scenario == "a-snippets-key-sends-it":
    terminal = open_host()
    app.snippets = [Snippet("00000001", "disk", "df -h {name}\r", "F8")]
    app.bind_snippet_keys(app.shortcuts, app.snippets)
    w.wMain.set_focus(terminal)
    keymap = Gdk.Keymap.get_for_display(Gdk.Display.get_default())
    keyboard = Gdk.Display.get_default().get_default_seat().get_keyboard()
    for kind in (Gdk.EventType.KEY_PRESS, Gdk.EventType.KEY_RELEASE):
        event = Gdk.Event.new(kind)
        event.key.window = w.wMain.get_window()
        event.key.time = Gdk.CURRENT_TIME
        event.key.keyval = Gdk.KEY_F8
        found, keys = keymap.get_entries_for_keyval(Gdk.KEY_F8)
        event.key.hardware_keycode, event.key.group = keys[0].keycode, keys[0].group
        event.set_device(keyboard)
        Gtk.main_do_event(event)
    until(lambda: "df -h db 01" in screen(terminal))
    assert "df -h db 01" in screen(terminal), screen(terminal)

elif scenario == "the-snippets-page-edits-the-library":
    app.snippets = [
        Snippet("00000001", "disk", "df -h\r", "F8", "ops"),
        Snippet("00000002", "up", "uptime\r"),
    ]
    prefs = app.Wconfig()
    pump()
    notebook = prefs.get_widget("nbConfig")
    last = notebook.get_nth_page(notebook.get_n_pages() - 1)
    assert notebook.get_tab_label(last).get_text() == "Snippets"
    notebook.set_current_page(notebook.get_n_pages() - 1)
    pump()
    assert listed(prefs) == [("ops", ["disk"]), "up"], listed(prefs)
    fields, text = prefs.snippet_entries, prefs.snippet_text.get_buffer()
    assert not prefs.snippet_form.get_sensitive()  # nothing chosen yet
    prefs.choose_snippet("00000001")
    pump()
    shown = {field: entry.get_text() for field, entry in fields.items()}
    assert shown == {"name": "disk", "folder": "ops", "key": "F8", "description": ""}, shown
    assert text.get_text(text.get_start_iter(), text.get_end_iter(), False) == "df -h\r"
    fields["name"].set_text("Disk usage")
    assert listed(prefs) == [("ops", ["Disk usage"]), "up"], listed(prefs)
    fields["folder"].set_text("ops/storage")
    fields["folder"].emit("activate")
    assert listed(prefs) == [("ops", [("storage", ["Disk usage"])]), "up"], listed(prefs)
    text.set_text("df -hT\r")
    prefs.on_add_snippet(None)  # in the folder of the snippet chosen
    pump()
    assert fields["folder"].get_text() == "ops/storage"
    text.set_text("du -sh .\r")  # and no name: listed by its first line
    prefs.choose_snippet("00000002")
    prefs.on_delete_snippet(None)
    pump()
    assert listed(prefs) == [("ops", [("storage", ["Disk usage", "du -sh ."])])], listed(prefs)
    prefs.on_okbutton1_clicked(None)
    pump()
    disk, du = app.snippets
    assert disk == Snippet("00000001", "Disk usage", "df -hT\r", "F8", "ops/storage"), disk
    assert (du.name, du.text, du.key, du.folder) == ("du -sh .", "du -sh .\r", "", "ops/storage")
    assert app.shortcuts["F8"] is disk
    written = open(app.CONFIG_FILE).read()
    assert "[snippet 00000001]" in written and "[snippet 00000002]" not in written, written
    assert drawn(w.popupMenu.mnuCommands)[2:] == [
        ("ops", [("storage", ["[F8] Disk usage", "du -sh ."])])
    ], drawn(w.popupMenu.mnuCommands)

elif scenario == "add-in-the-folder-chosen":
    app.snippets = [Snippet("00000001", "disk", "df -h\r", "", "ops/storage")]
    prefs = app.Wconfig()
    pump()
    notebook = prefs.get_widget("nbConfig")
    notebook.set_current_page(notebook.get_n_pages() - 1)
    pump()
    store = prefs.snippet_store
    storage = store.iter_children(store.get_iter_first())
    assert store[storage][0] == "storage", store[storage][0]
    prefs.snippet_view.get_selection().select_iter(storage)
    pump()
    # A folder is chosen: there is no snippet to edit or delete.
    assert not prefs.snippet_form.get_sensitive()
    assert not prefs.btnDeleteSnippet.get_sensitive()
    prefs.on_add_snippet(None)
    pump()
    assert prefs.snippet_form.get_sensitive()
    fields = prefs.snippet_entries
    assert fields["folder"].get_text() == "ops/storage", fields["folder"].get_text()
    prefs.snippet_text.get_buffer().set_text("uptime\r")
    # Listed by its first line as it is typed.
    assert listed(prefs) == [("ops", [("storage", ["disk", "uptime"])])], listed(prefs)
    # Typed carelessly, and filed again once the field is left.
    fields["name"].set_text("  load ")
    fields["folder"].set_text(" ops / checks/ ")
    fields["description"].set_text(" how busy it is ")
    leave(fields["folder"])
    assert listed(prefs) == [("ops", [("checks", ["  load "]), ("storage", ["disk"])])], listed(prefs)
    prefs.on_okbutton1_clicked(None)
    pump()
    kept = [(each.name, each.folder, each.description) for each in app.snippets]
    assert kept == [("disk", "ops/storage", ""), ("load", "ops/checks", "how busy it is")], kept
    # What the next start reads is what the library holds.
    import configparser
    written = configparser.RawConfigParser()
    written.read(app.CONFIG_FILE)
    assert app.snippetlib.load(written) == app.snippets, app.snippetlib.load(written)

elif scenario == "cancel-drops-the-page-edits":
    app.snippets = [Snippet("00000001", "disk", "df -h\r", "F8")]
    prefs = app.Wconfig()
    pump()
    prefs.choose_snippet("00000001")
    prefs.snippet_entries["name"].set_text("changed")
    prefs.on_delete_snippet(None)
    prefs.on_cancelbutton1_clicked(None)
    pump()
    assert app.snippets == [Snippet("00000001", "disk", "df -h\r", "F8")], app.snippets

elif scenario == "the-key-field-takes-a-key":
    app.snippets = [Snippet("00000001", "disk", "df -h\r", "F8")]
    prefs = app.Wconfig()
    pump()
    # Its widgets take keys once the page is shown, as it is when someone uses it.
    notebook = prefs.get_widget("nbConfig")
    notebook.set_current_page(notebook.get_n_pages() - 1)
    pump()
    prefs.choose_snippet("00000001")
    field = prefs.snippet_entries["key"]
    window = prefs.get_widget("wConfig")
    window.set_focus(field)
    for keyval, state, expected in (
        (Gdk.KEY_Shift_L, 0, "F8"),  # a modifier alone waits for its key
        (Gdk.KEY_a, 0, "F8"),  # a key that types is refused
        (Gdk.KEY_space, 0, "F8"),
        (Gdk.KEY_A, Gdk.ModifierType.SHIFT_MASK, "F8"),  # Shift only types a capital
        (Gdk.KEY_F9, 0, "F9"),
        (Gdk.KEY_r, Gdk.ModifierType.CONTROL_MASK, "CTRL+R"),
        (Gdk.KEY_BackSpace, 0, ""),
    ):
        press(window, keyval, state)
        assert field.get_text() == expected, (Gdk.keyval_name(keyval), field.get_text())
    # The list shows the key the snippet has now.
    assert prefs.snippet_store[prefs.snippet_row("00000001")][1] == ""
    # Only a key pressed is a key: nothing can be pasted there.
    Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text("rm -rf /", -1)
    field.emit("paste-clipboard")
    pump(0.3)
    assert field.get_text() == "", field.get_text()
    press(window, Gdk.KEY_Tab)  # moves on, as it does from any field
    assert window.get_focus() is prefs.snippet_entries["description"], window.get_focus()
    assert field.get_text() == ""
    prefs.on_okbutton1_clicked(None)
    pump()
    assert app.snippets[0].key == "" and "F8" not in app.shortcuts, app.snippets
    # Escape closes Preferences, as it does from any field.
    prefs = app.Wconfig()
    pump()
    notebook = prefs.get_widget("nbConfig")
    notebook.set_current_page(notebook.get_n_pages() - 1)
    pump()
    prefs.choose_snippet("00000001")
    window = prefs.get_widget("wConfig")
    window.set_focus(prefs.snippet_entries["key"])
    press(window, Gdk.KEY_Escape)
    assert not window.get_visible()

elif scenario == "the-picker-finds-a-snippet-and-sends-it":
    terminal = open_host()
    app.snippets = [
        Snippet("00000001", "disk", "df -h {name}\r", "", "ops"),
        Snippet("00000002", "disk free inodes", "df -i\r", "", "ops"),
        Snippet("00000003", "up", "uptime\r", "", "", "how long it has been up"),
    ]
    # Opened from the menubar, say, with the keyboard in the server tree: once addTab's
    # timer has given the new console the keyboard a second time, 200 ms on.
    pump(0.3)
    w.wMain.set_focus(w.treeServers)
    pump()
    assert w.wMain.get_focus() is w.treeServers, w.wMain.get_focus()
    picker = w.show_snippet_picker(terminal)
    pump()
    found = lambda: [row[0] for row in picker.found]
    rows = [(row[0], row[1], row[2]) for row in picker.found]
    assert rows == [("disk", "ops", ""), ("disk free inodes", "ops", ""), ("up", "", "")], rows
    for search, expected in (
        ("DISK ops", ["disk", "disk free inodes"]),  # a word in any field
        ("disk inodes", ["disk free inodes"]),  # and every word
        ("long", ["up"]),  # the description
        ("-i", ["disk free inodes"]),  # the text
        ("df", ["disk", "disk free inodes"]),
    ):
        picker.search.set_text(search)
        until(lambda: found() == expected, 3)
        assert found() == expected, (search, found())
    picker.set_focus(picker.search)
    chosen = lambda: picker.chosen().name
    assert chosen() == "disk", chosen()  # the first found
    press(picker, Gdk.KEY_Up)  # already the first
    assert chosen() == "disk", chosen()
    press(picker, Gdk.KEY_Down)
    press(picker, Gdk.KEY_Down)  # already the last
    assert chosen() == "disk free inodes", chosen()
    press(picker, Gdk.KEY_Return)
    until(lambda: "df -i" in screen(terminal))
    assert "df -i" in screen(terminal), screen(terminal)
    assert "df -h" not in screen(terminal), screen(terminal)
    assert not pickers()
    # The keyboard is in the console it was sent to.
    assert w.wMain.get_focus() is terminal, w.wMain.get_focus()
    # A row activated, as a double-click does, sends it too.
    picker = w.show_snippet_picker(terminal)
    pump()
    picker.view.row_activated(Gtk.TreePath.new_from_indices([2]), picker.view.get_column(0))
    until(lambda: "uptime" in screen(terminal))
    assert "uptime" in screen(terminal), screen(terminal)
    assert not pickers()

elif scenario == "escape-closes-the-picker":
    terminal = open_host()
    app.snippets = [Snippet("00000001", "up", "uptime\r")]
    w.wMain.set_focus(terminal)
    picker = w.show_snippet_picker(terminal)
    pump()
    picker.set_focus(picker.search)
    # While it is open, what is typed at the main window goes to it, not the console.
    press(w.wMain, Gdk.KEY_x)
    assert picker.search.get_text() == "x", picker.search.get_text()
    press(picker, Gdk.KEY_Escape)
    pump(0.3)
    assert not pickers()
    assert "uptime" not in screen(terminal) and "x" not in screen(terminal), screen(terminal)

elif scenario == "the-pickers-key-opens-it":
    terminal = open_host()
    app.snippets = [Snippet("00000001", "up", "uptime\r")]
    # An accelerator, from the shortcuts table, as every terminal command's is.
    assert application.get_accels_for_action("app.find-snippet") == ["<Primary><Shift>p"], (
        application.get_accels_for_action("app.find-snippet")
    )
    w.wMain.set_focus(terminal)
    press(w.wMain, Gdk.KEY_P, Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK)
    pickers = [win for win in Gtk.Window.list_toplevels() if isinstance(win, app.SnippetPicker)]
    assert len(pickers) == 1 and pickers[0].terminal is terminal, pickers

else:
    raise SystemExit("no scenario " + scenario)
print("OK")
'''


@pytest.mark.parametrize(
    "scenario",
    [
        "the-menus-list-snippets-by-name-in-folders",
        "a-menu-sends-a-snippet-filled-in-for-the-tab",
        "a-label-is-asked-once-and-cancelling-sends-nothing",
        "a-snippets-key-sends-it",
        "the-snippets-page-edits-the-library",
        "add-in-the-folder-chosen",
        "cancel-drops-the-page-edits",
        "the-key-field-takes-a-key",
        "the-picker-finds-a-snippet-and-sends-it",
        "escape-closes-the-picker",
        "the-pickers-key-opens-it",
    ],
)
def test_snippets_against_real_gtk(scenario):
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
    assert "Traceback" not in result.stderr, result.stderr[-3000:]
    # A key sent to a page not yet shown is dropped with a critical, and passed a test
    # that expected the key to change nothing.
    assert glib_complaints(result.stderr) == [], result.stderr[-3000:]
