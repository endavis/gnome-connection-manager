---
name: multi-plan
description: Run multiple AI agents in parallel to create independent implementation plans for a GitHub issue, then synthesize them into a single plan. Works the same from any host CLI (Claude Code, Codex CLI, Copilot CLI, Antigravity CLI).
---

# Multi-Agent Plan

Run multiple AI agents in parallel to create independent implementation plans for a GitHub issue, then synthesize them.

## When to use

Use this skill when the user wants multiple agents to independently plan an issue.

Expected prompt shape:

- `multi-plan claude codex 42`
- "run a multi-agent plan for issue 42 with claude and codex"

If the agent list or issue number is missing, ask for it before continuing.

## Agent invocations

Step 0 below already removed your own CLI from the agent list. Run your own part directly, in this
session (Step 3 below). Call every agent that list left through its CLI, exactly as this table gives
it — copied from [cross-agent-delegation.md — Non-interactive flags per
CLI](../../../docs/development/ai/cross-agent-delegation.md#non-interactive-flags-per-cli), which
stays the source of truth:

| Agent | Invocation |
| :--- | :--- |
| `claude` | `claude -p '<prompt>'` |
| `codex` | `codex -a never --dangerously-bypass-hook-trust exec '<prompt>' < /dev/null` |
| `copilot` | `copilot --allow-all -p '<prompt>'` |
| `antigravity` | `agy -p '<prompt>' --dangerously-skip-permissions --add-dir "$(git rev-parse --show-toplevel)"` |

A headless Codex host (`codex exec -a never`) can read GitHub through `.codex/rules/gh.rules` but cannot write to it or delegate to another agent CLI — see [Headless Codex host limits](../../../docs/development/ai/cross-agent-delegation.md#headless-codex-host-limits). It cannot run Step 3's delegation to the other listed agents or Step 4's `gh issue comment` headless; Codex hosts this skill interactively instead.

## Instructions

### Step 0: Parse arguments

Extract the agent list and issue number from the user's request.
Allowed agent names: `claude`, `copilot`, `codex`, `antigravity`.

- If the issue number is missing, tell the user the required syntax and stop.
- If any agent name is not in the allowed list, report the unknown name, list allowed names, and stop.

Then remove your own name — the CLI running this skill — from the agent list. Every later step uses only the agents that remain: you never call your own CLI. If no agent remains, tell the user and stop.

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

Every agent's plan comes from the same source — the **Planner brief** in
[`implement-issue`](../implement-issue/SKILL.md#planner-brief) — so the plans are directly
comparable. The brief's format has no `### Risks and Considerations` section; that belonged to the
old per-agent plan format this replaces. Each plan MUST be produced in an isolated context.

Before generating any plan, fetch the issue context the Planner brief reads, once, shared by every
agent (your own inline run and every delegated one):

```bash
doit delegation_context --kind=issue --n=<issue> --out=tmp/agents/<host>/multi-plan-<issue>/
```

#### You (the agent running this skill)

Run the Planner brief for issue #<issue> the same way `implement-issue`'s own Step 3 does — in a
subagent if your host provides one (see `implement-issue`'s [Per-host subagent
notes](../implement-issue/SKILL.md#per-host-subagent-notes)), otherwise inline in this session,
telling it the context directory above. Append `---` followed by `*Plan by: <your agent name>* |
*Date: <today>*` to what the brief returns, and capture that as your plan.

#### Every agent remaining after Step 0 removed yours

Invoke it with its row from [Agent invocations](#agent-invocations) above, substituting this prompt
(filling in `<issue>`, `<context-dir>`, and `<agent name>`):

> Read the Planner brief in `.agents/skills/implement-issue/SKILL.md` (the `## Planner brief`
> section) and follow it for issue #<issue> in the current repository. The issue context has
> already been fetched to `<context-dir>` — read `issue.json`/`comments.json` from there instead of
> running `gh`. If the context directory is missing or unreadable, print `DELEGATION-ERROR:` and
> stop. Append `---` followed by `*Plan by: <agent name>* | *Date: <today>*`. Output ONLY the
> resulting plan markdown.

For example, to delegate to Claude:

```bash
claude -p 'Read the Planner brief in .agents/skills/implement-issue/SKILL.md (the "## Planner brief" section) and follow it for issue #<issue> in the current repository. The issue context has already been fetched to <context-dir> — read issue.json/comments.json from there instead of running gh. If the context directory is missing or unreadable, print DELEGATION-ERROR: and stop. Append --- followed by *Plan by: Claude* | *Date: <today>*. Output ONLY the resulting plan markdown.'
```

Capture stdout as that agent's plan. Delete `tmp/agents/<host>/multi-plan-<issue>/` once every
agent has returned.

If any agent fails or produces empty output, report the error and ask whether to continue or retry. Also treat output containing `DELEGATION-ERROR:` as a failed run: the agent's context file was missing or unreadable, so whatever else it printed rests on no data.

### Step 4: Post each plan to the issue

```bash
gh issue comment <issue> --body "<agent plan>"
```

Post one comment per agent.

### Step 5: Synthesize the final plan

Create a synthesized plan combining the best elements from all plans. Note agreements (high
confidence) and divergences (needs discussion). Use the same format as the Planner brief.

Signature:
```
---
*Synthesized Plan by: <host agent> (from <agent1> + <agent2> + ... input)* | *Date: <today>*
```

### Step 6: Iterate with user

Present the synthesized plan and ask for feedback. Do NOT post until the user approves.

### Step 7: Post the approved synthesized plan

```bash
gh issue comment <issue> --body "<synthesized plan>"
```

Tell the user the plans have been posted and the next step is "implement issue <issue>" (optionally
"... with \<agent\>" to hand off only the coding step).

## See also

- [`implement-issue`](../implement-issue/SKILL.md) — the Planner brief this skill reuses, and the
  single-agent flow that follows once a plan is posted.
- [Cross-Agent Delegation Matrix](../../../docs/development/ai/cross-agent-delegation.md) — the
  non-interactive invocation table this skill's [Agent invocations](#agent-invocations) section
  copies.
