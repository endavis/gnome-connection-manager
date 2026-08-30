---
title: LSP Tool and Diagnostic Noise
description: What the LSP tool gives an AI agent, why pyright diagnostics arrive stale, and the two opt-outs agents can flip on themselves
audience:
  - contributors
  - ai-agents
tags:
  - ai
  - lsp
  - pyright
---

# LSP Tool and Diagnostic Noise

Claude Code (v2.0.74+) ships an `LSP` tool backed by the `pyright-lsp@claude-plugins-official` plugin. The tool itself is a navigation aid; the plugin layered on top of it is also responsible for a *separate* side channel that auto-injects pyright diagnostics into conversation context after edits. The two flows have very different cost profiles, and conflating them is what produces the "agent keeps chasing errors that aren't really errors" pattern.

## What the `LSP` Tool Actually Exposes

The `LSP` tool surfaces nine operations. **None of them return diagnostics.**

| Operation | Use |
|---|---|
| `goToDefinition` | Jump to the file/line where a symbol is defined |
| `findReferences` | Find every reference to a symbol across the workspace |
| `hover` | Get the type signature and docstring at a position |
| `documentSymbol` | List every symbol declared in a file |
| `workspaceSymbol` | Search the entire workspace by symbol name |
| `goToImplementation` | Jump from an interface/abstract member to its implementations |
| `prepareCallHierarchy` | Anchor a call-hierarchy query at a position |
| `incomingCalls` | List functions that call the anchored target |
| `outgoingCalls` | List functions called by the anchored target |

Every one of these answers from pyright's symbol index in milliseconds. The index is updated lazily but always responds with whatever it currently has. **Navigation is not where the slowness comes from.**

## Where the Slow / Stale Errors Come From

Diagnostics (type errors, lint warnings) are *not* an `LSP` tool operation. They reach the model through a separate side channel: the pyright-lsp plugin pushes pyright's `publishDiagnostics` output into conversation context after `Edit`/`Write` tool calls. This is the source of the noise:

- **Stale diagnostics** — pyright re-analyzes the file (and its dependents) after every change. On a non-trivial graph this takes 1–4 seconds. The diagnostic snapshot is taken before re-analysis settles, so the model sees errors against line numbers that no longer exist or symbols that were just renamed. Tracked upstream as [anthropics/claude-code#17979](https://github.com/anthropics/claude-code/issues/17979) and [#21297](https://github.com/anthropics/claude-code/issues/21297).
- **Hint-level noise promoted to errors** — pyright emits `DiagnosticTag.Unnecessary` (e.g., a never-used parameter) at *hint* severity. The plugin currently surfaces these as if they were diagnostics worth acting on. Tracked as [anthropics/claude-code#26634](https://github.com/anthropics/claude-code/issues/26634).

mypy via `doit check` is the authoritative type checker for this repo. Pyright's role is purely to back the LSP tool — its diagnostics are advisory, and they are cheap to ignore by default.

## Default Stance

LSP stays on. The navigation operations are valuable, and the diagnostic noise is something an agent can tune out once it knows the shape of the problem (symptom: errors against line numbers that don't match the just-edited file; cure: re-read the file or run `doit check` rather than chase the diagnostic).

If an agent (or the human running it) wants to silence the noise more aggressively, two opt-outs are below. Pick one or the other — running both is redundant.

## Opt-Out A: Make Diagnostics Wait Until Pyright Catches Up

Add a `PostToolUse` sleep hook to `.claude/settings.local.json` (gitignored, per-clone):

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "sleep 3",
            "statusMessage": "Letting pyright catch up to prevent stale diagnostics"
          }
        ]
      }
    ]
  }
}
```

| | |
|---|---|
| **What it does** | Delays the next tool call by 3 seconds, giving pyright time to settle before the diagnostic snapshot fires. |
| **Keeps diagnostics?** | Yes — the goal is fresher diagnostics, not fewer. |
| **Cost** | ~3 s of pure wait per `Edit`/`Write`/`MultiEdit`. A 30-edit session pays ~90 s of dead time. |
| **Caveats** | 1 s is often not enough on real codebases; 3 s is a safer floor but still won't survive a cold cache or a large refactor. The hook fires on every edit regardless of whether diagnostics would have been stale. Whether Claude Code reads diagnostics synchronously with PostToolUse return is undocumented — the hook is a community-known workaround, not a guaranteed fix. |
| **Pick this when** | You actively use pyright's diagnostics and just want them to be correct. |

## Opt-Out B: Turn Off Pyright Diagnostics Entirely

Edit `pyproject.toml`:

```toml
[tool.pyright]
typeCheckingMode = "off"   # was "basic"
```

| | |
|---|---|
| **What it does** | Pyright still indexes the workspace (so navigation works) but emits no type-check diagnostics, so there is nothing for the side channel to push into context. |
| **Keeps diagnostics?** | No — pyright's diagnostics go silent. mypy via `doit check` remains authoritative. |
| **Cost** | Zero runtime overhead. |
| **Caveats** | You lose pyright's interactive view of type errors. If you were using pyright as a second opinion against mypy, you'd lose that signal until you flip it back. |
| **Pick this when** | mypy via `doit check` is already your source of truth and pyright's running commentary is noise you'd rather not have. |

## Future Direction

Both [pyrefly (Meta)](https://pyrefly.org/) and [ty (Astral)](https://astral.sh/blog/ty) ship full LSP implementations backed by Rust analyzers, with re-analysis times measured in milliseconds rather than seconds. Either would collapse the staleness window enough that neither opt-out above would be necessary. Both are still beta as of May 2026; pyrefly is further along on Python typing conformance, ty is closer aligned with this repo's `uv`/`ruff` toolchain.

A future migration would replace the `pyright-lsp@claude-plugins-official` plugin with a local plugin pointing `lspServers.<name>.command` at `pyrefly lsp` or `ty server`. No such plugin is in the official Claude Code marketplace yet; a local one is straightforward to author when the time is right.

## Files

| File | Description |
|---|---|
| [`.claude/lsp-setup.md`](../../../.claude/lsp-setup.md) | Earlier pyright-lsp installation notes (now partially superseded — LSP requests no longer hang) |
| [`pyproject.toml`](../../../pyproject.toml) | `[tool.pyright]` block; flip `typeCheckingMode` here for opt-out B |
| `.claude/settings.local.json` | Per-clone Claude settings; wire opt-out A here |

## Related

- [Ruff Auto-Fix on Edit Hook](ruff-fix-hook.md) — sibling `PostToolUse` hook that runs ruff `--fix` on edited Python files
- [AI Command Blocking](command-blocking.md) — `PreToolUse` hook reference
- [AI Architectural Conventions](architectural-conventions.md)
