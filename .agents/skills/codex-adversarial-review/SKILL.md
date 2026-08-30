---
name: codex-adversarial-review
description: Use when running a steerable adversarial review from a Codex session. Pressure-tests design choices, hidden assumptions, and alternative approaches for the current changes.
---

# Adversarial Review

Run a steerable adversarial review using Codex — pressure-tests design choices, assumptions, and alternative approaches.

## When to use

Use this skill when the user wants Codex to challenge the current changes adversarially rather than give a standard code review.

Expected prompt shape:

- `$codex-adversarial-review challenge the design of the current changes`
- `$codex-adversarial-review pressure-test this branch`

The user may include focus text after the trigger.

## Instructions

**Read-only.** Review and report — do not edit files, commit, or push. Findings go to the user and the PR; any fix is a separate change the user asks for.

1. Check the current state of changes:
   ```bash
   git status
   git diff
   git log main..HEAD --oneline
   ```
   - If there are no uncommitted changes and no branch commits beyond main, tell the user there is nothing to review and stop.

2. Read project standards:
   - Read `AGENTS.md`
   - Check for relevant ADRs in `docs/decisions/`

3. Challenge the changes by pressure-testing:
   - **Direction Critique:** Was this the right approach? Would a different design be safer or simpler?
   - **Hidden Assumptions:** What implicit constraints does this code depend on? What breaks if those assumptions don't hold?
   - **Failure Modes:** Auth, data loss, race conditions, rollback, reliability failure modes?
   - **Alternatives Worth Considering:** Simpler or safer paths that might achieve the same goal?

4. Format findings as:
   ```markdown
   ## Adversarial Review

   ### Direction Critique
   - (Was this the right approach? Design-level concerns?)

   ### Hidden Assumptions
   - (What must be true for this code to work correctly?)

   ### Failure Modes
   - (What breaks under stress, adversarial input, or at scale?)

   ### Alternatives Worth Considering
   - (Simpler or safer paths that might achieve the same goal)

   ---
   *Adversarial Review by: Codex* | *Date: <today's date>*
   ```

5. Present findings to the user. This is a *challenge* — the user decides whether to accept, defer, or push back.

6. If a PR exists for the current branch, ask whether to post as a PR comment:
   ```bash
   gh pr view --json number,headRefName 2>/dev/null
   ```
   If yes: `gh pr comment <PR_NUMBER> --body "<adversarial review>"`
