#!/usr/bin/env python3
"""
Unified template management script with menu-driven interface.

Usage:
    # Interactive (default)
    python manage.py

    # Quick actions
    python manage.py create      # Create new project from template
    python manage.py configure   # Re-run configuration
    python manage.py check       # Check for template updates
    python manage.py repo        # Update repository settings
    python manage.py sync        # Mark as synced to latest template

    # Non-interactive
    python manage.py --yes       # Run recommended action non-interactively
    python manage.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Support running as script or as module
_script_dir = Path(__file__).parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

from check_template_updates import run_check_updates  # noqa: E402
from configure import load_defaults, run_configure  # noqa: E402
from settings import (  # noqa: E402
    PreflightWarning,
    ProjectContext,
    ProjectSettings,
    SettingsManager,
    TemplateState,
    get_template_commits_since,
    get_template_latest_commit,
)
from utils import Colors, Logger, prompt, validate_package_name  # noqa: E402

# Import cleanup utilities (optional - may not exist if already cleaned)
try:
    from cleanup import CleanupMode, cleanup_template_files, prompt_cleanup
except ImportError:
    CleanupMode = None
    cleanup_template_files = None
    prompt_cleanup = None


def print_banner() -> None:
    """Print the welcome banner."""
    print()
    print(f"{Colors.CYAN}pyproject-template{Colors.NC}")
    print()


def print_section(title: str) -> None:
    """Print a section header."""
    width = 60
    print(f"{Colors.BOLD}{'=' * width}{Colors.NC}")
    print(f"{Colors.BOLD}{title:^{width}}{Colors.NC}")
    print(f"{Colors.BOLD}{'=' * width}{Colors.NC}")
    print()


def print_warnings(warnings: list[PreflightWarning]) -> None:
    """Print preflight warnings."""
    if not warnings:
        return

    print_section("Warnings")
    for warning in warnings:
        print(f"  {Colors.YELLOW}!{Colors.NC} {warning.message}")
        if warning.suggestion:
            print(f"    {Colors.CYAN}({warning.suggestion}){Colors.NC}")
    print()


def print_settings(settings: ProjectSettings, context: ProjectContext) -> None:
    """Print detected settings."""
    print_section("Detected Settings")

    print(f"  Project name:      {settings.project_name or '(not set)'}")
    print(f"  Package name:      {settings.package_name or '(not set)'}")
    print(f"  PyPI name:         {settings.pypi_name or '(not set)'}")
    if settings.author_name or settings.author_email:
        author = f"{settings.author_name} <{settings.author_email}>"
    else:
        author = "(not set)"
    print(f"  Author:            {author}")
    if settings.github_user or settings.github_repo:
        github = f"{settings.github_user}/{settings.github_repo}"
    else:
        github = "(not set)"
    print(f"  GitHub:            {github}")
    print()

    # Context info
    if context.is_template_repo:
        print(f"  Context:           {Colors.CYAN}Template repository{Colors.NC}")
    elif context.is_existing_repo:
        print("  Context:           Existing repository")
    elif context.is_fresh_clone:
        print("  Context:           Fresh clone (needs setup)")
    else:
        print("  Context:           Not a git repository")
    print()


def print_template_status(
    template_state: TemplateState,
    latest_commit: tuple[str, str] | None,
    recent_commits: list[dict[str, str]] | None,
) -> None:
    """Print template sync status."""
    if template_state.is_synced() and template_state.commit:
        if latest_commit:
            latest_sha, _ = latest_commit
            if latest_sha[:12] == template_state.commit[:12]:
                print(
                    f"  Template status:   {Colors.GREEN}Up to date{Colors.NC} "
                    f"(synced: {template_state.commit_date})"
                )
            else:
                commits_behind = len(recent_commits) if recent_commits else "unknown"
                status = f"{Colors.YELLOW}{commits_behind} commits behind{Colors.NC}"
                print(f"  Template status:   {status} (last sync: {template_state.commit_date})")
                if recent_commits and len(recent_commits) > 0:
                    print()
                    print(f"  {Colors.CYAN}Recent changes:{Colors.NC}")
                    for commit in recent_commits[:5]:
                        msg = commit["message"][:50]
                        if len(commit["message"]) > 50:
                            msg += "..."
                        print(f"    - {msg}")
                    if len(recent_commits) > 5:
                        print(f"    ... and {len(recent_commits) - 5} more")
        else:
            print(f"  Template status:   Last sync: {template_state.commit_date}")
    else:
        print(f"  Template status:   {Colors.YELLOW}Never synced with template{Colors.NC}")
    print()


def get_recommended_action(
    context: ProjectContext,
    settings: ProjectSettings,
    template_state: TemplateState,
    latest_commit: tuple[str, str] | None,
    *,
    template_downloaded: bool,
) -> int | None:
    """Determine the recommended action based on context."""
    # No git repo - need to create new project
    if not context.has_git:
        return 1  # Create new project

    # Has git but placeholder values - need to configure
    if settings.has_placeholder_values():
        return 2  # Configure project

    # Template already downloaded and reviewed - recommend marking as synced
    if template_downloaded:
        return 5  # Mark as synced

    # Existing repo with outdated template
    if template_state.is_synced() and template_state.commit and latest_commit:
        latest_sha, _ = latest_commit
        if latest_sha[:12] != template_state.commit[:12]:
            return 3  # Check for updates

    # Existing repo but never synced - suggest checking updates
    if context.has_git and not template_state.is_synced():
        return 3  # Check for updates

    return None  # Up to date


def print_menu(recommended: int | None, dry_run: bool) -> None:
    """Print the menu options."""
    print(f"{Colors.BOLD}What would you like to do?{Colors.NC}")
    print()

    options = [
        (1, "Create new project from template"),
        (2, "Configure project"),
        (3, "Check for template updates"),
        (4, "Update repository settings"),
        (5, "Mark as synced to latest template"),
        (6, "Clean up template files"),
    ]

    for num, label in options:
        rec = f" {Colors.GREEN}<- recommended{Colors.NC}" if num == recommended else ""
        print(f"  [{num}] {label}{rec}")

    print()
    print("  [e] Edit settings")
    dry_status = "on" if dry_run else "off"
    print(f"  [d] Toggle dry-run (currently: {dry_status})")
    print("  [?] Help")
    print("  [q] Quit")
    print()


def print_help() -> None:
    """Print help text for menu options."""
    print()
    print(f"  {Colors.BOLD}[1] Create new project from template{Colors.NC}")
    print("      Create a new GitHub repo from the template, clone it,")
    print("      and run configuration (requires gh CLI authenticated)")
    print()
    print(f"  {Colors.BOLD}[2] Configure project{Colors.NC}")
    print("      Update placeholders in all files (project name, author,")
    print("      etc.) - run this after cloning the template")
    print()
    print(f"  {Colors.BOLD}[3] Check for template updates{Colors.NC}")
    print("      Compare your project against the latest template and")
    print("      selectively merge improvements (workflows, configs, etc.)")
    print()
    print(f"  {Colors.BOLD}[4] Update repository settings{Colors.NC}")
    print("      Configure GitHub repo settings, branch protection, labels")
    print("      (requires gh CLI authenticated)")
    print()
    print(f"  {Colors.BOLD}[5] Mark as synced to latest template{Colors.NC}")
    print("      After manually reviewing and applying template updates,")
    print("      mark your project as synced to the latest template commit")
    print()
    print(f"  {Colors.BOLD}[6] Clean up template files{Colors.NC}")
    print("      Remove template-specific files no longer needed:")
    print("      - Setup only: Remove bootstrap.py, setup_repo.py, etc.")
    print("      - All: Remove all template tools (no future update checking)")
    print()
    input("Press enter to return to menu...")


def edit_settings(manager: SettingsManager) -> None:
    """Allow user to edit settings interactively."""
    print()
    Logger.header("Edit Settings")
    print("Enter new values (press Enter to keep current value)")
    print()

    settings = manager.settings

    new_name = prompt("Project name", settings.project_name)
    if new_name:
        settings.project_name = new_name

    new_package = prompt("Package name", settings.package_name)
    if new_package:
        settings.package_name = new_package

    new_pypi = prompt("PyPI name", settings.pypi_name)
    if new_pypi:
        settings.pypi_name = new_pypi

    new_desc = prompt("Description", settings.description)
    if new_desc:
        settings.description = new_desc

    new_author = prompt("Author name", settings.author_name)
    if new_author:
        settings.author_name = new_author

    new_email = prompt("Author email", settings.author_email)
    if new_email:
        settings.author_email = new_email

    new_gh_user = prompt("GitHub user", settings.github_user)
    if new_gh_user:
        settings.github_user = new_gh_user

    new_gh_repo = prompt("GitHub repo", settings.github_repo)
    if new_gh_repo:
        settings.github_repo = new_gh_repo

    manager.save()


def run_action(
    action: int,
    manager: SettingsManager,
    dry_run: bool,
    *,
    yes: bool = False,
    cleanup_mode: str | None = None,
    show_excluded: bool = False,
    template_version: str | None = None,
) -> int:
    """Run the selected action."""
    if action == 1:
        return action_create_project(manager, dry_run, yes=yes)
    elif action == 2:
        return action_configure(manager, dry_run, yes=yes)
    elif action == 3:
        return action_check_updates(
            manager, dry_run, show_excluded=show_excluded, template_version=template_version
        )
    elif action == 4:
        return action_repo_settings(manager, dry_run)
    elif action == 5:
        return action_mark_synced(manager, dry_run, yes=yes)
    elif action == 6:
        return action_template_cleanup(manager, dry_run, yes=yes, cleanup_mode=cleanup_mode)
    else:
        Logger.error(f"Unknown action: {action}")
        return 1


def action_create_project(manager: SettingsManager, dry_run: bool, *, yes: bool = False) -> int:
    """Create a new project from the template."""
    del yes  # Kept for action_* signature uniformity; no confirmation prompts remain.
    Logger.header("Creating New Project from Template")

    settings = manager.settings

    if dry_run:
        Logger.info("Dry run: Would create new project")
        Logger.info(f"  - Create GitHub repo: {settings.github_user}/{settings.github_repo}")
        Logger.info("  - Clone from template")
        Logger.info("  - Run configuration")
        Logger.info("  - Save settings")
        return 0

    try:
        from setup_repo import RepositorySetup

        setup = RepositorySetup()

        # Set config from manager settings (skip gather_inputs)
        setup.config = {
            "repo_owner": settings.github_user,
            "repo_name": settings.github_repo,
            "repo_full": f"{settings.github_user}/{settings.github_repo}",
            "description": settings.description,
            "package_name": settings.package_name,
            "pypi_name": settings.pypi_name,
            "author_name": settings.author_name,
            "author_email": settings.author_email,
            "visibility": "public",  # Default to public
        }

        # Run individual setup steps (skip gather_inputs since we have config)
        setup.print_banner()
        setup.check_requirements()

        # Show configuration summary
        Logger.step("Configuration summary:")
        print(f"  Repository: {setup.config['repo_full']}")
        print(f"  Visibility: {setup.config['visibility']}")
        print(f"  Package name: {setup.config['package_name']}")
        print(f"  PyPI name: {setup.config['pypi_name']}")
        print(f"  Description: {setup.config['description']}")
        print(f"  Author: {setup.config['author_name']} <{setup.config['author_email']}>")
        print()

        # Create GitHub repo (no branch protection yet)
        setup.create_github_repository()
        setup.configure_repository_settings()

        # Clone and configure locally BEFORE branch protection
        setup.clone_repository()

        setup.configure_placeholders()
        setup.setup_development_environment()

        # Save and commit template state BEFORE branch protection rules
        project_dir = Path.cwd()
        latest = get_template_latest_commit()
        if latest:
            import subprocess  # nosec B404 - subprocess is required for git operations

            new_manager = SettingsManager(root=project_dir)
            new_manager.template_state.commit = latest[0]
            new_manager.template_state.commit_date = latest[1]
            new_manager.save()

            # Commit the settings file (use --no-verify to bypass pre-commit
            # hook that blocks commits to main - this is automated setup)
            subprocess.run(
                ["git", "add", ".config/pyproject_template/settings.toml"],
                cwd=project_dir,
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "commit",
                    "--no-verify",
                    "-m",
                    "chore: add template sync state",
                ],
                cwd=project_dir,
                check=True,
            )
            subprocess.run(["git", "push"], cwd=project_dir, check=True)

        # Now configure branch protection and other GitHub settings.
        # CodeQL scanning is NOT set up here: it runs from the committed
        # .github/workflows/codeql.yml workflow that was cloned with the repo.
        setup.configure_branch_protection()
        setup.replicate_labels()
        setup.enable_github_pages()

        setup.print_manual_steps()

        Logger.success(f"Project created at {project_dir}")

        return 0

    except Exception as e:
        Logger.error(f"Failed to create project: {e}")
        return 1


def action_check_updates(
    manager: SettingsManager,
    dry_run: bool,
    *,
    show_excluded: bool = False,
    template_version: str | None = None,
) -> int:
    """Check for template updates (comparison only, does not modify files).

    `template_version` pins which template snapshot the project is compared
    against. Without it the latest release is resolved from the GitHub API, and
    if that call fails the comparison silently falls back to `main` -- so a run
    that looks like "latest release" can be against unreleased code (#779).
    """
    Logger.header("Checking for Template Updates")

    result = run_check_updates(
        template_version=template_version,
        skip_changelog=True,
        keep_template=True,  # Keep template so user can run diff commands
        dry_run=dry_run,
        show_excluded=show_excluded,
    )

    # Show commit history link if we have a sync point (after the review section)
    latest = get_template_latest_commit()
    if manager.template_state.commit and latest and latest[0] != manager.template_state.commit:
        old_commit = manager.template_state.commit
        new_commit = latest[0]
        print()
        Logger.info("View template commit history since last sync:")
        print(
            f"  https://github.com/endavis/pyproject-template/compare/{old_commit}...{new_commit}"
        )

    # Save commit info to template directory for later sync
    if latest and not dry_run:
        template_dir = Path("tmp/extracted/pyproject-template-main")
        if template_dir.exists():
            commit_file = template_dir / ".template_commit"
            commit_file.write_text(f"{latest[0]}\n{latest[1]}\n", encoding="utf-8")
            print()
            Logger.info("After reviewing changes, use option [5] to mark as synced.")

    # Note: This only shows differences, it doesn't update files.
    # Template state is NOT updated here - only when user runs "Mark as synced".

    return int(result)


def action_configure(manager: SettingsManager, dry_run: bool, *, yes: bool = False) -> int:
    """Re-run configuration."""
    Logger.header("Running Configuration")

    # Prepare defaults from current settings
    defaults = {
        "project_name": manager.settings.project_name,
        "package_name": manager.settings.package_name,
        "pypi_name": manager.settings.pypi_name,
        "description": manager.settings.description,
        "author_name": manager.settings.author_name,
        "author_email": manager.settings.author_email,
        "github_user": manager.settings.github_user,
    }

    # Merge with pyproject.toml defaults
    pyproject_defaults = load_defaults(Path("pyproject.toml"))
    for key, value in pyproject_defaults.items():
        if not defaults.get(key):
            defaults[key] = value

    return int(
        run_configure(
            auto=yes,
            yes=yes,
            dry_run=dry_run,
            defaults=defaults,
        )
    )


def action_repo_settings(manager: SettingsManager, dry_run: bool) -> int:
    """Update repository settings."""
    Logger.header("Updating Repository Settings")

    if dry_run:
        Logger.info("Dry run: Would configure GitHub repository settings")
        Logger.info("  - Repository settings (description, features)")
        Logger.info("  - Branch protection rulesets")
        Logger.info("  - Labels")
        Logger.info("  - GitHub Pages")
        return 0

    # Import repo_settings module for repository configuration
    try:
        from repo_settings import update_all_repo_settings

        repo_full = f"{manager.settings.github_user}/{manager.settings.github_repo}"

        success = update_all_repo_settings(
            repo_full=repo_full,
            description=manager.settings.description or "",
        )

        if success:
            Logger.success("Repository settings updated")
            return 0
        else:
            Logger.warning("Some repository settings may not have been updated")
            return 0  # Partial success is still success

    except Exception as e:
        Logger.error(f"Failed to update repository settings: {e}")
        return 1


def action_mark_synced(manager: SettingsManager, dry_run: bool, *, yes: bool = False) -> int:
    """Mark project as synced to reviewed template commit."""
    import shutil
    import subprocess  # nosec B404 - subprocess is required for git operations

    Logger.header("Mark as Synced to Template")

    # Check for downloaded template with commit info
    template_dir = Path("tmp/extracted/pyproject-template-main")
    commit_file = template_dir / ".template_commit"

    if not commit_file.exists():
        Logger.error("No reviewed template found.")
        Logger.info("Run option [3] 'Check for template updates' first to review changes.")
        return 1

    # Read commit info from the reviewed template
    lines = commit_file.read_text(encoding="utf-8").strip().split("\n")
    if len(lines) < 2:
        Logger.error("Invalid commit file format")
        return 1

    new_commit, new_date = lines[0], lines[1]
    current_commit = manager.template_state.commit

    if current_commit == new_commit:
        Logger.success(f"Already synced to this commit ({new_commit})")
        # Clean up template directory
        if template_dir.exists():
            shutil.rmtree(template_dir.parent)
            Logger.info("Cleaned up template directory")
        return 0

    print(f"Current sync point:  {current_commit or 'Not set'}")
    print(f"Reviewed template:   {new_commit} ({new_date})")
    print()

    if dry_run:
        Logger.info(f"Dry run: Would mark as synced to {new_commit}")
        return 0

    # Confirm with user (skip when yes=True to auto-confirm)
    if not yes:
        confirm = prompt(f"Mark as synced to {new_commit}?", "Y")
        if confirm.lower() not in ("y", "yes", ""):
            Logger.warning("Cancelled")
            return 0

    # Update template state
    manager.update_template_state(new_commit, new_date)

    # Commit the settings file if there are changes
    settings_file = ".config/pyproject_template/settings.toml"
    try:
        subprocess.run(["git", "add", settings_file], check=True)

        # Check if there are staged changes to commit
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            capture_output=True,
        )
        if result.returncode != 0:
            # There are changes to commit
            subprocess.run(
                [
                    "git",
                    "commit",
                    "--no-verify",
                    "-m",
                    f"chore: sync template state to {new_commit}",
                ],
                check=True,
            )
            subprocess.run(["git", "push"], check=True)
            Logger.success(f"Marked as synced to {new_commit}")
        else:
            # Settings file exists but wasn't committed (maybe already staged)
            Logger.success(f"Marked as synced to {new_commit}")
            print()
            print(f"{Colors.BOLD}{Colors.YELLOW}*** IMPORTANT ***{Colors.NC}")
            print(f"{Colors.BOLD}Don't forget to commit the settings file:{Colors.NC}")
            print()
            print("  # 1. Create an issue")
            print("  doit issue --type=chore --title='Sync template state'")
            print()
            print("  # 2. Create branch, commit, and push")
            print("  git checkout -b chore/<issue#>-sync-template-state")
            print(f"  git add {settings_file}")
            print(f"  git commit -m 'chore: sync template state to {new_commit[:12]}'")
            print("  git push -u origin HEAD")
            print()
            print("  # 3. Create PR and merge")
            print("  doit pr --title='chore: sync template state'")
            print()
    except subprocess.CalledProcessError as e:
        Logger.error(f"Failed to commit: {e}")
        return 1

    # Clean up template directory
    if template_dir.exists():
        shutil.rmtree(template_dir.parent)
        Logger.info("Cleaned up template directory")

    return 0


def action_template_cleanup(
    manager: SettingsManager,
    dry_run: bool,
    *,
    yes: bool = False,
    cleanup_mode: str | None = None,
) -> int:
    """Clean up template-specific files."""
    Logger.header("Template File Cleanup")

    if prompt_cleanup is None or cleanup_template_files is None:
        Logger.error("Cleanup module not available (may have been removed already)")
        return 1

    if dry_run:
        Logger.info("Dry run: Would prompt for cleanup mode and show files to delete")
        return 0

    mode = None

    if cleanup_mode:
        # CLI-specified mode (cleanup module is guaranteed available after guard above)
        from cleanup import CleanupMode as CleanupModeEnum

        mode_map = {"setup": CleanupModeEnum.SETUP_ONLY, "all": CleanupModeEnum.ALL}
        mode = mode_map.get(cleanup_mode)
        if mode is None:
            Logger.error(f"Invalid cleanup mode: {cleanup_mode}. Use 'setup' or 'all'.")
            return 1
    elif yes:
        # Non-interactive without explicit mode: skip cleanup (safer default)
        Logger.info("Non-interactive mode: skipping cleanup (use --cleanup-mode to specify)")
        return 0
    else:
        # Interactive prompt
        mode = prompt_cleanup()
        if mode is None:
            Logger.info("Keeping all template files")
            return 0

    # Perform cleanup
    result = cleanup_template_files(mode, dry_run=False)

    if result.failed:
        Logger.warning("Some files could not be deleted")
        return 1

    Logger.success("Template cleanup complete")
    return 0


def offer_cleanup_prompt(*, yes: bool = False) -> None:
    """Offer to clean up template files after successful setup.

    This is called after "Create new project" or "Configure project" completes.
    """
    if prompt_cleanup is None or cleanup_template_files is None:
        return  # Cleanup module not available

    if yes:
        return  # Non-interactive mode: skip cleanup

    print()
    response = prompt("Would you like to clean up template-specific files? (y/N)", "n")
    if response.lower() in ("y", "yes"):
        mode = prompt_cleanup()
        if mode is not None:
            cleanup_template_files(mode, dry_run=False)


def prompt_initial_settings(manager: SettingsManager) -> None:
    """Prompt for settings if none are configured."""
    if manager.settings.is_configured():
        return

    print_banner()
    print_section("Initial Setup")
    print("No project settings found. Let's set them up.\n")

    settings = manager.settings

    settings.project_name = prompt("Project name", settings.project_name) or settings.project_name

    # Auto-derive package_name (lowercase, underscores) and pypi_name (lowercase, hyphens)
    default_package = validate_package_name(settings.project_name)
    default_pypi = settings.project_name.lower().replace("_", "-")

    # Let user confirm/override package name with PEP 8 validation
    while True:
        package_input = prompt("Package name (PEP 8: lowercase, underscores only)", default_package)
        if not package_input:
            package_input = default_package

        # Validate PEP 8 compliance
        valid_name = validate_package_name(package_input)
        if package_input == valid_name:
            settings.package_name = package_input
            break
        else:
            Logger.warning(f"'{package_input}' is not PEP 8 compliant. Suggested: '{valid_name}'")
            # Offer the corrected version as new default
            default_package = valid_name

    settings.pypi_name = default_pypi
    settings.description = prompt("Description", settings.description) or settings.description
    settings.author_name = prompt("Author name", settings.author_name) or settings.author_name
    settings.author_email = prompt("Author email", settings.author_email) or settings.author_email
    settings.github_user = prompt("GitHub user", settings.github_user) or settings.github_user
    # Default github_repo to project_name
    settings.github_repo = settings.project_name

    # Don't save yet - settings are saved after setup completes in the correct directory
    # Clear warnings since we just collected settings
    manager.warnings = []
    print()


def interactive_menu(manager: SettingsManager, dry_run: bool = False, *, yes: bool = False) -> int:
    """Run the interactive menu loop."""
    # Prompt for initial settings if not configured
    prompt_initial_settings(manager)

    while True:
        print_banner()

        # Fetch latest template info
        latest_commit = get_template_latest_commit()
        recent_commits = None
        if manager.template_state.is_synced() and manager.template_state.commit and latest_commit:
            recent_commits = get_template_commits_since(manager.template_state.commit)

        # Display information
        print_warnings(manager.warnings)
        print_settings(manager.settings, manager.context)
        print_template_status(manager.template_state, latest_commit, recent_commits)

        # Get recommended action
        recommended = get_recommended_action(
            manager.context,
            manager.settings,
            manager.template_state,
            latest_commit,
            template_downloaded=Path(
                "tmp/extracted/pyproject-template-main/.template_commit"
            ).exists(),
        )

        # Show menu
        print_menu(recommended, dry_run)

        # Get user input
        try:
            choice = input("Select option: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if choice == "q":
            return 0
        elif choice == "?":
            print_help()
        elif choice == "e":
            edit_settings(manager)
        elif choice == "d":
            dry_run = not dry_run
            Logger.info(f"Dry run mode: {'enabled' if dry_run else 'disabled'}")
        elif choice in ("1", "2", "3", "4", "5", "6"):
            action = int(choice)
            result = run_action(action, manager, dry_run, yes=yes)
            if result == 0:
                Logger.success("Action completed successfully")
                # Offer cleanup after successful create/configure (but not for cleanup itself)
                if action in (1, 2) and not dry_run:
                    offer_cleanup_prompt(yes=yes)
            else:
                Logger.error("Action failed")
            input("\nPress enter to return to menu...")
            # Refresh manager to detect new context (e.g., after creating project)
            manager = SettingsManager(root=Path.cwd())
        else:
            Logger.warning(f"Unknown option: {choice}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="python -m tools.pyproject_template",
        description="Unified template management with menu-driven interface.",
    )

    # Subcommands for quick actions
    subparsers = parser.add_subparsers(dest="command", help="Quick action commands")

    subparsers.add_parser("create", help="Create new project from template")
    subparsers.add_parser("configure", help="Re-run configuration")
    check_parser = subparsers.add_parser("check", help="Check for template updates")
    check_parser.add_argument(
        "--show-excluded",
        action="store_true",
        default=argparse.SUPPRESS,
        help="List paths skipped via .config/pyproject_template/sync-exclude.toml",
    )
    check_parser.add_argument(
        "--template-version",
        metavar="TAG",
        default=argparse.SUPPRESS,
        help="Compare against a specific template release tag (e.g. v2.2.0) instead of the latest",
    )
    subparsers.add_parser("repo", help="Update repository settings")
    subparsers.add_parser("sync", help="Mark as synced to latest template")
    cleanup_parser = subparsers.add_parser("cleanup", help="Clean up template-specific files")
    cleanup_parser.add_argument(
        "--cleanup-mode",
        choices=["setup", "all"],
        help="Cleanup mode: 'setup' removes setup files only, 'all' removes all template files",
    )

    # Global options
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Non-interactive mode (use detected settings, no prompts)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--update-only",
        action="store_true",
        help="Only check for updates (CI-friendly, fails if can't auto-detect)",
    )
    parser.add_argument(
        "--show-excluded",
        action="store_true",
        help="With 'check': list paths skipped via .config/pyproject_template/sync-exclude.toml",
    )
    parser.add_argument(
        "--template-version",
        metavar="TAG",
        default=None,
        help=(
            "With 'check': compare against a specific template release tag (e.g. v2.2.0) "
            "instead of the latest. Pins the comparison so a staged upgrade takes one "
            "release at a time and two runs produce the same diff."
        ),
    )

    args = parser.parse_args(argv)
    # Both parsers may declare these; SUPPRESS means an unset flag leaves no
    # attribute at all, so fill the defaults once here rather than letting
    # either parser's default overwrite the other's value.
    if not hasattr(args, "show_excluded"):
        args.show_excluded = False
    if not hasattr(args, "template_version"):
        args.template_version = None
    return args


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    args = parse_args(argv)

    # Initialize settings manager
    manager = SettingsManager(root=Path.cwd())

    # Handle quick action commands
    if args.command:
        command_map = {
            "create": 1,
            "configure": 2,
            "check": 3,
            "repo": 4,
            "sync": 5,
            "cleanup": 6,
        }
        action = command_map.get(args.command)
        if action:
            cleanup_mode = getattr(args, "cleanup_mode", None)
            return run_action(
                action,
                manager,
                args.dry_run,
                yes=args.yes,
                cleanup_mode=cleanup_mode,
                show_excluded=args.show_excluded,
                template_version=args.template_version,
            )
        return 1

    # Handle --update-only (CI mode)
    if args.update_only:
        if not manager.settings.is_configured():
            Logger.error("Cannot auto-detect settings. Run interactively first.")
            return 1
        return action_check_updates(
            manager,
            args.dry_run,
            show_excluded=args.show_excluded,
            template_version=args.template_version,
        )

    # Handle --yes (non-interactive mode)
    if args.yes:
        if not manager.settings.is_configured():
            Logger.error("Cannot run non-interactively without configured settings.")
            return 1

        # Run recommended action non-interactively
        latest_commit = get_template_latest_commit()
        recommended = get_recommended_action(
            manager.context,
            manager.settings,
            manager.template_state,
            latest_commit,
            template_downloaded=Path(
                "tmp/extracted/pyproject-template-main/.template_commit"
            ).exists(),
        )
        if recommended:
            return run_action(recommended, manager, args.dry_run, yes=True)
        Logger.success("Project is up to date, no action needed.")
        return 0

    # Interactive mode
    return interactive_menu(manager, args.dry_run)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        Logger.warning("Cancelled by user")
        sys.exit(1)
    except Exception as e:
        Logger.error(f"Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
