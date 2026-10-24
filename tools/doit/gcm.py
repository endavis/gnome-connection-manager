"""Tasks specific to gnome-connection-manager.

Everything else under `tools/doit/` is vendored from pyproject-template and is replaced
wholesale on a sync. Project-specific tasks live here so a sync never has to merge them.
"""

from __future__ import annotations

import os
import shutil
import subprocess  # nosec B404 - required to run msgfmt and the app
import sys
from pathlib import Path
from typing import Any

from doit.tools import title_with_actions

from . import git, quality
from .base import run_streamed

REPO = Path(__file__).resolve().parents[2]
LANG_DIR = REPO / "lang"
CATALOG = "gcm-lang.mo"


def task_launch() -> dict[str, Any]:
    """Run the application in development mode.

    Not `task_run`: doit reserves `run` as a command name and refuses to load a task
    called that.
    """
    return {
        "actions": ["uv run python -m gnome_connection_manager"],
        "title": title_with_actions,
        "verbosity": 2,
    }


def task_setup() -> dict[str, Any]:
    """Create the development environment.

    Not `install_dev`. GCM imports GTK and VTE through PyGObject, which is an apt package
    living in the system interpreter's dist-packages -- it is not installable from PyPI.
    The virtualenv therefore has to be created with --system-site-packages or every
    `import gi` fails. A plain `uv sync` reuses an existing venv and keeps the setting, so
    this only has to run once per checkout, but it does have to run first.
    """
    return {
        "actions": [
            "uv venv --system-site-packages",
            "uv sync --all-extras --dev",
            'echo "Development environment ready. Activate with: source .venv/bin/activate"',
        ],
        "title": title_with_actions,
        "verbosity": 2,
    }


def _compile_catalogs(lang_dir: Path | None = None) -> bool:
    """Compile lang/<lang>_<REGION>.po into lang/<lang>/LC_MESSAGES/gcm-lang.mo.

    Prefers msgfmt and falls back to tools/build_mo.py, so a checkout without gettext
    installed still produces catalogs the application can load.

    Returns False when there was nothing to compile, which doit reports as a failed task.
    That is the whole of #101: the old recipe globbed a directory that only ever held the
    compiled output, so it compiled nothing and printed "Translations compiled" anyway.

    `lang_dir` is a parameter so this can be exercised against a temporary tree.
    """
    lang_dir = LANG_DIR if lang_dir is None else lang_dir
    sources = sorted(lang_dir.glob("*.po"))
    if not sources:
        print(f"no .po files in {lang_dir} -- nothing was compiled")
        return False

    msgfmt = shutil.which("msgfmt")
    for po in sources:
        language = po.stem.split("_")[0]
        mo = lang_dir / language / "LC_MESSAGES" / CATALOG
        mo.parent.mkdir(parents=True, exist_ok=True)
        if msgfmt:
            subprocess.run([msgfmt, "-o", str(mo), str(po)], check=True)  # nosec B603
        else:
            subprocess.run(  # nosec B603
                [sys.executable, str(REPO / "tools" / "build_mo.py"), str(po), str(mo)],
                check=True,
                stdout=subprocess.DEVNULL,
            )
        print(f"  {po.name} -> {mo}")

    print(f"Translations compiled ({len(sources)})")
    return True


def task_translate() -> dict[str, Any]:
    """Compile the translation catalogs the application loads at runtime."""
    return {
        "actions": [_compile_catalogs],
        "targets": [
            str(LANG_DIR / po.stem.split("_")[0] / "LC_MESSAGES" / CATALOG)
            for po in sorted(LANG_DIR.glob("*.po"))
        ],
        "file_dep": [str(po) for po in sorted(LANG_DIR.glob("*.po"))],
        "title": title_with_actions,
        "verbosity": 2,
    }


def task_audit() -> dict[str, Any]:
    """Audit the project's locked dependencies for known vulnerabilities.

    Overrides the vendored task, which audits the *environment*. GCM's virtualenv is
    created with --system-site-packages so it can reach PyGObject, and a plain `pip-audit`
    therefore walks every distribution apt installed as well -- cloud-init, python-apt,
    ubuntu-pro-client -- then fails because none of them are on PyPI. Exporting the
    lockfile audits what this project actually pins, which is the question being asked.

    dodo.py installs this by name after discovery, because two modules defining task_audit
    would otherwise be resolved by whatever order rglob happened to return them in.
    """
    export = (
        "uv export --frozen --no-emit-project --all-extras "
        "--format requirements-txt -o tmp/requirements-audit.txt"
    )
    return {
        "actions": [
            "mkdir -p tmp",
            export,
            "uv run pip-audit -r tmp/requirements-audit.txt",
        ],
        "title": title_with_actions,
        "verbosity": 2,
    }


def task_check() -> dict[str, Any]:
    """Run all checks, as the vendored task does, without wheel_check.

    Overrides the vendored task, which also runs wheel_check: it installs the built wheel
    in a clean virtualenv, imports the package and runs each console script with --help.
    A wheel cannot supply GTK, VTE or PyGObject, so there `gcm --help` exits 1 with "No
    module named 'gi'", and the wheel carries no py.typed either, measured (#324). The
    rest of the vendored list is kept as it is, so a check the template adds reaches this
    one at the next sync.

    dodo.py installs this by name after discovery, as it does task_audit.
    """
    task = quality.task_check()
    task["task_dep"] = [dep for dep in task["task_dep"] if dep != "wheel_check"]
    return task


# How CI builds GCM's environment: from the system interpreter, whose dist-packages hold
# PyGObject, with the system's site packages in reach. tests/test_worktree.py holds both
# commands to ci.yml.
VENV_COMMAND = ["uv", "venv", "--system-site-packages", "--python", "/usr/bin/python3"]
SYNC_COMMAND = ["uv", "sync", "--all-extras", "--dev"]


def _build_venv_as_ci_does(branch: str) -> None:
    """Build the .venv of the worktree just made for *branch* again, as CI builds GCM's."""
    path = git.worktree_for_branch(branch)
    if path is None:
        print(f"No worktree has {branch} checked out, so no .venv was built again.")
        sys.exit(1)
    # The environment the vendored task gives its own sync, for the reasons it gives.
    env = {key: value for key, value in os.environ.items() if key != "VIRTUAL_ENV"}
    if "UV_CACHE_DIR" in env:
        env["UV_CACHE_DIR"] = str(Path(env["UV_CACHE_DIR"]).resolve())
    try:
        # Quiet, so that the vendored task's account of how to work there stays in sight.
        run_streamed([*VENV_COMMAND, "--clear", "--quiet"], env=env, cwd=path)
        run_streamed([*SYNC_COMMAND, "--quiet"], env=env, cwd=path)
    except subprocess.CalledProcessError:
        print("Building its .venv as CI builds GCM's failed. The worktree exists; run in it:")
        print("  " + " ".join([*VENV_COMMAND, "--clear"]))
        print("  " + " ".join(SYNC_COMMAND))
        sys.exit(1)
    print("Its .venv is built again from /usr/bin/python3, with the system's site packages,")
    print("where PyGObject is, as CI builds GCM's.")


def task_worktree() -> dict[str, Any]:
    """Create a git worktree with its own environment, built as CI builds GCM's.

    Overrides the vendored task, which builds the worktree's .venv with `uv sync` alone.
    That leaves out the system's site packages, the only place PyGObject comes from, so
    `gi` did not import in a worktree, and the suite failed and skipped there (#327). uv's
    `uv sync` has no option for them, and the .venv cannot be made before `git worktree
    add` makes its folder, so an action after the vendored one builds it again and syncs
    it. The vendored task is kept as it is otherwise, so a change the template makes to it
    reaches this one at the next sync.

    dodo.py installs this by name after discovery, as it does task_audit.
    """
    task = git.task_worktree()
    task["actions"].append(_build_venv_as_ci_does)
    return task
