"""Tests for OSC 52 extraction.

This is untrusted input by definition -- the bytes come from whatever runs in the
terminal, including a remote host over SSH -- so the negative cases matter as much as
the positive ones.
"""

from __future__ import annotations

import base64
import inspect
import json
import os
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

from gnome_connection_manager.utils.osc52 import MAX_PAYLOAD, Osc52Scanner


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


def test_relay_command_wraps_the_original_argv(app_module):
    wrapped = app_module.relay_command(["ssh", "host"], "/run/clip.sock")

    assert wrapped[1:] == [
        "-m",
        "gnome_connection_manager.relay",
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


def test_a_relayed_write_reaches_the_clipboard(app_module, monkeypatch):
    monkeypatch.setattr(app_module.conf, "OSC52_ENABLED", 1)
    captured = {}
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


def test_next_session_file_takes_the_first_free_number(tmp_path, app_module):
    prefix = tmp_path / "web-01-20260823"
    (tmp_path / "web-01-20260823-001.log").write_text("x")
    (tmp_path / "web-01-20260823-002.log").write_text("x")

    assert app_module.next_session_file(prefix, ".log").endswith("-003.log")


def test_next_session_file_keeps_raw_and_text_numbering_independent(tmp_path, app_module):
    prefix = tmp_path / "web-01-20260823"
    (tmp_path / "web-01-20260823-001.log").write_text("x")

    assert app_module.next_session_file(prefix, ".log").endswith("-002.log")
    assert app_module.next_session_file(prefix, ".raw").endswith("-001.raw")


def test_next_session_file_appends_to_the_last_when_exhausted(tmp_path, app_module, monkeypatch):
    """Refusing to log because 999 sessions happened today would be worse."""
    prefix = tmp_path / "busy-20260823"
    monkeypatch.setattr(app_module.Path, "exists", lambda self: True, raising=False)

    assert app_module.next_session_file(prefix, ".raw").endswith("-999.raw")


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
    """FILE_AND_ARGV_ZERO would eat the relay's `-m` as the child's argv[0].

    Python then reads the module name as a script path, relative to the spawn
    directory, and the session dies with "can't open file '$HOME/...relay'" (#91).
    """
    spawned = spawn_an_ssh_session(app_module, monkeypatch, tmp_path)

    assert spawned["flags"] & 2 == 0, "FILE_AND_ARGV_ZERO would swallow the relay's -m"
    assert spawned["argv"][1] == "-m", "the relay's own argv must survive intact"


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
