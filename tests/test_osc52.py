"""Tests for OSC 52 extraction.

This is untrusted input by definition -- the bytes come from whatever runs in the
terminal, including a remote host over SSH -- so the negative cases matter as much as
the positive ones.
"""

from __future__ import annotations

import base64
import enum
import fcntl
import inspect
import json
import logging
import os
import select
import shutil
import socket
import struct
import subprocess
import sys
import termios
import time
import types
from pathlib import Path

import pytest

from gnome_connection_manager.utils import childpython
from gnome_connection_manager.utils.osc52 import (
    KERNEL_RELEASE_FILE,
    MAX_PAYLOAD,
    MAX_SETS,
    REPAIR_GAP,
    REPEAT_WINDOW,
    WSLG_FOLDER,
    ClipboardWatch,
    Osc52Scanner,
    RepeatFilter,
    kernel_release,
    under_wslg,
    wslg_folder,
)
from tests.test_connections import glib_complaints
from tests.test_console_window import _private_display


def sequence(data: bytes, selection: str = "c", terminator: bytes = b"\x07") -> bytes:
    payload = base64.b64encode(data)
    return b"\x1b]52;" + selection.encode() + b";" + payload + terminator


def test_bel_terminated():
    assert Osc52Scanner().feed(sequence(b"hello")) == [("c", b"hello")]


def test_st_terminated():
    assert Osc52Scanner().feed(sequence(b"hello", terminator=b"\x1b\\")) == [("c", b"hello")]


def test_primary_selection():
    assert Osc52Scanner().feed(sequence(b"x", selection="p")) == [("p", b"x")]


def test_surrounding_output_is_ignored():
    stream = b"before " + sequence(b"mid") + b" after"

    assert Osc52Scanner().feed(stream) == [("c", b"mid")]


def test_several_writes_in_one_chunk():
    stream = sequence(b"one") + b"noise" + sequence(b"two")

    assert Osc52Scanner().feed(stream) == [("c", b"one"), ("c", b"two")]


@pytest.mark.parametrize("size", [1, 2, 3, 5, 17])
def test_a_sequence_split_across_chunks_is_still_found(size):
    """A terminal hands over whatever the read returned; sequences straddle chunks."""
    stream = b"lead " + sequence(b"split me") + b" tail"
    scanner = Osc52Scanner()

    found = [w for i in range(0, len(stream), size) for w in scanner.feed(stream[i : i + size])]

    assert found == [("c", b"split me")]


def test_the_read_direction_is_refused():
    """ESC]52;c;? asks the terminal to send the clipboard back -- that is exfiltration."""
    assert Osc52Scanner().feed(b"\x1b]52;c;?\x07") == []
    assert Osc52Scanner().feed(b"\x1b]52;c;?QQ==\x07") == []


def test_the_read_direction_guard_does_not_rely_on_base64_validation():
    """Two layers reject a query, and strict base64 hides whether the guard works.

    Checked directly because it is the layer that would still hold if the decode were
    ever relaxed: b64decode without validate=True silently drops the "?" and returns
    real bytes, so the explicit refusal is what stops a clipboard read.
    """
    assert base64.b64decode(b"?QQ==") == b"A"  # what a lenient decode would produce

    class LenientScanner(Osc52Scanner):
        @staticmethod
        def _decode(payload):
            return base64.b64decode(payload)  # the relaxation this guards against

    assert LenientScanner().feed(b"\x1b]52;c;?QQ==\x07") == []
    # and the decode layer alone refuses it too, with the guard bypassed
    assert Osc52Scanner()._decode(b"?QQ==") is None


def test_invalid_base64_is_dropped():
    assert Osc52Scanner().feed(b"\x1b]52;c;not!valid!base64\x07") == []


def test_unknown_selection_is_dropped():
    """Cut buffers s0-s7 are deliberately not honoured."""
    assert Osc52Scanner().feed(sequence(b"x", selection="s0")) == []


def test_an_empty_selection_means_clipboard():
    assert Osc52Scanner().feed(sequence(b"x", selection="")) == [("c", b"x")]


def test_an_oversized_payload_is_refused():
    scanner = Osc52Scanner(max_payload=64)

    assert scanner.feed(sequence(b"x" * 500)) == []


def test_an_unterminated_sequence_does_not_buffer_without_limit():
    """A remote host must not be able to make the relay grow memory forever."""
    scanner = Osc52Scanner(max_payload=1024)

    for _ in range(50):
        scanner.feed(b"\x1b]52;c;" + b"A" * 4096)

    assert len(scanner._pending) <= 8192


def test_plain_output_produces_nothing_and_holds_almost_no_state():
    scanner = Osc52Scanner()

    assert scanner.feed(b"ordinary terminal output\r\n" * 100) == []
    assert len(scanner._pending) < len(b"\x1b]52;")


def test_an_introducer_split_across_the_boundary_is_recognised():
    scanner = Osc52Scanner()
    stream = sequence(b"edge")

    assert scanner.feed(stream[:3]) == []
    assert scanner.feed(stream[3:]) == [("c", b"edge")]


def test_empty_feed_is_harmless():
    assert Osc52Scanner().feed(b"") == []


def test_default_max_payload_is_bounded():
    assert 0 < MAX_PAYLOAD <= 1 << 24


# -- GCM side: relay wiring and clipboard application ------------------------


# -- the edges of each rule (#337) ---------------------------------------------


def test_a_write_of_exactly_the_cap_is_taken():
    assert Osc52Scanner(max_payload=4).feed(sequence(b"AB")) == [("c", b"AB")]


def test_an_unterminated_write_of_exactly_the_cap_is_still_waited_for():
    scanner = Osc52Scanner(max_payload=6)

    assert scanner.feed(b"\x1b]52;c;QUI=") == []
    assert scanner.feed(b"\x07") == [("c", b"AB")]


def test_a_write_after_an_oversized_unterminated_one_is_still_found():
    scanner = Osc52Scanner(max_payload=6)

    assert scanner.feed(b"\x1b]52;c;" + b"A" * 10 + b"\x1b]52;c;QUI=") == []
    assert scanner.feed(b"\x07") == [("c", b"AB")]


def test_two_writes_ended_by_st_in_one_chunk_are_both_found():
    st = b"\x1b\\"

    assert Osc52Scanner().feed(
        sequence(b"one", terminator=st) + sequence(b"two", terminator=st)
    ) == [
        ("c", b"one"),
        ("c", b"two"),
    ]


@pytest.mark.parametrize("terminator", [b"\x07", b"\x1b\\"])
@pytest.mark.parametrize(("body", "writes"), [(b"", []), (b"c", []), (b"c;", [("c", b"")])])
def test_a_short_sequence_does_not_hide_the_write_after_it(terminator, body, writes):
    """Empty, a selection alone, and an empty write, which empties the clipboard."""
    chunk = b"\x1b]52;" + body + terminator + sequence(b"AB", terminator=terminator)

    assert Osc52Scanner().feed(chunk) == [*writes, ("c", b"AB")]


def test_only_the_first_semicolon_ends_the_selection():
    """What follows it is the payload, whole, and here that is not base64."""
    assert Osc52Scanner().feed(b"\x1b]52;c;QUI=;QUI=\x07") == []


def test_a_write_naming_two_selections_goes_to_the_first_honoured():
    assert Osc52Scanner().feed(sequence(b"AB", selection="pc")) == [("p", b"AB")]


def test_a_selection_that_is_not_ascii_is_ignored():
    """A remote host's bytes, which must not raise out of the relay."""
    assert Osc52Scanner().feed(b"\x1b]52;\xff;QUI=\x07") == []


def test_relay_command_wraps_the_original_argv(app_module):
    wrapped = app_module.relay_command(["ssh", "host"], "/run/clip.sock")

    assert wrapped == [
        *childpython.module_command("gnome_connection_manager.relay"),
        "--clipboard-socket",
        "/run/clip.sock",
        "--",
        "ssh",
        "host",
    ]
    assert wrapped[0].endswith("python") or "python" in wrapped[0]


def _message(text, selection="c"):
    return json.dumps(
        {"selection": selection, "data": base64.b64encode(text.encode()).decode()}
    ).encode()


# What /proc/sys/kernel/osrelease says on the machine WSLg runs on.
WSL_KERNEL = "6.18.33.2-microsoft-standard-WSL2"


def on_a_wsl_machine(app_module, monkeypatch):
    """Whatever this machine is, the kernel names Microsoft and the WSLg folder is there.

    A write is watched only where GCM's display is a Wayland one as well (#412). So a test
    whose display is not says the same on a machine that is not WSL as on one that is: the
    machine that could change its answer is the one set up."""
    monkeypatch.setattr(app_module.osc52, "kernel_release", lambda: WSL_KERNEL)
    monkeypatch.setattr(app_module.osc52, "wslg_folder", lambda: True)


def test_a_relayed_write_reaches_the_clipboard(app_module, monkeypatch):
    on_a_wsl_machine(app_module, monkeypatch)
    monkeypatch.setattr(app_module.conf, "OSC52_ENABLED", 1)
    captured: dict = {}
    monkeypatch.setattr(
        app_module.Gtk.Clipboard,
        "get_default",
        lambda *_a: types.SimpleNamespace(set_text=lambda t, n: captured.setdefault("text", t)),
        raising=False,
    )
    monkeypatch.setattr(app_module.Gdk.Display, "get_default", lambda: object(), raising=False)
    wmain = object.__new__(app_module.Wmain)

    assert wmain._apply_clipboard_message(_message("copied by the application")) is True
    assert captured["text"] == "copied by the application"


def test_a_relayed_write_is_refused_when_the_preference_is_off(app_module, monkeypatch):
    """A session started while it was on must lose the ability the moment it is off."""
    on_a_wsl_machine(app_module, monkeypatch)
    monkeypatch.setattr(app_module.conf, "OSC52_ENABLED", 0)
    calls = []
    monkeypatch.setattr(
        app_module.Gtk.Clipboard,
        "get_default",
        lambda *_a: types.SimpleNamespace(set_text=lambda t, n: calls.append(t)),
        raising=False,
    )
    wmain = object.__new__(app_module.Wmain)

    assert wmain._apply_clipboard_message(_message("should not land")) is False
    assert calls == []


@pytest.mark.parametrize(
    "line",
    [
        b"not json",
        b"{}",
        b'{"data": "not!base64"}',
        # decodes cleanly only if validation is off: a lenient decode drops the "!"
        # and yields b"abcdef", so this is what proves validate=True is in force
        b'{"data": "YWJj!ZGVm"}',
        b'{"data": ""}',
        b"",
        b'{"data": null}',
    ],
)
def test_malformed_relay_messages_are_discarded(app_module, monkeypatch, line):
    on_a_wsl_machine(app_module, monkeypatch)
    monkeypatch.setattr(app_module.conf, "OSC52_ENABLED", 1)
    calls = []
    monkeypatch.setattr(
        app_module.Gtk.Clipboard,
        "get_default",
        lambda *_a: types.SimpleNamespace(set_text=lambda t, n: calls.append(t)),
        raising=False,
    )
    wmain = object.__new__(app_module.Wmain)

    assert wmain._apply_clipboard_message(line) is False
    assert calls == []


def test_spawning_is_untouched_when_the_preference_is_off(app_module):
    """The default path must carry none of the relay's risk.

    Read with inspect rather than by slicing the file: module-level functions are
    followed by indented defs, so splitting on "\ndef " swallows the rest of the module
    and the assertions below stop meaning anything.
    """
    body = inspect.getsource(app_module.vte_run)

    assert "conf.OSC52_ENABLED and controller" in body, "the relay must be gated on the preference"
    assert body.index("socket_path = ") < body.index("if TERMINAL_V048")
    assert body.count("relay_command(") == 1


_RELAY_SCRIPT = """
import base64, json, os, socket, subprocess, sys, tempfile, threading, time

sock_dir = tempfile.mkdtemp()
sock_path = os.path.join(sock_dir, "clip.sock")
server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
server.bind(sock_path); server.listen(4)
got = []

def accept():
    conn, _ = server.accept()
    buf = b""
    while True:
        data = conn.recv(4096)
        if not data:
            break
        buf += data
        while b"\\n" in buf:
            line, buf = buf.split(b"\\n", 1)
            got.append(json.loads(line))
    conn.close()

t = threading.Thread(target=accept, daemon=True)
t.start()

payload = base64.b64encode(b"relayed-clipboard").decode()
script = (
    "printf 'before\\\\n'; "
    "printf '\\\\033]52;c;" + payload + "\\\\a'; "
    "printf 'after\\\\n'; "
    "exit 7"
)
proc = subprocess.run(
    [sys.executable, "-m", "gnome_connection_manager.relay",
     "--clipboard-socket", sock_path, "--", "/bin/sh", "-c", script],
    capture_output=True, timeout=60,
)
t.join(timeout=5)

assert proc.returncode == 7, proc.returncode
out = proc.stdout.decode("utf-8", "replace")
assert "before" in out and "after" in out, repr(out)
assert got, "no clipboard message reached the socket"
assert base64.b64decode(got[0]["data"]) == b"relayed-clipboard", got
assert got[0]["selection"] == "c"
print("OK")
"""


@pytest.mark.skipif(not hasattr(os, "openpty"), reason="needs pty support")
def test_the_relay_forwards_output_captures_osc52_and_propagates_exit_status():
    """End to end through a real pty, in a clean interpreter.

    conftest stubs gi for the whole session, and the relay imports the package, so
    this runs out of process for the same reason the buffer viewer test does.
    """
    result = subprocess.run(
        [sys.executable, "-c", _RELAY_SCRIPT],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
        timeout=120,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert "OK" in result.stdout


# -- raw session recording (#69) --------------------------------------------


def test_relay_command_passes_only_the_destinations_that_are_wanted(app_module):
    """Each flag appears only when its feature is on, so the relay does no idle work."""
    both = app_module.relay_command(["sh"], "/run/clip.sock", "/logs/a.raw")
    assert both[-3:] == ["--", "sh"] or both[-2:] == ["--", "sh"]
    assert "--clipboard-socket" in both and "--raw-log" in both

    clip_only = app_module.relay_command(["sh"], "/run/clip.sock", None)
    assert "--clipboard-socket" in clip_only
    assert "--raw-log" not in clip_only

    raw_only = app_module.relay_command(["sh"], None, "/logs/a.raw")
    assert "--raw-log" in raw_only
    assert "--clipboard-socket" not in raw_only

    neither = app_module.relay_command(["sh"])
    assert neither[-2:] == ["--", "sh"]
    assert "--clipboard-socket" not in neither and "--raw-log" not in neither


def test_session_file_shares_the_text_log_identity(tmp_path, app_module, monkeypatch):
    monkeypatch.setattr(app_module.conf, "LOG_PATH", str(tmp_path))
    monkeypatch.setattr(app_module.time, "strftime", lambda fmt: "20260823")
    terminal = types.SimpleNamespace(
        host=types.SimpleNamespace(group="Work", name="web-01", user="root", host="10.0.0.5")
    )

    path = app_module.session_file_for(terminal, ".raw")

    assert path == str(tmp_path / "Work" / "web-01" / "root-20260823-001.raw")
    assert (tmp_path / "Work" / "web-01").is_dir()


def test_spawning_stays_untouched_when_neither_feature_is_on(app_module):
    """Both preferences off must mean the relay is not in the path at all."""
    body = inspect.getsource(app_module.vte_run)

    assert "conf.OSC52_ENABLED and controller" in body
    assert "conf.RAW_SESSION_LOG" in body, "raw recording must be gated too"
    assert "if socket_path or raw_path:" in body
    assert body.count("relay_command(") == 1


@pytest.mark.skipif(not hasattr(os, "openpty"), reason="needs pty support")
def test_the_relay_records_the_raw_stream():
    """Captures every redraw, keeps attributes, and never takes the session down."""
    check = Path(__file__).resolve().parent / "helpers" / "raw_relay_check.py"
    result = subprocess.run(
        [sys.executable, str(check)],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        timeout=120,
    )

    assert result.returncode == 0, result.stderr[-2500:]
    assert "RAW-OK" in result.stdout


def test_raw_recorder_releases_its_handle(tmp_path):
    """Opened unbuffered, so nothing is lost without a close -- but the fd would leak."""
    from gnome_connection_manager.relay import RawRecorder

    target = tmp_path / "session.raw"
    recorder = RawRecorder(str(target))
    recorder.write(b"chunk")

    assert target.read_bytes() == b"chunk"

    recorder.close()
    assert recorder._handle is None
    recorder.close()  # idempotent
    recorder.write(b"after close")  # must not raise
    assert target.read_bytes() == b"chunk"


def test_raw_recorder_without_a_path_is_inert(tmp_path):
    from gnome_connection_manager.relay import RawRecorder

    recorder = RawRecorder(None)
    recorder.write(b"nowhere")
    recorder.close()

    assert list(tmp_path.iterdir()) == []


def test_raw_recorder_survives_an_unwritable_destination():
    """A logging failure must never take the session down."""
    from gnome_connection_manager.relay import RawRecorder

    recorder = RawRecorder("/proc/nonexistent-dir/session.raw")
    recorder.write(b"still fine")
    recorder.close()


def test_the_relay_closes_the_recorder():
    from gnome_connection_manager import relay as relay_module

    body = inspect.getsource(relay_module.relay)

    assert "recorder.close()" in body
    assert body.index("finally:") < body.index("recorder.close()")


# -- recordings need timing to be replayable (#74) ---------------------------


def test_timing_path_sits_beside_the_recording(app_module):
    assert app_module.timing_path_for("/logs/Work/web-01/root-20260823-001.raw") == (
        "/logs/Work/web-01/root-20260823-001.timing"
    )


def test_relay_command_asks_for_timing_whenever_it_asks_for_a_recording(app_module):
    """A recording without timing cannot be replayed frame by frame, only read."""
    command = app_module.relay_command(["sh"], None, "/logs/a.raw")

    assert "--raw-log" in command
    assert "--timing-log" in command
    assert command[command.index("--timing-log") + 1] == "/logs/a.timing"


def test_relay_command_asks_for_no_timing_without_a_recording(app_module):
    assert "--timing-log" not in app_module.relay_command(["sh"], "/run/clip.sock", None)


def test_recorder_writes_a_timing_line_per_chunk(tmp_path):
    from gnome_connection_manager.relay import RawRecorder

    raw, timing = tmp_path / "s.raw", tmp_path / "s.timing"
    recorder = RawRecorder(str(raw), str(timing))
    for chunk in (b"first", b"second chunk", b"3"):
        recorder.write(chunk)
    recorder.close()

    lines = timing.read_text().splitlines()
    assert len(lines) == 3
    assert [int(line.split()[1]) for line in lines] == [5, 12, 1]
    assert lines[0].split()[0] == "0.000000", "the first chunk has no delay to report"


def test_each_timing_line_is_on_disk_as_soon_as_its_chunk_is(tmp_path):
    """A tab's menu offers Save Transcript while its session still runs, and a timing
    line still in a buffer would leave its chunk without a boundary (#337)."""
    from gnome_connection_manager.relay import RawRecorder

    raw, timing = tmp_path / "s.raw", tmp_path / "s.timing"
    recorder = RawRecorder(str(raw), str(timing))
    recorder.write(b"live")
    try:
        assert timing.read_text().split()[1:] == ["4"]
    finally:
        recorder.close()


def test_timing_accounts_for_every_byte_of_the_recording(tmp_path):
    """The counts are what let a replayer cut the stream back into the original writes."""
    from gnome_connection_manager.relay import RawRecorder

    raw, timing = tmp_path / "s.raw", tmp_path / "s.timing"
    recorder = RawRecorder(str(raw), str(timing))
    written = [b"alpha\n", b"\x1b[H\x1b[2Jframe\n", b"tail"]
    for chunk in written:
        recorder.write(chunk)
    recorder.close()

    sizes = [int(line.split()[1]) for line in timing.read_text().splitlines()]
    assert sum(sizes) == raw.stat().st_size

    data, offset, rebuilt = raw.read_bytes(), 0, []
    for size in sizes:
        rebuilt.append(data[offset : offset + size])
        offset += size
    assert rebuilt == written
    assert offset == len(data)


def test_a_second_recorder_carries_on_in_the_same_files(tmp_path):
    """A reconnect records into the files its tab began, so opening them must not
    truncate either one, and the timing has to go on accounting for every byte (#200)."""
    from gnome_connection_manager.relay import RawRecorder

    raw, timing = tmp_path / "s.raw", tmp_path / "s.timing"
    written = [b"first connection\r\n", b"logout\r\n", b"second connection\r\n"]
    first = RawRecorder(str(raw), str(timing))
    for chunk in written[:2]:
        first.write(chunk)
    first.close()
    second = RawRecorder(str(raw), str(timing))
    second.write(written[2])
    second.close()

    assert raw.read_bytes() == b"".join(written)
    sizes = [int(line.split()[1]) for line in timing.read_text().splitlines()]
    assert sizes == [len(chunk) for chunk in written]


def test_a_recording_without_timing_still_records(tmp_path):
    from gnome_connection_manager.relay import RawRecorder

    raw = tmp_path / "s.raw"
    recorder = RawRecorder(str(raw), None)
    recorder.write(b"still here")
    recorder.close()

    assert raw.read_bytes() == b"still here"


def test_an_unwritable_timing_file_does_not_stop_the_recording(tmp_path):
    from gnome_connection_manager.relay import RawRecorder

    raw = tmp_path / "s.raw"
    recorder = RawRecorder(str(raw), "/proc/nonexistent-dir/s.timing")
    recorder.write(b"recorded anyway")
    recorder.close()

    assert raw.read_bytes() == b"recorded anyway"


class FailingHandle:
    """A file that accepts one write then starts failing, like a full disk."""

    def __init__(self, fail_after=0):
        self.writes = []
        self._fail_after = fail_after
        self.closed = False

    def write(self, data):
        if len(self.writes) >= self._fail_after:
            raise OSError("no space left on device")
        self.writes.append(data)

    def close(self):
        self.closed = True


def test_no_timing_line_is_written_for_a_chunk_that_was_not_recorded(tmp_path):
    """Otherwise the timing desyncs from the data and the offsets stop lining up."""
    from gnome_connection_manager.relay import RawRecorder

    recorder = RawRecorder(str(tmp_path / "s.raw"), str(tmp_path / "s.timing"))
    timing = FailingHandle(fail_after=99)
    recorder._handle = FailingHandle(fail_after=0)
    recorder._timing = timing

    recorder.write(b"never lands")

    assert timing.writes == [], "timing must not record a chunk the data write rejected"


def test_closing_releases_the_timing_file_too(tmp_path):
    from gnome_connection_manager.relay import RawRecorder

    recorder = RawRecorder(str(tmp_path / "s.raw"), str(tmp_path / "s.timing"))
    assert recorder._timing is not None

    recorder.close()

    assert recorder._timing is None
    assert recorder._handle is None
    recorder.close()  # idempotent


def test_a_timing_write_failure_leaves_the_recording_running(tmp_path):
    """A logging failure must never take the session down -- including the timing half."""
    from gnome_connection_manager.relay import RawRecorder

    raw = tmp_path / "s.raw"
    recorder = RawRecorder(str(raw), str(tmp_path / "s.timing"))
    recorder._timing = FailingHandle(fail_after=0)

    recorder.write(b"recorded regardless")
    recorder.write(b" and this too")
    recorder.close()

    assert recorder._timing is None, "the broken timing file should be dropped"
    assert raw.read_bytes() == b"recorded regardless and this too"


def test_delays_reflect_the_gap_between_chunks(tmp_path):
    """The byte counts alone cut the stream up; the delays are what replay it at speed."""
    from gnome_connection_manager.relay import RawRecorder

    recorder = RawRecorder(str(tmp_path / "s.raw"), str(tmp_path / "s.timing"))
    recorder.write(b"first")
    time.sleep(0.05)
    recorder.write(b"second")
    recorder.close()

    delays = [float(line.split()[0]) for line in (tmp_path / "s.timing").read_text().splitlines()]

    assert delays[0] == 0.0, "nothing precedes the first chunk"
    # generous bounds: this asserts the delay is measured, not that the clock is precise
    assert 0.02 < delays[1] < 5.0, delays


# -- relayed ssh/telnet sessions must still spawn (#91) -----------------------


def test_plain_argv_undoes_the_argv_zero_repeat(app_module):
    """FILE_AND_ARGV_ZERO repeats the command; an ordinary argv must not."""
    args = ["/path/ssh.expect", "/path/ssh.expect", "ssh", "-l", "me"]

    assert app_module.plain_argv(args, True) == ["/path/ssh.expect", "ssh", "-l", "me"]


def test_plain_argv_leaves_an_ordinary_argv_alone(app_module):
    """A local shell is spawned with DEFAULT, so nothing there is repeated."""
    args = ["env", "-u", "VIRTUAL_ENV", "/bin/bash"]

    assert app_module.plain_argv(args, False) == args


def test_plain_argv_survives_an_argv_with_nothing_to_drop(app_module):
    assert app_module.plain_argv(["/bin/telnet"], True) == ["/bin/telnet"]


def spawn_an_ssh_session(app_module, monkeypatch, tmp_path, recording=1):
    """Run vte_run for an ssh host and return the argv and flags it spawns with."""
    captured = {}

    class Terminal:
        def __init__(self):
            self.host = type("Host", (), {"term": ""})()

        def spawn_async(self, *args, **_kwargs):
            captured["argv"], captured["flags"] = args[2], args[4]

        def spawn_sync(self, *args, **_kwargs):
            captured["argv"], captured["flags"] = args[2], args[4]
            return True, 4321  # as VTE's: whether it spawned, and the child's pid

    # The real flags are an IntFlag; the stub's are opaque, so give them values that
    # survive the `|` and can be told apart.
    monkeypatch.setattr(app_module.GLib.SpawnFlags, "DEFAULT", 1)
    monkeypatch.setattr(app_module.GLib.SpawnFlags, "FILE_AND_ARGV_ZERO", 2)
    monkeypatch.setattr(app_module.GLib.SpawnFlags, "SEARCH_PATH", 4)
    for name in ("MAJOR_VERSION", "MINOR_VERSION", "MICRO_VERSION"):
        monkeypatch.setattr(app_module.Vte, name, 0)
    monkeypatch.setattr(app_module.conf, "RAW_SESSION_LOG", recording)
    monkeypatch.setattr(app_module.conf, "OSC52_ENABLED", 0)
    monkeypatch.setattr(app_module, "session_file_for", lambda _t, s: str(tmp_path / ("s" + s)))

    # Exactly what the ssh path passes: the command, then an arg list repeating it.
    app_module.vte_run(Terminal(), "/path/ssh.expect", ["/path/ssh.expect", "ssh", "-l", "me"])
    return captured


def test_a_relayed_ssh_session_is_spawned_with_a_literal_argv(app_module, monkeypatch, tmp_path):
    """FILE_AND_ARGV_ZERO would eat the relay's `-c` as the child's argv[0].

    Python then reads the bootstrap as a script path, relative to the spawn
    directory, and the session dies with "can't open file '$HOME/...'" (#91). The first
    argument after the interpreter was `-m` then, and is `-c` since #415.
    """
    spawned = spawn_an_ssh_session(app_module, monkeypatch, tmp_path)

    assert spawned["flags"] & 2 == 0, "FILE_AND_ARGV_ZERO would swallow the relay's -c"
    assert spawned["argv"][1] == "-c", "the relay's own argv must survive intact"


def test_a_relayed_ssh_session_hands_the_relay_an_ordinary_inner_argv(
    app_module, monkeypatch, tmp_path
):
    """The relay execs the inner command itself, so the argv-zero repeat must go.

    Left in, `ssh.expect` reads its own path where it expects the connection type.
    """
    spawned = spawn_an_ssh_session(app_module, monkeypatch, tmp_path)
    inner = spawned["argv"][spawned["argv"].index("--") + 1 :]

    assert inner == ["/path/ssh.expect", "ssh", "-l", "me"]


def test_an_unrelayed_ssh_session_still_gets_the_argv_zero_convention(
    app_module, monkeypatch, tmp_path
):
    """With no preference on, the spawn must be exactly what it always was."""
    spawned = spawn_an_ssh_session(app_module, monkeypatch, tmp_path, recording=0)

    assert spawned["flags"] & 2, "FILE_AND_ARGV_ZERO carries the child's argv[0]"
    assert spawned["argv"] == ["/path/ssh.expect", "/path/ssh.expect", "ssh", "-l", "me"]


def test_the_relay_hands_on_the_argv_the_child_would_have_had():
    """End to end on a real pty: the relay must be transparent to the inner argv."""
    check = Path(__file__).resolve().parent / "helpers" / "relay_argv_check.py"
    result = subprocess.run(
        [sys.executable, str(check)],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        timeout=120,
    )

    assert result.returncode == 0, result.stdout + result.stderr[-2000:]
    assert "RELAY-ARGV-OK" in result.stdout


# -- resizing (#319) ---------------------------------------------------------

# Reports the size it starts at, and each SIGWINCH with the size it then reads, and
# otherwise waits: after READY nothing it does passes through the relay. It writes with
# os.write, not print: a SIGWINCH landing inside a buffered print re-entered it and
# raised "reentrant call inside BufferedWriter", so the program died (#478).
_IDLE_PROGRAM = """
import fcntl, os, signal, struct, sys, termios, time

def size():
    rows, cols = struct.unpack("HHHH", fcntl.ioctl(0, termios.TIOCGWINSZ, b"\\0" * 8))[:2]
    return f"{rows}x{cols}"

def on_winch(*_):
    os.write(1, f"WINCH {size()}\\n".encode())

signal.signal(signal.SIGWINCH, on_winch)
os.write(1, f"READY {size()}\\n".encode())
time.sleep(60)
"""


def _relay_an_idle_program(rows, cols):
    """The relay on a pty of `rows` and `cols`, running `_IDLE_PROGRAM`, and the pty."""
    master, slave = os.openpty()
    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    process = subprocess.Popen(
        [sys.executable, "-m", "gnome_connection_manager.relay", "--"]
        + [sys.executable, "-c", _IDLE_PROGRAM],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
        # The pty as the relay's controlling terminal, as VTE gives a tab: only then does
        # a change of its size send the relay SIGWINCH.
        start_new_session=True,
        preexec_fn=lambda: fcntl.ioctl(0, termios.TIOCSCTTY, 0),
    )
    os.close(slave)
    return process, master


def _read_until(master, text, seconds):
    """What the pty shows until `text` is among it, or `seconds` have passed."""
    seen = b""
    deadline = time.monotonic() + seconds
    while text.encode() not in seen:
        ready, _, _ = select.select([master], [], [], max(deadline - time.monotonic(), 0))
        if not ready:
            break
        try:
            chunk = os.read(master, 4096)
        except OSError:  # EIO: the relay has gone
            break
        if not chunk:
            break
        seen += chunk
    return seen.decode(errors="replace")


@pytest.mark.skipif(not hasattr(os, "openpty"), reason="needs pty support")
def test_the_relayed_program_starts_at_the_terminals_size():
    process, master = _relay_an_idle_program(33, 111)
    try:
        seen = _read_until(master, "READY", 30)
    finally:
        process.kill()
        process.wait()
        os.close(master)

    assert "READY 33x111" in seen, seen


@pytest.mark.skipif(not hasattr(os, "openpty"), reason="needs pty support")
def test_each_resize_reaches_an_idle_program_under_the_relay():
    """With no key typed and no output. The relay passed a resize on only when a byte
    next went through it, in either direction, so an idle program never had it (#319).
    Twice, as a new tab changes its size twice as it settles."""
    process, master = _relay_an_idle_program(24, 80)
    try:
        started = _read_until(master, "READY", 30)
        reached = []
        for rows, cols in ((30, 100), (40, 120)):
            fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
            reached.append(_read_until(master, f"WINCH {rows}x{cols}", 5))
    finally:
        process.kill()
        process.wait()
        os.close(master)

    assert "READY 24x80" in started, started
    assert "WINCH 30x100" in reached[0], reached
    assert "WINCH 40x120" in reached[1], reached


# -- a copy written twice is one copy (#393) -------------------------------------
#
# A program in a tab writes each copy as a pair: the text for the target "" and again for
# "c". GCM put both on the clipboard, and the second set follows no input that GCM
# received, which Weston ignores without a word to GTK. GTK then answered every paste with
# GCM's text, and a copy made in Windows did not reach it.


def test_a_pair_of_writes_of_one_text_reaches_the_scanner_as_two_alike():
    """The scanner reads "" as "c", so nothing after it can tell the two writes apart.
    That is why GCM tells a repeat by its text and its time, and not by its target."""
    stream = sequence(b"copied", selection="") + sequence(b"copied", selection="c")

    assert Osc52Scanner().feed(stream) == [("c", b"copied"), ("c", b"copied")]


def test_the_first_write_is_not_a_repeat():
    assert RepeatFilter().repeated("copied", 100.0) is False


@pytest.mark.parametrize(
    ("gap", "repeat"),
    [
        (0.0, True),  # a pair handled in one go
        (0.0034, True),  # the gap of the pairs measured in two reads
        (0.5, True),  # a main loop that stalled, or a slow link
        (1.5, False),  # a person who copies the same text again
    ],
)
def test_a_write_of_the_same_text_is_a_repeat_for_about_a_second(gap, repeat):
    """The default window, which these times put between 0.5 s and 1.5 s."""
    repeats = RepeatFilter()
    repeats.repeated("copied", 100.0)

    assert repeats.repeated("copied", 100.0 + gap) is repeat


@pytest.mark.parametrize(("gap", "repeat"), [(1.0, True), (3.0, True), (4.0, False), (9.0, False)])
def test_a_write_is_a_repeat_until_exactly_one_window_after_the_one_let_through(gap, repeat):
    """Times that a float holds exactly, so that the edge is the edge: a window of 4 s,
    from 10 s."""
    repeats = RepeatFilter(window=4.0)
    repeats.repeated("copied", 10.0)

    assert repeats.repeated("copied", 10.0 + gap) is repeat


def test_a_different_text_is_never_a_repeat():
    repeats = RepeatFilter()
    repeats.repeated("one", 100.0)

    assert repeats.repeated("two", 100.0) is False


def test_only_the_write_just_before_counts():
    """A, B, A is three copies. A new write repeats the last one let through, no earlier."""
    repeats = RepeatFilter()

    assert [repeats.repeated(text, 100.0) for text in "ABA"] == [False, False, False]


def test_a_repeat_does_not_renew_the_window():
    """Let through at 10 s, left out at 12 s, and let through again at 14 s: a window of
    4 s after the first, not after the repeat. Otherwise a program that wrote one text
    every 2 s would be left out for good."""
    repeats = RepeatFilter(window=4.0)

    assert [repeats.repeated("copied", at) for at in (10.0, 12.0, 14.0)] == [False, True, False]


def test_the_window_restarts_from_each_write_let_through():
    repeats = RepeatFilter(window=4.0)

    answers = [repeats.repeated("copied", at) for at in (10.0, 14.0, 16.0, 18.0)]

    assert answers == [False, False, True, False]


@pytest.mark.parametrize(("window", "repeat"), [(0.5, False), (2.0, True)])
def test_the_window_is_the_one_given(window, repeat):
    """1.5 s after, which the default window of about a second would call a new copy."""
    repeats = RepeatFilter(window=window)
    repeats.repeated("copied", 100.0)

    assert repeats.repeated("copied", 101.5) is repeat


def test_the_window_is_about_a_second():
    """Pinned apart from its behaviour, as MAX_PAYLOAD is. Long enough for a pair 3.4 ms
    apart, a main loop that stalls and a slow link; short of the time a person takes to
    copy again, which is an estimate and not a measurement."""
    assert 0.5 <= REPEAT_WINDOW < 1.5


class EventType(enum.Enum):
    """Gdk.EventType as far as GCM's event handler goes: the three it acts on, and some it must
    not. A real enum, so that no test leans on the stub's Gdk, which gives any name an attribute.
    `test_the_fakes_offer_only_what_gdk_and_gtk_have` holds each name to the real enum."""

    FOCUS_CHANGE = enum.auto()
    SELECTION_REQUEST = enum.auto()
    SELECTION_CLEAR = enum.auto()
    KEY_PRESS = enum.auto()
    KEY_RELEASE = enum.auto()
    BUTTON_PRESS = enum.auto()
    BUTTON_RELEASE = enum.auto()
    MOTION_NOTIFY = enum.auto()
    ENTER_NOTIFY = enum.auto()
    LEAVE_NOTIFY = enum.auto()
    SCROLL = enum.auto()


def gdk_event(kind, entered=None, selection=None):
    """A stand-in for a Gdk.Event, with what GCM reads of its kind: `focus_change.in_`, and
    `selection.selection.name()`.

    Never a real Gdk.Event with its fields written from Python: that killed the interpreter
    with SIGSEGV, measured. The scenario against real GTK has real ones."""
    event = types.SimpleNamespace(type=kind)
    if entered is not None:
        event.focus_change = types.SimpleNamespace(in_=int(entered))
    if selection is not None:
        event.selection = types.SimpleNamespace(
            selection=types.SimpleNamespace(name=lambda: selection)
        )
    return event


def bare_display():
    """What the older tests give for a display: no type at all."""
    return object()


def display_of(kind):
    """A display of the given GDK type, as far as GCM asks of one: the name of its GType."""

    def display():
        return types.SimpleNamespace(__gtype__=types.SimpleNamespace(name=kind))

    return display


class Clipboard:
    """GCM's clipboard and clock as a test sees them: every set, and the time.

    The machine is a WSL one whatever it is, and what decides is the display, as it does for
    GCM, so that a test says the same on any machine. A display of `None` leaves the stub's own.

    `log` is the order of what GTK was given and what the clipboard was set to: the three
    functions of GDK and GTK that GCM calls for the watch are replaced, `Gdk.EventType` by a
    real enum, and `installed` holds each handler GCM gave GDK. `deliver` hands an event to the
    last one, as GDK does, `after` seconds on.
    """

    def __init__(
        self,
        app_module,
        monkeypatch,
        caplog,
        display=bare_display,
        kernel=WSL_KERNEL,
        folder=True,
    ):
        self.sets: list[str] = []
        self.log: list[tuple] = []
        self.installed: list = []
        self.now = 100.0
        self.caplog = caplog
        # What runs inside Gtk.main_do_event, for a test that has it run a main loop of its own.
        self.inside_main_do_event = None
        self.wmain = object.__new__(app_module.Wmain)
        monkeypatch.setattr(app_module.conf, "OSC52_ENABLED", 1)
        monkeypatch.setattr(app_module.time, "monotonic", lambda: self.now)
        monkeypatch.setattr(app_module.osc52, "kernel_release", lambda: kernel)
        monkeypatch.setattr(app_module.osc52, "wslg_folder", lambda: folder)
        if display is not None:
            monkeypatch.setattr(app_module.Gdk.Display, "get_default", display, raising=False)
        monkeypatch.setattr(
            app_module.Gtk.Clipboard,
            "get_default",
            lambda *_a: types.SimpleNamespace(set_text=self._set_text),
            raising=False,
        )
        monkeypatch.setattr(app_module.Gdk, "EventType", EventType, raising=False)
        monkeypatch.setattr(
            app_module.Gdk,
            "event_handler_set",
            lambda handler, data=None: self.installed.append(handler),
            raising=False,
        )
        monkeypatch.setattr(app_module.Gtk, "main_do_event", self._main_do_event, raising=False)

    def _set_text(self, text, _length):
        self.sets.append(text)
        self.log.append(("set", text))

    def _main_do_event(self, event):
        self.log.append(("event", event.type))
        if self.inside_main_do_event is not None:
            self.inside_main_do_event(event)

    def write(self, text, after=0.0):
        """What GCM answers to a write of `text`, `after` seconds after the one before."""
        self.now += after
        return self.wmain._apply_clipboard_message(_message(text))

    def faults(self):
        """What GCM logged as a fault, which it does where an event must go on regardless."""
        return [
            record.getMessage() for record in self.caplog.records if record.levelno >= logging.ERROR
        ]

    def deliver(self, event, after=0.0, faults=0):
        """Hand `event` to the handler GCM installed, `after` seconds after the last thing, and
        say how many faults it logged: none, unless the test expects some."""
        assert self.installed, "GCM gave GDK no event handler"
        self.now += after
        before = len(self.faults())
        self.installed[-1](event, None)
        assert len(self.faults()) - before == faults, self.faults()

    def focus(self, entered, after=0.0, faults=0):
        """The keyboard entering or leaving a GCM window."""
        self.deliver(gdk_event(EventType.FOCUS_CHANGE, entered=entered), after, faults)

    def request(self, selection="CLIPBOARD", after=0.0):
        """The compositor asking for the text, which is how a set taken shows."""
        self.deliver(gdk_event(EventType.SELECTION_REQUEST, selection=selection), after)

    def clear(self, selection="CLIPBOARD", after=0.0):
        """Another client taking the selection from GCM."""
        self.deliver(gdk_event(EventType.SELECTION_CLEAR, selection=selection), after)


@pytest.fixture
def clipboard(app_module, monkeypatch, caplog):
    """Off WSLg, as the older tests have it: a display with no type, on a WSL machine."""
    return Clipboard(app_module, monkeypatch, caplog)


@pytest.fixture
def wslg(app_module, monkeypatch, caplog):
    """Under WSLg: a Wayland display, a kernel that names Microsoft, and the WSLg folder."""
    return Clipboard(app_module, monkeypatch, caplog, display=display_of("GdkWaylandDisplay"))


@pytest.mark.parametrize("gap", [0.0, 0.0034])
def test_a_pair_of_writes_sets_the_clipboard_once(clipboard, gap):
    answers = [clipboard.write("copied"), clipboard.write("copied", after=gap)]

    assert answers == [True, False]
    assert clipboard.sets == ["copied"]


def test_two_texts_close_together_are_both_set(clipboard):
    answers = [clipboard.write("one"), clipboard.write("two", after=0.0034)]

    assert answers == [True, True]
    assert clipboard.sets == ["one", "two"]


def test_the_same_text_a_window_later_is_a_copy_of_its_own(clipboard):
    clipboard.write("copied")
    clipboard.write("copied", after=REPEAT_WINDOW)

    assert clipboard.sets == ["copied", "copied"]


def test_a_text_written_again_after_another_is_set_again(clipboard):
    for text in "ABA":
        clipboard.write(text)

    assert clipboard.sets == ["A", "B", "A"]


def test_a_write_refused_for_the_preference_is_not_remembered(app_module, clipboard, monkeypatch):
    """Otherwise the same text, written once the preference is on, would be left out."""
    monkeypatch.setattr(app_module.conf, "OSC52_ENABLED", 0)
    assert clipboard.write("copied") is False
    monkeypatch.setattr(app_module.conf, "OSC52_ENABLED", 1)

    assert clipboard.write("copied") is True
    assert clipboard.sets == ["copied"]


@pytest.mark.parametrize("line", [b"not json", b"{}", b'{"data": ""}'])
def test_a_line_that_sets_nothing_does_not_stand_in_the_way_of_the_next_write(clipboard, line):
    assert clipboard.wmain._apply_clipboard_message(line) is False

    assert clipboard.write("copied") is True
    assert clipboard.sets == ["copied"]


def test_two_windows_do_not_share_the_last_write(app_module, clipboard):
    """Tests build a Wmain at a time, and a filter on the class would carry one's last write
    into the next."""
    other = object.__new__(app_module.Wmain)
    clipboard.write("copied")

    assert other._apply_clipboard_message(_message("copied")) is True
    assert clipboard.sets == ["copied", "copied"]


def test_the_two_lines_of_a_pair_read_together_set_the_clipboard_once(
    app_module, clipboard, monkeypatch
):
    """The relay sends a pair's lines back to back, and the socket often gives GCM both in
    one read."""
    monkeypatch.setattr(app_module.GLib, "IO_HUP", 16, raising=False)
    line = _message("copied") + b"\n"
    ours, theirs = socket.socketpair()
    with ours, theirs:
        theirs.sendall(line + line)

        keep_watching = clipboard.wmain._on_clipboard_data(ours, bytearray(), 0)

    assert keep_watching is True
    assert clipboard.sets == ["copied"]


# -- a write the compositor ignored is set again (#412, #413) ---------------------------------
#
# GTK sets each new data source with the serial of the last input GCM saw, and under WSLg
# Weston ignores a set whose serial is not newer than the selection's, with no word to GTK. A
# write that follows a copy made in Windows, or another write, with no input to GCM between,
# was ignored: Windows kept the older text, and GCM pasted the write. A ClipboardWatch holds
# the write until the compositor has asked for its text, and GCM sets it again when the
# keyboard next enters or leaves one of its windows, whose serial is newer.
#
# Times are floats a binary fraction holds exactly, so that the edge is the edge: a gap of
# 0.25 s from 10.0 s.


def test_nothing_made_gives_nothing_again():
    assert ClipboardWatch().again(10.0) is None


def test_hearing_with_nothing_made_is_harmless():
    watch = ClipboardWatch()
    watch.heard()

    assert watch.again(10.0) is None


@pytest.mark.parametrize(
    ("later", "text"),
    [(10.0, None), (10.2, None), (10.25, "copied"), (10.5, "copied"), (60.0, "copied")],
)
def test_a_write_is_given_again_from_exactly_one_gap_after_the_set(later, text):
    watch = ClipboardWatch()
    watch.made("copied", 10.0)

    assert watch.again(later) == text


def test_a_write_refused_for_the_gap_is_still_held():
    watch = ClipboardWatch()
    watch.made("copied", 10.0)

    assert [watch.again(10.0), watch.again(10.2)] == [None, None]
    assert watch.again(10.25) == "copied"


def test_a_set_given_starts_the_gap_again_and_counts_with_the_first():
    """Made at 10.0, given at 10.25 and 10.5: three sets, and none at 10.75 although a gap has
    passed since the last. Nor at 10.25 a second time, which is no time since the set it gave."""
    watch = ClipboardWatch()
    watch.made("copied", 10.0)

    answers = [watch.again(at) for at in (10.25, 10.25, 10.5, 10.75, 99.0)]

    assert answers == ["copied", None, "copied", None, None]


def test_the_count_alone_stops_the_repairs():
    """A gap far past each time, so that nothing but the count can refuse."""
    watch = ClipboardWatch()
    watch.made("copied", 10.0)

    assert [watch.again(at) for at in (20.0, 30.0, 40.0, 50.0)] == ["copied", "copied", None, None]


def test_a_write_heard_is_not_given_again():
    watch = ClipboardWatch()
    watch.made("copied", 10.0)
    watch.heard()

    assert watch.again(20.0) is None


def test_a_write_heard_after_a_set_given_is_not_given_again():
    watch = ClipboardWatch()
    watch.made("copied", 10.0)
    assert watch.again(20.0) == "copied"
    watch.heard()

    assert watch.again(30.0) is None


def test_a_newer_write_replaces_the_one_held_and_starts_the_count_and_the_gap_again():
    watch = ClipboardWatch()
    watch.made("old", 10.0)
    assert [watch.again(at) for at in (20.0, 30.0, 40.0)] == ["old", "old", None]

    watch.made("new", 50.0)

    assert watch.again(50.125) is None
    assert [watch.again(at) for at in (60.0, 70.0, 80.0)] == ["new", "new", None]


def test_a_write_made_after_one_was_heard_is_held():
    watch = ClipboardWatch()
    watch.made("one", 10.0)
    watch.heard()
    watch.made("two", 20.0)

    assert watch.again(30.0) == "two"


@pytest.mark.parametrize(("max_sets", "given"), [(1, 0), (2, 1), (3, 2), (5, 4)])
def test_the_sets_are_counted_with_the_first_included(max_sets, given):
    watch = ClipboardWatch(max_sets=max_sets)
    watch.made("copied", 10.0)

    answers = [watch.again(10.0 + step) for step in range(1, 11)]

    assert answers == ["copied"] * given + [None] * (10 - given)


@pytest.mark.parametrize(
    ("gap", "at", "text"), [(4.0, 13.0, None), (4.0, 14.0, "copied"), (0.0, 10.0, "copied")]
)
def test_the_gap_is_the_one_given(gap, at, text):
    watch = ClipboardWatch(gap=gap)
    watch.made("copied", 10.0)

    assert watch.again(at) == text


def test_the_limits_are_the_ones_the_repair_was_measured_with():
    """Pinned apart from their behaviour, as REPEAT_WINDOW is. Three sets, the write's and two
    repairs, where the prototype's first repair was always taken. The gap is about five times
    the longest wait measured from a set to the compositor's request for its text, 52.9 ms:
    a margin, and not a measured threshold."""
    assert MAX_SETS == 3
    assert REPAIR_GAP == 0.25


@pytest.mark.parametrize(
    ("display", "kernel", "folder", "wslg"),
    [
        ("GdkWaylandDisplay", "6.18.33.2-microsoft-standard-WSL2", True, True),
        ("GdkWaylandDisplay", "4.4.0-19041-Microsoft", True, True),
        ("GdkWaylandDisplay", "6.8.0-generic", True, False),
        ("GdkWaylandDisplay", "", True, False),
        ("GdkWaylandDisplay", "6.18.33.2-microsoft-standard-WSL2", False, False),
        ("GdkX11Display", "6.18.33.2-microsoft-standard-WSL2", True, False),
        ("GdkBroadwayDisplay", "6.18.33.2-microsoft-standard-WSL2", True, False),
        ("", "6.18.33.2-microsoft-standard-WSL2", True, False),
        ("gdkwaylanddisplay", "6.18.33.2-microsoft-standard-WSL2", True, False),
        ("GdkWaylandDisplay2", "6.18.33.2-microsoft-standard-WSL2", True, False),
    ],
)
def test_wslg_is_a_wayland_display_on_a_kernel_that_names_microsoft_with_the_folder(
    display, kernel, folder, wslg
):
    """All three, and the display's type exactly: the compositor measured is WSLg's Weston."""
    assert under_wslg(display, kernel, folder) is wslg


def test_the_kernel_release_is_what_uname_gives():
    assert kernel_release() == os.uname().release


def test_a_kernel_release_file_is_read_without_the_newline_proc_ends_it_with(tmp_path):
    release = tmp_path / "osrelease"
    release.write_text(WSL_KERNEL + "\n")

    assert kernel_release(release) == WSL_KERNEL
    assert kernel_release(str(release)) == WSL_KERNEL


def test_a_kernel_release_that_cannot_be_read_is_empty(tmp_path):
    unreadable = tmp_path / "bytes"
    unreadable.write_bytes(b"\xff\xfe\xfa")

    assert kernel_release(tmp_path / "missing") == ""
    assert kernel_release(tmp_path) == ""  # a folder, which cannot be read as a file
    assert kernel_release(unreadable) == ""  # not text


def test_the_wslg_folder_is_a_folder_that_is_there(tmp_path):
    a_file = tmp_path / "wslg"
    a_file.write_text("")

    assert wslg_folder(tmp_path) is True
    assert wslg_folder(str(tmp_path)) is True
    assert wslg_folder(tmp_path / "missing") is False
    assert wslg_folder(a_file) is False


def test_a_path_the_system_refuses_is_not_the_wslg_folder():
    """A name too long for the file system: an error from the stat, not a missing path."""
    assert wslg_folder("/" + "a" * 5000) is False


def test_the_defaults_name_the_places_linux_and_wsl_keep_these_in():
    assert KERNEL_RELEASE_FILE == "/proc/sys/kernel/osrelease"
    assert WSLG_FOLDER == "/mnt/wslg"
    assert wslg_folder() is Path(WSLG_FOLDER).is_dir()


# -- GCM sets such a write again ---------------------------------------------------------------


def test_the_fakes_offer_only_what_gdk_and_gtk_have():
    """The stub's Gdk gives any name an attribute, so a fake can offer what GDK lacks, as
    #30 and #41 did. This is the real one, not the stub."""
    gi = pytest.importorskip("gi", reason="PyGObject not available")
    gi.require_version("Gdk", "3.0")
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gdk, Gtk

    for name in EventType.__members__:
        assert hasattr(Gdk.EventType, name), name
    assert hasattr(Gdk, "event_handler_set")
    assert hasattr(Gtk, "main_do_event")
    for owner, name in [
        (Gdk.Event, "type"),
        (Gdk.Event, "focus_change"),
        (Gdk.EventFocus, "in_"),
        (Gdk.Event, "selection"),
        (Gdk.EventSelection, "selection"),
        (Gdk.Atom, "name"),
    ]:
        assert hasattr(owner, name), (owner, name)
    assert Gdk.SELECTION_CLIPBOARD.name() == "CLIPBOARD"


@pytest.mark.parametrize(
    "machine",
    [
        pytest.param({"display": bare_display}, id="a display with no type"),
        pytest.param({"display": None}, id="the stub's own display"),
        pytest.param({"display": display_of("GdkX11Display")}, id="an X11 display"),
        pytest.param(
            {"display": display_of("GdkWaylandDisplay"), "kernel": "6.8.0-generic"},
            id="Wayland on a kernel that is not WSL's",
        ),
        pytest.param(
            {"display": display_of("GdkWaylandDisplay"), "folder": False},
            id="Wayland on a WSL kernel without the WSLg folder",
        ),
    ],
)
def test_off_wslg_a_write_is_set_once_and_nothing_is_watched(
    app_module, monkeypatch, caplog, machine
):
    clipboard = Clipboard(app_module, monkeypatch, caplog, **machine)

    answers = [clipboard.write("one"), clipboard.write("two", after=2.0)]

    assert answers == [True, True]
    assert clipboard.sets == ["one", "two"]
    assert clipboard.wmain.clipboard_watch() is None
    assert clipboard.installed == []
    # And an event that reached GCM anyway is nothing to it.
    clipboard.now += 2.0
    clipboard.wmain.follow_clipboard(gdk_event(EventType.FOCUS_CHANGE, entered=True))
    assert clipboard.sets == ["one", "two"]


def test_under_wslg_a_write_is_set_at_once_and_watched(wslg):
    assert wslg.write("from the tab") is True

    assert wslg.sets == ["from the tab"]
    # It was the write that gave GDK the handler, and not the call below.
    assert wslg.installed == [wslg.wmain.watch_gdk_event]
    assert wslg.wmain.clipboard_watch() is not None


def test_gdk_is_given_gcms_handler_once_however_many_writes_follow(wslg):
    for text in ("one", "two", "three"):
        wslg.write(text, after=2.0)

    assert wslg.installed == [wslg.wmain.watch_gdk_event]


@pytest.mark.parametrize("display", [bare_display, display_of("GdkWaylandDisplay")])
def test_the_machine_is_asked_once_whatever_the_answer(app_module, monkeypatch, caplog, display):
    """Off WSLg too, or every write would read the kernel and look for the folder again."""
    clipboard = Clipboard(app_module, monkeypatch, caplog, display=display)
    asked = []
    monkeypatch.setattr(app_module.osc52, "kernel_release", lambda: asked.append("k") or WSL_KERNEL)
    monkeypatch.setattr(app_module.osc52, "wslg_folder", lambda: asked.append("f") or True)

    for text in ("one", "two", "three"):
        clipboard.write(text, after=2.0)

    assert asked == ["k", "f"]


def test_two_windows_do_not_share_a_watch(app_module, wslg):
    """A Wmain built without new() has nothing of its own, and one on the class would carry a
    write from one window to the next."""
    other = object.__new__(app_module.Wmain)
    wslg.write("copied")

    assert other.clipboard_watch() is not wslg.wmain.clipboard_watch()


def test_a_fault_in_giving_gdk_the_handler_leaves_the_write_set(
    app_module, wslg, monkeypatch, caplog
):
    attempts = []

    def refuse(handler, data=None):
        attempts.append(handler)
        raise RuntimeError("GDK would not take it")

    monkeypatch.setattr(app_module.Gdk, "event_handler_set", refuse, raising=False)

    answers = [wslg.write("one"), wslg.write("two", after=2.0)]

    assert answers == [True, True]
    assert wslg.sets == ["one", "two"]
    assert wslg.wmain.clipboard_watch() is None
    assert len(attempts) == 1  # once, and not again at the next write
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == [
        "Could not watch GDK's events; an ignored OSC 52 write stays so"
    ]


def test_a_write_the_compositor_never_asked_for_is_set_again_when_the_keyboard_leaves(wslg):
    """#412: a copy in Windows with no input to GCM since, then the tab writes. Weston ignores
    the set, nothing asks for the text, and the next time the keyboard leaves GCM it is set
    again, with a serial newer than the copy's. GTK has handled the event first."""
    text = "from the tab"
    wslg.write(text)

    wslg.focus(False, after=2.0)

    assert wslg.sets == [text, text]
    assert wslg.log == [("set", text), ("event", EventType.FOCUS_CHANGE), ("set", text)]
    # This time the compositor takes it and asks for the text, and the next change of window
    # sets nothing: the control for the one above, which set on the same events.
    wslg.request(after=0.0625)
    wslg.focus(True, after=1.0)
    assert wslg.sets == [text, text]


def test_a_second_write_of_another_text_with_no_input_between_is_set_again(wslg):
    """#413: the first is taken and asked for, the second 2 s later is ignored."""
    wslg.write("first")
    wslg.request(after=0.0625)
    wslg.write("second", after=2.0)

    wslg.focus(True, after=1.0)

    assert wslg.sets == ["first", "second", "second"]


def test_a_second_write_of_the_same_text_more_than_a_window_later_is_set_again(wslg):
    """#413: RepeatFilter lets it through, being 2 s after the first, and Weston ignores it."""
    wslg.write("copied")
    wslg.request(after=0.0625)
    assert wslg.write("copied", after=2.0) is True

    wslg.focus(False, after=1.0)

    assert wslg.sets == ["copied", "copied", "copied"]


@pytest.mark.parametrize("entered", [True, False])
def test_the_keyboard_entering_or_leaving_a_window_sets_the_write_again(wslg, entered):
    wslg.write("copied")

    wslg.focus(entered, after=1.0)

    assert wslg.sets == ["copied", "copied"]


@pytest.mark.parametrize(
    ("heard", "sets"),
    [
        pytest.param("request", 1, id="the compositor asked for the text"),
        pytest.param("clear", 1, id="another client took the clipboard"),
        pytest.param(None, MAX_SETS, id="nothing heard, the control"),
    ],
)
def test_a_write_is_set_again_until_it_is_asked_for_or_the_claim_ends(wslg, heard, sets):
    """Three changes of window, 1 s apart. A write nobody asked for is set again at each until
    the count stops it; one whose set was taken, or whose claim ended, is not."""
    wslg.write("copied")
    if heard:
        getattr(wslg, heard)(after=0.0625)

    for entered in (True, False, True):
        wslg.focus(entered, after=1.0)

    assert len(wslg.sets) == sets


@pytest.mark.parametrize(
    ("kind", "selection", "forgets"),
    [
        ("request", "CLIPBOARD", True),
        ("clear", "CLIPBOARD", True),
        ("request", "PRIMARY", False),
        ("clear", "PRIMARY", False),
        ("request", "SECONDARY", False),
        ("clear", "SECONDARY", False),
    ],
)
def test_only_the_clipboard_selection_ends_the_watch(wslg, kind, selection, forgets):
    wslg.write("copied")

    getattr(wslg, kind)(selection, after=0.0625)
    wslg.focus(True, after=1.0)

    assert wslg.sets == (["copied"] if forgets else ["copied", "copied"])


def test_a_write_unheard_is_set_at_most_the_limit_in_all(wslg):
    wslg.write("copied")

    for step in range(12):
        wslg.focus(step % 2 == 0, after=1.0)

    assert len(wslg.sets) == MAX_SETS


def test_two_changes_of_window_at_the_same_instant_set_once(wslg):
    wslg.write("copied")

    wslg.focus(False, after=2.0)
    wslg.focus(True)  # the other window's, as the keyboard moves between two of GCM's

    assert wslg.sets == ["copied", "copied"]


def test_a_change_of_window_one_gap_after_a_repair_sets_again(wslg):
    wslg.write("copied")
    wslg.focus(False, after=2.0)

    wslg.focus(True, after=REPAIR_GAP)

    assert wslg.sets == ["copied"] * 3


def test_the_gap_runs_from_the_write_too(wslg):
    """A write applied between two events GDK read together takes the serial of an `enter` or
    `leave` it has not handed out yet, and a repair at that event would set with the same."""
    wslg.write("copied")

    wslg.focus(False, after=0.125)
    assert wslg.sets == ["copied"]

    wslg.focus(True, after=0.125)
    assert wslg.sets == ["copied", "copied"]


@pytest.mark.parametrize("gap", [0.0, 0.0034])
def test_a_pair_of_writes_is_set_once_and_set_again_once(wslg, gap):
    """The pair #393 measured, at once and 3 ms apart: one set, and one more if nobody asks."""
    assert [wslg.write("copied"), wslg.write("copied", after=gap)] == [True, False]

    wslg.focus(False, after=1.0)

    assert wslg.sets == ["copied", "copied"]


def test_a_pair_of_writes_is_remembered_once(wslg):
    """The second of a pair is left out, and with it any claim on the watch: it must not start
    the gap from the second, 0.125 s after the first."""
    assert [wslg.write("copied"), wslg.write("copied", after=0.125)] == [True, False]

    wslg.focus(False, after=0.125)  # a whole gap after the first, short of one after the second

    assert wslg.sets == ["copied", "copied"]


@pytest.mark.parametrize(
    "refused",
    [
        pytest.param(b"not json", id="a message that is not one"),
        pytest.param(b'{"data": ""}', id="an empty text"),
    ],
)
def test_a_write_that_sets_nothing_is_not_held(wslg, refused):
    wslg.write("copied")
    wslg.request(after=0.0625)

    assert wslg.wmain._apply_clipboard_message(refused) is False
    wslg.focus(True, after=1.0)

    assert wslg.sets == ["copied"]


def test_a_write_refused_for_the_preference_is_not_held(app_module, wslg, monkeypatch):
    wslg.write("copied")
    wslg.request(after=0.0625)
    monkeypatch.setattr(app_module.conf, "OSC52_ENABLED", 0)
    assert wslg.write("other", after=1.0) is False
    monkeypatch.setattr(app_module.conf, "OSC52_ENABLED", 1)

    wslg.focus(True, after=1.0)

    assert wslg.sets == ["copied"]


@pytest.mark.parametrize(
    "kind",
    [
        EventType.KEY_PRESS,
        EventType.KEY_RELEASE,
        EventType.BUTTON_PRESS,
        EventType.BUTTON_RELEASE,
        EventType.MOTION_NOTIFY,
        EventType.ENTER_NOTIFY,
        EventType.LEAVE_NOTIFY,
        EventType.SCROLL,
    ],
)
def test_an_event_that_is_no_change_of_the_keyboards_window_sets_nothing(wslg, kind):
    """A copy GCM makes at a key or a click is set first, with its serial and taken, and a
    repair at the same event would destroy that source and set the older text with the same
    serial. So only a change of window repairs: reasoned from the mechanism, not run."""
    wslg.write("copied")

    wslg.deliver(gdk_event(kind), after=1.0)

    assert wslg.sets == ["copied"]
    assert wslg.log[-1] == ("event", kind)  # and GTK was given it
    wslg.focus(True, after=1.0)  # the control: the change of window sets
    assert wslg.sets == ["copied", "copied"]


def test_every_event_goes_to_gtk_before_the_watch_looks_at_it(wslg):
    wslg.write("copied")

    wslg.focus(True, after=1.0)
    wslg.request(after=1.0)

    assert wslg.log == [
        ("set", "copied"),
        ("event", EventType.FOCUS_CHANGE),
        ("set", "copied"),
        ("event", EventType.SELECTION_REQUEST),
    ]


def test_an_event_goes_on_when_the_clipboard_raises(app_module, wslg, monkeypatch, caplog):
    wslg.write("copied")

    def refuse(*_args):
        raise RuntimeError("no clipboard")

    with monkeypatch.context() as broken:
        broken.setattr(app_module.Gtk.Clipboard, "get_default", refuse, raising=False)
        wslg.focus(True, after=1.0, faults=1)
    assert wslg.log[-1] == ("event", EventType.FOCUS_CHANGE)
    assert wslg.faults() == ["Could not follow the clipboard at an event"]

    wslg.focus(False, after=1.0)  # and the next event is handled as any
    assert wslg.sets == ["copied", "copied"]


def test_an_event_goes_on_when_the_watch_raises(wslg, monkeypatch):
    wslg.write("copied")

    def refuse(_now):
        raise RuntimeError("the watch is broken")

    monkeypatch.setattr(wslg.wmain.clipboard_watch(), "again", refuse)

    wslg.focus(True, after=1.0, faults=1)

    assert wslg.log[-1] == ("event", EventType.FOCUS_CHANGE)
    assert wslg.sets == ["copied"]


def test_a_nested_main_loop_handing_in_an_event_leaves_the_sets_as_they_were(wslg):
    """dialog.run() runs a main loop of its own inside the handling of the key that opened it,
    and the keyboard moving to the dialog reaches GCM's handler from there. The watch runs
    after Gtk.main_do_event returns, so that is safe: GTK is given each event in the order it
    came, and the one change of window sets the write once."""
    wslg.write("copied")
    key = gdk_event(EventType.KEY_PRESS)
    dialog_takes_the_keyboard = gdk_event(EventType.FOCUS_CHANGE, entered=False)
    handed_in: list = []

    def run_a_main_loop(event):
        if event is key:
            handed_in.append(event)
            wslg.installed[-1](dialog_takes_the_keyboard, None)

    wslg.inside_main_do_event = run_a_main_loop

    wslg.deliver(key, after=1.0)

    assert handed_in == [key]
    assert wslg.log == [
        ("set", "copied"),
        ("event", EventType.KEY_PRESS),
        ("event", EventType.FOCUS_CHANGE),
        ("set", "copied"),
    ]


def test_with_the_preference_off_the_write_is_forgotten(app_module, wslg, monkeypatch):
    """A session started while it was on must stop writing the moment it is off, and a write
    not set again then is not set again once it is on either, until a new write comes."""
    wslg.write("copied")
    monkeypatch.setattr(app_module.conf, "OSC52_ENABLED", 0)
    wslg.focus(False, after=1.0)
    monkeypatch.setattr(app_module.conf, "OSC52_ENABLED", 1)

    wslg.focus(True, after=1.0)

    assert wslg.sets == ["copied"]
    wslg.write("new", after=1.0)
    wslg.focus(False, after=1.0)  # the control: a new write is held, and set again
    assert wslg.sets == ["copied", "new", "new"]


# -- and against real GTK ----------------------------------------------------------------------
#
# GCM as GCM starts, on an Xvfb of its own, with real events: a second program pasting raises a
# SELECTION_REQUEST, a second program taking the clipboard raises a SELECTION_CLEAR, and
# Gdk.Window.focus on a second window raises the FOCUS_CHANGEs of the keyboard leaving one and
# entering the other. Measured on a private Xvfb with no window manager. The display is X11, so
# the scenario forces the answer the WSLg predicate gives, and then leaves it: the same moves
# must set nothing where it is not WSLg.

REPO = Path(__file__).resolve().parents[1]

_REAL_GTK_SCRIPT = r"""
import base64, faulthandler, json, os, subprocess, sys, tempfile, time
faulthandler.dump_traceback_later(100, exit=True)
mode = sys.argv[1]
os.environ["HOME"] = tempfile.mkdtemp(); os.environ["SHELL"] = "/bin/sh"; sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gdk, Gtk
from gnome_connection_manager import app
from gnome_connection_manager.utils import osc52

app.conf.CHECK_UPDATES = False
app.conf.STARTUP_LOCAL = False
app.conf.OSC52_ENABLED = 1
repairs = mode == "under-wslg"
if repairs:
    # Called through the module, so that the patch reaches GCM.
    osc52.under_wslg = lambda *_args: True

# Every set of the clipboard, by the real method. The first thing checked is that this is hit.
sets = []
real_set_text = Gtk.Clipboard.set_text
def recorded(self, text, length=-1):
    sets.append(text)
    return real_set_text(self, text, length)
Gtk.Clipboard.set_text = recorded

application = app.GcmApplication()
assert application.register(None)
application.activate()
w = application._controller
main = w.wMain
main.move(0, 0)
main.resize(800, 600)

def pump(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        Gtk.main_iteration_do(False)
        time.sleep(0.005)

def until(condition, seconds=10):
    end = time.monotonic() + seconds
    while time.monotonic() < end and not condition():
        Gtk.main_iteration_do(False)
        time.sleep(0.005)
    return condition()

# A second window to move the keyboard to. Its focus-in-event runs after the window's own, which
# is what sets has_toplevel_focus, and it can only run if GCM gave the event to GTK.
other = Gtk.Window(title="the other window")
other.set_default_size(300, 200)
entered = []
def focus_in(_widget, _event):
    entered.append(other.has_toplevel_focus())
    return False
other.connect_after("focus-in-event", focus_in)
other.show_all()
pump(0.5)
assert main.has_toplevel_focus(), "GCM's window has not got the keyboard"

def write(text):
    message = {"selection": "c", "data": base64.b64encode(text.encode()).decode()}
    assert w._apply_clipboard_message(json.dumps(message).encode()) is True

def move_keyboard():
    # To the other window, or back: GDK reports the window it leaves and the window it enters.
    target = other if main.has_toplevel_focus() else main
    target.get_window().focus(Gdk.CURRENT_TIME)
    assert until(target.has_toplevel_focus), "the keyboard did not move"
    pump(0.4)

def run_aside(program):
    # Another program on the same display, while GCM's main loop runs: it pastes, or copies.
    child = subprocess.Popen(
        [sys.executable, "-I", "-c", program],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    assert until(lambda: child.poll() is not None, 30), "the other program did not end"
    out, err = child.communicate()
    assert child.returncode == 0, err
    return out.strip()

READER = '''
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk
print(Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text())
'''
THIEF = '''
import gi, time
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk
Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text("taken by another program", -1)
end = time.monotonic() + 0.3
while time.monotonic() < end:
    Gtk.main_iteration_do(False)
    time.sleep(0.01)
'''

def expect(label, mark, again):
    # What was set since `mark`: the write's text once more where GCM sets it again, else nothing.
    assert sets[mark:] == again, (label, sets)

# 1. A write nobody asks for, and the keyboard leaving 0.4 s on: set again where WSLg.
write("one")
assert sets == ["one"], "the write did not reach the real set_text: " + repr(sets)
pump(0.4)
mark = len(sets)
move_keyboard()
expect("the keyboard moved", mark, ["one"] if repairs else [])
assert entered == [True], "GTK was not given the focus change: " + repr(entered)

# 2. A write that another program pastes: the request is heard, and nothing is set again.
write("two")
pump(0.4)
assert run_aside(READER) == "two", "the paste did not get the write"
pump(0.4)
mark = len(sets)
move_keyboard()
expect("after a paste", mark, [])

# 3. The control for 2 and 4: a fresh write that nobody pastes or takes is set again.
write("three")
pump(0.4)
mark = len(sets)
move_keyboard()
expect("the control, nothing heard", mark, ["three"] if repairs else [])

# 4. A write whose claim another program ends by taking the clipboard: nothing is set again.
write("four")
pump(0.4)
run_aside(THIEF)
pump(0.4)
mark = len(sets)
move_keyboard()
expect("after another program took the clipboard", mark, [])

assert (w.clipboard_watch() is not None) == repairs, w.clipboard_watch()
main.destroy()
print("OK")
"""


def run_real_gtk_scenario(mode, display):
    """Run the scenario for `mode` on `display`; fail on what it raised or GLib complained of."""
    environment = dict(os.environ, DISPLAY=display, GDK_BACKEND="x11")
    for name in ("WAYLAND_DISPLAY", "GDK_SCALE", "GDK_DPI_SCALE", "XDG_CONFIG_HOME"):
        environment.pop(name, None)
    # A GCM started from another's tab inherits where that one found its files, and a
    # worktree's would then run the main checkout's.
    for name in ("GCM_DATA_DIR", "GCM_GLADE_DIR", "GCM_SCRIPTS_DIR"):
        environment.pop(name, None)
    result = subprocess.run(
        [sys.executable, "-c", _REAL_GTK_SCRIPT, mode],
        capture_output=True,
        text=True,
        cwd=REPO,
        env=environment,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-3000:]
    assert "OK" in result.stdout
    # PyGObject prints what a signal handler raises, and carries on; so does GCM's own handler,
    # which logs a fault and goes on with the next event.
    assert "Traceback" not in result.stderr, result.stderr[-3000:]
    assert glib_complaints(result.stderr) == []


@pytest.mark.skipif(shutil.which("Xvfb") is None, reason="needs Xvfb for a display of its own")
@pytest.mark.parametrize("mode", ["under-wslg", "on-x11"])
def test_a_write_the_compositor_ignored_is_set_again_against_real_gtk(mode):
    """Real events on a display of its own: the keyboard moves between two windows, another
    program pastes, another program takes the clipboard. Where it is not WSLg, the same moves
    set nothing."""
    pytest.importorskip("gi", reason="PyGObject not available")
    process, display = _private_display()
    try:
        run_real_gtk_scenario(mode, display)
    finally:
        process.terminate()
        process.wait()
