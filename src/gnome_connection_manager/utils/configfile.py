"""Reading gcm.conf: leniently where that loses nothing, and not at all where it would.

configparser's strict mode refuses a file with a repeated section or a repeated key. That
is what merging two copies of gcm.conf by hand produces -- both number their hosts from
``[host 1]`` -- and until #161 GCM met it by coming up with no window and no message.
Both can be read without losing anything:

- a repeated ``[host N]`` is another host. Host sections are positional and renumbered on
  every write, so the repeat is simply given a free name.
- a repeated ``[folder <id>]`` is another folder, given a fresh id. A host naming that id
  cannot say which of the two it meant, so the id is reported as ambiguous and the caller
  files such hosts by the ``group`` path each one also carries.
- a repeat of either that is a verbatim copy of one already read is dropped.
- a repeated singleton section -- ``[options]``, ``[window]`` -- merges into the first,
  and a repeated key keeps its later value, as configparser's lenient mode does.

Anything else configparser refuses -- a stray line, text before the first section -- and
a file that cannot be decoded or opened raise `UnreadableError`, saying where. Dropping
such a line would lose whatever it was meant to say, and starting without the file is
worse: GCM writes its host list over the file when the window closes.

A save starts from the file too (#163): `unwritten` strips the sections a save writes from
memory and leaves the rest -- [keys], which people write by hand -- to be carried across.

An option whose value cannot be read comes back from `read_option` with the default and an
`Unread` record of what the file said. Until #173 the next save wrote that default over the
line, so the value was gone from the file with only a line on stderr to say so;
`put_back_unread` writes the text back instead, for as long as the setting still holds the
value used in its place.

Pure of GTK and of configuration globals, so it is tested directly.
"""

from __future__ import annotations

import configparser
from typing import TYPE_CHECKING, NamedTuple

from gnome_connection_manager.utils.folders import SECTION_PREFIX as FOLDER_PREFIX
from gnome_connection_manager.utils.folders import new_folder_id

if TYPE_CHECKING:
    from pathlib import Path

HOST_PREFIX = "host "

# Sections a save writes from memory. Host and folder sections are records, renumbered or
# re-keyed on every save, so one missing from memory was deleted and must not come back
# from the file; the others are written in full.
WRITTEN_SECTIONS = frozenset({"options", "window", "shortcuts"})
RECORD_PREFIXES = (HOST_PREFIX, FOLDER_PREFIX)


class UnreadableError(Exception):
    """gcm.conf exists but cannot be read in full. The message says where."""


class Reading(NamedTuple):
    config: configparser.RawConfigParser
    kept_apart: int  # repeated host or folder sections kept as records of their own
    dropped: int  # repeats that were verbatim copies
    ambiguous_folders: frozenset[str]  # folder ids that named more than one record


class Unread(NamedTuple):
    """An option the file gives a value that cannot be read, and the value used instead."""

    section: str
    option: str
    text: str  # the value as the file has it
    used: object  # the default read_option returned in its place
    reason: str  # configparser's or int()'s own words


def header(line: str) -> str | None:
    """The section a line opens, matched as configparser matches it, or None.

    Only a line starting with ``[`` counts. configparser also takes an indented one as a
    header when it does not continue a value; GCM never writes one, so a repeat of that
    kind is left to merge rather than guessed at.
    """
    if not line.startswith("["):
        return None
    match = configparser.RawConfigParser.SECTCRE.match(line.strip())
    return match.group("header") if match else None


def free_name(name: str, taken: set[str]) -> str:
    candidate, count = name, 1
    while candidate in taken:
        count += 1
        candidate = f"{name} {count}"
    return candidate


def read_config(text: str, source: str = "<gcm.conf>") -> Reading:
    """Parse gcm.conf's text, keeping repeated host and folder sections apart.

    Raises configparser.Error for anything the lenient parser still refuses.
    """
    # Split where configparser splits, on newlines alone: str.splitlines also breaks at a
    # form feed or U+2028, which can sit inside a pasted value.
    lines = text.split("\n")
    names = [header(line) for line in lines]
    taken = {name for name in names if name is not None}
    seen: set[str] = set()
    renamed: dict[str, str] = {}
    for index, name in enumerate(names):
        if name is None:
            continue
        if name not in seen:
            seen.add(name)
            continue
        if name.startswith(HOST_PREFIX):
            new = free_name(f"{name} (repeat)", taken)
        elif name.startswith(FOLDER_PREFIX):
            ids = {n[len(FOLDER_PREFIX) :].strip() for n in taken if n.startswith(FOLDER_PREFIX)}
            new = FOLDER_PREFIX + new_folder_id(ids)
        else:
            continue
        taken.add(new)
        renamed[new] = name
        lines[index] = f"[{new}]"

    config = configparser.RawConfigParser(strict=False)
    config.read_string("\n".join(lines), source)

    kept_apart = dropped = 0
    ambiguous: set[str] = set()
    copies: dict[str, list[dict[str, str]]] = {}
    for new, name in renamed.items():
        read = copies.setdefault(name, [dict(config.items(name))])
        content = dict(config.items(new))
        if content in read:
            config.remove_section(new)
            dropped += 1
            continue
        read.append(content)
        kept_apart += 1
        if name.startswith(FOLDER_PREFIX):
            ambiguous.add(name[len(FOLDER_PREFIX) :].strip())
    return Reading(config, kept_apart, dropped, frozenset(ambiguous))


def load(path: Path) -> Reading:
    """Read gcm.conf at `path`. A file that does not exist is an empty configuration.

    Raises UnreadableError, naming the file and where possible the line, when it exists
    and cannot be read in full. The text is decoded as `open` would, which is how GCM
    writes it.
    """
    try:
        text = path.read_text()
    except FileNotFoundError:
        text = ""
    except UnicodeDecodeError as error:
        line = error.object[: error.start].count(b"\n") + 1
        raise UnreadableError(f"{path}: line {line} is not valid {error.encoding}") from error
    except OSError as error:
        raise UnreadableError(f"{path}: {error.strerror or error}") from error
    try:
        return read_config(text, str(path))
    except configparser.Error as error:
        raise UnreadableError(str(error)) from error


def unwritten(config: configparser.RawConfigParser) -> configparser.RawConfigParser:
    """Strip from `config` the sections a save writes, leaving what it carries across.

    What is left is [keys], which GCM reads and never writes because people write it by
    hand (#163), and any section GCM does not know. [DEFAULT] stays as well: configparser
    keeps it apart from the sections.
    """
    for section in config.sections():
        if section in WRITTEN_SECTIONS or section.startswith(RECORD_PREFIXES):
            config.remove_section(section)
    return config


def read_option(
    config: configparser.RawConfigParser, section: str, option: str, kind: type, default: object
) -> tuple[object, Unread | None]:
    """One option's value, read as `kind`, and an `Unread` if the file's value cannot be.

    An absent option is not unread: a file written before the option existed simply has
    none, and takes the default without comment. A `str` option always reads.
    """
    try:
        if kind is bool:
            return config.getboolean(section, option), None
        if kind is int:
            return config.getint(section, option), None
        return config.get(section, option), None
    except (configparser.NoSectionError, configparser.NoOptionError):
        return default, None
    except (configparser.Error, ValueError) as error:
        return default, Unread(section, option, config.get(section, option), default, str(error))


def put_back_unread(
    config: configparser.RawConfigParser,
    unread: list[Unread],
    current: dict[tuple[str, str], object],
) -> list[Unread]:
    """Write each unread option's text back over the value a save put in its place, while
    the setting still holds the value used instead of it, and return those put back.

    `current` maps (section, option) to the setting's value now. One that has moved on
    was changed since -- in Preferences, say -- and that value is the one to keep; its
    record is dropped, so setting it back to the default later writes the default.
    """
    kept = []
    for record in unread:
        if current.get((record.section, record.option)) == record.used:
            config.set(record.section, record.option, record.text)
            kept.append(record)
    return kept


def aside_path(path: Path, stamp: str) -> Path:
    """A free name beside `path` for a copy of it that must not be written over."""
    candidate = path.with_name(f"{path.name}.unreadable-{stamp}")
    count = 1
    while candidate.exists():
        count += 1
        candidate = path.with_name(f"{path.name}.unreadable-{stamp}-{count}")
    return candidate
