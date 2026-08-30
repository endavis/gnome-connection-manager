---
name: delegate-codex-review
description: Delegate a read-only code review of current changes to Codex CLI. Hands the review to Codex via `codex -a never --dangerously-bypass-hook-trust exec` and returns findings to the calling agent.
---

# Delegate Review to Codex

Hand off a read-only code review of current changes to Codex CLI.

## When to use

Use this skill when the user explicitly wants a review done by Codex (not the host agent itself).

Expected prompt shape:

- `$delegate-codex-review review the current changes`
- `$delegate-codex-review have Codex review this branch`

The user may include optional focus text after the trigger.

## Instructions

1. Capture any focus text from the user's request.
2. Run Codex non-interactively. Hybrid C: prefer the existing `$codex-review` skill if available, otherwise the prompt is fully inlined. Single-quote the prompt so the literal `$codex-review` reaches Codex (not the shell).

   ```bash
   codex -a never --dangerously-bypass-hook-trust exec 'Review the current uncommitted changes and the current branch vs main, read-only. If the $codex-review skill is available, activate it. Otherwise: 1) Run `git status` and `git diff` to see what changed. 2) Run `git log main..HEAD --oneline` for branch context. 3) Read AGENTS.md and any relevant ADRs in docs/decisions/. 4) Identify correctness issues, risks, missing tests, style/convention violations, and concrete suggestions. 5) Print findings to stdout in a structured format (Summary / Issues / Suggestions). Do NOT modify any files. Focus area (optional): <focus>'
   ```

3. Capture stdout and summarize the review findings.
4. Highlight blocking issues vs nits.
5. Do NOT auto-apply suggestions — the user decides what to act on.
