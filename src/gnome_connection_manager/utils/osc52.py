"""Extraction of OSC 52 clipboard writes from a terminal byte stream.

VTE does not implement OSC 52 -- verified on 0.76 by feeding the sequence to a live
terminal and seeing the clipboard untouched, and by the absence of any "52;" string in
libvte. There is also no API to observe unhandled OSC sequences, so the only way to
support it is to see the bytes before VTE does.

This module is the pure part of that. It reads no clock, and does no I/O bar `kernel_release`
and `wslg_folder`, which look at the two places that say a system is WSLg, so it can be tested
without a terminal, a display or a pty. `Osc52Scanner` holds a partial-sequence buffer.
`RepeatFilter` is GCM's side of the relay, and holds the last write it let through.
`ClipboardWatch` holds the last write GCM set until the compositor has asked for its text, so
that GCM can set it again, and `under_wslg` says where that applies (#412, #413).
"""

from __future__ import annotations

import base64
import binascii
from pathlib import Path

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

# A write of the text just put on the clipboard, less than this many seconds after it, is
# the second of a pair and not a new copy (#393). The pairs measured came 3.4 ms apart, or
# in one read. A second leaves room for a main loop that stalls or a slow link, and is
# shorter than a person takes to copy elsewhere and then copy again; that last is an
# estimate, not a measurement.
REPEAT_WINDOW = 1.0

# A write that Weston ignored is set again at a change of the keyboard's window, and at most
# this many sets are made of one write, the first included (#412, #413). A bound on the
# repairs, not a measured figure: the prototype's repairs were taken at the first.
MAX_SETS = 3

# Seconds that must pass after a set, a write's or a repair's, before the next repair. Not a
# measured threshold: about five times the longest wait measured from a set to the
# compositor's request for its text, 52.9 ms. Two reasons for it, inferred and neither seen.
# The keyboard moving between two GCM windows gives two FOCUS_CHANGEs back to back, and if
# they were read together both would set with the serial GDK read last, so the second set
# would be ignored, as in #413. And GDK reads a batch of Wayland events, which advances its
# serial, and hands the events out one at a time, so a write applied in between takes the
# serial of an `enter` or `leave` not yet handed out, and a repair at that event would set
# with the same serial.
REPAIR_GAP = 0.25

# What says that GCM is under WSLg: a Wayland display, a kernel that names Microsoft, and the
# folder WSLg mounts (#412, #413).
WAYLAND_DISPLAY_TYPE = "GdkWaylandDisplay"
KERNEL_RELEASE_FILE = "/proc/sys/kernel/osrelease"
WSLG_FOLDER = "/mnt/wslg"


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


class RepeatFilter:
    """Tells the second write of a pair from a new copy (#393).

    A program in a tab can write its copy twice, once for the target "" and once for "c",
    and the scanner reads both as the clipboard. Set twice, the second set follows no input
    that GCM received. Weston ignores such a set without a word to GTK, which then goes on
    answering a paste with GCM's text and not with what was copied elsewhere since. So a
    write of the text last let through, less than `window` seconds before, is a repeat, and
    is left out.

    The window runs from the write let through, and a repeat does not renew it. Otherwise a
    program that wrote one text every 0.6 s would be left out for good, and a copy that is
    meant to put things right would never get through. The text is the whole key: the
    scanner reads the pair's "" as "c", so both writes arrive alike, target and all.

    The time is an argument, as `QuietWatch`'s is.
    """

    def __init__(self, window: float = REPEAT_WINDOW) -> None:
        self._window = window
        self._last: tuple[str, float] | None = None

    def repeated(self, text: str, now: float) -> bool:
        """Whether `text` is what was let through less than the window before `now`.

        Anything else is let through, and is what the next write is compared with.
        """
        last = self._last
        if last is not None and last[0] == text and now - last[1] < self._window:
            return True
        self._last = (text, now)
        return False


class ClipboardWatch:
    """The last write GCM set on the clipboard, until the compositor has asked for it (#412, #413).

    Under WSLg, Weston ignores a set of the clipboard whose serial is not newer than the
    selection's, equal included, and sends no `cancelled`. GTK sets each new data source with
    the serial of the last input GCM saw, so a write that follows a copy made in Windows, or
    follows another write, with no input to GCM between, was ignored. GTK then claimed a
    clipboard that Weston did not hold, and went on answering a paste with the write while
    Windows held the older text. GCM cannot make a serial of its own.

    A set Weston takes is followed by a request for the text, which GDK hands GCM as a
    SELECTION_REQUEST for the clipboard. Measured on WSLg 1.0.73.2 (Weston 9.0.0), of 22 sets
    the 13 Weston took each got exactly one, 0.1 to 5.4 ms after the first `send`, which came
    8.5 to 48.4 ms after the set; the 9 it ignored got none. Each of 25 `enter` and `leave`
    events was followed by exactly one FOCUS_CHANGE, the last within 0.675 ms, and the first
    after a copy made in Windows carried a serial newer than the copy's. So `again` gives the
    write at a change of the keyboard's window if it has not been heard (`heard`, called at
    that request, or at a SELECTION_CLEAR for the clipboard, which ends the claim).

    Not at a key or a click: GTK handles the event first, and a copy GCM makes at that key
    or click is set with its serial and taken, where a repair at the same event would destroy
    that source and set the older text with the same serial, which Weston ignores. That is
    reasoned from the mechanism and from #393's pair, not run.

    One mechanism ends the repairs, the count: `again` gives nothing once `max_sets` sets of
    the write were made, the first included, and nothing within `gap` seconds of the last
    set, a write's or a repair's. A newer write replaces the one held and starts the count
    again. The time is an argument, as `RepeatFilter`'s is.
    """

    def __init__(self, max_sets: int = MAX_SETS, gap: float = REPAIR_GAP) -> None:
        self._max_sets = max_sets
        self._gap = gap
        # The text, the sets made of it, and the time of the last.
        self._held: tuple[str, int, float] | None = None

    def made(self, text: str, now: float) -> None:
        """Hold `text`, which GCM has just set at `now`: one set made."""
        self._held = (text, 1, now)

    def heard(self) -> None:
        """Forget the write: the compositor asked for it, or the claim ended."""
        self._held = None

    def again(self, now: float) -> str | None:
        """The text to set again at a change of the keyboard's window at `now`, or None.

        None with nothing held, then once `max_sets` sets were made, then less than `gap`
        seconds after the last. The write stays held in each case. A text given counts as a
        set, made at `now`.
        """
        held = self._held
        if held is None:
            return None
        text, sets, last = held
        if sets >= self._max_sets:
            return None
        if now - last < self._gap:
            return None
        self._held = (text, sets + 1, now)
        return text


def under_wslg(display_type: str, kernel_release: str, wslg_folder: bool) -> bool:
    """Whether GCM runs under WSLg, whose Weston is the compositor measured (#412, #413).

    A Wayland display, `GdkWaylandDisplay` exactly; a kernel release that names Microsoft,
    in any case, as `6.18.33.2-microsoft-standard-WSL2` and `4.4.0-19041-Microsoft` do; and
    the folder WSLg mounts. All three, since a miss costs nothing and a false hit costs a
    set again at changes of the keyboard's window (#392 records that WSL cannot be told
    reliably).
    """
    return (
        display_type == WAYLAND_DISPLAY_TYPE
        and "microsoft" in kernel_release.lower()
        and wslg_folder
    )


def kernel_release(path: str | Path = KERNEL_RELEASE_FILE) -> str:
    """The kernel's release, as `uname -r` gives it: stripped, or "" where it cannot be read."""
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return ""


def wslg_folder(path: str | Path = WSLG_FOLDER) -> bool:
    """Whether the folder WSLg mounts is there. A file of that name is not it."""
    try:
        return Path(path).is_dir()
    except OSError:
        return False
