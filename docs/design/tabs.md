---
title: "Tab Names and Colours"
description: "What a host's tab is called and the colour it is marked with, in the tab, the server tree and the Hosts menu, and why"
audience:
  - contributors
tags:
  - gcm
  - gcm-dev
  - design
---

# Tab Names and Colours

Design notes for what a host's tab is called and the colour it is marked with: the modules
`src/gnome_connection_manager/utils/tabnames.py` and
`src/gnome_connection_manager/utils/tabcolors.py`, and the code in
`src/gnome_connection_manager/app.py` that names and colours the tabs, the server tree and
the Hosts menu. They say why each choice was made, what was measured and with which
versions, and what was rejected. They were moved here from `AGENTS.md` (#430).

## A host's tab name

`src/gnome_connection_manager/utils/tabnames.py` decides what a host's tab is called (#346).
`tab_name` gives a host its name, and where another host has the name, in another
folder, as much of its folder path as tells it apart from each, in front, folder first:
`infrafoundry/ansible` beside `pyproject-template/ansible`. A host at the top level keeps
its name. Pure, and judged among the configuration's hosts, not the open tabs', so a tab
is not renamed as others open and close. `host_tab_name` in `app.py` judges it among
`groups`, through the host there with the id of the one given: the host dialog builds a
new record for a host it edits, and a tab keeps the record it was opened for, as
`NotebookTabLabel.host`. A clone of a tab keeps the id for the same reason, where
Duplicate Host's copy, a second host, does not. `addTab` and `open_type_page` name a
tab so. Every change to the hosts redraws the tree, and `updateTree` ends in
`name_tabs`, which names each tab not renamed by hand again through `set_name`. Then
`title_windows` titles the windows again, not through `on_tab_focus`, which clears a
tab's mark, and `name_cluster_consoles` names an open cluster window's rows, since that
window is not modal. `name_tabs` does nothing while `count`, the tabs open, is 0, as it
is at class level for a `Wmain` built without `new()`, as tests build one.

## The whole path beside a name

`whole_path` is a host's folders and name, which a tab's tooltip, the open-console list
and the cluster window show beside its name (#347). `host_path` in `app.py` reads it from
the host `configured_host` finds, as `host_tab_name` does, and `set_name` gives it to a
tab renamed by hand too. `NotebookTabLabel.get_path` shows it only where it says more
than the tab's identity: not for a host at the top level, nor the Local console,
nor a #346 name that is the whole path already, and always for a renamed tab, which hides its
host. `with_path` puts it on a second line of a list, smaller and fainter by alpha.
Measured in a menu built as the open-console list's, a row with it was 43 pixels tall
against 27, and 85 against 50 at a font scale of 2.25. On the same line it made the
menu twice as wide, and as a tooltip it showed one row's path, half a second after the
pointer stopped there. `Wcluster.draw_console` reads it from the row's terminal's tab as
the row is drawn, so the cluster window's store keeps its columns. A row rewritten by
`name_cluster_consoles` is drawn again even with the same name, as the store emits
`row-changed` for it, measured.

## Preferences' Tab name

What a tab is named before the folders go in front is Preferences' Tab name,
`conf.TAB_NAME`, a template of the host's values that `templated` fills, the host's
name where it gives nothing (#348). The folders go in front of what it gives, so the
prefix compares template outputs, not names. `namer` fills it once for each host and
names any number of tabs from that: naming 50 tabs among 1000 hosts took 58 ms with the
template filled again for every tab and 2 ms with the namer, the best of 5 runs,
measured. `tab_namer` in `app.py`
builds one for each `name_tabs`. The Local console keeps `local`, through
`is_local_console`, since its type reads ssh and it has no address. Preferences' OK
stores the template and then redraws the tree, which renames the open tabs.

## A host's own tab name

A host's own tab name, `Host.tab_name` from Tab name on the host dialog's Properties
tab, names its tabs in place of the template (#349). `own_name` fills it as the
template is filled, and it is used as it is, with no folders in front. The other hosts
are compared against what each one's tab shows before any folders, an own name where
there is one. So a host whose tab would read as another's own name takes its folders,
and two hosts of one name lose theirs once one is named otherwise. An own name that
gives nothing counts as none. `tab_namer` reads it from the host `configured_host`
finds, so the host dialog's OK renames the host's tabs through `updateTree`. The field
is greyed and cleared for a type that opens no tab, as the command after disconnecting
is, and OK saves none for one.

## A tab's colour

`src/gnome_connection_manager/utils/tabcolors.py` decides the colour a host's tabs are marked
with (#350): `tab_color` gives the host's own, else that of the nearest folder above it
with one, `folder_color`, else none. `color_of` reads only `#rgb` and `#rrggbb`, so a
hand edit can put nothing else into the CSS, and a value it cannot read colours nothing
and is kept as written. `stripe_css` is the CSS of a stripe `STRIPE` pixels tall across
the top of the tab: an inset `box-shadow`, which takes no room. Not the background,
which the cluster window's tick and the attention mark colour, and not the bottom, where
Adwaita and Yaru mark the tab in use, measured with each and its dark variant, Yaru
from Ubuntu's `yaru-theme-gtk` unpacked into a scratch folder: GTK here names Yaru but
draws Adwaita, as Yaru is not installed. `NotebookTabLabel.set_color` gives a tab its
own `Gtk.CssProvider` the first time it has a colour, so a tab never given one is drawn
as before, and the class `colored`, for which `data/style.css` starts a mark `GAP`
below the stripe: without the gap, measured, a stripe of the mark's own colour did not
show on it. `host_tab_color` in `app.py` reads it through `configured_host`, as
`host_tab_name` does, and `add_page` and `name_tabs` give it to the tabs, so the host
dialog's OK, a folder's colour and a move reach the open tabs through `updateTree`. A
folder's colour comes from `color_selected_folder`, the folder's **Tab Color**, through
`choose_tab_color`, GTK's colour chooser with a No Color button, `NO_COLOR`. The host
dialog's `chkTabColor` is greyed and unticked for a type that opens no tab, and shows
the folder's colour while unticked. `tests/test_tabcolors.py` reads the pixels of real
tabs, drawn into an image rather than read from the screen.

## The colour in the tree and the Hosts menu

The server tree and the Hosts menu show the colour as `MARK`, a square, before the name
(#358). `row_color` in `app.py` gives a host's row `tab_color` and a folder's row
`folder_color`. `draw_name`, the name renderer's data function, puts `mark_markup` in
the name's own text, so the square is the name's size and on its line, and hands a row
without a colour to `draw_mount_mark`, which draws it as before. It is not a cell of its
own, which moved the name off `get_cells()[1]`, where a test reads it, nor a column of the
model, which tests slice from column 5. The markup puts the square on a patch of the
row's own background, the model's column 3. Measured in Adwaita, without it a square of
the selection's colour could not be seen on the selected row: `#3584e4`, which the host
dialog's colour button starts with. `label_menu_item` gives a Hosts menu item the
menu's background in the same way, as Adwaita draws a hovered item `#3584e4` too.
`colored_items` keeps those items for `on_tvServers_style_updated`. Measured, a change
of theme emits the tree's `style-updated` once, when the menus already give the new
background, and emits no hidden menu's own. The real-GTK scenarios read a row's pixels in
the mark's own box, which Pango measures: on a selected row in Adwaita, the text beside
it is white, the colour of a patch on a white row.

## The status bar

`make_status_bar` builds one for the main window and one for each `ConsoleWindow` (#405), and
`Wmain.update_status_bars` writes them: the whole label of the tab each window shows, from
`NotebookTabLabel.get_display_text`. It is off by default, `conf.SHOW_STATUS_BAR`, and a
bar calls `set_no_show_all` so that `show_all` leaves it hidden while it is off.

`switch-page` is emitted before the notebook's current page changes, so inside it
`get_current_page()` still answers the tab being left. `on_tab_focus` therefore passes the
page it is moving to. The other callers read the current page: `on_window_set_focus` when
the pane in use changes, `apply_settings_to_open_consoles`, `NotebookTabLabel.render_label`
(a title, a rename) and `open_console_window`. The main window's bar follows the pane in
use and ignores Dynamic title, which is about the window's title only.

A bar's label is ellipsized by GTK where the window is too narrow, and the bar's tooltip
carries the whole text. A bar is written only when its text changes.

## Dragging a tab

A tab dragged outside every notebook opens a console window (#255): under X11 GTK asks for one
through `create-window`, and under Wayland, where GTK reports the drop as an error and puts
the tab back, `on_notebook_drag_failed` moves it out itself.

A tab let go over another window's console used to open a window too (#407). A terminal has a
drag dest of its own for files and text, and in GTK 3 a site that matches no target answers
status 0 and ends the search there, so the notebook around the terminal never saw the drop.
So `addTab` gives each terminal the `GTK_NOTEBOOK_TAB` target as well, with the info
`TAB_DROP_INFO`, and `Wmain.take_dropped_tab` moves the tab to the notebook holding the
terminal's page, from an idle once the drop has finished, as `move_page` puts it.

The terminal decides its own motion, `on_terminal_drag_motion`: MOVE for a tab while
`dragged_tab` is set, COPY for files and text, 0 otherwise. The flags are
`Gtk.DestDefaults.DROP`, not ALL, so GTK offers nothing itself and a text or file source is
never offered MOVE. A tab dropped on its own console stays, and finishes as a success so that
no window opens. A page that is not a terminal is out of scope and still opens a window.

The target is found from the widget tree, not by asking GDK which window has the pointer when
the drag fails: under Wayland the pointer belongs to the data device for the whole drag, so
that is a timing question, and the drop would have failed already. (Once a drag has failed, GCM
does ask GDK where the pointer is, to keep a tab on a split's bar (#534) and to find the notebook
it was let go over (#538). That is after the compositor cancelled the drop, so it finds where the
tab should go and does not receive the drop. See below.)

Measured with a real pointer: under X11 (XTest on a private Xvfb) a tab dropped on a console
window's terminal gets `drag-data-received` with `TAB_DROP_INFO` and joins that window, where
before the change it opened a third. On sway 1.11, headless, with a virtual pointer, a drop on
a console window's terminal, on the main window's, and on the tab's own terminal each did the
same. A drop on the bare output there was not measured: the drag never ended, before the
change or after it.

### A tab let go on a split's bar stays (#534)

The bar between two panes of a split is the paned's handle, and it took no tab. GTK looks for a
drop site from the widget under the pointer up through its parents, and each pane's notebook
and consoles take a tab over their own area, so a tab let go on the bar found none. Measured
under X11 (XTest on a private Xvfb, `tests/test_console_window.py`), it opened a console
window, as a drop anywhere else outside the notebooks does. Under Wayland, where WSLg's
compositor sends `cancelled` for every release no client accepted, as #534 read in WSLg's
Weston source, `on_notebook_drag_failed` moved the tab out. The bar lies between two places
that take a tab, so a drop on it is a near miss and not a drop outside every window.

So `split_notebook` gives each split's paned a drop site of its own, `watch_split_drops`, with
no defaults, as a terminal has: `on_split_drag_motion` offers MOVE for a tab of this
application (`dragged_tab` set) over the handle and returns False for anything else, so GTK
goes on up the tree as it did before. `on_split_drag_drop` finishes the drop as a success and
moves nothing, as `take_dropped_tab` does for a tab let go on its own console. The drag then
ends as a drop, with no window, and GtkNotebook's own `drag-end` puts the label back. Nothing
is queued, as no tab moves.

The handle is `Gtk.Paned.get_handle_window`, not the gap between the panes' allocations: the
second pane's allocation starts at 0,0 in a window whose origin is that pane's own corner, so
it cannot be compared with the handle's. The point a drop site is given is relative to the
paned's allocation, in the window the paned is drawn in, and the scenario asserts it against
where it put the pointer. A drag straight from the bottom pane's strip to the bar was never
heard by the paned. The tab stayed in its notebook and no window opened, but whether a drag
began was not recorded. So for that pane the scenario goes up into the top pane and back down
onto the bar.

Only a split's paned has the site. A tab let go on the bar between the server pane and the
consoles still opens a window, and so does one let go on the toolbar, which the scenario checks
too. The first bar's hit area is 9 pixels wide and reaches into the consoles' side, where the
split's paned hears the drag over the margin of its first pane and declines it, as it does any
spot that is not its handle.

A quick flick onto the bar is a drop the site cannot take. Under WSLg a release made before any
drop target has answered is cancelled by the compositor, near the bar or not. #534's trace has
the two drops that opened a window released 28 and 33 ms after `drag-begin`, and the first
answers to the run's other drags came 19 to 73 ms in. So where GCM opens the window,
`move_out_after_drag` first asks `pointer_on_split_bar`, and the tab stays if the pointer is on
the handle of a split's paned. Under X11 `move_out_after_drag` is never queued, and
`on_notebook_create_window` is untouched.

`pointer_on_split_bar` first requires the pointer to be over the main window: the window
`Gdk.Device.get_window_at_position` returns must have the main window as its toplevel, or the
answer is False. GDK 3.24's Wayland device computes a window-relative position from the
pointer's focus surface (`gdk_wayland_device_query_state`, as read), so over another window of
GCM's the position would not be the handle's. Then it reads the pointer's place in the handle
window of each split's paned with `Gdk.Window.get_device_position`, walking `console_side()`
with `collect_paneds`, so the paned between the server pane and the consoles is not among
them. If asking raises, the tab moves out as it did before.

Why GDK should know the pointer's place when the idle runs, read from WSLg's Weston source: on
the release it sends the source `cancelled`, ends its drag grab and sends the surface under the
pointer `wl_pointer.enter` with the pointer's position, all in one batch. `GCM_TRACE=drag`
writes what `pointer_on_split_bar` read (the window under the pointer as main, other or none,
and the pointer's place in each handle in pixels), and that a tab stayed, so the hand check on
WSLg will show it. Measured under X11, with `move_out_after_drag` called by hand and the
pointer put by XTest (`tests/test_console_window.py`): the pointer is on the bar from the
handle's first pixel row to its last, and not a pixel beyond; over a console, the toolbar, the
bar between the server pane and the consoles, another window of GCM's and outside every window
it is not; and the tab stays on the bar and moves out elsewhere.

Not measured when #534 merged: WSLg by hand with this change, so Wayland was the source's
reading and not a measurement. That covered the drop site and the flick check alike, and left
open whether GDK knows the pointer's place when `move_out_after_drag` runs. The WSLg runs #538
reports answered that: in #533's hand check and in #537's measurement and fix check, every
`pointer_on_split_bar` reading gave a place in the main window. None of them was on a bar, so a
flick onto one under WSLg is still not on record.

### A tab let go over a notebook stays or joins it (#538)

The bar check above kept a tab in one case only. Under WSLg a release made before any drop
target has answered is cancelled by the compositor wherever the pointer is, so
`on_notebook_drag_failed` queued `move_out_after_drag` for a tab let go over a notebook as it
did for one let go on the desktop, and a console window opened for it. In one hand check, 15 of
74 drags did so. Each failed 23 to 93 ms after `drag-begin`, before any target answered. None
was a stuck drag (#537): no release reached a notebook during any of them. `pointer_on_split_bar`
read the pointer each time, in the main window: 13 in the bottom pane, the one the drags came
from, 95 to 128 px below the split's bar, and 2 in the top pane, 705 and 732 px above it.
Earlier runs of the same day did the same: 5 windows in #533's hand check and 12 in #537's
measurement. In the first, 4 of the 5 were drags from the bottom pane let go 41 to 62 px above
the bar, in the other pane. So a tab headed for another pane opened a window too.

GDK knows where the pointer is when the idle runs, so `move_out_after_drag` asks it where the
tab would have gone. After the bar check, which stays first, it asks `notebook_under_pointer`:

- over the tab's own notebook, the tab stays;
- over another console notebook, a pane's or a console window's, the tab joins it with
  `join_after_drop`, as a drop there would, and focuses it;
- over none, the tab moves to a window of its own as before. That is a tab let go outside every
  window of GCM's (#255), and one let go in the main window where no console notebook is, as on
  its toolbar or its server tree.

`notebook_under_pointer` finds the window under the pointer with
`Gdk.Device.get_window_at_position` and takes its toplevel for the main window, whose notebooks
are those `collect_notebooks` finds under `console_side()`, or for a `ConsoleWindow` in
`console_windows`, whose one notebook is its `notebook`. Any other toplevel, or none, answers
None with no position read, because GDK 3.24's Wayland device works a window-relative position
out from the pointer's focus surface (the reason `pointer_on_split_bar` gives for asking only
while the pointer is over the main window). Then it reads the pointer once, with
`Gdk.Window.get_device_position` on that toplevel, and `Gtk.Widget.translate_coordinates` takes
the place into each of the window's notebooks. A notebook counts over its whole allocation, the
tab strip and the console alike: a console takes a tab let go on it since #407. PyGObject answers
`translate_coordinates` with the place as `(x, y)`, or with None for a widget it cannot reach, and
not with a flag before them. A lookup that raises is logged and counts as no notebook, so the tab
moves out as it did, as the bar check's failure does. Nothing changes under X11, where
`move_out_after_drag` is never queued.

`GCM_TRACE=drag` writes what was read, in numbers: `notebook_under_pointer` names the window
under the pointer (main, console window N, other or none), the pointer's place in it and the
notebook found by its number, and `move_out_after_drag` says that the tab stays over its own
notebook, joins notebook N, or moves to a window. Never a console's text.

Measured under X11 (XTest on a private Xvfb, `tests/test_console_window.py`), with
`move_out_after_drag` called by hand and the pointer put where Wayland's would be: the pointer is
over the main window's two panes and a console window's notebook from the first pixel of their
allocations to the last, and not a pixel beyond; a tab stays over its own console and its own
tab, in a pane and in a console window; it joins the other pane over its console and over its
tab strip, and the pane it leaves, emptied, goes as it does when a tab is dropped out of it; it
joins a console window's notebook over its console and over its tab strip; and a window opens
over the toolbar and over the server tree. The tab, its label and its session come through each
move unchanged.

Checked by hand on WSLg on 2026-11-06, by Eric. There were two runs of this change, each with
`GCM_TRACE=drag`, Split V and GTK 3.24.41, one at `--scale=2` and one at `--scale=3`.

- 92 drags began, and the compositor cancelled 10 of them before any target answered.
  `notebook_under_pointer` read a place in the main window for each of the 10:
    - 4 were let go over the tab's own notebook, and the tab stayed;
    - 2 were let go over the other pane, and the tab joined it;
    - 4 were let go left of the consoles, over the server pane, and each opened a window. The
      bar readings put the consoles' left edge at x 627 and 758 in the two runs. These 4 were
      let go at x 388 to 471.
- One stuck drag ended at its release (#537).
- 11 tabs were let go on a split's bar. Each was a slow drop that the paned took (#534), and the
  tab stayed where it was. 4 of these tabs came from a console window, so each went back to that
  window. Whether such a tab should join the main window is a separate question, not #538's.
- Neither run logged a traceback or a Gtk-CRITICAL.

Not measured:

- **A cancelled drag that starts in a console window or ends over one, under WSLg.** None of the
  10 did. So the position read against a console window's toplevel under Wayland is the
  source's reading.
- **A flick onto a bar.** All 11 drops on a bar were slow.
- **Whether the 15 drags in #538's report were let go over a tab strip or over a console.** The
  reading against a bar does not say, but the answer does not matter here, as both count.
- **sway.**

### A drag begins once (#401, #406)

Under Wayland, WSLg among it, GtkNotebook began more than one drag for a tab. After
GTK's start_drag, gtk_notebook_motion_notify begins another for each button-1 motion that
reaches the notebook before the compositor's `wl_pointer.leave`. The extra drags did two
things, as both issues' findings measured on WSLg:

- They take the tab label out of the first drag's icon, which left #406's blank icon.
- They replace GTK's dnd_source, so GTK drops the compositor's `cancelled` for the real
  drag. That drag never ends, and its icon surface stays as WSLg's "pointer drag icon"
  window (#401). A successful drop was not affected.

`Wmain.watch_tab_drags` connects two handlers for this, and #537 added a third (below).
`Wmain.on_notebook_motion` returns True, which swallows the event, while `dragged_tab` is set
and button 1 is held. It is not gated on Wayland: under X11, GDK grabs the pointer for a drag
and no motion reached a notebook mid-drag (measured on #406), so it does nothing there. A
reorder within the strip emits no `drag-begin`, so `dragged_tab` is None and its motion passes.

`Wmain.on_notebook_button_press` clears `dragged_tab` on a button-1 press, cancels GTK's drag
too since #533 (below), and always returns False. During a drag no press reaches a notebook,
and the press that starts one comes before `drag-begin`, so a press seen while `dragged_tab` is
set means that drag is over. Without it a drag whose `drag-end` never came would leave the next
drag's first motion swallowed, and no tab could be dragged or reordered until GCM restarted.
Clearing on `drag-failed` was rejected: a failed drag emits `drag-end` anyway, and the stuck
case gets neither. A time window after `drag-begin` was rejected as fragile: bystander motion
came 26 ms in, and the gap reached 29.9 ms.

Measured under X11 (XTest on a private Xvfb, `tests/test_console_window.py`): dragging
tab A onto C's label in a strip of A, B, C leaves the order B, C, A with no `drag-begin`,
also when `dragged_tab` was left set beforehand.

This is a workaround for an upstream fault: [microsoft/wslg#1527](https://github.com/microsoft/wslg/issues/1527)
and [GTK issue 3143](https://gitlab.gnome.org/GNOME/gtk/-/issues/3143).

Not measured: WSLg by hand with this change, and sway, so whether this bug is why the drop
on the bare output above never ended there is not known.

### A drag that never ends is cancelled (#533)

The press check above ended GCM's side of a drag and left GTK's running. Under WSLg one drag
in 30 got no answer (#533's trace: `drag-begin`, then no drop, no `drag-failed` and no
`drag-end`), and its tab bar hid tabs until a console opened in that pane two minutes later.
Read from GTK 3.24.41's source: GtkNotebook moves the dragged tab's label into the drag's icon
when the drag begins, draws no current tab while it is detaching, and puts the label back only
on `drag-end`. A button release that reaches the notebook makes the detach last, and under
Wayland only the compositor ends GTK's drag, so the clicks that followed did not end it.

So `on_notebook_drag_begin` keeps the drag's `Gdk.DragContext` in `dragged_context`, and
`on_notebook_drag_end` drops it. `Wmain.end_stale_drag` clears `dragged_tab`, `pending_join`
and `dragged_context`, and then calls `Gtk.drag_cancel` with that context; a stale button-1
press calls it, and since #537 so does a release (below). The cancel has the
notebook emit `drag-failed` with ERROR and then `drag-end`, and GtkNotebook's own `drag-end`
puts the label back. The state is cleared first because `on_notebook_drag_failed` queues
`move_out_after_drag` under Wayland on an ERROR while `dragged_tab` is set: the other order
would open a console window, unless the pointer was on a split's bar, for a drag that was
never dropped anywhere. Without a context kept, as where a scenario sets `dragged_tab` by
hand, the drag ends on GCM's side alone, as before.

`GCM_TRACE=drag` says which. The `stale drag ended` line ends with `cancelling GTK's drag` or
`GTK's drag not cancelled, no context kept`, and comes before the `drag-failed` and `drag-end`
lines the cancel makes. The `drag-failed` line should say `move out queued False`, and the tabs
line after `drag-end` should say `stray labels: none`.

A button-1 release that reaches a notebook while `dragged_tab` is set also means the
compositor never took the drag (#533's "or sooner"). #537 cancels there too, as the next
subsection sets out; the press stays for a drag whose release reached no notebook.

Measured under X11 (XTest on a private Xvfb, `tests/test_console_window.py`): a real drag of a
tab from its strip into its console, with the button kept down, takes the tab's label out of
the notebook. GDK grabs the pointer for a drag under X11 (measured for motion on #406), so no
press reaches a notebook during one, and the scenario calls `on_notebook_button_press` by
hand, with a real `Gdk.EventButton` of button 1, as Wayland would deliver the next press.
Then `drag-failed` (ERROR) and `drag-end` each came once on the notebook, in that order, both
before the handler returned, so no `drag-end` can come late and clear the state of a drag begun
meanwhile. The label was back in its place, no console window opened, and after the button went up a click
selected another tab and a reorder in the strip worked. With the call to `Gtk.drag_cancel`
removed the label stayed out of the notebook and the scenario failed.

Seen on WSLg afterwards, in #533's hand check, whose trace #537 records (2026-11-06,
`GCM_TRACE=drag`): 49 drags began and 49 ended. The two that got no answer were ended by the
next button-1 press on a tab bar. Each logged `stale drag ended` with `cancelling GTK's drag`,
then `drag-failed` with `move out queued False`, then `drag-end` within 1 ms, and the tabs line
after it said `stray labels: none`. So `Gtk.drag_cancel` ends a drag Wayland manages, which had
been read from the source and measured only for X11's. The tab stayed hidden until that press,
1.1 s in one and 40 s in the other (#537, which the next subsection answers).

Not measured: the cause. One reading fits #533's trace: the button was already up when the
compositor read GTK's start_drag, so it ignored it.

### A release ends a drag that never ends (#537)

The press of #533 ended a stuck drag at the next click on a tab bar, and the tab stayed hidden
until then. During a drag the compositor takes, the pointer belongs to the Wayland data device,
so a button-1 release that reaches a notebook while `dragged_tab` is set should mean the
compositor never took the drag (#533's "or sooner").

Measured on WSLg by hand (WSLg 1.0.73.2, GTK 3.24.41, the Wayland backend, `GCM_TRACE=drag`,
Split V, recorded on #537): 102 drags began and 102 ended, and 11 got no answer. All 11 had a
button-1 release reach a notebook while `dragged_tab` was set, 1 to 32 ms after `drag-begin`:
8 at the notebook the drag began from and 3 at the other pane's, where the trace does not say
whether they came from its tab bar or were passed up from a child. None of the other 91 drags
had one. The release, not the swallowed motion, tells a stuck drag apart: the stuck ones had 0,
1 or 2 button-1 motions swallowed. The next press ended each of the 11, as in #533.

So `Wmain.on_notebook_button_release`, which `watch_tab_drags` connects, ends such a drag as the
button goes up. On button 1 with `dragged_tab` set it calls `end_stale_drag`, the helper the
press calls, so GCM's side is cleared before `Gtk.drag_cancel` and the `drag-failed` it emits
queues no window. It returns False always, so GtkNotebook still sees the release. Any other
button, and a release with no drag on, only trace; a reorder within the strip emits no
`drag-begin`, so its release finds `dragged_tab` None. The press stays as the end for a stuck
drag whose release reaches no notebook, which no measurement has shown: all 11 releases above
reached one.

`GCM_TRACE=drag` writes every release that reaches a notebook, `button-release: button 1 on
notebook 2, drag of alpha on` or `..., no drag on`. One that ended a drag is followed by
`stale drag ended at a release`, ending as the press's line does with `cancelling GTK's drag` or
`GTK's drag not cancelled, no context kept`, and then by the `drag-failed` and `drag-end` lines
the cancel makes. The press's line begins `stale drag ended:`, so the trace says which of them
found the drag.

Measured under X11 (XTest on a private Xvfb, `tests/test_console_window.py`): a real drag held
by XTest takes the tab's label out of its notebook. `on_notebook_button_release` called by hand
with a real `Gdk.EventButton` of type `BUTTON_RELEASE` and button 3 ended nothing. With button 1,
`drag-failed` (ERROR) and `drag-end` each came once, in that order, both before the handler
returned. The label was back in its place, no console window opened, and after the button went
up a click selected another tab and a reorder in the strip worked. With the handler's call to
`end_stale_drag` removed the scenario failed, and so did the release's unit tests. GDK grabs the
pointer for a drag under X11, and no release reached a notebook during one: the two real drags
of the traced scenario wrote no `button-release` line with a drag on, and the scenarios that
drop a tab still pass, which a release that cancelled their drag early would have broken.

Seen on WSLg by hand with this change (2026-11-06, `GCM_TRACE=drag`, recorded on #537): 74 drags
began and 74 ended. 8 got no answer, and each ended at its release, `stale drag ended at a
release` coming 0.8 to 32.8 ms after its `drag-begin` and its `drag-end` by 34.2 ms. No press
had to end one, no tabs line found a stray label, and no tab was seen to disappear. The run's
15 console windows were drags the compositor took and then cancelled, let go before any target
answered, with the pointer in the pane the drag came from: that is #538, not a stuck drag.

Not measured: whether a release reaches a notebook during a drag the compositor took on another
compositor, such as sway: a release that did would cancel a drag in progress.
