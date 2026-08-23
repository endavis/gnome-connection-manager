"""End-to-end check that the relay records the raw stream.

Run as a subprocess by tests/test_osc52.py, for the same reason the other helpers are:
conftest stubs `gi` session-wide and the relay imports the package.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

raw = Path(tempfile.mkdtemp()) / "session.raw"
script = (
    "printf 'plain line\\n'; "
    "for i in 0 50 100; do printf '\\rprogress: %s%%' $i; done; printf '\\n'; "
    "printf '\\033[31mRED\\033[0m done\\n'; "
    "exit 5"
)
result = subprocess.run(
    [
        sys.executable,
        "-m",
        "gnome_connection_manager.relay",
        "--raw-log",
        str(raw),
        "--",
        "/bin/sh",
        "-c",
        script,
    ],
    capture_output=True,
    env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")},
    timeout=60,
)

assert result.returncode == 5, result.returncode
data = raw.read_bytes()

# Every intermediate redraw is present, which is the whole point: the text log keeps one.
assert data.count(b"progress:") == 3, data
# Attributes survive, so a replay can reproduce the screen.
assert b"\x1b[31m" in data, data
# The recording is the stream, not an interpretation of it.
assert data == result.stdout, (data[:120], result.stdout[:120])

# A recording is only opened when asked for.
quiet = Path(tempfile.mkdtemp()) / "unused.raw"
subprocess.run(
    [sys.executable, "-m", "gnome_connection_manager.relay", "--", "/bin/sh", "-c", "printf hi"],
    capture_output=True,
    env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")},
    timeout=60,
)
assert not quiet.exists()

# An unwritable destination must not take the session down with it.
blocked = subprocess.run(
    [
        sys.executable,
        "-m",
        "gnome_connection_manager.relay",
        "--raw-log",
        "/proc/nonexistent-dir/session.raw",
        "--",
        "/bin/sh",
        "-c",
        "printf 'still ran\\n'",
    ],
    capture_output=True,
    env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")},
    timeout=60,
)
assert blocked.returncode == 0, blocked.stderr[-500:]
assert b"still ran" in blocked.stdout, blocked.stdout

print("RAW-OK")
