# Multi-Agent Plan

Run multiple AI agents in parallel to create independent implementation plans for GitHub issue #$ARGUMENTS, then synthesize them.

## Instructions

### Step 0: Parse arguments

Arguments: `<ais...> [issue#]`

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

- If plan comments already exist, warn the user:
  > "Issue #<issue> already has implementation plan comments. Continuing will post new ones. Proceed?"
- Wait for user confirmation before continuing.

### Step 3: Generate plans in parallel (separate contexts)

Each plan MUST be generated in an isolated context so no agent influences another.

For **each agent** in the list, run its plan generation in parallel:

#### If `claude` is in the agent list:

Use the Task tool to spawn a subagent with this prompt:
> Read AGENTS.md and .claude/CLAUDE.md for project standards.
> Fetch issue #<issue> via `gh issue view <issue> --json title,body,labels,assignees`.
> Explore the codebase to understand relevant files, patterns, and tests.
> Create an implementation plan in this exact format:
>
> ## Implementation Plan for #<number>: <title>
> ### Overview
> ### Files to Create/Modify
> ### Test Plan
> ### Documentation
> ### Validation
> ### Risks and Considerations
>
> End with: `---` followed by `*Plan by: Claude* | *Date: <today's date>*`
>
> Output ONLY the plan markdown.

Save the subagent's output as Claude's plan.

#### If `copilot` is in the agent list:

```bash
copilot --allow-all -p 'Plan the implementation for GitHub issue #<issue> in the current repository. If the /copilot-plan skill is available, activate it for this issue. Otherwise: 1) Run `gh issue view <issue> --json title,body,labels` to read the issue. 2) Read AGENTS.md. 3) Explore relevant files. 4) Draft a plan in the standard format: ## Implementation Plan for #<number>: <title> / ### Overview / ### Files to Create/Modify / ### Test Plan / ### Documentation / ### Validation / ### Risks and Considerations. End with --- and *Plan by: Copilot* | *Date: <today>*. 5) Print ONLY the plan markdown to stdout. Do NOT post to GitHub.' 2>/dev/null
```

Capture stdout as Copilot's plan.

#### If `codex` is in the agent list:

```bash
codex -a never --dangerously-bypass-hook-trust exec 'Plan the implementation for GitHub issue #<issue> in the current repository. If the $codex-plan skill is available, activate it for this issue. Otherwise: 1) Run `gh issue view <issue> --json title,body,labels` to read the issue. 2) Read AGENTS.md. 3) Explore relevant files. 4) Draft a plan in the standard format: ## Implementation Plan for #<number>: <title> / ### Overview / ### Files to Create/Modify / ### Test Plan / ### Documentation / ### Validation / ### Risks and Considerations. End with --- and *Plan by: Codex* | *Date: <today>*. 5) Print ONLY the plan markdown to stdout. Do NOT post to GitHub.'
```

Capture stdout as Codex's plan.

#### If `antigravity` is in the agent list:

```bash
agy -p 'Plan the implementation for GitHub issue #<issue> in the current repository. If an Antigravity planning skill (antigravity-plan) is available, use it for this issue. Otherwise: 1) Run `gh issue view <issue> --json title,body,labels`. 2) Read AGENTS.md. 3) Explore relevant files. 4) Draft a plan: ## Implementation Plan for #<number>: <title> / ### Overview / ### Files to Create/Modify / ### Test Plan / ### Documentation / ### Validation / ### Risks and Considerations. End with --- and *Plan by: Antigravity* | *Date: <today>*. 5) Print ONLY the plan to stdout. Do NOT post to GitHub.' --dangerously-skip-permissions --add-dir "$(git rev-parse --show-toplevel)" 2>/dev/null
```

Capture stdout as Antigravity's plan.

If any agent fails or produces empty output, report the error and ask the user whether to continue with the remaining plans or retry.

### Step 4: Post each plan to the issue

Post one comment per agent's plan:

```bash
gh issue comment <issue> --body "<agent plan>"
```

### Step 5: Synthesize the final plan

Read all plans and create a synthesized final plan that:
- Combines the best elements from all plans
- Resolves conflicts or contradictions
- Notes where all agents agreed (highest confidence)
- Notes where they diverged (needs discussion)
- Preserves the standard plan format

Add the signature:
```
---
*Synthesized Plan by: Claude (from <agent1> + <agent2> + ... input)* | *Date: <today's date>*
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
- When ready, use `/<currentai>:implement <issue>` (e.g. `/claude:implement <issue>`) to start implementation
