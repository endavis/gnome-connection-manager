---
name: delegate-copilot-plan
description: Delegate planning for a GitHub issue to GitHub Copilot CLI. Hands the planning work to Copilot via `copilot --allow-all -p` and returns the plan to the calling agent.
---

# Delegate Plan to Copilot

Hand off planning work for a GitHub issue to GitHub Copilot CLI.

## When to use

Use this skill when the user explicitly wants planning done by Copilot (not the host agent itself).

Expected prompt shape:

- `$delegate-copilot-plan plan issue 399`
- `$delegate-copilot-plan delegate planning for #399 to Copilot`

If the issue number is missing, ask for it before continuing.

## Instructions

1. Confirm the issue number from the user's request.
2. Run Copilot CLI non-interactively. Copilot requires `--allow-all` for non-interactive mode. Hybrid C: prefer the existing `/copilot-plan` skill if available, otherwise inline workflow. Copilot uses hyphen naming for skills because skill names cannot contain colons.

   ```bash
   copilot --allow-all -p 'Plan the implementation for GitHub issue #<n> in the current repository. If the /copilot-plan skill is available, activate it for this issue. Otherwise, follow this workflow: 1) Run `gh issue view <n> --json title,body,labels` to read the issue. 2) Read AGENTS.md to understand the workflow and conventions. 3) Explore the relevant files. 4) Draft a plan with three sections: Implementation Plan, Test Plan, Validation Plan. 5) Print the full plan to stdout. Do NOT post a comment to the issue — the user reviews and posts.'
   ```

3. Capture stdout and summarize the plan to the user.
4. If the user wants revisions, invoke Copilot again with their feedback appended.
5. Do NOT post the plan as a comment yourself — the user owns that step.
