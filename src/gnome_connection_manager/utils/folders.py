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

Order is kept sparsely. A ``position`` on a folder or a host places it among its siblings,
subfolders and hosts together, and a folder whose children carry none is drawn in name
order -- as every folder was before ordering existed. ``number`` decides when positions
are kept.

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


class FolderError(ValueError):
    """An edit that would break the tree. `reason` is one of the constants below."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


EMPTY_NAME = "empty"
NAME_HAS_SEPARATOR = "separator"
NAME_TAKEN = "taken"
INTO_ITSELF = "cycle"
NO_SUCH_FOLDER = "unknown"


def parse_position(text: str | None) -> int | None:
    """A stored position, or None when it is absent or not a whole number.

    A position only orders siblings, so an unreadable one costs nothing but its place:
    the record sorts with the ones that have none.
    """
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        return None


class Folder:
    def __init__(
        self, folder_id: str, name: str, parent: str = ROOT, position: int | None = None
    ) -> None:
        self.id = folder_id
        self.name = name
        self.parent = parent
        # Where it sits among its parent's children, or None for name order; see number().
        self.position = position

    def __repr__(self) -> str:
        return f"Folder({self.id!r}, {self.name!r}, parent={self.parent!r})"


def by_name(children: Iterable[Folder | Host]) -> list[Folder | Host]:
    """The order of a folder nobody has arranged: subfolders, then hosts, each by name.

    It is the order the tree was always drawn in, so a config with no positions in it
    looks exactly as it did before ordering existed.
    """
    return sorted(children, key=lambda child: (not isinstance(child, Folder), child.name))


def ordered(children: Iterable[Folder | Host]) -> list[Folder | Host]:
    """`children` in the order the tree draws them: by position, then the rest by name."""
    children = list(children)
    placed = sorted(
        (child for child in children if child.position is not None),
        key=lambda child: (child.position or 0, not isinstance(child, Folder), child.name),
    )
    return placed + by_name(child for child in children if child.position is None)


def arranged(
    order: list[Folder | Host],
    item: Folder | Host,
    beside: Folder | Host | None = None,
    *,
    after: bool = False,
) -> list[Folder | Host]:
    """`order` with `item` moved next to `beside`, or to the end. Changes nothing.

    `order` is one folder's children as drawn; `item` may be among them (a reorder) or
    not (a move in from elsewhere).
    """
    rest = [child for child in order if child is not item]
    index = len(rest) if beside is None else rest.index(beside) + (1 if after else 0)
    rest.insert(index, item)
    return rest


def number(order: list[Folder | Host]) -> None:
    """Store `order` as positions -- or as none at all, when it is name order anyway.

    That keeps a position meaning "the user put this here". A folder in name order stays
    in name order as hosts are added to it, and one arranged back into name order goes
    back to sorting itself.
    """
    keep = order != by_name(order)
    for position, child in enumerate(order):
        child.position = position if keep else None


def place(
    order: list[Folder | Host],
    item: Folder | Host,
    beside: Folder | Host | None = None,
    *,
    after: bool = False,
) -> None:
    """File `item` among `order`, one folder's children as the tree draws them.

    Next to `beside` when given. Otherwise at the end of a folder the user has arranged,
    and at its place by name in one they have not: dropping a host on a folder should
    not be what turns that folder's order into a manual one.
    """
    if beside is None and all(child.position is None for child in order if child is not item):
        item.position = None
        return
    number(arranged(order, item, beside, after=after))


class FolderTree:
    """Every folder, keyed by id. A parent of `ROOT` means top level."""

    def __init__(self) -> None:
        self.folders: dict[str, Folder] = {}

    def child_named(self, parent: str, name: str) -> Folder | None:
        for folder in self.folders.values():
            if folder.parent == parent and folder.name == name:
                return folder
        return None

    def contents(self, hosts: Iterable[Host]) -> dict[str, list[Folder | Host]]:
        """Each folder's children -- subfolders and hosts together -- as the tree draws
        them, keyed by folder id, with `ROOT` for the top level. Changes nothing.

        Hosts are filed by `host.folder`, so bind them first. A folder with no children
        has no entry.
        """
        contents: dict[str, list[Folder | Host]] = {}
        for folder in self.folders.values():
            contents.setdefault(folder.parent, []).append(folder)
        for host in hosts:
            contents.setdefault(host.folder, []).append(host)
        return {parent: ordered(children) for parent, children in contents.items()}

    def is_ancestor(self, ancestor: str, folder_id: str) -> bool:
        """Whether `ancestor` is `folder_id` itself or any folder above it."""
        seen = set()
        while folder_id in self.folders and folder_id not in seen:
            if folder_id == ancestor:
                return True
            seen.add(folder_id)
            folder_id = self.folders[folder_id].parent
        return False

    def subtree(self, folder_id: str) -> set[str]:
        """`folder_id` and every folder below it."""
        return {other for other in self.folders if self.is_ancestor(folder_id, other)}

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
        needed. That fallback is the whole of the migration. A folder left with no hosts
        stays: folders are records now, not a side effect of a path.
        """
        for host in hosts:
            if host.folder not in self.folders:
                host.folder = self.ensure_path(host.group or "")
            host.group = self.path_for(host.folder)

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

    def check_name(self, parent: str, name: str, *, renaming: str | None = None) -> str:
        """The name as it would be stored under `parent`, or FolderError saying why not.

        The same rules repair() enforces on a hand-edited file, applied before the edit
        instead of after it. `renaming` is the folder being renamed, which may keep its
        own name.
        """
        name = name.strip()
        if not name:
            raise FolderError(EMPTY_NAME)
        if SEPARATOR in name:
            raise FolderError(NAME_HAS_SEPARATOR)
        self._check_free(parent, name, renaming)
        return name

    def _check_free(self, parent: str, name: str, moving: str | None) -> None:
        existing = self.child_named(parent, name)
        if existing is not None and existing.id != moving:
            raise FolderError(NAME_TAKEN)

    def _check_parent(self, parent: str) -> None:
        if parent != ROOT and parent not in self.folders:
            raise FolderError(NO_SUCH_FOLDER)

    def add(self, parent: str, name: str) -> Folder:
        self._check_parent(parent)
        folder = Folder(new_folder_id(self.folders), self.check_name(parent, name), parent)
        self.folders[folder.id] = folder
        return folder

    def rename(self, folder_id: str, name: str) -> None:
        folder = self._get(folder_id)
        folder.name = self.check_name(folder.parent, name, renaming=folder_id)

    def move(self, folder_id: str, parent: str) -> None:
        """Refile a folder, with everything below it, under `parent`.

        Only the collision rule is checked for the name: a folder read from an old
        file may carry an empty name, and moving it should not demand a rename.
        """
        self.check_move(folder_id, parent)
        folder = self.folders[folder_id]
        if folder.parent != parent:
            # A position orders a folder among its siblings, and these are new ones.
            folder.parent, folder.position = parent, None

    def check_move(self, folder_id: str, parent: str) -> None:
        """What move() would refuse, without moving: a drag asks on every motion."""
        folder = self._get(folder_id)
        self._check_parent(parent)
        if self.is_ancestor(folder_id, parent):
            raise FolderError(INTO_ITSELF)
        self._check_free(parent, folder.name, folder_id)

    def remove(self, folder_id: str) -> set[str]:
        """Delete a folder and every folder below it. Returns the ids removed."""
        self._get(folder_id)
        doomed = self.subtree(folder_id)
        for other in doomed:
            del self.folders[other]
        return doomed

    def _get(self, folder_id: str) -> Folder:
        try:
            return self.folders[folder_id]
        except KeyError:
            raise FolderError(NO_SUCH_FOLDER) from None

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
                parse_position(cp.get(section, "position", fallback=None)),
            )
        return tree, tree.repair()

    def save(self, cp: configparser.RawConfigParser) -> None:
        for folder in self.folders.values():
            section = SECTION_PREFIX + folder.id
            cp.add_section(section)
            cp.set(section, "name", folder.name)
            cp.set(section, "parent", folder.parent)
            if folder.position is not None:
                cp.set(section, "position", str(folder.position))
