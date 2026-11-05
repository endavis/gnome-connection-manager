"""An Xvfb of a run's own, shared by the test suite and `doit sandbox --xvfb` (#509).

Lives in `tests/`, not `tools/` or `utils/`: `tests/conftest.py` imports it, and mutmut's
copy of the tree has no `tools/`, while `utils/` would ship in the package and be mutated
where no Xvfb runs. `tools/doit/gcm.py` imports it lazily.
"""

from __future__ import annotations

import shutil
import socket
import subprocess  # nosec B404  # runs Xvfb
import time
from pathlib import Path

SCREEN = "1920x1080x24"
ATTEMPTS = 10


def lock_file(number: int) -> Path:
    """The lock file Xvfb writes for display :number, holding its process's id."""
    return Path(f"/tmp/.X{number}-lock")


def is_up(number: int) -> bool:
    """True once display :number accepts a connection.

    Checks the abstract socket first. WSLg mounts /tmp/.X11-unix read-only, so Xvfb
    cannot create the filesystem socket there at all and only the abstract one appears;
    waiting for the path would wait forever. Xvfb's own -displayfd never reports back
    under that same condition, which is why readiness is probed rather than asked for.
    """
    for address in (f"\0/tmp/.X11-unix/X{number}", f"/tmp/.X11-unix/X{number}"):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(address)
            return True
        except OSError:
            continue
        finally:
            sock.close()
    return False


def free_number() -> int | None:
    """The first display number from 90 to 199 with no lock file and no server, or None."""
    for number in range(90, 200):
        if lock_file(number).exists() or is_up(number):
            continue
        return number
    return None


def holder(lock: Path) -> int | None:
    """The process a display's lock file names, or None while it names none yet."""
    try:
        return int(lock.read_text().strip())
    except (OSError, ValueError):
        return None


def start(size: str = SCREEN) -> tuple[subprocess.Popen[bytes], str] | None:
    """Spawn an Xvfb of this run's own and return (process, ":N"), or None.

    The number is chosen free and then bound, and two runs can choose the same one. The
    one that loses sees the other's server come up, and its own exits only once it finds
    the lock taken, which under load took longer than the wait meant for it. Two runs
    then shared a display: each one's keys reached the other's windows, and the first to
    finish took the server down under the other. So a display counts as its own only once
    the lock file Xvfb writes names its own process.
    """
    xvfb = shutil.which("Xvfb")
    if xvfb is None:
        return None
    for _attempt in range(ATTEMPTS):
        number = free_number()
        if number is None:
            break
        try:
            process = subprocess.Popen(  # nosec B603
                [xvfb, f":{number}", "-screen", "0", size, "-nolisten", "tcp"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            return None
        lock = lock_file(number)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and process.poll() is None:
            if is_up(number) and holder(lock) == process.pid:
                return process, f":{number}"
            time.sleep(0.02)
        process.kill()
        process.wait()
    return None


def stop(process: subprocess.Popen[bytes], grace: float = 5.0) -> None:
    """End `process`: terminate, wait `grace` seconds, then kill. Safe once it has exited."""
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
