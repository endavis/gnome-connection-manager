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

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Vte", "2.91")
from gi.repository import Gtk, Vte  # noqa: E402

from gnome_connection_manager import app  # noqa: E402


def pump(seconds=0.3):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        Gtk.main_iteration_do(False)
        time.sleep(0.005)


window = Gtk.OffscreenWindow()
window.set_default_size(800, 400)
terminal = Vte.Terminal()
window.add(terminal)
window.show_all()
terminal.feed(b"see https://example.com/page and banana here\r\n")
pump()

wmain = object.__new__(app.Wmain)
wmain.registerUrlRegexes(terminal)
entry = Gtk.Entry()
wmain.search_box = lambda: entry
wmain.get_target_terminal = lambda: terminal


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
print("OK")
