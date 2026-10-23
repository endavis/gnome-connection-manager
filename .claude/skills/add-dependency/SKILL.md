---
name: add-dependency
description: Use when a task needs a third-party Python package that is not a dependency yet, when the user asks to add or install a package or library, or when `uv add` is blocked by the dangerous-command hook. Rules out the standard library and existing dependencies, places the package in runtime dependencies or the dev or security extra, vets its license, maintenance and typing, hands the user the exact `uv add` command to run, then settles typing and runs `doit licenses`, `doit audit` and `doit check`.
---

# Add Dependency

Add a third-party package to this project: justified, placed, vetted, handed to the user to install,
then typed and checked.

The package, and what it is for, come from the user's request or from the task that needs it. If
neither says, ask the user what the task needs before doing anything else.

You cannot run `uv add`. The dangerous-command hook blocks it for every agent, in every form, and
that is deliberate: a new dependency is the user's decision. This skill does everything around that
one step — it prepares the decision, hands the user the exact command, and finishes the work once
they have run it.

Before Step 1, read `.github/CONTRIBUTING.md` and locate the "## Dependencies" section. It is the
policy this skill applies; where the two disagree, the policy wins and this skill is out of date.

## Instructions

### Step 1: Justify

Name the need in one sentence: what the code has to do, and which file needs it. "Parse TOML" is a
need. "Add tomli" is not.

Then look for something that already covers it:

- **The standard library**, on every Python version `requires-python` in `pyproject.toml` allows. A
  module that arrived after the oldest supported version does not count.
- **An existing dependency.** Read `[project] dependencies` and both extras under
  `[project.optional-dependencies]` in `pyproject.toml`.

**If the standard library or an existing dependency covers the need, stop here and use it.** Tell the
user what you used and why no new package was needed.

A package that is installed only because something else depends on it is not an existing dependency.
If the code imports it, it needs its own entry, and it goes through this skill.

### Step 2: Place it

| Table | Holds |
| :--- | :--- |
| `[project] dependencies` | What code under `src/` imports at runtime. It ships to every user of the package. |
| `[project.optional-dependencies] dev` | Tests, linting, type checking, docs, `doit` tasks — and type stubs, even for a runtime package. |
| `[project.optional-dependencies] security` | The tools behind `doit audit`, `doit security`, `doit licenses` and `doit sbom`. |

**Runtime only if the installed package imports it.** Anything that only tests or tooling use goes in
an extra. This project has no `[dependency-groups]` table: place a package with `--optional <extra>`,
never with `--dev`. A new extra is an architectural decision — propose it, do not create it.

### Step 3: Vet it

Look the package up on PyPI:

```bash
curl -sSf https://pypi.org/pypi/<package>/json | uv run python -c '
import json, sys
d = json.load(sys.stdin)
i = d["info"]
print("version:", i["version"])
print("released:", max((u["upload_time_iso_8601"] for u in d["urls"]), default="?")[:10])
print("license:", i.get("license_expression") or i.get("license") or "none declared")
print("requires_python:", i.get("requires_python"))
print("typed classifier:", "Typing :: Typed" in (i.get("classifiers") or []))
print("requires_dist:", i.get("requires_dist"))
print("project_urls:", i.get("project_urls"))
'
```

Then settle each of these. Write down what you find; Step 4 reports all of it.

- **License.** It must be compatible with this project's license (`license` in `pyproject.toml`). A
  missing license, or a copyleft one such as GPL or AGPL on a runtime dependency, is a finding to
  report, not one to settle yourself.
- **Python versions.** `requires_python` must allow every version this project supports; the
  classifiers in `pyproject.toml` list them.
- **Maintenance.** The release date above and, for a package hosted on GitHub, whether its repository
  is archived and when it last changed:
  ```bash
  gh api repos/<owner>/<repo> --jq '{archived, pushed_at}'
  ```
  An archived repository, or years without a release, is a finding.
- **What it pulls in.** `requires_dist` lists the packages that arrive with it. They are dependencies
  too.
- **Typing.** mypy runs without a global `ignore_missing_imports`, so importing a package that ships
  no type information fails with `[import-untyped]`. Decide which case applies:
  1. It ships inline types, marked by a `py.typed` file. The `Typing :: Typed` classifier is only a
     hint, and its absence proves nothing; Step 5 checks the installed package.
  2. A stub package exists. Most are named `types-<package>`:
     ```bash
     curl -s -o /dev/null -w "%{http_code}\n" https://pypi.org/pypi/types-<package>/json
     ```
     `200` means it exists and `404` that it does not. Some projects publish `<package>-stubs`
     instead, so check that name too. A stub is a dependency of its own: it goes in the `dev` extra
     and into the Step 4 command.
  3. Neither. If the installed package has no `py.typed` either, it needs a
     `[[tool.mypy.overrides]]` entry, which Step 5 adds.

### Step 4: Ask

Put everything to the user in one message:

- the need, and why nothing from Step 1 covers it
- the table from Step 2, and why
- what Step 3 found: license, supported Python versions, latest release and its date, maintenance,
  what it pulls in, and how it will be typed
- the exact command, with the version you vetted as its `>=` lower bound, in the form for its table,
  plus the stub if Step 3 found one

```text
uv add "<package>>=<version>"
uv add --optional dev "<package>>=<version>"
uv add --optional security "<package>>=<version>"
uv add --optional dev "types-<package>>=<version>"
```

Give the user only the lines that apply.

**Stop here.** Do not run `uv add` yourself, and do not write the dependency into `pyproject.toml` by
hand. Wait until the user has run the command and told you it succeeded.

If the user declines, the package is not added. Do not install it another way — not `pip install`,
not `uv pip install`, not by copying its source into the project. Tell the user what the task can and
cannot do without it.

### Step 5: Finish

Once the user says the command ran:

1. **Confirm what landed.**
   ```bash
   git diff -- pyproject.toml uv.lock
   ```
   The entry must sit in the table from Step 2 with its `>=` bound, and `uv.lock` must have changed.
   If either is wrong, stop and tell the user rather than correcting it by hand.
2. **Settle typing.** Unless Step 3 found a stub, check the installed package for a `py.typed`
   marker. `<module>` is the import name, which is not always the package name: `pyyaml` imports
   as `yaml`.
   ```bash
   uv run python -c 'import importlib.util, pathlib, sys; s = importlib.util.find_spec(sys.argv[1]); print((pathlib.Path(s.origin).parent / "py.typed").is_file())' <module>
   ```
   `True` means it is typed. `False` means it needs an override, beside the existing ones in
   `pyproject.toml`:
   ```toml
   [[tool.mypy.overrides]]
   module = "<module>.*"
   ignore_missing_imports = true
   ```
   Do this before any check runs.
3. **Check licenses and known vulnerabilities.**
   ```bash
   doit licenses
   doit audit
   ```
   Both need the `security` extra. Without it they print an install hint and exit 0, a pass that
   checked nothing. If you see the hint, run `doit install_dev` and run them again. Read the
   `doit licenses` output for the new package and for everything `git diff uv.lock` shows arriving
   with it.
4. **Validate.**
   ```bash
   doit check
   ```
   Stop at the first failure and report it. Never edit a test to make it pass. If nothing imports
   the package yet, this run cannot prove the typing decision; run it again once the code that uses
   the package exists.

### Step 6: Record

The justification belongs in the PR description, not only in this conversation: the need, what Step 1
ruled out, the table the package went into, and what Step 3 found. A reviewer should not have to ask
why the project now depends on it.

When the task is done, return to the `implement-issue` run, or commit and open a PR per
`.github/CONTRIBUTING.md` — either way, make sure the PR body carries this record.

## Notes

- Add the dependency on the branch of the task that needs it, never on `main`, and in the same PR as
  the code that imports it. `pyproject.toml` and `uv.lock` change together; commit them together.
- Needing several packages: run Steps 1 to 3 for each, then ask about all of them in one Step 4
  message.
- Write scratch files to `tmp/agents/<agent>/` with the issue number in the name, and delete them
  when the task is done.
