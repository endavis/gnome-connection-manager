"""Tests for utils/tabnames.py: a tab named with its folder where another host has its
host's name (#346), its host's whole path where there is room for it (#347), named by
Preferences' Tab name, a template of the host's values (#348), or by a tab name of its
host's own (#349)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

from gnome_connection_manager.utils import tabnames
from tests.test_connections import glib_complaints
from tests.test_console_window import _private_display


def at(path, **values):
    """A host at `path`, its folder path and then its name, with the other values a
    template can name (#348), and no tab name of its own (#349)."""
    group, _, name = path.rpartition("/")
    values = {
        "host": "10.0.0.5",
        "port": "22",
        "user": "ops",
        "type": "ssh",
        "tab_name": "",
        **values,
    }
    return types.SimpleNamespace(group=group, name=name, **values)


def names(*paths, template=tabnames.NAME):
    """The tab name of each host at `paths`, among them all."""
    hosts = [at(path) for path in paths]
    return [tabnames.tab_name(host, hosts, template) for host in hosts]


def test_a_name_no_other_host_has_is_the_tab_name():
    assert names("infrafoundry/ansible", "pyproject-template/terraform") == [
        "ansible",
        "terraform",
    ]


def test_two_hosts_of_one_name_are_named_with_the_folder_that_tells_them_apart():
    assert names("1. Projects/infrafoundry/ansible", "1. Projects/pyproject-template/ansible") == [
        "infrafoundry/ansible",
        "pyproject-template/ansible",
    ]


def test_folders_of_one_name_take_the_folder_above_them_too():
    assert names("A/x/ansible", "B/x/ansible") == ["A/x/ansible", "B/x/ansible"]
    assert names("top/A/x/ansible", "top/B/x/ansible") == ["A/x/ansible", "B/x/ansible"]


def test_a_host_at_the_top_level_keeps_its_name():
    assert names("ansible", "infrafoundry/ansible") == ["ansible", "infrafoundry/ansible"]


def test_a_path_another_ends_with_is_shown_whole():
    assert names("x/ansible", "y/x/ansible") == ["x/ansible", "y/x/ansible"]
    assert names("ops/x/ansible", "lab/ops/x/ansible") == ["ops/x/ansible", "lab/ops/x/ansible"]


def test_each_host_gets_only_the_folders_it_needs():
    assert names("A/x/ansible", "B/x/ansible", "C/y/ansible") == [
        "A/x/ansible",
        "B/x/ansible",
        "y/ansible",
    ]


def test_another_name_in_another_folder_is_no_collision():
    assert names("A/x/ansible", "B/x/terraform", "B/x/ansible") == [
        "A/x/ansible",
        "terraform",
        "B/x/ansible",
    ]


def test_names_are_compared_exactly():
    assert names("infra/Ansible", "lab/ansible") == ["Ansible", "ansible"]


def test_a_host_not_among_the_hosts_is_named_against_them():
    """A tab outlives its host, and the Local console has none in the configuration."""
    hosts = [at("pyproject-template/ansible"), at("lab/web")]

    assert tabnames.tab_name(at("infrafoundry/ansible"), hosts) == "infrafoundry/ansible"
    assert tabnames.tab_name(at("local"), hosts) == "local"
    assert tabnames.tab_name(at("web"), hosts) == "web"


def test_the_hosts_are_read_once():
    hosts = [at("a/b/ansible"), at("c/d/ansible")]

    assert tabnames.tab_name(hosts[0], iter(hosts)) == "b/ansible"


@pytest.mark.parametrize(
    ("group", "folders"),
    [("", []), ("ops", ["ops"]), ("1. Projects/infra foundry", ["1. Projects", "infra foundry"])],
)
def test_the_folders_of_a_path(group, folders):
    assert tabnames.folders_of(group) == folders


@pytest.mark.parametrize(
    ("path", "whole"),
    [
        ("router", "router"),
        ("1. Projects/pyproject-template/ansible", "1. Projects/pyproject-template/ansible"),
        ("/lab//x/web", "lab/x/web"),
    ],
)
def test_the_whole_path_of_a_host(path, whole):
    """Its folders and its name (#347), and the name alone at the top level."""
    assert tabnames.whole_path(at(path)) == whole


# -- named by a template (#348) ---------------------------------------------------------


@pytest.mark.parametrize(
    ("template", "name"),
    [
        ("{name}", "ansible"),
        ("{address}", "10.0.0.5"),
        ("{port}", "22"),
        ("{user}", "ops"),
        ("{group}", "1. Projects/infrafoundry"),
        ("{folder}", "infrafoundry"),
        ("{type}", "ssh"),
        ("[{type}] {name}", "[ssh] ansible"),
        ("{user}@{address}:{port}", "ops@10.0.0.5:22"),
        ("{name} {password} {?Label} {}", "ansible {password} {?Label} {}"),
    ],
)
def test_each_placeholder_names_a_tab_and_the_rest_is_kept(template, name):
    assert names("1. Projects/infrafoundry/ansible", template=template) == [name]


@pytest.mark.parametrize("template", ["", "   ", "{folder}", " {folder} ", "{user}"])
def test_a_template_that_gives_nothing_names_the_tab_after_its_host(template):
    """`{folder}` is empty at the top level, and a host may have no user."""
    host = at("ansible", user="")

    assert tabnames.tab_name(host, [host], template) == "ansible"


def test_spaces_around_what_a_template_gives_are_dropped():
    """The label pads the name itself, so spaces there only widen the tab."""
    assert names("lab/ansible", template="  {folder}: {name}  ") == ["lab: ansible"]


def test_what_the_template_gives_takes_the_folders_that_tell_it_apart():
    """#346's prefix, on what the template gives rather than on the hosts' names."""
    assert names("infrafoundry/ansible", "pyproject-template/terraform", template="{type}") == [
        "infrafoundry/ssh",
        "pyproject-template/ssh",
    ]
    # Their folders are both x, so the template names them alike.
    assert names("A/x/ansible", "B/x/ansible", template="{folder}: {name}") == [
        "A/x/x: ansible",
        "B/x/x: ansible",
    ]


def test_a_template_that_tells_the_hosts_apart_gets_no_folder():
    assert names(
        "infrafoundry/ansible", "pyproject-template/ansible", template="{group}/{name}"
    ) == ["infrafoundry/ansible", "pyproject-template/ansible"]
    assert names("A/x/ansible", "B/y/ansible", template="{folder}: {name}") == [
        "x: ansible",
        "y: ansible",
    ]


def test_hosts_of_one_folder_that_the_template_names_alike_stay_alike():
    """No folder of theirs tells them apart; #347's path, beside the name, does."""
    assert names("lab/web", "lab/db", "ops/web", template="{type}") == [
        "lab/ssh",
        "lab/ssh",
        "ops/ssh",
    ]


def test_the_namer_names_each_host_once_and_each_tab_from_that(monkeypatch):
    """Naming 50 tabs among 1000 hosts took 58 ms with the template filled again for every
    tab, measured, and 2 ms with the namer, which fills it once for each host."""
    hosts = [at(f"lab{i}/web") for i in range(20)]
    filled = []
    fill = tabnames.placeholders.fill
    monkeypatch.setattr(
        tabnames.placeholders, "fill", lambda *args: filled.append(args[0]) or fill(*args)
    )

    name = tabnames.namer(iter(hosts), "[{type}] {name}")
    named = [name(host) for host in hosts[:5]]

    assert named == [f"lab{i}/[ssh] web" for i in range(5)]
    assert len(filled) == 20 + 5


def test_by_default_a_tab_is_named_as_before():
    """An existing configuration has no template, and names its tabs by name (#346)."""
    assert tabnames.NAME == "{name}"
    assert names("1. Projects/infrafoundry/ansible", "lab/ansible", "web") == [
        "infrafoundry/ansible",
        "lab/ansible",
        "web",
    ]


# -- a host's own tab name (#349) -------------------------------------------------------


def named_among(*hosts, template=tabnames.NAME):
    """The tab name of each of `hosts`, among them all."""
    return [tabnames.tab_name(host, hosts, template) for host in hosts]


def test_a_hosts_own_tab_name_names_its_tab_in_place_of_the_template():
    """With the host's values filled in, as the template's are. A host without one is
    named by the template, as before."""
    own = at("lab/ansible", tab_name="tpl {name} ({user}@{folder})")
    plain = at("lab/web")

    assert named_among(own, plain, template="[{type}] {name}") == [
        "tpl ansible (ops@lab)",
        "[ssh] web",
    ]


def test_an_own_tab_name_gets_no_folder_where_another_tab_reads_the_same():
    """It was chosen. The other host's tab, which would read as it does, takes its folder."""
    chosen = at("infrafoundry/ansible", tab_name="{name}")

    assert named_among(chosen, at("pyproject-template/ansible")) == [
        "ansible",
        "pyproject-template/ansible",
    ]


def test_a_tab_that_would_read_as_another_hosts_own_tab_name_takes_its_folder():
    """What the other tabs read is compared, not the hosts' names: `db` is web's tab."""
    assert named_among(at("lab/web", tab_name="db"), at("ops/db")) == ["db", "ops/db"]


def test_a_tab_whose_host_another_host_names_otherwise_needs_no_folder():
    """Once one of two hosts of one name has a tab name of its own, the other's tab no
    longer reads as its tab, and keeps its name alone."""
    assert named_among(at("infrafoundry/ansible", tab_name="tpl"), at("lab/ansible")) == [
        "tpl",
        "ansible",
    ]


def test_own_tab_names_alike_stay_as_chosen():
    assert named_among(at("x/one", tab_name="db"), at("y/two", tab_name="db")) == ["db", "db"]


@pytest.mark.parametrize("own", ["   ", "{user}", " {user} "])
def test_an_own_tab_name_that_gives_nothing_leaves_the_template_naming_the_tab(own):
    """As if there were none: the template names the tab, and its folder goes in front
    where another host's tab reads the same."""
    host = at("infrafoundry/ansible", user="", tab_name=own)

    assert named_among(host, at("lab/ansible")) == ["infrafoundry/ansible", "lab/ansible"]


def test_spaces_around_what_an_own_tab_name_gives_are_dropped():
    """As around what the template gives: the label pads the name itself."""
    assert named_among(at("lab/web", tab_name="  {name} db  ")) == ["web db"]


# -- the tabs GCM names (#346) ----------------------------------------------------------


class Notebook:
    """What name_tabs and title_windows read of a console notebook: its tabs' labels."""

    def __init__(self, *labels, current=0):
        self.labels = list(labels)
        self.current = current

    def get_n_pages(self):
        return len(self.labels)

    def get_nth_page(self, position):
        return position

    def get_tab_label(self, page):
        return self.labels[page]

    def get_current_page(self):
        return self.current if self.labels else -1


def configure(app_module, monkeypatch, *hosts):
    """`hosts` as the configuration holds them, each in the folder its path names."""
    groups: dict = {}
    for host in hosts:
        groups.setdefault(host.group, []).append(host)
    monkeypatch.setattr(app_module, "groups", groups)


def host_at(app_module, path):
    group, _, name = path.rpartition("/")
    return app_module.Host(group, name)


def tab_for(app_module, host, name=None):
    """A tab opened for `host` when its name was `name`, its host's name if not given."""
    from tests.test_wmain import _tab_label

    tab = _tab_label(app_module, f"  {name or host.name}  ")
    tab.host = host
    return tab


def window_with(app_module, *notebooks, console_windows=()):
    """A main window holding `notebooks`, the first its pane in use, and `console_windows`."""
    wmain = object.__new__(app_module.Wmain)
    wmain.count = sum(notebook.get_n_pages() for notebook in notebooks)
    wmain.console_windows = console_windows
    wmain.console_notebooks = lambda: [*notebooks, *(each.notebook for each in console_windows)]
    wmain.main_notebook = lambda: notebooks[0]
    wmain.titles = []
    wmain.wMain = types.SimpleNamespace(set_title=wmain.titles.append)
    return wmain


def shown(tab):
    """What the tab is called: its identity, what it draws, and its tooltip."""
    return (tab.get_text().strip(), tab.label.get_text().strip(), tab.tooltips[-1])


def test_a_tab_takes_its_folder_once_another_host_has_its_name(app_module, monkeypatch):
    infra = host_at(app_module, "1. Projects/infrafoundry/ansible")
    other = host_at(app_module, "1. Projects/pyproject-template/ansible")
    tab = tab_for(app_module, infra)
    wmain = window_with(app_module, Notebook(tab))

    configure(app_module, monkeypatch, infra, other)
    wmain.name_tabs()
    assert shown(tab) == (
        "infrafoundry/ansible",
        "infrafoundry/ansible",
        "infrafoundry/ansible\n1. Projects/infrafoundry/ansible",
    )

    configure(app_module, monkeypatch, infra)
    wmain.name_tabs()
    assert shown(tab) == ("ansible", "ansible", "ansible\n1. Projects/infrafoundry/ansible")


def test_a_tab_follows_another_host_of_its_name_being_renamed_or_moved(app_module, monkeypatch):
    first = host_at(app_module, "A/x/ansible")
    second = host_at(app_module, "B/x/ansible")
    tab = tab_for(app_module, first, "A/x/ansible")
    wmain = window_with(app_module, Notebook(tab))

    moved = host_at(app_module, "C/ansible")
    moved.id = second.id
    configure(app_module, monkeypatch, first, moved)
    wmain.name_tabs()
    assert shown(tab)[0] == "x/ansible"

    renamed = host_at(app_module, "C/terraform")
    renamed.id = second.id
    configure(app_module, monkeypatch, first, renamed)
    wmain.name_tabs()
    assert shown(tab)[0] == "ansible"


def test_a_tab_follows_its_own_host_through_the_host_dialog(app_module, monkeypatch):
    """The dialog builds a new record for the host it edits, which keeps the id."""
    infra = host_at(app_module, "1. Projects/infrafoundry/ansible")
    other = host_at(app_module, "1. Projects/pyproject-template/ansible")
    tab = tab_for(app_module, infra, "infrafoundry/ansible")
    wmain = window_with(app_module, Notebook(tab))

    edited = host_at(app_module, "1. Projects/infrafoundry/ansible-old")
    edited.id = infra.id
    configure(app_module, monkeypatch, edited, other)
    wmain.name_tabs()
    assert shown(tab)[0] == "ansible-old"

    moved = host_at(app_module, "lab/ansible")
    moved.id = infra.id
    configure(app_module, monkeypatch, moved, other)
    wmain.name_tabs()
    assert shown(tab)[0] == "lab/ansible"


def test_a_tab_renamed_by_hand_keeps_its_name(app_module, monkeypatch):
    infra = host_at(app_module, "1. Projects/infrafoundry/ansible")
    tab = tab_for(app_module, infra)
    tab.rename("deploys")
    wmain = window_with(app_module, Notebook(tab))

    configure(app_module, monkeypatch, infra, host_at(app_module, "lab/ansible"))
    wmain.name_tabs()

    assert shown(tab) == ("deploys", "deploys", "deploys\n1. Projects/infrafoundry/ansible")


def test_a_tab_whose_host_is_not_configured_is_named_against_those_that_are(
    app_module, monkeypatch
):
    """A host deleted with its tab open, and the Local console, which has none."""
    gone = host_at(app_module, "1. Projects/infrafoundry/ansible")
    other = host_at(app_module, "1. Projects/pyproject-template/ansible")
    local = app_module.Host("", "local")
    tabs = [tab_for(app_module, gone), tab_for(app_module, other), tab_for(app_module, local)]
    wmain = window_with(app_module, Notebook(*tabs))

    configure(app_module, monkeypatch, other, host_at(app_module, "lab/local"))
    wmain.name_tabs()

    assert [shown(tab)[0] for tab in tabs] == ["infrafoundry/ansible", "ansible", "local"]


def test_a_tab_opened_for_no_host_is_left_alone(app_module, monkeypatch):
    """A plain label, as the glade's placeholder pages have (#41), and a page of no host."""
    from tests.test_wmain import PlainTabLabel

    page = tab_for(app_module, None, "notes")
    wmain = window_with(app_module, Notebook(PlainTabLabel(), page))
    configure(app_module, monkeypatch, host_at(app_module, "lab/notes"))

    wmain.name_tabs()

    assert page.get_text() == "  notes  "
    assert page.tooltips == []


def test_nothing_is_named_while_no_console_is_open(app_module, monkeypatch):
    """As the window is built, and as tests build one: there are no notebooks to ask."""
    wmain = object.__new__(app_module.Wmain)

    def ask():
        raise AssertionError("asked for the notebooks")

    wmain.console_notebooks = ask

    wmain.name_tabs()


def test_drawing_the_tree_names_the_tabs(app_module, monkeypatch):
    """Every change to the hosts redraws the tree, which is why the naming is there."""
    from tests.test_wmain import make_wmain_for_tree

    infra = host_at(app_module, "1. Projects/infrafoundry/ansible")
    other = host_at(app_module, "1. Projects/pyproject-template/ansible")
    tab = tab_for(app_module, infra)
    wmain = make_wmain_for_tree(app_module, monkeypatch, {infra.group: [infra]})
    wmain.updateTree()
    app_module.groups[other.group] = [other]
    monkeypatch.setattr(app_module.conf, "UPDATE_TITLE", False)
    wmain.count = 1
    wmain.console_notebooks = lambda: [Notebook(tab)]

    wmain.updateTree()

    assert shown(tab)[0] == "infrafoundry/ansible"


@pytest.mark.parametrize("dynamic", [True, False])
def test_the_window_titles_follow_and_keep_the_tabs_mark(app_module, monkeypatch, dynamic):
    monkeypatch.setattr(app_module.conf, "UPDATE_TITLE", dynamic)
    monkeypatch.setattr(app_module.conf, "APP_TITLE", "GCM")
    infra = host_at(app_module, "1. Projects/infrafoundry/ansible")
    other = host_at(app_module, "1. Projects/pyproject-template/ansible")
    shell = tab_for(app_module, app_module.Host("", "shell"))
    main = Notebook(shell, tab_for(app_module, infra), current=1)
    console_titles: list = []
    console_window = types.SimpleNamespace(
        notebook=Notebook(tab_for(app_module, other)), set_title=console_titles.append
    )
    wmain = window_with(app_module, main, console_windows=(console_window,))

    def clear(_page):
        raise AssertionError("cleared a tab's mark")

    wmain.clear_tab_attention = clear
    configure(app_module, monkeypatch, infra, other)

    wmain.name_tabs()

    assert wmain.titles == (["GCM - infrafoundry/ansible"] if dynamic else [])
    assert console_titles == ["GCM - pyproject-template/ansible"]


def test_a_window_showing_no_tab_is_titled_gcm(app_module, monkeypatch):
    monkeypatch.setattr(app_module.conf, "UPDATE_TITLE", True)
    monkeypatch.setattr(app_module.conf, "APP_TITLE", "")
    wmain = window_with(app_module, Notebook())
    wmain.console_notebooks = lambda: []

    wmain.title_windows()

    assert wmain.titles == [app_module.app_name]


class ClusterWindow:
    def __init__(self, consoles, visible=True):
        self.consoles = consoles
        self.visible = visible

    def get_property(self, name):
        assert name == "visible"
        return self.visible


@pytest.mark.parametrize("visible", [True, False])
def test_an_open_cluster_window_lists_the_consoles_by_their_names(app_module, monkeypatch, visible):
    infra = host_at(app_module, "1. Projects/infrafoundry/ansible")
    other = host_at(app_module, "1. Projects/pyproject-template/ansible")
    tabs = {"one": tab_for(app_module, infra), "two": tab_for(app_module, other)}
    rows = [[False, "  ansible  ", "one"], [True, "  ansible  ", "two"], [False, "  x  ", "shut"]]
    wmain = window_with(app_module, Notebook(*tabs.values()))
    wmain.wCluster = ClusterWindow(rows, visible)
    wmain.get_tab_label_for_terminal = tabs.get
    configure(app_module, monkeypatch, infra, other)

    wmain.name_tabs()

    if visible:
        assert rows == [
            [False, "  infrafoundry/ansible  ", "one"],
            [True, "  pyproject-template/ansible  ", "two"],
            [False, "  x  ", "shut"],
        ]
    else:
        assert [row[1] for row in rows] == ["  ansible  ", "  ansible  ", "  x  "]


def test_a_cluster_window_without_its_list_is_left_alone(app_module, monkeypatch):
    """Never opened, or one a test stands in for, which lists nothing to name again."""
    wmain = window_with(app_module, Notebook(tab_for(app_module, app_module.Host("", "a"))))
    configure(app_module, monkeypatch)

    wmain.name_tabs()
    wmain.wCluster = types.SimpleNamespace()
    wmain.name_tabs()


def test_a_tab_keeps_the_host_it_was_opened_for(app_module, monkeypatch):
    class Label:
        def __init__(self, title, notebook, page, popup):
            self.title = title

        def get_text(self):
            return self.title

        def set_name(self, name, path):
            self.named = (name, path)

        def set_color(self, color):
            self.color = color

    monkeypatch.setattr(app_module, "NotebookTabLabel", Label)
    host = host_at(app_module, "1. Projects/infrafoundry/ansible")
    wmain = object.__new__(app_module.Wmain)
    wmain.popupMenuTab = None
    notebook = types.SimpleNamespace(
        append_page=lambda page, tab_label: None,
        page_num=lambda page: 0,
        set_current_page=lambda position: None,
        set_tab_reorderable=lambda page, reorderable: None,
        set_tab_detachable=lambda page, detachable: None,
    )
    page = types.SimpleNamespace(show_all=lambda: None)

    tab = wmain.add_page(notebook, page, "infrafoundry/ansible", host)

    assert tab.host is host
    assert tab.get_text() == "  infrafoundry/ansible  "
    assert tab.named == ("infrafoundry/ansible", "1. Projects/infrafoundry/ansible")
    assert wmain.add_page(notebook, page, "notes").host is None


def test_a_page_of_another_kind_is_named_as_a_terminal_is(app_module, monkeypatch):
    """open_type_page, which opens a VNC host's desktop (#234). addTab's terminals are
    named against real GTK, below."""
    infra = host_at(app_module, "1. Projects/infrafoundry/ansible")
    configure(app_module, monkeypatch, infra, host_at(app_module, "lab/ansible"))
    opened = []
    wmain = object.__new__(app_module.Wmain)
    wmain.add_page = lambda notebook, page, title, host=None: opened.append((title, host))
    wmain.wMain = types.SimpleNamespace(set_focus=lambda widget: None)

    class Page:
        keyboard = None

        def __init__(self, host, ended):
            pass

        def connect(self, signal, handler):
            pass

        def open(self):
            pass

    wmain.open_type_page(None, infra, Page)

    assert opened == [("infrafoundry/ansible", infra)]


def test_a_tab_opened_for_an_old_record_is_named_after_the_host_with_its_id(
    app_module, monkeypatch
):
    """As a clone is, of a tab opened before its host was edited."""
    old = host_at(app_module, "1. Projects/pyproject-template/ansible")
    edited = host_at(app_module, "1. Projects/pyproject-template/ansible-old")
    edited.id = old.id
    configure(app_module, monkeypatch, edited, host_at(app_module, "1. Projects/infra/ansible"))

    assert app_module.host_tab_name(old) == "ansible-old"
    assert app_module.host_tab_name(app_module.Host("lab", "ansible")) == "lab/ansible"


class Terminal:
    """A terminal in its pane, in a notebook whose tab for it is `tab`."""

    def __init__(self, host, tab):
        self.host = host
        self.pane = types.SimpleNamespace(
            get_parent=lambda: types.SimpleNamespace(get_tab_label=lambda pane: tab)
        )

    def get_parent(self):
        return self.pane


@pytest.mark.parametrize("path", ["menu", "shortcut"])
def test_a_clone_of_a_tab_keeps_its_hosts_id(app_module, monkeypatch, path):
    """The same host in a second session: its tab is named, and follows, as the
    original's. Duplicate Host's copy is a second host, with an id of its own."""
    host = host_at(app_module, "1. Projects/infrafoundry/ansible")
    terminal = Terminal(host, tab_for(app_module, host))
    opened = []
    wmain = object.__new__(app_module.Wmain)
    wmain.addTab = lambda notebook, clone: opened.append(clone)
    if path == "menu":
        wmain.popupMenu = types.SimpleNamespace(terminal=terminal)
        app_module.Wmain.on_popupmenu(wmain, None, "CC2")
    else:
        monkeypatch.setattr(app_module, "shortcuts", {"CTRL+SHIFT+D": app_module._CLONE})
        monkeypatch.setattr(app_module, "get_key_name", lambda event: "CTRL+SHIFT+D")
        wmain.on_terminal_keypress(terminal, types.SimpleNamespace(keyval=0))

    [clone] = opened
    assert clone is not host
    assert (clone.id, clone.group, clone.name) == (host.id, host.group, host.name)


def test_a_tab_named_with_its_folder_logs_where_its_host_does(tmp_path, app_module, monkeypatch):
    """Session logs are named from the host's folder and name, never from its tab."""
    from tests.test_wmain import LoggingTerminal

    monkeypatch.setattr(app_module.conf, "LOG_PATH", str(tmp_path))
    monkeypatch.setattr(app_module.time, "strftime", lambda fmt: "20261025")
    infra = host_at(app_module, "1. Projects/infrafoundry/ansible")
    infra.user = "eric"
    configure(app_module, monkeypatch, infra, host_at(app_module, "lab/ansible"))
    assert app_module.host_tab_name(infra) == "infrafoundry/ansible"
    terminal = LoggingTerminal(infra)

    object.__new__(app_module.Wmain).set_terminal_logger(terminal)
    terminal.log.close()

    assert list(tmp_path.rglob("*.log")) == [
        tmp_path / "1. Projects" / "infrafoundry" / "ansible" / "eric-20261025-001.log"
    ]


# -- open tabs named by Preferences' Tab name (#348) -------------------------------------


def test_the_template_renames_the_open_tabs_but_not_one_renamed_by_hand(app_module, monkeypatch):
    infra = host_at(app_module, "1. Projects/infrafoundry/ansible")
    infra.user, infra.host = "eric", "10.0.0.5"
    web = host_at(app_module, "lab/web")
    tabs = [tab_for(app_module, infra), tab_for(app_module, web)]
    tabs[1].rename("deploys")
    wmain = window_with(app_module, Notebook(*tabs))
    configure(app_module, monkeypatch, infra, web)
    monkeypatch.setattr(app_module.conf, "UPDATE_TITLE", True)

    monkeypatch.setattr(app_module.conf, "TAB_NAME", "{user}@{address} ({folder})")
    wmain.name_tabs()

    assert [shown(tab) for tab in tabs] == [
        (
            "eric@10.0.0.5 (infrafoundry)",
            "eric@10.0.0.5 (infrafoundry)",
            "eric@10.0.0.5 (infrafoundry)\n1. Projects/infrafoundry/ansible",
        ),
        ("deploys", "deploys", "deploys\nlab/web"),
    ]
    assert wmain.titles[-1].endswith(" - eric@10.0.0.5 (infrafoundry)"), wmain.titles


def test_a_tab_is_opened_with_the_name_the_template_gives(app_module, monkeypatch):
    web = host_at(app_module, "lab/web")
    configure(app_module, monkeypatch, web)
    monkeypatch.setattr(app_module.conf, "TAB_NAME", "{folder}: {name}")

    assert app_module.host_tab_name(web) == "lab: web"


def test_the_local_console_keeps_its_name_whatever_the_template(app_module, monkeypatch):
    """Its values stand in for none: its type reads ssh, and it has no address. A clone of
    its tab keeps its id, as the clone paths give it. A host of the configuration named
    local is a host, and takes the template."""
    local = app_module.Host("", "local")
    clone = local.clone()
    clone.id = local.id
    configured = app_module.Host("", "local")
    configured.type = "command"
    tabs = [tab_for(app_module, each) for each in (local, clone, configured)]
    wmain = window_with(app_module, Notebook(*tabs))
    configure(app_module, monkeypatch, configured, host_at(app_module, "lab/local"))
    monkeypatch.setattr(app_module.conf, "TAB_NAME", "[{type}] {name}")

    wmain.name_tabs()

    assert [shown(tab)[0] for tab in tabs] == ["local", "local", "[command] local"]
    assert app_module.host_tab_name(local) == "local"


def test_a_deleted_hosts_tab_is_named_by_the_template_from_its_own_record(app_module, monkeypatch):
    """And against the hosts there are, so a host the template names alike puts the folder
    in front of what the template gives."""
    gone = host_at(app_module, "1. Projects/infrafoundry/ansible")
    tab = tab_for(app_module, gone)
    wmain = window_with(app_module, Notebook(tab))
    configure(app_module, monkeypatch, host_at(app_module, "lab/ansible"))
    monkeypatch.setattr(app_module.conf, "TAB_NAME", "[{type}] {name}")

    wmain.name_tabs()

    assert shown(tab)[0] == "infrafoundry/[ssh] ansible"


def test_an_empty_template_names_the_tabs_after_their_hosts(app_module, monkeypatch):
    infra = host_at(app_module, "1. Projects/infrafoundry/ansible")
    tab = tab_for(app_module, infra, "something else")
    wmain = window_with(app_module, Notebook(tab))
    configure(app_module, monkeypatch, infra, host_at(app_module, "lab/ansible"))
    monkeypatch.setattr(app_module.conf, "TAB_NAME", "")

    wmain.name_tabs()

    assert shown(tab)[0] == "infrafoundry/ansible"


def test_naming_the_tabs_fills_the_template_once_for_each_host(app_module, monkeypatch):
    """One namer for the whole pass, not one for each tab, which would fill every host's
    again for each."""
    hosts = [host_at(app_module, f"lab{i}/web") for i in range(10)]
    tabs = [tab_for(app_module, host) for host in hosts[:3]]
    wmain = window_with(app_module, Notebook(*tabs))
    configure(app_module, monkeypatch, *hosts)
    filled = []
    fill = app_module.tabnames.placeholders.fill
    monkeypatch.setattr(
        app_module.tabnames.placeholders, "fill", lambda *args: filled.append(1) or fill(*args)
    )

    wmain.name_tabs()

    assert [shown(tab)[0] for tab in tabs] == ["lab0/web", "lab1/web", "lab2/web"]
    assert len(filled) == 10 + 3


def test_a_tab_named_by_a_template_logs_where_its_host_does(tmp_path, app_module, monkeypatch):
    """Session logs are named from the host's folder and name, never from the template."""
    from tests.test_wmain import LoggingTerminal

    monkeypatch.setattr(app_module.conf, "LOG_PATH", str(tmp_path))
    monkeypatch.setattr(app_module.conf, "TAB_NAME", "[{type}] {user}@{folder}")
    monkeypatch.setattr(app_module.time, "strftime", lambda fmt: "20261025")
    infra = host_at(app_module, "1. Projects/infrafoundry/ansible")
    infra.user = "eric"
    configure(app_module, monkeypatch, infra)
    assert app_module.host_tab_name(infra) == "[ssh] eric@infrafoundry"
    terminal = LoggingTerminal(infra)

    object.__new__(app_module.Wmain).set_terminal_logger(terminal)
    terminal.log.close()

    assert list(tmp_path.rglob("*.log")) == [
        tmp_path / "1. Projects" / "infrafoundry" / "ansible" / "eric-20261025-001.log"
    ]


# -- open tabs named by a host's own tab name (#349) -------------------------------------


def edited(host, tab_name):
    """`host` as the host dialog saves it with `tab_name`: a new record, with its id."""
    record = host.clone()
    record.id = host.id
    record.tab_name = tab_name
    return record


def test_a_hosts_own_tab_name_renames_its_open_tabs_but_not_one_renamed_by_hand(
    app_module, monkeypatch
):
    """And without a folder in front, though another host has the host's name. Emptied,
    the template names its tabs again, folder and all."""
    infra = host_at(app_module, "1. Projects/infrafoundry/ansible")
    infra.user = "eric"
    lab = host_at(app_module, "lab/ansible")
    tabs = [tab_for(app_module, infra), tab_for(app_module, infra), tab_for(app_module, lab)]
    tabs[1].rename("deploys")
    wmain = window_with(app_module, Notebook(*tabs))
    monkeypatch.setattr(app_module.conf, "UPDATE_TITLE", True)
    monkeypatch.setattr(app_module.conf, "TAB_NAME", "[{type}] {name}")

    configure(app_module, monkeypatch, edited(infra, "tpl {name} ({user})"), lab)
    wmain.name_tabs()

    assert [shown(tab) for tab in tabs] == [
        (
            "tpl ansible (eric)",
            "tpl ansible (eric)",
            "tpl ansible (eric)\n1. Projects/infrafoundry/ansible",
        ),
        ("deploys", "deploys", "deploys\n1. Projects/infrafoundry/ansible"),
        ("[ssh] ansible", "[ssh] ansible", "[ssh] ansible\nlab/ansible"),
    ]
    assert wmain.titles[-1].endswith(" - tpl ansible (eric)"), wmain.titles

    configure(app_module, monkeypatch, edited(infra, ""), lab)
    wmain.name_tabs()

    assert [shown(tab)[0] for tab in tabs] == [
        "infrafoundry/[ssh] ansible",
        "deploys",
        "lab/[ssh] ansible",
    ]


def test_a_tab_is_opened_with_its_hosts_own_tab_name(app_module, monkeypatch):
    web = host_at(app_module, "lab/web")
    web.host = "10.0.0.5"
    web.tab_name = "web on {address}"
    configure(app_module, monkeypatch, web)
    monkeypatch.setattr(app_module.conf, "TAB_NAME", "[{type}] {name}")

    assert app_module.host_tab_name(web) == "web on 10.0.0.5"


def test_a_tab_named_by_its_hosts_own_tab_name_logs_where_its_host_does(
    tmp_path, app_module, monkeypatch
):
    """Session logs are named from the host's folder and name, never from its tab name."""
    from tests.test_wmain import LoggingTerminal

    monkeypatch.setattr(app_module.conf, "LOG_PATH", str(tmp_path))
    monkeypatch.setattr(app_module.time, "strftime", lambda fmt: "20261025")
    infra = host_at(app_module, "1. Projects/infrafoundry/ansible")
    infra.user = "eric"
    infra.tab_name = "tpl {user}"
    configure(app_module, monkeypatch, infra)
    assert app_module.host_tab_name(infra) == "tpl eric"
    terminal = LoggingTerminal(infra)

    object.__new__(app_module.Wmain).set_terminal_logger(terminal)
    terminal.log.close()

    assert list(tmp_path.rglob("*.log")) == [
        tmp_path / "1. Projects" / "infrafoundry" / "ansible" / "eric-20261025-001.log"
    ]


# -- the host's whole path beside the tab's name (#347) ----------------------------------


def test_a_tabs_tooltip_gives_its_hosts_whole_path(app_module, monkeypatch):
    infra = host_at(app_module, "1. Projects/infrafoundry/ansible")
    tab = tab_for(app_module, infra)
    wmain = window_with(app_module, Notebook(tab))
    configure(app_module, monkeypatch, infra)

    wmain.name_tabs()

    assert tab.tooltips[-1] == "ansible\n1. Projects/infrafoundry/ansible"
    assert tab.get_path() == "1. Projects/infrafoundry/ansible"


def test_the_path_goes_under_a_programs_title_too(app_module, monkeypatch):
    monkeypatch.setattr(app_module.conf, "TAB_TITLE_FROM_TERMINAL", 1)
    infra = host_at(app_module, "1. Projects/infrafoundry/ansible")
    tab = tab_for(app_module, infra)
    configure(app_module, monkeypatch, infra)
    window_with(app_module, Notebook(tab)).name_tabs()

    tab.set_terminal_title("htop")

    assert tab.tooltips[-1] == "ansible: htop\n1. Projects/infrafoundry/ansible"


def test_a_programs_title_is_no_reason_to_show_a_path(app_module, monkeypatch):
    """The path is weighed against the tab's name, not against its whole label."""
    monkeypatch.setattr(app_module.conf, "TAB_TITLE_FROM_TERMINAL", 1)
    router = app_module.Host("", "router")
    tab = tab_for(app_module, router)
    configure(app_module, monkeypatch, router)
    window_with(app_module, Notebook(tab)).name_tabs()

    tab.set_terminal_title("htop")

    assert tab.tooltips[-1] == "router: htop"
    assert tab.get_path() == ""


def test_a_host_at_the_top_level_and_the_local_console_show_no_path(app_module, monkeypatch):
    """Their path is the name their tabs bear, which said again would say nothing."""
    router = app_module.Host("", "router")
    local = app_module.Host("", "local")
    tabs = [tab_for(app_module, router), tab_for(app_module, local)]
    configure(app_module, monkeypatch, router)

    window_with(app_module, Notebook(*tabs)).name_tabs()

    assert [tab.tooltips[-1] for tab in tabs] == ["router", "local"]
    assert [tab.get_path() for tab in tabs] == ["", ""]


def test_a_name_that_is_its_whole_path_shows_no_path(app_module, monkeypatch):
    """As #346 names two hosts of one name, each in a folder at the top level."""
    first, second = host_at(app_module, "A/ansible"), host_at(app_module, "B/ansible")
    tabs = [tab_for(app_module, first), tab_for(app_module, second)]
    configure(app_module, monkeypatch, first, second)

    window_with(app_module, Notebook(*tabs)).name_tabs()

    assert [tab.tooltips[-1] for tab in tabs] == ["A/ansible", "B/ansible"]
    assert [tab.get_path() for tab in tabs] == ["", ""]


def test_a_tab_renamed_by_hand_shows_the_host_it_is_on(app_module, monkeypatch):
    """The rename hides the host, so its path shows, a name alone at the top level."""
    infra = host_at(app_module, "1. Projects/infrafoundry/ansible")
    router = app_module.Host("", "router")
    local = app_module.Host("", "local")
    tabs = [tab_for(app_module, host) for host in (infra, router, local)]
    for tab, name in zip(tabs, ("deploys", "core", "build"), strict=True):
        tab.rename(name)
    configure(app_module, monkeypatch, infra, router)

    window_with(app_module, Notebook(*tabs)).name_tabs()

    assert [tab.tooltips[-1] for tab in tabs] == [
        "deploys\n1. Projects/infrafoundry/ansible",
        "core\nrouter",
        "build\nlocal",
    ]


def test_renaming_a_tab_brings_its_hosts_path_to_the_tooltip(app_module):
    tab = tab_for(app_module, app_module.Host("", "router"))
    tab.set_name("router", "router")
    assert tab.tooltips[-1] == "router"

    tab.rename("core")

    assert tab.tooltips[-1] == "core\nrouter"


def test_the_path_follows_the_host(app_module, monkeypatch):
    """Moved to another folder, a host keeps its tab's name and gives it its new path,
    renamed by hand or not."""
    infra = host_at(app_module, "1. Projects/infrafoundry/ansible")
    tabs = [tab_for(app_module, infra), tab_for(app_module, infra)]
    tabs[1].rename("deploys")
    wmain = window_with(app_module, Notebook(*tabs))
    configure(app_module, monkeypatch, infra)
    wmain.name_tabs()

    moved = host_at(app_module, "2. Archive/ansible")
    moved.id = infra.id
    configure(app_module, monkeypatch, moved)
    wmain.name_tabs()

    assert [tab.tooltips[-1] for tab in tabs] == [
        "ansible\n2. Archive/ansible",
        "deploys\n2. Archive/ansible",
    ]


def test_a_tabs_path_is_that_of_the_host_with_its_id(app_module, monkeypatch):
    """The host dialog builds a new record for the host it edits, keeping the id. A host
    with none in the configuration gives its own."""
    old = host_at(app_module, "1. Projects/infrafoundry/ansible")
    moved = host_at(app_module, "lab/ansible")
    moved.id = old.id
    configure(app_module, monkeypatch, moved)

    assert app_module.host_path(old) == "lab/ansible"
    assert app_module.host_path(host_at(app_module, "gone/web")) == "gone/web"


def test_a_tab_opened_for_no_host_has_no_path(app_module):
    assert tab_for(app_module, None, "notes").get_path() == ""


def test_a_cluster_row_is_drawn_with_its_hosts_path(app_module, monkeypatch):
    """Under its name, each escaped, and the name alone for a row whose tab has gone."""
    from tests.test_console_list import escape

    monkeypatch.setattr(app_module.GLib, "markup_escape_text", escape, raising=False)
    tab = tab_for(app_module, host_at(app_module, "R&D/<lab>/web"))
    tab.set_name("web", "R&D/<lab>/web")
    wmain = types.SimpleNamespace(get_tab_label_for_terminal={"one": tab}.get)
    monkeypatch.setattr(app_module, "wMain", wmain, raising=False)
    model = {"first": [False, "  web  ", "one"], "second": [True, "  a&b  ", "gone"]}
    drawn = []
    cell = types.SimpleNamespace(set_property=lambda name, value: drawn.append((name, value)))

    cluster = object.__new__(app_module.Wcluster)
    cluster.draw_console(None, cell, model, "first")
    cluster.draw_console(None, cell, model, "second")

    assert drawn == [
        ("markup", "web\n<span size='small' alpha='60%'>R&amp;D/&lt;lab&gt;/web</span>"),
        ("markup", "a&amp;b"),
    ]


# What the stubs above cannot show: real tabs, drawn, and the windows and lists that name
# them. Each host has no address, so its tab is a local shell. HOME is a scratch folder,
# so this never reads a real gcm.conf.
_SCRIPT = r"""
import os, sys, tempfile, time
scenario = sys.argv[1]
os.environ["HOME"] = tempfile.mkdtemp(); os.environ["SHELL"] = "/bin/sh"; sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk
from pathlib import Path
from gnome_connection_manager import app

app.conf.CONFIRM_ON_CLOSE_TAB = 0
app.conf.STARTUP_LOCAL = False
app.conf.CHECK_UPDATES = False
app.conf.UPDATE_TITLE = 1
app.conf.APP_TITLE = "GCM"
logs = tempfile.mkdtemp()
app.conf.LOG_PATH = logs
app.wMain = w = app.Wmain(application=None)
application = app.GcmApplication()
application._controller = w
w.wMain.show_all()

def pump(seconds=0.3):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        Gtk.main_iteration_do(False)
        time.sleep(0.005)

def configure(*hosts):
    app.groups.clear()
    for host in hosts:
        app.groups.setdefault(host.group, []).append(host)
    w.updateTree()

def labels():
    notebook = w.nbConsole
    pages = [notebook.get_nth_page(i) for i in range(notebook.get_n_pages())]
    return [notebook.get_tab_label(page) for page in pages if hasattr(notebook.get_tab_label(page), "rename")]

def drawn():
    # What each tab draws, its tooltip, and its identity, which the dialogs read.
    return [
        (tab.label.get_text().strip(), tab.get_tooltip_text(), tab.get_text().strip())
        for tab in labels()
    ]

def names():
    return [tab.label.get_text().strip() for tab in labels()]

def listed():
    return [entry.text for _notebook, entries in w.open_console_groups() for entry in entries]

def cluster_rows():
    return [row[1].strip() for row in w.wCluster.consoles]

infra = app.Host("1. Projects/infrafoundry", "ansible")
infra.user, infra.log = "eric", True
other = app.Host("1. Projects/pyproject-template", "ansible")
web = app.Host("1. Projects/infrafoundry", "web")
configure(infra, other, web)
for host in (infra, other, web):
    w.addTab(w.nbConsole, host)
pump(0.5)

if scenario == "two-hosts-of-one-name":
    expected = ["infrafoundry/ansible", "pyproject-template/ansible", "web"]
    paths = [f"{host.group}/{host.name}" for host in (infra, other, web)]
    assert drawn() == [(name, f"{name}\n{path}", name) for name, path in zip(expected, paths)], drawn()
    assert w.wMain.get_title() == "GCM - web", w.wMain.get_title()
    assert listed() == expected, listed()
    w.on_btnCluster_clicked(None)
    pump()
    assert cluster_rows() == expected, cluster_rows()
    found = sorted(str(p.relative_to(logs)) for p in Path(logs).rglob("*.log"))
    day = time.strftime("%Y%m%d")
    assert found == ["1. Projects/infrafoundry/ansible/eric-%s-001.log" % day], found
    # The close confirmation and the rename dialog name the tab as it does.
    asked = []
    app.msgconfirm = lambda text: asked.append(text) or Gtk.ResponseType.CANCEL
    app.inputbox = lambda *args, **kwargs: asked.append(args[2])
    app.conf.CONFIRM_ON_CLOSE_TAB = 1
    labels()[0].on_close_tab(None, w.nbConsole)
    w.focus_console(w.nbConsole, w.nbConsole.get_nth_page(0))
    pump()
    application._on_action_console_rename(None, None)
    assert len(asked) == 2 and asked[0].endswith(" [infrafoundry/ansible]?"), asked
    assert asked[1] == "infrafoundry/ansible", asked
    assert names() == expected, names()

elif scenario == "the-names-follow-the-hosts":
    w.on_btnCluster_clicked(None)
    pump()
    w.focus_console(w.nbConsole, w.nbConsole.get_nth_page(1))
    pump()
    assert w.wMain.get_title() == "GCM - pyproject-template/ansible", w.wMain.get_title()
    # The host dialog builds a new record for the host it edits, keeping its id.
    edited = app.Host(other.group, "ansible-old")
    edited.id = other.id
    configure(infra, edited, web)
    pump()
    assert names() == ["ansible", "ansible-old", "web"], names()
    assert w.wMain.get_title() == "GCM - ansible-old", w.wMain.get_title()
    assert cluster_rows() == ["ansible", "ansible-old", "web"], cluster_rows()
    # A clone is named as its original, and follows it.
    application._on_action_console_clone(None, None)
    pump(0.5)
    assert names() == ["ansible", "ansible-old", "web", "ansible-old"], names()
    labels()[0].rename("deploys")
    configure(infra, other, web)
    pump()
    assert names() == ["deploys", "pyproject-template/ansible", "web", "pyproject-template/ansible"], names()
    # A console window's title names its tab, and follows it.
    w.toggle_console_window(w.nbConsole.get_nth_page(1))
    pump()
    [window] = w.console_windows
    assert window.get_title() == "GCM - pyproject-template/ansible", window.get_title()
    edited = app.Host(other.group, "ansible-new")
    edited.id = other.id
    configure(infra, edited, web)
    pump()
    assert window.get_title() == "GCM - ansible-new", window.get_title()
    assert names() == ["deploys", "web", "ansible-new"], names()

elif scenario == "the-paths-beside-the-names":
    # Real pointer motion, through XTest, on the scenario's own display.
    import ctypes
    x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
    xtst = ctypes.cdll.LoadLibrary("libXtst.so.6")
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XFlush.argtypes = [ctypes.c_void_p]
    xtst.XTestFakeMotionEvent.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong
    ]
    xtst.XTestFakeButtonEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
    display = x11.XOpenDisplay(None)

    def point(x, y):
        xtst.XTestFakeMotionEvent(display, -1, int(x), int(y), 0)
        x11.XFlush(display)

    def press(down):
        xtst.XTestFakeButtonEvent(display, 1, down, 0)
        x11.XFlush(display)

    def centre(widget):
        allocation = widget.get_allocation()
        _, x, y = widget.get_window().get_origin()
        return x + allocation.x + allocation.width // 2, y + allocation.y + allocation.height // 2

    def until(condition, seconds=5):
        end = time.monotonic() + seconds
        while time.monotonic() < end and not condition():
            pump(0.05)
        return condition()

    def walk(widget):
        found, pending = [], [widget]
        while pending:
            each = pending.pop()
            found.append(each)
            if isinstance(each, Gtk.Container):
                pending.extend(each.get_children())
        return found

    def tooltip():
        # The text of the tooltip on the screen, or None.
        for window in Gtk.Window.list_toplevels():
            if window.get_visible() and window.__gtype__.name == "GtkTooltipWindow":
                return [each.get_text() for each in walk(window) if isinstance(each, Gtk.Label)]
        return None

    def open_menu():
        for window in Gtk.Window.list_toplevels():
            menu = window.get_child() if window.get_visible() else None
            if isinstance(menu, Gtk.Menu) and menu.get_children():
                return menu
        return None

    router = app.Host("", "router")
    configure(infra, other, web, router)
    w.addTab(w.nbConsole, router)
    w.addTab(w.nbConsole, "local")
    pump(0.5)
    labels()[2].rename("deploys")
    pump()
    expected = [
        "infrafoundry/ansible\n1. Projects/infrafoundry/ansible",
        "pyproject-template/ansible\n1. Projects/pyproject-template/ansible",
        "deploys\n1. Projects/infrafoundry/web",
        "router",
        "local",
    ]

    # Each tab's tooltip, as GTK draws it once the pointer rests on the tab.
    shown = []
    for tab in labels():
        point(1900, 1060)
        assert until(lambda: tooltip() is None), tooltip()
        x, y = centre(tab.label)
        point(x, y)
        pump(0.1)
        point(x + 3, y)
        assert until(lambda: tooltip() is not None), "no tooltip over " + tab.get_text()
        shown.append(tooltip())
    assert shown == [[text] for text in expected], shown
    point(1900, 1060)
    pump()

    # The open-console list, opened as a click on the button at the end of the tab strip
    # opens it: each row's text as drawn, its lines, and its height.
    point(*centre(w.nbConsole.get_action_widget(Gtk.PackType.END)))
    pump(0.1)
    press(True)
    pump(0.1)
    press(False)
    assert until(lambda: open_menu() is not None), "the open-console list did not open"
    pump(0.3)
    rows = [item for item in open_menu().get_children() if isinstance(item, Gtk.CheckMenuItem)]
    texts = [row.get_child().get_text() for row in rows]
    assert [text.split("\n")[0].split("] ")[-1] for text in texts] == [
        text.split("\n")[0] for text in expected
    ], texts
    assert [text.split("\n")[1:] for text in texts] == [
        text.split("\n")[1:] for text in expected
    ], texts
    lines = [row.get_child().get_layout().get_line_count() for row in rows]
    assert lines == [2, 2, 2, 1, 1], lines
    heights = [row.get_allocated_height() for row in rows]
    assert min(heights[:3]) > max(heights[3:]), heights
    open_menu().popdown()
    pump()

    # The cluster window's list, as each row is drawn, and its rows' heights.
    w.on_btnCluster_clicked(None)
    pump(0.5)
    [tree] = [each for each in walk(w.wCluster) if isinstance(each, Gtk.TreeView)]
    store, column = tree.get_model(), tree.get_column(1)

    def drawn_rows():
        texts = []
        for row in store:
            column.cell_set_cell_data(store, row.iter, False, False)
            texts.append(column.get_cells()[0].props.text)
        return texts

    assert drawn_rows() == expected, drawn_rows()
    heights = [tree.get_background_area(row.path, column).height for row in store]
    assert min(heights[:3]) > max(heights[3:]), heights

    # Moved to another folder, web's tab keeps its rename and takes the new path.
    moved = app.Host("2. Archive", "web")
    moved.id = web.id
    configure(infra, other, moved, router)
    pump()
    assert labels()[2].get_tooltip_text() == "deploys\n2. Archive/web", labels()[2].get_tooltip_text()
    assert drawn_rows()[2] == "deploys\n2. Archive/web", drawn_rows()

elif scenario == "the-template-names-the-tabs":
    # As gcm.conf gives them, since OK saves them: a hand-built Host leaves these None.
    for host in (infra, other, web):
        host.description = host.password = host.private_key = host.commands = ""
    w.addTab(w.nbConsole, "local")
    pump(0.5)
    labels()[2].rename("deploys")
    w.on_btnCluster_clicked(None)
    pump()
    w.focus_console(w.nbConsole, w.nbConsole.get_nth_page(0))
    pump()

    def tab_name_entry(prefs):
        # The entry Preferences drew for the setting.
        [entry] = [
            child for child in prefs.tblGeneral.get_children()
            if getattr(child, "field", None) == "conf.TAB_NAME"
        ]
        return entry

    prefs = app.Wconfig()
    entry = tab_name_entry(prefs)
    rows = [child.get_text() for child in prefs.tblGeneral.get_children() if isinstance(child, Gtk.Label)]
    assert app._("Tab name") in rows, rows
    assert entry.get_text() == "{name}", entry.get_text()
    assert "{folder}" in entry.get_tooltip_text(), entry.get_tooltip_text()
    entry.set_text("[{type}] {folder}/{name}")
    prefs.on_okbutton1_clicked(None)
    pump()
    expected = ["[ssh] infrafoundry/ansible", "[ssh] pyproject-template/ansible", "deploys", "local"]
    assert [tab.get_text().strip() for tab in labels()] == expected, drawn()
    # The cut at 30 characters takes what the template gives, as it takes a name.
    assert names() == [*expected[:1], "[ssh] pyproject-template/ansi…", *expected[2:]], names()
    assert listed() == expected, listed()
    assert cluster_rows() == expected, cluster_rows()
    assert w.wMain.get_title() == "GCM - [ssh] infrafoundry/ansible", w.wMain.get_title()
    saved = Path(app.CONFIG_FILE).read_text()
    assert "tab-name = [{type}] {folder}/{name}\n" in saved, saved

    # A tab opened now is named so too, and logs where its host does.
    w.addTab(w.nbConsole, infra)
    pump(0.5)
    assert names()[-1] == "[ssh] infrafoundry/ansible", names()
    day = time.strftime("%Y%m%d")
    found = sorted(str(p.relative_to(logs)) for p in Path(logs).rglob("*.log"))
    assert found == [
        "1. Projects/infrafoundry/ansible/eric-%s-00%d.log" % (day, number) for number in (1, 2)
    ], found

    # Emptied, the template names each tab after its host, as {name} does.
    prefs = app.Wconfig()
    tab_name_entry(prefs).set_text("")
    prefs.on_okbutton1_clicked(None)
    pump()
    assert [tab.get_text().strip() for tab in labels()] == [
        "infrafoundry/ansible", "pyproject-template/ansible", "deploys", "local", "infrafoundry/ansible"
    ], drawn()

elif scenario == "a-host-names-its-own-tabs":
    import configparser
    # As gcm.conf gives them, since OK saves them: a hand-built Host leaves these None.
    for host in (infra, other, web):
        host.description = host.password = host.private_key = host.commands = ""
    # And what the dialog shows of infra as text. A local host, which the dialog saves
    # with no address, and whose tabs open a shell, as an ssh host's with none do.
    infra.host, infra.port, infra.keep_alive, infra.type = "", "22", "0", "local"
    w.addTab(w.nbConsole, infra)
    pump(0.5)
    labels()[3].rename("deploys")
    w.on_btnCluster_clicked(None)
    pump()
    w.focus_console(w.nbConsole, w.nbConsole.get_nth_page(0))
    pump()

    def opened(host=None):
        dialog = app.Whost()
        dialog.init(host.group if host else "", host)
        dialog.get_widget("wHost").present()
        pump()
        return dialog, dialog.get_widget("txtTabName")

    def edit(host, tab_name):
        # Edit Host's dialog with the field typed into, and the record OK saves.
        dialog, field = opened(host)
        field.set_text(tab_name)
        dialog.on_okbutton1_clicked(None)
        pump()
        [record] = [each for each in app.groups[host.group] if each.id == host.id]
        return record

    def saved_tab_name(host):
        saved = configparser.RawConfigParser()
        saved.read(app.CONFIG_FILE)
        [section] = [name for name in saved.sections() if saved.get(name, "id", fallback="") == host.id]
        return saved.get(section, "tab-name", fallback=None)

    # On Properties, below the name, drawn and in use, with the placeholders in its tooltip.
    dialog, field = opened(infra)
    grid = field.get_parent()
    assert dialog.get_widget("txtName").get_parent() is grid
    row = grid.child_get_property(field, "top-attach")
    [label] = [
        child for child in grid.get_children()
        if grid.child_get_property(child, "top-attach") == row and child is not field
    ]
    assert label.get_text() == app._("Tab name"), label.get_text()
    assert row == grid.child_get_property(dialog.get_widget("txtName"), "top-attach") + 1
    assert field.get_mapped() and field.get_sensitive() and field.get_text() == ""
    assert "{folder}" in field.get_tooltip_text(), field.get_tooltip_text()
    dialog.get_widget("wHost").destroy()

    record = edit(infra, "tpl {name} ({user})")
    expected = ["tpl ansible (eric)", "ansible", "web", "deploys"]
    assert [tab.get_text().strip() for tab in labels()] == expected, drawn()
    assert names() == expected, names()
    assert listed() == expected, listed()
    assert cluster_rows() == expected, cluster_rows()
    assert w.wMain.get_title() == "GCM - tpl ansible (eric)", w.wMain.get_title()
    assert saved_tab_name(record) == "tpl {name} ({user})"
    # The dialog shows it again, and a tab opened now is named by it, and logs where its
    # host does.
    dialog, field = opened(record)
    assert field.get_text() == "tpl {name} ({user})", field.get_text()
    dialog.get_widget("wHost").destroy()
    w.addTab(w.nbConsole, record)
    pump(0.5)
    assert names()[-1] == "tpl ansible (eric)", names()
    day = time.strftime("%Y%m%d")
    found = sorted(str(p.relative_to(logs)) for p in Path(logs).rglob("*.log"))
    assert found == [
        "1. Projects/infrafoundry/ansible/eric-%s-00%d.log" % (day, number) for number in (1, 2, 3)
    ], found

    # A type that opens no tab greys it and clears it, and another brings it back.
    dialog, field = opened()
    field.set_text("tpl")
    dialog.cmbType.set_active_id("web")
    assert not field.get_sensitive() and field.get_text() == "", field.get_text()
    dialog.cmbType.set_active_id("ssh")
    assert field.get_sensitive()
    dialog.get_widget("wHost").destroy()

    # Emptied, the template names its tabs again, folders and all, and none is saved.
    record = edit(record, "")
    assert [tab.get_text().strip() for tab in labels()] == [
        "infrafoundry/ansible", "pyproject-template/ansible", "web", "deploys", "infrafoundry/ansible"
    ], drawn()
    assert saved_tab_name(record) is None

else:
    raise SystemExit("no scenario " + scenario)
print("OK")
"""


@pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"),
    reason="needs a display for a real terminal",
)
@pytest.mark.parametrize("scenario", ["two-hosts-of-one-name", "the-names-follow-the-hosts"])
def test_tabs_named_with_their_folders_against_real_gtk(scenario):
    pytest.importorskip("gi", reason="PyGObject not available")
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT, scenario],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        timeout=120,
    )

    assert result.returncode == 0, result.stderr[-3000:]
    assert "OK" in result.stdout
    assert not glib_complaints(result.stderr), result.stderr[-3000:]


@pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"),
    reason="needs a display for a real terminal",
)
def test_the_tab_name_template_against_real_gtk():
    """Preferences' Tab name, typed into the real dialog, names the open tabs, the window
    title and the cluster window's rows at OK, but neither a tab renamed by hand nor the
    Local console, and is saved; a tab opened afterwards logs where its host does (#348)."""
    pytest.importorskip("gi", reason="PyGObject not available")
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT, "the-template-names-the-tabs"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        timeout=120,
    )

    assert result.returncode == 0, result.stderr[-3000:]
    assert "OK" in result.stdout
    assert not glib_complaints(result.stderr), result.stderr[-3000:]


@pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"),
    reason="needs a display for a real terminal",
)
def test_a_hosts_own_tab_name_against_real_gtk():
    """A host's tab name, typed into the real host dialog, names its open tabs at OK, with
    no folder in front, but not a tab renamed by hand; it is saved and shown again, names a
    tab opened afterwards, which logs where its host does, and is greyed for a web host.
    Emptied, the template names the tabs again (#349)."""
    pytest.importorskip("gi", reason="PyGObject not available")
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT, "a-host-names-its-own-tabs"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        timeout=120,
    )

    assert result.returncode == 0, result.stderr[-3000:]
    assert "OK" in result.stdout
    assert not glib_complaints(result.stderr), result.stderr[-3000:]


@pytest.mark.skipif(shutil.which("Xvfb") is None, reason="needs Xvfb for a display of its own")
def test_the_paths_beside_the_names_against_real_gtk():
    """The tooltip, the open-console list and the cluster window, as drawn (#347). On a
    display of its own, since the pointer is real: on the one the other tests share,
    another worker's windows could be under it."""
    pytest.importorskip("gi", reason="PyGObject not available")
    process, display = _private_display()
    environment = dict(os.environ, DISPLAY=display, GDK_BACKEND="x11")
    for name in ("WAYLAND_DISPLAY", "GDK_SCALE", "GDK_DPI_SCALE", "XDG_CONFIG_HOME"):
        environment.pop(name, None)
    try:
        result = subprocess.run(
            [sys.executable, "-c", _SCRIPT, "the-paths-beside-the-names"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[1],
            env=environment,
            timeout=120,
        )
    finally:
        process.terminate()
        process.wait()

    assert result.returncode == 0, result.stderr[-3000:]
    assert "OK" in result.stdout
    assert not glib_complaints(result.stderr), result.stderr[-3000:]
