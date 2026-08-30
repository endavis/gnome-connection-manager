# Review via Copilot

Delegate a read-only code review of the current changes to GitHub Copilot CLI. Optional focus area: $ARGUMENTS.

## Instructions

Use the Bash tool to invoke Copilot non-interactively. Copilot requires `--allow-all` for non-interactive mode. The review prompt is inlined directly.

```bash
copilot --allow-all -p 'Review the current uncommitted changes and the current branch vs main, read-only. 1) Run `git status` and `git diff` to see what changed. 2) Run `git log main..HEAD --oneline` for branch context. 3) Read AGENTS.md and any relevant ADRs in docs/decisions/. 4) Identify correctness issues, risks, missing tests, style/convention violations, and concrete suggestions. 5) Print findings to stdout in a structured format (Summary / Issues / Suggestions). Do NOT modify any files. Focus area (optional): $ARGUMENTS'
```

After Copilot returns:
- Summarize the review findings to the user.
- Highlight any blocking issues vs nits.
- The user decides what to act on; do not auto-apply suggestions.
