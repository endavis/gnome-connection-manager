#!/usr/bin/env python3
"""
setup-repo.py - Automated GitHub Repository Setup from pyproject-template

This script automates the creation and configuration of a new GitHub repository
based on the pyproject-template. It handles repository creation, settings
configuration, branch protection, and placeholder replacement.

Usage:
    python3 setup-repo.py
    curl -sSL https://raw.githubusercontent.com/endavis/pyproject-template/main/bootstrap.py \
        | python3

Requirements:
    - GitHub CLI (gh) installed and authenticated
    - Git installed
    - Python 3.12+

Author: Generated from pyproject-template
License: MIT
"""

import os
import shutil
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Any

# Support running as script or as module
_script_dir = Path(__file__).parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

# isort: off
# Import cleanup helpers (used after development environment setup to
# remove the template management suite from the spawned consumer project).
from cleanup import (  # noqa: E402
    CleanupMode,
    cleanup_template_files,
)

# Import repo settings functions (aliased to avoid shadowing class methods)
from repo_settings import (  # noqa: E402
    configure_branch_protection as _configure_branch_protection,
    configure_repository_settings as _configure_repository_settings,
    enable_github_pages as _enable_github_pages,
    replicate_labels as _replicate_labels,
)

# Import shared utilities
from utils import (  # noqa: E402
    FILES_TO_UPDATE,
    TEMPLATE_REPO,
    Colors,
    GitHubCLI,
    Logger,
    command_exists,
    get_git_config,
    prompt,
    prompt_confirm,
    remove_template_owned_tests,
    update_file,
    update_test_files,
)
# isort: on


class RepositorySetup:
    """Main class for repository setup orchestration."""

    # Use TEMPLATE_REPO from utils.py as the single source of truth
    TEMPLATE_FULL = TEMPLATE_REPO

    def __init__(self) -> None:
        self.config: dict[str, Any] = {}
        self.start_dir = os.getcwd()

    def print_banner(self) -> None:
        """Print welcome banner."""
        print()
        print(
            f"{Colors.CYAN}╔═══════════════════════════════════════════════════════════╗{Colors.NC}"
        )
        print(
            f"{Colors.CYAN}║                                                           ║{Colors.NC}"
        )
        print(
            f"{Colors.CYAN}║     Python Project Template - Repository Setup            ║{Colors.NC}"
        )
        print(
            f"{Colors.CYAN}║                                                           ║{Colors.NC}"
        )
        print(
            f"{Colors.CYAN}╚═══════════════════════════════════════════════════════════╝{Colors.NC}"
        )
        print()

    def check_requirements(self) -> None:
        """Check that all required tools are installed."""
        Logger.step("Checking requirements...")

        # Check for gh CLI
        if not command_exists("gh"):
            Logger.error("GitHub CLI (gh) is not installed")
            print("  Install from: https://cli.github.com/")
            sys.exit(1)

        gh_version = subprocess.run(
            ["gh", "--version"],
            capture_output=True,
            text=True,
        ).stdout.split("\n")[0]
        Logger.success(f"GitHub CLI found: {gh_version}")

        # Check gh authentication
        if not GitHubCLI.is_authenticated():
            Logger.error("GitHub CLI is not authenticated")
            print("  Run: gh auth login")
            sys.exit(1)
        Logger.success("GitHub CLI authenticated")

        # Check token type and permissions
        self._check_token_permissions()

        # Check for git
        if not command_exists("git"):
            Logger.error("Git is not installed")
            print("  Install from: https://git-scm.com/downloads")
            sys.exit(1)

        git_version = subprocess.run(
            ["git", "--version"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        Logger.success(f"Git found: {git_version}")

        # Check for uv
        if not command_exists("uv"):
            Logger.error("uv is not installed")
            print("  Install from: https://docs.astral.sh/uv/getting-started/installation/")
            sys.exit(1)

        uv_version = subprocess.run(
            ["uv", "--version"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        Logger.success(f"uv found: {uv_version}")

    def _check_token_permissions(self) -> None:
        """Check GitHub token type and permissions."""
        Logger.info("Checking GitHub token permissions...")

        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
        )
        auth_info = result.stderr + result.stdout

        if "github_pat_" in auth_info or "gho_" in auth_info:
            Logger.warning("You're using a Personal Access Token (PAT)")
            print()
            print(f"  {Colors.YELLOW}Required permissions for fine-grained PAT:{Colors.NC}")
            print("  - Repository permissions:")
            print("    • Administration: Read and write")
            print("    • Contents: Read and write")
            print("    • Metadata: Read")
            print()
            print(f"  {Colors.YELLOW}To create/update your PAT:{Colors.NC}")
            print("  1. Go to: https://github.com/settings/tokens?type=beta")
            print("  2. Create new token or edit existing")
            print("  3. Select 'All repositories' or specific repos")
            print("  4. Add the permissions listed above")
            print("  5. Generate token and run: gh auth login")
            print()

            if not prompt_confirm("Do you have the required permissions configured?", default=True):
                Logger.error("Please configure your PAT with required permissions first")
                sys.exit(1)
        else:
            Logger.success("Token type appears to be OAuth (recommended)")

    def gather_inputs(self) -> None:
        """Gather repository configuration from user."""
        Logger.step("Gathering repository information...")
        print()

        # Repository name
        self.config["repo_name"] = prompt("Repository name")

        # Organization (optional)
        if prompt_confirm("Create in an organization?"):
            self.config["repo_owner"] = prompt("Organization name")
        else:
            # Get current user
            user_info = GitHubCLI.api("user")
            self.config["repo_owner"] = user_info["login"]

        self.config["repo_full"] = f"{self.config['repo_owner']}/{self.config['repo_name']}"

        # Visibility
        self.config["visibility"] = (
            "public" if prompt_confirm("Make repository public?", default=True) else "private"
        )

        # Package configuration
        print()
        Logger.info("Package configuration (used for placeholder replacement)")

        default_package = self.config["repo_name"].replace("-", "_")
        self.config["package_name"] = prompt(
            "Python package name (import name)", default=default_package
        )
        self.config["pypi_name"] = prompt("PyPI package name", default=self.config["repo_name"])
        self.config["description"] = prompt(
            "Package description",
            default="A Python project based on pyproject-template",
        )

        # Get git config for defaults
        git_name = get_git_config("user.name", "")
        git_email = get_git_config("user.email", "")

        self.config["author_name"] = prompt("Author name", default=git_name)
        self.config["author_email"] = prompt("Author email", default=git_email)

        # Confirmation
        print()
        Logger.step("Configuration summary:")
        print(f"  Repository: {self.config['repo_full']}")
        print(f"  Visibility: {self.config['visibility']}")
        print(f"  Package name: {self.config['package_name']}")
        print(f"  PyPI name: {self.config['pypi_name']}")
        print(f"  Description: {self.config['description']}")
        print(f"  Author: {self.config['author_name']} <{self.config['author_email']}>")
        print()

        if not prompt_confirm("Proceed with these settings?", default=True):
            Logger.warning("Setup cancelled by user")
            sys.exit(0)

    def create_github_repository(self) -> None:
        """Create repository on GitHub from template (without cloning)."""
        Logger.step("Creating repository on GitHub from template...")

        try:
            # Use REST API to create from template
            data = {
                "owner": self.config["repo_owner"],
                "name": self.config["repo_name"],
                "description": self.config["description"],
                "private": self.config["visibility"] == "private",
                "include_all_branches": False,
            }

            GitHubCLI.api(f"repos/{self.TEMPLATE_FULL}/generate", method="POST", data=data)
            Logger.success(f"Repository created: https://github.com/{self.config['repo_full']}")

        except subprocess.CalledProcessError as e:
            Logger.error("Failed to create repository from template")
            print()

            # Always show the actual error message
            if e.stderr:
                print(f"{Colors.RED}Error details:{Colors.NC}")
                print(f"  {e.stderr.strip()}")
                print()

            # Provide specific help for known errors
            if e.stderr and "Resource not accessible by personal access token" in e.stderr:
                print(f"{Colors.YELLOW}Solution:{Colors.NC}")
                print()
                print(f"1. {Colors.CYAN}Re-authenticate with OAuth (recommended):{Colors.NC}")
                print("   gh auth logout")
                print("   gh auth login")
                print("   # Choose: GitHub.com → HTTPS → Login with browser")
                print()
                print(f"2. {Colors.CYAN}Or update your fine-grained PAT:{Colors.NC}")
                print("   https://github.com/settings/tokens?type=beta")
                print("   Required permissions:")
                print("   - Administration: Read and write")
                print("   - Contents: Read and write")
                print("   - Metadata: Read")
                print()
            elif e.stderr and "name already exists" in e.stderr.lower():
                print(f"{Colors.YELLOW}Solution:{Colors.NC}")
                print(f"  A repository named '{self.config['repo_name']}' already exists.")
                print("  Choose a different name or delete the existing repository at:")
                print(f"  https://github.com/{self.config['repo_full']}/settings")
                print()

            sys.exit(1)

        # Wait a moment for repo to be fully ready
        import time

        time.sleep(2)

    def clone_repository(self) -> None:
        """Clone the repository locally and change to its directory."""
        Logger.step("Cloning repository locally...")

        try:
            GitHubCLI.run(
                ["repo", "clone", self.config["repo_full"], self.config["repo_name"]], capture=False
            )
            Logger.success("Repository cloned locally")
        except subprocess.CalledProcessError:
            Logger.error("Failed to clone repository")
            print(f"  You can try cloning manually: gh repo clone {self.config['repo_full']}")
            sys.exit(1)

        # Change to repo directory
        os.chdir(self.config["repo_name"])

    def configure_placeholders(self) -> None:
        """Configure project placeholders by replacing template strings."""
        Logger.step("Configuring project placeholders...")

        try:
            # Define replacements
            owner = self.config["repo_owner"]
            pkg = self.config["package_name"]
            replacements = {
                # Marker tokens (unambiguous, used in prose files). These take
                # priority because ``update_file()`` treats them as blind
                # replaces regardless of surrounding context.
                "__PACKAGE_NAME__": self.config["package_name"],
                "__PYPI_NAME__": self.config["pypi_name"],
                "__PROJECT_NAME__": self.config["repo_name"],
                "__GH_OWNER__": owner,
                "__AUTHOR_NAME__": self.config["author_name"],
                "__AUTHOR_EMAIL__": self.config["author_email"],
                "__DESCRIPTION__": self.config["description"],
                "__REPO_URL__": f"https://github.com/{owner}/{pkg}",
                "__REPO_SLUG__": f"{owner}/{pkg}",
                # URLs — kept for runtime-critical files (pyproject.toml,
                # workflows, LICENSE, mkdocs.yml, dodo.py, .envrc,
                # .pre-commit-config.yaml) that retain literal placeholders,
                # and for downstream consumer projects that have not yet
                # migrated to marker tokens.
                "https://github.com/username/package_name": (f"https://github.com/{owner}/{pkg}"),
                f"https://github.com/username/{pkg}": (f"https://github.com/{owner}/{pkg}"),
                "gh username/package_name": f"gh {owner}/{pkg}",
                "username/package_name": f"{owner}/{pkg}",
                "username": owner,
                # Package names (literal forms; Python files receive
                # word-boundary protection from ``update_file()``).
                "package_name": self.config["package_name"],
                "package-name": self.config["pypi_name"],
                "Package Name": self.config["repo_name"],
                # Metadata
                "A short description of your package": self.config["description"],
                "Your Name": self.config["author_name"],
                "your.email@example.com": self.config["author_email"],
                # Security-report address in .github/SECURITY.md. Absent from
                # this map until #787, so every spawned project shipped a
                # policy telling reporters to email security@example.com --
                # a real-looking address nobody owns. The file was already in
                # FILES_TO_UPDATE; only the mapping was missing.
                #
                # This is the author's address, unlike configure.py's, and for
                # the same reason: `setup_repo` creates a brand-new project,
                # where the person who wrote it is the person who answers for
                # it. configure.py runs against projects that may have been
                # adopted, so it reads [project].maintainers first.
                "security@example.com": self.config["author_email"],
                "[INSERT CONTACT EMAIL]": self.config["author_email"],
            }

            # Update main configuration files (using shared constant from utils.py)
            for file_path in FILES_TO_UPDATE:
                path = Path(file_path)
                if path.exists():
                    update_file(path, replacements)

            # Update documentation files
            docs_dir = Path("docs")
            if docs_dir.exists():
                for doc_file in docs_dir.rglob("*.md"):
                    update_file(doc_file, replacements)

            # Update test files (limited replacements to preserve test data)
            tests_dir = Path("tests")
            if tests_dir.exists():
                update_test_files(tests_dir, self.config["package_name"])

            # Shed template-only tests. Shares one implementation with
            # configure.py so the two wizard paths cannot disagree about what
            # "template-owned" means; see remove_template_owned_tests (#731).
            shed = remove_template_owned_tests(Path.cwd())
            if shed:
                Logger.info(f"Removed {len(shed)} template-only test files")

            # Update source files
            src_dir = Path("src")
            if src_dir.exists():
                for src_file in src_dir.rglob("*.py"):
                    update_file(src_file, replacements)

            # Update issue templates
            issue_templates_dir = Path(".github/ISSUE_TEMPLATE")
            if issue_templates_dir.exists():
                for template_file in issue_templates_dir.glob("*.md"):
                    update_file(template_file, replacements)
                # Also update config.yml if it exists
                config_file = issue_templates_dir / "config.yml"
                if config_file.exists():
                    update_file(config_file, replacements)

            # Update example files
            examples_dir = Path("examples")
            if examples_dir.exists():
                for example_file in examples_dir.rglob("*"):
                    if example_file.is_file():
                        update_file(example_file, replacements)

            # Rename package directory
            old_package_dir = Path("src/package_name")
            new_package_dir = Path(f"src/{self.config['package_name']}")
            if old_package_dir.exists() and old_package_dir != new_package_dir:
                shutil.move(str(old_package_dir), str(new_package_dir))
                Logger.success(f"Renamed package directory to src/{self.config['package_name']}")

            Logger.success("Placeholders configured")

            # Commit the changes
            subprocess.run(["git", "add", "."], check=True, capture_output=True)
            commit_msg = f"""
chore: configure project from template

- Set project name to {self.config["repo_name"]}
- Configure package as {self.config["package_name"]}
- Set author to {self.config["author_name"]}

🤖 Generated with setup-repo.py"""

            # Use --no-verify to bypass pre-commit hooks (like no-commit-to-main)
            # This is necessary because we are initializing the repo on main
            subprocess.run(
                ["git", "commit", "-m", commit_msg, "--no-verify"], check=True, capture_output=True
            )
            subprocess.run(["git", "push"], check=True, capture_output=True)
            Logger.success("Changes committed and pushed")

        except Exception as e:
            Logger.warning(f"Placeholder configuration failed: {e}")
            import traceback

            traceback.print_exc()

    def setup_development_environment(self) -> None:
        """Set up the development environment with dependencies and pre-commit hooks."""
        Logger.step("Setting up development environment...")

        try:
            # Install dependencies
            Logger.info("Installing dependencies with uv sync --all-extras...")
            result = subprocess.run(
                ["uv", "sync", "--all-extras"],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                Logger.warning("Failed to install dependencies")
                Logger.info("You can install manually with: uv sync --all-extras")
                return

            Logger.success("Dependencies installed")

            # Install pre-commit hooks
            Logger.info("Installing pre-commit hooks...")
            result = subprocess.run(
                ["uv", "run", "pre-commit", "install"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                Logger.success("Pre-commit hooks installed")
                # Install post-merge and post-checkout hooks for auto uv sync
                for hook_type in ["post-merge", "post-checkout"]:
                    subprocess.run(
                        ["uv", "run", "pre-commit", "install", "--hook-type", hook_type],
                        capture_output=True,
                        text=True,
                    )
            else:
                Logger.warning("Failed to install pre-commit hooks")
                Logger.info("You can install manually with: uv run pre-commit install")

            # Fix linting issues (including import ordering)
            # Note: We run ruff directly with --fix because doit lint only checks,
            # doesn't auto-fix. This fixes import ordering (I001) and other auto-fixable issues.
            Logger.info("Fixing linting issues with ruff...")
            subprocess.run(
                ["uv", "run", "ruff", "check", "--fix", "."],
                capture_output=True,
                text=True,
            )

            # Format pyproject.toml using doit task
            Logger.info("Formatting pyproject.toml...")
            subprocess.run(
                ["uv", "run", "doit", "fmt_pyproject"],
                capture_output=True,
                text=True,
            )

            # Format code using doit task
            Logger.info("Formatting code with ruff...")
            subprocess.run(
                ["uv", "run", "doit", "format"],
                capture_output=True,
                text=True,
            )

            # Run validation checks BEFORE committing
            Logger.info("Running validation checks (doit check)...")
            check_result = subprocess.run(
                ["uv", "run", "doit", "check"],
                capture_output=False,
                text=True,
            )

            if check_result.returncode != 0:
                Logger.error("Validation checks failed")
                print()
                print(f"{Colors.YELLOW}Please fix the issues above before continuing.{Colors.NC}")
                print("The formatting changes have been applied but not committed.")
                print()
                print("After fixing issues, you can commit with:")
                print("  git add .")
                print("  git commit -m 'chore: apply code formatting'")
                print("  git push")
                print()
                return

            Logger.success("All validation checks passed")

            # Check if there are any formatting changes to commit
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
            )

            if result.stdout.strip():
                Logger.info("Committing formatting changes...")
                subprocess.run(["git", "add", "."], check=True, capture_output=True)
                commit_msg = """
chore: apply code formatting

- Fix linting issues with ruff
- Format pyproject.toml with pyproject-fmt
- Format code with ruff

🤖 Generated with setup-repo.py"""
                commit_result = subprocess.run(
                    ["git", "commit", "-m", commit_msg, "--no-verify"],
                    capture_output=True,
                    text=True,
                )
                if commit_result.returncode != 0:
                    Logger.error("Failed to commit formatting changes")
                    print()
                    print(f"{Colors.RED}Git commit error:{Colors.NC}")
                    if commit_result.stderr:
                        print(f"  {commit_result.stderr.strip()}")
                    if commit_result.stdout:
                        print(f"  {commit_result.stdout.strip()}")
                    print()
                    print(f"{Colors.YELLOW}Possible solutions:{Colors.NC}")
                    print("  1. Check pre-commit hook output above for specific issues")
                    print("  2. Fix any failing pre-commit checks manually")
                    print("  3. Run: git status")
                    print("  4. Review changes and commit manually")
                    print()
                    return

                push_result = subprocess.run(
                    ["git", "push"],
                    capture_output=True,
                    text=True,
                )
                if push_result.returncode != 0:
                    Logger.error("Failed to push formatting changes")
                    if push_result.stderr:
                        print(f"  Error: {push_result.stderr.strip()}")
                    print("  You can push manually later with: git push")
                else:
                    Logger.success("Formatting changes committed and pushed")
            else:
                Logger.success("No formatting changes needed")

        except subprocess.CalledProcessError as e:
            Logger.error("Development environment setup failed")
            print()
            print(f"{Colors.RED}Error details:{Colors.NC}")
            if e.stderr:
                print(f"  {e.stderr.strip()}")
            if e.stdout:
                print(f"  {e.stdout.strip()}")
            print()
            print(f"{Colors.YELLOW}You can complete setup manually with:{Colors.NC}")
            print("  cd", self.config["repo_name"])
            print("  uv sync --all-extras")
            print("  uv run pre-commit install")
            print("  uv run doit check")
            print()
        except Exception as e:
            Logger.error(f"Development environment setup failed: {e}")
            print()
            import traceback

            print(f"{Colors.RED}Full error:{Colors.NC}")
            traceback.print_exc()
            print()
            print(f"{Colors.YELLOW}You can complete setup manually with:{Colors.NC}")
            print("  cd", self.config["repo_name"])
            print("  uv sync --all-extras")
            print("  uv run pre-commit install")
            print("  uv run doit check")
            print()

    def cleanup_template_suite(self) -> None:
        """Remove the template management suite from the spawned consumer project.

        Consumer projects do not use or maintain the template's own tooling
        (``tools/pyproject_template/``, ``docs/template/``, ``bootstrap.py``).
        This step invokes :func:`cleanup_template_files` with
        :attr:`CleanupMode.ALL` to delete the suite, then stages, commits, and
        pushes the deletions so the consumer's default branch reflects a clean
        tree.

        Consumers who later want the template-sync suite back can re-install
        it with ``curl -sSL .../bootstrap.py | python3 - --sync``.

        This method is defensive: any failure is logged as a warning and
        execution continues, so a cleanup failure does not block the user from
        using their freshly-spawned repository.
        """
        Logger.step("Removing template management suite from spawned project...")

        try:
            result = cleanup_template_files(CleanupMode.ALL, root=Path.cwd())

            # If nothing was deleted, there's nothing to commit.
            if not result.deleted_files and not result.deleted_dirs:
                Logger.info("No template files found to clean up")
                return

            # Stage deletions, commit, and push. --no-verify mirrors the
            # pattern used in configure_placeholders(); the no-commit-to-main
            # pre-commit hook would otherwise reject the commit on a freshly
            # spawned repo whose only branch is main.
            subprocess.run(["git", "add", "-A"], check=True, capture_output=True)
            commit_msg = """
chore: remove template management suite

Auto-removed by setup_repo.py to keep the consumer project free of
template-only tooling:

- tools/pyproject_template/ (manage.py, setup_repo.py, configure.py,
  cleanup.py, check_template_updates.py, settings.py, repo_settings.py,
  utils.py, __init__.py)
- docs/template/
- bootstrap.py
- Template nav section in mkdocs.yml

To reinstall the template-sync suite later, run:
  curl -sSL https://raw.githubusercontent.com/endavis/pyproject-template/main/bootstrap.py \\
      | python3 - --sync

🤖 Generated with setup-repo.py"""

            subprocess.run(
                ["git", "commit", "-m", commit_msg, "--no-verify"],
                check=True,
                capture_output=True,
            )
            subprocess.run(["git", "push"], check=True, capture_output=True)
            Logger.success("Template management suite removed, committed, and pushed")

        except Exception as e:
            Logger.warning(f"Template suite cleanup failed: {e}")
            Logger.info(
                "You can remove the template suite manually later by running "
                "`python tools/pyproject_template/cleanup.py --all` from the project root."
            )
            import traceback

            traceback.print_exc()

    def verify_post_cleanup(self) -> None:
        """Run ``doit check`` after template suite cleanup; log on failure.

        The wizard already runs ``doit check`` inside
        :meth:`setup_development_environment`, but that runs *before*
        :meth:`cleanup_template_suite` removes ``bootstrap.py`` and the
        template management suite. Any task command that references files
        which cleanup just deleted would slip through undetected.

        This method re-runs ``uv run doit check`` in the cloned project
        directory after cleanup. Failure is treated leniently — matching the
        pattern in :meth:`setup_development_environment`: the wizard prints
        a clear diagnostic and continues to :meth:`print_manual_steps`. It
        does **not** ``sys.exit``, because the GitHub repo has already been
        created and partially configured; forcing an exit here would leave
        the user with a half-set-up remote and no friendly path forward.
        """
        Logger.step("Verifying project after cleanup (doit check)...")

        try:
            check_result = subprocess.run(
                ["uv", "run", "doit", "check"],
                capture_output=False,
                text=True,
            )
        except FileNotFoundError as e:
            # uv not on PATH in this shell; surface the diagnostic but
            # do not raise — the user can re-run manually.
            Logger.warning(f"Post-cleanup validation could not run: {e}")
            Logger.info(
                "Validation failed *after* cleanup — the repo was created but "
                "`doit check` currently fails; see output above"
            )
            return

        if check_result.returncode != 0:
            Logger.warning(
                f"Post-cleanup `doit check` returned non-zero exit status {check_result.returncode}"
            )
            Logger.info(
                "Validation failed *after* cleanup — the repo was created but "
                "`doit check` currently fails; see output above"
            )
            return

        Logger.success("Post-cleanup validation checks passed")

    def configure_repository_settings(self) -> None:
        """Configure repository settings to match template."""
        _configure_repository_settings(
            repo_full=self.config["repo_full"],
            description=self.config["description"],
            visibility=self.config.get("visibility"),
            template_repo=self.TEMPLATE_FULL,
        )

    def configure_branch_protection(self) -> None:
        """Configure branch protection using rulesets."""
        _configure_branch_protection(
            repo_full=self.config["repo_full"],
            template_repo=self.TEMPLATE_FULL,
        )

    def replicate_labels(self) -> None:
        """Replicate labels from template."""
        _replicate_labels(
            repo_full=self.config["repo_full"],
            template_repo=self.TEMPLATE_FULL,
        )

    def enable_github_pages(self) -> None:
        """Enable GitHub Pages."""
        _enable_github_pages(repo_full=self.config["repo_full"])

    def print_manual_steps(self) -> None:
        """Print manual steps that need to be completed."""
        print()
        print(
            f"{Colors.CYAN}╔═══════════════════════════════════════════════════════════╗{Colors.NC}"
        )
        print(
            f"{Colors.CYAN}║                  Setup Complete! 🎉                       ║{Colors.NC}"
        )
        print(
            f"{Colors.CYAN}╚═══════════════════════════════════════════════════════════╝{Colors.NC}"
        )
        print()
        Logger.success(
            f"Repository created and configured: https://github.com/{self.config['repo_full']}"
        )
        print()

        Logger.step("Manual steps required:")
        print()
        print(f"  {Colors.YELLOW}[ ]{Colors.NC} Add PyPI token to repository secrets:")
        print(f"      gh secret set PYPI_TOKEN --repo {self.config['repo_full']}")
        print()
        print(
            f"  {Colors.YELLOW}[ ]{Colors.NC} Add TestPyPI token to repository secrets (optional):"
        )
        print(f"      gh secret set TEST_PYPI_TOKEN --repo {self.config['repo_full']}")
        print()
        print(
            f"  {Colors.YELLOW}[ ]{Colors.NC} Add Codecov token to repository secrets (optional):"
        )
        print(f"      gh secret set CODECOV_TOKEN --repo {self.config['repo_full']}")
        print()
        print(f"  {Colors.YELLOW}[ ]{Colors.NC} Review and adjust repository settings:")
        print(f"      https://github.com/{self.config['repo_full']}/settings")
        print()
        print(f"  {Colors.YELLOW}[ ]{Colors.NC} Review branch protection rulesets:")
        print(f"      https://github.com/{self.config['repo_full']}/settings/rules")
        print()
        print(f"  {Colors.YELLOW}[ ]{Colors.NC} Invite collaborators (if needed):")
        print(f"      https://github.com/{self.config['repo_full']}/settings/access")
        print()

        Logger.info(
            "Template tooling was auto-removed. To reinstall the template-sync "
            "suite later, run: curl -sSL "
            "https://raw.githubusercontent.com/endavis/pyproject-template/main/bootstrap.py "
            "| python3 - --sync"
        )
        print()

        Logger.step("You're all set!")
        print()
        repo_path = os.path.join(self.start_dir, self.config["repo_name"])
        print(f"  {Colors.GREEN}✓{Colors.NC} Repository cloned to: {repo_path}")
        print(f"  {Colors.GREEN}✓{Colors.NC} Dependencies installed")
        print(f"  {Colors.GREEN}✓{Colors.NC} Pre-commit hooks configured")
        print(f"  {Colors.GREEN}✓{Colors.NC} Code formatted and validated")
        print()
        print("  Navigate to your repository and start developing:")
        print(f"     cd {self.config['repo_name']}")
        print()

        Logger.info(
            f"Documentation: https://github.com/{self.config['repo_full']}/blob/main/README.md"
        )
        print()

    def run(self) -> None:
        """Run the complete setup process.

        Order of operations:
        1. Create GitHub repository (fail fast if there are auth/permission issues)
        2. Configure all GitHub settings (before cloning to avoid partial setup)
        3. Clone repository locally
        4. Configure local files and development environment
        5. Remove template management suite from the consumer project
        6. Re-run ``doit check`` to confirm the post-cleanup tree is valid
        """
        self.print_banner()
        self.check_requirements()
        self.gather_inputs()

        # Create repository on GitHub and configure all GitHub settings
        # BEFORE cloning to avoid partial setup if GitHub operations fail.
        # CodeQL scanning is NOT set up here: it runs from the committed
        # .github/workflows/codeql.yml workflow that the template generator
        # copies into the new repo automatically.
        self.create_github_repository()
        self.configure_repository_settings()
        self.configure_branch_protection()
        self.replicate_labels()
        self.enable_github_pages()

        # Now clone and configure locally
        self.clone_repository()
        self.configure_placeholders()
        self.setup_development_environment()

        # Remove the template management suite from the spawned project.
        # Consumers don't use or maintain the template's own tooling; they
        # can re-install it later with `bootstrap.py --sync` if desired.
        self.cleanup_template_suite()

        # Re-run `doit check` after cleanup to catch any stale references
        # that survived the template-suite removal. Lenient — logs a
        # diagnostic and continues on failure so the wizard still reaches
        # print_manual_steps.
        self.verify_post_cleanup()

        self.print_manual_steps()


def main() -> None:
    """Main entry point."""
    try:
        setup = RepositorySetup()
        setup.run()
    except KeyboardInterrupt:
        print()
        Logger.warning("Setup cancelled by user")
        sys.exit(1)
    except Exception as e:
        print()
        Logger.error(f"Setup failed with unexpected error: {e}")
        print()
        print("This is likely a bug in the setup script.")
        print("Please report this issue with the error details above at:")
        print("  https://github.com/endavis/pyproject-template/issues")
        print()

        # Show traceback for debugging
        import traceback

        print("Full traceback:")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    print("This script should not be run directly.")
    print("Please use: python manage.py")
    sys.exit(1)
