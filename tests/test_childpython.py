"""Tests for the command GCM starts its Python children with (#415).

`install.sh`'s launcher makes the package importable in GCM's own process alone. GCM started
the relay and the update check as `python -m gnome_connection_manager.<module>`, which a fresh
`/usr/bin/python3` could not find, so no console opened with OSC 52 or raw recording on, and
the update check failed without a word. The last tests here start GCM's own commands in an
interpreter that finds nothing of GCM by itself, as that one does, and on the `-m` commands
they fail with `ModuleNotFoundError`.
"""

from __future__ import annotations

import inspect
import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

import gnome_connection_manager
from gnome_connection_manager.utils import childpython, updates
from tests.test_updates import start_check

if TYPE_CHECKING:
    from types import ModuleType

# The folder holding the package this test imports, which the command names.
ROOT = Path(inspect.getfile(gnome_connection_manager)).parents[1]

# A module of a package of the test's own, which reports what it finds and exits as told.
MODULE = """\
import json
import sys

from . import sibling

print(
    json.dumps(
        {
            "name": __name__,
            "package": __package__,
            "argv": sys.argv,
            "path": sys.path,
            "sibling": sibling.NAME,
        }
    )
)
sys.exit(int(sys.argv[1]))
"""


@pytest.fixture
def holder(tmp_path: Path) -> Path:
    """The folder holding `pkg`, a package of the test's own with a module `mod`."""
    package = tmp_path / "holder" / "pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "sibling.py").write_text("NAME = 'sibling'\n")
    (package / "mod.py").write_text(MODULE)
    return package.parent


def python_path(*flags: str, env: dict[str, str] | None = None) -> list[str]:
    """`sys.path` of an interpreter run with `flags`, as it starts."""
    shown = subprocess.run(
        [sys.executable, *flags, "-c", "import json, sys; print(json.dumps(sys.path))"],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        check=True,
    )
    path: list[str] = json.loads(shown.stdout)
    return path


def run_bootstrap(
    holder: Path,
    *arguments: str,
    flags: tuple[str, ...] = ("-I", "-S"),
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """The bootstrap as `module_command` hands it over, on `pkg.mod` in the folder
    `holder`, in an interpreter run with `flags`."""
    return subprocess.run(
        [sys.executable, *flags, "-c", childpython.BOOTSTRAP, str(holder), "pkg.mod", *arguments],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        check=False,
    )


def test_the_command_runs_the_bootstrap_on_the_folder_holding_the_package() -> None:
    assert childpython.module_command("gnome_connection_manager.relay") == [
        sys.executable,
        "-c",
        childpython.BOOTSTRAP,
        str(ROOT),
        "gnome_connection_manager.relay",
    ]
    assert (ROOT / "gnome_connection_manager" / "__init__.py").is_file()


def test_the_folder_is_the_one_the_package_was_imported_from_and_not_its_target(
    tmp_path: Path,
) -> None:
    """The child looks for it among its own `sys.path` entries as text, so a link followed
    here would name a folder that the entry the package came from does not."""
    link = tmp_path / "link"
    link.symlink_to(ROOT)
    program = (
        "import sys\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from gnome_connection_manager.utils import childpython\n"
        "print(childpython.package_root())\n"
    )

    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", program, str(link)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.stdout.strip() == str(link), result.stderr


def test_the_bootstrap_runs_the_module_as_main_with_its_file_and_arguments(holder: Path) -> None:
    result = run_bootstrap(holder, "7", "--two", "with space")

    assert result.returncode == 7, result.stderr  # its exit status is the child's
    seen = json.loads(result.stdout)
    assert seen["name"] == "__main__"
    assert seen["package"] == "pkg"
    assert seen["sibling"] == "sibling"  # a relative import works: it ran in its package
    assert seen["argv"] == [str(holder / "pkg" / "mod.py"), "7", "--two", "with space"]


def test_the_bootstrap_puts_the_folder_first_on_a_path_that_lacks_it(holder: Path) -> None:
    bare = python_path("-I", "-S")

    result = run_bootstrap(holder, "0")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["path"] == [str(holder), *bare]


def test_the_bootstrap_leaves_the_path_alone_where_the_folder_is_on_it_already(
    holder: Path,
) -> None:
    """A checkout's `.venv` and the `.deb` find the package themselves, and keep the order
    they import in: the folder is neither added again nor moved."""
    env = {**os.environ, "PYTHONPATH": str(holder)}
    before = python_path("-S", env=env)

    result = run_bootstrap(holder, "0", flags=("-S",), env=env)

    assert before.count(str(holder)) == 1
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["path"] == before


# -- GCM's own commands, from an interpreter that cannot find GCM itself ------------------


def without_site(command: list[str]) -> list[str]:
    """`command` with `-I -S` after its interpreter, so that the interpreter finds GCM only
    where the command says: as `/usr/bin/python3` does under `install.sh`'s launcher, where
    the package is importable in GCM's own process alone. `-I` leaves out the environment,
    the user's site and the working directory, and `-S` the `site-packages` of the `.venv`,
    whose `.pth` file is what installs GCM in a checkout."""
    return [command[0], "-I", "-S", *command[1:]]


def run_on_a_pty(command: list[str]) -> tuple[int, str]:
    """`command` with a pty for its input and output, as VTE gives a tab: its exit status
    and everything it wrote."""
    master, slave = os.openpty()
    process = subprocess.Popen(command, stdin=slave, stdout=slave, stderr=slave)
    os.close(slave)
    written = b""
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], 1)
            if not ready:
                continue
            try:
                chunk = os.read(master, 4096)
            except OSError:  # EIO: nothing holds the pty's other end any more
                break
            if not chunk:
                break
            written += chunk
        return process.wait(timeout=30), written.decode(errors="replace")
    finally:
        process.kill()
        os.close(master)


def test_an_interpreter_run_so_finds_nothing_of_gcm_by_itself() -> None:
    """The yardstick of the two tests below, which would pass for any command if this
    interpreter found GCM: the `-m` the children were started with does not here."""
    result = subprocess.run(
        [*without_site([sys.executable]), "-m", "gnome_connection_manager.relay"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode != 0
    assert "No module named 'gnome_connection_manager'" in result.stderr


def test_the_relay_starts_where_only_its_command_finds_gcm(app_module: ModuleType) -> None:
    command = app_module.relay_command(["/bin/sh", "-c", "echo under the relay; exit 7"])

    status, output = run_on_a_pty(without_site(command))

    assert status == 7, output  # the program's, passed on by the relay
    assert "under the relay" in output


def test_the_update_check_starts_where_only_its_command_finds_gcm(
    app_module: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    answer = tmp_path / "tags.json"
    answer.write_bytes(b'[{"name": "v9.9.9"}]')
    *command, asked = start_check(app_module, monkeypatch).process.argv
    assert asked == updates.TAGS_URL

    found = subprocess.run(
        without_site([*command, answer.as_uri()]), capture_output=True, timeout=60, check=False
    )

    assert (found.returncode, found.stdout) == (0, answer.read_bytes()), found.stderr
