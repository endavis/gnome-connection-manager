"""Tests for Host and HostUtils, exercised directly rather than through app.py.

No `app_module` fixture and no import of `app`, so nothing here runs against the `gi`
stub in conftest.py. That is what the extraction bought (#138).
"""

from __future__ import annotations

import configparser
import io

import pytest

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


# -- commands and their enable flag are stored separately (#151) --------------


def test_clone_carries_the_commands_enable_flag():
    host = make_sample_host()
    host.commands_enabled = True

    assert host.clone().commands_enabled is True


def test_disabled_commands_survive_a_round_trip():
    """The bug in #151: unticking the box used to write the commands away as "".

    Storing the flag separately is what lets the text stay put, so assert both halves
    come back rather than just the flag.
    """
    host = make_sample_host()
    host.commands_enabled = False
    config = configparser.RawConfigParser()
    config.add_section("h")

    hosts.HostUtils.save_host_to_ini(config, "h", host, pwd="secret")
    loaded = hosts.HostUtils.load_host_from_ini(reread(config), "h", pwd="secret")

    assert loaded.commands == "echo start\nrun-checks"
    assert loaded.commands_enabled is False


def test_enabled_commands_round_trip():
    host = make_sample_host()
    host.commands_enabled = True
    config = configparser.RawConfigParser()
    config.add_section("h")

    hosts.HostUtils.save_host_to_ini(config, "h", host, pwd="secret")
    loaded = hosts.HostUtils.load_host_from_ini(reread(config), "h", pwd="secret")

    assert loaded.commands == "echo start\nrun-checks"
    assert loaded.commands_enabled is True


def test_pre_151_entries_keep_running_their_commands():
    """A gcm.conf written before the split has no `commands-enabled` key.

    Back then the text *was* the flag, so stored commands were being sent. Defaulting
    the flag to "there is text" is what keeps that true across the upgrade.
    """
    config = configparser.RawConfigParser()
    config.add_section("h")
    for key in ("group", "name", "host", "user", "pass"):
        config.set("h", key, "")
    config.set("h", "commands", "echo start\\nrun-checks")

    loaded = hosts.HostUtils.load_host_from_ini(config, "h", pwd="secret")

    assert "commands-enabled" not in config["h"]
    assert loaded.commands_enabled is True


def test_pre_151_entries_without_commands_are_not_enabled():
    config = configparser.RawConfigParser()
    config.add_section("h")
    for key in ("group", "name", "host", "user", "pass"):
        config.set("h", key, "")

    loaded = hosts.HostUtils.load_host_from_ini(config, "h", pwd="secret")

    assert loaded.commands == ""
    assert loaded.commands_enabled is False


def test_every_host_is_born_with_an_id():
    """No caller passes one, so the record has to mint it (ADR-0001)."""
    host = make_sample_host()

    assert host.id
    assert len(host.id) == hosts.HOST_ID_BYTES * 2
    assert all(c in "0123456789abcdef" for c in host.id)


def test_ids_are_not_derived_from_the_record():
    """Two hosts with identical fields are still two hosts."""
    first = make_sample_host()
    second = make_sample_host()

    assert first.id != second.id


def test_an_id_survives_the_ini_round_trip():
    host = make_sample_host()
    config = configparser.RawConfigParser()
    config.add_section("host 1")

    hosts.HostUtils.save_host_to_ini(config, "host 1", host, pwd="secret")

    assert config.get("host 1", "id") == host.id
    loaded = hosts.HostUtils.load_host_from_ini(reread(config), "host 1", pwd="secret")
    assert loaded.id == host.id


def test_a_config_written_before_adr_0001_gets_ids_by_being_read():
    """The whole of the migration: no version bump, no separate pass."""
    host = make_sample_host()
    config = configparser.RawConfigParser()
    config.add_section("host 1")
    hosts.HostUtils.save_host_to_ini(config, "host 1", host, pwd="secret")
    stored = reread(config)
    stored.remove_option("host 1", "id")

    loaded = hosts.HostUtils.load_host_from_ini(stored, "host 1", pwd="secret")

    assert loaded.id
    assert loaded.id != host.id


def test_an_id_is_minted_even_when_parsing_fails_partway():
    """`Host.__init__` swallows parse errors, so later attributes never get assigned.

    `id` is set before that try for exactly this case -- nothing should have to test
    whether a record has one.
    """
    broken = hosts.Host("infra", "primary", "", "router.example.com", "netops", "", "", "22", None)

    assert broken.id
    assert not hasattr(broken, "type")


def test_clone_takes_a_fresh_id():
    """A clone is a second host, not the same host twice."""
    host = make_sample_host()

    cloned = host.clone()

    assert cloned.id
    assert cloned.id != host.id


def test_ensure_unique_ids_reassigns_the_later_duplicate():
    first, second = make_sample_host(), make_sample_host()
    second.id = first.id

    reassigned = hosts.HostUtils.ensure_unique_ids([first, second])

    assert reassigned == [second]
    assert second.id != first.id


def test_ensure_unique_ids_leaves_distinct_ids_alone():
    first, second = make_sample_host(), make_sample_host()
    before = (first.id, second.id)

    assert hosts.HostUtils.ensure_unique_ids([first, second]) == []
    assert (first.id, second.id) == before


def test_ensure_unique_ids_fills_in_a_cleared_id():
    host = make_sample_host()
    host.id = ""

    assert hosts.HostUtils.ensure_unique_ids([host]) == [host]
    assert host.id


def test_ensure_unique_ids_is_stable_when_run_again():
    """Running it twice must not keep churning ids, or nothing can rely on one."""
    first, second = make_sample_host(), make_sample_host()
    second.id = first.id
    hosts.HostUtils.ensure_unique_ids([first, second])
    settled = (first.id, second.id)

    assert hosts.HostUtils.ensure_unique_ids([first, second]) == []
    assert (first.id, second.id) == settled


def test_ensure_unique_ids_separates_a_three_way_collision():
    one, two, three = make_sample_host(), make_sample_host(), make_sample_host()
    two.id = three.id = one.id

    hosts.HostUtils.ensure_unique_ids([one, two, three])

    assert len({one.id, two.id, three.id}) == 3


def test_a_folder_survives_the_ini_round_trip():
    host = make_sample_host()
    host.folder = "ab12cd34"
    config = configparser.RawConfigParser()
    config.add_section("host 1")

    hosts.HostUtils.save_host_to_ini(config, "host 1", host, pwd="secret")

    assert config.get("host 1", "folder") == "ab12cd34"
    loaded = hosts.HostUtils.load_host_from_ini(reread(config), "host 1", pwd="secret")
    assert loaded.folder == "ab12cd34"


def test_a_record_written_before_adr_0002_has_no_folder_yet():
    """Empty, so FolderTree.bind resolves the group string instead."""
    config = configparser.RawConfigParser()
    config.add_section("host 1")
    hosts.HostUtils.save_host_to_ini(config, "host 1", make_sample_host(), pwd="secret")
    stored = reread(config)
    stored.remove_option("host 1", "folder")

    assert hosts.HostUtils.load_host_from_ini(stored, "host 1", pwd="secret").folder == ""


def test_clone_is_filed_beside_the_original():
    host = make_sample_host()
    host.folder = "ab12cd34"

    cloned = host.clone()

    assert cloned.folder == "ab12cd34"
    assert cloned.id != host.id


def test_a_folder_attribute_exists_even_when_parsing_fails_partway():
    broken = hosts.Host("infra", "primary", "", "router.example.com", "netops", "", "", "22", None)

    assert broken.folder == ""


@pytest.mark.parametrize(("position", "written"), [(2, "2"), (0, "0"), (None, None)])
def test_a_position_survives_the_ini_round_trip_and_is_written_only_when_set(position, written):
    """Only a host in a folder someone arranged has one; the rest sort by name."""
    host = make_sample_host()
    host.position = position
    config = configparser.RawConfigParser()
    config.add_section("host 1")

    hosts.HostUtils.save_host_to_ini(config, "host 1", host, pwd="secret")

    assert config.get("host 1", "position", fallback=None) == written
    loaded = hosts.HostUtils.load_host_from_ini(reread(config), "host 1", pwd="secret")
    assert loaded.position == position


def test_an_unreadable_position_loads_as_none():
    config = configparser.RawConfigParser()
    config.add_section("host 1")
    hosts.HostUtils.save_host_to_ini(config, "host 1", make_sample_host(), pwd="secret")
    stored = reread(config)
    stored.set("host 1", "position", "second")

    assert hosts.HostUtils.load_host_from_ini(stored, "host 1", pwd="secret").position is None


def test_clone_does_not_take_the_originals_place():
    host = make_sample_host()
    host.position = 4

    assert host.clone().position is None


def test_a_position_attribute_exists_even_when_parsing_fails_partway():
    broken = hosts.Host("infra", "primary", "", "router.example.com", "netops", "", "", "22", None)

    assert broken.position is None
