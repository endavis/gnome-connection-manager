"""What GCM's packages declare, read from the Makefile, and a check of built ones (#273).

The Makefile's `deb` and `rpm` recipes are the one list of what GCM needs and can use:
- `install.sh` reads the .deb's from it.
- `tests/test_packages.py` holds the README's tables, and `tests/test_install.py`'s lists, to it.
- CI builds both packages and holds what fpm wrote into them to it, by running

    python3 tools/packages.py <the .deb> <the .rpm>

An alternative is one word, `freerdp3-x11|freerdp2-x11`, quoted in the recipe, as
`install.sh` reads a recipe a word at a time. Measured with fpm 1.18.0, dpkg 1.22.6 and apt
2.8.3: fpm writes it into the control file as given, and dpkg and apt read it as they
read `freerdp3-x11 | freerdp2-x11`, which is how `dpkg-deb -f` gives it back. The .rpm's
weak dependencies are spec tags, `--rpm-tag 'Recommends: x'`, since fpm has no option of
its own for them.

The Python both packages require is `pyproject.toml`'s `requires-python`, written the same in
both recipes as one quoted word, `-d 'python3 >= 3.12'` while the floor is 3.12 (#564).
`install.sh` reads the first word of it, the package, to ask apt for, and takes the version
from the `requires-python` of the version's own `pyproject.toml` instead, so `unversioned`
gives that word where a name is wanted, as `names` does for apt. `dpkg-deb -f` gives a
relation back in one form whatever spacing it was written with, `python3 (>= 3.12)`, measured
with dpkg 1.22.6, and `as_written` turns that into the recipe's word. A control file holding
the bare `python3 >= 3.12` cannot be read at all: dpkg-deb exits 2. In the .deb fpm builds,
the word reads back through `dpkg-deb -f` as `python3 (>= 3.12)`, the one form `as_written`
turns into the recipe's word, and in the .rpm through `rpm -qp --requires` as
`python3 >= 3.12`. That was measured with fpm 1.18.0 by CI's check, which passed on PR #565.
"""

from __future__ import annotations

import re
import shlex
import subprocess  # nosec B404  # reads built packages with dpkg-deb and rpm
import sys
from pathlib import Path

MAKEFILE = Path(__file__).resolve().parents[1] / "Makefile"

RELATIONS = ("depends", "recommends", "suggests")
# The fpm options that state each relation, for each target.
DEB_OPTIONS = {"-d": "depends", "--deb-recommends": "recommends", "--deb-suggests": "suggests"}
RPM_TAGS = {"Recommends": "recommends", "Suggests": "suggests"}


def variable(makefile: str, name: str) -> str:
    """A variable the Makefile sets, without the quotes its recipes rely on."""
    match = re.search(rf"^{name}=(.*)$", makefile, re.MULTILINE)
    if match is None:
        raise ValueError(f"the Makefile sets no {name}")
    return match.group(1).strip().strip('"')


def recipe(makefile: str, target: str) -> list[str]:
    """The words of `target`'s recipe, as the shell reads them, continuations joined."""
    lines = makefile.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith(f"{target}:")]
    if len(starts) != 1:
        raise ValueError(f"the Makefile has {len(starts)} {target} targets")
    body = []
    for line in lines[starts[0] + 1 :]:
        if not line.startswith("\t"):
            break
        body.append(line.strip())
    return shlex.split(" ".join(line.removesuffix("\\") for line in body))


def declared(makefile: str, target: str) -> dict[str, list[str]]:
    """What `target`'s package depends on, recommends and suggests, in recipe order."""
    relations: dict[str, list[str]] = {relation: [] for relation in RELATIONS}
    words = recipe(makefile, target)
    for option, value in zip(words, words[1:], strict=False):
        if option in ("-d", "--deb-recommends", "--deb-suggests"):
            if target != "deb" and option != "-d":
                raise ValueError(f"{option} in the {target} recipe")
            relations[DEB_OPTIONS[option]].append(value)
        elif option == "--rpm-tag":
            tag, _, package = value.partition(":")
            if tag in RPM_TAGS:
                relations[RPM_TAGS[tag]].append(package.strip())
    return relations


# A package with a version as `dpkg-deb -f` gives it, `python3 (>= 3.12)`.
DPKG_VERSION = re.compile(r"(\S+) \(>= ([^()\s]+)\)")


def as_written(package: str) -> str:
    """A relation as `dpkg-deb -f` gives it, as the recipe writes it: an alternative, `a | b`,
    as `a|b`, and a version, `python3 (>= 3.12)`, as `python3 >= 3.12`. dpkg prints a relation
    in one form whatever spacing it was written with, measured with dpkg 1.22.6, so only that
    form is read. Only `>=` is converted, the one operator a recipe's words allow: a relation
    with another stays as dpkg prints it, matches no word of the recipe, and is reported."""
    written = []
    for part in package.split("|"):
        stripped = part.strip()
        version = DPKG_VERSION.fullmatch(stripped)
        written.append(f"{version[1]} >= {version[2]}" if version else stripped)
    return "|".join(written)


def unversioned(package: str) -> str:
    """The package a recipe word names, its first word, as `install.sh` reads it:
    `python3 >= 3.12` is `python3`, and an alternative, `a|b`, is itself."""
    return package.partition(" ")[0]


def built_deb(path: str) -> dict[str, object]:
    """A built .deb's relations, description and maintainer, as dpkg-deb reads them."""
    fields = {"depends": "Depends", "recommends": "Recommends", "suggests": "Suggests"}
    found: dict[str, object] = {}
    for relation, field in fields.items():
        value = _run(["dpkg-deb", "-f", path, field]).strip()
        found[relation] = [as_written(package) for package in value.split(",") if package]
    found["description"] = _run(["dpkg-deb", "-f", path, "Description"]).strip()
    found["maintainer"] = _run(["dpkg-deb", "-f", path, "Maintainer"]).strip()
    return found


def built_rpm(path: str) -> dict[str, object]:
    """A built .rpm's relations, summary and packager, as rpm reads them. What rpmbuild
    adds of its own to the requires, rpmlib's features and the scripts' shell, is left out."""
    found: dict[str, object] = {}
    for relation, option in (
        ("depends", "--requires"),
        ("recommends", "--recommends"),
        ("suggests", "--suggests"),
    ):
        lines = _run(["rpm", "-qp", option, path]).splitlines()
        found[relation] = [
            line.strip() for line in lines if line.strip() and not line.startswith(("rpmlib(", "/"))
        ]
    found["description"] = _run(["rpm", "-qp", "--qf", "%{SUMMARY}", path]).strip()
    found["maintainer"] = _run(["rpm", "-qp", "--qf", "%{PACKAGER}", path]).strip()
    return found


def _run(command: list[str]) -> str:
    return subprocess.run(command, capture_output=True, text=True, check=True).stdout  # nosec B603


def differences(makefile: str, target: str, found: dict[str, object]) -> list[str]:
    """Where a built package says other than its recipe and the Makefile's variables."""
    wanted: dict[str, object] = dict(declared(makefile, target))
    wanted["description"] = variable(makefile, "PKG_DESCRIPTION")
    wanted["maintainer"] = variable(makefile, "PKG_MAINTAINER")
    problems = []
    for key, value in wanted.items():
        got = found.get(key)
        if target == "rpm" and isinstance(value, list) and isinstance(got, list):
            # rpm lists a package's requires sorted, not in the order given.
            value, got = sorted(value), sorted(got)
        if got != value:
            problems.append(f"{target} {key}: the Makefile says {value!r}, the package {got!r}")
    return problems


def names(makefile: str, target: str) -> list[str]:
    """Every package `target`'s recipe names, each alternative on its own, without versions."""
    relations = declared(makefile, target)
    return [
        name
        for relation in RELATIONS
        for package in relations[relation]
        for name in unversioned(package).split("|")
    ]


def main(argv: list[str]) -> int:
    makefile = MAKEFILE.read_text(encoding="utf-8")
    if len(argv) == 2 and argv[0] == "--names" and argv[1] in ("deb", "rpm"):
        print("\n".join(names(makefile, argv[1])))
        return 0
    if len(argv) != 2 or not argv[0].endswith(".deb") or not argv[1].endswith(".rpm"):
        print("usage: packages.py <package.deb> <package.rpm>", file=sys.stderr)
        print("       packages.py --names deb|rpm", file=sys.stderr)
        return 2
    problems = differences(makefile, "deb", built_deb(argv[0]))
    problems += differences(makefile, "rpm", built_rpm(argv[1]))
    for problem in problems:
        print(problem, file=sys.stderr)
    if not problems:
        print("Both packages declare what the Makefile says.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
