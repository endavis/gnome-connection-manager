---
title: "ADR-9016: Unify ADR directories under docs/decisions"
description: Keep every ADR in docs/decisions/, numbering template decisions 9XXX and project decisions from 0001
date: 2026-04-22
audience:
  - contributors
tags:
  - adr
  - template
---

# ADR-9016: Unify ADR directories under docs/decisions

## Status

Accepted

## Decision

Collapse `docs/template/decisions/` into `docs/decisions/` so all ADRs —
template-meta (9XXX) and project-level (0001+) — live in a single
directory. The numeric prefix alone encodes ownership: 9XXX for
template-meta decisions, 0001+ for project-level decisions.
Downstream projects spawned from `pyproject-template` inherit the 9XXX
ADRs via the clone. They can keep, delete, or supersede any inherited
ADR with their own 0001-series ADR.

## Rationale

Before this decision, the template had two ADR directories:
`docs/template/decisions/` held 9001–9015 (template-meta) and
`docs/decisions/` was intended as an empty scaffold for downstream
projects' 0001-series ADRs. The split was meant to separate
template-meta from project-level decisions, but the numeric prefix
already carries that distinction, so the physical directory added no
information.

The split produced real cost. Guidance about where ADRs live was
inconsistent across the repo (the issue enumerated seven guidance files
and a hardcoded `ADR_DIR`); `doit adr` could only target the scaffold
path, so every 9XXX ADR had to be authored by hand; and
`tools/pyproject_template/manage.py` grew a `_copy_template_adrs` helper
plus an opt-in prompt during downstream project creation to let the
user decide whether to propagate 9XXX ADRs into `docs/decisions/` — a
choice that existed purely because the split forced the question.

Unifying into one directory collapses all of that: a single path to
reference, a single regex per series inside `_get_next_adr_number()`,
and no opt-in prompt. Downstream projects always inherit the 9XXX ADRs
via the clone; they can delete or supersede any of them without any
template-side tooling.

## Consequences

- **Single `docs/decisions/` directory.** `docs/template/decisions/` is
  deleted. The template's own `docs/template/` directory remains (it
  holds non-ADR template docs).
- **`doit adr --template` flag.** Project ADRs are created with
  `doit adr`; template ADRs with `doit adr --template`. The flag is
  explicit — there is no auto-detect-from-repo-context logic.
- **Downstream consumers always inherit 9XXX ADRs.** The opt-in prompt
  in `manage.py` and the `_copy_template_adrs` helper are removed. A
  downstream project that does not want an inherited template ADR can
  delete the file or supersede it with a 0001-series ADR.
- **One-time manual migration for already-spawned downstream projects.**
  Each downstream project should `git mv docs/template/decisions/9*.md
  docs/decisions/` and delete the now-empty `docs/template/decisions/`
  directory. This is a one-time per-project operation; the user owns
  all current downstream projects and will handle it by hand.
- **Guidance docs simplify.** Every file that previously mentioned both
  directories now points at the single `docs/decisions/` path.

## Related Issues

- Issue #461: contradicting guidance about where ADRs go

## Related Documentation

- [ADR Documentation](README.md) — the two-series convention
- [Doit Tasks Reference — `adr`](../development/doit-tasks-reference.md#adr)
- [Tooling Roles and Architectural Boundaries](../development/tooling-roles.md)
