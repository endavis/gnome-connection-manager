# Plan via Copilot

Delegate planning for GitHub issue #$ARGUMENTS to GitHub Copilot CLI.

## Instructions

Use the Bash tool to invoke Copilot non-interactively. Copilot requires `--allow-all` for non-interactive mode. Hybrid C: prefer the existing `/copilot-plan` skill if available, otherwise inline workflow. Copilot uses hyphen naming for skills because skill names cannot contain colons.

```bash
copilot --allow-all -p 'Plan the implementation for GitHub issue #$ARGUMENTS in the current repository. If the /copilot-plan skill is available, activate it for this issue. Otherwise, follow this workflow: 1) Run `gh issue view $ARGUMENTS --json title,body,labels` to read the issue. 2) Read AGENTS.md to understand the workflow and conventions. 3) Explore the relevant files. 4) Draft a plan with three sections: Implementation Plan, Test Plan, Validation Plan. 5) Print the full plan to stdout. Do NOT post a comment to the issue — the user reviews and posts.'
```

After Copilot returns:
- Summarize the plan to the user.
- If the user wants revisions, invoke Copilot again with their feedback appended to the prompt.
- Do not post the plan as a comment yourself — the user owns that step.
