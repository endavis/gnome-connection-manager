---
title: "Menus and Window Placement"
description: "Where GCM puts a pop-up menu so that it stays on the screen, which window each window it opens is placed over, what GTK reports of a window's place and size, and why"
audience:
  - contributors
tags:
  - gcm
  - gcm-dev
  - design
---

# Menus and Window Placement

Design notes for `src/gnome_connection_manager/utils/menuplacement.py`, the module, and for
the code in `src/gnome_connection_manager/app.py` that opens GCM's pop-up menus and windows:
why each choice was made, what was measured and with which versions, and what was rejected.
They were moved here from `AGENTS.md` (#430).

## Where a pop-up menu goes

The module says where a pop-up menu goes so that
it stays on the screen (#392). `place_menu` takes the row a menu opens from, the menu's
height and the room it has, and gives a `Placement(below, shift, scrolls, height)`: below the row
if the menu fits there, else above it, else on the side with more room, below on a tie,
slid along the room until it is inside, which covers the row. It lands inside the room
whichever way the row stands to it. A menu taller than the room `scrolls`, only when
strictly taller, and (#402) hangs beside its row on the side with more room, below on a
tie, cut to that side's space, which is the placement's `height`; it no longer starts at
the room's top. Where the row fills the whole room it has no side, and the menu is the
whole room from its top. Pure: the numbers are arguments.

`place_across` is the same decision along the other axis (#398), as Weston applies no
flip or slide sideways either. It takes the rectangle's left and right edges, the menu's
width and the room, and gives an `Across(leftwards, shift)`: on the preferred side if the
menu fits there, else the other, else the side with more room (the preferred on a tie),
slid along the room until inside. Rightwards hangs the menu's left edge from the
rectangle's left (WEST gravity); leftwards hangs its right edge from the rectangle's
right (EAST). `east` in `popup_menu_at` means "prefer leftwards": the open-console list
still opens leftwards, and now flips or slides where that does not fit. The shift goes to
GTK as `rect-anchor-dx`, set at every opening beside `rect-anchor-dy`; probed, with
`anchor-hints` 0, -50 moved a west-anchored menu from 1800 to 1750.

## Opening the five menus

`popup_menu_at` in `app.py` supplies them and asks GTK, for all five menus: the server
tree's, the terminal's, a tab's, the Mounted tab's and the open-console list. It
replaced a guess of 250 pixels and 50 spare in three, and `popup_at_pointer` and
`popup_at_widget` in the others. The shift goes to GTK as `rect-anchor-dy`. The
`anchor-hints` are set at every opening, as a menu is opened again, and a menu that
scrolls is not told it may resize in height, and is cut to `placement.height` (#402).
GTK cuts a menu to a height of GCM's choosing only through its toplevel, with two calls
before `popup_at_rect`: `set_resizable(True)`, then `set_default_size(-1, cut)`. Default
size alone does nothing (read in `gtk_menu_position` and below): `gtkmenu.c` makes the toplevel non-resizable, and for a
non-resizable window `gtk_window_compute_hints` sets min = max =
`gtk_window_guess_default_size`, `min(natural, workarea)`, so every default size is clamped
back to the monitor. `popup_menu_at` also calls `resize(width, cut)`: measured on X11, a
menu reopened with a cut of another height was placed by the size it had. A menu that fits
gets `set_default_size(-1, -1)` and `set_resizable(False)` back, as the toplevel is reused.
Probed on GTK 3.24.52 at `GDK_DPI_SCALE=2` with a 60-item menu: default size alone,
`set_size_request` on the menu or its toplevel, and `resize` after the popup did not cut
(each left 1080); `Gdk.Window.resize` after popup cuts on X11 but is lost on reopen, and
on Wayland GDK hides and re-shows the popup to do it, so it is rejected. Weston 14.0.2,
nested, ignores constraint adjustment, and cuts with the two calls.

`reset_menu_scroll` runs after each opening, on the older `menu.popup` call too (#408).
GTK keeps a menu's scroll position from one opening to the next and does not bring it
back within a menu that has become shorter: the open-console list, scrolled to its end
with 60 items and opened again with 8, opened with its first item at y=-1345 and none
in view. A scroll event, direction `SMOOTH` and `delta_y` of -1e6, emitted on the menu
(`menu.emit("scroll-event", ...)`) puts the first item at y=4 with 8 of 8 in view; GTK's
own step stops at the top. Measured, it works only once the menu is open: `menu.event`,
not `emit`, did nothing, and so did the same emit deferred to an idle. The other reset the
issue found, `select_first(False)` then `deselect()`, would also work, and
`select_first(True)` does not, as it leaves an insensitive heading out of view. Not
measured under Wayland, nor whether a reset shows for a frame first.

## Menus GTK places (#397)

A folder's submenu in the menu bar's Hosts menu, the Hosts menu itself and the cluster
window's Snippets `Gtk.MenuButton` are placed by GTK, not by `popup_menu_at`. Under
Weston, which applies no constraint adjustment, a folder of 60 hosts at `GDK_DPI_SCALE=2`
was 2592 pixels tall and its window ran to y=2635.

Why the hints cannot be set ahead, as the issue suggested: GTK 3.24.52's
`gtk_menu_item_real_popup_submenu` sets the submenu's `anchor-hints` (FLIP, SLIDE and
RESIZE) and `rect-anchor-dy` at every opening, so anything set before is overwritten. What
works, read in `gtkmenu.c`: `gtk_menu_popup_internal` shows the menu before
`gtk_menu_position` reads those properties, so a handler of the menu's `show` runs after
GTK has set them and before they are read; `gtk_menu_popdown` hides the menu, so `show`
fires at every opening. And `gtk_menu_position` calls
`gtk_window_set_unlimited_guessed_size` for a menu with RESIZE_Y, so its height is not
capped at the monitor: GTK expects the compositor to resize it.

`fit_placed_menu(menu, holder)` in `app.py` is that handler, connected for the Hosts menu
(`menuServers`) and each folder's submenu with the main window as `holder`, and for the
Snippets button's menu with the cluster window. A submenu opens beside its row, so
`menuplacement.place_beside` slides it along the room, and cuts it to the room, from the
room's top, where it is strictly taller; its shift is added to GTK's own `rect-anchor-dy`.
A menu of the menu bar or a button hangs below its item or stands above it, which
`place_menu` works out as for `popup_menu_at`, the offset being 0 for GTK there. A menu
that scrolls loses RESIZE_Y from its hints, and `cut_menu`, the block `popup_menu_at` used,
cuts its toplevel.

Measured on Weston 14.0.2 nested (`--backend=x11`, 1920x1080), GTK 3.24.52,
`GDK_BACKEND=wayland`, `GDK_DPI_SCALE=2`, 60 hosts: with the handler, maximized, the menu was
1036 pixels, from y=39 to 1078, with a scroll arrow, and scrolling reached the last host;
not maximized, 600 pixels, from 62 to 665, last host reached. Weston lands the menu about 5
pixels higher than asked, still on the screen. `menu_height` overestimates a submenu by 8
pixels (608 for 600 landed), so no test asserts an exact submenu height.

Coordinates under Wayland: GDK reports a popup's root coordinates against the main window's
content origin. `menu_room` of the submenu's own window is wrong, and cut it to 97 pixels.
What works: the room is `menu_room` of the window holding the menu (`holder`), and where the
item's GdkWindow has another toplevel than that window, which is so for an item of a
submenu in a popup, `window_content(holder)[1]` is added to the item's top.

Measured on a private Xvfb, with a handler connected after GCM's that sets `anchor-hints` to
0, as Weston leaves them: 60 hosts, from 40 to 1120 without the fix and 0 to 1080 with it; a
folder of 15 hosts low in the menu, 760 to 1360 without and 472 to 1072 with. With GTK's own
hints left on, X11 is unchanged.

Not included: Edit > Snippets' submenus and the terminal menu's Commands submenu; Terminal >
Open Consoles (`menuConsoles`, which `popup_menu_at` also opens); the horizontal axis. The
Snippets button was measured on the X11 stand-in only. Not measured on WSLg.

The scenarios in `tests/test_menuplacement.py` are `a-tall-folder-submenu-stays-on-the-screen`,
`a-low-folder-submenu-slides-onto-the-screen` (each also with GTK's hints kept),
`a-hosts-menu-of-top-level-hosts-stays-on-the-screen` and
`the-cluster-snippets-button-stays-on-the-screen`. The Hosts menu one passes without the fix
too: with its hints at 0 GTK caps a menu itself on X11, which Weston's RESIZE_Y does not
allow, so it holds the menu on the screen and not GCM's part; the fakes hold that.

## Why X11 hid it

X11 hid the bug, as GTK flips and slides a menu itself. Under Wayland GTK sends flip,
slide and resize to the compositor as the positioner's constraint adjustment, and reads
the result. Weston's libweston-desktop, which WSLg's compositor is built on, ends
`weston_desktop_xdg_positioner_get_geometry` in a TODO and returns the geometry
unadjusted: read in 9.0.0, in WSLg's `xdg-shell.c`, which is identical to 9.0.0's, and in
13.0.0. Measured on a nested Weston 13, a menu from the foot of the tree hung 240 pixels
past the screen. Not re-measured on WSLg itself.

## A menu's height

`menu_height` adds up the natural heights of the items showing, and the menu's padding.
A menu is not asked: one that is not showing answers `(0, 0)`, measured, and showing it
to ask emits its `hide` when it is hidden again, which clears the click's context. At
twice the usual text size on X11 the sum is the popped-up menu's height to the pixel:
549 for the server tree's menu on a host, 414 on a folder, 279 on the blank space, 821
for the terminal's, 323 for a tab's and 189 for the Mounted tab's. The CSS padding above
and below counts, 4 and 4 adding 8 and 7 and 3 adding 10, and so does twice the
container's border width. The CSS margin and border, and the deprecated
`vertical-padding` style property, each changed in turn, add nothing. GTK sizes a menu
already shown by the style it had then: after a provider was added, the popped height
stayed 195 where the height worked out from the style context was 198.

## A menu's width

`menu_width` is `Gtk.Menu.do_get_preferred_width(menu)[1]`, GtkMenu's own size vfunc,
called through the class: the bound `menu.do_get_preferred_width()` raises `TypeError` in
PyGObject. It skips the visibility check and shows nothing, so emits no `hide`. Probed on
X11 at twice the usual text size, it gives the landed width to the pixel even before the
first showing: terminal 555, tab 552, server tree (host) 514, Mounted 272. Rejected:
`menu.get_preferred_width()`, which answers `(0, 0)` while the menu is hidden, even after
it has been shown once; and the items' natural widths summed, 329 for the terminal's menu
against 555, as the menu adds its toggle and accelerator columns.

## The room a menu has

`menu_room` gives the room on both axes, (left, top, right, bottom). It is the monitor's
work area under X11. Under Wayland it is the toplevel's own span: a client is not told where its window is, and GDK puts every window with no
parent at (0, 0) -- read in `gdk_window_wayland_get_root_coords`, and measured on Weston
13, where a window at output y=505 reported root coordinates (0, 0) -- so a monitor's
geometry means nothing. That is so on every Wayland compositor, decided in #392 over
limiting it to WSL, which cannot be told reliably: a menu that fits inside GCM's window
stays inside it, and in a window smaller than the screen it may now flip or slide
within it where a compositor that moves menus let it hang below. Not measured on one.
A maximized window fills the output, and X11 is as before.

## The rectangle a menu opens from

The rectangle is the click in `event.window`, as `popup_at_pointer` has it, and not the
widget's `get_window()`. A terminal has no window of its own, so that is its parent's:
against the guess, the terminal's menu opened 6 pixels from the pointer, measured. For
the server tree, a tab's label and the Mounted list the two coincide, measured: the
tree's bin window, where its cell areas are, stays where the tree's own window is as it
scrolls, with its header hidden as GCM has it, and a tab label's event box has a window
of its own. Not handled: the submenus of the terminal's menu and of Edit > Snippets, and Terminal >
Open Consoles' list as a submenu, which GTK places too; the menu bar's Hosts menu and its
folders' submenus are, in the next section (#397). Under Wayland the room is the window's
content, `window_content`, the span of the `Gtk.Window`'s child, not its GdkWindow: measured
on Weston 14, GCM's main window not maximized was 1920x282 with its child at
(26, 67, 1868, 186), so the GdkWindow counted 29 pixels of invisible shadow below the
visible edge; maximized there is none, and on X11 the child is at (0, 0, w, h). Not
measured: sway, mutter, WSLg itself, and whether WSLg draws GCM with client-side
decorations. Weston puts a menu anchored SOUTH 12 pixels low, as before; the menu stays in
the window. A menu that fits the room but fits neither side still slides over its row
(#392), so a console list a little shorter than the room covers the button by the
difference. No decision record: it is an
internal helper, and no setting, file, command line or workflow changes.

## Scrolling a long menu (#399)

GTK moves a menu that is cut short by 15 pixels for each notch of the wheel
(`MENU_SCROLL_STEP2`), however tall a row is. Measured with real XTest wheel clicks on a
120-item `Gtk.Menu` cut to 1080 pixels, on a private Xvfb: 15 pixels at `GDK_DPI_SCALE` 1 and
2, where the rows were 25 and 40 pixels. XTest sends only discrete `DOWN` and `UP` events
(delta 0, source device "Virtual core XTEST pointer"); GTK's smooth step is `delta_y * 15`.

`install_menu_wheel`, called once from `GcmApplication.do_startup`, adds an emission hook,
`GObject.add_emission_hook(Gtk.Menu, "scroll-event", ...)`, which reaches every `Gtk.Menu`,
including the menubar's Snippets submenus GTK builds from a menu model and the Hosts folder
submenus `add_folder_rows` rebuilds on every `updateTree`. For each notch it emits one more
smooth scroll, so that GTK's 15 pixels and the extra come to a row. That the hook is
process-wide, and not a handler on each menu, was the repo owner's decision; a long
combo-box popup or entry context menu scrolls a row a notch too, which is accepted.
Rejected: a `connect` on each menu (about eleven places, and the model-built submenus
cannot be reached), and stopping GTK's own step from the hook, which GLib refuses:
`emission of signal "scroll-event" ... cannot be stopped from emission hook`. So the hook
adds to GTK's step.

- **Only a real notch.** The hook acts on an event whose `get_source_device()` is not None.
  `reset_menu_scroll`'s event (#408) and the hook's own have none, so neither is scrolled
  again; real wheel events have one.
- **The shortest row.** `menu_row_height` is the shortest shown item that is not a separator,
  by allocated height. With half a menu's rows two lines tall (40 and 67 pixels at scale 2) the
  median gave 53 pixels a notch and the shortest 40, a single line's.
- **Half a pixel.** `wheel_extra` adds `copysign(0.5, delta)`: GTK truncates, and without it a
  notch gave 39 pixels for a 40 pixel row, with it exactly 25 and 40, up and down.
- **Smooth scrolling** is scaled by the same row over 15, as a real mouse under Wayland and
  with XI2 on X11 sends 1.0 for a notch. Measured with a synthetic smooth event: 1.0 moved
  40 pixels and 0.1 moved 4 at scale 2. Not measured with a real touchpad, nor on Wayland.

A menu that fits does not move, with the hook and without it (six notches).

## Tests of menu placement

`tests/test_menuplacement.py` tests `place_menu` and `place_across` with no display, the
helpers with fakes, and scenarios against real GTK on a display of their own, at twice the usual
text size, with real clicks through XTest. Eight take the hints from a menu just before it
opens, `anchor-hints` 0, which leaves it where GCM asked, as a compositor that moves
nothing does. Five of them fail against the guess, two (`-at-the-right-edge`) fail against code that
only opens rightwards, and one holds `menu_height` and `menu_width` to the size GTK gives
each menu. `a-menu-stays-inside-a-short-window` stands in for Wayland's room with
`window_content` in a window 400 pixels tall (#402). The `-with-its-hints` scenarios keep GCM's hints, so
that what GCM works out is not undone by the flipping and sliding X11 does itself. They
are named `against_real_gtk`, which mutmut deselects.

A scenario takes where it clicks from the font in use, not from a count of the rows that fit
(#500). On a WSL2 Ubuntu 24.04 machine with `fonts-noto-core`, GTK's default font, Sans,
resolved to Noto Sans, whose rows are taller than DejaVu Sans's. Scenarios that had counted the shorter font's rows
failed there every time: the tree's last row fell below the short window, and the Hosts menu's
last folder off the screen. GCM did what #397 and #402 made it do in both. So a scenario
scrolls the row it clicks into sight, and gives a menu as many items as fit by its measured
row, `menu_row_height`. Pinning a font was rejected: the scenarios would test one font's
metrics, and need that font installed.

Seven more scenarios hold the wheel (#399), six of them at both text sizes: the console list
from the tab strip, Terminal > Open Consoles, a Hosts folder, the menubar's Snippets, the
cluster window's Snippets button, the terminal's menu on a screen of 600 pixels, and a menu
that fits. Each makes six notches and reads how far the first item moved. Without the call
in `do_startup` every one moves 15 pixels; without the half pixel, the pure test of the
exact step fails. A menu is opened under its menubar item by `popup_at_widget`: a click on
the item made GTK say that a menu's toplevel is no window.

## Which window a window opens over

A window GCM opens has a transient parent, bar six (#403). Under Wayland GTK cannot place
a window: the compositor does, over the window's transient parent where it has one, and
wherever it likes where not. The host dialog, the buffer viewer, Preferences and the mount
messages were reported to open at random places on WSLg. `dialog_parent` in `app.py` says
which window, and everything asks it: the modal window on top, else the parent the caller
names, else the console window in use, else the main window, else none. Modal first, since
a window opened over a modal one must sit above it, and a chain is unambiguous where two
siblings of one parent are not.

`modal_window` is the toplevel of the widget holding
`Gtk.grab_get_current()`, kept only while it is visible and of type `TOPLEVEL`. Measured
on X11 with GTK 3.24.41: inside `msgbox` it is the message; with the host dialog open it
is the host dialog, and with Preferences open it is Preferences; a message shown over the
host dialog takes it and gives it back as it closes; with a popup menu showing the grab is
the menu, whose window is no toplevel, and with the About dialog, which is not modal, or a
console window in use, there is none.

A parent a caller names is kept unless a modal
window is on top, as the server tree's New Folder, Rename Folder, Tab Color, Import and
Export name the main window, where that tree is. A dialog about a console names none, so
it opens over `window_in_use`, which `page_in_use` goes by: Save Buffer, the `{?Label}`
prompts of a snippet, the transcript's messages and Rename tab. `Whost`, `Wconfig`,
`Wcluster` and `Wabout` ask it in place of `wMain.window`, since their keys work in a
console window, where they opened over the main window, perhaps on another monitor.
`BufferViewer` and `SnippetPicker` call `set_transient_for(dialog_parent())` in their
`__init__`.

## Windows with no parent

The six with no parent are in `EXEMPT` in `tests/test_dialog_parents.py`, each
with its reason: `require_expect`, `require_config_dir` and `require_readable_config`,
which run from `main()` before any window exists; `Wmain`, the root; `ConsoleWindow`
(#255), a peer of the main window that is moved to another monitor on purpose, where a
transient window is kept above its parent and goes with it when the parent is minimized;
and the `Gtk.OffscreenWindow` of `TranscriptReplayer.start`, which is never on a screen.

## Tests of the parents

`tests/test_dialog_parents.py` holds the rule over `app.py` with `ast`, naming each window
built with no `parent=` or `transient_for=` that is a call of `dialog_parent`, and each
class of windows with no `__init__` of its own that sets one, and opens the windows
against real GTK; `tests/test_dialog_parent_order.py` holds the order.

Not measured: where
WSLg puts a window that has a parent, and GCM already gave the host dialog and Preferences
the main window when they were reported, so it may not be over it either; whether a
message shows while its parent is minimized, as a mount's result can now be, where it
appeared on its own before. The measurements and the scenarios are X11 with no window
manager: they say what GCM asks for, not where a Wayland compositor puts a window.

## A dialog is shown filled (#424)

A dialog used to be presented by `GladeComponent.__init__` before `new()` filled it, so
it opened small and grew, and the window manager placed it once at the small size and
then again after `fit_window_to_monitor`. `GladeComponent` now shows a dialog's children
only, so that `new()` can still hide what a type does not use, and `show_dialog` sizes
the window with `size_window_for_monitor`, maps it, and queues `fit_window_to_monitor`
for placement alone. Before a window is realized `monitor_workarea` reads the monitor of
its transient parent. `Whost` is filled after `__init__` returns, so it sets
`SHOWN_BY_INIT` and its `init` calls `fill` and then `show_dialog`. The signals are still
connected after `new()` and before the dialog is shown, so a new host's dialog runs no
`on_cmbType_changed`. `tests/test_window_fit.py` records each dialog's size at its first
map and holds it equal to the size it keeps, on the real work area and a small one.
Cluster keeps its glade default size, which no fit touches; that was not changed.

Measured on headless sway 1.11 (`WLR_BACKENDS=headless`, `GDK_BACKEND=wayland`, `WAYLAND_DEBUG=client`),
opening Preferences, New host and Edit host eight times each, the window geometries each
dialog's xdg_surface was given, a size listed again only when it changed. Before, on
`main`: Preferences `289x245 -> 597x1013 -> 794x984` and a host dialog
`544x453 -> 544x474`, every time. After: `794x984` and `544x474`, so each window's
first set_window_geometry is its last. This was not measured on WSLg's Weston.

## A window's geometry

What GTK 3 reports of a toplevel's place and size, which `fit_window_to_monitor` and its
helpers read. Measured for #550 with GTK 3.24.41 on three servers:

- a private Xvfb, which has no window manager;
- WSLg's X11, `DISPLAY=:0` and `GDK_BACKEND=x11`, whose window manager names itself
  Weston WM, at `GDK_SCALE` 1 and 2, with `GDK_DPI_SCALE` alike;
- Wayland, on headless sway 1.9 and on WSLg.

Places and sizes are in GDK's units, pixels divided by the scale. No GNOME, mutter or
KWin was available.

**The frame is not read back.** `Gdk.Window.get_frame_extents()` is the window manager's
frame around a window, and `Gtk.Window.get_size()` is GTK's own size. After a `resize()`
the two change at different moments. Under Weston at scale 2, a 400 by 300 window had a
frame 39 wide and 49 tall. Resized to 900 by 700, the extents had the new size several
milliseconds before `get_size()` did, so the extents less the size made a frame of 539
by 449; resized back, the frame was −461 by −351. Xvfb, with no frame at all, gave 500
by 400 and −500 by −400 in the same way. That subtraction, made during a resize, once
gave a frame of 736 pixels and shrank a dialog to 127 (#82). So `WINDOW_FRAME_ALLOWANCE`
allows a fixed 96 for the frame, in GDK's units. Weston's frame was 97 tall at scale 1
and 49 at scale 2, so at scale 2 the allowance is about twice the frame. The 89 to 97
pixels under GNOME in the constant's comment, from #82, were not measured again.

**`resize()` and `move()` are asynchronous.** Right after `resize()`, `get_size()` gave
the old size, and the new one 7 to 8 ms later, under Weston and on Xvfb alike. Right
after `move()` under Weston, `get_position()` gave the old place, and the new one 7 to
13 ms later. On Xvfb, with no window manager to wait for, it gave the new place at once.
So `fit_window_to_monitor` works from the size `size_window_for_monitor` asked for,
not one read back. Nor does a reading hold still between events. Two readings taken in
one idle callback, with no event handled between them, gave (0, 0) and then (19, 29)
in one run, and (0, 0) and then −16384 in another.

**What `get_position()` counts** is where the window manager's frame starts, not the
point a window was moved to. Under Weston, a window moved to (x, y) read back
(x − 32, y − 32) at scale 1 and (x − 16, y − 16) at scale 2, in each of seven moves.
At scale 1, its content, by `get_origin()`, began 6 across and 27 down from that
point, so the frame starts 32 pixels above and to the left of it. A window moved to
y = 0 read y = −32, or −16 at scale 2: under Weston, a negative y is a window at the top
of the screen, not one off it. On Xvfb, a window read back the place it was moved to.

A window with client-side decorations (a header bar for its title bar) has a margin of its
own inside its GDK window, 5 pixels at its top and left on Xvfb and under Weston.
`get_position()` leaves that margin out: on Xvfb, such a window moved to (200, 0) read
(200, 0), with its GDK window at (195, −5). Under Weston it read back (x − 19, y − 30).
In both runs that tried, Weston ignored its move to (200, 0), though it honoured the
plain window's move to the same point. Why was not established.

**Before a window is placed**, `get_position()` gives more than one reading. From
`show_all()` until Weston placed a window, the readings were:

- at scale 1: (38, 59), then (−32768, −32768), then its place, 13 ms after `show_all()`;
- at scale 2: (0, 0), (19, 29), then (−16384, −16384), then its place, 18 ms after;
- for a `Gtk.Dialog` with a transient parent, at scale 2: (1122, 1000) until shown, then
  (0, 0), (−16384, −16384) and its place;
- on Xvfb: (0, 0) throughout, for both.

(38, 59) and (19, 29) are where the window's content sits inside its frame. The sentinel
is −32768 divided by the scale, like every other coordinate.

`onscreen_position` counts a coordinate at or below `UNPLACED_WINDOW_COORD`, −30000, as
not yet placed. That catches the sentinel at scale 1 and none of the other readings. This
was measured with GCM's own code, following `GladeComponent.show_dialog`'s steps on a
`Gtk.Dialog` under Weston. In each of three runs, the idle that runs
`fit_window_to_monitor` read (0, 0), before the dialog was placed. At scale 2 it moved the
dialog both times, to the top left corner of a monitor its parent was not on, and once the
dialog stayed there. At scale 1 it moved nothing, in one run. Under Wayland, which GTK
picks whenever `WAYLAND_DISPLAY` is set, as WSLg sets it, `move()` does nothing (below).

**Whether a user can see a widget** is settled in root coordinates. Take the bottom of
the widget's allocation through `get_window().get_root_coords()`, and compare it with the
bottom of its monitor's `get_workarea()`. On Xvfb, a window 300 tall moved down until 150
of it showed put its OK button's bottom edge at 1230, against a work area ending at 1080.
`test_a_dialog_left_below_the_screen_is_brought_back_against_real_gtk` in
`tests/test_window_fit.py` reads its buttons this way.

**Placement varies from run to run.** Weston placed the same 400 by 300 window at
(532, 984), (1287, 1071) and (312, 981) in three runs at scale 2. So a test of a
placement fix puts the window where it needs rescuing, as that test moves a dialog below
the screen. It does not wait for a window manager to put it there.

**Under Wayland** the compositor places a toplevel, and GTK cannot. On sway, a window
moved to (300, 200) stayed where sway had centred it, at (758, 390) by
`swaymsg -t get_tree`. Under WSLg's Wayland, neither `get_position()` nor `get_origin()`
changed. Nor does a client learn where its windows are, as
[The room a menu has](#the-room-a-menu-has) says. `get_origin()` gave (0, 0) on both, and
`get_position()` gave (0, 0) on sway and (26, 23) on WSLg; neither is a place on the
screen. A menu opened at (100, 100) in its window gave `get_origin()` (100, 100) on sway,
a place in that window. So a probe that measures where a window lands on WSLg runs with
`GDK_BACKEND=x11`, under Weston's X11 window manager. It measures X11's placement, not
the compositor's, which GCM's windows get there by default.
