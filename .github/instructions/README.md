# Per-Stack Instruction Files (GitHub Copilot)

## Purpose

Instruction files in this directory capture **narrow, recurring footguns** that GitHub Copilot
keeps getting wrong for a specific stack or domain. They are not a second copy of `AGENTS.md`.
`AGENTS.md` carries broad workflow and architectural rules for the whole project. An instruction
file carries three to ten numbered self-checks for one specific failure mode — small enough to
survive a context window, sharp enough to change behavior.

The pattern works because a short, skill-gated checklist is more likely to be honored late in a
session than a paragraph buried in a large reference file.

> **Copilot-native format:** Files in this directory are consumed by GitHub Copilot via its native
> auto-discovery mechanism. Claude Code **cannot** read `.github/instructions/` files. For the
> Claude equivalent use `.claude/rules/`; for Codex and Antigravity use `.agents/skills/`.

## When to author an instruction file

Write an instruction file when all three conditions hold:

1. The same mistake has recurred in at least two separate sessions or PRs.
2. The failure can be expressed as a numbered checklist a model can self-check before acting.
3. The scope is narrow enough to belong to a single skill gate (e.g., `codegen`, `db-migrations`,
   `api-contracts`).

If the rule is broad (applies everywhere) or is not tied to an observed failure, put it in
`AGENTS.md` instead — or leave it out entirely.

## File naming and location

Files must be placed directly in `.github/instructions/` and named `NAME.instructions.md`.
Copilot auto-discovers all `*.instructions.md` files in this directory — no explicit import or
directive is required.

## File structure

Each instruction file must begin with YAML frontmatter that gates the file to a path scope,
followed by three required sections:

```
---
applyTo: 'src/**/*.py'
---
Skill: <name>

Self-check before <action>:
1. <First check — concrete and verifiable>
2. <Second check>
3. <Third check>
...

Observed failures: <PR or issue URL>, <PR or issue URL>
```

### `applyTo:` frontmatter

The `applyTo:` field is **required**. It is a glob pattern that gates the file to specific paths:

- `applyTo: '**'` — applies repo-wide (equivalent to Claude's `@./rules/*.md` with no path filter)
- `applyTo: 'src/**/*.py'` — scopes to Python source files only
- `applyTo: 'tests/**'` — scopes to test files only

Use a narrow glob when the self-checks are only relevant for a specific subtree.

### Body sections

- **`Skill: <name>`** — the first line after frontmatter, no heading. Names the capability gate so
  the model can self-identify when to apply the file.
- **Numbered self-check list** — imperative, specific. Each item must be falsifiable: the model
  should be able to answer "yes" or "no".
- **`Observed failures:` footer** — links to the PRs or issues where the failure was documented.
  This is mandatory. A rule with no observed-failure link is a guess, not a discipline.

Target: **30 lines or fewer** per instruction file (excluding frontmatter). If a file grows past
30 lines, split it.

## Discipline: build from observed failures, not generic best-practices

The central rule of this pattern is that instruction files must be derived from documented
failures, not from intuition or generic advice. A checklist written in advance of any failure will
drift into noise — the model will pattern-match the checklist language and satisfy it
superficially. A checklist written because a specific PR broke a specific invariant three times is
sharp enough to change behavior. If you cannot fill in the `Observed failures:` footer with real
links, the instruction file is not ready to be written yet.

## Worked example

The following sketch illustrates what a `codegen.instructions.md` file might look like for a
downstream project (`pynetappfoundry`) that generates typed Python from a YANG schema and has an
ADR (ADR-0008) documenting a round-trip invariant. **This example is illustrative only** — actual
instruction files belong in downstream repos, not in this template.

```
---
applyTo: 'src/**/*.py'
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

The **discipline** (≤30 lines, numbered self-checks, observed-failures footer) is shared across
Claude Code, GitHub Copilot, Codex and Antigravity even though the file format differs:

| CLI | Directory | Load mechanism |
| :--- | :--- | :--- |
| Claude Code | `.claude/rules/` | `@./rules/*.md` in `.claude/CLAUDE.md` |
| GitHub Copilot | `.github/instructions/` | Native auto-discovery (no directive needed) |

See [`.claude/rules/README.md`](../../.claude/rules/README.md) and
[`.agents/skills/README.md`](../../.agents/skills/README.md) for the other CLI variants.

## What NOT to put in an instruction file

- **Broad workflow rules** — things like "never commit to main" or "always run `doit check`"
  belong in `AGENTS.md`, not here. Instruction files are for stack-specific self-checks, not
  universal workflow.
- **Generic best-practices** — "prefer composition over inheritance", "write type annotations" —
  these are noise. They drift into checklists the model satisfies by rote without changing
  behavior.
- **Anything not tied to an observed failure** — if you cannot cite a PR or issue where the rule
  was violated, the instruction file is not ready to be written.

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
