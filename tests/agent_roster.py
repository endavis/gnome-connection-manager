"""Which AI agents this project actually ships.

The template wires four agents (Claude, Codex, Copilot, Antigravity). A project
spawned from it may keep only some — most keep one. Tests that assert on agent
wiring used to hardcode the template's own four and assert every file exists,
so dropping an unused agent produced 56 failures on the project's first run
(#690).

These helpers let those tests derive the roster from what is on disk. A project
that keeps every agent sees exactly the same assertions as before; one that
drops an agent simply stops asserting about it.

Presence is keyed on each agent's *self-action skill directory* rather than its
config root, because `.agents/` is shared: both Codex and Antigravity read it,
so its existence cannot distinguish them.

The markers point at each agent's `review` skill, not `plan` — `plan` and
`implement` were removed as per-agent self-action files when the shared
`implement-issue` skill replaced them (#976); `review` and
`adversarial-review` are the self-action files every agent still carries.

Not a test module — pytest does not collect it (the filename does not match
``test_*.py``).
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Every agent the template knows how to wire, in matrix order.
ALL_AGENTS: tuple[str, ...] = ("claude", "codex", "copilot", "antigravity")

# The directory whose presence means "this project uses this agent". Each is
# specific to one agent; see the module docstring on why `.agents/` alone will
# not do.
_PRESENCE_MARKERS: dict[str, Path] = {
    "claude": REPO_ROOT / ".claude" / "commands" / "claude",
    "codex": REPO_ROOT / ".agents" / "skills" / "codex-review",
    "copilot": REPO_ROOT / ".github" / "skills" / "copilot-review",
    "antigravity": REPO_ROOT / ".agents" / "skills" / "antigravity-review",
}


def agent_is_present(agent: str) -> bool:
    """Return whether *agent* is wired in this project."""
    marker = _PRESENCE_MARKERS.get(agent)
    return marker is not None and marker.is_dir()


def present_agents() -> tuple[str, ...]:
    """Return the agents this project wires, in :data:`ALL_AGENTS` order."""
    return tuple(agent for agent in ALL_AGENTS if agent_is_present(agent))


def skip_if_absent(agent: str) -> None:
    """Skip the calling test when *agent* is not wired in this project."""
    import pytest

    if not agent_is_present(agent):
        pytest.skip(f"{agent} is not wired in this project")
