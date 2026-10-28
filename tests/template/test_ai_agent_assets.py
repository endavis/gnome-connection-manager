"""Tests for AI agent workflow assets checked into the template."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from agent_roster import agent_is_present, present_agents, skip_if_absent

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_codex_workflow_skills_exist() -> None:
    """Codex workflow skills should be present in the repo skills directory."""
    skip_if_absent("codex")

    skill_paths = [
        REPO_ROOT / ".agents" / "skills" / "codex-review" / "SKILL.md",
        REPO_ROOT / ".agents" / "skills" / "codex-adversarial-review" / "SKILL.md",
        REPO_ROOT / ".agents" / "skills" / "implement-issue" / "SKILL.md",
    ]

    for skill_path in skill_paths:
        assert skill_path.exists(), f"Missing Codex skill: {skill_path}"


GH_RULES = REPO_ROOT / ".codex" / "rules" / "gh.rules"

# The exact rules in `.codex/rules/gh.rules`: the read-only `gh` subcommands a
# delegated Codex run uses, and nothing that writes (#980).
GH_ALLOW_RULES = (
    'prefix_rule(pattern=["gh", "pr", ["view", "diff", "checks", "list"]], decision="allow")',
    'prefix_rule(pattern=["gh", "issue", ["view", "list"]], decision="allow")',
)


def test_codex_gh_rules_allow_only_read_only_subcommands() -> None:
    """`.codex/rules/gh.rules` carries exactly the read-only allow rules.

    Without them a headless Codex session has no path to run `gh` with network
    access at all; with a broader rule (bare `["gh"]`) a delegated run could
    write to GitHub — see docs/development/ai/command-blocking.md#codex-cli (#980).
    """
    skip_if_absent("codex")

    assert GH_RULES.is_file(), f"missing Codex exec-policy rule: {GH_RULES}"
    rules = [
        line
        for line in GH_RULES.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    assert rules == list(GH_ALLOW_RULES)


@pytest.mark.parametrize(
    ("command", "allowed"),
    [
        ("gh pr view 1", True),
        ("gh pr diff", True),
        ("gh pr checks 1", True),
        ("gh issue view 1 --json comments", True),
        ("gh pr comment 1 --body x", False),
        ("gh api -X DELETE repos/o/r", False),
        ("gh pr merge 1", False),
    ],
)
def test_codex_gh_rules_parse_and_match(command: str, allowed: bool) -> None:
    """Codex itself parses the rule file and allows reads but not writes."""
    skip_if_absent("codex")
    codex = shutil.which("codex")
    if codex is None:
        pytest.skip("codex CLI not installed")

    result = subprocess.run(
        [codex, "execpolicy", "check", "--rules", str(GH_RULES), *command.split()],
        capture_output=True,
        text=True,
        check=True,
    )
    decision = json.loads(result.stdout).get("decision")
    assert (decision == "allow") is allowed, result.stdout


def test_multi_orchestrator_files_exist() -> None:
    """multi-* orchestrators exist for every host this project wires.

    Each orchestrator is a single shared skill, written once in `.agents/skills/`
    (read directly by Codex, Antigravity, and Copilot) and generated for Claude at
    `.claude/skills/` by `doit skills_sync` (#975). A project that keeps fewer
    hosts is checked against the hosts it kept (#690).
    """
    actions = ("plan", "review", "adversarial-review")
    paths: list[Path] = []
    if agent_is_present("claude"):
        paths += [REPO_ROOT / ".claude" / "skills" / f"multi-{a}" / "SKILL.md" for a in actions]
    if agent_is_present("codex") or agent_is_present("antigravity") or agent_is_present("copilot"):
        paths += [REPO_ROOT / ".agents" / "skills" / f"multi-{a}" / "SKILL.md" for a in actions]

    for path in paths:
        assert path.exists(), f"Missing multi-orchestrator file: {path}"


def test_self_action_grid_exists() -> None:
    """Every wired agent has its self-action files.

    Plan and implement are no longer per-agent self-action files — they are
    replaced by the single shared `implement-issue` skill (#976). The grid is
    built from the agents this project keeps rather than pinned at the
    template's roster (#690).
    """
    actions = ("review", "adversarial-review")
    # Where each host keeps its self-action files. Copilot uses .github/skills/
    # rather than .claude/skills/ — see tests/test_delegation_matrix.py
    # ::_expected_path for why.
    layouts = {
        "claude": lambda a: REPO_ROOT / ".claude" / "commands" / "claude" / f"{a}.md",
        "copilot": lambda a: REPO_ROOT / ".github" / "skills" / f"copilot-{a}" / "SKILL.md",
        "codex": lambda a: REPO_ROOT / ".agents" / "skills" / f"codex-{a}" / "SKILL.md",
        "antigravity": lambda a: REPO_ROOT / ".agents" / "skills" / f"antigravity-{a}" / "SKILL.md",
    }

    for agent in present_agents():
        for action in actions:
            path = layouts[agent](action)
            assert path.exists(), f"Missing self-action file: {path}"


def test_template_sync_exists_on_every_wired_surface() -> None:
    """`template-sync` is the entry point to the template upgrade, on every host.

    `.agents/skills/` is the source Codex, Antigravity and Copilot read; Claude
    reads `.claude/skills/`, generated from it byte for byte by `doit
    skills_sync` (#972). There is no `.copilot/commands/` copy because that
    path is never loaded — see `.copilot/README.md`.
    """
    paths: list[Path] = []
    if agent_is_present("claude"):
        paths.append(REPO_ROOT / ".claude" / "skills" / "template-sync" / "SKILL.md")
    if any(agent_is_present(a) for a in ("codex", "antigravity", "copilot")):
        paths.append(REPO_ROOT / ".agents" / "skills" / "template-sync" / "SKILL.md")

    for path in paths:
        assert path.exists(), f"Missing template-sync file: {path}"


def test_template_migrate_exists_on_every_wired_surface() -> None:
    """`template-migrate` plans an existing project's move onto the template.

    Same two-surface layout as `template-sync`, but this one is meant to be
    copied into a project that does not use the template yet — so the template
    is only its distribution point.
    """
    paths: list[Path] = []
    if agent_is_present("claude"):
        paths.append(REPO_ROOT / ".claude" / "skills" / "template-migrate" / "SKILL.md")
    if any(agent_is_present(a) for a in ("codex", "antigravity", "copilot")):
        paths.append(REPO_ROOT / ".agents" / "skills" / "template-migrate" / "SKILL.md")

    for path in paths:
        assert path.exists(), f"Missing template-migrate file: {path}"


def test_add_dependency_exists_on_every_wired_surface() -> None:
    """`add-dependency` walks an agent through a new dependency it cannot add itself.

    Same two-surface layout as `template-sync`. It ships to downstream projects,
    which is who adds dependencies, so it is not in `cleanup.SETUP_FILES` (#829).
    """
    paths: list[Path] = []
    if agent_is_present("claude"):
        paths.append(REPO_ROOT / ".claude" / "skills" / "add-dependency" / "SKILL.md")
    if any(agent_is_present(a) for a in ("codex", "antigravity", "copilot")):
        paths.append(REPO_ROOT / ".agents" / "skills" / "add-dependency" / "SKILL.md")

    for path in paths:
        assert path.exists(), f"Missing add-dependency file: {path}"


def test_mutation_triage_exists_on_every_wired_surface() -> None:
    """`mutation-triage` turns a mutmut survivor or an uncovered line into a behavior test.

    Same two-surface layout as `add-dependency` (#830): `doit mutate` and `doit
    coverage` are both informational, so nothing stops a survivor being declared
    equivalent with no reason, or a line staying uncovered forever. It ships to
    downstream projects, which is who runs `doit mutate`, so it is not in
    `cleanup.SETUP_FILES`.
    """
    paths: list[Path] = []
    if agent_is_present("claude"):
        paths.append(REPO_ROOT / ".claude" / "skills" / "mutation-triage" / "SKILL.md")
    if any(agent_is_present(a) for a in ("codex", "antigravity", "copilot")):
        paths.append(REPO_ROOT / ".agents" / "skills" / "mutation-triage" / "SKILL.md")

    for path in paths:
        assert path.exists(), f"Missing mutation-triage file: {path}"


def test_property_tests_exists_on_every_wired_surface() -> None:
    """`property-tests` walks an agent through picking and pinning a Hypothesis property.

    Same two-surface layout as `add-dependency`. It ships to downstream projects,
    which is who writes property tests, so it is not in `cleanup.SETUP_FILES` (#831).
    """
    paths: list[Path] = []
    if agent_is_present("claude"):
        paths.append(REPO_ROOT / ".claude" / "skills" / "property-tests" / "SKILL.md")
    if any(agent_is_present(a) for a in ("codex", "antigravity", "copilot")):
        paths.append(REPO_ROOT / ".agents" / "skills" / "property-tests" / "SKILL.md")

    for path in paths:
        assert path.exists(), f"Missing property-tests file: {path}"


def test_deprecate_api_exists_on_every_wired_surface() -> None:
    """`deprecate-api` warns callers off a public name before a later release removes it.

    Same two-surface layout as `template-sync`. It ships to downstream projects, which is who
    retires their own public API, so it is not in `cleanup.SETUP_FILES` (#832).
    """
    paths: list[Path] = []
    if agent_is_present("claude"):
        paths.append(REPO_ROOT / ".claude" / "skills" / "deprecate-api" / "SKILL.md")
    if any(agent_is_present(a) for a in ("codex", "antigravity", "copilot")):
        paths.append(REPO_ROOT / ".agents" / "skills" / "deprecate-api" / "SKILL.md")

    for path in paths:
        assert path.exists(), f"Missing deprecate-api file: {path}"


def test_python_version_bump_exists_on_every_wired_surface() -> None:
    """`python-version-bump` keeps the seven Python-version settings from drifting apart.

    Same two-surface layout as `add-dependency`. It ships to downstream projects, which are who
    bump Python versions, so it is not in `cleanup.SETUP_FILES` (#833).
    """
    paths: list[Path] = []
    if agent_is_present("claude"):
        paths.append(REPO_ROOT / ".claude" / "skills" / "python-version-bump" / "SKILL.md")
    if any(agent_is_present(a) for a in ("codex", "antigravity", "copilot")):
        paths.append(REPO_ROOT / ".agents" / "skills" / "python-version-bump" / "SKILL.md")

    for path in paths:
        assert path.exists(), f"Missing python-version-bump file: {path}"


def test_security_triage_exists_on_every_wired_surface() -> None:
    """`security-triage` triages bandit and pip-audit findings instead of silencing them.

    Same two-surface layout as `template-sync`. It ships to downstream projects, which is who
    triages their own scanner findings, so it is not in `cleanup.SETUP_FILES` (#834).
    """
    paths: list[Path] = []
    if agent_is_present("claude"):
        paths.append(REPO_ROOT / ".claude" / "skills" / "security-triage" / "SKILL.md")
    if any(agent_is_present(a) for a in ("codex", "antigravity", "copilot")):
        paths.append(REPO_ROOT / ".agents" / "skills" / "security-triage" / "SKILL.md")

    for path in paths:
        assert path.exists(), f"Missing security-triage file: {path}"


def test_dead_code_triage_exists_on_every_wired_surface() -> None:
    """`dead-code-triage` walks an agent through a vulture finding before it deletes anything.

    Same two-surface layout as `add-dependency`. It ships to downstream projects,
    which is who runs `doit check` against their own vulture findings, so it is
    not in `cleanup.SETUP_FILES` (#835).
    """
    paths: list[Path] = []
    if agent_is_present("claude"):
        paths.append(REPO_ROOT / ".claude" / "skills" / "dead-code-triage" / "SKILL.md")
    if any(agent_is_present(a) for a in ("codex", "antigravity", "copilot")):
        paths.append(REPO_ROOT / ".agents" / "skills" / "dead-code-triage" / "SKILL.md")

    for path in paths:
        assert path.exists(), f"Missing dead-code-triage file: {path}"


def test_perf_change_exists_on_every_wired_surface() -> None:
    """`perf-change` walks an agent through a measured baseline, profile and comparison.

    Same two-surface layout as `add-dependency`. It ships to downstream projects, which is who
    makes performance changes, so it is not in `cleanup.SETUP_FILES` (#836).
    """
    paths: list[Path] = []
    if agent_is_present("claude"):
        paths.append(REPO_ROOT / ".claude" / "skills" / "perf-change" / "SKILL.md")
    if any(agent_is_present(a) for a in ("codex", "antigravity", "copilot")):
        paths.append(REPO_ROOT / ".agents" / "skills" / "perf-change" / "SKILL.md")

    for path in paths:
        assert path.exists(), f"Missing perf-change file: {path}"


def test_merge_pr_exists_on_every_wired_surface() -> None:
    """`merge-pr` merges a green, labelled PR and closes the issues it fully addresses (#1062).

    Same two-surface layout as `perf-change`.
    """
    paths: list[Path] = []
    if agent_is_present("claude"):
        paths.append(REPO_ROOT / ".claude" / "skills" / "merge-pr" / "SKILL.md")
    if any(agent_is_present(a) for a in ("codex", "antigravity", "copilot")):
        paths.append(REPO_ROOT / ".agents" / "skills" / "merge-pr" / "SKILL.md")

    for path in paths:
        assert path.exists(), f"Missing merge-pr file: {path}"


def test_retired_self_action_aliases_are_removed() -> None:
    """The old ghissue-plan/implement/close self-action aliases should be gone."""
    removed = [
        REPO_ROOT / ".claude" / "commands" / "ghissue-plan.md",
        REPO_ROOT / ".claude" / "commands" / "ghissue-implement.md",
        REPO_ROOT / ".claude" / "commands" / "ghissue-close.md",
        REPO_ROOT / ".agents" / "skills" / "ghissue-plan" / "SKILL.md",
        REPO_ROOT / ".agents" / "skills" / "ghissue-implement" / "SKILL.md",
    ]

    for path in removed:
        assert not path.exists(), f"Retired self-action file should not exist: {path}"


def test_retired_plan_implement_matrix_is_removed() -> None:
    """The per-agent plan/implement matrix and ghi-finalize are gone (#976).

    Replaced by the single shared `implement-issue` skill, which plans
    conditionally and drives an issue to an open PR in one run.
    """
    removed = [
        REPO_ROOT / ".claude" / "commands" / "ghi-finalize.md",
        REPO_ROOT / ".agents" / "skills" / "ghi-finalize" / "SKILL.md",
        REPO_ROOT / ".agents" / "skills" / "codex-plan" / "SKILL.md",
        REPO_ROOT / ".agents" / "skills" / "codex-implement" / "SKILL.md",
        REPO_ROOT / ".agents" / "skills" / "antigravity-plan" / "SKILL.md",
        REPO_ROOT / ".agents" / "skills" / "antigravity-implement" / "SKILL.md",
    ]
    for target in ("claude", "codex", "copilot", "antigravity"):
        for action in ("plan", "implement"):
            removed.append(REPO_ROOT / ".claude" / "commands" / target / f"{action}.md")
    for target in ("claude", "codex", "copilot", "antigravity"):
        for action in ("plan", "implement"):
            removed.append(REPO_ROOT / ".github" / "skills" / f"{target}-{action}" / "SKILL.md")
    for target in ("claude", "codex", "copilot", "antigravity"):
        for action in ("plan", "implement"):
            removed.append(
                REPO_ROOT / ".agents" / "skills" / f"delegate-{target}-{action}" / "SKILL.md"
            )

    for path in removed:
        assert not path.exists(), f"Retired plan/implement matrix file should not exist: {path}"


def test_retired_dual_agent_files_are_removed() -> None:
    """The old hardcoded dual-agent commands should be gone, replaced by multi-* orchestrators."""
    removed = [
        REPO_ROOT / ".claude" / "commands" / "ghissue-plan-both.md",
        REPO_ROOT / ".claude" / "commands" / "ghissue-review-both.md",
    ]

    for path in removed:
        assert not path.exists(), f"Retired file should not exist: {path}"


def test_retired_workflow_step_aliases_are_removed() -> None:
    """The old ghissue-finalize/ghissue-status workflow steps should be renamed to ghi-*."""
    removed = [
        REPO_ROOT / ".claude" / "commands" / "ghissue-finalize.md",
        REPO_ROOT / ".claude" / "commands" / "ghissue-status.md",
        REPO_ROOT / ".agents" / "skills" / "ghissue-finalize" / "SKILL.md",
    ]

    for path in removed:
        assert not path.exists(), f"Retired workflow step file should not exist: {path}"


def test_codex_config_keeps_shared_dangerous_command_hook() -> None:
    """Codex config should keep the shared dangerous-command hook wired."""
    skip_if_absent("codex")

    config = (REPO_ROOT / ".codex" / "config.toml").read_text(encoding="utf-8")

    # `codex_hooks` is the deprecated spelling; Codex warns on it and would
    # silently stop running the hook if it were removed (#681).
    assert "hooks = true" in config
    # Match the assignment, not the bare word: the config explains the rename
    # in a comment, which a substring check would trip over.
    assert "codex_hooks = true" not in config
    assert "[[hooks.PreToolUse]]" in config
    assert "block-dangerous-commands.py" in config


def test_codex_config_uses_current_schema() -> None:
    """Codex config should avoid obsolete keys from older Codex releases."""
    skip_if_absent("codex")

    config = (REPO_ROOT / ".codex" / "config.toml").read_text(encoding="utf-8")

    assert 'approval_policy = "on-request"' in config
    assert "default_policy" not in config
    assert "[[approval_policy]]" not in config
    assert "[shell_env_policy]" not in config


def test_ai_setup_documents_codex_skills_workflow() -> None:
    """AI setup docs should describe the Codex skills-based workflow."""
    content = (REPO_ROOT / "docs" / "development" / "AI_SETUP.md").read_text(encoding="utf-8")

    assert ".agents/skills" in content
    assert "$codex-review" in content
    assert "shared dangerous-command hook" in content


def test_slash_commands_doc_mentions_codex_skills_instead_of_custom_commands() -> None:
    """Workflow docs should describe Codex via skills rather than custom slash commands."""
    content = (REPO_ROOT / "docs" / "development" / "ai" / "slash-commands.md").read_text(
        encoding="utf-8"
    )

    assert "repo-scoped skills" in content
    assert "/skills" in content
    assert "$codex-review" in content


def test_enforcement_principles_document_codex_hook_support() -> None:
    """Enforcement docs should reflect current Codex hook support."""
    content = (REPO_ROOT / "docs" / "development" / "ai" / "enforcement-principles.md").read_text(
        encoding="utf-8"
    )

    assert "Codex uses the shared hook" in content
    assert "no hook support" not in content


def test_antigravity_workflow_skills_exist() -> None:
    """Antigravity self-action skills should be present in the shared .agents/skills directory."""
    skip_if_absent("antigravity")

    for action in ("review", "adversarial-review"):
        skill_path = REPO_ROOT / ".agents" / "skills" / f"antigravity-{action}" / "SKILL.md"
        assert skill_path.exists(), f"Missing Antigravity skill: {skill_path}"


def test_antigravity_hooks_json_wires_shared_hook() -> None:
    """.agents/hooks.json should wire the shared dangerous-command hook on PreToolUse."""
    skip_if_absent("antigravity")

    hooks_path = REPO_ROOT / ".agents" / "hooks.json"
    assert hooks_path.exists(), f"Missing Antigravity hooks config: {hooks_path}"

    config = json.loads(hooks_path.read_text(encoding="utf-8"))
    commands = [
        handler.get("command", "")
        for group in config.values()
        for entry in group.get("PreToolUse", [])
        for handler in entry.get("hooks", [])
    ]
    assert any("block-dangerous-commands" in c for c in commands), (
        "Antigravity .agents/hooks.json must wire the shared dangerous-command hook on PreToolUse"
    )
    # The hook is agy's only gate (delegated invocations pass
    # --dangerously-skip-permissions), so its path must not depend on the CWD
    # agy happens to run handlers from. A bare "../tools/..." satisfied the
    # assertion above while resolving outside the repo from any other CWD.
    assert any("$(git rev-parse --show-toplevel)" in c for c in commands), (
        "Antigravity hook path must resolve independently of the handler CWD"
    )

    matchers = [
        entry.get("matcher", "")
        for group in config.values()
        for entry in group.get("PreToolUse", [])
    ]
    assert any("run_command" in m for m in matchers), (
        "Antigravity hook matcher must target the run_command tool"
    )


def test_copilot_hooks_json_pins_its_hook_path() -> None:
    """Copilot's wiring must keep an explicit cwd so its relative path resolves."""
    hooks_path = REPO_ROOT / ".github" / "hooks" / "copilot-hooks.json"
    assert hooks_path.exists(), f"Missing Copilot hooks config: {hooks_path}"

    config = json.loads(hooks_path.read_text(encoding="utf-8"))
    entries = config.get("hooks", {}).get("preToolUse", [])
    assert entries, "Copilot config must define a preToolUse hook"

    for entry in entries:
        assert "block-dangerous-commands" in entry.get("bash", ""), (
            "Copilot preToolUse hook must wire the shared dangerous-command hook"
        )
        # The path is relative, so the cwd pin is what makes it resolve.
        assert entry.get("cwd"), (
            "Copilot hook uses a relative path and must pin cwd, or it resolves "
            "against an unstated working directory"
        )


def test_stdout_contract_wirings_route_through_the_launcher() -> None:
    """Antigravity and Copilot must invoke the launcher, not the .py directly.

    Both block only on a stdout deny payload, so a hook that cannot start reads
    as "allow". The launcher denies in that case; calling the .py directly does
    not, because a script that never runs cannot emit its own deny.

    Only the hosts this project wires are checked (#690); the launcher itself is
    asserted either way, since it is what makes the contract fail closed.
    """
    wirings: list[tuple[str, list[str]]] = []

    if agent_is_present("antigravity"):
        agy = json.loads((REPO_ROOT / ".agents" / "hooks.json").read_text(encoding="utf-8"))
        wirings.append(
            (
                "Antigravity",
                [
                    handler.get("command", "")
                    for group in agy.values()
                    for entry in group.get("PreToolUse", [])
                    for handler in entry.get("hooks", [])
                ],
            )
        )

    if agent_is_present("copilot"):
        copilot = json.loads(
            (REPO_ROOT / ".github" / "hooks" / "copilot-hooks.json").read_text(encoding="utf-8")
        )
        wirings.append(
            (
                "Copilot",
                [e.get("bash", "") for e in copilot.get("hooks", {}).get("preToolUse", [])],
            )
        )

    for label, commands in wirings:
        assert any("block-dangerous-commands.sh" in c for c in commands), (
            f"{label} must route through the fail-closed launcher"
        )

    launcher = REPO_ROOT / "tools" / "hooks" / "ai" / "block-dangerous-commands.sh"
    assert launcher.exists(), f"Missing launcher: {launcher}"


def test_docs_document_antigravity_agent() -> None:
    """AI setup and command-blocking docs should register Antigravity as a supported agent."""
    ai_setup = (REPO_ROOT / "docs" / "development" / "AI_SETUP.md").read_text(encoding="utf-8")
    assert "Antigravity" in ai_setup
    assert ".agents/hooks.json" in ai_setup

    blocking = (REPO_ROOT / "docs" / "development" / "ai" / "command-blocking.md").read_text(
        encoding="utf-8"
    )
    assert ".agents/hooks.json" in blocking
    assert "write_to_file" in blocking


def test_multi_orchestrators_recognize_antigravity() -> None:
    """Every wired host's multi-* orchestrators offer antigravity as an agent.

    Skipped when the project does not wire Antigravity — there is nothing for the
    orchestrators to offer (#690).
    """
    skip_if_absent("antigravity")

    actions = ("plan", "review", "adversarial-review")
    multi_files: list[Path] = []
    if agent_is_present("claude"):
        multi_files += [
            REPO_ROOT / ".claude" / "skills" / f"multi-{a}" / "SKILL.md" for a in actions
        ]
    multi_files += [REPO_ROOT / ".agents" / "skills" / f"multi-{a}" / "SKILL.md" for a in actions]

    for f in multi_files:
        content = f.read_text(encoding="utf-8")
        assert "`antigravity`" in content, f"{f} does not list antigravity as an allowed agent"
        assert "agy -p" in content, f"{f} has no agy invocation block"
