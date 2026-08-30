---
title: Slash Commands and Workflows
description: Reference for the slash commands and dual-agent workflow this template ships with
audience:
  - contributors
  - ai-agents
tags:
  - ai
  - workflow
  - slash-commands
---

# Slash Commands and Workflows

## Purpose

This page documents the slash commands this template ships under `.claude/commands/`, and the single-agent and multi-agent workflows built on top of them. It is written for contributors who want to understand or extend the workflow, and for AI agents that need to know which command to run at each stage of the issue lifecycle.

## Workflows

### Single-agent workflow

The default Claude flow takes an issue from unplanned to closed. Each step produces an artifact the next step expects.

1. **`/<currentai>:plan <n>`** (e.g. `/claude:plan <n>`) — the host agent enters plan mode in the main conversation, reads project rules, explores the codebase, drafts a plan, and iterates with the user until approved. On approval the plan is posted as a comment on issue `#n` with the header `## Implementation Plan for #<n>: <title>`. The next step expects this comment to exist.
2. **User review of the plan** — read the comment, discuss revisions in chat, re-run `/<currentai>:plan` if needed.
3. **`/<currentai>:implement <n>`** (e.g. `/claude:implement <n>`) — the host agent verifies the plan comment exists, creates a branch (`<type>/<n>-<short-description>`) off fresh `main`, then spawns a subagent (Task tool) that reads `AGENTS.md`, fetches the plan, implements files and tests, and runs `doit check`. The main context receives only the summary. The artifact is an uncommitted working tree on the feature branch.
4. **User review of the changes** — inspect the diff and discuss fixes directly in chat; no command is needed for fix-ups.
5. **`/ghi-finalize`** — the host agent detects the branch and issue, spawns a finalization subagent that updates docs/ADRs as needed, runs `doit check`, and drafts a commit message and PR body. The main context presents the drafts and waits for explicit user approval before staging, committing, and creating the PR via `doit pr`. The artifact is an open PR referencing `Addresses #<n>`.
6. **User-driven merge** — the user reviews the PR, adds the `ready-to-merge` label, and merges via `doit pr_merge` (or the web UI). This step is never automated.
7. **Close the issue** — after the PR merges, run `doit pr_merge --auto-close` (or `gh issue close <n>`) to close the linked issue and post a closing comment.

### Multi-agent workflow

The multi-agent flow replaces the planning and (optionally) review steps with orchestrated calls that spawn any combination of agents in **isolated contexts**. The design intent is that no agent can bias another: each generates its output without seeing the others' work, and the orchestrating agent in the main conversation posts all raw outputs plus a synthesis.

Each agent's output is posted as a separate comment. The orchestrator is the only agent that writes to GitHub — all other agents run in non-interactive mode and emit to stdout only.

1. **`/multi-plan <ais...> <n>`** — takes a list of agent names (e.g. `claude codex`) and an issue number. Each listed agent independently generates a plan in an isolated context; all plans are posted as separate issue comments. The orchestrating agent synthesizes a combined plan, reviews it with the user, and posts the approved synthesized plan.
2. **`/<currentai>:implement <n>`** — same as the single-agent flow. The synthesized plan comment is the input.
3. **`/multi-review <ais...>`** — takes a list of agent names. Each listed agent independently reviews the current branch's PR; all reviews are posted as separate PR comments. The orchestrating agent synthesizes findings into a combined verdict. A user-approval gate precedes the synthesis post.
4. **`/multi-adversarial-review <ais...>`** — takes a list of agent names. Each listed agent independently challenges the current changes; all adversarial reviews are synthesized. If a PR exists the synthesis is posted; otherwise it appears in-conversation only. A user-approval gate precedes posting.
5. **`/ghi-finalize`**, merge, and **`doit pr_merge --auto-close`** — same as the single-agent flow.

### Diagnostic command

**`/ghi-status`** can be invoked at any point. It inspects the current branch, issue state, plan comment, uncommitted changes, unpushed commits, and open PRs, then reports a status summary and the suggested next command. It has no side effects.

## Command reference

Entries are alphabetical. Each one names the command, its arguments, what it does, its position in the workflow, and any design note worth knowing.

### `/<ai>:adversarial-review [focus]` (Copilot: `/<ai>-adversarial-review`)

**Args:** optional focus area. **Sources:** `.claude/commands/claude/adversarial-review.md`, `.agents/skills/codex-adversarial-review/SKILL.md` (self-action); `.claude/commands/<target>/adversarial-review.md`, `.github/skills/<target>-adversarial-review/SKILL.md` (cross-agent delegation). Copilot uses skill names instead of slash commands (see [Copilot section](#copilot) below).

Runs an adversarial review using the host agent (self-action) or delegates to a target agent (cross-agent). The review is read-only: it pressure-tests design choices, hidden assumptions, tradeoffs, alternatives, and failure modes. The host agent presents findings in the format Direction Critique / Hidden Assumptions / Failure Modes / Alternatives Worth Considering. If a PR exists, the user is asked whether to post the review as a PR comment. **Workflow position:** optional adversarial challenge before `/ghi-finalize`. **Design note:** in the self-action form, the host agent does the review work itself; no external CLI is invoked.

### `/<ai>:implement <n>` (Copilot: `/<ai>-implement <n>`)

**Args:** issue number. **Sources:** `.claude/commands/claude/implement.md`, `.agents/skills/codex-implement/SKILL.md` (self-action); cross-agent delegation files under `.claude/commands/<target>/implement.md`, `.github/skills/<target>-implement/SKILL.md`. Copilot uses skill names instead of slash commands (see [Copilot section](#copilot) below).

Validates that the issue is open and that a plan comment exists (otherwise instructs the user to run `/<currentai>:plan <n>` first). Checks the current branch: if already on `<type>/<n>-*` it resumes work on that branch, otherwise it checks out `main`, pulls, and creates a new branch. For Claude, it then spawns the custom `implement-worker` subagent (defined in `.claude/agents/implement-worker.md`) that reads `AGENTS.md` and `.claude/CLAUDE.md`, fetches the plan via `gh api`, implements files and tests, and runs `doit check`. For Copilot, implementation runs inline in the main conversation. For Codex, the `$codex-implement` skill implements inline in the Codex session. **Workflow position:** after plan exists, before `/ghi-finalize`.

### `/<ai>:plan <n>` (Copilot: `/<ai>-plan <n>`)

**Args:** issue number. **Sources:** `.claude/commands/claude/plan.md`, `.agents/skills/codex-plan/SKILL.md` (self-action); cross-agent delegation files under `.claude/commands/<target>/plan.md`, `.github/skills/<target>-plan/SKILL.md`. Copilot uses skill names instead of slash commands (see [Copilot section](#copilot) below).

Runs in the main conversation context (not a subagent) so the user can ask questions and refine the plan interactively. For Claude, enters plan mode. Validates the issue, warns if a plan comment already exists, reads `AGENTS.md`, fetches issue details, explores the codebase, and drafts a plan with the standard sections (Overview, Files to Create/Modify, Test Plan, Documentation, Validation). Iterates until the user approves, then posts the approved plan as an issue comment. **Workflow position:** first step of the single-agent workflow. **Design note:** Claude uses the `<ai>:<action>` naming convention. Copilot uses `<ai>-<action>` (hyphen) because skill names cannot contain colons; Codex uses `$<ai>-<action>` and `$delegate-<ai>-<action>`.

### `/<ai>:review [focus]` (Copilot: `/<ai>-review`)

**Args:** optional focus area. **Sources:** `.claude/commands/claude/review.md`, `.agents/skills/codex-review/SKILL.md` (self-action); `.claude/commands/<target>/review.md`, `.github/skills/<target>-review/SKILL.md` (cross-agent delegation). Copilot uses skill names instead of slash commands (see [Copilot section](#copilot) below).

Runs a PR review using the host agent (self-action) or delegates to a target agent (cross-agent). Gets the PR diff and branch context, reads project standards, evaluates correctness, style, testing, security, documentation, architecture, and breaking changes. Presents findings in the format Summary / Findings (Critical / Suggestions / Positive) / Verdict. The user is asked whether to post the review as a PR comment before posting. **Workflow position:** after `/claude:implement`, before `/ghi-finalize`.

### `/ghi-finalize`

**Args:** none. **Source:** `.claude/commands/ghi-finalize.md`.

Operates on the current feature branch, assuming implementation and review are complete. In the main context it detects the branch, extracts the issue number from the branch name, fetches issue details, and checks for uncommitted changes. It then spawns a general-purpose subagent that reads `AGENTS.md`, `.github/CONTRIBUTING.md`, and `.github/pull_request_template.md`, reviews changed files for doc/ADR updates, runs `doit check`, and drafts a commit message plus a PR body written to a temp file. The main context then presents the drafts to the user, waits for explicit approval, stages files, commits, and creates the PR via `doit pr --title=... --body-file=...`. **Workflow position:** after implementation and review. **Design note:** will not commit or create the PR without explicit user confirmation; stops if run on `main`.

### `/multi-adversarial-review <ais...>`

**Args:** one or more agent names (`claude`, `copilot`, `codex`, `antigravity`). **Sources:** `.claude/commands/multi-adversarial-review.md`, `.copilot/commands/multi-adversarial-review.md`, `.agents/skills/multi-adversarial-review/SKILL.md`.

Runs each listed agent in an isolated context to independently challenge the current uncommitted changes and the current branch vs `main`. Each agent outputs an adversarial review (Direction Critique / Hidden Assumptions / Failure Modes / Alternatives Worth Considering); all reviews are synthesized into a combined challenge with consensus and per-agent-only findings. A user-approval gate precedes posting. If a PR exists the synthesis is posted as a PR comment; otherwise it is presented in-conversation only. **Workflow position:** optional adversarial challenge before `/ghi-finalize`. **Design note:** no agent sees any other agent's output while drafting; every non-self agent runs in non-interactive mode and writes only to stdout.

### `/multi-plan <ais...> <issue#>`

**Args:** one or more agent names (`claude`, `copilot`, `codex`, `antigravity`) followed by the issue number. **Sources:** `.claude/commands/multi-plan.md`, `.copilot/commands/multi-plan.md`, `.agents/skills/multi-plan/SKILL.md`.

Validates the issue, warns if plan comments already exist, then generates independent plans from each listed agent in isolated contexts. Posts each plan as a separate issue comment, synthesizes a combined plan that highlights agreements and divergences, reviews the synthesis with the user, and only posts the synthesized plan after explicit approval. **Workflow position:** first step of the multi-agent workflow. **Design note:** isolated contexts are mandatory so no agent can see another's output while drafting; the orchestrating agent is the only one that writes to GitHub.

### `/multi-review <ais...>`

**Args:** one or more agent names (`claude`, `copilot`, `codex`, `antigravity`). **Sources:** `.claude/commands/multi-review.md`, `.copilot/commands/multi-review.md`, `.agents/skills/multi-review/SKILL.md`.

Verifies a PR exists for the current branch, warns if reviews already exist, then generates independent code reviews from each listed agent in isolated contexts. Posts each review as a separate PR comment, synthesizes findings into a combined verdict (consensus findings, per-agent-only findings, combined verdict). A user-approval gate precedes the synthesis post. **Workflow position:** after `/<currentai>:implement`, before `/ghi-finalize`, in the multi-agent workflow. **Design note:** same isolation guarantee as `/multi-plan` — no reviewer sees another's output; the synthesis is posted after all raw reviews so readers can audit it against the sources.

### `/ghi-status`

**Args:** none. **Source:** `.claude/commands/ghi-status.md`.

Inspects the current git state (branch, uncommitted changes, recent log), extracts the issue number from the branch name if on a feature branch, checks for a plan comment, unpushed commits, and open PRs, then reports a status summary and suggests the next command to run. **Workflow position:** any time. **Design note:** read-only and side-effect-free — safe to run whenever the user is unsure where they are in the lifecycle.

### `/checkpoint <slug>` and `/restore <slug>`

**Args:** optional kebab-case slug. **Sources:** `.claude/commands/checkpoint.md`, `.claude/commands/restore.md` (Claude); `.agents/skills/checkpoint/SKILL.md`, `.agents/skills/restore/SKILL.md` (Codex).

Pause-and-resume helpers for long-running workstreams. `/checkpoint` writes a paste-ready resumption prompt to `tmp/checkpoints/{inv_epoch}-{slug}.md`; `/restore` reads the matching file and treats its contents as the session's initial instructions. The `inv_epoch` prefix is a 10-digit decreasing integer so default `ls` lists newest first; users see only the slug. If `/restore` is invoked without a slug, it picks the most recent checkpoint. **Naming:** `checkpoint`/`restore` was chosen over `snapshot`/`resume` to avoid collisions with built-in slash commands across all four supported agents (Claude Code, Codex CLI and Copilot CLI all reserve `/resume`).

**Cross-agent portability:** `tmp/checkpoints/` is intentionally shared (not per-agent), so a checkpoint taken in Claude can be restored in Codex or Copilot and vice versa. This is the documented exception to the `tmp/agents/<agent-type>/` rule in `AGENTS.md`. **Workflow position:** any time, independent of the issue lifecycle. **Design note:** checkpoints are immutable once written; the user is expected to verify referenced issues/PRs are still current before acting on stale references. **When to use it:** at the end of a session when work is unfinished and you want a clean handoff into the next session — capture the goal, current branch state, recommended next step, and any user direction or constraints that should bind the future session.

**Auto-checkpoint (PreCompact / SessionStart hooks):** Claude Code also ships two lifecycle hooks that automate the pause/resume pattern for the most common context-loss event — autocompact firing mid-task. The `PreCompact` hook synthesizes a checkpoint to `tmp/checkpoints/{inv_epoch}-auto-precompact.md` before compaction; the `SessionStart` hook (matcher `compact|resume`) injects the newest auto-precompact file into the new session's context automatically. Auto-precompact files share the same filename convention and directory as manual `/checkpoint` files, so `/restore auto-precompact` also works. Set `CLAUDE_NO_AUTO_RESTORE=1` to opt out of the automatic restore; set `CLAUDE_RESTORE_ANY=1` to widen the restore glob to any `*.md` checkpoint. See [Auto-Checkpoint and Session-Restore Hooks](auto-checkpoint-hook.md) for full details.

## Codex

Codex does not use repo-defined slash commands in this template. Instead, the Codex workflow is provided through **repo-scoped skills** under `.agents/skills/`, which Codex can invoke through its built-in `/skills` browser or explicit mentions such as `$codex-plan`, `$codex-implement`, and `$ghi-finalize`.

**Workflow coverage:** the checked-in Codex skills cover planning, implementation, review, adversarial review, and finalization through PR creation. They preserve the same repo artifact contract used by the Claude flow:

- `$codex-plan` posts the approved plan comment with the header `## Implementation Plan for #<n>: <title>`
- `$codex-implement` creates or resumes the issue branch and finishes with `doit check`
- `$codex-review` reviews the current branch's PR and posts findings after user approval
- `$codex-adversarial-review` runs an adversarial challenge review
- `$ghi-finalize` drafts the commit and PR artifacts and uses `doit pr` after explicit approval

**Config and safety:** `.codex/config.toml` still configures approvals and hook wiring for Codex. The shared dangerous-command hook at `tools/hooks/ai/block-dangerous-commands.py` applies to Codex, and the approval-policy deny rules remain a secondary defense layer.

**Out of scope for Codex in this template:** no repo-defined custom slash commands, no dual-agent orchestration, and no Codex-specific close-issue automation.

## Antigravity

Antigravity (`agy`) does not use repo-defined slash commands in this template. Instead, the Antigravity workflow is provided through **repo-scoped skills** under `.agents/skills/` (the same directory and `SKILL.md` format Codex uses), which `agy` activates by matching your request against each skill's `description:` frontmatter — there is no slash or `$` prefix.

**Workflow coverage:** the checked-in Antigravity skills cover planning, implementation, review, and adversarial review. They preserve the same repo artifact contract used by the Claude flow:

- `antigravity-plan` posts the approved plan comment with the header `## Implementation Plan for #<n>: <title>`
- `antigravity-implement` creates or resumes the issue branch and finishes with `doit check`
- `antigravity-review` reviews the current branch's PR and posts findings after user approval
- `antigravity-adversarial-review` runs an adversarial challenge review
- The shared `ghi-finalize` skill (from `.agents/skills/`) drafts the commit and PR artifacts

**Config and safety:** `.agents/hooks.json` wires the shared dangerous-command hook at `tools/hooks/ai/block-dangerous-commands.py` for Antigravity (a `PreToolUse` matcher on `run_command`/`write_to_file`). Unlike the exit-code-2 CLIs, `agy` blocks by printing `{"decision":"deny"}` on stdout, which holds even under `--dangerously-skip-permissions`. Because `agy` only loads workspace customizations for an active/trusted workspace, headless `agy -p` invocations must pass `--add-dir <repo-root>`.

**Out of scope for Antigravity in this phase:** cross-agent delegation bridges and multi-agent orchestration for `agy` land in a later phase.

## Copilot

GitHub Copilot CLI discovers project **skills** only from `skills/` directories: `.github/skills/`, `.agents/skills/`, and `.claude/skills/` — plus the corresponding personal paths under `~/` and anything added via `/skills add`. It reads no `.copilot/commands/`, so this repo's `.copilot/commands/multi-*.md` files are never loaded.

It does load **single-file commands** from `.claude/commands/`. That is a separate mechanism from skills — added in CLI 0.0.399, flagged `isCommand` in `sdk/index.d.ts`, and gated by an `enableConfigDiscovery` option that defaults on. Claude's command files surface in a Copilot session as a result (#753).

Because skill names are derived from their directory name and **cannot contain colons**, Copilot's surface for the cross-agent matrix uses `<target>-<action>` (hyphen), not `<target>:<action>` (colon). The functional behavior is identical to the other CLIs — only the slash name differs.

**Self-action and cross-agent skills:** Every cell of the cross-agent matrix for the Copilot host lives under `.github/skills/<target>-<action>/SKILL.md`:

- Self-action: `/copilot-plan`, `/copilot-implement`, `/copilot-review`, `/copilot-adversarial-review`
- To Claude: `/claude-plan`, `/claude-implement`, `/claude-review`, `/claude-adversarial-review`
- To Codex: `/codex-plan`, `/codex-implement`, `/codex-review`, `/codex-adversarial-review`

**Why `.github/skills/` and not `.claude/skills/`?** Copilot reads both, but Claude also reads `.claude/skills/`. Placing the bridges there would surface them as a second set of slash commands in Claude alongside the native `<ai>:<action>` commands — visible noise. `.github/skills/` is read by Copilot but not by Claude (or by Codex), so it's the only Copilot-only project skill path.

**Config directory:** `.copilot/` — established as the Copilot CLI config directory for this repo, parallel to `.claude/`, `.codex/`, and `.agents/`. Note that no `.copilot/commands/<target>/` files are needed (or read).

**Dangerous command hook:** Already wired in `.github/hooks/copilot-hooks.json`. It invokes `tools/hooks/ai/block-dangerous-commands.py` as a `preToolUse` hook, blocking dangerous shell commands before they execute. See [AI Command Blocking](command-blocking.md) for details.

**Implement-worker subagent:** Shared with Claude — defined in `.claude/agents/implement-worker.md`. Copilot CLI's `task` tool reads this file when `/claude-implement` spawns the subagent.

**Known limitation — `delegate-*` skill bleed:** Because Copilot also reads `.agents/skills/`, it surfaces a Codex-only `delegate-<target>-<action>` skill for every (target, action) pair alongside the canonical `<target>-<action>` ones. The Codex-only skills shell out to Codex's syntax and are wasted noise in a Copilot session. Copilot exposes a `disabledSkills` config field (see `~/.copilot/config.json`), but **only at user level — there is no repo-level setting for it.** If you want to silence the delegate-* skills in Copilot, add them to your user config manually:

```json
{
  "disabledSkills": [
    "delegate-claude-plan",
    "delegate-claude-implement",
    "delegate-claude-review",
    "delegate-claude-adversarial-review",
    "delegate-codex-plan",
    "delegate-codex-implement",
    "delegate-codex-review",
    "delegate-codex-adversarial-review",
    "delegate-copilot-plan",
    "delegate-copilot-implement",
    "delegate-copilot-review",
    "delegate-copilot-adversarial-review",
    "delegate-antigravity-plan",
    "delegate-antigravity-implement",
    "delegate-antigravity-review",
    "delegate-antigravity-adversarial-review"
  ]
}
```

**`.claude/commands/` in Copilot — measured, and smaller than it looks.** Copilot loads single-file
commands from `.claude/commands/`, which raised the question of whether Claude's command surface
bleeds into a Copilot session the way `delegate-*` bleeds the other way. It does not, and the
question is closed (#757). Run `copilot skill list` from the repo root to reproduce:

| | |
| :--- | ---: |
| project entries Copilot lists | 40 |
| from `.github/skills/` | 16 |
| from `.agents/skills/` | 23 |
| **from `.claude/commands/`** | **1** |

Two reasons the number is one:

- **Discovery is not recursive.** Only top-level `*.md` files in `.claude/commands/` are read, so
  none of the 16 nested `<target>/<action>.md` bridge files surface in Copilot.
- **Names collide and dedupe.** `checkpoint`, `ghi-finalize`, `multi-*` and `restore` exist in
  `.agents/skills/` as well, and Copilot keeps one entry per name.

The one entry is **`ghi-status`**, which has no `.agents/skills/` counterpart — so
`.claude/commands/` discovery is not a leak here, it is the only thing that makes `/ghi-status`
available in Copilot at all.

The same dedup shadows eight `.agents/skills/` entries — the `antigravity-*` and `codex-*`
self-action skills — behind the same-named Copilot bridges in `.github/skills/`. That is the
desired outcome for a Copilot session, but it depends on precedence rather than on anything the
repo declares, so check `copilot skill list` after renaming a skill.

**Correction:** an earlier version of this note said `disabledSkills` does not cover commands. It
does — a command is loaded into the same collection `isSkillDisabled(name)` filters, which is why
`ghi-status` appears in `copilot skill list` at all. The claim was inferred from the field name
rather than checked.

## Adding a new slash command

1. **Pick the location.** Claude commands live in `.claude/commands/<name>.md` and become `/<name>` in Claude Code. Copilot CLI discovers **skills** only from `skills/` directories (`.github/skills/`, `.agents/skills/`, `.claude/skills/`) — never from `commands/`, though it does load single-file commands from `.claude/commands/` by a separate mechanism. To expose a Copilot-only command, author it as `.github/skills/<name>/SKILL.md` (with YAML frontmatter) — `.github/skills/` is the only Copilot project skill path that Claude does **not** also read. The slash name becomes `/<name>` because skill names cannot contain colons.
2. **Use the CLI file format** — not the `docs/` frontmatter format. Start with a top-level `# Title` heading, follow with a one-line description (which may include the `$ARGUMENTS` placeholder if the command takes arguments), then a `## Instructions` section containing the step-by-step body. **Do not add YAML frontmatter.** The CLIs expect plain markdown; frontmatter would appear verbatim in the rendered prompt.
3. **Use `$ARGUMENTS` for inputs.** When the user invokes `/<command> foo bar`, every `$ARGUMENTS` occurrence in the file is substituted with `foo bar` before the command body is sent to the model. For commands that take no arguments (like `/ghi-finalize` or `/ghi-status`), omit the placeholder.
4. **Decide: subagent or main context?** Delegate to a general-purpose subagent via the Task tool when the command does heavy codebase exploration, writes files, or runs long commands whose output would bloat the main conversation — `.claude/commands/claude/implement.md` is the canonical example. Run in the main context when the user needs to interact step by step (plan mode, iteration, explicit approvals) — `.claude/commands/claude/plan.md` is the canonical example.
5. **Update this document** when you add or remove a command. The command reference section should list every file under `.claude/commands/`.

## Cross-agent delegation matrix

This template ships a `<target>:<action>` matrix where `<target>` can be **the same agent** (self-action) or **any of the other three** (cross-agent delegation). Self-action (`/claude:plan`, etc.) and cross-agent delegation (`/codex:plan` from Claude, etc.) share the same `<ai>:<action>` naming convention. The full design — convention, file layout, prefix mapping (`/foo` vs `$foo` for Codex), Hybrid C runtime behavior, and the `.agents/skills/` ↔ Copilot conflict mitigation — is documented separately:

→ See [Cross-Agent Delegation Matrix](cross-agent-delegation.md).

Quick reference:

```text
# In Claude Code (colon separator):
/<target>:<action> [args]      # e.g. /codex:plan 42, /antigravity:adversarial-review

# In Copilot CLI (hyphen separator — skill names cannot contain colons):
/<target>-<action> [args]      # e.g. /codex-plan 42, /antigravity-adversarial-review

# In Codex CLI (skills, not slash commands; hyphen separator):
$<target>-<action> [args]              # self-action: $codex-plan 42
$delegate-<target>-<action> [args]     # cross-agent: $delegate-claude-implement 42
```

## See also

- [Cross-Agent Delegation Matrix](cross-agent-delegation.md) — convention, matrix, and per-host invocation for the `<target>:<action>` family.
- [First 5 Minutes with an AI Agent](first-5-minutes.md) — narrative onboarding walkthrough showing the workflow end to end.
- [AI Agent Setup Guide](../AI_SETUP.md) — per-CLI configuration and whitelists.
- [Architectural Conventions](architectural-conventions.md) — imperative rules for AI-generated code.
- [AI Enforcement Principles](enforcement-principles.md) — how this template enforces rules in code, not just instructions.
- [AI Command Blocking](command-blocking.md) — tool-level hooks that block dangerous commands.
- [AGENTS.md](../../../AGENTS.md) — universal context file and workflow reference.
