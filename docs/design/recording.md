---
title: "Session Logs, Recording and Transcripts"
description: "What GCM writes of a session and reads back, and why: the relay a session runs under, the names of a session's files, and the transcript rebuilt from a raw recording"
audience:
  - contributors
tags:
  - gcm
  - gcm-dev
  - design
---

# Session Logs, Recording and Transcripts

Design notes for what GCM writes of a session and reads back: the relay a session runs
under, `src/gnome_connection_manager/relay.py`; the names of a session's files,
`src/gnome_connection_manager/utils/logpaths.py`; and the transcript rebuilt from a raw
recording, `src/gnome_connection_manager/utils/transcript.py`, which the code in
`src/gnome_connection_manager/app.py` drives. They say why each choice was made, what was
measured and with which versions, and what was rejected. They were moved here from
`AGENTS.md` (#430).

## The relay

`src/gnome_connection_manager/relay.py` is a PTY relay run as its own process. When OSC 52
or raw recording is enabled, sessions are spawned *under this* rather than directly, so it
sits in the byte path between the child and VTE. It forwards bytes unmodified, watches for
OSC 52, and can tee the stream to disk. VTE keeps its C read path and a stall here cannot
freeze the interface. `relay_command` starts it with `childpython.module_command`, not as
`python -m` (#415). A change of the tab's size reaches it as SIGWINCH, and
`on_sigwinch` passes the size on itself. Python retries a `select` a signal
interrupted once the handler has run (PEP 475), so a size left for the loop reached an
idle program only when a byte next went through, measured (#319). `relay` makes the
program's pty itself, with `os.openpty`, and sizes it before it forks. `pty.fork` starts
the program first, and measured under load, a program that read its size at once then
read 0 by 0 (#339). It sends every OSC 52 write it finds, the two of a pair included:
whether they are one copy is for GCM to say, in `RepeatFilter` in
`src/gnome_connection_manager/utils/osc52.py` (#393).

## Testing the relay

`tests/test_osc52.py` runs the relay on a pty that is its controlling terminal, since
only then does a resize signal it. `tests/test_relay.py` calls `relay()` in pytest's
own process instead, with a pty or pipes of the test's in place of `sys.stdin` and
`sys.stdout`, so that mutmut sees its mutants reached (#337). The relay holds the test's
thread until its program ends, so what a test does meanwhile, a resize among it, runs
from a timer's SIGALRM, and the resize is a SIGWINCH the test sends itself.
`held_up_after_fork` holds the relay up once it has started its program, as load does,
so that what a test finds the program first sees does not hang on the scheduler.
`test_a_pair_of_clipboard_writes_sets_the_clipboard_once` sends a pair through it, at
once and 3 ms apart, and gives what arrives to the real `Wmain._apply_clipboard_message`
with a clipboard that counts its sets (#393). It prints nothing, as `sys.stdout` stays a
stand-in until teardown, and holds the clock still only once the relay has returned,
since the relay's own limit reads it.

## A session's files

`src/gnome_connection_manager/utils/logpaths.py` holds the naming and layout for session logs:
`<log_dir>/<group>/<name>/<user>-<YYYYMMDD>-<NNN>.log`, plus the containment check that
keeps a free-text group from escaping the log root. Two sanitizers on purpose —
`sanitize_log_name` guards a filesystem path, `sanitize_tab_title` guards a widget that
ends at `set_markup`. `truncate_tab_label` is a third thing again: it cuts the whole
composed label at `TAB_LABEL_MAX = 30` so one tab does not push its neighbours behind the
notebook's scroll arrows, which `sanitize_tab_title`'s per-title 40 cannot do -- the host
name and a rename are part of the label too (#190). A cut, not a Pango ellipsis: measured,
an ellipsized label reports the ellipsis as its minimum width and the tab collapses to
34px, and `set_width_chars` as a floor then pads a `Local` tab out from 66px to 223px.

## One number for a session's files

Pure of GTK and of configuration: the log root is an argument, and
`app.py` keeps a `session_file_for` wrapper that supplies `conf.LOG_PATH` and keeps the
number it chose on the terminal as `session_stem`. A session's `.log`, `.raw` and
`.timing` are opened at different times -- the recording again on every reconnect --
and when each chose its own number, `002.log` sat beside `001.raw` (#200). A number is
free only while none of `SESSION_SUFFIXES` uses it, and choosing one creates the file
asked for, empty and exclusively: the relay creates a recording about 35 ms after the
spawn, and until then a second tab for the host took the same number (#202). The claim
is then checked against the number's other files and backed out of if one appeared:
the exclusive create settles two GCM instances claiming the same file, not one
claiming the `.log` while another claims the `.raw` (#204). So an empty `.log` is a
session's own reservation, not an earlier log to append to -- `set_terminal_logger`
reads its size, not whether it exists.

## Rebuilding a transcript

`src/gnome_connection_manager/utils/transcript.py` rebuilds a readable transcript from a
raw recording: restores the write boundaries from the `.timing` sidecar, coalesces each
burst of writes back into the frame it drew, tracks which screen the stream is on, and
decides what a new alternate-screen frame actually added. Pure, so the heuristics are
testable without a display; the emulator driving it is `TranscriptReplayer` in `app.py`.

## The alternate screen

VTE 0.76 does not clear the alternate screen for `?47h`, measured, so a sample taken
straight after one shows what an earlier session left there. `AltScreenScanner`
reports a switch with the chunk it ends, and `TranscriptReplayer._plan` feeds a run
that is only a switch together with the frame after it, so that no such sample is
taken (#340).

## Reading the primary screen

`TranscriptReplayer._harvest` reads the primary screen's new rows by the
cursor's row: at a switch up to it, since output goes on from there once the
alternate screen is left, into rows that a screen not yet full has empty, and at the
end to a screen below it (#344). Not by the vertical adjustment: ED 3, which `clear`
sends, and a reset drop the scrollback even when it is unlimited, measured, and the
adjustment then counts from 0 again.

## What a clear or a reset drops

What they drop is read before they go in (#362):
`_plan` cuts a primary run before each of `ERASES` with `split_at_erases`, and
`_harvest_erased` reads up to the cursor for ED 3 and a screen below it for a reset.
It keeps those rows waiting in `_erased`, and `_keep` adds them with the lines after
them, less what `unreprinted` finds those print again. Gemini CLI clears and prints its
screen again on every resize, measured, so keeping all of it put the screen in one
transcript 17 times. A redraw is told by its first `REPRINT_WORDS` words, and a line
goes when each of its words is in a run of `RUN_WORDS` that the redraw prints. Words,
so that a redraw at another width still matches, and anywhere in the redraw, since
Gemini CLI printed its screen twice after some clears, measured: matched in one
stretch, its screen was in the transcript 8 times.

## Blank frames

`ScreenTracker.feed` passes over a
frame with no text, so the next is compared with the page before it, and `flush` gives
that page if the screen ends blank (#363). A blank holds none of the text
`screen_replaced` needs, so a program that blanked its page before leaving the
alternate screen, as xterm-r6's rmcup does, lost it, and a blank between two pages
lost the first, measured. A frame with a line or two of text still replaces a page
without emitting it.

## The replay's size

`TranscriptReplayer.start` puts its terminal in a
`Gtk.OffscreenWindow`, which no screen holds to its size (#365). GTK holds a window to
the screen's size, VTE's grid shrinks with its allocation, and `get_text_format` reads
only as far as that reaches: measured, a tab of 274 by 71 replayed at 239 by 63 on a
1920x1080 screen, and none of a full-screen frame's rows came back. An offscreen
window gives the terminal its least size, a grid of 2 by 1, so once it is shown the
grid is set again and the terminal asks for its natural size, which `check_resize`
applies before the window is hidden.
