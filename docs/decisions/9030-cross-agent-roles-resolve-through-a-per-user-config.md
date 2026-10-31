---
title: "ADR-9030: Cross-agent roles resolve through a per-user config"
description: Cross-agent roles resolve through one doit task reading a layered per-user config, subagent first, with Codex subagents taking a model and effort and Copilot subagent models resolving to the CLI
date: 2026-10-30
audience:
  - contributors
tags:
  - adr
---

# ADR-9030: Cross-agent roles resolve through a per-user config

## Status

Accepted

## Decision

1. **Roles, not CLIs.** Cross-agent work names one of five roles: `plan`, `plan_review`, `code`, `review`, `adversarial_review`. A role names the CLI and optionally a model and, for `codex` and `copilot`, an effort.
2. **Layered per-user config, no committed model names.** The user file (`$XDG_CONFIG_HOME/pyproject-template/agents.toml`, else `~/.config/pyproject-template/agents.toml`) is overridden key by key by the gitignored `.config/pyproject_template/agents.local.toml`. A local `cli` replaces the role wholesale. There is no built-in layer: with no config each CLI keeps its default.
3. **One resolver.** `doit agent_cmd --role --host [--cli]` returns `subagent` (optional model and effort), `inline`, or `cli` (a ready shell command with a `'<prompt>'` slot). Skills never parse the TOML or build flags. With no config the result is exactly the invocation the skills used before.
4. **Subagent first.** `subagent` is returned only when the role's CLI is the host and the host's subagent can run the model. Claude Code accepts `opus`, `sonnet`, `haiku` and `fable`. Copilot's `task` tool has a `model` parameter, but in 1.0.105 its schema allowed only `auto`, and a model passed outside it ran on a different model (#1151); per-agent models are Copilot's own `subagents.agents.<agent-name>` setting. Codex's `spawn_agent` takes `model` and `reasoning_effort` when spawned with `fork_turns: "none"` (verified live in 0.166.0, #1151), so a Codex role on a Codex host returns `subagent` with its `model` and `effort`. A configured model on Copilot resolves to `cli`. `agy` has no subagent mechanism: `inline` without a model, else `cli`.
5. **`--check`** matches configured models against `agy models`, `codex debug models` and `copilot help config`, which spend no tokens. Claude aliases pass; other Claude names are reported unchecked.

## Rationale

Every `agy`, `codex` and `copilot` invocation ran on the CLI's default model, and people's subscriptions differ. Putting the choice in a per-user file keeps model names out of the repository, and one resolver keeps the flag shapes for four CLIs in one tested place instead of copied into each skill. The python floor is 3.12, so `tomllib` needs no dependency.

## Consequences

- Delegation surfaces gain a resolution step and keep their literals as the fallback.
- The project-local file is per checkout, so a worktree needs its own copy; the user layer avoids that.
- Copilot stays on `cli`: a role's model cannot be relied on through its `task` tool. A person who wants Copilot subagents on a model sets it with `/subagents`.
- Codex returns `subagent` with its model and effort; the skills must spawn it with `fork_turns: "none"`, since a full-history fork ignores both. The briefs are self-contained, so no parent history is lost.

## Documentation

- [Agent Roles and Models](../development/ai/agent-roles.md)
- [Cross-Agent Delegation — Roles and models](../development/ai/cross-agent-delegation.md#roles-and-models)
- [doit tasks reference — agent_cmd](../development/doit-tasks-reference.md#agent_cmd)

Issue: #1150. Copilot `task` and Codex `multi_agent` results: #1151.
