"""Reconstructing a readable transcript from a raw session recording.

A full-screen application redraws a viewport instead of emitting lines, so its raw
stream is mostly escape sequences -- measured at roughly 9% printable for a real
application. The content is all there, but recovering it means replaying the stream
the way a terminal would and keeping only what is new.

This module is the part of that which needs no terminal: restoring the write
boundaries a recording was made with, tracking which screen the stream is on, and
deciding what a new frame actually added. The emulator itself is a hidden
``Vte.Terminal`` driven by ``app.TranscriptReplayer``; keeping the decisions here
means they can be tested against captured frames without a display.

Two screens, two very different problems:

* On the **primary screen** VTE keeps scrollback, and scrollback already *is* the
  linear transcript -- measured, 25 lines fed through a 10-row terminal all read
  back. Nothing here is needed for it.
* On the **alternate screen** there is no scrollback. Every frame overwrites the
  last, so the only record of what scrolled past is the difference between one frame
  and the next. That is what :class:`ScreenTracker` is for.
"""

from __future__ import annotations

from pathlib import Path

# Both the switch sequences and the screen each selects. `?1049` is what anything
# modern sends; the older `?47`/`?1047` are here because pagers and vim still do.
_MARKERS = (
    (b"\x1b[?1049h", True),
    (b"\x1b[?1047h", True),
    (b"\x1b[?47h", True),
    (b"\x1b[?1049l", False),
    (b"\x1b[?1047l", False),
    (b"\x1b[?47l", False),
)
_LONGEST = max(len(sequence) for sequence, _ in _MARKERS)


# A frame reaches the terminal as a burst of writes, then a pause while the
# application waits for something to change. Measured over three recorded sessions the
# two are not close: within a burst the gaps were 0.06-1.65ms, between frames 50ms and
# up. Anything under this counts as the same frame.
FRAME_GAP = 0.008


def read_writes(raw_path: str, timing_path: str) -> list[tuple[float, bytes]]:
    """The writes the recorder made, as `(delay, bytes)`, from the `.timing` sidecar.

    Concatenated bytes have no frame boundaries. Reading a recording back in
    file-sized blocks collapses a whole full-screen session to its final screen --
    measured, 6 of 20 lines survived. The counts in the sidecar cut the stream back
    into the writes the child produced, and the delays say which of those belong to
    the same frame (#75).

    Missing, short or unreadable timing degrades to one undelimited chunk rather than
    raising. That is the pre-#75 recording, and it is honestly unreconstructable.
    """
    data = Path(raw_path).read_bytes()
    timings: list[tuple[float, int]] = []
    try:
        with Path(timing_path).open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                fields = line.split()
                if len(fields) == 2:
                    timings.append((float(fields[0]), int(fields[1])))
    except (OSError, ValueError):
        timings = []
    writes: list[tuple[float, bytes]] = []
    offset = 0
    for delay, count in timings:
        if count <= 0 or offset >= len(data):
            continue
        writes.append((delay, data[offset : offset + count]))
        offset += count
    # Anything the sidecar did not account for is still real output; a recording whose
    # timing file was truncated should lose its boundaries, not its bytes.
    if offset < len(data):
        writes.append((0.0, data[offset:]))
    return writes


def coalesce(writes: list[tuple[float, bytes]], gap: float = FRAME_GAP) -> list[bytes]:
    """Merge each burst of writes back into the frame the application drew.

    Sampling the screen once per write is what produces half-drawn frames: a frame
    arrives as several writes, so a sample between two of them catches a screen the
    user never saw. The recording says where the real boundaries are -- a burst is one
    frame, and the pause after it is the application waiting.

    This also cuts the work. Every frame costs a wait for VTE to settle, so replaying
    per frame rather than per write is the difference between one sample and several
    for the same screen; measured on a viewer redrawing at 20Hz, 18 writes became the
    11 frames it actually drew.
    """
    frames: list[bytes] = []
    for delay, chunk in writes:
        if frames and delay < gap:
            frames[-1] += chunk
        else:
            frames.append(chunk)
    return frames


class AltScreenScanner:
    """Cuts a stream into runs that stay on one screen, tagged with which screen.

    The switch has to be seen *before* it is fed to the terminal. Leaving the
    alternate screen destroys everything on it, so a replayer that feeds the whole
    chunk and then looks has already lost the last frame -- measured, that dropped the
    final 10 of 20 content lines. Each switch sequence therefore begins the run it
    switches into, which leaves the caller a moment, between two runs, when the
    terminal still holds the outgoing screen.

    Reading this from the bytes rather than from VTE is deliberate: it is exact, and
    VTE offers no signal for it.
    """

    def __init__(self) -> None:
        self.alternate = False
        self._pending = b""

    def split(self, chunk: bytes) -> list[tuple[bytes, bool]]:
        """Cut `chunk` into `(bytes, alternate)` runs, each on a single screen.

        A switch sequence straddling two writes is still caught: a trailing partial
        one is held back and reconsidered with the next chunk.
        """
        window = self._pending + chunk
        self._pending = b""
        runs: list[tuple[bytes, bool]] = []
        start = search = 0
        while True:
            found: tuple[int, int, bool] | None = None
            for sequence, screen in _MARKERS:
                at = window.find(sequence, search)
                if at != -1 and (found is None or at < found[0]):
                    found = (at, len(sequence), screen)
            if found is None:
                break
            at, length, screen = found
            search = at + length
            if screen == self.alternate:
                continue  # already there; not a switch
            runs.append((window[start:at], self.alternate))
            self.alternate = screen
            start = at
        rest = window[start:]
        held = self._partial_marker(rest)
        if held:
            self._pending = rest[len(rest) - held :]
            rest = rest[: len(rest) - held]
        runs.append((rest, self.alternate))
        return [(data, screen) for data, screen in runs if data]

    def close(self) -> list[tuple[bytes, bool]]:
        """Any held-back bytes, once there is nothing left to disambiguate them."""
        pending, self._pending = self._pending, b""
        return [(pending, self.alternate)] if pending else []

    @staticmethod
    def _partial_marker(data: bytes) -> int:
        """How many trailing bytes could still turn into a switch sequence."""
        for length in range(min(_LONGEST - 1, len(data)), 0, -1):
            tail = data[len(data) - length :]
            if any(sequence.startswith(tail) for sequence, _ in _MARKERS):
                return length
        return 0


def _blank(line: str) -> bool:
    return not line.strip()


def _rows(lines: list[str]) -> list[str]:
    return [line.rstrip() for line in lines]


def _trim(lines: list[str]) -> list[str]:
    """`lines` without the empty rows below its last row of text."""
    end = len(lines)
    while end and _blank(lines[end - 1]):
        end -= 1
    return list(lines[:end])


def scroll_shift(
    previous: list[str], current: list[str], min_band: int = 2
) -> tuple[int, int] | None:
    """How far `current` is `previous` scrolled up, and over which band of rows.

    Returns ``(shift, band_start)``, or ``None`` when no clean shift is found.

    A whole-screen shift is the wrong thing to look for. Real applications scroll a
    *sub-region*: a title stays put at the top, a status line and an input box stay put
    at the bottom, and only the band between them moves. Measured against a viewer with
    a title row, taking the whole screen emits the title once per frame instead of the
    content line that actually scrolled away.

    So for each candidate shift the rows that match are found, the longest unbroken run
    of them is taken as the scrolling band, and only that band is trusted. Rows that
    differ for reasons that are not new content -- a clock, a counter, a progress bar,
    a cursor -- simply fall outside the run and stop mattering.

    Blank rows match at every shift, so only rows of real text count towards a run, and
    a run has to carry at least `min_band` of them. One line matching by chance is not a
    shift: acting on a single match reports a scroll that never happened and emits rows
    nobody scrolled past. When nothing qualifies the answer is ``None``, and the caller
    emits nothing. That direction is deliberate. A transcript that repeats a
    status line every frame is worse than one that misses a line -- the first spike at
    this emitted 96 lines for 20 lines of content.
    """
    previous, current = _rows(previous), _rows(current)
    height = min(len(previous), len(current))
    if height == 0:
        return None
    best: tuple[int, int, int] | None = None
    for shift in range(0, height):
        run_start = run_length = run_text = 0
        start = length = text = 0
        for index in range(height - shift):
            if previous[index + shift] == current[index]:
                if length == 0:
                    start = index
                length += 1
                text += 0 if _blank(current[index]) else 1
                if text > run_text or (text == run_text and length > run_length):
                    run_start, run_length, run_text = start, length, text
            else:
                length = text = 0
        if run_text < min_band:
            continue
        # A tie goes to the smaller shift: it emits fewer lines, and over-emitting is
        # the failure mode that makes a transcript useless.
        if best is None or run_text > best[0]:
            best = (run_text, shift, run_start)
    if best is None:
        return None
    _, shift, band_start = best
    return None if shift == 0 else (shift, band_start)


def screen_replaced(
    previous: list[str],
    current: list[str],
    min_text: int = 3,
    max_overlap: float = 0.25,
) -> bool:
    """Whether `current` is a wholly different screen rather than a redraw of `previous`.

    A pager turning a page shares nothing with the frame it replaced, so there is no
    shift to find and everything that was on screen is simply gone. Emitting nothing
    there costs real content -- measured against `less`, 22 of 40 lines.

    The reason this can be told apart from a redraw is that a half-drawn frame is a
    *subset* of the frame that completes it, never a different screen. Measured over
    both corpora, on the shift-less transitions:

        mid-draw frame completing   overlap 1.00
        pager turning a page        overlap 0.00, 0.08

    So the test is a low overlap between the text rows of the two frames, with both
    sides required to hold real text -- which is also what keeps a screen being torn
    down, or one still blank, from counting as a page turn.
    """
    before = {line for line in _rows(previous) if not _blank(line)}
    after = {line for line in _rows(current) if not _blank(line)}
    if len(before) < min_text or len(after) < min_text:
        return False
    return len(before & after) / min(len(before), len(after)) <= max_overlap


class ScreenTracker:
    """Turns a sequence of alternate-screen frames into the lines that scrolled past.

    Fed every frame, it returns only what left the screen since the last one. What is
    still on screen has not been transcribed yet, so :meth:`flush` closes the record
    with the final frame -- that is what the session was showing when it ended, and it
    is also the whole answer for an application that never scrolled at all.
    """

    def __init__(self, min_band: int = 2) -> None:
        self._previous: list[str] | None = None
        self._min_band = min_band

    def feed(self, lines: list[str]) -> list[str]:
        """Return the lines that scrolled out of view when this frame arrived."""
        lines = _rows(lines)
        previous, self._previous = self._previous, lines
        if previous is None or previous == lines:
            return []
        found = scroll_shift(previous, lines, self._min_band)
        if found is not None:
            shift, band_start = found
            return previous[band_start : band_start + shift]
        if screen_replaced(previous, lines):
            return _trim(previous)
        return []

    def flush(self) -> list[str]:
        """The frame still on screen, with the empty rows below it dropped.

        What is still displayed has not been transcribed yet, so the record is only
        complete once it is added. It is also the entire answer for an application
        that drew one screen and never scrolled.
        """
        lines, self._previous = self._previous or [], None
        return _trim(lines)


class Transcript:
    """Collects the reconstructed lines, keeping the blank runs a replay produces sane.

    A screen is a fixed grid, so every harvest of one arrives padded with the empty
    rows below its content. Left alone those stack up into long gaps that make the
    result harder to read than it needs to be, so a run of them collapses to one and
    the ends are trimmed.
    """

    def __init__(self) -> None:
        self._lines: list[str] = []

    def extend(self, lines: list[str]) -> None:
        for line in lines:
            if _blank(line):
                if self._lines and not _blank(self._lines[-1]):
                    self._lines.append("")
            else:
                self._lines.append(line.rstrip())

    @property
    def lines(self) -> list[str]:
        return _trim(self._lines)

    def text(self) -> str:
        lines = self.lines
        return "\n".join(lines) + "\n" if lines else ""
