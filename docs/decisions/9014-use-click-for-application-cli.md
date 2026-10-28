---
title: "ADR-9014: Use click for application CLI"
description: Build the package's user-facing command-line interface with click, registered as a console script
date: 2026-04-09
audience:
  - contributors
tags:
  - adr
  - cli
---

# ADR-9014: Use click for application CLI

## Status

Accepted

## Decision

Use **[click](https://click.palletsprojects.com/)** as the framework for
the package's user-facing command-line interface. The CLI lives at
`src/__PACKAGE_NAME__/cli.py` and is registered as a console script via
`[project.scripts]` in `pyproject.toml`:

```toml
[project.scripts]
__PYPI_NAME__ = "__PACKAGE_NAME__.cli:main"
```

`click` is added to `[project] dependencies` as a runtime dependency
alongside `rich`.

## Rationale

The template previously shipped with an empty `[project.scripts]` block
and no CLI module. Contributors adding a CLI had no obvious convention to
follow, and `docs/development/tooling-roles.md` forward-referenced a
guide that did not yet exist. This ADR documents the chosen framework and
grounds the new [CLI Guide](../usage/cli.md) in real code.

The runtime/dev split documented in
[ADR-9002](9002-use-doit-for-task-automation.md)
and [Tooling Roles and Architectural Boundaries](../development/tooling-roles.md)
requires the application CLI to live under `src/__PACKAGE_NAME__/` and to be
runnable without any dev tooling (no `doit`, no `uv`). A standardized
runtime CLI framework is needed to make that boundary concrete.

`click` was chosen because it is:

- **Mature and widely known.** Most Python developers have used it; the
  learning curve is near zero.
- **Decorator-based.** Commands, options, and arguments compose with
  `@click.command`, `@click.option`, and `@click.argument`, which matches
  the style already used by `pytest` fixtures and other decorator-heavy
  libraries in the ecosystem.
- **Low ceremony for nested subcommands.** `click.Group` + `@main.command()`
  makes adding new subcommands a single function definition.
- **Testable in-process.** `click.testing.CliRunner` allows asserting on
  output and exit codes without spawning subprocesses.
- **Small, focused, and stable.** One runtime dependency with a long
  track record of backward compatibility.

## Alternatives Considered

- **`argparse` (stdlib).** No new runtime dependency, but significantly
  more boilerplate for nested subcommands, and no in-process test runner
  equivalent to `CliRunner`. Rejected because the boilerplate cost
  outweighs the "no new dep" benefit for a template that expects
  contributors to extend the CLI.
- **`typer`.** Ergonomic type-hint-driven API, but it is built on top of
  `click` (so it drags click in anyway), and its Rich-based help
  formatting adds hidden coupling between the CLI framework and
  presentation. Rejected as heavier than necessary for a template
  baseline.

## Consequences

**Positive:**

- The template now has a concrete, testable CLI surface that contributors
  can extend by copying the pattern in `src/__PACKAGE_NAME__/cli.py`.
- The runtime/dev boundary is enforceable: end users of the published
  package run `__PYPI_NAME__ ...` without needing `doit` installed.
- New subcommands have one obvious home and one obvious test pattern.

**Negative:**

- Adds one runtime dependency (`click>=8.1`) to every install of the
  published package.
- The template now has an opinion about CLI framework that adopters who
  prefer `argparse` or `typer` will need to replace.

## Related Issues

- Issue #341: Add application CLI and CLI guide
- Issue #340: Document tooling roles and architectural boundaries
- Issue #342: End-to-end "add a feature" example (forward reference)

## Related Documentation

- [CLI Guide](../usage/cli.md)
- [Tooling Roles and Architectural Boundaries](../development/tooling-roles.md)
- [ADR-9002: Use doit for task automation](9002-use-doit-for-task-automation.md)
