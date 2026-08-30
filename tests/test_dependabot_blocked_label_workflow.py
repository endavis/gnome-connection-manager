"""Tests for the dependabot blocked-label GitHub Actions workflow configuration.

These tests are structural asserts on the parsed YAML. They do not execute the
workflow -- they only verify its shape. This workflow was split out from
``dependabot-automerge.yml`` in issue #424 so that the ``labeled`` trigger no
longer fires the main auto-merge workflow on every auto-applied dependabot
label (see the Context section of that issue's plan for the motivation).

The central regression guards here are:

1. The workflow triggers on ``pull_request_target: labeled`` only -- no other
   event types. Adding ``opened`` or ``synchronize`` would defeat the whole
   purpose of the split.
2. The ``handle-blocked-label`` job preserves the exact ``if:`` conditions and
   step sequence from the original job (disable auto-merge -> remove
   ``ready-to-merge`` label -> post sticky comment). The sticky-comment marker
   must survive intact so that the dedupe logic in ``dependabot-automerge.yml``
   and this workflow share a single comment slot.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

WORKFLOW_PATH = (
    Path(__file__).parent.parent / ".github" / "workflows" / "dependabot-blocked-label.yml"
)


def _load_workflow() -> dict[Any, Any]:
    """Load and parse the dependabot blocked-label workflow YAML.

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


def _handle_blocked_label_steps() -> list[dict[str, Any]]:
    """Return the list of steps in the ``handle-blocked-label`` job."""
    workflow = _load_workflow()
    job = workflow["jobs"]["handle-blocked-label"]
    steps: list[dict[str, Any]] = job["steps"]
    return steps


class TestWorkflowFile:
    """The workflow file exists and parses as YAML."""

    def test_workflow_file_exists(self) -> None:
        """The dependabot blocked-label workflow YAML file should exist."""
        assert WORKFLOW_PATH.exists(), f"Workflow not found: {WORKFLOW_PATH}"

    def test_workflow_parses_as_yaml(self) -> None:
        """The workflow file should be valid YAML with a jobs dict."""
        workflow = _load_workflow()
        assert isinstance(workflow, dict)
        assert "jobs" in workflow
        assert isinstance(workflow["jobs"], dict)

    def test_workflow_name(self) -> None:
        """The workflow name is the user-facing check-run label."""
        workflow = _load_workflow()
        assert workflow.get("name") == "Dependabot Blocked Label"


class TestTriggers:
    """Trigger configuration: ``labeled`` only, no other event types."""

    def test_only_trigger_is_pull_request_target(self) -> None:
        """The workflow should have exactly one trigger: ``pull_request_target``."""
        workflow = _load_workflow()
        triggers = workflow.get("on") or workflow.get(True)
        assert triggers is not None, "workflow has no triggers block"
        assert list(triggers.keys()) == ["pull_request_target"], (
            "workflow should trigger on pull_request_target only; other triggers "
            "would defeat the split from dependabot-automerge.yml (issue #424)"
        )

    def test_pull_request_target_types_is_labeled_only(self) -> None:
        """The only event type should be ``labeled``.

        This is the core regression guard for issue #424: the whole point of
        this workflow is to absorb the ``labeled`` event so the main
        auto-merge workflow no longer runs on every auto-applied label.
        """
        workflow = _load_workflow()
        triggers = workflow.get("on") or workflow.get(True)
        assert triggers is not None
        types = triggers["pull_request_target"]["types"]
        assert types == ["labeled"], f"expected types: [labeled], got {types}"


class TestPermissions:
    """Top-level permissions follow the principle of least privilege."""

    def test_permissions_pull_requests_write(self) -> None:
        """The job edits labels and toggles auto-merge, so it needs PR write access."""
        workflow = _load_workflow()
        assert workflow["permissions"]["pull-requests"] == "write"

    def test_permissions_contents_read(self) -> None:
        """``contents: read`` is the baseline; this workflow does not write to the repo.

        Notably we do NOT copy ``contents: write`` from the parent
        ``dependabot-automerge.yml``. That permission was there for the
        ``request-rebase`` job, which stays in the parent workflow. This
        workflow only needs to edit PR labels and comments.
        """
        workflow = _load_workflow()
        assert workflow["permissions"]["contents"] == "read"


class TestHandleBlockedLabelJob:
    """The ``handle-blocked-label`` job preserves the shape of the original job."""

    def test_job_exists(self) -> None:
        """Workflow should define the ``handle-blocked-label`` job."""
        workflow = _load_workflow()
        assert "handle-blocked-label" in workflow["jobs"]

    def test_job_name(self) -> None:
        """The user-facing job name should be ``Handle blocking label``."""
        workflow = _load_workflow()
        job = workflow["jobs"]["handle-blocked-label"]
        assert job["name"] == "Handle blocking label"

    def test_job_if_guards_dependabot_and_blocking_labels(self) -> None:
        """The ``if:`` guard must match the original from ``dependabot-automerge.yml``.

        The guard has four parts:

        1. ``github.event_name == 'pull_request_target'`` -- sanity check.
        2. ``github.event.action == 'labeled'`` -- explicit action filter.
        3. ``github.event.pull_request.user.login == 'dependabot[bot]'`` --
           only act on dependabot PRs.
        4. label name is ``automerge-blocked`` or ``do-not-merge``.

        Any of these going missing is a behavior change the test must catch.
        """
        workflow = _load_workflow()
        job = workflow["jobs"]["handle-blocked-label"]
        guard: str = job["if"]
        assert "github.event_name == 'pull_request_target'" in guard
        assert "github.event.action == 'labeled'" in guard
        assert "github.event.pull_request.user.login == 'dependabot[bot]'" in guard
        assert "github.event.label.name == 'automerge-blocked'" in guard
        assert "github.event.label.name == 'do-not-merge'" in guard

    def test_job_env_exposes_pr_number_and_label_name(self) -> None:
        """The job exposes ``PR_NUMBER`` and ``LABEL_NAME`` via ``env`` so the
        subsequent steps can read them as shell variables (the secure pattern
        that avoids direct ``${{ ... }}`` interpolation in ``run``).
        """
        workflow = _load_workflow()
        job = workflow["jobs"]["handle-blocked-label"]
        env = job["env"]
        assert env["PR_NUMBER"] == "${{ github.event.pull_request.number }}"
        assert env["LABEL_NAME"] == "${{ github.event.label.name }}"
        assert env["GH_TOKEN"] == "${{ secrets.GITHUB_TOKEN }}"


class TestHandleBlockedLabelSteps:
    """Step ordering mirrors the original job: disable -> unlabel -> comment."""

    def test_has_three_steps(self) -> None:
        """The job should have exactly three steps, matching the original."""
        steps = _handle_blocked_label_steps()
        assert len(steps) == 3, f"expected 3 steps, got {len(steps)}: {steps}"

    def test_first_step_disables_auto_merge(self) -> None:
        """Step 1 disables GitHub auto-merge via ``gh pr merge --disable-auto``."""
        steps = _handle_blocked_label_steps()
        assert steps[0]["name"] == "Disable auto-merge"
        assert "gh pr merge --disable-auto" in steps[0]["run"]

    def test_second_step_removes_ready_to_merge_label(self) -> None:
        """Step 2 removes the ``ready-to-merge`` label so the Merge Gate blocks the PR."""
        steps = _handle_blocked_label_steps()
        assert steps[1]["name"] == "Remove ready-to-merge label"
        assert "--remove-label ready-to-merge" in steps[1]["run"]

    def test_third_step_posts_sticky_blocked_comment(self) -> None:
        """Step 3 posts the sticky blocked comment via ``actions/github-script``."""
        steps = _handle_blocked_label_steps()
        assert steps[2]["name"] == "Post sticky blocked comment"
        assert steps[2]["uses"].startswith("actions/github-script@")

    def test_sticky_comment_retains_dedupe_marker(self) -> None:
        """The sticky-comment dedupe marker must match the parent workflow's marker
        so both workflows share a single comment slot on the PR."""
        steps = _handle_blocked_label_steps()
        script: str = steps[2]["with"]["script"]
        assert "<!-- dependabot-automerge:status -->" in script

    def test_sticky_comment_deletes_prior_bot_marker_comments(self) -> None:
        """The dedupe logic (list + delete prior marker comments) must remain."""
        steps = _handle_blocked_label_steps()
        script: str = steps[2]["with"]["script"]
        assert "deleteComment" in script
        assert "listComments" in script
