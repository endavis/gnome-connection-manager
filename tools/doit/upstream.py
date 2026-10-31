"""Pure helpers for ``doit issue --upstream`` (#1090).

``--upstream`` files an issue on the template repository from a project made from it. This module
holds the template repo name and the checks that need no ``gh`` call; the ``gh`` calls live in
``tools/doit/github.py``. It defines no ``task_`` functions, so doit's auto-discovery ignores it.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

# Local copy of tools/pyproject_template/utils.py TEMPLATE_REPO (ADR-9017): that package is shed on
# configuration, so tools/doit/ keeps its own. A template-owned test keeps the copies equal.
# This is the only occurrence of the name in tools/doit/.
TEMPLATE_REPO = "endavis/pyproject-template"

# Where a security finding goes instead of a public issue.
PRIVATE_REPORT_URL = f"https://github.com/{TEMPLATE_REPO}/security/policy"

SETTINGS_RELATIVE = Path(".config") / "pyproject_template" / "settings.toml"

# Case-insensitive, word-bounded terms that mark content as a security finding. Bare "security" is
# left out on purpose so a bug in `security-triage` or `doit audit` is not blocked.
_SECURITY_TERMS = (
    r"vulnerab\w*",
    r"exploit\w*",
    r"CVE-\d{4}-\d+",
    r"GHSA-",
    r"security (?:issue|bug|flaw|hole|finding|advisory)",
    r"bypass\w*",
    r"privilege escalation",
    r"remote code execution",
    r"arbitrary (?:code|command)",
    r"(?:command|shell|path|code) injection",
    r"path traversal",
    r"(?:secret|token|credential)s? (?:leak|exposed|disclos)\w*",
)
_SECURITY_PATTERN = re.compile(r"(?<![\w-])(?:" + "|".join(_SECURITY_TERMS) + r")", re.IGNORECASE)


def read_recorded_commit(root: Path) -> str | None:
    """Return ``[template].commit`` from settings.toml under *root*, or None when unavailable."""
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


def is_template_repo_slug(slug: str) -> bool:
    """Return True when *slug* names the template repository (case-insensitive)."""
    return slug.strip().lower() == TEMPLATE_REPO.lower()


def security_match(title: str, body: str) -> str | None:
    """Return the first security term found in *title* or *body*, or None."""
    match = _SECURITY_PATTERN.search(f"{title}\n{body}")
    return match.group(0) if match else None


def build_footer(commit: str | None, origin: str | None = None) -> str:
    """Return the footer appended to an upstream issue body.

    *origin* is the downstream repository slug; it is included only when given, because a
    downstream repository may be private.
    """
    recorded = commit if commit else "not recorded"
    line = f"Filed with `doit issue --upstream`. Template commit: `{recorded}`."
    if origin:
        line += f" Origin: `{origin}`."
    return f"---\n<sub>{line}</sub>\n"
