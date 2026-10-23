"""Tests for the mutation-testing workflow (#873, #878).

The workflow ran ``uv run mutmut run > ... || true``. mutmut 3 exits non-zero
only when it cannot test the mutants at all, never for surviving mutants, so
``|| true`` masked exactly the failure worth seeing: for months the weekly run
stopped while collecting stats, checked no mutant, and reported success.

The step's script is run for real here, with ``uv`` replaced by a stub that
exits with the status under test. The assertions are on what the step does,
not on how its script is spelled.

The results step is run the same way, against a stub that lists canned
``mutmut results`` output. The run used to show only the surviving mutants,
so it gave neither the killed count nor a mutation score (#878).
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOW_PATH = Path(__file__).parent.parent / ".github" / "workflows" / "mutation.yml"

# GitHub runs a Linux step's script as `bash -e {0}` unless the step names a
# shell. The Windows runner's `bash` resolves to wsl.exe with no distribution
# installed (see tests/test_statusline_gh_user.py), and this workflow runs on
# ubuntu-latest only.
needs_bash = pytest.mark.skipif(
    sys.platform == "win32",
    reason="the step runs under bash on Linux; the Windows runner has no usable bash",
)


def _job() -> dict[str, Any]:
    """Return the workflow's only job."""
    # yaml.safe_load returns Any; bind to an annotated local for warn_return_any.
    data: dict[str, Any] = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    job: dict[str, Any] = data["jobs"]["mutate"]
    return job


def _steps() -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = _job()["steps"]
    return steps


def _step_index(command: str) -> int:
    """Return the index of the one step whose script runs *command*."""
    indexes = [i for i, step in enumerate(_steps()) if command in step.get("run", "")]
    assert len(indexes) == 1, f"expected one step running `{command}`, found {len(indexes)}"
    return indexes[0]


def _mutmut_run_index() -> int:
    """Return the index of the one step that runs ``mutmut run``."""
    return _step_index("mutmut run")


def _run_script(
    tmp_path: Path, index: int, uv_stub: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run step *index*'s script with *uv_stub* as ``uv`` and *env* added to its environment."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text(uv_stub, encoding="utf-8")
    uv.chmod(uv.stat().st_mode | stat.S_IEXEC)
    script = tmp_path / "step.sh"
    script.write_text(_steps()[index]["run"], encoding="utf-8")
    return subprocess.run(
        ["bash", "-e", str(script)],
        cwd=tmp_path,
        env={"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", **(env or {})},
        capture_output=True,
        text=True,
        timeout=10,
    )


def _run_step(tmp_path: Path, *, mutmut_status: int) -> subprocess.CompletedProcess[str]:
    """Run the mutmut step's script with a ``uv`` stub that exits *mutmut_status*."""
    stub = f"#!/bin/bash\necho 'stub mutmut output'\nexit {mutmut_status}\n"
    return _run_script(tmp_path, _mutmut_run_index(), stub)


# `uv run mutmut results [--all BOOLEAN]`, answered as mutmut 3.8 does: killed
# mutants are left out unless --all is true.
_RESULTS_STUB = """\
#!/bin/bash
[ "$1 $2 $3" = "run mutmut results" ] || { echo "unexpected: uv $*" >&2; exit 2; }
shift 3
case " $* " in
  *" --all true "* | *" --all=true "*) cat "$STUB_RESULTS" ;;
  *) grep -v ': killed$' "$STUB_RESULTS" ;;
esac
"""

# 74 of 80 killed, as in #878's local run. Two of the rest have "no tests", a
# status with a space in it.
_MUTANTS = {"killed": 74, "survived": 4, "no tests": 2}


def _results_lines(counts: dict[str, int]) -> list[str]:
    """Return ``mutmut results --all true`` lines for *counts* mutants of each status."""
    statuses = [status for status, count in counts.items() for _ in range(count)]
    return [
        f"    package_name.core.x_greet__mutmut_{n}: {status}"
        for n, status in enumerate(statuses, start=1)
    ]


def _run_results_step(tmp_path: Path, lines: list[str]) -> subprocess.CompletedProcess[str]:
    """Run the results step's script with a ``uv`` stub whose mutmut lists *lines*."""
    listing = tmp_path / "listing.txt"
    listing.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    env = {
        "STUB_RESULTS": str(listing),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "step-summary.md"),
    }
    return _run_script(tmp_path, _step_index("mutmut results"), _RESULTS_STUB, env)


def _summary(result: subprocess.CompletedProcess[str]) -> str:
    """Return the log from the step's summary heading on."""
    assert result.returncode == 0, result.stdout + result.stderr
    _, found, summary = result.stdout.partition("=== Summary ===")
    assert found, f"no summary in the log:\n{result.stdout}"
    return summary


@needs_bash
def test_a_mutmut_failure_fails_the_step(tmp_path: Path) -> None:
    """mutmut exits 1 when its stats run fails, and the step must fail with it."""
    result = _run_step(tmp_path, mutmut_status=1)

    assert result.returncode != 0
    assert "::error::" in result.stdout


@needs_bash
def test_a_completed_run_passes_the_step(tmp_path: Path) -> None:
    """Surviving mutants leave mutmut's exit status at 0; the run stays informational."""
    result = _run_step(tmp_path, mutmut_status=0)

    assert result.returncode == 0, result.stdout + result.stderr
    log = tmp_path / "tmp" / "mutmut-run-raw.log"
    assert "stub mutmut output" in log.read_text(encoding="utf-8")


def test_nothing_turns_a_failed_step_green() -> None:
    """``continue-on-error`` would undo the step's failure at the job level."""
    assert not _steps()[_mutmut_run_index()].get("continue-on-error")
    assert not _job().get("continue-on-error")


def test_results_are_shown_and_uploaded_after_a_failure() -> None:
    """The steps after the run print its log and upload its results even when it fails."""
    later = _steps()[_mutmut_run_index() + 1 :]

    assert later, "no step prints or uploads the mutation results"
    assert all("always()" in str(step.get("if", "")) for step in later)


# test_property_tests_run_without_a_deadline is left out: it asserts the job sets
# HYPOTHESIS_PROFILE=ci, for the template's property tests and the Hypothesis profiles its
# conftest registers. GCM has neither, so its mutation.yml sets no profile (#324).


@needs_bash
def test_the_summary_counts_the_killed_mutants_and_gives_the_score(tmp_path: Path) -> None:
    """Run 36314365254 summarized its results as `6 survived`, with no killed count (#878)."""
    summary = _summary(_run_results_step(tmp_path, _results_lines(_MUTANTS)))

    assert re.search(r"^\s*74 killed$", summary, re.MULTILINE), summary
    assert re.search(r"^\s*4 survived$", summary, re.MULTILINE), summary
    assert re.search(r"^\s*2 no tests$", summary, re.MULTILINE), summary
    assert re.search(r"Mutation score: 92\.5%", summary), summary


@needs_bash
def test_the_uploaded_results_list_every_mutant(tmp_path: Path) -> None:
    """The artifact used to hold only the mutants the tests did not kill."""
    lines = _results_lines(_MUTANTS)
    _summary(_run_results_step(tmp_path, lines))
    (upload,) = [step for step in _steps() if "upload-artifact" in step.get("uses", "")]

    uploaded = tmp_path / upload["with"]["path"]
    assert uploaded.read_text(encoding="utf-8").splitlines() == lines


@needs_bash
def test_the_log_lists_only_the_mutants_not_killed(tmp_path: Path) -> None:
    """Triage works from the survivors (#830), and 74 killed lines would bury them."""
    lines = _results_lines(_MUTANTS)
    result = _run_results_step(tmp_path, lines)

    assert result.returncode == 0, result.stdout + result.stderr
    printed = set(result.stdout.splitlines())
    assert {line for line in lines if not line.endswith(": killed")} <= printed
    assert not {line for line in lines if line.endswith(": killed")} & printed


@needs_bash
def test_the_run_page_shows_the_score_and_the_counts(tmp_path: Path) -> None:
    """The step summary carries them, so a reader need not open the log."""
    _summary(_run_results_step(tmp_path, _results_lines(_MUTANTS)))
    page = (tmp_path / "step-summary.md").read_text(encoding="utf-8")

    rows = dict(re.findall(r"^\|\s*([a-z ]+?)\s*\|\s*(\d+)\s*\|$", page, re.MULTILINE))
    assert rows == {"killed": "74", "survived": "4", "no tests": "2"}
    assert re.search(r"Mutation score: 92\.5%", page), page


@needs_bash
def test_no_mutants_gives_no_score(tmp_path: Path) -> None:
    """A run that lists no mutants must neither divide by zero nor report a percentage."""
    summary = _summary(_run_results_step(tmp_path, []))

    assert "%" not in summary
