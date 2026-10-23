"""Tests for the dependabot configuration in ``.github/dependabot.yml``.

These tests are structural asserts on the parsed YAML. They do not run
dependabot -- they only verify the config's shape.

The guarantee that matters here is the ``codeql-action`` group (issue #799).
``github/codeql-action/init`` and ``github/codeql-action/analyze`` are two
separate dependencies to dependabot but a single unit to CodeQL: ``init``
writes a config file stamped with its own version, and ``analyze`` refuses to
load a config written by a different one::

    Loaded a configuration file for version '4.37.8', but running version '4.37.9'

Ungrouped, dependabot opens one PR per sub-action, each bumping only half the
pair. Both fail, and neither can be merged to unblock the other -- that is
exactly what happened to PRs #794 and #795. The group is what prevents it, so
its removal must be a CI failure rather than a silent return to split PRs.

The companion assert lives in ``tests/test_codeql_workflow.py``, which checks
that the two actions are in fact pinned to the same SHA today.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

CONFIG_PATH = Path(__file__).parent.parent / ".github" / "dependabot.yml"

# The two halves of the CodeQL action that must always bump together.
CODEQL_SUBACTIONS = ("github/codeql-action/init", "github/codeql-action/analyze")


def _load_config() -> dict[str, Any]:
    """Load and parse the dependabot config YAML.

    The explicit ``encoding="utf-8"`` is required for Windows, where the
    default ``locale.getpreferredencoding()`` is cp1252 and chokes on any
    non-ASCII content in the file (lesson from issue #430).
    """
    # Bind to an annotated local first: yaml.safe_load returns Any,
    # and returning Any from a typed function trips warn_return_any.
    data: dict[str, Any] = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    return data


def _github_actions_block() -> dict[str, Any]:
    """Return the ``github-actions`` ecosystem entry from ``updates``."""
    config = _load_config()
    updates: list[dict[str, Any]] = config["updates"]
    block = next(u for u in updates if u.get("package-ecosystem") == "github-actions")
    return block


def _glob_matches(pattern: str, name: str) -> bool:
    """Return True if a dependabot group glob matches a dependency name.

    Dependabot group patterns use ``*`` as the only wildcard and match the
    whole name. Everything else is escaped so a ``.`` in a pattern cannot
    silently behave as "any character".
    """
    escaped = re.escape(pattern).replace(r"\*", ".*")
    return re.fullmatch(escaped, name) is not None


class TestConfigFile:
    """The config file exists and parses as YAML."""

    def test_config_file_exists(self) -> None:
        """The dependabot config should exist."""
        assert CONFIG_PATH.exists(), f"Config not found: {CONFIG_PATH}"

    def test_config_parses_as_yaml(self) -> None:
        """The config should be valid YAML with a version and updates list."""
        config = _load_config()
        assert config["version"] == 2
        assert isinstance(config["updates"], list)

    def test_has_github_actions_ecosystem(self) -> None:
        """A ``github-actions`` ecosystem block must be configured."""
        assert _github_actions_block()["directory"] == "/"


class TestCodeqlActionGroup:
    """The CodeQL sub-actions must bump as one PR.

    This is the core regression guard for issue #799. Do NOT remove the group
    without also removing the reason it exists.
    """

    def test_github_actions_block_defines_groups(self) -> None:
        """The ``github-actions`` ecosystem must define at least one group."""
        groups = _github_actions_block().get("groups")
        assert isinstance(groups, dict) and groups, (
            "the github-actions ecosystem must define a 'groups' block -- "
            "without it dependabot splits codeql-action into failing PRs (#799)"
        )

    def test_both_codeql_subactions_land_in_one_group(self) -> None:
        """``init`` and ``analyze`` must be matched by the *same* group.

        Asserted behaviorally rather than by literal pattern string: any
        pattern that captures both sub-actions satisfies the invariant, so a
        reasonable rewording of the glob does not become a false failure.
        """
        groups: dict[str, Any] = _github_actions_block().get("groups", {})

        matching = [
            name
            for name, spec in groups.items()
            if all(
                any(_glob_matches(p, sub) for p in spec.get("patterns", []))
                for sub in CODEQL_SUBACTIONS
            )
        ]

        assert matching, (
            "no dependabot group matches both "
            f"{CODEQL_SUBACTIONS[0]} and {CODEQL_SUBACTIONS[1]}; they will be "
            "bumped in separate PRs and CodeQL will fail with 'Loaded a "
            "configuration file for version X, but running version Y' (#799)"
        )

    def test_no_group_splits_the_codeql_subactions(self) -> None:
        """No group may claim one sub-action without claiming the other.

        A group matching only ``init`` would pull it into a grouped PR and
        leave ``analyze`` in a lone PR -- reintroducing the exact split the
        group exists to prevent.
        """
        groups: dict[str, Any] = _github_actions_block().get("groups", {})

        for name, spec in groups.items():
            patterns = spec.get("patterns", [])
            matched = [s for s in CODEQL_SUBACTIONS if any(_glob_matches(p, s) for p in patterns)]
            assert len(matched) != 1, (
                f"dependabot group {name!r} matches {matched[0]} but not the "
                "other codeql-action sub-action; the pair must bump together (#799)"
            )
