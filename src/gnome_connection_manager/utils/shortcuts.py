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


# Keys that only change what another key types, or lock a mode, by GDK's names for them.
# Pressed alone they are no key to bind, and GDK's `is_modifier` cannot say so: measured
# with real input under X11, it is False for Shift, Control, Alt and Super alike (#239).
MODIFIER_KEY_NAMES = frozenset(
    {
        "Shift_L",
        "Shift_R",
        "Control_L",
        "Control_R",
        "Alt_L",
        "Alt_R",
        "Meta_L",
        "Meta_R",
        "Super_L",
        "Super_R",
        "Hyper_L",
        "Hyper_R",
        "ISO_Level3_Shift",
        "ISO_Level5_Shift",
        "Mode_switch",
        "ISO_Next_Group",
        "ISO_Prev_Group",
        "Caps_Lock",
        "Shift_Lock",
        "Num_Lock",
    }
)


def captured_key(keyval_name, key_name, types_text, held):
    """What a key pressed in a snippet's key field makes that snippet's key (#240): the
    name to bind it to, "" to leave it without one, or None to leave the field as it is.

    `keyval_name` is GDK's name for the key, `key_name` the name GCM binds it by,
    `types_text` whether it types a character, and `held` whether Ctrl, Alt or Super is
    held with it. A modifier alone waits for the key it modifies. Backspace or Delete
    alone clears the key. A key that types text with at most Shift held is refused:
    bound, it would be taken from every console, as Enter or a letter would.
    """
    if keyval_name in MODIFIER_KEY_NAMES:
        return None
    if keyval_name in ("BackSpace", "Delete") and not held:
        return ""
    if types_text and not held:
        return None
    return key_name
