# Checkpoint

Capture a resumption prompt for picking up the current work later.

When invoked, write a self-contained prompt to `tmp/checkpoints/` so the user (or a future agent session via `/restore`) can pick up where they left off without re-reading the current conversation. This is the **save** side of the checkpoint/restore pair — `/restore` is the load side.

Argument: `$ARGUMENTS` — optional kebab-case slug describing the topic. If empty, infer a 3-5 word descriptive slug from the conversation context.

## Instructions

### Step 1: Compute the filename

Filename format: `{inv_epoch}-{slug}.md` in `tmp/checkpoints/`.

`inv_epoch` is a 10-digit integer that *decreases* as time advances, so default `ls` (no flags) lists newest entries first. Compute:

```bash
INV_EPOCH=$(printf '%010d' $((9999999999 - $(date +%s))))
```

(The prefix is for sort order only; users read the slug and file contents, not the number.)

Run `mkdir -p tmp/checkpoints` before writing. Don't overwrite existing files; if a same-named file exists, append a 1-letter discriminator (`-a`, `-b`, …) to the slug.

> Note: this directory deviates from the `tmp/agents/<agent-type>/` convention in `AGENTS.md`. `tmp/checkpoints/` is intentionally shared (not per-agent) so checkpoints are portable across agents — Claude can write a checkpoint and Codex or Copilot can restore from it.

### Step 2: Draft the prompt

The prompt must be **paste-ready** — readable cold by a future agent session that has zero context from this conversation. Use absolute references throughout: issue/PR numbers, file paths, ISO dates (no "yesterday"/"this morning").

Structure:

- **Title** — short description of what's deferred.
- **Paste-block intro** — one line telling the future user what to do (paste into a fresh agent session at the repo's working directory).
- **Status as of {today's ISO date}** — what landed recently (merged PRs and closed issues with brief descriptions), current branch state, anything in-flight.
- **Open issues** (if any are filed but not started) — number, title, one-line scope.
- **Goal** — the bigger-picture objective this work serves.
- **Pick: option N (the recommendation)** — list 2-3 numbered next-step options. Mark the recommendation. Brief tradeoff notes.
- **User direction recorded** — decisions, preferences, or constraints surfaced in the current conversation that future sessions need to honor (e.g., "no cross-provider X", "always prefer Y pattern").
- **Pre-action reads** — files/docs the future session should read before starting, scoped per option.
- **Workflow** — short reminder of project conventions (Issue → Branch → PR per `AGENTS.md`, etc.).
- **Start by:** — concrete first command (e.g., `/<currentai>:plan 714`, or `git checkout main && git pull`).

Add anything else load-bearing — open blockers, runtime gotchas, manual prerequisite steps. Keep tight; this is a paste-block, not a doc.

Don't dump conversation history. Don't include `.claude/scheduled_tasks.lock` or other local-environment ephemera. Don't restate `MEMORY.md` content (it's auto-loaded in future sessions).

### Step 3: Confirm to the user

Report:
- The full path to the created file.
- A one-line summary of what's captured.
- The quick-use reminder: "paste the file contents into a fresh agent session at this repo's root."

## Notes

- Files persist; no auto-cleanup. The user can `rm` old prompts manually when they're stale.
- If invoked multiple times in one session, write a new file each time. The user may want separate resumption-points for separate work threads.
- The prefix uses 10 digits because epoch will exceed 10 digits in the year 2286; that's fine for foreseeable use. If you ever need to extend, bump to 11+ digits.
- The companion `/restore` command loads a captured checkpoint in a future session — point users to it.
