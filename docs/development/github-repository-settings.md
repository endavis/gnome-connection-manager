---
title: GitHub Repository Settings
description: Complete reference for all GitHub repository settings the template expects
audience:
  - users
  - contributors
tags:
  - github
  - settings
  - setup
  - configuration
---

# GitHub Repository Settings

Complete reference for the GitHub repository settings this template expects.
New repositories created from the template are configured automatically by
[`repo_settings.py`](../../tools/pyproject_template/repo_settings.py) via
`update_all_repo_settings()`. This page documents what each setting is, why
it is needed, and whether it is set automatically or requires manual action.

For the initial setup workflow, see the [New Project Setup](../template/new-project.md) guide.

## Repository Settings

These are the general repository-level settings applied by
`configure_repository_settings()`.

| Setting | Value | Purpose |
| :--- | :--- | :--- |
| **Default branch** | `main` | Standard branch for PRs and CI |
| **Issues** | Enabled | Issue tracking with custom templates |
| **Wiki** | Disabled | Documentation lives in `docs/` via MkDocs |
| **Projects** | Enabled | Available for project management if needed |
| **Discussions** | Disabled | Not used by default |
| **Allow squash merge** | Yes | Only merge strategy allowed (linear history) |
| **Allow merge commit** | No | Enforces squash-only policy |
| **Allow rebase merge** | No | Enforces squash-only policy |
| **Allow auto-merge** | Yes | Required by the [Dependabot Auto-merge](dependabot-automerge.md) workflow so it can call `gh pr merge --auto` |
| **Delete branch on merge** | Yes | Cleans up feature branches automatically |
| **Visibility** | Public | Template default; private repos may lack some security features |

**Automated:** Yes, all settings above are copied from the template repository.

## Branch Protection (Rulesets)

Branch protection uses GitHub **repository rulesets** rather than the legacy
branch protection API. The template has a single ruleset named `main` applied
to the default branch.

### Ruleset: `main`

| Rule | Details |
| :--- | :--- |
| **Enforcement** | Active |
| **Target** | Default branch (`main`) |
| **Deletion** | Blocked -- cannot delete `main` |
| **Non-fast-forward** | Blocked -- no force pushes |
| **Creation** | Controlled |
| **Required linear history** | Enforced (squash merges only) |
| **Required signatures** | Commits must be signed |
| **Pull request required** | Yes, with the following parameters: |
| | Required approving reviews: 0 |
| | Dismiss stale reviews on push: Yes |
| | Require code owner review: No |
| | Require last push approval: No |
| | Required review thread resolution: Yes |
| | Allowed merge methods: squash only |
| **Required status checks** | `require-label` (from the Merge Gate workflow) |
| | Strict policy: Yes (branch must be up to date) |
| **Required status checks** | `CodeQL` check-run emitted by `.github/workflows/codeql.yml` |
| **Code quality** | Errors severity threshold |
| **Bypass actors** | Repository admin role (always) |

**Automated:** Yes, rulesets are replicated from the template by
`configure_branch_protection()`.

## Labels

Labels are used by issue templates, workflows, release notes, and Dependabot.

**Source of truth:** `.github/labels.yml`. The file is a flat list of entries with `name`, `color` (6-char hex, no leading `#`), and `description`. Run `doit labels_sync` to reconcile the repository's labels with the file.

```bash
doit labels_sync --dry-run   # Preview changes
doit labels_sync             # Create missing labels, update drift
doit labels_sync --prune     # Also delete labels not in the file
```

The task is idempotent — running it twice in a row is a no-op the second time. Color comparison is case-insensitive. `--prune` is off by default because deletion is destructive.

To add a label: edit `.github/labels.yml`, run `doit labels_sync --dry-run` to preview, then `doit labels_sync` to apply.

| Label | Color | Description | Used By |
| :--- | :--- | :--- | :--- |
| `automated` | `#02db74` | -- | Dependabot PRs |
| `bug` | `#d73a4a` | Something isn't working | Issue template, release notes |
| `chore` | `#FEF2C0` | Maintenance, tooling, CI tasks | Issue template |
| `dependencies` | `#0366d6` | Pull requests that update a dependency file | Dependabot PRs, release notes exclusion |
| `documentation` | `#0075ca` | Improvements or additions to documentation | Issue template, release notes |
| `duplicate` | `#cfd3d7` | This issue or pull request already exists | Manual triage |
| `enhancement` | `#a2eeef` | New feature or request | Issue template, release notes |
| `full-matrix` | `#1D76DB` | Run CI on all supported Python versions | `CI (full matrix)` workflow (dispatches `ci.yml` with `full_matrix: true`) |
| `github_actions` | `#000000` | Pull requests that update GitHub Actions code | Dependabot PRs |
| `good first issue` | `#7057ff` | Good for newcomers | Manual triage |
| `help wanted` | `#008672` | Extra attention is needed | Manual triage |
| `invalid` | `#e4e669` | This doesn't seem right | Manual triage |
| `needs-adr` | `#d4c5f9` | This issue requires an Architecture Decision Record | PR merge gate |
| `needs-triage` | `#FBCA04` | Needs review and prioritization | All issue templates |
| `question` | `#d876e3` | Further information is requested | Manual triage |
| `ready-to-merge` | `#0E8A16` | PR is reviewed and ready to merge. Exception: the `dependabot-automerge` workflow applies this label automatically to qualifying dependabot PRs. | Merge Gate workflow |
| `refactor` | `#F9D0C4` | Code refactoring and cleanup | Issue template |
| `security` | `#d73a4a` | Security vulnerability or fix | Manual triage |
| `wontfix` | `#ffffff` | This will not be worked on | Manual triage |

### Label usage by issue template

| Template | Auto-applied labels |
| :--- | :--- |
| Bug Report | `bug`, `needs-triage` |
| Feature Request | `enhancement`, `needs-triage` |
| Refactor Request | `refactor`, `needs-triage` |
| Documentation Request | `documentation`, `needs-triage` |
| Chore / Maintenance | `chore`, `needs-triage` |

**Automated:** Yes, labels are copied from the template repository.

## GitHub Actions Workflows

All workflow files live in `.github/workflows/`. The table below summarizes
each workflow, its trigger, and required permissions.

| Workflow | File | Trigger | Permissions |
| :--- | :--- | :--- | :--- |
| **CI** | `ci.yml` | PR to `main` (opened, synchronize, reopened), `workflow_dispatch`, `workflow_call` | `contents: read` |
| **CI (full matrix)** | `ci-full-matrix.yml` | PR to `main` (labeled with `full-matrix`) -- dispatches `ci.yml` with `full_matrix: true` | `contents: read` |
| **CodeQL** | `codeql.yml` | Push to `main`, PR to `main`, Scheduled (Monday 04:27 UTC) | `contents: read`, `security-events: write`, `actions: read` |
| **Merge Gate** | `merge-gate.yml` | PR to `main` (opened, labeled, unlabeled, synchronize, reopened) | `contents: read` |
| **PR Validation** | `pr-checks.yml` | PR (opened, edited, synchronize) | `contents: read`, `pull-requests: read` |
| **Breaking Change Detection** | `breaking-change-detection.yml` | PR (opened, synchronize, edited) | `contents: read`, `issues: write`, `pull-requests: write` |
| **Benchmark** | `benchmark.yml` | Push to `main`, PR to `main`, `workflow_dispatch` | `contents: write`, `pull-requests: write` |
| **Mutation Testing** | `mutation.yml` | Scheduled (Sunday midnight UTC), `workflow_dispatch` | `contents: read` |
| **Release** | `release.yml` | Tag push (`v*.*.*`), `workflow_dispatch` | `contents: read`, `id-token: write` (per job: `contents: write`) |
| **TestPyPI** | `testpypi.yml` | Tag push (`v*-*`), `workflow_dispatch` | `contents: read`, `id-token: write` |

### Key workflow details

- **CI** uses a matrix strategy with Python versions from
  `.github/python-versions.json`; only the bookend versions are tested on
  every push. Adding the `full-matrix` label to a PR triggers the dedicated
  `CI (full matrix)` workflow, which calls `ci.yml` with
  `full_matrix: true` to cover the middle versions.
- **Merge Gate** requires the `ready-to-merge` label on a PR before the
  `require-label` status check passes. This is a manual gate added by a reviewer.
- **Release** publishes to TestPyPI first, then PyPI, then creates a GitHub
  Release with auto-generated notes and SBOM attachments.

For detailed CI configuration, see the [CI/CD Testing Guide](ci-cd-testing.md).

## GitHub Environments

Release workflows use GitHub environments for OIDC-based publishing.

| Environment | Used By | Purpose |
| :--- | :--- | :--- |
| `testpypi` | `release.yml`, `testpypi.yml` | Publish pre-release and release packages to TestPyPI |
| `pypi` | `release.yml` | Publish release packages to PyPI |

### OIDC Trusted Publisher Configuration

Both environments use PyPI's trusted publisher mechanism instead of API tokens.
PyPI scopes each trusted publisher per `(owner, repo, workflow, environment)`
tuple, so the template requires **three** separate registrations — one for
each `(workflow, env)` pair the publish flow uses:

| # | Host | Workflow | Environment | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| 1 | TestPyPI | `testpypi.yml` | `testpypi` | Pre-release uploads (`v*-*` tags) |
| 2 | TestPyPI | `release.yml` | `testpypi` | Production-release canary (before PyPI) |
| 3 | PyPI | `release.yml` | `pypi` | Production-release publish |

For every registration, supply the same common fields:

- **Publisher:** GitHub Actions
- **Owner:** Your GitHub username or organization
- **Repository:** Your repository name

Then fill in the row-specific **Workflow** and **Environment** from the
table above. Missing registration #2 is the most common failure mode —
pre-releases still work, but the first production release fails at the
`release.yml` TestPyPI canary step with `403 Invalid API Token: OIDC
scoped token is not valid for project`.

**Automated:** Partial. Run `doit publish_setup` to create the `testpypi`
and `pypi` environments in one step (idempotent). Trusted publishers must
still be configured manually on PyPI and TestPyPI — see the instructions
printed by `doit publish_setup` and the
[release automation guide](release-and-automation.md#github-environments-trusted-publishing).

## Secrets and Variables

| Secret/Variable | Kind | Required | Purpose |
| :--- | :--- | :--- | :--- |
| `GITHUB_TOKEN` | Secret | Automatic | Provided by GitHub Actions; used by most workflows |
| `CODECOV_TOKEN` | Secret | Optional | Upload coverage reports to Codecov |
| `RELEASE_APP_ID` | **Variable** | Recommended | GitHub App ID used by release automation and the dependabot auto-merge workflow |
| `RELEASE_APP_PRIVATE_KEY` | Secret | Recommended | GitHub App private key matching `RELEASE_APP_ID` |

PyPI publishing uses OIDC (trusted publishers), so no `PYPI_TOKEN` secret is
needed.

!!! note "App credentials are strongly recommended"
    `RELEASE_APP_ID` and `RELEASE_APP_PRIVATE_KEY` are technically optional,
    but the dependabot auto-merge workflow degrades gracefully without them:
    the `ready-to-merge` label is still applied (via `GITHUB_TOKEN`), but the
    Merge Gate will **not** re-run automatically on the `labeled` event — a
    consequence of GitHub's workflow-triggering
    [loop-prevention rule](https://docs.github.com/en/actions/using-workflows/triggering-a-workflow#triggering-a-workflow-from-a-workflow).
    Configure the App for fully automated dependabot merges. See
    [Dependabot Auto-merge → Required GitHub App configuration](dependabot-automerge.md#required-github-app-configuration).

!!! warning "`RELEASE_APP_ID` is a Variable, not a Secret"
    `RELEASE_APP_ID` is stored as a **repository Variable**
    (`vars.RELEASE_APP_ID`), not a Secret. Workflows reference it as
    `${{ vars.RELEASE_APP_ID }}`. Storing it as a Secret would silently
    produce an empty string at runtime.

**Automated:** No. Secrets and variables must be added manually in
repository settings.

## Security Settings

Security features are configured by `_configure_security_settings()` in
`repo_settings.py`.

| Setting | Status | Purpose |
| :--- | :--- | :--- |
| **Secret scanning** | Enabled | Detects accidentally committed secrets |
| **Secret scanning push protection** | Enabled | Blocks pushes containing secrets |
| **Dependabot security updates** | Enabled | Automatic PRs for vulnerable dependencies |
| **CodeQL analysis** | Workflow-driven | Runs from `.github/workflows/codeql.yml` on every push to `main`, PR to `main`, and weekly schedule |

!!! note
    Secret scanning and push protection are available for free on public
    repositories. Private repositories require GitHub Advanced Security (GHAS).

**Automated:** Yes, security settings are copied from the template. CodeQL
runs as a committed GitHub Actions workflow (`.github/workflows/codeql.yml`)
and is replicated automatically when the template generator copies workflow
files into a new repository — no extra API call is required.

## Dependabot

Dependabot is configured via `.github/dependabot.yml` with two ecosystems:

| Ecosystem | Directory | Schedule | Labels |
| :--- | :--- | :--- | :--- |
| `uv` | `/` | Weekly (Monday 09:00 UTC) | `dependencies`, `automated` |
| `github-actions` | `/` | Weekly (Monday 09:00 UTC) | `dependencies`, `automated` |

### Grouping

Dev dependencies (`pytest*`, `ruff`, `mypy`, `coverage`) are grouped into a
single PR under the `uv` ecosystem.

### Commit message prefix

All Dependabot commits use the `chore(deps)` prefix to follow conventional
commits format.

**Automated:** No. The `.github/dependabot.yml` file is part of the template
and included in new repositories, but Dependabot itself must be enabled in
repository settings if not already active.

## GitHub Pages

Documentation is published to GitHub Pages from the `gh-pages` branch.

| Setting | Value |
| :--- | :--- |
| **Source branch** | `gh-pages` |
| **Source path** | `/` (root) |
| **Build tool** | MkDocs with Material theme |
| **Deployment** | Handled by CI or manual `doit docs_build` |

**Automated:** Yes, `enable_github_pages()` configures Pages on the
`gh-pages` branch. The branch itself is created on the first documentation
deployment.

## Code Owners

The `.github/CODEOWNERS` file defines default reviewers for pull requests.
The template sets `@username` as the owner for all paths. After creating a
new project, update the file with the actual repository owner's GitHub
username.

Key ownership areas defined:

- `*` -- Default owner for all files
- `/docs/` and `*.md` -- Documentation
- `/.github/` -- GitHub configuration
- `/.github/workflows/` -- CI/CD pipelines
- `/src/` -- Core source code
- `/tests/` -- Test files
- `pyproject.toml` -- Project configuration
- `dodo.py` -- Task automation

**Automated:** No. The file is part of the template but requires manual
update with the correct username.

## Release Notes

Auto-generated release notes are configured in `.github/release.yml`.

| Category | Labels |
| :--- | :--- |
| Breaking Changes | `breaking` |
| New Features | `enhancement`, `feat` |
| Bug Fixes | `bug`, `fix` |
| Documentation | `documentation`, `docs` |
| Performance | `performance`, `perf` |
| Other Changes | `*` (catch-all) |

### Excluded from release notes

PRs with these labels are excluded from auto-generated notes:

- `dependencies`
- `needs-triage`

**Automated:** No. The `.github/release.yml` file is part of the template.

## Special Branches

| Branch | Purpose | Protected |
| :--- | :--- | :--- |
| `main` | Default branch; all PRs target this branch | Yes (ruleset) |
| `gh-pages` | Published documentation site | No |
| `gh-benchmarks` | Benchmark trend data for the Benchmark workflow | No |

## Summary of Manual Steps

After creating a new repository from the template, these items require manual
configuration:

1. **Environments** -- Run `doit publish_setup` to create the `testpypi` and `pypi` environments in one step
2. **OIDC Trusted Publishers** -- Configure on PyPI and TestPyPI
3. **Secrets** -- Add `CODECOV_TOKEN` and optional release app credentials
4. **CODEOWNERS** -- Replace `@username` with the actual owner
5. **Dependabot** -- Verify Dependabot is enabled in repository settings

For the full post-setup checklist, see the [New Project Setup](../template/new-project.md) guide.
