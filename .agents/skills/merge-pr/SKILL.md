---
name: merge-pr
description: Use when the user says "N is green", "merge N", "merge PR N" or "merge it" about a pull request in this repository. Checks the PR is open, mergeable, clean and labelled ready-to-merge, confirms every CI check passes, judges whether each linked issue is fully addressed, merges with doit pr_merge, closes the fully addressed issues and comments on the rest. Never adds the ready-to-merge label and never bypasses a block.
---

# Merge PR

Merge a finished pull request and close the issues it fully addresses. Invoking this skill is
consent to merge the named PR and to close the issues it fully addresses. It is not consent to
add `ready-to-merge` or to bypass a block.

## Instructions

The argument is a PR number `N`. Without one, take it from the user's message or from
`gh pr list --head "$(git branch --show-current)" --json number`; if it is still unclear, ask.

### Step 1: Check the preconditions

```bash
gh pr view N --json state,mergeable,mergeStateStatus,labels,body,baseRefName
```

Stop, without merging, and say which one failed, if any of these is not true:

- `state` is `OPEN`
- `mergeable` is `MERGEABLE`
- `mergeStateStatus` is `CLEAN`
- `labels` includes `ready-to-merge`

If the label is missing, tell the user they must add it: it is the human merge gate and this
skill never adds it.

### Step 2: Check CI

```bash
gh pr checks N
```

Every job must pass or be skipped. Stop and list the failing jobs otherwise. A pending job is
not passing: stop and tell the user to wait for it.

### Step 3: Judge the linked issues

For each `Addresses #X` line in the PR body:

```bash
gh issue view X
gh pr diff N
```

Compare the issue's Success Criteria with the diff. Record the issue as fully addressed, or as
not fully addressed with what is missing. If the body has no `Addresses #` line, tell the user
there is nothing to close before going on to Step 4.

### Step 4: Merge

Run from the main checkout. If the current directory is inside `worktrees/`, stop and say so:
`doit pr_merge` removes the PR branch's worktree and must not run from inside it.

- Every linked issue fully addressed, or none linked:

  ```bash
  uv run doit pr_merge --pr=N --auto-close
  ```

- Otherwise merge without closing, then close only the addressed issues and comment on the rest:

  ```bash
  uv run doit pr_merge --pr=N
  gh issue close X --comment "Addressed in PR #N"
  gh issue comment Y --body "PR #N merged but did not fully address this issue. Still missing: ..."
  ```

## Ask-first / stop

Stop and report, never work around it, when a precondition fails, a check is failing or pending,
`doit pr_merge` refuses or errors, or the merge is blocked for any reason. Ask the user how to
proceed.

## Never

- Never apply the `ready-to-merge` label or edit the PR's labels.
- Never use `--admin`, `--force` or `--no-verify`, or any other flag that overrides a block.
- Never merge with a failing or pending check.
- Never close an issue that is not fully addressed.

## Output format

Report:

- the merge commit
- the issues closed
- the issues left open, and why
- the current branch, from `git branch --show-current`
