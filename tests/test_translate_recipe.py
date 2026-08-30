"""`doit translate` must compile the catalogs, and must not claim to when it has not (#101).

The original justfile recipe iterated `lang/*/LC_MESSAGES/*.po`, which matches nothing --
the sources are `lang/<lang>_<REGION>.po` and that directory holds the compiled `.mo`
outputs. The loop body never ran, `msgfmt` was never called, and it printed "Translations
compiled" anyway.

The recipe is now a doit task (#115), so these check the function behind it rather than a
justfile. The failure they exist to prevent is unchanged: reporting success over nothing.
"""

from __future__ import annotations

import gettext
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from tools.doit.gcm import _compile_catalogs

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def lang_tree(tmp_path):
    """A copy of lang/ holding the sources but none of the compiled output."""
    tree = tmp_path / "lang"
    shutil.copytree(REPO / "lang", tree)
    for stale in tree.glob("*/LC_MESSAGES/*.mo"):
        stale.unlink()
    return tree


def test_translate_compiles_every_catalog(lang_tree, capsys):
    sources = sorted(p.name for p in lang_tree.glob("*.po"))

    assert _compile_catalogs(lang_tree) is True

    built = sorted(lang_tree.glob("*/LC_MESSAGES/gcm-lang.mo"))
    assert len(built) == len(sources), f"{len(sources)} .po files but {len(built)} catalogs"
    assert f"({len(sources)})" in capsys.readouterr().out


def test_translate_produces_a_catalog_that_really_loads(lang_tree):
    """A file of the right name is not the point; gettext has to be able to read it."""
    _compile_catalogs(lang_tree)

    with (lang_tree / "en/LC_MESSAGES/gcm-lang.mo").open("rb") as handle:
        catalog = gettext.GNUTranslations(handle)

    assert catalog.gettext("Ver buffer") == "View buffer"


def test_translate_fails_rather_than_reporting_success_over_nothing(tmp_path, capsys):
    """The whole of #101: it compiled nothing and said "Translations compiled"."""
    empty = tmp_path / "lang"
    empty.mkdir()

    assert _compile_catalogs(empty) is False

    output = capsys.readouterr().out
    assert "nothing was compiled" in output
    assert "Translations compiled" not in output


def test_doit_reports_the_empty_case_as_a_failure(tmp_path):
    """Returning False is only useful if doit actually fails the task on it.

    Run the real task runner rather than trusting the convention: a task that returns
    False but is reported as passing would put #101 straight back.
    """
    tree = tmp_path / "repo"
    tree.mkdir()
    (tree / "lang").mkdir()
    shutil.copy(REPO / "dodo.py", tree / "dodo.py")
    shutil.copytree(
        REPO / "tools", tree / "tools", ignore=shutil.ignore_patterns("__pycache__")
    )

    result = subprocess.run(
        [sys.executable, "-m", "doit", "translate"],
        cwd=tree,
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert result.returncode != 0, "reported success with no catalogs to compile"
    assert "nothing was compiled" in (result.stdout + result.stderr)


def test_the_fallback_compiler_agrees_with_msgfmt(lang_tree, monkeypatch):
    """tools/build_mo.py exists for checkouts without gettext, so it has to match it."""
    if shutil.which("msgfmt") is None:
        pytest.skip("msgfmt is not installed, so there is nothing to compare against")

    _compile_catalogs(lang_tree)
    with_msgfmt = (lang_tree / "fr/LC_MESSAGES/gcm-lang.mo").read_bytes()

    for stale in lang_tree.glob("*/LC_MESSAGES/*.mo"):
        stale.unlink()
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    _compile_catalogs(lang_tree)
    with_fallback = (lang_tree / "fr/LC_MESSAGES/gcm-lang.mo").read_bytes()

    assert with_fallback == with_msgfmt
