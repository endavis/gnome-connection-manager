"""Doit task runner configuration.

Tasks are auto-discovered from tools/doit/ modules.
Any function starting with 'task_' is automatically imported.
"""

from tools.doit import discover_tasks

globals().update(discover_tasks())

# Project-specific overrides, applied after discovery so they win regardless of the order
# rglob returns the task modules in. See tools/doit/gcm.py for why audit, check and
# worktree differ here.
from tools.doit.gcm import task_audit, task_check, task_worktree  # noqa: E402

globals()["task_audit"] = task_audit
globals()["task_check"] = task_check
globals()["task_worktree"] = task_worktree
