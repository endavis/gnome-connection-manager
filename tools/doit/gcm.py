"""Tasks specific to gnome-connection-manager.

Everything else under `tools/doit/` is vendored from pyproject-template and is replaced
wholesale on a sync. Project-specific tasks live here so a sync never has to merge them.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404 - required to run msgfmt and the app
import sys
from pathlib import Path
from typing import Any

from doit.tools import title_with_actions

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
