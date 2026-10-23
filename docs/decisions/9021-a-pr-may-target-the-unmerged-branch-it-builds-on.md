---
title: "ADR-9021: A PR may target the unmerged branch it builds on"
description: A PR may target the unmerged branch it builds on, but it merges only into main
date: 2026-09-26
audience:
  - contributors
tags:
  - adr
  - workflow
---

# ADR-9021: A PR may target the unmerged branch it builds on

## Status
Accepted

## Decision
**A PR may target the unmerged branch it builds on, but it merges only into `main`.**

When issue B needs code from issue A's branch before A merges, B is branched from A and
`doit pr --base=<A's branch>` opens B's PR against A's branch, so its diff shows only B's changes.

1. **The up-to-date check follows the base.** With `--base`, `doit pr` requires the branch to be
   up to date with `origin/<base>`, so the PR contains the tip of the branch it builds on. Without
   `--base`, nothing changes: the PR targets `main` and the check uses `origin/main`.
2. **Merging stays `main`-only.** `doit pr_merge` refuses a PR whose base is not the default
   branch (#853). Once A merges, B is rebased onto `main` and retargeted, then merged like any
   other PR.
3. **Plain branches, not GitHub's native stacked PRs.** No gh-stack dependency, and
   `doit pr_merge` keeps using `gh pr merge`.

## Rationale
Work that needs an unmerged branch had two options: wait for that branch to merge, or open the PR
against `main`, where its diff also shows everything from the branch below. Targeting the lower
branch keeps each review to one layer.

Merging stays `main`-only because GitHub merges a PR into its base branch. Merging B into A's
branch would put a `(merges PR #XX, addresses #YY)` commit on a feature branch, and
`--auto-close` would close issues whose work never reached `main`.

**Why not native stacked PRs.** #847 trialled them and did not adopt them. Each layer still waits
for a full CI run after it is rebased, the same wait as a manual rebase, so the saving is one
command. `gh pr merge` is refused for stacked PRs, which would have meant moving `doit pr_merge`
to GitHub's asynchronous merge API, on an extension in public preview. `--base` keeps the part
worth having, a diff that shows one layer, without any of that.

## Consequences
- **CI does not run on a PR while it targets another branch.** `ci.yml` and `merge-gate.yml`
  filter on `branches: [main]`. After the PR is retargeted to `main`, CI starts on the next push:
  `ci.yml` runs on `opened`, `synchronize` and `reopened`, and a retarget is none of those. The
  documented steps retarget before pushing.
- **Each layer is rebased once, with `--onto`.** A was squash-merged, so B still carries A's
  original commits, and a plain `git rebase origin/main` can conflict on them.
  `git rebase --onto origin/main <A's last commit>` replays only B's commits. A's last commit
  stays available from `gh pr view <A's PR> --json headRefOid` after its branch is deleted.
- **A base missing from `origin` is not caught early.** The up-to-date check warns and is
  skipped when `git fetch origin <base>` fails, as it already did for `main`, and
  `gh pr create` is left to reject the base.
- Choosing the base automatically from an issue's "blocked by" relationship is left as a
  follow-up.

## Related Issues
- Issue #855: add `--base` to `doit pr` for work that builds on an unmerged branch
- Issue #853: `doit pr_merge` refuses a PR whose base isn't the default branch
- Issue #847: GitHub native stacked PRs, trialled and not adopted

## Related Documentation
- [CONTRIBUTING.md](../../.github/CONTRIBUTING.md) — Development Workflow, step 4, has the steps
- [Doit Tasks Reference](../development/doit-tasks-reference.md) — the `--base` option of `doit pr`
- [ADR-9008](9008-pr-based-development-workflow.md) — the PR-based workflow this extends
