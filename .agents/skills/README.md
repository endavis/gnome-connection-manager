# Per-Stack Rule-Shaped Skills (Codex CLI)

## Purpose

Rule-shaped skills in this directory capture **narrow, recurring footguns** that Codex CLI keeps
getting wrong for a specific stack or domain. They are not a second copy of `AGENTS.md`. `AGENTS.md`
carries broad workflow and architectural rules for the whole project. A rule-shaped skill carries
three to ten numbered self-checks for one specific failure mode — small enough to survive a context
window, sharp enough to change behavior.

The pattern works because a short, skill-gated checklist is more likely to be honored late in a
session than a paragraph buried in a large reference file.

> **Codex-native loading:** Codex auto-loads a skill when the task description matches the skill's
> `description:` frontmatter. The `description:` field IS the skill-gate trigger — there is no
> `@import` directive or glob-import mechanism. Write the `description:` so that it matches only the
> tasks where the self-checks apply (e.g., "Use when generating typed Python from a YANG schema").
>
> This is the Codex equivalent of `.claude/rules/` (Claude Code). For the Claude variant, see that
> directory. For the GitHub Copilot variant, see
> [`.github/instructions/README.md`](../../.github/instructions/README.md).

> **Shared with Antigravity CLI (`agy`):** This `.agents/skills/` directory is also read by
> Antigravity, which uses the identical `SKILL.md` format (`name`/`description` frontmatter,
> description-gated activation). The `antigravity-*` workflow skills live here alongside the
> `codex-*` skills, and any rule-shaped skill added here is discovered by both CLIs. Because both
> read this directory, each sees the other's skills (the same bleed dynamic noted for Copilot);
> Antigravity-side suppression via `.agents/skills.json` `exclude` is planned for a later phase.

## When to author a rule-shaped skill

Write a rule-shaped skill when all three conditions hold:

1. The same mistake has recurred in at least two separate sessions or PRs.
2. The failure can be expressed as a numbered checklist a model can self-check before acting.
3. The scope is narrow enough to match a single, focused `description:` gate.

If the rule is broad (applies everywhere) or is not tied to an observed failure, put it in
`AGENTS.md` instead — or leave it out entirely.

## File location and naming

Each rule-shaped skill lives in its own subdirectory:

```
.agents/skills/<name>/SKILL.md
```

Use a short, lowercase, hyphenated name that reflects the domain (e.g., `codegen`, `db-migrations`,
`api-contracts`). Keep rule-shaped skills in separate directories from the workflow skills that
already exist here (`codex-plan`, `codex-implement`, etc.).

## File structure

Each rule-shaped skill's `SKILL.md` must have YAML frontmatter followed by three required sections:

```
---
name: <name>
description: <task-match trigger — the sentence Codex uses to decide when to load this skill>
---

Skill: <name>

Self-check before <action>:
1. <First check — concrete and verifiable>
2. <Second check>
3. <Third check>
...

Observed failures: <PR or issue URL>, <PR or issue URL>
```

### `description:` frontmatter

The `description:` field controls when Codex loads the skill. Write it as a sentence that matches
only the tasks where the self-checks apply:

- `description: Use when generating typed Python from a YANG schema` — task-specific
- `description: Use when writing or modifying database migration files` — task-specific

Avoid broad descriptions like `description: Use when writing Python` — that turns the skill into
ambient context, not a gate.

### Body sections

- **`Skill: <name>`** — the first line after frontmatter, no heading. Names the capability gate so
  the model can self-identify when to apply the file.
- **Numbered self-check list** — imperative, specific. Each item must be falsifiable: the model
  should be able to answer "yes" or "no".
- **`Observed failures:` footer** — links to the PRs or issues where the failure was documented.
  This is mandatory. A skill with no observed-failure link is a guess, not a discipline.

Target: **30 lines or fewer** per skill body (excluding frontmatter). If a body grows past 30 lines,
split it into two skills.

## Discipline: build from observed failures, not generic best-practices

The central rule of this pattern is that rule-shaped skills must be derived from documented
failures, not from intuition or generic advice. A checklist written in advance of any failure will
drift into noise — the model will pattern-match the checklist language and satisfy it superficially.
A checklist written because a specific PR broke a specific invariant three times is sharp enough to
change behavior. If you cannot fill in the `Observed failures:` footer with real links, the
rule-shaped skill is not ready to be written yet.

## Worked example

The following sketch illustrates what a `codegen/SKILL.md` rule-shaped skill might look like for a
downstream project (`pynetappfoundry`) that generates typed Python from a YANG schema and has an ADR
(ADR-0008) documenting a round-trip invariant. **This example is illustrative only** — actual
rule-shaped skills belong in downstream repos, not in this template.

```
---
name: codegen
description: Use when generating typed Python from a YANG schema in pynetappfoundry
---

Skill: codegen

Self-check before committing generated code:
1. Run `make roundtrip` and confirm exit 0 — the generated types must deserialize
   what the serializer produces without loss (ADR-0008).
2. Confirm no hand-edited lines remain in `src/generated/` — regenerate from schema
   if any exist.
3. Confirm the schema version in `src/generated/_version.py` matches the YANG source
   revision header.

Observed failures: endavis/pynetappfoundry#104, endavis/pynetappfoundry#117
```

## Shared discipline across CLIs

The **discipline** (≤30 lines, numbered self-checks, observed-failures footer) is shared across all
four CLIs even though the file format and load mechanism differ:

| CLI | Directory | Load mechanism |
| :--- | :--- | :--- |
| Claude Code | `.claude/rules/` | `@./rules/*.md` in `.claude/CLAUDE.md` |
| GitHub Copilot | `.github/instructions/` | Native auto-discovery (no directive needed) |
| Codex CLI | `.agents/skills/<name>/` | `description:` frontmatter is the skill-gate trigger |

See [`.claude/rules/README.md`](../../.claude/rules/README.md) and
[`.github/instructions/README.md`](../../.github/instructions/README.md) for the other CLI variants.

## What NOT to put in a rule-shaped skill

- **Broad workflow rules** — things like "never commit to main" or "always run `doit check`" belong
  in `AGENTS.md`, not here. Rule-shaped skills are for stack-specific self-checks, not universal
  workflow.
- **Generic best-practices** — "prefer composition over inheritance", "write type annotations" —
  these are noise. They drift into checklists the model satisfies by rote without changing behavior.
- **Anything not tied to an observed failure** — if you cannot cite a PR or issue where the rule was
  violated, the rule-shaped skill is not ready to be written yet.
- **Workflow logic** — do not mix rule-shaped skills (self-check checklists) with workflow skills
  (multi-step instructions like `codex-plan`). Keep them in separate subdirectories.

## Shipped rule: `typing-branch-narrowing`

This template ships one rule file, mirrored across all three agent rule surfaces because every
agent in the delegation matrix edits this codebase. The checklist body is identical everywhere;
only the frontmatter and the loading mechanism differ.

| Surface | Path |
| :--- | :--- |
| Claude | `.claude/rules/typing-branch-narrowing.md` |
| Copilot | `.github/instructions/typing-branch-narrowing.instructions.md` |
| Codex / Antigravity | `.agents/skills/typing-branch-narrowing/SKILL.md` |

**When you change one, change all three.** A rule that disagrees with itself across agents is worse
than no rule, because whichever agent is driving decides which version applies.
`tests/template/test_rule_files.py` enforces that each rule's three bodies stay identical. See
[`.claude/rules/README.md`](../../.claude/rules/README.md) for the authoring discipline.
