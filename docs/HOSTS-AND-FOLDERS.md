# Hosts and folders in GCM

The panel on the left is the server tree: folders, and the hosts filed under them. This
page covers making folders, moving things between them, putting them in the order you
want, and what a host carries with it when you export or import.

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
feature, so a Telnet or Local host has three tabs where an SSH host has four. A new host
shows the tab until you choose a type.

It is the only control that is hidden rather than disabled. The other SSH-only fields on
the Properties tab — keep-alive, X11 forwarding, agent forwarding, compression, private
key — stay where they are and go grey instead.

Automatic commands on connect are kept separately from the checkbox that runs them, so
unticking **Send commands after login** stops them running without discarding what you
typed.

## See also

- [Using terminals in GCM](TERMINAL-USAGE.md) — what happens inside a tab: selection,
  copy and paste, logging, the shortcut table, and what GCM does with a `gcm.conf` it
  cannot read
