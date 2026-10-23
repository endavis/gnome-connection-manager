---
name: codex-adversarial-review
description: Use to delegate a steerable adversarial review of the current changes from a Copilot CLI session to Codex CLI via `codex -a never --dangerously-bypass-hook-trust exec`. Pressure-tests direction, hidden assumptions, and alternatives; does not modify files.
---

# Delegate Adversarial Review to Codex (from Copilot)

Hand off a steerable adversarial review to Codex CLI via shell — pressure-tests design choices, assumptions, and alternative approaches.

## When to use

Use this skill when the user explicitly wants an adversarial review by Codex (not by Copilot). This is the Copilot-host bridge equivalent of Codex's `$codex-adversarial-review`.

Optional focus area can be passed in.

## Instructions

1. Run Codex non-interactively. Adversarial review challenges direction, not just code details. The
   prompt is fully inlined and reads only `git`/local files — no `gh` call, so it needs nothing from
   `.codex/rules/gh.rules` (#985).

   ```bash
   codex -a never --dangerously-bypass-hook-trust exec 'Run an adversarial review of the current uncommitted changes and the current branch vs main. Read-only. Be skeptical and steerable: pressure-test design choices, hidden assumptions, tradeoffs, alternative approaches, failure modes (auth, data loss, races, rollback, reliability). 1) Run `git status`, `git diff`, `git log main..HEAD`. 2) Read AGENTS.md and related ADRs. 3) Ask: was this the right approach? Would a different design be safer or simpler? What edge cases are missed? What hidden coupling exists? 4) Print findings to stdout in a structured format (Direction Critique / Hidden Assumptions / Failure Modes / Alternatives Worth Considering). Do NOT modify any files. Focus area (optional): <focus>. If the focus area names any of `errors`, `tests`, `types`, `comments`, read `docs/development/ai/review-focus-areas.md` and apply those checklists in addition to the general review.' < /dev/null
   ```

2. After Codex returns:
   - First, treat output containing `DELEGATION-ERROR:` as a failed run and report it instead of summarizing.
   - Summarize the adversarial findings to the user.
   - This is a *challenge* — the user decides whether to accept, defer, or push back.
   - Do not auto-apply suggestions.
