#!/usr/bin/env python3
"""
repo_settings.py - GitHub repository settings configuration.

This module provides functions to configure GitHub repository settings,
branch protection, labels, and GitHub Pages. It can be used independently
of the full setup process.

CodeQL scanning is driven by the committed workflow file at
``.github/workflows/codeql.yml`` (advanced setup), replicated by the
template generator along with all other workflow files. A repository that
enabled GitHub's own CodeQL **default setup** before adopting that workflow
still needs one API call to turn default setup off -- see
:func:`disable_codeql_default_setup`. See issues #431 and #1034.

These functions are used by both setup_repo.py (initial setup) and
manage.py (updating existing repositories).
"""

from __future__ import annotations

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

from utils import TEMPLATE_REPO, GitHubCLI, Logger  # noqa: E402


def _is_forbidden(error: subprocess.CalledProcessError) -> bool:
    """Whether *error* is an HTTP 403 response from a ``gh api`` call."""
    return "403" in str(error.stderr)


def check_admin_access(repo_full: str) -> bool:
    """Check that the authenticated token has Administration access to *repo_full*.

    Every step in :func:`update_all_repo_settings` needs the repository's
    **Administration** permission: the repository-settings ``PATCH``, the
    ruleset ``POST``/``PUT`` calls, and :func:`disable_codeql_default_setup`'s
    ``GET``/``PATCH``. Checking once up front with a single
    ``GET /repos/{owner}/{repo}`` call turns a token that lacks it into one
    clear message instead of a 403 on every later step (#1034).

    Args:
        repo_full: Full repository name (owner/repo)

    Returns:
        True if the token has admin access, False otherwise.
    """
    Logger.step("Checking repository access...")

    try:
        response = GitHubCLI.api(f"repos/{repo_full}")
    except subprocess.CalledProcessError as e:
        Logger.error(f"Could not read repository settings for {repo_full}")
        if e.stderr:
            print(f"  Error: {e.stderr.strip()}")
        return False

    has_admin = bool((response or {}).get("permissions", {}).get("admin"))
    if not has_admin:
        Logger.error(f"The authenticated token lacks Administration access to {repo_full}.")
        Logger.info("Every step below needs it (repository settings, rulesets, CodeQL setup).")
        Logger.info(
            "Fine-grained PAT / GitHub App: grant the 'Administration' repository "
            "permission (read and write)."
        )
        Logger.info("Classic PAT / OAuth app: the 'repo' scope ('public_repo' for public repos).")
        return False

    Logger.success("Repository access confirmed")
    return True


def disable_codeql_default_setup(repo_full: str) -> bool:
    """Detect and disable GitHub's own CodeQL **default setup**, if enabled.

    #431 moved CodeQL scanning from GitHub's default setup to the committed
    advanced workflow ``.github/workflows/codeql.yml``. GitHub refuses to
    process SARIF uploaded by an advanced workflow while default setup stays
    enabled for the repository, so every ``CodeQL`` run fails until default
    setup is switched off. A repository created fresh from the template never
    had default setup enabled, so this is a no-op there -- it matters only for
    a repository that synced the template after already using GitHub's own
    CodeQL default setup (#1034).

    Checks ``GET /repos/{owner}/{repo}/code-scanning/default-setup``. If its
    ``state`` is already ``not-configured``, nothing more to do. If
    ``configured``, sends ``PATCH ... {"state": "not-configured"}``.

    A 403 on either call warns instead of failing the whole run -- it can mean
    the token lacks the Administration permission (read for the ``GET``,
    write for the ``PATCH``), that GitHub Advanced Security is not enabled for
    the repository, or (``PATCH`` only) that the repository is archived.

    Args:
        repo_full: Full repository name (owner/repo)

    Returns:
        True if default setup is confirmed off (already, or just disabled),
        False if it could not be checked or disabled.
    """
    Logger.step("Checking CodeQL default setup...")

    endpoint = f"repos/{repo_full}/code-scanning/default-setup"

    try:
        response = GitHubCLI.api(endpoint)
    except subprocess.CalledProcessError as e:
        if _is_forbidden(e):
            _warn_codeql_403(repo_full, "check (GET)")
            return False
        Logger.warning("Failed to check CodeQL default setup")
        if e.stderr:
            print(f"  Error: {e.stderr.strip()}")
        return False

    state = (response or {}).get("state")
    if state != "configured":
        Logger.success("CodeQL default setup already disabled")
        return True

    try:
        GitHubCLI.api(endpoint, method="PATCH", data={"state": "not-configured"})
    except subprocess.CalledProcessError as e:
        if _is_forbidden(e):
            _warn_codeql_403(repo_full, "disable (PATCH)")
            return False
        Logger.warning("Failed to disable CodeQL default setup")
        if e.stderr:
            print(f"  Error: {e.stderr.strip()}")
        return False

    Logger.success("CodeQL default setup disabled (codeql.yml now handles scanning)")
    return True


def _warn_codeql_403(repo_full: str, action: str) -> None:
    """Print the standard warning for a 403 from the default-setup endpoint.

    A 403 here does not always mean a missing token permission -- it can also
    mean GitHub Advanced Security is not enabled for the repository, or (for
    the ``PATCH`` only) that the repository is archived. All three causes are
    listed regardless of which call failed, since the two endpoints share one
    settings page to check (#1034).
    """
    Logger.warning(f"Could not {action} CodeQL default setup for {repo_full} (HTTP 403)")
    Logger.info("This can mean any of:")
    Logger.info("  - the token lacks the Administration permission (read for GET, write for PATCH)")
    Logger.info("  - GitHub Advanced Security is not enabled for this repository")
    Logger.info("  - the repository is archived (PATCH only)")
    Logger.info(f"  https://github.com/{repo_full}/settings/security_analysis")


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


def _ruleset_covers_default_branch(ruleset: dict[str, Any]) -> bool:
    """Whether *ruleset*'s conditions include ``~DEFAULT_BRANCH``, like the template's own."""
    include = ruleset.get("conditions", {}).get("ref_name", {}).get("include", [])
    return "~DEFAULT_BRANCH" in include


def _find_matching_ruleset(
    repo_full: str,
    existing_rulesets: list[dict[str, Any]],
    ruleset_name: str,
    full_ruleset: dict[str, Any],
) -> dict[str, Any] | None:
    """Return the existing ruleset to update in place, or None to create a new one.

    Matches by name first (unchanged behavior). Falls back to matching on the
    same ``target`` with ``~DEFAULT_BRANCH`` in ``conditions.ref_name.include``
    -- the same condition the template's own ruleset uses -- so a differently
    named ruleset that already covers the default branch is updated instead of
    duplicated. Reported in #1034: a repo named its ruleset ``main`` while the
    template's is ``main branch``, so only matching by name created a second,
    duplicate ruleset covering the same branch.

    The conditions fallback only fires when the template's own ruleset
    actually covers ``~DEFAULT_BRANCH`` -- a different kind of template
    ruleset (e.g. one targeting tags) is matched by name only, since there is
    no shared "same branch" meaning to fall back on.
    """
    for ruleset in existing_rulesets:
        if ruleset.get("name") == ruleset_name:
            return ruleset

    if not _ruleset_covers_default_branch(full_ruleset):
        return None

    target = full_ruleset.get("target")
    for ruleset in existing_rulesets:
        if ruleset.get("target") != target:
            continue
        existing_full = GitHubCLI.api(f"repos/{repo_full}/rulesets/{ruleset['id']}")
        if _ruleset_covers_default_branch(existing_full):
            return ruleset

    return None


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

        # Replicate each ruleset
        for template_ruleset in template_rulesets:
            # Get full ruleset details
            ruleset_id = template_ruleset["id"]
            full_ruleset = GitHubCLI.api(f"repos/{template_repo}/rulesets/{ruleset_id}")

            # Prepare ruleset data (remove read-only fields)
            ruleset_data: dict[str, Any] = {
                "name": full_ruleset["name"],
                "target": full_ruleset["target"],
                "enforcement": full_ruleset["enforcement"],
                "bypass_actors": full_ruleset.get("bypass_actors", []),
                "conditions": full_ruleset.get("conditions", {}),
                "rules": full_ruleset.get("rules", []),
            }

            ruleset_name = full_ruleset["name"]

            matched = _find_matching_ruleset(
                repo_full, existing_rulesets, ruleset_name, full_ruleset
            )
            if matched is not None:
                existing_id = matched["id"]
                matched_name = matched.get("name", ruleset_name)
                if matched_name != ruleset_name:
                    # Matched only by target + conditions, not by name: keep the
                    # existing ruleset's own name. The PUT would otherwise rename
                    # it to the template's name, which isn't what updating it in
                    # place is meant to do (#1034).
                    ruleset_data["name"] = matched_name
                GitHubCLI.api(
                    f"repos/{repo_full}/rulesets/{existing_id}",
                    method="PUT",
                    data=ruleset_data,
                )
                Logger.success(f"Ruleset '{matched_name}' updated")
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


DEFAULT_LABELS_FILE = ".github/labels.yml"


def sync_labels_from_file(repo_full: str, file: str = DEFAULT_LABELS_FILE) -> bool:
    """Reconcile the repository's labels against *file* (create AND update).

    Runs ``uv run doit labels_sync`` in the project's own environment instead
    of :func:`replicate_labels`'s create-only copy. ``replicate_labels`` never
    updated a label that already existed on the target repo -- its ``POST``
    failed with 422, which the ``except`` block swallowed, so a label kept its
    old color and description forever (#1034).

    It runs as a subprocess, not an import, so this module stays
    standard-library-only: ``bootstrap.py`` runs ``manage.py`` with a bare
    ``sys.executable``, which has no ``yaml``, ``rich`` or ``doit``. When
    ``uv`` or *file* is missing -- e.g. a checkout installed only via
    ``bootstrap.py --sync`` -- it falls back to :func:`replicate_labels` with a
    warning. ``setup_repo.py`` calls ``replicate_labels`` directly, because it
    runs before the repository is cloned.

    Args:
        repo_full: Full repository name (owner/repo), passed to ``gh`` as
            ``GH_REPO``.
        file: Path to the labels YAML file (default: ``.github/labels.yml``).

    Returns:
        True if the reconcile (or the fallback) succeeded, False otherwise.
    """
    Logger.step("Reconciling labels...")

    if shutil.which("uv") is None or not Path(file).is_file():
        Logger.warning(
            f"Cannot run `doit labels_sync` (uv or {file} missing); "
            "falling back to a create-only copy of the template's labels."
        )
        return replicate_labels(repo_full)

    result = subprocess.run(  # nosec B603 B607 - fixed argument list, no shell
        ["uv", "run", "doit", "labels_sync", f"--file={file}"],
        env={**os.environ, "GH_REPO": repo_full},
        check=False,
    )
    if result.returncode != 0:
        Logger.warning(f"`doit labels_sync` failed (exit {result.returncode})")
        Logger.info(f"Reconcile labels manually: uv run doit labels_sync --file={file}")
        return False

    Logger.success("Labels reconciled")
    return True


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

    This is a convenience function that runs all configuration steps, in order:

    1. :func:`check_admin_access` -- stops before anything else runs if the
       token lacks the Administration permission, so a missing permission
       fails once with one clear message instead of a 403 on every step
       below (#1034).
    2. :func:`configure_repository_settings`
    3. :func:`configure_branch_protection`
    4. :func:`disable_codeql_default_setup` -- CodeQL scanning itself is
       driven by the committed ``.github/workflows/codeql.yml`` workflow
       file, which the template generator copies into new repositories
       alongside every other workflow. This step only switches off GitHub's
       own CodeQL *default setup* when a repository had it enabled before
       adopting that workflow -- a fresh repository created from the
       template never did, so this is a no-op there. See issues #431, #1034.
    5. :func:`sync_labels_from_file` -- reconciles (creates *and* updates)
       labels against ``.github/labels.yml`` via ``doit labels_sync``,
       falling back to the create-only :func:`replicate_labels` when that
       cannot run.
    6. :func:`enable_github_pages`

    Args:
        repo_full: Full repository name (owner/repo)
        description: Repository description
        visibility: Repository visibility ('public' or 'private')
        template_repo: Template repository to copy settings from

    Returns:
        True if every step succeeded, False if the admin check or any later
        step failed.
    """
    if not check_admin_access(repo_full):
        return False

    results = [
        configure_repository_settings(repo_full, description, visibility, template_repo),
        configure_branch_protection(repo_full, template_repo),
        disable_codeql_default_setup(repo_full),
        sync_labels_from_file(repo_full),
        enable_github_pages(repo_full),
    ]
    return all(results)
