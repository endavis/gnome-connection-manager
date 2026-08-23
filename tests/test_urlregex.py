"""Tests for the static URL regex definitions."""

from __future__ import annotations

import pytest

from gnome_connection_manager.utils import urlregex


def test_pcre2_flags_constant_matches_expected_value() -> None:
    assert urlregex.PCRE2_FLAGS == 1074398208


def test_regex_patterns_are_non_empty_strings() -> None:
    assert isinstance(urlregex.DIRECT, str) and urlregex.DIRECT
    assert isinstance(urlregex.URL, str) and urlregex.URL
    assert isinstance(urlregex.EMAIL, str) and urlregex.EMAIL


def test_direct_pattern_includes_expected_protocols() -> None:
    assert "news | telnet | nntp | https?" in urlregex.DIRECT


def test_url_pattern_prefers_www_or_ftp_prefixes() -> None:
    assert "(?=(?i:www|ftp))" in urlregex.URL


def test_email_pattern_optionally_allows_mailto_prefix() -> None:
    assert "(?i:mailto:)" in urlregex.EMAIL


def test_every_pattern_compiles_under_vte():
    """DIRECT was truncated by an unescaped quote and never compiled (#55).

    registerUrlRegex swallows the failure, so nothing surfaced it: the links just
    stopped existing. This is the guard.
    """
    gi = pytest.importorskip("gi", reason="PyGObject not available")
    gi.require_version("Vte", "2.91")
    from gi.repository import Vte

    patterns = {
        name: value
        for name, value in vars(urlregex).items()
        if name.isupper() and isinstance(value, str) and name != "PCRE2_FLAGS"
    }
    assert patterns, "no patterns found to check"

    for name, pattern in patterns.items():
        try:
            Vte.Regex.new_for_match(pattern, len(pattern), urlregex.PCRE2_FLAGS)
        except Exception as exc:  # noqa: BLE001 - the name is the useful part of the failure
            pytest.fail(f"urlregex.{name} does not compile: {exc}")


def test_patterns_are_not_truncated_by_their_own_quoting():
    """The bug was invisible in the file: the tail became a Python comment."""
    for name in ("DIRECT", "URL", "EMAIL"):
        pattern = getattr(urlregex, name)
        assert pattern.count("[") == pattern.count("]") or "\\Q" in pattern
        assert not pattern.rstrip().endswith(("\\Q", "&~", "(?x:")), (
            f"{name} looks cut off: {pattern[-30:]!r}"
        )
