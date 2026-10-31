# Review via Antigravity

Delegate a read-only code review of the current changes to Antigravity CLI (`agy`). Optional focus: $ARGUMENTS

## Instructions

Resolve the configured model first: `uv run doit agent_cmd --role=review --host=claude --cli=antigravity`. Its last stdout line is JSON with `mode: cli` and a `command` string. Run that `command` in place of the literal invocation below, replacing `'<prompt>'` with the prompt text from the literal. If the task is unavailable or fails, run the literal below as is; with no config the two are identical. See [Agent roles](../../../docs/development/ai/agent-roles.md).

Use the Bash tool to invoke Antigravity non-interactively. The prompt asks `agy` to use its Antigravity review skill if available, otherwise to follow the equivalent inline workflow. `agy` needs `--add-dir` pointed at the repo root so it loads the workspace (and the shared dangerous-command hook); `--dangerously-skip-permissions` auto-approves routine tools while that hook still hard-blocks unsafe ones.

```bash
agy -p 'Review the current uncommitted changes and the current branch vs main, read-only. If an Antigravity review skill (antigravity-review) is available, use it. Otherwise: 1) Run `git status` and `git diff`. 2) Run `git log main..HEAD --oneline` for branch context. 3) Read AGENTS.md and any relevant ADRs in docs/decisions/. 4) Identify correctness issues, risks, missing tests, style/convention violations, and concrete suggestions. 5) Print findings to stdout in a structured format (Summary / Issues / Suggestions). Do NOT modify any files. Focus area (optional): $ARGUMENTS. If the focus area names any of `errors`, `tests`, `types`, `comments`, read `docs/development/ai/review-focus-areas.md` and apply those checklists in addition to the general review.' --dangerously-skip-permissions --add-dir "$(git rev-parse --show-toplevel)"
```

After Antigravity returns:
- Summarize the review findings, highlighting blocking issues vs nits.
- Do not auto-apply suggestions — the user decides what to act on.
