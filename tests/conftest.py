"""Shared pytest fixtures for importing gnome_connection_manager without GTK."""

from __future__ import annotations

import importlib
import os
import sys
import types
from pathlib import Path

import pytest


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
    vte_module.Format = types.SimpleNamespace(TEXT=0)
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

    def compat_b64encode(data):
        if isinstance(data, str):
            data = data.encode("latin1")
        return original_b64encode(data)

    def compat_b64decode(data):
        result = original_b64decode(data)
        return result

    monkeypatch.setattr(module.base64, "b64encode", compat_b64encode)
    monkeypatch.setattr(module.base64, "b64decode", compat_b64decode)

    original_xor = module.xor

    def compat_xor(pw: str, str1):
        if isinstance(str1, bytes):
            str1 = str1.decode("latin1")
        return original_xor(pw, str1)

    monkeypatch.setattr(module, "xor", compat_xor)

    return module
