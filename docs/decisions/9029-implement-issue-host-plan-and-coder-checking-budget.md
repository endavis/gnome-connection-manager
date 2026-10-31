---
title: "ADR-9029: implement-issue host plan and Coder checking budget"
description: The implement-issue host may write the plan after posting findings, with a review pass, and the Coder runs a bounded set of checks while Step 5 runs the one full doit check
date: 2026-10-30
audience:
  - contributors
tags:
  - adr
---

# ADR-9029: implement-issue host plan and Coder checking budget

## Status

Accepted

## Decision

1. **The host may write the plan.** Only when it posted a findings comment on the issue during the run (or posts one with the plan) and the plan cites it. "The change seems clear" does not qualify. In every other case the Planner subagent writes the plan.
2. **A review pass before posting.** A host-written plan goes through the Plan-review brief, run as a subagent (`implement-planner` on Claude) or through another agent CLI. It reads only the draft, the findings and the files the plan names, and it does not explore or probe.
3. **Findings are settled.** Findings passed to the Planner brief are not re-measured or re-probed; the Planner flags any the code contradicts. `multi-plan` passes none, so it behaves as before.
4. **The Coder has a checking budget.** The tests covering the change, one revert check, what project rules require, `doit lint` and `doit type_check`. No `doit check`, no extra mutmut runs, no flakiness reruns unless the plan asks. Its summary lists every check command it ran.
5. **The full suite runs once.** Step 5 runs the single `doit check` plus `doit docs_build`. The host does not rely on a subagent's "check passed" claim (`.claude/rules/verified-claims.md`).

## Rationale

`implement-issue` re-measured findings the host had already posted, and ran `doit check` in both the Coder and Step 5. This amends ADR-9024 on who writes the plan and where validation runs. Success criterion 4 of #1128 (one full `doit check` per run) is pending a measurement on the next real run.

## Documentation

- [Slash Commands and Workflows — implement issue N](../development/ai/slash-commands.md#implement-issue-n)
- [AI Agent Walkthrough](../development/ai/first-5-minutes.md)
- [Cross-Agent Delegation](../development/ai/cross-agent-delegation.md)

Issue: #1128. Amends ADR-9024.
