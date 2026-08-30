---
name: delegate-copilot-review
description: Delegate a read-only code review of current changes to GitHub Copilot CLI. Hands the review to Copilot via `copilot --allow-all -p` and returns findings to the calling agent.
---

# Delegate Review to Copilot

Hand off a read-only code review of current changes to GitHub Copilot CLI.

## When to use

Use this skill when the user explicitly wants a review done by Copilot (not the host agent itself).

Expected prompt shape:

- `$delegate-copilot-review review the current changes`
- `$delegate-copilot-review have Copilot review this branch`

The user may include optional focus text after the trigger.

## Instructions

1. Capture any focus text from the user's request.
2. Run Copilot CLI non-interactively. Copilot requires `--allow-all` for non-interactive mode. Hybrid C: prefer the existing `/copilot-review` skill if available, otherwise the prompt is fully inlined. Copilot uses hyphen naming for skills because skill names cannot contain colons.

   ```bash
   copilot --allow-all -p 'Review the current uncommitted changes and the current branch vs main, read-only. If the /copilot-review skill is available, activate it. Otherwise: 1) Run `git status` and `git diff` to see what changed. 2) Run `git log main..HEAD --oneline` for branch context. 3) Read AGENTS.md and any relevant ADRs in docs/decisions/. 4) Identify correctness issues, risks, missing tests, style/convention violations, and concrete suggestions. 5) Print findings to stdout in a structured format (Summary / Issues / Suggestions). Do NOT modify any files. Focus area (optional): <focus>'
   ```

3. Capture stdout and summarize the review findings.
4. Highlight blocking issues vs nits.
5. Do NOT auto-apply suggestions — the user decides what to act on.
