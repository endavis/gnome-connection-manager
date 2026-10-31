"""Tests for the ``template-update-check`` SessionStart hook.

The hook script lives at ``tools/hooks/ai/template-update-check.py``. Its filename contains
hyphens, so it is loaded via ``importlib``. ``git`` is never run for real here: ``subprocess.run``
is replaced by a fake so no test touches the network.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

HOOK_PATH = (
    Path(__file__).resolve().parents[1] / "tools" / "hooks" / "ai" / "template-update-check.py"
)

REMOTE = "a" * 40
OLD = "b" * 40
NOW = 1_000_000.0


def _load_hook() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("template_update_check", HOOK_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"could not load hook from {HOOK_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def hook() -> types.ModuleType:
    """Load a fresh copy of the hook module."""
    return _load_hook()


class FakeGit:
    """Stand-in for ``subprocess.run`` that answers the two git calls the hook makes."""

    def __init__(
        self,
        origin: str | None = "https://github.com/someone/project.git",
        remote_head: str | None = REMOTE,
        ls_remote_error: Exception | None = None,
        ls_remote_stdout: str | None = None,
        ls_remote_code: int = 0,
    ) -> None:
        self.origin = origin
        self.remote_head = remote_head
        self.ls_remote_error = ls_remote_error
        self.ls_remote_stdout = ls_remote_stdout
        self.ls_remote_code = ls_remote_code
        self.ls_remote_calls = 0
        self.calls = 0

    def __call__(
        self,
        cmd: list[str],
        *,
        timeout: float = 0,
        env: dict[str, str] | None = None,
        **_: object,
    ) -> subprocess.CompletedProcess[str]:
        self.calls += 1
        if cmd[:2] == ["git", "config"]:
            if self.origin is None:
                return subprocess.CompletedProcess(cmd, 1, "", "")
            return subprocess.CompletedProcess(cmd, 0, self.origin + "\n", "")
        assert cmd[:2] == ["git", "ls-remote"]
        assert env is not None
        assert 0 < timeout <= 2
        assert env["GIT_TERMINAL_PROMPT"] == "0"
        self.ls_remote_calls += 1
        if self.ls_remote_error is not None:
            raise self.ls_remote_error
        if self.ls_remote_stdout is not None:
            return subprocess.CompletedProcess(cmd, self.ls_remote_code, self.ls_remote_stdout, "")
        out = f"{self.remote_head}\trefs/heads/main\n"
        return subprocess.CompletedProcess(cmd, self.ls_remote_code, out, "")


def _write_settings(root: Path, commit: str | None = OLD, body: str | None = None) -> None:
    path = root / ".config" / "pyproject_template" / "settings.toml"
    path.parent.mkdir(parents=True)
    if body is None:
        body = f'[template]\ncommit = "{commit}"\n' if commit is not None else "[template]\n"
    path.write_text(body, encoding="utf-8")


def _run(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
    git: FakeGit,
    now: float = NOW,
) -> str | None:
    monkeypatch.delenv("PYPROJECT_TEMPLATE_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(hook.subprocess, "run", git)
    result: str | None = hook.check(root, now)
    return result


def test_up_to_date_is_silent(
    hook: types.ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_settings(tmp_path, REMOTE)
    assert _run(hook, monkeypatch, tmp_path, FakeGit()) is None


def test_behind_prints_short_sha_and_skill(
    hook: types.ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_settings(tmp_path, OLD)
    message = _run(hook, monkeypatch, tmp_path, FakeGit())
    assert message is not None
    assert OLD[:7] in message
    assert "template-sync" in message
    assert "\n" not in message


def test_short_sha_prefix_counts_as_match(
    hook: types.ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_settings(tmp_path, REMOTE[:8])
    assert _run(hook, monkeypatch, tmp_path, FakeGit()) is None


def test_sha_shorter_than_seven_chars_needs_exact_match(hook: types.ModuleType) -> None:
    assert not hook.shas_match("aaa", REMOTE)
    assert hook.shas_match("aaa", "aaa")


def test_cache_hit_skips_network(
    hook: types.ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_settings(tmp_path, OLD)
    git = FakeGit()
    assert _run(hook, monkeypatch, tmp_path, git) is not None
    assert git.ls_remote_calls == 1
    assert _run(hook, monkeypatch, tmp_path, git, now=NOW + 60) is not None
    assert git.ls_remote_calls == 1


def test_expired_cache_refetches_and_rewrites(
    hook: types.ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_settings(tmp_path, OLD)
    git = FakeGit()
    _run(hook, monkeypatch, tmp_path, git)
    later = NOW + hook.CACHE_TTL_SECONDS + 1
    _run(hook, monkeypatch, tmp_path, git, now=later)
    assert git.ls_remote_calls == 2
    cache = json.loads((tmp_path / "tmp" / "template-update-check.json").read_text())
    assert cache == {"checked_at": later, "sha": REMOTE}


def test_cached_null_is_silent_without_fetch(
    hook: types.ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_settings(tmp_path, OLD)
    (tmp_path / "tmp").mkdir()
    (tmp_path / "tmp" / "template-update-check.json").write_text(
        json.dumps({"checked_at": NOW, "sha": None})
    )
    git = FakeGit()
    assert _run(hook, monkeypatch, tmp_path, git, now=NOW + 10) is None
    assert git.ls_remote_calls == 0


@pytest.mark.parametrize(
    "content", ["not json", "[]", '{"checked_at": "x", "sha": "a"}', '{"sha": 1}']
)
def test_corrupt_cache_counts_as_miss(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    content: str,
) -> None:
    _write_settings(tmp_path, OLD)
    (tmp_path / "tmp").mkdir()
    (tmp_path / "tmp" / "template-update-check.json").write_text(content)
    git = FakeGit()
    assert _run(hook, monkeypatch, tmp_path, git) is not None
    assert git.ls_remote_calls == 1


@pytest.mark.parametrize(
    "git",
    [
        FakeGit(ls_remote_error=subprocess.TimeoutExpired(["git"], 2)),
        FakeGit(ls_remote_error=OSError("no git")),
        FakeGit(ls_remote_code=128, ls_remote_stdout=""),
        FakeGit(ls_remote_stdout="garbage"),
        FakeGit(ls_remote_stdout="zzzz\trefs/heads/main\n"),
        FakeGit(ls_remote_stdout=f"{REMOTE}\trefs/heads/other\n"),
    ],
    ids=["timeout", "oserror", "nonzero", "malformed", "non-hex", "wrong-ref"],
)
def test_offline_is_silent_and_failure_is_cached(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    git: FakeGit,
) -> None:
    _write_settings(tmp_path, OLD)
    assert _run(hook, monkeypatch, tmp_path, git) is None
    cache = json.loads((tmp_path / "tmp" / "template-update-check.json").read_text())
    assert cache["sha"] is None
    assert _run(hook, monkeypatch, tmp_path, git, now=NOW + 5) is None
    assert git.ls_remote_calls == 1


def test_missing_settings_is_silent(
    hook: types.ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    git = FakeGit()
    assert _run(hook, monkeypatch, tmp_path, git) is None
    assert git.calls == 0


@pytest.mark.parametrize(
    "body",
    [
        "",
        "[project]\nname = 'x'\n",
        "[template]\n",
        '[template]\ncommit = ""\n',
        "[template\n",
        "template = 3\n",
    ],
    ids=["empty", "no-table", "no-commit", "empty-commit", "invalid-toml", "not-a-table"],
)
def test_settings_without_commit_is_silent(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    body: str,
) -> None:
    _write_settings(tmp_path, body=body)
    git = FakeGit()
    assert _run(hook, monkeypatch, tmp_path, git) is None
    assert git.ls_remote_calls == 0


def test_opt_out_touches_nothing(
    hook: types.ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_settings(tmp_path, OLD)

    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("opted out, nothing may run")

    monkeypatch.setenv("PYPROJECT_TEMPLATE_UPDATE_CHECK", "0")
    monkeypatch.setattr(hook.subprocess, "run", boom)
    monkeypatch.setattr(hook, "read_recorded_commit", boom)
    assert hook.check(tmp_path, NOW) is None
    assert hook.main(["--host=claude"]) == 0


@pytest.mark.parametrize(
    "origin",
    [
        "https://github.com/endavis/pyproject-template",
        "https://github.com/endavis/pyproject-template.git",
        "https://github.com/endavis/pyproject-template/",
        "git@github.com:endavis/pyproject-template.git",
        "ssh://git@github.com/endavis/pyproject-template.git",
    ],
)
def test_template_repo_itself_is_silent(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    origin: str,
) -> None:
    _write_settings(tmp_path, OLD)
    git = FakeGit(origin=origin)
    assert _run(hook, monkeypatch, tmp_path, git) is None
    assert git.ls_remote_calls == 0


@pytest.mark.parametrize(
    "origin",
    [
        "https://github.com/endavis/pyproject-template-foo.git",
        "https://github.com/other/pyproject-template.git",
        "https://github.com/xendavis/pyproject-template",
        None,
    ],
)
def test_forks_and_missing_origin_are_not_the_template(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    origin: str | None,
) -> None:
    _write_settings(tmp_path, OLD)
    assert _run(hook, monkeypatch, tmp_path, FakeGit(origin=origin)) is not None


def test_git_failure_in_template_check_is_not_the_template(
    hook: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise OSError("no git")

    monkeypatch.setattr(hook.subprocess, "run", boom)
    assert hook.is_template_repo(Path(".")) is False


YELLOW = "\033[33m"
RESET = "\033[0m"


def test_format_output_per_host(hook: types.ModuleType) -> None:
    msg = "pyproject-template has updates"
    env: dict[str, str] = {}
    claude = json.loads(hook.format_output(msg, "claude", env))
    assert claude == {
        "systemMessage": f"{YELLOW}{msg}{RESET}",
        "additionalContext": f"Tell the user, in one line: {msg}",
    }
    assert json.loads(hook.format_output(msg, "codex", env)) == {
        "systemMessage": f"{YELLOW}{msg}{RESET}"
    }
    assert json.loads(hook.format_output(msg, "copilot", env)) == {"additionalContext": msg}
    agy = json.loads(hook.format_output(msg, "antigravity", env))
    assert agy["injectSteps"][0]["systemMessage"]["systemMessage"] == (
        f"Tell the user, in one line: {msg}"
    )
    assert hook.format_output(msg, None, env) == msg


def test_no_color_makes_system_message_plain(hook: types.ModuleType) -> None:
    msg = "m"
    for host in ("claude", "codex"):
        out = json.loads(hook.format_output(msg, host, {"NO_COLOR": "1"}))
        assert out["systemMessage"] == msg


def test_empty_no_color_still_colours(hook: types.ModuleType) -> None:
    out = json.loads(hook.format_output("m", "codex", {"NO_COLOR": ""}))
    assert out["systemMessage"] == f"{YELLOW}m{RESET}"


def test_format_output_reads_process_env_by_default(
    hook: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    assert json.loads(hook.format_output("m", "codex"))["systemMessage"] == "m"
    monkeypatch.delenv("NO_COLOR")
    assert json.loads(hook.format_output("m", "codex"))["systemMessage"] == f"{YELLOW}m{RESET}"


def test_main_codex_prints_yellow_system_message_only(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_settings(tmp_path, OLD)
    monkeypatch.delenv("PYPROJECT_TEMPLATE_UPDATE_CHECK", raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(hook, "ROOT", tmp_path)
    monkeypatch.setattr(hook.subprocess, "run", FakeGit())
    assert hook.main(["--host=codex"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert list(out) == ["systemMessage"]
    assert out["systemMessage"].startswith(YELLOW)


def test_main_prints_for_host_and_exits_zero(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_settings(tmp_path, OLD)
    monkeypatch.delenv("PYPROJECT_TEMPLATE_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(hook, "ROOT", tmp_path)
    monkeypatch.setattr(hook.subprocess, "run", FakeGit())
    assert hook.main(["--host=claude"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert "systemMessage" in out
    assert out["additionalContext"].startswith("Tell the user, in one line: ")


def test_main_never_raises(hook: types.ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.delenv("PYPROJECT_TEMPLATE_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(hook, "check", boom)
    assert hook.main([]) == 0


def test_hook_does_not_import_pyproject_template() -> None:
    tree = ast.parse(HOOK_PATH.read_text(encoding="utf-8"))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    assert not [m for m in modules if "pyproject_template" in m]


def test_subprocess_smoke_exits_zero_with_bad_stdin(tmp_path: Path) -> None:
    """Run the script for real with the opt-out set, so no network is involved."""
    env = {**os.environ, "PYPROJECT_TEMPLATE_UPDATE_CHECK": "0"}
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH), "--host=claude"],
        input="not json",
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout == ""
