"""Password encryption for stored host entries.

AES-CTR over a PBKDF2-stretched key, with the pre-v2 formats kept readable: a
bare-SHA-256 key (no `_KDF_PREFIX`) and, before that, a repeating-key XOR. Neither
legacy format is written any more, only read, and both have to keep working -- the
passwords already in a user's gcm.conf were written with them.

Pure by design. Nothing here reads configuration, touches a widget or does I/O, so it
is tested directly rather than through the `gi` stub in tests/conftest.py. That
matters more here than elsewhere: the stub once hid the legacy XOR path failing
outright on Python 3 (#141).

`app.py` owns what is left out: the key file, the passphrase it holds, and the
`conf.VERSION` check that decides whether a value is legacy.
"""

from __future__ import annotations

import base64
import functools
import hashlib
import logging
import operator
import os

import pyaes

logger = logging.getLogger("gnome_connection_manager")


def xor(pw: str | bytes, data: str | bytes) -> bytes:
    """XOR `data` against a repeating `pw`, one byte at a time.

    Bytes rather than characters, because that is what the Python 2 original did and
    what the ciphertext in old configs was produced with: there `str` was `bytes`, so
    `ord`/`chr` walked octets. Running the same loop over Python 3 `str` indices XORs
    code points instead, which reads those files wrongly -- and raised outright once
    `base64.b64decode` started handing back `bytes` (#141).
    """
    key = pw.encode("utf-8") if isinstance(pw, str) else pw
    payload = data.encode("utf-8") if isinstance(data, str) else data
    if not key:
        # The Python 2 loop raised IndexError here. Reachable when the key file is
        # unreadable, since get_password() then returns "". Refuse rather than hand
        # back the payload unchanged.
        raise ValueError("empty key")
    return bytes(operator.xor(byte, key[i % len(key)]) for i, byte in enumerate(payload))


def encrypt_old(passw: str, string: str) -> str:
    """Encrypt a string using XOR (legacy method)."""
    try:
        return base64.b64encode(xor(passw, string)).decode("ascii")
    except (ValueError, TypeError, UnicodeError):
        logger.exception("Legacy encryption error")
        return ""


def decrypt_old(passw: str, string: str) -> str:
    """Decrypt a string using XOR (legacy method)."""
    try:
        plaintext = xor(passw, base64.b64decode(string))
    except (ValueError, TypeError, UnicodeError):
        logger.exception("Legacy decryption error")
        return ""
    try:
        return plaintext.decode("utf-8")
    except UnicodeDecodeError:
        # Written under a non-UTF-8 locale. latin1 cannot fail and gives back the
        # original octets, which beats discarding the password entirely.
        return plaintext.decode("latin1")


# Ciphertext written by this version carries this prefix. Anything without it predates
# the change and is keyed the old way -- see _password_to_key.
_KDF_PREFIX = "v2$"
_KDF_ITERATIONS = 600_000
_KDF_SALT_BYTES = 16

# One salt per process rather than per value. The secret is identical for every host, so a
# per-value salt buys nothing against the threat here -- someone who has taken both
# gcm.conf and the key file and is brute-forcing offline -- while costing a key derivation
# per host. With 51 hosts that is five seconds of startup; with one shared salt and the
# cache below it is one derivation.
_process_salt: bytes | None = None


def _session_salt() -> bytes:
    global _process_salt
    if _process_salt is None:
        _process_salt = os.urandom(_KDF_SALT_BYTES)
    return _process_salt


@functools.lru_cache(maxsize=8)
def _derive_key(secret: bytes, salt: bytes) -> bytes:
    """Stretch the secret into an AES key.

    PBKDF2 rather than a bare digest: the secret is the key file's contents joined to the
    username, and a single SHA-256 is fast enough to brute-force at hardware speed once
    someone has the files. Cached because every host in a config shares a salt, so a load
    derives once rather than once per host.
    """
    return hashlib.pbkdf2_hmac("sha256", secret, salt, _KDF_ITERATIONS, dklen=32)


def _password_to_key(secret: str | bytes) -> bytes:
    """The pre-v2 derivation. Kept to read what earlier versions wrote.

    Deliberately unchanged: values already in gcm.conf were keyed with it, and they have to
    stay readable until they are rewritten.
    """
    if isinstance(secret, str):
        secret = secret.encode("utf-8")
    return hashlib.sha256(secret).digest()


def _pkcs7_pad(data: bytes) -> bytes:
    pad_len = 16 - (len(data) % 16)
    if pad_len == 0:
        pad_len = 16
    return data + bytes([pad_len] * pad_len)


def _pkcs7_unpad(data: bytes) -> bytes:
    if not data:
        return data
    pad_len = data[-1]
    if pad_len < 1 or pad_len > 16:
        return data
    return data[:-pad_len]


def _iter_blocks(data: bytes, size: int = 16):
    for i in range(0, len(data), size):
        yield data[i : i + size]


def _generate_keystream(key: bytes, iv: bytes):
    ecb = pyaes.AESModeOfOperationECB(key)
    stream = iv
    while True:
        stream = ecb.encrypt(stream)
        yield stream


def encrypt(passw: str, string: str) -> str:
    """Encrypt a string using AES."""
    try:
        salt = _session_salt()
        key = _derive_key(passw.encode("utf-8"), salt)
        iv = os.urandom(16)
        plaintext = _pkcs7_pad(string.encode("utf-8"))
        keystream = _generate_keystream(key, iv)
        ciphertext = bytearray()
        for block in _iter_blocks(plaintext):
            stream_block = next(keystream)
            ciphertext.extend(bytes(b ^ s for b, s in zip(block, stream_block, strict=True)))
        return _KDF_PREFIX + base64.b64encode(salt + iv + ciphertext).decode("ascii")
    except Exception:
        logger.exception("AES encryption error")
        return ""


def decrypt(passw: str, string: str, legacy: bool = False) -> str:
    """Decrypt a string using AES, or legacy XOR when `legacy` is set.

    The caller decides which: the flag stands in for `conf.VERSION == 0`, which is
    configuration and stays in app.py so that nothing here has to read it.
    """
    try:
        if legacy:
            return decrypt_old(passw, string)
        if string.startswith(_KDF_PREFIX):
            data = base64.b64decode(string[len(_KDF_PREFIX) :])
            if len(data) <= _KDF_SALT_BYTES + 16:
                return ""
            salt = data[:_KDF_SALT_BYTES]
            iv = data[_KDF_SALT_BYTES : _KDF_SALT_BYTES + 16]
            ciphertext = data[_KDF_SALT_BYTES + 16 :]
            key = _derive_key(passw.encode("utf-8"), salt)
        else:
            # Written before the prefix existed, so keyed with the bare digest. Reading it
            # is the whole point of the prefix; it is rewritten in the new form the next
            # time the config is saved.
            data = base64.b64decode(string)
            if len(data) <= 16:
                return ""
            iv, ciphertext = data[:16], data[16:]
            key = _password_to_key(passw)
        keystream = _generate_keystream(key, iv)
        plaintext = bytearray()
        for block in _iter_blocks(ciphertext):
            stream_block = next(keystream)
            plaintext.extend(bytes(b ^ s for b, s in zip(block, stream_block, strict=True)))
        return _pkcs7_unpad(bytes(plaintext)).decode("utf-8")
    except Exception:
        logger.exception("AES decryption error")
        return ""
