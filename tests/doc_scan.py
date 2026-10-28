"""Tests-only helpers for scanning committed markdown and honoring sync-exclude.toml.

`tools/pyproject_template/check_template_updates.load_sync_excludes()` is removed when a
downstream project sheds the template suite (ADR-9017), so a test that ships downstream
cannot import it. It also cannot move into `tools/doit/`: `bootstrap.py` downloads this
template's own tooling on its own, without `tools/doit/` on the path. This module
therefore duplicates the small amount of logic the doc tests need — `tomllib` plus
`fnmatch.fnmatch` against a posix-relative path — rather than importing it.

`tests/template/test_check_template_updates.py` (template-owned, never shed to a
downstream project) carries a parity test that keeps this copy and the real one from
drifting apart.

Follows the `tests/agent_roster.py` precedent: a helper module, not a test module —
pytest does not collect it (the filename does not match ``test_*.py``).
"""

from __future__ import annotations

import fnmatch
import subprocess  # nosec B404 - subprocess is required to list git-tracked files
from pathlib import Path

try:
    import tomllib  # py311+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

# Project-managed exclude file: paths or globs of upstream files the downstream
# project intentionally does not adopt. See docs/template/manage.md. Duplicated
# from check_template_updates.SYNC_EXCLUDE_FILE -- see the module docstring.
SYNC_EXCLUDE_FILE = Path(".config/pyproject_template/sync-exclude.toml")


def load_sync_excludes(project_root: Path) -> list[str]:
    """Load project-managed sync exclude patterns.

    Duplicated from
    ``tools/pyproject_template/check_template_updates.load_sync_excludes`` --
    see the module docstring for why this cannot be a shared import. Keep the
    two in lockstep; `tests/template/test_check_template_updates.py` pins that
    they agree.

    Args:
        project_root: Project root directory.

    Returns:
        List of glob patterns. Returns an empty list when the file is absent,
        unreadable, malformed TOML, or missing/non-list ``exclude`` key.
    """
    exclude_file = project_root / SYNC_EXCLUDE_FILE
    if not exclude_file.is_file():
        return []

    try:
        with exclude_file.open("rb") as f:
            data = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError):
        return []

    excludes = data.get("exclude", [])
    if not isinstance(excludes, list):
        return []

    return [str(item) for item in excludes if isinstance(item, str)]


def is_excluded(rel_posix: str, excludes: list[str]) -> bool:
    """Return whether *rel_posix* matches any pattern in *excludes*.

    Matched with :func:`fnmatch.fnmatch`, the same matcher
    ``check_template_updates.compare_files`` uses, so a pattern that silences
    drift there also silences the corresponding doc check here.
    """
    return any(fnmatch.fnmatch(rel_posix, pattern) for pattern in excludes)


def committed_markdown_files(root: Path) -> list[Path]:
    """Return every markdown file under *root* that git would track or add.

    Uses ``git ls-files -z --cached --others --exclude-standard -- '*.md'``:
    tracked files and untracked-but-not-ignored files are included, so local
    authoring still works; anything `.gitignore` excludes -- including
    `worktrees/`, each a full copy of the repository -- drops out, which is
    what makes a hardcoded `SKIP_DIRS` unnecessary.

    Raises whatever ``subprocess`` raises if ``git`` is missing, and raises
    ``subprocess.CalledProcessError`` if *root* is not inside a git repository
    or the command otherwise fails. Deliberately not caught: a silent fallback
    to ``rglob`` is the exact bug this helper replaces (missing targets that
    should have failed the check passing because the scan read nothing).

    Returns:
        Absolute paths, sorted.
    """
    result = subprocess.run(  # nosec B603 B607 - fixed argv, no shell
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "*.md"],
        cwd=root,
        capture_output=True,
        check=True,
        text=True,
    )
    rel_paths = [p for p in result.stdout.split("\0") if p]
    return sorted(root / p for p in rel_paths)
