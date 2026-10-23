---
title: Review Focus Areas
description: Checklists for the errors, tests, types and comments focus areas available to every review and adversarial-review surface
audience:
  - contributors
  - ai-agents
tags:
  - ai
  - review
  - workflow
---

# Review Focus Areas

## Purpose

Every `review [focus]` and `adversarial-review [focus]` surface — self-action and cross-agent
delegation alike — already passes a free-form focus-area argument into the same placeholder. This
page adds four named focus areas to that slot: `errors` (silent failures), `tests` (test quality),
`types` (type design) and `comments` (comment and docstring accuracy). Each is a short, concrete
checklist grounded in standards this project already states in `AGENTS.md` — hunting for the
failure classes a general review tends to skim past in one line or none.

This doc is the single source for the four checklists. Every review and adversarial-review surface
carries one pointer sentence to this file; none copies the checklist text, so the four checklists
cannot drift into four slightly different versions.

## How focus areas are invoked

- **No argument:** the general checklist runs exactly as it did before this page existed.
- **One or more of `errors`, `tests`, `types`, `comments`,** comma-separated (e.g. `errors,tests`):
  run the matching checklist(s) below *in addition to* the general checklist, never instead of it.
- **Any other text:** passes through as free-form guidance to the reviewing agent, the same as
  before this page existed.

## errors

AGENTS.md lists "Silent Failures" as an anti-pattern: "Always log errors and raise exceptions with
context." This checklist hunts for places that violate it.

- Does every `except` clause either re-raise, log with context, or document why the error is safe
  to swallow? Flag a bare `except:` or an `except Exception: pass`.
- Does a fallback value (a default, `or ""`, stale cached data) get returned without a log line or
  raised exception saying the primary path failed?
- Is a caught error logged and then discarded, instead of propagated to a caller that could
  actually act on it?
- Does a caught exception lose the original cause — a missing `raise ... from err`, or
  `logger.error` where `logger.exception` would keep the traceback?
- Is invalid input validated and rejected, or does it silently fall through to a
  wrong-but-plausible result instead of failing loudly?
- Do retries or timeouts hide a persistent failure by eventually returning a cached or default
  value with no signal that the failure happened?
- Does a function that can fail have a return type that cannot represent failure (e.g. an empty
  list or `False` on error), leaving the caller no way to tell real-empty from failed?

## tests

AGENTS.md requires tests with every piece of new code; this checklist asks whether those tests
would actually catch a regression.

- For each new or changed behavior: if the implementation change were reverted, would the matching
  test fail? A test that still passes against the old behavior is not testing the behavior.
- Are error paths and edge cases exercised, not only the success path — empty input, `None`,
  boundary values, a raised exception?
- Does the assertion check the actual behavior (output, raised exception, call made), rather than
  an incidental detail — log wording, an internal attribute — that can stay green through a real
  regression?
- Is there a test for every new branch, especially ones added to fix a bug, so the fix cannot
  silently regress?
- Do mocks and stubs replace only the boundary under test (I/O, network, time), not the logic being
  verified? Over-mocking proves the mock was called, not that the code is correct.
- Does any test pass unconditionally — asserting on a value it just mocked, or swallowing its own
  failure in a `try`/`except: pass`?

## types

A strict-mypy project gains from reviewing new types for the invariants and encapsulation they
should carry, not only for having an annotation at all.

- Do new or changed parameters, returns, and module-level names carry complete, non-`Any`
  annotations so mypy strict mode actually checks them?
- Do new types encode the invariant they are meant to hold (a frozen dataclass, an enum instead of
  a raw string) rather than leaving validation to scattered runtime checks?
- Is `| None` used only where `None` is a genuine, handled state, not as a stand-in for "not sure
  yet"?
- Do new classes expose only what callers need, rather than public mutable attributes a caller
  could put into an invalid state?
- Per `.claude/rules/typing-branch-narrowing.md`: is a narrowing annotation placed at the narrowest
  scope that is correct, rather than hoisted to function scope just to silence mypy?
- Are container types specific (`list[Foo]`, not `list`), rather than widened to `Any` or `object`
  to make an error go away?

## comments

Comments and docstrings are only useful while they still describe the code they sit on.

- Does every comment describe the code immediately around it as it exists now, not a prior version
  left behind by an earlier edit in this diff?
- Do docstrings' parameter and return descriptions match the current signature — names, types,
  order — after this change?
- Is a comment explaining why a non-obvious choice was made still accurate for the choice actually
  made, rather than for a different choice this diff replaced?
- Does any comment state something the code cannot actually do — e.g. "never returns None" next to
  a path that can?
- Were comments updated in the same diff as the code they describe, rather than left to drift
  because the change "did not touch that part"?
- Does a TODO or FIXME left in this diff still apply, or does it describe something this change
  already resolved?
