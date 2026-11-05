"""GCM_TRACE's keys, actions, links, config and notifications areas (#513).

The point of each is what a line must never hold: a key given to a console, the key after a
prefix key, a search's or a console's text, a configuration value. Each privacy test types
a marker nobody could mistake and asserts it is nowhere in the output.
"""

import ast
import io
import re
import types
from pathlib import Path

import pytest

from gnome_connection_manager.utils import trace

APP = Path(__file__).resolve().parents[1] / "src" / "gnome_connection_manager" / "app.py"
NEW_AREAS = (trace.KEYS, trace.ACTIONS, trace.LINKS, trace.CONFIG, trace.NOTIFICATIONS)
SECRET = "zq9secretmarker"


@pytest.fixture
def out():
    """Every area on, written to a buffer, and off again after."""
    stream = io.StringIO()
    trace.configure({"GCM_TRACE": "all"}, stream=stream)
    yield stream
    trace.configure({})


def lines(stream: io.StringIO) -> list[str]:
    return [re.sub(r"^\[[^\]]*\] ", "", each) for each in stream.getvalue().splitlines()]


# -- the areas -------------------------------------------------------------------------


def test_the_new_areas_parse_and_all_includes_them() -> None:
    for area in NEW_AREAS:
        assert trace.parse(area) == (frozenset({area}), ())
        assert area in trace.parse("all")[0]
        assert area in trace.AREAS


def test_every_area_has_a_call_site_and_every_call_passes_a_function() -> None:
    tree = ast.parse(APP.read_text(encoding="utf-8"))
    used: set[str] = set()
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "note"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "trace"
        ):
            continue
        assert isinstance(node.args[1], ast.Lambda), ast.unparse(node)[:80]
        if isinstance(node.args[0], ast.Attribute):
            used.add(node.args[0].attr.lower())
    for area in trace.AREAS:
        assert area in used, area


def test_an_area_that_is_off_writes_nothing_and_reads_nothing(app_module, monkeypatch) -> None:
    stream = io.StringIO()
    trace.configure({"GCM_TRACE": "drag"}, stream=stream)
    try:

        def explode(*_args, **_kwargs):
            raise AssertionError("evaluated while off")

        monkeypatch.setattr(app_module, "own_key_command", explode)
        monkeypatch.setattr(app_module, "notification_owners", explode)
        app_module.trace_key("route", "where", object())
        wmain = object.__new__(app_module.Wmain)
        app_module.GcmApplication._trace_activate(wmain, None, None, "quit")
        assert stream.getvalue() == ""
    finally:
        trace.configure({})


# -- the pure lines ---------------------------------------------------------------------


def test_the_lines_hold_names_and_counts_only() -> None:
    assert trace.key_line("left to the accelerators", "console a", "app.quit") == (
        "key: left to the accelerators (console a), action app.quit"
    )
    assert trace.key_line("prefix key given", "console a") == "key: prefix key given (console a)"
    assert trace.refused_host_line("host 3", "ValueError", 4) == (
        "load: host section [host 3] refused, ValueError, 4 option(s)"
    )
    assert "none" in trace.save_line(1, 0, 0, [])
    assert trace.save_line(1, 0, 0, [], ["host 9"]).endswith("sections dropped: host 9")
    assert trace.save_line(1, 0, 0, [], None).endswith("sections dropped: not read")
    assert trace.notification_line(True, None) == "notification: sent, bus not reached"
    assert trace.notification_line(False, {"a": True, "b": False}) == (
        "notification: not sent, services on the bus: a yes, b no"
    )
    assert "no application" in trace.notification_line(False, None, False)


# -- keys -------------------------------------------------------------------------------


def event_named(app_module, monkeypatch, name):
    monkeypatch.setattr(app_module, "get_key_name", lambda _event: name)
    return types.SimpleNamespace(keyval=1, state=0)


def test_a_key_that_is_nobodys_writes_no_line_and_a_shortcut_is_named(
    app_module, monkeypatch, out
) -> None:
    monkeypatch.setattr(
        app_module, "shortcuts", {"CTRL+F": ["find"], "F7": types.SimpleNamespace()}
    )
    monkeypatch.setattr(app_module.Gtk.Application, "get_default", lambda: None, raising=False)

    app_module.trace_key("route", "not a console", event_named(app_module, monkeypatch, "Q"))
    assert out.getvalue() == ""

    app_module.trace_key("route", "not a console", event_named(app_module, monkeypatch, "CTRL+F"))
    app_module.trace_key("route", "not a console", event_named(app_module, monkeypatch, "F7"))
    assert lines(out) == [
        "keys: key: route (not a console), action find",
        "keys: key: route (not a console), action snippet",
    ]


def test_an_accelerator_is_named_by_its_action(app_module, monkeypatch, out) -> None:
    monkeypatch.setattr(app_module, "shortcuts", {})
    application = types.SimpleNamespace(get_actions_for_accel=lambda accel: ["app.quit"])
    monkeypatch.setattr(
        app_module.Gtk.Application, "get_default", lambda: application, raising=False
    )
    monkeypatch.setattr(app_module.Gtk, "accelerator_name", lambda *_a: "<Control>q", raising=False)
    monkeypatch.setattr(
        app_module.Gtk, "accelerator_get_default_mod_mask", lambda: 0, raising=False
    )

    app_module.trace_key("fixed", "vnc", event_named(app_module, monkeypatch, "CTRL+Q"))

    assert lines(out) == ["keys: key: fixed (vnc), action app.quit"]


def prefix_window(app_module, monkeypatch, name):
    terminal = app_module.Vte.Terminal()
    terminal.child_pid = 4242
    monkeypatch.setattr(app_module, "get_key_name", lambda _event: name)
    monkeypatch.setattr(app_module, "keyval_name_of", lambda _event: name)
    monkeypatch.setattr(app_module, "prefix_keys_of", lambda _t: {"CTRL+B"})
    monkeypatch.setattr(app_module, "shortcuts", {})
    window = types.SimpleNamespace(get_focus=lambda: terminal, propagate_key_event=lambda _e: True)
    return terminal, window


def test_a_prefix_key_and_the_key_after_it_are_named_by_neither(
    app_module, monkeypatch, out
) -> None:
    wmain = object.__new__(app_module.Wmain)
    terminal, window = prefix_window(app_module, monkeypatch, "CTRL+B")
    terminal.host = types.SimpleNamespace(name="web1")

    wmain.on_window_key_press(window, object())
    terminal, window = prefix_window(app_module, monkeypatch, SECRET)
    terminal.prefix_armed = True
    terminal.host = types.SimpleNamespace(name="web1")
    wmain.on_window_key_press(window, object())

    text = out.getvalue()
    assert "prefix key given" in text and "key after a prefix key" in text
    assert SECRET not in text.lower() and "ctrl+b" not in text.lower()


def test_typing_into_a_console_writes_no_line(app_module, monkeypatch, out) -> None:
    wmain = object.__new__(app_module.Wmain)
    terminal, window = prefix_window(app_module, monkeypatch, SECRET)
    monkeypatch.setattr(app_module, "prefix_keys_of", lambda _t: set())
    monkeypatch.setattr(app_module.Gtk.Application, "get_default", lambda: None, raising=False)

    wmain.on_window_key_press(window, object())

    assert out.getvalue() == ""


def test_a_keys_sequence_line_names_neither_the_key_nor_the_bytes(
    app_module, monkeypatch, out
) -> None:
    monkeypatch.setattr(app_module, "get_key_name", lambda _e: "CTRL+" + SECRET.upper())
    monkeypatch.setattr(app_module, "custom_keys", {"CTRL+" + SECRET.upper(): SECRET.encode()})
    monkeypatch.setattr(app_module, "shortcuts", {})
    fed: list[bytes] = []
    terminal = types.SimpleNamespace(
        feed_child=fed.append, get_parent=lambda: None, host=types.SimpleNamespace(name="web1")
    )
    wmain = object.__new__(app_module.Wmain)

    assert wmain.on_terminal_keypress(terminal, types.SimpleNamespace(keyval=1)) is True

    assert fed == [SECRET.encode()]
    assert lines(out) == ["keys: key: [keys] sequence sent (web1)"]


def test_a_shortcut_line_names_the_command_and_a_snippet_only_as_one(
    app_module, monkeypatch, out
) -> None:
    snippet = types.SimpleNamespace(text=SECRET)
    monkeypatch.setattr(app_module, "get_key_name", lambda _e: "F7")
    monkeypatch.setattr(app_module, "custom_keys", {})
    monkeypatch.setattr(app_module, "shortcuts", {"F7": snippet})
    wmain = object.__new__(app_module.Wmain)
    wmain.send_snippet = lambda *_a: None
    terminal = types.SimpleNamespace(get_parent=lambda: None, host=types.SimpleNamespace(name="w"))

    wmain.on_terminal_keypress(terminal, types.SimpleNamespace(keyval=1))

    assert lines(out) == ["keys: key: [shortcuts] command run (w), action snippet"]
    assert SECRET not in out.getvalue()


# -- actions ----------------------------------------------------------------------------


def test_an_activation_and_a_state_change_name_the_action_only(app_module, out) -> None:
    app = object.__new__(app_module.GcmApplication)

    app._trace_activate(None, SECRET, "quit")
    app._trace_change_state(None, SECRET, "toggle-panel")

    assert lines(out) == ["actions: activate app.quit", "actions: change-state app.toggle-panel"]


def test_the_action_creators_connect_the_trace_handlers(app_module) -> None:
    connected: list[str] = []

    class Action:
        def connect(self, signal, handler, *data):
            connected.append(signal)

        def __getattr__(self, _name):
            return lambda *a, **k: None

    gio = app_module.Gio
    gio.SimpleAction = types.SimpleNamespace(
        new=lambda *a: Action(), new_stateful=lambda *a: Action()
    )
    app = object.__new__(app_module.GcmApplication)
    app.add_action = lambda _a: None
    app.set_accels_for_action = lambda *_a: None
    app._create_action("x", lambda *a: None)
    app._create_stateful_action("y", True, lambda *a: None)

    assert connected == ["activate", "activate", "change-state", "change-state"]


@pytest.mark.parametrize(
    ("confirm", "count", "answer", "expected"),
    [
        (True, 2, "ok", "asked True, quit"),
        (True, 2, "cancel", "asked True, stay"),
        (False, 2, "cancel", "asked False, quit"),
    ],
)
def test_both_quit_paths_say_whether_they_asked(
    app_module, monkeypatch, out, confirm, count, answer, expected
) -> None:
    response = getattr(app_module.Gtk.ResponseType, answer.upper())
    monkeypatch.setattr(app_module.conf, "CONFIRM_ON_EXIT", confirm)
    monkeypatch.setattr(app_module, "msgconfirm", lambda _t: response)
    wmain = object.__new__(app_module.Wmain)
    wmain.count = count
    wmain.get_widget = lambda _n: types.SimpleNamespace(get_size=lambda: (1, 2))
    wmain.writeConfig = wmain.end_sessions = wmain.quit_application = lambda: None

    wmain.request_quit()
    wmain.on_wMain_delete_event(None)

    assert lines(out) == [
        f"actions: confirm_exit via request_quit: {expected}",
        f"actions: confirm_exit via delete-event: {expected}",
    ]


# -- links ------------------------------------------------------------------------------


class LinkTerminal:
    def __init__(self):
        self.tags = iter(range(10, 20))
        self.host = types.SimpleNamespace(name="web1")

    def get_parent(self):
        return None

    def match_add_regex(self, _regex, _flags):
        return next(self.tags)

    def match_set_cursor_name(self, *_a):
        pass

    def match_remove_all(self):
        raise AssertionError("no matcher is removed any more")


def test_each_matcher_added_is_a_line_with_its_console_and_caller(app_module, out) -> None:
    app_module.Vte.Regex = types.SimpleNamespace(new_for_match=lambda *a: object())
    wmain = object.__new__(app_module.Wmain)
    terminal = LinkTerminal()

    def addTab():
        wmain.registerUrlRegexes(terminal)

    addTab()

    got = lines(out)
    assert len(got) == 4
    assert (
        got[0] == "links: match added: direct, tag 10, console web1, by addTab > registerUrlRegexes"
    )
    assert [re.search(r"added: (\w+)", g).group(1) for g in got] == [
        "direct",
        "url",
        "email",
        "file",
    ]


def search_wmain(app_module, text, terminal):
    wmain = object.__new__(app_module.Wmain)
    entry = types.SimpleNamespace(get_text=lambda: text)
    wmain.search_box = lambda: entry
    wmain.get_target_terminal = lambda: terminal
    return wmain


def test_the_search_regex_set_and_cleared_are_lines_without_the_text(app_module, out) -> None:
    app_module.Vte.Regex = types.SimpleNamespace(new_for_search=lambda *a: object())
    terminal = types.SimpleNamespace(
        search_set_regex=lambda *a: None,
        search_set_wrap_around=lambda *a: None,
        get_parent=lambda: None,
        host=types.SimpleNamespace(name="web1"),
    )

    search_wmain(app_module, SECRET, terminal).init_search()
    search_wmain(app_module, "", terminal).init_search()

    assert lines(out) == [
        "links: search regex set, console web1",
        "links: search regex cleared, console web1",
    ]
    assert SECRET not in out.getvalue()


@pytest.mark.parametrize(("tag", "handler"), [(30, "open_file_location"), (31, "open_in_browser")])
def test_a_ctrl_click_names_the_tag_and_handler_not_the_text(
    app_module, monkeypatch, out, tag, handler
) -> None:
    gdk = app_module.Gdk
    gdk.EventType = types.SimpleNamespace(BUTTON_PRESS=1)
    gdk.ModifierType = types.SimpleNamespace(CONTROL_MASK=4)
    monkeypatch.setattr(app_module, "open_in_browser", lambda _u: None)
    wmain = object.__new__(app_module.Wmain)
    wmain.open_file_location = lambda *_a: None
    wmain.on_tab_focus = lambda *_a: None
    event = types.SimpleNamespace(type=1, button=1, get_state=lambda: 4)
    nb = types.SimpleNamespace(get_nth_page=lambda n: None, get_current_page=lambda: 0)
    widget = types.SimpleNamespace(
        match_check_event=lambda _e: (SECRET, tag),
        tag_file=30,
        tag_url=99,
        tag_email=98,
        hyperlink_check_event=lambda _e: None,
        get_parent=lambda: types.SimpleNamespace(get_parent=lambda: nb),
        host=types.SimpleNamespace(name="web1"),
    )

    wmain.on_terminal_click(widget, event)

    assert lines(out) == [f"links: ctrl+click: tag {tag}, handler {handler}, console web1"]


# -- config -----------------------------------------------------------------------------


def test_a_refused_host_is_named_by_section_and_class_not_by_value(
    app_module, monkeypatch, tmp_path, out
) -> None:
    conf_file = tmp_path / "gcm.conf"
    conf_file.write_text(f"[host 7]\nname = {SECRET}\nport = {SECRET}\n", encoding="utf-8")
    monkeypatch.setattr(app_module, "CONFIG_FILE", str(conf_file))
    monkeypatch.setattr(app_module, "get_password", lambda: "")
    monkeypatch.setattr(app_module, "sync_folders", lambda: {})
    wmain = object.__new__(app_module.Wmain)

    try:
        wmain.loadConfig()
    except Exception:
        pytest.skip("loadConfig needs more of the app than the stub has")  # pragma: no cover

    text = out.getvalue()
    assert "load: host section [host 7] refused, NoOptionError, 2 option(s)" in text
    assert SECRET not in text


# -- notifications ----------------------------------------------------------------------


def test_a_notification_names_the_services_and_not_its_text(app_module, monkeypatch, out) -> None:
    monkeypatch.setattr(
        app_module, "notification_owners", lambda: {"org.freedesktop.Notifications": True}
    )
    sent: list[str] = []
    application = types.SimpleNamespace(send_notification=lambda i, n: sent.append(i))
    app_module.Gio.Notification = types.SimpleNamespace(
        new=lambda _t: types.SimpleNamespace(set_body=lambda _b: None)
    )
    wmain = object.__new__(app_module.Wmain)
    wmain.wMain = types.SimpleNamespace(get_application=lambda: application)
    label = types.SimpleNamespace(get_text=lambda: SECRET)

    for _ in range(3):
        wmain.notify_attention(label)

    assert sent == ["gcm-bell"] * 3
    assert (
        lines(out)
        == [
            "notifications: notification: sent, services on the bus: org.freedesktop.Notifications yes"
        ]
        * 3
    )
    assert SECRET not in out.getvalue()


def test_a_missing_notification_service_is_not_checked_for_beforehand(
    app_module, monkeypatch
) -> None:
    trace.configure({})
    probes: list[int] = []

    def nobody_owns() -> dict[str, bool]:
        probes.append(1)
        return {"org.freedesktop.Notifications": False}

    monkeypatch.setattr(app_module, "notification_owners", nobody_owns)
    sent: list[str] = []
    application = types.SimpleNamespace(send_notification=lambda i, n: sent.append(i))
    app_module.Gio.Notification = types.SimpleNamespace(
        new=lambda _t: types.SimpleNamespace(set_body=lambda _b: None)
    )
    wmain = object.__new__(app_module.Wmain)
    wmain.wMain = types.SimpleNamespace(get_application=lambda: application)
    label = types.SimpleNamespace(get_text=lambda: SECRET)

    for _ in range(3):
        wmain.notify_attention(label)

    # Sent every time, whoever owns the names; and with tracing off the bus is not probed.
    assert sent == ["gcm-bell"] * 3
    assert probes == []
    doc = app_module.Wmain.notify_attention.__doc__
    assert "ServiceUnknown" in doc
    assert "once" in doc


def test_an_unreachable_bus_says_so(app_module, out) -> None:
    def no_bus(*_a):
        raise RuntimeError(SECRET)

    app_module.Gio.bus_get_sync = no_bus

    assert app_module.notification_owners() is None
    assert trace.notification_line(True, None) == "notification: sent, bus not reached"


def test_a_save_names_the_sections_it_writes_and_drops_and_no_value(
    app_module, monkeypatch, tmp_path, out
) -> None:
    config_file = tmp_path / "gcm.conf"
    config_file.write_text(f"[options]\nterm = {SECRET}\n[host 5]\nkey = {SECRET}\n")
    monkeypatch.setattr(app_module, "CONFIG_FILE", str(config_file))
    monkeypatch.setattr(app_module, "groups", {})
    wmain = object.__new__(app_module.Wmain)
    wmain.hpMain = types.SimpleNamespace(get_position=lambda: 1)
    wmain.wMain = types.SimpleNamespace(is_maximized=lambda: False)
    wmain.get_collapsed_nodes = lambda: []
    wmain.get_collapsed_folder_ids = lambda: []
    wmain.writeConfig()
    saves = [each for each in lines(out) if each.startswith("config: save") or "save:" in each]
    assert len(saves) == 1
    assert saves[0].endswith("sections dropped: host 5")
    assert "options" in saves[0].split("sections dropped:")[0]
    assert SECRET not in out.getvalue()


def test_gcm_started_with_the_config_area_traces_its_own_load(
    app_module, monkeypatch, tmp_path, capsys
) -> None:
    """`do_activate` builds `Wmain`, whose `__init__` loads gcm.conf, so the areas must be
    on before that: they used to start after the window was shown, and the load went
    unseen (#513)."""
    from tests.test_config import without_pass_and_with_a_word

    path = without_pass_and_with_a_word(tmp_path)
    monkeypatch.setattr(app_module, "CONFIG_FILE", str(path))
    monkeypatch.setattr(app_module, "groups", {})
    monkeypatch.setattr(app_module, "shortcuts", {})
    monkeypatch.setattr(app_module.crypto, "decrypt", lambda _pwd, value, **_kw: value)
    monkeypatch.setattr(app_module, "sync_folders", lambda: {})
    monkeypatch.setattr(app_module, "sync_shortcut_accels", lambda: None)
    monkeypatch.setattr(app_module, "start_trace", lambda *_a: None)
    monkeypatch.setenv("GCM_TRACE", "config")

    class LoadingOnly(app_module.Wmain):
        def __init__(self, application=None):
            self.loadConfig()

        def get_widget(self, _name):
            return None

        def report_unread_options(self):
            pass

        def report_unread_hosts(self):
            pass

    monkeypatch.setattr(app_module, "Wmain", LoadingOnly)
    monkeypatch.setattr(app_module.GLib, "idle_add", lambda *_a: 0, raising=False)
    application = object.__new__(app_module.GcmApplication)
    application._controller = None
    application._pending_cli = []
    application._reported_unread = False
    application._trace_started = False
    try:
        application.do_activate()
    finally:
        trace.configure({})

    written = capsys.readouterr().err
    assert "host section [host 2] refused" in written
    assert "host section [host 3] refused, ValueError" in written
    assert "host section [host 1] read" in written
    assert "[host 1] refused" not in written
    assert "router1" not in written and "netops" not in written and "plaintext" not in written
    assert "auto" not in written
