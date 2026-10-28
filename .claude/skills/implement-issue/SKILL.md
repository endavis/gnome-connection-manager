---
name: implement-issue
description: Use when the user says "implement issue N" (or close variants — "work on issue N", "take issue N to a PR", "pick up #N"), or when the user approves working on an issue — including a "yes" to a fix you proposed and filed as an issue. Takes an open GitHub issue from its current state to an open PR in one run: decides whether to plan first, posts a plan comment when it does, implements the change with tests, validates it, commits, pushes, opens the PR, and fixes CI for up to 3 rounds. Never adds ready-to-merge, never merges, and never closes the issue.
---

# Implement Issue

Take an open GitHub issue to a PR whose only expected failing check is `require-label`.

"Implement issue N" — or the user approving work on an issue, including a "yes" to a fix the agent
proposed and filed as an issue — replaces the old three-command chain (`/claude:plan`,
`/claude:implement`, `/ghi-finalize`). Nothing here waits for plan approval or commit approval — the trade is explicit:
the agent commits and pushes on the issue's own branch, and the user's first checkpoint is reviewing
the open PR, not approving each step along the way.

## Instructions

### Step 1: Preconditions

1. Verify the issue is open:
   ```bash
   gh issue view <n> --json number,title,state,labels,body
   ```
   If it is closed, tell the user and stop.
2. Determine the branch type from labels (`enhancement`→`feat`, `bug`→`fix`, `refactor`→`refactor`,
   `documentation`→`docs`, `chore`→`chore`, default→`issue`).
3. Check the current branch:
   ```bash
   git branch --show-current
   ```
   - If already on `<type>/<n>-*`, resume on it — skip branch creation. If it carries uncommitted
     changes, treat them as prior work to continue, not to discard.
   - Otherwise create it from fresh `main`:
     ```bash
     git checkout main && git pull
     git checkout -b <type>/<n>-<short-description>
     ```

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

### Step 3: Plan (subagent)

Fetch the context the Planner brief reads, so the brief never has to call `gh` itself:

```bash
doit delegation_context --kind=issue --n=<n> --out=tmp/agents/<host>/implement-issue-<n>/
```

Run the **Planner brief** below in a subagent, using the host's subagent tool (see
[Per-host subagent notes](#per-host-subagent-notes)), telling it the context directory above. Post
what it returns with:

```bash
gh issue comment <n> --body "<plan>"
```

There is no approval wait — the plan is posted, not proposed.

### Step 4: Code (inline, subagent, or delegated)

Do the coding inline, without a subagent, when Step 2 skipped planning and the change is one of:

- a version bump of an existing dependency, such as a `pip-audit` fix: `pyproject.toml` and
  `uv.lock` only;
- a documentation-only change to one or two files, such as a typo, a broken link or a stale
  example;
- any other change to one or two files with no new module and no change in behavior.

Inline coding follows the Coder brief all the same: read the rules it lists, add tests when code
changes, and run `doit check`. A subagent saves no work on a change this small; it only adds the
handoff. Adding a new dependency is never small; it is an ask-first trigger. "Implement issue N
with \<agent\>" still delegates.

Otherwise, re-fetch the context into the same directory — Step 3 posted a comment since the last
fetch, so `comments.json` needs to pick it up (when Step 3 did not run, this is the first fetch):

```bash
doit delegation_context --kind=issue --n=<n> --out=tmp/agents/<host>/implement-issue-<n>/
```

Run the **Coder brief** below in a subagent, telling it the context directory above. When the user
says **"implement issue N with \<agent\>"**, run the Coder brief through that agent's CLI instead,
using the non-interactive invocation for that host documented in
[cross-agent-delegation.md — Non-interactive flags per CLI](../../../docs/development/ai/cross-agent-delegation.md#non-interactive-flags-per-cli)
— the delegated agent reads the context directory instead of calling `gh` itself, so the invocation
needs no `gh`-specific guidance. "With \<agent\>" hands off only this step; every other step still
runs in the host that received "implement issue N". Delete
`tmp/agents/<host>/implement-issue-<n>/` once this step returns; it has served its purpose (an inline
run that never fetched it has nothing to delete).

### Step 5: Check the work

- Diff the branch against the issue's success criteria; anything missing is a gap to close before
  committing, not a note for the PR description.
- Run `doit check` and `doit docs_build`, and fix whatever either one finds.
- Confirm ADR, nav (`mkdocs.yml`) and documentation updates landed if the plan called for them.

### Step 6: Commit and open the PR

Commit with `git commit` in the format from `.github/CONTRIBUTING.md` — not `doit commit`, which
asks interactive questions this run cannot answer. Then:

```bash
git push -u origin <type>/<n>-<short-description>
doit pr --title="<type>: <subject>" --body-file=<pr-body-file>
```

The PR body follows `.github/pull_request_template.md` and includes `Addresses #<n>`.

### Step 7: CI loop

1. Watch `gh pr checks` until every job finishes or the round cap is hit.
2. For each failing job other than `require-label`, fetch its log — `gh api
   repos/{owner}/{repo}/actions/jobs/<job-id>/logs` works while the run is still in progress — fix
   the cause, run the relevant local checks, commit, and push.
3. **At most 3 rounds.** After the third round, stop regardless of outcome and report every job
   still failing, each with a short excerpt from its log.

`require-label` is expected to stay red — it is the human merge gate, not something this skill fixes.

### Step 8: Stop and report

Report: the PR URL, a summary of the change, whether a plan was posted and why (or why not), whether
coding ran inline or in a subagent, any deviations from the plan, and the CI state (green, or the round-capped failures from Step 7).

## Ask-first triggers

Stop and ask the user, at any step, when one of these fires: a new dependency, scope growing beyond
the issue, an architecture choice, a breaking change the issue did not already describe, a failing test
that would need changing to pass, or a blocked command (see `AGENTS.md` — When Blocked Protocol). Do
not resolve any of these unilaterally and keep going.

This skill **never** adds the `ready-to-merge` label, never merges a PR, and never closes the issue
it is implementing. Those stay the user's decisions.

## Planner brief

Give this to the planning subagent, with the issue number:

1. Read `AGENTS.md` and `.claude/CLAUDE.md` (or the host's equivalent) for workflow, conventions, and
   the mandatory test requirement.
2. Read the issue from `<context-dir>/issue.json` (title/body/labels/assignees) — the caller fetched
   it with `doit delegation_context --kind=issue --n=<n> --out=<context-dir>` before invoking this
   brief, so there is no `gh` call to make here. If `<context-dir>/issue.json` is missing or
   unreadable, print `DELEGATION-ERROR:` and stop. Check `needs-adr` and any related ADRs in
   `docs/decisions/`.
3. Explore the codebase for the files, modules, and tests the change touches, and the existing
   patterns in that area. If more than one approach is reasonable, pick one and say why in the plan
   rather than leaving it open — nothing downstream can ask the user.
4. Return the plan in this exact shape, so the header is machine-findable and the next step can read
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

## Coder brief

Give this to the coding subagent (or the delegated agent's CLI), with the issue number, the branch
name, and any issue-specific notes:

1. Read `AGENTS.md` and the host's agent-specific instructions file for workflow, conventions, code
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
4. Run `doit check`. Fix failures and re-run; do not stop at the first failure.
5. Return a summary: files created or modified, test results, and any deviations from the plan.
6. Never switch branches, never commit, never enter plan mode. The parent step handles validation
   doubling, commit, and PR.

## Per-host subagent notes

Each host uses its own subagent mechanism for the Planner and Coder briefs. When a host has none,
run the brief in the session itself instead of failing the step.

- **Claude Code:** the Agent tool with a general-purpose subagent for the Planner brief, and the
  `implement-worker` subagent (`.claude/agents/implement-worker.md`) for the Coder brief. Verified
  with `claude -p --permission-mode plan "<prompt asking which skill handles 'implement issue N'>"`,
  which named `implement-issue`.
- **Codex CLI:** `multi_agent`. `codex features list` reports `multi_agent` as `stable`/`true`
  (`multi_agent_v2` exists but is `stable`/`false` — not enabled). `codex debug prompt-input` lists
  `implement-issue` (source `.agents/skills/implement-issue/SKILL.md`) among the skills available to
  the session. A headless Codex host (`codex exec -a never`) can read GitHub through `.codex/rules/gh.rules` but cannot write to it or delegate to another agent CLI — see [Headless Codex host limits](../../../docs/development/ai/cross-agent-delegation.md#headless-codex-host-limits). It cannot run Step 4's "with \<agent\>" delegation, Step 6's `doit pr`, or Step 7's CI-log fetch headless; Codex hosts this skill interactively instead.
- **GitHub Copilot CLI:** `--fleet` ("run the prompt in fleet mode (parallel subagent...)", per
  `copilot --help`) for parallel subagent work; the `task` tool for the Coder brief, the same
  mechanism `.claude/agents/implement-worker.md` already documents being read through for Copilot.
  `copilot skill list | grep implement-issue` finds the skill.
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
- `.claude/agents/implement-worker.md` — Claude's Coder-brief subagent definition.
