"""Turn VTE's HTML export of a terminal grid into styled runs.

`Vte.Terminal.get_text_range_format(Vte.Format.HTML, ...)` returns the same rows the
plain-text call returns, with attributes attached. The vocabulary is small and already
resolved -- 256-colour and truecolour both arrive as hex, and dim and reverse are
flattened to concrete colours -- so nothing here needs a palette.

Measured on VTE 0.76, the whole vocabulary is:

    pre  font[color]  span[style=background-color]  b  i  u  strike  blink

Content is escaped as &amp; &lt; &gt; &quot;, which HTMLParser undoes for us. Unicode
is passed through raw.
"""

from __future__ import annotations

from html.parser import HTMLParser

# Attributes a Gtk.TextTag can express. `blink` is deliberately absent: there is no
# TextTag for it and a blinking log is not worth emulating.
FOREGROUND = "foreground"
BACKGROUND = "background"
BOLD = "bold"
ITALIC = "italic"
UNDERLINE = "underline"
STRIKETHROUGH = "strikethrough"

_FLAG_TAGS = {"b": BOLD, "i": ITALIC, "u": UNDERLINE, "strike": STRIKETHROUGH}


class _Collector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.runs: list[tuple[str, dict]] = []
        self._stack: list[dict] = []

    def _style(self):
        merged = {}
        for frame in self._stack:
            merged.update(frame)
        return merged

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        frame = {}
        if tag == "font" and attributes.get("color"):
            frame[FOREGROUND] = attributes["color"]
        elif tag == "span":
            background = _style_property(attributes.get("style", ""), "background-color")
            if background:
                frame[BACKGROUND] = background
        elif tag in _FLAG_TAGS:
            frame[_FLAG_TAGS[tag]] = True
        # `pre` carries nothing, and an unknown tag contributes nothing rather than
        # being dropped: its text still has to reach the output.
        self._stack.append(frame)

    def handle_endtag(self, tag):
        if self._stack:
            self._stack.pop()

    def handle_data(self, data):
        if data:
            self.runs.append((data, self._style()))


def _style_property(style, name):
    for declaration in style.split(";"):
        key, separator, value = declaration.partition(":")
        if separator and key.strip() == name:
            return value.strip()
    return None


def parse_vte_html(html):
    """Return `[(text, attributes), ...]` covering every character of the export.

    Adjacent runs sharing a style are merged, because a buffer of a few hundred lines
    otherwise produces thousands of one-character runs to tag individually.
    """
    if not html:
        return []
    collector = _Collector()
    collector.feed(html)
    collector.close()

    merged: list[tuple[str, dict]] = []
    for text, style in collector.runs:
        if merged and merged[-1][1] == style:
            merged[-1] = (merged[-1][0] + text, style)
        else:
            merged.append((text, style))
    return merged


def plain_text(runs):
    """The text of every run, which is what Copy and Save should see."""
    return "".join(text for text, _style in runs)
