"""Build and publish doit tasks."""

import os
import platform
import shutil
import subprocess  # nosec B404 - subprocess is required to build/install/run the wheel
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path
from typing import Any

from doit.action import CmdAction
from doit.tools import title_with_actions
from rich.console import Console

from .base import verbatim


def task_build() -> dict[str, Any]:
    """Build package."""
    return {
        "actions": ["uv build"],
        "title": title_with_actions,
    }


def task_publish() -> dict[str, Any]:
    """Build and publish package to PyPI."""

    def publish_cmd() -> str:
        token = os.environ.get("PYPI_TOKEN")
        if not token:
            raise RuntimeError("PYPI_TOKEN environment variable must be set.")
        return "uv publish --token '{token}'"

    return {
        "actions": ["uv build", CmdAction(publish_cmd)],
        "title": title_with_actions,
    }


def _load_pyproject(path: Path) -> dict[str, Any]:
    """Parse ``path`` (a ``pyproject.toml``) with ``tomllib``.

    Raises ``ValueError`` with a message naming the path on any failure
    (missing file, malformed TOML) so callers can report it and exit rather
    than let a raw ``tomllib``/``OSError`` traceback surface.
    """
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except (tomllib.TOMLDecodeError, OSError) as exc:
        raise ValueError(f"could not read {path}: {exc}") from exc


def _import_name(pyproject: dict[str, Any]) -> str:
    """Derive the installed package's import name from a parsed ``pyproject.toml``.

    Prefers ``[tool.hatch.build.targets.wheel].packages[0]`` — the last path
    segment of an entry like ``src/package_name`` is the import name — so a
    downstream rename that only touches the wheel ``packages`` list still
    resolves correctly. Falls back to ``project.name`` normalized the way
    wheel builders do (``-`` -> ``_``) when the hatch table is absent, since
    not every build backend uses hatchling.
    """
    hatch_wheel = (
        pyproject.get("tool", {})
        .get("hatch", {})
        .get("build", {})
        .get("targets", {})
        .get("wheel", {})
    )
    packages = hatch_wheel.get("packages")
    if packages:
        first = str(packages[0]).replace("\\", "/").rstrip("/")
        return first.rsplit("/", 1)[-1]

    project_name = str(pyproject.get("project", {}).get("name", ""))
    return project_name.replace("-", "_")


def _scripts(pyproject: dict[str, Any]) -> list[str]:
    """Return the console-script names declared in ``[project.scripts]``, sorted."""
    return sorted(pyproject.get("project", {}).get("scripts", {}))


def _find_wheel(dist_dir: Path) -> Path:
    """Return the single ``*.whl`` in ``dist_dir``.

    Raises ``ValueError`` when zero or more than one wheel is present, naming
    every candidate found so the caller can report it.
    """
    wheels = sorted(dist_dir.glob("*.whl"))
    if not wheels:
        raise ValueError(f"no *.whl found in {dist_dir}")
    if len(wheels) > 1:
        names = ", ".join(w.name for w in wheels)
        raise ValueError(f"expected exactly one *.whl in {dist_dir}, found {len(wheels)}: {names}")
    return wheels[0]


def _missing_py_typed(wheel_path: Path, import_name: str) -> str | None:
    """Return the expected ``py.typed`` member path if absent from the wheel, else ``None``."""
    expected = f"{import_name}/py.typed"
    with zipfile.ZipFile(wheel_path) as zf:
        names = set(zf.namelist())
    return None if expected in names else expected


def _venv_python(venv_dir: Path) -> Path:
    """Return the venv's ``python`` executable, Windows-aware (``Scripts/python.exe``)."""
    if platform.system() == "Windows":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _venv_script(venv_dir: Path, name: str) -> Path:
    """Return the path an installed console script ``name`` would land at in the venv."""
    if platform.system() == "Windows":
        return venv_dir / "Scripts" / f"{name}.exe"
    return venv_dir / "bin" / name


def _git(args: list[str], cwd: Path | None = None) -> str:
    """Run ``git`` with ``args`` and return its stdout.

    Raises ``ValueError`` naming the command and its output on a non-zero exit.
    """
    result = subprocess.run(  # nosec B603 B607 - fixed argv, no shell
        ["git", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )
    if result.returncode != 0:
        raise ValueError(f"`git {' '.join(args)}` failed:\n{result.stdout}{result.stderr}")
    return result.stdout


def _snapshot_source_tree(dest: Path) -> None:
    """Copy the working tree into ``dest`` as a git repository at the same commit.

    Building in place lets the build backend's version hook rewrite generated,
    gitignored files in the source tree (hatch-vcs rewrites
    ``src/<pkg>/_version.py``), which leaves them out of step with the editable
    install's metadata (issue #937). Building from this snapshot sends those
    writes to ``dest`` instead.

    ``dest`` is a ``--shared`` clone so the VCS version is computed from the
    same commit and tags, overlaid with every tracked and untracked,
    non-ignored file from the working tree so uncommitted changes are built.
    Nothing in the source repository, its index included, is written.

    Raises ``ValueError`` if any ``git`` command fails.
    """
    head = _git(["rev-parse", "HEAD"]).strip()
    _git(["clone", "--quiet", "--shared", "--no-checkout", ".", str(dest)])
    listing = _git(["ls-files", "-z", "--cached", "--others", "--exclude-standard"])
    for name in filter(None, listing.split("\0")):
        src = Path(name)
        # --cached lists tracked files deleted from disk; submodules are directories.
        if not (src.is_symlink() or src.is_file()):
            continue
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target, follow_symlinks=False)
    _git(["reset", "--quiet", head], cwd=dest)


def _check_wheel(dist: str) -> list[str]:
    """Build (or reuse) a wheel, install it in a throwaway venv, and smoke-test it.

    Returns a list of human-readable failure messages; empty means the wheel
    passed every check. Never raises for an expected failure (missing
    py.typed, broken entry point, import error) — those become entries in
    the returned list so the caller can report every problem found in one
    run instead of stopping at the first.
    """
    failures: list[str] = []

    try:
        pyproject = _load_pyproject(Path("pyproject.toml"))
    except ValueError as exc:
        return [str(exc)]

    import_name = _import_name(pyproject)
    scripts = _scripts(pyproject)

    with tempfile.TemporaryDirectory(prefix="wheel-check-") as tmp_name:
        tmp_dir = Path(tmp_name)

        if dist:
            dist_dir = Path(dist)
        else:
            dist_dir = tmp_dir / "dist"
            dist_dir.mkdir()
            source_dir = tmp_dir / "source"
            try:
                _snapshot_source_tree(source_dir)
            except ValueError as exc:
                return [f"could not snapshot the source tree to build from: {exc}"]
            build_result = subprocess.run(  # nosec B603 B607 - fixed argv, no shell
                ["uv", "build", "--wheel", "--out-dir", str(dist_dir)],
                capture_output=True,
                text=True,
                check=False,
                cwd=source_dir,
            )
            if build_result.returncode != 0:
                return [f"`uv build --wheel` failed:\n{build_result.stdout}{build_result.stderr}"]

        try:
            wheel_path = _find_wheel(dist_dir)
        except ValueError as exc:
            return [str(exc)]

        missing = _missing_py_typed(wheel_path, import_name)
        if missing is not None:
            failures.append(
                f"py.typed missing from wheel: expected {missing!r} in {wheel_path.name}"
            )

        venv_dir = tmp_dir / "venv"
        venv_result = subprocess.run(  # nosec B603 B607 - fixed argv, no shell
            ["uv", "venv", str(venv_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
        if venv_result.returncode != 0:
            failures.append(f"`uv venv` failed:\n{venv_result.stdout}{venv_result.stderr}")
            return failures

        python_path = _venv_python(venv_dir)
        install_result = subprocess.run(  # nosec B603 B607 - fixed argv, no shell
            ["uv", "pip", "install", "--python", str(python_path), str(wheel_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if install_result.returncode != 0:
            failures.append(
                f"`uv pip install` of {wheel_path.name} failed:\n"
                f"{install_result.stdout}{install_result.stderr}"
            )
            return failures

        import_result = subprocess.run(  # nosec B603 B607 - fixed argv, no shell
            [
                str(python_path),
                "-c",
                f"import {import_name}; print({import_name}.__version__); "
                f"print({import_name}.__file__)",
            ],
            capture_output=True,
            text=True,
            check=False,
            cwd=tmp_dir,
        )
        if import_result.returncode != 0:
            failures.append(
                f"importing {import_name!r} from the installed wheel failed:\n"
                f"{import_result.stdout}{import_result.stderr}"
            )
        else:
            lines = import_result.stdout.strip().splitlines()
            module_file = lines[-1] if lines else ""
            resolved_venv = venv_dir.resolve()
            try:
                resolved_module = Path(module_file).resolve()
                imported_from_venv = (
                    resolved_module == resolved_venv
                    or resolved_module.is_relative_to(resolved_venv)
                )
            except OSError:
                imported_from_venv = False
            if not imported_from_venv:
                failures.append(
                    f"{import_name}.__file__ resolved to {module_file!r}, not inside the "
                    f"venv {venv_dir} — the source tree was imported instead of the wheel"
                )

        for script in scripts:
            script_path = _venv_script(venv_dir, script)
            if not script_path.exists():
                failures.append(f"console script {script!r} was not installed at {script_path}")
                continue
            help_result = subprocess.run(  # nosec B603 B607 - fixed argv, no shell
                [str(script_path), "--help"],
                capture_output=True,
                text=True,
                check=False,
            )
            if help_result.returncode != 0:
                failures.append(
                    f"`{script} --help` exited {help_result.returncode}:\n"
                    f"{help_result.stdout}{help_result.stderr}"
                )

    return failures


def task_wheel_check() -> dict[str, Any]:
    """Build (or reuse) the wheel, install it in a throwaway venv, and smoke-test it.

    Installs the wheel into an isolated venv outside the source tree, imports
    the package, runs every ``[project.scripts]`` entry with ``--help``, and
    confirms ``py.typed`` shipped in the wheel — so a packaging regression
    (missing module, broken entry point, missing ``py.typed``) fails before it
    reaches PyPI. See issue #837. A fresh wheel is built from a snapshot of the
    working tree so the build never writes into the source tree (issue #937).

    Options:
        --dist: Directory containing an already-built wheel to check (e.g.
            ``dist``) instead of building a fresh one. Fails if the directory
            has zero or more than one ``*.whl``.
    """

    def run_wheel_check(dist: str) -> None:
        console = Console()
        failures = _check_wheel(dist)

        if failures:
            console.print()
            console.print("[bold red]wheel_check failed:[/bold red]")
            for failure in failures:
                console.print("[red]-[/red]", verbatim(failure))
            sys.exit(1)

        console.print("[bold green]✓ wheel_check passed.[/bold green]")

    return {
        "actions": [run_wheel_check],
        "params": [
            {
                "name": "dist",
                "long": "dist",
                "default": "",
                "help": "Directory with an already-built wheel to check (e.g. 'dist'), "
                "instead of building a fresh one.",
            },
        ],
        "title": title_with_actions,
    }
