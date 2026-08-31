"""Documentation that states facts about the code has to be checked against the code.

docs/SPEC.md's shortcut table had already drifted -- it documented Ctrl+Shift+G for
find_back, which defaults to CTRL+H -- so the user-facing table gets a guard.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

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


# -- internal links must land on a heading that exists ----------------------

_MARKDOWN_DOCS = [
    "docs/TERMINAL-USAGE.md",
    "docs/SPEC.md",
    "docs/DEVELOPING.md",
    "docs/PROJECT_STRUCTURE.md",
    "AGENTS.md",
    "README.md",
]


def _heading_slug(heading: str) -> str:
    """GitHub's anchor for a heading: lowercased, punctuation dropped, spaces hyphenated."""
    text = re.sub(r"[^\w\s-]", "", heading.strip().lstrip("#").strip().lower())
    return re.sub(r"\s+", "-", text)


@pytest.mark.parametrize("relative", _MARKDOWN_DOCS)
def test_internal_links_resolve_to_a_heading(relative):
    """A cross-reference that goes nowhere is worse than no cross-reference: the reader
    is told the answer exists somewhere and then cannot find it."""
    path = Path(__file__).resolve().parents[1] / relative
    body = path.read_text(encoding="utf-8")
    slugs = {_heading_slug(line) for line in body.splitlines() if line.startswith("#")}

    broken = sorted({a for a in re.findall(r"\]\(#([^)]+)\)", body) if a not in slugs})

    assert not broken, f"{relative} links to headings that do not exist: {broken}"


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
_SHORTHAND = {"app.py", "main.py", "__main__.py", "conftest.py", "relay.py"}


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
    assert "doit test" in text


def test_agents_md_lists_the_locales_that_exist():
    locales = sorted(p.name for p in (REPO / "lang").iterdir() if p.is_dir())
    text = AGENTS.read_text()

    for locale in locales:
        assert re.search(rf"\b{locale}\b", text), f"AGENTS.md omits the {locale} locale"


# Modules AGENTS.md is expected to describe. Package markers carry nothing to say, and
# entry points are covered by the one prose line about them.
_UNDOCUMENTED_BY_DESIGN = {"__init__.py"}

# Directories under tools/ vendored from pyproject-template (#115). This test exists to
# stop AGENTS.md going stale about *our* modules; upstream tooling is maintained and
# documented in the template, and listing it here would mean re-describing someone else's
# code every time a sync pulls a new file in.
_VENDORED_FROM_TEMPLATE = {"pyproject_template", "doit", "hooks", "statusline"}
# Vendored files that sit directly in tools/ rather than in a directory of their own.
_VENDORED_FILES = {"generate_doc_toc.py"}


def source_modules():
    roots = [REPO / "src" / "gnome_connection_manager", REPO / "tools"]
    return sorted(
        path
        for root in roots
        if root.is_dir()
        for path in root.rglob("*.py")
        if path.name not in _UNDOCUMENTED_BY_DESIGN
        and "__pycache__" not in path.parts
        and not _VENDORED_FROM_TEMPLATE & set(path.parts)
        and path.name not in _VENDORED_FILES
    )


def test_agents_md_describes_every_module():
    """The existing path check is one-directional.

    It verifies that everything AGENTS.md names exists, which says nothing about modules
    it has never heard of. That asymmetry let the file go stale twice -- relay.py, osc52.py
    and vtehtml.py all landed without it noticing.
    """
    text = AGENTS.read_text()
    modules = source_modules()

    assert len(modules) >= 5, f"module discovery looks broken: {modules}"
    missing = [str(path.relative_to(REPO)) for path in modules if path.name not in text]

    assert not missing, f"AGENTS.md does not mention: {missing}"


SPEC = REPO / "docs" / "SPEC.md"

# The figures are approximate by intent ("measured from the current tree"), so this
# allows drift and objects only when they stop being true enough to quote. They were
# 30% and 169% out before anyone noticed.
_FIGURE_TOLERANCE = 0.20


def _documented_figure(pattern):
    found = re.search(pattern, SPEC.read_text())
    assert found, f"SPEC.md no longer states a figure matching {pattern!r}"
    return int(found.group(1).replace(",", ""))


def _line_count(relative):
    return len((REPO / relative).read_text(encoding="utf-8", errors="replace").splitlines())


@pytest.mark.parametrize(
    ("pattern", "measure"),
    [
        (
            r"`app\.py` is ([\d,]+) lines",
            lambda: _line_count("src/gnome_connection_manager/app.py"),
        ),
        (
            r"([\d,]+) lines of Glade",
            lambda: _line_count("data/ui/gnome-connection-manager.glade"),
        ),
        (
            r"([\d,]+) lines of tests",
            lambda: sum(_line_count(p.relative_to(REPO)) for p in (REPO / "tests").rglob("*.py")),
        ),
    ],
)
def test_spec_effort_figures_are_still_roughly_true(pattern, measure):
    """§14's port estimate rests on these, so a reader may well check them."""
    documented = _documented_figure(pattern)
    actual = measure()

    drift = abs(actual - documented) / max(actual, 1)
    assert drift <= _FIGURE_TOLERANCE, (
        f"SPEC.md says {documented:,} but the tree has {actual:,} ({drift:.0%} out); re-measure §14"
    )


# -- the task runner is doit, and the docs have to say so (#146) ------------

# `just` was replaced by `doit` in e944cdb. Every recipe was migrated, but three doc
# references were not, and one of them sat inside a block of otherwise-correct doit
# commands -- the shape of drift a reader trusts and a writer skims past.
_JUST_INVOCATION = re.compile(
    r"""
      install \s+ just \b        # cargo install just / apt install just
    | ` \s* just \b              # `just clean` in prose
    | ^ \s* just \b              # just clean, on its own line in a code block
    | github\.com/casey/just     # a link naming it as the project's task runner
    """,
    re.MULTILINE | re.VERBOSE,
)


@pytest.mark.parametrize("relative", _MARKDOWN_DOCS)
def test_docs_do_not_invoke_just(relative):
    """The word survives in prose ("just a", "justified"); the command must not."""
    body = (REPO / relative).read_text(encoding="utf-8")

    found = sorted({m.group(0).strip() for m in _JUST_INVOCATION.finditer(body)})

    assert not found, f"{relative} still invokes the removed task runner: {found}"


# doit's own subcommands, which are not tasks and so are not in tools/doit/.
_DOIT_BUILTINS = {"list", "help", "clean", "forget", "ignore", "auto", "info", "reset-dep"}


def _defined_task_names() -> set[str]:
    defined = set()
    for module in sorted((REPO / "tools" / "doit").glob("*.py")):
        source = module.read_text(encoding="utf-8")
        defined.update(re.findall(r"^def task_(\w+)", source, re.MULTILINE))
    return defined


def _command_lines(body: str) -> list[str]:
    """Every inline-code span and every line inside a fenced block.

    Prose says "the doit tasks" and "doit is a dev dependency"; only these two forms
    are a reader being told what to type, so only these two are checked.
    """
    lines = []
    in_fence = False
    for line in body.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            lines.append(line.strip())
        else:
            lines.extend(span.strip() for span in re.findall(r"`([^`]+)`", line))
    return lines


def test_documented_doit_tasks_all_exist():
    """A named task that does not exist is the failure #146 was made of: `just run`
    became `doit launch`, and nothing would have caught a doc that kept saying `run`."""
    known = _defined_task_names() | _DOIT_BUILTINS
    assert "launch" in known, "task discovery found nothing; the parser is wrong"

    unknown = {}
    for relative in _MARKDOWN_DOCS:
        named = set()
        for line in _command_lines((REPO / relative).read_text(encoding="utf-8")):
            found = re.match(r"doit\s+([a-z][\w-]*)", line)
            if found:
                named.add(found.group(1))
        missing = sorted(named - known)
        if missing:
            unknown[relative] = missing

    assert not unknown, f"docs name doit tasks that do not exist: {unknown}"
