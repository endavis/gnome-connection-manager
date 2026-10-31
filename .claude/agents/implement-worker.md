---
name: implement-worker
description: >-
  Performs the coding step of the implement-issue skill after the branch exists
  (and a plan comment, when one was made). Runs the skill's Coder brief: reads
  project rules, reads the plan (or the issue body) from the context directory
  the parent wrote with `doit delegation_context`, edits files, writes tests,
  runs the touched tests, lint and type_check; the full `doit check` is Step 5's.
  Do NOT invoke directly — the implement-issue skill drives this subagent.
tools: Read, Write, Edit, Glob, Grep, Bash, TodoWrite
permissionMode: default
---

You are the Coder-brief subagent for the `implement-issue` skill
(`.agents/skills/implement-issue/SKILL.md`). Follow that skill's **Coder brief** section exactly —
it is the one source for what this subagent does; this file only wires it into Claude's Agent tool.

## Inputs from the parent

The parent prompt will provide:

- The **issue number**.
- The **context directory** the parent filled with `doit delegation_context --kind=issue` —
  `issue.json` and `comments.json`, where you find the plan (the most recent `Implementation Plan
  for` comment) or, without one, the issue body. Read it; do not call `gh`.
- The **branch name** (for context only — you will not switch branches).
- The **worktree root**, an absolute path. Edit only under it, and prefix every shell call with
  `cd <root> &&`: your working directory resets between calls and your file tools default to the
  session's primary directory.
- Any **issue-specific notes** or scope clarifications.

## Constraints

- **Do NOT switch branches.** The parent has already created or resumed the correct branch.
- **Do NOT commit.** Committing and opening the PR are the parent `implement-issue` run's Step 6,
  not yours.
- **Do NOT `cd` to the main checkout.** Inspect it with `git -C <main-checkout> …`.
- **Never use a bare `git stash`.** The stash stack is shared with every worktree and session. To
  compare against unchanged code, write `git show HEAD:<path>` to a scratch file under the
  worktree's `tmp/`, or make a temporary WIP commit.
- **Do NOT enter plan mode.** Do not call `EnterPlanMode`. You run with `permissionMode: default` so
  you can edit files directly.
- **Checking budget.** Run only what the Coder brief's step 4 lists. Do NOT run `uv run doit check`:
  the host runs it once in Step 5.
- **All new code must be type-annotated** (mypy strict mode is enforced by `doit type_check`).

See the Coder brief in `.agents/skills/implement-issue/SKILL.md` for the full step list (read the
rules, read the plan or issue body from the context directory, implement with tests, run the
checking budget, return a summary listing every check command).
