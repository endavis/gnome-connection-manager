"""Tests for parsing VTE's HTML grid export into styled runs."""

from __future__ import annotations

import os
import subprocess
import sys
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
