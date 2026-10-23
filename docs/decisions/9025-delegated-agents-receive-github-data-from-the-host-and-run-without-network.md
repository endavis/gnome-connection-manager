---
title: "ADR-9025: Delegated agents receive GitHub data from the host and run without network"
description: The host fetches GitHub issue/PR data with doit delegation_context and writes it to files, so delegated agent prompts read those instead of calling gh
date: 2026-10-21
audience:
  - contributors
tags:
  - adr
---

# ADR-9025: Delegated agents receive GitHub data from the host and run without network

## Status

Accepted

## Decision

**The host — the CLI that received the user's command, which already has a trusted, un-sandboxed
`gh` — fetches the GitHub data a delegated agent needs before delegating, writes it to files, and
the delegated prompt reads those files instead of calling `gh` itself.**

1. A new doit task, `delegation_context` (`tools/doit/github.py`), centralizes the fetch:
   - `doit delegation_context --kind=issue --n=<n> --out=<dir>` writes `issue.json`
     (number/title/body/labels/assignees) and `comments.json` (`{"comments": [...]}}`) from one
     `gh issue view --json ...,comments` call.
   - `doit delegation_context --kind=pr --n=<n> --out=<dir>` writes `pr.json`
     (number/title/body/baseRefName/headRefName) from `gh pr view` and `diff.txt` from `gh pr diff`.
   - A missing or inaccessible issue/PR aborts the task with a clear error and exit code 1 — never a
     silent empty file.
2. **Output location:** `tmp/agents/<host>/<task>-<n>/` (for example
   `tmp/agents/claude/multi-review-123/`), per `AGENTS.md`'s temp-file convention. The orchestrating
   skill that creates the directory deletes it once every delegated agent (or subagent) using it has
   returned.
3. **A fixed, generous set of files is fetched per task**, not a `DELEGATION-NEEDS:` back-and-forth:
   the orchestrating skills already run synchronously and sequentially per agent, so there is no
   cheap channel for a delegated agent to ask the host for more mid-run — that would need a second
   round trip through the CLI's non-interactive mode, which none of these hosts support mid-session.
   The fixed set matches what each brief already named explicitly (issue body + comments, PR
   metadata + diff), so nothing is lost versus the old `gh`-in-the-prompt design.
4. **Prompts updated to stop calling `gh`:**
   - `implement-issue`'s Planner brief (step 2) and Coder brief (step 2) read
     `<context-dir>/issue.json`/`comments.json` instead of running `gh issue view`. The caller
     (`implement-issue`'s own Step 3/Step 4, or `multi-plan`) runs `doit delegation_context` first.
   - `multi-plan`'s and `multi-review`'s delegated ("every agent remaining") prompt points at the
     context directory instead of telling the agent to run `gh issue view` / `gh pr view` + `gh pr
     diff`. `multi-adversarial-review`'s delegated prompt already used only `git`/local reads and is
     unchanged.
   - The six Codex review/adversarial-review bridge files
     (`.agents/skills/delegate-codex-{review,adversarial-review}/SKILL.md`,
     `.github/skills/codex-{review,adversarial-review}/SKILL.md`,
     `.claude/commands/codex/{review,adversarial-review}.md`) drop Hybrid C's "activate
     `$codex-review`/`$codex-adversarial-review` if available" fallback, which could still reach
     `gh pr view`/`gh pr diff` from inside a delegated Codex session. They now hand Codex only the
     git-based inline steps that were already there as the non-self-action fallback.
   - Every one of the above now tells its target: if the context directory/file is missing or
     unreadable, print `DELEGATION-ERROR:` and stop — the same marker the host already watches for
     (`DELEGATION_ERROR_CHECK`), repurposed from "a `gh` call failed" to "the pre-fetched context was
     missing or unreadable".
5. **`.codex/rules/gh.rules` is unchanged.** It still serves a headless Codex *host*'s own reads —
   its own `gh issue view`/`gh pr view` in `multi-plan`/`multi-review`'s precondition steps, and the
   Planner brief when Codex itself is the host running inline, not delegated (#984). This ADR only
   removes `gh` from *delegated* prompts.
6. `tests/test_cross_agent_contract.py` enforces the new shape: `GH_COMMAND_PATTERN` asserts no
   delegated prompt (the six Codex bridge files' exec string, and `multi-plan`'s/`multi-review`'s
   blockquoted per-agent prompt) invokes `gh`; `DELEGATION_ERROR_CHECK` is unchanged in substance.

## Rationale

Before this change, five surfaces embedded `gh` directly in a prompt handed to a delegated agent:
`multi-plan` Step 3, `multi-review` Step 3, the six Codex bridge files' Hybrid-C fallback, and
`implement-issue`'s Coder brief. For Codex specifically this already worked — `.codex/rules/gh.rules`
allow-rules the exact read-only subcommands these prompts used (`gh issue view`, `gh pr
{view,diff}`), as long as the call ran standalone rather than chained (#980). But that mechanism is
Codex-specific and allow-rule-dependent: a delegated Claude, Copilot, or Antigravity session has no
equivalent sandbox-escape, and even for Codex, depending on an allow-rule file staying in sync with
every prompt's exact `gh` invocation is a second thing that can drift. Centralizing the fetch in one
doit task, run once by the host before delegating, removes the dependency entirely: a delegated
agent that never calls `gh` cannot be blocked by a missing or stale allow rule, regardless of which
CLI or sandbox it runs in.

A fixed, generous fetch (rather than a request/response protocol where the delegated agent asks for
specific fields) matches how these skills already work: synchronous, sequential delegation with no
cheap mid-run channel back to the host. The three fields each brief already named explicitly (issue
body + comments; PR metadata + diff) are exactly what `delegation_context` fetches, so there is no
information lost by pre-fetching rather than fetching inline — only a difference in *who* makes the
one `gh` call and *when*.

## Consequences

- **Not a breaking change.** No public command, flag, or file was removed; `doit delegation_context`
  is additive, and the six bridge files plus `multi-plan`/`multi-review`/`implement-issue` changed
  only their internal prompt text. See [Consumer Notes](../template/consumer-notes.md) for the
  (non-breaking) behavior note.
- **One more step before every delegation.** `implement-issue`, `multi-plan`, and `multi-review` each
  gain a `doit delegation_context` call (and, for `implement-issue`, a second one before the Coder
  brief, to pick up the plan comment the Planner brief just posted) and a cleanup step that deletes
  the context directory once every agent using it has returned.
- **Headless-Codex-host delegation is *not* fixed by this ADR.** A headless Codex host still cannot
  delegate to another agent CLI at all — the called CLI needs its own reachable model API and a
  writable home directory, neither of which exists inside Codex's sandbox (#984). This ADR only
  removes a *GitHub* network dependency from delegated prompts; a delegated CLI's dependency on its
  own model API is untouched.
- **`.codex/rules/gh.rules` keeps its current scope** (host-side reads only); it is not tightened or
  loosened by this ADR.
- **Supersede check.** This ADR narrows *why* `.codex/rules/gh.rules` is needed (host-only reads, not
  delegated reads) but does not supersede ADR-9019 (the hook-is-a-guardrail principle, unrelated) or
  ADR-9023/ADR-9024 (skill location and `implement-issue`'s shape, unchanged by this).

## Related Issues

- Issue #985: refactor: have hosts fetch GitHub data for delegated agents so they run without
  network
- Issue #984: headless-Codex-host delegation limits (established `.codex/rules/gh.rules` also serves
  a headless host's own reads — untouched by this ADR)
- Issue #980: `gh` has no network inside Codex's sandbox except through an allow-ruled, standalone
  call — the constraint this ADR routes around for delegated prompts

## Related Documentation

- [Cross-Agent Delegation Matrix — Context-file
  convention](../development/ai/cross-agent-delegation.md#context-file-convention) — the
  specification this ADR implements
- [`doit-tasks-reference.md` —
  `delegation_context`](../development/doit-tasks-reference.md#delegation_context) — the task
  reference
- [AI Command Blocking — Codex CLI](../development/ai/command-blocking.md#codex-cli) — the measured
  sandbox-network facts `.codex/rules/gh.rules` routes around for host-side reads
- [Consumer Notes](../template/consumer-notes.md) — the non-breaking behavior note for downstream
  projects
