"""Tests for the static URL regex definitions."""

from __future__ import annotations

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
