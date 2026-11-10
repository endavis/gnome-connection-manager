"""Tasks specific to gnome-connection-manager.

Everything else under `tools/doit/` is vendored from pyproject-template and is replaced
wholesale on a sync. Project-specific tasks live here so a sync never has to merge them.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess  # nosec B404  # required to run msgfmt and the app
import sys
import tempfile
from datetime import datetime
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


def _run_sandbox(
    fresh: bool,
    many: int,
    few: int,
    scale: str,
    local: int = 0,
    wait: bool = False,
    trace: str = "",
    wayland_debug: bool = False,
    xvfb: bool = False,
) -> bool:
    """Prepare the sandbox and run GCM against it. False when GCM could not start or failed.

    GCM runs detached, its output in a log, so doit's database is released while it runs;
    `wait` keeps it in the foreground with its output on the terminal and its exit status.
    `xvfb` runs it so on an Xvfb of the run's own (#509), which it stops on every way out.
    """
    from tools import sandbox

    python = Path(sandbox.command(REPO)[0])
    if not python.exists():
        print(f"No {python}: run `doit setup` first.")
        return False
    home = sandbox.sandbox_home(REPO)
    started = None
    display = None
    try:
        written = sandbox.prepare(home, fresh=fresh, many=many, few=few, local=local)
        if xvfb:
            # Checked after the arguments, so a bad one starts no server.
            sandbox.environment({}, home, scale or None)
            from tests import xdisplay

            started = xdisplay.start()
            if started is None:
                print("No Xvfb came up: sudo apt install xvfb")
                return False
            display = started[1]
        env = sandbox.environment(
            dict(os.environ), home, scale or None, trace, wayland_debug, display
        )
    except ValueError as error:
        if started is not None:
            xdisplay.stop(started[0])
        print(error)
        return False
    if written:
        print(f"Wrote {sandbox.config_file(home)}")
    else:
        print(f"Kept {home}; --fresh rebuilds it")
    head = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()  # nosec B603 B607
    status = f"GCM {head or '(unknown commit)'}, GDK_DPI_SCALE={env.get('GDK_DPI_SCALE', '(unset)')}, HOME={home}"
    if "GCM_TRACE" in env:
        status += f", GCM_TRACE={env['GCM_TRACE']}"
    print(status)
    if started is not None:
        print(f"DISPLAY={started[1]} (Xvfb PID {started[0].pid})")
        return _run_on_display(sandbox.command(REPO), env, started[0])
    if wait:
        done = subprocess.run(sandbox.command(REPO), env=env, cwd=REPO, check=False)  # nosec B603
        return done.returncode == 0
    log = sandbox.log_file(home, datetime.now())
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("ab") as stream:
        process = subprocess.Popen(  # nosec B603
            sandbox.command(REPO),
            env=env,
            cwd=REPO,
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    print(f"GCM runs as PID {process.pid}, its output in {log}")
    return True


def _run_on_display(command: list[str], env: dict[str, str], xvfb_process: Any) -> bool:
    """Run GCM in the foreground on the run's Xvfb; True when it exits 0 (#509).

    GCM and Xvfb stay in doit's process group, so `timeout` and a terminal's Ctrl+C reach
    them as they reach doit. A SIGTERM to doit alone does not, so a handler for the run
    ends both, SIGINT's as well as SIGTERM's (#527); it is idempotent, as `timeout` has been
    measured to deliver the signal twice through `uv run`. Whatever the way out, GCM is then waited for and killed if it will
    not go, and the Xvfb stopped.
    """
    from tests import xdisplay

    process: subprocess.Popen[bytes] | None = None
    signalled = False

    def end_both(_signum: int, _frame: Any) -> None:
        nonlocal signalled
        signalled = True
        for child in (process, xvfb_process):
            if child is not None and child.poll() is None:
                child.terminate()

    # SIGINT too, not a KeyboardInterrupt: one that lands before Popen returns leaves
    # `process` None, and GCM, started all the same, would never be stopped (#527). A
    # signal that comes in that window is acted on once `process` is set, below.
    previous = {
        number: signal.signal(number, end_both) for number in (signal.SIGTERM, signal.SIGINT)
    }
    try:
        process = subprocess.Popen(command, env=env, cwd=REPO)  # nosec B603
        if signalled:
            process.terminate()
        process.wait()
        return process.returncode == 0
    finally:
        if process is not None:
            xdisplay.stop(process)
        xdisplay.stop(xvfb_process)
        for number, handler in previous.items():
            signal.signal(number, handler)


def task_sandbox() -> dict[str, Any]:
    """Run the application against a throwaway configuration under tmp/.

    Not `doit launch` or `uv run`: the HOME is a folder of the checkout's, holding a
    folder of many hosts and one of a few, so your own ~/.config/gcm is never read or
    written. GCM runs from the checkout's venv directly, as `uv run` would look for its
    cache under the fake HOME. Update checks are off in it.

    Options:
        --fresh: Rebuild the sandbox.
        --many: Hosts in the "Many hosts" folder (default 30).
        --few: Hosts in the "Few hosts" folder (default 3).
        --scale: GDK_DPI_SCALE for GCM, a positive number.
        --local: Hosts in the "Local hosts" folder, each a local shell (default 0).
        --wait: Keep GCM in the foreground, its output on the terminal.
        --trace: GCM_TRACE for GCM, the areas to trace (drag, menu, keys, actions, links,
            config, notifications, all).
        --wayland-debug: WAYLAND_DEBUG=client, its lines in the same log as the trace.
        --xvfb: Run GCM on an Xvfb of this run's own, headless; implies --wait. The Xvfb
            and GCM end with the task, however it ends.
    """
    return {
        "actions": [_run_sandbox],
        "params": [
            {
                "name": "fresh",
                "long": "fresh",
                "type": bool,
                "default": False,
                "help": "Rebuild the sandbox.",
            },
            {
                "name": "many",
                "long": "many",
                "type": int,
                "default": 30,
                "help": "Hosts in the 'Many hosts' folder.",
            },
            {
                "name": "few",
                "long": "few",
                "type": int,
                "default": 3,
                "help": "Hosts in the 'Few hosts' folder.",
            },
            {
                "name": "scale",
                "long": "scale",
                "default": "",
                "help": "GDK_DPI_SCALE for GCM, a positive number.",
            },
            {
                "name": "local",
                "long": "local",
                "type": int,
                "default": 0,
                "help": "Hosts in the 'Local hosts' folder.",
            },
            {
                "name": "wait",
                "long": "wait",
                "type": bool,
                "default": False,
                "help": "Keep GCM in the foreground.",
            },
            {
                "name": "trace",
                "long": "trace",
                "default": "",
                "help": (
                    "GCM_TRACE for GCM: the areas to trace "
                    "(drag, menu, keys, actions, links, config, notifications, all)."
                ),
            },
            {
                "name": "wayland_debug",
                "long": "wayland-debug",
                "type": bool,
                "default": False,
                "help": "WAYLAND_DEBUG=client, in the same log as the trace.",
            },
            {
                "name": "xvfb",
                "long": "xvfb",
                "type": bool,
                "default": False,
                "help": "Run GCM on an Xvfb of its own, in the foreground (implies --wait).",
            },
        ],
        "title": title_with_actions,
        "verbosity": 2,
    }


def _list_wslg_windows() -> bool:
    """Print the windows of WSLg's msrdc.exe; False off WSL or on a failure."""
    from tools import wslg_windows

    return wslg_windows.main([]) == 0


def task_wslg_windows() -> dict[str, Any]:
    """List the windows WSLg's own msrdc.exe holds, from inside WSL (#510).

    Shows each window's title, place, size, visibility, DPI and class, to find the grey
    rectangle a failed tab drag leaves on the Windows desktop (#401). Only WSL has them:
    elsewhere the task says so and fails.
    """
    return {
        "actions": [_list_wslg_windows],
        "title": title_with_actions,
        "verbosity": 2,
    }


def _write_screenshot(out: str) -> bool:
    """Write the README's screenshot to `out`; False when the run failed (#546)."""
    from tools import screenshot

    return screenshot.run(Path(out))


def task_screenshot() -> dict[str, Any]:
    """Write the README's screenshot, docs/images/screenshot.png, from this checkout (#546).

    This replaces the file the README shows. GCM runs on an Xvfb of its own, under a scratch
    HOME with a seeded tree of hosts and four tabs, in English, so nothing reaches your
    desktop or your ~/.config/gcm. The console of each tab shows this checkout's `git log`
    and `git status -sb`, so commit first. The file is replaced only after a run that ended
    as it should; after any other it is as it was. Unlike `doit sandbox --xvfb` (#527), it
    does not handle a SIGTERM sent to doit alone, which leaves the Xvfb running; a
    terminal's Ctrl+C and `timeout` reach the Xvfb and GCM as they reach doit.

    Options:
        --out: Where to write the PNG (default docs/images/screenshot.png).
    """
    return {
        "actions": [_write_screenshot],
        "params": [
            {
                "name": "out",
                "long": "out",
                "default": str(REPO / "docs" / "images" / "screenshot.png"),
                "help": "Where to write the PNG; the default is the README's own.",
            },
        ],
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
    return {
        "actions": [_audit_lock],
        "title": title_with_actions,
        "verbosity": 2,
    }


EXPORT_COMMAND = [
    "uv",
    "export",
    "--frozen",
    "--no-emit-project",
    "--all-extras",
    "--format",
    "requirements-txt",
]


def _audit_lock() -> bool:
    """Export uv.lock to a folder outside the tree, and audit what it pins.

    Not into tmp/, as this did: `doit pr_merge` keeps a worktree holding a file it cannot
    rebuild, and the export kept every worktree `doit check` had run in (#332). Nor with
    an action after pip-audit to remove it, since doit runs no action after a failed one,
    and the export would have stayed exactly when the audit failed.
    """
    with tempfile.TemporaryDirectory(prefix="gcm-audit-") as folder:
        requirements = str(Path(folder) / "requirements-audit.txt")
        try:
            run_streamed([*EXPORT_COMMAND, "-o", requirements], cwd=REPO)
            run_streamed(["uv", "run", "pip-audit", "-r", requirements], cwd=REPO)
        except subprocess.CalledProcessError:
            return False
    return True


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
