#!/usr/bin/env python3
"""
Session-start hook that tells the user when the project is behind pyproject-template.

A project made from pyproject-template records the template commit it last synced to in
``.config/pyproject_template/settings.toml`` (``[template].commit``, ADR-9020). This hook
compares that commit to the head of the template's ``main`` (``git ls-remote``, short timeout,
cached for 24h) and prints one line when they differ.

It is silent, and exits 0, in every no-op case: opted out with
``PYPROJECT_TEMPLATE_UPDATE_CHECK=0``, no settings file, no recorded commit, running inside the
template repo itself, offline, timeout or any ``git`` error. It never blocks a session.

This script ships with projects, and ``tools/pyproject_template/`` is removed on configuration
(ADR-9017), so it imports only the standard library.

Usage: ``template-update-check.py [--host={claude,copilot,codex,antigravity}]``. The host picks the
output shape; without it the hook prints a plain line. ``claude`` and ``codex`` get a yellow
``systemMessage`` (plain when ``NO_COLOR`` is set and non-empty); ``claude`` also carries an
``additionalContext`` relay line, because Copilot CLI runs this hook and drops ``systemMessage``.

For documentation, see: docs/template/updates.md
"""

from __future__ import annotations

import json
import os
import subprocess  # nosec B404  # runs git with list args, never a shell
import sys
import time
import tomllib
from collections.abc import Mapping
from pathlib import Path

# Local copy of tools/pyproject_template/utils.py TEMPLATE_REPO (ADR-9017); a template-owned
# test keeps the two equal.
TEMPLATE_REPO = "endavis/pyproject-template"
TEMPLATE_URL = f"https://github.com/{TEMPLATE_REPO}"
OPT_OUT_ENV = "PYPROJECT_TEMPLATE_UPDATE_CHECK"
CACHE_TTL_SECONDS = 24 * 60 * 60
LS_REMOTE_TIMEOUT_SECONDS = 2
MIN_SHA_MATCH = 7
YELLOW = "\033[33m"
RESET = "\033[0m"
RELAY_PREFIX = "Tell the user, in one line: "

ROOT: Path = Path(__file__).resolve().parents[3]
SETTINGS_RELATIVE = Path(".config") / "pyproject_template" / "settings.toml"
CACHE_RELATIVE = Path("tmp") / "template-update-check.json"


def is_opted_out(env: dict[str, str] | None = None) -> bool:
    """Return True when the user set ``PYPROJECT_TEMPLATE_UPDATE_CHECK=0``."""
    values = os.environ if env is None else env
    return values.get(OPT_OUT_ENV, "").strip() == "0"


def read_recorded_commit(root: Path) -> str | None:
    """Return ``[template].commit`` from settings.toml, or None when unavailable."""
    try:
        data = tomllib.loads((root / SETTINGS_RELATIVE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    template = data.get("template")
    if not isinstance(template, dict):
        return None
    commit = template.get("commit")
    if not isinstance(commit, str) or not commit.strip():
        return None
    return commit.strip()


def is_template_repo(root: Path) -> bool:
    """Return True when ``root`` is a checkout of the template repo itself."""
    try:
        result = subprocess.run(  # nosec B603 B607  # list args, fixed git command
            ["git", "config", "--get", "remote.origin.url"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=LS_REMOTE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if result.returncode != 0:
        return False
    url = result.stdout.strip()
    if url.endswith("/"):
        url = url[:-1]
    url = url.removesuffix(".git")
    # Anchor on a separator so a fork named "pyproject-template-foo" is not the template.
    return url == TEMPLATE_REPO or url.endswith(("/" + TEMPLATE_REPO, ":" + TEMPLATE_REPO))


def read_cache(path: Path, now: float) -> tuple[bool, str | None]:
    """Return ``(hit, sha)``. ``sha`` is None for a cached failed check. A bad cache is a miss."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        checked = float(data["checked_at"])
        sha = data["sha"]
    except (OSError, ValueError, KeyError, TypeError):
        return False, None
    if sha is not None and not isinstance(sha, str):
        return False, None
    if not 0 <= now - checked < CACHE_TTL_SECONDS:
        return False, None
    return True, sha


def write_cache(path: Path, sha: str | None, now: float) -> None:
    """Best-effort cache write; a failure only costs another ``ls-remote`` next time."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"checked_at": now, "sha": sha}), encoding="utf-8")
    except OSError:
        return


def fetch_remote_head() -> str | None:
    """Return the template ``main`` head SHA, or None on any failure."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        result = subprocess.run(  # nosec B603 B607  # list args, fixed URL, no shell
            ["git", "ls-remote", TEMPLATE_URL, "refs/heads/main"],
            capture_output=True,
            text=True,
            timeout=LS_REMOTE_TIMEOUT_SECONDS,
            check=False,
            env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    fields = result.stdout.split()
    if len(fields) < 2 or fields[1] != "refs/heads/main":
        return None
    sha = fields[0].lower()
    if len(sha) < 40 or any(c not in "0123456789abcdef" for c in sha):
        return None
    return sha


def shas_match(recorded: str, remote: str) -> bool:
    """Return True when one SHA is a prefix of the other (at least 7 characters)."""
    a, b = recorded.lower(), remote.lower()
    if min(len(a), len(b)) < MIN_SHA_MATCH:
        return a == b
    return a.startswith(b) or b.startswith(a)


def build_message(recorded: str) -> str:
    """Return the one-line notice."""
    return (
        f"pyproject-template has updates since {recorded[:7]}. "
        "Run the template-sync skill to review them."
    )


def colorize(text: str, env: Mapping[str, str] | None = None) -> str:
    """Wrap ``text`` in yellow, unless ``NO_COLOR`` is set and non-empty (no-color.org)."""
    values = os.environ if env is None else env
    if values.get("NO_COLOR", ""):
        return text
    return f"{YELLOW}{text}{RESET}"


def format_output(message: str, host: str | None, env: Mapping[str, str] | None = None) -> str:
    """Shape ``message`` for ``host``; with no host, a plain line."""
    if host == "claude":
        # Claude shows systemMessage to the user. Copilot runs this same hook but drops
        # systemMessage, so a plain top-level additionalContext asks the model to relay it;
        # Claude ignores unknown top-level keys.
        return json.dumps(
            {
                "systemMessage": colorize(message, env),
                "additionalContext": f"{RELAY_PREFIX}{message}",
            }
        )
    if host == "codex":
        return json.dumps({"systemMessage": colorize(message, env)})
    if host == "copilot":
        return json.dumps({"additionalContext": message})
    if host == "antigravity":
        # agy injects steps into the model's context; it has no user-facing field, so ask the
        # model to relay the notice. Shape confirmed by probe (SessionStartHookResult).
        text = f"{RELAY_PREFIX}{message}"
        return json.dumps({"injectSteps": [{"systemMessage": {"systemMessage": text}}]})
    return message


def check(root: Path, now: float, env: dict[str, str] | None = None) -> str | None:
    """Return the notice, or None when there is nothing to say. Cheapest checks first."""
    if is_opted_out(env):
        return None
    recorded = read_recorded_commit(root)
    if recorded is None:
        return None
    if is_template_repo(root):
        return None
    cache_path = root / CACHE_RELATIVE
    hit, remote = read_cache(cache_path, now)
    if not hit:
        remote = fetch_remote_head()
        write_cache(cache_path, remote, now)
    if remote is None or shas_match(recorded, remote):
        return None
    return build_message(recorded)


def parse_host(argv: list[str]) -> str | None:
    """Return the value of ``--host=<name>``, or None."""
    for arg in argv:
        if arg.startswith("--host="):
            return arg.split("=", 1)[1] or None
    return None


def main(argv: list[str] | None = None) -> int:
    """Hook entry point. Always returns 0; tests call this directly."""
    try:
        host = parse_host(sys.argv[1:] if argv is None else argv)
        message = check(ROOT, time.time())
        if message is not None:
            sys.stdout.write(format_output(message, host))
            sys.stdout.flush()
    except Exception:  # hook must never raise
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
