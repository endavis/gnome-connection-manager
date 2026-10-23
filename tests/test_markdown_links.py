"""Validate every relative link in the repository's markdown against the tree.

`mkdocs build --strict` only resolves links that land inside `docs_dir`. This
repository deliberately links out of `docs/` to canonical files that live
elsewhere — `AGENTS.md`, `README.md`, `.github/CONTRIBUTING.md`, the hook
scripts under `tools/`, and their tests — kept relative so they resolve when
the repository is browsed on GitHub and so downstream forks resolve to their
own files rather than to this upstream repo.

mkdocs 1.6 reports both classes identically (`links.not_found`), so silencing
the out-of-docs links there would also silence genuinely broken ones. The
validation therefore lives here, where a link can be checked against the whole
repository rather than only against `docs_dir`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from agent_roster import ALL_AGENTS, agent_is_present, present_agents

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = REPO_ROOT / "docs"

# Markdown that ships with the template and is read by humans or agents.
# Root-level files matter as much as `docs/`: README.md and
# .github/CONTRIBUTING.md are the first thing a new contributor opens, and
# their links were broken for as long as nothing checked them (#686).
_ROOT_MARKDOWN = ("README.md", "README.template.md", "AGENTS.md", "CHANGELOG.md")
_GITHUB_MARKDOWN_DIR = REPO_ROOT / ".github"

# Markdown inline links: [text](target). Reference-style and bare autolinks are
# not used for repo paths in this docs tree.
_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")

# Targets that are not repository paths.
_EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "tel:", "#")

# Placeholder paths inside templates and examples, which intentionally do not
# resolve — they are filled in by whoever copies the template.
_PLACEHOLDER_PARTS = ("path/to/", "<", "{{", "$")


def _iter_markdown() -> list[Path]:
    """Every checked markdown file: docs/, the repo root, and .github/."""
    paths = list(DOCS_DIR.rglob("*.md"))
    paths += [REPO_ROOT / name for name in _ROOT_MARKDOWN if (REPO_ROOT / name).is_file()]
    paths += list(_GITHUB_MARKDOWN_DIR.glob("*.md"))
    return sorted(set(paths))


def _link_targets(path: Path) -> list[str]:
    """Return the repo-path link targets in *path*, ignoring code fences."""
    text = path.read_text(encoding="utf-8")
    # Drop fenced code blocks so example snippets aren't treated as links.
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    targets = []
    for raw in _LINK_RE.findall(text):
        target = raw.strip().split(" ")[0]
        if not target or target.startswith(_EXTERNAL_PREFIXES):
            continue
        if any(part in target for part in _PLACEHOLDER_PARTS):
            continue
        targets.append(target)
    return targets


def _resolve(source: Path, target: str) -> Path:
    """Resolve *target* relative to the directory containing *source*."""
    return (source.parent / target.split("#")[0]).resolve()


# Which agents each config root belongs to. `.agents/` is read by both Codex and
# Antigravity, so it is only absent when neither is wired.
_AGENT_CONFIG_ROOTS: dict[Path, tuple[str, ...]] = {
    REPO_ROOT / ".claude": ("claude",),
    REPO_ROOT / ".codex": ("codex",),
    REPO_ROOT / ".copilot": ("copilot",),
    REPO_ROOT / ".github" / "skills": ("copilot",),
    REPO_ROOT / ".agents": ("codex", "antigravity"),
}


def _points_into_an_unwired_agent(resolved: Path) -> bool:
    """Return whether *resolved* lives under a config root this project dropped.

    The template's AI docs describe every agent it can wire. A project that keeps
    only some still ships that prose, so links into the dropped agents' config
    dirs dangle — expected, not broken (#690). In the template every agent is
    wired, so this never fires and the check is exactly as strict as before.
    """
    for root, owners in _AGENT_CONFIG_ROOTS.items():
        if resolved == root or root in resolved.parents:
            return not any(agent_is_present(agent) for agent in owners)
    return False


@pytest.mark.parametrize("doc", _iter_markdown(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_relative_links_resolve(doc: Path) -> None:
    """Every relative link in a docs page points at a file that exists.

    Covers links that leave `docs/` as well as those inside it — the whole
    point of validating here rather than in mkdocs.
    """
    broken = []
    for target in _link_targets(doc):
        resolved = _resolve(doc, target)
        if not resolved.exists() and not _points_into_an_unwired_agent(resolved):
            broken.append(f"{target} -> {resolved}")
    assert not broken, f"{doc.relative_to(REPO_ROOT)} has broken links:\n  " + "\n  ".join(broken)


def test_links_stay_inside_the_repository() -> None:
    """No docs link escapes the repository root.

    A link resolving above the repo root would work on one checkout layout and
    break on another.
    """
    escapes = []
    for doc in _iter_markdown():
        for target in _link_targets(doc):
            resolved = _resolve(doc, target)
            if REPO_ROOT not in resolved.parents and resolved != REPO_ROOT:
                escapes.append(f"{doc.relative_to(REPO_ROOT)}: {target} -> {resolved}")
    assert not escapes, "links escape the repository root:\n  " + "\n  ".join(escapes)


def test_the_scanner_actually_finds_links() -> None:
    """Guard against the link regex silently matching nothing.

    Without this, a regex change could make every test above pass vacuously.
    """
    total = sum(len(_link_targets(doc)) for doc in _iter_markdown())
    assert total > 100, f"expected many repo links across docs/, found {total}"


def test_unwired_agent_filter_is_inert_in_the_template() -> None:
    """The absent-agent exemption must not be masking real breakage here.

    When every agent is wired nothing may qualify for the exemption. If this
    fails, `_points_into_an_unwired_agent` is swallowing links it should be
    reporting.

    Skipped in a project that dropped an agent — there the exemption firing is
    the point, not a defect.
    """
    if set(present_agents()) != set(ALL_AGENTS):
        pytest.skip("project does not wire every agent; the exemption is expected to fire")

    exempted = [
        f"{doc.relative_to(REPO_ROOT)}: {target}"
        for doc in _iter_markdown()
        for target in _link_targets(doc)
        if _points_into_an_unwired_agent(_resolve(doc, target))
    ]
    assert not exempted, (
        "links were exempted as belonging to an unwired agent, but this project "
        f"wires all of them: {exempted}"
    )
