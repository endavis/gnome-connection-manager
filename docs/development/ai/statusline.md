---
title: Claude Code Statusline
description: Custom statusline showing git branch, Python version, and project info
audience:
  - contributors
  - ai-agents
tags:
  - ai
  - claude
  - antigravity
  - configuration
---

# Claude Code Statusline

The template includes custom statuslines for AI CLI sessions that provide useful context at a glance.

## Example Output

```
📁 project-name | 🐍 .venv | Python: 3.12.12
@username | 🔀 main (0 files uncommitted, synced 5m ago)
Claude Opus 4.5 | ▓▓░░░░░░░░ ~10% of 200k tokens
💬 work on issue #130
```

## Features

- **Current directory** and Python virtual environment name
- **Python version** currently active
- **GitHub username** (from `gh` CLI; omitted when `gh` is missing or unauthenticated)
- **Git branch** with uncommitted file count
- **Sync status** showing ahead/behind commits and last fetch time
- **Model name** with context usage bar (visual + percentage)
- **Last user message** preview for quick context

## Configuration

The statusline is configured in `.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "bash $CLAUDE_PROJECT_DIR/.claude/statusline-command.sh"
  }
}
```

## Customization

### Color Theme

Edit `.claude/statusline-command.sh` and change the `COLOR` variable at the top:

```bash
# Available themes: gray, orange, blue, teal, green, lavender, rose, gold, slate, cyan
COLOR="blue"
```

### Color Reference

| Theme    | ANSI Code | Description |
|----------|-----------|-------------|
| gray     | 245       | Monochrome, subtle |
| orange   | 173       | Warm, energetic |
| blue     | 74        | Default, calm |
| teal     | 66        | Cool, professional |
| green    | 71        | Fresh, nature |
| lavender | 139       | Soft, creative |
| rose     | 132       | Warm pink |
| gold     | 136       | Rich, elegant |
| slate    | 60        | Dark blue-gray |
| cyan     | 37        | Bright, tech |

The usage segment (opt-in, see below) uses three additional fixed colors that are independent
of the `COLOR` theme:

| Field | Variable | ANSI Code | Description |
|-------|----------|-----------|-------------|
| Percent value | `C_PCT` | 71 (green) | "value" semantics — current consumption |
| `@` separator | `C_DIM` | 238 (dark gray) | dim join between percent and time |
| Reset time | `C_TIME` | 136 (gold) | "schedule" semantics — when the bucket ends |

Edit `.claude/statusline-command.sh` to change these.

### Removing Features

Comment out or remove lines in the "Build output" section of the script:

```bash
# Build output: Model | Dir | Branch (uncommitted) | Context
output="📁 ${dir}"
[[ -n "$venv_name" ]] && output+=" | 🐍 ${venv_name}"
[[ -n "$python_version" ]] && output+=" | Python: ${python_version}"
# [[ -n "$gh_user" ]] && output+="\n@${gh_user}"  # Remove GitHub username
[[ -n "$branch" ]] && output+=" | 🔀 ${branch} ${git_status}"
```

## Opt-In: Claude Max Usage Display

For Claude Max subscribers, an optional helper at `tools/statusline/claude-usage.sh` displays
weekly + 5-hour utilization. The default statusline runs the helper only when the
`CLAUDE_USAGE_STATUSLINE` env var is set, so the default behavior is unchanged.

> **Beta API**: This helper hits an undocumented OAuth endpoint (`/api/oauth/usage`)
> gated by the `anthropic-beta: oauth-2025-04-20` header. Anthropic may change or remove
> this endpoint without notice. When the official `claude --usage` flag ships
> ([anthropics/claude-code#20399](https://github.com/anthropics/claude-code/issues/20399)),
> prefer it.

### Enable

Set `CLAUDE_USAGE_STATUSLINE=1` in your shell environment:

```bash
# In ~/.zshrc, ~/.bashrc, or .envrc.local
export CLAUDE_USAGE_STATUSLINE=1
```

Restart Claude Code. The statusline appends `5h:N%@HHMM wk:N%@aaa-HHMM` to the model/context line.
Times are shown in your local timezone.
To disable temporarily: `unset CLAUDE_USAGE_STATUSLINE` and restart Claude Code.

Example output (helper segment is the trailing portion of the third line):

```
📁 project | 🐍 .venv | Python: 3.12.12
@username | 🔀 main (0 files uncommitted, synced 5m ago)
Claude Opus 4.5 | ▓▓░░░░░░░░ ~10% of 200k tokens | 5h:25%@1800 · wk:6%@Mon-2000
```

### Cache behavior

Responses are cached at `${XDG_CACHE_HOME:-~/.cache}/claude-usage.json` for 60 seconds.
Adjust `MAX_AGE` at the top of the script. To force a refresh: `rm ~/.cache/claude-usage.json`.

### Helper requirements

- Active Claude Code OAuth login (`${CLAUDE_CONFIG_DIR:-~/.claude}/.credentials.json`)
- `curl` for HTTPS
- `jq` (already required by base statusline)
- `python3` for ISO-8601 timestamp formatting (already a project dev dependency)

### Helper troubleshooting

- **Outputs `?`**: missing/expired credentials, no network, beta endpoint changed schema, or
  curl timeout (5s). Debug with `bash -x tools/statusline/claude-usage.sh`.
- **Stale value**: cache has not expired. Delete the cache file or wait 60s.

## Requirements

- `jq` - JSON processor (used for parsing Claude's input)
- `gh` - GitHub CLI (optional, for username display)
- `git` - For branch and status information

## Troubleshooting

### Statusline not appearing

1. Ensure the script is executable: `chmod +x .claude/statusline-command.sh`
2. Check `jq` is installed: `which jq`
3. Test manually: `echo '{}' | bash .claude/statusline-command.sh`

### Colors not displaying

Some terminals may not support 256-color mode. Try setting `COLOR="gray"` for basic output.

## Antigravity CLI (agy) Statusline

The `agy` statusline is opt-in: unlike the Claude statusline, which is committed and auto-wired
via `.claude/settings.json`, `agy`'s statusline is configured in the user's **global**
`~/.gemini/antigravity-cli/settings.json` — outside the repo-committed `.agents/` workspace
config — so it cannot be auto-provisioned per-clone. This mirrors how
`tools/statusline/claude-usage.sh` is opt-in.

### Example Output

```
📁 pyproject-template | 🐍 package-name | Python: 3.12.12
@endavis | 🔀 main (0 files uncommitted, synced 5m ago) | ● working
Gemini 3 Pro | ██░░░░░░░░ 12% of 1048k tokens
```

### Enable (Opt-In)

Add the following to `~/.gemini/antigravity-cli/settings.json`:

```json
{
  "statusLine": {
    "command": "bash /absolute/path/to/pyproject-template/tools/statusline/agy-statusline.sh",
    "enabled": true
  }
}
```

> **`statusLine` (camelCase):** The key must be camelCase — `statusLine`, not `statusline`.
> Lowercase `statusline` is silently ignored by `agy`.

> **Absolute path required:** The global settings file has no `$CLAUDE_PROJECT_DIR` equivalent.
> Replace the placeholder with the full absolute path to this repository on your machine.

### What It Shows

Like the Claude statusline, the **directory, virtual environment, Python version, git branch +
status, and GitHub username are computed locally** — `agy`'s payload reports only `vcs.type`, not
the branch, so the script derives them itself (via `git`, `python`, `$VIRTUAL_ENV`, and `gh`),
anchored on the workspace directory. `agy`-native fields come from the JSON payload on stdin:

| Field | Used for |
|-------|----------|
| `.workspace.current_dir` (or `.cwd`) | Anchor for local git / venv / Python / `gh` detection |
| `.model.display_name` | Model label |
| `.agent_state` | Colored state dot + label |
| `.context_window.context_window_size` | Token-window size shown after the bar |
| `.context_window.current_usage.*` | Token occupancy for the context bar (falls back to `.context_window.used_percentage`) |
| `.sandbox.enabled` | Sandbox indicator (quota segment, opt-in) |
| `.quota["gemini-5h"]`, `.quota["gemini-weekly"]` | Quota segment (opt-in) |

### Color Theme

The script shares the same `COLOR` theme knob as `.claude/statusline-command.sh`.
Edit `tools/statusline/agy-statusline.sh` and change `COLOR="blue"` at the top.
Available themes: `gray`, `orange`, `blue`, `teal`, `green`, `lavender`, `rose`, `gold`,
`slate`, `cyan`.

### Opt-In: Quota Display

By default the `agy` statusline shows the three lines above. Set `AGY_STATUSLINE_EXTRAS=1` to
append `agy`'s quota usage to the model/context line: 5-hour and weekly usage (from the Gemini
`quota` block, rendered as *used* percent = `1 − remaining_fraction`) plus a sandbox indicator
(🔒, shown only when the sandbox is enabled). This mirrors how `CLAUDE_USAGE_STATUSLINE` gates
the Claude Max usage segment — the base render is unchanged; the env var only appends a segment.

```bash
# In ~/.bashrc, ~/.zshrc, or .envrc.local — the shell that launches `agy`
export AGY_STATUSLINE_EXTRAS=1
```

Example with the segment enabled:

```
📁 pyproject-template | 🐍 package-name | Python: 3.12.12
@endavis | 🔀 main (0 files uncommitted, synced 5m ago) | ● working
Gemini 3 Pro | ██░░░░░░░░ 12% of 1048k tokens | 5h:0% · wk:1% · 🔒
```

The var must be exported in the shell `agy` is launched from: `agy` runs the statusline script
as a subprocess and passes its environment through, so a var set only for the current command
will not reach it. To disable: `unset AGY_STATUSLINE_EXTRAS` and restart `agy`.

### Requirements

- `bash` — shell runtime
- `jq` — JSON processor (already required by the base Claude statusline)
- `git` — for branch and status (computed locally; `agy` reports only `vcs.type`)
- `gh` — GitHub CLI (optional, for the `@username` segment; the segment is
  dropped if `gh` is absent or its token is invalid)
- `python` — optional, for the active Python version
- `awk` — for the opt-in quota percentages (part of coreutils/busybox; already present)

### Troubleshooting

**Statusline not appearing:** verify the config key is `statusLine` (camelCase) and
`enabled` is `true`.

**Branch / directory blank:** the script anchors on `.workspace.current_dir`/`.cwd`, falling back
to the process working directory. If `agy` launches it from outside the repo, git detection can't
find the branch.

**Test manually:**

```bash
echo '{"agent_state":"working","model":{"display_name":"Gemini 3 Pro"},"context_window":{"context_window_size":1048576,"current_usage":{"input_tokens":26000}},"workspace":{"current_dir":"'"$PWD"'"}}' \
  | bash tools/statusline/agy-statusline.sh
```

**References:**
[official example script](https://github.com/google-antigravity/antigravity-cli/blob/main/examples/statusline/statusline.sh) ·
[agy statusline docs](https://antigravity.google/docs/cli-statusline)
