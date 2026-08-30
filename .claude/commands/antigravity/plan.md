# Plan via Antigravity

Delegate planning for GitHub issue #$ARGUMENTS to Antigravity CLI (`agy`).

## Instructions

Use the Bash tool to invoke Antigravity non-interactively. The prompt asks `agy` to use its Antigravity planning skill if available, otherwise to follow the equivalent inline workflow. `agy` needs `--add-dir` pointed at the repo root so it loads the workspace (and the shared dangerous-command hook); `--dangerously-skip-permissions` auto-approves routine tools while that hook still hard-blocks unsafe ones.

```bash
agy -p 'Plan the implementation for GitHub issue #$ARGUMENTS in the current repository. If an Antigravity planning skill (antigravity-plan) is available, use it for this issue. Otherwise, follow this workflow: 1) Run `gh issue view $ARGUMENTS --json title,body,labels` to read the issue. 2) Read AGENTS.md to understand the workflow and conventions. 3) Explore the relevant files. 4) Draft a plan with three sections: Implementation Plan, Test Plan, Validation Plan. 5) Print the full plan to stdout. Do NOT post a comment to the issue — the user reviews and posts.' --dangerously-skip-permissions --add-dir "$(git rev-parse --show-toplevel)"
```

After Antigravity returns:
- Summarize the plan to the user.
- If the user wants revisions, invoke Antigravity again with their feedback appended to the prompt.
- Do not post the plan as a comment yourself — the user owns that step.
