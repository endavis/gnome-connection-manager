"""Tests for the CodeQL GitHub Actions workflow configuration.

These tests are structural asserts on the parsed YAML. They do not execute the
workflow -- they only verify its shape. The central regression guard is the
summary job name: it must be exactly ``CodeQL`` (case-sensitive) because the
main-branch ruleset requires a check-run named ``CodeQL``. Renaming that job
will stop PRs from merging. See issue #431 for context (the migration from
GitHub's "default setup" to this advanced workflow file).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

WORKFLOW_PATH = Path(__file__).parent.parent / ".github" / "workflows" / "codeql.yml"


def _load_workflow() -> dict[Any, Any]:
    """Load and parse the CodeQL workflow YAML.

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


def _analyze_steps() -> list[dict[str, Any]]:
    """Return the list of steps in the ``analyze`` job."""
    workflow = _load_workflow()
    job = workflow["jobs"]["analyze"]
    steps: list[dict[str, Any]] = job["steps"]
    return steps


class TestWorkflowFile:
    """The workflow file exists and parses as YAML."""

    def test_workflow_file_exists(self) -> None:
        """The CodeQL workflow YAML file should exist."""
        assert WORKFLOW_PATH.exists(), f"Workflow not found: {WORKFLOW_PATH}"

    def test_workflow_parses_as_yaml(self) -> None:
        """The workflow file should be valid YAML with a jobs dict."""
        workflow = _load_workflow()
        assert isinstance(workflow, dict)
        assert "jobs" in workflow
        assert isinstance(workflow["jobs"], dict)

    def test_workflow_name_is_codeql(self) -> None:
        """Top-level workflow name should be ``CodeQL``."""
        workflow = _load_workflow()
        assert workflow.get("name") == "CodeQL"


class TestTriggers:
    """Triggers: push to main, PR to main, and a weekly schedule."""

    def test_push_triggers_on_main(self) -> None:
        """Workflow should trigger on push to ``main``.

        PyYAML parses the YAML boolean key ``on`` as ``True``, so we access
        the triggers via the ``True`` key (or ``"on"`` if quoted). Support
        both so the test is resilient to how the file was written.
        """
        workflow = _load_workflow()
        triggers = workflow.get("on") or workflow.get(True)
        assert triggers is not None, "workflow has no triggers block"
        push = triggers["push"]
        assert push["branches"] == ["main"]

    def test_pull_request_triggers_on_main(self) -> None:
        """Workflow should trigger on pull_request targeting ``main``."""
        workflow = _load_workflow()
        triggers = workflow.get("on") or workflow.get(True)
        assert triggers is not None
        pr = triggers["pull_request"]
        assert pr["branches"] == ["main"]

    def test_has_weekly_schedule(self) -> None:
        """Workflow should run on a weekly cron schedule."""
        workflow = _load_workflow()
        triggers = workflow.get("on") or workflow.get(True)
        assert triggers is not None
        schedule = triggers["schedule"]
        assert isinstance(schedule, list) and len(schedule) >= 1
        # Just assert there is a cron entry -- the exact minute/hour is
        # operational detail and can shift if it collides with other workflows.
        assert "cron" in schedule[0]
        assert isinstance(schedule[0]["cron"], str)


class TestPermissions:
    """Top-level permissions match CodeQL's documented minimum."""

    def test_permissions_contents_read(self) -> None:
        """``contents: read`` is the baseline read permission."""
        workflow = _load_workflow()
        permissions = workflow["permissions"]
        assert permissions["contents"] == "read"

    def test_permissions_security_events_write(self) -> None:
        """``security-events: write`` lets CodeQL upload SARIF results."""
        workflow = _load_workflow()
        permissions = workflow["permissions"]
        assert permissions["security-events"] == "write"

    def test_permissions_actions_read(self) -> None:
        """``actions: read`` is required for the Actions language scanner."""
        workflow = _load_workflow()
        permissions = workflow["permissions"]
        assert permissions["actions"] == "read"


class TestConcurrency:
    """Concurrency group cancels stale PR pushes."""

    def test_concurrency_group_keyed_on_ref(self) -> None:
        """Group should include ``github.head_ref || github.ref`` so each PR
        and each branch has its own lane."""
        workflow = _load_workflow()
        concurrency = workflow["concurrency"]
        group = concurrency["group"]
        assert "github.head_ref" in group
        assert "github.ref" in group

    def test_concurrency_cancel_in_progress(self) -> None:
        """``cancel-in-progress: true`` so stale runs are superseded."""
        workflow = _load_workflow()
        concurrency = workflow["concurrency"]
        assert concurrency["cancel-in-progress"] is True


class TestAnalyzeJob:
    """The ``analyze`` job runs the actual CodeQL scan."""

    def test_analyze_job_exists(self) -> None:
        """Workflow should define the ``analyze`` job."""
        workflow = _load_workflow()
        assert "analyze" in workflow["jobs"]

    def test_analyze_matrix_languages_exact(self) -> None:
        """Matrix languages must be exactly ``actions`` and ``python``.

        Expanding the language set is out of scope for #431 and requires a
        separate decision -- this test guards against accidental drift.
        """
        workflow = _load_workflow()
        job = workflow["jobs"]["analyze"]
        matrix = job["strategy"]["matrix"]
        assert sorted(matrix["language"]) == ["actions", "python"]

    def test_analyze_matrix_fail_fast_false(self) -> None:
        """fail-fast: false so one language failing doesn't mask the other."""
        workflow = _load_workflow()
        job = workflow["jobs"]["analyze"]
        assert job["strategy"]["fail-fast"] is False

    def test_analyze_pins_checkout_to_a_sha(self) -> None:
        """``actions/checkout`` must be pinned to a commit SHA.

        The exact major version is intentionally not asserted. Dependabot bumps
        ``actions/checkout`` routinely; pinning this test to a specific number
        turns every such bump into a false CI failure (see #625). The repo
        convention this guards is that the action is pinned to a version tag,
        not a floating ref/branch.
        """
        steps = _analyze_steps()
        checkout_steps = [s for s in steps if s.get("uses", "").startswith("actions/checkout@")]
        assert checkout_steps, "expected an actions/checkout step"
        uses = checkout_steps[0]["uses"]
        assert re.fullmatch(r"actions/checkout@[0-9a-f]{40}", uses), (
            f"expected actions/checkout pinned to a commit SHA, got {uses!r}"
        )

    def test_analyze_pins_codeql_init_to_a_sha(self) -> None:
        """``github/codeql-action/init`` must be pinned to a commit SHA.

        The exact major version is intentionally not asserted. Dependabot bumps
        ``github/codeql-action`` routinely; pinning this test to a specific
        number turns every such bump into a false CI failure (see #626). The
        SHA-pinning superseded major-tag pinning in #695. The general rule is
        enforced by tests/test_workflow_action_pinning.py; this asserts only
        that the right action is the one pinned.
        """
        steps = _analyze_steps()
        init_steps = [
            s for s in steps if s.get("uses", "").startswith("github/codeql-action/init@")
        ]
        assert init_steps, "expected a github/codeql-action/init step"
        uses = init_steps[0]["uses"]
        assert re.fullmatch(r"github/codeql-action/init@[0-9a-f]{40}", uses), (
            f"expected github/codeql-action/init pinned to a commit SHA, got {uses!r}"
        )

    def test_analyze_pins_codeql_analyze_to_a_sha(self) -> None:
        """``github/codeql-action/analyze`` must be pinned to a commit SHA.

        See ``test_analyze_pins_codeql_init_to_a_sha`` for the rationale
        (#626): the exact major version is intentionally not asserted so routine
        dependabot bumps don't turn into false CI failures.
        """
        steps = _analyze_steps()
        analyze_steps = [
            s for s in steps if s.get("uses", "").startswith("github/codeql-action/analyze@")
        ]
        assert analyze_steps, "expected a github/codeql-action/analyze step"
        uses = analyze_steps[0]["uses"]
        assert re.fullmatch(r"github/codeql-action/analyze@[0-9a-f]{40}", uses), (
            f"expected github/codeql-action/analyze pinned to a commit SHA, got {uses!r}"
        )

    def test_analyze_init_passes_matrix_language(self) -> None:
        """The init step must receive the matrix language via ``with.languages``."""
        steps = _analyze_steps()
        init_step = next(
            s for s in steps if s.get("uses", "").startswith("github/codeql-action/init@")
        )
        assert init_step["with"]["languages"] == "${{ matrix.language }}"


class TestSummaryJob:
    """The ``CodeQL`` summary job is the check-run the ruleset requires.

    This section is the core regression guard for issue #431: the name of the
    summary job must be exactly ``CodeQL``, case-sensitive, or branch
    protection will no longer match a required status check and PRs will be
    permanently blocked.
    """

    def test_summary_job_key_is_codeql_exact(self) -> None:
        """The summary job key must be the exact string ``CodeQL``.

        This is the contract with the main-branch ruleset. Do NOT rename.
        """
        workflow = _load_workflow()
        assert "CodeQL" in workflow["jobs"], (
            "summary job must be named exactly 'CodeQL' (case-sensitive) -- "
            "this is the required check-run name in the main-branch ruleset"
        )

    def test_summary_job_explicit_name_is_codeql(self) -> None:
        """The job's explicit ``name:`` field should also be ``CodeQL``.

        GitHub uses the ``name`` field for the displayed check-run when set,
        so both the job key and its ``name`` must align.
        """
        workflow = _load_workflow()
        summary = workflow["jobs"]["CodeQL"]
        assert summary.get("name") == "CodeQL"

    def test_summary_job_needs_analyze(self) -> None:
        """Summary job must depend on ``analyze`` so it reflects the real result."""
        workflow = _load_workflow()
        summary = workflow["jobs"]["CodeQL"]
        assert summary["needs"] == ["analyze"]

    def test_summary_job_if_always(self) -> None:
        """``if: always()`` ensures the summary job runs and emits a check-run
        even when the analyze matrix fails -- otherwise a failed scan would
        leave the required check in a ``waiting`` state forever."""
        workflow = _load_workflow()
        summary = workflow["jobs"]["CodeQL"]
        assert summary.get("if") == "always()"

    def test_summary_job_fails_when_analyze_fails(self) -> None:
        """The summary step must exit non-zero when any matrix language failed.

        The guard we care about is that the step inspects
        ``needs.analyze.result`` somewhere in its definition and exits
        non-zero on a non-success result. The idiomatic secure pattern is to
        surface the expression via ``env:`` (so the shell never interpolates
        ``${{ ... }}`` directly) and read it as a plain shell variable in
        ``run:``. Accept either location so the test enforces the contract
        without locking in one scripting style.
        """
        workflow = _load_workflow()
        summary = workflow["jobs"]["CodeQL"]
        steps = summary["steps"]

        # Combine everything we might want to inspect: env values and run bodies.
        run_bodies = [step.get("run", "") for step in steps]
        env_values: list[str] = []
        for step in steps:
            env_map = step.get("env", {})
            if isinstance(env_map, dict):
                env_values.extend(str(v) for v in env_map.values())

        searchable = "\n".join(run_bodies + env_values)

        assert "needs.analyze.result" in searchable, (
            "summary job must reference needs.analyze.result (directly in run "
            "or via env) so it exits non-zero when the matrix fails"
        )

        combined_runs = "\n".join(run_bodies)
        assert "exit 1" in combined_runs, (
            "summary job must explicitly exit non-zero on failure so the "
            "check-run turns red instead of green"
        )
