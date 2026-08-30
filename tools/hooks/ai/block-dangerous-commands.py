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
        "AI can help prepare (update changelog, verify CI) but not execute releases."
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
# routes, so this is a guardrail rather than a boundary.
CREDENTIAL_FILE_BASENAMES: dict[str, str] = {
    ".pypirc": "",
    ".netrc": "",
    "credentials": ".aws",
    "hosts.yml": "gh",
    "config.json": ".docker",
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
    ".env": "",
    ".env.local": "",
    ".env.development": "",
    ".env.production": "",
    "copilot-hooks.json": "",
}

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


def _is_env_persistence_target(path_str: str) -> bool:
    """Return True when *path_str* points to a file that the AI must not use
    to persist the ``ALLOW_AI_READY_TO_MERGE`` env var.

    Checks:
    - Basename + optional parent-path fragment (ENV_PERSISTENCE_TARGETS)
    - AI CLI settings files only when the immediate parent dir is in the
      corresponding allow-list (_AI_CLI_SETTINGS_TARGETS)
    """
    if not path_str:
        return False

    try:
        # Expand ~ so ~/.bashrc comparisons work
        path = Path(path_str).expanduser()
    except (ValueError, RuntimeError):
        return False

    basename = path.name
    parent = path.parent

    # Check plain persistence targets
    if basename in ENV_PERSISTENCE_TARGETS:
        fragment = ENV_PERSISTENCE_TARGETS[basename]
        if not fragment:
            return True
        # Fragment must appear in the parent path string
        parent_posix = parent.as_posix()
        if fragment in parent_posix:
            return True

    # Check AI CLI settings files
    if basename in _AI_CLI_SETTINGS_TARGETS:
        allowed_parents = _AI_CLI_SETTINGS_TARGETS[basename]
        if parent.name in allowed_parents:
            return True

    return False


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

# `<<EOF`, `<<-EOF`, `<<'EOF'`, `<<"EOF"`.
_HEREDOC_START = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


def _reads_stdin_as_code(words: list[str]) -> bool:
    """Whether the command in *words* will execute a heredoc body as a program.

    `bash <<EOF` and `sh -s <<EOF` run their body as shell; `bash script.sh
    <<EOF` and `cat >> notes.md <<EOF` feed it to something as input. The
    difference is whether a script argument appears before the heredoc operator.
    """
    if not words:
        return False
    if words[0].rsplit("/", 1)[-1].lower() not in _STDIN_INTERPRETERS:
        return False
    for word in words[1:]:
        if word.startswith("<<"):
            break
        if word == "-":
            return True  # explicit "read the program from stdin"
        if word.startswith("-"):
            continue  # some other flag; keep looking
        return False  # a script path: the heredoc is that script's input
    return True  # bare `bash <<EOF` reads the program from stdin


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
    payloads: list[str] = []
    lines = command.splitlines()
    index = 0
    while index < len(lines):
        match = _HEREDOC_START.search(lines[index])
        if not match:
            index += 1
            continue

        delimiter = match.group(2)
        # The command owning this heredoc is the last segment before it.
        words = re.split(r"[;&|]", lines[index][: match.start()])[-1].split()

        body: list[str] = []
        cursor = index + 1
        while cursor < len(lines) and lines[cursor].strip() != delimiter:
            body.append(lines[cursor])
            cursor += 1

        if _reads_stdin_as_code(words):
            payloads += [line for line in body if line.strip()]
        index = cursor + 1
    return payloads


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

# Shell commands that write to a file argument
_WRITE_COMMANDS = {"tee", "cp", "mv", "dd"}

# Script interpreters that can write files via -c/-e/--command
_INTERPRETER_COMMANDS = {"python", "python3", "perl", "ruby", "node"}

# Subshell separators used to bound a single command segment
_COMMAND_SEPARATORS = {"&&", "||", ";", "|"}


def _bash_writes_to_persistence_target(tokens: list[str]) -> bool:
    """Return True if the token stream contains a write operation targeting a
    persistence-protected file.

    Detected patterns:
    - A:  ``>`` / ``>>`` standalone token followed by a persistence target
    - B:  ``>foo`` / ``>>foo`` no-space form where ``foo`` is a persistence target
    - C:  ``tee`` / ``cp`` / ``mv`` / ``dd`` with a persistence target as a
          positional argument before the next command separator
    - D:  ``sed -i`` (in-place edit) with a persistence target as a positional
    - E:  script interpreter (``python``/``python3``/``perl``/``ruby``/``node``)
          invoked with ``-c`` / ``-e`` / ``--command`` whose script body mentions
          any persistence-target basename
    """
    n = len(tokens)
    for i, tok in enumerate(tokens):
        # Pattern A: standalone redirect operator
        if tok in _WRITE_REDIRECTS:
            if i + 1 < n and _is_env_persistence_target(tokens[i + 1]):
                return True
            continue

        # Pattern B: redirect operator concatenated with target (no whitespace)
        if tok.startswith(">>") and len(tok) > 2:
            if _is_env_persistence_target(tok[2:]):
                return True
            continue
        if tok.startswith(">") and len(tok) > 1 and tok[1] not in {"=", ">"}:
            # Skip ">=" (comparison) and ">>" (already handled)
            if _is_env_persistence_target(tok[1:]):
                return True
            continue

        # Pattern C: write command followed by persistence target as positional
        if tok in _WRITE_COMMANDS:
            for j in range(i + 1, n):
                t = tokens[j]
                if t in _COMMAND_SEPARATORS:
                    break
                if t.startswith("-"):
                    continue
                if _is_env_persistence_target(t):
                    return True
            continue

        # Pattern D: sed -i (in-place) with persistence target
        if tok == "sed":
            has_in_place = False
            for j in range(i + 1, n):
                t = tokens[j]
                if t in _COMMAND_SEPARATORS:
                    break
                if t.startswith("-i"):
                    has_in_place = True
                    continue
                if not has_in_place:
                    continue
                if t.startswith("-"):
                    continue
                if _is_env_persistence_target(t):
                    return True
            continue

        # Pattern E: script interpreter with -c/-e/--command and target in body
        if tok in _INTERPRETER_COMMANDS:
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
            continue

    return False


def check_env_persistence_in_bash(tokens: list[str]) -> tuple[bool, str]:
    """Block Bash commands that would persist ALLOW_AI_READY_TO_MERGE to a
    protected file.

    Two conditions must both hold:
    - The literal string ``ALLOW_AI_READY_TO_MERGE`` appears in any token, AND
    - The command performs a write operation targeting a persistence-protected
      file (see :func:`_bash_writes_to_persistence_target` for patterns).

    Plain mention of the var name (e.g., in a commit message, a doc string, or
    `git add` arguments that reference protected file paths) is NOT a write
    operation and is allowed.
    """
    var_name = ALLOW_AI_READY_TO_MERGE_VAR
    if not any(var_name in t for t in tokens):
        return False, ""
    if not _bash_writes_to_persistence_target(tokens):
        return False, ""
    return True, (
        f"Blocked: AI must not persist {var_name} to shell or project config files. "
        f"Only a human can set this variable in their environment."
    )


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


def _apply_patch_edits(command: str) -> list[tuple[str, str]]:
    """Return ``(target_path, added_content)`` for each file in a patch.

    Added content is every ``+``-prefixed line under that target, joined -- the
    lines the patch would introduce. Context and removed lines are ignored
    because only new content can persist a value.
    """
    edits: list[tuple[str, str]] = []
    matches = list(_APPLY_PATCH_TARGET_RE.finditer(command))
    for index, match in enumerate(matches):
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(command)
        added = [
            line[1:]
            for line in command[body_start:body_end].splitlines()
            # ``+++`` is a diff header, not added content.
            if line.startswith("+") and not line.startswith("+++")
        ]
        edits.append((match.group(1).strip(), "\n".join(added)))
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


def check_env_persistence_in_file_edit(
    tool_name: str, tool_input: dict[str, object]
) -> tuple[bool, str]:
    """Block file-edit operations (Edit/Write/MultiEdit for Claude/Codex,
    write_file/replace for Gemini, write_to_file for Antigravity) that would
    persist ALLOW_AI_READY_TO_MERGE to a protected file.

    Triggers when:
    - The target file_path is a persistence-protected target, AND
    - The new content being written contains ALLOW_AI_READY_TO_MERGE.
    """
    var_name = ALLOW_AI_READY_TO_MERGE_VAR

    file_path_raw = str(tool_input.get("file_path", "") or "")
    if not file_path_raw:
        return False, ""

    if not _is_env_persistence_target(file_path_raw):
        return False, ""

    # Collect all new content being written
    new_content_parts: list[str] = []

    tool_lower = tool_name.lower()

    if tool_lower in ("write", "write_file", "write_to_file", "apply_patch"):
        # Write/write_file (Claude/Gemini) and write_to_file (agy, normalized in
        # _parse_input): full file content lives in the 'content' key.
        # apply_patch (Codex) is normalised into the same shape by
        # check_env_persistence_in_apply_patch, one entry per patch target.
        content = str(tool_input.get("content", "") or "")
        new_content_parts.append(content)

    elif tool_lower in ("edit", "replace"):
        # Edit (Claude/Codex) and replace (Gemini): new_string key
        new_content_parts.append(str(tool_input.get("new_string", "") or ""))

    elif tool_lower == "multiedit":
        # MultiEdit: edits is a list of {old_string, new_string} dicts
        edits = tool_input.get("edits", [])
        if isinstance(edits, list):
            for edit_item in edits:
                if isinstance(edit_item, dict):
                    new_content_parts.append(str(edit_item.get("new_string", "") or ""))

    # Check if any new content contains the env var name
    combined = "\n".join(new_content_parts)
    if var_name in combined:
        return True, (
            f"Blocked: AI must not persist {var_name} to '{file_path_raw}'. "
            f"Only a human can set this variable in their environment."
        )

    return False, ""


def check_merge_to_protected(tokens: list[str]) -> tuple[bool, str]:
    """
    Check if command is a merge that would create a merge commit on a protected branch.

    Protected branches often require linear history (no merge commits).
    Blocks `git merge` on protected branches unless --ff-only is specified.
    """
    tokens_lower = [t.lower() for t in tokens]

    # Must be a git merge command
    if "git" not in tokens_lower or "merge" not in tokens_lower:
        return False, ""

    # Allow if --ff-only is specified (fast-forward only, no merge commit)
    if "--ff-only" in tokens_lower:
        return False, ""

    # Check if we're on a protected branch
    current_branch = get_current_branch()
    if current_branch and current_branch.lower() in PROTECTED_BRANCHES:
        return True, (
            f"Merge on protected branch '{current_branch}' would create merge commit. "
            f"Use --ff-only for fast-forward merge, or merge via PR"
        )

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
    required_parent = CREDENTIAL_FILE_BASENAMES.get(path.name)
    if required_parent is None:
        return False
    return not required_parent or required_parent in path.parent.as_posix()


def check_credential_file_read(tokens: list[str]) -> tuple[bool, str]:
    """Block a reader command pointed at a known credential store.

    Anchored on the reading command rather than scanning every token. A bare
    scan flagged any command whose text merely *contained* a credential path --
    writing this project's own test data tripped it immediately -- because
    heredoc bodies and file contents tokenize like arguments. Requiring a
    reader in command position keeps `cat ~/.netrc` blocked while leaving
    prose, test fixtures and documentation alone.
    """
    for index in _command_start_indices(tokens):
        if index >= len(tokens) or tokens[index] not in _CREDENTIAL_READER_COMMANDS:
            continue
        for argument in tokens[index + 1 :]:
            # Stop at a shell operator: later tokens belong to another command,
            # which gets its own turn through this loop.
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

    # Check for environment dumps and credential-store reads
    is_dangerous, reason = check_env_dump(tokens)
    if is_dangerous:
        return True, reason

    is_dangerous, reason = check_credential_file_read(tokens)
    if is_dangerous:
        return True, reason

    # Check for push to protected branches (regular or force)
    is_dangerous, reason = check_push_to_protected(tokens)
    if is_dangerous:
        return True, reason

    # Check for deletion of protected branches
    is_dangerous, reason = check_delete_protected_branch(tokens)
    if is_dangerous:
        return True, reason

    # Check for merge commits on protected branches
    is_dangerous, reason = check_merge_to_protected(tokens)
    if is_dangerous:
        return True, reason

    # Check for blocked workflow commands
    is_dangerous, reason = check_blocked_workflow_commands(tokens)
    if is_dangerous:
        return True, reason

    # Check for governance labels
    is_dangerous, reason = check_governance_labels(tokens)
    if is_dangerous:
        return True, reason

    # Check for attempts to persist ALLOW_AI_READY_TO_MERGE via Bash
    is_dangerous, reason = check_env_persistence_in_bash(tokens)
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


def _parse_input(input_data: dict) -> tuple[str, str, dict]:
    """
    Parse tool name, command, and tool_input from hook input.

    Handles three input formats:
    - Claude/Gemini: {"tool_name": "Bash", "tool_input": {"command": "..."}}
    - Copilot CLI:   {"toolName": "bash", "toolArgs": "{\"command\":\"...\"}"}
    - Antigravity:   {"toolCall": {"name": "run_command",
                      "args": {"CommandLine": "..."}}}

    Returns:
        (tool_name, command, tool_input) tuple where tool_input is the full
        parameter dict (used for file-edit operations). For Antigravity the
        PascalCase args are normalized to the canonical command/file_path/content
        keys the downstream checks expect.
    """
    # Antigravity CLI (agy) format: a nested toolCall with PascalCase args
    # (protojson camelCase envelope). run_command -> args.CommandLine;
    # write_to_file -> args.TargetFile / args.CodeContent.
    if "toolCall" in input_data:
        tool_call = input_data.get("toolCall") or {}
        tool_name = tool_call.get("name", "")
        args = tool_call.get("args") or {}
        if not isinstance(args, dict):
            args = {}
        tool_input = {
            **args,
            "command": args.get("CommandLine", "") or "",
            "file_path": args.get("TargetFile", "") or "",
            "content": args.get("CodeContent", "") or "",
        }
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
        except json.JSONDecodeError:
            tool_input = {}
        return tool_name, tool_input.get("command", ""), tool_input

    # Claude/Gemini format uses snake_case keys
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    if not isinstance(tool_input, dict):
        tool_input = {}
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
# tool names. This template no longer ships a Gemini integration, but the names
# are kept on purpose: a downstream project with enterprise Gemini access can
# still point that CLI at this hook, and matching an extra name costs nothing
# while failing to match one would silently remove protection.
_BASH_TOOL_NAMES = frozenset({"Bash", "run_shell_command", "bash", "run_command"})

# File-edit tool names across all supported AI CLIs
# Claude/Codex: Edit, Write, MultiEdit
# Gemini: write_file, replace
# Antigravity (agy): write_to_file
# Codex: apply_patch. Handled on its own path -- see the parser above -- because
# its payload is command-shaped rather than file_path/content.
_APPLY_PATCH_TOOL_NAME = "apply_patch"

_FILE_EDIT_TOOL_NAMES = frozenset(
    {"Edit", "Write", "MultiEdit", "write_file", "replace", "write_to_file"}
)


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

    _log(
        {
            "raw_input": input_data,
            "tool_name": tool_name,
            "command": command,
            "format": fmt,
        }
    )

    # --- Bash / shell command path ---
    if tool_name in _BASH_TOOL_NAMES:
        if not command:
            return 0
        is_dangerous, reason = check_command(command)
        if is_dangerous:
            return _block_response(fmt, redirect_reason(command, reason), command)
        return 0

    # --- Codex apply_patch path ---
    #
    # Checked as *both* a command and a file edit: the envelope is a shell
    # command (so the dangerous-flag scanning applies to it) and the patch body
    # writes files (so the env-persistence check must see its targets).
    if tool_name == _APPLY_PATCH_TOOL_NAME:
        if command:
            is_dangerous, reason = check_command(command)
            if is_dangerous:
                return _block_response(fmt, reason, command)
            is_dangerous, reason = check_env_persistence_in_apply_patch(command)
            if is_dangerous:
                return _block_response(fmt, reason, f"{tool_name} {command[:60]}")
        return 0

    # --- File-edit tool path (Edit/Write/MultiEdit/write_file/replace) ---
    if tool_name in _FILE_EDIT_TOOL_NAMES:
        is_dangerous, reason = check_env_persistence_in_file_edit(tool_name, tool_input)
        if is_dangerous:
            file_path = str(tool_input.get("file_path", ""))
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
