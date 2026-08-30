---
name: delegate-copilot-implement
description: Delegate implementation of a GitHub issue to GitHub Copilot CLI. Hands implementation work to Copilot via `copilot --allow-all -p` and returns the result to the calling agent.
---

# Delegate Implement to Copilot

Hand off implementation work for a GitHub issue to GitHub Copilot CLI.

## When to use

Use this skill when the user explicitly wants implementation done by Copilot (not the host agent itself).

Expected prompt shape:

- `$delegate-copilot-implement implement issue 399`
- `$delegate-copilot-implement delegate implementation of #399 to Copilot`

If the issue number is missing, ask for it before continuing.

## Instructions

1. Confirm the issue number from the user's request.
2. Run Copilot CLI non-interactively. Copilot requires `--allow-all` for non-interactive mode. Hybrid C: prefer the existing `/copilot-implement` skill if available, otherwise inline workflow. Copilot uses hyphen naming for skills because skill names cannot contain colons.

   ```bash
   copilot --allow-all -p 'Implement GitHub issue #<n> in the current repository. If the /copilot-implement skill is available, activate it for this issue. Otherwise, follow this workflow: 1) Read the plan comment from issue #<n> via `gh issue view <n> --json comments`. 2) Read AGENTS.md for branch naming and commit conventions. 3) Create or check out the branch `<type>/<n>-<slug>` (do not commit to main). 4) Implement the changes per the plan. 5) Run `doit check` to validate. Do NOT push the branch or open a PR — the user reviews first.'
   ```

3. Capture stdout and summarize what was implemented and the `doit check` result.
4. Show the user the changed files (`git status`, `git diff --stat`).
5. Do NOT push or open a PR yourself.
