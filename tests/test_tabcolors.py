"""Tests for utils/tabcolors.py, and the tab colour GCM draws from it: a host's own or its
folder's, as a stripe across the top of the host's tabs (#350)."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import types
from pathlib import Path

import pytest

from gnome_connection_manager.utils import tabcolors
from gnome_connection_manager.utils.folders import ROOT, Folder, FolderTree
from gnome_connection_manager.utils.hosts import Host
from tests.test_connections import glib_complaints
from tests.test_tabnames import Notebook, configure, host_at, tab_for, window_with

STYLE = Path(__file__).resolve().parents[1] / "data" / "style.css"
RED, YELLOW, BLUE = "#e01b24", "#f6d32d", "#3584e4"


def tree_of(*records: tuple[str, str, str]) -> FolderTree:
    """A tree from (id, parent, colour) triples, each folder named after its id."""
    tree = FolderTree()
    for folder_id, parent, color in records:
        tree.folders[folder_id] = Folder(folder_id, folder_id, parent, tab_color=color)
    return tree


def filed(folder_id: str, color: str = "") -> Host:
    """A real Host in the folder `folder_id`, with `color` its own."""
    host = Host("", "router")
    host.folder = folder_id
    host.tab_color = color
    return host


@pytest.mark.parametrize(
    ("text", "color"),
    [(RED, RED), ("#E01B24", RED), ("  #e01b24\t", RED), ("#f00", "#ff0000"), ("#AbC", "#aabbcc")],
)
def test_a_colour_reads_as_six_digits_in_lower_case(text: str, color: str) -> None:
    assert tabcolors.color_of(text) == color


@pytest.mark.parametrize(
    "text",
    [
        "",
        "e01b24",
        "#e01b2",
        "#e01b244",
        "#e0",
        "#ggg",
        "# e01b24",
        "red",
        "rgb(224, 27, 36)",
        "#e01b24; }",
        "#e01b24\n* {",
    ],
)
def test_anything_else_is_no_colour(text: str) -> None:
    """A hand edit can leave anything, and none of it reaches the CSS a tab is drawn with."""
    assert tabcolors.color_of(text) == ""


def test_a_folder_gives_its_colour_to_the_hosts_in_it_and_below_it() -> None:
    tree = tree_of(("ops", ROOT, BLUE), ("infra", "ops", ""), ("db", "infra", ""))

    assert [tabcolors.tab_color(filed(each), tree) for each in ("ops", "infra", "db")] == [BLUE] * 3


def test_the_nearest_folder_with_a_colour_gives_it() -> None:
    tree = tree_of(("ops", ROOT, BLUE), ("infra", "ops", YELLOW), ("db", "infra", ""))

    assert [tabcolors.tab_color(filed(each), tree) for each in ("ops", "infra", "db")] == [
        BLUE,
        YELLOW,
        YELLOW,
    ]


def test_a_hosts_own_colour_wins_over_its_folders() -> None:
    tree = tree_of(("ops", ROOT, BLUE))

    assert tabcolors.tab_color(filed("ops", "#E01B24"), tree) == RED


def test_an_own_colour_that_cannot_be_read_leaves_the_folders() -> None:
    tree = tree_of(("ops", ROOT, BLUE))

    assert tabcolors.tab_color(filed("ops", "crimson"), tree) == BLUE


def test_a_folders_colour_that_cannot_be_read_leaves_the_one_above() -> None:
    tree = tree_of(("ops", ROOT, BLUE), ("infra", "ops", "#12345"))

    assert tabcolors.tab_color(filed("infra"), tree) == BLUE


@pytest.mark.parametrize("folder_id", ["infra", ROOT, "gone"])
def test_with_no_colour_above_it_a_host_has_none(folder_id: str) -> None:
    """In a folder without one, at the top level, or in a folder the tree does not have."""
    tree = tree_of(("ops", ROOT, ""), ("infra", "ops", ""))

    assert tabcolors.tab_color(filed(folder_id), tree) == ""


def test_a_cycle_in_a_tree_that_skipped_repair_does_not_hang() -> None:
    """On a thread of its own, so that a loop that never ends fails the test, rather than
    holding up the run."""
    tree = tree_of(("a", "b", ""), ("b", "a", ""))
    found: list[str] = []
    walk = threading.Thread(
        target=lambda: found.append(tabcolors.folder_color(tree, "a")), daemon=True
    )

    walk.start()
    walk.join(5)

    assert found == [""]


def test_a_tab_is_drawn_with_a_stripe_of_its_colour_that_takes_no_room() -> None:
    assert tabcolors.stripe_css("#E01B24") == (
        f"* {{ box-shadow: inset 0 {tabcolors.STRIPE}px {RED}; }}"
    )


@pytest.mark.parametrize("color", ["", "crimson", "#e01b24; } * { background: red"])
def test_a_tab_without_a_colour_is_given_no_css(color: str) -> None:
    assert tabcolors.stripe_css(color) == ""


def test_a_mark_on_a_coloured_tab_starts_below_the_stripe_with_a_gap() -> None:
    """data/style.css starts each mark tabcolors.GAP below the tabcolors.STRIPE the stripe
    takes, in the mark's own colour, so the two say the same."""
    css = STYLE.read_text()
    marks = dict(
        re.findall(r"tab box\.(selected|attention) \{\s*background-color: (#[0-9A-Fa-f]{6});", css)
    )
    starts = {
        found["mark"]: (int(found["start"]), found["color"])
        for found in re.finditer(
            r"tab box\.colored\.(?P<mark>selected|attention) \{[^}]*linear-gradient\(to bottom, "
            r"transparent (?P<start>\d+)px, (?P<color>#[0-9A-Fa-f]{6}) (?P=start)px\)",
            css,
        )
    }

    assert set(marks) == {"selected", "attention"}
    assert starts == {
        mark: (tabcolors.STRIPE + tabcolors.GAP, color) for mark, color in marks.items()
    }


# -- the tabs GCM draws (#350) -------------------------------------------------


class StyleContext:
    """What set_color uses of a tab's style context. The real one has each of these, as
    test_the_fakes_offer_only_what_gtk_has checks."""

    def __init__(self) -> None:
        self.classes: set[str] = set()
        self.providers: list[object] = []

    def add_class(self, name: str) -> None:
        self.classes.add(name)

    def remove_class(self, name: str) -> None:
        self.classes.discard(name)

    def add_provider(self, provider: object, priority: object) -> None:
        self.providers.append(provider)


class CssProvider:
    def __init__(self) -> None:
        self.css: str | None = None

    def load_from_data(self, data: bytes) -> None:
        self.css = data.decode()


def test_the_fakes_offer_only_what_gtk_has() -> None:
    gi = pytest.importorskip("gi", reason="PyGObject not available")
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    for fake, real in (
        (StyleContext, Gtk.StyleContext),
        (CssProvider, Gtk.CssProvider),
        (MenuItem, Gtk.MenuItem),
    ):
        for name in vars(fake):
            if not name.startswith("_"):
                assert hasattr(real, name), (real, name)


def colourable(app_module, monkeypatch, tab):
    """`tab`, a stand-in's label, with a style context to colour, and providers recorded."""
    context = StyleContext()
    tab.get_style_context = lambda: context
    monkeypatch.setattr(app_module.Gtk, "CssProvider", CssProvider, raising=False)
    return context


def drawn_colour(tab, context):
    """The colour a tab is marked with, as its style says: (CSS, whether `colored`)."""
    css = context.providers[-1].css if context.providers else None
    return css, "colored" in context.classes


def test_a_tab_never_given_a_colour_has_no_style_for_one(app_module, monkeypatch):
    """So it is drawn as tabs always were."""
    tab = tab_for(app_module, host_at(app_module, "ops/web"))
    context = colourable(app_module, monkeypatch, tab)

    tab.set_color("")
    tab.set_color("crimson")

    assert (tab.color, tab.color_style, context.providers, context.classes) == ("", None, [], set())


def test_a_tab_is_given_its_colour_and_loses_it(app_module, monkeypatch):
    tab = tab_for(app_module, host_at(app_module, "ops/web"))
    context = colourable(app_module, monkeypatch, tab)

    tab.set_color("#E01B24")
    assert drawn_colour(tab, context) == (tabcolors.stripe_css(RED), True)
    tab.set_color(BLUE)
    assert drawn_colour(tab, context) == (tabcolors.stripe_css(BLUE), True)
    tab.set_color("")
    assert drawn_colour(tab, context) == ("", False)

    # One style, made once and loaded again for each colour.
    assert len(context.providers) == 1
    assert tab.color == ""


def test_the_same_colour_again_changes_nothing(app_module, monkeypatch):
    """name_tabs gives every tab its colour at each redraw of the tree."""
    tab = tab_for(app_module, host_at(app_module, "ops/web"))
    context = colourable(app_module, monkeypatch, tab)
    tab.set_color(RED)
    loaded: list[bytes] = []
    context.providers[0].load_from_data = loaded.append

    tab.set_color("#E01B24")

    assert loaded == []


def test_a_host_and_its_folder_colour_its_tab(app_module, monkeypatch):
    infra = host_at(app_module, "ops/infra/ansible")
    web = host_at(app_module, "ops/web")
    configure(app_module, monkeypatch, infra, web)
    tree = FolderTree()
    monkeypatch.setattr(app_module, "folders", tree)
    app_module.sync_folders()
    tree.folders[tree.child_named(ROOT, "ops").id].tab_color = BLUE
    infra.tab_color = RED

    assert (app_module.host_tab_color(infra), app_module.host_tab_color(web)) == (RED, BLUE)


def test_a_tabs_colour_is_that_of_the_host_with_its_id(app_module, monkeypatch):
    """As its name is: the host dialog builds a new record for a host it edits, and a tab
    keeps the record it was opened for (#346)."""
    opened = host_at(app_module, "ops/web")
    edited = host_at(app_module, "ops/web")
    edited.id, edited.tab_color = opened.id, RED
    configure(app_module, monkeypatch, edited)
    monkeypatch.setattr(app_module, "folders", FolderTree())

    assert app_module.host_tab_color(opened) == RED
    assert app_module.host_tab_color(app_module.Host("", "local")) == ""


def test_naming_the_tabs_colours_them_as_their_hosts_and_folders_now_are(app_module, monkeypatch):
    """Through updateTree, so a host's dialog, a folder's colour and a move to another
    folder reach the open tabs. A tab renamed by hand keeps its host's colour."""
    infra = host_at(app_module, "ops/infra/ansible")
    web = host_at(app_module, "lab/web")
    tabs = [tab_for(app_module, infra), tab_for(app_module, web)]
    contexts = [colourable(app_module, monkeypatch, tab) for tab in tabs]
    tabs[1].rename("deploys")
    wmain = window_with(app_module, Notebook(*tabs))
    wmain.title_windows = wmain.name_cluster_consoles = lambda: None
    configure(app_module, monkeypatch, infra, web)
    tree = FolderTree()
    monkeypatch.setattr(app_module, "folders", tree)
    app_module.sync_folders()
    tree.folders[tree.child_named(ROOT, "ops").id].tab_color = BLUE

    wmain.name_tabs()
    assert [tab.color for tab in tabs] == [BLUE, ""]

    web.group, web.folder = "ops", ""
    app_module.sync_folders()
    wmain.name_tabs()
    assert [tab.color for tab in tabs] == [BLUE, BLUE]
    assert [tab.get_text().strip() for tab in tabs] == ["ansible", "deploys"]

    tree.folders[tree.child_named(ROOT, "ops").id].tab_color = ""
    wmain.name_tabs()
    assert [drawn_colour(tab, context) for tab, context in zip(tabs, contexts, strict=True)] == [
        ("", False),
        ("", False),
    ]


def test_a_tab_is_opened_with_its_hosts_colour(app_module, monkeypatch):
    class Label:
        def __init__(self, title, notebook, page, popup):
            self.title = title
            self.color = None

        def set_name(self, name, path):
            pass

        def set_color(self, color):
            self.color = color

    monkeypatch.setattr(app_module, "NotebookTabLabel", Label)
    web = host_at(app_module, "ops/web")
    web.tab_color = RED
    configure(app_module, monkeypatch, web)
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

    assert wmain.add_page(notebook, page, "web", web).color == RED
    assert wmain.add_page(notebook, page, "notes").color is None


# -- a folder's colour, from its menu (#350) ------------------------------------


def folder_window(app_module, monkeypatch, tree, folder_id):
    """A main window whose tree has the folder `folder_id` selected, or a host where it is
    None, and what it did: the redraws, the saves and the row selected again."""
    done: list[str] = []
    wmain = object.__new__(app_module.Wmain)
    wmain.window = object()
    wmain.updateTree = lambda: done.append("updateTree")
    wmain.writeConfig = lambda: done.append("writeConfig")
    wmain.select_folder_row = lambda selected: done.append(f"select {selected}")
    selected = object()
    wmain.treeServers = types.SimpleNamespace(
        get_selection=lambda: types.SimpleNamespace(get_selected=lambda: (None, selected))
    )
    wmain.is_folder_row = lambda _row: folder_id is not None
    wmain.folder_id_at = lambda _row: folder_id
    monkeypatch.setattr(app_module, "folders", tree)
    return wmain, done


@pytest.mark.parametrize(
    ("before", "chosen", "after", "saved"),
    [
        ("", RED, RED, True),
        (BLUE, RED, RED, True),
        (BLUE, "", "", True),
        (BLUE, None, BLUE, False),  # cancelled
        (BLUE, BLUE, BLUE, False),  # the same again
    ],
)
def test_a_folders_tab_colour_is_chosen_from_its_menu(
    app_module, monkeypatch, before, chosen, after, saved
):
    tree = tree_of(("ops", ROOT, before))
    asked = []

    def choose(current, parent=None):
        asked.append(current)
        return chosen

    monkeypatch.setattr(app_module, "choose_tab_color", choose)
    wmain, done = folder_window(app_module, monkeypatch, tree, "ops")

    wmain.color_selected_folder()

    assert asked == [before]
    assert tree.folders["ops"].tab_color == after
    assert done == (["updateTree", "writeConfig", "select ops"] if saved else [])


def test_a_hosts_row_has_no_folder_colour_to_choose(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "choose_tab_color", lambda *_args, **_kwargs: RED)
    wmain, done = folder_window(app_module, monkeypatch, tree_of(("ops", ROOT, "")), None)

    wmain.color_selected_folder()

    assert done == []


def test_both_menus_offer_a_folders_tab_colour(app_module):
    """The tree's menu for a folder row, as Rename Folder is, and Servers' folder section."""
    source = Path(app_module.__file__).read_text()
    tree_menu = source.split("self.popupMenuFolder = Gtk.Menu()", 1)[1]
    tree_menu = tree_menu.split("self.popupMenuTab = Gtk.Menu()", 1)[0]
    servers = source.split("folder_section = Gio.Menu()", 1)[1].split("servers_menu.append", 1)[0]

    assert "app.folder-tab-color" in re.findall(r'"(app\.[a-z-]+)"', tree_menu)
    assert '_("Tab Color"), "app.folder-tab-color"' in servers


class MenuItem:
    """What the tree's handler does with an item of its menu. A real Gtk.MenuItem does
    each of these, as test_the_fakes_offer_only_what_gtk_has checks."""

    def __init__(self) -> None:
        self.visible = True

    def show(self) -> None:
        self.visible = True

    def hide(self) -> None:
        self.visible = False


def test_the_tree_menu_offers_a_tab_colour_for_a_folders_row_alone(app_module):
    """As it offers Rename Folder: not for a host's row, nor for the space below the rows.
    One menu serves them all, so each right-click shows or hides the item again."""
    wmain = object.__new__(app_module.Wmain)
    items = ("mnuDel", "mnuEdit", "mnuCopyAddress", "mnuDup", "mnuRenameFolder", "mnuFolderColor")
    wmain.popupMenuFolder = types.SimpleNamespace(
        **{name: MenuItem() for name in items}, popup=lambda *_args: None
    )
    clicked: list[bool | None] = []
    wmain.treeServers = types.SimpleNamespace(
        get_path_at_pos=lambda x, y: None if clicked[-1] is None else ("path", "column", 0, 0),
        get_selection=lambda: types.SimpleNamespace(unselect_all=lambda: None),
        grab_focus=lambda: None,
        set_cursor=lambda *_args: None,
    )
    wmain.treeModel = types.SimpleNamespace(get_iter=lambda path: "row")
    wmain.is_folder_row = lambda row: clicked[-1]
    wmain.set_context_tree_path = lambda path: None
    wmain.prepare_files_items = lambda host: None
    wmain.get_selected_host = lambda: None
    press = app_module.Gdk.EventType.BUTTON_PRESS
    event = types.SimpleNamespace(type=press, button=3, x=4, y=4, time=0)
    menu = wmain.popupMenuFolder

    offered = []
    # A host's row, a folder's, the space below the rows, and a folder's again.
    for folder_row in (False, True, None, True):
        clicked.append(folder_row)
        assert wmain.on_tvServers_button_press_event(wmain.treeServers, event) is True
        offered.append((menu.mnuFolderColor.visible, menu.mnuRenameFolder.visible))

    assert offered == [(False, False), (True, True), (False, False), (True, True)]


# The real tabs, drawn: their pixels, read from an image each is drawn into rather than
# from the screen, where another test's window may cover it. Each host has no address, so
# its tab is a local shell. HOME is a scratch folder, so this never reads a real gcm.conf.
_SCRIPT = r"""
import configparser, os, sys, tempfile, time
scenario = sys.argv[1]
os.environ["HOME"] = tempfile.mkdtemp(); os.environ["SHELL"] = "/bin/sh"; sys.argv = ["gcm"]
import cairo, gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import GLib, Gtk
from gnome_connection_manager import app
from gnome_connection_manager.utils import tabcolors

app.conf.CONFIRM_ON_CLOSE_TAB = 0
app.conf.AUTO_CLOSE_TAB = 0
app.conf.STARTUP_LOCAL = False
app.wMain = w = app.Wmain(application=None)
w.wMain.show_all()
STRIPE, GAP = tabcolors.STRIPE, tabcolors.GAP
RED, YELLOW, BLUE, GREEN = "#e01b24", "#f6d32d", "#3584e4", "#2ec27e"
SELECTED, ATTENTION = "#eeeb00", "#f57900"

def pump(seconds=0.3):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        Gtk.main_iteration_do(False)
        time.sleep(0.005)

def host(group, name):
    # As gcm.conf gives them, since a save writes them: a hand-built Host leaves these None.
    record = app.Host(group, name)
    record.description = record.password = record.private_key = record.commands = record.user = ""
    record.host, record.port, record.keep_alive, record.type = "", "22", "0", "local"
    return record

def labels():
    notebook = w.nbConsole
    pages = [notebook.get_nth_page(i) for i in range(notebook.get_n_pages())]
    return [notebook.get_tab_label(page) for page in pages if hasattr(notebook.get_tab_label(page), "rename")]

def image(tab):
    pump(0.1)
    width, height = tab.get_allocated_width(), tab.get_allocated_height()
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    tab.draw(cairo.Context(surface))
    surface.flush()
    return width, height, surface.get_stride(), bytes(surface.get_data())

def at(drawn, x, y):
    _width, _height, stride, data = drawn
    blue, green, red, alpha = data[y * stride + x * 4 : y * stride + x * 4 + 4]
    return "clear" if alpha == 0 else "#%02x%02x%02x" % (red, green, blue)

def rows(drawn, top, bottom):
    # Each row's colour at the tab's left edge, inside the spaces before its name, clear
    # of any text, as a set: one colour for a band of one.
    return {at(drawn, 2, y) for y in range(top, bottom)}

def bands(drawn):
    # The stripe, the gap a mark leaves below it, and the mark's own rows below that.
    height = drawn[1]
    return rows(drawn, 0, STRIPE), rows(drawn, STRIPE, STRIPE + GAP), rows(drawn, STRIPE + GAP, height - 2)

def saved(prefix, key):
    # The tab colour gcm.conf holds for each record whose section starts with `prefix`, by
    # the record's `key`: a folder by its name, a host by its id.
    stored = configparser.RawConfigParser()
    stored.read(app.CONFIG_FILE)
    return {
        stored.get(name, key): stored.get(name, "tab-color", fallback=None)
        for name in stored.sections()
        if name.startswith(prefix)
    }

def use(tab):
    w.nbConsole.set_current_page(w.nbConsole.page_num(tab.widget_))
    pump(0.1)

ansible = host("ops/infra", "ansible")
web = host("ops", "web")
app.groups.clear()
for each in (ansible, web):
    app.groups.setdefault(each.group, []).append(each)
w.updateTree()
for each in (ansible, web):
    w.addTab(w.nbConsole, each)
pump(0.5)
tab_ansible, tab_web = labels()
ops = app.folders.child_named("", "ops")

if scenario == "stripes":
    # No colour anywhere: no stripe, and no style given to draw one.
    never = image(tab_web)
    assert bands(never)[0] == {"clear"}, bands(never)
    assert tab_web.color_style is None and tab_ansible.color_style is None

    # A host's own colour, and its folder's for a host without one.
    ansible.tab_color = RED
    ops.tab_color = YELLOW
    w.updateTree()
    assert (tab_ansible.color, tab_web.color) == (RED, YELLOW)
    assert bands(image(tab_ansible)) == ({RED}, {"clear"}, {"clear"}), bands(image(tab_ansible))
    assert bands(image(tab_web)) == ({YELLOW}, {"clear"}, {"clear"}), bands(image(tab_web))
    assert tab_web.get_allocated_height() == never[1], "a stripe took room"

    # A mark on a coloured tab starts below the stripe, a stripe of its own colour too.
    tab_web.set_selected(True)
    tab_ansible.set_attention(True)
    assert bands(image(tab_web)) == ({YELLOW}, {"clear"}, {SELECTED}), bands(image(tab_web))
    assert bands(image(tab_ansible)) == ({RED}, {"clear"}, {ATTENTION}), bands(image(tab_ansible))
    tab_ansible.set_attention(False)

    # A mark on a tab with no colour is drawn as it was, from its top.
    plain = host("", "plain")
    app.groups.setdefault("", []).append(plain)
    w.updateTree()
    w.addTab(w.nbConsole, plain)
    pump(0.5)
    tab_plain = labels()[-1]
    tab_plain.set_selected(True)
    assert rows(image(tab_plain), 0, tab_plain.get_allocated_height() - 2) == {SELECTED}
    tab_plain.set_selected(False)

    # An ended session keeps its stripe, and the tab in use, and one that is not.
    tab_ansible.mark_tab_as_closed(0)
    assert bands(image(tab_ansible))[0] == {RED}, bands(image(tab_ansible))
    assert w.nbConsole.get_nth_page(w.nbConsole.get_current_page()) is tab_plain.widget_
    assert bands(image(tab_web))[0] == {YELLOW}
    use(tab_web)
    assert bands(image(tab_web))[0] == {YELLOW}

    # A change of the folder's colour, and none: drawn exactly as when it never had one,
    # the tab in use then as now.
    use(tab_plain)
    ops.tab_color = BLUE
    w.updateTree()
    assert bands(image(tab_web)) == ({BLUE}, {"clear"}, {SELECTED}), bands(image(tab_web))
    tab_web.set_selected(False)
    ops.tab_color = ""
    w.updateTree()
    use(tab_web)
    assert tab_web.color == "" and image(tab_web) == never, "not as before"

elif scenario == "the-folder-menu":
    # Through the real colour chooser, answered as it runs.
    def answer(response, rgba=None):
        def respond():
            [dialog] = [each for each in Gtk.Window.list_toplevels() if isinstance(each, Gtk.ColorChooserDialog) and each.get_visible()]
            answered.append((dialog.get_title(), dialog.get_transient_for() is w.window))
            assert dialog.get_widget_for_response(app.NO_COLOR).get_label() == app._("No Color")
            if rgba is not None:
                dialog.set_rgba(app.parse_color_rgba(rgba))
            dialog.response(response)
            return False
        GLib.timeout_add(300, respond)

    answered = []
    w.select_folder_row(ops.id)
    answer(Gtk.ResponseType.OK, GREEN)
    w.color_selected_folder()
    assert answered == [(app._("Tab Color"), True)], answered
    assert ops.tab_color == GREEN and tab_web.color == GREEN and tab_ansible.color == GREEN
    assert saved("folder ", "name")["ops"] == GREEN, saved("folder ", "name")

    answer(Gtk.ResponseType.CANCEL, RED)
    w.color_selected_folder()
    assert ops.tab_color == GREEN, ops.tab_color

    answer(app.NO_COLOR)
    w.color_selected_folder()
    assert ops.tab_color == "" and tab_web.color == "", ops.tab_color
    assert saved("folder ", "name")["ops"] is None, saved("folder ", "name")
    assert len(answered) == 3, answered

elif scenario == "the-host-dialog":
    def opened(record):
        dialog = app.Whost()
        dialog.init(record.group, record)
        dialog.get_widget("wHost").present()
        pump()
        return dialog, dialog.get_widget("chkTabColor"), dialog.get_widget("btnTabColor")

    ops.tab_color = BLUE
    w.updateTree()
    # On Properties, below the tab name, unticked, the button greyed with the folder's colour.
    dialog, box, button = opened(web)
    grid = box.get_parent()
    name = dialog.get_widget("txtTabName")
    assert name.get_parent() is grid and button.get_parent() is grid
    row = grid.child_get_property(box, "top-attach")
    assert row == grid.child_get_property(name, "top-attach") + 1
    assert grid.child_get_property(button, "top-attach") == row
    assert box.get_mapped() and box.get_sensitive() and not box.get_active()
    assert not button.get_sensitive()
    assert app.color_to_hex(button.get_rgba()) == BLUE
    box.set_active(True)
    assert button.get_sensitive()
    button.set_rgba(app.parse_color_rgba(GREEN))
    dialog.on_okbutton1_clicked(None)
    pump()
    [record] = [each for each in app.groups["ops"] if each.id == web.id]
    assert record.tab_color == GREEN and tab_web.color == GREEN, (record.tab_color, tab_web.color)
    assert saved("host ", "id")[web.id] == GREEN

    # Shown again, ticked, and unticked takes the folder's again.
    dialog, box, button = opened(record)
    assert box.get_active() and button.get_sensitive()
    assert app.color_to_hex(button.get_rgba()) == GREEN
    box.set_active(False)
    assert not button.get_sensitive()
    dialog.on_okbutton1_clicked(None)
    pump()
    [record] = [each for each in app.groups["ops"] if each.id == web.id]
    assert record.tab_color == "" and tab_web.color == BLUE, (record.tab_color, tab_web.color)
    assert saved("host ", "id")[web.id] is None

    # A web host opens no tab: greyed and unticked.
    dialog, box, button = opened(record)
    box.set_active(True)
    dialog.cmbType.set_active([row[0] for row in dialog.cmbType.get_model()].index("web"))
    pump()
    assert not box.get_sensitive() and not box.get_active() and not button.get_sensitive()
    dialog.get_widget("wHost").destroy()

elif scenario == "dark-marks":
    # The marks' text is dark on a dark theme, whose own is light.
    def text_colour(tab):
        context = tab.label.get_style_context()
        return context.get_color(context.get_state())

    light = text_colour(tab_web)
    assert light.red + light.green + light.blue > 1.5, light.to_string()
    tab_web.set_selected(True)
    tab_ansible.set_attention(True)
    pump()
    for tab in (tab_web, tab_ansible):
        assert app.color_to_hex(text_colour(tab)) == "#2e3436", text_colour(tab).to_string()
else:
    raise SystemExit("no scenario " + scenario)
print("OK")
"""


@pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"),
    reason="needs a display for a real terminal",
)
@pytest.mark.parametrize(
    ("scenario", "theme"),
    [
        ("stripes", None),
        ("the-folder-menu", None),
        ("the-host-dialog", None),
        ("stripes", "Adwaita:dark"),
        ("dark-marks", "Adwaita:dark"),
    ],
)
def test_tab_colours_against_real_gtk(scenario, theme):
    """A host's colour and its folder's, drawn on real tabs: the stripe, a mark below it
    with a gap, an ended session and the tab in use, a tab without a colour drawn exactly as
    before, and a colour chosen in the real dialogs, saved and drawn at once. On a dark
    theme too, where the marks' text is dark (#350)."""
    pytest.importorskip("gi", reason="PyGObject not available")
    environment = dict(os.environ)
    if theme is not None:
        environment["GTK_THEME"] = theme
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT, scenario],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr[-3000:]
    assert "OK" in result.stdout
    assert not glib_complaints(result.stderr), result.stderr[-3000:]
