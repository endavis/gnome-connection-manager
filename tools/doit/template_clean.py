"""Template cleanup doit task.

Provides a task to remove template-specific files from projects
created from pyproject-template.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from doit.tools import title_with_actions
from rich.console import Console

# Add tools directory to path for imports
_tools_dir = Path(__file__).parent.parent
if str(_tools_dir) not in sys.path:
    sys.path.insert(0, str(_tools_dir))


def task_template_clean() -> dict[str, Any]:
    """Remove template-specific files from the project.

    Options:
        --setup: Remove setup files only (keep update checking)
        --all: Remove all template files (no future updates)
        --dry-run: Show what would be deleted without deleting
    """

    def run_cleanup(setup: bool, all_files: bool, dry_run: bool) -> None:
        # Import from tools directory
        cleanup_module_path = _tools_dir / "pyproject_template" / "cleanup.py"
        if not cleanup_module_path.exists():
            console = Console()
            console.print(
                "[red]Error: cleanup.py not found. Template files may have been removed.[/red]"
            )
            sys.exit(1)

        import importlib.util

        spec = importlib.util.spec_from_file_location("cleanup", cleanup_module_path)
        if spec is None or spec.loader is None:
            console = Console()
            console.print("[red]Error: Could not load cleanup module.[/red]")
            sys.exit(1)

        cleanup_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cleanup_mod)

        cleanup_mode_enum = cleanup_mod.CleanupMode
        cleanup_template_files = cleanup_mod.cleanup_template_files
        prompt_cleanup = cleanup_mod.prompt_cleanup

        console = Console()

        # Determine mode
        if setup and all_files:
            console.print("[red]Error: Cannot specify both --setup and --all[/red]")
            sys.exit(1)
        elif setup:
            mode = cleanup_mode_enum.SETUP_ONLY
        elif all_files:
            mode = cleanup_mode_enum.ALL
        else:
            # Interactive mode
            mode = prompt_cleanup()
            if mode is None:
                console.print("[cyan]Keeping all template files[/cyan]")
                return

        # Perform cleanup
        result = cleanup_template_files(mode, dry_run=dry_run)

        if dry_run:
            console.print()
            console.print("[yellow]Dry run complete. No files were deleted.[/yellow]")
        elif result.failed:
            console.print()
            console.print("[red]Some files could not be deleted.[/red]")
            sys.exit(1)

    return {
        "actions": [run_cleanup],
        "params": [
            {
                "name": "setup",
                "short": "s",
                "long": "setup",
                "type": bool,
                "default": False,
                "help": "Remove setup files only (keep update checking)",
            },
            {
                "name": "all_files",
                "short": "a",
                "long": "all",
                "type": bool,
                "default": False,
                "help": "Remove all template files (no future updates)",
            },
            {
                "name": "dry_run",
                "short": "n",
                "long": "dry-run",
                "type": bool,
                "default": False,
                "help": "Show what would be deleted without deleting",
            },
        ],
        "title": title_with_actions,
        "verbosity": 2,
    }
