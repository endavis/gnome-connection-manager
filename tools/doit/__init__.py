"""Dodo task modules for the pyproject-template.

This package contains modular doit task definitions organized by functionality.
Tasks are auto-discovered from all modules in this package.
"""

import importlib
from pathlib import Path
from typing import Any


def discover_tasks() -> dict[str, Any]:
    """Auto-discover all task_* functions and DOIT_CONFIG from modules.

    Scans all Python modules in tools/doit/ (recursively) and collects:
    - Functions starting with 'task_' (doit task definitions)
    - DOIT_CONFIG dict (doit configuration)

    Returns:
        Dictionary mapping names to task functions/config for use with
        globals().update() in dodo.py.
    """
    discovered: dict[str, Any] = {}
    package_dir = Path(__file__).parent

    # Walk all modules in this package (recursive for future subdirectories)
    for py_file in package_dir.rglob("*.py"):
        # Skip __init__.py and other private files
        if py_file.name.startswith("_"):
            continue

        # Convert path to module name: tools/doit/build.py -> tools.doit.build
        relative = py_file.relative_to(package_dir.parent.parent)
        module_name = str(relative.with_suffix("")).replace("/", ".").replace("\\", ".")

        module = importlib.import_module(module_name)

        for name in dir(module):
            if name.startswith("task_") or name == "DOIT_CONFIG":
                discovered[name] = getattr(module, name)

    return discovered
