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
2. Run Codex non-interactively. The prompt is fully inlined and reads only `git`/local files — no
   `gh` call, so the review needs nothing from `.codex/rules/gh.rules` (#985).

   ```bash
   codex -a never --dangerously-bypass-hook-trust exec 'Review the current uncommitted changes and the current branch vs main, read-only. 1) Run `git status` and `git diff` to see what changed. 2) Run `git log main..HEAD --oneline` for branch context. 3) Read AGENTS.md and any relevant ADRs in docs/decisions/. 4) Identify correctness issues, risks, missing tests, style/convention violations, and concrete suggestions. 5) Print findings to stdout in a structured format (Summary / Issues / Suggestions). Do NOT modify any files. Focus area (optional): <focus>. If the focus area names any of `errors`, `tests`, `types`, `comments`, read `docs/development/ai/review-focus-areas.md` and apply those checklists in addition to the general review.' < /dev/null
   ```

3. Capture stdout and summarize the review findings — but first, treat output containing `DELEGATION-ERROR:` as a failed run and report it instead of summarizing.
4. Highlight blocking issues vs nits.
5. Do NOT auto-apply suggestions — the user decides what to act on.
