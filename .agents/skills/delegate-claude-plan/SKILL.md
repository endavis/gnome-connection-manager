---
name: delegate-claude-plan
description: Delegate planning for a GitHub issue to Claude Code. Hands the planning work to Claude via `claude -p` and returns the plan to the calling agent.
---

# Delegate Plan to Claude

Hand off planning work for a GitHub issue to Claude Code.

## When to use

Use this skill when the user explicitly wants planning done by Claude (not the host agent itself).

Expected prompt shape:

- `$delegate-claude-plan plan issue 399`
- `$delegate-claude-plan delegate planning for #399 to Claude`

If the issue number is missing, ask for it before continuing.

## Instructions

1. Confirm the issue number from the user's request.
2. Run Claude Code non-interactively. Hybrid C: prefer the existing `/claude:plan` command if available, otherwise inline workflow.

   ```bash
   claude -p 'Plan the implementation for GitHub issue #<n> in the current repository. If the /claude:plan command is available, run it for this issue. Otherwise, follow this workflow: 1) Run `gh issue view <n> --json title,body,labels` to read the issue. 2) Read AGENTS.md to understand the workflow and conventions. 3) Explore the relevant files. 4) Draft a plan with three sections: Implementation Plan, Test Plan, Validation Plan. 5) Print the full plan to stdout. Do NOT post a comment to the issue — the user reviews and posts.'
   ```

3. Capture stdout and summarize the plan to the user.
4. If the user wants revisions, invoke Claude again with their feedback appended.
5. Do NOT post the plan as a comment yourself — the user owns that step.
