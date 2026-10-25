"""Tests for utils/placeholders.py: a host's values filled into its local commands (#238)."""

from __future__ import annotations

import shlex
import subprocess
import types
from pathlib import Path

import pytest

from gnome_connection_manager.utils import placeholders


def a_host(**fields):
    values = {
        "name": "web-01",
        "host": "10.0.0.5",
        "port": "2222",
        "user": "ops",
        "group": "prod/web",
        "type": "ssh",
    }
    values.update(fields)
    return types.SimpleNamespace(**values)


@pytest.mark.parametrize(
    ("placeholder", "expected"),
    [
        ("{name}", "web-01"),
        ("{address}", "10.0.0.5"),
        ("{port}", "2222"),
        ("{user}", "ops"),
        ("{group}", "prod/web"),
        ("{folder}", "web"),
        ("{type}", "ssh"),
    ],
)
def test_each_placeholder_is_the_hosts_value(placeholder, expected):
    values = placeholders.host_values(a_host())

    assert placeholders.fill(f"x {placeholder} y", values) == f"x {expected} y"


def test_every_placeholder_is_tested():
    """The table above names each one, so a placeholder added without a test fails."""
    assert placeholders.PLACEHOLDERS == (
        "name",
        "address",
        "port",
        "user",
        "group",
        "folder",
        "type",
    )


@pytest.mark.parametrize(
    ("group", "folder"),
    [
        ("prod/web", "web"),
        ("web", "web"),
        ("1. Projects/infra foundry", "infra foundry"),
        ("/lab//x/", "x"),
        ("", ""),
        (None, ""),
    ],
)
def test_the_folder_is_the_one_the_host_is_in_alone(group, folder):
    """`{group}` is the whole path, and `{folder}` its last folder, none at the top level
    (#348). A path is read as the folder tree reads it, empty parts and all."""
    assert placeholders.host_values(a_host(group=group))["folder"] == folder


def test_every_list_of_the_placeholders_names_them_all():
    """Each hint that lists the placeholders, in the host dialog, Preferences and a command
    host's settings, lists them all: one added to PLACEHOLDERS, as {folder} was (#348),
    is not left out of what tells people of them."""
    root = Path(__file__).resolve().parents[1]
    sources = [
        *(root / "src").rglob("*.py"),
        root / "data" / "ui" / "gnome-connection-manager.glade",
    ]
    lists = [
        line
        for source in sources
        for line in source.read_text(encoding="utf-8").splitlines()
        if "{name}, {address}" in line
    ]

    assert len(lists) >= 4, lists
    for line in lists:
        assert all(f"{{{name}}}" in line for name in placeholders.PLACEHOLDERS), line


@pytest.mark.parametrize(
    "template",
    [
        "awk '{print $1}'",
        "echo ${HOME}",
        "{names} {Name} {address",
        "{}",
    ],
)
def test_anything_else_in_braces_is_left_as_written(template):
    assert placeholders.fill(template, placeholders.host_values(a_host())) == template


def test_a_value_the_host_lacks_is_empty():
    """The Local button's host is built with no user, and a port may be a number."""
    values = placeholders.host_values(a_host(user=None, port=22))

    assert values["user"] == ""
    assert values["port"] == "22"


def test_quote_is_applied_to_each_value_and_nothing_else():
    filled = placeholders.fill(
        "ping {address} -c {port}", placeholders.host_values(a_host()), quote=lambda v: f"<{v}>"
    )

    assert filled == "ping <10.0.0.5> -c <2222>"


@pytest.mark.parametrize(
    "name",
    ["plain", "two words", "semi; touch pwned", "it's", "$(touch pwned)", "`touch pwned`", ""],
)
def test_a_shell_quoted_value_stays_one_argument(tmp_path, name):
    """Run through a real `sh -c`, as GCM runs the command: the name arrives whole."""
    command = placeholders.fill(
        "printf '%s|' {name}", placeholders.host_values(a_host(name=name)), quote=shlex.quote
    )

    result = subprocess.run(
        ["sh", "-c", command], cwd=tmp_path, capture_output=True, text=True, check=True
    )

    assert result.stdout == f"{name}|"
    assert not (tmp_path / "pwned").exists()


def test_a_shell_quoted_folder_stays_one_argument(tmp_path):
    """The folder is free text too, and reaches a command on this computer whole."""
    host = a_host(group="prod/semi; touch pwned")
    command = placeholders.fill(
        "printf '%s|' {folder}", placeholders.host_values(host), quote=shlex.quote
    )

    result = subprocess.run(
        ["sh", "-c", command], cwd=tmp_path, capture_output=True, text=True, check=True
    )

    assert result.stdout == "semi; touch pwned|"
    assert not (tmp_path / "pwned").exists()


# Snippets (#240): the same names, unquoted, and a value asked for with {?Label}.


def test_a_snippet_takes_the_hosts_values_as_they_are():
    """Typed into whatever runs in the tab, which need not be a shell: no quoting."""
    values = placeholders.host_values(a_host(name="two words; more"))

    assert placeholders.fill_snippet("ssh {user}@{address} # {name}", values, {}) == (
        "ssh ops@10.0.0.5 # two words; more"
    )


def test_a_snippet_takes_the_folder_too():
    values = placeholders.host_values(a_host(group="prod/two words"))

    assert placeholders.fill_snippet("cd /srv/{folder} # {group}", values, {}) == (
        "cd /srv/two words # prod/two words"
    )


def test_each_label_is_asked_once_in_the_order_it_first_appears():
    template = "scp {?File} {?Where}:{?File} {?Where}"

    assert placeholders.asked(template) == ["File", "Where"]


@pytest.mark.parametrize("template", ["{?}", "{ ?File}", "{?{File}}", "?File"])
def test_what_is_not_a_label_is_not_asked(template):
    assert placeholders.asked(template) == []


def test_a_label_is_taken_as_written():
    assert placeholders.asked("ping {? Host name }") == [" Host name "]


def test_answers_fill_every_place_their_label_appears():
    filled = placeholders.fill_snippet(
        "cp {?File} /tmp/{?File}.{name}", placeholders.host_values(a_host()), {"File": "a.log"}
    )

    assert filled == "cp a.log /tmp/a.log.web-01"


def test_nothing_is_filled_in_twice():
    """One pass: an answer naming a placeholder, and a value that looks like a label,
    are typed as they are."""
    values = placeholders.host_values(a_host(name="{?Password}"))

    filled = placeholders.fill_snippet("{name} {?Say}", values, {"Say": "{address}"})

    assert filled == "{?Password} {address}"


def test_without_a_host_its_placeholders_are_left_as_written():
    filled = placeholders.fill_snippet("echo {name} {?Say} {other}", None, {"Say": "hi"})

    assert filled == "echo {name} hi {other}"


def test_a_label_with_no_answer_is_left_as_written():
    assert placeholders.fill_snippet("echo {?Say}", None, {}) == "echo {?Say}"


# A command host's command line (#248): the same names, quoted, and {password}.


def test_a_command_line_takes_the_hosts_values_quoted():
    filled, named = placeholders.fill_command(
        "ping {address} -c {port}", placeholders.host_values(a_host()), quote=lambda v: f"<{v}>"
    )

    assert (filled, named) == ("ping <10.0.0.5> -c <2222>", False)


def test_a_command_line_takes_the_folder_quoted():
    filled, named = placeholders.fill_command(
        "kubectl -n {folder} exec -it {name} -- sh",
        placeholders.host_values(a_host(group="clusters/two words")),
        quote=shlex.quote,
    )

    assert (filled, named) == ("kubectl -n 'two words' exec -it web-01 -- sh", False)


def test_its_password_is_a_reference_to_the_variable_and_never_the_value():
    """The value is not among the host's values at all: nothing here can write it."""
    filled, named = placeholders.fill_command(
        "IPMI_PASSWORD={password} ipmitool -U {user} -E; echo {password}",
        placeholders.host_values(a_host()),
        quote=shlex.quote,
    )

    assert filled == 'IPMI_PASSWORD="$GCM_PASSWORD" ipmitool -U ops -E; echo "$GCM_PASSWORD"'
    assert named and placeholders.PASSWORD_VARIABLE == "GCM_PASSWORD"


def test_a_value_holding_the_password_placeholder_is_not_filled_in_again():
    """One pass: a user named {password} is quoted as written, and asks for nothing."""
    filled, named = placeholders.fill_command(
        "ssh {user}@{address}",
        placeholders.host_values(a_host(user="{password}")),
        quote=shlex.quote,
    )

    assert (filled, named) == ("ssh '{password}'@10.0.0.5", False)


def test_the_password_placeholder_is_a_command_lines_alone():
    """#238's commands and snippets leave it as written, as they did before."""
    values = placeholders.host_values(a_host())

    assert placeholders.fill("echo {password}", values, quote=shlex.quote) == "echo {password}"
    assert placeholders.fill_snippet("echo {password}", values, {}) == "echo {password}"
