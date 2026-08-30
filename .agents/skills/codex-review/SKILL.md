---
name: codex-review
description: Use when running a single-agent PR review in this repository from a Codex session. Reviews the current branch's PR and posts findings as a PR comment after user approval.
---

# Review PR

Run a single-agent PR review using Codex in this repository.

## When to use

Use this skill when the user wants Codex to review the current branch's pull request.

Expected prompt shape:

- `$codex-review review the current PR`
- `$codex-review review this branch's pull request`

The user may include optional focus text after the trigger.

## Instructions

**Read-only.** Review and report — do not edit files, commit, or push. Findings go to the user and the PR; any fix is a separate change the user asks for.

1. Verify a PR exists for the current branch:
   ```bash
   gh pr view --json number,title,body,headRefName
   ```
   - If no PR exists, stop and tell the user.
   - Save the PR number for later.

2. Gather review context:
   ```bash
   gh pr diff
   git log main..HEAD --oneline
   ```
   - Read `AGENTS.md` and `.github/CONTRIBUTING.md`.
   - Check for relevant ADRs in `docs/decisions/`.

3. Review the changes for:
   - **Correctness:** does the code do what it claims? Are there logic errors?
   - **Code style:** does it follow existing patterns and conventions?
   - **Testing:** are tests present and adequate? Are edge cases covered?
   - **Security:** any injection, path traversal, secrets, or command-injection risks?
   - **Documentation:** are public APIs, config changes, or breaking changes documented?
   - **Architecture:** does it respect layering rules?
   - **Breaking changes:** any signature changes, removed APIs, or behavior changes?

4. Format findings as:
   ```markdown
   ## PR Review: #<number> — <title>

   ### Summary
   One-paragraph overview.

   ### Findings

   #### Critical
   - (blocking issues)

   #### Suggestions
   - (non-blocking improvements)

   #### Positive
   - (things done well)

   ### Verdict
   **Approve / Request Changes / Comment** — justification.

   ---
   *Review by: Codex* | *Date: <today's date>*
   ```

5. Present the review to the user and ask whether to post it as a PR comment.

6. If the user approves, post:
   ```bash
   gh pr comment <PR_NUMBER> --body "<review>"
   ```
