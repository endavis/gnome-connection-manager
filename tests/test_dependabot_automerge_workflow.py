"""Tests for the dependabot auto-merge GitHub Actions workflow configuration.

These tests are structural asserts on the parsed YAML. They do not execute the
workflow — they only verify its shape. The most important guarantee here is the
step ordering inside the ``enable-automerge`` job (see issue #423): the
``ready-to-merge`` label must be applied *before* ``gh pr merge --auto`` is
invoked so that a failure of the merge call cannot skip the label.

Issue #424 split the blocked-label handler out into a sibling workflow
(``dependabot-blocked-label.yml``) so this workflow no longer fires on
``labeled`` events. The ``TestOnTriggers`` and ``TestConcurrency`` classes
below guard that split.

Issue #428 added a preceding ``Generate App token`` step to the
``enable-automerge`` job. Applying the ``ready-to-merge`` label with a GitHub
App token (instead of the workflow's ``GITHUB_TOKEN``) is what allows the
downstream ``Merge Gate`` workflow to re-run on the ``labeled`` event —
``GITHUB_TOKEN`` is prohibited from triggering further workflow runs to
prevent recursion. The ``TestAppTokenStep`` class and several assertions in
``TestEnableAutomergeStepOrdering`` and ``TestStickyCommentStep`` guard that
wiring.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

WORKFLOW_PATH = Path(__file__).parent.parent / ".github" / "workflows" / "dependabot-automerge.yml"


def _load_workflow() -> dict[Any, Any]:
    """Load and parse the dependabot auto-merge workflow YAML.

    Return type is ``dict[Any, Any]`` (not ``dict[str, Any]``) because
    PyYAML parses the ``on`` key as the boolean ``True`` (YAML 1.1 alias).
    """
    # Bind to an annotated local first: yaml.safe_load returns Any,
    # and returning Any from a typed function trips warn_return_any.
    data: dict[Any, Any] = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    return data


def _enable_automerge_steps() -> list[dict[str, Any]]:
    """Return the list of steps in the ``enable-automerge`` job."""
    workflow = _load_workflow()
    job = workflow["jobs"]["enable-automerge"]
    steps: list[dict[str, Any]] = job["steps"]
    return steps


class TestDependabotAutomergeWorkflowExists:
    """The workflow file exists and parses as YAML."""

    def test_workflow_file_exists(self) -> None:
        """The dependabot auto-merge workflow YAML file should exist."""
        assert WORKFLOW_PATH.exists(), f"Workflow not found: {WORKFLOW_PATH}"

    def test_workflow_parses_as_yaml(self) -> None:
        """The workflow file should be valid YAML."""
        workflow = _load_workflow()
        assert isinstance(workflow, dict)
        assert "jobs" in workflow


class TestEnableAutomergeJobShape:
    """The ``enable-automerge`` job has the expected top-level shape."""

    def test_enable_automerge_job_exists(self) -> None:
        """Workflow should define the ``enable-automerge`` job."""
        workflow = _load_workflow()
        assert "enable-automerge" in workflow["jobs"]

    def test_enable_automerge_needs_evaluate(self) -> None:
        """``enable-automerge`` must depend on the ``evaluate`` job."""
        workflow = _load_workflow()
        job = workflow["jobs"]["enable-automerge"]
        assert job["needs"] == "evaluate"

    def test_enable_automerge_qualifies_guard(self) -> None:
        """The job should only run when ``evaluate`` reports ``qualifies == 'true'``."""
        workflow = _load_workflow()
        job = workflow["jobs"]["enable-automerge"]
        assert job["if"] == "needs.evaluate.outputs.qualifies == 'true'"

    def test_enable_automerge_job_does_not_set_gh_token_globally(self) -> None:
        """Regression guard for issue #428.

        The job-level ``env.GH_TOKEN`` was dropped in favour of per-step
        ``GH_TOKEN`` so the App-token-vs-``GITHUB_TOKEN`` distinction is
        explicit on each step instead of being shadowed by a job default.
        A future refactor that re-introduces a job-level ``GH_TOKEN`` would
        silently apply ``GITHUB_TOKEN`` to the label step again and reproduce
        the bug this issue fixes.
        """
        workflow = _load_workflow()
        job = workflow["jobs"]["enable-automerge"]
        job_env = job.get("env", {})
        assert "GH_TOKEN" not in job_env, (
            "enable-automerge must not set GH_TOKEN at the job level; "
            "set it per-step so the App-token vs GITHUB_TOKEN choice is explicit."
        )


class TestAppTokenStep:
    """Regression guard for issue #428.

    The first step in ``enable-automerge`` generates a GitHub App token when
    the App is configured. The label step then uses that token (with
    ``GITHUB_TOKEN`` fallback) so the label event is attributed to the App
    and the Merge Gate workflow re-runs. Removing or mis-wiring this step
    would reintroduce the ``GITHUB_TOKEN`` loop-prevention gap where
    Dependabot PRs get stuck with a stale ``require-label: FAILURE`` check.
    """

    def test_first_step_generates_app_token(self) -> None:
        """Step 0 must be the App-token generation step."""
        steps = _enable_automerge_steps()
        assert steps[0]["name"] == "Generate App token"

    def test_first_step_has_app_token_id(self) -> None:
        """The App-token step must have ``id: app-token`` so later steps and
        the sticky comment can reference ``steps.app-token.outputs.token``."""
        steps = _enable_automerge_steps()
        assert steps[0].get("id") == "app-token"

    def test_first_step_uses_create_github_app_token_v3(self) -> None:
        """The App-token step must use ``actions/create-github-app-token@v3``.

        Pinning to ``@v3`` (not ``@v1`` or an older major) matches the
        documented example in ``.github/CONTRIBUTING.md``; a drift between
        the two would confuse maintainers setting up the App for the first
        time.
        """
        steps = _enable_automerge_steps()
        assert steps[0]["uses"].startswith("actions/create-github-app-token@")

    def test_app_token_conditional_on_release_app_id(self) -> None:
        """The App-token step must be guarded by ``if: ${{ vars.RELEASE_APP_ID != '' }}``.

        The fallback path through ``GITHUB_TOKEN`` is only safe because this
        guard lets the step no-op cleanly when the App is not configured.
        Removing the guard would fail the whole job in repositories that
        haven't set up the App — a silent regression.
        """
        steps = _enable_automerge_steps()
        assert steps[0].get("if") == "${{ vars.RELEASE_APP_ID != '' }}"

    def test_app_token_inputs_reference_vars_and_secrets(self) -> None:
        """Inputs must reference ``vars.RELEASE_APP_ID`` and ``secrets.RELEASE_APP_PRIVATE_KEY``.

        ``RELEASE_APP_ID`` is a repo Variable (per ``.github/CONTRIBUTING.md``),
        not a Secret. Wiring it as ``secrets.RELEASE_APP_ID`` would silently
        produce an empty string at runtime and cause a confusing failure.
        """
        steps = _enable_automerge_steps()
        with_block = steps[0].get("with", {})
        assert with_block.get("app-id") == "${{ vars.RELEASE_APP_ID }}"
        assert with_block.get("private-key") == "${{ secrets.RELEASE_APP_PRIVATE_KEY }}"


class TestEnableAutomergeStepOrdering:
    """Regression guard for issue #423 (and the issue #428 renumbering).

    The label must be applied before the auto-merge call so a merge failure
    cannot skip the label. The sticky comment must run last and use
    ``if: always()`` so it posts on both success and failure. After issue
    #428, the App-token step is inserted at index 0 and every other step
    shifts by one.
    """

    def test_has_four_steps(self) -> None:
        """``enable-automerge`` should have exactly four steps after #428.

        The App-token step (index 0) was added ahead of the existing three
        steps (label, auto-merge, sticky comment).
        """
        steps = _enable_automerge_steps()
        assert len(steps) == 4, f"expected 4 steps, got {len(steps)}: {steps}"

    def test_second_step_is_label(self) -> None:
        """The label step must run second (right after the App-token step).

        This is the core regression guard for issue #423 — if the merge call
        is reordered to run before the label, a merge failure will skip the
        label and the Merge Gate will stay red forever. After #428 the label
        step moved from index 0 to index 1 (behind the App-token generator).
        """
        steps = _enable_automerge_steps()
        assert steps[1]["name"] == "Add ready-to-merge label"

    def test_label_step_adds_ready_to_merge(self) -> None:
        """The label step should add the ``ready-to-merge`` label via ``gh pr edit``."""
        steps = _enable_automerge_steps()
        label_step = steps[1]
        assert "--add-label ready-to-merge" in label_step["run"]

    def test_label_step_token_uses_app_token_with_fallback(self) -> None:
        """Core regression guard for issue #428.

        The label step's ``GH_TOKEN`` must resolve to the App token when the
        App is configured, and fall back to ``GITHUB_TOKEN`` only when it is
        not. A refactor that hard-codes ``secrets.GITHUB_TOKEN`` here would
        reintroduce the ``GITHUB_TOKEN`` loop-prevention gap: labels applied
        by ``GITHUB_TOKEN`` do not trigger downstream workflows, so the
        Merge Gate would not re-run on the ``labeled`` event.
        """
        steps = _enable_automerge_steps()
        label_env = steps[1].get("env", {})
        assert label_env.get("GH_TOKEN") == (
            "${{ steps.app-token.outputs.token || secrets.GITHUB_TOKEN }}"
        ), (
            "label step GH_TOKEN must prefer the App token with a "
            "GITHUB_TOKEN fallback; see issue #428."
        )

    def test_third_step_is_enable_automerge(self) -> None:
        """The auto-merge call runs third, after the label is already applied."""
        steps = _enable_automerge_steps()
        assert steps[2]["name"] == "Enable auto-merge (squash)"

    def test_enable_automerge_step_has_id(self) -> None:
        """The merge step needs ``id: automerge`` so the comment step can read its outcome."""
        steps = _enable_automerge_steps()
        assert steps[2].get("id") == "automerge"

    def test_enable_automerge_step_uses_squash(self) -> None:
        """The merge step should use the squash strategy with ``--auto``."""
        steps = _enable_automerge_steps()
        merge_step = steps[2]
        assert "gh pr merge --auto --squash" in merge_step["run"]

    def test_enable_automerge_step_uses_github_token(self) -> None:
        """The merge step should use ``GITHUB_TOKEN`` (not the App token).

        The auto-merge call does not need the App token — it only enables
        GitHub's native auto-merge flag on the PR and does not trigger any
        downstream event. Passing the App token here would only consume App
        rate limit with no benefit.
        """
        steps = _enable_automerge_steps()
        merge_env = steps[2].get("env", {})
        assert merge_env.get("GH_TOKEN") == "${{ secrets.GITHUB_TOKEN }}"

    def test_fourth_step_is_sticky_comment(self) -> None:
        """The sticky status comment runs last."""
        steps = _enable_automerge_steps()
        assert steps[3]["name"] == "Post sticky status comment"


class TestStickyCommentStep:
    """The sticky comment step is outcome-aware and always runs."""

    def test_sticky_comment_uses_always(self) -> None:
        """``if: always()`` ensures the comment runs even when the merge step fails."""
        steps = _enable_automerge_steps()
        assert steps[3].get("if") == "always()"

    def test_sticky_comment_uses_github_script(self) -> None:
        """The sticky comment step should use ``actions/github-script``."""
        steps = _enable_automerge_steps()
        assert steps[3]["uses"].startswith("actions/github-script@")

    def test_sticky_comment_exposes_automerge_outcome(self) -> None:
        """The sticky comment step must expose ``AUTOMERGE_OUTCOME`` via ``env``."""
        steps = _enable_automerge_steps()
        env = steps[3].get("env", {})
        assert env.get("AUTOMERGE_OUTCOME") == "${{ steps.automerge.outcome }}"

    def test_sticky_comment_exposes_app_token_configured(self) -> None:
        """Regression guard for issue #428.

        The sticky comment step must expose ``APP_TOKEN_CONFIGURED`` so the
        inline script can distinguish the "App not configured → Merge Gate
        will not re-run" case from the ordinary "merge call failed" case.
        Without this flag the user would get a generic failure message and
        would not know to remove and re-add the label manually.
        """
        steps = _enable_automerge_steps()
        env = steps[3].get("env", {})
        assert env.get("APP_TOKEN_CONFIGURED") == "${{ steps.app-token.outputs.token != '' }}"

    def test_sticky_comment_branches_on_outcome(self) -> None:
        """The inline script should branch on ``AUTOMERGE_OUTCOME``.

        Branching lets the script emit either the success copy or the
        failure copy depending on whether the merge call succeeded.
        """
        steps = _enable_automerge_steps()
        script: str = steps[3]["with"]["script"]
        assert "AUTOMERGE_OUTCOME" in script, (
            "sticky comment script must reference AUTOMERGE_OUTCOME so it can "
            "produce a success vs failure body"
        )

    def test_sticky_comment_branches_on_app_token_configured(self) -> None:
        """Regression guard for issue #428.

        The inline script must reference ``APP_TOKEN_CONFIGURED`` so it can
        emit the third-state message (App not configured, Merge Gate will
        not re-run, manual relabel required). Dropping this branch would
        leave the user guessing about the correct fallback path.
        """
        steps = _enable_automerge_steps()
        script: str = steps[3]["with"]["script"]
        assert "APP_TOKEN_CONFIGURED" in script, (
            "sticky comment script must reference APP_TOKEN_CONFIGURED so it "
            "can emit the App-not-configured copy (issue #428)"
        )

    def test_sticky_comment_retains_dedupe_marker(self) -> None:
        """The sticky-comment dedupe marker must survive the refactor."""
        steps = _enable_automerge_steps()
        script: str = steps[3]["with"]["script"]
        assert "<!-- dependabot-automerge:status -->" in script

    def test_sticky_comment_deletes_prior_bot_marker_comments(self) -> None:
        """The dedupe logic (list + delete prior marker comments) must remain."""
        steps = _enable_automerge_steps()
        script: str = steps[3]["with"]["script"]
        assert "deleteComment" in script
        assert "listComments" in script


class TestOnTriggers:
    """Trigger configuration: the ``labeled`` event is handled elsewhere.

    Issue #424 moved label-driven handling to ``dependabot-blocked-label.yml``.
    Leaving ``labeled`` in the trigger list here would re-introduce the
    duplicate-run problem on dependabot PRs (each auto-applied label fires a
    separate workflow run).
    """

    def test_labeled_not_in_pull_request_target_types(self) -> None:
        """The ``labeled`` event type must NOT appear in ``pull_request_target.types``.

        This is the core regression guard for issue #424.
        """
        workflow = _load_workflow()
        triggers = workflow.get("on") or workflow.get(True)
        assert triggers is not None, "workflow has no triggers block"
        types = triggers["pull_request_target"]["types"]
        assert "labeled" not in types, (
            f"'labeled' must not be in pull_request_target.types; got {types}. "
            "Label-driven handling is in dependabot-blocked-label.yml (issue #424)."
        )

    def test_pull_request_target_types_cover_core_lifecycle(self) -> None:
        """The PR trigger must still cover the core lifecycle events so the
        main evaluate/enable-automerge flow still runs on every open/sync."""
        workflow = _load_workflow()
        triggers = workflow.get("on") or workflow.get(True)
        assert triggers is not None
        types = triggers["pull_request_target"]["types"]
        for required in ("opened", "reopened", "synchronize", "ready_for_review"):
            assert required in types, f"pull_request_target.types missing '{required}': {types}"

    def test_schedule_and_workflow_dispatch_absent(self) -> None:
        """``schedule`` and ``workflow_dispatch`` must not be triggers on this
        workflow.

        These triggers previously drove a ``request-rebase`` job that posted
        ``@dependabot rebase`` on stale PRs. That job was removed in #496
        because dependabot's command parser rejects all GitHub App actors
        (upstream issue dependabot/dependabot-core#9147), so the comment
        could never be accepted. The remaining jobs (``evaluate``,
        ``enable-automerge``, ``comment-skip``) all gate on
        ``github.event_name == 'pull_request_target'``, so a schedule or
        workflow_dispatch tick would just spin up an empty workflow run.
        """
        workflow = _load_workflow()
        triggers = workflow.get("on") or workflow.get(True)
        assert triggers is not None
        assert "schedule" not in triggers
        assert "workflow_dispatch" not in triggers


class TestConcurrency:
    """Workflow-level concurrency block dedupes in-flight runs per PR.

    The concurrency block is only safe to add after the ``labeled`` trigger
    split in issue #424: prior to the split, a labeled event arriving shortly
    after an ``opened`` event would cancel the in-flight ``evaluate`` job
    mid-run. With label events routed to ``dependabot-blocked-label.yml``,
    cancelling stale runs on this workflow is safe.
    """

    def test_concurrency_block_exists(self) -> None:
        """The workflow must declare a top-level ``concurrency`` block."""
        workflow = _load_workflow()
        assert "concurrency" in workflow, "workflow must declare a concurrency block"

    def test_concurrency_group_keyed_on_pr_number_or_ref(self) -> None:
        """The group key must reference ``pull_request.number`` and ``github.ref``.

        ``pull_request.number`` isolates PR runs from each other.
        ``github.ref`` remains in the expression as a defensive fallback
        for any future trigger that might lack PR context; today every
        triggered event is ``pull_request_target`` and always populates
        ``pull_request.number``.
        """
        workflow = _load_workflow()
        group: str = workflow["concurrency"]["group"]
        assert "pull_request.number" in group or "github.event.pull_request.number" in group
        assert "github.ref" in group

    def test_concurrency_cancel_in_progress(self) -> None:
        """``cancel-in-progress: true`` supersedes stale runs on a new PR push."""
        workflow = _load_workflow()
        assert workflow["concurrency"]["cancel-in-progress"] is True
