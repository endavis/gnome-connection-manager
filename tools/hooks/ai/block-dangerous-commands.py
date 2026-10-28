#!/usr/bin/env python3
"""
Claude Code PreToolUse hook to block dangerous command patterns.

This hook intercepts Bash commands and file-edit operations before execution
and blocks those containing dangerous flags or attempting to persist the
ALLOW_AI_READY_TO_MERGE env var to shell configuration files.

Uses shlex to properly parse shell quoting, then checks for dangerous
patterns as standalone tokens (not embedded in quoted argument values).

Exit codes:
  0 - Allow command
  2 - Block command (shows stderr to Claude)

For full documentation, see: docs/development/ai/command-blocking.md
"""

import fnmatch
import json
import os
import posixpath
import re
import shlex
import subprocess  # nosec B404 - needed for git branch detection
import sys
from pathlib import Path

# Protected branches - operations on these require extra scrutiny
PROTECTED_BRANCHES = {"main", "master"}

# Dangerous flags that must appear as exact standalone tokens
DANGEROUS_FLAGS = {
    "--admin": "Bypasses branch protection rules",
    "--no-verify": "Skips pre-commit/pre-push hooks",
    "--hard": "Hard reset - can lose uncommitted changes",
}

# Dangerous token sequences (checked in order)
# Format: (token_sequence, description)
DANGEROUS_SEQUENCES = [
    (["rm", "-rf", "/"], "Destructive: removes root filesystem"),
    (["rm", "-rf", "~"], "Destructive: removes home directory"),
    (["sudo", "rm"], "Privileged deletion"),
]

# Force push flags (matched as exact token OR as prefix before "=")
FORCE_PUSH_FLAGS = {"--force", "-f", "--force-with-lease"}

# Blocked workflow commands - use doit wrappers or require user approval
BLOCKED_WORKFLOW_COMMANDS = {
    ("gh", "issue", "create"): "Use 'doit issue --type=<type>' instead of 'gh issue create'",
    ("gh", "pr", "create"): "Use 'doit pr' instead of 'gh pr create'",
    ("gh", "pr", "merge"): "Use 'doit pr_merge' instead of 'gh pr merge'",
    ("uv", "add"): (
        "Adding dependencies requires user approval. "
        "Suggest the package and let the user run 'uv add <package>' manually."
    ),
    ("doit", "release"): (
        "Releases must be run manually by the user, not by AI agents. "
        "AI can help prepare (check commit messages, verify CI) but not execute releases."
    ),
    ("doit", "release_tag"): "Releases must be run manually by the user, not by AI agents.",
}

# Governance labels that require human approval - AI should never add these
GOVERNANCE_LABELS = {
    "ready-to-merge": (
        "The 'ready-to-merge' label is a governance control requiring human approval. "
        "Add this label manually via 'gh pr edit --add-label ready-to-merge' or the GitHub web UI, "
        "or set ALLOW_AI_READY_TO_MERGE=1 in the shell before launching the AI CLI."
    ),
}

# Secret-shaped environment variable names. THIS IS THE SINGLE SOURCE OF TRUTH:
# `.codex/config.toml`'s `[shell_environment_policy] exclude` list must match it,
# and tests/template/test_secret_env_policy.py asserts the two agree so the
# patterns cannot drift between the hook and the one CLI that can enforce them
# natively (#682).
SECRET_ENV_PATTERNS: tuple[str, ...] = (
    "*_API_KEY",
    "*_SECRET",
    "*_TOKEN",
    "PASSWORD",
    "PYPI_TOKEN",
    "CODECOV_TOKEN",
)

# Credential stores. Reading one dumps live secrets into the transcript, which
# is the accidental-exposure case this guards; a determined agent has other
# routes, so this is a guardrail rather than a boundary. Each basename maps to
# the parent directories it is a credential store under; an empty tuple means
# any parent. `config.json` is a store under `.docker` and `.copilot` alone, so
# an ordinary project `config.json` is still readable (#1043).
CREDENTIAL_FILE_BASENAMES: dict[str, tuple[str, ...]] = {
    ".pypirc": (),
    ".netrc": (),
    "credentials": (".aws",),
    "hosts.yml": ("gh",),
    "config.json": (".docker", ".copilot"),
    "auth.json": (".codex",),
    ".credentials.json": (".claude",),
    "antigravity-oauth-token": ("antigravity-cli",),
}

# Commands that read a file's contents. The credential check is anchored on
# these rather than scanning every token, so a file that merely *mentions* a
# credential path is not mistaken for one that reads it.
_CREDENTIAL_READER_COMMANDS = frozenset(
    {
        "cat",
        "bat",
        "less",
        "more",
        "head",
        "tail",
        "strings",
        "xxd",
        "od",
        "base64",
        "cp",
        "mv",
        "scp",
        "rsync",
        "install",
        "openssl",
        "shasum",
    }
)

# Tokens that end one command's argument list. Output redirection is included
# because it flips the reader into a writer: `cat >> file <<EOF` streams a
# heredoc *into* a file, and the body must not be scanned as if it were
# arguments. Input redirection is deliberately absent so `cat < ~/.netrc`
# is still caught.
_SHELL_OPERATORS = frozenset({"&&", "||", ";", "|", "&", ">", ">>", "1>", "2>", "&>"})

# Commands that print the whole environment when given no command to run.
_ENV_DUMP_COMMANDS = frozenset({"env", "printenv"})

# `env` options that consume a following token, so the scan can tell an
# invocation (`env -u FOO cmd`) from a dump (`env`).
_ENV_OPTS_WITH_VALUE = frozenset({"-u", "--unset"})

# Env var name the human can set to allow AI to apply ready-to-merge
ALLOW_AI_READY_TO_MERGE_VAR = "ALLOW_AI_READY_TO_MERGE"

# Persistence-protected file basenames and path hints.
# Keys are basenames; values are optional required parent path fragments
# (if non-empty, the parent directory must contain that fragment).
ENV_PERSISTENCE_TARGETS: dict[str, str] = {
    ".bashrc": "",
    ".zshrc": "",
    ".profile": "",
    ".bash_profile": "",
    ".bash_login": "",
    ".zshenv": "",
    "config.fish": ".config/fish",
    ".envrc": "",
    ".envrc.local": "",
    # The source of the allowed `cp` below: writing it first, then copying,
    # would carry any content into `.envrc.local` (#1051).
    ".envrc.local.example": "",
    ".env": "",
    ".env.local": "",
    ".env.development": "",
    ".env.production": "",
    "copilot-hooks.json": "",
}

# Whole Bash commands that may write an ENV_PERSISTENCE_TARGETS file anyway.
# `.envrc` loads `.envrc.local` on every directory entry, so a confirmed write
# to it is blocked whatever its content, like `.envrc` (#1051). This project
# documents these agent-runnable writes to it (README, CONTRIBUTING.md,
# AI_SETUP.md), so they stay allowed. The whole command must match: a token
# list compares quoting-insensitively, and nothing before the write (such as a
# shell function shadowing `echo`) can change what it writes. For the same
# reason it applies only to the top-level command, never to a `bash -c` or
# heredoc payload, whose wrapper can export a function into it first.
_ALLOWED_ENV_PERSISTENCE_WRITES: frozenset[tuple[str, ...]] = frozenset(
    tuple(shlex.split(command))
    for command in (
        "cp .envrc.local.example .envrc.local",
        "echo 'export ENABLE_LSP_TOOL=1' >> .envrc.local",
    )
)

# The one allowed write whose source another command can swap out: `cp` is the
# sink for every git working-tree writer (`stash pop`, `apply`, `am`, `merge`,
# an alias ...), so it is allowed only while the example matches HEAD (#1061).
_ENVRC_EXAMPLE = ".envrc.local.example"
_ALLOWED_ENVRC_COPY: tuple[str, ...] = tuple(shlex.split(f"cp {_ENVRC_EXAMPLE} .envrc.local"))

# Settings files that are only protected when inside a known AI CLI config dir
_AI_CLI_SETTINGS_TARGETS: dict[str, set[str]] = {
    "settings.json": {".claude", ".gemini", ".copilot"},
    "settings.local.json": {".claude", ".gemini", ".copilot"},
    "config.toml": {".codex"},
}


def _env_truthy(name: str) -> bool:
    """Return True when env var *name* is set to a truthy value.

    Truthy values (case-insensitive): ``1``, ``true``, ``yes``, ``on``.
    All other values (including empty string) are falsy.
    """
    val = os.environ.get(name, "").strip().lower()
    return val in {"1", "true", "yes", "on"}


_DYNAMIC_CHARS = frozenset("$`*?[{\\")


def _scan_dynamic_path(path_str: str) -> list[tuple[str, str | None]]:
    """Split *path_str* into ``(literal_char, None)`` / ``("", regex)`` parts.

    Each shell expansion becomes a wildcard part, so a caller can ask whether
    the path *could* expand to a protected name (#1055). Only ``$name``, ``*``
    and ``?`` are read exactly. Every other expansion -- ``${...}``,
    ``$(...)``, ``$'...'``, a special parameter, a backtick, ``[...]``,
    ``{...}``, a backslash left by quoting -- turns the rest of the path into
    one wildcard: their bash grammar (nesting, ``[]x]``, ANSI-C escapes) is
    too easy to parse differently from the shell, so fail closed instead.
    """
    parts: list[tuple[str, str | None]] = []
    i = 0
    n = len(path_str)
    while i < n:
        ch = path_str[i]
        if ch == "$" and i + 1 < n and (path_str[i + 1].isalpha() or path_str[i + 1] == "_"):
            j = i + 1
            while j < n and (path_str[j].isalnum() or path_str[j] == "_"):
                j += 1
            parts.append(("", ".*"))
            i = j
        elif ch == "*":
            parts.append(("", ".*"))
            i += 1
        elif ch == "?":
            parts.append(("", "."))
            i += 1
        elif ch in _DYNAMIC_CHARS:
            parts.append(("", ".*"))
            break
        else:
            parts.append((ch, None))
            i += 1
    return parts


def _matches_dynamic_env_persistence_target(path_str: str) -> bool:
    """Return True when *path_str*, with its shell expansions read as
    wildcards, could name an ``ENV_PERSISTENCE_TARGETS`` file (#1055).

    The hook sees the text of a write target, not what the shell makes of it,
    so ``>> ${f}al`` or ``>> .envrc.loca?`` slipped past the literal match.
    Fail closed: every expansion matches anything, so ``>> $f`` matches every
    target. A parent path holding an expansion may supply any fragment
    ``ENV_PERSISTENCE_TARGETS`` asks for. Only a path with an expansion is
    treated this way; a literal path is left to the literal match.
    """
    if not _DYNAMIC_CHARS & set(path_str):
        return False
    parts = _scan_dynamic_path(path_str.rstrip("/"))
    # The basename starts after the last literal "/" -- one inside an
    # expansion (`$(dirname $0)/x`) is part of that wildcard.
    split = 0
    for idx, (lit, rx) in enumerate(parts):
        if rx is None and lit == "/":
            split = idx + 1
    parent, base = parts[:split], parts[split:]
    if not base:
        return False
    pattern = re.compile("".join(re.escape(lit) if rx is None else rx for lit, rx in base))
    parent_dynamic = any(rx is not None for _, rx in parent)
    parent_text = "".join(lit for lit, rx in parent if rx is None)
    for name, fragment in ENV_PERSISTENCE_TARGETS.items():
        if pattern.fullmatch(name) and (not fragment or parent_dynamic or fragment in parent_text):
            return True
    return False


def _matches_env_persistence_target(path_str: str, *, dynamic: bool = False) -> bool:
    """Return True when *path_str* matches a bare ``ENV_PERSISTENCE_TARGETS``
    basename (+ optional parent-path fragment).

    With *dynamic*, a path whose shell expansions could spell such a name also
    matches (:func:`_matches_dynamic_env_persistence_target`, #1055). Only the
    Bash write check asks for it: a file-edit tool's path is not shell text.

    Split out from the former single-function ``_is_env_persistence_target``
    so the Bash write check can tell this category apart from
    ``_AI_CLI_SETTINGS_TARGETS``: a confirmed write to one of these -- a shell
    rc file, an env file, or ``copilot-hooks.json`` -- is blocked whatever its
    content, while a settings file still needs the literal var name (#1037,
    decision b).
    """
    if not path_str:
        return False

    try:
        # Expand ~ so ~/.bashrc comparisons work
        path = Path(path_str).expanduser()
    except (ValueError, RuntimeError):
        return False

    basename = path.name
    if basename not in ENV_PERSISTENCE_TARGETS:
        return dynamic and _matches_dynamic_env_persistence_target(path_str)

    fragment = ENV_PERSISTENCE_TARGETS[basename]
    if not fragment:
        return True
    # Fragment must appear in the parent path string
    if fragment in path.parent.as_posix():
        return True
    # ...or a parent expansion may supply it (`$HOME/.config/fi*/config.fish`)
    return dynamic and _matches_dynamic_env_persistence_target(path_str)


def _matches_ai_cli_settings_target(path_str: str) -> bool:
    """Return True when *path_str* matches an ``_AI_CLI_SETTINGS_TARGETS``
    file inside its allowed parent dir.

    These still require the literal var name on the Bash write path (#1037,
    decision b): ``cp .codex/config.toml ~/.codex/config.toml`` is a
    documented, legitimate setup step
    (``docs/development/AI_SETUP.md``), so blocking every write to
    ``config.toml`` whatever its content would break it.
    """
    if not path_str:
        return False

    try:
        # Expand ~ so ~/.config comparisons work
        path = Path(path_str).expanduser()
    except (ValueError, RuntimeError):
        return False

    allowed_parents = _AI_CLI_SETTINGS_TARGETS.get(path.name)
    if allowed_parents is None:
        return False
    return path.parent.name in allowed_parents


def _is_env_persistence_target(path_str: str, *, dynamic: bool = False) -> bool:
    """Return True when *path_str* points to a file that the AI must not use
    to persist the ``ALLOW_AI_READY_TO_MERGE`` env var.

    Checks:
    - Basename + optional parent-path fragment (ENV_PERSISTENCE_TARGETS)
    - AI CLI settings files only when the immediate parent dir is in the
      corresponding allow-list (_AI_CLI_SETTINGS_TARGETS)
    """
    return _matches_env_persistence_target(
        path_str, dynamic=dynamic
    ) or _matches_ai_cli_settings_target(path_str)


def tokenize(command: str) -> list[str]:
    """
    Tokenize command using shlex for proper shell quote handling.

    shlex.split() correctly handles:
    - Double quoted strings: "text with --admin"
    - Single quoted strings: 'text with --force'
    - Embedded quotes: --body="value"
    - Escape sequences

    Returns list of tokens with quotes stripped from values.
    """
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        # Fallback for malformed quotes - try non-POSIX mode
        try:
            return shlex.split(command, posix=False)
        except ValueError:
            # Last resort - simple whitespace split
            return command.split()


def _normalize_branch_ref(token: str) -> str:
    """Return the destination branch name from a git refspec token.

    Strips a leading ``+`` (force-push marker), takes the last segment after
    ``:`` (the *destination* side of a refspec — ``src:dst`` pushes local
    ``src`` to remote ``dst``), then takes the last segment after ``/``
    (strip remote or ``refs/heads/`` prefix).

    Examples::

        "HEAD:main"           -> "main"
        "+main"               -> "main"
        "main:feature"        -> "feature"
        "HEAD:refs/heads/dev" -> "dev"
        "origin/main"         -> "main"
        "main"                -> "main"
    """
    if token.startswith("+"):
        token = token[1:]
    # Take destination side of refspec (last segment after ":")
    token = token.split(":")[-1]
    # Strip remote/refs prefix (last segment after "/")
    token = token.split("/")[-1]
    return token


# Git global options that consume a SEPARATE following token (value).
# Options written as "--opt=val" already consume one token; these are the
# ones that use "--opt val" (two-token) form and must skip an extra token.
_GIT_GLOBAL_OPTS_WITH_VALUE = frozenset(
    {
        "-C",
        "-c",
        "--git-dir",
        "--work-tree",
        "--namespace",
        "--exec-path",
        "--super-prefix",
        "--list-cmds",
        # Added for #1007, gap 6: without these, `_git_subcommand_index` took
        # the option's value as the subcommand, so e.g.
        # `git --attr-source HEAD merge feature` was never recognised as
        # `merge` and the merge-to-protected rule did not fire.
        "--attr-source",
        "--config-env",
    }
)

# Note: git global flags that consume no value (``--paginate``, ``--bare``,
# ``--no-pager``, ...) need no explicit list — ``_git_subcommand_index`` treats
# any token starting with "-" that is not in _GIT_GLOBAL_OPTS_WITH_VALUE as a
# single-token flag, which covers them and any future additions.


def _git_subcommand_index(tokens: list[str], git_idx: int) -> int | None:
    """Return the index of the git subcommand token, skipping global options.

    ``git`` global options appear between the ``git`` token and the subcommand.
    For example::

        git -C /path push ...       => subcommand index is git_idx + 3
        git -c k=v push ...         => subcommand index is git_idx + 3
        git --git-dir=.git push ... => subcommand index is git_idx + 2
        git push ...                => subcommand index is git_idx + 1

    Options written in ``--opt=val`` form (one token) consume only themselves.
    Options written in ``--opt val`` form (two tokens) consume themselves plus
    the next token.

    Returns ``None`` if the end of ``tokens`` is reached before finding a
    subcommand (malformed or truncated input).
    """
    i = git_idx + 1
    while i < len(tokens):
        tok = tokens[i]
        if tok.startswith("-"):
            # Check if it's a known two-token option (written without "=")
            if tok in _GIT_GLOBAL_OPTS_WITH_VALUE:
                i += 2  # skip option AND its value
            else:
                # Either a one-token flag or an "--opt=val" option
                i += 1
        else:
            # First non-flag token is the subcommand
            return i
    return None


def _wrapped_payloads(tokens: list[str]) -> list[str]:
    """Return shell payloads from ``bash/sh/zsh/dash -c <payload>`` and ``eval ...``.

    Yields (as a list) the payload strings that would be re-executed by the
    shell wrapper so ``check_command`` can recurse into them.
    """
    shell_names = frozenset({"bash", "sh", "zsh", "dash"})
    payloads: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i].lower()
        if tok in shell_names:
            # Look for a -c flag immediately after (possibly with --login etc.)
            j = i + 1
            while j < len(tokens) and tokens[j].startswith("-") and tokens[j] != "-c":
                j += 1
            if j < len(tokens) and tokens[j] == "-c" and j + 1 < len(tokens):
                payloads.append(tokens[j + 1])
        elif tok == "eval" and i + 1 < len(tokens):
            # eval "..." — join all remaining tokens as a single payload
            payloads.append(" ".join(tokens[i + 1 :]))
            break
        i += 1
    return payloads


# POSIX shells that run their stdin as a *shell* program. A heredoc feeding one
# of these is shell code and must be scanned the way `bash -c <payload>` already
# is.
#
# Deliberately shells only. `python3 - <<EOF`, `perl`, `ruby` and `node` also run
# their stdin, but as Python/Perl/Ruby/JS -- `printenv PYPI_TOKEN` in a Python
# heredoc is a SyntaxError, not a dump. Scanning those bodies for shell patterns
# would block string literals while still missing the real risk
# (`os.system("cat ~/.netrc")`), so it buys false positives and no coverage.
# Their bodies stay in the outer token scan, which is unchanged.
_STDIN_INTERPRETERS = frozenset({"bash", "sh", "zsh", "dash"})

# `<<EOF`, `<<-EOF`, `<<'EOF'`, `<<"EOF"`, `<<\EOF`. Groups: (1) the `-` of
# `<<-` (its own group so callers know whether to strip leading tabs), then
# one of (2/3) a quoted delimiter, (4) a backslash-escaped one, or (5) a bare
# one.
_HEREDOC_START = re.compile(
    r"<<(-)?\s*(?:(['\"])([A-Za-z_][A-Za-z0-9_]*)\2|\\([A-Za-z_][A-Za-z0-9_]*)|([A-Za-z_][A-Za-z0-9_]*))"
)


def _heredoc_terminator(line: str, strip_leading_tabs: bool) -> str:
    """Return *line* as the shell would compare it to the heredoc delimiter.

    Plain ``<<`` heredocs end only on a line that *exactly* equals the
    delimiter -- a real shell does not strip surrounding whitespace, so a
    terminator with leading or trailing blanks does not end the body (#1007,
    gap 2). ``<<-`` additionally strips leading tab characters -- not any
    other whitespace -- from both the terminator and the body before the
    shell compares them.
    """
    return line.lstrip("\t") if strip_leading_tabs else line


# Common prefixes that run another command without being an interpreter
# themselves, e.g. `env bash <<EOF` and `sudo sh <<EOF` (#1007, gap 3). Known
# limit: a wrapper's own flags (`env -i`, `sudo -u user`) are not skipped, so
# those forms fall through to "not an interpreter" rather than being resolved
# to the command after them.
_COMMAND_PREFIX_WRAPPERS = frozenset({"env", "sudo", "nice", "command"})

# `NAME=value` assignment prefix, as in `env FOO=1 bash <<EOF`.
_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# Shell options that take a separate following token as their value, so
# `bash -o errexit <<EOF` must not mistake `errexit` for a script argument
# (#1007, gap 3).
_SHELL_OPTS_WITH_VALUE = frozenset({"-o", "-O", "+o", "--rcfile", "--init-file"})


def _reads_stdin_as_code(words: list[str]) -> bool:
    """Whether the command in *words* will execute a heredoc body as a program.

    `bash <<EOF` and `sh -s <<EOF` run their body as shell; `bash script.sh
    <<EOF` and `cat >> notes.md <<EOF` feed it to something as input. The
    difference is whether a script argument appears before the heredoc operator.

    A wrapper (`env`, `sudo`, `nice`, `command`) or a leading `NAME=value`
    assignment is skipped first, so `env bash <<EOF` resolves to `bash`.
    """
    index = 0
    while index < len(words):
        word = words[index]
        base = word.rsplit("/", 1)[-1].lower()
        if base in _COMMAND_PREFIX_WRAPPERS or _ASSIGNMENT_RE.match(word):
            index += 1
            continue
        break
    if index >= len(words):
        return False
    if words[index].rsplit("/", 1)[-1].lower() not in _STDIN_INTERPRETERS:
        return False
    index += 1
    while index < len(words):
        word = words[index]
        if word.startswith("<<"):
            break
        if word == "-":
            return True  # explicit "read the program from stdin"
        if word in _SHELL_OPTS_WITH_VALUE:
            index += 2  # the option and its separate value
            continue
        if word.startswith(("-", "+")):
            index += 1  # some other flag; keep looking
            continue
        return False  # a script path: the heredoc is that script's input
    return True  # bare `bash <<EOF` reads the program from stdin


# Returned by `_heredoc_marker_match` as the open "quote" once a line nests an
# expansion inside a double quote, where bash's quoting is no longer
# a single flat state this scan can follow (#1011).
_QUOTING_UNCLEAR = "$("


def _heredoc_marker_match(line: str, quote: str = "") -> tuple[re.Match[str] | None, str]:
    """Return the first ``_HEREDOC_START`` match outside quotes and comments.

    A bare ``.search()`` over the raw line, as used before this fix, takes any
    ``<<`` on the line -- including one inside a quoted string. ``echo
    "<<EOF"`` was therefore mistaken for a real heredoc marker, and the lines
    after it were dropped from the credential-read check as though they were
    its body (regression from #1010, gap 1). This walks the line with the same
    quote-and-comment state machine :func:`_strip_shell_comments` uses --
    single- and double-quoted runs are skipped, a backslash escapes the next
    character outside single quotes, and an unquoted ``#`` ends the scan --
    and only tries the marker regex where that state is bare.

    *quote* is the quote still open from the previous line, and the second
    item returned is the quote still open at the end of this one, so a
    ``<<EOF"`` that closes a string opened on an earlier line is not taken as
    a marker either (#1011).

    Inside a double quote, ``$(``, ``${`` or a backtick starts an expansion
    whose own quotes nest (``"$(echo "x")"``, ``"${x:-"y"}"``), which a flat
    quote state cannot follow. The scan stops there and returns ``_QUOTING_UNCLEAR`` as the quote,
    so the caller can fail closed.
    """
    found: re.Match[str] | None = None
    word_start = not quote
    index = 0
    while index < len(line):
        char = line[index]
        if quote == "'":
            if char == "'":
                quote = ""
            index += 1
            continue
        if char == "\\" and index + 1 < len(line):
            index += 2
            word_start = False
            continue
        if quote:
            if char == "`" or line.startswith(("$(", "${"), index):
                return found, _QUOTING_UNCLEAR
            if char == quote:
                quote = ""
            index += 1
            continue
        if char in "'\"":
            quote = char
            index += 1
            word_start = False
            continue
        if char == "#" and word_start:
            break  # the rest of the line is a comment
        if line.startswith("<<<", index):
            # A here-string, not a heredoc: its word is on this line and
            # nothing after it is a body. Matching from the second `<` read
            # `<<<EOF` as a heredoc on EOF (#1025).
            index += 3
            word_start = True
            continue
        if line.startswith("$((", index) or (word_start and line.startswith("((", index)):
            # Arithmetic, where `<<` is a left shift: `$((1<<EOF))` is no
            # heredoc (#1025). Skip to the matching `))`. Arithmetic left open
            # at the end of the line is unclear, so fail closed.
            end = _arithmetic_end(line, index + (1 if char == "$" else 0))
            if end is None:
                return found, _QUOTING_UNCLEAR
            index = end
            word_start = False
            continue
        if found is None and char == "<" and line[index + 1 : index + 2] == "<":
            found = _HEREDOC_START.match(line, index)
        word_start = char in _COMMENT_WORD_BOUNDARY
        index += 1
    return found, quote


def _arithmetic_end(line: str, start: int) -> int | None:
    """Return the index just past the ``))`` closing the ``((`` at *start*.

    Counts parentheses, so ``$(( (1<<2) ))`` closes at the outer pair. Returns
    None when the line ends first.
    """
    depth = 0
    for index in range(start, len(line)):
        if line[index] == "(":
            depth += 1
        elif line[index] == ")":
            depth -= 1
            if depth == 0:
                return index + 1
    return None


def _heredocs(lines: list[str]) -> list[tuple[int, list[str], int, int]]:
    """Find each heredoc in *lines*.

    Returns ``(marker_line, owner_words, body_start, body_end)`` per heredoc:
    the line holding the ``<<`` marker, the words of the command that owns it,
    and the body as the half-open line range ``[body_start, body_end)``. The
    terminator, when present, is line ``body_end``.
    """
    found: list[tuple[int, list[str], int, int]] = []
    quote = ""  # a quote left open by an earlier line; a body never changes it
    index = 0
    while index < len(lines):
        match, quote = _heredoc_marker_match(lines[index], quote)
        if quote == _QUOTING_UNCLEAR:
            # A command substitution inside a double quote: its own quotes
            # nest, so whether a later `<<` is a marker is unclear. Stop
            # finding heredocs, as for a marker line ending inside a quote.
            break
        if not match:
            index += 1
            continue
        if quote:
            # The marker line ends inside a quote, which the shell keeps
            # reading into the lines that look like the body. Where the body
            # really starts is unclear, so stop finding heredocs: nothing from
            # here on is stripped, and every later line stays in the scans.
            break

        strip_leading_tabs = bool(match.group(1))
        delimiter = match.group(3) or match.group(4) or match.group(5)
        # The command owning this heredoc is the last segment before it.
        words = re.split(r"[;&|]", lines[index][: match.start()])[-1].split()

        cursor = index + 1
        while (
            cursor < len(lines)
            and _heredoc_terminator(lines[cursor], strip_leading_tabs) != delimiter
        ):
            cursor += 1

        found.append((index, words, index + 1, cursor))
        index = cursor + 1
    return found


def _heredoc_payloads(command: str) -> list[str]:
    """Return the lines of every heredoc body that its receiver will execute.

    `check_command` recurses into `bash -c <payload>` through
    :func:`_wrapped_payloads`, but a heredoc on stdin is not `-c`, so the body
    was never re-scanned. The checks that match a token in any position caught
    it anyway; the ones needing a command position did not, so
    `bash <<EOF cat ~/.netrc EOF` ran while `bash -c "cat ~/.netrc"` was blocked
    (#762).

    Each line is yielded separately because each is its own command to the
    shell, and a command position is what the missing checks require.
    """
    lines = command.splitlines()
    payloads: list[str] = []
    for _marker, words, body_start, body_end in _heredocs(lines):
        if _reads_stdin_as_code(words):
            payloads += [line for line in lines[body_start:body_end] if line.strip()]
    return payloads


def _without_heredoc_bodies(command: str) -> str:
    """Return *command* with every heredoc body and terminator line removed.

    A body is the receiver's stdin, not its arguments. The credential-read
    check scans a reader's arguments past a redirection (#1007, gap 4), so
    without this `cat >> notes.md <<EOF` would read its own body's text as
    file names. A body that is run as code is still checked, line by line,
    through :func:`_heredoc_payloads`.
    """
    lines = command.splitlines()
    dropped: set[int] = set()
    for _marker, _words, body_start, body_end in _heredocs(lines):
        dropped.update(range(body_start, body_end + 1))
    return "\n".join(line for number, line in enumerate(lines) if number not in dropped)


# A commit message is data, but a heredoc carrying one is scanned as arguments,
# so a message that *names* a blocked pattern is refused as if it invoked it
# (#759). The scanner is not taught to recognise prose -- that would mean
# skipping bodies for an allowlist of receivers, where a mistake is a bypass
# (ADR-9019, rule 3). The message is passed by file instead, and this turns the
# block into the redirect that says so.
_COMMIT_HEREDOC_REDIRECT = (
    "A commit message passed by heredoc is scanned as command arguments, so a "
    "message naming a blocked pattern is refused. Write the message to "
    "tmp/agents/<agent-type>/ and pass it with `git commit -F <file>` "
    "(.github/CONTRIBUTING.md, Commit Guidelines)."
)


def _is_commit_message_heredoc(command: str) -> bool:
    """Whether *command* is a ``git commit`` whose message arrives by heredoc.

    Detection only -- the body is never inspected, so this adds no parsing to
    the scan and cannot change what is blocked. It changes what the block says.
    """
    for line in command.splitlines():
        match = _HEREDOC_START.search(line)
        if not match:
            continue
        # Only the command that *owns* the heredoc counts. Scanning every line
        # would match a `git commit` example quoted inside another command's
        # body and hand back a redirect that does not apply to it.
        words = re.split(r"[;&|]", line[: match.start()])[-1].split()
        if len(words) >= 2 and words[0].rsplit("/", 1)[-1] == "git" and "commit" in words[1:3]:
            return True
    return False


def redirect_reason(command: str, reason: str) -> str:
    """Replace *reason* with an actionable one where the repo has a better path.

    Block-and-redirect (`docs/development/ai/enforcement-principles.md`): a block
    that does not say what to do instead costs a turn and teaches nothing.
    """
    if reason and _is_commit_message_heredoc(command):
        return _COMMIT_HEREDOC_REDIRECT
    return reason


def check_dangerous_flags(tokens: list[str]) -> tuple[bool, str]:
    """
    Check if any dangerous flag appears as a standalone token.

    A flag in a quoted argument value (e.g., -m "--admin mentioned")
    becomes part of a larger token and won't match.
    """
    for token in tokens:
        if token in DANGEROUS_FLAGS:
            return True, DANGEROUS_FLAGS[token]
    return False, ""


def check_dangerous_sequences(tokens: list[str]) -> tuple[bool, str]:
    """
    Check if dangerous token sequences appear in the command.

    Looks for consecutive tokens matching dangerous patterns.
    """
    tokens_lower = [t.lower() for t in tokens]

    for sequence, reason in DANGEROUS_SEQUENCES:
        seq_len = len(sequence)
        for i in range(len(tokens_lower) - seq_len + 1):
            if tokens_lower[i : i + seq_len] == [s.lower() for s in sequence]:
                return True, reason
    return False, ""


def check_push_to_protected(tokens: list[str]) -> tuple[bool, str]:
    """
    Check if command is a push (regular or force) while on a protected branch.

    Blocks any git push when the current branch is a protected branch.
    Force pushes to protected branches are also blocked even from feature branches.

    Scans all positions to handle chained commands (e.g., git status; git push --force).
    Handles git global options (e.g., ``git -C /path push ...``).
    Handles refspec forms (e.g., ``HEAD:main``, ``+main``).

    Tokens beginning with ``:`` are deletion refspecs — they are owned by
    ``check_delete_protected_branch`` and skipped here to preserve correct
    block-reason messages.
    """
    tokens_lower = [t.lower() for t in tokens]

    # Must be a git push command (not git stash push, etc.)
    if "git" not in tokens_lower or "push" not in tokens_lower:
        return False, ""

    # Find ALL positions where git + push appear as a pair
    for git_idx in range(len(tokens_lower) - 1):
        if tokens_lower[git_idx] != "git":
            continue

        # Resolve subcommand index, skipping git global options
        subcommand_idx = _git_subcommand_index(tokens, git_idx)
        if subcommand_idx is None:
            continue
        if tokens_lower[subcommand_idx] != "push":
            continue

        # Determine the end of this git push command (next git/doit/gh/uv token or end)
        cmd_end = len(tokens)
        for j in range(subcommand_idx + 1, len(tokens_lower)):
            if tokens_lower[j] in ("git", "doit", "gh", "uv"):
                cmd_end = j
                break
        cmd_tokens = tokens[git_idx:cmd_end]

        # Check if any force flag is present (prefix-aware for --force-with-lease=<ref>)
        has_force_flag = any(
            t == flag or t.startswith(flag + "=") for t in cmd_tokens for flag in FORCE_PUSH_FLAGS
        )

        # Look for branch name in tokens after 'push'.
        # Skip flags (tokens starting with -) and deletion refspecs (start with :).
        after_push = [
            t
            for t in tokens[subcommand_idx + 1 : cmd_end]
            if not t.startswith("-") and not t.startswith(":")
        ]

        # Check if explicitly pushing to a protected branch via refspec or branch name
        for token in after_push:
            branch = _normalize_branch_ref(token)
            if branch.lower() in PROTECTED_BRANCHES:
                action = "Force push" if has_force_flag else "Push"
                return True, f"{action} to protected branch '{branch}'"

        # Check if currently on a protected branch (catches bare `git push`)
        current_branch = get_current_branch()
        if (
            current_branch
            and current_branch.lower() in PROTECTED_BRANCHES
            and (not after_push or (len(after_push) == 1 and after_push[0] == "origin"))
        ):
            action = "Force push" if has_force_flag else "Push"
            return True, (
                f"{action} while on protected branch '{current_branch}'. "
                f"Create a feature branch first"
            )

        # Force push without explicit branch from a feature branch — block as safety
        if has_force_flag and (
            not after_push or (len(after_push) == 1 and after_push[0] == "origin")
        ):
            return True, "Force push without explicit branch (could affect protected branch)"

    return False, ""


def check_delete_protected_branch(tokens: list[str]) -> tuple[bool, str]:
    """
    Check if command deletes a protected branch (local or remote).

    Catches:
    - git push origin --delete main
    - git push origin :main
    - git branch -D main
    - git branch -d main

    Scans all positions to handle chained commands (e.g., git log; git push origin --delete main).
    """
    tokens_lower = [t.lower() for t in tokens]

    # Scan for all git token positions
    for git_idx in range(len(tokens_lower)):
        if tokens_lower[git_idx] != "git":
            continue

        subcommand_idx = _git_subcommand_index(tokens, git_idx)
        if subcommand_idx is None:
            continue

        subcommand = tokens_lower[subcommand_idx]

        # Determine the end of this git command (next command root or end)
        cmd_end = len(tokens)
        for j in range(subcommand_idx + 1, len(tokens_lower)):
            if tokens_lower[j] in ("git", "doit", "gh", "uv"):
                cmd_end = j
                break
        cmd_tokens = tokens[git_idx:cmd_end]
        cmd_tokens_lower = tokens_lower[git_idx:cmd_end]

        # Check for remote branch deletion: git push origin --delete main
        if subcommand == "push" and "--delete" in cmd_tokens_lower:
            for token in cmd_tokens:
                if token.lower() in PROTECTED_BRANCHES:
                    return True, f"Deleting protected remote branch '{token}'"

        # Check for remote branch deletion with colon syntax: git push origin :main
        if subcommand == "push":
            for token in cmd_tokens:
                if token.startswith(":") and token[1:].lower() in PROTECTED_BRANCHES:
                    return True, f"Deleting protected remote branch '{token[1:]}'"

        # Check for local branch deletion: git branch -D main or git branch -d main
        if subcommand == "branch" and ("-d" in cmd_tokens_lower or "-D" in cmd_tokens):
            for token in cmd_tokens:
                if token.lower() in PROTECTED_BRANCHES:
                    return True, f"Deleting protected local branch '{token}'"

    return False, ""


def get_current_branch() -> str | None:
    """
    Get the current git branch name.

    Returns None if not in a git repository or in detached HEAD state.
    """
    try:
        result = subprocess.run(  # nosec B603 B607 - trusted git command
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def check_blocked_workflow_commands(tokens: list[str]) -> tuple[bool, str]:
    """
    Check if command uses blocked workflow commands.

    These commands should use doit wrappers instead of direct gh commands.
    Scans all positions to catch commands chained with && or ;.
    """
    tokens_lower = [t.lower() for t in tokens]

    for cmd_tuple, reason in BLOCKED_WORKFLOW_COMMANDS.items():
        cmd_len = len(cmd_tuple)
        for i in range(len(tokens_lower) - cmd_len + 1):
            if tuple(tokens_lower[i : i + cmd_len]) == cmd_tuple:
                return True, reason
    return False, ""


def check_governance_labels(tokens: list[str]) -> tuple[bool, str]:
    """
    Check if command attempts to add a governance label.

    Governance labels (like 'ready-to-merge') require human approval and
    should never be added by AI agents unless ALLOW_AI_READY_TO_MERGE is set.
    """
    tokens_lower = [t.lower() for t in tokens]

    # Check for: gh pr edit --add-label <governance-label>
    # or: gh issue edit --add-label <governance-label>
    if "gh" not in tokens_lower:
        return False, ""

    if "edit" not in tokens_lower:
        return False, ""

    if "--add-label" not in tokens_lower:
        return False, ""

    # Check if any governance label is being added
    for label, reason in GOVERNANCE_LABELS.items():
        if label.lower() in tokens_lower:
            # Allow bypass when the human has explicitly set the env var
            if label == "ready-to-merge" and _env_truthy(ALLOW_AI_READY_TO_MERGE_VAR):
                return False, ""
            return True, reason

    return False, ""


# Shell write operators (as standalone tokens after shlex.split)
_WRITE_REDIRECTS = {">", ">>"}

# Shell commands that write to a file argument. `ln` points a protected name
# at another file, `install` and `rsync` copy over it (#1051).
_WRITE_COMMANDS = {"tee", "cp", "mv", "dd", "ln", "install", "rsync"}

# Characters a redirect operator is made of. :func:`_redirect_tokens` lexes
# them as punctuation so `>|`, `&>`, `1>>` and a redirect glued to a word
# (`echo x>~/.bashrc`) each yield a standalone operator token (#1051).
_REDIRECT_PUNCTUATION = "<>|&;()"

# Script interpreters that can write files via -c/-e/--command
_INTERPRETER_COMMANDS = {"python", "python3", "perl", "ruby", "node"}

# Subshell separators used to bound a single command segment
_COMMAND_SEPARATORS = {"&&", "||", ";", "|"}


def _is_broad_pathspec(path: str) -> bool:
    """Return True when git pathspec *path* could cover a repo-root file.

    ``.``, ``./``, ``src/..``, anything above the repo (``..``, ``../x``), an
    absolute path and anything starting with ``:`` (``:/``, ``:(top)``, ``:!x``
    pathspec magic) can reach the root. A subdirectory such as ``src/`` cannot
    hold a root-level file, so it is not broad (#1061).
    """
    if not path:
        return False
    if path.startswith((":", "/", "~")):
        return True
    norm = posixpath.normpath(path)
    return norm in {".", ".."} or norm.startswith("../")


def _envrc_example_modified() -> bool:
    """Return True when the example file differs from HEAD (#1061).

    Fails open (False) when git is missing, times out, is not in a repo or the
    file is untracked: the gated ``cp`` is a documented setup step and the hook
    is a guardrail (ADR-9019).
    """
    try:
        result = subprocess.run(  # nosec B603 B607 - trusted git command
            ["git", "diff", "--quiet", "HEAD", "--", _ENVRC_EXAMPLE],
            capture_output=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 1


def _long_opt_matches(tok: str, full: str) -> bool:
    """Return True when *tok* names long option *full*, abbreviated or not.

    GNU getopt and git's parse-options both accept any unambiguous prefix
    (``--in-pl`` for ``--in-place``), with or without ``=value`` (#1061). An
    ambiguous prefix makes the tool error out, so matching it fails closed.
    """
    name = tok.split("=", 1)[0]
    return len(name) >= 3 and full.startswith(name)


def _is_leading_dot_glob(path: str) -> bool:
    """Return True when *path*'s basename starts with a literal ``.``.

    Bash ``*``, ``?`` and ``[`` never match a leading dot, so only a glob that
    spells the dot can reach a dotfile such as ``.envrc.local`` (#1061).
    ``src/*`` does not qualify, and neither does the everyday ``src/.*``;
    ``src/.envrc.loca?``, ``src/.[e]nvrc.local`` and ``src/.?nvrc.local`` do.
    """
    base = path.rstrip("/").rsplit("/", 1)[-1]
    return base.startswith(".") and base not in {".", "..", ".*"}


_EXTGLOB_INTRODUCERS = frozenset("@+!?*")


def _collapse_extglobs(tokens: list[str]) -> list[str]:
    """Fold each extglob back into one wildcard token (#1061).

    The lexer splits ``.envrc.@(local)`` into ``.envrc.@``, ``(``, ``local``,
    ``)``. Rewrite the introducer as ``*`` and drop the group, so every write
    pattern reads ``.envrc.*`` as one dynamic target. Fails closed: the whole
    group becomes a wildcard whatever it holds.
    """
    out: list[str] = []
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if i + 1 < n and tokens[i + 1] == "(" and tok[-1:] in _EXTGLOB_INTRODUCERS:
            depth = 0
            j = i + 1
            while j < n:
                if tokens[j] == "(":
                    depth += 1
                elif tokens[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            out.append(tok[:-1] + "*")
            i = j + 1
            continue
        out.append(tok)
        i += 1
    return out


def _git_restore_targets(tokens: list[str], git_idx: int) -> list[str]:
    """Return the protected paths a ``git checkout``/``git restore`` at
    *git_idx* would overwrite (#1055).

    ``git checkout <rev> -- <path>`` and ``git restore [--source=<rev>] <path>``
    replace the file with another version of it, so this carries content into
    ``.envrc.local.example`` ahead of the allowed ``cp`` onto ``.envrc.local``.
    ``git checkout <rev> <path>`` needs no ``--``, so without one every
    non-option argument is checked as a path; a branch is never named like a
    protected file, so ``git checkout main`` still passes.

    With an explicit source (another revision), a broad pathspec (``.``, ``:/``,
    ``--pathspec-from-file``) covers the example too and counts as a write to it
    (#1061). Without one the content comes from the index, so ``git checkout .``
    and ``git restore .`` stay allowed.
    """
    sub = _git_subcommand_index(tokens, git_idx)
    if sub is None or tokens[sub] not in {"checkout", "restore"}:
        return []
    rest: list[str] = []
    for t in tokens[sub + 1 :]:
        if t in _COMMAND_SEPARATORS:
            break
        rest.append(t)
    paths: list[str] = []
    has_source = False
    if tokens[sub] == "checkout":
        non_options = [t for t in rest if not t.startswith("-")]
        if "--" in rest:
            dashes = rest.index("--")
            paths = rest[dashes + 1 :]
            has_source = any(not t.startswith("-") for t in rest[:dashes])
        else:
            paths = non_options
            has_source = len(non_options) >= 2
    else:
        skip = False
        for t in rest:
            if skip:
                skip = False
            elif t == "-s" or (_long_opt_matches(t, "--source") and "=" not in t):
                skip = True
                has_source = True
            elif _long_opt_matches(t, "--source") or (
                t.startswith("-s") and not t.startswith("--")
            ):
                has_source = True
            elif not t.startswith("-"):
                paths.append(t)
    targets = [path for path in paths if _is_env_persistence_target(path, dynamic=True)]
    # `-C`/`--work-tree` move where git resolves paths, so any pathspec may
    # reach the root (`git -C .. checkout X -- repo/`)
    moved = any(t == "-C" or t.startswith("--work-tree") for t in tokens[git_idx + 1 : sub])
    if has_source and (
        moved
        or any(_is_broad_pathspec(path) for path in paths)
        or any(_long_opt_matches(t, "--pathspec-from-file") for t in rest)
    ):
        # Stand in the protected name the broad pathspec covers, so the
        # caller's match blocks it
        targets.append(_ENVRC_EXAMPLE)
    return targets


def _bash_confirmed_write_targets(tokens: list[str]) -> list[str]:
    """Return every persistence-protected path/basename targeted by a
    *confirmed* Bash write.

    Detected patterns:
    - A:  ``>`` / ``>>`` standalone token followed by a persistence target
    - B:  ``>foo`` / ``>>foo`` no-space form where ``foo`` is a persistence target
    - C:  ``tee`` / ``cp`` / ``mv`` / ``dd`` with a persistence target as a
          positional argument before the next command separator
    - D:  ``sed -i`` (in-place edit) with a persistence target as a positional

    Split from the script-interpreter heuristic (:func:`_bash_interpreter_mentions_target`,
    formerly pattern E of this function) so :func:`check_env_persistence_in_bash`
    can block one of these outright for ``ENV_PERSISTENCE_TARGETS`` while still
    requiring the literal var name for ``_AI_CLI_SETTINGS_TARGETS`` (#1037,
    decision b) -- the interpreter heuristic only *might* write and keeps the
    var-name requirement for every target, confirmed or not.
    """
    targets: list[str] = []
    tokens = _collapse_extglobs(tokens)
    n = len(tokens)
    for i, tok in enumerate(tokens):
        # Pattern A: standalone redirect operator, including `>|`, `&>` and
        # `>&` as :func:`_redirect_tokens` yields them
        if tok in _WRITE_REDIRECTS or (">" in tok and set(tok) <= set(_REDIRECT_PUNCTUATION)):
            if i + 1 < n and _is_env_persistence_target(tokens[i + 1], dynamic=True):
                targets.append(tokens[i + 1])
            continue

        # Pattern B: redirect operator concatenated with target (no whitespace)
        if tok.startswith(">>") and len(tok) > 2:
            if _is_env_persistence_target(tok[2:], dynamic=True):
                targets.append(tok[2:])
            continue
        if tok.startswith(">") and len(tok) > 1 and tok[1] not in {"=", ">"}:
            # Skip ">=" (comparison) and ">>" (already handled)
            if _is_env_persistence_target(tok[1:], dynamic=True):
                targets.append(tok[1:])
            continue

        # Pattern C: write command followed by persistence target as positional
        if tok in _WRITE_COMMANDS:
            positionals: list[str] = []
            seg_open = True
            for j in range(i + 1, n):
                t = tokens[j]
                if t in _COMMAND_SEPARATORS:
                    break
                if t.startswith("-"):
                    continue
                if tok == "dd":
                    # `dd` names its files as `if=`/`of=`; only the output is
                    # written, so strip `of=` and ignore `if=` (#1061)
                    if t.startswith("if="):
                        continue
                    t = t.removeprefix("of=")
                if _is_env_persistence_target(t):
                    targets.append(t)
                if seg_open and set(t) <= set(_REDIRECT_PUNCTUATION):
                    seg_open = False
                if seg_open:
                    positionals.append(t)
            # A glob in a copy's source is a target only when it spells the
            # leading dot of a protected name (`cp src/.envrc.loca? .`), not for
            # `cp src/* build/`: bash `*` never matches a dot (#1055, #1061).
            # `tee`'s files and the destination are always read as dynamic.
            dynamic_targets = positionals[-1:]
            dynamic_targets += [
                t for t in positionals[:-1] if tok == "tee" or _is_leading_dot_glob(t)
            ]
            targets.extend(
                t
                for t in dynamic_targets
                if t not in targets and _matches_dynamic_env_persistence_target(t)
            )
            continue

        # Pattern D: sed -i (in-place) with persistence target. Every operand
        # is matched literally, and every operand after the script is a file
        # matched as dynamic too, not just the last (#1061). The script (first
        # operand, unless -e/-f supplies it) skips only the dynamic match, as
        # `s/a/$/` would read as a wildcard.
        if tok == "sed":
            has_in_place = False
            has_script_flag = False
            skip_next = False
            operands: list[str] = []
            for j in range(i + 1, n):
                t = tokens[j]
                if t in _COMMAND_SEPARATORS:
                    break
                if skip_next:
                    skip_next = False
                elif _long_opt_matches(t, "--in-place"):
                    has_in_place = True
                elif _long_opt_matches(t, "--expression") or _long_opt_matches(t, "--file"):
                    has_script_flag = True
                    skip_next = "=" not in t
                elif t.startswith("-") and not t.startswith("--"):
                    # A short-option cluster: `-i` takes the rest as its
                    # suffix, `-e`/`-f` the rest (or the next token) as script
                    for k, ch in enumerate(t[1:], start=2):
                        if ch == "i":
                            has_in_place = True
                            break
                        if ch in {"e", "f"}:
                            has_script_flag = True
                            skip_next = k == len(t)
                            break
                elif not t.startswith("-"):
                    operands.append(t)
            if has_in_place:
                files = operands if has_script_flag else operands[1:]
                targets.extend(t for t in operands if _is_env_persistence_target(t))
                targets.extend(
                    t
                    for t in files
                    if t not in targets and _matches_dynamic_env_persistence_target(t)
                )
            continue

        # Pattern F: `git checkout ... -- <path>` and `git restore <path>`
        # overwrite <path> from the index or another commit (#1055)
        if tok == "git":
            targets.extend(_git_restore_targets(tokens, i))

    return targets


def _redirect_tokens(command: str) -> list[str]:
    """Tokenize *command* with shell operator characters as their own tokens.

    :func:`tokenize` splits on whitespace only, so a redirect glued to a word
    (`echo x>~/.bashrc`) or written as `>|` / `1>>` / `&>` never produced the
    standalone `>`/`>>` token pattern A looks for (#1051). Quoted strings stay
    one token, so `git commit -m "a >> .envrc"` is still not a redirect.
    """
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=_REDIRECT_PUNCTUATION)
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except ValueError:
        return tokenize(command)


def _bash_interpreter_mentions_target(tokens: list[str]) -> bool:
    """Pattern E: script interpreter (``python``/``python3``/``perl``/``ruby``/
    ``node``) invoked with ``-c`` / ``-e`` / ``--command`` whose script body
    mentions any persistence-target basename.

    A *might-write* heuristic, not a confirmed write -- ``python -c
    "print('.bashrc')"`` only prints the basename -- so it keeps the literal
    var-name requirement for every target, including ``ENV_PERSISTENCE_TARGETS``
    (#1037, decision b), unlike the confirmed-write patterns in
    :func:`_bash_confirmed_write_targets`.
    """
    n = len(tokens)
    for i, tok in enumerate(tokens):
        if tok not in _INTERPRETER_COMMANDS:
            continue
        cmd_end = n
        for j in range(i + 1, n):
            if tokens[j] in _COMMAND_SEPARATORS:
                cmd_end = j
                break
        segment = tokens[i + 1 : cmd_end]
        has_inline = any(
            t in {"-c", "-e", "--command"} or t.startswith(("-c=", "-e=", "--command="))
            for t in segment
        )
        if not has_inline:
            continue
        persistence_basenames = set(ENV_PERSISTENCE_TARGETS) | set(_AI_CLI_SETTINGS_TARGETS)
        for t in segment:
            for basename in persistence_basenames:
                if basename in t:
                    return True
    return False


def check_env_persistence_in_bash(tokens: list[str], _depth: int = 0) -> tuple[bool, str]:
    """Block Bash commands that would persist ALLOW_AI_READY_TO_MERGE, or
    that write to a protected file at all.

    Two write classes, split by how confident the match is (#1037, decision b):

    - A *confirmed* write (:func:`_bash_confirmed_write_targets`: redirect,
      ``tee``/``cp``/``mv``/``dd``, ``sed -i``) to an ``ENV_PERSISTENCE_TARGETS``
      file -- a shell rc file, an env file, or ``copilot-hooks.json`` -- is
      blocked whatever its content. A runtime-assembled variable name
      (``v=ALLOW_AI_; echo "export ${v}READY_TO_MERGE=1" >> ~/.bashrc``) is
      blocked this way without the literal string ever needing to appear.
      The only exceptions are the whole commands in
      ``_ALLOWED_ENV_PERSISTENCE_WRITES``, the documented ``.envrc.local``
      setup steps, and only when *_depth* is 0: a wrapped payload is never
      the whole command (#1051).
    - A confirmed write to an ``_AI_CLI_SETTINGS_TARGETS`` file, and the
      script-interpreter *might-write* heuristic
      (:func:`_bash_interpreter_mentions_target`) against any target, still
      require the literal ``ALLOW_AI_READY_TO_MERGE`` string -- the behaviour
      before this issue, kept so ``cp .codex/config.toml ~/.codex/config.toml``
      (a documented, legitimate setup step) is not broken.

    Plain mention of the var name with no write at all (e.g., in a commit
    message, a doc string, or ``git add`` arguments that reference protected
    file paths) is allowed either way.
    """
    var_name = ALLOW_AI_READY_TO_MERGE_VAR
    var_present = any(var_name in t for t in tokens)
    message = (
        f"Blocked: writes to shell or project config files that could persist "
        f"{var_name} are not allowed. Only a human can edit these files."
    )

    for target in _bash_confirmed_write_targets(tokens):
        if _matches_env_persistence_target(target, dynamic=True):
            if _depth == 0 and tuple(tokens) in _ALLOWED_ENV_PERSISTENCE_WRITES:
                if tuple(tokens) == _ALLOWED_ENVRC_COPY and _envrc_example_modified():
                    return True, (
                        f"Blocked: {_ENVRC_EXAMPLE} differs from HEAD, so copying it could "
                        f"persist content that was swapped in. Restore or commit the "
                        f"example, or ask a human to run the copy."
                    )
                continue
            return True, message
        if var_present:
            return True, message

    if var_present and _bash_interpreter_mentions_target(tokens):
        return True, message

    return False, ""


# Codex's file-edit tool is ``apply_patch``. Unlike every other agent's
# file-edit tool it carries a *command* rather than ``file_path``/``content``:
#
#     {"tool_name": "apply_patch",
#      "tool_input": {"command": "apply_patch <<PATCH\n*** Begin Patch\n
#                                 *** Update File: ~/.bashrc\n
#                                 +export ALLOW_AI_READY_TO_MERGE=1\n
#                                 *** End Patch\nPATCH"}}
#
# so neither the Bash path nor the file-edit path handled it and the operation
# fell through to "allow" -- letting Codex persist the governance bypass that
# the same edit through Claude's Write tool is blocked from doing (#681).
_APPLY_PATCH_TARGET_RE = re.compile(
    r"^\*\*\* (?:Add|Update|Delete) File: (.+)$",
    re.MULTILINE,
)

# A ``*** Move to:`` line renames the file a `*** Update File:` section is
# editing. Only the original path was ever checked (#1007, gap 1): a patch
# that moves ``x`` to a protected path while adding the env var persisted it
# under the new name without ever being compared against
# ``ENV_PERSISTENCE_TARGETS``.
_APPLY_PATCH_MOVE_RE = re.compile(r"^\*\*\* Move to: (.+)$", re.MULTILINE)


def _apply_patch_edits(command: str) -> list[tuple[str, str]]:
    """Return ``(target_path, added_content)`` for each file in a patch.

    Added content is every ``+``-prefixed line under that target, joined -- the
    lines the patch would introduce. Context and removed lines are ignored
    because only new content can persist a value.

    A section with a ``*** Move to:`` line yields a second entry for the move
    destination, carrying the same added content -- the original path is still
    checked too, since the file exists at both paths from the patch's own
    perspective (before vs. after).
    """
    edits: list[tuple[str, str]] = []
    matches = list(_APPLY_PATCH_TARGET_RE.finditer(command))
    for index, match in enumerate(matches):
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(command)
        section = command[body_start:body_end]
        added = [
            line[1:]
            for line in section.splitlines()
            # ``+++`` is a diff header, not added content.
            if line.startswith("+") and not line.startswith("+++")
        ]
        added_content = "\n".join(added)
        edits.append((match.group(1).strip(), added_content))

        move_match = _APPLY_PATCH_MOVE_RE.search(section)
        if move_match:
            edits.append((move_match.group(1).strip(), added_content))
    return edits


def check_env_persistence_in_apply_patch(command: str) -> tuple[bool, str]:
    """Block a Codex ``apply_patch`` that persists the bypass env var.

    Reuses :func:`check_env_persistence_in_file_edit` by normalising each patch
    target into the ``file_path``/``content`` shape that check expects, so the
    protected-target list stays in one place.
    """
    for target, added in _apply_patch_edits(command):
        is_dangerous, reason = check_env_persistence_in_file_edit(
            "apply_patch", {"file_path": target, "content": added}
        )
        if is_dangerous:
            return True, reason
    return False, ""


# Path-shaped keys checked, in order, to resolve a file-edit tool's target.
# ``file_path`` is every CLI's own normalized key (Claude/Codex/Gemini, and
# Antigravity's PascalCase args normalized in ``_parse_input``); ``path`` and
# ``filename`` cover a tool this hook does not recognise by name -- Copilot's
# `create`/`edit` use ``path``, and the shape-based fallback in ``main()``
# routes any other unrecognised write-shaped tool here too (#1037).
_PATH_KEYS = ("file_path", "path", "filename")

# Content-shaped keys checked, in addition to each known tool's own key(s)
# below, so a key no CLI in the per-tool branches uses yet (``new_text``,
# ``file_text``) -- or an unrecognised tool that reuses a common name instead
# of inventing its own -- is still covered (#1037, decision a).
_GENERIC_CONTENT_KEYS = ("content", "new_string", "new_text", "file_text")


def _resolve_file_path(tool_input: dict[str, object]) -> str:
    """Return the first non-empty path-shaped value in *tool_input*."""
    for key in _PATH_KEYS:
        value = tool_input.get(key)
        if value:
            return str(value)
    return ""


def _looks_like_file_edit(tool_input: dict[str, object]) -> bool:
    """Whether *tool_input* has the shape of a file write: a path key plus a
    content key.

    Used by ``main()`` to fail closed on an unrecognised tool name (#1037)
    rather than letting it fall through to allow. A read-only tool (Read,
    Grep, Glob, a ``view`` tool) carries a path but no content key, so it
    does not match.
    """
    has_path = any(tool_input.get(key) for key in _PATH_KEYS)
    has_content = any(key in tool_input for key in _GENERIC_CONTENT_KEYS) or isinstance(
        tool_input.get("edits"), list
    )
    return has_path and has_content


def _all_string_values(value: object) -> list[str]:
    """Return every string found anywhere inside *value*, however it nests.

    Used for Copilot's ``create``/``edit`` tools: the SDK docs that confirm
    those tool names do not confirm a content key (#1037), so rather than
    guess one, every string value in the tool_input is scanned for the
    bypass var name.
    """
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        strings: list[str] = []
        for item in value.values():
            strings.extend(_all_string_values(item))
        return strings
    if isinstance(value, list):
        strings = []
        for item in value:
            strings.extend(_all_string_values(item))
        return strings
    return []


def _generic_content_strings(tool_input: dict[str, object]) -> list[str]:
    """Return the string content under :data:`_GENERIC_CONTENT_KEYS` plus
    ``edits``, unioned with whatever a tool's own key(s) already matched.

    ``edits`` only contributes each item's own added-content key(s)
    (``new_string``/``new_text``), not ``old_string`` -- scanning the text an
    edit *removes* would block the one operation that's actually safe, taking
    the var name back out of a file (#1037, decision a).
    """
    parts: list[str] = []
    for key in _GENERIC_CONTENT_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str):
            parts.append(value)
    edits = tool_input.get("edits")
    if isinstance(edits, list):
        for edit_item in edits:
            if not isinstance(edit_item, dict):
                continue
            for added_key in ("new_string", "new_text"):
                value = edit_item.get(added_key)
                if isinstance(value, str):
                    parts.append(value)
    return parts


def check_env_persistence_in_file_edit(
    tool_name: str, tool_input: dict[str, object], *, scan_all_values: bool = False
) -> tuple[bool, str]:
    """Block file-edit operations (Edit/Write/MultiEdit for Claude/Codex,
    write_file/replace for Gemini, write_to_file/write_file/edit_file for
    Antigravity, create/edit for Copilot) that would
    persist ALLOW_AI_READY_TO_MERGE to a protected file.

    Triggers when the target path (:func:`_resolve_file_path`) is:
    - an ``ENV_PERSISTENCE_TARGETS`` file, whatever the content (#1051), or
    - an ``_AI_CLI_SETTINGS_TARGETS`` file and the new content contains
      ALLOW_AI_READY_TO_MERGE.

    *scan_all_values*: when True, every string value anywhere in *tool_input*
    is scanned instead of relying on a known key name -- set by ``main()``
    for Copilot's ``create``/``edit`` tools, whose content key is not
    confirmed (#1037).
    """
    var_name = ALLOW_AI_READY_TO_MERGE_VAR

    file_path_raw = _resolve_file_path(tool_input)
    if not file_path_raw:
        return False, ""

    if not _is_env_persistence_target(file_path_raw):
        return False, ""

    # A shell rc or env file is run by bash or direnv when loaded, so content
    # that assembles the name (`v=ALLOW_AI_; export ${v}READY_TO_MERGE=1`)
    # persists it without the literal string. Block any edit, as the Bash
    # path does; only AI CLI settings files stay content-gated (#1051).
    if _matches_env_persistence_target(file_path_raw):
        return True, (
            f"Blocked: AI must not edit '{file_path_raw}', a file that could persist "
            f"{var_name}. Only a human can edit this file."
        )

    if scan_all_values:
        new_content_parts = _all_string_values(tool_input)
    else:
        # Collect all new content being written
        new_content_parts = []

        tool_lower = tool_name.lower()

        if tool_lower in ("write", "write_file", "write_to_file", "apply_patch"):
            # Write/write_file (Claude/Gemini/agy) and write_to_file (agy), with
            # agy's args normalized in _parse_input: full file content lives in the
            # 'content' key.
            # apply_patch (Codex) is normalised into the same shape by
            # check_env_persistence_in_apply_patch, one entry per patch target.
            content = str(tool_input.get("content", "") or "")
            new_content_parts.append(content)

        elif tool_lower in ("edit", "replace", "edit_file"):
            # Edit (Claude/Codex), replace (Gemini) and edit_file (agy, its
            # Replacement normalized in _parse_input): new_string key
            new_content_parts.append(str(tool_input.get("new_string", "") or ""))

        elif tool_lower == "multiedit":
            # MultiEdit: edits is a list of {old_string, new_string} dicts
            edits = tool_input.get("edits", [])
            if isinstance(edits, list):
                for edit_item in edits:
                    if isinstance(edit_item, dict):
                        new_content_parts.append(str(edit_item.get("new_string", "") or ""))

        # Union with a generic key scan, so a key none of the branches above
        # uses (or an unrecognised tool routed here by the shape-based
        # fallback in main()) is still covered (#1037, decision a).
        new_content_parts += _generic_content_strings(tool_input)

    # Check if any new content contains the env var name
    combined = "\n".join(new_content_parts)
    if var_name in combined:
        return True, (
            f"Blocked: AI must not persist {var_name} to '{file_path_raw}'. "
            f"Only a human can set this variable in their environment."
        )

    return False, ""


# A shell operator shlex leaves glued to a word (``origin/main;echo``) still ends the command.
_GLUED_OPERATOR = re.compile(r"[;&|]")


def _command_args(tokens: list[str], start: int) -> list[str]:
    """Return the tokens from *start* to the end of that command.

    A command ends at a shell operator. A token with one glued to it keeps only
    the part before the operator, and ends the command too.
    """
    args: list[str] = []
    for token in tokens[start:]:
        if token in _SHELL_OPERATORS:
            break
        glued = _GLUED_OPERATOR.search(token)
        if glued:
            if glued.start():
                args.append(token[: glued.start()])
            break
        args.append(token)
    return args


# Punctuation characters the structural tokenizer splits into standalone
# tokens. Deliberately narrower than shlex's default punctuation set
# (``();<>|&``, used when ``punctuation_chars=True``): including ``(``/``)``
# would split a ``$(...)`` command substitution, separating its trailing ``)``
# from a word like ``--ff-only)`` and turning it into the literal flag --
# letting an *unevaluated* ``--ff-only`` inside the substitution count as a
# real one. ``>`` is also absent, so a redirect like ``2>&1`` or ``1>`` keeps
# its leading digit glued on instead of splitting into a bare ``>`` that no
# longer matches ``_REDIRECT_TOKEN_RE``. ``\n`` is here so an unquoted newline
# ends a command, as the shell reads it, while a quoted one stays inside its
# word (#1007, gap 5).
_MERGE_RULE_PUNCTUATION = "&|;\n"

# Characters after which a ``#`` starts a word, and so a comment.
_COMMENT_WORD_BOUNDARY = frozenset(" \t\n;&|()<>")


def _strip_shell_comments(command: str) -> str:
    """Return *command* without its comments and backslash-newline continuations.

    A ``#`` starts a comment only at the start of a word and outside quotes:
    ``x#y; git merge feature`` and ``echo '#'; git merge feature`` both still
    run the merge. shlex's own ``commenters`` cut at any unquoted ``#``, which
    hid the rest of the line (#1007). A comment runs to the end of its line;
    the newline itself is kept, since it ends the command.
    """
    out: list[str] = []
    quote = ""
    word_start = True  # the next character would start a word
    index = 0
    while index < len(command):
        char = command[index]
        if quote == "'":
            out.append(char)
            if char == "'":
                quote = ""
            index += 1
            continue
        if char == "\\" and index + 1 < len(command):
            if command[index + 1] != "\n":
                out.append(command[index : index + 2])
                word_start = False  # an escaped character is part of a word
            index += 2  # a continuation joins the next line, as the shell does
            continue
        if quote == '"':
            out.append(char)
            if char == '"':
                quote = ""
            index += 1
            continue
        if char in "'\"":
            quote = char
        elif char == "#" and word_start:
            while index < len(command) and command[index] != "\n":
                index += 1
            continue
        word_start = char in _COMMENT_WORD_BOUNDARY
        out.append(char)
        index += 1
    return "".join(out)


def _structural_tokens(command: str) -> list[str]:
    """Tokenize *command* with each unquoted newline or glued separator as its own token.

    Built on ``shlex.shlex`` directly rather than :func:`tokenize` (``shlex.
    split``), so ``&&``, ``;``, ``|``, ``&`` and an unquoted newline become
    their own tokens the way ``_SHELL_OPERATORS``/``_command_args`` expect.
    ``tokenize()`` treats a newline as ordinary whitespace and leaves a glued
    separator (``hi;``) stuck to its neighbour, so a command position after
    either was invisible to any check anchored on :func:`_command_start_indices`
    (#1011, gap 2) -- the merge rule (:func:`check_merge_to_protected`),
    :func:`check_env_dump` and :func:`check_credential_file_read` all need one.
    The whole command is lexed at once, so a quoted string spanning lines
    stays one word instead of breaking the line it starts on.

    Written for the merge rule (then named ``_merge_rule_tokens``); renamed
    when the other two checks started reusing it (#1011). Its behaviour is
    unchanged by the rename.
    """
    stripped = _strip_shell_comments(command)
    try:
        lexer = shlex.shlex(stripped, posix=True, punctuation_chars=_MERGE_RULE_PUNCTUATION)
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        # Malformed quoting. Split on whitespace and operators instead, so a
        # glued ``&&git merge`` still yields its own ``git`` token.
        tokens = re.findall(r"[;&|\n]+|[^\s;&|]+", stripped)
    # A run of operators that includes a newline is a separator, whatever else
    # it holds: ``&&\n`` and ``;\n`` both end the command.
    return [
        ";" if "\n" in token and not token.strip(_MERGE_RULE_PUNCTUATION) else token
        for token in tokens
    ]


def check_merge_to_protected(command: str) -> tuple[bool, str]:
    """
    Check if command is a merge that would create a merge commit on a protected branch.

    Protected branches often require linear history (no merge commits).
    Blocks `git merge` on protected branches unless that merge passes --ff-only.

    Each ``git`` token's own subcommand decides whether it is a merge, and
    ``--ff-only`` counts only up to the end of that command. Matching the words
    anywhere on the line refused read-only commands such as
    ``git log --grep merge`` and let ``git merge x; echo --ff-only`` through (#894).

    Takes *command* with its heredoc bodies already removed (``check_command``
    passes the result of :func:`_without_heredoc_bodies`) rather than the
    shared ``tokenize()`` tokens: ``tokenize()`` treats a newline as whitespace
    and reads a ``#`` comment as arguments, either of which would let a
    ``--ff-only`` on the next line, or in a trailing comment, count for the
    ``git merge`` before it (#1007, gap 5). An unstripped heredoc body is worse
    -- an unbalanced quote inside it can swallow every command after its
    terminator, hiding a real ``git merge`` from this scan entirely (#1011,
    gap 3).
    """
    tokens = _structural_tokens(command)
    tokens_lower = [t.lower() for t in tokens]

    for git_idx in range(len(tokens_lower)):
        if tokens_lower[git_idx] != "git":
            continue
        subcommand_idx = _git_subcommand_index(tokens, git_idx)
        if subcommand_idx is None or tokens_lower[subcommand_idx] != "merge":
            continue
        # Allow a fast-forward-only merge (no merge commit)
        if "--ff-only" in _command_args(tokens_lower, subcommand_idx + 1):
            continue

        # Check if we're on a protected branch
        current_branch = get_current_branch()
        if current_branch and current_branch.lower() in PROTECTED_BRANCHES:
            return True, (
                f"Merge on protected branch '{current_branch}' would create merge commit. "
                f"Use --ff-only for fast-forward merge, or merge via PR"
            )
        return False, ""

    return False, ""


def _command_start_indices(tokens: list[str]) -> list[int]:
    """Return the indices at which a command begins.

    A command starts at position 0 and after any shell separator. Anchoring on
    these is what separates *running* a command from merely *mentioning* it:
    a heredoc body tokenizes exactly like an argument list, so a scan over all
    positions treats documentation and test fixtures as invocations. Both
    checks below hit that while this repository's own tests were being written.
    """
    starts = [0]
    for index, token in enumerate(tokens):
        if token in _SHELL_OPERATORS and index + 1 < len(tokens):
            starts.append(index + 1)
    return starts


def _is_secret_name(name: str) -> bool:
    """Return True when *name* matches one of SECRET_ENV_PATTERNS."""
    return any(fnmatch.fnmatchcase(name.upper(), pattern) for pattern in SECRET_ENV_PATTERNS)


def check_env_dump(tokens: list[str]) -> tuple[bool, str]:
    """Block commands that print the environment, or a secret-named variable.

    Distinguishes a *dump* from an *invocation*: ``env`` with no trailing
    command prints everything, while ``env -u FOO cmd`` and ``env VAR=1 cmd``
    merely run ``cmd`` with a modified environment and are left alone.

    Anchored on :func:`_command_start_indices`, so *tokens* must come from
    :func:`_structural_tokens` rather than the shared ``tokenize()``:
    ``tokenize()`` treats an unquoted newline as whitespace and leaves a glued
    separator (``hi;printenv``) stuck to its neighbour, so neither ever placed
    a command at the start of a line or after a glued ``;`` (#1011, gap 2).
    """
    for index in _command_start_indices(tokens):
        if index >= len(tokens) or tokens[index] not in _ENV_DUMP_COMMANDS:
            continue
        token = tokens[index]
        # Stop at the next separator: later tokens belong to another command.
        rest = []
        for candidate in tokens[index + 1 :]:
            if candidate in _SHELL_OPERATORS:
                break
            rest.append(candidate)

        # nosec B105 - bandit's hardcoded-password heuristic fires on this
        # string comparison; the literal is a shell command name.
        if token == "printenv":  # nosec B105
            # `printenv` alone dumps everything; `printenv NAME` prints one.
            if not rest:
                return True, "Prints the entire environment, which may contain secrets"
            if any(_is_secret_name(arg) for arg in rest if not arg.startswith("-")):
                return True, "Prints a secret-named environment variable"
            continue

        # `env`: walk past its own options and assignments looking for a command.
        position = 0
        while position < len(rest):
            argument = rest[position]
            if argument in _ENV_OPTS_WITH_VALUE:
                position += 2
                continue
            if argument.startswith("-") or "=" in argument:
                position += 1
                continue
            break  # a command follows, so this is an invocation
        else:
            return True, "Prints the entire environment, which may contain secrets"

        if position >= len(rest):
            return True, "Prints the entire environment, which may contain secrets"

    return False, ""


def _is_credential_store(token: str) -> bool:
    """Return True when *token* names a known credential store."""
    if not token or token.startswith("-"):
        return False
    try:
        path = Path(token).expanduser()
    except (ValueError, RuntimeError):
        return False
    required_parents = CREDENTIAL_FILE_BASENAMES.get(path.name)
    if required_parents is None:
        return False
    parent = path.parent.as_posix()
    return not required_parents or any(required in parent for required in required_parents)


# A redirection does not end the command the way `&&`/`;`/`|` does -- it
# merely flips where output goes, and a reader's other arguments still follow
# it. `_SHELL_OPERATORS` includes these for callers that *should* stop there;
# this check instead skips the operator and its target (#1007, gap 4).
_REDIRECT_TOKEN_RE = re.compile(r"^[12]?(?:>>|>|&>)")


def check_credential_file_read(tokens: list[str]) -> tuple[bool, str]:
    """Block a reader command pointed at a known credential store.

    Anchored on the reading command rather than scanning every token. A bare
    scan flagged any command whose text merely *contained* a credential path --
    writing this project's own test data tripped it immediately -- because
    heredoc bodies and file contents tokenize like arguments. Requiring a
    reader in command position keeps `cat ~/.netrc` blocked while leaving
    prose, test fixtures and documentation alone.

    A redirection (`>`, `>>`, `1>`, `2>`, `&>`) skips itself and, when it is a
    standalone token, its separate target too -- it flips the reader into a
    writer for that one argument, but `cat /dev/null > /tmp/x ~/.pypirc` still
    reads `~/.pypirc` as a second, un-redirected argument. A glued form such as
    `>/tmp/x` carries its target in the same token, so only the token itself is
    skipped.

    Anchored on :func:`_command_start_indices`, so *tokens* must come from
    :func:`_structural_tokens` rather than the shared ``tokenize()``:
    ``tokenize()`` treats an unquoted newline as whitespace and leaves a glued
    separator (``hi;cat``) stuck to its neighbour, so neither ever placed a
    command at the start of a line or after a glued ``;`` (#1011, gap 2).
    """
    for index in _command_start_indices(tokens):
        if index >= len(tokens) or tokens[index] not in _CREDENTIAL_READER_COMMANDS:
            continue
        skip_next = False
        for argument in tokens[index + 1 :]:
            if skip_next:
                skip_next = False
                continue
            redirect_match = _REDIRECT_TOKEN_RE.match(argument)
            if redirect_match:
                if redirect_match.end() == len(argument):
                    skip_next = True  # standalone operator; its target follows
                continue  # glued form (">/tmp/x"): only the token itself
            # Stop at a true separator: later tokens belong to another
            # command, which gets its own turn through this loop.
            if argument in _SHELL_OPERATORS:
                break
            if _is_credential_store(argument):
                return True, (f"Reads the credential store '{argument}', which holds live secrets")
    return False, ""


def check_command(command: str, _depth: int = 0) -> tuple[bool, str]:
    """
    Check if command contains dangerous patterns.

    Uses shlex to tokenize, then checks for:
    1. Dangerous flags as standalone tokens
    2. Dangerous token sequences
    3. Push to protected branches (regular or force)
    4. Deletion of protected branches
    5. Merge commits on protected branches
    6. Blocked workflow commands
    7. Governance labels
    8. Shell-wrapper payloads (``bash -c``, ``sh -c``, ``eval``) and heredoc
       bodies fed to a shell's stdin (``bash <<EOF``) — recursed up to depth 3
       so all seven checks above gain wrapper coverage. A heredoc consumed as
       *data* (``cat >> file <<EOF``, ``git commit -F - <<EOF``) or run by a
       non-shell interpreter (``python3 - <<EOF``) is not recursed.

    Returns:
        (is_dangerous, reason)
    """
    tokens = tokenize(command)

    # Check for dangerous standalone flags
    is_dangerous, reason = check_dangerous_flags(tokens)
    if is_dangerous:
        return True, reason

    # Check for dangerous sequences
    is_dangerous, reason = check_dangerous_sequences(tokens)
    if is_dangerous:
        return True, reason

    # *command* with every heredoc body and terminator line removed. Shared by
    # the three checks below that need a command position across an unquoted
    # newline or a glued separator, or that would otherwise lex a heredoc
    # body's own quoting as part of the surrounding command (#1011).
    stripped = _without_heredoc_bodies(command)

    # Check for environment dumps and credential-store reads. Each check runs on
    # the structural tokens, which find a command after a newline or a glued
    # separator, and also on the `tokenize()` input it had before #1011. That
    # second pass keeps every block the first one would lose to the new
    # tokenizer, such as `cat &>/tmp/x ~/.netrc`, where `&>` splits into a
    # separator `&` and `>/tmp/x`.
    structural = _structural_tokens(stripped)
    for check, legacy in (
        (check_env_dump, tokens),
        (check_credential_file_read, tokenize(stripped)),
    ):
        for check_tokens in (structural, legacy):
            is_dangerous, reason = check(check_tokens)
            if is_dangerous:
                return True, reason

    # Checks that find a `git` or `gh` command by scanning token positions. Each
    # runs on the `tokenize()` tokens and on the structural tokens of the full
    # command: `shlex.split` keeps a glued `true;git` as one word, so the scan
    # missed any command glued to `;`, `&&`, `||`, `|` or `&` (#1023). The
    # first pass keeps every block these checks had before.
    command_structural = _structural_tokens(command)
    for check in (
        check_push_to_protected,
        check_delete_protected_branch,
        check_blocked_workflow_commands,
        check_governance_labels,
    ):
        for check_tokens in (tokens, command_structural):
            is_dangerous, reason = check(check_tokens)
            if is_dangerous:
                return True, reason

    # Check for merge commits on protected branches. The stripped command keeps
    # a heredoc body's stray quote from hiding a later `git merge` (#1011, gap
    # 3); the full command still sees a merge inside a body whose receiver the
    # hook does not recognise as running it, such as `env -i bash <<EOF`.
    # Skipping bodies by receiver alone would be a bypass (ADR-9019, rule 3).
    for source in (stripped, command):
        is_dangerous, reason = check_merge_to_protected(source)
        if is_dangerous:
            return True, reason

    # Check for attempts to persist ALLOW_AI_READY_TO_MERGE via Bash
    # Checked on the `tokenize()` tokens and again on tokens that split out
    # redirect operators, which find `>|`, `1>>`, `&>` and glued redirects
    # (#1051). Heredoc bodies are stripped so a body's text is not a redirect.
    for check_tokens in (tokens, _redirect_tokens(stripped)):
        is_dangerous, reason = check_env_persistence_in_bash(check_tokens, _depth)
        if is_dangerous:
            return True, reason

    # Recurse into shell-wrapper payloads (bash/sh/zsh/dash -c <payload>, eval ...)
    # Depth cap of 3 prevents infinite loops on adversarial inputs.
    if _depth < 3:
        for payload in _wrapped_payloads(tokens) + _heredoc_payloads(command):
            is_dangerous, reason = check_command(payload, _depth + 1)
            if is_dangerous:
                return True, reason

    return False, ""


# Key ``_parse_input`` stores a bare patch-string payload under. Prefixed so it
# cannot collide with a real tool argument name (#1042). ``_parse_input`` also
# strips it from every dict payload, so a tool call cannot set it itself to
# steer ``main()`` past the checks its real tool name would get.
_RAW_PATCH_KEY = "_raw_patch"


def _raw_patch_input(raw: object) -> dict:
    """Wrap a bare patch-text payload so its targets can be checked.

    Returns ``{_RAW_PATCH_KEY: raw}`` when *raw* is a string naming at least one
    ``*** Add/Update/Delete File:`` target, else an empty dict -- the previous
    fallback for any payload that is not a dict.
    """
    if isinstance(raw, str) and _APPLY_PATCH_TARGET_RE.search(raw):
        return {_RAW_PATCH_KEY: raw}
    return {}


def _parse_input(input_data: dict) -> tuple[str, str, dict]:
    """
    Parse tool name, command, and tool_input from hook input.

    Handles three input formats:
    - Claude/Gemini: {"tool_name": "Bash", "tool_input": {"command": "..."}}
    - Copilot CLI:   {"toolName": "bash", "toolArgs": "{\"command\":\"...\"}"}
                     File edits use "create"/"edit" with a "path" key (vendor
                     SDK docs, not a live probe -- #1037); its content key is
                     not confirmed, so this is left unmapped here and
                     ``main()``/``check_env_persistence_in_file_edit`` scan
                     every string value instead of a guessed key name.
    - Antigravity:   {"toolCall": {"name": "run_command",
                      "args": {"CommandLine": "..."}}}

    Copilot's file-edit tool is ``apply_patch``, and its ``toolArgs`` is the
    bare patch text, not JSON. Copilot also runs the Claude-format hooks in
    ``.claude/settings.json`` with ``tool_name: "Edit"`` and that same patch
    text as ``tool_input``. Both were observed from a live ``-p`` session
    (#1042). A patch-shaped string is returned as ``{_RAW_PATCH_KEY: text}``
    so ``main()`` checks its targets instead of seeing an empty dict.

    Returns:
        (tool_name, command, tool_input) tuple where tool_input is the full
        parameter dict (used for file-edit operations). For Antigravity the
        PascalCase args are normalized to the canonical command/file_path/content
        keys the downstream checks expect. ``_resolve_file_path`` reads
        Copilot's "path" key directly, so it needs no normalizing here.
    """
    # Antigravity CLI (agy) format: a nested toolCall with PascalCase args
    # (protojson camelCase envelope). run_command -> args.CommandLine;
    # write_to_file -> args.TargetFile / args.CodeContent. agy 1.4.3 writes with
    # write_file -> args.Path / args.Content and edits in place with
    # edit_file -> args.Path / args.Target / args.Replacement, both observed
    # from a live session (#1006).
    if "toolCall" in input_data:
        tool_call = input_data.get("toolCall") or {}
        tool_name = tool_call.get("name", "")
        args = tool_call.get("args") or {}
        if not isinstance(args, dict):
            args = {}
        tool_input = {
            **args,
            "command": args.get("CommandLine", "") or "",
            "file_path": args.get("TargetFile", "") or args.get("Path", "") or "",
            "content": args.get("CodeContent", "") or args.get("Content", "") or "",
            "new_string": args.get("Replacement", "") or "",
        }
        tool_input.pop(_RAW_PATCH_KEY, None)
        return tool_name, tool_input["command"], tool_input

    # Copilot CLI format uses camelCase keys
    if "toolName" in input_data:
        tool_name = input_data.get("toolName", "")
        tool_args_raw = input_data.get("toolArgs", "{}")
        try:
            # No ``: dict`` annotation here — the Antigravity branch above already
            # binds ``tool_input``, so annotating in this branch reads as a
            # redefinition to mypy. Annotating at function scope instead would
            # narrow the Claude/Gemini branch's ``isinstance`` guard to dead code.
            tool_input = (
                json.loads(tool_args_raw) if isinstance(tool_args_raw, str) else tool_args_raw
            )
            if isinstance(tool_input, dict):
                tool_input.pop(_RAW_PATCH_KEY, None)
        except json.JSONDecodeError:
            tool_input = _raw_patch_input(tool_args_raw)
        return tool_name, tool_input.get("command", ""), tool_input

    # Claude/Gemini format uses snake_case keys
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    if isinstance(tool_input, dict):
        tool_input.pop(_RAW_PATCH_KEY, None)
    else:
        tool_input = _raw_patch_input(tool_input)
    return tool_name, tool_input.get("command", ""), tool_input


def _hook_format(input_data: dict) -> str:
    """Identify which CLI's hook format the input uses.

    Returns one of:
    - "agy": Antigravity CLI (nested ``toolCall``)
    - "copilot": Copilot CLI (``toolName``/``toolArgs``)
    - "default": Claude/Gemini/Codex (``tool_name``/``tool_input``)
    """
    if "toolCall" in input_data:
        return "agy"
    if "toolName" in input_data:
        return "copilot"
    return "default"


LOG_FILE = Path(__file__).parent / "hook-debug.jsonl"


def _log(entry: dict) -> None:
    """Append a JSON log entry. Only active when HOOK_BLOCKCOMMAND_DEBUG=1 is set."""
    if not os.environ.get("HOOK_BLOCKCOMMAND_DEBUG"):
        return
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass  # Never fail due to logging


# Claude: Bash · Codex/Copilot: bash · Antigravity: run_command
#
# ``run_shell_command`` (and ``write_file``/``replace`` below) are Gemini CLI's
# tool names. This project no longer ships a Gemini integration, but the names
# are kept on purpose: a downstream project with enterprise Gemini access can
# still point that CLI at this hook, and matching an extra name costs nothing
# while failing to match one would silently remove protection.
#
# All tool-name sets below are lower-case; ``main()`` compares against
# ``tool_name.lower()`` so a CLI that capitalizes its tool name differently
# (or inconsistently) still matches (#1037, decision a).
_BASH_TOOL_NAMES = frozenset({"bash", "run_shell_command", "run_command"})

# File-edit tool names across all supported AI CLIs
# Claude/Codex: Edit, Write, MultiEdit
# Gemini: write_file, replace
# Antigravity (agy): write_to_file (older releases), write_file and edit_file (#1006)
# Copilot CLI: create, edit (vendor SDK docs, not a live probe -- #1037). Its
# content key is not confirmed, so ``main()`` additionally scans every string
# value for these two rather than trusting a guessed key name.
# Codex: apply_patch. Handled on its own path -- see the parser above -- because
# its payload is command-shaped rather than file_path/content.
# Copilot CLI 1.0.104 in -p mode also edits through apply_patch, with the bare
# patch text as its payload (live probe, #1042); _parse_input wraps that under
# _RAW_PATCH_KEY. create/edit stay listed in case another mode still uses them.
_APPLY_PATCH_TOOL_NAME = "apply_patch"

_FILE_EDIT_TOOL_NAMES = frozenset(
    {"edit", "write", "multiedit", "write_file", "replace", "write_to_file", "edit_file", "create"}
)

# Copilot tool names whose content key is not confirmed (#1037): main() scans
# every string value in tool_input for these rather than a guessed key name.
# Gated on the Copilot format too -- "edit" alone would otherwise also match
# Claude's lower-cased "Edit", whose content lives specifically in new_string
# and whose old_string must NOT be scanned (removing the var is safe).
_COPILOT_SCAN_ALL_VALUES_TOOLS = frozenset({"create", "edit"})


def _block_response(fmt: str, reason: str, command: str) -> int:
    """Emit a block response in the format the calling CLI expects.

    - Antigravity ("agy"): print ``{"decision": "deny"}`` to stdout, exit 0.
      Confirmed by probe to hard-block even under
      ``--dangerously-skip-permissions``.
    - Copilot ("copilot"): print ``{"permissionDecision": "deny"}`` to stdout,
      exit 0.
    - Claude/Gemini/Codex ("default"): exit code 2 + stderr message.
    """
    manual = f"Blocked: {reason}. If intentional, ask the user to run it manually."

    if fmt == "agy":
        # Antigravity: deny via stdout JSON {"decision": "deny"}; exit 0.
        print(json.dumps({"decision": "deny", "reason": manual}))
        return 0

    if fmt == "copilot":
        # Copilot CLI: deny via JSON output to stdout
        print(json.dumps({"permissionDecision": "deny", "permissionDecisionReason": manual}))
        return 0

    # Claude/Gemini/Codex: block via exit code 2 + stderr message
    print(
        f"BLOCKED: Operation contains dangerous pattern.\n"
        f"Reason: {reason}\n"
        f"Operation: {command}\n"
        f"\n"
        f"If this is intentional, ask the user to run it manually.",
        file=sys.stderr,
    )
    return 2  # Exit 2 = Block and show stderr to Claude/Gemini/Codex


def _fail_closed(reason: str) -> int:
    """Deny using every supported CLI's contract at once.

    Used when the hook cannot tell which CLI called it (unparsable stdin) or
    when it hits an unexpected internal error. A hook that cannot evaluate a
    command must not let it through, and at that point the calling CLI is
    unknown -- so emit all three contracts together:

    - stdout JSON carrying both ``decision`` (Antigravity) and
      ``permissionDecision`` (Copilot) keys
    - exit code 2 + stderr (Claude/Gemini/Codex)

    Verified against the real CLIs: ``agy`` and ``copilot`` both honour the
    combined payload and both tolerate the extra key and the non-zero exit.
    """
    manual = f"Blocked: {reason}. If intentional, ask the user to run it manually."

    print(
        json.dumps(
            {
                "decision": "deny",
                "reason": manual,
                "permissionDecision": "deny",
                "permissionDecisionReason": manual,
            }
        )
    )
    print(f"BLOCKED: {manual}", file=sys.stderr)
    return 2


def main() -> int:
    """Main entry point."""
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        # Deny rather than return 1: no agent treats 1 as a block, so returning
        # it here would let the operation through on unparsable input.
        return _fail_closed(f"hook could not parse its input ({e})")

    tool_name, command, tool_input = _parse_input(input_data)
    fmt = _hook_format(input_data)
    # Case-insensitive throughout (#1037, decision a): a CLI's own
    # capitalization of a tool name is not part of its contract.
    tool_lower = tool_name.lower()

    _log(
        {
            "raw_input": input_data,
            "tool_name": tool_name,
            "command": command,
            "format": fmt,
        }
    )

    # --- Bash / shell command path ---
    if tool_lower in _BASH_TOOL_NAMES:
        if not command:
            return 0
        is_dangerous, reason = check_command(command)
        if is_dangerous:
            return _block_response(fmt, redirect_reason(command, reason), command)
        return 0

    # --- Bare patch-text path (Copilot apply_patch, either hook format) ---
    #
    # Only the env-persistence check runs: the payload is file content, not a
    # shell command, so scanning it with check_command would block a patch that
    # merely mentions a dangerous command in a doc (#1042). A clean patch falls
    # through rather than returning, so the checks below still see the call.
    raw_patch = tool_input.get(_RAW_PATCH_KEY)
    if isinstance(raw_patch, str):
        is_dangerous, reason = check_env_persistence_in_apply_patch(raw_patch)
        if is_dangerous:
            return _block_response(fmt, reason, f"{tool_name} {raw_patch[:60]}")

    # --- Codex apply_patch path ---
    #
    # Checked as *both* a command and a file edit: the envelope is a shell
    # command (so the dangerous-flag scanning applies to it) and the patch body
    # writes files (so the env-persistence check must see its targets). A call
    # with no `command` falls through instead of returning, so a path + content
    # payload under this name still reaches the shape-based fallback (#1048).
    if tool_lower == _APPLY_PATCH_TOOL_NAME and command:
        is_dangerous, reason = check_command(command)
        if is_dangerous:
            return _block_response(fmt, reason, command)
        is_dangerous, reason = check_env_persistence_in_apply_patch(command)
        if is_dangerous:
            return _block_response(fmt, reason, f"{tool_name} {command[:60]}")
        return 0

    # --- File-edit tool path (Edit/Write/MultiEdit/write_file/replace/create) ---
    if tool_lower in _FILE_EDIT_TOOL_NAMES:
        # Copilot's create/edit content key is not confirmed (#1037): scan
        # every string value rather than trust a guessed key name. Gated on
        # the Copilot format, not just the tool name, so Claude's "Edit"
        # (which lower-cases to the same "edit") keeps its precise,
        # key-based check instead.
        scan_all_values = fmt == "copilot" and tool_lower in _COPILOT_SCAN_ALL_VALUES_TOOLS
        is_dangerous, reason = check_env_persistence_in_file_edit(
            tool_name, tool_input, scan_all_values=scan_all_values
        )
        if is_dangerous:
            file_path = _resolve_file_path(tool_input)
            return _block_response(fmt, reason, f"{tool_name} {file_path}")
        return 0

    # --- Shape-based fallback for a tool name this hook doesn't recognise ---
    #
    # Fails closed on shape rather than falling through to allow (#1037): a
    # new or renamed edit tool, or one this hook has never seen (Copilot's
    # vendor docs are not a live probe), still gets checked when its
    # tool_input carries both a path key and a content key -- the shape of a
    # write. A read-only tool (Read, Grep, Glob, a `view` tool) carries a
    # path but no content key, so it does not match and is still allowed.
    if isinstance(tool_input, dict) and _looks_like_file_edit(tool_input):
        is_dangerous, reason = check_env_persistence_in_file_edit(tool_name, tool_input)
        if is_dangerous:
            file_path = _resolve_file_path(tool_input)
            return _block_response(fmt, reason, f"{tool_name} {file_path}")
        return 0

    return 0


def run() -> int:
    """Invoke :func:`main`, denying rather than propagating any internal error.

    Without this guard an unexpected exception produces no deny payload at all,
    which the stdout-contract CLIs (Antigravity, Copilot) read as "allow".
    """
    try:
        return main()
    # Broad by design: a hook that cannot evaluate a command must deny.
    except Exception as exc:
        return _fail_closed(f"hook raised {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    sys.exit(run())
