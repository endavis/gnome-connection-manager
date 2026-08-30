"""
pyproject-template tools package.

Provides utilities for managing Python projects based on pyproject-template.
"""

from .check_template_updates import (
    compare_files,
    download_template,
    resolve_template_ref,
    run_check_updates,
)
from .configure import (
    load_defaults,
    run_configure,
)
from .settings import (
    ProjectContext,
    ProjectSettings,
    SettingsManager,
    TemplateState,
    get_template_commits_since,
    get_template_latest_commit,
)
from .utils import (
    Colors,
    GitHubCLI,
    Logger,
    download_and_extract_archive,
    prompt,
    prompt_confirm,
    update_file,
    validate_email,
    validate_package_name,
    validate_pypi_name,
)

__all__ = [
    # Settings
    "ProjectContext",
    "ProjectSettings",
    "SettingsManager",
    "TemplateState",
    "get_template_commits_since",
    "get_template_latest_commit",
    # Configure
    "load_defaults",
    "run_configure",
    # Check updates
    "compare_files",
    "download_template",
    "resolve_template_ref",
    "run_check_updates",
    # Migrate
    # Utils
    "Colors",
    "GitHubCLI",
    "Logger",
    "download_and_extract_archive",
    "prompt",
    "prompt_confirm",
    "update_file",
    "validate_email",
    "validate_package_name",
    "validate_pypi_name",
]
