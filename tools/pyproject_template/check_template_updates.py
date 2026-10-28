#!/usr/bin/env python3
"""
check-template-updates.py - Compare project against latest template

This script fetches the latest pyproject-template release and shows which files
differ from the template. User can then manually review and merge changes.

Usage:
    python tools/pyproject_template/check_template_updates.py
    python tools/pyproject_template/manage.py check --template-version v2.2.0
    python tools/pyproject_template/check_template_updates.py --skip-changelog

Requirements:
    - Git installed
    - Python 3.12+
    - Internet connection (to fetch template)

Author: Generated from pyproject-template
License: MIT
"""

from __future__ import annotations

import argparse
import filecmp
import fnmatch
import os
import re
import shutil
import subprocess  # nosec B404
import sys
import urllib.error
import urllib.request
from pathlib import Path

try:
    import tomllib  # py311+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

# Support running as script or as module
_script_dir = Path(__file__).parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

# Import shared utilities
from utils import (  # noqa: E402
    SHA_RE,
    TEMPLATE_OWNED_TEST_FILES,
    TEMPLATE_REPO,
    TEMPLATE_URL,
    Colors,
    Logger,
    download_and_extract_archive,
    github_api_request,
)

# Frozen set for O(1) membership tests in the hot path of compare_files.
_TEMPLATE_OWNED_TEST_SET: frozenset[str] = frozenset(TEMPLATE_OWNED_TEST_FILES)

# Default archive URL derived from template constants
# The template is a rolling `main`; a tag or SHA can be named explicitly.
DEFAULT_TEMPLATE_REF = "main"

# Project-managed exclude file: paths or globs of upstream files the downstream
# project intentionally does not adopt. See docs/template/manage.md.
SYNC_EXCLUDE_FILE = Path(".config/pyproject_template/sync-exclude.toml")

# Downstream copies of the template-sync skill (#806, shared-skill layout #972).
# These are downstream-owned: a sync adopts them through the normal drift triage,
# never by this check overwriting them.
TEMPLATE_SYNC_SKILL_REL_PATHS = (
    ".agents/skills/template-sync/SKILL.md",
    ".claude/skills/template-sync/SKILL.md",
)

# Upstream location of the skill source at a ref, named in the warning below so
# an agent or admin can go re-read the current instructions before triaging a sync.
TEMPLATE_SYNC_SKILL_URL = (
    "https://raw.githubusercontent.com/{repo}/{ref}/.agents/skills/template-sync/SKILL.md"
)


def load_sync_excludes(project_root: Path) -> list[str]:
    """Load project-managed sync exclude patterns.

    Reads ``.config/pyproject_template/sync-exclude.toml`` from ``project_root``
    and returns the top-level ``exclude`` array as a list of glob patterns. The
    file is hand-managed by the downstream project; ``SettingsManager.save()``
    does not touch it.

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
    except (tomllib.TOMLDecodeError, OSError) as exc:
        Logger.warning(f"Could not read {SYNC_EXCLUDE_FILE}: {exc}")
        return []

    excludes = data.get("exclude", [])
    if not isinstance(excludes, list):
        Logger.warning(f"{SYNC_EXCLUDE_FILE}: 'exclude' must be a list of strings; ignoring.")
        return []

    return [str(item) for item in excludes if isinstance(item, str)]


class TemplateRefError(RuntimeError):
    """The template ref could not be pinned to a commit."""


def resolve_template_ref(ref: str) -> str:
    """Resolve *ref* -- a tag, branch or commit SHA -- to a commit SHA.

    One identity for a template version, matching what `bootstrap.py` pins
    (ADR-9020). A tag, a branch and a SHA all resolve here, so a comparison can
    be reproduced later and both halves of a sync can name the same commit.

    Raises:
        TemplateRefError: offline, rate-limited, an unknown ref or a non-SHA
            response. Unlike `bootstrap.resolve_ref`, the drift check does not
            continue against the moving ref: an extract of a moving ref cannot
            be recorded as a sync point, and continuing used to replace the
            reviewed extract `sync` needs (#1026).
    """
    if SHA_RE.match(ref):
        return ref

    api_url = f"https://api.github.com/repos/{TEMPLATE_REPO}/commits/{ref}"
    request = github_api_request(api_url, accept="application/vnd.github.sha")
    authenticated = request.has_header("Authorization")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # nosec B310
            sha: str = response.read().decode("utf-8").strip()
    except urllib.error.HTTPError as e:
        cause = "rate limited" if e.code in (403, 429) else str(e)
        raise TemplateRefError(_ref_error_message(ref, cause, authenticated)) from e
    except Exception as e:
        raise TemplateRefError(_ref_error_message(ref, str(e), authenticated)) from e

    if not SHA_RE.match(sha):
        raise TemplateRefError(
            _ref_error_message(ref, "unexpected response from the API", authenticated)
        )
    return sha


def _ref_error_message(ref: str, cause: str, authenticated: bool) -> str:
    """Name the cause of a failed ref lookup and the remedy for it."""
    if authenticated:
        remedy = (
            "check network access and that the ref exists, or wait for the API rate "
            "limit to reset, then re-run the check"
        )
    else:
        remedy = (
            "set GITHUB_TOKEN (e.g. GITHUB_TOKEN=$(gh auth token)) or log in with "
            "`gh auth login`, then re-run the check"
        )
    return f"Could not resolve '{ref}' to a commit ({cause}): {remedy}."


def download_template(target_dir: Path, ref: str | None = None) -> Path:
    """Download and extract the template at *ref* (a tag, branch or SHA).

    `ref` is resolved to a commit first, so one URL shape serves all three and
    the archive is a fixed commit rather than a moving branch.

    Raises:
        TemplateRefError: *ref* could not be pinned; nothing was downloaded.
    """
    commit = resolve_template_ref(ref or DEFAULT_TEMPLATE_REF)
    archive_url = f"{TEMPLATE_URL}/archive/{commit}.zip"

    template_root = Path(download_and_extract_archive(archive_url, target_dir))
    Logger.success(f"Template extracted to {template_root}")
    return template_root


def open_changelog(template_dir: Path) -> None:
    """Open CHANGELOG.md in user's editor."""
    changelog = template_dir / "CHANGELOG.md"
    if not changelog.exists():
        Logger.warning("CHANGELOG.md not found in template")
        return

    editor = os.environ.get("EDITOR", "less")

    print(f"\n{Colors.CYAN}Opening CHANGELOG.md for review...{Colors.NC}")
    print("(Close the editor when you're done)\n")

    try:
        subprocess.run([editor, str(changelog)], check=True)
    except subprocess.CalledProcessError:
        Logger.warning(f"Failed to open editor '{editor}'")
    except FileNotFoundError:
        Logger.warning(f"Editor '{editor}' not found, skipping changelog view")


def compare_files(
    project_root: Path,
    template_root: Path,
    excludes: list[str] | None = None,
) -> tuple[list[Path], list[Path]]:
    """Compare project files against template.

    Args:
        project_root: Project root directory.
        template_root: Extracted upstream template directory.
        excludes: Optional list of glob patterns (matched via :func:`fnmatch.fnmatch`
            against upstream-relative posix paths). When ``None``, the patterns are
            loaded from the project's ``sync-exclude.toml`` via
            :func:`load_sync_excludes`.

    Returns:
        ``(different_files, excluded_files)``. Both lists contain upstream-relative
        paths whose contents differ from the project. Files matching ``excludes``
        appear only in ``excluded_files``; everything else lands in
        ``different_files``. Files matching the hardcoded ``skip_patterns`` set
        are not in either list.
    """
    if excludes is None:
        excludes = load_sync_excludes(project_root)

    # Files/directories to skip (build artifacts, never user-configurable).
    skip_patterns = {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "tmp",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "*.pyc",
        "*.pyo",
        "uv.lock",
        ".envrc.local",
        "site",  # mkdocs build output
    }

    # Detect user's actual package name (directory under src/ that isn't package_name)
    actual_package_name: str | None = None
    src_dir = project_root / "src"
    if src_dir.exists():
        for item in src_dir.iterdir():
            if item.is_dir() and item.name != "package_name" and not item.name.startswith("."):
                actual_package_name = item.name
                break

    different_files: list[Path] = []
    excluded_files: list[Path] = []

    # Walk through template files
    for template_file in template_root.rglob("*"):
        if not template_file.is_file():
            continue

        # Skip hardcoded build-artifact patterns.
        rel_path = template_file.relative_to(template_root)
        if any(part in skip_patterns for part in rel_path.parts):
            continue
        if any(rel_path.match(pattern) for pattern in skip_patterns):
            continue

        # Map src/package_name/* to src/{actual_package_name}/*
        mapped_path = rel_path
        if (
            actual_package_name
            and len(rel_path.parts) >= 2
            and rel_path.parts[0] == "src"
            and rel_path.parts[1] == "package_name"
        ):
            mapped_path = Path("src", actual_package_name, *rel_path.parts[2:])

        # Compare with project file
        project_file = project_root / mapped_path
        if project_file.exists() and filecmp.cmp(template_file, project_file, shallow=False):
            continue  # Files match; nothing to report.

        # File differs (or is missing). Bucket it.
        rel_str = rel_path.as_posix()

        # Template-owned tooling tests are never adoptable drift: they live and
        # run in the template's own CI only. Skip them silently so they never
        # appear in different_files (and therefore never show up as "please
        # adopt this test" suggestions to downstream projects).
        if rel_str in _TEMPLATE_OWNED_TEST_SET:
            continue

        if excludes and any(fnmatch.fnmatch(rel_str, pat) for pat in excludes):
            excluded_files.append(rel_path)
        else:
            different_files.append(rel_path)

    return sorted(different_files), sorted(excluded_files)


def _imports_pyproject_tooling(content: str) -> bool:
    """Return True if ``content`` has a real import of the pyproject_template tooling.

    Anchored to actual ``import`` / ``from`` statements so that docstring or comment
    mentions of ``tools.pyproject_template`` (for example the note left behind in the
    split-out ``tests/template/test_properties.py``) do not count. This also keeps the
    coupling guard from matching ``tools.doit`` imports, which ``bootstrap --sync`` does
    not refresh.
    """
    return bool(
        re.search(
            r"^\s*(?:from|import)\s+tools\.pyproject_template\b",
            content,
            re.MULTILINE,
        )
    )


def _emit_coupling_warnings(different_files: list[Path], project_root: Path) -> None:
    """Warn when a drifted non-template-owned test imports tooling that has also drifted.

    This is a backstop for future straddlers: if a ``tests/template/test_*.py``
    file is NOT in ``TEMPLATE_OWNED_TEST_FILES`` (so it shows up as normal drift)
    but its local copy imports from ``tools.pyproject_template``, AND the tooling
    itself has also drifted, the downstream needs to run ``bootstrap --sync``
    first so the tooling matches what the test expects.

    Args:
        different_files: Paths (upstream-relative) returned by ``compare_files``.
        project_root: Downstream project root.
    """
    # Only engage the guard when the tooling itself has also drifted.
    tooling_drifted = any(
        file_path.as_posix().startswith("tools/pyproject_template/")
        for file_path in different_files
    )
    if not tooling_drifted:
        return

    for file_path in different_files:
        rel_str = file_path.as_posix()
        if not (rel_str.startswith("tests/template/test_") and rel_str.endswith(".py")):
            continue
        local_file = project_root / file_path
        if not local_file.is_file():
            continue
        try:
            content = local_file.read_text(encoding="utf-8")
        except OSError:
            continue
        if _imports_pyproject_tooling(content):
            Logger.warning(
                f"{rel_str}: imports tools/pyproject_template/ which has also drifted — "
                "run 'bootstrap --sync' to refresh tooling before adopting this test."
            )


def stale_template_sync_skill_copies(project_root: Path, template_root: Path) -> list[Path]:
    """Return project-relative paths of ``template-sync`` ``SKILL.md`` copies that are stale.

    Checks each path in ``TEMPLATE_SYNC_SKILL_REL_PATHS`` -- the ``.agents/`` and
    ``.claude/`` copies of the skill -- against ``template_root``. A path the
    template lacks is skipped: it names an older ref that predates the
    shared-skill layout (#806), so its absence is not drift, just a ref that
    predates the feature.

    A path is stale when the project's copy is missing, or when its contents
    differ from the template's.

    Args:
        project_root: Downstream project root.
        template_root: Extracted upstream template directory.

    Returns:
        Sorted project-relative paths that are missing or differ. Empty when
        both copies match, or the template has neither path.
    """
    stale: list[Path] = []
    for rel in TEMPLATE_SYNC_SKILL_REL_PATHS:
        template_file = template_root / rel
        if not template_file.is_file():
            continue  # Older ref predates #806 -- not stale, just absent upstream.

        project_file = project_root / rel
        if not project_file.is_file() or not filecmp.cmp(
            template_file, project_file, shallow=False
        ):
            stale.append(Path(rel))

    return sorted(stale)


def _warn_stale_template_sync_skill(
    stale: list[Path], project_root: Path, ref: str = DEFAULT_TEMPLATE_REF
) -> None:
    """Warn, before the drift report, that the local ``template-sync`` skill is stale.

    Prints nothing when ``stale`` is empty. This only warns and never writes --
    the skill is downstream-owned (#806), and adopting a stale copy goes through
    the normal drift triage (Step 5 of the skill itself), not an overwrite here.
    A skill that is already running also cannot usefully reload itself mid-sync.

    Args:
        stale: Project-relative paths returned by ``stale_template_sync_skill_copies``.
        project_root: Downstream project root the paths are relative to.
        ref: Template ref the copies were compared against, named in the URL.
    """
    if not stale:
        return

    Logger.warning(
        "Your local template-sync skill is older than the template's. Re-read "
        f"{TEMPLATE_SYNC_SKILL_URL.format(repo=TEMPLATE_REPO, ref=ref)} before triaging this sync."
    )
    for rel_path in stale:
        status = "(differs)" if (project_root / rel_path).is_file() else "(missing)"
        print(f"  {rel_path} {status}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare your project against the latest pyproject-template."
    )
    parser.add_argument(
        "--template-version",
        type=str,
        default=None,
        help=(
            "Compare against a specific template ref -- a tag, a branch, or a commit "
            "SHA. Defaults to 'main'."
        ),
    )
    parser.add_argument(
        "--skip-changelog",
        action="store_true",
        help="Skip opening CHANGELOG.md in editor",
    )
    parser.add_argument(
        "--keep-template",
        action="store_true",
        help="Keep downloaded template after comparison (don't clean up)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be checked without downloading (currently same as normal)",
    )
    parser.add_argument(
        "--show-excluded",
        action="store_true",
        help="List paths skipped via .config/pyproject_template/sync-exclude.toml",
    )
    return parser.parse_args(argv)


def run_check_updates(
    template_version: str | None = None,
    skip_changelog: bool = False,
    keep_template: bool = False,
    dry_run: bool = False,
    show_excluded: bool = False,
) -> int:
    """Check for template updates.

    Args:
        template_version: Template ref to compare against -- a tag, branch or SHA.
        skip_changelog: Skip opening CHANGELOG.md in editor.
        keep_template: Keep downloaded template after comparison.
        dry_run: Show what would be done without making changes.
        show_excluded: List paths skipped via the project's sync-exclude.toml.

    Returns:
        Exit code (0 for success, non-zero for error).
    """
    project_root = Path.cwd()
    tmp_dir = project_root / "tmp"
    tmp_dir.mkdir(exist_ok=True)

    # Which template snapshot to compare against. `main` by default -- this
    # template publishes no releases, and the previous code only reached `main`
    # by failing a releases/latest lookup first (#781).
    ref = template_version or DEFAULT_TEMPLATE_REF
    Logger.info(f"Comparing against template ref: {ref}")

    if dry_run:
        Logger.info("Dry run mode - would download and compare template files")
        return 0

    # Download template. A ref that cannot be pinned stops the check before
    # anything on disk changes, so a reviewed extract survives it (#1026).
    try:
        template_dir = download_template(tmp_dir, ref)
    except TemplateRefError as e:
        Logger.error(str(e))
        return 1

    # Warn -- before anything else -- if the local template-sync skill copies
    # are older than the template just downloaded. An agent following a stale
    # skill triages the rest of this sync on out-of-date instructions.
    stale_skill_copies = stale_template_sync_skill_copies(project_root, template_dir)
    _warn_stale_template_sync_skill(stale_skill_copies, project_root, ref)

    # Open CHANGELOG.md for review
    if not skip_changelog:
        open_changelog(template_dir)

    # Compare files
    Logger.header("Comparing your project to template")
    different_files, excluded_files = compare_files(project_root, template_dir)

    # Detect user's actual package name for display mapping
    actual_package_name: str | None = None
    src_dir = project_root / "src"
    if src_dir.exists():
        for item in src_dir.iterdir():
            if item.is_dir() and item.name != "package_name" and not item.name.startswith("."):
                actual_package_name = item.name
                break

    if not different_files:
        Logger.success("Your project matches the template perfectly!")
        print("\nNo differences found.")
    else:
        count = len(different_files)
        print(f"\n{Colors.YELLOW}Files different from template ({count} files):{Colors.NC}")
        print("━" * 60)

        for file_path in different_files:
            # Map src/package_name/* to src/{actual_package_name}/* for checking
            mapped_path = file_path
            if (
                actual_package_name
                and len(file_path.parts) >= 2
                and file_path.parts[0] == "src"
                and file_path.parts[1] == "package_name"
            ):
                mapped_path = Path("src", actual_package_name, *file_path.parts[2:])

            project_file = project_root / mapped_path
            if project_file.exists():
                print(f"  {file_path}")
            else:
                print(f"  {file_path} {Colors.CYAN}(new in template){Colors.NC}")

        # Coupling guard: warn when a non-template-owned drifted test imports
        # tooling that has also drifted — the user needs to bootstrap --sync first.
        _emit_coupling_warnings(different_files, project_root)

        # Show how to compare
        Logger.header("How to Review Changes")
        template_rel = template_dir.relative_to(project_root)
        print(f"Template files downloaded to: {Colors.CYAN}{template_rel}{Colors.NC}\n")

        print("To compare specific files:")
        # Show a few example diff commands
        for file_path in different_files[:3]:
            project_file = project_root / file_path
            template_file = template_dir / file_path
            if project_file.exists():
                print(f"  diff {file_path} {template_file.relative_to(project_root)}")

        if len(different_files) > 3:
            print(f"  ... ({len(different_files) - 3} more files)")

        print(f"\nOr browse all template files: {template_dir.relative_to(project_root)}/")

    if excluded_files:
        print(
            f"\n{Colors.CYAN}Skipped per project policy: {len(excluded_files)} files "
            f"(see {SYNC_EXCLUDE_FILE}){Colors.NC}"
        )
        if show_excluded:
            for file_path in excluded_files:
                print(f"  {file_path}")

    # Cleanup
    if not keep_template:
        print()
        Logger.info("Cleaning up downloaded template...")
        shutil.rmtree(template_dir.parent)
        Logger.success("Cleanup complete")
    else:
        print()
        Logger.info(f"Template kept at: {template_dir.relative_to(project_root)}")

    print()
    return 0


def main(argv: list[str] | None = None) -> int:
    """Main entry point for CLI usage."""
    args = parse_args(argv)
    return run_check_updates(
        template_version=args.template_version,
        skip_changelog=args.skip_changelog,
        keep_template=args.keep_template,
        dry_run=args.dry_run,
        show_excluded=args.show_excluded,
    )


if __name__ == "__main__":
    import sys

    print("This script should not be run directly.")
    print("Please use: python manage.py")
    sys.exit(1)
