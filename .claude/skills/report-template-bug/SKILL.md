---
name: report-template-bug
description: Use when, in a project made from pyproject-template, you find a bug in template-shipped tooling (`tools/doit/`, `tools/hooks/`, AI agent config, skills), or when the user says "report this upstream". Confirms the bug is upstream's by diffing the local file against the template at the recorded commit, reproduces it, checks whether a newer template already fixes it, looks for a duplicate, stops on a security finding, and files it with `doit issue --upstream`. Never patches the template file silently and never runs `gh issue create`.
---

# Report a Template Bug

File a bug in template-shipped tooling on the template repository, `endavis/pyproject-template`,
instead of patching it locally where the fix drifts and is lost on the next sync.

## When to use

- You are in a project made from the template and a file the template shipped misbehaves:
  `tools/doit/`, `tools/hooks/`, the AI agent configuration, or a skill.
- The user says "report this upstream".

Not for a bug in this project's own code, and not for a feature request.

## Instructions

### Step 0: Refuse in the template repository

Run `gh repo view --json nameWithOwner --jq .nameWithOwner`. If it prints
`endavis/pyproject-template`, this is the template itself and there is no upstream: stop and file
with `doit issue` as usual. `doit issue --upstream` refuses there too.

### Step 1: Confirm it is upstream's bug

Read the recorded commit: `[template].commit` in `.config/pyproject_template/settings.toml`. Fetch
the file as it was at that commit and diff it with the local copy:

```bash
gh api -H "Accept: application/vnd.github.raw+json" "repos/endavis/pyproject-template/contents/<path>?ref=<sha>" > tmp/agents/<agent>/upstream-copy.txt
diff tmp/agents/<agent>/upstream-copy.txt <path>
```

A difference is a local customization, which makes it this project's own bug: stop. With no
recorded commit, say so and ask the user before going on.

### Step 2: Reproduce it

Reproduce the failure and keep the exact command and its output. A claim without pasted output is
inference; say so or go measure it (the `verified-claims` rule).

### Step 3: Check the template version

Compare the recorded commit with upstream `main`. If it is behind, the bug may already be fixed:
look for the fix upstream, and when there is one suggest the `template-sync` skill before filing.

### Step 4: Look for a duplicate

```bash
gh issue list -R endavis/pyproject-template --state all --search "<keywords>"
```

If an issue already covers it, add the reproduction as a comment on that issue (ask the user to
confirm the comment) instead of filing a new one.

### Step 5: Stop on a security finding

If the bug is a security finding (a vulnerability, a hook bypass, an injection, a leaked secret),
file nothing public. Draft the report to a local file under `tmp/agents/<agent>/` and stop for the
user, who submits it by the template's security policy,
`https://github.com/endavis/pyproject-template/security/policy`. `doit issue --upstream` also
refuses security-related content.

### Step 6: File it

Write the body with the sections of the upstream bug template, then:

```bash
uv run doit issue --upstream --type=bug --title="bug: <subject>" --body-file=tmp/agents/<agent>/upstream-issue.md
```

The command validates the body against the upstream template, applies its labels, adds a footer
with the recorded template commit and prints the issue URL. Add `--include-origin` only if the
user asks to name this project; it may be private. If validation fails, fix the body: do not file
by hand.

### Step 7: Leave the local file alone

Do not silently patch the template file. Wait for the upstream fix and re-sync with
`template-sync`. If the user wants a stopgap, make a clearly marked local change that links the
upstream issue, so the next sync can drop it.

Delete the files you wrote under `tmp/agents/<agent>/` when done.
