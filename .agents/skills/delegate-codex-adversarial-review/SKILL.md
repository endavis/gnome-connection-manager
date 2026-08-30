---
name: delegate-codex-adversarial-review
description: Delegate a steerable adversarial review of current changes to Codex CLI. Hands an adversarial-review to Codex via `codex -a never --dangerously-bypass-hook-trust exec` and returns the challenge to the calling agent.
---

# Delegate Adversarial Review to Codex

Hand off a steerable adversarial review to Codex CLI — pressure-tests design choices, assumptions, and alternative approaches.

## When to use

Use this skill when the user explicitly wants an adversarial / challenge review done by Codex (not the host agent itself).

Expected prompt shape:

- `$delegate-codex-adversarial-review challenge the design of the current changes`
- `$delegate-codex-adversarial-review have Codex pressure-test this branch`

The user may include focus text after the trigger.

## Instructions

1. Capture any focus text from the user's request.
2. Run Codex non-interactively. Adversarial review challenges direction, not just code details. Single-quote the prompt so the literal `$codex-adversarial-review` reaches Codex (not the shell).

   ```bash
   codex -a never --dangerously-bypass-hook-trust exec 'Run an adversarial review of the current uncommitted changes and the current branch vs main. Read-only. If the $codex-adversarial-review skill is available, activate it. Otherwise be skeptical and steerable: pressure-test design choices, hidden assumptions, tradeoffs, alternative approaches, failure modes (auth, data loss, races, rollback, reliability). 1) Run `git status`, `git diff`, `git log main..HEAD`. 2) Read AGENTS.md and related ADRs. 3) Ask: was this the right approach? Would a different design be safer or simpler? What edge cases are missed? What hidden coupling exists? 4) Print findings to stdout in a structured format (Direction Critique / Hidden Assumptions / Failure Modes / Alternatives Worth Considering). Do NOT modify any files. Focus area (optional): <focus>'
   ```

3. Capture stdout and summarize the adversarial findings.
4. This is a *challenge* — the user decides whether to accept, defer, or push back.
5. Do NOT auto-apply suggestions.
