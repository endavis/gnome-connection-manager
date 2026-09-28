"""A host's values filled into a command written for it (#238).

A host's commands to run on this computer, before connecting and after disconnecting,
name the host's values in braces: `{name}`, `{address}`, `{port}`, `{user}`, `{group}`
and `{type}`. Anything else in braces is left as written, so `awk '{print $1}'` keeps
its braces.

Pure: `quote` is the caller's. A command run through `sh -c` quotes each value with
`shlex.quote`, so that a host name holding a space or a `;` stays one argument and
cannot extend the command.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

PLACEHOLDERS = ("name", "address", "port", "user", "group", "type")

_PLACEHOLDER = re.compile(r"\{(" + "|".join(PLACEHOLDERS) + r")\}")


def host_values(host: Any) -> dict[str, str]:
    """Each placeholder's value for `host`, as text. A value the host lacks is empty."""
    fields = {
        "name": host.name,
        "address": host.host,
        "port": host.port,
        "user": host.user,
        "group": host.group,
        "type": host.type,
    }
    return {key: "" if value is None else str(value) for key, value in fields.items()}


def fill(
    template: str, values: dict[str, str], quote: Callable[[str], str] = lambda value: value
) -> str:
    """`template` with each placeholder replaced by its value, passed through `quote`."""
    return _PLACEHOLDER.sub(lambda match: quote(values[match.group(1)]), template)
