# Where Am I

Assess the current workflow state and suggest the next step.

## Instructions

Gather information about the current state and determine where the user is in the issue lifecycle. This command takes no arguments — it inspects the environment.

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
- Suggest: "Start with `/<currentai>:plan <N>` to plan an issue, or create one with `doit issue`"

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
| On feature branch, no plan comment | Run `/<currentai>:plan <N>` to create a plan |
| On feature branch, plan exists, no code changes | Run `/<currentai>:implement <N>` to start implementation |
| On feature branch, code changes, not committed | Review changes, then run `/ghi-finalize` to commit and create PR |
| On feature branch, committed, no PR | Run `/ghi-finalize` to create the PR |
| On feature branch, PR exists (open) | PR is open — waiting for review/merge |
| On feature branch, PR exists (merged) | Run `doit pr_merge --auto-close` or `gh issue close <N>` to close the issue |
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
Run `/ghi-finalize` to commit your changes and create a PR.
```
