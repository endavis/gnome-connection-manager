# Cross-Agent Delegation Matrix

A consistent, explicit-invocation interface that lets any of the four supported AI CLIs (Claude Code, Codex CLI, Copilot CLI, Antigravity CLI) hand a task — `plan`, `implement`, `review`, or `adversarial-review` — to any of the others.

> **Antigravity CLI (`agy`) is wired into the matrix as a full agent** (both source and target). Its self-action skills (`antigravity-*`) live in `.agents/skills/`, and its outbound bridges **reuse Codex's host-agnostic `delegate-*` skills** in that same directory (both CLIs read it). Inbound bridges to `agy` live in each host's own directory. The `/multi-*` orchestrators also accept `antigravity` as an agent. See [Matrix](#matrix) for the cell and file counts — it is the only place they are written down.

## Why this exists

Each agent already drives *itself* through the issue-driven workflow (`/<ai>:plan`, `/<ai>:implement`, `/ghi-finalize`). This matrix adds the missing piece: deliberate, user-invoked handoff *between* agents, without depending on third-party plugins like `openai/codex-plugin-cc` or community forks.

The matrix replaces what would otherwise be a patchwork of inconsistent third-party plugins. It runs on top of the CLIs' existing non-interactive modes (`-p` / `exec`) and uses the same command names across all hosts, so users learn the surface once.

## Convention

`<prefix><target><separator><action>` where:

- **Prefix:** `/` on Claude Code and Copilot CLI; `$` on Codex CLI (Codex's repo-defined commands are skills, not slash commands; OpenAI deprecated `~/.codex/prompts/`).
- **Separator:** `:` (colon) on Claude Code — it reads a `commands/<scope>/<name>` directory layout that supports colon-namespaced slash commands. `-` (hyphen) on Copilot CLI and Codex CLI — these are skill-based and skill names are derived from directory names, which cannot contain colons.
- **Target:** `claude`, `codex`, `copilot`, `antigravity` — the agent to invoke. Can be the **same** agent (self-action) or one of the other three (cross-agent delegation). Antigravity (`agy`) has no slash/`$` prefix — it activates skills by matching the `description:` frontmatter.
- **Action:** `plan`, `implement`, `review`, `adversarial-review`.

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
| `plan` | issue number (required) | Prefers the target's existing `/<target>:plan` or `$<target>-plan` if available; otherwise inline workflow. |
| `implement` | issue number (required) | Prefers the target's existing `/<target>:implement` or `$<target>-implement` if available; otherwise inline workflow. |
| `review` | optional focus area | Reviews current PR or branch-vs-main changes. |
| `adversarial-review` | optional focus | Steerable challenge review — pressure-tests design, hidden assumptions, alternatives, failure modes. |

## Workflow contract

The naming convention above says where the files live. This says what they must **say**.

Because a user can switch agents mid-workflow — plan with Codex, implement with Claude,
review with Copilot — the workflow files carry a handful of literal strings that let the
next agent pick up the state the previous one left. These are a contract, not prose
choices: if one host stops emitting the plan-comment header, the next agent cannot find
the plan.

| Element | Literal | Required in | Why it is load-bearing |
| :--- | :--- | :--- | :--- |
| Plan-comment header | `Implementation Plan for` | every `plan` file | How `implement` locates the plan comment on the issue |
| Branch-name pattern | `<type>/` | every `implement` file | `doit pr` derives the issue number from the branch name |
| Validation command | `doit check` | every `implement` file | The pre-commit gate the workflow promises |
| Finalize handoff | `ghi-finalize` | every `implement` file | Tells the user the next step; implement never opens a PR |
| Issue reference | `Addresses #` | every `ghi-finalize` file | Links the PR to its issue; `doit pr_merge --auto-close` depends on it |
| Read-only constraint | the sentence below | every `review` and `adversarial-review` file | A review that edits code is not a review |

The read-only constraint must appear **verbatim** on every surface, because a
constraint paraphrased per host drifts into a weaker version on one of them, and
whichever agent is driving decides which version applies:

> **Read-only.** Review and report — do not edit files, commit, or push. Findings go to
> the user and the PR; any fix is a separate change the user asks for.

### Declared exemptions

Uniform prose is not the goal — agreement on the contract is. Where a host genuinely
differs, the difference is declared rather than papered over:

| Element | Host | Why |
| :--- | :--- | :--- |
| `doit check` in `implement` | Claude | Claude delegates implementation to `.claude/agents/implement-worker.md`, which runs it. The command file itself never names it. |

### Enforcement

`tests/test_cross_agent_contract.py` asserts every element above, and its `EXEMPTIONS`
table mirrors the one here. **This document is the specification**; when the two
disagree, the test is the bug. Adding an exemption to the test without adding a row here
is how a contract quietly becomes a suggestion.

The checks are scoped to the agents a project actually wires (see
`tests/agent_roster.py`), so a project that keeps one agent is held to the contract for
that agent only.

## Matrix

The 4 sources × 4 targets × 4 actions = 64 cells (including self-action). Cross-agent delegation is 4 × 3 × 4 = 48 cells, across **40 distinct files** — Codex and Antigravity share the host-agnostic `.agents/skills/delegate-*` files, so the 8 `antigravity → {claude, copilot}` cells reuse Codex's files.

| Source ↓ / Target → | claude | codex | copilot | antigravity |
| :--- | :--- | :--- | :--- | :--- |
| **claude** (`.claude/commands/`) | `/claude:{plan,implement,review,adversarial-review}` | `/codex:{...}` | `/copilot:{...}` | `/antigravity:{...}` |
| **codex** (`.agents/skills/`) | `$delegate-claude-{...}` | `$codex-{plan,implement,review,adversarial-review}` | `$delegate-copilot-{...}` | `$delegate-antigravity-{...}` |
| **copilot** (`.github/skills/`) | `/claude-{...}` | `/codex-{...}` | `/copilot-{plan,implement,review,adversarial-review}` | `/antigravity-{...}` |
| **antigravity** (`.agents/skills/`) | `delegate-claude-{...}` | `delegate-codex-{...}` | `delegate-copilot-{...}` | `antigravity-{plan,implement,review,adversarial-review}` |

Each cell expands to `{plan, implement, review, adversarial-review}`. The diagonal (self-action) cells run natively in the host agent rather than shelling out. **Naming asymmetry:** Claude uses `<target>:<action>` (colon); Copilot and Codex use `<target>-<action>` (hyphen) because their command surface is skills, and skill names — being directory names — cannot contain colons. Antigravity is also skill-based and has **no prefix at all** — it activates the matching skill by its `description:`. The functional behavior is identical across hosts; only the invocation surface differs.

## Non-interactive flags per CLI

Each bridge invokes the target CLI in headless mode. Each CLI requires a flag to skip the interactive approval prompts that would otherwise block tool calls when no human is at the terminal:

| Target | Invocation | Why |
| :--- | :--- | :--- |
| Claude Code | `claude -p '<prompt>'` | `-p` runs headless. No additional approval-bypass flag needed for the typical tool surface. |
| Codex CLI | `codex -a never --dangerously-bypass-hook-trust exec '<prompt>'` | `-a never` (`--ask-for-approval never`) prevents Codex from asking the (absent) user before running shell commands. Without it, every tool call in the delegated session is denied. |
| Copilot CLI | `copilot --allow-all -p '<prompt>'` | `--allow-all` enables all permissions (equivalent to `--allow-all-tools --allow-all-paths --allow-all-urls`). Without it, Copilot prompts for path or URL access mid-session, which the absent user can't answer. **Order matters:** `--allow-all` must precede `-p`, since `-p <text>` consumes its argument and would otherwise grab the next flag. |
| Antigravity CLI | `agy -p '<prompt>' --dangerously-skip-permissions --add-dir "$(git rev-parse --show-toplevel)"` | `-p` runs headless; `--dangerously-skip-permissions` auto-approves tool calls the absent user can't confirm. `--add-dir <repo-root>` is **required** so `agy` treats the repo as an active workspace and loads `.agents/` (skills + the shared dangerous-command hook) — a headless `agy -p` otherwise falls back to its own home workspace and ignores the repo's `.agents/`. The safety hook's stdout `{"decision":"deny"}` still hard-blocks dangerous commands even under `--dangerously-skip-permissions`. |

These flags are intentional: in delegated invocations, the human is at the *source* agent and not at the target's prompt. Approval prompts in the target session can never be answered, so they must be bypassed. The source agent retains full visibility through captured stdout and can stop the chain at any point.

## Hybrid C: how a delegation actually executes

Each command body is a prompt that the source agent reads. The body tells the source agent to invoke the target's CLI in non-interactive mode via the source's tool layer (Bash/exec) and pass a prompt that:

1. **Asks the target to activate its existing self-action command if available** (`/claude:plan`, `$codex-implement`, etc.).
2. **Falls back to an inline workflow** (steps the target should follow if the self-action command isn't available or doesn't activate in non-interactive mode).

This dual-path design — Hybrid C — works regardless of whether each CLI's non-interactive mode resolves slash commands or skill mentions. If resolution works, the target uses its existing solo command and stays consistent with self-action behavior. If it doesn't, the target falls through to the inline steps and still does the right thing.

The output of the target CLI is captured by the source agent's tool layer (e.g., Bash) and re-injected into the source's conversation context, so the source can iterate on the result.

## Per-host invocation examples

```text
# In Claude Code
/codex:plan 42                 # Claude delegates planning of issue 42 to Codex
/antigravity:adversarial-review # Claude delegates an adversarial review of current changes to Antigravity

# In Codex CLI
$delegate-claude-implement 42  # Codex delegates implementation of issue 42 to Claude
$delegate-copilot-review       # Codex delegates a review of current changes to Copilot

# In Copilot CLI (hyphen separator, not colon — skill names cannot contain colons)
/codex-adversarial-review      # Copilot delegates an adversarial review to Codex
/antigravity-implement 42      # Copilot delegates implementation of issue 42 to Antigravity
```

## Payload schema

| Action | Required | Optional |
| :--- | :--- | :--- |
| `plan` | issue number | — |
| `implement` | issue number | — |
| `review` | — | focus area / file scope |
| `adversarial-review` | — | focus area / risk dimension |

All cells receive a single freeform string argument that the source agent interpolates into the prompt. Issue numbers map to `$ARGUMENTS` (Claude/Copilot markdown commands) or are extracted from the user's natural language (Codex and Antigravity skills).

## Path conflicts

The skill discovery paths overlap across CLIs, so an unmitigated repo layout would cause skills authored for one host to bleed into others. Two pair-wise conflicts exist:

### Codex ↔ Copilot

Copilot CLI also reads `.agents/skills/` (per `@github/copilot` SDK, `sdk/index.d.ts`), so the same 12 Codex `delegate-*` skills bleed into Copilot sessions. They surface as `/delegate-<target>-<action>` slash commands alongside the canonical Copilot bridges (`/<target>-<action>`).

**Mitigation (user-level only):** Copilot supports a `disabledSkills` array in user config (`~/.copilot/config.json`), but **not in any repo-level settings file**. Per the SDK, a repo-level settings file accepts only `companyAnnouncements`, `disableAllHooks`, `enabledPlugins`, `extraKnownMarketplaces`, `hooks`, and `mergeStrategy` — not `disabledSkills`. So users who want to silence the bleed must edit `~/.copilot/config.json` manually. See the [Copilot section in slash-commands.md](slash-commands.md#copilot) for the snippet.

### Claude ↔ Copilot

Copilot also reads `.claude/skills/`, but this repo deliberately places the 16 Copilot-host bridges in `.github/skills/<target>-<action>/SKILL.md` instead. `.github/skills/` is read by Copilot but **not** by Claude — so the bridges do not surface as a second set of slash commands in Claude.

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

Each command is available for all four hosts:
- Claude: `.claude/commands/multi-{plan,review,adversarial-review}.md`
- Copilot: `.copilot/commands/multi-{plan,review,adversarial-review}.md`
- Codex: `.agents/skills/multi-{plan,review,adversarial-review}/SKILL.md`

## Out of scope (v1)

- Background jobs (`status`, `result`, `cancel` analogues)
- Session resume across delegations
- ACP-style brokering for long-running tasks
- Streaming output

These are deliberate omissions to keep v1 small. Synchronous-only invocation only.

## Relationship to existing artifacts

- `/<ai>:plan`, `/<ai>:implement`, `/<ai>:review`, `/<ai>:adversarial-review` (Claude) and `/<ai>-<action>` (Copilot), `$codex-<action>` / `$delegate-<target>-<action>` (Codex) — self-action and cross-agent delegation. Self-action files live in `.claude/commands/claude/` (Claude), `.github/skills/<ai>-<action>/` (Copilot), or `.agents/skills/<dir>/` (Codex, Antigravity).
- `ghi-finalize`, `ghi-status` — these cover the post-implementation steps (commit, PR creation, status reporting).
- `/multi-plan`, `/multi-review`, `/multi-adversarial-review` — N-to-1 orchestrators that dispatch to any combination of agents. See [Multi-agent orchestration](#multi-agent-orchestration-multi-) above.
- `.claude/commands/`, `.agents/skills/`, `.github/skills/` — per-agent discovery paths. Claude reads `.claude/commands/` and `.claude/skills/`; Codex and Antigravity read `.agents/skills/`; Copilot reads `.github/skills/`, `.agents/skills/`, and `.claude/skills/`. Copilot-host bridges in this repo live in `.github/skills/` (not `.claude/skills/`) to avoid duplicating slash commands in Claude.

## See also

- [Slash Commands & Workflows](slash-commands.md) — reference for the underlying workflow commands.
- [First 5 Minutes with an AI Agent](first-5-minutes.md) — narrative onboarding for the issue-driven flow this matrix complements.
