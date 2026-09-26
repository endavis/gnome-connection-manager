"""ssh.expect, which runs every host with a stored password: what it passes on to the tab.

That is the exit status, which a tab's Close console setting decides on (#210), and what
the program printed, which is all a tab has to say why a connection failed (#212).

The script runs as a tab runs it, on a pty, with only its ssh or telnet swapped for a
fake that prints what the real one would and exits with its status. The installed ssh
exits 255 on an error, measured with a connection it could not make.
"""

from __future__ import annotations

import fcntl
import os
import select
import shutil
import subprocess
import termios
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "data" / "scripts" / "ssh.expect"

pytestmark = pytest.mark.skipif(shutil.which("expect") is None, reason="needs expect")

# Each program as the script names it, and the arguments GCM gives the script for it.
PROGRAMS = {
    "ssh": ('"/usr/bin/ssh"', ["-l", "me", "example.invalid"]),
    "telnet": ('"/usr/bin/telnet"', ["-l", "me", "example.invalid", "23"]),
}


def _run(
    tmp_path: Path, output: str | None, status: int, connection: str = "ssh"
) -> tuple[int, str]:
    """Run ssh.expect against a fake program; return its exit code and what reached the pty.

    The fake prints `output` as one line, or nothing at all when it is None.
    """
    program, args = PROGRAMS[connection]
    fake = tmp_path / connection
    line = "" if output is None else f"printf '%s\\r\\n' '{output}'\n"
    fake.write_text(f"#!/bin/sh\n{line}exit {status}\n")
    fake.chmod(0o755)
    text = SCRIPT.read_text()
    assert text.count(program) == 1, f"ssh.expect no longer names {program} once"
    script = tmp_path / "ssh.expect"
    script.write_text(text.replace(program, f'"{fake}"'))

    master, slave = os.openpty()
    process = subprocess.Popen(
        ["expect", str(script), connection, *args],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        # The pty as the controlling terminal, as VTE gives a tab: the script's stty
        # refuses to run without one.
        start_new_session=True,
        preexec_fn=lambda: fcntl.ioctl(0, termios.TIOCSCTTY, 0),
    )
    os.close(slave)
    os.write(master, b"not-a-password\n")  # the script reads the password first
    seen = b""
    deadline = time.monotonic() + 30
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], deadline - time.monotonic())
            if not ready:
                break
            try:
                chunk = os.read(master, 4096)
            except OSError:  # EIO, which arrived before expect had exited
                break
            if not chunk:
                break
            seen += chunk
        code = process.wait(timeout=30)
    finally:
        # Only once expect has exited: closing the master hangs up its terminal, and
        # expect then dies of SIGHUP instead of exiting with ssh's status.
        if process.poll() is None:
            process.kill()
        os.close(master)
    return code, seen.decode(errors="replace")


def test_a_host_key_failure_reaches_the_tab_as_a_failure(tmp_path):
    """This branch used to exit on its own, with 0, which Close console read as a clean
    exit: Only on clean exit closed the tab over the message."""
    code, seen = _run(tmp_path, "Host key verification failed.", 255)

    assert code == 255
    assert "Host key verification failed." in seen


# What each program printed when the name did not resolve, measured through GCM (#212).
FAILURES = {
    "ssh": ("ssh: Could not resolve hostname example.invalid: Name or service not known", 255),
    "telnet": ("Server lookup failure:  example.invalid:23, Name or service not known", 1),
}


@pytest.mark.parametrize("connection", ["ssh", "telnet"])
def test_a_failed_connection_shows_why(tmp_path, connection):
    """The error matched none of the script's patterns, and log_user 0 had kept it off
    the screen, so a connection that failed left an empty tab (#212)."""
    output, status = FAILURES[connection]

    code, seen = _run(tmp_path, output, status, connection)

    assert output in seen
    assert code == status


# Not 1: expect exits with 1 when the script itself fails, so 1 could not tell them apart.
@pytest.mark.parametrize(("connection", "status"), [("ssh", 255), ("ssh", 0), ("telnet", 3)])
def test_a_program_that_prints_nothing_keeps_its_status(tmp_path, connection, status):
    """Printing what was read must not fail when nothing was."""
    code, _ = _run(tmp_path, None, status, connection)

    assert code == status


def test_a_clean_logout_reaches_the_tab_as_one(tmp_path):
    code, _ = _run(tmp_path, "Connection to example.invalid closed.", 0)

    assert code == 0
