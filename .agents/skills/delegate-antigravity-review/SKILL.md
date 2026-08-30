---
name: delegate-antigravity-review
description: Delegate a read-only code review of current changes to Antigravity CLI (agy). Hands the review to Antigravity via `agy -p` and returns findings to the calling agent.
---

# Delegate Review to Antigravity

Hand off a read-only code review of current changes to Antigravity CLI (`agy`).

## When to use

Use this skill when the user explicitly wants a review done by Antigravity (not the host agent itself).

Expected prompt shape:

- `$delegate-antigravity-review review the current changes`
- `$delegate-antigravity-review have Antigravity review this branch`

The user may include optional focus text after the trigger.

## Instructions

1. Capture any focus text from the user's request.
2. Run Antigravity non-interactively. `agy` needs `--add-dir` pointed at the repo root so it loads the workspace (and the shared dangerous-command hook); `--dangerously-skip-permissions` auto-approves routine tools while that hook still hard-blocks unsafe ones.

   ```bash
   agy -p 'Review the current uncommitted changes and the current branch vs main, read-only. If an Antigravity review skill (antigravity-review) is available, use it. Otherwise: 1) Run `git status` and `git diff`. 2) Run `git log main..HEAD --oneline` for branch context. 3) Read AGENTS.md and any relevant ADRs in docs/decisions/. 4) Identify correctness issues, risks, missing tests, style/convention violations, and concrete suggestions. 5) Print findings to stdout in a structured format (Summary / Issues / Suggestions). Do NOT modify any files. Focus area (optional): <focus>' --dangerously-skip-permissions --add-dir "$(git rev-parse --show-toplevel)"
   ```

3. Capture stdout and summarize the review findings.
4. Highlight blocking issues vs nits.
5. Do NOT auto-apply suggestions — the user decides what to act on.
