"""Tests for utils/logpaths.py, exercised directly rather than through app.py.

Moved out of tests/test_wmain.py with the code (#139): these are pure path and string
decisions and had no business being reached through a 3,000-line widget test file that
stubs all of `gi`.
"""

from __future__ import annotations

import types
from pathlib import Path

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


# -- a session's files share one number (#200) --------------------------------


def test_next_session_stem_takes_the_first_number_no_session_file_uses(tmp_path):
    prefix = tmp_path / "web-01-20260823"
    for taken in ("001.log", "002.raw", "003.timing"):
        (tmp_path / f"web-01-20260823-{taken}").write_text("x")

    assert logpaths.next_session_stem(prefix, ".log") == f"{prefix}-004"


# Spelled out rather than read from SESSION_SUFFIXES: parametrized over the constant, a
# mutant that dropped ".raw" from it dropped the case that would have caught it.
@pytest.mark.parametrize("left_behind", [".log", ".raw", ".timing"])
def test_next_session_stem_skips_a_number_any_earlier_file_holds(tmp_path, left_behind):
    """Numbered per suffix, a day that began without recording gave the next session
    002.log beside 001.raw -- and a day that began with only a recording, the reverse."""
    prefix = tmp_path / "session-20260925"
    (tmp_path / f"session-20260925-001{left_behind}").write_text("x")

    assert logpaths.next_session_stem(prefix, ".raw") == f"{prefix}-002"


def test_next_session_stem_falls_back_to_the_last_when_exhausted(tmp_path, monkeypatch):
    """Refusing to log because 999 sessions happened today would be worse."""
    monkeypatch.setattr(logpaths.Path, "exists", lambda self: True)

    assert logpaths.next_session_stem(tmp_path / "busy-20260823", ".raw") == (
        f"{tmp_path / 'busy-20260823'}-999"
    )


# -- the number is reserved as it is chosen (#202) ------------------------------


def test_next_session_stem_reserves_the_number_it_chooses(tmp_path):
    """The relay creates a recording about 35 ms after the spawn. Until something is on
    disk, the next tab for the same host chooses the same number."""
    prefix = tmp_path / "session-20260925"

    first = logpaths.next_session_stem(prefix, ".raw")

    assert Path(first + ".raw").read_bytes() == b"", "the reservation is an empty file"
    assert logpaths.next_session_stem(prefix, ".raw") == f"{prefix}-002"


def test_next_session_stem_yields_a_number_taken_after_it_looked(tmp_path, monkeypatch):
    """GCM is not a unique application, so another instance can create the file between
    the check and the create. That instance keeps the number, and its file is left as it
    was -- not truncated, not appended to."""
    prefix = tmp_path / "session-20260925"
    theirs = tmp_path / "session-20260925-001.raw"
    theirs.write_bytes(b"another instance's session")
    # Every check finds nothing, as if each file appeared just after it was looked for.
    monkeypatch.setattr(logpaths.Path, "exists", lambda self: False)

    assert logpaths.next_session_stem(prefix, ".raw") == f"{prefix}-002"
    assert theirs.read_bytes() == b"another instance's session"


def test_next_session_stem_leaves_an_unwritable_directory_to_the_caller(tmp_path, monkeypatch):
    """The caller's own open fails the same way and reports it where it always has; the
    number is still returned, so that report names the file it could not write."""

    def refuse(self, *args, **kwargs):
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(logpaths.Path, "touch", refuse)

    assert logpaths.next_session_stem(tmp_path / "ro-20260925", ".log") == (
        f"{tmp_path / 'ro-20260925'}-001"
    )


def test_session_stem_for_lays_the_session_out_under_its_host(tmp_path, monkeypatch):
    monkeypatch.setattr(logpaths.time, "strftime", lambda fmt: "20260823")
    terminal = types.SimpleNamespace(host=LogHost(group="Work", name="web-01", user="root"))

    stem = logpaths.session_stem_for(terminal, tmp_path, ".log")

    assert stem == str(tmp_path / "Work" / "web-01" / "root-20260823-001")
    assert sorted(p.name for p in (tmp_path / "Work" / "web-01").iterdir()) == [
        "root-20260823-001.log"
    ]


def test_session_stem_for_refuses_a_path_that_escapes(tmp_path, monkeypatch):
    """None rather than a path, and nothing created on the way to refusing."""
    monkeypatch.setattr(logpaths, "sanitize_log_name", lambda title: title)
    terminal = types.SimpleNamespace(host=LogHost(name="../escaped"))

    assert logpaths.session_stem_for(terminal, tmp_path / "logs", ".raw") is None
    assert not (tmp_path / "escaped").exists()


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


# -- the whole label, cut to what a tab strip can show (#190) ---------------


@pytest.mark.parametrize(
    "raw",
    [
        "web-01",
        "web-01: npm run build",
        "z" * logpaths.TAB_LABEL_MAX,
        "",
        None,
    ],
)
def test_truncate_tab_label_leaves_what_already_fits(raw):
    """Including the label that is exactly the cap: a cut there would be gratuitous."""
    assert logpaths.truncate_tab_label(raw) == (raw or "")


def test_truncate_tab_label_cuts_what_does_not_fit():
    out = logpaths.truncate_tab_label("y" * 300)

    assert len(out) == logpaths.TAB_LABEL_MAX
    assert out.endswith("…")


def test_truncate_tab_label_does_not_leave_a_dangling_space():
    """A cut that lands mid-gap would render as "name …"."""
    out = logpaths.truncate_tab_label("a" * 28 + "  tail")

    assert out == "a" * 28 + "…"


def test_the_label_cap_is_tighter_than_the_title_cap():
    """sanitize_tab_title bounds one untrusted title; this bounds the whole label."""
    assert logpaths.TAB_LABEL_MAX < logpaths.TAB_TITLE_MAX
