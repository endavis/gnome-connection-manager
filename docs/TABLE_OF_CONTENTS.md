# All Documents

Complete index of all documentation, organized by audience and as a full alphabetical list.

> These lists are auto-generated from document frontmatter.
> Run `python tools/generate_doc_toc.py` to update.

## By Audience

### Using GCM
<!-- BEGIN:tag=gcm-guide -->
- [Gnome Connection Manager](index.md) - What GCM is, and where to start reading
- [Hosts and folders in GCM](HOSTS-AND-FOLDERS.md) - The server tree: making and moving folders, putting it in the order you want, and what export and import carry
- [Using terminals in GCM](TERMINAL-USAGE.md) - Selection, copy and paste, session recording, OSC 52, the buffer viewer, tab titles, tabs that need your attention, font zoom, the shortcut table, a host's first connection, and what GCM does with a gcm.conf it cannot read
<!-- END:tag=gcm-guide -->

### Working on GCM
<!-- BEGIN:tag=gcm-dev -->
- [ADR template](decisions/adr-template.md) - The skeleton doit adr copies for a new architecture decision record; not a decision itself
- [ADR-0001: A stable id on every host record](decisions/0001-a-stable-id-on-every-host-record.md) - Why each saved host carries a random id, and what that makes possible
- [ADR-0002: Folders are records, not a path string](decisions/0002-folders-are-records-not-a-path-string.md) - Why the folder tree is stored as records keyed by id, with group kept as a derived path
- [Connection Manager - Feature Specification](SPEC.md) - A statement of behaviour, written as a spec for a Qt 6 port that is not being built
- [Development Guide](DEVELOPING.md) - Setting up an environment, the task runner, and running the tests
- [Gnome Connection Manager - Modern Project Structure](PROJECT_STRUCTURE.md) - What lives where, and where the modernization work stands
<!-- END:tag=gcm-dev -->

### Using the project template

These come from [pyproject-template](https://github.com/endavis/pyproject-template), which
this project's tooling is vendored from. "Users" here means users of the template, not of GCM.

<!-- BEGIN:audience=users -->
- [Doit Tasks Reference](development/doit-tasks-reference.md) - Complete reference for all doit automation tasks
- [GitHub Repository Settings](development/github-repository-settings.md) - Complete reference for all GitHub repository settings the template expects
- [Keeping Up to Date](template/updates.md) - Stay in sync with improvements to the pyproject-template
- [Migration Guide](template/migration.md) - Migrate existing Python projects to use this template
- [New Project Setup](template/new-project.md) - Create a new Python project from this template
- [Template Management](template/manage.md) - Unified interface for creating projects, checking updates, and syncing
- [Template Tools Reference](template/tools-reference.md) - Complete reference for all template tools in tools/pyproject_template/
- [Using This Template](template/index.md) - Overview of using pyproject-template for your Python projects
<!-- END:audience=users -->

### For Contributors
<!-- BEGIN:audience=contributors -->
- [ADR template](decisions/adr-template.md) - The skeleton doit adr copies for a new architecture decision record; not a decision itself
- [ADR-0001: A stable id on every host record](decisions/0001-a-stable-id-on-every-host-record.md) - Why each saved host carries a random id, and what that makes possible
- [ADR-0002: Folders are records, not a path string](decisions/0002-folders-are-records-not-a-path-string.md) - Why the folder tree is stored as records keyed by id, with group kept as a derived path
- [AI Agent Setup Guide](development/AI_SETUP.md) - Configure Claude, Copilot, Codex, and Antigravity for this project
- [AI Agent Token-Efficiency Add-Ons](development/ai/token-efficiency-add-ons.md) - Opt-in catalogue of external tools for reducing token usage in Claude Code sessions
- [AI Architectural Conventions](development/ai/architectural-conventions.md) - Imperative-form architectural rules AI agents must follow when generating code
- [AI Command Blocking](development/ai/command-blocking.md) - Hooks that block dangerous commands from AI agents
- [AI Enforcement Principles](development/ai/enforcement-principles.md) - How we enforce AI agent behavior in code and settings
- [Auto-Checkpoint and Session-Restore Hooks](development/ai/auto-checkpoint-hook.md) - PreCompact and SessionStart hooks that preserve context across autocompact events
- [CI/CD Testing Guide](development/ci-cd-testing.md) - GitHub Actions pipelines for testing, linting, and coverage
- [Claude Code Statusline](development/ai/statusline.md) - Custom statusline showing git branch, Python version, and project info
- [Connection Manager - Feature Specification](SPEC.md) - A statement of behaviour, written as a spec for a Qt 6 port that is not being built
- [Dependabot Auto-merge](development/dependabot-automerge.md) - How the dependabot auto-merge workflow evaluates, enables, and skips PRs
- [Development Guide](DEVELOPING.md) - Setting up an environment, the task runner, and running the tests
- [Doit Tasks Reference](development/doit-tasks-reference.md) - Complete reference for all doit automation tasks
- [First 5 Minutes with an AI Agent](development/ai/first-5-minutes.md) - Narrative walkthrough of the AI agent workflow from issue to merge
- [GitHub Repository Settings](development/github-repository-settings.md) - Complete reference for all GitHub repository settings the template expects
- [Gnome Connection Manager - Modern Project Structure](PROJECT_STRUCTURE.md) - What lives where, and where the modernization work stands
- [LSP Tool and Diagnostic Noise](development/ai/lsp-tool.md) - What the LSP tool gives an AI agent, why pyright diagnostics arrive stale, and the two opt-outs agents can flip on themselves
- [Optional Extensions](development/extensions.md) - Additional tools and extensions for testing, security, and more
- [Python Project Coding Standards](development/coding-standards.md) - Guidelines for exceptions, typing, structure, testing, and documentation
- [Release Automation & Security](development/release-and-automation.md) - Automated versioning, release management, and security tooling
- [Ruff Auto-Fix on Edit Hook](development/ai/ruff-fix-hook.md) - PostToolUse hook that runs ruff --fix on edited Python files
- [Slash Commands and Workflows](development/ai/slash-commands.md) - Reference for the slash commands and dual-agent workflow this template ships with
- [Template Tools Reference](template/tools-reference.md) - Complete reference for all template tools in tools/pyproject_template/
- [Tooling Roles and Architectural Boundaries](development/tooling-roles.md) - What each tool is for, who uses it, and where runtime code ends and dev tooling begins
<!-- END:audience=contributors -->

### For AI Agents
<!-- BEGIN:audience=ai-agents -->
- [AI Agent Setup Guide](development/AI_SETUP.md) - Configure Claude, Copilot, Codex, and Antigravity for this project
- [AI Agent Sync Checklist](template/ai-sync-checklist.md) - Step-by-step checklist for AI agents synchronizing downstream projects with pyproject-template
- [AI Agent Token-Efficiency Add-Ons](development/ai/token-efficiency-add-ons.md) - Opt-in catalogue of external tools for reducing token usage in Claude Code sessions
- [AI Architectural Conventions](development/ai/architectural-conventions.md) - Imperative-form architectural rules AI agents must follow when generating code
- [AI Command Blocking](development/ai/command-blocking.md) - Hooks that block dangerous commands from AI agents
- [AI Enforcement Principles](development/ai/enforcement-principles.md) - How we enforce AI agent behavior in code and settings
- [Auto-Checkpoint and Session-Restore Hooks](development/ai/auto-checkpoint-hook.md) - PreCompact and SessionStart hooks that preserve context across autocompact events
- [Claude Code Statusline](development/ai/statusline.md) - Custom statusline showing git branch, Python version, and project info
- [First 5 Minutes with an AI Agent](development/ai/first-5-minutes.md) - Narrative walkthrough of the AI agent workflow from issue to merge
- [LSP Tool and Diagnostic Noise](development/ai/lsp-tool.md) - What the LSP tool gives an AI agent, why pyright diagnostics arrive stale, and the two opt-outs agents can flip on themselves
- [Ruff Auto-Fix on Edit Hook](development/ai/ruff-fix-hook.md) - PostToolUse hook that runs ruff --fix on edited Python files
- [Slash Commands and Workflows](development/ai/slash-commands.md) - Reference for the slash commands and dual-agent workflow this template ships with
- [Tooling Roles and Architectural Boundaries](development/tooling-roles.md) - What each tool is for, who uses it, and where runtime code ends and dev tooling begins
<!-- END:audience=ai-agents -->

## Complete Index
<!-- BEGIN:all -->
- [ADR template](decisions/adr-template.md) - The skeleton doit adr copies for a new architecture decision record; not a decision itself
- [ADR-0001: A stable id on every host record](decisions/0001-a-stable-id-on-every-host-record.md) - Why each saved host carries a random id, and what that makes possible
- [ADR-0002: Folders are records, not a path string](decisions/0002-folders-are-records-not-a-path-string.md) - Why the folder tree is stored as records keyed by id, with group kept as a derived path
- [AI Agent Setup Guide](development/AI_SETUP.md) - Configure Claude, Copilot, Codex, and Antigravity for this project
- [AI Agent Sync Checklist](template/ai-sync-checklist.md) - Step-by-step checklist for AI agents synchronizing downstream projects with pyproject-template
- [AI Agent Token-Efficiency Add-Ons](development/ai/token-efficiency-add-ons.md) - Opt-in catalogue of external tools for reducing token usage in Claude Code sessions
- [AI Architectural Conventions](development/ai/architectural-conventions.md) - Imperative-form architectural rules AI agents must follow when generating code
- [AI Command Blocking](development/ai/command-blocking.md) - Hooks that block dangerous commands from AI agents
- [AI Enforcement Principles](development/ai/enforcement-principles.md) - How we enforce AI agent behavior in code and settings
- [Auto-Checkpoint and Session-Restore Hooks](development/ai/auto-checkpoint-hook.md) - PreCompact and SessionStart hooks that preserve context across autocompact events
- [CI/CD Testing Guide](development/ci-cd-testing.md) - GitHub Actions pipelines for testing, linting, and coverage
- [Claude Code Statusline](development/ai/statusline.md) - Custom statusline showing git branch, Python version, and project info
- [Connection Manager - Feature Specification](SPEC.md) - A statement of behaviour, written as a spec for a Qt 6 port that is not being built
- [Consumer Notes](template/consumer-notes.md) - Breaking changes and behaviour changes that arrive when a project syncs from the template.
- [Cross-Agent Delegation Matrix](development/ai/cross-agent-delegation.md)
- [Dependabot Auto-merge](development/dependabot-automerge.md) - How the dependabot auto-merge workflow evaluates, enables, and skips PRs
- [Development Guide](DEVELOPING.md) - Setting up an environment, the task runner, and running the tests
- [Doit Tasks Reference](development/doit-tasks-reference.md) - Complete reference for all doit automation tasks
- [First 5 Minutes with an AI Agent](development/ai/first-5-minutes.md) - Narrative walkthrough of the AI agent workflow from issue to merge
- [GitHub Repository Settings](development/github-repository-settings.md) - Complete reference for all GitHub repository settings the template expects
- [Gnome Connection Manager](index.md) - What GCM is, and where to start reading
- [Gnome Connection Manager - Modern Project Structure](PROJECT_STRUCTURE.md) - What lives where, and where the modernization work stands
- [Hosts and folders in GCM](HOSTS-AND-FOLDERS.md) - The server tree: making and moving folders, putting it in the order you want, and what export and import carry
- [install_tools Framework](development/install-tools-framework.md)
- [Keeping Up to Date](template/updates.md) - Stay in sync with improvements to the pyproject-template
- [LSP Tool and Diagnostic Noise](development/ai/lsp-tool.md) - What the LSP tool gives an AI agent, why pyright diagnostics arrive stale, and the two opt-outs agents can flip on themselves
- [Migration Guide](template/migration.md) - Migrate existing Python projects to use this template
- [New Project Setup](template/new-project.md) - Create a new Python project from this template
- [Optional Extensions](development/extensions.md) - Additional tools and extensions for testing, security, and more
- [Python Project Coding Standards](development/coding-standards.md) - Guidelines for exceptions, typing, structure, testing, and documentation
- [Release Automation & Security](development/release-and-automation.md) - Automated versioning, release management, and security tooling
- [Ruff Auto-Fix on Edit Hook](development/ai/ruff-fix-hook.md) - PostToolUse hook that runs ruff --fix on edited Python files
- [Slash Commands and Workflows](development/ai/slash-commands.md) - Reference for the slash commands and dual-agent workflow this template ships with
- [Template Management](template/manage.md) - Unified interface for creating projects, checking updates, and syncing
- [Template Tools Reference](template/tools-reference.md) - Complete reference for all template tools in tools/pyproject_template/
- [Tooling Roles and Architectural Boundaries](development/tooling-roles.md) - What each tool is for, who uses it, and where runtime code ends and dev tooling begins
- [Using terminals in GCM](TERMINAL-USAGE.md) - Selection, copy and paste, session recording, OSC 52, the buffer viewer, tab titles, tabs that need your attention, font zoom, the shortcut table, a host's first connection, and what GCM does with a gcm.conf it cannot read
- [Using This Template](template/index.md) - Overview of using pyproject-template for your Python projects
<!-- END:all -->

---

## Contributing to Documentation

When adding new documentation:

1. Add frontmatter with `title`, `description`, `audience`, and `tags`:
   ```yaml
   ---
   title: My New Guide
   description: Short description for the index
   audience:
     - users
     - contributors
   tags:
     - setup
     - getting-started
   ---
   ```

2. Place the file in the appropriate directory

3. Run `python tools/generate_doc_toc.py` to update this index

4. The pre-commit hook will also run automatically on commit
