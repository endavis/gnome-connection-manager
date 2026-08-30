"""
Settings detection and management for pyproject-template.

Handles reading settings from multiple sources and tracking template sync state.
"""

from __future__ import annotations

import subprocess  # nosec B404
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import tomllib  # py311+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

# Support running as script or as module
_script_dir = Path(__file__).parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

from utils import (  # noqa: E402
    TEMPLATE_REPO,
    Logger,
    command_exists,
    get_first_author,
    get_git_config,
    parse_github_url,
    validate_email,
    validate_package_name,
)

# Settings file location
SETTINGS_DIR = Path(".config/pyproject_template")
SETTINGS_FILE = SETTINGS_DIR / "settings.toml"


def _toml_escape(value: str) -> str:
    """Escape a string for TOML."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _toml_serialize(data: dict[str, Any]) -> str:
    """Serialize a simple dict to TOML format.

    Only supports flat tables with string values and nested tables one level deep.
    """
    lines: list[str] = []

    for section, values in data.items():
        if not isinstance(values, dict):
            continue
        lines.append(f"[{section}]")
        for key, value in values.items():
            if value is None:
                continue
            if isinstance(value, str):
                lines.append(f'{key} = "{_toml_escape(value)}"')
            elif isinstance(value, bool):
                lines.append(f"{key} = {str(value).lower()}")
            elif isinstance(value, int | float):
                lines.append(f"{key} = {value}")
        lines.append("")

    return "\n".join(lines)


@dataclass
class TemplateState:
    """Tracks the template sync state."""

    commit: str | None = None
    commit_date: str | None = None

    def is_synced(self) -> bool:
        """Check if template state has been tracked."""
        return self.commit is not None


@dataclass
class ProjectSettings:
    """Project configuration settings."""

    project_name: str = ""
    package_name: str = ""
    pypi_name: str = ""
    description: str = ""
    author_name: str = ""
    author_email: str = ""
    github_user: str = ""
    github_repo: str = ""

    def is_configured(self) -> bool:
        """Check if settings appear to be configured (not placeholders)."""
        placeholders = {
            "package_name",
            "package-name",
            "Package Name",
            "Your Name",
            "your.email@example.com",
            "username",
            "A short description of your package",
        }
        values = [
            self.project_name,
            self.package_name,
            self.author_name,
            self.author_email,
            self.github_user,
            self.description,
        ]
        return all(v and v not in placeholders for v in values)

    def has_placeholder_values(self) -> list[str]:
        """Return list of fields that still have placeholder values."""
        placeholders = {
            "project_name": {"Package Name", ""},
            "package_name": {"package_name", ""},
            "pypi_name": {"package-name", ""},
            "description": {"A short description of your package", ""},
            "author_name": {"Your Name", ""},
            "author_email": {"your.email@example.com", ""},
            "github_user": {"username", ""},
        }
        result = []
        for field_name, placeholder_set in placeholders.items():
            value = getattr(self, field_name, "")
            if value in placeholder_set:
                result.append(field_name)
        return result


@dataclass
class ProjectContext:
    """Detected project context."""

    has_pyproject: bool = False
    has_git: bool = False
    has_git_remote: bool = False
    git_remote_url: str = ""
    is_template_repo: bool = False

    @property
    def is_fresh_clone(self) -> bool:
        """Check if this appears to be a fresh clone needing setup."""
        return self.has_git and not self.has_pyproject

    @property
    def is_existing_repo(self) -> bool:
        """Check if this is an existing configured repo."""
        return self.has_git and self.has_pyproject


@dataclass
class PreflightWarning:
    """A warning to display to the user."""

    message: str
    suggestion: str = ""


@dataclass
class SettingsManager:
    """Manages project settings detection and persistence."""

    root: Path = field(default_factory=Path.cwd)
    settings: ProjectSettings = field(default_factory=ProjectSettings)
    template_state: TemplateState = field(default_factory=TemplateState)
    context: ProjectContext = field(default_factory=ProjectContext)
    warnings: list[PreflightWarning] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Initialize by detecting context and loading settings."""
        self._detect_context()
        self._load_settings()
        self._run_preflight_checks()

    def _detect_context(self) -> None:
        """Detect the project context."""
        self.context.has_pyproject = (self.root / "pyproject.toml").exists()
        self.context.has_git = (self.root / ".git").exists()

        if self.context.has_git:
            try:
                result = subprocess.run(
                    ["git", "config", "--get", "remote.origin.url"],
                    capture_output=True,
                    text=True,
                    cwd=self.root,
                )
                if result.returncode == 0 and result.stdout.strip():
                    self.context.has_git_remote = True
                    self.context.git_remote_url = result.stdout.strip()
                    # Check if this is the template repo itself
                    if TEMPLATE_REPO in self.context.git_remote_url:
                        self.context.is_template_repo = True
            except (subprocess.SubprocessError, FileNotFoundError):
                pass

    def _load_settings(self) -> None:
        """Load settings from all available sources."""
        # Priority order: settings.yml > pyproject.toml > git config
        self._load_from_settings_file()
        self._load_from_pyproject()
        self._load_from_git()

    def _load_from_settings_file(self) -> None:
        """Load settings from .config/pyproject_template/settings.toml."""
        settings_path = self.root / SETTINGS_FILE
        if not settings_path.exists():
            return

        try:
            with settings_path.open("rb") as f:
                data = tomllib.load(f)

            # Load project settings
            if "project" in data:
                proj = data["project"]
                self.settings.project_name = proj.get("name", self.settings.project_name)
                self.settings.package_name = proj.get("package_name", self.settings.package_name)
                self.settings.pypi_name = proj.get("pypi_name", self.settings.pypi_name)
                self.settings.description = proj.get("description", self.settings.description)
                self.settings.author_name = proj.get("author_name", self.settings.author_name)
                self.settings.author_email = proj.get("author_email", self.settings.author_email)
                self.settings.github_user = proj.get("github_user", self.settings.github_user)
                self.settings.github_repo = proj.get("github_repo", self.settings.github_repo)

            # Load template state
            if "template" in data:
                tmpl = data["template"]
                self.template_state.commit = tmpl.get("commit")
                self.template_state.commit_date = tmpl.get("commit_date")

        except (tomllib.TOMLDecodeError, OSError) as e:
            Logger.warning(f"Failed to read settings file: {e}")

    def _load_from_pyproject(self) -> None:
        """Load settings from pyproject.toml."""
        pyproject_path = self.root / "pyproject.toml"
        if not pyproject_path.exists():
            return

        try:
            with pyproject_path.open("rb") as f:
                data = tomllib.load(f)

            project = data.get("project", {})

            # Only override if not already set from settings.yml
            if not self.settings.project_name:
                name = project.get("name", "")
                self.settings.project_name = name
                if name and not self.settings.package_name:
                    self.settings.package_name = validate_package_name(name)
                if name and not self.settings.pypi_name:
                    # Convert underscores to hyphens for PyPI
                    self.settings.pypi_name = name.replace("_", "-")

            if not self.settings.description:
                self.settings.description = project.get("description", "")

            # Get author info
            author_name, author_email = get_first_author(data)
            if not self.settings.author_name:
                self.settings.author_name = author_name
            if not self.settings.author_email:
                self.settings.author_email = author_email

            # Get GitHub user from repository URL
            if not self.settings.github_user:
                repo_url = project.get("urls", {}).get("Repository", "")
                github_user, github_repo = parse_github_url(repo_url)
                if github_user:
                    self.settings.github_user = github_user
                    if not self.settings.github_repo:
                        self.settings.github_repo = github_repo

        except (tomllib.TOMLDecodeError, OSError) as e:
            Logger.warning(f"Failed to read pyproject.toml: {e}")

    def _load_from_git(self) -> None:
        """Load settings from git config."""
        if not self.context.has_git:
            return

        # Get author info from git config
        if not self.settings.author_name:
            self.settings.author_name = get_git_config("user.name")

        if not self.settings.author_email:
            self.settings.author_email = get_git_config("user.email")

        # Get GitHub user/repo from remote URL
        if self.context.has_git_remote and not self.settings.github_user:
            github_user, github_repo = parse_github_url(self.context.git_remote_url)
            if github_user:
                self.settings.github_user = github_user
                if not self.settings.github_repo:
                    self.settings.github_repo = github_repo

    def _run_preflight_checks(self) -> None:
        """Run preflight checks and collect warnings."""
        self.warnings = []

        # Check for GitHub CLI
        if not command_exists("gh"):
            self.warnings.append(
                PreflightWarning(
                    message="GitHub CLI (gh) not installed",
                    suggestion="Install from: https://cli.github.com/",
                )
            )
        elif not self._gh_authenticated():
            self.warnings.append(
                PreflightWarning(
                    message="GitHub CLI not authenticated",
                    suggestion="Run: gh auth login",
                )
            )

        # Check for git
        if not command_exists("git"):
            self.warnings.append(
                PreflightWarning(
                    message="Git not installed",
                    suggestion="Install from: https://git-scm.com/downloads",
                )
            )

        # Check for uv
        if not command_exists("uv"):
            self.warnings.append(
                PreflightWarning(
                    message="uv not installed",
                    suggestion="Install from: https://docs.astral.sh/uv/",
                )
            )

        # Note: We don't warn about missing .git - that's expected for new projects

        # Check for placeholder values
        placeholders = self.settings.has_placeholder_values()
        if placeholders:
            self.warnings.append(
                PreflightWarning(
                    message=f"Placeholder values detected: {', '.join(placeholders)}",
                    suggestion="Run configuration to set proper values",
                )
            )

        # Check email validity
        if self.settings.author_email and not validate_email(self.settings.author_email):
            self.warnings.append(
                PreflightWarning(
                    message="Invalid author email format",
                    suggestion="Update email in settings",
                )
            )

    def _gh_authenticated(self) -> bool:
        """Check if GitHub CLI is authenticated."""
        try:
            result = subprocess.run(
                ["gh", "auth", "status"],
                capture_output=True,
                text=True,
            )
            return result.returncode == 0
        except (subprocess.SubprocessError, FileNotFoundError):
            return False

    def save(self) -> None:
        """Save template state to .config/pyproject_template/settings.toml."""
        # Only save if we have template state to save
        if not self.template_state.commit:
            return

        settings_dir = self.root / SETTINGS_DIR
        settings_dir.mkdir(parents=True, exist_ok=True)

        data: dict[str, Any] = {
            "template": {
                "commit": self.template_state.commit,
                "commit_date": self.template_state.commit_date,
            },
        }

        settings_path = self.root / SETTINGS_FILE
        with settings_path.open("w", encoding="utf-8") as f:
            f.write(_toml_serialize(data))

        Logger.success(f"Settings saved to {SETTINGS_FILE}")

    def update_template_state(self, commit: str, commit_date: str) -> None:
        """Update the template sync state."""
        self.template_state.commit = commit
        self.template_state.commit_date = commit_date
        self.save()


def get_template_latest_commit() -> tuple[str, str] | None:
    """Fetch the latest commit info from the template repository.

    Returns:
        Tuple of (commit_sha, commit_date) or None if fetch fails.
    """
    import json
    import urllib.request

    api_url = f"https://api.github.com/repos/{TEMPLATE_REPO}/commits/main"
    try:
        req = urllib.request.Request(api_url)
        req.add_header("Accept", "application/vnd.github.v3+json")
        with urllib.request.urlopen(req, timeout=10) as response:  # nosec B310
            data = json.loads(response.read())
            commit_sha = data.get("sha", "")  # Full SHA for GitHub compare
            commit_date = data.get("commit", {}).get("committer", {}).get("date", "")
            if commit_date:
                # Parse and format the date
                dt = datetime.fromisoformat(commit_date.replace("Z", "+00:00"))
                commit_date = dt.strftime("%Y-%m-%d")
            return (commit_sha, commit_date)
    except Exception as e:
        Logger.warning(f"Could not fetch latest template commit: {e}")
        return None


def get_template_commits_since(since_commit: str) -> list[dict[str, str]] | None:
    """Get list of commits since a given commit.

    Returns:
        List of commit dicts with 'sha', 'message', 'date' or None if fetch fails.
    """
    import json
    import urllib.request

    api_url = f"https://api.github.com/repos/{TEMPLATE_REPO}/commits?per_page=50"
    try:
        req = urllib.request.Request(api_url)
        req.add_header("Accept", "application/vnd.github.v3+json")
        with urllib.request.urlopen(req, timeout=10) as response:  # nosec B310
            data = json.loads(response.read())

        commits = []
        for commit_data in data:
            sha = commit_data.get("sha", "")[:12]
            if sha == since_commit[:12]:
                break
            message = commit_data.get("commit", {}).get("message", "").split("\n")[0]
            date = commit_data.get("commit", {}).get("committer", {}).get("date", "")
            if date:
                dt = datetime.fromisoformat(date.replace("Z", "+00:00"))
                date = dt.strftime("%Y-%m-%d")
            commits.append({"sha": sha, "message": message, "date": date})

        return commits
    except Exception as e:
        Logger.warning(f"Could not fetch template commits: {e}")
        return None
