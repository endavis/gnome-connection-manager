#!/usr/bin/env python3
"""Generate categorized documentation TOC from frontmatter tags.

This script scans markdown files in docs/, extracts frontmatter metadata,
and generates categorized page lists in TABLE_OF_CONTENTS.md based on
template markers.

Template markers:
    <!-- BEGIN:audience=users -->
    <!-- END:audience=users -->

    <!-- BEGIN:tag=security,ci-cd -->
    <!-- END:tag=security,ci-cd -->

    <!-- BEGIN:all -->
    <!-- END:all -->

Usage:
    python tools/generate_doc_toc.py

For full documentation, see issue #169.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

DOCS_DIR = Path("docs")
TOC_FILE = DOCS_DIR / "TABLE_OF_CONTENTS.md"

# Files to exclude from the TOC
EXCLUDE_FILES = {
    "TABLE_OF_CONTENTS.md",
}

# Pattern to match template markers
# Matches: <!-- BEGIN:key=value,value2 --> or <!-- BEGIN:all -->
MARKER_PATTERN = re.compile(
    r"(<!-- BEGIN:(\w+)(?:=([^\s>]+))? -->)"  # Opening marker
    r"(.*?)"  # Content between markers (non-greedy)
    r"(<!-- END:\2(?:=\3)? -->)",  # Closing marker
    re.DOTALL,
)


def extract_frontmatter(path: Path) -> dict:
    """Extract YAML frontmatter from markdown file.

    Args:
        path: Path to markdown file.

    Returns:
        Dictionary of frontmatter metadata, empty if none found.
    """
    content = path.read_text(encoding="utf-8")

    if not content.startswith("---"):
        return {}

    try:
        # Find the closing ---
        end_idx = content.index("---", 3)
        frontmatter_str = content[3:end_idx]
        return yaml.safe_load(frontmatter_str) or {}
    except (ValueError, yaml.YAMLError):
        return {}


def get_title(path: Path, meta: dict) -> str:
    """Get document title from frontmatter or first heading.

    Args:
        path: Path to markdown file.
        meta: Frontmatter metadata dictionary.

    Returns:
        Document title string.
    """
    if "title" in meta:
        return str(meta["title"])

    content = path.read_text(encoding="utf-8")

    # Skip frontmatter if present
    if content.startswith("---"):
        try:
            end_idx = content.index("---", 3)
            content = content[end_idx + 3 :]
        except ValueError:
            pass

    # Find first heading
    match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if match:
        return match.group(1).strip()

    return path.stem.replace("-", " ").replace("_", " ").title()


def collect_docs() -> list[tuple[Path, dict]]:
    """Collect all documentation files with their metadata.

    Returns:
        List of (path, metadata) tuples.
    """
    docs = []

    for path in sorted(DOCS_DIR.rglob("*.md")):
        if path.name in EXCLUDE_FILES:
            continue

        meta = extract_frontmatter(path)
        docs.append((path, meta))

    return docs


def matches_filter(meta: dict, filter_key: str, filter_values: list[str]) -> bool:
    """Check if document metadata matches the filter criteria.

    Args:
        meta: Document frontmatter metadata.
        filter_key: Key to filter on ('audience', 'tag', 'tags', 'all').
        filter_values: Values to match (OR logic).

    Returns:
        True if document matches filter.
    """
    if filter_key == "all":
        return True

    # Normalize 'tag' to 'tags'
    key = "tags" if filter_key == "tag" else filter_key

    doc_values = meta.get(key, [])

    # Handle string values (convert to list)
    if isinstance(doc_values, str):
        doc_values = [doc_values]

    # OR logic: match if any filter value is in doc values
    return any(v in doc_values for v in filter_values)


def generate_section(
    docs: list[tuple[Path, dict]], filter_key: str, filter_values: list[str]
) -> str:
    """Generate markdown list for documents matching filter.

    Args:
        docs: List of (path, metadata) tuples.
        filter_key: Key to filter on.
        filter_values: Values to match.

    Returns:
        Markdown formatted list of matching documents.
    """
    lines = []

    for path, meta in docs:
        if not matches_filter(meta, filter_key, filter_values):
            continue

        rel_path = path.relative_to(DOCS_DIR)
        title = get_title(path, meta)
        description = meta.get("description", "")

        line = f"- [{title}]({rel_path})"
        if description:
            line += f" - {description}"

        lines.append((title.lower(), line))  # Sort key, line

    # Sort alphabetically by title
    lines.sort(key=lambda x: x[0])

    if not lines:
        return "*No documents in this category.*\n"

    return "\n".join(line for _, line in lines) + "\n"


def update_toc(docs: list[tuple[Path, dict]]) -> bool:
    """Update TABLE_OF_CONTENTS.md with generated sections.

    Args:
        docs: List of (path, metadata) tuples.

    Returns:
        True if file was modified, False otherwise.
    """
    if not TOC_FILE.exists():
        print(f"Warning: {TOC_FILE} not found, skipping TOC generation")
        return False

    original_content = TOC_FILE.read_text(encoding="utf-8")

    def replace_marker(match: re.Match) -> str:
        begin_marker = match.group(1)
        filter_key = match.group(2)
        filter_values_str = match.group(3) or ""
        end_marker = match.group(5)

        filter_values = [v.strip() for v in filter_values_str.split(",") if v.strip()]

        section = generate_section(docs, filter_key, filter_values)

        return f"{begin_marker}\n{section}{end_marker}"

    new_content = MARKER_PATTERN.sub(replace_marker, original_content)

    if new_content != original_content:
        TOC_FILE.write_text(new_content, encoding="utf-8")
        return True

    return False


def main() -> int:
    """Main entry point.

    Returns:
        Exit code (0 for success/no changes, 1 for changes made).
    """
    print(f"Scanning {DOCS_DIR} for documentation files...")

    docs = collect_docs()
    print(f"Found {len(docs)} documentation files")

    # Count docs with frontmatter
    with_frontmatter = sum(1 for _, meta in docs if meta)
    print(f"  - {with_frontmatter} with frontmatter")
    print(f"  - {len(docs) - with_frontmatter} without frontmatter")

    modified = update_toc(docs)

    if modified:
        print(f"Updated {TOC_FILE}")
        return 1  # Return 1 to indicate changes (useful for pre-commit)
    else:
        print(f"No changes to {TOC_FILE}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
