# Adversarial Review via Copilot

Delegate a steerable adversarial review to GitHub Copilot CLI — pressure-tests design choices, assumptions, and alternative approaches. Optional focus: $ARGUMENTS.

## Instructions

Resolve the configured model first: `uv run doit agent_cmd --role=adversarial_review --host=claude --cli=copilot`. Its last stdout line is JSON with `mode: cli` and a `command` string. Run that `command` in place of the literal invocation below, replacing `'<prompt>'` with the prompt text from the literal. If the task is unavailable or fails, run the literal below as is; with no config the two are identical. See [Agent roles](../../../docs/development/ai/agent-roles.md).

Use the Bash tool to invoke Copilot non-interactively. Copilot requires `--allow-all` for non-interactive mode. Adversarial review challenges direction, not just code details.

```bash
GITHUB_COPILOT_PROMPT_MODE_REPO_HOOKS=true copilot --allow-all -p 'Run an adversarial review of the current uncommitted changes and the current branch vs main. Read-only. Be skeptical and steerable: pressure-test design choices, hidden assumptions, tradeoffs, alternative approaches, failure modes (auth, data loss, races, rollback, reliability). 1) Run `git status`, `git diff`, `git log main..HEAD`. 2) Read AGENTS.md and related ADRs. 3) Ask: was this the right approach? Would a different design be safer or simpler? What edge cases are missed? What hidden coupling exists? 4) Print findings to stdout in a structured format (Direction Critique / Hidden Assumptions / Failure Modes / Alternatives Worth Considering). Do NOT modify any files. Focus area (optional): $ARGUMENTS. If the focus area names any of `errors`, `tests`, `types`, `comments`, read `docs/development/ai/review-focus-areas.md` and apply those checklists in addition to the general review.'
```

After Copilot returns:
- Summarize the adversarial findings to the user.
- This is a *challenge* — the user decides whether to accept, defer, or push back.
- Do not auto-apply suggestions.
