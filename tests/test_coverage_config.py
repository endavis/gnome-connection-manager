"""Coverage's settings in pyproject.toml, which the suite's memory depends on (#523)."""

from __future__ import annotations

import tomllib
from pathlib import Path

import coverage

REPO = Path(__file__).resolve().parents[1]


def test_coverage_measures_with_ctrace_not_sysmon() -> None:
    # Under sysmon, coverage's default on Python 3.14, every import of app.py that
    # app_module makes kept its memory: 533 MB over 200 tests against 239 MB under ctrace,
    # measured. With every xdist worker growing so, two `doit check` runs filled the
    # container (#523).
    settings = tomllib.loads((REPO / "pyproject.toml").read_text())
    assert settings["tool"]["coverage"]["run"]["core"] == "ctrace"


def test_coverage_reads_the_core_from_pyproject() -> None:
    # The setting is coverage's own, read from the file it is given, not an environment
    # variable someone has to remember: COVERAGE_CORE, when set, still overrides it.
    config = coverage.Coverage(config_file=str(REPO / "pyproject.toml")).config
    assert config.core == "ctrace"
