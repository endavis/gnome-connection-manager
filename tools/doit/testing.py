"""Testing-related doit tasks."""

from typing import Any

from doit.tools import title_with_actions


def task_test() -> dict[str, Any]:
    """Run pytest with parallel execution and terse failure output.

    ``-q -rfE --tb=short`` keeps the short tracebacks and the failure summary but drops
    the one ``PASSED`` line per test that ``-v`` printed (#1075). For per-test output,
    run ``uv run pytest -v`` directly.

    ``env_check`` runs first (#1033): see ``tools/doit/quality.py::task_check``.
    """
    return {
        "task_dep": ["env_check"],
        "actions": ["uv run pytest -n auto -q -rfE --tb=short"],
        "title": title_with_actions,
        "verbosity": 0,
    }


def task_coverage() -> dict[str, Any]:
    """Run pytest with coverage (note: parallel execution disabled for accurate coverage)."""
    return {
        "actions": [
            "uv run pytest "
            "--cov --cov-report=term-missing "
            "--cov-report=html:tmp/htmlcov --cov-report=xml:tmp/coverage.xml -v"
        ],
        "title": title_with_actions,
    }


def task_mutate() -> dict[str, Any]:
    """Run mutation testing with mutmut."""
    return {
        "actions": [
            "uv run mutmut run",
            "uv run mutmut results",
        ],
        "title": title_with_actions,
        "verbosity": 2,
    }
