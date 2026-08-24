"""The open-console list behind the tab-strip dropdown and the Terminal menu (#84)."""

from __future__ import annotations

import types

import pytest


def escape(text, _length=-1):
    """Stand-in for GLib.markup_escape_text, which the gi stub cannot provide."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class FakeTabLabel:
    def __init__(self, text, active=True, attention=False):
        self._text = text
        self.is_active = active
        self.needs_attention = attention

    def get_display_text(self):
        return self._text

    def get_text(self):
        """The identity, deliberately different from what the tab renders."""
        return "  identity  "


class FakeTerminal:
    pass


class FakePage:
    def __init__(self, terminal=None):
        self.terminal = terminal or FakeTerminal()

    def get_children(self):
        return [self.terminal]


class FakeNotebook:
    def __init__(self, labels):
        self.pages = [FakePage() for _ in labels]
        self.labels = list(labels)
        self.current = 0
        self.action_widgets = {}

    def get_n_pages(self):
        return len(self.pages)

    def get_nth_page(self, position):
        return self.pages[position]

    def get_tab_label(self, page):
        return self.labels[self.pages.index(page)]

    def page_num(self, page):
        return self.pages.index(page) if page in self.pages else -1

    def set_current_page(self, position):
        self.current = position

    def get_children(self):
        return list(self.pages)

    def set_action_widget(self, widget, pack_type):
        self.action_widgets[pack_type] = widget

    def get_action_widget(self, pack_type):
        return self.action_widgets.get(pack_type)


class FakePaned:
    def __init__(self, *children):
        self.children = list(children)

    def get_children(self):
        return self.children


class FakeMenuItem:
    def __init__(self, label=None, **_kwargs):
        self.label = label
        self.markup = None
        self.sensitive = True
        self.active = False
        self.radio = False
        self.submenu = None
        self.handlers = []

    def set_sensitive(self, value):
        self.sensitive = value

    def set_active(self, value):
        self.active = value

    def set_draw_as_radio(self, value):
        self.radio = value

    def set_submenu(self, submenu):
        self.submenu = submenu

    def get_children(self):
        return [self]

    def set_markup(self, markup):
        self.markup = markup

    def connect(self, signal, callback, *args):
        self.handlers.append((signal, callback, args))

    def activate(self):
        for signal, callback, args in self.handlers:
            if signal == "activate":
                callback(self, *args)

    def show(self):
        pass


class FakeSeparator(FakeMenuItem):
    pass


class FakeMenu:
    def __init__(self):
        self.items = []
        self.attached_to = None

    def attach_to_widget(self, widget, _detacher):
        self.attached_to = widget

    def append(self, item):
        self.items.append(item)

    def remove(self, item):
        self.items.remove(item)

    def foreach(self, callback):
        for item in list(self.items):
            callback(item)


@pytest.fixture
def console_env(monkeypatch, app_module):
    """Wire the module's gi stubs up far enough to build a console menu."""
    monkeypatch.setattr(app_module.GLib, "markup_escape_text", escape, raising=False)
    monkeypatch.setattr(app_module.Gtk, "Notebook", FakeNotebook, raising=False)
    monkeypatch.setattr(app_module.Gtk, "MenuItem", FakeMenuItem, raising=False)
    monkeypatch.setattr(app_module.Gtk, "CheckMenuItem", FakeMenuItem, raising=False)
    monkeypatch.setattr(app_module.Gtk, "SeparatorMenuItem", FakeSeparator, raising=False)
    monkeypatch.setattr(app_module.Vte, "Terminal", FakeTerminal, raising=False)
    return app_module


def make_wmain(app_module, root, current=None):
    wmain = object.__new__(app_module.Wmain)
    wmain.hpMain = root
    wmain.current = current
    return wmain


# -- shortcut hints ----------------------------------------------------------


def test_hints_follow_the_configured_keys(monkeypatch, app_module):
    """A hardcoded Alt+N would drift from what the user actually pressed (#3, #15)."""
    monkeypatch.setattr(
        app_module,
        "shortcuts",
        {"CTRL+1": ["console_1"], "SUPER+F4": ["console_2"]},
    )

    hints = app_module.console_shortcut_hints()

    assert hints[0] == "CTRL+1"
    assert hints[1] == "SUPER+F4"


def test_unbound_positions_have_no_hint(monkeypatch, app_module):
    monkeypatch.setattr(app_module, "shortcuts", {"ALT+1": ["console_1"]})

    hints = app_module.console_shortcut_hints()

    assert hints[1:] == [None] * 8


def test_hints_cover_exactly_nine_positions(monkeypatch, app_module):
    monkeypatch.setattr(app_module, "shortcuts", {})

    assert len(app_module.console_shortcut_hints()) == 9


def test_hints_ignore_custom_byte_sequences(monkeypatch, app_module):
    """A [keys] entry maps to a string, not a command list, and must not be read."""
    monkeypatch.setattr(app_module, "shortcuts", {"CTRL+1": "some text"})

    assert app_module.console_shortcut_hints()[0] is None


# -- entries -----------------------------------------------------------------


def test_entries_follow_tab_order(app_module):
    notebook = FakeNotebook([FakeTabLabel("one"), FakeTabLabel("two")])

    entries = app_module.console_entries(notebook, None, ["A", "B"])

    assert [e.text for e in entries] == ["one", "two"]
    assert [e.position for e in entries] == [0, 1]
    assert [e.accel for e in entries] == ["A", "B"]


def test_entries_beyond_the_hints_have_no_accel(app_module):
    """The tenth console onward is unreachable by key, so it must not borrow one."""
    notebook = FakeNotebook([FakeTabLabel(f"c{i}") for i in range(11)])

    entries = app_module.console_entries(notebook, None, [f"ALT+{n}" for n in range(1, 10)])

    assert len(entries) == 11
    assert entries[8].accel == "ALT+9"
    assert entries[9].accel is None and entries[10].accel is None


def test_entry_text_is_what_the_tab_renders_not_its_identity(app_module):
    """The program-set title is the half that tells two agent sessions apart."""
    notebook = FakeNotebook([FakeTabLabel("  claude: gcm  ")])

    entry = app_module.console_entries(notebook, None, [None])[0]

    assert entry.text == "claude: gcm"


def test_entry_reads_state_from_the_tab_label(app_module):
    notebook = FakeNotebook(
        [FakeTabLabel("gone", active=False), FakeTabLabel("ringing", attention=True)]
    )

    entries = app_module.console_entries(notebook, None, [None, None])

    assert entries[0].active is False and entries[0].attention is False
    assert entries[1].active is True and entries[1].attention is True


def test_only_the_focused_page_is_current(app_module):
    notebook = FakeNotebook([FakeTabLabel("one"), FakeTabLabel("two")])

    entries = app_module.console_entries(notebook, notebook.pages[1], [None, None])

    assert [e.current for e in entries] == [False, True]


def test_a_plain_tab_label_still_yields_text(app_module):
    """nbConsole carries glade placeholder pages whose labels are plain Gtk.Labels."""

    class PlainLabel:
        def get_text(self):
            return " placeholder "

    notebook = FakeNotebook([PlainLabel()])

    entry = app_module.console_entries(notebook, None, [None])[0]

    assert entry.text == "placeholder"
    assert entry.active is True


# -- markup ------------------------------------------------------------------


def test_markup_renders_a_plain_console(console_env):
    entry = console_env.ConsoleEntry(None, None, FakeTabLabel("web-01"), 0)

    assert console_env.console_item_markup(entry) == "web-01"


def test_markup_strikes_through_a_finished_session(console_env):
    entry = console_env.ConsoleEntry(None, None, FakeTabLabel("web-01", active=False), 0)

    markup = console_env.console_item_markup(entry)

    assert "strikethrough='true'" in markup
    assert "darkgray" in markup


def test_markup_bolds_a_console_wanting_attention(console_env):
    entry = console_env.ConsoleEntry(None, None, FakeTabLabel("web-01", attention=True), 0)

    assert console_env.console_item_markup(entry) == "<b>web-01</b>"


def test_markup_prefixes_the_configured_key(console_env):
    entry = console_env.ConsoleEntry(None, None, FakeTabLabel("web-01"), 0, accel="ALT+1")

    markup = console_env.console_item_markup(entry)

    assert markup.startswith("<span foreground='blue' size='x-small'>[ALT+1]</span> ")
    assert markup.endswith("web-01")


def test_markup_escapes_a_title_the_remote_end_chose(console_env):
    """The title comes from the program in the terminal, so it reaches set_markup hostile."""
    entry = console_env.ConsoleEntry(None, None, FakeTabLabel("<b>&pwn</b>"), 0)

    assert console_env.console_item_markup(entry) == "&lt;b&gt;&amp;pwn&lt;/b&gt;"


def test_markup_keeps_a_zero_in_the_name(console_env):
    """parse_markup with a '0' accel marker eats it; set_markup is used instead."""
    entry = console_env.ConsoleEntry(None, None, FakeTabLabel("web-01"), 0, accel="ALT+1")

    assert "web-01" in console_env.console_item_markup(entry)


# -- pane walking ------------------------------------------------------------


def test_collect_notebooks_finds_every_pane_in_order(console_env):
    left = FakeNotebook([FakeTabLabel("a")])
    right = FakeNotebook([FakeTabLabel("b")])
    wmain = make_wmain(console_env, FakePaned(left, FakePaned(right)))

    assert wmain.collect_notebooks(wmain.hpMain) == [left, right]


def test_collect_notebooks_does_not_descend_into_a_notebook(console_env):
    """Pages are not panes; descending would list a terminal's children as notebooks."""
    inner = FakeNotebook([FakeTabLabel("a")])
    wmain = make_wmain(console_env, FakePaned(inner))

    assert wmain.collect_notebooks(wmain.hpMain) == [inner]


def test_open_console_groups_keeps_panes_apart(console_env, monkeypatch):
    monkeypatch.setattr(console_env, "shortcuts", {})
    left = FakeNotebook([FakeTabLabel("a"), FakeTabLabel("b")])
    right = FakeNotebook([FakeTabLabel("c")])
    wmain = make_wmain(console_env, FakePaned(left, right))

    pane_groups = wmain.open_console_groups()

    assert [notebook for notebook, _entries in pane_groups] == [left, right]
    assert [[e.text for e in entries] for _nb, entries in pane_groups] == [["a", "b"], ["c"]]


def test_open_console_groups_marks_the_focused_console(console_env, monkeypatch):
    monkeypatch.setattr(console_env, "shortcuts", {})
    left = FakeNotebook([FakeTabLabel("a")])
    right = FakeNotebook([FakeTabLabel("b"), FakeTabLabel("c")])
    terminal = right.pages[1].terminal
    terminal.get_parent = lambda: right.pages[1]
    wmain = make_wmain(console_env, FakePaned(left, right), current=terminal)

    marked = [
        entry.text
        for _nb, entries in wmain.open_console_groups()
        for entry in entries
        if entry.current
    ]

    assert marked == ["c"]


def test_accel_hints_restart_in_each_pane(console_env, monkeypatch):
    """Alt+N addresses a position inside one notebook, so the keys repeat per pane."""
    monkeypatch.setattr(console_env, "shortcuts", {"ALT+1": ["console_1"]})
    left = FakeNotebook([FakeTabLabel("a")])
    right = FakeNotebook([FakeTabLabel("b")])
    wmain = make_wmain(console_env, FakePaned(left, right))

    pane_groups = wmain.open_console_groups()

    assert pane_groups[0][1][0].accel == "ALT+1"
    assert pane_groups[1][1][0].accel == "ALT+1"


# -- the menu ----------------------------------------------------------------


def test_menu_lists_one_item_per_console(console_env, monkeypatch):
    monkeypatch.setattr(console_env, "shortcuts", {})
    notebook = FakeNotebook([FakeTabLabel("a"), FakeTabLabel("b")])
    wmain = make_wmain(console_env, FakePaned(notebook))

    menu = wmain.build_console_menu(FakeMenu())

    assert [item.markup for item in menu.items] == ["a", "b"]


def test_menu_has_no_pane_headings_with_one_pane(console_env, monkeypatch):
    monkeypatch.setattr(console_env, "shortcuts", {})
    notebook = FakeNotebook([FakeTabLabel("a")])
    wmain = make_wmain(console_env, FakePaned(notebook))

    menu = wmain.build_console_menu(FakeMenu())

    assert [item.markup for item in menu.items] == ["a"]
    assert not [item for item in menu.items if not item.sensitive]


def test_menu_groups_panes_under_headings(console_env, monkeypatch):
    monkeypatch.setattr(console_env, "shortcuts", {})
    left = FakeNotebook([FakeTabLabel("a")])
    right = FakeNotebook([FakeTabLabel("b")])
    wmain = make_wmain(console_env, FakePaned(left, right))

    menu = wmain.build_console_menu(FakeMenu())

    headings = [item.label for item in menu.items if item.label]
    assert headings == ["Pane 1", "Pane 2"]
    assert all(not item.sensitive for item in menu.items if item.label)


def test_menu_separates_the_panes(console_env, monkeypatch):
    monkeypatch.setattr(console_env, "shortcuts", {})
    left = FakeNotebook([FakeTabLabel("a")])
    right = FakeNotebook([FakeTabLabel("b")])
    wmain = make_wmain(console_env, FakePaned(left, right))

    menu = wmain.build_console_menu(FakeMenu())

    assert sum(isinstance(item, FakeSeparator) for item in menu.items) == 1


def test_menu_skips_an_empty_pane(console_env, monkeypatch):
    monkeypatch.setattr(console_env, "shortcuts", {})
    left = FakeNotebook([FakeTabLabel("a")])
    right = FakeNotebook([])
    wmain = make_wmain(console_env, FakePaned(left, right))

    menu = wmain.build_console_menu(FakeMenu())

    assert [item.markup for item in menu.items] == ["a"]
    assert not [item.label for item in menu.items if item.label]


def test_menu_says_so_when_nothing_is_open(console_env, monkeypatch):
    monkeypatch.setattr(console_env, "shortcuts", {})
    wmain = make_wmain(console_env, FakePaned(FakeNotebook([])))

    menu = wmain.build_console_menu(FakeMenu())

    assert [item.label for item in menu.items] == ["No open consoles"]
    assert not menu.items[0].sensitive


def test_menu_is_rebuilt_rather_than_appended_to(console_env, monkeypatch):
    """It is filled on the way open, so a stale item must not survive the next open."""
    monkeypatch.setattr(console_env, "shortcuts", {})
    notebook = FakeNotebook([FakeTabLabel("a")])
    wmain = make_wmain(console_env, FakePaned(notebook))
    menu = FakeMenu()

    wmain.build_console_menu(menu)
    wmain.build_console_menu(menu)

    assert [item.markup for item in menu.items] == ["a"]


def test_menu_marks_the_current_console(console_env, monkeypatch):
    monkeypatch.setattr(console_env, "shortcuts", {})
    notebook = FakeNotebook([FakeTabLabel("a"), FakeTabLabel("b")])
    terminal = notebook.pages[1].terminal
    terminal.get_parent = lambda: notebook.pages[1]
    wmain = make_wmain(console_env, FakePaned(notebook), current=terminal)

    menu = wmain.build_console_menu(FakeMenu())

    assert [item.active for item in menu.items] == [False, True]
    assert all(item.radio for item in menu.items)


def test_choosing_a_console_raises_it_and_takes_the_keyboard(console_env, monkeypatch):
    monkeypatch.setattr(console_env, "shortcuts", {})
    left = FakeNotebook([FakeTabLabel("a")])
    right = FakeNotebook([FakeTabLabel("b"), FakeTabLabel("c")])
    wmain = make_wmain(console_env, FakePaned(left, right))
    focused = []
    wmain.wMain = type("W", (), {"set_focus": lambda _self, w: focused.append(w)})()
    wmain.on_tab_focus = lambda *args: None

    menu = wmain.build_console_menu(FakeMenu())
    [item for item in menu.items if item.markup == "c"][0].activate()

    assert right.current == 1
    assert focused == [right.pages[1].terminal]


def test_focus_console_refuses_a_page_that_has_gone(console_env):
    """A console can be closed while the menu is open; page_num then reports -1."""
    notebook = FakeNotebook([FakeTabLabel("a")])
    wmain = make_wmain(console_env, FakePaned(notebook))

    assert wmain.focus_console(notebook, FakePage()) is False


# -- installing the button and the menu --------------------------------------


class FakeButton:
    def __init__(self):
        self.child = None
        self.tooltip = None
        self.handlers = []

    def set_relief(self, _relief):
        pass

    def set_focus_on_click(self, _value):
        pass

    def add(self, child):
        self.child = child

    def set_tooltip_text(self, text):
        self.tooltip = text

    def connect(self, signal, callback, *args):
        self.handlers.append((signal, callback, args))

    def click(self):
        for signal, callback, args in self.handlers:
            if signal == "clicked":
                callback(self, *args)

    def show_all(self):
        pass


@pytest.fixture
def button_env(monkeypatch, console_env):
    monkeypatch.setattr(console_env.Gtk, "Button", FakeButton, raising=False)
    monkeypatch.setattr(console_env.Gtk, "Menu", FakeMenu, raising=False)
    monkeypatch.setattr(console_env.Gtk, "PackType", types.SimpleNamespace(END="end"), raising=False)
    monkeypatch.setattr(
        console_env.Gtk, "Image", types.SimpleNamespace(new_from_icon_name=lambda *a: object()),
        raising=False,
    )
    monkeypatch.setattr(console_env.Gtk, "ReliefStyle", types.SimpleNamespace(NONE=0), raising=False)
    monkeypatch.setattr(console_env.Gtk, "IconSize", types.SimpleNamespace(MENU=1), raising=False)
    return console_env


def test_the_button_goes_in_the_slot_beyond_the_overflow_arrows(button_env):
    """PackType.END is outside the scroll arrows, which is why it never scrolls away."""
    notebook = FakeNotebook([FakeTabLabel("a")])
    wmain = make_wmain(button_env, FakePaned(notebook))

    button = wmain.install_console_button(notebook)

    assert notebook.get_action_widget("end") is button
    assert button.tooltip == "List open consoles"


def test_the_button_is_not_installed_twice(button_env):
    """A notebook can be reached again; a second button would displace the first."""
    notebook = FakeNotebook([FakeTabLabel("a")])
    wmain = make_wmain(button_env, FakePaned(notebook))

    first = wmain.install_console_button(notebook)

    assert wmain.install_console_button(notebook) is None
    assert notebook.get_action_widget("end") is first


def test_clicking_the_button_fills_its_menu(button_env, monkeypatch):
    monkeypatch.setattr(button_env, "shortcuts", {})
    notebook = FakeNotebook([FakeTabLabel("a"), FakeTabLabel("b")])
    wmain = make_wmain(button_env, FakePaned(notebook))
    button = wmain.install_console_button(notebook)
    popped = []
    monkeypatch.setattr(
        button_env.Gtk, "get_current_event", lambda: object(), raising=False
    )
    monkeypatch.setattr(
        button_env.Gdk, "Gravity",
        types.SimpleNamespace(SOUTH_WEST=0, NORTH_WEST=1), raising=False,
    )
    FakeMenu.popup_at_widget = lambda self, *args: popped.append(self)
    try:
        button.click()
    finally:
        del FakeMenu.popup_at_widget

    assert popped and [item.markup for item in popped[0].items] == ["a", "b"]


class FakeMenuBar:
    def __init__(self, items):
        self.items = items

    def get_children(self):
        return self.items


class FakeTopLevelItem:
    def __init__(self, label, submenu=None):
        self.label = label
        self.submenu = submenu

    def get_label(self):
        return self.label

    def get_submenu(self):
        return self.submenu


def test_the_console_menu_hangs_off_the_terminal_menu(console_env, monkeypatch):
    monkeypatch.setattr(console_env.Gtk, "Menu", FakeMenu, raising=False)
    terminal_menu = FakeMenu()
    terminal_menu.append(FakeMenuItem(label="Close Console"))
    wmain = object.__new__(console_env.Wmain)
    wmain.menuConsoles = FakeMenu()
    wmain.menubar = FakeMenuBar(
        [FakeTopLevelItem("_File", FakeMenu()), FakeTopLevelItem("_Terminal", terminal_menu)]
    )

    item = wmain.install_console_menu()

    assert item is not None and item.label == "Open Consoles"
    assert [type(x).__name__ for x in terminal_menu.items[-2:]] == [
        "FakeSeparator",
        "FakeMenuItem",
    ]
    assert terminal_menu.items[-1].submenu is wmain.menuConsoles


def test_installing_the_console_menu_survives_a_missing_terminal_menu(console_env):
    wmain = object.__new__(console_env.Wmain)
    wmain.menuConsoles = FakeMenu()
    wmain.menubar = FakeMenuBar([FakeTopLevelItem("_File", FakeMenu())])

    assert wmain.install_console_menu() is None


def test_installing_the_console_menu_survives_no_menubar(console_env):
    wmain = object.__new__(console_env.Wmain)
    wmain.menuConsoles = FakeMenu()
    wmain.menubar = None

    assert wmain.install_console_menu() is None


# -- the real widget API the fakes stand in for ------------------------------


def test_gtk_notebook_really_has_an_action_widget_slot():
    """conftest stubs gi, so a fake could offer a slot GtkNotebook does not have."""
    gi = pytest.importorskip("gi", reason="PyGObject not available")
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    for name in ("set_action_widget", "get_action_widget"):
        assert hasattr(Gtk.Notebook, name), f"Gtk.Notebook has no {name}"
    assert hasattr(Gtk.PackType, "END")


def test_the_action_widget_stays_out_of_get_children():
    """find_notebook and the glade placeholder sweep both walk get_children()."""
    gi = pytest.importorskip("gi", reason="PyGObject not available")
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    notebook = Gtk.Notebook()
    notebook.append_page(Gtk.Label(label="page"), Gtk.Label(label="tab"))
    button = Gtk.Button(label="menu")
    notebook.set_action_widget(button, Gtk.PackType.END)

    assert button not in notebook.get_children()
    assert notebook.get_n_pages() == 1
    assert notebook.page_num(button) == -1


def test_check_menu_item_really_draws_as_a_radio():
    gi = pytest.importorskip("gi", reason="PyGObject not available")
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    item = Gtk.CheckMenuItem(label="")
    item.set_draw_as_radio(True)

    assert item.get_draw_as_radio()
    assert isinstance(item.get_children()[0], Gtk.AccelLabel)


def test_set_attention_records_the_flag_it_styles(app_module):
    """The entry reads this back; a style class is only answerable once realized."""
    label = object.__new__(app_module.NotebookTabLabel)
    classes = set()
    label.get_style_context = lambda: types.SimpleNamespace(
        add_class=classes.add, remove_class=classes.discard
    )

    app_module.NotebookTabLabel.set_attention(label, True)
    assert label.needs_attention is True and "attention" in classes

    app_module.NotebookTabLabel.set_attention(label, False)
    assert label.needs_attention is False and "attention" not in classes


def test_get_display_text_returns_what_the_tab_renders(app_module):
    """render_label puts host and terminal title here; get_text() holds the identity."""
    label = object.__new__(app_module.NotebookTabLabel)
    label.title = "  web-01  "
    label.label = types.SimpleNamespace(get_text=lambda: "  web-01: htop  ")

    assert app_module.NotebookTabLabel.get_display_text(label) == "  web-01: htop  "
    assert app_module.NotebookTabLabel.get_text(label) == "  web-01  "
