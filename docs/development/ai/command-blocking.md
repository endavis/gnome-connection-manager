---
title: AI Command Blocking
description: Hooks that block dangerous commands from AI agents
audience:
  - contributors
  - ai-agents
tags:
  - ai
  - security
  - hooks
---

# AI CLI Hooks

The `tools/hooks/ai/` directory contains hooks for AI coding assistants (Claude Code, Copilot CLI, Codex CLI, Antigravity CLI).

## Block Dangerous Commands

### Purpose

AI agents can sometimes attempt dangerous operations like:

- `--admin` - bypasses branch protection
- `--no-verify` - skips pre-commit hooks
- `git reset --hard` - loses uncommitted changes
- `rm -rf /` or `rm -rf ~` - destructive deletions
- Force push to `main`/`master` - overwrites shared history
- Deleting protected branches
- Merge commits on protected branches - violates linear history

These hooks intercept commands before execution and block dangerous patterns, even if the agent doesn't follow the rules in `AGENTS.md`.

### How It Works

The hook uses Python's `shlex` module to properly parse shell quoting:

1. **Tokenize** the command with `shlex.split()`
2. **Check** for dangerous flags as standalone tokens
3. **Check** for dangerous token sequences (e.g., `rm -rf ~`)
4. **Check** for force push to protected branches (main/master) — including refspec forms (`HEAD:main`, `+main`) and commands preceded by git global options (`-C`, `-c`, `--git-dir`, …)
5. **Check** for deletion of protected branches — also handles git global options
6. **Check** for merge commits on protected branches (linear history)
7. **Recurse** into shell-wrapper payloads (`bash -c "..."`, `sh -c "..."`, `eval "..."`) — up to depth 3, so all checks above apply inside wrappers
8. **Block** or **Allow** — Claude/Codex block via exit code 2; Copilot and Antigravity block via a stdout decision JSON (exit code 0)

#### Key Feature: Chained Command Detection

The hook scans all token positions, so chained commands using `&&` or `;` are caught. The scan
also runs on tokens where every `;`, `&&`, `||`, `|` and `&` is its own token, so a separator glued
to the next command still ends the one before it (#1023):

```bash
# BLOCKED - dangerous command after safe one
git status; git push --force origin main
true;git push --force origin main
cd /path && doit release

# ALLOWED - all commands in the chain are safe
cd /path && doit check
git status; git push origin feat/branch
```

#### Key Feature: Git Global Option Handling

Git global options (e.g., `-C <path>`, `-c <k>=<v>`, `--git-dir=<dir>`, `--attr-source <ref>`,
`--config-env <var>=<envvar>`) appear between the `git` token and the subcommand. The hook walks
past them to find the real subcommand, so these are all caught:

```bash
# BLOCKED - global options shift the subcommand position, but hook handles them
git -C . push --force origin main
git -c core.pager=cat push --force origin main
git --git-dir=.git push --force origin main
git -C . branch -D main
```

#### Key Feature: Refspec-Aware Branch Extraction

Force push to a protected branch is detected regardless of refspec form:

```bash
# BLOCKED - all target the 'main' branch
git push --force origin HEAD:main
git push origin +main
git push --force-with-lease=HEAD origin HEAD:main

# ALLOWED - destination branch is a feature branch
git push origin main:feature        # pushes local 'main' to remote 'feature'
git push origin HEAD:refs/heads/dev
```

#### Key Feature: Shell-Wrapper Payload Unwrapping

The hook recurses into `bash -c`, `sh -c`, `zsh -c`, `dash -c`, and `eval` payloads (up to depth
3), so all checks apply inside wrappers:

```bash
# BLOCKED - dangerous command inside a wrapper
bash -c "git push --force origin main"
sh -c "git branch -D main"
eval "gh pr merge 1 --admin"

# ALLOWED - safe command inside a wrapper
bash -c "echo main"
bash -c "git status"
```

#### Key Feature: Quote-Aware Parsing

The hook correctly distinguishes between:

```bash
# BLOCKED - actual dangerous flag
gh pr merge --admin

# ALLOWED - flag is just text in a commit message
git commit -m "The --admin flag is dangerous"

# ALLOWED - flag mentioned in heredoc content
doit pr --body="$(cat <<'EOF'
Do not use --force
EOF
)"
```

#### Heredocs

Quoting is what makes the example above safe: the `$( )` sits inside double quotes, so `shlex`
collapses the whole thing into one token and nothing inside it is ever a standalone `--force`. An
**unquoted** heredoc body gets no such protection — it is split into tokens like any other
argument. Four shapes, and they do not behave alike:

| shape | outcome |
| :--- | :--- |
| `doit pr --body="$(cat <<'EOF' … )"` — quoted substitution | allowed; the body is one token |
| `bash <<EOF` — a shell will execute the body | **blocked** if the body contains a blocked pattern; the body is re-scanned as commands, the way `bash -c` already is |
| `git commit -F - <<EOF` — prose the receiver consumes as data | **blocked** if the prose names a blocked pattern, because the body is still tokenized |
| `python3 - <<EOF`, `cat > f.md <<EOF` — a non-shell receiver | body is not re-scanned; the flat token scan still applies to it |

The third row is why **commit messages go in a file**: a message describing `--admin` or
`gh issue create` is refused as though it invoked one. That block names its alternative rather than
giving the generic reason:

```
Reason: A commit message passed by heredoc is scanned as command arguments, so a
message naming a blocked pattern is refused. Write the message to
tmp/agents/<agent-type>/ and pass it with `git commit -F <file>`.
```

See [Commit Guidelines — Passing the Message](../../../.github/CONTRIBUTING.md#commit-guidelines)
for the convention, and
[ADR-9019](../../decisions/9019-the-dangerous-command-hook-is-a-guardrail-not-a-security-boundary.md)
for why the scanner is not taught to recognise prose instead — the short version is that skipping
bodies for a list of trusted receivers turns a mistake in that list into a bypass, and the flat
scan is what covers interpreters nobody has listed.

Finding the marker itself has to be quote-aware too: `echo "<<EOF"` is not a heredoc, it is an
ordinary argument that happens to contain the characters `<<EOF`. `_heredoc_marker_match` walks
each line with the same quote-tracking the comment stripper uses, carrying an open quote from one
line to the next, and only tries the marker pattern outside a quote. A quoted `<<WORD`, including
one that closes a string opened on an earlier line, is left alone, and the lines after it are not
mistaken for its body (#1011). Where the quoting is too tangled to follow (a marker line that ends
inside a quote, or a `$(...)`, `${...}` or backtick expansion inside a double quote, whose own
quotes nest), the hook stops stripping heredoc bodies from that point on, so every later line is still
scanned.

```bash
# BLOCKED - the quoted "<<EOF" is not a heredoc marker, so the read after it is still seen
echo "<<EOF" ;
cat ~/.netrc
```

Two other shapes contain `<<` without starting a heredoc: a here-string (`cat <<< "$x"`), whose
word is on the same line, and a left shift inside arithmetic (`$((1<<n))`, `((x <<= 2))`). The
marker scan skips both, so the lines after them are not mistaken for a body (#1025). Arithmetic left
open at the end of a line is treated like tangled quoting: stripping stops there.

```bash
# BLOCKED - a here-string has no body, so the read on the next line is still seen
cat <<<EOF
cat ~/.netrc
```

The checks that need to know where a command *starts* (the merge rule, the credential-read check
and the env-dump check) see the command with every heredoc body and terminator line removed.
Without that, an unbalanced quote inside a heredoc body could open a quote that swallows everything
after the terminator, hiding a real `git merge` or credential read from the scan meant to catch it.
The merge rule also scans the full command, so a merge inside a body whose receiver the hook does not
recognise as running it, such as `env -i bash <<EOF`, is still blocked:

```bash
# BLOCKED - the merge rule sees the heredoc-stripped command, so the quote in the
# body does not swallow the `git merge` after the terminator
cat <<'EOF'
"
EOF
git merge feature "
```

### Files

| File | Description |
|------|-------------|
| [`block-dangerous-commands.py`](../../../tools/hooks/ai/block-dangerous-commands.py) | The hook script (shared by Claude, Copilot, Codex, and Antigravity) |
| [`block-dangerous-commands.sh`](../../../tools/hooks/ai/block-dangerous-commands.sh) | Fail-closed launcher used by the stdout-contract CLIs (Copilot, Antigravity) |
| [`tests/test_hook_dangerous_command_matrix.py`](../../../tests/test_hook_dangerous_command_matrix.py) | The block/allow matrix — 134 cases plus subprocess smoke tests |
| [`tests/test_hook_block_dangerous_commands.py`](../../../tests/test_hook_block_dangerous_commands.py) | Pytest test suite — collected by CI via `testpaths = ["tests"]` |

### Configuration

#### Claude Code

`.claude/settings.json`:
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "python3 $CLAUDE_PROJECT_DIR/tools/hooks/ai/block-dangerous-commands.py"
          }
        ]
      },
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "python3 $CLAUDE_PROJECT_DIR/tools/hooks/ai/block-dangerous-commands.py"
          }
        ]
      }
    ]
  }
}
```

#### Copilot CLI

`.github/hooks/copilot-hooks.json`:
```json
{
  "version": 1,
  "hooks": {
    "preToolUse": [
      {
        "type": "command",
        "bash": "sh ../../tools/hooks/ai/block-dangerous-commands.sh",
        "cwd": ".github/hooks",
        "timeoutSec": 10
      }
    ]
  }
}
```

No change needed to this config for Copilot — the hook fires on every tool call (no `matcher` field). But firing on the call is not the same as being understood: before #1037, the hook only recognised Claude/Codex's `Edit`/`Write`/`MultiEdit` names, Gemini's `write_file`/`replace`, and Antigravity's `write_to_file`/`write_file`/`edit_file` — none of which are Copilot's. Copilot's real file-edit tool names, from its shipped SDK docs rather than a live probe, are `create` and `edit`, with the target path under a `path` key. Its content key is not confirmed, so rather than guess one, the hook scans every string value in `tool_input` for the bypass var name when it sees Copilot's `create`/`edit`. See [Env-Var Persistence Blocks](#env-var-persistence-blocks) below.

**Headless (`-p`) runs load repo hooks only when opted in.** Copilot CLI 1.0.104 skips `.github/hooks/` in prompt mode unless `GITHUB_COPILOT_PROMPT_MODE_REPO_HOOKS=true` is set, `COPILOT_ALLOW_ALL=true` is set in the environment (the `--allow-all` flag alone does not count), or the folder is trusted. The value must be the literal string `true` — `=1` leaves the hook off. Every documented Copilot invocation in this repo (see [Non-interactive flags per CLI](cross-agent-delegation.md#non-interactive-flags-per-cli)) sets the variable. A `copilot -p` run started without it, in a folder Copilot has not trusted, runs with **no** dangerous-command protection (#1042).

**In `-p` mode Copilot edits files through `apply_patch`, not `create`/`edit`.** A live probe (#1042) showed its `toolArgs` is the bare patch text (`*** Begin Patch\n*** Add File: …`), not JSON. Copilot also runs the Claude-format hooks in `.claude/settings.json`, sending `tool_name: "Edit"` with the same patch text as `tool_input`. The hook recognises a patch-text payload in either format and checks each `*** Add/Update/Delete File:` and `*** Move to:` target against the env-var persistence rules. Unlike Codex's `apply_patch`, whose payload is a shell command, the patch text is not scanned as a command, so a patch that mentions `git reset --hard` in a doc is allowed.

An unrecognised tool name — Copilot's or any other CLI's — no longer falls through to "allow" either: `tool_input` carrying both a path-shaped key (`file_path`, `path`, `filename`) and a content-shaped key (`content`, `new_string`, `new_text`, `file_text`, `edits`) is routed into the same persistence check on shape alone.

#### Codex CLI

`.codex/config.toml`:
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

[[hooks.PreToolUse]]
matcher = "^apply_patch$"

[[hooks.PreToolUse.hooks]]
type = "command"
command = 'python3 "$(git rev-parse --show-toplevel)/tools/hooks/ai/block-dangerous-commands.py"'
timeout = 30
statusMessage = "Checking file edit"
```

Codex uses the shared hook as the primary defense layer. Project docs should not rely on the obsolete `[[approval_policy]]` command-rule format.

##### Codex's tool names, verified by probe

These were confirmed against a live Codex session with `HOOK_BLOCKCOMMAND_DEBUG=1`, not inferred
(#681):

| Operation | `tool_name` | Payload |
| :--- | :--- | :--- |
| Shell command | `Bash` | `default` schema — `tool_name` / `tool_input.command`, same as Claude |
| File edit | **`apply_patch`** | command-shaped: `tool_input.command` holds an `apply_patch <<PATCH …` heredoc |

The shell name matches Claude's, so `^Bash$` was correct. The file-edit matcher was **not**: Codex
has no `Edit`/`Write`/`MultiEdit`. Because `apply_patch` appeared in neither
`_BASH_TOOL_NAMES` nor `_FILE_EDIT_TOOL_NAMES`, it fell through to *allow* — so a patch persisting
`ALLOW_AI_READY_TO_MERGE` to `~/.bashrc` succeeded through Codex while the identical edit through
Claude's `Write` was blocked.

`apply_patch` is now checked on its own path, as **both** a command and a set of file edits: the
envelope goes through the dangerous-flag scanning, and each `*** Add/Update/Delete File:` target is
normalised into the `file_path`/`content` shape the env-persistence check expects, so the protected
target list stays in one place. An `apply_patch` call with no `command` is not allowed by default:
it goes on to the shape-based fallback, so a path + content payload under that name is checked like
any other write (#1048).

##### Codex requires hook trust

Codex will not run a hook it has not been told to trust; trust is persisted per hook (`trusted_hash`
in the hooks config). **An untrusted hook is skipped silently** — no warning, no log line — which is
why this hook appeared to work for as long as nobody checked. This is hook trust, scoped to one
hook's source; it is a different gate from the *project* trust covered next, and bypassing one does
not bypass the other.

Headless invocations therefore pass `--dangerously-bypass-hook-trust`, the way Antigravity's pass
`--dangerously-skip-permissions`:

```bash
codex -a never --dangerously-bypass-hook-trust exec '<prompt>' < /dev/null
```

The flag makes the safety hook **run**; it does not weaken it. What it bypasses is Codex's check
that the hook *source* has been vetted, and here that source is this repository's own checked-in
script.

> **Trade-off, stated deliberately:** with the flag, any hook defined in the repository's `.codex/`
> config runs without a prompt — so a hook added by a malicious pull request would execute. A
> consumer who would rather not accept that can trust the hook once in an interactive Codex session
> (the trust persists) and drop the flag from the bridges.

##### Codex requires *project* trust, a separate gate from hook trust

Hook trust (above) governs one hook's source. A separate, earlier gate governs whether Codex loads
the checkout's `.codex/` configuration — hooks **and** rules — at all: **project trust**, recorded
per checkout path in `~/.codex/config.toml`'s `[projects."<abs path>"]` table.
`--dangerously-bypass-hook-trust` does not grant it; the name only covers hook-source review.

Measured with codex-cli 0.163.0, 2026-10-21 (#984), from a scratch `git clone` of this repo with a
probe rule `.codex/rules/probe-984.rules` = `prefix_rule(pattern=["git", "ls-remote"],
decision="allow")` — chosen because the maintainer's personal `~/.codex/rules` do not cover `git
ls-remote`, so they cannot mask the result. Each row ran:

```bash
codex -a never --dangerously-bypass-hook-trust \
  [-c 'projects={"<clone path>"={trust_level="<level>"}}'] \
  exec 'Run exactly: git ls-remote https://github.com/endavis/pyproject-template refs/heads/main ...' \
  < /dev/null
```

counting `hook: PreToolUse` lines on stderr:

| Project trust for the clone | `hook: PreToolUse` lines | `git ls-remote` result | `.codex/` loaded? |
| :--- | :--- | :--- | :--- |
| No `[projects."<path>"]` entry in `~/.codex/config.toml` | 0 | `fatal: unable to access ...: Could not resolve host: github.com` | **No** |
| `trust_level = "untrusted"` | 0 | same failure | **No** |
| `trust_level = "trusted"` | 2 | resolves `refs/heads/main` (e.g. `ec0f479...`) | **Yes** |

So in a checkout Codex has not trusted, a headless `codex exec` loads neither `.codex/rules/gh.rules`
(the #980 fix) nor the `PreToolUse` dangerous-command hook — regardless of
`--dangerously-bypass-hook-trust`. The main checkout in this repo loads because its
`~/.codex/config.toml` already carries
`[projects."<abs path to this checkout>"] trust_level = "trusted"`.

One syntax note from the same measurement: the dotted override form
`-c projects."<path>".trust_level="trusted"` had no effect; the inline-table form
`-c 'projects={"<path>"={trust_level="trusted"}}'` did.

**Trust step, one-time per checkout:** before relying on `.codex/` in a headless `codex exec` run,
trust the checkout — accept the trust prompt in an interactive `codex` session opened in that
directory, or add `[projects."<abs path>"] trust_level = "trusted"` to `~/.codex/config.toml` by
hand. Until then, neither defense layer applies, headless or not. See also [Headless Codex host
limits](cross-agent-delegation.md#headless-codex-host-limits) for what a trusted-but-headless Codex
session still cannot do.

##### `gh` has no network inside the sandbox — `.codex/rules/*.rules` is a separate mechanism

`.codex/config.toml`'s `approval_policy` and `[[hooks.PreToolUse]]` control whether a command is
*asked about* or run through the dangerous-command hook. They do not control whether a command runs
*inside Codex's sandbox* or outside it — that is a third, separate mechanism: project-level
`.codex/rules/*.rules` files, each a sequence of Starlark `prefix_rule(pattern=[...],
decision="allow")` calls matched against the exec'd command's prefix.

Measured with codex-cli 0.163.0 (#980): inside the sandbox, `gh` has no network at all — a DNS write to `:53`,
and (with `GODEBUG=netdns=cgo`) a TCP write to `:443`, both return "permission denied", even with `-c
sandbox_workspace_write.network_access=true`. A standalone `gh` command (or `git ls-remote`) that
matches a `prefix_rule` allow runs *outside* the sandbox instead, with full network access —
confirmed by a probe rule file that fixed a previously-failing `git ls-remote`. The allow rule
decides only *where* a command runs; the `PreToolUse` hook still fires first (Codex logs `hook:
PreToolUse` before each allow-ruled `gh` call), so `gh pr merge --admin` and the other blocked
patterns are refused exactly as before.

`.codex/rules/gh.rules` allows only the read-only subcommands delegated runs use: `gh pr
{view,diff,checks,list}` and `gh issue {view,list}`. Everything else — `gh pr comment`, `gh api`
(which writes with `-X`/`-f`), `gh pr merge` — matches no rule and stays in the sandbox, where it has
no network, so GitHub writes from a delegated Codex run get no network path. That narrows the
normal path; it does not guarantee that a delegated run can't write. A rule matches its prefix with
any arguments after it, and the `PreToolUse` hook is a guardrail, not a security boundary
([ADR-9019](../../decisions/9019-the-dangerous-command-hook-is-a-guardrail-not-a-security-boundary.md)).
A guarantee needs a credential boundary, such as a token scoped for delegated runs. Check a change
to the file with
`codex execpolicy check --rules .codex/rules/gh.rules gh pr view 1`;
`tests/template/test_ai_agent_assets.py` does the same for both sides of the line.

Headless invocations also end in `< /dev/null`. `codex exec` reads extra input from stdin when stdin
is not a terminal ("Reading additional input from stdin..."), and a caller whose stdin is an open
pipe or socket — a backgrounded shell, an agent's tool runner — leaves it waiting forever.

The allow rule only matches when `gh` is the exec'd prefix. If a command chains `gh` with `;`,
`&&`, `|`, or any other command, the exec'd prefix is the shell, not `gh`, so the rule does not
match and the chained call falls into the sandboxed, network-less path instead. `.codex/rules/gh.rules`
still carries this allow rule for a headless Codex **host**'s own reads (its own `gh issue
view`/`gh pr view` in `multi-plan`/`multi-review`'s precondition steps) — but as of #985 no prompt
this repo hands Codex *non-interactively as a delegate* calls `gh` at all: the host pre-fetches the
GitHub data a delegated prompt needs with `doit delegation_context` first, so there is no `gh` call
left to chain-guard in a delegated prompt. See [Context-file
convention](cross-agent-delegation.md#context-file-convention).

#### Antigravity CLI (`agy`)

`.agents/hooks.json`:
```json
{
  "block-dangerous-commands": {
    "PreToolUse": [
      {
        "matcher": "run_command|write_to_file|write_file|edit_file",
        "hooks": [
          {
            "type": "command",
            "command": "sh \"$(git rev-parse --show-toplevel)/tools/hooks/ai/block-dangerous-commands.sh\""
          }
        ]
      }
    ]
  }
}
```

Antigravity sends a distinct hook payload — a nested `toolCall` with PascalCase args
(`{"toolCall": {"name": "run_command", "args": {"CommandLine": "..."}}}`). Its file tools, as logged
from a live `agy` 1.4.3 session (#1006):

| Tool | Args | Normalized to |
| :--- | :--- | :--- |
| `run_command` | `CommandLine` | `command` |
| `write_file` | `Path`, `Content`, `Overwrite` | `file_path`, `content` |
| `edit_file` | `Path`, `Target`, `Replacement` | `file_path`, `new_string` |
| `write_to_file` (older releases) | `TargetFile`, `CodeContent` | `file_path`, `content` |

`agy` 1.4.3 never called `write_to_file`; before #1006 the matcher named only it and `run_command`,
so `write_file` and `edit_file` never reached the hook. A test in
`tests/test_hook_dangerous_command_matrix.py` checks that the matcher matches every tool in this table.

Unlike Claude/Codex (which block via exit code 2), `agy` blocks only when the hook prints
`{"decision": "deny", "reason": "..."}` on **stdout** (exit code 0); a safe command prints nothing
and defers to `agy`'s normal permission flow. A `deny` decision hard-blocks even under
`--dangerously-skip-permissions`.

`agy` exposes no project-dir env var, but it **does** shell-interpret the hook command, so the
path is pinned with `$(git rev-parse --show-toplevel)` rather than left relative.

The handler's working directory is the directory containing `hooks.json`. Verified empirically by
logging `os.getcwd()` from the hook during a real `agy` run:

```
_cwd   = <repo-root>/.agents
_argv0 = ../tools/hooks/ai/block-dangerous-commands.py
```

A relative `../tools/...` therefore did resolve — but only because of that CWD, which is `agy`
behaviour rather than a documented contract. Since the hook is `agy`'s only gate (delegated
invocations pass `--dangerously-skip-permissions`) and its deny contract is stdout-based, a CWD
change in a future `agy` release would have disabled it silently and permissively. The absolute
form removes that dependency.

`agy` only loads workspace customizations for an **active/trusted** workspace, so headless
`agy -p` invocations must pass `--add-dir <repo-root>` for the hook to apply; interactive sessions
prompt to trust the workspace on first open.

To confirm the hook is firing, set `HOOK_BLOCKCOMMAND_DEBUG=1` — without it the hook writes no
debug log and an "is it wired?" probe reads as a false negative:

```bash
HOOK_BLOCKCOMMAND_DEBUG=1 agy -p 'run: git status' --add-dir "$(git rev-parse --show-toplevel)"
cat tools/hooks/ai/hook-debug.jsonl   # a new line means the hook ran
```

### Secret exposure

Two different controls, because only one CLI can do the stronger one.

#### Environment allowlists — Codex only

`.codex/config.toml` strips secret-shaped variables from the child environment before a command
runs:

```toml
[shell_environment_policy]
inherit = "core"
include_only = ["PATH", "HOME", "USER", "UV_CACHE_DIR", "VIRTUAL_ENV", "PYTHONPATH"]
exclude = ["*_API_KEY", "*_SECRET", "*_TOKEN", "PASSWORD", "PYPI_TOKEN", "CODECOV_TOKEN"]
```

**The other three agents have no native environment allowlist.** This was checked against each CLI
rather than assumed:

| Agent | Mechanism | Coverage |
| :--- | :--- | :--- |
| Codex | `[shell_environment_policy]` — `include_only` + `exclude` | Secrets removed from the child environment |
| Claude | `permissions` supports `allow` / `ask` / `deny` / `additionalDirectories` / `defaultMode` only | **No native environment allowlist** — hook only |
| Copilot | `--deny-tool` is tool-level; `--bash-env` *enables* `BASH_ENV` rather than restricting it | **No native environment allowlist** — hook only |
| Antigravity | no environment options | **No native environment allowlist** — hook only |

`SECRET_ENV_PATTERNS` in `block-dangerous-commands.py` is the single source of truth for the
pattern list; `.codex/config.toml`'s `exclude` must match it, and
`tests/template/test_secret_env_policy.py` fails if the two drift.

#### Environment dumps and credential stores — all four agents

Since three of four cannot restrict the environment, the shared hook carries the part that reaches
everyone:

| Command | Outcome |
| :--- | :--- |
| `env`, `printenv` (no command following) | **Blocked** — prints the whole environment |
| `printenv PYPI_TOKEN` | **Blocked** — secret-named variable |
| `printenv PATH` | Allowed — not secret-shaped |
| `env -u FORCE_COLOR doit check`, `env VAR=1 make` | Allowed — an *invocation*, not a dump |
| `cat ~/.pypirc`, `~/.netrc`, `~/.aws/credentials`, `~/.docker/config.json`, `gh/hosts.yml` | **Blocked** — credential stores |
| `cat ~/.copilot/config.json`, `~/.codex/auth.json`, `~/.claude/.credentials.json`, `~/.gemini/antigravity-cli/antigravity-oauth-token` | **Blocked** — AI CLI credential stores (#1043) |
| `echo hi; cat ~/.netrc`, `echo hi` *(newline)* `cat ~/.netrc`, `true` *(newline)* `printenv` | **Blocked** — a command position after a glued `;` or an unquoted newline counts (#1011) |

Both checks above are anchored on where a command *starts*, so they need a tokenizer that treats an
unquoted newline and a glued `;`/`&&`/`|` as separators of their own — `shlex.split` (what
`tokenize()` uses) treats a newline as ordinary whitespace and leaves a glued separator stuck to
its neighbour, so `hi;cat` never produced a `cat` in command position. `_structural_tokens` (built
for the merge rule, and now shared by these two checks) is a plain `shlex.shlex` lex instead, with
`;`, `&`, `|` and `\n` as punctuation characters.

**What this is and is not.** It reduces *accidental* exposure — a secret dumped into a transcript
that is then pasted into an issue, or read by a later summarisation step. It is not a boundary
against a determined agent, which has many other routes to the same value. That is true of the
hook as a whole, not only of this section — see
[ADR-9019](../../decisions/9019-the-dangerous-command-hook-is-a-guardrail-not-a-security-boundary.md) for the categories, the non-adversarial
assumption, and the rules governing what may be added. `$VAR` interpolation is
deliberately **not** blocked: legitimate uses are common, and blocking it would give false
assurance while being trivially avoided.

### Failure Behaviour

The hook uses two deny contracts, and they diverge on *failure*:

| Agents | Deny contract | If the hook produces nothing |
| :--- | :--- | :--- |
| Claude, Codex | exit code 2 + stderr | Blocked — a failed `python3` also exits non-zero |
| Copilot, Antigravity | stdout JSON, exit 0 | **Allowed** — "no payload" means "no objection" |

So for the stdout-contract CLIs, anything that stops the hook from printing its payload silently
removes protection. Two layers close that:

**In-script** (`block-dangerous-commands.py`) — `run()` wraps `main()` so an unexpected exception
denies instead of propagating, and unparsable stdin denies instead of returning `1` (which no CLI
treats as a block). Both paths call `_fail_closed()`, which emits *every* contract at once — a
single JSON object carrying both `decision` and `permissionDecision`, plus exit 2 and stderr —
because at that point the calling CLI is unknown.

**At the wiring** (`block-dangerous-commands.sh`) — a script that never starts cannot emit its own
deny, so the stdout-contract CLIs invoke this launcher instead of the `.py` directly. It denies
when `python3` or the hook script is unavailable.

The launcher checks those preconditions rather than the hook's exit status, deliberately: the hook
exits 2 on its own fail-closed path, which is indistinguishable from "`python3` could not find the
file". Branching on exit status would append a second deny payload after the hook's own, putting
two JSON objects on stdout.

Verified against the real CLIs — `agy`, `copilot`, and Claude Code all block on the combined
payload, and both stdout-contract CLIs tolerate the extra key and the non-zero exit. Codex
shares Claude's exit-2 contract.

**Known gap:** a syntax error in the hook script, or a hook timeout, still yields no payload and no
launcher precondition failure. Covering that would require the hook to emit something on every
invocation, including allows, which is a protocol change both stdout-contract CLIs would need to
tolerate.

### Testing

Run the test suite after making changes:

```bash
doit test
```

Output shows green for passing tests, red for failures:

```
Testing hook: /path/to/block-dangerous-commands.py

================================================================================
+ ALLOW (expected ALLOW) | safe command              | git status
+ ALLOW (expected ALLOW) | double quoted             | git commit -m "text with --admin"
+ BLOCK (expected BLOCK) | actual --admin flag       | gh pr merge --admin
================================================================================

Results: 134 passed, 0 failed
```

### Blocked Patterns

#### Dangerous Flags (always blocked)

| Flag | Reason |
|------|--------|
| `--admin` | Bypasses branch protection rules |
| `--no-verify` | Skips pre-commit/pre-push hooks |
| `--hard` | Hard reset - can lose uncommitted changes |

#### Dangerous Sequences (consecutive tokens)

| Sequence | Reason |
|----------|--------|
| `rm -rf /` | Destructive: removes root filesystem |
| `rm -rf ~` | Destructive: removes home directory |
| `sudo rm` | Privileged deletion |

#### Protected Branch Operations

Force push, delete, and merge operations are only blocked when targeting protected branches (`main`, `master`).

| Command | Result |
|---------|--------|
| `git push --force origin main` | BLOCKED |
| `git push --force origin feat/branch` | ALLOWED |
| `git push -f origin master` | BLOCKED |
| `git push --force` (no branch) | BLOCKED (safer default) |
| `git push origin --delete main` | BLOCKED |
| `git push origin :main` | BLOCKED |
| `git branch -D main` | BLOCKED |
| `git branch -D feat/old` | ALLOWED |
| `git merge branch` (on main) | BLOCKED (creates merge commit) |
| `git merge --ff-only branch` (on main) | ALLOWED (fast-forward only) |
| `git merge branch; echo --ff-only` (on main) | BLOCKED (`--ff-only` counts only on the merge itself) |
| `git merge branch\necho --ff-only` (on main) | BLOCKED (a newline doesn't end the command either) |
| `git merge branch # --ff-only` (on main) | BLOCKED (`#` starts a comment, not an argument) |
| `git --attr-source HEAD merge branch` (on main) | BLOCKED (`--attr-source` is a value-taking global option) |
| `git log --grep merge` (on main) | ALLOWED (a `git log`, not a merge) |
| `git merge branch` (on feature) | ALLOWED |
| `cat <<'EOF'` *(newline)* `"` *(newline)* `EOF` *(newline)* `git merge branch "` (on main) | BLOCKED (the merge rule reads the heredoc-stripped command, so the quote in the body doesn't swallow the merge after the terminator — #1011) |

#### Blocked Workflow Commands

These commands should use `doit` wrappers or require user approval:

| Command | Use Instead | Reason |
|---------|-------------|--------|
| `gh issue create` | `doit issue --type=<type>` | Ensures proper template and labels |
| `gh pr create` | `doit pr` | Ensures proper template format |
| `gh pr merge` | `doit pr_merge` | Enforces merge commit format: `<type>: <subject> (merges PR #XX, addresses #YY)` |
| `uv add` | User runs manually | Dependencies require human approval - suggest package, let user run command |
| `doit release*` | User runs manually | Releases require human approval - AI can help prepare but not execute |

#### Governance Labels

Some labels are governance controls that require human approval. AI agents are blocked from adding these labels:

| Label | Reason |
|-------|--------|
| `ready-to-merge` | Signals human approval that PR is ready for merge. Add manually via `gh pr edit --add-label ready-to-merge` or GitHub web UI. |

##### Opt-in: `ALLOW_AI_READY_TO_MERGE`

A human can grant an AI agent a one-session pass to apply the `ready-to-merge` label by setting an environment variable **before launching the AI CLI**:

```bash
export ALLOW_AI_READY_TO_MERGE=1
claude  # or copilot, codex, agy
```

The hook reads `os.environ` at hook-startup time (the AI CLI's process environment), so the variable must be set in the shell that launches the AI process — not by any command the AI itself runs. The AI has no path to set or persist this variable; attempts to do so are blocked (see [Env-Var Persistence Blocks](#env-var-persistence-blocks) below).

**Truthy values** (case-insensitive): `1`, `true`, `yes`, `on`. All other values (including empty string or unset) are falsy and preserve the block.

**Threat model:**

- The AI cannot set the variable in `os.environ` of its own parent process.
- The AI cannot persist the variable by writing to shell rc files, `.envrc`, `.env`, or AI CLI settings files — the hook blocks those writes.
- Each AI CLI session inherits a fixed snapshot of the environment; a Bash subprocess setting the variable does not affect the hook's already-read `os.environ`.
- The variable is scoped to a single shell session. Close the terminal (or `unset ALLOW_AI_READY_TO_MERGE`) to revoke the pass.

**To disable:** run `unset ALLOW_AI_READY_TO_MERGE`, or close the shell, or restart the AI CLI without the variable set.

#### Env-Var Persistence Blocks

The hook fires on **Edit**, **Write**, and **MultiEdit** (Claude/Codex), **write_file**/**replace** (retained for Gemini compatibility), **write_file**/**edit_file**/**write_to_file** (Antigravity), **create**/**edit** (Copilot, `path` key) and Copilot's patch-text **apply_patch** (see [Copilot CLI](#copilot-cli) above) in addition to Bash commands. Tool names are matched case-insensitively. Any other tool name is still checked when its input has the *shape* of a write — a path-shaped key (`file_path`, `path`, `filename`) plus a content-shaped key (`content`, `new_string`, `new_text`, `file_text`, `edits`) — rather than being allowed by default (#1037).

**Protected file basenames** (Bash redirect/`tee`/`cp`/`mv`/`dd`/`ln`/`install`/`rsync`/`sed -i` target, or a file-edit tool's path argument). A redirect counts in any spelling: `>`, `>>`, `>|`, `&>`, with an fd prefix (`1>>`), or glued to the word before it (`echo x>~/.bashrc`).

| File | Notes | Write blocked (Bash or file-edit tool) |
|------|-------|---------------------|
| `.bashrc`, `.zshrc`, `.profile`, `.bash_profile`, `.bash_login`, `.zshenv` | Shell init files | Always, whatever the content |
| `config.fish` | Only when parent path contains `.config/fish` | Always, whatever the content |
| `.envrc`, `.env`, `.env.local`, `.env.development`, `.env.production` | Project env files | Always, whatever the content |
| `copilot-hooks.json` | Any path (Copilot's env-injection vector) | Always, whatever the content |
| `.envrc.local` | Loaded by `.envrc` on every directory entry | Always, except the two documented Bash setup commands |
| `.envrc.local.example` | Source of the documented `cp` to `.envrc.local` | Always, whatever the content |
| `settings.json`, `settings.local.json` | Only when parent dir is `.claude` or `.copilot` | Only when `ALLOW_AI_READY_TO_MERGE` is literally present |
| `config.toml` | Only when parent dir is `.codex` | Only when `ALLOW_AI_READY_TO_MERGE` is literally present |

The first group — shell rc files, env files, `copilot-hooks.json` and `.envrc.local` — blocks a confirmed Bash write (redirect, `tee`/`cp`/`mv`/`dd`/`ln`/`install`/`rsync`, `sed -i`) outright, whatever it writes, rather than only when the literal `ALLOW_AI_READY_TO_MERGE` string appears. That closes a gap where the shell assembles the name at run time (`v=ALLOW_AI_; echo "export ${v}READY_TO_MERGE=1" >> ~/.bashrc`) and no token ever contains the literal name (#1037, and #1051 for `.envrc.local`). The project documents two agent-runnable writes to `.envrc.local` — `cp .envrc.local.example .envrc.local` and `echo 'export ENABLE_LSP_TOOL=1' >> .envrc.local` in [AI Agent Setup](../AI_SETUP.md) — so those stay allowed, but only as the whole top-level command. Anything run before them in the same command could change what they write, such as a shell function that shadows `echo`. So could a `bash -c` wrapper that exports such a function into its payload. `.envrc.local.example` is protected too, because it is the `cp`'s source: writing it first and then copying would carry any content into `.envrc.local`. The AI CLI settings files keep the literal-name requirement, because `cp .codex/config.toml ~/.codex/config.toml` is a documented setup step that must stay allowed. A script interpreter invoked inline (`python -c`, `perl -e`, …) whose script only *mentions* a target's basename is a "might write" heuristic rather than a confirmed write, and also keeps the literal-name requirement for every target, confirmed or not.

The hook sees the text of a write target, not what the shell expands it to, so it reads every expansion in a Bash write target as a wildcard and blocks the write if the result could name a file in the first group (#1055). That covers `${f}al`, `$(…)` and backtick substitution, globs (`.envrc.loca?`, `.envrc.l*l`, `[l]`) and brace expansion (`{l,}`). A target that is nothing but an expansion, such as `>> $f` or `>> "$GITHUB_OUTPUT"`, could expand to anything, so it is blocked too; write to a literal path instead. The destination of `cp`/`mv`/`install`/`rsync`/`ln`/`dd` is always read this way. A source glob is read only when its basename starts with a literal dot, such as `cp src/.envrc.loca? .` or `cp src/.[e]nvrc.local .` (#1061). Bash `*`, `?` and `[` never match a leading dot, so a glob can only reach a dotfile by writing the dot, and `cp src/* build/` and `cp src/*.py build/` still work. `dd` writes only its `of=` operand: the hook strips `of=` before matching, so `dd if=x of=.envrc.local` and `of=.envrc.loca?` are blocked, and ignores `if=`. For `sed -i` (also `--in-place`, any abbreviation such as `--in-pl`, and clusters such as `-ni`), every operand is matched against the literal names, and every operand after the script is read as dynamic too, not just the last (`sed -i s/a/b/ .envrc.loca? other.txt`). The script is the first operand unless `-e`/`-f` supplies it, attached (`-es/a/b/`, `-nes/a/b/`), abbreviated (`--expr=`) or not; it skips only the dynamic match, so `sed -i s/a/$/ file.txt` still works. An extglob (`.envrc.@(local)`, and the `+(`, `!(`, `?(` and `*(` forms) is read as a wildcard in every write target, redirect or command operand.

`git checkout <rev> [--] <path>` and `git restore [--source=<rev>] <path>` count as writes to `<path>`, which stops `.envrc.local.example` from being swapped for another version ahead of the allowed `cp`. With an explicit source, a broad pathspec covers the example too and is blocked: anything that normalizes to `.` or above it (`.`, `./.`, `src/..`, `../repo`), an absolute or `~` path, `:/` and any other `:` pathspec magic, and `--pathspec-from-file` (`git checkout HEAD~1 -- .`, `git restore --source=HEAD~1 :/`). Under `git -C` or `--work-tree` every pathspec counts as broad, since the root has moved. Abbreviated long options (`--sour=`, `--pathspec-from=`) are read as the full name. `git checkout main -- src/` stays allowed, since a subdirectory cannot hold a root file. Without a source the content comes from the index, so `git checkout -- .`, `git restore .` and `git restore --staged .` stay allowed.

Other git commands can rewrite the example as well (`stash pop`, `apply`, `am`, `cherry-pick`, `merge`, `checkout-index`, `read-tree -u`, `-c alias.*`). The hook does not list them, because most are everyday commands. It gates the sink instead: the allowed `cp .envrc.local.example .envrc.local` is blocked when `git diff --quiet HEAD -- .envrc.local.example` reports a difference (#1061). So `git stash pop` itself passes and the later `cp` is blocked. The gate fails open when git is missing, times out, is not in a repo or the file is untracked, as the hook is a guardrail (ADR-9019). If you edited the example on purpose, commit or restore it, or run the copy yourself. The `echo ... >> .envrc.local` setup line is not gated. HEAD is the reference point, so committing a modified example first defeats the gate; that leaves a commit in history for a human to see, which is the line ADR-9019 draws.

Known residual gaps, left open on purpose under ADR-9019: `cp src/.* build/` (a bare `.*` is too common), a `$var` source (`cp $src build/`), and source globs onto `copilot-hooks.json` or `config.fish` (no leading dot to key on).

A file-edit tool (Write, Edit, `apply_patch`, …) is blocked from every file in the first group whatever it writes, the same as a Bash write (#1051). bash or direnv runs these files when it loads them, so content that assembles the name (`v=ALLOW_AI_; export ${v}READY_TO_MERGE=1`) persists it without the literal string. That includes this template's own tracked `.envrc` and `.envrc.local.example`: a human edits them. The `ENABLE_LSP_TOOL` line goes in through the documented Bash `echo`, not an edit tool.

The AI CLI settings files keep a literal-string content check for file-edit tools too. They are JSON or TOML that no shell runs, and AI agents edit `.claude/`, `.github/hooks/`, `.agents/` and `.codex/` through their edit tools as normal, sanctioned work, which a blunter check would make impossible. For Copilot's `create`/`edit`, whose content key the hook has not confirmed, every string value in `tool_input` is scanned instead of one guessed key name.

**Example blocked Bash commands:**

```bash
# BLOCKED — AI cannot persist the variable via shell redirect
echo "export ALLOW_AI_READY_TO_MERGE=1" >> ~/.bashrc

# BLOCKED — any write to a shell rc file is blocked, not only one carrying
# the literal variable name
echo "PATH=/foo" >> ~/.bashrc

# ALLOWED — a documented, legitimate shell write to an AI CLI settings file
cp .codex/config.toml ~/.codex/config.toml
```

**Example blocked file edit:**

```
# BLOCKED — AI cannot persist the variable via Edit tool
Edit ~/.bashrc
  new_string: "export ALLOW_AI_READY_TO_MERGE=1"

# BLOCKED — any edit to a shell rc or env file, whatever it writes
Edit ~/.bashrc
  new_string: "export PATH=$PATH:/usr/local/bin"
```

### Adding New Patterns

Edit `tools/hooks/ai/block-dangerous-commands.py`:

```python
# Add a new always-blocked flag
DANGEROUS_FLAGS = {
    "--admin": "Bypasses branch protection rules",
    "--new-flag": "Description of why it's dangerous",
}

# Add a new dangerous sequence
DANGEROUS_SEQUENCES = [
    (["rm", "-rf", "/"], "Destructive: removes root filesystem"),
    (["new", "dangerous", "sequence"], "Why it's dangerous"),
]

# Add a new protected branch
PROTECTED_BRANCHES = {"main", "master", "production"}
```

Then run the test suite to verify.

## Related

- [AI Enforcement Principles](enforcement-principles.md) - Why and how we enforce rules in code
- [AGENTS.md](../../../AGENTS.md) - AI agent rules including "When Blocked Protocol"
- [AI Agent Setup](../AI_SETUP.md) - Setting up AI coding assistants
