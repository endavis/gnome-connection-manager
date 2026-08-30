# Multi-Agent Plan

Run multiple AI agents in parallel to create independent implementation plans for a GitHub issue, then synthesize them.

## Instructions

### Step 0: Parse arguments

Arguments: `<ais...> [issue#]` from `$ARGUMENTS`

The last argument is the issue number if it is an integer. Everything before it is the agent list.
Allowed agent names: `claude`, `copilot`, `codex`, `antigravity`.

- If the issue number is missing, tell the user the required syntax and stop.
- If any agent name is not in the allowed list, report the unknown name, list allowed names, and stop.

Example: `/multi-plan claude codex 42` → agents: [claude, codex], issue: 42

### Step 1: Validate the issue

```bash
gh issue view <issue> --json number,title,state,labels
```

- If the issue does not exist, tell the user and stop.
- If the issue is closed, tell the user and ask if they want to reopen it or stop.

### Step 2: Check for existing plans

```bash
gh api repos/{owner}/{repo}/issues/<issue>/comments --jq '.[].body' | grep -E "^#+ Implementation Plan for"
```

- If plan comments already exist, warn the user and ask for confirmation before continuing.

### Step 3: Generate plans in parallel

Each plan MUST be generated in an isolated context.

#### If `copilot` is in the agent list (self):

Generate Copilot's plan inline in this conversation:
- Fetch issue: `gh issue view <issue> --json title,body,labels,assignees`
- Read AGENTS.md
- Explore relevant codebase files
- Draft the plan in the standard format:
  ```
  ## Implementation Plan for #<number>: <title>
  ### Overview
  ### Files to Create/Modify
  ### Test Plan
  ### Documentation
  ### Validation
  ### Risks and Considerations
  ---
  *Plan by: Copilot* | *Date: <today>*
  ```

#### If `claude` is in the agent list:

```bash
claude -p 'Read AGENTS.md and .claude/CLAUDE.md for project standards. Fetch issue #<issue> via `gh issue view <issue> --json title,body,labels,assignees`. Explore the codebase. Create an implementation plan: ## Implementation Plan for #<number>: <title> / ### Overview / ### Files to Create/Modify / ### Test Plan / ### Documentation / ### Validation / ### Risks and Considerations. End with --- and *Plan by: Claude* | *Date: <today>*. Output ONLY the plan markdown.'
```

Capture stdout as Claude's plan.

#### If `codex` is in the agent list:

```bash
codex -a never --dangerously-bypass-hook-trust exec 'Plan the implementation for GitHub issue #<issue> in the current repository. If the $codex-plan skill is available, activate it for this issue. Otherwise: 1) Run `gh issue view <issue> --json title,body,labels`. 2) Read AGENTS.md. 3) Explore relevant files. 4) Draft a plan: ## Implementation Plan for #<number>: <title> / ### Overview / ### Files to Create/Modify / ### Test Plan / ### Documentation / ### Validation / ### Risks and Considerations. End with --- and *Plan by: Codex* | *Date: <today>*. 5) Print ONLY the plan markdown to stdout. Do NOT post to GitHub.'
```

Capture stdout as Codex's plan.

#### If `antigravity` is in the agent list:

```bash
agy -p 'Plan the implementation for GitHub issue #<issue> in the current repository. If an Antigravity planning skill (antigravity-plan) is available, use it for this issue. Otherwise: 1) Run `gh issue view <issue> --json title,body,labels`. 2) Read AGENTS.md. 3) Explore relevant files. 4) Draft a plan: ## Implementation Plan for #<number>: <title> / ### Overview / ### Files to Create/Modify / ### Test Plan / ### Documentation / ### Validation / ### Risks and Considerations. End with --- and *Plan by: Antigravity* | *Date: <today>*. 5) Print ONLY the plan to stdout. Do NOT post to GitHub.' --dangerously-skip-permissions --add-dir "$(git rev-parse --show-toplevel)" 2>/dev/null
```

Capture stdout as Antigravity's plan.

If any agent fails or produces empty output, report the error and ask the user whether to continue with remaining plans or retry.

### Step 4: Post each plan to the issue

```bash
gh issue comment <issue> --body "<agent plan>"
```

Post one comment per agent.

### Step 5: Synthesize the final plan

Create a synthesized plan that:
- Combines the best elements from all plans
- Resolves conflicts or contradictions
- Notes where all agents agreed (highest confidence)
- Notes where they diverged (needs discussion)
- Preserves the standard plan format

Add the signature:
```
---
*Synthesized Plan by: Copilot (from <agent1> + <agent2> + ... input)* | *Date: <today>*
```

### Step 6: Review with user

Present the synthesized plan for discussion:
- Highlight areas where agents disagreed
- Ask for feedback and iterate as needed
- Do NOT post the synthesized plan until the user approves it

### Step 7: Post the approved synthesized plan

Only after the user approves:

```bash
gh issue comment <issue> --body "<synthesized plan>"
```

Tell the user:
- All agent plans plus the synthesized plan have been posted to issue #<issue>
- When ready, use `/<currentai>:implement <issue>` (e.g. `/copilot-implement <issue>` in Copilot) to start implementation
