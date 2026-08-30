# Claude LSP Setup

This project ships LSP support for Claude Code via the `pyright-lsp@claude-plugins-official` plugin. The LSP server (pyright) gives AI agents go-to-definition, find-references, hover, and workspace symbol search.

This file covers **installation only**. For what the `LSP` tool actually exposes, where the noisy stale "errors" after edits come from, and the two opt-ins an agent can flip on itself, see [`docs/development/ai/lsp-tool.md`](../docs/development/ai/lsp-tool.md).

## Prerequisites

- Claude Code 2.0.74 or later (LSP is enabled by default in 2.0.74+; older versions need `ENABLE_LSP_TOOL=1`)
- Python 3.12+
- This project installed with dev dependencies (`uv sync`) — pyright comes in via the dev group

## Install Steps

### 1. Install the plugin

In Claude Code:

```
/plugin install pyright-lsp@claude-plugins-official
```

### 2. Confirm `pyright-langserver` is on PATH

`uv sync` installs pyright into `.venv/bin/`. Verify:

```bash
uv run pyright --version
# → pyright 1.1.x
```

If running outside `uv run`, make sure the venv is on PATH (this project uses direnv).

### 3. (Optional, Claude Code < 2.0.74) Enable the LSP tool

Older Claude Code releases gate the LSP tool behind an env var. Add to `.envrc.local`:

```bash
export ENABLE_LSP_TOOL=1
```

Or your shell profile. **Skip this step on 2.0.74+** — the tool is enabled by default.

## Configuration

Already done — `[tool.pyright]` in `pyproject.toml` sets `include`, `exclude`, `pythonVersion`, and the venv path. No additional setup needed.

## Verifying It Works

Ask an agent to use the `LSP` tool against a known symbol:

```
Use the LSP tool's goToDefinition on the `greet` symbol in src/.
```

A working setup returns the file path and line number near-instantly. A broken setup falls back to `Grep`.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `No LSP server available` | `pyright-langserver` not on PATH | `uv sync`; or `pip install pyright`; or `npm install -g pyright` |
| `Executable not found in $PATH` | Plugin installed but binary missing | Same as above |
| Plugin not loading at all | Plugin not installed at user scope | `/plugin install pyright-lsp@claude-plugins-official` then restart Claude Code |
| Noisy or stale "errors" after every edit | Pyright diagnostic side-channel staleness — working as designed | See [`docs/development/ai/lsp-tool.md`](../docs/development/ai/lsp-tool.md) for the two documented opt-ins |

## Related

- [LSP Tool and Diagnostic Noise](../docs/development/ai/lsp-tool.md) — what agents see, why diagnostics arrive stale, and how to opt out
- [AI Setup](../docs/development/AI_SETUP.md) — broader AI agent setup for this template
- [Pyright Documentation](https://microsoft.github.io/pyright/)
