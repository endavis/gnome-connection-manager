"""Tests for utils/afterlogin.py: when a host's commands after login go, and what becomes
of what is typed before then (#312).

`Gate` is pure, so it is driven with explicit times. The reading of /proc is tested
against real processes on real ptys, and against a /proc of the test's own for a kernel
without `children` lists. The end-to-end scenarios against real GTK are in
tests/test_commands_after_login.py.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import termios
import threading
import time
import warnings
from pathlib import Path

import pytest

from gnome_connection_manager.utils import afterlogin
from gnome_connection_manager.utils.afterlogin import (
    CONNECTING,
    FIND_WAIT,
    GIVE_UP,
    HOLD,
    PASS,
    QUIET,
    SECRET,
    SESSION,
    SETTLE,
    Gate,
)

COMMANDS = [(0, "echo one")]


# -- the commands -------------------------------------------------------------------


def scheduled_before_312(commands, basetime=3000):
    """When start_session typed each group before #312, in ms after the spawn: its loop,
    as it was, kept here to hold command_groups to it."""
    out = []
    lines: list = []
    for line in commands.splitlines():
        if line.startswith("##D=") and line[4:].isdigit():
            if len(lines):
                out.append((basetime, "\r".join(lines)))
                lines = []
            basetime += int(line[4:])
        else:
            lines.append(line)
    if len(lines):
        out.append((basetime, "\r".join(lines)))
    return out


@pytest.mark.parametrize(
    "commands",
    [
        "echo one",
        "echo one\necho two",
        "cd /srv\n##D=500\nmake\n##D=250\n##D=250\nmake check",
        "##D=1000\nsudo -i",
        "echo one\n##D=300",
        "echo one\n\necho two",
        "##D=x\n##D=\n##D=-5\necho one",
    ],
)
def test_command_groups_keeps_the_waits_start_session_had(commands):
    groups = afterlogin.command_groups(commands)
    assert [(3000 + delay, text) for delay, text in groups] == scheduled_before_312(commands)


def test_command_groups():
    assert afterlogin.command_groups("a\nb\n##D=500\nc\n##D=250\nd") == [
        (0, "a\rb"),
        (500, "c"),
        (750, "d"),
    ]
    assert afterlogin.command_groups("##D=100\n##D=200") == []


# -- what the login is doing --------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Are you sure you want to continue connecting (yes/no/[fingerprint])? ",
        "Please type 'yes', 'no' or the fingerprint: ",
        "ops@db-01's password: ",
        "Enter passphrase for key '/home/ops/.ssh/id_ed25519': ",
        "Passcode or option (1-3): ",
        "Accept updated hostkeys? (yes/no): ",
    ],
)
def test_text_before_the_cursor_is_a_question(text):
    assert afterlogin.asking(text)


@pytest.mark.parametrize("text", ["", "   ", "\t"])
def test_nothing_before_the_cursor_asks_nothing(text):
    assert not afterlogin.asking(text)


def test_state_of():
    assert afterlogin.state_of(termios.ICANON | termios.ECHO) == CONNECTING
    assert afterlogin.state_of(termios.ICANON) == SECRET
    assert afterlogin.state_of(0) == SESSION
    assert afterlogin.state_of(termios.ECHO) == SESSION


@pytest.fixture
def on_a_pty():
    """A process reading a pty of the test's own, and a way to set that pty's modes."""
    master, slave = os.openpty()
    process = subprocess.Popen(["sleep", "30"], stdin=slave)

    def modes(on, off):
        attrs = termios.tcgetattr(slave)
        attrs[3] = (attrs[3] | on) & ~off
        termios.tcsetattr(slave, termios.TCSADRAIN, attrs)

    try:
        yield process.pid, modes
    finally:
        process.kill()
        process.wait()
        os.close(master)
        os.close(slave)


def test_terminal_state_reads_the_terminal_a_process_reads(on_a_pty):
    pid, modes = on_a_pty
    modes(termios.ICANON | termios.ECHO, 0)
    assert afterlogin.terminal_state(pid) == CONNECTING
    modes(0, termios.ECHO)
    assert afterlogin.terminal_state(pid) == SECRET
    modes(0, termios.ICANON)
    assert afterlogin.terminal_state(pid) == SESSION


def test_terminal_state_is_none_without_a_terminal():
    process = subprocess.Popen(["sleep", "30"], stdin=subprocess.DEVNULL)
    try:
        assert afterlogin.terminal_state(process.pid) is None
    finally:
        process.kill()
        process.wait()
    assert afterlogin.terminal_state(process.pid) is None  # and once it has gone


def test_find_program_finds_the_nearest_among_real_processes(tmp_path):
    """An ssh further down is found while it is the only one, and the nearer once that
    starts: a ProxyJump's ssh is the session's ssh's child."""
    for folder in ("near", "deep"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "ssh").symlink_to(shutil.which("sleep"))
    deep = tmp_path / "deep.sh"
    deep.write_text(f"#!/bin/sh\n{tmp_path / 'deep' / 'ssh'} 30\n")
    deep.chmod(0o755)
    near = tmp_path / "near" / "ssh"
    root = subprocess.Popen(
        ["sh", "-c", f"{deep} & read go; {near} 30 & wait"],
        stdin=subprocess.PIPE,
        start_new_session=True,
    )

    def found(path):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            pid = afterlogin.find_program(root.pid, "ssh")
            argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0") if pid else []
            if argv and argv[0] == bytes(path):
                return True
            time.sleep(0.05)
        return False

    try:
        assert found(tmp_path / "deep" / "ssh")
        root.stdin.write(b"go\n")
        root.stdin.flush()
        assert found(near)
        assert afterlogin.find_program(root.pid, "absent") is None
    finally:
        os.killpg(root.pid, signal.SIGKILL)
        root.wait()


def fake_proc(tmp_path, tree, children_lists=True):
    """A /proc for `tree`, {pid: (name, parent)}."""
    proc = tmp_path / "proc"
    for pid, (name, parent) in tree.items():
        folder = proc / str(pid)
        (folder / "task" / str(pid)).mkdir(parents=True)
        (folder / "comm").write_text(name + "\n")
        # A name can hold parentheses and spaces of its own.
        (folder / "stat").write_text(f"{pid} ({name}) S {parent} 1 1 0 -1\n")
        if children_lists:
            kids = [str(child) for child, (_name, up) in tree.items() if up == pid]
            (folder / "task" / str(pid) / "children").write_text(" ".join(kids) + " ")
    (proc / "self").mkdir()
    return str(proc)


TREE = {
    10: ("python3", 1),
    11: ("ssh.expect", 10),
    12: ("stty", 11),
    13: ("ssh", 11),
    14: ("ssh", 13),
    # A later sibling with an ssh further down: found first by a search that goes deep.
    15: ("sh", 11),
    16: ("ssh", 15),
    20: ("a (b) c", 1),
}


@pytest.mark.parametrize("children_lists", [True, False])
def test_find_program_in_a_proc_of_its_own(tmp_path, children_lists):
    proc = fake_proc(tmp_path, TREE, children_lists)
    assert afterlogin.find_program(10, "ssh", proc) == 13
    assert afterlogin.find_program(13, "ssh", proc) == 13
    assert afterlogin.find_program(14, "ssh", proc) == 14
    assert afterlogin.find_program(10, "telnet", proc) is None
    assert afterlogin.find_program(99, "ssh", proc) is None
    assert sorted(afterlogin.children(11, proc)) == [12, 13, 15]


def test_parents_reads_a_name_with_parentheses(tmp_path):
    assert (20, 1) in afterlogin.parents(fake_proc(tmp_path, TREE))


# -- when the commands are due ------------------------------------------------------


def test_the_commands_wait_for_the_session_then_for_its_output_to_pause():
    gate = Gate("ssh", COMMANDS, spawned=0.0)
    assert not gate.due(None, False, 0.05)
    assert not gate.due(CONNECTING, False, 1.0)
    assert not gate.due(SESSION, False, 1.5)
    gate.output(1.6)  # the remote prompt
    assert not gate.due(SESSION, False, 1.6 + QUIET - 0.01)
    assert gate.due(SESSION, False, 1.6 + QUIET)


def test_output_that_never_pauses_waits_no_longer_than_settle():
    gate = Gate("ssh", COMMANDS, spawned=0.0)
    gate.due(SESSION, False, 1.0)
    now = 1.0
    while now < 1.0 + SETTLE - 0.05:
        gate.output(now)
        assert not gate.due(SESSION, False, now)
        now += 0.05
    gate.output(1.0 + SETTLE)
    assert gate.due(SESSION, False, 1.0 + SETTLE)


def test_a_slow_login_is_waited_for():
    """Where they used to go at 3 s."""
    gate = Gate("ssh", COMMANDS, spawned=0.0)
    assert not gate.due(CONNECTING, False, 3.0)
    assert not gate.due(CONNECTING, False, GIVE_UP - 0.01)
    assert not gate.due(SESSION, False, 10.0)
    assert gate.due(SESSION, False, 10.0 + QUIET)


def test_a_session_that_never_starts_gets_them_after_give_up():
    gate = Gate("ssh", COMMANDS, spawned=0.0)
    assert not gate.due(CONNECTING, False, GIVE_UP - 0.01)
    assert gate.due(CONNECTING, False, GIVE_UP)


@pytest.mark.parametrize(("state", "asked"), [(CONNECTING, True), (SECRET, False)])
def test_give_up_counts_from_the_last_thing_asked(state, asked):
    gate = Gate("ssh", COMMANDS, spawned=0.0)
    assert not gate.due(state, asked, 60.0)  # the user reads a fingerprint for a minute
    assert not gate.due(CONNECTING, False, 60.0 + GIVE_UP - 0.01)
    assert gate.due(CONNECTING, False, 60.0 + GIVE_UP)


def test_a_program_never_found_gets_them_as_it_always_did():
    gate = Gate("ssh", COMMANDS, spawned=0.0)
    assert not gate.due(None, False, FIND_WAIT - 0.01)
    assert gate.due(None, False, FIND_WAIT)
    asked = Gate("ssh", COMMANDS, spawned=0.0)
    assert not asked.due(None, True, 2.0)
    assert not asked.due(None, False, 2.0 + FIND_WAIT - 0.01)


def test_a_question_of_ssh_s_own_in_the_session_is_waited_for():
    """UpdateHostKeys=ask: ssh leaves raw mode to ask, and goes back once answered."""
    gate = Gate("ssh", COMMANDS, spawned=0.0)
    gate.due(SESSION, False, 1.0)
    assert not gate.due(CONNECTING, True, 1.0 + QUIET)
    assert not gate.due(CONNECTING, True, 30.0)
    assert not gate.due(SESSION, False, 31.0)
    assert gate.due(SESSION, False, 31.0 + QUIET)


# -- each key typed meanwhile -------------------------------------------------------


def test_keys_typed_while_connecting_are_held():
    gate = Gate("ssh", COMMANDS, spawned=0.0)
    assert gate.key(None, False, False) == HOLD
    assert gate.key(CONNECTING, False, False) == HOLD


@pytest.mark.parametrize(("state", "asked"), [(CONNECTING, True), (SECRET, False), (SECRET, True)])
def test_keys_answering_the_login_pass(state, asked):
    gate = Gate("ssh", COMMANDS, spawned=0.0)
    assert gate.key(state, asked, False) == PASS


@pytest.mark.parametrize("state", [None, CONNECTING])
def test_a_key_with_ctrl_acts_on_the_login(state):
    assert Gate("ssh", COMMANDS, spawned=0.0).key(state, False, True) == PASS


@pytest.mark.parametrize(("asked", "control"), [(False, False), (True, False), (True, True)])
def test_every_key_is_held_once_the_session_has_started(asked, control):
    gate = Gate("ssh", COMMANDS, spawned=0.0)
    assert gate.key(SESSION, asked, control) == HOLD


def test_every_key_is_held_while_the_commands_are_typed():
    gate = Gate("ssh", COMMANDS, spawned=0.0)
    gate.sending = True
    assert gate.key(CONNECTING, True, True) == HOLD


def test_a_question_in_the_session_is_answered():
    gate = Gate("ssh", COMMANDS, spawned=0.0)
    gate.due(SESSION, False, 1.0)
    assert gate.key(CONNECTING, True, False) == PASS
    assert gate.key(CONNECTING, False, False) == HOLD


# -- reading /proc as the kernel lays it out, and the edges of the waits (#337) -----------


@pytest.fixture
def listed_as_proc_lists(monkeypatch):
    """Each folder listed as the real /proc lists itself: its other entries, `self` and
    `bus` and the rest, before the processes. A folder of the test's own lists in an
    order of the filesystem's, which put `self` last here and first on CI (#337)."""
    real = Path.iterdir
    monkeypatch.setattr(
        Path,
        "iterdir",
        lambda self: iter(sorted(real(self), key=lambda p: (p.name.isdigit(), p.name))),
    )


def test_parents_reads_past_entries_that_are_no_process(tmp_path, listed_as_proc_lists):
    """Not a number, or a process gone before its stat was read."""
    proc = fake_proc(tmp_path, {7: ("sh", 1), 9: ("ssh", 7)})
    (Path(proc) / "5").mkdir()
    (Path(proc) / "5" / "stat").write_text("5 (gon")

    assert afterlogin.parents(proc) == [(7, 1), (9, 7)]


def test_children_reads_every_threads_list_where_the_kernel_keeps_them(
    tmp_path, listed_as_proc_lists
):
    """Each thread lists the children it started, and one whose list cannot be read is
    passed over. The lists are what is read, not the parent each child names, which
    disagree here for 12, as they cannot on a real kernel."""
    proc = fake_proc(tmp_path, {10: ("sh", 1), 11: ("ssh", 10), 12: ("ssh", 99)})
    task = Path(proc) / "10" / "task"
    (task / "1" / "children").mkdir(parents=True)
    (task / "30").mkdir()
    (task / "30" / "children").write_text("12 ")

    assert sorted(afterlogin.children(10, proc)) == [11, 12]


def test_children_and_parents_read_the_real_proc_unless_told_otherwise():
    process = subprocess.Popen(["sleep", "30"])
    try:
        assert process.pid in afterlogin.children(os.getpid())
        assert (process.pid, os.getpid()) in afterlogin.parents()
    finally:
        process.kill()
        process.wait()


def test_find_program_searches_a_process_listed_twice_once_and_goes_on(tmp_path):
    """Listed under two parents, as a process can be while it is reparented."""
    proc = fake_proc(tmp_path, {1: ("sh", 0), 2: ("sh", 1), 3: ("sh", 1), 4: ("ssh", 3)})
    (Path(proc) / "2" / "task" / "2" / "children").write_text("3 ")

    assert afterlogin.find_program(1, "ssh", proc) == 4


def test_find_program_ends_its_search_of_a_tree_that_loops(tmp_path):
    """A pid reused while the tree was read can make one. The search runs on a thread of
    its own, so that one that never ends fails here rather than hanging the suite."""
    proc = fake_proc(tmp_path, {1: ("sh", 2), 2: ("sh", 1)})
    found = []
    search = threading.Thread(
        target=lambda: found.append(afterlogin.find_program(1, "ssh", proc)), daemon=True
    )

    search.start()
    search.join(5)

    assert found == [None]


def test_find_program_passes_over_a_process_gone_before_it_was_read(tmp_path):
    proc = fake_proc(tmp_path, {1: ("sh", 0), 2: ("sh", 1), 3: ("ssh", 1)})
    (Path(proc) / "2" / "comm").unlink()

    assert afterlogin.find_program(1, "ssh", proc) == 3


@pytest.mark.parametrize("name", ["ssh ", "sshX"])
def test_find_program_drops_only_the_new_line_the_kernel_ends_a_name_with(tmp_path, name):
    """Anything else at its end makes it another program."""
    proc = fake_proc(tmp_path, {1: (name, 0)})

    assert afterlogin.find_program(1, "ssh", proc) is None


def test_reading_a_sessions_terminal_never_makes_it_gcms(tmp_path):
    """A session leader with no terminal of its own, as GCM can be, takes the first it
    opens without O_NOCTTY as its own, and its hangups with it. The child is forked,
    not started, so that it runs this process's code: mutation testing changes only that.
    """
    assert afterlogin.terminal_state(os.getpid(), str(tmp_path)) is None  # seen running here
    with warnings.catch_warnings():
        # Under xdist the process has threads. The child only makes system calls and exits.
        warnings.simplefilter("ignore", DeprecationWarning)
        pid = os.fork()
    if pid == 0:
        status = 2
        try:
            os.setsid()
            _master, slave = os.openpty()
            os.dup2(slave, 0)
            afterlogin.terminal_state(os.getpid())
            try:
                os.close(os.open("/dev/tty", os.O_RDONLY))
                status = 1
            except OSError:
                status = 0
        finally:
            os._exit(status)
    _, status = os.waitpid(pid, 0)

    assert os.waitstatus_to_exitcode(status) == 0


def test_a_new_gate_holds_its_program_and_commands_and_no_keys():
    """What app.py reads of it: the program to find, the commands to type, the keys held."""
    gate = Gate("ssh", COMMANDS, spawned=0.0)

    assert (gate.program, gate.commands, gate.held) == ("ssh", COMMANDS, [])


def test_the_commands_go_once_a_silent_session_has_been_raw_for_quiet():
    """With no output at all, the quiet counts from the moment the terminal went raw."""
    gate = Gate("ssh", COMMANDS, spawned=0.0)

    assert not gate.due(SESSION, False, 0.0)
    assert gate.due(SESSION, False, QUIET)
