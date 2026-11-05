"""A search leaves a console's links alone, and makes no word a link (#498)."""

import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_connections import glib_complaints

URL = "https://example.com/page"


def test_a_search_leaves_a_consoles_links_alone():
    """Measured on a real Vte.Terminal: Wmain.init_search, registerUrlRegexes' links."""
    pytest.importorskip("gi", reason="PyGObject not available")
    check = Path(__file__).resolve().parent / "helpers" / "search_links_check.py"
    result = subprocess.run(
        [sys.executable, str(check)],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        timeout=120,
    )

    assert result.returncode == 0, result.stderr[-2500:]
    measured, _, traced = result.stdout.partition("TRACE-BEGIN\n")
    seen = dict(line.split(": ", 1) for line in measured.splitlines() if ": " in line)
    assert seen["link before any search"] == URL
    assert seen["link after a search"] == URL
    assert seen["link after an empty search"] == URL
    # No searched word is a link, so Ctrl+click has nothing to hand to xdg-open.
    for name in (
        "searched word after a search",
        "earlier word after another",
        "current word",
        "word after an empty search",
    ):
        assert seen[name] == "None", name
    # The search itself still finds its word.
    assert seen["search selects"] == "True"
    # VTE warns when a search regex lacks PCRE2_MULTILINE.
    assert "VTE-WARNING" not in result.stderr, result.stderr[-2500:]
    assert glib_complaints(result.stderr) == []

    # The `links` trace (#513): the matchers added, the search set and cleared, the click.
    lines = [line.split("links: ", 1)[1] for line in traced.splitlines()]
    added = [line for line in lines if line.startswith("match added")]
    assert len(added) == 4
    for kind, line in zip(("direct", "url", "email", "file"), added, strict=True):
        assert re.fullmatch(
            rf"match added: {kind}, tag \d+, console \?, by <module> > registerUrlRegexes", line
        ), line
    assert lines[:4] == added
    assert "search regex set, console ?" in lines
    assert "search regex cleared, console ?" in lines
    clicks = [line for line in lines if line.startswith("ctrl+click")]
    assert len(clicks) == 1
    assert re.fullmatch(r"ctrl\+click: tag \d+, handler open_in_browser, console \?", clicks[0])
    assert seen["ctrl+click opens"] == "['https://example.com/page']"
    # Neither the search's text nor the console's text, nor the URL, is in the trace.
    for secret in ("SEARCHMARKQZX", "TEXTMARKQZX", "example.com", "banana"):
        assert secret not in traced, secret
