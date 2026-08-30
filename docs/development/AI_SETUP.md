---
title: AI Agent Setup Guide
description: Configure Claude, Copilot, Codex, and Antigravity for this project
audience:
  - contributors
  - ai-agents
tags:
  - ai
  - setup
  - configuration
---

# AI Agent Setup Guide

This template is designed primarily for **Claude Code**, which is the only agent that ships the full slash-command workflow and acts as the orchestrator in single-agent and multi-agent flows. **GitHub Copilot CLI** is supported as a standalone alternative whose workflow is discovered as skills from `.github/skills/`. **Codex CLI** is supported as a standalone alternative without slash commands. **Antigravity CLI** (`agy`) is supported as a standalone alternative that shares the `.agents/` customization root with Codex. See the comparison table below for the per-agent breakdown.

> **New here?** Start with the [First 5 Minutes walkthrough](ai/first-5-minutes.md) for a narrative tour of the AI agent workflow. This page is the configuration reference.

## Supported AI Agents

### Agent comparison

| Agent | Permission model | Hooks support | Slash commands | LSP | Dual-agent role |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Codex CLI** | TOML approval policies (`.codex/config.toml`) plus repo skills (`.agents/skills/`) | Project-level `tools/hooks/ai/` apply via Codex hooks | Built-in only; repo workflow uses skills | Not documented | Standalone alternative (not part of dual-agent flow) |
| **Antigravity CLI** (`agy`) | Skills + hooks in the shared `.agents/` root (`hooks.json`, `skills/`) | Project-level `tools/hooks/ai/` apply via `.agents/hooks.json` (stdout `deny` contract) | Built-in only; repo workflow uses `.agents/skills/` skills (`antigravity-*`), activated by description | Not documented | Standalone alternative; full cross-agent delegation + `/multi-*` support |
| **GitHub Copilot CLI** | JSON hook config (`.github/hooks/copilot-hooks.json`) | Project-level hooks apply; Copilot `preToolUse` hook wired | Self-action (`/copilot-plan`, `/copilot-implement`, `/copilot-review`, `/copilot-adversarial-review`) plus one cross-agent bridge per (target, action) pair (`/{claude,codex,antigravity}-{plan,implement,review,adversarial-review}`) — all under `.github/skills/<target>-<action>/SKILL.md` (Copilot-only path, invisible to Claude). Copilot uses hyphen naming because skill names cannot contain colons. `/ghi-finalize` and `/multi-*` come from `.agents/skills/` | Not documented | Standalone alternative |
| **Claude Code** | Layered permissions (`.claude/settings.local.json` + `.claude/settings.json` PreToolUse hooks) | Project-level hooks plus Claude PreToolUse hooks | Self-action (`/claude:plan`, `/claude:implement`, `/claude:review`, `/claude:adversarial-review`) + `/ghi-finalize`, `/ghi-status` + multi-orchestrator (`/multi-plan`, `/multi-review`, `/multi-adversarial-review`) + one delegation command per (target, action) pair (`.claude/commands/<target>/`) | Supported | Primary orchestrator in single-agent and multi-agent flows |

The project-level dangerous-command hooks under `tools/hooks/ai/` apply to all four agents regardless of per-agent config and cannot be bypassed by editing `.claude/settings.local.json`, `.codex/config.toml`, `.github/hooks/copilot-hooks.json`, or `.agents/hooks.json`. See [AI Enforcement Principles](ai/enforcement-principles.md) and [Command Blocking](ai/command-blocking.md).

### 1. Codex CLI (OpenAI)

**Configuration:** `.codex/config.toml`

> **Note**: Project-level dangerous-command hooks under `tools/hooks/ai/` apply to this agent regardless of the per-agent config below. See [AI Enforcement Principles](ai/enforcement-principles.md) and [Command Blocking](ai/command-blocking.md).

Codex CLI directly reads `AGENTS.md` from the project root. The configuration file whitelists common development commands.

**Whitelisted commands:**
- `git` - All git operations
- `gh` - GitHub CLI
- `uv` - UV package manager
- `doit` - Task automation
- File operations: `ls`, `cat`, `tree`, `find`, `grep`, `wc`, `mkdir`

**Setup:**
```bash
# Codex CLI will automatically use .codex/config.toml if present
# Or copy to global config:
cp .codex/config.toml ~/.codex/config.toml

# Initialize or regenerate AGENTS.md with Codex:
codex
/init
```

**Documentation:**
- [Codex CLI Documentation](https://developers.openai.com/codex/cli/)
- [Configuring Codex](https://developers.openai.com/codex/local-config/)
- [Codex Security Guide](https://developers.openai.com/codex/security/)

**Codex parity status:** Codex does not use repo-defined slash commands in this template. Instead, it uses repo-scoped workflow skills checked into `.agents/skills/` and invoked through Codex's built-in skill surface such as `/skills` or explicit mentions like `$codex-plan`, `$codex-implement`, `$codex-review`, `$codex-adversarial-review`, and `$ghi-finalize`. LSP integration is not documented for Codex here. Codex works as a standalone alternative for contributors who prefer the OpenAI CLI. The shared dangerous-command hook at `tools/hooks/ai/block-dangerous-commands.py` applies to Codex via `.codex/config.toml`, and the approval-policy rules remain a secondary defense layer. For the broader workflow picture, see [Slash Commands and Workflows](ai/slash-commands.md).

### 2. Claude Code (Anthropic)

**Configuration:** `.claude/` directory

> **Note**: Project-level dangerous-command hooks under `tools/hooks/ai/` apply to this agent regardless of the per-agent config below. See [AI Enforcement Principles](ai/enforcement-principles.md) and [Command Blocking](ai/command-blocking.md).

Claude Code uses a reference file (`.claude/CLAUDE.md`) that imports `AGENTS.md` and the per-stack rule files:

```
@../AGENTS.md
@./rules/*.md
```

The paths are relative to `.claude/`, which is why they are not bare `@AGENTS.md`.

**Whitelisted commands:**
- `git:*` - All git commands
- `gh:*` - All GitHub CLI commands
- `uv:*` - All uv commands
- `doit:*` - All doit commands
- File operations: `ls`, `cat`, `tree`, `find`, `grep`, `wc`, `mkdir`

**Setup:**
```bash
# Claude Code automatically detects .claude/ directory
# No additional setup needed
```

**Files:**
- `.claude/CLAUDE.md` - Imports `AGENTS.md` and `.claude/rules/*.md`
- `.claude/settings.local.json` - Command permissions
- `.claude/settings.json` - Status line and PreToolUse hooks

**LSP Support (Recommended):**

Claude Code supports Language Server Protocol for enhanced code intelligence:
- Document symbols (functions, classes, variables)
- Go to definition / find references
- Hover information and type checking
- Call hierarchy navigation

**Quick LSP Setup:**
```bash
# 1. Install the LSP plugin from marketplace
/install-plugin @anthropic-ai/claude-code-lsp

# 2. Install development dependencies (includes language server)
doit install_dev

# 3. Enable LSP tool in .envrc.local
echo 'export ENABLE_LSP_TOOL=1' >> .envrc.local
direnv allow

# 4. Start Claude Code
claude
```

For complete setup instructions and troubleshooting, see `.claude/lsp-setup.md` in the repository root.

#### Environment Variables

`.claude/settings.json` ships an `env` block with three Claude Code defaults aimed at token efficiency and session survival on long-running work. These propagate to downstream consumers via the template-sync mechanism, so all projects derived from this template inherit the same defaults.

| Var | Value | Effect | Risk |
| :--- | :--- | :--- | :--- |
| `ENABLE_PROMPT_CACHING_1H` | `1` | Extends prompt cache TTL from 5 minutes to 1 hour. Cuts cost on repeated reads of the same context within a session. | None — pure efficiency flag. |
| `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` | `50` | Auto-compaction triggers at 50% of the context window instead of the default (~92%). Sessions compact earlier, leaving more headroom for the post-compact continuation. | More frequent compaction churn; mitigated by the [PreCompact handoff hook](ai/auto-checkpoint-hook.md) which preserves context across compaction events. |
| `CLAUDE_CODE_SUBAGENT_MODEL` | `claude-sonnet-5` | Subagents (e.g. those spawned by `/claude:implement`) default to Sonnet 5 instead of inheriting the parent's Opus model. | Subagent output quality drops below Opus on hard reasoning tasks. Mitigate per-agent (see below). |

**Per-agent model overrides:**

`CLAUDE_CODE_SUBAGENT_MODEL` is a default. Any agent file under `.claude/agents/` that declares an explicit `model:` in its YAML frontmatter wins:

```yaml
---
name: high-stakes-reviewer
model: claude-opus-5   # overrides the env-var default for this agent only
---
```

Agents without a `model:` line inherit the env-var default. This template's `.claude/agents/implement-worker.md` deliberately does not override — implement-worker runs on Sonnet 5 as an explicit cost/quality trade-off. Future high-stakes subagents (e.g. design review, security review) can opt into Opus on a per-file basis.

**Per-developer overrides:**

To opt out or tune values for your local environment, override them in `.claude/settings.local.json` (already gitignored, used elsewhere in this template for personal config). Example:

```json
{
  "env": {
    "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "75"
  }
}
```

**Cross-references:**

- The 50% autocompact threshold is paired with the [PreCompact handoff hook](ai/auto-checkpoint-hook.md) — earlier compaction has lower cost because the hook preserves context across compaction events automatically.
- For operators who need more aggressive token reduction, see [AI Agent Token-Efficiency Add-Ons](ai/token-efficiency-add-ons.md) — a catalogue of opt-in external tools (RTK, Headroom, Caveman) with tipping-point guidance and trust caveats.

### 3. GitHub Copilot CLI

**Configuration:** `.copilot/` directory

> **Note**: Project-level dangerous-command hooks under `tools/hooks/ai/` apply to this agent regardless of the per-agent config below. See [AI Enforcement Principles](ai/enforcement-principles.md) and [Command Blocking](ai/command-blocking.md).

GitHub Copilot CLI reads `AGENTS.md` directly and discovers project skills from `skills/` directories — `.github/skills/`, `.agents/skills/`, and `.claude/skills/` (per `@github/copilot` SDK `sdk/index.d.ts`). For skills it reads no `commands/` directory, though it does load single-file commands from `.claude/commands/` — a separate mechanism, so Claude's command files also surface in Copilot (#753). Self-action and cross-agent bridge skills (`/copilot-plan`, `/copilot-implement`, `/copilot-review`, `/copilot-adversarial-review`, and one cross-agent bridge `/<target>-<action>` per target and action) live under `.github/skills/<target>-<action>/SKILL.md`. The `.github/skills/` location is chosen specifically because it's the only Copilot project skill path that Claude does **not** also read — placing bridges there avoids duplicating slash commands in Claude. Hyphen naming is structural — skill names are derived from directory names and cannot contain colons. Copilot also natively discovers per-stack instruction files from `.github/instructions/*.instructions.md`; see [`.github/instructions/README.md`](../../.github/instructions/README.md) for the scaffold and format.

**Hook wiring:**

The dangerous-command hook is wired in `.github/hooks/copilot-hooks.json`:
```json
{
  "version": 1,
  "hooks": {
    "preToolUse": [
      {
        "type": "command",
        "bash": "python3 ../../tools/hooks/ai/block-dangerous-commands.py",
        "cwd": ".github/hooks",
        "timeoutSec": 10
      }
    ]
  }
}
```

**Setup:**
```bash
# Copilot CLI automatically picks up .github/hooks/copilot-hooks.json
# and reads AGENTS.md; no additional setup needed.
copilot
```

**Files:**
- `.copilot/README.md` - Description of the Copilot CLI config directory
- `.github/hooks/copilot-hooks.json` - `preToolUse` hook wiring
- `.github/instructions/*.instructions.md` - Copilot-native per-stack instruction files (auto-discovered)
- `.github/instructions/README.md` - Instruction-file scaffold and format reference
- `.github/skills/<target>-<action>/SKILL.md` — Copilot-host workflow skills (one self-action skill per action plus one bridge per target and action; placed under `.github/skills/` so Claude does not also surface them)
- `.agents/skills/` — interoperable Codex skill path, also read by Copilot (provides `/ghi-finalize`, `/ghi-status`, `/multi-*`)
- `.claude/agents/implement-worker.md` — Shared subagent definition

**Documentation:**
- [GitHub Copilot CLI](https://github.com/github/copilot-cli)
- [Copilot CLI Hooks](https://docs.github.com/en/copilot/how-tos/use-copilot-for-common-tasks/use-copilot-in-the-cli)

**Copilot parity status:** Copilot CLI exposes every cross-agent matrix cell for its host under `.github/skills/<target>-<action>/SKILL.md` — a self-action skill per action (`/copilot-plan`, `/copilot-implement`, `/copilot-review`, `/copilot-adversarial-review`) plus a bridge per (target, action) pair (`/{claude,codex,antigravity}-{plan,implement,review,adversarial-review}`). The bridge bodies cannot be shared with Claude because each target CLI requires a different invocation (`claude -p`, `codex -a never --dangerously-bypass-hook-trust exec`, `agy -p`). The other workflow skills (`/ghi-finalize`, `/ghi-status`, `/multi-*`) come from `.agents/skills/`. The `.github/skills/` location was chosen because it's the only Copilot project skill path that Claude does not also read — bridges there do not surface as duplicate slash commands in Claude. Hyphen naming is a structural constraint (skill names cannot contain colons), not a stylistic choice. The project-level hooks under `tools/hooks/ai/` apply to Copilot via `.github/hooks/copilot-hooks.json` — see [Command Blocking](ai/command-blocking.md). For the broader slash-command picture, see [Slash Commands and Workflows](ai/slash-commands.md).

### 4. Antigravity CLI (Google)

**Configuration:** `.agents/` (shared customization root with Codex)

> **Note**: Project-level dangerous-command hooks under `tools/hooks/ai/` apply to this agent regardless of the per-agent config below. See [AI Enforcement Principles](ai/enforcement-principles.md) and [Command Blocking](ai/command-blocking.md).

Antigravity CLI (`agy`) directly reads `AGENTS.md` from the project root as always-on rules and discovers repo-scoped skills from `.agents/skills/<name>/SKILL.md` — the same `SKILL.md` format Codex uses, activated by the `description:` frontmatter.

**Setup:**
```bash
# Install (macOS/Linux):
curl -fsSL https://antigravity.google/cli/install.sh | bash

# Launch in the repo (trust the workspace when prompted so .agents/ loads):
agy
```

**Antigravity parity status:** Antigravity does not use repo-defined slash commands; its workflow skills (`antigravity-plan`, `antigravity-implement`, `antigravity-review`, `antigravity-adversarial-review`) live in `.agents/skills/` and activate by description match. The shared dangerous-command hook at `tools/hooks/ai/block-dangerous-commands.py` applies to Antigravity via `.agents/hooks.json` (a `PreToolUse` matcher on `run_command`/`write_to_file`); unlike the other agents it blocks by printing `{"decision":"deny"}` on stdout, which holds even under `--dangerously-skip-permissions`. `agy` only loads workspace customizations for an active/trusted workspace, so headless `agy -p` runs need `--add-dir <repo-root>`. Cross-agent delegation (both directions, reusing Codex's host-agnostic `delegate-*` skills) and the `/multi-*` orchestrators fully support `agy`. For the broader workflow picture, see [Slash Commands and Workflows](ai/slash-commands.md).

### 5. Other AI Tools

The `AGENTS.md` file serves as general-purpose documentation for any AI coding assistant:

- **Cursor**: Reference in `.cursorrules`
- **Codeium**: Reference in project settings
- **Tabnine**: Reference in configuration

> **Note**: For the slash commands and dual-agent workflow this template ships with, see [Slash Commands and Workflows](ai/slash-commands.md).

## AGENTS.md - Universal Context File

The `AGENTS.md` file provides comprehensive project context including:

- Repository structure and architecture
- Development workflows and commands
- Code style and conventions
- Testing expectations
- CI/CD workflows
- Troubleshooting guides

This file is:
- **Read directly** by Codex CLI, GitHub Copilot CLI, and Antigravity CLI
- **Imported** by Claude Code via `.claude/CLAUDE.md`
- **Referenceable** by other AI tools

## Context files and precedence

This template ships several files that influence agent behavior. They fall into two categories: **context/instruction files** (markdown) and **settings/config files** (JSON or TOML). Knowing which is which — and which one wins on conflict — matters when adapting the template for a new project.

**File inventory:**

- **`AGENTS.md`** (project root, ~20 KB) — universal source of truth for architecture, workflow, tooling hierarchy, and security rules. Read directly by Codex CLI, GitHub Copilot CLI, and Antigravity CLI; imported by Claude Code via `@../AGENTS.md` in `.claude/CLAUDE.md`.
- **`.claude/CLAUDE.md`** (~2 KB) — Claude-specific complement. First line is `@../AGENTS.md`, which imports the universal rules; the rest adds Claude-specific layers (token-efficiency guidance, the mandatory TodoWrite plan-test-code loop, the development workflow reminder, and the commit workflow reminder).
- **`.copilot/README.md`** — describes the Copilot CLI config directory. Copilot CLI reads `AGENTS.md` directly, discovers its workflow skills from `.github/skills/` (and the interoperable `.agents/skills/`), and uses `.github/instructions/*.instructions.md` for Copilot-native per-stack instruction files.
- **`.codex/config.toml`** — Codex approval policy file (TOML). Not a context file; configures permissions only. Codex reads `AGENTS.md` directly for instructions.
- **`.claude/settings.json`** — Claude PreToolUse hooks and statusline configuration. Committed.
- **`.claude/settings.local.json`** — local Claude permissions overlay. Not committed.
- **`.github/hooks/copilot-hooks.json`** — Copilot CLI `preToolUse` hook wiring that routes shell commands through `tools/hooks/ai/block-dangerous-commands.py`.

**Precedence rules:**

- All four agents treat `AGENTS.md` as the architectural and workflow source of truth.
- Agent-specific markdown files (for example `.claude/CLAUDE.md`) **complement** `AGENTS.md` — they cover behaviors specific to that agent's interaction model and do not override the universal rules.
- Settings/config files (`.codex/config.toml`, `.claude/settings*.json`, `.github/hooks/copilot-hooks.json`, `.agents/hooks.json`) configure **permissions and tooling**, not workflow rules. They cannot grant an agent permission to do something `AGENTS.md` forbids.
- Project-level hooks under `tools/hooks/ai/` apply to all agents and cannot be bypassed by per-agent config. This is the strongest layer.

**Conflict resolution:** if an agent-specific file conflicts with `AGENTS.md`, `AGENTS.md` wins for cross-cutting concerns (workflow, architecture, security). An agent-specific file may further restrict its own agent's behavior, but it should not loosen a universal rule.

## Customization

### For Your Project

When using this template for a new project:

1. **Update AGENTS.md**: Customize project-specific details
2. **Adjust permissions**: Modify `.codex/config.toml` and `.claude/settings.local.json` as needed
3. **Add project commands**: Include any custom scripts or tools

### Adding New Commands

**Codex CLI** (`.codex/config.toml`):
```toml
approval_policy = "on-request"

[features]
hooks = true

[[hooks.PreToolUse]]
matcher = "^Bash$"

[[hooks.PreToolUse.hooks]]
type = "command"
command = 'python3 "$(git rev-parse --show-toplevel)/tools/hooks/ai/block-dangerous-commands.py"'
timeout = 30
statusMessage = "Checking Bash command"
```

Use the shared hook script to control dangerous command patterns. The older
`[[approval_policy]]` command-rule examples are not part of the current Codex
config schema.

**Claude Code** (`.claude/settings.local.json`):
```json
{
  "permissions": {
    "allow": [
      "Bash(your-command:*)"
    ]
  }
}
```

**GitHub Copilot CLI** (`.github/hooks/copilot-hooks.json`):

Copilot CLI does not use a per-command allowlist — the dangerous-command hook blocks unsafe patterns; everything else is allowed. To adjust what is blocked, edit the shared hook at `tools/hooks/ai/block-dangerous-commands.py` (which applies to Claude, Copilot, Codex and Antigravity alike). New workflow skills added under `.github/skills/<name>/SKILL.md` are automatically discovered by Copilot CLI — no additional configuration is needed.

## Security Considerations

All configuration files are set up with security in mind.

> **Note**: This template enforces security rules in code and settings, not just instructions. See [AI Enforcement Principles](ai/enforcement-principles.md) for details.

> **Note**: For the architectural rules AI agents must follow when generating code, see [Architectural Conventions](ai/architectural-conventions.md).

**Whitelisted Operations:**
- Read-only file operations
- Safe git operations (status, diff, log, add, commit, push, pull)
- Package management (uv)
- Testing and linting (pytest, ruff, mypy)
- Task automation (doit)

**Protected Information:**
- API keys and tokens are excluded from environment variables
- No dangerous operations (rm -rf, format, etc.) are pre-approved
- Network operations require approval in some modes

## Troubleshooting

### Codex CLI

**Commands still prompt for approval:**
```bash
# Check current config
cat ~/.codex/config.toml

# Copy project config to global
cp .codex/config.toml ~/.codex/config.toml

# Or use project-specific config
codex --config .codex/config.toml
```

**Regenerate AGENTS.md:**
```bash
codex
/init
```

### Claude Code

**Permissions not working:**
- Ensure `.claude/settings.local.json` exists
- Check file is valid JSON
- Restart Claude Code

**Context not loading:**
- Verify `.claude/CLAUDE.md` contains `@../AGENTS.md` and `@./rules/*.md`
- Check `AGENTS.md` exists in project root

### Copilot CLI

**Hook not firing (dangerous commands going through):**
- Verify `.github/hooks/copilot-hooks.json` exists and is valid JSON
- The hook uses a relative `bash` path (`python3 ../../tools/hooks/ai/block-dangerous-commands.py`) and a `cwd` of `.github/hooks`; both must match your layout
- Run `doit test` to confirm the shared hook script still passes its test suite
  (`tests/test_hook_dangerous_command_matrix.py` — 134 block/allow cases, collected by CI)

**Slash commands not appearing:**
- Copilot CLI discovers skills only from `skills/` paths (`.github/skills/`, `.agents/skills/`, `.claude/skills/`) — make sure the directory exists and each skill is a `<name>/SKILL.md` with `name:` and `description:` frontmatter
- Single-file commands under `.claude/commands/` are loaded by a separate mechanism; `.copilot/commands/` is read by neither
- Restart the Copilot CLI session after adding new skill or command files

**`.copilot/` auto-detection:**
- The `.copilot/` directory exists primarily to document Copilot-specific wiring; Copilot CLI does not require any config files there
- Copilot CLI also auto-discovers `.github/instructions/*.instructions.md` without any import or directive
- If you move the repository, Copilot CLI still loads `AGENTS.md` from the repo root, the hook from `.github/hooks/copilot-hooks.json`, and instruction files from `.github/instructions/`

## Resources

### Codex CLI
- [Codex CLI](https://developers.openai.com/codex/cli/)
- [Codex Configuration](https://developers.openai.com/codex/local-config/)
- [Codex Security Guide](https://developers.openai.com/codex/security/)
- [Codex CLI Reference](https://developers.openai.com/codex/cli/reference/)

### Claude Code
- [Claude Code Documentation](https://claude.com/claude-code)
- [Claude Agent SDK](https://github.com/anthropics/claude-code)

### GitHub Copilot CLI
- [GitHub Copilot CLI](https://github.com/github/copilot-cli)
- [Using Copilot in the CLI](https://docs.github.com/en/copilot/how-tos/use-copilot-for-common-tasks/use-copilot-in-the-cli)
- [GitHub Copilot](https://github.com/features/copilot)

### General AI Coding
- [Cursor](https://cursor.sh/)
- [Codeium](https://codeium.com/)

---

**Note**: The `.codex/`, `.claude/`, `.copilot/`, and `.agents/` directories should be committed to version control to share consistent AI assistant configuration across the team. .local files should not be committed.
