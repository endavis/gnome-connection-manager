# Implement Issue

Implement the plan for GitHub issue #$ARGUMENTS.

## Instructions

The implementation is delegated to a sub-agent (Task tool) so raw tool output stays out of the main conversation context. The agent does the coding; you receive the summary for user review.

**Plan-mode trap:** parent plan-mode state propagates to the spawned sub-agent mid-execution and freezes it after its first non-readonly action (typically the first `Write`). Check your Claude Code status line before running — if it shows "plan mode", exit before invoking.

### Step 1: Validate preconditions

1. **Verify the issue exists and is open:**
   ```bash
   gh issue view $ARGUMENTS --json number,title,state,labels
   ```
   - If the issue does not exist or is closed, tell the user and stop.

2. **Verify a plan comment exists:**
   Fetch all comments and search for the plan header:
   ```bash
   gh api repos/{owner}/{repo}/issues/$ARGUMENTS/comments --jq '.[].body' | grep -E "^#+ Implementation Plan for"
   ```
   - If no plan comment is found, tell the user:
     > "No implementation plan found for issue #$ARGUMENTS. Run `/claude:plan $ARGUMENTS` first."
   - Stop and wait for the user.

3. **Check current branch state:**
   ```bash
   git branch --show-current
   git status --short
   ```
   - If already on a branch matching `*/$ARGUMENTS-*` (e.g., `feat/$ARGUMENTS-description`):
     - Tell the user you're resuming work on the existing branch
     - Skip branch creation (Step 2)
     - If there are uncommitted changes, warn the user and ask how to proceed
   - If on `main` or a different branch: proceed to Step 2

### Step 2: Create the branch

Only if not already on the correct branch:

1. Fetch the issue to determine the branch type:
   ```bash
   gh issue view $ARGUMENTS --json title,labels
   ```
2. Determine branch type from labels:
   - `enhancement` → `feat`
   - `bug` → `fix`
   - `refactor` → `refactor`
   - `documentation` → `docs`
   - `chore` → `chore`
   - Default → `issue`
3. Create and switch to branch:
   ```bash
   git checkout main && git pull
   git checkout -b <type>/$ARGUMENTS-<short-description>
   ```

### Step 3: Spawn the implementation subagent

Use the Task tool with `subagent_type: "implement-worker"`. In the prompt, pass:

- The issue number (so the subagent can fetch the plan).
- The branch name (for context; the subagent will not switch branches).
- Any issue-specific notes or scope clarifications.

The subagent carries its own system prompt covering project rules, plan fetch, implementation, and validation — this command does not repeat them. The subagent has `permissionMode: default`, which (per Claude Code's sub-agent precedence rules) should override parent plan mode for operations inside the subagent's context.

### Step 4: Present changes to user

After the agent returns, show the user:
- Summary of what was implemented
- Files changed
- Test results
- Any issues or deviations from the plan

Tell the user:
- Review the changes and test as needed
- Discuss any fixes directly in conversation (no command needed)
- When satisfied, use `/ghi-finalize` to commit and create a PR
