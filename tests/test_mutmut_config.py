"""Tests for ``[tool.mutmut]`` in ``pyproject.toml`` (#326).

The weekly mutation run never tested a mutant. mutmut copies the code it mutates, the
tests, and whatever ``also_copy`` names into ``mutants/``, then runs the selected tests
there with ``-x`` to learn which tests reach which functions. With no selection it ran all
of ``tests/``, stopped at the first test that imports ``tools``, which ``mutants/`` lacks,
and checked no mutant. The template failed the same way (endavis/pyproject-template#873).

The selection is now an explicit list, and these tests keep it complete and runnable, as
the template's own ``tests/test_mutmut_config.py`` does for the template. That file names
the template's placeholder tests, so GCM keeps this one in its place. GCM's tests also
reach the package through the ``app_module`` fixture, which imports ``app.py`` under the
``gi`` stub, so a test file that takes it is a test of the package too.

mutmut also runs pytest several times in its own process, and forks it for each mutant,
which GTK does not survive, so ``tests/conftest.py`` keeps the real ``gi`` out of that
process. The last tests here run pytest in a process of their own, as mutmut does; the rest
are structural asserts on the parsed TOML and on the test files' source. None runs mutmut.
"""

from __future__ import annotations

import ast
import fnmatch
import os
import shutil
import signal
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
TESTS = REPO_ROOT / "tests"

# Keys mutmut 3 deprecates, mapped to the keys that replace them.
REPLACED = {
    "paths_to_mutate": "source_paths",
    "tests_dir": "pytest_add_cli_args_test_selection",
}
# Keys mutmut 3 does not read at all, so nothing warns about them.
UNREAD = {"runner"}

# The fixture in tests/conftest.py that imports the package for the test taking it.
PACKAGE_FIXTURE = "app_module"

# Tests of the package left out of the selection on purpose.
NOT_SELECTED = {
    "tests/test_docs.py": (
        "it reads the guides under docs/ and AGENTS.md, and checks what they name against "
        "the whole tree, most of which mutmut does not copy into mutants/"
    ),
}


def _mutmut_config() -> dict[str, Any]:
    """Return the ``[tool.mutmut]`` table."""
    with PYPROJECT.open("rb") as f:
        config: dict[str, Any] = tomllib.load(f)["tool"]["mutmut"]
    return config


def _selected_paths(config: dict[str, Any]) -> list[Path]:
    """Return the paths in the test selection, dropping options and node ids."""
    return [
        REPO_ROOT / entry.split("::")[0]
        for entry in config["pytest_add_cli_args_test_selection"]
        if not entry.startswith("-")
    ]


def _is_selected(path: Path, selected: list[Path]) -> bool:
    """Return True if *path* is a selected file or lies under a selected directory."""
    return any(path == s or s in path.parents for s in selected)


def _copied_roots(config: dict[str, Any]) -> set[str]:
    """Return the names at the repository root that mutmut copies into ``mutants/``.

    mutmut 3 copies the source paths, ``tests/``, ``test/``, root-level ``test*.py``
    files and whatever ``also_copy`` lists, plus the lock files and project files,
    which nothing imports (``mutmut/configuration.py``).
    """
    entries = [*config["source_paths"], *config.get("also_copy", []), "tests", "test"]
    return {Path(e).parts[0] for e in entries} | {p.stem for p in REPO_ROOT.glob("test*.py")}


def _left_behind(names: set[str], copied: set[str]) -> set[str]:
    """Return the *names* that live at the repository root but are not copied."""
    return {
        name
        for name in names - copied
        if (REPO_ROOT / name).is_dir() or (REPO_ROOT / f"{name}.py").is_file()
    }


def _imported_names(source: str) -> set[str]:
    """Return the top-level names *source* imports absolutely, at any depth."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def _takes_package_fixture(source: str) -> bool:
    """Return True if a function in *source* takes ``app_module`` as an argument."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            arguments = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
            if any(argument.arg == PACKAGE_FIXTURE for argument in arguments):
                return True
    return False


def _package_names(config: dict[str, Any]) -> set[str]:
    """Return the import names of the code mutmut mutates."""
    names: set[str] = set()
    for source in config["source_paths"]:
        root = REPO_ROOT / source
        if (root / "__init__.py").is_file():
            names.add(root.name)
            continue
        names |= {p.name for p in root.iterdir() if (p / "__init__.py").is_file()}
        names |= {p.stem for p in root.glob("*.py")}
    return names


def _modules_pytest_loads(selected: list[Path]) -> list[Path]:
    """Return the selected test modules plus the ``conftest.py`` files above them."""
    modules: set[Path] = set()
    for path in selected:
        modules |= set(path.rglob("*.py")) if path.is_dir() else {path}
        start = path if path.is_dir() else path.parent
        for directory in (start, *start.parents):
            if (directory == TESTS or TESTS in directory.parents) and (
                directory / "conftest.py"
            ).is_file():
                modules.add(directory / "conftest.py")
    return sorted(modules)


def _deselected(config: dict[str, Any]) -> list[str]:
    """Return the node ids ``pytest_add_cli_args`` hands to ``--deselect``."""
    arguments: list[str] = config.get("pytest_add_cli_args", [])
    ids = []
    for index, argument in enumerate(arguments):
        if argument == "--deselect" and index + 1 < len(arguments):
            ids.append(arguments[index + 1])
        elif argument.startswith("--deselect="):
            ids.append(argument.removeprefix("--deselect="))
    return ids


def _defined_names(source: str) -> set[str]:
    """Return the names of the functions *source* defines, at any depth."""
    return {
        node.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def _imports_gi(node: ast.AST) -> bool:
    """Return True if *node* holds an import of ``gi`` or of a module under it."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Import) and any(
            alias.name.split(".")[0] == "gi" for alias in sub.names
        ):
            return True
        if isinstance(sub, ast.ImportFrom) and (sub.module or "").split(".")[0] == "gi":
            return True
    return False


def _skips_without_gi(node: ast.AST) -> bool:
    """Return True if *node* calls ``pytest.importorskip("gi")``."""
    return any(
        isinstance(sub, ast.Call)
        and isinstance(sub.func, ast.Attribute)
        and sub.func.attr == "importorskip"
        and bool(sub.args)
        and isinstance(sub.args[0], ast.Constant)
        and sub.args[0].value == "gi"
        for sub in ast.walk(node)
    )


def _gi_without_importorskip(source: str) -> list[str]:
    """Return what in *source* imports ``gi`` other than behind ``importorskip("gi")``.

    A function is taken whole, with whatever it defines inside it, as the tests that
    draw real windows define their helpers there.
    """
    offenders = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.Import | ast.ImportFrom) and _imports_gi(node):
            offenders.append(f"line {node.lineno}")
        functions = node.body if isinstance(node, ast.ClassDef) else [node]
        for function in functions:
            if (
                isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef)
                and _imports_gi(function)
                and not _skips_without_gi(function)
            ):
                offenders.append(function.name)
    return offenders


def _source_files(config: dict[str, Any]) -> list[str]:
    """Return the Python files mutmut walks, as the paths it matches patterns against."""
    return [
        path.relative_to(REPO_ROOT).as_posix()
        for source in config["source_paths"]
        for path in sorted((REPO_ROOT / source).rglob("*.py"))
    ]


def test_no_deprecated_or_unread_keys() -> None:
    stale = sorted(set(_mutmut_config()) & (set(REPLACED) | UNREAD))

    assert not stale, f"mutmut 3 deprecates or ignores {stale}"


def test_uses_the_replacement_keys() -> None:
    """Without them mutmut guesses what to mutate and which tests to run."""
    missing = sorted(set(REPLACED.values()) - set(_mutmut_config()))

    assert not missing


def test_every_selected_path_exists() -> None:
    """pytest stops on a path it cannot find, and mutmut then checks no mutant."""
    missing = [
        p.relative_to(REPO_ROOT).as_posix()
        for p in _selected_paths(_mutmut_config())
        if not p.exists()
    ]

    assert not missing, f"pytest_add_cli_args_test_selection names missing paths: {missing}"


def test_selected_tests_import_nothing_mutmut_leaves_behind() -> None:
    """A selected test, or a conftest it loads, must import only what ``mutants/`` holds."""
    config = _mutmut_config()
    copied = _copied_roots(config)
    offenders = {
        path.relative_to(REPO_ROOT).as_posix(): sorted(left)
        for path in _modules_pytest_loads(_selected_paths(config))
        if (left := _left_behind(_imported_names(path.read_text(encoding="utf-8")), copied))
    }

    assert not offenders, (
        "these selected tests import modules that mutmut does not copy into mutants/, "
        f"so its stats run stops before any mutant is checked (#326): {offenders}"
    )


def test_every_test_of_the_package_is_selected() -> None:
    """A test of the package that is not selected never runs against a mutant.

    A test of the package imports it or takes ``app_module``. One that also imports
    something ``mutants/`` lacks cannot be selected, so it is not required here; the
    previous test would reject it.
    """
    config = _mutmut_config()
    packages = _package_names(config)
    copied = _copied_roots(config)
    selected = _selected_paths(config)
    unselected = []
    for path in sorted(TESTS.rglob("test_*.py")):
        rel = path.relative_to(REPO_ROOT)
        if any(rel.is_relative_to(skipped) for skipped in NOT_SELECTED):
            continue
        source = path.read_text(encoding="utf-8")
        names = _imported_names(source)
        if (
            (names & packages or _takes_package_fixture(source))
            and not _left_behind(names, copied)
            and not _is_selected(path, selected)
        ):
            unselected.append(rel.as_posix())

    assert not unselected, (
        f"these tests import {sorted(packages)} or take {PACKAGE_FIXTURE}, but mutmut never "
        f"runs them: {unselected}. Add them to pytest_add_cli_args_test_selection in "
        "pyproject.toml, or to NOT_SELECTED here with the reason."
    )


def test_every_test_left_out_exists() -> None:
    """An excuse for a test that has gone would let a new test of that name go unselected."""
    missing = [path for path in NOT_SELECTED if not (REPO_ROOT / path).exists()]

    assert not missing, f"NOT_SELECTED names missing paths: {missing}"


def test_every_deselected_test_exists_in_the_selection() -> None:
    """pytest ignores a ``--deselect`` that matches nothing, so a renamed test would run.

    Each one is a test that reads what mutmut rewrites rather than what it does, and fails
    against ``mutants/`` with every mutant inactive, which stops the stats run.
    """
    config = _mutmut_config()
    selected = _selected_paths(config)
    stale = []
    for node_id in _deselected(config):
        file, _, test = node_id.partition("::")
        path = REPO_ROOT / file
        name = test.split("::")[-1].split("[")[0]
        if not (
            path.is_file()
            and _is_selected(path, selected)
            and name in _defined_names(path.read_text(encoding="utf-8"))
        ):
            stale.append(node_id)

    assert not stale, f"--deselect names no selected test: {stale}"


def test_every_file_left_unmutated_exists() -> None:
    """A pattern that matches no file would let the file it meant be mutated, renamed."""
    config = _mutmut_config()
    files = _source_files(config)
    unmatched = [
        pattern for pattern in config.get("do_not_mutate", []) if not fnmatch.filter(files, pattern)
    ]

    assert not unmatched, f"do_not_mutate patterns match no source file: {unmatched}"


def test_selected_tests_ask_for_the_real_gi_through_importorskip() -> None:
    """mutmut's process has no real ``gi``, and such a test must skip there, not fail.

    A bare ``import gi`` fails, and the stats run stops before any mutant is checked.
    """
    offenders = {
        path.relative_to(REPO_ROOT).as_posix(): found
        for path in _selected_paths(_mutmut_config())
        if path.is_file() and (found := _gi_without_importorskip(path.read_text("utf-8")))
    }

    assert not offenders, (
        "these selected tests import gi without pytest.importorskip('gi'), so they fail "
        f"in mutmut's process, where tests/conftest.py keeps the real gi out: {offenders}"
    )


def test_the_import_scanner_sees_every_absolute_import() -> None:
    """Imports inside functions count; relative imports stay inside ``tests/``."""
    source = (
        "import os.path\n"
        "from tools.doit import github\n"
        "from . import sibling\n"
        "def test_x():\n"
        "    import package_name.core\n"
    )

    assert _imported_names(source) == {"os", "tools", "package_name"}


def test_the_fixture_scanner_sees_app_module_taken_and_nothing_else() -> None:
    """A test or a fixture taking it counts; a mention of its name does not."""
    taken = [
        "def test_x(app_module):\n    pass\n",
        "def test_x(tmp_path, *, app_module):\n    pass\n",
        "class TestX:\n    def test_x(self, app_module):\n        pass\n",
        "import pytest\n@pytest.fixture\ndef wmain(app_module):\n    return app_module.Wmain\n",
    ]
    mentioned = [
        "def test_x(tmp_path):\n    '''Unlike app_module, this reads no GTK.'''\n",
        "# app_module is not needed here\ndef test_x():\n    pass\n",
        "def test_x(application_module):\n    pass\n",
    ]

    assert all(_takes_package_fixture(source) for source in taken)
    assert not any(_takes_package_fixture(source) for source in mentioned)


def test_the_deselect_parser_reads_both_spellings() -> None:
    config = {
        "pytest_add_cli_args": [
            "-k",
            "not slow",
            "--deselect",
            "tests/test_a.py::test_one",
            "--deselect=tests/test_b.py::TestB::test_two[x]",
        ]
    }

    assert _deselected(config) == [
        "tests/test_a.py::test_one",
        "tests/test_b.py::TestB::test_two[x]",
    ]


def test_the_gi_scanner_wants_importorskip_wherever_gi_is_imported() -> None:
    source = (
        "import pytest\n"
        "def test_skips():\n"
        "    gi = pytest.importorskip('gi', reason='PyGObject not available')\n"
        "    from gi.repository import Gtk\n"
        "    def settle():\n"
        "        from gi.repository import GLib\n"
        "def test_bare():\n"
        "    import gi\n"
        "class TestVte:\n"
        "    def test_from(self):\n"
        "        from gi.repository import Vte\n"
        "def test_in_a_script():\n"
        "    script = 'import gi'\n"
    )

    assert _gi_without_importorskip(source) == ["test_bare", "test_from"]
    assert _gi_without_importorskip("from gi.repository import Gtk\n") == ["line 1"]


def test_tools_is_left_behind_and_the_tests_are_not() -> None:
    """The import that stopped every weekly run (#326) is the one this check catches."""
    copied = _copied_roots(_mutmut_config())

    assert _left_behind({"tools", "tests", "os"}, copied) == {"tools"}


# A test that draws a real window, as the in-process real-GTK tests do.
DRAWS_A_WINDOW = """
import pytest


def test_draws_a_window():
    gi = pytest.importorskip("gi", reason="PyGObject not available")
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    window = Gtk.Window()
    window.show_all()
    while Gtk.events_pending():
        Gtk.main_iteration()
    window.destroy()
"""

# pytest run in one process as mutmut runs it: MUTANT_UNDER_TEST set, as mutmut sets it
# for each run, and mutmut imported, as it is in its own process. The run reads no
# pyproject.toml, so it blocks the system's platformdirs plugin itself, as GCM's addopts
# do: on CI it stopped the run before collection (#252).
RUNS_PYTEST = """
import os
import sys

import pytest

if sys.argv[1] == "mutmut":
    import mutmut  # noqa: F401
os.environ["MUTANT_UNDER_TEST"] = ""
arguments = ["-q", "-rs", "-p", "no:cacheprovider", "-p", "no:platformdirs", "test_draws.py"]
codes = [int(pytest.main(arguments)) for _ in range(int(sys.argv[2]))]
print("exit codes", codes)
"""


def _run_pytest_as(
    process: str,
    runs: int,
    tmp_path: Path,
    test: str = DRAWS_A_WINDOW,
    changes: dict[str, str | None] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run *test* under GCM's conftest, *runs* times in one process.

    *changes* sets variables of that process's environment, or removes those given None.
    """
    if shutil.which("Xvfb") is None:
        pytest.skip("needs Xvfb, which tests/conftest.py starts for each run")
    pytest.importorskip("gi", reason="PyGObject not available")
    shutil.copy(TESTS / "conftest.py", tmp_path / "conftest.py")
    (tmp_path / "test_draws.py").write_text(test)
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("PYTEST_")
        and key not in {"GCM_TEST_REAL_DISPLAY", "MUTANT_UNDER_TEST"}
    }
    for key, value in (changes or {}).items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return subprocess.run(
        [sys.executable, "-c", RUNS_PYTEST, process, str(runs)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_mutmuts_process_survives_a_second_run_of_a_test_that_draws(tmp_path: Path) -> None:
    """GTK kept the first run's display, which that run's end took away (#326).

    Measured without the guard in tests/conftest.py, the second run exited 1 and printed
    nothing, which is how mutmut's clean run ended after its stats run.
    """
    result = _run_pytest_as("mutmut", 2, tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "exit codes [0, 0]" in result.stdout
    assert result.stdout.count("1 skipped") == 2, result.stdout


def test_a_pytest_a_test_starts_keeps_the_real_gi(tmp_path: Path) -> None:
    """It inherits MUTANT_UNDER_TEST but makes one run, as tests/test_main.py's does."""
    result = _run_pytest_as("child", 1, tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "exit codes [0]" in result.stdout
    assert "1 passed" in result.stdout, result.stdout


# A test that records the display its run was given, then dies as mutmut ends a mutant
# that runs too long: SIGXCPU, whose default action takes no cleanup. No core file.
DIES_AT_ITS_TIMEOUT = """
import os
import resource
import signal
from pathlib import Path


def test_dies_at_its_timeout():
    Path("display.txt").write_text(
        os.environ.get("DISPLAY", "") + "\\n" + os.environ.get("WAYLAND_DISPLAY", "")
    )
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.kill(os.getpid(), signal.SIGXCPU)
"""


def _xvfb_serving(display: str) -> int | None:
    """Return the pid of the Xvfb serving X *display*, such as ``:90``, if one is running."""
    number = display.rpartition(":")[2].partition(".")[0]
    try:
        pid = int(Path(f"/tmp/.X{number}-lock").read_text().strip())
        comm = Path(f"/proc/{pid}/comm").read_text().strip()
    except (OSError, ValueError):
        return None
    return pid if comm == "Xvfb" else None


def test_a_mutant_mutmut_stops_at_its_timeout_leaves_no_xvfb(tmp_path: Path) -> None:
    """mutmut's process gets no display at all, so none outlives a mutant it kills (#341).

    It ends a mutant that runs too long with SIGXCPU, so pytest_unconfigure never stopped
    the Xvfb pytest_configure had started, and each such mutant left one running. Its
    display and the developer's are both named here, and neither may reach the run.
    """
    result = _run_pytest_as(
        "mutmut",
        1,
        tmp_path,
        DIES_AT_ITS_TIMEOUT,
        {"DISPLAY": "unix:4242", "WAYLAND_DISPLAY": "gcm-test-no-such-wayland"},
    )
    display, wayland = (tmp_path / "display.txt").read_text().split("\n")
    leftover = _xvfb_serving(display) if display else None
    if leftover:
        os.kill(leftover, signal.SIGTERM)

    assert result.returncode == -signal.SIGXCPU, result.stdout + result.stderr
    assert leftover is None, f"the run's Xvfb on {display} outlived it"
    assert (display, wayland) == ("", "")


def test_a_pytest_a_test_starts_gets_an_xvfb_of_its_own(tmp_path: Path) -> None:
    """mutmut's process has no display to pass on, so the pytest a test starts makes its own.

    The run here is given no display at all, as one started from mutmut's process is,
    and the window it draws needs one.
    """
    result = _run_pytest_as(
        "child", 1, tmp_path, changes={"DISPLAY": None, "WAYLAND_DISPLAY": None}
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "exit codes [0]" in result.stdout
    assert "1 passed" in result.stdout, result.stdout
