---
title: Template Management
description: Unified interface for creating projects, checking updates, and syncing
audience:
  - users
tags:
  - template
  - tooling
---

# Template Management

The `manage.py` script provides a unified interface for all template operations. It auto-detects your project context and recommends appropriate actions.

## Quick Start

```bash
# Interactive mode (recommended)
python tools/pyproject_template/manage.py

# Or use quick commands
python tools/pyproject_template/manage.py create     # Create new project
python tools/pyproject_template/manage.py check      # Check for updates
python tools/pyproject_template/manage.py sync       # Mark as synced
```

## Menu Options

### [1] Create new project from template

Creates a new GitHub repository from the template:

1. Creates the repository on GitHub
2. Configures repository settings
3. Clones locally and configures placeholders
4. Sets up development environment (dependencies, pre-commit hooks)
5. Configures branch protection and other GitHub settings
6. Saves template sync state

**When to use:** You're starting a brand new project and don't have a repository yet.

### [2] Configure project

Re-runs the configuration script to update placeholders:

- Project name, package name, PyPI name
- Author information
- GitHub user/repo
- Description

**When to use:** You cloned the template manually and need to configure it, or you want to update project metadata.

### [3] Check for template updates

Compares your project against the latest template:

1. Downloads the latest template
2. Shows files that differ from the template
3. Provides diff commands for reviewing changes
4. Shows GitHub compare URL for commit history

**When to use:** You want to see what improvements have been made to the template since you last synced.

**Important:** This does NOT automatically apply changes. You must manually review and apply changes you want.

#### Excluding upstream files from drift checks

Downstream projects often diverge from the template in deliberate ways — a
FastAPI example app for a tool that isn't a service, a Click `test_cli.py`
when the project uses Typer, and so on. Without a way to silence those, every
`check` run re-flags them and buries real upstream changes.

Add a hand-managed file at `.config/pyproject_template/sync-exclude.toml`
listing upstream-relative glob patterns:

```toml
exclude = [
    "examples/api/**",
    "src/package_name/core.py",
    "tests/test_cli.py",
]
```

- Patterns are matched against upstream-relative paths via `fnmatch.fnmatch`,
  so `*` matches any characters (including `/`) and `**` is a recursive
  wildcard for subtrees.
- Matched files are removed from the actionable drift list. `check` prints a
  trailing line like `Skipped per project policy: 15 files
  (see .config/pyproject_template/sync-exclude.toml)` so the suppression stays
  visible without crowding the signal.
- Pass `--show-excluded` to list every excluded path:
  ```bash
  python tools/pyproject_template/manage.py check --show-excluded
  ```
- The hardcoded skip set (build artifacts: `.git`, `__pycache__`, `.venv`,
  `uv.lock`, etc.) takes precedence and is not user-configurable. A file that
  matches the hardcoded set never appears in either list.
- This file is **separate** from `settings.toml` on purpose: `settings.toml`
  is rewritten by `manage.py sync`, which would clobber any user-managed
  excludes. `sync-exclude.toml` is never touched by automation.

### [4] Update repository settings

Configures GitHub repository settings:

- Repository description and features
- Branch protection rulesets
- Labels
- GitHub Pages

CodeQL code scanning is configured via the committed workflow file
`.github/workflows/codeql.yml` rather than an API call, so it replicates
automatically when the template generator copies workflow files into a new
repository. No explicit "update repository settings" step is required to
enable it.

**When to use:** You want to update GitHub settings to match the latest template configuration.

### [5] Mark as synced to latest template

After reviewing and applying template changes, marks your project as synced:

1. Updates `.config/pyproject_template/settings.toml` with the reviewed commit
2. Cleans up the downloaded template directory

**When to use:** After running "Check for template updates" and applying the changes you want.

### [6] Clean up template files

Removes template-specific files that are no longer needed after project setup:

**Setup only mode:** Removes files only needed for initial setup:

- `bootstrap.py` - Remote setup script
- `tools/pyproject_template/setup_repo.py` - Repository creation
- `docs/template/new-project.md` - New project instructions
- `docs/template/migration.md` - Migration guide

This keeps the template update checking capability intact.

**All mode:** Removes all template files:

- All setup files (above)
- `tools/pyproject_template/` directory (entire)
- `docs/template/` directory (entire)
- `.config/pyproject_template/` directory

⚠️ **Warning:** After removing all template files, you won't be able to check for template updates.

**When to use:** After setting up your project, to clean up files you no longer need.

You can also use the doit task:

```bash
doit template_clean              # Interactive mode
doit template_clean --setup      # Remove setup files only
doit template_clean --all        # Remove all template files
doit template_clean --dry-run    # Preview what would be deleted
```

## Workflow: Staying Up to Date

The recommended workflow for keeping your project in sync with template improvements:

### 1. Check for updates

```bash
python tools/pyproject_template/manage.py
# Select [3] Check for template updates
```

This downloads the latest template and shows what's different. The template files are kept at `tmp/extracted/pyproject-template-main/` for review.

### 2. Review changes

Use the provided diff commands to compare files:

```bash
diff .github/workflows/ci.yml tmp/extracted/pyproject-template-main/.github/workflows/ci.yml
```

Or view the commit history on GitHub using the provided compare URL.

### 3. Apply changes you want

Manually copy or merge changes from the template into your project. Be selective - not all template changes may apply to your project.

### 4. Mark as synced

```bash
python tools/pyproject_template/manage.py
# Select [5] Mark as synced to latest template
```

This updates your sync state and cleans up the template directory.

### 5. Commit the sync state

Follow the Issue → Branch → PR workflow:

```bash
# Create an issue
doit issue --type=chore --title='Sync template state'

# Create branch and commit
git checkout -b chore/<issue#>-sync-template-state
git add .config/pyproject_template/settings.toml
git commit -m 'chore: sync template state'
git push -u origin HEAD

# Create PR
doit pr --title='chore: sync template state'
```

## Settings File

The template sync state is stored in `.config/pyproject_template/settings.toml`:

```toml
[template]
commit = "7dc4dba86601ebb2a63fb9b60138af2da1d8d4be"
commit_date = "2025-01-15"
```

This tracks which template commit your project was last synced with.

## CLI Options

```bash
# Quick actions
python tools/pyproject_template/manage.py create     # Create new project
python tools/pyproject_template/manage.py configure  # Re-run configuration
python tools/pyproject_template/manage.py check      # Check for updates
python tools/pyproject_template/manage.py repo       # Update repo settings
python tools/pyproject_template/manage.py sync       # Mark as synced

# Flags
python tools/pyproject_template/manage.py --dry-run  # Preview without changes
python tools/pyproject_template/manage.py --yes      # Non-interactive mode
```

## Project Detection

The script auto-detects your project context:

| Context | Recommended Action |
|---------|-------------------|
| No git repository | Create new project |
| Has git but unconfigured | Configure project |
| Template downloaded, not synced | Mark as synced |
| Template outdated | Check for updates |
| Up to date | No action needed |

## Troubleshooting

### "No reviewed template found"

Run "Check for template updates" first to download and review the template before marking as synced.

### Settings file not committed

Branch protection prevents direct commits to main. Follow the Issue → Branch → PR workflow shown after marking as synced.

### Package name validation fails

Python package names must be PEP 8 compliant: lowercase letters, numbers, and underscores only. The script will suggest a valid name.
