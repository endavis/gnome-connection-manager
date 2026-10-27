---
title: "Hosts and folders in GCM"
description: "The server tree: making and moving folders, putting it in the order you want, and what export and import carry; the host dialog, commands on this computer, RDP, VNC, web and command hosts, and a host's files over SFTP and SSHFS"
audience:
  - gcm-users
tags:
  - gcm
  - gcm-guide
  - hosts
  - folders
---

# Hosts and folders in GCM

The panel on the left is the server tree: folders, and the hosts filed under them. This
page covers making folders, moving things between them, putting them in the order you
want, and what a host carries with it when you export or import. Then the hosts
themselves: the host dialog, commands a host runs on this computer before connecting and
after disconnecting, the kinds of host besides a terminal session (RDP and VNC desktops,
web pages, and command lines of your own), and an SSH host's files, opened over SFTP or
mounted with SSHFS and listed in the Mounted tab.

Every host lives in a folder. There is no such thing as a host at the top level — a drop
there is refused — so the first thing a new installation needs is a folder.

## Making, renaming and deleting folders

**New Folder**, **Rename Folder** and **Sort by Name** are in the tree's right-click menu
and under **Servers** in the menu bar. `F2` renames the selected folder.

Deleting is **Remove** in the right-click menu — **Delete Host** in the Servers menu, which
deletes a selected folder just the same — or the `Delete` key.

A new folder is made inside whatever is selected: inside the selected folder, inside the
folder the selected host is in, or at the top level when nothing is selected. Folders
nest as deep as you like.

A name cannot be empty and cannot contain `/`, which is the separator between folders in
a path. Two folders in the same parent cannot share a name. Each of those is refused with
a message rather than silently changed:

| Refused | What GCM says |
|---|---|
| a name containing `/` | A folder name cannot contain / |
| a name already used by a sibling | Host name [x] already exists for group [path] |

(That second message says "Host name" for a folder too — it is shared with the host
dialog.)

**Deleting a folder deletes everything in it** — its subfolders and every host under them,
not just the folder. GCM asks first, and the question says which:

- with hosts inside: *Do you really want to remove all hosts in group [path]?*
- empty: *Delete folder [path]?*

An empty folder is kept. It stays in the tree, and it is still there the next time GCM
starts — folders exist in their own right rather than being implied by the hosts filed
under them, so a folder you have emptied is one you have to delete on purpose.

Which folders are collapsed is remembered between runs, by folder rather than by position
in the tree, so adding or removing rows elsewhere no longer leaves the wrong ones closed.

## Moving hosts and folders

Drag a host or a folder and drop it where you want it. Where it lands depends on which
part of a row you drop it on:

| Dropped on | Where it goes |
|---|---|
| the line between two rows | into that row's folder, next to that row |
| the middle of a folder row | into that folder |
| the middle of a host row | into that host's folder |
| below every row | the top level (folders only) |

Hovering over a collapsed folder opens it, so you can drag into a folder several levels
down in one movement.

Some drops are refused. The line or highlight showing where it would land disappears and
the pointer changes, and letting go does nothing:

- a host onto the top level, since every host lives in a folder
- a host into a folder that already has a host of that name
- a folder into itself or into one of its own subfolders
- anything onto the place it is already in

## Putting the tree in the order you want

A folder you have never arranged sorts by name: subfolders first, then hosts. Drop
something on the line between two rows and that folder keeps the order you gave it, for
those rows and for anything added later.

**Sort by Name** hands one folder back to name order and keeps it there. It applies to the
selected folder only — subfolders keep whatever order they were given, and you can sort
them one at a time.

The order is stored only while it differs from name order, so a tree nobody has arranged
carries no ordering at all in `gcm.conf`.

## What a host carries

Each host has an id of its own, minted when it is saved and kept through renames and
moves. Nothing on screen shows it; it is what lets a host be referred to from elsewhere —
which folder it is filed under, for one — without depending on its name or its path.

A **duplicate** is a second host, so it gets an id of its own rather than sharing one.

No two hosts in one folder share a name. The host dialog refuses a name the folder already
has, and so does a drop. **Duplicate Host** names the copy after its original, *name
(copy)*, and adds another *(copy)* for as long as the folder already has that name.

A `gcm.conf` edited or merged by hand can still hold two hosts of one name in one folder,
and so can a file you import. So can two folders of one name side by side, which GCM merges
into one as it reads the file, with the hosts of both. Then the first of those hosts in
the file keeps the name, and GCM renames each later one: *name (2)*, *name (3)* and so on,
taking a number no host in the folder has. It lists the hosts it renamed, once the window
is up for `gcm.conf` and straight after an import, and saves the new names with your hosts.

A renamed host goes by its new name from then on: wherever `{name}` is filled in for it,
its tabs' names among them, and for the folder it mounts at over SSHFS. Its session logs go in a
folder of the new name, and its earlier logs stay where they were.

## Export and import

**Export Hosts** writes every host and the folder tree to a file, asking for a password
that the stored host passwords are encrypted with. **Import Hosts** asks for the same
password and then **replaces your entire server list** with what the file holds — it is
not a merge, and GCM confirms before doing it.

An exported file carries the ids that were minted on the machine it came from. Importing
it brings them along, and GCM repairs any that collide with each other, so a file merged
by hand from two exports still imports cleanly. A host whose name another host in its
folder has is renamed, as [What a host carries](#what-a-host-carries) says.

## The host dialog

A host's dialog shows only the tabs its connection type uses, so the tabs change as you
choose a type. This is deliberate:

| Tab | Shown for |
|---|---|
| **Properties** | every type |
| **SSH** | SSH: the private key, keep-alive, X11 and agent forwarding, and compression |
| **Port forwarding** | SSH, since tunnelling is an SSH feature |
| **RDP** | an RDP host: how FreeRDP shows the remote desktop |
| **Command line** | a command host |
| **Commands** | every type |
| **Terminal** | a host whose tab is a terminal: **Enable Logging**, **TERM**, the colours, and the Backspace and Delete keys |

A web host has no Terminal tab, since it opens no tab, and neither has a VNC host while
GCM draws its desktop with gtk-vnc. A new host is an SSH host until you choose another
type. On a tab every type is shown, a field the type does not use goes grey instead,
such as a web host's user and password.

What a hidden tab holds stays while you choose another type and back, but for
keep-alive, which another type turns off. Saved, a host keeps its port forwards only as
an SSH host.

Automatic commands on connect are kept separately from the checkbox that runs them, so
unticking **Send commands after login** stops them running without discarding what you
typed. An SSH host's go once its session has started, and what you type into the tab
before then goes after them: see
[A host's commands after login](TERMINAL-USAGE.md#a-hosts-commands-after-login).

`gcm.conf` keeps them as `commands`, each new line written as `\n`, the only form an
older GCM reads. Commands with a backslash and an n of their own, such as
`printf 'a\nb'`, would come back from that with a new line in its place, so GCM writes
those exactly as well, as a JSON string under `commands-json`, and reads that first. Only
while `commands` still says the same, though: edit `commands` by hand and the host sends
what you wrote. An older GCM that saves the file rewrites `commands` and drops
`commands-json`. Commands saved before GCM wrote both cannot say which they held, and are
read as GCM has been sending them, a backslash and an n as a new line.

## A host's own tab name

**Tab name**, on the host dialog's Properties tab below **Name**, is what the host's tabs
are called. Left empty, as it starts, the **Tab name** on the General tab of Preferences
names them, as it names every host's: see
[Naming tabs your own way](TERMINAL-USAGE.md#naming-tabs-your-own-way).

It takes the same values as that: `{name}`, `{address}`, `{port}`, `{user}`, `{group}`,
`{folder}` and `{type}`, so `tpl {name}` names an `ansible` host's tabs `tpl ansible`.
Hover the field for the list. Spaces around what it gives are dropped, and one that gives
nothing, such as `{user}` for a host with no user, counts as empty.

It is used as you wrote it, with no folder in front, even where another host's tab would
read the same. The other host's tab takes its folder instead. Two hosts of one name in two
folders, whose tabs take their folders, lose them once one has a tab name of its own: beside
`tpl ansible`, the other host's tab is `ansible` again.

Saving the dialog renames the host's open tabs, and the window titles, the open-console list
and the cluster window follow. A tab you have renamed keeps its name. Session logs stay where
they were, named by the host's folder and name. **Duplicate Host**'s copy has the same tab
name, and export and import carry it.

A web host opens no tab, so its dialog greys the field and clears it.

In `gcm.conf` it is `tab-name = tpl {name}` in the host's own section, written only when set.
An older GCM, such as 2.1.1, reads the file and names the host's tabs as it always has. When
it saves, it leaves `tab-name` out, so the host has no tab name of its own the next time this
GCM starts.

## Tab colours

A host's tabs can carry a colour, as a stripe across the top of each. With many tabs open
across several projects, a colour can be quicker to read than a name. A host can have a
colour of its own, and a folder can give one to every host in it.

- **A host's own:** tick **Tab color** on the host dialog's Properties tab, below **Tab
  name**, and choose the colour with the button beside it. Unticked, as it starts, the
  host's tabs take their colour from its folder, which the button then shows, greyed.
- **A folder's:** right-click the folder in the tree and choose **Tab Color**, or choose it
  from the **Servers** menu with the folder selected. Pick a colour and **Select** it, or
  choose **No Color** to take the folder's away.

A folder's colour reaches the hosts in its subfolders too. A host's own colour comes first,
then that of the nearest folder above the host that has one, and a host with neither has
none. So a project's folder can colour all its hosts, and one host among them a colour of
its own.

Saving the dialog, or choosing a folder's colour, colours the open tabs at once, and a host
moved to another folder takes that folder's colour. A tab you have renamed keeps its
host's colour. **Duplicate Host**'s copy has the same colour, and export and import carry
a host's colour and a folder's.

The server tree shows the colours too, as a small square before the name. A host's row
shows the colour its tabs take, its own or its folder's. A folder's row shows the colour
it gives the hosts in it, its own or one it takes from a folder above it. A host mounted
with SSHFS has its square first, then the tick. The **Hosts** menu marks each host and
folder in the same way. On the selected row, and on the menu item under the pointer, the
square sits on a small patch of the row's usual background, so that it still shows when
it is the selection's own colour. The tree and the menu follow each change at once.
Rows without a colour have no square, so a tree with no colour set looks as it always
has.

The stripe leaves the tab's other marks as they were: the yellow of a tab ticked in the
[cluster window](TERMINAL-USAGE.md#typing-into-several-consoles-at-once), the orange of
[a tab that needs your attention](TERMINAL-USAGE.md#when-a-tab-needs-your-attention), the
grey of an ended session, and the theme's own mark on the tab in use, along its bottom.
On a tab so marked, the mark starts just below the stripe, so that a yellow stripe still
shows on a tab ticked in the cluster window. A tab without a colour looks as it always
has.

A web host opens no tab, so its dialog greys **Tab color** and unticks it.

In `gcm.conf` it is `tab-color = #e01b24`, in the host's own section or in the folder's
`[folder <id>]` section, written only when set. A value GCM cannot read as a colour, a `#`
and three or six hexadecimal digits, colours nothing, and is kept as it is written. An
older GCM, such as 2.1.1, reads the file and draws no colour. When it saves, it leaves
`tab-color` out of the hosts and the folders, so they have no colour the next time this
GCM starts.

## Commands on this computer

A host can run a command on your computer before connecting, and another after
disconnecting. Both are on the host dialog's **Commands** tab, as **Run on this computer
before connecting** and **Run on this computer after disconnecting**. They are for what a
host needs on this side: a VPN brought up and taken down, a port knocked, a tunnel
opened, a key added to the agent.

- **Before connecting**, the command runs in the host's tab, so its output shows there.
  Connecting waits for it, and goes ahead only when it exits with status 0. With any
  other status the tab ends with that status and nothing connects, and **Close console**
  treats it as a session that failed. `Ctrl+C` in the tab stops it. **Reconnect** and
  **Clone** run it again.
- **After disconnecting**, the command runs once the session ends, however it ends: its
  program exits, you close the tab, or you quit GCM. GCM does not wait for it, and says
  so when it fails. It does not run when nothing connected.
- A **VNC** host runs its command before connecting out of sight, and opens its tab once
  the command succeeds. A **web** host opens its page then. A web host has no session to
  end, so its dialog greys the second field.

Both run through `sh -c`, from your home directory. In either, these are replaced by the
host's own values, each quoted for the shell:

| Placeholder | Value |
|---|---|
| `{name}` | the host's name |
| `{address}` | its address |
| `{port}` | its port |
| `{user}` | its user |
| `{group}` | the folder it is in, as a path, such as `ops/web` |
| `{folder}` | the folder it is in alone, such as `web`, and nothing at the top level |
| `{type}` | its connection type |

Leave the quotes out yourself: `ping -c 1 {address}`, not `ping -c 1 "{address}"`, which
would pass the quotes along too. Anything else in braces is left as it is, so
`awk '{print $1}'` works.

## Remote desktop hosts

A host of type **rdp** opens a remote desktop through FreeRDP, in a window of FreeRDP's
own, or in the host's tab (see [The desktop in its tab](#the-desktop-in-its-tab)). GCM
runs `xfreerdp3`, FreeRDP 3's client, or `xfreerdp` where only FreeRDP 2 is
installed. On Ubuntu they come from the `freerdp3-x11` and `freerdp2-x11` packages. With
neither installed, GCM says so and opens nothing.

The host still opens a tab, which shows what FreeRDP prints: the server's certificate and
a question about it on a first connection (see
[A host's first connection](TERMINAL-USAGE.md#a-hosts-first-connection)), a prompt for
anything the host does not store, and why a connection failed. The tab's session ends
when FreeRDP exits. Closing FreeRDP's window is a clean exit, and a failed connection is
not (see [When a session ends](TERMINAL-USAGE.md#when-a-session-ends)). Closing the tab,
reconnecting it, or quitting GCM asks FreeRDP to end and gives it a moment to, so that
FreeRDP 3 removes the folder it mounts in `/tmp` for files copied through the clipboard.

The port is 3389 unless you change it, and the rest of the host goes to FreeRDP:

- **User**: give a domain account as `DOMAIN\user`. Given a user alone, FreeRDP 3 asks
  for a domain, which GCM answers with none for a host with a stored password.
- **Password**: GCM types a stored password at FreeRDP's prompt and never puts it on
  FreeRDP's command line. Without one, FreeRDP asks in the tab.
- **Extra arguments**: FreeRDP's own options, given last. For example,
  `/drive:shared,/home/you/shared` shares a folder with the remote desktop. They are split
  as a shell splits them, so quote one that holds a space.

The **RDP** tab says how FreeRDP shows the remote desktop. Each setting is an option GCM
gives FreeRDP, before the extra arguments, which can still ask for anything else:

| Setting | Default | FreeRDP option |
|---|---|---|
| **Display**: **In a window**, **In its tab**, **Full screen**, or **Full screen on all monitors** | In a window | none, `/parent-window:` and `/size:`, `/f`, or `/f /multimon` |
| **Resize with the window**: FreeRDP asks the server to resize the remote desktop as you resize its window | on | `/dynamic-resolution` |
| **Size**: a width and height, such as `1920x1080`, or a share of the screen, such as `80%` | empty: FreeRDP's own, 1024x768 | `/size:` |
| **Desktop scale**: the remote desktop's text and icons drawn larger, as a percentage from 100 to 500 | empty: the server's own | `/scale-desktop:` |

- **Size** applies in a window. In its tab, the desktop starts at the tab's size, and full
  screen is as large as the screen, whatever the size says.
- The dialog refuses a size or scale FreeRDP would refuse. Each side of a size runs from
  200 to 32766 pixels, and a share of the screen from 1% to 100%. FreeRDP also refuses a
  share that comes to under 200 pixels on the screen it opens on.
- An RDP host saved before the tab existed resizes with the window, and has every other
  setting at its default.
- FreeRDP refuses to resize with the window and smart sizing together. A host whose extra
  arguments ask for `/smart-sizing` keeps it, and is not resized with the window.
  `-smart-sizing` and `/smart-sizing:off` leave resizing on.
- On a high-DPI screen, a **Desktop scale** such as 200 asks the server to draw the
  remote desktop's text and icons twice as large. Under WSLg, which reports every monitor
  at scale 1, a full-screen session is otherwise the screen's whole resolution at a scale
  of 100%.

An RDP host sends no commands after login, and its dialog greys them. Its tab runs
FreeRDP, which has no shell to run them, and a command typed while FreeRDP asks
something would be taken for the answer, to its certificate question or as the password.

### The desktop in its tab

With **Display** set to **In its tab**, the remote desktop shows in the host's tab, where
it can be split beside other consoles, moved between panes and windows, and chosen from the
open-console list like any tab. FreeRDP draws it into a window GCM makes for the tab.

- **While it connects**, the tab shows FreeRDP's terminal, as it does for a window. The
  certificate question and any prompt are answered there, and nothing is shown over
  them. The desktop takes the terminal's place once FreeRDP shows it. When the session
  ends, the terminal comes back with what FreeRDP printed last, and Reconnect brings the
  desktop back.
- **Its size**: the desktop starts at the tab's size. With **Resize with the window** on,
  FreeRDP asks the server to resize it as the tab changes size, with the window or a
  split. With `/smart-sizing` in the extra arguments, the desktop's image is scaled to
  the tab instead. A server that keeps a size of its own shows as much of the desktop as
  fits, unless smart sizing scales it.
- **The keyboard** goes to the desktop when it would go to a terminal: when its tab is
  opened or chosen, when the desktop is chosen from the open-console list, and when it is
  clicked. The desktop then gets every key, GCM's shortcuts included, as a VNC desktop
  does. Click elsewhere in GCM, in a terminal, the server tree or a tab strip, and the
  keyboard comes back.
- **A click** on the desktop, with any of the three buttons, reaches the remote desktop
  where it was made, and gives the desktop the keyboard, which makes its tab the one in
  use. Scrolling over it leaves the keyboard where it is. A click that moves the keyboard
  waits for GCM to move it, and the pointer waits with it, in every program. So should
  GCM stop responding, such a click holds the pointer still until GCM responds or is
  ended. A click on the desktop once it has the keyboard does not wait for GCM.
- **The pointer** reaches the desktop wherever it is over it, and a key pressed while it
  rests there goes to the desktop too, wherever the keyboard is: X gives a key to the
  window under the pointer.
- **Moving the tab** to another pane, or to a window of its own, keeps the session.
- **Closing the tab** ends FreeRDP.
- **Where it applies**: only where GCM runs on X11, which FreeRDP needs to draw into a
  window of GCM's. Elsewhere the host opens in FreeRDP's own window, and the first line of
  its tab says why. Under WSLg, GTK runs GCM on Wayland whenever `WAYLAND_DISPLAY` is set.
  Starting GCM with `GDK_BACKEND=x11` runs it on WSLg's X server instead, which was not
  tried with a desktop in a tab. With **Windows Remote Desktop** chosen, the host opens in
  Remote Desktop Connection's own window, and its tab says that too.

### Windows Remote Desktop under WSL

Under WSL, GCM can open RDP hosts in Windows' own client, Remote Desktop Connection
(`mstsc.exe`), instead of FreeRDP. Choose **Windows Remote Desktop** for **RDP client**
in Preferences, saved as `rdp-client`, `mstsc` or `freerdp`. Preferences shows the
setting only where WSL's interop finds `mstsc.exe`. Elsewhere RDP hosts open in FreeRDP
whatever it says, and FreeRDP need not be installed for Remote Desktop Connection.

- **User and password**: GCM gives Remote Desktop Connection neither. Windows asks for
  both in its own dialog. **Remember me** saves them in Windows' Credential Manager,
  unless the policy *Do not allow passwords to be saved* is set, which takes it away. The
  managed desktop this was tried on sets it, so whether Windows then uses a saved
  password was not measured. Where Credential Guard runs, as it does there too, Windows
  does not send a remembered RDP password, and a connection that tries fails with *Logon
  attempt failed*.
- **What it takes from the host**: the address and port, **Display**, as `/f` or
  `/f /multimon`, and a **Size** in pixels in a window, as `/w:` and `/h:`. Tried with
  the real one, each did what it says.
- **What it does not**: **Resize with the window**, **Desktop scale** and a size as a
  share of the screen, none of which Remote Desktop Connection has an option for, and the
  extra arguments, which are FreeRDP's. While Windows Remote Desktop is chosen, a host's
  dialog greys out the user, the password, the extra arguments and those two settings,
  and keeps what they hold for FreeRDP.
- **Its window**: Remote Desktop Connection has no setting to resize the remote desktop
  with its window, so the desktop keeps the size it started at. Tried with the real one,
  its window could not be resized by dragging. **Smart sizing**, on its window menu,
  lets the window be resized, and scales the desktop's image to fit instead of changing
  its size. To have the remote desktop follow the window, use FreeRDP, whose **Resize
  with the window** asks the server to.
- **Its size**: a host's **Size** sets the desktop's size each time it opens. Remote
  Desktop Connection saves the size it is given as its own default, in its
  `Default.rdp`, so a host with no **Size** opens at the size the last connection used.
  The clipboard and drives it shares are its own settings, on its Local Resources tab.
- **No `.rdp` file**: GCM starts Remote Desktop Connection with options rather than a
  file. Since Windows' April 2026 security update, a connection opened from an `.rdp`
  file waits on a security dialog every time, with the clipboard, drives and the rest
  off until ticked. A connection started without one is unchanged. Tried with the real
  one, the only dialog before connecting was Windows' warning that it could not verify
  the remote computer's identity, from the server's certificate.
- **The tab** runs Remote Desktop Connection, shows nothing, and ends when it exits.
  Closing the tab leaves Remote Desktop Connection running, so end the session in its
  own window. Remote Desktop Connection exits 0 however the session ends, measured:
  closed, signed out, a password prompt cancelled, or no answer from the host. GCM
  cannot tell a failed connection from one you ended, so **Close console**'s **Only on
  clean exit** closes the tab after either.

## VNC hosts

A host of type **vnc** shows a remote desktop in its tab, drawn by gtk-vnc and scaled to
fit the tab with its shape kept. The port is 5900 unless you change it. A server's display
`:1` is usually port 5901.

- **Password**: a stored password answers the server's request for one. Without one, GCM
  asks when the server does.
- **User**: a server that asks for a user name as well, such as TigerVNC with its
  `TLSPlain` security type, is given the host's user, and GCM asks when the host has none.
- **Extra arguments**: used only by a VNC viewer, below.

A line above the desktop says what the connection is doing, and why it ended, in gtk-vnc's
words: a wrong password, or the server going away. The session ends as a terminal's does
(see [When a session ends](TERMINAL-USAGE.md#when-a-session-ends)). Its end is a clean one
only when GCM closed the connection, as it does when you cancel its question for a
password. A failed login or a server that goes away is not. Closing the tab closes the
connection.

gtk-vnc closes a connection without saying why when it supports none of the security types
the server offers, and the line above the desktop then says that. TigerVNC's `RA2` is one
such type.

While the desktop has the keyboard it gets every key, GCM's shortcuts included, so Ctrl+W
closes a window on the remote desktop and not the tab. Opening the tab puts the keyboard in
the desktop, and so does a click in it. Click the tab's label, or anywhere outside the
desktop, and GCM's shortcuts work again, as they do once the session has ended.

A VNC host sends no commands after login, and its dialog greys them.

Not yet supported: the clipboard, sending Ctrl+Alt+Del, and reconnecting a VNC tab.

### Without gtk-vnc

gtk-vnc's GObject bindings are the `gir1.2-gtk-vnc-2.0` package on Debian and Ubuntu, which
GCM's package recommends. Without them, GCM runs a VNC viewer in a terminal tab, as it runs
FreeRDP for an RDP host. It runs the first of `vncviewer`, `xtigervncviewer` and
`xtightvncviewer` it finds, given the extra arguments and then `host::port`, with an IPv6
address in brackets, as `[fe80::1]::5900`. The viewer asks for the password itself,
TigerVNC's in a window of its own and TightVNC's in the tab, so a stored password is not
used. With neither gtk-vnc nor a viewer, GCM says so and opens nothing.

## Web hosts

A host of type **web** opens a web page in your browser, such as a server's management
console (iLO, iDRAC, IMM) or the admin page of a switch or a NAS. Connecting to it opens
no tab in GCM.

The **Host** field holds the address:

- A full URL, such as `http://switch.example/admin`, is opened as it is, and the port is
  not used.
- A host name or an IP address is opened over `https://`, with the port unless it is 443,
  the default. `bmc.example` with port 8443 opens `https://bmc.example:8443`, and
  anything after a `/` in the address is kept as the path: `bmc.example/console` opens
  `https://bmc.example/console`.

The page asks for a login itself, so a web host has no user or password, and its dialog
clears and greys them, with the extra arguments and the commands after login.

GCM opens the page with `xdg-open`, from the `xdg-utils` package, which hands it to the
browser your desktop names. Without `xdg-open`, GCM says so and opens nothing, and it
shows an error when `xdg-open` reports one.

## Command hosts

A host of type **command** runs a command line of its own in a tab, for a connection GCM
has no type for: `mosh`, `kubectl exec`, `ipmitool … sol activate`, or a cloud provider's
CLI. Write the command on the host dialog's **Command line** tab, which is shown while
the type is chosen. A command host cannot be saved without one.

The line can name the host's values, as the commands on this computer can: `{name}`,
`{address}`, `{port}`, `{user}`, `{group}`, `{folder}` and `{type}`. Each is quoted for the shell, so
write them bare, not inside quotes of your own. Anything else in braces is left as
written.

`{password}` is the host's stored password, and it never goes into a command line, which
any user of the computer can read. GCM writes `"$GCM_PASSWORD"` in its place and gives
the command the password in its environment, as `GCM_PASSWORD`, which only you and root
can read. Only a command whose line names `{password}` gets it. Hand it to a tool through
the environment where the tool allows that, as `ipmitool -E` does below: a tool that
takes a password as an argument shows it in its own command line.

| Connection | Command line |
|---|---|
| mosh | `mosh {user}@{address}` |
| A pod's shell | `kubectl exec -it {name} -- bash` |
| IPMI serial over LAN | `IPMI_PASSWORD={password} ipmitool -I lanplus -H {address} -U {user} -E sol activate` |
| AWS Session Manager | `aws ssm start-session --target {address}` |

The address, user, password and port are the line's to use, and a command host needs
none of them: without an address it still runs its command, where a host of another type
opens a local shell. Its extra arguments are cleared and greyed, since the line is the
whole command.

The command runs through `sh`, from your home folder, with the environment GCM was
started with, so aliases and functions from your own shell's startup files are not
there. The session ends when the command exits, and **Close console** decides what
becomes of the tab. **Reconnect** runs the command again, but GCM never reconnects a
command host by itself, whatever Preferences says about a dropped session: it cannot tell
a lost connection from a command that ended. Commands after login are typed into the tab
3 seconds after the command starts, or 0.7 seconds for a host without an address, since
GCM cannot see when a command's session does.

An older GCM opens a command host as Telnet, as it does any type it does not know, or as
a local shell when it has no address. It keeps the command line when it saves.

## A host's files

Right-click an SSH host in the server tree for two more items, **Open in File Manager**
and **Mount with SSHFS**. Neither needs a console, and neither uses one. Hosts of other
types do not offer them, nor does an SSH host with no address, which opens a local shell.
The **Servers** menu has them too, for the host selected in the tree, with **Unmount
SSHFS** beside them.

**Open in File Manager** opens the host's login folder over SFTP, at an address such as
`sftp://eric@files.example:2222/`: the host's user, address and port, the port left out
when it is 22. A host with no user is opened as you, as its console connects. GCM gives
the address to the application your desktop opens folders with, and where it names none,
to the first of Files (`nautilus`), Nemo, Caja, Thunar, Dolphin, PCManFM-Qt and PCManFM
that is installed. Not to `xdg-open`: no file manager says it opens `sftp:` addresses, and
`xdg-open` then gives them to the web browser. With none installed, GCM says so.

The address is all the file manager is given. The host's stored password and its key
file stay in GCM, and the file manager connects as it would to an address you typed into
it, asking for a password where it needs one.

**Mount with SSHFS** mounts the host's login folder at `~/mnt/<host name>`, with a
character a folder's name should not hold, such as `/` or `:`, as `_`, so that any
program can open the host's files as it opens its own. It needs
`sshfs`, which Ubuntu installs with `sudo apt install sshfs`. GCM says when the mount is
ready, or why it failed, in ssh's words where ssh gave any. While the host is mounted
there, its menu offers **Unmount SSHFS** in Mount's place, and GCM says when the host is
unmounted, or why it could not be. Unmounting removes the host's folder from `~/mnt`
again, as does a mount that fails, so that a folder is not left there for every host
ever mounted. GCM removes only an empty folder: one that held files before the mount
keeps them. `~/mnt` itself stays, and it can be a link to a folder elsewhere. The mount
lasts until you unmount it: closing GCM leaves it mounted. If something else is mounted at
that folder, GCM names it and leaves it alone, and Unmount SSHFS unmounts only the host's
own SSHFS mount.

**What is mounted.** A host mounted with SSHFS has a ✓ before its name, in the server
tree and in the **Hosts** menu, and its tooltip in the tree says where it is mounted.
**Servers ▸ Mounted** lists every SSHFS mount in `~/mnt`, each by its host's name, and
choosing one unmounts it. **Unmount All** below them unmounts them all and says once how
each went. Both follow the system's list of mounts as it changes, so they show a mount
made or ended outside GCM too, such as one unmounted from a terminal. A mount in `~/mnt`
that is no host's, such as one you made yourself, is listed by what it mounts, as
`user@host:`. A host renamed while mounted stays mounted where its old name put it, and
GCM still finds it there, to mark it, list it and unmount it, rather than offer to mount
it a second time. It finds it by the host's user and address, which is all the list of
mounts records, so of two hosts with the same user and address, on different ports, each
is found only where its own name puts it.

**The Mounted tab.** The tree is the server pane's **Servers** tab, and while anything is
mounted with SSHFS in `~/mnt`, a second tab, **Mounted**, sits beside it, with how many
mounts there are, as **Mounted (2)**. When the last mount ends with the Mounted tab
showing, the pane goes back to the tree. The tab lists the mounts as Servers ▸ Mounted
does, and follows them as it does. A mount's tooltip says where it is and what is mounted
there. Double-click a mount to open its folder, or right-click it for:

- **Open Folder**: the mount's folder in `~/mnt`, in the file manager Open in File
  Manager uses, to which it is a folder like any other.
- **Open over SFTP**: the host's address, as Open in File Manager opens it from the tree.
  A mount that is no host's does not offer it, since the list of mounts names no port.
- **Unmount**, and **Unmount All**, as in Servers ▸ Mounted.

The two tabs share the pane's width, and in a narrow pane their names are cut short.

The mount connects with the host's user, address, port and private key file. When ssh
asks for a password, GCM answers with the host's stored one, which never goes into a
command line. It answers nothing else: not a key's passphrase, and not whether to trust a
host key ssh has never seen, so then the mount fails with **Host key verification
failed.** Connect to the host once in a console and answer the question there, and the
mount finds the key. sshfs makes a connection of its own, so the host's port forwarding,
X11 and agent forwarding, compression, keep-alive and extra arguments are not used.

GCM asks sshfs to reconnect when the connection drops, and to stop waiting for a host
that does not answer after 15 seconds. When the reason GCM shows is not enough, ssh's
messages for the last mount of a host are in `sshfs-<host name>.log`, with any spaces in
the name as underscores, in the `gcm` folder under `$XDG_RUNTIME_DIR`, usually
`/run/user/<your uid>`.

## See also

- [Using terminals in GCM](TERMINAL-USAGE.md) — what happens inside a tab: selection,
  copy and paste, logging, the shortcut table, and what GCM does with a `gcm.conf` it
  cannot read
