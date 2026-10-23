---
name: template-migrate
description: Use when the user wants to migrate or convert an existing Python project to pyproject-template, adopt the template in a project that does not use it yet, or asks what migrating would involve. Reads the repository, fetches the template's documentation over HTTP, asks the owner what the repository cannot answer, and writes a migration plan to TEMPLATE_MIGRATION_PLAN.md. Changes nothing until the plan is approved.
---

# Template Migrate

Plan this project's migration onto `pyproject-template`
(https://github.com/endavis/pyproject-template).

**This skill plans. It does not migrate.** It reads the repository, fetches the template's own
documentation, asks the owner what the repository cannot tell it, and writes a migration plan to
`TEMPLATE_MIGRATION_PLAN.md`. Nothing in the project changes until the owner has read that plan and
said to proceed.

That split is deliberate. An automated migrator existed in the template once and was deleted
(endavis/pyproject-template#783) because it did the one mechanical step destructively while leaving
every judgement step untouched — which package is *the* package, how imports break moving to a
`src/` layout, which dependencies survive the merge. Those are the steps that need a plan, and they
are the ones this skill exists for.

## When to use

Use this skill when the user wants to bring an existing Python project onto the template, or wants
to know what that would involve.

Expected request shape:

- "plan our migration to pyproject-template"
- "what would it take to adopt this template here?"
- "plan the migration against v2.2.0"

The user may supply an optional template ref (tag, branch, or commit SHA) to plan against. Default
is `main`.

## Standalone

**Assume nothing from this template is installed.** No `tools/pyproject_template/`, no `dodo.py`
from here, no template documentation on disk. Every template fact below is fetched over HTTP.
`docs/template/*.md` in particular is not on this filesystem — reading it locally gets you nothing,
and an agent that finds nothing tends to invent the content rather than report the miss.

**Anything you do find belongs to the project, not to the template.** A `dodo.py`, an `AGENTS.md`,
a `tools/` directory, a `.claude/` — these are the owner's, they predate any contact with this
template, and they are conflicts to plan around rather than files to overwrite. If this repository
has its own `AGENTS.md` or agent instructions, **read them and follow them**; they outrank anything
this file says about how to work here.

The one pair that is genuinely template-specific is `tools/pyproject_template/` and
`.config/pyproject_template/`. Step 1 checks for those, and their presence means the project has
already migrated.

## Instructions

### Step 1: Confirm this is the right target

1. **Not the template itself.**
   ```bash
   git remote get-url origin
   ```
   If it points at `endavis/pyproject-template`, stop. This project *is* the template.

2. **Not already migrated.**
   ```bash
   ls -d tools/pyproject_template .config/pyproject_template 2>/dev/null
   ```
   If either exists, this project already uses the template. Stop and tell the user to use the
   `template-sync` skill instead — that is the one for upgrading a project that has already
   migrated.

3. **A git repository with a clean tree.**
   ```bash
   git status --short && git branch --show-current
   ```
   Planning is read-only, so a dirty tree is not fatal — but say so, because step 8 will need a
   clean one.

### Step 2: Pin the template version

Resolve the ref to a commit before fetching anything, so the plan records exactly what it planned
against and can be reproduced later:

```bash
REF="${REF:-main}"
TEMPLATE_SHA=$(curl -sSL -H "Accept: application/vnd.github.sha" \
  "https://api.github.com/repos/endavis/pyproject-template/commits/$REF")
echo "$TEMPLATE_SHA"
```

If that call fails — offline, rate-limited — fall back to the ref itself and **say so in the plan**,
because the plan is then against a moving target. `GITHUB_TOKEN` helps with rate limits.

Fetch from that commit, not from `main`:

```bash
RAW="https://raw.githubusercontent.com/endavis/pyproject-template/$TEMPLATE_SHA"
curl -sSL "$RAW/docs/template/migration.md"
```

Read at least these. Cite them in the plan rather than paraphrasing from memory:

| Fetch from `$RAW/` | What you need from it |
| :--- | :--- |
| `docs/template/migration.md` | The authoritative 15-step checklist your plan maps onto |
| `docs/template/consumer-notes.md` | Breaking changes and one-off actions |
| `AGENTS.md` | The workflow this project would be adopting |
| `.github/python-versions.json` | Which Python versions the template supports |
| `pyproject.toml` | The `[tool.*]` configuration that would land |
| `README.md` | What the template actually provides |

**Every row is the template's copy, fetched.** Four of those names — `AGENTS.md`, `pyproject.toml`,
`README.md`, and possibly `.github/python-versions.json` — may also exist in this repository as the
project's own files. Those are different files with the same name, and Step 3 reads them locally.
Keep the two straight: the fetched copy is what migrating would bring, the local copy is what is
here now, and the gap between them is the plan.

There is no documentation site for the template; raw URLs are the only online source.

### Step 3: Inventory this project — read only

Do not change anything. Establish:

- **Layout** — flat (`mypackage/`) or `src/`? This determines whether imports break in step 6 of the
  checklist, and it is the single most disruptive difference.
- **The package** — directory name, import name, and whether there is more than one. A repository
  with several top-level packages has no obvious answer; that is a question for Step 4.
- **Packaging** — where dependencies and metadata live today: `setup.py`, `setup.cfg`,
  `requirements*.txt`, `Pipfile`, `poetry.lock` / `[tool.poetry]`, `pdm.lock`, or a PEP 621
  `[project]` table. Each converts differently.
- **Python versions** — `requires-python`, classifiers, CI matrix.
- **Tests** — framework, location, whether they pass right now. Establish this *before* migrating;
  the checklist says so, and a suite that was already failing will otherwise be blamed on the
  migration.
- **CI** — what runs today, and anything project-specific the template's workflows would replace.
- **Tooling already in place** — ruff, black, flake8, isort, mypy, pyright, tox, nox, pre-commit,
  coverage. Overlaps are conflicts to resolve, not files to overwrite.
- **Task runner** — `dodo.py` (doit), `Makefile`, `noxfile.py`, `tasks.py` (invoke), `justfile`,
  npm scripts. The template ships `dodo.py` plus `tools/doit/`. A project that already uses doit has
  a direct collision; one that uses make or just has two task surfaces to reconcile. Either way it
  is a decision for the plan, not something to discover mid-copy.
- **Agent configuration** — `AGENTS.md`, `CLAUDE.md`, `.claude/`, `.agents/`, `.github/skills/`,
  `.github/instructions/`, `.cursor/`. These are the owner's instructions. The template ships its
  own `AGENTS.md` and agent config; where both exist they have to be merged deliberately, and the
  owner's rules win unless they say otherwise.
- **Entry points** — console scripts, plugin entry points.
- **Versioning** — hardcoded `__version__`, `setup.py` version, setuptools-scm, bumpversion. The
  template derives version from git tags via hatch-vcs, so any hardcoded version is going away.
- **Docs** — Sphinx, mkdocs, none. The template ships mkdocs.
- **License and changelog** — both are merge-don't-overwrite files.

### Step 4: Ask what the repository cannot tell you

**Ask rather than assume.** These decisions belong to the owner, and a plan that guesses them is a
plan that gets followed into the wrong shape. Batch them into one round — do not ask one at a time.

Ask about at least these, whenever the inventory leaves them open:

- **Which package is the one to ship,** if there is more than one, and whether the others stay.
- **PyPI name vs import name.** They differ often, and the template asks for both.
- **Does this project publish to PyPI at all?** If not, a large part of the template — release
  workflows, trusted publishing, TestPyPI — is scaffolding they may want but do not need on day one.
- **The Python version matrix.** The template supports what
  `.github/python-versions.json` names. Dropping a version their users depend on is a breaking
  change for them, not a formatting choice.
- **Existing CI.** Replace it with the template's, or keep both for a period? Project-specific jobs
  (deployment, integration tests against real services) will not be in the template.
- **Existing lint/format config.** Adopting the template's ruff rules will reformat their codebase
  in one commit. Some owners want that; some want it as a separate change afterwards.
- **An existing task runner**, if there is one. Replace it, or keep it alongside `doit`? A project
  already using doit has a `dodo.py` that will collide outright.
- **Existing agent instructions**, if there are any. The template ships its own `AGENTS.md` and
  agent configuration. Ask whether to merge the template's rules into theirs, keep theirs untouched,
  or take the template's wholesale — and default to preserving theirs.
- **`authors` vs `maintainers`.** The template ships `authors` only and the configurator asks for
  one name. If the project distinguishes them, that split has to be restored by hand.
- **The flat → `src/` move**, if applicable. It is the most invasive step and worth confirming they
  want it, rather than discovering it in the plan.

If the inventory raises none of these, say so explicitly — "no open questions" is a finding.

### Step 5: Assess the gap

For each area, three columns: what the template brings, what this project has, what conflicts.
Conflicts are the plan's real content — anything where both sides have an opinion needs a decision,
and the decision needs to be written down before anyone starts copying files.

### Step 6: Write the plan

Write `TEMPLATE_MIGRATION_PLAN.md` in the repository root. A file rather than an issue: the owner
decides whether it becomes an issue, a PR description, or nothing at all.

```markdown
# Migration Plan: <project> → pyproject-template

Planned against template commit <sha> (<ref>) on <ISO date>.
Nothing in this repository has been changed.

## What this project looks like today
## What migrating gives you
## Open questions and the answers given
## The plan
   <the 15 steps from migration.md, each made concrete for this repository,
    or marked "not applicable" with the reason>
## Irreversible steps and what to back up first
## What will break, and when you will notice
## After the migration
## How to run this
```

Requirements for the plan body:

- **Concrete, not generic.** Name this project's files, packages and versions. A plan that could
  apply to any repository has not done the work.
- **Every step marked applicable or not**, with a reason. A skipped step with no reason is
  indistinguishable from an overlooked one.
- **Flag the four merge-don't-overwrite files** — `pyproject.toml`, `README.md`, `LICENSE`,
  `CHANGELOG.md` — and the backup that must precede them:
  ```bash
  for f in pyproject.toml README.md LICENSE CHANGELOG.md; do
      [ -f "$f" ] && cp "$f" "$f.old"
  done
  ```
- **Say what will break.** Flat → `src/` breaks imports in tests. Adopting ruff reformats
  everything. Dropping a Python version breaks downstream users. Hardcoded `__version__` disappears
  in favour of git tags.
- **Carry the traps** the checklist and consumer notes name:
  - Version comes from git tags via hatch-vcs. Never edit the version in `pyproject.toml`.
  - `merge-gate.yml` requires a `ready-to-merge` label. Without it every PR carries a permanently
    failing check.
  - `doit pre_commit_install` must be run — and re-run after any later config change, because the
    config declares four hook types including `commit-msg`.
  - `manage.py repo` applies the GitHub-side configuration a migrated project does not get
    automatically; `doit publish_setup` handles PyPI trusted publishing. Both are separate steps
    after the migration commit.
  - Record the template commit as the sync point, or `template-sync` has no baseline afterwards.
- **`rsync` excludes `.git/`, `src/` and `tests/`.** Windows has no `rsync` — say so if the owner is
  on Windows.

**Stop here.** Do not change a single file until the owner has read the plan and told you to
proceed. The plan is the deliverable; migrating without it is the failure mode this skill exists to
prevent.

### Step 7: Report

Tell the user the plan file path, the template commit it was planned against, the count of steps
that apply, the open questions still outstanding, and the single biggest risk you found. Then stop.

### Step 8: Execute, only if asked

If and only if the owner approves:

1. Confirm a clean tree and a branch — never migrate on `main`.
2. Take the backups from the plan.
3. Copy the template in, then run `python tools/pyproject_template/manage.py` → **[2] Configure
   project**, which rewrites placeholders and renames `src/package_name` to the real package. This
   is the one mechanical step that is properly automated; use it rather than hand-editing.
4. Work the judgement steps one at a time, stopping after each for the owner to look.
5. `uv sync --all-extras --dev`, `doit pre_commit_install`, `doit check`.
6. Follow the plan's "After the migration" section for `manage.py repo` and `doit publish_setup`.

**Never edit a test to make it pass.** A test that breaks during migration is telling you an import
moved or a dependency did not survive the merge. Fix the cause.

## Notes

- Planning is read-only. If you find yourself editing a file before Step 8, stop.
- The plan file is the owner's. Do not commit it unless they ask — and do not delete it either.
- A migration that has to be argued for is a migration that should not happen yet. If the inventory
  says this project has good CI, a working release process and no packaging problems, say so in the
  plan rather than making the case for change.
- After migrating, the `template-sync` skill is the one for keeping up to date.
