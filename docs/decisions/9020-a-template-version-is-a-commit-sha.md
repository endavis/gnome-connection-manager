---
title: "ADR-9020: A template version is a commit SHA"
description: A template version is a commit SHA, not a release tag or a branch name
date: 2026-08-29
audience:
  - contributors
tags:
  - adr
  - template
---

# ADR-9020: A template version is a commit SHA

## Status
Accepted

## Decision
**A template version is a commit SHA.** Not a release tag, and not a branch name.

Both halves of the update path resolve to one:

| mechanism | accepts | resolves to |
| :--- | :--- | :--- |
| `bootstrap.py --sync` | `PYPROJECT_TEMPLATE_REF` — tag, branch or SHA; defaults to `main` | a commit SHA, fetched once for every file |
| `manage.py check --template-version` | a tag, a branch or a SHA; defaults to `main` | a commit SHA, one archive URL |

Consequences of that single definition:

1. **`main` is the default, stated rather than fallen into.** The template publishes no releases, so
   `releases/latest` 404s. The drift checker used to reach `main` only by *failing* that lookup
   first; now it names `main` as the default and says so.
2. **`get_latest_release()` is removed.** With releases out of the model it is a dead path that
   invites reintroducing the assumption.
3. **One archive URL shape**: `/archive/{sha}.zip`, for every ref kind.
4. **Resolution failure warns and continues** against the unresolved ref, matching
   `bootstrap.resolve_ref`. Refusing to run a drift check because `api.github.com` is unreachable
   trades a small consistency gain for a hard outage.
5. **The flag keeps its name.** `--template-version` was exposed hours before this decision (#779);
   renaming it to `--template-ref` twice in a day is churn for a cosmetic gain, and "version" is
   what a consumer calls the thing regardless of its form.

## Rationale
Releases were assumed by half the machinery and have never existed. `git tag` shows one entry,
`v0.0.0`, from the initial commit; `gh release list` is empty. So every drift check any downstream
project has ever run compared against `main` — whatever was merged most recently, including
half-finished sequences.

The two mechanisms also disagreed. `ai-sync-checklist.md` runs `bootstrap --sync` as Phase 1 and the
drift check as Phase 2; the first pinned a SHA and the second fetched the moving `main`, so **the
tooling a project synced and the template it then diffed against could be different commits.** Any
merge in the window landed in the gap, and fifteen PRs merged on the day this was found.

**Why SHA rather than cutting releases.** Both were viable:

- *Cut releases* would give consumers stable checkpoints and make staged upgrades possible
  ("adopt v2.2.0, then v2.3.0"). It costs an ongoing cadence and a judgement each time about what
  "ready" means for a template nobody installs as a package.
- *SHA-based* costs nothing ongoing, matches what `bootstrap.py` already does after #694/#740, and
  what the project already records: `TemplateState.commit` has stored a template commit SHA all
  along. The identity was already half-adopted; this finishes it.

The deciding factor is that `TemplateState.commit` exists. The repo had already chosen commits as
the thing it remembers about the template; only the drift checker's *fetch* disagreed.

Releases are not foreclosed. A tag is a ref, so `--template-version v2.2.0` keeps working if this
project starts cutting them — the difference is that nothing *depends* on their existence.

## Consequences
- **Staged upgrades remain unavailable** until releases exist. A project long behind still gets one
  large diff. This is the real cost of the decision and it is accepted: nothing in the template
  offered staged upgrades before either, because there were no tags to stage between.
- **Every drift check pins its own run.** Two runs against the same ref minutes apart can still
  resolve to different commits if `main` moves; each run is internally consistent, which is what
  `bootstrap.py` guarantees and no more.
- **Phase 1 and Phase 2 still resolve independently**, so the window is narrowed rather than closed.
  Closing it means Phase 1 handing Phase 2 its SHA — worth doing, deliberately not done here to keep
  this change to the decision it records.
- **`get_latest_release` disappears from the public surface** of `tools/pyproject_template`. It was
  exported from `__init__.py`; a downstream that imported it directly breaks. Judged acceptable —
  it returns `None` for this template in every case.
- A downstream can now answer "which template version am I on" with the SHA `bootstrap.py` prints
  and pass that same SHA to `manage.py check`. One identifier across the whole path.

## Related Issues
- Issue #805: the archive root is named for the resolved commit, which this decision made true and
  `manage.py` was never updated for — it kept looking for a fixed `pyproject-template-main`, which
  silently killed the check -> sync handoff. The fix reads the reviewed commit off the archive root's
  own name, so the identity this ADR defines is now the one recorded as the sync point.
- Issue #781: the template has never cut a release, and half the update path assumed it had
- Issue #779: `--template-version` was documented in three places and reachable from none — the flag
  this decision gives a coherent meaning
- Issue #694 / PR #740: `bootstrap.py` ref pinning, the half of the model that was already right
- Issue #770: documented that pinning, and told users to record the SHA

## Related Documentation
- [Keeping Up to Date](../template/updates.md) — the consumer-facing description of what a run pins
- [AI Sync Checklist](../template/ai-sync-checklist.md) — the two phases this decision aligns
- [Template Tooling](../template/tools-reference.md) — `manage.py check` and its flags
- [ADR-9018](9018-agentsmd-carries-only-shared-always-on-instructions.md) — the precedent for
  recording an allocation rule rather than re-deciding it per issue
