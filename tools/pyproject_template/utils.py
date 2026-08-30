"""
Shared utilities for pyproject-template tools.
"""

import json
import re
import shutil
import subprocess  # nosec B404
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    import tomllib  # py311+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

# Template repository info
TEMPLATE_REPO = "endavis/pyproject-template"
TEMPLATE_URL = f"https://github.com/{TEMPLATE_REPO}"

# Tests that are template-owned: they live in the template's own CI, are
# excluded from the drift checker, and are shed from downstreams by cleanup
# and by configure.py. All three consumers — check_template_updates.py,
# cleanup.py and configure.py — import this list; never hardcode it in any of
# them (ADR-9017).
#
# The membership test is whether the test's *target* survives configuration.
# Tests covering tools/doit/ and tools/hooks/ are deliberately absent: that
# code ships to the spawned project, runs there, and is measured by the
# coverage gate in pyproject.toml (#731).
TEMPLATE_OWNED_TEST_FILES: list[str] = [
    "tests/template/test_pyproject_template_main.py",
    "tests/template/test_check_template_updates.py",
    "tests/template/test_cleanup.py",
    "tests/template/test_repo_settings.py",
    "tests/template/test_setup_repo.py",
    "tests/template/test_bootstrap.py",
    "tests/template/test_utils.py",
    "tests/template/test_utils_properties.py",
    # Targets consumed by configure.py itself: configure.py self-destructs at
    # the end of its run, and README.template.md is renamed onto README.md.
    "tests/template/test_configure_paths.py",
    "tests/template/test_readme_split.py",
    "tests/template/test_downstream_test_retention.py",
]


def remove_template_owned_tests(root: Path) -> list[Path]:
    """Delete the template-owned test files under *root*, returning what was removed.

    The single shedding implementation for every path that turns the template
    into a real project: ``configure.py`` and ``setup_repo.py`` both call this,
    and ``cleanup --setup`` sheds the same list through ``SETUP_FILES``. That
    keeps ADR-9017's "single authoritative list" claim true in practice rather
    than only in the constant.

    Tests covering ``tools/doit/`` and ``tools/hooks/`` are deliberately kept:
    that code ships to the spawned project, runs there, and is measured by the
    coverage gate in ``pyproject.toml``. All three paths used to remove
    ``tests/template/`` wholesale, which left the spawned project failing its
    own coverage gate at 33.98% against a ``fail_under`` of 54 (#731).
    """
    removed: list[Path] = []
    for rel in TEMPLATE_OWNED_TEST_FILES:
        path = root / rel
        if path.is_file():
            path.unlink()
            removed.append(path)

    # Drop the package directory only if shedding emptied it. A project that
    # keeps tooling tests keeps the package they live in.
    template_tests_dir = root / "tests" / "template"
    if template_tests_dir.is_dir():
        survivors = [
            entry
            for entry in template_tests_dir.iterdir()
            if entry.name not in {"__init__.py", "__pycache__"}
        ]
        if not survivors:
            shutil.rmtree(template_tests_dir)

    return removed


# Files to update during placeholder replacement (single source of truth)
# Used by both configure.py and setup_repo.py
FILES_TO_UPDATE: tuple[str, ...] = (
    "pyproject.toml",
    "README.md",
    "LICENSE",
    "dodo.py",
    "mkdocs.yml",
    "AGENTS.md",
    "CHANGELOG.md",
    ".github/workflows/ci.yml",
    ".github/workflows/release.yml",
    ".github/workflows/testpypi.yml",
    ".github/workflows/breaking-change-detection.yml",
    ".github/CONTRIBUTING.md",
    ".github/SECURITY.md",
    ".github/CODE_OF_CONDUCT.md",
    ".github/CODEOWNERS",
    ".github/pull_request_template.md",
    ".claude/CLAUDE.md",
    ".claude/lsp-setup.md",
    ".envrc",
    ".pre-commit-config.yaml",
    ".vscode/launch.json",
)


# ANSI color codes
class Colors:
    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    BLUE = "\033[0;34m"
    CYAN = "\033[0;36m"
    BOLD = "\033[1m"
    NC = "\033[0m"  # No Color


class Logger:
    """Simple logging utility with colored output."""

    @staticmethod
    def info(msg: str) -> None:
        print(f"{Colors.BLUE}i{Colors.NC} {msg}")

    @staticmethod
    def success(msg: str) -> None:
        print(f"{Colors.GREEN}✓{Colors.NC} {msg}")

    @staticmethod
    def warning(msg: str) -> None:
        print(f"{Colors.YELLOW}⚠{Colors.NC} {msg}")

    @staticmethod
    def error(msg: str) -> None:
        print(f"{Colors.RED}✗{Colors.NC} {msg}", file=sys.stderr)

    @staticmethod
    def step(msg: str) -> None:
        print(f"\n{Colors.CYAN}▸{Colors.NC} {msg}")

    @staticmethod
    def header(msg: str) -> None:
        print(f"\n{Colors.BOLD}{msg}{Colors.NC}")
        print("━" * 60)


def prompt(question: str, default: str = "") -> str:
    """Prompt user for input with optional default value."""
    if default:
        p = f"{Colors.CYAN}?{Colors.NC} {question} [{Colors.GREEN}{default}{Colors.NC}]: "
        response = input(p).strip()
        return response or default
    while True:
        response = input(f"{Colors.CYAN}?{Colors.NC} {question}: ").strip()
        if response:
            return response
        Logger.warning("This field is required. Please enter a value.")


def prompt_confirm(question: str, default: bool = False) -> bool:
    """Prompt user for yes/no confirmation."""
    if default:
        p = f"{Colors.CYAN}?{Colors.NC} {question} [{Colors.GREEN}Y{Colors.NC}/n]: "
        response = input(p).strip().lower()
        return response in ("", "y", "yes")
    else:
        p = f"{Colors.CYAN}?{Colors.NC} {question} [y/{Colors.GREEN}N{Colors.NC}]: "
        response = input(p).strip().lower()
        return response in ("y", "yes")


def validate_package_name(name: str) -> str:
    """Validate and convert to valid Python package name."""
    # Convert to lowercase and replace invalid characters with underscores
    package_name = re.sub(r"[^a-z0-9_]", "_", name.lower())
    # Remove leading/trailing underscores
    package_name = package_name.strip("_")
    # Ensure it doesn't start with a number
    if package_name and package_name[0].isdigit():
        package_name = f"_{package_name}"
    return package_name


def validate_pypi_name(name: str) -> str:
    """Convert to valid PyPI package name (kebab-case)."""
    # Convert to lowercase and replace invalid characters with hyphens
    pypi_name = re.sub(r"[^a-z0-9-]", "-", name.lower())
    # Remove leading/trailing hyphens
    pypi_name = pypi_name.strip("-")
    # Collapse multiple hyphens
    pypi_name = re.sub(r"-+", "-", pypi_name)
    return pypi_name


def validate_email(email: str) -> bool:
    """Basic email validation."""
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))


def command_exists(command: str) -> bool:
    """Check if a command exists in PATH.

    Args:
        command: The command name to check for.

    Returns:
        True if the command exists and is executable, False otherwise.
    """
    try:
        result = subprocess.run(
            ["which", command],
            capture_output=True,
        )
        return result.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def get_git_config(key: str, default: str = "") -> str:
    """Get a git configuration value.

    Args:
        key: The git config key to retrieve (e.g., "user.name", "user.email").
        default: Default value to return if the key is not found.

    Returns:
        The config value if found, otherwise the default value.

    Notes:
        The unscoped ``git config <key>`` lookup merges system, global, and
        local config — but only when the current working directory is inside
        a git repository. When called from outside any repo (e.g. the
        bootstrap wizard running from ``~/src`` before the project checkout
        exists), the unscoped call exits non-zero even for keys that are set
        in ``~/.gitconfig``. This function retries with ``--global`` on
        failure so that ``user.name`` and ``user.email`` resolve from the
        user's global identity regardless of CWD (see #470). Keys that only
        exist locally (e.g. ``remote.origin.url``) fail both calls and fall
        through to ``default``, which is the correct behavior.
    """
    try:
        result = subprocess.run(
            ["git", "config", key],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        # Unscoped lookup failed — retry with --global so that globally
        # configured values (user.name, user.email) resolve even when the
        # CWD is not inside a git repository.
        global_result = subprocess.run(
            ["git", "config", "--global", key],
            capture_output=True,
            text=True,
        )
        if global_result.returncode == 0:
            return global_result.stdout.strip()
        return default
    except (subprocess.SubprocessError, FileNotFoundError):
        return default


def is_github_url(url: str) -> bool:
    """Check if URL is from github.com using proper URL parsing.

    This prevents URL manipulation attacks like 'https://evil.com/github.com/...'

    Args:
        url: The URL to check.

    Returns:
        True if the URL is from github.com, False otherwise.
    """
    try:
        parsed = urlparse(url)
        return parsed.netloc == "github.com" or parsed.netloc.endswith(".github.com")
    except Exception:
        return False


def parse_github_url(url: str) -> tuple[str, str]:
    """Parse a GitHub URL and extract owner and repository name.

    Handles both formats:
    - https://github.com/owner/repo
    - git@github.com:owner/repo.git

    Args:
        url: The GitHub URL to parse.

    Returns:
        Tuple of (owner, repo) or ("", "") if parsing fails.
    """
    if not url:
        return "", ""

    # Remove .git suffix if present
    if url.endswith(".git"):
        url = url[:-4]

    # Normalize SSH format to HTTPS for parsing
    if url.startswith("git@github.com:"):
        url = url.replace("git@github.com:", "https://github.com/")

    # Validate it's a GitHub URL
    if not is_github_url(url):
        return "", ""

    # Extract owner and repo from path
    parts = url.rstrip("/").split("/")
    if len(parts) >= 2:
        return parts[-2], parts[-1]

    return "", ""


def load_toml_file(path: Path) -> dict[str, Any]:
    """Load and parse a TOML file.

    Args:
        path: Path to the TOML file.

    Returns:
        Parsed TOML data as a dictionary, or empty dict if file doesn't exist
        or parsing fails.
    """
    if not path.exists():
        return {}
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError):
        return {}


def get_first_author(pyproject_data: dict[str, Any]) -> tuple[str, str]:
    """Extract the first author's name and email from pyproject.toml data.

    Args:
        pyproject_data: Parsed pyproject.toml data.

    Returns:
        Tuple of (name, email) or ("", "") if no author found.
    """
    authors = pyproject_data.get("project", {}).get("authors", [])
    if not authors:
        return "", ""
    author = authors[0]
    return author.get("name", ""), author.get("email", "")


# Marker tokens follow the ``__FOO__`` convention used in prose files
# (README, CHANGELOG, docs, .github prose, .claude/CLAUDE.md). They are always
# replaced via a blind string substitution because the surrounding double
# underscores make collisions with real code/prose structurally impossible.
_MARKER_TOKENS: frozenset[str] = frozenset(
    {
        "__PACKAGE_NAME__",
        "__PYPI_NAME__",
        "__PROJECT_NAME__",
        "__GH_OWNER__",
        "__AUTHOR_NAME__",
        "__AUTHOR_EMAIL__",
        "__DESCRIPTION__",
        "__REPO_URL__",
        "__REPO_SLUG__",
    }
)

# Literal placeholder tokens that must use word-boundary regex when applied to
# Python source so that identifier substrings (e.g. ``validate_package_name``,
# ``my_username``) are not accidentally rewritten. These are the tokens that
# collide with natural identifier-like substrings. Multi-word tokens such as
# ``Your Name`` do not need this guard because they cannot appear inside a
# Python identifier.
_IDENTIFIER_LITERALS: frozenset[str] = frozenset(
    {
        "package_name",
        "package-name",
        "username",
    }
)


def update_file(filepath: Path, replacements: dict[str, str]) -> None:
    """Update file with string replacements.

    Three replacement modes are applied per ``(old, new)`` pair:

    1. **Marker tokens** (``__FOO__``): blind string replace. Markers cannot
       collide with real identifiers or prose, so no guarding is required.
    2. **Identifier-like literals in Python source** (``.py`` files only):
       word-boundary regex replace so that ``validate_package_name`` and
       similar identifier substrings survive. The ``package_name`` literal
       additionally preserves keyword-argument and TOML-key forms via the
       ``(?!\\s*=)`` lookahead.
    3. **Everything else**: blind string replace (current default behaviour).

    Binary files are skipped silently.
    """
    if not filepath.exists():
        return
    try:
        content = filepath.read_text(encoding="utf-8")
        is_python = filepath.suffix == ".py"
        for old, new in replacements.items():
            if old in _MARKER_TOKENS:
                # Markers are unambiguous; blind replace.
                content = content.replace(old, new)
            elif is_python and old in _IDENTIFIER_LITERALS:
                # Word-boundary regex protects identifier substrings such as
                # ``validate_package_name`` or ``my_username`` from being
                # rewritten when the bare token appears elsewhere.
                if old == "package_name":
                    # Additional guard preserves kwargs/TOML-keys:
                    # ``package_name="value"`` and ``package_name = "value"``.
                    pattern = r"\bpackage_name\b(?!\s*=)"
                else:
                    pattern = rf"\b{re.escape(old)}\b"
                content = re.sub(pattern, new, content)
            else:
                content = content.replace(old, new)
        filepath.write_text(content, encoding="utf-8")
    except UnicodeDecodeError:
        pass  # Skip binary files


def update_test_files(test_dir: Path, package_name: str) -> None:
    """Update test files with limited replacements.

    Only replaces package_name for imports (from package_name import),
    preserving placeholder string values used as test fixtures for
    placeholder detection tests.

    Args:
        test_dir: Path to the tests directory
        package_name: The actual package name to use in imports
    """
    if not test_dir.exists():
        return

    # Limited replacements - only for imports, not string values
    test_replacements = {
        "package_name": package_name,
    }

    for py_file in test_dir.rglob("*.py"):
        update_file(py_file, test_replacements)


def download_and_extract_archive(url: str, target_dir: Path) -> Path:
    """Download and extract a zip/tar archive from a URL."""
    archive_path = target_dir / "archive.tmp"

    Logger.info(f"Downloading from {url}...")
    try:
        urllib.request.urlretrieve(url, archive_path)  # nosec B310
    except Exception as e:
        Logger.error(f"Failed to download archive: {e}")
        sys.exit(1)

    extract_dir = target_dir / "extracted"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)

    Logger.info("Extracting archive...")

    try:
        if zipfile.is_zipfile(archive_path):
            with zipfile.ZipFile(archive_path, "r") as zf:
                # Filter out dangerous paths
                for member in zf.namelist():
                    if member.startswith("/") or ".." in member:
                        continue
                    zf.extract(member, extract_dir)
        elif tarfile.is_tarfile(archive_path):
            with tarfile.open(archive_path, "r:*") as tf:
                # Filter out dangerous members
                safe_members = [
                    m
                    for m in tf.getmembers()
                    if m.name and not (m.name.startswith("/") or ".." in m.name)
                ]
                tf.extractall(extract_dir, members=safe_members)  # nosec B202
        else:
            raise ValueError("Unknown archive format")
    except Exception as e:
        Logger.error(f"Failed to extract archive: {e}")
        sys.exit(1)
    finally:
        if archive_path.exists():
            archive_path.unlink()

    # If the archive contains a single top-level directory, return that
    contents = list(extract_dir.iterdir())
    if len(contents) == 1 and contents[0].is_dir():
        return contents[0]
    return extract_dir


class GitHubCLI:
    """Wrapper for GitHub CLI commands."""

    @staticmethod
    def run(
        args: list[str], check: bool = True, capture: bool = True
    ) -> subprocess.CompletedProcess[str]:
        """Run a gh command."""
        cmd = ["gh", *args]
        try:
            result = subprocess.run(
                cmd,
                check=check,
                capture_output=capture,
                text=True,
            )
            return result
        except subprocess.CalledProcessError as e:
            if capture:
                Logger.error(f"Command failed: {' '.join(cmd)}")
                if e.stderr:
                    print(e.stderr, file=sys.stderr)
            raise

    @staticmethod
    def api(endpoint: str, method: str = "GET", data: dict[str, Any] | None = None) -> Any:
        """Make a GitHub API call."""
        args = ["api", endpoint, "-X", method]
        if data:
            args.append("--input")
            args.append("-")

        result = subprocess.run(
            ["gh", *args],
            input=json.dumps(data) if data else None,
            capture_output=True,
            text=True,
            check=True,
        )

        if result.stdout:
            return json.loads(result.stdout)
        return None

    @staticmethod
    def is_authenticated() -> bool:
        """Check if gh is authenticated."""
        try:
            result = subprocess.run(
                ["gh", "auth", "status"],
                capture_output=True,
                text=True,
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False
