"""Rebuilding a readable transcript from a raw recording (#70).

The numbers quoted here were measured by replaying real recordings -- made through
`relay.py` itself -- through a hidden `Vte.Terminal`. They are what the heuristics in
`utils/transcript.py` were tuned against, so they are worth keeping honest.
"""

from __future__ import annotations

import gettext
import inspect
import json
import os
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest

from gnome_connection_manager.utils.transcript import (
    AltScreenScanner,
    ScreenTracker,
    Transcript,
    coalesce,
    read_writes,
    screen_replaced,
    scroll_shift,
)
from tests.test_connections import glib_complaints

# -- restoring the writes a recording was made with ---------------------------


def write_recording(tmp_path, writes, timing=True):
    raw = tmp_path / "s.raw"
    raw.write_bytes(b"".join(chunk for _, chunk in writes))
    sidecar = tmp_path / "s.timing"
    if timing:
        sidecar.write_text("".join(f"{delay:.6f} {len(chunk)}\n" for delay, chunk in writes))
    return str(raw), str(sidecar)


def test_read_writes_restores_the_original_chunks(tmp_path):
    """The boundaries are what separate one frame from the next."""
    writes = [(0.0, b"frame one"), (0.05, b"frame two"), (0.05, b"frame three")]

    assert read_writes(*write_recording(tmp_path, writes)) == writes


def test_read_writes_without_timing_gives_one_undelimited_chunk(tmp_path):
    """A pre-#75 recording has no sidecar, and its boundaries are not recoverable."""
    raw, sidecar = write_recording(tmp_path, [(0.0, b"ab"), (0.1, b"cd")], timing=False)

    assert read_writes(raw, sidecar) == [(0.0, b"abcd")]


def test_read_writes_keeps_bytes_a_truncated_sidecar_never_accounted_for(tmp_path):
    """A cut-short timing file should cost boundaries, not content."""
    raw, sidecar = write_recording(tmp_path, [(0.0, b"aa"), (0.1, b"bbbb")])
    (tmp_path / "s.timing").write_text("0.000000 2\n")

    assert read_writes(raw, sidecar) == [(0.0, b"aa"), (0.0, b"bbbb")]


# -- a frame is a burst of writes, not one write ------------------------------


def test_coalesce_merges_a_burst_into_the_frame_it_drew():
    """Sampling per write catches screens half drawn; the pause is the frame boundary."""
    writes = [(0.0, b"top"), (0.0001, b"body"), (0.05, b"next"), (0.0002, b"more")]

    assert coalesce(writes) == [b"topbody", b"nextmore"]


def test_coalesce_keeps_writes_the_application_paused_between():
    writes = [(0.0, b"one"), (0.05, b"two"), (0.05, b"three")]

    assert coalesce(writes) == [b"one", b"two", b"three"]


# -- which screen the stream is on --------------------------------------------


def test_scanner_starts_each_run_with_the_sequence_that_switched_to_it():
    """Leaving the alternate screen destroys it, so the switch must not be fed early.

    The last frame has to be taken in the gap between two runs, while the terminal
    still holds the outgoing screen. Measured, taking it after feeding the switch lost
    the final 10 of 20 content lines.
    """
    scanner = AltScreenScanner()

    runs = scanner.split(b"shell\x1b[?1049hALT\x1b[?1049lback")

    assert runs == [
        (b"shell", False),
        (b"\x1b[?1049hALT", True),
        (b"\x1b[?1049lback", False),
    ]


def test_scanner_sees_a_switch_split_across_two_writes():
    """A sequence straddling a write boundary is still a switch."""
    scanner = AltScreenScanner()

    first = scanner.split(b"before\x1b[?10")
    second = scanner.split(b"49hafter")

    assert first == [(b"before", False)]
    assert second == [(b"\x1b[?1049hafter", True)]
    assert scanner.alternate is True


def test_scanner_holds_nothing_back_that_cannot_become_a_switch():
    scanner = AltScreenScanner()

    assert scanner.split(b"plain output\n") == [(b"plain output\n", False)]
    assert scanner.close() == []


@pytest.mark.parametrize("sequence", [b"\x1b[?1049h", b"\x1b[?1047h", b"\x1b[?47h"])
def test_scanner_knows_the_older_switch_sequences_too(sequence):
    """Pagers and vim still send `?47`/`?1047`."""
    scanner = AltScreenScanner()

    scanner.split(b"x" + sequence + b"y")

    assert scanner.alternate is True


def test_scanner_ignores_a_switch_to_the_screen_it_is_already_on():
    scanner = AltScreenScanner()

    runs = scanner.split(b"a\x1b[?1049hb\x1b[?1049hc")

    assert runs == [(b"a", False), (b"\x1b[?1049hb\x1b[?1049hc", True)]


# -- the heuristic: what a new frame actually added ---------------------------

HEADER = "== VIEWER =="


def viewer(first, status):
    """A frame shaped like a real full-screen application: fixed title, live status."""
    body = [f"content line {n:02d}" for n in range(first, first + 4)]
    return [HEADER, *body, status]


def test_scroll_shift_finds_the_band_that_moved_not_the_whole_screen():
    """A title stays put and a status line changes; only the middle scrolls.

    Taking the whole screen instead emits the title once per frame -- the header is
    what a whole-screen shift reports as having scrolled away, rather than the content
    line that actually did.
    """
    before = viewer(1, "tick 000")
    after = viewer(2, "tick 001")

    assert scroll_shift(before, after) == (1, 1)


def test_scroll_shift_reports_nothing_when_only_a_status_line_changed():
    """A clock differing between frames is not new content."""
    before = viewer(1, "tick 000")
    after = viewer(1, "tick 001")

    assert scroll_shift(before, after) is None


def test_scroll_shift_handles_more_than_one_line_at_a_time():
    """Two frames can land in one write, so the shift is not always one row."""
    assert scroll_shift(viewer(1, "a"), viewer(3, "b")) == (2, 1)


def test_scroll_shift_will_not_invent_a_scroll_from_one_matching_line():
    """One line matching by chance is not a shift, and acting on it emits fiction.

    Here nothing scrolled -- the screen was replaced -- but `match` happens to land two
    rows up. Taking that as evidence reports a two-line scroll and emits `p` and `q`,
    which were never scrolled past, and prevents the page-turn rule that would have
    recovered the screen properly.
    """
    before = ["p", "q", "match", "r"]
    after = ["match", "s", "t", "u"]

    assert scroll_shift(before, after) is None
    assert scroll_shift(before, after, min_band=1) == (2, 0), "without the guard, fiction"


def test_scroll_shift_will_not_take_blank_rows_as_evidence():
    """Blank rows match at every shift, so a near-empty screen must not look scrolled."""
    before = ["only line", "", "", ""]
    after = ["", "", "", ""]

    assert scroll_shift(before, after) is None


def test_scroll_shift_ignores_a_frame_that_is_still_being_drawn():
    """A half-drawn frame is a prefix of the one that completes it, not a scroll."""
    complete = viewer(1, "tick 000")
    partial = complete[:-1] + [""]

    assert scroll_shift(partial, complete) is None


# -- the page turn, where emitting nothing costs real content -----------------


def test_screen_replaced_recognises_a_pager_turning_a_page():
    """Measured against `less`: overlap 0.00 and 0.08 on the two page turns."""
    before = [f"pager line {n:02d}" for n in range(1, 9)]
    after = [f"pager line {n:02d}" for n in range(20, 28)]

    assert screen_replaced(before, after) is True


def test_screen_replaced_is_false_for_a_frame_completing():
    """Measured overlap 1.00 -- a half-drawn frame is a subset, never a new screen."""
    complete = [f"line {n}" for n in range(1, 9)]
    partial = complete[:5] + ["", "", ""]

    assert screen_replaced(partial, complete) is False


def test_screen_replaced_is_false_while_a_screen_is_being_torn_down():
    """Leaving the alternate screen blanks it; that is not a page of content."""
    assert screen_replaced([f"line {n}" for n in range(6)], ["", "", ""]) is False


def test_screen_replaced_needs_real_text_on_both_sides():
    """Two lines changing is a redraw, not a screenful being replaced."""
    assert screen_replaced(["a", "b"], ["c", "d"]) is False


# -- the tracker, end to end --------------------------------------------------


def test_tracker_emits_only_what_scrolled_out_of_the_band():
    tracker = ScreenTracker()

    tracker.feed(viewer(1, "tick 000"))
    scrolled = tracker.feed(viewer(2, "tick 001"))

    assert scrolled == ["content line 01"]


def test_tracker_emits_nothing_for_a_frame_that_only_ticked():
    tracker = ScreenTracker()

    tracker.feed(viewer(1, "tick 000"))

    assert tracker.feed(viewer(1, "tick 001")) == []


def test_tracker_emits_the_outgoing_page_when_a_screen_is_replaced():
    tracker = ScreenTracker()
    first = [f"pager line {n:02d}" for n in range(1, 9)]

    tracker.feed(first)
    turned = tracker.feed([f"pager line {n:02d}" for n in range(20, 28)])

    assert turned == first


def test_tracker_flush_closes_the_record_with_what_is_still_displayed():
    """A screen that never scrolled has been transcribed by nothing else."""
    tracker = ScreenTracker()
    tracker.feed([HEADER, "content line 01", "", ""])

    assert tracker.flush() == [HEADER, "content line 01"]


def test_a_viewer_scrolling_past_gives_each_line_once_in_order():
    """The measured shape of the whole feature: 20 content lines, once each, in order.

    The spike this issue opened with emitted 96 lines for 20 lines of content.
    """
    tracker, out = ScreenTracker(), []
    for first in range(1, 18):
        out += tracker.feed(viewer(first, f"tick {first:03d}"))
    out += tracker.flush()

    content = [line for line in out if line.startswith("content line")]
    assert content == [f"content line {n:02d}" for n in range(1, 21)]


# -- assembling the result ----------------------------------------------------


def test_transcript_collapses_the_blank_rows_a_screen_grid_brings():
    out = Transcript()

    out.extend(["alpha", "", "", ""])
    out.extend(["", "", "beta"])

    assert out.lines == ["alpha", "", "beta"]


def test_transcript_drops_the_blank_rows_at_both_ends():
    out = Transcript()

    out.extend(["", "", "only line", "", ""])

    assert out.lines == ["only line"]


def test_transcript_text_ends_with_a_newline():
    out = Transcript()
    out.extend(["a", "b"])

    assert out.text() == "a\nb\n"


def test_transcript_of_nothing_is_empty_not_a_bare_newline():
    assert Transcript().text() == ""


# -- the edges of each decision (#337) ----------------------------------------


def test_read_writes_passes_over_entries_that_account_for_no_bytes(tmp_path):
    """A count of nothing, or one past the end of the recording, cuts nothing. The
    entries after it, a one-byte write among them, still cut where they say."""
    raw = tmp_path / "s.raw"
    raw.write_bytes(b"abcdef")
    sidecar = tmp_path / "s.timing"
    sidecar.write_text("0.5 2\n0.1 0\n0.2 1\n0.3 3\n0.4 4\n")

    assert read_writes(str(raw), str(sidecar)) == [(0.5, b"ab"), (0.2, b"c"), (0.3, b"def")]


def test_read_writes_skips_a_garbled_line_of_the_sidecar(tmp_path):
    """One that is no `delay count` pair, in bytes no UTF-8 holds, costs that line alone."""
    raw = tmp_path / "s.raw"
    raw.write_bytes(b"abcd")
    sidecar = tmp_path / "s.timing"
    sidecar.write_bytes(b"0.1 2\n\xff\xfe\n0.2 2\n")

    assert read_writes(str(raw), str(sidecar)) == [(0.1, b"ab"), (0.2, b"cd")]


def test_coalesce_starts_a_frame_at_a_pause_of_exactly_the_gap():
    """Under the gap is the same frame, and the gap itself is not under it."""
    assert coalesce([(0.0, b"one"), (0.05, b"two")], gap=0.05) == [b"one", b"two"]


def test_scanner_cuts_a_chunk_that_leaves_the_alternate_screen_and_comes_back():
    """As a shell escape from vim does, with output before each switch."""
    scanner = AltScreenScanner()
    scanner.split(b"\x1b[?1049h")

    runs = scanner.split(b"vim screen\x1b[?1049lshell output\x1b[?1049hvim again")

    assert runs == [
        (b"vim screen", True),
        (b"\x1b[?1049lshell output", False),
        (b"\x1b[?1049hvim again", True),
    ]


def test_scanner_passes_over_a_switch_to_its_own_screen_and_sees_the_next():
    scanner = AltScreenScanner()

    runs = scanner.split(b"a\x1b[?1049lb\x1b[?1049hc")

    assert runs == [(b"a\x1b[?1049lb", False), (b"\x1b[?1049hc", True)]


@pytest.mark.parametrize(
    ("sequence", "cut"),
    [
        (sequence, cut)
        for sequence in (b"\x1b[?1049h", b"\x1b[?47h")
        for cut in range(1, len(sequence))
    ],
)
def test_scanner_sees_a_switch_split_after_any_of_its_bytes(sequence, cut):
    """A part of `?47`'s too, which is held though the whole one is not (#340)."""
    scanner = AltScreenScanner()

    first = scanner.split(b"before" + sequence[:cut])
    second = scanner.split(sequence[cut:] + b"after")

    assert first == [(b"before", False)]
    assert second == [(sequence + b"after", True)]


@pytest.mark.parametrize(
    "sequence",
    [b"\x1b[?1049h", b"\x1b[?1047h", b"\x1b[?47h", b"\x1b[?1049l", b"\x1b[?1047l", b"\x1b[?47l"],
)
def test_scanner_holds_back_no_switch_that_ends_a_chunk_whole(sequence):
    """Only a part of one, which the next chunk could finish. A whole `?47` one is as
    short as a part of `?1049`'s, and it used to be held until the next chunk (#340)."""
    leaving = sequence.endswith(b"l")
    scanner = AltScreenScanner()
    if leaving:
        scanner.split(b"\x1b[?1049h")

    assert scanner.split(b"text" + sequence) == [(b"text", leaving), (sequence, not leaving)]
    assert scanner.close() == []


def test_scanner_close_hands_back_what_it_held_once():
    scanner = AltScreenScanner()
    scanner.split(b"x\x1b[?10")

    assert scanner.close() == [(b"\x1b[?10", False)]
    assert scanner.close() == []


def test_scroll_shift_is_no_scroll_for_a_frame_that_changed_only_its_clock():
    """Though its rows repeat, so that a shift of two matches two of them as well."""
    before = ["a", "b", "a", "b", "clock 1"]
    after = ["a", "b", "a", "b", "clock 2"]

    assert scroll_shift(before, after) is None


def test_scroll_shift_will_not_take_blank_rows_matching_at_a_shift_as_evidence():
    """At a shift of one here only blank rows match, and they match at every shift."""
    assert scroll_shift(["x", "", "", "y"], ["", "", "z", "w"]) is None


def test_scroll_shift_takes_the_smaller_of_two_shifts_that_match_as_well():
    """It emits fewer lines, and over-emitting is what makes a transcript useless."""
    before = ["a", "b", "c", "a", "b", "c"]
    after = ["b", "c", "X", "b", "c", "Y"]

    assert scroll_shift(before, after) == (1, 0)


@pytest.mark.parametrize(
    ("before", "after", "found"),
    [
        # Two runs of two text rows each: the first.
        (
            ["p0", "p1", "p2", "q0", "q1", "q2"],
            ["p1", "p2", "zz", "q1", "q2", "ww"],
            (1, 0),
        ),
        # As many text rows, and a blank one between them: the longer.
        (
            ["p0", "p1", "p2", "q0", "q1", "", "q2", "r"],
            ["p1", "p2", "zz", "q1", "", "q2", "ww", "vv"],
            (1, 3),
        ),
        # Three text rows against one and three blank rows: the one with more text.
        (
            ["p0", "p1", "p2", "p3", "q0", "q1", "", "", "", "r"],
            ["p1", "p2", "p3", "zz", "q1", "", "", "", "ww", "vv"],
            (1, 0),
        ),
    ],
)
def test_scroll_shift_trusts_the_run_with_most_text_then_most_rows_then_the_first(
    before, after, found
):
    assert scroll_shift(before, after) == found


def test_screen_replaced_counts_three_lines_on_each_side_as_a_screen():
    """Two are a redraw (above); three are the fewest that make a page."""
    assert screen_replaced(["a", "b", "c"], ["d", "e", "f"]) is True


def test_screen_replaced_lets_a_quarter_of_the_lines_stay():
    assert screen_replaced(["a", "b", "c", "kept"], ["d", "e", "f", "kept"]) is True


@pytest.mark.parametrize(
    ("tracker", "scrolled"), [(ScreenTracker(), ["l1"]), (ScreenTracker(3), [])]
)
def test_the_trackers_least_band_reaches_the_search_for_a_shift(tracker, scrolled):
    """Two text rows are band enough by default, and not when it asks for three."""
    tracker.feed(["l1", "l2", "l3", "status 1"])

    assert tracker.feed(["l2", "l3", "l4", "status 2"]) == scrolled


def test_the_tracker_keeps_an_indented_line_as_it_was_drawn():
    """Its indent, not the blanks a screen row ends with."""
    tracker = ScreenTracker()
    tracker.feed(["    indented   ", "l2", "l3", "status 1"])

    assert tracker.feed(["l2", "l3", "l4", "status 2"]) == ["    indented"]


def test_a_transcript_keeps_an_indented_line_as_it_was_drawn():
    out = Transcript()

    out.extend(["    code();   "])

    assert out.lines == ["    code();"]


# -- the replayer, and how the application reaches a recording ----------------


def test_the_replayer_keeps_alternate_screen_frames_apart(tmp_path, app_module):
    """Alternate-screen frames must go in one at a time; primary ones need not.

    Feeding alternate-screen frames together makes VTE coalesce them and lose the ones
    in between. The primary screen has scrollback, so its runs merge into one feed --
    measured lossless at 30 of 30 lines, and it is what keeps a session with no
    full-screen application from paying VTE's per-frame tick for nothing.
    """
    writes = [
        (0.0, b"shell one\r\n"),
        (0.05, b"shell two\r\n"),
        (0.05, b"\x1b[?1049hframe A"),
        (0.05, b"frame B"),
        (0.05, b"frame C"),
        (0.05, b"\x1b[?1049lback"),
    ]
    raw, timing = write_recording(tmp_path, writes)

    runs = app_module.TranscriptReplayer._plan(raw, timing)

    screens = [alternate for _, alternate in runs]
    assert screens == [False, True, True, True, False]
    assert runs[0][0] == b"shell one\r\nshell two\r\n", "primary runs merge into one feed"
    assert runs[1][0].startswith(b"\x1b[?1049h")
    assert runs[4][0].startswith(b"\x1b[?1049l")


@pytest.mark.parametrize(
    ("on", "off"),
    [
        (b"\x1b[?1049h", b"\x1b[?1049l"),
        (b"\x1b[?1047h", b"\x1b[?1047l"),
        (b"\x1b[?47h", b"\x1b[?47l"),
    ],
)
def test_the_replayer_feeds_a_switch_that_ends_a_frame_with_the_next(tmp_path, app_module, on, off):
    """Not on its own, to be sampled before anything is drawn.

    The screen then shows what it held before, and VTE does not clear it for `?47h`.
    Measured, an earlier session's last page was there, and the tracker took it for a
    page turned and transcribed it again (#340).
    """
    writes = [
        (0.0, b"$ less\r\n" + on),
        (0.05, b"page 1"),
        (0.05, b"page 2" + off),
        (0.05, b"$ "),
    ]
    raw, timing = write_recording(tmp_path, writes)

    runs = app_module.TranscriptReplayer._plan(raw, timing)

    assert runs == [
        (b"$ less\r\n", False),
        (on + b"page 1", True),
        (b"page 2", True),
        (off + b"$ ", False),
    ]


def test_the_replayer_joins_a_lone_switch_only_to_an_alternate_run_after_it(tmp_path, app_module):
    """A primary run after it stays apart, and so does an alternate run after a primary
    one that is only a switch: either way, the two are on different screens."""
    writes = [(0.0, b"\x1b[?47l"), (0.05, b"\x1b[?47h"), (0.05, b"\x1b[?47l$ ")]
    raw, timing = write_recording(tmp_path, writes)

    runs = app_module.TranscriptReplayer._plan(raw, timing)

    assert runs == [(b"\x1b[?47l", False), (b"\x1b[?47h", True), (b"\x1b[?47l$ ", False)]


def test_the_replayer_marker_changes_every_frame(app_module):
    """VTE reports a title *change*; repeating one leaves the replay waiting for ever."""
    sentinel = app_module.TranscriptReplayer._SENTINEL

    assert sentinel.format(1) != sentinel.format(2)


def test_the_replayer_keeps_the_whole_scrollback(app_module):
    """The primary transcript is the scrollback, so nothing may fall off the top.

    Measured: -1 is unlimited and 0 -- which reads like "no limit" -- keeps nothing,
    which would silently empty every primary-screen transcript.
    """
    body = inspect.getsource(app_module.TranscriptReplayer.start)

    assert "set_scrollback_lines(-1)" in body


# Each recording replayed through the replayer in a real terminal of 40 by 8, and its
# transcript printed. HOME is a scratch folder.
_REPLAY_SCRIPT = r"""
import json, sys
recordings, sys.argv = json.loads(sys.argv[1]), ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import GLib, Gtk
from gnome_connection_manager import app

transcripts = {}
for name, raw, timing in recordings:
    def finished(text, name=name):
        transcripts[name] = text.splitlines()
        GLib.idle_add(Gtk.main_quit)
    app.TranscriptReplayer(raw, timing, 40, 8, finished).start()
    Gtk.main()
print(json.dumps(transcripts))
"""


def numbered(word, count):
    return [f"{word} {n:02d}" for n in range(count)]


def printed(lines):
    return b"".join(f"{line}\r\n".encode() for line in lines)


PAGER = b"\x1b[?1049h\x1b[H\x1b[2Jpager 1\r\npager 2\r\npager 3"
PAGED = ["pager 1", "pager 2", "pager 3"]
LEAVE = b"\x1b[?1049l"
# What ncurses' clear sends for xterm-256color. ED 3 drops the scrollback, unlimited or not.
CLEAR = b"\x1b[H\x1b[2J\x1b[3J"
SESSION = [b"$ one\r\n", PAGER, LEAVE + b"$ two\r\n", b"$ three\r\n"]

REPLAYED = {
    "a pager on a screen not yet full": (SESSION, ["$ one", *PAGED, "$ two", "$ three"]),
    "a pager after clear": (
        [printed(numbered("line", 10)), CLEAR, *SESSION],
        ["$ one", *PAGED, "$ two", "$ three"],
    ),
    # A clear without ED 3 keeps the scrollback, and leaves the cursor at the top.
    "a pager after a clear that keeps the scrollback": (
        [printed(numbered("line", 10)), b"\x1b[H\x1b[2J", *SESSION],
        [*numbered("line", 10), "", "$ one", *PAGED, "$ two", "$ three"],
    ),
    "a pager on a full screen": (
        [printed(numbered("line", 10)), *SESSION],
        [*numbered("line", 10), "$ one", *PAGED, "$ two", "$ three"],
    ),
    "a row half written as a pager starts": (
        [b"$ sh demo.sh\r\nabc", PAGER, LEAVE + b"def\r\n$ "],
        ["$ sh demo.sh", *PAGED, "abcdef", "$"],
    ),
    # As a program that draws on the primary screen can leave it at the end.
    "a status line on the last row, the cursor on the first": (
        [b"$ one\r\n", b"\x1b[8H-- status --\x1b[H"],
        ["$ one", "", "-- status --"],
    ),
    "clear after more than follows it": (
        [printed(numbered("line", 100)), CLEAR, printed(["$ x", *numbered("late", 5)])],
        ["$ x", *numbered("late", 5)],
    ),
    "reset after more than follows it": (
        [printed(numbered("line", 30)), b"\x1bc", printed(["$ x", *numbered("late", 3)])],
        ["$ x", *numbered("late", 3)],
    ),
}


@pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"),
    reason="needs a display for a real terminal",
)
def test_the_replayer_keeps_every_line_the_primary_screen_showed(tmp_path):
    """However full the screen was when a full-screen program started (#344).

    A harvest at a switch read to the screen's second last row and counted the rows
    below the cursor as read, which the screen has empty until it fills, so what was
    printed into them once the program ended was lost. And the vertical adjustment
    counts from 0 again once ED 3 or a reset has dropped the scrollback, so an end read
    from it fell short: a session that ran `clear` lost the lines after it, as many as it
    had dropped. Measured against real VTE 0.76.
    """
    pytest.importorskip("gi", reason="PyGObject not available")
    recordings = []
    for index, (name, (writes, _)) in enumerate(REPLAYED.items()):
        folder = tmp_path / str(index)
        folder.mkdir()
        recordings.append([name, *write_recording(folder, [(0.05, chunk) for chunk in writes])])
    result = subprocess.run(
        [sys.executable, "-c", _REPLAY_SCRIPT, json.dumps(recordings)],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "HOME": str(tmp_path)},
        timeout=120,
    )

    assert result.returncode == 0, result.stderr[-3000:]
    transcripts = json.loads(result.stdout.splitlines()[-1])
    assert transcripts == {name: lines for name, (_, lines) in REPLAYED.items()}
    assert not glib_complaints(result.stderr), result.stderr[-3000:]


def test_the_replayer_uses_methods_vte_really_has():
    """conftest stubs all of gi, so a fake can offer methods the real widget lacks."""
    gi = pytest.importorskip("gi", reason="PyGObject not available")
    gi.require_version("Vte", "2.91")
    from gi.repository import Vte

    for name in (
        "set_size",
        "set_scrollback_lines",
        "get_text_format",
        "get_text_range_format",
        "get_cursor_position",
        "get_window_title",
        "get_column_count",
        "get_row_count",
        "feed",
    ):
        assert hasattr(Vte.Terminal, name), f"Vte.Terminal has no {name}"


def test_a_session_remembers_the_recording_it_is_being_written_to(app_module):
    """Save Transcript has no other way to find this session's recording."""
    body = inspect.getsource(app_module.vte_run)

    assert "terminal.raw_path = raw_path" in body
    assert body.index("raw_path = session_file_for") < body.index("terminal.raw_path")


def test_saving_a_transcript_refuses_a_session_that_was_never_recorded(app_module, monkeypatch):
    """Without `raw-session-log` there are no frames to rebuild from."""
    said = []
    monkeypatch.setattr(app_module, "msgbox", lambda text, *a, **k: said.append(text))
    controller = app_module.Wmain.__new__(app_module.Wmain)
    controller.wMain = None
    terminal = type("T", (), {"raw_path": None})()

    assert controller.save_session_transcript(terminal) is None
    assert said, "refusing silently reads as the feature being broken"


def refusal_and_checkbox(app_module):
    """The refusal's msgid, and the label Preferences draws for the recording checkbox."""
    source = inspect.getsource(app_module.Wmain.save_session_transcript)
    # \s* around the literal, matching the i18n guard in test_i18n.py: the formatter is
    # free to wrap a long msgbox call across lines, and a pattern that only matched
    # `_("...")` on one line silently stopped seeing this message when it did.
    message = [s for s in re.findall(r'_\(\s*"([^"]+)"\s*\)', source) if "grabación" in s]
    prefs = inspect.getsource(app_module.Wconfig.new)
    label = re.findall(r'_\(\s*"([^"]+)"\s*\),\s*"conf\.RAW_SESSION_LOG"', prefs)
    assert message, "the refusal must be a translatable string"
    assert len(label) == 1, "Preferences should draw one checkbox for recording"
    return message[0], label[0]


def test_the_refusal_says_what_to_do_about_it(app_module):
    """Recording is off by default and read at spawn, so a reader told only that there is
    no recording has no way to get one: say where to turn it on, and that it takes a new
    session.

    Where is Preferences. The message used to say gcm.conf, believing the setting had no
    preference UI; it had one from the start, and an edit to gcm.conf made while GCM runs
    never takes effect -- the running GCM does not read it again, and its next save writes
    the old value back (#166). So the message names the checkbox by the label drawn for it.
    """
    message, label = refusal_and_checkbox(app_module)

    assert label.split(" (")[0] in message, "name the checkbox as Preferences draws it"
    assert "Preferencias" in message, "say where it is"
    assert "gcm.conf" not in message, "an edit there while GCM runs never takes effect"
    assert "nueva" in message, "say that it takes a new session"


def test_the_refusal_names_the_checkbox_in_english_too(app_module):
    """An English reader sees the translations, which have to agree with each other too.
    Read from the compiled catalog the application loads, so a stale one fails here."""
    message, label = refusal_and_checkbox(app_module)
    english = gettext.translation(
        app_module.domain_name,
        localedir=Path(app_module.__file__).parents[2] / "lang",
        languages=["en"],
    )

    assert english.gettext(label).split(" (")[0] in english.gettext(message)
    assert "Preferences" in english.gettext(message)
    assert "gcm.conf" not in english.gettext(message)


def test_an_empty_recording_says_so_instead_of_doing_nothing(app_module, monkeypatch, tmp_path):
    """A recording with nothing in it yet is ordinary right after a session starts.

    Closing the progress dialog and doing nothing else reads as a broken feature, and
    it is what the first cut did: the save was guarded on the text being truthy, so an
    empty transcript fell through both branches and the click did nothing at all.
    """
    said, saved = [], []
    monkeypatch.setattr(app_module, "msgbox", lambda text, *a, **k: said.append(text))
    raw = tmp_path / "s.raw"
    raw.write_bytes(b"")
    (tmp_path / "s.timing").write_text("")

    controller = app_module.Wmain.__new__(app_module.Wmain)
    controller.wMain = None
    controller.save_text_to_file = lambda text, *a, **k: saved.append(text)
    terminal = type(
        "T",
        (),
        {"raw_path": str(raw), "get_column_count": lambda s: 80, "get_row_count": lambda s: 24},
    )()

    controller.save_session_transcript(terminal)

    assert saved == [], "there is nothing to offer as a file"
    assert said, "the click must say something rather than appear to do nothing"


def test_the_progress_dialog_fake_matches_real_gtk():
    """conftest stubs all of gi, so the fake could offer methods GTK does not have."""
    gi = pytest.importorskip("gi", reason="PyGObject not available")
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    for name in (
        "set_icon_from_file",
        "add_button",
        "get_content_area",
        "show_all",
        "connect",
        "destroy",
    ):
        assert hasattr(Gtk.Dialog, name), f"Gtk.Dialog has no {name}"
    for name in ("set_fraction", "set_show_text", "set_text"):
        assert hasattr(Gtk.ProgressBar, name), f"Gtk.ProgressBar has no {name}"
    assert hasattr(Gtk.Box, "pack_start"), "the content area is a Gtk.Box"


# -- reachable from the tab menu too, on that tab's session (#93) -------------


def test_saving_a_transcript_is_reachable_from_every_menu(app_module):
    """A feature with no way in is not shipped.

    Restored after being dropped in an edit: the count was 2 and the suite stayed
    green with one test fewer, which is exactly how it went unnoticed.
    """
    source = inspect.getsource(app_module)

    assert 'self._create_action("save-transcript"' in source
    assert source.count('"app.save-transcript"') == 3, "menubar, terminal menu, tab menu"


def test_a_tab_menu_transcript_uses_that_tabs_terminal(app_module):
    """Right-clicking a tab must transcribe that tab, not whichever is on screen.

    The tab menu and the terminal menu reach their session by different routes, and
    getting that wrong is what broke Ctrl+W (#95). Here nothing new was needed:
    opening the tab menu sets the context terminal from the tab, and the action asks
    for the target terminal, which prefers it -- this holds that true.
    """
    controller = app_module.Wmain.__new__(app_module.Wmain)
    controller._context_terminal = None
    controller._context_tab_widget = None
    controller.sync_console_log_action = lambda terminal: None
    on_screen, in_the_tab = app_module.Vte.Terminal(), app_module.Vte.Terminal()
    controller.page_in_use = lambda: types.SimpleNamespace(get_children=lambda: [on_screen])
    page = types.SimpleNamespace(get_children=lambda: [in_the_tab])

    controller.set_context_tab_widget(page)

    assert controller.get_target_terminal() is in_the_tab, "took the visible console"


def test_the_transcript_action_hands_on_the_context_terminal(app_module):
    """The whole path: tab context -> action -> the terminal that gets transcribed."""
    controller = app_module.Wmain.__new__(app_module.Wmain)
    controller._context_terminal = None
    controller._context_tab_widget = None
    controller.sync_console_log_action = lambda terminal: None
    on_screen, in_the_tab = app_module.Vte.Terminal(), app_module.Vte.Terminal()
    controller.page_in_use = lambda: types.SimpleNamespace(get_children=lambda: [on_screen])
    controller.set_context_tab_widget(types.SimpleNamespace(get_children=lambda: [in_the_tab]))
    asked = []
    controller.save_session_transcript = lambda terminal: asked.append(terminal)

    app = app_module.GcmApplication()
    app._controller = controller
    app._on_action_save_transcript(None, None)

    assert asked == [in_the_tab]
