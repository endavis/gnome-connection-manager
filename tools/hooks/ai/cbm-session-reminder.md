# CBM Gate Protocol Reminder

The **Codebase Memory MCP gate** is active for `Read`, `Grep`, and `Glob` on source files.

## What the gate does

Any `Read`/`Grep`/`Glob` call targeting a **source-code file** (`.py`, `.ts`, `.js`, `.go`, etc.)
is blocked unless a CBM tool has been called within the last 120 seconds. This enforces the
token-efficient query path: CBM's knowledge graph answers structural questions for far fewer tokens
than reading files directly.

## What always passes through (no CBM needed)

The allow-list bypasses the gate automatically — you can read these directly:

- Config files: `.json`, `.yaml`, `.yml`, `.toml`, `.lock`, `.txt`, `.env`, `.sh`
- Docs: `.md`
- Paths containing `.claude/`, `CLAUDE.md`, `settings`, `hooks/`, `tests/`, or `_test.`

## How to work with the gate

**Before querying source code, call a CBM tool first:**

| Goal | CBM tool to call |
| :--- | :--- |
| Find where a function is defined | `mcp__codebase-memory__search_graph` |
| Understand a module's structure | `mcp__codebase-memory__get_architecture` |
| Trace a call path | `mcp__codebase-memory__trace_path` |
| Read a specific function body | `mcp__codebase-memory__get_code_snippet` |
| Ensure graph is current | `mcp__codebase-memory__index_repository` |

After any CBM tool call, you have **120 seconds** to `Read`/`Grep`/`Glob` source files freely.

## Whole-repo searches

A `Grep` or `Glob` call with **no `path` argument** is always gated — it is exactly the case CBM
is optimised for. Use `mcp__codebase-memory__search_graph` instead.

## Keeping the graph current

If the codebase has changed materially since the last index (new files, major refactors), call
`mcp__codebase-memory__index_repository` to refresh. The gate remains active but the graph will
give accurate results. Use `mcp__codebase-memory__detect_changes` to check whether a refresh is
needed before indexing.
