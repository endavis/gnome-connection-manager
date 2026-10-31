---
title: "ADR-9027: implement-issue works in a per-issue worktree"
description: implement-issue always works in a per-issue worktree under worktrees/, so several issues can run at once
date: 2026-10-29
audience:
  - contributors
tags:
  - adr
---

# ADR-9027: implement-issue works in a per-issue worktree

## Status

Accepted

## Decision

**`implement-issue` always works in a per-issue worktree under `worktrees/`, created with
`doit worktree`, so several issues can run at once and the main checkout is never switched.**

1. Step 1 resumes in place when the session is already on `<type>/<n>-*`, in the main checkout or a
   worktree. Otherwise it `cd`s into an existing worktree on that branch. If a local branch exists
   with no worktree it stops and asks, because `doit worktree` uses `git worktree add -b`, which
   fails on an existing branch. If none of these hold it runs
   `uv run doit worktree --branch=<type>/<n>-<desc>` and `cd`s into the new worktree.
2. The old `git checkout main && git pull` is gone: `doit worktree` fetches `origin/main` itself and
   branches from it with `--no-track`.
3. Every later step runs from the worktree through `uv run`, never with `--active`. The delegation
   context directory is an absolute path inside the worktree, and the Planner and Coder briefs
   receive the worktree root as an absolute path.
4. Step 8 reports the worktree path and the merge command, `uv run doit pr_merge --pr=<pr>
   --auto-close`, run from the main checkout (ADR-9022).

## Rationale

Step 1 used to run `git checkout main && git pull && git checkout -b ...` in whatever checkout the
session was in, so two sessions in the main checkout switched branches under each other. Worktrees
already solved this when set up by hand (ADR-9022); the skill never created one.

**Rejected: a worktree only when the main checkout is busy.** It is cheaper per issue, but behavior
would depend on the checkout's state, which makes the skill harder to predict and to test. Always
using a worktree has one path.

**Known limits.**

- `$CLAUDE_PROJECT_DIR` hooks run from the main checkout, so a PR that changes a hook does not run
  its own hook version in that session.
- `ruff-fix-on-edit.py` skips paths under `worktrees/`, which fail its allowed roots (read from the
  code, not run); `uv run doit lint` inside `doit check` is the backstop.
- Whether a shell `cd` persists is unverified on Copilot, Codex and `agy`, so the skill treats the
  working directory as non-persistent on every host.
- Two worktrees changing the same file still conflict at merge time.
- Each worktree has its own `.venv`; a shared uv cache (#1094) keeps that cheap.

## Consequences

- Running several issues means one session per issue, each started from the main checkout.
- The walkthrough's "When your checkout holds other work" section becomes the rare manual case.
- A worktree stays until its PR is merged with `doit pr_merge`.

## Related Issues

- Issue #1095: implement-issue works in a worktree per issue
- Issue #1094: shared uv cache, which keeps per-issue worktrees cheap

## Related Documentation

- [First 5 Minutes](../development/ai/first-5-minutes.md) — the walkthrough step that creates the worktree
- [Slash Commands and Workflows](../development/ai/slash-commands.md) — the `implement issue N` entry
- [Cross-Agent Delegation Matrix](../development/ai/cross-agent-delegation.md) — the context directory inside the worktree
- [doit tasks reference: worktree](../development/doit-tasks-reference.md#worktree)
- [ADR-9022](9022-worktrees-live-in-worktrees-each-with-its-own-environment.md) — where worktrees live
- [ADR-9024](9024-one-implement-issue-skill-takes-an-issue-to-a-green-pr.md) — the skill this changes
