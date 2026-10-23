---
title: "ADR-9023: Shared workflow skills are written once in .agents/skills/ and generated for Claude"
description: Shared workflow skills live once in .agents/skills/ and doit skills_sync generates Claude's copy
date: 2026-10-20
audience:
  - contributors
tags:
  - adr
---

# ADR-9023: Shared workflow skills are written once in .agents/skills/ and generated for Claude

## Status

Accepted

## Decision

**Shared workflow skills are written once, in `.agents/skills/<name>/SKILL.md`, and generated for
Claude by `doit skills_sync`.**

1. Twelve near-identical workflows (`add-dependency`, `checkpoint`, `restore`, `template-sync`,
   `template-migrate`, `mutation-triage`, `property-tests`, `deprecate-api`,
   `python-version-bump`, `security-triage`, `dead-code-triage`, `perf-change`) plus `ghi-status`
   are written once, with `name:`/`description:` frontmatter and no Claude-only instructions, so
   Claude can auto-invoke each one from its `description:` the same way Codex, Antigravity and
   Copilot already do. `implement-issue` joined this list in ADR-9024, as `SHARED_SKILLS` entry
   fourteen, after it replaced the per-agent plan/implement matrix and `ghi-finalize`. The three
   `multi-*` orchestrators (`multi-plan`, `multi-review`, `multi-adversarial-review`) joined in #975
   as entries fifteen through seventeen, once each could be rewritten to say "the entry in the
   table that matches the CLI running this skill is you" instead of hardcoding one agent as self.
2. `doit skills_sync` copies each source, byte for byte, to `.claude/skills/<name>/SKILL.md` — the
   path Claude Code reads (Claude Code 2.1.304 does not read `.agents/skills/`). The task runs only
   when the project wires Claude Code, using the same presence marker as `tests/agent_roster.py`.
   `doit skills_sync --check` reports drift and exits non-zero instead of writing anything.
3. The 13 corresponding `.claude/commands/<name>.md` files are deleted. The Claude slash names are
   unchanged: `/add-dependency` and the rest still work, now as skills.
4. `ghi-finalize` was out of scope here because it was written around the agent running it the same
   way the `multi-*` orchestrators originally were; ADR-9024 later removed it entirely rather than
   merging it — it is not "agent-portable", it does not exist any more. The `multi-*` orchestrators
   themselves moved from out of scope to in scope in #975, once each could say which CLI is running
   it without hardcoding an agent as self (see Decision 1 above).

## Rationale

Each of these 13 workflows used to be kept twice: once under `.claude/commands/<name>.md` for
Claude, once under `.agents/skills/<name>/SKILL.md` for Codex, Antigravity and Copilot. Nothing
enforced that the two stayed the same, and `tests/test_*_skill.py` had to carry a
"deliberately not byte-identical" contract-and-ordering check instead of a plain diff, because nothing
kept the bodies themselves in sync — only their steps and gate sentences.

Generating one copy from the other removes the drift entirely: a diff is now the whole contract, and
`tests/template/test_skills_sync.py` enforces it as a repo-level check. `.agents/skills/` was picked
as the source, not `.claude/commands/`, because it already carries the frontmatter every other agent
needs and because Claude is the one surface here that cannot read the other directory directly — so
Claude is the one that needs something generated *for* it, not the other way around.

Copilot reads both `.agents/skills/` and `.claude/skills/` for a skill of this name, and prefers
`.agents/skills/` when both exist (Copilot CLI 1.0.100) — so the generated Claude copy does not
create a second, possibly-stale entry in a Copilot session.

`ghi-finalize` stayed out of scope, and the `multi-*` orchestrators stayed out of scope at the time,
because each was written around the mechanics of the agent running it (which CLI to shell out to,
how it posts to GitHub) in a way the 12 merged workflows were not. Folding them in then would have
meant solving that problem as a side effect of this one. #975 later solved it directly for the
`multi-*` files — "the entry in the table that matches the CLI running this skill is you" replaces
the hardcoded self-agent branch — which is what let them join `SHARED_SKILLS` too.

## Consequences

- **Edit only `.agents/skills/<name>/SKILL.md`.** The generated `.claude/skills/<name>/SKILL.md` is
  build output; hand-editing it is caught by `doit skills_sync --check` and overwritten by
  `doit skills_sync`.
- **A new shared skill needs a `SHARED_SKILLS` entry.** `tools/doit/skills.py` holds the fixed list
  `doit skills_sync` copies; a skill meant for every agent that is left out of it never reaches
  `.claude/skills/`.
- **Downstream projects that customized a `.claude/commands/<name>.md` file need a one-off migration
  step** the next time they sync: move the customization into
  `.agents/skills/<name>/SKILL.md` and run `doit skills_sync`. Documented in
  `docs/template/consumer-notes.md`.
- **The `template-migrate` bootstrap URL changed.** A project installing it standalone now fetches
  `.agents/skills/template-migrate/SKILL.md` for every agent, including Claude; the old
  `.claude/commands/` raw URL for `template-migrate.md` 404s.

## Related Issues

- Issue #972: make `.agents/skills/` the single source for shared workflow skills
- Issue #976: `implement-issue` joins `SHARED_SKILLS`, replacing the per-agent plan/implement matrix
  and `ghi-finalize`
- Issue #975: the `multi-*` orchestrators join `SHARED_SKILLS`, rewritten to be agent-portable

## Related Documentation

- [ADR-9024](9024-one-implement-issue-skill-takes-an-issue-to-a-green-pr.md) — the skill that
  removed `ghi-finalize` and added `implement-issue` to this list

- [Slash Commands and Workflows](../development/ai/slash-commands.md) — the shared-skills section,
  and the per-command source references
- [AI Agent Setup Guide](../development/AI_SETUP.md) — per-agent skill discovery paths
- [Consumer Notes](../template/consumer-notes.md) — the one-off migration step for a downstream
  project that customized one of the 13 commands
