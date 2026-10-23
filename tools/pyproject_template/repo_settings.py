#!/usr/bin/env python3
"""
repo_settings.py - GitHub repository settings configuration.

This module provides functions to configure GitHub repository settings,
branch protection, labels, and GitHub Pages. It can be used independently
of the full setup process.

CodeQL scanning is configured via the committed workflow file at
``.github/workflows/codeql.yml`` (advanced setup) -- no API call is
required, because the workflow is replicated by the template generator
along with all other workflow files. See issue #431.

These functions are used by both setup_repo.py (initial setup) and
manage.py (updating existing repositories).
"""

from __future__ import annotations

import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Any

# Support running as script or as module
_script_dir = Path(__file__).parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

from utils import TEMPLATE_REPO, GitHubCLI, Logger  # noqa: E402


def configure_repository_settings(
    repo_full: str,
    description: str,
    visibility: str | None = None,
    template_repo: str = TEMPLATE_REPO,
) -> bool:
    """Configure repository settings to match template.

    Args:
        repo_full: Full repository name (owner/repo)
        description: Repository description
        visibility: Repository visibility ('public' or 'private'), used for
                   determining which security features are available
        template_repo: Template repository to copy settings from

    Returns:
        True if successful, False otherwise
    """
    Logger.step("Configuring repository settings...")

    try:
        # Get ALL settings from template repository
        template_settings = GitHubCLI.api(f"repos/{template_repo}")

        # Read-only fields that should not be copied
        readonly_fields = {
            # URLs
            "archive_url",
            "assignees_url",
            "blobs_url",
            "branches_url",
            "clone_url",
            "collaborators_url",
            "comments_url",
            "commits_url",
            "compare_url",
            "contents_url",
            "contributors_url",
            "deployments_url",
            "downloads_url",
            "events_url",
            "forks_url",
            "git_commits_url",
            "git_refs_url",
            "git_tags_url",
            "git_url",
            "hooks_url",
            "html_url",
            "issue_comment_url",
            "issue_events_url",
            "issues_url",
            "keys_url",
            "labels_url",
            "languages_url",
            "merges_url",
            "milestones_url",
            "notifications_url",
            "pulls_url",
            "releases_url",
            "ssh_url",
            "stargazers_url",
            "statuses_url",
            "subscribers_url",
            "subscription_url",
            "svn_url",
            "tags_url",
            "teams_url",
            "trees_url",
            "url",
            # IDs and metadata
            "id",
            "node_id",
            "owner",
            "full_name",
            "name",
            # Timestamps
            "created_at",
            "updated_at",
            "pushed_at",
            # Counts and computed values
            "forks",
            "forks_count",
            "open_issues",
            "open_issues_count",
            "size",
            "stargazers_count",
            "watchers",
            "watchers_count",
            "subscribers_count",
            "network_count",
            # Other read-only
            "fork",
            "language",
            "license",
            "permissions",
            "disabled",
            "mirror_url",
            "default_branch",  # Keep as main
            "private",  # Set separately via visibility
            "is_template",  # Don't make new repos templates
            # Deprecated
            "use_squash_pr_title_as_default",
        }

        # Build settings data by copying all writable fields from template
        data: dict[str, Any] = {}
        for key, value in template_settings.items():
            if key not in readonly_fields and value is not None:
                data[key] = value

        # Override description with user's description
        data["description"] = description

        # Check if repository is in an organization
        repo_owner = repo_full.split("/")[0]
        owner_info = GitHubCLI.api(f"users/{repo_owner}")
        is_org = owner_info.get("type") == "Organization"

        # Remove allow_forking if not an org repo (only applies to orgs)
        if not is_org and "allow_forking" in data:
            data.pop("allow_forking")

        # Remove security_and_analysis - we'll handle it separately
        security_settings = data.pop("security_and_analysis", None)

        # Apply all settings in one call
        GitHubCLI.api(f"repos/{repo_full}", method="PATCH", data=data)
        Logger.success("Repository settings configured")

        # Configure security and analysis settings separately
        if security_settings:
            _configure_security_settings(repo_full, security_settings, visibility)

        return True

    except subprocess.CalledProcessError as e:
        Logger.warning("Repository settings configuration failed")
        if e.stderr:
            print(f"  Error: {e.stderr.strip()}")
        Logger.info("You can configure settings manually at:")
        Logger.info(f"  https://github.com/{repo_full}/settings")
        return False


def _configure_security_settings(
    repo_full: str,
    security_settings: dict[str, Any],
    visibility: str | None = None,
) -> None:
    """Configure security and analysis settings.

    Args:
        repo_full: Full repository name (owner/repo)
        security_settings: Security settings from template
        visibility: Repository visibility for determining feature availability
    """
    if not security_settings:
        return

    # Enable secret scanning if template has it
    if security_settings.get("secret_scanning", {}).get("status") == "enabled":
        try:
            GitHubCLI.api(
                f"repos/{repo_full}/secret-scanning",
                method="PATCH",
                data={"status": "enabled"},
            )
            Logger.success("Secret scanning enabled")
        except subprocess.CalledProcessError as e:
            # 404 is expected for free/private repos that don't support this
            if "404" in str(e.stderr):
                if visibility == "public":
                    Logger.success("Secret scanning enabled (default for public repos)")
                else:
                    Logger.info("Secret scanning not available (requires GHAS or public repo)")
            else:
                Logger.warning("Secret scanning configuration failed")
                if e.stderr:
                    print(f"  Error: {e.stderr.strip()}")

    # Enable secret scanning push protection if template has it
    if security_settings.get("secret_scanning_push_protection", {}).get("status") == "enabled":
        try:
            GitHubCLI.api(
                f"repos/{repo_full}/secret-scanning/push-protection",
                method="PATCH",
                data={"status": "enabled"},
            )
            Logger.success("Secret scanning push protection enabled")
        except subprocess.CalledProcessError as e:
            if "404" in str(e.stderr):
                if visibility == "public":
                    Logger.success(
                        "Secret scanning push protection enabled (default for public repos)"
                    )
                else:
                    Logger.info("Secret scanning push protection not available for this repository")
            else:
                Logger.warning("Secret scanning push protection configuration failed")
                if e.stderr:
                    print(f"  Error: {e.stderr.strip()}")

    # Enable Dependabot security updates if template has it
    if security_settings.get("dependabot_security_updates", {}).get("status") == "enabled":
        try:
            GitHubCLI.api(
                f"repos/{repo_full}/automated-security-fixes",
                method="PUT",
            )
            Logger.success("Dependabot security updates enabled")
        except subprocess.CalledProcessError as e:
            Logger.warning("Dependabot security updates configuration failed")
            if e.stderr:
                print(f"  Error: {e.stderr.strip()}")


def configure_branch_protection(
    repo_full: str,
    template_repo: str = TEMPLATE_REPO,
) -> bool:
    """Configure branch protection using rulesets.

    Args:
        repo_full: Full repository name (owner/repo)
        template_repo: Template repository to copy rulesets from

    Returns:
        True if successful, False otherwise
    """
    Logger.step("Configuring branch protection rulesets...")

    try:
        # Get rulesets from template
        template_rulesets = GitHubCLI.api(f"repos/{template_repo}/rulesets")

        if not template_rulesets:
            Logger.warning("No rulesets found in template repository")
            return True  # Not a failure, just nothing to do

        # Get existing rulesets from target repository to check for duplicates
        existing_rulesets = GitHubCLI.api(f"repos/{repo_full}/rulesets")
        existing_by_name: dict[str, int] = {
            ruleset["name"]: ruleset["id"] for ruleset in existing_rulesets
        }

        # Replicate each ruleset
        for template_ruleset in template_rulesets:
            # Get full ruleset details
            ruleset_id = template_ruleset["id"]
            full_ruleset = GitHubCLI.api(f"repos/{template_repo}/rulesets/{ruleset_id}")

            # Prepare ruleset data (remove read-only fields)
            ruleset_data = {
                "name": full_ruleset["name"],
                "target": full_ruleset["target"],
                "enforcement": full_ruleset["enforcement"],
                "bypass_actors": full_ruleset.get("bypass_actors", []),
                "conditions": full_ruleset.get("conditions", {}),
                "rules": full_ruleset.get("rules", []),
            }

            ruleset_name = full_ruleset["name"]

            # Check if ruleset already exists
            if ruleset_name in existing_by_name:
                # Update existing ruleset
                existing_id = existing_by_name[ruleset_name]
                GitHubCLI.api(
                    f"repos/{repo_full}/rulesets/{existing_id}",
                    method="PUT",
                    data=ruleset_data,
                )
                Logger.success(f"Ruleset '{ruleset_name}' updated")
            else:
                # Create new ruleset
                GitHubCLI.api(
                    f"repos/{repo_full}/rulesets",
                    method="POST",
                    data=ruleset_data,
                )
                Logger.success(f"Ruleset '{ruleset_name}' created")

        return True

    except subprocess.CalledProcessError as e:
        Logger.warning("Branch protection ruleset configuration failed")
        if e.stderr:
            print(f"  Error: {e.stderr.strip()}")
        Logger.info("You can configure rulesets manually at:")
        Logger.info(f"  https://github.com/{repo_full}/settings/rules")
        return False


def replicate_labels(
    repo_full: str,
    template_repo: str = TEMPLATE_REPO,
) -> bool:
    """Replicate labels from template.

    Args:
        repo_full: Full repository name (owner/repo)
        template_repo: Template repository to copy labels from

    Returns:
        True if successful, False otherwise
    """
    Logger.step("Replicating labels from template...")

    try:
        # Get labels from template
        labels = GitHubCLI.api(f"repos/{template_repo}/labels")

        if not labels:
            Logger.warning("Could not retrieve labels from template")
            return False

        # Create each label
        for label in labels:
            try:
                label_data = {
                    "name": label["name"],
                    "color": label["color"],
                    "description": label.get("description", ""),
                }
                GitHubCLI.api(
                    f"repos/{repo_full}/labels",
                    method="POST",
                    data=label_data,
                )
            except subprocess.CalledProcessError:
                # Label might already exist, skip
                pass

        Logger.success("Labels replicated")
        return True

    except subprocess.CalledProcessError as e:
        Logger.warning("Failed to retrieve labels from template")
        if e.stderr:
            print(f"  Error: {e.stderr.strip()}")
        return False


def enable_github_pages(repo_full: str) -> bool:
    """Enable GitHub Pages.

    Args:
        repo_full: Full repository name (owner/repo)

    Returns:
        True if successful, False otherwise
    """
    Logger.step("Enabling GitHub Pages...")

    try:
        data = {
            "source": {
                "branch": "gh-pages",
                "path": "/",
            }
        }
        GitHubCLI.api(f"repos/{repo_full}/pages", method="POST", data=data)
        Logger.success("GitHub Pages enabled")
        return True
    except subprocess.CalledProcessError:
        Logger.warning("GitHub Pages not enabled (gh-pages branch doesn't exist yet)")
        Logger.info("Pages will be enabled automatically after first docs deployment")
        return False


def update_all_repo_settings(
    repo_full: str,
    description: str,
    visibility: str | None = None,
    template_repo: str = TEMPLATE_REPO,
) -> bool:
    """Update all repository settings to match template.

    This is a convenience function that runs all configuration steps.

    Note: CodeQL scanning is NOT configured here -- it is driven by the
    committed ``.github/workflows/codeql.yml`` workflow file, which the
    template generator copies into new repositories alongside every other
    workflow. No API call is required. See issue #431.

    Args:
        repo_full: Full repository name (owner/repo)
        description: Repository description
        visibility: Repository visibility ('public' or 'private')
        template_repo: Template repository to copy settings from

    Returns:
        True if all steps successful, False if any failed
    """
    results = [
        configure_repository_settings(repo_full, description, visibility, template_repo),
        configure_branch_protection(repo_full, template_repo),
        replicate_labels(repo_full, template_repo),
        enable_github_pages(repo_full),
    ]
    return all(results)
