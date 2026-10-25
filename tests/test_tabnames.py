"""Tests for utils/tabnames.py: a tab named with its folder where another host has its
host's name (#346)."""

from __future__ import annotations

import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

from gnome_connection_manager.utils import tabnames
from tests.test_connections import glib_complaints


def at(path):
    """A host at `path`, its folder path and then its name."""
    group, _, name = path.rpartition("/")
    return types.SimpleNamespace(group=group, name=name)


def names(*paths):
    """The tab name of each host at `paths`, among them all."""
    hosts = [at(path) for path in paths]
    return [tabnames.tab_name(host, hosts) for host in hosts]


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
    assert shown(tab) == ("infrafoundry/ansible",) * 3

    configure(app_module, monkeypatch, infra)
    wmain.name_tabs()
    assert shown(tab) == ("ansible",) * 3


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

    assert shown(tab) == ("deploys",) * 3


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
    assert drawn() == [(name, name, name) for name in expected], drawn()
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
