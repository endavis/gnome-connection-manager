#!/usr/bin/env python3
"""
Claude Code PreCompact hook that synthesizes a checkpoint before context compaction.

Triggered when Claude Code is about to compact the conversation context. Reads the
transcript, spawns a headless ``claude -p`` to synthesize a structured checkpoint,
and writes the result to ``tmp/checkpoints/{inv_epoch}-auto-precompact.md``.

The hook is best-effort: any failure (timeout, missing CLI, non-zero exit, JSON parse
failure, missing transcript) falls back to a banner + raw transcript tail tagged
``AUTO_PARTIAL``. Always exits 0 so it never blocks the compaction event.

For full documentation, see: docs/development/ai/auto-checkpoint-hook.md
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess  # nosec B404 - required to invoke claude CLI
import sys
import time
from pathlib import Path

# Maximum transcript bytes to include in the synthesis prompt.
TRANSCRIPT_TAIL_BYTES = 200_000

# Timeout for the synthesis subprocess (seconds). Set to 90 per issue #513 note.
SYNTHESIS_TIMEOUT_SECONDS = 90

# JSON schema the synthesis prompt asks for.
SYNTHESIS_SCHEMA = (
    "{title, status, in_flight_work, constraints, files_touched (array), next_steps, resume_prompt}"
)

# Prompt sent to the headless claude -p call.
SYNTHESIS_PROMPT_TEMPLATE = """\
You are summarizing a coding session for checkpoint/restore. \
Read the transcript excerpt below and produce ONLY a JSON object with EXACTLY these keys \
(no extra prose, no markdown fences, just the raw JSON):

{schema}

Field guidance:
- title: short description of current work (e.g. "Add caching layer to user service")
- status: one-line summary of what has landed recently and what is in-flight
- in_flight_work: detailed description of what is currently being worked on
- constraints: key decisions, preferences, or constraints from this session to preserve
- files_touched: array of file paths that have been created or modified
- next_steps: ordered list of next actions the future session should take
- resume_prompt: a self-contained paste-ready prompt for a future agent session

TRANSCRIPT (last {byte_count} bytes):
{transcript}
""".strip()

# Markdown template for the rendered checkpoint.
CHECKPOINT_TEMPLATE = """\
# Auto-Checkpoint: {title}

> **AUTO-PRECOMPACT** checkpoint written by the PreCompact hook before context compaction.
> Restore with `/restore auto-precompact` in a fresh session.

## Status

{status}

## In-Flight Work

{in_flight_work}

## Constraints to Preserve

{constraints}

## Files Touched

{files_touched}

## Next Steps

{next_steps}

## Resume Prompt

{resume_prompt}
""".strip()


def _inv_epoch() -> str:
    """Return a 10-digit decreasing integer string (newest sorts first)."""
    return f"{9_999_999_999 - int(time.time()):010d}"


def _unique_path(checkpoints_dir: Path, slug: str) -> Path:
    """Return a unique path under *checkpoints_dir* for *slug*.

    On collision (same-second invocation), appends ``-a``, ``-b``, … to the
    epoch prefix until a free name is found.
    """
    epoch = _inv_epoch()
    candidate = checkpoints_dir / f"{epoch}-{slug}.md"
    if not candidate.exists():
        return candidate
    for ch in "abcdefghijklmnopqrstuvwxyz":
        candidate = checkpoints_dir / f"{epoch}-{slug}-{ch}.md"
        if not candidate.exists():
            return candidate
    # Extremely unlikely: fall back to a microsecond suffix.
    candidate = checkpoints_dir / f"{epoch}-{slug}-x{time.time_ns()}.md"
    return candidate


def synthesize_checkpoint(transcript_tail: str) -> dict[str, object] | None:
    """Call headless ``claude -p`` with a synthesis prompt; return parsed JSON or None.

    Returns None immediately when *transcript_tail* is empty (nothing to synthesize).
    """
    if not transcript_tail:
        return None
    prompt = SYNTHESIS_PROMPT_TEMPLATE.format(
        schema=SYNTHESIS_SCHEMA,
        byte_count=len(transcript_tail.encode("utf-8", errors="replace")),
        transcript=transcript_tail,
    )
    try:
        result = subprocess.run(  # nosec B603 B607 - spawns claude CLI for synthesis
            [
                "claude",
                "-p",
                "--bare",
                "--model",
                "claude-sonnet-5",
                prompt,
            ],
            capture_output=True,
            text=True,
            timeout=SYNTHESIS_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            return None
        raw = result.stdout.strip()
        # Strip markdown fences if the model wrapped the JSON anyway.
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(line for line in lines if not line.startswith("```")).strip()
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return None
        return parsed
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    except json.JSONDecodeError:
        return None
    except Exception:  # nosec B110 - hook must never raise
        return None


def _render_checkpoint(data: dict[str, object]) -> str:
    """Render *data* dict into the markdown checkpoint format."""
    files_touched = data.get("files_touched", [])
    if isinstance(files_touched, list):
        files_str = "\n".join(f"- {f}" for f in files_touched) or "_none recorded_"
    else:
        files_str = str(files_touched)

    return CHECKPOINT_TEMPLATE.format(
        title=data.get("title", "Unknown"),
        status=data.get("status", "_not recorded_"),
        in_flight_work=data.get("in_flight_work", "_not recorded_"),
        constraints=data.get("constraints", "_none recorded_"),
        files_touched=files_str,
        next_steps=data.get("next_steps", "_not recorded_"),
        resume_prompt=data.get("resume_prompt", "_not recorded_"),
    )


def _fallback_checkpoint(transcript_tail: str, reason: str) -> str:
    """Return an AUTO_PARTIAL checkpoint with a raw transcript tail."""
    return (
        f"# Auto-Checkpoint (AUTO_PARTIAL)\n\n"
        f"> **AUTO_PARTIAL**: synthesis failed ({reason}). "
        f"Raw transcript tail follows.\n\n"
        f"## Raw Transcript Tail\n\n"
        f"```\n{transcript_tail}\n```"
    )


def _read_transcript_tail(transcript_path: str) -> str | None:
    """Read and return the tail of the JSONL transcript file, or None on error."""
    try:
        path = Path(transcript_path)
        if not path.is_file():
            return None
        size = path.stat().st_size
        if size == 0:
            return ""
        with path.open("rb") as fh:
            if size > TRANSCRIPT_TAIL_BYTES:
                fh.seek(size - TRANSCRIPT_TAIL_BYTES)
            raw_bytes = fh.read()
        return raw_bytes.decode("utf-8", errors="replace")
    except (OSError, PermissionError):
        return None
    except Exception:  # nosec B110 - defensive
        return None


def main() -> int:
    """Hook entry point. Always returns 0; tests call this directly."""
    try:
        try:
            input_data = json.load(sys.stdin)
        except (json.JSONDecodeError, ValueError):
            return 0

        if not isinstance(input_data, dict):
            return 0

        cwd = input_data.get("cwd", "")
        transcript_path = input_data.get("transcript_path", "")

        # Determine project root (cwd or CLAUDE_PROJECT_DIR).
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "") or cwd
        if not project_dir:
            return 0

        checkpoints_dir = Path(project_dir) / "tmp" / "checkpoints"
        try:
            checkpoints_dir.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError):
            return 0

        # Read transcript tail.
        transcript_tail: str = ""
        if transcript_path:
            tail = _read_transcript_tail(transcript_path)
            if tail is not None:
                transcript_tail = tail
            # If tail is None (file missing/unreadable), proceed with empty tail → fallback.

        # Synthesize checkpoint (always attempt; returns None on empty/failure).
        synthesized: dict[str, object] | None = synthesize_checkpoint(transcript_tail)

        # Render content.
        if synthesized is not None:
            try:
                content = _render_checkpoint(synthesized)
            except Exception:  # nosec B110 - defensive render failure
                content = _fallback_checkpoint(transcript_tail, "render error")
        else:
            reason = "synthesis returned None" if transcript_tail else "no transcript"
            content = _fallback_checkpoint(transcript_tail, reason)

        # Write the checkpoint file.
        out_path = _unique_path(checkpoints_dir, "auto-precompact")
        with contextlib.suppress(OSError, PermissionError):
            out_path.write_text(content, encoding="utf-8")

    except Exception:  # hook must never raise
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
