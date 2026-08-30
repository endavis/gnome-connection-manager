---
title: New Project Setup
description: Create a new Python project from this template
audience:
  - users
tags:
  - template
  - getting-started
  - setup
---

# New Project Setup

Create a new Python project from this template using either the automated or manual approach.

> **Tip:** For an interactive experience, use the [Template Manager](manage.md):
> ```bash
> python tools/pyproject_template/manage.py
> ```
> Select option **[1] Create new project from template** to be guided through the process.

## Automated Setup (Recommended)

The fastest way to create a new project:

```bash
curl -sSL https://raw.githubusercontent.com/endavis/pyproject-template/main/bootstrap.py | python3
```

### What It Does

The bootstrap script (`setup_repo.py`) automates the entire setup:

1. **Creates GitHub repository** from the template
2. **Configures repository settings**:
   - Disables wiki and projects (optional features)
   - Enables issues and discussions
   - Sets merge options (squash, delete branch on merge)
3. **Sets up branch protection** for `main`:
   - Requires PR reviews
   - Requires status checks to pass
   - Prevents force pushes
4. **Replicates labels** from the template repository
5. **Runs placeholder replacement** (`configure.py`)
6. **Clones the repository** locally
7. **Removes the template management suite** (`tools/pyproject_template/`,
   `docs/template/`, `bootstrap.py`) so your consumer project owns a clean
   tree. If you later want ongoing template sync, reinstall the suite with
   `bootstrap.py --sync` (see [Keeping Up to Date](updates.md)).
8. **Prints next steps** checklist

### Requirements

- [GitHub CLI](https://cli.github.com/) installed and authenticated (`gh auth login`)
- Git installed
- Python 3.12+

### Interactive Prompts

The script will ask for:

| Prompt | Description | Example |
|--------|-------------|---------|
| Repository name | Name for your new repo | `my-python-project` |
| Description | Short project description | `A utility for processing data` |
| Visibility | Public or private | `public` |
| Package name | Python import name (snake_case) | `my_python_project` |
| Author name | Your name | `Jane Doe` |
| Author email | Your email | `jane@example.com` |

### Post-Setup Manual Steps

After the script completes, you'll need to:

1. **Bootstrap PyPI publishing environments** (one step):
   ```bash
   doit publish_setup
   ```
   This creates the `testpypi` and `pypi` GitHub environments used for OIDC
   trusted publishing and prints the manual trusted-publisher registration
   instructions. See the
   [release automation guide](../development/release-and-automation.md#github-environments-trusted-publishing)
   for background.

   > **Note:** The template management suite (`tools/pyproject_template/`,
   > `docs/template/`, `bootstrap.py`) was auto-removed during setup so your
   > project owns a clean tree. If you later want ongoing template sync,
   > reinstall the suite by running:
   > ```bash
   > curl -sSL https://raw.githubusercontent.com/endavis/pyproject-template/main/bootstrap.py \
   >     | python3 - --sync
   > ```

2. **Add Codecov token** (optional, for coverage reports):
   - Sign up at [codecov.io](https://codecov.io)
   - Add `CODECOV_TOKEN` to repository secrets

3. **Configure collaborators** if needed:
   - Settings → Collaborators and teams

4. **Enable GitHub Pages** (for documentation):
   - Settings → Pages → Deploy from branch `gh-pages`

## Manual Setup

If you prefer more control, set up the template manually.

### Step 1: Create Repository from Template

**Option A: Use GitHub's template feature**

1. Go to [pyproject-template](https://github.com/endavis/pyproject-template)
2. Click "Use this template" → "Create a new repository"
3. Fill in repository details
4. Clone your new repository locally

**Option B: Clone directly**

```bash
# Clone the template
git clone https://github.com/endavis/pyproject-template.git my-project
cd my-project

# Remove template's git history and start fresh
rm -rf .git
git init
git add .
git commit -m "feat: initial commit from pyproject-template"

# Create GitHub repo and push
gh repo create my-project --public --source=. --push
```

### Step 2: Run Configuration

Replace all placeholder values with your project information:

```bash
python tools/pyproject_template/manage.py configure
```

The script will prompt for:

- Project name (display name)
- Package name (import name, snake_case)
- PyPI name (package name on PyPI, typically with hyphens)
- Author name and email
- GitHub username
- Project description

### What Configure Does

The `configure.py` script:

1. **Replaces placeholders** in all relevant files:
   - `pyproject.toml` - Package metadata
   - `README.md` - Badges and links
   - `mkdocs.yml` - Documentation site
   - `.github/workflows/*` - CI/CD configuration
   - `docs/*` - Documentation content

2. **Renames the source directory**:
   - `src/package_name/` → `src/your_package_name/`

3. **Updates badge URLs** for CI, coverage, and PyPI

### Step 3: Set Up Development Environment

```bash
# Allow direnv (if installed)
direnv allow

# Or manually set up
uv sync --all-extras --dev
doit pre_commit_install
```

#### Enable Shell Completions (Optional)

Enable tab completion for `doit` commands:

```bash
# Generate and install completions to your shell config
doit completions_install
```

This will:
- Generate completion scripts in `completions/`
- Add source lines to `~/.bashrc` (Bash) and/or `~/.zshrc` (Zsh)

After installation, reload your shell:
```bash
source ~/.bashrc   # For Bash
source ~/.zshrc    # For Zsh
```

### Step 4: Remove the Template Management Suite

The automated setup does this for you; the manual route has to be told:

```bash
uv run doit template_clean --all
```

This deletes `tools/pyproject_template/`, `docs/template/` and `bootstrap.py` —
the template's own management code, which your project does not use. Keeping it
also leaves your coverage gate measuring several thousand statements of tooling
whose tests are template-owned and were shed during configuration, which puts a
fresh project under `fail_under` on its first CI run.

To reinstall the template-sync suite later:

```bash
curl -sSL https://raw.githubusercontent.com/endavis/pyproject-template/main/bootstrap.py | python3 - --sync
```

### Step 5: Verify Setup

```bash
# Run all checks
doit check

# Should see:
# ✓ format_check
# ✓ lint
# ✓ type_check
# ✓ test
# ✓ All checks passed!
```

### Step 6: Configure GitHub Repository

Manually configure what the automated setup does automatically:

1. **Repository settings** (Settings → General):
   - Enable/disable features as needed
   - Set merge options

2. **Branch protection** (Settings → Branches):
   - Add rule for `main`
   - Require pull request reviews
   - Require status checks

3. **PyPI publishing environments**:
   - Run `doit publish_setup` to create the `testpypi` and `pypi`
     environments and print the trusted-publisher registration steps.
   - Follow the links in the printed output to register **three** trusted
     publishers — one per `(workflow, environment)` pair. See the
     [release automation guide](../development/release-and-automation.md#trusted-publisher-registration-manual)
     for the full table.

4. **Secrets** (Settings → Secrets → Actions):
   - Add `CODECOV_TOKEN` (optional, for coverage uploads)

5. **Labels**:
   - The template includes standard labels
   - Add custom labels as needed via Settings → Labels

## Next Steps

After setup is complete:

1. **Start coding** in `src/your_package_name/`
2. **Write tests** in `tests/`
3. **Update documentation** in `docs/`
4. **Follow the workflow**: Issue → Branch → Commit → PR → Merge

See [CONTRIBUTING.md](https://github.com/endavis/pyproject-template/blob/main/.github/CONTRIBUTING.md) for the development workflow, and [Tooling Roles and Architectural Boundaries](../development/tooling-roles.md) for the conventions you are inheriting from the template.
