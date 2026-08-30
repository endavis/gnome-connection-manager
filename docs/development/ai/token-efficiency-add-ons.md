---
title: AI Agent Token-Efficiency Add-Ons
description: Opt-in catalogue of external tools for reducing token usage in Claude Code sessions
audience:
  - contributors
  - ai-agents
  - operators
tags:
  - ai
  - token-efficiency
  - add-ons
---

# AI Agent Token-Efficiency Add-Ons

## Purpose

This page is an **opt-in menu** for operators of larger downstream projects who hit token-cost or
session-length pain points. The baseline defaults (env-var settings for Claude) are
already on for everyone — see [AI Agent Setup Guide](../AI_SETUP.md).
Add-ons here are additional investments: each has setup cost, operational burden, and in some cases
a trust trade-off. Read the tipping-point guidance before adopting any of them.

Most projects built on this template do not need these. The audience is operators running
multi-hour sessions against large codebases where the baseline defaults are not enough.

## When to consider an add-on

Adopt an add-on when one or more of the following apply:

- Sessions end in autocompact more than once per workday.
- Shell command output (test runs, `find` output, diff blobs) dominates context billing.
- AGENTS.md rules drift noticeably in long sessions — the agent ignores a documented rule late
  in a conversation that it respected at the start.
- You are running concurrent agents on a shared API key and token-rate costs are measurable.
- You are working in a regulated environment and want auditable compression before tokens leave
  the machine.

## RTK (Rust Token Killer)

**Repo:** [github.com/rtk-ai/rtk](https://github.com/rtk-ai/rtk)

RTK is a shell-output compressor. It intercepts the stdout of commands you run through the
Claude Code terminal, strips redundant whitespace and repeated lines, and injects a compact
representation into the context instead of the raw output. It is written in Rust for low-overhead
interception and ships as a standalone binary as well as bundled inside Headroom (see below).

**Tipping-point:** adopt RTK when test-suite output, build logs, or `find`/`grep` results are a
visible fraction of your context bills. If `pytest` output is 200 lines per run and you run tests
frequently in a session, RTK compresses that cost significantly.

**Per-CLI applicability:**

| CLI | Works? |
| :--- | :--- |
| Claude Code | Yes |
| GitHub Copilot CLI | Yes |
| Codex CLI | Yes |

**Install (standalone):**

```bash
# Install the Rust binary
cargo install rtk

# Wrap your shell session
rtk -- bash
```

Once the shell is wrapped, every command Claude Code (or you) runs through the terminal has its
output compressed automatically. No changes to `.claude/settings.local.json` are required.

**Trust caveat:** RTK operates entirely on your machine and does not proxy the API — it rewrites
the text that ends up in the context, but it never reads or forwards your API key. No significant
trust concern beyond normal Rust binary installation hygiene.

## Headroom

**Repo:** [github.com/chopratejas/headroom](https://github.com/chopratejas/headroom)

Headroom is a local proxy that sits between Claude Code and the Anthropic API. It intercepts
outbound API requests and compresses conversation history, system prompts, `CLAUDE.md` content,
and tool-call outputs **before they leave the machine**, reducing the token count sent upstream.
It also ships RTK as a bundled dependency so you get both tools in one install.

**Tipping-point:** adopt Headroom when context bills are high across the board — not just shell
output but also system prompts and conversation history. It is the most aggressive compression
option and gives you the broadest reduction.

> **Trust caveat:** Headroom is a **MITM proxy** in your API path. All requests to the Anthropic
> API, including your API key and full conversation content, pass through Headroom's local process.
> **Read the source before adopting Headroom on shared or employer-owned codebases.** Confirm that
> the binary you run matches the source at the tagged version and that no network forwarding is
> configured. This is not a warning against Headroom itself — it is a standard due-diligence step
> for any tool that sits in the API path.

**Per-CLI applicability:**

| CLI | Works? |
| :--- | :--- |
| Claude Code | Yes |
| GitHub Copilot CLI | No (uses GitHub's Copilot endpoint, not Anthropic) |
| Codex CLI | No (uses OpenAI endpoint) |

**Install:**

```bash
# Install Headroom (bundles RTK)
cargo install headroom

# Start the local proxy (default port 8082)
headroom proxy

# Configure Claude Code to route through it
```

**`.claude/settings.local.json` snippet:**

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://localhost:8082"
  }
}
```

This is a **local-only** settings file (not committed). The
`CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` env var documented in
[AI Agent Setup: Environment Variables](../AI_SETUP.md#environment-variables) continues to work alongside Headroom —
Headroom compresses tokens in flight while autocompact still triggers at your configured threshold.

## Caveman

**Repo:** [github.com/JuliusBrussee/caveman](https://github.com/JuliusBrussee/caveman)

Caveman is a Claude Code plugin that injects terse-style instructions at `SessionStart` and on
**every `UserPromptSubmit` event**. It tells the model to prefer brevity: shorter responses,
minimal prose, table-first formatting. Because it fires every turn, injected style survives
autocompact and context drift — the model is reminded on each prompt, not just at session start.

**Tipping-point:** adopt Caveman when you observe that Claude's response verbosity increases over
a long session, or when you want a consistent terse baseline across all sessions without relying
on ad-hoc prompting.

**Caveman is complementary to `AGENTS.md`, not a replacement.** `AGENTS.md` is rich
project-specific content (workflows, architecture, tooling rules) that is auto-loaded once per
session. Caveman injects narrow style instructions on every turn. They target different things.
Stacking is reasonable — but read the intensity trade-off table below before choosing a level.

### Intensity levels

| Level | What it enforces | Risk with project rules |
| :--- | :--- | :--- |
| `lite` | Terse phrasing, concise bullet points | Low — plays well with AGENTS.md; prose in issue bodies and PR descriptions is unaffected |
| `full` | Short answers, table-first, minimal explanation | Medium — may shorten ADR rationale, PR descriptions, commit messages below template minimums |
| `ultra` | Extreme brevity, single-sentence answers | High — likely to conflict with rules requiring structured long-form artefacts (issue bodies, ADR decisions) |

**Recommendation: start with `lite`.** It reduces verbosity in conversational turns without
clashing with template rules that require structured prose in artefacts. Move to `full` only
after confirming your workload does not produce artefacts that need to meet a length standard.

**Per-CLI applicability:**

| CLI | Works? |
| :--- | :--- |
| Claude Code | Yes (native plugin system) |
| GitHub Copilot CLI | No |
| Codex CLI | No |

**Install and enable:**

Follow the installation steps in the Caveman repo. Once installed, enable it at `lite` intensity
in your local Claude Code settings:

**`.claude/settings.local.json` snippet:**

```json
{
  "plugins": {
    "caveman": {
      "intensity": "lite"
    }
  }
}
```

This is a **local-only** file (not committed). Do not commit Caveman plugin config — intensity
preference varies by operator and can conflict with other contributors' expectations.

## Bash raw-tool ban (opt-in)

This hook enforces what `AGENTS.md` already asks for: prefer native file tools (`Read`, `Grep`,
`Glob`, `Edit`, `Write`) over their raw shell equivalents. When an agent defects to `Bash`, the
raw output bypasses every other token-efficiency control and lands in context uncompressed.

**What it blocks:**

- Leading banned commands: `cat`, `head`, `tail`, `find`, `grep`, `rg`, `wc`

Each block message names the offending command, suggests the native replacement, and reminds the
agent about the escape hatch.

**Native tool replacements:**

| Blocked command | Use instead |
| :--- | :--- |
| `cat` / `head` / `tail` | `Read` |
| `find` | `Glob` |
| `grep` / `rg` | `Grep` |
| `wc` | `Read` (then count in the result) |

**Opt-in via `.claude/settings.local.json`:**

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "python3 $CLAUDE_PROJECT_DIR/tools/hooks/ai/bash-ban-raw-tools.py"
          }
        ]
      }
    ]
  }
}
```

This goes in `.claude/settings.local.json` (not committed) — each operator opts in individually.
Do **not** add it to the committed `.claude/settings.json`.

**Escape hatch:**

```bash
mkdir -p tmp/agents/claude && touch tmp/agents/claude/bash-raw-unlock
```

Run this from the project root. Allows all banned commands for 10 minutes. The file auto-expires —
no cleanup needed. Useful when you need a one-off raw shell command without disabling the hook
permanently.

The unlock file is scoped to the project directory, so enabling the escape hatch in one project
does not affect any other project running concurrently on the same machine. If you work across
multiple projects, you must re-touch the file in each project root where you want raw commands
allowed.

**Why disabled by default:** humans share the repo. Raw shell commands are legitimate in human
workflows. The hook is only beneficial when an AI agent is the primary operator of the terminal.
Enable it locally for AI-heavy sessions; disable it when you are working interactively.

**Related:** the always-on dangerous-command hook (committed in `.claude/settings.json`) is
documented in [AI Command Blocking](command-blocking.md). The two hooks are complementary: the
dangerous-command hook blocks security-relevant patterns for everyone; this hook enforces
token-efficiency discipline only for operators who opt in.

## Codebase Memory MCP gate (opt-in)

The [Codebase Memory MCP server](https://github.com/DeusData/codebase-memory-mcp) (CBM) builds a
tree-sitter knowledge graph of your repository and exposes it as MCP tools
(`search_graph`, `trace_path`, `get_architecture`, `get_code_snippet`, `index_repository`,
`detect_changes`). Structural queries — "where is function X defined?", "what calls module Y?" —
cost orders of magnitude fewer tokens answered by the graph than by reading files directly.

Without enforcement, models default to trained behaviour: `Read`/`Grep`/`Glob` on source files.
The three hooks below close that loop.

### Three-hook design

| Hook | Event | What it does |
| :--- | :--- | :--- |
| `cbm-code-discovery-gate.py` | `PreToolUse` on `Read\|Grep\|Glob` | Blocks code-discovery on source files unless a CBM tool ran recently or the target is in the allow-list |
| `cbm-mcp-marker.py` | `PostToolUse` on CBM tool prefix | Touches a sidecar marker file, opening a 120s window during which the gate passes through |
| `cbm-session-reminder.py` | `SessionStart` on `compact\|resume\|clear` | Re-injects the CBM protocol into context so the model does not forget the discipline after autocompact |

### Allow-list

The gate passes through automatically for paths that CBM cannot help with:

| Allow-list rule | What it covers |
| :--- | :--- |
| Extensions `.json .yaml .yml .md .toml .lock .txt .env .sh` | Config, docs, lockfiles |
| Path contains `.claude/`, `CLAUDE.md`, `settings`, `hooks/` | Project metadata and hooks |
| Path contains `tests/` or `_test.` | Test files |

Source-code files (`.py`, `.ts`, `.js`, `.go`, etc.) are **not** in the allow-list. A
`Grep`/`Glob` with no `path` argument (whole-repo search) is also always gated — that is exactly
the case CBM's `search_graph` is optimised for.

### Read-after-CBM workflow

1. Agent calls a CBM tool (e.g. `mcp__codebase-memory__search_graph`).
2. `cbm-mcp-marker.py` touches `/tmp/cbm-mcp-used-{ppid}` (scoped to the Claude Code session by
   parent PID).
3. Within 120 seconds, `Read`/`Grep`/`Glob` on source files passes through the gate.
4. After 120 seconds the window closes — the next code-discovery call requires another CBM call
   first.

The 120-second window is deliberately short: long enough for a focused follow-up read, short
enough to prevent the gate from becoming permanently open after a single CBM call at session start.

### Setup

**Prerequisites:** install and configure the CBM MCP server. Follow the upstream instructions at
[github.com/DeusData/codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp). The
hooks in this template assume the server is named `codebase-memory` in your MCP config.

**Step 1** — Index the repository once:

```bash
# Inside a Claude Code session with CBM MCP wired:
mcp__codebase-memory__index_repository
```

**Step 2** — Wire the three hooks in `.claude/settings.local.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Read|Grep|Glob",
        "hooks": [
          {
            "type": "command",
            "command": "python3 $CLAUDE_PROJECT_DIR/tools/hooks/ai/cbm-code-discovery-gate.py"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "mcp__codebase-memory__.*",
        "hooks": [
          {
            "type": "command",
            "command": "python3 $CLAUDE_PROJECT_DIR/tools/hooks/ai/cbm-mcp-marker.py"
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "matcher": "compact|resume|clear",
        "hooks": [
          {
            "type": "command",
            "command": "python3 $CLAUDE_PROJECT_DIR/tools/hooks/ai/cbm-session-reminder.py"
          }
        ]
      }
    ]
  }
}
```

This goes in `.claude/settings.local.json` (not committed) — each operator opts in individually.
Do **not** add it to the committed `.claude/settings.json`.

**Step 3** — Refresh the graph when the codebase changes materially:

```bash
mcp__codebase-memory__detect_changes   # check if refresh is needed
mcp__codebase-memory__index_repository # re-index if needed
```

### Trust caveats

CBM indexes the repository by parsing source files with tree-sitter. The resulting graph lives
locally in whatever storage backend the CBM server is configured with. Key considerations:

- **Graph staleness:** the graph reflects the codebase at the time of the last `index_repository`
  call. After significant changes (new modules, major refactors), call `detect_changes` and
  re-index before relying on graph results. The gate passes through regardless of graph freshness —
  it enforces that a CBM tool *runs*, not that the graph is accurate.
- **Server trust:** CBM reads your source files to build the graph. Apply the same due-diligence
  you would to any tool that reads your codebase. Read the source and confirm no network egress
  before using on sensitive or employer-owned codebases.
- **MCP server name:** if your CBM server is configured under a different name than
  `codebase-memory`, update the `PostToolUse` matcher (e.g. `mcp__my-cbm__.*`) to match. The
  hook itself is tool-name-agnostic; only the matcher needs updating.

**Why disabled by default:** CBM requires an external MCP server that each operator installs and
configures separately. Wiring these hooks in committed settings would break every contributor who
has not installed CBM.

## context-mode MCP wrappers (opt-in)

The [context-mode MCP](https://github.com/mksglu/context-mode) intercepts tool outputs, runs
commands in a sandboxed environment, indexes the full output into a local BM25 knowledge base, and
returns only a compact summary to the model. Claude can call `ctx_search` later to retrieve detail.
This prevents large tool outputs — `pytest -v` over thousands of tests, `terraform plan`, verbose
`kubectl describe` — from flooding the conversation context and consuming tokens until the next
autocompact event.

context-mode wires up via four lifecycle hooks (`PreToolUse`, `PostToolUse`, `PreCompact`,
`SessionStart`), each invoking `context-mode hook claude-code <event>`. Without thin wrappers,
operators must hand-wire all four — error-prone, and easy to omit the `PreCompact`/`SessionStart`
events that handle index persistence across compaction cycles.

### Five-hook design

| Hook | Event | What it does |
| :--- | :--- | :--- |
| `context-mode-pretooluse.py` | `PreToolUse` (no matcher) | Forwards every PreToolUse event to the context-mode CLI for interception |
| `context-mode-posttooluse.py` | `PostToolUse` (no matcher) | Forwards every PostToolUse event so outputs are indexed and summarised |
| `context-mode-precompact.py` | `PreCompact` | Persists the BM25 index before autocompact so it survives context resets |
| `context-mode-sessionstart.py` | `SessionStart` | Restores the index when a session resumes after compaction |
| `context-mode-test-runner-reminder.py` | `PreToolUse` on `Bash` | Advisory only — reminds Claude to prefer `ctx_batch_execute` for test runs |

Each forwarder uses `shutil.which("context-mode")` to detect non-installation and exits 0 silently.
Non-installation is a no-op, not an error.

### Setup

**Prerequisites:** install the context-mode CLI and configure the MCP server. Follow the upstream
instructions at [github.com/mksglu/context-mode](https://github.com/mksglu/context-mode).

**Step 1** — Wire all five hooks in `.claude/settings.local.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 $CLAUDE_PROJECT_DIR/tools/hooks/ai/context-mode-pretooluse.py"
          }
        ]
      },
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "python3 $CLAUDE_PROJECT_DIR/tools/hooks/ai/context-mode-test-runner-reminder.py"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 $CLAUDE_PROJECT_DIR/tools/hooks/ai/context-mode-posttooluse.py"
          }
        ]
      }
    ],
    "PreCompact": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 $CLAUDE_PROJECT_DIR/tools/hooks/ai/context-mode-precompact.py"
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 $CLAUDE_PROJECT_DIR/tools/hooks/ai/context-mode-sessionstart.py"
          }
        ]
      }
    ]
  }
}
```

This goes in `.claude/settings.local.json` (not committed) — each operator opts in individually.
Do **not** add it to the committed `.claude/settings.json`.

**Step 2** — Verify the wiring with a manual smoke test: install a fake `context-mode` shim that
logs its argv to stderr, wire `context-mode-pretooluse.py` as above, trigger any tool call, and
confirm stderr shows `context-mode hook claude-code PreToolUse` with the original stdin forwarded.

### ctx_batch_execute workflow

When `context-mode` MCP is active, prefer `ctx_batch_execute` for multi-command sequences (test +
lint + typecheck) rather than running each command in a separate `Bash` call. `ctx_batch_execute`
submits all commands together, indexes the combined output into the BM25 store, and returns a
compact summary. Use `ctx_search` to retrieve specific detail from that summary on demand.

This is most valuable for test runs on large projects where `pytest -v` output can easily exceed
tens of thousands of lines.

### Trust caveats

context-mode claims to run commands in a sandboxed environment and maintain a local BM25 index with
no network egress. Key considerations before adopting:

- **Verify upstream:** read the source at [github.com/mksglu/context-mode](https://github.com/mksglu/context-mode)
  to confirm no network egress before using on sensitive or employer-owned codebases.
- **Local index:** the BM25 index lives on disk in whatever path context-mode configures. Treat it
  with the same care as any file containing code excerpts.
- **Index freshness:** the index reflects commands run since the last `SessionStart` restore. After
  a session that skips the hooks, `ctx_search` may return stale or empty results.

**Why disabled by default:** context-mode intercepts every tool call via `PreToolUse` and
`PostToolUse` with no matcher restriction. Wiring these hooks in committed settings would add
latency and context-mode dependency for every contributor regardless of whether they have installed
the CLI.

## Session-survival of project rules

This section documents the **pattern** that Caveman uses, so you can apply it to any narrow rule
that needs to survive long sessions — not just terse style.

### The two injection mechanisms

Claude Code offers two ways to get instructions in front of the model:

| | Auto-load (`CLAUDE.md` / `AGENTS.md`) | Per-turn injection (`UserPromptSubmit` hook) |
| :--- | :--- | :--- |
| Loaded | Once at session start | Every user message |
| Survives autocompact / context drift | No | Yes |
| Best for | Rich, project-specific content | Narrow rules that "the model knows but forgets" |

**Auto-load** is how this template ships `AGENTS.md` — comprehensive project context loaded once
per session. It works well for the bulk of project rules. **The failure mode is drift**: after an
autocompact event, or deep in a long conversation, the model may stop honoring a specific rule
even though `AGENTS.md` is still nominally in context.

**Per-turn injection** fires on every `UserPromptSubmit` event. It adds a small amount of text to
every message, but that text is always present, always current, and always wins against drift.
Caveman uses this mechanism for terse style. `cbm-session-reminder` (from the CBM tooling) uses
it for protocol reminders — ensuring that CBM conventions are active throughout a session
regardless of how many autocompact events have occurred.

### When to use this pattern yourself

The `UserPromptSubmit` hook is a reusable technique. If you have a narrow rule that you observe
the model forgetting mid-session, wrapping it in a `UserPromptSubmit` hook is often more reliable
than repeating it in `AGENTS.md`. Good candidates:

- A naming convention the model tends to ignore late in sessions.
- A formatting rule for a specific artefact type.
- A reminder to use `doit` instead of raw `git`/`gh` for a particular class of operation.

The hook lives in `.claude/settings.json` (committed) or `.claude/settings.local.json`
(local-only). Keep injected text short — per-turn injection costs tokens on every message, so
verbosity here works against the goal.

### Per-stack rule files (third mechanism)

A third application of the same pattern is **small per-stack rule files** imported into
`.claude/CLAUDE.md` via the `@import` directive. Where per-turn injection is best for style rules that must survive every
autocompact event, per-stack rule files are best for **narrow, domain-specific self-checks** that
only apply when the agent is doing a specific class of work (code generation, database migrations,
API contract changes, etc.).

Each rule file is skill-gated, capped at 30 lines, and built from documented observed failures —
not from generic advice. The template ships one such rule file
(`typing-branch-narrowing`) and loads it: `.claude/CLAUDE.md` carries a live
`@./rules/*.md` glob import.

See [`.claude/rules/README.md`](../../../.claude/rules/README.md) for the pattern, file structure,
and a worked example.

GitHub Copilot has a native equivalent: **`.github/instructions/NAME.instructions.md`** files with
`applyTo:` YAML frontmatter for path-based gating. No import directive is needed — Copilot
auto-discovers all `*.instructions.md` files in `.github/instructions/`. The body format (skill
gate, numbered self-checks, observed-failures footer, ≤30 lines) is identical to the Claude
variant. The key contrast is the load mechanism:

| CLI | Directory | Load mechanism |
| :--- | :--- | :--- |
| Claude Code | `.claude/rules/` | `@./rules/*.md` in `.claude/CLAUDE.md` |
| GitHub Copilot | `.github/instructions/` | Native auto-discovery (no directive needed) |
| Codex CLI | `.agents/skills/<name>/` | `description:` frontmatter is the skill-gate trigger |

Claude Code cannot read `.github/instructions/` files; this format is Copilot-native only. See [`.github/instructions/README.md`](../../../.github/instructions/README.md)
for the full pattern and a worked example.

Codex CLI uses a different mechanism: the `description:` field in a skill's YAML frontmatter acts
as the skill-gate trigger — Codex auto-loads the skill when the task description matches. There is
no `@import` directive. See [`.agents/skills/README.md`](../../../.agents/skills/README.md) for the
full pattern and a worked example.

## Related primitives in this template

These are not add-ons (they ship with the template) but they interact with the tools above:

- **`/checkpoint` and `/restore`** — session-state preservation commands. When a session is
  about to hit its context limit, `/checkpoint` writes a portable state file and `/restore`
  reconstructs context in a new session. Complements all three add-ons above. See
  [Slash Commands and Workflows](slash-commands.md).
- **Env-var defaults** — `ENABLE_PROMPT_CACHING_1H`, `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`, and
  `CLAUDE_CODE_SUBAGENT_MODEL` are already set via `.claude/settings.json`. Headroom and Caveman
  layer on top of these defaults, not instead of them. See
  [AI Agent Setup: Environment Variables](../AI_SETUP.md#environment-variables).
- **PreCompact handoff hook** — ships with this template. Autocompact events now synthesize a
  checkpoint automatically to `tmp/checkpoints/{inv_epoch}-auto-precompact.md` and the
  `SessionStart` hook restores it into the next session, reducing context loss without any manual
  `/checkpoint` invocation. See [Auto-Checkpoint and Session-Restore Hooks](auto-checkpoint-hook.md).
## Out of scope

- No code is shipped here. All three tools are external; install them from their respective repos.
- Equivalent add-ons for Codex CLI and GitHub Copilot CLI. Most of these tools are Claude Code-specific. RTK is the notable exception with universal support.
- Shipping tool configuration in this template's committed files. All snippets above go into
  `.claude/settings.local.json` (not committed) to keep individual operator preferences local.
