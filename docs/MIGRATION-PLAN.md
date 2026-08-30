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

- [ ] Merge the template's dev extras into `pyproject.toml`
- [ ] **Do not** take the template's runtime deps (`click`, `rich`) — GCM needs neither
- [ ] Keep `pyaes` and the commented note about system GTK packages
- [ ] `uv lock`
- [ ] Tests still 534

**Risk:** the template pins `pytest>=9.1.1`; GCM is on 8.x. A major pytest bump against 534
tests is the most likely source of surprise breakage in the whole migration. Do this phase
alone and run the suite before anything else changes.

## Phase 5 — mypy, before pre-commit can work

138 pre-existing errors, 137 of them in `app.py`. The template's pre-commit runs
`mypy src/ tools/ tests/`, so until this is resolved **every commit fails**.

- [ ] Decide the approach:
  - **(a)** Per-module override relaxing `app.py`, fix the rest — pragmatic, keeps the gate
    for new code
  - **(b)** Fix all 137 — large, and `app.py` is the file most in flux
  - **(c)** Leave mypy out of pre-commit — cheapest, loses the check
- [ ] Implement, and confirm the chosen scope is clean
- [ ] Record the new baseline

Recommendation: **(a)**. The dominant codes are `attr-defined` (36), `arg-type` (31) and
`name-defined` (17) — largely GTK dynamic-attribute noise in one legacy monolith, not a
signal worth blocking every commit on.

## Phase 6 — pre-commit

- [ ] Copy `.pre-commit-config.yaml` and `tools/hooks/`
- [ ] `doit pre_commit_install`
- [ ] Verify `commit-msg`, `pre-commit`, `post-merge`, `post-checkout` in `.git/hooks/`
- [ ] Confirm existing commit style passes conventional-commit enforcement

**Changes how we work here.** The dangerous-command hook scans heredoc bodies, and long
commit messages must be written to `tmp/agents/<agent-type>/` and passed with
`git commit -F <file>` rather than piped via heredoc. See the template's
`docs/template/consumer-notes.md`.

## Phase 7 — CI (the substantial one)

GCM's tests need a GTK stack and a display. The template's CI provides neither.

- [ ] Adopt `ci.yml`, `codeql.yml`, `pr-checks.yml`, `merge-gate.yml`, `mutation.yml`,
      dependabot config
- [ ] **Skip** `release.yml`, `testpypi.yml`
- [ ] Restrict the matrix to `ubuntu-latest` (drop windows and macos)
- [ ] Add an apt step: `python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-vte-2.91 xvfb`
- [ ] Create the venv with `--system-site-packages` before `uv sync`
- [ ] **Prove the GTK tests actually run in CI** — assert 534 passed / 0 skipped, because
      a missing display makes 12 tests skip and still report green
- [ ] Reconcile `pytest -n auto` (xdist) with the real-GTK tests, which spawn subprocesses
      and an Xvfb of their own

`mutation.yml` is worth having: the mutation run recorded in
[#115](https://github.com/endavis/gnome-connection-manager/issues/115) scored `relay.py`
at 33% -- its resize, stdin-lifecycle and EINTR paths have no behavioural tests.

## Phase 8 — Branch rename

**First irreversible step. Stop here and confirm before running.**

- [ ] `git branch -m master main` locally
- [ ] `git push -u origin main`
- [ ] `gh repo edit --default-branch main`
- [ ] Retarget open PRs
- [ ] Delete `origin/master`
- [ ] Grep the repo for `master` references in docs, workflows and `AGENTS.md`

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
