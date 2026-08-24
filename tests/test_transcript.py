"""Rebuilding a readable transcript from a raw recording (#70).

The numbers quoted here were measured by replaying real recordings -- made through
`relay.py` itself -- through a hidden `Vte.Terminal`. They are what the heuristics in
`utils/transcript.py` were tuned against, so they are worth keeping honest.
"""

from __future__ import annotations

import inspect

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

# -- restoring the writes a recording was made with ---------------------------


def write_recording(tmp_path, writes, timing=True):
    raw = tmp_path / "s.raw"
    raw.write_bytes(b"".join(chunk for _, chunk in writes))
    sidecar = tmp_path / "s.timing"
    if timing:
        sidecar.write_text(
            "".join(f"{delay:.6f} {len(chunk)}\n" for delay, chunk in writes)
        )
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
    which were never scrolled past, and pre-empts the page-turn rule that would have
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
        "get_vadjustment",
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
    assert said == [app_module._("Esta sesión no tiene grabación")]


def test_saving_a_transcript_is_reachable_from_the_menus(app_module):
    """A feature with no way in is not shipped."""
    source = inspect.getsource(app_module)

    assert 'self._create_action("save-transcript"' in source
    assert source.count('"app.save-transcript"') == 2, "menubar and context menu"
