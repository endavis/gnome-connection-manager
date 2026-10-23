"""Doit task that keeps Claude's generated skill copies in sync with `.agents/skills/`.

Each shared workflow skill in :data:`SHARED_SKILLS` is written once, in
`.agents/skills/<name>/SKILL.md`. Claude Code does not read `.agents/skills/`
(verified against Claude Code 2.1.304), so :func:`task_skills_sync` copies each
one, byte for byte, to `.claude/skills/<name>/SKILL.md` — the path Claude does
read. See ADR for the decision this task implements.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from doit.tools import title_with_actions
from rich.console import Console

from tools.doit.base import verbatim

REPO_ROOT = Path(__file__).resolve().parents[2]

# Workflow skills written once in `.agents/skills/` and generated for Claude
# under `.claude/skills/`. Every name here needs a
# `.agents/skills/<name>/SKILL.md` source; `tests/template/test_skills_sync.py`
# enforces that the generated copy stays byte-identical to it.
SHARED_SKILLS: tuple[str, ...] = (
    "add-dependency",
    "checkpoint",
    "restore",
    "template-sync",
    "template-migrate",
    "mutation-triage",
    "property-tests",
    "deprecate-api",
    "python-version-bump",
    "security-triage",
    "dead-code-triage",
    "perf-change",
    "ghi-status",
    "implement-issue",
    "multi-plan",
    "multi-review",
    "multi-adversarial-review",
)

# The marker that means Claude Code is wired in this project. Mirrors
# `tests/agent_roster.py`'s presence marker for Claude. Duplicated rather than
# imported: `tools/` is production code and `tests/` depends on it, never the
# other way around. Keep both in sync if the marker ever moves.
_CLAUDE_MARKER = Path(".claude") / "commands" / "claude"


def claude_is_wired(root: Path = REPO_ROOT) -> bool:
    """Return whether *root* wires Claude Code."""
    return (root / _CLAUDE_MARKER).is_dir()


def _source(name: str, root: Path) -> Path:
    return root / ".agents" / "skills" / name / "SKILL.md"


def _generated(name: str, root: Path) -> Path:
    return root / ".claude" / "skills" / name / "SKILL.md"


def drifted_skills(names: tuple[str, ...] = SHARED_SKILLS, root: Path = REPO_ROOT) -> list[str]:
    """Return the names among *names* whose generated copy is missing or stale."""
    drifted = []
    for name in names:
        generated = _generated(name, root)
        if not generated.is_file() or generated.read_bytes() != _source(name, root).read_bytes():
            drifted.append(name)
    return drifted


def sync_skills(names: tuple[str, ...] = SHARED_SKILLS, root: Path = REPO_ROOT) -> list[str]:
    """Copy every name in *names* from its `.agents/skills/` source to `.claude/skills/`.

    A copy already matching its source, byte for byte, is left untouched.

    Returns:
        The names whose generated copy was created or overwritten.
    """
    written = []
    for name in names:
        source = _source(name, root)
        generated = _generated(name, root)
        content = source.read_bytes()
        if not generated.is_file() or generated.read_bytes() != content:
            generated.parent.mkdir(parents=True, exist_ok=True)
            generated.write_bytes(content)
            written.append(name)
    return written


def task_skills_sync() -> dict[str, Any]:
    """Generate Claude's `.claude/skills/` copies from the `.agents/skills/` source.

    Shared workflow skills are written once, in `.agents/skills/<name>/SKILL.md`.
    Claude Code does not read that directory, so this task copies each one,
    byte for byte, to `.claude/skills/<name>/SKILL.md`.

    Runs only when this project wires Claude Code (same check as
    `tests/agent_roster.py`) — a project that dropped Claude has no
    `.claude/skills/` to populate.

    Options:
        --check: Report drift (a missing or stale generated copy) and exit
            non-zero instead of writing anything.
    """

    def run(check: bool) -> None:
        console = Console()

        if not claude_is_wired():
            console.print(verbatim("Claude is not wired in this project; nothing to sync."))
            return

        if check:
            drifted = drifted_skills()
            if drifted:
                console.print(verbatim(f"Drifted: {', '.join(drifted)}", "red"))
                console.print(
                    verbatim(
                        "Run `doit skills_sync` to regenerate .claude/skills/ "
                        "from .agents/skills/.",
                        "red",
                    )
                )
                sys.exit(1)
            console.print(
                verbatim("Every .claude/skills/ copy matches its .agents/skills/ source.", "green")
            )
            return

        written = sync_skills()
        if written:
            console.print(verbatim(f"Synced: {', '.join(written)}", "green"))
        else:
            console.print(verbatim("Nothing to sync; every copy already matches its source."))

    return {
        "actions": [run],
        "params": [
            {
                "name": "check",
                "long": "check",
                "type": bool,
                "default": False,
                "help": "Report drift and exit non-zero instead of writing anything",
            },
        ],
        "title": title_with_actions,
    }
