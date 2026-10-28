---
name: multi-adversarial-review
description: Run multiple AI agents in parallel for adversarial review of current changes, then synthesize challenges and recommended actions. Works the same from any host CLI (Claude Code, Codex CLI, Copilot CLI, Antigravity CLI).
---

# Multi-Agent Adversarial Review

Run multiple AI agents in parallel to independently challenge the current changes with adversarial reviews, then synthesize findings.

## When to use

Use this skill when the user wants multiple agents to adversarially challenge the current changes.

Expected prompt shape:

- `multi-adversarial-review claude codex`
- "pressure-test these changes with claude and codex"

If the agent list is missing, ask for it before continuing.

**Read-only.** Review and report — do not edit files, commit, or push. Findings go to the user and the PR; any fix is a separate change the user asks for.

## Agent invocations

Step 0 below already removed your own CLI from the agent list. Run your own review directly, in this
session (Step 2 below). Call every agent that list left through its CLI, exactly as this table gives
it — copied from [cross-agent-delegation.md — Non-interactive flags per
CLI](../../../docs/development/ai/cross-agent-delegation.md#non-interactive-flags-per-cli), which
stays the source of truth:

| Agent | Invocation |
| :--- | :--- |
| `claude` | `claude -p '<prompt>'` |
| `codex` | `codex -a never --dangerously-bypass-hook-trust exec '<prompt>' < /dev/null` |
| `copilot` | `GITHUB_COPILOT_PROMPT_MODE_REPO_HOOKS=true copilot --allow-all -p '<prompt>'` |
| `antigravity` | `agy -p '<prompt>' --dangerously-skip-permissions --add-dir "$(git rev-parse --show-toplevel)"` |

A headless Codex host (`codex exec -a never`) can read GitHub through `.codex/rules/gh.rules` but cannot write to it or delegate to another agent CLI — see [Headless Codex host limits](../../../docs/development/ai/cross-agent-delegation.md#headless-codex-host-limits). It cannot run Step 2's delegation to the other listed agents or Step 5's `gh pr comment` headless; Codex hosts this skill interactively instead.

## Instructions

### Step 0: Parse arguments

Extract the agent list from the user's request.
Allowed agent names: `claude`, `copilot`, `codex`, `antigravity`.

- If no agents are given, ask for the agent list.
- If any agent name is not in the allowed list, report the unknown name, list allowed names, and stop.

Then remove your own name — the CLI running this skill — from the agent list. Every later step uses only the agents that remain: you never call your own CLI. If no agent remains, tell the user and stop.

### Step 1: Verify there are changes to review

```bash
git status
git log main..HEAD --oneline
```

- If there are no uncommitted changes and no branch commits beyond main, tell the user there is nothing to review and stop.

### Step 2: Generate adversarial reviews in parallel

Each review MUST be in an isolated context.

#### You (the agent running this skill)

Run your adversarial review inline:
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
   *Adversarial Review by: <your agent name>* | *Date: <today>*
   ```

#### Every agent remaining after Step 0 removed yours

Invoke it with its row from [Agent invocations](#agent-invocations) above, substituting this prompt
(filling in `<agent name>`):

> Run an adversarial review of the current uncommitted changes and the current branch vs main.
> Read-only. Be skeptical: pressure-test design choices, hidden assumptions, tradeoffs, alternatives,
> failure modes (auth, data loss, races, rollback, reliability). 1) Run `git status`, `git diff`,
> `git log main..HEAD`. 2) Read AGENTS.md and related ADRs. 3) Ask: right approach? Safer
> alternative? Edge cases? Hidden coupling? 4) Output ONLY: ## Adversarial Review / ### Direction
> Critique / ### Hidden Assumptions / ### Failure Modes / ### Alternatives Worth Considering. End
> with --- and *Adversarial Review by: <agent name>* | *Date: <today>*. Do NOT modify any files.

For example, to delegate to Claude:

```bash
claude -p 'Run an adversarial review of the current uncommitted changes and the current branch vs main. Read-only. Be skeptical: pressure-test design choices, hidden assumptions, tradeoffs, alternatives, failure modes (auth, data loss, races, rollback, reliability). 1) Run `git status`, `git diff`, `git log main..HEAD`. 2) Read AGENTS.md and related ADRs. 3) Ask: right approach? Safer alternative? Edge cases? Hidden coupling? 4) Output ONLY: ## Adversarial Review / ### Direction Critique / ### Hidden Assumptions / ### Failure Modes / ### Alternatives Worth Considering. End with --- and *Adversarial Review by: Claude* | *Date: <today>*. Do NOT modify any files.'
```

Capture stdout as that agent's adversarial review.

If any agent fails or produces empty output, report the error and ask whether to continue or retry. Also treat output containing `DELEGATION-ERROR:` as a failed run: the agent's context file was missing or unreadable, so whatever else it printed rests on no data.

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
*Synthesized Adversarial Review by: <host agent> (from <agent1> + <agent2> + ... input)* | *Date: <today>*
```

### Step 4: User-approval gate

Present the synthesis. This is a *challenge* — the user decides whether to accept, defer, or push back.

### Step 5: Post the approved synthesis (if PR exists)

If a PR exists:

```bash
gh pr comment <PR_NUMBER> --body "<synthesis>"
```

If no PR exists, present the synthesis in the conversation only.

## See also

- [Cross-Agent Delegation Matrix](../../../docs/development/ai/cross-agent-delegation.md) — the
  non-interactive invocation table this skill's [Agent invocations](#agent-invocations) section
  copies, and the read-only constraint every review file carries.
