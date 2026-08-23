"""Tests for GcmApplication action wrappers that don't require GTK windows."""

from __future__ import annotations

import inspect
import re
import types
from pathlib import Path


class TerminalStub:
    def __init__(self):
        self.copied = 0
        self.pasted = 0


class ControllerStub:
    def __init__(self):
        self.calls: list[tuple[str, object | None]] = []
        self.terminal = TerminalStub()

    def on_btnCluster_clicked(self, arg):
        self.calls.append(("cluster", arg))

    def on_importar_servidores1_activate(self, arg):
        self.calls.append(("import", arg))

    def on_exportar_servidores1_activate(self, arg):
        self.calls.append(("export", arg))

    def show_save_buffer(self, terminal):
        self.calls.append(("save-buffer", terminal))

    def get_target_terminal(self):
        self.calls.append(("target", None))
        return self.terminal

    def clear_context_terminal(self):
        self.calls.append(("clear", None))

    # Terminal helpers
    def terminal_copy(self, terminal):
        terminal.copied += 1
        self.calls.append(("copy", terminal))

    def terminal_paste(self, terminal, single_line: bool = False):
        terminal.pasted += 1
        self.calls.append(("paste-single-line" if single_line else "paste", terminal))

    def terminal_copy_paste(self, terminal):
        self.calls.append(("copy-paste", terminal))

    def terminal_select_all(self, terminal):
        self.calls.append(("select-all", terminal))

    def terminal_copy_all(self, terminal):
        self.calls.append(("copy-all", terminal))

    def on_btnHSplit_clicked(self, arg):
        self.calls.append(("split-h", arg))

    def on_btnVSplit_clicked(self, arg):
        self.calls.append(("split-v", arg))

    def on_btnUnsplit_clicked(self, arg):
        self.calls.append(("unsplit", arg))

    def on_btnSearchBack_clicked(self, arg):
        self.calls.append(("search-back", arg))

    def on_btnSearch_clicked(self, arg):
        self.calls.append(("search", arg))

    def on_btnDonate_clicked(self, arg):
        self.calls.append(("donate", arg))

    def trigger_popup_action(self, terminal_code, tab_code):
        self.calls.append(("popup", (terminal_code, tab_code)))


def test_application_cluster_action_invokes_controller(app_module):
    app = app_module.GcmApplication()
    controller = ControllerStub()
    app._controller = controller

    app._on_action_cluster(None, None)

    assert ("cluster", None) in controller.calls


def test_application_import_export_actions_forward_calls(app_module):
    app = app_module.GcmApplication()
    controller = ControllerStub()
    app._controller = controller

    app._on_action_import_hosts(None, None)
    app._on_action_export_hosts(None, None)

    assert ("import", None) in controller.calls
    assert ("export", None) in controller.calls


def test_application_copy_action_uses_target_terminal(app_module):
    app = app_module.GcmApplication()
    controller = ControllerStub()
    app._controller = controller

    app._on_action_copy(None, None)

    assert controller.terminal.copied == 1
    assert ("clear", None) in controller.calls


def test_application_copy_action_no_terminal_still_clears(app_module):
    app = app_module.GcmApplication()

    class EmptyController(ControllerStub):
        def get_target_terminal(self):
            self.calls.append(("target", None))
            return None

    controller = EmptyController()
    app._controller = controller

    app._on_action_copy(None, None)

    assert controller.terminal.copied == 0
    assert controller.calls[-1] == ("clear", None)


def test_application_save_buffer_calls_show_and_clears(app_module):
    app = app_module.GcmApplication()
    controller = ControllerStub()
    app._controller = controller

    app._on_action_save_buffer(None, None)

    assert ("save-buffer", controller.terminal) in controller.calls
    assert controller.calls[-1] == ("clear", None)


def test_application_select_copy_all_actions(app_module):
    app = app_module.GcmApplication()
    controller = ControllerStub()
    app._controller = controller

    app._on_action_select_all(None, None)
    app._on_action_copy_all(None, None)

    assert ("select-all", controller.terminal) in controller.calls
    assert ("copy-all", controller.terminal) in controller.calls


def test_application_split_actions(app_module):
    app = app_module.GcmApplication()
    controller = ControllerStub()
    app._controller = controller

    app._on_action_split_horizontal(None, None)
    app._on_action_split_vertical(None, None)
    app._on_action_unsplit(None, None)

    assert ("split-h", None) in controller.calls
    assert ("split-v", None) in controller.calls
    assert ("unsplit", None) in controller.calls


def test_application_paste_single_line_action_asks_for_a_join(app_module):
    """The menu entry is the only way to reach single-line paste (#21)."""
    app = app_module.GcmApplication()
    controller = ControllerStub()
    app._controller = controller

    app._on_action_paste_single_line(None, None)

    assert ("paste-single-line", controller.terminal) in controller.calls
    assert ("paste", controller.terminal) not in controller.calls


def test_controller_stub_paste_matches_the_real_signature(app_module):
    """A stub that drifts from Wmain.terminal_paste hides real TypeErrors."""
    real = inspect.signature(app_module.Wmain.terminal_paste).parameters
    stub = inspect.signature(ControllerStub.terminal_paste).parameters

    assert list(real) == list(stub)


def test_application_search_and_donate_actions(app_module):
    app = app_module.GcmApplication()
    controller = ControllerStub()
    app._controller = controller

    app._on_action_search_back(None, None)
    app._on_action_search_next(None, None)
    app._on_action_donate(None, None)

    assert ("search-back", None) in controller.calls
    assert ("search", None) in controller.calls
    assert ("donate", None) in controller.calls


def test_application_console_actions(app_module):
    app = app_module.GcmApplication()
    controller = ControllerStub()
    app._controller = controller

    app._on_action_console_reset(None, None)
    app._on_action_console_reset_clear(None, None)
    app._on_action_console_clone(None, None)
    app._on_action_console_rename(None, None)

    assert ("popup", ("RS2", "RS")) in controller.calls
    assert ("popup", ("RC2", "RC")) in controller.calls
    assert ("popup", ("CC2", "CC")) in controller.calls
    assert ("popup", ("R", "R")) in controller.calls


def test_terminal_actions_carry_no_hardcoded_accelerator(app_module, monkeypatch):
    """Their key comes from [shortcuts]; a fixed accelerator would shadow it (#3, #15)."""
    registered = _registered_accels(app_module, monkeypatch)

    for command, action in app_module.TERMINAL_ACTIONS.items():
        assert registered[action] is None, (
            f"app.{action} hardcodes an accelerator, which would shadow "
            f"the configurable '{command}' shortcut"
        )


def test_no_app_accelerator_collides_with_a_different_terminal_command(
    app_module, monkeypatch
):
    """add-host held <Primary>n while [shortcuts] gave CTRL+N to console_reconnect."""
    registered = _registered_accels(app_module, monkeypatch)
    defaults = {key: command for command, _name, key in app_module.SHORTCUT_DEFAULTS}

    for action, accels in registered.items():
        for accel in accels or ():
            gcm_key = (
                accel.replace("<Primary>", "CTRL+")
                .replace("<Shift>", "SHIFT+")
                .replace("<Alt>", "ALT+")
                .upper()
            )
            command = defaults.get(gcm_key)
            if command is None:
                continue
            assert app_module.TERMINAL_ACTIONS.get(command) == action, (
                f"app.{action} claims {accel}, which [shortcuts] assigns to "
                f"'{command}' -- the terminal binding can never fire"
            )


def test_no_two_actions_share_an_accelerator(app_module, monkeypatch):
    """Duplicate accelerators silently disable the action registered second."""
    app = app_module.GcmApplication()
    registered: dict[str, list[str] | None] = {}

    def record(name, callback, accels=None, parameter_type=None):
        registered[name] = accels

    def record_stateful(name, initial_state, callback, accels=None):
        registered[name] = accels

    monkeypatch.setattr(
        app_module.Gtk.Application, "do_startup", lambda *_args: None, raising=False
    )
    monkeypatch.setattr(app, "_create_action", record)
    monkeypatch.setattr(app, "_create_stateful_action", record_stateful)
    monkeypatch.setattr(app, "_build_menus", lambda: None)

    app.do_startup()

    owners: dict[str, str] = {}
    for name, accels in registered.items():
        for accel in accels or ():
            assert accel not in owners, f"{accel} claimed by both {owners[accel]} and {name}"
            owners[accel] = name


def _registered_accels(app_module, monkeypatch):
    """Run do_startup with the action registration recorded instead of performed."""
    app = app_module.GcmApplication()
    registered: dict[str, list[str] | None] = {}

    def record(name, callback, accels=None, parameter_type=None):
        registered[name] = accels

    def record_stateful(name, initial_state, callback, accels=None):
        registered[name] = accels

    monkeypatch.setattr(
        app_module.Gtk.Application, "do_startup", lambda *_args: None, raising=False
    )
    monkeypatch.setattr(app, "_create_action", record)
    monkeypatch.setattr(app, "_create_stateful_action", record_stateful)
    monkeypatch.setattr(app, "_build_menus", lambda: None)
    app.do_startup()
    return registered


def _stub_gdk_keys(app_module, monkeypatch, known):
    """Minimal stand-in for the GDK calls shortcut_to_accel makes."""

    class Mods(int):
        def __or__(self, other):
            return Mods(int(self) | int(other))

    monkeypatch.setattr(app_module.Gdk, "ModifierType", Mods, raising=False)
    monkeypatch.setattr(app_module.Gdk, "KEY_VoidSymbol", 0xFFFFFF, raising=False)
    monkeypatch.setattr(
        app_module.Gdk, "keyval_from_name", lambda name: known.get(name, 0xFFFFFF), raising=False
    )
    monkeypatch.setattr(
        app_module.Gtk, "accelerator_name", lambda keyval, mods: f"{int(mods)}|{keyval}",
        raising=False,
    )


def test_shortcut_to_accel_collects_modifiers(app_module, monkeypatch):
    # conftest gives CTRL=1, SHIFT=2, ALT=4
    _stub_gdk_keys(app_module, monkeypatch, {"c": 99})

    assert app_module.shortcut_to_accel("CTRL+SHIFT+C") == "3|99"
    assert app_module.shortcut_to_accel("ctrl+shift+c") == "3|99"
    assert app_module.shortcut_to_accel("C") == "0|99"


def test_shortcut_to_accel_tries_capitalised_key_names(app_module, monkeypatch):
    """GCM stores key names upper-cased, but GDK knows them as Tab, Return, KP_Enter."""
    _stub_gdk_keys(app_module, monkeypatch, {"Tab": 65289, "KP_Enter": 65421})

    assert app_module.shortcut_to_accel("CTRL+TAB") == "1|65289"
    assert app_module.shortcut_to_accel("CTRL+KP_ENTER") == "1|65421"


def test_shortcut_to_accel_rejects_names_gdk_does_not_know(app_module, monkeypatch):
    """keyval_from_name reports VoidSymbol rather than 0, which is easy to miss."""
    _stub_gdk_keys(app_module, monkeypatch, {"c": 99})

    assert app_module.shortcut_to_accel("BOGUSKEY") is None
    assert app_module.shortcut_to_accel("") is None
    assert app_module.shortcut_to_accel(None) is None
    assert app_module.shortcut_to_accel("CTRL+") is None


def test_sync_shortcut_accels_follows_the_configured_shortcut(app_module, monkeypatch):
    applied = {}

    class ApplicationStub:
        def set_accels_for_action(self, action, accels):
            applied[action] = accels

    monkeypatch.setattr(
        app_module.Gtk.Application, "get_default", lambda: ApplicationStub(), raising=False
    )
    monkeypatch.setattr(app_module, "shortcut_to_accel", lambda key: f"<{key}>" if key else None)
    monkeypatch.setattr(app_module, "shortcuts", {"CTRL+ALT+Y": app_module._COPY})

    app_module.sync_shortcut_accels()

    assert applied["app.copy"] == ["<CTRL+ALT+Y>"]
    # unbound commands must be cleared, not left pointing at a stale key
    assert applied["app.paste"] == []


def test_sync_shortcut_accels_is_inert_without_an_application(app_module, monkeypatch):
    monkeypatch.setattr(app_module.Gtk.Application, "get_default", lambda: None, raising=False)

    app_module.sync_shortcut_accels()  # must not raise


def _menu_sources(app_module):
    source = Path(app_module.__file__).read_text()
    startup = source.split("def do_startup", 1)[1].split("def _create_action", 1)[0]
    actions = set(re.findall(r'_create_(?:stateful_)?action\(\s*\n?\s*"([a-z-]+)"', startup))
    menus = source.split("def _build_menus", 1)[1].split("\n    def ", 1)[0]
    reachable = set(re.findall(r'"app\.([a-z-]+)"', menus))
    return actions, reachable


def test_every_action_is_reachable_from_a_menu(app_module):
    """Menus are the discoverable surface; a command only on a key is invisible (#36)."""
    actions, reachable = _menu_sources(app_module)

    unreachable = actions - reachable
    assert unreachable == {"donate", "custom-command"}, (
        f"unexpected actions missing from the menus: {sorted(unreachable - {'donate', 'custom-command'})}"
    )


def test_donate_stays_out_of_the_menus(app_module):
    """Deliberately absent. Do not reintroduce it while completing the menus (#36)."""
    _actions, reachable = _menu_sources(app_module)

    assert "donate" not in reachable


def test_apply_menu_accels_labels_items_from_the_action_map(app_module, monkeypatch):
    class AccelLabel:
        def __init__(self):
            self.accel = None

        def set_accel(self, keyval, modifiers):
            self.accel = (keyval, modifiers)

    class MenuItem:
        def __init__(self, action, label):
            self._action = action
            self._label = label

        def get_action_name(self):
            return self._action

        def get_submenu(self):
            return None

        def get_children(self):
            return [self._label]

    class Menu:
        def __init__(self, items):
            self._items = items

        def get_children(self):
            return self._items

    class ApplicationStub:
        def get_accels_for_action(self, action):
            return {"app.copy": ["<Primary><Shift>c"]}.get(action, [])

    monkeypatch.setattr(app_module.Gtk, "AccelLabel", AccelLabel, raising=False)
    monkeypatch.setattr(
        app_module.Gtk, "accelerator_parse", lambda accel: (99, 3), raising=False
    )

    bound, unbound = AccelLabel(), AccelLabel()
    menu = Menu([MenuItem("app.copy", bound), MenuItem("app.console-rename", unbound)])

    app_module.apply_menu_accels(menu, ApplicationStub())

    assert bound.accel == (99, 3)
    # an unbound action must be cleared, not left showing a stale key
    assert unbound.accel == (0, 0)


def test_apply_menu_accels_is_inert_without_an_application(app_module, monkeypatch):
    monkeypatch.setattr(app_module.Gtk.Application, "get_default", lambda: None, raising=False)

    app_module.apply_menu_accels(object())  # must not raise
