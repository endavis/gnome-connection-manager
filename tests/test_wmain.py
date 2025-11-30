"""Tests for selected Wmain helpers that depend on tree/host interactions."""

from __future__ import annotations

import types
import configparser


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
    wmain.menuCustomCommands = DummyMenu()
    created_items = []

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

    assert len(created_items) == 2
    assert len(wmain.popupMenu.mnuCommands.children) == 1
    item = wmain.popupMenu.mnuCommands.children[0]
    assert item.shortcut == "ALT+R"
    assert item.action_name == "app.custom-command"
    assert len(wmain.menuCustomCommands.children) == 1


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


class ToggleStub:
    def __init__(self):
        self.value = None

    def set_active(self, state):
        self.value = state


class ToolbarStub:
    def __init__(self):
        self.visible = False

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False


class ClipboardStub:
    def __init__(self):
        self.text = None
        self.length = None
        self.stored = False

    def set_text(self, text, length):
        self.text = text
        self.length = length

    def store(self):
        self.stored = True


class ClipboardTerminal:
    def __init__(self):
        self.copied = []
        self.pasted = 0
        self.selected = []

    def copy_clipboard_format(self, fmt):
        self.copied.append(fmt)

    def paste_clipboard(self):
        self.pasted += 1

    def select_all(self):
        self.selected.append("all")

    def select_none(self):
        self.selected.append("none")


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
    toggle = ToggleStub()
    calls = {"toggle": 0}
    wmain.get_widget = lambda name: toggle if name == "show_panel" else None
    wmain._update_toggle_action = lambda name, state: calls.__setitem__("toggle", calls["toggle"] + 1)
    monkeypatch.setattr(app_module.GLib, "timeout_add", lambda delay, func: func())
    app_module.conf.SHOW_PANEL = False

    wmain.set_panel_visible(True)

    assert pane.positions[-1] == 30
    assert toggle.value is True
    assert app_module.conf.SHOW_PANEL is True
    assert calls["toggle"] == 1


def test_set_panel_visible_false_saves_position(monkeypatch, app_module):
    wmain = object.__new__(app_module.Wmain)
    pane = PaneStub(position=120)
    wmain.hpMain = pane
    toggle = ToggleStub()
    wmain.get_widget = lambda name: toggle if name == "show_panel" else None
    wmain._update_toggle_action = lambda *args: None
    monkeypatch.setattr(app_module.GLib, "timeout_add", lambda delay, func: func())
    app_module.conf.SHOW_PANEL = True

    wmain.set_panel_visible(False)

    assert pane.previous_position == 120
    assert pane.positions[-1] == 0
    assert toggle.value is False
    assert app_module.conf.SHOW_PANEL is False


def test_set_toolbar_visible_toggles_widgets(monkeypatch, app_module):
    wmain = object.__new__(app_module.Wmain)
    toolbar = ToolbarStub()
    toggle = ToggleStub()
    calls = {"toggle": 0}
    wmain.get_widget = lambda name: toolbar if name == "toolbar1" else toggle
    wmain._update_toggle_action = lambda *args: calls.__setitem__("toggle", calls["toggle"] + 1)
    app_module.conf.SHOW_TOOLBAR = False

    wmain.set_toolbar_visible(True)

    assert toolbar.visible is True
    assert toggle.value is True
    assert app_module.conf.SHOW_TOOLBAR is True
    assert calls["toggle"] == 1

    wmain.set_toolbar_visible(False)

    assert toolbar.visible is False
    assert toggle.value is False
    assert app_module.conf.SHOW_TOOLBAR is False
    assert calls["toggle"] == 2


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

    wmain.terminal_copy(terminal)
    assert terminal.copied == [app_module.Vte.Format.TEXT]

    wmain.terminal_paste(terminal)
    assert terminal.pasted == 1

    wmain.terminal_copy_paste(terminal)
    assert terminal.copied[-1] == app_module.Vte.Format.TEXT
    assert terminal.pasted == 2

    wmain.terminal_copy_all(terminal)
    assert terminal.selected == ["all", "none"]


def test_terminal_menu_actions_use_active_terminal(app_module):
    wmain = object.__new__(app_module.Wmain)
    terminal = ClipboardTerminal()
    wmain.hpMain = object()
    wmain.find_active_terminal = lambda widget: terminal

    wmain.on_menuCopy_activate(None)
    wmain.on_menuPaste_activate(None)
    wmain.on_menuCopyPaste_activate(None)
    wmain.on_menuSelectAll_activate(None)
    wmain.on_menuCopyAll_activate(None)

    assert terminal.copied.count(app_module.Vte.Format.TEXT) == 3
    assert terminal.pasted == 2
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
