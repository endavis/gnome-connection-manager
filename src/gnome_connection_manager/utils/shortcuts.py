"""Pure helpers for the keyboard-shortcut and font-zoom configuration.

Two decisions that need no widget to make. `parse_custom_keys` turns the ``[keys]``
section of gcm.conf into a mapping of key name to the bytes it should feed the terminal,
refusing anything already bound. `clamp_font_scale` holds a scale factor inside the range
VTE will actually apply.

Pure of GTK and of configuration: the reserved set is an argument rather than a read of
`RESERVED_ACCELERATORS`, which stays in `app.py` beside `SHORTCUT_DEFAULTS` and the
`do_startup` registrations a test checks it against. `shortcut_to_accel` and the rest of
the accelerator machinery stay in `app.py` too -- they are `Gdk` and `Gtk` calls, not
logic, and measurement is what put the seam here rather than around all of them (#140).

The policy these serve is not relocated by the move: an accelerator is derived from the
user's configuration rather than hardcoded, because GTK dispatches window accelerators
before the focused terminal sees the key. A fixed accelerator therefore shadows a
configured one silently, which is how #3 and #15 presented.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("gnome_connection_manager")


def parse_custom_keys(entries, reserved):
    """Turn a [keys] section into {key name: bytes}, dropping what cannot be delivered.

    A binding on a reserved combination is refused at load time rather than ignored at
    press time: the terminal handler never runs for those, so the user would otherwise
    see nothing happen and get no explanation.
    """
    accepted = {}
    for name, value in (entries or {}).items():
        key = (name or "").strip().upper()
        if not key:
            continue
        if key in reserved:
            logger.warning(
                "Ignoring [keys] entry %r: already bound, so it would never reach the terminal",
                key,
            )
            continue
        try:
            sequence = value.encode("utf-8").decode("unicode_escape").encode("latin-1")
        except (UnicodeDecodeError, UnicodeEncodeError):
            logger.warning("Ignoring [keys] entry %r: %r is not a decodable sequence", key, value)
            continue
        if not sequence:
            continue
        accepted[key] = sequence
    return accepted


# VTE clamps set_font_scale() to this range itself (measured on 0.76: 0.1 lands on
# 0.25 and 99.0 on 4.0). Mirroring it here keeps a held-down zoom key from walking
# a scale value that VTE has already stopped honouring.
FONT_SCALE_MIN = 0.25
FONT_SCALE_MAX = 4.0
FONT_SCALE_STEP = 1.1


def clamp_font_scale(scale):
    """Hold a font scale inside the range VTE will actually apply."""
    return min(FONT_SCALE_MAX, max(FONT_SCALE_MIN, scale))
