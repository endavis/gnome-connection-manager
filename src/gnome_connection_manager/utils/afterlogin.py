"""When a host's commands after login are typed, and what becomes of what is typed into
its tab before then (#312).

GCM typed them 3 s after the spawn, whatever the session was doing. What was typed into
the tab meanwhile went in front of them, joining the first, and a login still asking
something at 3 s took them for its answer.

An SSH host's commands now go once its session has started and its output has paused.
ssh shows the start by putting its own terminal in raw mode: measured with OpenSSH 9.6,
no more than 70 ms before the remote prompt showed. While it connects, and while it asks
about a host key, that terminal is canonical with echo, and while it reads a password or
a passphrase, canonical without. Run directly, ssh's terminal is the tab's. Under
ssh.expect or relay.py it is one of theirs, so `find_program` finds ssh among the tab's
processes and `terminal_state` reads the terminal it reads.

Until the commands have gone, `Gate` decides what becomes of each key typed into the
tab: held, and typed after them, or passed on, as an answer to the login.

Pure but for reading /proc, whose root is an argument. The time is an argument too.
"""

from __future__ import annotations

import os
import termios
from pathlib import Path

# The state of the terminal the session's program reads.
CONNECTING = "connecting"  # canonical with echo: connecting, or asking a question
SECRET = "secret"  # canonical without echo: reading a password or a passphrase
SESSION = "session"  # raw: the session has started

# What becomes of a key typed while the commands wait.
HOLD = "hold"  # typed after the commands
PASS = "pass"  # typed now

QUIET = 0.3  # seconds the session's output must pause once it has started
SETTLE = 2.0  # seconds after the session started that the commands go, paused or not
# Seconds after the spawn, or after the login last asked something, that the commands go
# anyway: a session without a terminal of its own, as ssh -T starts, never shows its start.
GIVE_UP = 20.0
# The same, for a program never found, after which the commands go as they always did.
FIND_WAIT = 3.0


def command_groups(commands: str) -> list[tuple[int, str]]:
    """A host's commands as the lines typed together, each group with the milliseconds
    from when the first could go to when it does. A `##D=<ms>` line adds its wait to
    the groups after it."""
    groups: list[tuple[int, str]] = []
    delay = 0
    lines: list[str] = []
    for line in commands.splitlines():
        if line.startswith("##D=") and line[4:].isdigit():
            if lines:
                groups.append((delay, "\r".join(lines)))
                lines = []
            delay += int(line[4:])
        else:
            lines.append(line)
    if lines:
        groups.append((delay, "\r".join(lines)))
    return groups


def asking(before_cursor: str) -> bool:
    """Whether the login is asking something, from the text before the cursor on its row.

    A question leaves the cursor after it, where a line of ssh's, or the server's, ends.
    A key held shows nowhere, so what is there was printed by the program, or is an
    answer it echoed."""
    return bool(before_cursor.strip())


def state_of(lflag: int) -> str:
    """A terminal's state from its local modes."""
    if not lflag & termios.ICANON:
        return SESSION
    return CONNECTING if lflag & termios.ECHO else SECRET


def terminal_state(pid: int, proc: str = "/proc") -> str | None:
    """The state of the terminal process `pid` reads as its standard input. None when that
    cannot be read: the process has gone, or reads no terminal."""
    try:
        fd = os.open(f"{proc}/{pid}/fd/0", os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        return state_of(termios.tcgetattr(fd)[3])
    except termios.error:
        return None
    finally:
        os.close(fd)


def children(pid: int, proc: str = "/proc") -> list[int]:
    """The processes `pid` started, as each of its threads lists them, or, on a kernel
    without those lists, as each process names its parent."""
    try:
        tasks = list(Path(proc, str(pid), "task").iterdir())
    except OSError:
        return []
    found: list[int] = []
    for task in tasks:
        try:
            found += [int(child) for child in (task / "children").read_text().split()]
        except FileNotFoundError:
            return [child for child, parent in parents(proc) if parent == pid]
        except OSError:
            continue
    return found


def parents(proc: str = "/proc") -> list[tuple[int, int]]:
    """Each process, with its parent's."""
    pairs = []
    for entry in Path(proc).iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
            # After the name, in parentheses, which can hold either of its own.
            pairs.append((int(entry.name), int(stat.rsplit(")", 1)[1].split()[1])))
        except (OSError, IndexError, ValueError):
            continue
    return pairs


def find_program(root: int, name: str, proc: str = "/proc") -> int | None:
    """The process named `name` nearest `root` among those it heads, `root` included, or
    None. The nearest, since ssh runs another for a ProxyJump."""
    queue, seen = [root], set()
    while queue:
        pid = queue.pop(0)
        if pid in seen:
            continue
        seen.add(pid)
        try:
            if Path(proc, str(pid), "comm").read_text().rstrip("\n") == name:
                return pid
        except OSError:
            continue
        queue += children(pid, proc)
    return None


class Gate:
    """One session's commands after login, from its spawn until they have been typed.

    The caller polls `due`, and asks `key` about each key typed into the tab meanwhile,
    keeping in `held` what is to be typed after the commands. It sets `pid` to the
    session's program once found, and `sending` as it starts typing the commands.
    """

    def __init__(self, program: str, commands: list[tuple[int, str]], spawned: float):
        self.program = program  # the program's name, as /proc gives it
        self.commands = commands  # as command_groups gives them
        self.pid: int | None = None
        self.held: list = []
        self.sending = False
        self.found = False  # whether the program's terminal has been read
        self.waiting_since = spawned  # the spawn, or the last time the login asked
        self.raw_since: float | None = None  # while the terminal is raw
        self.last_output: float | None = None

    def output(self, now: float) -> None:
        """Note a change to the tab's screen at `now`."""
        self.last_output = now

    def due(self, state: str | None, asked: bool, now: float) -> bool:
        """Note `state` at `now`, with `asked` whether the login is asking something, and
        say whether the commands are due.

        They are, once the terminal has been raw for QUIET without output, or for SETTLE
        whatever the output. Otherwise only GIVE_UP after the spawn, or after the login
        last asked something, or FIND_WAIT when the program was never found.
        """
        if state is not None:
            self.found = True
        if state == SESSION:
            if self.raw_since is None:
                self.raw_since = now
            quiet = now - max(self.raw_since, self.last_output or 0) >= QUIET
            return quiet or now - self.raw_since >= SETTLE
        # A session can ask something of ssh's own, as UpdateHostKeys=ask has it do.
        self.raw_since = None
        if asked or state == SECRET:
            self.waiting_since = now
            return False
        return now - self.waiting_since >= (GIVE_UP if self.found else FIND_WAIT)

    def key(self, state: str | None, asked: bool, control: bool) -> str:
        """What becomes of a key typed at `state`, with `asked` whether the login is asking
        something and `control` whether the key was pressed with Ctrl.

        While the terminal is raw, it is held: the session has started. Otherwise it
        answers a question or a secret being read, and a key with Ctrl, such as Ctrl+C,
        acts on the login. Any other is held, since ssh would hand it to the session
        ahead of the commands.
        """
        if self.sending or state == SESSION:
            return HOLD
        if asked or state == SECRET or control:
            return PASS
        return HOLD
