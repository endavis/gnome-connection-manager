"""Tests covering configuration persistence helpers in app.py."""

from __future__ import annotations

import configparser
import re
import types
from pathlib import Path


def make_host(app_module):
    """Create a sample Host instance for config round-trips."""
    return app_module.Host(
        "ops/prod",
        "router",
        "edge router",
        "router.example.com",
        "netops",
        "secret",
        "/home/netops/.ssh/id_rsa",
        "2200",
        "L8080:localhost:80",
        "ssh",
        "echo hello\nrun-checks",
        "30",
        "#111111",
        "#222222",
        True,
        True,
        False,
        "5",
        "-oStrictHostKeyChecking=no",
        True,
        7,
        8,
        "xterm-256color",
    )


def test_load_config_populates_conf_groups_and_shortcuts(tmp_path, app_module, monkeypatch):
    """Ensure loadConfig reads options, shortcuts, and host data."""
    config = configparser.RawConfigParser()
    config.add_section("options")
    config.set("options", "word-separators", "***")
    config.set("options", "buffer-lines", "4096")
    config.set("options", "startup-local", "false")
    config.set("options", "log-local", "true")
    config.set("options", "confirm-exit", "false")
    config.set("options", "font-color", "#010203")
    config.set("options", "back-color", "#030201")
    config.set("options", "term", "vt100")
    config.set("options", "transparency", "5")
    config.set("options", "paste-right-click", "false")
    config.set("options", "confirm-close-tab", "false")
    config.set("options", "confirm-close-tab-middle", "false")
    config.set("options", "check-updates", "false")
    config.set("options", "font", "Monospace 12")
    config.set("options", "donate", "true")
    config.set("options", "disable-hosts-stripes", "true")
    config.set("options", "auto-copy-selection", "true")
    config.set("options", "log-path", "/tmp/logs")
    config.set("options", "version", "99")
    config.set("options", "auto-close-tab", "2")
    config.set("options", "cycle-tabs", "false")
    config.set("options", "update-title", "true")
    config.set("options", "app-title", "Custom App")

    config.add_section("window")
    config.set("window", "collapsed-folders", "0,1")
    config.set("window", "left-panel-width", "222")
    config.set("window", "window-width", "800")
    config.set("window", "window-height", "600")
    config.set("window", "show-panel", "false")
    config.set("window", "show-toolbar", "false")

    config.add_section("shortcuts")
    config.set("shortcuts", "copy", "CTRL+ALT+C")
    config.set("shortcuts", "shortcut1", "ALT+R")
    config.set("shortcuts", "command1", "reboot\\nnow")

    config.add_section("host 1")
    config.set("host 1", "group", "ops/prod")
    config.set("host 1", "name", "router")
    config.set("host 1", "host", "router.example.com")
    config.set("host 1", "user", "netops")
    config.set("host 1", "pass", "plaintext")
    config.set("host 1", "description", "edge router")
    config.set("host 1", "private_key", "/home/netops/.ssh/id_rsa")
    config.set("host 1", "port", "2200")
    config.set("host 1", "tunnel", "L8080:localhost:80")
    config.set("host 1", "type", "ssh")
    config.set("host 1", "commands", "echo hello\\nrun-checks")
    config.set("host 1", "keepalive", "60")
    config.set("host 1", "font-color", "#111111")
    config.set("host 1", "back-color", "#222222")
    config.set("host 1", "x11", "true")
    config.set("host 1", "agent", "true")
    config.set("host 1", "compression", "true")
    config.set("host 1", "compression-level", "5")
    config.set("host 1", "extra_params", "-oStrictHostKeyChecking=no")
    config.set("host 1", "log", "true")
    config.set("host 1", "backspace-key", "1")
    config.set("host 1", "delete-key", "2")
    config.set("host 1", "term", "xterm-256color")

    config_path = tmp_path / "gcm.conf"
    with config_path.open("w") as handle:
        config.write(handle)

    monkeypatch.setattr(app_module, "CONFIG_FILE", str(config_path))
    monkeypatch.setattr(app_module, "groups", {})
    monkeypatch.setattr(app_module, "shortcuts", {})
    monkeypatch.setattr(app_module.crypto, "decrypt", lambda _pwd, value, **_kw: value)

    wmain = object.__new__(app_module.Wmain)
    wmain.loadConfig()

    assert app_module.conf.WORD_SEPARATORS == "***"
    assert app_module.conf.BUFFER_LINES == 4096
    assert app_module.conf.CHECK_UPDATES is False
    assert app_module.conf.COLLAPSED_FOLDERS == "0,1"
    assert app_module.conf.APP_TITLE == "Custom App"

    assert "ops/prod" in app_module.groups
    host = app_module.groups["ops/prod"][0]
    assert host.name == "router"
    assert host.commands == "echo hello\nrun-checks"
    assert host.password == "plaintext"

    assert app_module.shortcuts["CTRL+ALT+C"] == app_module._COPY
    assert app_module.shortcuts["ALT+R"] == "reboot\nnow"


def test_write_config_persists_conf_window_hosts_and_shortcuts(tmp_path, app_module, monkeypatch):
    """Ensure writeConfig serializes runtime values back to disk."""
    config_file = tmp_path / "gcm.conf"
    monkeypatch.setattr(app_module, "CONFIG_FILE", str(config_file))
    monkeypatch.setattr(app_module.crypto, "encrypt", lambda _pwd, value: value)

    conf = app_module.conf
    conf.WORD_SEPARATORS = "abc"
    conf.BUFFER_LINES = 2048
    conf.STARTUP_LOCAL = False
    conf.LOG_LOCAL = True
    conf.CONFIRM_ON_EXIT = False
    conf.FONT_COLOR = "#000001"
    conf.BACK_COLOR = "#010000"
    conf.TERM = "screen"
    conf.TRANSPARENCY = 7
    conf.PASTE_ON_RIGHT_CLICK = 0
    conf.CONFIRM_ON_CLOSE_TAB = False
    conf.CONFIRM_ON_CLOSE_TAB_MIDDLE = False
    conf.CHECK_UPDATES = False
    conf.FONT = "Monospace 10"
    conf.HIDE_DONATE = True
    conf.DISABLE_HOSTS_STRIPES = True
    conf.AUTO_COPY_SELECTION = True
    conf.LOG_PATH = "/tmp/custom-logs"
    conf.AUTO_CLOSE_TAB = 3
    conf.CYCLE_TABS = False
    conf.UPDATE_TITLE = True
    conf.APP_TITLE = "Persist Title"
    conf.SHOW_PANEL = False
    conf.SHOW_TOOLBAR = False
    conf.LEFT_PANEL_WIDTH = 444
    conf.WINDOW_WIDTH = 1024
    conf.WINDOW_HEIGHT = 768

    host = make_host(app_module)
    monkeypatch.setattr(app_module, "groups", {"ops/prod": [host]})
    monkeypatch.setattr(
        app_module,
        "shortcuts",
        {"CTRL+ALT+C": app_module._COPY, "ALT+R": "reboot now"},
    )

    hp_stub = types.SimpleNamespace(get_position=lambda: 333)
    wmain = object.__new__(app_module.Wmain)
    wmain.hpMain = hp_stub
    wmain.wMain = types.SimpleNamespace(is_maximized=lambda: False)
    wmain.get_collapsed_nodes = lambda: ["0", "2"]
    wmain.get_collapsed_folder_ids = lambda: []

    wmain.writeConfig()

    cp = configparser.RawConfigParser()
    cp.read(config_file)

    assert cp.get("options", "word-separators") == "abc"
    assert cp.getint("options", "buffer-lines") == 2048
    assert cp.get("options", "font-color") == "#000001"
    assert cp.get("options", "term") == "screen"
    assert cp.get("options", "log-path") == "/tmp/custom-logs"
    assert cp.get("window", "collapsed-folders") == "0,2"
    assert cp.getint("window", "left-panel-width") == 333
    assert cp.getint("window", "window-width") == 1024
    assert cp.getboolean("window", "show-toolbar") is False

    assert cp.get("shortcuts", "copy") == "CTRL+ALT+C"
    assert cp.get("shortcuts", "shortcut1") == "ALT+R"
    assert cp.get("shortcuts", "command1") == "reboot now"

    assert cp.has_section("host 1")
    assert cp.get("host 1", "group") == "ops/prod"
    assert cp.get("host 1", "name") == "router"
    assert cp.get("host 1", "host") == "router.example.com"
    assert cp.get("host 1", "pass") == "secret"
    assert cp.get("host 1", "commands") == "echo hello\\nrun-checks"


def _load_with(tmp_path, app_module, monkeypatch, options, window=None):
    """Run loadConfig against a gcm.conf built from `options`/`window`."""
    config = configparser.RawConfigParser()
    config.add_section("options")
    for key, value in options.items():
        config.set("options", key, value)
    config.add_section("window")
    for key, value in (window or {}).items():
        config.set("window", key, value)

    config_path = tmp_path / "gcm.conf"
    with config_path.open("w") as handle:
        config.write(handle)

    monkeypatch.setattr(app_module, "CONFIG_FILE", str(config_path))
    monkeypatch.setattr(app_module, "groups", {})
    monkeypatch.setattr(app_module, "shortcuts", {})

    wmain = object.__new__(app_module.Wmain)
    wmain.loadConfig()
    return app_module.conf


def test_load_config_missing_option_still_applies_the_later_ones(tmp_path, app_module, monkeypatch):
    """A key absent from an older gcm.conf must not discard the keys after it."""
    conf = _load_with(
        tmp_path,
        app_module,
        monkeypatch,
        # "buffer-lines" deliberately omitted; everything below it is present
        {
            "word-separators": "***",
            "auto-copy-selection": "true",
            "log-path": "/tmp/custom-logs",
            "term": "xterm-kitty",
            "app-title": "Custom App",
        },
    )

    assert conf.BUFFER_LINES == 10000  # absent -> default
    assert conf.AUTO_COPY_SELECTION is True
    assert conf.LOG_PATH == "/tmp/custom-logs"
    assert conf.TERM == "xterm-kitty"
    assert conf.APP_TITLE == "Custom App"


def test_load_config_malformed_value_only_affects_its_own_option(tmp_path, app_module, monkeypatch):
    conf = _load_with(
        tmp_path,
        app_module,
        monkeypatch,
        {
            "buffer-lines": "not-a-number",
            "transparency": "also-not-a-number",
            "term": "xterm-kitty",
            "app-title": "Custom App",
        },
    )

    assert conf.BUFFER_LINES == 10000
    assert conf.TRANSPARENCY == 0
    assert conf.TERM == "xterm-kitty"
    assert conf.APP_TITLE == "Custom App"


def test_load_config_without_a_config_file_falls_back_to_defaults(
    tmp_path, app_module, monkeypatch
):
    monkeypatch.setattr(app_module, "CONFIG_FILE", str(tmp_path / "absent.conf"))
    monkeypatch.setattr(app_module, "groups", {})
    monkeypatch.setattr(app_module, "shortcuts", {})

    wmain = object.__new__(app_module.Wmain)
    wmain.loadConfig()

    default_title = app_module.app_name
    assert app_module.conf.BUFFER_LINES == 10000
    assert default_title == app_module.conf.APP_TITLE


def test_config_options_table_matches_the_conf_defaults(app_module):
    """Every table entry must name a real conf attribute, and names must be unique."""
    seen = set()
    for attr, section, option, kind in app_module.CONFIG_OPTIONS:
        assert hasattr(app_module.conf, attr), f"conf has no attribute {attr}"
        assert section in ("options", "window"), f"{attr}: unexpected section {section}"
        assert kind in (str, int, bool), f"{attr}: unexpected type {kind}"
        assert (section, option) not in seen, f"duplicate entry for [{section}] {option}"
        seen.add((section, option))


def test_config_options_table_covers_everything_write_config_persists(app_module):
    """Guards against an option being written but never read back (see #34)."""
    source = Path(app_module.__file__).read_text()
    body = source.split("def writeConfig", 1)[1].split("def ", 1)[0]
    written = set(re.findall(r'cp\.set\(\s*"(options|window)",\s*"([a-z0-9-]+)"', body))
    known = {(section, option) for _attr, section, option, _kind in app_module.CONFIG_OPTIONS}

    # "version" is written as the running app version rather than from conf
    assert written - known == set(), f"written but never read: {sorted(written - known)}"


def _load_with_keys(tmp_path, app_module, monkeypatch, keys, shortcuts=None):
    config = configparser.RawConfigParser()
    config.add_section("shortcuts")
    for command, key in (shortcuts or {"copy": "CTRL+SHIFT+C"}).items():
        config.set("shortcuts", command, key)
    if keys is not None:
        config.add_section("keys")
        for name, value in keys.items():
            config.set("keys", name, value)

    config_path = tmp_path / "gcm.conf"
    with config_path.open("w") as handle:
        config.write(handle)

    monkeypatch.setattr(app_module, "CONFIG_FILE", str(config_path))
    monkeypatch.setattr(app_module, "groups", {})
    monkeypatch.setattr(app_module, "shortcuts", {})
    monkeypatch.setattr(app_module, "custom_keys", {})
    monkeypatch.setattr(app_module.crypto, "decrypt", lambda _pwd, value, **_kw: value)

    object.__new__(app_module.Wmain).loadConfig()
    return app_module.custom_keys


def test_load_config_reads_the_keys_section(tmp_path, app_module, monkeypatch):
    """Without this the section is silently inert -- the bindings simply never exist."""
    loaded = _load_with_keys(
        tmp_path, app_module, monkeypatch, {"SHIFT+RETURN": "\\n", "ALT+RETURN": "\\x1b\\r"}
    )

    assert loaded == {"SHIFT+RETURN": b"\n", "ALT+RETURN": b"\x1b\r"}


def test_load_config_refuses_a_key_a_shortcut_already_claims(tmp_path, app_module, monkeypatch):
    loaded = _load_with_keys(
        tmp_path,
        app_module,
        monkeypatch,
        {"CTRL+ALT+C": "\\n", "SHIFT+RETURN": "\\n"},
        shortcuts={"copy": "CTRL+ALT+C"},
    )

    assert "CTRL+ALT+C" not in loaded
    assert loaded == {"SHIFT+RETURN": b"\n"}


def test_load_config_refuses_a_key_an_application_accelerator_claims(
    tmp_path, app_module, monkeypatch
):
    loaded = _load_with_keys(tmp_path, app_module, monkeypatch, {"CTRL+Q": "\\n"})

    assert loaded == {}


def test_load_config_without_a_keys_section_is_fine(tmp_path, app_module, monkeypatch):
    assert _load_with_keys(tmp_path, app_module, monkeypatch, None) == {}


def write_minimal_hosts_config(tmp_path, entries):
    """A gcm.conf holding nothing but host sections.

    `entries` is one dict of extra keys per host; everything else is filled in so the
    sections parse. loadConfig tolerates the missing options/window/shortcuts sections.
    """
    config = configparser.RawConfigParser()
    for index, extra in enumerate(entries, 1):
        section = f"host {index}"
        config.add_section(section)
        config.set(section, "group", "ops")
        config.set(section, "name", f"router{index}")
        config.set(section, "host", f"router{index}.example.com")
        config.set(section, "user", "netops")
        config.set(section, "pass", "plaintext")
        for key, value in extra.items():
            config.set(section, key, value)
    config_path = tmp_path / "gcm.conf"
    with config_path.open("w") as handle:
        config.write(handle)
    return config_path


def load_hosts(app_module, monkeypatch, config_path):
    monkeypatch.setattr(app_module, "CONFIG_FILE", str(config_path))
    monkeypatch.setattr(app_module, "groups", {})
    monkeypatch.setattr(app_module, "shortcuts", {})
    monkeypatch.setattr(app_module.crypto, "decrypt", lambda _pwd, value, **_kw: value)
    object.__new__(app_module.Wmain).loadConfig()
    return [host for hosts in app_module.groups.values() for host in hosts]


def test_load_config_gives_ids_to_a_config_written_before_adr_0001(
    tmp_path, app_module, monkeypatch
):
    path = write_minimal_hosts_config(tmp_path, [{}, {}, {}])

    loaded = load_hosts(app_module, monkeypatch, path)

    assert len(loaded) == 3
    assert all(host.id for host in loaded)
    assert len({host.id for host in loaded}) == 3


def test_load_config_keeps_the_stored_ids(tmp_path, app_module, monkeypatch):
    path = write_minimal_hosts_config(tmp_path, [{"id": "aaaa1111"}, {"id": "bbbb2222"}])

    loaded = load_hosts(app_module, monkeypatch, path)

    assert sorted(host.id for host in loaded) == ["aaaa1111", "bbbb2222"]


def test_load_config_repairs_a_duplicate_id(tmp_path, app_module, monkeypatch):
    """gcm.conf is a text file people edit and merge; a repeat would alias two entries."""
    path = write_minimal_hosts_config(tmp_path, [{"id": "aaaa1111"}, {"id": "aaaa1111"}])

    loaded = load_hosts(app_module, monkeypatch, path)

    assert len({host.id for host in loaded}) == 2
    assert "aaaa1111" in {host.id for host in loaded}


def test_write_config_persists_the_host_id(tmp_path, app_module, monkeypatch):
    config_file = tmp_path / "gcm.conf"
    monkeypatch.setattr(app_module, "CONFIG_FILE", str(config_file))
    monkeypatch.setattr(app_module.crypto, "encrypt", lambda _pwd, value: value)
    host = make_host(app_module)
    monkeypatch.setattr(app_module, "groups", {"ops/prod": [host]})
    monkeypatch.setattr(app_module, "shortcuts", {})

    wmain = object.__new__(app_module.Wmain)
    wmain.hpMain = types.SimpleNamespace(get_position=lambda: 200)
    wmain.wMain = types.SimpleNamespace(is_maximized=lambda: False)
    wmain.get_collapsed_nodes = lambda: []
    wmain.get_collapsed_folder_ids = lambda: []
    wmain.writeConfig()

    written = configparser.RawConfigParser()
    written.read(config_file)
    assert written.get("host 1", "id") == host.id


def test_load_config_files_a_pre_adr_0002_config_under_folder_records(
    tmp_path, app_module, monkeypatch
):
    """The migration: no folder sections in, every host bound and no path changed."""
    path = write_minimal_hosts_config(
        tmp_path, [{"group": "Home/PVE"}, {"group": "Home/PVE/Nodes"}, {"group": "Work"}]
    )

    loaded = load_hosts(app_module, monkeypatch, path)

    tree = app_module.folders
    assert sorted(app_module.groups) == ["Home/PVE", "Home/PVE/Nodes", "Work"]
    assert all(host.folder in tree.folders for host in loaded)
    assert all(tree.path_for(host.folder) == host.group for host in loaded)
    assert len(tree.folders) == 4


def test_write_config_persists_the_folder_tree_and_reloads_it_unchanged(
    tmp_path, app_module, monkeypatch
):
    path = write_minimal_hosts_config(tmp_path, [{"group": "ops/prod"}, {"group": "ops"}])
    first = load_hosts(app_module, monkeypatch, path)
    bound = {host.name: host.folder for host in first}

    wmain = object.__new__(app_module.Wmain)
    wmain.hpMain = types.SimpleNamespace(get_position=lambda: 200)
    wmain.wMain = types.SimpleNamespace(is_maximized=lambda: False)
    wmain.get_collapsed_nodes = lambda: []
    wmain.get_collapsed_folder_ids = lambda: []
    wmain.writeConfig()

    written = configparser.RawConfigParser()
    written.read(path)
    assert sorted(s for s in written.sections() if s.startswith("folder ")) == sorted(
        f"folder {folder_id}" for folder_id in app_module.folders.folders
    )
    second = load_hosts(app_module, monkeypatch, path)
    assert {host.name: host.folder for host in second} == bound
    assert sorted(app_module.groups) == ["ops", "ops/prod"]


def save_config(app_module):
    wmain = object.__new__(app_module.Wmain)
    wmain.hpMain = types.SimpleNamespace(get_position=lambda: 200)
    wmain.wMain = types.SimpleNamespace(is_maximized=lambda: False)
    wmain.get_collapsed_nodes = lambda: []
    wmain.get_collapsed_folder_ids = lambda: []
    wmain.writeConfig()


def test_an_arranged_folder_keeps_its_order_through_a_save_and_reload(
    tmp_path, app_module, monkeypatch
):
    path = write_minimal_hosts_config(tmp_path, [{}, {}, {}])
    first = {host.name: host for host in load_hosts(app_module, monkeypatch, path)}
    for position, name in enumerate(["router3", "router1", "router2"]):
        first[name].position = position

    save_config(app_module)
    reloaded = load_hosts(app_module, monkeypatch, path)

    contents = app_module.folder_contents()[reloaded[0].folder]
    assert [host.name for host in contents] == ["router3", "router1", "router2"]


def test_an_empty_folder_survives_a_save_and_reload(tmp_path, app_module, monkeypatch):
    path = write_minimal_hosts_config(tmp_path, [{}])
    load_hosts(app_module, monkeypatch, path)
    app_module.folders.add(app_module.ROOT_FOLDER, "archive")

    save_config(app_module)
    load_hosts(app_module, monkeypatch, path)

    tree = app_module.folders
    assert sorted(tree.path_for(folder_id) for folder_id in tree.folders) == ["archive", "ops"]


def test_a_config_nobody_arranged_is_saved_without_positions(tmp_path, app_module, monkeypatch):
    """Ordering changes nothing in the file until someone uses it."""
    path = write_minimal_hosts_config(tmp_path, [{"group": "ops/prod"}, {}, {}])
    load_hosts(app_module, monkeypatch, path)

    save_config(app_module)

    written = configparser.RawConfigParser()
    written.read(path)
    assert not [s for s in written.sections() if written.has_option(s, "position")]


def test_load_config_lets_the_folder_record_win_over_a_stale_group(
    tmp_path, app_module, monkeypatch
):
    """ADR-0002: the group string is derived. Editing it by hand no longer moves a host."""
    path = write_minimal_hosts_config(tmp_path, [{"group": "elsewhere", "folder": "f1"}])
    with path.open("a") as handle:
        handle.write("\n[folder f1]\nname = ops\nparent = \n")

    loaded = load_hosts(app_module, monkeypatch, path)

    assert loaded[0].group == "ops"
    assert loaded[0].folder == "f1"
    assert list(app_module.groups) == ["ops"]


def test_renaming_a_folder_record_moves_every_host_below_it(tmp_path, app_module, monkeypatch):
    path = write_minimal_hosts_config(
        tmp_path, [{"group": "old", "folder": "f1"}, {"group": "old/sub", "folder": "f2"}]
    )
    with path.open("a") as handle:
        handle.write("\n[folder f1]\nname = new\n\n[folder f2]\nname = sub\nparent = f1\n")

    load_hosts(app_module, monkeypatch, path)

    assert sorted(app_module.groups) == ["new", "new/sub"]


def test_collapsed_folders_are_saved_by_id_beside_the_old_row_positions(
    tmp_path, app_module, monkeypatch
):
    """Ids for this build; positions stay for an older one, which raises on an id."""
    path = write_minimal_hosts_config(tmp_path, [{"group": "ops"}])
    load_hosts(app_module, monkeypatch, path)
    assert app_module.conf.COLLAPSED_FOLDER_IDS is None

    wmain = object.__new__(app_module.Wmain)
    wmain.hpMain = types.SimpleNamespace(get_position=lambda: 200)
    wmain.wMain = types.SimpleNamespace(is_maximized=lambda: False)
    wmain.get_collapsed_nodes = lambda: ["0"]
    wmain.get_collapsed_folder_ids = lambda: ["ab12cd34", "ef56ab78"]
    wmain.writeConfig()

    written = configparser.RawConfigParser()
    written.read(path)
    assert written.get("window", "collapsed-folders") == "0"
    assert written.get("window", "collapsed-folder-ids") == "ab12cd34,ef56ab78"
    load_hosts(app_module, monkeypatch, path)
    assert app_module.conf.COLLAPSED_FOLDER_IDS == "ab12cd34,ef56ab78"
