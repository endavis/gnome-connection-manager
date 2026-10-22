"""What GCM's packages declare, held to one list: the Makefile's recipes (#273).

`tools/packages.py` reads them. These hold the README's tables, `tests/test_install.py`'s
lists and the desktop entry to them. In CI, a job builds both packages and holds what fpm
wrote into them to the same reading, which needs fpm and rpmbuild, so it is not a test.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tomllib
from pathlib import Path

from tools.packages import declared, recipe, variable

from tests import test_install

REPO = Path(__file__).resolve().parents[1]
MAKEFILE = (REPO / "Makefile").read_text(encoding="utf-8")
README = (REPO / "README.md").read_text(encoding="utf-8")

# The README's one row that names programs neither package declares, as decided in #302
# and again in #273: GCM runs a VNC viewer only where gtk-vnc, which both install, is
# missing.
UNDECLARED = {"`tigervnc-viewer` or `xtightvncviewer`"}


def table(heading: str) -> list[list[str]]:
    """The cells of each row of the first table under `heading` in the README."""
    section = README.split(f"\n### {heading}\n", 1)[1].splitlines()
    start = next(i for i, line in enumerate(section) if line.startswith("|"))
    rows = []
    for line in section[start:]:
        if not line.startswith("|"):
            break
        rows.append(line)
    return [[cell.strip() for cell in row.strip("|").split("|")] for row in rows[2:]]


def packages(cell: str) -> list[str]:
    """The packages a README cell names, `a` or `b` as the recipe writes it, `a|b`."""
    named = []
    for part in re.split(r", or another .*$| and ", cell):
        names = re.findall(r"`([^`]+)`", part)
        if names:
            named.append("|".join(names))
    return named


def test_every_package_is_one_word_install_sh_can_read() -> None:
    """install.sh reads the .deb's recipe a word at a time, so `'a | b'` would reach apt as
    `'a`. Alternatives are `'a|b'`, and the rpm's tags are what fpm takes as they are."""
    for target in ("deb", "rpm"):
        for relation, named in declared(MAKEFILE, target).items():
            assert named, f"the {target} recipe {relation} nothing"
            for package in named:
                assert re.fullmatch(r"[a-z0-9][a-z0-9.+-]*(\|[a-z0-9][a-z0-9.+-]*)*", package), (
                    f"{target} {relation}: {package!r}"
                )


def test_the_readme_names_what_the_deb_depends_on() -> None:
    rows = table("Runtime dependencies")

    assert sorted(packages(row[0])[0] for row in rows) == sorted(
        declared(MAKEFILE, "deb")["depends"]
    )


def test_the_readme_names_what_the_rpm_requires() -> None:
    rows = table("Runtime dependencies")

    assert sorted({packages(row[1])[0] for row in rows}) == sorted(
        declared(MAKEFILE, "rpm")["depends"]
    )


def test_the_readme_names_the_optional_programs_the_deb_declares() -> None:
    deb = declared(MAKEFILE, "deb")
    rows = [row for row in table("Optional programs") if row[0] not in UNDECLARED]

    assert sorted(name for row in rows for name in packages(row[0])) == sorted(
        deb["recommends"] + deb["suggests"]
    )


def test_the_readme_names_the_optional_programs_the_rpm_declares() -> None:
    rpm = declared(MAKEFILE, "rpm")
    rows = [row for row in table("Optional programs") if row[0] not in UNDECLARED]

    assert sorted(name for row in rows for name in packages(row[1])) == sorted(
        rpm["recommends"] + rpm["suggests"]
    )


def test_the_readme_says_which_optional_programs_are_installed_without_asking() -> None:
    """Only what the .deb recommends, which apt installs as it does what GCM needs."""
    assert declared(MAKEFILE, "deb")["recommends"] == ["gir1.2-gtk-vnc-2.0"]
    assert "Only `gir1.2-gtk-vnc-2.0` is installed with GCM without asking" in README
    assert declared(MAKEFILE, "rpm")["recommends"] == ["gtk-vnc2"]
    assert "The\n`.rpm` recommends `gtk-vnc2` and suggests the rest" in README


def test_the_install_tests_expect_what_the_deb_declares() -> None:
    """tests/test_install.py checks install.sh against lists of its own, which must be the
    recipe's: what it depends on and recommends, and git, and each suggestion's first
    alternative, which is what install.sh installs."""
    deb = declared(MAKEFILE, "deb")
    suggests = [package.split("|") for package in deb["suggests"]]

    assert [*deb["depends"], *deb["recommends"], "git"] == test_install.PACKAGES
    assert [package[0] for package in suggests] == test_install.OPTIONAL
    assert [name for package in suggests for name in package[1:]] == test_install.ALTERNATIVES


def test_the_description_fits_a_synopsis() -> None:
    """The .deb's Description and the .rpm's Summary, which Debian keeps under 80
    characters, without a full stop at the end. The Python package's, which the .deb
    installs with GCM, is the same."""
    description = variable(MAKEFILE, "PKG_DESCRIPTION")
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))

    assert len(description) < 80
    assert not description.endswith(".")
    assert pyproject["project"]["description"] == description


def test_the_desktop_entry_has_no_deprecated_keys() -> None:
    """desktop-file-validate warned that `Encoding` is deprecated. CI's package job runs it
    on the entry, and fails on anything it reports."""
    entry = (REPO / "gnome-connection-manager.desktop").read_text(encoding="utf-8")

    assert not re.search(r"^Encoding=", entry, re.MULTILINE)
    if shutil.which("desktop-file-validate"):
        checked = subprocess.run(
            ["desktop-file-validate", str(REPO / "gnome-connection-manager.desktop")],
            capture_output=True,
            text=True,
            check=False,
        )
        assert (checked.returncode, checked.stdout + checked.stderr) == (0, "")


def test_no_package_runs_a_script() -> None:
    """The postinst ran xdg-desktop-menu, which the packages only suggest, and left the
    .deb half-configured without it, and without /usr/share/desktop-directories. dpkg's
    and rpm's desktop-file-utils triggers update the desktop database (#273)."""
    for target in ("deb", "rpm"):
        words = recipe(MAKEFILE, target)
        scripts = [word for word in words if word.startswith(("--after-", "--before-"))]
        assert scripts == [], f"the {target} recipe runs {scripts}"
    assert not (REPO / "postinst").exists()
