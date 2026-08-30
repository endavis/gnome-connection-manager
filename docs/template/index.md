---
title: Using This Template
description: Overview of using pyproject-template for your Python projects
audience:
  - users
tags:
  - template
  - getting-started
---

# Using This Template

This section covers how to use the pyproject-template for your Python projects.

## Quick Start: Template Manager

The easiest way to work with the template is through the unified **[Template Manager](manage.md)**:

```bash
python tools/pyproject_template/manage.py
```

This interactive menu provides access to all template operations - creating projects, configuring, checking for updates, and more.

## Choose Your Path

### Starting Fresh?

**[New Project Setup](new-project.md)** - Create a new Python project from this template.

- **Automated setup** (recommended): One command creates and configures everything
- **Manual setup**: Clone the template and configure it yourself

> **Note:** The automated setup removes the template management suite
> (`tools/pyproject_template/`, `docs/template/`, `bootstrap.py`) from your
> spawned project by default. Consumers who want ongoing template sync can
> reinstall the suite with `bootstrap.py --sync` — see
> **[Keeping Up to Date](updates.md)**.

### Have an Existing Project?

**[Migration Guide](migration.md)** - Bring your existing Python project into this template.

- Preserves your code while adopting template tooling
- Step-by-step checklist for a smooth migration

### Already Using This Template?

**[Keeping Up to Date](updates.md)** - Stay in sync with template improvements.

- Compare your project against the latest template
- Selectively merge updates you want

**[AI Sync Checklist](ai-sync-checklist.md)** - Structured guide for AI agents performing synchronization.

- Step-by-step phases from pre-flight through commit
- Decision points where AI should ask for user input

## Template Tools

All template tools are located in `tools/pyproject_template/`:

| Tool | Purpose |
|------|---------|
| **`manage.py`** | **Unified interface for all operations (recommended)** |
| `bootstrap.py` | Remote setup script (curl and run) |
| `setup_repo.py` | Full repository setup orchestration |
| `configure.py` | Replace placeholders with your project info |
| `check_template_updates.py` | Compare project against latest template |
| `cleanup.py` | Remove template files after setup |

See the **[Template Manager](manage.md)** for the recommended interactive interface, or the **[Tools Reference](tools-reference.md)** for detailed CLI documentation of individual tools.

## What the Template Provides

When you use this template, you get:

- **Modern Python packaging** with `pyproject.toml` and `uv`
- **Task automation** with `doit` (format, lint, test, release)
- **Code quality** with `ruff` (linting + formatting) and `mypy` (type checking)
- **Testing** with `pytest` and coverage reporting
- **CI/CD** with GitHub Actions (test, release to PyPI)
- **Documentation** with MkDocs and Material theme
- **Pre-commit hooks** enforcing code quality and conventional commits
- **AI agent support** with pre-configured settings for Claude, Copilot, Codex, and Antigravity
