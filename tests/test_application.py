"""Tests for GcmApplication action wrappers that don't require GTK windows."""

from __future__ import annotations

import types


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

    def terminal_paste(self, terminal):
        terminal.pasted += 1
        self.calls.append(("paste", terminal))

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
