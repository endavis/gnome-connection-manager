# Review via Codex

Delegate a read-only code review of the current changes to Codex CLI. Optional focus area: $ARGUMENTS.

## Instructions

Resolve the configured model first: `uv run doit agent_cmd --role=review --host=claude --cli=codex`. Its last stdout line is JSON with `mode: cli` and a `command` string. Run that `command` in place of the literal invocation below, replacing `'<prompt>'` with the prompt text from the literal. If the task is unavailable or fails, run the literal below as is; with no config the two are identical. See [Agent roles](../../../docs/development/ai/agent-roles.md).

Use the Bash tool to invoke Codex non-interactively. The prompt is fully inlined and reads only
`git`/local files — no `gh` call, so the review needs nothing from `.codex/rules/gh.rules` (#985).

```bash
codex -a never --dangerously-bypass-hook-trust exec 'Review the current uncommitted changes and the current branch vs main, read-only. 1) Run `git status` and `git diff` to see what changed. 2) Run `git log main..HEAD --oneline` for branch context. 3) Read AGENTS.md and any relevant ADRs in docs/decisions/. 4) Identify correctness issues, risks, missing tests, style/convention violations, and concrete suggestions. 5) Print findings to stdout in a structured format (Summary / Issues / Suggestions). Do NOT modify any files. Focus area (optional): $ARGUMENTS. If the focus area names any of `errors`, `tests`, `types`, `comments`, read `docs/development/ai/review-focus-areas.md` and apply those checklists in addition to the general review.' < /dev/null
```

After Codex returns:
- First, treat output containing `DELEGATION-ERROR:` as a failed run and report it instead of summarizing.
- Summarize the review findings to the user.
- Highlight any blocking issues vs nits.
- The user decides what to act on; do not auto-apply suggestions.
