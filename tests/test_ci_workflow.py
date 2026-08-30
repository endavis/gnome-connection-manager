"""Tests for the CI GitHub Actions workflow configuration.

These tests are structural asserts on the parsed YAML. They do not execute the
workflow -- they only verify its shape.

Scope is intentionally minimal: we guard the three invariants that matter for
issue #424:

1. ``labeled`` is NOT in the ``pull_request`` event type list. Keeping it
   there would cause every auto-applied label on a dependabot PR to spawn a
   duplicate CI run (the motivation for the split introduced in #424).
2. A workflow-level ``concurrency`` block exists with ``cancel-in-progress:
   true`` and a key that includes ``github.head_ref || github.ref``. This
   ensures a new push to a PR cancels the in-flight run on the prior commit.
3. The ``workflow_call`` trigger exposes a ``full_matrix`` boolean input
   (default ``false``) so the sibling ``ci-full-matrix.yml`` workflow can
   dispatch the full-matrix run via ``uses: ./.github/workflows/ci.yml``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

WORKFLOW_PATH = Path(__file__).parent.parent / ".github" / "workflows" / "ci.yml"


def _load_workflow() -> dict[Any, Any]:
    """Load and parse the CI workflow YAML.

    Return type is ``dict[Any, Any]`` (not ``dict[str, Any]``) because
    PyYAML parses the ``on`` key as the boolean ``True`` (YAML 1.1 alias).

    The explicit ``encoding="utf-8"`` is required for Windows, where the
    default ``locale.getpreferredencoding()`` is cp1252 and chokes on any
    non-ASCII content in the workflow file (lesson from issue #430).
    """
    # Bind to an annotated local first: yaml.safe_load returns Any,
    # and returning Any from a typed function trips warn_return_any.
    data: dict[Any, Any] = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    return data


class TestWorkflowFile:
    """The workflow file exists and parses as YAML."""

    def test_workflow_file_exists(self) -> None:
        """The CI workflow YAML file should exist."""
        assert WORKFLOW_PATH.exists(), f"Workflow not found: {WORKFLOW_PATH}"

    def test_workflow_parses_as_yaml(self) -> None:
        """The workflow file should be valid YAML with a jobs dict."""
        workflow = _load_workflow()
        assert isinstance(workflow, dict)
        assert "jobs" in workflow
        assert isinstance(workflow["jobs"], dict)

    def test_workflow_name(self) -> None:
        """The workflow name is ``CI`` -- the required check-run in branch
        protection and the name referenced by ``ci-full-matrix.yml``."""
        workflow = _load_workflow()
        assert workflow.get("name") == "CI"


class TestPullRequestTriggerHasNoLabeledType:
    """The main CI workflow should no longer fire on label events (issue #424).

    Label-driven full-matrix runs are handled by ``ci-full-matrix.yml``, which
    calls this workflow via ``workflow_call``. Leaving ``labeled`` in the
    trigger list here would re-introduce the duplicate-run problem.
    """

    def test_labeled_not_in_pull_request_types(self) -> None:
        """The ``labeled`` event type must NOT appear in ``pull_request.types``."""
        workflow = _load_workflow()
        triggers = workflow.get("on") or workflow.get(True)
        assert triggers is not None, "workflow has no triggers block"
        pr = triggers["pull_request"]
        types = pr["types"]
        assert "labeled" not in types, (
            f"'labeled' must not be in pull_request.types; got {types}. "
            "Label-driven runs are handled by ci-full-matrix.yml (issue #424)."
        )

    def test_pull_request_types_cover_core_lifecycle(self) -> None:
        """The PR trigger must still cover the core lifecycle events.

        We keep ``opened``, ``synchronize``, and ``reopened`` so that CI runs
        on every push and on reopened PRs. Removing any of these would leave
        a PR without CI coverage.
        """
        workflow = _load_workflow()
        triggers = workflow.get("on") or workflow.get(True)
        assert triggers is not None
        types = triggers["pull_request"]["types"]
        for required in ("opened", "synchronize", "reopened"):
            assert required in types, f"pull_request.types missing '{required}': {types}"


class TestConcurrency:
    """Workflow-level concurrency block cancels stale runs on new pushes."""

    def test_concurrency_block_exists(self) -> None:
        """The workflow must declare a top-level ``concurrency`` block."""
        workflow = _load_workflow()
        assert "concurrency" in workflow, "workflow must declare a concurrency block"

    def test_concurrency_group_keyed_on_ref(self) -> None:
        """The group key must reference ``head_ref || ref``.

        ``head_ref`` is only set for PR events and points at the PR's source
        branch; ``ref`` is the fallback for push/schedule/dispatch events.
        Using the pair gives each PR its own concurrency lane while still
        scoping main-branch runs to ``refs/heads/main``.
        """
        workflow = _load_workflow()
        group: str = workflow["concurrency"]["group"]
        assert "github.head_ref" in group
        assert "github.ref" in group

    def test_concurrency_cancel_in_progress(self) -> None:
        """``cancel-in-progress: true`` supersedes stale runs on a new push."""
        workflow = _load_workflow()
        assert workflow["concurrency"]["cancel-in-progress"] is True


# TestWorkflowCallInputs removed: it asserted that ci.yml exposes a full_matrix
# input for ci-full-matrix.yml to call. GCM has no matrix to run, that workflow was
# not adopted, and ci.yml no longer declares workflow_call at all (#127).
