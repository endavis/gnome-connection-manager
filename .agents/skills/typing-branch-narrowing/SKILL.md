---
name: typing-branch-narrowing
description: Use when adding, widening, or removing a Python type annotation to resolve a mypy [no-redef], [assignment], or [unreachable] error on a name bound in more than one if/elif/else branch.
---

Skill: typing

Self-check before adding or changing a type annotation to silence a mypy error:

1. Is the name bound in more than one branch? If not, this rule does not apply.
2. Do all branches `return` before the branches converge? If yes, each branch owns
   its own binding — do NOT hoist an annotation to function scope. Remove the
   redundant one instead (`_parse_input`, #701).
3. If the branches fall through to shared code, annotate once before the chain
   using the WIDEST type any branch assigns — including `| None` (`cleanup.py`,
   #700).
4. After the change, re-run mypy and confirm no new `[unreachable]` appeared.
5. If mypy now calls an `isinstance` / `is None` guard unreachable, the annotation
   is too narrow. Fix the annotation. Do NOT delete the guard — both observed
   failures had a guard that fires on real input.
6. Confirm the file is actually type-checked. Both failures reached review because
   `doit check` did not cover the file at the time (#700).

Observed failures: endavis/pyproject-template#701, endavis/pyproject-template#700
