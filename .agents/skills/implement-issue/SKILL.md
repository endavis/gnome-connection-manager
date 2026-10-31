---
name: implement-issue
description: Use when the user says "implement issue N" (or close variants — "work on issue N", "take issue N to a PR", "pick up #N"), or when the user approves working on an issue — including a "yes" to a fix you proposed and filed as an issue. Takes an open GitHub issue from its current state to an open PR in one run: decides whether to plan first, posts a plan comment when it does, implements the change with tests, validates it, commits, pushes, opens the PR, and fixes CI for up to 3 rounds. Never adds ready-to-merge, never merges, and never closes the issue. For several issues in one request, use `implement-issues`.
---

# Implement Issue

Take an open GitHub issue to a PR whose only expected failing check is `require-label`.

"Implement issue N" — or the user approving work on an issue, including a "yes" to a fix the agent
proposed and filed as an issue — replaces the old three-command chain (`/claude:plan`,
`/claude:implement`, `/ghi-finalize`). Nothing here waits for plan approval or commit approval — the trade is explicit:
the agent commits and pushes on the issue's own branch, and the user's first checkpoint is reviewing
the open PR, not approving each step along the way.

See also: [`implement-issues`](../implement-issues/SKILL.md) runs this skill for several issues in parallel, one worktree and one background agent each.

## Instructions

### Step 1: Preconditions

1. Verify the issue is open:
   ```bash
   gh issue view <n> --json number,title,state,labels,body
   ```
   If it is closed, tell the user and stop.
2. Determine the branch type from labels (`enhancement`→`feat`, `bug`→`fix`, `refactor`→`refactor`,
   `documentation`→`docs`, `chore`→`chore`, default→`issue`).
3. Find or create the issue's worktree. Every run works in a worktree under `worktrees/`, so two
   sessions can run two issues at once and the main checkout is never switched or pulled. Check, in
   order:
   ```bash
   git branch --show-current
   git worktree list --porcelain
   git branch --list '<type>/<n>-*'
   ```
   - If already on `<type>/<n>-*`, resume on it — skip branch creation. This holds in the main
     checkout and in a worktree. If it carries uncommitted changes, treat them as prior work to
     continue, not to discard.
   - If `git worktree list --porcelain` shows a worktree on `<type>/<n>-*`, `cd` into it and resume
     there. Uncommitted changes in it count as prior work too.
   - If a local branch `<type>/<n>-*` exists with no worktree, stop and ask the user. `doit
     worktree` uses `git worktree add -b`, which fails on an existing branch.
   - Otherwise create the worktree from the main checkout. `doit worktree` fetches `origin/main`
     itself and branches from it with no upstream, so there is no `git pull` here:
     ```bash
     uv run doit worktree --branch=<type>/<n>-<short-description>
     cd <main-checkout>/worktrees/<type>/<n>-<short-description>
     ```
4. Record the worktree's absolute path as `WORKTREE` (`git rev-parse --show-toplevel` from inside
   it). Every later step runs from `$WORKTREE` through `uv run`; never pass `--active`, which would
   install the worktree into the main checkout's `.venv`. Treat the shell's working directory as
   non-persistent on every host: start each shell command with `cd "$WORKTREE" &&`, or use absolute
   paths. See [Per-host subagent notes](#per-host-subagent-notes).
5. Never `cd` to the main checkout during a run: that moves the session out of its worktree. To
   inspect it, use `git -C <main-checkout> …`.

### Step 2: Decide whether to plan

Plan first when any of these hold:

- the issue carries the `needs-adr` label;
- it is a feature or refactor touching more than about 3 files, or adding a new module;
- more than one approach is reasonable and the choice matters.

Otherwise skip straight to Step 4 — the issue body is the spec.

If a comment already exists whose body has a heading line starting with `Implementation Plan for`,
reuse the most recent one instead of planning again:

```bash
gh api repos/{owner}/{repo}/issues/<n>/comments --jq '.[] | select(.body | test("^#+ Implementation Plan for"; "m")) | .body'
```

### Step 3: Plan (host or subagent)

Fetch the context the Planner brief reads, so the brief never has to call `gh` itself:

```bash
uv run doit delegation_context --kind=issue --n=<n> --out=$WORKTREE/tmp/agents/<host>/implement-issue-<n>/
```

**The host writes the plan itself only when** during this run it posted a findings comment on the
issue (or posts one together with the plan) and the plan cites that comment. "The change seems
clear" does not qualify. The plan uses the Planner brief's exact shape. Before posting it, run the
**Plan-review brief** below on the draft, in a subagent or through another agent CLI with the same
non-interactive invocation as "with \<agent\>"; fix or reject each point it raises. The review
reads only the draft, the findings and the files the plan names.

**Roles.** Who runs the Planner brief (`plan`), the Plan-review brief (`plan_review`) and the Coder
brief (`code`) comes from the person's agent-role config. Before each, run
`uv run doit agent_cmd --role=<role> --host=<host>` and read the last stdout line (JSON). If `mode`
is `subagent`, run the brief in the host's subagent with that `model` (and `effort`, Codex only) when
given (none means the subagent's own default). On Codex spawn it with `fork_turns: "none"` plus
`model` and `reasoning_effort`; the briefs are self-contained through the context directory, so no
parent history is needed, and a full-history fork ignores both. If `inline`, run it in the session. If `cli`, run its `command` with
`'<prompt>'` replaced by the brief's prompt, from `$WORKTREE`. With no config the result is today's
behaviour, and a task failure also falls back to it. See
[Agent roles](../../../docs/development/ai/agent-roles.md).

In every other case run the **Planner brief** below in a subagent, using the host's subagent tool (see
[Per-host subagent notes](#per-host-subagent-notes)), telling it the context directory above (an absolute path inside the worktree) and the worktree root
`$WORKTREE`. If you hold findings, pass them in its prompt, marked as findings. Post
what it returns (or the reviewed host plan) with:

```bash
gh issue comment <n> --body "<plan>"
```

There is no approval wait — the plan is posted, not proposed.

### Step 4: Code (inline, subagent, or delegated)

Do the coding inline, without a subagent, only when ALL of these hold: Step 2 skipped planning, the
change does not alter behavior, and it is one of:

- a version bump of an existing dependency, such as a `pip-audit` fix: `pyproject.toml` and
  `uv.lock` only;
- a documentation-only change, such as a typo, a broken link or a stale example;
- a behavior-preserving edit, such as a rename.

Behavior-changing work goes to the Coder brief in `implement-worker`, however few files it touches:
every bug fix with a regression test, and every code path change. File count alone never qualifies
for inline coding. When the caller's prompt, such as an `implement-issues` per-issue agent's, says
to run the Coder brief as a nested subagent, that overrides this list.

Inline coding follows the Coder brief all the same: read the rules it lists, add tests when code
changes, and run the touched tests plus `uv run doit lint` and `uv run doit type_check`. `doit check`
runs once, in Step 5. A subagent saves no work on a change this small; it only adds the
handoff. Adding a new dependency is never small; it is an ask-first trigger. "Implement issue N
with \<agent\>" still delegates.

Otherwise, re-fetch the context into the same directory — Step 3 posted a comment since the last
fetch, so `comments.json` needs to pick it up (when Step 3 did not run, this is the first fetch):

```bash
uv run doit delegation_context --kind=issue --n=<n> --out=$WORKTREE/tmp/agents/<host>/implement-issue-<n>/
```

Resolve the `code` role first (see **Roles** in Step 3), then run the **Coder brief** below in a subagent, telling it the context directory above and the worktree
root `$WORKTREE`. When the user
says **"implement issue N with \<agent\>"**, run the Coder brief through that agent's CLI instead,
using the non-interactive invocation for that host documented in
[cross-agent-delegation.md — Non-interactive flags per CLI](../../../docs/development/ai/cross-agent-delegation.md#non-interactive-flags-per-cli)
— the delegated agent reads the context directory instead of calling `gh` itself, so the invocation
needs no `gh`-specific guidance. Run that CLI from `$WORKTREE`. "With \<agent\>" hands off only this step; every other step still
runs in the host that received "implement issue N". Delete
`$WORKTREE/tmp/agents/<host>/implement-issue-<n>/` once this step returns; it has served its purpose (an inline
run that never fetched it has nothing to delete).

### Step 5: Check the work

- Build a requirements list before committing: the issue's Success Criteria; for a bug, its Expected
  behavior plus every concrete fix item named anywhere in the body (for example Additional Context).
  Diff the branch against it and mark each requirement met or unmet. Close an unmet one before
  committing. An unmet requirement, including one deliberately dropped, is an ask-first trigger,
  never a note in the PR body.
- Run `uv run doit check` and `uv run doit docs_build` from `$WORKTREE`, and fix whatever either one finds.
  This is the run's single full `doit check`, run once: the Coder does not run it, and the host does
  not rely on a subagent's "check passed" claim (`.claude/rules/verified-claims.md`).
- Confirm ADR, nav (`mkdocs.yml`) and documentation updates landed if the plan called for them.

### Step 6: Commit and open the PR

From `$WORKTREE`, commit with `git commit` in the format from `.github/CONTRIBUTING.md` — not `doit commit`, which
asks interactive questions this run cannot answer. Then:

```bash
git push -u origin <type>/<n>-<short-description>
uv run doit pr --title="<type>: <subject>" --body-file=<pr-body-file>
```

The PR body follows `.github/pull_request_template.md` and includes `Addresses #<n>`.

When the caller's prompt, such as an `implement-issues` per-issue agent's, says to stop after the
push, skip `doit pr` and Step 7 and report the pushed branch.

### Step 7: CI loop

1. Watch `gh pr checks` until every job finishes or the round cap is hit.
2. For each failing job other than `require-label`, fetch its log — `gh api
   repos/{owner}/{repo}/actions/jobs/<job-id>/logs` works while the run is still in progress — fix
   the cause, run the relevant local checks, commit, and push.
3. **At most 3 rounds.** After the third round, stop regardless of outcome and report every job
   still failing, each with a short excerpt from its log.

`require-label` is expected to stay red — it is the human merge gate, not something this skill fixes.

### Step 8: Stop and report

Report: the PR URL, a summary of the change, whether a plan was posted and why (or why not), who wrote
it (host or Planner), how many times `doit check` ran this run, whether
coding ran inline or in a subagent, a requirement-by-requirement met/unmet table (from Step 5's
requirements list), any deviations from the plan, and the CI state (green, or the round-capped failures from Step 7).
Also report the worktree path (`$WORKTREE`) and the merge command, which the user runs from the main
checkout: `uv run doit pr_merge --pr=<pr> --auto-close`. It removes the worktree and its branch.

## Ask-first triggers

Stop and ask the user, at any step, when one of these fires: a new dependency, scope growing beyond
the issue, a requirement of the issue that cannot be met as written (unsafe, contradicted by a review
finding, or needing a different design), an architecture choice, a breaking change the issue did not
already describe, a failing test that would need changing to pass, or a blocked command (see `AGENTS.md` — When Blocked Protocol). Narrowing
the scope is a trigger just as growing it is. Do not resolve any of these unilaterally and keep going.

This skill **never** adds the `ready-to-merge` label, never merges a PR, and never closes the issue
it is implementing. Those stay the user's decisions.

## Planner brief

Give this to the planning subagent, with the issue number and the worktree root as an absolute
path:

1. Work only under the worktree root you were given. A subagent's working directory resets between
   shell calls and its file tools default to the session's primary directory, so use absolute paths
   under the worktree root and start each shell command with `cd <root> &&`. Read `AGENTS.md` and
   `.claude/CLAUDE.md` (or the host's equivalent) for workflow, conventions, and
   the mandatory test requirement.
2. Read the issue from `<context-dir>/issue.json` (title/body/labels/assignees) — the caller fetched
   it with `doit delegation_context --kind=issue --n=<n> --out=<context-dir>` before invoking this
   brief, so there is no `gh` call to make here. If `<context-dir>/issue.json` is missing or
   unreadable, print `DELEGATION-ERROR:` and stop. Check `needs-adr` and any related ADRs in
   `docs/decisions/`.
3. Explore the codebase for the files, modules, and tests the change touches, and the existing
   patterns in that area. If more than one approach is reasonable, pick one and say why in the plan
   rather than leaving it open — nothing downstream can ask the user.
4. Findings the caller passes are settled: do not re-measure or re-probe them, and flag in the
   Overview any the code contradicts. Explore and probe only what they do not cover. Without
   findings, step 3 applies as written.
5. Return the plan in this exact shape, so the header is machine-findable and the next step can read
   every section:

   ```
   ## Implementation Plan for #<n>: <title>

   ### Overview
   What will be done and why.

   ### Files to Create/Modify
   - [ ] `path/to/file.py` — what changes
   - [ ] `tests/test_file.py` — what it covers

   ### Test Plan
   - [ ] Test case 1
   - [ ] Test case 2

   ### Documentation
   - [ ] Docs that need updating
   - [ ] ADR needed: yes/no (why)

   ### Validation
   - [ ] `doit check` passes
   ```

## Plan-review brief

Give this to the reviewing subagent (or another agent's CLI) when the host wrote the plan, with the
worktree root as an absolute path and the context directory:

1. Work only under the worktree root. Use absolute paths and start each shell command with
   `cd <root> &&`.
2. Read the draft plan and the findings from the file under `<context-dir>` the caller names. Read
   only the files the plan names. Do not explore the codebase, do not probe, and make no `gh` call.
3. Return a critique of design errors, missed edge cases and conflicts with project rules, or
   `NO ISSUES`. Do not edit files and do not post anything.

## Coder brief

Give this to the coding subagent (or the delegated agent's CLI), with the issue number, the branch
name, the worktree root as an absolute path, and any issue-specific notes:

1. Edit only under the worktree root. A subagent's working directory resets between shell calls and
   its file tools default to the session's primary directory, so use absolute paths under the
   worktree root and start every shell command with `cd <root> &&`. Read `AGENTS.md` and the host's agent-specific instructions file for workflow, conventions, code
   style, and the mandatory test requirement.
2. Read `<context-dir>/comments.json` for the most recent comment matching `Implementation Plan
   for` — the caller fetched it with `doit delegation_context --kind=issue --n=<n>
   --out=<context-dir>` before invoking this brief, re-fetched after the Planner brief posted its
   plan so the comment is already there. If there is none, read `<context-dir>/issue.json` for the
   issue body and use that as the spec instead. If `<context-dir>/comments.json` is missing or
   unreadable, print `DELEGATION-ERROR:` and stop.
3. Implement the plan (or the issue): create and edit files, follow existing patterns, and write
   tests — this is mandatory whenever there is code to test, with no exceptions for "small" changes.
   All new code is type-annotated for mypy strict mode.
4. Checking budget, run from the worktree root through `uv run`: the tests covering the change; one
   revert check (undo the fix, confirm the new tests fail, restore — using `git show HEAD:<path>`
   or a WIP commit); only what project rules require, such as the `mutation-triage` and
   `property-tests` skills when they apply; `uv run doit lint`; `uv run doit type_check`. Run
   nothing beyond that unless the plan asks: no extra mutmut runs, no flakiness reruns. Do not run
   `uv run doit check`; the full `doit check` runs once, in Step 5. Fix failures.
5. Return a summary: files created or modified, test results, every check command you ran, and any
   deviations from the plan.
6. Never use a bare `git stash`: the stash stack is shared with the main checkout, every worktree
   and every session, so a `pop` can take another session's entry. To compare against unchanged
   code, write `git show HEAD:<path>` to a scratch file under the worktree's `tmp/`, or make a
   temporary WIP commit.
7. Never switch branches, never commit, never enter plan mode. The parent step handles the full `doit check`
   (Step 5), commit, and PR.

## Per-host subagent notes

Directory change: the skill assumes no host keeps the working directory between shell calls, so
every command is `cd "$WORKTREE" && …` or uses absolute paths, which is correct either way. Claude
Code's main-session `cd` persists inside the repo (verified). Copilot (`-C`/`--add-dir`), Codex
(not installed here) and `agy` (`--add-dir`) are unverified; start a delegated run from `$WORKTREE`.

Each host uses its own subagent mechanism for the Planner and Coder briefs. When a host has none,
run the brief in the session itself instead of failing the step.

- **Claude Code:** the Agent tool with the `implement-planner` subagent
  (`.claude/agents/implement-planner.md`, `model: opus`) for the Planner brief and the Plan-review brief, and the
  `implement-worker` subagent (`.claude/agents/implement-worker.md`, no `model:` because Copilot shares the file; it gets Sonnet
  from `CLAUDE_CODE_SUBAGENT_MODEL`) for the Coder brief. Verified
  with `claude -p --permission-mode plan "<prompt asking which skill handles 'implement issue N'>"`,
  which named `implement-issue`.
- **Codex CLI:** `multi_agent`. `spawn_agent` accepts `model` and `reasoning_effort` when spawned with `fork_turns: "none"` (verified live in 0.166.0, #1151: the child ran the chosen model and effort while the parent kept its own); a full-history fork inherits the parent's and accepts no override. So a configured Codex model or effort on a Codex host resolves to `subagent`. `codex features list` reports `multi_agent` as `stable`/`true`
  (`multi_agent_v2` exists but is `stable`/`false` — not enabled). `codex debug prompt-input` lists
  `implement-issue` (source `.agents/skills/implement-issue/SKILL.md`) among the skills available to
  the session. A headless Codex host (`codex exec -a never`) can read GitHub through `.codex/rules/gh.rules` but cannot write to it or delegate to another agent CLI — see [Headless Codex host limits](../../../docs/development/ai/cross-agent-delegation.md#headless-codex-host-limits). It cannot run Step 4's "with \<agent\>" delegation, Step 6's `doit pr`, or Step 7's CI-log fetch headless; Codex hosts this skill interactively instead.
- **GitHub Copilot CLI:** `--fleet` ("run the prompt in fleet mode (parallel subagent...)", per
  `copilot --help`) for parallel subagent work; the `task` tool for the Coder brief, the same
  mechanism `.claude/agents/implement-worker.md` already documents being read through for Copilot.
  `copilot skill list | grep implement-issue` finds the skill. The `task` tool has a `model` parameter, but in
  1.0.105 its schema allowed only `auto`, and a model outside it ran on another model (#1151), so a
  configured model resolves to `cli` mode. Per-agent models are Copilot's own `/subagents` setting.
  A delegated Copilot run must set `GITHUB_COPILOT_PROMPT_MODE_REPO_HOOKS=true`, as the
  documented invocation does, or its dangerous-command hook does not load under `-p` (#1042).
- **Antigravity CLI (`agy`):** no dedicated subagent/delegation flag found — `agy --help` lists no
  subagent-style option, and `agy agent` (the "list available agents" subcommand) returns no
  output for this workspace. Run both briefs in the session itself. `agy --sandbox --add-dir "$PWD"
  -p "<list skills starting with 'implement'>"` named `implement-issue`.

## See also

- [Cross-Agent Delegation Matrix](../../../docs/development/ai/cross-agent-delegation.md) — the
  workflow contract this skill's literals satisfy, the non-interactive invocation per host, and the
  `doit delegation_context` context-file convention Steps 3–4 use.
- [Slash Commands and Workflows](../../../docs/development/ai/slash-commands.md) — command reference.
- `.claude/agents/implement-planner.md` — Claude's Planner-brief subagent definition.
- `.claude/agents/implement-worker.md` — Claude's Coder-brief subagent definition.
