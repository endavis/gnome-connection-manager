---
name: deprecate-api
description: Use when a public name in this package's API needs to be retired without breaking
  callers first — the user asks to deprecate, rename, replace or remove a public function, class or
  constant, or work on an issue calls for warning callers off an old name before deleting it. Warns
  with `warnings.warn(..., DeprecationWarning, stacklevel=2)`, requires a `pytest.warns` test, and
  only removes the name in a later release, following the Breaking Changes Policy.
---

# Deprecate API

A public name should never disappear without warning, and a warning should never run forever. This
skill runs the two halves of that promise as separate phases, in order, normally releases apart.

The phase (`deprecate` or `remove`) and the name or names involved come from the user's request or
from the task that needs it. If neither says, ask the user which phase before doing anything else.

Before Step 1, read `AGENTS.md` and locate the "## Breaking Changes Policy" section. It says what
counts as breaking and what a breaking change must document; this skill makes that policy executable
for retiring one public name. Where the two disagree, the policy wins and this skill is out of date.

## Instructions

## Phase 1: Deprecate

### Step 1: Keep it working

Keep `<old_name>` exported — it stays in `__all__` in `src/package_name/__init__.py` (or wherever this
project declares its public API) — and route it to `<new_name>` so there is one implementation, not two
copies that can drift apart. Add `<new_name>` to the same import line and to `__all__`, alongside
`<old_name>`; both stay exported during Phase 1:

```python
def new_name(...):
    ...  # the real implementation, previously old_name's body


def old_name(...):
    warnings.warn("old_name is deprecated; use new_name", DeprecationWarning, stacklevel=2)
    return new_name(...)
```

Worked example, verified against this project's own `src/package_name/core.py`:

```python
import warnings


def greet_v2(name: str = "World") -> str:
    """Return a greeting message."""
    return f"Hello, {name}!"


def greet(name: str = "World") -> str:
    """Deprecated. Use greet_v2 instead."""
    warnings.warn("greet is deprecated; use greet_v2", DeprecationWarning, stacklevel=2)
    return greet_v2(name)
```

### Step 2: Warn at the caller, not at the shim

Check `requires-python` in `pyproject.toml`. `@warnings.deprecated` (PEP 702) is only usable once every
version it allows has it — measured on the interpreters this project ships: Python 3.12 has no
`warnings.deprecated`, Python 3.13 does. While a supported version still lacks it, warn by hand:

```python
warnings.warn("old_name is deprecated; use new_name", DeprecationWarning, stacklevel=2)
```

This gives the same runtime warning as `@warnings.deprecated("...")`; write it this way instead of that
decorator until every version `requires-python` allows has it. `stacklevel=2` is what makes the warning
point at `old_name`'s caller instead of at this line — measured with the `warn()` call written directly
inside the shim: `stacklevel=1` (the default) attributes to the shim's own line, `stacklevel=2`
attributes to whoever called it.

Do not reach for `@typing_extensions.deprecated` to get the decorator on a version that lacks
`warnings.deprecated`. A new dependency is Ask First — see the Dependencies section of
`.github/CONTRIBUTING.md` — and this need does not justify one: the manual form above already covers
every version this project supports.

### Step 3: Test both directions

Add a test that `<old_name>` still works, and a separate test that it warns. This project's
`[tool.pytest.ini_options]` sets `--strict-config --strict-markers` and no `filterwarnings`, so pytest
does not fail a test merely because the code under test raises `DeprecationWarning` — only a test that
asserts the warning with `pytest.warns` will ever catch one that goes silent:

```python
import pytest
from package_name import greet, greet_v2


def test_greet_still_works() -> None:
    assert greet("Python") == greet_v2("Python")


def test_greet_warns() -> None:
    with pytest.warns(DeprecationWarning, match="use greet_v2"):
        greet("Python")
```

**Confirm `test_greet_warns` fails once the `warnings.warn` line is removed, then put the line back.**
That failure is the only thing standing between a silent regression and a released library that no
longer warns anyone.

Add these tests to the module's existing test file when one exists — `greet`'s tests already live in
`tests/test_core.py`, which is already listed in `pytest_add_cli_args_test_selection` under
`[tool.mutmut]` in `pyproject.toml`. A new test file that imports the package must be added to that
same list, or `tests/test_mutmut_config.py::test_every_test_of_the_package_is_selected` fails and takes
`doit check` down with it — see the "### Which Tests Run" section of
`docs/development/ci-cd-testing.md`.

### Step 4: Document the replacement

Name `<new_name>` in `<old_name>`'s docstring (Google-style, per `.github/CONTRIBUTING.md`). If the
module is already included in `docs/reference/api.md`, mkdocstrings renders the updated docstring there
automatically — nothing else to edit. If `<old_name>` is named anywhere else in `docs/`, update that
mention too.

## Phase 2: Remove (a later release)

### Step 5: Delete it

**Never run this step until Phase 1's warning has already shipped in a release.** Confirm it with a
check that can fail — find the deprecating commit's SHA and run:

```bash
git tag --contains <sha>
```

This project's tags are release versions (`tag_format = "v$version"` in `[tool.commitizen]`), so it
must print at least one. It exits 0 either way, so read the output, not the exit code: nothing printed
means the warning has reached nobody yet, and deleting now breaks every caller with no notice, which is
the one thing this workflow exists to prevent. Stop and ask the user rather than guess.

Delete `<old_name>` and its `__all__` entry. Leave `<new_name>` as the one remaining implementation.

### Step 6: Follow the Breaking Changes Policy

Write a `BREAKING CHANGE:` footer in the commit message and a migration guide in the PR description,
following `AGENTS.md`'s Breaking Changes Policy section. That policy also lists updating
`CHANGELOG.md`; in this project that step is carried out by `doit release`, which writes the changelog
entry from commit history — not by hand-editing the file. The same is true of the version in
`pyproject.toml`: it comes from git tags, never a hand edit. The agent's own part of the policy is the
`BREAKING CHANGE:` footer above; `doit release`'s commitizen bump reads it to write the entry and
choose the version. Check `major_version_zero` in `[tool.commitizen]`: with `true`, the shipped
default, that footer bumps MINOR, which is right while the project is on 0.x, and `doit release`
refuses to release 1.0 or later until the setting is `false` (#881); with `false`, it bumps MAJOR.
The agent tells the user which applies. Do not edit `pyproject.toml` to change it.

When the task is done, return to the `implement-issue` run, or commit and open a PR per
`.github/CONTRIBUTING.md` — either way, make sure the PR body carries the migration guide.

## Notes

- Treat the two phases as separate PRs, normally separate releases. Nothing stops one session from
  drafting both, but Step 5 must refuse to run until Phase 1 has actually shipped.
- Deprecating several names for one release: run Steps 1 to 4 for each in the same PR if they share
  it. Keep every Phase 2 removal in its own PR regardless.
- Write scratch files to `tmp/agents/<agent>/` with the issue number in the name, and delete them when
  the task is done.
