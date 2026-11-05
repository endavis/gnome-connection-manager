"""A search must leave a console's links alone (#498), against a real Vte.Terminal.

Run as a subprocess by tests/test_search_links.py: conftest stubs `gi` for the session.
Prints what it measured, one `name: value` per line, and OK last.
"""

import os
import sys
import tempfile
import time
import warnings

os.environ["HOME"] = tempfile.mkdtemp()
sys.argv = ["gcm"]
warnings.simplefilter("ignore")

import io  # noqa: E402

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Vte", "2.91")
from gi.repository import Gdk, Gtk, Vte  # noqa: E402

from gnome_connection_manager import app  # noqa: E402
from gnome_connection_manager.utils import trace  # noqa: E402

# Unmistakable markers: the `links` trace must hold neither (#513).
SEARCH_MARK = "SEARCHMARKQZX"
TEXT_MARK = "TEXTMARKQZX"


def pump(seconds=0.3):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        Gtk.main_iteration_do(False)
        time.sleep(0.005)


traced = io.StringIO()
trace.configure({"GCM_TRACE": "links"}, traced)

window = Gtk.OffscreenWindow()
window.set_default_size(800, 400)
# on_terminal_click reads terminal > page > notebook, as a console in a tab has.
notebook = Gtk.Notebook()
page = Gtk.Box()
terminal = Vte.Terminal()
page.pack_start(terminal, True, True, 0)
notebook.append_page(page)
window.add(notebook)
window.show_all()
terminal.feed(f"see https://example.com/page and banana here {TEXT_MARK}\r\n".encode())
pump()

wmain = object.__new__(app.Wmain)
wmain.on_tab_focus = lambda *args: None
wmain.registerUrlRegexes(terminal)
entry = Gtk.Entry()
wmain.search_box = lambda: entry
wmain.get_target_terminal = lambda: terminal


def matched_column(word):
    text, _ = terminal.get_text_range_format(Vte.Format.TEXT, 0, 0, 0, 10000)
    return text.index(word) + 1


def matched(word):
    """The text VTE's match_check finds at `word`, or None."""
    text, _ = terminal.get_text_range_format(Vte.Format.TEXT, 0, 0, 0, 10000)
    assert text, (terminal.get_row_count(), terminal.get_column_count())
    column = text.index(word) + 1
    return terminal.match_check(column, 0)[0]


def search(text):
    entry.set_text(text)
    wmain.init_search()
    pump(0.1)


print("link before any search:", matched("https"))
search("banana")
print("link after a search:", matched("https"))
print("searched word after a search:", matched("banana"))
search("here")
print("earlier word after another:", matched("banana"))
print("current word:", matched("here"))
search("")
print("link after an empty search:", matched("https"))
print("word after an empty search:", matched("banana"))
terminal.search_set_regex(None, 0)
wmain.search = {}
search("banana")
terminal.search_find_next()
print("search selects:", terminal.get_has_selection())

# What a Ctrl+click on the link hits: the real handler and a real VTE match. A GdkEvent made
# here is not hit-tested by VTE's match_check_event (measured: (None, 0) at every point of
# the row), so the match comes from match_check at the link's cell, as the event would give.
opened: list[str] = []
app.open_in_browser = opened.append
terminal.match_check_event = lambda _event: terminal.match_check(matched_column("https"), 0)
event = Gdk.Event.new(Gdk.EventType.BUTTON_PRESS)
click = event.button
click.button = 1
click.state = Gdk.ModifierType.CONTROL_MASK
wmain.on_terminal_click(terminal, click)
print("ctrl+click opens:", opened)
search(SEARCH_MARK)
search("")
print("OK")
print("TRACE-BEGIN")
print(traced.getvalue(), end="")
