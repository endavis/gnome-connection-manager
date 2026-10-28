"""Instruction pointers must resolve to something that exists.

`.claude/CLAUDE.md` told every Claude session, in blocks marked MANDATORY and
ending "NO EXCEPTIONS", to find two `AGENTS.md` sections that were not there and
to run a command that did not exist (#738). Authoritative framing plus no
destination is the documentation form of a control that reports success while
doing nothing.

Three pointer shapes are checked:

1. Quoted section references — ``Read <file> and locate the "## Section" section``.
2. Markdown link anchors — ``[text](path.md#anchor)``. `test_markdown_links.py`
   splits the fragment off before resolving, so it validates the file and never
   the section; this closes that half.
3. Parenthesized section names — `` `path.md` (Section) ``, the form of
   `AGENTS.md`'s Pre-Action Checks table. One of its rows sent every agent to a
   CONTRIBUTING.md section that did not exist (#828).

Anchors were all resolving when this was written. The check is preventive, and
`test_anchor_checker_detects_a_broken_anchor` keeps it from passing merely because
it looks at nothing. `test_section_name_checker_detects_a_broken_pointer` does the
same for the third shape.

A fourth kind of skip layers on top of all three: a downstream project lists in
`.config/pyproject_template/sync-exclude.toml` (ADR-9026) upstream-only targets it
did not adopt (`docs/template/*.md`, `src/package_name/core.py`, and so on). A
pointer whose target name matches one of those patterns is skipped rather than
reported missing. Upstream has no such file, so this is a no-op here.
"""

from __future__ import annotations

import re
import subprocess  # nosec B404 - subprocess is required to build a test git repo
from pathlib import Path

import pytest
from doc_scan import committed_markdown_files, is_excluded, load_sync_excludes

REPO_ROOT = Path(__file__).resolve().parents[1]

# Files that instruct an agent: always-on context, commands, and skills.
INSTRUCTION_GLOBS = (
    ".claude/CLAUDE.md",
    "AGENTS.md",
    ".claude/commands/**/*.md",
    ".claude/skills/*/SKILL.md",
    ".claude/agents/*.md",
    ".github/skills/*/SKILL.md",
    ".agents/skills/*/SKILL.md",
    ".copilot/commands/*.md",
    ".github/instructions/*.md",
)

# A quoted markdown heading. Backslashes are excluded so that shell examples like
# `--body="## Problem\nDescribe the problem"` in AGENTS.md are not mistaken for
# section references — they are literal payloads, not pointers.
QUOTED_HEADING = re.compile(r'"(#{1,6} [^"\\]+)"')
MD_FILENAME = re.compile(r"([\w./-]+\.md)")
MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
# A backticked markdown file followed by a parenthesized section name, as in
# `.github/CONTRIBUTING.md` (Commit Guidelines). The name must start with a
# capital and hold only words, so a summary such as
# `AGENTS.md` (Issue → Branch → Commit → PR) is not read as a pointer.
PARENTHESIZED_SECTION = re.compile(r"`([\w./-]+\.md)`\s*\(([A-Z][\w-]*(?: [\w-]+)*)\)")
# A code fence: three or more backticks or tildes, indented at most three spaces.
# The block it opens ends at a fence of the same character that is at least as
# long and has nothing after it.
FENCE = re.compile(r" {0,3}(`{3,}|~{3,})")


def _instruction_files() -> list[Path]:
    files: list[Path] = []
    for pattern in INSTRUCTION_GLOBS:
        files += sorted(REPO_ROOT.glob(pattern))
    return [f for f in files if f.is_file()]


def _markdown_files(root: Path = REPO_ROOT) -> list[Path]:
    """Return the markdown files git tracks or would add under *root*.

    Delegates to `doc_scan.committed_markdown_files`, which asks git rather than
    walking the filesystem with a hardcoded skip set -- see that function's
    docstring for why. A directory git ignores, such as `worktrees/` or `tmp/`,
    drops out without this function needing to know its name.
    """
    return committed_markdown_files(root)


def _headings(path: Path) -> set[str] | None:
    """Return the literal heading lines in *path*, or None if unreadable.

    Lines inside fenced code blocks are skipped. A `# comment` in a shell or
    Python example is not a section, and read as one it made a pointer to that
    comment pass every check here (#844).
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    headings = set()
    fence = ""  # the fence that opened the current code block, if inside one
    for line in text.splitlines():
        match = FENCE.match(line)
        if fence:
            if (
                match
                and match.group(1)[0] == fence[0]
                and len(match.group(1)) >= len(fence)
                and not line[match.end() :].strip()
            ):
                fence = ""
        elif match:
            fence = match.group(1)
        elif line.startswith("#"):
            headings.add(line.strip())
    return headings


def _slug(heading: str) -> str:
    """GitHub-style anchor slug for a heading line."""
    text = re.sub(r"^#+\s*", "", heading).strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"\s+", "-", text)


def _anchors(path: Path) -> set[str] | None:
    headings = _headings(path)
    return None if headings is None else {_slug(h) for h in headings}


def _section_references() -> list[tuple[Path, int, str, str]]:
    """Return (source, line_no, quoted_heading, target_filename) for each pointer."""
    refs = []
    for source in _instruction_files():
        for line_no, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
            for match in QUOTED_HEADING.finditer(line):
                targets = [
                    name
                    for name in MD_FILENAME.findall(line)
                    if name.lower() != source.name.lower()
                ]
                for name in targets:
                    refs.append((source, line_no, match.group(1), name))
    return refs


def _resolve_named(name: str, root: Path = REPO_ROOT) -> Path | None:
    """Resolve a markdown filename or relative path mentioned in prose to a file under *root*.

    Every caller of this function only ever names a `.md` file (`MD_FILENAME`
    and `PARENTHESIZED_SECTION` both anchor on that extension), so the fallback
    search is scoped to `doc_scan.committed_markdown_files` rather than an
    unrestricted `rglob` -- git-ignored and untracked-ignored copies, such as a
    worktree's, are never candidates.
    """
    direct = root / name
    if direct.is_file():
        return direct
    target_name = Path(name).name
    for candidate in committed_markdown_files(root):
        if candidate.name == target_name:
            return candidate
    return None


def _parenthesized_references(sources: list[Path]) -> list[tuple[Path, int, str, str]]:
    """Return (source, line_no, section_name, target_filename) for each pointer."""
    refs = []
    for source in sources:
        for line_no, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
            for name, section in PARENTHESIZED_SECTION.findall(line):
                refs.append((source, line_no, section, name))
    return refs


def _names_a_heading(section: str, headings: set[str]) -> bool:
    """True if *section* is a heading's text, or its leading words, in any case.

    `.claude/CLAUDE.md` (TodoWrite) means `# TODOWRITE USAGE (MANDATORY)`, so an
    exact match is too strict. A substring match is too loose: it resolves
    (Dependencies) against `# Install dependencies (creates venv automatically)`,
    a shell comment in a CONTRIBUTING.md code block, and #828 would have passed.
    """
    leading = re.compile(rf"#+\s*{re.escape(section)}\b", re.IGNORECASE)
    return any(leading.match(heading) for heading in headings)


def _unresolved_section_names(
    refs: list[tuple[Path, int, str, str]],
    root: Path = REPO_ROOT,
    excludes: list[str] | None = None,
) -> list[str]:
    """Describe each reference whose file is missing or has no such heading.

    A reference whose target name matches *excludes* (ADR-9026) is skipped
    rather than reported -- a downstream project names it because an adopted
    file (such as a shared skill) still describes the upstream-only target it
    chose not to adopt.
    """
    broken = []
    for source, line_no, section, name in refs:
        if excludes and is_excluded(name, excludes):
            continue
        where = f"{source.relative_to(root)}:{line_no}"
        target = _resolve_named(name, root)
        if target is None:
            broken.append(f"{where} -> {name} not found")
        elif not _names_a_heading(section, _headings(target) or set()):
            broken.append(f"{where} -> ({section}) not a heading in {name}")
    return broken


def _unresolved_quoted_references(
    refs: list[tuple[Path, int, str, str]],
    root: Path = REPO_ROOT,
    excludes: list[str] | None = None,
) -> list[str]:
    """Describe each quoted-heading reference whose target is missing or lacks the heading.

    A reference whose target name matches *excludes* (ADR-9026) is skipped --
    see `_unresolved_section_names`, which does the same for the parenthesized
    pointer shape.
    """
    broken = []
    for source, line_no, heading, target_name in refs:
        if excludes and is_excluded(target_name, excludes):
            continue
        target = _resolve_named(target_name, root)
        if target is None:
            broken.append(f"{source.relative_to(root)}:{line_no} -> {target_name} not found")
            continue
        headings = _headings(target)
        if headings is not None and heading not in headings:
            broken.append(
                f"{source.relative_to(root)}:{line_no} -> {heading!r} not in {target_name}"
            )
    return broken


def test_quoted_section_references_resolve() -> None:
    """Every `Read <file> and locate the "## X" section` must name a real heading."""
    excludes = load_sync_excludes(REPO_ROOT)
    broken = _unresolved_quoted_references(_section_references(), excludes=excludes)

    assert not broken, "instruction pointers that resolve to nothing:\n  " + "\n  ".join(broken)


def test_parenthesized_section_references_resolve() -> None:
    """Every `` `path.md` (Section) `` pointer must name a heading in that file.

    AGENTS.md sent every agent to `.github/CONTRIBUTING.md` (Dependencies) before
    it added a dependency, and CONTRIBUTING.md had no such section (#828).
    """
    excludes = load_sync_excludes(REPO_ROOT)
    broken = _unresolved_section_names(
        _parenthesized_references(_instruction_files()), excludes=excludes
    )

    assert not broken, "instruction pointers that resolve to nothing:\n  " + "\n  ".join(broken)


def _broken_anchors(
    sources: list[Path], root: Path = REPO_ROOT, excludes: list[str] | None = None
) -> list[str]:
    """Describe each `[text](file.md#anchor)` whose target or anchor does not resolve.

    A link whose target, repo-relative to *root*, matches *excludes* (ADR-9026)
    is skipped. A target outside *root* (``ValueError`` from ``relative_to``) is
    never excluded -- excludes are upstream-relative patterns, so a path with no
    such relation cannot match one.
    """
    broken = []
    excludes = excludes or []
    for source in sources:
        for match in MD_LINK.finditer(source.read_text(encoding="utf-8")):
            target = match.group(1)
            if target.startswith(("http", "mailto:", "#")) or "#" not in target:
                continue
            path_part, _, fragment = target.partition("#")
            resolved = (source.parent / path_part).resolve()
            try:
                rel = resolved.relative_to(root).as_posix()
            except ValueError:
                rel = None
            if rel is not None and is_excluded(rel, excludes):
                continue
            anchors = _anchors(resolved)
            if anchors is None:
                broken.append(f"{source.relative_to(root)}: {target} (file missing)")
            elif fragment.lower() not in anchors:
                broken.append(f"{source.relative_to(root)}: {target}")
    return broken


def test_markdown_anchors_resolve() -> None:
    """`[text](file.md#anchor)` must name a heading that exists in that file.

    Complements `tests/test_markdown_links.py`, which strips the fragment.
    """
    excludes = load_sync_excludes(REPO_ROOT)
    broken = _broken_anchors(_markdown_files(), excludes=excludes)

    assert not broken, "markdown links with anchors that resolve to nothing:\n  " + "\n  ".join(
        broken
    )


def test_referenced_commands_exist() -> None:
    """A `/command` or `$skill` named in an instruction file must be installed.

    `/commit-commands:commit` was named in a MANDATORY block for months without
    ever existing (#738).
    """
    known: set[str] = set()
    for path in REPO_ROOT.glob(".claude/commands/**/*.md"):
        rel = path.relative_to(REPO_ROOT / ".claude" / "commands").with_suffix("")
        known.add(rel.as_posix().replace("/", ":"))
    for pattern in (
        ".github/skills/*/SKILL.md",
        ".agents/skills/*/SKILL.md",
        ".claude/skills/*/SKILL.md",
    ):
        known |= {p.parent.name for p in REPO_ROOT.glob(pattern)}
    for path in REPO_ROOT.glob(".copilot/commands/*.md"):
        known.add(path.stem)

    claude_md = REPO_ROOT / ".claude" / "CLAUDE.md"
    broken = [
        name
        # Not preceded by a word char, backtick, slash, dot or @ — so the
        # `@./rules/*.md` import reads as a path, not a command — and not
        # followed by a path separator.
        for name in re.findall(
            r"(?<![\w`/.@])/([a-z][\w-]*(?::[\w-]+)?)(?![\w/-])",
            claude_md.read_text("utf-8"),
        )
        if name not in known and name.split(":")[0] not in known
    ]

    assert not broken, (
        f"CLAUDE.md names commands that are not installed: {sorted(set(broken))}. "
        "Available: " + ", ".join(sorted(known)[:12]) + " ..."
    )


def test_the_scanner_actually_finds_references() -> None:
    """Guard against the pointer regexes silently matching nothing."""
    assert _section_references(), "no quoted section references found; the regex has gone stale"
    assert _parenthesized_references(_instruction_files()), (
        "no `path.md` (Section) references found; the regex has gone stale"
    )

    anchored = [
        m.group(1)
        for source in _markdown_files()
        for m in MD_LINK.finditer(source.read_text(encoding="utf-8"))
        if "#" in m.group(1) and not m.group(1).startswith(("http", "mailto:", "#"))
    ]
    assert len(anchored) >= 10, f"only {len(anchored)} anchored links found; expected the docs set"


def test_shell_payloads_are_not_treated_as_pointers() -> None:
    """`--body="## Problem\\nDescribe..."` is a payload, not a section reference.

    AGENTS.md's issue-creation examples embed heading text in shell strings. Left
    unfiltered they read as seven dangling pointers and would drown the real ones.
    """
    payload = '--body="## Problem\\nDescribe the problem\\n\\n## Proposed Solution\\nDo it"'
    assert not QUOTED_HEADING.findall(payload), (
        "the quoted-heading regex matched a shell payload; it must exclude escapes"
    )


def test_parenthetical_summaries_are_not_treated_as_pointers() -> None:
    """`` `AGENTS.md` (Issue → Branch → Commit → PR) `` summarizes; it names no section.

    The template-sync command and skill both carry that line. Read as a pointer,
    it would fail the check on text that sends nobody to a section.
    """
    for line in (
        "Per `AGENTS.md` (Issue → Branch → Commit → PR):",
        "Per `AGENTS.md` (Issue -> Branch -> Commit -> PR):",
        "Stage `notes.md` (include every changed file)",
    ):
        assert not PARENTHESIZED_SECTION.findall(line), line


def test_anchor_checker_detects_a_broken_anchor(tmp_path: Path) -> None:
    """The anchor check must fail on a fragment that names no heading.

    Every anchor in the repo resolves today, so without this the check could pass
    because it found nothing rather than because everything is sound.
    """
    target = tmp_path / "target.md"
    target.write_text("# Real Heading\n", encoding="utf-8")

    assert _anchors(target) == {"real-heading"}
    assert "no-such-heading" not in (_anchors(target) or set())


def test_excluded_anchor_link_target_is_skipped(tmp_path: Path) -> None:
    """A missing anchor-link target matching sync-exclude.toml is not reported (ADR-9026)."""
    source = tmp_path / "source.md"
    source.write_text("[link](missing.md#some-heading)\n", encoding="utf-8")

    assert _broken_anchors([source], tmp_path, excludes=["missing.md"]) == []
    # The same missing target, unexcluded, is still reported.
    assert _broken_anchors([source], tmp_path, excludes=[]) == [
        "source.md: missing.md#some-heading (file missing)"
    ]


def test_fenced_comments_are_not_headings(tmp_path: Path) -> None:
    """A `# comment` in a code block names no section (#844).

    CONTRIBUTING.md's Initial Setup holds `# Install dependencies (creates venv
    automatically)` in a bash block. Read as a heading, a link to its slug passed
    the anchor check, and on GitHub it lands at the top of the page.
    """
    target = tmp_path / "target.md"
    target.write_text(
        "# Real Heading\n\n```bash\n# Install dependencies (creates venv automatically)\n```\n",
        encoding="utf-8",
    )

    assert _anchors(target) == {"real-heading"}


@pytest.mark.parametrize(
    "text",
    [
        "~~~\n# Tilde fence\n~~~\n# After\n",
        "````md\n```\n# Inside the outer fence\n```\n````\n# After\n",
        "```\n~~~\n# Inside the backtick fence\n~~~\n```\n# After\n",
        "   ```\n# Inside an indented fence\n   ```\n# After\n",
        "```\n# Code\n``` not a closing fence\n# Still code\n```\n# After\n",
    ],
    ids=["tilde", "shorter-fence-inside", "other-character-inside", "indented", "text-after"],
)
def test_a_code_block_ends_only_at_its_closing_fence(tmp_path: Path, text: str) -> None:
    """A fence closes only on the same character, at least as long, with nothing after it."""
    target = tmp_path / "target.md"
    target.write_text(text, encoding="utf-8")

    assert _headings(target) == {"# After"}


def test_section_name_checker_detects_a_broken_pointer(tmp_path: Path) -> None:
    """The parenthesized check must fail on a name that no heading starts with.

    The target mirrors CONTRIBUTING.md before #828: the only line holding the
    word is a shell comment in a code block, which `_headings` read as a heading
    until #844.
    """
    _init_repo(tmp_path)
    (tmp_path / "target.md").write_text(
        "# Real Heading\n\n```bash\n# Install dependencies\n```\n", encoding="utf-8"
    )
    source = tmp_path / "source.md"
    source.write_text(
        "| `target.md` (Real Heading) |\n"
        "| `target.md` (REAL) |\n"
        "| `target.md` (Rea) |\n"
        "| `target.md` (Dependencies) |\n"
        "| `missing.md` (Real Heading) |\n",
        encoding="utf-8",
    )

    assert _unresolved_section_names(_parenthesized_references([source]), tmp_path) == [
        "source.md:3 -> (Rea) not a heading in target.md",
        "source.md:4 -> (Dependencies) not a heading in target.md",
        "source.md:5 -> missing.md not found",
    ]


def test_excluded_parenthesized_target_is_skipped(tmp_path: Path) -> None:
    """A missing parenthesized target matching sync-exclude.toml is not reported (ADR-9026)."""
    _init_repo(tmp_path)
    source = tmp_path / "source.md"
    source.write_text("| `missing.md` (Some Heading) |\n", encoding="utf-8")

    refs = _parenthesized_references([source])
    assert _unresolved_section_names(refs, tmp_path, excludes=["missing.md"]) == []
    # The same missing target, unexcluded, is still reported.
    assert _unresolved_section_names(refs, tmp_path, excludes=[]) == [
        "source.md:1 -> missing.md not found"
    ]


def test_excluded_quoted_target_is_skipped(tmp_path: Path) -> None:
    """A missing quoted-section target matching sync-exclude.toml is not reported (ADR-9026)."""
    _init_repo(tmp_path)
    refs = [(tmp_path / "source.md", 1, "## Some Heading", "missing.md")]

    assert _unresolved_quoted_references(refs, tmp_path, excludes=["missing.md"]) == []
    assert _unresolved_quoted_references(refs, tmp_path, excludes=[]) == [
        "source.md:1 -> missing.md not found"
    ]


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(  # nosec B603 B607 - fixed argv, no shell, test fixture only
        ["git", *args], cwd=cwd, check=True, capture_output=True
    )


def _init_repo(root: Path) -> None:
    _git(["init", "--quiet"], root)
    _git(["config", "user.email", "test@example.com"], root)
    _git(["config", "user.name", "Test"], root)


def test_markdown_files_skip_only_directories_inside_the_root(tmp_path: Path) -> None:
    """A `tmp/` directory inside the repo is skipped via `.gitignore`, not path heredity.

    The old hardcoded `SKIP_DIRS` matched by absolute path parts, so a checkout
    under a directory named `tmp` hid the whole tree (#848). Discovery through
    `git ls-files` only ever sees paths relative to the repo root it is run in,
    so that failure mode cannot recur; this pins the in-repo case it replaces.
    """
    root = tmp_path / "checkout"
    root.mkdir()
    _init_repo(root)
    (root / ".gitignore").write_text("tmp/*\n", encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "kept.md").write_text("# Kept\n", encoding="utf-8")
    (root / "tmp").mkdir()
    (root / "tmp" / "skipped.md").write_text("# Skipped\n", encoding="utf-8")

    assert _markdown_files(root) == [root / "docs" / "kept.md"]


def test_markdown_files_skip_worktrees(tmp_path: Path) -> None:
    """Each worktree under `worktrees/` is a full copy of the repository (#854).

    Scanning them would check every copy's instruction files, not this checkout's.
    `worktrees/` is gitignored (mirroring the real `.gitignore`), so the git-based
    scan drops it without a hardcoded skip list.
    """
    _init_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("/worktrees/\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "kept.md").write_text("# Kept\n", encoding="utf-8")
    copy = tmp_path / "worktrees" / "feat" / "42-add-export"
    copy.mkdir(parents=True)
    (copy / "AGENTS.md").write_text("# Copy\n", encoding="utf-8")

    assert _markdown_files(tmp_path) == [tmp_path / "docs" / "kept.md"]


@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        ("## Commit Guidelines", "commit-guidelines"),
        ("### 5. Pre-Action Checks (Dynamic Context)", "5-pre-action-checks-dynamic-context"),
        ("# Overview", "overview"),
    ],
)
def test_slug_matches_github_anchor_rules(heading: str, expected: str) -> None:
    """Anchor slugs must match what GitHub generates, or the check is nonsense."""
    assert _slug(heading) == expected
