"""ssh.expect, which runs every host with a stored password: what it passes on to the tab.

That is the exit status, which a tab's Close console setting decides on (#210), and what
the program printed: why a connection failed (#212), and everything before the login
(#214). It is also what the user types at the host key question, which the script used
to answer itself (#216).

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
from typing import TYPE_CHECKING, NamedTuple

import pytest

if TYPE_CHECKING:
    from collections.abc import Sequence

SCRIPT = Path(__file__).resolve().parents[1] / "data" / "scripts" / "ssh.expect"
PASSWORD = "not-a-password"

pytestmark = pytest.mark.skipif(shutil.which("expect") is None, reason="needs expect")

# Each program as the script names it, and the arguments GCM gives the script for it.
PROGRAMS = {
    "ssh": ('"/usr/bin/ssh"', ["-l", "me", "example.invalid"]),
    "telnet": ('"/usr/bin/telnet"', ["-l", "me", "example.invalid", "23"]),
}

# A first connection: ssh asks about the host's key and waits for an answer, asking again
# until it gets one it takes, then the banner and the password prompt. The fake reports
# what it was given, not the password.
QUESTION = "(yes/no/[fingerprint])? "
ASKED_AGAIN = "Please type 'yes', 'no' or the fingerprint: "
FIRST_CONNECTION = r"""
printf "The authenticity of host 'example.invalid (192.0.2.1)' can't be established.\r\n"
printf "ED25519 key fingerprint is SHA256:GCMTESTFINGERPRINT.\r\n"
printf "This key is not known by any other names.\r\n"
printf "Are you sure you want to continue connecting (yes/no/[fingerprint])? "
while :; do
    read answer || answer=no
    case "$answer" in
        yes|SHA256:GCMTESTFINGERPRINT) break ;;
        no) printf "Host key verification failed.\r\n"; exit 255 ;;
    esac
    printf "Please type 'yes', 'no' or the fingerprint: "
done
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
    answered_at: list[float]  # seconds from the start, when each answer was typed


def _prints(output: str | None, status: int) -> str:
    """A fake that prints `output` as one line, or nothing when it is None, then exits."""
    line = "" if output is None else f"printf '%s\\r\\n' '{output}'\n"
    return f"{line}exit {status}\n"


def _run(
    tmp_path: Path,
    fake: str,
    connection: str = "ssh",
    answers: Sequence[tuple[str, bytes]] = (),
    seconds: float = 30,
    telnet_timeout: int | None = None,
    raw: bool = False,
) -> Run:
    """Run ssh.expect against a fake program: its exit code, and what reached the pty.

    Each of `answers` types its bytes once its text has reached the pty, after the text
    of the one before it, as a user would. With `raw`, each also waits for the script to
    put the terminal in raw mode, as interact does: until then a Ctrl+C interrupts the
    script, not the program. `telnet_timeout` replaces the script's 20 s wait for a
    prompt it knows.
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
    slave_name = os.ttyname(slave)
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
    pending = list(answers)
    answered_at: list[float] = []
    after = 0  # where the next answer's text is looked for
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
            shown = seen.decode(errors="replace")
            while pending and (found := shown.find(pending[0][0], after)) >= 0:
                if raw:
                    _wait_for_raw_mode(slave_name, deadline)
                after = found + len(pending[0][0])
                answered_at.append(time.monotonic() - start)
                os.write(master, pending.pop(0)[1])
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


def _wait_for_raw_mode(name: str, deadline: float) -> None:
    """Until interact has put the terminal in raw mode, where Ctrl+C is only a key."""
    while time.monotonic() < deadline:
        fd = os.open(name, os.O_RDWR | os.O_NOCTTY)
        try:
            if not termios.tcgetattr(fd)[3] & termios.ISIG:
                return
        finally:
            os.close(fd)
        time.sleep(0.01)


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


def test_a_new_host_key_waits_for_the_user(tmp_path):
    """The script used to answer yes to an unknown host key itself, so a host with a
    stored password trusted any key, and then sent the password to its server (#216)."""
    code, seen, _ = _run(tmp_path, FIRST_CONNECTION, seconds=2)

    assert code is None  # still asking at the deadline
    assert seen.endswith(QUESTION), seen
    assert "Permanently added" not in seen


@pytest.mark.parametrize("answer", ["yes", "SHA256:GCMTESTFINGERPRINT"])
def test_a_new_host_key_is_trusted_once_the_user_answers(tmp_path, answer):
    """Then the script goes on to the password, as before. Until #214 none of this reached
    the tab: not the question, the fingerprint, ssh's warning that the key was added, nor
    the banner."""
    code, seen, _ = _run(tmp_path, FIRST_CONNECTION, answers=[(QUESTION, f"{answer}\r".encode())])

    assert code == 0
    _in_order(
        seen,
        "The authenticity of host 'example.invalid (192.0.2.1)' can't be established.",
        "ED25519 key fingerprint is SHA256:GCMTESTFINGERPRINT.",
        f"Are you sure you want to continue connecting (yes/no/[fingerprint])? {answer}",
        "Warning: Permanently added 'example.invalid' (ED25519) to the list of known hosts.",
        "GCM-TEST banner: authorised use only",
        "me@example.invalid's password: ",
        f"Welcome (answer {answer}, password right)",
    )
    assert PASSWORD not in seen
    # log_user is 0 while the script spawns, or spawn would echo its command line.
    assert "spawn" not in seen


def test_answering_no_ends_the_connection(tmp_path):
    code, seen, _ = _run(tmp_path, FIRST_CONNECTION, answers=[(QUESTION, b"no\r")], seconds=10)

    assert code == 255
    assert seen.count("Host key verification failed.") == 1
    assert "password:" not in seen


def test_an_answer_ssh_refuses_is_asked_again(tmp_path):
    """ssh asks again in words of its own, which the script must hand to the user too."""
    answers = [(QUESTION, b"y\r"), (ASKED_AGAIN, b"yes\r")]

    code, seen, _ = _run(tmp_path, FIRST_CONNECTION, answers=answers, seconds=10)

    assert code == 0
    _in_order(seen, f"{QUESTION}y", f"{ASKED_AGAIN}yes", "Welcome (answer yes, password right)")


def test_an_answer_typed_before_the_question_is_not_lost(tmp_path):
    """ssh reads an answer typed ahead once it asks, so the script must pass it on too.
    interact dropped all of it but the Enter when it was typed before interact began."""
    fake = FIRST_CONNECTION.replace('printf "Are you sure', 'sleep 1\nprintf "Are you sure', 1)
    answers = [("This key is not known by any other names.", b"yes\r")]

    code, seen, _ = _run(tmp_path, fake, answers=answers, seconds=10)

    assert code == 0
    assert "Welcome (answer yes, password right)" in seen


def test_ctrl_c_at_the_question_is_not_a_clean_exit(tmp_path):
    """Ctrl+C at the question kills ssh. For a program killed by a signal exp_wait gives
    0, which the script passed on as a clean exit, so Only on clean exit closed the tab."""
    code, seen, _ = _run(tmp_path, FIRST_CONNECTION, answers=[(QUESTION, b"\x03")], raw=True)

    assert code == 128 + 2  # SIGINT, as a shell reports it
    # interact returns when ssh ends, and the expect block must not go on after it.
    assert "while executing" not in seen, seen


def test_a_program_killed_by_a_signal_is_not_a_clean_exit(tmp_path):
    code, _, _ = _run(tmp_path, "kill -TERM $$\n")

    assert code == 128 + 15


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
        tmp_path, fake, "telnet", answers=[("Login: ", b"me\n")], seconds=15, telnet_timeout=5
    )

    assert code == 0
    _in_order(seen, "GCM-TEST telnet banner", "Login: ", "bye me")
    assert answered_at and answered_at[0] < 2.5, answered_at
