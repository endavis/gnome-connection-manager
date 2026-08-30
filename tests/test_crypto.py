"""Tests for utils/crypto.py, exercised directly rather than through app.py.

No `app_module` fixture and no import of `app` anywhere in this file, so nothing here
runs against the `gi` stub in conftest.py. That is the point of the extraction (#137):
the stub previously hid the legacy XOR path failing outright on Python 3 (#141), and a
pure module cannot be hidden that way.
"""

from __future__ import annotations

import base64
import os

import pyaes
import pytest

from gnome_connection_manager.utils import crypto


def test_module_imports_without_gtk():
    """The property the extraction exists to buy.

    `sys.modules` must not have acquired `gi` from importing this module; if it ever
    does, the module has grown a dependency it was moved out to avoid.
    """
    import sys

    assert "gi" not in sys.modules or sys.modules["gi"].__class__.__name__ != "FakeGi"
    assert not hasattr(crypto, "Gtk")
    assert not hasattr(crypto, "conf")


# -- the primitives ---------------------------------------------------------


def test_password_to_key_returns_sha256_bytes():
    key = crypto._password_to_key("secret")
    assert len(key) == 32
    assert key == crypto._password_to_key("secret")


def test_pkcs7_pad_and_unpad_round_trip():
    data = b"1234567890abcdef"
    padded = crypto._pkcs7_pad(data)
    assert len(padded) == len(data) + 16
    assert crypto._pkcs7_unpad(padded) == data


def test_iter_blocks_splits_into_expected_chunks():
    data = bytes(range(40))
    blocks = list(crypto._iter_blocks(data))
    assert [len(b) for b in blocks] == [16, 16, 8]
    assert b"".join(blocks) == data


def test_generate_keystream_matches_ecb_output():
    key = b"0123456789abcdef"
    iv = b"fedcba9876543210"
    gen = crypto._generate_keystream(key, iv)

    ecb = pyaes.AESModeOfOperationECB(key)
    expected_first = ecb.encrypt(iv)
    expected_second = ecb.encrypt(expected_first)

    assert next(gen) == expected_first
    assert next(gen) == expected_second


def test_encrypt_decrypt_round_trip():
    ciphertext = crypto.encrypt("password", "hello world")
    assert ciphertext
    assert crypto.decrypt("password", ciphertext) == "hello world"


def test_xor_function_is_symmetric():
    source = "secret"
    encoded = crypto.xor("pw", source)
    decoded = crypto.xor("pw", encoded)
    assert isinstance(encoded, bytes)
    assert decoded.decode("utf-8") == source


def test_xor_rejects_an_empty_key():
    """get_password() returns "" when the key file is unreadable.

    The Python 2 loop raised IndexError there. Returning the payload unchanged would
    hand back the plaintext, so this refuses instead.
    """
    with pytest.raises(ValueError, match="empty key"):
        crypto.xor("", "secret")


# -- the legacy XOR path on Python 3 (#141) ---------------------------------
#
# These fixtures were computed independently of the implementation, by transcribing the
# Python 2 original and running it over byte strings. They are the compatibility
# contract: decrypt_old has to read what the Python 2 build wrote into gcm.conf.

LEGACY_FIXTURES = (
    ("pw", "value", "BhYcAhU="),
    ("pw", "señor", "AxKzxh8F"),
    ("k3y", "s3cr3t-p@ss", "GAAaGQANRkM5GEA="),
)


@pytest.mark.parametrize(("passw", "plaintext", "ciphertext"), LEGACY_FIXTURES)
def test_decrypt_old_reads_python2_ciphertext(passw, plaintext, ciphertext):
    assert crypto.decrypt_old(passw, ciphertext) == plaintext


@pytest.mark.parametrize(("passw", "plaintext", "ciphertext"), LEGACY_FIXTURES)
def test_encrypt_old_reproduces_python2_ciphertext(passw, plaintext, ciphertext):
    assert crypto.encrypt_old(passw, plaintext) == ciphertext


def test_legacy_path_is_utf8_not_latin1():
    """The discriminating case, and the reason latin1 is the wrong choice.

    Python 2 GTK handed back UTF-8 encoded str, so a non-ASCII password was XORed as
    its UTF-8 octets. Encoding it latin1 instead gives a shorter payload and different
    ciphertext, so a latin1 implementation would read old configs wrongly while still
    passing an ASCII-only round-trip test.
    """
    assert crypto.encrypt_old("pw", "señor") == "AxKzxh8F"
    assert crypto.encrypt_old("pw", "señor") != "Axjxxg=="


def test_decrypt_old_falls_back_to_latin1_on_undecodable_bytes():
    """Recover the octets rather than discard the password.

    A build under a non-UTF-8 locale could write bytes that are not valid UTF-8.
    """
    raw = bytes([0xFF, 0xFE, 0x41])
    key = b"pw"
    scrambled = bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))
    ciphertext = base64.b64encode(scrambled).decode("ascii")
    assert crypto.decrypt_old("pw", ciphertext) == raw.decode("latin1")


def test_decrypt_takes_the_legacy_path_only_when_asked():
    """The `legacy` flag replaces the `conf.VERSION` read that stayed in app.py."""
    assert crypto.decrypt("pw", "BhYcAhU=", legacy=True) == "value"
    assert crypto.decrypt("pw", "BhYcAhU=") != "value"


# -- the KDF migration (#117) -----------------------------------------------


def _legacy_ciphertext(passw: str, plaintext: str) -> str:
    """Reproduce exactly what the pre-v2 code wrote: no prefix, key = bare SHA-256."""
    key = crypto._password_to_key(passw)
    iv = os.urandom(16)
    padded = crypto._pkcs7_pad(plaintext.encode("utf-8"))
    keystream = crypto._generate_keystream(key, iv)
    out = bytearray()
    for block in crypto._iter_blocks(padded):
        out.extend(bytes(b ^ s for b, s in zip(block, next(keystream), strict=True)))
    return base64.b64encode(iv + bytes(out)).decode("ascii")


def test_a_password_saved_by_the_old_code_still_decrypts():
    """The reason this needed a format change rather than a swap.

    Every password already in a user's gcm.conf was keyed with a bare SHA-256. Changing
    the derivation without keeping this path would have made all of them unreadable.
    """
    legacy = _legacy_ciphertext("pw", "old-secret")

    assert not legacy.startswith(crypto._KDF_PREFIX)
    assert crypto.decrypt("pw", legacy) == "old-secret"


def test_new_ciphertext_is_marked_and_round_trips():
    written = crypto.encrypt("pw", "new-secret")

    assert written.startswith(crypto._KDF_PREFIX), "new values must be self-describing"
    assert crypto.decrypt("pw", written) == "new-secret"


def test_the_new_form_is_not_keyed_with_the_bare_digest():
    """The point of the change: the same secret must no longer produce the old key."""
    written = crypto.encrypt("pw", "secret")
    raw = base64.b64decode(written[len(crypto._KDF_PREFIX) :])
    salt = raw[: crypto._KDF_SALT_BYTES]

    assert crypto._derive_key(b"pw", salt) != crypto._password_to_key("pw")


def test_the_wrong_password_does_not_decrypt():
    written = crypto.encrypt("right", "secret")

    assert crypto.decrypt("wrong", written) != "secret"


def test_every_value_in_one_config_shares_a_salt():
    """A per-value salt would cost a key derivation per host: 51 hosts, five seconds.

    One salt per process keeps that to a single derivation while still defeating a
    precomputed table, which is what the salt is for here.
    """
    salts = {
        base64.b64decode(crypto.encrypt("pw", f"secret-{i}")[len(crypto._KDF_PREFIX) :])[
            : crypto._KDF_SALT_BYTES
        ]
        for i in range(5)
    }
    assert len(salts) == 1
