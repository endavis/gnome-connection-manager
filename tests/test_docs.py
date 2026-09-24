"""Documentation that states facts about the code has to be checked against the code.

docs/SPEC.md's shortcut table had already drifted -- it documented Ctrl+Shift+G for
find_back, which defaults to CTRL+H -- so the user-facing table gets a guard.
"""

from __future__ import annotations

import ast
import configparser
import gettext
import inspect
import logging
import re
import types
from pathlib import Path

import pytest
import yaml

DOC = Path(__file__).resolve().parents[1] / "docs" / "TERMINAL-USAGE.md"
# The user-facing guides between them, for the settings check below.
GUIDES = (DOC, DOC.with_name("HOSTS-AND-FOLDERS.md"))

# Settings Preferences draws a control for that no guide names, and why not. Every one of
# these predates the documentation this list was written with (#193); nothing added since
# belongs here without a reason that survives being read aloud. Documenting one means
# deleting its line, not editing it.
UNDOCUMENTED_SETTINGS = {
    "auto-close-tab": "what happens to a tab when its session ends; window behaviour",
    "check-updates": "whether GCM phones home at startup; nothing to do with a terminal",
    "confirm-close-tab": "confirmation dialogs, application behaviour",
    "confirm-close-tab-middle": "confirmation dialogs, application behaviour",
    "confirm-exit": "confirmation dialogs, application behaviour",
    "cycle-tabs": "whether Next Console wraps at the end; window behaviour",
    "disable-hosts-stripes": "striping in the server tree; appearance of the panel",
    "donate": "whether the donate button is shown",
    "startup-local": "whether a local console opens at startup",
    "transparency": "terminal background transparency; belongs in the terminal guide",
    "update-title": "whether the window title follows the console; window behaviour",
}

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


def _rebind_example():
    """The `[shortcuts]` block the guide gives for rebinding a shortcut, verbatim."""
    after = DOC.read_text().split("To rebind", 1)[1]
    return after.split("```ini\n", 1)[1].split("```", 1)[0]


def test_the_rebinding_example_rebinds(tmp_path, app_module, monkeypatch):
    """The example had the key and the command the wrong way round from the day it was
    written, and nothing said so: a reversed line is an option GCM never looks up (#165).
    So the block is loaded as it stands, through the real loadConfig."""
    block = _rebind_example()
    header, line = [text for text in block.splitlines() if text.strip()]
    assert header == "[shortcuts]"
    tokens = {command: token for command, token, _key in app_module.SHORTCUT_DEFAULTS}
    defaults = {command: key for command, _token, key in app_module.SHORTCUT_DEFAULTS}
    left, right = (part.strip() for part in line.split("=", 1))
    # whichever side names a command, so a reversed example fails rather than errors
    command, key = (left, right) if left in tokens else (right, left)
    assert command in tokens, f"the example names no command: {line}"
    assert key != defaults[command], "an example that keeps the default rebinds nothing"

    config = tmp_path / "gcm.conf"
    config.write_text(block)
    monkeypatch.setattr(app_module, "CONFIG_FILE", str(config))
    monkeypatch.setattr(app_module, "groups", {})
    monkeypatch.setattr(app_module, "shortcuts", {})
    object.__new__(app_module.Wmain).loadConfig()

    assert app_module.shortcuts.get(key) == tokens[command]
    assert app_module.shortcuts.get(defaults[command]) != tokens[command]


def _guide_sections():
    """The guide cut at every heading, as (heading, body) pairs."""
    parts = re.split(r"^(#{2,6} .+)$", DOC.read_text(), flags=re.M)
    return list(zip(parts[1::2], parts[2::2], strict=True))


def _options_examples(body):
    """Each `[options]` block a section gives: the line leading into it, the block as
    written, and its settings as (key, value) pairs."""
    examples = []
    for lead, block in re.findall(r"([^\n]*)\n\n```ini\n(.*?)```", body, re.S):
        header, *lines = block.splitlines()
        if header == "[options]":
            settings = [line.split("=", 1) for line in lines if "=" in line]
            pairs = [(key.strip(), value.strip()) for key, value in settings]
            examples.append((lead, block, pairs))
    return examples


def _options(app_module):
    """Each key GCM reads from `[options]`, mapped to its conf attribute and type."""
    return {
        option: (attr, kind)
        for attr, section, option, kind in app_module.CONFIG_OPTIONS
        if section == "options"
    }


def _english(app_module):
    """The compiled English catalog the application loads, as the refusal tests in
    test_transcript.py read it, so a stale catalog fails here too."""
    return gettext.translation(
        app_module.domain_name,
        localedir=Path(app_module.__file__).parents[2] / "lang",
        languages=["en"],
    )


def _preference_labels(app_module):
    """Each conf attribute Preferences has a control for, mapped to its English label."""
    source = inspect.getsource(app_module.Wconfig.new)
    english = _english(app_module)
    pairs = re.findall(r'_\(\s*"([^"]+)"\s*\),\s*"conf\.(\w+)"', source)
    return {attr: english.gettext(msgid) for msgid, attr in pairs}


def _parsed(kind, value):
    """What an `[options]` value means, read strictly: no inline comment survives this."""
    if kind is bool:
        return configparser.RawConfigParser.BOOLEAN_STATES[value.lower()]
    return kind(value)


def test_the_guide_names_each_setting_as_preferences_draws_it(app_module):
    """The guide gave only the gcm.conf key for settings Preferences has a control for,
    and an edit to gcm.conf while GCM runs is written over by its next save (#169).
    So wherever the guide names an `[options]` key, in an example or in its prose, the
    same section names the control, in bold and in the words the dialog draws: relabel a
    control and this fails.

    A label is compared up to its parenthetical, which the prose may drop -- "Record the
    raw session" for "Record the raw session (includes escape sequences)".
    """
    options = _options(app_module)
    labels = _preference_labels(app_module)
    named = 0
    for heading, body in _guide_sections():
        prose = re.sub(r"```.*?```", "", body, flags=re.S)
        keys = set(re.findall(r"`([a-z0-9-]+)`", prose)) & options.keys()
        keys |= {key for *_, settings in _options_examples(body) for key, _value in settings}
        text = " ".join(body.split())
        for key in sorted(keys):
            assert key in options, f"{heading}: `{key}` is not an option GCM reads"
            attr, _kind = options[key]
            assert attr in labels, f"{heading}: `{key}` has no control in Preferences to name"
            label = labels[attr].split(" (")[0]
            assert f"**{label}" in text, f"{heading}: names `{key}` but not **{labels[attr]}**"
            assert "Preferences" in text, f"{heading}: say that **{label}** is in Preferences"
            named += 1
    assert named, "the guide names no [options] setting at all; the test is misreading it"


def test_every_setting_preferences_draws_is_named_in_a_guide(app_module):
    """The other direction from the test above, which is the one that was missing.

    Every check ran guide -> code: a setting the guide mentioned had to name its control,
    its example had to load, its default had to be the real one. Nothing ran code -> guide,
    so a setting could ship with a control in Preferences and no mention anywhere and pass
    every test. Four did -- Copy screen if there is no selection and the three bell
    settings -- and were found by hand rather than by this suite (#193).

    UNDOCUMENTED_SETTINGS is the deliberate remainder. Adding a line to it is a decision
    about a reader, so it needs a reason; the assertion below refuses a blank one.
    """
    options = _options(app_module)
    labels = _preference_labels(app_module)
    guides = " ".join(" ".join(path.read_text(encoding="utf-8").split()) for path in GUIDES)
    key_for = {attr: key for key, (attr, _kind) in options.items()}

    for key, reason in sorted(UNDOCUMENTED_SETTINGS.items()):
        assert key in options, f"UNDOCUMENTED_SETTINGS names `{key}`, which GCM does not read"
        assert reason.strip(), f"{key}: say why it is left out"

    missing = sorted(
        key_for[attr]
        for attr, label in labels.items()
        if key_for[attr] not in UNDOCUMENTED_SETTINGS
        and key_for[attr] not in guides
        and label not in guides
    )
    assert not missing, (
        "settings with a control in Preferences that no guide names by key or by label: "
        f"{missing}. Document them, or add each to UNDOCUMENTED_SETTINGS with a reason."
    )

    documented = sorted(key for key in UNDOCUMENTED_SETTINGS if key in guides)
    assert not documented, f"documented after all, so drop from UNDOCUMENTED_SETTINGS: {documented}"


def test_each_options_example_says_when_it_applies_and_to_close_gcm_first():
    """A reader changing a setting needs to know whether a session already open sees the
    change. And an example on its own was a trap: GCM writes `[options]` from memory
    whenever it saves, so an edit made while it runs is written over (#166, #169)."""
    sections = [(heading, body) for heading, body in _guide_sections() if _options_examples(body)]
    assert sections, "the guide gives no [options] example at all"
    for heading, body in sections:
        text = " ".join(body.split())
        assert "with GCM closed" in text, f"{heading}: say to edit gcm.conf with GCM closed"
        assert re.search(r"straight away|opened after|next start", text), (
            f"{heading}: say whether a change applies straight away, to sessions opened "
            "after it, or at the next start"
        )


def test_each_options_example_loads_as_written(tmp_path, app_module, monkeypatch, caplog):
    """The pasting example had a `; comment` after each value. `;` only starts a comment
    at the beginning of a line, so all three values were rejected and the defaults used,
    with nothing but a log line to say so (#169). So each example is loaded through the
    real loadConfig, and has to set what it says."""
    options = _options(app_module)
    examples = [
        (block, settings)
        for _heading, body in _guide_sections()
        for _lead, block, settings in _options_examples(body)
    ]
    assert examples, "the guide gives no [options] example at all"
    config = tmp_path / "gcm.conf"
    monkeypatch.setattr(app_module, "CONFIG_FILE", str(config))
    monkeypatch.setattr(app_module, "groups", {})
    monkeypatch.setattr(app_module, "shortcuts", {})
    for block, settings in examples:
        config.write_text(block)
        caplog.clear()
        with caplog.at_level(logging.ERROR, logger="gnome_connection_manager"):
            object.__new__(app_module.Wmain).loadConfig()
        assert not caplog.records, caplog.text
        for key, value in settings:
            attr, kind = options[key]
            assert getattr(app_module.conf, attr) == _parsed(kind, value), f"{key} = {value}"


def test_an_example_given_with_its_defaults_shows_the_defaults(app_module):
    """ "With their defaults" is a claim about the code, and a number in prose drifts."""
    options = _options(app_module)
    checked = 0
    for heading, body in _guide_sections():
        for lead, _block, settings in _options_examples(body):
            if not re.search(r"with (its default|their defaults):$", lead):
                continue
            for key, value in settings:
                attr, kind = options[key]
                default = getattr(app_module.conf, attr)
                assert _parsed(kind, value) == default, f"{heading}: {key} defaults to {default}"
                checked += 1
    assert checked, "no example is given with its defaults; drop this test or the phrase"


def test_the_guide_gives_labels_as_english_draws_them(app_module):
    """The guide named the View buffer item by its Spanish msgid, "Ver buffer" (#172). A
    bold phrase that is a msgid with a different English translation is the source
    string, not what an English reader sees."""
    english = _english(app_module)
    source_strings = []
    for phrase in re.findall(r"\*\*(.+?)\*\*", DOC.read_text(), re.S):
        for part in re.split(r"\s*→\s*", " ".join(phrase.split())):
            if english.gettext(part) != part:
                source_strings.append(f"{part!r} is drawn as {english.gettext(part)!r}")
    assert not source_strings, source_strings


# How the guide spells each modifier the handler could test for.
_MODIFIER_NAMES = {"CONTROL_MASK": "Ctrl", "SHIFT_MASK": "Shift", "MOD1_MASK": "Alt"}


def _menu_modifiers(app_module, monkeypatch):
    """The modifiers that make a right-click open the terminal's menu while right-click
    pastes, found by trying each on the real handler."""
    monkeypatch.setattr(app_module.conf, "PASTE_ON_RIGHT_CLICK", 1)
    opened = []
    wmain = object.__new__(app_module.Wmain)
    wmain.terminal_paste = lambda _terminal: None
    wmain.set_context_terminal = lambda _terminal: opened.append(True)
    switch = types.SimpleNamespace(set_sensitive=lambda _value: None)
    wmain.popupMenu = types.SimpleNamespace(
        mnuCopy=switch, mnuSplitH=switch, mnuSplitV=switch, popup=lambda *_args: None
    )
    notebook = types.SimpleNamespace(get_n_pages=lambda: 1)
    notebook.get_parent = lambda: notebook
    terminal = types.SimpleNamespace(get_has_selection=lambda: False, get_parent=lambda: notebook)
    names = []
    for mask, name in _MODIFIER_NAMES.items():
        state = getattr(app_module.Gdk.ModifierType, mask)
        event = types.SimpleNamespace(
            type=app_module.Gdk.EventType.BUTTON_PRESS,
            button=3,
            x=0,
            y=0,
            time=0,
            get_state=lambda state=state: state,
        )
        opened.clear()
        wmain.on_terminal_click(terminal, event)
        if opened:
            names.append(name)
    return names


def test_the_guide_says_how_to_open_the_terminals_menu(app_module, monkeypatch):
    """Right-click pastes by default, so a guide that sent readers to "the right-click
    menu" sent them nowhere (#171). The section on the menu names the modifier that
    opens it, found on the real handler, and every other mention links to that section
    -- except a tab's right-click menu, which is another menu and always opens."""
    names = _menu_modifiers(app_module, monkeypatch)
    assert len(names) == 1, f"expected one modifier to open the menu, found {names}"
    section = " ".join(dict(_guide_sections())["## The terminal's menu"].split())
    assert f"**{names[0]}+right-click**" in section

    text = " ".join(DOC.read_text().split())
    text = text.replace("[the terminal's menu](#the-terminals-menu)", "")
    assert "the terminal's menu" not in text, "link each mention to the section"
    others = [word for word in re.findall(r"(\S+) right-click menus?", text) if word != "tab's"]
    assert not others, f"a right-click menu the guide does not say how to open: {others}"


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


@pytest.mark.parametrize("guide", [path.name for path in GUIDES])
def test_each_guide_is_linked_from_the_readme(guide):
    """A guide nobody links to is a guide nobody finds."""
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()

    assert f"docs/{guide}" in readme


# -- the front page has to say what GCM is, and stay true (#194) ------------

README = Path(__file__).resolve().parents[1] / "README.md"


def test_the_readme_says_what_gcm_does_before_how_to_build_it():
    """A visitor met "A tabbed SSH and telnet connection manager" and then
    `sudo apt install ruby`, with nothing in between about folders, cluster mode, port
    forwarding, recording or any of the rest. The feature list has to come first, because
    a reader who has to scroll past a build to find out what the thing is will not."""
    body = README.read_text(encoding="utf-8")
    headings = [line for line in body.splitlines() if line.startswith("## ")]

    assert "## What it does" in headings, "the README has no feature list"
    assert headings.index("## What it does") < headings.index("## Installation"), (
        "the feature list comes after the build instructions"
    )


def test_the_readme_shows_the_application():
    """A connection manager is a window; a front page for one should show it."""
    body = README.read_text(encoding="utf-8")
    images = re.findall(r"!\[([^\]]*)\]\(([^)]+)\)", body)

    assert images, "the README carries no screenshot"
    for alt, target in images:
        assert alt.strip(), f"{target} has no alt text"
        assert (README.parent / target).is_file(), f"{target} does not exist"


def test_the_readme_carries_no_phase_roadmap():
    """It claimed "Phase 2 Modernization: GTK refactors and logging/tests in progress"
    against a suite of more than a thousand tests. A roadmap on a front page rots faster
    than anything else on it; PROJECT_STRUCTURE.md is where that belongs."""
    body = README.read_text(encoding="utf-8")

    assert not re.search(r"Phase \d", body), "the README carries a development roadmap again"


def test_the_readme_links_every_doc_a_reader_would_want():
    """SPEC.md and the ADRs existed and were linked from nowhere."""
    body = README.read_text(encoding="utf-8")

    for target in ("docs/SPEC.md", "docs/decisions/", ".github/CONTRIBUTING.md"):
        assert target in body, f"the README does not link {target}"


def test_the_readme_warns_that_the_spec_is_a_port_that_is_not_being_built():
    """Linking SPEC.md without saying what it is sends the reader to a description of a
    Qt 6 program that does not exist."""
    body = " ".join(README.read_text(encoding="utf-8").split())
    link = body[body.index("docs/SPEC.md") :][:400]

    assert "not** being built" in link or "not being built" in link, (
        "the README links SPEC.md without saying it specifies a port that is not being built"
    )


def test_no_doc_claims_the_test_suite_is_still_to_be_written():
    """`docs/PROJECT_STRUCTURE.md` carried `- [ ] Add comprehensive test suite` unticked,
    twice, against a suite this test is part of."""
    structure = (Path(__file__).resolve().parents[1] / "docs" / "PROJECT_STRUCTURE.md").read_text()

    assert "- [ ] Add comprehensive test suite" not in structure, (
        "PROJECT_STRUCTURE.md still lists the test suite as unwritten"
    )


# -- internal links must land on a heading that exists ----------------------

_MARKDOWN_DOCS = [
    "docs/TERMINAL-USAGE.md",
    "docs/HOSTS-AND-FOLDERS.md",
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


# -- documents have to be findable: frontmatter and the site nav (#198) -----

DOCS_DIR = Path(__file__).resolve().parents[1] / "docs"
MKDOCS = Path(__file__).resolve().parents[1] / "mkdocs.yml"

# Vendored from pyproject-template and replaced wholesale on a sync, so their metadata is
# upstream's to get right, not ours.
VENDORED_DOC_DIRS = ("development", "template")

# Generated by tools/generate_doc_toc.py, which excludes it from its own scan.
GENERATED_DOCS = {"TABLE_OF_CONTENTS.md"}


def _our_docs():
    """Every document under docs/ that this project wrote."""
    for path in sorted(DOCS_DIR.rglob("*.md")):
        relative = path.relative_to(DOCS_DIR)
        if relative.parts[0] in VENDORED_DOC_DIRS or relative.as_posix() in GENERATED_DOCS:
            continue
        yield path


def _frontmatter(path: Path) -> dict:
    """The document's YAML frontmatter, read the way the TOC generator reads it."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    return yaml.safe_load(text[3 : text.index("---", 3)]) or {}


@pytest.mark.parametrize("path", list(_our_docs()), ids=lambda p: p.name)
def test_every_doc_we_wrote_carries_frontmatter(path):
    """Without it a document reaches no audience section of TABLE_OF_CONTENTS.md and shows
    there with no description -- which is how "For Users" came to list eight documents about
    the project template and none about GCM (#198).

    Parsing matters as much as presence: a colon in an unquoted YAML scalar makes
    `safe_load` raise, the generator swallows that and treats the file as having none. Three
    of these did, silently, the first time they were written.
    """
    meta = _frontmatter(path)

    assert meta, f"{path.name} has no frontmatter, or it does not parse as YAML"
    for key in ("title", "description", "audience", "tags"):
        assert meta.get(key), f"{path.name}: frontmatter has no {key}"
    assert "gcm" in meta["tags"], f"{path.name}: tag it `gcm` so it can be told from vendored docs"


@pytest.mark.parametrize("path", list(_our_docs()), ids=lambda p: p.name)
def test_our_docs_do_not_claim_the_templates_audience(path):
    """`audience: users` in the vendored documents means users of pyproject-template. A GCM
    document claiming it lands in the same list, which is the confusion this fixed."""
    audience = _frontmatter(path).get("audience", [])

    assert "users" not in audience, (
        f"{path.name}: `users` is the template's audience; GCM's readers are `gcm-users`"
    )


def _nav_documents():
    """Every .md path named in the mkdocs nav, however deeply nested."""

    class Loader(yaml.SafeLoader):
        """mkdocs.yml carries tags PyYAML does not know; they are not in the nav."""

    Loader.add_multi_constructor("tag:yaml.org,2002:python/name:", lambda *_: None)
    Loader.add_constructor("!ENV", lambda *_: None)

    def walk(node, found):
        if isinstance(node, dict):
            for value in node.values():
                walk(value, found)
        elif isinstance(node, list):
            for value in node:
                walk(value, found)
        elif isinstance(node, str) and node.endswith(".md"):
            found.append(node)
        return found

    return walk(yaml.load(MKDOCS.read_text(encoding="utf-8"), Loader=Loader)["nav"], [])


def test_the_site_nav_and_the_docs_directory_agree():
    """The nav is hand-written, so a new guide is invisible in a site build until somebody
    remembers it. `docs/HOSTS-AND-FOLDERS.md` was added and nothing failed (#198)."""
    nav = _nav_documents()
    on_disk = {path.relative_to(DOCS_DIR).as_posix() for path in DOCS_DIR.rglob("*.md")}

    assert sorted(set(nav) - on_disk) == [], "mkdocs.yml navigates to files that do not exist"
    assert sorted(on_disk - set(nav)) == [], "documents under docs/ that the site nav omits"
    assert len(nav) == len(set(nav)), "a document appears twice in the nav"


def test_the_toc_lists_our_guides_under_their_own_heading():
    """ "For Users" was filtered on the audience the template claims, so it listed the
    template's documents. GCM's carry tags of their own and the section follows those."""
    toc = (DOCS_DIR / "TABLE_OF_CONTENTS.md").read_text(encoding="utf-8")
    guides = toc.split("<!-- BEGIN:tag=gcm-guide -->")[1].split("<!-- END:")[0]

    for name in ("TERMINAL-USAGE.md", "HOSTS-AND-FOLDERS.md"):
        assert name in guides, f"the TOC's GCM section does not list {name}"
    assert "template/" not in guides, "the template's documents are back in GCM's section"


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
    """Whitespace is collapsed first: the prose wraps, so a figure and the words that
    identify it land on the same line only by luck."""
    found = re.search(pattern, re.sub(r"\s+", " ", SPEC.read_text()))
    assert found, f"SPEC.md no longer states a figure matching {pattern!r}"
    return int(found.group(1).replace(",", ""))


def _line_count(relative):
    return len((REPO / relative).read_text(encoding="utf-8", errors="replace").splitlines())


APP = "src/gnome_connection_manager/app.py"

# The modules the port would carry over are the ones that never reach for the toolkit.
_IMPORTS_TOOLKIT = re.compile(r"(?m)^import gi\b|gi\.repository")


def _test_lines():
    return sum(_line_count(path.relative_to(REPO)) for path in (REPO / "tests").rglob("*.py"))


def _toolkit_calls(name):
    return len(re.findall(rf"\b{name}\.", (REPO / APP).read_text()))


def _toolkit_free_lines():
    return sum(
        _line_count(path.relative_to(REPO))
        for path in sorted((REPO / "src").rglob("*.py"))
        if not _IMPORTS_TOOLKIT.search(path.read_text(encoding="utf-8"))
    )


def _conf_class_lines():
    """`conf` is plain defaults, so it carries over even though app.py does not."""
    tree = ast.parse((REPO / APP).read_text())
    found = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "conf"]

    assert found, "app.py no longer defines a `conf` class at module level"
    conf = found[0]

    assert conf.end_lineno is not None, "ast gave the class no end line"
    return conf.end_lineno - conf.lineno + 1


def _growth(baseline_pattern, actual):
    """How far a figure has come since it was first measured (490670f). The baseline is
    history, so it is read from the prose beside it rather than measured again -- what is
    checked is that the percentage still follows from the baseline and the tree."""
    return round(100 * (actual / _documented_figure(baseline_pattern) - 1))


@pytest.mark.parametrize(
    ("pattern", "measure"),
    [
        (r"`app\.py` is ([\d,]+) lines", lambda: _line_count(APP)),
        (
            r"~([\d,]+) direct toolkit calls",
            lambda: sum(map(_toolkit_calls, ("Gtk", "Gdk", "Vte"))),
        ),
        (r"\(([\d,]+) `Gtk\.`", lambda: _toolkit_calls("Gtk")),
        (r"([\d,]+) `Gdk\.`", lambda: _toolkit_calls("Gdk")),
        (r"([\d,]+) `Vte\.`", lambda: _toolkit_calls("Vte")),
        (
            r"([\d,]+) lines of Glade",
            lambda: _line_count("data/ui/gnome-connection-manager.glade"),
        ),
        (r"([\d,]+) lines of tests", _test_lines),
        (r"is ([\d,]+) lines, and the `conf` class", _toolkit_free_lines),
        (r"`conf` class inside `app\.py` another ([\d,]+)", _conf_class_lines),
        (
            r"`app\.py` by ([\d,]+)%",
            lambda: _growth(r"`app\.py` was ([\d,]+) lines", _line_count(APP)),
        ),
        (r"the tests by ([\d,]+)%", lambda: _growth(r"the tests were ([\d,]+)", _test_lines())),
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


# The share rewritten is a ratio of the figures above, so the relative allowance they use
# would wave through the 85% that stood against a true 77%. Three points is around 300
# lines moving between app.py and the modules that import no toolkit.
_SHARE_TOLERANCE = 3


def test_spec_effort_share_rewritten_is_still_roughly_true():
    """The one figure in §14 that had actually drifted, and the one the section rests on."""
    documented = _documented_figure(r"about ([\d,]+)% of the application is rewritten")
    carried = _toolkit_free_lines() + _conf_class_lines()
    total = sum(_line_count(path.relative_to(REPO)) for path in (REPO / "src").rglob("*.py"))
    actual = round(100 * (1 - carried / total))

    assert abs(actual - documented) <= _SHARE_TOLERANCE, (
        f"SPEC.md says {documented}% of the application is rewritten, but {carried:,} of "
        f"{total:,} lines carry over, making it {actual}%; re-measure §14"
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


# The Makefile is checked too: its translate comment pointed at `just translate` for
# long enough to outlive the justfile, which is #148.
_JUST_FREE_FILES = [*_MARKDOWN_DOCS, "Makefile"]


@pytest.mark.parametrize("relative", _JUST_FREE_FILES)
def test_docs_do_not_invoke_just(relative):
    """The word survives in prose ("just a", "justified"); the command must not."""
    body = (REPO / relative).read_text(encoding="utf-8")

    found = sorted({m.group(0).strip() for m in _JUST_INVOCATION.finditer(body)})

    assert not found, f"{relative} still invokes the removed task runner: {found}"


# -- the Makefile's translate comment must point somewhere real (#148) ------

# It tells a reader where the other half of a deliberate duplication lives. That is only
# useful while the names resolve, and the reason this test exists is that they stopped:
# the comment went on naming a justfile recipe for 27 commits after the justfile was
# deleted, and #146 -- which swept the same drift out of the docs -- walked past it.
_TRANSLATE_COMMENT_REFERENTS = [
    ("tools/doit/gcm.py", "_compile_catalogs"),
    ("tools/build_mo.py", None),
]


def _translate_comment() -> str:
    """The comment block immediately above the Makefile's translate target."""
    lines = (REPO / "Makefile").read_text(encoding="utf-8").splitlines()
    target = lines.index("translate:")
    start = target
    while start > 0 and lines[start - 1].startswith("#"):
        start -= 1
    return "\n".join(lines[start:target])


@pytest.mark.parametrize(("path", "symbol"), _TRANSLATE_COMMENT_REFERENTS)
def test_translate_comment_points_at_something_that_exists(path, symbol):
    comment = _translate_comment()
    assert path in comment, f"the Makefile's translate comment no longer names {path}"

    referent = REPO / path
    assert referent.is_file(), f"the comment names {path}, which is not in the tree"
    if symbol is not None:
        # Both directions. Asserting only that the tree still defines the symbol lets
        # the comment drift to a name nothing has, which is the failure being guarded.
        assert symbol in comment, f"the Makefile's translate comment no longer names {symbol}"
        assert f"def {symbol}" in referent.read_text(encoding="utf-8"), (
            f"the comment names {symbol}, which {path} no longer defines"
        )


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
