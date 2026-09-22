"""Tests for utils/configfile.py: reading gcm.conf leniently where that loses nothing (#161).

Measured before the module existed: a hand merge of two copies of gcm.conf repeats
sections, strict configparser refused it, and GCM came up with no window and the reason
only on stderr. A file it could not open was worse -- configparser skipped it, GCM
started empty, and closing the window wrote that empty list over the file.
"""

from __future__ import annotations

import configparser
import os
from textwrap import dedent

import pytest

from gnome_connection_manager.utils import configfile
from gnome_connection_manager.utils.folders import SECTION_PREFIX as FOLDER_PREFIX


def sections(reading):
    config = reading.config
    return {name: dict(config.items(name)) for name in config.sections()}


def test_a_file_without_repeats_reads_as_configparser_reads_it():
    text = dedent("""\
        [options]
        font = Monospace 11

        [host 1]
        name = web
        description = first line
          second line

        [folder a1]
        name = ops
        parent =
        """)
    strict = configparser.RawConfigParser()
    strict.read_string(text)

    reading = configfile.read_config(text)

    assert sections(reading) == {name: dict(strict.items(name)) for name in strict.sections()}
    assert (reading.kept_apart, reading.dropped, reading.ambiguous_folders) == (0, 0, frozenset())


def test_a_repeated_host_section_is_kept_as_another_host():
    """Both copies number their hosts from [host 1], so a merge repeats the header."""
    text = "[host 1]\nname = web\n\n[host 1]\nname = db\n"

    reading = configfile.read_config(text)

    hosts = sections(reading)
    assert hosts["host 1"] == {"name": "web"}
    assert sorted(host["name"] for host in hosts.values()) == ["db", "web"]
    # loadConfig reads a section as a host by this prefix alone
    assert all(name.startswith(configfile.HOST_PREFIX) for name in hosts)
    assert (reading.kept_apart, reading.dropped) == (1, 0)


def test_a_verbatim_repeat_is_dropped():
    reading = configfile.read_config("[host 1]\nname = web\n\n[host 1]\nname = web\n")

    assert sections(reading) == {"host 1": {"name": "web"}}
    assert (reading.kept_apart, reading.dropped) == (0, 1)


def test_a_repeat_matching_any_earlier_copy_is_dropped():
    """Three copies merged: the third repeats the second, not the first."""
    text = "[host 1]\nname = web\n\n[host 1]\nname = db\n\n[host 1]\nname = db\n"

    reading = configfile.read_config(text)

    assert sorted(host["name"] for host in sections(reading).values()) == ["db", "web"]
    assert (reading.kept_apart, reading.dropped) == (1, 1)


def test_a_kept_repeat_takes_a_name_nothing_else_uses():
    text = "[host 1]\nname = web\n\n[host 1 (repeat)]\nname = mail\n\n[host 1]\nname = db\n"

    reading = configfile.read_config(text)

    assert sorted(host["name"] for host in sections(reading).values()) == ["db", "mail", "web"]


def test_a_repeated_folder_is_kept_under_a_fresh_id_and_the_id_reported():
    """A folder renamed in one copy and not the other: both names survive."""
    text = dedent("""\
        [folder a1]
        name = ops
        parent =

        [folder a1]
        name = operations
        parent =
        """)

    reading = configfile.read_config(text)

    folders = sections(reading)
    assert folders["folder a1"]["name"] == "ops"
    assert sorted(folder["name"] for folder in folders.values()) == ["operations", "ops"]
    assert all(name.startswith(FOLDER_PREFIX) for name in folders)
    # a host naming a1 cannot say which of the two it meant
    assert reading.ambiguous_folders == {"a1"}


def test_a_verbatim_repeated_folder_is_dropped_and_its_id_still_means_one_folder():
    text = "[folder a1]\nname = ops\nparent =\n\n[folder a1]\nname = ops\nparent =\n"

    reading = configfile.read_config(text)

    assert list(sections(reading)) == ["folder a1"]
    assert reading.ambiguous_folders == frozenset()


def test_a_repeated_singleton_section_merges_and_a_repeated_key_keeps_the_later_value():
    text = dedent("""\
        [options]
        font = Monospace 11
        buffer-lines = 2000

        [options]
        font = Monospace 13
        word-separators = -
        """)

    reading = configfile.read_config(text)

    assert sections(reading) == {
        "options": {"font": "Monospace 13", "buffer-lines": "2000", "word-separators": "-"}
    }
    assert (reading.kept_apart, reading.dropped) == (0, 0)


def test_a_repeated_key_within_a_host_keeps_the_later_value():
    reading = configfile.read_config("[host 1]\nname = web\nname = db\n")

    assert sections(reading) == {"host 1": {"name": "db"}}


def test_an_indented_header_inside_a_value_is_left_to_the_value():
    """configparser reads an indented line after a key as more of its value."""
    reading = configfile.read_config("[host 1]\nname = web\ndescription = see\n  [host 1]\n")

    assert sections(reading) == {"host 1": {"name": "web", "description": "see\n[host 1]"}}
    assert (reading.kept_apart, reading.dropped) == (0, 0)


@pytest.mark.parametrize("separator", ["\x0c", "\u2028"])
def test_only_a_newline_ends_a_line(separator):
    """str.splitlines also breaks at these, and configparser does not: a value holding one
    followed by a header-shaped fragment must reach configparser untouched."""
    reading = configfile.read_config(f"[host 1]\nname = web{separator}[host 1]\n")

    assert sections(reading) == {"host 1": {"name": f"web{separator}[host 1]"}}


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("[host 1]\nname = web\nthis line has no equals sign\n", configparser.ParsingError),
        ("name = web\n[host 1]\n", configparser.MissingSectionHeaderError),
    ],
    ids=["stray line", "text before the first section"],
)
def test_a_line_configparser_cannot_place_is_still_refused(text, error):
    """Dropping it would lose whatever it was meant to say."""
    with pytest.raises(error):
        configfile.read_config(text)


def test_load_reads_a_file_as_gcm_writes_it(tmp_path):
    path = tmp_path / "gcm.conf"
    path.write_text("[host 1]\nname = wéb\n")

    assert sections(configfile.load(path)) == {"host 1": {"name": "wéb"}}


def test_load_treats_a_missing_file_as_an_empty_configuration(tmp_path):
    """The first run has no gcm.conf, and that is not an error."""
    assert configfile.load(tmp_path / "gcm.conf").config.sections() == []


def test_load_names_the_file_and_line_configparser_refused(tmp_path):
    path = tmp_path / "gcm.conf"
    path.write_text("[host 1]\nname = web\nstray\n")

    with pytest.raises(configfile.UnreadableError) as refused:
        configfile.load(path)

    assert str(path) in str(refused.value)
    assert "[line  3]" in str(refused.value)


def test_load_names_the_line_it_cannot_decode(tmp_path):
    path = tmp_path / "gcm.conf"
    path.write_bytes(b"[host 1]\nname = web\n\n[host 2]\nname = M\xfcnchen\n")

    with pytest.raises(configfile.UnreadableError, match="line 5 is not valid") as refused:
        configfile.load(path)

    assert str(path) in str(refused.value)


def test_load_refuses_a_path_it_cannot_open(tmp_path):
    """configparser skipped such a file without a word (#161). A directory stands in for
    one, since it cannot be opened even by root."""
    path = tmp_path / "gcm.conf"
    path.mkdir()

    with pytest.raises(configfile.UnreadableError, match="Is a directory") as refused:
        configfile.load(path)

    assert str(path) in str(refused.value)


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a file whatever its mode")
def test_load_refuses_a_file_without_read_permission(tmp_path):
    """The case measured in #161: GCM started empty and wrote that over the file."""
    path = tmp_path / "gcm.conf"
    path.write_text("[host 1]\nname = web\n")
    path.chmod(0)
    try:
        with pytest.raises(configfile.UnreadableError, match="Permission denied"):
            configfile.load(path)
    finally:
        path.chmod(0o600)
