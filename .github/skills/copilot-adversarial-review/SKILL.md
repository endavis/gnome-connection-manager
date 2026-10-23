---
name: copilot-adversarial-review
description: Use when running a steerable adversarial review of the current changes from a Copilot CLI session. Pressure-tests direction, hidden assumptions, failure modes, and alternatives. Read-only — no files are modified.
---

# Adversarial Review (Copilot)

Run a steerable adversarial review using GitHub Copilot — pressure-tests design choices, assumptions, and alternative approaches.

## When to use

Use this skill when the user wants Copilot to challenge the current changes. This is Copilot's self-action equivalent of `/claude:adversarial-review` / `$codex-adversarial-review`.

Optional focus area can be given as a freeform argument.

## Instructions

**Read-only.** Review and report — do not edit files, commit, or push. Findings go to the user and the PR; any fix is a separate change the user asks for.

This skill runs inline in the active Copilot session. Copilot performs the adversarial review directly.

### Step 1: Gather review context

1. Check what changed:
   ```bash
   git status
   git diff
   git log main..HEAD --oneline
   ```
2. Read project standards:
   - Read `AGENTS.md`
   - Check for relevant ADRs in `docs/decisions/`

### Step 2: Challenge the changes

Be skeptical and steerable. Pressure-test:

- **Direction Critique:** Was this the right approach? Is the design sound? Would a different architecture be safer or simpler?
- **Hidden Assumptions:** What implicit constraints does this code depend on? What breaks if those assumptions don't hold?
- **Failure Modes:** What are the auth, data loss, race condition, rollback, and reliability failure modes? What happens at scale or under adversarial input?
- **Alternatives Worth Considering:** What other approaches exist? Are there simpler paths that achieve the same goal with less risk or complexity?

Apply the optional focus area if the user supplied one. If the focus area names any of `errors`, `tests`, `types`, `comments`, read `docs/development/ai/review-focus-areas.md` and apply those checklists in addition to the general review.

### Step 3: Present findings

Format the adversarial review as:

```markdown
## Adversarial Review

### Direction Critique
- (Was this the right approach? Are there design-level concerns?)

### Hidden Assumptions
- (What must be true for this code to work correctly?)

### Failure Modes
- (What breaks under stress, adversarial input, or at scale?)

### Alternatives Worth Considering
- (Simpler or safer paths that might achieve the same goal)

---
*Adversarial Review by: Copilot* | *Date: <today's date>*
```

This is a *challenge* — the user decides whether to accept, defer, or push back on each finding.

### Step 4: Ask about posting

If a PR exists for the current branch, ask the user:

```bash
gh pr view --json number,headRefName 2>/dev/null
```

"Would you like to post this adversarial review as a PR comment? (yes / no)"

If yes:
```bash
gh pr comment <PR_NUMBER> --body "<adversarial review>"
```
