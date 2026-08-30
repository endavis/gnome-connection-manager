---
name: restore
description: Load a previously captured checkpoint prompt and continue the work it describes.
---

# Restore

Load a previously captured checkpoint prompt from `tmp/checkpoints/` and continue the work it describes.

## When to use

Use this skill when the user wants to pick up a previously captured checkpoint in a fresh Codex session. This is the **load** side of the checkpoint/restore pair — `$checkpoint` is the save side.

Expected prompt shape:

- `$restore restore the latest checkpoint`
- `$restore restore work tagged plan-test`

The user supplies an optional kebab-case `<slug>` to filter by. If the slug is missing, pick the most recent checkpoint regardless of slug.

## Instructions

### Step 1: Find the checkpoint file

Files live in `tmp/checkpoints/` with names like `{inv_epoch}-<slug>.md`. The `inv_epoch` prefix is monotonically *decreasing* in time, so the lexically smallest filename is the most recent.

```bash
mkdir -p tmp/checkpoints  # idempotent
```

**If no slug was supplied:** pick the lexically first file in the directory (newest).

```bash
ls tmp/checkpoints/*.md 2>/dev/null | head -1
```

**If a slug was supplied:** treat it as a slug fragment. Pick the lexically first file whose name matches `*-<slug>*.md`.

```bash
ls tmp/checkpoints/*-<slug>*.md 2>/dev/null | head -1
```

(Lexically-first = newest, because of the inv_epoch convention.)

### Step 2: Handle edge cases

- **Directory empty or missing:** tell the user `tmp/checkpoints/` has no checkpoints; suggest `$checkpoint <slug>` to capture one. Stop.
- **No match for the slug:** list available checkpoint filenames so the user can pick one. Stop and wait.
- **Multiple matches:** silently pick the newest, but mention how many were considered and offer to load a different one if asked.

### Step 3: Load and act on the checkpoint

1. Read the chosen file.
2. Print a one-line confirmation: `Restoring from {filename} (<slug>, captured {date if discoverable})`.
3. **Treat the file's contents as if the user had pasted them as their first message.** Follow the instructions inside — most checkpoints end with a "Start by:" line that names a concrete first action; do that. If the checkpoint has multiple "Pick" options, default to the recommended one unless the user said otherwise.
4. Don't summarize the checkpoint back to the user before acting — they already wrote it. Just proceed. (Exception: if the checkpoint is ambiguous about the next step, ask once before acting.)

### Step 4: Honor any "User direction recorded" or constraints in the checkpoint

Checkpoints typically capture decisions and preferences from the prior session. Treat them as binding for this session unless explicitly overridden in the user's current message.

## Notes

- Checkpoints are immutable once written. If the situation has changed since capture (a referenced PR landed, an issue closed, etc.), verify before acting on stale references — `gh issue view <n>`, `git log`, etc.
- The companion `$checkpoint` skill writes new checkpoints — point users to it if they want to capture something for later in this session.
- The `inv_epoch` prefix is a sort-only artifact; the user reads the slug, not the number. Always show the slug (or full filename) in confirmation messages, not just the prefix.
