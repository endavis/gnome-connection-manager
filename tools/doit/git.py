"""Git-related doit tasks."""

from typing import Any

from doit.tools import title_with_actions

from .base import install_check_or_skip


def task_commit() -> dict[str, Any]:
    """Interactive commit with commitizen (ensures conventional commit format)."""
    return {
        "actions": [
            install_check_or_skip(
                "commitizen",
                "commitizen not installed. Run: uv sync",
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
                "commitizen not installed. Run: uv sync",
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
                "commitizen not installed. Run: uv sync",
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
