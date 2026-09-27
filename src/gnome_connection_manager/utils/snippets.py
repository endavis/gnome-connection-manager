"""A library of snippets: text typed into a console on request, found by name (#240).

A snippet has a name and a text, and may have a key that sends it, a folder it is filed
under in the menus, and a description. Each is a record of its own in gcm.conf,
``[snippet <id>]``, as hosts and folders are, so one deleted does not come back from the
file (`configfile.RECORD_PREFIXES`).

Snippets replace custom commands, which GCM kept in ``[shortcuts]`` as ``shortcutN`` and
``commandN`` pairs: a command only ever with a key, and listed by its text. `migrate`
turns each pair into a snippet named by its first line, once. A pair whose key a snippet
already has is the copy a save writes back for an older GCM, which still reads the pairs,
not a command of its own.

A snippet's text is stored with `encode`, which loses nothing. The pairs' encoding did:
it wrote a newline as ``\\n`` and read every ``\\n`` back as a newline, so a command
holding a backslash and an n came back changed, measured. `migrate` reads the pairs as
GCM always has, which is what it has been sending, and a save writes its copies the same
way, for an older GCM to read as it always has.

Pure of GTK and of configuration globals, so it is tested directly.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import configparser
    from collections.abc import Collection, Iterable

SECTION_PREFIX = "snippet "
ID_BYTES = 4
# A name made from a text's first line is cut here, for the menus.
NAME_MAX = 40


@dataclass
class Snippet:
    id: str
    name: str
    text: str
    key: str = ""
    folder: str = ""
    description: str = ""


@dataclass
class Folder:
    """A folder of snippets as the menus draw it: subfolders, then snippets, by name."""

    name: str
    folders: list[Folder] = field(default_factory=list)
    snippets: list[Snippet] = field(default_factory=list)


def new_snippet_id(taken: Collection[str] = ()) -> str:
    """Mint a snippet id: random hex, for the reason host ids are random (ADR-0001)."""
    while True:
        snippet_id = secrets.token_hex(ID_BYTES)
        if snippet_id not in taken:
            return snippet_id


def name_for(text: str) -> str:
    """A name for a snippet that has none: its text's first line that is not blank."""
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if not first:
        return repr(text)
    if len(first) > NAME_MAX:
        return first[: NAME_MAX - 1].rstrip() + "…"
    return first


def encode(text: str) -> str:
    """A snippet's text as gcm.conf holds it: a JSON string, which configparser keeps as
    written. A value it stores bare loses its leading and trailing spaces, and the ``cd ``
    that waits for a directory to be typed after it is a snippet."""
    return json.dumps(text, ensure_ascii=False)


def decode(value: str) -> str:
    """A snippet's text from gcm.conf. A value that is not a JSON string, as someone may
    write by hand, is taken as it is written."""
    if value.startswith('"'):
        try:
            text = json.loads(value)
        except ValueError:
            return value
        if isinstance(text, str):
            return text
    return value


def legacy_encode(text: str) -> str:
    """A command as the ``commandN`` pairs hold it, for an older GCM to read."""
    return text.replace("\n", "\\n")


def legacy_decode(value: str) -> str:
    """A ``commandN`` value as GCM has always read it, and so sent it."""
    return value.replace("\\n", "\n")


def one_line(value: str) -> str:
    return " ".join(value.split("\n")).strip()


def load(cp: configparser.RawConfigParser) -> list[Snippet]:
    """The snippets gcm.conf records, in the order it holds them. A record without text
    has nothing to send, and is left out."""
    snippets: list[Snippet] = []
    taken = {section[len(SECTION_PREFIX) :].strip() for section in cp.sections()}
    for section in cp.sections():
        if not section.startswith(SECTION_PREFIX):
            continue
        values = dict(cp.items(section))
        text = decode(values.get("text", ""))
        if not text:
            continue
        snippet_id = section[len(SECTION_PREFIX) :].strip()
        if not snippet_id:
            snippet_id = new_snippet_id(taken)
            taken.add(snippet_id)
        snippets.append(
            Snippet(
                snippet_id,
                values.get("name", "").strip() or name_for(text),
                text,
                values.get("key", "").strip(),
                values.get("folder", "").strip(),
                values.get("description", "").strip(),
            )
        )
    return snippets


def save(cp: configparser.RawConfigParser, snippets: Iterable[Snippet]) -> None:
    """Write each snippet as a record. An empty key, folder or description is left out."""
    for snippet in snippets:
        section = SECTION_PREFIX + snippet.id
        cp.add_section(section)
        cp.set(section, "name", one_line(snippet.name))
        cp.set(section, "text", encode(snippet.text))
        for option in ("key", "folder", "description"):
            value = one_line(getattr(snippet, option))
            if value:
                cp.set(section, option, value)


def legacy_commands(cp: configparser.RawConfigParser) -> list[tuple[str, str]]:
    """The ``shortcutN``/``commandN`` pairs, key and text, read as GCM read them: from 1,
    up to the first pair that is not whole."""
    pairs = []
    number = 1
    while cp.has_option("shortcuts", f"shortcut{number}") and cp.has_option(
        "shortcuts", f"command{number}"
    ):
        key = cp.get("shortcuts", f"shortcut{number}")
        pairs.append((key, legacy_decode(cp.get("shortcuts", f"command{number}"))))
        number += 1
    return pairs


def migrate(cp: configparser.RawConfigParser, snippets: Iterable[Snippet]) -> list[Snippet]:
    """New snippets for the custom commands whose key no snippet has (#240).

    Keys and text as GCM had them. Of two pairs with one key the later is kept, since
    it was the one the key sent.
    """
    have = {snippet.key for snippet in snippets if snippet.key}
    taken = {snippet.id for snippet in snippets}
    commands: dict[str, str] = {}
    for key, text in legacy_commands(cp):
        if key not in have and text:
            commands[key] = text
    found = []
    for key, text in commands.items():
        snippet_id = new_snippet_id(taken)
        taken.add(snippet_id)
        found.append(Snippet(snippet_id, name_for(text), text, key))
    return found


def drop_repeated_keys(snippets: Iterable[Snippet]) -> None:
    """Of snippets that have one key, only the last keeps it, since it is the one the key
    sends. The others stay, without a key."""
    seen: set[str] = set()
    for snippet in reversed(list(snippets)):
        if not snippet.key:
            continue
        if snippet.key in seen:
            snippet.key = ""
        else:
            seen.add(snippet.key)


def folder_path(folder: str) -> list[str]:
    """A folder's names from the top, as ``a/b`` writes them."""
    return [part.strip() for part in folder.split("/") if part.strip()]


def tree(snippets: Iterable[Snippet]) -> Folder:
    """The snippets filed by folder, each level's subfolders and snippets by name."""
    root = Folder("")
    for snippet in snippets:
        node = root
        for part in folder_path(snippet.folder):
            child = next((folder for folder in node.folders if folder.name == part), None)
            if child is None:
                child = Folder(part)
                node.folders.append(child)
            node = child
        node.snippets.append(snippet)
    _sort(root)
    return root


def _sort(folder: Folder) -> None:
    folder.folders.sort(key=lambda child: child.name.casefold())
    folder.snippets.sort(key=lambda snippet: (snippet.name.casefold(), snippet.name))
    for child in folder.folders:
        _sort(child)
