---
name: claude-adversarial-review
description: Use to delegate a steerable adversarial review of the current changes from a Copilot CLI session to Claude Code via `claude -p`. Pressure-tests direction, hidden assumptions, and alternatives; does not modify files.
---

# Delegate Adversarial Review to Claude (from Copilot)

Hand off a steerable adversarial review to Claude Code via shell — pressure-tests design choices, assumptions, and alternative approaches.

## When to use

Use this skill when the user explicitly wants an adversarial review by Claude Code (not by Copilot). This is the Copilot-host bridge equivalent of Claude's `/claude:adversarial-review`.

Optional focus area can be passed in.

## Instructions

1. Run Claude Code non-interactively. Adversarial review challenges direction, not just code details.

   ```bash
   claude -p 'Run an adversarial review of the current uncommitted changes and the current branch vs main. Read-only. Be skeptical and steerable: pressure-test design choices, hidden assumptions, tradeoffs, alternative approaches, failure modes (auth, data loss, races, rollback, reliability). 1) Run `git status`, `git diff`, `git log main..HEAD`. 2) Read AGENTS.md and related ADRs. 3) Ask: was this the right approach? Would a different design be safer or simpler? What edge cases are missed? What hidden coupling exists? 4) Print findings to stdout in a structured format (Direction Critique / Hidden Assumptions / Failure Modes / Alternatives Worth Considering). Do NOT modify any files. Focus area (optional): <focus>. If the focus area names any of `errors`, `tests`, `types`, `comments`, read `docs/development/ai/review-focus-areas.md` and apply those checklists in addition to the general review.'
   ```

2. After Claude returns:
   - Summarize the adversarial findings to the user.
   - This is a *challenge* — the user decides whether to accept, defer, or push back.
   - Do not auto-apply suggestions.
