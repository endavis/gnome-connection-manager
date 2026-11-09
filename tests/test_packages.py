"""What GCM's packages declare, held to one list: the Makefile's recipes (#273).

`tools/packages.py` reads them. These hold the README's tables, `tests/test_install.py`'s
lists and the desktop entry to them. In CI, a job builds both packages and holds what fpm
wrote into them to the same reading, which needs fpm and rpmbuild, so it is not a test.

One test holds the `install` recipe, which both package recipes run first, to the image
files the glade file names (#545).

One holds both recipes' Python to `pyproject.toml`'s `requires-python` (#564). The tests of
`built_deb` give it `dpkg-deb -f`'s output written out, so they need no dpkg-deb, and nor
do they depend on the real recipe: the next raise of the floor does not break them.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from tests import test_install
from tools.packages import built_deb, declared, differences, names, recipe, unversioned, variable

REPO = Path(__file__).resolve().parents[1]
MAKEFILE = (REPO / "Makefile").read_text(encoding="utf-8")
README = (REPO / "README.md").read_text(encoding="utf-8")

# A word of a recipe as install.sh can read it: a package, alternatives, `a|b`, or a package
# and the version it needs, `python3 >= 3.12`. install.sh keeps the first word of it.
NAME = r"[a-z0-9][a-z0-9.+-]*"
WORD = rf"{NAME}(?:\|{NAME})*|{NAME} >= [0-9]+(?:\.[0-9]+)*"

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
    `'a`. Alternatives are `'a|b'`, and the rpm's tags are what fpm takes as they are. A
    required version is one word too, `'python3 >= 3.12'`, which install.sh reads as its first
    word, the package. So a version goes on a package alone: inside an alternative it would
    drop the alternatives after it, as install.sh keeps only the first word (#564)."""
    for target in ("deb", "rpm"):
        for relation, named in declared(MAKEFILE, target).items():
            assert named, f"the {target} recipe {relation} nothing"
            for package in named:
                assert re.fullmatch(WORD, package), f"{target} {relation}: {package!r}"


@pytest.mark.parametrize(
    ("word", "readable"),
    [
        ("python3", True),
        ("freerdp3-x11|freerdp2-x11", True),
        ("python3 >= 3.12", True),
        ("a >= 1|b", False),
        ("python3>=3.12", False),
        ("python3 > 3.12", False),
        ("python3 (>= 3.12)", False),
        ("a | b", False),
        ("'python3", False),
    ],
)
def test_a_version_is_allowed_on_a_package_alone(word: str, readable: bool) -> None:
    """The rule above on words written out: `>=` and a number after a package, and no version
    in an alternative or in dpkg's form, which a recipe does not use (#564)."""
    assert bool(re.fullmatch(WORD, word)) is readable


def test_the_readme_names_what_the_deb_depends_on() -> None:
    rows = table("Runtime dependencies")

    assert sorted(packages(row[0])[0] for row in rows) == sorted(
        unversioned(package) for package in declared(MAKEFILE, "deb")["depends"]
    )


def test_the_readme_names_what_the_rpm_requires() -> None:
    rows = table("Runtime dependencies")

    assert sorted({packages(row[1])[0] for row in rows}) == sorted(
        unversioned(package) for package in declared(MAKEFILE, "rpm")["depends"]
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
    alternative, which is what install.sh installs. A version is no part of it: of
    `'python3 >= 3.12'`, install.sh reads only the package, its first word (#564)."""
    deb = {
        relation: [unversioned(package) for package in named]
        for relation, named in declared(MAKEFILE, "deb").items()
    }
    suggests = [package.split("|") for package in deb["suggests"]]

    assert [*deb["depends"], *deb["recommends"], "git"] == test_install.PACKAGES
    assert [package[0] for package in suggests] == test_install.OPTIONAL
    assert [name for package in suggests for name in package[1:]] == test_install.ALTERNATIVES


def test_the_packages_require_the_python_pyproject_requires() -> None:
    """`requires-python` is GCM's floor, and both recipes declare it in one form, as one
    quoted word: `-d 'python3 >= 3.12'` while the floor is 3.12. Both declared `python3` with
    no version before, which Ubuntu 22.04's Python 3.10 satisfies (#564). A raise of the floor
    that misses the Makefile fails here, and the message names what to write."""
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    required = pyproject["project"]["requires-python"]
    floor = re.fullmatch(r">=\s*(\d+\.\d+)", required)
    assert floor, f"requires-python is {required!r}, not a floor this test can read"
    wanted = f"python3 >= {floor.group(1)}"

    for target in ("deb", "rpm"):
        depends = declared(MAKEFILE, target)["depends"]
        assert wanted in depends, (
            f"pyproject.toml requires Python {floor.group(1)}+, and the {target} recipe "
            f"depends on {depends}: write -d '{wanted}' in both recipes"
        )


# A recipe and the control fields of the .deb it builds, as `dpkg-deb -f` prints them, written
# out in full. dpkg prints a relation in one form whatever spacing the control file had, so a
# version is `python3 (>= 3.12)` and an alternative `a | b` (measured with dpkg 1.22.6).
DEB_RECIPE = """\
PKG_DESCRIPTION="A description"
PKG_MAINTAINER="A Maintainer <maintainer@example.org>"

deb: install
\tfpm -t deb \\
\t\t-d 'python3 >= 3.12' \\
\t\t-d python3-gi \\
\t\t--deb-recommends c \\
\t\t--deb-suggests 'a|b' \\
\t\tusr
"""
DPKG_DEB_FIELDS = {
    "Depends": "python3 (>= 3.12), python3-gi",
    "Recommends": "c",
    "Suggests": "a | b",
    "Description": "A description",
    "Maintainer": "A Maintainer <maintainer@example.org>",
}


def read_deb(monkeypatch: pytest.MonkeyPatch, depends: str) -> dict[str, object]:
    """`built_deb` of a .deb whose Depends field `dpkg-deb -f` prints as `depends`, and whose
    other fields are DPKG_DEB_FIELDS's. Nothing runs dpkg-deb."""
    printed = {**DPKG_DEB_FIELDS, "Depends": depends}

    def dpkg_deb(command: list[str]) -> str:
        assert command[:2] == ["dpkg-deb", "-f"], command
        return printed[command[3]] + "\n"

    monkeypatch.setattr("tools.packages._run", dpkg_deb)
    return built_deb("gnome-connection-manager.deb")


def test_a_deb_that_declares_what_the_recipe_says_differs_in_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The version dpkg-deb prints as `python3 (>= 3.12)` is the recipe's `python3 >= 3.12`,
    and the alternative it prints as `a | b` is the recipe's `a|b`."""
    found = read_deb(monkeypatch, DPKG_DEB_FIELDS["Depends"])

    assert found["depends"] == ["python3 >= 3.12", "python3-gi"]
    assert found["suggests"] == ["a|b"]
    assert differences(DEB_RECIPE, "deb", found) == []


@pytest.mark.parametrize(
    "depends",
    [
        pytest.param("python3, python3-gi", id="no version"),
        pytest.param("python3 (>> 3.12), python3-gi", id="another operator"),
    ],
)
def test_a_deb_that_does_not_declare_the_recipes_python_is_reported(
    monkeypatch: pytest.MonkeyPatch, depends: str
) -> None:
    """The check CI makes of a built .deb must fail where fpm wrote no floor, and where it
    wrote another relation: converting any operator to `>=` would hide the second."""
    problems = differences(DEB_RECIPE, "deb", read_deb(monkeypatch, depends))

    assert len(problems) == 1
    assert problems[0].startswith("deb depends: ")


@pytest.mark.parametrize(
    ("word", "package"),
    [("python3 >= 3.12", "python3"), ("python3", "python3"), ("a|b", "a|b")],
)
def test_unversioned_gives_the_first_word_of_a_recipes_word(word: str, package: str) -> None:
    assert unversioned(word) == package


def test_names_gives_apt_the_package_and_not_its_version() -> None:
    """CI asks apt for each name `--names deb` lists, so a name holding a space, as
    `python3 >= 3.12` does, would be asked for as more than one (#564)."""
    named = names(MAKEFILE, "deb")

    assert "python3" in named
    assert [name for name in named if " " in name] == []


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


def test_every_image_the_glade_names_is_installed_beside_it() -> None:
    """GtkBuilder looks for an image in the glade file's own folder, `ui/`. Both package
    recipes run `install` first, and it left out `icon.png`, so the About dialog's logo and
    the main window's icon were a 16x16 stand-in (#545)."""
    ui = REPO / "data" / "ui"
    glade = (ui / "gnome-connection-manager.glade").read_text(encoding="utf-8")
    image = r'<property name="[^"]+"[^>]*>([^<>]+\.(?:png|gif|svg|jpe?g|xpm|ico))</property>'
    names: set[str] = set(re.findall(image, glade))
    install = re.search(r"^install:.*?(?=^[\w.-]+:|\Z)", MAKEFILE, re.MULTILINE | re.DOTALL)

    assert {"icon.png", "donate.gif"} <= names
    assert install, "the Makefile has no install target"
    for name in sorted(names):
        copy = rf"^\tcp data/ui/{re.escape(name)} \$\(DATADIR\)/ui/$"
        assert (ui / name).is_file(), f"the glade file names {name}, and data/ui lacks it"
        assert re.search(copy, install.group(), re.MULTILINE), f"install does not copy {name}"
