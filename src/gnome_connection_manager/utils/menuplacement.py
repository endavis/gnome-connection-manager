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

The same is worked out across (#398): Weston does not flip or slide a menu sideways
either, so one opened near the right edge ran off it. `place_across` opens it rightwards
or leftwards, whichever fits, else slides it along the room.

A menu cut short scrolls 15 pixels for each notch of the wheel, however tall a row is
(#399): GTK's `MENU_SCROLL_STEP2`, measured, at text sizes where a row is 25 and 40
pixels alike. `wheel_extra` is what is added to that to make it a row, and `wheel_row`
picks the row: the shortest, which is a single line's.

Pure: only numbers go in, on one axis at a time, all in the same coordinates.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Iterable

# GTK's step for one notch of the wheel on a menu cut short: MENU_SCROLL_STEP2, measured as
# 15 pixels at text scales 1 and 2 (#399).
GTK_MENU_STEP = 15


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


class Across(NamedTuple):
    """Which way a menu opens from the rectangle it opens beside (#398).

    `leftwards` hangs the menu's right edge from the rectangle's right edge, and otherwise
    its left edge stands on the rectangle's left. `shift` moves it on from there, right
    when positive and left when negative: the slide, 0 for a menu that fits on its side.
    """

    leftwards: bool
    shift: int


def place_across(
    left: int, right: int, width: int, low: int, high: int, leftwards: bool = False
) -> Across:
    """Which way a menu `width` wide goes for a rectangle spanning `left` to `right`, in
    a room spanning `low` to `high` (#398).

    On the preferred side (`leftwards` says which) if it fits there, else on the other,
    else on the side with more room, the preferred one on a tie, slid along the room until
    it is inside. A menu wider than the room is as wide as the room and starts at `low`.
    """
    shown = min(width, high - low)
    space_right = high - left
    space_left = right - low
    fits_right = shown <= space_right
    fits_left = shown <= space_left
    if leftwards:
        if fits_left:
            go_left = True
        elif fits_right:
            go_left = False
        else:
            go_left = space_left >= space_right
    else:
        if fits_right:
            go_left = False
        elif fits_left:
            go_left = True
        else:
            go_left = space_left > space_right
    hung = right - shown if go_left else left
    start = min(max(hung, low), high - shown)
    return Across(go_left, start - hung)


def wheel_row(heights: Iterable[int]) -> int | None:
    """The row a notch of the wheel scrolls a menu by (#399): the smallest height above
    zero, None where there is none.

    The shortest, not the median: with half a menu's rows two lines tall the median made a
    notch 53 pixels at twice the usual text size, and the shortest 40, one line's.
    """
    positive = [height for height in heights if height > 0]
    return min(positive) if positive else None


def wheel_extra(delta: float, row: int | None, step: int = GTK_MENU_STEP) -> float:
    """The scroll delta to add to GTK's own for a wheel movement of `delta` so that the
    two come to `delta` rows of `row` pixels (#399); 0.0 where nothing is to be added.

    GTK moves a smooth scroll by `delta * step` pixels, truncated, so half a pixel is
    added in the direction of the movement: without it a 40 pixel row gave 39. Nothing
    is added for a row no taller than GTK's step, or for no movement.
    """
    if delta == 0 or row is None or row <= step:
        return 0.0
    return (delta * (row - step) + math.copysign(0.5, delta)) / step
