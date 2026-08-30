# Adversarial Review via Antigravity

Delegate a steerable adversarial review of the current changes to Antigravity CLI (`agy`). Optional focus: $ARGUMENTS

## Instructions

Use the Bash tool to invoke Antigravity non-interactively. Adversarial review challenges direction, not just code details. `agy` needs `--add-dir` pointed at the repo root so it loads the workspace (and the shared dangerous-command hook); `--dangerously-skip-permissions` auto-approves routine tools while that hook still hard-blocks unsafe ones.

```bash
agy -p 'Run an adversarial review of the current uncommitted changes and the current branch vs main. Read-only. If an Antigravity adversarial-review skill (antigravity-adversarial-review) is available, use it. Otherwise be skeptical and steerable: pressure-test design choices, hidden assumptions, tradeoffs, alternative approaches, failure modes (auth, data loss, races, rollback, reliability). 1) Run `git status`, `git diff`, `git log main..HEAD`. 2) Read AGENTS.md and related ADRs. 3) Ask: was this the right approach? Would a different design be safer or simpler? What edge cases are missed? 4) Print findings to stdout in a structured format (Direction Critique / Hidden Assumptions / Failure Modes / Alternatives Worth Considering). Do NOT modify any files. Focus area (optional): $ARGUMENTS' --dangerously-skip-permissions --add-dir "$(git rev-parse --show-toplevel)"
```

After Antigravity returns:
- Summarize the adversarial findings. This is a *challenge* — the user decides whether to accept, defer, or push back.
- Do not auto-apply suggestions.
