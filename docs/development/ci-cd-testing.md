---
title: CI/CD Testing Guide
description: GitHub Actions pipelines for testing, linting, and coverage
audience:
  - contributors
tags:
  - ci-cd
  - testing
  - github-actions
---

# CI/CD Testing Guide

## Overview

CI runs lint/format, tests, coverage, and quality checks to guard against regressions. GitHub Actions pipelines target multiple Python versions and publish coverage artifacts/comments.

## Audience and Prerequisites

- **Audience:** Contributors and reviewers ensuring CI health
- **Prerequisites:** GitHub Actions access; local tools (`uv`, `doit`, pytest, ruff, mypy) to replicate checks

## When to Use This

- Before opening/merging PRs to mirror CI locally
- Understanding pipeline stages and coverage expectations
- Expanding tests or adjusting quality thresholds

## Quick Start

Local commands:
```bash
doit format && doit lint
doit test
doit coverage
```

## Python Version Support Policy

### Active Support

Only the **last 3 major Python versions** are actively supported. This means:
- Bug fixes and new features are tested against these versions
- CI runs these versions on every PR (using bookend strategy - oldest + newest)
- Documentation and examples target these versions

**Current active versions:** Python 3.12, 3.13, 3.14

### Passive Compatibility

Older Python versions may continue to work but are not actively maintained:
- We continue testing previous versions in CI via the `full-matrix` label
- Once a version fails CI tests, it is removed from the matrix and marked incompatible
- Users on older Python versions can use version-tagged releases (e.g., `v1.2.3-py310-final`)

### Version Lifecycle

| Stage | Description | CI Testing |
|-------|-------------|------------|
| **Active** | Last 3 major versions | Every PR (bookend strategy) |
| **Passive** | Older versions still passing | On-demand (`full-matrix` label) |
| **Deprecated** | Fails CI tests | Removed from matrix |

### CI Matrix Strategy

To balance test coverage with CI efficiency:

| PR State | Python Versions Tested | Jobs |
|----------|----------------------|------|
| Default | Bookends only (oldest + newest) × 3 OSes | 6 |
| `full-matrix` label | Middle versions only × 3 OSes | 3 per middle version |

The **bookend strategy** tests the oldest and newest supported versions. If both pass, intermediate versions are assumed compatible. Use the `full-matrix` label when:
- Making changes that might affect version compatibility
- Preparing a release
- Investigating compatibility issues

### Configuration

Python versions are configured in `.github/python-versions.json`:

```json
{
  "oldest": "3.12",
  "newest": "3.14"
}
```

The CI workflow automatically derives:
- **Bookends**: oldest + newest (tested on every PR)
- **Middle versions**: everything between (tested when `full-matrix` label is added)

When updating supported versions, edit this config file - no workflow changes needed.

### Deprecation Process

When a Python version starts failing CI:

1. **Assess**: Determine if the failure is fixable without significant effort
2. **Decide**: Fix compatibility or deprecate the version
3. **Tag**: If deprecating, tag the last compatible release (e.g., `v1.2.3-py310-final`)
4. **Update**: Remove version from CI matrix and update `pyproject.toml` classifiers
5. **Document**: Update this documentation and release notes

## Pipeline Details (GitHub Actions)

### The pipeline that ships

`ci.yml` is the pipeline. It is not a starting point to copy — it is the workflow this template
installs, and it already does what a hand-rolled `tests.yml` would:

| | |
| :--- | :--- |
| **Matrix** | derived from `.github/python-versions.json` via `.github/actions/python-versions`, not hardcoded — so a version policy change moves one file |
| **Platforms** | `ubuntu-latest`, `windows-latest`, `macos-latest` |
| **Checks** | `doit` tasks (`format_check`, `lint`, `type_check`, `test`), so CI and a local run cannot diverge |
| **Coverage** | `package_name` **and** `tools/`, gated by `fail_under` in `pyproject.toml` |
| **Actions** | pinned to commit SHAs with a `# vX.Y.Z` comment (see [Action pinning](#action-pinning-and-workflow-permissions)) |

Read `.github/workflows/ci.yml` for the current definition. This page previously carried a ~60-line
`tests.yml` sample to copy; it drifted from the real file in every dimension above — hardcoded
versions, raw `pytest` instead of `doit`, and mutable action tags this project's own tests forbid
(#772). A second pipeline alongside `ci.yml` was never the intent.

### Pipeline Jobs

#### Code Quality Job

```yaml
code-quality:
  runs-on: ubuntu-latest
  steps:
    # checkout + uv setup, SHA-pinned — see .github/workflows/ci.yml
    - name: Install dependencies
      run: uv sync --dev
    - name: Format check
      run: uv run doit format_check
    - name: Lint check
      run: uv run doit lint
    - name: Type check
      run: uv run doit type_check
      continue-on-error: true
```

#### Security Scan Job

```yaml
security:
  runs-on: ubuntu-latest
  steps:
    # checkout + uv setup, SHA-pinned — see .github/workflows/ci.yml
    - name: Install security tools
      run: uv sync --extra security
    - name: Run security audit
      run: uv run doit audit
    - name: Run bandit scan
      run: uv run doit security
```

#### Documentation Build Job

Runs `doit docs_build` once on `ubuntu-latest` using the project's newest supported Python version (read dynamically from `.github/python-versions.json`). This job gates PRs against hard-crash regressions in the mkdocs build pipeline — for example, plugin incompatibilities, broken macros, or malformed configuration. See issue [#349](https://github.com/endavis/pyproject-template/issues/349) for the historical incident that motivated this gate.

Note: This job does **not** currently run `mkdocs build --strict`, so doc-link warnings and other non-fatal mkdocs warnings do not fail the build. Tightening this to strict mode is a potential future improvement once the existing warning backlog is cleared.

```yaml
docs:
  needs: setup
  runs-on: ubuntu-latest
  steps:
    # checkout, setup-python (at needs.setup.outputs.newest) and uv setup —
    # all SHA-pinned; see .github/workflows/ci.yml for the current pins
    - name: Install dependencies
      run: uv sync --all-extras --dev
    - name: Build documentation
      run: uv run doit docs_build
```

### Tests of shipped assets must fit the project, not the template

The template wires four AI agents; most projects spawned from it keep one. Tests
that assert on agent wiring therefore derive the roster from what is on disk
rather than hardcoding all four:

```python
from agent_roster import present_agents, agent_is_present, skip_if_absent

AGENTS = present_agents()          # size a matrix to this project
skip_if_absent("codex")            # or skip a whole agent-specific test
```

`tests/agent_roster.py` keys presence on each agent's self-action skill directory,
not its config root — `.agents/` is read by both Codex and Antigravity, so its
existence cannot distinguish them.

Before this, `test_delegation_matrix.py` and four other files asserted that all
68 delegation files existed, so a project that dropped an unused agent got 56
failures on its first run (#690). Dropping an agent should narrow what the suite
checks, never red it.

The same principle does **not** license shedding these tests. They cover
`tools/doit/`, `tools/hooks/`, workflows and agent assets — code that ships to and
runs in the project, and that the gate below measures. Shedding them was measured
at 40.73% total and 8.27% on `tools/hooks/`, well under `fail_under` (#731).

### Action pinning and workflow permissions

**Every external action is pinned to a commit SHA**, with a `# vX.Y.Z` comment so the
file stays readable:

```yaml
- uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
```

A major tag such as `@v7` is a moving pointer the publisher can re-aim at any commit, so
`uses: some/action@v7` is a standing instruction to run whatever they decide to put
there. A 40-character SHA is not re-pointable. Dependabot is configured for the
`github-actions` ecosystem, so pins are bumped through a reviewable PR rather than
changing silently — that trade is the point, and it is why pinning does not mean falling
behind.

First-party `actions/*` are pinned too. "GitHub publishes it" is not a security boundary,
and exempting them would leave most of the surface unpinned for no gain.

**One deliberate exemption:** `pypa/gh-action-pypi-publish@release/v1`. PyPA documents
that branch as the supported reference for trusted publishing and ships security fixes to
it, and the workflows using it hold `id-token: write`. The exemption and its reason live
in `PINNING_EXEMPT` in `tests/test_workflow_action_pinning.py`, which fails if it is ever
added to without a reason or left in place after the action stops being used.

**Permissions are least-privilege, and write is never reachable from a pull request.** A
same-repo PR branch runs its own code; if a write-capable `GITHUB_TOKEN` is in scope,
that code can use it — and workflow-scope `permissions:` apply to every trigger,
including `pull_request`. So a job needing write declares it at *job* scope and gates
itself on `github.event_name == 'push'`. `benchmark.yml` is the worked example: a
read-only `benchmark` job that runs everywhere, and a `store` job holding the only write
grant, gated on pushes to main.

`tests/test_benchmark_workflow.py` and `tests/test_workflow_action_pinning.py` enforce
both properties.

### Coverage Requirements

- **Enforced threshold**: `fail_under = 70` in `pyproject.toml`
- **Measured scope**: `package_name` **and** `tools/`
- **Artifacts**: Upload HTML coverage reports for review
- **Integration**: Use Codecov or similar service for tracking

#### What the gate measures, and why

The gate covers `tools/` as well as the package. `src/package_name/` is the skeleton every
downstream project deletes and replaces; `tools/` is the code that runs releases, creates PRs and
blocks dangerous commands. Gating only the package produced a healthy-looking number over ~66
statements while several thousand statements of tooling went unmeasured.

The threshold is deliberately set to what the codebase actually achieves rather than to an
aspirational number pointed at the wrong target. **Ratchet it upward** as tooling coverage
improves; treat lowering it as a change that needs justification in the PR.

One directory is omitted: `tools/pyproject_template/`. It is the template's own management
suite, deleted by both spawn routes, so leaving it in scope measured code downstream that is
never tested there — which put a spawned project 19 points under the gate (#731). Its tests
still run in template CI. Nothing else is omitted.

#### Template vs downstream

`cleanup --setup` / `--all` deletes `tools/pyproject_template/`, so the two shapes once measured
different code and reported different numbers.

**They no longer do.** #731 omitted that directory from the gate precisely so both shapes measure
the same statements with the same tests: a spawned project now sees the number this repository
sees, rather than one 19 points lower that it had no way to raise. There is one figure to track,
not two.

Run `doit coverage` for the current value. The gate is `fail_under` in `pyproject.toml` — 70 at the
time of writing — and CI fails below it.

Statement counts and percentages are deliberately **not** quoted here. They move with every merge:
the figures this section used to carry were stale within days, and a number in prose that no test
reads is a number that will be wrong (#754). `pyproject.toml` holds the threshold, `doit coverage`
reports the measurement, and both are checked.

#### Keep coverage hermetic

These figures are reproducible on any machine. They were not always: tests reached
`setup_repo._check_token_permissions()` through the *real* `gh auth status`, so the branch that
runs depended on the developer's GitHub auth state — a machine holding a fine-grained PAT
measured 34 more covered statements than CI did, a 0.54pp swing.

When a test reaches an interactive or shell-dependent function only incidentally, the gate stops
being reproducible and a tight threshold becomes unreliable. Mock the subprocess or the input and
cover the branches deliberately.

Shedding `tools/pyproject_template/` *raises* the measured percentage, so a consumer inherits a
gate that already passes — one threshold holds in both shapes and `cleanup` needs no
coverage-specific rewrite. A downstream project that wants a stricter gate over its own code can
narrow `source` back to its package and raise `fail_under`.

**Example pytest configuration in `pyproject.toml`:**
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = [
    "--cov=src",
    "--cov-report=term-missing",
    "--cov-report=html",
    "--cov-report=xml",
    "--cov-fail-under=70",
]
```

### PR Comments

This template does **not** post coverage comments on PRs, and no workflow here uses a
coverage-comment action. Coverage is reported by `doit coverage` locally and by the CI job's
output; the gate is `fail_under` in `pyproject.toml`.

If you add one to your own project, pin it to a commit SHA like every other external action — see
[Action pinning](#action-pinning-and-workflow-permissions). A previous version of this page
suggested `py-cov-action/python-coverage-comment-action@v3`, which was both unused here and
unpinned (#772).

Related: PRs no longer receive an automated benchmark regression comment either — that required
`contents: write` on the pull-request path and was removed with it. The benchmark still runs and
uploads its JSON.

## Local Development Workflow

### Running Tests Locally

```bash
# Run all tests
doit test

# Run specific test file
uv run pytest tests/test_config.py

# Run specific test
uv run pytest tests/test_config.py::test_load_config

# Run with verbose output
uv run pytest -v

# Run with coverage
doit coverage

# Generate HTML coverage report
uv run pytest --cov=src --cov-report=html
xdg-open htmlcov/index.html  # Open in browser
```

### Quality Checks

```bash
# Format code
doit format

# Check formatting (CI mode)
doit format_check

# Lint code
doit lint

# Type check
doit type_check

# Run all quality checks
doit check
```

### Coverage Analysis

```bash
# Run with coverage
doit coverage

# View coverage report
xdg-open tmp/htmlcov/index.html

# Check coverage threshold
pytest --cov=src --cov-fail-under=70
```

## Validation and Checks

### Pre-commit Integration

The template includes pre-commit hooks that run automatically:

```bash
# Install hooks
doit pre_commit_install

# Run manually on all files
doit pre_commit_run

# Update hook versions
uv run pre-commit autoupdate
```

**Hook stages in `.pre-commit-config.yaml`:**

**Pre-commit stage** (runs on every `git commit`):

| Hook | Purpose |
|------|---------|
| `trailing-whitespace` | Remove trailing whitespace |
| `end-of-file-fixer` | Ensure files end with a newline |
| `check-yaml` | Validate YAML syntax |
| `check-added-large-files` | Prevent large files from being committed |
| `check-toml` | Validate TOML syntax |
| `check-merge-conflict` | Detect merge conflict markers |
| `detect-private-key` | Prevent private keys from being committed |
| `ruff` | Lint and auto-fix Python code |
| `ruff-format` | Format Python code |
| `mypy` | Type checking (strict mode, `src/` only) |
| `bandit` | Security scanning (skipped if not installed) |
| `codespell` | Spell checking |
| `actionlint` | Lint GitHub Actions workflow files |
| `check-branch-name` | Enforce branch naming convention |
| `generate-doc-toc` | Update documentation TOC when docs change |
| `no-commit-to-main` | Prevent direct commits to main branch |
| `no-local-config` | Prevent committing local config files |
| `protect-dynamic-version` | Protect `dynamic = ["version"]` in `pyproject.toml` |
| `uv-lock-check` | Validate `uv.lock` is in sync with `pyproject.toml` when `pyproject.toml` is staged |

**Commit-msg stage** (validates commit messages):

| Hook | Purpose |
|------|---------|
| `conventional-pre-commit` | Enforce conventional commit format |

**Post-merge / Post-checkout stage** (automatic dependency sync):

| Hook | Purpose |
|------|---------|
| `uv-sync-on-pull` | Runs `uv sync --all-extras --dev` when `uv.lock` changes after `git pull` |
| `uv-sync-on-checkout` | Runs `uv sync --all-extras --dev` when `uv.lock` changes after branch switch |

### Continuous Integration Checklist

Before pushing to CI:
- [ ] Run `doit format` to format code
- [ ] Run `doit lint` to check for issues
- [ ] Run `doit type_check` to verify types
- [ ] Run `doit test` to ensure tests pass
- [ ] Run `doit coverage` to check coverage threshold
- [ ] Run `doit docs_build` to verify the documentation build succeeds
- [ ] Review changes and commit messages

## Testing Best Practices

### Test Organization

```
tests/
├── unit/           # Unit tests (fast, isolated)
│   ├── test_config.py
│   ├── test_utils.py
│   └── test_models.py
├── integration/    # Integration tests (slower, with dependencies)
│   ├── test_api.py
│   └── test_database.py
├── fixtures/       # Test data and fixtures
│   └── sample_config.json
└── conftest.py     # Shared pytest fixtures
```

### Writing Good Tests

```python
import pytest
from myproject import Config, ConfigError

@pytest.fixture
def temp_config_file(tmp_path):
    """Create a temporary config file."""
    config_file = tmp_path / "config.json"
    config_file.write_text('{"key": "value"}', encoding="utf-8")
    return config_file

def test_config_load_success(temp_config_file):
    """Test successful config loading."""
    config = Config.load(str(temp_config_file))
    assert config.get("key") == "value"

def test_config_load_file_not_found():
    """Test config loading with missing file."""
    with pytest.raises(ConfigError, match="not found"):
        Config.load("nonexistent.json")

@pytest.mark.parametrize("value,expected", [
    ("true", True),
    ("false", False),
    ("1", True),
    ("0", False),
])
def test_parse_bool(value, expected):
    """Test boolean parsing with various inputs."""
    assert parse_bool(value) == expected
```

### Mocking External Dependencies

```python
from unittest.mock import Mock, patch
import pytest

def test_api_call_success():
    """Test successful API call."""
    with patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = {"status": "ok"}
        mock_get.return_value.status_code = 200

        result = fetch_data("https://api.example.com/data")
        assert result["status"] == "ok"
        mock_get.assert_called_once_with("https://api.example.com/data")

def test_api_call_failure():
    """Test API call failure handling."""
    with patch("requests.get") as mock_get:
        mock_get.side_effect = ConnectionError("Network error")

        with pytest.raises(APIError, match="Network error"):
            fetch_data("https://api.example.com/data")
```

## Examples

### Running Specific Tests

```bash
# Run all tests in a file
pytest tests/unit/test_config.py

# Run a specific test class
pytest tests/unit/test_config.py::TestConfigManager

# Run a specific test method
pytest tests/unit/test_config.py::TestConfigManager::test_load_config

# Run tests matching a pattern
pytest -k "test_config"

# Run tests with markers
pytest -m "slow"  # Run only tests marked as slow
pytest -m "not slow"  # Skip slow tests
```

### Coverage Analysis

```bash
# Generate coverage report
doit coverage

# View HTML coverage report
xdg-open tmp/htmlcov/index.html

# Check specific module coverage
pytest --cov=src/myproject/config --cov-report=term-missing

# Generate XML coverage for CI
pytest --cov=src --cov-report=xml
```

### Testing Multiple Python Versions

Using `tox`:

```ini
# tox.ini
[tox]
envlist = py312,py313,py314

[testenv]
deps =
    pytest
    pytest-cov
commands = pytest {posargs}
```

```bash
# Run tests on all environments
tox

# Run on specific environment
tox -e py314
```

## Merge Gate Workflow

The repository uses a merge gate to ensure PRs are only merged after explicit approval.

### How It Works

The merge gate is implemented in `.github/workflows/merge-gate.yml`:

```yaml
name: Merge Gate

on:
  pull_request:
    branches: [main]
    types: [opened, labeled, unlabeled, synchronize, reopened]

jobs:
  require-label:
    runs-on: ubuntu-latest
    steps:
      - name: Check for ready-to-merge label
        run: |
          if [[ "${{ contains(github.event.pull_request.labels.*.name, 'ready-to-merge') }}" != "true" ]]; then
            echo "::error::PR requires 'ready-to-merge' label before merging"
            exit 1
          fi
```

### The `ready-to-merge` Label

This label is a **pure merge gate** - it signals that a PR is approved for merge but does not trigger additional CI runs. The default CI matrix (6 jobs) provides sufficient coverage.

**When to add the label:**
- All CI checks have passed
- Code review is complete and approved
- All review feedback has been addressed

**Adding the label:**
```bash
# Via GitHub CLI
gh pr edit <PR-NUMBER> --add-label "ready-to-merge"

# Or via GitHub web UI: PR page → Labels → ready-to-merge
```

### The `full-matrix` Label

Use this label to trigger comprehensive compatibility testing across all supported Python versions:

**When to use:**
- Changes that might affect Python version compatibility
- Preparing a release
- Investigating compatibility issues reported by users

```bash
# Add full-matrix label for comprehensive testing
gh pr edit <PR-NUMBER> --add-label "full-matrix"
```

Adding the label triggers the dedicated `.github/workflows/ci-full-matrix.yml`
workflow. That workflow is a thin dispatcher: it fires only on the `labeled`
event, confirms the label name is `full-matrix`, and then calls `ci.yml` via
`workflow_call` with `full_matrix: true`. The main `ci.yml` no longer fires on
label events itself, which keeps the per-push `CI` check from being duplicated
every time a label is added to a PR.

### Branch Protection Integration

Configure branch protection rules to require the merge gate:

1. Go to **Settings** → **Branches** → **Branch protection rules**
2. Select or create rule for `main`
3. Enable **Require status checks to pass before merging**
4. Add `require-label` to required status checks

This ensures PRs cannot be merged until:
- The `ready-to-merge` label is present
- All CI checks pass (default 6-job matrix)

### Interaction with Approval Workflows

The merge gate works alongside GitHub's approval requirement:

| Check | Type | Purpose |
|-------|------|---------|
| Approvals | GitHub built-in | Ensures code review is complete |
| CI checks | GitHub Actions | Tests code on bookend Python versions × all OSes |
| Merge gate | Custom workflow | Explicit "ready" signal via label |

**Recommended merge flow:**

```
PR opened → CI runs (6 jobs) → Review/Approval → Add ready-to-merge label → Merge
```

**Optional full compatibility check:**

```
PR opened → CI runs → Add full-matrix label → Full CI runs (9-15 jobs) → Review → Add ready-to-merge → Merge
```

## Property-Based Testing

### What Is Property-Based Testing?

Property-based testing verifies *invariant properties* of your code by feeding it hundreds of randomly generated inputs rather than a handful of hand-picked examples. If a property holds for every input the framework can dream up, you gain much higher confidence than example-based tests alone.

This project uses [Hypothesis](https://hypothesis.readthedocs.io/) for property-based testing.

### When to Use Property-Based Tests

| Good fit | Not a good fit |
|----------|----------------|
| Pure functions with clear contracts (validators, formatters, parsers) | Tests that require complex external state (databases, APIs) |
| Functions whose output must satisfy invariants (e.g., "always lowercase") | Behaviour that depends on side effects or ordering |
| Edge-case-heavy logic (string processing, numeric conversions) | Simple CRUD with no transformation logic |

### Writing Property Tests

```python
import pytest
from hypothesis import given, example
from hypothesis import strategies as st

@pytest.mark.property
@given(name=st.text(min_size=1))
@example("edge-case-value")
def test_output_is_always_lowercase(name: str) -> None:
    result = normalize(name)
    assert result == result.lower()
```

**Key decorators and strategies:**

| Element | Purpose |
|---------|---------|
| `@given(...)` | Declares the randomly generated inputs |
| `@example(...)` | Pins a specific input that must always be tested |
| `st.text()` | Generates arbitrary Unicode strings |
| `st.from_regex(r"...")` | Generates strings matching a regular expression |
| `st.integers()`, `st.floats()` | Numeric strategies |
| `@pytest.mark.property` | Custom marker to select/deselect property tests |

### Hypothesis Profiles

Two profiles are configured in `tests/conftest.py`:

| Profile | `max_examples` | `deadline` | Used when |
|---------|---------------|------------|-----------|
| `default` | 200 | Hypothesis default | Local development |
| `ci` | 50 | 500 ms | GitHub Actions CI |

The CI workflow sets `HYPOTHESIS_PROFILE: ci` so property tests run faster in pipelines.

### Running Property Tests

```bash
# Run only property tests
uv run pytest -m property -v

# Run with a specific seed for reproducibility
uv run pytest -m property --hypothesis-seed=12345

# Run with more examples locally
HYPOTHESIS_PROFILE=default uv run pytest -m property -v
```

### Debugging Failures

When a property test fails, Hypothesis prints the **minimal failing example**. To reproduce:

1. Copy the seed from the failure output (e.g., `--hypothesis-seed=98765`)
2. Re-run: `uv run pytest tests/template/test_properties.py --hypothesis-seed=98765 -v`
3. Hypothesis will reproduce the exact same sequence of inputs

Hypothesis also stores failing examples in a `.hypothesis/` directory (git-ignored) so they are replayed automatically on the next run.

## Mutation Testing

### What Is Mutation Testing?

Mutation testing evaluates the effectiveness of your test suite by introducing small changes (mutations) to your source code and checking whether the tests detect them. Each mutation represents a potential bug -- if your tests catch it (a "killed" mutant), that area is well tested. If they don't (a "survived" mutant), your tests may have a gap.

This project uses [mutmut](https://mutmut.readthedocs.io/) for mutation testing.

### Running Locally

```bash
# Run mutation testing (generates results and prints summary)
doit mutate

# View text results again without re-running
uv run mutmut results
```

### Interpreting Results

| Term | Meaning |
|------|---------|
| **Killed** | A mutation was detected by the test suite -- good coverage |
| **Survived** | A mutation was NOT detected -- potential test gap |
| **Timeout** | The mutation caused the tests to hang -- typically counted as killed |
| **Suspicious** | The mutation caused an unexpected result -- review manually |

The **mutation score** is the percentage of mutants killed out of total mutants generated. A higher score indicates a more thorough test suite. There is no enforced threshold -- use the score as a guide to identify areas that need better test coverage.

### CI Schedule

Mutation testing runs weekly in CI (Sunday midnight UTC) via the `.github/workflows/mutation.yml` workflow. It is informational only and does not block merges or fail the build.

Results are uploaded as the `mutmut-results.txt` artifact with 90-day retention. You can also trigger the workflow manually from the Actions tab using the `workflow_dispatch` event.

## Benchmark Tracking

### Overview

Benchmark results are tracked historically using [benchmark-action/github-action-benchmark](https://github.com/benchmark-action/github-action-benchmark). This enables performance trend visualization and automatic regression detection across commits.

### How It Works

The `benchmark.yml` workflow operates in two modes:

| Trigger | Behavior |
|---------|----------|
| **Push to `main`** | Runs benchmarks and commits results to the `gh-benchmarks` data branch for long-term tracking |
| **Pull request** | Runs benchmarks and posts a comparison comment on the PR if the `gh-benchmarks` branch exists (no commit to data branch) |
| **Manual dispatch** | Runs benchmarks and uploads artifact only |

Only main branch results are stored to keep the historical data clean and consistent.

If `tests/benchmarks/` does not exist or contains no `test_*.py` files, the workflow skips all benchmark steps and finishes successfully. This allows downstream projects generated from this template to enable the workflow incrementally without CI failures before any benchmark tests are written.

### The `gh-benchmarks` Branch

Benchmark data is stored in a dedicated `gh-benchmarks` branch, separate from the main codebase. This branch is auto-created by the benchmark action on the first push to `main` after the workflow is enabled. Until the branch exists, PR benchmark comparisons are skipped gracefully.

- **Data directory:** `dev/bench/` within the branch
- **Format:** JSON files with benchmark metrics over time
- **Purpose:** Serves as the data source for trend charts and regression detection

### PR Comments

On every pull request, the benchmark action posts a comment comparing the PR's benchmark results against the latest stored baseline from `main`. This gives reviewers immediate visibility into performance impact.

### Alert Threshold

The alert threshold is set to `110%`, meaning the workflow flags a warning if any benchmark is more than 10% slower than the baseline. To adjust this threshold, edit the `alert-threshold` value in `.github/workflows/benchmark.yml`.

### GitHub Pages (Optional)

The `gh-benchmarks` branch can optionally serve a trend chart via GitHub Pages:

1. Go to **Settings** > **Pages**
2. Set the source branch to `gh-benchmarks`
3. Set the directory to `/ (root)`
4. The trend chart will be available at `https://<owner>.github.io/<repo>/dev/bench/`

This step is optional and not required for the core tracking functionality.

## Troubleshooting

### Coverage Below Threshold

**Symptom**: `pytest --cov-fail-under=70` fails
**Fix**:
- Add tests for new/changed code paths
- Use `pytest --cov=src --cov-report=html` to see uncovered lines
- Review coverage report: `xdg-open tmp/htmlcov/index.html`

### Ruff/Format Failures

**Symptom**: Formatting or linting errors in CI
**Fix**:
- Run `doit format` locally to auto-format
- Run `doit lint` to see all violations
- Address violations or add exceptions to `pyproject.toml`

### Mypy Type Errors

**Symptom**: Type checking fails
**Fix**:
- Add proper type annotations
- Use `# type: ignore[error-code]` sparingly with explanatory comments
- Review mypy output for specific issues
- Consider making mypy non-blocking initially (`continue-on-error: true`)

### Tests Fail in CI but Pass Locally

**Symptom**: Tests pass locally but fail in CI
**Fix**:
- Check for environment-specific dependencies
- Ensure all test dependencies are in `pyproject.toml`
- Look for timing issues or race conditions
- Check for file system or path differences

### Pre-commit Hooks Too Slow

**Symptom**: Pre-commit hooks take too long
**Fix**:
- Skip test hook for routine commits: `git commit --no-verify`
- Run tests manually before pushing
- Consider running only fast unit tests in pre-commit
- Move integration tests to CI only

## Related Documentation

- [Coding Standards](coding-standards.md)
- [Release Automation](release-and-automation.md)

---

[Back to Documentation Index](../TABLE_OF_CONTENTS.md)
