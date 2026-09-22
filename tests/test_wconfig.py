"""Tests for the Wconfig dialog logic without GTK widgets."""

from __future__ import annotations

import os
import subprocess
import sys
import types
from pathlib import Path

import pytest


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
        self.conf = None  # the test's conf, read back when the consoles are given it
        self.applied_buffer_lines = None

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

    def apply_settings_to_open_consoles(self):
        self.applied_buffer_lines = self.conf.BUFFER_LINES


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
    wmain_stub.conf = conf
    monkeypatch.setattr(app_module, "wMain", wmain_stub, raising=False)
    monkeypatch.setattr(app_module, "shortcuts", {})

    wconfig.on_okbutton1_clicked(None)

    # The open consoles are given the settings once they are stored, not before (#174).
    assert wmain_stub.applied_buffer_lines == 4096

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


# -- preferences are addressed by name, not executed as source ---------------


def test_resolve_preference_splits_the_address(app_module):
    owner, attribute = app_module.resolve_preference("conf.LOG_PATH")

    assert owner is app_module.conf
    assert attribute == "LOG_PATH"


def test_resolve_preference_refuses_an_address_it_does_not_own(app_module):
    """The old exec() would happily have run anything on the left of the `=`."""
    with pytest.raises(ValueError, match="unsupported preference field"):
        app_module.resolve_preference("os.environ")


def test_a_preference_containing_a_quote_round_trips(app_module, monkeypatch):
    """Saving used to interpolate the typed text into an exec() statement, so a value
    with a double quote in it was a SyntaxError and the preference silently never saved.
    """
    monkeypatch.setattr(app_module.conf, "WORD_SEPARATORS", "", raising=False)

    owner, attribute = app_module.resolve_preference("conf.WORD_SEPARATORS")
    setattr(owner, attribute, 'has "quotes" inside')

    assert app_module.conf.WORD_SEPARATORS == 'has "quotes" inside'


# -- the window centring idle must not outlive its window (#175) -------------


class CenteringWindow:
    """The window methods center_window uses. The real Gtk.Window has each (checked below).

    A destroyed window reports no GdkWindow and is no longer visible, both measured on
    GTK 3; a hidden one keeps its GdkWindow.
    """

    def __init__(self, gdk_window=None, visible=True):
        self._gdk_window = gdk_window
        self._visible = visible
        self.moved = []

    def get_window(self):
        return self._gdk_window

    def get_visible(self):
        return self._visible

    def get_screen(self):
        return types.SimpleNamespace(
            get_monitor_at_window=lambda _window: 0,
            get_monitor_geometry=lambda _monitor: types.SimpleNamespace(
                x=100, y=50, width=1000, height=800
            ),
        )

    def get_size(self):
        return (400, 300)

    def move(self, x, y):
        self.moved.append((x, y))

    def destroy(self):
        self._gdk_window = None
        self._visible = False


def test_centering_window_fake_matches_real_gtk():
    gi = pytest.importorskip("gi", reason="PyGObject not available")
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    for name in ("get_window", "get_visible", "get_screen", "get_size", "move", "destroy"):
        assert hasattr(CenteringWindow, name), f"fake is missing {name}"
        assert hasattr(Gtk.Window, name), f"Gtk.Window has no {name}"


def _queued_centring(app_module, monkeypatch, window):
    """center_window's idle callback, and the window it was given."""
    queued = []
    monkeypatch.setattr(
        app_module.GLib, "idle_add", lambda callback, *a, **k: queued.append(callback)
    )
    wconfig = object.__new__(app_module.Wconfig)
    wconfig.main_widget = window
    wconfig.center_window()

    assert len(queued) == 1, "center_window must queue exactly one idle"
    return queued[0]


def _window(app_module, **kwargs):
    return type("Window", (CenteringWindow, app_module.Gtk.Window), {})(**kwargs)


def test_centering_waits_for_a_window_gtk_has_not_made_yet(app_module, monkeypatch):
    window = _window(app_module)

    assert _queued_centring(app_module, monkeypatch, window)() is True
    assert window.moved == []


def test_centering_stops_once_the_window_is_destroyed(app_module, monkeypatch):
    """It asked to run again for as long as there was no GdkWindow, and a destroyed
    window never gets one. Gtk.events_pending() then never went false, and every
    `while Gtk.events_pending()` loop ran for good -- addTab's among them (#175)."""
    window = _window(app_module)
    move_to_center = _queued_centring(app_module, monkeypatch, window)

    window.destroy()

    assert move_to_center() is False
    assert window.moved == []


def test_centering_centres_on_the_monitor_once_there_is_a_window(app_module, monkeypatch):
    window = _window(app_module, gdk_window=object())

    assert _queued_centring(app_module, monkeypatch, window)() is False
    assert window.moved == [(100 + (1000 - 400) // 2, 50 + (800 - 300) // 2)]


# The idle is GTK's to run, and the hang was GCM's own event loops spinning on it. Only
# a real dialog on a real main loop shows that. HOME is redirected so this can never
# touch a real ~/.gcm.
_CENTERING_SCRIPT = """
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(); os.environ["SHELL"] = "/bin/sh"; sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk
from gnome_connection_manager import app

app.wMain = wmain = app.Wmain(application=None)
prefs = app.Wconfig()
prefs.get_widget("wConfig").destroy()

# addTab waits like this, and so do four other places. An idle that outlives its window
# keeps events_pending() true, and none of them ever return.
for _ in range(2000):
    if not Gtk.events_pending():
        break
    Gtk.main_iteration_do(False)
else:
    raise AssertionError("still pending: the centring idle outlived the window it centres")
print("OK")
"""


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="needs a display for a real window")
def test_preferences_closed_at_once_leaves_nothing_pending_against_real_gtk():
    """Destroying Preferences before its first idle ran hung the next new tab."""
    pytest.importorskip("gi", reason="PyGObject not available")
    result = subprocess.run(
        [sys.executable, "-c", _CENTERING_SCRIPT],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        timeout=120,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert "OK" in result.stdout
