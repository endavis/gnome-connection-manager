---
name: python-version-bump
description: Use when a task needs to change which Python versions this project supports -- adding a newest version to .github/python-versions.json plus a classifier, or raising the floor (requires-python) and dropping the oldest version. Reads the seven places the supported range is declared, adds a newest version non-destructively, or asks the user before raising the floor and then changes all seven settings together, regenerates uv.lock, applies the UP rewrites doit lint reports, and runs doit check.
---

# Python Version Bump

Move the supported Python range in either direction: add a newest version, or raise the floor and
drop the oldest.

The direction and the version come from the user's request or from the task that needs it. If
neither says, ask the user which direction, and which version, before doing anything else.

Read `docs/development/ci-cd-testing.md` and find "## Python Version Support Policy" before Step 1.
It is the policy this skill applies; where the two disagree, the policy wins and this skill is out
of date.

## Instructions

### Step 1: Read the seven settings

The supported range is declared in seven places, and nothing but `tests/test_python_versions_agree.py`
checks that they agree:

1. `requires-python` under `[project]` in `pyproject.toml` — the floor.
2. `target-version` under `[tool.ruff]` in `pyproject.toml` — the floor, spelled `py3<minor>` with no
   dot, e.g. `py313`.
3. `python_version` under `[tool.mypy]` in `pyproject.toml` — the floor.
4. `pythonVersion` under `[tool.pyright]` in `pyproject.toml` — the floor.
5. `.python-version` at the repository root — the floor. `uv run` reads this to pick the
   interpreter, and rebuilds `.venv` on the next run after it changes — with the base dependencies
   only (Step 5).
6. `oldest` and `newest` in `.github/python-versions.json` — the floor and the ceiling.
7. The `Programming Language :: Python :: 3.X` classifiers under `[project] classifiers` in
   `pyproject.toml` — every version from `oldest` through `newest`, ascending, no gaps, nothing
   outside the range.

`.github/actions/python-versions/action.yml` reads only `.github/python-versions.json` and exposes
`oldest`/`newest` as outputs; `.github/workflows/ci.yml` builds its whole matrix from those two
outputs. Neither hardcodes a version, so changing the json is enough — no workflow file changes
needed.

None of the seven is cross-checked against prose elsewhere that also states a version. Steps 2 and
5 both search for it the same way, restricted to tracked files, which already excludes a
gitignored worktree, with the lockfile and changelog excluded by name since neither is meant to be
hand-edited, and both would only add noise:

```bash
git grep -n -F -e '3.<n>' -e 'py3<n>' -- ':!uv.lock' ':!CHANGELOG.md'
```

`<n>` is the minor version you're searching for — the current `newest` in Step 2, the old floor in
Step 5. Sort every hit into one of two piles:

- **A statement of this project's supported floor or range.** Update it.
- **Everything else** — a historical record (an ADR under `docs/decisions/`), a fact about when a
  Python feature arrived, or sample output and test data. Leave it.

Run `uv run pytest tests/test_python_versions_agree.py` now. If it already fails, the seven are out
of sync before you touch anything; stop and tell the user rather than folding a pre-existing
disagreement into your change.

### Step 2: Add a newest version

Purely additive — nothing to ask permission for.

1. Run the Step 1 grep for the current `newest`, and update every hit that states the range;
   leave the rest, per Step 1's sort.
2. Set `newest` in `.github/python-versions.json` to the new version.
3. Add its classifier to `pyproject.toml`, in ascending order beside the existing ones.
4. Run `uv run pytest tests/test_python_versions_agree.py`. It fails until the classifier list
   covers exactly `oldest` through the new `newest`.
5. Run `doit check`.
6. Commit `.github/python-versions.json`, the classifier, and the prose fixes together.

No `uv lock` needed here — `requires-python` does not move, and a classifier addition alone leaves
`uv lock --check` at exit 0. Every PR already runs the bookend versions (`oldest` and the new
`newest`); the `full-matrix` label on a PR additionally runs the middle versions once, per the "CI
Matrix Strategy" this skill's policy section describes. That is the user's call, not a step here.

### Step 3: Raise the floor — ask first

**Ask before changing a single file.** Raising the floor drops users still on the old version —
that decision belongs to the user, not to you. Wait for an explicit yes before Step 4.

Ask two more things in that same message, not a follow-up one. First, whether the commit should
carry a `BREAKING CHANGE:` footer: neither AGENTS.md's Breaking Changes Policy nor this skill's
policy section names dropping a Python version, so it is not a foregone conclusion, and the footer
changes what `doit release`'s automatic bump produces next: while `[tool.commitizen]` has
`major_version_zero = true`, it's a MINOR bump, and `doit release` refuses to release 1.0 or
later — MAJOR only once that setting is false (#881). Do not hand-edit `CHANGELOG.md` either way;
`doit release`
generates it from commit history.

Second, whether they want the latest release that still supports the old floor tagged, per the
policy section's "Deprecation Process" (e.g. `v1.2.3-py310-final`). That names a release that
already exists, not one this commit creates — creating and pushing the tag is the user's to do,
not this skill's.

### Step 4: Change all seven settings in one commit

**Change all seven settings in one commit.** A partial bump is worse than no bump: it leaves the
tools checking against different Pythons until someone notices.

Update every setting Step 1 listed to the new floor. For the classifiers, drop the ones below the
new floor — the list must still run exactly `oldest` through `newest` afterward, in ascending order.

### Step 5: Sync derived state

Five things follow from raising the floor, and none of them are optional:

1. **Run `uv lock`.** `uv.lock` carries its own copy of `requires-python` plus resolution markers
   derived from it; the pre-commit hook "Validate uv.lock matches pyproject.toml" runs
   `uv lock --check` and fails the commit until this has run.
2. **Run `uv sync --all-extras --dev`.** The new `.python-version` makes the next `uv run` rebuild
   `.venv` for the new interpreter with the base dependencies only: the `dev` and `security` extras
   are gone, and `doit` with them. This is the command `doit install_dev` runs; call it directly,
   because the rebuild removed `doit`.
3. **Run `doit lint`**, read what it reports, then **run `doit format`** to apply it. Ruff's `UP`
   rules key off `target-version`, so a higher floor can make more of them fire; `doit lint` only
   reports, `doit format` is what fixes.
4. **Search for `sys.version_info` branches and version-gated imports** (for example a
   `try`/`except ImportError` backport shim) that exist only for the version you just dropped, and
   remove the dead branch.
5. **Run the Step 1 grep for the old floor**, and update every hit that states the floor or range;
   leave the rest, per Step 1's sort.

### Step 6: Validate and commit

1. Run `uv run pytest tests/test_python_versions_agree.py` again.
2. Run `doit check`.
3. Commit everything from Steps 4 and 5 together — the seven settings, the `uv.lock` update, the
   `UP` rewrites, and any dead branches or doc fixes. This is one logical change, not a sequence of
   partial ones.

## Notes

- Steps 2 and 3–6 are independent. A single invocation does one direction; doing both means running
  this skill twice, ordinarily newest-version first since it is the simpler, non-breaking half.
- Write scratch files to `tmp/agents/<agent>/` with the issue number in the name, and delete them
  when the task is done.
- When the task is done, return to the `implement-issue` run, or commit and open a PR per
  `.github/CONTRIBUTING.md`.
