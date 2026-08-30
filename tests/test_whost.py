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
    captured: dict = {}
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
    messages: dict = {}
    monkeypatch.setattr(app_module, "msgbox", lambda text: messages.setdefault("msg", text))

    whost.on_okbutton1_clicked(None)

    assert messages["msg"] == app_module._("Puerto invalido")
    assert app_module.groups["ops"] == []
    assert destroy_stub.destroyed is False


# -- the dialog changes shape by connection type, on purpose (#103) -----------


def test_only_ssh_hosts_get_a_port_forwarding_tab(app_module):
    """Documented in SPEC.md and AGENTS.md; this keeps the documentation true.

    Hiding the page takes its tab with it, so a Telnet host's dialog has three tabs
    where an SSH host's has four. That reads as a glitch unless you know it is meant,
    which is why it is written down -- and why this holds it to what is written.
    """
    hidden = []
    shown = []

    class Grid:
        def hide(self):
            hidden.append(True)

        def show(self):
            shown.append(True)

    class Toggle:
        def __init__(self):
            self.sensitive = None
            self.active = False

        def set_sensitive(self, value):
            self.sensitive = value

        def get_active(self):
            return self.active

        def set_text(self, _text):
            pass

    dialog = app_module.Whost.__new__(app_module.Whost)
    controls = {
        name: Toggle()
        for name in (
            "txtKeepAlive",
            "chkKeepAlive",
            "chkX11",
            "chkAgent",
            "chkCompression",
            "txtCompressionLevel",
            "txtPrivateKey",
            "btnBrowse",
            "txtPort",
            "txtUser",
            "txtPassword",
            "txtHost",
            "txtExtraParams",
        )
    }
    for name, widget in controls.items():
        setattr(dialog, name, widget)
    dialog.get_widget = lambda name: Grid() if name == "tunnelGrid" else controls.get(name)

    dialog.on_cmbType_changed(types.SimpleNamespace(get_active_text=lambda: "ssh"))
    assert shown and not hidden, "SSH must keep the Port forwarding tab"

    shown.clear()
    dialog.on_cmbType_changed(types.SimpleNamespace(get_active_text=lambda: "telnet"))
    assert hidden and not shown, "Telnet must not offer port forwarding"


def test_the_other_ssh_only_controls_are_disabled_rather_than_hidden(app_module):
    """The tunnel page is the only thing that disappears; everything else greys out.

    That asymmetry is what makes the vanishing tab look like a fault, so it is worth
    holding in place: if these ever start hiding too, the documentation is wrong.
    """

    class Control:
        def __init__(self):
            self.sensitive = None

        def set_sensitive(self, value):
            self.sensitive = value

        def get_active(self):
            return False

        def set_text(self, _text):
            pass

    class Grid:
        def hide(self):
            pass

        def show(self):
            pass

    dialog = app_module.Whost.__new__(app_module.Whost)
    ssh_only = (
        "txtKeepAlive",
        "chkKeepAlive",
        "chkX11",
        "chkAgent",
        "chkCompression",
        "txtCompressionLevel",
        "txtPrivateKey",
        "btnBrowse",
    )
    controls = {
        name: Control()
        for name in (*ssh_only, "txtPort", "txtUser", "txtPassword", "txtHost", "txtExtraParams")
    }
    for name, widget in controls.items():
        setattr(dialog, name, widget)
    dialog.get_widget = lambda name: Grid() if name == "tunnelGrid" else controls.get(name)

    dialog.on_cmbType_changed(types.SimpleNamespace(get_active_text=lambda: "telnet"))

    still_there = [n for n in ssh_only if controls[n].sensitive is not False]
    assert not still_there, f"these should be insensitive for telnet: {still_there}"
