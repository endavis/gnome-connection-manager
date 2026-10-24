"""`doit worktree` must build the worktree's .venv as CI builds GCM's (#327).

The vendored task builds it with `uv sync` alone, which leaves out the system's site
packages, the only place PyGObject comes from. In a worktree `gi` did not import, and the
suite failed and skipped there. GCM's override in tools/doit/gcm.py runs the vendored task
and then builds that .venv again, from /usr/bin/python3 with --system-site-packages.

Git and uv are faked here, as the template's own tests of the task fake them, so nothing
runs a real worktree or venv.
"""

from __future__ import annotations

import runpy
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from tools.doit import gcm, git

REPO = Path(__file__).resolve().parents[1]
BRANCH = "fix/1-example"


@pytest.fixture
def faked(tmp_path, monkeypatch):
    """Git, which lists the new worktree once made, and uv, which records each command."""
    monkeypatch.chdir(tmp_path)
    worktree = tmp_path / "worktrees" / BRANCH

    def git(cmd, **_kwargs):
        listing = ""
        if cmd[1:3] == ["worktree", "list"]:
            listing = (
                f"worktree {tmp_path}\nHEAD 1\nbranch refs/heads/main\n\n"
                f"worktree {worktree}\nHEAD 1\nbranch refs/heads/{BRANCH}\n"
            )
        return subprocess.CompletedProcess(cmd, 0, stdout=listing, stderr="")

    uv = MagicMock()
    with (
        patch("tools.doit.git.subprocess.run", side_effect=git) as git_run,
        patch("tools.doit.git.run_streamed", uv),
        patch("tools.doit.gcm.run_streamed", uv),
    ):
        yield worktree, git_run, uv


def create_worktree():
    """Run the task's actions in order, as doit does."""
    for action in gcm.task_worktree()["actions"]:
        action(branch=BRANCH)


def test_the_venv_is_built_again_from_the_system_python_with_its_packages(faked, monkeypatch):
    worktree, _, uv = faked
    monkeypatch.setenv("VIRTUAL_ENV", "/main/.venv")
    monkeypatch.setenv("UV_CACHE_DIR", "tmp/.uv_cache")

    create_worktree()

    commands = [" ".join(made.args[0]) for made in uv.call_args_list]
    assert commands[-2:] == [
        "uv venv --system-site-packages --python /usr/bin/python3 --clear --quiet",
        "uv sync --all-extras --dev --quiet",
    ], "the venv must be built last, after everything the vendored task runs"
    assert commands[:-2], "the vendored task must run first"
    vendored, venv, sync = uv.call_args_list[-3], uv.call_args_list[-2], uv.call_args_list[-1]
    for ours in (venv, sync):
        assert ours.kwargs["cwd"] == worktree
        # The environment the vendored sync gets: no VIRTUAL_ENV naming the main
        # checkout's .venv, and this checkout's cache rather than one inside the worktree.
        assert ours.kwargs["env"] == vendored.kwargs["env"]
        assert "VIRTUAL_ENV" not in ours.kwargs["env"]
        assert ours.kwargs["env"]["UV_CACHE_DIR"] == str(Path("tmp/.uv_cache").resolve())


def test_the_commands_are_the_ones_ci_runs():
    workflow = yaml.safe_load((REPO / ".github" / "workflows" / "ci.yml").read_text())
    runs = [step.get("run", "") for job in workflow["jobs"].values() for step in job["steps"]]

    venv, sync = " ".join(gcm.VENV_COMMAND), " ".join(gcm.SYNC_COMMAND)
    assert any(venv in run and sync in run for run in runs), (venv, sync)


def test_a_failed_build_keeps_the_worktree_and_says_what_to_run(faked, capsys):
    _, git_run, uv = faked

    def fail_to_build(cmd, **_kwargs):
        if cmd[:2] == ["uv", "venv"]:
            raise subprocess.CalledProcessError(2, cmd)

    uv.side_effect = fail_to_build

    with pytest.raises(SystemExit) as exited:
        create_worktree()

    assert exited.value.code == 1
    out = capsys.readouterr().out
    assert "  uv venv --system-site-packages --python /usr/bin/python3 --clear\n" in out
    assert "  uv sync --all-extras --dev\n" in out
    git_commands = [made.args[0][1:3] for made in git_run.call_args_list]
    assert ["worktree", "remove"] not in git_commands


def test_dodo_installs_the_override_whichever_task_discovery_finds(monkeypatch):
    """Both git.py and gcm.py define task_worktree, and discovery's order is rglob's."""
    monkeypatch.setattr("tools.doit.discover_tasks", lambda: {"task_worktree": git.task_worktree})

    tasks = runpy.run_path(str(REPO / "dodo.py"))

    assert tasks["task_worktree"] is gcm.task_worktree
