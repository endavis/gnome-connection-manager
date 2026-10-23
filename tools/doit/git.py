"""Git-related doit tasks."""

import os
import subprocess  # nosec B404 - subprocess is required for doit tasks
import sys
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import Any

from doit.tools import title_with_actions
from rich.console import Console

from .base import install_check_or_skip, run_streamed, verbatim

# Where `doit worktree` creates worktrees, relative to the main checkout. It is
# gitignored and skipped by the repo-wide test walkers. Not under tmp/, which
# `doit cleanup` empties (#854).
WORKTREES_DIR = "worktrees"

# Ignored files a worktree can always rebuild, matched against the last part of
# each path `git status --ignored` lists. `git worktree remove` deletes ignored
# files without asking, so any other ignored file keeps the worktree: it may be
# an `.envrc.local`, or notes under tmp/ (#863).
_REBUILDABLE_IGNORED = (
    ".venv",
    ".direnv",
    "__pycache__",
    "*_cache",  # .pytest_cache, .mypy_cache, .ruff_cache
    ".hypothesis",
    ".coverage*",
    "coverage.xml",
    "htmlcov",
    ".doit.db*",
    "_version.py",
    "build",
    "dist",
    "site",
    "*.egg-info",
)


def task_commit() -> dict[str, Any]:
    """Interactive commit with commitizen (ensures conventional commit format)."""
    return {
        "actions": [
            install_check_or_skip(
                "commitizen",
                "commitizen not installed. Run: doit install_dev",
            )
            + "uv run cz commit"
        ],
        "title": title_with_actions,
    }


def task_bump() -> dict[str, Any]:
    """Bump version automatically based on conventional commits."""
    return {
        "actions": [
            install_check_or_skip(
                "commitizen",
                "commitizen not installed. Run: doit install_dev",
            )
            + "uv run cz bump"
        ],
        "title": title_with_actions,
    }


def task_changelog() -> dict[str, Any]:
    """Generate CHANGELOG from conventional commits."""
    return {
        "actions": [
            install_check_or_skip(
                "commitizen",
                "commitizen not installed. Run: doit install_dev",
            )
            + "uv run cz changelog"
        ],
        "title": title_with_actions,
    }


def task_pre_commit_install() -> dict[str, Any]:
    """Install pre-commit hooks.

    One action, deliberately. `.pre-commit-config.yaml` declares
    `default_install_hook_types`, so a bare `pre-commit install` installs every
    declared type — including `commit-msg`, which carries conventional-commit
    validation and the branch/issue check (#741).

    This used to enumerate `post-merge` and `post-checkout` explicitly. Those
    lines were redundant once the config declared the set, and worse than
    redundant: `commit-msg` was never added to them, so the enumeration
    described a hook set that was no longer the hook set, and the next person to
    add a type would have followed the pattern and silently changed nothing.
    The config is the single source; `tests/template/test_doit_git.py` holds the
    two to each other.
    """
    return {
        "actions": ["uv run pre-commit install"],
        "title": title_with_actions,
    }


def task_pre_commit_run() -> dict[str, Any]:
    """Run pre-commit on all files."""
    return {
        "actions": ["uv run pre-commit run --all-files"],
        "title": title_with_actions,
    }


def _main_checkout() -> Path:
    """Return the main checkout's root, also when run from a linked worktree.

    ``git worktree list`` always lists the main worktree first.
    """
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(result.stdout.splitlines()[0].removeprefix("worktree "))


def worktree_for_branch(branch: str) -> Path | None:
    """Return the linked worktree that has *branch* checked out, or ``None``.

    The main checkout is never returned. ``gh pr merge --delete-branch``
    handles a branch checked out there (#863).
    """
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    )
    # One block per worktree, separated by a blank line. The first block is the
    # main checkout.
    for block in result.stdout.split("\n\n")[1:]:
        lines = block.splitlines()
        if f"branch refs/heads/{branch}" in lines:
            return Path(lines[0].removeprefix("worktree "))
    return None


def _worktree_leftovers(worktree: Path) -> list[str]:
    """Return the ``git status`` lines for files that removing *worktree* would affect.

    ``git worktree remove`` refuses modified and untracked files, and deletes
    ignored ones. So every line counts, except ignored files that can be rebuilt.
    """
    status = subprocess.run(
        ["git", "-C", str(worktree), "status", "--porcelain", "--ignored"],
        capture_output=True,
        text=True,
        check=True,
    )
    leftovers = []
    for line in status.stdout.splitlines():
        name = PurePosixPath(line[3:].rstrip("/")).name
        if line.startswith("!! ") and any(fnmatch(name, p) for p in _REBUILDABLE_IGNORED):
            continue
        leftovers.append(line)
    return leftovers


def _branch_tip(branch: str) -> str:
    """Return the commit *branch* points at, or ``""`` if there is no such branch."""
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip()


def _remove_empty_parents(worktree: Path, stop: Path) -> None:
    """Remove the directories *worktree* leaves empty, up to but not including *stop*."""
    for parent in worktree.parents:
        if parent.resolve() == stop.resolve():
            return
        try:
            parent.rmdir()
        except OSError:  # not empty: another worktree is still there
            return


def remove_merged_worktree(worktree: Path, branch: str, merged_head: str, console: Console) -> None:
    """Remove a merged PR's worktree and local branch, or print how to (#863).

    Only a worktree under ``worktrees/`` is removed, and only when git would not
    refuse and no ignored file other than a rebuildable one would be deleted
    with it. The branch is deleted only if it points at *merged_head*, the
    commit the PR merged: a squash merge needs ``git branch -D``, which would
    otherwise drop a commit that was never pushed.

    Args:
        worktree: The linked worktree that has *branch* checked out.
        branch: The PR's head branch.
        merged_head: The PR's head commit when it merged.
        console: Rich console for output.
    """
    root = _main_checkout()
    managed = root / WORKTREES_DIR
    if not worktree.resolve().is_relative_to(managed.resolve()):
        console.print(
            verbatim(
                f"{branch} is checked out in {worktree}, which `doit worktree` did not "
                "create. Left the worktree and the branch in place.",
                "yellow",
            ),
            soft_wrap=True,
        )
        return

    tip = _branch_tip(branch)
    inside = Path.cwd().resolve().is_relative_to(worktree.resolve())
    leftovers = _worktree_leftovers(worktree)
    if inside or leftovers:
        if inside:
            console.print(
                "[yellow]This task runs inside the worktree, so it cannot remove it.[/yellow]"
            )
        if leftovers:
            console.print(
                verbatim(
                    f"Left {worktree} in place. `git worktree remove` refuses modified and "
                    "untracked files, and deletes ignored ones:",
                    "yellow",
                ),
                soft_wrap=True,
            )
            for line in leftovers:
                console.print(verbatim(f"  {line}"), soft_wrap=True)
        console.print("[bold]To remove it, from the main checkout:[/bold]")
        console.print(verbatim(f"  cd {root}"), soft_wrap=True)
        console.print(verbatim(f"  git worktree remove {worktree}"), soft_wrap=True)
        if tip and tip == merged_head:
            console.print(verbatim(f"  git branch -D {branch}"), soft_wrap=True)
        elif tip:
            _warn_branch_moved(branch, tip, merged_head, console)
        return

    try:
        subprocess.run(
            ["git", "worktree", "remove", str(worktree)],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        console.print(
            verbatim(f"git worktree remove failed: {(e.stderr or '').strip()}", "yellow"),
            soft_wrap=True,
        )
        return
    console.print(verbatim(f"Removed worktree {worktree}", "green"), soft_wrap=True)
    _remove_empty_parents(worktree, managed)

    if tip and tip == merged_head:
        subprocess.run(["git", "branch", "-D", branch], capture_output=True, text=True, check=True)
        console.print(f"[green]Deleted local branch {branch}[/green]")
    elif tip:
        _warn_branch_moved(branch, tip, merged_head, console)


def _warn_branch_moved(branch: str, tip: str, merged_head: str, console: Console) -> None:
    """Say why *branch* was kept: it no longer points at the commit the PR merged."""
    console.print(
        f"[yellow]Kept local branch {branch}: it is at {tip[:7]}, but the PR merged "
        f"{merged_head[:7] or 'an unknown commit'}. Delete it with `git branch -D {branch}` "
        "once nothing on it is needed.[/yellow]",
        soft_wrap=True,
    )


def task_worktree() -> dict[str, Any]:
    """Create a git worktree in ``worktrees/<branch>`` with its own environment.

    The branch starts from a freshly fetched ``origin/main`` with no upstream,
    so ``doit pr`` pushes it. ``uv sync --all-extras --dev`` then builds the
    worktree's own ``.venv`` with ``VIRTUAL_ENV`` unset: an inherited
    ``VIRTUAL_ENV`` names the main checkout's environment, which a worktree
    must neither use nor change (#854).

    Examples:
        doit worktree --branch=feat/42-add-export
    """

    def create_worktree(branch: str | None = None) -> None:
        # soft_wrap leaves wrapping to the terminal. Otherwise Rich breaks lines at
        # 80 columns when output is not a tty, splitting a path in a command to
        # paste, or git's own error message.
        console = Console(soft_wrap=True)
        if not branch:
            console.print("[red]--branch is required, e.g. --branch=feat/42-add-export[/red]")
            sys.exit(1)

        # A valid branch name cannot start with "/" or contain "..", so the
        # worktree path below stays inside worktrees/.
        valid = subprocess.run(
            ["git", "check-ref-format", "--branch", branch],
            capture_output=True,
            text=True,
            check=False,
        )
        if valid.returncode != 0:
            console.print(verbatim(f"Not a valid branch name: {branch}", "red"))
            sys.exit(1)

        root = _main_checkout()
        path = root / WORKTREES_DIR / branch

        try:
            subprocess.run(
                ["git", "fetch", "origin", "main"],
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip()
            console.print(verbatim(f"Warning: `git fetch origin main` failed: {stderr}", "yellow"))
            console.print("[yellow]Branching from the last fetched origin/main.[/yellow]")

        try:
            subprocess.run(
                ["git", "worktree", "add", "--no-track", "-b", branch, str(path), "origin/main"],
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            console.print(verbatim(f"git worktree add failed: {(e.stderr or '').strip()}", "red"))
            sys.exit(1)
        console.print(verbatim(f"Created {path} on {branch}, from origin/main.", "green"))

        env = {key: value for key, value in os.environ.items() if key != "VIRTUAL_ENV"}
        # base.py defaults UV_CACHE_DIR to a relative path. Resolved here, before
        # uv runs in the worktree, it keeps pointing at this checkout's cache
        # instead of a new, empty one inside the worktree.
        if "UV_CACHE_DIR" in env:
            env["UV_CACHE_DIR"] = str(Path(env["UV_CACHE_DIR"]).resolve())
        try:
            run_streamed(["uv", "sync", "--all-extras", "--dev"], env=env, cwd=path)
        except subprocess.CalledProcessError:
            console.print("[red]uv sync failed. The worktree exists; to retry, run in it:[/red]")
            console.print("  uv sync --all-extras --dev")
            sys.exit(1)

        console.print()
        console.print("[bold]Work there through uv run, which uses the worktree's .venv:[/bold]")
        console.print(verbatim(f"  cd {path}"))
        console.print("  uv run doit check")
        console.print(
            "[dim]Never pass --active: it installs the worktree into the main .venv.[/dim]"
        )
        console.print(
            "[bold]Merge its PR from the main checkout, which removes the worktree:[/bold]"
        )
        console.print(verbatim(f"  cd {root}"))
        console.print("  uv run doit pr_merge --pr=<number>")
        console.print("[bold]To remove it without merging:[/bold]")
        console.print(verbatim(f"  git worktree remove {path}"))

    return {
        "actions": [create_worktree],
        "params": [
            {
                "name": "branch",
                "long": "branch",
                "default": None,
                "help": "Branch to create, e.g. feat/42-add-export",
            },
        ],
        "title": title_with_actions,
    }
