---
title: "Hosts and folders in GCM"
description: "The server tree: making and moving folders, putting it in the order you want, what export and import carry, and remote desktop hosts"
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
want, what a host carries with it when you export or import, and hosts that open a
remote desktop.

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

## Export and import

**Export Hosts** writes every host and the folder tree to a file, asking for a password
that the stored host passwords are encrypted with. **Import Hosts** asks for the same
password and then **replaces your entire server list** with what the file holds — it is
not a merge, and GCM confirms before doing it.

An exported file carries the ids that were minted on the machine it came from. Importing
it brings them along, and GCM repairs any that collide with each other, so a file merged
by hand from two exports still imports cleanly.

## The host dialog

A host's dialog shows a different number of tabs depending on its connection type, and
this is deliberate. **Port forwarding** is shown for SSH only: tunnelling is an SSH
feature, so a Telnet, RDP, Local, web or VNC host has three tabs where an SSH host has four.
A new host shows the tab until you choose a type.

It is the only control that is hidden rather than disabled. The other SSH-only fields on
the Properties tab — keep-alive, X11 forwarding, agent forwarding, compression, private
key — stay where they are and go grey instead.

Automatic commands on connect are kept separately from the checkbox that runs them, so
unticking **Send commands after login** stops them running without discarding what you
typed.

`gcm.conf` keeps them as `commands`, each new line written as `\n`, the only form an
older GCM reads. Commands with a backslash and an n of their own, such as
`printf 'a\nb'`, would come back from that with a new line in its place, so GCM writes
those exactly as well, as a JSON string under `commands-json`, and reads that first. Only
while `commands` still says the same, though: edit `commands` by hand and the host sends
what you wrote. An older GCM that saves the file rewrites `commands` and drops
`commands-json`. Commands saved before GCM wrote both cannot say which they held, and are
read as GCM has been sending them, a backslash and an n as a new line.

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
| `{group}` | the folder it is in, as a path |
| `{type}` | its connection type |

Leave the quotes out yourself: `ping -c 1 {address}`, not `ping -c 1 "{address}"`, which
would pass the quotes along too. Anything else in braces is left as it is, so
`awk '{print $1}'` works.

## Remote desktop hosts

A host of type **rdp** opens a remote desktop through FreeRDP, in a window of FreeRDP's
own. GCM runs `xfreerdp3`, FreeRDP 3's client, or `xfreerdp` where only FreeRDP 2 is
installed. On Ubuntu they come from the `freerdp3-x11` and `freerdp2-x11` packages. With
neither installed, GCM says so and opens nothing.

The host still opens a tab, which shows what FreeRDP prints: the server's certificate and
a question about it on a first connection (see
[A host's first connection](TERMINAL-USAGE.md#a-hosts-first-connection)), a prompt for
anything the host does not store, and why a connection failed. The tab's session ends
when FreeRDP exits. Closing FreeRDP's window is a clean exit, and a failed connection is
not (see [When a session ends](TERMINAL-USAGE.md#when-a-session-ends)).

The port is 3389 unless you change it, and the rest of the host goes to FreeRDP:

- **User**: give a domain account as `DOMAIN\user`. Given a user alone, FreeRDP 3 asks
  for a domain, which GCM answers with none for a host with a stored password.
- **Password**: GCM types a stored password at FreeRDP's prompt and never puts it on
  FreeRDP's command line. Without one, FreeRDP asks in the tab.
- **Extra arguments**: FreeRDP's own options, after the host, port and user. For example,
  `/size:1920x1080` sets the size of the desktop, and `/dynamic-resolution` resizes it
  with FreeRDP's window. They are split as a shell splits them, so quote one that holds a
  space.

An RDP host sends no commands after login, and its dialog greys them. Its tab runs
FreeRDP, which has no shell to run them, and a command typed while FreeRDP asks
something would be taken for the answer, to its certificate question or as the password.

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

## See also

- [Using terminals in GCM](TERMINAL-USAGE.md) — what happens inside a tab: selection,
  copy and paste, logging, the shortcut table, and what GCM does with a `gcm.conf` it
  cannot read
