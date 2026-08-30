"""Tests for encryption and helper utilities in app.py without GTK dependencies."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pyaes

if TYPE_CHECKING:
    import pytest


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


# -- the KDF migration (#117) -----------------------------------------------


def _legacy_ciphertext(app_module, passw: str, plaintext: str) -> str:
    """Reproduce exactly what the pre-v2 code wrote: no prefix, key = bare SHA-256."""
    import base64
    import os

    key = app_module._password_to_key(passw)
    iv = os.urandom(16)
    padded = app_module._pkcs7_pad(plaintext.encode("utf-8"))
    keystream = app_module._generate_keystream(key, iv)
    out = bytearray()
    for block in app_module._iter_blocks(padded):
        out.extend(bytes(b ^ s for b, s in zip(block, next(keystream), strict=True)))
    return base64.b64encode(iv + bytes(out)).decode("ascii")


def test_a_password_saved_by_the_old_code_still_decrypts(app_module, monkeypatch):
    """The reason this needed a format change rather than a swap.

    Every password already in a user's gcm.conf was keyed with a bare SHA-256. Changing
    the derivation without keeping this path would have made all of them unreadable.
    """
    monkeypatch.setattr(app_module.conf, "VERSION", 1)
    legacy = _legacy_ciphertext(app_module, "pw", "old-secret")

    assert not legacy.startswith(app_module._KDF_PREFIX)
    assert app_module.decrypt("pw", legacy) == "old-secret"


def test_new_ciphertext_is_marked_and_round_trips(app_module, monkeypatch):
    monkeypatch.setattr(app_module.conf, "VERSION", 1)
    written = app_module.encrypt("pw", "new-secret")

    assert written.startswith(app_module._KDF_PREFIX), "new values must be self-describing"
    assert app_module.decrypt("pw", written) == "new-secret"


def test_the_new_form_is_not_keyed_with_the_bare_digest(app_module):
    """The point of the change: the same secret must no longer produce the old key."""
    import base64

    written = app_module.encrypt("pw", "secret")
    raw = base64.b64decode(written[len(app_module._KDF_PREFIX) :])
    salt = raw[: app_module._KDF_SALT_BYTES]

    assert app_module._derive_key(b"pw", salt) != app_module._password_to_key("pw")


def test_the_wrong_password_does_not_decrypt(app_module, monkeypatch):
    monkeypatch.setattr(app_module.conf, "VERSION", 1)
    written = app_module.encrypt("right", "secret")

    assert app_module.decrypt("wrong", written) != "secret"


def test_every_value_in_one_config_shares_a_salt(app_module):
    """A per-value salt would cost a key derivation per host: 51 hosts, five seconds.

    One salt per process keeps that to a single derivation while still defeating a
    precomputed table, which is what the salt is for here.
    """
    import base64

    salts = {
        base64.b64decode(app_module.encrypt("pw", f"secret-{i}")[len(app_module._KDF_PREFIX) :])[
            : app_module._KDF_SALT_BYTES
        ]
        for i in range(5)
    }

    assert len(salts) == 1
