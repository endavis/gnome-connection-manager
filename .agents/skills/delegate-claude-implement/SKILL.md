---
name: delegate-claude-implement
description: Delegate implementation of a GitHub issue to Claude Code. Hands implementation work to Claude via `claude -p` and returns the result to the calling agent.
---

# Delegate Implement to Claude

Hand off implementation work for a GitHub issue to Claude Code.

## When to use

Use this skill when the user explicitly wants implementation done by Claude (not the host agent itself).

Expected prompt shape:

- `$delegate-claude-implement implement issue 399`
- `$delegate-claude-implement delegate implementation of #399 to Claude`

If the issue number is missing, ask for it before continuing.

## Instructions

1. Confirm the issue number from the user's request.
2. Run Claude Code non-interactively. Hybrid C: prefer the existing `/claude:implement` command if available, otherwise inline workflow.

   ```bash
   claude -p 'Implement GitHub issue #<n> in the current repository. If the /claude:implement command is available, run it for this issue. Otherwise, follow this workflow: 1) Read the plan comment from issue #<n> via `gh issue view <n> --json comments`. 2) Read AGENTS.md for branch naming and commit conventions. 3) Create or check out the branch `<type>/<n>-<slug>` (do not commit to main). 4) Implement the changes per the plan. 5) Run `doit check` to validate. Do NOT push the branch or open a PR — the user reviews first.'
   ```

3. Capture stdout and summarize what was implemented and the `doit check` result.
4. Show the user the changed files (`git status`, `git diff --stat`).
5. Do NOT push or open a PR yourself.
