"""Does the relay hand the inner command the argv it would have had without it? (#91)

Run as a subprocess by tests/test_osc52.py: it needs a real pty, which pytest's
captured stdio is not.
"""

from __future__ import annotations

import os
import pty
import select
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from gnome_connection_manager.app import plain_argv, relay_command  # noqa: E402

SHOW = """import sys
sys.stderr.write("ARGV=" + repr(sys.argv) + "\\n")
sys.stderr.flush()
"""


def run(argv):
    """Run `argv` on its own pty and return everything it wrote."""
    pid, fd = pty.fork()
    if pid == 0:
        os.execvp(argv[0], argv)
    out = b""
    while True:
        readable, _, _ = select.select([fd], [], [], 10)
        if not readable:
            break
        try:
            chunk = os.read(fd, 65536)
        except OSError:
            break
        if not chunk:
            break
        out += chunk
    os.waitpid(pid, 0)
    return out.decode("utf-8", "replace")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        show = Path(tmp) / "show.py"
        show.write_text(SHOW)
        raw = str(Path(tmp) / "s.raw")

        # What vte_run builds for ssh: FILE_AND_ARGV_ZERO repeats the command, so GLib
        # can use the repeat as the child's argv[0].
        with_repeat = [sys.executable, sys.executable, str(show), "ssh", "-l", "me"]
        # ...and what GLib would then have given the child, which is the yardstick.
        expected = f"ARGV={[str(show), 'ssh', '-l', 'me']!r}"

        relayed = run(relay_command(plain_argv(with_repeat, True), None, raw))
        if expected not in relayed:
            print(f"MISMATCH relayed: wanted {expected!r} in {relayed!r}")
            return 1

        # Left in, the repeat arrives as a real argument and ssh.expect reads its own
        # path where it expects the connection type.
        kept = run(relay_command(with_repeat, None, raw))
        if expected in kept:
            print(f"the repeat was expected to leak through, but did not: {kept!r}")
            return 1

        print("RELAY-ARGV-OK")
        return 0


if __name__ == "__main__":
    sys.exit(main())
