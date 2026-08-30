---
title: First 5 Minutes with an AI Agent
description: Narrative walkthrough of the AI agent workflow from issue to merge
audience:
  - contributors
  - ai-agents
tags:
  - ai
  - onboarding
  - walkthrough
---

# First 5 Minutes with an AI Agent

## Purpose

This page is a narrative walkthrough of the AI agent workflow this template ships with. It is aimed at a new adopter who has Claude Code installed, has opened the repository for the first time, and wants to see what a full issue-to-merge cycle looks like before diving into the reference material. It is intentionally not a reference — the command-by-command reference lives in [Slash Commands and Workflows](slash-commands.md). Read this page once, then use the reference when you need the details.

## Prerequisites

- Claude Code installed and authenticated. See [AI Agent Setup](../AI_SETUP.md) for installation and per-agent configuration.
- The [GitHub CLI](https://cli.github.com/) (`gh`) installed and logged in. The slash commands shell out to `gh` for issue and PR operations.
- Optionally, a second agent CLI (Copilot, Codex or Antigravity) if you want to run the multi-agent review commands. The single-agent flow described below does not require it.
- Alternatively, the [GitHub Copilot CLI](https://github.com/github/copilot-cli) can be used in place of Claude Code for the single-agent flow — it runs the same workflow through its own hyphen-named skills (`/copilot-plan`, `/copilot-implement`, …), discovered from `.github/skills/`. See [AI Agent Setup § 3. GitHub Copilot CLI](../AI_SETUP.md#3-github-copilot-cli) for the wiring.

The rest of this page assumes you have these working.

## The walkthrough

### 1. Open Claude Code in the repo

Launch Claude Code from the repository root. On startup Claude automatically loads `AGENTS.md` (workflow and conventions), `.claude/CLAUDE.md` (Claude-specific rules on top of `AGENTS.md`), and the project hooks under `tools/hooks/ai/` (which block dangerous commands for every agent, not just Claude). You do not need to paste any context — the template is designed so a fresh session already knows the rules.

If you are not sure what state you are in, run `/ghi-status` at any time (Claude) or the equivalent for your agent. It inspects the branch, issue state, plan comments, uncommitted changes, unpushed commits, and open PRs, then reports a summary and suggests the next command. It is read-only and safe to run whenever you are unsure.

### 2. Pick an issue

Every change starts from an issue. Either list the open backlog with `gh issue list` and pick one, or create a new issue with `doit issue --type=<type>` (types are `feature`, `bug`, `refactor`, `docs`, `chore`). The template enforces Issue → Branch → Commit → PR → Merge; there is no supported path that skips the issue.

For the rest of this walkthrough assume you have picked issue number `42`.

### 3. `/claude:plan 42`

Run `/claude:plan 42` in the main conversation. Claude enters plan mode, reads `AGENTS.md` and `.claude/CLAUDE.md`, fetches the issue, explores the codebase, and drafts a plan. Plan mode is interactive: Claude will ask questions and iterate with you until you approve the plan. Only on approval does it exit plan mode and post the plan as a comment on the issue with the header `## Implementation Plan for #42: <title>`. That posted comment is the artifact the next command reads.

What you'll see (illustrative — your plan will look different):

```markdown
## Implementation Plan for #42: feat: add caching layer to provider

### Context
The provider module currently makes a network call on every lookup...

### Files to create
- `src/__PACKAGE_NAME__/cache.py` — new LRU cache wrapper
- `tests/test_cache.py` — unit tests for hit, miss, eviction

### Files to modify
- `src/__PACKAGE_NAME__/provider.py` — wrap lookups in the cache

### Test plan
- Unit tests for cache hit, cache miss, eviction ordering
- Provider tests updated to assert the cache is consulted

### Validation
- `doit check` passes
```

Read the comment, discuss revisions in chat if anything is off, and re-run `/claude:plan 42` if you need a fresh pass.

### 4. `/claude:implement 42`

Once the plan comment exists, run `/claude:implement 42`. Claude checks out `main`, pulls, and creates a branch whose type is derived from the issue's labels — for example, a `feature` issue becomes `feat/42-add-caching-layer`. Claude then spawns a subagent via the Task tool. The subagent does the heavy work: re-reads `AGENTS.md`, fetches the plan via `gh api`, creates files, writes tests, and runs `doit check`, fixing failures rather than giving up. The main conversation context receives only the subagent's summary, which keeps your scrollback clean and your context window small.

The artifact at the end of this step is an uncommitted working tree on the feature branch. Nothing has been committed yet — that is deliberate.

### 5. (Optional) `/multi-review claude codex`

If you have a second agent CLI installed and want another opinion on the changes, you can run `/multi-review claude codex` at this point (after a PR exists). This runs both agents in isolated contexts, posts each review as a separate PR comment, and then synthesizes the findings for you to approve before posting. If you want an adversarial challenge instead of a code review, use `/multi-adversarial-review claude codex`. Skip this step if you are running single-agent.

### 6. `/ghi-finalize`

Run `/ghi-finalize` when you are satisfied with the changes. Claude detects the branch and issue number, spawns a finalization subagent that reviews changed files for doc/ADR updates, runs `doit check` one more time, and drafts both a commit message and a PR body. The main conversation then presents the drafts to you and **waits for explicit approval** before staging files, committing, and running `doit pr`. Nothing gets committed without your go-ahead.

What you'll see (illustrative — your drafts will look different):

```markdown
Proposed commit message:

  feat: add LRU cache to provider lookups

  Wraps provider.lookup() in a bounded LRU cache to eliminate
  repeated network calls for the same key within a session.

  Addresses #42

Proposed PR body:

  ## Summary
  Adds a small LRU cache in front of the provider network calls.

  ## Changes
  - New `cache.py` with an LRU wrapper
  - Provider updated to consult the cache
  - Unit tests for hit, miss, eviction

  ## Validation
  - `doit check` passes locally

  Addresses #42

Approve and commit? (yes / edit / no)
```

Approve, and Claude stages the files, commits, and opens the PR via `doit pr`. The artifact is an open PR referencing `Addresses #42`.

### 7. Merge

Merging is never automated. Review the PR yourself, wait for CI to go green, add the `ready-to-merge` label, and merge via `doit pr_merge` (or the GitHub web UI). The `ready-to-merge` label and the Merge Gate action are designed to be a human checkpoint — do not let an agent add that label for you.

### 8. Close the issue

After the PR merges, close the linked issue. The easiest path is to have merged with `doit pr_merge --auto-close`, which closes the issue and posts a closing comment in one step. If you merged via the web UI, close manually:

```bash
gh issue close 42 --comment "Addressed in PR #<pr-number>"
```

That is the full loop.

## What each command produces

Every step in the flow produces a specific artifact the next step expects:

- `/<currentai>:plan <n>` → a plan comment on the issue with the header `## Implementation Plan for #<n>`
- `/<currentai>:implement <n>` → a feature branch with an uncommitted working tree
- `/ghi-finalize` → a staged commit plus an open PR referencing `Addresses #<n>`
- Merge → a merged commit on `main` and a closed PR
- `doit pr_merge --auto-close` (or `gh issue close`) → a closed issue with a closing comment

Knowing the artifact chain is the fastest way to figure out where you are if you get interrupted mid-flow.

## If you get lost

Run `/ghi-status`. It is read-only, has no side effects, and will tell you the current branch, issue state, plan comment status, uncommitted changes, unpushed commits, open PRs, and the suggested next command. Run it any time you are unsure. For the full command-by-command reference and the dual-agent variants, see [Slash Commands and Workflows](slash-commands.md).

## See also

- [Slash Commands and Workflows](slash-commands.md) — full command reference and dual-agent workflow.
- [AI Agent Setup](../AI_SETUP.md) — per-CLI configuration, permissions, and hooks.
- [Architectural Conventions](architectural-conventions.md) — imperative rules for AI-generated code.
- [AGENTS.md](../../../AGENTS.md) — universal context file and workflow reference.
- [`.claude/rules/` scaffold](../../../.claude/rules/README.md) — per-stack rule-file pattern for Claude Code.
- [`.github/instructions/` scaffold](../../../.github/instructions/README.md) — per-stack instruction-file pattern for GitHub Copilot.
- [`.agents/skills/` scaffold](../../../.agents/skills/README.md) — per-stack rule-shaped skill pattern for Codex CLI.
- <!-- TODO: wire this link up properly when #342 lands -->
  For an end-to-end example of the *coding* side of a feature (creating a module, CLI subcommand, tests, and docs), see [the add-a-feature example](https://github.com/endavis/pyproject-template/blob/main/examples/add-a-feature.md) (tracked in [#342](https://github.com/endavis/pyproject-template/issues/342)).
