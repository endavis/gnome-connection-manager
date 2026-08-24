"""Every user-visible string must have a catalog entry.

The msgids in this project are Spanish, so a string with no entry does not fall back
to English -- it shows Spanish to everyone. That is how the buffer viewer shipped with
untranslated buttons, and how 80 other strings had drifted before it.
"""

from __future__ import annotations

import gettext
import re
from pathlib import Path
from xml.etree import ElementTree

import pytest

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "src" / "gnome_connection_manager" / "app.py"
PO_DIR = REPO / "lang"
EN_PO = PO_DIR / "en_US.po"
EN_MO = PO_DIR / "en" / "LC_MESSAGES" / "gcm-lang.mo"

_GETTEXT_CALL = re.compile(r'_\(\s*"((?:[^"\\]|\\.)*)"\s*\)')

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


def translatable_strings():
    return {s for s in _GETTEXT_CALL.findall(APP.read_text(encoding="utf-8")) if s}


def test_extraction_finds_a_realistic_number_of_strings():
    """Guards the guard: a broken regex would make every check below vacuous."""
    assert len(translatable_strings()) > 100


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

    stale = sorted(
        s
        for s in strings
        if entries.get(s) and catalog.gettext(s) != entries[s]
    )

    assert not stale, (
        f"lang/en/LC_MESSAGES/gcm-lang.mo is behind lang/en_US.po for {label}: "
        f"{[x[:60] for x in stale]}"
    )


def test_the_compiled_catalog_is_not_stale():
    """.mo is what the application loads; editing .po alone changes nothing at runtime."""
    assert_mo_matches_po(translatable_strings(), "app.py strings")


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
        s
        for s in translatable_strings()
        if _SPANISH.search(s) and not entries.get(s, "")
    )

    assert not blank, f"lang/en_US.po has no translation for: {blank}"


# -- the glade file carries half the UI text (#80) ---------------------------

GLADE = REPO / "data" / "ui" / "gnome-connection-manager.glade"

# Not UI text. Glade emits placeholder names for unnamed widgets, and the values below
# are protocol and host identifiers where a translation would be wrong.
_NOT_UI_TEXT = {"label", "page 1", "page 2", "local", "localhost", "ssh", "telnet"}
_PLACEHOLDER_PREFIX = "__glade_unnamed_"


def glade_strings():
    tree = ElementTree.parse(GLADE)
    found = set()
    for tag in ("property", "item"):
        for element in tree.iter(tag):
            if element.get("translatable") != "yes":
                continue
            text = (element.text or "").strip()
            if not text or text in _NOT_UI_TEXT or text.startswith(_PLACEHOLDER_PREFIX):
                continue
            found.add(text)
    return found


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
