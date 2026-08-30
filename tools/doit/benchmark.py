"""Benchmarking-related doit tasks."""

from typing import Any

from doit.tools import title_with_actions


def task_benchmark() -> dict[str, Any]:
    """Run performance benchmarks."""
    return {
        "actions": ["uv run pytest tests/benchmarks/ --benchmark-enable --benchmark-only -v"],
        "title": title_with_actions,
        "verbosity": 0,
    }


def task_benchmark_save() -> dict[str, Any]:
    """Run benchmarks and save results as baseline."""
    return {
        "actions": [
            "uv run pytest tests/benchmarks/ --benchmark-enable --benchmark-only "
            "--benchmark-save=baseline --benchmark-storage=tmp/benchmarks -v"
        ],
        "title": title_with_actions,
        "verbosity": 0,
    }


def task_benchmark_compare() -> dict[str, Any]:
    """Run benchmarks and compare against saved baseline."""
    return {
        "actions": [
            "uv run pytest tests/benchmarks/ --benchmark-enable --benchmark-only "
            "--benchmark-compare=0001_baseline --benchmark-storage=tmp/benchmarks -v"
        ],
        "title": title_with_actions,
        "verbosity": 0,
    }
