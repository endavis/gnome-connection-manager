---
name: multi-adversarial-review
description: Run multiple AI agents in parallel for adversarial review of current changes from a Codex session, then synthesize challenges and recommended actions.
---

# Multi-Agent Adversarial Review

Run multiple AI agents in parallel to independently challenge the current changes with adversarial reviews, then synthesize findings.

## When to use

Use this skill when the user wants multiple agents to adversarially challenge the current changes.

Expected prompt shape:

- `$multi-adversarial-review claude codex`
- `$multi-adversarial-review pressure-test these changes with claude and codex`

If the agent list is missing, ask for it before continuing.

## Instructions

### Step 0: Parse arguments

Extract the agent list from the user's request.
Allowed agent names: `claude`, `copilot`, `codex`, `antigravity`.

- If no agents are given, ask for the agent list.
- If any agent name is not in the allowed list, report the unknown name, list allowed names, and stop.

### Step 1: Verify there are changes to review

```bash
git status
git log main..HEAD --oneline
```

- If there are no uncommitted changes and no branch commits beyond main, tell the user there is nothing to review and stop.

### Step 2: Generate adversarial reviews in parallel

Each review MUST be in an isolated context.

#### If `codex` is in the agent list (self):

Generate Codex's adversarial review inline:
1. Run `git status`, `git diff`, `git log main..HEAD`
2. Read AGENTS.md and related ADRs in docs/decisions/
3. Pressure-test design choices, hidden assumptions, tradeoffs, alternatives, failure modes
4. Draft in the standard format:
   ```
   ## Adversarial Review
   ### Direction Critique
   ### Hidden Assumptions
   ### Failure Modes
   ### Alternatives Worth Considering
   ---
   *Adversarial Review by: Codex* | *Date: <today>*
   ```

#### If `claude` is in the agent list:

```bash
claude -p 'Run an adversarial review of the current uncommitted changes and the current branch vs main. Read-only. Be skeptical: pressure-test design choices, hidden assumptions, tradeoffs, alternatives, failure modes (auth, data loss, races, rollback, reliability). 1) Run `git status`, `git diff`, `git log main..HEAD`. 2) Read AGENTS.md and related ADRs. 3) Ask: right approach? Safer alternative? Edge cases? Hidden coupling? 4) Output ONLY: ## Adversarial Review / ### Direction Critique / ### Hidden Assumptions / ### Failure Modes / ### Alternatives Worth Considering. End with --- and *Adversarial Review by: Claude* | *Date: <today>*. Do NOT modify any files.'
```

Capture stdout as Claude's adversarial review.

#### If `copilot` is in the agent list:

```bash
copilot --allow-all -p 'Run an adversarial review of the current uncommitted changes and the current branch vs main. Read-only. Be skeptical: pressure-test design choices, hidden assumptions, tradeoffs, alternatives, failure modes. 1) Run `git status`, `git diff`, `git log main..HEAD`. 2) Read AGENTS.md and related ADRs. 3) Ask: right approach? Safer alternative? Edge cases? Hidden coupling? 4) Output ONLY: ## Adversarial Review / ### Direction Critique / ### Hidden Assumptions / ### Failure Modes / ### Alternatives Worth Considering. End with --- and *Adversarial Review by: Copilot* | *Date: <today>*. Do NOT modify any files.' 2>/dev/null
```

Capture stdout as Copilot's adversarial review.

#### If `antigravity` is in the agent list:

```bash
agy -p 'Run an adversarial review of the current uncommitted changes and the current branch vs main. Read-only. Be skeptical: pressure-test design choices, hidden assumptions, tradeoffs, alternatives, failure modes (auth, data loss, races, rollback, reliability). 1) Run `git status`, `git diff`, `git log main..HEAD`. 2) Read AGENTS.md and related ADRs. 3) Ask: right approach? Safer or simpler alternative? Edge cases missed? Hidden coupling? 4) Output ONLY the review: ## Adversarial Review / ### Direction Critique / ### Hidden Assumptions / ### Failure Modes / ### Alternatives Worth Considering. End with --- and *Adversarial Review by: Antigravity* | *Date: <today>*. Do NOT modify any files.' --dangerously-skip-permissions --add-dir "$(git rev-parse --show-toplevel)" 2>/dev/null
```

Capture stdout as Antigravity's adversarial review.

If any agent fails or produces empty output, report the error and ask whether to continue or retry.

### Step 3: Synthesize the findings

Create a synthesis listing: consensus challenges (all agents), per-agent-only challenges, recommended actions.

Format:
```
## Combined Adversarial Review Summary

### Consensus Challenges (all agents raised)
- Description

### Per-Agent-Only Challenges
- **<Agent>:** Description

### Recommended Actions
- Prioritized list of what to address before shipping

---
*Synthesized Adversarial Review by: Codex (from <agent1> + <agent2> + ... input)* | *Date: <today>*
```

### Step 4: User-approval gate

Present the synthesis. This is a *challenge* — the user decides whether to accept, defer, or push back.

### Step 5: Post the approved synthesis (if PR exists)

If a PR exists:

```bash
gh pr comment <PR_NUMBER> --body "<synthesis>"
```

If no PR exists, present the synthesis in the conversation only.
