"""Folders as records: the tree the host list is filed under.

A folder used to exist only as a segment of some host's ``group`` path -- no name of its
own, no identity, gone the moment its last host left. ADR-0002 makes folders records
instead: ``[folder <id>]`` sections in gcm.conf carrying a ``name`` and a ``parent``, with
each host naming its folder by id.

``host.group`` survives, deliberately, as a cache derived from the tree. Five things read
that path string -- the session log layout, command line targets, connect-whole-subtree,
export, and the host dialog's group combo -- and keeping it written and true means none of
them change, and an older GCM can still read the file. The cache is only faithful while
``path_for`` gives every folder a different path: two folders sharing one would be merged
by anything keyed on the string. Hence the two naming rules the repair pass enforces --
no ``/`` inside a name, and no two siblings with the same one.

Pure: no GTK and no configuration globals, so it is tested directly rather than through
the ``gi`` stub in tests/conftest.py.
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import configparser
    from collections.abc import Collection, Iterable

    from gnome_connection_manager.utils.hosts import Host

ROOT = ""
SEPARATOR = "/"
SECTION_PREFIX = "folder "
FOLDER_ID_BYTES = 4


def new_folder_id(taken: Collection[str] = ()) -> str:
    """Mint a folder id: random hex, for the reason host ids are random (ADR-0001)."""
    while True:
        folder_id = secrets.token_hex(FOLDER_ID_BYTES)
        if folder_id not in taken:
            return folder_id


class Folder:
    def __init__(self, folder_id: str, name: str, parent: str = ROOT) -> None:
        self.id = folder_id
        self.name = name
        self.parent = parent

    def __repr__(self) -> str:
        return f"Folder({self.id!r}, {self.name!r}, parent={self.parent!r})"


class FolderTree:
    """Every folder, keyed by id. A parent of `ROOT` means top level."""

    def __init__(self) -> None:
        self.folders: dict[str, Folder] = {}

    def child_named(self, parent: str, name: str) -> Folder | None:
        for folder in self.folders.values():
            if folder.parent == parent and folder.name == name:
                return folder
        return None

    def path_for(self, folder_id: str) -> str:
        """The `/`-joined names from the top down: what `host.group` holds."""
        names = []
        seen = set()
        # `seen` only matters for a tree that skipped repair(); a cycle must not hang.
        while folder_id in self.folders and folder_id not in seen:
            seen.add(folder_id)
            folder = self.folders[folder_id]
            names.append(folder.name)
            folder_id = folder.parent
        return SEPARATOR.join(reversed(names))

    def ensure_path(self, path: str) -> str:
        """The folder at `path`, creating any part of it that is missing.

        Each segment is stripped: configparser strips every value it reads back, so a
        name kept with its spaces would change on the first reload. Log paths already
        strip segments (`sanitize_log_segments`), so no log directory moves. Empty
        segments are kept as empty names, which is how the tree has always drawn
        ``a//b``.
        """
        parent = ROOT
        for segment in path.split(SEPARATOR):
            name = segment.strip()
            folder = self.child_named(parent, name)
            if folder is None:
                folder = Folder(new_folder_id(self.folders), name, parent)
                self.folders[folder.id] = folder
            parent = folder.id
        return parent

    def bind(self, hosts: Iterable[Host]) -> None:
        """File every host under a folder, and derive its `group` from that folder.

        A host's folder id wins when it names a folder. When it names nothing -- a record
        from before ADR-0002, a host the dialog has just built, or a folder merged away by
        repair() -- the host's `group` string is resolved instead, creating folders as
        needed. That fallback is the whole of the migration.
        """
        for host in hosts:
            if host.folder not in self.folders:
                host.folder = self.ensure_path(host.group or "")
            host.group = self.path_for(host.folder)

    def prune(self, keep: Iterable[str]) -> list[str]:
        """Remove every folder with none of `keep` at or below it. Returns their ids.

        Mirrors the old rule that a folder exists only while a host names it, so that
        binding hosts to records changes nothing on screen. Creating a folder that stays
        empty is a later phase of #154, and it retires this.
        """
        needed: set[str] = set()
        for folder_id in keep:
            while folder_id in self.folders and folder_id not in needed:
                needed.add(folder_id)
                folder_id = self.folders[folder_id].parent
        removed = [folder_id for folder_id in self.folders if folder_id not in needed]
        for folder_id in removed:
            del self.folders[folder_id]
        return removed

    def repair(self) -> list[str]:
        """Make the tree well formed, returning one entry per problem fixed.

        gcm.conf is a text file people edit and merge by hand. In order: a parent that
        names nothing becomes the top level; a cycle is cut where it closes; a `/` in a
        name becomes `_`; and siblings sharing a name are merged into the first of them.
        The last two keep every path distinct, which `host.group` depends on. Repeated
        ids cannot occur -- the id is the section name, and configparser refuses a
        repeated section.
        """
        fixes = []
        for folder in self.folders.values():
            if folder.parent != ROOT and folder.parent not in self.folders:
                folder.parent = ROOT
                fixes.append("unknown parent")
        for start in self.folders.values():
            visited = {start.id}
            node = start
            while node.parent != ROOT:
                parent = self.folders[node.parent]
                if parent.id in visited:
                    node.parent = ROOT
                    fixes.append("cycle")
                    break
                visited.add(parent.id)
                node = parent
        for folder in self.folders.values():
            if SEPARATOR in folder.name:
                folder.name = folder.name.replace(SEPARATOR, "_")
                fixes.append("separator in name")
        while (pair := self._first_duplicate_sibling()) is not None:
            keep, gone = pair
            for folder in self.folders.values():
                if folder.parent == gone.id:
                    folder.parent = keep.id
            del self.folders[gone.id]
            fixes.append("duplicate sibling")
        return fixes

    def _first_duplicate_sibling(self) -> tuple[Folder, Folder] | None:
        seen: dict[tuple[str, str], Folder] = {}
        for folder in self.folders.values():
            key = (folder.parent, folder.name)
            if key in seen:
                return seen[key], folder
            seen[key] = folder
        return None

    @classmethod
    def load(cls, cp: configparser.RawConfigParser) -> tuple[FolderTree, list[str]]:
        """Read every ``[folder <id>]`` section, then repair. Returns the tree and fixes.

        A config with no folder sections gives an empty tree, and `bind` then builds it
        from the hosts' `group` strings.
        """
        tree = cls()
        for section in cp.sections():
            if not section.startswith(SECTION_PREFIX):
                continue
            folder_id = section[len(SECTION_PREFIX) :].strip()
            if not folder_id:
                continue
            tree.folders[folder_id] = Folder(
                folder_id,
                cp.get(section, "name", fallback=""),
                cp.get(section, "parent", fallback=ROOT),
            )
        return tree, tree.repair()

    def save(self, cp: configparser.RawConfigParser) -> None:
        for folder in self.folders.values():
            section = SECTION_PREFIX + folder.id
            cp.add_section(section)
            cp.set(section, "name", folder.name)
            cp.set(section, "parent", folder.parent)
