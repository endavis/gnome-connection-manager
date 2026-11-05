"""Trace lines for the areas of GCM that fail where a developer cannot see them (#507).

`GCM_TRACE=drag,menu` (or `all`) switches areas on; unset, nothing is written and nothing
is installed. Each line goes to stderr, stamped as libwayland stamps a `WAYLAND_DEBUG` line
(`[%7u.%03u]`, microseconds of the realtime clock modulo 2**32), so GCM's lines and the
protocol's fall in order in one stream.

What decides on or off is this module's set of areas, not a logger's level: `GCM_LOG_LEVEL`
never turns a trace on, and a trace never changes `GCM_LOG_LEVEL`. An area's logger is
`gnome_connection_manager.<area>`, with a handler of its own and `propagate` off so that
the root handler does not print each line twice.

Safety. A trace must never change what a handler does, and the handlers it sits in are
GTK's signal handlers, run in the middle of a drag:

- a call site passes `note` a function, never a string it built: nothing is evaluated
  while the area is off;
- `note` catches anything the function or a handler raises;
- a line reads data GCM holds (a page's `trace_name`, a notebook's `trace_number`), and
  walks no widget that a drag may have destroyed.

Privacy. A line holds a notebook's number and place, a tab's name as the host is named,
a button number, booleans, counts and pixel figures, a drag result's name, and the
environment's facts. Never a menu item's label, a console's text or title, a search
or a configuration value.

The areas of #513 add to that, and name no more. `keys`: a key GCM's accelerators own is
named by the action it runs, a key typed into a console by nothing, so ordinary typing
writes no line; never a key given to a console, a prefix key, the key after one, a `[keys]`
sequence or a snippet's text. `actions`: an action's name, never its parameter or state.
`links`: a matcher's kind and tag, never the text searched, a URL or a console's text.
`config`: a section's or an option's name and counts, never a value, nor an exception's
message, which may quote one (only its class). `notifications`: which services answer on the
bus, never the notification's text.

History. #401 and #406 were found by wrapping handlers from outside, and #505 (a join
that ran while the drag it followed was still on) by a crash with no line to show the
order. These lines are what those hand checks needed.
"""

from __future__ import annotations

import contextlib
import logging
import subprocess
import sys
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

DRAG = "drag"
MENU = "menu"
KEYS = "keys"
ACTIONS = "actions"
LINKS = "links"
CONFIG = "config"
NOTIFICATIONS = "notifications"
AREAS = (DRAG, MENU, KEYS, ACTIONS, LINKS, CONFIG, NOTIFICATIONS)

ROOT_LOGGER = "gnome_connection_manager"
STAMP_WRAP = 2**32
LABEL_LIMIT = 200
NO_LABEL = "(no label)"

ENVIRONMENT_KEYS = (
    "gtk",
    "display",
    "scale",
    "theme",
    "font",
    "font_family",
    "GDK_BACKEND",
    "GDK_SCALE",
    "GDK_DPI_SCALE",
    "WAYLAND_DEBUG",
    "config_dir",
    "commit",
)

_enabled: frozenset[str] = frozenset()


def parse(value: str | None) -> tuple[frozenset[str], tuple[str, ...]]:
    """The areas `value` names, and the names that are no area, once each in order."""
    areas: set[str] = set()
    unknown: list[str] = []
    for item in (value or "").split(","):
        name = item.strip().lower()
        if not name:
            continue
        if name == "all":
            areas.update(AREAS)
        elif name in AREAS:
            areas.add(name)
        elif name not in unknown:
            unknown.append(name)
    return frozenset(areas), tuple(unknown)


def stamp(microseconds: int) -> str:
    """libwayland's `[%7u.%03u]`: milliseconds, a dot, then the remaining microseconds."""
    t = microseconds % STAMP_WRAP
    return f"[{t // 1000:7d}.{t % 1000:03d}]"


class TraceFormatter(logging.Formatter):
    """`<stamp> <area>: <message>`."""

    def format(self, record: logging.LogRecord) -> str:
        area = record.name.removeprefix(ROOT_LOGGER + ".")
        return f"{stamp(int(record.created * 1_000_000))} {area}: {record.getMessage()}"


class TraceHandler(logging.Handler):
    """Writes to the stream given, else to `sys.stderr` as it is when the line is written."""

    def __init__(self, stream: TextIO | None = None) -> None:
        super().__init__(logging.DEBUG)
        self.target = stream
        self.setFormatter(TraceFormatter())

    def emit(self, record: logging.LogRecord) -> None:
        out = self.target if self.target is not None else sys.stderr
        out.write(self.format(record) + "\n")
        out.flush()


def _logger(area: str) -> logging.Logger:
    return logging.getLogger(f"{ROOT_LOGGER}.{area}")


def configure(
    environ: Mapping[str, str], stream: TextIO | None = None
) -> tuple[frozenset[str], tuple[str, ...]]:
    """Switch on the areas `GCM_TRACE` names in `environ`, and off every other.

    Idempotent: a handler this module added earlier is removed first. Returns what `parse`
    does, so the caller can report a name that is no area.
    """
    global _enabled
    areas, unknown = parse(environ.get("GCM_TRACE"))
    _enabled = areas
    for area in AREAS:
        logger = _logger(area)
        for handler in list(logger.handlers):
            if isinstance(handler, TraceHandler):
                logger.removeHandler(handler)
        if area in areas:
            logger.addHandler(TraceHandler(stream))
            logger.setLevel(logging.DEBUG)
            logger.propagate = False
        else:
            logger.setLevel(logging.NOTSET)
            logger.propagate = True
    return areas, unknown


def enabled(area: str) -> bool:
    return area in _enabled


def first_enabled() -> str | None:
    """The first area that is on, in `AREAS` order, for a line that belongs to none."""
    for area in AREAS:
        if area in _enabled:
            return area
    return None


def note(area: str, message: Callable[[], str]) -> None:
    """Write `message()` as a line of `area`; never raises, and never calls `message` when
    the area is off."""
    if area not in _enabled:
        return
    with contextlib.suppress(Exception):
        _logger(area).debug(message())


def _value(value: str | None) -> str:
    if value is None:
        return "(unset)"
    return f'"{value}"' if any(c.isspace() for c in value) or not value else value


def environment_line(facts: Mapping[str, str | None]) -> str:
    """The facts a report needs, in a fixed order; `(unset)` for one that is None or
    missing."""
    return "environment " + " ".join(f"{key}={_value(facts.get(key))}" for key in ENVIRONMENT_KEYS)


def place(pane: int | None, panes: int, window: int | None) -> str:
    """Where a notebook is: "window k", "pane i of n", or that the place was not read."""
    if window is not None:
        return f"window {window}"
    if pane is None:
        return "place not read during a drag"
    return f"pane {pane} of {panes}"


def tabs_line(
    notebooks: Sequence[tuple[int, str, Sequence[str]]],
    strays: Sequence[str],
    checked: bool = True,
) -> str:
    """Each notebook's number, place and tabs, then the labels found out of place."""
    parts = [
        f"notebook {number} ({where}): {', '.join(names) or '(no tabs)'}"
        for number, where, names in notebooks
    ]
    if not checked:
        tail = "labels not checked"
    elif strays:
        tail = "stray labels: " + ", ".join(strays)
    else:
        tail = "stray labels: none"
    return "tabs " + " | ".join(parts + [tail])


NOTIFICATION_NAMES = (
    "org.freedesktop.Notifications",
    "org.freedesktop.portal.Desktop",
    "org.gtk.Notifications",
)


def key_line(route: str, where: str, action: str | None = None) -> str:
    """A key's route and what took it: "key: <route> (<where>)", with the action when an
    accelerator owns the key. Never the key itself (#513)."""
    tail = f", action {action}" if action else ""
    return f"key: {route} ({where}){tail}"


def refused_host_line(section: str, error: str, options: int) -> str:
    """A host section loadConfig could not read: its name, the error's class and how many
    options it holds; no option's value and no message (#513)."""
    return f"load: host section [{section}] refused, {error}, {options} option(s)"


def save_line(
    hosts: int,
    refused: int,
    unread: int,
    carried: Sequence[str],
    dropped: Sequence[str] | None = None,
) -> str:
    """What a save wrote, carried across and dropped; names and counts only (#513).

    `dropped` is the sections the file had that the save leaves out, None where the file
    could not be read for it."""
    kept = ", ".join(carried) or "none"
    gone = "not read" if dropped is None else (", ".join(dropped) or "none")
    return (
        f"save: {hosts} host(s) written, {refused} refused host(s) put back, "
        f"{unread} unread option(s) put back, sections carried: {kept}, "
        f"sections dropped: {gone}"
    )


def notification_line(
    sent: bool, owners: Mapping[str, bool] | None, application: bool = True
) -> str:
    """Whether a desktop notification went out, and which services own their name on the
    bus. Never its text (#513)."""
    if not application:
        return "notification: not sent, the window has no application"
    state = "sent" if sent else "not sent"
    if owners is None:
        return f"notification: {state}, bus not reached"
    named = ", ".join(f"{name} {'yes' if owned else 'no'}" for name, owned in owners.items())
    return f"notification: {state}, services on the bus: {named}"


def mark_line(label: str) -> str:
    return f"=== MARK {label} ==="


def read_mark_label(path: Path) -> str:
    """The first line of the file at `path`, stripped and cut, or `(no label)`."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return NO_LABEL
    lines = text.splitlines()
    label = lines[0].strip()[:LABEL_LIMIT] if lines else ""
    return label or NO_LABEL


def checkout_commit(package_dir: Path) -> str | None:
    """The short commit of the git checkout GCM runs from, or None where it is no checkout
    or git does not say."""
    root = package_dir.parents[1]
    if not (root / ".git").exists():
        return None
    try:
        done = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.strip() or None
