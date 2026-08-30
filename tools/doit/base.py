"""Base utilities and configuration for doit tasks."""

import os
import shlex
import subprocess  # nosec B404 - subprocess is required to run doit sub-tasks
import sys
from collections.abc import Mapping
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

# Configuration
DOIT_CONFIG = {
    "verbosity": 2,
    "default_tasks": ["list"],
}

# Use direnv-managed UV_CACHE_DIR if available, otherwise use tmp/
# Set in os.environ so subprocesses inherit it (cross-platform compatible)
UV_CACHE_DIR = os.environ.get("UV_CACHE_DIR", "tmp/.uv_cache")
os.environ["UV_CACHE_DIR"] = UV_CACHE_DIR


def success_message() -> None:
    """Print success message after all checks pass."""
    console = Console()
    console.print()
    console.print(
        Panel.fit(
            "[bold green]✓ All checks passed![/bold green]", border_style="green", padding=(1, 2)
        )
    )
    console.print()


def optional_root_files(*names: str) -> str:
    """Return a shell-ready, space-prefixed suffix of existing root-level files.

    Builds a string such as ``" bootstrap.py"`` (leading space, space-separated)
    containing only the names that exist as files at the current working
    directory. Missing names are silently skipped; argument order is preserved
    for the names that survive.

    Designed for safe concatenation onto an existing command string used in a
    ``doit`` task action, so tasks can reference root-level files (e.g.
    ``bootstrap.py``) that are present in the template but deleted by the
    consumer-project cleanup step. Empty input or no surviving names yields
    ``""``, making concatenation a no-op.

    Args:
        *names: Candidate filenames at the current working directory.

    Returns:
        ``""`` when no names survive, otherwise ``" " + " ".join(survivors)``.
    """
    survivors = [name for name in names if Path(name).is_file()]
    if not survivors:
        return ""
    return " " + " ".join(survivors)


def install_check_or_skip(package: str, hint: str) -> str:
    """Build a shell prefix that gates a doit action on ``package`` being installed.

    Emits a shell snippet that exits 0 with ``hint`` printed when
    ``uv pip show <package>`` reports the package missing, and otherwise lets
    the rest of the action run so its real exit code reaches the operator
    unmasked. Replaces the ``cmd || echo 'not installed'`` pattern, which
    always swallowed real failures by exiting 0 regardless of why ``cmd``
    failed. See issue #527.

    The emitted snippet uses the form::

        uv pip show <package> >/dev/null 2>&1 || { echo <hint>; exit 0; };

    If ``uv pip show`` succeeds (package present), the brace group is skipped
    and the caller's real command runs; its exit code propagates unmasked.
    If ``uv pip show`` fails (package absent), the brace group prints the hint
    and ``exit 0`` terminates the shell before the real command is reached.

    Args:
        package: The package name as known to ``uv pip show`` (e.g.
            ``"bandit"``, ``"commitizen"``, ``"cyclonedx-bom"``).
        hint: Human-readable install instruction printed when the package is
            absent (e.g. ``"bandit not installed. Run: uv sync --extra
            security"``). Shell-quoted via ``shlex.quote`` so embedded spaces
            and special characters are safe.

    Returns:
        A shell fragment ending with ``"; "`` suitable for prepending to the
        rest of a doit action string via plain string concatenation.
    """
    return f"uv pip show {package} >/dev/null 2>&1 || {{ echo {shlex.quote(hint)}; exit 0; }}; "


def _child_env(env: Mapping[str, str] | None) -> dict[str, str]:
    """Build the environment for a child process spawned by a streaming helper.

    Always sets ``PYTHONUNBUFFERED=1`` so Python children (including descendants
    like ``pytest``, ``mypy``, ``cz``) flush stdout line-by-line to pipes instead
    of block-buffering to process exit. Without this, streaming appears to work
    in tests that explicitly flush, but real tools — whose output is the whole
    point of streaming — deliver everything in one burst at process end.

    A caller-supplied ``PYTHONUNBUFFERED`` is respected.
    """
    merged = dict(env if env is not None else os.environ)
    merged.setdefault("PYTHONUNBUFFERED", "1")
    return merged


def run_streamed(
    cmd: list[str],
    *,
    env: Mapping[str, str] | None = None,
    check: bool = True,
    cwd: str | os.PathLike[str] | None = None,
) -> None:
    """Run a subprocess with stdout/stderr inherited from the parent.

    Unlike ``subprocess.run(..., capture_output=True)``, this function does not
    buffer output: the child process writes directly to the parent's stdout and
    stderr so the user sees progress live. This is the right choice for long-
    running steps whose output we do not need to parse (``doit check``,
    ``git pull``, ``git push``, ``git commit``, ``gh pr create``).

    Args:
        cmd: Command to run, as a list of args (no shell expansion).
        env: Optional environment mapping. If ``None``, the child inherits the
            parent's environment.
        check: When ``True`` (default), a non-zero exit raises
            ``subprocess.CalledProcessError``.
        cwd: Optional working directory for the child process.

    Raises:
        subprocess.CalledProcessError: If ``check`` is ``True`` and the child
            exits with a non-zero return code.
    """
    subprocess.run(  # nosec B603 B607
        cmd,
        env=_child_env(env),
        check=check,
        cwd=cwd,
    )


def run_teed(
    cmd: list[str],
    *,
    env: Mapping[str, str] | None = None,
    check: bool = True,
    cwd: str | os.PathLike[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess, streaming output to stdout while also capturing it.

    Merges stderr into stdout (so the captured buffer reflects interleaved
    output as a user would see it), streams each line to ``sys.stdout`` as it
    arrives, and returns a ``CompletedProcess`` whose ``stdout`` contains the
    full captured output. ``stderr`` is always empty because it was merged.

    This is the right choice when the caller both needs live output (long step,
    hooks, etc.) *and* needs to parse the output afterwards (e.g. regex-extract
    the version printed by ``cz bump``).

    On non-zero exit with ``check=True``, raises ``CalledProcessError`` with
    ``stdout`` populated so existing error-path logging keeps working.

    Args:
        cmd: Command to run, as a list of args (no shell expansion).
        env: Optional environment mapping. If ``None``, the child inherits the
            parent's environment.
        check: When ``True`` (default), a non-zero exit raises
            ``subprocess.CalledProcessError``.
        cwd: Optional working directory for the child process.

    Returns:
        ``subprocess.CompletedProcess[str]`` with ``stdout`` set to the full
        captured output and ``stderr`` set to ``""``.

    Raises:
        subprocess.CalledProcessError: If ``check`` is ``True`` and the child
            exits with a non-zero return code. The exception's ``stdout``
            attribute contains the captured output.
    """
    # Popen with stdout piped and stderr merged into stdout. We read lines
    # from the pipe, echo each to sys.stdout (so the user sees live output),
    # and buffer them for the caller.
    process = subprocess.Popen(  # nosec B603 B607
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=_child_env(env),
        cwd=cwd,
        text=True,
        # bufsize=1 configures only the parent-side TextIOWrapper for reading
        # the pipe. Child-side flushing is controlled via PYTHONUNBUFFERED=1
        # in _child_env() — without it, Python children block-buffer to pipes.
        bufsize=1,
    )

    buffer: list[str] = []
    # process.stdout is non-None because we asked for subprocess.PIPE.
    assert process.stdout is not None  # nosec B101 - invariant from Popen args
    try:
        for line in process.stdout:
            buffer.append(line)
            sys.stdout.write(line)
            sys.stdout.flush()
    except BaseException:
        # Streaming raised (broken parent stdout, KeyboardInterrupt, etc.).
        # Kill the child so wait() below doesn't hang waiting for a process
        # that may be blocked on a full pipe buffer.
        process.kill()
        raise
    finally:
        process.stdout.close()
        process.wait()

    returncode = process.returncode
    captured = "".join(buffer)

    if check and returncode != 0:
        raise subprocess.CalledProcessError(
            returncode=returncode,
            cmd=cmd,
            output=captured,
            stderr="",
        )

    return subprocess.CompletedProcess(
        args=cmd,
        returncode=returncode,
        stdout=captured,
        stderr="",
    )
