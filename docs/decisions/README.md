---
title: Architecture Decision Records
description: What an ADR is, the two numbering series, the ADR format, and how to create one with doit adr
audience:
  - contributors
  - ai-agents
tags:
  - adr
  - architecture
---

# Architecture Decision Records

This directory contains Architecture Decision Records (ADRs) for the project.

## What is an ADR?

An ADR documents an architectural decision: what was decided and why. The detailed discussion and specification lives in the GitHub Issue; the ADR provides a summary with links.

## Two Series

All ADRs live in this single directory, but they follow a two-series numbering convention:

| Series | Prefix | Scope |
|--------|--------|-------|
| **Template-meta** | `9XXX` | Decisions about the template itself — tooling choices, workflows, and conventions inherited by every downstream project. Created with `doit adr --template`. |
| **Project-level** | `0001+` | Decisions made by this repository's owner about this project. Created with `doit adr`. |

Downstream projects spawned from `pyproject-template` inherit the 9XXX template ADRs via the clone. A downstream project can keep, delete, or supersede any template ADR with its own 0001-series ADR.

## ADR Format

ADRs use a simplified format:

```markdown
---
title: "ADR-NNNN: Title"
description: One sentence that says what was decided.
date: YYYY-MM-DD
audience:
  - contributors
tags:
  - adr
---

# ADR-NNNN: Title

## Status
Accepted

## Decision
Brief summary of what was decided.

## Rationale
Why this decision was made.

## Related Issues
- Issue #XX: Description

## Related Documentation
- [Relevant Doc](../path/to/doc.md)
```

See [adr-template.md](adr-template.md) for the template.

The frontmatter is what [`docs/TABLE_OF_CONTENTS.md`](../TABLE_OF_CONTENTS.md) is generated from:
it lists each ADR by its `title` and `description`, under each `audience`. The `title` is quoted
because every ADR title holds a colon, which YAML otherwise reads as a key. `doit adr` fills in
the title and the date; the description is yours to write.

## Creating a New ADR

```bash
# Project-level ADR (0001-series) — interactive
doit adr --title="Your decision title"

# Project-level ADR — non-interactive
doit adr --title="Use Redis" --body="## Status\nAccepted\n..."
doit adr --title="Use Redis" --body-file=adr.md

# Template-meta ADR (9XXX-series) — add --template
doit adr --title="Use some tool" --template
doit adr --title="Use some tool" --template --body-file=adr.md
```

Use `--template` when the decision is about the template's own tooling, workflow, or conventions (something every downstream project will inherit). Use the default (project-level) for decisions specific to this project.

A body passed with `--body` or `--body-file` gets the template's frontmatter unless it starts with
its own. Either way, `doit adr` sets the title and fills in the date. If the description is still
the template's placeholder, `doit adr` says so; replace it before you commit, because `doit check`
fails on an ADR that keeps it.

## When to Create an ADR

Create an ADR when:
- Introducing a new tool, framework, or library
- Changing development workflow or processes
- Making decisions that affect project architecture

The Issue contains the full discussion; the ADR summarizes the outcome.

## ADR Statuses

- **Accepted**: Decision is in effect
- **Deprecated**: No longer relevant (kept for history)
- **Superseded**: Replaced by a newer ADR

## Index

### Template-meta ADRs (9XXX)

| ADR | Title | Status |
|-----|-------|--------|
| [9001](9001-use-uv-for-package-management.md) | Use uv for package management | Accepted |
| [9002](9002-use-doit-for-task-automation.md) | Use doit for task automation | Accepted |
| [9003](9003-use-ruff-for-linting-and-formatting.md) | Use ruff for linting and formatting | Accepted |
| [9004](9004-auto-discover-doit-tasks.md) | Auto-discover doit tasks from modules | Accepted |
| [9005](9005-ai-agent-command-restrictions.md) | AI agent command restrictions via hooks | Accepted |
| [9006](9006-merge-gate-workflow.md) | Merge-gate workflow requiring ready-to-merge label | Accepted |
| [9007](9007-use-mypy-for-type-checking.md) | Use mypy for static type checking | Accepted |
| [9008](9008-pr-based-development-workflow.md) | PR-based development workflow | Accepted |
| [9009](9009-use-pre-commit-hooks-for-quality-gates.md) | Use pre-commit hooks for quality gates | Accepted |
| [9010](9010-use-conventional-commits-format.md) | Use conventional commits format | Accepted |
| [9011](9011-use-pytest-for-testing.md) | Use pytest for testing | Accepted |
| [9012](9012-use-mkdocs-with-material-theme-for-documentation.md) | Use mkdocs with Material theme for documentation | Accepted |
| [9013](9013-python-version-support-policy.md) | Python version support policy with bookend CI strategy | Accepted |
| [9014](9014-use-click-for-application-cli.md) | Use click for application CLI | Accepted |
| [9015](9015-install-tools-framework-archive-extraction-and-custom-urls.md) | install_tools framework: archive extraction and custom URLs | Accepted |
| [9016](9016-unify-adr-directories.md) | Unify ADR directories under docs/decisions | Accepted |
| [9017](9017-template-tooling-and-its-tests-are-template-owned.md) | Template tooling and its tests are template-owned | Accepted |
| [9018](9018-agentsmd-carries-only-shared-always-on-instructions.md) | AGENTS.md carries only shared, always-on instructions | Accepted |
| [9019](9019-the-dangerous-command-hook-is-a-guardrail-not-a-security-boundary.md) | The dangerous-command hook is a guardrail, not a security boundary | Accepted |
| [9020](9020-a-template-version-is-a-commit-sha.md) | A template version is a commit SHA | Accepted |
| [9021](9021-a-pr-may-target-the-unmerged-branch-it-builds-on.md) | A PR may target the unmerged branch it builds on | Accepted |
| [9022](9022-worktrees-live-in-worktrees-each-with-its-own-environment.md) | Worktrees live in worktrees/, each with its own environment | Accepted |
| [9023](9023-shared-workflow-skills-live-in-agents-skills-generated-for-claude.md) | Shared workflow skills live once in .agents/skills/ and are generated for Claude | Accepted |
| [9024](9024-one-implement-issue-skill-takes-an-issue-to-a-green-pr.md) | One implement-issue skill takes an issue to a green PR | Accepted |
| [9025](9025-delegated-agents-receive-github-data-from-the-host-and-run-without-network.md) | Delegated agents receive GitHub data from the host and run without network | Accepted |
| [9026](9026-doc-scanning-tests-honor-sync-excludetoml-and-discover-markdown-via-git.md) | Doc-scanning tests honor sync-exclude.toml and discover markdown via git | Accepted |

### Project-level ADRs (0001+)

| ADR | Title | Status |
|-----|-------|--------|

_(No project-level ADRs yet.)_
