---
name: multi-plan
description: Run multiple AI agents in parallel to create independent implementation plans for a GitHub issue from a Codex session, then synthesize them into a single plan.
---

# Multi-Agent Plan

Run multiple AI agents in parallel to create independent implementation plans for a GitHub issue, then synthesize them.

## When to use

Use this skill when the user wants multiple agents to independently plan an issue.

Expected prompt shape:

- `$multi-plan claude codex 42`
- `$multi-plan run multi-agent plan for issue 42 with claude and codex`

If the agent list or issue number is missing, ask for it before continuing.

## Instructions

### Step 0: Parse arguments

Extract the agent list and issue number from the user's request.
Allowed agent names: `claude`, `copilot`, `codex`, `antigravity`.

- If the issue number is missing, ask for it.
- If any agent name is not in the allowed list, report the unknown name, list allowed names, and stop.

### Step 1: Validate the issue

```bash
gh issue view <issue> --json number,title,state,labels
```

- If the issue does not exist, stop and tell the user.
- If the issue is closed, ask whether to reopen it or stop.

### Step 2: Check for existing plans

```bash
gh api repos/{owner}/{repo}/issues/<issue>/comments --jq '.[].body' | grep -E "^#+ Implementation Plan for"
```

- If plan comments already exist, warn the user and ask for confirmation.

### Step 3: Generate plans in parallel

Each plan MUST be in an isolated context. Use `codex -a never --dangerously-bypass-hook-trust exec` as the shell tool for all non-self agents.

#### If `codex` is in the agent list (self):

Generate Codex's plan inline using the standard workflow:
1. Run `gh issue view <issue> --json title,body,labels,assignees`
2. Read AGENTS.md
3. Explore relevant codebase files
4. Draft the plan in the standard format:
   ```
   ## Implementation Plan for #<number>: <title>
   ### Overview
   ### Files to Create/Modify
   ### Test Plan
   ### Documentation
   ### Validation
   ### Risks and Considerations
   ---
   *Plan by: Codex* | *Date: <today>*
   ```

#### If `claude` is in the agent list:

```bash
claude -p 'Read AGENTS.md and .claude/CLAUDE.md for project standards. Fetch issue #<issue> via `gh issue view <issue> --json title,body,labels,assignees`. Explore the codebase. Create an implementation plan: ## Implementation Plan for #<number>: <title> / ### Overview / ### Files to Create/Modify / ### Test Plan / ### Documentation / ### Validation / ### Risks and Considerations. End with --- and *Plan by: Claude* | *Date: <today>*. Output ONLY the plan markdown.'
```

Capture stdout as Claude's plan.

#### If `copilot` is in the agent list:

```bash
copilot --allow-all -p 'Plan the implementation for GitHub issue #<issue> in the current repository. If the /copilot-plan skill is available, activate it for this issue. Otherwise: 1) Run `gh issue view <issue> --json title,body,labels`. 2) Read AGENTS.md. 3) Explore relevant files. 4) Draft a plan: ## Implementation Plan for #<number>: <title> / ### Overview / ### Files to Create/Modify / ### Test Plan / ### Documentation / ### Validation / ### Risks and Considerations. End with --- and *Plan by: Copilot* | *Date: <today>*. 5) Print ONLY the plan to stdout. Do NOT post to GitHub.' 2>/dev/null
```

Capture stdout as Copilot's plan.

#### If `antigravity` is in the agent list:

```bash
agy -p 'Plan the implementation for GitHub issue #<issue> in the current repository. If an Antigravity planning skill (antigravity-plan) is available, use it for this issue. Otherwise: 1) Run `gh issue view <issue> --json title,body,labels`. 2) Read AGENTS.md. 3) Explore relevant files. 4) Draft a plan: ## Implementation Plan for #<number>: <title> / ### Overview / ### Files to Create/Modify / ### Test Plan / ### Documentation / ### Validation / ### Risks and Considerations. End with --- and *Plan by: Antigravity* | *Date: <today>*. 5) Print ONLY the plan to stdout. Do NOT post to GitHub.' --dangerously-skip-permissions --add-dir "$(git rev-parse --show-toplevel)" 2>/dev/null
```

Capture stdout as Antigravity's plan.

If any agent fails or produces empty output, report the error and ask whether to continue or retry.

### Step 4: Post each plan to the issue

```bash
gh issue comment <issue> --body "<agent plan>"
```

Post one comment per agent.

### Step 5: Synthesize the final plan

Create a synthesized plan combining the best elements from all plans. Note agreements (high confidence) and divergences (needs discussion). Use the standard plan format.

Signature:
```
---
*Synthesized Plan by: Codex (from <agent1> + <agent2> + ... input)* | *Date: <today>*
```

### Step 6: Iterate with user

Present the synthesized plan and ask for feedback. Do NOT post until the user approves.

### Step 7: Post the approved synthesized plan

```bash
gh issue comment <issue> --body "<synthesized plan>"
```

Tell the user the plans have been posted and the next step is `$codex-implement <issue>` (or the equivalent for the current host agent).
