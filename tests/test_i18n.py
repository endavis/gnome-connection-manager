"""Every user-visible string must have a catalog entry.

The msgids in this project are Spanish, so a string with no entry does not fall back
to English -- it shows Spanish to everyone. That is how the buffer viewer shipped with
untranslated buttons, and how 80 other strings had drifted before it.
"""

from __future__ import annotations

import gettext
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "src" / "gnome_connection_manager" / "app.py"
PO_DIR = REPO / "lang"
EN_PO = PO_DIR / "en_US.po"
EN_MO = PO_DIR / "en" / "LC_MESSAGES" / "gcm-lang.mo"

_GETTEXT_CALL = re.compile(r'_\(\s*"((?:[^"\\]|\\.)*)"\s*\)')
_MSGID = re.compile(r'^msgid "(.*)"$', re.M)
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
            current, collecting = line[6:].strip()[1:-1], True
        elif line.startswith("msgstr"):
            if current is not None:
                ids.add(current)
            current, collecting = None, False
        elif collecting and line.startswith('"') and line.endswith('"'):
            current = (current or "") + line[1:-1]
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
    spanish = re.compile(r"[áéíóúñü¿¡]")

    untranslated = sorted(
        s for s in translatable_strings() if catalog.gettext(s) == s and spanish.search(s)
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


def test_the_compiled_catalog_is_not_stale():
    """.mo is what the application loads; editing .po alone changes nothing at runtime."""
    catalog = gettext.GNUTranslations(EN_MO.open("rb"))
    po_ids = catalog_msgids(EN_PO)

    unknown = sorted(s for s in translatable_strings() & po_ids if not catalog.gettext(s))

    assert not unknown, f"lang/en/LC_MESSAGES/gcm-lang.mo needs rebuilding for: {unknown}"


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
            msgid, msgstr, field = line[6:].strip()[1:-1], "", "id"
        elif line.startswith("msgstr "):
            msgstr, field = line[7:].strip()[1:-1], "str"
        elif line.startswith('"') and line.endswith('"') and field:
            if field == "id":
                msgid += line[1:-1]
            else:
                msgstr += line[1:-1]
    if msgid is not None:
        entries[msgid] = msgstr
    return entries


def test_the_english_source_catalog_has_no_blank_translations():
    """The .mo is what loads, so a blanked .po hides until the next rebuild."""
    entries = catalog_entries(EN_PO)
    spanish = re.compile(r"[áéíóúñü¿¡]")

    blank = sorted(
        s
        for s in translatable_strings()
        if spanish.search(s) and not entries.get(s, "")
    )

    assert not blank, f"lang/en_US.po has no translation for: {blank}"
