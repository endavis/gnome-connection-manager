---
name: delegate-antigravity-implement
description: Delegate implementation of a GitHub issue to Antigravity CLI (agy). Hands implementation work to Antigravity via `agy -p` and returns the result to the calling agent.
---

# Delegate Implement to Antigravity

Hand off implementation work for a GitHub issue to Antigravity CLI (`agy`).

## When to use

Use this skill when the user explicitly wants implementation done by Antigravity (not the host agent itself).

Expected prompt shape:

- `$delegate-antigravity-implement implement issue 399`
- `$delegate-antigravity-implement delegate implementation of #399 to Antigravity`

If the issue number is missing, ask for it before continuing.

## Instructions

1. Confirm the issue number from the user's request.
2. Run Antigravity non-interactively. `agy` needs `--add-dir` pointed at the repo root so it loads the workspace (and the shared dangerous-command hook); `--dangerously-skip-permissions` auto-approves routine tools while that hook still hard-blocks unsafe ones.

   ```bash
   agy -p 'Implement GitHub issue #<n> in the current repository. If an Antigravity implementation skill (antigravity-implement) is available, use it. Otherwise, follow this workflow: 1) Read the plan comment from issue #<n> via `gh issue view <n> --json comments`. 2) Read AGENTS.md for branch naming and commit conventions. 3) Create or check out the branch `<type>/<n>-<slug>` (do not commit to main). 4) Implement the changes per the plan. 5) Run `doit check` to validate. Do NOT push the branch or open a PR — the user reviews first.' --dangerously-skip-permissions --add-dir "$(git rev-parse --show-toplevel)"
   ```

3. Capture stdout and summarize what was implemented and the `doit check` result.
4. Show the user the changed files (`git status`, `git diff --stat`).
5. Do NOT push or open a PR yourself.
