"""Documentation that states facts about the code has to be checked against the code.

docs/SPEC.md's shortcut table had already drifted -- it documented Ctrl+Shift+G for
find_back, which defaults to CTRL+H -- so the user-facing table gets a guard.
"""

from __future__ import annotations

import re
from pathlib import Path

DOC = Path(__file__).resolve().parents[1] / "docs" / "TERMINAL-USAGE.md"

# Symbols the doc spells the way a user reads them, mapped to GDK's key names.
_DISPLAY_TO_KEYNAME = {"=": "EQUAL", "-": "MINUS", ",": "COMMA"}


def _canonical(display_key: str) -> str:
    """Turn a table entry such as `Ctrl+=` into the CTRL+EQUAL form gcm.conf uses."""
    parts = display_key.strip().strip("`").split("+")
    tail = _DISPLAY_TO_KEYNAME.get(parts[-1], parts[-1])
    return "+".join([p.upper() for p in parts[:-1]] + [tail.upper()])


def _doc_shortcut_rows():
    rows = []
    for line in DOC.read_text().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 3 or cells[2] not in {"yes", "no"}:
            continue
        rows.append((cells[0], cells[1].strip("`"), cells[2] == "yes"))
    return rows


def test_documented_shortcut_table_matches_the_defaults(app_module):
    documented = {
        command: _canonical(key)
        for key, command, _in_menu in _doc_shortcut_rows()
        if not command.startswith("console_1")
    }
    actual = {command: key for command, _token, key in app_module.SHORTCUT_DEFAULTS}

    assert documented == actual


def test_documented_menu_column_matches_terminal_actions(app_module):
    for key, command, in_menu in _doc_shortcut_rows():
        if command.startswith("console_1"):
            continue
        expected = command in app_module.TERMINAL_ACTIONS
        assert in_menu is expected, (
            f"{key} ({command}) is documented as {'in' if in_menu else 'not in'} a menu, "
            f"but TERMINAL_ACTIONS says otherwise"
        )


def test_documented_application_accelerators_are_real(app_module):
    """The second table lists fixed accelerators; each must exist in do_startup."""
    source = Path(app_module.__file__).read_text()
    startup = source.split("def do_startup", 1)[1].split("def _create_action", 1)[0]
    registered = set(re.findall(r'_create_action\([^)]*?\["([^"]+)"\]', startup, re.S))

    body = DOC.read_text().split("### Terminal shortcuts versus application accelerators", 1)[1]
    documented = {
        _canonical(cells[0])
        for line in body.splitlines()
        if len(cells := [c.strip().strip("`") for c in line.strip().strip("|").split("|")]) == 2
        and cells[0].startswith(("Ctrl+", "F1"))
    }

    normalised = {
        _canonical(
            a.replace("<Primary>", "Ctrl+").replace("<Shift>", "Shift+").replace("<Alt>", "Alt+")
        )
        for a in registered
    }

    missing = documented - normalised
    assert not missing, f"documented accelerators that no action registers: {sorted(missing)}"


def test_doc_is_linked_from_the_readme():
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()

    assert "docs/TERMINAL-USAGE.md" in readme
