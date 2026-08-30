# Contributing to Gnome Connection Manager

Thank you for your interest in contributing to this project! We welcome contributions from everyone.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [How to Contribute](#how-to-contribute)
- [Coding Standards](#coding-standards)
- [Testing Guidelines](#testing-guidelines)
- [Commit Guidelines](#commit-guidelines)
- [Pull Request Process](#pull-request-process)
- [Release Process](#release-process)
- [Reporting Bugs](#reporting-bugs)
- [Requesting Features](#requesting-features)

## Code of Conduct

This project adheres to the Contributor Covenant [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## Getting Started

1. Fork the repository on GitHub
2. Clone your fork locally
3. Set up the development environment (see below)
4. Create a new branch for your changes
5. Make your changes
6. Run tests and checks
7. Submit a pull request

## Development Setup

### Prerequisites

- Python 3.12 or higher
- [uv](https://github.com/astral-sh/uv) - Fast Python package installer
- [direnv](https://direnv.net/) - Automatic environment management (recommended)

### Initial Setup

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/gnome-connection-manager.git
cd gnome-connection-manager

# Set up direnv
direnv allow
# Optional: Create .envrc.local for personal settings
cp .envrc.local.example .envrc.local

# Install dependencies (creates venv automatically)
uv sync --all-extras

# Install pre-commit hooks
doit pre_commit_install
```

### Available Commands

View all available development tasks:
```bash
doit list
```

Common commands:
```bash
doit test          # Run tests
doit coverage      # Run tests with coverage
doit lint          # Run linting
doit format        # Format code
doit type_check    # Run type checking
doit check         # Run all checks
doit benchmark     # Run performance benchmarks
doit cleanup       # Clean build artifacts
```

## How to Contribute

### Types of Contributions

We welcome many types of contributions:

- **Bug fixes** - Fix issues in the codebase
- **New features** - Add new functionality
- **Documentation** - Improve docs, docstrings, examples
- **Tests** - Add or improve test coverage
- **Refactoring** - Improve code quality without changing behavior
- **Performance** - Optimize performance

### Before You Start

1. **Check existing issues** - See if someone is already working on it
2. **Open an issue** - Discuss your proposed changes before starting work
3. **Get feedback** - Especially for large changes or new features

## Coding Standards

### Python Style

- **Python version:** 3.12+ with modern type hints
- **Line length:** Max 100 characters
- **Docstrings:** Google-style for all public APIs
- **Type hints:** Required for all public functions/methods
- **Naming:** `snake_case` for functions/variables, `PascalCase` for classes
- **File I/O:** Always pass `encoding="utf-8"` to `Path.read_text()`,
  `Path.write_text()`, text-mode `open()`, and `tempfile.NamedTemporaryFile()`.
  Omitting the kwarg falls back to `locale.getpreferredencoding()`, which is
  `cp1252` on Windows and breaks silently on non-ASCII content. Binary-mode
  calls (`"rb"`, `"wb"`, `"ab"`) and `tarfile.open(...)` do not take an
  encoding kwarg. Enforced by ruff's `PLW1514` rule.

### Type Hints

Use modern type hint syntax:
```python
# Good
def process_items(items: list[str]) -> dict[str, int]:
    pass

# Bad
from typing import List, Dict
def process_items(items: List[str]) -> Dict[str, int]:
    pass
```

### Docstrings

Use Google-style docstrings. These are automatically extracted into the
[API Reference](../docs/reference/api.md) documentation using mkdocstrings.

```python
def example_function(param1: str, param2: int = 10) -> bool:
    """Short description of the function.

    Longer description if needed, explaining the purpose,
    behavior, and any important details.

    Args:
        param1: Description of param1.
        param2: Description of param2. Defaults to 10.

    Returns:
        Description of return value.

    Raises:
        ValueError: When param2 is negative.

    Examples:
        >>> example_function("test", 5)
        True
        >>> example_function("", 10)
        False
    """
```

**Key points:**

- Type hints go in signatures, not duplicated in docstrings
- End descriptions with periods for consistency
- Include `Examples` section for complex functions (used by doctests)
- Document all public functions, classes, and methods
- Module-level docstrings describe the module's purpose

### Code Organization

Organize imports in three groups:
```python
# Standard library
import os
from pathlib import Path

# Third-party
import click
import pytest

# Local
from gnome_connection_manager import module
```

## Testing Guidelines

### Writing Tests

- Write tests for all new functionality
- Maintain or improve test coverage (target: ≥80%)
- Use descriptive test names: `test_function_does_something_when_condition`
- Use fixtures for common setup
- Test edge cases and error conditions

### Running Tests

```bash
# Run all tests
doit test

# Run with coverage
doit coverage

# Run specific test file
uv run pytest tests/test_example.py

# Run specific test
uv run pytest tests/test_example.py::test_specific_function -v
```

### Test Structure

```python
import pytest

def test_feature_works_correctly():
    """Test that feature produces expected output."""
    # Arrange
    input_data = "test input"

    # Act
    result = function_to_test(input_data)

    # Assert
    assert result == expected_output


@pytest.mark.parametrize("input_value,expected", [
    ("value1", "expected1"),
    ("value2", "expected2"),
])
def test_feature_with_multiple_inputs(input_value, expected):
    """Test feature with various inputs."""
    assert function_to_test(input_value) == expected
```

## Commit Guidelines

Follow [Conventional Commits](https://www.conventionalcommits.org/):

### Commit Format

```
<type>: <subject>

[optional body]

[optional footer]
```

### Commit Types

- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Formatting, whitespace (no code change)
- `test`: Adding or updating tests
- `refactor`: Code refactoring
- `perf`: Performance improvements
- `chore`: Maintenance tasks (deps, tooling)
- `ci`: CI/CD changes
- `revert`: Reverting previous commits

### Examples

```bash
feat: add support for async operations

fix: handle None values in data processor

docs: update installation instructions

test: add tests for edge cases in parser
```

### Passing the Message

Short one-liners are fine inline:

```bash
git commit -m "fix: handle None values in data processor"
```

**Anything longer goes in a file.** Write the message, then pass it with `-F`:

```bash
# AI agents: use tmp/agents/<agent-type>/ and delete the file afterwards
git commit -F tmp/agents/claude/commit-752.md
```

This matches how every other long-form body in this project is passed —
`doit issue --body-file=`, `doit pr --body-file=`, `doit adr --body-file=`.

It is also the only reliable way to write a message *about* the enforcement system. A heredoc
(`git commit -F - <<EOF`) is scanned by the dangerous-command hook as command arguments, so a
message that merely names `--admin`, `gh issue create` or any other blocked pattern is refused as
if it invoked it. The hook is not taught to tell prose from commands — doing that means skipping
heredoc bodies for a list of trusted commands, and a mistake in such a list is a bypass rather than
an inconvenience (see [ADR-9019](../docs/decisions/9019-the-dangerous-command-hook-is-a-guardrail-not-a-security-boundary.md)).
Passing the message by file costs nothing and avoids the question entirely.

### Breaking Changes

For breaking changes, include `BREAKING CHANGE:` in the footer:

```
refactor: change API to use async/await

BREAKING CHANGE: All public methods are now async.
Update calling code to use `await`.
```

### Exceptions

**Dependabot commits** are exempt from the full merge commit format. Dependabot automatically generates commits with:

```
chore(deps): bump <package> from X to Y (#PR)
```

This is acceptable because:
- Dependabot creates commit messages before the PR exists (cannot reference PR number)
- Automated dependency updates don't have linked issues
- The `chore(deps):` format follows conventional commits with a scope

## Pull Request Process

### Before Submitting

1. **Run all checks locally:**
   ```bash
   doit check
   ```

2. **Use conventional commit messages** - Your commit messages (`feat:`, `fix:`, etc.) automatically become changelog entries during release. See [Commit Guidelines](#commit-guidelines).

3. **Update documentation** (if needed)

4. **Update related ADRs** (if implementing an architectural decision) - Add your issue link to the Related section

5. **Self-review your code**

### PR Title

Use the same format as commits: `<type>: <subject>`

Examples:
- `feat: add support for custom validators`
- `fix: handle edge case in data parsing`
- `docs: improve API documentation`

### PR Description

Fill out the PR template (`.github/pull_request_template.md`):
- Provide a clear summary
- List specific changes
- Reference related issues
- Describe testing performed
- Note any breaking changes

### PR Review Process

1. **Automated checks** - CI must pass (tests, lint, type-check)
2. **Code review** - At least one maintainer approval required
3. **Address feedback** - Respond to review comments
4. **Add `ready-to-merge` label** - When PR is approved and CI passes (see below)
5. **Merge** - Maintainer will merge when approved

### Merge Gate and `ready-to-merge` Label

This repository uses a **merge gate** workflow to prevent premature merges:

**Why this exists:**
- Ensures full CI matrix (all OS/Python versions) completes before merge
- Prevents merging while tests are still running
- Provides explicit "ready" signal after review

**How it works:**
1. Open a PR - initial CI checks run
2. Get code review and address feedback
3. Wait for **all** CI checks to pass (including full OS matrix)
4. Add the `ready-to-merge` label to signal the PR is ready
5. The merge gate check passes, allowing merge

**Important:**
- The `ready-to-merge` label should only be added after:
  - All CI checks have passed (including full OS matrix)
  - Code review is complete and approved
  - All feedback has been addressed
- Adding the label prematurely doesn't bypass CI - the merge gate waits for CI completion
- The label works alongside GitHub's approval requirement - both must be satisfied

**With approval workflows enabled:**

If your repository requires PR approvals (branch protection → "Require approvals"), the merge flow becomes:

1. CI checks pass
2. Reviewer approves the PR
3. Add `ready-to-merge` label (final "ship it" signal)
4. Merge allowed

The label and approval are independent checks - both must pass. The label serves as an explicit final confirmation after review and CI are complete.

### After Merge

- Delete your branch
- Update your fork with the latest changes
- Close any related issues with comment "Addressed in PR #XXX"

## Release Process

The template this project is built on releases to PyPI from git tags. **GCM does not.**
A wheel cannot supply GTK 3, VTE or PyGObject — those come from the distribution — so a
PyPI install would not produce a working application.

What that means in practice:

- **The version is static**, in `pyproject.toml`. There is no `hatch-vcs`, no
  `dynamic = ["version"]`, and no release tag driving it. Four files carry the version and
  `tests/test_package.py::test_every_declared_version_agrees` fails if they disagree.
- **`release.yml` and `testpypi.yml` are deliberately absent.** So are `doit release` and
  `doit release_tag`; they are present in the vendored task modules but not wired to
  anything here.
- **Packaging is a `.deb`**, built by the `Makefile` with `fpm`. See the installation
  section of the README.

If PyPI publishing is ever wanted, the pieces are all still in the template — see
[#115](https://github.com/endavis/gnome-connection-manager/issues/115) for what was
skipped and why.

## Reporting Bugs

Use the bug report template (`.github/ISSUE_TEMPLATE/bug_report.yml`):

1. Go to **Issues** → **New Issue** → **Bug Report**
2. Fill out all sections:
   - Clear description of the bug
   - Steps to reproduce
   - Expected vs actual behavior
   - Environment details (OS, Python version, package version)
   - Error messages or logs
3. Add relevant labels
4. Be responsive to follow-up questions

## Requesting Features

Use the feature request template (`.github/ISSUE_TEMPLATE/feature_request.yml`):

1. Go to **Issues** → **New Issue** → **Feature Request**
2. Fill out all sections:
   - Problem statement
   - Proposed solution
   - Alternative solutions considered
   - Use cases
   - Benefits
3. Be open to discussion and feedback
4. Be willing to implement it yourself (or help)

## Development Workflow

**MANDATORY RULE:** All changes must originate from a GitHub Issue.

### Issue-Driven Development

Every code change must be linked to a GitHub Issue. This ensures:
- **Traceability:** Every change is linked to a documented need
- **Context:** Issues capture the "why" behind changes
- **Planning:** Better project management and prioritization
- **History:** Searchable record of decisions and rationale
- **Collaboration:** Clear communication about work in progress

### Workflow Steps

#### 1. **Issue:** Ensure GitHub Issue Exists

**Create issue using doit (recommended):**
```bash
# Interactive: Opens $EDITOR with template
doit issue --type=feature    # For new features
doit issue --type=bug        # For bugs and defects
doit issue --type=refactor   # For code refactoring
doit issue --type=docs       # For documentation
doit issue --type=chore      # For maintenance tasks

# Non-interactive: For AI agents or scripts
doit issue --type=feature --title="Add export" --body-file=issue.md
doit issue --type=docs --title="Add guide" --body="## Description\n..."
```

**Or use gh CLI directly:**
```bash
gh issue create --title "<description>" --label "enhancement" --body "..."
```

**Issue types auto-apply labels:**
- `feature` → `enhancement, needs-triage`
- `bug` → `bug, needs-triage`
- `refactor` → `refactor, needs-triage`
- `docs` → `documentation, needs-triage`
- `chore` → `chore, needs-triage`

**Required fields ensure complete information** - Fill all fields to provide context.

#### 2. **Branch:** Create Branch Linked to Issue

**Branch Format:** `<type>/<number>-<description>`

**Allowed Types:**
- `issue`, `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `ci`, `perf`, `hotfix`
- Special: `release/<version>` (no issue number required)

**Examples:**
```bash
feat/42-user-authentication
fix/123-handle-null-values
docs/41-update-guidelines
refactor/55-simplify-parser
```

**Create and link branch:**
```bash
# Option 1: GitHub CLI (auto-links)
gh issue develop <issue-number> --checkout

# Option 2: Manual (include issue number in name)
git checkout -b feat/42-add-feature
```

**Branch naming is enforced by pre-commit hooks.**

#### 3. **Commit:** Use Conventional Commits

**Format:** `<type>: <subject>`

Use `doit commit` for interactive commit creation with commitizen.

**Enforced by:**
- Pre-commit hooks (locally)
- CI checks (on PR)

#### 4. **Pull Request:** Submit PR from Branch to `main`

**Create PR using doit (recommended):**
```bash
# Interactive: Opens $EDITOR with template
doit pr

# Non-interactive: For AI agents or scripts
doit pr --title="feat: add export" --body-file=pr.md
doit pr --title="feat: add export" --body="## Description\n..."

# Create as draft
doit pr --draft
```

Features:
- Auto-detects issue number from branch name (e.g., `feat/42-description` → `Addresses #42`)
- Pre-fills the PR template with detected issue
- Validates required fields before creating

**PR Title:**
- Must follow conventional commit format: `<type>: <subject>`
- PR title becomes the merge commit message
- Examples: ✅ `feat: add validators`, ❌ `Add validators`

**PR Description Requirements (enforced by CI):**
- Minimum 50 characters
- Reference related issue: "Addresses #42"
- Describe what changed and why
- Include testing information

#### 5. **Merge:** Format Must Include PR and Issue Numbers

**Merge commit format:**
```
<type>: <subject> (merges PR #XX, addresses #YY)
```

**Examples - Correct:**
```
feat: add user authentication (merges PR #18, addresses #42)
fix: handle None values (merges PR #23, addresses #19)
docs: update installation guide (merges PR #29, addresses #25)
```

**Examples - Incorrect:**
```
❌ Merge pull request #18 from user/branch
❌ feat: Add Feature (capitalized subject)
❌ added feature (missing type)
❌ feat: add feature (missing PR reference)
```

**Using `doit pr_merge`:**

The `doit pr_merge` task enforces this format automatically:

```bash
# Merge PR for current branch
doit pr_merge

# Merge specific PR
doit pr_merge --pr=123

# Keep branch after merge (default deletes it)
doit pr_merge --delete-branch=false
```

The task:
- Fetches PR title, number, and linked issues from GitHub
- Validates PR title follows conventional commit format
- Constructs the merge commit subject automatically
- Uses squash merge with the formatted subject

### Architecture Decision Records (ADRs)

When your PR implements or relates to an architectural decision, update the relevant ADR:

**When to update an ADR:**
- Your PR implements a decision documented in an existing ADR
- Your PR changes behavior described in an ADR
- Your issue is related to an architectural decision

**How to update:**
1. Find related ADRs in `docs/decisions/`
2. Add your issue to the "Related Issues" section: `- Issue #XX: Brief description`
3. Add links to implementation docs in "Related Documentation" section
4. Include the ADR update in your PR

**When to create a new ADR:**
- Introducing a new tool, framework, or library
- Changing development workflow or processes
- Making decisions that affect project architecture
- Decisions that future contributors should understand

**Which issue types may need ADRs:**
- **Feature**: Often - new features may introduce architectural decisions
- **Refactor**: Often - refactoring may change architecture or patterns
- **Bug**: Rarely - only if the fix reveals a significant design decision
- **Doc/Chore**: No - documentation and maintenance don't need ADRs

**The `needs-adr` label:**
Use the `needs-adr` label on issues that require an ADR. This signals that:
- The issue involves an architectural decision
- An ADR should be created as part of the PR
- The PR should not be merged without the ADR

**Create a new ADR:**
```bash
# Interactive (opens editor)
doit adr --title="Use Redis for caching"

# Non-interactive (for scripts/AI)
doit adr --title="Use Redis" --body-file=adr.md
doit adr --title="Use Redis" --body="## Status\nAccepted\n..."
```

**ADR requirements:**
- Every ADR must link to the GitHub Issues where the decision was discussed
- Every ADR must link to documentation in `docs/` that describes the implementation
- If no documentation exists, create it as part of the PR

ADRs provide context for why decisions were made, helping future contributors understand the project's evolution.

### Edge Cases

**Issue needs to be split during work:**
- Create new issues for discovered separate concerns
- Update original issue to reference the new issues
- Continue work on current branch or create new branches

**Issue is obsolete or duplicate:**
- Comment explaining why it's obsolete/duplicate
- Link to the duplicate issue if applicable
- Close with appropriate label (duplicate, wontfix)
- Delete branch if no work committed

**Work spans multiple sessions:**
- Update issue with progress comments
- Document decisions and approaches tried
- Push commits regularly
- Keep PR description updated

### Keeping Your Fork Updated

```bash
# Add upstream remote (one-time setup)
git remote add upstream https://github.com/endavis/gnome-connection-manager.git

# Fetch and merge upstream changes
git checkout main
git fetch upstream
git merge upstream/main
git push origin main
```

## Questions?

If you have questions:

1. Check the [README.md](../README.md) and [AGENTS.md](../AGENTS.md)
2. Search existing [Issues](https://github.com/endavis/gnome-connection-manager/issues)
3. Open a new issue with the "question" label
4. Join our discussions (if available)

## Thank You!

Your contributions make this project better for everyone. We appreciate your time and effort!

---

For more detailed information, see:
- [README.md](../README.md) - Project overview
- [AGENTS.md](../AGENTS.md) - Development guide for AI agents
- [Architecture Decision Records](../docs/decisions/README.md) - Documented architectural decisions
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) - Community guidelines
- [SECURITY.md](SECURITY.md) - Security policy
