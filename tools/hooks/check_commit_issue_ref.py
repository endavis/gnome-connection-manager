#!/usr/bin/env python3
"""Fail a commit whose issue references disagree with its branch (#741).

The workflow is Issue → Branch → Commit → PR → Merge, and the repo enforces the
parts it can: `no-commit-to-main` blocks commits on `main`, and the branch-naming
hook blocks malformed branch names. Nothing checked that a commit lands on the
branch for *its own* issue.

That gap was hit during the template review backlog: work for #695 was committed
onto `feat/694-download-integrity-verification`, the branch left over from the
previous issue. Every existing control passed — the branch was not `main`, its
name was well-formed, and the code itself was fine. Only its location was wrong.

The rule
--------
If the message references any issue, the branch's issue must be among them.

A message that references no issue at all passes: plenty of legitimate commits
do not cite one, and requiring it would be a different and more intrusive policy
than this hook is for.

Usage:
    check_commit_issue_ref.py <path-to-commit-msg-file>
"""

from __future__ import annotations

import os
import re
import subprocess  # nosec B404 - reads the current branch name
import sys
from pathlib import Path

# `<type>/<issue>-<slug>` — the convention the branch-naming hook already
# enforces. Branches without an issue number (main, develop, release/*,
# hotfix/*) yield None and are skipped.
BRANCH_ISSUE = re.compile(r"^[a-z]+/(\d+)-")

# `#123`, but not `#123` inside a word (`abc#123`) and not a colour like
# `#1234ab` followed by more hex.
MESSAGE_ISSUE = re.compile(r"(?<![\w#])#(\d+)\b")

# Messages git generates or that target an existing commit, where the issue
# reference belongs to something other than the work being committed now.
SKIP_PREFIXES = ("merge ", "revert ", "fixup!", "squash!", "amend!")

OVERRIDE_ENV = "ALLOW_ISSUE_REF_MISMATCH"


def current_branch() -> str:
    """Return the checked-out branch name, or "" when detached or unavailable."""
    try:
        result = subprocess.run(  # nosec B603 B607 - fixed argv, no shell
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - defensive
        return ""
    return result.stdout.strip()


def branch_issue(branch: str) -> int | None:
    """Return the issue number encoded in *branch*, or None if it has none."""
    match = BRANCH_ISSUE.match(branch)
    return int(match.group(1)) if match else None


def strip_comments(message: str) -> str:
    """Drop git's comment lines and everything below a scissors line.

    Without this, the template git puts in `COMMIT_EDITMSG` — and any issue
    numbers quoted in a verbose diff — would count as references the author
    never wrote.
    """
    lines: list[str] = []
    for line in message.splitlines():
        if line.startswith("# ------------------------ >8 ------------------------"):
            break
        if line.startswith("#"):
            continue
        lines.append(line)
    return "\n".join(lines)


def message_issues(message: str) -> set[int]:
    """Return every issue number referenced in *message*."""
    return {int(number) for number in MESSAGE_ISSUE.findall(strip_comments(message))}


def should_skip(message: str) -> bool:
    """Return whether *message* is one this check does not apply to."""
    first_line = strip_comments(message).strip().splitlines()
    if not first_line:
        return True
    return first_line[0].lower().startswith(SKIP_PREFIXES)


def check(branch: str, message: str) -> str | None:
    """Return an error message when *branch* and *message* disagree, else None."""
    if should_skip(message):
        return None

    expected = branch_issue(branch)
    if expected is None:
        return None

    referenced = message_issues(message)
    if not referenced or expected in referenced:
        return None

    cited = ", ".join(f"#{number}" for number in sorted(referenced))
    return (
        f"Commit references {cited} but the branch is '{branch}' (issue #{expected}).\n"
        "\n"
        "This is what a commit landing on the previous issue's branch looks like:\n"
        "the code is fine, the branch name is valid, and only its location is wrong.\n"
        "\n"
        "  - If the commit belongs to a different issue, branch for it first:\n"
        "      git checkout main && git pull\n"
        f"      git checkout -b <type>/{sorted(referenced)[0]}-<description>\n"
        f"  - If it does belong to #{expected}, cite that issue in the message.\n"
        "\n"
        f"To commit anyway, set {OVERRIDE_ENV}=1 for this command.\n"
        "Do not use --no-verify; AGENTS.md forbids it."
    )


def main(argv: list[str] | None = None) -> int:
    """Entry point. Takes the path to the commit message file."""
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print("usage: check_commit_issue_ref.py <path-to-commit-msg-file>", file=sys.stderr)
        return 2

    if os.environ.get(OVERRIDE_ENV) == "1":
        return 0

    try:
        message = Path(args[0]).read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - defensive
        print(f"could not read commit message: {exc}", file=sys.stderr)
        return 2

    error = check(current_branch(), message)
    if error is None:
        return 0

    print(f"\n❌ {error}\n", file=sys.stderr)
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
