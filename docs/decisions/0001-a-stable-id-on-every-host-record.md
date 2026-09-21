# ADR-0001: A stable id on every host record

## Status

Accepted

## Decision

Every `Host` record carries an `id`: eight random hex characters from
`secrets.token_hex(4)`, persisted as an `id` key in the host's `gcm.conf` section,
assigned on load when absent and stable for the life of the entry.

The field lands on its own, ahead of any code that reads it.

## Rationale

A host's identity is currently computed from fields that change, which puts a ceiling on
what can be built around it. The rest of this section is why a field is the answer, why the
value is random, and why it lands before anything reads it.

### Identity is currently derived, and the things it derives from all change

A host is addressed today by the `(group, name)` pair. `open_cli_targets` matches command
line targets on it (`app.py:1606-1612`). The edit dialog finds the entry it is replacing
with `h.name == self.oldName` inside `groups[self.oldGroup]` (`app.py:4861-4884`). Delete
removes by object identity from `groups[host.group]` (`app.py:4287`); `Host` defines no
`__eq__`, only `__init__` and `__repr__`, so that is a pointer comparison and works only
because the list holds the same object the tree row does.

The file offers nothing more stable. Host sections are named `host <N>`, renumbered from 1
in iteration order on every `writeConfig` (`app.py:3384-3390`), so a host moves to a
different section whenever anything ahead of it in the iteration changes.

So identity is a function of two mutable fields plus an unstable file position. Nothing
outside the record can hold a reference to a host and still be right after a rename, a
move, or an unrelated edit.

### The features that want one

None of these exist yet; each would otherwise have to invent its own key, and each
invented key inherits the same fragility:

- reopening the tabs that were open at shutdown
- per-host state that does not belong in `gcm.conf` — last connected, connection counts
- binding a host to a shortcut, a favourites list, or a startup set
- ADR-0002, where a host's parent folder stops being a name and becomes a reference

### Random, not sequential

An incrementing counter is the obvious choice and it is wrong here, because GCM imports.
`on_importar_servidores1_activate` reads a whole exported config and replaces the host list
(`app.py:4075-4100`), and export writes its own `host <i>` sections from 1
(`app.py:4118-4127`). Any counter-derived id in an exported file collides with the ids
already in the importing config. Merging two configs is then a renumbering exercise, which
is exactly the property the id was supposed to remove. Eight random hex characters do not
collide in practice at this scale, and a load-time uniqueness pass catches the case where
they do — or where someone hand-edits the file.

### Assigned on read, so there is no migration

A config with no `id` keys gets them the first time it is loaded and keeps them at the next
write. No version bump, no migration step, no separate code path to maintain. `conf.VERSION`
already exists to gate the legacy password formats and is not extended here.

### Landing it alone, ahead of any consumer

An id that arrives with its first consumer arrives in the same release as that consumer,
which means the consumer has to handle records that do not have one yet. An id that lands
alone has been in every user's config for however long it takes the first consumer to be
written, and the consumer can assume it. The cost of landing it alone is one field nothing
reads for a while, which is close to free; the cost of landing it late is a nullable field
and a fallback path in every consumer.

`utils/hosts.py` is already pure and directly tested, so the read and write sides and the
uniqueness pass are testable without the `gi` stub in `tests/conftest.py`.

### Rejected

**Use the section name as the id.** It is already in the file and needs no new field. But it
is renumbered on every write (`app.py:3384-3390`), so it identifies a position, not a host.

**Give hosts a UUID.** A full `uuid4()` is 32 hex characters in a file a person edits by
hand. Eight is enough to be unique across a config holding tens to hundreds of entries.

**Make `(group, name)` immutable instead.** Renaming a host is a feature users have, and
ADR-0002 exists specifically to make moving between folders easy. Freezing either to buy
identity trades away the thing being built.

## Related Issues

- Issue #153: Add a stable id to every host record
- Issue #155: Record the host-id and folder-tree decisions as ADRs

## Related Documentation

- [ADR-0002: Folders are records, not a path string](0002-folders-are-records-not-a-path-string.md)
- [AGENTS.md](../../AGENTS.md) — `utils/hosts.py`, configuration and data flow
