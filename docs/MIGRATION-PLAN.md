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

Nothing outside this branch changes until Phase 7, which renames the default branch on
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

- [ ] Install the suite (`bootstrap.py --sync`, or copy from the local checkout)
- [ ] Review `.config/pyproject_template/settings.toml`
- [ ] Run `python tools/pyproject_template/manage.py check`
- [ ] Save the drift report; it drives Phases 3, 5, 6 and 8

**Deliverable:** a file-by-file list of Modified / Missing / Extra.

## Phase 2 — Python floor and version drift

- [ ] `requires-python = ">=3.12"`
- [ ] ruff `target-version = "py312"`, mypy `python_version = "3.12"`
- [ ] Update classifiers: drop 3.8–3.11, add 3.13
- [ ] Resolve the version drift: `pyproject.toml` 1.2.0 vs `Makefile` 1.2.2
- [ ] Tests still 534

Note that raising the floor may *surface* new ruff findings (pyupgrade rules apply more
aggressively at py312). Baseline the count before judging it.

## Phase 3 — Task runner: just to doit

- [ ] Copy `dodo.py` and `tools/doit/`
- [ ] Port every `justfile` recipe: `run fmt lint typecheck test test-cov check install build clean translate setup`
- [ ] **`setup` must keep `uv venv --system-site-packages`** — everything depends on it
- [ ] `translate` must keep calling `tools/build_mo.py`
- [ ] Decide: delete `justfile` or keep it as a thin shim
- [ ] `doit check` and `doit test` both work

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

`mutation.yml` is worth having: the mutation run in
[#113 follow-up](https://github.com/endavis/gnome-connection-manager/issues/115) found
`relay.py` at a 33% score.

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

- Keep `justfile` alongside `doit`, or delete it?
- Does the .deb packaging (`Makefile`, `postinst`) stay outside the template's build flow?
- Adopt `hatch-vcs` later, and what is the correct current version — 1.2.0 or 1.2.2?
