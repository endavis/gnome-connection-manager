---
name: mutation-triage
description: Use when `doit mutate` (mutmut) reports a surviving mutant, or `doit coverage` marks a line or branch Missing, and you need to decide whether it is an equivalent mutant, a missing assertion, an untested branch, or a real bug — then turn genuine gaps into behavior tests and prove each named mutant is killed.
---

# Mutation Triage

Turn surviving mutants and uncovered lines into behavior tests, or a documented reason they need
none.

The scope — a dotted module path, a file under `src/`, or specific mutant names already known to
survive — comes from the user's request or the task at hand. Empty means every survivor from the
latest run.

`doit mutate` runs mutation testing informationally: surviving mutants do not fail it, locally or in
the weekly workflow (`.github/workflows/mutation.yml`). That silence is the trap — a survivor is a
question nothing forces anyone to answer. The quick, wrong answers are a test that asserts on the
mutated expression just to kill it, and a survivor declared equivalent with no argument for why; both
report success while proving nothing. This skill replaces the quick answer with the slow one.

Before Step 1, read the "## Mutation Testing" section in `docs/development/ci-cd-testing.md`. It is
the policy this skill applies; where the two disagree, the policy wins and this skill is out of date.

## Instructions

### Step 1: Scope

mutmut generates mutants for every file under `source_paths` in `[tool.mutmut]` (`pyproject.toml`) on
every run — nothing scopes that part. What scopes is which of those generated mutants get *tested*:
`uv run mutmut run --help` shows its only positional argument is `MUTANT_NAMES`, and mutmut matches
each one against every mutant's dotted name with `fnmatch`, not only as an exact string.

1. Every mutant name starts with the dotted module it came from: `x_<function>__mutmut_<n>` for a
   top-level function, `xǁ<Class>ǁ<method>__mutmut_<n>` for a method. Turn the scope into a pattern —
   `<package>.<module>.*` for a whole module, or an exact name for one mutant already known to survive
   — and run `uv run mutmut run "<pattern>"`. Always quote it: an unquoted `*` is expanded by the
   shell before mutmut ever sees it.
2. `mutmut results` afterward reports every mutant the pattern excluded as `not checked`. That is
   expected — mutmut generated them, this run just never tested them — not a failure to investigate.
3. Run `doit mutate` instead when the scope is empty: it wraps `mutmut run` then `mutmut results` with
   no pattern, testing everything (prefer it over calling `mutmut` directly; see the tool table in
   `AGENTS.md`).

### Step 2: Inspect

For each survivor in scope, run `uv run mutmut show <MUTANT_NAME>`. It prints the mutant's status and
a unified diff of the line or lines it changed against the original. Read the diff before judging
anything — the name alone does not say what changed.

### Step 3: Classify

Decide, for each survivor, which of these it is:

- **Equivalent.** No input distinguishes the mutant from the original. **An equivalent verdict must
  say why no input tells the two apart — never record it without one.** "It's probably fine" is not a
  reason.
- **Missing assertion.** A test already executes the mutated line, but nothing checks the value it
  produces.
- **Untested branch.** No test executes the mutated line at all.
- **Real bug.** An input distinguishes the mutant from the original, but the *original's* behavior at
  that point is itself wrong.

Before writing anything for a missing-assertion or untested-branch survivor, confirm the current,
unmutated behavior is the intended one: check the docstring, neighboring tests, or the issue driving
the change. **If the distinguishing behavior is itself wrong, stop: do not write a test that asserts
the current output is correct, report the bug, and wait.** A test that pins bad behavior as correct is
the mistake AGENTS.md forbids for a failing test, aimed at a new one instead of an old one.

### Step 4: Write behavior tests

For every missing-assertion or untested-branch survivor that Step 3 did not stop on, write a test that
exercises the real input the classification named. **Never write a test whose assertion is keyed to
the mutated literal, operator, or constant itself — assert on the function's observable output or
effect for a real input, and let the mutation fail incidentally.** A test that reads "the value must
not equal the mutated constant" tests the mutation, not the behavior, and breaks again the next time
someone touches an unrelated literal on that line.

Several survivors in the same function often collapse to one root cause and one missing test — group
them before writing anything, rather than writing one redundant test per mutant name.

If the test lives in a file that is not already in `pytest_add_cli_args_test_selection` under
`[tool.mutmut]` in `pyproject.toml`, add it there. Otherwise mutmut never runs it inside `mutants/`,
`tests/test_mutmut_config.py` fails, and `doit check` fails with it. Adding a test to a file already in
that list needs no change there. A new file's imports are bound only for the repository's own code,
not for third-party or standard-library packages: it may import from the paths in `source_paths` and
from `tests/`, never from `tools/`, because those are the only repo-local directories mutmut copies
into `mutants/`.

See the "### Which Tests Run" section in `docs/development/ci-cd-testing.md` for what mutmut copies.

### Step 5: Prove the kill

Re-run exactly what you targeted: the same pattern from Step 1, one exact mutant name, or several
quoted the same way — `uv run mutmut run "<name-or-pattern>"`, adding more quoted arguments to check
several targets in one run. Read the "Mutant results" section it prints at the end: one emoji per
mutant matched, killed as 🎉 and survived as 🙁 (mutmut's own `emoji_by_status` in its source has the
rest, for a re-run that lands on neither). **A classification is not finished until you re-run what it
targeted and every one shows killed — paste the before and after status.** For the status as a word
instead of an emoji, run `uv run mutmut results --all true` — the `--all` flag needs the literal value
`true`, not just its presence. A test that looks right but does not flip its mutant from survived to
killed has proven nothing, and the diff from Step 2 is the fastest way to see why.

### Step 6: Uncovered lines

`doit coverage`'s term-missing report lists a `Missing` column per file (`show_missing = true` under
`[tool.coverage.report]` in `pyproject.toml`): a plain line number or range for a statement never
executed, and an arrow marker (`A->B`, or `A->exit`) for a branch from line A that was never taken to
line B, or never returned at all (`branch = true` under `[tool.coverage.run]`). Put every line it
marks `Missing`, in a file the task touches, through Step 3's same four-way judgment — dead or
defensive code is the coverage analog of an equivalent mutant, and needs the same stated reason, not
silence. A genuine gap goes through Steps 4 and 5 like any other; a covered line does not by itself
guarantee a mutant there dies, so re-running is still how you know a new test reaches it.

## Notes

- `mutants/` is mutmut's cache and is git-ignored; leave it between runs so re-triage stays cheap, and
  delete it only when you want a fully clean regeneration.
- Triage the survivors and uncovered lines that belong to the code the current task already touches.
  One you notice elsewhere is a separate task, not scope creep to fold in here.
- Once every survivor and uncovered line in scope is classified, and every test you added is proven
  against what it targeted and passes `doit check`, hand off to the `implement-issue` run in
  progress, or commit and open a PR per `.github/CONTRIBUTING.md`.
