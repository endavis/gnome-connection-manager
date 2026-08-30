---
name: ghi-finalize
description: Use when the implementation and review cycle for a repository issue is complete in a Codex session. Reviews the branch diff, updates docs or ADRs if needed, validates with `doit check`, drafts commit and PR artifacts, and stops for explicit approval before commit or PR creation.
---

# Finalize

Finalize the current issue branch for this repository.

## When to use

Use this skill after implementation is complete and the user wants Codex to prepare the commit and PR artifacts without committing or opening the PR until approval is explicit.

Expected prompt shape:

- `$ghi-finalize finalize this branch`
- `$ghi-finalize prepare the PR for issue 399`

## Instructions

1. Detect the current branch and linked issue:
   ```bash
   git branch --show-current
   ```
   - Extract the issue number from the branch name, for example `feat/399-description` -> `399`.
   - If on `main`, stop and tell the user they must be on a feature branch.

2. Gather context:
   ```bash
   gh issue view <issue-number> --json title,labels
   git status --short
   git diff main --stat
   ```
   - If there are unstaged or uncommitted changes, list them and confirm they should be included.

3. Read the project rules before finalization:
   - `AGENTS.md`
   - `.github/CONTRIBUTING.md`
   - `.github/pull_request_template.md`
   - `docs/decisions/README.md`

4. Check whether docs or ADR updates are required:
   - Review the changed files for user-facing behavior or workflow changes.
   - If the issue has `needs-adr`, create or update the ADR before proceeding.
   - Keep ADR links aligned with the relevant documentation.

5. Run final validation:
   ```bash
   doit check
   ```
   - All checks must pass before moving on.

6. Draft the PR body to a project-scoped temp file:
   ```bash
   mkdir -p tmp/agents/codex
   ```
   - Write the PR body to `tmp/agents/codex/pr-body-issue-<issue-number>.md`.
   - The PR body must include `Addresses #<issue-number>`.

7. Present the user with:
   - the proposed commit message following conventional commits
   - the proposed PR title
   - the PR body summary
   - any docs or ADR updates made

8. Wait for explicit user approval before:
   - staging files
   - committing
   - running `doit pr --title=... --body-file=...`

9. After approval, use `doit pr` rather than `gh pr create`, report the PR URL, and remove the temp PR body file.
