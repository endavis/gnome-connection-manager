---
name: multi-review
description: Run multiple AI agents in parallel to independently review the current PR from a Codex session, then synthesize findings.
---

# Multi-Agent Review

Run multiple AI agents in parallel to independently review the current branch's pull request, then synthesize findings.

## When to use

Use this skill when the user wants multiple agents to independently review an open PR.

Expected prompt shape:

- `$multi-review claude codex`
- `$multi-review run multi-agent review with claude and codex`

If the agent list is missing, ask for it before continuing.

## Instructions

### Step 0: Parse arguments

Extract the agent list from the user's request.
Allowed agent names: `claude`, `copilot`, `codex`, `antigravity`.

- If no agents are given, ask for the agent list.
- If any agent name is not in the allowed list, report the unknown name, list allowed names, and stop.

### Step 1: Verify the PR exists

```bash
gh pr view --json number,title,body,headRefName
```

- If no PR exists for the current branch, stop and tell the user.
- Save the PR number for later use.

### Step 2: Check for existing reviews

```bash
gh pr view --json comments --jq '.comments[].body' | grep -E "\*Review by:"
```

- If review comments already exist, warn the user and ask for confirmation.

### Step 3: Generate reviews in parallel

Each review MUST be in an isolated context.

#### If `codex` is in the agent list (self):

Generate Codex's review inline:
1. Run `gh pr view --json number,title,body,headRefName`
2. Run `gh pr diff`
3. Read AGENTS.md and .github/CONTRIBUTING.md
4. Review for correctness, style, testing, security, documentation, architecture, breaking changes
5. Draft the review in the standard format:
   ```
   ## PR Review: #<number> — <title>
   ### Summary
   ### Findings
   #### Critical
   #### Suggestions
   #### Positive
   ### Verdict
   ---
   *Review by: Codex* | *Date: <today>*
   ```

#### If `claude` is in the agent list:

```bash
claude -p 'Read AGENTS.md and .github/CONTRIBUTING.md. Get the PR via `gh pr view --json number,title,body,headRefName`. Get the diff via `gh pr diff`. Review for: correctness, style, testing, security, documentation, architecture, breaking changes. Output ONLY the review: ## PR Review: #<number> — <title> / ### Summary / ### Findings / #### Critical / #### Suggestions / #### Positive / ### Verdict. End with --- and *Review by: Claude* | *Date: <today>*.'
```

Capture stdout as Claude's review.

#### If `copilot` is in the agent list:

```bash
copilot --allow-all -p 'Review the pull request for the current branch. 1) Run `gh pr view --json number,title,body,headRefName`. 2) Run `gh pr diff`. 3) Read AGENTS.md and .github/CONTRIBUTING.md. 4) Review for correctness, style, testing, security, documentation, architecture, breaking changes. 5) Output ONLY the review: ## PR Review: #<number> — <title> / ### Summary / ### Findings / #### Critical / #### Suggestions / #### Positive / ### Verdict. End with --- and *Review by: Copilot* | *Date: <today>*. Do NOT post to GitHub.' 2>/dev/null
```

Capture stdout as Copilot's review.

#### If `antigravity` is in the agent list:

```bash
agy -p 'Review the pull request for the current branch. If an Antigravity review skill (antigravity-review) is available, use it. Otherwise: 1) Run `gh pr view --json number,title,body,headRefName`. 2) Run `gh pr diff`. 3) Read AGENTS.md and .github/CONTRIBUTING.md. 4) Review for correctness, style, testing, security, documentation, architecture, breaking changes. 5) Output ONLY the review: ## PR Review: #<number> — <title> / ### Summary / ### Findings / #### Critical / #### Suggestions / #### Positive / ### Verdict. End with --- and *Review by: Antigravity* | *Date: <today>*. Do NOT post to GitHub.' --dangerously-skip-permissions --add-dir "$(git rev-parse --show-toplevel)" 2>/dev/null
```

Capture stdout as Antigravity's review.

If any agent fails or produces empty output, report the error and ask whether to continue or retry.

### Step 4: Post each review to the PR

```bash
gh pr comment <PR_NUMBER> --body "<agent review>"
```

Post one comment per agent.

### Step 5: Synthesize the findings

Create a synthesis listing: consensus findings (all agents), per-agent-only findings, combined verdict.

Format:
```
## Combined Review Summary

### Consensus Findings (all agents flagged)
- Description

### Per-Agent-Only Findings
- **<Agent>:** Description

### Combined Verdict
**Approve / Request Changes / Comment** — justification

---
*Synthesized Review by: Codex (from <agent1> + <agent2> + ... input)* | *Date: <today>*
```

### Step 6: User-approval gate

Present the synthesis and ask for approval before posting.

### Step 7: Post the approved synthesis

```bash
gh pr comment <PR_NUMBER> --body "<synthesis>"
```
