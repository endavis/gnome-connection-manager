"""Which window a dialog opens over, in the order `dialog_parent` decides it (#403).

Under Wayland GTK cannot place a window, and the compositor puts one over its transient
parent where it has one. Every window GCM opens asks `dialog_parent` for it, so the order
it answers in is what these hold: the modal window on top, then the parent the caller
named, the console window in use, and the main window.

Asked here under the suite's `gi` stub, with windows made from its `Gtk.Window`, which is
what `dialog_parent` takes for a window, so that no display is needed.
`tests/test_dialog_parents.py` holds that everything asks it, and opens real windows.
"""

from __future__ import annotations

import types

import pytest


def windows(app_module, count):
    """`count` windows of the stub's `Gtk.Window`."""
    return [app_module.Gtk.Window() for _ in range(count)]


def put_wmain(app_module, monkeypatch, **attributes):
    """A Wmain with only `attributes`, where GCM keeps its own."""
    controller = types.SimpleNamespace(**attributes)
    monkeypatch.setattr(app_module, "wMain", controller, raising=False)
    return controller


def put_on_top(app_module, monkeypatch, window):
    """`window` the modal window on top, or None for there being none."""
    monkeypatch.setattr(app_module, "modal_window", lambda: window)


def test_the_modal_window_on_top_beats_the_parent_a_caller_names(app_module, monkeypatch):
    main, console, named, top = windows(app_module, 4)
    put_wmain(
        app_module, monkeypatch, wMain=main, window_in_use=console, console_windows=(console,)
    )
    put_on_top(app_module, monkeypatch, top)

    assert app_module.dialog_parent(named) is top
    assert app_module.dialog_parent() is top


def test_the_parent_a_caller_names_beats_the_console_window_in_use(app_module, monkeypatch):
    main, console, named = windows(app_module, 3)
    put_wmain(
        app_module, monkeypatch, wMain=main, window_in_use=console, console_windows=(console,)
    )
    put_on_top(app_module, monkeypatch, None)

    assert app_module.dialog_parent(named) is named


def test_the_parent_a_caller_names_is_returned_as_given(app_module, monkeypatch):
    """Callers always handed theirs straight to GTK, and tests hand stand-ins: it is not
    checked to be a window."""
    put_on_top(app_module, monkeypatch, None)
    stand_in = object()

    assert app_module.dialog_parent(stand_in) is stand_in


def test_the_console_window_in_use_beats_the_main_window(app_module, monkeypatch):
    main, console, other = windows(app_module, 3)
    put_wmain(
        app_module, monkeypatch, wMain=main, window_in_use=console, console_windows=(other, console)
    )
    put_on_top(app_module, monkeypatch, None)

    assert app_module.dialog_parent() is console
    assert app_module.dialog_parent(None) is console


@pytest.mark.parametrize("in_use", ["none", "main", "closed"])
def test_the_main_window_is_the_parent_when_no_console_window_is_in_use(
    app_module, monkeypatch, in_use
):
    """Nothing is in use at the start, the main window once it is active, and a console
    window that has closed is in no list. A console window that is open but not in use is
    in the list in each case, and is not taken."""
    main, open_one, closed = windows(app_module, 3)
    window_in_use = {"none": None, "main": main, "closed": closed}[in_use]
    put_wmain(
        app_module,
        monkeypatch,
        wMain=main,
        window_in_use=window_in_use,
        console_windows=(open_one,),
    )
    put_on_top(app_module, monkeypatch, None)

    assert app_module.dialog_parent() is main


def test_there_is_no_parent_before_a_wmain_is_built(app_module, monkeypatch):
    """The module has no `wMain` until a Wmain is built, and a message can be asked for
    before: Wmain.__init__ loads the key before it has a window."""
    assert "wMain" not in vars(app_module)
    put_on_top(app_module, monkeypatch, None)

    assert app_module.dialog_parent() is None


@pytest.mark.parametrize(
    "controller", [None, object(), types.SimpleNamespace()], ids=["none", "object", "empty"]
)
def test_a_wmain_stand_in_without_the_attributes_does_not_raise(
    app_module, monkeypatch, controller
):
    monkeypatch.setattr(app_module, "wMain", controller, raising=False)
    put_on_top(app_module, monkeypatch, None)

    assert app_module.dialog_parent() is None


def test_a_fallback_that_is_not_a_window_is_ignored(app_module, monkeypatch):
    """Tests hand over stand-ins, and a half-built Wmain may hold a widget not yet a window:
    each fallback is taken only if it is a Gtk.Window, so the next one is."""
    (main,) = windows(app_module, 1)
    not_a_window = object()
    put_on_top(app_module, monkeypatch, None)

    put_wmain(
        app_module,
        monkeypatch,
        wMain=main,
        window_in_use=not_a_window,
        console_windows=(not_a_window,),
    )
    assert app_module.dialog_parent() is main

    put_wmain(app_module, monkeypatch, wMain=not_a_window, window_in_use=None, console_windows=())
    assert app_module.dialog_parent() is None


def test_the_messages_are_shown_over_the_window_dialog_parent_names(app_module, monkeypatch):
    """What each helper hands GTK as the parent is the answer, with the caller's named
    window passed to it."""
    named, top = windows(app_module, 2)
    parents = []

    class Message:
        def __init__(self, **kwargs):
            parents.append(kwargs["parent"])

        def set_icon_from_file(self, *_args):
            pass

        def run(self):
            return 0

        def destroy(self):
            pass

    asked = []
    monkeypatch.setattr(app_module.Gtk, "MessageDialog", Message)
    monkeypatch.setattr(
        app_module, "dialog_parent", lambda preferred=None: asked.append(preferred) or top
    )

    app_module.msgbox("an error", named)
    app_module.msginfo("a notice", named)
    app_module.msgconfirm("a question")

    assert parents == [top, top, top]
    assert asked == [named, named, None]


# -- the stub's windows are what GTK has ------------------------------------------------


def window_of(app_module, kind, visible=True):
    """A window of the stub that answers as a real one does."""
    answers = {"get_window_type": lambda _self: kind, "get_visible": lambda _self: visible}
    return type("Window", (app_module.Gtk.Window,), answers)()


def grabbed_by(app_module, monkeypatch, widget):
    """GTK's grab held by `widget`, with the window types as plain names."""
    monkeypatch.setattr(app_module.Gtk, "grab_get_current", lambda: widget, raising=False)
    kinds = types.SimpleNamespace(TOPLEVEL="toplevel", POPUP="popup")
    monkeypatch.setattr(app_module.Gtk, "WindowType", kinds, raising=False)


def in_window(window):
    """A widget whose toplevel is `window`."""
    return types.SimpleNamespace(get_toplevel=lambda: window)


def test_the_modal_window_is_the_toplevel_of_the_widget_holding_the_grab(app_module, monkeypatch):
    dialog = window_of(app_module, "toplevel")
    grabbed_by(app_module, monkeypatch, in_window(dialog))

    assert app_module.modal_window() is dialog


@pytest.mark.parametrize(
    "grab",
    ["no grab", "a menu", "a hidden window", "no window"],
)
def test_there_is_no_modal_window_unless_a_visible_toplevel_holds_the_grab(
    app_module, monkeypatch, grab
):
    """A menu showing holds the grab too, in a window of its own that is no toplevel; and
    a widget with no window above it is its own toplevel."""
    held = {
        "no grab": None,
        "a menu": in_window(window_of(app_module, "popup")),
        "a hidden window": in_window(window_of(app_module, "toplevel", visible=False)),
        "no window": in_window(object()),
    }[grab]
    grabbed_by(app_module, monkeypatch, held)

    assert app_module.modal_window() is None


def test_the_fakes_offer_what_real_gtk_has():
    """conftest stubs gi, so a fake can offer what GTK lacks (#30, #41)."""
    gi = pytest.importorskip("gi", reason="PyGObject not available")
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    assert hasattr(Gtk, "grab_get_current")
    for name in ("get_window_type", "get_visible", "get_toplevel", "set_transient_for"):
        assert hasattr(Gtk.Window, name), f"Gtk.Window has no {name}"
    for name in ("set_icon_from_file", "run", "destroy"):
        assert hasattr(Gtk.MessageDialog, name), f"Gtk.MessageDialog has no {name}"
    for name in ("TOPLEVEL", "POPUP"):
        assert hasattr(Gtk.WindowType, name), f"Gtk.WindowType has no {name}"
