"""Third-party actions must be pinned to commit SHAs, not mutable tags (#695).

A major tag like `@v7` is a moving pointer the publisher can re-aim at any
commit, so `uses: some/action@v7` is a standing instruction to run whatever that
publisher decides to put there. A 40-character SHA is not re-pointable.

Dependabot is configured for the `github-actions` ecosystem, so pins get bumped
rather than rotting — pinning trades "silently changes" for "changes via a
reviewable PR", which is the whole point.

Each pin carries a `# vX.Y.Z` comment so a human can read the file without
resolving SHAs, and that comment is asserted too: a pin whose comment has drifted
from the version it names is worse than no comment.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIRS = (REPO_ROOT / ".github" / "workflows", REPO_ROOT / ".github" / "actions")

# `uses: owner/repo@ref` — captures the ref and any trailing comment.
USES = re.compile(
    r"^\s*(?:-\s*)?uses:\s*(?P<action>[^@\s]+)@(?P<ref>\S+)(?:\s*#\s*(?P<comment>.*))?$"
)

SHA = re.compile(r"^[0-9a-f]{40}$")
SEMVER_COMMENT = re.compile(r"^v?\d+\.\d+")

# Actions deliberately left on a mutable ref, each with the reason.
#
# PyPA publishes trusted-publishing fixes on this branch and documents it as the
# reference to use; the workflows holding `id-token: write` follow that guidance
# rather than pinning past it. Recorded here so the exemption is a decision
# rather than an oversight (#695).
# Empty here. The one entry upstream carries is for pypa/gh-action-pypi-publish, and GCM
# does not publish to PyPI, so it has no release workflow to use it. A test below asserts
# every exemption is still in use, which fails on a dead entry -- correctly.
PINNING_EXEMPT: dict[str, str] = {}


def _workflow_files() -> list[Path]:
    files: list[Path] = []
    for directory in WORKFLOW_DIRS:
        if directory.is_dir():
            files += sorted(directory.rglob("*.yml"))
    return files


def _uses_entries() -> list[tuple[Path, int, str, str, str | None]]:
    """Return (file, line_no, action, ref, comment) for every `uses:` line."""
    entries = []
    for path in _workflow_files():
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = USES.match(line)
            if not match:
                continue
            action = match.group("action").strip("'\"")
            if action.startswith("./"):
                continue  # local composite action or reusable workflow
            entries.append((path, line_no, action, match.group("ref"), match.group("comment")))
    return entries


def _base_repo(action: str) -> str:
    """`github/codeql-action/init` -> `github/codeql-action`."""
    return "/".join(action.split("/")[:2])


def test_every_external_action_is_sha_pinned() -> None:
    """No `uses:` may name a mutable tag or branch, exemptions aside."""
    unpinned = [
        f"{path.relative_to(REPO_ROOT)}:{line_no} {action}@{ref}"
        for path, line_no, action, ref, _ in _uses_entries()
        if not SHA.match(ref) and _base_repo(action) not in PINNING_EXEMPT
    ]
    assert not unpinned, (
        "actions on mutable refs — a publisher can re-point these at any commit:\n  "
        + "\n  ".join(unpinned)
        + "\n\nPin to a 40-character commit SHA with a `# vX.Y.Z` comment, or add an "
        "entry to PINNING_EXEMPT with a reason."
    )


def test_every_pin_names_the_version_it_points_at() -> None:
    """A SHA with no version comment is unreadable; a wrong one is misleading."""
    missing = [
        f"{path.relative_to(REPO_ROOT)}:{line_no} {action}"
        for path, line_no, action, ref, comment in _uses_entries()
        if SHA.match(ref) and not (comment and SEMVER_COMMENT.match(comment.strip()))
    ]
    assert not missing, "SHA pins without a `# vX.Y.Z` version comment:\n  " + "\n  ".join(missing)


def test_the_same_action_is_pinned_consistently() -> None:
    """One action at two SHAs in one repo means a bump was applied by hand."""
    seen: dict[str, set[tuple[str, str]]] = {}
    for _path, _line, action, ref, comment in _uses_entries():
        if SHA.match(ref):
            seen.setdefault(action, set()).add((ref, (comment or "").strip()))

    divergent = {a: sorted(v) for a, v in seen.items() if len(v) > 1}
    assert not divergent, f"the same action is pinned to different commits: {divergent}"


def test_exemptions_are_real_and_still_used() -> None:
    """An exemption must name a reason and an action the repo still uses.

    Stops the list becoming a place things are quietly added to and never removed.

    A loop rather than parametrize: PINNING_EXEMPT is empty here, and an empty parameter
    set makes pytest emit a skip. CI fails on any skip -- deliberately, since a silently
    skipped test is how twelve display-gated tests once vanished from a green run (#113).
    """
    in_use = {_base_repo(a) for _p, _l, a, _r, _c in _uses_entries()}
    for action, reason in sorted(PINNING_EXEMPT.items()):
        assert reason.strip(), f"{action} needs a reason"
        assert action in in_use, f"{action} is exempt but no longer used; drop the exemption"


def test_the_scanner_finds_the_uses_lines() -> None:
    """Guard the regex: a pattern matching nothing would pass every test above."""
    entries = _uses_entries()
    # 28 here today. Upstream asserts 40, counting workflows GCM did not adopt -- the
    # release, TestPyPI, benchmark, full-matrix and breaking-change ones. The number only
    # has to be high enough that a regex matching nothing fails this.
    assert len(entries) >= 25, f"only {len(entries)} `uses:` entries found; regex has gone stale"
    assert sum(1 for e in entries if SHA.match(e[3])) >= 25


def test_the_pin_check_rejects_a_mutable_ref() -> None:
    """The matcher must actually distinguish a tag from a SHA."""
    assert not SHA.match("v7")
    assert not SHA.match("release/v1")
    assert not SHA.match("3d3c42e5aac5ba805825da76410c181273ba90b")  # 39 chars
    assert SHA.match("3d3c42e5aac5ba805825da76410c181273ba90b1")


# --- Documentation samples are held to the same rule (#772) ----------------
#
# The workflows were pinned by #695 and this module has enforced it since. The
# docs were not covered, and drifted freely: 18 `uses: …@v4`-style tags across
# three pages, including a ~60-line `tests.yml` sample that told a reader to
# build a second, unpinned pipeline alongside `ci.yml`. `ci-cd-testing.md`
# stated the pinning rule correctly at one heading and violated it ninety lines
# earlier in the same file.
#
# A sample is copied more often than it is read, so an unpinned one hands the
# exposure this rule removes to every project that follows the docs.

DOCS_DIR = REPO_ROOT / "docs"
YAML_FENCE = re.compile(r"```yaml\n(.*?)```", re.DOTALL)


def _documented_uses() -> list[tuple[Path, str, str]]:
    """Return (file, action, ref) for every `uses:` inside a docs yaml fence."""
    entries: list[tuple[Path, str, str]] = []
    for path in sorted(DOCS_DIR.rglob("*.md")):
        for fence in YAML_FENCE.findall(path.read_text(encoding="utf-8")):
            for line in fence.splitlines():
                match = USES.match(line)
                if not match:
                    continue
                action = match.group("action").strip("'\"")
                if action.startswith("./"):
                    continue
                entries.append((path, action, match.group("ref")))
    return entries


def test_documented_samples_are_sha_pinned() -> None:
    """A sample teaching `@v4` teaches the pattern this repo forbids."""
    unpinned = [
        f"{path.relative_to(REPO_ROOT)} {action}@{ref}"
        for path, action, ref in _documented_uses()
        if not SHA.match(ref) and _base_repo(action) not in PINNING_EXEMPT
    ]
    assert not unpinned, (
        "documentation samples name actions on mutable refs:\n  "
        + "\n  ".join(unpinned)
        + "\nPin them, or elide the step and point at .github/workflows/ci.yml — a sample "
        "that cannot drift beats one guarded against drifting (#772)."
    )


# test_the_docs_scanner_reads_something removed. It guards against the docs assertions
# passing on an empty scan, and the scan is empty here: the pages carrying `uses:` samples
# live in docs/development, which this project has not adopted (#129). Its own docstring
# says to delete it rather than leave it green and blind. Restore it with those docs.


def test_exempt_actions_are_exempt_in_docs_too() -> None:
    """The docs may show an exempt action on its documented ref, as the workflows do."""
    documented = {action for _, action, _ in _documented_uses()}
    for action in documented:
        if _base_repo(action) in PINNING_EXEMPT:
            assert PINNING_EXEMPT[_base_repo(action)], "an exemption must carry its reason"
