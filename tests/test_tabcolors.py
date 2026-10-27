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
from tests.test_host_files import Cell, Rows
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


def test_the_tree_marks_a_colour_with_a_square_on_a_patch_of_the_rows_background() -> None:
    """The square the user chose (#358), drawn on a patch of the row's own background so
    that it shows on the selected row."""
    assert tabcolors.mark_markup(RED, "#ffffff") == (
        f'<span foreground="{RED}" background="#ffffff">■</span>'
    )


def test_a_marks_colour_and_background_are_read_as_a_stripes_colour_is() -> None:
    assert tabcolors.mark_markup("#E01B24", " #FFF") == (
        f'<span foreground="{RED}" background="#ffffff">{tabcolors.MARK}</span>'
    )


@pytest.mark.parametrize("color", ["", "crimson", '#e01b24" background="red'])
def test_no_colour_has_no_mark(color: str) -> None:
    assert tabcolors.mark_markup(color, "#ffffff") == ""


@pytest.mark.parametrize("background", ["", "rgb(255,255,255)", '#fff" foreground="red'])
def test_a_background_that_cannot_be_read_gives_the_mark_no_patch(background: str) -> None:
    """Only a colour read here reaches the markup, as with the stripe's CSS."""
    assert tabcolors.mark_markup(RED, background) == f'<span foreground="{RED}">■</span>'


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


# -- the server tree and the Hosts menu (#358) ---------------------------------


def escaped(app_module, monkeypatch) -> None:
    """GLib's markup_escape_text, for the stubbed gi."""
    monkeypatch.setattr(
        app_module.GLib,
        "markup_escape_text",
        lambda text, length=-1: text.replace("&", "&amp;").replace("<", "&lt;"),
        raising=False,
    )


def drawn_name(app_module, monkeypatch, tree: FolderTree, row: list) -> dict:
    """What draw_name gives the name's renderer for `row`, a row of the tree's model, with
    `tree` the folders."""
    monkeypatch.setattr(app_module, "folders", tree)
    escaped(app_module, monkeypatch)
    model = Rows(row)
    cell = Cell()
    app_module.draw_name(None, cell, model, model.rows[0], None)
    return cell.properties


def test_a_hosts_row_shows_the_colour_its_tabs_take(app_module, monkeypatch):
    """Its own, else its folder's, on a patch of the row's own background, and the mount
    mark after it, all in the name's own text."""
    tree = tree_of(("ops", ROOT, BLUE))
    own, plain = filed("ops", RED), filed("ops")
    plain.name = "R&D"

    assert drawn_name(app_module, monkeypatch, tree, ["router", own, "", "#f1f1f1", "", ""]) == {
        "markup": f'<span foreground="{RED}" background="#f1f1f1">■</span> router'
    }
    mounted = ["R&D", plain, "", "#ffffff", "", "/home/x/mnt/R&D"]
    assert drawn_name(app_module, monkeypatch, tree, mounted) == {
        "markup": f'<span foreground="{BLUE}" background="#ffffff">■</span> ✓ R&amp;D'
    }


def test_a_folders_row_shows_the_colour_it_gives(app_module, monkeypatch):
    """Its own, or one it takes from a folder above it."""
    tree = tree_of(("ops", ROOT, BLUE), ("prod", "ops", ""), ("lab", ROOT, ""))

    assert drawn_name(app_module, monkeypatch, tree, ["prod", None, "", "#ffffff", "prod", ""]) == {
        "markup": f'<span foreground="{BLUE}" background="#ffffff">■</span> prod'
    }
    assert drawn_name(app_module, monkeypatch, tree, ["lab", None, "", "#ffffff", "lab", ""]) == {}


def test_a_row_with_no_colour_is_drawn_as_before(app_module, monkeypatch):
    """As draw_mount_mark alone draws it: the name column's text, after the tick only
    while the host is mounted."""
    tree = tree_of(("ops", ROOT, "crimson"))
    host = filed("ops", "")
    rows = (
        ["router", host, "", "#fff", "", "/home/x/mnt/router"],
        ["router", host, "", "#fff", "", ""],
    )

    assert [drawn_name(app_module, monkeypatch, tree, row) for row in rows] == [
        {"text": "✓ router"},
        {},
    ]


class MenuStyle:
    """The Hosts menu's style context, as label_menu_item reads its background."""

    def __init__(self, background: tuple[float, float, float]) -> None:
        self.background = background

    def get_property(self, name: str, state: object) -> types.SimpleNamespace:
        assert name == "background-color"
        red, green, blue = self.background
        return types.SimpleNamespace(red=red, green=green, blue=blue)


class StyledMenu:
    """The Hosts menu, with the background `style` gives it."""

    def __init__(self, background: tuple[float, float, float]) -> None:
        self.style = MenuStyle(background)

    def get_style_context(self) -> MenuStyle:
        return self.style


class ItemLabel:
    """A menu item's Gtk.AccelLabel, as label_menu_item marks it."""

    def __init__(self) -> None:
        self.markup: str | None = None

    def set_markup(self, markup: str) -> None:
        self.markup = markup


class LabelledItem:
    """A Hosts menu item, as label_menu_item labels it."""

    def __init__(self) -> None:
        self.label: str | None = None
        self.child = ItemLabel()

    def set_label(self, label: str) -> None:
        self.label = label

    def get_child(self) -> ItemLabel:
        return self.child


def menu_window(app_module, monkeypatch, background=(1.0, 1.0, 1.0)):
    escaped(app_module, monkeypatch)
    wmain = object.__new__(app_module.Wmain)
    wmain.menuServers = StyledMenu(background)
    wmain.colored_items = {}
    wmain.update_row_color = lambda *_args: None
    return wmain


def test_a_hosts_menu_item_shows_its_colour_on_a_patch_of_the_menus_background(
    app_module, monkeypatch
):
    """So that it shows on a hovered item, which Adwaita draws in #3584e4."""
    wmain = menu_window(app_module, monkeypatch, background=(47 / 255, 47 / 255, 47 / 255))
    item = LabelledItem()

    wmain.label_menu_item(item, "✓ R&D", BLUE)

    assert item.child.markup == f'<span foreground="{BLUE}" background="#2f2f2f">■</span> ✓ R&amp;D'
    assert item.label is None
    assert wmain.colored_items == {item: ("✓ R&D", BLUE)}


def test_a_hosts_menu_item_without_a_colour_is_labelled_as_before(app_module, monkeypatch):
    wmain = menu_window(app_module, monkeypatch)
    item = LabelledItem()

    wmain.label_menu_item(item, "R&D", "")

    assert (item.label, item.child.markup, wmain.colored_items) == ("R&D", None, {})


def test_a_change_of_theme_marks_the_hosts_menu_on_its_new_background(app_module, monkeypatch):
    wmain = menu_window(app_module, monkeypatch)
    marked, plain = LabelledItem(), LabelledItem()
    wmain.label_menu_item(marked, "web", RED)
    wmain.label_menu_item(plain, "db", "")
    wmain.menuServers.style.background = (47 / 255, 47 / 255, 47 / 255)

    wmain.on_tvServers_style_updated(None)

    assert marked.child.markup == f'<span foreground="{RED}" background="#2f2f2f">■</span> web'
    assert (plain.label, plain.child.markup) == ("db", None)


def test_the_tree_and_menu_fakes_offer_only_what_gtk_has() -> None:
    gi = pytest.importorskip("gi", reason="PyGObject not available")
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    for fake, real in (
        (StyledMenu, Gtk.Menu),
        (MenuStyle, Gtk.StyleContext),
        (ItemLabel, Gtk.AccelLabel),
        (LabelledItem, Gtk.MenuItem),
    ):
        for name in vars(fake):
            if not name.startswith("_"):
                assert hasattr(real, name), (real, name)


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
app.conf.CHECK_UPDATES = False
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


# The real server tree, drawn into an image as the tabs are above, and the real Hosts
# menu (#358). HOME is a scratch folder, so this never reads a real gcm.conf.
_TREE_SCRIPT = r"""
import os, sys, tempfile, time
from collections import Counter
scenario = sys.argv[1]
os.environ["HOME"] = tempfile.mkdtemp(); os.environ["SHELL"] = "/bin/sh"; sys.argv = ["gcm"]
import cairo, gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import GLib, Gtk
if scenario == "the-hosts-menu":
    # A theme GTK has built in, so that preferring its dark variant changes the theme.
    Gtk.Settings.get_default().set_property("gtk-theme-name", "Adwaita")
from gnome_connection_manager import app
from gnome_connection_manager.utils import tabcolors

app.conf.STARTUP_LOCAL = False
app.conf.CHECK_UPDATES = False
app.conf.LEFT_PANEL_WIDTH = 300
app.wMain = w = app.Wmain(application=None)
w.wMain.resize(760, 400)
w.wMain.show_all()
RED, YELLOW, BLUE, GREEN = "#e01b24", "#f6d32d", "#3584e4", "#2ec27e"
COLOURS = {RED, YELLOW, BLUE, GREEN}

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

ansible, web, db = host("ops/infra", "ansible"), host("ops/infra", "web"), host("ops", "db")
router, plain = host("lab", "router"), host("misc", "plain")
app.groups.clear()
for each in (ansible, web, db, router, plain):
    app.groups.setdefault(each.group, []).append(each)
w.updateTree()
ops = app.folders.child_named("", "ops")
lab = app.folders.child_named("", "lab")
tree, model = w.treeServers, w.treeModel
column = tree.get_column(0)
icon, name = column.get_cells()

def settle(seconds=5):
    # Until the pane is as wide as it stays: measured, the tree is first drawn 148 pixels
    # wide, and 298 a moment later.
    end, size = time.monotonic() + seconds, None
    while time.monotonic() < end:
        pump(0.2)
        if size == (size := (tree.get_allocated_width(), tree.get_allocated_height())):
            return
    raise AssertionError(f"the tree did not settle: {size}")

settle()

def redraw():
    w.updateTree()
    tree.expand_all()
    tree.get_selection().unselect_all()
    pump(0.2)

def row(called):
    found = []
    def visit(_model, path, iter_):
        if model.get_value(iter_, 0) == called:
            found.append((path.copy(), iter_.copy()))
        return False
    model.foreach(visit)
    [(path, iter_)] = found
    return path, iter_

def rows():
    found = []
    model.foreach(lambda _model, path, _iter: found.append(path.copy()) and False)
    return found

def heights():
    return [tree.get_background_area(path, column).height for path in rows()]

def image():
    pump(0.1)
    width, height = tree.get_allocated_width(), tree.get_allocated_height()
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    tree.draw(cairo.Context(surface))
    surface.flush()
    return width, height, surface.get_stride(), bytes(surface.get_data())

def at(drawn, x, y):
    _width, _height, stride, data = drawn
    blue, green, red, alpha = data[y * stride + x * 4 : y * stride + x * 4 + 4]
    return "clear" if alpha == 0 else "#%02x%02x%02x" % (red, green, blue)

def mark_box(called):
    # Where the row's square is drawn, on its patch, before the rest of its name, which
    # starts there on a row without one: (x0, x1, y0, y1) in the drawing.
    path, iter_ = row(called)
    column.cell_set_cell_data(model, iter_, False, False)
    start, _width = column.cell_get_position(name)
    xpad, _ypad = name.get_padding()
    layout = tree.create_pango_layout("")
    layout.set_markup(tabcolors.mark_markup(RED, "#ffffff"), -1)
    _ink, logical = layout.get_pixel_extents()
    cell, area = tree.get_cell_area(path, column), tree.get_background_area(path, column)
    x0, y0 = tree.convert_bin_window_to_widget_coords(cell.x + start + xpad, area.y)
    return x0, x0 + logical.width, y0, y0 + area.height

def colours(drawn, called):
    x0, x1, y0, y1 = mark_box(called)
    return Counter(at(drawn, x, y) for x in range(x0, x1) for y in range(y0, y1))

def mark_of(drawn, called):
    # The test colour a row's square shows, or None: at least a 5 by 5 square of it, and
    # no other test colour.
    found = colours(drawn, called)
    shown = {colour for colour in COLOURS if found[colour]}
    assert len(shown) <= 1, (called, shown)
    [colour] = shown or [None]
    assert colour is None or found[colour] >= 25, (called, found.most_common(4))
    return colour

def text_of(called):
    # The text the name's renderer draws for the row, its marks with it.
    column.cell_set_cell_data(model, row(called)[1], False, False)
    return name.props.text

def framed(drawn, called, background, inside):
    # Whether a run of `inside` lies between two of `background` on a line of the row's
    # mark: the square on its patch. The square's edges are blended, and left out.
    x0, x1, y0, y1 = mark_box(called)
    for y in range(y0, y1):
        runs = []
        for x in range(x0, x1):
            colour = at(drawn, x, y)
            if colour not in (background, inside):
                continue
            if runs and runs[-1][0] == colour:
                runs[-1][1] += 1
            else:
                runs.append([colour, 1])
        for before, middle, after in zip(runs, runs[1:], runs[2:]):
            if before[0] == after[0] == background and middle[0] == inside and middle[1] >= 3:
                return True
    return False

if scenario == "drawn":
    redraw()
    before, tall = image(), heights()
    assert [mark_of(before, called) for called in ("ops", "db", "lab", "plain")] == [None] * 4

    # A host's own colour, its folder's, a folder's own, and one a folder takes from above.
    db.tab_color, ops.tab_color, lab.tab_color = RED, BLUE, GREEN
    redraw()
    drawn = image()
    shown = {called: mark_of(drawn, called) for called in ("ops", "infra", "ansible", "web", "db", "lab", "router", "misc", "plain")}
    assert shown == {
        "ops": BLUE, "infra": BLUE, "ansible": BLUE, "web": BLUE, "db": RED,
        "lab": GREEN, "router": GREEN, "misc": None, "plain": None,
    }, shown
    # On both stripes, and every row as tall as with no mark.
    striped = {model.get_value(row(called)[1], 3) for called, colour in shown.items() if colour}
    assert striped == {w.color_back1, w.color_back2}, striped
    assert heights() == tall, (heights(), tall)
    # Beside the mount mark, which comes after it, as show_mounts marks a row.
    model.set_value(row("ansible")[1], 5, "/home/x/mnt/ansible")
    assert mark_of(image(), "ansible") == BLUE
    assert text_of("ansible") == f"{tabcolors.MARK} {app.MOUNTED_MARK} ansible", text_of("ansible")

    # The selected row, in the selection's own colour: the square on a patch of the row's
    # own background. The selection read as drawn, clear of the row's text.
    def selected(called):
        tree.get_selection().select_path(row(called)[0])
        drawn = image()
        _x0, _x1, y0, y1 = mark_box(called)
        return drawn, at(drawn, drawn[0] - 4, (y0 + y1) // 2)

    _drawn, selection = selected("db")
    db.tab_color = selection
    redraw()
    drawn, now = selected("db")
    assert now == selection, (now, selection)
    background = model.get_value(row("db")[1], 3)
    assert framed(drawn, "db", background, selection), colours(drawn, "db").most_common(6)
    # And a mark on the other stripe, in another colour, on its patch too.
    drawn, _selection = selected("router")
    assert framed(drawn, "router", model.get_value(row("router")[1], 3), GREEN)

    # No colour anywhere: drawn exactly as the name column was before, by draw_mount_mark
    # alone. Last, as nothing gives back the data function the tree was given.
    db.tab_color = ops.tab_color = lab.tab_color = ""
    redraw()
    after = image()
    column.set_cell_data_func(name, app.draw_mount_mark)
    assert image() == after, "not drawn as before"

elif scenario == "follows":
    def answer(response, rgba=None):
        # The real colour chooser, answered as it runs.
        def respond():
            [dialog] = [each for each in Gtk.Window.list_toplevels() if isinstance(each, Gtk.ColorChooserDialog) and each.get_visible()]
            if rgba is not None:
                dialog.set_rgba(app.parse_color_rgba(rgba))
            dialog.response(response)
            return False
        GLib.timeout_add(300, respond)

    def drawn(*called):
        tree.expand_all()
        tree.get_selection().unselect_all()
        picture = image()
        return [mark_of(picture, each) for each in called]

    ops.tab_color = BLUE
    redraw()
    assert drawn("web", "ansible") == [BLUE, BLUE]

    # The host dialog's OK.
    dialog = app.Whost()
    dialog.init(web.group, web)
    dialog.get_widget("wHost").present()
    pump()
    dialog.get_widget("chkTabColor").set_active(True)
    dialog.get_widget("btnTabColor").set_rgba(app.parse_color_rgba(YELLOW))
    dialog.on_okbutton1_clicked(None)
    pump()
    assert drawn("web", "ansible", "ops") == [YELLOW, BLUE, BLUE]

    # A folder's Tab Color, through the real chooser.
    w.select_folder_row(lab.id)
    answer(Gtk.ResponseType.OK, GREEN)
    w.color_selected_folder()
    assert drawn("lab", "router") == [GREEN, GREEN]

    # A host moved to another folder, as a drop moves it.
    ansible.folder = lab.id
    w.updateTree()
    assert drawn("ansible") == [GREEN]

    # No Color.
    w.select_folder_row(lab.id)
    answer(app.NO_COLOR)
    w.color_selected_folder()
    assert drawn("lab", "router", "ansible", "ops") == [None, None, None, BLUE]

elif scenario == "the-hosts-menu":
    def background():
        context = w.menuServers.get_style_context()
        return app.color_to_hex(context.get_property("background-color", Gtk.StateFlags.NORMAL))

    def label_of(item):
        child = item.get_child()
        return child.get_label(), child.get_use_markup()

    def item_of(menu, text):
        [item] = [each for each in menu.get_children() if each.get_child().get_text() == text]
        return item

    web.type, web.host, web.user = "ssh", "192.0.2.10", "eric"
    db.tab_color, ops.tab_color = RED, BLUE
    redraw()
    light = background()
    # Each host's item and each folder's, marked as its row is, on the menu's background.
    assert label_of(w.host_items[db]) == (app.marked_markup("db", RED, light), True)
    assert label_of(w.host_items[web]) == (app.marked_markup("web", BLUE, light), True)
    assert label_of(w.host_items[router]) == ("router", False)
    mark = tabcolors.MARK
    ops_item = item_of(w.menuServers, f"{mark} ops")
    assert label_of(ops_item) == (app.marked_markup("ops", BLUE, light), True)
    assert label_of(item_of(ops_item.get_submenu(), f"{mark} infra"))[0] == app.marked_markup("infra", BLUE, light)
    assert label_of(item_of(w.menuServers, "lab")) == ("lab", False)

    # Mounted and unmounted, as the mount table has it: the mark stays, the tick after it,
    # in the tree too.
    folder = os.path.join(os.environ["HOME"], "mnt", "web")
    app.read_mount_table = lambda: f"300 1 0:90 / {folder} rw - fuse.sshfs eric@192.0.2.10: rw\n"
    w.show_mounts()
    assert label_of(w.host_items[web]) == (app.marked_markup("✓ web", BLUE, light), True)
    assert text_of("web") == f"{mark} ✓ web", text_of("web")
    app.read_mount_table = lambda: ""
    w.show_mounts()
    assert label_of(w.host_items[web]) == (app.marked_markup("web", BLUE, light), True)
    assert text_of("web") == f"{mark} web", text_of("web")

    # A change of theme marks the items again, on its menus' background.
    Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)
    pump(0.5)
    dark = background()
    assert dark != light, dark
    assert label_of(w.host_items[db]) == (app.marked_markup("db", RED, dark), True)
    assert label_of(ops_item) == (app.marked_markup("ops", BLUE, dark), True)
    assert label_of(w.host_items[router]) == ("router", False)
else:
    raise SystemExit("no scenario " + scenario)
print("OK")
"""


@pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"),
    reason="needs a display for a real tree",
)
@pytest.mark.parametrize(
    ("scenario", "theme"),
    [
        ("drawn", None),
        ("drawn", "Adwaita:dark"),
        ("follows", None),
        ("the-hosts-menu", None),
    ],
)
def test_tree_colours_against_real_gtk(scenario, theme):
    """A host's colour and a folder's, drawn in the real server tree (#358): a square
    before the name, readable on both stripes and on the selected row in the selection's
    own colour, rows as tall as before, and a tree without a colour drawn exactly as
    before. It follows the host dialog, the folder's chooser and a move at once, and the
    Hosts menu shows it too, through a mount and a change of theme."""
    pytest.importorskip("gi", reason="PyGObject not available")
    environment = dict(os.environ)
    # The Hosts menu's change of theme is made in GTK's settings, which GTK_THEME overrides.
    environment.pop("GTK_THEME", None)
    if theme is not None:
        environment["GTK_THEME"] = theme
    result = subprocess.run(
        [sys.executable, "-c", _TREE_SCRIPT, scenario],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr[-3000:]
    assert "OK" in result.stdout
    assert not glib_complaints(result.stderr), result.stderr[-3000:]
