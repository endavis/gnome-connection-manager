"""Validate the cross-agent delegation matrix file layout.

Static test only — no CLI or model invocations. Verifies that:

- Every source x target x action command/skill cell resolves to a file at the
  documented path (Codex and Antigravity share the host-agnostic
  `.agents/skills/delegate-*` files, so distinct files number fewer than cells).
- The matrix documentation page exists.

The matrix covers `review` and `adversarial-review` only — `plan` and `implement`
were removed from the per-agent matrix in favor of the single shared
`implement-issue` skill (#976). The matrix is sized from the agents this
project wires, not from the template's own four. In the template that is 24
cells over 20 distinct files; a project that keeps one agent has no
cross-agent matrix and checks nothing here, rather than failing cells for
agents it deliberately dropped (#690).

See `docs/development/ai/cross-agent-delegation.md` and issues #550, #640.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from agent_roster import present_agents

REPO_ROOT = Path(__file__).resolve().parents[1]

ACTIONS = ("review", "adversarial-review")

# The agents this project actually wires. The template wires all four; a project
# spawned from it keeps only the ones it uses, and must not be told its suite is
# broken for declining the rest (#690).
AGENTS = present_agents()


def _cross_pairs() -> list[tuple[str, str]]:
    """Yield (source, target) pairs where source != target.

    Empty for a single-agent project — there is no cross-agent matrix to check —
    which parametrizes the cell tests away rather than failing them.
    """
    return [(s, t) for s in AGENTS for t in AGENTS if s != t]


def _expected_path(source: str, target: str, action: str) -> Path:
    """Map a (source, target, action) cell to its on-disk location.

    Copilot bridges live under .github/skills/<target>-<action>/SKILL.md.
    Copilot CLI discovers project skills from .github/skills/, .agents/skills/,
    and .claude/skills/ (per @github/copilot SDK index.d.ts), but we use
    .github/skills/ specifically because it's the only one of those paths that
    Claude does not also read — placing the bridges there avoids surfacing
    duplicate slash commands in Claude alongside its native /<target>:<action>.
    Skill names use hyphen because skill names cannot contain colons.
    """
    if source == "claude":
        return REPO_ROOT / ".claude" / "commands" / target / f"{action}.md"
    if source == "copilot":
        return REPO_ROOT / ".github" / "skills" / f"{target}-{action}" / "SKILL.md"
    if source in ("codex", "antigravity"):
        # Antigravity shares Codex's host-agnostic delegate-* skills in
        # .agents/skills/ (both CLIs read that directory). antigravity->codex
        # uses the new delegate-codex-*, codex->antigravity uses
        # delegate-antigravity-*, and delegate-{claude,copilot}-* are
        # reused by both sources.
        return REPO_ROOT / ".agents" / "skills" / f"delegate-{target}-{action}" / "SKILL.md"
    raise ValueError(f"unknown source agent: {source}")


@pytest.mark.parametrize(("source", "target"), _cross_pairs())
@pytest.mark.parametrize("action", ACTIONS)
def test_delegation_file_exists(source: str, target: str, action: str) -> None:
    """Every (source, target, action) cell has a corresponding file."""
    path = _expected_path(source, target, action)
    assert path.is_file(), f"missing delegation file: {path.relative_to(REPO_ROOT)}"


def test_total_file_count() -> None:
    """Every cross-agent cell resolves, and Codex/Antigravity share their files.

    The template wires four agents: 4 sources x 3 targets x 2 actions = 24 cells,
    of which 4 share a file, leaving 20 distinct. Both counts are *derived* from
    the agents this project wires rather than pinned, so dropping an agent
    narrows the matrix instead of failing it (#690).
    """
    cells = [(s, t, a) for s, t in _cross_pairs() for a in ACTIONS]
    expected_cells = len(AGENTS) * max(len(AGENTS) - 1, 0) * len(ACTIONS)
    assert len(cells) == expected_cells

    missing = [
        str(_expected_path(s, t, a).relative_to(REPO_ROOT))
        for s, t, a in cells
        if not _expected_path(s, t, a).is_file()
    ]
    assert not missing, f"missing delegation files: {missing}"

    # Codex and Antigravity both read the host-agnostic .agents/skills/delegate-*
    # files, so when a project wires both, every cell they aim at a third agent
    # collapses onto one file.
    both_share = "codex" in AGENTS and "antigravity" in AGENTS
    shared_cells = (
        len([t for t in AGENTS if t not in ("codex", "antigravity")]) * len(ACTIONS)
        if both_share
        else 0
    )
    distinct = {_expected_path(s, t, a) for s, t, a in cells}
    assert len(distinct) == expected_cells - shared_cells, (
        f"expected {expected_cells - shared_cells} distinct files for agents "
        f"{AGENTS}, found {len(distinct)}"
    )


def test_matrix_doc_exists() -> None:
    """The cross-agent delegation doc page exists."""
    doc = REPO_ROOT / "docs" / "development" / "ai" / "cross-agent-delegation.md"
    assert doc.is_file(), f"missing matrix doc: {doc.relative_to(REPO_ROOT)}"


# --- The doc's numbers must be the derived ones (#754) ---------------------
#
# The matrix size was written out in eight places across four files and checked
# in none; five were wrong, in three directions, and one still described the
# five-agent era that ended with #712. The count is derived data — this module
# already computes it — so it now lives in exactly one prose sentence, and these
# tests hold that sentence to what the filesystem says.

MATRIX_DOC = REPO_ROOT / "docs" / "development" / "ai" / "cross-agent-delegation.md"

# `The 4 sources \u00d7 4 targets \u00d7 4 actions = 64 cells (including self-action).
#  Cross-agent delegation is 4 \u00d7 3 \u00d7 4 = 48 cells, across **40 distinct files**`
MATRIX_SENTENCE = re.compile(
    r"The (?P<sources>\d+) sources \u00d7 (?P<targets>\d+) targets \u00d7 (?P<actions>\d+) actions "
    r"= (?P<total>\d+) cells.*?"
    r"Cross-agent delegation is \d+ \u00d7 \d+ \u00d7 \d+ = (?P<cross>\d+) cells, "
    r"across \*\*(?P<files>\d+) distinct files\*\*",
    re.DOTALL,
)

# Files that must describe the matrix structurally rather than by number, so
# there is only one copy of the count to keep true.
_PROSE_ONLY_DOCS = (
    "docs/development/AI_SETUP.md",
    "docs/development/ai/slash-commands.md",
    ".copilot/README.md",
    "AGENTS.md",
)

# Nouns a matrix count is written with. `distinct files` alone was too narrow:
# `.copilot/README.md` carried "(16 files)" in a file this test already scanned,
# and the guard was trusted to cover it (#774). Widened to the bare nouns, which
# hits that line and nothing else in _PROSE_ONLY_DOCS -- verified before landing,
# because a pattern that matches ordinary prose would make the guard noise.
_COUNT_IN_PROSE = re.compile(
    r"\b\d+ (?:cells|files|entries|skills|bridges|commands|"
    r"distinct files|cross-agent bridges|delegation commands|"
    r"self-action skills|delegate-\S+ skills)\b"
)


def _derived_counts() -> dict[str, int]:
    """The matrix size, computed the same way :func:`test_total_file_count` does."""
    cross = len(AGENTS) * max(len(AGENTS) - 1, 0) * len(ACTIONS)
    both_share = "codex" in AGENTS and "antigravity" in AGENTS
    shared = (
        len([t for t in AGENTS if t not in ("codex", "antigravity")]) * len(ACTIONS)
        if both_share
        else 0
    )
    return {
        "sources": len(AGENTS),
        "targets": len(AGENTS),
        "actions": len(ACTIONS),
        "total": len(AGENTS) * len(AGENTS) * len(ACTIONS),
        "cross": cross,
        "files": cross - shared,
    }


def _stated_counts(text: str) -> dict[str, int] | None:
    match = MATRIX_SENTENCE.search(text)
    return {k: int(v) for k, v in match.groupdict().items()} if match else None


@pytest.mark.skipif(len(present_agents()) < 2, reason="no cross-agent matrix to size")
def test_matrix_doc_states_the_derived_counts() -> None:
    """A number in prose that no test reads is a number that will be wrong."""
    stated = _stated_counts(MATRIX_DOC.read_text(encoding="utf-8"))
    assert stated is not None, (
        f"{MATRIX_DOC.name} no longer states the matrix size in the form this test reads. "
        "If the sentence was reworded, update MATRIX_SENTENCE — dropping the assertion "
        "silently is how the eight stale copies happened (#754)."
    )
    assert stated == _derived_counts(), (
        f"{MATRIX_DOC.name} states {stated}, but the wired agents "
        f"{AGENTS} \u00d7 {ACTIONS} give {_derived_counts()}."
    )


@pytest.mark.parametrize("relative", _PROSE_ONLY_DOCS)
def test_only_the_matrix_doc_states_counts(relative: str) -> None:
    """Everywhere else describes the structure, so there is nothing to drift."""
    path = REPO_ROOT / relative
    if not path.is_file():
        pytest.skip(f"{relative} is not present in this project")
    offenders = [
        f"line {n}: {m.group(0)!r}"
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        for m in _COUNT_IN_PROSE.finditer(line)
    ]
    assert not offenders, (
        f"{relative} writes out a matrix count:\n  " + "\n  ".join(offenders) + "\n"
        f'Describe the structure instead ("one bridge per (target, action) pair"). '
        f"{MATRIX_DOC.relative_to(REPO_ROOT)} is the one place the numbers belong (#754)."
    )


def test_the_count_checks_detect_a_planted_error() -> None:
    """Guard against both scans passing because they match nothing."""
    doctored = MATRIX_DOC.read_text(encoding="utf-8").replace("= 32 cells", "= 33 cells", 1)
    assert _stated_counts(doctored) != _derived_counts(), (
        "the matrix sentence parser did not notice a wrong total"
    )
    assert _COUNT_IN_PROSE.search("plus 12 cross-agent bridges under .github/skills/"), (
        "the prose scan did not notice a written-out count"
    )
    # The shape the pattern used to miss: a bare noun after the number. This
    # exact string sat in .copilot/README.md, inside a file the scan covers,
    # while the guard was believed to be holding it (#774).
    assert _COUNT_IN_PROSE.search("Copilot-host workflow skills (16 files)"), (
        "the prose scan still misses a bare '<n> files'"
    )
    # ...and the pattern must not fire on ordinary prose that happens to count
    # something else, or the guard becomes noise rather than a signal.
    for benign in (
        "takes 1 to 3 minutes",
        "Python 3.14 support",
        "the 4 sources are listed above",
    ):
        assert not _COUNT_IN_PROSE.search(benign), f"false positive on {benign!r}"
