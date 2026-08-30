# Plan Issue

Plan the implementation for GitHub issue #$ARGUMENTS.

## Instructions

This command runs in the main conversation context (NOT in a subagent) so the user can ask questions, discuss tradeoffs, and refine the plan interactively.

### Step 1: Go into Plan Mode

### Step 2: Validate the issue

1. **Verify the issue exists and is open:**
   ```bash
   gh issue view $ARGUMENTS --json number,title,state,labels
   ```
   - If the issue does not exist, tell the user and stop.
   - If the issue is closed, tell the user and ask if they want to reopen it or stop.

2. **Check for an existing plan comment:**
   ```bash
   gh issue view $ARGUMENTS --json comments --jq '.comments[].body' | grep -lE "^#+ Implementation Plan for"
   ```
   - If a plan comment already exists, warn the user:
     > "Issue #$ARGUMENTS already has an implementation plan comment. Continuing will post a new one. Proceed?"
   - Wait for user confirmation before continuing.

### Step 3: Read the project rules

- Read `AGENTS.md` — understand workflow, conventions, and commit guidelines
- Read `.claude/CLAUDE.md` — understand TodoWrite requirements

### Step 4: Fetch the issue details

- Run: `gh issue view $ARGUMENTS --json title,body,labels,assignees`
- Parse the issue body to understand what needs to be done
- Check if the issue has the `needs-adr` label

### Step 5: Explore the codebase

- Identify which files, modules, and tests are relevant
- Understand existing patterns and conventions in the affected areas
- Check for related ADRs in `docs/decisions/`
- If anything is ambiguous or there are multiple valid approaches, **ask the user** before deciding

### Step 6: Draft the plan and iterate with the user (inside plan mode)

**Stay in plan mode for this entire step.** Draft the plan, present it, and iterate until the user approves — all before leaving plan mode.

1. Present the plan to the user. The plan MUST include these sections:

   ```
   ## Implementation Plan for #<number>: <title>

   ### Overview
   Brief description of what will be done.

   ### Files to Create/Modify
   - [ ] `path/to/file.py` — description of changes
   - [ ] `tests/test_file.py` — description of test coverage

   ### Test Plan
   - [ ] Test case 1: description
   - [ ] Test case 2: description

   ### Documentation
   - [ ] Any docs that need updating
   - [ ] ADR needed: yes/no (if yes, brief description)

   ### Validation
   - [ ] `doit check` passes
   - [ ] Manual verification steps
   ```

2. Use `AskUserQuestion` to ask for feedback on the plan.
3. Discuss alternatives, answer questions, and adjust the plan as the user requests.
4. Keep iterating inside plan mode until the user explicitly says the plan is approved.
5. Do NOT leave plan mode until the user confirms approval.

### Step 7: Leave plan mode

Once the user has approved the plan, leave plan mode. The `ExitPlanMode` approval prompt means: **"Post the approved plan to the issue."** The plan has already been reviewed and approved by the user during Step 6.

### Step 8: Post the approved plan to the issue

Post the approved plan as a comment on the issue:

```bash
gh issue comment $ARGUMENTS --body "<approved plan>"
```

Tell the user:
- The plan has been posted as a comment on issue #$ARGUMENTS
- When ready, use `/claude:implement $ARGUMENTS` to start implementation
