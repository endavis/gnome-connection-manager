"""Shared pytest fixtures for importing gnome_connection_manager without GTK."""

from __future__ import annotations

import importlib
import os
import shutil
import socket
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

# --- private display for the tests that drive real GTK -------------------------------
#
# A handful of tests deliberately spawn real Gtk/Vte windows and let them settle for a
# couple of seconds. On a live desktop -- WSLg in particular -- those windows map on the
# developer's screen and steal keyboard and pointer focus mid-run. Give them an Xvfb of
# their own instead: still a real X server driving real GTK, just not the one being
# looked at.
#
# This has to happen in pytest_configure, before collection: the tests gate themselves
# with @pytest.mark.skipif(not os.environ.get("DISPLAY")), which is evaluated at import
# time, so setting DISPLAY from a fixture would be too late to un-skip them.
#
# Set GCM_TEST_REAL_DISPLAY=1 to keep the real desktop, which is what you want when
# measuring against the compositor GCM actually ships on.

_XVFB_SCREEN = "1920x1080x24"
_xvfb_process = None


def _x_display_is_up(number):
    """True once display :number accepts a connection.

    Checks the abstract socket first. WSLg mounts /tmp/.X11-unix read-only, so Xvfb
    cannot create the filesystem socket there at all and only the abstract one appears;
    waiting for the path would wait forever. Xvfb's own -displayfd never reports back
    under that same condition, which is why readiness is probed rather than asked for.
    """
    for address in (f"\0/tmp/.X11-unix/X{number}", f"/tmp/.X11-unix/X{number}"):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(address)
            return True
        except OSError:
            continue
        finally:
            sock.close()
    return False


def _free_display():
    for number in range(90, 200):
        if Path(f"/tmp/.X{number}-lock").exists() or _x_display_is_up(number):
            continue
        return number
    return None


def _start_xvfb():
    """Spawn an Xvfb and return (process, display), or None if it cannot be used."""
    xvfb = shutil.which("Xvfb")
    if xvfb is None:
        return None
    number = _free_display()
    if number is None:
        return None
    try:
        process = subprocess.Popen(
            [xvfb, f":{number}", "-screen", "0", _XVFB_SCREEN, "-nolisten", "tcp"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if _x_display_is_up(number):
            return process, f":{number}"
        if process.poll() is not None:
            return None
        time.sleep(0.02)
    process.terminate()
    return None


def pytest_configure(config):
    global _xvfb_process
    if os.environ.get("GCM_TEST_REAL_DISPLAY"):
        return
    # Under xdist this hook runs in the controller and again in every worker. The
    # controller configures first and workers inherit its environment, so they already
    # have DISPLAY pointing at the server it started. Starting one per worker would be
    # wasteful, and worse: picking a free display number is a check followed by a bind,
    # so two workers racing can choose the same number, and the one that loses falls
    # back to the developer's real desktop -- the exact thing this exists to prevent.
    if os.environ.get("PYTEST_XDIST_WORKER"):
        return
    started = _start_xvfb()
    if started is None:
        # No Xvfb, or it failed to come up. Fall back to whatever display is already
        # there rather than turning a focus annoyance into a broken test run.
        return
    _xvfb_process, display = started
    os.environ["DISPLAY"] = display
    os.environ["GDK_BACKEND"] = "x11"
    # WSLg exports both, and GTK prefers Wayland whenever WAYLAND_DISPLAY is set, which
    # would send the windows straight back to the real desktop.
    os.environ.pop("WAYLAND_DISPLAY", None)
    # WSLg also exports GDK_SCALE=2.25. Wayland reports scale 1 and absorbs it, but on
    # X11 it is applied, so a 1920x1080 screen reports a 960x540 workarea and the
    # geometry assertions are measuring a screen that does not exist.
    os.environ.pop("GDK_SCALE", None)
    os.environ.pop("GDK_DPI_SCALE", None)


def pytest_unconfigure(config):
    global _xvfb_process
    if _xvfb_process is None:
        return
    _xvfb_process.terminate()
    try:
        _xvfb_process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _xvfb_process.kill()
    _xvfb_process = None


class DummyAttribute:
    """Generic attribute acting as callable, namespace, and GTK-compatible base."""

    def __init__(self):
        self._attrs: dict[str, DummyAttribute] = {}

    def __call__(self, *args, **kwargs):
        return self

    def __getattr__(self, name: str):
        attr = self._attrs.get(name)
        if attr is None:
            attr = DummyAttribute()
            self._attrs[name] = attr
        return attr

    def __setattr__(self, name: str, value):
        if name == "_attrs":
            super().__setattr__(name, value)
        else:
            self._attrs[name] = value

    def __or__(self, other):
        return self

    __ror__ = __or__

    def __mro_entries__(self, bases):
        return (object,)


class DummyModule(types.ModuleType):
    """Module whose attributes lazily materialize into DummyAttribute objects."""

    def __init__(self, name: str):
        super().__init__(name)
        self._attributes: dict[str, object] = {}

    def __getattr__(self, name: str):
        attr = self._attributes.get(name)
        if attr is None:
            attr = DummyAttribute()
            self._attributes[name] = attr
        return attr

    def __setattr__(self, name: str, value):
        if name in {"_attributes", "__name__", "__doc__"}:
            super().__setattr__(name, value)
        else:
            self._attributes[name] = value


def make_gtk_class(name: str):
    class _Widget:
        def __init__(self, *args, **kwargs):
            pass

        def set_transient_for(self, *_args, **_kwargs):
            pass

        def set_application(self, *_args, **_kwargs):
            pass

        def show_all(self):
            pass

        def present(self):
            pass

        # The dialog surface save_session_transcript drives. Every method here is
        # asserted against the real Gtk.Dialog in test_transcript.py -- a fake that
        # offers something GTK lacks is how #30 and #41 shipped.
        def set_icon_from_file(self, *_args, **_kwargs):
            pass

        def add_button(self, *_args, **_kwargs):
            pass

        def get_content_area(self):
            return _Widget()

        def pack_start(self, *_args, **_kwargs):
            pass

        def connect(self, *_args, **_kwargs):
            return 0

        def destroy(self):
            pass

    _Widget.__name__ = name
    return _Widget


class DummyMessageDialog:
    def __init__(self, *args, **kwargs):
        self.value = kwargs.get("text")

    def set_icon_from_file(self, *args, **_kwargs):
        pass

    def run(self):
        return 0

    def destroy(self):
        pass


class DummyBuilder:
    def set_translation_domain(self, *_args, **_kwargs):
        pass

    def expose_object(self, *_args, **_kwargs):
        pass

    def add_objects_from_file(self, *_args, **_kwargs):
        pass

    def get_object(self, *_args, **_kwargs):
        return make_gtk_class("GtkWidget")()


class DummyTerminal:
    def spawn_async(self, *args, **kwargs):
        pass

    def feed_child(self, *args, **kwargs):
        pass

    def feed_child_binary(self, *args, **kwargs):
        pass


class DummyRGBA:
    def __init__(self):
        self.red = 0
        self.green = 0
        self.blue = 0

    def to_color(self):
        return object()


@pytest.fixture
def app_module(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Import gnome_connection_manager.app with stubbed gi modules."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(os, "system", lambda *_args, **_kwargs: 0)

    fake_gi = types.ModuleType("gi")
    fake_gi.require_version = lambda *args, **kwargs: None
    repository = types.ModuleType("gi.repository")
    fake_gi.repository = repository

    gtk_module = DummyModule("Gtk")
    gtk_module.MessageDialog = DummyMessageDialog
    gtk_module.Builder = DummyBuilder
    gtk_module.Window = make_gtk_class("GtkWindow")
    gtk_module.Dialog = make_gtk_class("GtkDialog")
    gtk_module.Application = make_gtk_class("GtkApplication")
    gtk_module.HBox = make_gtk_class("GtkHBox")
    gtk_module.TextView = make_gtk_class("GtkTextView")
    gtk_module.CellEditable = make_gtk_class("GtkCellEditable")
    gtk_module.CellRendererText = make_gtk_class("GtkCellRendererText")
    gtk_module.ButtonsType = types.SimpleNamespace(OK=1, OK_CANCEL=2)
    gtk_module.MessageType = types.SimpleNamespace(ERROR=0, QUESTION=1)
    gtk_module.ResponseType = types.SimpleNamespace(OK=1, CANCEL=2)
    gtk_module.events_pending = lambda: False

    gdk_module = DummyModule("Gdk")
    gdk_module.ModifierType = types.SimpleNamespace(
        CONTROL_MASK=1, SHIFT_MASK=2, MOD1_MASK=4, SUPER_MASK=8
    )
    gdk_module.ScrollDirection = types.SimpleNamespace(
        UP=0, DOWN=1, LEFT=2, RIGHT=3, SMOOTH=4
    )
    gdk_module.RGBA = DummyRGBA
    gdk_module.Color = object
    gdk_module.keyval_name = lambda *_args, **_kwargs: "KEY"

    gio_module = DummyModule("Gio")
    glib_module = DummyModule("GLib")
    gobject_module = DummyModule("GObject")
    pango_module = DummyModule("Pango")

    vte_module = DummyModule("Vte")
    vte_module.Terminal = DummyTerminal
    vte_module.MAJOR_VERSION = 0
    vte_module.MINOR_VERSION = 60
    vte_module.PtyFlags = types.SimpleNamespace(DEFAULT=0)
    vte_module.Format = types.SimpleNamespace(TEXT=0, HTML=1)
    vte_module.EraseBinding = types.SimpleNamespace(AUTO=0, BS=1, DEL=2)

    class DummyRegex:
        @staticmethod
        def new_for_search(*_args, **_kwargs):
            return object()

        @staticmethod
        def new_for_match(*_args, **_kwargs):
            return object()

    vte_module.Regex = DummyRegex

    for name, module in {
        "Gtk": gtk_module,
        "Gdk": gdk_module,
        "Gio": gio_module,
        "GLib": glib_module,
        "GObject": gobject_module,
        "Pango": pango_module,
        "Vte": vte_module,
    }.items():
        setattr(repository, name, module)
        monkeypatch.setitem(sys.modules, f"gi.repository.{name}", module)

    monkeypatch.setitem(sys.modules, "gi", fake_gi)
    monkeypatch.setitem(sys.modules, "gi.repository", repository)

    sys.modules.pop("gnome_connection_manager.app", None)
    module = importlib.import_module("gnome_connection_manager.app")

    original_b64encode = module.base64.b64encode
    original_b64decode = module.base64.b64decode

    def compat_b64encode(data, *args, **kwargs):
        if isinstance(data, str):
            data = data.encode("latin1")
        return original_b64encode(data, *args, **kwargs)

    def compat_b64decode(data, *args, **kwargs):
        # Forward every argument: dropping them silently disabled validate=True for
        # any caller that asked for strict decoding, which is the kind of drift
        # between a fake and the real API that caused #30 and #41.
        return original_b64decode(data, *args, **kwargs)

    monkeypatch.setattr(module.base64, "b64encode", compat_b64encode)
    monkeypatch.setattr(module.base64, "b64decode", compat_b64decode)

    original_xor = module.xor

    def compat_xor(pw: str, str1):
        if isinstance(str1, bytes):
            str1 = str1.decode("latin1")
        return original_xor(pw, str1)

    monkeypatch.setattr(module, "xor", compat_xor)

    return module
