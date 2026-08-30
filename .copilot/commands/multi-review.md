# Multi-Agent Review

Run multiple AI agents in parallel to independently review the current branch's pull request, then synthesize findings.

## Instructions

### Step 0: Parse arguments

Arguments: `<ais...>` from `$ARGUMENTS`

All arguments are agent names. No issue number is needed — the PR is inferred from the current branch.
Allowed agent names: `claude`, `copilot`, `codex`, `antigravity`.

- If no agents are given, tell the user the required syntax and stop.
- If any agent name is not in the allowed list, report the unknown name, list allowed names, and stop.

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

- If review comments already exist, warn the user and ask for confirmation before continuing.

### Step 3: Generate reviews in parallel

Each review MUST be generated in an isolated context.

#### If `copilot` is in the agent list (self):

Generate Copilot's review inline in this conversation:
- Run `gh pr view --json number,title,body,headRefName`
- Run `gh pr diff`
- Read AGENTS.md and .github/CONTRIBUTING.md
- Review for correctness, style, testing, security, documentation, architecture, breaking changes
- Draft the review in the standard format:
  ```
  ## PR Review: #<number> — <title>
  ### Summary
  ### Findings
  #### Critical
  #### Suggestions
  #### Positive
  ### Verdict
  ---
  *Review by: Copilot* | *Date: <today>*
  ```

#### If `claude` is in the agent list:

```bash
claude -p 'Read AGENTS.md and .github/CONTRIBUTING.md. Get the PR via `gh pr view --json number,title,body,headRefName`. Get the diff via `gh pr diff`. Review for: correctness, style, testing, security, documentation, architecture, breaking changes. Output ONLY the review: ## PR Review: #<number> — <title> / ### Summary / ### Findings / #### Critical / #### Suggestions / #### Positive / ### Verdict. End with --- and *Review by: Claude* | *Date: <today>*.'
```

Capture stdout as Claude's review.

#### If `codex` is in the agent list:

```bash
codex -a never --dangerously-bypass-hook-trust exec 'Review the pull request for the current branch. 1) Run `gh pr view --json number,title,body,headRefName`. 2) Run `gh pr diff`. 3) Read AGENTS.md and .github/CONTRIBUTING.md. 4) Review for correctness, style, testing, security, documentation, architecture, breaking changes. 5) Output ONLY the review: ## PR Review: #<number> — <title> / ### Summary / ### Findings / #### Critical / #### Suggestions / #### Positive / ### Verdict. End with --- and *Review by: Codex* | *Date: <today>*. Do NOT post to GitHub.'
```

Capture stdout as Codex's review.

#### If `antigravity` is in the agent list:

```bash
agy -p 'Review the pull request for the current branch. If an Antigravity review skill (antigravity-review) is available, use it. Otherwise: 1) Run `gh pr view --json number,title,body,headRefName`. 2) Run `gh pr diff`. 3) Read AGENTS.md and .github/CONTRIBUTING.md. 4) Review for correctness, style, testing, security, documentation, architecture, breaking changes. 5) Output ONLY the review: ## PR Review: #<number> — <title> / ### Summary / ### Findings / #### Critical / #### Suggestions / #### Positive / ### Verdict. End with --- and *Review by: Antigravity* | *Date: <today>*. Do NOT post to GitHub.' --dangerously-skip-permissions --add-dir "$(git rev-parse --show-toplevel)" 2>/dev/null
```

Capture stdout as Antigravity's review.

If any agent fails or produces empty output, report the error and ask the user whether to continue with remaining reviews or retry.

### Step 4: Post each review to the PR

```bash
gh pr comment <PR_NUMBER> --body "<agent review>"
```

Post one comment per agent.

### Step 5: Synthesize the findings

Create a synthesis that:
- Lists issues all agents flagged (highest priority)
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
*Synthesized Review by: Copilot (from <agent1> + <agent2> + ... input)* | *Date: <today>*
```

### Step 6: User-approval gate

Present the synthesis to the user and ask for approval before posting.

### Step 7: Post the approved synthesis

Only after the user approves:

```bash
gh pr comment <PR_NUMBER> --body "<synthesis>"
```
