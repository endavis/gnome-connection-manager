"""The Backspace and Delete choices of the host dialog keep their hint in a column of its
own (#384), in the real dialog: a name with no padding, a hint, one x for every hint, and the
stored index unchanged."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_connections import glib_complaints
from tests.test_i18n import build_private_locale, catalog_entries

REPO = Path(__file__).resolve().parents[1]

_SCRIPT = r"""
import json, os, sys, tempfile
import locale
os.environ["HOME"] = tempfile.mkdtemp(); os.environ.pop("XDG_CONFIG_HOME", None)
# The locale is the test's own (LANG, LOCPATH and LANGUAGE come from the caller): glibc
# ignores LANGUAGE while the locale is C, and GtkBuilder translates through glibc.
locale.setlocale(locale.LC_ALL, "")
sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gdk, Gtk
from gnome_connection_manager import app

app.conf.STARTUP_LOCAL = False
app.conf.CHECK_UPDATES = False
app.wMain = w = app.Wmain(application=None)
dialog = app.Whost()
dialog.init("", None)
out = {}
for key in ("cmbBackspace", "cmbDelete"):
    combo = getattr(dialog, key)
    rows = [(row[0], row[1]) for row in combo.get_model()]
    area = combo.get_area()
    renderers = area.get_cells()
    context = area.create_context()
    for row in combo.get_model():
        area.apply_attributes(combo.get_model(), row.iter, False, False)
        area.get_preferred_width(context, combo)
    width, _ = context.get_preferred_width()
    context.allocate(width, -1)
    xs = []
    for row in combo.get_model():
        area.apply_attributes(combo.get_model(), row.iter, False, False)
        rect = Gdk.Rectangle(); rect.x = 0; rect.y = 0; rect.width = width; rect.height = 40
        alloc = area.get_cell_allocation(context, combo, renderers[1], rect)
        xs.append(alloc.x)
    for n in range(5):
        combo.set_active(n)
        assert combo.get_active() == n
    out[key] = {"rows": rows, "renderers": len(renderers), "xs": xs}
print(json.dumps(out))
"""

_ROUND_TRIP = r"""
import configparser, os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(); os.environ.pop("XDG_CONFIG_HOME", None)
sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91")
from gnome_connection_manager import app

app.conf.STARTUP_LOCAL = False
app.conf.CHECK_UPDATES = False
app.wMain = w = app.Wmain(application=None)
pairs = [(1, 2), (3, 4), (4, 3), (0, 4)]
for n, (b, d) in enumerate(pairs):
    host = app.Host(
        "Work", "h%d" % n, "", "box.example", "alice", "s3cret", "", "22", "", "ssh",
        "", "0", "", "", False, False, False, "6", "", False, b, d, "xterm", False, "id-%d" % n,
    )
    app.groups.setdefault("Work", []).append(host)
w.writeConfig()
app.groups.clear()
w.loadConfig()
for n, (b, d) in enumerate(pairs):
    [host] = [h for h in app.groups["Work"] if h.id == "id-%d" % n]
    dialog = app.Whost()
    dialog.init("Work", host)
    assert (dialog.cmbBackspace.get_active(), dialog.cmbDelete.get_active()) == (b, d)
    dialog.on_okbutton1_clicked(None)
app.groups.clear()
w.loadConfig()
got = sorted((h.backspace_key, h.delete_key) for h in app.groups["Work"])
assert got == sorted(pairs), got
print("OK")
"""


def run(script, env=None):
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        cwd=REPO,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    assert "Traceback" not in result.stderr, result.stderr[-3000:]
    assert glib_complaints(result.stderr) == []
    return result.stdout.splitlines()[-1]


needs_display = pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="needs a display")


# Every language with a catalog: its glibc locale, its language code and its source.
LANGUAGES = {
    "de": ("de_DE", "de_DE.po"),
    "es": ("es_ES", "es_ES.po"),
    "fr": ("fr_FR", "fr_FR.po"),
    "it": ("it_IT", "it_IT.po"),
    "ko": ("ko_KR", "ko_KO.po"),
    "pl": ("pl_PL", "pl_PL.po"),
    "pt": ("pt_BR", "pt_BR.po"),
    "ru": ("ru_RU", "ru_RU.po"),
}
CHOICES = [
    "ASCII Backspace \t[Ctrl+H 0x08]",
    "ASCII Delete    \t[Ctrl+? 0x7F]",
    "Delete Sequence \t[@7]",
]


def environment(lang, folder):
    """The locale really set, as test_i18n's Spanish test sets it: a private locale of the
    test's own under LOCPATH, since LANGUAGE alone is ignored under C."""
    env = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {"LANG", "LANGUAGE", "LOCPATH", "GCM_DATA_DIR", "GCM_GLADE_DIR", "GCM_SCRIPTS_DIR"}
        and not key.startswith("LC_")
    }
    if lang != "en":
        name = LANGUAGES[lang][0] + ".UTF-8"
        if not build_private_locale(name, folder):
            pytest.skip(f"localedef cannot build {name} here")
        env.update(LOCPATH=str(folder), LANG=name, LANGUAGE=lang)
    return env


@needs_display
@pytest.mark.parametrize("lang", ["en", *LANGUAGES])
def test_hint_has_a_column_of_its_own(lang, tmp_path):
    pytest.importorskip("gi", reason="PyGObject not available")
    out = json.loads(run(_SCRIPT, environment(lang, tmp_path)))
    if lang == "en":
        expected = [text.split("\t") for text in CHOICES]
    else:
        entries = catalog_entries(REPO / "lang" / LANGUAGES[lang][1])
        expected = [entries[text].split("\t") for text in CHOICES]
        # The rows are the catalog's, not the msgids: every language translates a name.
        assert [e[0].rstrip() for e in expected] != [t.split("\t")[0].rstrip() for t in CHOICES]
    for combo, found in out.items():
        rows = found["rows"]
        assert len(rows) == 5, combo
        assert [name for name, _hint in rows[1:4]] == [e[0].rstrip() for e in expected], combo
        assert [hint for _name, hint in rows[1:4]] == [e[1] for e in expected], combo
        for name, hint in rows[1:4]:
            assert name == name.rstrip() and "\t" not in name, (combo, name)
            assert hint.startswith("["), (combo, hint)
        assert found["renderers"] == 2, combo
        # Every hint is drawn from one x, whatever its name's width.
        xs = [x for x, (_n, hint) in zip(found["xs"], rows, strict=True) if hint]
        assert len(xs) == 3 and len(set(xs)) == 1 and xs[0] > 0, (combo, found["xs"])


@needs_display
def test_the_stored_index_round_trips():
    pytest.importorskip("gi", reason="PyGObject not available")
    assert run(_ROUND_TRIP) == "OK"
