"""Tests for selected Wmain helpers that depend on tree/host interactions."""

from __future__ import annotations

import configparser
import inspect
import os
import re
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

from gnome_connection_manager.utils import logpaths, shortcuts


class FakeIter:
    def __init__(self, label: str, host=None, has_child: bool = False):
        self.label = label
        self.host = host
        self.has_child = has_child


class FakeTreeModel:
    def __init__(self):
        self._iters: dict[str, FakeIter] = {}

    def register(self, path: str, host=None, has_child: bool = False) -> FakeIter:
        iter_ = FakeIter(path, host=host, has_child=has_child)
        self._iters[path] = iter_
        return iter_

    def get_iter(self, path: str):
        return self._iters[path]

    def get_value(self, iter_, column: int):
        if column == 0:
            return iter_.label
        if column == 1:
            return iter_.host
        raise ValueError("unsupported column")

    def iter_has_child(self, iter_):
        return iter_.has_child


class FakeSelection:
    def __init__(self, model, iter_):
        self.model = model
        self.iter = iter_

    def get_selected(self):
        return self.model, self.iter


class FakeTreeView:
    def __init__(self, selection):
        self._selection = selection

    def get_selection(self):
        return self._selection


class DummyTreeStore:
    def __init__(self):
        self.rows: list[tuple] = []
        self.folders: dict[str, list[str]] = {}
        self.root_nodes: list[DummyTreeNode] = []

    def clear(self):
        self.rows.clear()
        self.folders.clear()
        self.root_nodes.clear()

    def prepend(self, parent, row):
        self.rows.insert(0, row)
        node = DummyTreeNode(row[0])
        if parent:
            parent.add_child(node)
        else:
            self.root_nodes.append(node)
        return node

    def append(self, parent, row):
        node = DummyTreeNode(row[0], host=row[1])
        if parent:
            parent.add_child(node)
        else:
            self.root_nodes.append(node)
        return node

    def foreach(self, callback, nodes=None):
        return None

    def get_objects(self):
        return []


class DummyMenu:
    def __init__(self):
        self.children = []

    def foreach(self, callback):
        self.children.clear()

    def prepend(self, item):
        self.children.insert(0, item)

    def append(self, item):
        self.children.append(item)

    def remove(self, item):
        if item in self.children:
            self.children.remove(item)

    def get_children(self):
        return list(self.children)


class DummyMenuItem:
    def __init__(self, label):
        self._label = label
        self._submenu = None
        self._callbacks = []

    def set_submenu(self, menu):
        self._submenu = menu

    def get_submenu(self):
        return self._submenu

    def get_children(self):
        return []

    def get_label(self):
        return self._label

    def show(self):
        pass

    def connect(self, *args):
        self._callbacks.append(args)


class MenuItemStub:
    def __init__(self, shortcut, label):
        self.shortcut = shortcut
        self.label = label
        self.action_name = None
        self.target_value = None

    def set_action_name(self, name):
        self.action_name = name

    def set_action_target_value(self, value):
        self.target_value = value


class TrackingTreeModel:
    def __init__(self, owner):
        self.owner = owner
        self.folder_rows: list[tuple[str, str]] = []
        self.host_rows: list[list] = []

    def clear(self):
        self.folder_rows.clear()
        self.host_rows.clear()

    def prepend(self, parent, row):
        path = getattr(self.owner, "_pending_path", "")
        node = types.SimpleNamespace(label=row[0])
        handle = types.SimpleNamespace(iter=node)
        self.owner.folder_nodes[path] = handle
        self.folder_rows.append((path, row[0]))
        return handle

    def append(self, parent, row):
        self.host_rows.append(row)
        return types.SimpleNamespace(iter=None)


class DeletionTreeModel:
    """Minimal tree model to exercise delete logic."""

    def __init__(self, label: str, host=None, has_child: bool = False, child_host=None):
        self.selection_iter = object()
        self.selection_label = label
        self.selection_host = host
        self.selection_has_child = has_child
        self.child_iter = object() if has_child else None
        self.child_host = child_host
        self.child_label = child_host.name if child_host else ""

    def get_value(self, iter_, column: int):
        if iter_ is self.selection_iter:
            return self.selection_label if column == 0 else self.selection_host
        if iter_ is self.child_iter:
            return self.child_label if column == 0 else self.child_host
        raise ValueError("Unknown iter")

    def iter_has_child(self, iter_):
        return iter_ is self.selection_iter and self.selection_has_child

    def iter_children(self, iter_):
        return self.child_iter if iter_ is self.selection_iter else None

    def iter_parent(self, iter_):
        return self.selection_iter if iter_ is self.child_iter else None


def make_host(app_module):
    return app_module.Host(
        "ops/prod",
        "router",
        "edge router",
        "router.example.com",
        "netops",
        "secret",
        "/home/netops/.ssh/id_rsa",
        "2200",
        "L8080:localhost:80",
        "ssh",
        "echo hello\nrun-checks",
        "30",
        "#111111",
        "#222222",
        True,
        True,
        False,
        "5",
        "-oStrictHostKeyChecking=no",
        True,
        7,
        8,
        "xterm-256color",
    )


def make_wmain_with_host(app_module, host, has_child=False):
    model = FakeTreeModel()
    iter_ = model.register(
        "ops/prod/router", host=host if not has_child else None, has_child=has_child
    )
    selection = FakeSelection(model, iter_)
    tree = FakeTreeView(selection)

    wmain = object.__new__(app_module.Wmain)
    wmain.treeModel = model
    wmain.treeServers = tree
    wmain._context_tree_path = None
    return wmain, iter_


def make_wmain_for_tree(app_module):
    wmain = object.__new__(app_module.Wmain)
    wmain.folder_nodes = {}
    wmain.menu_nodes = {}
    wmain.treeModel = TrackingTreeModel(wmain)
    wmain.menuServers = DummyMenu()
    wmain.nbConsole = object()
    wmain.get_collapsed_nodes = lambda: []
    wmain.set_collapsed_nodes = lambda: None
    wmain.update_row_color = lambda *args: None
    wmain.addTab = lambda nb, host: None
    return wmain


def test_get_selected_host_returns_none_for_group(app_module):
    host = make_host(app_module)
    wmain, iter_ = make_wmain_with_host(app_module, host, has_child=True)

    assert wmain.get_selected_host() is None


def test_get_selected_host_returns_host_for_leaf(app_module):
    host = make_host(app_module)
    wmain, iter_ = make_wmain_with_host(app_module, host)

    assert wmain.get_selected_host() is host


def test_duplicate_selected_host_clones_entry(monkeypatch, app_module):
    host = make_host(app_module)
    wmain, iter_ = make_wmain_with_host(app_module, host)
    monkeypatch.setattr(app_module, "groups", {"ops/prod": [host]})

    calls = {"write": 0, "tree": 0}
    wmain.updateTree = lambda: calls.__setitem__("tree", calls["tree"] + 1)
    wmain.writeConfig = lambda: calls.__setitem__("write", calls["write"] + 1)
    wmain.get_group = lambda _iter: "ops/prod"

    wmain.duplicate_selected_host()

    cloned_hosts = app_module.groups["ops/prod"]
    assert len(cloned_hosts) == 2
    assert cloned_hosts[1].name == "router (copy)"
    assert calls["write"] == 1
    assert calls["tree"] == 1


def test_copy_selected_address_sets_clipboard(monkeypatch, app_module):
    host = make_host(app_module)
    wmain, iter_ = make_wmain_with_host(app_module, host)

    clipboard = ClipboardStub()
    monkeypatch.setattr(app_module.Gdk.Display, "get_default", lambda: object())
    monkeypatch.setattr(app_module.Gtk.Clipboard, "get_default", lambda *_args: clipboard)

    wmain.copy_selected_address()

    assert clipboard.text == host.host
    assert clipboard.length == len(host.host)
    assert clipboard.stored is True


def test_populate_commands_menu_adds_custom_entries(monkeypatch, app_module):
    wmain = object.__new__(app_module.Wmain)
    wmain.popupMenu = types.SimpleNamespace(mnuCommands=DummyMenu())
    created_items = []

    class CommandsModel:
        def __init__(self):
            self.items = []
            self.cleared = 0

        def remove_all(self):
            self.cleared += 1
            self.items = []

        def append_item(self, item):
            self.items.append(item)

    commands_model = CommandsModel()
    monkeypatch.setattr(
        app_module.Gtk.Application,
        "get_default",
        lambda: types.SimpleNamespace(commands_menu=commands_model),
        raising=False,
    )

    def fake_create(shortcut, label):
        item = MenuItemStub(shortcut, label)
        created_items.append(item)
        return item

    wmain.createMenuItem = fake_create
    monkeypatch.setattr(
        app_module,
        "shortcuts",
        {
            "CTRL+C": app_module._COPY,
            "ALT+R": "run reboot now",
        },
    )

    wmain.populateCommandsMenu()

    # only the non-list entry is a user command; _COPY is a built-in
    assert len(created_items) == 1
    assert len(wmain.popupMenu.mnuCommands.children) == 1
    item = wmain.popupMenu.mnuCommands.children[0]
    assert item.shortcut == "ALT+R"
    assert item.action_name == "app.custom-command"
    assert commands_model.cleared == 1
    assert len(commands_model.items) == 1


def test_populate_commands_menu_without_an_application(monkeypatch, app_module):
    """The popup menu must still fill in even if the menu model is unavailable."""
    wmain = object.__new__(app_module.Wmain)
    wmain.popupMenu = types.SimpleNamespace(mnuCommands=DummyMenu())
    wmain.createMenuItem = lambda shortcut, label: MenuItemStub(shortcut, label)
    monkeypatch.setattr(app_module.Gtk.Application, "get_default", lambda: None, raising=False)
    monkeypatch.setattr(app_module, "shortcuts", {"ALT+R": "run reboot now"})

    wmain.populateCommandsMenu()

    assert len(wmain.popupMenu.mnuCommands.children) == 1


def test_get_context_tree_iter_prefers_context_path(app_module):
    host = make_host(app_module)
    wmain, iter_ = make_wmain_with_host(app_module, host)
    explicit_iter = FakeIter("explicit", host=host)
    wmain.treeModel._iters["explicit"] = explicit_iter
    wmain._context_tree_path = "explicit"

    assert wmain.get_context_tree_iter() is explicit_iter


def test_on_btnDel_clicked_removes_host(monkeypatch, app_module):
    host = make_host(app_module)
    model = DeletionTreeModel(label=host.name, host=host, has_child=False)
    selection = FakeSelection(model, model.selection_iter)
    tree = FakeTreeView(selection)

    wmain = object.__new__(app_module.Wmain)
    wmain.treeModel = model
    wmain.treeServers = tree
    calls = {"tree": 0, "write": 0}
    wmain.updateTree = lambda: calls.__setitem__("tree", calls["tree"] + 1)
    wmain.writeConfig = lambda: calls.__setitem__("write", calls["write"] + 1)

    monkeypatch.setattr(app_module, "groups", {host.group: [host]})
    monkeypatch.setattr(app_module, "msgconfirm", lambda _text: app_module.Gtk.ResponseType.OK)

    wmain.on_btnDel_clicked(None)

    assert app_module.groups[host.group] == []
    assert calls["tree"] == 1
    assert calls["write"] == 1


def test_on_btnDel_clicked_removes_group(monkeypatch, app_module):
    parent_host = make_host(app_module)
    child_host = parent_host.clone()
    child_host.group = f"{parent_host.group}/child"
    model = DeletionTreeModel(label="ops", host=None, has_child=True, child_host=parent_host)
    selection = FakeSelection(model, model.selection_iter)
    tree = FakeTreeView(selection)

    wmain = object.__new__(app_module.Wmain)
    wmain.treeModel = model
    wmain.treeServers = tree
    calls = {"tree": 0, "write": 0}
    wmain.updateTree = lambda: calls.__setitem__("tree", calls["tree"] + 1)
    wmain.writeConfig = lambda: calls.__setitem__("write", calls["write"] + 1)

    monkeypatch.setattr(
        app_module,
        "groups",
        {
            parent_host.group: [parent_host],
            child_host.group: [child_host],
        },
    )
    monkeypatch.setattr(app_module, "msgconfirm", lambda _text: app_module.Gtk.ResponseType.OK)

    wmain.on_btnDel_clicked(None)

    assert parent_host.group not in app_module.groups
    assert child_host.group not in app_module.groups
    assert calls["tree"] == 1
    assert calls["write"] == 1


def test_set_context_terminal_tracks_terminal_state(app_module, monkeypatch):
    wmain = object.__new__(app_module.Wmain)
    terminal = app_module.Vte.Terminal()
    called = {"sync": 0}
    wmain.sync_console_log_action = lambda term: called.__setitem__("sync", called["sync"] + 1)

    wmain.set_context_terminal(terminal)

    assert wmain._context_terminal is terminal
    assert wmain.current is terminal
    assert called["sync"] == 1

    wmain.clear_context_terminal()
    assert wmain._context_terminal is None


def test_get_target_terminal_prefers_context_then_active_then_current(app_module, monkeypatch):
    wmain = object.__new__(app_module.Wmain)
    wmain.hpMain = object()
    ctx = app_module.Vte.Terminal()
    active = app_module.Vte.Terminal()
    fallback = app_module.Vte.Terminal()
    wmain._context_terminal = ctx
    wmain.find_active_terminal = lambda widget: active
    wmain.current = fallback

    assert wmain.get_target_terminal() is ctx

    wmain._context_terminal = None
    assert wmain.get_target_terminal() is active

    wmain.find_active_terminal = lambda widget: None
    assert wmain.get_target_terminal() is fallback


def test_run_custom_command_invokes_vte_feed(monkeypatch, app_module):
    wmain = object.__new__(app_module.Wmain)
    terminal = app_module.Vte.Terminal()
    wmain.get_target_terminal = lambda: terminal
    fed: dict = {}
    monkeypatch.setattr(app_module, "vte_feed", lambda term, data: fed.setdefault("data", data))

    wmain.run_custom_command("echo hi")

    assert fed["data"] == "echo hi"


class PaneStub:
    def __init__(self, position):
        self._position = position
        self.previous_position = 150
        self.positions = []

    def set_position(self, value):
        self.positions.append(value)
        self._position = value

    def get_position(self):
        return self._position


class ToolbarStub:
    def __init__(self):
        self.visible = False

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False


class ToolItemStub:
    def __init__(self, width, homogeneous=True):
        self.width = width
        self.homogeneous = homogeneous

    def set_homogeneous(self, value):
        self.homogeneous = value

    def get_homogeneous(self):
        return self.homogeneous


class ItemToolbarStub(ToolbarStub):
    """A toolbar that pads homogeneous items out to the widest, the way GTK does."""

    def __init__(self, items):
        super().__init__()
        self.items = list(items)

    def get_n_items(self):
        return len(self.items)

    def get_nth_item(self, index):
        return self.items[index]

    def natural_width(self):
        widest = max((i.width for i in self.items), default=0)
        return sum(widest if i.homogeneous else i.width for i in self.items)


class ClipboardStub:
    def __init__(self, text=None):
        self.text = text
        self.length = None
        self.stored = False

    def wait_for_text(self):
        return self.text

    def set_text(self, text, length):
        self.text = text
        self.length = length

    def store(self):
        self.stored = True


class ClipboardTerminal:
    """Mirrors the Vte.Terminal clipboard surface. Only add methods VTE really has."""

    def __init__(self, has_selection: bool = True, screen_text: str = "visible screen\n"):
        self.copied: list = []
        self.pasted = 0
        self.pasted_text: list = []
        self.selected: list = []
        self._has_selection = has_selection
        self.screen_text = screen_text
        self.font_scale = 1.0

    def get_has_selection(self):
        return self._has_selection

    def copy_clipboard_format(self, fmt):
        self.copied.append(fmt)

    def paste_clipboard(self):
        self.pasted += 1

    def paste_text(self, text):
        self.pasted_text.append(text)

    def select_all(self):
        self.selected.append("all")
        self._has_selection = True

    def unselect_all(self):
        self.selected.append("none")
        self._has_selection = False

    def get_text_format(self, fmt):
        return self.screen_text

    def get_text(self, *args):
        return (self.screen_text, None)

    def get_font_scale(self):
        return self.font_scale

    def set_font_scale(self, scale):
        # Vte clamps for real; the fake mirrors that so tests cannot drift optimistic.
        self.font_scale = min(4.0, max(0.25, scale))


class LogWriter:
    def __init__(self):
        self.entries: list[str] = []
        self.flushes = 0

    def write(self, data: str):
        self.entries.append(data)

    def flush(self):
        self.flushes += 1


class LogTerminal(ClipboardTerminal):
    def __init__(self, text: str, row: int = 1, col: int = 1):
        super().__init__()
        self.text = text
        self.log = LogWriter()
        self.last_logged_row = 0
        self.last_logged_col = 0
        self.cursor = (col, row)
        self.last_call = None

    def get_cursor_position(self):
        return self.cursor

    def get_text_range(self, *args):
        self.last_call = ("range", args)
        return (self.text, None)

    def get_text_range_format(self, *args):
        self.last_call = ("format", args)
        return (self.text, None)

    def flush(self):
        pass


def test_set_panel_visible_updates_conf_and_positions(monkeypatch, app_module):
    wmain = object.__new__(app_module.Wmain)
    pane = PaneStub(position=250)
    pane.previous_position = 30
    wmain.hpMain = pane
    toggled = []
    wmain.get_widget = lambda name: None
    wmain._update_toggle_action = lambda name, state: toggled.append((name, state))
    monkeypatch.setattr(app_module.GLib, "timeout_add", lambda delay, func: func())
    app_module.conf.SHOW_PANEL = False

    wmain.set_panel_visible(True)

    assert pane.positions[-1] == 30
    assert app_module.conf.SHOW_PANEL is True
    # the menu check item is driven by the action state, not by a glade widget
    assert toggled == [("toggle-panel", True)]


def test_set_panel_visible_false_saves_position(monkeypatch, app_module):
    wmain = object.__new__(app_module.Wmain)
    pane = PaneStub(position=120)
    wmain.hpMain = pane
    toggled = []
    wmain.get_widget = lambda name: None
    wmain._update_toggle_action = lambda name, state: toggled.append((name, state))
    monkeypatch.setattr(app_module.GLib, "timeout_add", lambda delay, func: func())
    app_module.conf.SHOW_PANEL = True

    wmain.set_panel_visible(False)

    assert pane.previous_position == 120
    assert pane.positions[-1] == 0
    assert app_module.conf.SHOW_PANEL is False
    assert toggled == [("toggle-panel", False)]


def test_set_toolbar_visible_toggles_widgets(monkeypatch, app_module):
    wmain = object.__new__(app_module.Wmain)
    toolbar = ToolbarStub()
    toggled = []
    wmain.get_widget = lambda name: toolbar if name == "toolbar1" else None
    wmain._update_toggle_action = lambda name, state: toggled.append((name, state))
    app_module.conf.SHOW_TOOLBAR = False

    wmain.set_toolbar_visible(True)

    assert toolbar.visible is True
    assert app_module.conf.SHOW_TOOLBAR is True
    assert toggled == [("toggle-toolbar", True)]

    wmain.set_toolbar_visible(False)

    assert toolbar.visible is False
    assert app_module.conf.SHOW_TOOLBAR is False
    assert toggled[-1] == ("toggle-toolbar", False)


def test_fit_toolbar_items_stops_gtk_padding_every_item(app_module):
    """Homogeneous items are padded to the widest, which is what pushed the toolbar
    past the screen and hid buttons in an unusable overflow menu (#86)."""
    wmain = object.__new__(app_module.Wmain)
    toolbar = ItemToolbarStub([ToolItemStub(183), ToolItemStub(43), ToolItemStub(43)])
    wmain.get_widget = lambda name: toolbar if name == "toolbar1" else None

    assert toolbar.natural_width() == 183 * 3

    wmain.fit_toolbar_items()

    assert all(not item.homogeneous for item in toolbar.items)
    assert toolbar.natural_width() == 183 + 43 + 43


def test_fit_toolbar_items_survives_a_missing_toolbar(app_module):
    wmain = object.__new__(app_module.Wmain)
    wmain.get_widget = lambda _name: None

    wmain.fit_toolbar_items()  # must not raise


def test_fit_toolbar_items_skips_an_absent_item(app_module):
    wmain = object.__new__(app_module.Wmain)
    toolbar = ItemToolbarStub([ToolItemStub(43), None, ToolItemStub(43)])
    wmain.get_widget = lambda name: toolbar if name == "toolbar1" else None

    wmain.fit_toolbar_items()

    assert [i.homogeneous for i in toolbar.items if i is not None] == [False, False]


def test_the_toolbar_fit_runs_at_startup(app_module):
    """The fix is inert unless __init__ calls it, and __init__ needs a real GTK to run.

    Asserted against the source for the same reason the menu coverage check is
    (test_application.py): there is no way to construct a Wmain under the gi stubs.
    """
    source = inspect.getsource(app_module.Wmain.__init__)

    assert "self.fit_toolbar_items()" in source, (
        "Wmain.__init__ no longer fits the toolbar; its items go back to being padded "
        "to the widest and the last buttons fall into the unusable overflow menu (#86)"
    )


def test_tool_items_really_are_homogeneous_by_default():
    """The fix is only load-bearing if GTK really defaults this on."""
    gi = pytest.importorskip("gi", reason="PyGObject not available")
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    item = Gtk.ToolButton()

    assert item.get_homogeneous() is True, "GTK no longer pads items; the fix is moot"
    item.set_homogeneous(False)
    assert item.get_homogeneous() is False


def test_toolbar_stub_matches_the_real_gtk_toolbar_api():
    gi = pytest.importorskip("gi", reason="PyGObject not available")
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    for name in ("get_n_items", "get_nth_item"):
        assert hasattr(ItemToolbarStub, name), f"fake is missing {name}"
        assert hasattr(Gtk.Toolbar, name), f"Gtk.Toolbar has no {name}"
    for name in ("set_homogeneous", "get_homogeneous"):
        assert hasattr(ToolItemStub, name), f"fake is missing {name}"
        assert hasattr(Gtk.ToolItem, name), f"Gtk.ToolItem has no {name}"


def test_update_tree_rebuilds_structure(monkeypatch, app_module):
    base_host = make_host(app_module)
    base_host.group = "ops"
    base_host.name = "alpha"
    child_host = base_host.clone()
    child_host.group = "ops/prod"
    child_host.name = "beta"
    monkeypatch.setattr(
        app_module,
        "groups",
        {"ops": [base_host], "ops/prod": [child_host], "unused": []},
    )
    wmain = make_wmain_for_tree(app_module)

    def fake_get_folder(_model, base, path):
        wmain._pending_path = path
        return wmain.folder_nodes.get(path)

    def fake_get_folder_menu(menu, base, path):
        wmain._pending_menu_path = path
        return wmain.menu_nodes.get(path)

    wmain.get_folder = fake_get_folder
    wmain.get_folder_menu = fake_get_folder_menu

    class RecordingMenuItem(DummyMenuItem):
        def set_submenu(self, menu):
            super().set_submenu(menu)
            wmain.menu_nodes[wmain._pending_menu_path] = menu

    monkeypatch.setattr(app_module.Gtk, "MenuItem", RecordingMenuItem)
    monkeypatch.setattr(app_module.Gtk, "Menu", DummyMenu)

    wmain.updateTree()

    assert "unused" not in app_module.groups
    assert wmain.treeModel.host_rows[0][0] == "beta"
    assert wmain.treeModel.host_rows[1][0] == "alpha"
    assert "/ops" in wmain.folder_nodes
    assert "/ops/prod" in wmain.folder_nodes
    assert "/ops" in wmain.menu_nodes


def test_terminal_copy_helpers(monkeypatch, app_module):
    wmain = object.__new__(app_module.Wmain)
    terminal = ClipboardTerminal()
    _clipboard(monkeypatch, app_module, "hello")

    wmain.terminal_copy(terminal)
    assert terminal.copied == [app_module.Vte.Format.TEXT]

    wmain.terminal_paste(terminal)
    assert terminal.pasted_text == ["hello"]

    wmain.terminal_copy_paste(terminal)
    assert terminal.copied[-1] == app_module.Vte.Format.TEXT
    assert terminal.pasted_text == ["hello", "hello"]

    wmain.terminal_copy_all(terminal)
    assert terminal.selected == ["all", "none"]


def test_terminal_copy_without_selection_leaves_clipboard_alone(app_module):
    """VTE serves an empty string when it owns the clipboard with no selection."""
    wmain = object.__new__(app_module.Wmain)
    terminal = ClipboardTerminal(has_selection=False)

    wmain.terminal_copy(terminal)

    assert terminal.copied == []


def test_terminal_copy_paste_without_selection_still_pastes(monkeypatch, app_module):
    wmain = object.__new__(app_module.Wmain)
    terminal = ClipboardTerminal(has_selection=False)
    _clipboard(monkeypatch, app_module, "hello")

    wmain.terminal_copy_paste(terminal)

    assert terminal.copied == []
    assert terminal.pasted_text == ["hello"]


def test_terminal_copy_all_deselects_after_copying(app_module):
    wmain = object.__new__(app_module.Wmain)
    terminal = ClipboardTerminal(has_selection=False)

    wmain.terminal_copy_all(terminal)

    assert terminal.copied == [app_module.Vte.Format.TEXT]
    assert terminal.selected == ["all", "none"]
    assert terminal.get_has_selection() is False


def test_clipboard_terminal_fake_matches_real_vte_api():
    """Guards against the fake offering methods Vte.Terminal lacks."""
    gi = pytest.importorskip("gi", reason="PyGObject not available")
    gi.require_version("Vte", "2.91")
    from gi.repository import Vte

    for name in (
        "get_has_selection",
        "copy_clipboard_format",
        "get_font_scale",
        "set_font_scale",
        "paste_clipboard",
        "paste_text",
        "select_all",
        "unselect_all",
    ):
        assert hasattr(ClipboardTerminal, name), f"fake is missing {name}"
        assert hasattr(Vte.Terminal, name), f"Vte.Terminal has no {name}"


def test_clipboard_stub_matches_real_gtk_clipboard_api():
    """wait_for_text is the sync read terminal_paste relies on; prove GTK really has it."""
    gi = pytest.importorskip("gi", reason="PyGObject not available")
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    for name in ("wait_for_text", "set_text", "store"):
        assert hasattr(ClipboardStub, name), f"fake is missing {name}"
        assert hasattr(Gtk.Clipboard, name), f"Gtk.Clipboard has no {name}"


def test_terminal_menu_actions_use_active_terminal(monkeypatch, app_module):
    wmain = object.__new__(app_module.Wmain)
    terminal = ClipboardTerminal()
    wmain.hpMain = object()
    wmain.find_active_terminal = lambda widget: terminal
    _clipboard(monkeypatch, app_module, "hello")

    wmain.on_menuCopy_activate(None)
    wmain.on_menuPaste_activate(None)
    wmain.on_menuCopyPaste_activate(None)
    wmain.on_menuSelectAll_activate(None)
    wmain.on_menuCopyAll_activate(None)

    assert terminal.copied.count(app_module.Vte.Format.TEXT) == 3
    assert terminal.pasted_text == ["hello", "hello"]
    assert terminal.selected == ["all", "all", "none"]


def test_on_contents_changed_uses_text_range_pre72(monkeypatch, app_module):
    wmain = object.__new__(app_module.Wmain)
    terminal = LogTerminal("output\n")
    monkeypatch.setattr(app_module.Vte, "get_minor_version", lambda: 60, raising=False)

    wmain.on_contents_changed(terminal)

    assert terminal.last_call[0] == "range"
    assert terminal.log.entries == ["output\n"]
    assert terminal.last_logged_row == terminal.cursor[1]
    assert terminal.last_logged_col == terminal.cursor[0]


def test_on_contents_changed_uses_format_api(monkeypatch, app_module):
    wmain = object.__new__(app_module.Wmain)
    terminal = LogTerminal("formatted\n")
    monkeypatch.setattr(app_module.Vte, "get_minor_version", lambda: 80, raising=False)

    wmain.on_contents_changed(terminal)

    assert terminal.last_call[0] == "format"
    assert terminal.log.entries == ["formatted\n"]


def test_logging_keeps_the_trailing_newline(monkeypatch, app_module):
    """These two tests previously asserted "output" for input "output\n".

    They pinned the truncation rather than catching it, which is why a bug that ate a
    newline from every write survived with the logger under test.
    """
    monkeypatch.setattr(app_module.Vte, "get_minor_version", lambda: 80, raising=False)
    wmain = object.__new__(app_module.Wmain)
    terminal = LogTerminal("one\ntwo\n")

    wmain.on_contents_changed(terminal)

    assert terminal.log.entries == ["one\ntwo\n"]
    assert "".join(terminal.log.entries).endswith("\n")


def test_logging_a_range_that_ends_mid_line_keeps_its_last_character(monkeypatch, app_module):
    """A chunk ending at a prompt has no trailing newline, so [:-1] ate real content.

    Measured against VTE: a range of "aaa\nbbb\n$ some-command" was logged as
    "aaa\nbbb\n$ some-comman".
    """
    monkeypatch.setattr(app_module.Vte, "get_minor_version", lambda: 80, raising=False)
    wmain = object.__new__(app_module.Wmain)
    terminal = LogTerminal("aaa\nbbb\n$ some-command")

    wmain.on_contents_changed(terminal)

    assert terminal.log.entries == ["aaa\nbbb\n$ some-command"]


def test_logging_an_empty_range_writes_nothing(monkeypatch, app_module):
    """A backwards range returns "" from VTE, and None from the pre-0.72 call."""
    monkeypatch.setattr(app_module.Vte, "get_minor_version", lambda: 80, raising=False)
    wmain = object.__new__(app_module.Wmain)

    for empty in ("", None):
        terminal = LogTerminal(empty)
        wmain.on_contents_changed(terminal)
        assert terminal.log.entries == [""], f"for {empty!r}"


def test_importar_servidores_loads_hosts(monkeypatch, tmp_path, app_module):
    host = make_host(app_module)
    password = "secretpw"
    filename = tmp_path / "hosts.ini"

    monkeypatch.setattr(app_module, "encrypt", lambda _pwd, value: value)
    monkeypatch.setattr(app_module, "decrypt", lambda _pwd, value: value)

    exporter = object.__new__(app_module.Wmain)
    exporter.window = object()
    exporter.wMain = object()
    monkeypatch.setattr(app_module, "groups", {"ops/prod": [host]})
    monkeypatch.setattr(app_module, "show_open_dialog", lambda **kwargs: str(filename))
    monkeypatch.setattr(app_module, "inputbox", lambda *args, **kwargs: password)
    exporter.on_exportar_servidores1_activate(None)

    wmain = object.__new__(app_module.Wmain)
    wmain.window = object()
    wmain.wMain = object()
    called = {"update": 0}
    wmain.updateTree = lambda: called.__setitem__("update", called["update"] + 1)

    monkeypatch.setattr(app_module, "groups", {})
    monkeypatch.setattr(
        app_module, "msgconfirm", lambda *_args, **_kwargs: app_module.Gtk.ResponseType.OK
    )
    messages: list[str] = []
    monkeypatch.setattr(app_module, "msgbox", lambda text: messages.append(text))
    monkeypatch.setattr(app_module, "groups", {})

    wmain.on_importar_servidores1_activate(None)

    assert messages == []
    assert "ops/prod" in app_module.groups
    assert called["update"] == 1
    imported = app_module.groups["ops/prod"][0]
    assert imported.name == host.name
    assert imported.host == host.host


def test_exportar_servidores_writes_encrypted_hosts(monkeypatch, tmp_path, app_module):
    host = make_host(app_module)
    password = "secretpw"
    filename = tmp_path / "export.ini"

    wmain = object.__new__(app_module.Wmain)
    wmain.window = object()
    wmain.wMain = object()

    monkeypatch.setattr(app_module, "show_open_dialog", lambda **kwargs: str(filename))
    monkeypatch.setattr(app_module, "inputbox", lambda *args, **kwargs: password)
    monkeypatch.setattr(app_module, "groups", {"ops/prod": [host]})

    wmain.on_exportar_servidores1_activate(None)

    cp = configparser.RawConfigParser()
    cp.read(filename)
    assert cp.get("gcm", "gcm")
    assert cp.get("host 1", "group") == "ops/prod"
    assert cp.get("host 1", "name") == host.name


class DummyTreeNode:
    def __init__(self, label, host=None):
        self.label = label
        self.host = host
        self.children: list[DummyTreeNode] = []

    def add_child(self, child):
        self.children.append(child)

    def iterchildren(self):
        return self.children


def _clipboard(monkeypatch, app_module, text=None):
    clipboard = ClipboardStub(text)
    monkeypatch.setattr(app_module.Gdk.Display, "get_default", lambda: object())
    monkeypatch.setattr(app_module.Gtk.Clipboard, "get_default", lambda *_args: clipboard)
    return clipboard


def test_copy_screen_uses_format_api(monkeypatch, app_module):
    monkeypatch.setattr(app_module.Vte, "get_minor_version", lambda: 76, raising=False)
    wmain = object.__new__(app_module.Wmain)
    terminal = ClipboardTerminal(screen_text="ALT-LINE-000\nALT-LINE-001\n\n")
    clipboard = _clipboard(monkeypatch, app_module)

    wmain._copy_screen(terminal)

    assert clipboard.text == "ALT-LINE-000\nALT-LINE-001"


def test_copy_screen_uses_legacy_api_pre72(monkeypatch, app_module):
    monkeypatch.setattr(app_module.Vte, "get_minor_version", lambda: 60, raising=False)
    wmain = object.__new__(app_module.Wmain)
    terminal = ClipboardTerminal(screen_text="legacy screen\n")
    clipboard = _clipboard(monkeypatch, app_module)

    wmain._copy_screen(terminal)

    assert clipboard.text == "legacy screen"


def test_copy_screen_ignores_blank_screen(monkeypatch, app_module):
    monkeypatch.setattr(app_module.Vte, "get_minor_version", lambda: 76, raising=False)
    wmain = object.__new__(app_module.Wmain)
    terminal = ClipboardTerminal(screen_text="   \n\n")
    clipboard = _clipboard(monkeypatch, app_module)

    wmain._copy_screen(terminal)

    assert clipboard.text is None


def test_terminal_copy_falls_back_to_screen_only_when_enabled(monkeypatch, app_module):
    monkeypatch.setattr(app_module.Vte, "get_minor_version", lambda: 76, raising=False)
    wmain = object.__new__(app_module.Wmain)
    terminal = ClipboardTerminal(has_selection=False, screen_text="screen body\n")

    monkeypatch.setattr(app_module.conf, "COPY_SCREEN_IF_NO_SELECTION", 0)
    clipboard = _clipboard(monkeypatch, app_module)
    wmain.terminal_copy(terminal)
    assert clipboard.text is None
    assert terminal.copied == []

    monkeypatch.setattr(app_module.conf, "COPY_SCREEN_IF_NO_SELECTION", 1)
    clipboard = _clipboard(monkeypatch, app_module)
    wmain.terminal_copy(terminal)
    assert clipboard.text == "screen body"


def test_terminal_copy_prefers_the_selection_over_the_screen(monkeypatch, app_module):
    monkeypatch.setattr(app_module.conf, "COPY_SCREEN_IF_NO_SELECTION", 1)
    wmain = object.__new__(app_module.Wmain)
    terminal = ClipboardTerminal(has_selection=True)
    clipboard = _clipboard(monkeypatch, app_module)

    wmain.terminal_copy(terminal)

    assert terminal.copied == [app_module.Vte.Format.TEXT]
    assert clipboard.text is None


def test_terminal_copy_paste_never_falls_back_to_screen(monkeypatch, app_module):
    """Pasting a whole screen back into the terminal is never the intent."""
    monkeypatch.setattr(app_module.Vte, "get_minor_version", lambda: 76, raising=False)
    monkeypatch.setattr(app_module.conf, "COPY_SCREEN_IF_NO_SELECTION", 1)
    wmain = object.__new__(app_module.Wmain)
    terminal = ClipboardTerminal(has_selection=False)
    clipboard = _clipboard(monkeypatch, app_module)

    wmain.terminal_copy_paste(terminal)

    assert terminal.copied == []
    assert clipboard.text is None
    assert terminal.pasted == 1


# -- paste hygiene (#21) ----------------------------------------------------


@pytest.mark.parametrize(
    ("clipboard_text", "expected"),
    [
        ("echo hi\n", "echo hi"),
        ("echo hi\r\n", "echo hi"),
        ("echo hi\r", "echo hi"),
        ("echo hi", "echo hi"),
        ("line one\nline two\n", "line one\nline two"),
        ("trailing blank\n\n", "trailing blank"),
        ("crlf pair\r\n\r\n", "crlf pair"),
        ("", ""),
        (None, ""),
    ],
)
def test_paste_transform_strips_trailing_terminators(app_module, clipboard_text, expected):
    """A trailing newline is what turns a pasted prompt into a submitted one.

    Every terminator goes, not just one: VTE copies a line selection as "text\\n\\n",
    so a single-newline strip would still auto-submit the most common paste there is.
    """
    assert app_module.paste_transform(clipboard_text) == expected


def test_paste_transform_respects_disabled_option(monkeypatch, app_module):
    monkeypatch.setattr(app_module.conf, "PASTE_STRIP_TRAILING_NEWLINE", 0)

    assert app_module.paste_transform("echo hi\n") == "echo hi\n"


def test_paste_transform_single_line_joins_and_drops_blanks(app_module):
    text = "  first  \n\n   second\nthird   \n"

    assert app_module.paste_transform(text, single_line=True) == "first second third"


def test_paste_transform_single_line_ignores_strip_option(monkeypatch, app_module):
    """Joining already removes every newline, so the strip toggle cannot change it."""
    monkeypatch.setattr(app_module.conf, "PASTE_STRIP_TRAILING_NEWLINE", 0)

    assert app_module.paste_transform("a\nb\n", single_line=True) == "a b"


def test_paste_needs_confirmation_on_line_count(monkeypatch, app_module):
    monkeypatch.setattr(app_module.conf, "PASTE_CONFIRM_LINES", 3)
    monkeypatch.setattr(app_module.conf, "PASTE_CONFIRM_BYTES", 0)

    assert app_module.paste_needs_confirmation("a\nb\nc") is False
    assert app_module.paste_needs_confirmation("a\nb\nc\nd") is True


def test_paste_needs_confirmation_on_byte_count(monkeypatch, app_module):
    monkeypatch.setattr(app_module.conf, "PASTE_CONFIRM_LINES", 0)
    monkeypatch.setattr(app_module.conf, "PASTE_CONFIRM_BYTES", 8)

    assert app_module.paste_needs_confirmation("12345678") is False
    assert app_module.paste_needs_confirmation("123456789") is True
    # Multi-byte characters count as the bytes they occupy on the wire.
    assert app_module.paste_needs_confirmation("ñññññ") is True


def test_paste_needs_confirmation_thresholds_of_zero_disable_it(monkeypatch, app_module):
    monkeypatch.setattr(app_module.conf, "PASTE_CONFIRM_LINES", 0)
    monkeypatch.setattr(app_module.conf, "PASTE_CONFIRM_BYTES", 0)

    assert app_module.paste_needs_confirmation("a\n" * 5000) is False


def test_paste_preview_summarises_and_truncates(app_module):
    preview = app_module.paste_preview("\n".join(f"line {n}" for n in range(50)), max_lines=3)

    assert "50" in preview
    assert "line 0" in preview and "line 2" in preview
    assert "line 3" not in preview
    assert preview.endswith("…")


def test_terminal_paste_delivers_transformed_text(monkeypatch, app_module):
    monkeypatch.setattr(app_module.conf, "PASTE_CONFIRM_LINES", 0)
    monkeypatch.setattr(app_module.conf, "PASTE_CONFIRM_BYTES", 0)
    wmain = object.__new__(app_module.Wmain)
    terminal = ClipboardTerminal()
    _clipboard(monkeypatch, app_module, "echo hi\n")

    wmain.terminal_paste(terminal)

    assert terminal.pasted_text == ["echo hi"]
    assert terminal.pasted == 0


def test_terminal_paste_single_line_joins(monkeypatch, app_module):
    monkeypatch.setattr(app_module.conf, "PASTE_CONFIRM_LINES", 0)
    monkeypatch.setattr(app_module.conf, "PASTE_CONFIRM_BYTES", 0)
    wmain = object.__new__(app_module.Wmain)
    terminal = ClipboardTerminal()
    _clipboard(monkeypatch, app_module, "one\ntwo\n")

    wmain.terminal_paste(terminal, single_line=True)

    assert terminal.pasted_text == ["one two"]


def test_terminal_paste_confirms_large_paste_and_delivers_on_ok(monkeypatch, app_module):
    monkeypatch.setattr(app_module.conf, "PASTE_CONFIRM_LINES", 2)
    prompts = []
    monkeypatch.setattr(
        app_module,
        "msgconfirm",
        lambda text: prompts.append(text) or app_module.Gtk.ResponseType.OK,
    )
    wmain = object.__new__(app_module.Wmain)
    terminal = ClipboardTerminal()
    _clipboard(monkeypatch, app_module, "a\nb\nc\n")

    wmain.terminal_paste(terminal)

    assert len(prompts) == 1
    assert terminal.pasted_text == ["a\nb\nc"]


def test_terminal_paste_cancelled_confirmation_delivers_nothing(monkeypatch, app_module):
    monkeypatch.setattr(app_module.conf, "PASTE_CONFIRM_LINES", 2)
    monkeypatch.setattr(app_module, "msgconfirm", lambda _text: app_module.Gtk.ResponseType.CANCEL)
    wmain = object.__new__(app_module.Wmain)
    terminal = ClipboardTerminal()
    _clipboard(monkeypatch, app_module, "a\nb\nc\n")

    wmain.terminal_paste(terminal)

    assert terminal.pasted_text == []
    assert terminal.pasted == 0


def test_terminal_paste_without_text_falls_back_to_vte(monkeypatch, app_module):
    """Non-text clipboard contents stay VTE's problem rather than being swallowed."""
    wmain = object.__new__(app_module.Wmain)
    terminal = ClipboardTerminal()
    _clipboard(monkeypatch, app_module, None)

    wmain.terminal_paste(terminal)

    assert terminal.pasted == 1
    assert terminal.pasted_text == []


def test_terminal_paste_of_only_a_newline_delivers_nothing(monkeypatch, app_module):
    """Stripping must not turn a lone newline into an unguarded paste_clipboard fallback."""
    wmain = object.__new__(app_module.Wmain)
    terminal = ClipboardTerminal()
    _clipboard(monkeypatch, app_module, "\n")

    wmain.terminal_paste(terminal)

    assert terminal.pasted == 0
    assert terminal.pasted_text == []


class NotebookAncestor:
    """terminal.get_parent().get_parent() is the notebook that owns the tabs."""

    def __init__(self, pages: int = 1):
        self.pages = pages

    def get_parent(self):
        return self

    def get_n_pages(self):
        return self.pages


# -- font zoom (#19) --------------------------------------------------------


class ScrollEvent:
    """Mirrors the Gdk.EventScroll surface on_terminal_scroll actually reads."""

    def __init__(self, direction, ctrl=True, deltas=None):
        self.direction = direction
        self.state = 1 if ctrl else 0  # conftest maps CONTROL_MASK to 1
        self._deltas = deltas

    def get_scroll_deltas(self):
        if self._deltas is None:
            return (False, 0.0, 0.0)
        return (True, *self._deltas)


def _terminal_signal_connections(app_module):
    source = Path(app_module.__file__).read_text()
    body = source.split("def addTab", 1)[1].split("\n    def ", 1)[0]
    return dict(re.findall(r'v\.connect\(\s*"([a-z_-]+)",\s*(?:self\.)?([A-Za-z_.]+)', body))


def test_terminal_signals_are_wired_at_creation(app_module):
    """A handler that exists but is never connected stays invisible until someone tries it."""
    connections = _terminal_signal_connections(app_module)

    assert connections.get("scroll-event") == "on_terminal_scroll"
    assert connections.get("increase-font-size") == "terminal_zoom_in"
    assert connections.get("decrease-font-size") == "terminal_zoom_out"
    # Pre-existing wiring, guarded here because this is the only place that checks it.
    assert connections.get("key_press_event") == "on_terminal_keypress"
    assert connections.get("button_press_event") == "on_terminal_click"
    assert connections.get("bell") == "on_terminal_bell"


def test_terminal_zoom_steps_and_resets(app_module):
    wmain = object.__new__(app_module.Wmain)
    terminal = ClipboardTerminal()

    assert wmain.terminal_zoom_in(terminal) > 1.0
    assert terminal.font_scale > 1.0
    wmain.terminal_zoom_out(terminal)
    assert terminal.font_scale == pytest.approx(1.0)

    wmain.terminal_zoom_in(terminal)
    assert wmain.terminal_zoom_reset(terminal) == 1.0
    assert terminal.font_scale == 1.0


def test_terminal_zoom_saturates_instead_of_running_away(app_module):
    """A held-down zoom key must not walk a scale VTE has stopped honouring."""
    wmain = object.__new__(app_module.Wmain)
    terminal = ClipboardTerminal()

    for _ in range(80):
        wmain.terminal_zoom_in(terminal)
    assert terminal.font_scale == shortcuts.FONT_SCALE_MAX

    for _ in range(120):
        wmain.terminal_zoom_out(terminal)
    assert terminal.font_scale == shortcuts.FONT_SCALE_MIN


def test_terminal_zoom_is_per_terminal_not_global(app_module):
    """set_font_scale is a widget property; a wide log must not shrink the next tab."""
    wmain = object.__new__(app_module.Wmain)
    zoomed, untouched = ClipboardTerminal(), ClipboardTerminal()

    wmain.terminal_zoom_in(zoomed)

    assert zoomed.font_scale > 1.0
    assert untouched.font_scale == 1.0


def test_ctrl_scroll_zooms_and_swallows_the_event(app_module):
    """Returning False as well would scroll the buffer while zooming it."""
    wmain = object.__new__(app_module.Wmain)
    terminal = ClipboardTerminal()
    direction = app_module.Gdk.ScrollDirection

    assert wmain.on_terminal_scroll(terminal, ScrollEvent(direction.UP)) is True
    assert terminal.font_scale > 1.0
    assert wmain.on_terminal_scroll(terminal, ScrollEvent(direction.DOWN)) is True
    assert terminal.font_scale == pytest.approx(1.0)


def test_plain_scroll_is_left_to_vte(app_module):
    """Without Ctrl the wheel belongs to the scrollback, untouched."""
    wmain = object.__new__(app_module.Wmain)
    terminal = ClipboardTerminal()
    direction = app_module.Gdk.ScrollDirection

    handled = wmain.on_terminal_scroll(terminal, ScrollEvent(direction.UP, ctrl=False))

    assert handled is False
    assert terminal.font_scale == 1.0


@pytest.mark.parametrize(
    ("dy", "grows"),
    [(-1.0, True), (1.0, False)],
)
def test_ctrl_smooth_scroll_zooms_by_delta_sign(app_module, dy, grows):
    """Smooth scroll reports upward movement as a negative delta."""
    wmain = object.__new__(app_module.Wmain)
    terminal = ClipboardTerminal()
    event = ScrollEvent(app_module.Gdk.ScrollDirection.SMOOTH, deltas=(0.0, dy))

    assert wmain.on_terminal_scroll(terminal, event) is True
    assert (terminal.font_scale > 1.0) is grows


def test_ctrl_smooth_scroll_without_usable_deltas_is_ignored(app_module):
    wmain = object.__new__(app_module.Wmain)
    terminal = ClipboardTerminal()
    direction = app_module.Gdk.ScrollDirection

    assert wmain.on_terminal_scroll(terminal, ScrollEvent(direction.SMOOTH)) is False
    assert (
        wmain.on_terminal_scroll(terminal, ScrollEvent(direction.SMOOTH, deltas=(0.0, 0.0)))
        is False
    )
    assert terminal.font_scale == 1.0


def test_sideways_ctrl_scroll_does_not_zoom(app_module):
    wmain = object.__new__(app_module.Wmain)
    terminal = ClipboardTerminal()

    handled = wmain.on_terminal_scroll(terminal, ScrollEvent(app_module.Gdk.ScrollDirection.LEFT))

    assert handled is False
    assert terminal.font_scale == 1.0


def test_zoom_commands_are_configurable_shortcuts(app_module):
    """Zoom rides the [shortcuts] table so its keys can be rebound like any other."""
    defaults = {command: key for command, _token, key in app_module.SHORTCUT_DEFAULTS}

    assert defaults["zoom_in"] == "CTRL+EQUAL"
    assert defaults["zoom_out"] == "CTRL+MINUS"
    assert defaults["zoom_reset"] == "CTRL+0"
    for command in ("zoom_in", "zoom_out", "zoom_reset"):
        assert command in app_module.TERMINAL_ACTIONS


def _context_menu_actions(app_module):
    source = Path(app_module.__file__).read_text()
    body = source.split("def createMenu", 1)[1].split("\n    def ", 1)[0]
    return set(re.findall(r'"app\.([a-z-]+)"', body))


def test_terminal_context_menu_offers_the_clipboard_actions(app_module):
    """Right-click is where paste is actually reached from, so it carries the same set."""
    actions = _context_menu_actions(app_module)

    assert {
        "copy",
        "paste",
        "paste-single-line",
        "copy-paste",
        "select-all",
        "copy-all",
    } <= actions


def test_right_click_paste_goes_through_the_policy(monkeypatch, app_module):
    """PASTE_ON_RIGHT_CLICK used to call paste_clipboard() and bypass every rule."""
    monkeypatch.setattr(app_module.conf, "PASTE_ON_RIGHT_CLICK", 1)
    monkeypatch.setattr(app_module.conf, "PASTE_CONFIRM_LINES", 0)
    monkeypatch.setattr(app_module.conf, "PASTE_CONFIRM_BYTES", 0)
    wmain = object.__new__(app_module.Wmain)
    wmain.popupMenu = types.SimpleNamespace(
        mnuSplitH=types.SimpleNamespace(set_sensitive=lambda _v: None),
        mnuSplitV=types.SimpleNamespace(set_sensitive=lambda _v: None),
    )
    terminal = ClipboardTerminal()
    terminal.get_parent = NotebookAncestor
    _clipboard(monkeypatch, app_module, "echo hi\n")
    event = types.SimpleNamespace(type=app_module.Gdk.EventType.BUTTON_PRESS, button=3, x=0, y=0)

    wmain.on_terminal_click(terminal, event)

    assert terminal.pasted_text == ["echo hi"]
    assert terminal.pasted == 0


class BellTabLabel:
    def __init__(self, text="agy"):
        self.attention = None
        self.text = text

    def set_attention(self, value):
        self.attention = value

    def get_text(self):
        return f"  {self.text}  "


class BellNotebook:
    def __init__(self, label, current=0, page_index=1):
        self.label = label
        self.current = current
        self.page_index = page_index

    def get_tab_label(self, _page):
        return self.label

    def get_current_page(self):
        return self.current

    def page_num(self, _page):
        return self.page_index


class BellWindow:
    def __init__(self, active=True, application=None):
        self.active = active
        self.urgency = False
        self.application = application

    def is_active(self):
        return self.active

    def set_urgency_hint(self, value):
        self.urgency = value

    def get_application(self):
        return self.application


class BellApplication:
    def __init__(self):
        self.sent = []

    def send_notification(self, ident, notification):
        self.sent.append((ident, notification))


def _bell_setup(app_module, monkeypatch, *, window_active=True, showing=False, application=None):
    monkeypatch.setattr(app_module.conf, "BELL_MARK_TAB", 1)
    monkeypatch.setattr(app_module.conf, "BELL_NOTIFY", 0)
    label = BellTabLabel()
    notebook = BellNotebook(label, current=1 if showing else 0, page_index=1)
    page = types.SimpleNamespace(get_parent=lambda: notebook)
    terminal = types.SimpleNamespace(get_parent=lambda: page)
    wmain = object.__new__(app_module.Wmain)
    wmain.wMain = BellWindow(active=window_active, application=application)
    return wmain, terminal, label, page


def test_bell_marks_a_background_tab(app_module, monkeypatch):
    wmain, terminal, label, _page = _bell_setup(app_module, monkeypatch, showing=False)

    wmain.on_terminal_bell(terminal)

    assert label.attention is True


def test_bell_leaves_the_tab_the_user_is_watching_alone(app_module, monkeypatch):
    wmain, terminal, label, _page = _bell_setup(
        app_module, monkeypatch, window_active=True, showing=True
    )

    wmain.on_terminal_bell(terminal)

    assert label.attention is None


def test_bell_marks_the_visible_tab_when_the_window_is_not_active(app_module, monkeypatch):
    wmain, terminal, label, _page = _bell_setup(
        app_module, monkeypatch, window_active=False, showing=True
    )

    wmain.on_terminal_bell(terminal)

    assert label.attention is True
    assert wmain.wMain.urgency is True


def test_bell_does_not_raise_the_urgency_hint_while_the_window_is_active(app_module, monkeypatch):
    wmain, terminal, _label, _page = _bell_setup(app_module, monkeypatch, window_active=True)

    wmain.on_terminal_bell(terminal)

    assert wmain.wMain.urgency is False


def test_bell_respects_the_mark_tab_preference(app_module, monkeypatch):
    wmain, terminal, label, _page = _bell_setup(app_module, monkeypatch)
    monkeypatch.setattr(app_module.conf, "BELL_MARK_TAB", 0)

    wmain.on_terminal_bell(terminal)

    assert label.attention is None


def test_bell_notifies_only_when_enabled_and_the_window_is_inactive(app_module, monkeypatch):
    application = BellApplication()

    wmain, terminal, _label, _page = _bell_setup(
        app_module, monkeypatch, window_active=False, application=application
    )
    wmain.on_terminal_bell(terminal)
    assert application.sent == []  # preference off

    monkeypatch.setattr(app_module.conf, "BELL_NOTIFY", 1)
    wmain.on_terminal_bell(terminal)
    assert len(application.sent) == 1
    assert application.sent[0][0] == "gcm-bell"

    # window back in front: nothing to notify about
    wmain.wMain.active = True
    wmain.on_terminal_bell(terminal)
    assert len(application.sent) == 1


def test_focusing_a_tab_clears_its_attention_mark(app_module, monkeypatch):
    monkeypatch.setattr(app_module.conf, "UPDATE_TITLE", 0)
    wmain, _terminal, label, page = _bell_setup(app_module, monkeypatch)
    label.attention = True

    # notebook switch-page delivers the page widget as `tab`
    wmain.on_tab_focus(object(), page)

    assert label.attention is False


def test_window_becoming_active_clears_the_urgency_hint(app_module):
    wmain = object.__new__(app_module.Wmain)
    window = BellWindow(active=True)
    window.urgency = True

    wmain.on_window_active_changed(window, None)

    assert window.urgency is False


class LogHost:
    def __init__(self, group="", name="web-01", user="", host="", port=""):
        self.group = group
        self.name = name
        self.user = user
        self.host = host
        self.port = port


def test_session_file_for_wrapper_supplies_the_configured_log_path(
    app_module, monkeypatch, tmp_path
):
    """The wrapper's whole job after #139: turn conf.LOG_PATH into an argument.

    Asserted directly rather than inferred from a path, because the failure mode is the
    wrapper passing a stale or default root and the log landing somewhere else.
    """
    seen: dict[str, object] = {}

    def fake(terminal, suffix, log_path):
        seen.update(suffix=suffix, log_path=log_path)
        return "sentinel"

    monkeypatch.setattr(app_module.logpaths, "session_file_for", fake)
    monkeypatch.setattr(app_module.conf, "LOG_PATH", str(tmp_path / "logs"))

    assert app_module.session_file_for(object(), ".raw") == "sentinel"
    assert seen == {"suffix": ".raw", "log_path": str(tmp_path / "logs")}


def test_session_file_for_lands_under_the_configured_root(app_module, monkeypatch, tmp_path):
    """End to end through the wrapper, with no logpaths function patched out."""
    monkeypatch.setattr(app_module.conf, "LOG_PATH", str(tmp_path))
    terminal = type("T", (), {"host": LogHost(group="prod", name="web-01", user="deploy")})()

    path = app_module.session_file_for(terminal, ".log")

    assert path is not None
    assert Path(path).is_relative_to(tmp_path)
    assert Path(path).parent == tmp_path / "prod" / "web-01"
    assert Path(path).name.startswith("deploy-")


class LoggingTerminal:
    """Terminal surface set_terminal_logger touches. Only what Vte.Terminal really has."""

    def __init__(self, host):
        self.host = host
        self.connected = []

    def get_cursor_position(self):
        return (0, 0)

    def connect(self, signal, handler):
        self.connected.append(signal)
        return 1

    def disconnect(self, handler_id):
        self.connected.append(("disconnect", handler_id))

    def get_parent(self):  # must never be reached: the label is not the identity
        raise AssertionError("set_terminal_logger walked to the tab label")


def test_set_terminal_logger_names_the_log_from_the_host_not_the_tab(
    tmp_path, app_module, monkeypatch
):
    """The tab label is presentation; walking to it at all is the bug (#49)."""
    monkeypatch.setattr(app_module.conf, "LOG_PATH", str(tmp_path))
    monkeypatch.setattr(app_module.time, "strftime", lambda fmt: "20260823")
    wmain = object.__new__(app_module.Wmain)
    terminal = LoggingTerminal(
        LogHost(group="Home Tech/PVE/PVE1", name="pve1", user="root", host="10.0.0.9", port=22)
    )

    wmain.set_terminal_logger(terminal)
    terminal.log.close()

    written = list(tmp_path.rglob("*.log"))
    assert len(written) == 1
    assert written[0] == (
        tmp_path / "Home Tech" / "PVE" / "PVE1" / "pve1" / "root-20260823-001.log"
    )
    assert "pve1 (root@10.0.0.9:22)" in written[0].read_text()


def test_set_terminal_logger_falls_back_when_the_connection_never_set_a_host(
    tmp_path, app_module, monkeypatch
):
    """addTab now assigns v.host up front, but set_terminal_logger is reachable from the
    logging toggle too, so it still has to cope with a terminal that never got one."""
    monkeypatch.setattr(app_module.conf, "LOG_PATH", str(tmp_path))
    monkeypatch.setattr(app_module.time, "strftime", lambda fmt: "20260823")
    wmain = object.__new__(app_module.Wmain)
    terminal = LoggingTerminal(None)
    del terminal.host

    wmain.set_terminal_logger(terminal)
    terminal.log.close()

    written = list(tmp_path.rglob("*.log"))
    assert len(written) == 1
    assert written[0] == tmp_path / "session" / "session-20260823-001.log"


def test_addtab_sets_the_host_before_it_starts_logging(app_module):
    """set_terminal_logger reads terminal.host to build the log path, so assigning
    v.host after the call sent every text log to <logs>/session/session-*.log --
    a real ssh session to a grouped host logged under the fallback name."""
    source = Path(app_module.__file__).read_text()
    body = source.split("def addTab", 1)[1].split("\n    def ", 1)[0]

    assert "v.host = host" in body
    assert body.index("v.host = host") < body.index("set_terminal_logger(v")


# addTab needs a real Gtk/Vte to run at all, so the ordering above is only half the
# story: it proves the statements are in the right order, not that a session actually
# lands in its host's directory. Drive the real thing in a subprocess and look at where
# the file came out. HOME is redirected so this can never touch a real ~/.gcm.
_ADDTAB_LOG_SCRIPT = """
import os, sys, tempfile, time
os.environ["HOME"] = tempfile.mkdtemp(); sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk
from pathlib import Path
from gnome_connection_manager import app

logs = tempfile.mkdtemp()
app.conf.LOG_PATH = logs

app.wMain = app.Wmain(application=None)
# No host address, so this opens a local shell rather than reaching for the network.
# The group, name and user are what the log path is built from either way.
host = app.Host("Work/Projects", "uss3-linux-bastion", "", "", "admed")
host.log = True

app.wMain.addTab(app.wMain.nbConsole, host)
deadline = time.monotonic() + 3
while time.monotonic() < deadline:
    Gtk.main_iteration_do(False); time.sleep(0.005)

found = sorted(str(p.relative_to(logs)) for p in Path(logs).rglob("*.log"))
expected = ["Work/Projects/uss3-linux-bastion/admed-%s-001.log" % time.strftime("%Y%m%d")]
assert found == expected, "log landed at %r, expected %r" % (found, expected)
print("OK")
"""


@pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"),
    reason="needs a display for a real terminal",
)
def test_addtab_logs_into_the_host_directory_against_real_gtk():
    """The regression #111 actually produced: every session logged to <logs>/session/.

    Mutation tested -- with v.host assigned after set_terminal_logger this reports
    session/session-<date>-001.log, which is exactly what was found in the wild.
    """
    pytest.importorskip("gi", reason="PyGObject not available")
    result = subprocess.run(
        [sys.executable, "-c", _ADDTAB_LOG_SCRIPT],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        timeout=90,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert "OK" in result.stdout


def _clone_blocks(app_module):
    source = Path(app_module.__file__).read_text()
    return [
        source[m : m + 400]
        for m in (i for i in range(len(source)) if source.startswith("host = term.host.clone()", i))
    ]


def test_cloning_a_console_keeps_the_host_name(app_module):
    """Clone used to write the tab label into host.name, which then reached the logs."""
    blocks = _clone_blocks(app_module)

    assert len(blocks) == 2, f"expected both clone paths, found {len(blocks)}"
    for block in blocks:
        assert "host.name = tab.get_text()" not in block


class PlainTabLabel:
    """A tab label that is not a NotebookTabLabel, as the glade placeholders are."""

    def get_text(self):
        return "page 1"


def test_clearing_attention_tolerates_a_plain_tab_label(app_module, monkeypatch):
    """nbConsole ships placeholder pages whose labels are plain Gtk.Labels (#41)."""
    monkeypatch.setattr(app_module.conf, "UPDATE_TITLE", 0)
    notebook = BellNotebook(PlainTabLabel())
    page = types.SimpleNamespace(get_parent=lambda: notebook)
    wmain = object.__new__(app_module.Wmain)

    wmain.clear_tab_attention(page)  # must not raise


def test_bell_tolerates_a_plain_tab_label(app_module, monkeypatch):
    monkeypatch.setattr(app_module.conf, "BELL_MARK_TAB", 1)
    monkeypatch.setattr(app_module.conf, "BELL_NOTIFY", 0)
    notebook = BellNotebook(PlainTabLabel())
    page = types.SimpleNamespace(get_parent=lambda: notebook)
    terminal = types.SimpleNamespace(get_parent=lambda: page)
    wmain = object.__new__(app_module.Wmain)
    wmain.wMain = BellWindow(active=False)

    wmain.on_terminal_bell(terminal)  # must not raise

    assert wmain.wMain.urgency is False


def test_tab_focus_still_updates_the_title_after_a_plain_label(app_module, monkeypatch):
    """The crash aborted on_tab_focus before it reached the title update."""
    monkeypatch.setattr(app_module.conf, "UPDATE_TITLE", 1)
    monkeypatch.setattr(app_module.conf, "APP_TITLE", "GCM")
    titles: list = []
    notebook = BellNotebook(PlainTabLabel())
    page = types.SimpleNamespace(get_parent=lambda: notebook)
    wmain = object.__new__(app_module.Wmain)
    wmain.wMain = types.SimpleNamespace(set_title=titles.append)
    notebook.get_tab_label = lambda _p: PlainTabLabel()

    wmain.on_tab_focus(notebook, page)

    assert titles == ["GCM - page 1"]


def test_install_menubar_renders_the_model_into_the_layout(app_module, monkeypatch):
    """set_menubar() is inert for a plain GtkWindow, so the model must be rendered (#43)."""
    packed = {}

    class MenuBarStub:
        def __init__(self):
            self.children = []
            self.shown = False

        def get_children(self):
            return self.children

        def insert(self, item, position):
            self.children.insert(position, item)

        def show_all(self):
            self.shown = True

    class BoxStub:
        def pack_start(self, child, expand, fill, padding):
            packed["child"] = child

        def reorder_child(self, child, position):
            packed["position"] = position

    class MenuItemStubGtk:
        def __init__(self, label=None):
            self.label = label
            self.submenu = None

        def set_use_underline(self, value):
            pass

        def set_submenu(self, submenu):
            self.submenu = submenu

    menubar_widget = MenuBarStub()
    menubar_widget.children = [object(), object()]  # model items, Help last
    monkeypatch.setattr(
        app_module.Gtk,
        "MenuBar",
        types.SimpleNamespace(new_from_model=lambda model: menubar_widget),
        raising=False,
    )
    monkeypatch.setattr(app_module.Gtk, "MenuItem", MenuItemStubGtk, raising=False)
    monkeypatch.setattr(
        app_module.Gtk.Application,
        "get_default",
        lambda: types.SimpleNamespace(get_menubar=lambda: object()),
        raising=False,
    )

    wmain = object.__new__(app_module.Wmain)
    wmain.menuServers = object()
    wmain.get_widget = lambda name: BoxStub() if name == "mainBox" else None

    wmain.install_menubar()

    assert wmain.menubar is menubar_widget
    assert packed["child"] is menubar_widget
    assert packed["position"] == 0
    assert menubar_widget.shown is True
    # the host list is inserted before Help, which the model appends last
    hosts = menubar_widget.children[-2]
    assert isinstance(hosts, MenuItemStubGtk)
    assert hosts.submenu is wmain.menuServers


def test_install_menubar_is_inert_without_an_application(app_module, monkeypatch):
    monkeypatch.setattr(app_module.Gtk.Application, "get_default", lambda: None, raising=False)
    wmain = object.__new__(app_module.Wmain)
    wmain.menubar = None
    wmain.get_widget = lambda name: None

    wmain.install_menubar()

    assert wmain.menubar is None


def test_glade_no_longer_defines_a_menubar(app_module):
    """One menubar definition only; a second would silently shadow the model (#43)."""
    glade = Path(app_module.glade_dir) / "gnome-connection-manager.glade"
    assert "GtkMenuBar" not in glade.read_text()


class StubLabel:
    def __init__(self):
        self.text = ""
        self.markup = None

    def set_text(self, text):
        self.text = text
        self.markup = None

    def get_text(self):
        return self.text

    def set_markup(self, markup):
        self.markup = markup


def _tab_label(app_module, title="  prod-web-01  "):
    tab = object.__new__(app_module.NotebookTabLabel)
    tab.title = title
    tab.terminal_title = ""
    tab.renamed = False
    tab.label = StubLabel()
    tab.label.set_text(title)
    tab.set_tooltip_text = lambda _text: None
    return tab


def test_tab_get_text_returns_identity_not_the_rendered_title(app_module, monkeypatch):
    """Clone and cluster selection read get_text(); a program title must not decide those."""
    monkeypatch.setattr(app_module.conf, "TAB_TITLE_FROM_TERMINAL", 1)
    tab = _tab_label(app_module)

    tab.set_terminal_title("npm run build")

    assert tab.label.get_text() == "  prod-web-01: npm run build  "
    assert tab.get_text() == "  prod-web-01  "


def test_tab_title_is_ignored_when_the_preference_is_off(app_module, monkeypatch):
    monkeypatch.setattr(app_module.conf, "TAB_TITLE_FROM_TERMINAL", 0)
    tab = _tab_label(app_module)

    tab.set_terminal_title("npm run build")

    assert tab.label.get_text() == "  prod-web-01  "


def test_set_terminal_title_sanitises_before_rendering(app_module, monkeypatch):
    """The label is fed straight into set_markup elsewhere, so it must arrive clean."""
    monkeypatch.setattr(app_module.conf, "TAB_TITLE_FROM_TERMINAL", 1)
    tab = _tab_label(app_module)

    tab.set_terminal_title("  bell\x07here   and\x1bescape  ")

    assert tab.terminal_title == "bellhere andescape"
    assert tab.label.get_text() == "  prod-web-01: bellhere andescape  "


def test_set_terminal_title_truncates_before_rendering(app_module, monkeypatch):
    monkeypatch.setattr(app_module.conf, "TAB_TITLE_FROM_TERMINAL", 1)
    tab = _tab_label(app_module)

    tab.set_terminal_title("y" * 300)

    assert len(tab.terminal_title) == logpaths.TAB_TITLE_MAX
    assert tab.label.get_text().endswith("…  ")


def test_manual_rename_becomes_identity_and_outranks_later_titles(app_module, monkeypatch):
    monkeypatch.setattr(app_module.conf, "TAB_TITLE_FROM_TERMINAL", 1)
    tab = _tab_label(app_module)

    tab.rename("my session")
    assert tab.get_text() == "  my session  "

    tab.set_terminal_title("program tries again")

    assert tab.label.get_text() == "  my session  "
    assert tab.get_text() == "  my session  "


def test_an_empty_title_leaves_the_tab_alone(app_module, monkeypatch):
    """Programs clear the title on exit; that must not blank the tab."""
    monkeypatch.setattr(app_module.conf, "TAB_TITLE_FROM_TERMINAL", 1)
    tab = _tab_label(app_module)

    tab.set_terminal_title("busy")
    tab.set_terminal_title("")

    assert tab.label.get_text() == "  prod-web-01  "


def test_closed_tab_markup_escapes_the_label(app_module, monkeypatch):
    """A label containing & failed set_markup outright before this; OSC titles make it reachable."""
    monkeypatch.setattr(app_module.conf, "TAB_TITLE_FROM_TERMINAL", 1)
    monkeypatch.setattr(app_module.conf, "AUTO_CLOSE_TAB", 0)
    monkeypatch.setattr(
        app_module.GLib,
        "markup_escape_text",
        lambda t: t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"),
        raising=False,
    )
    tab = _tab_label(app_module)
    tab.is_active = False
    tab.set_terminal_title("A & B <b>x</b>")

    tab.mark_tab_as_closed()

    assert "&amp;" in tab.label.markup
    assert "&lt;b&gt;" in tab.label.markup


def test_glib_really_provides_markup_escape_text():
    """The stub above would happily pass against a function that does not exist."""
    gi = pytest.importorskip("gi", reason="PyGObject not available")
    gi.require_version("Gtk", "3.0")
    from gi.repository import GLib

    assert GLib.markup_escape_text("A & B") == "A &amp; B"


class TitleTerminal(ClipboardTerminal):
    def __init__(self, title, label):
        super().__init__()
        self._title = title
        self._label = label

    def get_window_title(self):
        return self._title

    def get_parent(self):
        pane = types.SimpleNamespace()
        pane.get_parent = lambda: types.SimpleNamespace(get_tab_label=lambda _p: self._label)
        return pane


def test_on_terminal_title_changed_updates_the_tab(app_module, monkeypatch):
    monkeypatch.setattr(app_module.conf, "TAB_TITLE_FROM_TERMINAL", 1)
    wmain = object.__new__(app_module.Wmain)
    tab = _tab_label(app_module)
    terminal = TitleTerminal("npm run build", tab)

    wmain.on_terminal_title_changed(terminal)

    assert tab.label.get_text() == "  prod-web-01: npm run build  "


def test_on_terminal_title_changed_tolerates_a_plain_tab_label(app_module):
    """Glade placeholder pages carry a label with no set_terminal_title."""
    wmain = object.__new__(app_module.Wmain)
    terminal = TitleTerminal("anything", PlainTabLabel())

    wmain.on_terminal_title_changed(terminal)  # must not raise


def test_window_title_changed_is_wired_at_creation(app_module):
    connections = _terminal_signal_connections(app_module)

    assert connections.get("window-title-changed") == "on_terminal_title_changed"


def test_a_program_set_title_cannot_reach_the_log_path(tmp_path, app_module, monkeypatch):
    """#18's headline risk: OSC titles are remote-controlled, and logging once read the label.

    Decoupled by #49, but this is the regression that would matter, so it is named.
    """
    monkeypatch.setattr(app_module.conf, "LOG_PATH", str(tmp_path))
    monkeypatch.setattr(app_module.conf, "TAB_TITLE_FROM_TERMINAL", 1)
    monkeypatch.setattr(app_module.time, "strftime", lambda fmt: "20260823")
    wmain = object.__new__(app_module.Wmain)

    tab = _tab_label(app_module)
    tab.set_terminal_title("../../../../tmp/pwned")
    assert "pwned" in tab.label.get_text()  # the label really did take the title

    terminal = LoggingTerminal(LogHost(group="Work", name="web-01", user="root"))
    wmain.set_terminal_logger(terminal)
    terminal.log.close()

    written = list(tmp_path.rglob("*.log"))
    assert written == [tmp_path / "Work" / "web-01" / "root-20260823-001.log"]
    assert not list(tmp_path.parent.glob("pwned*"))


# -- dropping files onto a terminal (#22) -----------------------------------


@pytest.fixture
def _real_uri_decoding(monkeypatch, app_module):
    """conftest stubs GLib, so filename_from_uri would fall into the except branch."""
    from urllib.parse import unquote, urlparse

    def filename_from_uri(uri):
        parsed = urlparse(uri)
        return unquote(parsed.path), parsed.hostname

    monkeypatch.setattr(app_module.GLib, "filename_from_uri", filename_from_uri, raising=False)


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        ("file:///tmp/a.py", "/tmp/a.py"),
        ("file:///tmp/my%20notes.txt", "'/tmp/my notes.txt'"),
        ("file:///tmp/weird%3Bname%26here.txt", "'/tmp/weird;name&here.txt'"),
        ("https://example.com/x?a=1&b=2", "'https://example.com/x?a=1&b=2'"),
        ("sftp://host/path", "sftp://host/path"),
        ("  ", ""),
        ("", ""),
        (None, ""),
    ],
)
def test_uri_to_terminal_text(app_module, _real_uri_decoding, uri, expected):
    """Quoting matters: an unquoted space or & lands as several broken arguments."""
    assert app_module.uri_to_terminal_text(uri) == expected


def test_uris_to_terminal_text_joins_and_skips_blanks(app_module, _real_uri_decoding):
    text = app_module.uris_to_terminal_text(["file:///tmp/a.py", "", "file:///tmp/b%20c.py", None])

    assert text == "/tmp/a.py '/tmp/b c.py'"


def test_glib_really_decodes_file_uris():
    """The fixture above would pass against a GLib that has no such function."""
    gi = pytest.importorskip("gi", reason="PyGObject not available")
    gi.require_version("Gtk", "3.0")
    from gi.repository import GLib

    assert GLib.filename_from_uri("file:///tmp/my%20notes.txt")[0] == "/tmp/my notes.txt"


class DropTerminal:
    """The feed surface vte_feed uses. Vte.Terminal really has feed_child."""

    def __init__(self):
        self.fed = []

    def feed_child(self, data, *args):
        self.fed.append(data)


class DropData:
    def __init__(self, uris=None, text=None):
        self._uris = uris
        self._text = text

    def get_uris(self):
        return self._uris

    def get_text(self):
        return self._text


def _drop(app_module, monkeypatch, data):
    finished = []
    monkeypatch.setattr(
        app_module.Gtk,
        "drag_finish",
        lambda ctx, success, delete, t: finished.append(success),
        raising=False,
    )
    wmain = object.__new__(app_module.Wmain)
    terminal = DropTerminal()
    handled = wmain.on_terminal_drag_data_received(terminal, object(), 0, 0, data, 0, 0)
    return terminal, finished, handled


def test_dropping_files_inserts_quoted_paths(app_module, monkeypatch, _real_uri_decoding):
    terminal, finished, handled = _drop(
        app_module, monkeypatch, DropData(uris=["file:///tmp/a.py", "file:///tmp/b%20c.py"])
    )

    assert terminal.fed == [b"/tmp/a.py '/tmp/b c.py'"]
    assert finished == [True]
    assert handled is True


def test_dropped_paths_carry_no_trailing_newline(app_module, monkeypatch, _real_uri_decoding):
    """Same reasoning as paste hygiene: leave it at the prompt for review."""
    terminal, _finished, _handled = _drop(
        app_module, monkeypatch, DropData(uris=["file:///tmp/a.py"])
    )

    assert not terminal.fed[0].endswith(b"\n")


def test_dropping_plain_text_inserts_it_verbatim(app_module, monkeypatch):
    """A text drop is text, not a path, so it must not be shell-quoted."""
    terminal, finished, _handled = _drop(
        app_module, monkeypatch, DropData(text="some dragged words")
    )

    assert terminal.fed == [b"some dragged words"]
    assert finished == [True]


def test_an_empty_drop_feeds_nothing(app_module, monkeypatch):
    terminal, finished, _handled = _drop(app_module, monkeypatch, DropData())

    assert terminal.fed == []
    assert finished == [False]


def test_uri_drop_wins_over_text_when_both_are_offered(app_module, monkeypatch, _real_uri_decoding):
    """File managers offer both; the URI is the one that carries a usable path."""
    terminal, _finished, _handled = _drop(
        app_module,
        monkeypatch,
        DropData(uris=["file:///tmp/a.py"], text="file:///tmp/a.py"),
    )

    assert terminal.fed == [b"/tmp/a.py"]


def test_drag_targets_are_registered_at_creation(app_module):
    source = Path(app_module.__file__).read_text()
    body = source.split("def addTab", 1)[1].split("\n    def ", 1)[0]

    assert "drag_dest_add_uri_targets()" in body
    assert "drag_dest_add_text_targets()" in body
    connections = _terminal_signal_connections(app_module)
    assert connections.get("drag-data-received") == "on_terminal_drag_data_received"


# -- file:line links (#23) --------------------------------------------------


@pytest.mark.parametrize(
    ("match", "expected"),
    [
        ("src/app.py:42", ("src/app.py", 42, 0)),
        ("src/app.py:42:7", ("src/app.py", 42, 7)),
        ("/abs/mod.rs:1234:56", ("/abs/mod.rs", 1234, 56)),
        ("  padded.py:3  ", ("padded.py", 3, 0)),
        ("no-line.py", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_file_location(app_module, match, expected):
    assert app_module.parse_file_location(match) == expected


class LocationTerminal:
    def __init__(self, host=None, cwd_uri=None, pgid_cwd=None):
        self.host = host
        self._cwd_uri = cwd_uri
        self._pgid_cwd = pgid_cwd

    def get_current_directory_uri(self):
        return self._cwd_uri

    def get_pty(self):
        return types.SimpleNamespace(get_fd=lambda: 7) if self._pgid_cwd else None


def test_terminal_is_local_only_for_a_shell_session(app_module):
    """A path printed by a remote host does not exist here."""
    assert app_module.terminal_is_local(LocationTerminal(LogHost(name="local", host=""))) is True
    assert (
        app_module.terminal_is_local(LocationTerminal(LogHost(name="w", host="10.0.0.5"))) is False
    )
    assert app_module.terminal_is_local(LocationTerminal(None)) is False


def test_working_directory_prefers_osc7(app_module, monkeypatch, _real_uri_decoding):
    terminal = LocationTerminal(cwd_uri="file:///srv/from%20osc7", pgid_cwd="/other")
    monkeypatch.setattr(app_module.os, "tcgetpgrp", lambda fd: 123)
    monkeypatch.setattr(app_module.os, "readlink", lambda p: "/other")

    assert app_module.terminal_working_directory(terminal) == "/srv/from osc7"


def test_working_directory_falls_back_to_the_pty_process(app_module, monkeypatch):
    """Measured: bash emits no OSC 7 by default, so this is the path that actually runs."""
    terminal = LocationTerminal(cwd_uri=None, pgid_cwd="/srv/work")
    monkeypatch.setattr(app_module.os, "tcgetpgrp", lambda fd: 123)
    monkeypatch.setattr(app_module.os, "readlink", lambda p: "/srv/work")

    assert app_module.terminal_working_directory(terminal) == "/srv/work"


def test_working_directory_is_none_without_a_pty(app_module):
    assert app_module.terminal_working_directory(LocationTerminal()) is None


def test_build_editor_command_prefers_the_configured_template(app_module, monkeypatch):
    monkeypatch.setattr(app_module.conf, "EDITOR_COMMAND", "code --goto {file}:{line}:{col}")

    assert app_module.build_editor_command("/tmp/x.py", 42, 7) == [
        "code",
        "--goto",
        "/tmp/x.py:42:7",
    ]


def test_build_editor_command_uses_editor_with_the_plus_line_convention(app_module, monkeypatch):
    monkeypatch.setattr(app_module.conf, "EDITOR_COMMAND", "")
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setenv("EDITOR", "vim")

    assert app_module.build_editor_command("/tmp/x.py", 42, 7) == ["vim", "+42", "/tmp/x.py"]


def test_build_editor_command_falls_back_to_xdg_open(app_module, monkeypatch):
    monkeypatch.setattr(app_module.conf, "EDITOR_COMMAND", "")
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.delenv("EDITOR", raising=False)

    assert app_module.build_editor_command("/tmp/x.py", 42, 7) == ["xdg-open", "/tmp/x.py"]


@pytest.fixture
def _spawned(monkeypatch, app_module):
    calls = []
    monkeypatch.setattr(app_module.subprocess, "Popen", lambda cmd, *a, **k: calls.append(cmd))
    monkeypatch.setattr(app_module.conf, "EDITOR_COMMAND", "ed {file} {line}")
    return calls


def test_open_file_location_resolves_a_relative_path(tmp_path, app_module, monkeypatch, _spawned):
    (tmp_path / "app.py").write_text("x\n")
    terminal = LocationTerminal(LogHost(name="local", host=""), pgid_cwd=str(tmp_path))
    monkeypatch.setattr(app_module.os, "tcgetpgrp", lambda fd: 1)
    monkeypatch.setattr(app_module.os, "readlink", lambda p: str(tmp_path))

    assert app_module.Wmain.open_file_location(None, terminal, "app.py:42") is True
    assert _spawned == [["ed", str(tmp_path / "app.py"), "42"]]


def test_open_file_location_skips_remote_sessions(tmp_path, app_module, _spawned):
    (tmp_path / "app.py").write_text("x\n")
    terminal = LocationTerminal(LogHost(name="w", host="10.0.0.5"))

    result = app_module.Wmain.open_file_location(None, terminal, f"{tmp_path / 'app.py'}:42")

    assert result is False
    assert _spawned == []


def test_open_file_location_skips_a_path_that_does_not_exist(tmp_path, app_module, _spawned):
    terminal = LocationTerminal(LogHost(name="local", host=""))

    result = app_module.Wmain.open_file_location(None, terminal, f"{tmp_path / 'gone.py'}:42")

    assert result is False
    assert _spawned == []


def test_open_file_location_ignores_a_non_location_match(app_module, _spawned):
    terminal = LocationTerminal(LogHost(name="local", host=""))

    assert app_module.Wmain.open_file_location(None, terminal, "not-a-location") is False
    assert _spawned == []


def test_file_pattern_is_registered_as_a_match(app_module):
    source = Path(app_module.__file__).read_text()
    body = source.split("def registerUrlRegexes", 1)[1].split("\n    def ", 1)[0]

    assert "urlregex.FILE_LINE" in body
    assert "terminal.tag_file" in body


class ClickTerminal:
    def __init__(self, match, tag, tag_file):
        self._match = match
        self._tag = tag
        self.tag_file = tag_file
        self.tag_url = "url"
        self.tag_email = "email"

    def match_check_event(self, event):
        return self._match, self._tag


def _ctrl_click_event(app_module):
    return types.SimpleNamespace(
        type=app_module.Gdk.EventType.BUTTON_PRESS,
        button=1,
        get_state=lambda: 1,  # conftest maps CONTROL_MASK to 1
    )


def test_ctrl_click_on_a_file_match_opens_it(app_module, monkeypatch):
    """Without this the match is registered, shows a pointer, and does nothing."""
    opened = []
    monkeypatch.setattr(
        app_module.Wmain,
        "open_file_location",
        lambda self, term, match: opened.append(match) or True,
        raising=False,
    )
    wmain = object.__new__(app_module.Wmain)
    terminal = ClickTerminal("src/app.py:42", "file", "file")

    assert wmain.on_terminal_click(terminal, _ctrl_click_event(app_module)) is True
    assert opened == ["src/app.py:42"]


def test_ctrl_click_on_a_url_does_not_go_to_the_file_handler(app_module, monkeypatch):
    opened = []
    shown = []
    monkeypatch.setattr(
        app_module.Wmain,
        "open_file_location",
        lambda self, term, match: opened.append(match),
        raising=False,
    )
    monkeypatch.setattr(app_module.Gtk, "show_uri", lambda *a: shown.append(a), raising=False)
    wmain = object.__new__(app_module.Wmain)
    terminal = ClickTerminal("www.example.com", "url", "file")
    terminal.hyperlink_check_event = lambda e: None
    terminal.get_parent = lambda: types.SimpleNamespace(
        get_parent=lambda: types.SimpleNamespace(
            get_nth_page=lambda i: None, get_current_page=lambda: 0
        )
    )
    wmain.on_tab_focus = lambda *a: None

    wmain.on_terminal_click(terminal, _ctrl_click_event(app_module))

    assert opened == []
    assert shown, "a url should still reach show_uri"


@pytest.mark.filterwarnings("ignore:Vte.Terminal.match_check is deprecated")
@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="needs a display for a real terminal")
def test_file_line_pattern_matches_only_real_locations():
    """The pattern must require both an extension and a line number.

    Without the line number every bare word matches; without the extension "host:22"
    does. Checked against real PCRE2 through VTE, since that is what compiles it.
    """
    gi = pytest.importorskip("gi", reason="PyGObject not available")
    gi.require_version("Gtk", "3.0")
    gi.require_version("Vte", "2.91")
    from gi.repository import Gtk, Vte

    from gnome_connection_manager.utils import urlregex

    def settle(seconds=0.6):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)
            time.sleep(0.01)

    window = Gtk.Window()
    terminal = Vte.Terminal()
    window.add(terminal)
    window.show_all()
    settle()  # the terminal has no grid until it is realised

    regex = Vte.Regex.new_for_match(
        urlregex.FILE_LINE, len(urlregex.FILE_LINE), urlregex.PCRE2_FLAGS
    )
    tag = terminal.match_add_regex(regex, 0)

    should_match = ["src/app.py:42", "src/app.py:42:7", "./rel/f.ts:10", "/abs/m.rs:1:2"]
    should_not = ["file.py", "host:22", "192.168.1.10:8080", "plain words", "app.py:"]
    for line in should_match + should_not:
        terminal.feed((line + "\r\n").encode())
    settle()

    def matched(row, text):
        for col in range(len(text)):
            found = terminal.match_check(col, row)
            if found and found[0] and found[1] == tag:
                return found[0]
        return None

    for row, text in enumerate(should_match):
        assert matched(row, text) == text, f"{text!r} should match"
    for offset, text in enumerate(should_not):
        row = len(should_match) + offset
        assert matched(row, text) is None, f"{text!r} should not match"

    window.destroy()


# -- buffer viewer (#24) ----------------------------------------------------


class BufferTerminal:
    def __init__(self, range_text="", screen_text="", lower=0, upper=0):
        self.range_text = range_text
        self.screen_text = screen_text
        self._lower, self._upper = lower, upper
        self.range_calls = []
        self.selected = []

    def get_vadjustment(self):
        return types.SimpleNamespace(get_lower=lambda: self._lower, get_upper=lambda: self._upper)

    def get_text_range_format(self, fmt, srow, scol, erow, ecol):
        self.range_calls.append((srow, scol, erow, ecol))
        return self.range_text

    def get_text_format(self, fmt):
        return self.screen_text

    def select_all(self):
        self.selected.append("all")


def test_buffer_text_reads_the_real_row_bounds(app_module):
    terminal = BufferTerminal(range_text="a\nb\nc\n", lower=0, upper=401)

    assert app_module.terminal_buffer_text(terminal) == "a\nb\nc"
    assert terminal.range_calls == [(0, 0, 401, 0)]


def test_buffer_text_never_disturbs_the_selection(app_module):
    """select_all()+get_text_selected_full() would work, but destroys the user's selection."""
    terminal = BufferTerminal(range_text="a\n", lower=0, upper=10)

    app_module.terminal_buffer_text(terminal)

    assert terminal.selected == []


def test_buffer_text_falls_back_to_the_visible_screen(app_module):
    """The alternate screen has no scrollback, so the range comes back empty."""
    terminal = BufferTerminal(range_text="   \n  ", screen_text="ALT-0\nALT-1\n", lower=0, upper=7)

    assert app_module.terminal_buffer_text(terminal) == "ALT-0\nALT-1"


def test_buffer_text_handles_a_tuple_return(app_module):
    """Older VTE returns (text, attrs) from the range call."""
    terminal = BufferTerminal(lower=0, upper=3)
    terminal.get_text_range_format = lambda *a: ("x\ny\n", None)

    assert app_module.terminal_buffer_text(terminal) == "x\ny"


# -- the viewer must not go blank on the alternate screen (#107) -------------


class FormatTerminal:
    """A terminal that answers each format separately, the way VTE does.

    The alternate screen is the case that matters. The vertical adjustment still
    describes rows there, but the range export cannot read them back -- measured on VTE
    0.76, it answers with newlines and nothing else -- so only get_text_format() holds
    the content a full-screen application put on screen.
    """

    def __init__(self, app_module, ranges=None, screens=None, lower=0, upper=0):
        self._formats = app_module.Vte.Format
        self.ranges = ranges or {}
        self.screens = screens or {}
        self._lower, self._upper = lower, upper
        self.screen_calls = []
        self.range_calls = []

    def _name(self, fmt):
        return "html" if fmt == self._formats.HTML else "text"

    def get_vadjustment(self):
        return types.SimpleNamespace(get_lower=lambda: self._lower, get_upper=lambda: self._upper)

    def get_text_range_format(self, fmt, srow, scol, erow, ecol):
        self.range_calls.append((self._name(fmt), srow, scol, erow, ecol))
        return self.ranges.get(self._name(fmt), "")

    def get_text_format(self, fmt):
        self.screen_calls.append(self._name(fmt))
        return self.screens.get(self._name(fmt), "")


# What VTE hands back for a range of empty rows: markup around nothing but newlines.
BLANK_ROWS_HTML = "<pre>\n\n\n\n</pre>"
ALT_SCREEN_HTML = '<pre><font color="#00C000">ALT row</font>\n</pre>'


def test_buffer_html_falls_back_to_the_visible_screen(app_module):
    """Its text twin already falls through here; without the same fall through the
    viewer rendered a full-screen application as a page of empty rows."""
    terminal = FormatTerminal(
        app_module,
        ranges={"html": BLANK_ROWS_HTML},
        screens={"html": ALT_SCREEN_HTML},
        lower=0,
        upper=12,
    )

    assert app_module.terminal_buffer_html(terminal) == ALT_SCREEN_HTML


def test_buffer_html_keeps_the_range_when_it_carries_text(app_module):
    """The scrollback is the point of the viewer; the screen is only the fallback."""
    scrollback = "<pre>scrollback line\n</pre>"
    terminal = FormatTerminal(
        app_module,
        ranges={"html": scrollback},
        screens={"html": ALT_SCREEN_HTML},
        lower=0,
        upper=401,
    )

    assert app_module.terminal_buffer_html(terminal) == scrollback
    assert terminal.range_calls == [("html", 0, 0, 401, 0)]
    assert terminal.screen_calls == [], "the screen must not be read when rows exist"


def test_buffer_html_and_text_agree_on_the_alternate_screen(app_module):
    """The two exports promise the same rows and differ only in attributes."""
    terminal = FormatTerminal(
        app_module,
        ranges={"html": BLANK_ROWS_HTML, "text": "\n\n\n\n"},
        screens={"html": ALT_SCREEN_HTML, "text": "ALT row\n"},
        lower=0,
        upper=12,
    )

    html = app_module.terminal_buffer_html(terminal)
    runs = app_module.vtehtml.parse_vte_html(html)

    assert app_module.vtehtml.plain_text(runs).strip() == (
        app_module.terminal_buffer_text(terminal).strip()
    )


def test_buffer_html_returns_none_when_nothing_has_text(app_module):
    """A genuinely empty terminal must still let the caller fall back to plain text."""
    terminal = FormatTerminal(
        app_module, ranges={"html": BLANK_ROWS_HTML}, screens={"html": ""}, lower=0, upper=4
    )

    assert app_module.terminal_buffer_html(terminal) is None


def test_buffer_html_handles_a_tuple_return(app_module):
    """Older VTE returns (text, attrs) from the range call."""
    terminal = FormatTerminal(app_module, lower=0, upper=3)
    terminal.get_text_range_format = lambda *a: ("<pre>x\n</pre>", None)

    assert app_module.terminal_buffer_html(terminal) == "<pre>x\n</pre>"


class FakeTextBuffer:
    """Enough Gtk.TextBuffer for render_styled and trim_trailing_blank_lines."""

    def __init__(self):
        self.text = ""

    def get_end_iter(self):
        return len(self.text)

    def insert(self, _end, text):
        self.text += text

    def insert_with_tags(self, _end, text, _tag):
        self.text += text

    def get_bounds(self):
        return 0, len(self.text)

    def get_text(self, start, end, _include_hidden):
        return self.text[start:end]

    def get_iter_at_offset(self, offset):
        return offset

    def delete(self, start, _end):
        self.text = self.text[:start]

    def create_tag(self, *_args, **_kwargs):
        return object()


def _viewer_for(app_module, html):
    viewer = object.__new__(app_module.BufferViewer)
    viewer.terminal = object()
    viewer.buffer = FakeTextBuffer()
    viewer._style_tags = {}
    return viewer


def test_render_styled_reports_failure_for_rows_with_no_text(app_module, monkeypatch):
    """A grid of blank rows parses into one whitespace run, and a run list is truthy --
    so testing the list instead of its text let a blank render shadow the fallback."""
    monkeypatch.setattr(app_module, "terminal_buffer_html", lambda _t: BLANK_ROWS_HTML)
    viewer = _viewer_for(app_module, BLANK_ROWS_HTML)

    assert viewer.render_styled() is False
    assert viewer.buffer.text == "", "a failed render must leave nothing behind"


def test_render_styled_renders_an_export_that_has_text(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "terminal_buffer_html", lambda _t: ALT_SCREEN_HTML)
    viewer = _viewer_for(app_module, ALT_SCREEN_HTML)

    assert viewer.render_styled() is True
    assert viewer.buffer.text == "ALT row"


def test_show_buffer_viewer_opens_a_window_for_the_terminal(app_module, monkeypatch):
    made = []

    class FakeViewer:
        def __init__(self, controller, terminal, title):
            made.append((terminal, title))

        def show_all(self):
            made.append("shown")

    monkeypatch.setattr(app_module, "BufferViewer", FakeViewer)
    wmain = object.__new__(app_module.Wmain)
    tab = _tab_label(app_module)
    terminal = TitleTerminal("t", tab)

    wmain.show_buffer_viewer(terminal)

    assert made[0][0] is terminal
    assert "prod-web-01" in made[0][1]
    assert "shown" in made


def test_show_buffer_viewer_ignores_a_missing_terminal(app_module):
    wmain = object.__new__(app_module.Wmain)

    assert wmain.show_buffer_viewer(None) is None


def test_view_buffer_is_a_configurable_shortcut_in_a_menu(app_module):
    defaults = {command: key for command, _token, key in app_module.SHORTCUT_DEFAULTS}

    assert defaults["view_buffer"] == "CTRL+SHIFT+F"
    assert app_module.TERMINAL_ACTIONS["view_buffer"] == "view-buffer"
    assert "view-buffer" in _context_menu_actions(app_module)


# conftest stubs gi across the whole session, so the real widget cannot be built in
# process -- BufferViewer would inherit a stub Gtk.Window. This runs in a clean
# interpreter, which is the only way to exercise the search against a real TextView.
_VIEWER_SCRIPT = """
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(); sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk
from gnome_connection_manager import app

class Snapshot:
    def get_vadjustment(self): return None
    def get_text_format(self, fmt): return "alpha needle\\nbeta\\ngamma needle\\ndelta\\n"

v = app.BufferViewer(None, Snapshot(), "test")
v.show_all()
for _ in range(50): Gtk.main_iteration_do(False)

assert v.get_all_text().splitlines() == ["alpha needle", "beta", "gamma needle", "delta"], v.get_all_text()
assert v.view.get_editable() is False
assert v.view.get_monospace() is True

v.search.set_text("needle")
assert v.on_search_changed(v.search) == 2
# the count is not proof the highlight was applied
probe = v.buffer.get_start_iter().forward_search("needle", Gtk.TextSearchFlags.CASE_INSENSITIVE, None)
assert probe is not None
assert probe[0].has_tag(v.match_tag), "matches must be highlighted, not just counted"

assert v.find(forward=True) is True
first = v.buffer.get_selection_bounds()[0].get_line()
assert v.find(forward=True) is True
second = v.buffer.get_selection_bounds()[0].get_line()
assert second > first, (first, second)
assert v.find(forward=True) is True
assert v.buffer.get_selection_bounds()[0].get_line() == first, "search must wrap"
assert v.find(forward=False) is True

v.search.set_text("absent")
assert v.find(forward=True) is False
assert v.on_search_changed(v.search) == 0

assert v.get_selected_text() != ""

# Copy Selection must copy the selection, not everything
from gi.repository import Gdk
clip = Gtk.Clipboard.get_default(Gdk.Display.get_default())
start = v.buffer.get_iter_at_line(1)
end = v.buffer.get_iter_at_line(2)
v.buffer.select_range(start, end)
v.on_copy_selection(None)
for _ in range(50): Gtk.main_iteration_do(False)
copied = clip.wait_for_text() or ""
assert copied.strip() == "beta", repr(copied)
assert copied != v.get_all_text()

v.destroy()
print("OK")
"""


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="needs a display for a real window")
def test_buffer_viewer_search_and_copy_against_real_gtk():
    """Search, wrap-around and read-only behaviour against a real Gtk.TextView."""
    pytest.importorskip("gi", reason="PyGObject not available")
    result = subprocess.run(
        [sys.executable, "-c", _VIEWER_SCRIPT],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        timeout=120,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert "OK" in result.stdout


# The whole point of #107 is a viewer built on a terminal a full-screen application
# holds. Only a real Vte.Terminal has an alternate screen at all, so this is the check
# that would have caught it -- the in-process tests can only assert the shape of the
# fix, not that VTE behaves the way the fix assumes.
_ALT_SCREEN_SCRIPT = """
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(); sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk, GLib, Vte
from gnome_connection_manager import app

term = Vte.Terminal(); term.set_scrollback_lines(1000); term.set_size(80, 24)
win = Gtk.Window(); win.set_default_size(700, 400); win.add(term); win.show_all()

def pump(ms=400):
    loop = GLib.MainLoop(); GLib.timeout_add(ms, lambda: (loop.quit(), False)[1]); loop.run()

pump(500)
for i in range(30):
    term.feed(("scrollback %d\\r\\n" % i).encode())
pump()
# Exactly what GitHub Copilot CLI sends on startup: alternate screen, then a clear.
term.feed(b"\\x1b[?1049h\\x1b[H\\x1b[2J")
term.feed(b"\\x1b[1;32mALT green row\\x1b[m\\r\\nALT plain row\\r\\n")
pump(500)

html = app.terminal_buffer_html(term)
assert html and "ALT green row" in html, repr(html)
v = app.BufferViewer(None, term, "alt")
v.show_all()
for _ in range(50): Gtk.main_iteration_do(False)

shown = v.get_all_text()
assert shown.strip(), "the viewer must not be blank on the alternate screen"
assert "ALT green row" in shown, repr(shown)
assert "ALT plain row" in shown, repr(shown)
# Colour survives the fallback, so the viewer stays styled rather than dropping to
# plain text -- get_text_format(HTML) carries attributes just as the range export does.
assert v._style_tags, "the styled path must have run, not the plain-text fallback"

v.destroy(); win.destroy()
print("OK")
"""


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="needs a display for a real window")
def test_buffer_viewer_shows_the_alternate_screen_against_real_vte():
    """A full-screen application leaves the range export blank; the viewer must not be."""
    pytest.importorskip("gi", reason="PyGObject not available")
    result = subprocess.run(
        [sys.executable, "-c", _ALT_SCREEN_SCRIPT],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        timeout=120,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert "OK" in result.stdout


def test_view_buffer_shortcut_opens_the_viewer(app_module, monkeypatch):
    """The shortcut is the discoverable route; without dispatch it is inert."""
    opened = []
    monkeypatch.setattr(
        app_module.Wmain,
        "show_buffer_viewer",
        lambda self, term: opened.append(term),
        raising=False,
    )
    monkeypatch.setattr(app_module, "get_key_name", lambda event: "CTRL+SHIFT+F")
    monkeypatch.setattr(app_module, "shortcuts", {"CTRL+SHIFT+F": app_module._VIEW_BUFFER})
    wmain = object.__new__(app_module.Wmain)
    terminal = ClipboardTerminal()

    wmain.on_terminal_keypress(terminal, object())

    assert opened == [terminal]


# -- a line the session ends on must still be written (#68) ------------------


def test_flush_writes_the_line_the_session_ends_on(monkeypatch, app_module):
    """The row guard means an unfinished line is never written otherwise."""
    monkeypatch.setattr(app_module.Vte, "get_minor_version", lambda: 80, raising=False)
    wmain = object.__new__(app_module.Wmain)
    terminal = LogTerminal("progress: 100%", row=0, col=14)

    assert wmain.flush_terminal_log(terminal) is True
    assert terminal.log.entries == ["progress: 100%"]
    assert terminal.log.flushes == 1


def test_flush_advances_the_checkpoint_so_it_cannot_double_write(monkeypatch, app_module):
    monkeypatch.setattr(app_module.Vte, "get_minor_version", lambda: 80, raising=False)
    wmain = object.__new__(app_module.Wmain)
    terminal = LogTerminal("progress: 100%", row=0, col=14)

    wmain.flush_terminal_log(terminal)

    assert wmain.flush_terminal_log(terminal) is False
    assert terminal.log.entries == ["progress: 100%"]


def test_flush_writes_nothing_when_the_cursor_has_not_moved(app_module):
    """A line already logged by on_contents_changed must not be written twice."""
    wmain = object.__new__(app_module.Wmain)
    terminal = LogTerminal("already written", row=0, col=0)

    assert wmain.flush_terminal_log(terminal) is False
    assert terminal.log.entries == []


def test_flush_is_harmless_without_a_log(app_module):
    wmain = object.__new__(app_module.Wmain)
    terminal = LogTerminal("x", row=0, col=3)
    del terminal.log

    assert wmain.flush_terminal_log(terminal) is False


def test_flush_is_harmless_before_logging_ever_started(app_module):
    wmain = object.__new__(app_module.Wmain)
    terminal = LogTerminal("x", row=0, col=3)
    del terminal.last_logged_row

    assert wmain.flush_terminal_log(terminal) is False


def test_flush_writes_nothing_for_an_empty_range(monkeypatch, app_module):
    monkeypatch.setattr(app_module.Vte, "get_minor_version", lambda: 80, raising=False)
    wmain = object.__new__(app_module.Wmain)
    terminal = LogTerminal("", row=0, col=5)

    assert wmain.flush_terminal_log(terminal) is False
    assert terminal.log.entries == []


def test_disabling_logging_flushes_first(monkeypatch, app_module):
    """Disconnecting the handler without flushing loses the current line."""
    monkeypatch.setattr(app_module.Vte, "get_minor_version", lambda: 80, raising=False)
    wmain = object.__new__(app_module.Wmain)
    terminal = LogTerminal("tail of the session", row=0, col=19)
    terminal.log_handler_id = 7
    disconnected: list = []
    terminal.disconnect = disconnected.append

    wmain.set_terminal_logger(terminal, False)

    assert terminal.log.entries == ["tail of the session"]
    assert disconnected == [7]


def test_child_exit_flushes_and_marks_the_tab(monkeypatch, app_module):
    monkeypatch.setattr(app_module.Vte, "get_minor_version", lambda: 80, raising=False)
    wmain = object.__new__(app_module.Wmain)
    terminal = LogTerminal("last line", row=0, col=9)
    marked = []

    wmain.on_terminal_child_exited(
        terminal, types.SimpleNamespace(mark_tab_as_closed=lambda: marked.append(True))
    )

    assert terminal.log.entries == ["last line"]
    assert marked == [True]


def test_child_exit_is_wired_to_the_flushing_handler(app_module):
    """Connected through a lambda, since the handler needs the tab as well as the
    terminal, so the name check the other signals use cannot see it."""
    source = Path(app_module.__file__).read_text()
    body = source.split("def addTab", 1)[1].split("\n    def ", 1)[0]

    connect = next(line for line in body.splitlines() if "child-exited" in line)
    assert "on_terminal_child_exited" in connect, connect
