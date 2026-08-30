"""Tests for the key-file lifecycle and the config-aware crypto wrappers in app.py.

The primitives themselves moved to utils/crypto.py in #137 and are tested in
tests/test_crypto.py, without the `gi` stub. What stays here is what genuinely belongs
to the application: the passphrase file, and the `conf.VERSION` read that decides
whether a stored value is legacy.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from gnome_connection_manager.utils import crypto

if TYPE_CHECKING:
    import pytest


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


# -- the wrappers that keep conf out of utils/crypto.py (#137) --------------


def test_encrypt_decrypt_round_trip_through_the_wrappers(app_module, monkeypatch):
    monkeypatch.setattr(app_module.conf, "VERSION", 1)
    ciphertext = app_module.encrypt("password", "hello world")
    assert ciphertext
    assert app_module.decrypt("password", ciphertext) == "hello world"


def test_decrypt_takes_the_legacy_path_when_the_config_has_no_version(app_module, monkeypatch):
    """The end-to-end shape of #141: a version-less config holds XOR ciphertext.

    `conf.VERSION` defaults to the int 0 when the key is absent, which is exactly the
    population the legacy path exists to serve.
    """
    monkeypatch.setattr(app_module.conf, "VERSION", 0)
    assert app_module.decrypt("pw", "BhYcAhU=") == "value"


def test_decrypt_takes_the_aes_path_for_a_saved_config(app_module, monkeypatch):
    """A saved config holds the *string* "1", because CONFIG_OPTIONS declares it str.

    `"1" == 0` is False, so these users take the AES path. Pinning this stops the
    wrapper being "simplified" to a truthiness check, which would invert it.
    """
    monkeypatch.setattr(app_module.conf, "VERSION", "1")
    written = crypto.encrypt("pw", "secret")
    assert app_module.decrypt("pw", written) == "secret"
    assert app_module.decrypt("pw", "BhYcAhU=") != "value"


def test_decrypt_wrapper_forwards_the_version_flag(app_module, monkeypatch):
    """The wrapper's whole job, asserted directly rather than inferred from a result."""
    seen: dict[str, object] = {}

    def fake(passw, string, legacy=False):
        seen.update(passw=passw, string=string, legacy=legacy)
        return "sentinel"

    monkeypatch.setattr(app_module.crypto, "decrypt", fake)

    monkeypatch.setattr(app_module.conf, "VERSION", 0)
    assert app_module.decrypt("pw", "ct") == "sentinel"
    assert seen == {"passw": "pw", "string": "ct", "legacy": True}

    monkeypatch.setattr(app_module.conf, "VERSION", "1")
    app_module.decrypt("pw", "ct")
    assert seen["legacy"] is False


def test_the_remaining_crypto_callers_still_resolve_through_app(app_module):
    """The re-export footgun, narrowed to the callers that are still in app.py.

    `HostUtils` moved to utils/hosts.py in #138 and is no longer covered here -- it
    calls `crypto.encrypt` / `crypto.decrypt` module-qualified, so `crypto` is its patch
    point, not `app`. This test caught that move: it failed the moment the class left,
    which is what it is for. What remains are Wmain's import/export paths, which still
    resolve `encrypt` / `decrypt` through app's globals.
    """
    callers = (
        app_module.Wmain.on_importar_servidores1_activate,
        app_module.Wmain.on_exportar_servidores1_activate,
    )
    for caller in callers:
        func = getattr(caller, "__func__", caller)
        assert func.__globals__ is vars(app_module), (
            f"{func.__qualname__} no longer resolves encrypt/decrypt through app.py; "
            "repoint its patch points at the module it now reads them from"
        )


def test_hostutils_reads_crypto_from_its_own_module(app_module):
    """The other half: patching `app` must NOT be assumed to reach HostUtils any more.

    Asserted rather than left implicit, because the failure mode is a test that passes
    while testing nothing -- which is how #141 survived as long as it did.
    """
    from gnome_connection_manager.utils import hosts

    assert hosts.HostUtils.load_host_from_ini.__globals__ is not vars(app_module)
    assert hosts.HostUtils.load_host_from_ini.__globals__ is vars(hosts)


def test_patching_app_encrypt_intercepts_a_real_caller(app_module, monkeypatch):
    """The same property, exercised rather than inspected."""
    monkeypatch.setattr(app_module, "encrypt", lambda _pwd, value: f"stub:{value}")
    assert app_module.encrypt("pw", "x") == "stub:x"
