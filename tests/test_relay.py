"""relay.py's parts, run in pytest's own process (#337).

GCM runs the relay as a process of its own, and so does tests/test_osc52.py. A process so
started imports the package from the tree, not from mutmut's copy, so none of those tests
reached a mutant of it. These call `relay()` here, with terminals and pipes of the test's
own in place of its input and output, and the parts it is made of directly.
"""

from __future__ import annotations

import base64
import contextlib
import fcntl
import json
import os
import re
import select
import signal
import socket
import struct
import sys
import tempfile
import termios
import threading
import time
import warnings
from pathlib import Path
from types import SimpleNamespace

import pytest

from gnome_connection_manager import relay as relay_module

# Far longer than any of these takes on a loaded machine: a relay still running then has hung.
LIMIT = 10.0


class HungError(Exception):
    """A relay still running after LIMIT. Not TimeoutError, which is an OSError: the relay
    takes an OSError from a read or a write for the end of its input or output, and went on."""


class Descriptors:
    """The descriptors a test opens, closed after it unless it closed them itself."""

    def __init__(self):
        self.open = set()

    def add(self, fd):
        self.open.add(fd)
        return fd

    def pipe(self):
        read_end, write_end = os.pipe()
        self.open |= {read_end, write_end}
        return read_end, write_end

    def terminal(self):
        master, slave = os.openpty()
        self.open |= {master, slave}
        return master, slave

    def close(self, fd):
        self.open.discard(fd)
        os.close(fd)


@pytest.fixture
def fds():
    descriptors = Descriptors()
    yield descriptors
    for fd in descriptors.open:
        with contextlib.suppress(OSError):
            os.close(fd)


def input_of(fds, data):
    """A pipe holding `data` and then its end, for the relay's input."""
    read_end, write_end = fds.pipe()
    os.write(write_end, data)
    fds.close(write_end)
    return read_end


def read_all(fd):
    """What is waiting on `fd` now, without waiting for more."""
    os.set_blocking(fd, False)
    data = b""
    with contextlib.suppress(OSError):
        while chunk := os.read(fd, 65536):
            data += chunk
    return data


def resize(fd, rows, cols):
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def put_in_place(monkeypatch, stdin, stdout):
    """Give the relay `stdin` and `stdout` for its own, and keep its command out of this
    process: a relay that ran it in place of itself would end the test run. So too the
    command's terminal, which would make this process the leader of a session that a
    hangup ends: measured under mutmut, it died of SIGHUP, which mutmut does not count as
    a test failing (#339)."""
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(fileno=lambda: stdin))
    monkeypatch.setattr(sys, "stdout", SimpleNamespace(fileno=lambda: stdout))
    own = os.getpid()

    def in_a_child(call):
        def called(*args):
            assert os.getpid() != own, "the relay ran its command in place of itself"
            return call(*args)

        return called

    for name in ("execvp", "login_tty"):
        monkeypatch.setattr(os, name, in_a_child(getattr(os, name)))
    return own


def run_relay(monkeypatch, command, stdin, stdout, during=None, **destinations):
    """`relay(command, **destinations)` here, on `stdin` and `stdout`, and what it returns.

    The relay holds this thread until its command ends, so `during` is what a test does
    meanwhile: a timer calls it every 50 ms until it returns True. A relay still running
    after LIMIT raises HungError rather than hanging the suite.
    """
    own = put_in_place(monkeypatch, stdin, stdout)
    deadline = time.monotonic() + LIMIT
    waiting = [during] if during else []

    def on_alarm(_signum, _frame):
        if time.monotonic() > deadline:
            raise HungError
        if waiting and waiting[0]():
            waiting.clear()

    previous = signal.signal(signal.SIGALRM, on_alarm)
    signal.setitimer(signal.ITIMER_REAL, *((0.05, 0.05) if during else (LIMIT, 0)))
    try:
        with warnings.catch_warnings():
            # Under xdist this process has threads, which forkpty warns of. Its child
            # only execs.
            warnings.simplefilter("ignore", DeprecationWarning)
            return relay_module.relay(command, **destinations)
    finally:
        if os.getpid() != own:
            os._exit(1)  # a child that never ran its command must not run the tests
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def received(server):
    """Everything the one connection to `server` sent, once it has closed."""
    server.settimeout(LIMIT)
    connection, _ = server.accept()
    with connection:
        connection.settimeout(LIMIT)
        data = b""
        while chunk := connection.recv(65536):
            data += chunk
    return data


@pytest.fixture
def held_up_after_fork(monkeypatch):
    """The relay held up once it has started its program, as load holds it up, so that the
    program runs before anything the relay does next. Both ways of starting a program on a
    pty of its own are held up: `os.fork`, and `os.forkpty`, which `pty.fork` calls."""

    def held_up(fork):
        def forked():
            result = fork()
            if (result[0] if isinstance(result, tuple) else result) != 0:
                time.sleep(0.3)
            return result

        return forked

    for name in ("fork", "forkpty"):
        monkeypatch.setattr(os, name, held_up(getattr(os, name)))


# -- relay() -----------------------------------------------------------------


@pytest.mark.usefixtures("held_up_after_fork")
def test_a_program_is_given_the_terminals_size_and_its_status_comes_back(monkeypatch, fds):
    """On its first read, however late the relay gets to run after starting it. The relay
    used to size the program's terminal after starting the program, and measured under
    load, `stty size` then said 0 0 (#339)."""
    master, slave = fds.terminal()
    resize(master, 33, 111)

    status = run_relay(monkeypatch, ["sh", "-c", "stty size; exit 3"], slave, slave)

    assert status == 3
    assert b"33 111" in read_all(master)


def test_the_terminal_is_given_back_as_it_was(monkeypatch, fds):
    """Raw while the relay runs, as the program's own terminal does the line editing, and
    with no handler left for a resize to reach once the pty it fed is gone."""
    master, slave = fds.terminal()
    modes = termios.tcgetattr(slave)

    run_relay(monkeypatch, ["sh", "-c", "printf done"], slave, slave)

    assert termios.tcgetattr(slave) == modes
    assert signal.getsignal(signal.SIGWINCH) is signal.SIG_DFL
    assert read_all(master) == b"done"


# Says when it is ready for a resize, then the sizes each SIGWINCH gave it, once one of
# them is the size the test resizes to. Not printed from the handler, which can interrupt
# a print: when the relay sized the program's terminal after starting it, measured under
# load, that SIGWINCH came while READY was being printed, and printing again raised.
WINCH_PROGRAM = """
import fcntl, signal, struct, termios, time

def size():
    rows, cols = struct.unpack("HHHH", fcntl.ioctl(0, termios.TIOCGWINSZ, bytes(8)))[:2]
    return f"{rows}x{cols}"

sizes = []
signal.signal(signal.SIGWINCH, lambda *_: sizes.append(size()))
print("READY", flush=True)
deadline = time.monotonic() + 3
while "30x100" not in sizes and time.monotonic() < deadline:
    time.sleep(0.02)
print("WINCH", *sizes, flush=True)
"""


@pytest.mark.usefixtures("held_up_after_fork")
def test_a_resize_reaches_the_program(monkeypatch, fds):
    """VTE resizing the relay's terminal, which sends the relay SIGWINCH. That is the one
    SIGWINCH the program gets: its terminal has its size before it starts, where one sized
    after sent it another, which it could take before printing READY (#339)."""
    master, slave = fds.terminal()
    resize(master, 24, 80)
    seen = []

    def resize_once_ready():
        seen.append(read_all(master))
        if b"READY" not in b"".join(seen):
            return False
        resize(master, 30, 100)
        os.kill(os.getpid(), signal.SIGWINCH)
        return True

    command = [sys.executable, "-I", "-c", WINCH_PROGRAM]
    status = run_relay(monkeypatch, command, slave, slave, during=resize_once_ready)

    output = b"".join(seen) + read_all(master)
    assert status == 0, output
    assert re.search(rb"WINCH 30x100\r?\n", output), output


def test_what_is_typed_reaches_the_program_and_its_end_ends_only_input(monkeypatch, fds):
    """The program's output goes on coming through, and the relay stops watching an
    input that has ended rather than spinning on it."""
    stdin = input_of(fds, b"hello\n")
    out_read, out_write = fds.pipe()
    watched = []
    real_select = select.select

    def noting_select(readers, *rest):
        watched.append(list(readers))
        return real_select(readers, *rest)

    monkeypatch.setattr(select, "select", noting_select)
    program = 'read line; sleep 0.2; echo "got $line"; exit 5'

    status = run_relay(monkeypatch, ["sh", "-c", program], stdin, out_write)

    fds.close(out_write)
    assert status == 5
    assert b"got hello" in read_all(out_read)
    assert sum(stdin in readers for readers in watched) <= 2


def test_a_program_that_cannot_be_run_ends_with_127(monkeypatch, fds):
    """As a shell reports a command it cannot find."""
    _, out_write = fds.pipe()

    status = run_relay(monkeypatch, ["/nonexistent/gcm-test"], input_of(fds, b""), out_write)

    assert status == 127


def test_a_program_ended_by_a_signal_ends_with_128_and_its_number(monkeypatch, fds):
    _, out_write = fds.pipe()

    status = run_relay(monkeypatch, ["sh", "-c", "kill -TERM $$"], input_of(fds, b""), out_write)

    assert status == 128 + signal.SIGTERM


def test_the_relay_waits_for_the_program_and_not_only_for_its_output(monkeypatch, fds):
    """The output ends when the program lets go of its terminal, which need not be when it
    ends. The relay closes that terminal then, which hangs it up: hence the trap."""
    _, out_write = fds.pipe()
    program = "trap '' HUP; exec >/dev/null 2>&1 </dev/null; sleep 0.3; exit 4"

    status = run_relay(monkeypatch, ["sh", "-c", program], input_of(fds, b""), out_write)

    assert status == 4


def test_a_clipboard_write_reaches_gcm_and_the_terminal_both(monkeypatch, fds):
    out_read, out_write = fds.pipe()
    payload = base64.b64encode(b"copied").decode()
    with tempfile.TemporaryDirectory() as folder:
        path = str(Path(folder) / "clip.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(path)
            server.listen(1)
            status = run_relay(
                monkeypatch,
                ["sh", "-c", f"printf '\\033]52;c;{payload}\\a'"],
                input_of(fds, b""),
                out_write,
                clipboard_socket=path,
            )
            message = received(server)

    fds.close(out_write)
    assert status == 0
    assert message == (json.dumps({"selection": "c", "data": payload}) + "\n").encode()
    assert read_all(out_read) == f"\x1b]52;c;{payload}\x07".encode()


def test_the_session_is_recorded_with_its_timing(monkeypatch, fds, tmp_path):
    out_read, out_write = fds.pipe()
    raw, timing = tmp_path / "s.raw", tmp_path / "s.timing"

    run_relay(
        monkeypatch,
        ["sh", "-c", "printf one; sleep 0.1; printf two"],
        input_of(fds, b""),
        out_write,
        raw_log=str(raw),
        timing_log=str(timing),
    )

    fds.close(out_write)
    assert read_all(out_read) == raw.read_bytes() == b"onetwo"
    assert sum(int(line.split()[1]) for line in timing.read_text().splitlines()) == 6


def test_output_that_cannot_be_delivered_is_dropped_and_the_session_goes_on(monkeypatch, fds):
    out_read, out_write = fds.pipe()
    fds.close(out_read)
    program = "printf lost; sleep 0.1; printf lost; exit 2"

    status = run_relay(monkeypatch, ["sh", "-c", program], input_of(fds, b""), out_write)

    assert status == 2


def test_an_input_that_cannot_be_read_ends_input_and_not_the_session(monkeypatch, fds, tmp_path):
    """A folder: select calls it readable, and reading it fails. The program must be sent
    nothing for it."""
    folder = fds.add(os.open(tmp_path, os.O_RDONLY))
    out_read, out_write = fds.pipe()
    program = "import select; print('input' if select.select([0], [], [], 0.3)[0] else 'none')"

    status = run_relay(monkeypatch, [sys.executable, "-I", "-c", program], folder, out_write)

    fds.close(out_write)
    assert status == 0
    assert read_all(out_read) == b"none\r\n"


def test_the_terminal_going_away_ends_input_and_not_the_session(monkeypatch, fds):
    """VTE closing the relay's terminal while the program runs on. Giving that terminal its
    modes back then fails, and must not end the relay with an error."""
    master, slave = fds.terminal()
    out_read, out_write = fds.pipe()
    seen = []

    def hang_up_once_ready():
        seen.append(read_all(out_read))
        ready = re.search(rb"READY (\d+)", b"".join(seen))
        if not ready:
            return False
        fds.close(master)
        os.kill(int(ready.group(1)), signal.SIGUSR1)
        return True

    program = "trap 'echo after; exit 5' USR1; echo READY $$; while :; do sleep 0.05; done"
    status = run_relay(
        monkeypatch, ["sh", "-c", program], slave, out_write, during=hang_up_once_ready
    )

    fds.close(out_write)
    assert status == 5
    assert b"after" in b"".join(seen) + read_all(out_read)


def test_a_wait_that_fails_ends_the_relay_with_the_programs_status(monkeypatch, fds):
    """The relay's input closed under it: nothing more can be relayed, so the relay stops
    there, and still waits for its program. Not closed from the start: the relay would
    then close the program's terminal before the program had taken it, measured, and the
    child forkpty made would exit 1."""
    stdin, _ = fds.pipe()
    out_read, out_write = fds.pipe()
    seen = []

    def close_input_once_ready():
        seen.append(read_all(out_read))
        if b"READY" not in b"".join(seen):
            return False
        fds.close(stdin)
        return True

    # The relay closes the program's terminal as it stops, which hangs it up.
    program = "trap '' HUP; echo READY; sleep 0.3; exit 6"
    status = run_relay(
        monkeypatch, ["sh", "-c", program], stdin, out_write, during=close_input_once_ready
    )

    assert status == 6, b"".join(seen)


def test_off_the_main_thread_the_relay_runs_without_a_resize_handler(monkeypatch, fds):
    """Only the main thread may set a signal's handler, so elsewhere the relay goes
    without one, and must not try to put one back as it ends."""
    out_read, out_write = fds.pipe()
    own = put_in_place(monkeypatch, input_of(fds, b""), out_write)
    result = []

    def run():
        try:
            result.append(relay_module.relay(["sh", "-c", "printf off; exit 7"]))
        except Exception as error:  # noqa: BLE001 - shown by the assertion below
            result.append(error)
        finally:
            if os.getpid() != own:
                os._exit(1)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)  # forkpty, with threads
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        thread.join(LIMIT)

    fds.close(out_write)
    assert result == [7]
    assert read_all(out_read) == b"off"
    assert signal.getsignal(signal.SIGWINCH) is signal.SIG_DFL


# -- main() ------------------------------------------------------------------


@pytest.fixture
def relayed(monkeypatch):
    """What `main` hands `relay`, which here only notes it."""
    calls = []
    monkeypatch.setattr(relay_module, "relay", lambda *args: calls.append(args) or 9)
    return calls


def test_main_hands_the_relay_its_command_and_destinations(relayed):
    argv = ["--clipboard-socket", "S", "--raw-log", "R", "--timing-log", "T", "--", "sh", "-c", "x"]

    assert relay_module.main(argv) == 9
    assert relayed == [(["sh", "-c", "x"], "S", "R", "T")]


def test_main_takes_a_command_without_the_separator(relayed):
    relay_module.main(["sh", "-c", "x"])

    assert relayed == [(["sh", "-c", "x"], None, None, None)]


@pytest.mark.parametrize("argv", [[], ["--"], ["--raw-log", "R"]])
def test_main_refuses_to_run_without_a_command(relayed, capsys, argv):
    with pytest.raises(SystemExit) as refused:
        relay_module.main(argv)

    assert refused.value.code == 2
    assert "gcm-relay: error: no command given" in capsys.readouterr().err
    assert relayed == []


def test_main_describes_the_relay_when_asked(relayed, capsys, monkeypatch):
    monkeypatch.setenv("COLUMNS", "200")

    with pytest.raises(SystemExit) as answered:
        relay_module.main(["--help"])

    assert answered.value.code == 0
    assert (relay_module.__doc__ or "").splitlines()[0] in capsys.readouterr().out


# -- ClipboardChannel ----------------------------------------------------------


@pytest.fixture
def listening():
    """A socket listening as GCM's does, as `(path, server)`."""
    with tempfile.TemporaryDirectory() as folder:
        path = str(Path(folder) / "clip.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(path)
            server.listen(1)
            yield path, server


def test_the_channel_sends_each_write_as_a_line_of_json(listening):
    path, server = listening
    channel = relay_module.ClipboardChannel(path)
    channel.send("c", b"one")
    channel.send("p", b"\xff two")
    channel.close()

    *lines, rest = received(server).split(b"\n")

    assert [json.loads(line) for line in lines] == [
        {"selection": "c", "data": base64.b64encode(b"one").decode()},
        {"selection": "p", "data": base64.b64encode(b"\xff two").decode()},
    ]
    assert rest == b""


@pytest.mark.parametrize("path", [None, ""])
def test_a_channel_with_nowhere_to_send_sends_nothing(path):
    """The relay is given no socket while OSC 52 is off."""
    channel = relay_module.ClipboardChannel(path)
    channel.send("c", b"lost")
    channel.close()


def test_a_channel_that_cannot_connect_sends_nothing():
    with tempfile.TemporaryDirectory() as folder:
        channel = relay_module.ClipboardChannel(str(Path(folder) / "gone.sock"))
        channel.send("c", b"lost")
        channel.close()


def test_a_channel_whose_far_end_has_gone_stops_sending(listening):
    path, server = listening
    channel = relay_module.ClipboardChannel(path)
    connection, _ = server.accept()
    connection.close()

    channel.send("c", b"lost")
    channel.send("c", b"lost again")
    channel.close()


def test_a_closed_channel_sends_nothing_and_closes_again_quietly(listening):
    path, server = listening
    channel = relay_module.ClipboardChannel(path)
    channel.close()
    channel.send("c", b"lost")
    channel.close()

    assert received(server) == b""


# -- window_size(), set_window_size() and _write_all() --------------------------


def test_a_terminals_size_is_set_and_read_over_the_whole_range_of_its_fields(fds):
    master, slave = fds.terminal()

    relay_module.set_window_size(slave, (50, 40000, 65535, 1))

    assert relay_module.window_size(master) == (50, 40000, 65535, 1)


def test_what_is_not_a_terminal_has_no_size_and_takes_none(fds):
    read_end, write_end = fds.pipe()

    relay_module.set_window_size(write_end, (24, 80, 0, 0))
    relay_module.set_window_size(read_end, None)

    assert relay_module.window_size(read_end) is None


def test_a_write_the_system_takes_in_parts_is_carried_on_to_the_end(monkeypatch):
    """A signal arriving mid-write, a resize say, ends a write early with part of it done."""
    taken: list[bytes] = []

    def write(_fd, data):
        assert len(taken) < 10, "the same bytes written again and again"
        taken.append(bytes(data[:3]))
        return len(taken[-1])

    def hung(_signum, _frame):
        raise HungError

    monkeypatch.setattr(os, "write", write)
    previous = signal.signal(signal.SIGALRM, hung)
    signal.setitimer(signal.ITIMER_REAL, LIMIT)
    try:
        relay_module._write_all(1, b"abcdefgh")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)

    assert taken == [b"abc", b"def", b"gh"]
