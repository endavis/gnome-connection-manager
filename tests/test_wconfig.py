"""Tests for the Wconfig dialog logic without GTK widgets."""

from __future__ import annotations

import types


class CheckButtonStub:
    def __init__(self, field: str, value: bool):
        self.field = field
        self._value = value

    def get_active(self) -> bool:
        return self._value


class SpinButtonStub:
    def __init__(self, field: str, value: int):
        self.field = field
        self._value = value

    def set_range(self, *_args, **_kwargs):
        pass

    def set_increments(self, *_args, **_kwargs):
        pass

    def set_numeric(self, *_args, **_kwargs):
        pass

    def set_value(self, value: int):
        self._value = value

    def get_value_as_int(self) -> int:
        return self._value


class ComboBoxStub:
    def __init__(self, field: str, value: int):
        self.field = field
        self._value = value

    def get_active(self) -> int:
        return self._value


class EntryStub:
    def __init__(self, field: str, text: str):
        self.field = field
        self._text = text

    def get_text(self) -> str:
        return self._text


class ButtonStub:
    def __init__(self, label: str):
        self.selected_font = types.SimpleNamespace(to_string=lambda: label)

    def set_label(self, *_args, **_kwargs):
        pass


class CheckStub:
    def __init__(self, active: bool):
        self._active = active

    def get_active(self) -> bool:
        return self._active

    def set_active(self, value: bool):
        self._active = value


class DestroyStub:
    def __init__(self):
        self.destroyed = False

    def destroy(self):
        self.destroyed = True


class DonateButton:
    def __init__(self):
        self.visible = True

    def hide(self):
        self.visible = False

    def show(self):
        self.visible = True


class WmainStub:
    def __init__(self, donate: DonateButton):
        self.donate = donate
        self.tree_calls = 0
        self.cmd_calls = 0
        self.write_calls = 0

    def get_widget(self, name: str):
        if name == "btnDonate":
            return self.donate
        raise KeyError(name)

    def updateTree(self):
        self.tree_calls += 1

    def populateCommandsMenu(self):
        self.cmd_calls += 1

    def writeConfig(self):
        self.write_calls += 1


def make_wconfig(app_module):
    wconfig = object.__new__(app_module.Wconfig)
    wconfig.tblGeneral = [
        CheckButtonStub("conf.STARTUP_LOCAL", True),
        SpinButtonStub("conf.BUFFER_LINES", 4096),
        ComboBoxStub("conf.AUTO_CLOSE_TAB", 2),
        EntryStub("conf.APP_TITLE", "Custom Title"),
    ]
    wconfig.treeModel = [["Clipboard Copy", "CTRL+ALT+C"]]
    wconfig.treeModel2 = [["ALT+R", "run reboot"]]
    wconfig.btnFColor = types.SimpleNamespace(selected_color="#112233")
    wconfig.btnBColor = types.SimpleNamespace(selected_color="#445566")
    wconfig.btnFont = ButtonStub("Monospace 14")
    wconfig.chkDefaultFont = CheckStub(False)
    wconfig.dlgColor = None
    wconfig.treeCmd = []
    wconfig.treeCustom = []

    destroy_stub = DestroyStub()
    widgets = {
        "chkDefaultColors1": CheckStub(False),
        "wConfig": destroy_stub,
    }
    wconfig.get_widget = lambda name: widgets[name]
    return wconfig, destroy_stub


def test_wconfig_on_okbutton_updates_conf_shortcuts(monkeypatch, app_module):
    monkeypatch.setattr(app_module.Gtk, "CheckButton", CheckButtonStub, raising=False)
    monkeypatch.setattr(app_module.Gtk, "SpinButton", SpinButtonStub, raising=False)
    monkeypatch.setattr(app_module.Gtk, "ComboBox", ComboBoxStub, raising=False)
    monkeypatch.setattr(app_module.Gtk, "Entry", EntryStub, raising=False)

    wconfig, destroy_stub = make_wconfig(app_module)

    conf = app_module.conf
    conf.STARTUP_LOCAL = False
    conf.BUFFER_LINES = 100
    conf.AUTO_CLOSE_TAB = 0
    conf.APP_TITLE = "Old"
    conf.FONT_COLOR = ""
    conf.BACK_COLOR = ""
    conf.FONT = ""
    conf.HIDE_DONATE = True

    donate_button = DonateButton()
    wmain_stub = WmainStub(donate_button)
    monkeypatch.setattr(app_module, "wMain", wmain_stub, raising=False)
    monkeypatch.setattr(app_module, "shortcuts", {})

    wconfig.on_okbutton1_clicked(None)

    assert conf.STARTUP_LOCAL is True
    assert conf.BUFFER_LINES == 4096
    assert conf.AUTO_CLOSE_TAB == 2
    assert conf.APP_TITLE == "Custom Title"
    assert conf.FONT_COLOR == "#112233"
    assert conf.BACK_COLOR == "#445566"
    assert conf.FONT == "Monospace 14"

    assert app_module.shortcuts == {
        "CTRL+ALT+C": ["Clipboard Copy"],
        "run reboot": "ALT+R",
    }

    assert donate_button.visible is False
    assert wmain_stub.tree_calls == 1
    assert wmain_stub.cmd_calls == 1
    assert wmain_stub.write_calls == 1
    assert destroy_stub.destroyed is True
