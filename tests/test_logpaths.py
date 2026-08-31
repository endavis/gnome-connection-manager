"""Tests for utils/logpaths.py, exercised directly rather than through app.py.

Moved out of tests/test_wmain.py with the code (#139): these are pure path and string
decisions and had no business being reached through a 3,000-line widget test file that
stubs all of `gi`.
"""

from __future__ import annotations

import pytest

from gnome_connection_manager.utils import logpaths


class LogHost:
    def __init__(self, group="", name="web-01", user="", host="", port=""):
        self.group = group
        self.name = name
        self.user = user
        self.host = host
        self.port = port


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("router", "router"),
        ("  local  ", "local"),
        ("my   host", "my host"),
        # a title set by whatever runs in the terminal, via OSC 0
        ("../../../../tmp/pwned", "tmp_pwned"),
        ("claude - ~/src/app (3 tools)", "claude - ~_src_app (3 tools)"),
        ('a/b\\c:d*e?f"g<h>i|j', "a_b_c_d_e_f_g_h_i_j"),
        (".hidden", "hidden"),
        ("..", "session"),
        ("", "session"),
        ("   ", "session"),
        # BEL and ESC must not survive into a file someone will later cat
        ("tab\x07\x1b[31mred", "tab_[31mred"),
    ],
)
def test_sanitize_log_name(title, expected):
    assert logpaths.sanitize_log_name(title) == expected


def test_sanitize_log_name_caps_the_length():
    name = logpaths.sanitize_log_name("x" * 500)

    assert name == "x" * logpaths.LOG_NAME_MAX


def test_build_log_prefix_keeps_a_traversing_name_inside_the_log_directory(tmp_path):
    prefix = logpaths.build_log_prefix(tmp_path, "", "../../../../tmp/pwned", "", "20260823")

    assert prefix is not None
    assert prefix.parent.parent == tmp_path
    assert prefix.parent.name == "tmp_pwned"
    assert prefix.name == "session-20260823"


def test_build_log_prefix_refuses_a_path_that_escapes(tmp_path, monkeypatch):
    """The containment check must hold even if sanitising ever lets something through."""
    monkeypatch.setattr(logpaths, "sanitize_log_name", lambda title: title)

    assert logpaths.build_log_prefix(tmp_path, "", "../escaped", "", "20260823") is None


def test_build_log_prefix_expands_a_user_relative_log_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))

    prefix = logpaths.build_log_prefix("~/logs", "", "router", "", "20260823")

    assert prefix == tmp_path / "logs" / "router" / "session-20260823"


# -- log paths follow the host entry (#49) ----------------------------------


def test_build_log_prefix_mirrors_the_host_tree(tmp_path):
    """Nested groups become nested directories, since host.group is already a path."""
    prefix = logpaths.build_log_prefix(
        tmp_path, "Home Tech/OPNsense/OPNA/endavis", "OPNA-TS", "root", "20260823"
    )

    assert prefix == (
        tmp_path / "Home Tech" / "OPNsense" / "OPNA" / "endavis" / "OPNA-TS" / "root-20260823"
    )


def test_build_log_prefix_falls_back_when_no_user_is_set(tmp_path):
    """Deliberately the fallback name, not the host name again: the parent directory
    already carries the identity, so repeating it would give tmpl/tmpl-20260823."""
    prefix = logpaths.build_log_prefix(tmp_path, "1. Projects", "tmpl", "", "20260823")

    assert prefix == tmp_path / "1. Projects" / "tmpl" / "session-20260823"
    assert prefix.name != "tmpl-20260823"


def test_build_log_prefix_puts_an_ungrouped_host_at_the_top_level(tmp_path):
    """Local consoles arrive as Host("", "local"), so nothing above them moves."""
    prefix = logpaths.build_log_prefix(tmp_path, "", "local", "", "20260823")

    assert prefix == tmp_path / "local" / "session-20260823"


@pytest.mark.parametrize(
    ("group", "expected"),
    [
        ("prod/eu-west", ["prod", "eu-west"]),
        ("a//b/./c", ["a", "b", "c"]),
        ("../../etc", ["etc"]),
        ("", []),
        (None, []),
        ("...", []),
    ],
)
def test_sanitize_log_segments(group, expected):
    """Dots and blanks are dropped before sanitising -- sanitize_log_name would turn
    ".." into the fallback name and litter the tree with bogus directories."""
    assert logpaths.sanitize_log_segments(group) == expected


def test_sanitize_log_segments_does_not_flatten_the_separator():
    """Sanitising the whole path at once would collapse it: / is in the unsafe set."""
    assert logpaths.sanitize_log_name("prod/eu-west") == "prod_eu-west"
    assert logpaths.sanitize_log_segments("prod/eu-west") == ["prod", "eu-west"]


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        (
            LogHost(name="OPNA-TS", user="root", host="10.0.0.4", port=22),
            "OPNA-TS (root@10.0.0.4:22)",
        ),
        (LogHost(name="web-01", user="", host="10.0.0.5", port=22), "web-01 (10.0.0.5:22)"),
        (
            LogHost(name="web-01", user="deploy", host="10.0.0.5", port=""),
            "web-01 (deploy@10.0.0.5)",
        ),
        (LogHost(name="local", host=""), "local"),
    ],
)
def test_describe_log_session(host, expected):
    """Provenance lives inside the file so it survives the log being moved."""
    assert logpaths.describe_log_session(host) == expected


# -- tab titles from window-title-changed (#18) -----------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("npm run build", "npm run build"),
        ("  spaced   out  ", "spaced out"),
        ("bell\x07and\x1bescape", "bellandescape"),
        ("", ""),
        (None, ""),
    ],
)
def test_sanitize_tab_title(raw, expected):
    """Titles arrive over OSC from whatever runs in the terminal, including a remote host."""
    assert logpaths.sanitize_tab_title(raw) == expected


def test_sanitize_tab_title_truncates():
    out = logpaths.sanitize_tab_title("y" * 300)

    assert len(out) == logpaths.TAB_TITLE_MAX
    assert out.endswith("…")
