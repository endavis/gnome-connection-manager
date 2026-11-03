---
title: "Menus and Window Placement"
description: "Where GCM puts a pop-up menu so that it stays on the screen, and which window each window it opens is placed over, and why"
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
height and the room it has, and gives a `Placement(below, shift, scrolls)`: below the row
if the menu fits there, else above it, else on the side with more room, below on a tie,
slid along the room until it is inside, which covers the row. It lands inside the room
whichever way the row stands to it, and a menu taller than the room starts at the top of
it and `scrolls`, only when strictly taller. Pure: the numbers are arguments.

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
scrolls is not told it may resize in height, so that GTK makes it no taller than the
monitor and scrolls it (read in `gtk_window_guess_default_size` and `gtk_menu_position`;
measured, a menu of 30 items opened 1080 tall on a screen of 1080 on X11, and one of
1233 opened 1068 tall on Weston 13).

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
of its own. Not handled: the menu bar's Hosts submenu, which GTK places itself (#397), the submenus
of the terminal's menu, which GTK places too, and cutting the room to the screen rather
than the window (#402). No decision record: it is an
internal helper, and no setting, file, command line or workflow changes.

## Tests of menu placement

`tests/test_menuplacement.py` tests `place_menu` and `place_across` with no display, the
helpers with fakes, and thirteen scenarios against real GTK on a display of their own, at twice the usual
text size, with real clicks through XTest. Eight take the hints from a menu just before it
opens, `anchor-hints` 0, which leaves it where GCM asked, as a compositor that moves
nothing does. Five of them fail against the guess, two (`-at-the-right-edge`) fail against code that
only opens rightwards, and one holds `menu_height` and `menu_width` to the size GTK gives
each menu. The three `-with-its-hints` scenarios keep GCM's hints, so
that what GCM works out is not undone by the flipping and sliding X11 does itself. They
are named `against_real_gtk`, which mutmut deselects.

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
