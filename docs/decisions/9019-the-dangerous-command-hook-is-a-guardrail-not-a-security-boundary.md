---
title: "ADR-9019: The dangerous-command hook is a guardrail, not a security boundary"
description: The dangerous-command hook guards against a non-adversarial agent, not a determined one
date: 2026-08-29
audience:
  - contributors
tags:
  - adr
  - ai
  - hooks
  - security
---

# ADR-9019: The dangerous-command hook is a guardrail, not a security boundary

## Status
Accepted

## Decision
The dangerous-command hook is a **guardrail against a non-adversarial agent, not a boundary
against a determined one.** ADR-9005 decided to block commands at the tool level; this decides
*what* it should block and *how far* it should go to do it.

**Three categories, deliberately different in value:**

| category | examples | what it is doing | tolerance |
| :--- | :--- | :--- | :--- |
| **1. Workflow redirect** | `gh pr create` → `doit pr`, `gh issue create`, `uv add`, `doit release`, `ready-to-merge` | process compliance; the *message* is the product | false positives cheap; false negatives cost a template |
| **2. Damage guardrail** | `rm -rf ~`, `git reset --hard`, force-push or delete a protected branch, `--no-verify`, `--admin` | irreversible harm from a careless agent | highest value per line; both error kinds matter |
| **3. Accidental exposure** | `env`, `printenv SECRET`, `~/.netrc`, `~/.aws/credentials` | tripwire against a secret reaching a transcript | trivially avoided by design; precision here buys little |

All three assume the agent is **not trying to evade the hook**. An agent that types `rm -rf ~` meant
it as a shortcut. This assumption is what makes pattern matching a reasonable instrument at all, and
it is the reason none of the categories justify unbounded effort.

**Two layers of scanning, and each stays in its lane:**

- **Precise layer** — the command line proper, plus payloads that are *provably shell*:
  `bash/sh/zsh/dash -c <payload>`, `eval`, and a heredoc fed to a shell's stdin (`bash <<EOF`).
  These are re-scanned by `check_command` with every check, including the position-sensitive ones
  (`check_env_dump`, `check_credential_file_read`).
- **Crude layer** — a flat `shlex` token scan over the whole command string, matching a pattern in
  any position. A catch-all tripwire.

**Rules that follow, and are the operative part of this decision:**

1. **Never trade crude-layer coverage for precision.** The over-matching is the feature: it needs no
   allowlist, so it covers interpreters nobody has thought about.
2. **Add a payload to the precise layer only when the payload is shell.** Not Python, Perl, Ruby or
   JavaScript: shell patterns inside those are string literals, and the real risk in them
   (`os.system("cat ~/.netrc")`) is not shell-shaped, so scanning buys false positives and no
   coverage.
3. **Crude-layer false positives are fixed by convention, not by making the crude layer smarter.**
   A heredoc that names a blocked pattern in prose is blocked; the answer is to pass the text by
   file (#759), not to teach the scanner to recognise prose.
4. **Do not spend complexity on category 3.** It is already documented as not-a-boundary. Precision
   there is false assurance.

## Rationale
The principle already existed in `command-blocking.md`, stated for one case:

> `$VAR` interpolation is deliberately **not** blocked: legitimate uses are common, and blocking it
> would give false assurance while being trivially avoided.

That is the correct test. It had never been generalised, so each new question — *should the hook see
inside a heredoc?* — was re-argued from scratch and answered inconsistently. The immediate cause of
this ADR is two issues that pointed in opposite directions (#759, over-blocking prose; #762,
under-blocking executed bodies) and turned out to be the same design question.

**Both plausible "fix the false positive" routes were measured, and both cost real coverage:**

| candidate | what it un-blocks |
| :--- | :--- |
| strip heredoc bodies whose receiver consumes them as data | `perl <<EOF` / `rm -rf ~`, `ruby <<EOF` / `--admin`, `node <<EOF` / `git push --force origin main`, `ssh host <<EOF` / `rm -rf ~` |
| make wrapper detection position-aware | `xargs bash -c`, `find -exec bash -c`, `timeout 5 bash -c` |

Every one of those is blocked today **only** because the crude layer over-matches. Trading four
category-2 blocks for one cosmetic false positive is the wrong direction, and a *more correct* shell
parser makes it worse, not better: a parser that understood heredoc ownership would stop flagging
`perl <<EOF` / `rm -rf ~` unless it also modelled Perl, and that regress is unbounded.

Rule 2 was learned the same way. An earlier draft of #762 included `python3 - <<EOF` as an
interpreter whose body should be scanned. It is not:

```console
$ python3 - <<'PY'
printenv PATH
PY
SyntaxError: invalid syntax
```

The body is Python. `printenv PYPI_TOKEN` there does not dump anything, it crashes — so the
pre-existing test case marking it `ALLOW` and labelling it "heredoc *mentioning* a dump" was right,
and the draft that flipped it to `BLOCK` was wrong.

## Consequences
- **Known false positives are accepted and recorded** rather than engineered away: prose naming a
  blocked pattern inside `cat > file <<EOF`, `gh ... --body-file - <<EOF`, or a `bash -c` payload
  quoted inside a data heredoc. Conventions the repo already has — the Write tool over
  `cat <<EOF`, `--body-file=<path>` over `-` — avoid all of them.
- **#762 is the last precision addition of its kind.** It closes a real inconsistency and makes the
  enforced-processes table true, but everything it newly blocks is category 3; every category-2
  pattern in a shell heredoc was already caught by the crude layer. Under rule 4 it would not be
  proposed today, and this ADR exists partly so the next one is not.
- **Future "should the hook catch X" is answered by category and rule**, not re-argued. If X is
  category 3 and needs new parsing, the answer is no.
- **The hook stays small enough to audit.** It is a single file every agent depends on; the cost of
  a subtle mistake in it is higher than the cost of the false positives it produces.
- This constrains contributors who will reasonably want to close a demonstrated gap. The constraint
  is deliberate: a demonstrated gap in category 3 is not sufficient reason to add parsing.

## Related Issues
- Issue #762: interpreter heredoc bodies escaped the position-sensitive checks — the precise-layer
  addition this ADR bounds
- Issue #759: the hook scans heredoc bodies, so commit messages naming a blocked pattern are
  refused — the crude-layer false positive this ADR declines to fix in the matcher
- Issue #678: git global options, refspecs and shell wrappers — an earlier round of the same
  precise-versus-crude question
- ADR-9005: the decision to block at the tool level, which this scopes

## Related Documentation
- [AI Command Blocking](../development/ai/command-blocking.md) — the pattern tables, the deny
  contracts, and the category-3 threat model this generalises
- [AI Enforcement Principles](../development/ai/enforcement-principles.md) — why enforcement lives
  in code rather than instructions, and the Block and Redirect pattern category 1 depends on
- [ADR-9005](9005-ai-agent-command-restrictions.md) — the mechanism decision this builds on
