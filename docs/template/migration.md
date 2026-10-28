---
title: Migration Guide
description: Migrate existing Python projects to use this template
audience:
  - users
tags:
  - template
  - migration
---

# Migration Guide

Bring your existing Python project into the pyproject-template.

> **How much of this is automated:** steps 2, 3 and 12. Copying is one `rsync` invocation,
> `manage.py configure` rewrites every placeholder and renames `src/package_name` to your
> package, and `manage.py repo` applies the GitHub-side configuration a new project gets
> automatically. The rest is judgement about your own code: which dependencies to carry
> over, how imports change when moving to a `src/` layout. Work through the checklist.

## Let an agent plan it for you

The `template-migrate` skill reads your project, fetches this checklist, asks you what your
repository cannot answer, and writes a plan specific to your code — layout, dependencies, what will
break — to `TEMPLATE_MIGRATION_PLAN.md`. It changes nothing until you approve it.

It is **standalone**: copy one file into your project and activate it. Nothing else needs to be
installed first.

```bash
# Claude Code
mkdir -p .claude/skills/template-migrate && curl -sSL \
  https://raw.githubusercontent.com/endavis/pyproject-template/main/.agents/skills/template-migrate/SKILL.md \
  -o .claude/skills/template-migrate/SKILL.md

# Codex, Antigravity, or Copilot
mkdir -p .agents/skills/template-migrate && curl -sSL \
  https://raw.githubusercontent.com/endavis/pyproject-template/main/.agents/skills/template-migrate/SKILL.md \
  -o .agents/skills/template-migrate/SKILL.md
```

Both commands fetch the same file: `.agents/skills/` is the one source, and Claude's copy is
byte-identical to it.

Then `/template-migrate` (Claude, Copilot), `$template-migrate` (Codex), or just describe the task
(Antigravity). See
[Slash Commands and Workflows](../development/ai/slash-commands.md#template-migrate-ref).

The plan it writes maps onto the checklist below, which stays authoritative — read it when a step is
ambiguous, or when migrating by hand.

## Manual Migration Checklist

Use this checklist for a manual migration. The flow assumes hatch-vcs for versioning, commitizen for tagging/changelog, uv for deps, and doit for tasks.

Run every command from **your project's root**, not from a template checkout.

### 1) Inventory & Prep
- Note current package import name, supported Python versions, dependencies (runtime/dev/extras), scripts/entry points, CI/release setup.
- Ensure current tests pass before migrating.

### 2) Bring in the Template

Copy **everything except your own code**. An inclusion list is the wrong shape here: the
template's top-level entries cross-reference each other — `dodo.py` imports `tools/doit/`,
`doit pr` reads `.github/pull_request_template.md`, `doit issue` reads
`.github/ISSUE_TEMPLATE/`. A list of "the important ones" silently omits whatever it was
not updated for.

**Backup first.** Four files are merged rather than overwritten in later steps, so keep
your originals:

```bash
for f in pyproject.toml README.md LICENSE CHANGELOG.md; do
    [ -f "$f" ] && cp "$f" "$f.old"
done
```

**Then copy:**

```bash
git clone --depth=1 https://github.com/endavis/pyproject-template.git ../pyproject-template-src

rsync -a \
    --exclude='.git/' \
    --exclude='src/' \
    --exclude='tests/' \
    ../pyproject-template-src/ ./
```

Your git history is untouched — this copies files into your existing repository rather
than starting a new one.

**What is excluded, and why:**

| Excluded | Reason |
| :--- | :--- |
| `.git/` | Your history. Copying the template's would replace it. |
| `src/` | Your package. The template ships a skeleton you do not want. |
| `tests/` | Your tests. Step 6 moves them into the new layout. |

Everything else is copied, including the parts a hand-written list tends to miss:
`tools/` (which `dodo.py` imports — without it `doit check` cannot run), the whole of
`.github/` rather than just `workflows/`, and dotfiles such as `.gitignore` and
`.editorconfig`.

> **Windows:** Git Bash does not ship `rsync`. Use WSL, or copy the clone's contents by
> hand and then delete the template's `src/` and `tests/` from your project before
> continuing.

### 3) Run the Template Manager
- From your project root: `python tools/pyproject_template/manage.py`.
- Select **[2] Configure project** to run the configurator.
- Provide project name, package name (import), PyPI name, author, GitHub user, description.
- **What it does:** Rewrites placeholders (badges/links/docs/workflows), renames `src/package_name → src/<your_package>`.

See [Template Management](manage.md) for full documentation on the management script.

### 4) Move Your Code
- Move your existing package source into the newly renamed `src/<your_package>/`.
- **Cleanup:** Delete the template's default `core.py` if not needed.
- **Type Hinting:** Ensure `py.typed` exists in `src/<your_package>/` to mark your package as typed.
- **Versioning:** Leave `_version.py` as the stub; hatch-vcs generates it at build time from git tags.

### 5) Update pyproject.toml
- **Merge, don't overwrite:** Copy your dependencies and metadata *into* the new `pyproject.toml`. Preserve the `[tool]` sections (hatch, ruff, mypy, doit) provided by the template.
- Update `[project.dependencies]`.
- Add dev tools to `[project.optional-dependencies]` (keep the template's defaults like `ruff`, `pytest` if possible).
- Define entry points under `[project.scripts]` if you have a CLI.
- If your project distinguishes `authors` from `maintainers`, restore that split from your
  backup: the template ships `authors` only, and the configurator asks for a single name.

### 6) Tests & Coverage
- Move your tests to `tests/`.
- If moving from a flat layout to `src/`, you may need to adjust imports in your tests.
- Ensure `dodo.py` and workflows point coverage to the correct package (handled by `configure.py`, but worth double-checking).

### 7) Regenerate Lockfile
- Run `uv lock` to refresh `uv.lock` with your merged dependencies.

### 8) Tasks and CI
- Local tasks: `doit check` runs format (ruff), lint, mypy, tests.
- Workflows: `ci.yml` runs checks; `release.yml` triggers on stable `v*` tags; `testpypi.yml` triggers on prerelease `v*-<pre>` tags.

### 9) Docs & Badges
- Check `README.md`: Restore your project description, but keep the new badges (links were updated by `configure.py`).
- Update docs (`docs/getting-started/installation.md`, `docs/usage/`, `docs/reference/api.md`) with your specific details.

### 10) Verify Locally
- Install environment: `uv sync --all-extras --dev`
- Install hooks: `doit pre_commit_install`
    - Already ran this in an earlier migration? Run it again. The config now declares four hook
      types and `commit-msg` is newly among them, so an older install has no `commit-msg` hook
      and neither conventional-commit enforcement nor the branch/issue check fires. Verify with
      `ls .git/hooks/` — see [Consumer Notes](consumer-notes.md#re-run-doit-pre_commit_install).
- Run checks: `doit check`
- Run tests: `doit test`
- Optional — tab completion for `doit`: `doit completions_install`

### 11) Commit the Migration

Commit and push before configuring GitHub. The next step reads the workflows and labels
you just brought in, and branch protection will require status checks that must exist on
the remote first.

### 12) Configure the GitHub Repository

A project created by the automated setup gets its GitHub-side configuration applied by
`setup_repo.py`. A migrated project has to ask for it:

```bash
python tools/pyproject_template/manage.py repo
```

Preview it first with `python tools/pyproject_template/manage.py --dry-run repo` — the
flag is global, so it goes before the subcommand.

This applies:

| Applied | Covers |
| :--- | :--- |
| Repository settings | Description, features (issues, discussions, wiki), merge options |
| Security settings | Secret scanning, push protection, Dependabot security updates |
| Branch protection | Rulesets on `main` — required reviews, required status checks, no force pushes |
| Labels | Replicated from the template repository |
| GitHub Pages | Enabled for the documentation site |

It reads your GitHub user and repository from `.config/pyproject_template/settings.toml`,
which step 3 wrote. Some settings are unavailable on private repositories without GitHub
Advanced Security; the script reports those and continues.

**Labels specifically.** `manage.py repo` runs `doit labels_sync` against the committed
`.github/labels.yml`, creating missing labels and updating drifted ones. If `uv` or that
file is missing it falls back to copying the template's labels as they exist on GitHub.
To run the sync yourself:

```bash
doit labels_sync            # add and update
doit labels_sync --dry-run  # preview
```

The `ready-to-merge` label matters: `merge-gate.yml` requires it, so without it every pull
request carries a permanently failing check.

### 13) Publishing and Secrets

Neither is applied by `manage.py repo` — both need credentials it does not have.

**PyPI trusted publishing** (required before step 14 can release anything):

```bash
doit publish_setup
```

This creates the `testpypi` and `pypi` GitHub environments and prints the registration
instructions. Follow them to register **three** trusted publishers — one per
`(workflow, environment)` pair. See the
[release automation guide](../development/release-and-automation.md#trusted-publisher-registration-manual)
for the full table.

**Codecov** (optional, for coverage reporting):

1. Sign up at [codecov.io](https://codecov.io) and add your repository.
2. `gh secret set CODECOV_TOKEN`

### 14) Release Flow
- **All releases go through a PR.** `doit release [--prerelease=alpha|beta|rc]` opens a release PR with the version bump and changelog updates.
- **Tag after merge.** Once the release PR is merged, run `doit release_tag` to tag `main` and trigger the publish workflow (`testpypi.yml` for pre-releases, `release.yml` for production tags).
- **Important:** No manual edits to `pyproject.toml` version or `_version.py`; the git tag is the source of truth.

### 15) Record the Template Version

Your project now needs to know *which* template it came from, or the first update check
will present the entire template as a diff:

```bash
python tools/pyproject_template/manage.py sync
```

This records the reviewed commit SHA. A template version is a commit SHA, not a release
tag — see [ADR-9020](../decisions/9020-a-template-version-is-a-commit-sha.md).

### 16) Clean Up & Commit
- Remove old CI configs/Makefiles you no longer need.
- Delete `../pyproject-template-src` and the `*.old` backups from step 2 once you have
  merged everything out of them.
- `direnv allow` to load `.envrc`.
- Commit and push. Monitor CI actions to ensure the migration was successful.

## Keeping or Shedding the Template Suite

Step 2 brings in `tools/pyproject_template/`, `docs/template/` and `bootstrap.py` — the
template's own management code. Keeping them is what makes steps 12 and 15 and all of
[Keeping Up to Date](updates.md) possible, and it costs nothing measurable: the coverage
gate omits `tools/pyproject_template/` (`pyproject.toml`), `docs/template/` is
documentation, and `bootstrap.py` is outside the gate's scope.

If you would rather not carry it, shed it with `doit template_clean --all` and reinstall
later when you want to sync:

```bash
curl -sSL https://raw.githubusercontent.com/endavis/pyproject-template/main/bootstrap.py | python3 - --sync
```

## Staying Updated

After migration, use [Keeping Up to Date](updates.md) to stay in sync with template improvements.
