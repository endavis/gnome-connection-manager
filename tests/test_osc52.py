"""Tests for OSC 52 extraction.

This is untrusted input by definition -- the bytes come from whatever runs in the
terminal, including a remote host over SSH -- so the negative cases matter as much as
the positive ones.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
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
        app_module.Gtk.Clipboard, "get_default",
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
        app_module.Gtk.Clipboard, "get_default",
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
        app_module.Gtk.Clipboard, "get_default",
        lambda *_a: types.SimpleNamespace(set_text=lambda t, n: calls.append(t)),
        raising=False,
    )
    wmain = object.__new__(app_module.Wmain)

    assert wmain._apply_clipboard_message(line) is False
    assert calls == []


def test_spawning_is_untouched_when_the_preference_is_off(app_module, monkeypatch):
    """The default path must carry none of the relay's risk."""
    source = Path(app_module.__file__).read_text()
    body = source.split("def vte_run", 1)[1].split("\ndef ", 1)[0]

    assert "conf.OSC52_ENABLED and controller" in body, "the relay must be gated on the preference"
    assert body.index("socket_path = ") < body.index("if TERMINAL_V048")
    # and the wrap is the only thing the gate does
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
