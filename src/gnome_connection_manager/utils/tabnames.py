"""What a host's tab is called (#346).

A tab is named after its host, and two hosts in two folders can share a name, as
`1. Projects/infrafoundry/ansible` and `1. Projects/pyproject-template/ansible` do. Their
tabs read the same, and so does everything that names a tab: the window title, the
cluster window's list, the open-console list. So a host whose name another host has gets
as much of its folder path as tells it apart from each of them, in front of its name:
`infrafoundry/ansible` and `pyproject-template/ansible`. Folder first, because a label is
cut at its end, `truncate_tab_label`, and the cut then takes the program title before the
part that tells the tabs apart.

A host whose name is its own keeps it alone, so no tab changes where nothing is ambiguous.
One at the top level has no folder to show: beside `infrafoundry/ansible` it stays
`ansible`, which already tells the two apart. No folder holds two hosts of one name (#351),
so a folder path and a name always tell two hosts apart.

Pure: the hosts are an argument. They are the configuration's, not the open tabs', so
that a tab's name does not change as other tabs open and close.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable


def tab_name(host: Any, hosts: Iterable[Any]) -> str:
    """The name of `host`'s tab among `hosts`, each read for its `.group` and `.name`.

    `host` need not be one of `hosts`: a tab outlives its host, and the Local console has
    none in the configuration. Each host gets only as many folders as it needs, so the
    folder of one that needs one is not lengthened for another that needs two.
    """
    name: str = host.name
    path = folders_of(host.group)
    others = [folders_of(other.group) for other in hosts if other.name == name]
    others = [other for other in others if other != path]
    if not others:
        return name
    # The fewest folders, counted from the host's own, that no other host's path ends
    # with. A path of fewer folders than that ends with none of them.
    for count in range(1, len(path)):
        if all(other[-count:] != path[-count:] for other in others):
            return "/".join([*path[-count:], name])
    # Else the whole path, which tells it apart too. Another host whose path ends with all
    # of it, as `y/x` does with `x`, has a longer one, and that tab shows more of it. A host
    # at the top level has no folder to show, and keeps its name.
    return "/".join([*path, name])


def folders_of(group: str) -> list[str]:
    """The folders of a host's path, outermost first, and none at the top level."""
    return [folder for folder in group.split("/") if folder]
