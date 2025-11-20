"""Tests covering configuration persistence helpers in app.py."""

from __future__ import annotations

import configparser
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
    monkeypatch.setattr(app_module, "decrypt", lambda _pwd, value: value)

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
    monkeypatch.setattr(app_module, "encrypt", lambda _pwd, value: value)

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
