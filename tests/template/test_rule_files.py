"""Contract tests for per-stack rule files.

Rule files are mirrored across every agent rule surface this project wires,
because every agent in the delegation matrix edits this codebase. The checklist body must stay
identical everywhere: a rule that disagrees with itself across agents is worse
than no rule, because whichever agent is driving decides which version applies.

These tests also enforce the authoring discipline from
``docs/development/ai/rule-files.md`` — the 30-line cap and the mandatory
``Observed failures:`` footer, which is what separates a rule derived from real
defects from a generic best-practices checklist.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from agent_roster import agent_is_present

REPO_ROOT = Path(__file__).resolve().parents[2]

# Rules are discovered, not listed. Pinning one name meant the second rule
# authored (`verified-claims`, #785) inherited none of the guarantees below --
# it was mirrored to three surfaces with nothing holding the bodies together,
# which is the state this module exists to prevent.
RULE_DIR = REPO_ROOT / ".claude" / "rules"


def _rule_names() -> list[str]:
    """Every rule authored on the Claude surface, which is the canonical list."""
    return sorted(path.stem for path in RULE_DIR.glob("*.md"))


def _all_rule_paths(rule: str) -> dict[str, Path]:
    """Every surface a rule is mirrored to, and how each one is loaded."""
    return {
        "claude": REPO_ROOT / ".claude" / "rules" / f"{rule}.md",
        "copilot": REPO_ROOT / ".github" / "instructions" / f"{rule}.instructions.md",
        "agents": REPO_ROOT / ".agents" / "skills" / rule / "SKILL.md",
    }


RULE_NAMES = _rule_names()

# Which agents each surface serves. `.agents/` is read by both Codex and
# Antigravity, so that surface is live if either agent is.
SURFACE_AGENTS = {
    "claude": ("claude",),
    "copilot": ("copilot",),
    "agents": ("codex", "antigravity"),
}


# The surfaces this project actually loads. A project that drops an agent drops
# its rule surface with it, and must not be told the mirror is broken (#690).
def _rule_paths(rule: str) -> dict[str, Path]:
    """The surfaces this project actually loads, for one rule.

    A project that drops an agent drops its rule surface with it, and must not
    be told the mirror is broken (#690).
    """
    return {
        surface: path
        for surface, path in _all_rule_paths(rule).items()
        if any(agent_is_present(agent) for agent in SURFACE_AGENTS[surface])
    }


# Every (rule, surface) pair this project loads, for parametrisation.
RULE_SURFACES = [(rule, surface) for rule in RULE_NAMES for surface in sorted(_rule_paths(rule))]

MAX_LINES = 30


def _body(path: Path) -> str:
    """Return the rule body, stripped of any YAML frontmatter.

    Copilot requires ``applyTo:`` frontmatter and Codex/Antigravity require
    ``name:``/``description:``; only the checklist below it must match.
    """
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            text = parts[2]
    return text.strip()


@pytest.mark.parametrize(("rule", "surface"), RULE_SURFACES)
def test_rule_exists_on_every_surface(rule: str, surface: str) -> None:
    """Each rule is present for every agent family this project wires."""
    path = _rule_paths(rule)[surface]
    assert path.exists(), f"{rule}: missing {surface} copy: {path}"


@pytest.mark.parametrize("rule", RULE_NAMES)
def test_rule_bodies_are_identical_across_surfaces(rule: str) -> None:
    """The checklist must not drift between agents."""
    paths = _rule_paths(rule)
    if len(paths) < 2:
        pytest.skip("only one rule surface is live; there is nothing to drift against")

    bodies = {name: _body(path) for name, path in paths.items()}
    reference_surface = next(iter(sorted(bodies)))
    reference = bodies[reference_surface]
    mismatched = [name for name, body in bodies.items() if body != reference]
    assert not mismatched, (
        f"{rule}: body differs on {mismatched} (compared against {reference_surface}); "
        "update every live surface together"
    )


@pytest.mark.parametrize(("rule", "surface"), RULE_SURFACES)
def test_rule_declares_observed_failures(rule: str, surface: str) -> None:
    """A rule with no observed-failure link is a guess, not a discipline."""
    body = _body(_rule_paths(rule)[surface])
    match = re.search(r"^Observed failures:\s*(.+)$", body, re.MULTILINE)
    assert match, f"{rule}: {surface} copy is missing the 'Observed failures:' footer"
    assert re.search(r"#\d+", match.group(1)), (
        f"{rule}: {surface} footer must cite at least one real issue or PR"
    )


@pytest.mark.parametrize(("rule", "surface"), RULE_SURFACES)
def test_rule_names_a_skill_gate(rule: str, surface: str) -> None:
    """``Skill:`` is the first body line — it names the capability gate."""
    assert _body(_rule_paths(rule)[surface]).splitlines()[0].startswith("Skill: ")


@pytest.mark.parametrize(("rule", "surface"), RULE_SURFACES)
def test_rule_stays_within_the_line_budget(rule: str, surface: str) -> None:
    """Past 30 lines a rule stops surviving a long context window; split it."""
    count = len(_rule_paths(rule)[surface].read_text(encoding="utf-8").splitlines())
    assert count <= MAX_LINES, f"{rule}: {surface} copy is {count} lines (max {MAX_LINES})"


@pytest.mark.parametrize("rule", RULE_NAMES)
def test_copilot_copy_declares_a_path_scope(rule: str) -> None:
    """Copilot's loader requires ``applyTo:`` frontmatter to gate the file."""
    paths = _rule_paths(rule)
    if "copilot" not in paths:
        pytest.skip("copilot is not wired in this project")
    text = paths["copilot"].read_text(encoding="utf-8")
    assert text.startswith("---"), "Copilot instructions need YAML frontmatter"
    assert re.search(r"^applyTo:\s*\S+", text, re.MULTILINE)


@pytest.mark.parametrize("rule", RULE_NAMES)
def test_agents_copy_declares_a_skill_gate_description(rule: str) -> None:
    """``description:`` is the skill-gate trigger for Codex and Antigravity."""
    paths = _rule_paths(rule)
    if "agents" not in paths:
        pytest.skip("neither codex nor antigravity is wired in this project")
    text = paths["agents"].read_text(encoding="utf-8")
    assert re.search(r"^name:\s*\S+", text, re.MULTILINE)
    assert re.search(r"^description:\s*\S+", text, re.MULTILINE)


def test_claude_loads_rule_files() -> None:
    """The glob import must be live, not commented out.

    A rule file that ships but never loads is a mechanism built and not used.
    """
    if not any("claude" in _rule_paths(rule) for rule in RULE_NAMES):
        pytest.skip("claude is not wired in this project")
    text = (REPO_ROOT / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
    assert re.search(r"^@\./rules/\*\.md\s*$", text, re.MULTILINE), (
        "CLAUDE.md must import ./rules/*.md (uncommented)"
    )


def test_rule_dir_holds_only_rule_files() -> None:
    """The glob loads every ``.md`` in ``.claude/rules/`` into every session.

    Authoring docs placed there load too: ``README.md`` did until #957, costing
    about 6 KB of context per session. They belong in ``docs/development/ai/``.
    """
    not_rules = [
        path.name
        for path in RULE_DIR.glob("*.md")
        if not path.read_text(encoding="utf-8").startswith("Skill: ")
    ]
    assert not not_rules, f"not rule files, but loaded every session: {not_rules}"
