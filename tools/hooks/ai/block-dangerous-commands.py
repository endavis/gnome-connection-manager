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
import stat
import subprocess  # nosec B404  # needed for git branch detection
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


_SHELL_OPERATORS = frozenset({"&", "|&", ";", "&&", "||", "|", "(", ")"})

# Every punctuation token the shell reads, longest first, for splitting a run
# that shlex returns as one token (``)&&``, ``;(``).
_SHELL_PUNCTUATION = sorted(
    _SHELL_OPERATORS
    | {"&>>", ";;&", "<<<", ";;", ";&", ">>", "<<", ">&", "<&", "&>", ">|", "<>", "<", ">"},
    key=len,
    reverse=True,
)


def _split_punctuation(run: str) -> list[tuple[str, bool]]:
    """Split a run of shell punctuation into its tokens, longest match first."""
    tokens: list[tuple[str, bool]] = []
    i = 0
    while i < len(run):
        token = next((p for p in _SHELL_PUNCTUATION if run.startswith(p, i)), run[i])
        tokens.append((token, token in _SHELL_OPERATORS))
        i += len(token)
    return tokens


class _OpenConstructError(Exception):
    """Raised when a quote or substitution is not closed, or cannot be read safely."""


# Text inside a substitution that this scanner does not model: a ``case``
# statement (its ``)`` pattern terminators) or a here-document (``<<``).
_UNMODELLED_IN_SUBSTITUTION = re.compile(r"(?<!\w)case(?!\w)|(?<!<)<<(?!<)")


def _skip_single(text: str, i: int) -> int:
    """Return the index after the ``'`` that closes the string opened before *i*."""
    end = text.find("'", i)
    if end == -1:
        raise _OpenConstructError
    return end + 1


def _skip_ansi(text: str, i: int) -> int:
    """Return the index after the end of a ``$'...'`` string whose body starts at *i*."""
    while i < len(text):
        if text[i] == "\\":
            i += 2
        elif text[i] == "'":
            return i + 1
        else:
            i += 1
    raise _OpenConstructError


def _skip_backtick(text: str, i: int) -> int:
    """Return the index after the backtick that closes the one opened before *i*."""
    while i < len(text):
        if text[i] == "\\":
            i += 2
        elif text[i] == "`":
            return i + 1
        else:
            i += 1
    raise _OpenConstructError


def _skip_dollar(text: str, i: int, *, ansi: bool, in_double: bool = False) -> int:
    """Return the index after the ``$`` construct at *i* (``$(``, ``${``, ``$'``).

    *in_double* says the construct sits in a double quote, where a ``'`` inside
    ``${...}`` is an ordinary character.
    """
    if ansi and text.startswith("$'", i):
        return _skip_ansi(text, i + 2)
    if text.startswith("$(", i):
        return _skip_paren(text, i + 2)
    if text.startswith("${", i):
        return _skip_brace(text, i + 2, in_double=in_double)
    return i + 1


def _skip_double(text: str, i: int) -> int:
    """Return the index after the ``"`` that closes the string opened before *i*."""
    while i < len(text):
        char = text[i]
        if char == "\\":
            i += 2
        elif char == '"':
            return i + 1
        elif char == "$":
            i = _skip_dollar(text, i, ansi=False, in_double=True)
        elif char == "`":
            i = _skip_backtick(text, i + 1)
        else:
            i += 1
    raise _OpenConstructError


def _skip_brace(text: str, i: int, *, in_double: bool = False) -> int:
    """Return the index after the ``}`` that closes the ``${`` whose body starts at *i*.

    *in_double* says the expansion sits in a double quote, where a ``'`` and a
    ``$'`` are ordinary text; bare, they quote.
    """
    while i < len(text):
        char = text[i]
        if char == "\\":
            i += 2
        elif char == "'" and not in_double:
            i = _skip_single(text, i + 1)
        elif char == '"':
            i = _skip_double(text, i + 1)
        elif char == "$":
            i = _skip_dollar(text, i, ansi=not in_double, in_double=in_double)
        elif char == "`":
            i = _skip_backtick(text, i + 1)
        elif char == "}":
            return i + 1
        else:
            i += 1
    raise _OpenConstructError


def _skip_paren(text: str, i: int) -> int:
    """Return the index after the ``)`` that closes the construct whose body starts at *i*."""
    start = i
    depth = 1
    while i < len(text):
        char = text[i]
        if char == "\\":
            i += 2
        elif char == "'":
            i = _skip_single(text, i + 1)
        elif char == '"':
            i = _skip_double(text, i + 1)
        elif char == "$":
            i = _skip_dollar(text, i, ansi=True)
        elif char == "`":
            i = _skip_backtick(text, i + 1)
        elif char == "#" and (i == start or text[i - 1].isspace() or text[i - 1] in "&|;()<>"):
            raise _OpenConstructError
        elif char in "()":
            depth += 1 if char == "(" else -1
            i += 1
            if depth == 0:
                if _UNMODELLED_IN_SUBSTITUTION.search(text, start, i):
                    raise _OpenConstructError
                return i
        else:
            i += 1
    raise _OpenConstructError


def _scan_tokens(command: str) -> list[tuple[str, bool]]:
    """Scan *command* left to right; raise ``_OpenConstructError`` when it cannot be read."""
    punctuation = "&|;()<>"
    result: list[tuple[str, bool]] = []
    word_start: int | None = None
    n = len(command)

    def flush(end: int) -> None:
        nonlocal word_start
        if word_start is not None:
            word = command[word_start:end]
            if word in ("case", "[["):
                raise _OpenConstructError
            result.append((word, False))
            word_start = None

    def starts_substitution(at: int) -> bool:
        return command[at] in "<>" and command.startswith("(", at + 1)

    i = 0
    while i < n:
        char = command[i]
        if char.isspace():
            flush(i)
            i += 1
        elif char in punctuation and not starts_substitution(i):
            flush(i)
            j = i
            while j < n and command[j] in punctuation and not starts_substitution(j):
                j += 1
            tokens = _split_punctuation(command[i:j])
            if "((" in command[i:j] or any(text == "<<" for text, _ in tokens):
                raise _OpenConstructError
            result.extend(tokens)
            i = j
        else:
            if word_start is None:
                word_start = i
                if char == "#":
                    end = command.find("\n", i)
                    end = n if end == -1 else end
                    result.extend((piece, False) for piece in command[i:end].split())
                    word_start = None
                    i = end
                    continue
            if char == "\\":
                i += 2
            elif char == "'":
                i = _skip_single(command, i + 1)
            elif char == '"':
                i = _skip_double(command, i + 1)
            elif char == "$":
                i = _skip_dollar(command, i, ansi=True)
            elif char == "`":
                i = _skip_backtick(command, i + 1)
            elif starts_substitution(i):
                i = _skip_paren(command, i + 2)
            else:
                i += 1
            if i > n:
                raise _OpenConstructError
    flush(n)
    return result


def operator_tokens(command: str) -> list[tuple[str, bool]]:
    """
    Split *command* into ``(text, is_operator)`` tokens.

    A single left-to-right character scanner (``shlex`` is not used). Words end
    at top-level whitespace and at top-level punctuation, so operators glued to
    words (``a;b``, ``x&&y``) come out as separate tokens. ``is_operator`` is
    True only for the control operators ``&``, ``|&``, ``;``, ``&&``, ``||``,
    ``|``, ``(`` and ``)``. Redirect punctuation (``>``, ``>&``, ``&>``,
    ``<``, ``;;``) is returned as a word.

    Text the shell reads as one unit stays inside its word, whatever it holds:
    a backslash escape, ``'...'``, ``"..."`` (where ``\\"``, ``\\\\``, ``\\$`` and
    a backslash before a backtick escape), ``$'...'``, ``$(...)``, ``$((...))``,
    ``${...}``, backtick substitution and ``<(...)`` / ``>(...)``, all nested.
    A ``#`` that starts a word begins a comment; its text is returned as words.

    The result never contains an operator the shell would not see. When the
    command holds an unclosed construct, a top-level ``((`` or here-document
    ``<<``, a ``[[`` or ``case`` word, or a substitution holding a comment,
    ``case`` or ``<<``, every whitespace-separated piece is returned as a word.
    Never raises.

    The words-only result can miss an operator but never reports one the shell
    would not see. It suits callers where a missed operator only widens what
    they check (such as ending an argument scan), not callers that need every
    command start. A newline is read as whitespace, not as a separator.
    """
    try:
        return _scan_tokens(command)
    except (_OpenConstructError, RecursionError):
        return [(word, False) for word in command.split()]


_ANSI_C_SIMPLE = {
    "a": "\a",
    "b": "\b",
    "e": "\x1b",
    "E": "\x1b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
    "\\": "\\",
    "'": "'",
    '"': '"',
    "?": "?",
}
_ANSI_C_NUMERIC = re.compile(
    r"([0-7]{1,3})|x([0-9a-fA-F]{1,2})|u([0-9a-fA-F]{1,4})|U([0-9a-fA-F]{1,8})"
)


def _decode_ansi_c(body: str) -> str | None:
    """Return the text bash makes of a ``$'...'`` body, or None when unsure.

    Only the escapes bash defines are decoded: the single-character ones,
    1-3 octal digits (masked to a byte, as bash does), ``\\x`` with 1-2 hex
    digits and ``\\u``/``\\U`` with up to 4/8. Any other escape (``\\c``,
    ``\\N``, a bare ``\\x``) and any non-ASCII text or result give None.
    """
    if not body.isascii():
        return None
    out: list[str] = []
    i = 0
    while i < len(body):
        if body[i] != "\\":
            out.append(body[i])
            i += 1
            continue
        if i + 1 >= len(body):
            return None
        nxt = body[i + 1]
        if nxt in _ANSI_C_SIMPLE:
            out.append(_ANSI_C_SIMPLE[nxt])
            i += 2
            continue
        match = _ANSI_C_NUMERIC.match(body, i + 1)
        if match is None:
            return None
        octal, hex2, hex4, hex8 = match.groups()
        code = int(octal, 8) & 0xFF if octal is not None else int(hex2 or hex4 or hex8, 16)
        if code > 0x7F:
            return None
        out.append(chr(code))
        i = match.end()
    return "".join(out)


def _ansi_word(word: str) -> str | None:
    """Return the text bash passes for a word holding ``$'...'``, or None.

    ``'...'`` is literal, ``$'...'`` is decoded, ``"..."`` loses its quotes and
    the backslash before ``\\``, ``"``, ``$`` and a backtick, and a bare
    backslash escapes the next character. Any ``$`` expansion other than
    ``$'`` is kept as written, as the dynamic target match expects.
    """
    out: list[str] = []
    i = 0
    while i < len(word):
        char = word[i]
        if word.startswith("$'", i):
            end = _skip_ansi(word, i + 2)
            decoded = _decode_ansi_c(word[i + 2 : end - 1])
            if decoded is None:
                return None
            out.append(decoded)
            i = end
        elif char == "'":
            end = _skip_single(word, i + 1)
            out.append(word[i + 1 : end - 1])
            i = end
        elif char == '"':
            end = _skip_double(word, i + 1)
            out.append(re.sub(r'\\([\\"$`])', r"\1", word[i + 1 : end - 1]))
            i = end
        elif char == "\\" and i + 1 < len(word):
            out.append(word[i + 1])
            i += 2
        else:
            out.append(char)
            i += 1
    return "".join(out)


def _exact_operator_tokens(command: str) -> list[str] | None:
    """Return *command* as strings with each real operator as its own token.

    Unlike :func:`operator_tokens` it returns None when the command cannot be
    read, so the caller can tell that apart from a command with no operators.
    An operator keeps its text. A word holding ``$'`` gets the text bash would
    pass (:func:`_ansi_word`), or keeps its raw text when that can't be read. A
    word holding another ``$`` or a backtick loses its quote characters
    (``"$PWD/x"`` becomes ``$PWD/x``). Any other word is dequoted, except that a word whose dequoted
    text is empty or equals an operator string (``'&'``, ``\\&``) keeps its
    raw text, so a token equal to an operator string is always a real operator.
    """
    try:
        scanned = _scan_tokens(command)
    except (_OpenConstructError, RecursionError):
        return None
    result: list[str] = []
    for text, is_operator in scanned:
        if is_operator:
            result.append(text)
            continue
        if "$'" in text:
            try:
                decoded = _ansi_word(text)
            except _OpenConstructError:
                decoded = None
            ok = decoded is not None and decoded and decoded not in _SHELL_OPERATORS
            result.append(decoded if ok and decoded is not None else text)
            continue
        if "$" in text or "`" in text:
            # shlex would expand nothing but could split a substitution; drop
            # the quote characters so `"$PWD/x"` reads as `$PWD/x`, the form
            # the dynamic target match expects
            stripped = text.replace('"', "").replace("'", "")
            result.append(stripped if stripped not in _SHELL_OPERATORS else text)
            continue
        try:
            dequoted = "".join(shlex.split(text))
        except ValueError:
            dequoted = text
        if not dequoted or dequoted in _SHELL_OPERATORS:
            dequoted = text
        result.append(dequoted)
    return result


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


# Characters that end the delimiter word after `<<`: a blank or a shell
# metacharacter. Anything else, such as `\r`, is still part of the word.
_HEREDOC_WORD_ENDS = frozenset(" \t|&;()<>")


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


def _heredoc_logical_line(lines: list[str], start: int, join: bool) -> tuple[str, int]:
    """Return the body line starting at *start* as bash reads it, and the next index.

    With an unquoted delimiter (*join*), bash joins a line ending in an odd
    number of backslashes with the next one, dropping that backslash, before
    comparing it to the delimiter: ``EO\\`` then ``F`` ends a ``<<EOF`` body
    (#1113). An even count is an escaped backslash and joins nothing.
    """
    text = lines[start]
    index = start + 1
    while join and index < len(lines) and (len(text) - len(text.rstrip("\\"))) % 2 == 1:
        text = text[:-1] + lines[index]
        index += 1
    return text, index


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


def _heredocs(
    lines: list[str], *, unclear_as_body: bool = False
) -> list[tuple[int, list[str], int, int]]:
    """Find each heredoc in *lines*.

    Returns ``(marker_line, owner_words, body_start, body_end)`` per heredoc:
    the line holding the ``<<`` marker, the words of the command that owns it,
    and the body as the half-open line range ``[body_start, body_end)``. The
    terminator, when present, is line ``body_end``.

    *lines* must be the command split at ``\\n`` only, as bash splits it, not
    by ``str.splitlines()``, which also breaks at ``\\r``, ``\\v``, ``\\f`` and
    other characters bash keeps inside a line (#1102).

    When the delimiter is unclear or never terminated, where the body ends is
    unknown. By default the heredoc is then left out, so a caller stripping
    bodies keeps every later line in its scans. With *unclear_as_body* it is
    returned with its body running to the last line, so a caller re-scanning
    bodies as code checks every later line too. Either way the guess errs
    toward checking more.
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

        # The command owning this heredoc is the last segment before it.
        words = re.split(r"[;&|]", lines[index][: match.start()])[-1].split()

        after = lines[index][match.end() : match.end() + 1]
        if after and after not in _HEREDOC_WORD_ENDS:
            # The delimiter word goes on past what the marker regex took, e.g.
            # a trailing `\r`, so the shell's delimiter is not the one matched
            # here and where the body ends is unknown (#1102).
            if unclear_as_body:
                found.append((index, words, index + 1, len(lines)))
            break

        strip_leading_tabs = bool(match.group(1))
        delimiter = match.group(3) or match.group(4) or match.group(5)
        # only a bare delimiter has its body lines joined at a trailing `\`
        join = match.group(5) is not None

        cursor = index + 1
        terminator_end = cursor
        while cursor < len(lines):
            logical, terminator_end = _heredoc_logical_line(lines, cursor, join)
            if _heredoc_terminator(logical, strip_leading_tabs) == delimiter:
                break
            cursor = terminator_end
        else:
            cursor = len(lines)
        # The terminator matched line by line, without joining
        plain = next(
            (
                k
                for k in range(index + 1, len(lines))
                if _heredoc_terminator(lines[k], strip_leading_tabs) == delimiter
            ),
            len(lines),
        )
        if join and plain != cursor:
            # A shell that did not join lines would end the body elsewhere, so
            # where it ends is unclear: treat it as for an unclear delimiter
            if unclear_as_body:
                found.append((index, words, index + 1, len(lines)))
            break
        if cursor == len(lines) and not unclear_as_body:
            # No terminator. Should this scan's idea of the delimiter differ
            # from the shell's, the rest of the command is not body at all, so
            # leave it in the scans rather than drop it (#1102).
            break

        found.append((index, words, index + 1, cursor))
        # a terminator joined from several lines spans them all
        index = max(cursor + 1, terminator_end)
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

    The receiving shell joins a line ending in an odd number of backslashes
    with the next one, whether or not the delimiter was quoted, so the joined
    lines are yielded too (#1122). The physical lines stay as well: inside a
    quoted string in the script a backslash-newline is kept, and checking both
    readings covers either.
    """
    lines = command.split("\n")  # bash ends a line only at \n (#1102)
    payloads: list[str] = []
    for _marker, words, body_start, body_end in _heredocs(lines, unclear_as_body=True):
        if _reads_stdin_as_code(words):
            body = lines[body_start:body_end]
            payloads += [line for line in body if line.strip()]
            # `<<-` strips each line's leading tabs before the shell joins
            # them; joining both readings covers either operator
            for reading in (body, [line.lstrip("\t") for line in body]):
                payloads += [
                    line
                    for line in _joined_continuation_lines(reading)
                    if line.strip() and line not in body and line not in payloads
                ]
    return payloads


def _expansion_payloads(text: str, i: int, payloads: list[str], *, in_double: bool) -> None:
    """Collect the ``$(...)`` and backtick bodies inside a ``${...}`` at *i*.

    A default or alternate value (``${x:-$(cmd)}``) is expanded by the shell, so
    the command in it runs. The end of the expansion comes from
    :func:`_skip_brace`, the function every caller uses to step past it, and the
    text inside is read with the same quoting rules, so this scan and the skip
    cannot disagree about where the expansion ends or which parts are quoted.
    *in_double* says the expansion sits in a double quote, where a ``'`` is an
    ordinary character; bare, it quotes.
    Text that cannot be read is left unreported, as the caller skips the whole
    expansion anyway.
    """
    try:
        stop = _skip_brace(text, i + 2, in_double=in_double) - 1
        j = i + 2
        while j < stop:
            char = text[j]
            if char == "\\":
                j += 2
            elif char == "'" and not in_double:
                j = _skip_single(text, j + 1)
            elif char == '"':
                j = _double_quoted_payloads(text, j + 1, payloads)
            elif char == "`":
                end = _skip_backtick(text, j + 1)
                payloads.append(text[j + 1 : end - 1])
                j = end
            elif text.startswith("$(", j) and not text.startswith("$((", j):
                end = _skip_paren(text, j + 2)
                payloads.append(text[j + 2 : end - 1])
                j = end
            elif text.startswith("${", j):
                _expansion_payloads(text, j, payloads, in_double=in_double)
                j = _skip_dollar(text, j, ansi=not in_double, in_double=in_double)
            elif char == "$":
                j = _skip_dollar(text, j, ansi=not in_double, in_double=in_double)
            else:
                j += 1
    except _OpenConstructError:
        return


def _double_quoted_payloads(text: str, i: int, payloads: list[str]) -> int:
    """Collect the bodies of ``$(...)`` and backticks in a double-quoted string.

    *i* is the index after the opening ``"``. Returns the index after the
    closing quote. An arithmetic ``$((...))`` and an escaped ``\\$`` hold no
    command, and are skipped.
    """
    while i < len(text):
        char = text[i]
        if char == "\\":
            i += 2
        elif char == '"':
            return i + 1
        elif char == "`":
            end = _skip_backtick(text, i + 1)
            payloads.append(text[i + 1 : end - 1])
            i = end
        elif text.startswith("$(", i) and not text.startswith("$((", i):
            end = _skip_paren(text, i + 2)
            payloads.append(text[i + 2 : end - 1])
            i = end
        elif char == "$":
            if text.startswith("${", i):
                _expansion_payloads(text, i, payloads, in_double=True)
            i = _skip_dollar(text, i, ansi=False)
        else:
            i += 1
    raise _OpenConstructError


def _heredoc_body_payloads(body: str, payloads: list[str]) -> None:
    """Collect the ``$(...)`` and backtick bodies in an unquoted-delimiter heredoc body.

    The shell expands these in such a body as it does inside double quotes,
    except that a ``"`` is an ordinary character. An arithmetic ``$((...))``
    and an escaped ``\\$`` hold no command. A construct that cannot be read is
    passed over a character at a time.
    """
    i = 0
    while i < len(body):
        char = body[i]
        try:
            if char == "\\":
                i += 2
            elif char == "`":
                end = _skip_backtick(body, i + 1)
                payloads.append(body[i + 1 : end - 1])
                i = end
            elif body.startswith("$((", i):
                i = _skip_paren(body, i + 2)
            elif body.startswith("$(", i):
                end = _skip_paren(body, i + 2)
                payloads.append(body[i + 2 : end - 1])
                i = end
            elif char == "$":
                if body.startswith("${", i):
                    _expansion_payloads(body, i, payloads, in_double=True)
                i = _skip_dollar(body, i, ansi=False)
            else:
                i += 1
        except _OpenConstructError:
            i += 1


def _consume_heredoc_bodies(
    command: str, pos: int, pending: list[tuple[str, bool, bool]], payloads: list[str]
) -> int:
    """Read the bodies of the heredocs in *pending*, starting at line start *pos*.

    Each entry is ``(delimiter, unquoted, strip_tabs)``. The body of a
    quoted-delimiter heredoc is skipped; the substitutions in an unquoted one
    are collected into *payloads*. Returns the index after the last terminator.
    """
    for delimiter, unquoted, strip_tabs in pending:
        body: list[str] = []
        while pos < len(command):
            newline = command.find("\n", pos)
            line_end = len(command) if newline == -1 else newline
            line = command[pos:line_end]
            pos = line_end + 1
            logical = line
            if unquoted:
                # Bash joins a line ending in an odd number of backslashes
                # with the next before comparing it to the delimiter, as
                # :func:`_heredoc_logical_line` does.
                joined_to = pos
                while (len(logical) - len(logical.rstrip("\\"))) % 2 == 1 and joined_to < len(
                    command
                ):
                    next_end = command.find("\n", joined_to)
                    next_end = len(command) if next_end == -1 else next_end
                    logical = logical[:-1] + command[joined_to:next_end]
                    joined_to = next_end + 1
                if (logical.lstrip("\t") if strip_tabs else logical) == delimiter:
                    pos = joined_to
                    break
            elif (line.lstrip("\t") if strip_tabs else line) == delimiter:
                break
            body.append(line)
        if unquoted:
            _heredoc_body_payloads("\n".join(body), payloads)
    return min(pos, len(command))


def _opens_subshell(command: str, i: int) -> bool:
    """Whether the ``(`` at *i* opens a subshell rather than something else.

    Not a subshell: ``$(``, ``<(`` and ``>(`` (read elsewhere), an assignment
    ``name=(...)`` or ``name+=(...)``, and a function definition ``f()``. A
    ``(`` right after a reserved word (``then(...)``, ``do(...)``) is one.
    """
    previous = command[i - 1] if i else " "
    if previous in "$<>=":
        return False
    if previous.isalnum() or previous == "_":
        word = re.search(r"[^\s;&|()<>]*\Z", command[:i])
        return word is not None and word.group() in _COMMAND_KEYWORDS
    return True


def _substitution_payloads(command: str) -> list[str]:
    """Return the body of each command substitution, process substitution and subshell.

    These bodies are shell the current shell runs: ``$(...)`` and backticks
    (bare or inside double quotes), ``<(...)`` and ``>(...)``, and a ``(...)``
    group in command position. :func:`check_command` re-scans each one, as it
    does a ``bash -c`` payload, so a check anchored on a command position
    sees the command inside. Text in single quotes, ``$'...'``, an escaped
    ``$``, an arithmetic ``$((...))``, an array literal ``a=(...)`` and a
    function definition ``f()`` hold no such body and are skipped, as is the
    body of a heredoc with a quoted delimiter. The body of one with an
    unquoted delimiter is read for substitutions.

    A nested body is returned inside its parent only; :func:`check_command`
    reaches it through :func:`_all_substitution_payloads`. A construct that
    cannot be read, such as a heredoc inside ``$(...)``, is passed over and the
    scan goes on after its first character, so a later substitution is found.
    """
    payloads: list[str] = []
    pending: list[tuple[str, bool, bool]] = []
    i = 0
    while i < len(command):
        start = i
        char = command[i]
        previous = command[i - 1] if i else " "
        try:
            if char == "\\":
                i += 2
            elif char == "'":
                i = _skip_single(command, i + 1)
            elif char == '"':
                i = _double_quoted_payloads(command, i + 1, payloads)
            elif command.startswith("$'", i):
                i = _skip_ansi(command, i + 2)
            elif command.startswith("$((", i):
                i = _skip_paren(command, i + 2)
            elif command.startswith("$(", i) or (char in "<>" and command.startswith("(", i + 1)):
                end = _skip_paren(command, i + 2)
                payloads.append(command[i + 2 : end - 1])
                i = end
            elif char == "$":
                if command.startswith("${", i):
                    _expansion_payloads(command, i, payloads, in_double=False)
                i = _skip_dollar(command, i, ansi=False)
            elif char == "`":
                end = _skip_backtick(command, i + 1)
                payloads.append(command[i + 1 : end - 1])
                i = end
            elif char == "(" and _opens_subshell(command, i):
                end = _skip_paren(command, i + 1)
                payloads.append(command[i + 1 : end - 1])
                i = end
            elif char == "<" and previous != "<" and (marker := _HEREDOC_START.match(command, i)):
                after = command[marker.end() : marker.end() + 1]
                if after and after != "\n" and after not in _HEREDOC_WORD_ENDS:
                    # The delimiter word goes on past what the marker regex
                    # took, so the shell's delimiter is not the one matched
                    # and where the body ends is unknown. Register no
                    # heredoc, so the lines that follow are read as commands,
                    # as :func:`_heredocs` leaves such a body unstripped.
                    i = marker.end()
                    continue
                delimiter = marker.group(3) or marker.group(4) or marker.group(5)
                pending.append((delimiter, marker.group(5) is not None, bool(marker.group(1))))
                i = marker.end()
            elif char == "\n" and pending:
                i = _consume_heredoc_bodies(command, i + 1, pending, payloads)
                pending.clear()
            else:
                i += 1
        except _OpenConstructError:
            i = start + 1
    return list(dict.fromkeys(payloads))


def _unquoted_heredoc_bodies(command: str) -> list[str]:
    """Return the body of each heredoc in *command* whose delimiter is unquoted."""
    lines = command.split("\n")
    bodies: list[str] = []
    for marker_line, _words, body_start, body_end in _heredocs(lines, unclear_as_body=True):
        match, _quote = _heredoc_marker_match(lines[marker_line])
        if match is not None and match.group(5) is None:
            continue  # a quoted delimiter: the body is not expanded
        bodies.append("\n".join(lines[body_start:body_end]))
    return bodies


# Most substitution bodies read from one command, so a pathological input
# cannot make the scan unbounded.
_MAX_SUBSTITUTION_PAYLOADS = 256


def _all_substitution_payloads(command: str) -> list[str] | None:
    """Return every substitution body in *command*, nested ones included.

    Nesting is followed here, one level at a time, so it does not use the
    recursion budget of :func:`check_command`. Returns None when the input
    holds more than ``_MAX_SUBSTITUTION_PAYLOADS`` bodies, which the caller
    treats as unreadable.
    """
    result: list[str] = []
    seen = {command}
    queue = [command]
    while queue:
        text = queue.pop(0)
        found = _substitution_payloads(_strip_shell_comments(_without_heredoc_bodies(text)))
        for body in _unquoted_heredoc_bodies(text):
            _heredoc_body_payloads(body, found)
        for payload in found:
            if payload in seen:
                continue
            seen.add(payload)
            if len(result) >= _MAX_SUBSTITUTION_PAYLOADS:
                return None
            result.append(payload)
            queue.append(payload)
    return result


def _joined_continuation_lines(lines: list[str]) -> list[str]:
    """Join each line ending in an odd number of backslashes with the next one.

    The trailing backslash is dropped, as the shell drops a backslash-newline.
    An even count is an escaped backslash and joins nothing.
    """
    joined: list[str] = []
    current: str | None = None
    for line in lines:
        current = line if current is None else current[:-1] + line
        if (len(current) - len(current.rstrip("\\"))) % 2 == 0:
            joined.append(current)
            current = None
    if current is not None:
        joined.append(current)
    return joined


def _without_heredoc_bodies(command: str) -> str:
    """Return *command* with every heredoc body and terminator line removed.

    A body is the receiver's stdin, not its arguments. The credential-read
    check scans a reader's arguments past a redirection (#1007, gap 4), so
    without this `cat >> notes.md <<EOF` would read its own body's text as
    file names. A body that is run as code is still checked, line by line,
    through :func:`_heredoc_payloads`.
    """
    lines = command.split("\n")  # bash ends a line only at \n (#1102)
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


# Command names the rules key on. A path-qualified spelling (``/usr/bin/git``,
# ``./bin/gh``) runs the same program, so :func:`_normalise_command_words`
# reduces it to the bare name before any rule sees the tokens (#1132).
_RULE_COMMAND_WORDS = (
    frozenset(
        {"git", "gh", "uv", "doit", "patch", "rm", "sudo", "env", "printenv"}
        | {"bash", "sh", "zsh", "dash"}
    )
    | _CREDENTIAL_READER_COMMANDS
)


def _normalise_command_words(tokens: list[str]) -> list[str]:
    """Return *tokens* with each path-qualified rule word reduced to its basename.

    The one place a command word is normalised. Every non-option token whose
    basename is a rule command word is reduced, wherever it sits, so a rule
    word after a keyword, wrapper, option or substitution is still seen
    (fails closed). The result has the same length as *tokens*, so an index
    in one list is the same token in the other.

    Only rules that key on a command word read this list. Checks that treat a
    token as a filesystem path (patch sources, redirect and stdin targets,
    credential-store paths, persistence targets) read the original tokens.
    """
    normalised = list(tokens)
    for index, token in enumerate(tokens):
        if "/" not in token or token[0] in "-<>&":
            continue
        base = token.rsplit("/", 1)[-1]
        if base.lower() in _RULE_COMMAND_WORDS:
            normalised[index] = base
    return normalised


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
        result = subprocess.run(  # nosec B603 B607  # trusted git command
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
    """Return True when the example file's bytes differ from HEAD's (#1061).

    The bytes are compared directly, not through ``git diff``: the index flags
    ``--skip-worktree`` and ``--assume-unchanged`` make ``git diff`` skip the
    worktree and report no difference for a swapped file.

    Inside a repo, an example missing from HEAD (untracked, or no commit yet)
    counts as modified: there is nothing to vouch for it. Fails open (False)
    when git is missing, times out or the directory is not a repo: the gated
    ``cp`` is a documented setup step and the hook is a guardrail (ADR-9019).
    """
    try:
        current = Path(_ENVRC_EXAMPLE).read_bytes()
    except OSError:
        return False  # no example to copy, so the `cp` fails on its own
    try:
        inside = subprocess.run(  # nosec B603 B607  # trusted git command
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            timeout=5,
        )
        if inside.returncode != 0:
            return False
        # The raw blob, never --filters: those run smudge filters a worktree
        # .gitattributes and repo config choose, which can make swapped
        # content match. Line endings are normalised below instead.
        head = subprocess.run(  # nosec B603 B607  # trusted git command
            ["git", "cat-file", "blob", f"HEAD:./{_ENVRC_EXAMPLE}"],
            capture_output=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    if head.returncode != 0:
        return True
    # a clean autocrlf checkout differs from the blob only in CRLF
    return current.replace(b"\r\n", b"\n") != head.stdout.replace(b"\r\n", b"\n")


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

# Tokens that end a command, so an extglob group never folds across them
_EXTGLOB_COMMAND_END = frozenset({";", "&&", "||", "&", "|&"})


def _collapse_extglobs(tokens: list[str]) -> list[str]:
    """Fold each extglob back into one wildcard token (#1061).

    The lexer splits ``.envrc.@(local)`` into ``.envrc.@``, ``(``, ``local``,
    ``)``. Rewrite the introducer as ``*`` and drop the group, so every write
    pattern reads ``.envrc.*`` as one dynamic target. Fails closed: the whole
    group becomes a wildcard whatever it holds.

    A group folds only when its closing ``)`` comes before the end of the
    command. With no ``)`` before a ``;``, ``&&``, ``||``, ``&``, ``|&`` or
    the end of the tokens, the tokens stay as they are (#1104). ``|`` is the
    extglob alternative separator, so it does not end the search. Since the
    group's `|` may be a pipe and its other tokens may be a redirect, every
    folded group keeps its original tokens after the folded one.
    """
    out: list[str] = []
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if i + 1 < n and tokens[i + 1] == "(" and tok[-1:] in _EXTGLOB_INTRODUCERS:
            depth = 0
            j = i + 1
            closed = False
            while j < n and tokens[j] not in _EXTGLOB_COMMAND_END:
                if tokens[j] == "(":
                    depth += 1
                elif tokens[j] == ")":
                    depth -= 1
                    if depth == 0:
                        closed = True
                        break
                j += 1
            if closed:
                out.append(tok[:-1] + "*")
                # the tokens lost their quoting, so `x@'(' | tee f ')'` or
                # `x@'(' > f ')'` looks like a group: keep the original tokens
                # after the wildcard, so an operator inside stays visible (#1120)
                out.extend(tokens[i : j + 1])
                i = j + 1
                continue
        out.append(tok)
        i += 1
    return out


# A `;`, `&&` or `||` attached to a word still ends the command there (#1093).
_GLUED_COMMAND_END = re.compile(r";|&&|\|\|")
# The same operators, only where they end a word
_GLUED_END_OF_WORD = re.compile(r"(?:;|&&|\|\|)$")


_EXACT_COMMAND_END = _COMMAND_SEPARATORS | {"&", "|&", "(", ")"}


def _working_tree_moved(tokens: list[str], git_idx: int, sub: int, paths: list[str]) -> bool:
    """Return True when git may resolve paths against another working tree.

    Covers ``-C``/``--work-tree``/``--git-dir``/``-c core.worktree=``/
    ``--config-env core.worktree=`` between ``git`` and the subcommand, a
    ``cd``/``pushd``/``popd``/``env -C`` earlier in the command when a pathspec
    could climb out of the new directory (a ``..`` segment, a ``/``, ``~`` or
    ``:`` start, or a shell expansion: any other relative pathspec stays below
    it), and any mention of ``GIT_WORK_TREE``, ``GIT_DIR`` or ``GIT_CONFIG``
    before ``git`` (set by ``=``, ``read`` or ``printf -v``). An earlier
    ``core.worktree`` or include setting (``git config core.worktree ..``) or a
    path under ``.git/`` can move it through the repository config too. When
    unsure, this answers True.
    """
    # a shell expansion (`.?`, `$UP`) or a git magic pathspec (`:(top)`) may
    # also climb, so either counts as climbing
    climbs = any(
        path.startswith(("/", "~", ":"))
        or ".." in path.replace("\\", "/").split("/")
        or any(c in "$`{}*?[]~" for c in path)
        for path in paths
    )
    for t in tokens[:git_idx]:
        lowered = t.lower()
        if (
            ((t in {"cd", "pushd", "popd", "-C"} or t.startswith(("--chdir", "-C"))) and climbs)
            or "GIT_WORK_TREE" in t
            or "GIT_DIR" in t
            or "GIT_CONFIG" in t
            or "core.worktree" in lowered
            or "include" in lowered
            or ".git/" in t
        ):
            return True

    def moves(key: str) -> bool:
        lowered = key.lower()
        return lowered.startswith("core.worktree") or "include" in lowered

    opts = tokens[git_idx + 1 : sub]
    for k, t in enumerate(opts):
        if t.startswith(("-C", "--work-tree", "--git-dir")):
            return True
        if t == "-c" and k + 1 < len(opts) and moves(opts[k + 1]):
            return True
        if t.startswith("-c") and t != "-c" and moves(t[2:]):
            return True
        if t.startswith("--config-env"):
            value = t.partition("=")[2] or (opts[k + 1] if k + 1 < len(opts) else "")
            if moves(value):
                return True
    return False


def _has_quoted_redirect_word(command: str) -> bool:
    """Return True if *command* holds a word that may be a quoted redirect operator.

    A word with quoting or an escape whose remaining characters are all redirect
    punctuation, at least one of them ``<`` or ``>`` (``'>'``, ``"\\>>"``, ``\\>``).
    The tokens the scans read have lost that quoting, so they cannot tell it
    from a real operator (#1134). Over-approximates on purpose: it fails closed.
    Never raises.
    """
    for text, is_operator in operator_tokens(command):
        if is_operator or not any(c in text for c in "'\"\\"):
            continue
        bare = "".join(c for c in text if c not in "'\"\\$")
        if bare and set(bare) <= set(_REDIRECT_PUNCTUATION) and ("<" in bare or ">" in bare):
            return True
    return False


def _scan_command_words(
    tokens: list[str],
    start: int,
    *,
    glued_separators: bool = False,
    exact_operators: bool = False,
    literal_redirects: bool = False,
) -> tuple[list[str], list[tuple[str, str]], list[str]]:
    """Return the words of the command whose arguments begin at *start*.

    The scan ends where bash ends the command: at ``_COMMAND_SEPARATORS``, or
    ``_EXACT_COMMAND_END`` when *exact_operators* is set, and, with
    *glued_separators*, at a ``;``, ``&&`` or ``||`` attached to a word.
    Returns ``(arguments, redirects, after_glued)``:

    - *arguments*: the words, redirect operators and their targets left out
    - *redirects*: ``(operator, target)`` pairs. The target is not an argument,
      but the tokens lost their quoting (``'>'``), so callers still check it
      against the protected names (#1088)
    - *after_glued*: the tokens after a glued separator, which are no argument
      but may have been quoted (``'x;'``): callers still check them (#1093)

    *glued_separators* is for the ``tokenize()`` tokens, which keep a ``;``,
    ``&&`` or ``||`` attached to a word (``main;``) and have lost its quoting.
    :func:`_redirect_tokens` splits an unquoted operator into its own token and
    keeps a quoted one (``'x;'``) inside the word, so on those tokens a word
    holding ``;`` is a literal argument and the flag stays off (#1093).
    *exact_operators* is for :func:`_exact_operator_tokens`, where every token
    equal to an operator string is a real operator (#1117).

    *literal_redirects* is for a command holding a quoted word made of redirect
    punctuation (``'>'``). The tokens lost their quoting, so such a word cannot
    be told from a real operator; with the flag set a redirect-looking token is
    an ordinary operand, never an operator that swallows the next word (#1134).
    """
    rest: list[str] = []
    redirects: list[tuple[str, str]] = []
    pending_op: str | None = None
    glued_at: int | None = None
    for idx, t in enumerate(tokens[start:]):
        if pending_op is not None:
            redirects.append((pending_op, t))
            pending_op = None
            continue
        if t in (_EXACT_COMMAND_END if exact_operators else _COMMAND_SEPARATORS):
            break
        glued = _GLUED_COMMAND_END.search(t) if glued_separators and not exact_operators else None
        if glued:
            # `main;` / `main&&`: bash ends the command at the operator, so
            # keep the part before it and stop scanning (#1093)
            if glued.start():
                rest.append(t[: glued.start()])
            glued_at = idx
            break
        if (
            not literal_redirects
            and t
            and set(t) <= set(_REDIRECT_PUNCTUATION)
            and ("<" in t or ">" in t)
        ):
            # a redirect operator as :func:`_redirect_tokens` yields it. A
            # preceding fd number (`2` of `2>`) stays: it can be neither a
            # protected name nor a broad pathspec
            pending_op = t
            continue
        rest.append(t)
    after_glued = [] if glued_at is None else tokens[start + glued_at + 1 :]
    return rest, redirects, after_glued


def _git_restore_targets(
    tokens: list[str],
    git_idx: int,
    *,
    glued_separators: bool = False,
    exact_operators: bool = False,
    literal_redirects: bool = False,
) -> list[str]:
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

    *glued_separators* is for the ``tokenize()`` tokens, which keep a ``;``,
    ``&&`` or ``||`` attached to a word (``main;``) and have lost its quoting.
    :func:`_redirect_tokens` splits an unquoted operator into its own token and
    keeps a quoted one (``'x;'``) inside the word, so on those tokens a word
    holding ``;`` is a literal argument and the flag stays off (#1093).

    *exact_operators* is for :func:`_exact_operator_tokens`, where every token
    equal to an operator string is a real operator: the scan then ends at
    ``&``, ``|&``, ``(`` and ``)`` as well, as bash ends the command there.

    *literal_redirects* is passed to :func:`_scan_command_words`: the tokens lost
    their quoting, so when the command holds a quoted redirect-looking word, one
    in the tokens is read as an operand rather than an operator (#1134).
    """
    sub = _git_subcommand_index(tokens, git_idx)
    if sub is None or tokens[sub] not in {"checkout", "restore"}:
        return []
    rest, redirects, after_glued = _scan_command_words(
        tokens,
        sub + 1,
        glued_separators=glued_separators,
        exact_operators=exact_operators,
        literal_redirects=literal_redirects,
    )
    # the file or fd a redirect points at is no checkout argument, but the
    # tokens lost their quoting (`'>'`), so it is still checked against the
    # protected names below: fail closed (#1088)
    redirect_targets = [target for _, target in redirects]
    paths: list[str] = []
    has_source = False
    if tokens[sub] == "checkout":
        paths = [t for t in rest if not t.startswith("-")]
        if "--" in rest:
            dashes = rest.index("--")
            has_source = any(not t.startswith("-") for t in rest[:dashes])
        else:
            # `--pathspec-from-file` reads the paths from a file, so the one
            # non-option argument is then the revision
            has_source = len(paths) >= 2 or (
                len(paths) >= 1 and any(_long_opt_matches(t, "--pathspec-from-file") for t in rest)
            )
    else:
        skip = False
        for t in rest:
            if skip:
                skip = False
            elif _long_opt_matches(t, "--source") and "=" not in t:
                skip = True
                has_source = True
            elif _long_opt_matches(t, "--source"):
                has_source = True
            elif t.startswith("-") and not t.startswith("--") and t != "-":
                # a short-option cluster: walk it one character at a time.
                # `s` takes a value, the rest of the token or the next token.
                # `U` also takes one; its characters are still walked, which
                # can only read a source where git reads a number
                for pos, ch in enumerate(t[1:], start=1):
                    if ch == "s":
                        has_source = True
                        skip = pos == len(t) - 1
                        break
            elif not t.startswith("-"):
                paths.append(t)
    # `after_glued`: the tokens lost their quoting, so a `;` glued to a word may
    # have been quoted (`'x;'`) and bash not have ended the command. Fail closed:
    # what follows is no argument, but a protected name there is still a target.
    targets = [
        path
        for path in paths + redirect_targets + after_glued
        if _is_env_persistence_target(path, dynamic=True)
    ]
    # `-C`/`--work-tree` move where git resolves paths, so any pathspec may
    # reach the root (`git -C .. checkout X -- repo/`)
    moved = _working_tree_moved(tokens, git_idx, sub, paths)
    if has_source and (
        moved
        or any(_is_broad_pathspec(path) for path in paths)
        or any(_long_opt_matches(t, "--pathspec-from-file") for t in rest)
    ):
        # Stand in the protected name the broad pathspec covers, so the
        # caller's match blocks it
        targets.append(_ENVRC_EXAMPLE)
    return targets


# Largest patch file the hook reads. A bigger one reads as unresolvable.
_PATCH_READ_LIMIT = 4 * 1024 * 1024

_C_QUOTE_SIMPLE = {
    "a": 7,
    "b": 8,
    "f": 12,
    "n": 10,
    "r": 13,
    "t": 9,
    "v": 11,
    '"': 34,
    "\\": 92,
}

_PATCH_HEADER_PREFIXES = (
    "--- ",
    "+++ ",
    "*** ",
    "Index: ",
    "rename from ",
    "rename to ",
    "copy from ",
    "copy to ",
)

# A transfer encoding other than 7bit/8bit/binary (including a folded or
# unrecognised one), or a multipart body, means git decodes the patch before
# reading it, so the raw header lines are not the real paths
_TRANSFER_ENCODING = re.compile(
    r"^content-transfer-encoding:(?![ \t]*(?:7bit|8bit|binary)[ \t]*(?:\r?\n(?![ \t])|\Z))"
    r"|^content-type:[ \t]*multipart",
    re.IGNORECASE | re.MULTILINE,
)


def _unquote_c_path(text: str) -> str | None:
    """Undo git's C-quoting of a path (``"a/\\303\\251"``).

    *text* is latin-1 decoded, so each character is one byte. A text that is
    not quoted is returned unchanged; a quoting that cannot be undone gives
    ``None``.
    """
    if not text.startswith('"'):
        return text
    if len(text) < 2 or not text.endswith('"'):
        return None
    body = text[1:-1]
    out = bytearray()
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == '"':
            return None
        if ch != "\\":
            out.append(ord(ch) & 0xFF)
            i += 1
            continue
        i += 1
        if i >= len(body):
            return None
        ch = body[i]
        if ch in _C_QUOTE_SIMPLE:
            out.append(_C_QUOTE_SIMPLE[ch])
            i += 1
        elif ch in "0123":
            digits = body[i : i + 3]
            if len(digits) < 3 or any(d not in "01234567" for d in digits):
                return None
            out.append(int(digits, 8))
            i += 3
        else:
            return None
    return out.decode("utf-8", "replace")


def _patch_header_paths(data: bytes) -> list[str] | None:
    """Return the file paths a patch's header lines name, or ``None``.

    ``None`` means the paths cannot be told: a quoting that cannot be undone,
    or no header line at all (an empty file, an ed script, a series file).
    Reads ``diff --git``, ``---``/``+++``, ``***``, ``Index:`` and the rename
    and copy lines. Matching is deliberately wide: a hunk line that looks like
    a header adds a candidate, which can only block, never miss a write. A
    leading ``a/``, ``b/`` or ``-p N`` strip is not applied, because it never
    changes the basename and the unstripped path holds every parent fragment.
    """
    paths: list[str] = []
    for line in data.decode("latin-1").split("\n"):
        line = line.rstrip("\r")
        if line.startswith("diff --git "):
            # the only line naming the file in binary patches, mode changes
            # and pure renames: check the whole remainder and each piece
            rest = line[len("diff --git ") :]
            for piece in [rest, *rest.split()]:
                unquoted = _unquote_c_path(piece.strip())
                paths.append(unquoted if unquoted is not None else piece.strip('"'))
            continue
        for prefix in _PATCH_HEADER_PREFIXES:
            if line.startswith(prefix):
                rest = line[len(prefix) :]
                raw = rest.split("\t", 1)[0].strip()
                if not raw:
                    break
                unquoted = _unquote_c_path(raw)
                if unquoted is None:
                    return None
                paths.append(unquoted)
                # a name may also end at a space (a timestamp after a blank):
                # each piece is a candidate as well, which only widens the match
                paths.extend(piece.strip('"') for piece in rest.split() if piece != raw)
                break
    return paths or None


def _read_patch_paths(path: str, *, base_dir: str | None, mbox: bool) -> list[str] | None:
    """Return the paths the patch file at *path* names, or ``None``.

    ``None`` means unresolvable: the file is not a regular file (a FIFO, a
    directory, ``/dev/stdin``), cannot be read, is over ``_PATCH_READ_LIMIT``,
    names no path, or (with *mbox*) carries a transfer encoding git would
    decode first. The file is opened non-blocking so a FIFO cannot hang the
    hook.
    """
    full = posixpath.join(base_dir, path) if base_dir else path
    try:
        # O_NONBLOCK is POSIX only; Windows has no FIFOs to block on
        fd = os.open(full, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        chunks: list[bytes] = []
        total = 0
        while total <= _PATCH_READ_LIMIT:
            chunk = os.read(fd, min(65536, _PATCH_READ_LIMIT + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
    except OSError:
        return None
    finally:
        os.close(fd)
    if total > _PATCH_READ_LIMIT:
        return None
    data = b"".join(chunks)
    if mbox and _TRANSFER_ENCODING.search(data.decode("latin-1")):
        return None
    return _patch_header_paths(data)


def _is_first_command(tokens: list[str], idx: int) -> bool:
    """Return True when nothing in *tokens* before *idx* could run first.

    The hook reads a patch file before any part of the command runs, so a
    patch written by an earlier command (``printf x > p && git apply p``)
    would be judged on stale content.
    """
    return not any(
        t in _EXACT_COMMAND_END or any(c in t for c in ";&|()<>`$") for t in tokens[:idx]
    )


# Wrappers that run a command after options of their own, some of which change
# the directory (`sudo -D`, `nsenter -w`, `unshare --wd`, `env -C`, `chroot`).
_CWD_WRAPPERS = _COMMAND_PREFIX_WRAPPERS | frozenset(
    {"doas", "nsenter", "unshare", "chroot", "setpriv", "runuser", "su", "ionice", "nohup", "time"}
)
# these change the root or directory with no option at all
_CWD_ALWAYS_MOVING = frozenset({"chroot"})


def _cwd_moved(tokens: list[str], idx: int) -> bool:
    """Return True when a word before *idx* may change the working directory.

    Fails closed: any option given to a prefix wrapper (``sudo -D x``,
    ``nsenter -w x``, ``env -i``) counts, as its own options may move the
    directory. A wrapper's options are read up to its command word;
    ``NAME=value`` assignments are skipped.
    """
    words = [t.strip(";&|()") for t in tokens[:idx]]
    if any(t in {"cd", "pushd", "popd", "-C"} or t.startswith(("--chdir", "-C")) for t in words):
        return True
    for i, word in enumerate(words):
        base = word.rsplit("/", 1)[-1].lower()
        if base not in _CWD_WRAPPERS:
            continue
        if base in _CWD_ALWAYS_MOVING:
            return True
        for nxt in words[i + 1 :]:
            if nxt.startswith("-") and len(nxt) > 1:
                return True
            if not _ASSIGNMENT_RE.match(nxt):
                break
    return False


def _patch_source_targets(
    sources: list[tuple[str, str | None]],
    *,
    read_files: bool,
    cwd_moved: bool,
    mbox: bool,
    root: str | None,
) -> list[str]:
    """Return the protected paths the patch files in *sources* write.

    *sources* holds ``(path, base_dir)`` pairs. When the files cannot be read
    or trusted the targets are unresolvable and ``_ENVRC_EXAMPLE`` stands in
    for them, as in Pattern F, so the caller blocks. *root* is a
    ``--directory`` / ``-d`` prefix: both ``root/path`` and ``path`` are checked.
    """
    if not read_files or not sources:
        return [_ENVRC_EXAMPLE]
    named: list[str] = []
    for src, base_dir in sources:
        if any(c in _DYNAMIC_CHARS for c in src) or (
            base_dir is not None and any(c in _DYNAMIC_CHARS for c in base_dir)
        ):
            return [_ENVRC_EXAMPLE]
        absolute = posixpath.isabs(src) or (base_dir is not None and posixpath.isabs(base_dir))
        if cwd_moved and not absolute:
            return [_ENVRC_EXAMPLE]
        paths = _read_patch_paths(src, base_dir=base_dir, mbox=mbox)
        if paths is None:
            return [_ENVRC_EXAMPLE]
        named.extend(paths)
    hits: list[str] = []
    for path in named:
        for candidate in (
            (path, posixpath.normpath(posixpath.join(root, path))) if root else (path,)
        ):
            if _is_env_persistence_target(candidate):
                hits.append(candidate)
    return hits


# `git apply` and `git am` options that take a value (`-p` and `-C` also glued)
_GIT_PATCH_VALUE_OPTS = (
    "--exclude",
    "--include",
    "--whitespace",
    "--directory",
    "--build-fake-ancestor",
    "--patch-format",
    "--resolvemsg",
    "--quoted-cr",
    "--empty",
)
_GIT_PATCH_SHORT_VALUE = "pC"
# resolved last-one-wins, with their `--no-` forms
_GIT_APPLY_TOGGLES = ("--check", "--stat", "--numstat", "--summary", "--apply", "--unsafe-paths")
_GIT_AM_RESUME = ("--continue", "--resolved", "--skip", "--retry")
_GIT_AM_STOP = ("--abort", "--quit", "--show-current-patch")

# a redirect (`>out`, `2>&1`, `<in`) glued to a word on the `tokenize()` tokens
_GLUED_REDIRECT = re.compile(r"^\d*[<>&]")


def _first_long_match(name: str, names: tuple[str, ...]) -> str | None:
    """Return the entry of *names* that *name* spells, exactly or abbreviated."""
    if name.split("=", 1)[0] in names:
        return name.split("=", 1)[0]
    return next((full for full in names if _long_opt_matches(name, full)), None)


def _split_stdin_sources(
    args: list[str], redirects: list[tuple[str, str]]
) -> tuple[list[str], list[str], bool, bool]:
    """Sort a command's arguments into operands and stdin sources.

    Returns ``(operands, stdin_files, stdin_unresolvable, has_output_redirect)``.
    A ``<`` redirect names a file; ``<<``, ``<<<``, ``<(`` and ``<&`` do not.
    """
    operands: list[str] = []
    stdin_files: list[str] = []
    unresolvable = False
    has_output = False
    for op, target in redirects:
        if "<" in op:
            if op == "<":
                stdin_files.append(target)
            else:
                unresolvable = True
        else:
            has_output = True
    for t in args:
        if _GLUED_REDIRECT.match(t):
            if t.startswith("<"):
                if t.startswith(("<<", "<(", "<&")):
                    unresolvable = True
                else:
                    stdin_files.append(t[1:])
            else:
                has_output = True
        else:
            operands.append(t)
    return operands, stdin_files, unresolvable, has_output


def _has_dotdot(value: str) -> bool:
    """Return True when a ``/`` or ``\\`` separated *value* has a ``..`` segment."""
    return ".." in value.replace("\\", "/").split("/")


def _git_work_tree_root(tokens: list[str], git_idx: int, sub: int) -> tuple[str | None, bool]:
    """Return ``(root, unresolvable)``: where git writes a patch's paths (#1133).

    Fails closed: the root is *unresolvable* unless it is simple. Every ``-C``
    among the options before the subcommand is joined in order (an absolute one
    resets the directory), wherever it stands. The last ``--work-tree`` (else a
    literal ``GIT_WORK_TREE=<dir>`` assigned before ``git``) is then resolved
    against that final directory, and ``.`` segments are folded. Unresolvable:

    - a ``..`` segment in a ``-C``, ``--work-tree`` or ``GIT_WORK_TREE`` value;
    - a value with an expansion, an empty value, or ``GIT_WORK_TREE`` set any way
      but a literal assignment;
    - any other ``GIT_*`` word before ``git``, or ``-c``, ``--config-env`` or
      ``--git-dir``, which may move the work tree, unless a literal
      ``--work-tree`` or ``GIT_WORK_TREE`` names it (the git dir's config is
      not read);
    - a working directory moved before ``git`` (``cd``, ``pushd``, ``env -C``),
      unless an absolute ``--work-tree``, ``GIT_WORK_TREE`` or ``-C`` resets it.
    """
    env_tree: str | None = None
    moved = False
    for t in tokens[:git_idx]:
        if t.startswith("GIT_WORK_TREE="):
            env_tree = t.partition("=")[2]
        elif "GIT_WORK_TREE" in t:
            return None, True
        elif "GIT_" in t:
            moved = True
    cwd = ""
    tree: str | None = None
    opts = tokens[git_idx + 1 : sub]
    i = 0
    while i < len(opts):
        t = opts[i]
        i += 1
        # (option name, value) for the options that matter; else skip like
        # `_git_subcommand_index` does
        name, value = t, None
        if t in _GIT_GLOBAL_OPTS_WITH_VALUE:
            value = opts[i] if i < len(opts) else ""
            i += 1
        elif t.startswith("-C") or t.startswith("-c"):
            name, value = t[:2], t[2:]
        elif t.startswith("--") and "=" in t:
            name, _, value = t.partition("=")
        if name in {"-c", "--config-env", "--git-dir"}:
            moved = True
        elif name in {"-C", "--work-tree"}:
            if not value or any(c in _DYNAMIC_CHARS for c in value) or _has_dotdot(value):
                return None, True
            if name == "-C":
                cwd = posixpath.join(cwd, value)
            else:
                tree = value
    if tree is None and env_tree is not None:
        tree = env_tree
        if not tree or any(c in _DYNAMIC_CHARS for c in tree) or _has_dotdot(tree):
            return None, True
    if tree is None and moved:
        return None, True
    final = posixpath.join(cwd, tree) if tree is not None else cwd
    if _cwd_moved(tokens, git_idx) and (not posixpath.isabs(final) or final.startswith("~")):
        return None, True
    root = posixpath.normpath(final or ".")
    return (None if root == "." else root), False


def _git_patch_targets(
    tokens: list[str],
    git_idx: int,
    *,
    glued_separators: bool = False,
    exact_operators: bool = False,
    read_files: bool = False,
) -> list[str]:
    """Return the protected paths a ``git apply`` / ``git am`` at *git_idx*
    would write (#1105).

    The patch files are read for their header paths (:func:`_patch_header_paths`),
    only when *read_files* is set and the command is the first of the line, at
    a literal path that the command has not moved. Anything the hook cannot
    resolve (stdin, an unreadable or encoded file, ``--unsafe-paths``,
    ``git am --continue``/``--skip``/``--retry``) adds ``_ENVRC_EXAMPLE`` as a
    stand-in target, so the caller blocks it.

    No write: ``--check``/``--stat``/``--numstat``/``--summary`` without
    ``--apply`` (resolved last-one-wins with their ``--no-`` forms), and
    ``git am --abort``/``--quit``/``--show-current-patch``. A
    ``--build-fake-ancestor`` file is written even then.

    Limitation: the file can change between the hook reading it and the
    command running. The hook is a guardrail, not a boundary (ADR-9019).
    """
    sub = _git_subcommand_index(tokens, git_idx)
    if sub is None or tokens[sub] not in {"apply", "am"}:
        return []
    is_am = tokens[sub] == "am"
    args, redirects, after_glued = _scan_command_words(
        tokens, sub + 1, glued_separators=glued_separators, exact_operators=exact_operators
    )
    targets = [
        t
        for t in [target for _, target in redirects] + after_glued
        if _is_env_persistence_target(t, dynamic=True)
    ]
    toggles: dict[str, bool] = {}
    fake_ancestors: list[str] = []
    root: str | None = None
    resume = stop = False
    plain: list[str] = []
    i = 0
    while i < len(args):
        t = args[i]
        i += 1
        if t == "--":
            plain.extend(args[i:])
            break
        if _GLUED_REDIRECT.match(t) or t == "-" or not t.startswith("-"):
            plain.append(t)
        elif t.startswith("--"):
            name = t.partition("=")[0]
            negated = name.startswith("--no-")
            base = "--" + name[len("--no-") :] if negated else name
            has_value = "=" in t
            if is_am and (full := _first_long_match(base, _GIT_AM_RESUME)):
                resume = resume or not negated
            elif is_am and _first_long_match(base, _GIT_AM_STOP):
                stop = stop or not negated
            elif full := _first_long_match(base, _GIT_APPLY_TOGGLES):
                toggles[full] = not negated
            elif not negated and (full := _first_long_match(base, _GIT_PATCH_VALUE_OPTS)):
                value = t.partition("=")[2] if has_value else (args[i] if i < len(args) else "")
                i += 0 if has_value else 1
                if full == "--directory":
                    if _has_dotdot(value):
                        return [*targets, _ENVRC_EXAMPLE]
                    root = value
                elif full == "--build-fake-ancestor":
                    fake_ancestors.append(value)
        else:
            if is_am and t == "-r":
                resume = True
            for pos, ch in enumerate(t[1:], start=1):
                if ch in _GIT_PATCH_SHORT_VALUE:
                    i += 1 if pos == len(t) - 1 else 0
                    break
    targets.extend(v for v in fake_ancestors if _is_env_persistence_target(v, dynamic=True))
    if is_am:
        if resume:
            return [*targets, _ENVRC_EXAMPLE]
        if stop:
            return targets
    elif any(toggles.get(k, False) for k in _GIT_APPLY_TOGGLES[:4]) and not toggles.get(
        "--apply", False
    ):
        return targets
    if toggles.get("--unsafe-paths", False):
        return [*targets, _ENVRC_EXAMPLE]
    operands, stdin_files, unresolvable, has_output = _split_stdin_sources(plain, redirects)
    if has_output:
        # an fd number (`2` of `2>`) is no patch file
        operands = [t for t in operands if not t.isdigit()]
    needs_stdin = not [t for t in operands if t != "-"] or "-" in operands
    operands = [t for t in operands if t != "-"]
    if unresolvable or (needs_stdin and not stdin_files):
        return [*targets, _ENVRC_EXAMPLE]
    opts = tokens[git_idx + 1 : sub]
    cwd_moved = _cwd_moved(tokens, git_idx) or any(t.startswith("-C") for t in opts)
    tree, tree_unresolvable = _git_work_tree_root(tokens, git_idx, sub)
    if tree_unresolvable:
        return [*targets, _ENVRC_EXAMPLE]
    if tree is not None:
        root = posixpath.join(tree, root) if root else tree
    if root:
        root = posixpath.normpath(root)
        if root == ".":
            root = None
    return targets + _patch_source_targets(
        [(src, None) for src in operands + stdin_files],
        read_files=read_files and _is_first_command(tokens, git_idx),
        cwd_moved=cwd_moved,
        mbox=is_am,
        root=root,
    )


# GNU `patch` options that take a value, as short characters and long names
_PATCH_SHORT_VALUE = "pFiorDBYzVgd"
_PATCH_LONG_VALUE = (
    "--strip",
    "--fuzz",
    "--input",
    "--output",
    "--reject-file",
    "--ifdef",
    "--prefix",
    "--basename-prefix",
    "--suffix",
    "--version-control",
    "--get",
    "--directory",
    "--quoting-style",
    "--reject-format",
    "--read-only",
)
_PATCH_LONG_FLAGS = ("--dry-run", "--help", "--version")
# options that rename the backup files: a header name can become any name
_PATCH_BACKUP_NAMING = {"B", "Y", "z", "--prefix", "--basename-prefix", "--suffix"}
# environment variables that rename the backup files the same way
_PATCH_BACKUP_ENV = ("SIMPLE_BACKUP_SUFFIX", "VERSION_CONTROL", "PATCH_VERSION_CONTROL")


def _patch_command_targets(
    tokens: list[str],
    patch_idx: int,
    *,
    glued_separators: bool = False,
    exact_operators: bool = False,
    read_files: bool = False,
) -> list[str]:
    """Return the protected paths a ``patch`` at *patch_idx* would write (#1105).

    Checked against GNU patch 2.8. ORIGFILE takes every hunk, so when it is
    given it is the only target and the patch file is not read. ``-o FILE``
    replaces the original as the write, and stays a write under ``--dry-run``;
    ``-r FILE`` is a target as well. Without ORIGFILE or ``-o`` the targets
    are the header paths of the patch file (:func:`_read_patch_paths`), under
    the same conditions as :func:`_git_patch_targets`. Backup naming options
    (``-B``, ``-Y``, ``-z``) and a patch read from stdin are unresolvable and
    add ``_ENVRC_EXAMPLE`` as a stand-in.
    """
    args, redirects, after_glued = _scan_command_words(
        tokens, patch_idx + 1, glued_separators=glued_separators, exact_operators=exact_operators
    )
    targets = [
        t
        for t in [target for _, target in redirects] + after_glued
        if _is_env_persistence_target(t, dynamic=True)
    ]
    plain: list[str] = []
    values: dict[str, list[str]] = {}
    flags: set[str] = set()

    def note(key: str, value: str) -> None:
        values.setdefault(key, []).append(value)

    i = 0
    while i < len(args):
        t = args[i]
        i += 1
        if t == "--":
            plain.extend(args[i:])
            break
        if _GLUED_REDIRECT.match(t) or t == "-" or not t.startswith("-"):
            plain.append(t)
        elif t.startswith("--"):
            full = _first_long_match(t.partition("=")[0], _PATCH_LONG_VALUE + _PATCH_LONG_FLAGS)
            if full in _PATCH_LONG_FLAGS:
                flags.add(full)
            elif full is not None:
                if "=" in t:
                    note(full, t.partition("=")[2])
                else:
                    note(full, args[i] if i < len(args) else "")
                    i += 1
        elif t == "-v":
            flags.add("--version")
        else:
            for pos, ch in enumerate(t[1:], start=1):
                if ch in _PATCH_SHORT_VALUE:
                    if pos < len(t) - 1:
                        note(ch, t[pos + 1 :])
                    else:
                        note(ch, args[i] if i < len(args) else "")
                        i += 1
                    break
    short_long = {"i": "--input", "o": "--output", "r": "--reject-file", "d": "--directory"}
    merged: dict[str, list[str]] = {}
    for key, vals in values.items():
        merged.setdefault(short_long.get(key, key), []).extend(vals)
    targets.extend(
        v for v in merged.get("--reject-file", []) if _is_env_persistence_target(v, dynamic=True)
    )
    if "--help" in flags or "--version" in flags:
        return targets
    if "--output" in merged:
        targets.extend(
            v
            for v in merged["--output"]
            if v != "-" and _is_env_persistence_target(v, dynamic=True)
        )
        return targets
    if "--dry-run" in flags:
        return targets
    if (
        _PATCH_BACKUP_NAMING & set(values)
        or any(name in t for t in tokens for name in _PATCH_BACKUP_ENV)
        or any(os.environ.get(name) for name in _PATCH_BACKUP_ENV)
    ):
        # set on this command line or inherited from the hook's environment
        return [*targets, _ENVRC_EXAMPLE]
    operands, stdin_files, unresolvable, has_output = _split_stdin_sources(plain, redirects)
    if has_output:
        operands = [t for t in operands if not t.isdigit()]
    if operands and operands[0] != "-":
        if _is_env_persistence_target(operands[0], dynamic=True):
            targets.append(operands[0])
        return targets
    directory = merged.get("--directory", [None])[-1]
    sources: list[tuple[str, str | None]] = [(f, None) for f in stdin_files]
    inputs = merged.get("--input", [])
    if len(operands) > 1:
        inputs = [*inputs, operands[1]]
    sources += [(f, directory) for f in inputs if f != "-"]
    needs_stdin = not inputs or "-" in inputs
    if unresolvable or (needs_stdin and not stdin_files):
        return [*targets, _ENVRC_EXAMPLE]
    return targets + _patch_source_targets(
        sources,
        read_files=read_files and _is_first_command(tokens, patch_idx),
        cwd_moved=_cwd_moved(tokens, patch_idx),
        mbox=False,
        root=directory,
    )


def _bash_confirmed_write_targets(
    tokens: list[str],
    *,
    glued_separators: bool = False,
    exact_operators: bool = False,
    restore_scan: bool = True,
    read_patch_files: bool = False,
    literal_redirects: bool = False,
    glued_ends_write_command: bool = False,
) -> list[str]:
    """Return every persistence-protected path/basename targeted by a
    *confirmed* Bash write.

    Detected patterns:
    - A:  ``>`` / ``>>`` standalone token followed by a persistence target
    - B:  ``>foo`` / ``>>foo`` no-space form where ``foo`` is a persistence target
    - C:  ``tee`` / ``cp`` / ``mv`` / ``dd`` with a persistence target as a
          positional argument before the next command separator
    - D:  ``sed -i`` (in-place edit) with a persistence target as a positional
    - F:  ``git checkout`` / ``git restore`` of a persistence target (#1055)
    - G:  ``git apply`` / ``git am``: the paths the patch file names (#1105)
    - H:  ``patch``: its file operand, ``-o`` / ``-r`` values, or the paths the
          patch file names (#1105)

    *read_patch_files* lets G and H open the patch file; by default they treat
    it as unresolvable and add ``_ENVRC_EXAMPLE`` as a stand-in target.

    Split from the script-interpreter heuristic (:func:`_bash_interpreter_mentions_target`,
    formerly pattern E of this function) so :func:`check_env_persistence_in_bash`
    can block one of these outright for ``ENV_PERSISTENCE_TARGETS`` while still
    requiring the literal var name for ``_AI_CLI_SETTINGS_TARGETS`` (#1037,
    decision b) -- the interpreter heuristic only *might* write and keeps the
    var-name requirement for every target, confirmed or not.
    """
    targets: list[str] = []
    tokens = _collapse_extglobs(tokens)
    words = _normalise_command_words(tokens)
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

        # The patterns below key on a command word; operands stay in *tokens*.
        tok = words[i]

        # Pattern C: write command followed by persistence target as positional
        if tok in _WRITE_COMMANDS:
            positionals: list[str] = []
            seg_open = True
            # The command's own operands. With *glued_ends_write_command* a
            # token that ends in `;`, `&&` or `||` is the last one, and only
            # the part before the operator counts (#1131). A token with text
            # after the operator (`b;cp`) keeps the old, wider scan.
            write_words: list[str] = []
            for j in range(i + 1, n):
                t = tokens[j]
                if t in _COMMAND_SEPARATORS:
                    break
                glued_end = (
                    _GLUED_END_OF_WORD.search(t)
                    if glued_ends_write_command and glued_separators
                    else None
                )
                if glued_end:
                    if glued_end.start():
                        write_words.append(t[: glued_end.start()])
                    break
                write_words.append(t)
            for t in write_words:
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
        if tok == "git" and restore_scan:
            targets.extend(
                _git_restore_targets(
                    tokens,
                    i,
                    glued_separators=glued_separators,
                    exact_operators=exact_operators,
                    literal_redirects=literal_redirects,
                )
            )

        # Pattern G: `git apply` / `git am` write the paths the patch names
        if tok == "git":
            targets.extend(
                _git_patch_targets(
                    tokens,
                    i,
                    glued_separators=glued_separators,
                    exact_operators=exact_operators,
                    read_files=read_patch_files,
                )
            )

        # Pattern H: `patch` writes its file operand, `-o` / `-r` or the
        # paths its patch names, wherever the word sits (ADR-9019, rule 1)
        if tok == "patch":
            targets.extend(
                _patch_command_targets(
                    tokens,
                    i,
                    glued_separators=glued_separators,
                    exact_operators=exact_operators,
                    read_files=read_patch_files,
                )
            )

    return targets


def _newlines_as_separators(text: str) -> str:
    """Return *text* with each unquoted newline written as `` ; ``.

    :func:`tokenize`, :func:`_redirect_tokens` and :func:`_exact_operator_tokens`
    read a newline as whitespace, so a write command's operand scan ran on into
    the next line (#1131). A newline inside ``'...'``, ``"..."``, a backslash
    escape, ``$(...)``, a backtick substitution or ``<(...)`` is not a separator
    and is kept; so is a backslash-newline continuation. Leading and trailing
    newlines are dropped. When *text* holds a here-document, a comment or a
    construct that cannot be read, it is returned unchanged, which keeps the
    old scan.
    """
    body = text.strip("\n")
    if "\n" not in body:
        return body
    out: list[str] = []
    i = 0
    n = len(body)
    try:
        while i < n:
            char = body[i]
            if char == "\n":
                out.append(" ; ")
                i += 1
                continue
            if char == "\\":
                if body.startswith("\n", i + 1):
                    return text
                end = i + 2
            elif char == "'":
                end = _skip_single(body, i + 1)
            elif char == '"':
                end = _skip_double(body, i + 1)
            elif char == "$":
                end = _skip_dollar(body, i, ansi=True)
            elif char == "`":
                end = _skip_backtick(body, i + 1)
            elif char in "<>" and body.startswith("(", i + 1):
                end = _skip_paren(body, i + 2)
            elif char == "<" and body.startswith("<<<", i):
                end = i + 3
            elif char == "<" and body.startswith("<", i + 1):
                return text  # a here-document
            elif char == "#" and (i == 0 or body[i - 1].isspace() or body[i - 1] in "&|;()<>"):
                return text  # a comment
            else:
                end = i + 1
            if end > n:
                return text
            out.append(body[i:end])
            i = end
    except (_OpenConstructError, RecursionError):
        return text
    return "".join(out)


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


def check_env_persistence_in_bash(
    tokens: list[str],
    _depth: int = 0,
    *,
    glued_separators: bool = False,
    exact_operators: bool = False,
    restore_scan: bool = True,
    read_patch_files: bool = False,
    literal_redirects: bool = False,
    glued_ends_write_command: bool = False,
) -> tuple[bool, str]:
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

    for target in _bash_confirmed_write_targets(
        tokens,
        glued_separators=glued_separators,
        exact_operators=exact_operators,
        restore_scan=restore_scan,
        read_patch_files=read_patch_files,
        literal_redirects=literal_redirects,
        glued_ends_write_command=glued_ends_write_command,
    ):
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
    tokens = _normalise_command_words(_structural_tokens(command))
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


# Reserved words after which a command begins: ``if printenv; then ...``,
# ``! printenv``, ``{ printenv; }``, ``time printenv``.
_COMMAND_KEYWORDS = frozenset(
    {"!", "{", "if", "then", "do", "else", "elif", "while", "until", "time"}
)


def _command_start_indices(tokens: list[str]) -> list[int]:
    """Return the indices at which a command begins.

    A command starts at position 0, after any shell separator, and after a
    reserved word (:data:`_COMMAND_KEYWORDS`) that itself sits at a start, so
    ``then printenv`` counts while ``echo then printenv`` does not. Anchoring
    on these is what separates *running* a command from merely *mentioning*
    it: a heredoc body tokenizes exactly like an argument list, so a scan over
    all positions treats documentation and test fixtures as invocations. Both
    checks below hit that while this repository's own tests were being written.
    """
    start_set = {0}
    for index, token in enumerate(tokens):
        if token in _SHELL_OPERATORS and index + 1 < len(tokens):
            start_set.add(index + 1)
    for index, word in enumerate(tokens):
        if index in start_set and word in _COMMAND_KEYWORDS and index + 1 < len(tokens):
            start_set.add(index + 1)
            if word == "time" and tokens[index + 1] == "-p" and index + 2 < len(tokens):
                start_set.add(index + 2)
    return sorted(start_set)


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
    words = _normalise_command_words(tokens)
    for index in _command_start_indices(tokens):
        if index >= len(tokens) or words[index] not in _ENV_DUMP_COMMANDS:
            continue
        token = words[index]
        # Stop at the next separator: later tokens belong to another command.
        rest = []
        for candidate in tokens[index + 1 :]:
            if candidate in _SHELL_OPERATORS:
                break
            rest.append(candidate)

        # nosec B105  # bandit's hardcoded-password heuristic fires on this
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
    words = _normalise_command_words(tokens)
    for index in _command_start_indices(tokens):
        if index >= len(tokens) or words[index] not in _CREDENTIAL_READER_COMMANDS:
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


def check_command(command: str, _depth: int = 0, _expanded: bool = False) -> tuple[bool, str]:
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
    raw_tokens = tokenize(command)
    tokens = _normalise_command_words(raw_tokens)

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
        (check_env_dump, raw_tokens),
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
    command_structural = _normalise_command_words(_structural_tokens(command))
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
    # Only the `tokenize()` tokens keep a `;` glued to a word; on the redirect
    # tokens such a word was quoted and is a literal argument (#1093).
    # A third pass runs on the exact operator tokens, where `&`, `|&`, `(` and
    # `)` also end a checkout/restore argument scan. The scan runs on every
    # pass, so the exact pass only adds coverage (#1117).
    # An unquoted newline ends a command, but the tokens drop it: write it as
    # `;` first so a write command's operands end at the line (#1131).
    lined = _newlines_as_separators(stripped)
    exact_tokens = _exact_operator_tokens(lined)
    # A patch file is read only for the top-level command, and not when the
    # command has several lines: the tokens lose a newline, so an earlier line
    # could have written the file (#1105).
    read_patch_files = _depth == 0 and "\n" not in stripped.strip()
    # The redirect tokens lost the quoting of a word like `'>'`, so when the
    # command holds one, the scans read redirect-looking tokens as operands
    # instead of operators that swallow the next word (#1134).
    literal_redirects = _has_quoted_redirect_word(stripped)
    passes: list[tuple[list[str], bool, bool, bool]] = [
        (
            tokenize(_newlines_as_separators(command)),
            True,
            False,
            exact_tokens is not None,
        ),
        (_redirect_tokens(lined), False, False, False),
    ]
    if exact_tokens is not None:
        passes.append((exact_tokens, False, True, False))
    for check_tokens, glued, exact, glued_ends in passes:
        is_dangerous, reason = check_env_persistence_in_bash(
            check_tokens,
            _depth,
            glued_separators=glued,
            exact_operators=exact,
            restore_scan=True,
            read_patch_files=read_patch_files,
            literal_redirects=literal_redirects,
            glued_ends_write_command=glued_ends,
        )
        if is_dangerous:
            return True, reason

    # Recurse into shell-wrapper payloads (bash/sh/zsh/dash -c <payload>, eval ...)
    # Depth cap of 3 prevents infinite loops on adversarial inputs.
    if _depth < 3:
        for payload in _wrapped_payloads(tokens) + _heredoc_payloads(command):
            is_dangerous, reason = check_command(payload, _depth + 1)
            if is_dangerous:
                return True, reason

    # Substitution bodies, nested ones included, are collected in one pass and
    # each is checked at one level down, so nesting does not use the wrapper
    # depth budget above. A checked body does not collect its own again.
    if not _expanded:
        try:
            substitutions = _all_substitution_payloads(command)
        except RecursionError:
            substitutions = None
        if substitutions is None:
            return True, "Command substitutions are nested too deeply to scan"
        for payload in substitutions:
            is_dangerous, reason = check_command(payload, _depth + 1, _expanded=True)
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
