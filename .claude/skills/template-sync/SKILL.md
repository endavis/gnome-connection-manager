---
name: template-sync
description: Use when the user wants to upgrade this project to the latest pyproject-template, sync with upstream template changes, or adopt template improvements. Refreshes the management suite, runs the drift check, triages the diff into a plan posted on a tracking issue for the repo admin to review, applies what is approved, validates with `doit check`, and records the new sync point.
---

# Template Sync

Upgrade this project to the latest `pyproject-template`.

Drives the sync tooling end to end: refreshes the management suite, runs the drift check, triages
the diff into a plan the repo admin reviews, applies what they approve, validates, and records the
new sync point. It does not reimplement any of that machinery — `bootstrap.py --sync`,
`manage.py check`, `manage.py sync` and `doit check` do the work. This skill supplies the ordering,
the questions, and the review gate.

## When to use

Use this skill when the user wants to pull upstream template improvements into this project.

Expected request shape:

- "upgrade this project to the latest template"
- "sync with pyproject-template"
- "sync to v2.2.0"

The user may supply an optional template ref (tag, branch, or commit SHA) to sync *to*. Default is
`main`. An older ref takes a large backlog one step at a time.

The full reference is `docs/template/ai-sync-checklist.md`; read it if any step here is ambiguous.

## Instructions

### Step 1: Preflight

1. **Check this skill against the upstream copy.** Fetch the template's latest `SKILL.md`:
   ```bash
   curl -sSL https://raw.githubusercontent.com/endavis/pyproject-template/main/.agents/skills/template-sync/SKILL.md \
     -o tmp/agents/<agent>/template-sync-upstream-SKILL.md
   diff tmp/agents/<agent>/template-sync-upstream-SKILL.md .agents/skills/template-sync/SKILL.md
   ```
   If they differ, you are running a stale copy of these very instructions — follow the fetched
   version for the rest of this sync instead. The local copy is then adopted through the normal
   Step 5 triage, not by overwriting it here: it is downstream-owned, and `manage.py check` (Step 4)
   only warns about it and never writes it.

2. **Refuse to run in the template itself.**
   ```bash
   git remote get-url origin
   ```
   If it points at `endavis/pyproject-template`, stop and say so. This project *is* the upstream;
   there is nothing to sync from.

3. **Confirm a clean starting point.**
   ```bash
   git status --short && git branch --show-current
   ```
   Working tree must be clean. If it is not, stop and ask — a sync produces a large diff and
   unrelated pending edits will be impossible to separate afterwards.

4. **Confirm the current state passes** with `doit check`. A failure that predates the sync must be
   understood before you add a hundred changed files on top of it. Stop and report if it fails.

5. **Read `docs/template/consumer-notes.md`** — the breaking changes and one-off actions that
   arrive through this path. Note which apply before adopting anything. If the project has no copy
   of that file yet, read it from the template you download in Step 3.

### Step 2: Open the tracking issue and branch

Per `AGENTS.md` (Issue -> Branch -> Commit -> PR):

First resolve the target ref (default `main`; a tag, branch or SHA also works) to a full commit SHA,
so the issue, the check and the recorded sync point all name the same commit even if upstream
`main` moves during the sync. The short SHA is its first 7 characters:

```bash
gh api repos/endavis/pyproject-template/commits/<ref> --jq .sha
```

```bash
git checkout main && git pull
doit issue --type=chore --title="chore: synchronize with pyproject-template <short-sha>" --body-file=<file>
git checkout -b chore/<issue#>-sync-pyproject-template
```

The issue body at this point states intent only — what is being synced, the ref and its full SHA.
The plan comes in Step 6, once you know what the drift actually is. Record the issue number and the
SHA; every later step refers to them.

Branch before Step 3: `bootstrap.py --sync` overwrites tracked files under
`tools/pyproject_template/`, so it is already a change to `main` if you skip this.

### Step 3: Refresh the management suite first

```bash
curl -sSL https://raw.githubusercontent.com/endavis/pyproject-template/main/bootstrap.py | python3 - --sync
```

**This is not optional and its position is not negotiable.** The drift checker compares your files
against the template it was fetched with; a checker older than the template you are about to adopt
misreports what changed. Refresh the tooling, then check.

First run in a project also creates `.config/pyproject_template/settings.toml`. Review its detected
values and correct them before continuing.

### Step 4: Check for drift

```bash
python tools/pyproject_template/manage.py --yes check --template-version <sha>
```

Always pass the full SHA resolved in Step 2, whether or not the user named a ref.

The template is left extracted for diffing. **Locate it by glob, not by a fixed name** — the
directory is named for the resolved commit:

```bash
TEMPLATE_DIR=$(ls -d tmp/extracted/pyproject-template-*/ | head -1)
diff <file> "$TEMPLATE_DIR/<file>"
```

If the project keeps a `.config/pyproject_template/sync-exclude.toml`, run
`manage.py --yes check --show-excluded` once to see what it is suppressing. An exclusion added for
a good reason two syncs ago may now be hiding a change you want.

### Step 5: Triage the diff — and ask about what you cannot settle

Sort every reported file into adopt / skip / merge by hand.

| Category | Meaning | Default |
| :--- | :--- | :--- |
| **Modified** | Exists in both, content differs | Review the diff; merge selectively |
| **Missing** | New upstream file | Adopt if it applies to this project |
| **Extra** | Project-specific | Keep as-is; never delete |

Order the work so configuration lands before the code that depends on it: `pyproject.toml` tool
sections and dev-dependencies, then `.github/workflows/`, then `tools/doit/` and `tools/hooks/`,
then `AGENTS.md` and the AI agent configs, then `.pre-commit-config.yaml` and the `.github/`
templates.

Traps to check for explicitly:

- **Template-owned tests are not yours.** The files in `TEMPLATE_OWNED_TEST_FILES`
  (`tools/pyproject_template/utils.py`) cover machinery that does not survive configuration
  (ADR-9017). They are excluded from the drift report already; do not adopt them by hand. Everything
  else under `tests/` is yours, including the `tools/doit/` and `tools/hooks/` tests.
- **A downstream-owned test can still name structure you lack.** Read the constants at the top of
  any test before adopting it. `tests/test_agents_md_allocation.py` names template paths in
  `RELOCATION_TARGETS`; adopt it into a project missing those and you have installed a test that
  cannot pass.
- **Adopt AI agent config only for the agents this project wires.** Derive the roster from disk the
  way `tests/agent_roster.py` does — a self-action skill directory per agent — rather than assuming
  all four. Adopting `.claude/`, `.agents/`, `.github/skills/` and `.copilot/` wholesale installs
  commands for agents nobody here uses, and roster-aware tests that then assert about them.
- **Roster-aware tests need a roster.** `tests/test_cross_agent_contract.py` and friends derive
  their scope from `tests/agent_roster.py` — adopt that helper alongside them.
- **Placeholders.** Any `__PACKAGE_NAME__` in copied content must become this project's package
  name.
- **Intentional divergence stays.** If an ADR documents a deliberate difference from the template,
  respect it. If you find yourself re-applying the same upstream change every sync, propose adding
  it to `.config/pyproject_template/sync-exclude.toml` instead.

**Ask rather than guess.** A wrong adoption is silent: it passes `doit check` and surfaces weeks
later as a threshold nobody chose or a workflow nobody wanted. Batch every open question into one
round and put it to the user before drafting the plan — do not ask them one at a time, and do not
resolve them by picking the template's answer because it is the template's.

Ask about at least these, whenever the diff touches them:

- **Thresholds the project may differ on deliberately** — coverage `fail_under`, complexity limits,
  the Python version matrix. The template's value is not automatically right for this project.
- **New dev dependencies.** `AGENTS.md` puts new dependencies under Ask First, and new doit tasks
  usually bring some.
- **Files that diverge with no ADR explaining why.** Either the divergence is deliberate and
  undocumented, or it is drift. Only the admin knows which.
- **Anything you would be reverting for the second time.** That is a `sync-exclude.toml` candidate,
  and the exclusion is the admin's call.
- **A backlog too large to review honestly.** Offer to sync to an intermediate ref instead.
- **Suppressed excludes that now look wrong** — surfaced by `--show-excluded` in Step 4.

If the diff raises nothing from that list, say so explicitly rather than staying silent; "no open
questions" is a finding the admin should see.

### Step 6: Post the plan to the issue and wait for review

Write the triage up as a plan and post it as a comment on the issue from Step 2:

```bash
gh issue comment <issue#> --body-file=tmp/agents/<agent>/sync-plan-<issue#>.md
```

The comment opens with the header, so the plan is findable and a second run can detect it:

```
## Sync Plan for #<issue#>: <template ref> (<short-sha>)
```

Include, in this order:

- **Sync point** — the current template commit (from `.config/pyproject_template/settings.toml`, or
  "none recorded"), the target commit, and the compare URL
  `https://github.com/endavis/pyproject-template/compare/<old>...<new>`.
- **Adopt** — every file, grouped by area, one line each on what the change does and why it applies
  here.
- **Skip** — every file and the reason. This list is the one that hides mistakes; make it explicit,
  not a count.
- **Merge by hand** — files with local customizations that need line-level judgment, and what the
  conflict is.
- **Consumer notes that apply** — from `docs/template/consumer-notes.md`, with the one-off action
  each requires.
- **Open questions** — the Step 5 questions and the user's answers, or the questions still
  outstanding.
- **Risk** — what could break, and what `doit check` will and will not catch.

**Stop here.** Do not apply a single file until the repo admin has approved the plan on the issue.
The plan comment is the artifact they review; applying first and asking after defeats the point of
writing it.

### Step 7: Apply the approved plan

Apply the adopt set, in the Step 5 order. Apply what the plan says and nothing else — a change you
discover mid-apply and think is a good idea goes back to Step 6 as an amendment, not into the diff.
After each group, note what you changed and why; you will need it for the commit message.

If `.pre-commit-config.yaml` changed, re-run the installer and verify:

```bash
doit pre_commit_install
ls .git/hooks/
```

The config declares four hook types. An install that predates `commit-msg` leaves it absent and
conventional-commit enforcement silently does not run.

### Step 8: Validate

```bash
doit check
```

Stop at the first failure and report it. **Never edit a test to make it pass.** A test that broke
during a sync is telling you something real: either the adopted change does not fit this project,
or the project relies on behavior the template changed deliberately. Explain which, and let the
user decide.

Then re-run the drift check to confirm the diff shrank to the set the plan said would be skipped.

### Step 9: Mark as synced

```bash
python tools/pyproject_template/manage.py --yes sync
```

This records the reviewed commit in `.config/pyproject_template/settings.toml` and cleans up
`tmp/extracted/`. Future checks compare from this point.

The commit recorded is the one you actually reviewed — with `--template-version` that is the pinned
ref, not the tip of `main` (#805). Confirm the SHA it reports matches the SHA resolved in Step 2
before moving on.

### Step 10: Summarize, then finalize

Report against the plan, not from memory: what was adopted, what was skipped, where you deviated
and why, the `doit check` result, and the old and new template SHAs.

Then return to the `implement-issue` run, or commit and open a PR per `.github/CONTRIBUTING.md`.
The commit subject and the PR title both use the Step 2 short SHA, matching the issue title (for
example `doit pr --title="chore: synchronize with pyproject-template <short-sha>" --body-file=<file>`).
The commit message should list the upstream changes taken:

```
chore: synchronize with pyproject-template <short-sha>

Syncs the following template improvements:
- endavis/pyproject-template#<PR> (description)
```

## Notes

- One sync per PR. Do not mix a template sync with feature work — the diff is already large enough
  to hide things in.
- Small and frequent beats large and rare. A project two hundred commits behind produces a triage
  no one reviews honestly.
- `sync-exclude.toml` is hand-managed and never rewritten by automation, unlike `settings.toml`.
  That separation is deliberate; keep it.
- Do not delete files merely because the template lacks them. **Extra** is the expected category for
  everything this project actually does.
- Write scratch files to `tmp/agents/<agent>/` with the issue number in the name, and delete them
  when the task is done.
