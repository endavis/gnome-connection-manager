---
title: "ADR-9012: Use mkdocs with Material theme for documentation"
description: Build the documentation with MkDocs and the Material theme, and host it on GitHub Pages
date: 2026-01-21
audience:
  - contributors
tags:
  - adr
  - tooling
---

# ADR-9012: Use mkdocs with Material theme for documentation

## Status

Accepted

## Decision

Use **MkDocs** with the **Material for MkDocs** theme for project documentation, hosted on GitHub Pages.

## Rationale

MkDocs uses Markdown (familiar to most developers), Material theme provides modern responsive design with search and dark mode out of the box, and documentation lives alongside code ensuring it stays in sync. Free hosting on GitHub Pages.

## Related Issues

- Issue #169: Auto-generate categorized documentation TOC from frontmatter tags
- Issue #109: Add comprehensive template tools and workflows documentation
- Issue #105: Improve GitHub workflows and documentation

## Related Documentation

- [Documentation Index](../index.md)
- [Extensions Guide](../development/extensions.md)
