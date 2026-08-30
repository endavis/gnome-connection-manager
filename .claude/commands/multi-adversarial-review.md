# Multi-Agent Adversarial Review

Run multiple AI agents in parallel to independently challenge the current changes with adversarial reviews, then synthesize findings.

## Instructions

### Step 0: Parse arguments

Arguments: `<ais...>`

All arguments are agent names. No issue number is needed — the review targets current uncommitted changes and the current branch vs main.
Allowed agent names: `claude`, `copilot`, `codex`, `antigravity`.

- If no agents are given, tell the user the required syntax and stop.
- If any agent name is not in the allowed list, report the unknown name, list allowed names, and stop.

Example: `/multi-adversarial-review claude codex` → agents: [claude, codex]

### Step 1: Verify there are changes to review

```bash
git status
git log main..HEAD --oneline
```

- If there are no uncommitted changes and no branch commits beyond main, tell the user there is nothing to review and stop.

### Step 2: Generate adversarial reviews in parallel (separate contexts)

Each review MUST be generated in an isolated context so no agent influences another.

For **each agent** in the list, run its review generation in parallel:

#### If `claude` is in the agent list:

Use the Task tool to spawn a subagent with this prompt:
> Run an adversarial review of the current uncommitted changes and the current branch vs main. Read-only.
> Be skeptical and steerable: pressure-test design choices, hidden assumptions, tradeoffs, alternative approaches, failure modes (auth, data loss, races, rollback, reliability).
> 1) Run `git status`, `git diff`, `git log main..HEAD`.
> 2) Read AGENTS.md and related ADRs in docs/decisions/.
> 3) Ask: was this the right approach? Would a different design be safer or simpler? What edge cases are missed? What hidden coupling exists?
> 4) Output findings in this format:
>
> ## Adversarial Review
> ### Direction Critique
> ### Hidden Assumptions
> ### Failure Modes
> ### Alternatives Worth Considering
>
> End with: `---` followed by `*Adversarial Review by: Claude* | *Date: <today's date>*`
>
> Output ONLY the review markdown. Do NOT modify any files.

Save the subagent's output as Claude's adversarial review.

#### If `copilot` is in the agent list:

```bash
copilot --allow-all -p 'Run an adversarial review of the current uncommitted changes and the current branch vs main. Read-only. Be skeptical: pressure-test design choices, hidden assumptions, tradeoffs, alternatives, failure modes (auth, data loss, races, rollback, reliability). 1) Run `git status`, `git diff`, `git log main..HEAD`. 2) Read AGENTS.md and related ADRs. 3) Ask: was this the right approach? Safer or simpler alternative? Edge cases missed? Hidden coupling? 4) Output ONLY the review in this format: ## Adversarial Review / ### Direction Critique / ### Hidden Assumptions / ### Failure Modes / ### Alternatives Worth Considering. End with --- and *Adversarial Review by: Copilot* | *Date: <today>*. Do NOT modify any files.' 2>/dev/null
```

Capture stdout as Copilot's adversarial review.

#### If `codex` is in the agent list:

```bash
codex -a never --dangerously-bypass-hook-trust exec 'Run an adversarial review of the current uncommitted changes and the current branch vs main. Read-only. Be skeptical: pressure-test design choices, hidden assumptions, tradeoffs, alternatives, failure modes (auth, data loss, races, rollback, reliability). 1) Run `git status`, `git diff`, `git log main..HEAD`. 2) Read AGENTS.md and related ADRs. 3) Ask: was this the right approach? Safer or simpler alternative? Edge cases missed? Hidden coupling? 4) Output ONLY the review in this format: ## Adversarial Review / ### Direction Critique / ### Hidden Assumptions / ### Failure Modes / ### Alternatives Worth Considering. End with --- and *Adversarial Review by: Codex* | *Date: <today>*. Do NOT modify any files.'
```

Capture stdout as Codex's adversarial review.

#### If `antigravity` is in the agent list:

```bash
agy -p 'Run an adversarial review of the current uncommitted changes and the current branch vs main. Read-only. Be skeptical: pressure-test design choices, hidden assumptions, tradeoffs, alternatives, failure modes (auth, data loss, races, rollback, reliability). 1) Run `git status`, `git diff`, `git log main..HEAD`. 2) Read AGENTS.md and related ADRs. 3) Ask: right approach? Safer or simpler alternative? Edge cases missed? Hidden coupling? 4) Output ONLY the review: ## Adversarial Review / ### Direction Critique / ### Hidden Assumptions / ### Failure Modes / ### Alternatives Worth Considering. End with --- and *Adversarial Review by: Antigravity* | *Date: <today>*. Do NOT modify any files.' --dangerously-skip-permissions --add-dir "$(git rev-parse --show-toplevel)" 2>/dev/null
```

Capture stdout as Antigravity's adversarial review.

If any agent fails or produces empty output, report the error and ask the user whether to continue with remaining reviews or retry.

### Step 3: Synthesize the findings

Read all adversarial reviews and create a synthesis that:
- Lists challenges all agents raised (highest priority — independently discovered)
- Lists challenges only some agents raised (worth investigating)
- Notes any disagreements in recommendations
- Provides combined recommended actions

Format:
```
## Combined Adversarial Review Summary

### Consensus Challenges (all agents raised)
- Description of shared challenge

### Per-Agent-Only Challenges
- **<Agent>:** Description of challenge only that agent raised

### Recommended Actions
- Prioritized list of what to address before shipping

---
*Synthesized Adversarial Review by: Claude (from <agent1> + <agent2> + ... input)* | *Date: <today's date>*
```

### Step 4: User-approval gate

Present the synthesis to the user and ask for approval before posting.
This is a *challenge* — the user decides whether to accept, defer, or push back on each finding.

### Step 5: Post the approved synthesis (if PR exists)

If a PR exists for the current branch, post the synthesis:

```bash
gh pr comment <PR_NUMBER> --body "<synthesis>"
```

If no PR exists, present the synthesis in the conversation only.
