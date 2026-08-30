# Implement via Codex

Delegate implementation of GitHub issue #$ARGUMENTS to Codex CLI.

## Instructions

Use the Bash tool to invoke Codex non-interactively. Hybrid C: prefer the existing `$codex-implement` skill if available, otherwise inline workflow.

```bash
codex -a never --dangerously-bypass-hook-trust exec 'Implement GitHub issue #$ARGUMENTS in the current repository. If the $codex-implement skill is available, activate it for this issue. Otherwise, follow this workflow: 1) Read the plan comment from issue #$ARGUMENTS via `gh issue view $ARGUMENTS --json comments`. 2) Read AGENTS.md for branch naming and commit conventions. 3) Create or check out the branch `<type>/$ARGUMENTS-<slug>` (do not commit to main). 4) Implement the changes per the plan. 5) Run `doit check` to validate. Do NOT push the branch or open a PR — the user reviews first.'
```

After Codex returns:
- Summarize what was implemented and the `doit check` result.
- Show the user the changed files (`git status`, `git diff --stat`) so they can review.
- Do not push or open a PR yourself.
