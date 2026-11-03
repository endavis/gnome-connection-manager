"""Whether WSLg cannot draw GCM's window (#414).

WSLg opens the shared memory it draws windows through when it starts. When that fails, its
log, `/mnt/wslg/weston.log`, says so and every Linux window draws blank, with nothing on
GCM's console. The failure line, measured on WSLg 1.0.73.2 (Weston 9.0.0), is:

    rdp_allocate_shared_memory: Failed to open "/mnt/shared_memory/{...}" with error: ...

Measured on a working WSLg session: `/mnt/wslg/weston.log` was 43,045 bytes, its first
`copy` match was `[10:23:51.878] RDP backend: enable_copy_warning_title = 1` at byte offset
4232, and it held no `rdp_allocate_shared_memory` line. The failing log quoted in #414 logs
the same `enable_copy_warning_title = 1` line, so that setting is not a sign of the failure:
only the failure line is, and it is the one thing matched.

The blank window's title is `[WARN:COPY MODE] <window title> (<distro>)`, measured two ways:
WSLg's source (`microsoft/weston-mirror` at 7fbf69314f8a74450c265650232f66f59a4e0630,
`libweston/backend-rdp/rdprail.c`) builds it as `"[WARN:COPY MODE] %s (%s)"`, the window's
title then the distro's name or "Linux"; and the installed WSLg's
`/usr/lib/libweston-9/rdp-backend.so`, read with `wsl --system -- grep -a -o -F "WARN:COPY"`,
holds `WARN:COPY` and no `WARN]`.

Pure but for `read_log` and `startup_notice`, which read the one file: the log's text is an
argument everywhere else. The message is marked with `N_` and `app.py` translates it where it
prints it, as `utils/connections.py` does.
"""

from __future__ import annotations

from pathlib import Path

LOG_PATH = Path("/mnt/wslg/weston.log")

# Measured: startup lines sit in the first ~5 KB of both a working log (43,045 bytes, the
# `enable_copy_warning_title` line at byte 4232) and the failing one in #414 (failure at
# byte 3652 of a log that had reached 77 KB). 256 KB is a wide margin over that.
READ_LIMIT = 256 * 1024


def N_(message: str) -> str:
    """Mark a message for translation. app.py translates it where it shows it."""
    return message


_FAILURE = "rdp_allocate_shared_memory: Failed to open"

NOTICE = N_(
    "WSLg could not open the shared memory it draws windows through, so GCM's window may stay blank, its title starting with [WARN:COPY MODE]. Run `wsl --shutdown` in Windows, then start GCM again. See docs/WSL-SETUP.md, 'When something goes wrong'."
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
