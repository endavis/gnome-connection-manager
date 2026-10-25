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

What a tab is named before any of this is a template, Preferences' Tab name (#348): the
host's values filled into it, as a host's commands take them, `{name}` until changed. The
folders go in front of what the template gives, where it gives two hosts in two folders
the same name, so a template that tells hosts apart, as `{group}/{name}` does, gets none.
Two hosts in one folder that the template names alike stay alike: no folder of theirs can
tell them apart, and #347's path, beside the name, still does.

Pure: the hosts and the template are arguments. The hosts are the configuration's, not the
open tabs', so that a tab's name does not change as other tabs open and close.

Where there is room, beside the tab's name, goes the host's whole place in the folder tree,
`whole_path` (#347): in the tab's tooltip, the open-console list and the cluster window.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from gnome_connection_manager.utils import placeholders

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

# The template a tab is named by until Preferences says otherwise: its host's name.
NAME = "{name}"


def tab_name(host: Any, hosts: Iterable[Any], template: str = NAME) -> str:
    """The name of `host`'s tab among `hosts`, each read for its `.group` and the values
    `template` names, as `namer` reads them."""
    return namer(hosts, template)(host)


def namer(hosts: Iterable[Any], template: str = NAME) -> Callable[[Any], str]:
    """What names a host's tab among `hosts`, for naming many tabs at once: each of `hosts`
    is read, and named by `template`, once, here, rather than once for every tab.

    The host it is given need not be one of `hosts`: a tab outlives its host, and the Local
    console has none in the configuration. Each host gets only as many folders as it needs,
    so the folder of one that needs one is not lengthened for another that needs two.
    """
    named = [(templated(other, template), folders_of(other.group)) for other in hosts]

    def name_of(host: Any) -> str:
        name = templated(host, template)
        path = folders_of(host.group)
        others = [folders for each, folders in named if each == name and folders != path]
        if not others:
            return name
        # The fewest folders, counted from the host's own, that no other host's path ends
        # with. A path of fewer folders than that ends with none of them.
        for count in range(1, len(path)):
            if all(other[-count:] != path[-count:] for other in others):
                return "/".join([*path[-count:], name])
        # Else the whole path, which tells it apart too. Another host whose path ends with
        # all of it, as `y/x` does with `x`, has a longer one, and that tab shows more of it.
        # A host at the top level has no folder to show, and keeps its name.
        return "/".join([*path, name])

    return name_of


def templated(host: Any, template: str) -> str:
    """`template` filled with `host`'s values, and anything else in it kept as written. Where
    that leaves nothing but spaces, as `{folder}` does at the top level, the host's name."""
    filled = placeholders.fill(template, placeholders.host_values(host)).strip()
    return filled or str(host.name)


def whole_path(host: Any) -> str:
    """`host`'s folders and its name, outermost first: `1. Projects/pyproject-template/ansible`,
    and the name alone at the top level (#347)."""
    return "/".join([*folders_of(host.group), host.name])


def folders_of(group: str) -> list[str]:
    """The folders of a host's path, outermost first, and none at the top level."""
    return [folder for folder in group.split("/") if folder]
