"""Tests for utils/activity.py: when a console busy out of sight counts as finished (#208).

Pure, so these drive `QuietWatch` with explicit times rather than a clock or a terminal.
The end-to-end check against a real VTE is in tests/test_wmain.py.
"""

from __future__ import annotations

from gnome_connection_manager.utils.activity import QUIET_MIN_BUSY, QuietWatch


def _busy(watch: QuietWatch, start: float, seconds: float, step: float = 0.2) -> float:
    """Screen updates every `step` seconds for `seconds`, the way a spinner draws.

    Returns the time of the last update.
    """
    t = last = start
    while t <= start + seconds:
        watch.output(t, watched=False)
        last = t
        t += step
    return last


def test_a_console_busy_out_of_sight_settles_once_it_has_been_still():
    watch = QuietWatch()
    last = _busy(watch, 10.0, 3.0)

    assert watch.settled(last + 4.9, quiet_seconds=5) is False
    assert watch.settled(last + 5.0, quiet_seconds=5) is True


def test_settling_happens_once_per_run():
    watch = QuietWatch()
    last = _busy(watch, 0.0, 2.0)

    assert watch.settled(last + 5, quiet_seconds=5) is True
    assert watch.settled(last + 60, quiet_seconds=5) is False
    assert watch.waiting is False


def test_output_while_waiting_restarts_the_quiet_period():
    watch = QuietWatch()
    last = _busy(watch, 0.0, 2.0)
    watch.output(last + 4, watched=False)

    assert watch.settled(last + 5, quiet_seconds=5) is False
    assert watch.settled(last + 9, quiet_seconds=5) is True


def test_a_single_burst_is_not_work_finishing():
    """One line of a log, or a redraw on resize, is a single update."""
    watch = QuietWatch()
    watch.output(10.0, watched=False)

    assert watch.settled(20.0, quiet_seconds=5) is False
    assert watch.waiting is False  # the run is over either way


def test_output_just_short_of_the_minimum_does_not_count():
    watch = QuietWatch()
    watch.output(0.0, watched=False)
    watch.output(QUIET_MIN_BUSY - 0.01, watched=False)

    assert watch.settled(60.0, quiet_seconds=5) is False


def test_output_spanning_the_minimum_counts():
    watch = QuietWatch()
    watch.output(0.0, watched=False)
    watch.output(QUIET_MIN_BUSY, watched=False)

    assert watch.settled(60.0, quiet_seconds=5) is True


def test_output_the_user_can_see_starts_the_run_over():
    """Typing a command and switching away is not work finishing out of sight."""
    watch = QuietWatch()
    _busy(watch, 0.0, 3.0)
    watch.output(3.5, watched=True)

    assert watch.waiting is False
    assert watch.settled(60.0, quiet_seconds=5) is False


def test_only_output_after_the_user_looks_away_counts():
    watch = QuietWatch()
    watch.output(0.0, watched=True)
    watch.output(0.5, watched=True)
    watch.output(1.0, watched=False)  # switched away just before the last line

    assert watch.settled(60.0, quiet_seconds=5) is False


def test_nothing_settles_before_any_output():
    watch = QuietWatch()

    assert watch.waiting is False
    assert watch.settled(1000.0, quiet_seconds=5) is False


def test_turning_the_preference_off_ends_the_run():
    """A caller polls `waiting`, so a run left open would keep its timer alive for ever."""
    watch = QuietWatch()
    last = _busy(watch, 0.0, 3.0)

    assert watch.settled(last + 60, quiet_seconds=0) is False
    assert watch.waiting is False


def test_reset_forgets_the_run():
    watch = QuietWatch()
    last = _busy(watch, 0.0, 3.0)
    watch.reset()

    assert watch.waiting is False
    assert watch.settled(last + 60, quiet_seconds=5) is False
