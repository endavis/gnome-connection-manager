"""Tests for selected Wmain helpers that depend on tree/host interactions."""

from __future__ import annotations

import re
import types
import configparser
from pathlib import Path

import pytest


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
    iter_ = model.register("ops/prod/router", host=host if not has_child else None, has_child=has_child)
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
    monkeypatch.setattr(
        app_module.Gtk.Application, "get_default", lambda: None, raising=False
    )
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
    monkeypatch.setattr(
        app_module, "msgconfirm", lambda _text: app_module.Gtk.ResponseType.OK
    )

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
    monkeypatch.setattr(
        app_module, "msgconfirm", lambda _text: app_module.Gtk.ResponseType.OK
    )

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
    fed = {}
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
        self.copied = []
        self.pasted = 0
        self.pasted_text = []
        self.selected = []
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

    def write(self, data: str):
        self.entries.append(data)


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
    assert terminal.log.entries == ["output"]
    assert terminal.last_logged_row == terminal.cursor[1]
    assert terminal.last_logged_col == terminal.cursor[0]


def test_on_contents_changed_uses_format_api(monkeypatch, app_module):
    wmain = object.__new__(app_module.Wmain)
    terminal = LogTerminal("formatted\n")
    monkeypatch.setattr(app_module.Vte, "get_minor_version", lambda: 80, raising=False)

    wmain.on_contents_changed(terminal)

    assert terminal.last_call[0] == "format"
    assert terminal.log.entries == ["formatted"]


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
        app_module, "msgconfirm", lambda text: prompts.append(text) or app_module.Gtk.ResponseType.OK
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


def test_clamp_font_scale_holds_vte_limits(app_module):
    """VTE itself lands 0.1 on 0.25 and 99.0 on 4.0; the clamp mirrors that."""
    assert app_module.clamp_font_scale(0.01) == app_module.FONT_SCALE_MIN
    assert app_module.clamp_font_scale(99.0) == app_module.FONT_SCALE_MAX
    assert app_module.clamp_font_scale(1.0) == 1.0


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
    assert terminal.font_scale == app_module.FONT_SCALE_MAX

    for _ in range(120):
        wmain.terminal_zoom_out(terminal)
    assert terminal.font_scale == app_module.FONT_SCALE_MIN


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
    event = types.SimpleNamespace(
        type=app_module.Gdk.EventType.BUTTON_PRESS, button=3, x=0, y=0
    )

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


def test_bell_does_not_raise_the_urgency_hint_while_the_window_is_active(
    app_module, monkeypatch
):
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


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("router", "router"),
        ("  local  ", "local"),
        ("my   host", "my host"),
        # a title set by whatever runs in the terminal, via OSC 0
        ("../../../../tmp/pwned", "tmp_pwned"),
        ("claude - ~/src/app (3 tools)", "claude - ~_src_app (3 tools)"),
        ('a/b\\c:d*e?f"g<h>i|j', "a_b_c_d_e_f_g_h_i_j"),
        (".hidden", "hidden"),
        ("..", "session"),
        ("", "session"),
        ("   ", "session"),
        # BEL and ESC must not survive into a file someone will later cat
        ("tab\x07\x1b[31mred", "tab_[31mred"),
    ],
)
def test_sanitize_log_name(app_module, title, expected):
    assert app_module.sanitize_log_name(title) == expected


def test_sanitize_log_name_caps_the_length(app_module):
    name = app_module.sanitize_log_name("x" * 500)

    assert name == "x" * app_module.LOG_NAME_MAX


def test_build_log_prefix_keeps_a_traversing_title_inside_the_log_directory(
    tmp_path, app_module
):
    prefix = app_module.build_log_prefix(tmp_path, "../../../../tmp/pwned", "20260823")

    assert prefix is not None
    assert prefix.parent == tmp_path
    assert prefix.name == "tmp_pwned-20260823"


def test_build_log_prefix_refuses_a_path_that_escapes(tmp_path, app_module, monkeypatch):
    """The containment check must hold even if sanitising ever lets something through."""
    monkeypatch.setattr(app_module, "sanitize_log_name", lambda title: title)

    assert app_module.build_log_prefix(tmp_path, "../escaped", "20260823") is None


def test_build_log_prefix_expands_a_user_relative_log_dir(app_module, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))

    prefix = app_module.build_log_prefix("~/logs", "router", "20260823")

    assert prefix == tmp_path / "logs" / "router-20260823"


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
    titles = []
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
        app_module.Gtk, "MenuBar",
        types.SimpleNamespace(new_from_model=lambda model: menubar_widget), raising=False,
    )
    monkeypatch.setattr(app_module.Gtk, "MenuItem", MenuItemStubGtk, raising=False)
    monkeypatch.setattr(
        app_module.Gtk.Application, "get_default",
        lambda: types.SimpleNamespace(get_menubar=lambda: object()), raising=False,
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
