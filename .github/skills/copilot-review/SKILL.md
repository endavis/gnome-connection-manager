---
name: copilot-review
description: Use when reviewing the current branch's PR from a Copilot CLI session. Reads the diff, evaluates correctness/style/testing/security/architecture, drafts a structured review, and posts it after user approval.
---

# Review PR (Copilot)

Run a single-agent PR review using GitHub Copilot.

## When to use

Use this skill when the user wants Copilot to review the PR for the current branch. This is Copilot's self-action equivalent of `/claude:review` / `$codex-review`.

Optional focus area can be given as a freeform argument.

## Instructions

**Read-only.** Review and report — do not edit files, commit, or push. Findings go to the user and the PR; any fix is a separate change the user asks for.

This skill runs inline in the active Copilot session. Copilot reviews the current branch's PR directly.

### Step 1: Verify a PR exists

```bash
gh pr view --json number,title,body,headRefName
```

- If no PR exists for the current branch, tell the user and stop.
- Save the PR number for use in Step 4.

### Step 2: Gather review context

1. Get the full diff:
   ```bash
   gh pr diff
   ```
2. Get branch commit history:
   ```bash
   git log main..HEAD --oneline
   ```
3. Read project standards:
   - Read `AGENTS.md` and `.github/CONTRIBUTING.md`
   - Check for relevant ADRs in `docs/decisions/`

### Step 3: Review the changes

Evaluate the diff for:
- **Correctness:** does the code do what it claims? Are there logic errors?
- **Code style:** does it follow existing patterns and conventions from `AGENTS.md`?
- **Testing:** are tests present and adequate? Are edge cases covered?
- **Security:** any injection, path traversal, secrets, or command-injection risks?
- **Documentation:** are public APIs, config changes, or breaking changes documented?
- **Architecture:** does it respect layering rules from `docs/development/ai/architectural-conventions.md`?
- **Breaking changes:** any signature changes, removed APIs, or behavior changes?

Apply the optional focus area if the user supplied one. If the focus area names any of `errors`, `tests`, `types`, `comments`, read `docs/development/ai/review-focus-areas.md` and apply those checklists in addition to the general review.

### Step 4: Present findings and post review

Format the review as:

```markdown
## PR Review: #<number> — <title>

### Summary
One-paragraph overview of what the PR does and the overall quality.

### Findings

#### Critical
- (blocking issues — must fix before merge)

#### Suggestions
- (non-blocking improvements worth considering)

#### Positive
- (things done well)

### Verdict
**Approve / Request Changes / Comment** — justification in one sentence.

---
*Review by: Copilot* | *Date: <today's date>*
```

Ask the user: "Post this review as a PR comment? (yes / edit / no)"

If approved, post:

```bash
gh pr comment <PR_NUMBER> --body "<review>"
```
