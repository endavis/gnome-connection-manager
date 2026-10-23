---
name: implement-worker
description: >-
  Performs the coding step of the implement-issue skill after the branch exists
  (and a plan comment, when one was made). Runs the skill's Coder brief: reads
  project rules, reads the plan (or the issue body) from the context directory
  the parent wrote with `doit delegation_context`, edits files, writes tests,
  and runs `doit check`.
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
- Any **issue-specific notes** or scope clarifications.

## Constraints

- **Do NOT switch branches.** The parent has already created or resumed the correct branch.
- **Do NOT commit.** Committing and opening the PR are the parent `implement-issue` run's Step 6,
  not yours.
- **Do NOT enter plan mode.** Do not call `EnterPlanMode`. You run with `permissionMode: default` so
  you can edit files directly.
- **All new code must be type-annotated** (mypy strict mode is enforced by `doit check`).

See the Coder brief in `.agents/skills/implement-issue/SKILL.md` for the full step list (read the
rules, read the plan or issue body from the context directory, implement with tests, run `doit
check`, return a summary).
