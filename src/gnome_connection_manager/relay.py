"""A PTY relay that sits between a child process and VTE.

VTE implements no OSC 52 and offers no way to observe unhandled OSC sequences, so the
only way to support it is to see the bytes first. This runs as its own process rather
than as an IO watch inside GCM: VTE keeps its C read path, and a stall or crash here
cannot freeze the interface. `script(1)` and the existing `ssh.expect` are the same
shape of middle-man.

Run as::

    python -m gnome_connection_manager.relay [--clipboard-socket PATH]
        [--raw-log PATH] -- COMMAND [ARGS]

Bytes are forwarded unmodified in both directions. The OSC 52 sequence is passed
through as well: VTE ignores it, so filtering would be extra risk for no gain.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import errno
import fcntl
import json
import os
import pty
import select
import signal
import socket
import struct
import sys
import termios
import time
import tty
from pathlib import Path

from gnome_connection_manager.utils.osc52 import Osc52Scanner

BUFFER_SIZE = 65536


def window_size(fd):
    with contextlib.suppress(OSError):
        return struct.unpack("HHHH", fcntl.ioctl(fd, termios.TIOCGWINSZ, b"\0" * 8))
    return None


def set_window_size(fd, size):
    if size is None:
        return
    with contextlib.suppress(OSError):
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", *size))


class RawRecorder:
    """Writes the child's output byte for byte, with a companion timing file.

    The bytes alone are not enough. Concatenating them discards the write boundaries,
    and those are what separate one frame from the next -- replaying a bare stream in
    file-sized blocks collapses a whole full-screen session to its final screen. The
    timing file records `<delay> <bytes>` per chunk, the same shape `script -t` writes,
    so the boundaries can be reproduced.

    The stream itself stays byte-identical to what the child produced, which keeps it
    greppable and keeps existing recordings valid. A failure here must never disturb
    the session, so it degrades to doing nothing.
    """

    def __init__(self, path, timing_path=None):
        self._handle = None
        self._timing = None
        self._last = None
        if not path:
            return
        try:
            self._handle = Path(path).open("ab", buffering=0)  # noqa: SIM115 - closed below
        except OSError:
            self._handle = None
            return
        if timing_path:
            try:
                self._timing = Path(timing_path).open("a", buffering=1)  # noqa: SIM115
            except OSError:
                self._timing = None

    def write(self, chunk):
        if self._handle is None:
            return
        now = time.monotonic()
        delay = 0.0 if self._last is None else now - self._last
        self._last = now
        try:
            self._handle.write(chunk)
        except OSError:
            # close() drops the timing file too, so the guard below then declines to
            # record a chunk that never landed. No early return is needed.
            self.close()
        if self._timing is not None:
            try:
                self._timing.write(f"{delay:.6f} {len(chunk)}\n")
            except OSError:
                self._close_timing()

    def _close_timing(self):
        if self._timing is not None:
            try:
                self._timing.close()
            finally:
                self._timing = None

    def close(self):
        self._close_timing()
        if self._handle is not None:
            try:
                self._handle.close()
            finally:
                self._handle = None


class ClipboardChannel:
    """One-way link back to GCM. A failure here must never disturb the session."""

    def __init__(self, path):
        self._socket = None
        if not path:
            return
        try:
            self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._socket.connect(path)
        except OSError:
            self._socket = None

    def send(self, selection, data):
        if self._socket is None:
            return
        message = json.dumps(
            {"selection": selection, "data": base64.b64encode(data).decode("ascii")}
        )
        try:
            self._socket.sendall(message.encode("utf-8") + b"\n")
        except OSError:
            self._socket = None

    def close(self):
        if self._socket is not None:
            self._socket.close()
            self._socket = None


def relay(command, clipboard_socket=None, raw_log=None, timing_log=None):
    """Run `command` on its own pty, forwarding bytes to and from this process's tty."""
    child_pid, master_fd = pty.fork()
    if child_pid == 0:
        try:
            os.execvp(command[0], command)
        except OSError:
            os._exit(127)

    set_window_size(master_fd, window_size(sys.stdout.fileno()))

    resized = [False]

    def on_sigwinch(_signum, _frame):
        resized[0] = True

    with_winch = False
    try:
        signal.signal(signal.SIGWINCH, on_sigwinch)
        with_winch = True
    except ValueError:
        pass

    # Our own tty must be raw: the child's pty already does echo and line editing, and
    # doing it twice mangles everything the user types.
    stdin_fd = sys.stdin.fileno()
    saved = None
    try:
        saved = termios.tcgetattr(stdin_fd)
        tty.setraw(stdin_fd)
    except termios.error:
        saved = None

    scanner = Osc52Scanner()
    stdin_open = True
    clipboard = ClipboardChannel(clipboard_socket)
    recorder = RawRecorder(raw_log, timing_log)
    try:
        while True:
            if with_winch and resized[0]:
                resized[0] = False
                set_window_size(master_fd, window_size(sys.stdout.fileno()))
            watched = [master_fd, stdin_fd] if stdin_open else [master_fd]
            try:
                readable, _, _ = select.select(watched, [], [])
            except OSError as exc:
                if exc.errno == errno.EINTR:
                    continue
                break
            if master_fd in readable:
                try:
                    chunk = os.read(master_fd, BUFFER_SIZE)
                except OSError:
                    break
                if not chunk:
                    break
                recorder.write(chunk)
                for selection, data in scanner.feed(chunk):
                    clipboard.send(selection, data)
                _write_all(sys.stdout.fileno(), chunk)
            if stdin_open and stdin_fd in readable:
                try:
                    chunk = os.read(stdin_fd, BUFFER_SIZE)
                except OSError:
                    chunk = b""
                if not chunk:
                    # Input ending is not a reason to kill the child: stop watching and
                    # keep relaying its output until it closes on its own.
                    stdin_open = False
                else:
                    _write_all(master_fd, chunk)
    finally:
        if saved is not None:
            with contextlib.suppress(termios.error, OSError):
                termios.tcsetattr(stdin_fd, termios.TCSAFLUSH, saved)
        clipboard.close()
        recorder.close()
        with contextlib.suppress(OSError):
            os.close(master_fd)

    _, status = os.waitpid(child_pid, 0)
    if os.WIFSIGNALED(status):
        return 128 + os.WTERMSIG(status)
    return os.WEXITSTATUS(status)


def _write_all(fd, data):
    while data:
        try:
            written = os.write(fd, data)
        except OSError as exc:
            if exc.errno == errno.EINTR:
                continue
            return
        data = data[written:]


def main(argv=None):
    parser = argparse.ArgumentParser(prog="gcm-relay", description=__doc__)
    parser.add_argument("--clipboard-socket", default=None)
    parser.add_argument("--raw-log", default=None)
    parser.add_argument("--timing-log", default=None)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("no command given")
    return relay(command, args.clipboard_socket, args.raw_log, args.timing_log)


if __name__ == "__main__":
    sys.exit(main())
