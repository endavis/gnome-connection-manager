"""Tests for Host and HostUtils, exercised directly rather than through app.py.

No `app_module` fixture and no import of `app`, so nothing here runs against the `gi`
stub in conftest.py. That is what the extraction bought (#138).
"""

from __future__ import annotations

import configparser
import io

from gnome_connection_manager.utils import crypto, hosts


def reread(cp):
    """Serialize and parse back, the way writeConfig and loadConfig actually do it.

    Not a detour: `save_host_to_ini` hands `cp.set` real bools, and `RawConfigParser`
    stores them as-is, so `getboolean` chokes on them in memory. Writing to a file
    stringifies them first, which is why production never hits that. Round-tripping
    through text here tests the path the application takes instead of patching
    `RawConfigParser.set` to paper over the difference.
    """
    buf = io.StringIO()
    cp.write(buf)
    out = configparser.RawConfigParser()
    out.read_string(buf.getvalue())
    return out


def make_sample_host():
    return hosts.Host(
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


def test_module_imports_without_gtk():
    """The property the extraction exists to buy."""
    assert not hasattr(hosts, "Vte")
    assert not hasattr(hosts, "Gtk")
    assert not hasattr(hosts, "conf")


def test_erase_binding_auto_matches_the_real_enum():
    """`hosts` holds the value as a plain int so it needs no gi import.

    Nothing would notice if VTE renumbered the enum, so assert it against the real one
    here -- the same discipline that catches a fake offering what the real class does
    not (#30, #41). This test uses real gi, not the conftest stub.
    """
    import gi

    gi.require_version("Vte", "2.91")
    from gi.repository import Vte

    assert int(Vte.EraseBinding.AUTO) == hosts.ERASE_BINDING_AUTO


def test_host_clone_returns_independent_copy():
    host = make_sample_host()
    cloned = host.clone()

    assert cloned is not host
    assert cloned.group == host.group
    assert cloned.tunnel == host.tunnel
    cloned.tunnel.append("extra")
    assert host.tunnel != cloned.tunnel
    assert cloned.commands == "echo start\nrun-checks"
    assert host.tunnel_as_string() == "L8080:localhost:80,L8443:localhost:443"
    assert cloned.tunnel_as_string() == "L8080:localhost:80,L8443:localhost:443,extra"


def test_host_defaults_use_the_erase_binding_constant():
    host = hosts.Host()
    assert host.backspace_key == hosts.ERASE_BINDING_AUTO
    assert host.delete_key == hosts.ERASE_BINDING_AUTO


def test_hostutils_save_and_load_round_trip(monkeypatch):
    host = make_sample_host()
    config = configparser.RawConfigParser()
    section = "host:primary"
    config.add_section(section)

    monkeypatch.setattr(crypto, "encrypt", lambda pwd, text: f"{pwd}:{text}" if text else "")
    monkeypatch.setattr(
        crypto,
        "decrypt",
        lambda pwd, value, **_kw: value.split(":", 1)[1] if ":" in value else value,
    )

    hosts.HostUtils.save_host_to_ini(config, section, host, pwd="secret")

    assert config.get(section, "commands") == "echo start\\nrun-checks"
    assert config.get(section, "tunnel") == "L8080:localhost:80,L8443:localhost:443"

    loaded = hosts.HostUtils.load_host_from_ini(reread(config), section, pwd="secret")

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


def test_round_trip_through_real_crypto():
    """The shim-free path: no patched encrypt, so the stored value is real ciphertext.

    tests/conftest.py once faked base64 and xor for the whole session and hid the legacy
    path failing outright (#141). Nothing is patched here.
    """
    host = make_sample_host()
    config = configparser.RawConfigParser()
    config.add_section("h")

    hosts.HostUtils.save_host_to_ini(config, "h", host, pwd="secret")
    stored = config.get("h", "pass")

    assert stored != host.password
    assert stored.startswith(crypto._KDF_PREFIX)
    loaded = hosts.HostUtils.load_host_from_ini(reread(config), "h", pwd="secret")
    assert loaded.password == "topsecret"
    assert loaded.x11 is True and loaded.compression is False


def test_load_honours_the_legacy_flag():
    """`legacy` replaces the `conf.VERSION` read that stayed in app.py."""
    config = configparser.RawConfigParser()
    config.add_section("h")
    for key in ("group", "name", "host", "user"):
        config.set(config.sections()[0], key, "x")
    config.set("h", "pass", "BhYcAhU=")  # XOR ciphertext for "value" under key "pw"

    assert hosts.HostUtils.load_host_from_ini(config, "h", "pw", legacy=True).password == "value"
    assert hosts.HostUtils.load_host_from_ini(config, "h", "pw").password != "value"
