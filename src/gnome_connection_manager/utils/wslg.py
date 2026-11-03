"""Whether WSLg cannot draw GCM's window (#414).

WSLg opens the shared memory it draws windows through when it starts. When that fails, its
log, `/mnt/wslg/weston.log`, says so and every Linux window draws blank, titled
`[WARN:COPY MODE]`, with nothing on GCM's console. The failure line, measured on WSLg
1.0.73.2 (Weston 9.0.0), is:

    rdp_allocate_shared_memory: Failed to open "/mnt/shared_memory/{...}" with error: ...

Pure but for `read_log` and `startup_notice`, which read the one file: the log's text is an
argument everywhere else. A healthy log's own wording was not measured (no WSL to hand), so
the match is the failure's line alone and a log without it prints nothing.
"""

from __future__ import annotations

from pathlib import Path

LOG_PATH = Path("/mnt/wslg/weston.log")

# The failure was at byte 3652 of a log that had reached 77 KB, so the start suffices.
READ_LIMIT = 256 * 1024

_FAILURE = "rdp_allocate_shared_memory: Failed to open"

NOTICE = (
    "WSLg could not open the shared memory it draws windows through, so GCM's window may "
    "stay blank, titled [WARN:COPY MODE]. Run `wsl --shutdown` in Windows PowerShell, then "
    "start GCM again. See docs/WSL-SETUP.md, 'When something goes wrong'."
)


def copy_mode_notice(log_text: str) -> str | None:
    """The line to print for this WSLg log, or None when it shows no such failure."""
    if _FAILURE in log_text:
        return NOTICE
    return None


def read_log(path: Path = LOG_PATH) -> str:
    """The start of the log, or "" when there is none or it cannot be read."""
    try:
        with path.open("rb") as handle:
            return handle.read(READ_LIMIT).decode("utf-8", errors="replace")
    except OSError:
        return ""


def startup_notice(path: Path = LOG_PATH) -> str | None:
    """`copy_mode_notice` for the log at `path`."""
    return copy_mode_notice(read_log(path))
