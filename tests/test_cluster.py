"""The cluster window's Hide input toggle (#237), and its Snippets menu (#240).

The cluster window sends a line to every console selected in it, which is how a `sudo`
password prompt on several hosts is answered at once. Its text box showed the password
as it was typed, and kept it for Ctrl+Up to bring back. GTK 3's text view cannot mask
text, so the toggle swaps in an entry that can.

Its Snippets menu sends a snippet to every console selected, each with its own host's
values, asking for a `{?Label}` once for them all.

Each scenario runs against real GTK, in a process of its own, with real tabs, and types
into the window with key events delivered as GTK delivers a key typed. What reaches the
consoles is recorded at vte_feed, which the window sends through.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_connections import glib_complaints

_SCRIPT = r'''
import os, sys, tempfile, time
scenario = sys.argv[1]
os.environ["HOME"] = tempfile.mkdtemp(); sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk, Gdk, GLib, Vte
from gnome_connection_manager import app

app.conf.CONFIRM_ON_CLOSE_TAB = 0
app.conf.STARTUP_LOCAL = False  # only the tabs each scenario opens
app.wMain = w = app.Wmain(application=None)

def pump(seconds=0.2):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        Gtk.main_iteration_do(False)
        time.sleep(0.005)

sent = []
app.vte_feed = lambda terminal, text: sent.append((terminal.name, text))

for name in ("A", "B", "C"):
    w.addTab(w.nbConsole, app.Host("", name))
pump(0.5)

opened = []

class Cluster(app.Wcluster):
    def __init__(self, *args, **kwargs):
        opened.append(self)
        super().__init__(*args, **kwargs)

app.Wcluster = Cluster
Snippet = app.snippetlib.Snippet
asked = []
answers = []

def inputbox(title, text, default="", password=False, parent=None):
    asked.append((title, text, parent))
    return answers.pop(0) if answers else None

app.inputbox = inputbox

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

def open_cluster():
    """The window as Servers > Cluster opens it, with A and B chosen and C not."""
    w.on_btnCluster_clicked(None)
    pump(0.3)
    cluster = opened[-1]
    for row in cluster.treeStore:
        row[2].name = row[1].strip()
        if row[2].name in ("A", "B"):
            cluster.on_active_toggled(None, row.path)
    return cluster

def key(dialog, keyval, state=0):
    """A key pressed and let go, through the window, as a key typed is."""
    keymap = Gdk.Keymap.get_for_display(Gdk.Display.get_default())
    keyboard = Gdk.Display.get_default().get_default_seat().get_keyboard()
    for kind in (Gdk.EventType.KEY_PRESS, Gdk.EventType.KEY_RELEASE):
        event = Gdk.Event.new(kind)
        event.key.window = dialog.get_window()
        event.key.time = Gdk.CURRENT_TIME
        event.key.state = state
        event.key.keyval = keyval
        found, keys = keymap.get_entries_for_keyval(keyval)
        event.key.hardware_keycode, event.key.group = keys[0].keycode, keys[0].group
        event.set_device(keyboard)
        Gtk.main_do_event(event)
    pump(0.05)

def type_text(dialog, text):
    for char in text:
        key(dialog, Gdk.unicode_to_keyval(ord(char)))

def shown(cluster):
    """Which of the inputs is drawn, by what is mapped, not what the model says."""
    names = ("scrolledwindow6", "txtHiddenCommand", "label53")
    return {name: cluster.get_widget(name).get_mapped() for name in names}

TEXT_BOX = {"scrolledwindow6": True, "txtHiddenCommand": False, "label53": True}
HIDDEN = {"scrolledwindow6": False, "txtHiddenCommand": True, "label53": False}

if scenario == "hidden-input-is-masked-and-sent":
    cluster = open_cluster()
    dialog = cluster.get_widget("wCluster")
    entry = cluster.get_widget("txtHiddenCommand")
    assert shown(cluster) == TEXT_BOX, shown(cluster)
    cluster.get_widget("chkHideInput").set_active(True)
    pump()
    assert shown(cluster) == HIDDEN, shown(cluster)
    assert dialog.get_focus() == entry, dialog.get_focus()
    type_text(dialog, "s3cret")
    assert entry.get_text() == "s3cret", entry.get_text()
    # What is drawn: as many masking characters, and not the text.
    drawn = entry.get_layout().get_text()
    assert len(drawn) == 6 and "s3cret" not in drawn and len(set(drawn)) == 1, drawn
    key(dialog, Gdk.KEY_Return)
    assert sent == [("A", "s3cret\r"), ("B", "s3cret\r")], sent
    assert entry.get_text() == "", entry.get_text()
    assert cluster.get_widget("txtCommands1").history == [], cluster.get_widget("txtCommands1").history
    # Still hidden, for the next prompt.
    assert shown(cluster) == HIDDEN and dialog.get_focus() == entry

elif scenario == "the-history-never-holds-a-hidden-line":
    cluster = open_cluster()
    dialog = cluster.get_widget("wCluster")
    box = cluster.get_widget("txtCommands1")
    toggle = cluster.get_widget("chkHideInput")
    box.grab_focus()
    type_text(dialog, "uptime")
    key(dialog, Gdk.KEY_Return)
    toggle.set_active(True)
    pump()
    type_text(dialog, "pw")
    key(dialog, Gdk.KEY_Return)
    toggle.set_active(False)
    pump()
    assert sent == [("A", "uptime\r"), ("B", "uptime\r"), ("A", "pw\r"), ("B", "pw\r")], sent
    assert shown(cluster) == TEXT_BOX, shown(cluster)
    assert dialog.get_focus() == box, dialog.get_focus()
    buffer = box.get_buffer()
    recalled = []
    for _ in range(2):
        key(dialog, Gdk.KEY_Up, Gdk.ModifierType.CONTROL_MASK)
        recalled.append(buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False))
    assert recalled == ["uptime", ""], recalled

elif scenario == "nothing-half-typed-is-kept":
    cluster = open_cluster()
    dialog = cluster.get_widget("wCluster")
    entry = cluster.get_widget("txtHiddenCommand")
    toggle = cluster.get_widget("chkHideInput")
    toggle.set_active(True)
    pump()
    type_text(dialog, "abc")
    toggle.set_active(False)
    pump()
    assert entry.get_text() == "", entry.get_text()
    toggle.set_active(True)
    pump()
    assert entry.get_text() == "", entry.get_text()
    assert sent == [], sent

elif scenario == "the-toggle-starts-off":
    cluster = open_cluster()
    cluster.get_widget("chkHideInput").set_active(True)
    pump()
    cluster.get_widget("wCluster").destroy()
    pump()
    cluster = open_cluster()
    assert not cluster.get_widget("chkHideInput").get_active()
    assert shown(cluster) == TEXT_BOX, shown(cluster)

elif scenario == "the-snippets-button-drops-down-the-library":
    app.snippets = []
    cluster = open_cluster()
    assert not cluster.btnSnippets.get_sensitive()  # nothing to send
    cluster.get_widget("wCluster").destroy()
    pump()
    app.snippets = [
        Snippet("00000001", "disk", "df -h\r", "F8", "ops"),
        Snippet("00000002", "up", "uptime\r"),
    ]
    cluster = open_cluster()
    button = cluster.btnSnippets
    close = cluster.get_widget("cancelbutton2")
    pump()
    # Drawn in the row of buttons, at the other end from Close, with an arrow.
    assert button.get_mapped() and button.get_sensitive()
    assert button.get_parent() is close.get_parent()
    assert button.get_allocation().x < cluster.get_widget("wCluster").get_allocated_width() / 2
    assert button.get_image() is not None and button.get_image().get_mapped()
    assert button.get_allocation().x < close.get_allocation().x, (
        button.get_allocation().x, close.get_allocation().x)
    # What it drops down. Not dropped down here: a menu needs the pointer to itself, and
    # with scenarios running at once on one display, another can hold it.
    menu = button.get_popup()
    assert drawn(menu) == [("ops", ["[F8] disk"]), "up"], drawn(menu)

elif scenario == "a-snippet-goes-to-each-console-chosen":
    app.snippets = [Snippet("00000001", "greet", "echo {name} {?Word}\r", "", "ops")]
    cluster = open_cluster()
    dialog = cluster.get_widget("wCluster")
    [folder] = cluster.btnSnippets.get_popup().get_children()
    [item] = folder.get_submenu().get_children()
    item.activate()  # and the question cancelled
    pump()
    assert asked == [("greet", "Word", dialog)] and sent == [], (asked, sent)
    answers.append("hi")
    item.activate()
    pump()
    # Asked once for them all, over this window, and each with its own host's name.
    assert asked == [("greet", "Word", dialog)] * 2, asked
    assert sent == [("A", "echo A hi\r"), ("B", "echo B hi\r")], sent
    # With no console chosen, nothing is asked, and nothing sent.
    cluster.on_btnNone_clicked(None)
    asked.clear()
    sent.clear()
    item.activate()
    pump()
    assert asked == [] and sent == [], (asked, sent)

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
        "hidden-input-is-masked-and-sent",
        "the-history-never-holds-a-hidden-line",
        "nothing-half-typed-is-kept",
        "the-toggle-starts-off",
    ],
)
def test_the_cluster_windows_hidden_input_against_real_gtk(scenario):
    _run(scenario)


@pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"),
    reason="needs a display for a real terminal",
)
@pytest.mark.parametrize(
    "scenario",
    ["the-snippets-button-drops-down-the-library", "a-snippet-goes-to-each-console-chosen"],
)
def test_the_cluster_windows_snippets_against_real_gtk(scenario):
    stderr = _run(scenario)
    assert not glib_complaints(stderr), stderr[-3000:]


def _run(scenario):
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
    return result.stderr
