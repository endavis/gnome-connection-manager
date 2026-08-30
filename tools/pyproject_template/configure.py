#!/usr/bin/env python3
"""Interactive/non-interactive script to configure the project template.

Modes:
- Interactive (default): prompts for values with defaults pulled from pyproject.toml.
- Auto: use values from pyproject.toml (and git remote) with no prompts (--auto).
Optional: skip final confirmation with --yes.
"""

import argparse
import shutil
import subprocess  # nosec B404
import sys
from pathlib import Path

# Support running as script or as module
_script_dir = Path(__file__).parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

# Import shared utilities
from utils import (  # noqa: E402
    FILES_TO_UPDATE,
    Logger,
    get_first_author,
    get_git_config,
    load_toml_file,
    parse_github_url,
    prompt,
    prompt_confirm,
    remove_template_owned_tests,
    update_file,
    update_test_files,
    validate_email,
    validate_package_name,
    validate_pypi_name,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Configure the project template.")
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Use values from pyproject.toml (and git remote) without prompts.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt (useful with --auto).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes.",
    )
    return parser.parse_args(argv)


def find_backup_pyproject() -> Path | None:
    """Find the most recent backup pyproject.toml from migration helper (in tmp/)."""
    candidates = []
    for backup_dir in Path("tmp").glob("template-migration-backup-*"):
        pyproject = backup_dir / "pyproject.toml"
        if pyproject.exists():
            candidates.append(pyproject)
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def guess_github_user(pyproject_data: dict[str, object]) -> str:
    """Get GitHub user from pyproject data or git remote."""
    # First try from pyproject.toml repository URL
    project = pyproject_data.get("project", {})
    urls = project.get("urls", {}) if isinstance(project, dict) else {}
    repo_url = urls.get("Repository", "") if isinstance(urls, dict) else ""
    github_user: str
    github_user, _ = parse_github_url(str(repo_url))
    if github_user:
        return github_user

    # Fallback: try git remote origin
    remote_url = get_git_config("remote.origin.url")
    github_user, _ = parse_github_url(remote_url)
    return github_user


def read_readme_title(readme_path: Path) -> str:
    if not readme_path.exists():
        return ""
    for line in readme_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            return line.lstrip("#").strip()
    return ""


def load_defaults(pyproject_path: Path) -> dict[str, str]:
    data = load_toml_file(pyproject_path)
    project = data.get("project", {})
    project_name = project.get("name", "")
    package_name = validate_package_name(project_name) if project_name else ""
    pypi_name = validate_pypi_name(project_name) if project_name else ""
    description = project.get("description") or read_readme_title(Path("README.md"))
    author_name, author_email = get_first_author(data)
    github_user = guess_github_user(data)

    # If current pyproject still has template placeholders, try backup for real values
    backup_pyproject = find_backup_pyproject()
    if backup_pyproject:
        backup_data = load_toml_file(backup_pyproject)
        b_project = backup_data.get("project", {})

        def not_placeholder(val: str, placeholders: set[str]) -> bool:
            return bool(val) and val not in placeholders

        if not_placeholder(project_name, {"package_name", "Package Name", ""}):
            pass
        else:
            project_name = b_project.get("name", project_name)
            package_name = validate_package_name(project_name) if project_name else package_name
            pypi_name = validate_pypi_name(project_name) if project_name else pypi_name

        if not_placeholder(description, {"A short description of your package", ""}):
            pass
        else:
            description = b_project.get("description", description)

        b_author_name, b_author_email = get_first_author(backup_data)
        if not_placeholder(author_name, {"Your Name", ""}):
            pass
        else:
            author_name = b_author_name or author_name
        if not_placeholder(author_email, {"your.email@example.com", ""}):
            pass
        else:
            author_email = b_author_email or author_email

        if not_placeholder(github_user, {"username", ""}):
            pass
        else:
            github_user = guess_github_user(backup_data) or github_user

    return {
        "project_name": project_name,
        "package_name": package_name,
        "pypi_name": pypi_name,
        "description": description,
        "author_name": author_name,
        "author_email": author_email,
        "github_user": github_user,
    }


def require(value: str, label: str) -> str:
    if value:
        return value
    raise SystemExit(
        f"❌ Missing required value for {label} (supply in pyproject.toml or via prompt)."
    )


def _git_has_version_tag() -> bool:
    """Return ``True`` if the current repo has at least one ``v*`` tag."""
    result = subprocess.run(  # nosec B603 B607
        ["git", "tag", "--list", "v*"],
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(result.stdout.strip())


def _git_root_commit() -> str | None:
    """Return the root commit SHA of the current repo, or ``None`` if unavailable.

    Returns ``None`` if not inside a git repo, the repo has no commits, or the
    ``git rev-list`` call fails for any other reason.
    """
    result = subprocess.run(  # nosec B603 B607
        ["git", "rev-list", "--max-parents=0", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return lines[0] if lines else None


def seed_baseline_tag() -> None:
    """Seed a ``v0.0.0`` tag on the root commit if no ``v*`` tag exists.

    Gives commitizen an anchor to compute pre-release versions against. Without
    it, ``doit release --prerelease=alpha`` refuses on a tagless repo (guard
    from issue #448). Idempotent: skips if any ``v*`` tag already exists. Skips
    silently (with a visible message) if not inside a git repo or if there are
    no commits yet, so the user can run ``git init && git commit`` first and
    seed manually with ``git tag v0.0.0 <root-commit>``.
    """
    if not Path(".git").exists():
        Logger.info(
            "Skipping v0.0.0 baseline tag: not a git repo yet (run `git init` "
            "and commit first, then seed manually: "
            "`git tag v0.0.0 <root-commit>`)"
        )
        return

    if _git_has_version_tag():
        Logger.info("Skipping v0.0.0 baseline tag: a v* tag already exists")
        return

    root = _git_root_commit()
    if root is None:
        Logger.info(
            "Skipping v0.0.0 baseline tag: no commits yet "
            "(seed manually after your first commit: `git tag v0.0.0 <root-commit>`)"
        )
        return

    result = subprocess.run(  # nosec B603 B607
        ["git", "tag", "v0.0.0", root],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        print(f"  ✓ Seeded baseline tag v0.0.0 on root commit {root[:7]}")
        Logger.info("   → push with `git push origin v0.0.0` when ready")
    else:
        Logger.warning(f"Could not create v0.0.0 tag: {result.stderr.strip() or 'unknown error'}")


def run_configure(
    auto: bool = False,
    yes: bool = False,
    dry_run: bool = False,
    defaults: dict[str, str] | None = None,
) -> int:
    """Run the configuration wizard.

    Args:
        auto: Use values from pyproject.toml without prompts.
        yes: Skip confirmation prompt.
        dry_run: Show what would be done without making changes.
        defaults: Pre-loaded default values (if None, loads from pyproject.toml).

    Returns:
        Exit code (0 for success, non-zero for error).
    """
    # Ensure script is run from project root
    if not Path("pyproject.toml").exists():
        Logger.error("Please run this script from the project root directory.")
        return 1

    if defaults is None:
        defaults = load_defaults(Path("pyproject.toml"))

    Logger.header("Python Project Template Configuration")
    print("\nThis script will help you set up your new Python project.\n")

    # Gather project information
    Logger.step("Project Information")

    if auto:
        project_name = require(defaults["project_name"], "[project].name")
        package_name = require(defaults["package_name"], "package name")
        pypi_name = require(defaults["pypi_name"], "PyPI name")
        description = require(defaults["description"], "description")
        author_name = require(defaults["author_name"], "author name")
        author_email = require(defaults["author_email"], "author email")
        if not validate_email(author_email):
            raise SystemExit("❌ Invalid email format in pyproject.toml")
        github_user = require(
            defaults["github_user"],
            "GitHub user (from Repository URL or git remote)",
        )
    else:
        project_name = prompt(
            "Project name (human-readable)",
            defaults["project_name"] or "My Awesome Project",
        )

        suggested_package = validate_package_name(project_name)
        suggested_pypi = validate_pypi_name(project_name)

        package_name = prompt("Python package name", defaults["package_name"] or suggested_package)
        package_name = validate_package_name(package_name)

        pypi_name = prompt("PyPI package name", defaults["pypi_name"] or suggested_pypi)
        pypi_name = validate_pypi_name(pypi_name)

        description = prompt(
            "Short description",
            defaults["description"] or "A short description of your package",
        )

        author_name = prompt("Author name", defaults["author_name"] or "Your Name")

        while True:
            author_email = prompt(
                "Author email",
                defaults["author_email"] or "your.email@example.com",
            )
            if validate_email(author_email):
                break
            Logger.warning("Invalid email format. Please try again.")

        github_user = prompt("GitHub username", defaults["github_user"] or "username")

    # Confirm configuration
    Logger.header("Configuration Summary")
    print(f"Project Name:     {project_name}")
    print(f"Package Name:     {package_name}")
    print(f"PyPI Name:        {pypi_name}")
    print(f"Description:      {description}")
    print(f"Author:           {author_name} <{author_email}>")
    print(f"GitHub:           {github_user}")
    # Stated, not asked. Dependabot is part of the template's automation
    # surface -- .github/dependabot.yml plus two workflows, a docs page and
    # their tests -- and ships with every project.
    print("Dependabot:       Enabled (ships with the template)")
    print("━" * 60)

    if not yes and not prompt_confirm("\nProceed with configuration?"):
        Logger.warning("Configuration cancelled.")
        return 1

    if dry_run:
        Logger.info("Dry run mode - no changes will be made")
        Logger.success("Configuration validated successfully (dry run)")
        return 0

    Logger.step("Configuring project...")

    # Define replacements
    # IMPORTANT: Longer/Specific replacements must come before shorter substrings
    replacements = {
        # Marker tokens (unambiguous, used in prose files). These take
        # priority because ``update_file()`` treats them as blind replaces
        # regardless of surrounding context.
        "__PACKAGE_NAME__": package_name,
        "__PYPI_NAME__": pypi_name,
        "__PROJECT_NAME__": project_name,
        "__GH_OWNER__": github_user,
        "__AUTHOR_NAME__": author_name,
        "__AUTHOR_EMAIL__": author_email,
        "__DESCRIPTION__": description,
        "__REPO_URL__": f"https://github.com/{github_user}/{package_name}",
        "__REPO_SLUG__": f"{github_user}/{package_name}",
        # URLs (Specific matches first). Retained for runtime-critical files
        # (pyproject.toml, workflows, LICENSE, mkdocs.yml, dodo.py, .envrc,
        # .pre-commit-config.yaml) that keep literal placeholders, and for
        # downstream consumer projects that have not yet migrated.
        "https://github.com/username/package_name": f"https://github.com/{github_user}/{package_name}",
        "https://github.com/original-owner/package_name": f"https://github.com/{github_user}/{package_name}",
        "https://codecov.io/gh/username/package_name": f"https://codecov.io/gh/{github_user}/{package_name}",
        "https://codecov.io/gh/username/package_name/branch/main/graph/badge.svg": f"https://codecov.io/gh/{github_user}/{package_name}/branch/main/graph/badge.svg",
        "https://github.com/username/package_name/actions/workflows/ci.yml/badge.svg": f"https://github.com/{github_user}/{package_name}/actions/workflows/ci.yml/badge.svg",
        "https://github.com/username": f"https://github.com/{github_user}",
        # GitHub Pages URL (mkdocs.yml)
        "https://username.github.io/package_name": f"https://{github_user}.github.io/{package_name}",
        # Files and Paths
        "package-name.svg": f"{pypi_name}.svg",
        "package-name/": f"{pypi_name}/",
        # Repo name pattern (mkdocs.yml) - must come before general package_name
        "username/package_name": f"{github_user}/{package_name}",
        # General Placeholders (Substrings). Python files receive
        # word-boundary protection from ``update_file()`` so identifier
        # substrings (e.g. ``validate_package_name``) survive.
        "package_name": package_name,
        "package-name": pypi_name,
        "Package Name": project_name,
        "A short description of your package": description,
        "Your Name": author_name,
        "your.email@example.com": author_email,
        # GitHub template placeholders (for issue templates, etc.)
        "{owner}": github_user,
        "{repo}": package_name,
        # Contact email placeholders
        "security@example.com": author_email,
        "[INSERT CONTACT EMAIL]": author_email,
        # Note: "username" is NOT replaced globally to avoid breaking code
        # variables (e.g. in extensions.md)
    }

    # Install the consumer README before placeholder replacement.
    #
    # README.md in the template is the repository's landing page: it describes
    # the template itself and carries working badges, so browsing the repo does
    # not show a placeholder title and four broken badge images (#697).
    # README.template.md is the README the spawned project actually wants.
    # Moving it into place here means it is then picked up by the
    # FILES_TO_UPDATE pass below like any other file.
    consumer_readme = Path("README.template.md")
    if consumer_readme.exists():
        print("  ✓ Installing README.template.md as README.md")
        consumer_readme.replace(Path("README.md"))

    # Update files (using shared constant from utils.py)
    for file_path in FILES_TO_UPDATE:
        path = Path(file_path)
        if path.exists():
            print(f"  ✓ Updating {file_path}")
            update_file(path, replacements)

    # Update docs directory
    docs_dir = Path("docs")
    if docs_dir.exists():
        print("  ✓ Updating documentation files")
        for md_file in docs_dir.rglob("*.md"):
            update_file(md_file, replacements)

    # Update issue/PR templates
    issue_template_dir = Path(".github/ISSUE_TEMPLATE")
    if issue_template_dir.exists():
        print("  ✓ Updating issue templates")
        for template_file in issue_template_dir.rglob("*"):
            if template_file.suffix in {".md", ".yml", ".yaml"}:
                update_file(template_file, replacements)

    # Update examples directory
    examples_dir = Path("examples")
    if examples_dir.exists():
        print("  ✓ Updating example files")
        for example_file in examples_dir.rglob("*"):
            if example_file.suffix in {".py", ".md"}:
                update_file(example_file, replacements)

    # Rename package directory
    old_package_dir = Path("src/package_name")
    new_package_dir = Path(f"src/{package_name}")

    if old_package_dir.exists() and old_package_dir != new_package_dir:
        if new_package_dir.exists():
            print(f"  ⚠️  src/{package_name} already exists; skipping rename of src/package_name")
        else:
            print(f"  ✓ Renaming src/package_name → src/{package_name}")
            shutil.move(str(old_package_dir), str(new_package_dir))
    elif not old_package_dir.exists():
        print("  ⚠️  src/package_name not found; assuming code already relocated")

    # Update imports in renamed package
    if new_package_dir.exists():
        for py_file in new_package_dir.rglob("*.py"):
            update_file(py_file, replacements)

    # Update test files (limited replacements to preserve test data)
    test_dir = Path("tests")
    if test_dir.exists():
        print("  ✓ Updating test files")
        update_test_files(test_dir, package_name)

    # Shed template-only tests. This must shed exactly what `cleanup --setup`
    # sheds — ADR-9017 makes TEMPLATE_OWNED_TEST_FILES the single authoritative
    # list, and cleanup.py already consumes it.
    #
    # Removing the whole directory instead (as this did until #731) also deleted
    # the tests covering tools/doit/ and tools/hooks/ — code that ships to and
    # runs in the spawned project, and that the coverage gate in pyproject.toml
    # measures. A spawned project failed its first CI run at 33.98% against a
    # fail_under of 54.
    shed = remove_template_owned_tests(Path.cwd())
    if shed:
        print(f"  ✓ Removing {len(shed)} template-only test files")

    # Seed v0.0.0 baseline tag so `doit release --prerelease=alpha` works on the
    # first release (see issue #447). Idempotent and skipped gracefully when
    # there is no git repo or no commits yet.
    seed_baseline_tag()

    Logger.success("Configuration complete!")
    Logger.header("Next Steps")
    print("1. Review the changes: git diff")
    print("2. Initialize git repository: git init")
    print("3. Install dependencies: uv sync --all-extras --dev")
    print("4. Install pre-commit hooks: uv run doit pre_commit_install")
    # The bootstrap wizard (setup_repo.py) runs this automatically. The manual
    # route has to be told, or the project keeps a template management suite it
    # does not use (#731).
    print("5. Remove the template suite: uv run doit template_clean --all")
    print("6. Run tests: uv run pytest")
    print("7. Cut a prerelease (if desired): uv run doit release --prerelease=alpha")
    print("8. Start coding!")
    print("━" * 60)

    # Self-destruct
    print("\n🗑️  Removing configure.py (self-destruct)...")
    try:
        Path(__file__).unlink()
        Logger.success("configure.py removed")
    except Exception as e:
        Logger.warning(f"Could not remove configure.py: {e}")
        print("  → You can safely delete it manually")

    return 0


def main(argv: list[str] | None = None) -> int:
    """Main entry point for CLI usage."""
    args = parse_args(argv)
    return run_configure(
        auto=args.auto,
        yes=args.yes,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    print("This script should not be run directly.")
    print("Please use: python manage.py")
    sys.exit(1)
