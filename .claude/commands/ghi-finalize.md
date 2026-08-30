# Finalize

Finalize the current branch: update documentation, commit changes, and create a PR.

## Instructions

This command operates on the current branch. It assumes implementation and review are complete.

### Step 1: Gather context

In the main context (lightweight reads):

1. **Detect the current branch and linked issue:**
   ```bash
   git branch --show-current
   ```
   Extract the issue number from the branch name (e.g., `feat/245-description` → `#245`).
   - If on `main`, tell the user they need to be on a feature branch and stop.

2. **Get the issue details:**
   ```bash
   gh issue view <number> --json title,labels
   ```

3. **Check for uncommitted changes:**
   ```bash
   git status --short
   ```
   - If there are unstaged or uncommitted changes (e.g., from the review/fix cycle), list them for the user
   - These will be included in the commit — confirm with the user that all changes should be included

4. **Check what changed vs main:**
   ```bash
   git diff main --stat
   ```

### Step 2: Spawn a finalization agent

Use the Task tool with `subagent_type: "general-purpose"` and provide it with the branch name, issue number, issue title, labels, and the list of changed files. The agent should:

1. **Read the project rules:**
   - Read `AGENTS.md` — understand commit guidelines, PR checklist, ADR requirements
   - Read `.github/CONTRIBUTING.md` — understand commit format
   - Read `.github/pull_request_template.md` — understand PR structure

2. **Check documentation needs:**
   - Review the changed files — do any user-facing behaviors change?
   - If yes, identify which docs in `docs/` need updating and update them
   - Check `docs/decisions/` for related ADRs that need updating

3. **Check ADR needs:**
   - If the issue has the `needs-adr` label, create an ADR using `doit adr`
   - If the changes relate to an existing ADR, update it with the issue link
   - Every ADR must link to documentation in `docs/`

4. **Run final validation:**
   - Run: `doit check`
   - ALL checks must pass before proceeding

5. **Draft the PR description** and write it to a temp file:
   - Read `.github/pull_request_template.md` for structure
   - Run `mkdir -p tmp/agents/claude` to ensure the directory exists
   - Write the PR body to `tmp/agents/claude/pr-body-issue-<n>.md`
   - The body MUST include `Addresses #<issue-number>`

6. **Return** a summary of:
   - Documentation changes made (if any)
   - ADR changes made (if any)
   - Suggested commit message following conventional format: `<type>: <subject>`
   - Suggested PR title following conventional format: `<type>: <subject>`
   - Path to the PR body file (`tmp/agents/claude/pr-body-issue-<n>.md`)

### Step 3: Commit and create PR

After the agent returns, in the main context:

1. **Show the user** the suggested commit message and PR description
2. **Ask the user** for approval to commit and create the PR
3. **Only after user confirms:**
   - Stage files: `git add <specific files>` (include all changed files from implementation and review/fix cycle)
   - Commit with the approved message
   - Create PR: `doit pr --title="<type>: <subject>" --body-file=tmp/agents/claude/pr-body-issue-<n>.md`
   - Delete the temp file: `rm tmp/agents/claude/pr-body-issue-<n>.md`
4. **Report** the PR URL to the user

**IMPORTANT:** Do NOT commit or create the PR without explicit user confirmation.
