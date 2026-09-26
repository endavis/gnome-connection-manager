"""When a console that was busy out of sight has gone quiet (#208).

An agent CLI working in a tab nobody is watching gives no sign when it finishes. Of the
four measured -- Claude Code, codex, agy and Copilot CLI, each in a real VTE 0.76 -- only
codex rings the bell. What all four do share is the screen: it changes continuously while
they work, with the longest pause measured at 1.35 s, and not at all while they wait. VTE
reports those changes as ``contents-changed``, so GCM can see them without the relay.

`QuietWatch` turns that into one decision: this console was busy while you were not
looking, and has now been still long enough to call it finished. Output made while the
tab is watched starts it over, so typing a command and switching away does not count as
work finishing out of sight. Neither does a single burst -- a line of a log, a redraw on
resize -- which is what `QUIET_MIN_BUSY` is for.

Pure: the time is an argument, not a clock read, so the rules are tested without GTK and
without waiting.
"""

from __future__ import annotations

# Output must span this long before going quiet counts as something finishing.
QUIET_MIN_BUSY = 1.0


class QuietWatch:
    """One console's output while it is out of sight."""

    def __init__(self):
        self.busy_since: float | None = None
        self.last_output: float | None = None

    @property
    def waiting(self) -> bool:
        """True while output seen out of sight has not yet been settled one way or the other."""
        return self.busy_since is not None

    def output(self, now: float, watched: bool) -> None:
        """Note a change to the screen at `now`. Output the user can see starts over."""
        if watched:
            self.reset()
            return
        if self.busy_since is None:
            self.busy_since = now
        self.last_output = now

    def settled(self, now: float, quiet_seconds: float) -> bool:
        """True, once, when the console was busy and has since been still for `quiet_seconds`.

        Either way the run is over once the quiet period has passed, so the next output
        starts a new one. A `quiet_seconds` of 0 or less is the preference turned off,
        which ends the run too: a caller polling `waiting` then stops.
        """
        if self.busy_since is None or self.last_output is None:
            return False
        if quiet_seconds <= 0:
            self.reset()
            return False
        if now - self.last_output < quiet_seconds:
            return False
        busy = self.last_output - self.busy_since >= QUIET_MIN_BUSY
        self.reset()
        return busy

    def reset(self) -> None:
        """Forget the current run: the user has looked, or it has been settled."""
        self.busy_since = None
        self.last_output = None
