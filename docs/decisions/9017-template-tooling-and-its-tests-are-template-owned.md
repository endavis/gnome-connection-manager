---
title: "ADR-9017: Template tooling and its tests are template-owned"
description: A test under tests/template/ is template-owned when its target does not survive configuration
date: 2026-07-16
audience:
  - contributors
tags:
  - adr
  - template
  - testing
---

# ADR-9017: Template tooling and its tests are template-owned

## Status
Accepted

## Decision
A test in `tests/template/` is **template-owned** when its target does not survive
configuration. Template-owned tests run only in the template's own CI, are excluded from the
drift checker, and are shed from downstream projects by every path that turns the template
into a real project.

That membership test resolves the question `tests/template/` had grown ambiguous about
(#691). Applying it:

| test target | owner | why |
| :--- | :--- | :--- |
| `tools/pyproject_template/` | **template** | Both spawn routes delete the suite; a downstream that keeps it holds tests for a namespace that no longer exists. |
| `configure.py`, `README.template.md` | **template** | Consumed by configuration itself — `configure.py` self-destructs, `README.template.md` is renamed onto `README.md`. |
| `tools/doit/`, `tools/hooks/` | **downstream** | This code ships to the spawned project, runs there (`doit check`, `doit pr`, the dangerous-command hook), and is measured by the project's own coverage gate. |
| `.claude/`, `.agents/`, `.github/` assets | **downstream** | Ship with the project and are the project's to maintain. |

`test_doit_*.py` is therefore **downstream-owned** and travels with the project. The earlier
implied answer — shed everything under `tests/template/` — left a spawned project running
several thousand statements of untested tooling and failing its own coverage gate on the first
CI run (#731).

A single constant `TEMPLATE_OWNED_TEST_FILES` in `utils.py` is the authoritative list.
`check_template_updates.py`, `cleanup.py`, `configure.py` and `setup_repo.py` all import from
it; none hardcodes the list.

## Rationale
Before this decision, tooling tests lived alongside skeleton tests with no distinction.
The drift checker would present them as "please adopt" suggestions to downstream projects,
and `cleanup --setup` left them in place — meaning a downstream project would carry
template-CI tests that import `tools.pyproject_template.*` (a namespace that no longer
exists after cleanup removes the tooling directory).

A single source of truth avoids the shed-list and exclude-list diverging silently.

The "straddler" file `tests/template/test_properties.py` was split:
- `test_properties.py` — downstream-owned; contains only skeleton (`greet`) assertions.
- `tests/template/test_utils_properties.py` — template-owned; contains tooling property tests.

A coupling guard (`_emit_coupling_warnings`) warns when a drifted non-owned test imports
tooling that has also drifted, so users know to run `bootstrap --sync` before adopting
that test.

## Consequences
- **Downstream projects carry no tests for the *management suite*.** The suite
  (`manage.py`, `check_template_updates.py`, `cleanup.py`, …) still ships via
  `bootstrap.py` `TEMPLATE_MODULES`, but its tests do not. We accept this: downstreams
  consume that tooling without modifying it, and these tests depend on template-only
  fixtures (the `package_name` skeleton) that no longer exist once a downstream is
  configured. This is why the alternative — adding the tests to `TEMPLATE_MODULES` so
  tooling and tests travel together — was rejected: it would push non-runnable,
  skeleton-coupled tests into every downstream.

  This clause is scoped to the management suite and **does not** extend to
  `tools/doit/` or `tools/hooks/`, which keep their tests (#731). It was stated
  broadly enough at first to read as a blessing for shedding those too.

- **The coverage gate excludes `tools/pyproject_template/`.** Because its tests are
  template-owned while the code itself may linger in a downstream, measuring it would
  count code that is never tested there. Omitting it makes the gate report the same
  number in the template and in a spawned project (#731). The suite's tests still run
  in template CI; they no longer feed the ratchet.
- **Existing downstreams need a one-time cleanup.** Projects that adopted these
  tests in an earlier sync are not cleaned up automatically; they should run
  `cleanup --setup` once to shed them (see
  [AI Sync Checklist – Phase 1](../template/ai-sync-checklist.md)).
- **Known limitation — the stale-comparator facet remains.** The drift checker runs
  from the downstream's local (possibly stale) tooling, so both the exclusion list
  (`TEMPLATE_OWNED_TEST_FILES`) and the comparison logic are only as fresh as the
  last `bootstrap --sync`; a newly template-owned test added upstream is not excluded
  until the downstream syncs `utils.py`. A self-updating comparator was considered and
  declined as too fragile — running `bootstrap --sync` first (now an always-run early
  step) is the mitigation.

## Related Issues
- Issue #631: Make template tooling tests template-owned
- Issue #731: `configure.py`/`setup_repo.py` shed tests the spawned project's coverage gate
  depends on (PR #732) — established the membership test recorded above
- Issue #691: `configure.py` and `cleanup.py` disagree on what is template-owned

## Related Documentation
- [Template Tooling](../template/tools-reference.md)
- [AI Sync Checklist – Phase 1](../template/ai-sync-checklist.md)
- [CI/CD and Testing](../development/ci-cd-testing.md) — the downstream/template coverage split
- [New Project Setup](../template/new-project.md) — where the manual route sheds the suite
