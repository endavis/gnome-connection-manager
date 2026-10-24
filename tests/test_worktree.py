"""What `doit worktree` builds, and what `doit pr_merge` leaves of it (#327, #332).

The vendored task builds the worktree's .venv with `uv sync` alone, which leaves out the
system's site packages, the only place PyGObject comes from. In a worktree `gi` did not
import, and the suite failed and skipped there. GCM's override in tools/doit/gcm.py runs
the vendored task and then builds that .venv again, from /usr/bin/python3 with
--system-site-packages (#327).

`doit pr_merge` removes a merged worktree only while every file git ignores there can be
rebuilt. Under a bare `tmp/` in .gitignore, git listed a tmp/ holding anything as the one
entry `!! tmp/`, a cache included, and GCM's audit left its export there, so every
worktree was kept (#332).

Git and uv are faked here, as the template's own tests of the task fake them, so nothing
runs a real worktree or venv. The .gitignore is tried with a real git, in a repository of
the test's own.
"""

from __future__ import annotations

import os
import runpy
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from tools.doit import gcm, git

REPO = Path(__file__).resolve().parents[1]
BRANCH = "fix/1-example"
EXPORTED = "pyaes==1.6.1\n"


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


def git_in(folder, *args):
    """Run a real git in *folder*, failing the test with what git said."""
    done = subprocess.run(["git", "-C", str(folder), *args], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return done.stdout


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    """A repository holding this one's .gitignore and an empty tmp/.gitkeep, committed."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    repo = tmp_path / "repo"
    (repo / "tmp").mkdir(parents=True)
    shutil.copy(REPO / ".gitignore", repo / ".gitignore")
    (repo / "tmp" / ".gitkeep").touch()
    git_in(repo, "init", "-q")
    # Not `add -f`: that tracks the file under a bare `tmp/` too, and git then lists the
    # folder file by file all the same, which would hide the rule this tries.
    git_in(repo, "add", ".gitignore", "tmp/.gitkeep")
    git_in(repo, "-c", "user.name=GCM", "-c", "user.email=gcm@example.com", "commit", "-qm", ".")
    return repo


def test_a_worktree_with_only_caches_under_tmp_can_be_removed(scratch):
    for cache in (".uv_cache", ".mypy_cache", ".ruff_cache"):
        (scratch / "tmp" / cache).mkdir()
        (scratch / "tmp" / cache / "CACHEDIR.TAG").touch()

    assert git._worktree_leftovers(scratch) == []


def test_anything_else_under_tmp_still_keeps_the_worktree(scratch):
    (scratch / "tmp" / ".uv_cache").mkdir()
    (scratch / "tmp" / ".uv_cache" / "CACHEDIR.TAG").touch()
    (scratch / "tmp" / "notes.md").write_text("someone's notes\n")

    assert git._worktree_leftovers(scratch) == ["!! tmp/notes.md"]


def test_tmp_gitkeep_is_tracked():
    """Git lists tmp/ file by file only while it tracks a file there."""
    git_in(REPO, "ls-files", "--error-unmatch", "tmp/.gitkeep")


@pytest.fixture
def exporting_uv(tmp_path, monkeypatch):
    """uv, which writes the export where it is told and records each command."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    def run(cmd, **_kwargs):
        if cmd[:2] == ["uv", "export"]:
            Path(cmd[cmd.index("-o") + 1]).write_text(EXPORTED)
        elif "pip-audit" in cmd:
            assert Path(cmd[-1]).read_text() == EXPORTED, "pip-audit must read the export"

    uv = MagicMock(side_effect=run)
    monkeypatch.setattr("tools.doit.gcm.run_streamed", uv)
    return uv


def run_audit():
    """Run the task's actions in order, as doit does, stopping at a failed one."""
    return all(action() is not False for action in gcm.task_audit()["actions"])


def test_the_audit_reads_an_export_made_outside_the_tree_and_removes_it(exporting_uv):
    assert run_audit()

    export, pip_audit = (made.args[0] for made in exporting_uv.call_args_list)
    requirements = Path(pip_audit[-1])
    assert " ".join(export) == (
        f"uv export --frozen --no-emit-project --all-extras --format requirements-txt "
        f"-o {requirements}"
    )
    assert pip_audit == ["uv", "run", "pip-audit", "-r", str(requirements)]
    assert all(made.kwargs["cwd"] == REPO for made in exporting_uv.call_args_list)
    assert REPO not in requirements.parents, "an export in the tree keeps a merged worktree"
    assert not requirements.parent.exists(), "the export's folder must go once it is read"


@pytest.mark.parametrize("failing", ["export", "pip-audit"])
def test_a_failed_export_or_audit_fails_the_task_and_leaves_nothing(exporting_uv, failing):
    ordinary = exporting_uv.side_effect

    def fail(cmd, **kwargs):
        ordinary(cmd, **kwargs)
        if failing in cmd:
            raise subprocess.CalledProcessError(1, cmd)

    exporting_uv.side_effect = fail

    assert run_audit() is False

    commands = [made.args[0] for made in exporting_uv.call_args_list]
    assert not Path(commands[0][-1]).parent.exists(), "the export's folder must go anyway"
    if failing == "export":
        assert len(commands) == 1, "pip-audit must not run without an export"
