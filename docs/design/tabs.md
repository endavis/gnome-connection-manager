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
