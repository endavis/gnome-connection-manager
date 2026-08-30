# Multi-Agent Review

Run multiple AI agents in parallel to independently review the current branch's pull request, then synthesize findings.

## Instructions

### Step 0: Parse arguments

Arguments: `<ais...>`

All arguments are agent names. No issue number is needed — the PR is inferred from the current branch.
Allowed agent names: `claude`, `copilot`, `codex`, `antigravity`.

- If no agents are given, tell the user the required syntax and stop.
- If any agent name is not in the allowed list, report the unknown name, list allowed names, and stop.

Example: `/multi-review claude codex` → agents: [claude, codex]

### Step 1: Verify the PR exists

```bash
gh pr view --json number,title,body,headRefName
```

- If no PR exists for the current branch, tell the user and stop.
- Save the PR number for later use.

### Step 2: Check for existing reviews

```bash
gh pr view --json comments --jq '.comments[].body' | grep -E "\*Review by:"
```

- If review comments already exist, warn the user:
  > "PR #<number> already has review comments. Continuing will post new ones. Proceed?"
- Wait for user confirmation before continuing.

### Step 3: Generate reviews in parallel (separate contexts)

Each review MUST be generated in an isolated context so no agent influences another.

For **each agent** in the list, run its review generation in parallel:

#### If `claude` is in the agent list:

Use the Task tool to spawn a subagent with this prompt:
> Read AGENTS.md and .github/CONTRIBUTING.md for project standards.
> Get the PR details via `gh pr view --json number,title,body,headRefName`.
> Get the diff via `gh pr diff`.
> Review the code for: correctness, code style, testing, security, documentation, architecture, and breaking changes.
> Create a review in this exact format:
>
> ## PR Review: #<number> — <title>
> ### Summary
> ### Findings
> #### Critical
> #### Suggestions
> #### Positive
> ### Verdict
> Approve, Request Changes, or Comment with justification.
>
> End with: `---` followed by `*Review by: Claude* | *Date: <today's date>*`
>
> Output ONLY the review markdown.

Save the subagent's output as Claude's review.

#### If `copilot` is in the agent list:

```bash
copilot --allow-all -p 'Review the pull request for the current branch. 1) Run `gh pr view --json number,title,body,headRefName` to identify the PR. 2) Run `gh pr diff` to get the diff. 3) Read AGENTS.md and .github/CONTRIBUTING.md. 4) Review for correctness, style, testing, security, documentation, architecture, and breaking changes. 5) Output ONLY the review in this format: ## PR Review: #<number> — <title> / ### Summary / ### Findings / #### Critical / #### Suggestions / #### Positive / ### Verdict. End with --- and *Review by: Copilot* | *Date: <today>*. Do NOT post to GitHub.' 2>/dev/null
```

Capture stdout as Copilot's review.

#### If `codex` is in the agent list:

```bash
codex -a never --dangerously-bypass-hook-trust exec 'Review the pull request for the current branch. 1) Run `gh pr view --json number,title,body,headRefName` to identify the PR. 2) Run `gh pr diff` to get the diff. 3) Read AGENTS.md and .github/CONTRIBUTING.md. 4) Review for correctness, style, testing, security, documentation, architecture, and breaking changes. 5) Output ONLY the review in this format: ## PR Review: #<number> — <title> / ### Summary / ### Findings / #### Critical / #### Suggestions / #### Positive / ### Verdict. End with --- and *Review by: Codex* | *Date: <today>*. Do NOT post to GitHub.'
```

Capture stdout as Codex's review.

#### If `antigravity` is in the agent list:

```bash
agy -p 'Review the pull request for the current branch. If an Antigravity review skill (antigravity-review) is available, use it. Otherwise: 1) Run `gh pr view --json number,title,body,headRefName`. 2) Run `gh pr diff`. 3) Read AGENTS.md and .github/CONTRIBUTING.md. 4) Review for correctness, style, testing, security, documentation, architecture, breaking changes. 5) Output ONLY the review: ## PR Review: #<number> — <title> / ### Summary / ### Findings / #### Critical / #### Suggestions / #### Positive / ### Verdict. End with --- and *Review by: Antigravity* | *Date: <today>*. Do NOT post to GitHub.' --dangerously-skip-permissions --add-dir "$(git rev-parse --show-toplevel)" 2>/dev/null
```

Capture stdout as Antigravity's review.

If any agent fails or produces empty output, report the error and ask the user whether to continue with remaining reviews or retry.

### Step 4: Post each review to the PR

Post one comment per agent's review:

```bash
gh pr comment <PR_NUMBER> --body "<agent review>"
```

### Step 5: Synthesize the findings

Read all reviews and create a synthesis that:
- Lists issues all agents flagged (highest priority — all caught it)
- Lists issues only some agents flagged (worth investigating)
- Notes any disagreements in verdicts
- Provides a combined verdict with justification

Format:
```
## Combined Review Summary

### Consensus Findings (all agents flagged)
- Description of shared finding

### Per-Agent-Only Findings
- **<Agent>:** Description of finding only that agent caught

### Combined Verdict
**Approve / Request Changes / Comment** — justification

---
*Synthesized Review by: Claude (from <agent1> + <agent2> + ... input)* | *Date: <today's date>*
```

### Step 6: User-approval gate

Present the synthesis to the user and ask for approval before posting.

### Step 7: Post the approved synthesis

Only after the user approves:

```bash
gh pr comment <PR_NUMBER> --body "<synthesis>"
```

Present the synthesis to the user and highlight any areas that need attention.
