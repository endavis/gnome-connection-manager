---
title: "Connection Types"
description: "How GCM opens each kind of host, and why: the registry of connection types, a type's own settings, command hosts, RDP through FreeRDP or Windows Remote Desktop, and web and VNC hosts"
audience:
  - contributors
tags:
  - gcm
  - gcm-dev
  - design
---

# Connection Types

Design notes for `src/gnome_connection_manager/utils/connections.py`, the module, and for the
code in `src/gnome_connection_manager/app.py` that opens each kind of host: why each choice
was made, what was measured and with which versions, and what was rejected. They were moved
here from `AGENTS.md` (#430). Read the section for a type before changing it.

## The registry

The connection types (#228) are a class
per kind of host, `Ssh`, `Telnet`, `Rdp`, `Local`, `Web`, `Vnc` and `CustomCommand`, listed in `CONNECTION_TYPES` in the
order the host dialog offers them, which fills its list from there. Code that used to
compare `host.type` with a name asks the type instead: `addTab` for the `Command` to
spawn, and the dialog and `host_sends_commands` for `default_port`, `remote`,
`ssh_options` and `sends_commands`, the server tree's menu for `sftp`, whether a
host's files open over SFTP (#267), and `start_session` for `session_program`, whose
session's start the commands after login wait for (#312). A new type adds a class to the module, not a branch in each
of those. `named` finds a type by name, and gives Telnet for a name GCM does not know;
`for_host` is what `addTab` opens a host as, a local shell for a host with no address
unless its type has `runs_without_address`, since the Local button's host is of type
ssh. Both keep what `addTab`
did before the registry, checked by recording its command for a matrix of hosts before
and after. Pure: what a command needs from outside comes in as `Programs`, which
`connection_programs` in `app.py` builds at each spawn, so a test that swaps
`SSH_COMMAND` for a copy of the script is heard. A type's message, such as the one its
`missing` gives for RDP, is marked with `N_` and translated in `app.py`, and
`tests/test_i18n.py` reads the module for it, one literal per message: its pattern
does not follow a message split across literals.

## Pages that are not terminals

A type whose tab is not a terminal has its page in `TYPE_PAGES` in `app.py`, by the
type's id, since a page is made of widgets. `addTab` opens one with `open_type_page`
before it asks the type for `missing`, and builds no terminal for it: VTE 0.76 reports
GLib criticals as a terminal that never joined a window is dropped, which every web
host did until `addTab` made its terminal last. The registry scenarios fail on a GLib
critical since, and not on a warning: on CI, GTK warns that it has no accessibility
bus and no icon theme.

## A type's own settings

A type's own settings are the `Setting`s in its `settings`, each a flag, a choice or
text. A choice has `choices`, each a value and its label, drawn as a combo box, and a
value it does not offer reads as its default (#278). The
host dialog draws them on a page titled `settings_title`, which
`Whost.build_type_pages` places after Port forwarding and `on_cmbType_changed` shows
only while that type is chosen. A host keeps them in `Host.type_settings`, by the name
each is saved under in its section, `<type>.<key>`, and only while one differs from
its default. `HostUtils` reads every option with a dot as one, those of a type GCM
does not know included, so clone and export and import carry them, and a new type adds
no attribute to `Host`. A key is lower case: configparser folds an option's name as it
writes it, and a key in mixed case would not be found once GCM restarted, so `Setting`
refuses one. `settings_hint` is a line of help under the settings, and `invalid` lets
a type refuse them on OK. The page packs its rows at the top at their own height:
measured in a screenshot, a grid given the whole page shared its height out among the
rows, and the one entry of the first type with settings drew half a page tall.

## Command hosts

That first type with settings is `CustomCommand` (#248), a command host, whose `command.line` runs through
`sh -c` in a terminal tab, with the host's values quoted as `local_command` quotes them.
It sets `runs_without_address`, so the dialog does not ask for one. Its `{password}`
reaches the command in `Command.environment`, which `vte_run` hands VTE as `envv`:
measured, VTE adds it to what the child inherits, directly and under the relay, and it
never enters GCM's own environment, as TERM does. So `terminal.command` is
`(program, argv, environment)`, which `start_session` and the Reconnect key in
`on_terminal_keypress` read, and a stored password reaches `data/scripts/ssh.expect`
the same way (#314). Nothing is typed at a command host's prompts.
`tests/test_connections.py` gives a type of its own settings, as
`tests/test_tab_pages.py` opens a page of its own.

## RDP: FreeRDP's settings

RDP's settings (#278) are how FreeRDP shows the desktop: Display, Resize with the
window, on by default, Size and Desktop scale. `rdp_arguments` gives FreeRDP an option
for each, `/f`, `/f /multimon`, `/dynamic-resolution`, `/size:` in a window only and
`/scale-desktop:`, before the extra arguments. `rdp_size` and `rdp_scale` hold a value
to what FreeRDP 3.32.1 takes, measured at each edge: a side from 200 to 32766, a share
from 1% to 100%, a scale from 100 to 500. FreeRDP refuses `/dynamic-resolution`
beside smart sizing, exit 22, so `asks_for_smart_sizing` leaves it out for extra
arguments that ask for that. These were measured against `freerdp-shadow-cli3`,
unpacked from Ubuntu's packages and serving one Xvfb to a client on another. Its
desktop keeps its own size, so neither a resize nor the scale could be seen to take.
Under `/sec:rdp` the client's MCS Connect Initial is not encrypted, and decoded
through a relay it carried `/scale-desktop:`'s value in its core data as given.
FreeRDP's own log line for its monitor swaps the desktop and device scales. So does
the monitor `freerdp_settings_enforce_monitor_exists` builds, which reaches a server
only in a session with more than one monitor. Its log also names blocks 0xC006 and
0xC00A `CS_MONITOR` and `CS_MONITOR_EX`, which they are not.

## RDP: Windows Remote Desktop

Under WSL, Preferences' RDP client can choose Windows Remote Desktop, `mstsc.exe`,
which WSL's interop runs (#283). `Programs` carries the choice as `rdp_client` to
`Rdp.missing` and `Rdp.command`, which falls back to FreeRDP where `windows_rdp` finds
no `mstsc.exe`, and Preferences draws the setting only where it does. `mstsc_arguments`
gives `/v:` and an option for Display and a size in pixels, and never the user, the
password or the extra arguments: Windows asks for the password itself, as #283 decided
rather than a file holding it. Options rather than an `.rdp` file, since Windows' April 2026
security update shows a dialog before every connection opened from a file, with each
redirection off until ticked. The real `mstsc.exe` opens its windows on the Windows
desktop, so no test may reach it: `tests/test_windows_rdp.py` runs its scenarios with a
fake first on a PATH without the folders WSL adds under `/mnt`.

What the program a host opens in leaves unused is its type's `ignores`, given the
`Programs`. `on_cmbType_changed` greys it and keeps what it holds, where it clears
what a type never uses: Windows Remote Desktop ignores an RDP host's user, password,
extra arguments, Resize and Desktop scale (#285). OK checks a setting so greyed at its
default, or a value a hand edit left would refuse it with no way to correct it.

Measured with the real mstsc on a managed desktop (#283): a certificate warning before
connecting, not a file's dialog; a window that could not be resized by dragging, which
Smart sizing allows, scaling the image; Remember me gone, under the policy *Do not
allow passwords to be saved*, `DisablePasswordSaving`; and closing the tab left mstsc
running. mstsc has no dynamic resolution (#287): of 19 `.rdp` setting names, its
binary holds 16, not `dynamic resolution`, nor the two Microsoft lists as Windows
App's alone. A size given applies each time, and mstsc saves the `/w:` and `/h:` into
its `Default.rdp`, which a connection with no size then opens at. It exits 0 however a
session ends, a failed connection included, so `Rdp.dropped` and `Rdp.refused` never
apply to it.

## RDP: the desktop in its tab

An RDP host whose Display is In its tab, `tab`, shows the desktop in its tab (#227),
through FreeRDP's `/parent-window:`, which needs X11. `Rdp.in_tab` says the host asks
for it and FreeRDP is the client, `can_show_desktops` in `app.py` that GCM runs on X11,
and `Rdp.window_instead` why a host asking opens in a window, which its tab prints
first. `rdp_display` reads In its tab as In a window, Size and all, without a
`TabWindow`, the window and the tab's size `Programs.tab_window` carries. The tab is
`addTab`'s terminal page with an `RdpDesktop` packed after the terminal, so
`page_terminal` still finds it. The desktop is hidden while FreeRDP connects and asks
in the terminal, and takes its place once FreeRDP's window appears in `holder`, a
window of GCM's own, which each realize puts into the widget's window and each
unrealize back at the root. Moving a tab remakes the widget's window, measured, and
FreeRDP 3 then kept running with nothing to draw in, where FreeRDP 2 ended.
`spawn_command` builds the command again at each spawn, Reconnect's included, for the
tab's size then, and `keyboard_of` gives the keyboard to the desktop shown, never the
terminal hidden behind it, whose keys would reach FreeRDP's terminal. FreeRDP never
follows its parent's size, so each allocation resizes its window. For
`DESKTOP_SETTLE` seconds after the window appears, GCM resizes it again whenever it
differs: FreeRDP makes it the session's size as it finishes connecting, which a server
of a fixed size makes other than the tab's, measured. The X calls are `X11`'s, libX11
through ctypes on GDK's own connection, which PyGObject gives as a pointer whose
`hash()` is its address, measured, so they run in order with GDK's. Each is inside
GDK's error trap: measured, an X error GDK did not trap there ended GTK with status 1.
GTK's focus on the desktop gives FreeRDP's window X's. Focus leaving it within GCM
gives X's back to the toplevel, which `has_toplevel_focus` tells, not `is_active`:
GTK changes that only after the desktop's focus-out, measured, and GCM took the
keyboard back from another window. X still gives a key to the window under the
pointer, so a key typed with the pointer on the desktop goes to it, whatever has the
keyboard. A click on the desktop gives it GTK's focus through `ClickToFocus` (#373),
since FreeRDP's window takes the press and GTK never sees it. GCM holds buttons 1 to 3
on `holder` with a passive grab, the pointer synchronous, as Mutter 46.2's click to
focus holds a window, read in its source. X hands GCM the press and holds the pointer
until GCM replays it with `ReplayPointer`, after which FreeRDP gets it where it was
made, and a drag whole, measured. So every press is replayed, whatever came of taking
the keyboard. The grab is made on a connection of GCM's own, read from a GLib watch.
Measured with the grab on GDK's own connection, GDK made no event of the press, and
the pointer stayed frozen while GCM's main loop ran. PyGObject has no
`Gdk.Window.add_filter` to see it by, measured. The grab is let go while the desktop
has the keyboard, as Mutter lets go a focused window's, so such a click needs nothing
of GCM. Against the shadow server, FreeRDP 3.32.1 put a press from the server tree
where the pointer had begun, on `main` too and with no grab, while FreeRDP 2.11.5 put
each press and drag where it was made.

`tests/test_rdp_tab.py` runs real GCM on an Xvfb of its own, with a fake
FreeRDP that draws a real X window and logs what reaches it. FreeRDP 3.32.1 and 2.11.5
were measured, unpacked from Ubuntu's packages, against FreeRDP's shadow server and
Weston's RDP backend, and the measurements are on #227. Neither server applies a
resize once connected, so that the remote desktop follows the tab under Resize with
the window is not measured. A click made in the same instant as a move landed where
the pointer had been, as FreeRDP sent the press first and the shadow server presses
wherever its pointer is, so a test lets the pointer settle before it clicks.

## RDP: ending FreeRDP

FreeRDP 3 ended by SIGHUP, as a closed tab's was, leaves its clipboard's FUSE mount at
`/tmp/com.freerdp.client.cliprdr.<pid>`, measured, where SIGTERM and SIGINT unmount it
(#371). So the type's `asked_to_end` names FreeRDP's clients, and `end_programs` in
`app.py` sends SIGTERM to each one `afterlogin.find_program` finds among a tab's
processes, then waits up to `END_WAIT` for `afterlogin.ended`, before anything hangs
up on it. It runs from a terminal page's `destroy`, whose handlers run before the page
destroys the terminal and VTE hangs up its child. It runs from `end_sessions` at
Ctrl+Q, which destroys no tab, and from `vte_run`, before a spawn such as Reconnect's
replaces a session. GCM waits because, measured, a hangup straight after SIGTERM left
FreeRDP 3's mount, or its folder. Given the time, FreeRDP 3 unmounted within 20 ms and
exited 145 within 38 ms. FreeRDP 2.11.5 mounts nothing. `on_terminal_child_exited`
clears `child_pid`, as a reaped pid can be another process's. The fake that stands for
this in `tests/test_rdp.py` runs as `xfreerdp3` itself, with Python in its `#!` line:
one a shell script runs is named `python` in /proc, and is not found.

## Web hosts

A web host (#231) opens no tab: its type's `opens_tab` is False, and `addTab` hands
its `url` to `open_in_browser` in `app.py` and returns. `credentials` and `arguments`
say whether a remote host's user and password, and its extra arguments, apply; the
dialog clears and greys them for a web host, as it does all of them for a local one.
`open_in_browser` runs `xdg-open`, not `Gtk.show_uri`: GIO finds a browser only
through a MIME cache or a default in `mimeapps.list`, and WSLg had neither. Measured
there, GIO raised `Operation not supported` where `xdg-open` found the browser from
its desktop file. A link Ctrl+clicked in a terminal goes through it too (#232), and it
gives `xdg-open` the scheme in lower case: `xdg-open` looks a handler up by the scheme
as written, and sent `HTTPS:` and `MAILTO:` to `BROWSER`. It is not waited for, since `xdg-open` with no desktop session runs
the browser itself and returns only when it closes, and a child watch reports a
failure once it exits. Its tests give `xdg-open` a browser of their own, through a
desktop file and through `BROWSER` both: with neither, `xdg-open` falls back to
`x-www-browser`, which started a real browser when this was measured.

## VNC hosts

A VNC host (#234) is drawn in its tab by `VncPage` in `app.py`, with gtk-vnc, whose
bindings are optional: `TYPE_PAGES` holds it only where `GtkVnc` imports, and without
it a VNC host runs a viewer in a terminal tab from its type's `command`, the first of
`VNC_VIEWERS` found. Measured with gtk-vnc 1.3.1 against Xtigervnc 1.13.1, and each a
scenario in `tests/test_vnc.py`: the credentials asked for come as a
`GObject.ValueArray`, which PyGObject does not iterate, so `get_nth` over `n_values`;
a server with no security type gtk-vnc supports is dropped without an error, so an end
is clean only when GCM closed the connection; the error for a server going away is
"Server closed the connection" or "Failed to flush data", by what gtk-vnc was doing;
and destroying the page closes the connection with no signal. GCM's shortcuts are
accelerators, which run before the focused widget sees a key, and measured with real
input they took Ctrl+W, closing the tab, and Ctrl+F from the desktop, which were Close
console's and Find's keys then; they are Ctrl+Shift+W and Ctrl+Shift+L now (#419). So
`Wmain.on_window_key_press` gives a desktop with the keyboard every key first;
gtk-vnc leaves them once disconnected, and the shortcuts apply again.

`tests/test_vnc.py` starts Xtigervnc on a display number it picks and retries, since
`-displayfd` finds none under WSLg, whose `/tmp/.X11-unix` is not writable. What it
starts dies with the scenario: a leftover held the scenario's output open, and the
test waited out its timeout. It starts `GcmApplication` as GCM does, `register` then
`activate`: a bare `Wmain` has no accelerators, and a key test there passes with or
without the fix.
