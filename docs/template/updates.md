---
title: Keeping Up to Date
description: Stay in sync with improvements to the pyproject-template
audience:
  - users
tags:
  - template
  - updates
---

# Keeping Up to Date

Stay in sync with improvements to the pyproject-template.

> **Tip:** The easiest way to check for updates is through the [Template Manager](manage.md):
> ```bash
> python tools/pyproject_template/manage.py
> ```
> Select option **[3] Check for template updates** to compare your project against the latest template, then **[5] Mark as synced** after applying changes.

> **Don't have the template management suite?** The automated
> [New Project Setup](new-project.md) removes the suite by default so your
> consumer project starts with a clean tree. Reinstall it at any time with:
> ```bash
> curl -sSL https://raw.githubusercontent.com/endavis/pyproject-template/main/bootstrap.py \
>     | python3 - --sync
> ```
> This installs `tools/pyproject_template/` back into your project so you
> can use `manage.py`, `check_template_updates.py`, and the rest of the
> sync tooling described below.

## Which template version you get

`bootstrap.py` resolves the ref once, up front, and fetches every file from that single commit.
A run is therefore internally consistent: `main` moving mid-run cannot give you half of one commit
and half of another.

It prints the commit it pinned to:

```
  Pinned to commit 4ef5b9c1a2b3 (from 'main')
```

**Record that SHA.** It is the answer to "which template version is this project synced against",
and it is what makes a sync reproducible.

To pin deliberately — reviewing an update before taking it, or reproducing an earlier sync — set
`PYPROJECT_TEMPLATE_REF` to a branch, tag or full SHA:

```bash
PYPROJECT_TEMPLATE_REF=4ef5b9c... curl -sSL https://raw.githubusercontent.com/endavis/pyproject-template/main/bootstrap.py | python3 - --sync
```

If `api.github.com` is unreachable or rate-limited, the run **warns and continues** against the
moving ref rather than failing. Pinning is a consistency improvement; refusing to bootstrap because
an API call failed would trade a small gain for a hard outage. Set `GITHUB_TOKEN` if you are being
rate-limited.

## When to Update

Consider checking for template updates when:

- A new template version is released
- You want new tooling or workflow improvements
- You're starting a new phase of development
- Security updates are announced

## Using check_template_updates.py

The `check_template_updates.py` script compares your project against the latest template and shows what's different.

### Basic Usage

```bash
python tools/pyproject_template/manage.py check
```

### What It Does

1. **Fetches the latest template** (or specified version)
2. **Opens CHANGELOG.md** so you can review what changed
3. **Compares files** and categorizes them:
   - **Modified**: Files that exist in both but differ
   - **Missing**: Files in template but not in your project
   - **Extra**: Files in your project but not in template
4. **Generates a diff** for each modified file
5. **Cleans up** temporary files

### CLI Options

```bash
# Compare against a specific template release instead of the latest
python tools/pyproject_template/manage.py check --template-version v2.2.0
```

`--template-version` accepts a **tag, a branch, or a commit SHA**; the default is `main`. Whatever
you give it is resolved to a commit before anything is downloaded, so a check runs against one
fixed snapshot rather than a branch that can move underneath it:

```
i Comparing against template ref: main
i Downloading from https://github.com/endavis/pyproject-template/archive/5853ced….zip...
```

That is the same identity `bootstrap.py` pins, so the SHA it prints can be passed straight to
`manage.py check --template-version <sha>` to diff against exactly what you synced. See
[ADR-9020](https://github.com/endavis/pyproject-template/blob/main/docs/decisions/9020-a-template-version-is-a-commit-sha.md).

`--skip-changelog` and `--keep-template` are not exposed: `manage.py` already sets both, keeping the
downloaded template so you can run your own diffs and not opening an editor mid-run.

### Example Output

```
Comparing your project against the latest pyproject-template...

Latest template release: v2.3.0
Template extracted to tmp/pyproject-template-2.3.0

Opening CHANGELOG.md for review...
(Close the editor when you're done)

=== Comparison Results ===

Modified files (differ from template):
  - .github/workflows/ci.yml
  - dodo.py
  - .pre-commit-config.yaml

Missing files (in template, not in project):
  - .github/ISSUE_TEMPLATE/chore.yml
  - docs/template/updates.md

Your project-specific files (not in template):
  - src/mypackage/custom_module.py
  - tests/test_custom.py

Would you like to see diffs for modified files? [y/N]
```

## Reviewing Changes

### Understanding the Categories

| Category | Meaning | Action |
|----------|---------|--------|
| **Modified** | File exists in both but content differs | Review diff, merge selectively |
| **Missing** | New file in template you don't have | Consider adding if useful |
| **Extra** | Your project-specific files | Keep as-is (expected) |

### Files to Usually Update

These files typically should be kept in sync:

- `.github/workflows/*.yml` - CI/CD improvements
- `.pre-commit-config.yaml` - New hooks or version bumps
- `dodo.py` - New tasks or improvements
- `tools/pyproject_template/*.py` - Template tooling

### Breaking and behaviour changes

Before adopting drift, read **[Consumer Notes](consumer-notes.md)** — changes that arrive through
the sync path and need action. It currently carries a breaking change to `install_tools`
(`sha256` is now mandatory for non-GitHub hosts), a hook re-install that must be run once, and the
behaviour changes a project will notice without explanation.

### Files to Review Carefully

These may have project-specific customizations:

- `pyproject.toml` - Your dependencies differ
- `mkdocs.yml` - Your navigation differs
- `README.md` - Your content differs
- `.github/CONTRIBUTING.md` - May have project-specific rules
- `tools/doit/install_tools.py` - Adopting this requires `sha256=` for any non-GitHub
  download; see [Consumer Notes](consumer-notes.md#install_tools-requires-sha256-for-untrusted-hosts)

### Files to Usually Skip

These are project-specific:

- `src/your_package/*` - Your code
- `tests/*` - Your tests
- `docs/*.md` - Your documentation content
- `CHANGELOG.md` - Your release history

## Merging Updates

### Manual Merge Process

1. **Run the comparison**:
   ```bash
   python tools/pyproject_template/manage.py check
   ```
   The downloaded template is kept under `tmp/` so you can diff against it.

2. **Review the CHANGELOG** to understand what changed and why

3. **For each modified file**, decide:
   - **Accept template version**: Copy from `tmp/pyproject-template-*/`
   - **Keep your version**: No action needed
   - **Merge selectively**: Manually combine changes

4. **For missing files**, decide:
   - **Add the file**: Copy from template
   - **Skip**: Not needed for your project

5. **Test your changes**:
   ```bash
   doit check
   ```

6. **Commit the updates**:
   ```bash
   git add -A
   git commit -m "chore: update from pyproject-template vX.Y.Z"
   ```

### Using Git Diff Tools

For complex merges, use your preferred diff tool:

```bash
# Compare specific file
diff -u your_file.py tmp/pyproject-template-*/your_file.py

# Use visual diff tool
code --diff your_file.py tmp/pyproject-template-*/your_file.py
```

## AI Agent Workflow

If you're using an AI agent (Claude, Codex, etc.) to perform the synchronization, see the **[AI Sync Checklist](ai-sync-checklist.md)** for a structured, step-by-step guide covering all phases from pre-flight through commit.

## Best Practices

1. **Update regularly** - Small, frequent updates are easier than large ones

2. **Read the CHANGELOG** - Understand what changed before merging

3. **Test after updating** - Always run `doit check` after merging changes

4. **Commit updates separately** - Keep template updates in their own commits

5. **Document deviations** - If you intentionally differ from template, note why

## Troubleshooting

### Script Can't Fetch Template

If you're behind a proxy or have network issues:

```bash
# Download template manually
wget https://github.com/endavis/pyproject-template/archive/refs/heads/main.zip
unzip main.zip -d tmp/

# Compare manually
diff -r your_project/ tmp/pyproject-template-main/
```

### Too Many Differences

If your project has diverged significantly:

1. Focus on critical files first (CI, pre-commit)
2. Skip content files (docs, README)
3. Consider a fresh migration if heavily outdated
