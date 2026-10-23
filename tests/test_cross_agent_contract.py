"""The cross-agent workflow files must agree, not merely exist.

`test_delegation_matrix.py` checks that every command/skill file is present.
Presence is not agreement: the files encode a shared workflow contract that lets
a user switch agents mid-workflow without losing state. Until #692 nothing
checked that they still said the same things, so the contract held only by
manual discipline across dozens of files.

`plan`, `implement` and the `ghi-finalize` handoff were per-agent matrix files
until #976 replaced them with the single shared `implement-issue` skill
(`.agents/skills/implement-issue/SKILL.md`, generated for Claude by `doit
skills_sync`). Its contract is checked directly against that one source rather
than per-agent, since there is only one file to agree with itself.

The three `multi-*` orchestrators used to hardcode one agent as the one running
inline (`(self)`) and carry their own copy of the non-interactive invocation
table per host, until #975 rewrote each as a single shared skill
(`.agents/skills/multi-{plan,review,adversarial-review}/SKILL.md`, generated
for Claude the same way) that identifies "self" generically: "the entry in the
table that matches the CLI running this skill is you." Their contract is
checked the same way `implement-issue`'s is — against the one shared source.

The contract itself is documented in
``docs/development/ai/cross-agent-delegation.md``; this module is its enforcement.
When the two disagree, the doc is the specification and this file is the bug.

Per-agent exemptions are declared in `EXEMPTIONS` with a reason, because uniform
prose is not the goal — agreement on the contract is.

Assertions are scoped to the agents a project actually wires, following the
convention in `tests/agent_roster.py` (#690).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from agent_roster import agent_is_present, present_agents

REPO_ROOT = Path(__file__).resolve().parents[1]

# Where each agent keeps its self-action workflow file for a given action.
SELF_ACTION_LAYOUTS = {
    "claude": lambda action: REPO_ROOT / ".claude" / "commands" / "claude" / f"{action}.md",
    "copilot": lambda action: REPO_ROOT / ".github" / "skills" / f"copilot-{action}" / "SKILL.md",
    "codex": lambda action: REPO_ROOT / ".agents" / "skills" / f"codex-{action}" / "SKILL.md",
    "antigravity": (
        lambda action: REPO_ROOT / ".agents" / "skills" / f"antigravity-{action}" / "SKILL.md"
    ),
}


def _bridge_action_file(source: str, target: str, action: str) -> Path:
    """Map a (source, target, action) cross-agent cell to its on-disk bridge file.

    Mirrors `tests/test_delegation_matrix.py::_expected_path` — kept as a separate,
    smaller copy here rather than imported, since nothing else in this module
    depends on that file and test modules in this repo do not import each other.
    """
    if source == "claude":
        return REPO_ROOT / ".claude" / "commands" / target / f"{action}.md"
    if source == "copilot":
        return REPO_ROOT / ".github" / "skills" / f"{target}-{action}" / "SKILL.md"
    if source in ("codex", "antigravity"):
        return REPO_ROOT / ".agents" / "skills" / f"delegate-{target}-{action}" / "SKILL.md"
    raise ValueError(f"unknown source agent: {source}")


def _bridge_files(action: str) -> dict[tuple[str, str], Path]:
    """Every distinct (source, target) bridge file for *action*, among wired agents."""
    agents = present_agents()
    return {
        (source, target): _bridge_action_file(source, target, action)
        for source in agents
        for target in agents
        if source != target
    }


# The single shared implement-issue skill source. Its generated Claude copy is
# asserted byte-identical by tests/template/test_skills_sync.py, so checking
# the source here is sufficient.
IMPLEMENT_ISSUE_FILE = REPO_ROOT / ".agents" / "skills" / "implement-issue" / "SKILL.md"

# The three shared multi-* orchestrator sources. Same reasoning as
# IMPLEMENT_ISSUE_FILE: each has one generated Claude copy, asserted
# byte-identical by tests/template/test_skills_sync.py, so checking the source
# is sufficient.
MULTI_AGENT_FILES: dict[str, Path] = {
    "multi-plan": REPO_ROOT / ".agents" / "skills" / "multi-plan" / "SKILL.md",
    "multi-review": REPO_ROOT / ".agents" / "skills" / "multi-review" / "SKILL.md",
    "multi-adversarial-review": (
        REPO_ROOT / ".agents" / "skills" / "multi-adversarial-review" / "SKILL.md"
    ),
}

# A `gh` subcommand invocation, the thing a delegated prompt must no longer contain (#985):
# the host now pre-fetches any GitHub data a delegated agent needs with `doit
# delegation_context` and writes it to files under `tmp/agents/<host>/<task>-<n>/`, so the
# delegated prompt reads those instead of shelling out to `gh` itself. Matches `gh`
# followed by any subcommand (`gh issue`, `gh run`, `gh release`, ...) — not a bare
# mention of `gh` in prose, which several prompts carry when telling the agent NOT
# to run it (the closing backtick in "`gh` itself" keeps that from matching).
GH_COMMAND_PATTERN = re.compile(r"\bgh [a-z][a-z-]*\b")

# The host half of the DELEGATION-ERROR marker: without it, a delegated run that
# reached no GitHub data still prints a confident plan or review, and nothing
# flags it — #980's original symptom. Repurposed by #985 from "a `gh` call failed"
# to "the pre-fetched context file was missing or unreadable", since a delegated
# prompt no longer calls `gh` to fail in the first place.
DELEGATION_ERROR_CHECK = "treat output containing `DELEGATION-ERROR:` as a failed run"

# The sentence that tells a headless Codex host it cannot do GitHub writes or
# delegate to another agent CLI, carried verbatim by implement-issue and the
# three multi-* skills so the limit cannot read differently per surface (#984).
# docs/development/ai/cross-agent-delegation.md#headless-codex-host-limits is
# the full writeup; this is the pointer every skill file carries to it.
HEADLESS_CODEX_HOST_SENTENCE = (
    "A headless Codex host (`codex exec -a never`) can read GitHub through "
    "`.codex/rules/gh.rules` but cannot write to it or delegate to another agent CLI "
    "— see [Headless Codex host "
    "limits](../../../docs/development/ai/cross-agent-delegation.md#headless-codex-host-limits)."
)

# The mechanical self-removal rule each multi-* skill's Step 0 must carry verbatim.
# Replaces the old inference-based "identify which CLI you are" instruction, which
# a headless Codex host got wrong once in three attempts (#975 run 6): it reviewed
# inline as `codex` *and* also spawned a nested `codex … exec` call for the same
# slot. Filtering the agent list is a deterministic operation on Step 0's parse
# result, not a judgment call that can misfire (#986). Agent-name-agnostic by
# construction, so it can never special-case one CLI — see
# test_multi_agent_files_do_not_hardcode_a_self_agent.
SELF_REMOVAL_SENTENCE = (
    "Then remove your own name — the CLI running this skill — from the agent list. Every later "
    "step uses only the agents that remain: you never call your own CLI. If no agent remains, "
    "tell the user and stop."
)

# Files that must carry HEADLESS_CODEX_HOST_SENTENCE verbatim — the three
# shared multi-* skills plus the shared implement-issue skill.
HEADLESS_CODEX_HOST_FILES: dict[str, Path] = {
    **MULTI_AGENT_FILES,
    "implement-issue": IMPLEMENT_ISSUE_FILE,
}

# The non-interactive invocation each CLI needs, copied verbatim from
# docs/development/ai/cross-agent-delegation.md's "Non-interactive flags per
# CLI" table. test_non_interactive_invocations_match_the_doc keeps this copy
# honest against that doc.
NON_INTERACTIVE_INVOCATIONS: dict[str, str] = {
    "claude": "claude -p '<prompt>'",
    "codex": "codex -a never --dangerously-bypass-hook-trust exec '<prompt>' < /dev/null",
    "copilot": "copilot --allow-all -p '<prompt>'",
    "antigravity": (
        "agy -p '<prompt>' --dangerously-skip-permissions "
        '--add-dir "$(git rev-parse --show-toplevel)"'
    ),
}

# The six Codex bridge files that carry a *concrete* (not `<prompt>`-templated)
# exec string rather than a copy of NON_INTERACTIVE_INVOCATIONS["codex"]. Until
# #985 these inlined Hybrid C's "activate $codex-review/$codex-adversarial-review
# if available" fallback, which could still reach `gh pr view`/`gh pr diff`
# (#980); they now give Codex only the git-based inline steps, so there is no
# `gh` call left to guard and no self-action preference to inline.
CODEX_BRIDGE_FILES: dict[str, Path] = {
    "delegate-codex-review": (
        REPO_ROOT / ".agents" / "skills" / "delegate-codex-review" / "SKILL.md"
    ),
    "delegate-codex-adversarial-review": (
        REPO_ROOT / ".agents" / "skills" / "delegate-codex-adversarial-review" / "SKILL.md"
    ),
    "copilot-codex-review": REPO_ROOT / ".github" / "skills" / "codex-review" / "SKILL.md",
    "copilot-codex-adversarial-review": (
        REPO_ROOT / ".github" / "skills" / "codex-adversarial-review" / "SKILL.md"
    ),
    "claude-codex-review": REPO_ROOT / ".claude" / "commands" / "codex" / "review.md",
    "claude-codex-adversarial-review": (
        REPO_ROOT / ".claude" / "commands" / "codex" / "adversarial-review.md"
    ),
}

CROSS_AGENT_DELEGATION_DOC = REPO_ROOT / "docs" / "development" / "ai" / "cross-agent-delegation.md"

# The pointer sentence every review and adversarial-review surface (self-action
# and cross-agent bridge alike) carries verbatim to the one shared doc that
# holds the errors/tests/types/comments focus-area checklists (#956). The
# checklists themselves live only in docs/development/ai/review-focus-areas.md
# — this sentence is what keeps every surface pointing at that one source
# instead of copying the checklist text.
REVIEW_FOCUS_AREAS_SENTENCE = (
    "If the focus area names any of `errors`, `tests`, `types`, `comments`, read "
    "`docs/development/ai/review-focus-areas.md` and apply those checklists in addition to the "
    "general review."
)

# Contract elements, by the action whose files must carry them. Each entry is
# (label, substring). Substrings rather than regexes: the contract is a literal
# string the agents must reproduce, so a literal check is the honest test.
CONTRACT = {
    "review": [
        ("read-only constraint", "**Read-only.**"),
        ("review-focus-areas pointer", REVIEW_FOCUS_AREAS_SENTENCE),
    ],
    "adversarial-review": [
        ("read-only constraint", "**Read-only.**"),
        ("review-focus-areas pointer", REVIEW_FOCUS_AREAS_SENTENCE),
    ],
}

# implement-issue carries its own contract — one shared file, not one per agent.
IMPLEMENT_ISSUE_CONTRACT: list[tuple[str, str]] = [
    ("plan-comment header", "Implementation Plan for"),
    ("branch-name pattern", "<type>/"),
    ("validation command", "doit check"),
    ("docs validation command", "doit docs_build"),
    ("pr command", "doit pr"),
    ("issue reference", "Addresses #"),
    ("merge-gate check", "require-label"),
]

# (action, agent) pairs that legitimately omit an element, with the reason.
# An exemption is a documented architectural difference, not a licence to drift.
EXEMPTIONS: dict[tuple[str, str, str], str] = {}

# The identical sentence every review file must carry, so the constraint cannot
# be reworded into something weaker on one surface.
READ_ONLY_SENTENCE = (
    "**Read-only.** Review and report — do not edit files, commit, or push. "
    "Findings go to the user and the PR; any fix is a separate change the user asks for."
)


def _self_action_files(action: str) -> list[tuple[str, Path]]:
    """Return (agent, path) for each wired agent's file for *action*."""
    return [(agent, SELF_ACTION_LAYOUTS[agent](action)) for agent in present_agents()]


def _contract_violations(action: str, agent: str, text: str) -> list[str]:
    """Return the contract elements *text* is missing for (*action*, *agent*).

    Shared by the real check and its non-vacuity companion, so the companion
    exercises the logic that actually runs rather than a restatement of it.
    """
    return [
        f"{agent}/{action} is missing the {label} ({needle!r})"
        for label, needle in CONTRACT[action]
        if needle not in text and (action, agent, label) not in EXEMPTIONS
    ]


@pytest.mark.parametrize("action", sorted(CONTRACT))
def test_self_action_files_carry_the_contract(action: str) -> None:
    """Every wired agent's file for *action* contains that action's contract elements."""
    missing: list[str] = []

    for agent, path in _self_action_files(action):
        if not path.is_file():
            missing.append(f"{agent}: {path.relative_to(REPO_ROOT)} does not exist")
            continue
        missing += _contract_violations(action, agent, path.read_text(encoding="utf-8"))

    assert not missing, (
        "cross-agent contract violations:\n  "
        + "\n  ".join(missing)
        + "\n\nThe contract is specified in docs/development/ai/cross-agent-delegation.md. "
        "If an agent legitimately differs, declare it in EXEMPTIONS with a reason."
    )


@pytest.mark.parametrize("action", sorted(CONTRACT))
def test_bridge_files_carry_the_review_focus_areas_pointer(action: str) -> None:
    """Every cross-agent bridge file for *action* points at the shared focus-area doc.

    `test_self_action_files_carry_the_contract` already checks the 8 self-action files
    through `CONTRACT`; this is the matching check for the 20 (12 cells, 4 shared via
    `delegate-*`) cross-agent bridge files, so the pointer sentence cannot drift on the
    delegated path while holding on every self-action one.
    """
    missing = [
        f"{source}->{target}/{action}: {path.relative_to(REPO_ROOT)}"
        for (source, target), path in _bridge_files(action).items()
        if not path.is_file() or REVIEW_FOCUS_AREAS_SENTENCE not in path.read_text(encoding="utf-8")
    ]
    assert not missing, (
        "these cross-agent bridge files are missing the review-focus-areas pointer "
        f"sentence verbatim: {missing}"
    )


def test_read_only_constraint_is_worded_identically() -> None:
    """The review constraint must be the same sentence everywhere.

    A constraint that is paraphrased per host drifts into a weaker version on one
    surface, and whichever agent is driving decides which version applies — the
    same failure mode the rule-file mirror guards against.
    """
    divergent = []
    for action in ("review", "adversarial-review"):
        for agent, path in _self_action_files(action):
            if not path.is_file():
                continue
            if READ_ONLY_SENTENCE not in path.read_text(encoding="utf-8"):
                divergent.append(f"{agent}/{action}")

    assert not divergent, (
        f"these files do not carry the exact read-only sentence: {divergent}. "
        "Reword all of them together or none."
    )


def test_implement_issue_file_carries_its_contract() -> None:
    """The shared `implement-issue` skill carries every literal the workflow promises.

    There is one source file (`.agents/skills/implement-issue/SKILL.md`); its
    generated Claude copy is asserted byte-identical to it by
    `tests/template/test_skills_sync.py`, so checking the source is sufficient.
    """
    assert IMPLEMENT_ISSUE_FILE.is_file(), (
        f"missing implement-issue skill: {IMPLEMENT_ISSUE_FILE.relative_to(REPO_ROOT)}"
    )
    text = IMPLEMENT_ISSUE_FILE.read_text(encoding="utf-8")
    missing = [
        f"{label} ({needle!r})" for label, needle in IMPLEMENT_ISSUE_CONTRACT if needle not in text
    ]
    assert not missing, f"implement-issue skill is missing: {missing}"


def test_implement_issue_forbids_merge_actions() -> None:
    """implement-issue must say it never applies ready-to-merge, merges, or closes the issue.

    Those stay the user's decisions (ADR-9006's merge gate is unchanged by #976).
    """
    text = IMPLEMENT_ISSUE_FILE.read_text(encoding="utf-8")
    assert "ready-to-merge" in text
    assert "never merges" in text or "never merge" in text
    assert "closes the issue" in text or "close the issue" in text


def test_implement_issue_briefs_hand_no_gh_command() -> None:
    """The Planner and Coder briefs must read context files rather than call `gh` (#985).

    Both briefs run as a subagent, or get handed to a delegated agent's CLI; their caller
    (`implement-issue` itself, or `multi-plan`) fetches the issue with `doit
    delegation_context` first. The surrounding skill (Step 1's precondition check, Step 3's
    `gh issue comment`) still calls `gh` directly — it runs in the host, not delegated — so
    this is scoped to the two brief sections only.
    """
    text = IMPLEMENT_ISSUE_FILE.read_text(encoding="utf-8")
    planner_start = text.index("## Planner brief")
    coder_start = text.index("## Coder brief")
    per_host_start = text.index("## Per-host subagent notes")
    planner_brief = text[planner_start:coder_start]
    coder_brief = text[coder_start:per_host_start]

    assert not GH_COMMAND_PATTERN.search(planner_brief), "Planner brief still invokes gh"
    assert not GH_COMMAND_PATTERN.search(coder_brief), "Coder brief still invokes gh"


def test_the_contract_scanner_detects_a_violation() -> None:
    """Feeding the checker a file with none of the contract must flag every element.

    Without this, `test_self_action_files_carry_the_contract` could pass because
    the checker finds nothing to complain about rather than because the files
    comply. Uses an agent with no exemptions so nothing is silently skipped.
    """
    empty = "an unrelated document with none of the contract in it"

    for action, elements in CONTRACT.items():
        violations = _contract_violations(action, "copilot", empty)
        assert len(violations) == len(elements), (
            f"scanner found {len(violations)} of {len(elements)} missing elements "
            f"for {action!r}; the needles are too weak to assert on"
        )


def test_exemptions_are_real_and_documented() -> None:
    """Every exemption must name a live agent/action and actually be needed.

    Stops the exemption table from outliving the difference it excuses — the way
    an allowlist quietly becomes a list of things nobody checks.
    """
    stale: list[str] = []
    for (action, agent, label), reason in EXEMPTIONS.items():
        assert reason.strip(), f"exemption ({action}, {agent}, {label}) needs a reason"
        if not agent_is_present(agent):
            continue
        path = SELF_ACTION_LAYOUTS[agent](action)
        needle = next(n for lbl, n in CONTRACT[action] if lbl == label)
        if path.is_file() and needle in path.read_text(encoding="utf-8"):
            stale.append(f"({action}, {agent}, {label}) — the file now carries {needle!r}")

    assert not stale, f"these exemptions are no longer needed and should be removed: {stale}"


# --- multi-* orchestrator contract (#975) ---


def test_non_interactive_invocations_match_the_doc() -> None:
    """NON_INTERACTIVE_INVOCATIONS must still match cross-agent-delegation.md.

    That doc is the specification (see module docstring); if this copy drifts
    from it, this test — not the doc — is the bug to fix.
    """
    doc_text = CROSS_AGENT_DELEGATION_DOC.read_text(encoding="utf-8")
    missing = [
        f"{agent}: {invocation!r}"
        for agent, invocation in NON_INTERACTIVE_INVOCATIONS.items()
        if invocation not in doc_text
    ]
    assert not missing, (
        f"these invocations no longer match {CROSS_AGENT_DELEGATION_DOC.relative_to(REPO_ROOT)}: "
        f"{missing}"
    )


def test_multi_agent_files_carry_every_invocation() -> None:
    """Each multi-* skill's invocation table must carry all four CLIs' commands verbatim.

    A headless run can't reliably go and read cross-agent-delegation.md mid-skill
    (see module docstring), so each multi-* file carries its own copy of the
    table — this is what keeps that copy from drifting.
    """
    missing: list[str] = []
    for name, path in MULTI_AGENT_FILES.items():
        if not path.is_file():
            missing.append(f"{name}: {path.relative_to(REPO_ROOT)} does not exist")
            continue
        text = path.read_text(encoding="utf-8")
        for agent, invocation in NON_INTERACTIVE_INVOCATIONS.items():
            if invocation not in text:
                missing.append(f"{name} is missing the {agent} invocation ({invocation!r})")

    assert not missing, "multi-* invocation table violations:\n  " + "\n  ".join(missing)


def test_multi_agent_files_do_not_hardcode_a_self_agent() -> None:
    """No multi-* file may hardcode one agent as the one running inline.

    The old per-agent files each had a branch like "If `codex` is in the agent
    list (self):". The shared file replaces that with "the entry in the table
    that matches the CLI running this skill is you" — see the module docstring.
    """
    hardcoded = [
        name
        for name, path in MULTI_AGENT_FILES.items()
        if path.is_file() and "(self)" in path.read_text(encoding="utf-8")
    ]
    assert not hardcoded, (
        f"these multi-* files hardcode an agent as (self), which only one CLI can be: {hardcoded}"
    )


def test_multi_agent_files_remove_self_before_delegating() -> None:
    """Every multi-* skill's Step 0 must carry SELF_REMOVAL_SENTENCE verbatim.

    A paraphrase per file reopens exactly the drift
    `test_multi_agent_files_do_not_hardcode_a_self_agent` guards against: whichever
    host is driving ends up following whichever version of the rule its own file
    happens to carry (#986).
    """
    missing: list[str] = []
    for name, path in MULTI_AGENT_FILES.items():
        if not path.is_file():
            missing.append(f"{name}: {path.relative_to(REPO_ROOT)} does not exist")
            continue
        if SELF_REMOVAL_SENTENCE not in path.read_text(encoding="utf-8"):
            missing.append(f"{name} is missing SELF_REMOVAL_SENTENCE")

    assert not missing, "self-removal sentence violations:\n  " + "\n  ".join(missing)


def test_multi_review_files_carry_the_read_only_sentence() -> None:
    """`multi-review` and `multi-adversarial-review` must carry READ_ONLY_SENTENCE verbatim.

    They used to only paraphrase it; a paraphrase drifts into a weaker version,
    the same failure mode `test_read_only_constraint_is_worded_identically`
    guards against for the self-action files.
    """
    divergent = [
        name
        for name in ("multi-review", "multi-adversarial-review")
        if READ_ONLY_SENTENCE not in MULTI_AGENT_FILES[name].read_text(encoding="utf-8")
    ]
    assert not divergent, (
        f"these multi-* files do not carry the exact read-only sentence: {divergent}"
    )


def _exec_prompt(line: str) -> str | None:
    """Extract the single-quoted prompt from a `codex ... exec '...' < /dev/null` line.

    Returns ``None`` if *line* does not have the expected shape, so a caller can
    distinguish "no prompt found" from "empty prompt".
    """
    marker = "trust exec '"
    start = line.find(marker)
    if start == -1:
        return None
    start += len(marker)
    end = line.rfind("' < /dev/null")
    if end == -1 or end < start:
        return None
    return line[start:end]


def test_codex_bridge_files_close_stdin() -> None:
    """The six Codex bridge files' exec line must still close Codex's stdin (#980).

    `codex exec` waits forever on stdin otherwise, when the caller's own stdin is a
    pipe or socket rather than a terminal.
    """
    missing: list[str] = []
    for name, path in CODEX_BRIDGE_FILES.items():
        if not path.is_file():
            missing.append(f"{name}: {path.relative_to(REPO_ROOT)} does not exist")
            continue
        text = path.read_text(encoding="utf-8")
        exec_lines = [line for line in text.splitlines() if "trust exec '" in line]
        if not exec_lines or not all(line.endswith("' < /dev/null") for line in exec_lines):
            missing.append(f"{name}: a codex exec line does not end in < /dev/null")

    assert not missing, "Codex bridge file violations:\n  " + "\n  ".join(missing)


def test_codex_bridge_files_hand_codex_no_gh_command() -> None:
    """The six Codex bridge files' delegated prompt must never invoke `gh` (#985).

    The host no longer needs Codex to fetch its own GitHub data for these two
    actions — the inline steps are git-only — so there is nothing left for
    Hybrid C's old self-action-skill fallback (which did call `gh`) to guard.
    """
    violations: list[str] = []
    for name, path in CODEX_BRIDGE_FILES.items():
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            prompt = _exec_prompt(line)
            if prompt is not None and GH_COMMAND_PATTERN.search(prompt):
                violations.append(name)

    assert not violations, f"these bridge files still hand Codex a gh command: {violations}"


def test_codex_hosts_check_for_the_delegation_error_marker() -> None:
    """Every file that hands Codex a prompt must also check its output for the marker.

    Each delegated prompt tells its target to print `DELEGATION-ERROR:` when its
    pre-fetched context file is missing or unreadable (#985, was "when a `gh` call
    fails" before it); this is the other half, so the calling agent reports a
    failed run instead of summarizing output built on no data (#980).
    """
    files = {**MULTI_AGENT_FILES, **CODEX_BRIDGE_FILES}
    missing = [
        name
        for name, path in files.items()
        if DELEGATION_ERROR_CHECK not in path.read_text(encoding="utf-8")
    ]
    assert not missing, f"these files never check for DELEGATION-ERROR: {missing}"


def test_multi_agent_delegated_prompts_hand_no_gh_command() -> None:
    """Every multi-* skill's delegated (blockquoted) prompt must never invoke `gh` (#985).

    Step 3 of `multi-plan`/`multi-review` now fetches GitHub data once with `doit
    delegation_context` before delegating; the blockquoted prompt each hands to the
    other agents must read the resulting context directory rather than call `gh`
    itself. `multi-adversarial-review`'s prompt never needed `gh` in the first
    place and is asserted here too, so it cannot regress.
    """
    violations: list[str] = []
    for name, path in MULTI_AGENT_FILES.items():
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        prompt = "\n".join(line[2:] for line in text.splitlines() if line.startswith("> "))
        if GH_COMMAND_PATTERN.search(prompt):
            violations.append(name)

    assert not violations, f"these multi-* delegated prompts still invoke gh: {violations}"


def test_headless_codex_host_files_carry_the_limit_sentence() -> None:
    """implement-issue and the three multi-* skills must carry the headless-Codex-host sentence.

    Without a shared literal, the limitation could be worded differently (or dropped) in one
    skill and not the others — the same drift risk READ_ONLY_SENTENCE guards against (#984).
    """
    missing: list[str] = []
    for name, path in HEADLESS_CODEX_HOST_FILES.items():
        if not path.is_file():
            missing.append(f"{name}: {path.relative_to(REPO_ROOT)} does not exist")
            continue
        if HEADLESS_CODEX_HOST_SENTENCE not in path.read_text(encoding="utf-8"):
            missing.append(f"{name} is missing HEADLESS_CODEX_HOST_SENTENCE")

    assert not missing, "headless-Codex-host sentence violations:\n  " + "\n  ".join(missing)


def test_gh_command_pattern_catches_any_subcommand_but_not_prose() -> None:
    """The no-`gh` tests are only as strong as this pattern (#985 review)."""
    for command in ("gh issue view 1", "gh run list", "gh release create", "gh secret set X"):
        assert GH_COMMAND_PATTERN.search(command), command
    for prose in ("instead of running `gh`.", "rather than calling `gh` itself"):
        assert not GH_COMMAND_PATTERN.search(prose), prose
