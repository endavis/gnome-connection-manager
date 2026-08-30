"""Installation-related doit tasks."""

from typing import Any

from doit.tools import title_with_actions

from .install_tools import create_install_task

_DIRENV_POST_INSTALL_MESSAGE = (
    "\nIMPORTANT: Add direnv hook to your shell:\n"
    "  Bash: echo 'eval \"$(direnv hook bash)\"'\n"
    "  Zsh:  echo 'eval \"$(direnv hook zsh)\"'"
)


def task_install() -> dict[str, Any]:
    """Install package with dependencies."""
    return {
        "actions": [
            "uv sync",
        ],
        "title": title_with_actions,
    }


def task_install_dev() -> dict[str, Any]:
    """Install package with dev dependencies."""
    return {
        "actions": [
            "uv sync --all-extras --dev",
        ],
        "title": title_with_actions,
    }


def task_install_gh() -> dict[str, Any]:
    """Install GitHub CLI for repository operations."""
    return create_install_task(
        name="gh",
        repo="cli/cli",
        asset_patterns={},
        url_template="https://github.com/cli/cli/releases/download/v{version}/gh_{version}_{os}_{arch}.tar.gz",
        extract_binaries=["gh"],
        version_cmd=["gh", "--version"],
        prefer_brew=False,
    )


def task_install_direnv() -> dict[str, Any]:
    """Install direnv for automatic environment loading."""
    return create_install_task(
        name="direnv",
        repo="direnv/direnv",
        asset_patterns={"linux": "direnv.linux-amd64"},
        version_cmd=["direnv", "--version"],
        post_install_message=_DIRENV_POST_INSTALL_MESSAGE,
    )
