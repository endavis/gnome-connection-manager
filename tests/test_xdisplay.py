"""`tests/xdisplay.py` (#509): an Xvfb of a run's own, shared by the suite and the sandbox."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from tests import xdisplay

needs_xvfb = pytest.mark.skipif(shutil.which("Xvfb") is None, reason="needs Xvfb")


def test_holder_reads_the_padded_pid_xvfb_writes(tmp_path: Path) -> None:
    lock = tmp_path / "lock"
    lock.write_text("      1234\n")
    assert xdisplay.holder(lock) == 1234


@pytest.mark.parametrize("content", [None, "", "garbage\n"])
def test_holder_is_none_while_the_lock_names_nobody(tmp_path: Path, content: str | None) -> None:
    lock = tmp_path / "lock"
    if content is not None:
        lock.write_text(content)
    assert xdisplay.holder(lock) is None


def test_lock_file_is_xvfbs() -> None:
    assert xdisplay.lock_file(95) == Path("/tmp/.X95-lock")


def test_free_number_skips_a_number_with_a_lock_file(tmp_path: Path) -> None:
    taken = {90, 91}

    def lock(number: int) -> Path:
        path = tmp_path / f"lock{number}"
        if number in taken:
            path.touch()
        return path

    with (
        patch.object(xdisplay, "lock_file", side_effect=lock),
        patch.object(xdisplay, "is_up", return_value=False),
    ):
        assert xdisplay.free_number() == 92


def test_free_number_skips_a_number_with_a_server(tmp_path: Path) -> None:
    with (
        patch.object(xdisplay, "lock_file", side_effect=lambda n: tmp_path / f"l{n}"),
        patch.object(xdisplay, "is_up", side_effect=lambda n: n == 90),
    ):
        assert xdisplay.free_number() == 91


def test_free_number_is_none_when_every_number_is_taken(tmp_path: Path) -> None:
    with patch.object(xdisplay, "is_up", return_value=True):
        assert xdisplay.free_number() is None


def test_start_is_none_without_xvfb() -> None:
    with patch.object(xdisplay.shutil, "which", return_value=None):
        assert xdisplay.start() is None


@needs_xvfb
def test_start_gives_a_display_that_is_up_and_ours_and_stop_ends_it() -> None:
    started = xdisplay.start()
    assert started is not None
    process, display = started
    try:
        number = int(display.removeprefix(":"))
        assert xdisplay.is_up(number)
        assert xdisplay.holder(xdisplay.lock_file(number)) == process.pid
    finally:
        xdisplay.stop(process)
    assert process.poll() is not None
    assert not xdisplay.is_up(number)
    xdisplay.stop(process)  # safe once it has exited


@needs_xvfb
def test_a_display_whose_lock_names_another_process_is_not_ours() -> None:
    spawned: list[subprocess.Popen[bytes]] = []
    real_popen = subprocess.Popen

    def recording_popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        process = real_popen(*args, **kwargs)  # type: ignore[call-overload]
        spawned.append(process)
        return process  # type: ignore[no-any-return]

    try:
        with (
            patch.object(xdisplay, "ATTEMPTS", 2),
            patch.object(xdisplay, "free_number", side_effect=[95, 96]),
            patch.object(xdisplay, "is_up", return_value=True),
            patch.object(xdisplay, "holder", return_value=-1),
            patch.object(xdisplay.time, "monotonic", side_effect=_fast_clock()),
            patch.object(xdisplay.subprocess, "Popen", side_effect=recording_popen),
        ):
            assert xdisplay.start() is None
        assert len(spawned) == 2, "it tried again"
        assert all(process.poll() is not None for process in spawned), "and left none running"
    finally:
        for process in spawned:
            process.kill()
            process.wait()


def _fast_clock():
    """A clock that jumps 4 s a reading, so a 10 s wait ends in a few."""
    value = 0.0

    def clock() -> float:
        nonlocal value
        value += 4.0
        return value

    return clock


def test_stop_kills_what_will_not_terminate() -> None:
    process = subprocess.Popen(  # noqa: S603
        ["/bin/sh", "-c", "trap '' TERM; echo ready; while :; do sleep 1; done"],
        stdout=subprocess.PIPE,
    )
    try:
        assert process.stdout is not None
        process.stdout.readline()
        xdisplay.stop(process, grace=0.3)
        assert process.poll() is not None
    finally:
        process.kill()
        process.wait()
        if process.stdout:
            process.stdout.close()
