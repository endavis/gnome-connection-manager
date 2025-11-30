"""Tests for encryption and helper utilities in app.py without GTK dependencies."""

from __future__ import annotations

from pathlib import Path

import pyaes
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
