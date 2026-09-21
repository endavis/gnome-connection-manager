# ADR-0002: Folders are records, not a path string

## Status

Accepted

## Decision

Folders become records. `gcm.conf` gains `[folder <id>]` sections carrying `name`,
`parent` (a folder id, empty at root) and `position`; each host gains a `folder` key
naming its parent. Folder ids are generated the same way as host ids in ADR-0001.

`host.group` is not removed. It stays in the file and stays correct, recomputed from the
folder tree after any structural change — demoted from source of truth to derived cache.

The tree itself, its repair pass and its migration live in a new pure module,
`src/gnome_connection_manager/utils/folders.py`.

## Rationale

The current design has no record of a folder anywhere, which makes two ordinary
operations — renaming a folder, and dragging a host into another one — into rewrites
across every affected host. This section covers why an adjacency list is the right shape,
why the old path string survives anyway, and what was rejected.

### What exists today

`groups` is a `dict[str, list[Host]]` keyed by a `/`-joined path, rebuilt from `host.group`
at load (`app.py:3194-3207`). `updateTree` synthesizes the folder rows by splitting that
path on `/` (`app.py:3245-3273`), and deletes any group whose list has emptied
(`app.py:3233-3235`). `get_group` reconstructs the path string back out of the widget tree
by walking parent iters (`app.py:4246-4254`).

A folder therefore exists if and only if some host names it. It has no name of its own, no
position, and no lifetime independent of its contents.

The consequences are all visible from the outside:

- Renaming a folder means rewriting `group` on every descendant host. No code does this;
  the original author left it as a TODO at `app.py:33` — "permitir cambiar nombre de grupo".
- Hosts cannot be dragged between folders. Also a TODO, `app.py:16` — "drag'n drop hosts
  entre grupos". The tree registers no drag targets at all; the only `drag_dest_set` in the
  file is on the VTE widgets (`app.py:2979`).
- An empty folder cannot exist, so a folder cannot be created before it has contents, and
  dragging the last host out of one destroys it.
- A folder name cannot contain `/`, because the separator is structural.
- There is no user ordering: groups are reverse-sorted then prepended, hosts sorted by name
  (`app.py:3245`, `app.py:3271`).

### Why an adjacency list

A folder needs identity for the same reason a host does (ADR-0001): something refers to it.
With `parent` holding an id rather than a name, a rename touches one record and a move
touches one record, regardless of how much sits underneath. Folders gain an independent
lifetime, so an empty one is representable. Names become free text, `/` included. And
`position` gives the tree a user-defined order, which the current alphabetical sort cannot
express at all.

The cost is referential integrity, which becomes ours to maintain: a parent id that names
nothing, a duplicate id, and a cycle from dragging a folder into its own descendant. That is
a load-time repair pass — unknown parent reparents to root, cycle breaks at root, duplicate
id is reassigned — plus an `is_ancestor` check at drop time. Both are pure functions over a
dict, and both belong in `utils/folders.py` where they can be tested without the `gi` stub
in `tests/conftest.py`.

### Keeping `host.group` as a derived cache

This is the decision that makes the change affordable, and it is the one most likely to look
redundant later, so: the path string has five consumers, none of which is about the tree
widget.

- the session log layout, `<log_dir>/<group>/<name>/<user>-<date>-<nnn>.log` (`app.py:2830`)
- command line targets of the form `group/name` (`app.py:1606-1612`)
- connect-every-host-below-here, which finds the subtree with
  `g == group or g.startswith(group + "/")` (`app.py:4216-4223`)
- export, which iterates `groups` and writes each host's `group` key (`app.py:4118-4127`)
- the `cmbGroup` free-text combo in the host dialog (`app.py:4592-4594`)

If `folder` replaced `group`, all five change in the same commit as the tree rewrite. If
`group` survives as a derived field, none of them do, and each can be migrated later on its
own schedule or never. Recomputing it is one pass over the host list on an explicit user
action, against a config holding tens to hundreds of entries.

It also buys file compatibility in both directions. `load_host_from_ini` reads `group` with
a bare `cp.get` (`utils/hosts.py:122`), so a host section without that key raises and the
entry is dropped with an error (`app.py:3208-3209`). Writing `group` means an older GCM
build, and an older build importing a newly exported file, both still work.

### Migration by synthesis

With no `[folder]` sections present, the tree is synthesized from the `host.group` strings
already in the file — the same split on `/` that `updateTree` does today, done once into
records. No version bump and no separate migration path, and the same code imports an old
export file, which `on_importar_servidores1_activate` will otherwise hand us
(`app.py:4081-4092`).

### Two things this exposes

`conf.COLLAPSED_FOLDERS` stores GTK positional paths like `0:2:1`, from
`get_string_from_iter` (`app.py:3211-3213`), and restores them by
`Gtk.TreePath.new_from_string` (`app.py:3222-3225`). A positional path already points at a
different row whenever the tree changes shape; under user-defined ordering it would be
wrong routinely. It should be keyed by folder id.

The servers menu is built in the same loop as the tree and matches folders by label text
(`get_folder_menu`, `app.py:3323-3331`). It follows the same resolver.

### Drag-and-drop specifics

`Gtk.TreeView.set_reorderable(True)` is not used. It performs the move itself and offers no
veto, and a veto is exactly what is needed to refuse a folder dropped into its own
descendant. The implementation is `drag_dest_set` plus a `drag-motion` handler that returns
false on an invalid target, and a `drag-data-received` handler that writes the model change
and calls `updateTree`.

### Phasing

Each phase lands on its own:

1. `utils/folders.py` and migration — no behavior change
2. hosts bind to a folder id, `host.group` becomes derived — no behavior change
3. folder create, rename and delete; drag-and-drop
4. user-defined ordering

Phases 1 and 2 are testable end to end with no GTK, and the application behaves identically
after both.

### Rejected

**Keep the path string; add a rename command.** Rename becomes a rewrite of `group` on every
host matching the prefix, and a drag becomes the same rewrite. Roughly a hundred lines, no
migration, no format change — by far the cheapest option. Rejected because it fixes only the
symptom that prompted the discussion: a folder still cannot be empty, so it still cannot be
created before it has contents and still evaporates when the last host leaves; a name still
cannot contain `/`; and the tree is still alphabetical. It is a patch, not a folder
structure.

**Materialized path of ids** — the host stores `f9c2/f3a1` instead of a single parent.
Renames stay O(1) because the segments are ids rather than names, but a move goes back to
being O(descendants), and the integrity problems do not go away. Same work, worse
properties.

**A nested document — JSON, replacing the flat INI for hosts.** Genuinely the more robust
shape in one specific respect: a cycle becomes unrepresentable rather than something a
repair pass has to detect, and ordering is just list order. Rejected on blast radius. It
discards the documented `gcm.conf` format, the export and import paths, and the structural
tests around `writeConfig`, in exchange for eliminating one thirty-line validation function.

**Closure table or nested sets.** The usual answers when subtree queries must be fast. This
tree holds tens to hundreds of rows and is walked in full on every `updateTree` anyway.

## Related Issues

- Issue #154: Replace the group path string with a real folder tree
- Issue #153: Add a stable id to every host record
- Issue #155: Record the host-id and folder-tree decisions as ADRs

## Related Documentation

- [ADR-0001: A stable id on every host record](0001-a-stable-id-on-every-host-record.md)
- [AGENTS.md](../../AGENTS.md) — repository map, configuration and data flow
- [docs/SPEC.md](../SPEC.md) — feature specification
