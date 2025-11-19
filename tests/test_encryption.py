"""Tests for encryption and helper utilities in app.py without GTK dependencies."""

from __future__ import annotations

import importlib
import os
import sys
import types
from pathlib import Path

import pyaes
import pytest


class DummyAttribute:
    """Generic attribute that can act as both callable and namespace."""

    def __call__(self, *args, **kwargs):
        return self

    def __getattr__(self, name):
        attr = DummyAttribute()
        setattr(self, name, attr)
        return attr

    def __or__(self, other):
        return self

    __ror__ = __or__

    def __mro_entries__(self, bases):
        return (object,)


class DummyModule(types.ModuleType):
    """Module whose unknown attributes resolve to DummyAttribute."""

    def __getattr__(self, name):
        attr = DummyAttribute()
        setattr(self, name, attr)
        return attr


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


DummyGtkWidget = make_gtk_class("GtkWidget")


class DummyMessageDialog:
    def __init__(self, *args, **kwargs):
        self.value = kwargs.get("text")

    def set_icon_from_file(self, *args, **kwargs):
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
        return DummyGtkWidget()


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

    class DummyRegex:
        @staticmethod
        def new_for_search(*args, **kwargs):
            return object()

        @staticmethod
        def new_for_match(*args, **kwargs):
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

    monkeypatch.setitem(sys.modules, "Gtk", gtk_module)

    sys.modules.pop("gnome_connection_manager.app", None)
    module = importlib.import_module("gnome_connection_manager.app")

    original_b64encode = module.base64.b64encode
    original_b64decode = module.base64.b64decode

    def compat_b64encode(data):
        if isinstance(data, str):
            data = data.encode("latin1")
        return original_b64encode(data)

    def compat_b64decode(data):
        return original_b64decode(data)

    monkeypatch.setattr(module.base64, "b64encode", compat_b64encode)
    monkeypatch.setattr(module.base64, "b64decode", compat_b64decode)

    original_xor = module.xor

    def compat_xor(pw: str, str1):
        if isinstance(str1, bytes):
            str1 = str1.decode("latin1")
        return original_xor(pw, str1)

    monkeypatch.setattr(module, "xor", compat_xor)

    return module


def test_password_to_key_returns_sha256_bytes(app_module):
    key = app_module._password_to_key("secret")
    assert len(key) == 32
    assert key == app_module._password_to_key("secret")


def test_pkcs7_pad_and_unpad_round_trip(app_module):
    data = b"1234567890abcdef"
    padded = app_module._pkcs7_pad(data)
    assert len(padded) == len(data) + 16
    assert app_module._pkcs7_unpad(padded) == data


def test_iter_blocks_splits_into_expected_chunks(app_module):
    data = b"abcdefghijklmnopqrstuvwxyz"
    blocks = list(app_module._iter_blocks(data, size=5))
    assert blocks == [b"abcde", b"fghij", b"klmno", b"pqrst", b"uvwxy", b"z"]


def test_generate_keystream_matches_ecb_output(app_module):
    key = b"\x00" * 32
    iv = b"\x01" * 16
    gen = app_module._generate_keystream(key, iv)
    ecb = pyaes.AESModeOfOperationECB(key)

    expected_first = ecb.encrypt(iv)
    expected_second = ecb.encrypt(expected_first)

    assert next(gen) == expected_first
    assert next(gen) == expected_second


def test_encrypt_decrypt_round_trip(app_module):
    app_module.conf.VERSION = 1
    ciphertext = app_module.encrypt("password", "hello world")
    assert ciphertext
    assert app_module.decrypt("password", ciphertext) == "hello world"


def test_decrypt_legacy_mode_uses_xor(app_module):
    app_module.conf.VERSION = 0
    legacy = app_module.encrypt_old("pw", "old-secret")
    assert app_module.decrypt("pw", legacy) == "old-secret"


def test_encrypt_old_decrypt_old_round_trip(app_module):
    secret = app_module.encrypt_old("pw", "value")
    assert secret
    assert app_module.decrypt_old("pw", secret) == "value"


def test_get_username_prefers_user_env(app_module, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("USER", "primary")
    monkeypatch.delenv("LOGNAME", raising=False)
    monkeypatch.delenv("USERNAME", raising=False)
    assert app_module.get_username() == "primary"


def test_get_password_combines_username_and_enc_passwd(app_module, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("USER", "acct")
    app_module.enc_passwd = "token"
    assert app_module.get_password() == "accttoken"


def test_load_encryption_key_reads_file_contents(app_module):
    key_path = Path(app_module.KEY_FILE)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text("stored-secret")
    app_module.enc_passwd = ""

    app_module.load_encryption_key()

    assert app_module.enc_passwd == "stored-secret"


def test_initialise_encryption_key_creates_file_with_permissions(app_module):
    key_path = Path(app_module.KEY_FILE)
    if key_path.exists():
        key_path.unlink()

    app_module.initialise_encyption_key()

    assert key_path.exists()
    contents = key_path.read_text()
    assert contents
    assert (key_path.stat().st_mode & 0o777) == 0o600


def test_xor_function_is_symmetric(app_module):
    source = "secret"
    encoded = "".join(app_module.xor("pw", source))
    decoded = "".join(app_module.xor("pw", encoded))
    assert decoded == source
