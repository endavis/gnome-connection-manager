# Migration to pyproject-template

Working checklist for [#115](https://github.com/endavis/gnome-connection-manager/issues/115).
Transient: delete this file when the migration lands.

Template checkout: `../pyproject-template` (branch `main`).
Template docs: `../pyproject-template/docs/template/`.

## Rewind

Everything happens on `chore/migrate-to-pyproject-template`, branched from `65714ba`.

```bash
git checkout master && git branch -D chore/migrate-to-pyproject-template
```

Nothing outside this branch changes until Phase 8, which renames the default branch on
GitHub. That is the first irreversible step and has its own checkpoint.

## Baseline at 65714ba

Every phase re-checks these. A regression is a stop signal, not a footnote.

| Measure | Value |
|---|---|
| Tests | 534 passed, 0 skipped |
| ruff `src/` | 4 findings |
| ruff `tests/` | 3 findings |
| mypy | 138 errors in 2 files (137 in `app.py`) |
| Coverage | 45% |

## Decisions

| Decision | Choice | Consequence |
|---|---|---|
| Scope | Full adoption, minus release workflows | `configure.py` rewrites `AGENTS.md`/`README`/docs; doc tests need repair |
| Python floor | `>=3.8` becomes `>=3.12` | Matches `.python-version` and the venv; drops an untested claim |
| Default branch | `master` becomes `main` | Template workflows apply unmodified; breaks existing clones |
| Release flow | Skipped | No `release.yml`/`testpypi.yml`; version stays static |
| Version | 1.2.2 | The `Makefile` was right; `pyproject.toml` was stale |
| Task runner | doit only | `justfile` is deleted once its recipes are ported |

## Things that must survive

Check these after every phase that copies template files.

- **`LICENSE` — GPL-3.0-or-later.** The template ships MIT with a placeholder copyright.
  The migration checklist says to copy `LICENSE`. Doing so would relicense the project.
- **`.venv` with `include-system-site-packages = true`.** `gi` comes from the system apt
  package at `/usr/lib/python3/dist-packages/gi`, not from pip. Any flow that recreates
  the venv without `--system-site-packages` breaks every GTK import.
- **`data/`, `lang/`, `gnome-connection-manager.desktop`, `postinst`, `Makefile`.** The
  .deb packaging path. The template knows nothing about these.
- **`tools/build_mo.py`.** Compiles the translation catalogs; `just translate` calls it.

---

## Phase 0 — Preparation

- [x] Record the baseline above
- [x] Create the branch from `origin/master`
- [x] File the tracking issue
- [ ] Confirm `../pyproject-template` is current (`git -C ../pyproject-template pull`)

## Phase 1 — Install the sync suite

Installs `tools/pyproject_template/` and `.config/pyproject_template/settings.toml`, which
is what makes later template updates a supported operation rather than a manual diff.

- [x] Install the suite (`python ../pyproject-template/bootstrap.py --sync`)
- [x] Review `.config/pyproject_template/settings.toml`
- [x] Run `python tools/pyproject_template/manage.py check`
- [x] Save the drift report; it drives Phases 3, 5, 6 and 7

### Result: 328 files differ

**320 are new in the template** — workflows, `tools/doit/`, `tools/hooks/`,
`tools/statusline/`, docs and the template's own test suite. These are additive and get
adopted phase by phase.

**8 exist in both and differ. This is the danger list — never copy these wholesale:**

| File | Why it differs | Action |
|---|---|---|
| `LICENSE` | Template MIT vs GCM **GPL-3.0-or-later** | **Never adopt** |
| `tests/conftest.py` | Carries the Xvfb bootstrap from #113/#114 | **Never adopt**; merge by hand |
| `src/package_name/__init__.py` | Template's placeholder package | **Never adopt** — would create a bogus `src/package_name/` |
| `AGENTS.md` | GCM's is project-specific; 7 tests assert on it | Merge in Phase 9 |
| `README.md` | Doc-link tests assert on it | Merge in Phase 9 |
| `pyproject.toml` | Deps, metadata, tool config | Merge, never overwrite (Phases 2, 4) |
| `.gitignore` | Both have real entries | Merge |
| `.python-version` | Template `3.12`, GCM `3.12.3` | Trivial; either works |

### Settings detected

`bootstrap.py` read `author_name = "Renzo Bertuzzi"` from `[project].authors`. That is
correct attribution for the original author, but `configure.py` writes these values into
generated files in Phase 9. Decide then whether template-generated prose should name the
author or the maintainer.

### Side effect already handled

Adding `tools/pyproject_template/` broke `test_agents_md_describes_every_module`, which
requires AGENTS.md to name every module under `src/` and `tools/`. Vendored template
directories are now excluded from that discovery — verified both ways: a new GCM module
still fails the test, a new vendored file does not.

## Phase 2 — Python floor and version drift

- [x] `requires-python = ">=3.12"`
- [x] ruff `target-version = "py312"`, mypy `python_version = "3.12"`
- [x] Update classifiers: drop 3.8–3.11, add 3.13
- [x] Set the version to **1.2.2** everywhere
- [x] `uv lock` refreshed — 518 lines lighter, all the 3.8–3.11 resolution branches gone
- [x] Tests 535 (534 + the new version check)

### The version drift was worse than recorded

Three values across four files, not two: `pyproject.toml` 1.2.0, `__init__.py` 1.2.0,
`app.py` **1.2.1**, `Makefile` 1.2.2. `app_version` feeds the About dialog and the update
check, so the application reported a different release from the `.deb` the user installed.

All four now say 1.2.2, and `test_every_declared_version_agrees` reads all four and fails
naming the offender, so it cannot drift again silently.

### Measured against baseline

| Measure | Baseline | After | Note |
|---|---|---|---|
| Tests | 534 | 535 | +1, the version check |
| ruff `src/` | 4 | 7 | +3 newly surfaced at py312 |
| ruff `tests/` | 3 | 3 | unchanged |
| mypy | 138 in 2 files | **132 in 1 file** | improved; `main.py` now clean |

### Deferred: 3 ruff findings newly surfaced at py312

These block Phase 7 (CI runs ruff) and need a decision, but they are unrelated to the
migration and are deliberately not bundled into a version bump.

- `app.py:664` `PTH115 os.readlink()` → `Path.readlink()`. Mechanical.
- `app.py:1436,1457` `B905 zip() without strict=`. **Password encryption.** In `encrypt`,
  `_pkcs7_pad` guarantees 16-byte blocks so the lengths always match and `strict=True` is
  safe. In `decrypt` the ciphertext is externally supplied and can be short, so the final
  block can genuinely mismatch — today `zip` truncates and `_pkcs7_unpad` usually fails,
  but it could return garbage instead of `""`. Both sit inside `except Exception: return ""`,
  so the caller sees the same thing either way. `strict=True` is the better behaviour
  (fails closed), but it is a crypto change and deserves its own review.

## Phase 3 — Task runner: just to doit

- [x] Copy `dodo.py`, `tools/__init__.py` and `tools/doit/` (17 vendored modules)
- [x] Port every `justfile` recipe
- [x] **`setup` keeps `uv venv --system-site-packages`**
- [x] `translate` still falls back to `tools/build_mo.py`
- [x] **`justfile` deleted**
- [x] `doit test` works; `doit check` does **not** yet — see below

### Recipe mapping

`launch` (not `run`: doit reserves that as a command name), `format`, `lint`,
`type_check`, `test`, `coverage`, `check`, `install`, `build`, `cleanup`, `translate`,
`setup`. GCM-specific tasks live in `tools/doit/gcm.py`; the other 16 modules are vendored
and replaced wholesale on a sync.

### Findings

- **`uv sync` preserves an existing venv's `--system-site-packages`** (verified). So the
  footgun is limited to fresh environments, which is exactly CI. `doit setup` is the
  documented entry point; `doit install_dev` would build a venv that cannot `import gi`.
- **`pytest -n auto` is safe and faster** — 535 in 23s against 32s serial. But
  `pytest_configure` runs in every xdist worker, so each was starting its own Xvfb, and
  picking a free display is a check-then-bind race: the worker that loses falls back to
  the real desktop. Workers now inherit the controller's display. Verified: one server,
  no orphans, `gw0` reports `DISPLAY=:90`.
- **Vendored code fails GCM's ruff config** — 47 findings, all because the template does
  not select `PTH` (use-pathlib). Per-file-ignores added for the vendored directories,
  which are linted upstream under their own rules. Back to the baseline of 10.
- **`tools/build_mo.py` had 3 real findings** that `just lint` never saw, because it only
  covered `src/ tests/`. Fixed; the compiled `.mo` is byte-identical afterwards.
- **`pythonpath = ["."]`** added so tests can import `tools.doit.*`, matching the template.
- **`msgfmt` is not installed here**, so `build_mo.py` has been doing all the work. Add
  `gettext` to the Phase 7 apt list or the fallback-versus-reference test skips forever.

### Resolved: the tree is now ruff-formatted

Decision (a) — reformat once, drop the prohibition. `format_check` passes.

The format settings already matched the template exactly (line-length 100, py312, double
quotes), so no vendored file changed and no sync drift was created. `line-ending = "lf"`
added for full parity.

Churn was far smaller than feared: 19 files, 252 insertions, 189 deletions. `app.py` took
116 lines out of 4,600. **Verified semantically neutral by comparing the AST of every
reformatted file before and after — zero differences.**

`AGENTS.md` loses the "never run a formatter" rule and gains the opposite: layout is
ruff's, run `doit format`.

### But the prohibition had a real reason, and it bit

`save_session_transcript` carried a deliberately long single line with a comment saying
why. The formatter wrapped it, and
`test_transcript.py::test_the_refusal_says_what_to_do_about_it` broke: its regex matched
only `_("...")` on one line, so it silently started reading a *different* message.

`tests/test_i18n.py` already had the robust form, `_\(\s*"..."\s*\)`. The transcript test
now matches it. Mutation tested: a message that drops the preference name still fails.

Worth keeping in mind for later phases — any test that regexes source is exposed to the
formatter.

### Still blocked: `doit check` fails on `lint`

The 10 pre-existing findings (7 `src/`, 3 `tests/`), including the three py312 ones from
Phase 2. They have to be resolved before CI in Phase 7.

## Phase 4 — Dependencies

- [x] Merge the template's `dev` and `security` extras into `pyproject.toml`
- [x] Skip `click`; **keep `rich`** — the template has it as a runtime dep, but GCM needs
      it only because `tools/doit` imports it, so it is a dev tool here
- [x] Keep `pyaes` and the note about system GTK packages
- [x] `uv lock` and `uv sync --all-extras --dev`
- [x] Tests still pass

### The feared bump was a non-event

| Tool | Was | Now | Result |
|---|---|---|---|
| pytest | 8.x | **9.1.1** | 535 passed, 1 skipped |
| ruff | 0.8.0 | **0.16.5** | format clean, lint exactly 10 |
| mypy | 1.8.0 | **2.3.1** | exactly 132 in 1 file |

Not one finding moved across three major version jumps.

### Four new blockers for `doit check`

`check` depends on `format_check lint type_check deadcode security audit spell_check test`.
Now that the tools are installed, all of them run:

1. **`deadcode` (vulture)** — fails with "Please pass at least one file or directory". The
   task relies on a `[tool.vulture]` section GCM does not have. Config, not findings.
2. **`spell_check` (codespell)** — 4 findings, all false: `comandos` and `historial` are
   Spanish, and GCM's UI strings and i18n tests are bilingual by design. Needs an ignore
   list.
3. **`security` (bandit)** — 123 findings. Read the summary carefully: the task prints
   *confidence*, so "High: 111" is not severity. By severity it is **117 LOW, 5 MEDIUM,
   1 HIGH**. The LOW mass is `B603`/`B607` subprocess use, inherent to a program whose job
   is spawning `ssh` and `telnet`. The single HIGH is `app.py:4559`,
   `os.system(f"/usr/bin/xdg-open {f.name}")` in the donate handler — the argument is a
   tempfile name, not user input, and the fix is a `subprocess.run` list.
4. **`audit` (pip-audit)** — fails on `ubuntu-pro-client`, `unattended-upgrades` and
   `types-pytz`. It is auditing the **system** site-packages, which it can see precisely
   because the venv is built with `--system-site-packages`. A direct consequence of the
   GTK constraint, and it needs `--skip-editable` plus an ignore or a different strategy.

### Incidental bug found

`app.py:4557` calls `os.filestart`, which does not exist in Python — the Windows function
is `os.startfile`. Unreachable on GCM's Linux-only target, but it is a typo waiting for
anyone who tries a port. Not fixed here; it is unrelated to the migration.

## Phase 5 — make `doit check` pass

**Done. `doit check` runs format_check, lint, type_check, deadcode, security, audit,
spell_check and test, and all eight pass.**

| Gate | Before | After |
|---|---|---|
| ruff lint | 10 | **0** |
| mypy `src/` | 138 | **0** |
| mypy `src/ tools/ tests/` | 186 | **0** |
| bandit | 123 | **0** |
| vulture | n/a (unconfigured) | **0** |
| codespell | n/a (unconfigured) | **0** |
| pip-audit | failed | **0 vulnerabilities** |
| tests | 534 | **538** |

### mypy: relaxed by code, not excluded

`app.py` is a 4,600-line GTK monolith where attributes are attached at runtime and glade
supplies half the callers. Five codes — `attr-defined`, `arg-type`, `has-type`,
`name-defined`, `union-attr` — account for 118 of its 132 errors. Those are disabled *for
that module only*; every other module stays fully checked, and the remaining 15 errors
were fixed rather than suppressed. Narrow this as `app.py` is broken up.

`tests/` gets a similar override for the codes that follow from fake-based testing. This
needed `tests/__init__.py`: a per-module pattern must be fully qualified, and `test_*` is
rejected outright, so without the package marker the override silently matched nothing.

### Real problems found by the new gates

- **Weak encryption key generation.** `initialise_encyption_key()` built the key that
  encrypts saved host passwords from `random.random()` — a Mersenne Twister seeded from
  the clock. Now `secrets.token_hex(16)`. Existing key files are untouched; only newly
  generated keys change.
- **`exec()` on user input.** Saving preferences did
  `value = f'"{obj.get_text()}"'` then `exec(f"{obj.field}={value}")`, so **any preference
  containing a double quote raised SyntaxError and silently failed to save** — reproduced
  before fixing. Addresses now resolve to a real attribute via `resolve_preference()`.
- **A vulnerable dependency**: pygments 2.19.2, PYSEC-2026-2987. Upgraded to 2.21.0.
- `eval()` and `os.system()` are now **entirely absent** from the codebase.
- Six genuine English typos, and three unused-parameter warnings that were toolkit-
  mandated signature positions rather than dead code.

### `audit` had to be overridden

`pip-audit` walks the *environment*, and GCM's venv uses `--system-site-packages` so it
can reach PyGObject — so it also walked `cloud-init`, `python-apt` and `ubuntu-pro-client`
and failed on distributions that are not on PyPI. `tools/doit/gcm.py` exports the lockfile
and audits that instead. `dodo.py` installs it by name after discovery, because two
modules defining `task_audit` would otherwise be resolved by whatever order `rglob`
returned them in.

### Suppressions, and why

Every skip is documented in `pyproject.toml`. bandit's `B603`/`B607`/`B404` are a program
whose purpose is spawning `ssh`, `telnet` and `$SHELL`; `B105`/`B107` are empty `pwd=""`
defaults. codespell's ignore list is Spanish words that look like English typos — the UI
and its fixtures are bilingual.

## Phase 6 — pre-commit

- [x] Copy `.pre-commit-config.yaml`, `tools/hooks/`, `tools/generate_doc_toc.py`
- [x] `doit pre_commit_install`
- [x] All four hook types present: `commit-msg`, `pre-commit`, `post-merge`, `post-checkout`
- [x] `pre-commit run --all-files` clean across 23 hooks

### Branch naming convention changed

The `check-branch-name` hook requires `<type>/<issue>-<description>` and allows only
`main`/`develop` as bare names. GCM's convention was `fix/<description>` with no issue
number, so **this branch was renamed** from `chore/migrate-to-pyproject-template` to
`chore/115-migrate-to-pyproject-template`. It had not been pushed, so the rename was free.

Going forward: `feat/`, not `feature/`, and every branch carries its issue number. That
fits the issue-first workflow — the number is now in the branch, the commit and the PR.

`check-commit-issue-ref` additionally requires that if a message cites an issue, the
branch's issue is among them.

### The whitespace hook broke i18n, and would have done it silently

`trailing-whitespace` stripped a space from inside a *translatable* glade string:

```
-<property name="tooltip-text" translatable="yes">Nivel de compresión:
+<property name="tooltip-text" translatable="yes">Nivel de compresión:
```

That trailing space is part of the msgid, so the widget detached from every translation of
it. Two i18n tests caught it. `data/ui/*.glade` and `lang/*.po` are now excluded from that
hook — they are translation sources, where whitespace is data.

`end-of-file-fixer` also trimmed blank lines from `postinst` and `data/scripts/ssh.expect`;
both harmless and kept.

### Adaptations

- The mypy hook ran `mypy src/ tools/ tests/ bootstrap.py`; GCM has no `bootstrap.py`.
- `protect-dynamic-version` is inert here — it guards a `dynamic =` field GCM does not
  have. It becomes relevant if hatch-vcs is ever adopted.
- `test_agents_md_describes_every_module` needed `tools/generate_doc_toc.py` treating as
  vendored, like the directories added in Phase 1.

## Phase 7 — CI

**GCM has CI for the first time.** Ten workflows, adapted where the GTK stack forced it.

- [x] `ci.yml`, `codeql.yml`, `pr-checks.yml`, `merge-gate.yml`, `mutation.yml`,
      `daily-check.yml`, dependabot workflows and config
- [x] **Skipped** `release.yml`, `testpypi.yml` (no PyPI publishing)
- [x] **Dropped** `ci-full-matrix.yml` (no matrix to run) and
      `breaking-change-detection.yml` (`griffe` API diffing for a library; GCM is an
      application, and it still held the unconfigured `package_name` placeholder)
- [x] actionlint passes on every workflow

### The constraint that shaped everything

PyGObject is an apt package built for the distribution's own interpreter, living in
`/usr/lib/python3/dist-packages`. It is not on PyPI. So:

- **Linux only.** There is no GTK 3 / VTE stack to test against on windows or macos.
- **No `actions/setup-python`.** It installs a separate interpreter that cannot see apt's
  dist-packages, so `import gi` fails whatever else is configured. The venv is built from
  `/usr/bin/python3` with `--system-site-packages`.
- **`ubuntu-24.04` pinned**, not `ubuntu-latest`, so the system interpreter stays the 3.12
  that `.python-version` names and that apt's PyGObject is built for.

Verified locally by building the CI environment exactly as the workflow does: `gi` resolved
to `/usr/lib/python3/dist-packages`, Gtk 3.24, Vte 0.76.

`daily-check.yml` and `mutation.yml` needed the same treatment.

### The skip guard, and what it found

CI fails the run if **anything** skips. Twelve tests gate themselves on a display, so
without Xvfb they vanish and the run still reports success — a green tick that tested
nothing is worse than a red one.

Installing `gettext` locally to satisfy that rule immediately exposed a real bug: **every
one of the 8 `.po` catalogs had 3 duplicate msgid definitions**, which `msgfmt` rejects as
fatal. `doit translate` was therefore broken on any machine with gettext installed. It
only appeared to work here because `build_mo.py` silently accepts duplicates, last one
winning.

The duplicates were untranslated stubs appended under "glade strings that had no catalog
entry" — for three strings that *did* already have entries. Removed, keeping the canonical
entries that carry `#:` source references. One case in `en_US.po` had two real
translations differing as `"blank: default compression"` versus `"blank: default"`; the
canonical one was kept and the difference is recorded here.

**539 passed, 0 skipped.**

### Also corrected

`test_the_fallback_compiler_agrees_with_msgfmt` asserted byte equality, which is too
strong: msgfmt writes a lookup hash table that `build_mo.py` does not, making its output
~800 bytes smaller for identical messages. It now compares catalog contents, minus the
metadata header, where msgfmt records a `POT-Creation-Date` that the fallback does not.

## Phase 8 — Branch rename

**Done. The default branch is `main`; `origin/master` is deleted.**

- [x] `git branch -m master main`, pushed, default branch set on GitHub
- [x] `origin/master` deleted; the working branch retargeted to `origin/main`
- [x] Swept for stale `master` references — the only two hits are correct as they stand:
      a Spanish comment about a "master password", and the vendored hook whose
      `PROTECTED_BRANCHES` deliberately covers both names

### Blast radius, checked before doing it

| | |
|---|---|
| Forks of this repo | 1 — `Kianda/gnome-connection-manager`, still defaulting to `master` |
| This repo is itself a fork of | `kuthulux/gnome-connection-manager` |
| Open PRs to retarget | none |
| Stars / watchers | 1 / 0 |

GitHub redirects `master` to `main` for web URLs and for fetching the default branch, so
existing clones keep working. What breaks is a hardcoded `master` ref — a fork opening a
PR against it, or a deep link to `blob/master/...`. Kianda is the contributor behind #2;
they were deliberately not notified.

### Noted, not done

The repository has **no branch protection and no rulesets**. Nothing was left dangling by
the rename, but nothing guards `main` either. Now that CI exists, requiring `ci-complete`
before merge is worth doing — the template's `manage.py` can configure it.

### Memory updated

The stored note describing this project's workflow said "branch from `origin/master` as
`fix/...` or `feature/...`", which is wrong twice over now. It records `origin/main`,
`<type>/<issue>-<slug>`, `feat/` over `feature/`, and the hooks that enforce all of it.

## Phase 9 — configure.py and the docs rewrite

Highest-breakage phase. Do it last, when everything else is green.

- [ ] Copy the remaining template files: `mkdocs.yml`, `CHANGELOG.md`, `.editorconfig`,
      `.envrc`, `.github/` non-workflow files, `.claude/`, `.codex/`, `.copilot/`, `.agents/`
- [ ] Run `configure.py` via `manage.py configure`
- [ ] **Verify `LICENSE` is still GPL-3.0** — check immediately, before anything else
- [ ] Repair the doc tests it breaks:
      `test_agents_md_references_paths_that_exist`,
      `test_agents_md_names_symbols_that_exist`,
      `test_agents_md_carries_no_line_number_references`,
      `test_agents_md_does_not_claim_tests_are_manual`,
      `test_agents_md_lists_the_locales_that_exist`,
      `test_agents_md_describes_every_module`,
      `test_documented_application_accelerators_are_real`,
      `test_doc_is_linked_from_the_readme`,
      `test_internal_links_resolve_to_a_heading`
- [ ] Merge the template's `AGENTS.md` with GCM's, keeping the project-specific content the
      tests assert on
- [ ] `mkdocs build` succeeds

## Phase 10 — Land it

- [ ] Full suite green, 0 skipped
- [ ] ruff and mypy at or better than the recorded baseline
- [ ] CI green on the PR — the first time this repo has ever had CI
- [ ] Delete this file
- [ ] PR referencing #115

---

## Open questions

- Does the .deb packaging (`Makefile`, `postinst`) stay outside the template's build flow?
  It carries `PKG_VERSION`, so it is a second place the version lives.
- Adopt `hatch-vcs` later? If so the first tag should be `v1.2.2`, and that would remove
  the version duplication between `pyproject.toml` and the `Makefile`.
