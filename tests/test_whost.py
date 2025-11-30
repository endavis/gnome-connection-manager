"""Tests for the Whost dialog logic (host add/edit flows) without GTK."""

from __future__ import annotations

import types


class TextEntry:
    def __init__(self, text: str = ""):
        self.text = text

    def get_text(self) -> str:
        return self.text

    def set_text(self, value: str) -> None:
        self.text = value


class ComboStub:
    def __init__(self, text: str):
        self.text = text

    def get_active_text(self) -> str:
        return self.text


class CheckStub:
    def __init__(self, active: bool = False):
        self.active = active

    def get_active(self) -> bool:
        return self.active

    def set_active(self, value: bool) -> None:
        self.active = value


class BufferStub:
    def __init__(self, text: str = ""):
        self.text = text

    def get_text(self, *_args, **_kwargs) -> str:
        return self.text


class TextViewStub:
    def __init__(self, text: str = ""):
        self.buffer = BufferStub(text)

    def get_buffer(self) -> BufferStub:
        return self.buffer

    def set_sensitive(self, *_args, **_kwargs):
        pass


class TreeModelStub(list):
    def append(self, value):
        super().append(value)


class ColorButtonStub:
    def __init__(self, rgba):
        self._rgba = rgba

    def get_rgba(self):
        return self._rgba


class DestroyStub:
    def __init__(self):
        self.destroyed = False

    def destroy(self):
        self.destroyed = True


def make_whost(app_module, *, commands: str = "", keepalive: str = ""):
    whost = object.__new__(app_module.Whost)
    whost.cmbGroup = ComboStub("ops")
    whost.txtName = TextEntry("router")
    whost.txtDescription = TextEntry("edge router")
    whost.txtHost = TextEntry("router.example.com")
    whost.cmbType = ComboStub("ssh")
    whost.txtUser = TextEntry("netops")
    whost.txtPass = TextEntry("secret")
    whost.txtPrivateKey = TextEntry("/home/netops/.ssh/id_rsa")
    whost.txtPort = TextEntry("2222")
    whost.txtCommands = TextViewStub(commands)
    whost.chkCommands = CheckStub(bool(commands))
    whost.txtKeepAlive = TextEntry(keepalive or "30")
    whost.chkKeepAlive = CheckStub(bool(keepalive))
    whost.treeModel = TreeModelStub()
    whost.chkX11 = CheckStub(True)
    whost.chkAgent = CheckStub(True)
    whost.chkCompression = CheckStub(False)
    whost.txtCompressionLevel = TextEntry("5")
    whost.txtExtraParams = TextEntry("-oStrictHostKeyChecking=no")
    whost.chkLogging = CheckStub(True)
    whost.cmbBackspace = types.SimpleNamespace(get_active=lambda: 1)
    whost.cmbDelete = types.SimpleNamespace(get_active=lambda: 2)
    whost.txtTerm = TextEntry("xterm-256color")
    whost.btnFColor = ColorButtonStub(types.SimpleNamespace(red=1, green=1, blue=1))
    whost.btnBColor = ColorButtonStub(types.SimpleNamespace(red=0, green=0, blue=0))
    whost.isNew = True

    destroy_stub = DestroyStub()
    widgets = {
        "chkDefaultColors": CheckStub(True),
        "wHost": destroy_stub,
    }
    whost.widgets = widgets
    whost.get_widget = lambda name: widgets[name]
    return whost, destroy_stub


def test_whost_on_okbutton_adds_host_and_updates_wmain(monkeypatch, app_module):
    whost, destroy_stub = make_whost(app_module)
    monkeypatch.setattr(app_module, "groups", {"ops": []})

    class WmainStub:
        def __init__(self):
            self.tree_calls = 0
            self.write_calls = 0

        def updateTree(self):
            self.tree_calls += 1

        def writeConfig(self):
            self.write_calls += 1

    wmain_stub = WmainStub()
    monkeypatch.setattr(app_module, "wMain", wmain_stub, raising=False)
    captured = {}
    monkeypatch.setattr(app_module, "msgbox", lambda text: captured.setdefault("msg", text))

    whost.on_okbutton1_clicked(None)

    assert "msg" not in captured
    assert len(app_module.groups["ops"]) == 1
    host = app_module.groups["ops"][0]
    assert host.name == "router"
    assert host.host == "router.example.com"
    assert host.user == "netops"
    assert host.term == "xterm-256color"
    assert wmain_stub.tree_calls == 1
    assert wmain_stub.write_calls == 1
    assert destroy_stub.destroyed is True


def test_whost_on_okbutton_validates_port(monkeypatch, app_module):
    whost, destroy_stub = make_whost(app_module)
    whost.txtPort = TextEntry("invalid")
    monkeypatch.setattr(app_module, "groups", {"ops": []})
    messages = {}
    monkeypatch.setattr(app_module, "msgbox", lambda text: messages.setdefault("msg", text))

    whost.on_okbutton1_clicked(None)

    assert messages["msg"] == app_module._("Puerto invalido")
    assert app_module.groups["ops"] == []
    assert destroy_stub.destroyed is False
