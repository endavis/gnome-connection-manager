# Implement via Antigravity

Delegate implementation of GitHub issue #$ARGUMENTS to Antigravity CLI (`agy`).

## Instructions

Use the Bash tool to invoke Antigravity non-interactively. The prompt asks `agy` to use its Antigravity implementation skill if available, otherwise to follow the equivalent inline workflow. `agy` needs `--add-dir` pointed at the repo root so it loads the workspace (and the shared dangerous-command hook); `--dangerously-skip-permissions` auto-approves routine tools while that hook still hard-blocks unsafe ones.

```bash
agy -p 'Implement GitHub issue #$ARGUMENTS in the current repository. If an Antigravity implementation skill (antigravity-implement) is available, use it. Otherwise, follow this workflow: 1) Read the plan comment from issue #$ARGUMENTS via `gh issue view $ARGUMENTS --json comments`. 2) Read AGENTS.md for branch naming and commit conventions. 3) Create or check out the branch `<type>/$ARGUMENTS-<slug>` (do not commit to main). 4) Implement the changes per the plan. 5) Run `doit check` to validate. Do NOT push the branch or open a PR — the user reviews first.' --dangerously-skip-permissions --add-dir "$(git rev-parse --show-toplevel)"
```

After Antigravity returns:
- Summarize what was implemented and the `doit check` result.
- Show the user the changed files (`git status`, `git diff --stat`).
- Do not push or open a PR yourself — the user reviews first.
