"""Every user-visible string must have a catalog entry.

The msgids in this project are Spanish, so a string with no entry does not fall back
to English -- it shows Spanish to everyone. That is how the buffer viewer shipped with
untranslated buttons, and how 80 other strings had drifted before it.
"""

from __future__ import annotations

import ast
import gettext
import re
import string
from pathlib import Path
from xml.etree import ElementTree

import pytest

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "src" / "gnome_connection_manager" / "app.py"
# The modules that hold user-visible strings. A connection type marks its messages with
# N_ where it is defined, and app.py translates them where it shows them (#228).
SOURCES = (APP, REPO / "src" / "gnome_connection_manager" / "utils" / "connections.py")
PO_DIR = REPO / "lang"
EN_PO = PO_DIR / "en_US.po"
EN_MO = PO_DIR / "en" / "LC_MESSAGES" / "gcm-lang.mo"

# A literal in either quote. Five messages sit in single quotes inside f-strings, such as
# f"{_('Archivo invalido')}: {e}", and a pattern that took double quotes alone never saw
# them: measured, it found 265 messages where an AST walk of the sources finds 270 (#359).
_GETTEXT_CALL = re.compile(r"""_\(\s*("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')\s*\)""")

# Whether a msgid is Spanish, and so needs an English translation before it is shown
# to an English user. Accents alone do not answer that: "Permitir que las aplicaciones
# escriban en el portapapeles (OSC 52)" carries none, so it reached the preferences
# dialog untranslated with these checks passing (#90). The glade half of this file had
# already learned the same lesson on "para historial" and "Ingrese el texto...".
#
# Function words settle it, but only ones that are not also ordinary English: `no`,
# `con`, `sin`, `de`, `un` and `al` all appear in English UI text, and including `no`
# flagged "No open consoles". Measured over the strings in app.py, the list below
# leaves all 38 translated Spanish msgids alone and still catches the one from #90.
_SPANISH = re.compile(
    r"[áéíóúñü¿¡]"
    r"|\b(el|los|las|una|del|para|por|que|su|desde|hasta|todos|esta|este)\b",
    re.I,
)
_MSGID = re.compile(r'^msgid "(.*)"$', re.M)
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


def unescape(text):
    """Undo .po escaping, so a msgid compares equal to the string gettext looks up.

    Without this a glade label containing a tab or newline never matches its catalog
    entry, and the check silently passes over exactly the strings most likely to be
    mis-transcribed by hand.
    """
    out, index = [], 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            out.append(_ESCAPES.get(text[index + 1], text[index + 1]))
            index += 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


_CONTINUATION = re.compile(r'^"(.*)"$', re.M)


def catalog_msgids(po):
    """Every msgid in a .po, including gettext's multi-line continuation form.

    A long entry is written as `msgid ""` followed by quoted continuation lines; a
    naive single-line regex reports those as missing.
    """
    ids, current, collecting = set(), None, False
    for raw in po.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("msgid "):
            if current is not None:
                ids.add(current)
            current, collecting = unescape(line[6:].strip()[1:-1]), True
        elif line.startswith("msgstr"):
            if current is not None:
                ids.add(current)
            current, collecting = None, False
        elif collecting and line.startswith('"') and line.endswith('"'):
            current = (current or "") + unescape(line[1:-1])
    if current is not None:
        ids.add(current)
    return ids


def gettext_calls(text):
    """The messages `_()` is given in `text`, each literal read as Python reads it.

    The catalogs' msgids are unescaped, so a message kept as written, `\\n` as a
    backslash and an n, never matched its entry and was reported missing from every
    catalog (#298).
    """
    return {ast.literal_eval(s) for s in _GETTEXT_CALL.findall(text) if len(s) > 2}


def translatable_strings():
    return {s for path in SOURCES for s in gettext_calls(path.read_text(encoding="utf-8"))}


def test_extraction_finds_a_realistic_number_of_strings():
    """Guards the guard: a broken regex would make every check below vacuous."""
    assert len(translatable_strings()) > 100


def test_a_message_is_read_as_python_reads_it():
    """Not as `unescape` reads a msgid, which knows nothing of `\\u00e9`."""
    source = r'_("one\ntwo") _("a \"quoted\" word") _("\u00e9t\u00e9")'
    assert gettext_calls(source) == {"one\ntwo", 'a "quoted" word', "été"}


def test_a_single_quoted_message_is_found():
    """As inside an f-string, where the other quote is taken."""
    source = """f"{_('Hay')} {count} {_('consolas abiertas, confirma que desea salir?')}" _('')"""
    assert gettext_calls(source) == {"Hay", "consolas abiertas, confirma que desea salir?"}


def test_a_message_with_an_escape_matches_its_catalog_entry(tmp_path):
    """The case #298 measured: `\\n` in the source and in a catalog's msgid."""
    po = tmp_path / "xx.po"
    po.write_text('msgid "one\\ntwo"\nmsgstr "eins\\nzwei"\n', encoding="utf-8")
    assert gettext_calls(r'_("one\ntwo")') <= catalog_msgids(po)


def test_every_string_has_an_english_translation():
    catalog = gettext.GNUTranslations(EN_MO.open("rb"))

    untranslated = sorted(
        s for s in translatable_strings() if catalog.gettext(s) == s and _SPANISH.search(s)
    )

    assert not untranslated, (
        "these show Spanish text to an English user; add them to lang/en_US.po "
        f"and rebuild: {untranslated}"
    )


def test_every_string_appears_in_every_catalog():
    """A msgid absent from a catalog is invisible to that language's translator."""
    strings = translatable_strings()
    missing = {}
    for po in sorted(PO_DIR.glob("*.po")):
        absent = strings - catalog_msgids(po)
        if absent:
            missing[po.name] = sorted(absent)[:5]

    assert not missing, f"msgids missing from catalogs: {missing}"


def assert_mo_matches_po(strings, label):
    """Every translation the .po states must be the one the .mo returns.

    Checking `gettext(s)` for truthiness does not work: gettext returns the msgid when
    there is no entry, so a missing translation looks like a present one. Both staleness
    checks here were vacuous until this compared the two files directly.
    """
    catalog = gettext.GNUTranslations(EN_MO.open("rb"))
    entries = catalog_entries(EN_PO)

    stale = sorted(s for s in strings if entries.get(s) and catalog.gettext(s) != entries[s])

    assert not stale, (
        f"lang/en/LC_MESSAGES/gcm-lang.mo is behind lang/en_US.po for {label}: "
        f"{[x[:60] for x in stale]}"
    )


def test_the_compiled_catalog_is_not_stale():
    """.mo is what the application loads; editing .po alone changes nothing at runtime."""
    assert_mo_matches_po(translatable_strings(), "source strings")


@pytest.mark.parametrize(
    ("msgid", "expected"),
    [
        ("Copiar selección", "Copy selection"),
        ("Actualizar", "Refresh"),
        ("Cerrar", "Close"),
        ("Buscar", "Search"),
        ("Ver buffer", "View buffer"),
        ("Consola", "Console"),
    ],
)
def test_buffer_viewer_strings_are_translated(msgid, expected):
    """The reported bug: these rendered as Spanish in an English UI."""
    catalog = gettext.GNUTranslations(EN_MO.open("rb"))

    assert catalog.gettext(msgid) == expected


def catalog_entries(po):
    """msgid -> msgstr for a .po, handling continuation lines."""
    entries, msgid, msgstr, field = {}, None, "", None
    for raw in po.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("msgid "):
            if msgid is not None:
                entries[msgid] = msgstr
            msgid, msgstr, field = unescape(line[6:].strip()[1:-1]), "", "id"
        elif line.startswith("msgstr "):
            msgstr, field = unescape(line[7:].strip()[1:-1]), "str"
        elif line.startswith('"') and line.endswith('"') and field:
            if field == "id":
                msgid += unescape(line[1:-1])
            else:
                msgstr += unescape(line[1:-1])
    if msgid is not None:
        entries[msgid] = msgstr
    return entries


def test_the_english_source_catalog_has_no_blank_translations():
    """The .mo is what loads, so a blanked .po hides until the next rebuild."""
    entries = catalog_entries(EN_PO)

    blank = sorted(
        s for s in translatable_strings() if _SPANISH.search(s) and not entries.get(s, "")
    )

    assert not blank, f"lang/en_US.po has no translation for: {blank}"


# -- the glade file carries half the UI text (#80) ---------------------------

GLADE = REPO / "data" / "ui" / "gnome-connection-manager.glade"

# Not UI text. Glade emits placeholder names for unnamed widgets, and localhost is a
# host name, where a translation would be wrong. The connection types were here too, until
# the host dialog took its list from the registry (#228).
_NOT_UI_TEXT = {"label", "page 1", "page 2", "localhost"}
_PLACEHOLDER_PREFIX = "__glade_unnamed_"


def glade_strings(glade=GLADE):
    """Each translatable text as GtkBuilder looks it up: as written, edge spaces and all.

    Measured with a catalog holding both forms of a label that ends in a space, GtkBuilder
    showed the spaced form's translation. Stripped here, the check asked every catalog for
    an entry nothing reads, and none for the one the label shows (#359).
    """
    tree = ElementTree.parse(glade)
    found = set()
    for tag in ("property", "item"):
        for element in tree.iter(tag):
            if element.get("translatable") != "yes":
                continue
            text = element.text or ""
            bare = text.strip()
            if not bare or bare in _NOT_UI_TEXT or bare.startswith(_PLACEHOLDER_PREFIX):
                continue
            found.add(text)
    return found


def test_a_glade_text_keeps_its_edge_spaces(tmp_path):
    glade = tmp_path / "x.glade"
    glade.write_text(
        '<interface><object class="GtkLabel">'
        '<property name="label" translatable="yes">Enter text: </property>'
        "</object></interface>",
        encoding="utf-8",
    )
    assert glade_strings(glade) == {"Enter text: "}


def test_glade_string_extraction_finds_a_realistic_number():
    """Guards the guard: a broken parse would make the checks below vacuous."""
    assert len(glade_strings()) > 50


def test_every_glade_string_has_an_english_translation():
    """Four of these rendered as Spanish because nothing checked the glade file.

    Compared against the catalog rather than guessed at by language: the first attempt
    used an accent heuristic and missed all four, because "para historial" and
    "Ingrese el texto..." contain no accented characters.
    """
    catalog = catalog_entries(EN_PO)

    untranslated = sorted(s for s in glade_strings() if not catalog.get(s))

    assert not untranslated, (
        f"glade strings with no English translation: {[s[:60] for s in untranslated]}"
    )


def test_every_glade_string_appears_in_every_catalog():
    strings = glade_strings()
    missing = {}
    for po in sorted(PO_DIR.glob("*.po")):
        absent = strings - catalog_msgids(po)
        if absent:
            missing[po.name] = sorted(s[:50] for s in absent)[:5]

    assert not missing, f"glade msgids missing from catalogs: {missing}"


def test_the_compiled_catalog_covers_the_glade_strings():
    """The .mo is what GtkBuilder reads; editing .po alone changes nothing at runtime."""
    assert_mo_matches_po(glade_strings(), "glade strings")


# -- every catalog translates every message, keeping what the code relies on (#359) --

CATALOGS = sorted(PO_DIR.glob("*.po"))
_TAG = re.compile(r"<[^>]+>")
# GNOME's convention: its msgstr names the catalog's translators, and translates nothing.
_NOT_A_TRANSLATION = {"translator-credits"}


def compiled(po):
    """The catalog GCM loads for a source: `lang/de_DE.po` compiles to `lang/de/...`."""
    return PO_DIR / po.stem.split("_")[0] / "LC_MESSAGES" / "gcm-lang.mo"


@pytest.mark.parametrize("po", CATALOGS, ids=lambda po: po.stem)
def test_every_message_is_translated_in_every_catalog(po):
    """A message a catalog leaves untranslated shows in English, or in Spanish.

    Each of the seven other catalogs left about 200 so, until #359 translated them, and a
    message added since has to come with its translations.
    """
    entries = catalog_entries(po)
    untranslated = sorted(s for s in translatable_strings() | glade_strings() if not entries.get(s))

    assert not untranslated, f"{po.name} has no translation for: {[s[:60] for s in untranslated]}"


def format_fields(text):
    """The `str.format` fields in a message, positional `{}` as an empty name."""
    return sorted(field for _, field, _, _ in string.Formatter().parse(text) if field is not None)


def form_problems(msgid, msgstr):
    """What a translation changed of the parts the code relies on."""
    problems = []
    try:
        if format_fields(msgid) != format_fields(msgstr):
            problems.append("placeholders")
    except ValueError:
        problems.append("a lone brace")
    # A menu label's underscore marks its access key, and one a translation adds to any
    # other label marks one there: a menu built from a model reads it so.
    if msgid.count("_") != msgstr.count("_"):
        problems.append("underscores")
    if _TAG.findall(msgid) != _TAG.findall(msgstr):
        problems.append("markup")
    if msgid.count("\n") != msgstr.count("\n"):
        problems.append("newlines")
    if msgid.count("\t") != msgstr.count("\t"):
        problems.append("tabs")
    return problems


@pytest.mark.parametrize(
    ("msgid", "msgstr", "problem"),
    [
        ("Pane {}", "Bereich", "placeholders"),
        ("Paste {lines} lines", "{zeilen} Zeilen einfügen", "placeholders"),
        ("Mounted ({})", "Eingehängt ({)", "a lone brace"),
        ("_File", "Datei", "underscores"),
        ("Copy", "_Kopieren", "underscores"),
        ("<span size='smaller'>{name}</span>", "<span>{name}</span>", "markup"),
        ("written by\nCopyright", "geschrieben von Copyright", "newlines"),
        ("TTY Erase \t[@7]", "TTY-Löschen [@7]", "tabs"),
    ],
)
def test_a_broken_translation_is_caught(msgid, msgstr, problem):
    assert problem in form_problems(msgid, msgstr)


def test_a_faithful_translation_passes():
    assert (
        form_problems("Could not mount {} at {}: {}", "Не удалось смонтировать {} в {}: {}") == []
    )
    assert form_problems("_Hosts", "H_osts") == []


@pytest.mark.parametrize("po", CATALOGS, ids=lambda po: po.stem)
def test_every_translation_keeps_what_the_code_relies_on(po):
    """Placeholders by name, an underscore, markup, newlines and tabs, as the msgid has them.

    A placeholder lost is a KeyError or a value missing from the message, and an
    underscore lost is a menu without its access key.
    """
    broken = {
        msgid[:50]: problems
        for msgid, msgstr in catalog_entries(po).items()
        if msgid and msgstr and msgid not in _NOT_A_TRANSLATION
        for problems in [form_problems(msgid, msgstr)]
        if problems
    }

    assert not broken, f"{po.name}: {broken}"


# The labels that carry an access key, by the menu each is in: _build_menus gives the menu
# bar its submenus and the application menu its three items, and install_menubar adds
# _Hosts before Help. Two labels in one menu with one key are reached only by pressing it
# again, so each translation gives each label a key of its own (#359).
MENUS = {
    "menu bar": ("_File", "_Edit", "_View", "_Terminal", "_Servers", "_Hosts", "_Help"),
    "application menu": ("_Preferences", "_About", "_Quit"),
}
# Names that hold an underscore and are no access key, kept as written in every catalog.
_UNDERSCORED_NAMES = ("GCM_PASSWORD",)


def access_key(label):
    return label[label.index("_") + 1].lower()


def test_every_label_with_an_access_key_is_in_a_listed_menu():
    """So a label added to a menu is checked against the others there."""
    listed = {label for labels in MENUS.values() for label in labels}
    keyed = {
        s
        for s in translatable_strings() | glade_strings()
        if "_" in s and not any(name in s for name in _UNDERSCORED_NAMES)
    }

    assert keyed == listed


@pytest.mark.parametrize("po", CATALOGS, ids=lambda po: po.stem)
def test_each_menu_gives_its_labels_keys_of_their_own(po):
    """Two labels in one menu with one key open their menus by turns (#382).

    Measured with real input, Alt+H opened Hosts and Help alternately while English gave
    both H.
    """
    entries = catalog_entries(po)
    for menu, labels in MENUS.items():
        keys = {label: access_key(entries.get(label) or label) for label in labels}

        assert len(set(keys.values())) == len(keys), f"{po.name}, the {menu}: {keys}"


@pytest.mark.parametrize("po", CATALOGS, ids=lambda po: po.stem)
def test_every_compiled_catalog_matches_its_source(po):
    """GCM loads the .mo, so a .po changed and not compiled changes nothing.

    Only English's was compared before, so another language's could fall behind unseen.
    """
    with compiled(po).open("rb") as handle:
        catalog = gettext.GNUTranslations(handle)
    stale = sorted(
        msgid
        for msgid, msgstr in catalog_entries(po).items()
        if msgid and msgstr and catalog.gettext(msgid) != msgstr
    )

    assert not stale, f"{compiled(po).relative_to(REPO)} is behind {po.name}: {stale[:5]}"


# -- one name for Preferences, and no entry left unused (#383) --

# A label app.py gives the action that opens Preferences, wrapped or not.
_PREFERENCES_LABEL = re.compile(r'_\(\s*("(?:[^"\\]|\\.)*")\s*\),\s*"app\.preferences"')
# An access key marked as most catalogs mark it, `_Preferences`, or as GNOME's Korean does,
# `기본 설정(_P)`.
_ACCESS_KEY = re.compile(r"\(_\w\)|_")


def preferences_menu_labels() -> list[str]:
    """The labels `app.py` gives the action that opens Preferences, as Python reads them."""
    text = APP.read_text(encoding="utf-8")
    return [ast.literal_eval(label) for label in _PREFERENCES_LABEL.findall(text)]


def preferences_properties(glade: Path = GLADE) -> list[tuple[str, ElementTree.Element]]:
    """What names Preferences in the glade file: (`title` or `tooltip`, its property).

    The title is the window's, `wConfig`'s. The tooltip is the main toolbar button's, which
    has no id of its own to find it by, so it is the one on the same action as the menus.
    """
    found = []
    for element in ElementTree.parse(glade).iter("object"):
        properties = {prop.get("name"): prop for prop in element.findall("property")}
        action = properties.get("action-name")
        opens_preferences = action is not None and action.text == "app.preferences"
        if element.get("id") == "wConfig" and "title" in properties:
            found.append(("title", properties["title"]))
        if opens_preferences and "tooltip-text" in properties:
            found.append(("tooltip", properties["tooltip-text"]))
    return found


def without_access_key(label: str) -> str:
    """A menu label's name: the label with its access key taken off."""
    return _ACCESS_KEY.sub("", label)


@pytest.mark.parametrize(
    ("label", "name"),
    [
        pytest.param("_Preferences", "Preferences", id="underscore"),
        pytest.param("기본 설정(_P)", "기본 설정", id="bracketed"),
        pytest.param("Preferences", "Preferences", id="no-key"),
    ],
)
def test_an_access_key_is_taken_off_a_label(label: str, name: str) -> None:
    """The key is an underscore before a letter, or, in Korean, one in brackets after the name."""
    assert without_access_key(label) == name


def test_the_texts_that_name_preferences_are_found() -> None:
    """Guards the guard: finding nothing would make the checks below vacuous.

    Each glade text must be translatable too. GtkBuilder shows one that is not as its
    msgid in every language, and reads no catalog for it.
    """
    found = preferences_properties()

    assert sorted(preferences_menu_labels()) == ["Preferences", "_Preferences"]
    assert sorted(what for what, _ in found) == ["title", "tooltip"]
    assert {prop.get("translatable") for _, prop in found} == {"yes"}


@pytest.mark.parametrize("po", CATALOGS, ids=lambda po: po.stem)
def test_the_preferences_window_is_named_as_its_menu_items_are(po: Path) -> None:
    """The window's title and its toolbar button's tooltip say what the menu items say.

    Each as it reads in the catalog, the menu items without their access keys. The title
    and the tooltip were the msgid `Configuración`, which English gave as Settings and six
    of the seven other catalogs gave otherwise than the menu items. Only German agreed
    (#383).
    """
    entries: dict[str, str] = catalog_entries(po)

    def shown(msgid: str) -> str:
        # What gettext gives: the msgid itself, where the catalog has no translation.
        return entries.get(msgid) or msgid

    menu_items = {label: without_access_key(shown(label)) for label in preferences_menu_labels()}
    named = {what: shown(prop.text or "") for what, prop in preferences_properties()}

    assert len(set(menu_items.values())) == 1, f"{po.name}: its menu items differ: {menu_items}"
    assert set(named.values()) == set(menu_items.values()), (
        f"{po.name}: the menu items say {menu_items}, but the window and its button say {named}"
    )


@pytest.mark.parametrize("po", CATALOGS, ids=lambda po: po.stem)
def test_no_catalog_keeps_an_entry_nothing_uses(po: Path) -> None:
    """An entry nothing asks for is never shown, and is kept in step with the rest for nothing.

    `Configuración` was one once the Preferences window took the Edit menu's msgid (#383).
    The header is the entry with an empty msgid. A message that moves to a module outside
    `SOURCES` shows up here as well, which is the cue to list the module.
    """
    used = translatable_strings() | glade_strings() | _NOT_A_TRANSLATION | {""}
    unused = sorted(catalog_msgids(po) - used)

    assert not unused, f"{po.name} keeps entries nothing uses: {[s[:60] for s in unused]}"
