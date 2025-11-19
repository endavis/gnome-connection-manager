"""Tests for Host and HostUtils helpers that avoid GTK dependencies."""

from __future__ import annotations

import configparser


def make_sample_host(app_module):
    return app_module.Host(
        "infra",
        "primary",
        "core router",
        "router.example.com",
        "netops",
        "topsecret",
        "/home/netops/.ssh/id_rsa",
        "2200",
        "L8080:localhost:80,L8443:localhost:443",
        "ssh",
        "echo start\nrun-checks",
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


def test_host_clone_returns_independent_copy(app_module):
    host = make_sample_host(app_module)
    cloned = host.clone()

    assert cloned is not host
    assert cloned.group == host.group
    assert cloned.tunnel == host.tunnel
    cloned.tunnel.append("extra")
    assert host.tunnel != cloned.tunnel
    assert cloned.commands == "echo start\nrun-checks"
    assert host.tunnel_as_string() == "L8080:localhost:80,L8443:localhost:443"
    assert cloned.tunnel_as_string() == "L8080:localhost:80,L8443:localhost:443,extra"


def test_hostutils_save_and_load_round_trip(app_module, monkeypatch):
    host = make_sample_host(app_module)
    config = configparser.RawConfigParser()
    section = "host:primary"
    config.add_section(section)

    monkeypatch.setattr(
        app_module, "encrypt", lambda pwd, text: f"{pwd}:{text}" if text else ""
    )
    monkeypatch.setattr(
        app_module,
        "decrypt",
        lambda pwd, value: value.split(":", 1)[1] if ":" in value else value,
    )
    original_set = configparser.RawConfigParser.set

    def coerce_bool(self, section, option, value):
        if isinstance(value, bool):
            value = str(value)
        return original_set(self, section, option, value)

    monkeypatch.setattr(configparser.RawConfigParser, "set", coerce_bool)

    app_module.HostUtils.save_host_to_ini(config, section, host, pwd="secret")

    assert config.get(section, "commands") == "echo start\\nrun-checks"
    assert config.get(section, "tunnel") == "L8080:localhost:80,L8443:localhost:443"

    loaded = app_module.HostUtils.load_host_from_ini(config, section, pwd="secret")

    assert loaded.name == host.name
    assert loaded.description == host.description
    assert loaded.password == host.password
    assert loaded.private_key == host.private_key
    assert loaded.commands == host.commands
    assert loaded.tunnel == host.tunnel
    assert loaded.x11 is host.x11
    assert loaded.agent is host.agent
    assert loaded.compression is host.compression
    assert loaded.font_color == host.font_color
    assert loaded.back_color == host.back_color
    assert loaded.keep_alive == host.keep_alive
    assert loaded.backspace_key == host.backspace_key
    assert loaded.delete_key == host.delete_key
