---
title: "Clipboard and OSC 52"
description: "How GCM sets the clipboard for a program's OSC 52 writes, and why: one copy from a pair, and a write set again where WSLg's Weston ignored it"
audience:
  - contributors
tags:
  - gcm
  - gcm-dev
  - design
---

# Clipboard and OSC 52

Design notes for `src/gnome_connection_manager/utils/osc52.py`, the module, and for the
clipboard code of `Wmain` in `src/gnome_connection_manager/app.py`: why each choice was made,
what was measured and with which versions, and what was rejected. The relay that finds the
writes in a program's output is `src/gnome_connection_manager/relay.py`, which `AGENTS.md`
describes. These notes were moved here from `AGENTS.md` (#430).

## The scanner and the pair

The module holds the extraction of OSC 52 clipboard writes from
a byte stream, and the decision that a pair of them is one copy (#393), and the watch that
sets a write again when the compositor ignored it (#412, #413). Pure but for
`kernel_release` and `wslg_folder`, so it is testable without a terminal, a display or a
pty: `Osc52Scanner` holds a partial-sequence buffer, and `RepeatFilter` the last write GCM
let through, with the time an argument as `QuietWatch`'s is, and `ClipboardWatch` the last
write GCM set, below. A program in a tab wrote each copy as a pair, the text for the target
`''` and again for `c`, and the scanner reads `''` as `c`, so the two reach GCM alike.
`Wmain._apply_clipboard_message` asks `RepeatFilter.repeated` and sets the clipboard once
for a pair.

## Why a pair left the clipboard stuck under WSLg

The mechanism, measured on WSLg 1.0.73.2 (Weston 9.0.0) and posted on #393: GTK 3 makes
a new data source for each `set_text`, with the serial of the last input event. Weston's
clipboard manager, `libweston/clipboard.c`, keeps a copy of the selection with its serial
and sets it back when the selection's source is destroyed. So a second set with no input
since carries the serial the selection already has, and `weston_seat_set_selection`
ignores it, with no `cancelled`. GTK gives up its claim only on `cancelled` for its own
source, so it went on answering a paste with GCM's text, while a copy made in Windows
replaced the manager's copy and not GCM's source. The same three pieces are in upstream
Weston 13.0.0, read in its source. An echo through Windows, which the issue first
suspected, was not it: a single write stayed the selection for nearly 5 s. A pair
handled in one go also left Windows an empty string, three runs out of three, as GTK
destroyed the first source before it answered the manager's read of it; with the writes
3 ms apart it answered, and Windows held the text, two runs out of two.

## One copy from a pair

Decided there: `REPEAT_WINDOW` is 1 s, from the last write let through, and a repeat
does not renew it, since a program writing one text every 0.6 s would be left out for
good and the copy that puts things right must always get through. The key is the decoded
text alone. The target is not honoured: xterm reads `''` as the primary selection, and a
program that wrote it alone would no longer reach the clipboard, which changes what an
existing configuration does. The filter is made on first use, as a terminal's
`quiet_watch` is, since tests build a `Wmain` with `object.__new__` and one on the class
would carry a write from one to the next. It comes after the preference check, the
decode and the empty-text check, so a write refused is never remembered. It is GCM's and
not the relay's: the relay is in the byte path and is meant to stay simple, and GCM
already re-checks the preference.

## A write the compositor ignored

The same ignored set came two more ways (#412, #413): a write after a copy made in Windows
with no input to GCM since, and a second write with no input since the first, of another
text or of the same one more than `REPEAT_WINDOW` later. GCM cannot make a serial of its
own. Measured on WSLg 1.0.73.2 (Weston 9.0.0), from `WAYLAND_DEBUG=client` merged with the
calls of a GDK event handler, `Gdk.event_handler_set`, that passes every event on to
`Gtk.main_do_event`. Of 22 sets, the 13 that Weston took each got exactly one
SELECTION_REQUEST for the clipboard in the handler, 0.1 to 5.4 ms after the first
`wl_data_source.send`, which came 8.5 to 48.4 ms after the set; the 9 it ignored got none,
and no `send`. GCM's own `wait_for_text()` on its false claim raised none. A source Weston
cancelled gave a SELECTION_CLEAR for the clipboard, 3 of 3, 0.13 to 0.21 ms after the
`cancelled`, one of them while GCM was not the active window. All 25 `wl_keyboard.enter`
and `leave` events of two runs, GCM's windows and the probe's other window, were followed
by exactly one FOCUS_CHANGE with the matching `in_`, the last within 0.675 ms. A native
Windows window forced to the foreground from a script, an `Alt` key press and then
`SetForegroundWindow`, gave GCM a `leave`, and an `enter` when GCM was forced forward
again; the script's `Alt` reached GCM as a key press and release 13 ms before the `leave`,
and `AppActivate` alone left `msrdc` in front and showed nothing. The foreground was
changed by a script, and a click was not measured.

## Setting it again

`ClipboardWatch` holds the write GCM set until `heard`, which `Wmain.follow_clipboard`
calls at a SELECTION_REQUEST or SELECTION_CLEAR for the clipboard: the compositor took the
set and asked for the text, or the claim ended. `again` gives the text at a FOCUS_CHANGE,
in or out, which `follow_clipboard` sets again. It gives nothing once `MAX_SETS` = 3 sets
of it were made, the write's included, and nothing within `REPAIR_GAP` = 0.25 s of the last
set, a write's or a repair's. A newer write replaces the one held and starts the count
again. A prototype of this in the probe's handler, real GCM on WSLg: 5 scenarios, 37
checks, 0 failed, and the first FOCUS_CHANGE after a copy in Windows carried a serial newer
than the copy's (a write set with 9466 ignored, the leave's 9471 set it again and was
taken; with 9493 ignored, the enter's 9500 taken; 9512 taken and 9512 ignored, the leave's
9516 taken; 9534 taken and 9534 ignored, the leave's 9538 taken). The control, a write
right after input, 9444, was taken at once, and the three later enters and leaves set
nothing.

## Only at a change of window

Not at a key or a click, only at a change of window: GTK handles the event before the watch
looks at it, so a copy GCM makes at that key or click is set first, with its serial, and
taken. A repair at the same event would destroy that source, which Weston's clipboard
manager may not have read yet (#393 measured Windows left with an empty string for such a
pair), and set the older text with the same serial, which Weston ignores: the copy would be
lost. That is reasoned from the mechanism and from #393's pair, not run. Pasting into a
Windows application means the keyboard leaves GCM first, and the leave repairs the
clipboard. `REPAIR_GAP` counts from a write too, for two reasons, inferred and neither
seen. The keyboard moving between two GCM windows gives two FOCUS_CHANGEs back to back (seen
on X11), and read together both would set with the serial GDK read last, so the second set
would be ignored, as in #413. And GDK reads a batch of Wayland events, which advances its
serial, and hands the events out one at a time, so a write applied in between takes the
serial of an `enter` or `leave` not yet handed out, and a repair at that event would set
with the same serial. The gap is about 5 times the longest wait measured from a set to the
request, 52.9 ms: a margin, not a threshold.

## Only under WSLg

Only under WSLg: `under_wslg` wants a Wayland display, `GdkWaylandDisplay` exactly, a
kernel release that names Microsoft, from `kernel_release`, and the folder `/mnt/wslg`, from
`wslg_folder`. Every figure above is WSLg's Weston. A compositor that asks for no source it
takes, where Weston's clipboard manager asks, would have every write set again at the next
two changes of window, and whether another compositor accepts a set made as the keyboard
leaves was not measured. The folder as well as the kernel: WSL cannot be told
reliably, as #392 decided for menu placement, and here a miss costs nothing and a
false hit costs a set again at changes of window. Elsewhere GCM does what it did.

## GDK's event handler

`Wmain.clipboard_watch` decides once per window, at the first write, with a flag of its own
since None cannot tell "not decided" from "decided: not here", and installs
`Wmain.watch_gdk_event` with `Gdk.event_handler_set`. **GCM owns GDK's event handler from
then on, and any later hook has to chain through `Wmain.watch_gdk_event`.** It gives every
event to `Gtk.main_do_event` first and then to `follow_clipboard`, inside a try that logs,
so a fault there can never stop an event. `dialog.run()` enters it again, which is safe as
the watch runs after `Gtk.main_do_event`. The preference is checked at the FOCUS_CHANGE
too: off, the write is forgotten.

## Directions not taken

Not taken, of the directions the issues offered. Holding a write until GCM's next input
delays a write that is taken at once today, and a copy made after the write would be
overwritten at the input, where today it replaces the write. `Gtk.Clipboard.clear()` on
`owner-change`: the findings measured that `owner-change` also comes at every keyboard
`enter` and for GCM's own taken set, with no owner in the event, and `clear()` would not put
the text in Windows. Coalescing a burst is `RepeatFilter`'s for one text, and covers no
write seconds later.

## Known limits

Known limits, in `docs/TERMINAL-USAGE.md` as well. A copy made elsewhere after a write Weston ignored,
and before the next change of window, is replaced by the write at that change: an unfocused
GCM is told nothing of it, and a focused one is told by a `selection` event and an
OWNER_CHANGE that also come at every `enter` and for its own taken sets, which the fix does
not use. Between an ignored write and that change, `powershell.exe Get-Clipboard` or
`win32yank.exe -o` run in a GCM tab read the older text. A write that comes while GCM is not
in use reaches Windows when the keyboard comes back. A change of window within
`REPAIR_GAP` of an ignored write is skipped. A SELECTION_REQUEST or SELECTION_CLEAR for
GCM's previous source that reaches the handler after a new write was set would end the
watch of a write Weston ignored; it needs two writes of different texts less than about
50 ms apart, and was not seen.

## Tests

`tests/test_osc52.py` holds `ClipboardWatch` and `under_wslg` to exact boundaries, and
GCM's side with plain objects for events, never a `Gdk.Event` with its fields written from
Python: that killed the interpreter with SIGSEGV, exit 139, measured. Its `Clipboard` fakes
the kernel and the folder, so a test says the same on a machine that is not WSL. The
scenario `test_a_write_the_compositor_ignored_is_set_again_against_real_gtk` runs real GCM
on an Xvfb of its own with real events, measured there: a second program pasting raises one
SELECTION_REQUEST, whose selection reads `event.selection.selection.name()` as
`'CLIPBOARD'`, where `wait_for_text()` in the owning process raises none; a second program
taking the clipboard raises SELECTION_CLEAR; and `Gdk.Window.focus` on a second toplevel
raises FOCUS_CHANGE with `in_` 0 for the first window and 1 for the second, back to back.
The display is X11, so it forces `under_wslg`, and runs the same moves without, which
must set nothing.
