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


class ChoiceStub(ComboBoxStub):
    """A choice Preferences saves by its value rather than its place in the list (#283)."""

    by_value = True

    def __init__(self, field: str, value: int, value_id: str):
        super().__init__(field, value)
        self._value_id = value_id

    def get_active_id(self) -> str:
        return self._value_id


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
        ChoiceStub("conf.RDP_CLIENT", 1, "mstsc"),
    ]
    wconfig.treeModel = [["Clipboard Copy", "CTRL+ALT+C"]]
    # The Snippets page's copies (#240): one without a name, and one without a key.
    Snippet = app_module.snippetlib.Snippet
    wconfig.library = [
        Snippet("aa11bb22", "", "run reboot", "ALT+R"),
        Snippet("cc33dd44", "up", "uptime"),
    ]
    wconfig.btnFColor = types.SimpleNamespace(selected_color="#112233")
    wconfig.btnBColor = types.SimpleNamespace(selected_color="#445566")
    wconfig.btnFont = ButtonStub("Monospace 14")
    wconfig.chkDefaultFont = CheckStub(False)
    wconfig.dlgColor = None
    wconfig.treeCmd = []
    wconfig.treeCustom = []
    # Preferences' prefix keys (#452): none ticked, none typed.
    wconfig.prefix_field = "conf.PREFIX_KEYS"
    wconfig.prefix_checks = {"CTRL+B": CheckStub(False), "CTRL+A": CheckStub(False)}
    wconfig.prefix_other = types.SimpleNamespace(get_text=lambda: "")

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
    conf.RDP_CLIENT = "freerdp"
    conf.FONT_COLOR = ""
    conf.BACK_COLOR = ""
    conf.FONT = ""
    conf.HIDE_DONATE = True

    donate_button = DonateButton()
    wmain_stub = WmainStub(donate_button)
    wmain_stub.conf = conf
    monkeypatch.setattr(app_module, "wMain", wmain_stub, raising=False)
    monkeypatch.setattr(app_module, "shortcuts", {})
    monkeypatch.setattr(app_module, "snippets", [])

    wconfig.on_okbutton1_clicked(None)

    # The open consoles are given the settings once they are stored, not before (#174).
    assert wmain_stub.applied_buffer_lines == 4096

    assert conf.STARTUP_LOCAL is True
    assert conf.BUFFER_LINES == 4096
    assert conf.AUTO_CLOSE_TAB == 2
    assert conf.APP_TITLE == "Custom Title"
    # Its value, not the 1 of its place in the list.
    assert conf.RDP_CLIENT == "mstsc"
    assert conf.FONT_COLOR == "#112233"
    assert conf.BACK_COLOR == "#445566"
    assert conf.FONT == "Monospace 14"

    # One without a key is a snippet too, sent from the menus.
    reboot, uptime = app_module.snippets
    assert (reboot.name, reboot.text, reboot.key) == ("run reboot", "run reboot", "ALT+R")
    assert (uptime.name, uptime.text, uptime.key) == ("up", "uptime", "")
    assert app_module.shortcuts == {"CTRL+ALT+C": ["Clipboard Copy"], "ALT+R": reboot}

    assert donate_button.visible is False
    assert wmain_stub.tree_calls == 1
    assert wmain_stub.cmd_calls == 1
    assert wmain_stub.write_calls == 1
    assert destroy_stub.destroyed is True


def test_ok_stores_the_tab_name_before_the_tabs_are_named_again(monkeypatch, app_module):
    """Redrawing the tree names the open tabs (#346), so it must find the template OK has
    just stored, and the open tabs take it at once (#348)."""
    monkeypatch.setattr(app_module.Gtk, "CheckButton", CheckButtonStub, raising=False)
    monkeypatch.setattr(app_module.Gtk, "SpinButton", SpinButtonStub, raising=False)
    monkeypatch.setattr(app_module.Gtk, "ComboBox", ComboBoxStub, raising=False)
    monkeypatch.setattr(app_module.Gtk, "Entry", EntryStub, raising=False)
    wconfig, _destroy_stub = make_wconfig(app_module)
    wconfig.tblGeneral.append(EntryStub("conf.TAB_NAME", "[{type}] {name}"))
    wmain_stub = WmainStub(DonateButton())
    wmain_stub.conf = app_module.conf
    named = []
    wmain_stub.updateTree = lambda: named.append(app_module.conf.TAB_NAME)
    monkeypatch.setattr(app_module, "wMain", wmain_stub, raising=False)
    monkeypatch.setattr(app_module, "shortcuts", {})
    monkeypatch.setattr(app_module, "snippets", [])

    wconfig.on_okbutton1_clicked(None)

    assert named == ["[{type}] {name}"]


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


def test_the_combo_box_fakes_match_real_gtk():
    gi = pytest.importorskip("gi", reason="PyGObject not available")
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    for name in ("get_active", "get_active_id"):
        assert hasattr(Gtk.ComboBoxText, name), name


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

app.conf.CHECK_UPDATES = False
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


def kept(app_module, library):
    wconfig = object.__new__(app_module.Wconfig)
    wconfig.library = library
    return wconfig.kept_snippets()


def test_ok_keeps_each_snippet_as_the_page_left_it(app_module):
    Snippet = app_module.snippetlib.Snippet
    snippet = Snippet("aa11bb22", " Disk usage ", "df -h", " F8 ", " ops / db/ ", " free ")

    assert kept(app_module, [snippet]) == [
        Snippet("aa11bb22", "Disk usage", "df -h", "F8", "ops/db", "free")
    ]


def test_a_snippet_without_text_is_not_kept(app_module):
    """It has nothing to send, and gcm.conf would not bring it back."""
    Snippet = app_module.snippetlib.Snippet

    assert kept(app_module, [Snippet("aa11bb22", "empty", ""), Snippet("cc33dd44", "", "\n")]) == [
        Snippet("cc33dd44", repr("\n"), "\n")
    ]


def test_a_snippet_without_a_name_is_named_by_its_first_line(app_module):
    Snippet = app_module.snippetlib.Snippet

    [snippet] = kept(app_module, [Snippet("aa11bb22", "  ", "\nw\nuptime")])

    assert snippet.name == "w"


def test_of_two_snippets_with_one_key_the_later_keeps_it(app_module):
    """The earlier is kept, without it, where a custom command was dropped."""
    Snippet = app_module.snippetlib.Snippet
    library = [Snippet("aa11bb22", "first", "a", "F8"), Snippet("cc33dd44", "second", "b", "F8")]

    first, second = kept(app_module, library)

    assert (first.key, second.key) == ("", "F8")


# -- the Shortcut column: a key to clear, and a key cleared stays cleared (#419) -----------


def click_ok(app_module, monkeypatch, rows):
    """Press OK in Preferences with `rows` in its list of commands, and nothing else."""
    wconfig, _destroy_stub = make_wconfig(app_module)
    wconfig.tblGeneral = []
    wconfig.treeModel = rows
    wmain_stub = WmainStub(DonateButton())
    wmain_stub.conf = app_module.conf
    monkeypatch.setattr(app_module, "wMain", wmain_stub, raising=False)
    monkeypatch.setattr(app_module, "shortcuts", {})
    monkeypatch.setattr(app_module, "unbound_commands", set())
    monkeypatch.setattr(app_module, "snippets", [])
    wconfig.library = []

    wconfig.on_okbutton1_clicked(None)


def test_ok_keeps_a_command_without_a_key_without_one(monkeypatch, app_module):
    """The row is empty, where the row used to be dropped and the command came back on its
    default at the next start: OK now keeps it apart, since `shortcuts` is keyed by key."""
    rows = [["save", ""], ["find", ""], ["copy", "CTRL+SHIFT+C"]]

    click_ok(app_module, monkeypatch, rows)

    assert app_module.shortcuts == {"CTRL+SHIFT+C": ["copy"]}
    assert app_module.unbound_commands == {"save", "find"}


def test_ok_with_every_command_bound_leaves_none_unbound(monkeypatch, app_module):
    click_ok(app_module, monkeypatch, [["copy", "CTRL+SHIFT+C"], ["paste", "CTRL+SHIFT+V"]])

    assert app_module.shortcuts == {"CTRL+SHIFT+C": ["copy"], "CTRL+SHIFT+V": ["paste"]}
    assert app_module.unbound_commands == set()


def test_ok_gives_a_command_without_a_key_no_accelerator(monkeypatch, app_module):
    """`sync_shortcut_accels` gives [] to a command that `shortcuts` does not hold."""
    applied = {}

    class ApplicationStub:
        def set_accels_for_action(self, action, accels):
            applied[action] = accels

    monkeypatch.setattr(
        app_module.Gtk.Application, "get_default", lambda: ApplicationStub(), raising=False
    )
    monkeypatch.setattr(app_module, "shortcut_to_accel", lambda key: f"<{key}>" if key else None)

    click_ok(app_module, monkeypatch, [["find", ""], ["copy", "CTRL+SHIFT+C"]])

    assert applied["app.find"] == []
    assert applied["app.copy"] == ["<CTRL+SHIFT+C>"]


class FieldStub:
    """The entry of the cell editor, which has only what the handler asks of it."""

    def __init__(self, text: str = "OLD"):
        self.text = text

    def set_text(self, text: str) -> None:
        self.text = text


CTRL, SHIFT, ALT, SUPER = 1, 2, 4, 8


def press_in_column(app_module, monkeypatch, name, state=0, types_text=True, capturing=True):
    """Press the key GDK calls `name` in the Shortcut column's editor.

    Returns what the handler answered, and the entry. GDK's key names are the fakes' keyvals,
    so that `get_key_name` is the real one; `types_text` is what GDK says of the key.
    """
    monkeypatch.setattr(app_module.Gdk, "keyval_name", lambda keyval: keyval, raising=False)
    monkeypatch.setattr(
        app_module.Gdk, "keyval_to_unicode", lambda _keyval: 1 if types_text else 0, raising=False
    )
    wconfig = object.__new__(app_module.Wconfig)
    wconfig.capture_keys = capturing
    entry = FieldStub()
    event = types.SimpleNamespace(keyval=name, state=state)

    answered = wconfig.on_treeCommands_key_press_event(entry, event, "model", "row", 1)

    return answered, entry


@pytest.mark.parametrize("name", ["BackSpace", "Delete"])
def test_backspace_or_delete_clears_the_key_and_the_entry_does_not_act(
    app_module, monkeypatch, name
):
    """BackSpace bound BackSpace, and Delete left 'ELETE', measured (#419). True keeps the
    entry from acting on the key after the handler has."""
    answered, entry = press_in_column(app_module, monkeypatch, name)

    assert entry.text == ""
    assert answered is True


@pytest.mark.parametrize(
    ("name", "state", "types_text", "bound"),
    [
        ("s", CTRL, True, "CTRL+S"),
        ("s", CTRL | SHIFT, True, "CTRL+SHIFT+S"),
        ("F8", 0, False, "F8"),
        ("r", ALT, True, "ALT+R"),
        # Enter and Tab bind with a key held, as the default keys Ctrl+Return and Ctrl+Tab do
        ("Return", CTRL, True, "CTRL+RETURN"),
        ("Tab", CTRL, True, "CTRL+TAB"),
        ("BackSpace", CTRL, True, "CTRL+BACKSPACE"),
    ],
)
def test_a_key_pressed_is_named_as_the_key_of_the_command(
    app_module, monkeypatch, name, state, types_text, bound
):
    answered, entry = press_in_column(app_module, monkeypatch, name, state, types_text)

    assert entry.text == bound
    assert answered is True


@pytest.mark.parametrize(
    ("name", "state"),
    [
        ("a", 0),  # a letter would be taken from every console
        ("A", SHIFT),
        ("space", 0),
        ("Shift_L", 0),  # a modifier waits for the key it modifies
        ("Control_R", CTRL),
        ("Super_L", SUPER),
    ],
)
def test_a_key_that_binds_nothing_leaves_the_text_and_the_entry_does_not_act(
    app_module, monkeypatch, name, state
):
    """Handed on, the entry typed it after the name the handler had written."""
    answered, entry = press_in_column(app_module, monkeypatch, name, state)

    assert entry.text == "OLD"
    assert answered is True


@pytest.mark.parametrize(
    "name", ["Return", "KP_Enter", "ISO_Enter", "Tab", "ISO_Left_Tab", "Escape"]
)
def test_enter_tab_and_escape_are_left_to_the_cell_editor(app_module, monkeypatch, name):
    """Enter commits, Tab moves on and commits, and Escape cancels: they are the editor's."""
    answered, entry = press_in_column(app_module, monkeypatch, name)

    assert entry.text == "OLD"
    assert answered is False


def test_a_key_is_ignored_unless_the_editor_is_capturing_keys(app_module, monkeypatch):
    answered, entry = press_in_column(
        app_module, monkeypatch, "F8", types_text=False, capturing=False
    )

    assert entry.text == "OLD"
    assert answered is False


def test_a_call_without_the_editor_s_three_arguments_captures_nothing(app_module, monkeypatch):
    monkeypatch.setattr(app_module.Gdk, "keyval_name", lambda keyval: keyval, raising=False)
    wconfig = object.__new__(app_module.Wconfig)
    wconfig.capture_keys = True
    entry = FieldStub()

    answered = wconfig.on_treeCommands_key_press_event(entry, types.SimpleNamespace(keyval="F8"))

    assert entry.text == "OLD"
    assert answered is False


def test_the_key_names_the_shortcut_column_goes_by_are_gdks_own():
    """The handler compares GDK's names, which the fakes above cannot vouch for."""
    gi = pytest.importorskip("gi", reason="PyGObject not available")
    gi.require_version("Gdk", "3.0")
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gdk, Gtk

    named = {
        "Return": Gdk.KEY_Return,
        "KP_Enter": Gdk.KEY_KP_Enter,
        "ISO_Enter": Gdk.KEY_ISO_Enter,
        "Tab": Gdk.KEY_Tab,
        "ISO_Left_Tab": Gdk.KEY_ISO_Left_Tab,
        "Escape": Gdk.KEY_Escape,
        "BackSpace": Gdk.KEY_BackSpace,
        "Delete": Gdk.KEY_Delete,
    }
    for name, keyval in named.items():
        assert Gdk.keyval_name(keyval) == name
    assert Gdk.keyval_to_unicode(Gdk.KEY_a) != 0, "a letter types text"
    assert Gdk.keyval_to_unicode(Gdk.KEY_F8) == 0, "a function key does not"
    assert hasattr(Gtk.Entry, "set_text"), "the fake entry offers set_text"
    assert hasattr(FieldStub, "set_text")


# -- Preferences' prefix keys (#452) ------------------------------------------


def test_ok_stores_the_ticked_prefix_keys_and_the_other_keys_typed(monkeypatch, app_module):
    monkeypatch.setattr(app_module.Gtk, "CheckButton", CheckButtonStub, raising=False)
    monkeypatch.setattr(app_module.Gtk, "SpinButton", SpinButtonStub, raising=False)
    monkeypatch.setattr(app_module.Gtk, "ComboBox", ComboBoxStub, raising=False)
    monkeypatch.setattr(app_module.Gtk, "Entry", EntryStub, raising=False)
    wconfig, _destroy_stub = make_wconfig(app_module)
    wconfig.prefix_checks["CTRL+A"].set_active(True)
    wconfig.prefix_other = types.SimpleNamespace(get_text=lambda: "grave, ctrl+a,F5")
    wmain_stub = WmainStub(DonateButton())
    wmain_stub.conf = app_module.conf
    monkeypatch.setattr(app_module, "wMain", wmain_stub, raising=False)
    monkeypatch.setattr(app_module, "shortcuts", {})
    monkeypatch.setattr(app_module, "snippets", [])
    monkeypatch.setattr(app_module.conf, "PREFIX_KEYS", "", raising=False)

    wconfig.on_okbutton1_clicked(None)

    assert app_module.conf.PREFIX_KEYS == "CTRL+A,GRAVE,F5"


def test_no_prefix_key_is_set_by_default(app_module):
    assert app_module.conf.PREFIX_KEYS == ""
    assert ("PREFIX_KEYS", "options", "prefix-keys", str) in app_module.CONFIG_OPTIONS


class WidgetFake:
    """Whatever addPrefixKeys draws: it keeps its text and its state, and takes anything."""

    def __init__(self, *_args, label: str = "", **_kwargs):
        self.text = label
        self.active = False
        self.children: list = []

    def __getattr__(self, name: str):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *_args, **_kwargs: None

    def set_text(self, text: str) -> None:
        self.text = text

    def get_text(self) -> str:
        return self.text

    def set_active(self, value: bool) -> None:
        self.active = value

    def get_active(self) -> bool:
        return self.active

    def pack_start(self, child, *_args) -> None:
        self.children.append(child)


def test_preferences_draws_a_checkbox_for_each_common_prefix_and_a_field_for_the_rest(
    app_module, monkeypatch
):
    """On the Shortcuts page, ticked as gcm.conf says, the rest in the field."""
    for name in ("Box", "Label", "CheckButton", "Entry"):
        monkeypatch.setattr(app_module.Gtk, name, WidgetFake, raising=False)
    wconfig = object.__new__(app_module.Wconfig)
    box = WidgetFake()
    wconfig.get_widget = lambda name: box
    monkeypatch.setattr(app_module.conf, "PREFIX_KEYS", "CTRL+X,F5", raising=False)

    wconfig.addPrefixKeys("Prefix keys", "conf.PREFIX_KEYS")

    assert {key: check.get_active() for key, check in wconfig.prefix_checks.items()} == {
        "CTRL+B": False,
        "CTRL+A": False,
        "CTRL+X": True,
    }
    assert [check.text for check in wconfig.prefix_checks.values()] == [
        "Ctrl+B (tmux)",
        "Ctrl+A (screen)",
        "Ctrl+X (Emacs)",
    ]
    assert wconfig.prefix_other.get_text() == "F5"
    assert wconfig.prefix_keys_value() == "CTRL+X,F5"


def test_the_other_keys_field_takes_the_key_pressed(app_module, monkeypatch):
    monkeypatch.setattr(app_module.Gdk, "keyval_name", lambda keyval: keyval, raising=False)
    entry = WidgetFake()
    take = app_module.take_prefix_key

    assert take(entry, types.SimpleNamespace(keyval="grave", state=0)) is True
    assert entry.get_text() == "GRAVE"
    assert take(entry, types.SimpleNamespace(keyval="b", state=CTRL)) is True
    assert entry.get_text() == "GRAVE,CTRL+B"
    # A modifier alone waits for its key; Tab is the dialog's; Backspace clears.
    assert take(entry, types.SimpleNamespace(keyval="Shift_L", state=0)) is True
    assert entry.get_text() == "GRAVE,CTRL+B"
    assert take(entry, types.SimpleNamespace(keyval="Tab", state=0)) is False
    assert entry.get_text() == "GRAVE,CTRL+B"
    assert take(entry, types.SimpleNamespace(keyval="BackSpace", state=0)) is True
    assert entry.get_text() == ""


def test_the_prefix_keys_box_is_on_the_shortcuts_page_in_the_glade():
    from xml.etree import ElementTree

    glade = Path(__file__).resolve().parent.parent / "data/ui/gnome-connection-manager.glade"
    root = ElementTree.parse(glade).getroot()
    vbox = root.find(".//object[@id='vbox4']")
    assert vbox.find(".//object[@id='boxPrefixKeys']") is not None
    assert vbox.find(".//object[@id='treeCommands']") is not None
