"""Where a pop-up menu goes so that it stays on the screen (#392).

A menu in GCM is placed by GCM: below the row or the click, else above it, else slid until it
fits, and rightwards or leftwards the same way (#398). The decisions are
`menuplacement.place_menu` and `place_across`, which takes numbers and is tested here
without a display. `app.py` supplies the numbers -- the menu's height from its items, and the
room from the monitor or, under Wayland, the window -- and asks GTK for the result in
`popup_menu_at`, which is tested with fakes first and then against real GTK.

Real GTK, because the bug did not show there before: X11 flips and slides a menu itself, so
every menu opened at the bottom of the screen looked right. Wayland leaves that to the
compositor, and Weston's, which WSLg's is built on, applies none of it (read in its source,
and measured on Weston 13), so a menu landed where it was asked for, past the bottom edge.
A scenario emulates such a compositor by taking every hint from the menu just before it
opens, `anchor-hints` 0, which leaves it exactly where GCM asked. Five of the scenarios fail
against the code that guessed a menu 250 pixels tall, so they test GCM's side and not GTK's,
and a sixth holds `menu_height` to the height GTK gives each menu. The two that keep GCM's
hints hold X11, which moves a menu itself, to the same.

Two more scenarios hold a menu's scroll (#408): GTK keeps it from one opening to the next, so
a menu scrolled to its end with real wheel notches opened again, shorter or as long, must
start at its top.

They run at twice the usual text size, where the menus are tall enough to be wrong for the
old guess on a screen of 1080 pixels: the server tree's menu on a host is 549 pixels there,
and the terminal's 821. Each runs on a display of its own, with real clicks through XTest.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

from gnome_connection_manager.utils.menuplacement import (
    Across,
    Placement,
    place_across,
    place_beside,
    place_menu,
    wheel_extra,
    wheel_row,
)
from tests.test_connections import glib_complaints
from tests.test_console_window import _private_display

REPO = Path(__file__).resolve().parents[1]


# -- the decision, with no display -------------------------------------------------------------


def landing(placement: Placement, top: int, bottom: int, height: int, low: int, high: int):
    """The span a menu `height` tall covers when GTK puts it where `placement` says, as
    (start, end): hung from the row's bottom or stood on its top, then moved by the shift.
    A menu taller than the room is shown at the placement's height (#402)."""
    shown = placement.height
    start = bottom + placement.shift if placement.below else top + placement.shift - shown
    return start, start + shown


def test_a_menu_that_fits_below_the_row_hangs_from_it():
    assert place_menu(100, 140, 300, 0, 1000) == Placement(True, 0, False, 300)


def test_a_menu_that_does_not_fit_below_stands_on_the_row():
    assert place_menu(700, 740, 300, 0, 1000) == Placement(False, 0, False, 300)


def test_below_is_chosen_where_it_fits_on_both_sides():
    assert place_menu(400, 440, 300, 0, 1000) == Placement(True, 0, False, 300)


@pytest.mark.parametrize(
    ("top", "bottom", "expected"),
    [
        # A menu of 300 and a room to 1000: a row ending at 700 leaves exactly 300 below it,
        # and one ending at 701 leaves 299, so the menu stands on the row.
        (660, 700, Placement(True, 0, False, 300)),
        (661, 701, Placement(False, 0, False, 300)),
    ],
)
def test_a_menu_fits_below_with_exactly_the_room_that_is_left(top, bottom, expected):
    assert place_menu(top, bottom, 300, 0, 1000) == expected


@pytest.mark.parametrize(
    ("top", "bottom", "expected"),
    [
        # A row from 300 to 701 leaves 299 below it, so below is out, and exactly 300 above
        # it. From 299 it leaves 299 above too: neither fits, the tie goes to below, and the
        # menu is lifted the one pixel it takes.
        (300, 701, Placement(False, 0, False, 300)),
        (299, 701, Placement(True, -1, False, 300)),
    ],
)
def test_a_menu_fits_above_with_exactly_the_room_that_is_left(top, bottom, expected):
    assert place_menu(top, bottom, 300, 0, 1000) == expected


def test_a_menu_that_fits_neither_side_slides_up_from_below_the_row():
    """More room below than above: it still hangs from the row, and is lifted until its
    bottom edge is the room's."""
    placement = place_menu(300, 340, 800, 0, 1000)

    assert placement == Placement(True, -140, False, 800)
    assert landing(placement, 300, 340, 800, 0, 1000) == (200, 1000)


def test_a_menu_that_fits_neither_side_slides_down_from_above_the_row():
    """More room above than below: it stands on the row, and is lowered until its top
    edge is the room's."""
    placement = place_menu(600, 640, 800, 0, 1000)

    assert placement == Placement(False, 200, False, 800)
    assert landing(placement, 600, 640, 800, 0, 1000) == (0, 800)


def test_where_both_sides_are_alike_a_menu_that_fits_neither_slides_from_below():
    """450 above, 450 below, and a menu of 600: the tie goes to below."""
    placement = place_menu(450, 550, 600, 0, 1000)

    assert placement == Placement(True, -150, False, 600)
    assert landing(placement, 450, 550, 600, 0, 1000) == (400, 1000)


def test_a_menu_exactly_as_tall_as_the_room_fills_it_and_does_not_scroll():
    placement = place_menu(450, 550, 1000, 0, 1000)

    assert placement == Placement(True, -550, False, 1000)
    assert landing(placement, 450, 550, 1000, 0, 1000) == (0, 1000)


def test_a_menu_one_pixel_taller_than_the_room_scrolls():
    placement = place_menu(450, 550, 1001, 0, 1000)

    # Below the row, cut to the 450 pixels under it (#402).
    assert placement == Placement(True, 0, True, 450)
    assert landing(placement, 450, 550, 1001, 0, 1000) == (550, 1000)


def test_a_menu_much_taller_than_the_room_hangs_beside_its_row_on_the_side_with_more_room():
    assert place_menu(100, 120, 5000, 0, 1000) == Placement(True, 0, True, 880)
    assert place_menu(800, 820, 5000, 0, 1000) == Placement(False, 0, True, 800)


def test_a_menu_taller_than_the_room_goes_below_where_both_sides_are_alike():
    assert place_menu(480, 520, 5000, 0, 1000) == Placement(True, 0, True, 480)


def test_a_menu_taller_than_the_room_is_inside_it_for_a_row_partly_outside():
    for top, bottom in ((-20, 20), (980, 1020)):
        placement = place_menu(top, bottom, 5000, 0, 1000)
        start, end = landing(placement, top, bottom, 5000, 0, 1000)
        assert placement.scrolls and placement.height > 0
        assert start >= 0 and end <= 1000


def test_a_menu_taller_than_the_room_is_the_whole_room_where_the_row_fills_it():
    placement = place_menu(0, 1000, 5000, 0, 1000)

    assert placement == Placement(True, -1000, True, 1000)
    assert landing(placement, 0, 1000, 5000, 0, 1000) == (0, 1000)


@pytest.mark.parametrize("offset", [-500, -1, 1, 37, 4000])
def test_where_the_room_is_does_not_change_what_is_decided(offset):
    """Only distances matter: a window whose top is 37, or a monitor below another."""
    for top, bottom, height in ((100, 140, 300), (700, 740, 300), (300, 340, 800), (600, 640, 800)):
        moved = place_menu(top + offset, bottom + offset, height, offset, 1000 + offset)
        assert moved == place_menu(top, bottom, height, 0, 1000)


@pytest.mark.parametrize(
    ("top", "bottom", "expected"),
    [
        # Half out at the top: room below it, so it hangs from the row's visible edge.
        (-20, 20, Placement(True, 0, False, 400)),
        # Half out at the bottom: only above.
        (980, 1020, Placement(False, 0, False, 400)),
        # Wholly above the room, or below it: the menu is moved in, to the room's edge.
        (-50, -10, Placement(True, 10, False, 400)),
        (1010, 1050, Placement(False, -10, False, 400)),
    ],
)
def test_a_row_outside_the_room_still_gets_a_menu_inside_it(top, bottom, expected):
    """A tree row scrolled half out of sight has an edge beyond the room's."""
    placement = place_menu(top, bottom, 400, 0, 1000)

    assert placement == expected
    start, end = landing(placement, top, bottom, 400, 0, 1000)
    assert start >= 0 and end <= 1000


def test_every_menu_lands_in_the_room_and_off_the_row_where_there_is_room_for_both():
    """Every row and every height on a small room, rows partly or wholly outside it too."""
    low, high = 0, 40
    checked = 0
    for top in range(-8, 49):
        for row in range(1, 7):
            bottom = top + row
            inside = low <= top and bottom <= high
            for height in range(0, 46):
                placement = place_menu(top, bottom, height, low, high)
                start, end = landing(placement, top, bottom, height, low, high)
                why = (top, bottom, height, placement)
                shown = placement.height
                assert shown == (min(height, high - low) if not placement.scrolls else shown)
                assert placement.scrolls == (height > high - low), why
                assert low <= start and end <= high, why
                checked += 1
                if not inside:
                    continue
                covers = start < bottom and end > top
                if placement.scrolls:
                    # Beside the row, cut to the side's space, where a side has any.
                    if max(high - bottom, top - low) > 0:
                        assert not covers, why
                        assert placement.shift == 0, why
                        assert placement.height == max(high - bottom, top - low), why
                        assert start == bottom or end == top, why
                    else:
                        assert (start, end) == (low, high), why
                    continue
                below, above = high - bottom >= shown, top - low >= shown
                if below:
                    assert placement == Placement(True, 0, False, shown), why
                elif above:
                    assert placement == Placement(False, 0, False, shown), why
                else:
                    # Nothing fits beside the row, so the menu covers it, and is moved no
                    # further than it takes to be inside: against an edge of the room, on
                    # the side with more room.
                    assert covers, why
                    assert start == low or end == high, why
                    assert placement.below == (high - bottom >= top - low), why
                if below or above:
                    assert not covers, why
                    assert start == bottom or end == top, why
    assert checked == 57 * 6 * 46


def test_a_placement_unpacks_as_it_is_named():
    below, shift, scrolls, height = place_menu(300, 340, 800, 0, 1000)

    assert (below, shift, scrolls, height) == (True, -140, False, 800)


# -- a submenu, beside its row (#397) ------------------------------------------------------------


def test_a_submenu_that_fits_stays_where_gtk_put_it():
    assert place_beside(300, 200, 0, 1080) == Placement(True, 0, False, 200)


def test_a_submenu_that_runs_past_the_room_slides_up_to_its_bottom_edge():
    assert place_beside(900, 400, 0, 1080) == Placement(True, -220, False, 400)


def test_a_submenu_above_the_room_slides_down_to_its_top_edge():
    assert place_beside(-50, 400, 0, 1080) == Placement(True, 50, False, 400)


def test_a_submenu_exactly_as_tall_as_the_room_fills_it_and_does_not_scroll():
    assert place_beside(300, 1080, 0, 1080) == Placement(True, -300, False, 1080)


def test_a_submenu_one_pixel_taller_than_the_room_scrolls_from_the_low_edge():
    assert place_beside(300, 1081, 0, 1080) == Placement(True, -300, True, 1080)


@pytest.mark.parametrize("offset", [0, 37, -500])
def test_where_the_room_is_does_not_change_what_is_decided_beside(offset):
    for top in range(-100, 1300, 50):
        for height in (100, 700, 1080, 1500):
            base = place_beside(top, height, 0, 1080)
            moved_by = place_beside(top + offset, height, offset, 1080 + offset)
            assert moved_by == base


def test_every_submenu_lands_inside_the_room():
    for top in range(-200, 1400, 17):
        for height in range(1, 1500, 53):
            placement = place_beside(top, height, 100, 1000)
            start = top + placement.shift
            assert start >= 100 and start + placement.height <= 1000, (top, height, placement)
            assert placement.scrolls == (height > 900)


# -- the decision across, with no display (#398) ----------------------------------------------


def across_landing(result: Across, left: int, right: int, width: int, low: int, high: int):
    shown = min(width, high - low)
    start = (right - shown if result.leftwards else left) + result.shift
    return start, start + shown


def test_a_menu_that_fits_rightwards_hangs_from_the_left_edge():
    assert place_across(100, 140, 300, 0, 1000) == Across(False, 0)


def test_a_menu_that_fits_only_leftwards_stands_on_the_right_edge():
    result = place_across(900, 940, 300, 0, 1000)

    assert result == Across(True, 0)
    assert across_landing(result, 900, 940, 300, 0, 1000) == (640, 940)


@pytest.mark.parametrize(
    ("left", "expected"),
    [(700, Across(False, 0)), (701, Across(True, 0))],
)
def test_a_menu_fits_rightwards_with_exactly_the_room_that_is_left(left, expected):
    assert place_across(left, left + 40, 300, 0, 1000) == expected


@pytest.mark.parametrize(
    ("right", "expected"),
    [
        # Room 500 to 1000, a menu of 300 and a rectangle from 701: rightwards leaves 299.
        # Leftwards leaves exactly 300 from a right edge of 800; from 799 it leaves 299 too,
        # a tie, so rightwards, slid left by the one pixel it takes.
        (800, Across(True, 0)),
        (799, Across(False, -1)),
    ],
)
def test_a_menu_fits_leftwards_with_exactly_the_room_that_is_left(right, expected):
    assert place_across(701, right, 300, 500, 1000) == expected


def test_leftwards_is_preferred_where_both_fit_and_rightwards_where_only_it_fits():
    assert place_across(400, 440, 300, 0, 1000, leftwards=True) == Across(True, 0)
    assert place_across(100, 140, 300, 0, 1000, leftwards=True) == Across(False, 0)
    assert place_across(400, 440, 300, 0, 1000) == Across(False, 0)


def test_a_menu_that_fits_neither_way_goes_to_the_side_with_more_room_and_slides():
    # Room 0..1000, menu 800: from 300..340 there are 700 right and 340 left.
    right = place_across(300, 340, 800, 0, 1000)
    assert right == Across(False, -100)
    assert across_landing(right, 300, 340, 800, 0, 1000) == (200, 1000)
    # From 600..640: 400 right and 640 left.
    left = place_across(600, 640, 800, 0, 1000)
    assert left == Across(True, 160)
    assert across_landing(left, 600, 640, 800, 0, 1000) == (0, 800)


def test_where_both_sides_are_alike_the_preferred_one_gets_a_menu_that_fits_neither():
    assert place_across(450, 550, 600, 0, 1000) == Across(False, -50)
    assert place_across(450, 550, 600, 0, 1000, leftwards=True) == Across(True, 50)


def test_a_menu_wider_than_the_room_starts_at_the_low_edge():
    for leftwards in (False, True):
        result = place_across(450, 550, 1500, 30, 1030, leftwards)
        assert across_landing(result, 450, 550, 1500, 30, 1030)[0] == 30


@pytest.mark.parametrize("offset", [0, 37, -500, 4000])
def test_where_the_room_is_across_does_not_change_what_is_decided(offset):
    base = place_across(900, 940, 300, 0, 1000)
    moved = place_across(900 + offset, 940 + offset, 300, offset, 1000 + offset)

    assert moved == base


def test_every_menu_lands_inside_the_room_across():
    low, high = 20, 520
    for width in range(1, 700, 37):
        for left in range(-50, 600, 23):
            for span in (1, 40):
                for leftwards in (False, True):
                    result = place_across(left, left + span, width, low, high, leftwards)
                    start, end = across_landing(result, left, left + span, width, low, high)
                    assert low <= start and end <= high, (width, left, span, leftwards)


def test_an_across_unpacks_as_it_is_named():
    leftwards, shift = place_across(900, 940, 300, 0, 1000)

    assert (leftwards, shift) == (True, 0)


# -- a notch of the wheel, with no display (#399) -----------------------------------------------


def moved(delta, row):
    """What GTK's step and the extra come to, as GTK truncates each."""
    return int(delta * 15) + int(wheel_extra(delta, row) * 15)


def test_a_notch_and_the_extra_come_to_exactly_a_row():
    for row in (25, 40):
        assert moved(1.0, row) == row
        assert moved(-1.0, row) == -row
    assert 15 + wheel_extra(1.0, 25) * 15 == pytest.approx(25.5)
    assert wheel_extra(1.0, 40) == pytest.approx(25.5 / 15)


@pytest.mark.parametrize("delta", [1.0, -1.0, 0.1, -0.1, 2.0, -2.0])
def test_a_movement_scrolls_a_row_for_each_notch_within_a_pixel(delta):
    for row in range(16, 121):
        assert abs(moved(delta, row) - round(delta * row)) <= 1, (delta, row)
        if abs(delta) == 1.0:
            assert moved(delta, row) == round(delta * row), row


@pytest.mark.parametrize("delta,row", [(0.0, 40), (1.0, None), (1.0, 15), (-1.0, 10), (1.0, 0)])
def test_nothing_is_added_for_no_movement_no_row_or_a_row_no_taller_than_gtks_step(delta, row):
    assert wheel_extra(delta, row) == 0.0


def test_the_row_is_the_shortest_that_has_a_height():
    assert wheel_row([40, 67, 40]) == 40
    assert wheel_row([67, 40, 53]) == 40
    assert wheel_row([]) is None
    assert wheel_row([0, 0]) is None
    assert wheel_row([0, 40, 0, 67]) == 40
    assert wheel_row(iter([25])) == 25


# -- the numbers app.py supplies, with fakes --------------------------------------------------


class Padding:
    def __init__(self, top, bottom):
        self.top, self.bottom = top, bottom


class StyleContext:
    def __init__(self, padding):
        self.padding = padding
        self.asked = []

    def get_padding(self, state):
        self.asked.append(state)
        return self.padding


class MenuItem:
    """A Gtk.MenuItem as menu_height reads one: shown or not, and how tall."""

    def __init__(self, visible, minimum, natural):
        self.visible, self.height = visible, (minimum, natural)

    def get_visible(self):
        return self.visible

    def get_preferred_height(self):
        return self.height


class FakeMenuToplevel:
    """A menu's toplevel: what is asked of it goes in the log the menu shares (#402)."""

    def __init__(self, log):
        self.log = log

    def set_resizable(self, resizable):
        self.log.append(("set_resizable", resizable))

    def set_default_size(self, width, height):
        self.log.append(("set_default_size", width, height))

    def resize(self, width, height):
        self.log.append(("resize", width, height))


class FakeMenu:
    """A Gtk.Menu as popup_menu_at drives one."""

    def __init__(self, items=(), padding=(0, 0), border=0, popup_at_rect=True, width=200):
        self.width = width
        self.items, self.padding, self.border = list(items), Padding(*padding), border
        self.style = StyleContext(self.padding)
        self.properties = {}
        self.opened = []
        self.popped = []
        self.emitted = []
        self.log: list[object] = []
        self.toplevel = FakeMenuToplevel(self.log)
        self.attach = None
        if popup_at_rect:
            self.popup_at_rect = self.record_popup_at_rect

    def get_children(self):
        return self.items

    def get_toplevel(self):
        return self.toplevel

    def get_attach_widget(self):
        return self.attach

    def get_property(self, name):
        return self.properties[name]

    def get_style_context(self):
        return self.style

    def get_border_width(self):
        return self.border

    def set_property(self, name, value):
        self.properties[name] = value

    def record_popup_at_rect(self, window, rect, rect_anchor, menu_anchor, event):
        # What the properties were at the moment GTK was asked, not what they are after.
        self.log.append("popup_at_rect")
        self.opened.append((window, rect, rect_anchor, menu_anchor, event, dict(self.properties)))

    def popup(self, *arguments):
        self.popped.append(arguments)

    def emit(self, name, *arguments):
        self.emitted.append((name, *arguments))


def test_a_menus_height_is_its_shown_items_and_its_padding(app_module, monkeypatch):
    monkeypatch.setattr(app_module.Gtk, "StateFlags", types.SimpleNamespace(NORMAL="normal"))
    menu = FakeMenu(
        [MenuItem(True, 10, 30), MenuItem(False, 500, 600), MenuItem(True, 12, 20)],
        padding=(4, 6),
        border=3,
    )

    # Natural heights, not minimums; the hidden item is not counted; the padding above and
    # below is; the border is counted at both edges.
    assert app_module.menu_height(menu) == 30 + 20 + 4 + 6 + 2 * 3
    assert menu.style.asked == ["normal"]


def test_a_menu_with_nothing_shown_is_as_tall_as_its_padding(app_module):
    menu = FakeMenu([MenuItem(False, 20, 30)], padding=(4, 4))

    assert app_module.menu_height(menu) == 8


class FakeMonitor:
    def __init__(self, workarea):
        self.workarea = workarea

    def get_workarea(self):
        return self.workarea


class Rect:
    def __init__(self, x=0, y=0, width=0, height=0):
        self.x, self.y, self.width, self.height = x, y, width, height


class FakeDisplay:
    """A Gdk.Display of the given backend, whose type name is how app.py tells them apart."""

    def __init__(self, backend, monitor=None):
        self.__gtype__ = types.SimpleNamespace(name=backend)
        self.monitor = monitor
        self.asked = []

    def get_monitor_at_window(self, window):
        self.asked.append(window)
        return self.monitor


class FakeWindow:
    """A Gdk.Window: where it is, how tall its toplevel is, and which display it is on."""

    def __init__(self, display, offset=(0, 0), toplevel=None, height=0, width=0):
        self.display, self.offset, self.toplevel, self.height = display, offset, toplevel, height
        self.width = width

    def get_display(self):
        return self.display

    def get_toplevel(self):
        return self.toplevel or self

    def get_root_coords(self, x, y):
        return x + self.offset[0], y + self.offset[1]

    def get_height(self):
        return self.height

    def get_width(self):
        return self.width


X11, WAYLAND = "GdkX11Display", "GdkWaylandDisplay"


class Allocation:
    def __init__(self, x, y, width, height):
        self.x, self.y, self.width, self.height = x, y, width, height


class FakeChild:
    def __init__(self, allocation):
        self.allocation = allocation

    def get_allocation(self):
        return self.allocation


class FakeGtkWindow:
    """A Gtk.Window as window_content reads one (#402)."""

    def __init__(self, gdk_window, child=None):
        self.gdk_window, self.child = gdk_window, child

    def get_window(self):
        return self.gdk_window

    def get_child(self):
        return self.child


@pytest.fixture
def gtk_windows(app_module, monkeypatch):
    """The list `Gtk.Window.list_toplevels` answers, which a test fills."""
    windows: list[object] = []
    monkeypatch.setattr(
        app_module.Gtk.Window, "list_toplevels", lambda: list(windows), raising=False
    )
    return windows


def test_under_x11_the_room_is_the_work_area_of_the_monitor_the_window_is_on(app_module):
    display = FakeDisplay(X11, FakeMonitor(Rect(0, 27, 1920, 1053)))
    window = FakeWindow(display)

    assert app_module.menu_room(window) == (0, 27, 1920, 1080)
    assert display.asked == [window]


def test_under_x11_there_is_no_room_where_the_window_is_on_no_monitor(app_module):
    assert app_module.menu_room(FakeWindow(FakeDisplay(X11, None))) is None


def test_under_wayland_the_room_is_the_toplevels_own_span(app_module, gtk_windows):
    """Its top is where GDK says it is, which is 0 for a window with no parent, and
    nothing is asked of a monitor: a client is not told where its window is."""
    display = FakeDisplay(WAYLAND, FakeMonitor(Rect(0, 0, 3840, 2160)))
    toplevel = FakeWindow(display, offset=(11, 37), height=600, width=800)
    child = FakeWindow(display, offset=(5, 200), toplevel=toplevel)

    assert app_module.menu_room(child) == (11, 37, 811, 637)
    assert display.asked == []


def test_under_wayland_the_room_is_the_windows_content_not_its_shadow(app_module, gtk_windows):
    """Measured on Weston 14: a GdkWindow 1920x282, its child at (26, 67, 1868, 186)."""
    display = FakeDisplay(WAYLAND)
    toplevel = FakeWindow(display, height=282, width=1920)
    other = FakeWindow(display, height=10, width=10)
    gtk_windows.append(FakeGtkWindow(other, FakeChild(Allocation(1, 1, 5, 5))))
    gtk_windows.append(FakeGtkWindow(toplevel, FakeChild(Allocation(26, 67, 1868, 186))))

    assert app_module.menu_room(toplevel) == (26, 67, 1894, 253)


def test_under_wayland_a_window_with_no_child_is_its_gdk_windows_span(app_module, gtk_windows):
    display = FakeDisplay(WAYLAND)
    toplevel = FakeWindow(display, height=282, width=1920)
    gtk_windows.append(FakeGtkWindow(toplevel, None))

    assert app_module.menu_room(toplevel) == (0, 0, 1920, 282)


def test_a_room_with_no_height_is_no_room(app_module, gtk_windows):
    display = FakeDisplay(WAYLAND)

    assert app_module.menu_room(FakeWindow(display, height=0, width=800)) is None
    assert app_module.menu_room(FakeWindow(display, height=600, width=0)) is None
    assert (
        app_module.menu_room(FakeWindow(FakeDisplay(X11, FakeMonitor(Rect(0, 0, 10, 0))))) is None
    )
    assert (
        app_module.menu_room(FakeWindow(FakeDisplay(X11, FakeMonitor(Rect(0, 0, 0, 10))))) is None
    )


def test_a_menus_width_is_what_the_class_vfunc_gives(app_module, monkeypatch):
    asked = []

    def vfunc(menu):
        asked.append(menu)
        return (10, 555)

    monkeypatch.setattr(app_module.Gtk.Menu, "do_get_preferred_width", vfunc, raising=False)
    menu = FakeMenu()

    assert app_module.menu_width(menu) == 555
    assert asked == [menu]


# A fake of the enumerations: the real values, which the last test here holds them to.
ANCHOR_HINTS = types.SimpleNamespace(FLIP=3, SLIDE=12, RESIZE_X=16, RESIZE_Y=32, RESIZE=48)
GRAVITY = types.SimpleNamespace(
    SOUTH_WEST="south-west",
    NORTH_WEST="north-west",
    SOUTH_EAST="south-east",
    NORTH_EAST="north-east",
)
ALL_HINTS = 3 | 12 | 16 | 32
SCROLLING_HINTS = 3 | 12 | 16


@pytest.fixture
def popping(app_module, monkeypatch):
    """app_module with the enumerations and the rectangle popup_menu_at uses, and a screen
    of 1080 pixels under X11 for the window it is given."""
    monkeypatch.setattr(app_module.Gdk, "AnchorHints", ANCHOR_HINTS, raising=False)
    monkeypatch.setattr(app_module.Gdk, "Gravity", GRAVITY, raising=False)
    monkeypatch.setattr(app_module.Gdk, "Rectangle", Rect, raising=False)
    monkeypatch.setattr(app_module.Gtk, "StateFlags", types.SimpleNamespace(NORMAL=0))
    monkeypatch.setattr(app_module.Gtk.Window, "list_toplevels", lambda: [], raising=False)
    monkeypatch.setattr(app_module.Gtk, "get_current_event_time", lambda: 777, raising=False)
    monkeypatch.setattr(
        app_module.Gtk.Menu,
        "do_get_preferred_width",
        lambda menu: (0, menu.width),
        raising=False,
    )
    return app_module


def screen_window(offset=(0, 0)):
    return FakeWindow(FakeDisplay(X11, FakeMonitor(Rect(0, 0, 1920, 1080))), offset=offset)


def click(window, x=40, y=300, button=3, stamp=1234):
    return types.SimpleNamespace(window=window, x=float(x), y=float(y), button=button, time=stamp)


def tall(height):
    """A menu `height` pixels tall: one item, and no padding."""
    return FakeMenu([MenuItem(True, height, height)])


def test_without_popup_at_rect_the_older_call_opens_the_menu(popping):
    menu = FakeMenu(popup_at_rect=False)
    event = click(screen_window())

    popping.popup_menu_at(menu, event)

    assert menu.popped == [(None, None, None, None, 3, 1234)]


def test_a_menu_is_scrolled_back_to_its_top_once_it_is_open(popping):
    """GTK keeps a menu's scroll position from one opening to the next (#408), on either
    call; the scenarios hold what the scroll does against real GTK."""
    for older in (False, True):
        menu = FakeMenu(popup_at_rect=not older)
        popping.popup_menu_at(menu, click(screen_window()), rect=None, window=screen_window())

        assert [name for name, *_ in menu.emitted] == ["scroll-event"]
        assert menu.opened or menu.popped


def test_the_older_call_takes_the_current_time_where_there_is_no_event(popping):
    menu = FakeMenu(popup_at_rect=False)

    popping.popup_menu_at(menu, None)

    assert menu.popped == [(None, None, None, None, 0, 777)]


def test_the_older_call_takes_the_current_time_for_an_event_with_none(popping):
    """A key event, as the keyboard opens the console list with: no button either."""
    menu = FakeMenu(popup_at_rect=False)

    popping.popup_menu_at(menu, types.SimpleNamespace())

    assert menu.popped == [(None, None, None, None, 0, 777)]


def test_a_menu_opens_at_the_click_in_the_window_that_received_it(popping):
    window = screen_window()
    event = click(window, x=40.9, y=300.2)
    menu = tall(100)

    popping.popup_menu_at(menu, event)

    [(rect_window, rect, _ra, _ma, trigger, _properties)] = menu.opened
    assert rect_window is window and trigger is event
    assert (rect.x, rect.y, rect.width, rect.height) == (40, 300, 1, 1)


def test_the_click_is_judged_where_it_is_on_the_screen_not_in_its_window(popping):
    """The window is 500 pixels down, so a click at 300 in it is at 800, with 279 below."""
    menu = tall(400)

    popping.popup_menu_at(menu, click(screen_window(offset=(0, 500)), y=300))

    [(_w, _r, rect_anchor, menu_anchor, _e, _p)] = menu.opened
    assert (rect_anchor, menu_anchor) == (GRAVITY.NORTH_WEST, GRAVITY.SOUTH_WEST)


def test_a_menu_that_fits_below_hangs_from_the_click(popping):
    menu = tall(400)

    popping.popup_menu_at(menu, click(screen_window(), y=300))

    [(_w, _r, rect_anchor, menu_anchor, _e, properties)] = menu.opened
    assert (rect_anchor, menu_anchor) == (GRAVITY.SOUTH_WEST, GRAVITY.NORTH_WEST)
    assert properties == {"anchor-hints": ALL_HINTS, "rect-anchor-dy": 0, "rect-anchor-dx": 0}


def test_a_menu_that_fits_above_stands_on_the_click(popping):
    menu = tall(400)

    popping.popup_menu_at(menu, click(screen_window(), y=900))

    [(_w, _r, rect_anchor, menu_anchor, _e, properties)] = menu.opened
    assert (rect_anchor, menu_anchor) == (GRAVITY.NORTH_WEST, GRAVITY.SOUTH_WEST)
    assert properties == {"anchor-hints": ALL_HINTS, "rect-anchor-dy": 0, "rect-anchor-dx": 0}


def test_a_menu_that_fits_neither_side_is_slid_by_the_anchors_offset(popping):
    """821 pixels at 300 on a screen of 1080: the click ends at 301, so the menu is lifted
    by 1080 - 821 - 301 to start at 259."""
    menu = tall(821)

    popping.popup_menu_at(menu, click(screen_window(), y=300))

    [(_w, _r, rect_anchor, menu_anchor, _e, properties)] = menu.opened
    assert (rect_anchor, menu_anchor) == (GRAVITY.SOUTH_WEST, GRAVITY.NORTH_WEST)
    assert properties == {
        "anchor-hints": ALL_HINTS,
        "rect-anchor-dy": 1080 - 821 - 301,
        "rect-anchor-dx": 0,
    }


def test_a_menu_taller_than_the_screen_is_cut_to_the_room_beside_the_click(popping):
    menu = tall(1500)

    popping.popup_menu_at(menu, click(screen_window(), y=300))

    [(*_head, properties)] = menu.opened
    assert properties == {
        "anchor-hints": SCROLLING_HINTS,
        "rect-anchor-dy": 0,
        "rect-anchor-dx": 0,
    }
    # Resizable first, then the default size and the size itself, all before GTK is asked
    # (#402): a menu reopened with another cut is placed by the size it had, else.
    assert menu.log == [
        ("set_resizable", True),
        ("set_default_size", -1, 779),
        ("resize", 200, 779),
        "popup_at_rect",
    ]


def test_a_tall_menu_low_on_the_screen_stands_above_the_click_cut_to_it(popping):
    menu = tall(1500)

    popping.popup_menu_at(menu, click(screen_window(), y=900))

    [(_w, _r, rect_anchor, menu_anchor, _e, properties)] = menu.opened
    assert (rect_anchor, menu_anchor) == (GRAVITY.NORTH_WEST, GRAVITY.SOUTH_WEST)
    assert properties["rect-anchor-dy"] == 0
    assert ("set_default_size", -1, 900) in menu.log


def test_a_cut_menu_opened_again_as_a_short_one_gets_its_size_back(popping):
    menu = FakeMenu([MenuItem(True, 1500, 1500)])
    window = screen_window()
    popping.popup_menu_at(menu, click(window, y=300))
    menu.items[0].height = (100, 100)
    menu.log.clear()

    popping.popup_menu_at(menu, click(window, y=300))

    assert menu.log == [
        ("set_default_size", -1, -1),
        ("set_resizable", False),
        "popup_at_rect",
    ]


def test_a_menu_opened_again_is_given_its_placement_again(popping):
    """One menu is opened over and over: a slide, or hints taken for a tall list, must not
    stay for the next time."""
    menu = FakeMenu([MenuItem(True, 100, 100)])
    window = screen_window()
    menu.items[0].height = (1500, 1500)
    popping.popup_menu_at(menu, click(window, y=300))
    menu.items[0].height = (100, 100)

    popping.popup_menu_at(menu, click(window, y=300))

    assert menu.opened[0][-1] == {
        "anchor-hints": SCROLLING_HINTS,
        "rect-anchor-dy": 0,
        "rect-anchor-dx": 0,
    }
    assert menu.opened[1][-1] == {
        "anchor-hints": ALL_HINTS,
        "rect-anchor-dy": 0,
        "rect-anchor-dx": 0,
    }


def test_a_rectangle_and_a_window_given_are_used_in_place_of_the_click(popping):
    """The console button's allocation, in the window the button is drawn in."""
    window = screen_window(offset=(0, 700))
    elsewhere = screen_window()
    rect = Rect(1000, 10, 40, 30)
    menu = tall(600)

    popping.popup_menu_at(menu, click(elsewhere), rect, window)

    [(rect_window, opened, rect_anchor, menu_anchor, _e, properties)] = menu.opened
    assert rect_window is window and opened is rect
    # 710 to 740 on the screen: 340 below it, 710 above, so above.
    assert (rect_anchor, menu_anchor) == (GRAVITY.NORTH_WEST, GRAVITY.SOUTH_WEST)
    assert properties["rect-anchor-dy"] == 0


def test_east_hangs_the_menus_right_edge_from_the_rectangles(popping):
    window = screen_window()
    below, above = tall(200), tall(600)

    popping.popup_menu_at(below, None, Rect(1800, 100, 40, 30), window, east=True)
    popping.popup_menu_at(above, None, Rect(1800, 900, 40, 30), window, east=True)

    assert below.opened[0][2:4] == (GRAVITY.SOUTH_EAST, GRAVITY.NORTH_EAST)
    assert above.opened[0][2:4] == (GRAVITY.NORTH_EAST, GRAVITY.SOUTH_EAST)


def wide(width, height=100):
    return FakeMenu([MenuItem(True, height, height)], width=width)


def test_a_menu_near_the_right_edge_opens_leftwards(popping):
    menu = wide(555)

    popping.popup_menu_at(menu, click(screen_window(), x=1900, y=300))

    [(_w, _r, rect_anchor, menu_anchor, _e, properties)] = menu.opened
    assert (rect_anchor, menu_anchor) == (GRAVITY.SOUTH_EAST, GRAVITY.NORTH_EAST)
    assert properties["rect-anchor-dx"] == 0


def test_a_menu_in_the_middle_opens_rightwards(popping):
    menu = wide(555)

    popping.popup_menu_at(menu, click(screen_window(), x=900, y=300))

    [(_w, _r, rect_anchor, menu_anchor, _e, properties)] = menu.opened
    assert (rect_anchor, menu_anchor) == (GRAVITY.SOUTH_WEST, GRAVITY.NORTH_WEST)
    assert properties["rect-anchor-dx"] == 0


def test_a_menu_that_fits_neither_way_in_a_narrow_window_is_slid(popping):
    """A toplevel 400 wide at x 100, a menu of 300, a click at 250 (150 in): 250 of room
    on the right and 151 on the left, so rightwards, moved left by 50."""
    display = FakeDisplay(WAYLAND, FakeMonitor(Rect(0, 0, 3840, 2160)))
    toplevel = FakeWindow(display, offset=(100, 0), height=600, width=400)
    window = FakeWindow(display, offset=(100, 0), toplevel=toplevel)
    menu = wide(300)

    popping.popup_menu_at(menu, click(window, x=150, y=100))

    [(_w, _r, rect_anchor, menu_anchor, _e, properties)] = menu.opened
    assert (rect_anchor, menu_anchor) == (GRAVITY.SOUTH_WEST, GRAVITY.NORTH_WEST)
    assert properties["rect-anchor-dx"] == -50


def test_east_opens_leftwards_where_there_is_room_on_the_left(popping):
    menu = wide(300)

    popping.popup_menu_at(menu, None, Rect(1800, 100, 40, 30), screen_window(), east=True)

    assert menu.opened[0][2:4] == (GRAVITY.SOUTH_EAST, GRAVITY.NORTH_EAST)
    assert menu.opened[0][-1]["rect-anchor-dx"] == 0


def test_east_opens_rightwards_where_the_button_is_at_the_left_of_a_narrow_room(popping):
    menu = wide(300)

    popping.popup_menu_at(menu, None, Rect(10, 100, 40, 30), screen_window(), east=True)

    assert menu.opened[0][2:4] == (GRAVITY.SOUTH_WEST, GRAVITY.NORTH_WEST)
    assert menu.opened[0][-1]["rect-anchor-dx"] == 0


def test_the_slide_across_does_not_stay_for_the_next_opening(popping):
    display = FakeDisplay(WAYLAND, FakeMonitor(Rect(0, 0, 3840, 2160)))
    window = FakeWindow(display, height=600, width=400)
    menu = wide(300)

    popping.popup_menu_at(menu, click(window, x=150, y=100))
    popping.popup_menu_at(menu, click(window, x=10, y=100))

    assert menu.opened[0][-1]["rect-anchor-dx"] == -50
    assert menu.opened[1][-1]["rect-anchor-dx"] == 0


def test_where_the_room_cannot_be_told_the_menu_opens_rightwards_unless_east(popping):
    window = FakeWindow(FakeDisplay(X11, None))
    west, east = wide(300), wide(300)

    popping.popup_menu_at(west, click(window, x=1900))
    popping.popup_menu_at(east, click(window, x=1900), east=True)

    assert west.opened[0][2:4] == (GRAVITY.SOUTH_WEST, GRAVITY.NORTH_WEST)
    assert east.opened[0][2:4] == (GRAVITY.SOUTH_EAST, GRAVITY.NORTH_EAST)
    assert west.opened[0][-1]["rect-anchor-dx"] == 0 == east.opened[0][-1]["rect-anchor-dx"]


def test_where_the_room_cannot_be_told_gtk_is_left_to_place_the_menu(popping):
    """No monitor: below, as GTK would have it, with all its hints."""
    window = FakeWindow(FakeDisplay(X11, None))
    menu = tall(5000)

    popping.popup_menu_at(menu, click(window, y=900))

    [(_w, _r, rect_anchor, menu_anchor, _e, properties)] = menu.opened
    assert (rect_anchor, menu_anchor) == (GRAVITY.SOUTH_WEST, GRAVITY.NORTH_WEST)
    assert properties == {"anchor-hints": ALL_HINTS, "rect-anchor-dy": 0, "rect-anchor-dx": 0}


def test_under_wayland_the_window_is_the_room(popping, gtk_windows):
    """A window 600 tall on an output of 2160: a menu of 400 opened 500 down it does not
    fit below, though the output has room, and stands on the click instead."""
    display = FakeDisplay(WAYLAND, FakeMonitor(Rect(0, 0, 3840, 2160)))
    window = FakeWindow(display, height=600, width=800)
    menu = tall(400)

    popping.popup_menu_at(menu, click(window, y=500))

    [(_w, _r, rect_anchor, menu_anchor, _e, properties)] = menu.opened
    assert (rect_anchor, menu_anchor) == (GRAVITY.NORTH_WEST, GRAVITY.SOUTH_WEST)
    assert properties["rect-anchor-dy"] == 0


# -- a menu GTK places, with fakes (#397) ----------------------------------------------------


class AttachItem:
    """The widget a menu hangs from, as fit_placed_menu reads it: its window, where it is in
    that window, and its parent."""

    def __init__(self, window, y, height=30, parent=None):
        self.window, self.area, self.parent = window, Allocation(0, y, 100, height), parent

    def get_window(self):
        return self.window

    def get_allocation(self):
        return self.area

    def get_parent(self):
        return self.parent


@pytest.fixture
def placed(popping, monkeypatch):
    """`popping`, and a `Gtk.Menu` class a menu's parent can be an instance of."""

    class GtkMenu:
        @staticmethod
        def do_get_preferred_width(menu):
            return (0, menu.width)

    monkeypatch.setattr(popping.Gtk, "Menu", GtkMenu, raising=False)
    return popping


def gtk_menu(app_module, height, dy=-8, hints=ALL_HINTS):
    """A menu as GTK has just set it to open: its hints and offset, hung from nothing yet."""
    menu = tall(height)
    menu.properties.update({"anchor-hints": hints, "rect-anchor-dy": dy})
    return menu


def beside_item(app_module, window, y):
    return AttachItem(window, y, parent=app_module.Gtk.Menu())


def test_a_submenu_that_fits_keeps_what_gtk_set(placed):
    window = screen_window()
    menu = gtk_menu(placed, 200)
    menu.attach = beside_item(placed, window, 300)

    placed.fit_placed_menu(menu, FakeGtkWindow(window))

    assert menu.properties == {"anchor-hints": ALL_HINTS, "rect-anchor-dy": -8}
    assert menu.log == [("set_default_size", -1, -1), ("set_resizable", False)]


def test_a_submenu_that_runs_past_the_screen_is_slid_up_by_adding_to_gtks_offset(placed):
    window = screen_window()
    menu = gtk_menu(placed, 400)
    menu.attach = beside_item(placed, window, 1000)

    placed.fit_placed_menu(menu, FakeGtkWindow(window))

    # GTK's -8 puts its top at 992, and 992 + 400 is past 1080: up by 312, to 680.
    assert menu.properties["rect-anchor-dy"] == -8 - 312
    assert menu.properties["anchor-hints"] == ALL_HINTS


def test_a_submenu_taller_than_the_screen_is_cut_and_loses_resize_y(placed):
    window = screen_window()
    menu = gtk_menu(placed, 1500)
    menu.attach = beside_item(placed, window, 300)

    placed.fit_placed_menu(menu, FakeGtkWindow(window))

    assert menu.properties == {
        "anchor-hints": SCROLLING_HINTS,
        # From the low edge: GTK's top is 292, so up by 292.
        "rect-anchor-dy": -8 - 292,
    }
    assert menu.log == [
        ("set_resizable", True),
        ("set_default_size", -1, 1080),
        ("resize", 200, 1080),
    ]


def test_a_submenu_cut_and_opened_again_as_a_short_one_gets_its_size_back(placed):
    window = screen_window()
    menu = gtk_menu(placed, 1500)
    menu.attach = beside_item(placed, window, 300)
    holder = FakeGtkWindow(window)
    placed.fit_placed_menu(menu, holder)
    menu.items[0].height = (100, 100)
    menu.properties.update({"anchor-hints": ALL_HINTS, "rect-anchor-dy": -8})
    menu.log.clear()

    placed.fit_placed_menu(menu, holder)

    assert menu.log == [("set_default_size", -1, -1), ("set_resizable", False)]
    assert menu.properties == {"anchor-hints": ALL_HINTS, "rect-anchor-dy": -8}


def wayland_holder(placed, monkeypatch, content_top=67):
    """A holder under Wayland whose content starts `content_top` down its GdkWindow, and
    spans 500 pixels: the room is 67 to 567."""
    display = FakeDisplay(WAYLAND)
    holder_window = FakeWindow(display, height=700, width=1000)
    holder = FakeGtkWindow(holder_window, FakeChild(Allocation(26, content_top, 900, 500)))
    monkeypatch.setattr(placed.Gtk.Window, "list_toplevels", lambda: [holder], raising=False)
    return display, holder_window, holder


def test_under_wayland_a_submenus_item_in_a_popup_has_the_content_top_added(placed, monkeypatch):
    display, holder_window, holder = wayland_holder(placed, monkeypatch)
    # The popup the parent menu is drawn in: its coordinates are against the content.
    popup = FakeWindow(display, offset=(0, 10))
    menu = gtk_menu(placed, 300)
    menu.attach = beside_item(placed, popup, 400)

    placed.fit_placed_menu(menu, holder)

    # 10 + 400 + 67 = 477, GTK's offset -8 makes 469; 469 + 300 is past 567: up to 267.
    assert menu.properties["rect-anchor-dy"] == -8 + (267 - 469)


def test_under_wayland_an_item_in_the_holders_own_window_has_nothing_added(placed, monkeypatch):
    _display, holder_window, holder = wayland_holder(placed, monkeypatch)
    menu = gtk_menu(placed, 300)
    menu.attach = beside_item(placed, holder_window, 400)

    placed.fit_placed_menu(menu, holder)

    # 400 - 8 = 392; 392 + 300 is past 567: up to 267.
    assert menu.properties["rect-anchor-dy"] == -8 + (267 - 392)


def test_a_menu_from_the_menu_bar_hangs_below_its_item_whatever_it_had_before(placed):
    window = screen_window()
    menu = gtk_menu(placed, 200, dy=-50)
    menu.attach = AttachItem(window, 20, parent=object())

    placed.fit_placed_menu(menu, FakeGtkWindow(window))

    assert menu.properties["rect-anchor-dy"] == 0


def test_a_menu_from_the_menu_bar_low_in_the_window_stands_above_its_item(placed):
    window = screen_window()
    menu = gtk_menu(placed, 200, dy=0)
    menu.attach = AttachItem(window, 1050, parent=object())

    placed.fit_placed_menu(menu, FakeGtkWindow(window))

    # Hung from the item's bottom by GTK, so up by the item's height and the menu's.
    assert menu.properties["rect-anchor-dy"] == -30 - 200


def test_a_menu_from_the_menu_bar_taller_than_the_screen_is_cut_below_its_item(placed):
    window = screen_window()
    menu = gtk_menu(placed, 1500, dy=0)
    menu.attach = AttachItem(window, 20, parent=object())

    placed.fit_placed_menu(menu, FakeGtkWindow(window))

    assert menu.properties["rect-anchor-dy"] == 0
    assert menu.properties["anchor-hints"] == SCROLLING_HINTS
    assert ("set_default_size", -1, 1030) in menu.log


def test_a_menu_with_no_item_window_or_room_is_left_as_gtk_set_it(placed):
    window = screen_window()
    holder = FakeGtkWindow(window)
    left = {"anchor-hints": ALL_HINTS, "rect-anchor-dy": -8}
    # No widget it hangs from.
    menu = gtk_menu(placed, 1500)
    placed.fit_placed_menu(menu, holder)
    assert (menu.properties, menu.log) == (left, [])
    # The item has no window.
    menu = gtk_menu(placed, 1500)
    menu.attach = beside_item(placed, None, 300)
    placed.fit_placed_menu(menu, holder)
    assert (menu.properties, menu.log) == (left, [])
    # The holder has none.
    menu = gtk_menu(placed, 1500)
    menu.attach = beside_item(placed, window, 300)
    placed.fit_placed_menu(menu, FakeGtkWindow(None))
    assert (menu.properties, menu.log) == (left, [])
    # No room: the window is on no monitor.
    nowhere = FakeWindow(FakeDisplay(X11, None))
    menu = gtk_menu(placed, 1500)
    menu.attach = beside_item(placed, nowhere, 300)
    placed.fit_placed_menu(menu, FakeGtkWindow(nowhere))
    assert (menu.properties, menu.log) == (left, [])


def test_every_menu_gtk_places_is_given_the_handler(app_module):
    """The Hosts menu, each folder's submenu and the cluster window's Snippets button: a
    menu added without it runs off the screen under Weston again (#397)."""
    source = Path(app_module.__file__).read_text()

    assert len(re.findall(r'\.connect\("show", fit_placed_menu, ', source)) == 3
    assert "def cut_menu(" in source


def test_the_fakes_match_real_gtk():
    """conftest stubs gi, so a fake can offer what GTK does not have (#30, #41)."""
    gi = pytest.importorskip("gi", reason="PyGObject not available")
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, Gtk

    for fake, real, names in (
        (
            FakeMenu,
            Gtk.Menu,
            (
                "get_children",
                "get_toplevel",
                "get_attach_widget",
                "get_property",
                "get_style_context",
                "get_border_width",
                "set_property",
                "popup",
                "emit",
            ),
        ),
        (StyleContext, Gtk.StyleContext, ("get_padding",)),
        (MenuItem, Gtk.MenuItem, ("get_visible", "get_preferred_height")),
        (FakeMonitor, Gdk.Monitor, ("get_workarea",)),
        (FakeDisplay, Gdk.Display, ("get_monitor_at_window",)),
        (
            FakeWindow,
            Gdk.Window,
            ("get_display", "get_toplevel", "get_root_coords", "get_height", "get_width"),
        ),
        (FakeMenuToplevel, Gtk.Window, ("set_resizable", "set_default_size", "resize")),
        (FakeGtkWindow, Gtk.Window, ("get_window", "get_child")),
        (FakeChild, Gtk.Widget, ("get_allocation",)),
        (AttachItem, Gtk.Widget, ("get_window", "get_allocation", "get_parent")),
    ):
        for name in names:
            assert hasattr(fake, name), f"{fake.__name__} is missing {name}"
            assert hasattr(real, name), f"{real.__name__} has no {name}"
    # FakeMenu has popup_at_rect on an instance only when a test asks, as a menu on older GTK
    # lacks it; the real class has it.
    assert hasattr(Gtk.Menu, "popup_at_rect")
    assert hasattr(Gtk.Window, "list_toplevels")
    assert {"anchor-hints", "rect-anchor-dy", "rect-anchor-dx"} <= {
        p.name for p in Gtk.Menu.list_properties()
    }
    assert hasattr(Gtk.Menu, "do_get_preferred_width")
    assert hasattr(Gtk, "get_current_event_time")
    # The values the fake enumerations hold.
    for name in ("FLIP", "SLIDE", "RESIZE_X", "RESIZE_Y", "RESIZE"):
        assert int(getattr(Gdk.AnchorHints, name)) == getattr(ANCHOR_HINTS, name), name
    for name in vars(GRAVITY):
        assert hasattr(Gdk.Gravity, name), name
    every = int(Gdk.AnchorHints.FLIP | Gdk.AnchorHints.SLIDE | Gdk.AnchorHints.RESIZE)
    scrolling = int(Gdk.AnchorHints.FLIP | Gdk.AnchorHints.SLIDE | Gdk.AnchorHints.RESIZE_X)
    assert (every, scrolling) == (ALL_HINTS, SCROLLING_HINTS)
    # And the type name that tells the backends apart.
    display = Gdk.Display.get_default()
    if display is not None:
        assert display.__gtype__.name in {"GdkX11Display", "GdkWaylandDisplay"}


# -- the wheel hook, with fakes (#399) --------------------------------------------------------------


class WheelItem:
    def __init__(self, height, visible=True):
        self.height, self.visible = height, visible

    def get_visible(self):
        return self.visible

    def get_allocated_height(self):
        return self.height


class WheelSeparator(WheelItem):
    pass


class WheelMenu(FakeMenu):
    pass


class WheelEvent:
    """A Gdk.Event as the hook reads and the code that makes one sets."""

    def __init__(self, kind=None):
        self.kind, self.device = kind, None
        self.deltas, self.scroll_direction = (False, 0.0, 0.0), (False, None)
        self.direction = self.delta_y = None

    def set_source_device(self, device):
        self.device = device

    def get_source_device(self):
        return self.device

    def get_scroll_deltas(self):
        return self.deltas

    def get_scroll_direction(self):
        return self.scroll_direction


DIRECTION = types.SimpleNamespace(UP="up", DOWN="down", SMOOTH="smooth")


@pytest.fixture
def wheel(app_module, monkeypatch):
    monkeypatch.setattr(app_module.Gtk, "Menu", WheelMenu)
    monkeypatch.setattr(app_module.Gtk, "SeparatorMenuItem", WheelSeparator, raising=False)
    monkeypatch.setattr(
        app_module.Gdk, "Event", types.SimpleNamespace(new=WheelEvent), raising=False
    )
    monkeypatch.setattr(
        app_module.Gdk, "EventType", types.SimpleNamespace(SCROLL="scroll"), raising=False
    )
    monkeypatch.setattr(app_module.Gdk, "ScrollDirection", DIRECTION, raising=False)
    return app_module


DEVICE = object()


def notch(direction=None, smooth=None, device=DEVICE):
    event = WheelEvent()
    event.device = device
    if smooth is not None:
        event.deltas = (True, 0.0, smooth)
    else:
        event.scroll_direction = (True, direction)
    return event


def wheel_menu(*heights):
    return WheelMenu([WheelItem(height) for height in heights])


def test_a_discrete_notch_emits_one_smooth_event_of_the_extra(wheel):
    menu = wheel_menu(40, 67, 40)
    for direction, delta in ((DIRECTION.DOWN, 1.0), (DIRECTION.UP, -1.0)):
        del menu.emitted[:]
        assert wheel.scroll_menu_by_rows(menu, notch(direction)) is True
        [(name, sent)] = menu.emitted
        assert name == "scroll-event"
        assert sent.direction == DIRECTION.SMOOTH and sent.kind == "scroll"
        assert sent.delta_y == wheel_extra(delta, 40)
        assert sent.delta_y != 0


def test_a_smooth_scroll_emits_the_extra_for_its_own_delta(wheel):
    menu = wheel_menu(40, 67)

    assert wheel.scroll_menu_by_rows(menu, notch(smooth=0.3)) is True

    [(_name, sent)] = menu.emitted
    assert sent.delta_y == wheel_extra(0.3, 40)


def test_an_event_with_no_source_device_emits_nothing(wheel):
    menu = wheel_menu(40)
    assert wheel.scroll_menu_by_rows(menu, notch(DIRECTION.DOWN, device=None)) is True
    assert menu.emitted == []
    # The event reset_menu_scroll emits, and the hook's own fed back to it.
    wheel.reset_menu_scroll(menu)
    [(_name, reset)] = menu.emitted
    assert reset.get_source_device() is None
    del menu.emitted[:]
    assert wheel.scroll_menu_by_rows(menu, reset) is True
    assert menu.emitted == []
    wheel.scroll_menu_by_rows(menu, notch(DIRECTION.DOWN))
    [(_name, own)] = menu.emitted
    del menu.emitted[:]
    assert wheel.scroll_menu_by_rows(menu, own) is True
    assert menu.emitted == []


def test_a_widget_that_is_not_a_menu_emits_nothing_and_every_path_returns_true(wheel):
    other = FakeMenu([WheelItem(40)])
    assert wheel.scroll_menu_by_rows(other, notch(DIRECTION.DOWN)) is True
    assert other.emitted == []
    menu = wheel_menu(40)
    for event in (notch("left"), notch(smooth=0.0), notch(DIRECTION.DOWN)):
        assert wheel.scroll_menu_by_rows(menu, event) is True
    # No direction at all, and a menu with no row.
    event = WheelEvent()
    event.device = object()
    assert wheel.scroll_menu_by_rows(menu, event) is True
    assert wheel.scroll_menu_by_rows(WheelMenu(), notch(DIRECTION.DOWN)) is True


def test_separators_and_hidden_items_do_not_set_the_row(wheel):
    menu = WheelMenu(
        [WheelSeparator(3), WheelItem(10, visible=False), WheelItem(40), WheelItem(67)]
    )
    assert wheel.menu_row_height(menu) == 40
    assert wheel.menu_row_height(WheelMenu([WheelSeparator(3)])) is None


def test_the_hook_is_installed_once(wheel, monkeypatch):
    calls = []
    monkeypatch.setattr(
        wheel.GObject,
        "add_emission_hook",
        lambda *arguments: calls.append(arguments),
        raising=False,
    )

    wheel.install_menu_wheel()
    wheel.install_menu_wheel()

    assert calls == [(WheelMenu, "scroll-event", wheel.scroll_menu_by_rows)]


def test_startup_installs_the_hook(app_module, monkeypatch):
    monkeypatch.setattr(app_module.Gtk.Application, "do_startup", lambda *_a: None, raising=False)
    app = app_module.GcmApplication()
    installed = []
    monkeypatch.setattr(app_module, "install_menu_wheel", lambda: installed.append(True))
    monkeypatch.setattr(app, "_create_action", lambda *a, **k: None)
    monkeypatch.setattr(app, "_create_stateful_action", lambda *a, **k: None)
    monkeypatch.setattr(app, "_build_menus", lambda: None)

    app.do_startup()

    assert installed == [True]


def test_the_wheel_fakes_match_real_gtk():
    gi = pytest.importorskip("gi", reason="PyGObject not available")
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, GObject, Gtk

    for fake, real, names in (
        (
            WheelEvent,
            Gdk.Event,
            ("get_source_device", "get_scroll_deltas", "get_scroll_direction", "set_source_device"),
        ),
        (WheelItem, Gtk.MenuItem, ("get_visible", "get_allocated_height")),
    ):
        for name in names:
            assert hasattr(fake, name), f"{fake.__name__} is missing {name}"
            assert hasattr(real, name), f"{real.__name__} has no {name}"
    assert hasattr(GObject, "add_emission_hook")
    for name in vars(DIRECTION):
        assert hasattr(Gdk.ScrollDirection, name), name


def test_every_menu_is_opened_by_the_one_helper(app_module):
    """The server tree's, the terminal's, a tab's, the Mounted tab's and the console list:
    nothing asks GTK to open a menu by another way, or places one by a guess of its height
    again (#392). A sixth menu goes through the helper, or this fails."""
    source = Path(app_module.__file__).read_text()

    assert len(re.findall(r"(?<!def )\bpopup_menu_at\(", source)) == 5
    assert re.findall(r"\.popup_at_\w+\(", source) == [".popup_at_rect("]
    assert re.findall(r"\.popup\(", source) == [".popup("]
    assert "menu_height = 250" not in source


# -- against real GTK ----------------------------------------------------------------------------

_SCRIPT = r'''
import ctypes, faulthandler, os, sys, time
faulthandler.dump_traceback_later(100, exit=True)
scenario, scratch = sys.argv[1], sys.argv[2]
# The scenarios named so leave GTK its hints, as they are on X11, where GTK moves a menu
# itself: GCM's own must not undo what GCM has worked out.
KEEP_HINTS = scenario.endswith("-with-its-hints")
scenario = scenario.removesuffix("-with-its-hints")
os.environ["HOME"] = os.path.join(scratch, "home")
os.makedirs(os.environ["HOME"], exist_ok=True)
os.environ["XDG_RUNTIME_DIR"] = os.path.join(scratch, "run")
os.makedirs(os.environ["XDG_RUNTIME_DIR"], mode=0o700, exist_ok=True)
os.environ["SHELL"] = "/bin/sh"
sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gdk, Gtk
from gnome_connection_manager import app

app.conf.STARTUP_LOCAL = False
app.conf.CHECK_UPDATES = False
# A right-click pastes by default, and Ctrl+right-click opens the menu.
app.conf.PASTE_ON_RIGHT_CLICK = False
application = app.GcmApplication()
assert application.register(None)
application.activate()
w = application._controller
shown = []
app.msgbox = shown.append
app.msginfo = shown.append

display = Gdk.Display.get_default()
workarea = (display.get_primary_monitor() or display.get_monitor(0)).get_workarea()
SCREEN_TOP, SCREEN_BOTTOM = workarea.y, workarea.y + workarea.height
SCREEN_LEFT, SCREEN_RIGHT = workarea.x, workarea.x + workarea.width

def pump(seconds=0.2):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        Gtk.main_iteration_do(False)
        time.sleep(0.005)

def until(condition, seconds=10):
    end = time.monotonic() + seconds
    while time.monotonic() < end and not condition():
        Gtk.main_iteration_do(False)
        time.sleep(0.005)
    return condition()

def ssh_host(name, address, group=""):
    return app.Host(group, name, "", address, "eric", "", "", "22", "", "ssh", "")

def real_input():
    """Real clicks, through XTest, on the scenario's own display."""
    x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
    xtst = ctypes.cdll.LoadLibrary("libXtst.so.6")
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XFlush.argtypes = [ctypes.c_void_p]
    xtst.XTestFakeButtonEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
    xtst.XTestFakeMotionEvent.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong
    ]
    xdisplay = x11.XOpenDisplay(None)
    assert xdisplay, "no connection to the display for XTest"

    def click(number, x, y):
        xtst.XTestFakeMotionEvent(xdisplay, -1, int(x), int(y), 0)
        x11.XFlush(xdisplay)
        pump(0.1)
        xtst.XTestFakeButtonEvent(xdisplay, number, True, 0)
        xtst.XTestFakeButtonEvent(xdisplay, number, False, 0)
        x11.XFlush(xdisplay)

    return click

click = real_input()

# What GCM asked of GTK, each time a menu was opened. A compositor that moves no menu leaves
# it where it was asked to be, and X11 does the same for a menu with no hints at all, so the
# hints are taken just before it opens. The menus that were opened by popup_at_pointer and
# popup_at_widget, as the code before the fix opened two of them, are treated the same.
asked = []

def recording(name):
    real = getattr(Gtk.Menu, name)
    def opened(menu, *arguments):
        asked.append({"menu": menu, "call": name, "hints": int(menu.get_property("anchor-hints")),
                      "dy": menu.get_property("rect-anchor-dy"),
                      "dx": menu.get_property("rect-anchor-dx")})
        if not KEEP_HINTS:
            menu.set_property("anchor-hints", 0)
        return real(menu, *arguments)
    # What a scenario that leaves the hints to its own stand-in opens a menu by.
    opened.real = real
    return opened

for call in ("popup_at_rect", "popup_at_pointer", "popup_at_widget"):
    setattr(Gtk.Menu, call, recording(call))

RESIZE_Y = int(Gdk.AnchorHints.RESIZE_Y)

def fill_screen(height=None, width=1000):
    """The main window from the top left corner, as tall as the screen unless told."""
    w.wMain.move(0, 0)
    w.wMain.resize(width, height or SCREEN_BOTTOM - SCREEN_TOP - 10)
    w.wMain.present()
    pump(0.6)

def on_screen(widget, x=0, y=0):
    """Where the point (x, y) of `widget` is on the screen."""
    inside_x, inside_y = widget.translate_coordinates(w.wMain, x, y)
    _, origin_x, origin_y = w.wMain.get_window().get_origin()
    return origin_x + inside_x, origin_y + inside_y

def landed(menu):
    """(x, y, width, height) of the open menu on the screen."""
    window = menu.get_toplevel().get_window()
    _, x, y = window.get_origin()
    return x, y, window.get_width(), window.get_height()

def open_at(menu, x, y, wait=0.3):
    """Right-click the point (x, y) of the screen, and the open menu's box."""
    del asked[:]
    click(3, x, y)
    assert until(menu.get_visible), f"the menu did not open for a click at {x}, {y}"
    pump(wait)
    assert asked, "GCM asked GTK for no menu"
    return landed(menu)

def close(menu):
    menu.popdown()
    assert until(lambda: not menu.get_visible()), "the menu stayed open"
    pump(0.15)

def check(what, top, bottom, box):
    """The menu `box` is on the screen, and beside the row top..bottom, not over it, where
    there is room for it there: hung from its bottom or standing on its top."""
    x, y, width, height = box
    assert SCREEN_TOP <= y and y + height <= SCREEN_BOTTOM, (
        f"{what}: the menu runs from {y} to {y + height} on a screen from {SCREEN_TOP} to {SCREEN_BOTTOM}"
    )
    beside = SCREEN_BOTTOM - bottom >= height or top - SCREEN_TOP >= height
    if beside:
        assert y == bottom or y + height == top, (
            f"{what}: the menu {y} to {y + height} is not against the row {top} to {bottom}"
        )

def check_across(what, x, box, width):
    """The menu `box` is inside the screen from side to side, and, as it would have run off
    the screen rightwards, opened leftwards with its right edge at the pointer `x`."""
    assert SCREEN_LEFT <= box[0] and box[0] + box[2] <= SCREEN_RIGHT, (
        f"{what}: the menu runs from {box[0]} to {box[0] + box[2]} on a screen from {SCREEN_LEFT} to {SCREEN_RIGHT}"
    )
    assert x + width > SCREEN_RIGHT, f"{what}: the menu would have fitted rightwards"
    assert abs(box[0] + box[2] - (x + 1)) <= 1, f"{what}: the menu's right edge is at {box[0] + box[2]}, not at {x}"

def pointer_row(y):
    """The row a click at y is, to the menu: one pixel."""
    return y, y + 1

def open_page(name, notebook=None):
    """A tab of a kind GCM does not have yet, which needs no terminal."""
    page = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
    page.pack_start(Gtk.Label(label=name), True, True, 0)
    w.add_page(notebook or w.nbConsole, page, name)
    return page

def first_top(menu):
    """Where the menu's first item is in the menu's window: it moves as the menu scrolls."""
    shown = menu.get_toplevel().get_window()
    _, _, shown_y = shown.get_origin()
    item = menu.get_children()[0]
    _, _, item_y = item.get_window().get_origin()
    return item_y + item.get_allocation().y - shown_y

def center_of(item):
    """Where the middle of a menu item is on the screen."""
    _, origin_x, origin_y = item.get_window().get_origin()
    box = item.get_allocation()
    return origin_x + box.x + box.width // 2, origin_y + box.y + box.height // 2

def wheel(what, menu, down=4, up=2):
    """Real wheel notches over the open `menu`: each moves it by a row, the shortest, which
    is 15 pixels without #399's hook, at whatever size the text is."""
    row = app.menu_row_height(menu)
    assert row and row > 15, (what, row)
    x, y, width, height = landed(menu)
    assert height < app.menu_height(menu), f"{what}: the menu is not cut short"
    tops = [first_top(menu)]
    for number in range(down + up):
        click(5 if number < down else 4, x + width // 2, y + height // 2)
        pump(0.3)
        tops.append(first_top(menu))
    steps = [after - before for before, after in zip(tops, tops[1:])]
    wanted = [-row] * down + [row] * up
    assert all(abs(step - want) <= 1 for step, want in zip(steps, wanted)), (
        f"{what}: the steps were {steps}, a row is {row}"
    )
    print(what, "steps", steps, "row", row)

def open_menubar_item(label):
    """The menu of the menubar's item of that label, open under it. Not by a click on the
    item: that makes GTK complain, once, that a menu's toplevel is no window."""
    item = w.find_menubar_item(label)
    assert item is not None, label
    menu = item.get_submenu()
    menu.popup_at_widget(item, Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None)
    assert until(menu.get_visible), f"{label} did not open"
    pump(0.3)
    return menu

def center_of_widget(widget):
    """Where the middle of a widget with a window of its own, or a menubar's item, is."""
    return on_screen(widget, widget.get_allocated_width() // 2, widget.get_allocated_height() // 2)

def standin(menu):
    """Weston's part, for a menu GTK places itself: a menu that is moved by no compositor
    has no hints when GTK reads them, and GTK sets a submenu's hints at each opening, so this
    runs after GCM's own handler of `show`, which runs before GTK reads them (#397)."""
    if not KEEP_HINTS:
        menu.connect_after("show", lambda opened: opened.set_property("anchor-hints", 0))

def inside_screen(what, menu):
    x, y, width, height = landed(menu)
    assert SCREEN_TOP <= y and y + height <= SCREEN_BOTTOM, (
        f"{what}: the menu runs from {y} to {y + height} on a screen from {SCREEN_TOP} to {SCREEN_BOTTOM}"
    )
    return x, y, width, height

def reach_last(what, menu):
    """Scroll the open `menu` until its last item is in sight, as the wheel does."""
    last = menu.get_children()[-1]
    shown = menu.get_toplevel().get_window()
    for _ in range(600):
        top = shown.get_origin()[2]
        _, _, item_y = last.get_window().get_origin()
        bottom = item_y + last.get_allocation().y + last.get_allocation().height - top
        if bottom <= shown.get_height():
            return
        more = Gdk.Event.new(Gdk.EventType.SCROLL)
        more.direction = Gdk.ScrollDirection.SMOOTH
        more.delta_y = 1.0
        menu.emit("scroll-event", more)
        pump(0.01)
    raise AssertionError(f"{what}: the last item cannot be scrolled into sight")

def lab_folder(count, folders_before=0):
    """A folder of `count` hosts, after `folders_before` folders of one, so low in the menu."""
    app.groups.clear()
    for number in range(folders_before):
        name = f"F{number:02d}"
        app.groups[name] = [ssh_host("x", "192.0.2.1", name)]
    app.groups["Zulu"] = [ssh_host(f"host-{i:02d}", f"192.0.2.{i + 1}", "Zulu") for i in range(count)]
    w.updateTree()
    pump(0.4)

def open_folder(hosts, which=-1):
    folders = [item for item in hosts.get_children() if item.get_submenu() is not None]
    folder = folders[which]
    sub = folder.get_submenu()
    standin(sub)
    click(1, *center_of(folder))
    assert until(sub.get_visible), "the folder did not open"
    pump(0.5)
    return folder, sub

def long_list(count):
    app.snippets[:] = [app.snippetlib.Snippet(f"{n:08x}", f"snippet {n:02d}", "x") for n in range(count)]

if scenario == "the-tree-menu":
    menu = w.popupMenuFolder
    column = w.treeServers.get_column(0)

    def rows_in_sight():
        """Each row of the tree showing: its path, whether it is a folder's, its area."""
        view = w.treeServers.get_visible_rect()
        found = []
        w.treeModel.foreach(lambda model, path, it: found.append((path.copy(), w.is_folder_row(it))) or False)
        sights = []
        for path, folder in found:
            area = w.treeServers.get_cell_area(path, column)
            if area.height and view.y <= area.y and area.y + area.height <= view.y + view.height:
                sights.append((path, folder, area))
        return sights

    def click_each(rows, kinds):
        _, bin_x, bin_y = w.treeServers.get_bin_window().get_origin()
        for number, (path, folder, area) in enumerate(rows):
            row_top, row_bottom = bin_y + area.y, bin_y + area.y + area.height
            x = bin_x + area.x + min(area.width // 2, 40)
            what = f"row {number}, a {'folder' if folder else 'host'}'s"
            box = open_at(menu, x, bin_y + area.y + area.height // 2)
            check(what, row_top, row_bottom, box)
            assert box[0] == bin_x + area.x, f"{what}: the menu is at {box[0]}, not at its cell"
            kinds.add((folder, box[1] >= row_bottom, box[1] + box[3] <= row_top))
            close(menu)

    def fill_tree(hosts):
        """Lab with `hosts` hosts, and Zulu, a folder with one, last: hosts + 3 rows."""
        app.groups.clear()
        app.groups["Lab"] = [ssh_host(f"host-{i:02d}", f"192.0.2.{i + 1}", "Lab") for i in range(hosts)]
        app.groups["Zulu"] = [ssh_host("zulu-host", "192.0.2.99", "Zulu")]
        w.updateTree()
        w.treeServers.expand_all()
        pump(0.5)

    # Rows to fill the pane but for two, whatever a row's height, and so the space below
    # them: a folder's row among the last.
    fill_screen()
    fill_tree(1)
    assert until(lambda: w.treeServers.get_allocated_height() > 600), w.treeServers.get_allocated_height()
    # A row's pitch, which is more than its cell's height: the tree puts space between.
    first, second = (area for _path, _folder, area in rows_in_sight()[:2])
    count = w.treeServers.get_allocated_height() // (second.y - first.y) - 5
    assert count > 8, (count, first.y, second.y)
    fill_tree(count)
    rows = rows_in_sight()
    assert len(rows) == count + 3 and rows[-2][1] and not rows[-1][1], (len(rows), count)
    kinds = set()
    click_each(rows, kinds)
    # Both a host's row and a folder's were clicked, and the menu was below some rows and
    # above others.
    assert {folder for folder, _below, _above in kinds} == {True, False}, kinds
    assert any(below for _folder, below, _above in kinds), kinds
    assert any(above for _folder, _below, above in kinds), kinds
    # The space below the rows: there is no cell, so the click is the rectangle.
    _, tree_x, tree_y = w.treeServers.get_window().get_origin()
    y = tree_y + w.treeServers.get_allocated_height() - 12
    box = open_at(menu, tree_x + 30, y)
    check("the space below the rows", *pointer_row(y), box)
    assert box[0] == tree_x + 30, box
    close(menu)

    # A tree longer than the pane, scrolled to its end: the rows at the pane's foot are far
    # down the tree, and a cell area counts the scroll, so the menu must be against the row
    # that is on the screen, not where it is in the tree.
    app.groups["Lab"] = [ssh_host(f"host-{i:02d}", f"192.0.2.{i + 1}", "Lab") for i in range(45)]
    w.updateTree()
    w.treeServers.expand_all()
    pump(0.5)
    adjustment = w.treeServers.get_vadjustment()
    adjustment.set_value(adjustment.get_upper() - adjustment.get_page_size())
    pump(0.5)
    assert w.treeServers.get_visible_rect().y > 0, "the tree did not scroll"
    click_each(rows_in_sight()[-9:], set())

elif scenario == "the-terminal-menu-at-the-right-edge":
    menu = w.popupMenu
    w.addTab(w.nbConsole, app.Host("", "shell"))
    fill_screen(width=SCREEN_RIGHT - SCREEN_LEFT)
    terminal = app.page_terminal(w.nbConsole.get_nth_page(0))
    terminal_x, terminal_top = on_screen(terminal)
    x = terminal_x + terminal.get_allocated_width() - 20
    assert terminal_top < 300 and 900 < terminal_top + terminal.get_allocated_height(), terminal_top
    for y in (300, 600, 900):
        box = open_at(menu, x, y)
        check_across(f"a click at {y}", x, box, app.menu_width(menu))
        check(f"a click at {y}", *pointer_row(y), box)
        assert asked[-1]["dx"] == 0, asked[-1]
        close(menu)

elif scenario == "the-tab-menu-at-the-right-edge":
    w.addTab(w.nbConsole, app.Host("", "shell"))
    # The tabs down the right side, so that the label is at the screen's right edge.
    w.nbConsole.set_tab_pos(Gtk.PositionType.RIGHT)
    label = w.nbConsole.get_tab_label(w.nbConsole.get_nth_page(0))
    menu = label.popup
    for height in (500, 800, 1070):
        fill_screen(height, width=SCREEN_RIGHT - SCREEN_LEFT)
        assert until(lambda: label.eb.get_allocated_height() > 10)
        x, y = on_screen(label.eb, label.eb.get_allocated_width() // 2, label.eb.get_allocated_height() // 2)
        box = open_at(menu, x, y)
        check_across(f"a tab in a window {height} tall", x, box, app.menu_width(menu))
        check(f"a tab in a window {height} tall", *pointer_row(y), box)
        close(menu)

elif scenario == "the-terminal-menu":
    menu = w.popupMenu
    w.addTab(w.nbConsole, app.Host("", "shell"))
    fill_screen()
    terminal = app.page_terminal(w.nbConsole.get_nth_page(0))
    terminal_x, terminal_top = on_screen(terminal)
    # The clicks are in the terminal, and its menu fits on neither side of the first two.
    assert terminal_top < 300 and 900 < terminal_top + terminal.get_allocated_height(), terminal_top
    for y in (300, 600, 900):
        x = terminal_x + terminal.get_allocated_width() // 2
        box = open_at(menu, x, y)
        check(f"a click at {y}", *pointer_row(y), box)
        assert box[0] == x, f"a click at {y}: the menu is at {box[0]}, not at the pointer, {x}"
        close(menu)

elif scenario == "a-menu-stays-inside-a-short-window":
    # Under Wayland the room is the window's content, as `window_content` reads it, and this
    # stands in for that on X11: a window 400 tall with its menus taller than it (#402).
    app.menu_room = lambda window: app.window_content(window.get_toplevel())
    w.addTab(w.nbConsole, app.Host("", "shell"))
    app.groups.clear()
    app.groups["Lab"] = [ssh_host(f"host-{i:02d}", f"192.0.2.{i + 1}", "Lab") for i in range(6)]
    w.updateTree()
    w.treeServers.expand_all()
    fill_screen(400)
    assert until(lambda: w.wMain.get_window().get_height() <= 410), w.wMain.get_window().get_height()
    win_top = w.wMain.get_window().get_origin()[2]
    win_bottom = win_top + w.wMain.get_window().get_height()

    def last_bottom(menu):
        shown = menu.get_toplevel().get_window()
        _, _, shown_y = shown.get_origin()
        item = [i for i in menu.get_children() if i.get_visible()][-1]
        _, _, item_y = item.get_window().get_origin()
        return item_y + item.get_allocation().y + item.get_allocation().height - shown_y

    def inside_window(what, menu, row_top, row_bottom, box):
        _x, y, _width, height = box
        assert app.menu_height(menu) > win_bottom - win_top, (what, app.menu_height(menu))
        assert win_top <= y and y + height <= win_bottom, (what, box, win_top, win_bottom)
        assert y == row_bottom or y + height == row_top, (what, box, row_top, row_bottom)
        shown_x, shown_y, shown_width, shown_height = box
        for _ in range(200):
            if last_bottom(menu) <= shown_height:
                break
            click(5, shown_x + shown_width // 2, shown_y + shown_height // 2)
            pump(0.05)
        assert last_bottom(menu) <= shown_height, (what, last_bottom(menu), shown_height)

    menu = w.popupMenu
    terminal = app.page_terminal(w.nbConsole.get_nth_page(0))
    terminal_x, terminal_top = on_screen(terminal)
    terminal_height = terminal.get_allocated_height()
    for offset in (20, terminal_height - 20):
        y = terminal_top + offset
        box = open_at(menu, terminal_x + 100, y)
        inside_window(f"the terminal's menu at {y}", menu, *pointer_row(y), box)
        close(menu)

    column = w.treeServers.get_column(0)
    rows = []
    w.treeModel.foreach(lambda model, path, it: rows.append(path.copy()) or False)
    # The seven rows end above the window's foot only in a font whose rows are as short as
    # DejaVu Sans's: Noto Sans's are taller, and the last was below the window, so the click on
    # it missed (#500). So the row is scrolled into sight, as a person would, whatever the font.
    w.treeServers.scroll_to_cell(rows[-1], None, False, 0, 0)

    def last_row_span():
        """The last row's background area from top to foot, and the height the tree shows, in the
        bin window's coordinates. The area, not the cell inside it: that is in sight one pixel
        before the scroll ends."""
        row = w.treeServers.get_background_area(rows[-1], column)
        return row.y, row.y + row.height, w.treeServers.get_visible_rect().height

    def last_row_in_sight():
        top, bottom, shown = last_row_span()
        return 0 <= top and bottom <= shown

    assert until(last_row_in_sight), ("the tree's last row did not scroll into sight", last_row_span())
    pump(0.3)
    area = w.treeServers.get_cell_area(rows[-1], column)
    _, bin_x, bin_y = w.treeServers.get_bin_window().get_origin()
    row_top, row_bottom = bin_y + area.y, bin_y + area.y + area.height
    assert win_top <= row_top and row_bottom <= win_bottom, (
        "the tree's last row is not in the window", row_top, row_bottom, win_top, win_bottom
    )
    menu = w.popupMenuFolder
    box = open_at(menu, bin_x + area.x + 20, bin_y + area.y + area.height // 2)
    inside_window("the tree's menu on its last row", menu, row_top, row_bottom, box)
    close(menu)

elif scenario == "the-tab-menu":
    w.addTab(w.nbConsole, app.Host("", "shell"))
    # The tabs along the bottom, so that the window's height moves them down the screen.
    w.nbConsole.set_tab_pos(Gtk.PositionType.BOTTOM)
    label = w.nbConsole.get_tab_label(w.nbConsole.get_nth_page(0))
    menu = label.popup
    for height in (500, 650, 800, 950, 1070):
        fill_screen(height)
        assert until(lambda: label.eb.get_allocated_height() > 10)
        x, y = on_screen(label.eb, label.eb.get_allocated_width() // 2, label.eb.get_allocated_height() // 2)
        box = open_at(menu, x, y)
        check(f"a tab in a window {height} tall", *pointer_row(y), box)
        assert box[0] == x, f"a tab in a window {height} tall: the menu is at {box[0]}, not at {x}"
        close(menu)

elif scenario == "the-console-list":
    fill_screen()
    button = w.nbConsole.get_action_widget(Gtk.PackType.END)
    pages = []

    def have(count):
        while len(pages) < count:
            pages.append(open_page(f"console-{len(pages):02d}"))
        while len(pages) > count:
            w.nbConsole.remove_page(w.nbConsole.page_num(pages.pop()))
        pump(0.4)

    def press_button(what):
        """Press the button; the box of the menu it opens, and the button's, as on the screen."""
        x, y = on_screen(button, button.get_allocated_width() // 2, button.get_allocated_height() // 2)
        del asked[:]
        click(1, x, y)
        assert until(lambda: asked), f"{what}: the button opened nothing"
        menu = asked[-1]["menu"]
        assert until(menu.get_visible)
        pump(0.3)
        left, top = on_screen(button)
        return menu, landed(menu), (left, top, left + button.get_allocated_width(), top + button.get_allocated_height())

    # Three consoles under a tab strip along the top: below the button, its right edge on the
    # button's, so that it opens leftwards.
    have(3)
    menu, box, (left, top, right, bottom) = press_button("three consoles")
    check("three consoles, strip along the top", top, bottom, box)
    assert box[1] == bottom and box[0] + box[2] == right, (box, left, top, right, bottom)
    assert asked[-1]["hints"] & RESIZE_Y, asked
    close(menu)

    # The strip along the bottom, and fifteen consoles: no room below, so above the button.
    w.nbConsole.set_tab_pos(Gtk.PositionType.BOTTOM)
    have(15)
    menu, box, (left, top, right, bottom) = press_button("fifteen consoles")
    check("fifteen consoles, strip along the bottom", top, bottom, box)
    assert box[1] + box[3] == top and box[0] + box[2] == right, (box, left, top, right, bottom)
    assert asked[-1]["hints"] & RESIZE_Y, asked
    close(menu)

    # Forty: taller than the screen. It is cut to the room beside the button, here above it
    # with the strip along the bottom, and told it may not be resized in height, so that GTK
    # scrolls it (#402); and a short list is told it may again.
    def last_bottom(menu):
        """Where the last console's row ends in the menu's window: it moves as the menu scrolls."""
        shown = menu.get_toplevel().get_window()
        _, _, shown_y = shown.get_origin()
        item = menu.get_children()[-1]
        _, _, item_y = item.get_window().get_origin()
        return item_y + item.get_allocation().y + item.get_allocation().height - shown_y

    def scroll_to_last(menu):
        x, y, width, height = landed(menu)
        assert last_bottom(menu) > height, "the last console is in view before any scrolling"
        for _ in range(200):
            if last_bottom(menu) <= height:
                break
            click(5, x + width // 2, y + height // 2)
            pump(0.05)
        assert last_bottom(menu) <= height, (last_bottom(menu), height)

    have(40)
    menu, box, (left, top, right, bottom) = press_button("forty consoles, strip at the bottom")
    assert len([item for item in menu.get_children() if item.get_visible()]) == 40
    assert app.menu_height(menu) > SCREEN_BOTTOM - SCREEN_TOP, app.menu_height(menu)
    assert box[1] + box[3] == top and box[1] >= SCREEN_TOP, (box, top)
    assert box[3] == top - SCREEN_TOP and box[3] < app.menu_height(menu), (box, top)
    assert box[0] + box[2] == right, (box, right)
    assert asked[-1]["hints"] & RESIZE_Y == 0 and asked[-1]["hints"] & int(Gdk.AnchorHints.RESIZE_X), asked
    scroll_to_last(menu)
    close(menu)

    # The strip along the top: the menu hangs from the button's bottom and ends at the foot
    # of the screen.
    w.nbConsole.set_tab_pos(Gtk.PositionType.TOP)
    pump(0.4)
    menu, box, (left, top, right, bottom) = press_button("forty consoles, strip at the top")
    assert box[1] == bottom and box[1] + box[3] == SCREEN_BOTTOM, (box, bottom)
    assert box[0] + box[2] == right, (box, right)
    scroll_to_last(menu)
    close(menu)
    w.nbConsole.set_tab_pos(Gtk.PositionType.BOTTOM)
    have(40)
    pump(0.4)
    have(3)
    menu, box, (left, top, right, bottom) = press_button("three consoles again")
    check("three consoles again, strip along the bottom", top, bottom, box)
    assert asked[-1]["hints"] & RESIZE_Y, "the hints stayed off for a short list"
    assert asked[-1]["dy"] == 0, asked
    # It is not resizable any more, and as tall as it is: the cut is not kept (#402).
    assert not menu.get_toplevel().get_resizable(), "the menu stayed resizable"
    assert box[3] == app.menu_height(menu), (box, app.menu_height(menu))
    close(menu)

    # From the keyboard there is no event to give GTK, and the menu is placed all the same.
    del asked[:]
    button.clicked()
    assert until(lambda: asked), "activating the button opened nothing"
    assert until(menu.get_visible)
    pump(0.3)
    assert asked[-1]["menu"] is menu
    box = landed(menu)
    check("three consoles, from the keyboard", top, bottom, box)
    assert box[1] + box[3] == top and box[0] + box[2] == right, (box, top, right)
    close(menu)

elif scenario == "the-mounted-tab-menu":
    menu = w.popupMenuMounts
    fill_screen()
    store = w.treeMounts.get_model()
    for name in ("alpha", "beta", "gamma"):
        store.append([name, os.path.join(os.environ["HOME"], "mnt", name), name])
    w.nbServers.get_nth_page(1).show()
    w.nbServers.set_current_page(1)
    assert until(lambda: w.treeMounts.get_allocated_height() > 600)
    pump(0.3)
    # On the space below the rows, at the foot of the screen: above the pointer.
    _, tree_x, tree_y = w.treeMounts.get_window().get_origin()
    tree_bottom = tree_y + w.treeMounts.get_allocated_height()
    assert tree_bottom > SCREEN_BOTTOM - 200, (tree_bottom, SCREEN_BOTTOM)
    for y in (tree_bottom - 80, tree_bottom - 12):
        box = open_at(menu, tree_x + 30, y)
        check(f"the space below the rows, at {y}", *pointer_row(y), box)
        assert box[0] == tree_x + 30 and box[1] + box[3] == y, (box, y)
        close(menu)
    # On the first row, high up: below the pointer.
    column = w.treeMounts.get_column(0)
    area = w.treeMounts.get_cell_area(Gtk.TreePath.new_first(), column)
    _, bin_x, bin_y = w.treeMounts.get_bin_window().get_origin()
    x, y = bin_x + 30, bin_y + area.y + area.height // 2
    box = open_at(menu, x, y)
    check("a mount's row", *pointer_row(y), box)
    assert box[0] == x and box[1] == y + 1, (box, x, y)
    close(menu)

elif scenario == "a-menu-is-as-tall-as-the-items-it-shows":
    # The height asked of the items is the height GTK gives the menu, to the pixel, for
    # each menu GCM opens and in each state of the one menu the tree has three of.
    # The theme's padding, asymmetric and unlike any theme's, in place before the first menu
    # is shown: a menu already shown keeps the size it had until it is restyled.
    css = Gtk.CssProvider()
    css.load_from_data(b"menu { padding: 9px 0 2px 0; }")
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_USER
    )
    fill_screen()
    heights = {}

    def compare(what, menu, x, y):
        box = open_at(menu, x, y)
        # GTK makes a menu no taller than the screen, as it scrolls one that is.
        asked_for = min(app.menu_height(menu), SCREEN_BOTTOM - SCREEN_TOP)
        assert app.menu_width(menu) == box[2], f"{what}: asked {app.menu_width(menu)} wide, GTK gave {box[2]}"
        assert asked_for == box[3], f"{what}: asked {app.menu_height(menu)}, GTK gave {box[3]}"
        heights[what] = box[3]
        close(menu)

    app.groups.clear()
    app.groups["Lab"] = [ssh_host(f"host-{i}", f"192.0.2.{i + 1}", "Lab") for i in range(3)]
    w.updateTree()
    w.treeServers.expand_all()
    pump(0.5)
    column = w.treeServers.get_column(0)
    _, bin_x, bin_y = w.treeServers.get_bin_window().get_origin()
    rows = []
    w.treeModel.foreach(lambda model, path, it: rows.append(path.copy()) or False)
    for what, path in (("a folder", rows[0]), ("a host", rows[1])):
        area = w.treeServers.get_cell_area(path, column)
        compare(what, w.popupMenuFolder, bin_x + area.x + 20, bin_y + area.y + area.height // 2)
    _, tree_x, tree_y = w.treeServers.get_window().get_origin()
    compare("the blank space", w.popupMenuFolder, tree_x + 30, tree_y + 600)
    assert len(set(heights.values())) == 3, heights

    w.addTab(w.nbConsole, app.Host("", "shell"))
    pump(0.5)
    terminal = app.page_terminal(w.nbConsole.get_nth_page(0))
    terminal_x, terminal_top = on_screen(terminal)
    compare("the terminal", w.popupMenu, terminal_x + 100, terminal_top + 60)
    label = w.nbConsole.get_tab_label(w.nbConsole.get_nth_page(0))
    x, y = on_screen(label.eb, 10, 5)
    compare("a tab", label.popup, x, y)

    store = w.treeMounts.get_model()
    store.append(["alpha", os.path.join(os.environ["HOME"], "mnt", "alpha"), "alpha"])
    w.nbServers.get_nth_page(1).show()
    w.nbServers.set_current_page(1)
    assert until(lambda: w.treeMounts.get_allocated_height() > 400)
    _, mounts_x, mounts_y = w.treeMounts.get_window().get_origin()
    mounts = w.popupMenuMounts
    compare("the mounted tab", mounts, mounts_x + 30, mounts_y + 30)
    # The menu's own border adds to both edges.
    mounts.set_border_width(3)
    compare("the mounted tab with a border", mounts, mounts_x + 30, mounts_y + 30)
    assert heights["the mounted tab with a border"] == heights["the mounted tab"] + 6, heights

    # And the console list, whose items GCM makes afresh each time it opens.
    for number in range(3):
        open_page(f"console-{number}")
    pump(0.4)
    button = w.nbConsole.get_action_widget(Gtk.PackType.END)
    x, y = on_screen(button, 5, 5)
    del asked[:]
    click(1, x, y)
    assert until(lambda: asked)
    listed = asked[-1]["menu"]
    assert until(listed.get_visible)
    pump(0.3)
    assert app.menu_height(listed) == landed(listed)[3], (app.menu_height(listed), landed(listed))
    assert app.menu_width(listed) == landed(listed)[2], (app.menu_width(listed), landed(listed))
    close(listed)

elif scenario in ("a-menu-opens-at-its-top-once-it-is-shorter", "a-long-menu-opened-again-starts-at-its-top"):
    # GTK keeps a menu's scroll position from one opening to the next, and does not bring it
    # back within a menu that has become shorter (#408). Real wheel notches, as measured.
    # A window of its own with a right-click handler, so that the menu has the real trigger
    # event GTK asks for.
    pad = Gtk.Window()
    pad.set_default_size(400, 400)
    pad_box = Gtk.EventBox()
    pad.add(pad_box)
    pad.move(0, 0)
    pad.show_all()
    pump(0.5)
    menu = Gtk.Menu()
    pad_box.connect("button-press-event", lambda box, event: app.popup_menu_at(menu, event) or True)

    def fill(count):
        menu.foreach(menu.remove)
        for number in range(count):
            item = Gtk.MenuItem(label=f"entry {number}")
            if number == 0:
                item.set_sensitive(False)
            menu.append(item)
        menu.show_all()

    def open_menu():
        click(3, 300, 40)
        assert until(menu.get_visible), "the menu did not open"
        pump(0.4)

    def first_item_top():
        """(the first item's top in the menu window, the items in view, the items)."""
        shown = menu.get_toplevel().get_window()
        _, shown_x, shown_y = shown.get_origin()
        items = menu.get_children()
        tops = []
        for item in items:
            _, _, item_y = item.get_window().get_origin()
            tops.append((item_y + item.get_allocation().y - shown_y, item.get_allocation().height))
        inside = [t for t in tops if t[0] >= 0 and t[0] + t[1] <= shown.get_height()]
        return tops[0][0], len(inside), len(items)

    fill(60)
    open_menu()
    top, inside, count = first_item_top()
    assert top >= 0 and 1 < inside < count, (top, inside, count)
    opened_at = top
    x, y, width, height = landed(menu)
    for _ in range(130):
        click(5, x + width // 2, y + height // 2)
        pump(0.01)
    pump(0.3)
    scrolled = first_item_top()
    assert scrolled[0] < -100, scrolled
    close(menu)
    if scenario == "a-long-menu-opened-again-starts-at-its-top":
        open_menu()
    else:
        fill(8)
        open_menu()
    top, inside, count = first_item_top()
    assert top >= 0, (top, inside, count)
    if scenario.startswith("a-menu-opens"):
        assert inside == count == 8, (top, inside, count)
    else:
        assert 1 < inside < count, (top, inside, count)
    close(menu)

elif scenario.startswith("wheel-"):
    fill_screen()
    if scenario == "wheel-the-console-list":
        button = w.nbConsole.get_action_widget(Gtk.PackType.END)
        for number in range(60):
            open_page(f"Lab/web-{number:02d} console" if number % 3 == 0 else f"console-{number:02d}")
        pump(0.4)
        del asked[:]
        click(1, *center_of_widget(button))
        assert until(lambda: asked), "the button opened nothing"
        menu = asked[-1]["menu"]
        assert until(menu.get_visible)
        pump(0.3)
        wheel("the console list", menu)
    elif scenario == "wheel-open-consoles-menu":
        for number in range(60):
            open_page(f"console-{number:02d}")
        pump(0.4)
        terminal_menu = open_menubar_item("_Terminal")
        item = terminal_menu.get_children()[-1]
        terminal_menu.select_item(item)
        assert until(w.menuConsoles.get_visible), "Open Consoles did not open"
        pump(0.4)
        wheel("Open Consoles", w.menuConsoles)
    elif scenario == "wheel-a-hosts-folder-submenu":
        app.groups.clear()
        app.groups["Lab"] = [ssh_host(f"host-{i:02d}", f"192.0.2.{i + 1}", "Lab") for i in range(60)]
        w.updateTree()
        pump(0.4)
        hosts = open_menubar_item("H_osts")
        folder = [item for item in hosts.get_children() if item.get_submenu() is not None][0]
        click(1, *center_of(folder))
        sub = folder.get_submenu()
        assert until(sub.get_visible), "the folder did not open"
        pump(0.4)
        wheel("a Hosts folder", sub)
    elif scenario == "wheel-the-snippets-submenu":
        long_list(60)
        w.populateCommandsMenu()
        pump(0.3)
        edit = open_menubar_item("_Edit")
        item = [i for i in edit.get_children() if i.get_submenu() is not None and i.get_label() == "Snippets"][0]
        click(1, *center_of(item))
        sub = item.get_submenu()
        assert until(sub.get_visible), "Snippets did not open"
        pump(0.4)
        wheel("the Snippets submenu", sub)
    elif scenario == "wheel-the-cluster-snippets-button":
        long_list(60)
        w.addTab(w.nbConsole, app.Host("", "shell"))
        pump(0.5)
        w.on_btnCluster_clicked(None)
        window = w.wCluster
        window.move(0, 0)
        window.present()
        pump(0.6)
        found = []
        def walk(widget):
            if isinstance(widget, Gtk.MenuButton):
                found.append(widget)
            if hasattr(widget, "get_children"):
                for child in widget.get_children():
                    walk(child)
        walk(window)
        button = [b for b in found if b.get_label() == "Snippets"][0]
        _, window_x, window_y = window.get_window().get_origin()
        inside_x, inside_y = button.translate_coordinates(window, button.get_allocated_width() // 2, button.get_allocated_height() // 2)
        click(1, window_x + inside_x, window_y + inside_y)
        menu = button.get_popup()
        assert until(menu.get_visible), "the button opened nothing"
        pump(0.4)
        wheel("the cluster's Snippets button", menu)
    elif scenario == "wheel-the-terminal-menu-on-a-short-screen":
        w.addTab(w.nbConsole, app.Host("", "shell"))
        fill_screen()
        terminal = app.page_terminal(w.nbConsole.get_nth_page(0))
        terminal_x, terminal_top = on_screen(terminal)
        menu = w.popupMenu
        assert SCREEN_BOTTOM - SCREEN_TOP <= 600
        box = open_at(menu, terminal_x + 200, terminal_top + 60)
        assert app.menu_height(menu) > SCREEN_BOTTOM - SCREEN_TOP, app.menu_height(menu)
        # Beside the click, hung from it, and cut at the foot of the screen (#402).
        assert box[1] == terminal_top + 61 and box[1] + box[3] == SCREEN_BOTTOM, box
        wheel("the terminal's menu", menu)
    elif scenario == "wheel-a-menu-that-fits":
        w.addTab(w.nbConsole, app.Host("", "shell"))
        fill_screen()
        terminal = app.page_terminal(w.nbConsole.get_nth_page(0))
        terminal_x, terminal_top = on_screen(terminal)
        menu = w.popupMenu
        x, y, width, height = open_at(menu, terminal_x + 200, terminal_top + 60)
        assert app.menu_height(menu) <= height, (app.menu_height(menu), height)
        before = first_top(menu)
        for _ in range(6):
            click(5, x + width // 2, y + height // 2)
            pump(0.3)
        assert first_top(menu) == before, (first_top(menu), before)
        close(menu)
        print("fits ok")

elif scenario == "a-tall-folder-submenu-stays-on-the-screen":
    lab_folder(60)
    hosts = open_menubar_item("H_osts")
    folder, sub = open_folder(hosts)
    x, y, width, height = inside_screen("a folder of 60 hosts", sub)
    assert height < app.menu_height(sub), (height, app.menu_height(sub))
    reach_last("a folder of 60 hosts", sub)
elif scenario == "a-low-folder-submenu-slides-onto-the-screen":
    # The Hosts menu has as many folders before Zulu as fit above the screen's foot with a row
    # to spare, so that it is not cut and Zulu is low in it: 24 with DejaVu Sans's rows, 21 with
    # Noto Sans's, which are taller. With 24 of those the menu was cut to the screen and Zulu
    # was off it (#500). Its top and its row are read from the menu with Zulu alone.
    lab_folder(15)
    hosts = open_menubar_item("H_osts")
    top = landed(hosts)[1]
    row = app.menu_row_height(hosts)
    assert row and row > 15, row
    close(hosts)
    lab_folder(15, folders_before=(SCREEN_BOTTOM - top) // row - 2)
    hosts = open_menubar_item("H_osts")
    folder, sub = open_folder(hosts)
    x, y, width, height = inside_screen("a low folder of 15 hosts", sub)
    assert height >= app.menu_height(sub) - 10, (height, app.menu_height(sub))
    assert center_of(folder)[1] > SCREEN_BOTTOM - height, "the folder is not low enough to test"
elif scenario == "a-hosts-menu-of-top-level-hosts-stays-on-the-screen":
    app.groups.clear()
    app.groups[""] = [ssh_host(f"host-{i:02d}", f"192.0.2.{i + 1}") for i in range(60)]
    w.updateTree()
    pump(0.4)
    item = w.find_menubar_item("H_osts")
    hosts = item.get_submenu()
    standin(hosts)
    # Not the recording call, which takes the hints before GCM's handler runs.
    Gtk.Menu.popup_at_widget.real(hosts, item, Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None)
    assert until(hosts.get_visible), "the Hosts menu did not open"
    pump(0.5)
    x, y, width, height = inside_screen("60 hosts in the Hosts menu", hosts)
    assert height < app.menu_height(hosts), (height, app.menu_height(hosts))
    reach_last("60 hosts in the Hosts menu", hosts)
elif scenario == "the-cluster-snippets-button-stays-on-the-screen":
    long_list(60)
    w.addTab(w.nbConsole, app.Host("", "shell"))
    pump(0.5)
    w.on_btnCluster_clicked(None)
    window = w.wCluster
    window.move(0, 0)
    window.present()
    pump(0.6)
    found = []
    def walk(widget):
        if isinstance(widget, Gtk.MenuButton):
            found.append(widget)
        if hasattr(widget, "get_children"):
            for child in widget.get_children():
                walk(child)
    walk(window)
    button = [b for b in found if b.get_label() == "Snippets"][0]
    menu = button.get_popup()
    standin(menu)
    _, window_x, window_y = window.get_window().get_origin()
    inside_x, inside_y = button.translate_coordinates(window, button.get_allocated_width() // 2, button.get_allocated_height() // 2)
    click(1, window_x + inside_x, window_y + inside_y)
    assert until(menu.get_visible), "the button opened nothing"
    pump(0.5)
    x, y, width, height = inside_screen("the cluster's Snippets button", menu)
    assert height < app.menu_height(menu), (height, app.menu_height(menu))
    reach_last("the cluster's Snippets button", menu)

else:
    raise SystemExit("no scenario " + scenario)
w.wMain.destroy()
print("OK")
'''


def run_scenario(scenario, tmp_path, display, dpi="2"):
    """Run a scenario at twice the usual text size unless told, as GCM runs, and fail on what it raised or
    GLib complained of."""
    environment = dict(os.environ, DISPLAY=display, GDK_BACKEND="x11", GDK_DPI_SCALE=dpi)
    for name in ("WAYLAND_DISPLAY", "GDK_SCALE", "XDG_CONFIG_HOME"):
        environment.pop(name, None)
    # A GCM started from another's tab inherits where that one found its files, and a
    # worktree's would then run the main checkout's.
    for name in ("GCM_DATA_DIR", "GCM_GLADE_DIR", "GCM_SCRIPTS_DIR"):
        environment.pop(name, None)
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT, scenario, str(tmp_path)],
        capture_output=True,
        text=True,
        cwd=REPO,
        env=environment,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-3000:]
    assert "OK" in result.stdout
    # PyGObject prints what a signal handler raises, and carries on.
    assert "Traceback" not in result.stderr, result.stderr[-3000:]
    assert glib_complaints(result.stderr) == []


@pytest.mark.skipif(shutil.which("Xvfb") is None, reason="needs Xvfb for a display of its own")
@pytest.mark.parametrize(
    "scenario",
    [
        "the-tree-menu",
        "the-terminal-menu",
        "the-tab-menu",
        "the-console-list",
        "the-mounted-tab-menu",
        "a-menu-is-as-tall-as-the-items-it-shows",
        "the-terminal-menu-at-the-right-edge",
        "the-tab-menu-at-the-right-edge",
        "the-tab-menu-at-the-right-edge-with-its-hints",
        "the-terminal-menu-with-its-hints",
        "the-console-list-with-its-hints",
        "a-menu-stays-inside-a-short-window",
        "a-menu-opens-at-its-top-once-it-is-shorter",
        "a-long-menu-opened-again-starts-at-its-top",
        "a-tall-folder-submenu-stays-on-the-screen",
        "a-tall-folder-submenu-stays-on-the-screen-with-its-hints",
        "a-low-folder-submenu-slides-onto-the-screen",
        "a-low-folder-submenu-slides-onto-the-screen-with-its-hints",
        "a-hosts-menu-of-top-level-hosts-stays-on-the-screen",
        "the-cluster-snippets-button-stays-on-the-screen",
    ],
)
def test_menus_stay_on_the_screen_against_real_gtk(scenario, tmp_path):
    """Real clicks, so on a display of its own: on the one the other tests share, another
    test's window can be where the click lands."""
    pytest.importorskip("gi", reason="PyGObject not available")
    process, display = _private_display()
    try:
        run_scenario(scenario, tmp_path, display)
    finally:
        process.terminate()
        process.wait()


@pytest.mark.skipif(shutil.which("Xvfb") is None, reason="needs Xvfb for a display of its own")
@pytest.mark.parametrize("dpi", ["1", "2"])
@pytest.mark.parametrize(
    "scenario",
    [
        "wheel-the-console-list",
        "wheel-open-consoles-menu",
        "wheel-a-hosts-folder-submenu",
        "wheel-the-snippets-submenu",
        "wheel-the-cluster-snippets-button",
        "wheel-a-menu-that-fits",
    ],
)
def test_a_notch_of_the_wheel_scrolls_a_row_against_real_gtk(scenario, dpi, tmp_path):
    """Real wheel notches through XTest: each moves a long menu by its row, not by GTK's
    15 pixels (#399)."""
    pytest.importorskip("gi", reason="PyGObject not available")
    process, display = _private_display()
    try:
        run_scenario(scenario, tmp_path, display, dpi)
    finally:
        process.terminate()
        process.wait()


@pytest.mark.skipif(shutil.which("Xvfb") is None, reason="needs Xvfb for a display of its own")
def test_a_menu_cut_short_by_a_short_screen_scrolls_a_row_against_real_gtk(tmp_path):
    """The terminal's menu, 821 pixels tall at twice the usual text size, on a screen of 600."""
    pytest.importorskip("gi", reason="PyGObject not available")
    process, display = _private_display("1920x600x24")
    try:
        run_scenario("wheel-the-terminal-menu-on-a-short-screen", tmp_path, display)
    finally:
        process.terminate()
        process.wait()
