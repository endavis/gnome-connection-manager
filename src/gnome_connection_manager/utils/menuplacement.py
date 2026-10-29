"""Where a pop-up menu goes so that it stays on the screen (#392).

GCM used to place a menu itself, below the click or above it, from a guess of how tall it
was: 250 pixels and 50 spare. Real menus are 205 to 889 pixels tall at twice the usual
text size, and a list of 25 consoles 1233, so the guess was wrong for most of them, and
under WSLg a menu from the bottom of the server tree ran off the screen (#392).

GTK asks the windowing system to keep a menu on screen, and X11 does it: GTK flips and
slides the menu itself. Under Wayland GTK only sends flip, slide and resize to the
compositor as the positioner's constraint adjustment, and reads the result back. Weston's
libweston-desktop, which WSLg's compositor is built on, ends its positioner with a TODO
where the adjustment would be applied and returns the geometry unadjusted, so there a
menu lands where it was asked for, past the bottom edge.

So the placement is worked out here, from the menu's real height and the room it has, and
GTK is asked for that: below the row, else above it, else slid along the room until it
fits. A menu taller than the whole room starts at the top of it and scrolls, as GTK scrolls
one taller than the monitor. Whether the room is the monitor or the window is `app.py`'s
to say: a Wayland client does not know where its window is on the output.

Pure: only numbers go in, on one axis, all in the same coordinates.
"""

from __future__ import annotations

from typing import NamedTuple


class Placement(NamedTuple):
    """Where a menu goes, relative to the row it opens from.

    `below` hangs the menu's top edge from the row's bottom, and otherwise its bottom edge
    stands on the row's top. `shift` moves it on from there, down when positive and up
    when negative: the slide, which is 0 for a menu that fits on its side of the row.
    `scrolls` is whether the menu is taller than the room, so that only part of it shows.
    """

    below: bool
    shift: int
    scrolls: bool


def place_menu(top: int, bottom: int, height: int, low: int, high: int) -> Placement:
    """Where a menu `height` tall goes for a row spanning `top` to `bottom`, in a room
    spanning `low` to `high`.

    Below the row if it fits there, else above it. Where it fits on neither side it goes
    to the side with more room, below on a tie, and slides along the room until it is
    inside, and so covers the row: nothing else puts it on the screen. The menu is always
    inside the room, whichever way the row stands to it: one scrolled half out of sight
    has an edge beyond it. A menu taller than the room is as tall as the room, and starts
    at `low`: `scrolls` is True for it, and only for it, so a menu exactly as tall as the
    room does not.
    """
    room = high - low
    shown = min(height, room)
    space_below = high - bottom
    space_above = top - low
    # Below where it fits there. Where it does not, the side with more room, which is
    # above wherever it fits above, as then there is more room above than below, and
    # below on a tie.
    below = shown <= space_below or space_below >= space_above
    hung = bottom if below else top - shown
    start = min(max(hung, low), high - shown)
    return Placement(below, start - hung, height > room)
