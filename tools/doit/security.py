"""Security-related doit tasks."""

from typing import Any

from doit.tools import title_with_actions

from .base import install_check_or_skip, optional_root_files


def task_audit() -> dict[str, Any]:
    """Run security audit with pip-audit (requires security extras)."""
    return {
        "actions": [
            install_check_or_skip(
                "pip-audit",
                "pip-audit not installed. Run: uv sync --extra security",
            )
            + "uv run pip-audit --skip-editable"
        ],
        "title": title_with_actions,
    }


def task_security() -> dict[str, Any]:
    """Run security checks with bandit (requires security extras)."""
    return {
        "actions": [
            install_check_or_skip(
                "bandit",
                "bandit not installed. Run: uv sync --extra security",
            )
            + "uv run bandit -c pyproject.toml -r src/ tools/"
            + optional_root_files("bootstrap.py")
        ],
        "title": title_with_actions,
        "verbosity": 0,
    }


def task_licenses() -> dict[str, Any]:
    """Check licenses of dependencies (requires security extras)."""
    return {
        "actions": [
            install_check_or_skip(
                "pip-licenses",
                "pip-licenses not installed. Run: uv sync --extra security",
            )
            + "uv run pip-licenses --format=markdown --order=license"
        ],
        "title": title_with_actions,
    }


def task_sbom() -> dict[str, Any]:
    """Generate SBOM in CycloneDX format (requires security extras)."""
    return {
        "actions": [
            "mkdir -p tmp",
            install_check_or_skip(
                "cyclonedx-bom",
                "cyclonedx-py not installed. Run: uv sync --extra security",
            )
            + "uv run cyclonedx-py environment --of JSON -o tmp/sbom.json && "
            "uv run cyclonedx-py environment --of XML -o tmp/sbom.xml",
        ],
        "title": title_with_actions,
        "verbosity": 2,
    }
