---
title: Cross-Agent Delegation Matrix
description: Commands that let any supported AI CLI hand a review task to any other; plan and implement are handled by the shared implement-issue skill instead
audience:
  - contributors
  - ai-agents
tags:
  - ai
  - workflow
---

# Cross-Agent Delegation Matrix

A consistent, explicit-invocation interface that lets any of the four supported AI CLIs (Claude Code, Codex CLI, Copilot CLI, Antigravity CLI) hand a task — `review` or `adversarial-review` — to any of the others.

> **Antigravity CLI (`agy`) is wired into the matrix as a full agent** (both source and target). Its self-action skills (`antigravity-*`) live in `.agents/skills/`, and its outbound bridges **reuse Codex's host-agnostic `delegate-*` skills** in that same directory (both CLIs read it). Inbound bridges to `agy` live in each host's own directory. The `/multi-*` orchestrators also accept `antigravity` as an agent. See [Matrix](#matrix) for the cell and file counts — it is the only place they are written down.

> **`plan` and `implement` are no longer part of this matrix.** #976 replaced the per-agent
> plan/implement files with one shared `implement-issue` skill
> (`.agents/skills/implement-issue/SKILL.md`, generated for Claude by `doit skills_sync`) that takes
> an issue to an open PR in a single run — deciding whether to plan, posting the plan without an
> approval wait, implementing with tests, validating, committing, pushing, opening the PR, and
> fixing CI for up to 3 rounds. "Implement issue N with \<agent\>" hands only the coding step to
> that agent; see [Workflow contract](#workflow-contract) below and
> [`implement-issue`](slash-commands.md#implement-issue-n) in the command reference.

## Why this exists

Each agent already drives *itself* through the issue-driven workflow (`implement issue N`, `/<ai>:review`). This matrix adds the missing piece: deliberate, user-invoked handoff *between* agents, without depending on third-party plugins like `openai/codex-plugin-cc` or community forks.

The matrix replaces what would otherwise be a patchwork of inconsistent third-party plugins. It runs on top of the CLIs' existing non-interactive modes (`-p` / `exec`) and uses the same command names across all hosts, so users learn the surface once.

## Convention

`<prefix><target><separator><action>` where:

- **Prefix:** `/` on Claude Code and Copilot CLI; `$` on Codex CLI (Codex's repo-defined commands are skills, not slash commands; OpenAI deprecated `~/.codex/prompts/`).
- **Separator:** `:` (colon) on Claude Code — it reads a `commands/<scope>/<name>` directory layout that supports colon-namespaced slash commands. `-` (hyphen) on Copilot CLI and Codex CLI — these are skill-based and skill names are derived from directory names, which cannot contain colons.
- **Target:** `claude`, `codex`, `copilot`, `antigravity` — the agent to invoke. Can be the **same** agent (self-action) or one of the other three (cross-agent delegation). Antigravity (`agy`) has no slash/`$` prefix — it activates skills by matching the `description:` frontmatter.
- **Action:** `review`, `adversarial-review`.

Self-action and cross-agent delegation share the same naming convention within each host. For self-action the command body runs the work natively in the host agent; for cross-agent delegation it shells out to the target CLI.

**Surface mapping per host:**

| Host | Self-action | Cross-agent delegation | File layout |
| :--- | :--- | :--- | :--- |
| Claude Code | `/claude:<action>` | `/<target>:<action>` | `.claude/commands/<target>/<action>.md` |
| Copilot CLI | `/copilot-<action>` | `/<target>-<action>` | `.github/skills/<target>-<action>/SKILL.md` |
| Codex CLI | `$codex-<action>` | `$delegate-<target>-<action>` | `.agents/skills/<dir>/SKILL.md` |
| Antigravity CLI | `antigravity-<action>` (by description) | `delegate-<target>-<action>` (by description) | `.agents/skills/<dir>/SKILL.md` (shared with Codex) |

| Action | Argument | Notes |
| :--- | :--- | :--- |
| `review` | optional focus area | Reviews current PR or branch-vs-main changes. |
| `adversarial-review` | optional focus | Steerable challenge review — pressure-tests design, hidden assumptions, alternatives, failure modes. |

`plan` and `implement` are not matrix actions. "Implement issue N" runs the single shared
`implement-issue` skill in whichever host received the request; "implement issue N with \<agent\>"
hands only the coding step to \<agent\>, using that host's non-interactive invocation (see
[Non-interactive flags per CLI](#non-interactive-flags-per-cli)).

## Workflow contract

The naming convention above says where the files live. This says what they must **say**.

Because a user can switch agents mid-review — review with Codex, challenge with Copilot — the
review files carry a literal string that lets the user trust the constraint regardless of which
host is driving. `implement-issue` is a single shared file rather than a per-agent one, so its
contract is checked directly against that one source instead of once per agent.

| Element | Literal | Required in | Why it is load-bearing |
| :--- | :--- | :--- | :--- |
| Plan-comment header | `Implementation Plan for` | `implement-issue` | How a reused plan comment is found on the issue |
| Branch-name pattern | `<type>/` | `implement-issue` | `doit pr` derives the issue number from the branch name |
| Validation commands | `doit check`, `doit docs_build` | `implement-issue` | The gates the workflow promises before committing |
| PR command | `doit pr` | `implement-issue` | Opens the PR; `implement-issue` never leaves it uncommitted |
| Issue reference | `Addresses #` | `implement-issue` | Links the PR to its issue; `doit pr_merge --auto-close` depends on it |
| Merge-gate check | `require-label` | `implement-issue` | The only check the CI-fix loop does not try to fix |
| Read-only constraint | the sentence below | every `review` and `adversarial-review` file | A review that edits code is not a review |

`implement-issue` never applies the `ready-to-merge` label, never merges a PR, and never closes the
issue it implements — those stay the user's decisions (ADR-9006's merge gate is unchanged).

The read-only constraint must appear **verbatim** on every surface, because a
constraint paraphrased per host drifts into a weaker version on one of them, and
whichever agent is driving decides which version applies:

> **Read-only.** Review and report — do not edit files, commit, or push. Findings go to
> the user and the PR; any fix is a separate change the user asks for.

### Declared exemptions

Uniform prose is not the goal — agreement on the contract is. There are none currently declared:
`implement-issue` is one shared file, so there is nothing for a host to diverge from, and the
review contract has no per-host exception either. Where a host genuinely differs in the future, the
difference belongs here, declared rather than papered over, mirrored in
`tests/test_cross_agent_contract.py`'s `EXEMPTIONS` table.

### Enforcement

`tests/test_cross_agent_contract.py` asserts every element above, and its `EXEMPTIONS`
table mirrors the one here. **This document is the specification**; when the two
disagree, the test is the bug. Adding an exemption to the test without adding a row here
is how a contract quietly becomes a suggestion.

The checks are scoped to the agents a project actually wires (see
`tests/agent_roster.py`), so a project that keeps one agent is held to the contract for
that agent only.

## Matrix

The 4 sources × 4 targets × 2 actions = 32 cells (including self-action). Cross-agent delegation is 4 × 3 × 2 = 24 cells, across **20 distinct files** — Codex and Antigravity share the host-agnostic `.agents/skills/delegate-*` files, so the 4 `antigravity → {claude, copilot}` cells reuse Codex's files.

| Source ↓ / Target → | claude | codex | copilot | antigravity |
| :--- | :--- | :--- | :--- | :--- |
| **claude** (`.claude/commands/`) | `/claude:{review,adversarial-review}` | `/codex:{...}` | `/copilot:{...}` | `/antigravity:{...}` |
| **codex** (`.agents/skills/`) | `$delegate-claude-{...}` | `$codex-{review,adversarial-review}` | `$delegate-copilot-{...}` | `$delegate-antigravity-{...}` |
| **copilot** (`.github/skills/`) | `/claude-{...}` | `/codex-{...}` | `/copilot-{review,adversarial-review}` | `/antigravity-{...}` |
| **antigravity** (`.agents/skills/`) | `delegate-claude-{...}` | `delegate-codex-{...}` | `delegate-copilot-{...}` | `antigravity-{review,adversarial-review}` |

Each cell expands to `{review, adversarial-review}`. The diagonal (self-action) cells run natively in the host agent rather than shelling out. **Naming asymmetry:** Claude uses `<target>:<action>` (colon); Copilot and Codex use `<target>-<action>` (hyphen) because their command surface is skills, and skill names — being directory names — cannot contain colons. Antigravity is also skill-based and has **no prefix at all** — it activates the matching skill by its `description:`. The functional behavior is identical across hosts; only the invocation surface differs.

## Non-interactive flags per CLI

Each bridge invokes the target CLI in headless mode. Each CLI requires a flag to skip the interactive approval prompts that would otherwise block tool calls when no human is at the terminal:

| Target | Invocation | Why |
| :--- | :--- | :--- |
| Claude Code | `claude -p '<prompt>'` | `-p` runs headless. No additional approval-bypass flag needed for the typical tool surface. |
| Codex CLI | `codex -a never --dangerously-bypass-hook-trust exec '<prompt>' < /dev/null` | `-a never` (`--ask-for-approval never`) prevents Codex from asking the (absent) user before running shell commands. Without it, every tool call in the delegated session is denied. The trailing `< /dev/null` stops `codex exec` waiting forever on stdin when the caller's stdin is a pipe or socket (#980). The prompt no longer needs `gh`-chaining guidance (`GH_STANDALONE_SENTENCE`, pre-#985): the host now pre-fetches any GitHub data the delegated prompt needs with `doit delegation_context` and writes it to files under `tmp/agents/<host>/<task>-<n>/`, so `<prompt>` reads those instead of calling `gh` itself — see [Context-file convention](#context-file-convention) below. |
| Copilot CLI | `copilot --allow-all -p '<prompt>'` | `--allow-all` enables all permissions (equivalent to `--allow-all-tools --allow-all-paths --allow-all-urls`). Without it, Copilot prompts for path or URL access mid-session, which the absent user can't answer. **Order matters:** `--allow-all` must precede `-p`, since `-p <text>` consumes its argument and would otherwise grab the next flag. |
| Antigravity CLI | `agy -p '<prompt>' --dangerously-skip-permissions --add-dir "$(git rev-parse --show-toplevel)"` | `-p` runs headless; `--dangerously-skip-permissions` auto-approves tool calls the absent user can't confirm. `--add-dir <repo-root>` is **required** so `agy` treats the repo as an active workspace and loads `.agents/` (skills + the shared dangerous-command hook) — a headless `agy -p` otherwise falls back to its own home workspace and ignores the repo's `.agents/`. The safety hook's stdout `{"decision":"deny"}` still hard-blocks dangerous commands even under `--dangerously-skip-permissions`. |

These flags are intentional: in delegated invocations, the human is at the *source* agent and not at the target's prompt. Approval prompts in the target session can never be answered, so they must be bypassed. The source agent retains full visibility through captured stdout and can stop the chain at any point.

### Context-file convention

Before #985, every non-interactive invocation handed to Codex opened with a literal sentence
(`GH_STANDALONE_SENTENCE`) telling it to run every `gh` command standalone, never chained — because
`.codex/rules/gh.rules` only allow-rules a standalone `gh` prefix, and a `gh` chained into another
command falls back into the sandbox, which has no network at all (#980). That sentence is gone now:
instead of asking each delegated agent (Codex or otherwise) to fetch its own GitHub data, the
**host** — the CLI that received the user's command, which already has a trusted, un-sandboxed
`gh` — fetches it first, with the `doit delegation_context` task:

```bash
doit delegation_context --kind=issue --n=<n> --out=tmp/agents/<host>/<task>-<n>/
doit delegation_context --kind=pr --n=<n> --out=tmp/agents/<host>/<task>-<n>/
```

`--kind=issue` writes `issue.json` (number/title/body/labels/assignees) and `comments.json`
(`{"comments": [...]}}`); `--kind=pr` writes `pr.json`
(number/title/body/baseRefName/headRefName) and `diff.txt` (the PR's diff). A missing or
inaccessible issue/PR aborts the task with a clear error — never a silent empty file. See
[`doit-tasks-reference.md` — `delegation_context`](../doit-tasks-reference.md#delegation_context)
for the full reference.

By convention the output directory is `tmp/agents/<host>/<task>-<n>/` (for example
`tmp/agents/claude/multi-review-123/`), per `AGENTS.md`'s temp-file convention. The delegated
prompt is told to read the files in that directory instead of calling `gh`, and to print
`DELEGATION-ERROR:` and stop if the directory or a file in it is missing or unreadable — the
`DELEGATION_ERROR_CHECK` half of the contract (below) is unchanged, only what triggers the marker
is: a missing context file, not a failed `gh` call. The orchestrating skill that created the
directory deletes it once every delegated agent (or subagent) using it has returned.

This removes `gh` from every delegated prompt this template ships: `implement-issue`'s Planner and
Coder briefs, `multi-plan`'s and `multi-review`'s per-agent delegated prompt, and the six Codex
bridge files, which now give Codex only git-based inline steps (`.agents/skills/delegate-codex-
{review,adversarial-review}/SKILL.md`, `.github/skills/codex-{review,adversarial-review}/SKILL.md`,
`.claude/commands/codex/{review,adversarial-review}.md`) — Hybrid C's old "activate
`$codex-review`/`$codex-adversarial-review` if available" fallback, which could still reach `gh pr
view`/`gh pr diff` from inside the delegated session, is gone along with it. `tests/test_cross_
agent_contract.py`'s `GH_COMMAND_PATTERN` asserts none of these delegated prompts invokes `gh`.

`.codex/rules/gh.rules` is **unchanged** by this — it still serves a headless Codex *host*'s own
reads (its own `gh issue view`/`gh pr view` in Step 1 of `multi-review`/`multi-plan`, and the
Planner brief when Codex itself is the host, run directly in the host's own session, not delegated)
— see [Headless Codex host limits](#headless-codex-host-limits) below and [Command Blocking — Codex
CLI](command-blocking.md#codex-cli) for the measured sandbox-network facts (#980).

## Headless Codex host limits

A headless Codex host (`codex -a never exec`) can run the read side of `multi-*` and
`implement-issue` but not the write side, and it cannot delegate to another agent CLI at all. Both
limits trace to the same sandbox: a command or CLI Codex has not allow-ruled runs with no network
and, for a nested CLI, a read-only home directory.

**Write steps.** `.codex/rules/gh.rules` allows only `gh pr {view,diff,checks,list}` and `gh issue
{view,list}` — see [Command Blocking — Codex CLI](command-blocking.md#codex-cli). Everything else
these workflows need — `gh pr comment` / `gh issue comment` (the `multi-*` posting steps), `gh api
repos/{owner}/{repo}/actions/jobs/<id>/logs` (`implement-issue`'s CI loop), and `doit pr` — matches
no allow rule, so it runs inside the sandbox with no network and fails.

**Delegation.** Measured against the #975 run record (issue #975, comment
[6313535706](https://github.com/endavis/pyproject-template/issues/975#issuecomment-6313535706),
runs 4–6, #984): a headless Codex host calling another agent's CLI fails every time, because the
called CLI also runs inside Codex's sandbox rather than escaping it the way an allow-ruled `gh` call
does:

| Called CLI | Failure |
| :--- | :--- |
| `claude -p '<prompt>'` | exits 1 after ~200s: `API Error: Can't reach the API server — check your internet or DNS (EAI_AGAIN)` (3 of 3 attempts) |
| nested `codex … exec '<prompt>' < /dev/null` | `Error: failed to initialize in-process app-server client: Read-only file system (os error 30)` |

A delegated agent needs its own model API reachable and a writable home directory; neither exists
inside the sandbox, and no `.codex/rules/*.rules` allow rule fixes that the way it does for a
standalone `gh` call — an allow rule moves the *matched command* outside the sandbox, not everything
that command goes on to run.

**Self-identification was inference-based, now it's mechanical.** The #975 run record (issue #975,
comment
[6313535706](https://github.com/endavis/pyproject-template/issues/975#issuecomment-6313535706), run
6) caught a headless Codex host getting its own identity wrong once in three attempts: it reviewed
inline as `codex` *and* spawned a nested `codex … exec` call for the same slot, which then failed as
above. The other two runs in the same batch got it right, so the failure was intermittent — the
instruction ("identify which of the four CLIs is running this skill — that entry is you") was
inference the model could occasionally misjudge, not a step it executed deterministically. Each
`multi-*` skill's Step 0 now removes the host's own CLI name from the agent list before any
delegation call is made, so what follows (own part inline, delegate to everyone the filtered list
still names) is a filter over Step 0's parse result rather than a judgment call (#986). The sentence
is pinned byte-identical across the three skills by
`tests/test_cross_agent_contract.py`'s `SELF_REMOVAL_SENTENCE`, the same way
`HEADLESS_CODEX_HOST_SENTENCE` and `READ_ONLY_SENTENCE` are.

**Supported stance.** Codex hosts `multi-*` and `implement-issue … with <agent>` interactively, where
it can ask the user to approve the write step or the delegation. A headless Codex host supports
neither; a user who wants one anyway can add a personal `~/.codex/rules/` entry for that one command,
knowing the rule runs it outside the sandbox. This template does not add a repo-level rule for `gh`
writes or for delegated CLIs — that would trade the sandbox boundary away for exactly the commands
it exists to contain, which is a decision for a later issue, not this one.

## Hybrid C: how a delegation actually executes

Each command body is a prompt that the source agent reads. The body tells the source agent to invoke the target's CLI in non-interactive mode via the source's tool layer (Bash/exec) and pass a prompt that:

1. **Asks the target to activate its existing self-action command if available** (`/claude:review`, `$codex-adversarial-review`, etc.).
2. **Falls back to an inline workflow** (steps the target should follow if the self-action command isn't available or doesn't activate in non-interactive mode).

**Exception: the Codex bridges** (`delegate-codex-*`, `.github/skills/codex-*`,
`.claude/commands/codex/*`) hand Codex only the inline path. Its self-action skills reach `gh pr
view`/`gh pr diff`, and delegated prompts carry no `gh` command — see [Context-file
convention](#context-file-convention) (#985).

This dual-path design — Hybrid C — works regardless of whether each CLI's non-interactive mode resolves slash commands or skill mentions. If resolution works, the target uses its existing solo command and stays consistent with self-action behavior. If it doesn't, the target falls through to the inline steps and still does the right thing.

The output of the target CLI is captured by the source agent's tool layer (e.g., Bash) and re-injected into the source's conversation context, so the source can iterate on the result.

## Per-host invocation examples

```text
# In Claude Code
/codex:review                   # Claude delegates a review of current changes to Codex
/antigravity:adversarial-review # Claude delegates an adversarial review of current changes to Antigravity

# In Codex CLI
$delegate-claude-review        # Codex delegates a review of current changes to Claude
$delegate-copilot-review       # Codex delegates a review of current changes to Copilot

# In Copilot CLI (hyphen separator, not colon — skill names cannot contain colons)
/codex-adversarial-review      # Copilot delegates an adversarial review to Codex
/antigravity-review            # Copilot delegates a review of current changes to Antigravity
```

Issue-level work ("implement issue 42") does not go through this matrix — it runs the shared
`implement-issue` skill in whichever host received the request. See
[`implement-issue`](slash-commands.md#implement-issue-n) in the command reference.

## Payload schema

| Action | Required | Optional |
| :--- | :--- | :--- |
| `review` | — | focus area / file scope |
| `adversarial-review` | — | focus area / risk dimension |

All cells receive a single freeform string argument (an optional focus area) that the source agent interpolates into the prompt via `$ARGUMENTS` (Claude/Copilot markdown commands) or the user's natural language (Codex and Antigravity skills).

## Path conflicts

The skill discovery paths overlap across CLIs, so an unmitigated repo layout would cause skills authored for one host to bleed into others. Two pair-wise conflicts exist:

### Codex ↔ Copilot

Copilot CLI also reads `.agents/skills/` (per `@github/copilot` SDK, `sdk/index.d.ts`), so the same 8 Codex `delegate-*` skills bleed into Copilot sessions. They surface as `/delegate-<target>-<action>` slash commands alongside the canonical Copilot bridges (`/<target>-<action>`).

**Mitigation (user-level only):** Copilot supports a `disabledSkills` array in user config (`~/.copilot/config.json`), but **not in any repo-level settings file**. Per the SDK, a repo-level settings file accepts only `companyAnnouncements`, `disableAllHooks`, `enabledPlugins`, `extraKnownMarketplaces`, `hooks`, and `mergeStrategy` — not `disabledSkills`. So users who want to silence the bleed must edit `~/.copilot/config.json` manually. See the [Copilot section in slash-commands.md](slash-commands.md#copilot) for the snippet.

### Claude ↔ Copilot

Copilot also reads `.claude/skills/`, but this repo deliberately places the 8 Copilot-host bridges in `.github/skills/<target>-<action>/SKILL.md` instead. `.github/skills/` is read by Copilot but **not** by Claude — so the bridges do not surface as a second set of slash commands in Claude.

**Mitigation by construction.** Placing the bridges in `.github/skills/` was the explicit fix for the duplication that would otherwise occur if they lived in `.claude/skills/`. See PR #584 / issue #583 for the original report.

### What's clean by construction

Codex does not read `.claude/commands/`, `.copilot/commands/`, or `.github/skills/`. Claude does not read `.agents/skills/` or `.github/skills/`. The conflicts above are the only ones the layout creates.

## Multi-agent orchestration (`/multi-*`)

In addition to the 1-to-1 delegation matrix above, this template ships three N-to-1 orchestrators that let any host agent run **any combination** of agents in parallel and synthesize the results:

| Command | Args | Description |
| :--- | :--- | :--- |
| `/multi-plan <ais...> <issue#>` | agent list + issue number | Each listed agent independently plans the issue; plans posted as separate comments; synthesized plan posted after user approval. |
| `/multi-review <ais...>` | agent list | Each listed agent independently reviews the current PR; reviews posted as separate comments; synthesis posted after user approval. |
| `/multi-adversarial-review <ais...>` | agent list | Each listed agent independently challenges the current changes; synthesis posted to PR (if exists) after user approval. |

Each is a single shared skill, written once in `.agents/skills/multi-{plan,review,adversarial-review}/SKILL.md` (read directly by Codex, Antigravity, and Copilot) and generated for Claude at `.claude/skills/multi-{plan,review,adversarial-review}/SKILL.md` by `doit skills_sync` — the same mechanism the other 14 shared workflow skills use. Each file identifies which agent is running it the same way: Step 0 removes the host's own CLI name from the parsed agent list (see [Headless Codex host limits](#headless-codex-host-limits) above, which documents why this moved from inference to a mechanical filter), so the file never hardcodes one agent as the default and never has to infer identity a second time downstream.

## Out of scope (v1)

- Background jobs (`status`, `result`, `cancel` analogues)
- Session resume across delegations
- ACP-style brokering for long-running tasks
- Streaming output

These are deliberate omissions to keep v1 small. Synchronous-only invocation only.

## Relationship to existing artifacts

- `/<ai>:review`, `/<ai>:adversarial-review` (Claude) and `/<ai>-<action>` (Copilot), `$codex-<action>` / `$delegate-<target>-<action>` (Codex) — self-action and cross-agent delegation. Self-action files live in `.claude/commands/claude/` (Claude), `.github/skills/<ai>-<action>/` (Copilot), or `.agents/skills/<dir>/` (Codex, Antigravity).
- `implement-issue`, `ghi-status` — the shared skills that cover planning-when-needed, implementation, commit, PR creation, CI fixing, and status reporting. `implement-issue` replaced the former `/<ai>:plan`, `/<ai>:implement` matrix and `ghi-finalize` (#976).
- `/multi-plan`, `/multi-review`, `/multi-adversarial-review` — N-to-1 orchestrators that dispatch to any combination of agents. See [Multi-agent orchestration](#multi-agent-orchestration-multi-) above.
- `.claude/commands/`, `.agents/skills/`, `.github/skills/` — per-agent discovery paths. Claude reads `.claude/commands/` and `.claude/skills/`; Codex and Antigravity read `.agents/skills/`; Copilot reads `.github/skills/`, `.agents/skills/`, and `.claude/skills/`. Copilot-host bridges in this repo live in `.github/skills/` (not `.claude/skills/`) to avoid duplicating slash commands in Claude.

## See also

- [Slash Commands & Workflows](slash-commands.md) — reference for the underlying workflow commands.
- [First 5 Minutes with an AI Agent](first-5-minutes.md) — narrative onboarding for the issue-driven flow this matrix complements.
