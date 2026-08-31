"""Tests for utils/shortcuts.py, exercised directly rather than through app.py.

Moved out of tests/test_application.py and tests/test_wmain.py with the code (#140).
Nothing here imports `app`, so nothing here needs the `gi` stub in tests/conftest.py --
which is the point of the extraction: a stub that can define methods the real class
lacks has hidden real faults before (#30, #41, #141).

The one custom-key test left behind is the one that reads `RESERVED_ACCELERATORS`. That
constant stays in app.py beside the `do_startup` registrations a test checks it against,
so the test asserting a reserved accelerator is refused stays with it.
"""

from __future__ import annotations

import logging

import pytest

from gnome_connection_manager.utils import shortcuts


def test_a_custom_key_on_a_terminal_shortcut_is_refused():
    """Accepting it would shadow copy, paste or find depending on the user's config."""
    accepted = shortcuts.parse_custom_keys(
        {"CTRL+SHIFT+C": "\\n", "SHIFT+RETURN": "\\n"},
        reserved={"CTRL+SHIFT+C"},
    )

    assert "CTRL+SHIFT+C" not in accepted
    assert accepted["SHIFT+RETURN"] == b"\n"


def test_custom_keys_decode_escape_sequences():
    accepted = shortcuts.parse_custom_keys(
        {
            "SHIFT+RETURN": "\\n",
            "ALT+RETURN": "\\x1b\\r",
            "CTRL+SHIFT+RETURN": "\\r\\n",
            "SHIFT+TAB": "literal",
        },
        reserved=set(),
    )

    assert accepted["SHIFT+RETURN"] == b"\n"
    assert accepted["ALT+RETURN"] == b"\x1b\r"
    assert accepted["CTRL+SHIFT+RETURN"] == b"\r\n"
    assert accepted["SHIFT+TAB"] == b"literal"


def test_an_undecodable_custom_key_is_dropped_not_fatal():
    accepted = shortcuts.parse_custom_keys(
        {"SHIFT+RETURN": "\\xZZ", "SHIFT+TAB": "\\n"}, reserved=set()
    )

    assert "SHIFT+RETURN" not in accepted
    assert accepted["SHIFT+TAB"] == b"\n"


def test_an_empty_custom_sequence_is_dropped():
    assert shortcuts.parse_custom_keys({"SHIFT+RETURN": ""}, reserved=set()) == {}


def test_key_names_are_matched_case_insensitively_after_stripping():
    """gcm.conf is hand-editable, and configparser preserves whatever case was typed."""
    accepted = shortcuts.parse_custom_keys({"  shift+return  ": "\\n"}, reserved=set())

    assert accepted == {"SHIFT+RETURN": b"\n"}


def test_a_reserved_key_is_matched_after_the_same_normalisation():
    """A lowercase entry must not slip past the reserved check the uppercase one hits."""
    assert shortcuts.parse_custom_keys({"ctrl+q": "\\n"}, reserved={"CTRL+Q"}) == {}


def test_a_blank_key_name_is_dropped():
    assert shortcuts.parse_custom_keys({"   ": "\\n"}, reserved=set()) == {}


def test_no_entries_is_not_an_error():
    """`config.items()` on a missing section hands back nothing at all."""
    assert shortcuts.parse_custom_keys(None, reserved=set()) == {}
    assert shortcuts.parse_custom_keys({}, reserved=set()) == {}


def test_a_refused_key_says_why_in_the_log(caplog):
    """The binding is dropped silently from the user's point of view otherwise."""
    with caplog.at_level(logging.WARNING, logger="gnome_connection_manager"):
        shortcuts.parse_custom_keys({"CTRL+Q": "\\n"}, reserved={"CTRL+Q"})

    assert "CTRL+Q" in caplog.text
    assert "never reach the terminal" in caplog.text


def test_clamp_font_scale_holds_vte_limits():
    """VTE itself lands 0.1 on 0.25 and 99.0 on 4.0; the clamp mirrors that."""
    assert shortcuts.clamp_font_scale(0.01) == shortcuts.FONT_SCALE_MIN
    assert shortcuts.clamp_font_scale(99.0) == shortcuts.FONT_SCALE_MAX
    assert shortcuts.clamp_font_scale(1.0) == 1.0


@pytest.mark.parametrize("scale", [shortcuts.FONT_SCALE_MIN, shortcuts.FONT_SCALE_MAX])
def test_clamp_font_scale_is_inclusive_at_both_ends(scale):
    """The bounds are values VTE applies, not values it rejects."""
    assert shortcuts.clamp_font_scale(scale) == scale
