"""Template parser for GitHub issue and PR templates, and ADR templates.

Reads templates from .github/ directory and docs/decisions/ and converts them
to editor-friendly markdown.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any, NamedTuple

import yaml


class AdrTemplate(NamedTuple):
    """Parsed ADR template with editor content and metadata."""

    editor_template: str
    required_sections: list[str]
    all_sections: list[str]


class IssueTemplate(NamedTuple):
    """Parsed issue template with editor content and metadata."""

    name: str
    labels: str
    editor_template: str
    required_sections: list[str]


# Map issue types to template filenames
ISSUE_TYPE_TO_FILE = {
    "feature": "feature_request.yml",
    "bug": "bug_report.yml",
    "refactor": "refactor.yml",
    "docs": "documentation.yml",
    "chore": "chore.yml",
}

# Map YAML field IDs to section names for validation
FIELD_ID_TO_SECTION = {
    "problem": "Problem",
    "proposed-solution": "Proposed Solution",
    "success-criteria": "Success Criteria",
    "additional-context": "Additional Context",
    "bug-description": "Bug Description",
    "steps-to-reproduce": "Steps to Reproduce",
    "expected-vs-actual": "Expected vs Actual Behavior",
    "environment": "Environment",
    "error-output": "Error Output",
    "current-code-issue": "Current Code Issue",
    "proposed-improvement": "Proposed Improvement",
    "doc-type": "Documentation Type",
    "description": "Description",
    "location": "Suggested Location",
    "chore-type": "Chore Type",
    "proposed-changes": "Proposed Changes",
}


def _get_github_dir() -> Path:
    """Get the .github directory path."""
    # Find project root by looking for .github directory
    current = Path(__file__).resolve()
    for parent in [current, *list(current.parents)]:
        github_dir = parent / ".github"
        if github_dir.is_dir():
            return github_dir
    raise FileNotFoundError("Could not find .github directory")


def _parse_yaml_template(template_path: Path) -> dict[str, Any]:
    """Parse a YAML template file.

    Args:
        template_path: Path to the YAML template file

    Returns:
        Parsed YAML content as dict
    """
    with open(template_path, encoding="utf-8") as f:
        result: dict[str, Any] = yaml.safe_load(f)
        return result


def _yaml_to_editor_markdown(yaml_data: dict) -> tuple[str, list[str]]:
    """Convert YAML template structure to editor-friendly markdown.

    Args:
        yaml_data: Parsed YAML template data

    Returns:
        Tuple of (editor_template, required_sections)
    """
    lines = [
        "# Lines starting with # are comments and will be ignored.",
        "# Fill in the sections below, save, and exit.",
        "# Delete the placeholder text and add your content.",
        "",
    ]
    required_sections: list[str] = []

    body = yaml_data.get("body", [])
    for item in body:
        item_type = item.get("type")
        attrs = item.get("attributes", {})
        validations = item.get("validations", {})

        if item_type == "markdown":
            # Skip markdown intro sections
            continue

        if item_type in ("textarea", "dropdown"):
            field_id = item.get("id", "")
            label = attrs.get("label", "")
            description = attrs.get("description", "")
            placeholder = attrs.get("placeholder", "")
            is_required = validations.get("required", False)

            # Map field ID to section name
            section_name = FIELD_ID_TO_SECTION.get(field_id) or label

            if is_required and section_name:
                required_sections.append(section_name)

            # Build section
            lines.append(f"## {section_name}")

            # Add requirement indicator in comment
            req_text = "Required" if is_required else "Optional"
            if description:
                lines.append(f"<!-- {req_text}: {description} -->")
            else:
                lines.append(f"<!-- {req_text} -->")

            # Add placeholder content
            if item_type == "dropdown":
                # For dropdowns, list options as choices
                options = attrs.get("options", [])
                lines.append(" / ".join(options))
            elif placeholder:
                # Clean up placeholder - remove leading pipe formatting
                placeholder_clean = placeholder.strip()
                lines.append(placeholder_clean)
            else:
                lines.append("")

            lines.append("")

    return "\n".join(lines), required_sections


@lru_cache(maxsize=10)
def get_issue_template(issue_type: str) -> IssueTemplate:
    """Get the issue template for a given type.

    Args:
        issue_type: One of 'feature', 'bug', 'refactor', 'docs', 'chore'

    Returns:
        IssueTemplate with editor content and metadata

    Raises:
        ValueError: If issue_type is not valid
        FileNotFoundError: If template file doesn't exist
    """
    if issue_type not in ISSUE_TYPE_TO_FILE:
        valid_types = list(ISSUE_TYPE_TO_FILE.keys())
        raise ValueError(f"Invalid issue type: {issue_type}. Must be one of: {valid_types}")

    github_dir = _get_github_dir()
    template_file = github_dir / "ISSUE_TEMPLATE" / ISSUE_TYPE_TO_FILE[issue_type]

    if not template_file.exists():
        raise FileNotFoundError(f"Template file not found: {template_file}")

    yaml_data = _parse_yaml_template(template_file)

    # Extract metadata
    name = yaml_data.get("name", issue_type)
    labels_list = yaml_data.get("labels", [])
    labels = ",".join(labels_list) if isinstance(labels_list, list) else str(labels_list)

    # Convert to editor template
    editor_template, required_sections = _yaml_to_editor_markdown(yaml_data)

    return IssueTemplate(
        name=name,
        labels=labels,
        editor_template=editor_template,
        required_sections=required_sections,
    )


@lru_cache(maxsize=1)
def get_pr_template() -> str:
    """Get the PR template content.

    Returns:
        PR template as markdown string with editor comments added

    Raises:
        FileNotFoundError: If PR template doesn't exist
    """
    github_dir = _get_github_dir()
    template_file = github_dir / "pull_request_template.md"

    if not template_file.exists():
        raise FileNotFoundError(f"PR template not found: {template_file}")

    content = template_file.read_text(encoding="utf-8")

    # Add editor instructions at the top
    header = """\
# Lines starting with # are comments and will be ignored.
# Fill in the sections below, save, and exit.
# Delete the placeholder text and add your content.
# Mark checkboxes with [x] where applicable.

"""
    return header + content


def get_issue_labels(issue_type: str) -> str:
    """Get the labels for a given issue type.

    Args:
        issue_type: One of 'feature', 'bug', 'refactor', 'docs', 'chore'

    Returns:
        Comma-separated string of labels
    """
    template = get_issue_template(issue_type)
    return template.labels


def get_required_sections(issue_type: str) -> list[str]:
    """Get the required sections for a given issue type.

    Args:
        issue_type: One of 'feature', 'bug', 'refactor', 'docs', 'chore'

    Returns:
        List of required section names
    """
    template = get_issue_template(issue_type)
    return template.required_sections


def clear_template_cache() -> None:
    """Clear the template cache. Useful for testing."""
    get_issue_template.cache_clear()
    get_pr_template.cache_clear()
    get_adr_template.cache_clear()


def _get_docs_dir() -> Path:
    """Get the docs directory path."""
    # Find project root by looking for docs directory
    current = Path(__file__).resolve()
    for parent in [current, *list(current.parents)]:
        docs_dir = parent / "docs"
        if docs_dir.is_dir():
            return docs_dir
    raise FileNotFoundError("Could not find docs directory")


def _parse_adr_template(template_path: Path) -> AdrTemplate:
    """Parse an ADR markdown template file.

    Extracts section headers and identifies required sections marked with
    <!-- Required --> comments.

    Args:
        template_path: Path to the ADR template file

    Returns:
        AdrTemplate with editor content and metadata
    """
    content = template_path.read_text(encoding="utf-8")

    all_sections: list[str] = []
    required_sections: list[str] = []

    # Find all ## headers and check for <!-- Required --> marker
    # Pattern: ## Section Name followed optionally by <!-- Required -->
    lines = content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        # Check for ## header (but not ### or more)
        header_match = re.match(r"^##\s+(.+)$", line)
        if header_match:
            section_name = header_match.group(1).strip()
            all_sections.append(section_name)

            # Check next line for <!-- Required --> marker
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if next_line == "<!-- Required -->":
                    required_sections.append(section_name)
        i += 1

    # Create editor template with instructions
    editor_header = """\
# Lines starting with # are comments and will be ignored.
# Fill in the sections below, save, and exit.
# Sections marked <!-- Required --> must have content.

"""
    editor_template = editor_header + content

    return AdrTemplate(
        editor_template=editor_template,
        required_sections=required_sections,
        all_sections=all_sections,
    )


@lru_cache(maxsize=1)
def get_adr_template() -> AdrTemplate:
    """Get the ADR template with parsed metadata.

    Returns:
        AdrTemplate with editor content and required sections

    Raises:
        FileNotFoundError: If template file doesn't exist
    """
    docs_dir = _get_docs_dir()
    template_file = docs_dir / "decisions" / "adr-template.md"

    if not template_file.exists():
        raise FileNotFoundError(f"ADR template not found: {template_file}")

    return _parse_adr_template(template_file)


def get_adr_required_sections() -> list[str]:
    """Get the required sections for ADRs.

    Returns:
        List of required section names
    """
    template = get_adr_template()
    return template.required_sections


def get_adr_all_sections() -> list[str]:
    """Get all sections defined in the ADR template.

    Returns:
        List of all section names
    """
    template = get_adr_template()
    return template.all_sections
