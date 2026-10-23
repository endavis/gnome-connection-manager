---
name: codex-review
description: Use to delegate a read-only code review of the current changes from a Copilot CLI session to Codex CLI via `codex -a never --dangerously-bypass-hook-trust exec`. Captures findings from stdout; does not modify files.
---

# Delegate Review to Codex (from Copilot)

Hand off a read-only code review of the current changes to Codex CLI via shell.

## When to use

Use this skill when the user explicitly wants a review by Codex (not by Copilot). This is the Copilot-host bridge equivalent of Codex's `$codex-review`.

Optional focus area can be passed in.

## Instructions

1. Run Codex non-interactively. The prompt is fully inlined and reads only `git`/local files — no
   `gh` call, so the review needs nothing from `.codex/rules/gh.rules` (#985).

   ```bash
   codex -a never --dangerously-bypass-hook-trust exec 'Review the current uncommitted changes and the current branch vs main, read-only. 1) Run `git status` and `git diff` to see what changed. 2) Run `git log main..HEAD --oneline` for branch context. 3) Read AGENTS.md and any relevant ADRs in docs/decisions/. 4) Identify correctness issues, risks, missing tests, style/convention violations, and concrete suggestions. 5) Print findings to stdout in a structured format (Summary / Issues / Suggestions). Do NOT modify any files. Focus area (optional): <focus>. If the focus area names any of `errors`, `tests`, `types`, `comments`, read `docs/development/ai/review-focus-areas.md` and apply those checklists in addition to the general review.' < /dev/null
   ```

2. After Codex returns:
   - First, treat output containing `DELEGATION-ERROR:` as a failed run and report it instead of summarizing.
   - Summarize the review findings to the user.
   - Highlight any blocking issues vs nits.
   - The user decides what to act on; do not auto-apply suggestions.
