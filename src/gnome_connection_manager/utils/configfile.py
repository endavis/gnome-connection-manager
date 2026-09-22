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


class UnreadableError(Exception):
    """gcm.conf exists but cannot be read in full. The message says where."""


class Reading(NamedTuple):
    config: configparser.RawConfigParser
    kept_apart: int  # repeated host or folder sections kept as records of their own
    dropped: int  # repeats that were verbatim copies
    ambiguous_folders: frozenset[str]  # folder ids that named more than one record


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
