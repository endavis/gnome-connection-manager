"""Every user-visible string is English, and has an entry in every catalog.

The msgids are English (ADR-0003, #390), so a locale GCM has no catalog for -- `C`,
`C.UTF-8`, a language it lacks -- shows them as they are, in the Python messages and in the
glade file's texts alike. That holds only while no msgid is Spanish, which is what
`test_no_message_is_spanish` keeps. A message with no entry in a catalog shows in English
there, and is untranslated: that is what the other tests here keep out.
"""

from __future__ import annotations

import ast
import gettext
import json
import os
import re
import string
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree

import pytest

from tests.test_connections import glib_complaints

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "src" / "gnome_connection_manager" / "app.py"
# The modules that hold user-visible strings. A connection type marks its messages with
# N_ where it is defined, and app.py translates them where it shows them (#228).
SOURCES = (APP, REPO / "src" / "gnome_connection_manager" / "utils" / "connections.py")
PO_DIR = REPO / "lang"

# A literal in either quote. Five messages sit in single quotes inside f-strings, such as
# f"{_('Invalid file')}: {e}", and a pattern that took double quotes alone never saw
# them: measured, it found 265 messages where an AST walk of the sources finds 270 (#359).
_GETTEXT_CALL = re.compile(r"""_\(\s*("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')\s*\)""")

# Whether a msgid is Spanish. The msgids were Spanish until #390, and a Spanish one shows
# to everyone whose locale has no catalog, `C` and `C.UTF-8` among them. Accents alone do
# not answer that: "Permitir que las aplicaciones escriban en el portapapeles (OSC 52)"
# carried none, so it reached the preferences dialog untranslated with these checks passing
# (#90). Function words settle it, but only ones that are not also ordinary English: `no`,
# `con`, `sin`, `de`, `un` and `al` all appear in English UI text, and including `no`
# flagged "No open consoles".
#
# That caught fewer than half of the Spanish msgids #390 replaced: "Agregar", "Puerto Local"
# and "Siempre" carry no accent and no function word. The longer list is the words of those
# msgids that no English msgid uses, of four letters or more and not English words
# themselves (`active`, `anterior`, `central`, `final`, `mouse` and `todo` are), and with it
# all but two were caught: "Hay" and "Ver buffer", made of shorter words. A Spanish word in
# neither list still passes, so review is the rest of this guard.
_SPANISH = re.compile(
    r"[áéíóúñü¿¡]"
    r"|\b(el|los|las|una|del|para|por|que|su|desde|hasta|todos|esta|este"
    r"|abiertas|abra|abrir|acción|activar|actualizaciones|actualizar|agente|agregar"
    r"|alternas|ancho|anexar|aplicaciones|archivo|asignado|atajo|atajos|atencion|atención"
    r"|autenticación|blanco|botón|buscar|campana|campos|cerrar|clave|clonar|colores"
    r"|comando|comandos|como|compresión|comprobar|conectar|configuracion|confirma"
    r"|confirmar|consola|consolas|contiene|continuar|contraer|copiar|crear|crudo|cuando"
    r"|debe|defecto|dejar|derecho|desactiva|descripcion|descripción|desea|deshabilitar"
    r"|detiene|dinámica|dinámico|direccion|donar|duplicar|editar|eliminar|entrada|enviar"
    r"|errores|escriban|escritura|existe|existente|expandir|exportar|fijo|fondo"
    r"|formato|franjas|fuente|grabación|grabar|grupo|guardar|habilitar|historial"
    r"|horizontalmente|importar|incluye|ingresar|ingrese|iniciar|inicio|intervalo"
    r"|introducir|invalida|invalido|invertir|limpiar|lista|llegar|línea|líneas|marcar"
    r"|milisegundos|mismo|mostrar|nivel|nombre|notificar|nueva|nuevo|nunca|obligatorios"
    r"|ocultar|opciones|palabras|pantalla|paquetes|parámetros|pasar|pegar|permitir"
    r"|pestaña|portapapeles|predefinidos|preferencias|primer|privada|programa|propiedades"
    r"|puede|puerto|puertos|quitar|recibir|reconectar|reconstruyendo|redirección|redirigir"
    r"|registro|reiniciar|remoto|renombrar|requiere|ruta|salida|salir|salto|secuencias"
    r"|segundos|seleccionado|seleccionar|seleccione|selección|separador|separar|sequencias"
    r"|servidor|servidores|sesion|sesión|siempre|sobreescribirá|subgrupos|sólo|tamaño"
    r"|teclas|termina|texto|tiempo|tiene|tipo|todas|todavía|transcripción"
    r"|transparencia|título|túnel|unir|usar|usuario|utilizar|varios|ventana|verticalmente"
    r"|último"
    r")\b",
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
    source = """f"{_('There are')} {count} {_('open consoles, exit anyway?')}" _('')"""
    assert gettext_calls(source) == {"There are", "open consoles, exit anyway?"}


def test_a_message_with_an_escape_matches_its_catalog_entry(tmp_path):
    """The case #298 measured: `\\n` in the source and in a catalog's msgid."""
    po = tmp_path / "xx.po"
    po.write_text('msgid "one\\ntwo"\nmsgstr "eins\\nzwei"\n', encoding="utf-8")
    assert gettext_calls(r'_("one\ntwo")') <= catalog_msgids(po)


def spanish_marks(msgid):
    """What marks a msgid as Spanish: its accents, its function words and its words."""
    return [match.group(0) for match in _SPANISH.finditer(msgid)]


def test_no_message_is_spanish():
    """A Spanish msgid shows as it is wherever GCM reads no catalog (#390).

    Under `C` or `C.UTF-8`, with no locale set, and in a language GCM has no catalog for,
    both Python's gettext and glibc, which translates the glade file's texts, give back
    the msgid. So a msgid is the text everyone with no catalog reads, and it is English.
    """
    spanish = {
        msgid: spanish_marks(msgid)
        for msgid in sorted(translatable_strings() | glade_strings())
        if spanish_marks(msgid)
    }

    assert not spanish, f"these msgids are Spanish; write them in English: {spanish}"


@pytest.mark.parametrize(
    "msgid",
    [
        "Agregar",
        "Puerto Local",
        "Ruta de logs",
        "Copiar y Pegar",
        "Siempre",
        "Configuración",
        "Permitir que las aplicaciones escriban en el portapapeles (OSC 52)",
    ],
)
def test_a_spanish_message_is_caught(msgid):
    """Guards the guard: the first four carry no accent and no function word."""
    assert spanish_marks(msgid)


@pytest.mark.parametrize(
    "msgid",
    [
        "Add",
        "Local Port",
        "Logs path",
        "Copy and Paste",
        "Always",
        "No open consoles",
        "Let applications write to the clipboard (OSC 52)",
    ],
)
def test_an_english_message_is_not_caught(msgid):
    assert not spanish_marks(msgid)


def test_every_string_appears_in_every_catalog():
    """A msgid absent from a catalog is invisible to that language's translator."""
    strings = translatable_strings()
    missing = {}
    for po in sorted(PO_DIR.glob("*.po")):
        absent = strings - catalog_msgids(po)
        if absent:
            missing[po.name] = sorted(absent)[:5]

    assert not missing, f"msgids missing from catalogs: {missing}"


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


def test_every_glade_string_appears_in_every_catalog():
    strings = glade_strings()
    missing = {}
    for po in sorted(PO_DIR.glob("*.po")):
        absent = strings - catalog_msgids(po)
        if absent:
            missing[po.name] = sorted(s[:50] for s in absent)[:5]

    assert not missing, f"glade msgids missing from catalogs: {missing}"


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
    """A message a catalog leaves untranslated shows in English there.

    Each of the seven catalogs left about 200 so, until #359 translated them, and a
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
    assert form_problems("_Help", "H_ilfe") == []


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
# H_osts before Help. Two labels in one menu with one key are reached only by pressing it
# again, so each translation gives each label a key of its own (#359).
MENUS = {
    "menu bar": ("_File", "_Edit", "_View", "_Terminal", "_Servers", "H_osts", "_Help"),
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


# English has no catalog: its labels are the msgids, so `None` stands for English here, where
# a test is about what each language shows.
LANGUAGES = [None, *CATALOGS]


def language_name(po):
    return "English" if po is None else po.name


@pytest.mark.parametrize("po", LANGUAGES, ids=lambda po: "msgids" if po is None else po.stem)
def test_each_menu_gives_its_labels_keys_of_their_own(po):
    """Two labels in one menu with one key open their menus by turns (#382).

    Measured with real input, Alt+H opened Hosts and Help alternately while English gave
    both H. English is the msgids themselves, `H_osts` and `_Help`.
    """
    entries = {} if po is None else catalog_entries(po)
    for menu, labels in MENUS.items():
        keys = {label: access_key(entries.get(label) or label) for label in labels}

        assert len(set(keys.values())) == len(keys), f"{language_name(po)}, the {menu}: {keys}"


@pytest.mark.parametrize("po", CATALOGS, ids=lambda po: po.stem)
def test_every_compiled_catalog_matches_its_source(po):
    """GCM loads the .mo, so a .po changed and not compiled changes nothing."""
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


@pytest.mark.parametrize("po", LANGUAGES, ids=lambda po: "msgids" if po is None else po.stem)
def test_the_preferences_window_is_named_as_its_menu_items_are(po: Path | None) -> None:
    """The window's title and its toolbar button's tooltip say what the menu items say.

    Each as it reads in the catalog, the menu items without their access keys. The title
    and the tooltip were the msgid `Configuración`, which English gave as Settings and six
    of the seven other catalogs gave otherwise than the menu items. Only German agreed
    (#383).
    """
    entries: dict[str, str] = {} if po is None else catalog_entries(po)

    def shown(msgid: str) -> str:
        # What gettext gives: the msgid itself, where the catalog has no translation.
        return entries.get(msgid) or msgid

    menu_items = {label: without_access_key(shown(label)) for label in preferences_menu_labels()}
    named = {what: shown(prop.text or "") for what, prop in preferences_properties()}

    where = language_name(po)
    assert len(set(menu_items.values())) == 1, f"{where}: its menu items differ: {menu_items}"
    assert set(named.values()) == set(menu_items.values()), (
        f"{where}: the menu items say {menu_items}, but the window and its button say {named}"
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


# -- GCM shows English where it reads no catalog (#390) --

# GCM started as it starts itself, `register` and then `activate`, with Preferences and the
# dialog Add Host opens brought up through their actions. It prints, as JSON on its last
# line, every text the windows draw: labels, buttons, menu items, tooltips, tab names and
# titles. It runs in a clean interpreter, as conftest stubs gi for the whole session.
_ENGLISH_SCRIPT = r'''
"""Start GCM as it starts itself, open Preferences and the Add Host dialog through their
actions, and print every text the windows draw as JSON (the last line of stdout)."""
import json, locale, os, sys, tempfile, time
os.environ["HOME"] = tempfile.mkdtemp(); os.environ.pop("XDG_CONFIG_HOME", None)
os.environ["SHELL"] = "/bin/sh"; sys.argv = ["gcm"]
try:
    locale.setlocale(locale.LC_ALL, "")
    locale_ok = True
except locale.Error:
    locale_ok = False
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gio, Gtk
from gnome_connection_manager import app

app.conf.CHECK_UPDATES = False
app.conf.STARTUP_LOCAL = False
application = app.GcmApplication()
assert application.register(None)
application.activate()

def pump(seconds=0.5):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        Gtk.main_iteration_do(False)
        time.sleep(0.005)

pump(1.0)
application.activate_action("preferences", None)
pump(1.0)
application.activate_action("add-host", None)
pump(1.0)

def model_labels(model, found):
    for i in range(model.get_n_items()):
        label = model.get_item_attribute_value(i, "label", None)
        if label is not None:
            found.append(label.get_string())
        for name in (Gio.MENU_LINK_SECTION, Gio.MENU_LINK_SUBMENU):
            child = model.get_item_link(i, name)
            if child is not None:
                model_labels(child, found)
    return found

LABELLED = (Gtk.Button, Gtk.MenuItem, Gtk.Expander, Gtk.Frame, Gtk.ToolButton)

def texts(widget, found):
    if isinstance(widget, Gtk.Window) and widget.get_title():
        found.add(widget.get_title())
    if isinstance(widget, Gtk.Label):
        found.add(widget.get_text())
    elif isinstance(widget, LABELLED) and widget.get_label():
        found.add(widget.get_label())
    if isinstance(widget, Gtk.Entry) and widget.get_placeholder_text():
        found.add(widget.get_placeholder_text())
    tip = widget.get_tooltip_text()
    if tip:
        found.add(tip)
    if isinstance(widget, Gtk.Notebook):
        for i in range(widget.get_n_pages()):
            tab = widget.get_tab_label(widget.get_nth_page(i))
            if tab is not None:
                texts(tab, found)
    if isinstance(widget, Gtk.MenuItem) and widget.get_submenu() is not None:
        texts(widget.get_submenu(), found)
    if isinstance(widget, Gtk.Bin) and widget.get_child() is not None:
        texts(widget.get_child(), found)
    if isinstance(widget, Gtk.Container):
        for child in widget.get_children():
            texts(child, found)
    return found

windows = {}
for window in Gtk.Window.list_toplevels():
    if window.get_visible():
        windows[window.get_title() or window.get_name()] = sorted(texts(window, set()))
menus = model_labels(application.get_menubar(), [])
print(json.dumps({"locale_ok": locale_ok, "windows": windows, "menus": sorted(set(menus))}, ensure_ascii=False))
sys.stdout.flush()
os._exit(0)
'''


_SCRUBBED = {"LANG", "LANGUAGE", "GCM_DATA_DIR", "GCM_GLADE_DIR", "GCM_SCRIPTS_DIR"}


@pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"),
    reason="needs a display for real windows",
)
@pytest.mark.parametrize(
    ("lang", "language"),
    [
        pytest.param("", "", id="no-LANG"),
        pytest.param("C.UTF-8", "", id="C.UTF-8"),
        pytest.param("C.UTF-8", "nl", id="C.UTF-8-LANGUAGE=nl"),
        pytest.param("en_US.UTF-8", "", id="en_US.UTF-8"),
        pytest.param("en_US.UTF-8", "nl", id="en_US.UTF-8-LANGUAGE=nl"),
    ],
)
def test_gcm_shows_english_where_it_reads_no_catalog(lang, language):
    """With no locale set, under `C.UTF-8` and in a language GCM has no catalog for, GCM drew
    its Spanish msgids (#390).

    Measured on 9c8504c: the main window, Preferences and the host dialog each drew many of
    their texts so, and `LANG=en_US.UTF-8` alone drew none. Python's gettext stops at `C`,
    and glibc, which translates the glade file's texts, ignores `LANGUAGE` while
    `LC_MESSAGES` is `C` or `C.UTF-8`, so neither half reads a catalog there. English has no
    catalog now, so the `en_US.UTF-8` cases are the English locale that had one before.
    """
    pytest.importorskip("gi", reason="PyGObject not available")
    # The developer's own LANG, LANGUAGE and LC_* would decide the locale the case sets, or
    # leaves unset. GCM_DATA_DIR, which a GCM tab's shell carries, would have the scenario
    # read another checkout's glade file from a worktree.
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in _SCRUBBED and not key.startswith("LC_")
    }
    if lang:
        environment["LANG"] = lang
    if language:
        environment["LANGUAGE"] = language

    result = subprocess.run(
        [sys.executable, "-c", _ENGLISH_SCRIPT],
        capture_output=True,
        text=True,
        cwd=REPO,
        env=environment,
        timeout=90,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    # PyGObject prints what a signal handler raises, and carries on, so the scenario still
    # exits 0; and the criticals GLib reported are held out as the registry scenarios hold
    # them out. Measured on this change: all five cases print one line on stderr, "System
    # doesn't support transparency", which is neither.
    assert "Traceback" not in result.stderr, result.stderr[-2000:]
    assert glib_complaints(result.stderr) == [], result.stderr[-2000:]
    shown = json.loads(result.stdout.strip().splitlines()[-1])
    windows = shown["windows"]
    spanish = {
        title: marked
        for title, texts in windows.items()
        if (marked := [text for text in texts if spanish_marks(text)])
    }

    where = f"LANG={lang or '<unset>'} (set: {shown['locale_ok']}) LANGUAGE={language or '<unset>'}"
    assert not spanish, f"{where}: these are Spanish: {spanish}"
    # English, not merely not Spanish: the texts the bug showed as Agregar, Separador de
    # Palabras and Editar Host.
    assert {"Gnome Connection Manager", "Preferences", "Edit Host"} <= set(windows)
    assert {"Add", "Edit", "Remove", "Add new host"} <= set(windows["Gnome Connection Manager"])
    assert {"Word separator", "Buffer size", "Logs path"} <= set(windows["Preferences"])
    assert {"Name", "Port", "Private key"} <= set(windows["Edit Host"])
