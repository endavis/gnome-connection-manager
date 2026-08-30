#!/usr/bin/env python3
"""
cleanup.py - Template file cleanup utilities.

This module provides functions to remove template-specific files from projects
created from pyproject-template. Users can choose to:
1. Remove setup files only (keep update checking capability)
2. Remove all template files (no future update checking)

Usage:
    from cleanup import cleanup_template_files, CleanupMode

    # Remove setup files only
    cleanup_template_files(CleanupMode.SETUP_ONLY)

    # Remove all template files
    cleanup_template_files(CleanupMode.ALL)

    # Preview what would be deleted
    cleanup_template_files(CleanupMode.SETUP_ONLY, dry_run=True)
"""

from __future__ import annotations

import re
import shutil
import sys
from enum import Enum
from pathlib import Path
from typing import NamedTuple

# Support running as script or as module
_script_dir = Path(__file__).parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

from utils import TEMPLATE_OWNED_TEST_FILES, Logger  # noqa: E402


class CleanupMode(Enum):
    """Cleanup mode selection."""

    SETUP_ONLY = "setup"  # Remove setup files, keep update checking
    ALL = "all"  # Remove all template files


class CleanupResult(NamedTuple):
    """Result of cleanup operation."""

    deleted_files: list[Path]
    deleted_dirs: list[Path]
    failed: list[tuple[Path, str]]
    mkdocs_updated: bool


# Files to delete when removing setup files only
# These are only needed for initial project creation.
# TEMPLATE_OWNED_TEST_FILES are included so that SETUP_ONLY sheds tooling
# tests from downstream projects (they only run in the template's own CI).
SETUP_FILES = [
    "bootstrap.py",
    "tools/pyproject_template/setup_repo.py",
    "docs/template/new-project.md",
    "docs/template/migration.md",
    *TEMPLATE_OWNED_TEST_FILES,
]

# Additional files to delete when removing all template files
# After this, no template update checking is possible
ALL_TEMPLATE_FILES = [
    "tools/pyproject_template/manage.py",
    "tools/pyproject_template/check_template_updates.py",
    "tools/pyproject_template/configure.py",
    "tools/pyproject_template/settings.py",
    "tools/pyproject_template/repo_settings.py",
    "tools/pyproject_template/cleanup.py",
    "tools/pyproject_template/utils.py",
    "tools/pyproject_template/__init__.py",
    # doit task that wraps cleanup.py — useless in a spawned project because
    # the module it imports is deleted above. Leaving it in ``doit list``
    # would be misleading.
    "tools/doit/template_clean.py",
    "docs/template/index.md",
    "docs/template/manage.md",
    "docs/template/updates.md",
    "docs/template/tools-reference.md",
]

# Directories to delete when removing all template files
ALL_TEMPLATE_DIRS = [
    "tools/pyproject_template",
    "docs/template",
    ".config/pyproject_template",
]


def get_files_to_delete(mode: CleanupMode, root: Path | None = None) -> list[Path]:
    """Get list of files that would be deleted for the given mode.

    Args:
        mode: Cleanup mode (SETUP_ONLY or ALL)
        root: Project root directory (defaults to cwd)

    Returns:
        List of file paths that exist and would be deleted
    """
    if root is None:
        root = Path.cwd()

    files = SETUP_FILES.copy()
    if mode == CleanupMode.ALL:
        files.extend(ALL_TEMPLATE_FILES)

    existing_files = []
    for file_path in files:
        full_path = root / file_path
        if full_path.is_file():
            existing_files.append(full_path)

    return existing_files


def get_dirs_to_delete(mode: CleanupMode, root: Path | None = None) -> list[Path]:
    """Get list of directories that would be deleted for the given mode.

    Args:
        mode: Cleanup mode (only ALL mode deletes directories)
        root: Project root directory (defaults to cwd)

    Returns:
        List of directory paths that exist and would be deleted
    """
    if root is None:
        root = Path.cwd()

    if mode != CleanupMode.ALL:
        return []

    existing_dirs = []
    for dir_path in ALL_TEMPLATE_DIRS:
        full_path = root / dir_path
        if full_path.is_dir():
            existing_dirs.append(full_path)

    return existing_dirs


def update_mkdocs_nav(root: Path | None = None, dry_run: bool = False) -> bool:
    """Remove Template section from mkdocs.yml navigation.

    Args:
        root: Project root directory (defaults to cwd)
        dry_run: If True, only report what would be changed

    Returns:
        True if mkdocs.yml was updated (or would be), False otherwise
    """
    if root is None:
        root = Path.cwd()

    mkdocs_file = root / "mkdocs.yml"
    if not mkdocs_file.exists():
        return False

    content = mkdocs_file.read_text(encoding="utf-8")

    # Pattern to match the Template section in nav
    # Matches from "  - Template:" to the next "  - " at the same indent level or end of nav
    pattern = r"(  - Template:\n(?:      - [^\n]+\n)*)"

    if not re.search(pattern, content):
        return False

    if dry_run:
        Logger.info("Would remove Template section from mkdocs.yml")
        return True

    new_content = re.sub(pattern, "", content)
    mkdocs_file.write_text(new_content, encoding="utf-8")
    Logger.success("Removed Template section from mkdocs.yml")
    return True


# Regex patterns used by scrub_template_references. Defined at module scope so
# tests can import/inspect them if needed. The patterns are applied blindly
# (``re.sub`` is a no-op when nothing matches), and the function detects
# whether any scrub occurred by comparing the final content to the original.

# ``pyproject.toml`` stanza for the template-only tools.pyproject_template.*
# mypy override. Removes the ``[[tool.mypy.overrides]]`` block (including its
# two trailing preceding comment lines and the ``follow_imports = "skip"`` row)
# plus the single blank line that separates it from the next section. Greedy
# comment capture is avoided by anchoring on the module line.
#
# Kept as a fallback because ``doit fmt_pyproject`` in the wizard rewrites the
# stanza form into inline-array form before the scrubber runs
# (see ``_PYPROJECT_TEMPLATE_MYPY_OVERRIDE_INLINE_RE``); downstream users that
# invoke the scrubber on an un-formatted file still need this pattern to hit.
_PYPROJECT_TEMPLATE_MYPY_OVERRIDE_RE = re.compile(
    r"\[\[tool\.mypy\.overrides\]\]\n"
    r"(?:# [^\n]*\n)*"  # optional explanatory comments
    r'module = "tools\.pyproject_template\.\*"\n'
    r'follow_imports = "skip"\n'
    r"\n?",  # trailing blank line (optional so trailing-file case is tolerated)
)

# ``pyproject.toml`` inline-array form of the mypy override. ``doit
# fmt_pyproject`` (run earlier in the wizard) rewrites the stanza form into
# an entry inside ``overrides = [...]``. The two comment lines above the
# dict entry are preserved by the formatter, so they're part of the match.
_PYPROJECT_TEMPLATE_MYPY_OVERRIDE_INLINE_RE = re.compile(
    r"  # Standalone scripts using sys\.path manipulation; excluded from discovery\n"
    r"  # but still followed via imports from bootstrap\.py\n"
    r'  \{ module = "tools\.pyproject_template\.\*", follow_imports = "skip" \},\n',
)

# ``pyproject.toml`` ruff ``per-file-ignores`` block targeting
# ``tools/pyproject_template/*.py``. Matches the whole TOML entry from the
# ``lint.per-file-ignores."tools/pyproject_template/*.py" = [`` line through
# the closing ``]\n``; the indented body is captured non-greedily.
_PYPROJECT_TEMPLATE_RUFF_PERFILE_RE = re.compile(
    r'lint\.per-file-ignores\."tools/pyproject_template/\*\.py" = \[\n'
    r"(?:  [^\n]*\n)*?"
    r"\]\n",
)

# ``pyproject.toml`` comment line above ``[tool.mypy]::exclude`` that
# specifically references ``tools/pyproject_template/``. Removed alongside
# the corresponding array entry so the remaining AI-config excludes are not
# left dangling beneath a now-irrelevant explanatory comment.
_PYPROJECT_TEMPLATE_MYPY_EXCLUDE_COMMENT_RE = re.compile(
    r"# tools/pyproject_template/ uses sys\.path manipulation for standalone execution\n",
)

# ``pyproject.toml`` array entry ``"tools/pyproject_template/"`` inside
# ``[tool.mypy]::exclude = [...]``. The trailing ``\s*`` consumes the
# separator between array entries (comma, optional whitespace and/or
# newline), which handles both pyproject-fmt-normalized form (``[ ... ]``
# padded with spaces) and the raw template form.
_PYPROJECT_TEMPLATE_MYPY_EXCLUDE_ENTRY_RE = re.compile(
    r'"tools/pyproject_template/",\s*',
)

# doit-tasks-reference.md ``### template_clean`` section. Runs from the heading
# up to (but not including) the next ``### build`` heading. The non-greedy body
# match guards against consuming adjacent sections.
_DOIT_REF_TEMPLATE_CLEAN_RE = re.compile(
    r"### `template_clean`\n.*?(?=### `build`)",
    re.DOTALL,
)

# doit-tasks-reference.md TOC table row that lists ``template_clean`` alongside
# ``cleanup``. Rewrites the backtick-delimited command pair so the remaining
# task (``cleanup``) still shows up in the Maintenance row.
_DOIT_REF_TOC_TEMPLATE_CLEAN_RE = re.compile(
    r"`cleanup`, `template_clean`",
)

# docs/development/github-repository-settings.md intro paragraph (lines 16-20).
# Surgical scrub: removes ONLY the broken-link sentence pointing at deleted
# ``tools/pyproject_template/repo_settings.py``. The trailing space after
# ``update_all_repo_settings()\.`` is part of the match so the next sentence
# (``This page documents...``) joins cleanly to the previous newline. The
# preceding sentence (``Complete reference for the GitHub repository settings
# this template expects.``) and the doc-purpose sentence both survive.
_GITHUB_SETTINGS_REPO_SETTINGS_INTRO_RE = re.compile(
    r"New repositories created from the template are configured automatically by\n"
    r"\[`repo_settings\.py`\]\(\.\./\.\./tools/pyproject_template/repo_settings\.py\) via\n"
    r"`update_all_repo_settings\(\)`\. ",
)

# docs/development/github-repository-settings.md Security Settings paragraph
# (lines 233-234). Strips the entire paragraph plus its trailing blank line so
# the table that follows sits directly under the heading. The table is
# self-explanatory, so removing the prose introduction does not leave a gap.
_GITHUB_SETTINGS_SECURITY_REPO_SETTINGS_RE = re.compile(
    r"Security features are configured by `_configure_security_settings\(\)` in\n"
    r"`repo_settings\.py`\.\n\n",
)

# docs/development/release-and-automation.md "New projects (bootstrap flow)"
# paragraph (lines 94-96). REWRITES (not strips) the paragraph: the spawned
# project does have a ``v0.0.0`` tag (``configure.py`` created it during
# bootstrap before being deleted), so the user-facing instruction "push it
# when ready" is still correct — only the broken
# ``tools/pyproject_template/configure.py`` link needs to go. The lead
# ``**New projects (bootstrap flow).**`` and the trailing
# ``git push origin v0.0.0`` code block both survive untouched.
_RELEASE_AUTO_NEW_PROJECTS_BOOTSTRAP_RE = re.compile(
    r"\*\*New projects \(bootstrap flow\)\.\*\* `tools/pyproject_template/configure\.py`\n"
    r"auto-seeds a `v0\.0\.0` tag on the root commit, so nothing else is required —\n"
    r"only push it when you're ready:\n",
)

# Markers used by ``check_stale_template_references`` to surface any future
# regression of the #469 family bug class. Conservative list with zero
# false-positive risk in a spawned project: every reference to
# ``tools/pyproject_template/`` is broken once the directory is deleted; the
# ``template/tools-reference.md`` link is defensive coverage in case the TOC
# regenerator misses it; ``tools/doit/template_clean`` is namespaced enough
# that no legitimate file should match. ``bootstrap.py`` is excluded because
# legitimate ``curl ... bootstrap.py`` reinstall references survive in some
# docs.
_STALE_TEMPLATE_MARKERS = (
    "tools/pyproject_template/",
    "template/tools-reference.md",
    "tools/doit/template_clean",
)


def scrub_template_references(root: Path | None = None, dry_run: bool = False) -> list[Path]:
    """Remove user-visible stale references to template-only machinery.

    Applies targeted regex rewrites to five files that retain documentation
    or configuration for template-only tooling after the cleanup phase has
    deleted the files those references point at:

    * ``pyproject.toml`` — removes every ``tools/pyproject_template/``
      artifact: the ruff ``per-file-ignores`` block, the mypy ``exclude``
      entry (and its explanatory comment), and the mypy override (in both
      stanza and inline-array form, because ``doit fmt_pyproject`` rewrites
      the file before cleanup runs in the wizard).
    * ``docs/development/doit-tasks-reference.md`` — removes the
      ``### template_clean`` section and rewrites the TOC table row so the
      remaining ``cleanup`` entry is listed alone.

    ``README.md`` is deliberately absent from this list. It used to be scrubbed
    of template-only sections here; since #697 the consumer README ships
    separately as ``README.template.md``, which ``configure`` moves into place
    and which never contained those sections.
    * ``docs/development/github-repository-settings.md`` — strips the
      broken-link sentence in the intro paragraph that points at
      ``tools/pyproject_template/repo_settings.py``, and removes the
      ``Security Settings`` introductory paragraph that names
      ``_configure_security_settings()`` in the same deleted module.
    * ``docs/development/release-and-automation.md`` — rewrites the
      "New projects (bootstrap flow)" paragraph so the broken link to
      ``tools/pyproject_template/configure.py`` is gone but the user-facing
      "push the v0.0.0 tag when ready" instruction (and its trailing
      ``git push origin v0.0.0`` code block) survives untouched.

    Patterns are applied blindly; ``re.sub`` is a no-op when nothing matches,
    and the function detects whether a file changed by comparing final
    content to the original. That makes the scrubber idempotent — repeat
    calls and already-scrubbed files record no change.

    Companion helpers in this module handle the cases where a regex per file
    is the wrong tool: :func:`regenerate_doc_toc` rebuilds
    ``docs/TABLE_OF_CONTENTS.md`` from the surviving ``docs/`` tree (so all
    broken ``template/*.md`` links drop out in one pass), and
    :func:`check_stale_template_references` performs a warn-only post-cleanup
    sweep that surfaces any future regression of this bug class.

    Args:
        root: Project root directory (defaults to cwd).
        dry_run: If True, report what would be changed but do not write files.

    Returns:
        Sorted list of paths whose contents changed (or would change, under
        ``dry_run``). Empty list when no scrub was needed.
    """
    if root is None:
        root = Path.cwd()

    changed: list[Path] = []

    # 1. pyproject.toml — scrub all template-only configuration fragments.
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        original = pyproject.read_text(encoding="utf-8")
        new_content = original
        new_content = _PYPROJECT_TEMPLATE_RUFF_PERFILE_RE.sub("", new_content)
        new_content = _PYPROJECT_TEMPLATE_MYPY_EXCLUDE_COMMENT_RE.sub("", new_content)
        new_content = _PYPROJECT_TEMPLATE_MYPY_EXCLUDE_ENTRY_RE.sub("", new_content)
        new_content = _PYPROJECT_TEMPLATE_MYPY_OVERRIDE_RE.sub("", new_content)
        new_content = _PYPROJECT_TEMPLATE_MYPY_OVERRIDE_INLINE_RE.sub("", new_content)
        if new_content != original:
            if dry_run:
                Logger.info("Would scrub template-only references in pyproject.toml")
            else:
                pyproject.write_text(new_content, encoding="utf-8")
                Logger.success("Removed template-only references from pyproject.toml")
            changed.append(pyproject)

    # 2. docs/development/doit-tasks-reference.md — remove the template_clean
    #    section and rewrite the TOC row.
    doit_ref = root / "docs" / "development" / "doit-tasks-reference.md"
    if doit_ref.is_file():
        original = doit_ref.read_text(encoding="utf-8")
        new_content = original
        new_content = _DOIT_REF_TEMPLATE_CLEAN_RE.sub("", new_content)
        new_content = _DOIT_REF_TOC_TEMPLATE_CLEAN_RE.sub("`cleanup`", new_content)
        if new_content != original:
            if dry_run:
                Logger.info(
                    "Would scrub template_clean references in "
                    "docs/development/doit-tasks-reference.md"
                )
            else:
                doit_ref.write_text(new_content, encoding="utf-8")
                Logger.success(
                    "Removed template_clean references from "
                    "docs/development/doit-tasks-reference.md"
                )
            changed.append(doit_ref)

    # 3. docs/development/github-repository-settings.md — strip the broken
    #    intro-link sentence and the Security Settings introductory paragraph.
    github_settings = root / "docs" / "development" / "github-repository-settings.md"
    if github_settings.is_file():
        original = github_settings.read_text(encoding="utf-8")
        new_content = original
        new_content = _GITHUB_SETTINGS_REPO_SETTINGS_INTRO_RE.sub("", new_content)
        new_content = _GITHUB_SETTINGS_SECURITY_REPO_SETTINGS_RE.sub("", new_content)
        if new_content != original:
            if dry_run:
                Logger.info(
                    "Would scrub repo_settings.py references in "
                    "docs/development/github-repository-settings.md"
                )
            else:
                github_settings.write_text(new_content, encoding="utf-8")
                Logger.success(
                    "Removed repo_settings.py references from "
                    "docs/development/github-repository-settings.md"
                )
            changed.append(github_settings)

    # 4. docs/development/release-and-automation.md — rewrite the "New
    #    projects (bootstrap flow)" paragraph so the broken configure.py link
    #    is gone but the surrounding instruction and code block survive.
    release_auto = root / "docs" / "development" / "release-and-automation.md"
    if release_auto.is_file():
        original = release_auto.read_text(encoding="utf-8")
        new_content = _RELEASE_AUTO_NEW_PROJECTS_BOOTSTRAP_RE.sub(
            "**New projects (bootstrap flow).** A `v0.0.0` tag is auto-seeded on the\n"
            "root commit during initial setup, so nothing else is required — only push\n"
            "it when you're ready:\n",
            original,
        )
        if new_content != original:
            if dry_run:
                Logger.info(
                    "Would scrub configure.py references in "
                    "docs/development/release-and-automation.md"
                )
            else:
                release_auto.write_text(new_content, encoding="utf-8")
                Logger.success(
                    "Removed configure.py references from "
                    "docs/development/release-and-automation.md"
                )
            changed.append(release_auto)

    return sorted(changed)


def regenerate_doc_toc(root: Path | None = None, dry_run: bool = False) -> bool:
    """Re-run ``tools/generate_doc_toc.py`` to rebuild ``docs/TABLE_OF_CONTENTS.md``.

    The TOC is driven from the surviving ``docs/`` tree, so once
    ``docs/template/`` is deleted in :class:`CleanupMode.ALL`, simply
    re-running the generator naturally drops every stale ``template/*.md``
    reference in one pass — much safer than a per-line regex strip, which
    would leave behind any future broken ``template/*.md`` link the regex
    didn't anticipate.

    The generator script returns exit ``0`` (no change) or ``1`` (changes
    written); both are treated as success. Anything else is logged as a
    warning and treated as a failure.

    Args:
        root: Project root directory (defaults to cwd).
        dry_run: If True, report what would be regenerated but do not invoke
            the subprocess.

    Returns:
        True if the TOC was (or would be) regenerated; False if the
        generator/TOC files are missing, the subprocess failed, or no
        changes were needed.
    """
    if root is None:
        root = Path.cwd()
    script = root / "tools" / "generate_doc_toc.py"
    toc = root / "docs" / "TABLE_OF_CONTENTS.md"
    if not script.is_file() or not toc.is_file():
        return False
    if dry_run:
        Logger.info("Would regenerate docs/TABLE_OF_CONTENTS.md")
        return True

    import subprocess  # nosec B404 - local import for invoking generate_doc_toc.py

    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    # generate_doc_toc.py returns 0 (no change) or 1 (changes written); both
    # are success. Anything else is a real failure.
    if result.returncode not in (0, 1):
        Logger.warning(
            f"TOC regeneration failed (exit {result.returncode}): {result.stderr.strip()}"
        )
        return False
    if result.returncode == 1:
        Logger.success("Regenerated docs/TABLE_OF_CONTENTS.md")
        return True
    return False


def check_stale_template_references(
    root: Path | None = None,
) -> list[tuple[Path, int, str]]:
    """Scan post-cleanup docs and README for known template-only markers.

    A warn-only post-cleanup sweep. Surfaces any future regression of the
    #469 / #474 bug class (stale references to template-only files that
    survive the scrubber) in the wizard transcript instead of waiting for a
    manual grep. Catches arbitrary docs files, not just the targets handled
    explicitly by :func:`scrub_template_references`.

    The marker list (:data:`_STALE_TEMPLATE_MARKERS`) is conservative — every
    marker references a path that is guaranteed to be broken once the cleanup
    deletes its target.

    Args:
        root: Project root directory (defaults to cwd).

    Returns:
        List of ``(path, line_no, line_content)`` tuples for any survivors.
        Empty list when no stale references are found. The caller decides
        what to do with the result; this function never raises and never
        modifies any files.
    """
    if root is None:
        root = Path.cwd()

    survivors: list[tuple[Path, int, str]] = []
    candidates: list[Path] = []
    docs_dir = root / "docs"
    if docs_dir.is_dir():
        candidates.extend(sorted(docs_dir.rglob("*.md")))
    readme = root / "README.md"
    if readme.is_file():
        candidates.append(readme)

    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            if any(marker in line for marker in _STALE_TEMPLATE_MARKERS):
                survivors.append((path, line_no, line))
    return survivors


def cleanup_template_files(
    mode: CleanupMode,
    root: Path | None = None,
    dry_run: bool = False,
) -> CleanupResult:
    """Remove template-specific files from the project.

    Args:
        mode: Cleanup mode (SETUP_ONLY or ALL)
        root: Project root directory (defaults to cwd)
        dry_run: If True, only report what would be deleted

    Returns:
        CleanupResult with details of what was deleted
    """
    if root is None:
        root = Path.cwd()

    deleted_files: list[Path] = []
    deleted_dirs: list[Path] = []
    failed: list[tuple[Path, str]] = []

    # Get files and directories to delete
    files_to_delete = get_files_to_delete(mode, root)
    dirs_to_delete = get_dirs_to_delete(mode, root)

    if not files_to_delete and not dirs_to_delete:
        Logger.info("No template files found to clean up")
        return CleanupResult([], [], [], False)

    # Report what will be deleted
    if files_to_delete:
        Logger.step(f"{'Would delete' if dry_run else 'Deleting'} files:")
        for file_path in files_to_delete:
            rel_path = file_path.relative_to(root)
            print(f"  - {rel_path}")

    if dirs_to_delete:
        Logger.step(f"{'Would delete' if dry_run else 'Deleting'} directories:")
        for dir_path in dirs_to_delete:
            rel_path = dir_path.relative_to(root)
            print(f"  - {rel_path}/")

    if dry_run:
        # Check mkdocs update
        mkdocs_would_update = False
        if mode == CleanupMode.ALL:
            mkdocs_would_update = update_mkdocs_nav(root, dry_run=True)
            # Also report any scrub targets; the return value is discarded
            # here because CleanupResult has no field for it.
            scrub_template_references(root, dry_run=True)
            # Mirror the live path's TOC regenerate step (read-only under
            # dry_run). check_stale_template_references is read-only too,
            # but it's only called in the live path because dry_run already
            # promises no writes — running it here would just be noise.
            regenerate_doc_toc(root, dry_run=True)
        return CleanupResult(files_to_delete, dirs_to_delete, [], mkdocs_would_update)

    # Delete files
    for file_path in files_to_delete:
        try:
            file_path.unlink()
            deleted_files.append(file_path)
        except OSError as e:
            failed.append((file_path, str(e)))

    # Delete directories (only for ALL mode, and only after files are deleted)
    # Sort by depth (deepest first) to avoid deleting parent before child
    for dir_path in sorted(dirs_to_delete, key=lambda p: len(p.parts), reverse=True):
        try:
            if dir_path.exists():
                shutil.rmtree(dir_path)
                deleted_dirs.append(dir_path)
        except OSError as e:
            failed.append((dir_path, str(e)))

    # Update mkdocs.yml if removing all template files
    mkdocs_updated = False
    if mode == CleanupMode.ALL:
        mkdocs_updated = update_mkdocs_nav(root, dry_run=False)
        # Scrub user-visible references (pyproject.toml, README.md,
        # doit-tasks-reference.md, github-repository-settings.md,
        # release-and-automation.md) that still point at now-deleted files.
        scrub_template_references(root, dry_run=False)
        # Regenerate the TOC from the surviving docs/ tree so any broken
        # template/*.md links naturally drop out (no per-line regex needed).
        regenerate_doc_toc(root, dry_run=False)
        # Warn-only regression sweep: surface any stale template references
        # that survived the targeted scrubs above. Catches future drift in
        # arbitrary docs files, not just the ones explicitly handled.
        stale = check_stale_template_references(root)
        if stale:
            Logger.warning(f"Stale template references survived cleanup ({len(stale)} hits):")
            for path, line_no, content in stale:
                rel = path.relative_to(root) if path.is_relative_to(root) else path
                print(f"  - {rel}:{line_no}: {content.strip()}")

    # Report results
    if deleted_files:
        Logger.success(f"Deleted {len(deleted_files)} files")
    if deleted_dirs:
        Logger.success(f"Deleted {len(deleted_dirs)} directories")
    if failed:
        Logger.warning(f"Failed to delete {len(failed)} items:")
        for path, error in failed:
            rel_path = path.relative_to(root) if path.is_relative_to(root) else path
            print(f"  - {rel_path}: {error}")

    return CleanupResult(deleted_files, deleted_dirs, failed, mkdocs_updated)


def prompt_cleanup(root: Path | None = None) -> CleanupMode | None:
    """Interactively prompt user for cleanup mode.

    Args:
        root: Project root directory (defaults to cwd)

    Returns:
        Selected CleanupMode, or None if user chose to keep all files
    """
    if root is None:
        root = Path.cwd()

    print()
    Logger.header("Template File Cleanup")
    print()
    print("Would you like to remove template-specific files?")
    print()
    print("  [1] Remove setup files only (keep update checking)")
    print("      Removes: bootstrap.py, setup_repo.py")
    print("      Keeps: manage.py, check_template_updates.py (for future updates)")
    print()
    print("  [2] Remove all template files (no future update checking)")
    print("      Removes: All template tools and documentation")
    print("      Warning: You won't be able to check for template updates")
    print()
    print("  [3] Keep all files")
    print()

    while True:
        try:
            choice = input("Select option [1-3]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None

        if choice == "1":
            return CleanupMode.SETUP_ONLY
        elif choice == "2":
            return CleanupMode.ALL
        elif choice == "3":
            return None
        else:
            print("Invalid option. Please enter 1, 2, or 3.")


def main() -> int:
    """Main entry point for standalone usage."""
    import argparse

    parser = argparse.ArgumentParser(description="Remove template-specific files from the project.")
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Remove setup files only (keep update checking)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Remove all template files (no future update checking)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting",
    )

    args = parser.parse_args()

    # Determine mode. Annotated up front because ``prompt_cleanup()`` in the
    # else-branch returns ``CleanupMode | None``; without this, mypy infers
    # ``CleanupMode`` from the first branch and then reports the ``is None``
    # guard below as unreachable.
    mode: CleanupMode | None
    if args.setup and args.all:
        Logger.error("Cannot specify both --setup and --all")
        return 1
    elif args.setup:
        mode = CleanupMode.SETUP_ONLY
    elif args.all:
        mode = CleanupMode.ALL
    else:
        # Interactive mode
        mode = prompt_cleanup()
        if mode is None:
            Logger.info("Keeping all template files")
            return 0

    # Perform cleanup
    result = cleanup_template_files(mode, dry_run=args.dry_run)

    if args.dry_run:
        Logger.info("Dry run complete. No files were deleted.")

    return 0 if not result.failed else 1


if __name__ == "__main__":
    sys.exit(main())
