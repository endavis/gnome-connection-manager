"""Exercise BufferViewer's colour rendering against a real Gtk.TextView.

Run as a subprocess by tests/test_vtehtml.py: conftest stubs `gi` for the whole test
session, so BufferViewer would otherwise inherit a stub Gtk.Window and prove nothing.
"""

import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp()
sys.argv = ["gcm"]

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Vte", "2.91")
from gi.repository import Gtk, Pango  # noqa: E402

from gnome_connection_manager import app  # noqa: E402

HTML = (
    "<pre>plain\n"
    '<font color="#C00000">RED</font> '
    '<font color="#00C000"><b>BOLD</b></font> '
    '<span style="background-color:#0000C0">BG</span> '
    '<u style="text-decoration-style:solid">UL</u>\n'
    "a &amp; b &lt;tag&gt;\n</pre>"
)


class Snapshot:
    def get_vadjustment(self):
        return type("A", (), {"get_lower": lambda s: 0, "get_upper": lambda s: 3})()

    def get_text_range_format(self, fmt, *args):
        return HTML if fmt == app.Vte.Format.HTML else "ignored"

    def get_text_format(self, fmt):
        return "ignored"


class NoHtml(Snapshot):
    """A terminal with no HTML export at all -- not from the range, not from the screen.

    Both routes have to refuse. Since #107 the HTML export falls through to the visible
    screen when the range comes back without text, so a fake that answers the screen
    call with plain text would feed that text to the HTML parser and never reach the
    fallback this is here to check.
    """

    def get_text_range_format(self, fmt, *args):
        if fmt == app.Vte.Format.HTML:
            raise RuntimeError("no html here")
        return "fallback text\n"

    def get_text_format(self, fmt):
        if fmt == app.Vte.Format.HTML:
            raise RuntimeError("no html here")
        return "ignored"


def settle():
    for _ in range(50):
        Gtk.main_iteration_do(False)


viewer = app.BufferViewer(None, Snapshot(), "colour")
viewer.show_all()
settle()

text = viewer.get_all_text()
assert text == "plain\nRED BOLD BG UL\na & b <tag>", repr(text)


def tags_at(needle):
    return viewer.buffer.get_iter_at_offset(text.index(needle)).get_tags()


red = tags_at("RED")[0]
assert red.get_property("foreground-set")
assert red.get_property("foreground-rgba").to_string() == "rgb(192,0,0)"

bold = tags_at("BOLD")[0]
assert bold.get_property("weight") == Pango.Weight.BOLD
assert bold.get_property("foreground-rgba").to_string() == "rgb(0,192,0)"

background = tags_at("BG")[0]
assert background.get_property("background-set")
assert not background.get_property("foreground-set")

assert tags_at("UL")[0].get_property("underline") == Pango.Underline.SINGLE
assert tags_at("plain") == [], "unstyled text must carry no tag"

# One tag per distinct style, not one per run.
assert len(viewer._style_tags) == 4, viewer._style_tags

fallback = app.BufferViewer(None, NoHtml(), "fallback")
fallback.show_all()
settle()
assert fallback.get_all_text() == "fallback text", repr(fallback.get_all_text())

viewer.destroy()
fallback.destroy()
print("OK")

# One tag object is reused for a repeated style, not merely one entry per style.
repeat = app.BufferViewer(
    None,
    type(
        "Repeat",
        (Snapshot,),
        {
            "get_text_range_format": lambda self, fmt, *a: (
                '<pre><font color="#C00000">a</font>x<font color="#C00000">b</font></pre>'
                if fmt == app.Vte.Format.HTML
                else "ignored"
            )
        },
    )(),
    "repeat",
)
repeat.show_all()
settle()
body = repeat.get_all_text()
first = repeat.buffer.get_iter_at_offset(body.index("a")).get_tags()[0]
second = repeat.buffer.get_iter_at_offset(body.index("b")).get_tags()[0]
assert first is second, "a repeated style must reuse its cached tag"
assert len(repeat._style_tags) == 1, repeat._style_tags
repeat.destroy()
print("REUSE-OK")

# The view must not sit on the theme background: light text on it is invisible.
import gi.repository.Gdk as Gdk  # noqa: E402


class Dark(Snapshot):
    def get_color_background_for_draw(self):
        colour = Gdk.RGBA()
        colour.parse("#1C1C1C")
        return colour


dark = app.BufferViewer(None, Dark(), "dark")
dark.show_all()
settle()
context = dark.view.get_style_context()
assert context.get_background_color(Gtk.StateFlags.NORMAL).to_string() == "rgb(28,28,28)"
assert context.get_color(Gtk.StateFlags.NORMAL).to_string() == "rgb(255,255,255)"
assert dark.match_tag.get_property("foreground-set"), "highlight needs a readable foreground"
dark.destroy()
print("COLOURS-OK")
