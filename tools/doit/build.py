"""Build and publish doit tasks."""

import os
from typing import Any

from doit.action import CmdAction
from doit.tools import title_with_actions


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
