---
title: "ADR-9026: Doc-scanning tests honor sync-exclude.toml and discover markdown via git"
description: The shipped doc-link and doc-path tests discover markdown via git ls-files instead of rglob, and skip a target excluded in sync-exclude.toml
date: 2026-10-26
audience:
  - contributors
tags:
  - adr
---

# ADR-9026: Doc-scanning tests honor sync-exclude.toml and discover markdown via git

## Status

Accepted

## Decision

**The three shipped doc-scanning tests — `tests/test_markdown_links.py`, `tests/test_documented_paths.py`
and `tests/test_instruction_pointers.py` — discover markdown through `git ls-files` rather than
`rglob()` minus a hardcoded skip set, and honor a downstream project's
`.config/pyproject_template/sync-exclude.toml` when judging a link or path target.**

1. **Discovery.** `tests/doc_scan.py`'s `committed_markdown_files(root)` runs
   `git ls-files -z --cached --others --exclude-standard -- '*.md'`: tracked files and
   untracked-but-not-ignored files are read; anything `.gitignore` excludes — including
   `worktrees/`, each a full copy of the repository (ADR-9022) — drops out without a name in a
   skip set. If `root` is not a git repository, or `git` is missing, the call raises rather than
   falling back to a filesystem walk — a silent fallback is the exact bug this replaces (a scan
   that reads nothing passing because it checked nothing). The three test files' own `SKIP_DIRS`
   constants and `rglob`-based `_markdown_files()` helpers are replaced by this call; the two that
   guarded against a `tmp`/`worktrees` component appearing by absolute-path heredity (#848, #854)
   are moot under it, since `git ls-files` only ever sees paths relative to the repository root it
   runs in.
2. **Exclusion.** Each test loads `.config/pyproject_template/sync-exclude.toml` (the same file
   `check_template_updates.py` reads for drift suppression) and skips a link or documented-path
   *target* that matches one of its patterns, via `fnmatch.fnmatch` against the target's
   upstream-relative posix path — the same matcher `compare_files` already uses. A target is
   skipped only when it is otherwise missing; an existing file is still checked for anchors and
   headings. Upstream (`endavis/pyproject-template` itself) carries no such file, so
   `load_sync_excludes` returns `[]` and every check here is exactly as strict as before this ADR.
3. **Duplicated reader, not a shared import.** `check_template_updates.load_sync_excludes()` lives
   in `tools/pyproject_template/`, which a downstream project deletes once it sheds the template
   suite (ADR-9017) — but the three test files, and `tests/doc_scan.py` itself, ship and run in
   every downstream project indefinitely. `tests/doc_scan.py` therefore duplicates the loader
   (`tomllib` plus the same `fnmatch` matching) rather than importing it, following the
   `tests/agent_roster.py` precedent of a small tests-only helper module that pytest does not
   collect as a test module. It cannot move into `tools/doit/` either: `bootstrap.py`'s one-shot
   installer fetches `tools/pyproject_template/` directly, without `tools/doit/` on the path, so a
   helper that lived there would not be reachable at the point `tests/doc_scan.py` needs it.
   `tests/template/test_check_template_updates.py` (template-owned, never shed) carries a parity
   test suite that runs both copies against the same fixtures and fails if they disagree.

## Rationale

Before this change, the three test files read with `rglob("*.md")` minus a hardcoded `SKIP_DIRS`.
That reads whatever is on disk, tracked or not: in this repository it already picks up
the README pytest writes into its cache directory, and downstream — per the issue this ADR implements — it picked up a
Terraform provider's README under a checked-out `.terraform/providers/` tree and paths from an
unrelated checked-out config repository, failing `test_markdown_anchors_resolve` and
`test_documented_paths_exist` on content the project never wrote. `git ls-files` reports exactly
what the project's own `.gitignore` and index already say is part of the project, which is the
same question these tests are trying to answer, so asking git directly removes an entire class of
false positives rather than trying to anticipate every tool that leaves markdown lying around a
checkout.

The exclusion half addresses a separate failure: a downstream project that adopts a template-owned
file verbatim (a 9xxx ADR, a shared skill such as `deprecate-api` or `template-sync`) inherits that
file's links to template-only pages the project did not adopt — `docs/template/*.md`,
`docs/development/tooling-roles.md`, `src/package_name/core.py`, `tests/test_core.py`. The only ways
to pass the tests without this ADR were editing the adopted file (undone by the next sync) or
adopting documentation the project deliberately excluded. `sync-exclude.toml` already exists for
exactly this shape of problem — "upstream files a project intentionally does not adopt" — so reusing
it here, rather than inventing a second suppression file, keeps one place to declare that decision
tests and drift-checking the project did not already distinguish.

## Consequences

- **Not a breaking change upstream.** `endavis/pyproject-template` itself has no
  `sync-exclude.toml`, so `load_sync_excludes` returns `[]` and every check in this repository is
  exactly as strict as it was. The discovery change only *removes* false positives: git-ignored
  content that was never meant to be scanned.
- **The three tests now need git.** Run outside a git checkout (an unpacked sdist, for example),
  or without `git` on `PATH`, they fail rather than pass on an empty scan.
- **A downstream project's local-authoring workflow is preserved.** An untracked markdown file that
  is not git-ignored is still discovered and checked — `git ls-files --others --exclude-standard`
  includes it — so a doc written before its first `git add` still gets validated.
- **`SKIP_DIRS` is gone from all three files.** The hardcoded directory names it listed
  (`.git`, `.venv`, `tmp`, `worktrees`, `node_modules`, `__pycache__`, `.mypy_cache`, `site`) are
  now whatever each project's own `.gitignore` says, which is also more correct: a project that adds
  a new ignored directory is covered without anyone updating a second list.
- **ADR-9022 is amended** (its "every repository-wide walker must skip `worktrees/`" consequence):
  these two tests now get that skip from `.gitignore`-driven `git ls-files` rather than from a
  hardcoded directory name, alongside `tests/template/test_secret_env_policy.py`, which is unchanged
  by this ADR and still names `worktrees/` directly.
- **`tests/doc_scan.py` and `tests/test_doc_scan.py` are new downstream-owned files.** Per the
  "New files you will see in this sync" table in the AI Sync Checklist, both are adopted alongside
  the three tests that depend on `tests/doc_scan.py` — adopting one without the other leaves an
  import that cannot resolve.
- **A project without a git working tree cannot run these three tests.** `committed_markdown_files`
  raises rather than silently scanning nothing; this is already true in effect today, since
  `doit check`/CI always run inside a checkout.

## Related Issues

- Issue #1012: let the doc link and path tests honor sync-exclude.toml and skip untracked files

## Related Documentation

- [Template Management — Excluding upstream files from drift checks](../template/manage.md#excluding-upstream-files-from-drift-checks) —
  `sync-exclude.toml`'s existing purpose, now also read by these three tests
- [Consumer Notes](../template/consumer-notes.md) — the behaviour note for downstream projects
- [AI Agent Sync Checklist](../template/ai-sync-checklist.md) — `tests/doc_scan.py` in the
  new-files table
- [ADR-9017](9017-template-tooling-and-its-tests-are-template-owned.md) — why `tests/doc_scan.py`
  duplicates rather than imports `load_sync_excludes`
- [ADR-9022](9022-worktrees-live-in-worktrees-each-with-its-own-environment.md) — the
  walker-skip consequence this ADR amends
