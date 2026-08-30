---
name: codex-implement
description: Use when implementing an approved GitHub issue plan in this repository from a Codex session. Creates or resumes the issue branch, follows the posted plan comment, writes tests with the change, and finishes with `doit check`.
---

# Implement Issue

Implement the approved plan for a GitHub issue in this repository.

## When to use

Use this skill when the user wants Codex to carry out the repository's implementation workflow for an issue that already has an approved plan comment.

Expected prompt shape:

- `$codex-implement implement issue 399`
- `$codex-implement continue work on issue 399`

If the issue number is missing, ask for it before continuing.

## Instructions

1. Validate the issue exists and is open:
   ```bash
   gh issue view <issue-number> --json number,title,state,labels
   ```
   - If the issue does not exist or is closed, stop and tell the user.

2. Verify an approved plan comment exists:
   ```bash
   gh api repos/{owner}/{repo}/issues/<issue-number>/comments --jq '.[].body' | grep -E "^#+ Implementation Plan for"
   ```
   - If no plan comment exists, stop and tell the user to run `$codex-plan` first.

3. Check the current branch state:
   ```bash
   git branch --show-current
   git status --short
   ```
   - If already on a branch matching `*/<issue-number>-*`, resume work there.
   - If not, create a new branch from fresh `main`.

4. Determine the branch type from labels:
   - `enhancement` -> `feat`
   - `bug` -> `fix`
   - `refactor` -> `refactor`
   - `documentation` -> `docs`
   - `chore` -> `chore`
   - otherwise `issue`

5. If a new branch is needed, create it from updated `main`:
   ```bash
   git checkout main
   git pull
   git checkout -b <type>/<issue-number>-<short-description>
   ```

6. Read the project rules before editing:
   - `AGENTS.md`
   - `docs/development/ai/architectural-conventions.md`
   - `.github/CONTRIBUTING.md`

7. Fetch the issue and plan details:
   ```bash
   gh issue view <issue-number> --json title,body,labels
   gh api repos/{owner}/{repo}/issues/<issue-number>/comments --jq '.[].body'
   ```
   - Use the approved implementation plan comment as the implementation contract.

8. Implement the plan in the main Codex session:
   - Follow existing repo patterns.
   - Create tests with the implementation.
   - Do not commit.
   - If an action fails in a way that changes the intended fix, stop and explain it to the user.

9. Run full validation:
   ```bash
   doit check
   ```
   - Fix failures that are part of the issue scope.
   - Do not paper over failing tests by weakening them without user discussion.

10. Summarize what changed, list the changed files, report the validation result, and tell the user the next workflow step is `$ghi-finalize`.
