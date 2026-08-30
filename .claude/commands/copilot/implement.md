# Implement via Copilot

Delegate implementation of GitHub issue #$ARGUMENTS to GitHub Copilot CLI.

## Instructions

Use the Bash tool to invoke Copilot non-interactively. Copilot requires `--allow-all` for non-interactive mode. Hybrid C: prefer the existing `/copilot-implement` skill if available, otherwise inline workflow. Copilot uses hyphen naming for skills because skill names cannot contain colons.

```bash
copilot --allow-all -p 'Implement GitHub issue #$ARGUMENTS in the current repository. If the /copilot-implement skill is available, activate it for this issue. Otherwise, follow this workflow: 1) Read the plan comment from issue #$ARGUMENTS via `gh issue view $ARGUMENTS --json comments`. 2) Read AGENTS.md for branch naming and commit conventions. 3) Create or check out the branch `<type>/$ARGUMENTS-<slug>` (do not commit to main). 4) Implement the changes per the plan. 5) Run `doit check` to validate. Do NOT push the branch or open a PR — the user reviews first.'
```

After Copilot returns:
- Summarize what was implemented and the `doit check` result.
- Show the user the changed files (`git status`, `git diff --stat`) so they can review.
- Do not push or open a PR yourself.
