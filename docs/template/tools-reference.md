---
title: Template Tools Reference
description: Complete reference for all template tools in tools/pyproject_template/
audience:
  - users
  - contributors
tags:
  - template
  - reference
  - tooling
---

# Template Tools Reference

Complete reference for all template tools in `tools/pyproject_template/`.

> **Note:** For most use cases, the **[Template Manager](manage.md)** (`manage.py`) provides a unified, interactive interface to all these tools. Use this reference for advanced usage, scripting, or understanding the underlying CLI options.

## bootstrap.py

Remote bootstrap script for one-command setup.

### Usage

```bash
curl -sSL https://raw.githubusercontent.com/endavis/pyproject-template/main/bootstrap.py | python3
```

### Description

This is a thin wrapper that downloads and runs `setup_repo.py`. It's designed to be fetched and executed directly from the template repository.

### Requirements

- Python 3.12+
- Internet connection

---

> **Run these through `manage.py`.** `setup_repo.py`, `configure.py` and
> `check_template_updates.py` refuse to run directly — they print
> *"This script should not be run directly"* and do nothing. `manage.py` is the entry
> point for all three; the sections below give the command for each.

## setup_repo.py

Full repository setup orchestration from the template.

### Usage

```bash
python tools/pyproject_template/manage.py repo
```

### Description

Automates the complete process of creating a new GitHub repository from this template:

1. Creates repository from template on GitHub
2. Configures repository settings
3. Sets up branch protection rules
4. Replicates labels from template
5. Runs `configure.py` for placeholder replacement
6. Clones repository locally
7. Displays post-setup checklist

### Interactive Prompts

| Prompt | Description |
|--------|-------------|
| Repository name | Name for the new GitHub repository |
| Description | Short project description |
| Visibility | Public or private repository |
| Package name | Python import name (snake_case) |
| Author name | Your name for package metadata |
| Author email | Your email for package metadata |

### Requirements

- GitHub CLI (`gh`) installed and authenticated
- Git installed
- Python 3.12+

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Error (missing requirements, API failure, etc.) |

---

## configure.py

Replace placeholder values with your project information.

### Usage

```bash
python tools/pyproject_template/manage.py configure
```

### Description

Interactively prompts for project information and replaces all placeholder values throughout the template files.

### Interactive Prompts

| Prompt | Default | Description |
|--------|---------|-------------|
| Project name | Package Name | Display name for the project |
| Package name | package_name | Python import name (snake_case) |
| PyPI name | package-name | Name on PyPI (typically hyphenated) |
| Author name | Your Name | Author for package metadata |
| Author email | your.email@example.com | Contact email |
| GitHub username | username | Your GitHub username |
| Description | A short description of your package | One-line project description |

### Files Modified

- `pyproject.toml`
- `README.md`
- `mkdocs.yml`
- `dodo.py`
- `AGENTS.md`
- `CHANGELOG.md`
- `.github/workflows/*`
- `.github/SECURITY.md`
- `docs/*`
- `examples/*`

### Actions Performed

1. Replaces placeholder strings with provided values
2. Renames `src/package_name/` to `src/your_package_name/`
3. Updates all URLs and badge links
4. Updates documentation references

### Requirements

- Python 3.12+
- Must be run from template root directory

### Placeholder Markers

Prose files in the template (`README.md`, `CHANGELOG.md`, `docs/**/*.md`, most files under `.github/`) use explicit marker tokens like `__PACKAGE_NAME__`, `__GH_OWNER__`, `__AUTHOR_NAME__`, `__PYPI_NAME__`, `__PROJECT_NAME__`, `__AUTHOR_EMAIL__`, and `__DESCRIPTION__`. The spawn flow (`setup_repo.py` / `configure.py`) substitutes these at placeholder-replacement time. Markers are used instead of bare identifier literals (`package_name`, `username`) so substring collisions cannot corrupt identifiers like `validate_package_name`. Runtime-critical files (`pyproject.toml`, `mkdocs.yml`, `dodo.py`, workflows, `LICENSE`, `.envrc`, `.pre-commit-config.yaml`) keep literal placeholder values so the template repo itself remains runnable. Python source and test files keep literal identifiers but get word-boundary regex protection during substitution.

---

## check_template_updates.py

Compare your project against a template commit — `main` by default (ADR-9020).

### Usage

```bash
python tools/pyproject_template/manage.py check
```

### Description

Fetches the latest template release (or specified version), compares it against your project, and shows what files differ.

### CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `--template-version` | Latest release | Compare against specific version (e.g., `v2.2.0`) |
| `--skip-changelog` | False | Don't open CHANGELOG.md in editor |
| `--keep-template` | False | Keep downloaded template after comparison |

### Examples

```bash
# Compare against `main` (the default)
python tools/pyproject_template/manage.py check

# Compare against a specific tag, branch or commit SHA
python tools/pyproject_template/manage.py check --template-version v2.2.0
```

`check_template_updates.py` refuses to run directly — `manage.py` is the entry point. See
[#778](https://github.com/endavis/pyproject-template/issues/778) for the other invocations in this
document that still need the same treatment.

### Output Categories

| Category | Description |
|----------|-------------|
| Modified | Files that exist in both but have different content |
| Missing | Files in template that don't exist in your project |
| Extra | Files in your project that don't exist in template |

### Skipped Paths

The comparison automatically skips:

- `.git/`
- `.venv/`, `venv/`
- `__pycache__/`
- `tmp/`
- `*.pyc`, `*.pyo`
- `*.egg-info/`
- `.coverage`, `htmlcov/`
- Project-specific source files

### Requirements

- Python 3.12+
- Internet connection (to fetch template)
- `$EDITOR` environment variable (for changelog viewing)

---

## cleanup.py

Remove template-specific files after project setup.

### Usage

```bash
python tools/pyproject_template/cleanup.py
python tools/pyproject_template/cleanup.py --setup
python tools/pyproject_template/cleanup.py --all
python tools/pyproject_template/cleanup.py --dry-run
```

Or use the doit task:

```bash
doit template_clean
doit template_clean --setup
doit template_clean --all
doit template_clean --dry-run
```

### Description

Removes template-specific files that are no longer needed after project setup. Two cleanup modes are available:

**Setup only mode (`--setup`):** Removes files only needed for initial setup:

- `bootstrap.py` - Remote setup script
- `tools/pyproject_template/setup_repo.py` - Repository creation
- `docs/template/new-project.md` - New project instructions
- `docs/template/migration.md` - Migration guide

This mode keeps the template update checking capability intact.

**All mode (`--all`):** Removes all template files:

- All setup files (above)
- `tools/pyproject_template/` directory (entire)
- `docs/template/` directory (entire)
- `.config/pyproject_template/` directory

### CLI Options

| Option | Description |
|--------|-------------|
| `--setup` | Remove setup files only (keep update checking) |
| `--all` | Remove all template files (no future updates) |
| `--dry-run` | Show what would be deleted without deleting |

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Error (conflicting flags, deletion failure) |

---

## repo_settings.py

GitHub repository settings configuration functions.

### Description

Internal module providing functions to configure GitHub repository settings. Used by both `setup_repo.py` (initial setup) and `manage.py` (updating existing repositories).

### Functions

| Function | Description |
|----------|-------------|
| `configure_repository_settings()` | Configure repo description, features, security settings |
| `configure_branch_protection()` | Set up branch protection rulesets |
| `replicate_labels()` | Copy labels from template repository |
| `enable_github_pages()` | Enable GitHub Pages for documentation |
| `update_all_repo_settings()` | Convenience function to run all configuration steps |

!!! note "CodeQL scanning is workflow-driven"
    CodeQL code scanning is configured via the committed
    `.github/workflows/codeql.yml` workflow rather than an API call. It is
    replicated automatically when the template generator copies workflow
    files into a new repository, so no dedicated function (or manual setup
    step) is required. See issue #431 for the migration from default setup
    to this advanced workflow file.

### Usage

This module is not meant to be run directly. It's imported by other template tools:

```python
from tools.pyproject_template.repo_settings import update_all_repo_settings

update_all_repo_settings(
    repo_full="user/repo",
    description="My project description",
)
```

---

## utils.py

Shared utilities used by other template tools.

### Description

Internal module providing common functionality:

- `Colors` - ANSI color codes for terminal output
- `Logger` - Formatted logging (info, success, warning, error)
- `GitHubCLI` - Wrapper for `gh` CLI commands
- `prompt()` - Interactive input with defaults
- `prompt_confirm()` - Yes/no confirmation prompts
- `update_file()` - Safe file content replacement
- `download_and_extract_archive()` - Download and extract zip/tar archives

### Usage

This module is not meant to be run directly. It's imported by other template tools:

```python
from tools.pyproject_template.utils import Logger, prompt

Logger.info("Starting process...")
name = prompt("Enter name", default="default_value")
```
