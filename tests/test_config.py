"""Tests covering configuration persistence helpers in app.py."""

from __future__ import annotations

import configparser
import logging
import os
import re
import types
from pathlib import Path

import pytest


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


# -- a gcm.conf that strict configparser refused (#161) ------------------------


def hand_merged(tmp_path, *copies):
    """gcm.conf as a hand merge leaves it: each copy's text, one after another.

    Each copy is a list of host entries, as write_minimal_hosts_config takes them, so
    every copy numbers its hosts from [host 1] -- which is what made the merge unreadable.
    """
    texts = []
    for index, entries in enumerate(copies):
        folder = tmp_path / f"copy{index}"
        folder.mkdir()
        texts.append(write_minimal_hosts_config(folder, entries).read_text())
    path = tmp_path / "gcm.conf"
    path.write_text("".join(texts))
    return path


def test_load_config_reads_a_hand_merged_config(tmp_path, app_module, monkeypatch):
    """Measured before the fix: DuplicateSectionError, and no window at all."""
    path = hand_merged(
        tmp_path,
        [{"id": "aaaa1111"}, {"id": "bbbb2222"}],
        [{"id": "aaaa1111"}, {"id": "cccc3333", "name": "switch"}],
    )

    loaded = load_hosts(app_module, monkeypatch, path)

    # the first host is in both copies verbatim; the second differs, so both are kept
    assert sorted(host.name for host in loaded) == ["router1", "router2", "switch"]
    assert sorted(host.id for host in loaded) == ["aaaa1111", "bbbb2222", "cccc3333"]


def test_load_config_files_hosts_by_group_when_a_folder_id_repeats(
    tmp_path, app_module, monkeypatch
):
    """One copy renamed the folder. The id cannot say which name a host meant; the group
    path saved beside it can."""
    path = hand_merged(
        tmp_path,
        [{"group": "ops", "folder": "f1"}],
        [{"group": "operations", "folder": "f1", "name": "switch"}],
    )
    text = path.read_text()
    first, second = text.split("[host 1]", 2)[1:]
    path.write_text(
        "[host 1]" + first + "[folder f1]\nname = ops\nparent =\n\n"
        "[host 1]" + second + "[folder f1]\nname = operations\nparent =\n"
    )

    loaded = {host.name: host for host in load_hosts(app_module, monkeypatch, path)}

    assert loaded["router1"].group == "ops"
    assert loaded["switch"].group == "operations"
    assert sorted(app_module.groups) == ["operations", "ops"]


UNREADABLE = "[host 1]\nname = web\nthis line has no equals sign\n"


def test_require_readable_config_refuses_on_stderr_without_a_display(
    tmp_path, app_module, monkeypatch, capsys
):
    """With no display there is nobody to click OK, so a dialog would be a hang."""
    path = tmp_path / "gcm.conf"
    path.write_text(UNREADABLE)
    monkeypatch.setattr(app_module, "CONFIG_FILE", str(path))
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    with pytest.raises(SystemExit) as exit_info:
        app_module.require_readable_config()

    assert exit_info.value.code == 1
    said = capsys.readouterr().err
    assert "could not read its configuration file" in said
    assert str(path) in said
    assert "[line  3]" in said
    assert path.read_text() == UNREADABLE


class RefusalDialog:
    """Records a message dialog: require_readable_config's, and the notice of values that
    could not be read. Its methods are checked against the real Gtk.MessageDialog below."""

    shown: list = []

    def __init__(self, **kwargs):
        self.text = kwargs["text"]
        self.message_type = kwargs["message_type"]
        self.parent = kwargs.get("parent")
        self.detail = None

    def format_secondary_text(self, text):
        self.detail = text

    def run(self):
        RefusalDialog.shown.append(self)

    def destroy(self):
        pass


def test_require_readable_config_says_it_in_a_dialog_when_there_is_a_display(
    tmp_path, app_module, monkeypatch
):
    path = tmp_path / "gcm.conf"
    path.write_text(UNREADABLE)
    monkeypatch.setattr(app_module, "CONFIG_FILE", str(path))
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setattr(RefusalDialog, "shown", [])
    monkeypatch.setattr(app_module.Gtk, "MessageDialog", RefusalDialog)

    with pytest.raises(SystemExit) as exit_info:
        app_module.require_readable_config()

    assert exit_info.value.code == 1
    [dialog] = RefusalDialog.shown
    assert "could not read its configuration file" in dialog.text
    assert str(path) in dialog.detail
    assert "Nothing has been changed" in dialog.detail


def test_the_refusal_dialog_fake_matches_real_gtk():
    """conftest stubs all of gi, so the fake could offer methods GTK does not have."""
    gi = pytest.importorskip("gi", reason="PyGObject not available")
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    for name in ("format_secondary_text", "run", "destroy"):
        assert hasattr(Gtk.MessageDialog, name), f"Gtk.MessageDialog has no {name}"


@pytest.mark.parametrize(
    "text",
    [None, "[host 1]\nname = web\n\n[host 1]\nname = db\n"],
    ids=["first run, no file", "a hand merge"],
)
def test_require_readable_config_lets_a_readable_file_through(
    tmp_path, app_module, monkeypatch, capsys, text
):
    path = tmp_path / "gcm.conf"
    if text is not None:
        path.write_text(text)
    monkeypatch.setattr(app_module, "CONFIG_FILE", str(path))
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    app_module.require_readable_config()

    assert capsys.readouterr().err == ""


def test_main_checks_the_config_before_the_application_exists(app_module, monkeypatch):
    """The empty start that overwrote the file on close needs a window to exist."""
    calls = []

    def refuse():
        calls.append("config")
        raise SystemExit(1)

    monkeypatch.setattr(app_module, "require_expect", lambda: calls.append("expect"))
    monkeypatch.setattr(app_module, "require_readable_config", refuse)
    monkeypatch.setattr(app_module, "GcmApplication", lambda: calls.append("application"))

    with pytest.raises(SystemExit):
        app_module.main(["gcm"])

    assert calls == ["expect", "config"]


# -- what a save keeps of the file it replaces (#163) ----------------------------


def saved_sections(path):
    written = configparser.RawConfigParser()
    written.read(path)
    return written


def test_a_save_keeps_the_keys_section(tmp_path, app_module, monkeypatch):
    """[keys] is written by hand and never by GCM. Measured before the fix: the first save
    dropped it, so a binding lasted one session."""
    path = write_minimal_hosts_config(tmp_path, [{}])
    with path.open("a") as handle:
        handle.write("\n[keys]\nSHIFT+RETURN = \\n\n")
    load_hosts(app_module, monkeypatch, path)

    save_config(app_module)
    load_hosts(app_module, monkeypatch, path)

    assert app_module.custom_keys == {"SHIFT+RETURN": b"\n"}


def test_a_save_keeps_a_keys_line_added_while_gcm_runs(tmp_path, app_module, monkeypatch):
    """The documented way in is editing gcm.conf by hand, and GCM may well be running. So a
    save reads what it carries from the file as it is then, not as it was at startup."""
    path = write_minimal_hosts_config(tmp_path, [{}])
    load_hosts(app_module, monkeypatch, path)
    with path.open("a") as handle:
        handle.write("\n[keys]\nSHIFT+RETURN = \\n\n")

    save_config(app_module)

    assert dict(saved_sections(path).items("keys")) == {"shift+return": "\\n"}


def test_a_save_keeps_a_section_gcm_does_not_know(tmp_path, app_module, monkeypatch):
    path = write_minimal_hosts_config(tmp_path, [{}])
    with path.open("a") as handle:
        handle.write("\n[from-a-newer-gcm]\nsetting = on\n")
    load_hosts(app_module, monkeypatch, path)

    save_config(app_module)

    assert dict(saved_sections(path).items("from-a-newer-gcm")) == {"setting": "on"}


def test_a_save_does_not_bring_back_a_host_or_folder_deleted_since_the_load(
    tmp_path, app_module, monkeypatch
):
    """Host and folder sections are records: one missing from memory was deleted."""
    path = write_minimal_hosts_config(tmp_path, [{"group": "ops"}, {"group": "old"}])
    load_hosts(app_module, monkeypatch, path)
    del app_module.groups["old"]  # what deleting its one host does
    [old] = [f for f in app_module.folders.folders if app_module.folders.path_for(f) == "old"]
    app_module.folders.remove(old)

    save_config(app_module)

    written = saved_sections(path)
    hosts = [written.get(s, "name") for s in written.sections() if s.startswith("host ")]
    folders = [written.get(s, "name") for s in written.sections() if s.startswith("folder ")]
    assert hosts == ["router1"]
    assert folders == ["ops"]


def test_a_second_save_starts_from_the_first(tmp_path, app_module, monkeypatch):
    """Every section a save writes, it must strip from the file first, or the next save
    finds it there and add_section refuses: every save after the first would fail."""
    path = write_minimal_hosts_config(tmp_path, [{}])
    load_hosts(app_module, monkeypatch, path)
    save_config(app_module)
    first = saved_sections(path).sections()

    save_config(app_module)

    assert saved_sections(path).sections() == first


@pytest.mark.parametrize(
    "leftover",
    [lambda saved: saved, lambda saved: "[options]\nword-sep"],
    ids=["a complete copy", "cut off mid-line"],
)
def test_a_leftover_from_an_interrupted_save_does_not_stop_the_next(
    tmp_path, app_module, monkeypatch, leftover
):
    """Measured before the fix: writeConfig read gcm.conf.tmp first, so a leftover raised
    DuplicateSectionError or ParsingError on every save and nothing was saved again."""
    path = write_minimal_hosts_config(tmp_path, [{}])
    load_hosts(app_module, monkeypatch, path)
    save_config(app_module)
    tmp = Path(f"{path}.tmp")
    tmp.write_text(leftover(path.read_text()))
    monkeypatch.setattr(app_module.conf, "FONT", "Monospace 13")

    save_config(app_module)

    assert saved_sections(path).get("options", "font") == "Monospace 13"
    assert not tmp.exists()


def test_a_save_keeps_a_file_it_cannot_read_aside_rather_than_write_over_it(
    tmp_path, app_module, monkeypatch, caplog
):
    """Broken by hand while GCM runs, say. Writing over it would lose whatever the edit
    meant, and main() refuses to start on such a file for the same reason (#161)."""
    path = write_minimal_hosts_config(tmp_path, [{}])
    load_hosts(app_module, monkeypatch, path)
    broken = path.read_text() + "[keys]\nSHIFT+RETURN = \\n\na line with no equals sign\n"
    path.write_text(broken)

    with caplog.at_level(logging.WARNING, logger="gnome_connection_manager"):
        save_config(app_module)

    [aside] = tmp_path.glob("gcm.conf.unreadable-*")
    assert aside.read_text() == broken
    assert str(aside) in caplog.text
    assert saved_sections(path).get("host 1", "name") == "router1"


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a file whatever its mode")
def test_a_save_keeps_a_file_it_cannot_open_aside(tmp_path, app_module, monkeypatch):
    """Renaming needs the directory, not the file, so even this one can be kept."""
    path = write_minimal_hosts_config(tmp_path, [{}])
    load_hosts(app_module, monkeypatch, path)
    before = path.read_text()
    path.chmod(0)

    save_config(app_module)

    [aside] = tmp_path.glob("gcm.conf.unreadable-*")
    aside.chmod(0o600)
    assert aside.read_text() == before
    assert saved_sections(path).get("host 1", "name") == "router1"


# -- values that cannot be read (#173) --------------------------------------------


def with_options(tmp_path, *lines):
    """A minimal gcm.conf with these lines in [options]."""
    path = write_minimal_hosts_config(tmp_path, [{}])
    with path.open("a") as handle:
        handle.write("\n[options]\n" + "".join(f"{line}\n" for line in lines))
    return path


def test_a_value_gcm_cannot_read_survives_a_save(tmp_path, app_module, monkeypatch):
    """Measured before the fix: GCM used the default, said so only on stderr, and closing
    the window wrote the default over the line."""
    path = with_options(tmp_path, "paste-confirm-lines = 7 ; x", "bell-audible = maybe")
    load_hosts(app_module, monkeypatch, path)
    assert app_module.conf.PASTE_CONFIRM_LINES == 5

    save_config(app_module)
    save_config(app_module)

    saved = saved_sections(path)
    assert saved.get("options", "paste-confirm-lines") == "7 ; x"
    assert saved.get("options", "bell-audible") == "maybe"


def test_a_setting_changed_since_is_saved_as_changed(tmp_path, app_module, monkeypatch):
    """Preferences sets the value; that is the one to keep. And set back to the default
    afterwards, the default is saved rather than the old text coming back."""
    path = with_options(tmp_path, "paste-confirm-lines = 7 ; x")
    load_hosts(app_module, monkeypatch, path)

    app_module.conf.PASTE_CONFIRM_LINES = 9
    save_config(app_module)
    assert saved_sections(path).get("options", "paste-confirm-lines") == "9"

    app_module.conf.PASTE_CONFIRM_LINES = 5
    save_config(app_module)
    assert saved_sections(path).get("options", "paste-confirm-lines") == "5"


def test_an_unreadable_window_value_is_saved_as_the_window_is(tmp_path, app_module, monkeypatch):
    """[window] is GCM's record of its own window, not a setting anyone chose: a save
    writes what the window is now."""
    path = write_minimal_hosts_config(tmp_path, [{}])
    with path.open("a") as handle:
        handle.write("\n[window]\nshow-panel = maybe\n")
    load_hosts(app_module, monkeypatch, path)

    save_config(app_module)

    assert app_module.unread_options == []
    assert saved_sections(path).getboolean("window", "show-panel") is True


def test_the_window_reports_each_value_it_could_not_read(tmp_path, app_module, monkeypatch):
    path = with_options(tmp_path, "paste-confirm-lines = 7 ; x", "bell-audible = maybe")
    load_hosts(app_module, monkeypatch, path)
    monkeypatch.setattr(RefusalDialog, "shown", [])
    monkeypatch.setattr(app_module.Gtk, "MessageDialog", RefusalDialog)
    wmain = object.__new__(app_module.Wmain)
    wmain.wMain = object()

    assert wmain.report_unread_options() is False

    [dialog] = RefusalDialog.shown
    assert dialog.parent is wmain.wMain
    assert dialog.message_type == app_module.Gtk.MessageType.WARNING
    assert "could not be read" in dialog.text
    assert "paste-confirm-lines = 7 ; x  (expects a whole number)" in dialog.detail
    assert "bell-audible = maybe  (expects true or false)" in dialog.detail
    assert "Preferences" in dialog.detail


def test_the_window_says_nothing_when_every_value_reads(tmp_path, app_module, monkeypatch):
    load_hosts(app_module, monkeypatch, with_options(tmp_path, "paste-confirm-lines = 7"))
    monkeypatch.setattr(RefusalDialog, "shown", [])
    monkeypatch.setattr(app_module.Gtk, "MessageDialog", RefusalDialog)

    assert object.__new__(app_module.Wmain).report_unread_options() is False
    assert RefusalDialog.shown == []


def test_activation_reports_once(app_module, monkeypatch):
    """After the window and any tabs asked for are up; and only once, though activation
    can come again."""
    scheduled = []
    monkeypatch.setattr(app_module.GLib, "idle_add", lambda func, *args: scheduled.append(func))
    monkeypatch.setattr(app_module, "sync_shortcut_accels", lambda: None)
    application = app_module.GcmApplication()
    application._controller = types.SimpleNamespace(
        get_widget=lambda _name: None, report_unread_options=lambda: False
    )

    application.do_activate()
    application.do_activate()

    assert scheduled == [application._controller.report_unread_options]
