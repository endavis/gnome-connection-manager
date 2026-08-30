"""Tests for parsing VTE's HTML grid export into styled runs."""

from __future__ import annotations

import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

from gnome_connection_manager.utils import vtehtml
from gnome_connection_manager.utils.vtehtml import parse_vte_html, plain_text


def styles(html):
    return [(text, style) for text, style in parse_vte_html(html)]


def test_plain_text_carries_no_style():
    assert styles("<pre>hello\n</pre>") == [("hello\n", {})]


def test_foreground_colour():
    runs = styles('<pre><font color="#C00000">red</font></pre>')

    assert runs == [("red", {vtehtml.FOREGROUND: "#C00000"})]


def test_background_colour_comes_from_the_style_property():
    runs = styles('<pre><span style="background-color:#0000C0">bg</span></pre>')

    assert runs == [("bg", {vtehtml.BACKGROUND: "#0000C0"})]


@pytest.mark.parametrize(
    ("markup", "attribute"),
    [
        ("<b>x</b>", vtehtml.BOLD),
        ("<i>x</i>", vtehtml.ITALIC),
        ('<u style="text-decoration-style:solid">x</u>', vtehtml.UNDERLINE),
        ("<strike>x</strike>", vtehtml.STRIKETHROUGH),
    ],
)
def test_attribute_tags(markup, attribute):
    assert styles(f"<pre>{markup}</pre>") == [("x", {attribute: True})]


def test_nested_tags_combine():
    runs = styles('<pre><font color="#00C000"><b>bold green</b></font></pre>')

    assert runs == [("bold green", {vtehtml.FOREGROUND: "#00C000", vtehtml.BOLD: True})]


def test_blink_is_ignored_but_its_text_survives():
    """There is no Gtk.TextTag for blinking, and a blinking log helps nobody."""
    assert styles("<pre><blink>still here</blink></pre>") == [("still here", {})]


def test_an_unknown_tag_does_not_swallow_its_text():
    assert styles("<pre><wat>kept</wat></pre>") == [("kept", {})]


def test_an_unknown_tag_does_not_unwind_a_real_one():
    """Every start must push and every end must pop, or styles leak past their close."""
    runs = styles('<pre><font color="#FF0000">a<wat>b</wat>c</font>d</pre>')

    assert runs == [("abc", {vtehtml.FOREGROUND: "#FF0000"}), ("d", {})]


def test_entities_are_decoded():
    """VTE escapes & < > " on the way out; the buffer must show the originals."""
    runs = styles("<pre>a &amp; b &lt;tag&gt; &quot;q&quot;</pre>")

    assert runs == [('a & b <tag> "q"', {})]


def test_unicode_passes_through():
    assert styles("<pre>é中文 😀</pre>") == [("é中文 😀", {})]


def test_adjacent_runs_with_the_same_style_are_merged():
    """Otherwise a few hundred lines become thousands of one-character tag applications."""
    runs = styles("<pre>one<blink>two</blink>three</pre>")

    assert runs == [("onetwothree", {})]


def test_styles_are_not_merged_across_a_change():
    runs = styles('<pre>a<font color="#FF0000">b</font>c</pre>')

    assert [text for text, _ in runs] == ["a", "b", "c"]


def test_plain_text_reconstructs_every_character():
    html = '<pre>plain\n<font color="#C00000">RED</font> <b>B</b>\na &amp; b\n</pre>'

    assert plain_text(parse_vte_html(html)) == "plain\nRED B\na & b\n"


@pytest.mark.parametrize("html", ["", None])
def test_empty_input(html):
    assert parse_vte_html(html) == []


def test_unclosed_tags_do_not_raise():
    """The parser must never be the reason the viewer fails to open."""
    assert plain_text(parse_vte_html('<pre><font color="#FF0000">dangling')) == "dangling"


def test_a_stray_close_tag_does_not_raise():
    assert plain_text(parse_vte_html("<pre>a</b>b</pre>")) == "ab"


# -- viewer integration (needs a real Gtk.TextView) --------------------------


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="needs a display for a real window")
def test_the_viewer_applies_colour_and_falls_back_cleanly():
    """conftest stubs gi session-wide, so the real TextView needs its own interpreter."""
    pytest.importorskip("gi", reason="PyGObject not available")
    check = Path(__file__).resolve().parent / "helpers" / "colour_viewer_check.py"
    result = subprocess.run(
        [sys.executable, str(check)],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        timeout=120,
    )

    assert result.returncode == 0, result.stderr[-2500:]
    assert "OK" in result.stdout
    assert "REUSE-OK" in result.stdout
    assert "COLOURS-OK" in result.stdout


# -- the view must follow the terminal's colours ----------------------------


class FakeRGBA:
    def __init__(self, red, green, blue, text):
        self.red, self.green, self.blue = red, green, blue
        self._text = text

    def to_string(self):
        return self._text


class ColourTerminal:
    def __init__(self, background=None, host=None, raises=False):
        self._background = background
        self._raises = raises
        if host is not None:
            self.host = host

    def get_color_background_for_draw(self):
        if self._raises:
            raise RuntimeError("no colour here")
        return self._background


@pytest.mark.parametrize(
    ("rgb", "expected"),
    [
        ((0.0, 0.0, 0.0), "#FFFFFF"),
        ((0.11, 0.11, 0.11), "#FFFFFF"),
        ((1.0, 1.0, 1.0), "#000000"),
        ((0.93, 0.93, 0.92), "#000000"),
    ],
)
def test_contrasting_foreground(app_module, rgb, expected):
    """Picked by luma, because VTE has no getter for its default foreground."""
    assert app_module.contrasting_foreground(FakeRGBA(*rgb, "x")) == expected


def test_contrasting_foreground_without_a_colour(app_module):
    assert app_module.contrasting_foreground(None) == "#FFFFFF"


def test_terminal_colors_take_the_background_from_vte(app_module, monkeypatch):
    """VTE knows its background even when GCM configured none -- its default is black."""
    monkeypatch.setattr(app_module.conf, "FONT_COLOR", "")
    terminal = ColourTerminal(FakeRGBA(0.0, 0.0, 0.0, "rgb(0,0,0)"))

    assert app_module.terminal_colors(terminal) == ("#FFFFFF", "rgb(0,0,0)")


def test_terminal_colors_prefer_the_host_font_colour(app_module, monkeypatch):
    monkeypatch.setattr(app_module.conf, "FONT_COLOR", "#111111")
    host = types.SimpleNamespace(font_color="#ABCDEF")
    terminal = ColourTerminal(FakeRGBA(0.0, 0.0, 0.0, "rgb(0,0,0)"), host=host)

    assert app_module.terminal_colors(terminal)[0] == "#ABCDEF"


def test_terminal_colors_fall_back_to_the_global_font_colour(app_module, monkeypatch):
    monkeypatch.setattr(app_module.conf, "FONT_COLOR", "#123456")
    host = types.SimpleNamespace(font_color="")
    terminal = ColourTerminal(FakeRGBA(0.0, 0.0, 0.0, "rgb(0,0,0)"), host=host)

    assert app_module.terminal_colors(terminal)[0] == "#123456"


def test_terminal_colors_default_to_black_when_vte_will_not_say(app_module, monkeypatch):
    """Never leave the view on the theme background: that is what hid light text."""
    monkeypatch.setattr(app_module.conf, "FONT_COLOR", "")
    terminal = ColourTerminal(raises=True)

    assert app_module.terminal_colors(terminal) == ("#FFFFFF", "#000000")
