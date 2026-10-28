---
title: Slash Commands and Workflows
description: Reference for the slash commands and dual-agent workflow this project ships with
audience:
  - contributors
  - ai-agents
tags:
  - ai
  - workflow
  - slash-commands
---

# Slash Commands and Workflows

## Purpose

This page documents the slash commands this project ships — the shared `implement-issue` skill
that drives an issue to an open PR, self-action and multi-agent review commands under
`.claude/commands/`; the shared workflow skills (`implement-issue`, `ghi-status`,
`checkpoint`/`restore`, `template-sync`, `template-migrate`, `add-dependency`, `mutation-triage`,
`property-tests`, `deprecate-api`, `python-version-bump`, `security-triage`, `dead-code-triage`,
`perf-change`, `merge-pr`) written once under `.agents/skills/` and generated for Claude under `.claude/skills/`
by `doit skills_sync` — and the single-agent and multi-agent workflows built on top of them. It is
written for contributors who want to understand or extend the workflow, and for AI agents that need
to know which command to run at each stage of the issue lifecycle.

## Workflows

### Single-agent workflow

The default flow takes an issue from unplanned to an open PR in one run. Each step produces an
artifact the next step expects.

1. **"Implement issue \<n\>"** (natural language, any host) — the `implement-issue` skill decides
   whether to plan first (`needs-adr`, more than about three files, or more than one reasonable
   approach), posts a plan comment with the header `## Implementation Plan for #<n>: <title>` when
   it does (no approval wait), then implements the change with tests in a subagent, runs `doit
   check` and `doit docs_build`, commits with `git commit` in the CONTRIBUTING format, pushes, and
   opens the PR with `doit pr` (`Addresses #<n>`). It then watches `gh pr checks` and fixes any
   failing job other than `require-label` for up to 3 rounds, stopping and reporting whatever is
   still red after that. See [`implement-issue`](#implement-issue-n) below.
2. **(Optional) "implement issue \<n\> with \<agent\>"** — hands only the coding step to `<agent>`'s
   CLI; every other step (deciding whether to plan, committing, opening the PR, fixing CI) still
   runs in the host that received the request.
3. **User review of the PR** — inspect the diff on GitHub, optionally run `/<currentai>:review` or
   `/multi-review` for a second opinion, and discuss fixes directly in chat; no command is needed
   for fix-ups (the skill is not re-run for small corrections — just edit, `doit check`, commit, and
   push).
4. **User-driven merge** — the user reviews the PR, adds the `ready-to-merge` label, and merges via
   `doit pr_merge` (or the web UI), or says "merge \<n\>" to run [`merge-pr`](#merge-pr-n). The
   label stays manual — neither `implement-issue` nor `merge-pr` applies it, and
   `implement-issue` never merges.
5. **Close the issue** — `merge-pr` closes the issues the PR fully addresses and comments on the
   rest. Merging by hand, run `doit pr_merge --auto-close` (or `gh issue close <n>`) to close the
   linked issue and post a closing comment.

### Multi-agent workflow

The multi-agent flow adds orchestrated review calls that spawn any combination of agents in
**isolated contexts**, on top of the PR `implement-issue` already opened. The design intent is that
no agent can bias another: each generates its output without seeing the others' work, and the
orchestrating agent in the main conversation posts all raw outputs plus a synthesis.

Each agent's output is posted as a separate comment. The orchestrator is the only agent that writes
to GitHub — all other agents run in non-interactive mode and emit to stdout only.

1. **"Implement issue \<n\>"** — same as the single-agent flow; produces the open PR these commands
   review.
2. **`/multi-review <ais...>`** — takes a list of agent names. Each listed agent independently
   reviews the current branch's PR; all reviews are posted as separate PR comments. The orchestrating
   agent synthesizes findings into a combined verdict. A user-approval gate precedes the synthesis
   post.
3. **`/multi-adversarial-review <ais...>`** — takes a list of agent names. Each listed agent
   independently challenges the current changes; all adversarial reviews are synthesized. If a PR
   exists the synthesis is posted; otherwise it appears in-conversation only. A user-approval gate
   precedes posting.
4. **Merge** and **`doit pr_merge --auto-close`** — same as the single-agent flow.

`/multi-plan` still exists for the rare case of wanting independent plans from several agents
synthesized into one before `implement-issue` runs. Since #975 each listed agent runs
`implement-issue`'s own Planner brief rather than its own planning steps, so the synthesized plan
uses the same format `implement-issue` posts on its own.

### Diagnostic command

**`/ghi-status`** can be invoked at any point. It inspects the current branch, issue state, plan comment, uncommitted changes, unpushed commits, and open PRs, then reports a status summary and the suggested next command (typically "implement issue N"). It has no side effects.

## Shared workflow skills: one source, generated for Claude

Eighteen workflow skills — `implement-issue`, `ghi-status`, `checkpoint`, `restore`, `template-sync`, `template-migrate`, `add-dependency`, `mutation-triage`, `property-tests`, `deprecate-api`, `python-version-bump`, `security-triage`, `dead-code-triage`, `perf-change`, `merge-pr`, `multi-plan`, `multi-review`, `multi-adversarial-review` — are written once, in `.agents/skills/<name>/SKILL.md`, with no Claude-only frontmatter so Claude can auto-invoke them from their `description:` the same way Codex, Antigravity and Copilot do. **Edit only the `.agents/skills/` copy.** `doit skills_sync` then copies each one, byte for byte, to `.claude/skills/<name>/SKILL.md` — the path Claude Code reads (verified against Claude Code 2.1.304, which does not read `.agents/skills/`). The task runs only when this project wires Claude Code; `doit skills_sync --check` reports drift and exits non-zero instead of writing anything, and `tests/template/test_skills_sync.py` enforces that the generated copies never drift from source in this repo.

The slash names are unchanged for Claude users: `/add-dependency` and the rest still work, now as skills rather than single-file commands. `multi-plan`, `multi-review` and `multi-adversarial-review` joined this list in #975, once each could say "the entry in the table that matches the CLI running this skill is you" instead of hardcoding one agent as self — see [Multi-agent orchestration](cross-agent-delegation.md#multi-agent-orchestration-multi-) for what changed. `ghi-finalize` and the per-agent `plan`/`implement` matrix are gone entirely, replaced by `implement-issue` (#976).

## Command reference

Entries are alphabetical. Each one names the command, its arguments, what it does, its position in the workflow, and any design note worth knowing.

### `/<ai>:adversarial-review [focus]` (Copilot: `/<ai>-adversarial-review`)

**Args:** optional focus area. **Sources:** `.claude/commands/claude/adversarial-review.md`, `.agents/skills/codex-adversarial-review/SKILL.md` (self-action); `.claude/commands/<target>/adversarial-review.md`, `.github/skills/<target>-adversarial-review/SKILL.md` (cross-agent delegation). Copilot uses skill names instead of slash commands (see [Copilot section](#copilot) below).

Runs an adversarial review using the host agent (self-action) or delegates to a target agent (cross-agent). The review is read-only: it pressure-tests design choices, hidden assumptions, tradeoffs, alternatives, and failure modes. The host agent presents findings in the format Direction Critique / Hidden Assumptions / Failure Modes / Alternatives Worth Considering. If a PR exists, the user is asked whether to post the review as a PR comment. **Workflow position:** optional adversarial challenge on the PR `implement issue N` opened. **Design note:** in the self-action form, the host agent does the review work itself; no external CLI is invoked. **Focus areas:** passing `errors`, `tests`, `types`, or `comments` (comma-separated) as the focus argument runs the matching checklist from [Review Focus Areas](review-focus-areas.md) in addition to the general review; any other text passes through as free-form guidance, and no argument runs the general review unchanged.

### implement issue N

**Args:** issue number, optionally followed by `with <agent>` to delegate only the coding step. **Trigger:** "implement issue N" or a close variant, or the user approving work on an issue — including a "yes" to a fix the agent proposed and filed as an issue. A question is not approval. **Sources:** `.agents/skills/implement-issue/SKILL.md` (Codex, Antigravity, Copilot, and the source Claude's copy is generated from); `.claude/skills/implement-issue/SKILL.md` (Claude, generated by `doit skills_sync`); `.claude/agents/implement-worker.md` (Claude's Coder-brief subagent).

Takes an open issue to an open PR in one run, replacing the former `/<ai>:plan` → `/<ai>:implement` → `/ghi-finalize` chain. Validates the issue is open, creates or resumes the branch `<type>/<n>-<short-description>` from a label→type mapping, decides whether to post a plan first (`needs-adr`, more than about three files, or more than one reasonable approach — otherwise the issue body is the spec), implements with tests in a subagent (the Coder brief; Claude's is `implement-worker`), or inline for a small change (see the skill's Step 4), runs `doit check` and `doit docs_build`, commits with `git commit` in the CONTRIBUTING format, pushes, and opens the PR with `doit pr` (`Addresses #<n>`). It then watches `gh pr checks` and fixes any job other than `require-label` for up to 3 rounds, stopping to report whatever is still red after that. **Workflow position:** first and only step of the single-agent workflow before PR review. **Design note:** there is no approval wait for the plan or the commit — the trade is explicit, and the skill never applies `ready-to-merge`, merges, or closes the issue. See [Cross-Agent Delegation Matrix — plan and implement are no longer part of this matrix](cross-agent-delegation.md) for why this replaced the per-agent matrix.

### `/<ai>:review [focus]` (Copilot: `/<ai>-review`)

**Args:** optional focus area. **Sources:** `.claude/commands/claude/review.md`, `.agents/skills/codex-review/SKILL.md` (self-action); `.claude/commands/<target>/review.md`, `.github/skills/<target>-review/SKILL.md` (cross-agent delegation). Copilot uses skill names instead of slash commands (see [Copilot section](#copilot) below).

Runs a PR review using the host agent (self-action) or delegates to a target agent (cross-agent). Gets the PR diff and branch context, reads project standards, evaluates correctness, style, testing, security, documentation, architecture, and breaking changes. Presents findings in the format Summary / Findings (Critical / Suggestions / Positive) / Verdict. The user is asked whether to post the review as a PR comment before posting. **Workflow position:** after `implement issue N` opens the PR. **Focus areas:** passing `errors`, `tests`, `types`, or `comments` (comma-separated) as the focus argument runs the matching checklist from [Review Focus Areas](review-focus-areas.md) in addition to the general review; any other text passes through as free-form guidance, and no argument runs the general review unchanged.

### `/multi-adversarial-review <ais...>`

**Args:** one or more agent names (`claude`, `copilot`, `codex`, `antigravity`). **Sources:** `.agents/skills/multi-adversarial-review/SKILL.md` (Codex, Antigravity, Copilot, and the source Claude's copy is generated from), `.claude/skills/multi-adversarial-review/SKILL.md` (Claude, generated by `doit skills_sync`).

Runs each listed agent in an isolated context to independently challenge the current uncommitted changes and the current branch vs `main`. Each agent outputs an adversarial review (Direction Critique / Hidden Assumptions / Failure Modes / Alternatives Worth Considering); all reviews are synthesized into a combined challenge with consensus and per-agent-only findings. A user-approval gate precedes posting. If a PR exists the synthesis is posted as a PR comment; otherwise it is presented in-conversation only. **Workflow position:** optional adversarial challenge on the PR `implement issue N` opened. **Design note:** no agent sees any other agent's output while drafting; every agent other than the one running this skill is invoked in non-interactive mode and writes only to stdout.

### `/multi-plan <ais...> <issue#>`

**Args:** one or more agent names (`claude`, `copilot`, `codex`, `antigravity`) followed by the issue number. **Sources:** `.agents/skills/multi-plan/SKILL.md` (Codex, Antigravity, Copilot, and the source Claude's copy is generated from), `.claude/skills/multi-plan/SKILL.md` (Claude, generated by `doit skills_sync`).

Validates the issue, warns if plan comments already exist, then generates independent plans from each listed agent in isolated contexts. Posts each plan as a separate issue comment, synthesizes a combined plan that highlights agreements and divergences, reviews the synthesis with the user, and only posts the synthesized plan after explicit approval. **Workflow position:** first step of the multi-agent workflow. **Design note:** isolated contexts are mandatory so no agent can see another's output while drafting; the orchestrating agent is the only one that writes to GitHub.

### `/multi-review <ais...>`

**Args:** one or more agent names (`claude`, `copilot`, `codex`, `antigravity`). **Sources:** `.agents/skills/multi-review/SKILL.md` (Codex, Antigravity, Copilot, and the source Claude's copy is generated from), `.claude/skills/multi-review/SKILL.md` (Claude, generated by `doit skills_sync`).

Verifies a PR exists for the current branch, warns if reviews already exist, then generates independent code reviews from each listed agent in isolated contexts. Posts each review as a separate PR comment, synthesizes findings into a combined verdict (consensus findings, per-agent-only findings, combined verdict). A user-approval gate precedes the synthesis post. **Workflow position:** after `implement issue N` opens the PR, in the multi-agent workflow. **Design note:** same isolation guarantee as `/multi-plan` — no reviewer sees another's output; the synthesis is posted after all raw reviews so readers can audit it against the sources.

### `/ghi-status`

**Args:** none. **Sources:** `.agents/skills/ghi-status/SKILL.md` (Codex, Antigravity, Copilot), `.claude/skills/ghi-status/SKILL.md` (Claude, generated by `doit skills_sync`).

Inspects the current git state (branch, uncommitted changes, recent log), extracts the issue number from the branch name if on a feature branch, checks for a plan comment, unpushed commits, and open PRs, then reports a status summary and suggests the next command to run. **Workflow position:** any time. **Design note:** read-only and side-effect-free — safe to run whenever the user is unsure where they are in the lifecycle.

### `/checkpoint <slug>` and `/restore <slug>`

**Args:** optional kebab-case slug. **Sources:** `.agents/skills/checkpoint/SKILL.md`, `.agents/skills/restore/SKILL.md` (Codex, Antigravity, Copilot); `.claude/skills/checkpoint/SKILL.md`, `.claude/skills/restore/SKILL.md` (Claude, generated by `doit skills_sync`).

Pause-and-resume helpers for long-running workstreams. `/checkpoint` writes a paste-ready resumption prompt to `tmp/checkpoints/{inv_epoch}-{slug}.md`; `/restore` reads the matching file and treats its contents as the session's initial instructions. The `inv_epoch` prefix is a 10-digit decreasing integer so default `ls` lists newest first; users see only the slug. If `/restore` is invoked without a slug, it picks the most recent checkpoint. **Naming:** `checkpoint`/`restore` was chosen over `snapshot`/`resume` to avoid collisions with built-in slash commands across all four supported agents (Claude Code, Codex CLI and Copilot CLI all reserve `/resume`).

**Cross-agent portability:** `tmp/checkpoints/` is intentionally shared (not per-agent), so a checkpoint taken in Claude can be restored in Codex or Copilot and vice versa. This is the documented exception to the `tmp/agents/<agent-type>/` rule in `AGENTS.md`. **Workflow position:** any time, independent of the issue lifecycle. **Design note:** checkpoints are immutable once written; the user is expected to verify referenced issues/PRs are still current before acting on stale references. **When to use it:** at the end of a session when work is unfinished and you want a clean handoff into the next session — capture the goal, current branch state, recommended next step, and any user direction or constraints that should bind the future session. Use `/compact <instructions>` to steer native autocompact's own summary when a session is approaching its context limit, and take a manual `/checkpoint` first if you want a record other agents can read.

### `/template-sync [ref]`

**Args:** optional template ref (tag, branch, or commit SHA) to sync *to*; defaults to `main`. **Sources:** `.agents/skills/template-sync/SKILL.md` (Codex, Antigravity, Copilot), `.claude/skills/template-sync/SKILL.md` (Claude, generated by `doit skills_sync`).

Upgrades a downstream project to the latest `pyproject-template`. Refuses to run in the template repo itself. Opens a tracking issue and branch, refreshes the management suite with `bootstrap.py --sync` **before** running `manage.py check` (a stale drift checker misreports drift), triages the diff into adopt / skip / merge-by-hand, batches every open judgment call into one round of questions to the user, then posts the result as a plan comment on the issue under the header `## Sync Plan for #<n>: <ref>` and **stops for the repo admin to approve**. Only after approval does it apply, validate with `doit check`, mark the sync point, and return to the `implement-issue` run, or commit and open a PR per `.github/CONTRIBUTING.md`. **Workflow position:** any time, independent of the issue lifecycle. **Design note:** the plan gate is the point of the command — a sync applied first and explained afterwards is a record, not a decision the admin got to make. `tests/test_template_sync_skill.py` enforces that both bodies carry the same gate sentence and that the gate precedes the apply step.

This command drives the tooling documented in [Template Management](../../template/manage.md) and the procedure in [AI Sync Checklist](../../template/ai-sync-checklist.md); it replaces neither. Read the checklist when a step is ambiguous.

### `/template-migrate [ref]`

**Args:** optional template ref (tag, branch, or commit SHA) to plan against; defaults to `main`. **Sources:** `.agents/skills/template-migrate/SKILL.md` (Codex, Antigravity, Copilot), `.claude/skills/template-migrate/SKILL.md` (Claude, generated by `doit skills_sync`).

Plans an **existing** project's migration onto the template — the step before `/template-sync` has anything to sync. Unlike every other file here it is **standalone**: it is meant to be copied into a project that does not use the template, so it assumes no `doit`, no `tools/pyproject_template/`, no `AGENTS.md`, and no local copy of any template document. It resolves the template ref to a commit, fetches `migration.md`, `consumer-notes.md`, `AGENTS.md`, `python-versions.json` and `pyproject.toml` over raw HTTP (there is no documentation site, so raw URLs are the only online source), inventories the project read-only, batches its open questions to the owner, and writes `TEMPLATE_MIGRATION_PLAN.md` to the repository root. **It changes nothing until the owner approves the plan.**

**Workflow position:** before adopting the template at all; `/template-sync` takes over afterwards. **Design note:** it plans rather than migrates on purpose. #783 deleted an automated migrator because it did the one mechanical step destructively while leaving every judgement step — which package is *the* package, how imports break moving to `src/`, which dependencies survive the merge — untouched. This is the complement to that decision. `tests/test_template_migrate_skill.py` enforces that both bodies fetch rather than read from disk, and that the plan gate precedes the execute step.

**Installing it into another project:**

```bash
# Claude Code
mkdir -p .claude/skills/template-migrate && curl -sSL \
  https://raw.githubusercontent.com/endavis/pyproject-template/main/.agents/skills/template-migrate/SKILL.md \
  -o .claude/skills/template-migrate/SKILL.md

# Codex, Antigravity, or Copilot
mkdir -p .agents/skills/template-migrate && curl -sSL \
  https://raw.githubusercontent.com/endavis/pyproject-template/main/.agents/skills/template-migrate/SKILL.md \
  -o .agents/skills/template-migrate/SKILL.md
```

Both commands fetch the same file — `.agents/skills/` is the single source, and Claude's copy is byte-identical to it (see [Shared workflow skills: one source, generated for Claude](#shared-workflow-skills-one-source-generated-for-claude)).

### `/add-dependency <package> [what it is for]`

**Args:** the package the task needs, optionally followed by what it is for. **Sources:** `.agents/skills/add-dependency/SKILL.md` (Codex, Antigravity, Copilot), `.claude/skills/add-dependency/SKILL.md` (Claude, generated by `doit skills_sync`).

Walks an agent through adding a dependency, which it cannot do alone: the dangerous-command hook blocks every `uv add`. It rules out the standard library and existing dependencies, places the package in `[project] dependencies` or the `dev` or `security` extra, vets its license, supported Python versions, maintenance and typing against PyPI, and hands the user the exact `uv add` command with a `>=` lower bound. **It stops there until the user has run the command.** Afterwards it confirms what landed and adds the `[[tool.mypy.overrides]]` entry an untyped package needs. It then runs `doit licenses`, `doit audit` and `doit check`, and carries the justification into the PR description.

**Workflow position:** mid-task, whenever the work needs a package the project does not have. **Design note:** it applies the policy in [CONTRIBUTING.md — Dependencies](../../../.github/CONTRIBUTING.md#dependencies) rather than restating it. `tests/test_add_dependency_skill.py` enforces that both bodies take the same steps in the same order and carry the same stop and hand-off sentences, and that neither puts `uv add` in a command for the agent to run.

### `/mutation-triage [scope]`

**Args:** an optional scope — a dotted module path or a file under `src/` to triage, optionally followed by specific mutant names already known to survive; empty means every current survivor. **Sources:** `.agents/skills/mutation-triage/SKILL.md` (Codex, Antigravity, Copilot), `.claude/skills/mutation-triage/SKILL.md` (Claude, generated by `doit skills_sync`).

Turns a `doit mutate` survivor, or a `doit coverage` line marked `Missing`, into a behavior test or a documented reason it needs none. For each survivor in scope it inspects the diff with `mutmut show`, classifies it as equivalent, a missing assertion, an untested branch, or a real bug — stopping to report a bug rather than writing a test that pins it — then writes a test for the genuine gaps and re-runs what it targeted, by exact name or by an `fnmatch` pattern, to prove each one is now killed.

**Workflow position:** after `doit mutate` or `doit coverage` finds something worth a second look, before the change that produced it is finalized. **Design note:** both underlying tasks are informational — neither fails on a survivor or an uncovered line — so nothing but this command's own gates stops a survivor being declared equivalent with no reason, or "killed" by a test keyed to the mutated literal instead of real behavior. `tests/test_mutation_triage_skill.py` enforces that both bodies take the same six steps in the same order and carry the same four gate sentences in place.

### `/property-tests <target> [property]`

**Args:** the function or module to test, optionally followed by what property to check. **Sources:** `.agents/skills/property-tests/SKILL.md` (Codex, Antigravity, Copilot), `.claude/skills/property-tests/SKILL.md` (Claude, generated by `doit skills_sync`).

Walks an agent through writing a Hypothesis property test: name the property first (round-trip, idempotence, invariant or oracle, or stop for an example-based test instead), build the strategy from types before reaching for `assume()` or `.filter()`, mark it `@pytest.mark.property`, and leave `deadline` and `max_examples` to the profiles in `tests/conftest.py` rather than a per-test `@settings(...)`. It also breaks the code under test on purpose to confirm the property actually fails, undoes just that break without touching the task's other changes, and -- whenever a property turns up a genuine failing input against the real code -- fixes the bug first and pins that input as `@example(...)`.

**Workflow position:** mid-task, whenever new or changed code needs a property test rather than (or alongside) an example-based one. **Design note:** it defers to the `ci` and `default` profiles already configured in `tests/conftest.py` (#736) instead of restating their values, and its restore step undoes only the deliberate break so it never discards the task's own uncommitted work. A new test file that imports the package also needs adding to mutmut's test selection; see [Which Tests Run](../ci-cd-testing.md#which-tests-run). `tests/test_property_tests_skill.py` enforces that both bodies take the same steps in the same order and carry the same stop and prove-it-can-fail sentences.

### `/deprecate-api deprecate <old-name> <new-name>` / `/deprecate-api remove <old-name>`

**Args:** the phase (`deprecate` or `remove`) and the name or names it applies to. **Sources:** `.agents/skills/deprecate-api/SKILL.md` (Codex, Antigravity, Copilot), `.claude/skills/deprecate-api/SKILL.md` (Claude, generated by `doit skills_sync`).

Retires a public name over two releases instead of breaking callers with no notice. In the `deprecate` phase it keeps the old name exported and routes it to the replacement, warns with `warnings.warn(..., DeprecationWarning, stacklevel=2)` — not `@warnings.deprecated`, since this project's floor (Python 3.12) predates it — requires a `pytest.warns` test in the same change, and documents the replacement in the docstring. In the `remove` phase, a later release, it refuses to delete the name until that deprecating release has already shipped, then deletes it and follows [AGENTS.md — Breaking Changes Policy](../../../AGENTS.md#breaking-changes-policy): a `BREAKING CHANGE:` footer and a migration guide in the PR description, never a hand-edited `CHANGELOG.md` or `pyproject.toml` version — both come from `doit release`.

**Workflow position:** whenever a public name needs to change, in two separate PRs a release apart. **Design note:** pytest's own configuration (`--strict-config --strict-markers`, no `filterwarnings`) does not fail a test merely because code under test raises `DeprecationWarning`, so the `pytest.warns` test is the only thing that catches a shim that silently stops warning — measured against this project's own `tests/test_core.py`. `tests/test_deprecate_api_skill.py` enforces that both bodies take the same phases and steps in the same order and carry the same gate sentences, and that neither body's code examples use `@warnings.deprecated` or `@typing_extensions.deprecated`.

### `/python-version-bump [direction] [version]`

**Args:** the direction and the version, e.g. `newest 3.15` or `floor 3.13`. **Sources:** `.agents/skills/python-version-bump/SKILL.md` (Codex, Antigravity, Copilot), `.claude/skills/python-version-bump/SKILL.md` (Claude, generated by `doit skills_sync`).

The supported Python range is declared in seven places (`requires-python`, ruff `target-version`, mypy `python_version`, pyright `pythonVersion`, `.python-version`, `.github/python-versions.json`'s `oldest`/`newest`, and the PyPI classifiers), and `tests/test_python_versions_agree.py` is the only check that they agree. This command moves the range in either direction. Adding a newest version touches `.github/python-versions.json`, a classifier, and any prose that states the range — no gate, and no `uv lock` since the floor does not move. Raising the floor drops support for the oldest version, so **it asks the user first**, in the same message asking whether the release should carry a `BREAKING CHANGE:` footer and whether the last release still supporting the old floor should be tagged, then changes all seven settings in one commit, regenerates `uv.lock`, rebuilds the environment with `uv sync --all-extras --dev` (the new interpreter's `.venv` comes back without the dev tools), applies the `UP` rewrites `doit lint` reports, removes dead `sys.version_info` branches for the dropped version, updates any other prose that stated the old floor, and runs `doit check`.

**Workflow position:** mid-task, whenever the work is to change which Python versions the project supports. **Design note:** it applies the policy in [CI/CD Testing Guide — Python Version Support Policy](../ci-cd-testing.md#python-version-support-policy) rather than restating it. `tests/test_python_version_bump_skill.py` enforces that both bodies take the same steps in the same order and carry the same ask-first and one-commit sentences.

### `/security-triage [bandit|pip-audit]`

**Args:** optional, which scanner to focus on; empty triages both. **Sources:** `.agents/skills/security-triage/SKILL.md` (Codex, Antigravity, Copilot), `.claude/skills/security-triage/SKILL.md` (Claude, generated by `doit skills_sync`).

Triages a `doit security` (bandit) or `doit audit` (pip-audit) finding instead of letting an agent reach for the fastest suppression. For a bandit finding it fixes the pattern when it can (list-form `subprocess` without `shell=True`, `yaml.safe_load`, a validated path) or justifies it with `# nosec <ID> - <reason>` naming only the IDs reported on that line — **never a bare `# nosec`, and never a new `[tool.bandit] skips` entry without asking.** For a pip-audit finding it upgrades to a fixed version, or assesses reachability when none exists, and **stops to ask before a `--ignore-vuln` advisory is accepted.** It also guards against a false clean result: both scanners need the `security` extra and silently pass without it, and a bandit run scoped to a sample under `tmp/` finds nothing because `[tool.bandit] exclude_dirs` excludes that directory.

**Workflow position:** whenever `doit check`, `doit security` or `doit audit` reports a finding. **Design note:** bandit's `# nosec` convention and pip-audit's advisory handling were unwritten before this skill (#834); it is the policy, not an application of one. `tests/test_security_triage_skill.py` enforces that both bodies take the same steps in the same order and carry the bare-nosec, skips and ignore-vuln gates word for word.

### `/dead-code-triage [finding]`

**Args:** the finding to triage — a `doit deadcode` output line, or a file and line number; empty triages every finding `doit deadcode` reports. **Sources:** `.agents/skills/dead-code-triage/SKILL.md` (Codex, Antigravity, Copilot), `.claude/skills/dead-code-triage/SKILL.md` (Claude, generated by `doit skills_sync`).

Walks an agent through a vulture finding before it deletes code, hides it, or leaves a bug in place. `doit check` runs `doit deadcode` as one of its `task_dep`, so a finding blocks the check, and vulture cannot tell a genuine dead import from one an interface, a framework, or the type checker still needs. It reads `[tool.vulture]` in `pyproject.toml` for the configured threshold and the existing `ignore_names`/`ignore_decorators` exceptions, then branches on the finding's kind: checking string annotations, re-exports and side-effect imports before deleting an unused import; whether a caller or framework imposes an argument's signature before removing or `_`-prefixing it; and whether the statement before unreachable code exits too early before deleting the code after it.

**Workflow position:** whenever `doit check` or `doit deadcode` reports a finding, or the user pastes one. **Design note:** every new `ignore_names` entry must carry a comment naming the reference vulture cannot see, the same shape as the entries already there. `tests/test_dead_code_triage_skill.py` enforces that both bodies take the same steps in the same order and carry the same early-exit and reason-comment gates word for word.

### `/perf-change [target and why]`

**Args:** the function or path to make faster, and why. **Sources:** `.agents/skills/perf-change/SKILL.md` (Codex, Antigravity, Copilot), `.claude/skills/perf-change/SKILL.md` (Claude, generated by `doit skills_sync`).

Turns a performance change into a measured one instead of a claimed one. It confirms `tests/benchmarks/` covers the path being changed (writing a benchmark first if it does not), takes a baseline with `doit benchmark_save`, profiles with the standard library's `cProfile` read through `pstats`, makes the change, then compares with `doit benchmark_compare` and pastes the table into the PR. `doit check` must still pass — a faster wrong answer is a regression.

**Workflow position:** mid-task, whenever the work is a performance change or a speedup claim needs backing. **Design note:** the local `doit benchmark_save` / change / `doit benchmark_compare` loop used to compare against a pinned first save regardless of how many baselines existed (`tools/doit/benchmark.py`); #840 made `--benchmark-compare` use the latest one instead, which is what makes running this loop as-is trustworthy. CI tracks its own benchmark history too (see [CI/CD and Testing — Benchmark Tracking](../ci-cd-testing.md#benchmark-tracking)), but only from pushes to `main` — the workflow's `store` job, the only one that writes history or can comment, is gated on `github.event_name == 'push'`. A PR gets no benchmark comparison from CI, so this loop's pasted table is the only before/after number the PR carries. `tests/test_perf_change_skill.py` enforces that both bodies take the same steps in the same order, carry the same benchmark, comparison and correctness gates word for word, and never tell the agent to pin the comparison to a specific saved run.

### `/merge-pr [N]`

**Args:** the PR number; "N is green", "merge N" and "merge PR N" all invoke it. **Sources:** `.agents/skills/merge-pr/SKILL.md` (Codex, Antigravity, Copilot), `.claude/skills/merge-pr/SKILL.md` (Claude, generated by `doit skills_sync`).

Merges a finished PR and closes the issues it fully addresses. It checks that the PR is open, mergeable, clean and labelled `ready-to-merge`, that every `gh pr checks` job passes or is skipped, and compares each `Addresses #X` issue's success criteria with the diff. It then runs `doit pr_merge --pr=N --auto-close` from the main checkout when every linked issue is fully addressed; otherwise it merges without `--auto-close`, closes only the addressed issues and comments on the rest with what is missing.

**Consent scope:** invoking `merge-pr` is consent to merge that PR and to close the issues it fully addresses. It never adds `ready-to-merge` (the human merge gate), never uses `--admin`, `--force` or `--no-verify`, and stops when a precondition or check fails. **Workflow position:** after the PR is reviewed and the user has added the `ready-to-merge` label. `tests/test_merge_pr_skill.py` enforces the contract.

## Codex

Codex does not use repo-defined slash commands in this project. Instead, the Codex workflow is provided through **repo-scoped skills** under `.agents/skills/`, which Codex can invoke through its built-in `/skills` browser or explicit mentions such as `$implement-issue`, `$codex-review`, and `$ghi-status`.

**Workflow coverage:** the checked-in Codex skills cover taking an issue to a PR, review, and adversarial review. They preserve the same repo artifact contract used by the Claude flow:

- `$implement-issue` (shared skill) decides whether to plan, posts a plan comment with the header `## Implementation Plan for #<n>: <title>` when it does, creates or resumes the issue branch, implements with tests, finishes with `doit check` and `doit docs_build`, commits, pushes, opens the PR with `doit pr`, and fixes CI for up to 3 rounds
- `$codex-review` reviews the current branch's PR and posts findings after user approval
- `$codex-adversarial-review` runs an adversarial challenge review
- `$ghi-status` inspects the current branch, issue, plan comment, uncommitted changes and PR state, and suggests the next step — read-only, no side effects
- `$template-sync` upgrades the project to the latest template, posting a plan on the tracking issue for the admin to approve before applying anything
- `$template-migrate` is the standalone precursor: copied into a project that does not use the template yet, it plans the migration and writes it to `TEMPLATE_MIGRATION_PLAN.md`
- `$add-dependency` prepares a new dependency for the user to approve and install, since the agent cannot run `uv add`, then settles its typing and runs the license and audit checks
- `$mutation-triage` classifies each `doit mutate` survivor or `doit coverage` gap in scope, writes behavior tests for the genuine ones, and re-runs them by name or pattern to prove each is killed
- `$property-tests` names the property a Hypothesis test asserts, builds the strategy from types, proves the test can fail against deliberately broken code, and pins the counterexample
- `$deprecate-api` warns callers off a public name in one release and only removes it in a later one, following the Breaking Changes Policy
- `$python-version-bump` adds a newest supported Python version, or asks first and then raises the
  floor across all seven settings in one commit
- `$security-triage` fixes or justifies each bandit and pip-audit finding, and stops to ask before a `skips` entry or an ignored advisory
- `$dead-code-triage` triages a `doit deadcode` finding against `[tool.vulture]` in `pyproject.toml` — unused import, unused variable, or unreachable code — before fixing it, adding a documented exception, or asking
- `$perf-change` takes a measured baseline before a performance change, profiles with `cProfile`, and compares after, so a speedup claim is backed by a pasted table
- `$merge-pr` merges a PR that is open, clean, green and labelled `ready-to-merge`, then closes the issues it fully addresses and comments on the rest

**Config and safety:** `.codex/config.toml` still configures approvals and hook wiring for Codex. The shared dangerous-command hook at `tools/hooks/ai/block-dangerous-commands.py` applies to Codex, and the approval-policy deny rules remain a secondary defense layer.

**Out of scope for Codex in this project:** no repo-defined custom slash commands, no dual-agent orchestration, and no Codex-specific close-issue automation.

## Antigravity

Antigravity (`agy`) does not use repo-defined slash commands in this project. Instead, the Antigravity workflow is provided through **repo-scoped skills** under `.agents/skills/` (the same directory and `SKILL.md` format Codex uses), which `agy` activates by matching your request against each skill's `description:` frontmatter — there is no slash or `$` prefix.

**Workflow coverage:** the checked-in Antigravity skills cover taking an issue to a PR, review, and adversarial review. They preserve the same repo artifact contract used by the Claude flow:

- The shared `implement-issue` skill decides whether to plan, posts a plan comment with the header `## Implementation Plan for #<n>: <title>` when it does, creates or resumes the issue branch, implements with tests, finishes with `doit check` and `doit docs_build`, commits, pushes, opens the PR with `doit pr`, and fixes CI for up to 3 rounds
- `antigravity-review` reviews the current branch's PR and posts findings after user approval
- `antigravity-adversarial-review` runs an adversarial challenge review
- The shared `ghi-status` skill inspects the current branch, issue, plan comment, uncommitted changes and PR state, and suggests the next step — read-only, no side effects
- The shared `template-sync` skill (from `.agents/skills/`) upgrades the project to the latest template behind an admin review gate
- The shared `template-migrate` skill plans an existing project's move onto the template, changing nothing until the owner approves
- The shared `add-dependency` skill prepares a new dependency for the user to approve and install, then settles its typing and runs the license and audit checks
- The shared `mutation-triage` skill classifies each `doit mutate` survivor or `doit coverage` gap in scope, writes behavior tests for the genuine ones, and re-runs them by name or pattern to prove each is killed
- The shared `property-tests` skill names the property a Hypothesis test asserts, builds the strategy from types, proves the test can fail against deliberately broken code, and pins the counterexample
- The shared `deprecate-api` skill warns callers off a public name in one release and only removes it in a later one, following the Breaking Changes Policy
- The shared `python-version-bump` skill adds a newest supported Python version, or asks first and
  then raises the floor across all seven settings in one commit
- The shared `security-triage` skill fixes or justifies each bandit and pip-audit finding, and stops to ask before a `skips` entry or an ignored advisory
- The shared `dead-code-triage` skill triages a `doit deadcode` finding against `[tool.vulture]` in `pyproject.toml` — unused import, unused variable, or unreachable code — before fixing it, adding a documented exception, or asking
- The shared `perf-change` skill takes a measured baseline before a performance change, profiles with `cProfile`, and compares after, so a speedup claim is backed by a pasted table
- The shared `merge-pr` skill merges a PR that is open, clean, green and labelled `ready-to-merge`, then closes the issues it fully addresses and comments on the rest

**Config and safety:** `.agents/hooks.json` wires the shared dangerous-command hook at `tools/hooks/ai/block-dangerous-commands.py` for Antigravity (a `PreToolUse` matcher on `run_command`, `write_file`, `edit_file` and `write_to_file`). Unlike the exit-code-2 CLIs, `agy` blocks by printing `{"decision":"deny"}` on stdout, which holds even under `--dangerously-skip-permissions`. Because `agy` only loads workspace customizations for an active/trusted workspace, headless `agy -p` invocations must pass `--add-dir <repo-root>`.

**Out of scope for Antigravity in this phase:** cross-agent delegation bridges and multi-agent orchestration for `agy` land in a later phase.

## Copilot

GitHub Copilot CLI discovers project **skills** only from `skills/` directories: `.github/skills/`, `.agents/skills/`, and `.claude/skills/` — plus the corresponding personal paths under `~/` and anything added via `/skills add`. It reads no `.copilot/commands/`; that directory no longer exists in this repo (#975 moved the `multi-*` orchestrators that used to live there into `.agents/skills/`).

It does load **single-file commands** from `.claude/commands/`. That is a separate mechanism from skills — added in CLI 0.0.399, flagged `isCommand` in `sdk/index.d.ts`, and gated by an `enableConfigDiscovery` option that defaults on. Claude's command files surface in a Copilot session as a result (#753).

Because skill names are derived from their directory name and **cannot contain colons**, Copilot's surface for the cross-agent matrix uses `<target>-<action>` (hyphen), not `<target>:<action>` (colon). The functional behavior is identical to the other CLIs — only the slash name differs.

**Self-action and cross-agent skills:** Every cell of the cross-agent matrix for the Copilot host lives under `.github/skills/<target>-<action>/SKILL.md`:

- Self-action: `/copilot-plan`, `/copilot-implement`, `/copilot-review`, `/copilot-adversarial-review`
- To Claude: `/claude-plan`, `/claude-implement`, `/claude-review`, `/claude-adversarial-review`
- To Codex: `/codex-plan`, `/codex-implement`, `/codex-review`, `/codex-adversarial-review`

**Why `.github/skills/` and not `.claude/skills/`?** Copilot reads both, but Claude also reads `.claude/skills/`. Placing the bridges there would surface them as a second set of slash commands in Claude alongside the native `<ai>:<action>` commands — visible noise. `.github/skills/` is read by Copilot but not by Claude (or by Codex), so it's the only Copilot-only project skill path.

**Config directory:** `.copilot/` — established as the Copilot CLI config directory for this repo, parallel to `.claude/`, `.codex/`, and `.agents/`. Note that no `.copilot/commands/<target>/` files are needed (or read).

**Dangerous command hook:** Already wired in `.github/hooks/copilot-hooks.json`. It invokes `tools/hooks/ai/block-dangerous-commands.py` as a `preToolUse` hook, blocking dangerous shell commands before they execute. See [AI Command Blocking](command-blocking.md) for details.

**Implement-worker subagent:** Shared with Claude — defined in `.claude/agents/implement-worker.md`. Copilot CLI's `task` tool reads this file when `/claude-implement` spawns the subagent.

**Known limitation — `delegate-*` skill bleed:** Because Copilot also reads `.agents/skills/`, it surfaces a Codex-only `delegate-<target>-<action>` skill for every (target, action) pair alongside the canonical `<target>-<action>` ones. The Codex-only skills shell out to Codex's syntax and are wasted noise in a Copilot session. Copilot exposes a `disabledSkills` config field (see `~/.copilot/config.json`), but **only at user level — there is no repo-level setting for it.** If you want to silence the delegate-* skills in Copilot, add them to your user config manually:

```json
{
  "disabledSkills": [
    "delegate-claude-review",
    "delegate-claude-adversarial-review",
    "delegate-codex-review",
    "delegate-codex-adversarial-review",
    "delegate-copilot-review",
    "delegate-copilot-adversarial-review",
    "delegate-antigravity-review",
    "delegate-antigravity-adversarial-review"
  ]
}
```

**`.claude/commands/` in Copilot — measured, and smaller than it looks.** Copilot loads single-file
commands from `.claude/commands/`, which raised the question of whether Claude's command surface
bleeds into a Copilot session the way `delegate-*` bleeds the other way. It does not, and the
question is closed (#757). Run `copilot skill list` from the repo root to reproduce:

| | |
| :--- | ---: |
| project entries Copilot lists | 35 |
| from `.github/skills/` | 8 |
| from `.agents/skills/` | 31 |
| **from `.claude/commands/`** | **0** |

**Discovery is not recursive.** Only top-level `*.md` files in `.claude/commands/` are read, and
there are none any more — the three top-level `multi-{plan,review,adversarial-review}.md` files were
the last ones; #975 replaced them with the shared `.agents/skills/multi-*/SKILL.md` files (generated
for Claude by `doit skills_sync`, the same way the other 14 shared skills already were). What is left
under `.claude/commands/` is the nested `<target>/<action>.md` bridge files, and none of those
surface in Copilot either.

The same dedup shadows four `.agents/skills/` entries — the `antigravity-*` and `codex-*`
self-action `review`/`adversarial-review` skills — behind the same-named Copilot bridges in
`.github/skills/`. That is the
desired outcome for a Copilot session, but it depends on precedence rather than on anything the
repo declares, so check `copilot skill list` after renaming a skill.

**Correction:** an earlier version of this note said `disabledSkills` does not cover commands. It
does — a command is loaded into the same collection `isSkillDisabled(name)` filters, which is why
`ghi-status` used to appear in `copilot skill list` through the commands mechanism before #972
moved it to `.agents/skills/`. The claim was inferred from the field name
rather than checked.

## Adding a new slash command

**If the workflow should run the same way under every agent** (Claude, Codex, Antigravity, Copilot), it belongs with the shared skills in [Shared workflow skills: one source, generated for Claude](#shared-workflow-skills-one-source-generated-for-claude): write `.agents/skills/<name>/SKILL.md` with `name:`/`description:` frontmatter and no Claude-only instructions, run `doit skills_sync` to generate its `.claude/skills/<name>/SKILL.md` copy, and add it to `SHARED_SKILLS` in `tools/doit/skills.py`. The rest of this section is for a command written around one specific agent's config surface (`.claude/commands/<name>.md`, `.github/skills/<name>/SKILL.md`), not a shared one — the `multi-*` orchestrators used to be the example of this before #975 made them shared too.

1. **Pick the location.** Claude commands live in `.claude/commands/<name>.md` and become `/<name>` in Claude Code. Copilot CLI discovers **skills** only from `skills/` directories (`.github/skills/`, `.agents/skills/`, `.claude/skills/`) — never from `commands/`, though it does load single-file commands from `.claude/commands/` by a separate mechanism. To expose a Copilot-only command, author it as `.github/skills/<name>/SKILL.md` (with YAML frontmatter) — `.github/skills/` is the only Copilot project skill path that Claude does **not** also read. The slash name becomes `/<name>` because skill names cannot contain colons.
2. **Use the CLI file format** — not the `docs/` frontmatter format. Start with a top-level `# Title` heading, follow with a one-line description (which may include the `$ARGUMENTS` placeholder if the command takes arguments), then a `## Instructions` section containing the step-by-step body. **Do not add YAML frontmatter.** The CLIs expect plain markdown; frontmatter would appear verbatim in the rendered prompt.
3. **Use `$ARGUMENTS` for inputs.** When the user invokes `/<command> foo bar`, every `$ARGUMENTS` occurrence in the file is substituted with `foo bar` before the command body is sent to the model. For a command that takes no arguments, omit the placeholder.
4. **Decide: subagent or main context?** Delegate to a general-purpose subagent via the Task tool when the command does heavy codebase exploration, writes files, or runs long commands whose output would bloat the main conversation — the `implement-issue` skill's Planner and Coder briefs are the canonical example (`.agents/skills/implement-issue/SKILL.md`). Run in the main context when the user needs to interact step by step and the step has no approval wait of its own — `.claude/commands/claude/review.md` is the canonical example.
5. **Update this document** when you add or remove a command. The command reference section should list every file under `.claude/commands/`, and every shared skill under `.agents/skills/`.

## Cross-agent delegation matrix

This project ships a `<target>:<action>` matrix for `review` and `adversarial-review`, where `<target>` can be **the same agent** (self-action) or **any of the other three** (cross-agent delegation). Self-action (`/claude:review`, etc.) and cross-agent delegation (`/codex:review` from Claude, etc.) share the same `<ai>:<action>` naming convention. Planning and implementation are not part of this matrix — they run through the single shared `implement-issue` skill instead (see [implement issue N](#implement-issue-n) above). The full design — convention, file layout, prefix mapping (`/foo` vs `$foo` for Codex), Hybrid C runtime behavior, and the `.agents/skills/` ↔ Copilot conflict mitigation — is documented separately:

→ See [Cross-Agent Delegation Matrix](cross-agent-delegation.md).

Quick reference:

```text
# In Claude Code (colon separator):
/<target>:<action> [args]      # e.g. /codex:review, /antigravity:adversarial-review

# In Copilot CLI (hyphen separator — skill names cannot contain colons):
/<target>-<action> [args]      # e.g. /codex-review, /antigravity-adversarial-review

# In Codex CLI (skills, not slash commands; hyphen separator):
$<target>-<action> [args]              # self-action: $codex-review
$delegate-<target>-<action> [args]     # cross-agent: $delegate-claude-review

# Anywhere, to take an issue to a PR:
implement issue 42                     # natural language, not a slash/$ command
implement issue 42 with codex          # delegates only the coding step to Codex
```

## See also

- [Cross-Agent Delegation Matrix](cross-agent-delegation.md) — convention, matrix, and per-host invocation for the `<target>:<action>` family.
- [First 5 Minutes with an AI Agent](first-5-minutes.md) — narrative onboarding walkthrough showing the workflow end to end.
- [AI Agent Setup Guide](../AI_SETUP.md) — per-CLI configuration and whitelists.
- [Architectural Conventions](architectural-conventions.md) — imperative rules for AI-generated code.
- [AI Enforcement Principles](enforcement-principles.md) — how this project enforces rules in code, not just instructions.
- [AI Command Blocking](command-blocking.md) — tool-level hooks that block dangerous commands.
- [AGENTS.md](../../../AGENTS.md) — universal context file and workflow reference.
