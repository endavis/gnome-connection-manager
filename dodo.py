"""Doit task runner configuration.

Tasks are auto-discovered from tools/doit/ modules.
Any function starting with 'task_' is automatically imported.
"""

from tools.doit import discover_tasks

globals().update(discover_tasks())
