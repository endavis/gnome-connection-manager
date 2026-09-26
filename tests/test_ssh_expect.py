"""ssh.expect's exit status, which a tab's Close console setting decides on (#210).

The script runs as a tab runs it, on a pty, with only its ssh swapped for a fake that
prints what ssh would and exits with ssh's status. The installed ssh exits 255 on an
error, measured with a connection it could not make.
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


def _run(tmp_path: Path, output: str, status: int) -> tuple[int, str]:
    """Run ssh.expect against a fake ssh; return its exit code and what reached the pty."""
    fake = tmp_path / "ssh"
    fake.write_text(f"#!/bin/sh\nprintf '%s\\r\\n' '{output}'\nexit {status}\n")
    fake.chmod(0o755)
    text = SCRIPT.read_text()
    assert text.count('"/usr/bin/ssh"') == 1, "ssh.expect no longer names /usr/bin/ssh once"
    script = tmp_path / "ssh.expect"
    script.write_text(text.replace('"/usr/bin/ssh"', f'"{fake}"'))

    master, slave = os.openpty()
    process = subprocess.Popen(
        ["expect", str(script), "ssh", "-l", "me", "example.invalid"],
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


def test_a_failed_connection_reaches_the_tab_as_a_failure(tmp_path):
    code, _ = _run(
        tmp_path, "ssh: connect to host example.invalid port 22: Connection refused", 255
    )

    assert code == 255


def test_a_clean_logout_reaches_the_tab_as_one(tmp_path):
    code, _ = _run(tmp_path, "Connection to example.invalid closed.", 0)

    assert code == 0
