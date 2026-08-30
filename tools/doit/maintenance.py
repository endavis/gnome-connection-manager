"""Maintenance-related doit tasks."""

import os
import shutil
import subprocess  # nosec B404 - subprocess is required for doit tasks
import sys
from typing import Any

from doit.tools import title_with_actions
from rich.console import Console
from rich.panel import Panel

from .base import UV_CACHE_DIR


def task_cleanup() -> dict[str, Any]:
    """Clean build and cache artifacts (deep clean)."""

    def clean_artifacts() -> None:
        console = Console()
        console.print("[bold yellow]Performing deep clean...[/bold yellow]")
        console.print()

        # Remove build artifacts
        console.print("[cyan]Removing build artifacts...[/cyan]")
        dirs = [
            "build",
            "dist",
            ".eggs",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
        ]
        for d in dirs:
            if os.path.exists(d):
                console.print(f"  [dim]Removing {d}...[/dim]")
                if os.path.isdir(d):
                    shutil.rmtree(d)
                else:
                    os.remove(d)

        # Remove *.egg-info directories
        for item in os.listdir("."):
            if item.endswith(".egg-info") and os.path.isdir(item):
                console.print(f"  [dim]Removing {item}...[/dim]")
                shutil.rmtree(item)

        # Clear tmp/ directory but keep the directory and .gitkeep
        console.print("[cyan]Clearing tmp/ directory...[/cyan]")
        if os.path.exists("tmp"):
            for item in os.listdir("tmp"):
                if item != ".gitkeep":
                    path = os.path.join("tmp", item)
                    if os.path.isdir(path):
                        shutil.rmtree(path)
                    else:
                        os.remove(path)
        else:
            os.makedirs("tmp", exist_ok=True)

        # Ensure .gitkeep exists
        gitkeep = os.path.join("tmp", ".gitkeep")
        if not os.path.exists(gitkeep):
            open(gitkeep, "a", encoding="utf-8").close()

        # Recursive removal of Python cache
        console.print("[cyan]Removing Python cache files...[/cyan]")
        for root, dirs_list, files in os.walk("."):
            # Skip .venv directory
            if ".venv" in dirs_list:
                dirs_list.remove(".venv")

            for d in dirs_list:
                if d == "__pycache__":
                    full_path = os.path.join(root, d)
                    console.print(f"  [dim]Removing {full_path}...[/dim]")
                    shutil.rmtree(full_path)

            for f in files:
                if f.endswith((".pyc", ".pyo")) or f.startswith(".coverage"):
                    full_path = os.path.join(root, f)
                    console.print(f"  [dim]Removing {full_path}...[/dim]")
                    os.remove(full_path)

        console.print()
        console.print(
            Panel.fit(
                "[bold green]✓ Deep clean complete![/bold green]",
                border_style="green",
                padding=(1, 2),
            )
        )

    return {
        "actions": [clean_artifacts],
        "title": title_with_actions,
    }


def task_update_deps() -> dict[str, Any]:
    """Update dependencies and run tests to verify."""

    def update_dependencies() -> None:
        console = Console()
        console.print()
        console.print(
            Panel.fit("[bold cyan]Updating Dependencies[/bold cyan]", border_style="cyan")
        )
        console.print()

        print("Checking for outdated dependencies...")
        print()
        subprocess.run(
            ["uv", "pip", "list", "--outdated"],
            env={**os.environ, "UV_CACHE_DIR": UV_CACHE_DIR},
            check=False,
        )

        print()
        print("=" * 70)
        print("Updating all dependencies (including extras)...")
        print("=" * 70)
        print()

        # Update dependencies and refresh lockfile
        result = subprocess.run(
            ["uv", "sync", "--all-extras", "--dev", "--upgrade"],
            env={**os.environ, "UV_CACHE_DIR": UV_CACHE_DIR},
        )

        if result.returncode != 0:
            print("\n❌ Dependency update failed!")
            sys.exit(1)

        print()
        print("=" * 70)
        print("Running tests to verify updates...")
        print("=" * 70)
        print()

        # Run all checks
        check_result = subprocess.run(["doit", "check"])

        print()
        if check_result.returncode == 0:
            print("=" * 70)
            print(" " * 20 + "[OK] All checks passed!")
            print("=" * 70)
            print()
            print("Next steps:")
            print("1. Review the changes: git diff pyproject.toml")
            print("2. Test thoroughly")
            print("3. Commit the updated dependencies")
        else:
            print("=" * 70)
            print("⚠ Warning: Some checks failed after update")
            print("=" * 70)
            print()
            print("You may need to:")
            print("1. Fix compatibility issues")
            print("2. Update code for breaking changes")
            print("3. Revert problematic updates")
            sys.exit(1)

    return {
        "actions": [update_dependencies],
        "title": title_with_actions,
    }


def task_fmt_pyproject() -> dict[str, Any]:
    """Format pyproject.toml with pyproject-fmt."""
    return {
        "actions": ["uv run pyproject-fmt pyproject.toml"],
        "title": title_with_actions,
    }


def task_completions() -> dict[str, Any]:
    """Generate shell completion scripts for doit tasks."""

    def generate_completions() -> None:
        console = Console()
        console.print()
        console.print(
            Panel.fit("[bold cyan]Generating Shell Completions[/bold cyan]", border_style="cyan")
        )
        console.print()

        # Ensure completions directory exists
        os.makedirs("completions", exist_ok=True)

        # Generate bash completion
        console.print("[cyan]Generating bash completion...[/cyan]")
        bash_result = subprocess.run(
            ["doit", "tabcompletion", "--shell", "bash"],
            capture_output=True,
            text=True,
            check=True,
        )
        with open("completions/doit.bash", "w", encoding="utf-8") as f:
            f.write(bash_result.stdout)
        console.print("  [dim]Created completions/doit.bash[/dim]")

        # Generate zsh completion
        console.print("[cyan]Generating zsh completion...[/cyan]")
        zsh_result = subprocess.run(
            ["doit", "tabcompletion", "--shell", "zsh"],
            capture_output=True,
            text=True,
            check=True,
        )
        with open("completions/doit.zsh", "w", encoding="utf-8") as f:
            f.write(zsh_result.stdout)
        console.print("  [dim]Created completions/doit.zsh[/dim]")

        console.print()
        console.print(
            Panel.fit(
                "[bold green]✓ Completions generated![/bold green]\n\n"
                "[dim]To enable, add to your shell config:[/dim]\n"
                "  Bash: source completions/doit.bash\n"
                "  Zsh:  source completions/doit.zsh",
                border_style="green",
                padding=(1, 2),
            )
        )

    return {
        "actions": [generate_completions],
        "title": title_with_actions,
    }


def task_completions_install() -> dict[str, Any]:
    """Install doit completions to your shell config (~/.bashrc or ~/.zshrc)."""

    def install_completions() -> None:
        console = Console()
        console.print()
        console.print(
            Panel.fit("[bold cyan]Installing Shell Completions[/bold cyan]", border_style="cyan")
        )
        console.print()

        # Get absolute path to completions
        project_dir = os.path.abspath(os.getcwd())
        bash_completion = os.path.join(project_dir, "completions", "doit.bash")
        zsh_completion = os.path.join(project_dir, "completions", "doit.zsh")

        # Check if completions exist
        if not os.path.exists(bash_completion) or not os.path.exists(zsh_completion):
            console.print("[yellow]Completions not found. Generating...[/yellow]")
            subprocess.run(["doit", "completions"], check=True)
            console.print()

        # Source line to add (with unique marker for identification)
        project_name = os.path.basename(project_dir)
        bash_source_line = (
            f"\n# Doit completions for {project_name}\n"
            f'if [ -f "{bash_completion}" ]; then source "{bash_completion}"; fi\n'
        )
        zsh_source_line = (
            f"\n# Doit completions for {project_name}\n"
            f'if [ -f "{zsh_completion}" ]; then source "{zsh_completion}"; fi\n'
        )

        home = os.path.expanduser("~")
        installed = []

        # Install bash completion
        bashrc = os.path.join(home, ".bashrc")
        if os.path.exists(bashrc):
            with open(bashrc, encoding="utf-8") as f:
                content = f.read()
            if bash_completion not in content:
                with open(bashrc, "a", encoding="utf-8") as f:
                    f.write(bash_source_line)
                installed.append(("Bash", bashrc))
                console.print(f"[green]✓ Added to {bashrc}[/green]")
            else:
                console.print(f"[dim]Already in {bashrc}[/dim]")

        # Install zsh completion
        zshrc = os.path.join(home, ".zshrc")
        if os.path.exists(zshrc):
            with open(zshrc, encoding="utf-8") as f:
                content = f.read()
            if zsh_completion not in content:
                with open(zshrc, "a", encoding="utf-8") as f:
                    f.write(zsh_source_line)
                installed.append(("Zsh", zshrc))
                console.print(f"[green]✓ Added to {zshrc}[/green]")
            else:
                console.print(f"[dim]Already in {zshrc}[/dim]")

        console.print()
        if installed:
            shells = ", ".join(s[0] for s in installed)
            console.print(
                Panel.fit(
                    f"[bold green]✓ Completions installed for {shells}![/bold green]\n\n"
                    "[dim]Reload your shell or run:[/dim]\n"
                    "  source ~/.bashrc  (for Bash)\n"
                    "  source ~/.zshrc   (for Zsh)",
                    border_style="green",
                    padding=(1, 2),
                )
            )
        else:
            console.print(
                Panel.fit(
                    "[yellow]No shell config files found or already installed.[/yellow]\n\n"
                    "[dim]Manually add to your shell config:[/dim]\n"
                    f'  source "{bash_completion}"  (Bash)\n'
                    f'  source "{zsh_completion}"   (Zsh)',
                    border_style="yellow",
                    padding=(1, 2),
                )
            )

    return {
        "actions": [install_completions],
        "title": title_with_actions,
    }
