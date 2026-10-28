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

This page is a narrative walkthrough of the AI agent workflow this project ships with. It is aimed at a new adopter who has Claude Code installed, has opened the repository for the first time, and wants to see what a full issue-to-merge cycle looks like before diving into the reference material. It is intentionally not a reference — the command-by-command reference lives in [Slash Commands and Workflows](slash-commands.md). Read this page once, then use the reference when you need the details.

## Prerequisites

- Claude Code installed and authenticated. See [AI Agent Setup](../AI_SETUP.md) for installation and per-agent configuration.
- The [GitHub CLI](https://cli.github.com/) (`gh`) installed and logged in. The slash commands shell out to `gh` for issue and PR operations.
- Optionally, a second agent CLI (Copilot, Codex or Antigravity) if you want to run the multi-agent review commands. The single-agent flow described below does not require it.
- Alternatively, the [GitHub Copilot CLI](https://github.com/github/copilot-cli) can be used in place of Claude Code for the single-agent flow — "implement issue 42" activates the same shared `implement-issue` skill (discovered from `.agents/skills/`), and review commands run through its own hyphen-named skills (`/copilot-review`, `/copilot-adversarial-review`). See [AI Agent Setup § 3. GitHub Copilot CLI](../AI_SETUP.md#3-github-copilot-cli) for the wiring.

The rest of this page assumes you have these working.

## The walkthrough

### 1. Open Claude Code in the repo

Launch Claude Code from the repository root. On startup Claude automatically loads `AGENTS.md` (workflow and conventions), `.claude/CLAUDE.md` (Claude-specific rules on top of `AGENTS.md`), and the project hooks under `tools/hooks/ai/` (which block dangerous commands for every agent, not just Claude). You do not need to paste any context — the template is designed so a fresh session already knows the rules.

If you are not sure what state you are in, run `/ghi-status` at any time (Claude) or the equivalent for your agent. It inspects the branch, issue state, plan comments, uncommitted changes, unpushed commits, and open PRs, then reports a summary and suggests the next command. It is read-only and safe to run whenever you are unsure.

### 2. Pick an issue

Every change starts from an issue. Either list the open backlog with `gh issue list` and pick one, or create a new issue with `doit issue --type=<type>` (types are `feature`, `bug`, `refactor`, `docs`, `chore`). The template enforces Issue → Branch → Commit → PR → Merge; there is no supported path that skips the issue.

For the rest of this walkthrough assume you have picked issue number `42`.

### 3. "implement issue 42"

Say "implement issue 42" in the main conversation — no slash command, just natural language. The shared `implement-issue` skill (`.agents/skills/implement-issue/SKILL.md`, generated for Claude by `doit skills_sync`) takes it from there:

1. It checks out `main`, pulls, and creates a branch whose type is derived from the issue's labels — for example, a `feature` issue becomes `feat/42-add-caching-layer` — or resumes the existing branch if you already have one for this issue.
2. It decides whether to plan first: the issue carries `needs-adr`, the change touches more than about three files or adds a module, or more than one approach is reasonable. **There is no approval wait** — if it plans, the plan is posted straight to the issue as a comment with the header `## Implementation Plan for #42: <title>`.
3. It spawns a subagent (Claude's is `implement-worker`) to do the heavy work: re-read `AGENTS.md`, fetch the plan (or use the issue body directly), create files, write tests, and run `doit check`, fixing failures rather than giving up. The main conversation context receives only the subagent's summary.
4. It runs `doit check` and `doit docs_build` again, commits with `git commit` in the CONTRIBUTING format, pushes, and opens the PR with `doit pr` — `Addresses #42` included. **There is no approval wait here either** — this is the trade for collapsing three commands into one.
5. It watches `gh pr checks` and fixes any failing job other than `require-label` for up to 3 rounds, then stops and reports whatever is still red.

What you'll see at the end (illustrative — yours will look different):

```markdown
## Summary
Added an LRU cache in front of the provider's network calls (no plan needed —
single-file change with one reasonable approach).

## Files changed
- `src/__PACKAGE_NAME__/cache.py` — new LRU cache wrapper
- `src/__PACKAGE_NAME__/provider.py` — wraps lookups in the cache
- `tests/test_cache.py` — hit, miss, eviction-order tests

## PR
https://github.com/you/your-repo/pull/43 (Addresses #42)

## CI state
All checks passing except `require-label` (expected — that's the human merge gate).
```

The artifact is an open PR referencing `Addresses #42`. Your first checkpoint is reviewing that PR, not approving an in-chat plan or commit.

If your checkout holds work you want left alone, do not run this step there: see [When your checkout holds other work](#when-your-checkout-holds-other-work) first.

### 4. Review the PR

Review the diff on GitHub. If you have a second agent CLI installed and want another opinion, run `/multi-review claude codex` to have both agents independently review the PR and synthesize their findings for your approval before posting, or `/multi-adversarial-review claude codex` for an adversarial challenge instead. For small fixes, just edit directly, run `doit check`, commit, and push — there is no need to re-run the whole skill.

### 5. Merge

Merging is never automated, and `implement-issue` never applies the `ready-to-merge` label or merges for you. Review the PR yourself, wait for CI to go green (`require-label` is the only check expected to stay red), add the `ready-to-merge` label, and merge via `doit pr_merge` (or the GitHub web UI). A PR from a worktree is merged from the main checkout instead: see [When your checkout holds other work](#when-your-checkout-holds-other-work).

### 6. Close the issue

After the PR merges, close the linked issue. The easiest path is to have merged with `doit pr_merge --auto-close`, which closes the issue and posts a closing comment in one step. If you merged via the web UI, close manually:

```bash
gh issue close 42 --comment "Addressed in PR #<pr-number>"
```

That is the full loop.

## When your checkout holds other work

Step 3 checks out `main` in the checkout Claude runs in. If yours holds work you want left alone, give the issue its own [worktree](../doit-tasks-reference.md#worktree) before step 3, and start Claude Code there:

```bash
doit worktree --branch=feat/42-add-caching-layer
cd worktrees/feat/42-add-caching-layer
direnv allow  # direnv users: switches the shell to the worktree's .venv
claude
```

The worktree is a separate checkout with its own `.venv`, on a new branch from `origin/main`. Name the branch the way `implement-issue` would, `<type>/42-<description>`. Saying "implement issue 42" then finds it is already on a branch for issue 42, skips creating one, and does the work in the worktree. Steps 4 through 6 run there unchanged.

Step 5 changes: merge from the main checkout, and pass the PR number. Without `--pr`, `doit pr_merge` looks up the PR for the main checkout's own branch instead. From the main checkout:

```bash
uv run doit pr_merge --pr=<pr-number> --auto-close
```

That merges the PR, closes issue 42, removes the worktree and its branch, and fast-forwards the main checkout's `main`. See [`pr_merge`](../doit-tasks-reference.md#pr_merge) for when it keeps them instead.

## What each step produces

Every step in the flow produces a specific artifact the next step expects:

- "implement issue N" → (sometimes) a plan comment on the issue with the header `## Implementation Plan for #<n>`, always a branch, a commit, and an open PR referencing `Addresses #<n>`
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
- [Per-stack rule files](rule-files.md) — the `.claude/rules/` pattern for Claude Code.
- [`.github/instructions/` scaffold](../../../.github/instructions/README.md) — per-stack instruction-file pattern for GitHub Copilot.
- [`.agents/skills/` scaffold](../../../.agents/skills/README.md) — per-stack rule-shaped skill pattern for Codex CLI.
- <!-- TODO: wire this link up properly when #342 lands -->
  For an end-to-end example of the *coding* side of a feature (creating a module, CLI subcommand, tests, and docs), see [the add-a-feature example](../../examples/add-a-feature.md) (tracked in [#342](https://github.com/endavis/pyproject-template/issues/342)).
