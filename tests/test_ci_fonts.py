"""What CI's `test` job prints about the machine the real-GTK scenarios ran on (#503).

The menu placement scenarios of #500 failed every time on a WSL2 Ubuntu 24.04 machine and
passed on CI. GTK's default font, Sans, resolved there to Noto Sans, whose rows are
taller than DejaVu Sans's, which the scenarios had been sized for. Which font CI's runner
resolved Sans to was never printed, so the two could not be compared.

This reads `.github/workflows/ci.yml` as `tests/test_worktree.py` does, and runs none of it.
It is not in `tests/test_menuplacement.py`, whose geometry is the font's: mutmut runs that
file in a copy of the tree, and `[tool.mutmut]` copies no `.github/` into it.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
JOB = "test"
STEP = "Verify PyGObject is reachable"


def test_the_test_job_prints_the_font_sans_resolves_to_beside_the_gtk_version() -> None:
    """The `test` job prints `fc-match Sans` where it prints GTK's and VTE's versions.

    Without it a real-GTK test that passes on CI and fails on another machine, or the other
    way about, cannot be compared on the font first. Nothing else in the suite would notice
    the line gone: only a run's log shows what it printed.
    """
    workflow = yaml.safe_load((REPO / ".github" / "workflows" / "ci.yml").read_text("utf-8"))
    scripts = {step.get("name"): step.get("run", "") for step in workflow["jobs"][JOB]["steps"]}
    assert STEP in scripts, f"the {JOB!r} job of ci.yml has no step named {STEP!r}"

    # A line commented out is not run, and the words of a comment must not stand for it.
    commands = [line for line in scripts[STEP].splitlines() if not line.lstrip().startswith("#")]
    assert any("fc-match Sans" in line for line in commands), (
        f"the {STEP!r} step of the {JOB!r} job in ci.yml must run `fc-match Sans`, beside the "
        "versions of GTK and VTE it prints: it is the only record of the font the real-GTK "
        "scenarios draw with on the runner (#503)"
    )
