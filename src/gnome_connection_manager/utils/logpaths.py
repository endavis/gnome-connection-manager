"""Naming and layout for session log files.

Sessions are laid out as ``<log_dir>/<group>/<name>/<user>-<YYYYMMDD>-<NNN>.log`` so the
log tree mirrors the host tree, with ``.raw`` and ``.timing`` siblings under the same
number when raw recording is on. Getting the names right is a containment problem as
much as a cosmetic one: a group is free text that becomes directory segments, and a tab
title arrives over OSC 0/2 from whatever is running in the terminal, including a remote
host.

Two sanitizers, deliberately different: `sanitize_log_name` guards a filesystem path,
`sanitize_tab_title` guards a widget that ends at ``set_markup``. `truncate_tab_label`
is neither: it bounds the whole composed label so a tab does not crowd its neighbours
off the strip, and it is here because it is the same kind of pure decision.

Pure of GTK and of configuration -- the log root is an argument, not a `conf` read -- so
it is tested directly rather than through the `gi` stub in tests/conftest.py (#139). It
does touch the filesystem: existence checks, `resolve()` for the containment check, one
`mkdir`, and the empty file that reserves a session's number.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

_LOG_NAME_UNSAFE = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]+')
LOG_NAME_FALLBACK = "session"
LOG_NAME_MAX = 80


def sanitize_log_name(title):
    """Reduce a tab label to something safe to embed in a filename."""
    name = _LOG_NAME_UNSAFE.sub("_", title or "")
    name = " ".join(name.split())
    # Leading dots hide the file or walk up a directory; trailing dots break on Windows.
    name = name.strip(" ._")
    if len(name) > LOG_NAME_MAX:
        name = name[:LOG_NAME_MAX].rstrip(" ._")
    return name or LOG_NAME_FALLBACK


TAB_TITLE_MAX = 40


def sanitize_tab_title(title):
    """Reduce a program-set window title to something safe to show in a tab.

    Titles arrive over OSC 0/2 from whatever runs in the terminal, including a remote
    host, so this is untrusted input on a path that ends in set_markup. Control
    characters, markup and unbounded length all have to go. Distinct from
    sanitize_log_name: that one guards a filesystem path, this one guards a widget.
    """
    text = "".join(ch for ch in (title or "") if ch.isprintable())
    text = " ".join(text.split())
    if len(text) > TAB_TITLE_MAX:
        text = text[: TAB_TITLE_MAX - 1].rstrip() + "\u2026"
    return text


TAB_LABEL_MAX = 30


def truncate_tab_label(text):
    """Cut a composed tab label down to what a tab strip can show (#190).

    A different job from sanitize_tab_title, which bounds one untrusted title: this
    bounds the whole label, host name and rename included, because a tab is as wide as
    its text and the ones that no longer fit go behind the notebook's scroll arrows.
    Measured at 1400px with twelve consoles open: three tabs reachable at 56 characters,
    five at this cap.

    A cut rather than Pango ellipsis on purpose. An ellipsized label reports the
    ellipsis as its minimum width, which collapses the tab to 34px; giving it
    set_width_chars as a floor then pads every short tab out to the cap, taking a
    ``Local`` tab from 66px to 223px.
    """
    text = text or ""
    if len(text) <= TAB_LABEL_MAX:
        return text
    return text[: TAB_LABEL_MAX - 1].rstrip() + "…"


def sanitize_log_segments(group):
    """Sanitize a group path one segment at a time.

    `/` is in the unsafe set, so sanitising the whole path at once would collapse
    "prod/eu-west" into "prod_eu-west" and flatten the tree we are trying to mirror.
    """
    segments = []
    for part in (group or "").split("/"):
        part = part.strip()
        # Drop "", "." and ".." before sanitising: sanitize_log_name turns them into the
        # fallback name, which would litter the tree with bogus "session" directories.
        if not part or set(part) <= {"."}:
            continue
        segments.append(sanitize_log_name(part))
    return segments


def build_log_prefix(log_dir, group, name, user, stamp):
    """Path prefix for a session log, or None if it would escape `log_dir`.

    Sessions are laid out as <log_dir>/<group>/<name>/<user>-<stamp> so the log tree
    mirrors the host tree. The user is a directory segment rather than part of the
    filename because `name` is free text: no separator character is collision-proof,
    but a path separator cannot be ambiguous once each segment is sanitised.

    sanitize_log_name should make escaping impossible; the containment check is here
    so that a gap in it cannot put the log somewhere the user did not ask for.
    """
    root = Path(log_dir).expanduser()
    directory = root
    for segment in sanitize_log_segments(group):
        directory = directory / segment
    directory = directory / sanitize_log_name(name)
    # Hosts with no user fall back to LOG_NAME_FALLBACK rather than repeating the host
    # name: the parent directory already carries the identity, and repeating it would
    # read as .../infrafoundry/infrafoundry-20260823-001.log. Deliberate -- do not
    # "fix" this by substituting the name.
    prefix = directory / f"{sanitize_log_name(user) if user else LOG_NAME_FALLBACK}-{stamp}"
    try:
        if root.resolve() not in prefix.resolve().parents:
            return None
    except OSError:
        return None
    return prefix


# Every file a session writes. A number is free only while none of them uses it.
SESSION_SUFFIXES = (".log", ".raw", ".timing")


def next_session_stem(prefix, claim):
    """First `<prefix>-NNN` no session file uses yet, falling back to the last on exhaustion.

    One number for all of a session's files. Each file used to take the first number
    free for its own suffix, so a day whose first session was not recorded gave the next
    one 002.log beside 001.raw (#200).

    The number is reserved as it is chosen, by creating the `claim` file -- the one the
    caller is about to write -- empty. The relay creates a recording only once it has
    started, about 35 ms after the spawn, and until then two tabs for one host opened
    together chose the same number and recorded into one file (#202). The create is
    exclusive because GCM is not a unique application: another instance that creates the
    same file between the check and the create keeps the number, and this one moves on.
    Measured with four processes allocating at once, that is no number twice in 600. It
    does not cover two instances claiming different files of one number -- a .log and a
    .raw -- which takes different logging settings for the same host, at the same moment.

    Appending to the final files is deliberate: refusing to log at all because 999
    sessions happened on one day would be worse than a crowded file.
    """
    for index in range(1, 1000):
        stem = f"{prefix}-{index:03d}"
        if any(Path(stem + suffix).exists() for suffix in SESSION_SUFFIXES):
            continue
        try:
            Path(stem + claim).touch(exist_ok=False)
        except FileExistsError:
            continue
        except OSError:
            # Not this function's to report: the caller's own open fails the same way,
            # and says so where it always has.
            pass
        return stem
    return f"{prefix}-999"


def session_stem_for(terminal, log_path, claim):
    """A new session's files, as one path without a suffix, sharing the text log's layout.

    Creates the `claim` file to reserve the number; see `next_session_stem`. None when
    the path would escape `log_path`. That is the caller's to supply -- it
    was `conf.LOG_PATH`, the one thing in this module that read configuration (#139).
    """
    host = getattr(terminal, "host", None)
    prefix = build_log_prefix(
        Path(log_path).expanduser(),
        getattr(host, "group", "") or "",
        getattr(host, "name", "") or "",
        getattr(host, "user", "") or "",
        time.strftime("%Y%m%d"),
    )
    if prefix is None:
        return None
    prefix.parent.mkdir(parents=True, exist_ok=True)
    return next_session_stem(prefix, claim)


def describe_log_session(host):
    """Identity line for the log header: the name plus where it actually connected.

    Kept inside the file so provenance survives the log being moved or renamed.
    """
    name = sanitize_log_name(getattr(host, "name", "") or "")
    target = getattr(host, "host", "") or ""
    if not target:
        return name
    user = getattr(host, "user", "") or ""
    detail = f"{user}@{target}" if user else target
    port = getattr(host, "port", "") or ""
    if port:
        detail = f"{detail}:{port}"
    return f"{name} ({detail})"
