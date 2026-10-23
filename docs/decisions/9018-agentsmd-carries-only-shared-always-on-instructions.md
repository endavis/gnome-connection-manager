---
title: "ADR-9018: AGENTS.md carries only shared, always-on instructions"
description: Content belongs in AGENTS.md only when it holds for every agent and must be in effect at all times
date: 2026-08-29
audience:
  - contributors
tags:
  - adr
  - ai
---

# ADR-9018: AGENTS.md carries only shared, always-on instructions

## Status
Accepted

## Decision
Content belongs in root `AGENTS.md` only when **both** hold:

1. **Shared** — true for every agent the project wires (`tests/agent_roster.py` decides which
   those are).
2. **Always-on** — must be in effect at all times, not at a nameable moment.

Fail either test and the content has an existing home:

| | always-on | just-in-time |
| :--- | :--- | :--- |
| **shared** | `AGENTS.md` — workflow, decision framework, the NEVER list, tool hierarchy | `docs/`, indexed from `### 5. Pre-Action Checks` |
| **agent-specific** | that agent's own always-on surface, *where one exists* | that agent's own docs and skills |

A third constraint cuts across both axes: **nothing is mirrored across surfaces without a sync
test.** `tests/template/test_rule_files.py` (byte-identical rule bodies) and
`tests/test_cross_agent_contract.py` (#692) are the two existing instances. A fact stated in two
places with nothing holding them together is a fact that will disagree with itself.

**The agent-specific always-on cell is not populated for every agent.** Measured on the template:

| agent | agent-specific always-on surface |
| :--- | :--- |
| Claude | `.claude/CLAUDE.md`, which glob-imports `.claude/rules/*.md` |
| Copilot | `.github/instructions/*.instructions.md` with `applyTo: '**'` |
| Codex | **none** — root `AGENTS.md` is its always-on file; `.agents/skills/` is `description:`-gated |
| Antigravity | **none** — same, and it shares `.agents/skills/` with Codex |

For Codex and Antigravity, "move it to that agent's own always-on file" is not an available move.
That is a reason to re-examine whether the content is genuinely always-on, not a licence to leave
agent-specific content in the shared file.

## Rationale
The cost of misallocation is not context size. Against a large context window, `AGENTS.md` at
~27.5 KB is not a capacity problem. Two other costs are real:

- **Relevance.** `### AI Config Directories` was 5,847 bytes — 21% of the file — describing four
  agents' config layouts to all four agents. Claude parsed Codex's approval flags and
  Antigravity's stdout-deny hook contract every session and could act on neither.
- **Position.** A rule buried in a large file is less likely to be honored late in a session;
  `docs/development/ai/rule-files.md` makes the same argument for why short skill-gated checklists work.
  #738 is the evidence that always-on is not always-honored: `.claude/CLAUDE.md` instructed every
  Claude session, in blocks marked MANDATORY, to find two `AGENTS.md` sections that did not exist
  and run a command that was never installed — for months, unnoticed.

**Why the config section was collapsed rather than split four ways.** #693 proposed moving each
agent's row into that agent's own always-on file. Rejected because:

- Two of the four agents have no such file (table above), so for half the audience the split buys
  the same resolution cost it was meant to avoid.
- Codex and Antigravity share `.agents/skills/`, so "each agent's own file" collapses to one file
  both read — each would still read the other's row.
- `.github/instructions/` is chartered for ≤30-line stack-specific self-checks with an
  `Observed failures:` footer; Copilot config prose meets none of that.
- Every distinctive fact in the section was already stated in `docs/development/AI_SETUP.md`,
  `slash-commands.md`, `cross-agent-delegation.md` or `command-blocking.md`. Splitting would have
  created four files that must agree about facts already stated correctly in one place — a drift
  surface bought for zero unique content.

**Why a structural test and not a byte budget.** #693 asked for a byte budget as a regrowth
ratchet. A size assertion is satisfied equally by removing agent-specific content (the goal) or by
deleting a shared always-on rule (the opposite), so it cannot fail for the right reason.
`tests/test_agents_md_allocation.py` asserts the property the decision is actually about: no
per-agent config detail in the shared file, and pointer-table rows that stay one line.

## Consequences
- `AGENTS.md`'s `### AI Config Directories` is a four-row pointer table naming each config root and
  the doc carrying its detail. Reading that doc is now a step, not a given.
- Reaching per-agent config detail costs one read at the moment of need. Accepted here because the
  content was duplication — the pointer resolves to a fuller, already-maintained account than the
  summary it replaces. The same trade is *not* automatically accepted for content that exists only
  in `AGENTS.md`; that is judged case by case (#751).
- Rule files remain the deliberate exception: mirrored to four surfaces on purpose, held together
  byte-for-byte by `tests/template/test_rule_files.py`.
- A downstream project that drops an agent drops that agent's row. The allocation rule is
  unchanged; `tests/agent_roster.py` decides which rows exist.
- Adding a fifth agent means adding one row and one doc section, not a paragraph per surface.

## Related Issues
- Issue #750: Collapse `AGENTS.md`'s `AI Config Directories` to a pointer table
- Issue #693: `AGENTS.md` mixes agent-specific content into the shared always-on file — the parent
  issue this decision was split out of
- Issue #751: Index the just-in-time reference from Pre-Action Checks — applies the same rule to
  the shared-but-not-always-on quadrant
- Issue #738 / PR #739: three dangling pointers inside `CLAUDE.md`'s MANDATORY blocks — the
  evidence that always-on is not always-honored
- Issue #692: cross-agent contract test — the precedent for guarding deliberate mirroring
- Issue #754: cross-agent matrix counts duplicated in eight places and verified in none — the
  anti-duplication constraint applied to derived data, found while auditing this collapse
- Issue #753: docs claimed Copilot CLI reads no `commands/` directory — found the same way,
  and the reason a pointer's destination must be checked, not assumed
- Issue #704: the first per-stack rule file, mirrored across four surfaces

## Related Documentation
- [AI Agent Setup Guide](../development/AI_SETUP.md) — per-agent config roots and setup; the
  destination the pointer table names
- [Slash Commands and Workflows](../development/ai/slash-commands.md) — per-host command discovery
- [Cross-Agent Delegation Matrix](../development/ai/cross-agent-delegation.md) — naming convention,
  workflow contract, non-interactive flags
- [AI Command Blocking](../development/ai/command-blocking.md) — hook wiring and per-host block
  contracts
- [Per-Stack Rule Files](../development/ai/rule-files.md) — the mirrored-with-a-sync-test exception
