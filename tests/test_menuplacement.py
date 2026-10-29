"""Where a pop-up menu goes so that it stays on the screen (#392).

A menu in GCM is placed by GCM: below the row or the click, else above it, else slid until it
fits. The decision is `menuplacement.place_menu`, which takes numbers and is tested here
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

from gnome_connection_manager.utils.menuplacement import Placement, place_menu
from tests.test_connections import glib_complaints
from tests.test_console_window import _private_display

REPO = Path(__file__).resolve().parents[1]


# -- the decision, with no display -------------------------------------------------------------


def landing(placement: Placement, top: int, bottom: int, height: int, low: int, high: int):
    """The span a menu `height` tall covers when GTK puts it where `placement` says, as
    (start, end): hung from the row's bottom or stood on its top, then moved by the shift.
    A menu taller than the room is shown no taller than the room."""
    shown = min(height, high - low)
    start = bottom + placement.shift if placement.below else top + placement.shift - shown
    return start, start + shown


def test_a_menu_that_fits_below_the_row_hangs_from_it():
    assert place_menu(100, 140, 300, 0, 1000) == Placement(True, 0, False)


def test_a_menu_that_does_not_fit_below_stands_on_the_row():
    assert place_menu(700, 740, 300, 0, 1000) == Placement(False, 0, False)


def test_below_is_chosen_where_it_fits_on_both_sides():
    assert place_menu(400, 440, 300, 0, 1000) == Placement(True, 0, False)


@pytest.mark.parametrize(
    ("top", "bottom", "expected"),
    [
        # A menu of 300 and a room to 1000: a row ending at 700 leaves exactly 300 below it,
        # and one ending at 701 leaves 299, so the menu stands on the row.
        (660, 700, Placement(True, 0, False)),
        (661, 701, Placement(False, 0, False)),
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
        (300, 701, Placement(False, 0, False)),
        (299, 701, Placement(True, -1, False)),
    ],
)
def test_a_menu_fits_above_with_exactly_the_room_that_is_left(top, bottom, expected):
    assert place_menu(top, bottom, 300, 0, 1000) == expected


def test_a_menu_that_fits_neither_side_slides_up_from_below_the_row():
    """More room below than above: it still hangs from the row, and is lifted until its
    bottom edge is the room's."""
    placement = place_menu(300, 340, 800, 0, 1000)

    assert placement == Placement(True, -140, False)
    assert landing(placement, 300, 340, 800, 0, 1000) == (200, 1000)


def test_a_menu_that_fits_neither_side_slides_down_from_above_the_row():
    """More room above than below: it stands on the row, and is lowered until its top
    edge is the room's."""
    placement = place_menu(600, 640, 800, 0, 1000)

    assert placement == Placement(False, 200, False)
    assert landing(placement, 600, 640, 800, 0, 1000) == (0, 800)


def test_where_both_sides_are_alike_a_menu_that_fits_neither_slides_from_below():
    """450 above, 450 below, and a menu of 600: the tie goes to below."""
    placement = place_menu(450, 550, 600, 0, 1000)

    assert placement == Placement(True, -150, False)
    assert landing(placement, 450, 550, 600, 0, 1000) == (400, 1000)


def test_a_menu_exactly_as_tall_as_the_room_fills_it_and_does_not_scroll():
    placement = place_menu(450, 550, 1000, 0, 1000)

    assert placement == Placement(True, -550, False)
    assert landing(placement, 450, 550, 1000, 0, 1000) == (0, 1000)


def test_a_menu_one_pixel_taller_than_the_room_scrolls():
    placement = place_menu(450, 550, 1001, 0, 1000)

    assert placement == Placement(True, -550, True)
    assert landing(placement, 450, 550, 1001, 0, 1000) == (0, 1000)


def test_a_menu_much_taller_than_the_room_starts_at_the_top_of_it_from_either_side():
    low, high = 30, 1110
    for top in (60, 500, 1000):
        placement = place_menu(top, top + 40, 3000, low, high)
        assert placement.scrolls
        assert landing(placement, top, top + 40, 3000, low, high) == (low, high)


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
        (-20, 20, Placement(True, 0, False)),
        # Half out at the bottom: only above.
        (980, 1020, Placement(False, 0, False)),
        # Wholly above the room, or below it: the menu is moved in, to the room's edge.
        (-50, -10, Placement(True, 10, False)),
        (1010, 1050, Placement(False, -10, False)),
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
                shown = min(height, high - low)
                assert placement.scrolls == (height > high - low), why
                assert low <= start and end <= high, why
                checked += 1
                if not inside:
                    continue
                below, above = high - bottom >= shown, top - low >= shown
                covers = start < bottom and end > top
                if below:
                    assert placement == Placement(True, 0, placement.scrolls), why
                elif above:
                    assert placement == Placement(False, 0, placement.scrolls), why
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
    below, shift, scrolls = place_menu(300, 340, 800, 0, 1000)

    assert (below, shift, scrolls) == (True, -140, False)


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


class FakeMenu:
    """A Gtk.Menu as popup_menu_at drives one."""

    def __init__(self, items=(), padding=(0, 0), border=0, popup_at_rect=True):
        self.items, self.padding, self.border = list(items), Padding(*padding), border
        self.style = StyleContext(self.padding)
        self.properties = {}
        self.opened = []
        self.popped = []
        if popup_at_rect:
            self.popup_at_rect = self.record_popup_at_rect

    def get_children(self):
        return self.items

    def get_style_context(self):
        return self.style

    def get_border_width(self):
        return self.border

    def set_property(self, name, value):
        self.properties[name] = value

    def record_popup_at_rect(self, window, rect, rect_anchor, menu_anchor, event):
        # What the properties were at the moment GTK was asked, not what they are after.
        self.opened.append((window, rect, rect_anchor, menu_anchor, event, dict(self.properties)))

    def popup(self, *arguments):
        self.popped.append(arguments)


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

    def __init__(self, display, offset=(0, 0), toplevel=None, height=0):
        self.display, self.offset, self.toplevel, self.height = display, offset, toplevel, height

    def get_display(self):
        return self.display

    def get_toplevel(self):
        return self.toplevel or self

    def get_root_coords(self, x, y):
        return x + self.offset[0], y + self.offset[1]

    def get_height(self):
        return self.height


X11, WAYLAND = "GdkX11Display", "GdkWaylandDisplay"


def test_under_x11_the_room_is_the_work_area_of_the_monitor_the_window_is_on(app_module):
    display = FakeDisplay(X11, FakeMonitor(Rect(0, 27, 1920, 1053)))
    window = FakeWindow(display)

    assert app_module.menu_room(window) == (27, 1080)
    assert display.asked == [window]


def test_under_x11_there_is_no_room_where_the_window_is_on_no_monitor(app_module):
    assert app_module.menu_room(FakeWindow(FakeDisplay(X11, None))) is None


def test_under_wayland_the_room_is_the_toplevels_own_span(app_module):
    """Its top is where GDK says it is, which is 0 for a window with no parent, and
    nothing is asked of a monitor: a client is not told where its window is."""
    display = FakeDisplay(WAYLAND, FakeMonitor(Rect(0, 0, 3840, 2160)))
    toplevel = FakeWindow(display, offset=(0, 37), height=600)
    child = FakeWindow(display, offset=(5, 200), toplevel=toplevel)

    assert app_module.menu_room(child) == (37, 637)
    assert display.asked == []


def test_a_room_with_no_height_is_no_room(app_module):
    display = FakeDisplay(WAYLAND)

    assert app_module.menu_room(FakeWindow(display, height=0)) is None
    assert (
        app_module.menu_room(FakeWindow(FakeDisplay(X11, FakeMonitor(Rect(0, 0, 10, 0))))) is None
    )


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
    monkeypatch.setattr(app_module.Gtk, "get_current_event_time", lambda: 777, raising=False)
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
    assert properties == {"anchor-hints": ALL_HINTS, "rect-anchor-dy": 0}


def test_a_menu_that_fits_above_stands_on_the_click(popping):
    menu = tall(400)

    popping.popup_menu_at(menu, click(screen_window(), y=900))

    [(_w, _r, rect_anchor, menu_anchor, _e, properties)] = menu.opened
    assert (rect_anchor, menu_anchor) == (GRAVITY.NORTH_WEST, GRAVITY.SOUTH_WEST)
    assert properties == {"anchor-hints": ALL_HINTS, "rect-anchor-dy": 0}


def test_a_menu_that_fits_neither_side_is_slid_by_the_anchors_offset(popping):
    """821 pixels at 300 on a screen of 1080: the click ends at 301, so the menu is lifted
    by 1080 - 821 - 301 to start at 259."""
    menu = tall(821)

    popping.popup_menu_at(menu, click(screen_window(), y=300))

    [(_w, _r, rect_anchor, menu_anchor, _e, properties)] = menu.opened
    assert (rect_anchor, menu_anchor) == (GRAVITY.SOUTH_WEST, GRAVITY.NORTH_WEST)
    assert properties == {"anchor-hints": ALL_HINTS, "rect-anchor-dy": 1080 - 821 - 301}


def test_a_menu_taller_than_the_screen_is_not_told_it_may_resize_in_height(popping):
    menu = tall(1500)

    popping.popup_menu_at(menu, click(screen_window(), y=300))

    [(*_head, properties)] = menu.opened
    assert properties == {"anchor-hints": SCROLLING_HINTS, "rect-anchor-dy": -301}


def test_a_menu_opened_again_is_given_its_placement_again(popping):
    """One menu is opened over and over: a slide, or hints taken for a tall list, must not
    stay for the next time."""
    menu = FakeMenu([MenuItem(True, 100, 100)])
    window = screen_window()
    menu.items[0].height = (1500, 1500)
    popping.popup_menu_at(menu, click(window, y=300))
    menu.items[0].height = (100, 100)

    popping.popup_menu_at(menu, click(window, y=300))

    assert menu.opened[0][-1] == {"anchor-hints": SCROLLING_HINTS, "rect-anchor-dy": -301}
    assert menu.opened[1][-1] == {"anchor-hints": ALL_HINTS, "rect-anchor-dy": 0}


def test_a_rectangle_and_a_window_given_are_used_in_place_of_the_click(popping):
    """The console button's allocation, in the window the button is drawn in."""
    window = screen_window(offset=(0, 700))
    elsewhere = screen_window()
    rect = Rect(1800, 10, 40, 30)
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


def test_where_the_room_cannot_be_told_gtk_is_left_to_place_the_menu(popping):
    """No monitor: below, as GTK would have it, with all its hints."""
    window = FakeWindow(FakeDisplay(X11, None))
    menu = tall(5000)

    popping.popup_menu_at(menu, click(window, y=900))

    [(_w, _r, rect_anchor, menu_anchor, _e, properties)] = menu.opened
    assert (rect_anchor, menu_anchor) == (GRAVITY.SOUTH_WEST, GRAVITY.NORTH_WEST)
    assert properties == {"anchor-hints": ALL_HINTS, "rect-anchor-dy": 0}


def test_under_wayland_the_window_is_the_room(popping):
    """A window 600 tall on an output of 2160: a menu of 400 opened 500 down it does not
    fit below, though the output has room, and stands on the click instead."""
    display = FakeDisplay(WAYLAND, FakeMonitor(Rect(0, 0, 3840, 2160)))
    window = FakeWindow(display, height=600)
    menu = tall(400)

    popping.popup_menu_at(menu, click(window, y=500))

    [(_w, _r, rect_anchor, menu_anchor, _e, properties)] = menu.opened
    assert (rect_anchor, menu_anchor) == (GRAVITY.NORTH_WEST, GRAVITY.SOUTH_WEST)
    assert properties["rect-anchor-dy"] == 0


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
            ("get_children", "get_style_context", "get_border_width", "set_property", "popup"),
        ),
        (StyleContext, Gtk.StyleContext, ("get_padding",)),
        (MenuItem, Gtk.MenuItem, ("get_visible", "get_preferred_height")),
        (FakeMonitor, Gdk.Monitor, ("get_workarea",)),
        (FakeDisplay, Gdk.Display, ("get_monitor_at_window",)),
        (FakeWindow, Gdk.Window, ("get_display", "get_toplevel", "get_root_coords", "get_height")),
    ):
        for name in names:
            assert hasattr(fake, name), f"{fake.__name__} is missing {name}"
            assert hasattr(real, name), f"{real.__name__} has no {name}"
    # FakeMenu has popup_at_rect on an instance only when a test asks, as a menu on older GTK
    # lacks it; the real class has it.
    assert hasattr(Gtk.Menu, "popup_at_rect")
    assert {"anchor-hints", "rect-anchor-dy"} <= {p.name for p in Gtk.Menu.list_properties()}
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
                      "dy": menu.get_property("rect-anchor-dy")})
        if not KEEP_HINTS:
            menu.set_property("anchor-hints", 0)
        return real(menu, *arguments)
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

def pointer_row(y):
    """The row a click at y is, to the menu: one pixel."""
    return y, y + 1

def open_page(name, notebook=None):
    """A tab of a kind GCM does not have yet, which needs no terminal."""
    page = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
    page.pack_start(Gtk.Label(label=name), True, True, 0)
    w.add_page(notebook or w.nbConsole, page, name)
    return page

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

    # Forty: taller than the screen. It starts at the top of the screen and is told it may not
    # be resized in height, so that GTK scrolls it; and a short list is told it may again.
    have(40)
    menu, box, (left, top, right, bottom) = press_button("forty consoles")
    assert len([item for item in menu.get_children() if item.get_visible()]) == 40
    assert app.menu_height(menu) > SCREEN_BOTTOM - SCREEN_TOP, app.menu_height(menu)
    assert box[1] == SCREEN_TOP and box[1] + box[3] <= SCREEN_BOTTOM, box
    assert asked[-1]["hints"] & RESIZE_Y == 0 and asked[-1]["hints"] & int(Gdk.AnchorHints.RESIZE_X), asked
    close(menu)
    have(3)
    menu, box, (left, top, right, bottom) = press_button("three consoles again")
    check("three consoles again, strip along the bottom", top, bottom, box)
    assert asked[-1]["hints"] & RESIZE_Y, "the hints stayed off for a short list"
    assert asked[-1]["dy"] == 0, asked
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
    close(listed)

else:
    raise SystemExit("no scenario " + scenario)
w.wMain.destroy()
print("OK")
'''


def run_scenario(scenario, tmp_path, display):
    """Run a scenario at twice the usual text size, as GCM runs, and fail on what it raised or
    GLib complained of."""
    environment = dict(os.environ, DISPLAY=display, GDK_BACKEND="x11", GDK_DPI_SCALE="2")
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
        "the-terminal-menu-with-its-hints",
        "the-console-list-with-its-hints",
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
