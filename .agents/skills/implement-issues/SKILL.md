---
name: implement-issues
description: Use when the user says "implement issues A, B and C" (or "implement issues A and B", "work on issues A, B", "take issues A, B to PRs") — several issues in one request. Checks every issue is open and compares their likely files (overlap sets the PR order), creates one worktree per issue, runs implement-issue for each in its own background agent up to the push (default 2 at a time, --max=N overrides), then the orchestrator itself opens the PRs one at a time, each rebased on main first. "check only" stops after the overlap check. Never adds ready-to-merge, never merges, never closes an issue. For a single issue use implement-issue.
---

# Implement Issues

Take several open GitHub issues to one PR each from a single session: the work runs in parallel, the
PRs are opened one at a time by the orchestrator. Each issue runs [`implement-issue`](../implement-issue/SKILL.md) up to
the push in its own worktree and its own background agent (phase 1); the orchestrator then opens the PRs
one after another, each rebased on `origin/main` first (phase 2). "Implement issues A, B and C" authorizes, per issue, what "implement issue N"
authorizes: commit, push and PR creation on that issue's own branch. It is not consent to add
`ready-to-merge`, merge or close.

## Instructions

The arguments are two or more issue numbers, optionally `--max=N` (concurrency cap, default 2) and
`check only`. With a single number, tell the user to use `implement-issue` and stop. Run Steps 1 to 5
from the main checkout and never leave it (phase 2 commands target a worktree with `git -C` or `cd`).

### Step 1: Pre-flight (before any worktree exists)

For each issue:

```bash
gh issue view <n> --json number,title,state,labels,body
gh api repos/{owner}/{repo}/issues/<n>/comments --jq '.[] | select(.body | test("^#+ Implementation Plan for"; "m")) | .body'
```

- The issue must be open. If one is closed, drop it and say so.
- Determine the branch type from its labels with the mapping in
  [implement-issue Step 1.2](../implement-issue/SKILL.md#step-1-preconditions). Do not restate the
  mapping here.
- Build its likely file set from the paths named in the issue body and in the newest
  `Implementation Plan for` comment, if there is one.

Print a table with one row per issue: issue, type/branch, likely files, overlaps with other issues.
Overlap does not block the run: it only sets the phase 2 order (see Step 4).

With `check only`, stop here: the table is the whole output, no worktree is created and nothing is
changed.

### Step 2: Create the worktrees, one after another

From the main checkout, for each issue in turn (never concurrently):

```bash
git worktree list --porcelain
git branch --list '<type>/<n>-*'
uv run doit worktree --branch=<type>/<n>-<short-description>
```

- An issue that already has a worktree on `<type>/<n>-*` is resumed there; do not create another.
- An issue with a local branch but no worktree stops on its own and is reported: `doit worktree` uses
  `git worktree add -b`, which fails on an existing branch. The other issues go on.
- Record each worktree's absolute path as that issue's `WORKTREE`.

### Step 3: Run one background agent per issue

Start one `general-purpose` subagent per issue with `run_in_background: true`, at most `--max=N` at a
time (default 2). `doit test` already runs `pytest -n auto`, so one `doit check` uses every core.
Issues past the cap wait in a queue; start the next when an agent returns. `--max` counts only these
phase 1 agents. You, the orchestrator, do no phase 1 coding.

Prompt each agent with this, filling in the issue number and absolute `$WORKTREE`:

> Run the `implement-issue` skill for issue <n>, reading
> `<WORKTREE>/.claude/skills/implement-issue/SKILL.md`. Your worktree is `<WORKTREE>`; it is already
> created and checked out on its branch, so skip Step 1.3's creation. Edit only under it, use
> absolute paths, start every shell command with `cd "<WORKTREE>" &&`, run everything through
> `uv run` and never pass the active-environment flag, never use a bare `git stash`, and inspect the
> main checkout only with `git -C`. Run Step 3's Planner or Plan-review brief and the Coder brief as nested
> subagents (`implement-planner`, `implement-worker`); Step 4's inline exception does not apply, so always run the Coder brief in `implement-worker`. Run Steps 2 to 5, then Step 6's commit and
> `git push -u origin <branch>` only. Do not run `doit pr` or Step 7: this run opens no PR and runs no
> CI loop. Finish with the Step 8 report, giving the branch name and pushed HEAD SHA in place of the PR
> URL and CI state. You cannot ask the user. When an ask-first trigger fires, stop and make your final
> message start with `ASK-FIRST: <trigger> — <detail>`.

An `ASK-FIRST:` return stops that issue only; the others continue. Relay it to the user and never
resolve it yourself. The user answers the orchestrator, which restarts that issue's agent with the
same prompt plus the answer. "Implement issue N" would open its PR outside the queue, so it is only
for taking an issue out of the run. The push runs no CI: CI starts with the PR.

When you relay a review finding to a running per-issue agent, relay the finding itself, not a
narrowed fix. The agent must still meet every requirement of the issue or return `ASK-FIRST:`.

### Step 4: Open PRs one at a time

Phase 2 starts when the first branch finishes phase 1, while other phase 1 agents may still run. The
next branch is the earliest finished one in the user's argument order. Two overlapping issues: the
later waits for the earlier to merge, and behind it if it is stopped; a non-overlapping branch may go
ahead of a stopped one. Only one PR from the run is open at a time.

You, the orchestrator, run phase 2 yourself, one branch at a time, with no agent for it. Every command
is `git -C <WORKTREE> …` or `cd "<WORKTREE>" && …` through `uv run`; the main checkout never moves.

1. `git fetch origin main`. If `git merge-base --is-ancestor origin/main HEAD` succeeds, skip the
   rebase, the re-check and the push.
2. Otherwise `git rebase origin/main`. Resolve a conflict only when the resolution keeps both sides'
   changes unaltered; any other conflict gets `git rebase --abort` and an ask-first stop to the user:
   `ASK-FIRST: rebase conflict — <files>`.
3. If the rebase brought changes, run `uv run doit check` and fix what it finds.
4. `git push --force-with-lease origin <branch>`, always naming the branch.
5. `uv run doit pr` from `<WORKTREE>`, with a body that follows the PR template and includes
   `Addresses #<n>`.
6. Run implement-issue Step 7's CI loop, at most 3 rounds. A failure that needs a real code change
   goes back to an `implement-worker` subagent for that worktree; you only resolve keep-both-sides
   conflicts and run commands.
7. Report the PR URL, the CI state, and whether `doit check` ran again. Never apply `ready-to-merge`,
   never merge.

A phase 2 stop holds the branches that overlap it; the others continue.

After a PR is reported, end the turn with the remaining queue and tell the user to merge through
[`merge-pr`](../merge-pr/SKILL.md). On the user's next message check `gh pr view <pr> --json state`:
`MERGED` starts the next branch; `OPEN` is reported and waits; `CLOSED` unmerged stops the queue and
asks the user.

In a new session, "implement issues A, B" again rebuilds the queue: Step 1 drops closed issues, Step 2
resumes worktrees, a clean pushed branch (`@{u}` equals HEAD) with no PR (`gh pr list --head <branch>`)
skips phase 1, and a branch with an open PR becomes the queue head.

### Step 5: Report

For each issue report the pushed branch and HEAD SHA, the PR URL and CI state of the current PR, the
queue still waiting, any deviation from the plan, and any stop (`ASK-FIRST:`, a branch with no
worktree, a closed issue). Also report the main checkout's branch and
`git -C <main-checkout> status --short`, taken before Step 2 and again here, so it is visible that
neither moved.

Merging is unchanged: the user merges each PR through [`merge-pr`](../merge-pr/SKILL.md). Rebasing
each branch before its PR is what keeps a file two issues both changed from conflicting at merge.

## Host support

Parallel mode is verified on Claude Code only (2.1.314): a background `general-purpose` subagent has
the Agent tool and starts `implement-planner` (Opus) and `implement-worker` nested, so the model
split from implement-issue holds. On Codex, Copilot and Antigravity, and on Claude when background
agents are unavailable, run phase 1 for each issue one after another in this session, then phase 2 in the session;
nested background agents were not verified there. See
[Cross-Agent Delegation Matrix — Parallel issues](../../../docs/development/ai/cross-agent-delegation.md#parallel-issues-implement-issues).
A headless Codex host (`codex exec -a never`) can read GitHub through `.codex/rules/gh.rules` but cannot write to it or delegate to another agent CLI — see [Headless Codex host limits](../../../docs/development/ai/cross-agent-delegation.md#headless-codex-host-limits).

## Ask-first triggers

Stop and ask the user when a phase 2 rebase conflict is not a union of both sides, or any
trigger from implement-issue fires (a new dependency, scope growth, a requirement that cannot be met
as written, an architecture choice, a breaking change, a failing test that would need changing, a blocked command).

## Never

- Never apply the `ready-to-merge` label, merge a PR, or close an issue.
- Never do phase 1 coding as the orchestrator, or `cd` to or switch the main checkout's branch.
- Never create worktrees concurrently, or run more agents than the cap.
- Never open a PR while the previous one from the run is unmerged.
- Never let a subagent open a PR.
- Never resolve an `ASK-FIRST:` stop on the user's behalf.
