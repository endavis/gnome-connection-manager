# Adversarial Review via Copilot

Delegate a steerable adversarial review to GitHub Copilot CLI — pressure-tests design choices, assumptions, and alternative approaches. Optional focus: $ARGUMENTS.

## Instructions

Use the Bash tool to invoke Copilot non-interactively. Copilot requires `--allow-all` for non-interactive mode. Adversarial review challenges direction, not just code details.

```bash
copilot --allow-all -p 'Run an adversarial review of the current uncommitted changes and the current branch vs main. Read-only. Be skeptical and steerable: pressure-test design choices, hidden assumptions, tradeoffs, alternative approaches, failure modes (auth, data loss, races, rollback, reliability). 1) Run `git status`, `git diff`, `git log main..HEAD`. 2) Read AGENTS.md and related ADRs. 3) Ask: was this the right approach? Would a different design be safer or simpler? What edge cases are missed? What hidden coupling exists? 4) Print findings to stdout in a structured format (Direction Critique / Hidden Assumptions / Failure Modes / Alternatives Worth Considering). Do NOT modify any files. Focus area (optional): $ARGUMENTS'
```

After Copilot returns:
- Summarize the adversarial findings to the user.
- This is a *challenge* — the user decides whether to accept, defer, or push back.
- Do not auto-apply suggestions.
