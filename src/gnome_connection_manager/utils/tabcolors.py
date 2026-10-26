"""The colour a host's tabs are marked with (#350).

Tabs are told apart by their names, and with many open across several projects a colour
can be quicker to read. A host can have a colour of its own, from the host dialog, and a
folder can have one for every host in it, from the folder's menu. A host's own wins; a
host without one takes the colour of the nearest folder above it that has one, so a
folder colours its subfolders' hosts too, until one of them, or a host, sets another.

The colour is drawn as a stripe across the top of the tab: the cluster window's tick and a
tab that needs attention already colour the tab's background, and the theme marks the tab
in use along its bottom, measured in Adwaita and Yaru and their dark variants. Text in a
colour would have to be read against all of those.

A colour is stored as written, `#rrggbb` as GCM writes it. One that cannot be read, as a
hand edit can leave, counts as none and is kept as it is, so that a save does not lose it.
Only a colour read here reaches the CSS the tab is drawn with.

Pure: the host and the folder tree are arguments.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from gnome_connection_manager.utils.folders import FolderTree

# How tall the stripe is, in pixels, and the gap below it where a mark on the tab starts,
# which data/style.css leaves: without it, measured, a stripe of the mark's own colour
# could not be seen on it.
STRIPE = 4
GAP = 2

HEX_COLOR = re.compile(r"#([0-9a-f]{3}|[0-9a-f]{6})")


def color_of(text: str) -> str:
    """`text` as `#rrggbb` in lower case, for a `#rgb` or a `#rrggbb`, else ""."""
    text = (text or "").strip().lower()
    if not HEX_COLOR.fullmatch(text):
        return ""
    digits = text[1:]
    if len(digits) == 3:
        digits = "".join(digit * 2 for digit in digits)
    return f"#{digits}"


def folder_color(tree: FolderTree, folder_id: str) -> str:
    """The colour of the folder `folder_id`, or of the nearest folder above it with one,
    or "" where none has one that can be read."""
    seen: set[str] = set()
    # `seen` only matters for a tree that skipped repair(); a cycle must not hang.
    while folder_id in tree.folders and folder_id not in seen:
        seen.add(folder_id)
        folder = tree.folders[folder_id]
        color = color_of(folder.tab_color)
        if color:
            return color
        folder_id = folder.parent
    return ""


def tab_color(host: Any, tree: FolderTree) -> str:
    """The colour of `host`'s tabs: its own, else its folder's, as `folder_color` finds it,
    else ""."""
    return color_of(host.tab_color) or folder_color(tree, host.folder)


def stripe_css(color: str) -> str:
    """The CSS a tab's label is drawn with for `color`, and none for "": an inset shadow,
    which takes no room, so a tab is as large with a colour as without."""
    color = color_of(color)
    if not color:
        return ""
    return f"* {{ box-shadow: inset 0 {STRIPE}px {color}; }}"
