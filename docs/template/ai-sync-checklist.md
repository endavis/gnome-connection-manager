---
title: AI Agent Sync Checklist
description: Step-by-step checklist for AI agents synchronizing downstream projects with pyproject-template
audience:
  - ai-agents
tags:
  - template
  - sync
  - ai
---

# AI Agent Checklist: Synchronize with pyproject-template

This checklist guides an AI agent through synchronizing a downstream project with the latest pyproject-template. It uses the official `manage.py` tooling documented in [Template Manager](manage.md), [Keeping Up to Date](updates.md), and [Tools Reference](tools-reference.md).

**Prerequisites:**

- Downstream project already uses pyproject-template structure (doit tasks, CI workflows, pre-commit, etc.)
- Template repo: `endavis/pyproject-template`

---

## Pre-Flight

- [ ] Verify on `main` branch and clean working tree (`git status`)
- [ ] Run `doit check` to confirm current state passes
- [ ] Create a GitHub Issue for the sync work:
  ```bash
  doit issue --type=chore --title="chore: synchronize with latest pyproject-template" \
    --body="## Description\nSynchronize project with latest pyproject-template improvements."
  ```
- [ ] Create branch linked to the issue (e.g., `chore/<issue#>-sync-pyproject-template`)
- [ ] Read [Consumer Notes](consumer-notes.md) — the breaking and behaviour changes that
      arrive through this sync. Note which apply to this project before adopting any drift.

---

## Phase 1: Sync Template Management Tools (Always Run First)

Run `bootstrap --sync` at the start of **every** sync, not just the first time.
This ensures the tooling suite in `tools/pyproject_template/` matches the version of the template
you are about to adopt. Applying file diffs with a stale tooling version can produce incorrect results.

```bash
curl -sSL https://raw.githubusercontent.com/endavis/pyproject-template/main/bootstrap.py | python3 - --sync
```

This will:

1. Overwrite the management suite in `tools/pyproject_template/` with the latest template version:
    - `__init__.py`, `utils.py`, `settings.py`, `check_template_updates.py`, `manage.py`, `configure.py`, `cleanup.py`
2. Detect project settings from `pyproject.toml` (first-time only creates `.config/pyproject_template/settings.toml`)
3. Verify the installation

**Version-skew caveat:** The drift checker (`check_template_updates.py`) compares your files against the
template version it was fetched with. If your local tooling is older than the template version you are
comparing against, the checker may miss or misreport differences. Always run `bootstrap --sync` before running
the drift check.

**Template-owned tests:** The files listed in `TEMPLATE_OWNED_TEST_FILES` are excluded from the drift
report and shed by `cleanup --setup`; you do not need to adopt or maintain them. A test is
template-owned when **its target does not survive configuration** (ADR-9017) — which is broader than
"tooling tests". The list covers the management suite, and also `test_configure_paths.py`,
`test_readme_split.py` and `test_downstream_test_retention.py`, whose targets `configure.py`
consumes or destroys during setup. Everything else under `tests/` is yours to adopt, including the
`tools/doit/` and `tools/hooks/` tests, which cover code that ships to and runs in your project
(#731).

**New files you will see in this sync.** These are recent additions, all downstream-owned, so the
drift checker will offer them:

| File | Adopt? |
| :--- | :--- |
| `tests/agent_roster.py` | Yes — a helper, not a test. Required by the roster-aware tests below. |
| `tests/test_cross_agent_contract.py` | Yes if you wire more than one AI agent; it derives its scope from the roster and checks nothing for agents you dropped. |
| `tests/test_instruction_pointers.py` | Yes — catches instruction files pointing at sections and commands that do not exist. |
| `tests/test_workflow_action_pinning.py` | Yes if you keep `.github/workflows/`. |
| `tests/test_hermetic_suite.py` | Yes — keeps the unit suite off real external binaries. |
| `tests/test_hypothesis_profiles.py` | Yes if you kept the Hypothesis profiles in `conftest.py`. |
| `tools/hooks/check_commit_issue_ref.py` + `tests/test_hook_commit_issue_ref.py` | Yes, together, and re-run `doit pre_commit_install` after — the hook needs the `commit-msg` type. |
| `tests/test_agents_md_allocation.py` | Yes, **then trim `RELOCATION_TARGETS`**. It names template paths including `docs/development/dependabot-automerge.md`; a project without that doc adopts a test that cannot pass. |

The last row is the general hazard: a test can be downstream-owned and still name structure your
project does not have. Read the constants at the top of a test before adopting it.

After running bootstrap:

- [ ] Review `.config/pyproject_template/settings.toml` and correct any values (first-time only)
- [ ] Decide: Track `.config/pyproject_template/` in git or add to `.gitignore` (first-time only)
- [ ] **Existing projects:** run `cleanup --setup` once to shed any template-owned tests adopted in an earlier sync
- [ ] Verify: `python tools/pyproject_template/manage.py --dry-run check`

---

## Phase 2: Run Template Update Check

Per [Template Manager](manage.md) "Workflow: Staying Up to Date":

```bash
python tools/pyproject_template/manage.py --yes check
```

This will (per [Tools Reference](tools-reference.md)):

1. Fetch the template at `main` — or at a specific tag, branch or commit SHA via `manage.py check --template-version <ref>` (ADR-9020)
2. Compare all files - categorized as **Modified**, **Missing** (new in template), or **Extra** (project-specific)
3. Keep the template at `tmp/extracted/pyproject-template-main/` for diff commands
4. Show GitHub compare URL for commit history since last sync
5. Save commit info to `.template_commit` for later `sync` marking

**Diff commands** (per documentation):

```bash
diff <file> tmp/extracted/pyproject-template-main/<file>
```

Review the output and proceed with Phases 3-8 to selectively apply changes.

---

## Phase 3: pyproject.toml Tool Configuration

Configuration changes often enable new doit tasks and workflows, so this phase comes first.

### 3.1 Add Missing Tool Sections

Check template's pyproject.toml for sections not present in the project:

- [ ] `[tool.vulture]` - Dead code detection configuration
- [ ] `[tool.pyright]` - LSP/type checking for AI code editors

### 3.2 Update Existing Sections

Compare each `[tool.*]` section and apply template improvements:

- [ ] `[tool.ruff]` - New rules, updated ignores
- [ ] `[tool.mypy]` - Configuration updates
- [ ] `[tool.pytest.ini_options]` - Version bumps, new options
- [ ] `[tool.coverage]` - Threshold changes, exclude patterns
- [ ] `[tool.bandit]` - New skips, exclude patterns
- [ ] `[tool.commitizen]` - Format updates

**Decision points (ask user):**

- Coverage `fail_under` threshold (project may intentionally differ)
- Cache directory locations (template uses defaults, project may customize)
- Extended ignores/excludes (project-specific suppressions should be preserved)

### 3.3 Dev Dependencies

Add any new dev dependencies required by new doit tasks:

- [ ] `vulture` (for `task_deadcode()`)
- [ ] `radon` (for `task_complexity()` and `task_maintainability()`)
- [ ] `pyright` (for `[tool.pyright]`)
- [ ] Any other new tools referenced by updated doit tasks

---

## Phase 4: GitHub Workflows (`.github/workflows/`)

For each workflow file flagged as **Modified** or **Missing**:

- [ ] Compare each workflow against the template version
- [ ] Apply updates (new permissions, action version bumps, new features)
- [ ] **Preserve project-specific divergences** (e.g., custom OS matrix, extra setup steps, project-specific env vars)
- [ ] Verify workflows still reference the correct package name

**Files typically synchronized:**

- `ci.yml` - Test matrix, action versions, triggers
- `breaking-change-detection.yml` - Permissions, PR comment reporting
- `release.yml` - Release automation
- `testpypi.yml` - Pre-release testing
- `pr-checks.yml` - PR validation
- `merge-gate.yml` - Merge requirements

**Check for ADRs:** If the project has ADRs documenting intentional divergences from template workflows, respect those decisions.

---

## Phase 5: Doit Tasks (`tools/doit/`)

### 5.0 Breaking change: `install_tools` digests

- [ ] Does this project call `install_tool()` or `create_install_task()` with `url_template`
      for a **non-GitHub** host? If so, adopting `tools/doit/install_tools.py` aborts that
      install with `IntegrityError` until you pass `sha256=`.
- [ ] Take the digest from the publisher's checksums file, not from a download you have not
      verified. Per-platform digests use a dict keyed like `asset_patterns`.
- [ ] See [Consumer Notes](consumer-notes.md#install_tools-requires-sha256-for-untrusted-hosts).

### 5.1 Core Task Infrastructure

- [ ] Compare `tools/doit/__init__.py` for discovery mechanism updates
- [ ] Compare `tools/doit/base.py` for configuration changes (DOIT_CONFIG, helpers)

### 5.2 Quality Tasks

- [ ] Compare `tools/doit/quality.py` - check for new tasks:
    - `task_deadcode()` (uses vulture)
    - `task_complexity()` (uses radon cc)
    - `task_maintainability()` (uses radon mi)
    - Any new linting/formatting improvements

### 5.3 All Other Task Files

- [ ] Compare each of: `github.py`, `testing.py`, `security.py`, `maintenance.py`, `release.py`, `build.py`, `docs.py`, `git.py`, `install.py`, `adr.py`, `templates.py`
- [ ] Apply differences that are template improvements (not project-specific)
- [ ] Skip `template_clean.py` unless cleanup capability is desired

---

## Phase 6: AGENTS.md Updates

- [ ] Compare AGENTS.md between project and template
- [ ] Add new sections from template (e.g., Pre-Action Checks, Reasoning Examples)
- [ ] Update workflow commands and examples to match latest template patterns
- [ ] **Preserve all project-specific sections** (architecture, CLI, patterns, etc.)

---

## Phase 7: Pre-commit & Other Config

- [ ] After adopting `.pre-commit-config.yaml`, run `doit pre_commit_install` **again** —
      the config declares four hook types and `commit-msg` is newly among them. An earlier
      install leaves it absent, and conventional-commit enforcement silently does not run.
      Verify with `ls .git/hooks/`.

- [ ] Compare `.pre-commit-config.yaml` - hook versions, new hooks
- [ ] Compare `.github/CONTRIBUTING.md` for updated processes
- [ ] Compare `.github/pull_request_template.md` for new checklist items
- [ ] Compare `.github/ISSUE_TEMPLATE/*.yml` for template updates
- [ ] Compare `.github/python-versions.json` for version support changes

---

## Phase 8: AI Hooks

AI coding assistants (Claude Code, Copilot, Codex, Antigravity) use hooks to block dangerous commands. See [AI Command Blocking](../development/ai/command-blocking.md) for details.

### 8.1 Hook Scripts

- [ ] Compare `tools/hooks/ai/block-dangerous-commands.py` for new blocked patterns
- [ ] Compare `tests/test_hook_dangerous_command_matrix.py` for new block/allow cases
- [ ] Run `doit test` to verify hooks work

### 8.2 AI Agent Configuration

- [ ] Compare `.claude/settings.json` for Claude Code hook configuration
- [ ] Compare `.codex/config.toml` for Codex CLI approval policies
- [ ] **Review pinned model IDs.** `.claude/settings.json` pins
      `CLAUDE_CODE_SUBAGENT_MODEL`, and `tools/hooks/ai/precompact-checkpoint.py`
      passes a model to `claude -p`. Nothing in the update-check machinery looks at
      model IDs, so a pin from two generations ago survives indefinitely and silently
      (#696). `tests/template/test_model_pins.py` fails when a pinned ID leaves the
      current family — run `doit test` after syncing and update
      `CURRENT_MODEL_IDS` there if the family has moved on.

**Note:** If these configuration files don't exist in the downstream project, copy them from the template to enable AI safety hooks.

---

## Phase 9: Validation

- [ ] Run `doit check` - all checks must pass
- [ ] Run `doit test` - all tests must pass
- [ ] Run `doit pre_commit_run` - all hooks must pass
- [ ] Run `doit lint` - no new linting issues
- [ ] Run `doit type_check` - no new type errors
- [ ] If new quality tasks added: run them and verify output is reasonable

---

## Phase 10: Mark as Synced

Per [Template Manager](manage.md) step [5]:

```bash
python tools/pyproject_template/manage.py --yes sync
```

This:

1. Reads the reviewed commit from `tmp/extracted/pyproject-template-main/.template_commit` (saved during Phase 2)
2. Updates `.config/pyproject_template/settings.toml` with the template commit SHA and date
3. Cleans up the `tmp/extracted/` directory
4. Future runs of `manage.py check` will compare from this sync point

---

## Phase 11: Commit & PR

- [ ] Stage all changes
- [ ] Commit with conventional format:
  ```
  chore: synchronize with pyproject-template

  Syncs the following template improvements:
  - endavis/pyproject-template#<PR1> (description)
  - endavis/pyproject-template#<PR2> (description)
  - <additional changes summary>
  ```
- [ ] Create PR: `doit pr --title="chore: synchronize with pyproject-template" --body-file=<body>`
- [ ] PR body should reference the issue and list all synced template PRs

---

## Future Updates

Once `tools/pyproject_template/manage.py` is installed and sync state is tracked, future updates follow this simplified workflow:

1. **Check:** `python tools/pyproject_template/manage.py --yes check`
2. **Review:** Inspect diffs for Modified/Missing files
3. **Apply:** Manually merge relevant changes
4. **Validate:** `doit check`
5. **Mark synced:** `python tools/pyproject_template/manage.py --yes sync`
6. **Commit:** Follow issue → branch → PR workflow

---

## Key Principles

- **Selective merging:** Not all template changes apply to every project - review diffs carefully
- **Preserve divergences:** Projects may intentionally differ from template (document with ADRs)
- **Replace placeholders:** Any `__PACKAGE_NAME__` references in copied template content must be replaced with the actual package name
- **Validate before commit:** Always run `doit check` before staging - mandatory per project workflow
- **One PR per sync:** Keep all template synchronization changes in a single PR unless scope is too large
- **manage.py is the official tool:** Use it for checking updates and marking sync state
- **Read the CHANGELOG:** Review template CHANGELOG to understand why changes were made before applying
