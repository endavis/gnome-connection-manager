"""ssh.expect, which runs every host with a stored password: what it passes on to the tab.

That is the exit status, which a tab's Close console setting decides on (#210), and what
the program printed: why a connection failed (#212), and everything before the login,
the host key question the script answers among it (#214).

The script runs as a tab runs it, on a pty, with only its ssh or telnet swapped for a
fake that prints what the real one would and exits with its status. The installed ssh
exits 255 on an error, measured with a connection it could not make. The fakes turn
echo off before they ask for a password, as ssh and login do.
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
from typing import NamedTuple

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "data" / "scripts" / "ssh.expect"
PASSWORD = "not-a-password"

pytestmark = pytest.mark.skipif(shutil.which("expect") is None, reason="needs expect")

# Each program as the script names it, and the arguments GCM gives the script for it.
PROGRAMS = {
    "ssh": ('"/usr/bin/ssh"', ["-l", "me", "example.invalid"]),
    "telnet": ('"/usr/bin/telnet"', ["-l", "me", "example.invalid", "23"]),
}

# A first connection: ssh asks about the host's key, the script answers yes, then the
# banner and the password prompt. The fake reports what it was given, not the password.
FIRST_CONNECTION = r"""
printf "The authenticity of host 'example.invalid (192.0.2.1)' can't be established.\r\n"
printf "ED25519 key fingerprint is SHA256:GCMTESTFINGERPRINT.\r\n"
printf "This key is not known by any other names.\r\n"
printf "Are you sure you want to continue connecting (yes/no/[fingerprint])? "
read answer
printf "Warning: Permanently added 'example.invalid' (ED25519) to the list of known hosts.\r\n"
printf "GCM-TEST banner: authorised use only\r\n"
stty -echo
printf "me@example.invalid's password: "
read pw
stty echo
printf "\r\nWelcome (answer %s, password %s)\r\n" "$answer" \
    "$([ "$pw" = not-a-password ] && echo right || echo wrong)"
exit 0
"""

# telnet's own lines, a banner, then login: and Password:, and a refusal.
TELNET_LOGIN = r"""
printf "Trying 192.0.2.1...\r\nConnected to example.invalid.\r\nEscape character is '^]'.\r\n"
printf "GCM-TEST telnet banner\r\n\r\n"
printf "login: "
read user
stty -echo
printf "Password: "
read pw
stty echo
printf "\r\nLogin incorrect (user %s, password %s)\r\n" "$user" \
    "$([ "$pw" = not-a-password ] && echo right || echo wrong)"
exit 1
"""


class Run(NamedTuple):
    code: int | None  # None: still running at the deadline, and killed
    seen: str
    answered_at: float | None  # seconds from the start, when `answer`'s text appeared


def _prints(output: str | None, status: int) -> str:
    """A fake that prints `output` as one line, or nothing when it is None, then exits."""
    line = "" if output is None else f"printf '%s\\r\\n' '{output}'\n"
    return f"{line}exit {status}\n"


def _run(
    tmp_path: Path,
    fake: str,
    connection: str = "ssh",
    answer: tuple[str, bytes] | None = None,
    seconds: float = 30,
    telnet_timeout: int | None = None,
) -> Run:
    """Run ssh.expect against a fake program: its exit code, and what reached the pty.

    `answer` types its bytes once its text has reached the pty, as a user would.
    `telnet_timeout` replaces the script's 20 s wait for a prompt it knows.
    """
    program, args = PROGRAMS[connection]
    path = tmp_path / connection
    path.write_text("#!/bin/sh\n" + fake)
    path.chmod(0o755)
    text = SCRIPT.read_text()
    assert text.count(program) == 1, f"ssh.expect no longer names {program} once"
    script = tmp_path / "ssh.expect"
    text = text.replace(program, f'"{path}"')
    if telnet_timeout is not None:
        assert text.count("set timeout 20") == 1, "ssh.expect no longer waits 20 s for telnet"
        text = text.replace("set timeout 20", f"set timeout {telnet_timeout}")
    script.write_text(text)

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
    start = time.monotonic()
    deadline = start + seconds
    answered_at = None
    code: int | None = None
    # Type the password once the script has turned echo off, as GCM waits 2 s for. The
    # slave's settings: on Linux the master has settings of its own, which never echo.
    while termios.tcgetattr(slave)[3] & termios.ECHO and time.monotonic() < deadline:
        time.sleep(0.01)
    os.close(slave)
    os.write(master, PASSWORD.encode() + b"\n")  # the script reads the password first
    seen = b""
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
            if answer and answer[0] in seen.decode(errors="replace"):
                answered_at = time.monotonic() - start
                os.write(master, answer[1])
                answer = None
        if process.poll() is None:
            process.wait(timeout=max(deadline - time.monotonic(), 0.1))
        code = process.returncode
    except subprocess.TimeoutExpired:
        pass
    finally:
        # Only once expect has exited: closing the master hangs up its terminal, and
        # expect then dies of SIGHUP instead of exiting with ssh's status.
        if process.poll() is None:
            process.kill()
        os.close(master)
    return Run(code, seen.decode(errors="replace").replace("\r", ""), answered_at)


def _in_order(seen: str, *parts: str) -> None:
    at = 0
    for part in parts:
        found = seen.find(part, at)
        assert found >= 0, f"{part!r} not after {seen[:at][-60:]!r} in {seen!r}"
        at = found + len(part)


def test_a_host_key_failure_reaches_the_tab_as_a_failure(tmp_path):
    """This branch used to exit on its own, with 0, which Close console read as a clean
    exit: Only on clean exit closed the tab over the message."""
    code, seen, _ = _run(tmp_path, _prints("Host key verification failed.", 255))

    assert code == 255
    assert seen.count("Host key verification failed.") == 1


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

    code, seen, _ = _run(tmp_path, _prints(output, status), connection)

    assert seen.count(output) == 1
    assert code == status


# Not 1: expect exits with 1 when the script itself fails, so 1 could not tell them apart.
@pytest.mark.parametrize(("connection", "status"), [("ssh", 255), ("ssh", 0), ("telnet", 3)])
def test_a_program_that_prints_nothing_keeps_its_status(tmp_path, connection, status):
    code, _, _ = _run(tmp_path, _prints(None, status), connection)

    assert code == status


def test_a_clean_logout_reaches_the_tab_as_one(tmp_path):
    code, _, _ = _run(tmp_path, _prints("Connection to example.invalid closed.", 0))

    assert code == 0


def test_a_new_host_key_is_shown_as_it_is_trusted(tmp_path):
    """The script answers yes to an unknown host key. The question, the fingerprint and
    ssh's warning that the key was added never reached the tab, nor did the banner (#214)."""
    code, seen, _ = _run(tmp_path, FIRST_CONNECTION)

    assert code == 0
    _in_order(
        seen,
        "The authenticity of host 'example.invalid (192.0.2.1)' can't be established.",
        "ED25519 key fingerprint is SHA256:GCMTESTFINGERPRINT.",
        "Are you sure you want to continue connecting (yes/no/[fingerprint])? yes",
        "Warning: Permanently added 'example.invalid' (ED25519) to the list of known hosts.",
        "GCM-TEST banner: authorised use only",
        "me@example.invalid's password: ",
        "Welcome (answer yes, password right)",
    )
    assert PASSWORD not in seen
    # log_user is 0 while the script spawns, or spawn would echo its command line.
    assert "spawn" not in seen


def test_telnet_shows_what_comes_before_its_login(tmp_path):
    code, seen, _ = _run(tmp_path, TELNET_LOGIN, "telnet")

    assert code == 1
    _in_order(
        seen,
        "Trying 192.0.2.1...",
        "Connected to example.invalid.",
        "Escape character is '^]'.",
        "GCM-TEST telnet banner",
        "login: me",
        "Password: ",
        "Login incorrect (user me, password right)",
    )
    assert PASSWORD not in seen


def test_a_prompt_the_script_does_not_know_is_shown_at_once(tmp_path):
    """A prompt that matches none of the patterns waits for the user. What the user types
    reaches telnet only once the script's timeout starts interact, as it always has, and
    what came before the prompt used to be lost even then. Now it shows at once, well
    inside the timeout, which is cut to 5 s here to keep the test short."""
    fake = 'printf "GCM-TEST telnet banner\\r\\nLogin: "\nread user\nprintf "\\r\\nbye %s\\r\\n" "$user"\n'

    code, seen, answered_at = _run(
        tmp_path, fake, "telnet", answer=("Login: ", b"me\n"), seconds=15, telnet_timeout=5
    )

    assert code == 0
    _in_order(seen, "GCM-TEST telnet banner", "Login: ", "bye me")
    assert answered_at is not None and answered_at < 2.5, answered_at
