"""Tests for the daily check workflow (#952).

The workflow ran ``uv run doit check``, which stops at the first failing task.
Every task after it never ran, so a second failure stayed hidden behind the
first, and the issue it filed named no task at all.

The steps' scripts are run for real here, with ``uv`` and ``gh`` replaced by
stubs. The assertions are on what the steps do, not on how their scripts are
spelled.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOW_PATH = Path(__file__).parent.parent / ".github" / "workflows" / "daily-check.yml"

# GitHub runs a Linux step's script as `bash -e {0}` unless the step names a
# shell. The Windows runner's `bash` resolves to wsl.exe with no distribution
# installed (see tests/test_statusline_gh_user.py), and this workflow runs on
# ubuntu-latest only.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="the steps run under bash on Linux; the Windows runner has no usable bash",
)

# What `doit --continue check` prints with doit 0.37.0 when `audit` fails, a
# Python action in `deadcode` raises and `test` fails. Failures of tasks below
# verbosity 2 are printed again at the end of the run, hence `audit` twice.
_DOIT_OUTPUT = """\
.  format_check
.  audit
TaskFailed - taskid:audit
Command failed: 'pip-audit' returned 1

.  deadcode
TaskError - taskid:deadcode
PythonAction Error
.  test
TaskFailed - taskid:test
Command failed: 'pytest' returned 1

UnmetDependency - taskid:check
audit deadcode test
########################################
TaskFailed - taskid:audit
"""

# Echoes the output named by $STUB_OUTPUT, records its arguments, exits $STUB_STATUS.
_UV_STUB = """\
#!/bin/bash
echo "$*" > "$STUB_ARGS"
cat "$STUB_OUTPUT"
exit "$STUB_STATUS"
"""

# Answers `gh issue list` with $STUB_EXISTING and records every call.
_GH_STUB = """\
#!/bin/bash
printf '%s\\n' "$*" >> "$STUB_CALLS"
if [ "$1 $2" = "issue list" ]; then
  echo "$STUB_EXISTING"
fi
"""


def _steps() -> list[dict[str, Any]]:
    # yaml.safe_load returns Any; bind to an annotated local for warn_return_any.
    data: dict[str, Any] = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    steps: list[dict[str, Any]] = data["jobs"]["check"]["steps"]
    return steps


def _step(name: str) -> dict[str, Any]:
    """Return the one step called *name*."""
    found = [step for step in _steps() if step.get("name") == name]
    assert len(found) == 1, f"expected one step named {name!r}, found {len(found)}"
    return found[0]


def _stub(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _run(tmp_path: Path, step: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run *step*'s script with stubbed ``uv`` and ``gh`` and *env* added."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    _stub(bin_dir, "uv", _UV_STUB)
    _stub(bin_dir, "gh", _GH_STUB)
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir(exist_ok=True)
    script = tmp_path / "step.sh"
    script.write_text(_step(step)["run"], encoding="utf-8")
    return subprocess.run(
        ["bash", "-e", str(script)],
        cwd=tmp_path,
        env={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "RUNNER_TEMP": str(runner_temp),
            "RUN_URL": "https://example.invalid/runs/1",
            "OWNER": "someone",
            "STUB_CALLS": str(tmp_path / "gh-calls.txt"),
            "STUB_ARGS": str(tmp_path / "uv-args.txt"),
            **env,
        },
        capture_output=True,
        text=True,
        timeout=10,
    )


def _run_check(tmp_path: Path, status: int) -> subprocess.CompletedProcess[str]:
    """Run the check step with ``uv`` printing ``_DOIT_OUTPUT`` and exiting *status*."""
    output = tmp_path / "doit-output.txt"
    output.write_text(_DOIT_OUTPUT, encoding="utf-8")
    env = {"STUB_OUTPUT": str(output), "STUB_STATUS": str(status)}
    return _run(tmp_path, "Run doit check", env)


def _report(tmp_path: Path, existing: str) -> str:
    """Run the report step against open issue *existing* and return its ``gh`` calls."""
    result = _run(tmp_path, "Open or update failure issue", {"STUB_EXISTING": existing})
    assert result.returncode == 0, result.stdout + result.stderr
    return (tmp_path / "gh-calls.txt").read_text(encoding="utf-8")


def test_the_check_continues_after_a_failing_task(tmp_path: Path) -> None:
    """doit is told to run every task, not stop at the first failure."""
    _run_check(tmp_path, 0)
    args = (tmp_path / "uv-args.txt").read_text(encoding="utf-8").split()
    assert args[:2] == ["run", "doit"]
    assert "--continue" in args
    assert args[-1] == "check"


def test_a_failing_check_fails_the_step(tmp_path: Path) -> None:
    """The log is piped through tee; doit's exit status must still reach the step."""
    result = _run_check(tmp_path, 2)
    assert result.returncode != 0


def test_a_passing_check_passes_the_step(tmp_path: Path) -> None:
    result = _run_check(tmp_path, 0)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_check_output_is_shown_and_kept(tmp_path: Path) -> None:
    """The output stays in the run log and is saved for the report step."""
    result = _run_check(tmp_path, 2)
    assert "TaskFailed - taskid:audit" in result.stdout
    saved = (tmp_path / "runner-temp" / "doit-check.log").read_text(encoding="utf-8")
    assert saved == _DOIT_OUTPUT


def test_the_report_runs_only_on_failure() -> None:
    assert _step("Open or update failure issue")["if"] == "failure()"


def test_a_new_issue_names_each_failing_task(tmp_path: Path) -> None:
    """Each failing task once, in run order; the `check` target is not one of them."""
    _run_check(tmp_path, 2)
    calls = _report(tmp_path, existing="")
    assert "issue create" in calls
    body = (tmp_path / "runner-temp" / "issue-body.md").read_text(encoding="utf-8")
    assert "- Failing tasks: `audit`, `deadcode`, `test`\n" in body


def test_a_new_issue_does_not_list_tasks_from_memory(tmp_path: Path) -> None:
    """The body used to list the checks by hand, and the list fell behind `task_check`."""
    _run_check(tmp_path, 2)
    _report(tmp_path, existing="")
    body = (tmp_path / "runner-temp" / "issue-body.md").read_text(encoding="utf-8")
    assert "(format, lint" not in body


def test_a_still_failing_comment_names_each_failing_task(tmp_path: Path) -> None:
    """A failure that joins mid-streak shows up in the thread."""
    _run_check(tmp_path, 2)
    calls = _report(tmp_path, existing="42")
    comment = next(line for line in calls.splitlines() if line.startswith("issue comment"))
    assert comment.startswith("issue comment 42 ")
    assert "Failing tasks: `audit`, `deadcode`, `test`." in comment
    assert "issue create" not in calls


def test_no_log_still_reports(tmp_path: Path) -> None:
    """A failure before doit runs (say, the install step) leaves no log to read."""
    calls = _report(tmp_path, existing="42")
    assert "Failing tasks: none identified, see the run log." in calls
