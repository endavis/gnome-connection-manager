---
title: Agent Roles and Models
description: How to choose which CLI and model runs each cross-agent role (plan, plan review, code, review, adversarial review) from a per-user config
audience:
  - contributors
  - ai-agents
tags:
  - ai
  - workflow
  - configuration
---

# Agent Roles and Models

Cross-agent work names a *role*, not a CLI. You choose, per role, which CLI runs it and on which
model. Subscriptions belong to a person, so the choice lives in a per-user file and no model names
are committed. With no config nothing changes: every skill runs the invocation it always did.

| Role | Used by |
| :--- | :--- |
| `plan` | `implement-issue` Planner brief, `multi-plan` |
| `plan_review` | `implement-issue` Plan-review brief |
| `code` | `implement-issue` Coder brief |
| `review` | review bridges, `multi-review` |
| `adversarial_review` | adversarial-review bridges, `multi-adversarial-review` |

## Config files

Two TOML layers, merged key by key. The project-local layer wins.

| Layer | Path | Committed |
| :--- | :--- | :--- |
| User | `$XDG_CONFIG_HOME/pyproject-template/agents.toml`, else `~/.config/pyproject-template/agents.toml` | no |
| Project-local | `.config/pyproject_template/agents.local.toml` | no (gitignored) |
| Built-in | none: each CLI keeps its own default | n/a |

The project-local file is per checkout, so a worktree needs its own copy; prefer the user layer.
Do not use the committed `.config/pyproject_template/settings.toml`: it holds template-sync metadata.

```toml
[roles.plan]
cli = "claude"
model = "opus"

[roles.review]
cli = "agy"
model = "<a model from `agy models`>"

[roles.adversarial_review]
cli = "copilot"
model = "<a model from `copilot help config`>"
effort = "high"
```

For a starting point that sets every role, copy [`agents.example.toml`](agents.example.toml) to
`~/.config/pyproject-template/agents.toml`, keep the CLIs you subscribe to, and run
`uv run doit agent_cmd --check`.

- `cli` is required: `claude`, `codex`, `copilot` or `agy` (`antigravity` is an alias).
- `model` is optional. Without it the CLI keeps its default.
- `effort` is accepted only for `codex` and `copilot`. For `agy` and `claude` put it in the model
  name or leave it out; anything else is a config error.
- A project-local `cli` replaces the whole role from the user layer, since a model belongs to its CLI.
- Values must be non-empty and not start with `-`.

## Resolving a role

Skills never read the TOML. They run the task and act on the last stdout line (JSON):

```bash
uv run doit agent_cmd --role=code --host=claude
uv run doit agent_cmd --role=review --host=claude --cli=codex
```

| `mode` | Meaning |
| :--- | :--- |
| `subagent` (optional `model`, optional `effort`) | Run the brief in the host's own subagent, with that model and effort when given. On Codex spawn it with `fork_turns: "none"` plus `model` and `reasoning_effort`. |
| `inline` | The host is `agy`, the target, with no model: do the work in the session. |
| `cli` (`cli`, `command`) | Run `command` after replacing `'<prompt>'` with the prompt. |

The result is `subagent` only when the role's CLI is the host and the host's subagent can run the
model: Claude Code accepts `opus`, `sonnet`, `haiku` and `fable`, and Codex's `spawn_agent` accepts any
`model` and `reasoning_effort` when spawned with `fork_turns: "none"` (verified live in 0.166.0, #1151), so a
Codex role may also carry `effort`. Copilot's `task` tool does not honour a
chosen model (in 1.0.105 its `model` schema allowed only `auto`; per-agent models are Copilot's own
`subagents.agents.<agent-name>` setting, set with `/subagents`), and `agy` has no subagent
mechanism, so a configured model on those hosts resolves to `cli`. Effort on Claude also resolves to `cli`. `--cli=<name>` fixes the target CLI, as the
bridges do; the role's model and effort then apply only if its configured `cli` is that CLI.

## Listing models and checking the config

None of these spend tokens:

| CLI | Command |
| :--- | :--- |
| `agy` | `agy models` |
| `codex` | `codex debug models` (the `slug` fields) |
| `copilot` | `copilot help config` (the `model` values) |

`uv run doit agent_cmd --check` matches each configured model against those lists, requiring the
whole name (a prefix fails), and exits 1 on any error or a missing CLI. Claude has no list: the
aliases pass and other names are reported as unchecked.

## See also

- [Cross-Agent Delegation Matrix](cross-agent-delegation.md#roles-and-models)
- [`agent_cmd` task reference](../doit-tasks-reference.md#agent_cmd)
- [ADR-9030: Cross-agent roles resolve through a per-user config](../../decisions/9030-cross-agent-roles-resolve-through-a-per-user-config.md)
