---
title: "ADR-9024: One implement-issue skill takes an issue to a green PR"
description: One shared implement-issue skill replaces /claude:plan, /claude:implement, /ghi-finalize and the per-agent plan/implement matrix
date: 2026-10-20
audience:
  - contributors
tags:
  - adr
---

# ADR-9024: One implement-issue skill takes an issue to a green PR

## Status

Accepted

## Decision

**One shared skill, `implement-issue` (`.agents/skills/implement-issue/SKILL.md`, generated for
Claude by `doit skills_sync`, ADR-9023), takes an open GitHub issue to an open PR in a single run,
replacing `/<ai>:plan`, `/<ai>:implement`, `/ghi-finalize`, and the 28-file per-agent plan/implement
matrix.**

1. The skill decides whether to plan first: the issue carries `needs-adr`, the change is a feature
   or refactor touching more than about 3 files or adding a module, or more than one approach is
   reasonable. Otherwise the issue body is the spec.
2. When it plans, the plan is posted to the issue as a comment under the header
   `## Implementation Plan for #<n>: <title>` **without waiting for approval**.
3. The coding step runs in a subagent (the skill's Coder brief; Claude's is
   `.claude/agents/implement-worker.md`). "Implement issue N with \<agent\>" hands only this step
   to that agent's CLI; every other step still runs in the host that received the request.
4. The skill runs `doit check` and `doit docs_build`, commits with `git commit` in the
   `.github/CONTRIBUTING.md` format (not `doit commit`, which is interactive), pushes, and opens the
   PR with `doit pr`, carrying `Addresses #<n>`.
5. It then watches `gh pr checks` and fixes any job other than `require-label` for **up to 3
   rounds**, stopping after the third to report every job still failing with a log excerpt.
6. The skill **never** applies `ready-to-merge`, never merges, and never closes the issue — those
   stay the user's decisions (the merge gate itself is unchanged; see ADR-9006).
7. It stops and asks the user at any point an ask-first trigger fires: a new dependency, scope
   growth, an architecture choice, a breaking change the issue did not already describe, a failing
   test that would need changing, or a blocked command.
8. The 28-file per-agent plan/implement matrix
   (`.claude/commands/{claude,codex,copilot,antigravity}/{plan,implement}.md`,
   `.github/skills/*-{plan,implement}/`, `.agents/skills/{codex,antigravity}-{plan,implement}/`,
   `.agents/skills/delegate-*-{plan,implement}/`) and `ghi-finalize`
   (`.claude/commands/ghi-finalize.md`, `.agents/skills/ghi-finalize/`) are deleted. The cross-agent
   matrix (`docs/development/ai/cross-agent-delegation.md`) now covers only `review` and
   `adversarial-review`.

## Rationale

Getting from an issue to a PR used to take three commands, two of which waited for the user: plan
mode (approve the plan), then implement (no wait), then `ghi-finalize` (approve the commit and PR
body). Each of the four agents also carried its own copy of the plan and implement files — 28 files
differing only in invocation syntax — so a change to the shared contract (the plan-comment header,
the branch-name pattern, `doit check`) had to be applied 28 times and checked by
`tests/test_cross_agent_contract.py` doing the same thing 28 times over.

Collapsing plan, implement, and finalize into one skill removes both costs at once: one approval
wait rather than two, and one file per behavior rather than one file per (agent, action) cell. The
behavior itself does not need four variants — deciding whether to plan, running `doit check`, and
opening a PR are not agent-specific decisions, the same insight ADR-9023 already applied to twelve
other near-identical workflows. `implement-issue` is SHARED_SKILLS entry fourteen.

Removing the approval waits is a real trade, not a free simplification: the skill now commits and
pushes without asking. The safety net is unchanged and still enforced at the tool level, not just in
prose — commits only ever land on the issue's own feature branch (never `main`), the dangerous-
command hooks still block `--force`, `--no-verify`, and direct `main` commits regardless of what
this skill's instructions say, and `ready-to-merge` stays something only a human applies (or an
agent with `ALLOW_AI_READY_TO_MERGE=1` explicitly set, unchanged from before this ADR). The user's
first checkpoint moves from "approve this plan" / "approve this commit" to "review this PR" — a
single, familiar GitHub artifact instead of two in-chat approvals.

The CI-fix loop's 3-round cap exists for the same reason the approval waits were bounded: an agent
that kept retrying CI fixes indefinitely would eventually make an unrelated change to force a flaky
check green, or loop forever on a failure it cannot actually fix. Stopping after 3 rounds and
reporting the still-failing jobs with log excerpts hands the decision back to the user at a bounded
cost, rather than either giving up after one try or never giving up at all.

## Consequences

- **Breaking change** (pre-1.0, MINOR bump). Downstream projects lose `/claude:plan`,
  `/claude:implement`, `/ghi-finalize`, and every agent's plan and implement skills. See
  [Consumer Notes](../template/consumer-notes.md) for the migration.
- **`tests/agent_roster.py` presence markers moved** from each agent's `*-plan` directory to its
  `*-review` directory, since `plan` files no longer exist per agent.
- **The agent commits and pushes without an approval wait.** Safety depends on the hooks and
  branch-only commits described above, not on this skill choosing to ask — `AGENTS.md`'s *Summary
  Before Commit* rule gains an explicit exception for "implement issue X".
- **`multi-plan` is not touched by this ADR** (#975 tracks it separately). It still names each
  agent's own plan skill, which no longer exists, so it falls back to inline planning per agent.
- **Supersede check.** ADR-9005 (command-restriction hooks) and ADR-9018 (`AGENTS.md` scope) do not
  decide plan or commit approval, so neither is superseded. ADR-9006 (the `ready-to-merge` merge
  gate) is explicitly unchanged — this ADR relies on it rather than altering it.

## Related Issues

- Issue #976: one implement-issue skill that takes an issue to a green PR
- Issue #975: clean up `multi-plan`'s references to removed per-agent plan skills (follow-up, not
  done here)

## Related Documentation

- [Slash Commands and Workflows](../development/ai/slash-commands.md) — the `implement issue N`
  command reference entry and the shared-skills list
- [Cross-Agent Delegation Matrix](../development/ai/cross-agent-delegation.md) — the matrix reduced
  to `review`/`adversarial-review`, and the workflow contract `implement-issue` carries
- [ADR-9023](9023-shared-workflow-skills-live-in-agents-skills-generated-for-claude.md) — the
  one-source/generated-for-Claude mechanism `implement-issue` uses
- [ADR-9006](9006-merge-gate-workflow.md) — the merge gate this ADR relies on and does not change
- [Consumer Notes](../template/consumer-notes.md) — the breaking-change migration for downstream
  projects
