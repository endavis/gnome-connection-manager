"""`inputbox` must actually open. It did not (#2).

`Gtk.Button(_label=...)` is not a rendering nit -- there is no such property, so the
constructor raises and `EntryDialog` cannot be built at all. That took down every
caller of `inputbox`: renaming a console, and the password prompts for importing and
exporting hosts.

conftest stubs `gi` for the whole session, and a stub happily accepts `_label=`, so
this has to run against real GTK in a clean interpreter.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

_DIALOG_SCRIPT = """
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(); sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk
from gnome_connection_manager import app

dialog = app.EntryDialog("title", "message", "default", mask=True)

buttons = []
def walk(widget):
    if isinstance(widget, Gtk.Button) and widget.get_label():
        buttons.append((widget.get_label(), widget.get_use_underline()))
    if isinstance(widget, Gtk.Container):
        for child in widget.get_children():
            walk(child)
walk(dialog)

labels = [text for text, _ in buttons]
assert len(buttons) == 2, "expected OK and Cancel, got %r" % (labels,)
for text, mnemonic in buttons:
    assert mnemonic, "%r shows a literal underscore instead of a mnemonic" % (text,)

entry = dialog.entry
assert entry.get_text() == "default"
assert not entry.get_visibility(), "a password prompt must mask what is typed"

dialog.destroy()
print("ENTRY-DIALOG-OK")
"""


@pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"),
    reason="needs a display for a real window",
)
def test_the_entry_dialog_can_be_built_at_all():
    pytest.importorskip("gi", reason="PyGObject not available")
    result = subprocess.run(
        [sys.executable, "-c", _DIALOG_SCRIPT],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        timeout=90,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert "ENTRY-DIALOG-OK" in result.stdout


def test_gtk_button_really_has_no_underscore_label_property():
    """Why `_label=` raises rather than being ignored -- worth pinning, not recalling."""
    pytest.importorskip("gi", reason="PyGObject not available")
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    assert not hasattr(Gtk.Button.props, "_label")
    assert hasattr(Gtk.Button.props, "label")


def test_no_widget_is_constructed_with_an_underscore_label():
    """The same typo anywhere else would raise the same way.

    Anchored on a non-word character: `tab_label=` is a real and correct keyword on
    `append_page`, and a bare substring search reports three false positives on it.
    """
    source = (
        Path(__file__).resolve().parents[1] / "src/gnome_connection_manager/app.py"
    ).read_text(encoding="utf-8")

    assert not re.search(r"(?<![A-Za-z0-9])_label\s*=", source)
