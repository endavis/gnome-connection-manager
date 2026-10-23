"""The secret-pattern list must exist once, and be enforced where it can be.

Only Codex has a native environment allowlist (`[shell_environment_policy]`).
Claude, Copilot and Antigravity have no equivalent setting — verified against
each CLI, see `docs/development/ai/command-blocking.md` (#682).

That leaves two enforcement points, and they must not drift:

* `.codex/config.toml` removes secret-shaped variables from the child
  environment outright.
* The shared PreToolUse hook — the only control that reaches all four agents —
  blocks environment dumps and credential-store reads.

`SECRET_ENV_PATTERNS` in the hook is the single source of truth; these tests
hold the Codex config to it.
"""

from __future__ import annotations

import importlib.util
import re
import tomllib
import types
from pathlib import Path

from agent_roster import skip_if_absent

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK_PATH = REPO_ROOT / "tools" / "hooks" / "ai" / "block-dangerous-commands.py"
CODEX_CONFIG = REPO_ROOT / ".codex" / "config.toml"
# Generated trees. `mutants/` is mutmut's copy of src/ and tests/, made by
# `doit mutate`, so it holds this test file's own copy of the list (#873).
SKIP_DIRS = {".git", "site", "tmp", ".venv", "__pycache__", "worktrees", "mutants"}
SCANNED_SUFFIXES = {".py", ".toml", ".json", ".yaml", ".yml"}


def _hook() -> types.ModuleType:
    """Load the hook module (its filename has hyphens, so import by path)."""
    spec = importlib.util.spec_from_file_location("block_dangerous_commands", HOOK_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"could not load hook from {HOOK_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stray_copies(root: Path, exempt: tuple[Path, ...] = ()) -> list[str]:
    """Return files under *root* that hold a literal copy of the pattern list.

    SKIP_DIRS applies to directories inside *root* only. Matched against the
    absolute path, a checkout under a directory named `tmp` skipped every file
    and the search passed having checked nothing (#848).
    """
    strays = []
    for path in root.rglob("*"):
        if not path.is_file() or path in exempt:
            continue
        if SKIP_DIRS.intersection(path.relative_to(root).parts):
            continue
        if path.suffix not in SCANNED_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if '"*_API_KEY"' in text and '"*_SECRET"' in text:
            strays.append(str(path.relative_to(root)))
    return strays


def test_codex_exclude_list_matches_the_hook_patterns() -> None:
    """The one CLI that can enforce natively must use the shared list.

    Two copies of a secret-pattern list drift silently: the config would keep
    excluding yesterday's variable names while the hook checked today's.
    """
    skip_if_absent("codex")

    with CODEX_CONFIG.open("rb") as fh:
        policy = tomllib.load(fh)["shell_environment_policy"]

    assert tuple(policy["exclude"]) == _hook().SECRET_ENV_PATTERNS, (
        "`.codex/config.toml` exclude list has drifted from SECRET_ENV_PATTERNS; "
        "the hook is the single source of truth"
    )


def test_codex_still_restricts_the_inherited_environment() -> None:
    """The allowlist is the stronger half of Codex's control; keep it."""
    skip_if_absent("codex")

    with CODEX_CONFIG.open("rb") as fh:
        policy = tomllib.load(fh)["shell_environment_policy"]

    assert policy["inherit"] == "core"
    assert "PATH" in policy["include_only"]
    # An allowlist that grew to include a secret-shaped name would defeat itself.
    hook = _hook()
    leaked = [name for name in policy["include_only"] if hook._is_secret_name(name)]
    assert not leaked, f"include_only lets secret-shaped vars through: {leaked}"


def test_patterns_are_declared_once() -> None:
    """No second literal copy of the pattern list anywhere in the tree.

    Written as a search rather than a review note because the failure mode is a
    well-meaning copy-paste into another agent's config.
    """
    hook_source = HOOK_PATH.read_text(encoding="utf-8")
    # The tuple literal should appear exactly once: its definition.
    assert hook_source.count('"CODECOV_TOKEN",') == 1

    strays = _stray_copies(REPO_ROOT, exempt=(HOOK_PATH, CODEX_CONFIG, Path(__file__)))
    assert not strays, f"secret patterns are duplicated in: {strays}"


def test_stray_search_skips_only_directories_inside_the_root(tmp_path: Path) -> None:
    """A `tmp` directory above the checkout must not hide the whole tree (#848)."""
    root = tmp_path / "tmp" / "checkout"
    copy = '"*_API_KEY",\n"*_SECRET",\n'
    (root / "config").mkdir(parents=True)
    (root / "config" / "agent.toml").write_text(copy, encoding="utf-8")
    (root / "tmp").mkdir()
    (root / "tmp" / "scratch.toml").write_text(copy, encoding="utf-8")

    assert _stray_copies(root) == [str(Path("config") / "agent.toml")]


def test_stray_search_skips_worktrees(tmp_path: Path) -> None:
    """A worktree holds its own copy of the hook and configs, not a stray (#854)."""
    copy = '"*_API_KEY",\n"*_SECRET",\n'
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "agent.toml").write_text(copy, encoding="utf-8")
    worktree_config = tmp_path / "worktrees" / "feat" / "42-add-export" / ".codex"
    worktree_config.mkdir(parents=True)
    (worktree_config / "config.toml").write_text(copy, encoding="utf-8")

    assert _stray_copies(tmp_path) == [str(Path("config") / "agent.toml")]


def test_documentation_records_per_agent_coverage() -> None:
    """The docs must say which agents are covered by what.

    #682's point was that silence about the gap is worse than the gap: a reader
    should not have to diff four configs to learn Claude has no env allowlist.
    """
    doc = (REPO_ROOT / "docs" / "development" / "ai" / "command-blocking.md").read_text(
        encoding="utf-8"
    )
    assert "shell_environment_policy" in doc
    assert re.search(r"no native environment allowlist", doc, re.I), (
        "command-blocking.md must state which agents cannot restrict the environment"
    )
