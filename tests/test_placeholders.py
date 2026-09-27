"""Tests for utils/placeholders.py: a host's values filled into its local commands (#238)."""

from __future__ import annotations

import shlex
import subprocess
import types

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
        ("{type}", "ssh"),
    ],
)
def test_each_placeholder_is_the_hosts_value(placeholder, expected):
    values = placeholders.host_values(a_host())

    assert placeholders.fill(f"x {placeholder} y", values) == f"x {expected} y"


def test_every_placeholder_is_tested():
    """The table above names each one, so a placeholder added without a test fails."""
    assert placeholders.PLACEHOLDERS == ("name", "address", "port", "user", "group", "type")


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
