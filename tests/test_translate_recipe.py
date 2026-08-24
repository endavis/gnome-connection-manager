"""`just translate` must compile the catalogs, and must not claim to when it has not (#101).

The recipe iterated `lang/*/LC_MESSAGES/*.po`, which matches nothing -- the sources are
`lang/<lang>_<REGION>.po` and that directory holds the compiled `.mo` outputs. The loop
body never ran, `msgfmt` was never called, and it printed "Translations compiled" anyway.
It also wrote `$$po` for the shell variable, which is Makefile escaping: `just` passes
`$` through untouched, so that expanded to the process id.
"""

from __future__ import annotations

import gettext
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
JUSTFILE = REPO / "justfile"

just = shutil.which("just")
needs_just = pytest.mark.skipif(just is None, reason="the `just` runner is not installed")


def recipe(name):
    """The lines of one justfile recipe."""
    lines, collecting = [], False
    for line in JUSTFILE.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{name}:"):
            collecting = True
            continue
        if collecting:
            if line and not line[0].isspace():
                break
            lines.append(line)
    return "\n".join(lines)


def build_tree(tmp_path):
    """A copy holding just enough to run the recipe."""
    shutil.copy(JUSTFILE, tmp_path / "justfile")
    shutil.copytree(REPO / "lang", tmp_path / "lang")
    shutil.copytree(REPO / "tools", tmp_path / "tools", ignore=shutil.ignore_patterns("__pycache__"))
    return tmp_path


def run_translate(tree):
    return subprocess.run(
        [just, "translate"], cwd=tree, capture_output=True, text=True, timeout=120
    )


def test_the_recipe_does_not_use_makefile_dollar_escaping():
    """`just` hands `$` to the shell as it stands, so `$$po` is the process id."""
    assert "$$" not in recipe("translate")


@needs_just
def test_translate_compiles_every_catalog(tmp_path):
    tree = build_tree(tmp_path)
    sources = sorted(p.name for p in (tree / "lang").glob("*.po"))
    for stale in (tree / "lang").glob("*/LC_MESSAGES/*.mo"):
        stale.unlink()

    result = run_translate(tree)

    assert result.returncode == 0, result.stderr[-2000:]
    built = sorted(p for p in (tree / "lang").glob("*/LC_MESSAGES/gcm-lang.mo"))
    assert len(built) == len(sources), f"{len(sources)} .po files but {len(built)} catalogs"
    assert f"({len(sources)})" in result.stdout, result.stdout


@needs_just
def test_translate_produces_a_catalog_that_really_loads(tmp_path):
    """A file of the right name is not the point; gettext has to be able to read it."""
    tree = build_tree(tmp_path)
    for stale in (tree / "lang").glob("*/LC_MESSAGES/*.mo"):
        stale.unlink()

    run_translate(tree)

    catalog = gettext.GNUTranslations((tree / "lang/en/LC_MESSAGES/gcm-lang.mo").open("rb"))
    assert catalog.gettext("Ver buffer") == "View buffer"


@needs_just
def test_translate_fails_rather_than_reporting_success_over_nothing(tmp_path):
    """The whole of #101: it compiled nothing and said "Translations compiled"."""
    tree = build_tree(tmp_path)
    for source in (tree / "lang").glob("*.po"):
        source.unlink()

    result = run_translate(tree)

    assert result.returncode != 0, "reported success with no catalogs to compile"
    assert "nothing was compiled" in (result.stdout + result.stderr)
