"""Tests for selected Wmain helpers that depend on tree/host interactions."""

from __future__ import annotations

import configparser
import inspect
import os
import re
import shutil
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


class FakeTreePath(tuple):
    def copy(self):
        return self


class RecordingTreeStore:
    """The slice of Gtk.TreeStore the tree code uses, kept as nested nodes."""

    def __init__(self):
        self.roots: list = []

    def clear(self):
        self.roots.clear()

    def append(self, parent, row):
        node = types.SimpleNamespace(row=list(row), children=[])
        (parent.children if parent is not None else self.roots).append(node)
        return node

    def get_value(self, node, column):
        return node.row[column]

    def get_iter_first(self):
        return self.roots[0] if self.roots else None

    def get_iter(self, path):
        nodes, node = self.roots, None
        for index in path:
            node = nodes[index]
            nodes = node.children
        return node

    def foreach(self, func):
        def walk(nodes, prefix):
            for index, node in enumerate(nodes):
                path = FakeTreePath((*prefix, index))
                if func(self, path, node) or walk(node.children, path):
                    return True
            return False

        walk(self.roots, ())

    def find(self, name):
        found: list = []
        self.foreach(lambda _m, path, node: node.row[0] == name and found.append((path, node)))
        return found[0]

    def shape(self, nodes=None):
        nodes = self.roots if nodes is None else nodes
        return [
            (n.row[0], self.shape(n.children)) if n.children or n.row[1] is None else n.row[0]
            for n in nodes
        ]


class FolderTreeView:
    """The slice of Gtk.TreeView the folder and drag code uses."""

    def __init__(self, store):
        self.store = store
        self.selected = None
        self.dest = None
        self.pressed = None
        self.collapsed: set = set()
        self.cursor = None
        self.expanded_to: list = []
        self.stopped: list = []
        self.dest_row = "unset"

    def get_selection(self):
        return types.SimpleNamespace(
            get_selected=lambda: (self.store, self.selected),
            unselect_all=lambda: setattr(self, "selected", None),
        )

    def get_dest_row_at_pos(self, _x, _y):
        return self.dest

    def get_path_at_pos(self, _x, _y):
        return None if self.pressed is None else (self.pressed, None, 0, 0)

    def set_drag_dest_row(self, path, pos):
        self.dest_row = (path, pos)

    def stop_emission_by_name(self, name):
        self.stopped.append(name)

    def expand_all(self):
        self.collapsed.clear()

    def collapse_row(self, path):
        self.collapsed.add(tuple(path))
        return True

    def row_expanded(self, path):
        return tuple(path) not in self.collapsed

    def expand_to_path(self, path):
        self.expanded_to.append(tuple(path))

    def set_cursor(self, path, _column, _start_editing):
        self.cursor = tuple(path)


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


def make_wmain_for_tree(app_module, monkeypatch, groups=None):
    """A Wmain whose updateTree is real, drawn onto RecordingTreeStore."""
    monkeypatch.setattr(app_module.Gtk, "MenuItem", DummyMenuItem)
    monkeypatch.setattr(app_module.Gtk, "Menu", DummyMenu)
    if groups is not None:
        monkeypatch.setattr(app_module, "groups", groups)
    wmain = object.__new__(app_module.Wmain)
    wmain.treeModel = RecordingTreeStore()
    wmain.treeServers = FolderTreeView(wmain.treeModel)
    wmain.menuServers = DummyMenu()
    wmain.nbConsole = object()
    wmain.window = object()
    wmain.update_row_color = lambda *args: None
    wmain.addTab = lambda nb, host: None
    wmain.writes = 0
    wmain.writeConfig = lambda: setattr(wmain, "writes", wmain.writes + 1)
    wmain._drag_source_path = None
    return wmain


def hosts_named(app_module, *names):
    """Hosts from make_host, renamed and filed at the given group paths."""
    made = []
    for spec in names:
        group, name = spec.rsplit("/", 1)
        host = make_host(app_module)
        host.group, host.name = group, name
        made.append(host)
    return made


def menu_shape(menu):
    return [
        (item.get_label(), menu_shape(item.get_submenu()))
        if item.get_submenu()
        else item.get_label()
        for item in menu.get_children()
    ]


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


def test_deleting_a_folder_removes_its_hosts_and_every_folder_below(monkeypatch, app_module):
    prod, db, home = hosts_named(app_module, "ops/prod/web", "ops/prod/db/pg", "home/nas")
    groups = {"ops/prod": [prod], "ops/prod/db": [db], "home": [home]}
    wmain = make_wmain_for_tree(app_module, monkeypatch, groups)
    wmain.updateTree()
    asked: list = []
    monkeypatch.setattr(
        app_module, "msgconfirm", lambda text: asked.append(text) or app_module.Gtk.ResponseType.OK
    )
    wmain.treeServers.selected = wmain.treeModel.find("prod")[1]

    wmain.on_btnDel_clicked(None)

    assert wmain.treeModel.shape() == [("home", ["nas"]), ("ops", [])]
    assert [h.name for hs in app_module.groups.values() for h in hs] == ["nas"]
    assert asked == [
        "{} [ops/prod]?".format(
            app_module._("Confirma que desea eliminar todos los hosts del grupo")
        )
    ]
    assert wmain.writes == 1


def test_deleting_an_empty_folder_asks_about_the_folder(monkeypatch, app_module):
    wmain = make_wmain_for_tree(
        app_module, monkeypatch, {"ops": hosts_named(app_module, "ops/web")}
    )
    app_module.sync_folders()
    app_module.folders.add(app_module.ROOT_FOLDER, "archive")
    wmain.updateTree()
    asked: list = []
    monkeypatch.setattr(
        app_module, "msgconfirm", lambda text: asked.append(text) or app_module.Gtk.ResponseType.OK
    )
    wmain.treeServers.selected = wmain.treeModel.find("archive")[1]

    wmain.on_btnDel_clicked(None)

    assert asked == ["{} [archive]?".format(app_module._("Delete folder"))]
    assert wmain.treeModel.shape() == [("ops", ["web"])]


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


def test_update_tree_draws_subfolders_then_hosts_each_in_name_order(monkeypatch, app_module):
    gamma, beta, alpha = hosts_named(app_module, "ops/gamma", "ops/prod/beta", "ops/alpha")
    groups = {"ops": [gamma, alpha], "ops/prod": [beta], "unused": []}
    wmain = make_wmain_for_tree(app_module, monkeypatch, groups)

    wmain.updateTree()

    assert wmain.treeModel.shape() == [("ops", [("prod", ["beta"]), "alpha", "gamma"])]
    assert menu_shape(wmain.menuServers) == [("ops", [("prod", ["beta"]), "alpha", "gamma"])]
    assert "unused" not in app_module.groups


def test_update_tree_draws_an_empty_folder_but_keeps_it_out_of_the_servers_menu(
    monkeypatch, app_module
):
    """The tree is where folders are managed; the servers menu is for connecting."""
    wmain = make_wmain_for_tree(
        app_module, monkeypatch, {"ops": hosts_named(app_module, "ops/alpha")}
    )
    app_module.sync_folders()
    app_module.folders.add(app_module.ROOT_FOLDER, "archive")

    wmain.updateTree()

    assert wmain.treeModel.shape() == [("archive", []), ("ops", ["alpha"])]
    assert menu_shape(wmain.menuServers) == [("ops", ["alpha"])]


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


def test_the_tree_menu_offers_the_folder_commands(app_module):
    """Right-click on the tree is where folders are managed from."""
    source = Path(app_module.__file__).read_text()
    body = source.split("self.popupMenuFolder = Gtk.Menu()", 1)[1]
    body = body.split("self.popupMenuTab = Gtk.Menu()", 1)[0]

    assert {"new-folder", "rename-folder", "sort-folder"} <= set(
        re.findall(r'"app\.([a-z-]+)"', body)
    )


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

    wmain.on_terminal_click(terminal, _right_click_event(app_module))

    assert terminal.pasted_text == ["echo hi"]
    assert terminal.pasted == 0


def _right_click_event(app_module, state=0):
    """A button-3 press. `get_state()` returns the mask itself, as it does on the
    Gdk.EventButton a real handler receives -- unlike Gdk.Event, whose returns a tuple."""
    return types.SimpleNamespace(
        type=app_module.Gdk.EventType.BUTTON_PRESS,
        button=3,
        x=0,
        y=0,
        time=0,
        get_state=lambda: state,
    )


@pytest.mark.parametrize(
    ("paste_on_right_click", "ctrl", "opens_menu"),
    [(1, False, False), (1, True, True), (0, False, True), (0, True, True)],
)
def test_ctrl_right_click_opens_the_menu_even_while_right_click_pastes(
    monkeypatch, app_module, paste_on_right_click, ctrl, opens_menu
):
    """Right-click pastes by default, and nothing else opened the terminal's menu, so it
    could not be reached at all while the guide sent readers to it (#171)."""
    monkeypatch.setattr(app_module.conf, "PASTE_ON_RIGHT_CLICK", paste_on_right_click)
    monkeypatch.setattr(app_module.conf, "PASTE_CONFIRM_LINES", 0)
    monkeypatch.setattr(app_module.conf, "PASTE_CONFIRM_BYTES", 0)
    popped = []
    sensitive = types.SimpleNamespace(set_sensitive=lambda _v: None)
    wmain = object.__new__(app_module.Wmain)
    wmain.popupMenu = types.SimpleNamespace(
        mnuCopy=sensitive,
        mnuSplitH=sensitive,
        mnuSplitV=sensitive,
        popup=lambda *args: popped.append(args),
    )
    terminal = ClipboardTerminal()
    terminal.get_parent = NotebookAncestor
    _clipboard(monkeypatch, app_module, "echo hi\n")
    state = app_module.Gdk.ModifierType.CONTROL_MASK if ctrl else 0

    assert wmain.on_terminal_click(terminal, _right_click_event(app_module, state)) is True

    assert bool(popped) is opens_menu
    assert terminal.pasted_text == ([] if opens_menu else ["echo hi"])


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


# -- marking a tab when its output stops or its session ends (#208) ------------------


class QuietClock:
    """time.monotonic and GLib.timeout_add for app_module, driven by the test."""

    def __init__(self):
        self.now = 100.0
        self.timers: list = []

    def monotonic(self):
        return self.now

    def timeout_add(self, interval, callback, *args):
        self.timers.append((interval, callback, args))
        return len(self.timers)


def _quiet_setup(app_module, monkeypatch, *, window_active=True, showing=False, seconds=5):
    wmain, terminal, label, page = _bell_setup(
        app_module, monkeypatch, window_active=window_active, showing=showing
    )
    monkeypatch.setattr(app_module.conf, "QUIET_MARK_SECONDS", seconds)
    monkeypatch.setattr(app_module.conf, "ENDED_MARK_TAB", 1)
    clock = QuietClock()
    monkeypatch.setattr(app_module.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(app_module.GLib, "timeout_add", clock.timeout_add)
    page.get_children = lambda: [terminal]
    return wmain, terminal, label, page, clock


def _output(wmain, terminal, clock, seconds, step=0.2):
    """Screen updates every `step` seconds for `seconds`, the way a spinner draws."""
    end = clock.now + seconds
    while clock.now <= end:
        wmain.on_terminal_contents_changed(terminal)
        clock.now += step
    clock.now -= step  # back to the last update


def _poll(clock, wmain, terminal, after):
    """Run the tab's quiet timer `after` seconds from now, as GLib would."""
    clock.now += after
    return wmain.check_quiet(terminal)


def test_output_that_stops_out_of_sight_marks_the_tab(app_module, monkeypatch):
    wmain, terminal, label, _page, clock = _quiet_setup(app_module, monkeypatch)
    _output(wmain, terminal, clock, 3)

    assert [interval for interval, _cb, _args in clock.timers] == [app_module.QUIET_POLL_MS]
    assert _poll(clock, wmain, terminal, 4.9) is True
    assert label.attention is None
    assert _poll(clock, wmain, terminal, 0.1) is False  # marked, and the timer ends
    assert label.attention is True
    assert terminal.quiet_timer is None


def test_the_quiet_timer_is_started_once_per_run(app_module, monkeypatch):
    """contents-changed fires on every redraw; a timer per redraw would pile up."""
    wmain, terminal, _label, _page, clock = _quiet_setup(app_module, monkeypatch)
    _output(wmain, terminal, clock, 3)

    assert len(clock.timers) == 1


def test_output_while_the_tab_is_watched_never_marks_it(app_module, monkeypatch):
    wmain, terminal, label, _page, clock = _quiet_setup(
        app_module, monkeypatch, window_active=True, showing=True
    )
    _output(wmain, terminal, clock, 3)

    assert clock.timers == []
    assert label.attention is None


def test_the_visible_tab_is_out_of_sight_while_gcm_is_not_the_active_window(
    app_module, monkeypatch
):
    wmain, terminal, label, _page, clock = _quiet_setup(
        app_module, monkeypatch, window_active=False, showing=True
    )
    _output(wmain, terminal, clock, 3)
    _poll(clock, wmain, terminal, 5)

    assert label.attention is True
    assert wmain.wMain.urgency is True


def test_a_single_burst_out_of_sight_does_not_mark_the_tab(app_module, monkeypatch):
    """One line of a log is not work finishing."""
    wmain, terminal, label, _page, clock = _quiet_setup(app_module, monkeypatch)
    wmain.on_terminal_contents_changed(terminal)

    assert _poll(clock, wmain, terminal, 5) is False
    assert label.attention is None


def test_quiet_marking_can_be_turned_off(app_module, monkeypatch):
    wmain, terminal, label, _page, clock = _quiet_setup(app_module, monkeypatch, seconds=0)
    _output(wmain, terminal, clock, 3)

    assert clock.timers == []
    assert label.attention is None


def test_turning_quiet_marking_off_ends_a_waiting_timer(app_module, monkeypatch):
    wmain, terminal, label, _page, clock = _quiet_setup(app_module, monkeypatch)
    _output(wmain, terminal, clock, 3)
    monkeypatch.setattr(app_module.conf, "QUIET_MARK_SECONDS", 0)

    assert _poll(clock, wmain, terminal, 60) is False
    assert label.attention is None


def test_a_changed_quiet_period_applies_to_a_tab_already_waiting(app_module, monkeypatch):
    """Preferences reach consoles already open: the timer reads conf each time."""
    wmain, terminal, label, _page, clock = _quiet_setup(app_module, monkeypatch)
    _output(wmain, terminal, clock, 3)
    monkeypatch.setattr(app_module.conf, "QUIET_MARK_SECONDS", 2)

    _poll(clock, wmain, terminal, 2)

    assert label.attention is True


def test_looking_at_the_tab_settles_what_it_was_doing_out_of_sight(app_module, monkeypatch):
    wmain, terminal, label, page, clock = _quiet_setup(app_module, monkeypatch)
    monkeypatch.setattr(app_module.conf, "UPDATE_TITLE", 0)
    _output(wmain, terminal, clock, 3)

    wmain.on_tab_focus(object(), page)  # looked, then switched away again

    assert _poll(clock, wmain, terminal, 5) is False
    assert label.attention is False


def test_a_closed_tab_ends_its_quiet_timer(app_module, monkeypatch):
    wmain, terminal, label, _page, clock = _quiet_setup(app_module, monkeypatch)
    _output(wmain, terminal, clock, 3)
    terminal.get_parent = lambda: None  # close_tab destroyed the page around it

    # At the next poll, not once the quiet period is up, when it would have ended anyway.
    assert _poll(clock, wmain, terminal, 0.5) is False
    assert terminal.quiet_timer is None
    assert label.attention is None


class EndedTab:
    """The tab label on_terminal_child_exited reports to, keeping each status it is given."""

    def __init__(self):
        self.statuses: list = []

    def mark_tab_as_closed(self, status=None):
        self.statuses.append(status)


def test_a_session_ending_out_of_sight_marks_the_tab(app_module, monkeypatch):
    wmain, terminal, label, _page, _clock = _quiet_setup(app_module, monkeypatch)
    tab = EndedTab()

    wmain.on_terminal_child_exited(terminal, tab, 0)

    assert tab.statuses == [0]
    assert label.attention is True


def test_a_session_ending_in_the_watched_tab_is_not_marked(app_module, monkeypatch):
    wmain, terminal, label, _page, _clock = _quiet_setup(
        app_module, monkeypatch, window_active=True, showing=True
    )

    wmain.on_terminal_child_exited(terminal, EndedTab(), 0)

    assert label.attention is None


def test_marking_a_session_that_ended_can_be_turned_off(app_module, monkeypatch):
    wmain, terminal, label, _page, _clock = _quiet_setup(app_module, monkeypatch)
    monkeypatch.setattr(app_module.conf, "ENDED_MARK_TAB", 0)

    wmain.on_terminal_child_exited(terminal, EndedTab(), 0)

    assert label.attention is None


def test_a_session_ending_settles_its_quiet_watch(app_module, monkeypatch):
    """The end is its own trigger; the output just before it must not mark again later."""
    wmain, terminal, label, _page, clock = _quiet_setup(app_module, monkeypatch)
    monkeypatch.setattr(app_module.conf, "ENDED_MARK_TAB", 0)
    _output(wmain, terminal, clock, 3)

    wmain.on_terminal_child_exited(terminal, EndedTab(), 0)

    assert _poll(clock, wmain, terminal, 5) is False
    assert label.attention is None


def test_every_trigger_can_raise_the_notification(app_module, monkeypatch):
    application = BellApplication()
    wmain, terminal, _label, _page, clock = _quiet_setup(
        app_module, monkeypatch, window_active=False
    )
    wmain.wMain.application = application
    monkeypatch.setattr(app_module.conf, "BELL_NOTIFY", 1)

    _output(wmain, terminal, clock, 3)
    _poll(clock, wmain, terminal, 5)
    wmain.on_terminal_child_exited(terminal, EndedTab(), 0)

    assert [ident for ident, _n in application.sent] == ["gcm-bell", "gcm-bell"]


def test_contents_changed_is_wired_to_the_quiet_watch(app_module):
    source = Path(app_module.__file__).read_text()
    body = source.split("def addTab", 1)[1].split("\n    def ", 1)[0]

    connect = next(line for line in body.splitlines() if '"contents-changed"' in line)
    assert "on_terminal_contents_changed" in connect, connect


# Two local tabs; the second is current, so the first is out of sight in its pane whether
# or not the X server lets the window be active -- under Xvfb it was.
_QUIET_MARK_SCRIPT = """
import os, sys, tempfile, time
os.environ["HOME"] = tempfile.mkdtemp(); sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk, Vte
from gnome_connection_manager import app

app.conf.QUIET_MARK_SECONDS = 1
app.conf.ENDED_MARK_TAB = 1
app.conf.AUTO_CLOSE_TAB = 0

def pump(until, what, limit=20):
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        Gtk.main_iteration_do(False)
        if until():
            return
        time.sleep(0.005)
    raise AssertionError("timed out waiting for " + what)

def text(v):
    return v.get_text_format(Vte.Format.TEXT) or ""

app.wMain = app.Wmain(application=None)
nb = app.wMain.nbConsole
host = app.Host("Work", "local", "", "", "", "", "local")
app.wMain.addTab(nb, host)
page_a = nb.get_nth_page(nb.get_n_pages() - 1)
app.wMain.addTab(nb, host)
page_b = nb.get_nth_page(nb.get_n_pages() - 1)
va, vb = page_a.get_children()[0], page_b.get_children()[0]
label_a, label_b = nb.get_tab_label(page_a), nb.get_tab_label(page_b)
assert nb.get_current_page() == nb.page_num(page_b)
pump(lambda: text(va).strip() and text(vb).strip(), "both prompts")
pump(lambda: getattr(va, "quiet_timer", None) is None, "the prompt's own output to settle")
app.wMain.clear_tab_attention(page_a)

# $((i*11)) so the echoed command line cannot satisfy the wait; only its output can.
app.vte_feed(va, "for i in 1 2 3 4 5 6; do echo tick$((i*11)); sleep 0.3; done\\r")
pump(lambda: "tick66" in text(va), "the last tick")
last_tick = time.monotonic()
assert not label_a.needs_attention, "marked while its output was still running"
pump(lambda: label_a.needs_attention, "the quiet tab to be marked", limit=10)
waited = time.monotonic() - last_tick
assert waited >= 1.0, "marked %.2fs after the last tick, inside the quiet period" % waited
assert label_a.get_style_context().has_class("attention")
assert va.quiet_timer is None, "the timer outlived the mark"

app.wMain.clear_tab_attention(page_a)
app.vte_feed(va, "exit\\r")
pump(lambda: not label_a.is_active, "the first session to end")
assert label_a.needs_attention, "a session ending out of sight was not marked"

# Close the second tab while it waits, with a quiet period it cannot reach in time.
nb.set_current_page(nb.page_num(page_a))
app.vte_feed(vb, "for i in 1 2 3 4 5 6 7 8; do echo tock$((i*11)); sleep 0.3; done\\r")
pump(lambda: "tock33" in text(vb), "the second tab's output")
assert vb.quiet_watch.waiting
app.conf.QUIET_MARK_SECONDS = 30
label_b.close_tab(None)
# VTE emits child-exited as close_tab destroys the terminal, which settles the watch.
assert not vb.quiet_watch.waiting, "closing the tab left its watch running"
assert vb.get_parent() is None, "check_quiet reads a closed tab as one with no parent"
pump(lambda: vb.quiet_timer is None, "a closed tab's timer to end", limit=5)
print("OK")
"""


@pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"),
    reason="needs a display for a real terminal",
)
def test_a_tab_out_of_sight_is_marked_when_its_output_stops_against_real_gtk():
    """Mutation tested: with contents-changed not connected the quiet tab is never
    marked, and with the session end not marking the tab, or not settling its watch,
    the assertion for each fails.

    Removing `check_quiet`'s closed-tab branch does not fail it: closing the tab
    settles the watch through child-exited first. The unit test covers that branch."""
    pytest.importorskip("gi", reason="PyGObject not available")
    result = subprocess.run(
        [sys.executable, "-c", _QUIET_MARK_SCRIPT],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        timeout=120,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert "Traceback" not in result.stderr, result.stderr[-2000:]
    assert "OK" in result.stdout


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

    def fake(terminal, log_path, claim):
        seen.update(log_path=log_path, claim=claim)
        return "sentinel"

    monkeypatch.setattr(app_module.logpaths, "session_stem_for", fake)
    monkeypatch.setattr(app_module.conf, "LOG_PATH", str(tmp_path / "logs"))

    assert app_module.session_file_for(types.SimpleNamespace(), ".raw") == "sentinel.raw"
    # The claim is the file asked for, so the one reserving the number is the one written.
    assert seen == {"log_path": str(tmp_path / "logs"), "claim": ".raw"}


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


def test_set_terminal_logger_refuses_a_log_outside_the_log_path(tmp_path, app_module, monkeypatch):
    """Nothing written, the handler it connected let go, and the refusal said aloud."""
    said = []
    monkeypatch.setattr(app_module.conf, "LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setattr(app_module.logpaths, "sanitize_log_name", lambda title: title)
    monkeypatch.setattr(app_module, "msgbox", lambda text, *a, **k: said.append(text))
    wmain = object.__new__(app_module.Wmain)
    terminal = LoggingTerminal(LogHost(name="../escaped"))

    assert wmain.set_terminal_logger(terminal) is False
    assert not hasattr(terminal, "log")
    assert not hasattr(terminal, "log_handler_id")
    assert ("disconnect", 1) in terminal.connected
    assert said and str(tmp_path / "logs") in said[0]
    assert not list(tmp_path.rglob("*.log"))


# -- a session's files share one number (#200) ------------------------------


def logging_folder(tmp_path, app_module, monkeypatch, earlier=None):
    """1. Projects/pyproject-template as it was found, with `earlier` left by a session
    before this one."""
    monkeypatch.setattr(app_module.conf, "LOG_PATH", str(tmp_path))
    monkeypatch.setattr(app_module.time, "strftime", lambda fmt: "20260925")
    folder = tmp_path / "1. Projects" / "pyproject-template"
    folder.mkdir(parents=True)
    if earlier:
        (folder / f"session-20260925-001{earlier}").write_text("an earlier session\n")
    return folder, LoggingTerminal(LogHost(group="1. Projects", name="pyproject-template"))


def test_a_recording_takes_the_number_its_text_log_took(tmp_path, app_module, monkeypatch):
    """What was found: a session that was not recorded, then one that was, gave
    002.log beside 001.raw. The log opens with the tab and chose first; the recording
    opens at spawn and chose again, among .raw files only."""
    folder, terminal = logging_folder(tmp_path, app_module, monkeypatch, earlier=".log")
    wmain = object.__new__(app_module.Wmain)

    wmain.set_terminal_logger(terminal)
    terminal.log.close()

    assert Path(terminal.log.name) == folder / "session-20260925-002.log"
    assert app_module.session_file_for(terminal, ".raw") == str(folder / "session-20260925-002.raw")


def test_a_log_switched_on_mid_session_takes_the_recordings_number(
    tmp_path, app_module, monkeypatch
):
    """The other order: recording from the spawn, logging switched on from the menu later,
    after a day that began with a recording only. That gave 001.log beside 002.raw."""
    folder, terminal = logging_folder(tmp_path, app_module, monkeypatch, earlier=".raw")
    wmain = object.__new__(app_module.Wmain)
    raw = app_module.session_file_for(terminal, ".raw")
    Path(raw).write_bytes(b"what the relay wrote")

    wmain.set_terminal_logger(terminal)
    terminal.log.close()

    assert raw == str(folder / "session-20260925-002.raw")
    assert Path(terminal.log.name) == folder / "session-20260925-002.log"


def test_a_reconnect_keeps_the_tabs_number_and_a_new_tab_takes_the_next(
    tmp_path, app_module, monkeypatch
):
    """vte_run asks again on every spawn. Numbering afresh split one tab's recording
    across files while its log carried on in one; a number shared beyond the tab would
    put two sessions in one file."""
    folder, terminal = logging_folder(tmp_path, app_module, monkeypatch)
    first = app_module.session_file_for(terminal, ".raw")
    Path(first).write_bytes(b"first connection")

    assert app_module.session_file_for(terminal, ".raw") == first
    other = LoggingTerminal(terminal.host)
    assert app_module.session_file_for(other, ".raw") == str(folder / "session-20260925-002.raw")


# -- the number is reserved as it is chosen (#202) ------------------------------


def test_two_tabs_for_one_host_opened_together_take_two_numbers(tmp_path, app_module, monkeypatch):
    """Nothing written between the two, as when the relay has not started yet: it creates
    a recording about 35 ms after the spawn, and both tabs recorded into one 001.raw."""
    folder, first = logging_folder(tmp_path, app_module, monkeypatch)
    second = LoggingTerminal(first.host)

    paths = [app_module.session_file_for(t, ".raw") for t in (first, second)]

    assert paths == [
        str(folder / "session-20260925-001.raw"),
        str(folder / "session-20260925-002.raw"),
    ]


def test_a_new_log_is_not_mistaken_for_an_earlier_one(tmp_path, app_module, monkeypatch):
    """Choosing the number creates the log, empty. Read as an existing file, every new
    session announced it was appending to an earlier one and wrote its end marker."""
    said = []
    monkeypatch.setattr(app_module, "msgbox", lambda text, *a, **k: said.append(text))
    folder, terminal = logging_folder(tmp_path, app_module, monkeypatch)
    wmain = object.__new__(app_module.Wmain)

    wmain.set_terminal_logger(terminal)
    terminal.log.close()

    assert said == []
    assert (folder / "session-20260925-001.log").read_text().startswith("Session '")


def test_appending_to_an_earlier_log_is_still_announced(tmp_path, app_module, monkeypatch):
    """The last number is reused once all 999 are taken, and that log has a session in it."""
    said = []
    monkeypatch.setattr(app_module, "msgbox", lambda text, *a, **k: said.append(text))
    folder, terminal = logging_folder(tmp_path, app_module, monkeypatch)
    last = folder / "session-20260925-999.log"
    last.write_text("the 999th session\n")
    monkeypatch.setattr(
        app_module.logpaths, "next_session_stem", lambda prefix, claim: str(last)[:-4]
    )
    wmain = object.__new__(app_module.Wmain)

    wmain.set_terminal_logger(terminal)
    terminal.log.close()

    assert len(said) == 1 and str(last) in said[0]
    text = last.read_text()
    assert text.startswith("the 999th session\n\n\n=====")
    assert "Session '" in text.split("=====")[-1]


def test_the_last_number_without_a_log_of_its_own_opens_one_quietly(
    tmp_path, app_module, monkeypatch
):
    """Reused once all 999 are taken, the number may have a recording and no log. Its log
    is new, not an earlier one -- and not one that cannot be opened, which is what
    reading the size of a file that is not there would have made of it."""
    said = []
    monkeypatch.setattr(app_module, "msgbox", lambda text, *a, **k: said.append(text))
    folder, terminal = logging_folder(tmp_path, app_module, monkeypatch)
    (folder / "session-20260925-999.raw").write_bytes(b"a recording, and no log")
    monkeypatch.setattr(
        app_module.logpaths, "next_session_stem", lambda prefix, claim: f"{prefix}-999"
    )
    wmain = object.__new__(app_module.Wmain)

    assert wmain.set_terminal_logger(terminal) is True
    terminal.log.close()

    assert said == []
    assert (folder / "session-20260925-999.log").read_text().startswith("Session '")


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


# The same, for #200: a session that was not recorded, then one that was, gave 002.log
# beside 001.raw. The unit tests above stand in for the two call sites; this drives the
# real ones -- addTab opening the log, vte_run starting the relay that writes the
# recording, and vte_run again for a reconnect, as Reopen and Ctrl+N do.
_ADDTAB_RECORDING_SCRIPT = """
import os, sys, tempfile, time
os.environ["HOME"] = tempfile.mkdtemp(); sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk
from pathlib import Path
from gnome_connection_manager import app

logs = Path(tempfile.mkdtemp())
app.conf.LOG_PATH = str(logs)
app.conf.RAW_SESSION_LOG = True
stem = "admed-" + time.strftime("%Y%m%d")
folder = logs / "Work" / "bastion"
folder.mkdir(parents=True)
(folder / (stem + "-001.log")).write_text("an earlier session, not recorded")

def pump(until, what):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        Gtk.main_iteration_do(False)
        if until():
            return
        time.sleep(0.005)
    raise AssertionError("timed out waiting for " + what)

app.wMain = app.Wmain(application=None)
host = app.Host("Work", "bastion", "", "", "admed")
host.log = True
app.wMain.addTab(app.wMain.nbConsole, host)
nb = app.wMain.nbConsole
v = nb.get_nth_page(nb.get_n_pages() - 1).get_children()[0]
raw, log = Path(v.raw_path), folder / (stem + "-002.log")
timing = Path(app.timing_path_for(v.raw_path))

def accounted():
    counts = [int(line.split()[1]) for line in timing.read_text().splitlines() if line]
    return sum(counts) == raw.stat().st_size

def check_files(when):
    found = sorted(p.name for p in folder.iterdir())
    names = ("-001.log", "-002.log", "-002.raw", "-002.timing")
    expected = sorted(stem + suffix for suffix in names)
    assert found == expected, "%s: found %r, expected %r" % (when, found, expected)

exited = []
v.connect("child-exited", lambda *_: exited.append(True))
# $((6*7)) so the echoed command line cannot satisfy the wait; only its output can.
pump(lambda: raw.exists() and raw.stat().st_size > 0, "the relay to start recording")
app.vte_feed(v, "echo FIRST_$((6*7))\\r")
pump(lambda: b"FIRST_42" in raw.read_bytes(), "the first session's output")
check_files("once the session was recording")
app.vte_feed(v, "exit\\r")
pump(lambda: exited, "the first session to end")
recorded = raw.stat().st_size

app.vte_run(v, app.SHELL)
assert v.raw_path == str(raw), "the reconnect moved the recording to %s" % v.raw_path
pump(lambda: raw.stat().st_size > recorded, "the reconnected session")
app.vte_feed(v, "echo SECOND_$((6*7))\\r")
pump(lambda: b"SECOND_42" in raw.read_bytes() and accounted(), "the second session's output")
pump(lambda: v.log.flush() or "SECOND_42" in log.read_text(), "the text log to catch up")

check_files("after the reconnect")
data = raw.read_bytes()
assert data.index(b"FIRST_42") < data.index(b"SECOND_42"), "the recording lost a session"
text = log.read_text()
assert text.index("FIRST_42") < text.index("SECOND_42"), "the text log lost a session"
print("OK")
"""


@pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"),
    reason="needs a display for a real terminal",
)
def test_a_tabs_files_share_one_number_across_a_reconnect_against_real_gtk():
    """Mutation tested: with the recording numbered on its own again this reports
    002.log beside 001.raw, the listing #200 was filed from."""
    pytest.importorskip("gi", reason="PyGObject not available")
    result = subprocess.run(
        [sys.executable, "-c", _ADDTAB_RECORDING_SCRIPT],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        timeout=120,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert "OK" in result.stdout


# #202: two tabs for one host, opened before either relay had created its recording,
# both chose 001 and recorded into one file. Opened the way the command line opens them.
_CLI_TWICE_RECORDING_SCRIPT = """
import os, sys, tempfile, time
os.environ["HOME"] = tempfile.mkdtemp(); sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk
from pathlib import Path
from gnome_connection_manager import app

logs = Path(tempfile.mkdtemp())
app.conf.LOG_PATH = str(logs)
app.conf.RAW_SESSION_LOG = True
stem = "admed-" + time.strftime("%Y%m%d")
folder = logs / "Work" / "bastion"

def pump(until, what):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        Gtk.main_iteration_do(False)
        if until():
            return
        time.sleep(0.005)
    raise AssertionError("timed out waiting for " + what)

app.wMain = app.Wmain(application=None)
host = app.Host("Work", "bastion", "", "", "admed")
host.log = False  # the log would reserve the number itself, before the spawn
app.groups["Work"] = [host]
nb = app.wMain.nbConsole
before = nb.get_n_pages()
# What `gnome-connection-manager Work/bastion Work/bastion` does once the window is up.
app.wMain.open_cli_targets(["Work/bastion", "Work/bastion"])
tabs = [nb.get_nth_page(i).get_children()[0] for i in range(before, nb.get_n_pages())]
assert len(tabs) == 2, "opened %d tabs" % len(tabs)
raws = [Path(t.raw_path) for t in tabs]
# Each terminal's own prompt, not the files: two tabs sharing one recording fill it as
# soon as either relay starts. And nothing is typed before then, because the relay's
# tty.setraw flushes input that arrived ahead of it.
pump(lambda: all(t.get_cursor_position()[0] > 0 for t in tabs), "both prompts")
pump(lambda: all(r.exists() and r.stat().st_size for r in raws), "both recordings")

found = sorted(p.name for p in folder.iterdir())
names = ("-001.raw", "-001.timing", "-002.raw", "-002.timing")
expected = sorted(stem + suffix for suffix in names)
assert found == expected, "found %r, expected %r" % (found, expected)
# $((6*7)) so the echoed command line cannot satisfy the wait; only its output can.
for n, t in enumerate(tabs):
    app.vte_feed(t, "echo TAB%d_$((6*7))\\r" % n)
pump(lambda: all(b"TAB%d_42" % n in r.read_bytes() for n, r in enumerate(raws)), "each tab")
for n, raw in enumerate(raws):
    assert b"TAB%d_42" % (1 - n) not in raw.read_bytes(), raw.name + " holds the other tab"
print("OK")
"""


@pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"),
    reason="needs a display for a real terminal",
)
def test_two_tabs_opened_together_record_apart_against_real_gtk():
    """Mutation tested: run against the code before the reservation, five times out of
    five it finds one 001.raw and 001.timing for the two tabs, what #202 was filed from."""
    pytest.importorskip("gi", reason="PyGObject not available")
    result = subprocess.run(
        [sys.executable, "-c", _CLI_TWICE_RECORDING_SCRIPT],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        timeout=120,
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
    tab.is_active = True
    tab.label = StubLabel()
    tab.label.set_text(title)
    tab.full_text = title.strip()
    tab.tooltips = []
    tab.set_tooltip_text = tab.tooltips.append
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


@pytest.mark.parametrize("closed", [False, True])
def test_a_rerendered_tab_follows_the_title_setting_both_ways(app_module, monkeypatch, closed):
    """Preferences re-renders every tab on OK (#174), so the setting has to reach a tab
    in both directions from what it already stored -- and a session that has ended must
    stay greyed and struck through, which set_text alone would clear."""
    monkeypatch.setattr(app_module.conf, "TAB_TITLE_FROM_TERMINAL", 1)
    monkeypatch.setattr(app_module.conf, "AUTO_CLOSE_TAB", 0)
    # Real GLib provides this; test_glib_really_provides_markup_escape_text checks.
    monkeypatch.setattr(app_module.GLib, "markup_escape_text", lambda t: t, raising=False)
    tab = _tab_label(app_module)
    tab.set_terminal_title("htop")
    if closed:
        tab.mark_tab_as_closed()

    def shown():
        if closed:
            assert tab.label.markup is not None and "strikethrough='true'" in tab.label.markup
            return re.sub(r"<[^>]+>", "", tab.label.markup)
        assert tab.label.markup is None
        return tab.label.get_text()

    assert shown() == "  prod-web-01: htop  "
    monkeypatch.setattr(app_module.conf, "TAB_TITLE_FROM_TERMINAL", 0)
    tab.render_label()
    assert shown() == "  prod-web-01  "
    monkeypatch.setattr(app_module.conf, "TAB_TITLE_FROM_TERMINAL", 1)
    tab.render_label()
    assert shown() == "  prod-web-01: htop  "


class PreferencesTerminal:
    """Records, in order, what Preferences sets on a terminal. The real Vte.Terminal has
    each of these methods (checked below)."""

    def __init__(self, host=None):
        self.host = host
        self.calls = []

    def set_word_char_exceptions(self, exceptions):
        self.calls.append(("word chars", exceptions))

    def set_scrollback_lines(self, lines):
        self.calls.append(("scrollback", lines))

    def set_colors(self, foreground, background, palette):
        spec = lambda colour: None if colour is None else colour.spec  # noqa: E731
        size = None if palette is None else len(palette)
        self.calls.append(("colours", spec(foreground), spec(background), size))

    def set_color_background(self, background):
        self.calls.append(("background", background.spec, round(background.alpha, 2)))

    def set_font(self, font):
        self.calls.append(("font", font))

    def set_audible_bell(self, audible):
        self.calls.append(("bell", audible))

    def set(self, name):
        return [call for call in self.calls if call[0] == name]


def test_preferences_terminal_fake_matches_real_vte():
    gi = pytest.importorskip("gi", reason="PyGObject not available")
    gi.require_version("Vte", "2.91")
    from gi.repository import Vte

    for name in (
        "set_word_char_exceptions",
        "set_scrollback_lines",
        "set_colors",
        "set_color_background",
        "set_font",
        "set_audible_bell",
    ):
        assert hasattr(PreferencesTerminal, name), f"fake is missing {name}"
        assert hasattr(Vte.Terminal, name), f"Vte.Terminal has no {name}"


@pytest.fixture
def preferences(app_module, monkeypatch):
    """Preferences as a user might leave them, and a Wmain to apply them. Colours are
    parsed into records the fake can report, and a font description is its text."""
    for name, value in {
        "BUFFER_LINES": 123,
        "WORD_SEPARATORS": "-A-",
        "FONT_COLOR": "#FFFF00",
        "BACK_COLOR": "#0000FF",
        "FONT": "Monospace 21",
        "BELL_AUDIBLE": 0,
        "TRANSPARENCY": 0,
    }.items():
        monkeypatch.setattr(app_module.conf, name, value)
    monkeypatch.setattr(
        app_module, "parse_color_rgba", lambda spec: types.SimpleNamespace(spec=spec, alpha=1.0)
    )
    monkeypatch.setattr(app_module.Pango, "FontDescription", lambda text: text, raising=False)
    wmain = object.__new__(app_module.Wmain)
    wmain.wMain = types.SimpleNamespace(transparency=False)
    return wmain


def test_preferences_reach_every_open_console(app_module, preferences):
    """addTab applied these only when it made a terminal, and a tab rendered the program's
    title only when the title changed (#174, #181). Two panes, as a split leaves."""
    terminal_class = type("Terminal", (PreferencesTerminal, app_module.Vte.Terminal), {})
    own = types.SimpleNamespace(font_color="#FFFFFF", back_color="#00AA00")
    rendered = []

    def console(name, host=None):
        terminal = terminal_class(host)
        page = types.SimpleNamespace(get_children=lambda: [terminal])
        label = types.SimpleNamespace(render_label=lambda: rendered.append(name))
        return terminal, types.SimpleNamespace(page=page, label=label)

    (first, one), (second, two), (third, three) = console("a"), console("b", own), console("c")
    preferences.open_console_groups = lambda: [("left", [one, two]), ("right", [three])]

    preferences.apply_settings_to_open_consoles()

    for terminal in (first, second, third):
        assert terminal.set("word chars") == [("word chars", "-A-")]
        assert terminal.set("scrollback") == [("scrollback", 123)]
        assert terminal.set("font") == [("font", "Monospace 21")]
        assert terminal.set("bell") == [("bell", False)]
    assert first.set("colours") == third.set("colours") == [("colours", "#FFFF00", "#0000FF", 16)]
    assert second.set("colours") == [("colours", "#FFFFFF", "#00AA00", 16)], "a host's own win"
    assert rendered == ["a", "b", "c"]


def test_default_colours_put_an_open_console_back_to_vte_s_own(
    app_module, preferences, monkeypatch
):
    """A new console with the default colours never had set_colors called. An open one has
    to be given None to get there: measured, that draws what a new terminal draws."""
    monkeypatch.setattr(app_module.conf, "FONT_COLOR", "")
    monkeypatch.setattr(app_module.conf, "BACK_COLOR", "")
    terminal = PreferencesTerminal()

    preferences.apply_preferences_to_terminal(terminal)

    assert terminal.set("colours") == [("colours", None, None, None)]


def test_a_host_needs_both_colours_to_keep_its_own(preferences):
    terminal = PreferencesTerminal(types.SimpleNamespace(font_color="#FFFFFF", back_color=""))

    preferences.apply_preferences_to_terminal(terminal)

    assert terminal.set("colours") == [("colours", "#FFFF00", "#0000FF", 16)]


@pytest.mark.parametrize(
    ("foreground", "background", "expected"),
    [("#FFFF00", "#0000FF", "#0000FF"), ("", "", "#000000")],
)
def test_transparency_goes_on_after_the_colours(
    app_module, preferences, monkeypatch, foreground, background, expected
):
    """set_colors resets the background's alpha -- measured -- so it has to come first."""
    monkeypatch.setattr(app_module.conf, "FONT_COLOR", foreground)
    monkeypatch.setattr(app_module.conf, "BACK_COLOR", background)
    monkeypatch.setattr(app_module.conf, "TRANSPARENCY", 30)
    preferences.wMain.transparency = True
    terminal = PreferencesTerminal()

    preferences.apply_preferences_to_terminal(terminal)

    names = [call[0] for call in terminal.calls]
    assert names.index("colours") < names.index("background")
    assert terminal.set("background") == [("background", expected, 0.7)]


def test_transparency_needs_a_screen_that_can_show_it(app_module, preferences, monkeypatch):
    monkeypatch.setattr(app_module.conf, "TRANSPARENCY", 30)
    terminal = PreferencesTerminal()

    preferences.apply_preferences_to_terminal(terminal)

    assert terminal.set("background") == []


def test_the_default_font_is_monospace_and_stays_unwritten(app_module, preferences, monkeypatch):
    """addTab used to write "monospace" into conf.FONT when it was empty. Preferences
    treats the two alike, so reading it is enough."""
    monkeypatch.setattr(app_module.conf, "FONT", "")
    terminal = PreferencesTerminal()

    preferences.apply_preferences_to_terminal(terminal)

    assert terminal.set("font") == [("font", "monospace")]
    assert app_module.conf.FONT == ""


def test_addtab_sets_nothing_preferences_decides_itself(app_module):
    """One method sets these for a new console and an open one alike. A setter that
    addTab kept for itself would reach only the consoles opened after a change."""
    source = inspect.getsource(app_module.Wmain.addTab)

    assert "self.apply_preferences_to_terminal(v)" in source
    for setter in (
        "set_word_char_exceptions",
        "set_scrollback_lines",
        "set_colors",
        "set_color_background",
        "set_font(",
        "set_audible_bell",
    ):
        assert setter not in source, f"addTab calls {setter} itself"


# The fakes above record calls; this checks what real terminals end up with, through a
# real Wmain: a console opened before Preferences changes, one whose host has colours of
# its own, and one opened after. HOME is redirected so this can never touch a real ~/.gcm.
_PREFERENCES_SCRIPT = """
import os, sys, tempfile, time
os.environ["HOME"] = tempfile.mkdtemp(); os.environ["SHELL"] = "/bin/sh"; sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk
from gnome_connection_manager import app

def pump(seconds=0.3):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        Gtk.main_iteration_do(False); time.sleep(0.005)

app.wMain = wmain = app.Wmain(application=None)
wmain.wMain.show_all()

def open_console(host):
    wmain.addTab(wmain.nbConsole, host)
    pump()
    notebook = wmain.nbConsole
    return notebook.get_nth_page(notebook.get_n_pages() - 1).get_children()[0]

def look(term):
    return (
        term.get_font().to_string(),
        term.get_audible_bell(),
        term.get_word_char_exceptions(),
        term.get_color_background_for_draw().to_string(),
    )

own = app.Host("", "own colours")
own.font_color, own.back_color = "#FFFFFF", "#00AA00"
before, hosted = open_console("local"), open_console(own)
before.set_font_scale(2.0)

app.conf.FONT, app.conf.BELL_AUDIBLE, app.conf.WORD_SEPARATORS = "Monospace 21", 0, "-A-"
app.conf.FONT_COLOR, app.conf.BACK_COLOR = "#FFFF00", "#0000FF"
wmain.apply_settings_to_open_consoles()
pump()
after = open_console("local")

expected = ("Monospace 21", False, "-A-", "rgb(0,0,255)")
assert look(before) == expected, look(before)
assert look(after) == expected, look(after)
assert look(hosted) == ("Monospace 21", False, "-A-", "rgb(0,170,0)"), look(hosted)
assert before.get_font_scale() == 2.0, "the zoom must survive a new font"

app.conf.FONT_COLOR = app.conf.BACK_COLOR = ""
wmain.apply_settings_to_open_consoles()
pump()
fresh = open_console("local")
assert look(before)[3] == look(after)[3] == look(fresh)[3] == "rgb(0,0,0)", look(before)
assert look(hosted)[3] == "rgb(0,170,0)", look(hosted)
print("OK")
"""


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="needs a display for a real window")
def test_open_consoles_look_like_new_ones_after_preferences_against_real_gtk():
    """Font, colours, word separators and the bell reached only new consoles (#181)."""
    pytest.importorskip("gi", reason="PyGObject not available")
    result = subprocess.run(
        [sys.executable, "-c", _PREFERENCES_SCRIPT],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        timeout=120,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert "OK" in result.stdout


# Split and Unsplit move a console into another notebook, and its tab label carries
# more than its text (#180). Only real notebooks show what survives the move, so drive
# a real Wmain in a subprocess. HOME is redirected so this can never touch a real ~/.gcm,
# and SHELL is one whose prompt sets no title of its own to race the test's.
_SPLIT_SCRIPT = """
import os, sys, tempfile, time
os.environ["HOME"] = tempfile.mkdtemp(); os.environ["SHELL"] = "/bin/sh"; sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk
from gnome_connection_manager import app

def pump(seconds=0.3):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        Gtk.main_iteration_do(False); time.sleep(0.005)

app.conf.TAB_TITLE_FROM_TERMINAL = 1
app.conf.AUTO_CLOSE_TAB = 0
app.wMain = wmain = app.Wmain(application=None)
wmain.wMain.show_all()

def open_console():
    wmain.addTab(wmain.nbConsole, "local")
    pump()
    notebook = wmain.nbConsole
    return notebook.get_nth_page(notebook.get_n_pages() - 1).get_children()[0]

def tab(term):
    page = term.get_parent()
    return page.get_parent().get_tab_label(page)

def look(term):
    page = term.get_parent()
    notebook, context = page.get_parent(), tab(term).get_style_context()
    return (
        tab(term).label.get_label(),
        tab(term).is_active,
        context.has_class("attention"),
        context.has_class("selected"),
        notebook.get_tab_reorderable(page) and notebook.get_tab_detachable(page),
    )

def split(term):
    page = term.get_parent()
    before = page.get_parent()
    before.set_current_page(before.page_num(page))
    wmain.current = term
    wmain.split_notebook(app.HSPLIT)
    pump()
    assert page.get_parent() is not before, "the split did not move the console"

def unsplit(term):
    wmain.on_btnUnsplit_clicked(None)
    pump()
    assert term.get_parent().get_parent() is wmain.nbConsole, "unsplit left it behind"

titled, renamed, ended, spare = (open_console() for _ in range(4))
titled.feed(b"\\x1b]0;TITLE\\x07")
tab(titled).set_selected(True)  # the cluster window's mark
tab(renamed).rename("mine")
tab(ended).mark_tab_as_closed()
pump()
STRUCK = "<span color='darkgray' strikethrough='true'>  local  </span>"

split(titled)
assert look(titled) == ("  local: TITLE  ", True, False, True, True), look(titled)
tab(titled).set_attention(True)  # the bell, in its own pane, while GCM is in the background
unsplit(titled)
assert look(titled) == ("  local: TITLE  ", True, True, True, True), look(titled)

split(renamed)
renamed.feed(b"\\x1b]0;LATER\\x07"); pump()
assert look(renamed)[0] == "  mine  ", look(renamed)
unsplit(renamed)
renamed.feed(b"\\x1b]0;LATER STILL\\x07"); pump()
assert look(renamed)[0] == "  mine  ", look(renamed)

split(ended)
assert look(ended)[:2] == (STRUCK, False), look(ended)
unsplit(ended)
assert look(ended)[:2] == (STRUCK, False), look(ended)
print("OK")
"""


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="needs a display for a real window")
def test_split_and_unsplit_keep_what_the_tab_shows_against_real_gtk():
    """A moved tab lost its program title, its rename, its ended state and its marks."""
    pytest.importorskip("gi", reason="PyGObject not available")
    result = subprocess.run(
        [sys.executable, "-c", _SPLIT_SCRIPT],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        timeout=120,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert "OK" in result.stdout


# Dragging a tab into another pane is GTK's own notebook drag-and-drop rather than GCM
# code. Measured with real pointer input: the drop carries the same NotebookTabLabel
# across, still reorderable and detachable, and the tab keeps everything it was showing
# (#186). What GCM owns there are its page-added and page-removed handlers, which run on
# a drop like any other move. So this moves pages the way a drop does -- detach, then
# insert with the label they already had -- and checks the handlers leave the label
# alone. It does not re-check GTK's own drag: that needs synthetic pointer input, and
# python-xlib is not a dependency of this project.
_DRAG_SCRIPT = """
import os, sys, tempfile, time
os.environ["HOME"] = tempfile.mkdtemp(); os.environ["SHELL"] = "/bin/sh"; sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk
from gnome_connection_manager import app

def pump(seconds=0.3):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        Gtk.main_iteration_do(False); time.sleep(0.005)

app.conf.TAB_TITLE_FROM_TERMINAL = 1
app.conf.AUTO_CLOSE_TAB = 0
app.wMain = wmain = app.Wmain(application=None)
wmain.wMain.show_all()

def open_console():
    wmain.addTab(wmain.nbConsole, "local")
    pump()
    notebook = wmain.nbConsole
    return notebook.get_nth_page(notebook.get_n_pages() - 1).get_children()[0]

def tab(term):
    page = term.get_parent()
    return page.get_parent().get_tab_label(page)

def look(term):
    return (tab(term).label.get_label(), tab(term).is_active,
            tab(term).get_style_context().has_class("selected"))

def drop(term, notebook):
    page = term.get_parent()
    label = page.get_parent().get_tab_label(page)
    page.get_parent().detach_tab(page)
    notebook.append_page(page, label)
    pump()

titled, renamed, ended, pane = (open_console() for _ in range(4))
titled.feed(b"\\x1b]0;TITLE\\x07")
tab(titled).set_selected(True)  # the cluster window's mark
tab(renamed).rename("mine")
tab(ended).mark_tab_as_closed()
pump()

# A pane of its own to drop into.
page = pane.get_parent()
wmain.nbConsole.set_current_page(wmain.nbConsole.page_num(page))
wmain.current = pane
wmain.split_notebook(app.HSPLIT)
pump()
target = pane.get_parent().get_parent()
assert target is not wmain.nbConsole, "the split did not make a second notebook"

labels = {term: tab(term) for term in (titled, renamed, ended)}
for term in (titled, renamed, ended):
    drop(term, target)
    assert term.get_parent().get_parent() is target, "the page did not move"
    assert tab(term) is labels[term], "the label that arrived is not the one that left"

assert look(titled) == ("  local: TITLE  ", True, True), look(titled)
renamed.feed(b"\\x1b]0;LATER\\x07"); pump()
assert look(renamed)[0] == "  mine  ", look(renamed)
STRUCK = "<span color='darkgray' strikethrough='true'>  local  </span>"
assert look(ended)[:2] == (STRUCK, False), look(ended)
print("OK")
"""


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="needs a display for a real window")
def test_a_tab_moved_between_notebooks_keeps_its_label_against_real_gtk():
    """A dropped tab must arrive with the label it left with, state and all (#186)."""
    pytest.importorskip("gi", reason="PyGObject not available")
    result = subprocess.run(
        [sys.executable, "-c", _DRAG_SCRIPT],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        timeout=120,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert "OK" in result.stdout


_TAB_CAP_SCRIPT = """
import os, sys, tempfile, time
os.environ["HOME"] = tempfile.mkdtemp(); os.environ["SHELL"] = "/bin/sh"; sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk
from gnome_connection_manager import app
from gnome_connection_manager.utils import logpaths

def pump(seconds=0.3):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        Gtk.main_iteration_do(False); time.sleep(0.005)

app.conf.TAB_TITLE_FROM_TERMINAL = 1
app.conf.AUTO_CLOSE_TAB = 0
app.wMain = wmain = app.Wmain(application=None)
wmain.wMain.show_all()
wmain.wMain.resize(1400, 900)
pump()

notebook = wmain.nbConsole
def tab(index):
    return notebook.get_tab_label(notebook.get_nth_page(index))

# How many tabs of this width the strip holds. A scrolled-out tab keeps its old
# allocation rather than a zero one, so ask what a tab wants instead of what it got.
def fit():
    return notebook.get_allocation().width // tab(first).get_preferred_width()[1]

TITLE = "systemctl status postgresql on node 3"
FULL = "local: " + TITLE
first = notebook.get_n_pages()  # Wmain opens a console of its own before any of these
for _ in range(8):
    wmain.addTab(wmain.nbConsole, "local")
    pump(0.2)
    notebook.get_nth_page(notebook.get_n_pages() - 1).get_children()[0].feed(
        b"\\x1b]0;" + TITLE.encode() + b"\\x07"
    )
pump(0.6)

shown = tab(first).label.get_text()
assert shown == "  " + logpaths.truncate_tab_label(FULL) + "  ", repr(shown)
assert len(shown.strip()) == logpaths.TAB_LABEL_MAX, repr(shown)
assert shown.endswith("\u2026  "), repr(shown)

# The full text survives where there is room for it: the tooltip and the console list.
assert tab(first).get_tooltip_text() == FULL, repr(tab(first).get_tooltip_text())
assert tab(first).get_display_text() == FULL, repr(tab(first).get_display_text())
assert tab(first).get_text() == "  local  ", repr(tab(first).get_text())

capped = fit()

# Now render exactly as GCM did before #190 and count again.
app.truncate_tab_label = lambda text: text
for i in range(notebook.get_n_pages()):
    tab(i).render_label()
pump(0.6)
uncapped = fit()
assert tab(first).label.get_text() == "  " + FULL + "  ", repr(tab(first).label.get_text())
assert capped > uncapped, "the cap put no more tabs on the strip: %s vs %s" % (capped, uncapped)

# A long host name is cut the moment the tab is built, before any title arrives.
app.truncate_tab_label = logpaths.truncate_tab_label
LONG_HOST = "some-really-long-hostname.example.internal"
wmain.addTab(wmain.nbConsole, LONG_HOST)
pump(0.4)
built = tab(notebook.get_n_pages() - 1)
assert built.label.get_text() == "  " + logpaths.truncate_tab_label(LONG_HOST) + "  ", repr(
    built.label.get_text()
)
assert built.get_tooltip_text() == LONG_HOST, repr(built.get_tooltip_text())

# A short label is left exactly as it was -- no padding out to the cap.
app.conf.TAB_TITLE_FROM_TERMINAL = 0
short = tab(first)
short.render_label()
pump(0.2)
assert short.label.get_text() == "  local  ", repr(short.label.get_text())
assert short.get_tooltip_text() == "local", repr(short.get_tooltip_text())

print("OK", capped, uncapped)
"""


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="needs a display for a real window")
def test_a_long_tab_label_is_cut_and_puts_more_tabs_on_the_strip_against_real_gtk():
    """#190: the stub cannot show this -- it is a question of what GTK allocates."""
    pytest.importorskip("gi", reason="PyGObject not available")
    result = subprocess.run(
        [sys.executable, "-c", _TAB_CAP_SCRIPT],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        timeout=180,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert "OK" in result.stdout


def test_set_terminal_title_sanitises_before_rendering(app_module, monkeypatch):
    """The label is fed straight into set_markup elsewhere, so it must arrive clean."""
    monkeypatch.setattr(app_module.conf, "TAB_TITLE_FROM_TERMINAL", 1)
    tab = _tab_label(app_module, "  web-01  ")  # short, so the cap stays out of this

    tab.set_terminal_title("  bell\x07here   and\x1bescape  ")

    assert tab.terminal_title == "bellhere andescape"
    assert tab.label.get_text() == "  web-01: bellhere andescape  "


def test_set_terminal_title_truncates_before_rendering(app_module, monkeypatch):
    monkeypatch.setattr(app_module.conf, "TAB_TITLE_FROM_TERMINAL", 1)
    tab = _tab_label(app_module)

    tab.set_terminal_title("y" * 300)

    assert len(tab.terminal_title) == logpaths.TAB_TITLE_MAX
    assert tab.label.get_text().endswith("…  ")


# -- the label is cut to fit the tab strip (#190) ---------------------------


def _rendered(tab):
    return tab.label.get_text()


def test_a_long_label_is_cut_for_the_strip_and_kept_in_the_tooltip(app_module, monkeypatch):
    """The tab is as wide as its text, so the neighbours pay for a long one."""
    monkeypatch.setattr(app_module.conf, "TAB_TITLE_FROM_TERMINAL", 1)
    tab = _tab_label(app_module, "  prod-db-eu-west-1a  ")

    tab.set_terminal_title("systemctl status postgresql")

    full = "prod-db-eu-west-1a: systemctl status postgresql"
    assert _rendered(tab).strip() == logpaths.truncate_tab_label(full)
    assert len(_rendered(tab).strip()) == logpaths.TAB_LABEL_MAX
    assert _rendered(tab).endswith("…  ")
    assert tab.tooltips[-1] == full, "the tooltip is the only place the rest survives"
    assert tab.get_display_text() == full


def test_a_label_that_fits_is_not_touched(app_module, monkeypatch):
    """No padding out to the cap, and no ellipsis on a tab that was already short."""
    monkeypatch.setattr(app_module.conf, "TAB_TITLE_FROM_TERMINAL", 1)
    tab = _tab_label(app_module, "  web-01  ")

    tab.set_terminal_title("htop")

    assert _rendered(tab) == "  web-01: htop  "
    assert tab.tooltips[-1] == "web-01: htop"


def test_a_long_host_name_alone_is_cut(app_module, monkeypatch):
    """The cap has to cover the name on its own, not only host-plus-title."""
    monkeypatch.setattr(app_module.conf, "TAB_TITLE_FROM_TERMINAL", 0)
    name = "some-really-long-hostname.example.internal"
    tab = _tab_label(app_module, f"  {name}  ")

    tab.render_label()

    assert _rendered(tab).strip() == logpaths.truncate_tab_label(name)
    assert tab.tooltips[-1] == name


def test_a_long_rename_is_cut_on_the_tab_but_stays_the_identity(app_module, monkeypatch):
    """get_text() feeds clone, cluster consoles and move_page; it must stay whole."""
    monkeypatch.setattr(app_module.conf, "TAB_TITLE_FROM_TERMINAL", 1)
    tab = _tab_label(app_module)

    tab.rename("a name far longer than any tab strip can show")

    assert tab.get_text() == "  a name far longer than any tab strip can show  "
    assert len(_rendered(tab).strip()) == logpaths.TAB_LABEL_MAX
    assert _rendered(tab).endswith("…  ")


def test_an_ended_session_is_cut_inside_its_markup(app_module, monkeypatch):
    """The struck-through branch renders separately, so it needs the cap of its own."""
    monkeypatch.setattr(app_module.conf, "TAB_TITLE_FROM_TERMINAL", 1)
    tab = _tab_label(app_module, "  prod-db-eu-west-1a  ")
    tab.is_active = False
    # The gi stub's GLib returns a dummy for markup_escape_text, so catch what it is
    # handed: the point is that the cut text, not the whole label, is what gets escaped.
    escaped = []
    monkeypatch.setattr(
        app_module.GLib, "markup_escape_text", lambda text: escaped.append(text) or text
    )

    tab.set_terminal_title("systemctl status postgresql")

    assert escaped[-1].strip() == logpaths.truncate_tab_label(
        "prod-db-eu-west-1a: systemctl status postgresql"
    )
    assert escaped[-1].endswith("…  ")
    assert tab.label.markup.startswith("<span color='darkgray' strikethrough='true'>")
    assert tab.tooltips[-1] == "prod-db-eu-west-1a: systemctl status postgresql"


def test_closing_a_tab_asks_about_the_tab_not_the_cut_label(app_module, monkeypatch):
    """A confirmation quoting "prod-db-eu-…" names nothing the user recognises."""
    monkeypatch.setattr(app_module.conf, "TAB_TITLE_FROM_TERMINAL", 1)
    monkeypatch.setattr(app_module.conf, "CONFIRM_ON_CLOSE_TAB", 1)
    tab = _tab_label(app_module, "  prod-db-eu-west-1a  ")
    tab.set_terminal_title("systemctl status postgresql")
    asked = []
    monkeypatch.setattr(app_module, "msgconfirm", lambda text: asked.append(text))
    tab.close_tab = lambda _widget: None

    app_module.NotebookTabLabel.on_close_tab(tab, None, None)

    assert asked and "prod-db-eu-west-1a" in asked[0]
    assert "…" not in asked[0]


def test_rename_offers_the_tab_name_not_the_cut_label(app_module, monkeypatch):
    """Prefilling with the drawn label would type the ellipsis back in as the name (#190)."""
    monkeypatch.setattr(app_module.conf, "TAB_TITLE_FROM_TERMINAL", 1)
    tab = _tab_label(app_module, "  prod-db-eu-west-1a  ")
    tab.set_terminal_title("systemctl status postgresql")
    notebook = types.SimpleNamespace(
        emit=lambda *args: None, get_current_page=lambda: 0, get_nth_page=lambda _n: None
    )
    tab.get_parent = lambda: notebook
    tab.label.get_parent = lambda: types.SimpleNamespace(get_parent=lambda: tab)
    offered = []
    monkeypatch.setattr(
        app_module, "inputbox", lambda *args, **kwargs: offered.append(args[2]) or None
    )
    wmain = object.__new__(app_module.Wmain)
    wmain.popupMenuTab = types.SimpleNamespace(label=tab.label)
    wmain.window = None

    app_module.Wmain.on_popupmenu(wmain, None, "R")

    assert offered == ["prod-db-eu-west-1a"]


def test_middle_click_close_asks_about_the_tab_not_the_cut_label(app_module, monkeypatch):
    """The other confirmation, on the other close path (#190)."""
    monkeypatch.setattr(app_module.conf, "TAB_TITLE_FROM_TERMINAL", 1)
    monkeypatch.setattr(app_module.conf, "CONFIRM_ON_CLOSE_TAB_MIDDLE", 1)
    tab = _tab_label(app_module, "  prod-db-eu-west-1a  ")
    tab.set_terminal_title("systemctl status postgresql")
    tab.widget_ = object()
    closed: list = []
    tab.close_tab = closed.append
    asked = []
    monkeypatch.setattr(
        app_module, "msgconfirm", lambda text: asked.append(text) or app_module.Gtk.ResponseType.OK
    )
    event = types.SimpleNamespace(type=app_module.Gdk.EventType.BUTTON_PRESS, button=2)

    app_module.NotebookTabLabel.popupmenu(tab, None, event, tab.label)

    assert asked and "prod-db-eu-west-1a" in asked[0]
    assert "\u2026" not in asked[0]
    assert closed == [tab.widget_]


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


# -- Close console: what happens to a tab when its session ends (#210) ----------------


class ClosingPage:
    """A tab's page, as close_tab uses it. The real Gtk.Widget has each (checked below)."""

    def __init__(self):
        self.parent = None
        self.destroyed = 0
        self.on_destroy = None

    def get_parent(self):
        return self.parent

    def destroy(self):
        self.destroyed += 1
        if self.on_destroy is not None:
            self.on_destroy()


class ClosingNotebook:
    """The notebook calls close_tab makes. The real Gtk.Notebook has each (checked below)."""

    def __init__(self, page):
        self.pages = [page]
        page.parent = self

    def page_num(self, page):
        return self.pages.index(page) if page in self.pages else -1

    def remove_page(self, index):
        self.pages.pop(index).parent = None


def test_closing_fakes_match_real_gtk():
    gi = pytest.importorskip("gi", reason="PyGObject not available")
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    for name in ("get_parent", "destroy"):
        assert hasattr(ClosingPage, name), f"fake is missing {name}"
        assert hasattr(Gtk.Widget, name), f"Gtk.Widget has no {name}"
    for name in ("page_num", "remove_page"):
        assert hasattr(ClosingNotebook, name), f"fake is missing {name}"
        assert hasattr(Gtk.Notebook, name), f"Gtk.Notebook has no {name}"


def _closing_tab(app_module, monkeypatch, mode):
    monkeypatch.setattr(app_module.conf, "AUTO_CLOSE_TAB", mode)
    # Real GLib provides this; test_glib_really_provides_markup_escape_text checks.
    monkeypatch.setattr(app_module.GLib, "markup_escape_text", lambda t: t, raising=False)
    tab = _tab_label(app_module)
    tab.widget_ = ClosingPage()
    return tab, ClosingNotebook(tab.widget_)


# Close console is 0 Never, 1 Always, 2 Only on clean exit. The statuses are wait
# statuses, as child-exited reports them against VTE 0.76: 768 is `exit 3`, 9 a SIGKILL.
@pytest.mark.parametrize(
    ("mode", "status", "closes"),
    [
        (0, 0, False),
        (0, 768, False),
        (1, 0, True),
        (1, 768, True),
        (2, 0, True),
        (2, 768, False),
        (2, 9, False),
    ],
)
def test_close_console_decides_on_the_exit_status(app_module, monkeypatch, mode, status, closes):
    """Only on clean exit asked the terminal for the status, which VTE 2.91 cannot give,
    so it raised on every session end and never closed a tab (#210)."""
    tab, notebook = _closing_tab(app_module, monkeypatch, mode)
    page = tab.widget_

    tab.mark_tab_as_closed(status)

    assert (notebook.page_num(page) < 0) is closes
    assert page.destroyed == (1 if closes else 0)
    assert tab.is_active is False


def test_only_on_clean_exit_keeps_a_tab_whose_status_is_unknown(app_module, monkeypatch):
    tab, notebook = _closing_tab(app_module, monkeypatch, 2)

    tab.mark_tab_as_closed()

    assert notebook.page_num(tab.widget_) == 0


@pytest.mark.parametrize("mode", [0, 1, 2])
def test_closing_a_tab_survives_its_session_ending_inside_the_close(app_module, monkeypatch, mode):
    """VTE emits child-exited while close_tab destroys the terminal, after the page has
    left its notebook. With Close console on, that asked for the tab to be closed again,
    and close_tab read the missing notebook and raised (#210)."""
    tab, notebook = _closing_tab(app_module, monkeypatch, mode)
    page = tab.widget_
    # What VTE does as the terminal goes: the session ends, killed.
    page.on_destroy = lambda: tab.mark_tab_as_closed(9)

    tab.close_tab(page)

    assert notebook.page_num(page) < 0
    assert page.destroyed == 1


# Each mode and each way a session ends, in one process. A tab ends out of sight, so a
# session that ends in one left open is marked (#208).
_CLOSE_CONSOLE_SCRIPT = """
import os, sys, tempfile, time
os.environ["HOME"] = tempfile.mkdtemp(); sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk, Vte
from gnome_connection_manager import app

app.conf.ENDED_MARK_TAB = 1

def pump(until, what, limit=20):
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
host = app.Host("Work", "local", "", "", "", "", "local")

def open_tab():
    app.wMain.addTab(nb, host)
    page = nb.get_nth_page(nb.get_n_pages() - 1)
    terminal = page.get_children()[0]
    pump(lambda: (terminal.get_text_format(Vte.Format.TEXT) or "").strip(), "a prompt")
    return page, nb.get_tab_label(page)

watched, _label = open_tab()
found = {}
for mode in (0, 1, 2):
    app.conf.AUTO_CLOSE_TAB = mode
    for end in ("close", "exit", "exit 3"):
        page, label = open_tab()
        nb.set_current_page(nb.page_num(watched))
        if end == "close":
            label.close_tab(None)
        else:
            app.vte_feed(page.get_children()[0], end + "\\r")
        pump(lambda: nb.page_num(page) < 0 or not label.is_active, "the session to end")
        settle(0.3)
        if nb.page_num(page) < 0:
            found[mode, end] = "closed"
        else:
            found[mode, end] = "marked" if getattr(label, "needs_attention", False) else "open"

expected = {
    (0, "close"): "closed", (0, "exit"): "marked", (0, "exit 3"): "marked",
    (1, "close"): "closed", (1, "exit"): "closed", (1, "exit 3"): "closed",
    (2, "close"): "closed", (2, "exit"): "closed", (2, "exit 3"): "marked",
}
assert found == expected, found
print("OK")
"""


@pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"),
    reason="needs a display for a real terminal",
)
def test_close_console_follows_each_mode_against_real_gtk():
    """Before #210, Only on clean exit left every tab open and unmarked, and Always and
    Only on clean exit raised whenever a tab was closed by hand. A handler that raises
    only prints its traceback, so stderr is checked as well as the outcome."""
    pytest.importorskip("gi", reason="PyGObject not available")
    result = subprocess.run(
        [sys.executable, "-c", _CLOSE_CONSOLE_SCRIPT],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        timeout=120,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert "Traceback" not in result.stderr, result.stderr[-2000:]
    assert "OK" in result.stdout


# A host with a stored password runs through ssh.expect. Real ssh, against a port that
# does not answer, with no ssh configuration read, so the port is all that decides.
_FAILED_CONNECTION_SCRIPT = """
import os, sys, tempfile, time
os.environ["HOME"] = tempfile.mkdtemp(); sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk, Vte
from gnome_connection_manager import app

app.conf.AUTO_CLOSE_TAB = 0

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
host = app.Host("Work", "unreachable", "", "127.0.0.1", "me", "not-a-password")
host.port, host.keep_alive = "1", "0"
host.extra_params = "-F /dev/null -o ConnectTimeout=2"
app.wMain.addTab(nb, host)
page = nb.get_nth_page(nb.get_n_pages() - 1)
v, label = page.get_children()[0], nb.get_tab_label(page)
assert v.command[0] == app.SSH_COMMAND, "not run through ssh.expect: %r" % (v.command[0],)
pump(lambda: not label.is_active, "the connection to fail")
settle(0.5)
shown = v.get_text_format(Vte.Format.TEXT) or ""
# Refused or timed out, depending on the machine; ssh starts both the same way.
assert "ssh: connect to host 127.0.0.1 port 1" in shown, "the tab shows %r" % shown.strip()
print("OK")
"""


@pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"),
    reason="needs a display for a real terminal",
)
def test_a_failed_connection_shows_why_in_its_tab_against_real_gtk():
    """A host with a stored password that could not connect left an empty tab: ssh.expect
    kept ssh's error off the screen, and no pattern of its own matched it (#212). The
    same host with no password runs ssh directly, which always showed it."""
    pytest.importorskip("gi", reason="PyGObject not available")
    for program in ("ssh", "expect"):
        if shutil.which(program) is None:
            pytest.skip(f"needs {program}")
    result = subprocess.run(
        [sys.executable, "-c", _FAILED_CONNECTION_SCRIPT],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        timeout=120,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert "OK" in result.stdout


# A first connection to a host with a stored password (#214). ssh.expect runs a fake ssh
# that asks about the host's key, prints a banner and asks for the password, turning echo
# off first as ssh does. It reports what it was given rather than the password.
_FAKE_FIRST_CONNECTION = r"""#!/bin/sh
printf "The authenticity of host 'example.invalid (192.0.2.1)' can't be established.\n"
printf "ED25519 key fingerprint is SHA256:GCMTESTFINGERPRINT.\n"
printf "Are you sure you want to continue connecting (yes/no/[fingerprint])? "
read answer
printf "Warning: Permanently added 'example.invalid' (ED25519) to the list of known hosts.\n"
printf "GCM-TEST banner: authorised use only\n"
stty -echo
printf "me@example.invalid's password: "
read pw
stty echo
printf "\nWelcome (answer %s, password %s)\n" "$answer" \
    "$([ "$pw" = not-a-password ] && echo right || echo wrong)"
"""

_FIRST_CONNECTION_SCRIPT = """
import os, sys, tempfile, time
from pathlib import Path
fake = os.environ["GCM_TEST_FAKE_SSH"]
os.environ["HOME"] = tempfile.mkdtemp(); sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk, Vte
from gnome_connection_manager import app

# The script as it ships, with only its ssh swapped for the fake.
text = Path(app.SSH_COMMAND).read_text()
assert text.count('"/usr/bin/ssh"') == 1
script = Path(tempfile.mkdtemp()) / "ssh.expect"
script.write_text(text.replace('"/usr/bin/ssh"', '"%s"' % fake))
script.chmod(0o755)
app.SSH_COMMAND = str(script)
app.conf.AUTO_CLOSE_TAB = 0

def pump(until, what, limit=30):
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        Gtk.main_iteration_do(False)
        if until():
            return
        time.sleep(0.005)
    raise AssertionError("timed out waiting for " + what)

app.wMain = app.Wmain(application=None)
nb = app.wMain.nbConsole
host = app.Host("Work", "first", "", "example.invalid", "me", "not-a-password")
host.port, host.keep_alive = "22", "0"
app.wMain.addTab(nb, host)
v = nb.get_nth_page(nb.get_n_pages() - 1).get_children()[0]

def whole():
    # Every row, not the visible ones: a tab can be two rows tall on Xvfb.
    text, _ = v.get_text_range_format(Vte.Format.TEXT, 0, 0, v.get_cursor_position()[1], 10000)
    return text or ""

pump(lambda: "Welcome" in whole(), "the login to finish")
shown, at = whole(), 0
for part in (
    "The authenticity of host 'example.invalid (192.0.2.1)' can't be established.",
    "ED25519 key fingerprint is SHA256:GCMTESTFINGERPRINT.",
    "Are you sure you want to continue connecting (yes/no/[fingerprint])? yes",
    "Warning: Permanently added 'example.invalid' (ED25519) to the list of known hosts.",
    "GCM-TEST banner: authorised use only",
    "me@example.invalid's password:",
    "Welcome (answer yes, password right)",
):
    found = shown.find(part, at)
    assert found >= 0, "the tab lacks %r after %r: %r" % (part, shown[:at][-40:], shown)
    at = found + len(part)
assert "not-a-password" not in shown, shown
print("OK")
"""


@pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"),
    reason="needs a display for a real terminal",
)
def test_a_first_connection_shows_the_host_key_it_trusts_against_real_gtk(tmp_path):
    """ssh.expect answers yes to an unknown host key. A host with a stored password showed
    none of it: not the question, the fingerprint, ssh's warning that the key was added,
    nor the banner after it (#214). A host without one runs ssh, which shows it all."""
    pytest.importorskip("gi", reason="PyGObject not available")
    if shutil.which("expect") is None:
        pytest.skip("needs expect")
    fake = tmp_path / "ssh"
    fake.write_text(_FAKE_FIRST_CONNECTION)
    fake.chmod(0o755)
    result = subprocess.run(
        [sys.executable, "-c", _FIRST_CONNECTION_SCRIPT],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "GCM_TEST_FAKE_SSH": str(fake)},
        timeout=120,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert "OK" in result.stdout


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

    tab = _tab_label(app_module, "  web-01  ")  # short: the point is the title reaching it
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
    """Rows numbered the way VTE 0.76 numbers them, each point measured (#179).

    Row numbers count from the start of the session and carry on once the oldest rows
    are dropped, so the rows held start at `first`, not 0. The cursor is reported in
    those numbers. The vertical adjustment is not: it runs from 0 to the number of rows
    held, counted down to the bottom of the screen. get_text_range_format answers every
    row it is asked for, and a row VTE does not hold, on either side, comes back as an
    empty line. `screen` is what get_text_format answers, per format.
    """

    def __init__(self, app_module, held=(), first=0, cursor=None, rows=24, top=None, screen=None):
        self._formats = app_module.Vte.Format
        self.held = list(held)
        self.first = first
        after = first + len(self.held)
        self.cursor = after - 1 if cursor is None else cursor
        self.rows = rows
        # The screen's top row. By default the screen ends with the last row held.
        self.top = max(first, after - rows) if top is None else top
        self.screen = screen or {}
        self.range_calls = []
        self.screen_calls = []
        self.selected = []

    def _name(self, fmt):
        return "html" if fmt == self._formats.HTML else "text"

    def get_cursor_position(self):
        return 0, self.cursor

    def get_row_count(self):
        return self.rows

    def get_vadjustment(self):
        upper = self.top + self.rows - self.first
        return types.SimpleNamespace(get_lower=lambda: 0, get_upper=lambda: upper)

    def get_text_range_format(self, fmt, srow, scol, erow, ecol):
        self.range_calls.append((self._name(fmt), srow, scol, erow, ecol))
        text = "".join(
            (self.held[row - self.first] if 0 <= row - self.first < len(self.held) else "") + "\n"
            for row in range(srow, erow)
        )
        return f"<pre>{text}</pre>" if self._name(fmt) == "html" else text

    def get_text_format(self, fmt):
        self.screen_calls.append(self._name(fmt))
        return self.screen.get(self._name(fmt), "")

    def select_all(self):
        self.selected.append("all")


def test_buffer_terminal_fake_matches_real_vte_api():
    """Guards against the fake offering methods Vte.Terminal lacks."""
    gi = pytest.importorskip("gi", reason="PyGObject not available")
    gi.require_version("Vte", "2.91")
    from gi.repository import Vte

    for name in (
        "get_cursor_position",
        "get_row_count",
        "get_vadjustment",
        "get_text_range_format",
        "get_text_format",
        "select_all",
    ):
        assert hasattr(BufferTerminal, name), f"fake is missing {name}"
        assert hasattr(Vte.Terminal, name), f"Vte.Terminal has no {name}"


# 12000 lines printed into a 10000-row buffer, as measured for #179: rows 0..2001 have
# been dropped, and the prompt is on row 12001, the bottom of a 46-row screen.
OVERFLOWED = [str(n) for n in range(2002, 12001)] + ["$"]


def test_buffer_text_reads_every_row_before_any_is_dropped(app_module):
    terminal = BufferTerminal(app_module, held=["a", "b", "c", ""])

    assert app_module.terminal_buffer_text(terminal) == "a\nb\nc"


def test_buffer_text_keeps_the_newest_rows_once_the_oldest_are_dropped(app_module):
    """The adjustment read 0..10000 with the cursor on row 12001. Taken as row numbers it
    gave 2002 empty lines, then 2002..9999, and nothing newer -- the screen included."""
    terminal = BufferTerminal(app_module, held=OVERFLOWED, first=2002, rows=46)

    assert app_module.terminal_buffer_text(terminal) == "\n".join(OVERFLOWED)


def test_buffer_text_keeps_rows_below_the_cursor(app_module):
    """A program drawing under its prompt -- an agent CLI's footer below its input box --
    leaves the cursor above the last row held."""
    held = OVERFLOWED + ["y", "z", ""]
    terminal = BufferTerminal(app_module, held=held, first=2002, cursor=12001, rows=46)

    assert app_module.terminal_buffer_text(terminal) == "\n".join(held).rstrip()


def test_buffer_text_starts_at_the_oldest_row_with_the_prompt_at_the_top(app_module):
    """After a clear the prompt is on the screen's top row, and the rows held begin up to
    a screen later than the cursor alone allows for. The empty lines VTE answers for the
    rows in between must not open the text."""
    cursor = 2002 + len(OVERFLOWED) - 1
    terminal = BufferTerminal(app_module, held=OVERFLOWED, first=2002, rows=46, top=cursor)

    assert app_module.terminal_buffer_text(terminal) == "\n".join(OVERFLOWED)


def test_buffer_html_reads_exactly_the_rows_the_text_does(app_module):
    """The styled viewer trims empty lines at the end but not at the start, so the HTML
    is read over the rows the text found, not over the window around them."""
    cursor = 2002 + len(OVERFLOWED) - 1
    terminal = BufferTerminal(app_module, held=OVERFLOWED, first=2002, rows=46, top=cursor)

    html = app_module.terminal_buffer_html(terminal)

    assert html == "<pre>" + "\n".join(OVERFLOWED) + "\n</pre>"
    assert terminal.range_calls[-1] == ("html", 2002, 0, 2002 + len(OVERFLOWED), 0)


def test_buffer_text_never_disturbs_the_selection(app_module):
    """select_all()+get_text_selected_full() would work, but destroys the user's selection."""
    terminal = BufferTerminal(app_module, held=OVERFLOWED, first=2002, rows=46)

    app_module.terminal_buffer_text(terminal)
    app_module.terminal_buffer_html(terminal)

    assert terminal.selected == []


def test_buffer_text_falls_back_to_the_visible_screen(app_module):
    """With nothing readable in the range, the visible screen is all there is."""
    terminal = BufferTerminal(app_module, held=["   ", "  ", ""], screen={"text": "ALT-0\nALT-1\n"})

    assert app_module.terminal_buffer_text(terminal) == "ALT-0\nALT-1"


def test_buffer_text_handles_a_tuple_return(app_module):
    """Older VTE returns (text, attrs) from the range call."""
    terminal = BufferTerminal(app_module, held=["x", "y"])
    terminal.get_text_range_format = lambda *a: ("x\ny\n", None)

    assert app_module.terminal_buffer_text(terminal) == "x\ny"


# -- the viewer must not go blank on the alternate screen (#107) -------------
#
# The range used to come back as empty rows on the alternate screen, and these fall
# throughs to the visible screen kept the viewer from going blank. The cause was #179:
# the range was asked for by the adjustment's numbers, which miss every row of the
# alternate screen. Asked for by the cursor's, the range holds that screen (the real-VTE
# test below). The fall through stays for a range with nothing readable in it.

# What VTE hands back for a range of empty rows: markup around nothing but newlines.
BLANK_ROWS_HTML = "<pre>\n\n\n\n</pre>"
ALT_SCREEN_HTML = '<pre><font color="#00C000">ALT row</font>\n</pre>'


def test_buffer_html_falls_back_to_the_visible_screen(app_module):
    """Its text twin falls through here too; without it the viewer rendered a
    full-screen application as a page of empty rows."""
    terminal = BufferTerminal(app_module, held=["", "", "", ""], screen={"html": ALT_SCREEN_HTML})

    assert app_module.terminal_buffer_html(terminal) == ALT_SCREEN_HTML


def test_buffer_html_keeps_the_range_when_it_carries_text(app_module):
    """The scrollback is the point of the viewer; the screen is only the fallback."""
    terminal = BufferTerminal(
        app_module, held=["scrollback line"], screen={"html": ALT_SCREEN_HTML}
    )

    assert app_module.terminal_buffer_html(terminal) == "<pre>scrollback line\n</pre>"
    assert terminal.screen_calls == [], "the screen must not be read when rows exist"


def test_buffer_html_and_text_agree_when_the_range_is_blank(app_module):
    """The two exports promise the same rows and differ only in attributes."""
    terminal = BufferTerminal(
        app_module,
        held=["", "", "", ""],
        screen={"html": ALT_SCREEN_HTML, "text": "ALT row\n"},
    )

    html = app_module.terminal_buffer_html(terminal)
    runs = app_module.vtehtml.parse_vte_html(html)

    assert app_module.vtehtml.plain_text(runs).strip() == (
        app_module.terminal_buffer_text(terminal).strip()
    )


def test_buffer_html_returns_none_when_nothing_has_text(app_module):
    """A genuinely empty terminal must still let the caller fall back to plain text."""
    terminal = BufferTerminal(app_module, held=["", "", "", ""], screen={"html": ""})

    assert app_module.terminal_buffer_html(terminal) is None


def test_buffer_html_handles_a_tuple_return(app_module):
    """Older VTE returns (text, attrs) from the range call."""
    terminal = BufferTerminal(app_module, held=["x"])
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


# The in-process tests describe how VTE numbers rows; this checks VTE still does. A
# 100-row buffer overflowed three times over, then the two layouts that leave the
# cursor short of the bottom of the screen (#179). What VTE holds is read the way Copy
# All reads it, which is exact and which the viewer must not use: it takes the selection.
_OVERFLOW_SCRIPT = """
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(); sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk, GLib, Vte
from gnome_connection_manager import app

term = Vte.Terminal(); term.set_scrollback_lines(100); term.set_size(80, 24)
win = Gtk.Window(); win.set_default_size(700, 400); win.add(term); win.show_all()

def pump(ms=400):
    loop = GLib.MainLoop(); GLib.timeout_add(ms, lambda: (loop.quit(), False)[1]); loop.run()

def check(label):
    term.select_all()
    held = term.get_text_selected_full(Vte.Format.TEXT)[0].lstrip("\\n").rstrip()
    term.unselect_all()
    text = app.terminal_buffer_text(term)
    assert text == held, (label, text[:30], text[-30:], held[:30], held[-30:])
    html = app.terminal_buffer_html(term)
    styled = app.vtehtml.plain_text(app.vtehtml.parse_vte_html(html))
    assert styled.rstrip() == held, (label, styled[:30], held[:30])
    viewer = app.BufferViewer(None, term, label)
    viewer.show_all()
    for _ in range(50): Gtk.main_iteration_do(False)
    shown = viewer.get_all_text()
    viewer.destroy()
    assert shown.rstrip() == held, (label, shown[:30], held[:30])
    return held

pump(500)
term.feed("".join("%d\\r\\n" % n for n in range(1, 301)).encode())
pump()
held = check("overflowed")
assert held.split("\\n")[0] != "1" and held.endswith("300"), (held[:30], held[-30:])
term.feed(b"prompt\\r\\ny\\r\\nz\\r\\n\\x1b[3A")
pump()
assert check("rows below the cursor").endswith("z")
term.feed(b"\\x1b[H\\x1b[2Jtop")
pump()
assert check("prompt at the top").endswith("top")

win.destroy()
print("OK")
"""


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="needs a display for a real window")
def test_buffer_text_and_viewer_hold_what_vte_holds_after_overflow_against_real_vte():
    """View buffer and Save buffer lost the newest rows once the scrollback overflowed."""
    pytest.importorskip("gi", reason="PyGObject not available")
    result = subprocess.run(
        [sys.executable, "-c", _OVERFLOW_SCRIPT],
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
    # In no notebook, so the session-ended mark (#208) has no tab to mark.
    terminal.get_parent = lambda: None
    tab = EndedTab()

    wmain.on_terminal_child_exited(terminal, tab, 768)

    assert terminal.log.entries == ["last line"]
    # The status VTE reported, which Close console decides on (#210): here `exit 3`.
    assert tab.statuses == [768]


def test_child_exit_is_wired_to_the_flushing_handler(app_module):
    """Connected through a lambda, since the handler needs the tab as well as the
    terminal, so the name check the other signals use cannot see it. The lambda must
    pass on the status the signal carries: dropping it is what left Close console
    asking the terminal for one, which VTE 2.91 cannot answer (#210)."""
    source = Path(app_module.__file__).read_text()
    body = source.split("def addTab", 1)[1].split("\n    def ", 1)[0]

    wiring = re.search(
        r'"child-exited",\s*lambda\s+\w+,\s*(\w+):\s*self\.on_terminal_child_exited\(v, tab, (\w+)\)',
        body,
    )
    assert wiring, "child-exited is not connected to on_terminal_child_exited with its status"
    assert wiring.group(1) == wiring.group(2), wiring.group(0)


def export_then_import(monkeypatch, tmp_path, app_module, exported_hosts, mangle=None):
    """Export `exported_hosts`, optionally edit the file, then import it back.

    Returns the hosts that landed in `groups`. Mirrors the round trip in
    test_importar_servidores_loads_hosts; `mangle` takes and returns the file text.
    """
    filename = tmp_path / "hosts.ini"
    monkeypatch.setattr(app_module, "encrypt", lambda _pwd, value: value)
    monkeypatch.setattr(app_module, "decrypt", lambda _pwd, value: value)
    monkeypatch.setattr(app_module, "show_open_dialog", lambda **_kwargs: str(filename))
    monkeypatch.setattr(app_module, "inputbox", lambda *_args, **_kwargs: "secretpw")
    monkeypatch.setattr(
        app_module, "msgconfirm", lambda *_args, **_kwargs: app_module.Gtk.ResponseType.OK
    )
    messages: list[str] = []
    monkeypatch.setattr(app_module, "msgbox", lambda text: messages.append(text))

    exporter = object.__new__(app_module.Wmain)
    exporter.window = object()
    exporter.wMain = object()
    monkeypatch.setattr(app_module, "groups", {"ops/prod": list(exported_hosts)})
    exporter.on_exportar_servidores1_activate(None)

    if mangle is not None:
        filename.write_text(mangle(filename.read_text()))

    importer = object.__new__(app_module.Wmain)
    importer.window = object()
    importer.wMain = object()
    importer.updateTree = lambda: None
    monkeypatch.setattr(app_module, "groups", {})
    importer.on_importar_servidores1_activate(None)

    assert messages == []
    return [host for hosts in app_module.groups.values() for host in hosts]


def test_an_exported_host_keeps_its_id_through_an_import(monkeypatch, tmp_path, app_module):
    host = make_host(app_module)

    imported = export_then_import(monkeypatch, tmp_path, app_module, [host])

    assert [h.id for h in imported] == [host.id]


def test_importing_a_file_with_a_repeated_id_separates_them(monkeypatch, tmp_path, app_module):
    """An export can be hand-edited or merged; nothing upstream would notice the repeat."""
    first, second = make_host(app_module), make_host(app_module)
    second.name = "switch"

    imported = export_then_import(
        monkeypatch,
        tmp_path,
        app_module,
        [first, second],
        mangle=lambda text: text.replace(f"id = {second.id}", f"id = {first.id}"),
    )

    assert len(imported) == 2
    assert len({h.id for h in imported}) == 2


def test_importing_a_hand_merged_export_keeps_every_host(monkeypatch, tmp_path, app_module):
    """Two exports pasted together repeat every section. Strict parsing refused that, and
    the import said only that the file was invalid (#161)."""
    first, second = make_host(app_module), make_host(app_module)
    second.name = "switch"

    imported = export_then_import(
        monkeypatch,
        tmp_path,
        app_module,
        [first, second],
        mangle=lambda text: text + "\n" + text.replace("name = switch", "name = firewall"),
    )

    assert sorted(h.name for h in imported) == sorted([first.name, "firewall", "switch"])


def test_a_folder_outlives_its_last_host(monkeypatch, app_module):
    """ADR-0002: folders are records, not a side effect of some host's path."""
    kept, moved = hosts_named(app_module, "ops/web", "ops/old/db")
    monkeypatch.setattr(app_module, "groups", {"ops": [kept], "ops/old": [moved]})
    app_module.sync_folders()

    app_module.groups["ops/old"].remove(moved)  # what on_btnDel_clicked does to a host
    app_module.sync_folders()

    tree = app_module.folders
    assert sorted(tree.path_for(folder_id) for folder_id in tree.folders) == ["ops", "ops/old"]
    assert list(app_module.groups) == ["ops"]


def test_an_export_carries_the_folder_tree_through_an_import(monkeypatch, tmp_path, app_module):
    host = make_host(app_module)

    imported = export_then_import(monkeypatch, tmp_path, app_module, [host])

    assert host.folder
    assert imported[0].folder == host.folder
    assert app_module.folders.path_for(host.folder) == host.group


def test_importing_an_export_from_before_adr_0002_builds_the_tree(
    monkeypatch, tmp_path, app_module
):
    def strip_folders(text):
        kept, in_folder = [], False
        for line in text.splitlines():
            if line.startswith("["):
                in_folder = line.startswith("[folder ")
            if not in_folder and not line.startswith("folder ="):
                kept.append(line)
        return "\n".join(kept) + "\n"

    host = make_host(app_module)
    imported = export_then_import(monkeypatch, tmp_path, app_module, [host], mangle=strip_folders)
    assert app_module.folders.folders == {}

    app_module.sync_folders()

    assert app_module.folders.path_for(imported[0].folder) == host.group


def drawn_tree(app_module, monkeypatch, *specs):
    """A Wmain with `specs` (``group/name``) drawn, plus inputbox and msgbox captured."""
    made = hosts_named(app_module, *specs)
    groups: dict = {}
    for host in made:
        groups.setdefault(host.group, []).append(host)
    wmain = make_wmain_for_tree(app_module, monkeypatch, groups)
    wmain.updateTree()
    wmain.said = []
    monkeypatch.setattr(app_module, "msgbox", wmain.said.append)
    return wmain, made


def answer(monkeypatch, app_module, text):
    asked: list = []
    monkeypatch.setattr(
        app_module,
        "inputbox",
        lambda title, prompt, default="", **_kw: asked.append(default) or text,
    )
    return asked


def paths(app_module):
    return sorted(app_module.folders.path_for(f) for f in app_module.folders.folders)


@pytest.mark.parametrize(
    ("select", "expected"),
    [("prod", "ops/prod/staging"), ("web", "ops/prod/staging"), (None, "staging")],
)
def test_new_folder_goes_in_the_selected_folder_or_a_hosts_folder_or_the_top(
    monkeypatch, app_module, select, expected
):
    wmain, _made = drawn_tree(app_module, monkeypatch, "ops/prod/web")
    wmain.treeServers.selected = wmain.treeModel.find(select)[1] if select else None
    answer(monkeypatch, app_module, " staging ")

    wmain.new_folder()

    assert expected in paths(app_module)
    assert wmain.treeServers.cursor == wmain.treeModel.find("staging")[0]
    assert wmain.writes == 1


@pytest.mark.parametrize(("typed", "said"), [("a/b", "cannot contain /"), ("prod", "[prod]")])
def test_new_folder_explains_a_refused_name_and_changes_nothing(
    monkeypatch, app_module, typed, said
):
    wmain, _made = drawn_tree(app_module, monkeypatch, "ops/prod/web")
    wmain.treeServers.selected = wmain.treeModel.find("ops")[1]
    before = paths(app_module)
    answer(monkeypatch, app_module, typed)

    wmain.new_folder()

    assert paths(app_module) == before
    assert len(wmain.said) == 1 and said in wmain.said[0]
    assert wmain.writes == 0


@pytest.mark.parametrize("typed", [None, "", "   "])
def test_new_folder_cancelled_or_blank_does_nothing(monkeypatch, app_module, typed):
    wmain, _made = drawn_tree(app_module, monkeypatch, "ops/web")
    answer(monkeypatch, app_module, typed)

    wmain.new_folder()

    assert paths(app_module) == ["ops"]
    assert wmain.said == [] and wmain.writes == 0


def test_rename_moves_every_host_below_the_folder_with_it(monkeypatch, app_module):
    wmain, (web, db) = drawn_tree(app_module, monkeypatch, "ops/web", "ops/prod/db")
    wmain.treeServers.selected = wmain.treeModel.find("ops")[1]
    offered = answer(monkeypatch, app_module, "operations")

    wmain.rename_selected_folder()

    assert offered == ["ops"]
    assert (web.group, db.group) == ("operations", "operations/prod")
    assert sorted(app_module.groups) == ["operations", "operations/prod"]
    assert wmain.treeServers.cursor == wmain.treeModel.find("operations")[0]


def test_rename_refused_and_rename_of_a_host_row_do_nothing(monkeypatch, app_module):
    wmain, (web, _db) = drawn_tree(app_module, monkeypatch, "ops/web", "home/nas")
    wmain.treeServers.selected = wmain.treeModel.find("ops")[1]
    answer(monkeypatch, app_module, "home")

    wmain.rename_selected_folder()
    wmain.treeServers.selected = wmain.treeModel.find("web")[1]
    answer(monkeypatch, app_module, "renamed")
    wmain.rename_selected_folder()

    assert paths(app_module) == ["home", "ops"]
    assert len(wmain.said) == 1 and "[home]" in wmain.said[0]
    assert web.group == "ops"


def test_f2_renames_the_selected_folder(monkeypatch, app_module):
    wmain, _made = drawn_tree(app_module, monkeypatch, "ops/web")
    wmain.treeServers.selected = wmain.treeModel.find("ops")[1]
    answer(monkeypatch, app_module, "operations")
    monkeypatch.setattr(app_module.Gdk, "KEY_Delete", 1, raising=False)
    monkeypatch.setattr(app_module.Gdk, "KEY_F2", 2, raising=False)

    handled = wmain.on_treeServers_key_press(None, types.SimpleNamespace(keyval=2))

    assert handled is True
    assert paths(app_module) == ["operations"]


DROP = types.SimpleNamespace(
    BEFORE="before", AFTER="after", INTO_OR_BEFORE="into-before", INTO_OR_AFTER="into-after"
)


def aim(wmain, name, position):
    """Point the fake drag at the row called `name`, or at blank space for None."""
    wmain.treeServers.dest = None if name is None else (wmain.treeModel.find(name)[0], position)


@pytest.mark.parametrize(
    ("row", "position", "lands"),
    [
        ("prod", DROP.INTO_OR_BEFORE, ("ops/prod", None, False)),
        ("prod", DROP.INTO_OR_AFTER, ("ops/prod", None, False)),
        ("prod", DROP.BEFORE, ("ops", "prod", False)),
        ("prod", DROP.AFTER, ("ops", "prod", True)),
        ("ops", DROP.AFTER, ("", "ops", True)),
        ("web", DROP.BEFORE, ("ops/prod", "web", False)),
        ("web", DROP.AFTER, ("ops/prod", "web", True)),
        ("web", DROP.INTO_OR_AFTER, ("ops/prod", None, False)),
        (None, None, ("", None, False)),
    ],
)
def test_drop_target(monkeypatch, app_module, row, position, lands):
    """The edge of a row is a place beside it; the middle is its folder, or the host's."""
    monkeypatch.setattr(app_module.Gtk, "TreeViewDropPosition", DROP)
    wmain, _made = drawn_tree(app_module, monkeypatch, "ops/prod/web")
    aim(wmain, row, position)

    folder, beside, after = wmain.drop_target(0, 0)

    assert (app_module.folders.path_for(folder), beside and beside.name, after) == lands


def folder_id(app_module, path):
    return next(f for f in app_module.folders.folders if app_module.folders.path_for(f) == path)


def child_named(app_module, folder, name):
    """The host or folder called `name` directly inside `folder`, as the tree has it."""
    return next(c for c in app_module.folder_contents()[folder] if c.name == name)


@pytest.mark.parametrize(
    ("kind", "subject", "target", "refused"),
    [
        ("host", "web", ("ops/prod", None, False), "already there"),
        ("host", "web", ("ops/prod", "web", False), "already there"),
        ("host", "web", ("ops/prod", "db", True), "already there"),
        ("host", "web", ("ops/prod", "db", False), None),
        ("host", "web", ("", None, False), "hosts live in folders"),
        ("host", "web", ("home", None, False), "taken"),
        ("host", "web", ("ops", None, False), None),
        ("folder", "ops/prod", ("ops/prod", None, False), "cycle"),
        ("folder", "ops", ("ops/prod", None, False), "cycle"),
        ("folder", "ops", ("ops", "prod", False), "cycle"),
        ("folder", "ops/prod", ("ops", None, False), "already there"),
        ("folder", "home", ("ops/prod", None, False), None),
        ("folder", "home", ("ops/prod", "db", False), None),
        ("folder", "ops/prod", ("", None, False), None),
        ("folder", "home", ("", "ops", True), None),
        ("folder", "home", ("", "ops", False), "already there"),
    ],
)
def test_drop_refusal(monkeypatch, app_module, kind, subject, target, refused):
    """A spot that would leave everything where it is counts as already there."""
    wmain, made = drawn_tree(app_module, monkeypatch, "ops/prod/web", "ops/prod/db", "home/web")
    path, beside, after = target
    folder = folder_id(app_module, path) if path else app_module.ROOT_FOLDER
    spot = (folder, beside and child_named(app_module, folder, beside), after)
    item = ("host", made[0]) if kind == "host" else ("folder", folder_id(app_module, subject))

    assert wmain.drop_refusal(item, spot) == refused


class DragData:
    def __init__(self, payload=b""):
        self.payload = payload
        self.sent = None

    def get_target(self):
        return "GCM_TREE_ROW"

    def set(self, target, fmt, payload):
        self.sent = (target, fmt, payload)

    def get_data(self):
        return self.payload


def test_drag_data_names_the_dragged_row_by_id(monkeypatch, app_module):
    wmain, (web,) = drawn_tree(app_module, monkeypatch, "ops/web")
    data = DragData()

    wmain._drag_source_path = wmain.treeModel.find("web")[0]
    wmain.on_treeServers_drag_data_get(None, None, data, 0, 0)
    assert data.sent == ("GCM_TREE_ROW", 8, f"host:{web.id}".encode())

    wmain._drag_source_path = wmain.treeModel.find("ops")[0]
    wmain.on_treeServers_drag_data_get(None, None, data, 0, 0)
    assert data.sent[2] == f"folder:{web.folder}".encode()


def test_a_drag_carries_the_pressed_row_not_the_selection(monkeypatch, app_module):
    """Measured with real pointer input: a press on a folder's expander arrow starts a
    drag without selecting the folder, and the selection then held another row."""
    wmain, _made = drawn_tree(app_module, monkeypatch, "ops/prod/db", "home/nas")
    press = types.SimpleNamespace(type=app_module.Gdk.EventType.BUTTON_PRESS, button=1, x=5, y=9)
    wmain.treeServers.selected = wmain.treeModel.find("home")[1]

    wmain.treeServers.pressed = wmain.treeModel.find("prod")[0]
    wmain.on_tvServers_button_press_event(wmain.treeServers, press)
    assert wmain.dragged_tree_item() == ("folder", folder_id(app_module, "ops/prod"))

    wmain.treeServers.pressed = None
    wmain.on_tvServers_button_press_event(wmain.treeServers, press)
    assert wmain.dragged_tree_item() is None


@pytest.mark.parametrize("payload", [b"", b"host:nobody", b"folder:nothing", b"bogus"])
def test_a_drop_naming_nothing_known_is_ignored(monkeypatch, app_module, payload):
    wmain, _made = drawn_tree(app_module, monkeypatch, "ops/web")

    assert wmain.decode_dragged_item(payload) is None


def drag_recorders(monkeypatch, app_module):
    finished: list = []
    statuses: list = []
    monkeypatch.setattr(app_module.Gtk, "TreeViewDropPosition", DROP)
    monkeypatch.setattr(app_module.Gtk, "drag_finish", lambda *args: finished.append(args))
    monkeypatch.setattr(app_module.Gdk, "drag_status", lambda *args: statuses.append(args))
    return finished, statuses


def test_dropping_a_host_on_a_folder_refiles_it(monkeypatch, app_module):
    finished, _statuses = drag_recorders(monkeypatch, app_module)
    wmain, (web, _nas) = drawn_tree(app_module, monkeypatch, "ops/web", "home/nas")
    aim(wmain, "home", DROP.INTO_OR_BEFORE)

    wmain.on_treeServers_drag_data_received(
        wmain.treeServers, "ctx", 0, 0, DragData(f"host:{web.id}".encode()), 0, 7
    )

    assert web.group == "home"
    assert wmain.treeModel.shape() == [("home", ["nas", "web"]), ("ops", [])]
    assert finished == [("ctx", True, False, 7)]
    assert wmain.treeServers.stopped == ["drag-data-received"]
    assert wmain.writes == 1


def test_dropping_a_folder_moves_it_with_its_hosts(monkeypatch, app_module):
    finished, _statuses = drag_recorders(monkeypatch, app_module)
    wmain, (db, _nas) = drawn_tree(app_module, monkeypatch, "ops/prod/db", "home/nas")
    aim(wmain, "home", DROP.INTO_OR_AFTER)

    wmain.on_treeServers_drag_data_received(
        wmain.treeServers,
        "ctx",
        0,
        0,
        DragData(f"folder:{folder_id(app_module, 'ops/prod')}".encode()),
        0,
        7,
    )

    assert db.group == "home/prod"
    assert finished == [("ctx", True, False, 7)]


def test_a_refused_drop_changes_nothing_and_reports_failure(monkeypatch, app_module):
    finished, _statuses = drag_recorders(monkeypatch, app_module)
    wmain, _made = drawn_tree(app_module, monkeypatch, "ops/prod/db")
    aim(wmain, "prod", DROP.INTO_OR_BEFORE)
    ops = folder_id(app_module, "ops")

    wmain.on_treeServers_drag_data_received(
        wmain.treeServers, "ctx", 0, 0, DragData(f"folder:{ops}".encode()), 0, 7
    )

    assert paths(app_module) == ["ops", "ops/prod"]
    assert finished == [("ctx", False, False, 7)]
    assert wmain.writes == 0


def test_drag_motion_refuses_a_spot_itself_and_leaves_a_good_one_to_gtk(monkeypatch, app_module):
    _finished, statuses = drag_recorders(monkeypatch, app_module)
    wmain, _made = drawn_tree(app_module, monkeypatch, "ops/prod/db", "home/nas")
    wmain._drag_source_path = wmain.treeModel.find("ops")[0]

    aim(wmain, "prod", DROP.INTO_OR_BEFORE)
    assert wmain.on_treeServers_drag_motion(wmain.treeServers, "ctx", 0, 0, 7) is True
    assert statuses == [("ctx", 0, 7)]
    assert wmain.treeServers.dest_row == (None, DROP.BEFORE)

    aim(wmain, "home", DROP.INTO_OR_BEFORE)
    assert wmain.on_treeServers_drag_motion(wmain.treeServers, "ctx", 0, 0, 8) is False
    assert statuses == [("ctx", 0, 7)]


def drop_here(wmain, payload):
    """Deliver a drop of `payload` wherever aim() last pointed the fake drag."""
    wmain.on_treeServers_drag_data_received(
        wmain.treeServers, "ctx", 0, 0, DragData(payload.encode()), 0, 7
    )


def test_dropping_on_the_edge_of_a_row_puts_the_host_there(monkeypatch, app_module):
    finished, _statuses = drag_recorders(monkeypatch, app_module)
    wmain, (a, b, c) = drawn_tree(app_module, monkeypatch, "ops/a", "ops/b", "ops/c")
    aim(wmain, "a", DROP.BEFORE)

    drop_here(wmain, f"host:{c.id}")

    assert wmain.treeModel.shape() == [("ops", ["c", "a", "b"])]
    assert menu_shape(wmain.menuServers) == [("ops", ["c", "a", "b"])]
    assert [h.position for h in (a, b, c)] == [1, 2, 0]
    assert finished == [("ctx", True, False, 7)]
    assert wmain.writes == 1


def test_a_folder_can_be_placed_among_hosts(monkeypatch, app_module):
    drag_recorders(monkeypatch, app_module)
    wmain, _made = drawn_tree(app_module, monkeypatch, "ops/a", "ops/b", "ops/prod/db")
    aim(wmain, "a", DROP.AFTER)

    drop_here(wmain, f"folder:{folder_id(app_module, 'ops/prod')}")

    assert wmain.treeModel.shape() == [("ops", ["a", ("prod", ["db"]), "b"])]


@pytest.mark.parametrize(("arranged", "drawn"), [(False, ["a", "y", "z"]), (True, ["z", "y", "a"])])
def test_a_host_dropped_on_a_folder_goes_to_the_end_only_of_an_arranged_one(
    monkeypatch, app_module, arranged, drawn
):
    """Dropping on a folder is not arranging it: one in name order stays in name order."""
    drag_recorders(monkeypatch, app_module)
    wmain, (z, y, a) = drawn_tree(app_module, monkeypatch, "ops/z", "ops/y", "home/a")
    if arranged:
        z.position, y.position = 0, 1
        wmain.updateTree()
    aim(wmain, "ops", DROP.INTO_OR_AFTER)

    drop_here(wmain, f"host:{a.id}")

    assert wmain.treeModel.shape() == [("home", []), ("ops", drawn)]
    assert a.position == (2 if arranged else None)


def test_the_folder_a_host_leaves_closes_the_gap_or_goes_back_to_name_order(
    monkeypatch, app_module
):
    drag_recorders(monkeypatch, app_module)
    wmain, (a, b, c, _nas) = drawn_tree(
        app_module, monkeypatch, "ops/a", "ops/b", "ops/c", "home/nas"
    )
    c.position, a.position, b.position = 0, 1, 2
    wmain.updateTree()
    aim(wmain, "home", DROP.INTO_OR_BEFORE)

    drop_here(wmain, f"host:{a.id}")
    assert (c.position, b.position) == (0, 1)

    drop_here(wmain, f"host:{c.id}")
    assert b.position is None


def test_collapsed_folders_stay_collapsed_through_a_reorder(monkeypatch, app_module):
    """Collapse state is keyed by folder id, so moving rows around it changes nothing."""
    drag_recorders(monkeypatch, app_module)
    wmain, _made = drawn_tree(app_module, monkeypatch, "ops/prod/db", "ops/web", "home/nas")
    wmain.treeServers.collapse_row(wmain.treeModel.find("prod")[0])
    wmain.treeServers.collapse_row(wmain.treeModel.find("home")[0])
    aim(wmain, "ops", DROP.AFTER)

    drop_here(wmain, f"folder:{folder_id(app_module, 'home')}")

    assert [node.row[0] for node in wmain.treeModel.roots] == ["ops", "home"]
    collapsed = {wmain.treeModel.get_iter(p).row[0] for p in wmain.treeServers.collapsed}
    assert collapsed == {"prod", "home"}


@pytest.mark.parametrize("selected", ["ops", "y"])
def test_sort_by_name_hands_one_folder_back_to_name_order(monkeypatch, app_module, selected):
    """The selected folder, or a selected host's: its subfolders keep their own order."""
    wmain, (z, y, x, w) = drawn_tree(
        app_module, monkeypatch, "ops/z", "ops/y", "ops/sub/x", "ops/sub/w"
    )
    z.position, y.position = 0, 1
    app_module.folders.folders[folder_id(app_module, "ops/sub")].position = 2
    x.position, w.position = 0, 1
    wmain.updateTree()
    assert wmain.treeModel.shape() == [("ops", ["z", "y", ("sub", ["x", "w"])])]
    wmain.treeServers.selected = wmain.treeModel.find(selected)[1]

    wmain.sort_selected_folder()
    wmain.sort_selected_folder()

    assert wmain.treeModel.shape() == [("ops", [("sub", ["x", "w"]), "y", "z"])]
    assert wmain.writes == 1


@pytest.mark.parametrize(
    ("arranged", "drawn"),
    [
        (True, ["b", "b (copy)", "a", "b (backup)"]),
        (False, ["a", "b", "b (backup)", "b (copy)"]),
    ],
)
def test_a_duplicate_sits_after_its_original_only_in_an_arranged_folder(
    monkeypatch, app_module, arranged, drawn
):
    """In name order the copy sorts in like any new host -- here after `b (backup)`,
    which placing it beside its original would not have respected."""
    wmain, (a, b, backup) = drawn_tree(app_module, monkeypatch, "ops/a", "ops/b", "ops/b (backup)")
    if arranged:
        b.position, a.position, backup.position = 0, 1, 2
        wmain.updateTree()
    wmain.treeServers.selected = wmain.treeModel.find("b")[1]
    wmain._context_tree_path = None
    wmain.get_group = lambda _iter: "ops"

    wmain.duplicate_selected_host()

    assert wmain.treeModel.shape() == [("ops", drawn)]


def test_collapsed_folders_are_recorded_and_restored_by_id(monkeypatch, app_module):
    wmain, _made = drawn_tree(app_module, monkeypatch, "ops/prod/db", "home/nas")
    wmain.treeServers.collapse_row(wmain.treeModel.find("prod")[0])
    wmain.treeServers.collapse_row(wmain.treeModel.find("home")[0])
    recorded = wmain.get_collapsed_folder_ids()
    assert sorted(recorded) == sorted(
        [folder_id(app_module, "ops/prod"), folder_id(app_module, "home")]
    )

    # A new folder sorts ahead of both, so every row position shifts. Ids do not.
    app_module.folders.add(app_module.ROOT_FOLDER, "archive")
    wmain.updateTree()

    collapsed = {wmain.treeModel.get_iter(p).row[0] for p in wmain.treeServers.collapsed}
    assert collapsed == {"prod", "home"}


def test_the_first_start_after_upgrading_restores_row_positions(monkeypatch, app_module):
    monkeypatch.setattr(
        app_module.Gtk,
        "TreePath",
        types.SimpleNamespace(new_from_string=lambda s: FakeTreePath(int(i) for i in s.split(":"))),
    )
    monkeypatch.setattr(app_module.conf, "COLLAPSED_FOLDER_IDS", None)
    monkeypatch.setattr(app_module.conf, "COLLAPSED_FOLDERS", "1")
    made = hosts_named(app_module, "home/nas", "ops/web")
    wmain = make_wmain_for_tree(app_module, monkeypatch, {"home": [made[0]], "ops": [made[1]]})

    wmain.updateTree()

    assert wmain.treeServers.collapsed == {(1,)}
    assert app_module.conf.COLLAPSED_FOLDERS is None


def test_folder_fakes_offer_only_what_gtk_has():
    """The fakes above stand in for real widgets; a method the real class lacks would
    pass here and fail in the application (#30, #41)."""
    gi = pytest.importorskip("gi", reason="PyGObject not available")
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    for name in ("clear", "append", "get_value", "get_iter_first", "get_iter", "foreach"):
        assert hasattr(RecordingTreeStore, name) and hasattr(Gtk.TreeStore, name), name
    for name in (
        "get_selection",
        "get_dest_row_at_pos",
        "get_path_at_pos",
        "set_drag_dest_row",
        "stop_emission_by_name",
        "expand_all",
        "collapse_row",
        "row_expanded",
        "expand_to_path",
        "set_cursor",
    ):
        assert hasattr(FolderTreeView, name) and hasattr(Gtk.TreeView, name), name
    for name in ("get_selected", "unselect_all"):
        assert hasattr(Gtk.TreeSelection, name), name
    for name in ("get_target", "set", "get_data"):
        assert hasattr(DragData, name) and hasattr(Gtk.SelectionData, name), name
    assert hasattr(Gtk.TreePath, "copy")
