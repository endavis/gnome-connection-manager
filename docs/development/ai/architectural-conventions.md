---
title: AI Architectural Conventions
description: Imperative-form architectural rules AI agents must follow when generating code
audience:
  - contributors
  - ai-agents
tags:
  - ai
  - architecture
---

# AI Architectural Conventions

## Purpose

This page is the imperative-form rulebook AI agents must follow when generating code in this template. It complements [Tooling Roles and Architectural Boundaries](../tooling-roles.md), which explains *why* the layering exists and is written for human readers. This page restates those rules as short directives plus concrete anti-patterns AI agents frequently hit. Do not duplicate the rationale here — read `tooling-roles.md` when you need the reasoning.

## Rules

**DO:**

- DO put runtime application code under `src/__PACKAGE_NAME__/`.
- DO put development tooling, scaffolding, install scripts, and doit task definitions under `tools/`.
- DO expose the application's user-facing command-line interface as a console script declared in `[project.scripts]` in `pyproject.toml`, backed by a module under `src/__PACKAGE_NAME__/`.
- DO keep `[project] dependencies` minimal. Every entry ships to every end user of the package.
- DO use `doit <task>` for development workflows (test, lint, type-check, build, release, issue and PR creation).
- DO add heavy libraries used only by tests or tooling to `[dependency-groups] dev`, not `[project] dependencies`.

**DO NOT:**

- DO NOT import from `tools/` or `dodo.py` in any module under `src/__PACKAGE_NAME__/`. Runtime code must be installable and runnable without any dev tooling present.
- DO NOT use `doit` tasks to expose application functionality to end users. `doit` is a dev surface, not a runtime surface.
- DO NOT add a runtime dependency without asking the user first. See the "Ask First" policy in `.github/CONTRIBUTING.md`.
- DO NOT conflate the development CLI (`doit`) with the application's runtime CLI (console script) in code, PR descriptions, or docs.

## Common failure modes

Concrete anti-patterns AI agents hit in this template, with the correct framing for each.

### 1. Adding a new user-facing feature as a doit task

**Wrong:** User asks for a "greet" command. Agent adds `def task_greet()` under `tools/doit/` so the user runs `doit greet`.

**Right:** Add a module under `src/__PACKAGE_NAME__/` that implements `greet`, register a console script in `[project.scripts]` (e.g. `greet = "__PACKAGE_NAME__.greet:main"`), and test it as runtime code under `tests/`. End users install the package and run `greet` directly — they should never need `doit` installed.

### 2. Importing a helper from `tools/` into `src/__PACKAGE_NAME__/`

**Wrong:** Runtime module does `from tools.doit.helpers import something` because the helper "already exists and does what I need."

**Right:** If the helper is needed by runtime code, move it into `src/__PACKAGE_NAME__/` and test it as runtime code. If it is only needed by dev tooling, duplicate the small bit of logic or keep it in `tools/` — `src/__PACKAGE_NAME__/` never imports from `tools/` or `dodo.py`.

### 3. Adding a heavy library to `[project] dependencies` for tests or tooling

**Wrong:** Test needs `hypothesis`, so agent runs `uv add hypothesis`, which adds it to `[project] dependencies`. Every downstream user of the package now pulls `hypothesis` at install time.

**Right:** Add test-only and tooling-only libraries to `[dependency-groups] dev`. Runtime dependencies ship to every user of the package and must stay minimal. New runtime deps require explicit user approval (do not run `uv add` on your own — that command is blocked for AI agents).

### 4. Proposing `doit run_app` as the user entry point

**Wrong:** Agent drafts a README section telling end users to `pip install __PACKAGE_NAME__ && doit run_app` to launch the application.

**Right:** End users run the console script declared in `[project.scripts]`. They install the package and invoke the entry point by name. `doit` is not in the runtime dependency surface for end users and must not be presented as a runtime entry point.

### 5. Conflating the dev CLI with the runtime CLI

**Wrong:** PR description says "adds `doit foo` command for users." Docs under `docs/usage/` reference `doit` tasks as the way to use the package.

**Right:** Keep the two surfaces distinct in both code and prose. `doit` tasks live in contributor-facing docs (`docs/development/`). The application's user-facing commands live in end-user docs (`docs/usage/`, `docs/getting-started/`) and are invoked via the console script, not `doit`.

## Before generating code

Short checklist to run through before writing any new code:

1. Read [Tooling Roles and Architectural Boundaries](../tooling-roles.md) for the layering rationale.
2. Identify the layer the change belongs in: runtime (`src/__PACKAGE_NAME__/`), dev tooling (`tools/`), or dev entry point (`dodo.py`).
3. Confirm imports respect the boundary: nothing under `src/__PACKAGE_NAME__/` imports from `tools/` or `dodo.py`.
4. If the change adds a user-facing command, plan it as a console script under `[project.scripts]`, not a `doit` task.
5. If the change needs a new runtime dependency, stop and ask the user first.

## See also

- [Tooling Roles and Architectural Boundaries](../tooling-roles.md) — the human-facing rationale for the layering
- [ADR-9002: Use doit for task automation](https://github.com/endavis/pyproject-template/blob/main/docs/decisions/9002-use-doit-for-task-automation.md)
- [ADR-9005: AI agent command restrictions](https://github.com/endavis/pyproject-template/blob/main/docs/decisions/9005-ai-agent-command-restrictions.md)
- [AI Enforcement Principles](enforcement-principles.md)
- [AI Command Blocking](command-blocking.md)
- [`AGENTS.md`](../../../AGENTS.md) — imperative tool reference and workflow rules
