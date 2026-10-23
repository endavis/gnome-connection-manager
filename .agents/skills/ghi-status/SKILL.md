---
name: ghi-status
description: Use when the user wants to know where they are in the issue workflow for this repository, or asks what their status is or what to do next. Inspects the current git state, the branch's linked issue, its plan comment, uncommitted changes, unpushed commits, and open PRs, then reports a status summary and suggests the next step. Read-only; makes no changes.
---

# Where Am I

Assess the current workflow state and suggest the next step.

## Instructions

This skill takes no arguments — it inspects the environment.

### Step 1: Check git state

```bash
git branch --show-current
git status --short
git log --oneline -5
```

### Step 2: Determine context

Based on the branch name, determine the workflow state:

**If on `main`:**
- No active work in progress
- Suggest: start planning an issue (the current agent's plan workflow), or create one with `doit issue`

**If on a feature branch (e.g., `feat/245-description`):**
1. Extract the issue number from the branch name
2. Fetch issue state:
   ```bash
   gh issue view <number> --json number,title,state,labels
   ```
3. Check for a plan comment:
   ```bash
   gh api repos/{owner}/{repo}/issues/<number>/comments --jq '.[].body' | grep -E "^#+ Implementation Plan for"
   ```
4. Check for uncommitted changes:
   ```bash
   git status --short
   ```
5. Check for unpushed commits:
   ```bash
   git log origin/main..HEAD --oneline 2>/dev/null || git log main..HEAD --oneline
   ```
6. Check for an existing PR:
   ```bash
   gh pr list --head "$(git branch --show-current)" --json number,title,state,url
   ```

### Step 3: Report state and suggest next step

Present a status summary and suggest what to do next:

| State | Suggestion |
| :--- | :--- |
| On feature branch, no plan comment, no code changes | Say "implement issue N" — it decides whether to plan first |
| On feature branch, plan exists, no code changes | Say "implement issue N" to resume — it reuses the existing plan comment |
| On feature branch, code changes, not committed | Say "implement issue N" to resume, or commit and open a PR per `.github/CONTRIBUTING.md` |
| On feature branch, committed, no PR | Say "implement issue N" to resume, or open a PR per `.github/CONTRIBUTING.md` |
| On feature branch, PR exists (open) | PR is open — waiting for review/merge |
| On feature branch, PR exists (merged) | Close the issue: `gh issue close <N> --comment "Addressed in PR #<PR>"` |
| Issue is already closed | Work complete — switch back to `main` |

### Output format

```
## Workflow Status

- **Branch:** feat/245-workflow-commands
- **Issue:** #245 — feat: add workflow commands (OPEN)
- **Plan:** Posted as comment ✓
- **Changes:** 4 files modified, 2 uncommitted
- **PR:** None

## Suggested next step
Say "implement issue 245" to resume — it will pick up the uncommitted changes, run `doit check`,
commit, push, and open the PR.
```
