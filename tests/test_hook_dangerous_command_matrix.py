"""Matrix tests for the ``block-dangerous-commands`` PreToolUse hook.

These 134 cases were migrated verbatim from ``tools/hooks/ai/test_hook.py``,
a standalone script that pytest never collected and no workflow, ``doit`` task
or pre-commit hook ever ran (#702). That script has been deleted; this file is
authoritative.

**The branch is pinned deliberately.** The old script shelled out to the real
hook with the real environment, so ``get_current_branch()`` returned whatever
was checked out. Two cases -- "merge on feature branch" and "merge origin/main
on feat" -- expect ALLOW and therefore only passed on a feature branch. Run on
``main`` the suite was red (132/134) and had been for as long as nothing ran
it. Pinning the branch here states the assumption those cases always had.

Cases run in-process for speed and coverage; a handful of subprocess smoke
tests at the end keep the real ``__main__`` path covered, which is what the
CLIs actually invoke.
"""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import types
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

HOOK_PATH = (
    Path(__file__).resolve().parents[1] / "tools" / "hooks" / "ai" / "block-dangerous-commands.py"
)

# Branch the hook sees. The migrated cases were authored against a feature
# branch; see the module docstring.
FEATURE_BRANCH = "feature/test"

# --- Bash command cases (no bypass env var) ---
BASH_CASES = [
    # The commands the block messages redirect to. Added here (#127) because the matrix
    # asserted `gh pr merge` is refused without ever asserting its replacement is not:
    # an over-broad pattern matching "merge" would break the documented workflow and
    # nothing would have caught it.
    (
        "doit pr_merge --pr=130",
        "ALLOW",
        "the task gh pr merge redirects to",
    ),
    (
        "doit pr --title=x --body-file=y.md",
        "ALLOW",
        "the task gh pr create redirects to",
    ),
    (
        "git status",
        "ALLOW",
        "safe command",
    ),
    (
        "git log --oneline",
        "ALLOW",
        "safe with flag",
    ),
    (
        'git commit -m "text with --admin"',
        "ALLOW",
        "double quoted",
    ),
    (
        'echo "--force flag"',
        "ALLOW",
        "double quoted 2",
    ),
    (
        "echo '--no-verify test'",
        "ALLOW",
        "single quoted",
    ),
    (
        'git commit -m "do not use --force"',
        "ALLOW",
        "flag in message",
    ),
    (
        "git commit -m \"$(cat <<'EOF'\n--admin mentioned in docs\nEOF\n)\"",
        "ALLOW",
        "heredoc with --admin",
    ),
    (
        "doit pr --body=\"$(cat <<'EOF'\n## Blocked Patterns\n- `--admin` (bypasses branch protection)\n- `rm -rf ~` (destructive)\nEOF\n)\"",  # noqa: E501 - migrated test data, kept verbatim
        "ALLOW",
        "heredoc with markdown",
    ),
    (
        "git push --force origin feat/my-feature",
        "ALLOW",
        "force push feature branch",
    ),
    (
        "git push -f origin fix/bugfix",
        "ALLOW",
        "-f push feature branch",
    ),
    (
        "git push --force-with-lease origin dev",
        "ALLOW",
        "force-with-lease feature",
    ),
    (
        "gh pr merge --admin",
        "BLOCK",
        "actual --admin flag",
    ),
    (
        "git commit --no-verify",
        "BLOCK",
        "actual --no-verify",
    ),
    (
        "git reset --hard HEAD",
        "BLOCK",
        "git reset --hard",
    ),
    (
        "git push --force origin main",
        "BLOCK",
        "force push to main",
    ),
    (
        "git push --force origin master",
        "BLOCK",
        "force push to master",
    ),
    (
        "git push -f origin main",
        "BLOCK",
        "force push -f to main",
    ),
    (
        "git push --force-with-lease origin main",
        "BLOCK",
        "force-with-lease to main",
    ),
    (
        "git push --force",
        "BLOCK",
        "force push no branch",
    ),
    (
        "git push -f",
        "BLOCK",
        "-f push no branch",
    ),
    (
        "git push --force origin",
        "BLOCK",
        "force push origin only",
    ),
    (
        "git push origin --delete main",
        "BLOCK",
        "delete remote main",
    ),
    (
        "git push origin :main",
        "BLOCK",
        "delete main colon syntax",
    ),
    (
        "git branch -D main",
        "BLOCK",
        "force delete local main",
    ),
    (
        "git branch -d master",
        "BLOCK",
        "delete local master",
    ),
    (
        "git push origin --delete feat/old-feature",
        "ALLOW",
        "delete remote feature",
    ),
    (
        "git branch -D feat/old-feature",
        "ALLOW",
        "delete local feature",
    ),
    (
        "git merge --ff-only some-branch",
        "ALLOW",
        "merge --ff-only",
    ),
    (
        "git merge --ff-only origin/main",
        "ALLOW",
        "merge --ff-only origin",
    ),
    (
        "git merge some-branch",
        "ALLOW",
        "merge on feature branch",
    ),
    (
        "git merge origin/main",
        "ALLOW",
        "merge origin/main on feat",
    ),
    (
        "gh issue create --title 'test'",
        "BLOCK",
        "gh issue create",
    ),
    (
        "gh pr create --title 'test'",
        "BLOCK",
        "gh pr create",
    ),
    (
        'gh issue create --title "test" --body "body"',
        "BLOCK",
        "gh issue create full",
    ),
    (
        "gh pr create --fill",
        "BLOCK",
        "gh pr create fill",
    ),
    (
        "gh pr merge 123",
        "BLOCK",
        "gh pr merge",
    ),
    (
        "gh pr merge --squash",
        "BLOCK",
        "gh pr merge squash",
    ),
    (
        "gh pr merge 123 --squash --delete-branch",
        "BLOCK",
        "gh pr merge full",
    ),
    (
        "uv add requests",
        "BLOCK",
        "uv add single package",
    ),
    (
        "uv add requests httpx",
        "BLOCK",
        "uv add multiple packages",
    ),
    (
        "uv add 'requests>=2.0'",
        "BLOCK",
        "uv add with version",
    ),
    (
        "uv add --dev pytest",
        "BLOCK",
        "uv add dev dependency",
    ),
    (
        "uv sync",
        "ALLOW",
        "uv sync",
    ),
    (
        "uv run pytest",
        "ALLOW",
        "uv run",
    ),
    (
        "uv pip list",
        "ALLOW",
        "uv pip list",
    ),
    (
        "uv remove requests",
        "ALLOW",
        "uv remove",
    ),
    (
        "doit release",
        "BLOCK",
        "doit release",
    ),
    (
        "doit release --dry-run",
        "BLOCK",
        "doit release dry-run",
    ),
    (
        "doit release_tag",
        "BLOCK",
        "doit release_tag",
    ),
    (
        "doit check",
        "ALLOW",
        "doit check",
    ),
    (
        "doit test",
        "ALLOW",
        "doit test",
    ),
    (
        "doit pr",
        "ALLOW",
        "doit pr",
    ),
    (
        "doit issue --type=bug",
        "ALLOW",
        "doit issue",
    ),
    (
        "gh pr edit 123 --add-label ready-to-merge",
        "BLOCK",
        "add ready-to-merge",
    ),
    (
        "gh pr edit --add-label ready-to-merge",
        "BLOCK",
        "add ready-to-merge no PR",
    ),
    (
        "gh issue edit 45 --add-label ready-to-merge",
        "BLOCK",
        "issue ready-to-merge",
    ),
    (
        "gh pr edit 123 --add-label bug",
        "ALLOW",
        "add bug label",
    ),
    (
        "gh pr edit 123 --add-label enhancement",
        "ALLOW",
        "add enhancement label",
    ),
    (
        "cd /path && doit release",
        "BLOCK",
        "chained doit release",
    ),
    (
        "cd /path && gh pr create --fill",
        "BLOCK",
        "chained gh pr create",
    ),
    (
        "cd /path && uv add requests",
        "BLOCK",
        "chained uv add",
    ),
    (
        "cd /path && git push --force origin main",
        "BLOCK",
        "chained force push main",
    ),
    (
        "git status; git push --force origin main",
        "BLOCK",
        "semicolon force push main",
    ),
    (
        "git status; git push origin --delete main",
        "BLOCK",
        "semicolon delete main",
    ),
    (
        "git log; git branch -D main",
        "BLOCK",
        "semicolon branch -D main",
    ),
    (
        "cd /path && doit check",
        "ALLOW",
        "chained doit check",
    ),
    (
        "cd /path && git status",
        "ALLOW",
        "chained git status",
    ),
    (
        "git status; git push origin feat/branch",
        "ALLOW",
        "semicolon push feature",
    ),
    (
        "gh issue list",
        "ALLOW",
        "gh issue list",
    ),
    (
        "gh pr list",
        "ALLOW",
        "gh pr list",
    ),
    (
        "gh issue view 123",
        "ALLOW",
        "gh issue view",
    ),
    (
        "gh pr view 456",
        "ALLOW",
        "gh pr view",
    ),
    (
        "gh issue close 123",
        "ALLOW",
        "gh issue close",
    ),
    (
        "gh pr close 123",
        "ALLOW",
        "gh pr close",
    ),
    (
        'echo "ALLOW_AI_READY_TO_MERGE=1" >> ~/.bashrc',
        "BLOCK",
        "persist rtm var to .bashrc",
    ),
    (
        "tee -a ~/.zshrc <<< 'export ALLOW_AI_READY_TO_MERGE=1'",
        "BLOCK",
        "persist rtm var to .zshrc",
    ),
    (
        "git push --force origin HEAD:main",
        "BLOCK",
        "force push HEAD:main refspec",
    ),
    (
        "git push origin +main",
        "BLOCK",
        "push +main force-push marker",
    ),
    (
        "git -C . push --force origin main",
        "BLOCK",
        "git -C global option push force",
    ),
    (
        "git -c core.pager=cat push --force origin main",
        "BLOCK",
        "git -c global option push force",
    ),
    (
        "git --git-dir=.git push --force origin main",
        "BLOCK",
        "git --git-dir push force",
    ),
    (
        "git push --force-with-lease=main origin HEAD:main",
        "BLOCK",
        "force-with-lease= prefix form",
    ),
    (
        'bash -c "git push --force origin main"',
        "BLOCK",
        "bash -c push force",
    ),
    (
        'sh -c "git push --force origin main"',
        "BLOCK",
        "sh -c push force",
    ),
    (
        'eval "git push --force origin main"',
        "BLOCK",
        "eval push force",
    ),
    (
        "git -C . branch -D main",
        "BLOCK",
        "git -C branch -D main",
    ),
    (
        'bash -c "git branch -D main"',
        "BLOCK",
        "bash -c branch -D main",
    ),
    (
        'bash -c "gh pr merge 1 --admin"',
        "BLOCK",
        "bash -c gh pr merge --admin",
    ),
    (
        "git push origin main:feature",
        "ALLOW",
        "refspec dst is feature",
    ),
    (
        "git push origin HEAD:refs/heads/feature",
        "ALLOW",
        "refspec HEAD to refs feature",
    ),
    (
        "git -C /other/repo push origin feature",
        "ALLOW",
        "git -C push feature",
    ),
    (
        'bash -c "echo main"',
        "ALLOW",
        "bash -c echo main is safe",
    ),
    (
        'echo "ALLOW_AI_READY_TO_MERGE=1" >> /tmp/notes.txt',
        "ALLOW",
        "rtm var to non-protected file",
    ),
    (
        'echo "PATH=/foo" >> ~/.bashrc',
        "ALLOW",
        "no var name write to .bashrc",
    ),
    (
        'git add .claude/settings.json && git commit -m "doc: mention ALLOW_AI_READY_TO_MERGE"',
        "ALLOW",
        "git add + commit message mentions var",
    ),
    (
        'echo "ALLOW_AI_READY_TO_MERGE is the env var" ',
        "ALLOW",
        "var name in echo without redirect",
    ),
    (
        "grep ALLOW_AI_READY_TO_MERGE .claude/settings.json",
        "ALLOW",
        "grep var name in protected file",
    ),
    (
        "cat .claude/settings.json | head -5 # ALLOW_AI_READY_TO_MERGE",
        "ALLOW",
        "read protected file with var in comment",
    ),
    (
        "sed -i 's/X/ALLOW_AI_READY_TO_MERGE=1/' ~/.bashrc",
        "BLOCK",
        "sed -i in-place edit on .bashrc",
    ),
    (
        "python -c \"open('/home/me/.bashrc','a').write('ALLOW_AI_READY_TO_MERGE=1')\"",
        "BLOCK",
        "python -c writing var to .bashrc",
    ),
    (
        'echo "ALLOW_AI_READY_TO_MERGE=1" >>~/.bashrc',
        "BLOCK",
        "no-space redirect to .bashrc",
    ),
    (
        "sed 's/X/ALLOW_AI_READY_TO_MERGE=1/' ~/.bashrc",
        "ALLOW",
        "sed without -i (read-only) on .bashrc",
    ),
    (
        "python script.py # ALLOW_AI_READY_TO_MERGE",
        "ALLOW",
        "python without -c flag",
    ),
    (
        "python -c \"print('ALLOW_AI_READY_TO_MERGE')\"",
        "ALLOW",
        "python -c print var name only",
    ),
]

# --- Governance label bypass cases (ALLOW_AI_READY_TO_MERGE=1 injected) ---
BYPASS_CASES = [
    (
        "gh pr edit 123 --add-label ready-to-merge",
        "ALLOW",
        "rtm label with bypass var",
    ),
    (
        "gh pr edit --add-label ready-to-merge",
        "ALLOW",
        "rtm label no PR with bypass var",
    ),
    (
        "gh issue edit 45 --add-label ready-to-merge",
        "ALLOW",
        "issue rtm label with bypass var",
    ),
]

# --- File-edit cases (Claude/Codex format) ---
EDIT_CASES: list[tuple[str, dict, str, str]] = [
    (
        "Edit",
        {
            "file_path": "~/.bashrc",
            "old_string": "",
            "new_string": "export ALLOW_AI_READY_TO_MERGE=1",
        },
        "BLOCK",
        "Edit .bashrc adding rtm var",
    ),
    (
        "Edit",
        {"file_path": ".envrc", "old_string": "", "new_string": "export ALLOW_AI_READY_TO_MERGE=1"},
        "BLOCK",
        "Edit .envrc adding rtm var",
    ),
    (
        "Write",
        {
            "file_path": ".claude/settings.local.json",
            "content": '{"env": {"ALLOW_AI_READY_TO_MERGE": "1"}}',
        },
        "BLOCK",
        "Write claude settings.local.json with rtm var",
    ),
    (
        "Edit",
        {
            "file_path": "~/.bashrc",
            "old_string": "",
            "new_string": "export PATH=$PATH:/usr/local/bin",
        },
        "ALLOW",
        "Edit .bashrc unrelated content",
    ),
    (
        "Edit",
        {
            "file_path": "/tmp/scratch.txt",
            "old_string": "",
            "new_string": "export ALLOW_AI_READY_TO_MERGE=1",
        },
        "ALLOW",
        "Edit non-protected file with rtm var",
    ),
    (
        "MultiEdit",
        {
            "file_path": "~/.zshrc",
            "edits": [
                {"old_string": "# aliases", "new_string": "# aliases\nalias ll='ls -la'"},
                {"old_string": "# env", "new_string": "# env\nexport ALLOW_AI_READY_TO_MERGE=1"},
            ],
        },
        "BLOCK",
        "MultiEdit .zshrc one edit has rtm var",
    ),
    (
        "write_file",
        {"file_path": ".envrc", "content": "export ALLOW_AI_READY_TO_MERGE=1\n"},
        "BLOCK",
        "Gemini write_file to .envrc with rtm var",
    ),
    (
        "replace",
        {
            "file_path": "~/.bashrc",
            "old_string": "",
            "new_string": "export ALLOW_AI_READY_TO_MERGE=1",
        },
        "BLOCK",
        "Gemini replace .bashrc with rtm var",
    ),
    (
        "write_file",
        {"file_path": "/tmp/scratch.txt", "content": "export ALLOW_AI_READY_TO_MERGE=1\n"},
        "ALLOW",
        "Gemini write_file non-protected with rtm var",
    ),
]

# --- File-edit cases (Copilot format) ---
COPILOT_EDIT_CASES: list[tuple[str, dict, str, str]] = [
    (
        "Edit",
        {
            "file_path": "~/.bashrc",
            "old_string": "",
            "new_string": "export ALLOW_AI_READY_TO_MERGE=1",
        },
        "BLOCK",
        "Copilot Edit .bashrc adding rtm var",
    ),
    (
        "Edit",
        {
            "file_path": "~/.bashrc",
            "old_string": "",
            "new_string": "export PATH=$PATH:/usr/local/bin",
        },
        "ALLOW",
        "Copilot Edit .bashrc unrelated content",
    ),
]

# --- Antigravity run_command cases ---
AGY_COMMAND_CASES = [
    (
        "git status",
        "ALLOW",
        "safe command",
    ),
    (
        "doit check",
        "ALLOW",
        "doit check",
    ),
    (
        'echo "--admin in quotes"',
        "ALLOW",
        "quoted flag is text",
    ),
    (
        "git push --force origin feat/x",
        "ALLOW",
        "force push feature branch",
    ),
    (
        "gh pr merge --admin",
        "BLOCK",
        "--admin flag",
    ),
    (
        "git commit --no-verify",
        "BLOCK",
        "--no-verify flag",
    ),
    (
        "git reset --hard HEAD",
        "BLOCK",
        "git reset --hard",
    ),
    (
        "git push --force origin main",
        "BLOCK",
        "force push to main",
    ),
    (
        "rm -rf /",
        "BLOCK",
        "rm -rf /",
    ),
    (
        "gh pr create --fill",
        "BLOCK",
        "gh pr create",
    ),
    (
        "uv add requests",
        "BLOCK",
        "uv add",
    ),
    (
        "cd /path && git push --force origin main",
        "BLOCK",
        "chained force push main",
    ),
]

# --- Antigravity write_to_file cases ---
AGY_EDIT_CASES: list[tuple[str, str, str, str]] = [
    (
        "~/.bashrc",
        "export ALLOW_AI_READY_TO_MERGE=1",
        "BLOCK",
        "write_to_file .bashrc rtm var",
    ),
    (
        ".envrc",
        "export ALLOW_AI_READY_TO_MERGE=1\n",
        "BLOCK",
        "write_to_file .envrc rtm var",
    ),
    (
        "/tmp/scratch.txt",
        "export ALLOW_AI_READY_TO_MERGE=1",
        "ALLOW",
        "write_to_file non-protected target",
    ),
    (
        "~/.bashrc",
        "export PATH=$PATH:/usr/local/bin",
        "ALLOW",
        "write_to_file .bashrc no var",
    ),
]


def _load_hook() -> types.ModuleType:
    """Load the hook script as a fresh module instance.

    The filename contains hyphens, so it is not importable by name.
    """
    spec = importlib.util.spec_from_file_location("block_dangerous_commands", HOOK_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"could not load hook from {HOOK_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def hook() -> Iterator[types.ModuleType]:
    """Load a fresh copy of the hook module for each test."""
    module = _load_hook()
    sys.modules["block_dangerous_commands"] = module
    try:
        yield module
    finally:
        sys.modules.pop("block_dangerous_commands", None)


def _outcome_exit_code(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    payload: str,
) -> str:
    """Run the hook on *payload*; BLOCK is exit 2 (Claude/Gemini/Codex)."""
    monkeypatch.setattr(hook, "get_current_branch", lambda: FEATURE_BRANCH)
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    return "BLOCK" if int(hook.main()) == 2 else "ALLOW"


def _outcome_stdout(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    payload: str,
    key: str,
) -> str:
    """Run the hook on *payload*; BLOCK is a stdout deny (Copilot/Antigravity).

    A safe operation prints nothing and defers to the CLI's own permission
    flow, which reads as ALLOW.
    """
    monkeypatch.setattr(hook, "get_current_branch", lambda: FEATURE_BRANCH)
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    hook.main()
    out = capsys.readouterr().out
    try:
        return "BLOCK" if json.loads(out).get(key) == "deny" else "ALLOW"
    except json.JSONDecodeError:
        return "ALLOW"


def _ids(cases: list, desc_index: int) -> list[str]:
    """Build unique, readable test ids from each case's description."""
    return [f"{i:03d}-{case[desc_index]}" for i, case in enumerate(cases)]


@pytest.mark.parametrize(
    ("command", "expected", "description"), BASH_CASES, ids=_ids(BASH_CASES, 2)
)
def test_bash_command(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    expected: str,
    description: str,
) -> None:
    """Bash-tool commands block or allow as the migrated matrix specifies."""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    assert _outcome_exit_code(hook, monkeypatch, payload) == expected, description


@pytest.mark.parametrize(
    ("command", "expected", "description"), BYPASS_CASES, ids=_ids(BYPASS_CASES, 2)
)
def test_governance_label_bypass(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    expected: str,
    description: str,
) -> None:
    """With ALLOW_AI_READY_TO_MERGE=1 the human has opted in, so the label is allowed."""
    monkeypatch.setenv("ALLOW_AI_READY_TO_MERGE", "1")
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    assert _outcome_exit_code(hook, monkeypatch, payload) == expected, description


@pytest.mark.parametrize(
    ("tool_name", "tool_input", "expected", "description"), EDIT_CASES, ids=_ids(EDIT_CASES, 3)
)
def test_file_edit_claude_format(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    tool_input: dict,
    expected: str,
    description: str,
) -> None:
    """File edits that would persist the bypass env var are blocked."""
    payload = json.dumps({"tool_name": tool_name, "tool_input": tool_input})
    assert _outcome_exit_code(hook, monkeypatch, payload) == expected, description


@pytest.mark.parametrize(
    ("tool_name", "tool_input", "expected", "description"),
    COPILOT_EDIT_CASES,
    ids=_ids(COPILOT_EDIT_CASES, 3),
)
def test_file_edit_copilot_format(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tool_name: str,
    tool_input: dict,
    expected: str,
    description: str,
) -> None:
    """Copilot sends camelCase keys and blocks via a stdout deny payload."""
    payload = json.dumps({"toolName": tool_name, "toolArgs": json.dumps(tool_input)})
    outcome = _outcome_stdout(hook, monkeypatch, capsys, payload, "permissionDecision")
    assert outcome == expected, description


@pytest.mark.parametrize(
    ("command", "expected", "description"), AGY_COMMAND_CASES, ids=_ids(AGY_COMMAND_CASES, 2)
)
def test_antigravity_run_command(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
    expected: str,
    description: str,
) -> None:
    """Antigravity sends a nested toolCall and blocks via a stdout deny payload."""
    payload = json.dumps({"toolCall": {"name": "run_command", "args": {"CommandLine": command}}})
    assert _outcome_stdout(hook, monkeypatch, capsys, payload, "decision") == expected, description


@pytest.mark.parametrize(
    ("target", "content", "expected", "description"), AGY_EDIT_CASES, ids=_ids(AGY_EDIT_CASES, 3)
)
def test_antigravity_write_to_file(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    target: str,
    content: str,
    expected: str,
    description: str,
) -> None:
    """Antigravity's write_to_file uses TargetFile / CodeContent."""
    payload = json.dumps(
        {
            "toolCall": {
                "name": "write_to_file",
                "args": {"TargetFile": target, "CodeContent": content},
            }
        }
    )
    assert _outcome_stdout(hook, monkeypatch, capsys, payload, "decision") == expected, description


# --- Subprocess smoke tests -------------------------------------------------
#
# The parametrized cases above run in-process, which is fast and reports
# coverage but bypasses the script's entry point. These few exercise the real
# `__main__` path -- the exit code and stdout a CLI actually observes -- which
# is what the deleted standalone script used to be the only check on.


def _run_subprocess(payload: str) -> subprocess.CompletedProcess[str]:
    """Invoke the hook as a real subprocess, the way a CLI does."""
    return subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
    )


def test_subprocess_blocks_a_dangerous_bash_command() -> None:
    """Exit code 2 is what Claude/Gemini/Codex read as a block."""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git commit --no-verify"}})
    proc = _run_subprocess(payload)
    assert proc.returncode == 2
    assert "BLOCKED" in proc.stderr


def test_subprocess_allows_a_safe_bash_command() -> None:
    """A safe command exits 0 and says nothing."""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git status"}})
    proc = _run_subprocess(payload)
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_subprocess_blocks_via_stdout_for_antigravity() -> None:
    """Antigravity reads a stdout deny payload and exit 0, not the exit code."""
    payload = json.dumps(
        {"toolCall": {"name": "run_command", "args": {"CommandLine": "git commit --no-verify"}}}
    )
    proc = _run_subprocess(payload)
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["decision"] == "deny"


def test_subprocess_blocks_via_stdout_for_copilot() -> None:
    """Copilot reads ``permissionDecision`` from stdout."""
    payload = json.dumps(
        {"toolName": "bash", "toolArgs": json.dumps({"command": "git commit --no-verify"})}
    )
    proc = _run_subprocess(payload)
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["permissionDecision"] == "deny"


# --- Codex apply_patch cases (issue #681) ----------------------------------
#
# Codex's shell tool is `Bash` with the default payload schema, so every case in
# BASH_CASES above already covers Codex's command path. Its *file-edit* tool is
# `apply_patch`, which no other agent has: the payload is command-shaped, so it
# is checked both as a command and as a set of file edits.
#
# Before this was handled, an apply_patch persisting ALLOW_AI_READY_TO_MERGE to
# ~/.bashrc was ALLOWED, while the identical edit through Claude's Write tool
# was blocked.

_PATCH_HEADER = "apply_patch <<PATCH\n*** Begin Patch\n"
_PATCH_FOOTER = "*** End Patch\nPATCH"


def _patch(*sections: str) -> str:
    """Build an apply_patch envelope from ``*** … File:`` sections."""
    return _PATCH_HEADER + "".join(sections) + _PATCH_FOOTER


APPLY_PATCH_CASES: list[tuple[str, str, str]] = [
    (
        _patch("*** Update File: ~/.bashrc\n+export ALLOW_AI_READY_TO_MERGE=1\n"),
        "BLOCK",
        "apply_patch persists rtm var to .bashrc",
    ),
    (
        _patch("*** Update File: .envrc\n+export ALLOW_AI_READY_TO_MERGE=1\n"),
        "BLOCK",
        "apply_patch persists rtm var to .envrc",
    ),
    (
        # The bypass hides in the second file: the parser must check every target.
        _patch(
            "*** Update File: src/ok.py\n+print(1)\n",
            "*** Update File: ~/.zshrc\n+export ALLOW_AI_READY_TO_MERGE=1\n",
        ),
        "BLOCK",
        "apply_patch rtm var in the second of two files",
    ),
    (
        _patch("*** Add File: src/new.py\n+print('hello')\n"),
        "ALLOW",
        "apply_patch ordinary source edit",
    ),
    (
        _patch("*** Update File: README.md\n+Mentions ALLOW_AI_READY_TO_MERGE in prose.\n"),
        "ALLOW",
        "apply_patch names the var in an unprotected file",
    ),
    (
        # The envelope is a shell command, so command scanning applies to it.
        "git commit --no-verify && " + _patch("*** Update File: src/ok.py\n+print(1)\n"),
        "BLOCK",
        "apply_patch envelope carrying a dangerous flag",
    ),
]


@pytest.mark.parametrize(
    ("command", "expected", "description"), APPLY_PATCH_CASES, ids=_ids(APPLY_PATCH_CASES, 2)
)
def test_codex_apply_patch(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    expected: str,
    description: str,
) -> None:
    """Codex file edits are checked as both a command and a set of file writes."""
    payload = json.dumps({"tool_name": "apply_patch", "tool_input": {"command": command}})
    assert _outcome_exit_code(hook, monkeypatch, payload) == expected, description


def test_codex_shell_tool_uses_the_default_schema() -> None:
    """Codex's shell tool name and payload shape, as observed from a live session.

    Recorded as a test rather than a comment because it is the premise the
    `^Bash$` matcher in `.codex/config.toml` rests on.
    """
    assert "Bash" in _load_hook()._BASH_TOOL_NAMES


# --- Secret exposure cases (issue #682) ------------------------------------
#
# Only Codex can strip secrets from the child environment; Claude, Copilot and
# Antigravity have no such setting, so the shared hook carries the part that
# reaches all four: environment dumps and credential-store reads.
#
# Two distinctions are load-bearing, and both were found by the control firing
# on this repository's own workflow within minutes of being written:
#
#   * invocation vs dump -- `env -u VAR cmd` is used constantly here
#   * running vs mentioning -- a heredoc body tokenizes exactly like an
#     argument list, so a scan over every token treats test fixtures and
#     documentation as invocations
#
# The last two cases pin the second distinction directly.

SECRET_EXPOSURE_CASES: list[tuple[str, str, str]] = [
    ("env", "BLOCK", "bare env dumps the environment"),
    ("printenv", "BLOCK", "bare printenv dumps the environment"),
    ("printenv PYPI_TOKEN", "BLOCK", "printenv of a secret-named var"),
    ("printenv MY_API_KEY", "BLOCK", "printenv matching the *_API_KEY pattern"),
    ("printenv PATH", "ALLOW", "printenv of a non-secret var"),
    ("env -u FORCE_COLOR doit check", "ALLOW", "env -u is an invocation not a dump"),
    ("env VAR=1 make", "ALLOW", "env with assignment is an invocation"),
    ("env -i PATH=/usr/bin sh -c true", "ALLOW", "env -i is an invocation"),
    ("git status && env", "BLOCK", "env dump after a shell separator"),
    ("cat ~/.pypirc", "BLOCK", "reads the PyPI credential store"),
    ("cat ~/.aws/credentials", "BLOCK", "reads AWS credentials"),
    ("cp ~/.docker/config.json /tmp/x", "BLOCK", "copies the docker credential store"),
    ("cat credentials", "ALLOW", "a bare 'credentials' file outside .aws"),
    ("grep -rn pypirc docs/", "ALLOW", "searching for the name is not reading the file"),
    ("cat README.md", "ALLOW", "an ordinary file read"),
    # Who receives the body, and in what language. `bash <<EOF` runs it as shell,
    # so shell patterns in it are real commands. `cat >> notes.md` writes it to a
    # file, and `python3 -` runs it as Python -- where `printenv PYPI_TOKEN` is a
    # SyntaxError, not a dump. Only the shell case is scanned (#762).
    (
        "cat >> notes.md <<EOF\ncat ~/.netrc\nEOF",
        "ALLOW",
        "a data heredoc: the body is written, not run",
    ),
    (
        "python3 - <<EOF\nprintenv PYPI_TOKEN\nEOF",
        "ALLOW",
        "python3 - runs Python: that body is a SyntaxError, not a dump",
    ),
    ("bash <<EOF\ncat ~/.netrc\nEOF", "BLOCK", "bash executes the credential read in its body"),
    ("sh <<EOF\ncat ~/.pypirc\nEOF", "BLOCK", "sh executes the credential read in its body"),
    ("zsh <<EOF\nprintenv MY_API_KEY\nEOF", "BLOCK", "zsh executes the dump in its body"),
    ("dash <<EOF\nenv\nEOF", "BLOCK", "dash executes the bare env dump in its body"),
    (
        "python - <<EOF\ncat ~/.aws/credentials\nEOF",
        "ALLOW",
        "same: a shell line in a Python heredoc does not run",
    ),
    (
        "python3 script.py <<EOF\nprintenv PYPI_TOKEN\nEOF",
        "ALLOW",
        "a script reading stdin data, not code",
    ),
    (
        'bash -c "cat ~/.netrc"',
        "BLOCK",
        "the -c form was already covered; the heredoc must match it",
    ),
    # Deliberately NOT blocked -- see docs/development/ai/command-blocking.md.
    # Blocking $VAR interpolation gives false assurance while being trivially
    # avoided, and legitimate uses are common.
    ("echo $PYPI_TOKEN", "ALLOW", "var interpolation is deliberately not blocked"),
]


@pytest.mark.parametrize(
    ("command", "expected", "description"),
    SECRET_EXPOSURE_CASES,
    ids=_ids(SECRET_EXPOSURE_CASES, 2),
)
def test_secret_exposure(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    expected: str,
    description: str,
) -> None:
    """Environment dumps and credential reads are blocked for every agent."""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    assert _outcome_exit_code(hook, monkeypatch, payload) == expected, description


# --- Heredoc bodies: data or code (#762) -----------------------------------
#
# `check_command` recurses into `bash -c <payload>`, but a heredoc on stdin is
# not `-c`, so its body was never re-scanned. Checks matching a token in any
# position caught it anyway; checks needing a command position did not, so
# `bash <<EOF cat ~/.netrc EOF` ran while `bash -c "cat ~/.netrc"` was blocked.
#
# The distinction the parser has to get right is who receives the body: an
# interpreter reading stdin executes it, everything else consumes it as text.
# These cases pin that boundary and the parsing around it.

HEREDOC_BODY_CASES: list[tuple[str, str, str]] = [
    # Interpreters: the body runs, so it is scanned.
    ("bash <<-EOF\n\tcat ~/.netrc\n\tEOF", "BLOCK", "<<- with a tab-indented terminator"),
    ("bash <<'END'\ncat ~/.pypirc\nEND", "BLOCK", "quoted delimiter"),
    ("/bin/bash <<EOF\ncat ~/.netrc\nEOF", "BLOCK", "interpreter named by absolute path"),
    ("cd /tmp && bash <<EOF\ncat ~/.netrc\nEOF", "BLOCK", "interpreter after a shell separator"),
    (
        "bash <<EOF\necho one\necho two\ncat ~/.aws/credentials\nEOF",
        "BLOCK",
        "danger on the third line of the body",
    ),
    (
        "cat > a.md <<A\nhello\nA\nbash <<B\ncat ~/.netrc\nB",
        "BLOCK",
        "a data heredoc first, then an interpreter one",
    ),
    # Data consumers: the body is text, so it is not scanned.
    (
        "cat >> notes.md <<EOF\nprintenv PYPI_TOKEN\nEOF",
        "ALLOW",
        "written to a file, not run",
    ),
    # Known limitation, and #759's territory rather than this one's: a data
    # heredoc naming a pattern that any check matches positionally -- `--admin`,
    # `gh issue create`, or a `bash -c` payload the outer tokenization reaches --
    # is still blocked. That predates this change and is untouched by it; the
    # case is pinned here so the gap is recorded rather than rediscovered.
    (
        "cat >> notes.md <<EOF\nbash -c 'cat ~/.netrc'\nEOF",
        "BLOCK",
        "known limitation: outer tokenization reaches a -c payload in a data heredoc",
    ),
    ("python3 script.py <<EOF\nprintenv PYPI_TOKEN\nEOF", "ALLOW", "stdin for a named script"),
    ("bash script.sh <<EOF\ncat ~/.netrc\nEOF", "ALLOW", "stdin for a named shell script"),
    # Parsing edges.
    ("bash <<EOF\necho hello", "ALLOW", "unterminated heredoc, benign body"),
    ("cat > n.md <<EOF\nEOF is the delimiter\nEOF", "ALLOW", "delimiter word inside the body"),
    ('python3 -c "print(1)"', "ALLOW", "the -c path is untouched by heredoc handling"),
]


@pytest.mark.parametrize(
    ("command", "expected", "description"),
    HEREDOC_BODY_CASES,
    ids=_ids(HEREDOC_BODY_CASES, 2),
)
def test_heredoc_body(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    expected: str,
    description: str,
) -> None:
    """A heredoc an interpreter will execute is scanned; one consumed as text is not."""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    assert _outcome_exit_code(hook, monkeypatch, payload) == expected, description
