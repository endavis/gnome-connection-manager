"""Pinned Claude model IDs must be current and must agree with the docs.

A model pin in a *template* is different from a pin in an ordinary repo: every
project spawned from it inherits the value, and nothing in the update-checking
machinery looks at model IDs. `CLAUDE_CODE_SUBAGENT_MODEL` sat at
`claude-sonnet-4-6` for two model generations, and the same stale ID had spread
into `precompact-checkpoint.py`, which passes it to a live `claude -p`
invocation (#696).

The pin itself is deliberate — `AI_SETUP.md` records it as a cost/quality
trade-off, with `implement-worker` intentionally not overriding it. So these
tests do not forbid pinning. They make a *stale* pin loud.

Two properties are checked:

1. **Currency** — every pinned ID is in `CURRENT_MODEL_IDS` below. That list is
   the single place a model-family change has to be applied; the test failing
   is how the change surfaces at all.
2. **Consistency** — `.claude/settings.json` and the `AI_SETUP.md` table quote
   the same ID. This one needs no maintenance and catches the two drifting
   apart, which is how the docs came to describe a value nobody had checked.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SETTINGS = REPO_ROOT / ".claude" / "settings.json"
AI_SETUP = REPO_ROOT / "docs" / "development" / "AI_SETUP.md"

# Update when the Claude model family changes. Deliberately a short list rather
# than a pattern: a regex for "looks like a model ID" would have happily
# accepted claude-sonnet-4-6 forever.
CURRENT_MODEL_IDS = frozenset(
    {
        "claude-opus-5",
        "claude-sonnet-5",
        "claude-fable-5",
        "claude-haiku-4-5-20251001",
    }
)

# Any `claude-<family>-<version>` token, so a stale ID is found wherever it hides.
_MODEL_RE = re.compile(r"claude-(?:opus|sonnet|haiku|fable)-[0-9][0-9a-z-]*")

# Files that legitimately name a model ID.
_SCANNED = (
    SETTINGS,
    AI_SETUP,
    REPO_ROOT / "tools" / "hooks" / "ai" / "precompact-checkpoint.py",
    REPO_ROOT / "docs" / "development" / "ai" / "auto-checkpoint-hook.md",
)


def _subagent_pin() -> str:
    """The subagent model pinned in `.claude/settings.json`."""
    env = json.loads(SETTINGS.read_text(encoding="utf-8")).get("env", {})
    pin = env.get("CLAUDE_CODE_SUBAGENT_MODEL")
    assert pin, "CLAUDE_CODE_SUBAGENT_MODEL is absent from .claude/settings.json"
    return str(pin)


@pytest.mark.parametrize("path", _SCANNED, ids=lambda p: p.name)
def test_model_ids_are_current(path: Path) -> None:
    """No file may name a model outside the current family."""
    stale = sorted(set(_MODEL_RE.findall(path.read_text(encoding="utf-8"))) - CURRENT_MODEL_IDS)
    assert not stale, (
        f"{path.name} names non-current model IDs: {stale}\n"
        "Update them, or add the new family to CURRENT_MODEL_IDS in this test."
    )


def test_settings_and_docs_quote_the_same_pin() -> None:
    """The documented subagent model must match the one actually shipped.

    Needs no maintenance, unlike the currency check: it fails whenever the two
    drift, whatever the current model happens to be.
    """
    pin = _subagent_pin()
    row = re.search(
        r"^\| `CLAUDE_CODE_SUBAGENT_MODEL` \| `([^`]+)` \|",
        AI_SETUP.read_text(encoding="utf-8"),
        re.M,
    )
    assert row, "AI_SETUP.md no longer documents CLAUDE_CODE_SUBAGENT_MODEL in its env table"
    assert row.group(1) == pin, (
        f"settings.json pins {pin!r} but AI_SETUP.md documents {row.group(1)!r}"
    )


def test_the_scanner_actually_finds_model_ids() -> None:
    """Guard against the pattern silently matching nothing.

    Without this, a regex change could make every assertion above pass
    vacuously — the same silent-success shape the pin itself had.
    """
    total = sum(len(_MODEL_RE.findall(p.read_text(encoding="utf-8"))) for p in _SCANNED)
    assert total >= 4, f"expected the scanned files to name model IDs, found {total}"
