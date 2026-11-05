"""A search leaves a console's links alone, and makes no word a link (#498)."""

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
    seen = dict(line.split(": ", 1) for line in result.stdout.splitlines() if ": " in line)
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
