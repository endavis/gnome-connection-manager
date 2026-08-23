"""Extraction of OSC 52 clipboard writes from a terminal byte stream.

VTE does not implement OSC 52 -- verified on 0.76 by feeding the sequence to a live
terminal and seeing the clipboard untouched, and by the absence of any "52;" string in
libvte. There is also no API to observe unhandled OSC sequences, so the only way to
support it is to see the bytes before VTE does.

This module is the pure part of that: it holds no state beyond a partial-sequence
buffer and does no I/O, so it can be tested without a terminal, a display or a pty.
"""

from __future__ import annotations

import base64
import binascii

# ESC ] 52 ; <selection> ; <payload> (BEL | ESC \)
_INTRODUCER = b"\x1b]52;"
_BEL = b"\x07"
_ST = b"\x1b\\"

# A clipboard payload larger than this is not a paste, it is someone probing for a
# buffer bug. Real selections are far smaller, and refusing is safer than growing.
MAX_PAYLOAD = 1 << 20

# Selections this honours. "c" is the clipboard; "p" the primary selection. Cut buffers
# (s0-s7) are deliberately ignored: nothing mainstream writes them and each is one more
# thing a remote host can reach.
_SELECTIONS = {"c", "p"}


class Osc52Scanner:
    """Finds OSC 52 clipboard writes in a stream that arrives in arbitrary chunks.

    `feed` returns the completed writes in the chunk. Bytes are never modified or
    withheld -- the caller forwards the original chunk onward regardless. VTE ignores
    the sequence, so passing it through costs nothing and keeps this a pure observer.
    """

    def __init__(self, max_payload: int = MAX_PAYLOAD):
        self._pending = bytearray()
        self._max_payload = max_payload

    def feed(self, chunk: bytes) -> list[tuple[str, bytes]]:
        if not chunk:
            return []
        buffer = bytes(self._pending) + bytes(chunk)
        self._pending.clear()
        found: list[tuple[str, bytes]] = []

        while True:
            start = buffer.find(_INTRODUCER)
            if start == -1:
                # Keep only enough tail to recognise an introducer split across chunks.
                self._pending.extend(buffer[-(len(_INTRODUCER) - 1) :])
                return found
            body = buffer[start + len(_INTRODUCER) :]
            end, terminator = self._find_terminator(body)
            if end == -1:
                if len(body) > self._max_payload:
                    # Never completed and already too large: drop it and move on rather
                    # than buffer a remote host's output forever.
                    buffer = body
                    continue
                self._pending.extend(buffer[start:])
                return found
            write = self._parse(body[:end])
            if write is not None:
                found.append(write)
            buffer = body[end + len(terminator) :]

    @staticmethod
    def _find_terminator(body: bytes) -> tuple[int, bytes]:
        bel = body.find(_BEL)
        st = body.find(_ST)
        if bel == -1 and st == -1:
            return -1, b""
        if st == -1 or (bel != -1 and bel < st):
            return bel, _BEL
        return st, _ST

    def _parse(self, body: bytes) -> tuple[str, bytes] | None:
        separator = body.find(b";")
        if separator == -1:
            return None
        selection = body[:separator].decode("ascii", "replace") or "c"
        payload = body[separator + 1 :]
        # "?" is the read direction: it asks the terminal to send the clipboard back to
        # the application. Honouring it would let a remote host exfiltrate the local
        # clipboard, so it is ignored, as most terminals do.
        if payload.startswith(b"?"):
            return None
        if len(payload) > self._max_payload:
            return None
        target = next((s for s in selection if s in _SELECTIONS), None)
        if target is None:
            return None
        data = self._decode(payload)
        if data is None:
            return None
        return target, data

    @staticmethod
    def _decode(payload: bytes) -> bytes | None:
        """Strict base64 only.

        Deliberately redundant with the "?" refusal above: a lenient decode silently
        drops characters outside the alphabet, so b64decode(b"?QQ==") returns b"A" and
        a clipboard read would look like an ordinary write. Either layer alone refuses
        a query; both are kept so relaxing one does not open the other.
        """
        try:
            return base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError):
            return None
