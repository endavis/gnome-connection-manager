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


# -- AGENTS.md must describe the tree that exists (#51) ---------------------

AGENTS = Path(__file__).resolve().parents[1] / "AGENTS.md"
REPO = AGENTS.parent

def _agents_references():
    return sorted(set(re.findall(r"`([^`]+)`", AGENTS.read_text())))


# Suffixes that mark a reference as naming a file in this repo. Anything else -- API
# names like Gtk.Builder, bare globs like .deb, absolute system paths -- is left alone.
_FILE_SUFFIXES = (".py", ".md", ".glade", ".css", ".png", ".gif", ".expect", ".toml", ".desktop")
_REPO_DIRS = ("src/", "data/", "tests/", "docs/", "lang/")

# Bare filenames allowed as shorthand, but only where the full path is also given.
_SHORTHAND = {"app.py", "main.py", "__main__.py", "conftest.py"}


def _agents_file_refs():
    refs = []
    for ref in _agents_references():
        if " " in ref or ref.startswith(("/", "~", "$", ".")):
            continue
        if ref.endswith(_FILE_SUFFIXES) or ref.startswith(_REPO_DIRS):
            refs.append(ref)
    return refs


def test_agents_md_references_paths_that_exist():
    """The previous version described the pre-src/ layout and had 11 dead references.

    A reference is wrong two ways: the path may not exist at all, or -- the case that
    actually happened -- it may name a bare filename that lives somewhere else now.
    """
    refs = _agents_file_refs()
    assert len(refs) >= 10, f"reference extraction looks broken, only found {refs}"

    problems = []
    for ref in refs:
        if (REPO / ref).exists():
            continue
        base = Path(ref).name
        if base in _SHORTHAND:
            if not any(r.endswith("/" + base) for r in refs):
                problems.append(f"{ref}: used as shorthand but its full path is never given")
            continue
        elsewhere = [
            str(h.relative_to(REPO))
            for h in REPO.rglob(base)
            if ".git" not in h.parts and ".venv" not in h.parts
        ]
        problems.append(
            f"{ref}: does not exist" + (f", actual location {elsewhere}" if elsewhere else "")
        )

    assert not problems, "AGENTS.md is out of step with the tree: " + "; ".join(problems)


def test_agents_md_names_symbols_that_exist():
    """It names symbols rather than line numbers, so the names have to be real."""
    source = (REPO / "src" / "gnome_connection_manager" / "app.py").read_text()

    for symbol in ("conf", "CONFIG_OPTIONS", "SHORTCUT_DEFAULTS", "TERMINAL_ACTIONS"):
        assert symbol in AGENTS.read_text(), f"AGENTS.md no longer names {symbol}"
        assert re.search(rf"^(class |){symbol}\b", source, re.M), f"{symbol} is gone from app.py"


def test_agents_md_carries_no_line_number_references():
    """Line numbers rot: the old file pointed at a path:line wrong in both halves."""
    stale = re.findall(r"`[^`]*\.py:\d+`", AGENTS.read_text())

    assert not stale, f"replace line-number references with symbol names: {stale}"


def test_agents_md_does_not_claim_tests_are_manual():
    text = AGENTS.read_text().lower()

    assert "tests are manual" not in text
    assert "just test" in text


def test_agents_md_lists_the_locales_that_exist():
    locales = sorted(p.name for p in (REPO / "lang").iterdir() if p.is_dir())
    text = AGENTS.read_text()

    for locale in locales:
        assert re.search(rf"\b{locale}\b", text), f"AGENTS.md omits the {locale} locale"
